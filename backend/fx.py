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
SPREAD_MAX = 0.10


def _sql_medio(compra: str, venta: str) -> str:
    return (f"CASE WHEN {compra} > 0 AND {compra} < {venta} "
            f"AND ({venta} - {compra}) <= {SPREAD_MAX} * {venta} "
            f"THEN ({compra} + {venta}) / 2.0 ELSE {venta} END")


SQL_MEDIO_MEP = _sql_medio("mep_compra", "mep_venta")
SQL_MEDIO_BLUE = _sql_medio("blue_compra", "blue_venta")



def punta_media(compra, venta):
    """LA MISMA REGLA que `_sql_medio`, para los callers que NO pasan por SQL.

    La hay en dos medios porque hay dos caminos: los siete lectores de
    `fx_rates_daily` arman su consulta (y ahí la cuenta viaja como expresión), y
    los que reciben el JSON de la fuente la necesitan en Python — hoy
    `_fetch_dolar_blue_monthly`, que arma la serie mensual de benchmarks sin
    tocar la tabla. Es el mismo patrón que `fechas.py` ↔ `fecha.js`, y
    `tests/test_dolar_medio_historico.py` verifica que las dos den lo mismo.

    Devuelve la punta de venta cuando la compra falta o es implausible — el
    statu quo, que es lo que hay que hacer ante la duda.
    """
    try:
        v = float(venta)
    except (TypeError, ValueError):
        return None
    if not v > 0:
        return None
    try:
        c = float(compra) if compra is not None else None
    except (TypeError, ValueError):
        c = None
    if c is None or not (0 < c < v) or (v - c) > SPREAD_MAX * v:
        return v
    return (c + v) / 2.0

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


def serie_diaria(conn, desde: str, dolar: str = "mep"):
    """`fx_for_date` para una serie entera, en UNA lectura: [(fecha, tc, fecha_del_tc)]
    por cada fila de `fx_rates_daily` desde `desde` (y la última anterior, para
    arrastrar). La regla es la misma que `fx_for_date`: el ÚLTIMO MEP conocido
    (aunque sea de días antes); el blue sólo si todavía no hubo ningún MEP.
    `fecha_del_tc` es la fecha del dato que se usó: quien la consume decide si es
    demasiado vieja para ser "el dólar de ese día".

    `dolar`='ccl': el contado con liqui de cada día, el dólar de los CEDEARs (ver
    «El dólar de los CEDEARs», abajo), con la misma forma.

    (Existe porque la ficha técnica convierte ~750 velas y pedir `fx_for_date`
    de a una son 750 consultas; y porque la versión que tenía aparte usaba el
    blue DEL DÍA cuando faltaba el MEP, distinto del resto de la app: un día así
    fabricaba un pozo de ~10 % en el gráfico.)"""
    if dolar == "ccl":
        return _serie_ccl(conn, desde)
    rows = conn.execute(
        f"SELECT date, {SQL_MEDIO_MEP} AS mep, {SQL_MEDIO_BLUE} AS blue FROM fx_rates_daily "
        "WHERE date >= COALESCE((SELECT MAX(date) FROM fx_rates_daily WHERE date < ?), ?) "
        "ORDER BY date", (desde, desde)).fetchall()
    out, mep, f_mep = [], None, None
    for r in rows:
        if r["mep"] is not None and r["mep"] > 0:
            mep, f_mep = float(r["mep"]), r["date"]
        if mep is not None:
            out.append((r["date"], mep, f_mep))
        elif r["blue"] is not None and r["blue"] > 0:
            out.append((r["date"], float(r["blue"]), r["date"]))
    return out


def fx_for_date(conn, date_str, fallback=None, riel: str = RIEL_MEP) -> Optional[float]:
    """El TC ARS/USD de `date_str`. Ver el docstring del módulo.

    `fallback` es el ÚLTIMO recurso (fechas previas a 2011 o base sin serie). No es
    el dólar de hoy salvo que el caller decida pasarlo — y los callers del motor lo
    pasan solo para no romper con una base vacía en tests.
    """
    return fx_for_date_detail(conn, date_str, fallback=fallback, riel=riel)[0]


