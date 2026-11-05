"""Payslip PDF -> gross salary booking.

Target shape (replaces the net bank deposit, which keeps its bank leg and ids):
  Income:Salary:<Employer>              -gross
  Expenses:Taxes:IRPF:Withheld          +irpf
  Expenses:Taxes:SocialSecurity:Employee +ss
  Expenses:EatingOut                    +other   (in-kind: Cobee meal card, tax-exempt)
  Assets:Bank:...                       +net
Meta: payslip (YYYY-MM), irpf_base (base sujeta a retención, differs from gross when part of
the pay is exempt in kind), irpf_rate.
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fin import docs, ledger
from fin.models import Posting
from fin.renta import interest, pdf, rewrite

SS_EMPLOYEE = "Expenses:Taxes:SocialSecurity:Employee"
DEDUCTIONS = "Expenses:EatingOut"  # in-kind = Cobee meal card, spent outside the bank
EMPLOYERS = {"EXAMPLE": "Example"}  # substring of the payslip employer name -> ledger name
MATCH_DAYS_AFTER = 15  # the net is usually paid in the first days of the next month
CENT = Decimal("0.01")

PERIOD = re.compile(r"(\d{1,2}) (\w+) (\d{4}) a (\d{1,2}) (\w+) (\d{4})")
COTIZACION = re.compile(r"Cotizaci[óo]n .*?\([\d,]+%\)\s+([\d.,]+)\s*$", re.M)
IRPF = re.compile(r"Tributaci[óo]n IRPF \(([\d,]+)%\)\s+([\d.,]+)\s*$", re.M)


def employer_name(raw: str) -> str:
    up = raw.upper()
    return next((v for k, v in EMPLOYERS.items() if k in up), raw.split()[0].title())


def parse_text(text: str) -> dict:
    lines = text.split("\n")

    def after(header: str) -> int:
        return next(i for i, line in enumerate(lines) if header in line)

    i = after("EMPRESA")
    raw_employer = next(line for line in lines[i + 1:] if line.strip())
    raw_employer = re.split(r"\s{2,}", raw_employer.strip())[0]
    m = PERIOD.search(text)
    if not m:
        raise ValueError("payslip period not found")
    start = date(int(m[3]), pdf.MONTHS_ES[m[2].lower()], int(m[1]))
    end = date(int(m[6]), pdf.MONTHS_ES[m[5].lower()], int(m[4]))
    ss = sum((pdf.num_es(x) for x in COTIZACION.findall(text)), Decimal(0))
    im = IRPF.search(text)
    if not im:
        raise ValueError("IRPF line not found")
    irpf_rate, irpf = pdf.num_es(im[1]) / 100, pdf.num_es(im[2])
    i = after("T. DEVENGADO")
    totals = next(pdf.numbers(line) for line in lines[i + 1:] if pdf.numbers(line))
    gross, deductions, irpf_base = totals[-2], totals[-1], totals[-3]
    i = after("Líquido a Percibir")
    net = next(pdf.numbers(line)[0] for line in lines[i + 1:] if pdf.numbers(line))
    if gross - deductions != net:
        raise ValueError(f"payslip does not add up: {gross} - {deductions} != {net}")
    return {"employer": employer_name(raw_employer), "employer_raw": raw_employer,
            "month": f"{end:%Y-%m}", "period_start": start, "period_end": end,
            "gross": gross, "irpf": irpf, "ss": ss, "net": net,
            "other": deductions - irpf - ss, "irpf_base": irpf_base, "irpf_rate": irpf_rate}


def parse(pdf_path: str | Path) -> dict:
    return parse_text(pdf.text(pdf_path))


def find_deposit(lg: ledger.Ledger, parsed: dict):
    """The net salary deposit this payslip explains, or None."""
    account = f"Income:Salary:{parsed['employer']}"
    y, m = (int(x) for x in parsed["month"].split("-"))
    start = date(y, m, 1)
    end = date(y + m // 12, m % 12 + 1, 1) + timedelta(days=MATCH_DAYS_AFTER)
    hits = [t for t in lg.transactions if start <= t.date <= end and "payslip" not in t.meta
            and any(p.account == account and abs(-p.units.number - parsed["net"]) <= CENT
                    for p in t.postings)]
    if len(hits) > 1:
        tag = f"NOMINA {m:02d}/{y}"
        hits = [t for t in hits if tag in (t.narration or "")] or hits
    if len(hits) > 1:
        raise ValueError(f"{len(hits)} deposits match {parsed['employer']} {parsed['month']} "
                         f"{parsed['net']}; book by hand")
    return hits[0] if hits else None


def postings(parsed: dict, t) -> list[Posting]:
    account = f"Income:Salary:{parsed['employer']}"
    out = [Posting(account, -parsed["gross"]), Posting(interest.WITHHELD, parsed["irpf"]),
           Posting(SS_EMPLOYEE, parsed["ss"])]
    if parsed["other"]:
        out.append(Posting(DEDUCTIONS, parsed["other"]))
    out += [Posting(p.account, p.units.number, p.units.currency)
            for p in t.postings if p.account != account]
    return out


def meta(parsed: dict) -> dict[str, str]:
    return {"payslip": parsed["month"], "irpf_base": str(parsed["irpf_base"]),
            "irpf_rate": str(parsed["irpf_rate"])}


def book(parsed: dict, dry_run: bool = False) -> dict:
    """Rewrite the matching net deposit into the gross shape. Raises if none matches."""
    lg = ledger.load()
    t = find_deposit(lg, parsed)
    if t is None:
        raise ValueError(f"no {parsed['employer']} deposit of {parsed['net']} EUR found for "
                         f"{parsed['month']} (import the bank transactions first)")
    new = postings(parsed, t)
    out = {"id": ledger.txn_id(t), "date": t.date.isoformat(), "employer": parsed["employer"],
           "month": parsed["month"], "gross": str(parsed["gross"]), "net": str(parsed["net"]),
           "before": ledger.format_txn(rewrite.as_txn(t, [
               Posting(p.account, p.units.number, p.units.currency) for p in t.postings], {})),
           "after": rewrite.preview(t, new, meta(parsed))}
    if dry_run:
        return out
    for acct in (interest.WITHHELD, SS_EMPLOYEE, DEDUCTIONS):
        ledger.ensure_open(acct, "EUR")
    rewrite.rewrite(t, new, meta(parsed))
    return out


def archive(pdf_path: str | Path, parsed: dict) -> Path:
    """File the PDF as <year>/payslips/YYYY-MM_<employer>.pdf in the documents folder."""
    name = f"{parsed['month']}_{parsed['employer'].lower()}.pdf"
    return docs.put(Path(pdf_path).read_bytes(), "payslips", parsed["month"][:4], name)
