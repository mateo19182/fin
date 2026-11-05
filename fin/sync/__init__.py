"""Daily sync: fetch from every source, ingest, notify. Per-source failures are reported."""

from datetime import date, timedelta

from fin import ledger, store
from fin.models import Candidate

SOURCES = ("prices", "banks", "indexa", "wallets")
OVERLAP = timedelta(days=5)


def since_date(lg: ledger.Ledger) -> date:
    last = store.get("last_sync")
    if last:
        return date.fromisoformat(last) - OVERLAP
    dates = [t.date for t in lg.transactions if "transaction_id" in t.meta]
    last = max(dates) if dates else max(t.date for t in lg.transactions) - timedelta(days=30)
    return last - OVERLAP


def run(sources: list[str] | None = None, dry_run: bool = False) -> dict:
    from fin import alerts, ingest, notify
    from fin.renta import quarterly
    from fin.sync import banks, indexa, prices, wallets

    todo = [s for s in SOURCES if not sources or s in sources]
    lg = ledger.load()
    res: dict = {"since": None, "sources": {}, "errors": [], "dry_run": dry_run}
    cands: list[Candidate] = []

    def attempt(name, fn):
        try:
            return fn()
        except Exception as e:  # one source failing must not stop the others
            res["errors"].append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
            return None

    if "prices" in todo:
        res["sources"]["prices"] = attempt("prices", lambda: prices.update() if not dry_run else 0)
    if "banks" in todo:
        res["since"] = since_date(lg).isoformat()
        got = attempt("banks", lambda: banks.fetch(date.fromisoformat(res["since"])))
        cands += got or []
        res["sources"]["banks"] = dict(banks.last_result)
        for key, r in banks.last_result.items():
            if not r["ok"]:
                res["errors"].append(f"banks/{key}: {r['error']}")
    if "indexa" in todo:
        res["sources"]["indexa"] = attempt("indexa", lambda: indexa.update() if not dry_run
                                           else {"skipped": "dry-run"})
    if "wallets" in todo:
        got = attempt("wallets", wallets.fetch)
        cands += got or []
        res["sources"]["wallets"] = len(got or [])

    res["ingest"] = ingest.ingest(cands, dry_run=dry_run)
    if not dry_run and "banks" in todo:
        today = date.today().isoformat()
        ok = {k: today for k, r in banks.last_result.items() if r["ok"]}
        if ok:
            store.put("last_sync", today)
            store.put("bank_last_sync", {**store.get("bank_last_sync", {}), **ok})
    res["notified"] = notify.after_sync(res, dry_run=dry_run)
    res["alerts"] = attempt("alerts", lambda: alerts.run(res["ingest"], dry_run=dry_run))
    res["quarter_reminder"] = attempt("quarter", lambda: quarterly.remind(dry_run=dry_run))
    return res
