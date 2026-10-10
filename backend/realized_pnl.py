"""Criterio ÚNICO de "P&L realizado en USD" sobre `operations`.

Este módulo existe porque el criterio estaba copiado a mano en 4 lugares y
divergió: se arregló en uno solo y los otros tres siguieron mintiendo. El
síntoma en producción fue un cupón de bono en pesos que el dashboard mostraba
como US$100 y la IA, en el MISMO request, le contaba al usuario como
US$125.000 (≈ el monto en pesos leído como si fueran dólares).

── El problema de fondo ──────────────────────────────────────────────────────
La columna se llama `pnl_usd`, pero en las cobranzas de renta fija NO guarda
USD: guarda la ganancia en la MONEDA DEL BROKER (`_registrar_cobro_bono`: en el
cupón es el monto cobrado; en la amortización, desde 2026-10-09, sólo lo cobrado
por encima del costo — lo cobrado va en `quantity`). Un cupón de $125.000 en un broker en pesos entra a la
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

── Pendiente #1: el win rate cuenta los cupones como "operaciones ganadas" ───
Distinto del bug de moneda, y NO se arregla convirtiendo. Medido: un cupón entra
al conteo y el win rate va de 50% a 50% al convertir (125.000 y 100 son ambos
positivos), y sólo baja a 33% si se lo EXCLUYE.

El problema es que un cupón nunca es negativo: no existe "cobrar mal un cupón".
Así que cada uno suma una ganada al numerador y al denominador, e infla un
número que el usuario lee como "cuántas de mis decisiones salieron bien" —
decisiones que no tomó. Afecta a:

  • reporting/timeline.py:61   _compute_user_historical_win_rate (win rate lifetime)
  • behavioral.py             detect_winrate_payoff → evidence.win_rate_pct
                              (avg_win y expectancy del mismo card YA están bien:
                               ésos sí eran de moneda y se arreglaron)
  • reporting/builder.py:255  wins/losses del período
  • ai/builders/reports.py    trades_year (sólo cuenta)

Arreglarlo es EXCLUIR Cupón/Amortización del universo de "trades", o sea
cambiarle el significado a la métrica — decisión de producto, no una conversión.
Sin decidir a propósito (2026-08-18).

── Pendiente #2: las 398 filas viejas ────────────────────────────────────────
No se tocan, y por eso siguen infladas también en el dashboard. Sin
`fx_to_usd` sellado no hay forma de convertirlas sin romper las ~125 que ya
vienen en dólares (ver arriba). Necesita su propio trabajo: un criterio
verificable para distinguirlas, o conseguir el TC de la fecha de cada una.

── Pendiente #3: la MITAD de `Interés PF` que sigue abierta ──────────────────
La moneda ya está: `Interés PF` entró a `_NATIVE_CCY_OPS` y el endpoint sella
el MEP del día del cobro, así que el interés en pesos deja de leerse como
dólares (era un PF de $10M a 30 días = US$328.767 falsos en 5 pantallas).
Agregarlo no movió ninguna fila vieja: sin `fx_to_usd` sellado las dos ramas
caen al crudo, exactamente como antes.

Lo que NO se tocó es que `Interés PF` tampoco está en `_NOT_A_TRADE`, así que
cada cobro sigue sumando "una operación ganada" a los 6 win rates de la lista de
arriba — el usuario no decidió nada, le venció un plazo fijo. Eso es el mismo
pendiente #1 y la misma causa: `_NOT_A_TRADE` es una lista de EXCLUSIÓN, o sea
que todo `op_type` nuevo entra como trade cerrado ganado POR OMISIÓN. Cambiarlo
le cambia el significado a la métrica — decisión de producto, no mecánica.
"""
from __future__ import annotations

# Tipos de operación que NO son un trade cerrado (no aportan P&L realizado).
# `''` cubre las filas con op_type vacío.
_NOT_A_TRADE = ('Compra', 'Dividendo', 'Interés', '')

# Cobranzas en MONEDA NATIVA: `pnl_usd` guarda el monto en moneda del broker.
# Éstas son las únicas que se convierten (ver docstring).
#
# `Interés PF` entra acá por la MISMA razón que las otras dos: el endpoint lo
# escribe en pesos con `currency='ARS'`. Agregarlo NO mueve ni una fila vieja —
# las dos ramas de conversión (SQL y Python) exigen `fx_to_usd > 0` y las filas
# de antes nacieron con NULL, así que caen al crudo igual que antes. Sólo tiene
# efecto sobre lo que se escriba de ahora en más, que ya sella el MEP del día
# del cobro (main.py, `cobrar_plazo_fijo`).
_NATIVE_CCY_OPS = ('Cupón', 'Amortización', 'Interés PF')


