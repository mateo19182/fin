from datetime import date

from fin import alerts, digest, ledger, store

TODAY = date(2026, 10, 2)


def row(id_, d, payee, amount):
    return {"id": id_, "date": d, "payee": payee, "amount": amount, "currency": "EUR"}


def test_rules(root):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-10.beancount"
    f.write_text("""
2026-10-01 * "Netflix" "Netflix"
  transaction_id: "nf-10"
  Expenses:Software                      12.99 EUR
  Assets:Bank:Revolut:Checking          -12.99 EUR
""")
    lg = ledger.load()
    rows = [row("dup-1", "2026-10-02", "Netflix", "-12.99"),  # same as nf-10, one day apart
            row("big-1", "2026-10-02", "Mercadona", "-200.00"),  # median 23.40 -> > 150
            row("new-1", "2026-10-02", "Apple Store", "-999.00"),
            row("small-1", "2026-10-02", "Kiosk", "-5.00"),
            row("inc-1", "2026-10-02", "Example", "2000.00")]
    got = {a["kind"]: a for a in alerts.evaluate(lg, rows, TODAY)}
    assert got["duplicate"]["key"] == "dup:dup-1"
    assert "Mercadona 200.00" in got["large"]["text"] or "Apple Store" in got["large"]["text"]
    larges = [a for a in alerts.evaluate(lg, rows, TODAY) if a["kind"] == "large"]
    assert {a["key"] for a in larges} == {"large:big-1", "large:new-1"}
    assert "price" not in got  # Netflix is recurring only with >= 3 months in the fixture


def test_own_account_transfers_are_not_expenses(root):
    lg = ledger.load()
    rows = [{**row("sav-1", "2026-10-02", "Revolut Savings", "-2000.00"),
             "account": "Assets:Bank:Revolut:Savings"},
            {**row("buy-1", "2026-10-02", "Apple Store", "-999.00"),
             "account": "Expenses:Shopping"}]
    keys = {a["key"] for a in alerts.evaluate(lg, rows, TODAY)}
    assert "large:sav-1" not in keys and "large:buy-1" in keys


def test_price_change_and_dedup(root):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-older.beancount"
    f.write_text("\n".join(f'''
2026-0{m}-05 * "Netflix" "Netflix"
  transaction_id: "nf-{m}"
  Expenses:Software                      12.99 EUR
  Assets:Bank:Revolut:Checking          -12.99 EUR
''' for m in (6, 7, 8)))
    lg = ledger.load()
    rows = [row("nf-10", "2026-10-05", "Netflix", "-14.99")]
    got = [a for a in alerts.evaluate(lg, rows, date(2026, 10, 6)) if a["kind"] == "price"]
    assert len(got) == 1 and "12.99 → 14.99" in got[0]["text"]
    sent = alerts.run({"booked": rows, "pending": []}, dry_run=False, today=date(2026, 10, 6))
    assert any("price change" in s for s in sent)
    assert "price:netflix:2026-10-05" in store.get("alerts_sent")
    assert alerts.run({"booked": rows, "pending": []}, today=date(2026, 10, 6)) == []
    assert alerts.recent(7, date(2026, 10, 6))[0]["kind"] == "price"


def test_digest(root):
    d = digest.digest(date(2026, 9, 21))
    assert d["lines"][0].startswith("This week")
    assert len(d["lines"]) <= 6
    assert digest.send(date(2026, 9, 21), dry_run=True) is None or d["notable"]
    store.put("alerts_log", [{"date": "2026-09-20", "kind": "large", "text": "Unusually large: x"}])
    d = digest.digest(date(2026, 9, 21))
    assert d["notable"] and "alerts" in d["reasons"] and any("1 alert" in x for x in d["lines"])
    assert digest.send(date(2026, 9, 21), dry_run=True)


def test_subscription_false_rule_silences_price_alerts(root):
    rules = ledger.ledger_file().parent / "rules.toml"
    rules.write_text('[[rule]]\nmatch = "^Estacion Servicio"\nsubscription = false\n')
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-fuel.beancount"
    f.write_text("\n".join(f'''
2026-0{m}-26 * "Estacion Servicio Sant" "Fuel"
  transaction_id: "gas-{m}"
  Expenses:Transport                     30.00 EUR
  Assets:Bank:Revolut:Checking          -30.00 EUR
''' for m in (6, 7, 8, 9)))
    from fin import analytics
    lg = ledger.load()
    assert not any(s["payee"].startswith("Estacion") for s in analytics.subscriptions(lg))
    rows = [row("gas-10", "2026-10-06", "Estacion Servicio Sant", "-120.90")]
    assert not [a for a in alerts.evaluate(lg, rows, date(2026, 10, 7)) if a["kind"] == "price"]


def test_subscription_true_rule_groups_by_payee(root):
    rules = ledger.ledger_file().parent / "rules.toml"
    rules.write_text('[[rule]]\nmatch = "Youtube ?Premium"\nsubscription = true\n')
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-yt.beancount"
    f.write_text("\n".join(f'''
2026-{m}-02 * "Google Youtubepremium" "YouTube"
  transaction_id: "yt-{m}"
  Expenses:Entertainment                 {amt} EUR
  Assets:Bank:Revolut:Checking          -{amt} EUR
''' for m, amt in (("09", "24.77"), ("10", "29.99"))))
    from fin import analytics
    subs = analytics.subscriptions(ledger.load(), today=date(2026, 10, 10))
    yt = [s for s in subs if "Youtube" in s["payee"]]
    assert len(yt) == 1 and yt[0]["amount"] == 29.99 and yt[0]["months"] == 2
