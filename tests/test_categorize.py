from datetime import date
from decimal import Decimal

from fin import categorize, ledger
from fin.models import Candidate


def cand(payee, amount, narration=None):
    return Candidate("revolut", f"c-{payee}", date(2026, 10, 1), payee, narration or payee,
                     Decimal(amount), "EUR", "Assets:Bank:Revolut:Checking")


def test_normalize():
    assert categorize.normalize("Glovo*07AUG BDF7VK*BARCELONA") == "glovo 07aug bdf7vk barcelona"
    assert categorize.normalize("Festival Wos 5") == "festival wos"
    assert categorize.normalize("  MERCADONA  ") == "mercadona"


def test_history_decisive_when_dominant(root):
    lg = ledger.load()
    sugg, reason = categorize.suggest(cand("MERCADONA", "-30.00"), lg)
    assert reason == "history"
    assert sugg[0] == {"account": "Expenses:Food:Groceries", "p": 1.0}


def test_single_exact_match_is_decisive_but_fuzzy_single_is_not(root):
    lg = ledger.load()
    assert categorize.suggest(cand("Netflix", "-12.99"), lg)[1] == "history"
    sugg, reason = categorize.suggest(cand("Netflx", "-12.99"), lg)  # typo: fuzzy, single
    assert reason is None and sugg[0]["account"] == "Expenses:Software"


def test_split_history_is_pending_with_ranked_suggestions(root):
    lg = ledger.load()
    sugg, reason = categorize.suggest(cand("Bar Pepe", "-9.00"), lg)
    assert reason is None
    assert {s["account"] for s in sugg} == {"Expenses:Food:Restaurant", "Expenses:Entertainment"}


def test_direction_matters(root):
    lg = ledger.load()
    sugg, reason = categorize.suggest(cand("Mercadona", "+30.00"), lg)
    assert reason is None and sugg == [{"account": "Income:Uncategorized", "p": 0.0}]


def test_unknown_payee_without_llm_key(root):
    lg = ledger.load()
    sugg, reason = categorize.suggest(cand("Totally New Shop", "-5.00"), lg)
    assert reason is None and sugg == [{"account": "Expenses:Uncategorized", "p": 0.0}]


def test_llm_books_only_confident_answers(root, monkeypatch):
    from fin import categorize as cz
    from fin import llm

    calls = []

    def answer(confidence):
        def fake(txn, accounts):
            calls.append((txn, accounts))
            return llm.AccountChoice(account="Expenses:Entertainment", confidence=confidence)
        return fake

    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "choose_account", answer("high"))
    lg = ledger.load()
    sugg, reason = cz.suggest(cand("Totally New Shop", "-5.00"), lg)
    assert reason == "llm" and sugg[0] == {"account": "Expenses:Entertainment", "p": 0.9}
    assert calls[0][0]["payee"] == "Totally New Shop"
    assert "Expenses:Entertainment" in calls[0][1]
    # low confidence: suggested, but left for review
    monkeypatch.setattr(llm, "choose_account", answer("low"))
    sugg, reason = cz.suggest(cand("Another Shop", "-5.00"), lg)
    assert reason is None and sugg[0]["account"] == "Expenses:Entertainment"
    # an API failure leaves it for review
    monkeypatch.setattr(llm, "choose_account", lambda *a: 1 / 0)
    assert cz.suggest(cand("Third Shop", "-5.00"), lg)[1] is None
    # history still wins without asking
    assert cz.suggest(cand("Mercadona", "-30.00"), lg)[1] == "history"
