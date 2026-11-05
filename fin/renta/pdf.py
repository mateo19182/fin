"""Shared helpers for the PDF parsers (payslips, invoices, Revolut P&L)."""

import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path

MONTHS_ES = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
     "octubre", "noviembre", "diciembre"])}


def text(path: str | Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True,
                          capture_output=True, text=True).stdout


def num_es(s: str) -> Decimal:
    """'6.274,33' -> Decimal('6274.33'); '1.317,6' -> 1317.6."""
    s = s.strip().replace("€", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"not a number: {s!r}") from e


NUM_ES = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{1,2}|-?\d+,\d{1,2}|-?\d+")


def numbers(line: str) -> list[Decimal]:
    return [num_es(m) for m in NUM_ES.findall(line)]
