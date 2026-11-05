"""HTTP API + static SPA. Single user behind Tailscale: no auth.

The app is reached directly (http://127.0.0.1:8742/) and behind `tailscale serve --set-path /fin`,
which strips the prefix before proxying. Both work: a request that still carries the prefix
is stripped here, and index.html is served with the prefix in a meta tag so the SPA knows
its base when the browser URL starts with it.
"""

import re
import threading
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fin import activity, analytics, close, config, details, ingest, networth, payees, status, store
from fin.ledger import load
from fin.renta import quarterly
from fin.sync import banks, revolut_invest, revolut_savings

api = APIRouter(prefix="/api")
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
PREFIX_META = '<meta name="fin-prefix" content="">'


def _pending_count() -> int:
    try:
        return len(store.list_pending())
    except Exception:
        return 0


# --- read -------------------------------------------------------------------


def _compare(s: str) -> set[str]:
    keys = {k for k in s.split(",") if k}
    if not keys <= {"prev", "yoy"}:
        raise HTTPException(400, "compare must be prev, yoy or prev,yoy")
    return keys


def _span(start: date | None, end: date | None) -> tuple[date, date]:
    """Default period: this month so far."""
    today = date.today()
    start, end = start or analytics.month_start(today), end or today
    if start > end:
        raise HTTPException(400, "start after end")
    return start, end


@api.get("/period")
def period(range: str = "1m"):
    ledger = load()
    return analytics.resolve_period(range, first=analytics.first_date(ledger))


@api.get("/overview")
def overview(start: date | None = None, end: date | None = None):
    return analytics.overview(load(), *_span(start, end), pending_count=_pending_count())


@api.get("/cashflow")
def cashflow(start: date | None = None, end: date | None = None, bucket: str = "month"):
    if bucket not in ("month", "quarter"):
        raise HTTPException(400, "bucket must be month or quarter")
    return analytics.cashflow_series(load(), *_span(start, end), bucket)


@api.get("/categories")
def categories(start: date, end: date, kind: str = "Expenses", compare: str = ""):
    if kind not in ("Expenses", "Income"):
        raise HTTPException(400, "kind must be Expenses or Income")
    keys = _compare(compare)
    if not keys:
        return analytics.categories(load(), start, end, kind)
    return analytics.categories_compared(load(), start, end, kind, keys)


@api.get("/portfolio/series")
def portfolio_series(start: date | None = None, end: date | None = None):
    return analytics.portfolio_series(load(), *_span(start, end))


@api.get("/transactions")
def transactions(start: date | None = None, end: date | None = None, account: str | None = None,
                 q: str | None = None, auto: bool = False,
                 limit: int = Query(200, ge=1, le=5000), offset: int = Query(0, ge=0)):
    return analytics.transactions(load(), start, end, account, q, auto, limit, offset)


@api.get("/transactions/recent-auto")
def recent_auto(days: int = Query(30, ge=1, le=365)):
    return analytics.recent_auto(load(), days)


@api.get("/holdings")
def holdings(start: date | None = None, end: date | None = None):
    return analytics.holdings(load(), end, start)


@api.get("/subscriptions")
def subscriptions():
    return analytics.subscriptions(load())


@api.get("/accounts")
def accounts():
    return load().accounts()


@api.get("/pending")
def pending():
    return store.list_pending()


# --- write ------------------------------------------------------------------


class AccountBody(BaseModel):
    account: str


@api.patch("/transactions/{entry_id}")
def recategorize(entry_id: str, body: AccountBody):
    ingest.recategorize(entry_id, body.account)
    return {"ok": True}


@api.post("/pending/{external_id}/approve")
def approve(external_id: str, body: AccountBody):
    ingest.approve(external_id, body.account)
    return {"ok": True, "pending": _pending_count()}


@api.post("/pending/{external_id}/dismiss")
def dismiss(external_id: str):
    ingest.dismiss(external_id)
    return {"ok": True, "pending": _pending_count()}


# --- sources ----------------------------------------------------------------


@api.get("/banks")
def bank_status():
    return banks.status()


@api.post("/banks/{key}/auth/start")
def auth_start(key: str):
    return {"url": banks.auth_start(key)}


class CodeBody(BaseModel):
    code: str


@api.post("/banks/{key}/auth/complete")
def auth_complete(key: str, body: CodeBody):
    banks.auth_complete(key, body.code.strip())
    return {"ok": True}


_sync_lock = threading.Lock()
_sync_state: dict = {"running": False}


def _run_sync(sources: list[str] | None):
    started = datetime.now().isoformat(timespec="seconds")
    try:
        from fin.sync import run

        result = run(sources)
        last = {"started": started, "ok": True, "result": result}
    except Exception as e:
        traceback.print_exc()
        last = {"started": started, "ok": False, "error": f"{type(e).__name__}: {e}"}
    last["finished"] = datetime.now().isoformat(timespec="seconds")
    try:
        store.put("last_sync", last)
    finally:
        with _sync_lock:
            _sync_state["running"] = False


class SyncBody(BaseModel):
    sources: list[str] | None = None


@api.get("/sync")
def sync_status():
    return {"running": _sync_state["running"], "last": store.get("last_sync")}


@api.post("/sync", status_code=202)
def sync_start(body: SyncBody | None = None):
    with _sync_lock:
        if _sync_state["running"]:
            return JSONResponse({"running": True}, status_code=409)
        _sync_state["running"] = True
    threading.Thread(target=_run_sync, args=(body.sources if body else None,),
                     daemon=True).start()
    return {"running": True}


