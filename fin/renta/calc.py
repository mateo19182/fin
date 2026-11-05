"""Pure IRPF arithmetic on Decimals. No ledger access; every input is explicit.

Amounts are rounded to the cent only where the modelo 100 does (each cuota figure).
"""

from decimal import ROUND_HALF_UP, Decimal

from fin.renta import params_2026 as P

ZERO = Decimal(0)
CENT = Decimal("0.01")


def q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def scale(base: Decimal, tramos: list[tuple[Decimal | None, Decimal]]) -> Decimal:
    """Progressive tax on `base`: each tramo's rate applies to the slice up to its limit."""
    tax, lower = ZERO, ZERO
    for limit, rate in tramos:
        if base <= lower:
            break
        upper = base if limit is None else min(base, limit)
        tax += (upper - lower) * rate
        lower = upper if limit is None else limit
    return tax


def half_scale(tramos):
    return [(limit, rate / 2) for limit, rate in tramos]


def trabajo(ingresos: Decimal, ss: Decimal, otras_rentas: Decimal = ZERO) -> dict:
    """Rendimiento neto reducido del trabajo (arts. 17-20 LIRPF).

    The art. 20 reduction is measured on the net before the 2.000 "otros gastos" and needs
    other non-exempt income (`otras_rentas`) <= 6.500."""
    neto_previo = ingresos - ss
    otros = min(P.TRABAJO_OTROS_GASTOS, max(neto_previo, ZERO))
    neto = neto_previo - otros
    r = P.TRABAJO_REDUCCION
    if otras_rentas > r["otras_rentas_max"] or neto_previo >= r["slope2_until"]:
        red = ZERO
    elif neto_previo <= r["full_until"]:
        red = r["full"]
    elif neto_previo <= r["slope1_until"]:
        red = r["full"] - r["slope1"] * (neto_previo - r["full_until"])
    else:
        red = r["slope2_base"] - r["slope2"] * (neto_previo - r["slope1_until"])
    red = min(max(q(red), ZERO), max(neto, ZERO))
    return {"ingresos": ingresos, "ss": ss, "otros_gastos": otros, "neto_previo": neto_previo,
            "neto": neto, "reduccion": red, "neto_reducido": neto - red}


def deduccion_smi(ingresos_trabajo: Decimal, otras_rentas: Decimal, cuota_integra: Decimal,
                  neto_trabajo: Decimal, bl_general: Decimal) -> Decimal:
    """DA 61ª LIRPF (RDL 5/2026): deducción en cuota for low salaries, 2026 onwards."""
    d = P.TRABAJO_DEDUCCION_SMI
    if ingresos_trabajo <= 0 or otras_rentas > d["otras_rentas_max"] or \
            ingresos_trabajo >= d["until"]:
        return ZERO
    amount = d["full"] if ingresos_trabajo <= d["full_until"] else \
        d["full"] - d["slope"] * (ingresos_trabajo - d["full_until"])
    share = cuota_integra * neto_trabajo / bl_general if bl_general > 0 else ZERO
    return max(min(q(amount), q(share)), ZERO)


def actividad(ingresos: Decimal, gastos: Decimal, rentas_totales: Decimal,
              inicio: bool) -> dict:
    """Rendimiento neto reducido, estimación directa simplificada (arts. 28-32 LIRPF)."""
    previo = ingresos - gastos
    dificil = min(max(previo, ZERO) * P.ACTIVIDAD_DIFICIL_JUSTIFICACION,
                  P.ACTIVIDAD_DIFICIL_JUSTIFICACION_MAX) if previo > 0 else ZERO
    neto = previo - q(dificil)
    rb = P.ACTIVIDAD_RENTAS_BAJAS
    if neto > 0 and rentas_totales < rb["until"]:
        bajas = rb["full"] if rentas_totales <= rb["full_until"] else \
            rb["full"] - rb["slope"] * (rentas_totales - rb["full_until"])
        bajas = min(q(bajas), neto)
    else:
        bajas = ZERO
    tras_bajas = neto - bajas
    inicio_red = q(min(tras_bajas, P.ACTIVIDAD_INICIO_CAP) * P.ACTIVIDAD_INICIO_REDUCCION) \
        if inicio and tras_bajas > 0 else ZERO
    return {"ingresos": ingresos, "gastos": gastos, "neto_previo": previo,
            "dificil_justificacion": q(dificil), "neto": neto, "reduccion_rentas_bajas": bajas,
            "reduccion_inicio": inicio_red, "neto_reducido": tras_bajas - inicio_red}


def ahorro(rcm: Decimal, ganancias: Decimal, pendientes: Decimal = ZERO) -> dict:
    """Base imponible del ahorro with art. 49 compensation. `rcm` = interest + dividends,
    `ganancias` = net realised gains (negative = losses), `pendientes` = prior-year losses."""
    gp = ganancias - pendientes
    comp = ZERO
    if rcm < 0 < gp:
        comp = min(-rcm, gp * P.AHORRO_CROSS_COMPENSATION)
        base, carry = gp - comp, -rcm - comp
    elif gp < 0 < rcm:
        comp = min(-gp, rcm * P.AHORRO_CROSS_COMPENSATION)
        base, carry = rcm - comp, -gp - comp
    else:
        base = max(rcm + gp, ZERO)
        carry = -(rcm + gp) if rcm + gp < 0 else ZERO
    return {"rcm": rcm, "ganancias": ganancias, "pendientes_aplicadas": pendientes,
            "compensado": q(comp), "base": q(base), "a_compensar_4_anos": q(carry)}


def cuotas(bl_general: Decimal, bl_ahorro: Decimal, minimo_estatal: Decimal,
           minimo_auto: Decimal) -> dict:
    """Cuotas íntegras estatal y autonómica (arts. 62-66 and 73-76 LIRPF).

    The mínimo is taxed at the scale and subtracted; what exceeds the general base moves to
    the savings base (art. 56.2)."""
    out = {}
    for part, tramos, minimo in (("estatal", P.STATE_SCALE, minimo_estatal),
                                 ("autonomica", P.GALICIA_SCALE, minimo_auto)):
        m_gen = min(minimo, bl_general)
        m_aho = min(minimo - m_gen, bl_ahorro)
        half = half_scale(P.SAVINGS_SCALE)
        general = q(scale(bl_general, tramos)) - q(scale(m_gen, tramos))
        savings = q(scale(bl_ahorro, half)) - q(scale(m_aho, half))
        out[part] = {"general": general, "ahorro": savings, "total": general + savings,
                     "minimo_general": m_gen, "minimo_ahorro": m_aho}
    out["integra"] = out["estatal"]["total"] + out["autonomica"]["total"]
    out["integra_general"] = out["estatal"]["general"] + out["autonomica"]["general"]
    out["integra_ahorro"] = out["estatal"]["ahorro"] + out["autonomica"]["ahorro"]
    return out


def doble_imposicion(foreign_tax_creditable: Decimal, foreign_income: Decimal,
                     cuota_ahorro: Decimal, bl_ahorro: Decimal) -> dict:
    """art. 80 LIRPF: min(tax paid abroad, tipo medio efectivo del ahorro x foreign income)."""
    tipo = (cuota_ahorro / bl_ahorro) if bl_ahorro else ZERO
    limite = q(foreign_income * tipo)
    return {"pagado": q(foreign_tax_creditable),
            "tipo_medio_ahorro": tipo.quantize(Decimal("0.0001")),
            "limite": limite, "deduccion": min(q(foreign_tax_creditable), limite)}
