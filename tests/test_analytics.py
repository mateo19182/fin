import json
import os
import subprocess
import sys
from datetime import date

import pytest

TODAY = date(2026, 10, 25)


def test_net_worth_groups(ledger):
    from fin import analytics as a

    nw = a.net_worth(ledger, TODAY)
    # cash: 1000 - 100 + 3*2000 - 4*12.99 - 40 - 60 - 25 - 30 = 6693.04
    assert nw["groups"]["cash"] == pytest.approx(6693.04)
    # 2 NVDA @150 USD / 1.25 = 240 EUR; 0.01 BTC @60000 = 600; 10 INDEXA @11 = 110
    assert nw["groups"]["stocks"] == pytest.approx(240.0)
    assert nw["groups"]["crypto"] == pytest.approx(600.0)
    assert nw["groups"]["indexa"] == pytest.approx(110.0)
    assert nw["total"] == pytest.approx(6693.04 + 240 + 600 + 110)
    assert nw["liabilities"] == 0


def test_net_worth_series_samples_month_ends_with_baseline(ledger):
    from fin import analytics as a

    s = a.net_worth_series(ledger, date(2025, 6, 1), TODAY)
    assert [r["date"] for r in s][:3] == ["2025-05-31", "2025-06-30", "2025-07-31"]
    assert s[-1]["date"] == "2026-10-25" and len(s) == 18
    assert s[0]["total"] == 0
    assert s[-1]["total"] == a.net_worth(ledger, TODAY)["total"]
    jan = next(r for r in s if r["date"] == "2026-01-31")
    assert jan["groups"]["stocks"] == pytest.approx(200.0)  # 2 NVDA @100 USD, EUR=1 USD
    assert jan["total"] == pytest.approx(900 + 200 + 500 + 100)


def test_series_granularity(ledger):
    from fin import analytics as a

    daily = a.net_worth_series(ledger, date(2026, 10, 1), TODAY)
    assert len(daily) == 26 and daily[0]["date"] == "2026-09-30"
    weekly = a.net_worth_series(ledger, date(2026, 8, 1), TODAY)
    assert weekly[1]["date"] == "2026-08-02" and weekly[-1]["date"] == "2026-10-25"
    assert len(weekly) == 14
    year = a.net_worth_series(ledger, date(2025, 11, 1), TODAY)
    assert len(year) == 53 and year[0]["date"] == "2025-10-31"


def test_cashflow_series(ledger):
    from fin import analytics as a

    s = {r["period"]: r for r in a.cashflow_series(ledger, date(2026, 5, 1), TODAY)}
    assert list(s) == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert s["2026-08"] == {"period": "2026-08", "income": 2000.0, "expenses": 72.99,
                            "savings": 1927.01}
    assert s["2026-10"]["income"] == 0.0 and s["2026-10"]["expenses"] == pytest.approx(42.99)
    q = {r["period"]: r for r in a.cashflow_series(ledger, date(2026, 1, 1), TODAY, "quarter")}
    assert list(q) == ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]
    assert q["2026-Q3"]["income"] == 6000.0
    assert q["2026-Q3"]["expenses"] == pytest.approx(52.99 + 72.99 + 37.99)


def test_categories_rollup(ledger):
    from fin import analytics as a

    cats = a.categories(ledger, date(2026, 7, 1), date(2026, 9, 30))
    by = {c["account"]: c for c in cats}
    assert by["Expenses:Food"]["total"] == pytest.approx(125.0)
    assert [c["account"] for c in by["Expenses:Food"]["children"]] == [
        "Expenses:Food:Groceries", "Expenses:Food:Restaurant"]
    assert by["Expenses:Software"]["total"] == pytest.approx(38.97)
    assert sum(c["share"] for c in cats) == pytest.approx(1.0, abs=0.001)
    assert cats[0]["account"] == "Expenses:Food"  # sorted desc


# --- periods ----------------------------------------------------------------


