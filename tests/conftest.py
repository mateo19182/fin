import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = """
ledger = "ledger/main.beancount"
data_dir = "data"
docs_dir = "docs"

[categorize]
auto_threshold = 0.85

[enable_banking.banks.revolut]
name = "Revolut"
country = "ES"
account = "Assets:Bank:Revolut:Checking"

[enable_banking.banks.caixa_rural]
name = "Caixa Rural Galega"
country = "ES"
account = "Assets:Bank:CaixaRural:Checking"

[indexa]
account = "Assets:Investment:Indexa"
"""


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A throwaway FIN_ROOT with the fixture ledger, a git repo and no API keys."""
    shutil.copytree(FIXTURES / "ledger", tmp_path / "ledger")
    (tmp_path / "config.toml").write_text(CONFIG)
    monkeypatch.setenv("FIN_ROOT", str(tmp_path))
    monkeypatch.setenv("FIN_NOTIFY_DRY_RUN", "1")
    for var in ("ANTHROPIC_API_KEY", "INDEXA_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.com")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    from fin import categorize, config, ledger

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    config.config.cache_clear()
    ledger._cache = None
    categorize._hist_cache = None
    yield tmp_path
    config.config.cache_clear()
    ledger._cache = None
    categorize._hist_cache = None