# ─── EL DÓLAR DE LOS CEDEARs: el contado con liqui de cada día ───────────────
#
# Un CEDEAR se compra y se vende con el contado con liqui (CCL), no con el MEP:
# en pesos es la acción de afuera × el CCL ÷ su ratio. Medido el 06/11/2026
# contra los cierres de BYMA (83 CEDEARs, todas las ruedas de 5 años,
# audit/_scripts/medir_ccl.out): con el CCL de cada día el estimado queda entre
# 0,1 y 0,3 % de la Bolsa en la mediana de 2024 a 2026 (99 % de las ruedas de
# 2025–2026 a menos de 2 %); con el MEP, entre 0 y 12 % abajo según el mes, porque
# la distancia entre los dos dólares cambia (~6 % en noviembre de 2026, 0 en
# agosto de 2024) y con ella el error: de ahí los saltos del gráfico que no
# eran del mercado (auditoría del 06/11, H3 de la serie, H4 y H5 de la pantalla).
#
# DÓNDE SE GUARDA. En `bond_indices_daily` con el nombre 'CCL': la tabla de los
# números públicos de cada día (CER, UVA, A3500, que ya es un dólar), cuyos
# lectores filtran todos por nombre. NO en `fx_rates_daily`, que no tiene columnas
# para él: sumarlas cambia el esquema de Postgres en la publicación, y el
# 02/08/2026 un cambio así dejó la app caída. Un número por día: el MEDIO, con la
# regla de `punta_media` (la de la valuación). Lo baja `main._actualizar_ccl` de
# argentinadatos, la misma fuente del MEP, y es el mismo número que da en vivo
# dolarapi (medido el 06/11: 1.658,4 / 1.664,9 en las dos).
INDICE_CCL = "CCL"
# Lo que se vuelve a escribir cada vez aunque ya esté guardado: la fuente puede
# corregir los últimos días.
DIAS_CCL_REVISAR = 10
# Desde qué hora (de la Argentina) el CCL de HOY es el del cierre y se guarda. Antes,
# la fuente lo publica en vivo: guardado a la mañana (un arranque del servidor),
# la vela de hoy del gráfico quedaba con el dólar de esa hora y la Cartera de BAC
# con el de ahora (auditoría del contado con liqui, 06/11, H6 de la pantalla). El
# de hoy, mientras no cerró, es siempre el de ahora (`main._ccl_de_las_fechas`,
# `tecnico._dolar_de_hoy`).
HORA_CIERRE_CCL = 18

# EL escritor de `bond_indices_daily`: el CCL (`guardar_ccl`) y el CER y la UVA
# (`main._ensure_index_cached`) pasan por la misma sentencia.
SQL_GUARDAR_INDICE = """INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at)
   VALUES (?, ?, ?, ?, ?)
   ON CONFLICT(index_name, date) DO UPDATE SET
     value = excluded.value,
     source = excluded.source,
     updated_at = excluded.updated_at"""


def _serie_ccl(conn, desde: str):
    """`serie_diaria(..., 'ccl')`: el CCL guardado de cada día desde `desde` (y el
    último anterior, para arrastrar), [(fecha, ccl, fecha)]."""
    rows = conn.execute(
        "SELECT date, value FROM bond_indices_daily WHERE index_name = ? AND date >= "
        "COALESCE((SELECT MAX(date) FROM bond_indices_daily WHERE index_name = ? AND date < ?), ?) "
        "ORDER BY date", (INDICE_CCL, INDICE_CCL, desde, desde)).fetchall()
    return [(r["date"], float(r["value"]), r["date"]) for r in rows
            if r["value"] is not None and float(r["value"]) > 0]


