"""Revolut Invest account-statement CSV → investment transactions (no review step)."""

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fin import docs, ledger, store
from fin.models import Posting, Txn
from fin.renta import securities

STOCKS = "Assets:Investment:Revolut:Stocks"
CASH = "Assets:Investment:Revolut:Cash"
DIVIDENDS = "Income:Investment:Dividends"
GAINS = "Income:CapitalGains:Stocks"
FEES = "Expenses:Investment:Fees"
REWARDS = "Income:Investment:Rewards"
TAXES = "Expenses:Investment:Taxes"
# Tax withheld at source by the paying country (US 15% with W-8BEN, DE 26.375%, ...).
FOREIGN_TAX = "Expenses:Taxes:Foreign:Withheld"
SOURCE = "revolut_invest"
FILE = "transactions/investments.beancount"
# Top-ups also arrive through the bank sync ("To investment account"), which books them
# into this clearing account; the CSV books the other side, so nothing is counted twice.
TRANSFER = "Assets:Transfer:RevolutInvest"
# Positions before this date are in the 2026-01-03 opening balances.
SINCE = date(2026, 1, 4)


ARCHIVE_PREFIX = "revolut-invest_"


def archive(data: bytes) -> Path:
    """Keep the raw statement as <year>/statements/revolut-invest_<last date>.csv: the full
    history is what the Renta FIFO lots are built from."""
    rows = parse(data.decode("utf-8-sig"))
    end = max((r["date"] for r in rows), default=date.today())
    return docs.put(data, "statements", end.year, f"{ARCHIVE_PREFIX}{end}.csv")


def _num(s: str | None) -> Decimal:
    s = re.sub(r"[^\d.\-()]", "", s or "")
    neg = s.startswith("(") or s.startswith("-")
    s = s.strip("()-")
    try:
        n = Decimal(s) if s else Decimal(0)
    except InvalidOperation:
        return Decimal(0)
    return -n if neg else n


def _date(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def parse(text: str) -> list[dict]:
    rows = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if not r.get("date") or not r.get("type"):
            continue
        rows.append({
            "id": "revinv:" + hashlib.sha1("|".join(raw.values()).encode()).hexdigest()[:16],
            "date": _date(r["date"]),
            "ticker": r.get("ticker", ""),
            "type": r["type"].upper(),
            "qty": _num(r.get("quantity")),
            "price": _num(r.get("price per share")),
            "total": _num(r.get("total amount")),
            "currency": r.get("currency") or "USD",
            "fx": _num(r.get("fx rate")),
        })
    return sorted(rows, key=lambda r: r["date"])


def to_txn(r: dict) -> Txn | None:
    t, cur, total, tk = r["type"], r["currency"], abs(r["total"]), r["ticker"]
    meta = {"external_id": r["id"], "source": SOURCE}
    bank_leg = _bank_leg(cur, r["fx"])

    def txn(payee, narration, postings):
        return Txn(r["date"], payee, narration, postings, meta)

    if t.startswith("BUY"):
        return txn("Buy", f"{r['qty'].normalize():f} {tk} @ {r['price']} {cur}", [
            Posting(STOCKS, r["qty"], tk, cost=f"{{{{{total} {cur}}}}}"),
            Posting(CASH, -total, cur)])
    if t.startswith("SELL"):
        return txn("Sell", f"{r['qty'].normalize():f} {tk} @ {r['price']} {cur}", [
            Posting(STOCKS, -abs(r["qty"]), tk, cost="{}", price=f"@@ {total} {cur}"),
            Posting(CASH, total, cur),
            Posting(GAINS)])
    if "DIVIDEND TAX" in t or t.startswith("WITHHOLDING"):
        signed = total if "CORRECTION" in t else -total  # a correction refunds tax withheld
        return txn("Dividend tax", f"{t.title()} {tk}", [Posting(CASH, signed, cur),
                                                         Posting(TAXES, -signed, cur)])
    if t == "DIVIDEND":
        return txn("Dividend", tk, dividend_postings(tk, total, cur, meta))
    if "TOP-UP" in t or "TRANSFER FROM" in t:
        return txn("Revolut Invest", "Cash top-up", [Posting(CASH, total, cur), bank_leg(-total)])
    if "WITHDRAWAL" in t or "TRANSFER TO" in t:
        return txn("Revolut Invest", "Cash withdrawal", [Posting(CASH, -total, cur),
                                                         bank_leg(total)])
    if t == "REWARD":
        return txn("Revolut Invest", f"Reward {tk}".strip(), [Posting(CASH, total, cur),
                                                               Posting(REWARDS, -total, cur)])
    if "FEE" in t:
        return txn("Revolut Invest", t.title(), [Posting(CASH, -total, cur),
                                                 Posting(FEES, total, cur)])
    return None  # e.g. STOCK SPLIT: reported as unsupported


def dividend_postings(ticker: str, net: Decimal, cur: str, meta: dict) -> list[Posting]:
    """The CSV gives the net dividend: gross it up at the country's withholding rate.

    Estimated until the Revolut P&L statement gives the exact figures (`estimated` meta)."""
    rate, _, country = securities.withholding(ticker)
    gross, withheld = securities.gross_up(net, rate)
    meta.update({"estimated": "true", "withholding_country": country,
                 "withholding_rate": str(rate)})
    out = [Posting(CASH, net, cur), Posting(DIVIDENDS, -gross, cur)]
    if withheld:
        out.append(Posting(FOREIGN_TAX, withheld, cur))
    return out


def _bank_leg(cur: str, fx: Decimal):
    def leg(amount: Decimal) -> Posting:
        if cur == "EUR" or not fx:
            return Posting(TRANSFER, amount, cur)
        eur = (amount / fx).quantize(Decimal("0.01"))
        return Posting(TRANSFER, eur, "EUR", price=f"@@ {abs(amount)} {cur}")
    return leg


def import_csv(text: str, dry_run: bool = False, since: date | None = None) -> dict:
    """Rows before `since` (default SINCE) are skipped."""
    since = since or SINCE
    lg = ledger.load()
    known = lg.external_ids()
    out: dict = {"rows": 0, "imported": 0, "skipped": 0, "unsupported": [], "errors": [],
                 "preview": []}
    txns, rows = [], parse(text)
    for r in rows:
        out["rows"] += 1
        if r["date"] < since or r["id"] in known:
            out["skipped"] += 1
            continue
        t = to_txn(r)
        if t is None:
            out["unsupported"].append(f"{r['date']} {r['type']} {r['ticker']} {r['total']}")
            continue
        txns.append(t)
    out["preview"] = [ledger.format_txn(t) for t in txns]
    if dry_run:
        return out
    if rows:
        store.put(f"import:{SOURCE}", {"imported_at": date.today().isoformat(),
                                       "statement_end": max(r["date"] for r in rows).isoformat()})
    if not txns:
        return out
    for acct, currencies in ((FEES, "USD,EUR"), (TAXES, "USD,EUR"), (REWARDS, "USD,EUR"),
                              (FOREIGN_TAX, "USD,EUR"), (TRANSFER, "")):
        if any(p.account == acct for t in txns for p in t.postings):
            ledger.ensure_open(acct, currencies)
    failures = ledger.append_safe(txns, ledger.ledger_file().parent / FILE)
    out["errors"] = [f"{t.date} {t.narration}: {msg}" for t, msg in failures]
    out["imported"] = len(txns) - len(failures)
    if out["imported"]:
        ledger.commit(f"revolut invest: import {out['imported']} rows")
    return out
