"""Criterio ÚNICO de "P&L realizado en USD" sobre `operations`.

Este módulo existe porque el criterio estaba copiado a mano en 4 lugares y
divergió: se arregló en uno solo y los otros tres siguieron mintiendo. El
síntoma en producción fue un cupón de bono en pesos que el dashboard mostraba
como US$100 y la IA, en el MISMO request, le contaba al usuario como
US$125.000 (≈ el monto en pesos leído como si fueran dólares).

── El problema de fondo ──────────────────────────────────────────────────────
La columna se llama `pnl_usd`, pero en las cobranzas de renta fija NO guarda
USD: guarda el monto en la MONEDA DEL BROKER (`bond_cashflow` inserta
`net_amount` tal cual). Un cupón de $125.000 en un broker en pesos entra a la
columna como 125000, y cualquiera que sume la columna cruda cuenta 125.000
dólares.

Desde 2026-08-15 las filas nuevas se sellan con `currency` + `fx_to_usd` (el FX
del día del evento), que es lo que permite convertirlas.

── La regla ──────────────────────────────────────────────────────────────────
Se divide SÓLO en Cupón/Amortización con `currency='ARS'` y `fx_to_usd > 0`:

  • En `Venta` el `pnl_usd` YA es USD y `fx_to_usd` guarda el tc_venta —
    dividir ahí rompería todo.
  • Las filas VIEJAS (fx NULL) caen al ELSE y quedan como estaban. NO se
    convierten con un FX inferido a posteriori, y esto es deliberado: medido
    contra el backup de producción del 2026-08-16, de los 276 cupones marcados
    ARS sin FX sellado, ~125 tienen montos < 1 (son bonos en dólares tipo
    AL30/AL29/AE38, ya en USD) y sólo ~29 superan 1.000 (AL35/GD35/TX26, pesos
    inequívocos). No hay forma confiable de separarlos desde los datos:
    convertirlos a todos haría 1250× más chicas a las que ya estaban bien —
    un bug peor que el que arregla. Quedan como están, en TODOS los lectores
    (incluido el dashboard), hasta que exista una clasificación aparte.

── Pendiente conocido ────────────────────────────────────────────────────────
`Interés PF` (interés de plazo fijo, main.py) guarda el monto en moneda nativa
igual que un cupón y NO está excluido de `closed_filter_sql`, pero tampoco se
convierte acá — porque el lector del dashboard tampoco lo convierte, y el
objetivo de este módulo es que los 4 lectores digan el MISMO número. Hoy no
muerde (0 filas en producción); el primer plazo fijo en pesos que alguien cobre
entra inflado en los 4. Para arreglarlo hay que agregarlo a `_NATIVE_CCY_OPS`,
lo que cambia el dashboard también — decisión de producto, no mecánica.
"""
from __future__ import annotations

# Tipos de operación que NO son un trade cerrado (no aportan P&L realizado).
# `''` cubre las filas con op_type vacío.
_NOT_A_TRADE = ('Compra', 'Dividendo', 'Interés', '')

# Cobranzas de renta fija: `pnl_usd` guarda el monto en MONEDA DEL BROKER.
# Éstas son las únicas que se convierten (ver docstring).
_NATIVE_CCY_OPS = ('Cupón', 'Amortización')


def _p(prefix: str) -> str:
    return f"{prefix}." if prefix else ""


def closed_filter_sql(prefix: str = "") -> str:
    """WHERE de "operaciones cerradas". `prefix` es el alias de la tabla."""
    p = _p(prefix)
    quoted = ",".join(f"'{t}'" for t in _NOT_A_TRADE)
    return (
        f"{p}pnl_usd IS NOT NULL "
        f"AND {p}op_type NOT IN ({quoted}) "
        f"AND {p}op_type NOT LIKE 'CONVERSION%' "
        f"AND {p}op_type NOT LIKE 'Conversión%'"
    )


def realized_usd_sql(prefix: str = "") -> str:
    """Expresión SELECT que devuelve el pnl de la fila en USD de verdad."""
    p = _p(prefix)
    quoted = ",".join(f"'{t}'" for t in _NATIVE_CCY_OPS)
    return (
        f"CASE WHEN {p}op_type IN ({quoted}) "
        f"AND {p}currency = 'ARS' "
        f"AND {p}fx_to_usd > 0 "
        f"THEN {p}pnl_usd / {p}fx_to_usd "
        f"ELSE {p}pnl_usd END"
    )


def is_closed_op(op_type) -> bool:
    """Equivalente en Python de `closed_filter_sql` (sin el chequeo de NULL)."""
    t = (op_type or "").strip()
    if t in _NOT_A_TRADE:
        return False
    return not t.startswith(("CONVERSION", "Conversión"))


def realized_usd(row) -> float:
    """Equivalente en Python de `realized_usd_sql`.

    `row` puede ser un dict o un sqlite3.Row: necesita `op_type`, `pnl_usd` y
    —para poder convertir— `currency` y `fx_to_usd`. Si la query no trajo esas
    dos columnas devuelve el valor crudo, que es el mismo comportamiento que
    tenía antes (no empeora, pero conviene traerlas).
    """
    def _get(k):
        try:
            return row[k]
        except (KeyError, IndexError, TypeError):
            return None

    raw = float(_get("pnl_usd") or 0)
    if (_get("op_type") or "").strip() not in _NATIVE_CCY_OPS:
        return raw
    if (_get("currency") or "").upper() != "ARS":
        return raw
    try:
        fx = float(_get("fx_to_usd") or 0)
    except (TypeError, ValueError):
        return raw
    return raw / fx if fx > 0 else raw
