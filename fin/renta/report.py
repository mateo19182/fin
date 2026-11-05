"""`renta(year)`: the IRPF estimate from the ledger, with warnings, casillas and entry ids.

Never final: it is an estimate to compare with the borrador and the gestor's figures.
"""

from datetime import date
from decimal import Decimal

from fin import activity, balances, config, ledger
from fin.renta import calc, interest, invoices, payslips, securities, stocks
from fin.renta import params_2026 as P
from fin.sync import revolut_invest as ri

ZERO = Decimal(0)
SALARY = "Income:Salary:"
AUTONOMO = "Income:Salary:Autonomo"
REWARDS = "Income:Investment:Rewards"
SS_AUTONOMO = "Expenses:Taxes:SocialSecurity"
AEAT_PAYMENTS = "Expenses:Taxes:IRPF"
FOREIGN_ACCOUNTS = ("Assets:Investment:Revolut:",)
SECTIONS = ("trabajo", "actividad", "ahorro", "base", "cuota", "pagos_a_cuenta", "resultado",
            "modelo_720")


def q(v: Decimal) -> str:
    return str(calc.q(v))


def fig(value: Decimal, casilla: str | None = None, entries: list[str] | None = None) -> dict:
    out: dict = {"value": q(value)}
    if casilla:
        out["casilla"] = P.CASILLAS.get(casilla, casilla)
    if entries is not None:
        out["entries"] = entries
    return out


def _amount(t, account: str, lg: ledger.Ledger) -> Decimal:
    """Sum of the postings of `t` to `account`, in EUR."""
    total = ZERO
    for p in t.postings:
        if p.account == account:
            v = lg.to_eur(p.units.number, p.units.currency, t.date)
            total += v if v is not None else ZERO
    return total


def _starts(t, prefix: str) -> list[str]:
    return sorted({p.account for p in t.postings if p.account.startswith(prefix)})


def employment() -> dict[str, date]:
    """employer -> first day as employee; earlier deposits from it are activity receipts."""
    raw = config.section("renta").get("employment", {})
    return {k: date.fromisoformat(v) for k, v in raw.items()}


def is_activity_receipt(t, account: str) -> bool:
    name = account.removeprefix(SALARY)
    if account == AUTONOMO or t.meta.get("activity") == "true":
        return True
    if "FACTURA" in (t.narration or "").upper():
        return True
    start = employment().get(name)
    return name in invoices.CLIENTS.values() and (start is None or t.date < start)


def _trabajo(lg: ledger.Ledger, txns: list, warnings: list[str]) -> dict:
    per: dict[str, dict] = {}
    last: dict[str, tuple] = {}  # employer -> (irpf rate on base, ss) of the last payslip
    for t in sorted(txns, key=lambda t: t.date):
        for acct in _starts(t, SALARY):
            if is_activity_receipt(t, acct):
                continue
            emp = acct.removeprefix(SALARY)
            e = per.setdefault(emp, {"ingresos": ZERO, "retenciones": ZERO, "ss": ZERO,
                                     "entries": [], "estimated_months": []})
            e["entries"].append(ledger.txn_id(t))
            gross = -_amount(t, acct, lg)
            if "payslip" in t.meta:
                irpf, ss = _amount(t, interest.WITHHELD, lg), _amount(t, payslips.SS_EMPLOYEE, lg)
                base = Decimal(t.meta.get("irpf_base", gross))
                e["ingresos"] += base
                last[emp] = (irpf / base, ss)
            elif emp in last:
                # Gross and SS repeat monthly; the net moves with the exempt in-kind part, which
                # also lowers the IRPF base: net = base * (1 - rate) - ss.
                rate, ss = last[emp]
                net = gross  # the Income leg of an unrewritten deposit is the net pay
                base = calc.q((net + ss) / (1 - rate))
                irpf = base - net - ss
                e["ingresos"] += base
            else:  # no payslip yet: gross the net deposit up with the default rates
                r_irpf, r_ss = ZERO, P.SS_EMPLOYEE_RATE
                gross_est = calc.q(gross / (1 - r_irpf - r_ss))
                irpf = calc.q(gross_est * r_irpf)
                ss = gross_est - gross - irpf
                e["ingresos"] += gross_est
                e["estimated_months"].append(f"{t.date:%Y-%m}")
            e["retenciones"] += irpf
            e["ss"] += ss
    ingresos = sum((e["ingresos"] for e in per.values()), ZERO)
    ss = sum((e["ss"] for e in per.values()), ZERO)
    ret = sum((e["retenciones"] for e in per.values()), ZERO)
    for emp, e in per.items():
        if e["estimated_months"]:
            warnings.append(f"trabajo {emp}: {len(e['estimated_months'])} month(s) before the "
                            "first payslip, estimated with IRPF 0% — send a payslip: "
                            + ", ".join(e["estimated_months"]))
    entries = [i for e in per.values() for i in e["entries"]]
    return {
        "employers": {emp: {"ingresos": q(e["ingresos"]), "retenciones": q(e["retenciones"]),
                            "ss": q(e["ss"]), "estimated_months": e["estimated_months"],
                            "entries": e["entries"]} for emp, e in per.items()},
        "ingresos": fig(ingresos, "trabajo.ingresos", entries),
        "ss": fig(ss, "trabajo.ss"),
        "retenciones": fig(ret, "trabajo.retenciones"),
    }


