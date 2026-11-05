import os
import tomllib
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(os.environ.get("FIN_ROOT", Path(__file__).resolve().parent.parent))
DEFAULT_BASE_URL = "http://127.0.0.1:8742"


@cache
def config() -> dict:
    path = ROOT / "config.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}


def path(key: str, default: str) -> Path:
    p = Path(config().get(key, default)).expanduser()
    return p if p.is_absolute() else ROOT / p


def ledger_file() -> Path:
    return path("ledger", "ledger/main.beancount")


def data_dir() -> Path:
    d = path("data_dir", "data")
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def section(name: str) -> dict:
    return config().get(name, {})


def secret(section_name: str, key: str, env: str) -> str | None:
    return os.environ.get(env) or section(section_name).get(key)


def web_url(route: str = "") -> str:
    """Public URL of a web app route, e.g. web_url("/review")."""
    return section("web").get("base_url", DEFAULT_BASE_URL).rstrip("/") + route


def web_prefix() -> str:
    """Path the app is mounted under behind the tailnet proxy ("/fin"), "" at the root."""
    return urlsplit(web_url()).path.rstrip("/")
