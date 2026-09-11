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

# ─── EL DÓLAR DE VALUACIÓN POR FECHA: EL PUNTO MEDIO ─────────────────────────
#
# `(compra + venta) / 2`, con red a la punta de venta cuando no hay compra
# guardada. Es la MISMA regla que `main._val_rate` aplica al dólar vivo, y existe
# por la misma razón: los brokers (Cocos/IOL/Balanz) valúan al medio. Medido con
# un usuario real: veía US$ 6.884 donde Cocos le mostraba 6.933 — los mismos
# 10,53 M de pesos divididos por 1.529,71 (la punta cara) en vez de 1.518,43.
#
# POR QUÉ IMPORTA QUE SEA LA MISMA EN LAS DOS. Mientras la valuación viva usaba
# el medio y lo guardado por fecha era la venta, un borde reconstruido y otro
# medido diferían por el spread (~0,7 %) y encadenarlos FABRICABA retorno de la
# nada. `ledger_replay` lo documenta como la "pérdida fantasma" y lo parcheaba
# estampando `fx_basis` y marcando los tramos con bases distintas.
#
# Va como EXPRESIÓN SQL y no como función de Python porque los lectores son
# siete y cada uno arma su propia consulta: así la cuenta vive una sola vez.
# `tests/test_dolar_medio_historico.py` verifica que ninguno la re-escriba.
#
# COALESCE y no `IFNULL`: funciona igual en SQLite y en Postgres. Si `*_compra`
# es NULL la suma es NULL y cae a la punta de venta — exactamente el fallback de
# `_val_rate` para el caché viejo o una casa sin compra.
# ⚠️ FILTRO DE CORDURA SOBRE LA PUNTA COMPRADORA — no es decorativo.
#
# La fuente tiene dato podrido, medido el 2026-09-11 sobre las dos series:
#   · 2025-05-02 (bolsa): compra 751,67 contra venta 1.363,60 = 45 % de spread.
#     El MEP nunca tuvo eso. Tomar ese medio mueve el dólar de esa fecha −22,4 %.
#   · 73 días con la compra POR ENCIMA de la venta (70 en blue, 3 en bolsa).
#   · un `0` sería "no hay dato", no "el dólar vale cero": su medio es venta/2,
#     un error del 50 %.
#
# La asimetría manda el criterio: usar una compra mala corrompe el costo hasta un
# 22 %, mientras que descartarla deja el valor que ya se usaba —la punta de venta—
# o sea el statu quo. Ante la duda NO se usa. El tope de 10 % deja pasar las
# cotizaciones viejas del blue, donde el dólar valía $10 y el redondeo entero a
# 10/11 da un 9 % que es legítimo.
#
# El guard va acá, en el LECTOR, aunque el backfill ya filtre: es el embudo único
# y una fila mala escrita por cualquier otro camino no puede hacer daño. Misma
# lección que cerró la tanda F4.
#
# `CASE` y no `COALESCE`: con la compra en NULL la condición da NULL, que no es
# verdadera, y cae al ELSE. Funciona igual en SQLite y en Postgres.
def _sql_medio(compra: str, venta: str) -> str:
    return (f"CASE WHEN {compra} > 0 AND {compra} < {venta} "
            f"AND ({venta} - {compra}) <= 0.10 * {venta} "
            f"THEN ({compra} + {venta}) / 2.0 ELSE {venta} END")


SQL_MEDIO_MEP = _sql_medio("mep_compra", "mep_venta")
SQL_MEDIO_BLUE = _sql_medio("blue_compra", "blue_venta")

_COL = {RIEL_MEP: SQL_MEDIO_MEP, RIEL_BLUE: SQL_MEDIO_BLUE}

# La columna CRUDA de cada riel, para el `IS NOT NULL` del WHERE: el medio puede
# ser NULL por falta de compra y aun así haber venta, que es lo que se entrega.
_COL_CRUDA = {RIEL_MEP: "mep_venta", RIEL_BLUE: "blue_venta"}


