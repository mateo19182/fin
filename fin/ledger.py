"""Read, write and commit the beancount ledger. All writes go through here."""

import fcntl
import re
import subprocess
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from beancount import loader
from beancount.core import data, prices

from fin.config import ROOT, data_dir, ledger_file, section
from fin.models import Txn

ACCOUNT_WIDTH = 38
AMOUNT_WIDTH = 15
ID_KEYS = ("transaction_id", "external_id")


@dataclass
class Ledger:
    entries: list
    errors: list
    options: dict
    price_map: dict

    @property
    def transactions(self) -> list[data.Transaction]:
        return [e for e in self.entries if isinstance(e, data.Transaction)]

    def accounts(self) -> list[str]:
        closed = {e.account for e in self.entries if isinstance(e, data.Close)}
        return sorted(
            e.account for e in self.entries if isinstance(e, data.Open) and e.account not in closed
        )

    def external_ids(self) -> set[str]:
        return {str(t.meta[k]) for t in self.transactions for k in ID_KEYS if k in t.meta}

    def find(self, entry_id: str) -> data.Transaction | None:
        return next((t for t in self.transactions if txn_id(t) == entry_id), None)

    def to_eur(self, number: Decimal, currency: str, on: date | None = None) -> Decimal | None:
        if currency == "EUR":
            return number
        _, rate = prices.get_price(self.price_map, (currency, "EUR"), on)
        if rate is None:
            _, usd = prices.get_price(self.price_map, (currency, "USD"), on)
            _, eur_usd = prices.get_price(self.price_map, ("EUR", "USD"), on)
            if usd is None or not eur_usd:
                return None
            rate = usd / eur_usd
        return number * rate


def txn_id(t: data.Transaction) -> str:
    for k in ID_KEYS:
        if k in t.meta:
            return str(t.meta[k])
    return f"{relpath(t.meta['filename'])}:{t.meta['lineno']}"


def relpath(filename: str) -> str:
    return str(Path(filename).resolve().relative_to(ledger_file().parent))


_cache: tuple[tuple, Ledger] | None = None


def _signature() -> tuple:
    root = ledger_file().parent
    return tuple((str(p), p.stat().st_mtime_ns) for p in sorted(root.rglob("*.beancount")))


def load() -> Ledger:
    """Load the ledger, reusing the parsed result while no file has changed."""
    global _cache
    sig = _signature()
    if _cache and _cache[0] == sig:
        return _cache[1]
    entries, errors, options = loader.load_file(str(ledger_file()))
    ledger = Ledger(entries, errors, options, prices.build_price_map(entries))
    _cache = (sig, ledger)
    return ledger


