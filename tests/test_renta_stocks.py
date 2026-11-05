from datetime import date
from decimal import Decimal as D

from fin.renta import stocks
from fin.sync import revolut_invest as ri

HEADER = "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"


def row(d, ticker, kind, qty, price, total, cur="USD", fx="1.2500"):
    return f"{d}T10:00:00.000Z,{ticker},{kind},{qty},{cur} {price},{cur} {total},{cur},{fx}\n"


CSV = (HEADER
       + row("2025-03-10", "AMD", "BUY - LIMIT", 2, "100.00", "200.00")  # 160 EUR
       + row("2025-06-01", "AMD", "BUY - MARKET", 1, "130.00", "130.00", fx="1.3000")  # 100 EUR
       + row("2025-05-16", "EUNK", "BUY - LIMIT", 2, "86.50", "174", "EUR", "1.0000")
       + row("2026-02-01", "AMD", "SELL - MARKET", 2.5, "150.00", "375.00")  # 300 EUR
       + row("2026-03-01", "EUNK", "SELL - MARKET", 2, "86.14", "172.28", "EUR", "1.0000")
       + row("2026-03-20", "EUNK", "BUY - MARKET", 1, "80.00", "80.00", "EUR", "1.0000")
       + row("2025-08-08", "NVDA", "SELL - MARKET", 1, "100.00", "100.00"))  # no lots


def test_fifo_partial_lots_and_eur_conversion():
    rows = ri.parse(CSV)
    g = stocks.gains(rows, 2026)
    amd = g["shares"][0]
    # FIFO: 2 shares at 160 EUR + 0.5 of the 100 EUR lot = 210 EUR cost; proceeds 300 EUR
    assert amd["ticker"] == "AMD" and amd["cost_eur"] == D("210.00")
    assert amd["proceeds_eur"] == D("300.00") and amd["gain_eur"] == D("90.00")
    assert [lot["qty"] for lot in amd["lots"]] == ["2", "0.5"]
    assert amd["repurchase_within_2m"] is False
    assert g["shares_total"] == D("90.00")


def test_etf_loss_is_separate_and_repurchase_flagged():
    rows = ri.parse(CSV)
    g = stocks.gains(rows, 2026)
    etf = g["etf"][0]
    assert etf["kind"] == "etf" and etf["gain_eur"] == D("-1.72")
    assert etf["repurchase_within_2m"] is True  # bought EUNK again 19 days later
    assert g["etf_total"] == D("-1.72")
    assert any("art. 33.5.f" in w for w in g["warnings"])
    assert not any("NVDA" in w for w in g["warnings"])  # the 2025 sale is not in 2026


def test_sale_without_lots_is_reported():
    g = stocks.gains(ri.parse(CSV), 2025)
    assert g["shares"][0]["ticker"] == "NVDA" and "more than the known lots" in g["warnings"][0]


def test_positions_after_sales():
    pos = stocks.positions(ri.parse(CSV), date(2026, 12, 31))
    assert pos == {"AMD": D("0.5"), "EUNK": D("1")}


def test_latest_csv_from_archive(root, tmp_path):
    assert stocks.latest_csv() is None and stocks.load_rows() == []
    old = root / "docs" / "2025" / "statements" / "revolut-invest_2025-12-31.csv"
    old.parent.mkdir(parents=True)
    old.write_text(HEADER)
    f = tmp_path / "statement.csv"
    f.write_text(CSV)
    dest = ri.archive(f.read_bytes())  # named after its last row, filed under that year
    assert dest.relative_to(root / "docs").parts[:2] == ("2026", "statements")
    assert ri.archive(f.read_bytes()) == dest  # same bytes: no second copy
    assert stocks.latest_csv() == dest
    assert len(stocks.load_rows()) == 7
