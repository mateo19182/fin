"""Readable payees from bank descriptions, and the user's own rules (ledger/rules.toml).

`clean` is a short ordered list of regex substitutions, not a model: processor prefixes
(TJ-, Sumup, Sq, Wl…), order codes, legal suffixes and mojibake go; SHOUTING gets title-cased.
Rules are `[[rule]]` tables with `match` (regex, case-insensitive, searched in the cleaned
payee, then the raw bank text, then the narration), optional `payee` and optional `account`.
Activity fields (see fin/activity.py): `deductible`, `deductible_pct` (IRPF), `vat_pct` (IVA),
`requires_receipt`, `vat` ("es" | "eu" | "non_eu" | "oss") and `vat_rate`. Subscription flag
(see fin/analytics.py): `subscription` true | false.
"""

import re
import tomllib
from datetime import date

from fin import ledger
from fin.config import ledger_file
from fin.models import Candidate

BIZUM = re.compile(r"^(?P<concept>.*?)\s*Bizum payment (?:from|to):\s*(?P<name>.+?)\s*$", re.I)
NO_CONCEPT = {"", "sin concepto"}
# (pattern, replacement) applied in order with re.sub (IGNORECASE); \g<...> allowed.
SUBS = [
    (r"\s{2,}", " "),
    (r"ã", "ñ"),  # Caixa encodes Ñ this way
    (r"\bCORU[.#ñ]A\b", "Coruña"),
    (r"^(?:TJ-|TST-|WL \*|SQ \*|SUMUP\s*\*+|ZETTLE_\*|MP\*\*|ANT\*|PAYPAL \*|Bizum de)\s*", ""),
    (r"^Google \*\s*", "Google "),
    (r"^RCBO\.", ""),
    (r"^(?:www\.)?(\w[\w-]*\.\w+)(?:/.*)?$", r"\1"),  # bare domains: dazn.com, airvpn.org
    (r"^\d{3}[.-]\s*", ""),  # store numbers: 144.gadis, 083-feu vert
    (r"^Uber \*?\s*Eats\b.*", "Uber Eats"),
    (r"^Glovo.*", "Glovo"),
    (r"^(Vast\.ai|Airbnb|Vueling|Uber(?! Eats$)|Amazon|Openrouter|Cursor)\b.*", r"\1"),
    (r"^Steam Purchase$", "Steam"),
    (r"^NH Collection A Coruña.*", "NH Collection A Coruña"),
    (r"^TGSS\..*", "TGSS"),
    (r"^LIQ\.CTA\.VISTA\b.*", "Caixa Rural"),
    (r"^Metal Repricing.*|^(Plus|Premium) plan fee$", "Revolut"),
    (r"\s+\d{4,}$", ""),  # trailing store/terminal numbers: Dia 13849, Tesco Stores 6849
    (r",?\s+(?:S\.?\s?L\.?U?|S\.?\s?A\.?|GmbH|Inc\.?|Ltd\.?|Limited)\.?$", ""),
]
KEEP_UPPER = {"NH", "SK", "UK", "GB", "CH", "FI", "AI", "TV", "TGSS", "AEAT"}
LOWER = {"de", "del", "la", "las", "los", "el", "y", "e", "do", "da", "dos", "das", "of", "the",
         "and", "en"}
_rules_cache: tuple[float, list[dict]] | None = None


def normalize(text: str) -> str:
    """Comparison key for a payee: casefolded words, punctuation and bare numbers dropped."""
    s = re.sub(r"[^\w\s]", " ", (text or "").casefold())
    return " ".join(w for w in s.split() if not w.isdigit())


def split(raw: str) -> tuple[str, str | None]:
    """(clean payee, concept moved out of the payee or None)."""
    text, concept = (raw or "").strip(), None
    if m := BIZUM.match(text):
        text = m["name"]
        concept = m["concept"].strip() or None
        if concept and concept.casefold() in NO_CONCEPT:
            concept = None
    shouting = text == text.upper() and any(c.isalpha() for c in text)
    for pat, repl in SUBS:
        text = re.sub(pat, repl, text, flags=re.I).strip()
    return _case(text, shouting) or (raw or "").strip(), concept


def clean(raw: str) -> str:
    return split(raw)[0]