def _p(prefix: str) -> str:
    return f"{prefix}." if prefix else ""


def no_es_conversion_sql(prefix: str = "") -> str:
    """WHERE que deja afuera las conversiones de moneda — `es_conversion` en SQL."""
    p = _p(prefix)
    return (f"{p}op_type NOT LIKE 'CONVERSION%' "
            f"AND {p}op_type NOT LIKE 'Conversión%'")


def closed_filter_sql(prefix: str = "") -> str:
    """WHERE de "operaciones cerradas". `prefix` es el alias de la tabla."""
    p = _p(prefix)
    quoted = ",".join(f"'{t}'" for t in _NOT_A_TRADE)
    return (
        f"{p}pnl_usd IS NOT NULL "
        f"AND {p}op_type NOT IN ({quoted}) "
        f"AND {no_es_conversion_sql(prefix)}"
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


def es_conversion(op_type) -> bool:
    """¿La fila de `operations` es una conversión de moneda (pesos ↔ dólares)?

    Una conversión NO es un trade aunque viva en la misma tabla y con las mismas
    columnas: `quantity` guarda el monto de la moneda que SALE (pesos en una
    compra de USD) y `entry_price`/`exit_price` el tipo de cambio. Quien la lea
    como trade multiplica pesos por TC: comprar US$10 con $15.400 figuraba en
    Movimientos como "Venta US$23.710.610".

    Las escriben el botón Comprar/Vender USD (`CONVERSION <tipo> ARS→USDT`, con
    tipo MEP/CCL/USDT/Otro) y el importador (`CONVERSION IMPORT ARS→USDT`).
    'Conversión' cubre las filas de parsers viejos."""
    return (op_type or "").strip().startswith(("CONVERSION", "Conversión"))


def is_closed_op(op_type) -> bool:
    """Equivalente en Python de `closed_filter_sql` (sin el chequeo de NULL)."""
    t = (op_type or "").strip()
    if t in _NOT_A_TRADE:
        return False
    return not es_conversion(t)


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


# ─── Los COBROS: plata que entra por TENER el activo ───────────────────────
#
# Un dividendo, un cupón, un interés, la amortización de un bono. Viven en la
# misma tabla y con las mismas columnas que una venta, pero se leen distinto:
#
#   · `quantity` NO son unidades: es lo que entró a la cuenta (en los cobros
#     anotados desde las bandejas de Cartera y en los importados);
#   · `pnl_usd` es la GANANCIA, en la moneda de la cuenta para los de
#     `_NATIVE_CCY_OPS` (`realized_usd` la pasa a dólares). En una amortización
#     es sólo lo cobrado por encima del costo: el resto es capital que vuelve.
#
# UNA regla (`leer_cobro`) para Movimientos, el CSV del contador, el chat de IA
# y sus herramientas. Quien lea la fila como un trade muestra "800 unidades" o
# le cuenta al modelo $ 95.000 como US$ 95.000 (auditoría 2026-10-10).
#
# ⚠️ Esto NO decide si un cobro cuenta como "operación ganada" en el win rate:
# eso es el Pendiente #1 de arriba (`_NOT_A_TRADE`), decisión de producto.
_TIPO_DE_COBRO = {
    "Dividendo": "DIVIDEND",
    "Cupón": "DIVIDEND", "Cupon": "DIVIDEND", "Renta": "DIVIDEND",
    "Interés": "INTEREST", "Interes": "INTEREST", "Interés PF": "INTEREST",
    # La amortización de un bono es capital que vuelve, no un dividendo: tipo
    # propio. Lo que entró va en `amount_usd` y sólo la GANANCIA en `pnl_usd`.
    "Amortización": "AMORTIZATION", "Amortizacion": "AMORTIZATION",
}


def es_cobro(op_type) -> bool:
    return (op_type or "").strip() in _TIPO_DE_COBRO


def leer_cobro(d):
    """Un COBRO como movimiento: tipo, lo que entró en dólares, la ganancia en
    dólares y las comisiones. None si la fila no es un cobro. `d` es un dict (o
    Row) con `op_type`, `quantity`, `pnl_usd`, `currency`, `fx_to_usd`,
    `commissions`.

    Lo que entró: los cobros de las bandejas lo guardan en `quantity`, en la
    moneda de la fila; sólo se usa si la moneda está DICHA (USD, o ARS con su
    TC). Filas viejas sin moneda (dividendos que perdieron su vínculo con el
    import) tienen `quantity` en pesos: leerlas como dólares mostraba $ 14.500
    como US$ 14.500 (auditoría 2026-10-09). Para ésas, y para los cupones
    anteriores a 2026-10-09 (que no guardaban `quantity`), lo que entró es su
    resultado en dólares."""
    def _get(k):
        try:
            return d[k]
        except (KeyError, IndexError, TypeError):
            return None

    def _num(v):
        try:
            return None if v is None or v == "" else float(v)
        except (TypeError, ValueError):
            return None

    tipo = _TIPO_DE_COBRO.get((_get("op_type") or "").strip())
    if not tipo:
        return None
    ccy = (_get("currency") or "").upper()
    fx = _num(_get("fx_to_usd")) or 0
    pnl = realized_usd(d) if _get("pnl_usd") is not None else 0
    cant = _num(_get("quantity"))
    if cant and ccy in ("USD", "USDT"):
        monto, div = cant, 1.0
    elif cant and ccy == "ARS" and fx > 0:
        monto, div = cant / fx, fx
    else:
        monto, div = pnl, (fx if (ccy == "ARS" and fx > 0) else 1.0)
    return {
        "type": tipo,
        "amount_usd": monto,
        "currency": ccy or "USD",
        "fees_usd": (_num(_get("commissions")) or 0) / div,
        "pnl_usd": pnl,
    }


# ─── El techo de credibilidad del % realizado (F4 · guard C7) ──────────────
#
# `pnl_pct` se DEFINE como 100·pnl_usd/invested_usd (persister.py, rebuild.py,
# main.py: los tres motores de venta escriben esa identidad). O sea que el
# cociente pnl/costo y el porcentaje guardado son el MISMO número en escalas
# distintas, y el techo "no publicar arriba de 10× el costo" se lee directo
# sobre la columna: |pnl_pct| > 1000.
#
# Por qué existe el techo — el razonamiento es de `ratePct` en
# frontend/src/utils/assetPnl.js, que lo aplica desde antes: cuando el costo se
# evapora, el cociente deja de ser un rendimiento. Un bono que amortizó casi
# todo sigue sumando años de cupones contra un costo residual (GD35: US$15 de
# posición, US$1.463 de renta ⇒ +9.804%). Y con el bug de escala per-100 del
# motor de ventas, un bono cotizado por 100 nominales da pnl = 99×costo.
#
# ⚠️ ESTO ES UN CINTURÓN, NO UN ARREGLO. Las dos causas conocidas del número
# absurdo siguen abiertas y tienen nombre: el motor toma el COSTO de
# `gross_amount` y los INGRESOS de `unit_price*qty` sin reconciliarlos (ver
# /api/admin/diagnose-scale, que las cuenta), y la venta declarada en una
# moneda distinta a la del lote no convierte el precio de salida. El techo
# impide publicar el número; no arregla la fila. Lo que sí hace, y por eso vale
# igual, es atrapar la PRÓXIMA causa — la que todavía no tiene nombre.
#
# Qué se oculta y qué no: se oculta LA TASA, nunca el monto. Falta el costo, no
# el dato. Misma decisión que ya tomaba `ratePct`.
#
# ⚠️ El valor está ESPEJADO en frontend/src/utils/assetPnl.js y hay un test que
# verifica que los dos no diverjan (test_advisor_composition.py). Si tocás uno,
# tocá el otro.
MAX_PNL_TO_COST = 10
MAX_PNL_PCT = MAX_PNL_TO_COST * 100        # 1000 %


def pct_creible(pnl_pct):
    """El `operations.pnl_pct` guardado, o None cuando no se sostiene.

    Para los lectores que ya tienen el porcentaje escrito en la fila. Los que
    tienen el par (total, costo) y necesitan además el chequeo de costo
    incompleto usan `rate_pct` de acá abajo — misma regla, misma constante.
    """
    if pnl_pct is None:
        return None
    try:
        p = float(pnl_pct)
    except (TypeError, ValueError):
        return None
    if p != p or p in (float("inf"), float("-inf")):   # NaN / ±inf
        return None
    return None if abs(p) > MAX_PNL_PCT else p


def rate_pct(total: float, cost: float, incomplete: bool = False):
    """La tasa a partir del par (resultado, costo), o None cuando no hay tasa
    que valga. Espejo exacto de `ratePct()` en assetPnl.js.

    Tres motivos para no publicarla: no hay costo, el costo está incompleto
    (alguna venta no trajo con qué despejarlo), o el costo es tan chico contra
    el resultado que el cociente dejó de ser un rendimiento.
    """
    if incomplete or not cost or cost <= 0:
        return None
    if abs(total) > cost * MAX_PNL_TO_COST:
        return None
    return (total / cost) * 100