def _trabajo_calc(t: dict, otras_rentas: Decimal) -> None:
    c = calc.trabajo(Decimal(t["ingresos"]["value"]), Decimal(t["ss"]["value"]), otras_rentas)
    t.update({"otros_gastos": fig(c["otros_gastos"], "trabajo.otros_gastos"),
              "neto": fig(c["neto"], "trabajo.neto"),
              "reduccion": fig(c["reduccion"], "trabajo.reduccion"),
              "otras_rentas": fig(otras_rentas),
              "neto_reducido": fig(c["neto_reducido"])})


def _actividad(lg: ledger.Ledger, txns: list, year: int, rentas_otras: Decimal,
               warnings: list[str]) -> dict:
    ingresos = ret = gastos = pagos = ZERO
    ids: dict[str, list[str]] = {"ingresos": [], "gastos": [], "retenciones": [], "pagos": []}
    estimated: list[str] = []
    for t in txns:
        tid = ledger.txn_id(t)
        for acct in _starts(t, invoices.INCOME + ":"):
            ingresos += -_amount(t, acct, lg)
            ids["ingresos"].append(tid)
        if r := _amount(t, invoices.RETENCIONES, lg):
            ret += r
            ids["retenciones"].append(tid)
        if pf := _amount(t, invoices.PAGOS_FRACCIONADOS, lg):
            pagos += pf
            ids["pagos"].append(tid)
        for acct in _starts(t, SALARY):
            if not is_activity_receipt(t, acct):
                continue
            net = -_amount(t, acct, lg)  # total received = base + IVA - retención
            base = calc.q(net / (1 + P.IVA_GENERAL - P.RETENCION_ACTIVIDAD))
            ingresos += base
            ret += calc.q(base * P.RETENCION_ACTIVIDAD)
            ids["ingresos"].append(tid)
            estimated.append(f"{t.date} {t.payee} {q(net)}")
        if _amount(t, SS_AUTONOMO, lg):
            gastos += _amount(t, SS_AUTONOMO, lg)
            ids["gastos"].append(tid)
    ss = gastos
    costs = [c for c in activity.costs(lg, date(year, 1, 1), date(year, 12, 31))
             if not c["equipment"]]
    amort = activity.amortisation(lg, date(year, 1, 1), date(year, 12, 31))
    deducibles = sum((c["base"] for c in costs), ZERO)
    amortizacion = sum((a["amount"] for a in amort), ZERO)
    gastos += deducibles + amortizacion
    if estimated:
        warnings.append(f"actividad: {len(estimated)} deposit(s) without an invoice PDF, base "
                        f"estimated as total/(1+IVA-7%) — import the invoices: "
                        + "; ".join(estimated))
    inicio = year in P.ACTIVIDAD_INICIO_YEARS
    c = calc.actividad(ingresos, gastos, rentas_otras + ingresos - gastos, inicio)
    return {
        "ingresos": fig(ingresos, "actividad.ingresos", ids["ingresos"]),
        "gastos_ss": fig(ss, "actividad.ss", ids["gastos"]),
        "gastos_deducibles": fig(deducibles, "actividad.gastos_deducibles",
                                 [x["id"] for x in costs]),
        "gastos_deducibles_detalle": [{k: str(v) for k, v in x.items()} for x in costs],
        "amortizacion": fig(amortizacion, "actividad.amortizacion", [a["id"] for a in amort]),
        "amortizacion_detalle": [{k: str(v) for k, v in a.items()} for a in amort],
        "gastos": fig(gastos),
        "neto_previo": fig(c["neto_previo"]),
        "dificil_justificacion": fig(c["dificil_justificacion"], "actividad.dificil_justificacion"),
        "neto": fig(c["neto"], "actividad.rendimiento_neto"),
        "reduccion_rentas_bajas": fig(c["reduccion_rentas_bajas"]),
        "reduccion_inicio": fig(c["reduccion_inicio"], "actividad.reduccion_inicio"),
        "inicio_aplicable": inicio,
        "neto_reducido": fig(c["neto_reducido"]),
        "retenciones": fig(ret, "actividad.retenciones", ids["retenciones"]),
        "pagos_fraccionados": fig(pagos, "actividad.pagos_fraccionados", ids["pagos"]),
        "estimated_receipts": estimated,
    }


