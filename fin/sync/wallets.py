"""On-chain wallet balances vs ledger. A mismatch becomes a Candidate for review."""

from datetime import date
from decimal import Decimal

import requests

from fin import config, ledger
from fin.models import Candidate

RPC = {"eth": "https://ethereum-rpc.publicnode.com", "base": "https://base-rpc.publicnode.com"}
BTC_API = "https://mempool.space/api/address/"
# Blockbook servers for xpub/zpub accounts (Trezor's LTC one sits behind a Cloudflare challenge)
BLOCKBOOK = {"btc": "https://btc1.trezor.io", "ltc": "https://litecoin.atomicwallet.io"}
COIN = {"btc": "BTC", "ltc": "LTC", "eth": "ETH", "base": "ETH"}
DUST = Decimal("0.00000001")


def _rpc(url: str, method: str, params: list):
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      timeout=30)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(f"{method}: {body['error']}")
    return body["result"]


def _evm_call(url: str, contract: str, data: str) -> int:
    return int(_rpc(url, "eth_call", [{"to": contract, "data": data}, "latest"]), 16)


def balances(w: dict) -> list[tuple[str, str, Decimal]]:
    """[(ledger account, currency, on-chain amount)] for one [[wallets]] entry."""
    chain, addr = w["chain"], w.get("address")
    out = []
    if "xpub" in w:
        r = requests.get(f"{BLOCKBOOK[chain]}/api/v2/xpub/{w['xpub']}", params={"details": "basic"},
                         headers={"User-Agent": "fin/0.1"}, timeout=30)
        r.raise_for_status()
        out.append((w["account"], COIN[chain], Decimal(r.json()["balance"]) / 10**8))
    elif chain == "btc":
        s = requests.get(BTC_API + addr, timeout=30).json()
        sats = sum(s[k]["funded_txo_sum"] - s[k]["spent_txo_sum"]
                   for k in ("chain_stats", "mempool_stats"))
        out.append((w["account"], "BTC", Decimal(sats) / 10**8))
    elif chain in RPC:
        url = RPC[chain]
        wei = int(_rpc(url, "eth_getBalance", [addr, "latest"]), 16)
        out.append((w["account"], "ETH", Decimal(wei) / 10**18))
        for t in w.get("tokens", []):
            raw = _evm_call(url, t["contract"], "0x70a08231" + addr[2:].lower().rjust(64, "0"))
            decimals = t.get("decimals") or _evm_call(url, t["contract"], "0x313ce567")
            out.append((t["account"], t["symbol"], Decimal(raw) / 10**decimals))
    else:
        raise ValueError(f"unknown chain {chain!r}")
    return out


def ledger_units(lg: ledger.Ledger, account: str, currency: str) -> Decimal:
    return sum((p.units.number for t in lg.transactions for p in t.postings
                if p.account == account and p.units.currency == currency), Decimal(0))


def fetch() -> list[Candidate]:
    wallets = config.config().get("wallets", [])
    if not wallets:
        return []
    lg, today, out = ledger.load(), date.today(), []
    for w in wallets:
        for account, cur, onchain in balances(w):
            have = ledger_units(lg, account, cur)
            delta = (onchain - have).quantize(DUST)
            if abs(delta) < DUST:
                continue
            out.append(Candidate(
                source="wallet", external_id=f"wallet:{account}:{today}", date=today,
                payee=f"{w['chain'].upper()} wallet", amount=delta, currency=cur, account=account,
                narration=f"on-chain {onchain.normalize()} {cur}, ledger {have.normalize()} {cur}",
                raw={"onchain": str(onchain), "ledger": str(have),
                     "address": (w.get("address") or w["xpub"])[:8]},
            ))
    return out
