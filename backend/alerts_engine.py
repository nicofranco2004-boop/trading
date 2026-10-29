"""Motor de evaluación de alertas personalizadas.

Tres tipos de alerta (ver schema en main.init_db). Las dos primeras se evalúan
en vivo, cada vez que pega el cron; la tercera, una vez por día (ver
`evaluar_tecnicas`, al final):
  • price_target — avisar cuando `symbol` cruza `threshold` en `direction`
    (above/below). Usa EDGE-TRIGGER con la columna `armed`: dispara SOLO en la
    transición no-cumplida → cumplida, nunca mientras el precio sigue del lado
    disparado. Re-arma cuando el precio vuelve a cruzar (repeat != 'once').
  • pct_move — avisar cuando un activo se mueve `threshold`% vs el cierre previo.
    `scope='holdings'` evalúa TODAS las tenencias del user; `scope='ticker'` una.
    Como el % es vs prev_close (que se resetea cada día), el anti-spam es por
    COOLDOWN por (alerta, símbolo) vía la tabla alert_events — no la columna
    armed (una alerta holdings tiene N símbolos, cada uno con su propio estado).
  • tecnica — avisar cuando pasa una señal del análisis técnico de la ficha
    (`senal`: cruzó su promedio de 200 / 50 días, el RSI cruzó 30 o 70, cerró
    en su máximo del año). Sale de las velas que se guardan de noche, con las
    cuentas de `tecnico.py`, y avisa una vez por cruce.

Precios: reusa los MISMOS rieles que el snapshot diario (fetch_prices_for_symbols
→ stocks/CEDEARs/cripto/FCI/bonos) para price_target, y para pct_move la
variación del día de `main._variacion_del_dia` (vía home.market._fetch_batch_quotes):
la MISMA que la columna "Var. día" de Posiciones — data912 para BYMA y bonos,
yfinance para EEUU y cripto. NUNCA dispara con precio None/stale.

Y nunca dispara con un porcentaje que no sea el de la rueda de HOY: cada quote
viaja con la fecha de la rueda que midió (`as_of`/`is_today`, ver home.market),
y si esa fecha no es la de hoy el número no se usa ni para disparar ni para
re-armar. Hacía falta porque antes de que abra el mercado —y cuando la barra del
día viene con los OHLC en NaN, que con los `.BA` pasa seguido— el proveedor
devuelve el cierre a cierre de AYER, y salía por mail con el título "hoy".

Fuera de la rueda (pre y post mercado de Wall Street): las pct_move "En el día"
también avisan si la acción —o, para un CEDEAR o una acción argentina, su acción
o ADR en Nueva York— se mueve más que el umbral en el pre o en el post. Ver
`_evaluar_fuera_de_rueda`: un aviso por franja y por día, sólo con operaciones
de verdad detrás, y SIN consumir la alerta del día (es un anticipo).

Entrega: reusa _send_push_to_user (Web Push) + billing.emails.send_alert_email
(Resend). Cada disparo queda logueado en alert_events (dedup + feed in-app), uno
por activo — pero el ENVÍO es uno por alerta y por ciclo: una alerta de "toda mi
cartera" se expande a todas las tenencias y un día movido dispara varias juntas.
Los disparos se acumulan durante el loop y salen agrupados al final.
"""
from __future__ import annotations
from money_fmt import fmt_num

import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

log = logging.getLogger("alerts")

VALID_KINDS = ("price_target", "pct_move", "tecnica")
# Las que se miran en vivo, cada vez que pega el cron (`evaluate_alerts`).
KINDS_EN_VIVO = ("price_target", "pct_move")
VALID_SCOPES = ("ticker", "holdings")
VALID_DIRECTIONS = ("above", "below", "either")
VALID_CHANNELS = ("push", "email", "both")
VALID_REPEATS = ("once", "daily", "always")


# ─── Precios ──────────────────────────────────────────────────────────────────

def _prices_for(symbols: list) -> dict:
    """Precio actual por símbolo en su RIEL (.BA→ARS, pelado→USD, FCI→NAV,
    bono→per-1). Mismo resolver que el snapshot diario."""
    syms = [s for s in set(symbols) if s]
    if not syms:
        return {}
    try:
        from snapshots_job import fetch_prices_for_symbols
        import main
        return fetch_prices_for_symbols(syms, main.CRYPTO_YF) or {}
    except Exception as ex:
        log.warning("alerts _prices_for falló: %s", ex)
        return {}


def _quotes_for(symbols: list) -> dict:
    """{symbol: {price, prev_close, change_pct, as_of, is_today}} para pct_move:
    la variación del día de Posiciones (`main._variacion_del_dia`)."""
    syms = [s for s in set(symbols) if s]
    if not syms:
        return {}
    try:
        from home.market import _fetch_batch_quotes
        from pricing import yahoo as _yahoo
        # Corrida de fondo con TODOS los símbolos de las alertas: el tope largo.
        return _fetch_batch_quotes(syms, tope=_yahoo.TOPE_FONDO_SEG) or {}
    except Exception as ex:
        log.warning("alerts _quotes_for falló: %s", ex)
        return {}


def price_for_alert(symbol: str, en_dolares: bool = False):
    """Precio actual de UN símbolo — para armar el edge-trigger al crear la
    alerta (arma según de qué lado del umbral está hoy). `en_dolares`: un CEDEAR
    vigilado en dólares (ver `cedear_en_dolares`)."""
    if en_dolares:
        return precios_cedear_en_dolares([symbol]).get(symbol)
    return _prices_for([symbol]).get(symbol)


# ─── CEDEAR en dólares ────────────────────────────────────────────────────────
# Un CEDEAR cotiza en la Bolsa en pesos (AAPL) y en dólares (AAPLD). Una alerta
# de precio lo guarda como 'AAPL.BA' + la moneda: 'ARS' mira el precio en pesos,
# 'USD' el precio en dólares — el MISMO que muestra el buscador de "Registrar
# compra" (main.cedears_con_dolares → cedears_dolar.universo: el AAPLD de hoy si
# está cerca de pesos ÷ MEP, si no pesos ÷ MEP).
#
# Antes la moneda era sólo un rótulo: «AAPL baja a US$ 15» se comparaba contra
# el precio EN PESOS (~$20.000) y no avisaba nunca. Por eso el alta rechaza una
# moneda que el activo no tiene (ver main.alerts_create).

def cedear_en_dolares(kind, scope, symbol, currency) -> bool:
    """¿Es una alerta de precio sobre un CEDEAR vigilado en dólares?

    Sólo el aviso de precio: en el de % la moneda no cambia nada que se vea (el
    movimiento es el del CEDEAR) y "toda mi cartera" se expande a símbolos que
    llevan su propio riel."""
    return (kind == "price_target" and (scope or "ticker") == "ticker"
            and bool(symbol) and str(symbol).upper().endswith(".BA")
            and str(currency or "").upper() == "USD")


def _es_cedear_usd(alert, symbol) -> bool:
    return cedear_en_dolares(_campo(alert, "kind"), _campo(alert, "scope"),
                             symbol, _campo(alert, "currency"))


def _campo(alert, k):
    try:
        return alert[k]
    except (KeyError, IndexError):
        return None


def cedears_con_dolares():
    """Los CEDEARs de la Bolsa con su precio en dólares (`main.cedears_con_dolares`),
    o None si la lista no se pudo armar (data912 caído): "no sé" no es "no tiene"."""
    try:
        import main
        items = (main.cedears_con_dolares() or {}).get("items")
    except Exception as ex:
        log.warning("alerts: no se pudo armar la lista de CEDEARs en dólares: %s", ex)
        return None
    return items or None


def _codigos(it) -> set:
    """Cómo puede venir escrito el CEDEAR en una alerta: el código de la Bolsa
    (BRKB.BA, el que arma priceSymbol) o el ticker de Rendi (BRK-B.BA)."""
    return {f"{c}.BA" for c in (it.get("pesos"), it.get("s")) if c}


def precios_cedear_en_dolares(symbols, items=None) -> dict:
    """{símbolo '.BA': precio en dólares} de los que tienen especie en dólares."""
    syms = {str(s).upper() for s in symbols if s and str(s).upper().endswith(".BA")}
    if not syms:
        return {}
    if items is None:
        items = cedears_con_dolares() or []
    out = {}
    for it in items:
        if not (it.get("dolares") and it.get("px_usd")):
            continue
        for cod in _codigos(it) & syms:
            out[cod] = float(it["px_usd"])
    return out


def tiene_precio_en_dolares(symbol):
    """True / False si el CEDEAR tiene (o no) especie en dólares; None si la
    lista no está (no se puede saber)."""
    items = cedears_con_dolares()
    if items is None:
        return None
    return str(symbol or "").upper() in precios_cedear_en_dolares([symbol], items)


def _holding_symbols(conn, uid: int) -> list:
    """Símbolos-de-precio (rail-aware) de las tenencias del user. Reusa
    build_price_symbols para no divergir de la valuación."""
    try:
        from snapshots_job import build_price_symbols
        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND (is_cash=0 OR is_cash IS NULL)",
            (uid,)).fetchall()]
        brokers = [dict(r) for r in conn.execute(
            "SELECT * FROM brokers WHERE user_id=?", (uid,)).fetchall()]
        return build_price_symbols(positions, brokers)
    except Exception as ex:
        log.warning("alerts _holding_symbols uid=%s falló: %s", uid, ex)
        return []


# ─── Normalización de símbolo (cripto) ───────────────────────────────────────

_CRYPTO = None

def _crypto_symbols() -> set:
    global _CRYPTO
    if _CRYPTO is None:
        try:
            import main
            _CRYPTO = set(getattr(main, "CRYPTO_SYMBOLS", None)
                          or getattr(main, "CRYPTO_YF", {}).keys())
        except Exception:
            _CRYPTO = set()
    return _CRYPTO


def _norm_sym(sym):
    """Cripto en broker AR se representa como 'BTC.BA' (build_price_symbols), pero
    NO cotiza así en yfinance. La valuamos por 'BTC' (→ BTC-USD, riel USD). Sin
    esto una alerta de cripto comprada en Cocos/Balanz nunca resolvía precio.
    Todo lo demás pasa igual."""
    if sym and sym.endswith(".BA") and sym[:-3] in _crypto_symbols():
        return sym[:-3]
    return sym


_SESION_US = (9, 30, 16, 0)     # NYSE/Nasdaq 09:30–16:00 hora de Nueva York
_SESION_BYMA = (11, 0, 17, 0)   # BYMA        11:00–17:00 hora argentina


def _en_rueda(local_dt, h1, m1, h2, m2) -> bool:
    if local_dt.weekday() >= 5:      # 5=sábado, 6=domingo
        return False
    minutos = local_dt.hour * 60 + local_dt.minute
    return (h1 * 60 + m1) <= minutos < (h2 * 60 + m2)


def _sesion_hoy(sym) -> str:
    """Qué día es "hoy" para el mercado de este símbolo. Una sola definición,
    compartida con el que estampa las cotizaciones — si el tope de "1 aviso por
    jornada" contara los días con otro almanaque que el `as_of` del quote, la
    jornada del tope y la de la rueda se correrían una respecto de la otra.

    Antes el tope contaba días UTC (`utcnow().strftime`), que cambian a las
    21:00 de Buenos Aires: un aviso disparado a las 22:00 quedaba anotado como
    del día SIGUIENTE y se comía el cupo de mañana."""
    try:
        from home.market import session_today
        return session_today(sym)
    except Exception:
        from fechas import hoy_art
        return hoy_art()