@contextmanager
def write_lock():
    with open(data_dir() / "ledger.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _quote(s: str) -> str:
    s = " ".join(s.replace("\\", "").replace('"', "'").split())
    return '"' + s + '"'


def format_txn(t: Txn) -> str:
    lines = [f"{t.date.isoformat()} {t.flag} {_quote(t.payee)} {_quote(t.narration)}"]
    lines += [f"  {k}: {_quote(str(v))}" for k, v in t.meta.items()]
    for p in t.postings:
        if p.amount is None:
            lines.append(f"  {p.account}")
            continue
        line = f"  {p.account:<{ACCOUNT_WIDTH}}{p.amount:>{AMOUNT_WIDTH}} {p.currency}"
        if p.cost:
            line += f" {p.cost}"
        if p.price:
            line += f" {p.price}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def bank_file(on: date) -> Path:
    return ledger_file().parent / "transactions" / "banks" / f"{on:%Y-%m}.beancount"


def _check_unchanged_errors(before: int, restore: dict[Path, str | None]) -> None:
    after = load()
    if len(after.errors) > before:
        for p, text in restore.items():
            if text is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(text)
        msg = "; ".join(e.message for e in after.errors[before:])
        raise ValueError(f"ledger rejected the change: {msg}")


def append(txns: list[Txn], file: Path | None = None) -> None:
    """Append transactions (default: monthly bank file by date), validating the result."""
    if not txns:
        return
    with write_lock():
        before = len(load().errors)
        by_file: dict[Path, list[Txn]] = {}
        for t in txns:
            by_file.setdefault(file or bank_file(t.date), []).append(t)
        restore = {p: (p.read_text() if p.exists() else None) for p in by_file}
        for p, items in by_file.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            old = restore[p] or ""
            sep = ("" if not old or old.endswith("\n\n")
                   else "\n" if old.endswith("\n") else "\n\n")
            p.write_text(old + sep + "\n".join(format_txn(t) for t in items))
        _check_unchanged_errors(before, restore)


def append_safe(txns: list[Txn], file: Path | None = None) -> list[tuple[Txn, str]]:
    """Like append, but keeps the valid ones when the batch is rejected. Returns failures."""
    try:
        append(txns, file)
        return []
    except ValueError:
        pass
    failures = []
    for t in txns:
        try:
            append([t], file)
        except ValueError as e:
            failures.append((t, str(e)))
    return failures


def append_raw(file: Path, text: str) -> None:
    """Append raw directives (e.g. prices) to a ledger file, validating the result."""
    with write_lock():
        before = len(load().errors)
        old = file.read_text() if file.exists() else ""
        file.write_text(old.rstrip("\n") + "\n" + text.rstrip("\n") + "\n")
        _check_unchanged_errors(before, {file: old or None})


HEADER = re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<flag>[*!P&#?%txn]|txn)\s+'
                    r'(?P<payee>"(?:[^"\\]|\\.)*")\s*(?P<narration>"(?:[^"\\]|\\.)*")?(?P<rest>.*)$')
META_LINE = re.compile(r"^\s+([a-z][\w-]*):\s")


def edit_file(path: Path, fn: Callable[[str], str]) -> None:
    """Rewrite one ledger file through `fn`; new ledger errors roll the change back."""
    with write_lock():
        before = len(load().errors)
        old = path.read_text()
        new = fn(old)
        if new == old:
            return
        path.write_text(new)
        _check_unchanged_errors(before, {path: old})


def patch_txn(lines: list[str], lineno: int, payee: str | None = None,
              narration: str | None = None, meta: dict[str, str] | None = None) -> list[str]:
    """Pure text edit of the transaction whose header is at 1-based `lineno`.

    Meta keys are replaced in place or inserted after the existing meta lines."""
    i = lineno - 1
    m = HEADER.match(lines[i])
    if not m:
        raise ValueError(f"line {lineno} is not a transaction header: {lines[i]!r}")
    # A lone string after the flag is the narration, not the payee.
    old_payee, old_narr = (m["payee"], m["narration"]) if m["narration"] else (None, m["payee"])
    payee = _quote(payee) if payee is not None else old_payee
    narration = _quote(narration) if narration is not None else old_narr
    head = f"{m['date']} {m['flag']} " + " ".join(x for x in (payee, narration) if x)
    lines = [*lines[:i], head + m["rest"], *lines[i + 1:]]
    j = i + 1
    while j < len(lines) and (mm := META_LINE.match(lines[j])):
        key = mm.group(1)
        if meta and key in meta:
            lines[j] = f"  {key}: {_quote(str(meta.pop(key)))}"
        j += 1
    for k, v in (meta or {}).items():
        lines.insert(j, f"  {k}: {_quote(str(v))}")
        j += 1
    return lines


def update_txn(entry_id: str, payee: str | None = None, narration: str | None = None,
               meta: dict[str, str] | None = None) -> None:
    """Edit the header text and/or string metadata of one existing transaction."""
    t = load().find(entry_id)
    if t is None:
        raise KeyError(entry_id)
    path = Path(t.meta["filename"])
    edit_file(path, lambda text: "\n".join(
        patch_txn(text.split("\n"), t.meta["lineno"], payee, narration, dict(meta or {}))))


def settle(entry_ids: list[str]) -> int:
    """Flip `!` (imported while the bank still had it pending) to `*`. Returns the count."""
    lg = load()
    by_file: dict[Path, list[int]] = {}
    for eid in entry_ids:
        t = lg.find(eid)
        if t is not None and t.flag == "!":
            by_file.setdefault(Path(t.meta["filename"]), []).append(t.meta["lineno"])

    def flip(linenos):
        def fn(text):
            lines = text.split("\n")
            for n in linenos:
                lines[n - 1] = lines[n - 1].replace(" ! ", " * ", 1)
            return "\n".join(lines)
        return fn

    for path, linenos in by_file.items():
        edit_file(path, flip(linenos))
    return sum(map(len, by_file.values()))


def set_account(entry_id: str, old: str, new: str) -> None:
    """Re-point one posting of an existing transaction to another account."""
    with write_lock():
        ledger = load()
        t = ledger.find(entry_id)
        if t is None:
            raise KeyError(entry_id)
        path = Path(t.meta["filename"])
        text = path.read_text()
        lines = text.split("\n")
        i = t.meta["lineno"]  # 1-based header line; postings follow
        while i < len(lines) and lines[i].strip():
            parts = lines[i].split()
            if parts and parts[0] == old:
                rest = parts[1:]
                lines[i] = (f"  {new:<{ACCOUNT_WIDTH}}{rest[0]:>{AMOUNT_WIDTH}} "
                            + " ".join(rest[1:]) if rest else f"  {new}")
                break
            i += 1
        else:
            raise ValueError(f"{old} not found in {entry_id}")
        before = len(ledger.errors)
        path.write_text("\n".join(lines))
        _check_unchanged_errors(before, {path: text})


def ensure_open(account: str, currencies: str = "") -> None:
    """Open an account if the ledger does not have it yet."""
    if account in load().accounts():
        return
    f = ledger_file().parent / "accounts" / "accounts.beancount"
    with write_lock():
        old = f.read_text()
        f.write_text(old.rstrip() + f"\n\n2020-01-01 open {account} {currencies}".rstrip() + "\n")


def commit(message: str) -> bool:
    """Commit ledger changes to git. Returns False when there was nothing to commit."""
    if not section("git").get("enabled", False):
        return False
    ledger_dir = str(ledger_file().parent)
    if subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT, capture_output=True).returncode:
        return False  # not a git checkout (e.g. a temp FIN_ROOT)
    subprocess.run(["git", "add", "-A", ledger_dir], cwd=ROOT, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode == 0:
        return False
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=ROOT, check=True)
    # Off-site backup; a failed push is retried implicitly by the next commit's push.
    subprocess.Popen(["git", "push", "-q"], cwd=ROOT, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return True
