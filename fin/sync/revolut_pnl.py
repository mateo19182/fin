"""Revolut "Profit and loss statement" PDF -> exact dividend gross / withholding / net.

Revolut issues one PDF per account currency. The dividends section lists, per payment, the
date, security (symbol + name, ISIN), gross amount, withholding tax and net amount. The exact
layout is not documented publicly; this parser is written against that description and must
be checked on the first real sample (~/.hermes/cache/documents/*.pdf). The parsed rows replace
the estimated gross-ups booked from the CSV (`estimated: "true"` meta).
"""

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fin import ledger
from fin.models import Posting
from fin.renta import pdf, rewrite
from fin.sync import revolut_invest as ri

SECTION = re.compile(r"^\s*Dividends?\b", re.M | re.I)
END = re.compile(r"^\s*(Sales|Interest|Fees|Total)\b", re.M | re.I)
DATE = re.compile(r"\b(\d{1,2} \w{3} \d{4}|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b")
AMOUNT = re.compile(r"-?[A-Z]{0,3}\s?[$€£]?\s?-?\d[\d,]*\.\d{2}")
TICKER = re.compile(r"\b([A-Z][A-Z0-9]{0,5})\b")
CENT = Decimal("0.01")


def _date(s: str) -> date:
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(s)


def _amount(s: str) -> Decimal:
    return Decimal(re.sub(r"[^\d.\-]", "", s))


def parse_text(text: str) -> list[dict]:
    """Rows {date, ticker, gross, withholding, net, currency} from the dividends section."""
    m = SECTION.search(text)
    if not m:
        return []
    body = text[m.end():]
    e = END.search(body)
    body = body[:e.start()] if e else body
    currency = (re.search(r"\b(USD|EUR|GBP)\b", text) or [None, "USD"])[1]
    rows = []
    for line in body.split("\n"):
        dm = DATE.search(line)
        amounts = AMOUNT.findall(line)
        if not dm or len(amounts) < 3:
            continue
        rest = line[dm.end():]
        tm = TICKER.search(rest)
        if not tm:
            continue
        gross, tax, net = (_amount(a) for a in amounts[-3:])
        tax = abs(tax)
        if abs(gross - tax - net) > CENT:
            raise ValueError(f"dividend row does not add up: {line.strip()!r}")
        rows.append({"date": _date(dm[1]), "ticker": tm[1], "gross": gross, "withholding": tax,
                     "net": net, "currency": currency})
    return rows


def parse(path: str | Path) -> list[dict]:
    return parse_text(pdf.text(path))


def apply(rows: list[dict], dry_run: bool = False) -> dict:
    """Replace estimated dividend bookings by the statement's exact figures."""
    lg = ledger.load()
    out = {"matched": [], "unmatched": [], "unchanged": 0}
    pending = []
    for r in rows:
        t = next((t for t in lg.transactions if t.date == r["date"] and t.narration == r["ticker"]
                  and t.payee == "Dividend" and any(
                      p.account == ri.CASH and p.units.number == r["net"] for p in t.postings)),
                 None)
        if t is None:
            out["unmatched"].append({**r, "date": r["date"].isoformat()})
            continue
        if "estimated" not in t.meta:
            out["unchanged"] += 1
            continue
        pending.append((t, r))
    # rewrite bottom-up per file so earlier line numbers stay valid
    for t, r in sorted(pending, key=lambda x: (x[0].meta["filename"], -x[0].meta["lineno"])):
        postings = [Posting(ri.CASH, r["net"], r["currency"]),
                    Posting(ri.DIVIDENDS, -r["gross"], r["currency"])]
        if r["withholding"]:
            postings.append(Posting(ri.FOREIGN_TAX, r["withholding"], r["currency"]))
        txn = rewrite.as_txn(t, postings, {"estimated": None, "withholding_rate": None,
                                           "withholding_source": "revolut_pnl"})
        out["matched"].append({"id": ledger.txn_id(t), "preview": ledger.format_txn(txn)})
        if not dry_run:
            path = Path(t.meta["filename"])
            ledger.edit_file(path, lambda text, n=t.meta["lineno"], x=txn:
                             rewrite.replace_block(text, n, x))
    return out