def _ahorro(lg: ledger.Ledger, txns: list, year: int, warnings: list[str]) -> dict:
    intr = {"gross": ZERO, "withheld": ZERO, "entries": []}
    div = {"gross": ZERO, "foreign_tax": ZERO, "creditable": ZERO, "entries": [], "estimated": 0,
           "by_country": {}}
    for t in txns:
        tid = ledger.txn_id(t)
        if g := -_amount(t, interest.INCOME, lg):
            w = _amount(t, interest.WITHHELD, lg)
            if not w:
                warnings.append(f"interest {tid} is booked without withholding (net?)")
            intr["gross"] += g
            intr["withheld"] += w
            intr["entries"].append(tid)
        if g := -_amount(t, ri.DIVIDENDS, lg):
            tax = _amount(t, ri.FOREIGN_TAX, lg)
            country = t.meta.get("withholding_country") or securities.withholding(t.narration)[2]
            cap = P.FOREIGN_WITHHOLDING.get(country, {}).get("treaty")
            cred = min(tax, calc.q(g * cap)) if cap is not None else tax
            div["gross"] += g
            div["foreign_tax"] += tax
            div["creditable"] += cred
            div["entries"].append(tid)
            div["estimated"] += t.meta.get("estimated") == "true"
            bc = div["by_country"].setdefault(country, {"gross": ZERO, "tax": ZERO})
            bc["gross"] += g
            bc["tax"] += tax
    if div["estimated"]:
        warnings.append(f"dividends: {div['estimated']} of {len(div['entries'])} gross-ups are "
                        "estimated from the net — import the Revolut P&L statement")
    rows = stocks.load_rows()
    if rows:
        g = stocks.gains(rows, year)
        warnings += [f"stocks: {w}" for w in g["warnings"]]
    else:
        g = {"shares": [], "etf": [], "shares_total": ZERO, "etf_total": ZERO}
        warnings.append("stocks: no Revolut Invest CSV archived under <year>/statements in the "
                        "documents folder — gains/losses unknown")
    redemptions = [ledger.txn_id(t) for t in txns for p in t.postings
                   if p.account.startswith("Assets:Investment:Indexa") and p.units.number < 0]
    if redemptions:
        warnings.append("Indexa: redemption(s) found; take the gain from Indexa's fiscal report: "
                        + ", ".join(redemptions))
    rcm = intr["gross"] + div["gross"]
    ganancias = g["shares_total"] + g["etf_total"]
    c = calc.ahorro(rcm, ganancias, P.PENDING_LOSSES_FROM_PRIOR_YEARS)
    if c["a_compensar_4_anos"]:
        warnings.append(f"ahorro: {q(c['a_compensar_4_anos'])} EUR of losses carry forward")
    return {
        "intereses": fig(intr["gross"], "ahorro.intereses", intr["entries"]),
        "intereses_retencion": fig(intr["withheld"], "ahorro.retenciones"),
        "dividendos": fig(div["gross"], "ahorro.dividendos", div["entries"]),
        "dividendos_impuesto_extranjero": fig(div["foreign_tax"]),
        "dividendos_impuesto_acreditable": fig(div["creditable"]),
        "dividendos_por_pais": {k: {"gross": q(v["gross"]), "tax": q(v["tax"])}
                                for k, v in div["by_country"].items()},
        "dividendos_estimados": div["estimated"],
        "ganancias_acciones": fig(g["shares_total"], "ganancias.acciones"),
        "ganancias_fondos": fig(g["etf_total"], "ganancias.fondos"),
        "ventas": [_strs(s) for s in g["shares"] + g["etf"]],
        "indexa_reembolsos": redemptions,
        "rcm": fig(rcm), "ganancias_netas": fig(ganancias),
        "compensado": fig(c["compensado"]), "a_compensar": fig(c["a_compensar_4_anos"]),
        "base": fig(c["base"], "base.ahorro"),
    }


def _strs(d: dict) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


