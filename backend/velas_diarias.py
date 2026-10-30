"""Velas diarias guardadas: la base del análisis técnico.

QUÉ ES. Para cada activo que alguien tiene o sigue, la vela de cada rueda
(apertura, máximo, mínimo, cierre y volumen) de los últimos 3 años, en la tabla
`velas_diarias`. Con esto se calculan después la media de 200 días, el RSI, el
máximo del año, el volumen inusual y los giros para Fibonacci, sin salir a
pedirle a Yahoo cada vez que alguien abre una pantalla.

POR QUÉ 3 AÑOS. La ficha muestra hasta 2 años, y la media de 200 ruedas del
primer día de esos 2 años necesita ~10 meses de antes. 3 años cubren eso.

POR QUÉ NO ES `asset_price_history` (price_history.py), aunque se parezcan.
Las dos guardan precios por día, pero con reglas opuestas:
  · `asset_price_history` NO PISA: un precio guardado es el hecho de esa fecha y
    sirve para valuar una cartera en el pasado.
  · Acá SÍ se pisa. Cuando una acción se divide (split 4 a 1), Yahoo reescribe
    toda la historia vieja dividida por 4. Si guardáramos lo viejo sin pisar, el
    gráfico mostraría una caída de 75% que no existió y la media de 200 diría
    "bajista" durante 10 meses. Por eso cada noche se compara lo que ya estaba
    guardado con lo que trae Yahoo: si los días que se repiten no coinciden, la
    historia cambió y se baja entera de nuevo.

QUÉ CIERRE SE GUARDA. El de Yahoo con `auto_adjust=False`: ajustado por splits
pero NO por dividendos. Es el que muestra TradingView por defecto, así los
niveles que ve el usuario en Rendi son los mismos que ve allá.

QUÉ SÍMBOLO. El de Yahoo, tal cual: 'AAPL' (Apple en dólares, en Nueva York),
'AAPL.BA' (el CEDEAR en pesos), 'GGAL.BA', 'BTC-USD'. De un CEDEAR se guardan
las dos series: la acción de afuera (en dólares, la que define la tendencia de
verdad) y el CEDEAR en pesos (para la vista "en pesos"). Qué serie se lee para
cada pantalla lo decide quien calcula los indicadores, no esta tabla.

CUÁNDO CORRE. Al final de la foto diaria (`_run_daily_snapshot_job`), que ya
dispara un cron externo todas las noches después del cierre de Nueva York y de
Buenos Aires. No hace falta otro cron. Y A PEDIDO, cuando alguien abre la ficha
de un activo que nadie sigue (desde el mapa de calor o el buscador): ver
`tickers_a_pedido` y `asegurar`, con sus frenos.
"""
import logging
import math
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Cuánto se baja la primera vez (o cuando la historia cambió).
PERIODO_COMPLETO = "3y"
# Cuánto se baja las noches siguientes: sobra para cubrir fines de semana,
# feriados largos y alguna noche que el trabajo no corrió.
PERIODO_INCREMENTAL = "1mo"
# Se borra lo más viejo que esto.
DIAS_GUARDADOS = 3 * 366
# Si un día que ya estaba guardado vuelve con un cierre distinto en más de esto,
# la historia fue reescrita (split, corrección de Yahoo) y se baja entera.
# 1,5% deja pasar el redondeo y las correcciones chicas de un cierre; un split
# mueve el precio 50% o más.
TOLERANCIA_REESCRITURA = 0.015
# Cuántos días repetidos distintos alcanzan para decir "la historia cambió". Un
# split mueve TODOS los días anteriores a él; Yahoo corrigiendo un cierre suelto
# mueve uno. No es "la mayoría": si Yahoo aplica el split dos semanas tarde, la
# mayoría de los días del último mes ya vienen después del split y son iguales.
DIAS_DISTINTOS_REESCRITURA = 3
# Cada cuánto se baja la historia entera aunque no se haya visto nada raro: la
# red de seguridad para lo que la comparación del último mes no puede ver (un
# split que Yahoo ajusta más de un mes tarde).
DIAS_ENTRE_COMPLETAS = 30
# Cuántos tickers se le piden a Yahoo por tanda, y el tope de cada tanda.
TANDA = 25
TOPE_TANDA_SEG = 120.0
# Tope de la corrida entera: lo que no entró queda para la noche siguiente (los
# que nunca se bajaron van primero).
TOPE_CORRIDA_SEG = 15 * 60
# El S&P 500 se guarda siempre, lo tenga alguien o no: es contra lo que la ficha
# compara cuánto se mueve un papel en un día normal (movimiento.py).
SP500 = "^GSPC"

# ─── Qué activos se siguen ───────────────────────────────────────────────────

def _yahoo_de(asset: str, asset_type: str, en_pesos: bool, es_cripto,
              cedears_byma: frozenset = frozenset()) -> list:
    """Los tickers de Yahoo que representan este activo. [] = no tiene serie
    técnica (efectivo, bonos, letras, fondos, monedas estables).

    `cedears_byma`: los códigos en pesos que BYMA lista como CEDEAR. Sirve para
    reconocer un CEDEAR que vino sin `asset_type` (SPY importado en IOL): sin
    esto sólo se guardaba su precio en pesos y no la acción de afuera."""
    from cripto import CRIPTO_ESTABLES
    from snapshots_job import _FIXED_INCOME_TYPES, simbolo_byma
    from main import CEDEAR_USD_RATIOS
    a = (asset or '').strip().upper()
    tipo = (asset_type or '').strip().upper()
    if not a or a in ('USD', 'ARS') or a in CRIPTO_ESTABLES or a.startswith('FCI:'):
        return []
    if tipo in _FIXED_INCOME_TYPES or _es_bono(a):
        return []
    if es_cripto(a):
        return [es_cripto(a)]
    if a.endswith('.BA'):
        a, en_pesos = a[:-3], True
    pesos = simbolo_byma(a)
    es_cedear = tipo == 'CEDEAR' or (en_pesos and pesos[:-3] in cedears_byma)
    if es_cedear:
        if a in CEDEAR_USD_RATIOS:
            # Su '.BA' en Yahoo cotiza en dólares y roto (BAC ≈ 9): la serie en
            # pesos se arma de la acción de afuera, como el gráfico de la ficha.
            return [ticker_de_afuera(a)]
        # La acción de afuera (dólares) y el CEDEAR en pesos. Es la ÚNICA rama
        # que devuelve dos: `_seguimiento` reconoce el par por esta forma.
        return [ticker_de_afuera(a), pesos]
    return [pesos] if en_pesos else [ticker_de_afuera(a)]


