"""Read-only numbers over the ledger. Every value is EUR unless noted; dates are inclusive
unless a function says [start, end)."""

import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from beancount.core import data

from fin import balances
from fin.balances import INVESTMENT_GROUPS, LABELS, ZERO, group_of, is_investment
from fin.ledger import Ledger, txn_id
from fin.payees import normalize


def _q(x: Decimal | None, places: int = 2) -> float | None:
    return None if x is None else round(float(x), places)


# --- months -----------------------------------------------------------------


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def month_end(d: date) -> date:
    return next_month(d) - timedelta(days=1)


def shift_months(d: date, n: int) -> date:
    """First day of the month n months after d's month (n may be negative)."""
    i = d.year * 12 + d.month - 1 + n
    return date(i // 12, i % 12 + 1, 1)


def months_in(start: date, end: date) -> int:
    """Calendar months touched by [start, end]."""
    return (end.year - start.year) * 12 + end.month - start.month + 1


def month_range(start: date, end: date) -> list[date]:
    return [shift_months(start, i) for i in range(months_in(start, end))]


def month_bounds(month: str | None, today: date | None = None) -> tuple[date, date]:
    """[start, end) of `month` (YYYY-MM); default: the month before `today`."""
    if month:
        y, m = (int(x) for x in month.split("-"))
        start = date(y, m, 1)
    else:
        start = shift_months(today or date.today(), -1)
    return start, next_month(start)


# --- periods ----------------------------------------------------------------

PRESETS = ("1m", "3m", "6m", "ytd", "1y", "all")


def shift_period(start: date, end: date, months: int) -> tuple[date, date]:
    """Move a month-aligned period by n months. A partial last month (end before the
    month's last day) keeps the same day of month, clipped to the target month."""
    s = shift_months(start, months)
    last = shift_months(end, months)
    if end == month_end(end):
        return s, month_end(last)
    return s, last.replace(day=min(end.day, month_end(last).day))


def previous_period(start: date, end: date) -> tuple[date, date]:
    return shift_period(start, end, -months_in(start, end))


def year_ago(start: date, end: date) -> tuple[date, date] | None:
    """Same period a year earlier; None once the period itself spans a year or more."""
    return shift_period(start, end, -12) if months_in(start, end) < 12 else None


def comparisons(start: date, end: date, first: date | None,
                keys=("prev", "yoy")) -> dict[str, tuple[date, date] | None]:
    """Comparison spans for a period; None when undefined or before the first txn
    (a year-ago span must lie entirely after it, or partial data reads as huge growth)."""
    out = {}
    for key, span in (("prev", previous_period(start, end)), ("yoy", year_ago(start, end))):
        if key in keys:
            edge = span and (span[0] if key == "yoy" else span[1])
            out[key] = None if span is None or (first and edge < first) else span
    return out


def resolve_period(range_: str, today: date | None = None, first: date | None = None) -> dict:
    """Preset (1m, 3m, 6m, ytd, 1y, all) or "YYYY-MM..YYYY-MM" -> month-aligned dates.

    Comparison periods are None when they end before the ledger's first transaction."""
    today = today or date.today()
    r = range_.lower().strip()
    if r == "all":
        start = month_start(first or today)
    elif r == "ytd":
        start = date(today.year, 1, 1)
    elif r in PRESETS:
        start = shift_months(today, 1 - int(r[:-1]) * (12 if r.endswith("y") else 1))
    elif ".." in r:
        a, b = r.split("..", 1)
        start = date.fromisoformat(a + "-01")
        end = min(month_end(date.fromisoformat(b + "-01")), today)
        if start > end:
            raise ValueError("start after end")
        return _period(r, start, end, first)
    else:
        raise ValueError(f"unknown range {range_!r}")
    return _period(r, start, today, first)


def _period(range_: str, start: date, end: date, first: date | None) -> dict:
    spans = {k: v and {"start": v[0].isoformat(), "end": v[1].isoformat()}
             for k, v in comparisons(start, end, first).items()}
    return {"range": range_, "start": start.isoformat(), "end": end.isoformat(),
            "months": months_in(start, end), **spans}


def first_date(ledger: Ledger) -> date | None:
    t = ledger.transactions
    return t[0].date if t else None


def _points(start: date, end: date) -> list[date]:
    """Sample dates for a series over [start, end]: the day before start as baseline, then
    daily (<= 1 month), weekly (<= 12 months) or month ends."""
    n = months_in(start, end)
    if n > 12:
        pts = [min(month_end(m), end) for m in month_range(start, end)]
    else:
        step = 1 if n <= 1 else 7
        pts = [end - timedelta(days=i) for i in range(0, (end - start).days + 1, step)][::-1]
    return [start - timedelta(days=1)] + pts


# --- net worth --------------------------------------------------------------


def net_worth(ledger: Ledger, on: date | None = None) -> dict:
    on = on or date.today()
    groups = balances.group_values(ledger, on)
    assets = sum(groups.values(), ZERO)
    liabilities = -sum(balances.account_values(ledger, on, "Liabilities:").values(), ZERO)
    return {
        "date": on.isoformat(),
        "total": _q(assets - liabilities),
        "assets": _q(assets),
        "liabilities": _q(liabilities),
        "groups": {g: _q(v) for g, v in groups.items()},
    }


def net_worth_series(ledger: Ledger, start: date, end: date) -> list[dict]:
    """Net worth sampled over the period; the first point is the day before start."""
    return [net_worth(ledger, on) for on in _points(start, end)]


# --- income / expenses ------------------------------------------------------


def _flows(ledger: Ledger, start: date, end: date):
    """Yield (txn, posting, eur_amount) for Income/Expenses postings in [start, end]."""
    for t in ledger.transactions:
        if t.date < start:
            continue
        if t.date > end:
            break
        for p in t.postings:
            if p.account.startswith(("Income:", "Expenses:")) and p.units.number is not None:
                v = ledger.to_eur(p.units.number, p.units.currency, t.date)
                if v is not None:
                    yield t, p, v


def income_expenses(ledger: Ledger, start: date, end: date) -> tuple[Decimal, Decimal]:
    income = expenses = ZERO
    for _, p, v in _flows(ledger, start, end):
        if p.account.startswith("Income:"):
            income -= v
        else:
            expenses += v
    return income, expenses


def account_flows(ledger: Ledger, start: date, end: date) -> tuple[dict, dict, dict]:
    """(income by account, expenses by account, expenses by payee) in [start, end]."""
    income: dict[str, Decimal] = defaultdict(Decimal)
    expenses: dict[str, Decimal] = defaultdict(Decimal)
    payees: dict[str, Decimal] = defaultdict(Decimal)
    for t, p, v in _flows(ledger, start, end):
        if p.account.startswith("Income:"):
            income[p.account] -= v
        else:
            expenses[p.account] += v
            payees[t.payee or "?"] += v
    return income, expenses, payees


def expense_of(ledger: Ledger, t: data.Transaction) -> Decimal:
    """EUR total of a transaction's Expenses postings."""
    return sum((ledger.to_eur(p.units.number, p.units.currency, t.date) or ZERO
                for p in t.postings if p.account.startswith("Expenses:")), ZERO)


def totals(ledger: Ledger, start: date, end: date) -> dict:
    inc, exp = income_expenses(ledger, start, end)
    return {"income": _q(inc), "expenses": _q(exp), "savings": _q(inc - exp)}


def cashflow_series(ledger: Ledger, start: date, end: date, bucket: str = "month") -> list[dict]:
    """Income/expenses per month ("2026-03") or per calendar quarter ("2026-Q1")."""
    rows: dict[str, list[Decimal]] = {}
    for m in month_range(start, end):
        key = m.strftime("%Y-%m") if bucket == "month" else f"{m.year}-Q{(m.month - 1) // 3 + 1}"
        inc, exp = income_expenses(ledger, m, min(month_end(m), end))
        acc = rows.setdefault(key, [ZERO, ZERO])
        acc[0] += inc
        acc[1] += exp
    return [{"period": k, "income": _q(i), "expenses": _q(e), "savings": _q(i - e)}
            for k, (i, e) in rows.items()]


def with_comparison(ledger: Ledger, start: date, end: date, fn, compare: set[str]) -> dict:
    """{"prev": fn(prev period), "yoy": fn(same period last year)} for the requested keys."""
    return {k: v and fn(*v)
            for k, v in comparisons(start, end, first_date(ledger), compare).items()}


def categories(ledger: Ledger, start: date, end: date, kind: str = "Expenses") -> list[dict]:
    """Totals per leaf account rolled up into top-level categories (e.g. Expenses:Food)."""
    leaves: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    sign = 1 if kind == "Expenses" else -1
    for _, p, v in _flows(ledger, start, end):
        if p.account.startswith(kind + ":"):
            leaves[p.account] += sign * v
            counts[p.account] += 1
    parents: dict[str, dict] = {}
    for acc, total in leaves.items():
        top = ":".join(acc.split(":")[:2])
        parent = parents.setdefault(
            top, {"account": top, "total": ZERO, "count": 0, "children": []})
        parent["total"] += total
        parent["count"] += counts[acc]
        parent["children"].append({"account": acc, "total": _q(total), "count": counts[acc]})
    grand = sum((p["total"] for p in parents.values()), ZERO)
    out = []
    for p in sorted(parents.values(), key=lambda x: -x["total"]):
        p["children"].sort(key=lambda c: -c["total"])
        out.append({**p, "total": _q(p["total"]),
                    "share": _q(p["total"] / grand, 4) if grand else 0.0})
    return out


def categories_compared(ledger: Ledger, start: date, end: date, kind: str = "Expenses",
                        compare: set[str] = frozenset({"prev", "yoy"})) -> list[dict]:
    """categories() for the period, each row (and child) carrying the same account's total in
    the previous period / a year earlier (None when that period has no data). Categories only
    present in a comparison period are appended with total 0."""
    rows = categories(ledger, start, end, kind)
    others = with_comparison(ledger, start, end,
                             lambda s, e: categories(ledger, s, e, kind), compare)
    by_acc = {r["account"]: r for r in rows}
    for key, other in others.items():
        index = {} if other is None else {c["account"]: c for c in other}
        kids = {ch["account"]: ch["total"] for c in index.values() for ch in c["children"]}
        for acc in index:
            if acc not in by_acc:
                by_acc[acc] = {"account": acc, "total": 0.0, "count": 0, "share": 0.0,
                               "children": []}
                rows.append(by_acc[acc])
        for r in rows:
            r[key] = None if other is None else index.get(r["account"], {}).get("total", 0.0)
            for ch in r["children"]:
                ch[key] = None if other is None else kids.get(ch["account"], 0.0)
    return rows


def portfolio_series(ledger: Ledger, start: date, end: date) -> list[dict]:
    """Investment value and cost sampled over the period (first point = day before start)."""
    out = []
    for on in _points(start, end):
        value = cost = ZERO
        for account, inv in balances.inventories(ledger, on).items():
            if not is_investment(account):
                continue
            value += balances.value(ledger, inv, on)
            cost += sum((balances.cost_eur(ledger, pos, on) or ZERO for pos in inv), ZERO)
        out.append({"date": on.isoformat(), "value": _q(value), "cost": _q(cost)})
    return out


# --- transactions -----------------------------------------------------------

BANK_PREFIXES = ("Assets:Bank:", "Assets:Cash:")


def _summarize(ledger: Ledger, t: data.Transaction) -> dict:
    bank = [p for p in t.postings if p.account.startswith(BANK_PREFIXES)]
    cat = [p for p in t.postings if p.account.startswith(("Expenses:", "Income:"))]
    other = [p for p in t.postings if p not in bank]
    main = cat[0] if cat else (other[0] if other else t.postings[0])
    if bank:
        amount = sum((ledger.to_eur(p.units.number, p.units.currency, t.date) or ZERO
                      for p in bank if p.units.number is not None), ZERO)
    else:
        amount = -(ledger.to_eur(main.units.number, main.units.currency, t.date) or ZERO)
    return {
        "id": txn_id(t),
        "date": t.date.isoformat(),
        "payee": t.payee or "",
        "narration": t.narration or "",
        "amount": _q(amount),
        "account": main.account,
        "bank": bank[0].account if bank else None,
        "source": t.meta.get("source"),
        "auto": t.meta.get("auto"),
        "accounts": [p.account for p in t.postings],
    }


def transactions(ledger: Ledger, start: date | None = None, end: date | None = None,
                 account: str | None = None, q: str | None = None, auto_only: bool = False,
                 limit: int = 500, offset: int = 0) -> dict:
    needle = (q or "").lower().strip()
    rows = []
    for t in reversed(ledger.transactions):
        if start and t.date < start:
            continue
        if end and t.date > end:
            continue
        if auto_only and "auto" not in t.meta:
            continue
        if account and not any(p.account.startswith(account) for p in t.postings):
            continue
        if needle and needle not in f"{t.payee or ''} {t.narration or ''}".lower():
            continue
        rows.append(_summarize(ledger, t))
    return {"total": len(rows), "items": rows[offset:offset + limit]}


def recent_auto(ledger: Ledger, days: int = 30, today: date | None = None) -> list[dict]:
    today = today or date.today()
    return transactions(ledger, start=today - timedelta(days=days), auto_only=True)["items"]


# --- holdings ---------------------------------------------------------------


def _period_flows(ledger: Ledger, start: date, end: date) -> dict[tuple[str, str], Decimal]:
    """EUR value of units moved into (+) or out of (-) each holding during the period."""
    flows: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for t in ledger.transactions:
        if t.date < start or t.date > end:
            continue
        for p in t.postings:
            if not is_investment(p.account) or p.units is None or p.units.number is None:
                continue
            v = ledger.to_eur(p.units.number, p.units.currency, t.date)
            if v is None:
                v = balances.cost_eur(ledger, p, t.date)
            flows[(LABELS[group_of(p.account)], p.units.currency)] += v or ZERO
    return flows


def _period_return(value: Decimal, start_value: Decimal, flow: Decimal) -> dict:
    pl = value - start_value - flow
    base = start_value + max(flow, ZERO)
    return {"period_pl": _q(pl), "period_pct": _q(pl / base * 100, 2) if base else None}


def holdings(ledger: Ledger, on: date | None = None, start: date | None = None) -> dict:
    """Positions at `on`; with `start`, also each position's return over [start, on],
    net of buys and sells in between (so new money is not counted as gain)."""
    on = on or date.today()
    if start:
        before = holdings(ledger, start - timedelta(days=1))
        start_values = {(h["group"], h["symbol"]): Decimal(str(h["value"]))
                        for h in before["positions"]}
        flows = _period_flows(ledger, start, on)
    agg: dict[tuple[str, str], dict] = {}
    for account, inv in balances.inventories(ledger, on).items():
        if not is_investment(account):
            continue
        grp = LABELS[group_of(account)]
        for pos in inv:
            units, cur = pos.units.number, pos.units.currency
            if not units:
                continue
            value = ledger.to_eur(units, cur, on)
            cost = balances.cost_eur(ledger, pos, on)
            if value is None:
                value = cost if cost is not None else ZERO
            key = (grp, cur)
            h = agg.setdefault(key, {"group": grp, "symbol": cur, "units": ZERO, "value": ZERO,
                                     "cost": None, "accounts": set(), "priced": True})
            h["units"] += units
            h["value"] += value
            h["accounts"].add(account)
            if cost is not None:
                h["cost"] = (h["cost"] or ZERO) + cost
            if ledger.to_eur(Decimal(1), cur, on) is None and cur != "EUR":
                h["priced"] = False
    total = sum((h["value"] for h in agg.values()), ZERO)
    total_cost = sum((h["cost"] for h in agg.values() if h["cost"] is not None), ZERO)
    positions = []
    for h in sorted(agg.values(), key=lambda x: -x["value"]):
        pl = h["value"] - h["cost"] if h["cost"] is not None else None
        positions.append({
            "group": h["group"], "symbol": h["symbol"], "units": _q(h["units"], 8),
            "value": _q(h["value"]), "cost": _q(h["cost"]), "pl": _q(pl),
            "pl_pct": _q(pl / h["cost"] * 100, 2) if pl is not None and h["cost"] else None,
            "price": _q(h["value"] / h["units"], 4) if h["units"] else None,
            "weight": _q(h["value"] / total * 100, 2) if total else 0.0,
            "accounts": sorted(h["accounts"]), "priced": h["priced"],
        })
        if start:
            key = (h["group"], h["symbol"])
            positions[-1].update(_period_return(h["value"], start_values.get(key, ZERO),
                                                flows.get(key, ZERO)))
    groups = []
    for g in (LABELS[k] for k in INVESTMENT_GROUPS):
        gv = sum((h["value"] for h in agg.values() if h["group"] == g), ZERO)
        gc = sum((h["cost"] for h in agg.values() if h["group"] == g and h["cost"] is not None),
                 ZERO)
        groups.append({"name": g, "value": _q(gv), "cost": _q(gc), "pl": _q(gv - gc),
                       "weight": _q(gv / total * 100, 2) if total else 0.0})
        if start:
            sv = sum((v for (grp, _), v in start_values.items() if grp == g), ZERO)
            fl = sum((v for (grp, _), v in flows.items() if grp == g), ZERO)
            groups[-1].update(_period_return(gv, sv, fl))
    pl = total - total_cost
    out = {
        "date": on.isoformat(), "total": _q(total), "cost": _q(total_cost), "pl": _q(pl),
        "pl_pct": _q(pl / total_cost * 100) if total_cost else None,
        "groups": groups, "positions": positions,
    }
    if start:
        out.update(_period_return(total, sum(start_values.values(), ZERO),
                                  sum(flows.values(), ZERO)), since=start.isoformat())
    return out


# --- recurring payees -------------------------------------------------------


DAY_SLACK = 4  # days around the usual day of the month
MIN_RECURRING = Decimal(3)  # EUR: below this, repeats are coffees and tolls


def _subscription_flag(payee: str) -> bool | None:
    """`subscription = true|false` from the first matching rule that sets it, else None.
    false: a habit (fuel, the climbing gym), never a subscription. true: a subscription even
    when its price changes (YouTube Premium 24.77 -> 29.99), so it is grouped by payee only."""
    from fin import payees

    for r in payees.rules():
        if isinstance(r.get("subscription"), bool) and r["_re"].search(payee):
            return r["subscription"]
    return None


def subscriptions(ledger: Ledger, today: date | None = None) -> list[dict]:
    """Recurring payments: same payee, same amount, around the same day, in 2+ months."""
    today = today or date.today()
    groups: dict[tuple, list] = defaultdict(list)
    for t in ledger.transactions:
        exp = [p for p in t.postings if p.account.startswith("Expenses:")]
        amount = expense_of(ledger, t)
        if not (t.payee and exp and amount >= MIN_RECURRING) or exp[0].account.startswith(
                "Expenses:Taxes:Foreign"):  # dividend withholding is not a payment
            continue
        flag = _subscription_flag(t.payee)
        if flag is False:
            continue
        # cents differ between transfers of the same rent (266.66 / 266.60)
        key = "flagged" if flag else (
            round(float(amount)) if amount >= 20 else round(float(amount), 2))
        groups[(normalize(t.payee), key)].append((t, exp[0].account))
    out = []
    for (_, key), rows in groups.items():
        rows.sort(key=lambda r: r[0].date)
        day = statistics.median([t.date.day for t, _ in rows])
        hits = [r for r in rows if abs(r[0].date.day - day) <= DAY_SLACK]
        months = {(t.date.year, t.date.month) for t, _ in hits}
        if len(months) < 2:
            continue
        per_month = sum(float(expense_of(ledger, t)) for t, _ in hits) / len(months)
        t, account = hits[-1]
        if key == "flagged":  # its price may change: show what it costs now
            per_month = float(expense_of(ledger, t))
        out.append({
            "payee": t.payee, "account": account, "amount": round(per_month, 2),
            "months": len(months), "last_date": t.date.isoformat(),
            "active": (today - t.date).days <= 45, "yearly": round(per_month * 12, 2),
        })
    out.sort(key=lambda s: (-s["active"], -s["amount"]))
    return out


def recurring(ledger: Ledger, end: date, months: int = 4) -> tuple[list[str], list[str]]:
    """(recurring payees, newly recurring) over the `months` ending at `end`: charged in >= 3
    distinct months with amounts within 30% of each other. "New" = first ever charge inside
    the window. Payees whose rule says `subscription = false` (habits) never count."""
    seen: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for t in ledger.transactions:
        amt = sum((p.units.number for p in t.postings if p.account.startswith("Expenses:")),
                  ZERO)
        if amt > 0 and t.payee and _subscription_flag(t.payee) is not False:  # habits
            seen[t.payee].append((t.date, amt))
    window = end - timedelta(days=30 * months)
    rec, new = [], []
    for payee, hits in seen.items():
        recent = [(d, a) for d, a in hits if window <= d < end]
        month_set = {(d.year, d.month) for d, _ in recent}
        amounts = [a for _, a in recent]
        if len(month_set) >= 3 and max(amounts) <= min(amounts) * Decimal("1.3"):
            rec.append(payee)
            if min(d for d, _ in hits) >= window:
                new.append(payee)
    return sorted(rec), sorted(new)


# --- overview ---------------------------------------------------------------


def overview(ledger: Ledger, start: date, end: date, pending_count: int = 0) -> dict:
    series = net_worth_series(ledger, start, end)
    now, base = series[-1], series[0]
    change = (now["total"] or 0) - (base["total"] or 0)
    pct = round(change / base["total"] * 100, 2) if base["total"] else None
    compare = {"prev", "yoy"}
    return {
        "net_worth": {**now, "change": round(change, 2), "change_pct": pct},
        "series": series,
        "totals": {**totals(ledger, start, end),
                   **with_comparison(ledger, start, end,
                                     lambda s, e: totals(ledger, s, e), compare)},
        "categories": categories_compared(ledger, start, end, compare=compare),
        "pending": pending_count,
    }
