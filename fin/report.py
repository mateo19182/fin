"""The monthly plain-text report (1st of the month, deploy/fin-report.timer), built on
close.stats so the numbers have one source."""

from decimal import Decimal

from fin import analytics, close, config, ledger, notify, store

LABELS = {"EatingOut": "Eating out", "Taxes:SocialSecurity": "Social Security"}


def _eur(v, sign: bool = False) -> str:
    return f"{Decimal(v):{'+' if sign else ''},.0f} €".replace("-", "−")


def _label(account: str) -> str:
    name = account.split(":", 1)[-1]
    return LABELS.get(name, name.replace(":", " / "))


def monthly(month: str | None = None) -> str:
    s = close.stats(month)
    start, _ = analytics.month_bounds(s["month"])
    nw = s["net_worth"]
    rate = (f" ({s['savings_rate']:.0%}" + (f", last month {s['prev_savings_rate']:.0%}"
                                            if s["prev_savings_rate"] is not None else "") + ")"
            if s["savings_rate"] is not None else "")
    lines = [f"📊 Finance report: {start:%B %Y}", "",
             f"Income {_eur(s['income'])} · spent {_eur(s['expenses'])} · "
             f"saved {_eur(nw['saved'])}{rate}", "",
             f"Spending (usual = {close.AVG_MONTHS}-month average):"]
    for c in s["top_categories"]:
        line = f"• {_label(c['account'])}: {_eur(c['amount'])}"
        pct, avg = c["vs_avg6_pct"], Decimal(c["avg6"])
        if (pct is not None and avg > 0 and abs(pct) >= close.INSIGHT_MIN_PCT
                and abs(Decimal(c["vs_avg6"])) >= 20):
            line += f" {'↑' if pct > 0 else '↓'} usual {_eur(avg)}"
        lines.append(line)
    if s["biggest_expenses"]:
        b = s["biggest_expenses"][0]
        lines.append(f"Biggest: {b['payee']} {_eur(b['amount'])} "
                     f"on {b['date'][8:]}/{b['date'][5:7]}")
    if s["new_recurring"]:
        lines.append("New recurring charges: " + ", ".join(s["new_recurring"]))
    groups = analytics.holdings(ledger.load())["groups"]
    lines += ["", f"Net worth {_eur(nw['total'])} ({_eur(nw['change'], True)} this month)",
              f"• saved {_eur(nw['saved'], True)}, markets {_eur(nw['market'], True)}"
              f" ({_eur(nw['contributions'])} moved into investments)",
              "Investments (share · gain since bought):"]
    lines += [f"• {g['name']}: {g['weight']:.0f}% · {_eur(g['pl'], True)}" for g in groups]
    lines += ["", "To do:",
              f"1. Revolut Invest CSV (Invest → ⋯ → Documents → Brokerage account → Account"
              f" statement → CSV): upload at {config.web_url('/close')} or send it here",
              "2. Revolut savings statement CSV: same",
              "3. Rebalance if the investment split drifted"]
    if store.list_pending():
        lines.append(f"4. Clear pending reviews: {config.web_url('/review')}")
    return "\n".join(lines)


def send_monthly(month: str | None = None, dry_run: bool = False) -> str:
    text = monthly(month)
    notify.send(text, dry_run)
    return text
