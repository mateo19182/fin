from datetime import date
from decimal import Decimal as D

import pytest

from fin import activity, ledger, payees, receipts
from fin.renta import pdf

RULES = """
[[rule]]
match = "^Cursor\\\\b"
deductible = true
vat = "non_eu"

[[rule]]
match = "^Renfe\\\\b"
deductible = true
requires_receipt = true
vat = "es"
vat_rate = 10

[[rule]]
match = "^Gas$"
deductible = true
deductible_pct = 50
requires_receipt = true
vat = "es"
vat_rate = 21
"""

TXNS = """
2026-03-08 * "Laptop Shop" "new laptop"
  transaction_id: "lap-1"
  deductible: "true"
  equipment: "true"
  vat: "es"
  Expenses:Software                      2576.60 EUR
  Assets:Bank:Revolut:Checking          -2576.60 EUR

2026-09-12 * "Cursor" "Cursor Pro"
  transaction_id: "cur-1"
  Expenses:Software                        20.70 EUR
  Assets:Bank:Revolut:Checking            -20.70 EUR

2026-09-15 * "Renfe" "Train tickets"
  transaction_id: "ren-1"
  Expenses:Entertainment                   23.20 EUR
  Assets:Bank:Revolut:Checking            -23.20 EUR

2026-09-16 * "Gas" "fuel"
  transaction_id: "gas-1"
  document: "documents/2026/09/ticket.jpg"
  Expenses:Entertainment                   60.50 EUR
  Assets:Bank:Revolut:Checking            -60.50 EUR

2026-09-17 * "Netflix" "Netflix"
  transaction_id: "net-1"
  deductible: "false"
  Expenses:Software                        12.99 EUR
  Assets:Bank:Revolut:Checking            -12.99 EUR
"""


def setup(root):
    payees.rules_file().write_text(RULES)
    base = ledger.ledger_file().parent / "transactions" / "banks"
    (base / "2026-act.beancount").write_text(TXNS)
    assert not ledger.load().errors


def test_resolver_precedence(root):
    setup(root)
    lg = ledger.load()
    d = activity.deductible(lg.find("cur-1"))
    assert (d.on, d.pct, d.reason, d.vat, d.vat_rate) == (True, 100, "rule", "non_eu", None)
    d = activity.deductible(lg.find("ren-1"))  # no invoice: IRPF only, IVA left out
    assert (d.on, d.reason, d.iva_blocked) == (True, "no invoice: IRPF only", True)
    d = activity.deductible(lg.find("gas-1"))
    assert (d.on, d.pct, d.vat_rate) == (True, 50, D("0.21"))
    assert activity.deductible(lg.find("net-1")).reason == "meta"
    assert not activity.deductible(lg.find("net-1")).on
    lap = activity.deductible(lg.find("lap-1"))
    assert lap.on and lap.equipment and lap.vat_rate == D("0.21")
    # payees.match ignores activity-only rules so they never shadow rename/account rules
    assert payees.match("Cursor") is None


def test_costs_and_amortisation(root):
    setup(root)
    lg = ledger.load()
    costs = {c["id"]: c for c in activity.costs(lg, date(2026, 1, 1), date(2026, 12, 31))}
    assert set(costs) == {"lap-1", "cur-1", "gas-1", "ren-1"}
    assert costs["ren-1"]["base"] == D("23.20") and costs["ren-1"]["iva"] == D("0")
    assert costs["cur-1"]["base"] == D("20.70") and costs["cur-1"]["iva"] == D("0")
    assert costs["gas-1"]["base"] == D("25.00") and costs["gas-1"]["iva"] == D("5.25")  # 50%
    assert costs["lap-1"]["base"] == D("2129.42") and costs["lap-1"]["iva"] == D("447.18")
    rows = activity.amortisation(lg, date(2026, 1, 1), date(2026, 12, 31))
    assert len(rows) == 1 and rows[0]["annual"] == D("553.65")
    # 299 days of 2026 (8 Mar - 31 Dec inclusive): 553.65 x 299 / 365
    assert rows[0]["amount"] == D("453.54")
    q3 = activity.amortisation(lg, date(2026, 7, 1), date(2026, 9, 30))[0]["amount"]
    assert q3 == D("139.55")  # 92 days
    full = activity.amortisation(lg, date(2026, 1, 1), date(2031, 12, 31))
    assert full[0]["amount"] == D("2129.42")


def test_set_deductible_and_payee_rule(root):
    setup(root)
    r = activity.set_deductible("ren-1", True, 40)
    assert r["on"] and r["pct"] == 40 and r["reason"] == "meta"
    assert activity.set_deductible("ren-1", False)["on"] is False
    assert not ledger.load().errors
    rule = activity.set_payee_deductible("Netflix", True, 30)
    assert rule == {"match": "^Netflix$", "deductible": True, "deductible_pct": 30}
    rule = activity.set_payee_deductible("Netflix", False)
    assert rule["deductible"] is False and rule["deductible_pct"] == 30
    assert payees.rules_file().read_text().count("^Netflix$") == 1
    rule = activity.set_payee_deductible("Cursor", True, 80, vat="oss")
    assert rule["match"] == "^Cursor\\b" and rule["vat"] == "oss" and rule["deductible_pct"] == 80
    with pytest.raises(ValueError):
        activity.set_payee_deductible("X", True, 150)


