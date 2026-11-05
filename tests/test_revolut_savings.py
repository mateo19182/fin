from datetime import date
from decimal import Decimal

from fin import ledger, store
from fin.sync import revolut_savings as rs

HEADER = "Transaction/Value date,Description,AER,NIR,Money in,Money out,Balance\n"


def row(d, desc, money_in="", money_out="", balance="0.00"):
    return f'"{d}","{desc}",,,{money_in},{money_out},"€{balance}"\n'


def interest(d, amt, bal):
    return row(d, f'Net interest paid to ""Instant Access Savings"" for {d}', f"€{amt}", "", bal)


STATEMENT = (HEADER
             + row("Dec 30, 2025", 'Deposit to ""Instant Access Savings""', "€100.00", "", "100.00")
             + interest("Dec 31, 2025", "0.50", "100.50")
             + row("Jan 2, 2026", 'Deposit to ""Instant Access Savings""', '"€1,000.00"', "",
                   "1,100.50")
             + interest("Jan 3, 2026", "0.10", "1,100.60")
             + interest("Jan 31, 2026", "0.20", "1,100.80")
             + interest("Feb 1, 2026", "0.30", "1,101.10")
             + row("Feb 2, 2026", 'Withdrawal from ""Instant Access Savings""', "", "€50.00",
                   "1,051.10")
             + interest("Feb 10, 2026", "0.40", "1,051.50"))


WITHDRAWAL = ('2026-02-02 * "From Instant Access Savings" ""\n  transaction_id: "bank-2"\n'
              f"  {rs.ACCOUNT}   -50.00 EUR\n  Assets:Bank:Revolut:Checking  50.00 EUR\n")


def setup_accounts(root, withdrawal=False):
    acc = ledger.ledger_file().parent / "accounts" / "accounts.beancount"
    acc.write_text(acc.read_text() + f"\n2025-01-01 open {rs.ACCOUNT} EUR\n"
                   f"2025-01-01 open {rs.INCOME} EUR\n")
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-01.beancount"
    f.write_text('2026-01-01 * "Opening" "savings"\n'
                 f"  {rs.ACCOUNT}   100.50 EUR\n  Equity:Opening-Balances  -100.50 EUR\n\n"
                 '2026-01-02 * "To Instant Access Savings" "To Instant Access Savings"\n'
                 '  transaction_id: "bank-1"\n'
                 f"  {rs.ACCOUNT}   1000.00 EUR\n  Assets:Bank:Revolut:Checking  -1000.00 EUR\n")
    if withdrawal:
        (f.parent / "2026-02.beancount").write_text(WITHDRAWAL)


def test_parse():
    rows = rs.parse(STATEMENT)
    assert len(rows) == 8 and rows[2]["amount"] == Decimal("1000.00")
    assert rows[2]["kind"] == "deposit" and rows[6]["amount"] == Decimal("-50.00")
    assert rows[-1] == {"date": date(2026, 2, 10), "kind": "interest", "amount": Decimal("0.40"),
                        "balance": Decimal("1051.50"),
                        "description": 'Net interest paid to "Instant Access Savings" '
                                       "for Feb 10, 2026"}


def test_import_books_interest_per_month_and_reports_transfers(root):
    setup_accounts(root)
    r = rs.import_csv(STATEMENT, dry_run=True)
    assert [(i["id"], i["amount"]) for i in r["interest"]] == [
        ("revsav:2026-01:01-31", "0.30"), ("revsav:2026-02:01-10", "0.70")]
    assert r["unmatched_transfers"] == [{"date": "2026-02-02", "amount": "-50.00",
                                         "description": 'Withdrawal from "Instant Access Savings"'}]
    assert r["balance"] == {"date": "2026-02-11", "amount": "1051.50"}
    assert ledger.load().find("revsav:2026-01:01-31") is None

    r = rs.import_csv(STATEMENT)  # the unmatched withdrawal makes the assertion fail
    assert r["imported"] == 2 and r["balance"]["ok"] is False
    assert "50.00 too much" in r["errors"][0]
    text = (ledger.ledger_file().parent / rs.FILE).read_text()
    assert " balance " not in text

    (ledger.ledger_file().parent / "transactions" / "banks" / "2026-02.beancount").write_text(
        WITHDRAWAL)
    r = rs.import_csv(STATEMENT)
    assert r["imported"] == 0 and r["unmatched_transfers"] == [] and r["balance"]["ok"]
    lg = ledger.load()
    assert not lg.errors
    t = lg.find("revsav:2026-02:01-10")
    assert t.date == date(2026, 2, 10) and t.meta["source"] == rs.SOURCE
    text = (ledger.ledger_file().parent / rs.FILE).read_text()
    assert f"2026-02-11 balance {rs.ACCOUNT} 1051.50 EUR" in text
    assert store.get(f"import:{rs.SOURCE}")["statement_end"] == "2026-02-10"

    again = rs.import_csv(STATEMENT)
    assert again["imported"] == 0 and not again["balance"]["changed"]


def test_later_statement_books_only_the_remainder(root):
    setup_accounts(root, withdrawal=True)
    rs.import_csv(STATEMENT)
    r = rs.import_csv(STATEMENT + interest("Feb 20, 2026", "0.05", "1,051.55"))
    assert [(i["id"], i["amount"]) for i in r["interest"]] == [("revsav:2026-02:11-20", "0.05")]
    # once the statement runs past February, the rest of the month is booked at its end
    r = rs.import_csv(STATEMENT + interest("Feb 20, 2026", "0.05", "1,051.55")
                      + interest("Feb 25, 2026", "0.01", "1,051.56")
                      + interest("Mar 1, 2026", "0.07", "1,051.63"))
    assert [(i["id"], i["amount"], i["date"]) for i in r["interest"]] == [
        ("revsav:2026-02:21-28", "0.01", "2026-02-28"),
        ("revsav:2026-03:01-01", "0.07", "2026-03-01")]
    text = (ledger.ledger_file().parent / rs.FILE).read_text()
    assert text.count(" balance ") == 1 and "2026-03-02 balance" in text
    t = ledger.load().find("revsav:2026-02:21-28")
    assert t.narration == "Savings interest 2026-02 (21-28)"
    assert rs.covered(ledger.load()) == {"2026-01": 31, "2026-02": 28, "2026-03": 1}