def huella_del_dolar(conn, dolar: str):
    """Algo que cambia cuando cambia lo guardado del dólar `dolar` ('mep' | 'ccl'):
    cuántos días hay, el último y la suma de lo que valen. Para lo que se arma con
    él y queda en la memoria del proceso (las velas de 1 y 4 horas, `velas_horarias`;
    las alertas en la rueda, `alerts_engine._preparadas`). Los valores y no la hora
    de la última escritura: cada vez que alguien abre su Dashboard se reescribe el
    MEP de hoy (`main.post_snapshot`), casi siempre igual, y lo armado se volvía a
    armar a cada rato sin que cambiara nada. La misma idea que `tecnico._huellas`."""
    if dolar == "ccl":
        r = conn.execute("SELECT COUNT(*) AS n, MAX(date) AS u, SUM(value) AS s FROM bond_indices_daily "
                         "WHERE index_name = ?", (INDICE_CCL,)).fetchone()
    else:
        r = conn.execute(f"SELECT COUNT(*) AS n, MAX(date) AS u, SUM({SQL_MEDIO_MEP}) AS s "
                         "FROM fx_rates_daily").fetchone()
    return (r["n"], r["u"], r["s"]) if r else None


def ccl_desde(conn):
    """El primer día con CCL guardado, o None si todavía no hay ninguno (una base
    nueva antes de que `main._actualizar_ccl` lo baje)."""
    r = conn.execute("SELECT MIN(date) AS d FROM bond_indices_daily WHERE index_name = ?",
                     (INDICE_CCL,)).fetchone()
    return r["d"] if r else None


def ccl_de_las_fechas(conn, fechas, max_dias: int) -> dict:
    """{fecha: CCL} de cada fecha 'YYYY-MM-DD' con la regla de `serie_diaria`: el
    último guardado hasta ese día, si no tiene más de `max_dias` (más viejo no es
    «el de ese día»). La que no tiene queda afuera. En UNA lectura."""
    from datetime import date
    pedidas = sorted({str(f)[:10] for f in fechas if f})
    if not pedidas:
        return {}
    serie = _serie_ccl(conn, pedidas[0])
    out, j, actual = {}, 0, None
    for f in pedidas:
        while j < len(serie) and serie[j][0] <= f:
            actual = serie[j]
            j += 1
        if actual and (date.fromisoformat(f) - date.fromisoformat(actual[0])).days <= max_dias:
            out[f] = actual[1]
    return out


def _fecha_valida(fecha) -> bool:
    """¿'YYYY-MM-DD' de un día que existe? Con la forma exacta: en producción
    (Python 3.11) `fromisoformat` acepta «2026-W45-5» (una semana ISO), y en la Mac
    (3.9) no. Una fecha rota guardada hacía reventar la cuenta de «los últimos
    días» de la noche siguiente."""
    import re
    from datetime import date
    try:
        return bool(isinstance(fecha, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha)
                    and date.fromisoformat(fecha))
    except ValueError:
        return False


# El CCL que anota el propio servidor de dolarapi, con la fecha del dato
# (`main._actualizar_ccl`): el cierre de cada día, sin depender de cómo fecha
# argentinadatos. Manda: lo de argentinadatos no lo pisa.
FUENTE_PROPIA = "dolarapi"


