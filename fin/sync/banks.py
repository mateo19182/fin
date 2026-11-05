"""Enable Banking: bank sessions (auth) and transaction fetch → Candidates."""

import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import jwt
import requests

from fin import config
from fin.models import Candidate

API = "https://api.enablebanking.com"
PENDING = ("PDNG", "PENDING")

last_result: dict[str, dict] = {}  # per bank key, filled by fetch()


def _cfg() -> dict:
    return config.section("enable_banking")


def banks() -> dict[str, dict]:
    return _cfg().get("banks", {})


def _path(key: str, default: str) -> Path:
    p = Path(_cfg().get(key, default)).expanduser()
    return p if p.is_absolute() else config.ROOT / p


def _headers() -> dict:
    cfg = _cfg()
    now = int(time.time())
    token = jwt.encode(
        {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": now, "exp": now + 600},
        _path("key_path", "data/secrets/enable-banking.pem").read_bytes(),
        algorithm="RS256",
        headers={"kid": cfg["app_id"]},
    )
    return {"Authorization": f"Bearer {token}"}


def _call(method: str, path: str, **kw) -> dict:
    r = requests.request(method, API + path, headers=_headers(), timeout=60, **kw)
    if r.status_code >= 400:
        raise requests.HTTPError(f"{method} {path}: {r.status_code} {r.text[:200]}")
    return r.json()


def _sessions() -> dict:
    p = _path("sessions", "data/secrets/eb-sessions.json")
    return json.loads(p.read_text()) if p.exists() else {}


def _save_sessions(sessions: dict) -> None:
    p = _path("sessions", "data/secrets/eb-sessions.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sessions, indent=2))
    p.chmod(0o600)


def _valid_until(session: dict | None) -> datetime | None:
    raw = ((session or {}).get("access") or {}).get("valid_until")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None


def status() -> list[dict]:
    from fin import store

    sessions, now = _sessions(), datetime.now(UTC)
    last = store.get("bank_last_sync", {})
    out = []
    for key, b in banks().items():
        s = sessions.get(key)
        vu = _valid_until(s)
        expired = bool(s) and vu is not None and vu <= now
        out.append({
            "key": key,
            "name": b.get("name", key),
            "account": b["account"],
            "authorized": bool(s) and not expired,
            "expired": expired,
            "valid_until": vu.date().isoformat() if vu else None,
            "last_sync": last.get(key),
        })
    return out


def auth_start(bank_key: str) -> str:
    b = banks()[bank_key]
    aspsps = _call("GET", "/aspsps", params={"country": b["country"]})["aspsps"]
    wanted = b.get("aspsp", b["name"]).lower()
    aspsp = next((a for a in aspsps if wanted in a["name"].lower()), None)
    if aspsp is None:
        raise ValueError(f"bank {b['name']!r} not found in Enable Banking ({b['country']})")
    redirect = _call("GET", "/application")["redirect_urls"][0]
    body = {
        "access": {"valid_until": (datetime.now(UTC) + timedelta(days=90)).isoformat()},
        "aspsp": {"name": aspsp["name"], "country": aspsp["country"]},
        "state": bank_key,
        "redirect_url": redirect,
        "psu_type": "personal",
    }
    return _call("POST", "/auth", json=body)["url"]


def auth_complete(bank_key: str, code_or_redirect_url: str) -> dict:
    code = code_or_redirect_url.strip()
    if "://" in code:
        code = parse_qs(urlparse(code).query).get("code", [""])[0]
    if not code:
        raise ValueError("no authorization code found")
    session = _call("POST", "/sessions", json={"code": code})
    sessions = _sessions()
    sessions[bank_key] = session
    _save_sessions(sessions)
    return {"key": bank_key, "accounts": len(session.get("accounts", [])),
            "valid_until": (session.get("access") or {}).get("valid_until")}


def _pages(account_uid: str, since: date, until: date):
    params: dict = {"date_from": since.isoformat(), "date_to": until.isoformat()}
    while True:
        page = _call("GET", f"/accounts/{account_uid}/transactions", params=params)
        yield from page.get("transactions", [])
        key = page.get("continuation_key")
        if not key:
            return
        params = {**params, "continuation_key": key}


def convert(raw: dict, bank_key: str, account: str) -> Candidate | None:
    """One Enable Banking transaction → Candidate (None for zero/undated rows)."""
    money = raw.get("transaction_amount") or {}
    amount = Decimal(str(money.get("amount") or "0"))
    if amount == 0:
        return None
    cdi = (raw.get("credit_debit_indicator") or "").upper()
    if cdi == "DBIT":
        amount = -abs(amount)
    elif cdi == "CRDT":
        amount = abs(amount)
    when = raw.get("booking_date") or raw.get("value_date") or raw.get("transaction_date")
    if not when:
        return None
    creditor = (raw.get("creditor") or {}).get("name") or ""
    debtor = (raw.get("debtor") or {}).get("name") or ""
    remit = raw.get("remittance_information") or []
    narration = " ".join(x for x in ([remit] if isinstance(remit, str) else remit) if x).strip()
    payee = ((debtor if amount > 0 else creditor) or creditor or debtor or narration[:50]
             or bank_key).strip()
    ext = raw.get("entry_reference") or raw.get("transaction_id")
    if not ext:  # some banks send no ids: stable hash of the row's identity
        sig = f"{bank_key}|{when[:10]}|{amount}|{money.get('currency')}|{payee}|{narration}"
        ext = f"{bank_key}:{hashlib.sha1(sig.encode()).hexdigest()[:16]}"
    return Candidate(
        source=bank_key,
        external_id=str(ext),
        date=date.fromisoformat(when[:10]),
        payee=payee[:100],
        narration=(narration or payee)[:200],
        amount=amount,
        currency=money.get("currency") or "EUR",
        account=account,
        raw={"status": raw.get("status"),
             "code": (raw.get("bank_transaction_code") or {}).get("code")},
    )


def _bank_since(key: str, since: date) -> date:
    """Go back further for a bank whose last synced transaction is older (e.g. after re-auth)."""
    from fin import ledger

    dates = [t.date for t in ledger.load().transactions if t.meta.get("source") == key]
    return min(since, max(dates) - timedelta(days=5)) if dates else since


def fetch(since: date) -> list[Candidate]:
    """All authorized banks, all accounts, all pages since `since` (inclusive)."""
    last_result.clear()
    sessions, now, today = _sessions(), datetime.now(UTC), date.today()
    out: list[Candidate] = []
    for key, b in banks().items():
        s = sessions.get(key)
        vu = _valid_until(s)
        if not s or (vu and vu <= now):
            last_result[key] = {"ok": False, "error": "session expired" if s else "not authorized"}
            continue
        try:
            n, start = 0, _bank_since(key, since)
            for acc in s.get("accounts", []):
                for raw in _pages(acc["uid"], start, today):
                    c = convert(raw, key, b["account"])
                    if c:
                        out.append(c)
                        n += 1
            last_result[key] = {"ok": True, "count": n}
        except (requests.RequestException, KeyError, ValueError) as e:
            last_result[key] = {"ok": False, "error": str(e)[:200]}
    return out