def test_shift_period_full_months():
    from fin import analytics as a

    assert a.shift_period(date(2026, 3, 1), date(2026, 5, 31), -3) == (
        date(2025, 12, 1), date(2026, 2, 28))
    assert a.previous_period(date(2026, 7, 1), date(2026, 7, 31)) == (
        date(2026, 6, 1), date(2026, 6, 30))
    # leap February, full month -> full month
    assert a.year_ago(date(2024, 2, 1), date(2024, 2, 29)) == (date(2023, 2, 1), date(2023, 2, 28))
    assert a.year_ago(date(2023, 2, 1), date(2023, 2, 28)) == (date(2022, 2, 1), date(2022, 2, 28))
    assert a.year_ago(date(2025, 6, 1), date(2026, 10, 25)) is None  # 17 months: overlaps itself


def test_shift_period_partial_month_keeps_day_clipped():
    from fin import analytics as a

    assert a.previous_period(date(2026, 10, 1), date(2026, 10, 25)) == (
        date(2026, 9, 1), date(2026, 9, 25))
    assert a.previous_period(date(2026, 3, 1), date(2026, 3, 30)) == (
        date(2026, 2, 1), date(2026, 2, 28))
    assert a.previous_period(date(2024, 3, 1), date(2024, 3, 30)) == (
        date(2024, 2, 1), date(2024, 2, 29))
    # 3 months ending mid-month -> the 3 before, ending on the same day
    assert a.previous_period(date(2026, 8, 1), date(2026, 10, 25)) == (
        date(2026, 5, 1), date(2026, 7, 25))
    # across a year boundary
    assert a.previous_period(date(2026, 1, 1), date(2026, 1, 15)) == (
        date(2025, 12, 1), date(2025, 12, 15))
    assert a.months_in(date(2025, 11, 1), date(2026, 10, 25)) == 12


def test_resolve_period_presets():
    from fin import analytics as a

    first = date(2026, 1, 1)
    p = a.resolve_period("1m", TODAY, first)
    assert (p["start"], p["end"], p["months"]) == ("2026-10-01", "2026-10-25", 1)
    assert p["prev"] == {"start": "2026-09-01", "end": "2026-09-25"}
    assert p["yoy"] is None  # Oct 2025 is before the first transaction
    assert a.resolve_period("3m", TODAY, first)["start"] == "2026-08-01"
    assert a.resolve_period("6m", TODAY, first)["start"] == "2026-05-01"
    ytd = a.resolve_period("ytd", TODAY, first)
    assert (ytd["start"], ytd["months"]) == ("2026-01-01", 10)
    assert ytd["prev"] == {"start": "2025-03-01", "end": "2025-12-25"} or ytd["prev"] is None
    year = a.resolve_period("1y", TODAY, first)
    assert year["start"] == "2025-11-01" and year["yoy"] is None  # would equal prev
    al = a.resolve_period("all", TODAY, first)
    assert al["start"] == "2026-01-01" and al["prev"] is None and al["yoy"] is None
    assert a.resolve_period("all", TODAY, None)["start"] == "2026-10-01"
    assert a.resolve_period("1m", date(2026, 1, 15), None)["prev"] == {
        "start": "2025-12-01", "end": "2025-12-15"}


def test_resolve_period_custom_and_errors():
    from fin import analytics as a

    c = a.resolve_period("2026-07..2026-09", TODAY, date(2026, 1, 1))
    assert (c["start"], c["end"], c["months"]) == ("2026-07-01", "2026-09-30", 3)
    assert c["prev"] == {"start": "2026-04-01", "end": "2026-06-30"}
    assert a.resolve_period("2026-10..2026-12", TODAY)["end"] == "2026-10-25"
    with pytest.raises(ValueError):
        a.resolve_period("2026-09..2026-07", TODAY)
    with pytest.raises(ValueError):
        a.resolve_period("2w", TODAY)


def test_ytd_prev_period_before_ledger_is_none(ledger):
    from fin import analytics as a

    p = a.resolve_period("ytd", TODAY, a.first_date(ledger))
    assert p["prev"] is None and p["yoy"] is None


# --- comparisons --------------------------------------------------------------


