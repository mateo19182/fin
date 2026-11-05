"""Health of every balance-sheet account: how it updates, how fresh it is, does it reconcile."""

from datetime import date, timedelta
from decimal import Decimal

from beancount.core import data

from fin import balances, config, ledger, store
from fin.sync import indexa, revolut_invest

SAVINGS = "Assets:Bank:Revolut:Savings"
RECONCILIATION = "Equity:Reconciliation"
MAX_AGE = {"bank": 2, "wallet": 2, "indexa": 3, "prices": 3, "csv": 35, "manual": 90}
CSV_SOURCES = {"revolut_invest": revolut_invest.SOURCE, "savings_csv": "revolut_savings_csv"}


def _updaters() -> dict[str, tuple[str, str]]:
    """account -> (kind, detail) for every account a sync/import maintains."""
    out = {}
    for key, b in config.section("enable_banking").get("banks", {}).items():
        out[b["account"]] = ("bank", key)
    for w in config.config().get("wallets", []):
        out[w["account"]] = ("wallet", w["chain"])
        for t in w.get("tokens", []):
            out[t["account"]] = ("wallet", w["chain"])
    out[indexa.account()] = ("indexa", indexa.COMMODITY)
    for a in (revolut_invest.STOCKS, revolut_invest.CASH, revolut_invest.TRANSFER):
        out[a] = ("csv", "revolut_invest")
    out[SAVINGS] = ("csv", "savings_csv")
    return out


def _last_dates(lg: ledger.Ledger) -> tuple[dict, dict, dict]:
    """(latest txn date per account, latest date per source meta, latest price per commodity)."""
    by_account: dict[str, date] = {}
    by_source: dict[str, date] = {}
    for t in lg.transactions:
        if (src := t.meta.get("source")):
            by_source[src] = max(by_source.get(src, t.date), t.date)
        for p in t.postings:
            by_account[p.account] = max(by_account.get(p.account, t.date), t.date)
    prices: dict[str, date] = {}
    for e in lg.entries:
        if isinstance(e, data.Price):
            prices[e.currency] = max(prices.get(e.currency, e.date), e.date)
    return by_account, by_source, prices


def _assertion(lg: ledger.Ledger, account: str) -> dict | None:
    checks = [e for e in lg.entries if isinstance(e, data.Balance) and e.account == account]
    if not checks:
        return None
    last = max(checks, key=lambda e: e.date)
    failing = [e for e in lg.errors if isinstance(getattr(e, "entry", None), data.Balance)
               and e.entry.account == account and e.entry.date == last.date]
    return {"date": last.date.isoformat(), "amount": str(last.amount),
            "ok": not failing, "error": failing[0].message if failing else None}


def _reconciled(lg: ledger.Ledger, account: str, since: date) -> Decimal:
    total = Decimal(0)
    for t in lg.transactions:
        if t.date < since or not any(p.account == RECONCILIATION for p in t.postings):
            continue
        for p in t.postings:
            if p.account == account:
                total += lg.to_eur(p.units.number, p.units.currency, t.date) or Decimal(0)
    return total


def _price_age(inv, prices: dict, today: date) -> int | None:
    """Days since the oldest 'latest price' among the non-EUR commodities held."""
    ages = []
    for pos in inv:
        cur = "EUR" if pos.units.currency == "USD" else pos.units.currency  # USD via EUR/USD
        if cur != "EUR" and pos.units.number:
            ages.append((today - prices[cur]).days if cur in prices else 10**6)
    return max(ages) if ages else None


