"""IRPF parameters for tax year 2026 (Renta filed spring 2027), resident in Galicia.

Every block cites its source. STATUS says whether the figure is confirmed for 2026 or is the
latest published one (then the report flags it: "verify for 2026"). To prepare 2027, copy this
module, update the values and the sources, and point `fin.renta.params` at it.
"""

from decimal import Decimal as D

YEAR = 2026

# Escala general estatal, art. 63 LIRPF (Ley 35/2006, consolidated text of 2026-10-07).
# https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764#a63
# STATUS: CONFIRMED 2026 (last amended by Ley 11/2020).
# Tramos: (base hasta, tipo). Each tramo applies to the slice up to its limit.
STATE_SCALE = [(D("12450"), D("0.095")), (D("20200"), D("0.12")), (D("35200"), D("0.15")),
               (D("60000"), D("0.185")), (D("300000"), D("0.225")), (None, D("0.245"))]

# Escala autonómica de Galicia, art. 4 Decreto Legislativo 1/2011 (consolidated 2026-03-27).
# https://www.boe.es/eli/es-ga/dlg/2011/07/28/1/con
# Hacienda "Tributación autonómica, medidas 2026" (2026-09-23) lists no Galicia tariff change:
# https://www.hacienda.gob.es/sgfal/financiacionterritorial/autonomica/capitulo-ii-tributacion-autonomica-2026.pdf
# STATUS: CONFIRMED 2026 (Ley 5/2025 de Galicia only added a talidomida deduction).
GALICIA_SCALE = [(D("12985.35"), D("0.09")), (D("21068.60"), D("0.1165")),
                 (D("35200"), D("0.149")), (D("60000"), D("0.184")), (None, D("0.225"))]

# Escala del ahorro, arts. 66 and 76 LIRPF: full rate; state and autonomic halves are 50% each.
# https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764#a66
# STATUS: CONFIRMED 2026 (30% top tramo since 2025, Ley 7/2024 DF 7; no later change).
SAVINGS_SCALE = [(D("6000"), D("0.19")), (D("50000"), D("0.21")), (D("200000"), D("0.23")),
                 (D("300000"), D("0.27")), (None, D("0.30"))]

# Mínimo del contribuyente, art. 57 LIRPF (estatal) and Galicia's own amount (art. 4 bis.1.a
# DLeg 1/2011). Taxpayer < 65, no descendants/ascendants. Matches Renta 2025 casillas 0511/0512.
# STATUS: CONFIRMED 2026 (both unchanged in the 2026 consolidations).
MINIMO_ESTATAL = D("5550")
MINIMO_GALICIA = D("5789")

# Rendimientos del trabajo: gastos deducibles art. 19.2 (SS + 2.000 "otros gastos", letter f)
# and reducción art. 20 LIRPF (RDL 4/2024, unchanged for 2026). The reduction is computed on
# the rendimiento neto BEFORE the 2.000 (letters a-e only) and requires other non-exempt
# income <= 6.500 €.  https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764#a20
# STATUS: CONFIRMED 2026.
TRABAJO_OTROS_GASTOS = D("2000")
TRABAJO_REDUCCION = {  # (rendimiento neto <=, full amount) then the linear phase-out
    "full_until": D("14852"), "full": D("7302"),
    "slope1_until": D("17673.52"), "slope1": D("1.75"),
    "slope2_until": D("19747.50"), "slope2_base": D("2364.34"), "slope2": D("1.14"),
    "otras_rentas_max": D("6500"),
}
# DA 61ª LIRPF as rewritten by RDL 5/2026 (BOE 2026-02-19, art. 28), effective 2026-01-01:
# deducción en cuota for employees with rendimientos íntegros del trabajo < 20.048,45 and other
# non-exempt income <= 6.500: 590,89 if RIT <= 17.094 (SMI 2026), then 590,89 - 0,2 x (RIT -
# 17.094). Capped at the share of the cuotas íntegras attributable to those rendimientos.
# https://sede.agenciatributaria.gob.es/static_files/Sede/Actualidad/Novedades/2026/BOLINFORM%20_RDL_5_2026.pdf
# STATUS: CONFIRMED 2026. Casilla 0414 (Renta 2025 numbering).
TRABAJO_DEDUCCION_SMI = {"full_until": D("17094"), "full": D("590.89"), "until": D("20048.45"),
                         "slope": D("0.2"), "otras_rentas_max": D("6500")}

