"""Turn Candidates into ledger entries (auto-booked) or pending review items."""

from decimal import Decimal

from beancount.core import prices as bprices

from fin import categorize, config, ledger, payees, store
from fin.models import Candidate, Posting, Txn
from fin.renta import interest, invoices
from fin.sync import indexa

PENDING_STATUS = ("PDNG", "PENDING")


def _postings(c: Candidate, account: str, lg: ledger.Ledger) -> list[Posting]:
    own = Posting(c.account, c.amount, c.currency)
    if c.source == "wallet":  # coin units: cost at today's price so lots stay valued
        _, price = bprices.get_price(lg.price_map, (c.currency, "USD"))
        held_at_cost = any(p.account == c.account and p.units.currency == c.currency and p.cost
                           for t in lg.transactions for p in t.postings)
        if c.amount < 0 and held_at_cost:
            own.cost = "{}"
        elif c.amount < 0:  # lots booked with @ price have no cost to reduce
            own.price = f"@ {(price or Decimal(1)).quantize(Decimal('0.0001'))} USD"
        elif price:
            own.cost = f"{{{price.quantize(Decimal('0.01'))} USD}}"
        return [Posting(account), own]
    if account == indexa.account() and c.currency == "EUR" and c.amount < 0:
        return [Posting(account, -c.amount, indexa.COMMODITY, cost="{1 EUR}"), own]
    if account == interest.INCOME and c.amount > 0:  # bank interest is paid net of 19%
        return [*interest.postings(c.amount, c.currency), own]
    return [Posting(account, -c.amount, c.currency), own]


def to_txn(c: Candidate, account: str, lg: ledger.Ledger, auto: str | None = None) -> Txn:
    meta = {"transaction_id": c.external_id, "source": c.source}
    if auto:
        meta["auto"] = auto
    if (c.raw or {}).get("bank_payee"):
        meta["bank_payee"] = c.raw["bank_payee"]
    flag = "!" if (c.raw or {}).get("status") in PENDING_STATUS else "*"
    return Txn(c.date, c.payee, c.narration, _postings(c, account, lg), meta, flag)


def _is_dup(c: Candidate, lg: ledger.Ledger) -> bool:
    """Same account/amount within a day in a hand-written entry (no bank id): already booked."""
    for t in lg.transactions:
        if abs((t.date - c.date).days) > 1 or any(k in t.meta for k in ledger.ID_KEYS):
            continue
        if any(p.account == c.account and p.units.number == c.amount
               and p.units.currency == c.currency for p in t.postings):
            return True
    return False


def _hash_id(ext: str) -> bool:
    """Ids the sync makes up when the bank sends none (`<bank>:<sha1 prefix>`, banks.py)."""
    head, _, tail = ext.partition(":")
    return bool(tail) and len(tail) == 16 and all(ch in "0123456789abcdef" for ch in tail)


def _same_row_other_id(c: Candidate, lg: ledger.Ledger) -> bool:
    """The bank sent this row before under another kind of id: first with no id (we hashed it),
    then with its own (Caixa: `2026-10-30.0`), or the other way round. Same source, date,
    account, amount and text = the same row. Two real identical charges keep the same kind of
    id (`.0` / `.1`), so they still both book."""
    mine = _hash_id(c.external_id)
    for t in lg.transactions:
        if t.date != c.date or t.meta.get("source") != c.source:
            continue
        ext = next((str(t.meta[k]) for k in ledger.ID_KEYS if k in t.meta), None)
        if ext is None or ext == c.external_id or _hash_id(ext) == mine:
            continue
        if t.narration == c.narration and any(
                p.account == c.account and p.units.number == c.amount for p in t.postings):
            return True
    for p in store.list_pending():  # the first copy may still be waiting for review
        ext = p["external_id"]
        if (ext != c.external_id and _hash_id(ext) != mine and p["source"] == c.source
                and p["date"] == c.date.isoformat() and p["narration"] == c.narration
                and Decimal(str(p["amount"])) == c.amount):
            return True
    return False


def _row(c: Candidate, **extra) -> dict:
    return {"id": c.external_id, "date": c.date.isoformat(), "payee": c.payee,
            "narration": c.narration, "amount": str(c.amount), "currency": c.currency,
            "source": c.source, **extra}


