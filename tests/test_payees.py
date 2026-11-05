from datetime import date
from decimal import Decimal

import pytest

from fin import categorize, ingest, ledger, payees
from fin.models import Candidate


@pytest.mark.parametrize("raw, expected", [
    ("TJ-SK MARKET", "SK Market"),
    ("Sumup  *todomedre Sl", "Todomedre"),
    ("Wl *steam Purchase", "Steam"),
    ("Vast.ai* Mli2kn6", "Vast.ai"),
    ("Amazon Mktp ES*2K4QW8NM3", "Amazon"),
    ("TJ-NH COLLECTION A CORUãA FI", "NH Collection A Coruña"),
    ("RCBO.TGSS. COTIZACION 005 R.E.AUTONOMOS", "TGSS"),
    ("EXAMPLE INTELLIGENCE S L", "Example Intelligence"),
    ("Mp**dia 13849", "Dia"),
    ("144.gadis Sta.cruz", "Gadis Sta.cruz"),
    ("Uber * Eats Pending", "Uber Eats"),
    ("Uber *trip", "Uber"),
    ("Glovo*07AUG BDF7VKJY*BARCELONA", "Glovo"),
    ("Www.dazn.com", "dazn.com"),
    ("Bizum de AINHOA XIOMARA", "Ainhoa Xiomara"),
    ("Mercadona Oleiros", "Mercadona Oleiros"),
    ("airvpn.org", "airvpn.org"),
    ("", ""),
])
def test_clean(raw, expected):
    assert payees.clean(raw) == expected


def test_split_moves_bizum_concept_to_narration():
    assert payees.split("cena Bizum payment from: Diego O.F.") == ("Diego O.F.", "cena")
    assert payees.split("Sin concepto Bizum payment from: Markos A.") == ("Markos A.", None)
    assert payees.split("Comida Bizum payment to: Martin D.F.") == ("Martin D.F.", "Comida")


def cand(payee, narration=None, amount="-10.00"):
    return Candidate("revolut", "x-1", date(2026, 10, 1), payee, narration or payee,
                     Decimal(amount), "EUR", "Assets:Bank:Revolut:Checking")


def test_prepare_keeps_raw_text_and_applies_rules(root):
    payees.add_rule("^TGSS", payee="TGSS", account="Expenses:Software")
    c = payees.prepare(cand("cena Bizum payment from: Diego O.F."))
    assert (c.payee, c.narration, c.raw["bank_payee"]) == (
        "Diego O.F.", "cena", "cena Bizum payment from: Diego O.F.")
    c = payees.prepare(cand("Mercadona"))
    assert c.payee == "Mercadona" and "bank_payee" not in c.raw
    c = payees.prepare(cand("RCBO.TGSS. COTIZACION 005 R.E.AUTONOMOS"))
    assert c.payee == "TGSS"
    assert categorize.suggest(c, ledger.load()) == ([{"account": "Expenses:Software", "p": 1.0}],
                                                    "rule")


def test_rules_file_and_cli_surface(root):
    assert payees.list_rules() == []
    with pytest.raises(ValueError):
        payees.add_rule("x")
    with pytest.raises(ValueError):
        payees.add_rule("x", account="Expenses:Nope")
    payees.add_rule("steam", payee="Steam", account="Expenses:Entertainment")
    payees.add_rule('quote"d', payee="Q")
    assert payees.list_rules() == [
        {"match": "steam", "payee": "Steam", "account": "Expenses:Entertainment"},
        {"match": 'quote"d', "payee": "Q"}]
    assert payees.match("Wl *steam Purchase")["payee"] == "Steam"
    assert payees.match("Nothing") is None
    assert payees.match("Shop", narration='quote"d thing')["payee"] == "Q"


def test_ingest_books_clean_payee_with_bank_payee_meta(root):
    payees.add_rule("steam", payee="Steam", account="Expenses:Entertainment")
    res = ingest.ingest([Candidate("revolut", "n-9", date(2026, 10, 2), "Wl *steam Purchase",
                                   "Wl *steam Purchase", Decimal("-5"), "EUR",
                                   "Assets:Bank:Revolut:Checking")])
    assert res["booked"][0]["payee"] == "Steam" and res["booked"][0]["auto"] == "rule"
    t = ledger.load().find("n-9")
    assert t.payee == "Steam" and t.meta["bank_payee"] == "Wl *steam Purchase"
    assert t.meta["auto"] == "rule"
    assert "Expenses:Entertainment" in {p.account for p in t.postings}
