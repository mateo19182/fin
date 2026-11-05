from decimal import Decimal
from pathlib import Path

from fin import ledger
from fin.sync import revolut_invest as ri

CSV = (Path(__file__).parent / "fixtures" / "revolut_invest.csv").read_text()


def test_parse_numbers_and_dates():
    rows = ri.parse(CSV)
    assert len(rows) == 7 and rows[0]["type"] == "CASH TOP-UP"
    assert rows[0]["total"] == Decimal("500.00") and rows[0]["date"].isoformat() == "2026-03-02"
    assert rows[1]["qty"] == Decimal("1.5") and rows[1]["price"] == Decimal("180.00")
    assert rows[5]["total"] == Decimal("-0.50")
    assert rows[0]["id"].startswith("revinv:") and rows[0]["id"] != rows[1]["id"]
    assert ri.parse(CSV)[0]["id"] == rows[0]["id"]  # stable


def test_import_is_idempotent_and_balanced(root):
    dry = ri.import_csv(CSV, dry_run=True)
    assert dry["rows"] == 7 and dry["imported"] == 0 and len(dry["preview"]) == 6
    assert dry["unsupported"] == ["2026-04-01 STOCK SPLIT NVDA 0"]
    assert ledger.load().find(ri.parse(CSV)[0]["id"]) is None

    res = ri.import_csv(CSV)
    assert res["imported"] == 6 and res["errors"] == []
    lg = ledger.load()
    assert not lg.errors
    ids = {r["id"] for r in ri.parse(CSV)}
    assert len(ids & lg.external_ids()) == 6

    sell = next(t for t in lg.transactions if t.payee == "Sell")
    gains = next(p for p in sell.postings if p.account == ri.GAINS)
    assert gains.units.number == Decimal("-50.00")  # sold 1 NVDA bought at 150 for 200
    topup = next(t for t in lg.transactions if t.narration == "Cash top-up")
    bank = next(p for p in topup.postings if p.account == ri.TRANSFER)
    assert bank.units.currency == "EUR" and bank.units.number == Decimal("-460.83")
    assert "Expenses:Investment:Fees" in lg.accounts()

    again = ri.import_csv(CSV)
    assert again["imported"] == 0 and again["skipped"] == 6