def ticker_de_afuera(a: str) -> str:
    """El nombre con que Yahoo cotiza la acción de afuera: las acciones con
    clase van con guión ('BRK.B' → 'BRK-B'). Con el punto, Yahoo no la encuentra
    y la serie en dólares de Berkshire no se guardaba (auditoría 22/10). La usa
    también `tecnico.serie` para leerla: un solo traductor."""
    a = (a or '').strip().upper()
    return a.replace('.', '-') if '.' in a and not a.endswith('.BA') else a


def _cedears_de_byma() -> frozenset:
    """Los códigos que BYMA lista como CEDEAR (data912 → arg_cedears, la misma
    fuente que ya cotiza los CEDEARs en pesos). Si data912 no contesta, vacío:
    los CEDEARs etiquetados se siguen igual y a los otros les falta sólo la serie
    en dólares esa noche."""
    try:
        from main import _fetch_data912_equities
        feed = _fetch_data912_equities() or {}
    except Exception as ex:
        log.warning("velas: no se pudo leer la lista de CEDEARs de BYMA: %s", ex)
        return frozenset()
    return frozenset(s for s, v in feed.items() if (v or {}).get('mercado') == 'arg_cedears')


def _es_bono(asset: str) -> bool:
    try:
        from pricing.bond_amortization import is_amortizing_bond
        return bool(is_amortizing_bond(asset))
    except Exception:
        return False


# Cuántos tickers de Yahoo puede sumar UNA persona a la descarga de la noche, por
# todas las puertas juntas (lo que tiene, lo que sigue, sus alertas técnicas, lo
# que operó). El 22/10 se topeó la watchlist (100); las alertas técnicas fueron
# otra puerta a la misma lista, sin tope y con cualquier símbolo con forma de
# ticker: una cuenta metió 89 inventados (auditoría E4, 29/10). El tope va acá,
# en la SALA, no en cada puerta: la próxima puerta que se abra queda cubierta.
# Una cartera grande tiene ~60 activos (un CEDEAR son dos tickers) más 100 de
# watchlist: 300 sobra para una persona y frena a un script.
TICKERS_POR_PERSONA = 300


def simbolos_a_seguir(conn) -> list:
    """Todos los tickers de Yahoo que hacen falta: lo que alguien tiene en
    cartera, lo que alguien sigue en su watchlist, lo que alguien vigila con
    una alerta técnica y lo que alguien operó."""
    return sorted(_seguimiento(conn)[0])


def _seguimiento(conn):
    """(tickers, pares): lo de `_seguimiento_por_persona` sin el detalle de
    quién aporta qué."""
    tickers, pares, _ = _seguimiento_por_persona(conn)
    return tickers, pares


