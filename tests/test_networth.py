from datetime import date

from fin import ledger, networth

TODAY = date(2026, 10, 15)


def add_investing(root):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-09.beancount"
    f.write_text(f.read_text() + '\n2026-09-25 * "Revolut Invest" "top-up"\n'
                 "  Assets:Investment:Revolut:Cash   200.00 EUR\n"
                 "  Assets:Bank:Revolut:Checking    -200.00 EUR\n"
                 '\n2026-10-02 * "Revolut Invest" "withdrawal"\n'
                 "  Assets:Investment:Revolut:Cash   -50.00 EUR\n"
                 "  Assets:Bank:Revolut:Checking      50.00 EUR\n")


def test_series_shape_and_order(root):
    rows = networth.series(3, TODAY)
    assert [r["month"] for r in rows] == ["2026-07", "2026-08", "2026-09", "2026-10"]
    assert set(rows[0]["groups"]) == {"cash", "stocks", "indexa", "crypto", "receivables"}


def test_month_split(root):
    add_investing(root)
    lg = ledger.load()
    sep = networth.month(lg, "2026-09", TODAY)
    # NVDA 2 × 180 USD + 100 USD cash at 1.17 + 200 EUR top-up = 593.16; cash 1883.76 - 200
    assert sep["groups"]["stocks"] == "593.16" and sep["groups"]["cash"] == "1683.76"
    assert sep["income"] == "2000.00" and sep["expenses"] == "116.24" and sep["saved"] == "1883.76"
    assert sep["contributions"] == "200.00"
    # August (before any price): 2 NVDA at cost 150 + 100 USD = 400 USD at the first known rate
    assert sep["market"] == "51.28" and sep["change"] == "1935.04" and sep["total"] == "2276.92"

    octo = networth.month(lg, "2026-10", TODAY)
    assert octo["contributions"] == "-50.00" and octo["saved"] == "0.00"
    assert octo["groups"]["cash"] == "1733.76" and octo["market"] == "0.00"