def _modelo_720(lg: ledger.Ledger, year: int, today: date) -> dict:
    on = min(date(year, 12, 31), today)
    vals = balances.account_values(lg, on)
    total = sum((v for a, v in vals.items() if a.startswith(FOREIGN_ACCOUNTS)), ZERO)
    return {"date": on.isoformat(), "foreign_securities_eur": q(total),
            "threshold": q(P.MODELO_720_THRESHOLD), "required": total > P.MODELO_720_THRESHOLD,
            "note": "Revolut Securities Europe UAB (LT) custody counts as foreign; Indexa (ES) "
                    "and the Spanish branch savings do not. Crypto: modelo 721, out of scope."}


def renta(year: int = P.YEAR, today: date | None = None) -> dict:
    today = today or date.today()
    lg = ledger.load()
    txns = [t for t in lg.transactions if t.date.year == year]
    warnings: list[str] = []
    if year != P.YEAR:
        warnings.append(f"parameters are for {P.YEAR}, not {year}")
    warnings += [f"param: {w}" for w in P.UNCONFIRMED]
    if today <= date(year, 12, 31):
        warnings.append(f"year {year} not finished: figures to {today}")

    trabajo = _trabajo(lg, txns, warnings)
    ahorro = _ahorro(lg, txns, year, warnings)
    rentas_ahorro = Decimal(ahorro["rcm"]["value"]) + Decimal(ahorro["ganancias_netas"]["value"])
    trabajo_neto = Decimal(trabajo["ingresos"]["value"]) - Decimal(trabajo["ss"]["value"])
    actividad = _actividad(lg, txns, year, trabajo_neto + rentas_ahorro, warnings)
    _trabajo_calc(trabajo, Decimal(actividad["neto_reducido"]["value"]) + rentas_ahorro)

    aeat = [(ledger.txn_id(t), q(_amount(t, AEAT_PAYMENTS, lg)), t.date.isoformat())
            for t in txns if _amount(t, AEAT_PAYMENTS, lg)]
    if aeat:
        warnings.append("tax payments in Expenses:Taxes:IRPF are not counted as pagos a cuenta "
                        "(303 IVA / Renta 2025 / 130?): "
                        + "; ".join(f"{d} {a}" for _, a, d in aeat))

    # Referral bonuses and free-share rewards: ganancias patrimoniales no derivadas de
    # transmisión, taxed in the general base.
    rewards = [t for t in txns if _starts(t, REWARDS)]
    otras = sum((-_amount(t, a, lg) for t in rewards for a in _starts(t, REWARDS)), ZERO)
    if otras:
        warnings.append(f"otras ganancias: {q(otras)} EUR of referral/rewards added to the general "
                        "base (ganancias patrimoniales no derivadas de transmisión)")
    bl_general = max(Decimal(trabajo["neto_reducido"]["value"])
                     + Decimal(actividad["neto_reducido"]["value"]) + otras, ZERO)
    bl_ahorro = Decimal(ahorro["base"]["value"])
    cu = calc.cuotas(bl_general, bl_ahorro, P.MINIMO_ESTATAL, P.MINIMO_GALICIA)
    di = calc.doble_imposicion(Decimal(ahorro["dividendos_impuesto_acreditable"]["value"]),
                               Decimal(ahorro["dividendos"]["value"]), cu["integra_ahorro"],
                               bl_ahorro)
    pagos = {
        "trabajo": Decimal(trabajo["retenciones"]["value"]),
        "actividad": Decimal(actividad["retenciones"]["value"]),
        "pagos_fraccionados": Decimal(actividad["pagos_fraccionados"]["value"]),
        "ahorro": Decimal(ahorro["intereses_retencion"]["value"]),
    }
    total_pagos = sum(pagos.values(), ZERO)
    smi = calc.deduccion_smi(Decimal(trabajo["ingresos"]["value"]),
                             Decimal(actividad["neto_reducido"]["value"]) + rentas_ahorro,
                             cu["integra"], Decimal(trabajo["neto_reducido"]["value"]), bl_general)
    cuota_liquida = max(cu["integra"] - di["deduccion"] - smi, ZERO)
    resultado = cuota_liquida - total_pagos
    return {
        "year": year, "as_of": today.isoformat(), "warnings": warnings,
        "trabajo": trabajo, "actividad": actividad, "ahorro": ahorro,
        "otras_ganancias": fig(otras, entries=[ledger.txn_id(t) for t in rewards]),
        "base": {"general": fig(bl_general, "base.general"),
                 "ahorro": fig(bl_ahorro, "base.ahorro"),
                 "minimo_estatal": fig(P.MINIMO_ESTATAL, "minimo.estatal"),
                 "minimo_autonomico": fig(P.MINIMO_GALICIA, "minimo.autonomico")},
        "cuota": {
            "estatal": {k: q(v) for k, v in cu["estatal"].items()},
            "autonomica": {k: q(v) for k, v in cu["autonomica"].items()},
            "integra_estatal": fig(cu["estatal"]["total"], "cuota.integra_estatal"),
            "integra_autonomica": fig(cu["autonomica"]["total"], "cuota.integra_autonomica"),
            "integra": fig(cu["integra"]),
            "doble_imposicion": {**{k: str(v) for k, v in di.items()},
                                 "casilla": P.CASILLAS["deduccion.doble_imposicion"]},
            "deduccion_smi": fig(smi, "trabajo.deduccion_smi"),
            "liquida": fig(cuota_liquida, "cuota.resultante"),
        },
        "pagos_a_cuenta": {**{k: q(v) for k, v in pagos.items()},
                           "total": fig(total_pagos, "pagos_a_cuenta")},
        "resultado": {**fig(resultado, "resultado"),
                      "sentido": "a pagar" if resultado > 0 else "a devolver" if resultado < 0
                      else "cero"},
        "modelo_720": _modelo_720(lg, year, today),
    }


