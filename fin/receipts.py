"""Receipts (facturas de gastos): match a file to the bank transaction it explains and attach it.

A PDF is read with pdftotext; every date and every "total"-looking amount in it is a candidate.
Images only match when the file name carries a date and an amount (2026-03-25-uber-24.73.jpg).
A transaction matches when it is a bank expense within ±MATCH_DAYS of a receipt date whose EUR
amount is within ±MATCH_EUR, or whose USD total converts at the ledger EUR/USD price within
±USD_TOLERANCE. When the receipt never names the payee, only an exact main total on the same
or the next day counts (a 20 € Bizum must not swallow a 20 € train ticket). One candidate (or
a unique closest one) wins; otherwise the file is kept as <year>/receipts/unmatched-* in the
documents folder and reported.
"""

import hashlib
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from beancount.core import prices

from fin import activity, details, docs, ledger
from fin.renta import pdf

MATCH_DAYS = 5
MATCH_EUR = Decimal("0.05")
STRICT_DAYS = 1  # when the receipt text does not name the payee
STRICT_EUR = Decimal("0.01")
USD_TOLERANCE = Decimal("0.05")
OLDEST = date(2020, 1, 1)  # older dates in a receipt are boilerplate ("IVA desde 01.09.2012")
PDF_EXT = {".pdf"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTHS.update({m[:3]: i for m, i in pdf.MONTHS_ES.items()})
MONTHS["sept"] = 9
TOTAL_WORDS = re.compile(r"total|amount (?:paid|due)|importe|grand total|a pagar", re.I)
PAID_WORDS = re.compile(r"a pagar|amount (?:paid|due)|importe total|total factura|grand total",
                        re.I)
AMOUNT = re.compile(r"(?P<cur>[€$]|EUR|USD)?\s*"
                    r"(?P<num>-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|-?\d+[.,]\d{2})"
                    r"\s*(?P<cur2>€|EUR|USD)?")
DATES = [
    re.compile(r"\b(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{4})\b"),
    re.compile(r"\b(?P<y>\d{4})[/-](?P<m>\d{1,2})[/-](?P<d>\d{1,2})\b"),
    re.compile(r"\b(?P<mon>[A-Za-z]{3,10})\.? (?P<d>\d{1,2}), (?P<y>\d{4})\b"),
    re.compile(r"\b(?P<d>\d{1,2})\.? (?:de )?(?P<mon>[A-Za-zñ]{3,10}) (?:de )?(?P<y>\d{4})\b",
               re.I),
]


def _month(s: str) -> int | None:
    return MONTHS.get(s.lower()[:4]) or MONTHS.get(s.lower()[:3])


def dates_in(text: str) -> list[date]:
    out: set[date] = set()
    for rx in DATES:
        for m in rx.finditer(text):
            g = m.groupdict()
            month = int(g["m"]) if g.get("m") else _month(g["mon"])
            try:
                if month:
                    out.add(date(int(g["y"]), month, int(g["d"])))
            except ValueError:
                continue
    return sorted(out)


def _num(s: str) -> Decimal | None:
    s = s.replace(" ", "")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return abs(Decimal(s))
    except InvalidOperation:
        return None


def amounts_in(text: str) -> list[tuple[Decimal, str]]:
    """Amounts the bank charge can equal: the largest total per currency plus every amount on
    a "paid / a pagar / total factura" line. Unmarked numbers are EUR, and also USD when the
    document mentions USD (two-currency statements)."""
    usd_doc = "USD" in text or "$" in text
    totals: list[tuple[Decimal, str]] = []
    paid: list[tuple[Decimal, str]] = []
    for line in text.split("\n"):
        if not TOTAL_WORDS.search(line):
            continue
        for m in AMOUNT.finditer(line):
            v = _num(m["num"])
            if v is None or v == 0:
                continue
            marks = (m["cur"] or "") + (m["cur2"] or "")
            curs = ["USD"] if "$" in marks or "USD" in marks else \
                ["EUR"] if marks else (["EUR", "USD"] if usd_doc else ["EUR"])
            for cur in curs:
                totals.append((v, cur))
                if PAID_WORDS.search(line):
                    paid.append((v, cur))
    out = []  # the largest total per currency comes first: it is the "primary" amount
    for cur in ("EUR", "USD"):
        vals = [v for v, c in totals if c == cur]
        if vals:
            out.append((max(vals), cur))
    out += [x for x in paid if x not in out]
    return out


def parse_filename(name: str) -> tuple[list[date], list[tuple[Decimal, str]]]:
    stem = Path(name).stem
    ds = dates_in(stem.replace("_", "-"))
    amts = [(Decimal(m), "EUR") for m in re.findall(r"(?<!\d)(\d+[.,]\d{2})(?!\d)", stem)]
    return ds, [(_num(str(a)), c) for a, c in amts]


def parse(path: Path) -> dict:
    ext = path.suffix.lower()
    text = pdf.text(path) if ext in PDF_EXT else ""
    read = _read_llm(path)
    if read:  # one date, one total: no guessing among every number on the page
        return {"file": str(path), "dates": [read.date],
                "amounts": [(read.total, read.currency.upper())], "vat": read.vat,
                "text": f"{read.supplier}\n{text}"}
    ds, amts = dates_in(text), amounts_in(text)
    if not (ds and amts):  # scanned PDF or image: fall back to the file name
        fds, famts = parse_filename(path.name)
        ds, amts = ds or fds, amts or famts
    return {"file": str(path), "dates": ds, "amounts": amts, "text": text}


def _read_llm(path: Path):
    from fin import llm

    if not llm.enabled():
        return None
    try:
        r = llm.read_receipt(path)
    except Exception:  # API down or unreadable file: the text matching still runs
        return None
    return r if r and r.total > 0 else None


def doc_date(parsed: dict) -> date | None:
    """The receipt's own date: the one in the file name, else the earliest plausible one."""
    named = [d for d in parse_filename(Path(parsed["file"]).name)[0] if OLDEST <= d]
    ok = named or [d for d in parsed["dates"] if OLDEST <= d <= date.today()]
    return ok[0] if ok else None


def _usd_rate(lg: ledger.Ledger, on: date) -> Decimal | None:
    _, r = prices.get_price(lg.price_map, ("EUR", "USD"), on)
    return r


def _bank_expense(t, lg: ledger.Ledger) -> Decimal | None:
    """Positive EUR amount of a bank-paid expense, else None."""
    if not any(p.account.startswith(("Assets:Bank:", "Assets:Cash:")) for p in t.postings):
        return None
    v = activity.expense_amount(t, lg)
    return v if v > 0 else None


def _payee_hit(t, text: str) -> bool:
    words = [w for w in re.findall(r"[a-zñ]{4,}", (t.payee or "").lower())
             if w not in ("pending", "trip", "payment")]
    return any(w in text for w in words)


def candidates(parsed: dict, lg: ledger.Ledger) -> list[dict]:
    """Bank expenses matching a receipt date and amount; `hit` = the payee appears in the text."""
    hits = []
    t_by_id = {}
    text = parsed.get("text", "").lower()
    for t in lg.transactions:
        amt = _bank_expense(t, lg)
        if amt is None:
            continue
        hit = _payee_hit(t, text)
        t_by_id[ledger.txn_id(t)] = t
        primary = {cur: v for v, cur in reversed(parsed["amounts"])}
        for d in parsed["dates"]:
            gap = abs((t.date - d).days)
            if gap > MATCH_DAYS:
                continue
            for v, cur in parsed["amounts"]:
                if not hit and (primary.get(cur) != v or gap > STRICT_DAYS or cur != "EUR"
                                or abs(v - amt) > STRICT_EUR):
                    continue
                if cur == "EUR" and abs(v - amt) <= MATCH_EUR:
                    hits.append({"id": ledger.txn_id(t), "gap": gap, "how": "eur", "hit": hit})
                elif cur == "USD" and (rate := _usd_rate(lg, t.date)) \
                        and abs(v / rate - amt) <= amt * USD_TOLERANCE:
                    hits.append({"id": ledger.txn_id(t), "gap": gap, "how": "usd", "hit": hit})
    best: dict[str, dict] = {}
    for h in hits:
        if h["id"] not in best or h["gap"] < best[h["id"]]["gap"]:
            best[h["id"]] = {**h, "date": t_by_id[h["id"]].date.isoformat(),
                             "payee": t_by_id[h["id"]].payee,
                             "amount": str(_bank_expense(t_by_id[h["id"]], lg))}
    return sorted(best.values(), key=_rank)


def _rank(h: dict) -> tuple:
    return (not h["hit"], h["gap"], h["how"])


def pick(cands: list[dict]) -> dict | None:
    """The best candidate when it is strictly better than the runner-up."""
    if not cands:
        return None
    if len(cands) == 1 or _rank(cands[0])[:2] < _rank(cands[1])[:2]:
        return cands[0]
    return None


def _already_attached(t, data: bytes) -> bool:
    digest = hashlib.sha256(data).digest()
    for k, v in t.meta.items():
        if k == "document" or k.startswith("document_"):
            try:
                p = docs.resolve(str(v))
            except ValueError:
                continue
            if p.exists() and hashlib.sha256(p.read_bytes()).digest() == digest:
                return True
    return False


def attach(path: Path, entry_id: str, data: bytes | None = None) -> dict:
    """Attach the file and, when the payee rule makes it deductible, mark the entry."""
    data = data if data is not None else path.read_bytes()
    lg = ledger.load()
    t = lg.find(entry_id)
    if t is None:
        raise KeyError(entry_id)
    out = {"file": str(path), "id": entry_id, "date": t.date.isoformat(), "payee": t.payee,
           "status": "attached", "deductible": None}
    if _already_attached(t, data):
        out["status"] = "already attached"
    else:
        details.attach(entry_id, path.name, data)
    if path.name.startswith("unmatched-") and path.resolve().is_relative_to(docs.root().resolve()):
        path.unlink()  # the filed copy now lives under its matched name
    rule = activity.rule_for(t.payee, t.meta.get("bank_payee"))
    if rule and activity._truthy(rule["deductible"]) and "deductible" not in t.meta:
        out["deductible"] = activity.set_deductible(entry_id, True)
    else:
        out["deductible"] = activity.deductible(ledger.load().find(entry_id)).as_dict()
    return out


def unmatched_name(path: Path, when: date | None) -> str:
    """unmatched-<date>_<name>.<ext>; no date prefix when the name already carries one."""
    dated = when and not parse_filename(path.name)[0]
    return (f"unmatched-{f'{when}_' if dated else ''}{details.slug(path.stem)}"
            f"{path.suffix.lower()}")


def _keep_unmatched(path: Path, data: bytes, when: date | None) -> str:
    return docs.rel(docs.put(data, "receipts", (when or date.today()).year,
                             unmatched_name(path, when)))


def receipt(path: str | Path, entry_id: str | None = None, dry_run: bool = False) -> dict:
    """Match one receipt (or every file of a folder) and attach it."""
    path = Path(path)
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file())
        return {"results": [receipt(f, dry_run=dry_run) for f in files]}
    lg = ledger.load()
    data = path.read_bytes()
    if entry_id:
        return attach(path, entry_id, data) if not dry_run else {"file": str(path), "id": entry_id,
                                                                  "status": "would attach"}
    parsed = parse(path)
    cands = candidates(parsed, lg)
    chosen = pick(cands)
    base = {"file": str(path), "dates": [d.isoformat() for d in parsed["dates"]],
            "amounts": [f"{v} {c}" for v, c in parsed["amounts"]], "candidates": cands}
    if chosen:
        if dry_run:
            return {**base, **{k: chosen[k] for k in ("id", "date", "payee")},
                    "status": "would attach"}
        out = {**base, **attach(path, chosen["id"], data)}
        _record_vat(chosen["id"], parsed)
        return out
    reason = ("ambiguous" if cands else "no date/amount found"
              if not (parsed["dates"] and parsed["amounts"]) else "no transaction matches")
    kept = None if dry_run else _keep_unmatched(path, data, doc_date(parsed))
    return {**base, "status": "unmatched", "reason": reason, "kept": kept}