# Actividades económicas, estimación directa simplificada.
# art. 30.2.4ª LIRPF + art. 30 RIRPF: gastos de difícil justificación 5% of the positive
# rendimiento neto previo, max 2.000 €/year.  https://www.boe.es/buscar/act.php?id=BOE-A-2007-6820#a30
# art. 32.3 LIRPF: reducción por inicio de actividad 20% in the first positive year and the next
# (cap: rendimiento of 100.000 €). The activity started 2025-09-04 with positive net in 2025,
# so 2026 is the second and last year.  art. 32.2.3º: reducción for rentas no exentas < 12.000.
# art. 32.2.3º: reducción for rentas no exentas (all, incl. the activity) < 12.000; joint cap
# with the art. 20 reduction 3.700 €.  STATUS: CONFIRMED 2026 (no change in the consolidations).
ACTIVIDAD_DIFICIL_JUSTIFICACION = D("0.05")
ACTIVIDAD_DIFICIL_JUSTIFICACION_MAX = D("2000")
ACTIVIDAD_INICIO_REDUCCION = D("0.20")
ACTIVIDAD_INICIO_CAP = D("100000")
ACTIVIDAD_INICIO_YEARS = (2025, 2026)
ACTIVIDAD_RENTAS_BAJAS = {"full_until": D("8000"), "full": D("1620"), "until": D("12000"),
                          "slope": D("0.405")}

# Amortisation, estimación directa simplificada: linear, "tabla de amortización simplificada"
# (Orden de 27 de marzo de 1998, BOE-A-1998-7200), group 5 "Equipos para tratamiento de la
# información y sistemas y programas informáticos": coeficiente lineal máximo 26%, período máximo
# 10 años. https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/folleto-actividades-economicas/3-impuesto-sobre-renta-personas-fisicas/3_5-estimacion-directa-simplificada/3_5_4-tabla-amortizacion-simplificada.html
# The gestor's Renta 2025 shows no amortisation line (the laptop is a 2026 purchase), so the
# method could not be copied from a filed return: the maximum coefficient is used, prorated by
# days in the purchase year (art. 3.1 RIS). STATUS: table in force; "verify with the gestor".
AMORTIZACION_EQUIPOS = D("0.26")
AMORTIZACION_EQUIPOS_YEARS_MAX = 10

