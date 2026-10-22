"""Cobros: lo que le pagaron al usuario sus inversiones (dividendos, cupones, intereses).

POR QUÉ EXISTE (2026-10-22). Los dividendos y los intereses eran movimientos
sueltos: se veían sólo filtrando la lista de Movimientos, y el único total era el
"Cobrado" de toda la historia. La pestaña Cobros de Movimientos los muestra por
mes, por año y por activo.

LAS FILAS SON LAS DE MOVIMIENTOS. Este módulo no lee ninguna tabla: recibe las
filas que arma `main._build_movements` (lo mismo que devuelve /api/movements) y
elige cuáles son cobros. Las SUMAS (por mes, año, activo) las hace la pantalla
(frontend/src/utils/cobros.js · resumirCobros), en UN lugar, porque una parte de
los cupones sólo se puede separar con el cronograma de cada bono, que vive allá
(utils/bondSchedule.js, el mismo de Eventos y del estimado).

EL DÓLAR DE CADA COBRO ES EL DE SU DÍA, y no se resuelve acá: ya viene en
`amount_usd` de cada fila.
  · Importado en pesos: `gross_amount_usd`, sellado al importar con
    `fx.fx_for_date` de la fecha del cobro (importing/pipeline.py).
  · Confirmado desde las bandejas (dividendo o cupón): `fx_to_usd` sellado con
    `fx.fx_for_date_detail` del día del cobro (dividendos.registrar_cobro y
    POST /api/bonds/cashflow/pago), leído por `realized_pnl.leer_cobro`.
  Lo que NO se suma: `operations.pnl_usd` de un dividendo importado, que va al
  dólar del día del IMPORT (persister._persist_dividend_or_interest).

DOS LISTAS:
  · `cobros`: los tipos DIVIDEND (dividendo, cupón, renta) e INTEREST (interés,
    interés de plazo fijo), enteros. Mismo universo que el KPI "Cobrado" de
    Movimientos (Operations.jsx · computeMovementKpis).
  · `pagos_mixtos`: pagos de un bono que el broker trae en UN renglón con el
    cupón y la amortización juntos ("Renta y Amortización"). Una parte es renta
    y otra es capital propio que vuelve; sumarlos enteros inflaba los cupones y
    descartarlos los perdía. Llegan de dos formas, las dos importadas, con la
    marca de siempre en la nota ("amortiz", la misma de
    `cobros_bonos.ventas_que_son_amortizacion` y del persister):
      – sin cantidad: DIVIDEND que Movimientos muestra como AMORTIZATION
        (`main._tipo_de_fila_importada`);
      – con cantidad (Balanz): una VENTA de los nominales que se devolvieron.
    Sólo los que además dicen "renta": una "Amortización" sola no trae cupón.
    La pantalla separa el cupón con el cronograma; si no puede, lo dice.

El monto es con signo, igual que el KPI: una reversión del broker resta. Va sin
redondear: Movimientos lo lee de la misma fila y los dos totales tienen que dar
igual al centavo.
"""
from __future__ import annotations

from datetime import date

TIPOS = ("DIVIDEND", "INTEREST")


def _fecha(m) -> str | None:
    f = str(m.get("date") or "")[:10]
    return f if len(f) == 10 and f[4] == "-" and f[7] == "-" else None


def es_pago_mixto(m) -> bool:
    """Un renglón importado de un bono con cupón y amortización juntos."""
    if m.get("source") != "import" or m.get("transfer_out"):
        return False
    if m.get("type") not in ("AMORTIZATION", "SELL"):
        return False
    notas = (m.get("notes") or "").lower()
    return "amortiz" in notas and "renta" in notas


def clase_de_cobro(m):
    """LA regla de qué renglón de Movimientos es un cobro. 'entero' si cuenta
    todo su monto (dividendo, cupón, interés), 'mixto' si sólo cuenta su parte de
    cupón (la separa la pantalla con el cronograma), None si no es un cobro.

    `main._build_movements` la estampa en cada fila (campo `cobro`) y `cobros()`
    la usa para /api/cobros: Movimientos ("Cobrado", el total del filtro) y la
    pestaña Cobros cuentan con la misma regla y la misma cuenta
    (frontend/src/utils/cobros.js · montoCobrado). Pedido de Nico, 2026-10-22:
    los dos números tienen que coincidir."""
    if m.get("type") in TIPOS:
        return "entero"
    if es_pago_mixto(m):
        return "mixto"
    return None


def cobros(movimientos: list, hoy: str, dias_hasta_el_pago: int) -> dict:
    """Las filas de Movimientos que son cobros, desde el 1/1 del año ANTERIOR (lo
    que necesitan la comparación, las barras y los últimos 12 meses) más el total
    de cada año previo (para la vista "Por año").

    `hoy` es la fecha de Argentina (AAAA-MM-DD)."""
    hoy_d = date.fromisoformat(hoy[:10])
    desde = date(hoy_d.year - 1, 1, 1).isoformat()
    filas, mixtos, anios_previos = [], [], {}
    for m in movimientos:
        f = _fecha(m)
        if not f:
            continue
        usd = float(m.get("amount_usd") or 0)
        if not usd:
            continue
        activo = (m.get("asset") or "").strip().upper()
        clase = m.get("cobro", clase_de_cobro(m))
        if clase == "entero":
            fila = {"fecha": f, "activo": activo, "tipo": m["type"], "usd": usd}
        elif clase == "mixto":
            fila = {"fecha": f, "activo": activo, "tipo": "MIXTO", "usd": abs(usd)}
        else:
            continue
        if f >= desde:
            (filas if fila["tipo"] != "MIXTO" else mixtos).append(fila)
        else:
            # Años viejos: de los cobros enteros alcanza con el total del año; los
            # mixtos viajan uno por uno, porque su cupón lo separa la pantalla.
            y = int(f[:4])
            if fila["tipo"] == "MIXTO":
                mixtos.append(fila)
            else:
                anios_previos[y] = anios_previos.get(y, 0.0) + usd
    filas.sort(key=lambda c: c["fecha"])
    mixtos.sort(key=lambda c: c["fecha"])
    return {
        "hoy": hoy_d.isoformat(),
        "dias_hasta_el_pago": dias_hasta_el_pago,
        "cobros": filas,
        "pagos_mixtos": mixtos,
        "anios_previos": [{"anio": k, "usd": round(v, 2)} for k, v in sorted(anios_previos.items())],
    }
