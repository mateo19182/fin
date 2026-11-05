"""Account balances valued in EUR at a date, and the asset groups the app reports on."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from beancount.core import inventory

from fin import ledger

ZERO = Decimal(0)
GROUPS = (  # first prefix match wins
    ("indexa", "Assets:Investment:Indexa"),
    ("stocks", "Assets:Investment"),
    ("crypto", "Assets:Crypto"),
    ("receivables", "Assets:Receivable"),
    ("cash", "Assets:"),
)
LABELS = {"cash": "Cash", "stocks": "Revolut", "indexa": "Indexa", "crypto": "Crypto",
          "receivables": "Receivables"}
INVESTMENT_GROUPS = ("stocks", "indexa", "crypto")


def group_of(account: str) -> str | None:
    return next((g for g, prefix in GROUPS if account.startswith(prefix)), None)


def is_investment(account: str) -> bool:
    return group_of(account) in INVESTMENT_GROUPS


def inventories(lg: ledger.Ledger, on: date, prefix: str = "Assets:") -> dict:
    """account -> Inventory of positions held at the end of `on`."""
    inv: dict[str, inventory.Inventory] = defaultdict(inventory.Inventory)
    for t in lg.transactions:
        if t.date > on:
            break
        for p in t.postings:
            if p.account.startswith(prefix) and p.units.number is not None:
                inv[p.account].add_position(p)
    return inv


def cost_eur(lg: ledger.Ledger, pos, on: date | None = None) -> Decimal | None:
    if pos.cost is None:
        return None
    return lg.to_eur(pos.units.number * pos.cost.number, pos.cost.currency, on)


def value(lg: ledger.Ledger, inv: inventory.Inventory, on: date) -> Decimal:
    """EUR market value. Without a price on `on`: cost, then the latest price known at all."""
    total = ZERO
    for pos in inv:
        v = lg.to_eur(pos.units.number, pos.units.currency, on)
        if v is None and pos.cost is not None:
            v = cost_eur(lg, pos, on)
            if v is None:  # before the first FX price: convert cost at the latest rate
                v = cost_eur(lg, pos)
        if v is None:  # before the first price of a commodity held without cost
            v = lg.to_eur(pos.units.number, pos.units.currency)
        total += v or ZERO
    return total


def account_values(lg: ledger.Ledger, on: date, prefix: str = "Assets:") -> dict[str, Decimal]:
    return {a: value(lg, inv, on) for a, inv in inventories(lg, on, prefix).items()}


def group_values(lg: ledger.Ledger, on: date) -> dict[str, Decimal]:
    out = {g: ZERO for g, _ in GROUPS}
    for a, v in account_values(lg, on).items():
        out[group_of(a)] += v
    return out


def q(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01")))