def fechas_de_argentinadatos(filas: list, hoy: str) -> list:
    """Las filas de argentinadatos [(fecha, compra, venta)] con la fecha del CIERRE
    que traen, sólo de los días anteriores a `hoy`.

    DESDE SEPTIEMBRE DE 2026 LA FUENTE FECHA CADA CIERRE CON EL DÍA SIGUIENTE.
    Medido el 06/11/2026 (auditoría del contado con liqui, H1 del servidor): de
    2013 a agosto de 2026 la fila del sábado repetía la del viernes (el último
    cierre) en todos los fines de semana; desde el 12/09 repite la del LUNES y no
    la del viernes, o sea que la fila del lunes trae el cierre del viernes, la del
    martes el del lunes. Y contra el dólar que implican los CEDEARs en la Bolsa, la
    variación de cada día acompaña a la fila del día siguiente (correlación 0,77 y
    0,92 en septiembre y octubre; con la del mismo día, 0,09 y −0,24; hasta agosto
    era al revés). Sin corregirlo, cada vela del estimado iba con el dólar de la
    rueda anterior y la variación del día de BAC quedaba peor que con el MEP.

    Cómo se corrige sin atarse a una fecha (la fuente puede volver a cambiar): cada
    sábado dice de qué lado está su semana —igual al viernes y distinto del lunes,
    alineada; igual al lunes y distinto del viernes, corrida; si no, no dice nada— y
    cada fila toma lo que dice el sábado más cercano. En una semana corrida, la fila
    del día X es el cierre del día anterior. Lo que queda en hoy o después, con la
    fecha ya corregida, no se usa: mientras el día no cerró, la fuente publica el
    valor del momento (el de cada día lo anota el servidor de dolarapi después del
    cierre, `FUENTE_PROPIA`). Con la fecha corregida y no antes: en una semana
    corrida la fila de HOY es el cierre de AYER, y descartándola antes de
    corregirla, ayer quedaba sin su dólar hasta la noche siguiente (medido el
    06/11/2026 a las 21: la vela del 05/11 iba con el cierre del 04/11).

    Una fila con la fecha o el valor rotos no entra, y se descarta ANTES de juntar
    las filas por fecha: si no, una rota que llegaba después de la buena del mismo
    día la borraba, y ese día quedaba sin dólar (`guardar_ccl` descarta la rota,
    pero ya sin la buena)."""
    from bisect import bisect_left
    from datetime import date, timedelta
    validas = {f: (c, v) for f, c, v in filas if _fecha_valida(f) and punta_media(c, v)}
    medio = {f: punta_media(c, v) for f, (c, v) in validas.items()}
    marcas = []                                     # [(sábado, corrida)]
    for f in sorted(medio):
        x = date.fromisoformat(f)
        if x.weekday() != 5:
            continue
        sab, vie, lun = medio[f], medio.get((x - timedelta(days=1)).isoformat()), \
            medio.get((x + timedelta(days=2)).isoformat())
        if sab is None or vie is None or lun is None:
            continue
        if sab == vie and sab != lun:
            marcas.append((f, False))
        elif sab == lun and sab != vie:
            marcas.append((f, True))
    if not marcas:
        return [(f, c, v) for f, (c, v) in sorted(validas.items()) if f < hoy]
    sabados = [s for s, _ in marcas]

    def corrida(f):
        i = bisect_left(sabados, f)
        cerca = [j for j in (i - 1, i) if 0 <= j < len(sabados)]
        j = min(cerca, key=lambda j: abs((date.fromisoformat(sabados[j]) - date.fromisoformat(f)).days))
        return marcas[j][1]
    out = {}
    for f in sorted(validas):          # en orden: si dos caen en el mismo día, gana la más nueva
        dia = (date.fromisoformat(f) - timedelta(days=1)).isoformat() if corrida(f) else f
        out[dia] = validas[f]
    return [(f, c, v) for f, (c, v) in sorted(out.items()) if f < hoy]