def text(r: dict) -> str:
    lines = [f"Renta {r['year']} (estimate as of {r['as_of']}) — NOT FINAL"]
    lines += [f"  ! {w}" for w in r["warnings"]]
    t, a, s = r["trabajo"], r["actividad"], r["ahorro"]
    lines.append("Trabajo: " + ", ".join(
        f"{e} {v['ingresos']}" + (" (est.)" if v["estimated_months"] else "")
        for e, v in t["employers"].items()) or "Trabajo: none")
    v = _vals
    lines.append(f"  íntegros {v(t, 'ingresos')}  SS {v(t, 'ss')}  otros gastos "
                 f"{v(t, 'otros_gastos')}  reducción {v(t, 'reduccion')}  "
                 f"neto reducido {v(t, 'neto_reducido')}  retenciones {v(t, 'retenciones')}")
    lines.append(f"Actividad: ingresos {v(a, 'ingresos')}  gastos {v(a, 'gastos')} (SS "
                 f"{v(a, 'gastos_ss')}, deducibles {v(a, 'gastos_deducibles')}, amortización "
                 f"{v(a, 'amortizacion')})"
                 f"  difícil just. {v(a, 'dificil_justificacion')}  red. inicio "
                 f"{v(a, 'reduccion_inicio')}  neto reducido {v(a, 'neto_reducido')}"
                 f"  retenciones {v(a, 'retenciones')}")
    lines.append(f"Ahorro: intereses {v(s, 'intereses')} (ret. {v(s, 'intereses_retencion')})"
                 f"  dividendos {v(s, 'dividendos')} "
                 f"(ext. {v(s, 'dividendos_impuesto_extranjero')})"
                 f"  ganancias acciones {v(s, 'ganancias_acciones')}  fondos/ETF "
                 f"{v(s, 'ganancias_fondos')}  base {v(s, 'base')}")
    b, c = r["base"], r["cuota"]
    lines.append(f"Base liquidable general {b['general']['value']}  ahorro {b['ahorro']['value']}")
    lines.append(f"Cuota íntegra estatal {c['integra_estatal']['value']} + autonómica "
                 f"{c['integra_autonomica']['value']} = {c['integra']['value']}; doble imposición "
                 f"-{c['doble_imposicion']['deduccion']}; deducción SMI "
                 f"-{c['deduccion_smi']['value']}; líquida {c['liquida']['value']}")
    p = r["pagos_a_cuenta"]
    lines.append(f"Pagos a cuenta {p['total']['value']} (trabajo {p['trabajo']}, actividad "
                 f"{p['actividad']}, ahorro {p['ahorro']}, fraccionados {p['pagos_fraccionados']})")
    lines.append(f"RESULTADO ESTIMADO: {r['resultado']['value']} EUR {r['resultado']['sentido']}")
    m = r["modelo_720"]
    lines.append(f"Modelo 720: foreign securities {m['foreign_securities_eur']} EUR at {m['date']}"
                 f" → {'REQUIRED' if m['required'] else 'not required'} (> {m['threshold']})")
    return "\n".join(lines)


def _vals(section: dict, key: str) -> str:
    return section[key]["value"]


def detail(r: dict, section: str) -> dict:
    if section not in SECTIONS:
        raise KeyError(f"section {section!r}; one of {', '.join(SECTIONS)}")
    return r[section]