_AVISO_SIN_ZONEINFO = False


def rueda_en_horario(mercado: str, now) -> bool:
    """¿La rueda de `mercado` está en horario ahora? `mercado` es 'us'
    (NYSE/Nasdaq), 'byma' o 'cripto' (24/7). Es LA definición del horario de
    Rendi: la usan estas alertas y el indicador "Abierto / Cerrado" de las
    secciones de mercado del inicio (home.market.estado_de_rueda). No hay
    feriados acá: eso lo cubre quien la llama mirando la FECHA de la rueda.

    Las horas se preguntan a la base de zonas horarias en vez de escribirse como
    un offset fijo, porque Estados Unidos sí tiene horario de verano y la ventana
    en UTC se corre una hora dos veces al año. Esto NO es un segundo calendario:
    contesta "¿hay rueda?", no "¿qué día es?" — esa sigue siendo de `fechas.py`."""
    if mercado == "cripto":
        return True
    from datetime import timezone
    ahora = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    try:
        from zoneinfo import ZoneInfo
        if mercado == "byma":
            return _en_rueda(ahora.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")), *_SESION_BYMA)
        return _en_rueda(ahora.astimezone(ZoneInfo("America/New_York")), *_SESION_US)
    except Exception as ex:
        # Sin base de zonas horarias (imagen sin tzdata): ventana fija en UTC.
        # BYMA es exacta (la Argentina no cambia de hora: 11–17 ART = 14–20 UTC).
        # NY es ANCHA pero nunca empieza antes que su apertura más temprana real
        # (13:30 UTC, en verano) — no puede repetir el bug de las 13:01.
        # El aviso sale UNA vez por proceso: esta función corre por mercado y
        # por pedido, y sin tzdata cada llamada lo repetía en el log.
        global _AVISO_SIN_ZONEINFO
        if not _AVISO_SIN_ZONEINFO:
            _AVISO_SIN_ZONEINFO = True
            log.warning("rueda_en_horario sin zoneinfo (%s): ventana fija UTC", ex)
        if ahora.weekday() >= 5:
            return False
        minutos = ahora.hour * 60 + ahora.minute
        if mercado == "byma":
            return (14 * 60) <= minutos < (20 * 60)
        return (13 * 60 + 30) <= minutos < (21 * 60)


def _market_open_now(now) -> bool:
    """¿Hay alguna rueda abierta ahora? Es la unión de las dos que nos importan:
    NYSE/Nasdaq y BYMA. Las alertas de acciones/CEDEARs/bonos SOLO disparan acá
    adentro; cripto no pasa por esta función (opera 24/7).

    🔴 Lo que decía antes: "L-V, 13:00–21:00 UTC". Esa media hora de más por
    delante es la que mandó la ráfaga del 15/09/2026 a las 13:01 UTC (10:01 ART):
    Nueva York abre 13:30 UTC en horario de verano y BYMA 14:00 UTC, así que a
    las 13:01 NO había rueda abierta en ningún lado y el `change_pct` que traía
    el proveedor era todavía el del día anterior. Cuatro mails con el movimiento
    del lunes fechados como "hoy"."""
    return rueda_en_horario("us", now) or rueda_en_horario("byma", now)


# ─── Lógica de condición ──────────────────────────────────────────────────────

def condition_met(kind: str, direction: str, threshold: float,
                  price, change_pct=None):
    """price_target: ¿cumplida ahora? True/False, o None si no hay precio (→ NO
    disparar, no adivinar). pct_move usa pct_move_side (umbrales asimétricos)."""
    if kind == "price_target":
        if price is None or threshold is None:
            return None
        if direction == "above":
            return price >= threshold
        if direction == "below":
            return price <= threshold
    return None


def pct_move_side(change_pct, up_pct, down_pct):
    """pct_move con umbrales asimétricos en UNA alerta: devuelve qué lado
    disparó ('up' | 'down') o None. Ej: up_pct=3, down_pct=2 → dispara si
    subió ≥3% O cayó ≥2%. Cualquiera de los dos puede ser None (solo un lado)."""
    if change_pct is None:
        return None
    if up_pct is not None and change_pct >= up_pct:
        return "up"
    if down_pct is not None and change_pct <= -abs(down_pct):
        return "down"
    return None


def _recently_fired(conn, alert_id: int, symbol, cooldown_min: int, now: datetime) -> bool:
    """¿Ya disparó esta (alerta, símbolo) dentro del cooldown? (para pct_move)."""
    row = conn.execute(
        "SELECT fired_at FROM alert_events WHERE alert_id=? AND symbol IS ? "
        "ORDER BY fired_at DESC LIMIT 1",
        (alert_id, symbol),
    ).fetchone()
    if not row or not row["fired_at"]:
        return False
    try:
        last = datetime.fromisoformat(row["fired_at"])
    except (ValueError, TypeError):
        return False
    return (now - last) < timedelta(minutes=max(0, cooldown_min or 0))


# ─── Estado armado POR (alerta, símbolo) — edge-trigger de pct_move "En el día" ──

def _sym_state(conn, alert_id: int, symbol):
    """(armed, last_fired_date) del par (alerta, símbolo). Sin registro = (armado, None)."""
    row = conn.execute(
        "SELECT armed, last_fired_date FROM alert_symbol_state WHERE alert_id=? AND symbol=?",
        (alert_id, symbol),
    ).fetchone()
    if not row:
        return (1, None)
    return (int(row["armed"]), row["last_fired_date"])


def _set_sym_armed(conn, alert_id: int, symbol, armed: int):
    conn.execute(
        "INSERT INTO alert_symbol_state (alert_id, symbol, armed, updated_at) "
        "VALUES (?,?,?,datetime('now')) "
        "ON CONFLICT(alert_id, symbol) DO UPDATE SET "
        "armed=excluded.armed, updated_at=excluded.updated_at",
        (alert_id, symbol, armed),
    )


def _set_sym_fired(conn, alert_id: int, symbol, date: str):
    """Marca disparado hoy: armed=0 + last_fired_date=date (para el tope de 1/día)."""
    conn.execute(
        "INSERT INTO alert_symbol_state (alert_id, symbol, armed, last_fired_date, updated_at) "
        "VALUES (?,?,0,?,datetime('now')) "
        "ON CONFLICT(alert_id, symbol) DO UPDATE SET "
        "armed=0, last_fired_date=excluded.last_fired_date, updated_at=excluded.updated_at",
        (alert_id, symbol, date),
    )


# ─── El mismo movimiento no se avisa dos veces ────────────────────────────────
# Regla (Nico, 2026-10-15): un movimiento se define por CONTRA QUÉ CIERRE se mide
# y hacia dónde va. El post-mercado de anoche, el pre-mercado de hoy y la rueda
# de hoy se miden los tres contra el cierre de ayer: si los tres dicen «+3 %»,
# es UNA suba contada tres veces y se avisa una vez. El post de hoy se mide
# contra el cierre de hoy: otro 3 % arriba es una suba NUEVA. Y si cambia de
# sentido contra el mismo cierre (pre +3 %, abre −3 %), también se avisa.
# Se anota en alert_symbol_state con la clave '<símbolo>#<cierre>#<up|down>'.

def _clave_movimiento(symbol, base: str, lado: str) -> str:
    return f"{symbol}#{base}#{lado}"


def _ya_avisado(conn, alert_id: int, symbol, base, lado) -> bool:
    if not base or not lado:
        return False
    return _sym_state(conn, alert_id, _clave_movimiento(symbol, base, lado))[1] is not None


def _anotar_movimiento(conn, alert_id: int, symbol, base, lado) -> None:
    if base and lado:
        _set_sym_fired(conn, alert_id, _clave_movimiento(symbol, base, lado), base)


# Segundo aviso (Nico, 2026-10-15): si el MISMO movimiento llega al doble del
# umbral, se avisa una vez más — y nunca una tercera. Se anota con el sentido
# 'upx2' / 'downx2' en la misma clave. Si el primer aviso ya salió con el doble
# (abrió +7 % con una alerta de 3 %), se anotan los dos: ese aviso ya dio el número.
_DOBLE = "x2"


def _llego_al_doble(change, alert, lado) -> bool:
    thr = alert["up_pct"] if lado == "up" else alert["down_pct"]
    return thr is not None and change is not None and abs(change) >= 2 * abs(thr)


def _toca_el_doble(conn, alert, symbol, base, lado, change) -> bool:
    """¿Este movimiento ya avisado llegó al doble y todavía no se avisó eso?"""
    return (_ya_avisado(conn, alert["id"], symbol, base, lado)
            and _llego_al_doble(change, alert, lado)
            and not _ya_avisado(conn, alert["id"], symbol, base, lado + _DOBLE))


def _anotar_aviso(conn, alert, symbol, base, lado, change, doble: bool) -> None:
    """Anota lo que se acaba de avisar: el movimiento y, si ya está en el doble
    (o este ES el aviso del doble), también el segundo escalón."""
    if not doble:
        _anotar_movimiento(conn, alert["id"], symbol, base, lado)
    if doble or _llego_al_doble(change, alert, lado):
        _anotar_movimiento(conn, alert["id"], symbol, base, lado + _DOBLE)


_SUFIJO_DOBLE = " (el doble de tu alerta)"


def _base_de_la_rueda(symbol, sesiones_byma: set = None) -> str:
    """El cierre contra el que se mide la «Var. día» de hoy: la rueda anterior a
    la de hoy (un lunes, el viernes).

    Un papel de BYMA (`.BA`) usa los días en que operó BYMA (`sesiones_byma`, de
    `fuera_de_horario._sesiones_de_byma`): es la MISMA fuente que da la fecha del
    pre/post de un CEDEAR (`base_byma`). Con dos almanaques distintos, el martes
    después del feriado del lunes 12/10 el pre decía «contra el viernes» y la
    rueda «contra el lunes», y el mismo +3 % se avisaba dos veces (auditoría
    2026-10-15). Las acciones de EE.UU. no conocen feriados de allá: el día
    después de uno puede salir un aviso repetido, una vez."""
    from datetime import date as _date
    d = _date.fromisoformat(_sesion_hoy(symbol)) - timedelta(days=1)
    usar = bool(sesiones_byma) and str(symbol or "").upper().endswith(".BA")
    for _ in range(20):
        if d.weekday() < 5 and (not usar or d in sesiones_byma):
            return d.isoformat()
        d -= timedelta(days=1)
    return d.isoformat()


def _podar_movimientos(conn, now: datetime) -> None:
    """Las claves de movimiento viejas no sirven más (un cierre de hace 10 días ya
    no lo mide nadie)."""
    corte = (now - timedelta(days=10)).date().isoformat()
    try:
        conn.execute("DELETE FROM alert_symbol_state WHERE symbol LIKE ? AND last_fired_date < ?",
                     ("%#%#%", corte))
    except Exception as ex:
        log.warning("alerts: no se pudieron podar los movimientos viejos: %s", ex)


# ─── «Una sola vez» ───────────────────────────────────────────────────────────

def _cumplio_una_vez(conn, alert) -> None:
    """Una alerta «una sola vez» que acaba de dar su aviso queda apagada. Es el
    ÚNICO lugar que la apaga: precio, % de un activo, % de toda la cartera, en
    la rueda o fuera de ella, primer aviso o el del doble.

    El apagado se escribe en el momento (va en la misma transacción que el
    aviso: un corte del proceso no la deja prendida), pero el ciclo NO corta
    acá. Los demás activos de la misma alerta se siguen mirando —el ciclo usa
    la lista de alertas que leyó al arrancar, no la base— y todo lo que pasó el
    % en esta pasada sale en el MISMO aviso agrupado (`_entregar_pendientes`).

    Antes cortaba con el primer activo: «toda mi cartera, 3 %» con AAPL −8 %,
    KO −4 % y NVDA +5 % en la misma pasada avisaba sólo AAPL y se apagaba; KO y
    NVDA no llegaban nunca (medido el 21/10/2026). Y el aviso del doble en la
    rueda no la apagaba: seguía avisando.

    Regla (Nico, 2026-10-21): «una vez» en toda la cartera es UN aviso con
    todos los que pasaron el % en esa pasada, y después se apaga."""
    if alert["repeat"] == "once":
        conn.execute("UPDATE alerts SET active=0 WHERE id=?", (alert["id"],))


# ─── Mensajes ─────────────────────────────────────────────────────────────────

def _display_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    s = symbol
    if s.startswith("FCI:"):
        s = s[4:]
    if s.endswith(".BA"):
        s = s[:-3]
    return s


def _ccy_for(symbol, fallback=None) -> str:
    """Moneda del RIEL del símbolo: `.BA` cotiza en pesos, el símbolo pelado en
    dólares (es la misma convención con la que se guardan los símbolos, ver
    `_norm_sym` y `build_price_symbols`).

    Por qué no alcanza con la moneda guardada en la alerta: una alerta de "toda
    mi cartera" guarda UNA sola moneda —la que haya quedado al crearla— y después
    se expande a N tenencias que están en los dos rieles. Por eso el mail del
    15/09 decía "INTC cayó 5.8% y cotiza a US$ 31.020,00": 31.020 eran PESOS del
    CEDEAR y el rótulo salía de la fila de la alerta, no del activo que disparó.

    Los FCI son un tercer riel (los hay en pesos y en dólares) y ahí el símbolo
    no contesta la pregunta: se respeta lo que guardó la alerta."""
    if symbol:
        if symbol.endswith(".BA"):
            return "ARS"
        if not symbol.startswith("FCI:"):
            return "USD"
    return (fallback or "USD")


def _moneda(alert, symbol) -> str:
    """La moneda en que se muestra el precio de ESTE aviso: la del riel del
    símbolo (`_ccy_for`), salvo un CEDEAR vigilado en dólares."""
    if _es_cedear_usd(alert, symbol):
        return "USD"
    return _ccy_for(symbol, _campo(alert, "currency"))


def _fmt(price, currency) -> str:
    """Precio en convención argentina. Mostraba los pesos bien ($7.350) y los
    dólares a la inglesa (US$2,145.30) en el MISMO mail; ahora los dos salen
    del único formateador, money_fmt.fmt_money. Ojo: esto arma también el
    ASUNTO de la alerta, no sólo el cuerpo."""
    from money_fmt import fmt_money
    return fmt_money(price, currency)


def _compose_message(alert, symbol, price, change_pct) -> str:
    sym = _display_symbol(symbol)
    ccy = _moneda(alert, symbol)
    if alert["kind"] == "price_target":
        thr = _fmt(alert["threshold"], ccy)
        cur = _fmt(price, ccy)
        if alert["direction"] == "above":
            return f"{sym} alcanzó {cur}"
        return f"{sym} bajó a {cur}"
    # pct_move — título limpio, sin el detalle de umbrales (va en el cuerpo del mail).
    verbo = "subió" if (change_pct or 0) >= 0 else "cayó"
    cuando = "desde tu alerta" if (alert["baseline"] or "prev_close") == "set_price" else "hoy"
    return f"{sym} {verbo} {_fmt_pct(change_pct)}% {cuando}"


def _fmt_pct(v) -> str:
    """% limpio: 3.0 → '3', 3.2 → '3.2' (sin decimales de más en el título)."""
    v = abs(v or 0)
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{fmt_num(v, 1)}"


def _short_label(alert, symbol, price, change_pct) -> str:
    """Un movimiento en pocas palabras: "INTC cayó 5.8%".

    Es `_compose_message` sin el "hoy" del final, que en una lista de cuatro se
    repetiría cuatro veces. El "hoy" lo dice el asunto una sola vez."""
    if alert["kind"] == "price_target":
        return _compose_message(alert, symbol, price, change_pct)
    verbo = "subió" if (change_pct or 0) >= 0 else "cayó"
    return f"{_display_symbol(symbol)} {verbo} {_fmt_pct(change_pct)}%"


def _cuando_item(it) -> str:
    f = it.get("fuera")
    return f"en el {_NOMBRE_FRANJA[f['sesion']]}" if f else "hoy"


def _compose_group_message(items, fuera: dict = None, mixto: bool = False) -> str:
    """El asunto de un aviso agrupado. Nombra los movimientos en vez de
    contarlos: "INTC cayó 5.8%, NVDA cayó 3.4% y 2 más hoy", no "4 alertas".

    Es la misma lección que el resumen de mercado — el asunto ES el titular y es
    lo que decide si el mail se abre; cuántos avisos hay es justo lo que a nadie
    le importa. `items` llega ya ordenado de mayor a menor movimiento."""
    if mixto:
        # Rueda y pre/post juntos: cada uno con su cuándo, sin sufijo común.
        etiquetas = [f"{it['label']} {_cuando_item(it)}" for it in items]
        if len(etiquetas) == 2:
            return f"{etiquetas[0]} y {etiquetas[1]}"
        return f"{etiquetas[0]}, {etiquetas[1]} y {len(etiquetas) - 2} más"
    etiquetas = [it["label"] for it in items]
    cuando = f"en el {_NOMBRE_FRANJA[fuera['sesion']]}" if fuera else "hoy"
    if len(etiquetas) == 2:
        return f"{etiquetas[0]} y {etiquetas[1]} {cuando}"
    return f"{etiquetas[0]}, {etiquetas[1]} y {len(etiquetas) - 2} más {cuando}"


# ─── Entrega ──────────────────────────────────────────────────────────────────

def _delivery_target(conn, uid: int):
    """A quién se le ENTREGA la alerta de esta cuenta.

    Plan Asesor: las alertas de una cuenta ADMINISTRADA (shadow, managed_by
    seteado) le llegan al ASESOR — el shadow no tiene devices de push ni un
    email real (@shadow.rendi.internal, casilla muerta). Devuelve
    (deliver_uid, client_label|None). Para cuentas normales: (uid, None)."""
    try:
        row = conn.execute("SELECT managed_by FROM users WHERE id=?", (uid,)).fetchone()
        if row and row["managed_by"]:
            adv = int(row["managed_by"])
            lrow = conn.execute(
                """SELECT label FROM advisor_clients
                   WHERE advisor_uid=? AND client_uid=?""", (adv, uid)).fetchone()
            return adv, (lrow["label"] if lrow and lrow["label"] else f"Cliente {uid}")
    except Exception as ex:
        log.warning("alerts delivery-target uid=%s falló: %s (entrego al dueño)", uid, ex)
    return uid, None


def entrega(conn, uid: int, armar, *, push_titulo: str = None, push_url: str = None) -> dict:
    """LA forma de armar un aviso para la cuenta `uid`: a quién le llega, qué
    dice y adónde lleva. La usan todos los avisos (precio, %, técnica,
    recordatorio de tesis, el resumen de los sábados).

    `armar(cuenta)` devuelve los argumentos de `emails.send_alert_email` (sin el
    destinatario), escritos para quien los va a leer: `cuenta` es None si es la
    cuenta propia y el nombre del cliente («Juan») si la administra un asesor,
    para quien quiera cambiar «tu plata» por «la plata de Juan».
    `push_titulo` / `push_url`: el texto y el destino del push; sin ellos, el
    asunto y el botón del mail.

    Devuelve {'destino': uid a quien se le entrega, 'cliente': nombre | None,
              'mail': {…}, 'push': {'titulo', 'url'}}.

    🔴 POR QUÉ ES UNA SOLA FUNCIÓN (auditoría B, 29/10). La regla «un aviso de un
    cliente le llega al asesor» eran dos funciones sueltas: `_delivery_target`
    (A QUIÉN) y `_para_el_asesor` (QUÉ DICE y ADÓNDE LLEVA), y cada aviso nuevo
    tenía que acordarse de las dos. El resumen de los sábados usó sólo la
    primera: a Laura le llegaba «el 94% de tu plata» de Juan, con los links a SUS
    señales (B1). Y el destino del push se calculaba aparte del botón del mail:
    el push de la técnica de Juan abría «Mis alertas» de Laura (B2)."""
    destino, cliente = _delivery_target(conn, uid)
    mail = dict(armar(cliente))
    push = {"titulo": push_titulo or mail["heading"], "url": push_url or mail["cta_path"]}
    if cliente:
        _para_el_asesor(mail, push, cliente)
    return {"destino": destino, "cliente": cliente, "mail": mail, "push": push}


def _deliver(conn, alert, items) -> tuple:
    """Manda UN push + UN email por alerta y por ciclo, con todo lo que disparó.
    Devuelve (push_ok, email_ok).

    `items` es la lista de movimientos de ESTA alerta en ESTE ciclo. Con uno
    solo el mail es igual que siempre. Con varios va uno solo, porque una alerta
    de "toda mi cartera" se expande a todas las tenencias y un día movido
    dispara varias juntas: el 15/09/2026 salieron cuatro mails en el mismo
    minuto. Cuatro mails idénticos en un minuto además son la señal más fuerte
    de "esto lo manda un robot" que mira Gmail para elegir la pestaña.

    Los avisos de la app siguen siendo uno por activo (`alert_events`): se
    movieron cuatro cosas, no una. Lo que se agrupa es la ENTREGA."""
    # Más grande primero: si hay que nombrar dos en el asunto, que sean los dos
    # que más se movieron.
    items = sorted(items, key=lambda it: abs(it.get("change_pct") or 0), reverse=True)
    franjas = {(it.get("fuera") or {}).get("sesion") for it in items}
    mixto = len(franjas) > 1
    fuera = None if mixto else items[0].get("fuera")
    heading = (items[0]["message"] if len(items) == 1
               else _compose_group_message(items, fuera, mixto=mixto))
    tecnica = alert["kind"] == "tecnica"
    # Un aviso que trae su mail ya armado (el recordatorio de una tesis,
    # `evaluar_recordatorios`) no pasa por el de precio y %.
    armado = items[0].get("contenido")
    e = entrega(
        conn, alert["user_id"],
        lambda _cuenta: ({**armado, "heading": heading} if armado
                         else _contenido_del_mail(alert, items, fuera, mixto, heading)),
        # El push de precio y % abre «Mis alertas»: la alerta que saltó, con su
        # estado y para pausarla. (Iba a /config?tab=notificaciones, ruta MUERTA
        # desde que las alertas se mudaron a /alertas; después a /dashboard, que
        # no dice nada del aviso.) La técnica y el recordatorio van adonde va el
        # botón del mail: la ficha del activo, con el gráfico.
        push_titulo=heading, push_url=None if (tecnica or armado) else _MIS_ALERTAS)
    uid = e["destino"]
    channel = alert["channel"] or "both"
    push_ok = email_ok = False

    if channel in ("push", "both"):
        try:
            import main
            titulo = e["push"]["titulo"]
            sent = main._send_push_to_user(uid, {
                "title": "Rendi · Alerta",
                # La señal técnica lleva la aclaración también en el push: es lo
                # único que lee quien no abre el mail.
                "body": f"{titulo}. {_NO_ES_RECOMENDACION}" if tecnica else titulo,
                "url": e["push"]["url"],
                "tag": (f"alert-{alert['id']}-{items[0]['symbol'] or ''}"
                        if len(items) == 1 else f"alert-{alert['id']}-grupo"),
            })
            push_ok = sent > 0
        except Exception as ex:
            log.warning("alerts push uid=%s falló: %s", uid, ex)

    if channel in ("email", "both"):
        try:
            row = conn.execute("SELECT email, name FROM users WHERE id=?", (uid,)).fetchone()
            if row and row["email"]:
                from billing import emails
                email_ok = emails.send_alert_email(
                    to=row["email"], user_name=(row["name"] or ""), **e["mail"])
        except Exception as ex:
            log.warning("alerts email uid=%s falló: %s", uid, ex)

    return push_ok, email_ok


# ─── El mail ──────────────────────────────────────────────────────────────────
# Diseño del tablero «Cómo llega por mail» (lienzo de Alertas, 19/10/2026): un
# titular grande, UNA oración, la lista si son varios, UN botón y al pie lo que
# se puede hacer con la alerta. El asunto no se arma acá: es `heading` (el
# titular que nombra los movimientos, ver `_deliver`).

# «Mis alertas»: donde está la alerta que saltó, con su interruptor para
# pausarla o volver a prenderla y el formulario para cambiarle el %. Es la misma
# ruta a la que lleva el push.
_MIS_ALERTAS = "/alertas?tab=mis"


def _pct_con_signo(v) -> str:
    """"+8,4%" / "−5,6%": el % de la lista, con el signo que en el asunto dice
    el verbo ("subió" / "cayó"). Mismo redondeo que el asunto (`_fmt_pct`)."""
    return f"{'+' if (v or 0) >= 0 else '−'}{_fmt_pct(v)}%"


def _email_detail(alert, symbol, price=None, change_pct=None, doble=False) -> str:
    """La oración del mail de UN activo en la rueda (el mail le antepone "Hola
    Juan, "): lo que el titular no dice, que es a cuánto está ahora.

    Tiene que traer NÚMEROS. Antes decía "tuvo un movimiento importante hoy,
    entrá a Rendi para ver cómo impacta en tu cartera": el título traía más
    información que el cuerpo, y un mail que no dice nada no se abre. Gmail mide
    justamente eso para decidir la pestaña — medido el 2026-09-09 sobre la
    casilla del fundador, las ÚNICAS alertas que se salieron de Actualizaciones
    son las que estaban leídas. El titular ya lleva el % (o el precio marcado);
    esto lleva el precio de ahora, en la moneda del activo."""
    cur = _fmt(price, _moneda(alert, symbol))
    ahora = f" Ahora está en {cur}." if price is not None else ""
    if alert["kind"] == "price_target":
        return f"es el precio que marcaste.{ahora}"
    if doble:
        return f"ya es el doble del límite que marcaste.{ahora}"
    return f"pasó el límite que marcaste.{ahora}"


def _titulo_precio(alert, symbol, price) -> str:
    """«GGAL llegó a $8.000»: el precio que la persona MARCÓ, no el de ahora (ése
    va en la oración). Es lo que reconoce de un vistazo — lo eligió ella."""
    ccy = _moneda(alert, symbol)
    marcado = alert["threshold"] if alert["threshold"] is not None else price
    return f"{_display_symbol(symbol)} llegó a {_fmt(marcado, ccy)}"


def _fila(it, mixto: bool) -> dict:
    """Un renglón de la lista del agrupado: quién y cuánto. Lo que haga falta
    aclarar (que fue en el pre-mercado, que es el doble) va en una nota chica
    abajo del nombre, no en la columna del %."""
    f = it.get("fuera")
    nombre = _quien(it["symbol"], f) if f else _display_symbol(it["symbol"])
    notas = []
    if mixto:
        notas.append(_cuando_item(it))
    if f and f.get("via") != "propio":
        notas.append(_desde_byma(f).lstrip(", "))
    if it.get("doble"):
        notas.append(_SUFIJO_DOBLE.strip(" ()"))
    return {"nombre": nombre, "pct": it.get("change_pct"),
            "pct_txt": _pct_con_signo(it.get("change_pct")), "nota": " · ".join(notas)}


def _contenido_del_mail(alert, items, fuera, mixto: bool, heading) -> dict:
    """Todo lo que lleva el mail: asunto, titular, oración, lista, botón y pie.
    Devuelve los argumentos de `emails.send_alert_email` (menos el destinatario).

    El asunto es `heading`, el mismo texto del push, salvo en el aviso de precio:
    ahí asunto y titular dicen el precio MARCADO («GGAL llegó a $8.000») y la
    oración el de ahora. El push sigue diciendo el de ahora («GGAL alcanzó
    $8.012»): esta función arma sólo el mail.

      · Un precio: «GGAL llegó a $8.000» / «es el precio que marcaste. Ahora
        está en $8.012.» / botón «Ver GGAL».
      · Un %: el titular es el mismo del asunto («AAPL cayó 5% hoy») / «pasó el
        límite que marcaste. Ahora está en …» / botón «Ver AAPL».
      · Varios: «3 de tus activos se movieron fuerte hoy» / la lista de ticker y
        % / botón «Ver mi cartera».
    El pie: si era «una sola vez», que ya cumplió y cómo volver a activarla; si
    no, cómo cambiar el % (o pausarla, la de precio). Los dos van a «Mis
    alertas». Antes el botón llevaba a /dashboard, que no dice nada del aviso."""
    una_vez = alert["repeat"] == "once"
    if una_vez:
        pie = ("Esta alerta ya cumplió.", "Volver a activarla", _MIS_ALERTAS)
    elif alert["kind"] == "tecnica":
        pie = ("Te volvemos a avisar la próxima vez que pase.", "Pausarla o cambiarla", _MIS_ALERTAS)
    elif alert["kind"] == "price_target":
        pie = ("Te volvemos a avisar si lo cruza de nuevo.", "Pausarla o cambiarla", _MIS_ALERTAS)
    else:
        pie = ("¿Demasiados avisos?", "Cambiá el %", _MIS_ALERTAS)

    if len(items) == 1:
        it = items[0]
        sym = _display_symbol(it["symbol"])
        if it.get("tecnica"):
            titulo = it["message"]
            detail = _detalle_tecnico(alert, it["symbol"], it["tecnica"])
        elif fuera:
            # El pre/post explica qué franja, contra qué cierre y que es un
            # anticipo: es más que una oración, pero sin eso el % engaña.
            titulo = it["message"]
            detail = _detalle_fuera(it["symbol"], it["change_pct"], it["price"], fuera)
        elif alert["kind"] == "price_target":
            titulo = _titulo_precio(alert, it["symbol"], it["price"])
            detail = _email_detail(alert, it["symbol"], it["price"])
            heading = titulo
        else:
            titulo = it["message"]
            detail = _email_detail(alert, it["symbol"], it["price"], it["change_pct"],
                                   doble=bool(it.get("doble")))
        contenido = {"titulo": titulo, "detail": detail, "filas": None,
                     "cta_label": f"Ver {sym}", "cta_path": f"/activo/{quote(sym, safe='')}"}
    else:
        n = len(items)
        if mixto:
            titulo = f"{n} de tus activos se movieron fuerte"
            detail = ("pasaron el límite que marcaste. Lo de Wall Street fuera de la "
                      "rueda es un anticipo: todavía no se suma a tu cartera.")
        elif fuera:
            franja = _NOMBRE_FRANJA[fuera["sesion"]]
            titulo = f"{n} de tus activos se mueven fuerte en el {franja}"
            detail = (f"pasaron el límite que marcaste en el {franja} de Wall Street. "
                      f"Es un anticipo: todavía no se suma a tu cartera.")
        else:
            titulo = f"{n} de tus activos se movieron fuerte hoy"
            detail = "pasaron el límite que marcaste."
        contenido = {"titulo": titulo, "detail": detail,
                     "filas": [_fila(it, mixto) for it in items],
                     "cta_label": "Ver mi cartera", "cta_path": "/posiciones"}

    contenido["pie"] = pie
    contenido["heading"] = heading
    if alert["kind"] == "tecnica":
        contenido["aclaracion"] = _NO_ES_RECOMENDACION
    return contenido


def _para_el_asesor(mail: dict, push: dict, cliente: str) -> None:
    """Plan Asesor: el aviso es de una cuenta que administra. Su cartera, su
    ficha, su «Mis alertas» y sus señales no son las de esa cuenta: se entra
    desde Clientes. Sólo la llama `entrega`.

    «en la cuenta de Juan» va ADELANTE de la oración («Hola Laura, en la cuenta
    de Juan, pasó el límite…»): pegado al final quedaba colgando de la última
    frase de la lectura («…la tendencia de fondo es alcista, en la cuenta de
    Juan.», auditoría B2)."""
    mail["heading"] = f"[{cliente}] {mail['heading']}"
    push["titulo"] = f"[{cliente}] {push['titulo']}"
    mail["detail"] = f"en la cuenta de {cliente}, {mail['detail']}"
    mail["cta_label"], mail["cta_path"] = "Ver mis clientes", "/clientes"
    mail["pie"] = (f"Para cambiar este aviso, entrá a la cuenta de {cliente}.",
                   "Ir a mis clientes", "/clientes")
    push["url"] = "/clientes"


def _fire(conn, alert, symbol, price, change_pct, now: datetime, pendientes: list,
          fuera: dict = None, doble: bool = False, tecnica: dict = None):
    """Dispara: log en alert_events + actualiza last_fired_* + ENCOLA la entrega.

    El mail y el push no salen acá. Se acumulan en `pendientes` y salen al
    cerrar el ciclo, agrupados por alerta (ver `_entregar_pendientes`): si no,
    una alerta de toda la cartera manda un mail por cada activo que se movió.

    El evento de la app se escribe igual, uno por activo y en el momento — es lo
    que alimenta la lista de "Últimos avisos" y el puntito del sidebar. Las dos
    banderas de entregado se completan cuando la entrega efectivamente sale."""
    if tecnica:
        # Una señal técnica: la frase sale de la señal, no de un precio.
        message = label = _mensaje_tecnico(alert, symbol, tecnica)
    elif fuera:
        # Pre o post mercado: el mensaje dice en qué franja y, para un CEDEAR,
        # que es su acción en Nueva York. El precio es el de allá, en dólares.
        message = _mensaje_fuera(symbol, change_pct, fuera)
        label = _etiqueta_fuera(symbol, change_pct, fuera)
    else:
        message = _compose_message(alert, symbol, price, change_pct)
        label = _short_label(alert, symbol, price, change_pct)
    if doble:
        # El segundo aviso del mismo movimiento dice por qué vuelve a llegar.
        message += _SUFIJO_DOBLE
    cur = conn.execute(
        """INSERT INTO alert_events
           (alert_id, user_id, symbol, fired_at, price, message,
            delivered_push, delivered_email)
           VALUES (?,?,?,?,?,?,0,0)""",
        # Fuera de la rueda el precio es el de Nueva York, en dólares: guardado
        # junto a un símbolo .BA se leería como pesos. Se guarda el %, como en las
        # pct_move sin precio.
        (alert["id"], alert["user_id"], symbol, now.isoformat(),
         change_pct if fuera else (price if price is not None else change_pct), message),
    )
    conn.execute(
        "UPDATE alerts SET last_fired_at=?, last_fired_price=? WHERE id=?",
        (now.isoformat(), price if price is not None else None, alert["id"]),
    )
    pendientes.append({
        "alert": alert, "symbol": symbol, "price": price,
        "change_pct": change_pct, "message": message,
        "label": label,
        "event_id": cur.lastrowid,
        "fuera": fuera, "doble": doble, "tecnica": tecnica,
    })
    log.info("alert %s fired (uid=%s sym=%s): %s",
             alert["id"], alert["user_id"], symbol, message)


def _entregar_pendientes(conn, pendientes: list) -> None:
    """Entrega todo lo que disparó en el ciclo, con un envío por alerta.

    Una alerta que falla al entregar no puede dejar sin avisar a las otras: cada
    grupo va en su propio try (misma guarda que el cron usa entre el motor de
    precios y el del libro del asesor)."""
    # Uno por alerta, AUNQUE mezcle franjas: desde el 1/11, de 11:00 a 11:30
    # coinciden la rueda de BYMA y el pre de Nueva York, y dos mails seguidos de
    # la misma alerta son justo el spam que el agrupado vino a evitar. Cada
    # renglón dice dónde fue (ver `_deliver`).
    por_alerta: dict = {}
    for it in pendientes:
        por_alerta.setdefault(it["alert"]["id"], []).append(it)
    for items in por_alerta.values():
        alert = items[0]["alert"]
        try:
            push_ok, email_ok = _deliver(conn, alert, items)
        except Exception as ex:
            log.warning("alerts entrega de la alerta %s falló: %s", alert["id"], ex)
            continue
        # Anotar la entrega va en su propio try: si la base está trabada (un
        # import largo la tiene tomada más que el busy_timeout), el UPDATE
        # falla — y afuera del try cortaba la entrega de TODAS las alertas que
        # faltaban, que ya estaban registradas como disparadas y no se
        # reintentan. Mejor un "entregado" sin anotar que un aviso sin mandar.
        try:
            conn.executemany(
                "UPDATE alert_events SET delivered_push=?, delivered_email=? WHERE id=?",
                [(1 if push_ok else 0, 1 if email_ok else 0, it["event_id"]) for it in items])
            conn.commit()    # no llevar el lock de escritura a la entrega que sigue
        except Exception as ex:
            log.warning("alerts: no se pudo anotar la entrega de la alerta %s: %s",
                        alert["id"], ex)
            try:
                conn.rollback()
            except Exception:
                pass
        log.info("alert %s entregada (%s aviso/s, push=%s email=%s)",
                 alert["id"], len(items), push_ok, email_ok)


# ─── Fuera de la rueda: pre y post mercado de Wall Street ─────────────────────

_NOMBRE_FRANJA = {"pre": "pre-mercado", "post": "post-mercado"}


def _quien(symbol, fuera) -> str:
    """«NVDA» o, para un CEDEAR / acción argentina, «AAPL en Nueva York»: lo que
    se mueve es la acción de allá, no el papel de acá (que todavía no operó)."""
    sym = _display_symbol(symbol)
    ref = fuera.get("ref")
    if fuera.get("via") == "propio":
        return sym
    return f"{ref} en Nueva York" if ref == sym else f"{sym} ({ref} en Nueva York)"


def _desde_byma(fuera) -> str:
    """Un CEDEAR o una acción argentina se mide desde lo que valía su acción
    cuando cerró BYMA (`pct_segun_via`): en invierno, una hora antes del cierre
    de NY. Sin decirlo, «NVDA en Nueva York sube 6,7% en el pre-mercado» era
    falso: el pre-mercado de NVDA, contra su cierre, era +3,5 % (auditoría
    2026-10-15)."""
    return "" if fuera.get("via") == "propio" else ", desde el cierre de BYMA"


def _etiqueta_fuera(symbol, change_pct, fuera) -> str:
    verbo = "sube" if (change_pct or 0) >= 0 else "cae"
    return f"{_quien(symbol, fuera)} {verbo} {_fmt_pct(change_pct)}%"


def _mensaje_fuera(symbol, change_pct, fuera) -> str:
    """El título: «NVDA cae 3,1% en el pre-mercado» o, para un CEDEAR, «AAPL en
    Nueva York sube 3,4% en el pre-mercado, desde el cierre de BYMA»."""
    return (f"{_etiqueta_fuera(symbol, change_pct, fuera)} en el {_NOMBRE_FRANJA[fuera['sesion']]}"
            f"{_desde_byma(fuera)}")


def _detalle_fuera(symbol, change_pct, price, fuera) -> str:
    """El cuerpo del mail: qué franja, contra qué, y que es un anticipo.

    Arranca en minúscula: el mail lo antepone con «Hola Nico,» (como el resto de
    los avisos). Y lo que se dice del papel de ACÁ depende de la franja: en el
    pre todavía no operó hoy; en el post ya cerró en BYMA y esto anticipa cómo
    puede abrir mañana."""
    franja = _NOMBRE_FRANJA[fuera["sesion"]]
    momento = ("antes de que abra la rueda" if fuera["sesion"] == "pre"
               else "después del cierre de la rueda")
    # «El último cierre» y no «el de ayer»: un lunes es el del viernes. Un CEDEAR
    # se mide desde lo que valía su acción cuando cerró BYMA (ver `_desde_byma`).
    if fuera.get("via") == "propio":
        contra = "contra el último cierre" if fuera["sesion"] == "pre" else "contra el cierre de hoy"
    else:
        contra = ("desde lo que valía cuando cerró BYMA" if fuera["sesion"] == "pre"
                  else "desde lo que valía cuando cerró BYMA hoy")
    verbo = "sube" if (change_pct or 0) >= 0 else "cae"
    cotiza = f" y cotiza a {_fmt(price, 'USD')}" if price else ""
    txt = (f"en el {franja} de Wall Street ({momento}), {_quien(symbol, fuera)} {verbo} "
           f"{_fmt_pct(change_pct)}% {contra}{cotiza}. Es un anticipo: todavía no "
           f"se suma a tu cartera.")
    if fuera.get("via") != "propio":
        papel = (f"Tu CEDEAR de {_display_symbol(symbol)}" if fuera.get("via") == "eeuu"
                 else f"Tu acción de {_display_symbol(symbol)}")
        if fuera["sesion"] == "pre":
            txt += (f" {papel} todavía no operó hoy: cuando abra BYMA, en pesos también "
                    f"va a pesar lo que haga el dólar CCL.")
        else:
            txt += (f" {papel} ya cerró hoy en BYMA: esto anticipa cómo puede abrir en la "
                    f"próxima rueda, y en pesos también va a pesar lo que haga el dólar CCL.")
    return txt


def _evaluar_fuera_de_rueda(conn, units: list, pendientes: list, now: datetime) -> int:
    """Las pct_move "En el día" en el pre y el post mercado de Wall Street.

    Reglas (decididas el 2026-10-15):
      · Sólo pct_move con baseline "En el día" (prev_close). Las de precio
        objetivo y las de "Desde ahora" no: un precio en pesos no se puede
        comparar con uno de Nueva York.
      · El % es el del pre/post de la acción de EE.UU. que sigue la tenencia
        (`fuera_de_horario.referencia_en_eeuu`, la misma de la pantalla). Para un
        CEDEAR o una acción argentina, desde el cierre de BYMA
        (`fuera_de_horario.pct_segun_via`) y sólo hasta que abre BYMA.
      · Sólo con operaciones de verdad: MIN_VELAS velas de 5 min en la franja
        (`con_operaciones`). Una operación suelta no dispara.
      · El mismo movimiento se avisa UNA vez (ver `_ya_avisado`): el post de
        anoche, el pre de hoy y la rueda de hoy se miden contra el mismo cierre;
        si ya se avisó «+3 %» contra ese cierre, ni el pre ni la apertura lo
        repiten. El post de hoy (contra el cierre de hoy) o un cambio de sentido
        sí avisan. Una alerta "una sola vez" se apaga con su primer aviso, sea
        en la rueda o fuera de ella — y ese aviso lleva todo lo que pasó el % en
        el ciclo, también lo de la rueda de BYMA si coincide con el pre
        (`_cumplio_una_vez`).
      · Si dos tenencias siguen a la misma acción (NVDA y el CEDEAR de NVDA) y
        dan el MISMO %, un solo renglón; si dan distinto (en invierno el CEDEAR
        se mide desde el cierre de BYMA), dos.
      · Si el precio al cierre de BYMA no llegó (`byma_aproximado`), el CEDEAR
        no avisa hasta que llegue.
      · La red (Yahoo) va ANTES de cualquier escritura: el que llama confirma lo
        anterior, así no se tiene tomada la base mientras se espera a Yahoo.
    """
    import fuera_de_horario as fdh
    candidatas = []
    for a, sym in units:
        if a["kind"] != "pct_move" or (a["baseline"] or "prev_close") != "prev_close":
            continue
        if sym in _crypto_symbols():
            continue
        ref = fdh.referencia_en_eeuu(sym)
        if ref:
            candidatas.append((a, sym, ref))
    if not candidatas:
        return 0
    try:
        datos = fdh.estado(sorted({r[0] for _, _, r in candidatas}),
                           byma=sorted({r[0] for _, _, r in candidatas if r[1] != "propio"}))
    except Exception as ex:
        log.warning("alerts fuera de la rueda: Yahoo falló: %s", ex)
        return 0
    sesion = datos.get("sesion")
    if sesion not in ("pre", "post"):
        return 0          # en la rueda manda la «Var. día»; de noche no hay nada vivo
    cot = datos.get("cotizaciones") or {}

    cruzaron = []
    for a, sym, (ref, via) in candidatas:
        if via != "propio" and datos.get("byma_abierto"):
            continue      # el papel de acá ya tiene precio propio
        q = cot.get(ref) or {}
        # Un CEDEAR: lo que se movió su acción desde que cerró BYMA, y el cierre
        # contra el que se mide es el de BYMA (el mismo de su «Var. día»).
        if via != "propio" and q.get("byma_aproximado"):
            # Yahoo no dio el precio al cierre de BYMA y el % vino contra el de NY:
            # cuando vuelva, el mismo precio «se movería» de 3,5 a 6,7 % y saltaría
            # un falso aviso del doble (auditoría 2026-10-15). Se espera al dato.
            continue
        pct = fdh.pct_segun_via(q, via)
        lado = pct_move_side(pct, a["up_pct"], a["down_pct"])
        base = (q.get("base_byma") if via != "propio" else None) or q.get("base")
        if pct is None or not lado or not base:
            continue
        doble = False
        if _ya_avisado(conn, a["id"], sym, base, lado):
            # El mismo movimiento (mismo cierre, mismo sentido) ya se avisó: sólo
            # vuelve si llegó al doble del umbral, una vez.
            if not _toca_el_doble(conn, a, sym, base, lado, pct):
                continue
            doble = True
        cruzaron.append((a, sym, ref, via, pct, q.get("precio"), (base, lado), doble))
    if not cruzaron:
        return 0
    try:
        velas = fdh.con_operaciones(sorted({c[2] for c in cruzaron}), sesion)
    except Exception as ex:
        log.warning("alerts fuera de la rueda: velas fallaron: %s", ex)
        return 0
    fired = 0
    mismo_ref = set()     # (alerta, acción de EE.UU., sentido, %, base) ya avisados en ESTE ciclo
    for a, sym, ref, via, pct, precio, clave, doble in cruzaron:
        # NVDA en Schwab y el CEDEAR de NVDA son la MISMA suba sólo si dicen el
        # mismo número desde el mismo cierre (en verano). En invierno el CEDEAR
        # se mide desde el cierre de BYMA y da otro %: son dos renglones. Juntarlos
        # escondía uno y le gastaba su aviso del doble (auditoría 2026-10-15).
        igual = (a["id"], ref, clave[1], doble, round(pct, 1), clave[0])
        if igual in mismo_ref:
            _anotar_aviso(conn, a, sym, clave[0], clave[1], pct, doble)
            continue
        if velas.get(ref, 0) < fdh.MIN_VELAS:
            log.info("alert %s %s: %+.2f%% en el %s con %s velas: poca operación, no aviso",
                     a["id"], sym, pct, sesion, velas.get(ref, 0))
            continue
        _fire(conn, a, sym, precio, pct, now, pendientes,
              fuera={"sesion": sesion, "ref": ref, "via": via}, doble=doble)
        _anotar_aviso(conn, a, sym, clave[0], clave[1], pct, doble)
        mismo_ref.add(igual)
        fired += 1
        # «Una sola vez» es una sola vez, también si el aviso fue fuera de la
        # rueda (auditoría 2026-10-15: seguía avisando día tras día).
        _cumplio_una_vez(conn, a)
    return fired


# ─── Loop principal ────────────────────────────────────────────────────────────

def evaluate_alerts(conn, only_user: int = None) -> dict:
    """Evalúa TODAS las alertas activas (o las de un user). Idempotente y seguro
    para correr cada N minutos desde un cron externo. Confirma lo que disparó
    ANTES de entregar y cada entrega por separado (ver `_entregar_pendientes`):
    la entrega es red y no puede llevar el lock de escritura."""
    now = datetime.utcnow()
    # Sólo las de precio y %: las técnicas van una vez por día
    # (`evaluar_tecnicas`) y un recordatorio de tesis (`kind='recordatorio'`)
    # no mira precios y caería en la rama del % (`evaluar_recordatorios`).
    en_vivo = "kind IN (" + ",".join(f"'{k}'" for k in KINDS_EN_VIVO) + ")"
    q = f"SELECT * FROM alerts WHERE active=1 AND {en_vivo}"
    params: tuple = ()
    if only_user is not None:
        q += " AND user_id=?"
        params = (only_user,)
    alerts = conn.execute(q, params).fetchall()
    if not alerts:
        return {"alerts": 0, "evaluated": 0, "fired": 0}

    # Expandir a unidades (alerta, símbolo). holdings-scope → cada tenencia.
    # Qué precio necesita cada una: price_target y pct_move "Desde ahora"
    # (set_price) usan el precio actual; pct_move "En el día" usa el change_pct.
    def _wants_price(a):
        if a["kind"] == "price_target":
            return True
        return a["scope"] != "holdings" and (a["baseline"] or "prev_close") == "set_price"

    units: list = []          # [(alert_row, symbol)]
    price_syms: set = set()
    quote_syms: set = set()
    holdings_cache: dict = {}
    for a in alerts:
        bucket = price_syms if _wants_price(a) else quote_syms
        if a["scope"] == "holdings":
            uid = a["user_id"]
            if uid not in holdings_cache:
                holdings_cache[uid] = _holding_symbols(conn, uid)
            for sym in holdings_cache[uid]:
                sym = _norm_sym(sym)   # cripto AR: BTC.BA → BTC
                units.append((a, sym))
                bucket.add(sym)
        else:
            sym = _norm_sym(a["symbol"])
            if not sym:
                continue
            units.append((a, sym))
            bucket.add(sym)

    prices = _prices_for(list(price_syms)) if price_syms else {}
    # Los CEDEARs vigilados en dólares: su precio sale aparte (ver
    # `cedear_en_dolares`). Mismo símbolo que la alerta en pesos, otro precio.
    usd_syms = {sym for a, sym in units if _es_cedear_usd(a, sym)}
    precios_usd = precios_cedear_en_dolares(usd_syms) if usd_syms else {}
    quotes = _quotes_for(list(quote_syms)) if quote_syms else {}

    market_open = _market_open_now(now)
    # Los días en que operó BYMA, para la base de la «Var. día» de los `.BA`
    # (`_base_de_la_rueda`). Es red (cacheada 10 min): va ACÁ, antes de la
    # primera escritura del ciclo, no adentro del loop con la base tomada.
    sesiones_byma = None
    if any(str(s).upper().endswith(".BA") for _a, s in units):
        try:
            import fuera_de_horario as _fdh
            sesiones_byma = _fdh._sesiones_de_byma()
        except Exception as ex:
            log.warning("alerts: no se pudo saber qué días operó BYMA: %s", ex)
    # Los avisos de este ciclo se acumulan acá y salen todos juntos al final,
    # un envío por alerta. Ver `_entregar_pendientes`.
    pendientes: list = []
    fired = 0
    # Una «una sola vez» que avisa en el ciclo se apaga ahí mismo, pero sus
    # otros activos se siguen mirando: van todos en el mismo aviso (ver
    # `_cumplio_una_vez`).
    for a, sym in units:
        # Acciones/CEDEARs/bonos: solo disparan en horario de mercado (evita saltos
        # de madrugada sobre precios congelados). Cripto: 24/7.
        tradeable = (sym in _crypto_symbols()) or market_open

        if a["kind"] == "price_target":
            price = (precios_usd if _es_cedear_usd(a, sym) else prices).get(sym)
            met = condition_met("price_target", a["direction"], a["threshold"], price, None)
            if met is None:
                continue  # sin precio → no adivinar
            if a["armed"] and met and tradeable:
                _fire(conn, a, sym, price, None, now, pendientes)
                fired += 1
                conn.execute("UPDATE alerts SET armed=0 WHERE id=?", (a["id"],))
                _cumplio_una_vez(conn, a)
            elif not a["armed"] and not met:
                conn.execute("UPDATE alerts SET armed=1 WHERE id=?", (a["id"],))  # re-arma (cualquier hora)
        else:  # pct_move
            base = a["baseline"] or "prev_close"
            if a["scope"] != "holdings" and base == "set_price":
                # "Desde ahora": % vs el precio ancla (re-anclado al crear/reactivar).
                price = prices.get(sym)
                anchor = a["anchor_price"]
                if price is None or not anchor:
                    continue
                change = (price - anchor) / anchor * 100.0
                fire_price = price
            else:
                # "En el día": movimiento vs el cierre previo.
                quote = quotes.get(sym)
                change = quote.get("change_pct") if quote else None
                fire_price = (quote or {}).get("price")
                # ⛔ El número tiene que ser el de la rueda de HOY. Si la última
                # barra que trajo el proveedor es la de ayer (pre-apertura,
                # feriado, o la barra del día con los OHLC en NaN), ese
                # `change_pct` es el movimiento de AYER: ni dispara ni re-arma.
                # `change = None` corta las dos cosas de una, porque la rama que
                # re-arma exige `change is not None`.
                if change is not None and not (quote or {}).get("is_today"):
                    log.info("alert %s %s: el %+.2f%% es de la rueda %s, no de "
                             "hoy (%s) → ni disparo ni re-armo",
                             a["id"], sym, change, (quote or {}).get("as_of"),
                             _sesion_hoy(sym))
                    change = None
                    fire_price = None
            side = pct_move_side(change, a["up_pct"], a["down_pct"])

            if base == "set_price":
                # "Desde ahora": la dedup la da el re-ancla (no edge-trigger por símbolo).
                if not side or not tradeable:
                    continue
                _fire(conn, a, sym, fire_price, change, now, pendientes)
                fired += 1
                if a["repeat"] != "once" and fire_price:
                    # "Siempre" = avisar CADA X%: re-anclar al precio actual.
                    conn.execute("UPDATE alerts SET anchor_price=? WHERE id=?",
                                 (fire_price, a["id"]))
                _cumplio_una_vez(conn, a)
            else:
                # "En el día": edge-trigger POR SÍMBOLO + tope de 1 aviso por jornada.
                #  • dispara al cruzar el umbral;
                #  • máximo 1 vez por día UTC por símbolo (si oscila alrededor del 3%
                #    no vuelve a avisar hoy);
                #  • NO se re-arma el mismo día que disparó → el % congelado de ayer no
                #    re-dispara hoy; recién se re-arma un día nuevo cuando el % vuelve
                #    dentro de la banda (al abrir el mercado el change_pct resetea).
                today = _sesion_hoy(sym)
                armed, last_fired_date = _sym_state(conn, a["id"], sym)
                fired_today = (last_fired_date == today)
                if not side:
                    if change is not None and not armed and not fired_today:
                        _set_sym_armed(conn, a["id"], sym, 1)   # día nuevo, dentro de banda → re-arma
                    continue
                # Cripto no tiene pre ni post y su día es el día UTC (opera los
                # sábados): la regla de «mismo cierre» no aplica. Con ella, el
                # sábado, el domingo y el lunes compartían clave y se callaban
                # entre sí (auditoría 2026-10-15).
                es_cripto = sym in _crypto_symbols()
                base = None if es_cripto else _base_de_la_rueda(sym, sesiones_byma)
                if tradeable and base and _toca_el_doble(conn, a, sym, base, side, change):
                    # El mismo movimiento llegó al doble del umbral: segundo y
                    # último aviso, aunque hoy ya haya avisado (+3 % a las 11,
                    # +6 % a las 15; o pre +3 % y abre +6 %).
                    _fire(conn, a, sym, fire_price, change, now, pendientes, doble=True)
                    fired += 1
                    _set_sym_fired(conn, a["id"], sym, today)
                    _anotar_aviso(conn, a, sym, base, side, change, doble=True)
                    _cumplio_una_vez(conn, a)
                    continue
                if not armed or not tradeable or fired_today:
                    continue
                if _ya_avisado(conn, a["id"], sym, base, side):
                    # Es el MISMO movimiento que ya se avisó fuera de la rueda (el
                    # post de anoche o el pre de hoy, contra el mismo cierre): no se
                    # manda nada. El día NO se marca como avisado: si en la rueda
                    # da vuelta (pre +3 %, después −3 %), eso sí se avisa. Y una
                    # alerta «una sola vez» ya cumplió: se apaga — sin callar a
                    # los otros activos de la cartera que se movieron ahora.
                    _cumplio_una_vez(conn, a)
                    continue
                _fire(conn, a, sym, fire_price, change, now, pendientes)
                fired += 1
                _set_sym_fired(conn, a["id"], sym, today)
                _anotar_aviso(conn, a, sym, base, side, change, doble=False)
                _cumplio_una_vez(conn, a)

    # Pre y post mercado de Wall Street (anticipo, con su propio estado).
    # ⚠️ ANTES se confirma lo escrito en el loop: esto pregunta a Yahoo (hasta
    # minutos si anda lento) y con la transacción abierta el resto de la app
    # comía «database is locked» (auditoría 2026-10-15, medido con una segunda
    # conexión). Adentro, la red va antes que cualquier escritura.
    conn.commit()
    try:
        fired += _evaluar_fuera_de_rueda(conn, units, pendientes, now)
    except Exception as ex:
        log.warning("alerts fuera de la rueda falló: %s", ex)

    # La entrega va DESPUÉS del loop: recién cuando terminó de evaluarse toda la
    # cartera se sabe cuántos activos se movieron y puede salir un mail solo.
    #
    # Y DESPUÉS DE CONFIRMAR lo que disparó. El loop deja abierta una
    # transacción de escritura (alert_events, armed, last_fired_*), y la entrega
    # es red: un push y un mail por alerta, cada mail esperando su turno en
    # `emails._send` (PAUSA_ENTRE_ENVIOS). Con el lock tomado durante todo eso,
    # el resto de la app come 'database is locked'. Es el mismo criterio que
    # `advisor_alerts.evaluate`: el aviso queda registrado UNA vez aunque la
    # entrega falle — antes, si el proceso se caía a mitad de la entrega, se
    # deshacía todo y el ciclo siguiente volvía a mandar las que ya habían salido.
    conn.commit()
    _entregar_pendientes(conn, pendientes)

    conn.execute(
        f"UPDATE alerts SET last_evaluated_at=? WHERE active=1 AND {en_vivo}"
        + ("" if only_user is None else " AND user_id=?"),
        (now.isoformat(),) + (() if only_user is None else (only_user,)),
    )
    # La poda va AL FINAL, pegada al último commit: al principio abría la
    # transacción de escritura y la dejaba tomada durante los pedidos de precios.
    _podar_movimientos(conn, now)
    conn.commit()
    return {"alerts": len(alerts), "evaluated": len(units), "fired": fired}


# ─── Alertas técnicas: una vez por día, con las velas de la noche ─────────────
#
# Qué vigila: una señal de la ficha técnica de UN activo (`tecnico.SENALES`):
# cruzó su promedio de 200 o de 50 días (para arriba, para abajo o cualquiera),
# el RSI bajó de 30 / pasó 70 / volvió a pasar 30, cerró en su máximo del año.
#
# Cuándo: con las velas que se guardan cada noche (`velas_diarias`, al final de
# la foto diaria), no en vivo: un cruce de la media de 200 se mira al CIERRE.
# La evaluación va en el cron de alertas pero sólo desde las 9 de la mañana
# (`HORA_AVISO_TECNICO`): las velas llegan cerca de la medianoche y un push a esa
# hora despierta a la gente por algo que puede esperar a la mañana.
#
# Una vez por cruce: cada (alerta, activo) guarda HASTA QUÉ VELA ya miró
# (`_visto_hasta`, en alert_symbol_state con la clave '<activo>#velas'). Cada
# pasada mira sólo las velas nuevas: si una cruzó, avisa; y corre la marca a la
# última vela. Correr el cron de nuevo, o que las velas se guarden dos veces la
# misma noche, no repite nada. La marca arranca en la última vela que había al
# CREAR la alerta (`arrancar_tecnica`): un cruce de antes de crearla no avisa.
#
# Cuentas: las de `tecnico.py` sobre `tecnico.serie` (la serie que corrige los
# cambios de ratio de un CEDEAR), las mismas que dibuja la ficha.

# Desde qué hora (Argentina) salen los avisos técnicos del día.
HORA_AVISO_TECNICO = 9
# Un cruce de hace más que esto no se avisa aunque recién llegue (las velas se
# trabaron una semana y volvieron): ya no es noticia. La marca se corre igual.
DIAS_AVISO_TECNICO = 7
# Un cierre que salta más que `_salto_sospechoso()` contra el anterior puede ser
# Yahoo atrasado con un split (la acción "cae" 75 % hasta que reescribe la
# historia, a veces varias noches después) o un precio roto que nadie corrige
# (una acción argentina sin par afuera). Con ese cierre la alerta diría «quedó
# abajo de su promedio de 200 días» sin que haya pasado nada. Se mira hasta el
# día ANTERIOR al salto y la marca queda ahí hasta que el precio nuevo se
# sostiene `DIAS_CONFIRMA_SALTO` días de mercado (una caída de verdad avisa
# unos días tarde) o la historia se reescribe (el salto desaparece y no hubo
# nada). Es el umbral de "salto sin explicar" de las velas, el mismo número.
DIAS_CONFIRMA_SALTO = 3


def _salto_sospechoso() -> float:
    # Vive en cambios_ratio (la lista única de cambios de ratio de la ficha).
    import cambios_ratio
    return cambios_ratio.SALTO_SIN_EXPLICAR


def _hasta_antes_del_salto(velas: list, visto: str) -> list:
    """Las velas que se pueden mirar hoy: todas, o hasta el día anterior al
    primer salto sin confirmar posterior a `visto`."""
    umbral = _salto_sospechoso()
    for j in range(1, len(velas)):
        if velas[j]["date"] <= visto:
            continue
        a, b = velas[j - 1]["close"], velas[j]["close"]
        if a and b and abs(b / a - 1) > umbral and len(velas) - j < DIAS_CONFIRMA_SALTO:
            return velas[:j]
    return velas

_NO_ES_RECOMENDACION = "Muestra cómo se movió el precio: no es una recomendación para comprar ni vender."


def _clave_velas(symbol) -> str:
    return f"{symbol}#velas"


def _visto_hasta(conn, alert_id: int, symbol):
    """La fecha de la última vela que ya miró esta alerta, o None."""
    return _sym_state(conn, alert_id, _clave_velas(symbol))[1]


def _marcar_visto(conn, alert_id: int, symbol, fecha: str) -> None:
    _set_sym_fired(conn, alert_id, _clave_velas(symbol), fecha)


def _serie_tecnica(conn, alert) -> list:
    """Las velas que mira la alerta: las de la ficha en la moneda elegida
    (`tecnico.serie`), con la marca de acción argentina igual que la ficha."""
    import tecnico
    moneda = "ars" if str(alert["currency"] or "").upper() == "ARS" else "usd"
    return tecnico.serie(conn, alert["symbol"], moneda, bool(_campo(alert, "accion_local")))["velas"]


def arrancar_tecnica(conn, alert) -> None:
    """Pone la marca de «ya miré hasta acá» al crear (o reactivar) una alerta
    técnica: lo que cierre desde HOY cuenta, lo de antes no.

    Es la última vela guardada o ayer, la que sea MÁS NUEVA. Con sólo la última
    vela, unas velas atrasadas dejaban pasar un cruce viejo: un activo que nadie
    seguía desde agosto (o el de una alerta pausada, que deja de bajarse) tenía
    la última vela del 27/08; al crearla el 22/10, esa noche se bajaban los días
    que faltaban y avisaba el cruce del 19/10 (auditoría 22/10). Con «ayer»
    sola, una alerta creada a la 1 de la mañana, con la vela de ayer ya
    guardada, la contaría como nueva."""
    from fechas import hoy_art_date
    ayer = (hoy_art_date() - timedelta(days=1)).isoformat()
    velas = _serie_tecnica(conn, alert)
    hasta = max(velas[-1]["date"], ayer) if velas else ayer
    _marcar_visto(conn, alert["id"], alert["symbol"], hasta)


def _sentido_pedido(alert):
    """El sentido que pidió la alerta para un cruce de media (None = cualquiera)."""
    return {"above": "arriba", "below": "abajo"}.get(alert["direction"])


def _quien_tecnico(alert, symbol) -> str:
    """«AAPL», o «AAPL en pesos» cuando se mira en pesos (la ficha y la alerta
    miran en dólares por defecto: en pesos el precio también sube con el dólar)."""
    sym = _display_symbol(symbol)
    if str(alert["currency"] or "").upper() == "ARS" and not _campo(alert, "accion_local"):
        return f"{sym} en pesos"
    if str(alert["currency"] or "").upper() == "USD" and _campo(alert, "accion_local"):
        return f"{sym} en dólares"
    return sym


def _mensaje_tecnico(alert, symbol, ev) -> str:
    """El titular (asunto, push y «Mis alertas»): qué pasó y qué quiere decir, en
    palabras de la ficha. «AAPL pasó para arriba su promedio de 200 días: la
    tendencia de fondo se volvió alcista»."""
    quien = _quien_tecnico(alert, symbol)
    senal, arriba = alert["senal"], ev["sentido"] == "arriba"
    if senal == "linea":
        ccy = "ARS" if str(alert["currency"] or "").upper() == "ARS" else "USD"
        return (f"{quien} {'subió' if arriba else 'bajó'} hasta tu {_nombre_de_linea(alert)}, "
                f"en {_fmt(ev['referencia'], ccy)}")
    if senal == "media200":
        return (f"{quien} pasó para arriba su promedio de 200 días: la tendencia de fondo se volvió alcista"
                if arriba else
                f"{quien} quedó abajo de su promedio de 200 días: la tendencia de fondo se volvió bajista")
    if senal == "media50":
        return (f"{quien} pasó para arriba su promedio de 50 días: en el corto plazo viene subiendo"
                if arriba else
                f"{quien} quedó abajo de su promedio de 50 días: en el corto plazo viene bajando")
    if senal == "rsi_bajo_30":
        return f"La fuerza (RSI) de {quien} bajó de 30: cayó muy rápido"
    if senal == "rsi_sobre_70":
        return f"La fuerza (RSI) de {quien} pasó 70: subió muy rápido"
    if senal == "rsi_sube_30":
        return f"La fuerza (RSI) de {quien} volvió a pasar 30: dejó de caer tan rápido"
    if senal == "rsi_baja_70":
        return f"La fuerza (RSI) de {quien} volvió a bajar de 70: dejó de subir tan rápido"
    return f"{quien} cerró en su precio más alto del año"


def _detalle_tecnico(alert, symbol, ev) -> str:
    """La oración del mail (va después de «Hola Nico, »): el día, los números y
    qué quieren decir, con las palabras de las tarjetas de la ficha. Describe lo
    que pasó; no anticipa (test_detalle_tecnico_no_promete)."""
    from cartera_hoy import dia_txt
    from fechas import hoy_art
    sym = _display_symbol(symbol)
    ccy = "ARS" if str(alert["currency"] or "").upper() == "ARS" else "USD"
    cuando = dia_txt(ev["fecha"], hoy_art())
    cierre = _fmt(ev["cierre"], ccy)
    senal, arriba = alert["senal"], ev["sentido"] == "arriba"
    if senal == "linea":
        # El día con su mínimo y su máximo: «la tocó» puede ser en el medio de
        # la rueda y cerrar lejos.
        return (f"{cuando} {sym} tocó tu {_nombre_de_linea(alert)}, que ese día estaba en "
                f"{_fmt(ev['referencia'], ccy)}: fue de {_fmt(ev['minimo'], ccy)} a "
                f"{_fmt(ev['maximo'], ccy)} y cerró en {cierre}. Es la línea que dibujaste en su gráfico.")
    if senal in ("media200", "media50"):
        dias = 200 if senal == "media200" else 50
        prom = _fmt(ev["referencia"], ccy)
        if senal == "media200":
            lectura = (f"Estar {'arriba' if arriba else 'abajo'} de ese promedio es la señal más usada "
                       f"de que la tendencia de fondo es {'alcista' if arriba else 'bajista'}.")
        else:
            lectura = (f"Quiere decir que en los últimos meses viene "
                       f"{'subiendo' if arriba else 'bajando'}.")
        return f"{cuando} {sym} cerró en {cierre} y su promedio de {dias} días está en {prom}. {lectura}"
    if senal.startswith("rsi_"):
        fuerza = f"{cuando} la fuerza (RSI) de {sym} quedó en {_fmt_rsi(ev['rsi'], ev['referencia'])} de 100, con un cierre de {cierre}."
        # Describen, no anticipan: «suele frenar» y «suele rebotar» no se cumplieron
        # en la medición. La caída es la única con algo de ventaja, y su frase es
        # la de «Tus señales» (UNA, en senales_semana), no otra escrita acá.
        from senales_semana import POSIBILIDAD_REBOTE
        lectura = {
            "rsi_bajo_30": f"Bajar de 30 es caer muy rápido. {POSIBILIDAD_REBOTE}",
            "rsi_sobre_70": "Pasar 70 es subir muy rápido.",
            "rsi_sube_30": "Volver a pasar 30: dejó de caer tan rápido.",
            "rsi_baja_70": "Volver a bajar de 70: dejó de subir tan rápido.",
        }[senal]
        return f"{fuerza} {lectura}"
    return f"{cuando} {sym} cerró en {cierre}, el cierre más alto de los últimos 12 meses."


def _nombre_de_linea(alert) -> str:
    """«línea horizontal» o «línea de tendencia» (lo dice la referencia al dibujo)."""
    ref = referencia_de_linea(_campo(alert, "dibujo")) or {}
    return "línea de tendencia" if ref.get("tipo") == "tendencia" else "línea horizontal"


def _fmt_rsi(r, nivel) -> str:
    """El RSI sin decimales, como la ficha; con uno si redondeado cae justo en
    el nivel que cruzó: «bajó de 30» con «quedó en 30» se contradice (29,6)."""
    r = r or 0.0
    return fmt_num(r, 1) if round(r) == round(nivel or 0) else str(round(r))


def evaluar_tecnicas(conn, now: datetime = None, only_user: int = None) -> dict:
    """Las alertas técnicas activas contra las velas guardadas. Idempotente: lo
    pega el cron de alertas cada pocos minutos y sólo trabaja la primera pasada
    después de que llegan velas nuevas (ver el bloque de arriba)."""
    from fechas import dia_art, en_art
    now = now or datetime.utcnow()
    if en_art(now).hour < HORA_AVISO_TECNICO:
        return {"tecnicas": 0, "esperando": f"desde las {HORA_AVISO_TECNICO}:00"}
    q = "SELECT * FROM alerts WHERE active=1 AND kind='tecnica'"
    params: tuple = ()
    if only_user is not None:
        q += " AND user_id=?"
        params = (only_user,)
    alerts = conn.execute(q, params).fetchall()
    if not alerts:
        return {"tecnicas": 0, "fired": 0}
    hoy = dia_art(now)
    piso = (hoy - timedelta(days=DIAS_AVISO_TECNICO)).isoformat()
    # La última vela que hay en toda la tabla: una alerta que ya miró hasta ahí
    # no tiene nada nuevo y no se lee su serie (el cron pega cada 10 minutos).
    row = conn.execute("SELECT MAX(date) AS d FROM velas_diarias").fetchone()
    ultima_global = row["d"] if row else None
    series: dict = {}
    pendientes: list = []
    fired = mirados = errores = 0
    for a in alerts:
        # Una alerta que revienta (un activo raro, una serie rota) no puede dejar
        # sin mirar a las demás: el cron pega cada 10 minutos y fallaría siempre
        # en la misma. Las cuentas van antes de cualquier escritura.
        # Pero el error queda a la vista: con el NOMBRE del error y su traza en el
        # registro, y contado en el resultado del cron. Al juntar ficha-tecnica
        # con estas alertas, un número mudado de archivo (SALTO_SIN_EXPLICAR) hacía
        # fallar TODAS, cada 10 minutos, con un aviso que nadie miraba: ninguna
        # alerta técnica avisaba nunca (pieza 15, 11f57c03).
        try:
            resultado = _evaluar_una_tecnica(conn, a, series, ultima_global, piso, now, pendientes)
        except Exception as ex:
            errores += 1
            log.error("alert técnica %s (%s) falló: %s: %s", a["id"], a["symbol"],
                      type(ex).__name__, ex, exc_info=True)
            continue
        mirados += resultado in ("mirada", "avisó")
        fired += resultado == "avisó"
    # Lo disparado y las marcas quedan confirmados ANTES de entregar (la entrega
    # es red): igual que `evaluate_alerts`.
    conn.commit()
    _entregar_pendientes(conn, pendientes)
    out = {"tecnicas": len(alerts), "mirados": mirados, "fired": fired}
    if errores:
        out["errores"] = errores
    return out


def _evaluar_una_tecnica(conn, a, series: dict, ultima_global, piso: str, now, pendientes: list) -> str:
    """Una alerta técnica contra sus velas nuevas. Devuelve qué pasó: 'nada'
    (nada nuevo que mirar), 'mirada' o 'avisó'."""
    import tecnico
    sym = a["symbol"]
    if not sym or (a["senal"] not in _senales() and a["senal"] != tecnico.SENAL_LINEA):
        return "nada"
    visto = _visto_hasta(conn, a["id"], sym)
    if visto and ultima_global and visto >= ultima_global:
        return "nada"
    linea = None
    if a["senal"] == tecnico.SENAL_LINEA:
        # La línea como está AHORA en tu gráfico (si la moviste, la nueva).
        linea = linea_de_la_alerta(conn, a)
        if linea is None:
            # Borraste la línea: el aviso no tiene qué mirar y se apaga (no se
            # borra: queda en Mis alertas, apagado, por si fue sin querer).
            conn.execute("UPDATE alerts SET active=0 WHERE id=?", (a["id"],))
            log.info("alert %s %s: la línea %s ya no está, se apaga", a["id"], sym, _campo(a, "dibujo"))
            return "nada"
    clave = (sym, str(a["currency"] or "").upper(), bool(_campo(a, "accion_local")))
    if clave not in series:
        series[clave] = _serie_tecnica(conn, a)
    velas = series[clave]
    if not velas:
        return "nada"       # todavía no hay velas: la marca queda donde estaba
    if visto is None:
        # Sin marca (no debería pasar: la pone el alta): se arranca acá, sin avisar.
        _marcar_visto(conn, a["id"], sym, velas[-1]["date"])
        return "nada"
    mirables = _hasta_antes_del_salto(velas, visto)
    if len(mirables) < len(velas):
        log.info("alert %s %s: el cierre del %s saltó demasiado, se espera a que se confirme",
                 a["id"], sym, velas[len(mirables)]["date"])
    if not mirables or mirables[-1]["date"] <= visto:
        return "nada"
    ultima = mirables[-1]["date"]
    ev = (tecnico.toque_de_linea(mirables, linea, visto) if linea is not None
          else tecnico.senal_desde(mirables, a["senal"], visto, _sentido_pedido(a)))
    if ev and ev["fecha"] < piso:
        log.info("alert %s %s: %s del %s llegó tarde, no aviso", a["id"], sym, a["senal"], ev["fecha"])
        ev = None
    if ev:
        _fire(conn, a, sym, ev["cierre"], None, now, pendientes, tecnica=ev)
        _cumplio_una_vez(conn, a)
    _marcar_visto(conn, a["id"], sym, ultima)
    return "avisó" if ev else "mirada"


def referencia_de_linea(texto):
    """Qué línea mira una alerta (columna `dibujo`): {'asset', 'moneda', 'id',
    'tipo'} o None si está vacía o rota."""
    try:
        r = json.loads(texto or "null")
    except (TypeError, ValueError):
        return None
    if not isinstance(r, dict) or not all(isinstance(r.get(k), str) and r.get(k) for k in ("asset", "moneda", "id")):
        return None
    return r


def linea_de_la_alerta(conn, alert):
    """La línea que dibujaste, TAL COMO ESTÁ AHORA en tu gráfico (tabla
    `dibujos_grafico`, la misma que lee la ficha): {'tipo', 'precio'} o
    {'tipo', 'a', 'b'}. None si ya no está (la borraste)."""
    ref = referencia_de_linea(_campo(alert, "dibujo"))
    if not ref:
        return None
    fila = conn.execute(
        "SELECT datos FROM dibujos_grafico WHERE user_id = ? AND asset = ? AND moneda = ?",
        (alert["user_id"], ref["asset"], ref["moneda"])).fetchone()
    try:
        dibujos = json.loads(fila[0]) if fila else []
    except (TypeError, ValueError):
        dibujos = []
    for d in dibujos if isinstance(dibujos, list) else []:
        if isinstance(d, dict) and d.get("id") == ref["id"] and d.get("tipo") in ("horizontal", "tendencia"):
            return d
    return None


def _senales() -> tuple:
    import tecnico
    return tecnico.SENALES


# ─── Recordatorios de una tesis («Recordarme revisarla») ─────────────────────
# Una alerta más del mismo motor: `kind='recordatorio'`, una sola vez, mail +
# push. La fecha y el texto viven en la tabla `tesis` (tesis.py). Llega desde
# las 9:00 de Argentina del día marcado: el cron de alertas corre cada ~10 min
# y a medianoche un push despierta gente.
HORA_RECORDATORIO = 9


def evaluar_recordatorios(conn, now: datetime = None) -> dict:
    """Dispara los recordatorios de tesis que llegaron a su día. Mismo circuito
    que las de precio: anota el evento en `alert_events` (la lista de avisos de
    la app), apaga la alerta (es «una vez»), confirma, y DESPUÉS entrega
    (`_entregar_pendientes`, que no lleva el lock de escritura a la red)."""
    import tesis as _tesis
    from fechas import ART_OFFSET_HORAS, dia_art
    now = now or datetime.utcnow()
    hoy = dia_art(now)
    if (now - timedelta(hours=ART_OFFSET_HORAS)).hour < HORA_RECORDATORIO:
        return {"recordatorios": 0}
    filas = conn.execute(
        """SELECT a.*, t.asset AS t_asset, t.texto AS t_texto, t.escrita_el AS t_escrita_el,
                  t.tendencia_json AS t_tendencia_json, t.accion_local AS t_accion_local
             FROM alerts a JOIN tesis t ON t.alert_id = a.id AND t.user_id = a.user_id
            WHERE a.kind = 'recordatorio' AND a.active = 1 AND t.recordar_el <= ?""",
        (hoy.isoformat(),)).fetchall()
    pendientes = []
    for a in filas:
        t = {k[2:]: a[k] for k in a.keys() if k.startswith("t_")}
        try:
            contenido = _tesis.para_el_aviso(conn, t)
        except Exception as ex:
            log.warning("recordatorio %s: no se pudo armar: %s", a["id"], ex)
            continue
        contenido["heading"] = contenido["titulo"]
        contenido["pie"] = ("Te lo recordamos una sola vez.", "Ver tu tesis",
                            contenido["cta_path"])
        cur = conn.execute(
            """INSERT INTO alert_events (alert_id, user_id, symbol, fired_at, price, message,
                                         delivered_push, delivered_email)
               VALUES (?,?,?,?,NULL,?,0,0)""",
            (a["id"], a["user_id"], t["asset"], now.isoformat(), contenido["titulo"]))
        conn.execute("UPDATE alerts SET active=0, last_fired_at=? WHERE id=?",
                     (now.isoformat(), a["id"]))
        pendientes.append({"alert": a, "symbol": t["asset"], "price": None, "change_pct": None,
                           "message": contenido["titulo"], "label": contenido["titulo"],
                           "event_id": cur.lastrowid, "fuera": None, "doble": False,
                           "contenido": contenido})
    conn.commit()
    _entregar_pendientes(conn, pendientes)
    return {"recordatorios": len(pendientes)}
