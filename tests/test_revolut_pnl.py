from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from fin.sync import revolut_pnl

# Only Revolut P&L statements: other uploads (contracts, receipts) land in the same cache.
SAMPLES = [f for f in sorted(Path("~/.hermes/cache/documents").expanduser().glob("*.pdf"))
           if "revolut" in f.name.lower() or "profit" in f.name.lower()]

# Guessed layout: one line per dividend, date, symbol + name, gross, withholding, net.
GUESSED = """Profit and loss statement
Account currency: USD

Dividends
Date         Security                    Gross amount   Withholding tax   Net amount
2 Apr 2026   AVGO Broadcom Inc.          US$1.94        -US$0.29          US$1.65
10 Apr 2026  NXPI NXP Semiconductors     US$1.01        -US$0.15          US$0.86

Sales
"""


def test_parse_guessed_layout():
    rows = revolut_pnl.parse_text(GUESSED)
    assert rows == [
        {"date": date(2026, 4, 2), "ticker": "AVGO", "gross": D("1.94"), "withholding": D("0.29"),
         "net": D("1.65"), "currency": "USD"},
        {"date": date(2026, 4, 10), "ticker": "NXPI", "gross": D("1.01"), "withholding": D("0.15"),
         "net": D("0.86"), "currency": "USD"}]


def test_parse_rejects_rows_that_do_not_add_up():
    with pytest.raises(ValueError):
        revolut_pnl.parse_text(GUESSED.replace("US$1.65", "US$1.60"))


@pytest.mark.skipif(not SAMPLES, reason="no Revolut P&L PDF sample in ~/.hermes/cache/documents")
def test_parse_real_sample():
    rows = [r for f in SAMPLES for r in revolut_pnl.parse(f)]
    assert rows, "the dividends section was not recognised: adapt revolut_pnl to the layout"
    assert all(r["gross"] - r["withholding"] == r["net"] for r in rows)
