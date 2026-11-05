from datetime import date

from fin import ledger, status, store

TODAY = date(2026, 10, 1)


def by_account(rows):
    return {r["account"]: r for r in rows}


def test_accounts_status_kinds_and_staleness(root):
    store.put("bank_last_sync", {"revolut": "2026-09-30"})
    rows = by_account(status.accounts_status(TODAY))
    rev = rows["Assets:Bank:Revolut:Checking"]
    assert rev["updates_via"] == "bank" and rev["updater"] == "revolut"
    assert rev["last_update"] == "2026-09-30" and not rev["stale"] and rev["status"] == "ok"
    assert rev["balance_eur"] == "1883.76"

    caixa = rows["Assets:Bank:CaixaRural:Checking"]  # never synced, never used
    assert caixa["updates_via"] == "bank" and caixa["last_update"] is None
    assert not caixa["stale"] and caixa["balance_eur"] == "0.00"

    stocks = rows["Assets:Investment:Revolut:Stocks"]
    assert stocks["updates_via"] == "csv" and stocks["last_update"] is None and stocks["stale"]
    assert stocks["stale_reason"] == "never updated"

    rows = by_account(status.accounts_status(date(2026, 10, 6)))
    assert "bank 6 days old" in rows["Assets:Bank:Revolut:Checking"]["stale_reason"]
    assert "prices 6 days old" in rows["Assets:Investment:Revolut:Stocks"]["stale_reason"]


def test_balance_assertion_and_reconciliation(root):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-09.beancount"
    f.write_text(f.read_text() + "\n2020-01-01 open Equity:Reconciliation\n"
                 "2026-09-29 pad Assets:Bank:Revolut:Checking Equity:Reconciliation\n"
                 "2026-09-30 balance Assets:Bank:Revolut:Checking 1900.00 EUR\n"
                 "2026-09-30 balance Assets:Bank:CaixaRural:Checking 5.00 EUR\n")
    rows = by_account(status.accounts_status(TODAY))
    rev = rows["Assets:Bank:Revolut:Checking"]
    assert rev["balance_check"] == {"date": "2026-09-30", "amount": "1900.00 EUR", "ok": True,
                                    "error": None}
    assert rev["reconciled_30d"] == "16.24" and rev["balance_eur"] == "1900.00"
    caixa = rows["Assets:Bank:CaixaRural:Checking"]
    assert caixa["status"] == "error" and not caixa["balance_check"]["ok"]
    s = status.summary(TODAY)
    assert s["accounts"]["error"] == 1 and s["ledger_errors"] == 1
    assert s["pending_reviews"] == 0 and s["banks_expiring"] == []
    assert "FAIL" in status.text(status.accounts_status(TODAY), s)