def test_totals_with_comparison(ledger):
    from fin import analytics as a

    cur = a.totals(ledger, date(2026, 10, 1), TODAY)
    assert cur == {"income": 0.0, "expenses": 42.99, "savings": -42.99}
    cmp = a.with_comparison(ledger, date(2026, 10, 1), TODAY,
                            lambda s, e: a.totals(ledger, s, e), {"prev", "yoy"})
    assert cmp["prev"] == {"income": 2000.0, "expenses": 37.99, "savings": 1962.01}
    assert cmp["yoy"] is None
    three = a.with_comparison(ledger, date(2026, 8, 1), TODAY,
                              lambda s, e: a.totals(ledger, s, e), {"prev"})
    assert three == {"prev": {"income": 2000.0, "expenses": 52.99, "savings": 1947.01}}


def test_categories_compared(ledger):
    from fin import analytics as a

    rows = {r["account"]: r for r in a.categories_compared(ledger, date(2026, 10, 1), TODAY)}
    food = rows["Expenses:Food"]
    assert (food["total"], food["prev"], food["yoy"]) == (30.0, 25.0, None)
    assert rows["Expenses:Software"]["prev"] == 12.99
    assert food["children"][0] == {"account": "Expenses:Food:Groceries", "total": 30.0,
                                   "count": 1, "prev": 0.0, "yoy": None}
    # a category only present in the previous period is kept with total 0
    inc = a.categories_compared(ledger, date(2026, 10, 1), TODAY, "Income", {"prev"})
    assert inc == [{"account": "Income:Salary", "total": 0.0, "count": 0, "share": 0.0,
                    "children": [], "prev": 2000.0}]
    plain = a.categories_compared(ledger, date(2026, 10, 1), TODAY, compare=set())
    assert "prev" not in plain[0]


def test_portfolio_series(ledger):
    from fin import analytics as a

    s = a.portfolio_series(ledger, date(2025, 6, 1), TODAY)
    assert s[0] == {"date": "2025-05-31", "value": 0.0, "cost": 0.0}
    assert s[-1]["value"] == pytest.approx(950.0)
    assert s[-1]["cost"] == pytest.approx(160 + 500 + 100)
    jan = next(r for r in s if r["date"] == "2026-01-31")
    assert jan["value"] == pytest.approx(800.0) and jan["cost"] == pytest.approx(800.0)


