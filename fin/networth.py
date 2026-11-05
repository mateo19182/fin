"""Monthly net worth by asset group, and where each month's change came from.

saved         = income − expenses
contributions = net EUR moved from funding accounts (bank, cash, transfer clearing) into
                investment accounts (stocks, indexa, crypto) — withdrawals count negative
market        = change in investment value not explained by contributions (opening balances
                therefore show up as "market" in their month)
"""

from datetime import date, timedelta
from decimal import Decimal

from fin import analytics, balances, ledger
from fin.balances import INVESTMENT_GROUPS, ZERO, is_investment, q

FUNDING = ("Assets:Bank:", "Assets:Cash:", "Assets:Transfer:")
_cache: dict[tuple, dict] = {}


def flows(lg: ledger.Ledger, start: date, end: date) -> dict[str, Decimal]:
    """{"saved", "contributions", "income", "expenses"} in EUR for [start, end)."""
    income, expenses = analytics.income_expenses(lg, start, end - timedelta(days=1))
    contrib = ZERO
    for t in lg.transactions:
        if start <= t.date < end and any(is_investment(p.account) for p in t.postings):
            for p in t.postings:
                if p.account.startswith(FUNDING):
                    contrib -= lg.to_eur(p.units.number, p.units.currency, t.date) or ZERO
    return {"income": income, "expenses": expenses, "saved": income - expenses,
            "contributions": contrib}


def month(lg: ledger.Ledger, ym: str, today: date | None = None) -> dict:
    """One month's row; the current month is valued at `today`."""
    today = today or date.today()
    start, end = analytics.month_bounds(ym)
    on = min(end - timedelta(days=1), today)
    key = (id(lg), ym, on)
    if key in _cache:
        return _cache[key]
    if _cache and next(iter(_cache))[0] != id(lg):  # ledger reloaded: drop stale rows
        _cache.clear()
    now, before = balances.group_values(lg, on), balances.group_values(lg, start - timedelta(1))
    f = flows(lg, start, min(end, today + timedelta(days=1)))
    invest_now = sum(now[g] for g in INVESTMENT_GROUPS)
    invest_before = sum(before[g] for g in INVESTMENT_GROUPS)
    total, prev_total = sum(now.values(), ZERO), sum(before.values(), ZERO)
    row = {
        "month": ym,
        "groups": {g: q(v) for g, v in now.items()},
        "total": q(total),
        "change": q(total - prev_total),
        "saved": q(f["saved"]),
        "contributions": q(f["contributions"]),
        "market": q(invest_now - invest_before - f["contributions"]),
        "income": q(f["income"]),
        "expenses": q(f["expenses"]),
    }
    _cache[key] = row
    return row


def series(months: int = 24, today: date | None = None) -> list[dict]:
    """Last `months` full months plus the current one, oldest first."""
    lg = ledger.load()
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for i in range(months, -1, -1):
        k = y * 12 + m - 1 - i
        out.append(month(lg, f"{k // 12}-{k % 12 + 1:02d}", today))
    return out