def _seguimiento_por_persona(conn):
    """(tickers, pares, de_cada_una): los tickers de Yahoo a seguir y, de cada CEDEAR, su
    par {'XLE.BA': 'XLE'} (el CEDEAR en pesos y la acción de afuera), que es
    contra lo que la lista de cambios de ratio (`cambios_ratio`) compara la
    serie en pesos.

    El par sale de saber que ES un CEDEAR (`_yahoo_de`), no de que dos tickers
    se llamen igual: AGRO.BA es Agrometal y AGRO en Nueva York es Adecoagro.

    "En pesos" se decide con la MISMA regla que la valuación
    (`snapshots_job.position_price_key`): si la posición se valúa por su '.BA',
    su serie en pesos es la del '.BA'. Reinventar esa regla acá es lo que hizo
    que un CEDEAR comprado por dólar-MEP pidiera el ticker equivocado (bug C1).

    Cada persona suma hasta `TICKERS_POR_PERSONA`, en este orden: lo que
    tiene, lo que sigue, sus alertas técnicas, lo que operó. Lo que pasa de ahí
    queda afuera (y se anota en el log). `de_cada_una`: {uid: [sus tickers, en
    ese orden]}, para repartir la noche por turnos (`_por_turnos`)."""
    from cripto import yahoo_de_cripto
    from snapshots_job import _broker_name_sets, position_price_key, simbolo_byma

    cedears = _cedears_de_byma()
    # {uid: [lista de tickers de un activo]} en el orden de las puertas.
    por_persona = {}

    def _anotar_de(uid, ys):
        if ys:
            por_persona.setdefault(uid, []).append(ys)
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, user_id, name, currency, parent_broker_id FROM brokers").fetchall()]
    por_usuario = {}
    for b in brokers:
        por_usuario.setdefault(b['user_id'], []).append(b)
    sets = {uid: _broker_name_sets(bs) for uid, bs in por_usuario.items()}

    for r in conn.execute(
            """SELECT user_id, broker, asset, asset_type, currency, invested, quantity
               FROM positions
               WHERE COALESCE(is_cash, 0) = 0 AND COALESCE(quantity, 0) > 0""").fetchall():
        p = dict(r)
        ars, ar_usd = sets.get(p['user_id'], (set(), set()))
        clave = position_price_key(p, ars, ar_usd)
        en_pesos = str(clave).upper().endswith('.BA')
        _anotar_de(p['user_id'], _yahoo_de(p['asset'], p.get('asset_type'), en_pesos, yahoo_de_cripto, cedears))

    for r in conn.execute("SELECT user_id, symbol, asset_type FROM watchlist").fetchall():
        sym = (r['symbol'] or '').upper()
        _anotar_de(r['user_id'], _yahoo_de(sym, r['asset_type'], sym.endswith('.BA'), yahoo_de_cripto, cedears))

    # Las alertas técnicas (alerts_engine.evaluar_tecnicas) miran la serie de la
    # ficha: sin esto, una alerta sobre un activo que nadie tiene no avisaba
    # nunca. El activo viene pelado ('AAPL', 'GGAL'): en pesos hace falta el
    # '.BA' — el de una acción argentina, o el de un CEDEAR que BYMA lista.
    # Sólo las de un activo REAL (`es_activo_real`, la regla del alta): una
    # alerta vieja con un símbolo inventado no le pide nada a Yahoo.
    for r in conn.execute(
            "SELECT user_id, symbol, currency, accion_local FROM alerts "
            "WHERE kind = 'tecnica' AND active = 1").fetchall():
        sym = (r['symbol'] or '').upper()
        if not es_activo_real(conn, sym, r['user_id']):
            continue
        en_pesos = bool(r['accion_local']) or (
            (r['currency'] or '').upper() == 'ARS' and simbolo_byma(sym)[:-3] in cedears)
        _anotar_de(r['user_id'], _yahoo_de(sym, None, en_pesos, yahoo_de_cripto, cedears))

    # Lo que alguien VENDIÓ y compró dentro de lo que se guarda: el diario de
    # operaciones de Movimientos dice cómo estaba la tendencia el día de la
    # compra (tecnico.tendencias_en_fechas). Sin esto, un activo que ya no tenés
    # no tenía velas y toda tu historia de cerradas decía «sin dato». La
    # operación no guarda `asset_type`: un CEDEAR en pesos se reconoce por la
    # lista de BYMA (`cedears`), igual que uno importado sin tipo. Los
    # dividendos e intereses no son una compra y no entran; un cupón es de un
    # bono, que no tiene serie técnica (`_yahoo_de` devuelve []).
    from fechas import hoy_art_date
    piso = (hoy_art_date() - timedelta(days=DIAS_GUARDADOS)).isoformat()
    # GROUP BY + MAX y no DISTINCT + ORDER BY entry_date: Postgres no deja
    # ordenar un DISTINCT por una columna que no está en el SELECT, y la
    # consulta entera (y con ella la noche) se caía (re-test E4, 29/10).
    for r in conn.execute(
            """SELECT user_id, broker, asset, currency, MAX(entry_date) AS ultima FROM operations
               WHERE entry_date IS NOT NULL AND entry_date >= ?
                 AND COALESCE(op_type, '') NOT IN ('Compra', 'Dividendo', 'Interés')
               GROUP BY user_id, broker, asset, currency
               ORDER BY user_id, ultima DESC""",
            (piso,)).fetchall():
        p = dict(r)
        ars, ar_usd = sets.get(p['user_id'], (set(), set()))
        clave = position_price_key(p, ars, ar_usd)
        en_pesos = str(clave).upper().endswith('.BA')
        _anotar_de(p['user_id'], _yahoo_de(p['asset'], None, en_pesos, yahoo_de_cripto, cedears))

    tickers, pares, topados, de_cada_una = set(), {}, {}, {}
    for uid, listas in por_persona.items():
        suyos, orden = set(), []
        for ys in listas:
            nuevos = [y for y in ys if y and y not in suyos]
            if len(suyos) + len(nuevos) > TICKERS_POR_PERSONA:
                topados[uid] = topados.get(uid, 0) + 1
                continue
            suyos.update(nuevos)
            orden += nuevos
            if len(ys) == 2:   # la forma de un CEDEAR: [afuera, pesos]
                pares[ys[1]] = ys[0]
        tickers |= suyos
        de_cada_una[uid] = orden
    if topados:
        log.warning("velas: %d persona(s) pasaron el tope de %d tickers por persona; quedaron "
                    "afuera %d activos (uid: %s)", len(topados), TICKERS_POR_PERSONA,
                    sum(topados.values()), sorted(topados)[:20])

    tickers.add(SP500)
    tickers.discard('')
    tickers.discard(None)
    return tickers, pares, de_cada_una


def _turno(estado: dict, t: str, hoy: str) -> int:
    """Primero lo que nunca se intentó (0), después lo que necesita la historia
    entera (1), después la puesta al día (2), y AL FINAL lo que falló la última
    vez (3). Antes "lo que nunca se bajó" iba primero siempre, y un símbolo que
    nunca trae datos (inventado en una watchlist) nunca deja de ser "nunca
    bajado": con miles, se comían el tope de la noche y los activos de verdad no
    se actualizaban (auditoría de seguridad 22/10)."""
    e = estado.get(t)
    if e is None:
        return 0
    if not e.get('ok'):
        return 3
    return 1 if _toca_completa(e, hoy) else 2


def _por_turnos(conn, de_cada_una: dict, hoy: str) -> list:
    """El orden de la noche: por TURNOS entre personas, no todo lo de una
    adelante de todo lo de otra. Ronda 1: lo primero de cada persona; ronda 2:
    lo segundo; etc. Cada persona ordena lo suyo por `_turno`. Lo que falló la
    última vez va en una segunda vuelta, después de todo lo demás de todos.

    Por qué: lo «nunca intentado» va primero (para que lo que alguien acaba de
    sumar tenga su historia), y una cuenta que mete 300 inventados por día los
    tiene siempre nunca intentados. Con 3 clientes de un asesor más una cuenta
    Pro, la noche tuvo 1.300 inventados primero y los 7 reales en la última
    tanda (re-test E4, 29/10): si la noche se cortaba por tiempo, lo de verdad
    no se actualizaba. Por turnos, cada persona avanza al mismo ritmo: los que
    meten mucho sólo se atrasan a sí mismos."""
    estado = {r['symbol']: dict(r) for r in conn.execute(
        "SELECT symbol, ultima_completa, ok FROM velas_estado").fetchall()}
    vueltas = ([], [])
    for uid in sorted(de_cada_una, key=str):
        suyos = sorted(de_cada_una[uid], key=lambda t: _turno(estado, t, hoy))   # estable: el orden de las puertas
        for v, lista in enumerate(([t for t in suyos if _turno(estado, t, hoy) < 3],
                                   [t for t in suyos if _turno(estado, t, hoy) == 3])):
            vueltas[v].append(lista)
    orden, puestos = [SP500], {SP500}
    for listas in vueltas:
        for k in range(max((len(x) for x in listas), default=0)):
            for lista in listas:
                if k < len(lista) and lista[k] not in puestos:
                    puestos.add(lista[k])
                    orden.append(lista[k])
    return orden