def guardar_ccl(conn, filas: list, fuente: str, hasta: str = None) -> int:
    """Guarda el CCL de cada día: `filas` = [(fecha 'YYYY-MM-DD', compra, venta)] de
    la fuente; el valor es el MEDIO (`punta_media`). Escribe las fechas que faltan
    y vuelve a escribir las últimas `DIAS_CCL_REVISAR` (ver arriba), hasta `hasta`
    (los días cerrados: `main._actualizar_ccl`). Lo que anotó el servidor de
    dolarapi (`FUENTE_PROPIA`) no lo pisa otra fuente. No hace commit. Devuelve
    cuántas escribió."""
    from datetime import date, datetime, timedelta
    valores = {}
    for fecha, compra, venta in filas:
        if not _fecha_valida(fecha) or (hasta and fecha > hasta):
            continue
        v = punta_media(compra, venta)
        if v:
            valores[fecha] = v
    if not valores:
        return 0
    ya = {r["date"]: r["source"] for r in conn.execute(
        "SELECT date, source FROM bond_indices_daily WHERE index_name = ?", (INDICE_CCL,)).fetchall()}
    revisar = ((date.fromisoformat(max(ya)) - timedelta(days=DIAS_CCL_REVISAR)).isoformat()
               if ya else "")
    ahora = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    nuevas = [(INDICE_CCL, f, v, fuente, ahora) for f, v in sorted(valores.items())
              if (f not in ya or f >= revisar or fuente == FUENTE_PROPIA)
              and (fuente == FUENTE_PROPIA or ya.get(f) != FUENTE_PROPIA)]
    if nuevas:
        # De a una sentencia por fila (como el respaldo del blue): un INSERT con
        # varias filas y la misma fecha dos veces lo rechaza Postgres.
        conn.executemany(SQL_GUARDAR_INDICE, nuevas)
    return len(nuevas)




# ─── El costo de un lote ─────────────────────────────────────────────────────

def costo_del_lote(invested, buy_price, quantity):
    """Lo que costó un lote, en SU moneda y sin comisiones: el `invested` de la
    fila y, si la fila no lo tiene, precio × cantidad. None si no hay con qué
    saberlo.

    POR QUÉ ACÁ Y NO EN CADA MOTOR
    ──────────────────────────────
    `positions.invested` puede ser NULL: `POST /api/positions` acepta un alta con
    precio y cantidad y sin "invertido". El alta le descontaba a la caja
    `invested ?? precio × cantidad` y en la fila guardaba el NULL: la plata salía
    y el lote quedaba anotado como si no hubiera costado nada.

    Aguas abajo, cada motor leía ese NULL por su cuenta. Los tres de venta
    (`sell_position_fifo`, `persister._persist_sell_fifo`, `rebuild._replay_asset`)
    tenían la red "sin costo guardado → precio × cantidad" SÓLO en la rama de
    dólares; la de pesos restaba `(entry_invested or 0)` y anotaba todo lo cobrado
    como ganancia (medido: 25,6 donde eran 9,6). Los dos de amortización de bonos
    no la tenían en ninguna moneda.

    Ahora la cuenta es una y la usan el alta (para la caja Y para la fila), la
    edición y los cinco motores.

    ⚠️ `is None`, NO "¿tiene valor?". Un `invested = 0` explícito es un costo
    cero que alguien cargó (el alta le descuenta 0 a la caja), no un dato que
    falta: no se pisa con precio × cantidad.

    La red va ANTES de `costo_en_moneda_de_venta`: precio × cantidad está en la
    moneda del lote, así que se convierte igual que un `invested` guardado. La
    red vieja de la rama de dólares se aplicaba después y no convertía nada.
    """
    if invested is not None:
        return float(invested)
    if buy_price is None or quantity is None:
        return None
    return float(buy_price) * float(quantity)


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


def fx_version_lectura(conn, uid: int) -> str:
    """La misma respuesta que `fx_version`, pero SOLO LEE: no persiste la versión de
    una cuenta virgen. Es para lo que no puede escribir: un GET, o el ensayo de una
    corrección (que además tomaría el candado de escritura de SQLite sin necesidad).

    La respuesta coincide con la que `fx_version` daría y guardaría en ese momento:
    la fila de config si existe; si no, v1 para una cuenta con historia y v2 para una
    virgen. Ante cualquier duda, v1 (no corrompe nada)."""
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
        return FX_V1 if tiene_historia else FX_V2
    except Exception:
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
