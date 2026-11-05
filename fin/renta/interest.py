"""Interest arrives net of the 19% Spanish withholding; book it gross plus the retención."""

from decimal import Decimal

from fin.models import Posting
from fin.renta import params_2026 as P
from fin.renta.securities import gross_up

INCOME = "Income:Interest:Savings"
WITHHELD = "Expenses:Taxes:IRPF:Withheld"


def postings(net: Decimal, currency: str = "EUR") -> list[Posting]:
    """Income and withholding legs for a net interest payment (the asset leg is the caller's)."""
    gross, withheld = gross_up(net, P.RETENCION_AHORRO)
    return [Posting(INCOME, -gross, currency), Posting(WITHHELD, withheld, currency)]


def is_net_booking(t) -> Decimal | None:
    """The net amount if `t` books interest the old way (income only, no withholding leg)."""
    income = [p for p in t.postings if p.account == INCOME]
    if len(income) != 1 or any(p.account == WITHHELD for p in t.postings):
        return None
    return -income[0].units.number
