"""Indexa Capital: daily valuation of the INDEXA commodity.

Model: 1 INDEXA = 1 EUR contributed (bank transfers to Indexa are booked as
`N INDEXA {1 EUR}`), and `price INDEXA <market value / units> EUR` each day,
so the position's market value tracks the real portfolio and its cost the contributions.
"""

from datetime import date
from decimal import Decimal

import requests
from beancount.core import data

from fin import config, ledger
from fin.config import ledger_file

API = "https://api.indexacapital.com"
COMMODITY = "INDEXA"


def token() -> str | None:
    return config.secret("indexa", "token", "INDEXA_TOKEN")


def account() -> str:
    return config.section("indexa").get("account", "Assets:Investment:Indexa")


def _get(path: str) -> dict:
    r = requests.get(API + path, headers={"X-AUTH-TOKEN": token(), "Accept": "application/json"},
                     timeout=30)
    r.raise_for_status()
    return r.json()


def accounts() -> list[str]:
    return [a["account_number"] for a in _get("/users/me").get("accounts", [])]


def portfolio_value() -> Decimal:
    """Total market value (EUR) over all Indexa accounts."""
    total = Decimal(0)
    for n in accounts():
        total += Decimal(str(_get(f"/accounts/{n}/portfolio")["portfolio"]["total_amount"]))
    return total


def units(lg: ledger.Ledger) -> Decimal:
    return sum((p.units.number for t in lg.transactions for p in t.postings
                if p.account == account() and p.units.currency == COMMODITY), Decimal(0))


def update(on: date | None = None) -> dict:
    if not token():
        return {"skipped": "indexa: no token ([indexa].token or INDEXA_TOKEN)"}
    on = on or date.today()
    lg = ledger.load()
    value, n = portfolio_value(), units(lg)
    out = {"value_eur": str(value), "units": str(n)}
    if n <= 0:
        out["skipped"] = f"no {COMMODITY} units in ledger: book transfers to {account()}"
        return out
    if any(isinstance(e, data.Price) and e.currency == COMMODITY and e.date == on
           for e in lg.entries):
        return {**out, "written": 0}
    price = (value / n).quantize(Decimal("0.000001"))
    ledger.append_raw(ledger_file().parent / "prices" / "prices.beancount",
                      f"{on} price {COMMODITY:<10} {price:>18} EUR")
    return {**out, "price": str(price), "written": 1}
