"""Fixtures for the analytics/API tests: a tiny inline ledger under a temp FIN_ROOT.

Imported explicitly by the test modules that use them (conftest.py belongs to the pipeline tests).
"""

import shutil
from pathlib import Path

import pytest

FIXTURE = """
option "operating_currency" "EUR"
option "inferred_tolerance_default" "*:0.01"

2024-01-01 open Assets:Bank:Revolut:Checking EUR
2024-01-01 open Assets:Investment:Revolut:Stocks NVDA
2024-01-01 open Assets:Investment:Indexa INDEXA
2024-01-01 open Assets:Crypto:Wallet:BTC BTC
2024-01-01 open Income:Salary:Example EUR
2024-01-01 open Expenses:Food:Groceries EUR
2024-01-01 open Expenses:Food:Restaurant EUR
2024-01-01 open Expenses:Software EUR
2024-01-01 open Expenses:Uncategorized EUR
2024-01-01 open Equity:Opening-Balances EUR,USD

2026-01-01 * "Opening Balance" ""
  Equity:Opening-Balances        -1000.00 EUR
  Assets:Bank:Revolut:Checking    1000.00 EUR

2026-01-05 * "Opening Balance" "NVDA"
  Equity:Opening-Balances         -200.00 USD
  Assets:Investment:Revolut:Stocks   2 NVDA {100.00 USD}

2026-01-05 * "Opening Balance" "BTC"
  Equity:Opening-Balances         -500.00 EUR
  Assets:Crypto:Wallet:BTC         0.01 BTC {50000.00 EUR}

2026-01-05 * "Indexa" "deposit"
  Assets:Investment:Indexa          10 INDEXA {10.00 EUR}
  Assets:Bank:Revolut:Checking    -100.00 EUR

2026-07-01 * "Example" "Salary"
  transaction_id: "s7"
  source: "revolut"
  Income:Salary:Example             -2000.00 EUR
  Assets:Bank:Revolut:Checking    2000.00 EUR

2026-07-03 * "Netflix" "Netflix"
  transaction_id: "n7"
  source: "revolut"
  Expenses:Software                 12.99 EUR
  Assets:Bank:Revolut:Checking     -12.99 EUR

2026-07-10 * "Lidl" "Lidl"
  transaction_id: "l7"
  source: "revolut"
  auto: "history"
  Expenses:Food:Groceries           40.00 EUR
  Assets:Bank:Revolut:Checking     -40.00 EUR

2026-08-01 * "Example" "Salary"
  transaction_id: "s8"
  source: "revolut"
  Income:Salary:Example             -2000.00 EUR
  Assets:Bank:Revolut:Checking    2000.00 EUR

2026-08-03 * "Netflix" "Netflix"
  transaction_id: "n8"
  source: "revolut"
  Expenses:Software                 12.99 EUR
  Assets:Bank:Revolut:Checking     -12.99 EUR

2026-08-15 * "Lidl" "Lidl"
  transaction_id: "l8"
  source: "revolut"
  Expenses:Food:Groceries           60.00 EUR
  Assets:Bank:Revolut:Checking     -60.00 EUR

2026-09-01 * "Example" "Salary"
  transaction_id: "s9"
  source: "revolut"
  Income:Salary:Example             -2000.00 EUR
  Assets:Bank:Revolut:Checking    2000.00 EUR

2026-09-03 * "Netflix" "Netflix"
  transaction_id: "n9"
  source: "revolut"
  Expenses:Software                 12.99 EUR
  Assets:Bank:Revolut:Checking     -12.99 EUR

2026-09-20 * "Bar Pepe" "Bar Pepe"
  transaction_id: "b9"
  source: "revolut"
  Expenses:Food:Restaurant          25.00 EUR
  Assets:Bank:Revolut:Checking     -25.00 EUR

2026-10-03 * "Netflix" "Netflix"
  transaction_id: "n10"
  source: "revolut"
  auto: "llm"
  Expenses:Software                 12.99 EUR
  Assets:Bank:Revolut:Checking     -12.99 EUR

2026-10-05 * "Lidl" "Lidl"
  transaction_id: "l10"
  source: "revolut"
  Expenses:Food:Groceries           30.00 EUR
  Assets:Bank:Revolut:Checking     -30.00 EUR

2026-01-05 price NVDA 100.00 USD
2026-01-05 price EUR 1.00 USD
2026-01-05 price BTC 50000.00 EUR
2026-01-05 price INDEXA 10.00 EUR
2026-09-30 price NVDA 150.00 USD
2026-09-30 price EUR 1.25 USD
2026-09-30 price BTC 60000.00 EUR
2026-09-30 price INDEXA 11.00 EUR
"""


@pytest.fixture(scope="session")
def ui_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("uiroot")
    (root / "ledger" / "transactions" / "banks").mkdir(parents=True)
    (root / "ledger" / "main.beancount").write_text(FIXTURE)
    (root / "config.toml").write_text('ledger = "ledger/main.beancount"\ndata_dir = "data"\n')
    return root


@pytest.fixture
def fin_root(ui_root, monkeypatch) -> Path:
    """Point fin.config/fin.ledger at the inline fixture ledger for one test."""
    from fin import config, ledger

    monkeypatch.setenv("FIN_ROOT", str(ui_root))
    monkeypatch.setattr(config, "ROOT", ui_root)
    monkeypatch.setattr(ledger, "ROOT", ui_root)
    config.config.cache_clear()
    ledger._cache = None
    yield ui_root
    config.config.cache_clear()
    ledger._cache = None


@pytest.fixture
def ledger(fin_root):
    from fin.ledger import load

    return load()


@pytest.fixture(scope="session")
def real_ledger_root(tmp_path_factory) -> Path | None:
    """Temp copy of the repo's real ledger (read-only sanity checks), or None if absent."""
    src = Path(__file__).resolve().parent.parent / "ledger"
    if not (src / "main.beancount").exists():
        return None
    root = tmp_path_factory.mktemp("realroot")
    shutil.copytree(src, root / "ledger", ignore=shutil.ignore_patterns("documents"))
    return root
