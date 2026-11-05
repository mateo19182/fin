"""End-to-end: a small ledger in the gross shape -> renta(2026), checked by hand.

Hand computation (params_2026):
  Trabajo (Example): two payslip months gross 2.500 (IRPF 250, SS 162,50, net 2.087,50) and one
    net-only deposit of 2.087,50 grossed up with the last payslip's rates (10% / 6,5%):
    2.087,50 / 0,835 = 2.500. Íntegros 7.500, SS 487,50, otros gastos 2.000 -> neto 5.012,50.
    Other income > 6.500 -> no art. 20 reduction -> neto reducido 5.012,50. Retenciones 750.
  Actividad (Demo invoice): base 10.000, IVA 2.100, retención 700; SS autónomo 2 x 100.
    Previo 9.800, difícil justificación 5% = 490 -> neto 9.310; rentas totales > 12.000 so no
    rentas-bajas reduction; inicio 20% x 9.310 = 1.862 -> neto reducido 7.448.
  Ahorro: interest gross 100 (withheld 19); dividend AVGO gross 10 EUR, foreign tax 1,50;
    stocks: AMD bought 2 x 100 USD at 1,25 = 160 EUR, sold 2 x 150 USD at 1,25 = 240 EUR ->
    +80; EUNK (ETF) bought 174 sold 172,28 -> -1,72. RCM 110 + ganancias 78,28 = base 188,28.
  Base general 5.012,50 + 7.448 = 12.460,50.
  Cuota estatal general: 1.182,75 + 10,50 x 12% = 1.184,01 - 5.550 x 9,5% (527,25) = 656,76.
  Cuota autonómica general: 12.460,50 x 9% = 1.121,45 - 5.789 x 9% (521,01) = 600,44.
  Ahorro: 188,28 x 9,5% = 17,89 each half -> 35,78.  Íntegra = 1.292,98.
  Doble imposición: foreign tax 1,50 (= 15% treaty cap of 10) vs 10 x (35,78 / 188,28) = 1,90
    -> 1,50.  SMI deduction: other income > 6.500 -> 0.  Cuota líquida 1.291,48.
  Pagos a cuenta: 750 + 700 + 19 = 1.469.  Resultado 1.291,48 - 1.469 = -177,52 (a devolver).
"""

from datetime import date

from fin import ledger
from fin.renta import report
from tests.test_renta_stocks import HEADER, row

ACCOUNTS = """
2024-01-01 open Income:Salary:Demo EUR
2024-01-01 open Income:Interest:Savings EUR
2024-01-01 open Expenses:Taxes:IRPF EUR
2024-01-01 open Expenses:Taxes:IRPF:Withheld EUR
2024-01-01 open Expenses:Taxes:SocialSecurity EUR
2024-01-01 open Expenses:Taxes:SocialSecurity:Employee EUR
2024-01-01 open Expenses:Taxes:Foreign:Withheld USD,EUR
2024-01-01 open Income:Activity:Demo EUR
2024-01-01 open Liabilities:Hacienda:IVA EUR
2024-01-01 open Assets:Hacienda:Retenciones EUR
2024-01-01 open Assets:Receivable:Demo EUR
2024-01-01 open Assets:Bank:Revolut:Savings EUR
"""

PAYSLIP = """
{d} * "Example" "ABONO NOMINA {m}/2026"
  transaction_id: "sal-{m}"
  payslip: "2026-{m}"
  irpf_base: "2500.00"
  irpf_rate: "0.10"
  Income:Salary:Example                      -2500.00 EUR
  Expenses:Taxes:IRPF:Withheld              250.00 EUR
  Expenses:Taxes:SocialSecurity:Employee    162.50 EUR
  Assets:Bank:Revolut:Checking             2087.50 EUR
"""

