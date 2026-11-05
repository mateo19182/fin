"""Rewrite the postings/meta of one existing ledger transaction (text edit, validated)."""

from pathlib import Path

from beancount.core import data

from fin import ledger
from fin.models import Posting, Txn


def block_end(lines: list[str], lineno: int) -> int:
    """Index one past the last line of the transaction whose header is at 1-based `lineno`."""
    j = lineno
    while j < len(lines) and lines[j].strip() and lines[j][0] in " \t":
        j += 1
    return j


def replace_block(text: str, lineno: int, txn: Txn) -> str:
    lines = text.split("\n")
    end = block_end(lines, lineno)
    new = ledger.format_txn(txn).rstrip("\n").split("\n")
    return "\n".join([*lines[: lineno - 1], *new, *lines[end:]])


def as_txn(t: data.Transaction, postings: list[Posting], meta: dict[str, str | None]) -> Txn:
    """`t` with new postings; meta merged (a None value deletes the key; order kept)."""
    skip = ("filename", "lineno", "__tolerances__")
    keep = {k: str(v) for k, v in t.meta.items() if k not in skip}
    for k, v in meta.items():
        if v is None:
            keep.pop(k, None)
        else:
            keep[k] = str(v)
    return Txn(t.date, t.payee or "", t.narration or "", postings, keep, t.flag)


def rewrite(t: data.Transaction, postings: list[Posting], meta: dict | None = None) -> None:
    """Replace the postings of `t` in its file; new ledger errors roll the change back."""
    txn = as_txn(t, postings, meta or {})
    path = Path(t.meta["filename"])
    ledger.edit_file(path, lambda text: replace_block(text, t.meta["lineno"], txn))


def preview(t: data.Transaction, postings: list[Posting], meta: dict | None = None) -> str:
    return ledger.format_txn(as_txn(t, postings, meta or {}))
