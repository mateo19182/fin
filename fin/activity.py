"""Is an expense deductible for the autónomo activity? One resolver used everywhere.

Precedence: transaction meta (`deductible: "true"|"false"`, `deductible_pct`, `vat`,
`equipment`) → the first rule in ledger/rules.toml with a `deductible` key matching the payee
or the raw bank text (not the narration: deductibility is about the supplier) → not deductible.
IRPF and IVA are separate: `deductible_pct` is the IRPF share, `vat_pct` the IVA share (defaults
to `deductible_pct`). The bank charge is enough proof for IRPF; Spanish IVA ("es") needs the
invoice, so with `requires_receipt = true` and no `document` attached the expense still counts
for IRPF at its gross amount and its IVA is left out (`iva_blocked`).

VAT origin (`vat`): "es" Spanish invoice with IVA (deductible base = net of IVA), "eu" / "non_eu"
foreign supplier without VAT (self-assessed in the 303, neutral), "oss" foreign supplier that
charged Spanish VAT as B2C (counts gross, nothing in the 303). See params_2026.IVA_RATES.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from fin import ledger, payees
from fin.renta import params_2026 as P

ZERO = Decimal(0)
CENT = Decimal("0.01")
VAT_ORIGINS = ("es", "eu", "non_eu", "oss")
EXCLUDED = ("Expenses:Taxes",)
ACTIVITY_FIELDS = ("deductible", "deductible_pct", "vat_pct", "requires_receipt", "vat",
                   "vat_rate")


@dataclass
class Deductible:
    on: bool
    pct: int
    reason: str
    vat: str | None = None  # VAT origin, see module doc
    vat_rate: Decimal | None = None
    equipment: bool = False
    vat_pct: int | None = None  # IVA share; None = same as pct
    iva_blocked: bool = False  # Spanish IVA left out: no invoice attached

    def as_dict(self) -> dict:
        return {"on": self.on, "pct": self.pct, "reason": self.reason, "vat": self.vat,
                "vat_rate": str(self.vat_rate) if self.vat_rate is not None else None,
                "equipment": self.equipment, "vat_pct": self.vat_share,
                "iva_blocked": self.iva_blocked}

    @property
    def vat_share(self) -> int:
        return self.pct if self.vat_pct is None else self.vat_pct


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "yes", "1", "on")


def rule_for(payee: str | None, bank_payee: str | None = None) -> dict | None:
    """First rule carrying a `deductible` key that matches the payee or the raw bank text."""
    for r in payees.rules():
        if "deductible" in r and any(r["_re"].search(x) for x in (payee, bank_payee) if x):
            return r
    return None


def _rate(origin: str | None, rule: dict | None, meta: dict) -> Decimal | None:
    if origin != "es":
        return None
    raw = meta.get("vat_rate") or (rule or {}).get("vat_rate")
    return Decimal(str(raw)) / 100 if raw is not None else P.IVA_RATES["es"]


def _pct(*values, default: int) -> int:
    for v in values:
        if v is not None and v != "":
            return max(0, min(100, int(v)))
    return default


def deductible(t) -> Deductible:
    meta = t.meta
    rule = rule_for(t.payee, meta.get("bank_payee")) or {}
    origin = meta.get("vat") or rule.get("vat")
    origin = origin if origin in VAT_ORIGINS else None
    equipment = _truthy(meta.get("equipment", ""))
    pct = _pct(meta.get("deductible_pct"), rule.get("deductible_pct"), default=100)
    vat_pct = _pct(meta.get("vat_pct"), rule.get("vat_pct"), default=pct)
    rate = _rate(origin, rule, meta)
    blocked = (origin == "es" and _truthy(rule.get("requires_receipt", ""))
               and not has_receipt(t))
    if "deductible" in meta:
        on = _truthy(meta["deductible"])
        return Deductible(on, pct if on else 0, "meta", origin, rate, equipment,
                          vat_pct if on else 0, blocked and on)
    if _truthy(meta.get("activity", "")):
        return Deductible(True, pct, "meta activity", origin, rate, equipment, vat_pct, blocked)
    if rule and _truthy(rule["deductible"]):
        reason = "no invoice: IRPF only" if blocked else "rule"
        return Deductible(True, pct, reason, origin, rate, equipment, vat_pct, blocked)
    return Deductible(False, 0, "", origin, rate, equipment)


def has_receipt(t) -> bool:
    return any(k == "document" or k.startswith("document_") for k in t.meta)


def expense_amount(t, lg: ledger.Ledger) -> Decimal:
    """EUR total of the Expenses postings that can be activity costs (taxes excluded)."""
    total = ZERO
    for p in t.postings:
        if p.account.startswith("Expenses:") and not p.account.startswith(EXCLUDED):
            total += lg.to_eur(p.units.number, p.units.currency, t.date) or ZERO
    return total


def split_vat(amount: Decimal, d: Deductible) -> tuple[Decimal, Decimal]:
    """(base, IVA) of a gross amount: Spanish invoices carry IVA, foreign ones do not."""
    if d.vat == "es" and d.vat_rate:
        base = (amount / (1 + d.vat_rate)).quantize(CENT)
        return base, amount - base
    return amount, ZERO


def cost(t, lg: ledger.Ledger) -> dict | None:
    """The deductible share of one transaction, or None. `base` is what IRPF deducts
    (net of deductible IVA, times pct); `iva` the Spanish IVA soportado (times pct)."""
    d = deductible(t)
    if not d.on:
        return None
    gross = expense_amount(t, lg)
    if not gross:  # a refund (negative) of a deductible supplier reduces the costs
        return None
    # without the invoice the IVA is not deductible, so all of it is an IRPF expense
    net, iva = (gross, ZERO) if d.iva_blocked else split_vat(gross, d)
    base = (net * Decimal(d.pct) / 100).quantize(CENT)
    # the 303 deducts Spanish IVA with its invoice, and foreign suppliers' self-assessed VAT
    in_303 = (d.vat == "es" and not d.iva_blocked) or d.vat in ("eu", "non_eu")
    vat_share = Decimal(d.vat_share) / 100 if in_303 else ZERO
    iva, vat_base = (iva * vat_share).quantize(CENT), (net * vat_share).quantize(CENT)
    if not base and not iva:
        return None
    # base: IRPF expense; vat_base / iva: what the 303 deducts (casillas 28/29)
    return {"id": ledger.txn_id(t), "date": t.date.isoformat(), "payee": t.payee or "",
            "gross": gross.quantize(CENT), "base": base, "iva": iva, "vat_base": vat_base,
            "pct": d.pct,
            "vat_pct": d.vat_share, "vat": d.vat, "equipment": d.equipment,
            "reason": d.reason, "iva_blocked": d.iva_blocked}


def costs(lg: ledger.Ledger, start: date, end: date) -> list[dict]:
    """Deductible costs in [start, end]; equipment is listed but amortised, not expensed."""
    out = []
    for t in lg.transactions:
        if start <= t.date <= end and (c := cost(t, lg)):
            out.append(c)
    return out


def amortisation(lg: ledger.Ledger, start: date, end: date) -> list[dict]:
    """Linear amortisation of equipment accrued in [start, end], prorated by days."""
    rows = []
    for t in lg.transactions:
        if t.date > end:
            break
        c = cost(t, lg)
        if not c or not c["equipment"] or not c["base"]:
            continue
        annual = c["base"] * P.AMORTIZACION_EQUIPOS
        life_end = min(t.date.replace(year=t.date.year + P.AMORTIZACION_EQUIPOS_YEARS_MAX),
                       t.date + timedelta(days=int(c["base"] / annual * 365)))
        first, last = max(start, t.date), min(end, life_end)
        if last < first:
            continue
        amount = _accrued(annual, t.date, last, c["base"]) \
            - _accrued(annual, t.date, first - timedelta(days=1), c["base"])
        rows.append({**c, "annual": annual.quantize(CENT), "rate": str(P.AMORTIZACION_EQUIPOS),
                     "from": first.isoformat(), "to": last.isoformat(),
                     "amount": amount.quantize(CENT), "fully_amortised": life_end.isoformat()})
    return rows


def _accrued(annual: Decimal, bought: date, until: date, cap: Decimal) -> Decimal:
    days = (until - bought).days + 1
    return min(annual * days / 365, cap) if days > 0 else ZERO


# --- writes -------------------------------------------------------------------


def set_deductible(entry_id: str, on: bool, pct: int | None = None,
                   equipment: bool | None = None) -> dict:
    lg = ledger.load()
    t = lg.find(entry_id)
    if t is None:
        raise KeyError(entry_id)
    meta: dict[str, str] = {"deductible": "true" if on else "false"}
    if pct is not None:
        if not 0 <= pct <= 100:
            raise ValueError("pct must be 0-100")
        meta["deductible_pct"] = str(pct)
    if equipment is not None:
        meta["equipment"] = "true" if equipment else "false"
    ledger.update_txn(entry_id, meta=meta)
    ledger.commit(f"deductible: {t.date} {t.payee} {'on' if on else 'off'}")
    return deductible(ledger.load().find(entry_id)).as_dict()


def payee_rule(payee: str) -> dict | None:
    r = rule_for(payee)
    return {k: v for k, v in r.items() if not k.startswith("_")} if r else None


def set_payee_deductible(payee: str, on: bool, pct: int | None = None,
                         vat: str | None = None) -> dict:
    """Create or update the rule that decides for `payee` (regex-escaped exact match)."""
    import re

    if pct is not None and not 0 <= pct <= 100:
        raise ValueError("pct must be 0-100")
    if vat is not None and vat not in VAT_ORIGINS:
        raise ValueError(f"vat must be one of {', '.join(VAT_ORIGINS)}")
    fields: dict = {"deductible": on}
    if pct is not None:
        fields["deductible_pct"] = pct
    if vat is not None:
        fields["vat"] = vat
    existing = rule_for(payee)
    if existing:
        return payees.update_rule(existing["match"], **fields)
    return payees.add_rule(f"^{re.escape(payee)}$", **fields)
