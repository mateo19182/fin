from datetime import date
from decimal import Decimal

from fin import ledger
from fin.models import Posting, Txn


def test_format_round_trip(root):
    t = Txn(date(2026, 10, 2), 'Café "Central"', "coffee", [
        Posting("Expenses:Food:Restaurant", Decimal("2.30"), "EUR"),
        Posting("Assets:Bank:Revolut:Checking", Decimal("-2.30"), "EUR"),
    ], {"transaction_id": "rt-1", "source": "revolut"})
    text = ledger.format_txn(t)
    assert text.startswith("2026-10-02 * \"Café 'Central'\" \"coffee\"\n  transaction_id: \"rt-1\"")
    ledger.append([t])
    lg = ledger.load()
    assert not lg.errors
    got = lg.find("rt-1")
    assert got.payee == "Café 'Central'" and got.meta["source"] == "revolut"
    assert {(p.account, p.units.number) for p in got.postings} == {
        ("Expenses:Food:Restaurant", Decimal("2.30")),
        ("Assets:Bank:Revolut:Checking", Decimal("-2.30"))}
    assert ledger.bank_file(t.date).read_text().endswith(text)


def test_cost_and_price_round_trip(root):
    t = Txn(date(2026, 10, 3), "Buy", "1 AMD", [
        Posting("Assets:Investment:Revolut:Stocks", Decimal("1"), "AMD", cost="{{180.00 USD}}"),
        Posting("Assets:Bank:Revolut:Checking", Decimal("-165.90"), "EUR", price="@@ 180.00 USD"),
    ], {"external_id": "rt-2"})
    ledger.append([t], ledger.ledger_file().parent / "transactions" / "investments.beancount")
    got = ledger.load().find("rt-2")
    stock = next(p for p in got.postings if p.units.currency == "AMD")
    assert stock.cost.number == Decimal("180.00") and stock.cost.currency == "USD"


def test_append_rejects_invalid_and_restores(root):
    bad = Txn(date(2026, 10, 3), "x", "x", [
        Posting("Expenses:Nope", Decimal("1"), "EUR"),
        Posting("Assets:Bank:Revolut:Checking", Decimal("-1"), "EUR")], {"transaction_id": "bad"})
    before = ledger.bank_file(bad.date).exists()
    try:
        ledger.append([bad])
        raise AssertionError("expected rejection")
    except ValueError:
        pass
    assert ledger.bank_file(bad.date).exists() == before
    assert ledger.load().find("bad") is None


def test_set_account(root):
    ledger.set_account("t-pepe-1", "Expenses:Food:Restaurant", "Expenses:Entertainment")
    got = ledger.load().find("t-pepe-1")
    assert {p.account for p in got.postings} == {"Expenses:Entertainment",
                                                 "Assets:Bank:Revolut:Checking"}


def test_update_txn_edits_header_and_meta(root):
    ledger.update_txn("t-merc-1", payee="Mercadona Oleiros", meta={"source": "caixa_rural",
                                                                   "bank_payee": "MERCADONA"})
    t = ledger.load().find("t-merc-1")
    assert t.payee == "Mercadona Oleiros" and t.narration == "Mercadona"
    assert t.meta["source"] == "caixa_rural" and t.meta["bank_payee"] == "MERCADONA"
    assert {p.account for p in t.postings} == {"Expenses:Food:Groceries",
                                               "Assets:Bank:Revolut:Checking"}
    assert ledger.load().find("t-merc-2").payee == "Mercadona"


def test_patch_txn_single_string_header_is_narration():
    lines = ['2026-01-01 * "only narration"', "  Expenses:Software  1 EUR", "  Assets:Cash:Wallet"]
    out = ledger.patch_txn(lines, 1, payee="Shop")
    assert out[0] == '2026-01-01 * "Shop" "only narration"'
    out = ledger.patch_txn(lines, 1, narration="new")
    assert out[0] == '2026-01-01 * "new"'


def test_edit_file_rolls_back(root):
    path = ledger.bank_file(date(2026, 9, 1))
    before = path.read_text()
    try:
        bad = "\n2026-09-30 balance Assets:Bank:Revolut:Checking 1 EUR\n"
        ledger.edit_file(path, lambda s: s + bad)
        raise AssertionError("expected rejection")
    except ValueError:
        pass
    assert path.read_text() == before and not ledger.load().errors


def test_settle_flips_pending_flag(root):
    t = Txn(date(2026, 3, 2), "Shop", "pending", [
        Posting("Expenses:Food:Groceries", Decimal("2.00")),
        Posting("Assets:Bank:Revolut:Checking", Decimal("-2.00"))], {"transaction_id": "p1"}, "!")
    ledger.append([t])
    assert ledger.settle(["p1", "missing"]) == 1
    assert ledger.load().find("p1").flag == "*"
    assert ledger.settle(["p1"]) == 0


def test_git_backup_disabled_by_default(monkeypatch):
    from fin import ledger

    monkeypatch.setattr(ledger, "section", lambda name: {})

    def unexpected_git(*args, **kwargs):
        raise AssertionError("Default settings must not commit or push private data")

    monkeypatch.setattr(ledger.subprocess, "run", unexpected_git)
    monkeypatch.setattr(ledger.subprocess, "Popen", unexpected_git)
    assert ledger.commit("private transaction") is False
