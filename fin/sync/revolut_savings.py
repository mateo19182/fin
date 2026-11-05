"""Revolut savings statement CSV → one interest transaction per month + a balance assertion.

Transfers in the statement are not booked (the bank sync books them from the checking side);
they are only compared against the ledger and the unmatched ones reported.
"""

import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fin import analytics, docs, ledger, store
from fin.models import Posting, Txn
from fin.renta import interest

ACCOUNT = "Assets:Bank:Revolut:Savings"
INCOME = interest.INCOME
SOURCE = "revolut_savings_csv"
FILE = "transactions/banks/revolut-savings.beancount"
# The ledger opens the account with a balance on this date; earlier statement rows are in it.
SINCE = date(2026, 1, 1)
ID = re.compile(r"^revsav:(\d{4}-\d{2}):(\d{2})-(\d{2})$")
BALANCE_LINE = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}} balance {re.escape(ACCOUNT)}\b.*$", re.M)


def _num(s: str) -> Decimal:
    s = re.sub(r"[^\d.\-]", "", s or "")
    return Decimal(s) if s else Decimal(0)


def parse(text: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        when = (r.get("Transaction/Value date") or r.get("Date") or "").strip()
        if not when:
            continue
        desc = (r.get("Description") or "").strip()
        kind = ("interest" if "interest" in desc.lower()
                else "deposit" if desc.startswith("Deposit") else
                "withdrawal" if desc.startswith("Withdrawal") else "other")
        rows.append({
            "date": datetime.strptime(when, "%b %d, %Y").date(),
            "kind": kind,
            "description": desc,
            "amount": _num(r.get("Money in")) - _num(r.get("Money out")),
            "balance": _num(r.get("Balance")),
        })
    return rows  # statement order: chronological


def covered(lg: ledger.Ledger) -> dict[str, int]:
    """month -> last day of that month already booked as interest."""
    out: dict[str, int] = {}
    for ext in lg.external_ids():
        if m := ID.match(ext):
            out[m.group(1)] = max(out.get(m.group(1), 0), int(m.group(3)))
    return out


def interest_txns(rows: list[dict], lg: ledger.Ledger) -> list[Txn]:
    """The not-yet-booked part of each month's interest, as one transaction per month."""
    done, months, last = covered(lg), {}, rows[-1]["date"]
    for r in rows:
        if r["kind"] == "interest" and r["date"] >= SINCE:
            months.setdefault(f"{r['date']:%Y-%m}", []).append(r)
    out = []
    for month, items in sorted(months.items()):
        start = done.get(month, 0) + 1
        end = last.day if month == f"{last:%Y-%m}" else analytics.month_end(items[0]["date"]).day
        part = [r for r in items if r["date"].day >= start]
        if end < start or not part:
            continue
        amount = sum((r["amount"] for r in part), Decimal(0))
        on = items[0]["date"].replace(day=end)
        label = f"Savings interest {month}" + (f" ({start:02d}-{end:02d})" if start > 1 else "")
        # The statement shows interest net of the 19% retención; book it gross + withholding.
        out.append(Txn(on, "Revolut", label, [Posting(ACCOUNT, amount), *interest.postings(amount)],
                       {"external_id": f"revsav:{month}:{start:02d}-{end:02d}", "source": SOURCE}))
    return out


def unmatched_transfers(rows: list[dict], lg: ledger.Ledger) -> list[dict]:
    """Statement deposits/withdrawals with no ledger transfer of the same amount within ±1 day."""
    seen = [(t.date, p.units.number) for t in lg.transactions for p in t.postings
            if p.account == ACCOUNT and "external_id" not in t.meta]
    out = []
    for r in rows:
        if r["kind"] not in ("deposit", "withdrawal") or r["date"] < SINCE:
            continue
        hit = next((i for i, (d, n) in enumerate(seen)
                    if n == r["amount"] and abs((d - r["date"]).days) <= 1), None)
        if hit is None:
            out.append({"date": r["date"].isoformat(), "description": r["description"],
                        "amount": str(r["amount"])})
        else:
            seen.pop(hit)
    return out


def archive(data: bytes) -> Path:
    """File the statement as <year>/statements/revolut-savings_<last date>.csv."""
    rows = parse(data.decode("utf-8-sig"))
    end = rows[-1]["date"] if rows else date.today()
    return docs.put(data, "statements", end.year, f"revolut-savings_{end}.csv")


def _set_balance(text: str, on: date, amount: Decimal) -> str:
    line = f"{on} balance {ACCOUNT} {amount} EUR"
    if BALANCE_LINE.search(text):
        return BALANCE_LINE.sub(line, text, count=1)
    return text.rstrip("\n") + f"\n\n{line}\n"


def import_csv(text: str, dry_run: bool = False) -> dict:
    rows = parse(text)
    if not rows:
        raise ValueError("no rows found in statement")
    lg = ledger.load()
    txns = interest_txns(rows, lg)
    last = rows[-1]
    out: dict = {
        "rows": len(rows), "statement_end": last["date"].isoformat(),
        "interest": [{"id": t.meta["external_id"], "date": t.date.isoformat(),
                      "amount": str(t.postings[0].amount)} for t in txns],
        "imported": 0, "errors": [],
        "unmatched_transfers": unmatched_transfers(rows, lg),
        "balance": {"date": (last["date"] + timedelta(days=1)).isoformat(),
                    "amount": str(last["balance"])},
        "preview": [ledger.format_txn(t) for t in txns],
    }
    if dry_run:
        return out
    path = ledger.ledger_file().parent / FILE
    if txns:
        ledger.ensure_open(interest.WITHHELD, "EUR")
    failures = ledger.append_safe(txns, path)
    out["errors"] = [f"{t.date} {t.narration}: {msg}" for t, msg in failures]
    out["imported"] = len(txns) - len(failures)
    old = path.read_text() if path.exists() else ""
    new = _set_balance(old, last["date"] + timedelta(days=1), last["balance"])
    out["balance"]["changed"] = new != old
    try:
        ledger.edit_file(path, lambda _: new)
        out["balance"]["ok"] = True
    except ValueError as e:
        out["balance"]["ok"] = False
        out["errors"].append(f"balance: {e}")
    store.put(f"import:{SOURCE}", {"imported_at": date.today().isoformat(),
                                   "statement_end": out["statement_end"]})
    if out["imported"] or (out["balance"]["ok"] and out["balance"]["changed"]):
        ledger.commit(f"revolut savings: {out['imported']} interest months, "
                      f"balance {out['balance']['date']}")
    return out
