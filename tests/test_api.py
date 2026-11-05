import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(fin_root):
    from fin.api import app

    return TestClient(app)


@pytest.mark.parametrize("path", [
    "/api/overview", "/api/overview?start=2026-08-01&end=2026-10-25", "/api/holdings",
    "/api/cashflow?start=2026-05-01&end=2026-10-25",
    "/api/cashflow?start=2026-01-01&bucket=quarter",
    "/api/subscriptions", "/api/accounts", "/api/pending", "/api/transactions?q=netflix",
    "/api/sync", "/api/transactions/recent-auto", "/api/period?range=3m",
    "/api/period?range=2026-07..2026-09", "/api/portfolio/series?start=2026-07-01",
    "/api/categories?start=2026-07-01&end=2026-09-30",
    "/api/categories?start=2026-07-01&end=2026-09-30&compare=prev,yoy",
])
def test_gets(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    assert r.json() is not None


def test_overview_shape(client):
    o = client.get("/api/overview").json()
    assert {"net_worth", "series", "totals", "categories", "pending"} <= o.keys()
    assert o["net_worth"]["total"] > 0
    assert {"income", "expenses", "savings", "prev", "yoy"} <= o["totals"].keys()


def test_period_and_compare_validation(client):
    p = client.get("/api/period?range=1m").json()
    assert {"start", "end", "prev", "yoy", "months"} <= p.keys()
    assert client.get("/api/period?range=2w").status_code == 400
    assert client.get("/api/period?range=2026-09..2026-07").status_code == 400
    assert client.get("/api/overview?start=2026-10-01&end=2026-09-01").status_code == 400
    assert client.get("/api/cashflow?bucket=week").status_code == 400
    r = client.get("/api/categories?start=2026-10-01&end=2026-10-25&compare=prev")
    assert r.status_code == 200 and "prev" in r.json()[0] and "yoy" not in r.json()[0]
    bad = client.get("/api/categories?start=2026-10-01&end=2026-10-25&compare=x")
    assert bad.status_code == 400


def test_transactions_filters(client):
    r = client.get("/api/transactions", params={"account": "Expenses:Food", "limit": 2})
    body = r.json()
    assert body["total"] == 4 and len(body["items"]) == 2


def test_categories_rejects_bad_kind(client):
    assert client.get("/api/categories?start=2026-01-01&end=2026-02-01&kind=X").status_code == 400


def test_spa_fallback_without_build(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    r = client.get("/some/route")
    assert r.status_code in (200, 404)  # index.html if built, else a clear 404 message


def test_web_prefix_is_stripped_and_announced(client, fin_root):
    from fin import config
    from fin.api import WEB_DIST

    assert config.web_prefix() == ""  # localhost default
    (fin_root / "config.toml").write_text(
        'ledger = "ledger/main.beancount"\ndata_dir = "data"\n'
        '[web]\nbase_url = "http://localhost:8742/fin"\n')
    config.config.cache_clear()
    assert config.web_prefix() == "/fin"
    assert client.get("/fin/api/accounts").json() == client.get("/api/accounts").json()
    assert client.get("/fin").status_code == client.get("/").status_code
    if (WEB_DIST / "index.html").exists():
        html = client.get("/fin/review").text
        assert '<meta name="fin-prefix" content="/fin">' in html
        assert 'src="./assets/' in html  # relative assets work under any prefix
    (fin_root / "config.toml").write_text(
        'ledger = "ledger/main.beancount"\ndata_dir = "data"\n[web]\nbase_url = "http://x/"\n')
    config.config.cache_clear()
    assert config.web_prefix() == "" and config.web_url("/review") == "http://x/review"
    r = client.get("/fin/api/accounts")  # no prefix configured: just an unknown SPA route
    assert r.status_code == 404 or "text/html" in r.headers["content-type"]
    (fin_root / "config.toml").write_text('ledger = "ledger/main.beancount"\ndata_dir = "data"\n')
    config.config.cache_clear()


# --- status / close / net worth / detail / rules (per-test FIN_ROOT copy, see conftest) ---


@pytest.fixture
def wclient(root):
    from fin.api import app

    return TestClient(app)


def test_status(wclient):
    r = wclient.get("/api/status")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {a["account"]: a for a in body["accounts"]}
    assert rows["Assets:Bank:Revolut:Checking"]["updates_via"] == "bank"
    assert {"ok", "warn", "error"} == set(body["summary"]["accounts"])


def test_close_and_default_month(wclient):
    from datetime import date

    from fin.api import default_close_month

    assert default_close_month(date(2026, 10, 5)) == "2026-09"
    assert default_close_month(date(2026, 10, 11)) == "2026-10"
    assert default_close_month(date(2026, 1, 3)) == "2025-12"
    r = wclient.get("/api/close?month=2026-09")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["month"] == "2026-09" and body["stats"]["income"] == "2000.00"
    assert {i["key"] for i in body["checklist"]} == {"stocks_csv", "savings_csv", "pending",
                                                     "balances", "banks"}
    assert wclient.get("/api/close?month=2026-9").status_code == 422
    assert wclient.get("/api/close").status_code == 200


def test_networth(wclient):
    r = wclient.get("/api/networth?months=2&end=2026-10-15")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["month"] for x in rows] == ["2026-08", "2026-09", "2026-10"]
    assert {"saved", "contributions", "market", "groups", "total", "change"} <= rows[0].keys()


def test_detail_read_update_attach_and_document(wclient, root):
    r = wclient.get("/api/transactions/t-pepe-1/detail")
    assert r.status_code == 200 and r.json()["payee"] == "Bar Pepe"
    assert wclient.get("/api/transactions/nope/detail").status_code == 404

    r = wclient.patch("/api/transactions/t-pepe-1/detail", json={"note": "with Ana",
                                                                 "narration": "cañas"})
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["note"] == "with Ana" and r.json()["narration"] == "cañas"

    r = wclient.post("/api/transactions/t-pepe-1/attachment",
                     files={"file": ("ticket.PDF", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200, r.text
    docs = r.json()["documents"]
    assert docs == ["2026/receipts/2026-09-06_bar-pepe.pdf"]
    assert (root / "docs" / docs[0]).read_bytes() == b"%PDF-1.4 x"

    r = wclient.get(f"/api/documents/{docs[0]}")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 x"
    assert wclient.get("/api/documents/2026/receipts/missing.pdf").status_code == 404
    # anything outside the documents folder is refused, however it is spelled
    assert wclient.get("/api/documents/../config.toml").status_code in (400, 404)
    assert wclient.get("/api/documents/2026/../../config.toml").status_code in (400, 404)
    assert wclient.get("/api/documents/%2E%2E/config.toml").status_code == 400
    assert wclient.post("/api/transactions/t-pepe-1/attachment",
                        files={"file": ("x.pdf", b"", "application/pdf")}).status_code == 400


def test_rules(wclient):
    from fin import payees

    assert payees.list_rules() == []
    rule = {"match": "^Bar Pepe$", "account": "Expenses:Food:Restaurant"}
    r = wclient.post("/api/rules", json=rule)
    assert r.status_code == 201, r.text
    assert payees.list_rules() == [rule]
    for bad in ({"match": "(", "account": "Expenses:Food"}, {"match": "x"},
                {"match": "x", "account": "Expenses:Nope"}):
        assert wclient.post("/api/rules", json=bad).status_code == 400


def test_import_savings_dry_run_then_confirm(wclient, root):
    from tests.test_revolut_savings import STATEMENT, setup_accounts

    setup_accounts(root)
    files = {"file": ("savings.csv", STATEMENT.encode(), "text/csv")}
    r = wclient.post("/api/import/savings?dry_run=true", files=files)
    assert r.status_code == 200, r.text
    dry = r.json()
    assert dry["imported"] == 0 and len(dry["interest"]) == 2 and dry["preview"]
    r = wclient.post("/api/import/savings", files=files)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2
    empty = {"file": ("e.csv", b"", "text/csv")}
    assert wclient.post("/api/import/savings", files=empty).status_code == 400


def test_deductible_and_quarter_endpoints(wclient):
    r = wclient.get("/api/transactions/t-pepe-1/detail")
    assert r.json()["deductible"] == {"on": False, "pct": 0, "reason": "", "vat": None,
                                      "vat_rate": None, "equipment": False, "vat_pct": 0,
                                      "iva_blocked": False}
    r = wclient.patch("/api/transactions/t-pepe-1/deductible", json={"on": True, "pct": 50})
    assert r.status_code == 200 and r.json()["deductible"]["pct"] == 50
    assert wclient.patch("/api/transactions/t-pepe-1/deductible",
                         json={"on": True, "pct": 101}).status_code == 400
    r = wclient.post("/api/rules/deductible", json={"payee": "Bar Pepe", "on": True})
    assert r.status_code == 200 and r.json()["match"] == "^Bar\\ Pepe$"
    subs = wclient.get("/api/subscriptions").json()
    assert all("deductible" in s for s in subs)
    r = wclient.get("/api/quarter?period=2026-3T")
    assert r.status_code == 200 and r.json()["period"] == "2026-3T"
    assert {"modelo_303", "modelo_130", "show_card", "open_decisions"} <= r.json().keys()
    assert wclient.get("/api/quarter?period=2026-5T").status_code == 422
