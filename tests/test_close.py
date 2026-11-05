from datetime import date

from fin import close, ledger, report, store

TODAY = date(2026, 10, 2)


def test_checklist(root):
    items = {i["key"]: i for i in close.checklist("2026-09", TODAY)}
    assert set(items) == {"stocks_csv", "savings_csv", "pending", "balances", "banks"}
    assert not items["stocks_csv"]["ok"] and items["stocks_csv"]["detail"] == "never imported"
    assert not items["savings_csv"]["ok"] and items["pending"]["ok"] and items["balances"]["ok"]
    assert not items["banks"]["ok"] and "revolut: bank" in items["banks"]["detail"]

    store.put("import:revolut_invest", {"imported_at": "2026-10-01", "statement_end": "2026-09-30"})
    store.put("import:revolut_savings_csv", {"imported_at": "2026-10-01",
                                             "statement_end": "2026-09-30"})
    store.put("bank_last_sync", {"revolut": "2026-10-01", "caixa_rural": "2026-10-02"})
    items = {i["key"]: i for i in close.checklist("2026-09", TODAY)}
    assert all(i["ok"] for i in items.values()), items
    assert items["savings_csv"]["detail"] == "covered to 2026-10-01"


def test_stats_and_report(root):
    s = close.stats("2026-09", TODAY)
    assert (s["income"], s["expenses"], s["savings_rate"]) == ("2000.00", "116.24", 0.942)
    assert s["prev_savings_rate"] is None and s["transactions"] == 7
    assert s["expense_transactions"] == 6 and s["days"] == 30 and s["avg_daily_spend"] == "3.87"
    top = s["top_categories"][0]
    assert top["account"] == "Expenses:Food:Groceries" and top["amount"] == "83.25"
    assert top["vs_prev"] == "83.25" and top["avg6"] == "0.00" and top["vs_avg6_pct"] is None
    assert s["top_payees"][0] == {"payee": "Mercadona", "amount": "83.25"}
    assert s["biggest_expenses"][0]["payee"] == "Mercadona"
    assert s["biggest_expenses"][0]["amount"] == "41.10" and len(s["biggest_expenses"]) == 5
    assert s["net_worth"]["saved"] == "1883.76" and s["net_worth"]["contributions"] == "0.00"
    assert s["insights"][0] == "Savings rate 94%"
    assert s["insights"][1] == "Biggest expense: Mercadona 41.10 EUR on 2026-09-10"
    assert s["insights"][-1].startswith("Net worth +")

    text = close.text(s, close.checklist("2026-09", TODAY))
    assert text.startswith("Close 2026-09: income 2000.00") and "[ ] Bank syncs fresh" in text
    monthly = report.monthly("2026-09")
    assert "Finance report: September 2026" in monthly and "(94%" in monthly


def test_current_month_uses_elapsed_days(root):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-10.beancount"
    f.write_text('2026-10-01 * "Bar" "x"\n  Expenses:Entertainment  10.00 EUR\n'
                 "  Assets:Bank:Revolut:Checking  -10.00 EUR\n")
    s = close.stats("2026-10", TODAY)
    assert s["days"] == 2 and s["avg_daily_spend"] == "5.00" and s["prev_savings_rate"] == 0.942