RECEIPT = """
RENFE VIAJEROS S.M.E., S.A.  NIVA: ESA86868189
FACTURA NÚMERO: VJ0001                      MADRID, 15 de SEPTIEMBRE de 2026
Total Servicio:          21,09
Cuota IVA:                2,11
Total Factura           23,20
IVA REPERCUTIDO_10% (DESDE 01.09.2012)   21,09   10,00   2,11
"""
USD_RECEIPT = """
Invoice number 07876C85-0027
Date of issue  September 12, 2026
Cursor Pro        1   $20.00   21%   $20.00
Total excluding tax   $20.00
VAT - Spain (21% on $20.00)   $4.20
Total             $24.20
Amount due        $24.20 USD
Anysphere, Inc.
"""


def test_receipt_parse_and_match(root, monkeypatch, tmp_path):
    setup(root)
    (ledger.ledger_file().parent / "prices" / "prices.beancount").write_text(
        "2026-09-10 price EUR 1.17 USD\n", "utf-8")
    f = tmp_path / "renfe.pdf"
    f.write_bytes(b"%PDF fake")
    monkeypatch.setattr(pdf, "text", lambda p: RECEIPT if "renfe" in str(p) else USD_RECEIPT)
    parsed = receipts.parse(f)
    assert date(2026, 9, 15) in parsed["dates"]
    assert parsed["amounts"][0] == (D("23.20"), "EUR")
    r = receipts.receipt(f)
    assert r["status"] == "attached" and r["id"] == "ren-1"
    t = ledger.load().find("ren-1")
    assert t.meta["document"] == "2026/receipts/2026-09-15_renfe.pdf"
    assert (root / "docs" / t.meta["document"]).read_bytes() == b"%PDF fake"
    assert t.meta["deductible"] == "true" and r["deductible"]["on"]
    assert receipts.receipt(f)["status"] == "already attached"
    g = tmp_path / "cursor.pdf"
    g.write_bytes(b"%PDF fake 2")
    r = receipts.receipt(g)  # 24.20 USD / 1.17 = 20.68 ~ 20.70 EUR, payee named in the text
    assert r["status"] == "attached" and r["id"] == "cur-1"
    assert not ledger.load().errors


def test_receipt_unmatched_is_kept(root, monkeypatch, tmp_path):
    setup(root)
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")
    monkeypatch.setattr(pdf, "text", lambda p: "Total 99,99 EUR\nFecha 15/09/2026")
    r = receipts.receipt(f)
    assert r["status"] == "unmatched" and r["reason"] == "no transaction matches"
    assert (root / "docs" / r["kept"]).exists()
    assert r["kept"] == "2026/receipts/unmatched-2026-09-15_x.pdf"
    r = receipts.receipt(f, entry_id="net-1")
    assert r["status"] == "attached" and not r["deductible"]["on"]


def test_amounts_and_dates_parsing():
    txt = "Importe total a pagar   12,95 €\nTotal IVA 10%   1,18 €\nAug 8, 2026\n4. April 2026"
    assert receipts.amounts_in(txt)[0] == (D("12.95"), "EUR")
    assert set(receipts.dates_in(txt)) == {date(2026, 8, 8), date(2026, 4, 4)}
    assert receipts.amounts_in("Total   2.576,70 €")[0] == (D("2576.70"), "EUR")
    assert receipts.amounts_in("Amount paid  $1,234.56")[0] == (D("1234.56"), "USD")
    ds, amts = receipts.parse_filename("2026-03-25-uber-24.73.jpg")
    assert ds == [date(2026, 3, 25)] and amts == [(D("24.73"), "EUR")]


def test_irpf_and_vat_shares(root):
    """Fuel in a mixed-use car: 0% IRPF, 50% IVA, and only with the invoice."""
    payees.rules_file().write_text(RULES.replace(
        'match = "^Gas$"\ndeductible = true\ndeductible_pct = 50',
        'match = "^Gas$"\ndeductible = true\ndeductible_pct = 0\nvat_pct = 50'))
    base = ledger.ledger_file().parent / "transactions" / "banks"
    (base / "2026-act.beancount").write_text(TXNS + """
2026-09-18 * "Gas" "fuel, no invoice"
  transaction_id: "gas-2"
  Expenses:Transport                       30.00 EUR
  Assets:Bank:Revolut:Checking            -30.00 EUR
""")
    lg = ledger.load()
    c = activity.cost(lg.find("gas-1"), lg)
    assert (c["base"], c["iva"], c["vat_base"]) == (D("0.00"), D("5.25"), D("25.00"))
    assert activity.cost(lg.find("gas-2"), lg) is None  # nothing without the invoice
    assert activity.deductible(lg.find("gas-2")).iva_blocked