def test_transactions_filters(ledger):
    from fin import analytics as a

    all_ = a.transactions(ledger)
    assert all_["total"] == 15 and all_["items"][0]["date"] == "2026-10-05"
    first = all_["items"][0]
    assert first["id"] == "l10" and first["amount"] == -30.0
    assert first["account"] == "Expenses:Food:Groceries"
    assert first["bank"] == "Assets:Bank:Revolut:Checking"
    assert a.transactions(ledger, q="netflix")["total"] == 4
    assert a.transactions(ledger, account="Expenses:Food")["total"] == 4
    assert a.transactions(ledger, auto_only=True)["total"] == 2
    sept = a.transactions(ledger, start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert [i["id"] for i in sept["items"]] == ["b9", "n9", "s9"]
    assert a.transactions(ledger, limit=2, offset=1)["items"][0]["id"] == "n10"
    assert [i["id"] for i in a.recent_auto(ledger, 30, TODAY)] == ["n10"]


def test_holdings(ledger):
    from fin import analytics as a

    h = a.holdings(ledger, TODAY)
    pos = {p["symbol"]: p for p in h["positions"]}
    nvda = pos["NVDA"]
    assert nvda["group"] == "Revolut" and nvda["units"] == 2
    assert nvda["value"] == pytest.approx(240.0)
    assert nvda["cost"] == pytest.approx(160.0)  # 200 USD / 1.25
    assert nvda["pl"] == pytest.approx(80.0) and nvda["pl_pct"] == pytest.approx(50.0)
    assert pos["BTC"]["pl"] == pytest.approx(100.0)
    assert pos["INDEXA"]["group"] == "Indexa"
    assert h["total"] == pytest.approx(950.0)
    groups = {g["name"]: g for g in h["groups"]}
    assert groups["Crypto"]["weight"] == pytest.approx(600 / 950 * 100, abs=0.01)
    assert sum(p["weight"] for p in h["positions"]) == pytest.approx(100, abs=0.05)


def test_holdings_period_excludes_new_money(ledger):
    from fin import analytics as a

    same_day = a.holdings(ledger, TODAY, TODAY)
    assert same_day["since"] == TODAY.isoformat()
    assert all(p["period_pl"] == pytest.approx(0) for p in same_day["positions"])
    whole = a.holdings(ledger, TODAY, date(2000, 1, 1))  # every buy is inside the period
    flows = sum(a._period_flows(ledger, date(2000, 1, 1), TODAY).values())
    assert whole["period_pl"] == pytest.approx(whole["total"] - float(flows), abs=0.01)


def test_subscriptions(ledger):
    from fin import analytics as a

    subs = a.subscriptions(ledger, today=TODAY)
    assert [s["payee"] for s in subs] == ["Netflix"]
    assert subs[0]["amount"] == 12.99 and subs[0]["months"] == 4 and subs[0]["active"]
    # Lidl varies too much in amount and Example is income


def test_overview(ledger):
    from fin import analytics as a

    o = a.overview(ledger, date(2026, 10, 1), TODAY, pending_count=3)
    assert o["pending"] == 3
    assert o["totals"]["expenses"] == pytest.approx(42.99)
    assert o["totals"]["prev"]["expenses"] == pytest.approx(37.99)
    assert o["totals"]["yoy"] is None
    assert o["net_worth"]["change"] == pytest.approx(-42.99)
    assert o["series"][0]["date"] == "2026-09-30" and len(o["series"]) == 26
    assert o["categories"][0]["account"] == "Expenses:Food"
    q = a.overview(ledger, date(2026, 8, 1), TODAY)
    assert q["totals"] == {"income": 4000.0, "expenses": pytest.approx(153.97),
                           "savings": pytest.approx(3846.03),
                           "prev": {"income": 2000.0, "expenses": 52.99, "savings": 1947.01},
                           "yoy": None}


REAL_SCRIPT = """
import json, datetime as dt
from fin.ledger import load
from fin import analytics as a
l = load()
t = dt.date(2026, 10, 25)
print(json.dumps({
  "nw": a.net_worth(l, t), "cf": a.cashflow_series(l, dt.date(2025, 11, 1), t),
  "period": a.resolve_period("6m", t, a.first_date(l)),
  "ov": a.overview(l, dt.date(2026, 5, 1), t), "pf": a.portfolio_series(l, dt.date(2026, 1, 1), t),
  "sept": a.categories(l, dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
  "hold": a.holdings(l, t), "subs": a.subscriptions(l, today=t),
  "tx": a.transactions(l, limit=5)["total"], "errors": len(l.errors),
}))
"""


def test_real_ledger_sanity(real_ledger_root):
    """Read-only run against a temp copy of the real ledger (skipped if not present)."""
    if real_ledger_root is None:
        pytest.skip("no real ledger")
    env = {**os.environ, "FIN_ROOT": str(real_ledger_root)}
    out = subprocess.run([sys.executable, "-c", REAL_SCRIPT], env=env, capture_output=True,
                         text=True, check=True).stdout
    r = json.loads(out)
    assert r["errors"] == 0
    assert r["nw"]["total"] > 0
    assert abs(sum(r["nw"]["groups"].values()) - r["nw"]["assets"]) < 0.05
    assert r["hold"]["total"] == pytest.approx(r["nw"]["groups"]["stocks"]
                                                + r["nw"]["groups"]["indexa"]
                                                + r["nw"]["groups"]["crypto"], abs=0.05)
    sept = next(m for m in r["cf"] if m["period"] == "2026-09")
    assert sept["expenses"] == pytest.approx(sum(c["total"] for c in r["sept"]), abs=0.05)
    assert r["tx"] > 100
    assert r["period"]["start"] == "2026-05-01" and r["period"]["prev"] is not None
    ov = r["ov"]
    assert ov["totals"]["expenses"] == pytest.approx(
        sum(m["expenses"] for m in r["cf"] if m["period"] >= "2026-05"), abs=0.05)
    assert ov["totals"]["prev"]["expenses"] > 0
    assert sum(c["total"] for c in ov["categories"]) == pytest.approx(ov["totals"]["expenses"],
                                                                      abs=0.05)
    assert r["pf"][-1]["value"] == pytest.approx(r["hold"]["total"], abs=0.05)
