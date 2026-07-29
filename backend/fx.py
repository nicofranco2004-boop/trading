"""FX ARS/USD por FECHA — la fuente única para dolarizar cualquier cosa histórica.

POR QUÉ EXISTE
──────────────
El motor dolarizaba las ventas con `tc_blue`, el dólar VIVO del momento en que se
corría el import (`persister.py`, `rebuild.py`). Consecuencias medidas en producción
(2026-07-28, `/api/admin/diagnose-sell-fx`):

  · 51.475 ventas de 503 usuarios con el TC equivocado
  · un usuario con 370 ventas repartidas en 3.746 días —diez años— estampadas TODAS
    con el mismo 1415,00
  · 80.868 de 84.123 flujos en pesos (96%) al mismo 1415, desde 2013

Una venta en pesos de 2021 dividida por 1450 en vez de por ~180 muestra la octava
parte del P&L en dólares que realmente fue.

ESTRICTA A PROPÓSITO — NUNCA CAE AL DÓLAR VIVO
──────────────────────────────────────────────
`persister.blue_for_date` cae a `tc_blue` (el dólar de HOY) cuando no encuentra dato.
Eso hace que replayar el MISMO `import_normalized_tx` en dos momentos distintos dé
P&L distinto — medido: 1.490 contra 1.433,33. Con eso, un recompute masivo reescribe
también el P&L de cuentas SANAS y después no hay forma de distinguir una reparación
de un drift.

Acá la cadena de fallback es toda HISTÓRICA:

    MEP de la fecha  →  blue de la fecha  →  el `fallback` explícito del caller

o sea que el replay es DETERMINÍSTICO: mismo input, mismo output, siempre. Esa
propiedad es lo que hace que reparar el histórico sea replayar en vez de escribir
números a mano (que además el rebuild pisa en el próximo import).

COBERTURA REAL (medida, no estimada)
────────────────────────────────────
  · MEP: diario COMPLETO desde 2018-10-29 — 2.829 filas sobre un span de 2.830 días
  · blue: diario COMPLETO desde 2011-01-03 — 5.685 filas sobre 5.686 días
  · solo 290 de 73.718 ventas (0,4%) son anteriores a la cobertura MEP

Por eso el riel por defecto es MEP (la regla canónica del proyecto para todo menos
cripto de exchange) y el blue queda como red histórica, no como excusa.
"""
from typing import Optional

RIEL_MEP = "mep"
RIEL_BLUE = "blue"

_COL = {RIEL_MEP: "mep_venta", RIEL_BLUE: "blue_venta"}


def _lookup(conn, col: str, d: str) -> Optional[float]:
    """Último valor NO NULO de `col` en o antes de `d`.

    ⚠️ El filtro `IS NOT NULL` va en el WHERE, no después de traer la fila. Si se
    toma "la fila más reciente ≤ fecha" y recién ahí se valida la columna, un solo
    día sin MEP devuelve NULL y el caller cae al fallback creyendo que no hay
    cobertura — cuando el dato existía dos días antes. `mep_venta` es NULLABLE y se
    pobló por UPDATE sobre fechas que ya tenían blue, así que ese caso es real.
    """
    try:
        row = conn.execute(
            f"SELECT {col} FROM fx_rates_daily "
            f"WHERE date <= ? AND {col} IS NOT NULL ORDER BY date DESC LIMIT 1",
            (d,),
        ).fetchone()
    except Exception:
        return None
    if row and row[0] is not None:
        try:
            v = float(row[0])
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None
    return None


def fx_for_date_detail(conn, date_str, fallback=None, riel: str = RIEL_MEP):
    """Devuelve `(tc, fuente)` con fuente ∈ {'mep', 'blue', 'fallback', None}.

    Sirve para auditar con qué riel se valuó cada operación sin tener que
    re-derivarlo después comparando contra la serie.
    """
    if conn is None or not date_str:
        return (fallback, "fallback" if fallback else None)
    d = str(date_str)[:10]

    primero = riel if riel in _COL else RIEL_MEP
    v = _lookup(conn, _COL[primero], d)
    if v is not None:
        return (v, primero)

    # Red histórica: el blue cubre desde 2011 y es determinístico igual.
    if primero != RIEL_BLUE:
        v = _lookup(conn, _COL[RIEL_BLUE], d)
        if v is not None:
            return (v, RIEL_BLUE)

    return (fallback, "fallback" if fallback else None)


def fx_for_date(conn, date_str, fallback=None, riel: str = RIEL_MEP) -> Optional[float]:
    """El TC ARS/USD de `date_str`. Ver el docstring del módulo.

    `fallback` es el ÚLTIMO recurso (fechas previas a 2011 o base sin serie). No es
    el dólar de hoy salvo que el caller decida pasarlo — y los callers del motor lo
    pasan solo para no romper con una base vacía en tests.
    """
    return fx_for_date_detail(conn, date_str, fallback=fallback, riel=riel)[0]
