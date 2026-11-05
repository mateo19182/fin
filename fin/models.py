from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class Posting:
    account: str
    amount: Decimal | None = None  # None lets beancount infer the balancing leg
    currency: str = "EUR"
    cost: str | None = None  # raw cost spec, e.g. "{123.45 USD}"
    price: str | None = None  # raw price spec, e.g. "@ 1.08 USD"


@dataclass
class Txn:
    date: date
    payee: str
    narration: str
    postings: list[Posting]
    meta: dict[str, str] = field(default_factory=dict)
    flag: str = "*"


@dataclass
class Candidate:
    """A transaction seen at a source (bank, CSV, API) that is not yet in the ledger.

    `amount` is signed from the point of view of `account` (negative = money out).
    """

    source: str  # "revolut", "caixa_rural", "revolut_invest", ...
    external_id: str
    date: date
    payee: str
    narration: str
    amount: Decimal
    currency: str
    account: str  # ledger asset account the money moved in/out of
    raw: dict = field(default_factory=dict)
