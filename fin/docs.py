"""The documents folder (Syncthing `misc/finance`, in the restic backup): every finance file.

  inbox/                  drop folder; an agent (Claude/Hermes) files what lands here
  <YYYY>/<kind>/<name>    YYYY = the year the document belongs to, kind in KINDS
  permanent/              contracts, RETA, W-8BEN...

Ledger `document:` meta values are paths relative to this folder.
"""

import os
from pathlib import Path

from fin import config

DEFAULT = "docs"
KINDS = ("payslips", "invoices-issued", "receipts", "taxes", "statements")
PERMANENT = "permanent"


def root() -> Path:
    # A test FIN_ROOT never falls back to the real folder.
    default = "docs" if "FIN_ROOT" in os.environ else DEFAULT
    return config.path("docs_dir", default)


def path_for(kind: str, year: int | str | None, name: str) -> Path:
    if kind == PERMANENT:
        return root() / PERMANENT / name
    if kind not in KINDS:
        raise ValueError(f"unknown document kind: {kind}")
    return root() / str(year) / kind / name


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(root().resolve()))


def resolve(rel_path: str) -> Path:
    """Absolute path of a document, refusing anything outside the documents folder."""
    base = root().resolve()
    p = (base / rel_path).resolve()
    if base not in p.parents:
        raise ValueError(f"not a document: {rel_path}")
    return p


def put(data: bytes, kind: str, year: int | str | None, name: str) -> Path:
    """Write a document under its kind folder. The same bytes already at that name are reused;
    different bytes get a -2, -3... suffix."""
    target = path_for(kind, year, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    stem, ext, n = target.stem, target.suffix, 2
    while target.exists():
        if target.read_bytes() == data:
            return target
        target = target.with_name(f"{stem}-{n}{ext}")
        n += 1
    target.write_bytes(data)
    return target
