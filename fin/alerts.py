"""Anomaly alerts on newly synced transactions, sent right after each sync (dry-run respected).

Every rule and threshold lives in THRESHOLDS. Alerts are deduplicated for good in the kv store
(`alerts_sent`: key -> date) and logged (`alerts_log`) for the weekly digest.
"""

import statistics
from datetime import date, timedelta
from decimal import Decimal

from fin import analytics, ledger, notify, status, store
from fin.payees import normalize

THRESHOLDS = {
    "duplicate_days": 3,  # same payee + amount within N days, different ids
    "duplicate_min": Decimal(5),  # below this, repeats are tolls and coffees, not double charges
    "large_factor": Decimal(3),  # > factor x payee median ...
    "large_min": Decimal(150),  # ... and above this floor
    "new_payee_min": Decimal(300),  # payee never seen before
    "price_change_pct": Decimal(5),  # subscription charge vs its previous charge
    "bank_expiry_days": 14,  # reused from status.summary
    "log_keep": 100,
}
ZERO = Decimal(0)


def _history(lg: ledger.Ledger) -> dict[str, list[tuple[date, Decimal, str]]]:
    """normalized payee -> [(date, EUR expense, id)] over the ledger."""
    out: dict[str, list] = {}
    for t in lg.transactions:
        v = analytics.expense_of(lg, t)
        if v > 0 and t.payee:
            out.setdefault(normalize(t.payee), []).append((t.date, v, ledger.txn_id(t)))
    return out


def _expense(row: dict, lg: ledger.Ledger) -> Decimal | None:
    amt = Decimal(str(row["amount"]))
    if amt >= 0:
        return None
    # booked rows know their counter-account: only spending counts, not moves between own
    # accounts (savings, Indexa, cards), tax payments or investments
    if row.get("account") and not row["account"].startswith("Expenses:"):
        return None
    v = lg.to_eur(-amt, row.get("currency", "EUR"), date.fromisoformat(row["date"]))
    return v


def evaluate(lg: ledger.Ledger, rows: list[dict], today: date | None = None) -> list[dict]:
    """Alerts for `rows` (ingest booked + pending rows: id, date, payee, amount, currency)."""
    today = today or date.today()
    T = THRESHOLDS
    hist = _history(lg)
    subs = {normalize(s["payee"]): s for s in analytics.subscriptions(lg, today=today)}
    out = []
    seen_rows: list[tuple[str, date, Decimal, str]] = []
    for row in rows:
        v = _expense(row, lg)
        if v is None:
            continue
        d, key, rid = date.fromisoformat(row["date"]), normalize(row["payee"]), row["id"]
        label = f"{row['date'][5:]} {row['payee']} {v:.2f} EUR"
        others = [(hd, hv, hid) for hd, hv, hid in hist.get(key, []) if hid != rid]
        others += [(sd, sv, sid) for sk, sd, sv, sid in seen_rows if sk == key and sid != rid]
        seen_rows.append((key, d, v, rid))
        dup = [o for o in others if v >= T["duplicate_min"]
               and abs((o[0] - d).days) <= T["duplicate_days"] and abs(o[1] - v) < Decimal("0.01")]
        if dup:
            out.append({"key": f"dup:{rid}", "kind": "duplicate",
                        "text": f"Possible duplicate charge: {label} (also {dup[0][0]})"})
        amounts = [o[1] for o in others if o[2] != rid]
        if not amounts and v > T["new_payee_min"]:
            out.append({"key": f"large:{rid}", "kind": "large",
                        "text": f"Large expense at a new payee: {label}"})
        elif amounts:
            med = Decimal(str(statistics.median(amounts)))
            if v > max(T["large_factor"] * med, T["large_min"]):
                out.append({"key": f"large:{rid}", "kind": "large",
                            "text": f"Unusually large: {label} (median {med:.2f})"})
        if key in subs:
            prev = [o for o in others if o[0] < d or (o[0] == d and o[2] < rid)]
            if prev:
                last = max(prev)[1]
                if last and abs(v - last) / last * 100 > T["price_change_pct"]:
                    out.append({"key": f"price:{key}:{row['date']}", "kind": "price",
                                "text": f"Subscription price change: {row['payee']} "
                                        f"{last:.2f} → {v:.2f} EUR"})
    _, new_rec = analytics.recurring(lg, today + timedelta(days=1))
    for payee in new_rec:
        out.append({"key": f"recurring:{normalize(payee)}", "kind": "recurring",
                    "text": f"New recurring payee: {payee}"})
    for b in status.summary(today)["banks_expiring"]:
        if b["days"] < T["bank_expiry_days"]:
            out.append({"key": f"bank:{b['key']}:{b['valid_until']}", "kind": "bank",
                        "text": f"Bank {b['name']}: session expires {b['valid_until']} "
                                f"({b['days']} days) — `fin bank-auth {b['key']}`"})
    return out


def run(ingest_result: dict, dry_run: bool = False, today: date | None = None) -> list[str]:
    """Evaluate the sync's new rows, send the alerts not sent before, remember them."""
    today = today or date.today()
    rows = list(ingest_result.get("booked", [])) + list(ingest_result.get("pending", []))
    lg = ledger.load()
    sent = store.get("alerts_sent", {})
    fresh = [a for a in evaluate(lg, rows, today) if a["key"] not in sent]
    if not fresh:
        return []
    notify.send("Finance alerts:\n" + "\n".join(f"- {a['text']}" for a in fresh), dry_run)
    if not dry_run:
        store.put("alerts_sent", {**sent, **{a["key"]: today.isoformat() for a in fresh}})
        log = store.get("alerts_log", [])
        log += [{"date": today.isoformat(), "kind": a["kind"], "text": a["text"]} for a in fresh]
        store.put("alerts_log", log[-THRESHOLDS["log_keep"]:])
    return [a["text"] for a in fresh]


def recent(days: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    return [a for a in store.get("alerts_log", []) if a["date"] >= since]
