"""2026-3T on the renta fixture (tests/test_renta_report.py) plus deductible costs.

303: invoice base 10.000 / cuota 2.100 (casillas 07/09). Cursor 20,70 non-EU → ISP 12/13:
  20,70 / 4,35; Renfe 23,20 with receipt, 10%: base 21,09, IVA 2,11 → 28/29 = 41,79 / 6,46
  (ISP cuota is deducted there too). 27 = 2.104,35; 45 = 6,46; 71 = 2.097,89.
130 (Jan-Sep): ingresos 10.000; SS 200; deducibles 20,70 + 21,09 + 50 (Renfe without invoice:
  IRPF only, gross) = 91,79; 5% of (10.000 - 291,79) = 485,41 → gastos 777,20; neto 9.222,80;
  20% = 1.844,56; retenciones 700 → 07 = 1.144,56; minoración 50 → 19 = 1.094,56.
"""

from datetime import date
from decimal import Decimal as D

from fin import ledger, store
from fin.renta import quarterly
from tests.test_renta_report import setup

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
"""
TXNS = """
2026-09-12 * "Cursor" "Cursor Pro"
  transaction_id: "cur-1"
  Expenses:Software                        20.70 EUR
  Assets:Bank:Revolut:Checking            -20.70 EUR

2026-09-15 * "Renfe" "Train tickets"
  transaction_id: "ren-1"
  document: "documents/2026/09/x.pdf"
  Expenses:Entertainment                   23.20 EUR
  Assets:Bank:Revolut:Checking            -23.20 EUR

2026-09-16 * "Renfe" "no receipt"
  transaction_id: "ren-2"
  Expenses:Entertainment                   50.00 EUR
  Assets:Bank:Revolut:Checking            -50.00 EUR
"""


def prepare(root):
    setup(root, csv=False)
    base = ledger.ledger_file().parent
    (base / "rules.toml").write_text(RULES)
    (base / "transactions" / "banks" / "2026-q.beancount").write_text(TXNS)
    assert not ledger.load().errors


def test_periods():
    assert quarterly.parse_period("2026-3t") == (2026, 3)
    assert quarterly.bounds(2026, 4) == (date(2026, 10, 1), date(2026, 12, 31))
    assert quarterly.deadline(2026, 4) == date(2027, 1, 30)
    assert quarterly.last_ended(date(2026, 10, 25)) == (2026, 3)
    assert quarterly.last_ended(date(2026, 2, 1)) == (2025, 4)
    assert quarterly.next_deadline(date(2026, 10, 25)) == ("2026-4T", date(2027, 1, 30))
    assert quarterly.next_deadline(date(2026, 10, 10)) == ("2026-3T", date(2026, 10, 20))
    assert quarterly.show_card(date(2026, 10, 25)) and not quarterly.show_card(date(2026, 12, 1))


def test_303_and_130(root):
    prepare(root)
    r = quarterly.quarter("2026-3T", today=date(2026, 10, 25))
    c = r["modelo_303"]["casillas"]
    assert (c["07"], c["09"]) == ("10000.00", "2100.00")
    assert (c["12"], c["13"]) == ("0.00", "0.00")  # gestor method: no self-assessment
    assert (c["28"], c["29"]) == ("41.79", "6.46")
    assert (c["27"], c["45"], c["71"]) == ("2100.00", "6.46", "2093.54")
    assert r["modelo_303"]["sentido"] == "a ingresar"
    assert [x["id"] for x in r["modelo_303"]["soportado"]["es"]] == ["ren-1"]
    k = r["modelo_130"]["casillas"]
    assert k["01"] == "10000.00" and k["02"] == "777.20" and k["03"] == "9222.80"
    assert (k["04"], k["06"], k["07"]) == ("1844.56", "700.00", "1144.56")
    assert (k["13"], k["19"]) == ("50.00", "1094.56")
    assert r["modelo_130"]["gastos"]["dificil_justificacion"] == "485.41"
    # the AEAT payment booked as 303 3T is compared, the unclassified one is an open decision
    assert any("303 2026-3T paid" in w for w in r["warnings"]) is False
    assert [o["id"] for o in r["open_decisions"]] == ["aeat-1"]
    text = quarterly.text(r)
    assert "RESULTADO [71] 2093.54" in text and "Open decisions" in text


def test_tax_payment_and_130_chain(root):
    prepare(root)
    out = quarterly.book_tax_payment("aeat-1", "303", "2026-3T")
    assert out["account"] == "Liabilities:Hacienda:IVA"
    t = ledger.load().find("aeat-1")
    assert t.meta["tax_form"] == "303" and t.meta["period"] == "2026-3T"
    r = quarterly.quarter("2026-3T", today=date(2026, 10, 25))
    assert r["payments"][0]["amount"] == "2000.00" and not r["open_decisions"]
    assert any("paid 2000.00" in w and "2093.54" in w for w in r["warnings"])
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-q.beancount"
    f.write_text(f.read_text() + """
2026-07-15 * "AEAT" "130 2T"
  transaction_id: "aeat-130"
  Expenses:Taxes:IRPF                       300.00 EUR
  Assets:Bank:Revolut:Checking             -300.00 EUR
""")
    quarterly.book_tax_payment("aeat-130", "130", "2026-2T")
    r = quarterly.quarter("2026-3T", today=date(2026, 10, 25))
    k = r["modelo_130"]["casillas"]
    assert k["05"] == "300.00" and k["07"] == "844.56" and k["19"] == "794.56"


def test_reminder_once(root):
    prepare(root)
    assert quarterly.remind(date(2026, 9, 1)) is None
    msg = quarterly.remind(date(2026, 10, 12))
    assert msg and "2026-3T" in msg and "303 estimate: 2093.54" in msg
    assert store.get("quarter_reminded") == {"2026-3T": "2026-10-12"}
    assert quarterly.remind(date(2026, 10, 13)) is None
    assert D(quarterly.quarter("2026-2T", today=date(2026, 10, 25))["modelo_303"]["resultado"]) == 0