# IVA on purchases (modelo 303, Orden HFP/1124/2022 form; AEAT instructions 2025):
# https://sede.agenciatributaria.gob.es/Sede/todas-gestiones/impuestos-tasas/iva/modelo-303-iva-autoliquidacion_/instrucciones-2025.html
# - Spanish supplier with IVA: cuotas soportadas deducibles, casillas 28/29 (bienes de inversión
#   30/31). Transport (train, flights, taxi/VTC) carries 10%, the rest 21%.
# - EU supplier, no VAT charged (needs the customer's NIF-IVA/ROI): adquisición intracomunitaria
#   de servicios, devengado 10/11 and deducible 36/37 (art. 84.Uno.2º LIVA); also modelo 349.
# - Non-EU supplier, no VAT charged: inversión del sujeto pasivo, devengado 12/13 and deducible
#   28/29 (art. 84.Uno.2º LIVA; AEAT "Prestaciones de servicios" exterior guide).
# - "oss": the foreign supplier charged Spanish VAT under the OSS/B2C regime (no customer VAT
#   number): no ISP, the VAT is not deductible and the expense counts gross for IRPF.
# Vehicle fuel: IVA deductible 50% by presumption (art. 95.Tres.2ª LIVA) → deductible_pct 50.
IVA_RATES = {"es": D("0.21"), "transport": D("0.10")}
CASILLAS_303 = {
    "devengado.base": "07", "devengado.tipo": "08", "devengado.cuota": "09",
    "intracom.base": "10", "intracom.cuota": "11", "isp.base": "12", "isp.cuota": "13",
    "total_devengado": "27",
    "soportado.base": "28", "soportado.cuota": "29",
    "soportado_inversion.base": "30", "soportado_inversion.cuota": "31",
    "intracom_deducible.base": "36", "intracom_deducible.cuota": "37",
    "total_deducir": "45", "resultado_regimen_general": "46", "suma_resultados": "64",
    "atribuible_estado": "66", "resultado_autoliquidacion": "69", "resultado": "71",
}
# Modelo 130 (AEAT instructions, same source family):
# https://sede.agenciatributaria.gob.es/Sede/impuestos-tasas/impuesto-sobre-renta-personas-fisicas/modelo-130-irpf______esionales-estimacion-directa-fraccionado_/instrucciones.html
CASILLAS_130 = {
    "ingresos": "01", "gastos": "02", "rendimiento_neto": "03", "pct20": "04",
    "pagos_anteriores": "05", "retenciones": "06", "pago_previo": "07", "suma": "12",
    "minoracion": "13", "diferencia": "14", "negativos_anteriores": "15", "vivienda": "16",
    "total": "17", "complementaria": "18", "resultado": "19",
}
# art. 110.3.c) RIRPF minoración of the 130 by the previous year's rendimiento neto de
# actividades: 100 (<= 9.000), 75 (<= 10.000), 50 (<= 11.000), 25 (<= 12.000). Renta 2025 casilla
# 0224 total: 10.065,37 + 237,50 = 10.302,87 → 50 €/quarter in 2026.
RENTA_2025_RENDIMIENTO_NETO_ACTIVIDAD = D("10302.87")
MINORACION_130 = [(D("9000"), D("100")), (D("10000"), D("75")), (D("11000"), D("50")),
                  (D("12000"), D("25"))]
# art. 109.2 RIRPF: no 130 due when >= 70% of the previous year's activity income had retención.
MODELO_130_RETENCION_EXEMPT_SHARE = D("0.70")
# Deadlines (AEAT instructions 303/130): 1-20 April, July, October; 1-30 January.
QUARTER_DEADLINES = {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 30)}

# Retenciones: capital mobiliario 19% (art. 101.4 LIRPF), actividades profesionales 15% or 7%
# in the start year and the two following (art. 95.1 RIRPF), trabajo per tables (art. 80 ss.).
# Modelo 130 not required when >= 70% of the activity income had retención (art. 109.2 RIRPF).
# https://www.boe.es/buscar/act.php?id=BOE-A-2007-6820
# STATUS: CONFIRMED 2026.
RETENCION_AHORRO = D("0.19")
RETENCION_ACTIVIDAD = D("0.07")  # new activity: 7% until the third year
IVA_GENERAL = D("0.21")
SS_EMPLOYEE_RATE = D("0.0650")  # CC 4.70 + MEI 0.15 + FP 0.10 + desempleo 1.55 (payslips 2026)

