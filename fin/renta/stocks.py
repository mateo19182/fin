"""FIFO lots and realised gains per sale from the full Revolut Invest CSV history.

Amounts are converted to EUR at the FX rate in the CSV, which is Revolut's rate on the day
(AEAT would accept the ECB rate; the difference is cents on these sizes). The acquisition
value is the row total (it already includes Revolut's fee); the transmission value is the
sale total (net of fees). Losses with a repurchase of the same ticker within two months are
flagged (art. 33.5.f LIRPF), not removed: the loss is deferred until those shares are sold.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fin import docs
from fin.renta import securities
from fin.sync import revolut_invest

REPURCHASE_DAYS = 61  # "dos meses" around the sale date, inclusive
CENT = Decimal("0.01")


def archives() -> list[Path]:
    """Archived statements, oldest first: <year>/statements/revolut-invest_<last date>.csv."""
    return sorted(docs.root().glob(f"*/statements/{revolut_invest.ARCHIVE_PREFIX}*.csv"),
                  key=lambda p: p.name)


def latest_csv() -> Path | None:
    """Each statement holds the full history, so the latest one is enough."""
    files = archives()
    return files[-1] if files else None


def to_eur(amount: Decimal, currency: str, fx: Decimal) -> Decimal:
    return amount if currency == "EUR" or not fx else amount / fx


def lots_and_sales(rows: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Run FIFO over the whole history. Returns (open lots per ticker, realised sales)."""
    lots: dict[str, list[dict]] = {}
    sales: list[dict] = []
    for r in rows:
        kind = r["type"]
        if kind.startswith("BUY"):
            lots.setdefault(r["ticker"], []).append({
                "date": r["date"], "qty": r["qty"], "cost_eur": to_eur(abs(r["total"]),
                                                                        r["currency"], r["fx"])})
        elif kind.startswith("SELL"):
            sales.append(_sell(lots.setdefault(r["ticker"], []), r))
        elif "SPLIT" in kind:
            sales.append({"date": r["date"], "ticker": r["ticker"], "error":
                          "stock split not supported: check lots by hand"})
    return lots, sales


def _sell(lots: list[dict], r: dict) -> dict:
    qty, proceeds = abs(r["qty"]), to_eur(abs(r["total"]), r["currency"], r["fx"])
    left, cost, used = qty, Decimal(0), []
    while left > 0 and lots:
        lot = lots[0]
        take = min(left, lot["qty"])
        part = lot["cost_eur"] * take / lot["qty"]
        used.append({"date": lot["date"].isoformat(), "qty": str(take), "cost_eur": str(_q(part))})
        cost += part
        lot["qty"] -= take
        lot["cost_eur"] -= part
        left -= take
        if lot["qty"] == 0:
            lots.pop(0)
    out = {"date": r["date"], "ticker": r["ticker"], "kind": securities.info(r["ticker"])[1],
           "qty": str(qty), "proceeds_eur": _q(proceeds), "cost_eur": _q(cost),
           "gain_eur": _q(proceeds - cost), "lots": used, "currency": r["currency"],
           "fx": str(r["fx"])}
    if left > 0:
        out["error"] = f"sold {left} {r['ticker']} more than the known lots"
    return out


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT)


def flag_repurchases(sales: list[dict], rows: list[dict]) -> None:
    buys = [(r["date"], r["ticker"]) for r in rows if r["type"].startswith("BUY")]
    window = timedelta(days=REPURCHASE_DAYS)
    for s in sales:
        loss = "gain_eur" in s and s["gain_eur"] < 0
        s["repurchase_within_2m"] = loss and any(
            t == s["ticker"] and abs(d - s["date"]) <= window for d, t in buys)


def gains(rows: list[dict], year: int) -> dict:
    """Realised gains of `year`, split shares vs ETF/IIC, with totals and warnings."""
    _, sales = lots_and_sales(rows)
    flag_repurchases(sales, rows)
    in_year = [s for s in sales if s["date"].year == year]
    out = {"shares": [], "etf": [], "warnings": []}
    for s in in_year:
        s = {**s, "date": s["date"].isoformat()}
        if "error" in s:
            out["warnings"].append(f"{s['date']} {s['ticker']}: {s['error']}")
            if "gain_eur" not in s:
                continue
        if s.get("repurchase_within_2m"):
            out["warnings"].append(
                f"{s['date']} {s['ticker']}: loss {s['gain_eur']} EUR with a repurchase within "
                f"2 months (art. 33.5.f): not deductible until those shares are sold")
        if not securities.info(s["ticker"])[2]:
            out["warnings"].append(f"{s['ticker']}: not in securities.TICKERS, assumed US share")
        out["etf" if s["kind"] == "etf" else "shares"].append(s)
    for key in ("shares", "etf"):
        out[f"{key}_total"] = _q(sum((s["gain_eur"] for s in out[key]), Decimal(0)))
    return out


def positions(rows: list[dict], on: date) -> dict[str, Decimal]:
    """ticker -> quantity held at the end of `on` (from the CSV history alone)."""
    lots, _ = lots_and_sales([r for r in rows if r["date"] <= on])
    return {t: sum((lot["qty"] for lot in ls), Decimal(0)) for t, ls in lots.items()
            if sum((lot["qty"] for lot in ls), Decimal(0))}


def load_rows(path: Path | None = None) -> list[dict]:
    path = path or latest_csv()
    return revolut_invest.parse(path.read_text()) if path else []