# ─── Bajar y guardar ─────────────────────────────────────────────────────────

def _numero(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _velas_de(df, hoy: str) -> dict:
    """{fecha: (o, h, l, c, v)} de una tabla de Yahoo. Se descartan:
      · las filas sin cierre válido: yfinance devuelve ruedas de '.BA' con
        volumen pero precios en NaN, y eso no es una rueda;
      · la vela de HOY (fecha UTC): a la hora del cron, la de una cripto es de
        3 horas y todavía se mueve. La noche siguiente entra completa."""
    out = {}
    if df is None or getattr(df, 'empty', True):
        return out
    for idx, row in df.iterrows():
        f = idx.date().isoformat()
        if f >= hoy:
            continue
        c = _numero(row.get('Close'))
        if c is None or c <= 0:
            continue
        o, h, l = (_numero(row.get(k)) for k in ('Open', 'High', 'Low'))
        vol = _numero(row.get('Volume'))
        # Una vela con máximo/mínimo roto se guarda igual, pero sólo con cierre:
        # un máximo de 0 arruinaría el "máximo del año" y los giros de Fibonacci.
        if not (h and l and h >= c >= l > 0):
            h = l = None
        out[f] = (o if o and o > 0 else None, h, l, c, vol if vol and vol >= 0 else None)
    return out


def _bajar(ticker: str, periodo: str):
    from pricing import yahoo as _yahoo
    return _yahoo._historia(ticker, periodo, '1d', False, 10.0)


def _guardar(conn, ticker: str, velas: dict, *, completa: bool) -> int:
    """Una bajada COMPLETA reemplaza todo lo del ticker (si Yahoo reescribió la
    historia, no puede quedar ningún día viejo); una incremental pisa sus días."""
    if completa:
        conn.execute("DELETE FROM velas_diarias WHERE symbol=?", (ticker,))
    for f, (o, h, l, c, v) in velas.items():
        conn.execute(
            """INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(symbol, date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume,
                 fetched_at=datetime('now')""",
            (ticker, f, o, h, l, c, v))
    return len(velas)


def _historia_reescrita(conn, ticker: str, velas: dict) -> bool:
    """¿Los días que ya teníamos vuelven con otro cierre? Entonces Yahoo
    reescribió la historia (split) y lo guardado no sirve más.

    Alcanzan `DIAS_DISTINTOS_REESCRITURA` días distintos (o todos, si se
    repiten menos): un split mueve todos los días anteriores a él, mientras que
    Yahoo corrigiendo un cierre suelto mueve uno, y eso alcanza con pisarlo."""
    if not velas:
        return False
    fechas = sorted(velas)
    rows = conn.execute(
        "SELECT date, close FROM velas_diarias WHERE symbol=? AND date>=? AND date<=?",
        (ticker, fechas[0], fechas[-1])).fetchall()
    comparados = distintos = 0
    for r in rows:
        nueva = velas.get(r['date'])
        if nueva and r['close']:
            comparados += 1
            if abs(nueva[3] / r['close'] - 1) > TOLERANCIA_REESCRITURA:
                distintos += 1
    return distintos >= DIAS_DISTINTOS_REESCRITURA or (0 < comparados == distintos)


def _anotar(conn, ticker: str, *, completa: bool, ok: bool, filas: int = 0, error: str = None):
    # `CASE WHEN ?=1`, no `CASE WHEN ?`: SQLite acepta un entero como condición,
    # Postgres exige un booleano.
    conn.execute(
        """INSERT INTO velas_estado (symbol, ultima_corrida, ultima_completa, ok, filas, error)
           VALUES (?, datetime('now'), CASE WHEN ?=1 THEN datetime('now') END, ?, ?, ?)
           ON CONFLICT(symbol) DO UPDATE SET
             ultima_corrida=datetime('now'),
             ultima_completa=CASE WHEN ?=1 THEN datetime('now') ELSE velas_estado.ultima_completa END,
             ok=excluded.ok, filas=excluded.filas, error=excluded.error""",
        (ticker, 1 if completa else 0, 1 if ok else 0, filas, error, 1 if completa else 0))


def _toca_completa(est: dict, hoy: str) -> bool:
    """Nunca se bajó entera, o hace más de `DIAS_ENTRE_COMPLETAS` que no."""
    ultima = (est or {}).get('ultima_completa')
    if not ultima:
        return True
    limite = (date.fromisoformat(hoy) - timedelta(days=DIAS_ENTRE_COMPLETAS)).isoformat()
    return str(ultima)[:10] <= limite


def actualizar(conn, tickers: list, *, bajar=None, hoy: str = None,
               tope_seg: float = TOPE_CORRIDA_SEG, tope_tanda: float = TOPE_TANDA_SEG,
               podar: bool = True, en_orden: bool = False) -> dict:
    """Pone al día las velas de estos tickers. Idempotente: correrlo dos veces
    seguidas no cambia nada.

    Los que nunca se bajaron (o se bajaron mal) van primero: con el tope de
    tiempo, una noche lenta deja sin actualizar a los que ya tenían 3 años, no
    a los que no tienen nada.

    Nunca se espera a Yahoo con una escritura abierta: cada tanda baja todo,
    escribe y confirma; los que hay que rebajar enteros (split) se piden DESPUÉS
    de confirmar. En SQLite una escritura abierta traba a todos los demás que
    quieren escribir, y Yahoo puede tardar 30 s en contestar.

    `tope_tanda`: cuánto se espera a Yahoo por tanda (la ficha a pedido espera
    poco). `podar`: borrar lo que quedó más viejo que 3 años; la ficha a pedido
    no lo hace (es un borrado de toda la tabla y lo hace la corrida de la noche).
    `en_orden`: respetar el orden de `tickers` (la noche lo trae repartido por
    personas, `_por_turnos`) en vez de ordenar por `_turno`."""
    from fechas import hoy_art
    from pricing import yahoo as _yahoo
    bajar = bajar or _bajar
    # El día argentino. Corriendo a cualquier hora deja afuera la vela que
    # todavía se mueve: la de una acción en plena rueda y la de una cripto, que
    # a partir de las 21:00 de acá ya está fechada "mañana" (UTC).
    hoy = hoy or hoy_art()
    fin = time.monotonic() + tope_seg

    estado = {r['symbol']: dict(r) for r in conn.execute(
        "SELECT symbol, ultima_completa, ok FROM velas_estado").fetchall()}
    if en_orden:
        # El orden ya viene decidido (la noche: `_por_turnos`).
        pendientes = list(dict.fromkeys(t for t in (tickers or []) if t))
    else:
        pendientes = sorted(set(t for t in (tickers or []) if t), key=lambda t: (_turno(estado, t, hoy), t))

    res = {"pedidos": len(pendientes), "completas": 0, "incrementales": 0,
           "reescritas": [], "sin_datos": [], "sin_tiempo": 0, "filas": 0}

    for i in range(0, len(pendientes), TANDA):
        if time.monotonic() >= fin:
            res["sin_tiempo"] = len(pendientes) - i
            break
        tanda = pendientes[i:i + TANDA]
        pedidos = {t: (PERIODO_COMPLETO if _toca_completa(estado.get(t), hoy)
                       else PERIODO_INCREMENTAL) for t in tanda}
        bajadas, _ = _yahoo.varios(lambda t: bajar(t, pedidos[t]), tanda,
                                   tope=tope_tanda, que="velas diarias")
        a_rebajar = []
        for t in tanda:
            velas = _velas_de(bajadas.get(t), hoy)
            completa = pedidos[t] == PERIODO_COMPLETO
            if not velas:
                _anotar(conn, t, completa=False, ok=False, error="Yahoo no devolvió velas")
                res["sin_datos"].append(t)
                continue
            if not completa and _historia_reescrita(conn, t, velas):
                a_rebajar.append(t)
                continue
            n = _guardar(conn, t, velas, completa=completa)
            _anotar(conn, t, completa=completa, ok=True, filas=n)
            res["filas"] += n
            res["completas" if completa else "incrementales"] += 1
        conn.commit()

        if a_rebajar:
            # Con la tanda ya confirmada: acá no hay ninguna escritura abierta.
            rebajadas, _ = _yahoo.varios(lambda t: bajar(t, PERIODO_COMPLETO), a_rebajar,
                                         tope=tope_tanda, que="velas diarias (historia cambiada)")
            for t in a_rebajar:
                velas = _velas_de(rebajadas.get(t), hoy)
                if not velas:
                    # Lo viejo queda como estaba (mejor que borrarlo sin reemplazo)
                    # y la noche siguiente se vuelve a detectar y a intentar.
                    _anotar(conn, t, completa=False, ok=False,
                            error="La historia cambió y no se pudo bajar de nuevo")
                    res["sin_datos"].append(t)
                    continue
                n = _guardar(conn, t, velas, completa=True)
                _anotar(conn, t, completa=True, ok=True, filas=n)
                res["filas"] += n
                res["completas"] += 1
                res["reescritas"].append(t)
            conn.commit()

    if podar:
        piso = (date.fromisoformat(hoy) - timedelta(days=DIAS_GUARDADOS)).isoformat()
        conn.execute("DELETE FROM velas_diarias WHERE date < ?", (piso,))
        conn.commit()
    return res


def correr(conn) -> dict:
    """La corrida nocturna completa: qué seguir, ponerlo al día y, con las velas
    ya guardadas, la lista única de cambios de ratio (`cambios_ratio`), a la que
    se le pasa de cada CEDEAR cuál es su acción de afuera. Un error de la lista
    no toca las velas."""
    from fechas import hoy_art
    tickers, pares, de_cada_una = _seguimiento_por_persona(conn)
    res = actualizar(conn, _por_turnos(conn, de_cada_una, hoy_art()), en_orden=True)
    res["podados_a_pedido"] = _podar_a_pedido(conn, tickers)
    # Cuándo corrió la NOCHE, aparte de cada activo: las fichas abiertas a pedido
    # también anotan su `ultima_corrida`, y /admin no tiene que confundirlas.
    _anotar(conn, MARCA_CORRIDA_NOCHE, completa=False, ok=True, filas=res["filas"])
    conn.commit()
    try:
        import cambios_ratio
        res["cambios_ratio"] = cambios_ratio.correr(
            conn, {ba[:-3]: afuera for ba, afuera in pares.items()})
    except Exception as ex:
        log.error("velas: la lista de cambios de ratio falló: %r", ex, exc_info=True)
        res["cambios_ratio"] = {"error": repr(ex)}
    return res


# ─── A pedido: la ficha de un activo que nadie sigue ─────────────────────────
# La ficha del activo se abre desde el mapa de calor, el buscador y la watchlist,
# también para un activo que nadie tiene ni sigue: la corrida de la noche no lo
# baja. Entonces se baja en el momento en que alguien abre su ficha, con frenos
# para que nadie pueda usar la ficha para disparar descargas sin límite:
#   · sólo activos que la app conoce (`se_puede_pedir`): los de los buscadores,
#     el mapa de calor, BYMA, o los que la persona tiene o sigue. Un símbolo
#     inventado, o miles de símbolos reales de cualquier bolsa, no entran;
#   · cuántos activos nuevos por hora y por día, por persona, y por hora entre
#     todos;
#   · lo que ya se intentó hoy no se vuelve a pedir (la vela de hoy no entra
#     hasta mañana: otra descarga no puede traer nada nuevo), ni lo que falló
#     en las últimas horas;
#   · a Yahoo se lo espera poco, y si otra persona ya lo está bajando no se
#     espera: la ficha dice "trayendo la historia" y vuelve a pedir;
#   · lo que nadie sigue ni volvió a mirar en `A_PEDIDO_DIAS_SIN_USO` días se
#     borra de noche (`_podar_a_pedido`): no se acumula basura.
A_PEDIDO_POR_PERSONA_HORA = 30
A_PEDIDO_POR_PERSONA_DIA = 100
A_PEDIDO_TODOS_HORA = 200
A_PEDIDO_TOPE_SEG = 10.0
A_PEDIDO_REINTENTO_HORAS = 6
A_PEDIDO_DIAS_SIN_USO = 45
# La fila de `velas_estado` donde la corrida de la noche anota que corrió. No es
# un ticker (`~` no pasa la validación de símbolos de la API): no choca con nada.
MARCA_CORRIDA_NOCHE = '~corrida_noche'

_a_pedido_cond = threading.Condition()
_a_pedido_en_curso = set()
_a_pedido_hechos = deque()   # (momento, uid) de cada ticker bajado a pedido


def _variantes(asset: str) -> set:
    """Las formas de escribir el mismo papel: con o sin '.BA', una cripto con
    o sin '-USD', y una acción con clase con punto o guión (BRK.B / BRK-B)."""
    a = (asset or '').strip().upper()
    base = a[:-3] if a.endswith('.BA') else a
    for suf in ('-USD', '-USDT', '-USDC'):
        if base.endswith(suf):
            base = base[:-len(suf)]
    return {a, base, base.replace('.', '-'), base.replace('-', '.')}


def _lo_conoce_la_app(v: set) -> bool:
    """Las listas de la app: lo que ofrecen los buscadores y lo que se puede
    tocar en Mercado (`ai.trade_tickers`, `home.market`) y lo que cotiza en BYMA
    (data912). `v`: las variantes del activo (`_variantes`)."""
    from ai import trade_tickers as tt
    from home import market as mk
    conocidos = (tt.CRYPTO_TICKERS | tt.US_TICKERS | tt.CEDEAR_TICKERS | tt.AR_STOCK_TICKERS)
    if v & conocidos:
        return True
    mercado = {x for lista in (mk.SP500_TOP_50, mk.MERVAL_TOP_25, mk.CRYPTO_TOP_30)
               for s in lista for x in _variantes(s)}
    if v & mercado:
        return True
    try:
        from main import _fetch_data912_equities
        if v & set((_fetch_data912_equities() or {}).keys()):
            return True
    except Exception:
        pass
    return False


def _lo_tiene(conn, v: set, uid, tablas) -> bool:
    marcas = ",".join("?" * len(v))
    for tabla, col in tablas:
        if conn.execute(f"SELECT 1 FROM {tabla} WHERE user_id=? AND UPPER({col}) IN ({marcas}) LIMIT 1",
                        (uid, *v)).fetchone():
            return True
    return False


def se_puede_pedir(conn, asset: str, uid) -> bool:
    """¿Se BAJA a pedido? Lo que la app conoce (`_lo_conoce_la_app`) y lo que la
    persona tiene, operó o sigue. Lo demás no se baja a pedido: sin esto,
    cualquier cuenta podía llenar la base pidiendo, de a 30 por hora, las
    decenas de miles de tickers reales que existen (auditoría 22/10).

    NO es la regla de qué se puede GUARDAR (una tesis, un dibujo, una alerta):
    ésa es `es_activo_real`. La lista de seguimiento acepta cualquier texto con
    forma de ticker, y si «lo sigo» bastara para guardar, cualquier símbolo
    inventado pasaba por esa puerta (re-test E4, 29/10)."""
    v = _variantes(asset)
    return _lo_conoce_la_app(v) or _lo_tiene(
        conn, v, uid, (("positions", "asset"), ("operations", "asset"), ("watchlist", "symbol")))


def es_activo_real(conn, asset: str, *uids) -> bool:
    """¿Existe este activo, para guardarle algo encima (una tesis, un dibujo,
    una alerta técnica)? LA regla, una sola:
      · lo conoce la app (`_lo_conoce_la_app`), o
      · tiene velas guardadas: lo bajó la noche o la ficha de alguien, o sea
        que Yahoo lo conoce y la ficha lo muestra con su gráfico. «Lo que la
        ficha muestra se puede dibujar, avisar y comentar»: YPF, SMCI o ARM no
        están en las listas de la app, y sin esto no se podían dibujar aunque
        el gráfico estuviera a la vista (re-test E3, 29/10), o
      · alguna de estas personas lo tiene o lo operó (un fondo no tiene
        velas, y su tesis igual vale).
    La lista de seguimiento NO alcanza: acepta cualquier texto, y un símbolo
    real que alguien sigue ya tiene velas (lo baja la noche, o su ficha).
    `uids`: de quién puede ser (los dibujos son del asesor que los hace, sobre
    el activo del cliente que mira)."""
    v = {x for x in _variantes(asset) if x}
    if not v:
        return False
    if _lo_conoce_la_app(v):
        return True
    yahoo = v | {x + '.BA' for x in v} | {x + '-USD' for x in v}
    marcas = ",".join("?" * len(yahoo))
    if conn.execute(f"SELECT 1 FROM velas_diarias WHERE symbol IN ({marcas}) LIMIT 1",
                    tuple(yahoo)).fetchone():
        return True
    return any(u and _lo_tiene(conn, v, u, (("positions", "asset"), ("operations", "asset")))
               for u in uids)


def tickers_a_pedido(asset: str, local: bool = False, cedears=None) -> list:
    """Los tickers de Yahoo que la ficha de `asset` necesita y se pueden bajar
    en el momento. La misma traducción que la corrida de la noche (`_yahoo_de`),
    con una excepción: de un CEDEAR se baja SÓLO la acción de afuera. Su serie
    en pesos se corrige con la lista de cambios de ratio (`cambios_ratio`), que
    se arma de noche y sólo para lo que alguien sigue; sin ella, el gráfico en
    pesos mostraría caídas que no existieron (XLE.BA −50 % el 05/12/2025). En
    pesos, la ficha usa la de afuera × el MEP de cada día (`tecnico.serie`).

    `local`: la ficha dice que es una acción argentina (su serie es la de BYMA).
    Un '.BA' necesita la lista de CEDEARs de BYMA para saber qué es: si data912
    no contesta, sólo se baja si es una acción argentina conocida (`local` lo
    manda la pantalla, pero también se puede escribir a mano). Mejor sin gráfico
    que uno equivocado guardado para todos."""
    from ai.trade_tickers import AR_STOCK_TICKERS
    from cripto import yahoo_de_cripto
    a = (asset or '').strip().upper()
    en_pesos = a.endswith('.BA') or bool(local)
    if cedears is None:
        cedears = _cedears_de_byma() if en_pesos else frozenset()
    ys = _yahoo_de(a, None, en_pesos, yahoo_de_cripto, cedears)
    if len(ys) == 2:          # la forma de un CEDEAR: [afuera, pesos]
        return [ys[0]]
    base = a[:-3] if a.endswith('.BA') else a
    if not cedears and any(t.endswith('.BA') for t in ys) and base not in AR_STOCK_TICKERS:
        return []
    return ys


def _ahora_utc() -> datetime:
    # `velas_estado.ultima_corrida` se guarda con datetime('now'): UTC, sin zona.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _necesita(conn, ticker: str, hoy: str, ahora: datetime) -> bool:
    """¿Hay que bajarlo? No, si:
      · su última vela es de ayer (la de hoy no entra hasta mañana: `_velas_de`);
      · ya se intentó HOY (día argentino), salga bien o mal: otra descarga hoy
        no puede traer nada nuevo. Un domingo, un lunes antes del cierre o el
        día después de un feriado, la última vela es de hace 2-4 días y antes
        eso se leía como "vieja": cada ficha volvía a bajar lo mismo y gastaba
        el cupo (auditoría 22/10);
      · se intentó hace menos de `A_PEDIDO_REINTENTO_HORAS`.
    Lo que sigue la corrida de la noche ya se intentó hoy: no se vuelve a pedir."""
    r = conn.execute("SELECT MAX(date) AS d FROM velas_diarias WHERE symbol=?", (ticker,)).fetchone()
    if r and r["d"] and (date.fromisoformat(hoy) - date.fromisoformat(str(r["d"])[:10])).days <= 1:
        return False
    e = conn.execute("SELECT ultima_corrida FROM velas_estado WHERE symbol=?", (ticker,)).fetchone()
    if e and e["ultima_corrida"]:
        try:
            cuando = datetime.fromisoformat(str(e["ultima_corrida"])[:19])
        except ValueError:
            return True
        from fechas import dia_art   # el día argentino de un instante UTC (regla única)
        if (dia_art(cuando) >= date.fromisoformat(hoy)
                or ahora - cuando < timedelta(hours=A_PEDIDO_REINTENTO_HORAS)):
            return False
    return True


def _hay_cupo(uid, n: int) -> bool:
    """¿Entran `n` tickers más en la última hora y en el último día para esta
    persona, y en la última hora para todos? Si entran, quedan anotados. Se
    llama con `_a_pedido_cond` tomado."""
    ahora = time.monotonic()
    while _a_pedido_hechos and ahora - _a_pedido_hechos[0][0] > 86400:
        _a_pedido_hechos.popleft()
    hora = [u for t, u in _a_pedido_hechos if ahora - t <= 3600]
    de_el_hora = sum(1 for u in hora if u == uid)
    de_el_dia = sum(1 for _, u in _a_pedido_hechos if u == uid)
    if (len(hora) + n > A_PEDIDO_TODOS_HORA or de_el_hora + n > A_PEDIDO_POR_PERSONA_HORA
            or de_el_dia + n > A_PEDIDO_POR_PERSONA_DIA):
        return False
    _a_pedido_hechos.extend((ahora, uid) for _ in range(n))
    return True


def asegurar(conn, tickers: list, uid, *, bajar=None, hoy: str = None):
    """Baja en el momento las velas de `tickers` que falten o estén viejas (ver
    `_necesita`), con los frenos de arriba. Devuelve None (listo, o no hacía
    falta), 'tope' (se llegó al cupo) o 'bajando' (otra persona lo está bajando
    ahora mismo: la ficha vuelve a pedir en unos segundos, sin dejar un hilo del
    servidor esperando)."""
    from fechas import hoy_art
    hoy = hoy or hoy_art()
    tickers = [t for t in dict.fromkeys(tickers or []) if t]
    faltan = [t for t in tickers if _necesita(conn, t, hoy, _ahora_utc())]
    if not faltan:
        return None
    # Una acción argentina que no tenía nada: su lista de cambios de cantidad
    # (YPFD 10 a 1) se arma después de bajarla, o el gráfico de hoy mostraría
    # el salto falso hasta la noche.
    nuevos_ba = [t for t in faltan if t.endswith('.BA') and not conn.execute(
        "SELECT 1 FROM velas_diarias WHERE symbol=? LIMIT 1", (t,)).fetchone()]
    with _a_pedido_cond:
        if set(faltan) & _a_pedido_en_curso:
            return "bajando"
        if not _hay_cupo(uid, len(faltan)):
            log.warning("velas a pedido: cupo lleno (uid=%s, %s)", uid, faltan)
            return "tope"
        _a_pedido_en_curso.update(faltan)
    try:
        # Se cierra la lectura antes de esperar a Yahoo: en Postgres quedaba una
        # transacción abierta los 10 s de la espera.
        conn.commit()
        actualizar(conn, faltan, bajar=bajar, hoy=hoy, tope_seg=A_PEDIDO_TOPE_SEG,
                   tope_tanda=A_PEDIDO_TOPE_SEG, podar=False)
        bajados = [t for t in nuevos_ba if conn.execute(
            "SELECT 1 FROM velas_diarias WHERE symbol=? LIMIT 1", (t,)).fetchone()]
        if bajados:
            import cambios_ratio
            # Sin `pares`: a pedido nunca se baja la serie en pesos de un CEDEAR
            # (`tickers_a_pedido`), así que un '.BA' bajado acá es una acción argentina.
            cambios_ratio.recalcular(conn, [t[:-3] for t in bajados], tope_seg=A_PEDIDO_TOPE_SEG)
    finally:
        with _a_pedido_cond:
            _a_pedido_en_curso.difference_update(faltan)
            _a_pedido_cond.notify_all()
    return None


def _podar_a_pedido(conn, seguidos) -> int:
    """Borra las velas de lo que nadie sigue y nadie miró en los últimos
    `A_PEDIDO_DIAS_SIN_USO` días (lo bajado a pedido, o lo que alguien dejó de
    tener). Lo que se mira se vuelve a bajar a pedido cuando está viejo, y eso
    renueva su `ultima_corrida`: lo que se usa no se borra."""
    limite = (_ahora_utc() - timedelta(days=A_PEDIDO_DIAS_SIN_USO)).strftime('%Y-%m-%d %H:%M:%S')
    seguidos = set(seguidos or [])
    viejos = [r["symbol"] for r in conn.execute(
        "SELECT symbol FROM velas_estado WHERE ultima_corrida < ?", (limite,)).fetchall()
        if r["symbol"] not in seguidos]
    for t in viejos:
        conn.execute("DELETE FROM velas_diarias WHERE symbol=?", (t,))
        conn.execute("DELETE FROM velas_estado WHERE symbol=?", (t,))
    conn.commit()
    return len(viejos)


# ─── Leer ────────────────────────────────────────────────────────────────────

def _crudas(conn, ticker: str, desde: str = None) -> list:
    """Las velas tal como las dio Yahoo, sin empalmar. Las lee `serie`; quien
    necesita lo crudo (la lista de cambios de ratio, la evidencia de un lote)
    lee la tabla con su propia consulta."""
    q = "SELECT date, open, high, low, close, volume FROM velas_diarias WHERE symbol=?"
    args = [ticker]
    if desde:
        q += " AND date >= ?"
        args.append(str(desde)[:10])
    return [dict(r) for r in conn.execute(q + " ORDER BY date", args).fetchall()]


def _empalmar(velas: list, g: dict) -> list:
    """Las velas en pesos con lo que dice la lista única de cambios de ratio
    (`cambios_ratio.para_el_grafico`):
      · escalones [(fecha, factor)]: lo ANTERIOR a `fecha` se lleva a la escala
        nueva (el precio ÷ factor; el volumen, en cantidad de CEDEARs, × factor).
        Cambios de ratio, escisiones (DuPont 03/11/2025) y precios rotos de nivel;
        sólo los que la serie guardada muestra (lo que Yahoo ya corrigió, no).
      · rotos: días que saltan y vuelven (ETHA 06/10/2026): se sacan.
      · pendientes: un salto de los últimos días que todavía no se sabe si se
        queda: se esconde desde ese día (no se reescala la historia por algo que
        puede ser un precio roto). La noche que haya 5 ruedas, se decide."""
    escalones = [(d, f) for d, f in (g.get("escalones") or []) if f and f > 0]
    rotos = set(g.get("rotos") or [])
    pendiente = min(g.get("pendientes") or [None], key=lambda d: d or "9999")
    if not escalones and not rotos and not pendiente:
        return velas
    out = []
    for v in velas:
        if v["date"] in rotos or (pendiente and v["date"] >= pendiente):
            continue
        f = 1.0
        for desde, factor in escalones:
            if v["date"] < desde:
                f *= factor
        if f != 1.0:
            v = {**v, **{k: (v[k] / f if v.get(k) is not None else None)
                         for k in ("open", "high", "low", "close")},
                 "volume": (v["volume"] * f if v.get("volume") is not None else None)}
        out.append(v)
    return out


def serie(conn, ticker: str, desde: str = None) -> list:
    """Las velas guardadas de un ticker, de la más vieja a la más nueva:
    [{date, open, high, low, close, volume}]. Las de una serie en pesos ('.BA')
    vienen empalmadas con la lista única de cambios de ratio (`cambios_ratio`):
    Yahoo no corrige los cambios de ratio de los CEDEAR en la especie en pesos
    (XLE.BA cae 50 % el 05/12/2025 sin que nada pase), y esa caída falsa dejaba
    la media de 200 en pesos diciendo "bajista" diez meses. [] si no hay: quien
    la usa tiene que decir "sin datos", nunca inventar. Es LA puerta para leer
    velas en un gráfico o una lectura: no leer la tabla a mano."""
    velas = _crudas(conn, ticker, desde)
    if not velas or not str(ticker).upper().endswith('.BA'):
        return velas
    import cambios_ratio
    return _empalmar(velas, cambios_ratio.para_el_grafico(conn, ticker))


def ultima_vela(conn, ticker: str):
    """La última vela de `ticker` por la puerta de `serie` (si la última vino
    rota, la anterior). None si no hay."""
    row = conn.execute("SELECT MAX(date) AS d FROM velas_diarias WHERE symbol=?", (ticker,)).fetchone()
    if not row or not row["d"]:
        return None
    desde = (date.fromisoformat(row["d"]) - timedelta(days=15)).isoformat()
    velas = serie(conn, ticker, desde)
    return velas[-1] if velas else None
