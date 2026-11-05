"""Autónomo invoices (facturas emitidas) -> activity booking.

Each invoice is one transaction at its issue date (devengo), paid later by the bank deposit:
  Income:Activity:<Client>       -base        rendimiento de actividad económica
  Liabilities:Hacienda:IVA       -iva         IVA repercutido, cleared by the quarterly 303
  Assets:Hacienda:Retenciones    +retención   IRPF withheld by the client (pago a cuenta)
  Assets:Receivable:<Client>     +total
The deposit (previously Income:Salary:<Client>) is re-pointed to the receivable.
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fin import docs, ledger
from fin.models import Posting, Txn
from fin.renta import pdf

INCOME = "Income:Activity"
IVA = "Liabilities:Hacienda:IVA"
RETENCIONES = "Assets:Hacienda:Retenciones"
PAGOS_FRACCIONADOS = "Assets:Hacienda:PagosFraccionados"
RECEIVABLE = "Assets:Receivable"
SOURCE = "invoice_pdf"
CLIENTS = {"DEMO": "Demo", "EXAMPLE": "Example"}  # substring of the client name -> ledger name
RECEIPT_ACCOUNTS = ("Income:Salary:{client}", "Income:Salary:Autonomo")
MATCH_DAYS = 120
CENT = Decimal("0.01")

NUMBER = re.compile(r"FACTURA\s+([A-Z]+/\d+)")
DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
CLIENT = re.compile(r"^\s{40,}([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 ,.&-]*?\b(?:S\.?L\.?U?\.?|S\.?A\.?))\s*$",
                    re.M)
NIF = re.compile(r"\bNIF\s+([A-Z]\d{7}[A-Z0-9])")


LEGAL_FORM = re.compile(r",?\s*(S\.?L\.?U?\.?|S\.?A\.?)\s*$", re.I)


def client_name(raw: str) -> str:
    up = raw.upper()
    return next((v for k, v in CLIENTS.items() if k in up), raw.split()[0].title())


def payee(raw: str) -> str:
    return LEGAL_FORM.sub("", raw).strip().title()


def parse_text(text: str) -> dict:
    nm = NUMBER.search(text)
    if not nm:
        raise ValueError("invoice number not found")
    dm = DATE.search(text, nm.end())
    cm, im = CLIENT.search(text), NIF.search(text)
    if not (dm and cm and im):
        raise ValueError("invoice date/client/NIF not found")
    lines = text.split("\n")
    i = next(k for k, line in enumerate(lines) if "Importes" in line)
    tokens: list[str] = []
    for line in lines[i + 1:i + 6]:
        tokens += re.findall(r"[\d.,]+\s*%|[\d.,]+\d\s*€?", line)
    if len(tokens) < 5:
        raise ValueError(f"invoice totals not found: {tokens}")
    pct = [k for k, tok in enumerate(tokens) if "%" in tok]
    base, iva = tokens[1], tokens[3]
    if pct and pct[0] == 4:  # retención present: "7%" then its amount, then the total
        ret_rate, ret, total = tokens[4], tokens[5], tokens[6]
    else:
        ret_rate, ret, total = "0%", "0", tokens[4]
    k = next(k for k, line in enumerate(lines) if "Descripción" in line)
    desc = next(line for line in lines[k + 1:] if line.strip())
    out = {"number": nm[1], "date": date(int(dm[3]), int(dm[2]), int(dm[1])),
           "client_raw": cm[1].strip(), "client": client_name(cm[1]), "client_nif": im[1],
           "base": _n(base), "iva_rate": _n(tokens[2]) / 100, "iva": _n(iva),
           "ret_rate": _n(ret_rate) / 100, "ret": _n(ret), "total": _n(total),
           "description": re.split(r"\s{2,}", desc.strip())[0]}
    diff = out["total"] - (out["base"] + out["iva"] - out["ret"])
    if abs(diff) > CENT:
        raise ValueError(f"invoice does not add up: {out}")
    out["iva"] += diff  # the PDF prints the IVA with one decimal; the total carries the cent
    return out


def _n(tok: str) -> Decimal:
    return pdf.num_es(tok.rstrip("€% ")).quantize(CENT)


def parse(pdf_path: str | Path) -> dict:
    return parse_text(pdf.text(pdf_path))


def external_id(parsed: dict) -> str:
    return f"inv:{parsed['date']:%Y}:{parsed['number']}"


def to_txn(parsed: dict) -> Txn:
    c = parsed["client"]
    postings = [Posting(f"{INCOME}:{c}", -parsed["base"]), Posting(IVA, -parsed["iva"])]
    if parsed["ret"]:
        postings.append(Posting(RETENCIONES, parsed["ret"]))
    postings.append(Posting(f"{RECEIVABLE}:{c}", parsed["total"]))
    return Txn(parsed["date"], payee(parsed["client_raw"]),
               f"Factura {parsed['number']}: {parsed['description']}"[:120], postings,
               {"external_id": external_id(parsed), "source": SOURCE,
                "invoice": parsed["number"], "client_nif": parsed["client_nif"]})


def find_receipt(lg: ledger.Ledger, parsed: dict):
    """(deposit transaction, its income posting account) still booked as plain income."""
    accounts = {a.format(client=parsed["client"]) for a in RECEIPT_ACCOUNTS}
    until = parsed["date"] + timedelta(days=MATCH_DAYS)
    for t in sorted(lg.transactions, key=lambda t: t.date):
        if not parsed["date"] <= t.date <= until:
            continue
        for p in t.postings:
            if p.account in accounts and abs(-p.units.number - parsed["total"]) <= CENT:
                return t, p.account
    return None, None


def receipt_expected(lg: ledger.Ledger, account: str, amount: Decimal) -> bool:
    """False when `account` is a client receivable with no booked invoice covering `amount`."""
    if not account.startswith(RECEIVABLE + ":"):
        return True
    open_ = sum((p.units.number for t in lg.transactions for p in t.postings
                 if p.account == account), Decimal(0))
    return open_ >= amount - CENT


def accounts_for(client: str) -> list[tuple[str, str]]:
    return [(f"{INCOME}:{client}", "EUR"), (IVA, "EUR"), (RETENCIONES, "EUR"),
            (f"{RECEIVABLE}:{client}", "EUR")]


def book(parsed: dict, dry_run: bool = False) -> dict:
    """Book the invoice and re-point its deposit (if already in the ledger) to the receivable."""
    lg = ledger.load()
    t = to_txn(parsed)
    out = {"id": t.meta["external_id"], "client": parsed["client"], "total": str(parsed["total"]),
           "preview": ledger.format_txn(t), "already_booked": t.meta["external_id"] in
           lg.external_ids(), "receipt": None}
    deposit, from_account = find_receipt(lg, parsed)
    if deposit is not None:
        out["receipt"] = {"id": ledger.txn_id(deposit), "date": deposit.date.isoformat(),
                          "from": from_account, "to": f"{RECEIVABLE}:{parsed['client']}"}
    if dry_run:
        return out
    for acct, cur in accounts_for(parsed["client"]):
        ledger.ensure_open(acct, cur)
    if not out["already_booked"]:
        ledger.append([t])
    if deposit is not None:
        ledger.set_account(out["receipt"]["id"], from_account, out["receipt"]["to"])
    ledger.commit(f"invoice: {parsed['client']} {parsed['number']}")
    return out


def archive(pdf_path: str | Path, parsed: dict) -> Path:
    """File the PDF as <year>/invoices-issued/YYYY-MM_<number>_<client>.pdf."""
    d = parsed["date"]
    name = f"{d:%Y-%m}_{parsed['number'].replace('/', '-')}_{parsed['client'].lower()}.pdf"
    return docs.put(Path(pdf_path).read_bytes(), "invoices-issued", d.year, name)