def _case(text: str, shouting: bool) -> str:
    """Title-case SHOUTING words (3+ letters, not known acronyms); capitalize lowercase ones."""
    words = []
    for i, w in enumerate(text.split()):
        if shouting and i and w.lower() in LOWER:
            words.append(w.lower())
        elif w.isupper() and sum(c.isalpha() for c in w) >= 3 and w not in KEEP_UPPER:
            words.append(w[0] + w[1:].lower())
        elif w.islower() and "." not in w:
            words.append(w[0].upper() + w[1:])
        else:
            words.append(w)
    return " ".join(words)


# --- rules --------------------------------------------------------------------

def rules_file():
    return ledger_file().parent / "rules.toml"


def rules() -> list[dict]:
    global _rules_cache
    f = rules_file()
    if not f.exists():
        return []
    mtime = f.stat().st_mtime
    if _rules_cache is None or _rules_cache[0] != mtime:
        items = tomllib.loads(f.read_text()).get("rule", [])
        for r in items:
            r["_re"] = re.compile(r["match"], re.I)
        _rules_cache = (mtime, items)
    return _rules_cache[1]


def match(payee: str, bank_payee: str | None = None, narration: str | None = None) -> dict | None:
    """First rename/account rule whose regex is found in the payee, raw bank text or narration.
    Rules carrying only activity fields (see fin/activity.py) are skipped here."""
    for r in rules():
        if ("payee" in r or "account" in r) and \
                any(r["_re"].search(x) for x in (payee, bank_payee, narration) if x):
            return r
    return None


def list_rules() -> list[dict]:
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rules()]


def add_rule(match_: str, payee: str | None = None, account: str | None = None,
             **fields) -> dict:
    """Append a rule. `fields` are the activity keys (deductible, vat, ...), already typed."""
    re.compile(match_)
    if not payee and not account and not fields:
        raise ValueError("a rule needs a payee rename, an account or activity fields")
    if account and account not in ledger.load().accounts():
        raise ValueError(f"unknown account {account}; see `fin accounts`")
    rule = {"match": match_}
    if payee:
        rule["payee"] = payee
    if account:
        rule["account"] = account
    rule.update({k: v for k, v in fields.items() if v is not None})
    lines = [f"\n[[rule]]  # added {date.today()}"]
    lines += [f"{k} = {_toml_val(v)}" for k, v in rule.items()]
    f = rules_file()
    with ledger.write_lock():
        old = f.read_text() if f.exists() else "# Payee/category rules; see fin/payees.py\n"
        f.write_text(old.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
    ledger.commit(f"rule: {match_} → {payee or ''} {account or ''}".rstrip())
    return rule


KEY_LINE = re.compile(r"^([a-z_]+)\s*=")


def update_rule(match_: str, **fields) -> dict:
    """Set/replace keys of the rule whose `match` is `match_` (a None value deletes the key)."""
    f = rules_file()
    blocks = re.split(r"(?m)^(?=\[\[rule\]\])", f.read_text())
    for i, b in enumerate(blocks):
        try:
            cur = tomllib.loads(b)["rule"][0] if b.startswith("[[rule]]") else None
        except (tomllib.TOMLDecodeError, KeyError, IndexError):
            cur = None
        if cur is None or cur.get("match") != match_:
            continue
        lines = [ln for ln in b.rstrip("\n").split("\n")
                 if not (m := KEY_LINE.match(ln)) or m[1] not in fields]
        lines += [f"{k} = {_toml_val(v)}" for k, v in fields.items() if v is not None]
        blocks[i] = "\n".join(lines) + "\n\n"
        with ledger.write_lock():
            f.write_text("".join(blocks).rstrip("\n") + "\n")
        ledger.commit(f"rule: {match_} {fields}")
        cur.update(fields)
        return {k: v for k, v in cur.items() if v is not None}
    raise KeyError(f"no rule with match {match_!r}")


def _toml_val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def prepare(c: Candidate) -> Candidate:
    """Clean a bank candidate in place: readable payee, concept → narration, raw text kept."""
    raw = c.payee
    payee, concept = split(raw)
    if concept and c.narration.strip() in (raw.strip(), ""):
        c.narration = concept
    if r := match(payee, raw, c.narration):
        payee = r.get("payee", payee)
    c.payee = payee
    if payee != raw:
        c.raw = {**(c.raw or {}), "bank_payee": raw}
    return c