def _lookup(conn, riel: str, d: str) -> Optional[float]:
    """El dólar de VALUACIÓN del riel `riel` en o antes de `d`: el punto medio.

    ⚠️ El filtro `IS NOT NULL` va en el WHERE, no después de traer la fila. Si se
    toma "la fila más reciente ≤ fecha" y recién ahí se valida la columna, un solo
    día sin MEP devuelve NULL y el caller cae al fallback creyendo que no hay
    cobertura — cuando el dato existía dos días antes. `mep_venta` es NULLABLE y se
    pobló por UPDATE sobre fechas que ya tenían blue, así que ese caso es real.

    ⚠️ Y el WHERE mira la columna CRUDA, no la expresión del medio. Una fila con
    venta pero sin compra tiene medio = venta (por el COALESCE) y es perfectamente
    entregable; filtrar por el medio no cambiaría nada hoy, pero ata el criterio de
    cobertura a la presencia de la punta compradora, que es otra pregunta.
    """
    col = _COL.get(riel) or _COL[RIEL_MEP]
    cruda = _COL_CRUDA.get(riel) or _COL_CRUDA[RIEL_MEP]
    try:
        row = conn.execute(
            f"SELECT {col} FROM fx_rates_daily "
            f"WHERE date <= ? AND {cruda} IS NOT NULL ORDER BY date DESC LIMIT 1",
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
    v = _lookup(conn, primero, d)
    if v is not None:
        return (v, primero)

    # Red histórica: el blue cubre desde 2011 y es determinístico igual.
    if primero != RIEL_BLUE:
        v = _lookup(conn, RIEL_BLUE, d)
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




# ─── El costo de un lote, en la moneda de la venta ───────────────────────────

def costo_en_moneda_de_venta(base_invested, lot_currency, sell_currency, *,
                             conn=None, entry_date=None, tc_venta=None,
                             tc_blue=None, historico: bool = False):
    """Lleva el costo de un lote a la moneda en que se lo vende.

    POR QUÉ ACÁ Y NO EN CADA MOTOR
    ──────────────────────────────
    Esta cuenta vivía copiada en TRES lugares —`persister._persist_sell_fifo`,
    `rebuild`, y el endpoint de venta manual `POST /api/positions/sell`— y las
    tres copias no decían lo mismo. Las dos del importador respetan el
    `fx_version` de la cuenta; la del formulario manual no lo miraba y pedía el
    BLUE siempre.

    O sea que en una cuenta v2 la MISMA venta daba un costo distinto según se
    hubiera importado o tipeado. Medido sobre la serie real: MEP y blue se
    separan más de 3 % en la mitad de los días con los dos publicados, más de
    10 % en el 8 %, y el peor día 25,1 % (2023-10-20).

    Y el defecto estaba a treinta líneas de su propio arreglo: en ese mismo
    endpoint la pata de la VENTA ya era version-aware y usaba `fx_for_date`
    (main.py, `tc_venta`). Se arregló una de las dos patas.

    LAS DOS DIRECCIONES
    ───────────────────
    · lote USD vendido en ARS → el costo en dólares es real; se lleva a pesos al
      MISMO TC de la venta, así `pnl_ars / tc_venta` preserva el costo USD (se
      cancela).
    · lote ARS vendido en USD (dólar-MEP) → el FX SÍ se realiza al vender. El
      costo en dólares es lo que esos pesos valían CUANDO SE COMPRÓ, no hoy:
      usar el de hoy achica el costo e infla la ganancia con la devaluación.

    `historico` viene del `fx_version` de la cuenta (v2 → True). En v1 el riel
    es el blue y el replay queda EXACTAMENTE como siempre: `fx_for_date` con
    `riel=RIEL_BLUE` es la misma consulta que hacía `persister.blue_for_date`
    (`blue_venta` es NOT NULL en los dos motores, así que el `IS NOT NULL` del
    WHERE no cambia ninguna fila).

    Sin `conn` o sin `entry_date` cae a `tc_blue`, que es el comportamiento que
    ya tenían los tres call sites para tests y callers viejos.
    """
    # ⚠️ `> 0`, NO "¿tiene valor?". Los tres call sites acotan `tc_blue` a
    # positivo antes de llamar (persister.py:365, pipeline._read_user_tc_blue,
    # main._user_tc_blue), así que hoy no hay camino que llegue con un negativo.
    # Pero esta función es el EMBUDO ÚNICO de la cuenta: con la guarda de
    # truthiness un `tc_blue = -5` pasaba y devolvía un costo NEGATIVO, que
    # después se resta de los ingresos y publica una ganancia inventada. El guard
    # va donde se usa el dato, no sólo donde se produce — es lo mismo que cerró
    # la tanda F4.
    def _pos(x):
        try:
            return float(x) if x is not None and float(x) > 0 else None
        except (TypeError, ValueError):
            return None

    _tcb = _pos(tc_blue)
    if lot_currency == sell_currency or _tcb is None:
        return base_invested
    if lot_currency == "USD" and sell_currency == "ARS":
        return base_invested * (_pos(tc_venta) or _tcb)
    if lot_currency == "ARS" and sell_currency == "USD":
        riel = RIEL_MEP if historico else RIEL_BLUE
        compra_fx = fx_for_date(conn, entry_date, fallback=_tcb, riel=riel)
        return base_invested / (_pos(compra_fx) or _tcb)
    return base_invested

# ─── Versionado por usuario: la migración es POR CUENTA, no global ────────────
#
# Deployar el TC histórico sin esto rompe a los 503 usuarios con data existente:
# el rebuild re-deriva sus VENTAS con el TC nuevo en cuanto tocan cualquier camino
# de rebuild (import, foto, backfill), pero sus FLUJOS quedan estampados al dólar
# del import viejo (medido: 80.868 de 84.123 al mismo 1415, desde 2013). Hoy los
# dos errores se CANCELAN en el cociente del Total Return (medido: 2,00% mostrado
# vs 1,63% real = error 1,23×); con una sola pata migrada dejan de cancelarse y el
# error salta a 9,1×. Las dos patas tienen que moverse JUNTAS, por usuario, en una
# transacción — eso es exactamente lo que hace el migrador
# (/api/admin/fx-migrate-user), que al final estampa `fx_version = v2`.
#
#   v1 → el motor escribe como siempre (dólar vivo del import). Nadie cambia de
#        número por el deploy.
#   v2 → el motor escribe con fx_for_date. Cuentas nuevas nacen acá.

FX_V1 = "v1"
FX_V2 = "v2"
_FX_VERSION_KEY = "fx_version"


def fx_version(conn, uid: int) -> str:
    """Versión de FX de la cuenta. Resuelve UNA vez y queda persistida.

    Sin fila en config:
      · cuenta con historia (algún batch confirmado o alguna operación) → v1,
        "grandfathered": sus números no se mueven hasta que el migrador la pase.
      · cuenta virgen → v2, y se PERSISTE en el momento. El orden importa: la
        primera resolución ocurre durante el primer preview/persist, ANTES de que
        su primer batch quede confirmado — si no se persistiera acá, la segunda
        llamada la vería "con historia" y la degradaría a v1 para siempre.
    """
    try:
        row = conn.execute(
            "SELECT value FROM config WHERE user_id=? AND key=?",
            (uid, _FX_VERSION_KEY)).fetchone()
        if row and row[0] in (FX_V1, FX_V2):
            return row[0]
        tiene_historia = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM import_batches WHERE user_id=? AND status='confirmed') "
            "OR EXISTS(SELECT 1 FROM operations WHERE user_id=?)",
            (uid, uid)).fetchone()[0]
        version = FX_V1 if tiene_historia else FX_V2
        # Conflicto por la PK entera (key, user_id): `fx_version` es POR CUENTA, no
        # global. Nombra las 3 columnas de `config`, así que no hay nada que se
        # pierda respecto del INSERT OR REPLACE de antes (que borraba y reinsertaba).
        # DO UPDATE y no DO NOTHING: acá se llega justo cuando la fila NO existe o
        # trae un valor basura (el `if row[0] in (FX_V1, FX_V2)` de arriba ya devolvió
        # si era válido). Con DO NOTHING una fila corrupta quedaría corrupta para
        # siempre y la cuenta re-resolvería su versión en cada llamada.
        conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (uid, _FX_VERSION_KEY, version))
        return version
    except Exception:
        # Ante cualquier duda, el comportamiento viejo: v1 no corrompe nada, solo
        # posterga la mejora para esa cuenta.
        return FX_V1


def set_fx_version(conn, uid: int, version: str) -> None:
    if version not in (FX_V1, FX_V2):
        raise ValueError(f"fx_version inválida: {version}")
    # Conflicto por la PK entera (key, user_id). Pisar es el PUNTO de esta función:
    # el migrador FX la llama al final de la transacción para estampar v2 sobre la
    # v1 que la cuenta ya tenía, así que la rama que corre de verdad es el DO UPDATE.
    # DO NOTHING la dejaría en v1 con las dos patas del TC ya migradas = peor que no
    # migrar. Nombra las 3 columnas de `config`: no se pierde ninguna.
    conn.execute(
        "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
        (uid, _FX_VERSION_KEY, version))