# Foreign dividend withholding. `default` is what the paying country withholds at source for
# a Revolut (Revolut Securities Europe UAB) customer; `treaty` is the Spain treaty cap, the most
# that counts for the deducción por doble imposición (art. 80 LIRPF); the excess is reclaimed
# abroad, not deducted in Spain. US: 15% with W-8BEN on file (signed).
# DE 25% + 5.5% Soli = 26.375% (§43a EStG); IT 26%; NL 15%; FR 12.8% (non-resident
# individuals, fully creditable); TW 21% (no treaty in force with Spain).
# Treaty rates: https://taxsummaries.pwc.com/ (DE, IT, NL, FR); US Protocolo 2019 BOE 2019-10-23.
# Revolut help: EU withholding "depends on the origin country, up to 35%"; no relief at source.
# STATUS: statutory rates CONFIRMED 2026; what Revolut actually withheld is ESTIMATED until the
# Revolut P&L statement shows the exact figure (the AIXA/ENR1 nets match 26.375%, NXPI/BSI 15%).
FOREIGN_WITHHOLDING = {
    "US": {"default": D("0.15"), "treaty": D("0.15")},
    "DE": {"default": D("0.26375"), "treaty": D("0.15")},
    "IT": {"default": D("0.26"), "treaty": D("0.15")},
    "NL": {"default": D("0.15"), "treaty": D("0.15")},
    "FR": {"default": D("0.128"), "treaty": D("0.15")},
    "TW": {"default": D("0.21"), "treaty": None},
}

# Base del ahorro compensation, art. 49 LIRPF: a negative balance of capital mobiliario or of
# ganancias/pérdidas offsets up to 25% of the other's positive balance; the rest carries 4 years.
# https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764#a49  STATUS: in force.
AHORRO_CROSS_COMPENSATION = D("0.25")
PENDING_LOSSES_FROM_PRIOR_YEARS = D("0")  # Renta 2025 shows none

# Modelo 720 (Orden HAP/72/2013): foreign securities worth > 50.000 € at 31 Dec.
# https://sede.agenciatributaria.gob.es/Sede/declaraciones-informativas/modelo-720.html
# STATUS: in force. Crypto has its own modelo 721 (out of scope).
MODELO_720_THRESHOLD = D("50000")

# Casillas del modelo 100, Renta 2025 numbering (Orden HAC/277/2026, BOE 2026-03-27).
# https://www.boe.es/boe/dias/2026/03/27/pdfs/BOE-A-2026-7041.pdf
# STATUS: LATEST PUBLISHED (2025); verify against the Renta 2026 order (March 2027).
CASILLAS = {
    "trabajo.ingresos": "0003", "trabajo.ss": "0013", "trabajo.otros_gastos": "0019",
    "trabajo.neto": "0022", "trabajo.reduccion": "0023", "trabajo.retenciones": "0596",
    "trabajo.deduccion_smi": "0414",
    "ahorro.intereses": "0027", "ahorro.dividendos": "0029", "ahorro.retenciones": "0597",
    "actividad.ingresos": "0171", "actividad.ss": "0186", "actividad.otros_gastos": "0202",
    "actividad.gastos_deducibles": "0202", "actividad.amortizacion": "0216",
    "actividad.dificil_justificacion": "0222", "actividad.rendimiento_neto": "0224",
    "actividad.reduccion_rentas_bajas": "0233", "actividad.reduccion_inicio": "0234",
    "actividad.retenciones": "0599", "actividad.pagos_fraccionados": "0604",
    "ganancias.acciones": "0326-0340", "ganancias.fondos": "0310-0325",
    "ganancias.fondos_retenciones": "0603",
    "base.general": "0435", "base.ahorro": "0460",
    "minimo.estatal": "0511", "minimo.autonomico": "0512",
    "cuota.integra_estatal": "0545", "cuota.integra_autonomica": "0546",
    "deduccion.doble_imposicion": "0588", "cuota.resultante": "0595",
    "pagos_a_cuenta": "0609", "resultado": "0670",
}

# Figures above that are not yet confirmed for 2026; the report repeats these warnings.
UNCONFIRMED = [
    "Casilla numbers are from Renta 2025 (Orden HAC/277/2026); check the Renta 2026 order",
    "Foreign dividend withholding rates are statutory defaults, not Revolut's statement",
    "Laptop amortised at the simplified-table maximum (26%/year, prorated); the gestor's Renta "
    "2025 has no amortisation to copy — confirm the method and casilla 0216 with the gestor",
]
