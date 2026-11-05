"""Daily prices for every commodity currently held → ledger/prices/prices.beancount."""

import math
import re
from datetime import date, datetime
from decimal import Decimal

from beancount.core import convert, data, inventory

from fin import ledger
from fin.config import ledger_file

SOURCE = re.compile(r"^(\w+):yahoo/(.+)$")


def held(lg: ledger.Ledger) -> set[str]:
    inv = inventory.Inventory()
    for t in lg.transactions:
        for p in t.postings:
            if p.account.startswith("Assets:"):
                inv.add_position(p)
    units = inv.reduce(convert.get_units)
    return {pos.units.currency for pos in units if pos.units.number} - {"EUR", "USD"}


def symbols(lg: ledger.Ledger) -> dict[str, tuple[str, str]]:
    """commodity → (quote currency, yahoo symbol), from commodity directives' `price` meta."""
    out = {"EUR": ("USD", "EURUSD=X")}
    for e in lg.entries:
        if isinstance(e, data.Commodity) and (m := SOURCE.match(str(e.meta.get("price", "")))):
            out[e.currency] = (m.group(1), m.group(2))
    for c in held(lg):
        out.setdefault(c, ("USD", c))
    return out


def _last_close(tickers: list[str]) -> dict[str, float]:
    import warnings

    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(tickers, period="5d", progress=False, auto_adjust=False,
                         group_by="column")
    closes = df["Close"] if "Close" in df else df
    out = {}
    for t in tickers:
        series = closes[t] if t in closes else closes
        vals = [v for v in series.tolist() if v is not None and not math.isnan(v)]
        if vals:
            out[t] = vals[-1]
    return out


def update(on: date | None = None) -> int:
    """Append today's prices for held commodities (+EUR/USD). Returns the number written."""
    lg = ledger.load()
    on = on or date.today()
    wanted = {c: s for c, s in symbols(lg).items() if c in held(lg) or c == "EUR"}
    have = {e.currency for e in lg.entries if isinstance(e, data.Price) and e.date == on}
    todo = {c: s for c, s in wanted.items() if c not in have}
    if not todo:
        return 0
    quotes = _last_close(sorted({sym for _, sym in todo.values()}))
    lines = []
    for c, (quote, sym) in sorted(todo.items()):
        if sym in quotes:
            price = Decimal(str(quotes[sym])).quantize(Decimal("0.00000001"))
            lines.append(f"{on} price {c:<10} {price:>18} {quote}")
    if lines:
        text = f"\n; Prices updated: {datetime.now():%Y-%m-%d %H:%M:%S}\n" + "\n".join(lines)
        ledger.append_raw(ledger_file().parent / "prices" / "prices.beancount", text)
    return len(lines)

