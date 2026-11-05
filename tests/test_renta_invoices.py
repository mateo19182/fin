# ruff: noqa: E501  (pdftotext -layout fixtures keep their column widths)
from datetime import date
from decimal import Decimal as D

import pytest

from fin import ledger
from fin.renta import invoices

# Layout of the real invoices (pdftotext -layout), names and amounts changed.
INVOICE = """
                                                                     FACTURA A/13
                                                                     18/08/2026



                                                                          DEMO SOLUTIONS AMX, S.L.
   PEREZ, JUAN                                                            NIF B00000000
   CIF 00000000T                                                          CL. FALSA, 1
   AV. Falsa, 1                                                           28000 MADRID

                                                                                                  Pág.     1

                                                Descripción                 Cantidad     Precio      Importe


Servicios profesionales de desarrollo de software                                 1,00   6.274,33     6.274,33
en calidad de socio y gestor de la sociedad mercantil.




     Suma            Pronto Pago                 Base                 I.V.A.          Rec. Equiv.       Retención
    Importes         %Dto. Imp.                Imponible          %IVA Cuota         %R.E. Cuota          IRPF        Total Factura
   6.274,33                                   6.274,33            21       1.317,6                           7%
                                                                                                           439,20
                                                                                                                       7.152,74 €

       CONDICIONES DE PAGO
"""


def test_parse_text():
    p = invoices.parse_text(INVOICE)
    assert p["number"] == "A/13" and p["date"] == date(2026, 8, 18)
    assert p["client"] == "Demo" and p["client_raw"] == "DEMO SOLUTIONS AMX, S.L."
    assert p["client_nif"] == "B00000000"
    # the PDF prints 1.317,6 but the total carries the exact cent: 6.274,33 x 21% = 1.317,61
    assert p["base"] == D("6274.33") and p["iva"] == D("1317.61") and p["ret"] == D("439.20")
    assert p["iva_rate"] == D("0.21") and p["ret_rate"] == D("0.07")
    assert p["total"] == D("7152.74")
    assert p["description"] == "Servicios profesionales de desarrollo de software"


def test_parse_without_retencion():
    text = INVOICE.replace("7%\n", "\n").replace("439,20", "").replace("7.152,74", "7.591,93")
    p = invoices.parse_text(text)
    assert p["ret"] == 0 and p["total"] == D("7591.93")


def test_parse_rejects_inconsistent_totals():
    with pytest.raises(ValueError, match="does not add up"):
        invoices.parse_text(INVOICE.replace("7.152,74", "7.152,75"))


def test_to_txn_shape():
    t = invoices.to_txn(invoices.parse_text(INVOICE))
    assert t.date == date(2026, 8, 18) and t.meta["external_id"] == "inv:2026:A/13"
    assert t.payee == "Demo Solutions Amx" and invoices.payee("EXAMPLE INTELLIGENCE, SLU") == "Example Intelligence"
    assert [(p.account, p.amount) for p in t.postings] == [
        ("Income:Activity:Demo", D("-6274.33")), ("Liabilities:Hacienda:IVA", D("-1317.61")),
        ("Assets:Hacienda:Retenciones", D("439.20")), ("Assets:Receivable:Demo", D("7152.74"))]


def deposit(day="2026-08-20", amount="7152.74", account="Income:Salary:Demo", tid="dep-1"):
    f = ledger.ledger_file().parent / "transactions" / "banks" / f"{day[:7]}.beancount"
    old = f.read_text() if f.exists() else ""
    f.write_text(old + f'\n{day} * "Demo Solutions Amx" "00005 DEMO"\n  transaction_id: "{tid}"\n'
                 f"  {account}   -{amount} EUR\n  Assets:Bank:Revolut:Checking  {amount} EUR\n")


def open_accounts():
    acc = ledger.ledger_file().parent / "accounts" / "accounts.beancount"
    acc.write_text(acc.read_text() + "\n2024-01-01 open Income:Salary:Demo EUR\n"
                   "2024-01-01 open Income:Salary:Autonomo EUR\n")


def test_book_and_repoint_receipt(root):
    open_accounts()
    deposit()
    parsed = invoices.parse_text(INVOICE)
    dry = invoices.book(parsed, dry_run=True)
    assert dry["receipt"]["id"] == "dep-1" and not dry["already_booked"]
    assert ledger.load().find("inv:2026:A/13") is None

    invoices.book(parsed)
    lg = ledger.load()
    assert not lg.errors
    inv = lg.find("inv:2026:A/13")
    assert inv.date == date(2026, 8, 18) and inv.meta["invoice"] == "A/13"
    dep = lg.find("dep-1")
    assert {p.account for p in dep.postings} == {"Assets:Receivable:Demo",
                                                 "Assets:Bank:Revolut:Checking"}
    assert invoices.receipt_expected(lg, "Assets:Receivable:Demo", D("1")) is False  # all paid
    again = invoices.book(parsed)
    assert again["already_booked"] and again["receipt"] is None


def test_book_without_receipt_then_receipt_expected(root):
    open_accounts()
    parsed = invoices.parse_text(INVOICE)
    r = invoices.book(parsed)
    assert r["receipt"] is None
    lg = ledger.load()
    assert invoices.receipt_expected(lg, "Assets:Receivable:Demo", D("7152.74"))
    assert not invoices.receipt_expected(lg, "Assets:Receivable:Demo", D("7200"))
    assert invoices.receipt_expected(lg, "Expenses:Food:Groceries", D("1"))
    # a deposit matched later through Income:Salary:Autonomo
    deposit(account="Income:Salary:Autonomo", tid="dep-2")
    r = invoices.book(parsed)
    assert r["already_booked"] and r["receipt"]["id"] == "dep-2"
    assert not ledger.load().errors


def test_receipt_outside_window_is_not_matched(root):
    open_accounts()
    deposit(day="2026-12-31")
    assert invoices.book(invoices.parse_text(INVOICE), dry_run=True)["receipt"] is None
