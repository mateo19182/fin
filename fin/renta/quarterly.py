"""Quarterly 303 (IVA) and 130 (pago fraccionado IRPF) figures from the ledger, per casilla.

Casilla numbers and deadlines: params_2026.CASILLAS_303 / CASILLAS_130 / QUARTER_DEADLINES
(AEAT instructions cited there). An estimate to compare with the gestor's filings, never the
return itself: cuotas a compensar from earlier quarters are not tracked.
"""

import re
from datetime import date, timedelta
from decimal import Decimal

from fin import activity, docs, ledger, store
from fin.renta import calc, invoices
from fin.renta import params_2026 as P
from fin.renta.report import AEAT_PAYMENTS, SS_AUTONOMO

ZERO = Decimal(0)
PERIOD = re.compile(r"^(\d{4})-([1-4])T$")
REMIND_DAYS = 10
CARD_DAYS_AFTER_END = 35
CARD_DAYS_BEFORE_DEADLINE = 15


def q(v: Decimal) -> str:
    return str(calc.q(v))


def parse_period(s: str) -> tuple[int, int]:
    m = PERIOD.match(s.strip().upper())
    if not m:
        raise ValueError(f"period must look like 2026-3T, got {s!r}")
    return int(m[1]), int(m[2])


def bounds(year: int, quarter: int) -> tuple[date, date]:
    start = date(year, 3 * quarter - 2, 1)
    end = date(year + quarter // 4, (3 * quarter) % 12 + 1, 1) - timedelta(days=1)
    return start, end


def deadline(year: int, quarter: int) -> date:
    month, day = P.QUARTER_DEADLINES[quarter]
    return date(year + (1 if quarter == 4 else 0), month, day)


def last_ended(today: date) -> tuple[int, int]:
    quarter = (today.month - 1) // 3 + 1
    return (today.year, quarter - 1) if quarter > 1 else (today.year - 1, 4)


def next_deadline(today: date) -> tuple[str, date]:
    """(period, deadline) of the first filing still open at `today`."""
    y, qn = last_ended(today)
    while deadline(y, qn) < today:
        y, qn = (y, qn + 1) if qn < 4 else (y + 1, 1)
    return f"{y}-{qn}T", deadline(y, qn)


def _postings(lg, start: date, end: date, account: str, sign: int) -> list[tuple]:
    """(txn, EUR amount) of postings to `account` with the given sign in [start, end]."""
    out = []
    for t in lg.transactions:
        if not start <= t.date <= end:
            continue
        v = sum((lg.to_eur(p.units.number, p.units.currency, t.date) or ZERO
                 for p in t.postings if p.account == account), ZERO)
        if v and (v > 0) == (sign > 0):
            out.append((t, abs(v)))
    return out


def _prefix_postings(lg, start: date, end: date, prefix: str) -> list[tuple]:
    out = []
    for t in lg.transactions:
        if not start <= t.date <= end:
            continue
        v = sum((lg.to_eur(p.units.number, p.units.currency, t.date) or ZERO
                 for p in t.postings if p.account.startswith(prefix)), ZERO)
        if v:
            out.append((t, -v))
    return out


def _row(t, amount: Decimal, **extra) -> dict:
    return {"id": ledger.txn_id(t), "date": t.date.isoformat(), "payee": t.payee or "",
            "amount": q(amount), **extra}


def tax_payments(lg, year: int) -> tuple[list[dict], list[dict]]:
    """(classified 303/130 payments of the year, AEAT payments still unclassified)."""
    booked, open_ = [], []
    for t in lg.transactions:
        if t.date.year != year:
            continue
        if t.meta.get("tax_form") in ("303", "130"):
            amt = sum((abs(p.units.number) for p in t.postings
                       if p.account in (invoices.IVA, invoices.PAGOS_FRACCIONADOS)), ZERO)
            booked.append(_row(t, amt, form=t.meta["tax_form"], period=t.meta.get("period")))
        elif t.meta.get("tax_form") == "ignore":
            continue
        elif (v := sum((p.units.number for p in t.postings if p.account == AEAT_PAYMENTS),
                       ZERO)) > 0:
            open_.append(_row(t, v, note="AEAT payment not classified: run "
                              f"`fin tax-payment {ledger.txn_id(t)} 303|130 {year}-NT`"))
    return booked, open_


def modelo_303(lg, year: int, quarter: int) -> dict:
    start, end = bounds(year, quarter)
    c = P.CASILLAS_303
    devengado = []
    for t, base in _prefix_postings(lg, start, end, invoices.INCOME + ":"):
        cuota = sum((-p.units.number for p in t.postings if p.account == invoices.IVA), ZERO)
        devengado.append(_row(t, base, cuota=q(cuota)))
    base_dev = sum((Decimal(r["amount"]) for r in devengado), ZERO)
    cuota_dev = sum((Decimal(r["cuota"]) for r in devengado), ZERO)
    costs = activity.costs(lg, start, end)
    groups = {k: [x for x in costs if x["vat"] == k] for k in ("es", "eu", "non_eu")}
    es_ded = [x for x in groups["es"] if x["vat_base"]]  # no invoice: IRPF only, not in the 303
    es_cur = [x for x in es_ded if not x["equipment"]]
    es_inv = [x for x in es_ded if x["equipment"]]
    rate = P.IVA_RATES["es"]

    def tot(rows, key):
        return sum((r[key] for r in rows), ZERO)

    # The gestor's method (matches the filed returns): a foreign supplier's amount is the base
    # and 21% of it is deducted in [28/29]; nothing is self-assessed in [10-13] / [36/37].
    foreign = [x for x in groups["eu"] + groups["non_eu"] if x["vat_base"]]
    for_base = tot(foreign, "vat_base")
    for_cuota = calc.q(for_base * rate)
    isp_base = intra_base = isp_cuota = intra_cuota = ZERO
    sop_base, sop_cuota = tot(es_cur, "vat_base") + for_base, tot(es_cur, "iva") + for_cuota
    inv_base, inv_cuota = tot(es_inv, "vat_base"), tot(es_inv, "iva")
    total_dev = cuota_dev
    total_ded = sop_cuota + inv_cuota
    result = total_dev - total_ded
    cas = {
        c["devengado.base"]: q(base_dev), c["devengado.tipo"]: "21.00",
        c["devengado.cuota"]: q(cuota_dev),
        c["intracom.base"]: q(intra_base), c["intracom.cuota"]: q(intra_cuota),
        c["isp.base"]: q(isp_base), c["isp.cuota"]: q(isp_cuota),
        c["total_devengado"]: q(total_dev),
        c["soportado.base"]: q(sop_base), c["soportado.cuota"]: q(sop_cuota),
        c["soportado_inversion.base"]: q(inv_base), c["soportado_inversion.cuota"]: q(inv_cuota),
        c["intracom_deducible.base"]: q(intra_base), c["intracom_deducible.cuota"]: q(intra_cuota),
        c["total_deducir"]: q(total_ded), c["resultado_regimen_general"]: q(result),
        c["suma_resultados"]: q(result), c["atribuible_estado"]: q(result),
        c["resultado_autoliquidacion"]: q(result), c["resultado"]: q(result),
    }
    strip = ("gross", "reason", "equipment", "pct", "vat")
    return {
        "casillas": cas, "resultado": q(result),
        "sentido": "a ingresar" if result > 0 else "a compensar" if result < 0 else "cero",
        "devengado": devengado,
        "soportado": {k: [{kk: vv for kk, vv in x.items() if kk not in strip or kk == "pct"}
                          for x in v] for k, v in (("es", es_cur), ("es_inversion", es_inv),
                                                   ("eu", groups["eu"]),
                                                   ("non_eu", groups["non_eu"]))},
        "oss": [x["id"] for x in costs if x["vat"] == "oss"],
        "sin_origen_iva": [x["id"] for x in costs if x["vat"] is None],
    }


def minoracion_130() -> Decimal:
    prev = P.RENTA_2025_RENDIMIENTO_NETO_ACTIVIDAD
    for limit, amount in P.MINORACION_130:
        if prev <= limit:
            return amount
    return ZERO


def modelo_130(lg, year: int, quarter: int, _negatives: Decimal = ZERO) -> dict:
    start, end = date(year, 1, 1), bounds(year, quarter)[1]
    c = P.CASILLAS_130
    ingresos_rows = [_row(t, v) for t, v in _prefix_postings(lg, start, end, invoices.INCOME + ":")]
    ss_rows = [_row(t, v) for t, v in _postings(lg, start, end, SS_AUTONOMO, +1)]
    costs = [x for x in activity.costs(lg, start, end) if not x["equipment"]]
    amort = activity.amortisation(lg, start, end)
    ingresos = sum((Decimal(r["amount"]) for r in ingresos_rows), ZERO)
    ss = sum((Decimal(r["amount"]) for r in ss_rows), ZERO)
    deducibles = sum((x["base"] for x in costs), ZERO)
    amortizacion = sum((x["amount"] for x in amort), ZERO)
    previo = ingresos - ss - deducibles - amortizacion
    dificil = calc.q(min(max(previo, ZERO) * P.ACTIVIDAD_DIFICIL_JUSTIFICACION,
                         P.ACTIVIDAD_DIFICIL_JUSTIFICACION_MAX))
    gastos = ss + deducibles + amortizacion + dificil
    neto = ingresos - gastos
    pct20 = calc.q(max(neto, ZERO) * Decimal("0.20"))
    pagos = [_row(t, v, period=t.meta.get("period"))
             for t, v in _postings(lg, start, end, invoices.PAGOS_FRACCIONADOS, +1)]
    anteriores = sum((Decimal(r["amount"]) for r in pagos), ZERO)
    ret_rows = [_row(t, v) for t, v in _postings(lg, start, end, invoices.RETENCIONES, +1)]
    retenciones = sum((Decimal(r["amount"]) for r in ret_rows), ZERO)
    previo_pago = pct20 - anteriores - retenciones
    suma = max(previo_pago, ZERO)
    minor = minoracion_130() if suma > 0 else ZERO
    diferencia = suma - minor
    negativos = min(_negatives, diferencia) if diferencia > 0 else ZERO
    total = diferencia - negativos
    cas = {
        c["ingresos"]: q(ingresos), c["gastos"]: q(gastos), c["rendimiento_neto"]: q(neto),
        c["pct20"]: q(pct20), c["pagos_anteriores"]: q(anteriores),
        c["retenciones"]: q(retenciones), c["pago_previo"]: q(previo_pago), c["suma"]: q(suma),
        c["minoracion"]: q(minor), c["diferencia"]: q(diferencia),
        c["negativos_anteriores"]: q(negativos), c["vivienda"]: "0.00", c["total"]: q(total),
        c["complementaria"]: "0.00", c["resultado"]: q(total),
    }
    return {
        "casillas": cas, "resultado": q(total),
        "sentido": "a ingresar" if total > 0 else "negativa (a deducir después)" if total < 0
        else "cero",
        "ingresos": ingresos_rows, "gastos": {
            "ss": q(ss), "deducibles": q(deducibles), "amortizacion": q(amortizacion),
            "dificil_justificacion": q(dificil), "total": q(gastos),
            "deducibles_entries": [x["id"] for x in costs],
            "amortizacion_entries": [{"id": x["id"], "amount": q(x["amount"])} for x in amort]},
        "retenciones": ret_rows, "pagos_anteriores": pagos,
        "note": ("Modelo 130 is not due when >= 70% of the previous year's activity income had "
                 "retención (art. 109.2 RIRPF) — the gestor decides; minoración casilla 13 from "
                 f"Renta 2025 rendimiento neto {P.RENTA_2025_RENDIMIENTO_NETO_ACTIVIDAD}"),
    }


def _unlinked_receipts(start: date, end: date) -> list[str]:
    """Names of `unmatched-<date>_*` receipts dated inside [start, end)."""
    folder = docs.path_for("receipts", start.year, "x").parent
    out = []
    for f in sorted(folder.glob("unmatched-*")) if folder.exists() else []:
        m = re.match(r"unmatched-(\d{4}-\d{2}-\d{2})", f.name)
        if m and start <= date.fromisoformat(m[1]) < end:
            out.append(f.name)
    return out


def quarter(period: str | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    year, qn = parse_period(period) if period else last_ended(today)
    lg = ledger.load()
    start, end = bounds(year, qn)
    negatives = ZERO  # 130 casilla 15: negative results of earlier quarters this year
    for k in range(1, qn):
        r = Decimal(modelo_130(lg, year, k, negatives)["resultado"])
        negatives = max(negatives - max(r, ZERO), ZERO) + (-r if r < 0 else ZERO)
    m303, m130 = modelo_303(lg, year, qn), modelo_130(lg, year, qn, negatives)
    booked, open_ = tax_payments(lg, year)
    per = f"{year}-{qn}T"
    due = deadline(year, qn)
    paid = [b for b in booked if b["period"] == per]
    warnings = [
        "Estimate from the ledger: compare with the gestor's 303/130 before filing",
        "Cuotas a compensar from earlier quarters are not tracked",
    ]
    if m303["sin_origen_iva"]:
        warnings.append(f"{len(m303['sin_origen_iva'])} deductible expense(s) without a vat "
                        "origin (set `vat` in the rule or the transaction): "
                        + ", ".join(m303["sin_origen_iva"][:5]))
    loose = _unlinked_receipts(start, end)
    if loose:
        warnings.append(f"{len(loose)} receipt(s) of this quarter are not linked to a payment "
                        "(paid by someone else, cash, or a card that isn't synced?): "
                        + ", ".join(loose))
    for p in paid:
        warnings.append(f"{p['form']} {per} paid {p['amount']} on {p['date']} vs computed "
                        f"{m303['resultado'] if p['form'] == '303' else m130['resultado']}")
    return {
        "period": per, "start": start.isoformat(), "end": end.isoformat(),
        "deadline": due.isoformat(), "days_to_deadline": (due - today).days,
        "as_of": today.isoformat(), "warnings": warnings,
        "modelo_303": m303, "modelo_130": m130, "payments": paid, "open_decisions": open_,
    }


def text(r: dict) -> str:
    c3, c1 = r["modelo_303"]["casillas"], r["modelo_130"]["casillas"]
    lines = [f"Quarter {r['period']} ({r['start']} → {r['end']}), deadline {r['deadline']} "
             f"({r['days_to_deadline']} days) — ESTIMATE"]
    lines += [f"  ! {w}" for w in r["warnings"]]
    lines.append(f"303: devengado base [07] {c3['07']} cuota [09] {c3['09']}; intracom [10/11] "
                 f"{c3['10']}/{c3['11']}; ISP [12/13] {c3['12']}/{c3['13']}; total [27] {c3['27']}")
    lines.append(f"     soportado [28/29] {c3['28']}/{c3['29']}; inversión [30/31] {c3['30']}/"
                 f"{c3['31']}; intracom [36/37] {c3['36']}/{c3['37']}; a deducir [45] {c3['45']}")
    lines.append(f"     RESULTADO [71] {r['modelo_303']['resultado']} {r['modelo_303']['sentido']}")
    g = r["modelo_130"]["gastos"]
    lines.append(f"130: ingresos [01] {c1['01']}; gastos [02] {c1['02']} (SS {g['ss']}, "
                 f"deducibles {g['deducibles']}, amortización {g['amortizacion']}, 5% "
                 f"{g['dificil_justificacion']}); neto [03] {c1['03']}; 20% [04] {c1['04']}")
    lines.append(f"     pagos anteriores [05] {c1['05']}; retenciones [06] {c1['06']}; "
                 f"[07] {c1['07']}; minoración [13] {c1['13']}; negativos [15] {c1['15']}")
    lines.append(f"     RESULTADO [19] {r['modelo_130']['resultado']} {r['modelo_130']['sentido']}")
    for p in r["payments"]:
        lines.append(f"Paid: {p['form']} {p['period']} {p['amount']} on {p['date']} [{p['id']}]")
    if r["open_decisions"]:
        lines.append("Open decisions (AEAT payments to classify):")
        lines += [f"  - {o['date']} {o['amount']} EUR [{o['id']}]" for o in r["open_decisions"]]
    return "\n".join(lines)


def show_card(today: date | None = None) -> bool:
    today = today or date.today()
    _, end = bounds(*last_ended(today))
    _, due = next_deadline(today)
    return ((today - end).days <= CARD_DAYS_AFTER_END
            or (due - today).days <= CARD_DAYS_BEFORE_DEADLINE)


def remind(today: date | None = None, dry_run: bool = False) -> str | None:
    """Telegram note ~REMIND_DAYS before a 303 deadline, once per period (130 is exempt)."""
    from fin import notify

    today = today or date.today()
    period, due = next_deadline(today)
    if not 0 <= (due - today).days <= REMIND_DAYS:
        return None
    done = store.get("quarter_reminded", {})
    if done.get(period):
        return None
    r = quarter(period, today)
    msg = (f"Tax deadline {due} ({(due - today).days} days): {period}\n"
           f"303 estimate: {r['modelo_303']['resultado']} EUR {r['modelo_303']['sentido']}\n"
           "Compare with your gestor's figures; `fin quarter` has the casillas.")
    if r["open_decisions"]:
        msg += f"\n{len(r['open_decisions'])} AEAT payment(s) still unclassified."
    notify.send(msg, dry_run)
    if not dry_run:
        store.put("quarter_reminded", {**done, period: today.isoformat()})
    return msg


def book_tax_payment(entry_id: str, form: str, period: str) -> dict:
    """Classify an AEAT payment: 303 clears the IVA liability, 130 is a pago fraccionado."""
    if form not in ("303", "130"):
        raise ValueError("form must be 303 or 130")
    parse_period(period)
    lg = ledger.load()
    t = lg.find(entry_id)
    if t is None:
        raise KeyError(entry_id)
    target = invoices.IVA if form == "303" else invoices.PAGOS_FRACCIONADOS
    ledger.ensure_open(target, "EUR")
    if any(p.account == AEAT_PAYMENTS for p in t.postings):
        ledger.set_account(entry_id, AEAT_PAYMENTS, target)
    elif not any(p.account == target for p in t.postings):
        raise ValueError(f"{entry_id} has no {AEAT_PAYMENTS} posting")
    ledger.update_txn(entry_id, meta={"tax_form": form, "period": period.upper()})
    ledger.commit(f"tax: {t.date} {form} {period}")
    return {"id": entry_id, "form": form, "period": period.upper(), "account": target}
