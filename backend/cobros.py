"""Cobros: lo que le pagaron al usuario sus inversiones (dividendos, cupones, intereses).

POR QUÉ EXISTE (2026-10-22). Los dividendos y los intereses eran movimientos
sueltos: se veían sólo filtrando la lista de Movimientos, y el único total era el
"Cobrado" de toda la historia. La pestaña Cobros de Movimientos los muestra por
mes, por año y por activo.

LAS FILAS SON LAS DE MOVIMIENTOS. Este módulo no lee ninguna tabla: recibe las
filas que arma `main._build_movements` (lo mismo que devuelve /api/movements) y
las agrupa. Así "Cobrado" de Movimientos y los totales de Cobros coinciden POR
CONSTRUCCIÓN, como ya pasa con las comisiones (`/api/insights/commissions`).

EL DÓLAR DE CADA COBRO ES EL DE SU DÍA, y no se resuelve acá: ya viene en
`amount_usd` de cada fila.
  · Importado en pesos: `gross_amount_usd`, sellado al importar con
    `fx.fx_for_date` de la fecha del cobro (importing/pipeline.py).
  · Confirmado desde las bandejas (dividendo o cupón): `fx_to_usd` sellado con
    `fx.fx_for_date_detail` del día del cobro (dividendos.registrar_cobro y
    POST /api/bonds/cashflow/pago), leído por `realized_pnl.leer_cobro`.
  Lo que NO se suma: `operations.pnl_usd` de un dividendo importado, que va al
  dólar del día del IMPORT (persister._persist_dividend_or_interest).

QUÉ CUENTA COMO COBRO: los tipos DIVIDEND (dividendo, cupón, renta) e INTEREST
(interés, interés de plazo fijo). La AMORTIZACIÓN de un bono no: es el capital
propio que vuelve, no algo que la inversión pagó. Mismo criterio que el KPI
"Cobrado" de Movimientos (Operations.jsx · computeMovementKpis).

El monto es con signo, igual que ese KPI: una reversión del broker resta.
"""
from __future__ import annotations

from datetime import date, timedelta

TIPOS = ("DIVIDEND", "INTEREST")


def _fecha(m) -> str | None:
    f = str(m.get("date") or "")[:10]
    return f if len(f) == 10 and f[4] == "-" and f[7] == "-" else None


def _r(v: float) -> float:
    return round(v, 2)


def resumir(movimientos: list, hoy: str) -> dict:
    """Agrupa las filas de Movimientos que son cobros.

    `hoy` es la fecha de Argentina (AAAA-MM-DD): define el año en curso, el
    "mismo período del año anterior" y la ventana de los últimos 12 meses.

    Devuelve:
      anio, total_anio                → lo cobrado en el año en curso.
      total_anterior_a_la_fecha       → lo cobrado del 1/1 al mismo día del año
                                        anterior: la comparación justa en octubre.
      total_anterior                  → el año anterior completo.
      por_mes  [12]                   → {mes, anio, anterior}: cada mes de los dos años.
      por_anio                        → {anio, usd}: todos los años con cobros.
      por_activo                      → los del año en curso, de mayor a menor:
                                        {activo, tipos, usd, cobros}.
      ultimos_12_meses                → {fecha, activo, tipo, usd}: la historia
                                        con la que la pantalla estima los próximos 12.
    """
    hoy_d = date.fromisoformat(hoy[:10])
    anio = hoy_d.year
    anterior = anio - 1
    # El mismo día del año anterior (el 29/2 cae al 28).
    try:
        tope_anterior = hoy_d.replace(year=anterior).isoformat()
    except ValueError:
        tope_anterior = hoy_d.replace(year=anterior, day=28).isoformat()
    desde_12m = (hoy_d - timedelta(days=365)).isoformat()

    por_mes = {m: [0.0, 0.0] for m in range(1, 13)}
    por_anio: dict = {}
    por_activo: dict = {}
    total_anterior_a_la_fecha = 0.0
    ultimos = []

    for m in movimientos:
        tipo = m.get("type")
        if tipo not in TIPOS:
            continue
        f = _fecha(m)
        if not f:
            continue
        usd = float(m.get("amount_usd") or 0)
        if not usd:
            continue
        y, mes = int(f[:4]), int(f[5:7])
        activo = (m.get("asset") or "").strip().upper()
        por_anio[y] = por_anio.get(y, 0.0) + usd
        if y == anio:
            por_mes[mes][0] += usd
            a = por_activo.setdefault(activo, {"activo": activo, "tipos": set(), "usd": 0.0, "cobros": 0})
            a["tipos"].add(tipo)
            a["usd"] += usd
            a["cobros"] += 1
        elif y == anterior:
            por_mes[mes][1] += usd
            if f <= tope_anterior:
                total_anterior_a_la_fecha += usd
        if desde_12m < f <= hoy:
            ultimos.append({"fecha": f, "activo": activo, "tipo": tipo, "usd": _r(usd)})

    activos = sorted(por_activo.values(), key=lambda a: -a["usd"])
    for a in activos:
        a["tipos"] = sorted(a["tipos"])
        a["usd"] = _r(a["usd"])
    ultimos.sort(key=lambda c: c["fecha"])
    return {
        "hoy": hoy_d.isoformat(),
        "anio": anio,
        "total_anio": _r(por_anio.get(anio, 0.0)),
        "total_anterior_a_la_fecha": _r(total_anterior_a_la_fecha),
        "total_anterior": _r(por_anio.get(anterior, 0.0)),
        "por_mes": [{"mes": k, "anio": _r(v[0]), "anterior": _r(v[1])} for k, v in por_mes.items()],
        "por_anio": [{"anio": k, "usd": _r(v)} for k, v in sorted(por_anio.items())],
        "por_activo": activos,
        "ultimos_12_meses": ultimos,
    }