def ingest(cands: list[Candidate], dry_run: bool = False) -> dict:
    lg = ledger.load()
    known = lg.external_ids() | store.pending_ids() | set(store.get("dismissed", []))
    res: dict = {"total": len(cands), "skipped": 0, "booked": [], "pending": [], "errors": []}
    book, pend = [], []
    bank_keys = set(config.section("enable_banking").get("banks", {}))
    flagged = {ledger.txn_id(t) for t in lg.transactions if t.flag == "!"}
    settled = [c.external_id for c in cands if c.external_id in flagged
               and (c.raw or {}).get("status") not in PENDING_STATUS]
    if settled and not dry_run:
        res["settled"] = ledger.settle(settled)
    for c in cands:
        if c.external_id in known or _is_dup(c, lg) or _same_row_other_id(c, lg):
            res["skipped"] += 1
            continue
        known.add(c.external_id)
        if c.source in bank_keys:
            payees.prepare(c)
        sugg, reason = categorize.suggest(c, lg)
        if reason and not invoices.receipt_expected(lg, sugg[0]["account"], c.amount):
            reason = None  # client payment with no booked invoice: review it
        (book if reason else pend).append((c, sugg, reason))
    res["booked"] = [_row(c, account=s[0]["account"], auto=r) for c, s, r in book]
    res["pending"] = [_row(c, suggestions=s) for c, s, _ in pend]
    if dry_run:
        return res
    if any(s[0]["account"] == indexa.account() for _, s, _ in book):
        ledger.ensure_open(indexa.account(), indexa.COMMODITY)
    if any(s[0]["account"] == interest.INCOME for _, s, _ in book):
        ledger.ensure_open(interest.WITHHELD, "EUR")
    txns = {c.external_id: to_txn(c, s[0]["account"], lg, r) for c, s, r in book}
    failed = {t.meta["transaction_id"]: msg for t, msg in ledger.append_safe(list(txns.values()))}
    for c, s, _ in book:
        if c.external_id in failed:
            res["errors"].append(f"{c.date} {c.payee}: {failed[c.external_id]}")
            pend.append((c, s, None))
    res["booked"] = [b for b in res["booked"] if b["id"] not in failed]
    for c, s, _ in pend:
        store.add_pending(c, s)
    res["pending"] = [_row(c, suggestions=s) for c, s, _ in pend]
    if res["booked"] or res["pending"] or res.get("settled"):
        ledger.commit(f"sync: {len(res['booked'])} booked, {len(res['pending'])} pending, "
                      f"{res.get('settled', 0)} settled")
    return res


def resolve(id_or_prefix: str) -> Candidate:
    c = store.get_candidate(id_or_prefix)
    if c:
        return c
    hits = [p["external_id"] for p in store.list_pending()
            if p["external_id"].startswith(id_or_prefix)]
    if len(hits) != 1:
        raise KeyError(f"pending id {id_or_prefix!r}: {len(hits)} matches")
    return store.get_candidate(hits[0])


def approve(external_id: str, account: str) -> dict:
    c = resolve(external_id)
    lg = ledger.load()
    if account == indexa.account():
        ledger.ensure_open(account, indexa.COMMODITY)
    elif account not in lg.accounts():
        raise ValueError(f"unknown account {account}; see `fin accounts`")
    if account == interest.INCOME:
        ledger.ensure_open(interest.WITHHELD, "EUR")
    t = to_txn(c, account, lg)
    ledger.append([t])
    store.remove_pending(c.external_id)
    ledger.commit(f"approve: {c.date} {c.payee} → {account}")
    return _row(c, account=account)


def dismiss(external_id: str) -> dict:
    c = resolve(external_id)
    store.remove_pending(c.external_id)
    store.put("dismissed", sorted({*store.get("dismissed", []), c.external_id}))
    return _row(c)


def recategorize(entry_id: str, account: str) -> dict:
    lg = ledger.load()
    t = lg.find(entry_id)
    if t is None:  # accept the short id prefix shown in the Telegram list
        hits = [x for x in lg.transactions if ledger.txn_id(x).startswith(entry_id)]
        if len(hits) != 1:
            raise KeyError(f"entry {entry_id!r}: {len(hits)} matches")
        t, entry_id = hits[0], ledger.txn_id(hits[0])
    if account not in lg.accounts():
        raise ValueError(f"unknown account {account}; see `fin accounts`")
    others = [p.account for p in t.postings if not categorize._is_own(p.account)]
    if len(others) != 1:
        raise ValueError(f"{entry_id}: expected one counter-posting, found {len(others)}")
    ledger.set_account(entry_id, others[0], account)
    ledger.commit(f"recat: {t.date} {t.payee} {others[0]} → {account}")
    return {"id": entry_id, "from": others[0], "to": account}