@api.post("/revolut/csv")
async def revolut_csv(file: UploadFile, dry_run: bool = False):
    data = await file.read()
    r = revolut_invest.import_csv(data.decode("utf-8-sig"), dry_run=dry_run)
    if not dry_run:
        r["archived"] = str(revolut_invest.archive(data))
    return r


@api.post("/import/savings")
async def import_savings(file: UploadFile, dry_run: bool = False):
    data = await file.read()
    r = revolut_savings.import_csv(data.decode("utf-8-sig"), dry_run=dry_run)
    if not dry_run:
        r["archived"] = str(revolut_savings.archive(data))
    return r


# --- status / close / net worth ---------------------------------------------


@api.get("/status")
def account_status():
    return {"accounts": status.accounts_status(), "summary": status.summary()}


def default_close_month(today: date | None = None) -> str:
    """Previous month until the 10th (time to import statements), then the current one."""
    today = today or date.today()
    if today.day > 10:
        return f"{today:%Y-%m}"
    first = today.replace(day=1)
    return f"{first - timedelta(days=1):%Y-%m}"


@api.get("/close")
def close_month(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$")):
    month = month or default_close_month()
    return {"month": month, "checklist": close.checklist(month), "stats": close.stats(month),
            "deductions": close.deductions(month)}


@api.get("/networth")
def networth_series(months: int = Query(12, ge=1, le=600), end: date | None = None):
    """Monthly rows ending at `end` (default today): `months` full months plus the end month."""
    today = min(end or date.today(), date.today())
    return networth.series(months, today)


# --- transaction detail -----------------------------------------------------


def _detail(entry_id: str) -> dict:
    try:
        return details.get(entry_id)
    except KeyError:
        raise HTTPException(404, entry_id) from None


@api.get("/transactions/{entry_id}/detail")
def detail(entry_id: str):
    return _detail(entry_id)


class DetailBody(BaseModel):
    payee: str | None = None
    narration: str | None = None
    note: str | None = None


@api.patch("/transactions/{entry_id}/detail")
def update_detail(entry_id: str, body: DetailBody):
    _detail(entry_id)
    return details.update(entry_id, body.payee, body.narration, body.note)


@api.post("/transactions/{entry_id}/attachment")
async def attach(entry_id: str, file: UploadFile):
    _detail(entry_id)
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    return details.attach(entry_id, file.filename or "file", data)


@api.get("/documents/{rel:path}")
def document(rel: str):
    path = details.document_path(rel)
    if not path.is_file():
        raise HTTPException(404, rel)
    return FileResponse(path)


class DeductibleBody(BaseModel):
    on: bool
    pct: int | None = None


@api.patch("/transactions/{entry_id}/deductible")
def set_deductible(entry_id: str, body: DeductibleBody):
    _detail(entry_id)
    activity.set_deductible(entry_id, body.on, body.pct)
    return _detail(entry_id)


class PayeeDeductibleBody(BaseModel):
    payee: str
    on: bool
    pct: int | None = None


@api.post("/rules/deductible")
def payee_deductible(body: PayeeDeductibleBody):
    return activity.set_payee_deductible(body.payee.strip(), body.on, body.pct)


@api.get("/quarter")
def quarter(period: str | None = Query(None, pattern=r"^\d{4}-[1-4]T$")):
    r = quarterly.quarter(period)
    r["show_card"] = quarterly.show_card()
    return r


# --- rules ------------------------------------------------------------------


class RuleBody(BaseModel):
    match: str
    payee: str | None = None
    account: str | None = None


@api.post("/rules", status_code=201)
def add_rule(body: RuleBody):
    try:
        return payees.add_rule(body.match, body.payee or None, body.account or None)
    except re.error as e:
        raise HTTPException(400, f"bad regex: {e}") from e


# --- app --------------------------------------------------------------------

app = FastAPI(title="fin", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(api)


@app.exception_handler(KeyError)
@app.exception_handler(ValueError)
async def bad_request(request: Request, exc: Exception):
    return JSONResponse({"detail": str(exc)}, status_code=400)


class StripPrefix:
    """Drop the configured web prefix ("/fin") when a proxy left it on the path."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        prefix = config.web_prefix()
        path = scope.get("path", "")
        if scope["type"] == "http" and prefix and (path == prefix or path.startswith(prefix + "/")):
            scope = {**scope, "path": path[len(prefix):] or "/"}
        await self.app(scope, receive, send)


app.add_middleware(StripPrefix)

if (WEB_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    if "assets/" in path:  # relative asset URL resolved from a nested route like /fin/review/
        candidate = WEB_DIST / "assets" / path.rsplit("assets/", 1)[1]
    else:
        candidate = WEB_DIST / path
    if path and candidate.is_file() and candidate.resolve().is_relative_to(WEB_DIST.resolve()):
        return FileResponse(candidate)
    index = WEB_DIST / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "web/dist not built; run `cd web && npm run build`"}, 404)
    html = index.read_text().replace(PREFIX_META, PREFIX_META.replace('""',
                                                                      f'"{config.web_prefix()}"'))
    return HTMLResponse(html)


def serve(host: str | None = None, port: int | None = None):
    import uvicorn

    cfg = config.config()
    uvicorn.run("fin.api:app", host=host or cfg.get("host", "127.0.0.1"),
                port=port or int(cfg.get("port", 8742)))


if __name__ == "__main__":
    serve()
