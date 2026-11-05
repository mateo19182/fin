"""What each held ticker is: paying country (dividend withholding) and shares vs ETF/IIC.

Unknown tickers default to US shares, which the report flags. Keep this map explicit.
"""

from decimal import Decimal

from fin.renta import params_2026 as P

# ticker -> (country of the paying entity, "stock" | "etf")
TICKERS = {
    "AMD": ("US", "stock"), "AVGO": ("US", "stock"), "COHR": ("US", "stock"),
    "CRWV": ("US", "stock"), "GOOG": ("US", "stock"), "LITE": ("US", "stock"),
    "NET": ("US", "stock"), "NVDA": ("US", "stock"), "SNPS": ("US", "stock"),
    "SNDK": ("US", "stock"), "AEVA": ("US", "stock"), "AXTI": ("US", "stock"),
    "QMCO": ("US", "stock"), "PSIX": ("US", "stock"), "TTMI": ("US", "stock"),
    "NBIS": ("US", "stock"),  # Nebius Group N.V. (NL) listed on Nasdaq; no dividends
    "NXPI": ("NL", "stock"),  # NXP Semiconductors N.V., Dutch withholding 15%
    "BSI": ("NL", "stock"),  # BE Semiconductor Industries N.V. (Xetra listing)
    "TSM": ("TW", "stock"),  # TSMC ADR: Taiwan withholds 21%
    "TSEM": ("IL", "stock"),  # Tower Semiconductor (Israel); no dividends
    "AIXA": ("DE", "stock"),  # Aixtron SE
    "ENR1": ("DE", "stock"),  # Siemens Energy AG
    "EUNK": ("IE", "etf"),  # iShares Core MSCI Europe UCITS ETF (Acc)
    "MEQA": ("IE", "etf"),  # ETF per holdings notes; verify ISIN/issuer
}


def info(ticker: str) -> tuple[str, str, bool]:
    """(country, kind, known?)"""
    if ticker in TICKERS:
        return (*TICKERS[ticker], True)
    return "US", "stock", False


def withholding(ticker: str) -> tuple[Decimal, Decimal | None, str]:
    """(rate withheld at source, treaty cap or None, country) for a dividend of `ticker`."""
    country = info(ticker)[0]
    w = P.FOREIGN_WITHHOLDING.get(country, {"default": Decimal(0), "treaty": None})
    return w["default"], w["treaty"], country


def gross_up(net: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    """(gross, withheld) from a net amount and the withholding rate, exact to the cent."""
    gross = (net / (1 - rate)).quantize(Decimal("0.01"))
    return gross, gross - net
