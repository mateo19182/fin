"""One transaction in full, by entry id (see ledger.txn_id): read, edit text/note, attach a file."""

import re
from pathlib import Path

from fin import activity, docs, ledger

HIDDEN_META = {"filename", "lineno", "__tolerances__", "__automatic__"}


def _find(entry_id: str):
    t = ledger.load().find(entry_id)
    if t is None:
        raise KeyError(entry_id)
    return t


def get(entry_id: str) -> dict:
    t = _find(entry_id)
    return {
        "id": ledger.txn_id(t),
        "date": t.date.isoformat(),
        "flag": t.flag,
        "payee": t.payee,
        "narration": t.narration,
        "tags": sorted(t.tags or []),
        "links": sorted(t.links or []),
        "postings": [{
            "account": p.account,
            "amount": str(p.units.number) if p.units and p.units.number is not None else None,
            "currency": p.units.currency if p.units else None,
            "cost": str(p.cost) if p.cost else None,
            "price": str(p.price) if p.price else None,
        } for p in t.postings],
        "meta": {k: str(v) for k, v in t.meta.items() if k not in HIDDEN_META},
        "documents": [str(v) for k, v in t.meta.items() if k.startswith("document")],
        "file": f"{ledger.relpath(t.meta['filename'])}:{t.meta['lineno']}",
        "deductible": activity.deductible(t).as_dict(),
    }


def update(entry_id: str, payee: str | None = None, narration: str | None = None,
           note: str | None = None) -> dict:
    """Change the payee and/or narration; `note` is stored as meta `note`."""
    t = _find(entry_id)
    meta = {"note": note} if note is not None else None
    ledger.update_txn(entry_id, payee, narration, meta)
    ledger.commit(f"edit: {t.date} {payee or t.payee}")
    return get(entry_id)


def slug(name: str) -> str:
    s = re.sub(r"[^\w-]+", "-", name.casefold()).strip("-")
    return s[:60] or "file"


def attach(entry_id: str, filename: str, data: bytes) -> dict:
    """File a receipt as <year>/receipts/<date>_<payee>.<ext> in the documents folder and
    reference it from the transaction's `document` meta."""
    t = _find(entry_id)
    ext = re.sub(r"[^.\w]", "", Path(filename).suffix.casefold()[:10])
    path = docs.put(data, "receipts", t.date.year,
                    f"{t.date}_{slug(t.payee or Path(filename).stem)}{ext}")
    rel = docs.rel(path)
    docs_meta = {str(v) for k, v in t.meta.items() if k.startswith("document")}
    if rel not in docs_meta:
        key, n = "document", 2
        while key in t.meta:
            key, n = f"document_{n}", n + 1
        ledger.update_txn(entry_id, meta={key: rel})
        ledger.commit(f"attach: {t.date} {t.payee} {path.name}")
    return get(entry_id)


def document_path(rel: str) -> Path:
    """Absolute path of a `document` meta value, refusing anything outside the documents folder."""
    return docs.resolve(rel)