def accounts_status(today: date | None = None) -> list[dict]:
    today = today or date.today()
    lg = ledger.load()
    updaters = _updaters()
    by_account, by_source, prices = _last_dates(lg)
    bank_sync = store.get("bank_last_sync", {})
    last_sync = store.get("last_sync")
    invs = balances.inventories(lg, today, "")
    out = []
    for account in lg.accounts():
        if not account.startswith(("Assets:", "Liabilities:")):
            continue
        kind, detail = updaters.get(account, ("manual", None))
        inv = invs.get(account)
        held = inv is not None and not inv.is_empty()
        last_txn = by_account.get(account)
        if kind == "bank":
            synced = bank_sync.get(detail)
            last_update = date.fromisoformat(synced) if synced else by_source.get(detail)
        elif kind == "wallet":
            last_update = date.fromisoformat(last_sync) if last_sync else by_source.get("wallet")
        elif kind == "indexa":
            last_update = prices.get(indexa.COMMODITY)
        elif kind == "csv":
            rec = store.get(f"import:{CSV_SOURCES[detail]}") or {}
            last_update = (date.fromisoformat(rec["imported_at"]) if rec.get("imported_at")
                           else by_source.get(CSV_SOURCES[detail]))
        else:  # manual: a balance assertion counts as a check-in
            asserted = max((e.date for e in lg.entries
                            if isinstance(e, data.Balance) and e.account == account), default=None)
            last_update = max(filter(None, (last_txn, asserted)), default=None)
        age = (today - last_update).days if last_update else None
        reasons = []
        if age is None and (held or last_txn):
            reasons.append("never updated")
        elif age is not None and age > MAX_AGE[kind] and (held or kind != "manual"):
            reasons.append(f"{kind} {age} days old (max {MAX_AGE[kind]})")
        price_age = _price_age(inv, prices, today) if held else None
        if price_age is not None and price_age > MAX_AGE["prices"]:
            reasons.append(f"prices {min(price_age, 9999)} days old")
        assertion = _assertion(lg, account)
        status = ("error" if assertion and not assertion["ok"]
                  else "warn" if reasons else "ok")
        out.append({
            "account": account,
            "group": balances.group_of(account),
            "balance_eur": balances.q(balances.value(lg, inv, today)) if held else "0.00",
            "updates_via": kind,
            "updater": detail,
            "last_update": last_update.isoformat() if last_update else None,
            "last_txn": last_txn.isoformat() if last_txn else None,
            "balance_check": assertion,
            "reconciled_30d": balances.q(_reconciled(lg, account, today - timedelta(days=30))),
            "stale": bool(reasons),
            "stale_reason": "; ".join(reasons) or None,
            "status": status,
        })
    return out


def summary(today: date | None = None) -> dict:
    from fin.sync import banks

    today = today or date.today()
    rows = accounts_status(today)
    counts = {s: sum(r["status"] == s for r in rows) for s in ("ok", "warn", "error")}
    expiring = []
    for b in banks.status():
        if b["valid_until"]:
            days = (date.fromisoformat(b["valid_until"]) - today).days
            if days < 14:
                expiring.append({"key": b["key"], "name": b["name"],
                                 "valid_until": b["valid_until"], "days": days})
    return {"date": today.isoformat(), "accounts": counts,
            "pending_reviews": len(store.list_pending()), "banks_expiring": expiring,
            "ledger_errors": len(ledger.load().errors)}


def text(rows: list[dict], s: dict) -> str:
    lines = [f"{r['status']:<5} {r['account']:<38}{r['balance_eur']:>12} EUR  "
             f"{r['updates_via']:<7} {r['last_update'] or '-':<10} "
             + (f"check {r['balance_check']['date']} "
                f"{'ok' if r['balance_check']['ok'] else 'FAIL'}  "
                if r["balance_check"] else "")
             + (r["stale_reason"] or "") for r in rows]
    c = s["accounts"]
    lines.append(f"\n{c['ok']} ok, {c['warn']} warn, {c['error']} error; "
                 f"{s['pending_reviews']} pending reviews; {s['ledger_errors']} ledger errors")
    for b in s["banks_expiring"]:
        lines.append(f"bank {b['name']}: session expires {b['valid_until']} ({b['days']} days)")
    return "\n".join(lines)
