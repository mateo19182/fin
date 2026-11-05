# ruff: noqa: E501  (pdftotext -layout fixtures keep their column widths)
from decimal import Decimal as D

import pytest

from fin import ledger
from fin.renta import payslips

# Layout of the real payslips (pdftotext -layout), amounts changed.
PAYSLIP = """
                  EMPRESA                     DOMICILIO                 Nº INSCRIPCIÓN S.S.

 ACME ROBOTICS S L                           CL FALSA 123                   15/0000000-00

                 TRABAJADOR                 CATEGORIA         PUESTO DE TRABAJO   ANTIGÜEDAD

 PEREZ, JUAN                                 ÁREA 3            DESARROLLADOR      04/05/2026

     15/00000000-00     2   6210   000052   Mensual - 1 Junio 2026 a 30 Junio 2026        30

  CUANTIA   PRECIO       CONCEPTO                              DEVENGOS      DEDUCCIONES

     30,00    65,67    1    *Salario Base                       2400,00
     30,00     1,77   14    *RF TRANSPORTE EXENTO                 100,00
                            Descuento Conceptos en Especie                       100,00
                            Cotización Contingencias Comunes (4,70%)             117,50
                            Cotización Mecanismo Equidad Intergeneracional (0,15%)  3,75
                            Cotización Formación Profesional (0,10%)               2,50
                            Cotización Desempleo (1,55%)                          38,75
                            Tributación IRPF (10,00%)                            240,00

   REM. TOTAL   P.P. EXTRAS   BASE C.C.   BASE A.T. Y DES   BASE I.R.P.F.   T. DEVENGADO   T. A DEDUCIR

     2500,00                  2500,00         2500,00          2400,00          2500,00         502,50
  FECHA                        SELLO EMPRESA              RECIBI
  martes, 30 de Junio de 2026
                                                                     Líquido a Percibir
  CORUÑA, A

                                                                              1997,50
"""


def test_parse_text():
    p = payslips.parse_text(PAYSLIP)
    assert p["employer"] == "Acme" and p["employer_raw"] == "ACME ROBOTICS S L"
    assert p["month"] == "2026-06" and p["period_start"].isoformat() == "2026-06-01"
    assert p["gross"] == D("2500.00") and p["net"] == D("1997.50")
    assert p["ss"] == D("162.50") and p["irpf"] == D("240.00") and p["other"] == D("100.00")
    assert p["irpf_base"] == D("2400.00") and p["irpf_rate"] == D("0.10")


def test_parse_rejects_inconsistent_totals():
    with pytest.raises(ValueError, match="does not add up"):
        payslips.parse_text(PAYSLIP.replace("1997,50", "1997,51"))


PARSED = {"employer": "Example", "month": "2026-05", "gross": D("2500.00"), "irpf": D("250.00"),
          "ss": D("162.50"), "net": D("2087.50"), "other": D("0.00"), "irpf_base": D("2500.00"),
          "irpf_rate": D("0.10")}


def deposit(root, day="2026-06-02", amount="2087.50", narration="ABONO NOMINA 05/2026"):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-06.beancount"
    f.write_text(f'{day} * "Example" "{narration}"\n  transaction_id: "sal-1"\n  source: "revolut"\n'
                 f"  Income:Salary:Example   -{amount} EUR\n  Assets:Bank:Revolut:Checking  {amount} EUR\n")


def test_book_rewrites_the_net_deposit(root):
    deposit(root)
    r = payslips.book(PARSED, dry_run=True)
    assert r["id"] == "sal-1" and "Expenses:Taxes:IRPF:Withheld" in r["after"]
    assert ledger.load().find("sal-1").meta.get("payslip") is None

    r = payslips.book(PARSED)
    lg = ledger.load()
    assert not lg.errors
    t = lg.find("sal-1")
    assert t.meta["payslip"] == "2026-05" and t.meta["irpf_base"] == "2500.00"
    assert t.meta["transaction_id"] == "sal-1" and t.meta["source"] == "revolut"
    got = {p.account: p.units.number for p in t.postings}
    assert got == {"Income:Salary:Example": D("-2500.00"),
                   "Expenses:Taxes:IRPF:Withheld": D("250.00"),
                   "Expenses:Taxes:SocialSecurity:Employee": D("162.50"),
                   "Assets:Bank:Revolut:Checking": D("2087.50")}
    with pytest.raises(ValueError, match="no Example deposit"):
        payslips.book(PARSED)  # already rewritten: not matched again


def test_book_with_other_deductions_and_no_match(root):
    deposit(root, amount="1997.50")
    with pytest.raises(ValueError, match="no Example deposit of 2087.50"):
        payslips.book(PARSED)
    other = {**PARSED, "net": D("1997.50"), "other": D("90.00"), "irpf_base": D("2410.00")}
    payslips.book(other)
    t = ledger.load().find("sal-1")
    assert next(p.units.number for p in t.postings
                if p.account == payslips.DEDUCTIONS) == D("90.00")


def test_book_disambiguates_by_narration(root):
    f = ledger.ledger_file().parent / "transactions" / "banks" / "2026-06.beancount"
    f.write_text('2026-06-02 * "Example" "ABONO NOMINA 05/2026"\n  transaction_id: "a"\n'
                 "  Income:Salary:Example   -2087.50 EUR\n  Assets:Bank:Revolut:Checking  2087.50 EUR\n\n"
                 '2026-06-03 * "Example" "Bonus"\n  transaction_id: "b"\n'
                 "  Income:Salary:Example   -2087.50 EUR\n  Assets:Bank:Revolut:Checking  2087.50 EUR\n")
    assert payslips.book(PARSED, dry_run=True)["id"] == "a"


def test_parse_pdf_not_available_without_sample():
    with pytest.raises((FileNotFoundError, Exception)):
        payslips.parse("/nonexistent.pdf")
