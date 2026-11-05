"""Weekly digest (Sundays 19:00 via deploy/fin-digest.timer): at most six short lines.

Notable (otherwise nothing is sent): the week's spend is >= NOTABLE_PCT % away from the
8-week average (and >= NOTABLE_EUR), an alert fired this week, reviews are pending, or a
303/130 deadline is within DEADLINE_SOON days.
"""

from datetime import date, timedelta
from decimal import Decimal

from fin import alerts, analytics, config, ledger, notify, store
from fin.renta import quarterly

WEEKS = 8
NOTABLE_PCT = 25
NOTABLE_EUR = Decimal(50)
MOVE_EUR = Decimal(30)
DEADLINE_SOON = 14
DEADLINE_SHOW = 30


def _eur(v) -> str:
    return f"{Decimal(v):,.0f} €"


def digest(today: date | None = None) -> dict:
    today = today or date.today()
    lg = ledger.load()
    start, prev_start = today - timedelta(days=6), today - timedelta(days=6 + 7 * WEEKS)
    _, spent = analytics.income_expenses(lg, start, today)
    _, prev = analytics.income_expenses(lg, prev_start, start - timedelta(days=1))
    avg = prev / WEEKS
    diff = spent - avg
    pct = round(float(diff / avg * 100)) if avg else None
    lines, reasons = [], []
    lines.append(f"This week {_eur(spent)} vs {_eur(avg)} avg ({pct:+d}%)" if pct is not None
                 else f"This week {_eur(spent)}")
    if avg and abs(diff) >= NOTABLE_EUR and abs(pct) >= NOTABLE_PCT:
        reasons.append("spend")

    week = {c["account"]: Decimal(str(c["total"])) for c in analytics.categories(lg, start, today)}
    base = {c["account"]: Decimal(str(c["total"])) / WEEKS
            for c in analytics.categories(lg, prev_start, start - timedelta(days=1))}
    moves = sorted(((a, week.get(a, Decimal(0)) - base.get(a, Decimal(0)))
                    for a in set(week) | set(base)), key=lambda x: -abs(x[1]))
    moves = [(a, d) for a, d in moves if abs(d) >= MOVE_EUR][:2]
    if moves:
        lines.append("Moves: " + ", ".join(f"{a.split(':', 1)[-1]} {d:+,.0f} €" for a, d in moves))

    odd = alerts.recent(7, today)
    if odd:
        lines.append(f"{len(odd)} alert{'s' if len(odd) > 1 else ''}: {odd[-1]['text']}"[:160])
        reasons.append("alerts")

    pending = len(store.list_pending())
    if pending:
        lines.append(f"{pending} to review: {config.web_url('/review')}")
        reasons.append("pending")

    period, due = quarterly.next_deadline(today)
    days = (due - today).days
    if days <= DEADLINE_SHOW:
        r = quarterly.quarter(period, today)
        lines.append(f"Tax {period} due {due} ({days} d): 303 {r['modelo_303']['resultado']} €, "
                     f"130 {r['modelo_130']['resultado']} €")
        if days <= DEADLINE_SOON:
            reasons.append("deadline")

    biggest = max(((t, v) for t in lg.transactions if start <= t.date <= today
                   for v in [analytics.expense_of(lg, t)] if v > 0),
                  key=lambda x: x[1], default=None)
    if biggest and len(lines) < 6:
        lines.append(f"Biggest: {biggest[0].payee} {_eur(biggest[1])} on {biggest[0].date:%d %b}")
    return {"date": today.isoformat(), "lines": lines[:6], "notable": bool(reasons),
            "reasons": reasons}


def text(d: dict) -> str:
    return "\n".join(d["lines"])


def send(today: date | None = None, dry_run: bool = False) -> str | None:
    d = digest(today)
    if not d["notable"]:
        return None
    notify.send("Weekly: " + text(d), dry_run)
    return text(d)
