from decimal import Decimal as D

from fin.renta import calc
from fin.renta import params_2026 as P


def test_state_scale_matches_the_published_cuotas():
    # Cuota íntegra at each tramo limit, Manual Renta (art. 63 LIRPF).
    assert calc.scale(D("12450"), P.STATE_SCALE) == D("1182.75")
    assert calc.scale(D("20200"), P.STATE_SCALE) == D("2112.75")
    assert calc.scale(D("35200"), P.STATE_SCALE) == D("4362.75")
    assert calc.scale(D("60000"), P.STATE_SCALE) == D("8950.75")
    assert calc.scale(D("300000"), P.STATE_SCALE) == D("62950.75")
    assert calc.scale(D("0"), P.STATE_SCALE) == 0


def test_galicia_scale_matches_the_published_cuotas():
    assert calc.q(calc.scale(D("12985.35"), P.GALICIA_SCALE)) == D("1168.68")
    assert calc.q(calc.scale(D("21068.60"), P.GALICIA_SCALE)) == D("2110.38")
    assert calc.q(calc.scale(D("35200"), P.GALICIA_SCALE)) == D("4215.96")
    assert calc.q(calc.scale(D("60000"), P.GALICIA_SCALE)) == D("8779.16")


def test_renta_2025_cuotas_reproduced_from_the_filed_return():
    """Modelo 100 Renta 2025 (filed 2026-05-08): BL general 7.696,42 (0505), BL ahorro 12,32
    (0510), mínimos 5.550 / 5.789 -> cuota estatal general 203,91 (0532), autonómica 171,67
    (0533), ahorro 1,17 + 1,17 (0540/0541), íntegra estatal 205,08 (0545), autonómica 172,84
    (0546). The 2025 and 2026 scales and mínimos are identical, so params_2026 reproduces it."""
    c = calc.cuotas(D("7696.42"), D("12.32"), P.MINIMO_ESTATAL, P.MINIMO_GALICIA)
    assert c["estatal"]["general"] == D("203.91")
    assert c["autonomica"]["general"] == D("171.67")
    assert c["estatal"]["ahorro"] == D("1.17") and c["autonomica"]["ahorro"] == D("1.17")
    assert c["estatal"]["total"] == D("205.08") and c["autonomica"]["total"] == D("172.84")
    assert c["integra"] == D("377.92")


def test_renta_2025_actividad_reproduced():
    """Renta 2025: ingresos 11.104 + 250, gastos 341,68 + 167,19 -> difícil justificación
    542,26 (529,76 + 12,50), RN 10.302,87 (0231), reducción rentas bajas 682,35 (0233, rentas
    10.315,19 incl. 12,32 of interest), reducción inicio 1.924,10 (0234), RN reducido 7.696,42."""
    a = calc.actividad(D("11354"), D("508.87"), D("10302.87") + D("12.32"), inicio=True)
    assert a["dificil_justificacion"] == D("542.26")
    assert a["neto"] == D("10302.87")
    assert a["reduccion_rentas_bajas"] == D("682.35")
    assert a["reduccion_inicio"] == D("1924.10")
    assert a["neto_reducido"] == D("7696.42")


def test_actividad_caps_and_conditions():
    a = calc.actividad(D("100000"), D("0"), D("100000"), inicio=False)
    assert a["dificil_justificacion"] == D("2000")  # 5% capped at 2.000
    assert a["reduccion_inicio"] == 0 and a["reduccion_rentas_bajas"] == 0
    loss = calc.actividad(D("100"), D("500"), D("0"), inicio=True)
    assert loss["dificil_justificacion"] == 0 and loss["neto_reducido"] == D("-400")


def test_trabajo_reduction_needs_low_other_income():
    t = calc.trabajo(D("10000"), D("650"))
    assert t["otros_gastos"] == D("2000") and t["neto"] == D("7350")
    assert t["reduccion"] == D("7302") and t["neto_reducido"] == D("48")
    # the same salary next to 18.508 of activity income: no art. 20 reduction
    assert calc.trabajo(D("10000"), D("650"), D("18508"))["reduccion"] == 0
    # phase-out: neto previo 16.000 -> 7.302 - 1,75 x 1.148 = 5.293
    assert calc.trabajo(D("16000"), D("0"))["reduccion"] == D("5293")
    # neto previo 18.000 -> 2.364,34 - 1,14 x 326,48 = 1.992,15
    assert calc.trabajo(D("18000"), D("0"))["reduccion"] == D("1992.15")
    assert calc.trabajo(D("25000"), D("0"))["reduccion"] == 0
    assert calc.trabajo(D("1500"), D("100"))["otros_gastos"] == D("1400")  # cannot go negative


def test_deduccion_smi():
    assert calc.deduccion_smi(D("17094"), D("0"), D("3000"), D("8000"), D("8000")) == D("590.89")
    assert calc.deduccion_smi(D("18094"), D("0"), D("3000"), D("8000"), D("8000")) == D("390.89")
    assert calc.deduccion_smi(D("17094"), D("7000"), D("3000"), D("8000"), D("8000")) == 0
    # capped at the share of the cuota attributable to the salary
    assert calc.deduccion_smi(D("17094"), D("0"), D("100"), D("4000"), D("8000")) == D("50")


def test_ahorro_compensation_25_percent():
    a = calc.ahorro(D("1000"), D("-2000"))
    assert a["compensado"] == D("250") and a["base"] == D("750")
    assert a["a_compensar_4_anos"] == D("1750")
    b = calc.ahorro(D("-100"), D("1000"))
    assert b["compensado"] == D("100") and b["base"] == D("900") and b["a_compensar_4_anos"] == 0
    c = calc.ahorro(D("100"), D("50"))
    assert c["base"] == D("150") and c["compensado"] == 0
    d = calc.ahorro(D("100"), D("500"), pendientes=D("200"))  # prior-year losses first
    assert d["base"] == D("400")


def test_minimo_spills_into_savings_base():
    c = calc.cuotas(D("3000"), D("10000"), D("5550"), D("5789"))
    assert c["estatal"]["minimo_general"] == D("3000")
    assert c["estatal"]["minimo_ahorro"] == D("2550")
    assert c["estatal"]["general"] == 0
    # ahorro: 6.000 x 9,5% + 4.000 x 10,5% = 990 minus 2.550 x 9,5% = 242,25
    assert c["estatal"]["ahorro"] == D("747.75")
    assert c["autonomica"]["minimo_ahorro"] == D("2789")


def test_doble_imposicion_limit():
    d = calc.doble_imposicion(D("26.38"), D("100"), D("1900"), D("10000"))
    assert d["tipo_medio_ahorro"] == D("0.19") and d["limite"] == D("19.00")
    assert d["deduccion"] == D("19.00")
    assert calc.doble_imposicion(D("1.50"), D("10"), D("0"), D("0"))["deduccion"] == 0