LEDGER = PAYSLIP.format(d="2026-06-02", m="05") + PAYSLIP.format(d="2026-06-29", m="06") + """
2026-07-30 * "Example" "ABONO NOMINA 07/2026"
  transaction_id: "sal-07"
  Income:Salary:Example                      -2087.50 EUR
  Assets:Bank:Revolut:Checking             2087.50 EUR

2026-08-18 * "Demo Solutions Amx" "Factura A/13"
  external_id: "inv:2026:A/13"
  Income:Activity:Demo                  -10000.00 EUR
  Liabilities:Hacienda:IVA                -2100.00 EUR
  Assets:Hacienda:Retenciones               700.00 EUR
  Assets:Receivable:Demo                 11400.00 EUR

2026-08-20 * "Demo Solutions Amx" "payment"
  transaction_id: "dep-1"
  Assets:Receivable:Demo                -11400.00 EUR
  Assets:Bank:Revolut:Checking            11400.00 EUR

2026-08-31 * "TGSS" "COTIZACION R.E.AUTONOMOS"
  transaction_id: "ss-08"
  Expenses:Taxes:SocialSecurity             100.00 EUR
  Assets:Bank:CaixaRural:Checking          -100.00 EUR

2026-09-30 * "TGSS" "COTIZACION R.E.AUTONOMOS"
  transaction_id: "ss-09"
  Expenses:Taxes:SocialSecurity             100.00 EUR
  Assets:Bank:CaixaRural:Checking          -100.00 EUR

2026-09-30 * "Revolut" "Savings interest 2026-09"
  external_id: "revsav:2026-09:01-30"
  Assets:Bank:Revolut:Savings                81.00 EUR
  Income:Interest:Savings                  -100.00 EUR
  Expenses:Taxes:IRPF:Withheld               19.00 EUR

2026-10-01 * "Dividend" "AVGO"
  external_id: "div-1"
  withholding_country: "US"
  Assets:Investment:Revolut:Cash              8.50 EUR
  Income:Investment:Dividends               -10.00 EUR
  Expenses:Taxes:Foreign:Withheld             1.50 EUR

2026-10-19 * "AEAT" "303 3T"
  transaction_id: "aeat-1"
  Expenses:Taxes:IRPF                      2000.00 EUR
  Assets:Bank:Revolut:Checking            -2000.00 EUR
"""

CSV = (HEADER
       + row("2025-03-10", "AMD", "BUY - LIMIT", 2, "100.00", "200.00")
       + row("2025-05-16", "EUNK", "BUY - LIMIT", 2, "86.50", "174", "EUR", "1.0000")
       + row("2026-02-01", "AMD", "SELL - MARKET", 2, "150.00", "300.00")
       + row("2026-03-01", "EUNK", "SELL - MARKET", 2, "86.14", "172.28", "EUR", "1.0000"))


def setup(root, csv=True):
    base = ledger.ledger_file().parent
    acc = base / "accounts" / "accounts.beancount"
    acc.write_text(acc.read_text() + ACCOUNTS)
    (base / "transactions" / "banks" / "2026-renta.beancount").write_text(LEDGER)
    sept = base / "transactions" / "banks" / "2026-09.beancount"  # drop the fixture's salary
    sept.write_text("\n\n".join(b for b in sept.read_text().split("\n\n")
                                if "Income:Salary:Example" not in b))
    (root / "config.toml").write_text((root / "config.toml").read_text()
                                      + '\n[renta]\nemployment = { Example = "2026-05-04" }\n')
    from fin import config

    config.config.cache_clear()
    if csv:
        d = root / "docs" / "2026" / "statements"
        d.mkdir(parents=True)
        (d / "revolut-invest_2026-10-25.csv").write_text(CSV)
    assert not ledger.load().errors


