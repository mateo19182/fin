"""Monthly close: is the month complete (checklist) and what happened in it (stats).

`report.monthly` renders `stats`, so the numbers have one source.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from beancount.core import data

from fin import analytics, ledger, networth, status, store
from fin.balances import ZERO, q
from fin.sync import revolut_invest, revolut_savings

AVG_MONTHS = 6
INSIGHT_MIN_EUR = Decimal(50)
INSIGHT_MIN_PCT = 25


def _pct(part: Decimal, whole: Decimal) -> int | None:
    return round(float(part / whole * 100)) if whole else None


def checklist(month: str | None = None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    lg = ledger.load()
    start, end = analytics.month_bounds(month, today)
    items = []

    rec = store.get(f"import:{revolut_invest.SOURCE}") or {}
    last_row = max((t.date for t in lg.transactions
                    if t.meta.get("source") == revolut_invest.SOURCE), default=None)
    imported = date.fromisoformat(rec["imported_at"]) if rec.get("imported_at") else None
    ok = (imported >= end) if imported else bool(last_row and last_row >= start)
    items.append({"key": "stocks_csv", "label": "Revolut Invest CSV imported after month end",
                  "ok": ok, "detail": f"imported {imported}" if imported
                  else f"last row {last_row}" if last_row else "never imported"})

    rec = store.get(f"import:{revolut_savings.SOURCE}") or {}
    checks = [e.date for e in lg.entries if isinstance(e, data.Balance)
              and e.account == revolut_savings.ACCOUNT]
    if rec.get("statement_end"):
        checks.append(date.fromisoformat(rec["statement_end"]) + timedelta(days=1))
    covered = max(checks, default=None)
    items.append({"key": "savings_csv", "label": "Savings statement covers month end",
                  "ok": bool(covered and covered >= end),
                  "detail": f"covered to {covered}" if covered else "no statement imported"})

    pending = store.list_pending()
    items.append({"key": "pending", "label": "No pending reviews", "ok": not pending,
                  "detail": f"{len(pending)} pending"})

    failing = [e for e in lg.errors if isinstance(getattr(e, "entry", None), data.Balance)]
    items.append({"key": "balances", "label": "All balance assertions pass", "ok": not failing,
                  "detail": "; ".join(e.message for e in failing)[:300] or "all pass"})

    banks = [r for r in status.accounts_status(today) if r["updates_via"] == "bank"]
    stale = [f"{r['updater']}: {r['stale_reason']}" for r in banks if r["stale"]]
    items.append({"key": "banks", "label": "Bank syncs fresh", "ok": not stale,
                  "detail": "; ".join(stale) or ", ".join(
                      f"{r['updater']} {r['last_update']}" for r in banks)})
    return items


def _biggest(lg: ledger.Ledger, start: date, end: date, n: int = 5) -> list[dict]:
    rows = []
    for t in lg.transactions:
        if not start <= t.date < end:
            continue
        exp = [p for p in t.postings if p.account.startswith("Expenses:")]
        if not exp:
            continue
        rows.append({"id": ledger.txn_id(t), "date": t.date.isoformat(), "payee": t.payee,
                     "account": exp[0].account, "amount": analytics.expense_of(lg, t)})
    rows.sort(key=lambda r: -r["amount"])
    return [{**r, "amount": q(r["amount"])} for r in rows[:n]]


def _insights(s: dict) -> list[str]:
    out = []
    cats = [c for c in s["top_categories"] if Decimal(c["avg6"]) > 0
            and Decimal(c["amount"]) >= INSIGHT_MIN_EUR and c["vs_avg6_pct"] is not None
            and abs(c["vs_avg6_pct"]) >= INSIGHT_MIN_PCT]
    for c in sorted(cats, key=lambda c: -abs(c["vs_avg6_pct"]))[:3]:
        word = "above" if c["vs_avg6_pct"] > 0 else "below"
        out.append(f"{c['account'].split(':', 1)[-1]} {abs(c['vs_avg6_pct'])}% {word} "
                   f"{AVG_MONTHS}-month average ({c['amount']} EUR)")
    if s["savings_rate"] is not None:
        line = f"Savings rate {s['savings_rate']:.0%}"
        if s["prev_savings_rate"] is not None:
            line += f" (previous month {s['prev_savings_rate']:.0%})"
        out.append(line)
    if s["biggest_expenses"]:
        b = s["biggest_expenses"][0]
        out.append(f"Biggest expense: {b['payee']} {b['amount']} EUR on {b['date']}")
    if s["new_recurring"]:
        out.append("New recurring payees: " + ", ".join(s["new_recurring"]))
    nw = s["net_worth"]
    out.append(f"Net worth {Decimal(nw['change']):+.0f} EUR: saved {Decimal(nw['saved']):+.0f}, "
               f"contributions {Decimal(nw['contributions']):+.0f}, "
               f"market {Decimal(nw['market']):+.0f}")
    return out


def stats(month: str | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    lg = ledger.load()
    start, end = analytics.month_bounds(month, today)
    ym = f"{start:%Y-%m}"

    def flows(s, e):  # [s, e) like month_bounds
        return analytics.account_flows(lg, s, e - timedelta(days=1))

    income, expenses, payees = flows(start, end)
    total_in, total_out = sum(income.values(), ZERO), sum(expenses.values(), ZERO)
    prev_in, prev_exp, _ = flows(analytics.shift_months(start, -1), start)
    prev_in_total, prev_out_total = sum(prev_in.values(), ZERO), sum(prev_exp.values(), ZERO)
    avg: dict[str, Decimal] = defaultdict(Decimal)
    for i in range(1, AVG_MONTHS + 1):
        s = analytics.shift_months(start, -i)
        for a, v in flows(s, analytics.next_month(s))[1].items():
            avg[a] += v / AVG_MONTHS
    days = (min(end, today + timedelta(days=1)) - start).days
    nw = networth.month(lg, ym, today)
    txns = [t for t in lg.transactions if start <= t.date < end and t.flag != "P"]
    _, new_rec = analytics.recurring(lg, end)
    out = {
        "month": ym,
        "income": q(total_in),
        "expenses": q(total_out),
        "savings_rate": (round(float((total_in - total_out) / total_in), 3) if total_in else None),
        "prev_savings_rate": (round(float((prev_in_total - prev_out_total) / prev_in_total), 3)
                              if prev_in_total else None),
        "income_by_account": {a: q(v) for a, v in sorted(income.items(), key=lambda x: -x[1])},
        "top_categories": [{
            "account": a, "amount": q(v),
            "prev": q(prev_exp.get(a, ZERO)), "vs_prev": q(v - prev_exp.get(a, ZERO)),
            "avg6": q(avg.get(a, ZERO)), "vs_avg6": q(v - avg.get(a, ZERO)),
            "vs_avg6_pct": _pct(v - avg.get(a, ZERO), avg.get(a, ZERO)),
        } for a, v in sorted(expenses.items(), key=lambda x: -x[1])[:8]],
        "top_payees": [{"payee": p, "amount": q(v)}
                       for p, v in sorted(payees.items(), key=lambda x: -x[1])[:5]],
        "biggest_expenses": _biggest(lg, start, end),
        "avg_daily_spend": q(total_out / days) if days > 0 else "0.00",
        "days": max(days, 0),
        "transactions": len(txns),
        "expense_transactions": sum(any(p.account.startswith("Expenses:") for p in t.postings)
                                    for t in txns),
        "new_recurring": new_rec,
        "net_worth": {"total": nw["total"], "change": nw["change"], "saved": nw["saved"],
                      "contributions": nw["contributions"], "market": nw["market"],
                      "groups": nw["groups"]},
    }
    out["insights"] = _insights(out)
    return out


def text(s: dict, items: list[dict]) -> str:
    lines = [f"Close {s['month']}: income {s['income']}, expenses {s['expenses']}"
             + (f", savings rate {s['savings_rate']:.0%}" if s["savings_rate"] is not None else "")]
    lines += [f"  [{'x' if i['ok'] else ' '}] {i['label']} — {i['detail']}" for i in items]
    lines.append("Top categories (vs prev / vs 6m avg):")
    lines += [f"  {c['account'].split(':', 1)[-1]:<28}{c['amount']:>10}  "
              f"({Decimal(c['vs_prev']):+.0f} / {Decimal(c['vs_avg6']):+.0f})"
              for c in s["top_categories"]]
    lines.append("Biggest expenses: " + "; ".join(
        f"{b['payee']} {b['amount']}" for b in s["biggest_expenses"]))
    lines.append(f"{s['transactions']} transactions, {s['avg_daily_spend']} EUR/day")
    lines += ["Insights:"] + [f"  - {i}" for i in s["insights"]]
    return "\n".join(lines)


# Categories where a work cost usually hides; anything else is only deducted by a rule or a tap.
MAYBE_ACCOUNTS = ("Expenses:Software", "Expenses:Tech", "Expenses:Travel")


def deductions(month: str | None = None, today: date | None = None) -> dict:
    """The month's autónomo costs: deducted, waiting for a receipt, and candidates to decide."""
    from fin import activity

    lg = ledger.load()
    start, end = analytics.month_bounds(month, today or date.today())
    out: dict = {"deducted": [], "needs_receipt": [], "maybe": []}
    for t in lg.transactions:
        if not start <= t.date < end:
            continue
        gross = activity.expense_amount(t, lg)
        if gross <= 0:
            continue
        row = {"id": ledger.txn_id(t), "date": t.date.isoformat(), "payee": t.payee or "",
               "amount": str(q(gross))}
        d = activity.deductible(t)
        if d.on:
            c = activity.cost(t, lg)
            if c:
                out["deducted"].append({**row, "base": str(c["base"]), "iva": str(c["iva"]),
                                        "receipt": activity.has_receipt(t)})
            if d.iva_blocked:  # the invoice would add its IVA (fuel: the only way it counts)
                out["needs_receipt"].append(row)
        elif (not d.reason and activity.rule_for(t.payee, t.meta.get("bank_payee")) is None
              and any(p.account.startswith(MAYBE_ACCOUNTS) for p in t.postings)):
            out["maybe"].append(row)
    out["base"] = str(q(sum((Decimal(x["base"]) for x in out["deducted"]), ZERO)))
    out["iva"] = str(q(sum((Decimal(x["iva"]) for x in out["deducted"]), ZERO)))
    return out
