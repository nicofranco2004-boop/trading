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
Buenos Aires. No hace falta otro cron.
"""
import logging
import math
import time
from datetime import date, timedelta

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
            return [a]
        # La acción de afuera (dólares) y el CEDEAR en pesos.
        return [a, pesos]
    return [pesos] if en_pesos else [a]


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


def simbolos_a_seguir(conn) -> list:
    """Todos los tickers de Yahoo que hacen falta: lo que alguien tiene en
    cartera y lo que alguien sigue en su watchlist."""
    return sorted(_seguimiento(conn)[0])


def _seguimiento(conn):
    """(tickers, pares): los tickers de Yahoo a seguir y, de cada CEDEAR, su
    par {'XLE.BA': 'XLE'} (el CEDEAR en pesos y la acción de afuera), que es
    contra lo que la lista de cambios de ratio (`cambios_ratio`) compara la
    serie en pesos.

    El par sale de saber que ES un CEDEAR (`_yahoo_de`), no de que dos tickers
    se llamen igual: AGRO.BA es Agrometal y AGRO en Nueva York es Adecoagro.

    "En pesos" se decide con la MISMA regla que la valuación
    (`snapshots_job.position_price_key`): si la posición se valúa por su '.BA',
    su serie en pesos es la del '.BA'. Reinventar esa regla acá es lo que hizo
    que un CEDEAR comprado por dólar-MEP pidiera el ticker equivocado (bug C1)."""
    from cripto import yahoo_de_cripto
    from snapshots_job import _broker_name_sets, position_price_key

    cedears = _cedears_de_byma()
    tickers, pares = set(), {}

    def _sumar(ys):
        tickers.update(ys)
        if len(ys) == 2:   # la forma de un CEDEAR: [afuera, pesos]
            pares[ys[1]] = ys[0]
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
        _sumar(_yahoo_de(p['asset'], p.get('asset_type'), en_pesos, yahoo_de_cripto, cedears))

    for r in conn.execute("SELECT symbol, asset_type FROM watchlist").fetchall():
        sym = (r['symbol'] or '').upper()
        _sumar(_yahoo_de(sym, r['asset_type'], sym.endswith('.BA'), yahoo_de_cripto, cedears))

    tickers.discard('')
    tickers.discard(None)
    return tickers, pares


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
               tope_seg: float = TOPE_CORRIDA_SEG) -> dict:
    """Pone al día las velas de estos tickers. Idempotente: correrlo dos veces
    seguidas no cambia nada.

    Los que nunca se bajaron (o se bajaron mal) van primero: con el tope de
    tiempo, una noche lenta deja sin actualizar a los que ya tenían 3 años, no
    a los que no tienen nada.

    Nunca se espera a Yahoo con una escritura abierta: cada tanda baja todo,
    escribe y confirma; los que hay que rebajar enteros (split) se piden DESPUÉS
    de confirmar. En SQLite una escritura abierta traba a todos los demás que
    quieren escribir, y Yahoo puede tardar 30 s en contestar."""
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
    pendientes = sorted(set(t for t in (tickers or []) if t),
                        key=lambda t: (bool((estado.get(t) or {}).get('ultima_completa')), t))

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
                                   tope=TOPE_TANDA_SEG, que="velas diarias")
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
                                         tope=TOPE_TANDA_SEG, que="velas diarias (historia cambiada)")
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

    piso = (date.fromisoformat(hoy) - timedelta(days=DIAS_GUARDADOS)).isoformat()
    conn.execute("DELETE FROM velas_diarias WHERE date < ?", (piso,))
    conn.commit()
    return res


def correr(conn) -> dict:
    """La corrida nocturna completa: qué seguir, ponerlo al día y, con las velas
    ya guardadas, la lista única de cambios de ratio (`cambios_ratio`), a la que
    se le pasa de cada CEDEAR cuál es su acción de afuera. Un error de la lista
    no toca las velas."""
    tickers, pares = _seguimiento(conn)
    res = actualizar(conn, sorted(tickers))
    try:
        import cambios_ratio
        res["cambios_ratio"] = cambios_ratio.correr(
            conn, {ba[:-3]: afuera for ba, afuera in pares.items()})
    except Exception as ex:
        log.error("velas: la lista de cambios de ratio falló: %r", ex, exc_info=True)
        res["cambios_ratio"] = {"error": repr(ex)}
    return res


# ─── Leer ────────────────────────────────────────────────────────────────────

def serie(conn, ticker: str, desde: str = None) -> list:
    """Las velas guardadas de un ticker, de la más vieja a la más nueva:
    [{date, open, high, low, close, volume}]. [] si no hay: quien la usa tiene
    que decir "sin datos", nunca inventar."""
    q = "SELECT date, open, high, low, close, volume FROM velas_diarias WHERE symbol=?"
    args = [ticker]
    if desde:
        q += " AND date >= ?"
        args.append(str(desde)[:10])
    return [dict(r) for r in conn.execute(q + " ORDER BY date", args).fetchall()]