def test_worked_example(root):
    setup(root)
    r = report.renta(2026, today=date(2027, 1, 15))
    t = r["trabajo"]
    assert t["ingresos"]["value"] == "7500.00" and t["ingresos"]["casilla"] == "0003"
    assert t["ss"]["value"] == "487.50" and t["retenciones"]["value"] == "750.00"
    assert t["employers"]["Example"]["estimated_months"] == []  # July repeats the payslip
    assert t["reduccion"]["value"] == "0.00" and t["neto_reducido"]["value"] == "5012.50"
    a = r["actividad"]
    assert a["ingresos"]["value"] == "10000.00" and a["gastos_ss"]["value"] == "200.00"
    assert a["dificil_justificacion"]["value"] == "490.00"
    assert a["reduccion_inicio"]["value"] == "1862.00" and a["neto_reducido"]["value"] == "7448.00"
    assert a["retenciones"]["value"] == "700.00" and a["ingresos"]["entries"] == ["inv:2026:A/13"]
    s = r["ahorro"]
    assert s["intereses"]["value"] == "100.00" and s["intereses_retencion"]["value"] == "19.00"
    assert s["dividendos"]["value"] == "10.00"
    assert s["dividendos_impuesto_extranjero"]["value"] == "1.50"
    assert s["ganancias_acciones"]["value"] == "80.00" and s["ganancias_fondos"]["value"] == "-1.72"
    assert s["base"]["value"] == "188.28"
    assert r["base"]["general"]["value"] == "12460.50"
    c = r["cuota"]
    assert c["estatal"]["general"] == "656.76" and c["autonomica"]["general"] == "600.44"
    assert c["estatal"]["ahorro"] == "17.89" and c["integra"]["value"] == "1292.98"
    assert c["doble_imposicion"]["deduccion"] == "1.50" and c["deduccion_smi"]["value"] == "0.00"
    assert c["liquida"]["value"] == "1291.48"
    assert r["pagos_a_cuenta"]["total"]["value"] == "1469.00"
    assert r["resultado"]["value"] == "-177.52" and r["resultado"]["sentido"] == "a devolver"
    assert r["modelo_720"]["required"] is False
    assert not any("send a payslip" in w for w in r["warnings"])
    assert any("Expenses:Taxes:IRPF are not counted" in w for w in r["warnings"])
    assert not any("not finished" in w for w in r["warnings"])
    text = report.text(r)
    assert "RESULTADO ESTIMADO: -177.52 EUR a devolver" in text and "NOT FINAL" in text
    assert report.detail(r, "resultado")["casilla"] == "0670"


def test_warnings_without_csv_and_in_progress_year(root):
    setup(root, csv=False)
    r = report.renta(2026, today=date(2026, 10, 25))
    assert any("no Revolut Invest CSV" in w for w in r["warnings"])
    assert any("not finished" in w for w in r["warnings"])
    assert r["ahorro"]["base"]["value"] == "110.00"


def test_activity_receipt_rules(root):
    setup(root, csv=False)
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-renta.beancount"
    f.write_text(f.read_text() + """
2026-04-01 * "Example Intelligence" "FACTURA A/11"
  transaction_id: "fac-11"
  Income:Salary:Example                      -1254.00 EUR
  Assets:Bank:Revolut:Checking             1254.00 EUR

2026-10-15 * "Demo Solutions Amx" "payment"
  transaction_id: "dep-2"
  Income:Salary:Demo                     -1140.00 EUR
  Assets:Bank:Revolut:Checking             1140.00 EUR
""")
    r = report.renta(2026, today=date(2027, 1, 15))
    # 1.254 / 1,14 = 1.100 and 1.140 / 1,14 = 1.000 estimated bases on top of the 10.000 invoice
    assert r["actividad"]["ingresos"]["value"] == "12100.00"
    assert r["actividad"]["retenciones"]["value"] == "847.00"  # 700 + 77 + 70
    assert r["trabajo"]["ingresos"]["value"] == "7500.00"  # the FACTURA deposit is not salary
    assert any("2 deposit(s) without an invoice" in w for w in r["warnings"])