def _record_vat(entry_id: str, parsed: dict) -> None:
    """Keep the receipt's real VAT rate when it differs from the payee rule's (a flight that
    is mostly airport taxes, a 10% Uber vs a 21% rule)."""
    vat = parsed.get("vat")
    total = parsed["amounts"][0][0] if parsed["amounts"] else None
    if vat is None or not total or vat >= total:
        return
    d = activity.deductible(ledger.load().find(entry_id))
    rate = (vat / (total - vat) * 100).quantize(Decimal("0.01"))
    if d.vat == "es" and (d.vat_rate is None or abs(rate - d.vat_rate * 100) > Decimal("0.5")):
        ledger.update_txn(entry_id, meta={"vat_rate": str(rate)})


def summary(r: dict) -> str:
    rows = r.get("results", [r])
    lines = []
    for x in rows:
        if x["status"] == "unmatched":
            lines.append(f"UNMATCHED {x['file']}: {x['reason']} (dates {', '.join(x['dates'])}; "
                         f"amounts {', '.join(x['amounts'])})")
        else:
            d = x.get("deductible") or {}
            lines.append(f"{x['status']:<16} {x['file']} → {x.get('date', '')} "
                         f"{x.get('payee', '')} [{x['id']}]"
                         + (f" deductible {d['pct']}%" if d.get("on") else ""))
    n = sum(x["status"] != "unmatched" for x in rows)
    lines.append(f"{n} matched, {len(rows) - n} unmatched")
    return "\n".join(lines)

