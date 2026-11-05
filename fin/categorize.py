"""Suggest the counter-account for a Candidate: rules, then ledger history, then Claude Haiku."""

from collections import Counter, defaultdict
from difflib import SequenceMatcher

from fin import config, ledger, llm, payees
from fin.models import Candidate
from fin.payees import normalize

MIN_SHARE = 0.8
FUZZY = 0.85
Hist = dict[tuple[str, str], Counter]  # (direction, normalized payee) -> account counts

_hist_cache: tuple[int, dict] | None = None


def own_accounts() -> set[str]:
    banks = config.section("enable_banking").get("banks", {}).values()
    own = {b["account"] for b in banks if "account" in b}
    own.add(config.section("indexa").get("account", "Assets:Investment:Indexa"))
    return own


def _is_own(account: str) -> bool:
    return account in own_accounts() or account.startswith("Assets:Bank:")


def _key(text: str, amount) -> tuple[str, str]:
    """History key: money direction plus payee, so refunds/salary don't mix with payments."""
    return ("in" if amount > 0 else "out", normalize(text))


def history(lg: ledger.Ledger) -> Hist:
    """normalized payee → Counter(counter-account) over bank transactions in the ledger."""
    global _hist_cache
    if _hist_cache and _hist_cache[0] == id(lg):
        return _hist_cache[1]
    hist: Hist = defaultdict(Counter)
    for t in lg.transactions:
        own = [p for p in t.postings if _is_own(p.account)]
        if not own or not normalize(t.payee):
            continue
        key = _key(t.payee, own[0].units.number)
        for p in t.postings:
            if not _is_own(p.account) and not p.account.startswith("Equity:"):
                hist[key][p.account] += 1
    _hist_cache = (id(lg), dict(hist))
    return _hist_cache[1]


def _lookup(key: tuple[str, str], hist: Hist) -> tuple[Counter, bool]:
    """Bookings for this payee: exact key, else merged over similar payees (same direction)."""
    if key in hist:
        return hist[key], True
    direction, payee = key
    merged: Counter = Counter()
    if payee:
        for (d, other), counts in hist.items():
            m = SequenceMatcher(None, payee, other)
            if (d == direction and m.real_quick_ratio() >= FUZZY and m.quick_ratio() >= FUZZY
                    and m.ratio() >= FUZZY):
                merged.update(counts)
    return merged, False


def from_history(c: Candidate, hist: Hist) -> tuple[list[dict], bool]:
    """(ranked suggestions, decisive?) using the ledger alone."""
    counts, exact = _lookup(_key(c.payee, c.amount), hist)
    if not counts and normalize(c.narration) != normalize(c.payee):
        counts, exact = _lookup(_key(c.narration, c.amount), hist)
    total = sum(counts.values())
    if not total:
        return [], False
    sugg = [{"account": a, "p": round(n / total, 2)} for a, n in counts.most_common(3)]
    decisive = sugg[0]["p"] >= MIN_SHARE and (total >= 2 or exact)
    return sugg, decisive


def _accounts(c: Candidate, lg: ledger.Ledger, hist: Hist) -> dict[str, str]:
    """Account -> description with the payees most often booked there."""
    examples: dict[str, Counter] = defaultdict(Counter)
    for (_, payee), counts in hist.items():
        for a, n in counts.items():
            examples[a][payee] += n
    accounts = [a for a in lg.accounts() if a.startswith(("Expenses:", "Income:", "Assets:Cash"))]
    accounts += sorted(a for a in own_accounts() if a != c.account and a in lg.accounts())
    out = {}
    for a in accounts:
        top = [p for p, _ in examples[a].most_common(5)]
        desc = a.split(":", 1)[-1].replace(":", " / ")
        out[a] = desc + (f" (e.g. {', '.join(top)})" if top else "")
    return out


def ask_llm(c: Candidate, lg: ledger.Ledger, hist: Hist):
    if not llm.enabled():
        return None
    txn = {"payee": c.payee, "narration": c.narration, "amount": str(c.amount),
           "currency": c.currency, "bank_text": (c.raw or {}).get("bank_payee")}
    try:
        return llm.choose_account(txn, _accounts(c, lg, hist))
    except Exception:  # an API hiccup must not stop the sync: the item goes to review
        return None


def suggest(c: Candidate, lg: ledger.Ledger) -> tuple[list[dict], str | None]:
    """Ranked suggestions [{"account", "p"}] and the auto-book reason or None.

    Reasons: "rule" (ledger/rules.toml), "history" (decisive ledger history), "llm" (Haiku,
    only when it is confident)."""
    rule = payees.match(c.payee, (c.raw or {}).get("bank_payee"), c.narration)
    if rule and rule.get("account"):
        return [{"account": rule["account"], "p": 1.0}], "rule"
    hist = history(lg)
    sugg, decisive = from_history(c, hist)
    if decisive:
        return sugg, "history"
    answer = ask_llm(c, lg, hist)
    if answer:
        sugg = [{"account": answer.account, "p": 0.9 if answer.confidence == "high" else 0.5}]
        sugg += [x for x in from_history(c, hist)[0] if x["account"] != answer.account][:2]
        if answer.confidence == "high":
            return sugg, "llm"
    if not sugg:
        default = "Income:Uncategorized" if c.amount > 0 else "Expenses:Uncategorized"
        sugg = [{"account": default, "p": 0.0}]
    return sugg, None
