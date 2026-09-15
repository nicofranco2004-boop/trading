"""Motor de evaluación de alertas personalizadas.

Dos tipos de alerta (ver schema en main.init_db):
  • price_target — avisar cuando `symbol` cruza `threshold` en `direction`
    (above/below). Usa EDGE-TRIGGER con la columna `armed`: dispara SOLO en la
    transición no-cumplida → cumplida, nunca mientras el precio sigue del lado
    disparado. Re-arma cuando el precio vuelve a cruzar (repeat != 'once').
  • pct_move — avisar cuando un activo se mueve `threshold`% vs el cierre previo.
    `scope='holdings'` evalúa TODAS las tenencias del user; `scope='ticker'` una.
    Como el % es vs prev_close (que se resetea cada día), el anti-spam es por
    COOLDOWN por (alerta, símbolo) vía la tabla alert_events — no la columna
    armed (una alerta holdings tiene N símbolos, cada uno con su propio estado).

Precios: reusa los MISMOS rieles que el snapshot diario (fetch_prices_for_symbols
→ stocks/CEDEARs/cripto/FCI/bonos) para price_target, y _fetch_batch_quotes
(change_pct vs cierre previo) para pct_move. NUNCA dispara con precio None/stale.

Y nunca dispara con un porcentaje que no sea el de la rueda de HOY: cada quote
viaja con la fecha de la rueda que midió (`as_of`/`is_today`, ver home.market),
y si esa fecha no es la de hoy el número no se usa ni para disparar ni para
re-armar. Hacía falta porque antes de que abra el mercado —y cuando la barra del
día viene con los OHLC en NaN, que con los `.BA` pasa seguido— el proveedor
devuelve el cierre a cierre de AYER, y salía por mail con el título "hoy".

Entrega: reusa _send_push_to_user (Web Push) + billing.emails.send_alert_email
(Resend). Cada disparo queda logueado en alert_events (dedup + feed in-app), uno
por activo — pero el ENVÍO es uno por alerta y por ciclo: una alerta de "toda mi
cartera" se expande a todas las tenencias y un día movido dispara varias juntas.
Los disparos se acumulan durante el loop y salen agrupados al final.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("alerts")

VALID_KINDS = ("price_target", "pct_move")
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
    """{symbol: {price, prev_close, change_pct}} vía yfinance (para pct_move)."""
    syms = [s for s in set(symbols) if s]
    if not syms:
        return {}
    try:
        from home.market import _fetch_batch_quotes
        return _fetch_batch_quotes(syms) or {}
    except Exception as ex:
        log.warning("alerts _quotes_for falló: %s", ex)
        return {}


def price_for_alert(symbol: str):
    """Precio actual de UN símbolo — para armar el edge-trigger al crear la
    alerta (arma según de qué lado del umbral está hoy)."""
    return _prices_for([symbol]).get(symbol)


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


def _market_open_now(now) -> bool:
    """¿Hay alguna rueda abierta ahora? Es la unión de las dos que nos importan:
    NYSE/Nasdaq y BYMA. Las alertas de acciones/CEDEARs/bonos SOLO disparan acá
    adentro; cripto no pasa por esta función (opera 24/7).

    🔴 Lo que decía antes: "L-V, 13:00–21:00 UTC". Esa media hora de más por
    delante es la que mandó la ráfaga del 15/09/2026 a las 13:01 UTC (10:01 ART):
    Nueva York abre 13:30 UTC en horario de verano y BYMA 14:00 UTC, así que a
    las 13:01 NO había rueda abierta en ningún lado y el `change_pct` que traía
    el proveedor era todavía el del día anterior. Cuatro mails con el movimiento
    del lunes fechados como "hoy".

    Las horas se preguntan a la base de zonas horarias en vez de escribirse como
    un offset fijo, porque Estados Unidos sí tiene horario de verano y la ventana
    en UTC se corre una hora dos veces al año. Esto NO es un segundo calendario:
    contesta "¿hay rueda?", no "¿qué día es?" — esa sigue siendo de `fechas.py`."""
    from datetime import timezone
    ahora = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    try:
        from zoneinfo import ZoneInfo
        return (_en_rueda(ahora.astimezone(ZoneInfo("America/New_York")), *_SESION_US)
                or _en_rueda(ahora.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")),
                             *_SESION_BYMA))
    except Exception as ex:
        # Sin base de zonas horarias (imagen sin tzdata): ventana fija ANCHA pero
        # que nunca empieza antes que la apertura más temprana real (13:30 UTC,
        # NY en verano) — no puede repetir el bug de las 13:01. El guard fino de
        # pct_move no depende de esta función: mira la FECHA de la rueda.
        log.warning("alerts _market_open_now sin zoneinfo (%s): ventana fija UTC", ex)
        if ahora.weekday() >= 5:
            return False
        return (13 * 60 + 30) <= (ahora.hour * 60 + ahora.minute) < (21 * 60)


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


def _fmt(price, currency) -> str:
    """Precio en convención argentina. Mostraba los pesos bien ($7.350) y los
    dólares a la inglesa (US$2,145.30) en el MISMO mail; ahora los dos salen
    del único formateador, money_fmt.fmt_money. Ojo: esto arma también el
    ASUNTO de la alerta, no sólo el cuerpo."""
    from money_fmt import fmt_money
    return fmt_money(price, currency)


def _compose_message(alert, symbol, price, change_pct) -> str:
    sym = _display_symbol(symbol)
    ccy = _ccy_for(symbol, alert["currency"])
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
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def _short_label(alert, symbol, price, change_pct) -> str:
    """Un movimiento en pocas palabras: "INTC cayó 5.8%".

    Es `_compose_message` sin el "hoy" del final, que en una lista de cuatro se
    repetiría cuatro veces. El "hoy" lo dice el asunto una sola vez."""
    if alert["kind"] == "price_target":
        return _compose_message(alert, symbol, price, change_pct)
    verbo = "subió" if (change_pct or 0) >= 0 else "cayó"
    return f"{_display_symbol(symbol)} {verbo} {_fmt_pct(change_pct)}%"


def _group_line(alert, symbol, price, change_pct) -> str:
    """Un renglón de la lista del mail agrupado: el movimiento y a cuánto
    cotiza, en la moneda del activo (un CEDEAR cotiza en pesos)."""
    base = _short_label(alert, symbol, price, change_pct)
    if price is None:
        return base
    return f"{base} y cotiza a {_fmt(price, _ccy_for(symbol, alert['currency']))}"


def _compose_group_message(items) -> str:
    """El asunto de un aviso agrupado. Nombra los movimientos en vez de
    contarlos: "INTC cayó 5.8%, NVDA cayó 3.4% y 2 más hoy", no "4 alertas".

    Es la misma lección que el resumen de mercado — el asunto ES el titular y es
    lo que decide si el mail se abre; cuántos avisos hay es justo lo que a nadie
    le importa. `items` llega ya ordenado de mayor a menor movimiento."""
    etiquetas = [it["label"] for it in items]
    if len(etiquetas) == 2:
        return f"{etiquetas[0]} y {etiquetas[1]} hoy"
    return f"{etiquetas[0]}, {etiquetas[1]} y {len(etiquetas) - 2} más hoy"


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
    uid, client_label = _delivery_target(conn, alert["user_id"])
    # Más grande primero: si hay que nombrar dos en el asunto, que sean los dos
    # que más se movieron.
    items = sorted(items, key=lambda it: abs(it.get("change_pct") or 0), reverse=True)
    heading = (items[0]["message"] if len(items) == 1
               else _compose_group_message(items))
    if client_label:
        # El asesor recibe alertas de N clientes: el prefijo dice de quién es.
        heading = f"[{client_label}] {heading}"
    channel = alert["channel"] or "both"
    push_ok = email_ok = False

    if channel in ("push", "both"):
        try:
            import main
            sent = main._send_push_to_user(uid, {
                "title": "Rendi · Alerta",
                "body": heading,
                # Iba a /config?tab=notificaciones: ruta MUERTA desde que las
                # alertas se mudaron a /alertas (en Config ya no existe esa
                # pestana), asi que tocar el push caia en Config > Cuenta.
                "url": "/dashboard",
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
                if len(items) == 1:
                    it = items[0]
                    detail = _email_detail(alert, it["symbol"], it["price"],
                                           it["change_pct"])
                    lines = None
                else:
                    detail = f"se movieron {len(items)} activos de tu cartera hoy:"
                    lines = [it["line"] for it in items]
                email_ok = emails.send_alert_email(
                    to=row["email"], user_name=(row["name"] or ""),
                    heading=heading, detail=detail, lines=lines)
        except Exception as ex:
            log.warning("alerts email uid=%s falló: %s", uid, ex)

    return push_ok, email_ok


def _email_detail(alert, symbol, price=None, change_pct=None) -> str:
    """Cuerpo del mail: los NÚMEROS, no una invitación a ir a buscarlos.

    Antes decía "tuvo un movimiento importante hoy, entrá a Rendi para ver
    cómo impacta en tu cartera": el título traía más información que el
    cuerpo, y un mail que no dice nada no se abre. Gmail mide justamente eso
    para decidir la pestaña — medido el 2026-09-09 sobre la casilla del
    fundador, las ÚNICAS alertas que se salieron de Actualizaciones son las
    que estaban leídas. `price` y `change_pct` ya los tenía _deliver() al
    lado; sólo no se los pasaba a esta función."""
    sym = _display_symbol(symbol)
    ccy = _ccy_for(symbol, alert["currency"])
    cur = _fmt(price, ccy)
    if alert["kind"] == "price_target":
        thr = _fmt(alert["threshold"], ccy)
        lado = "subió hasta" if alert["direction"] == "above" else "bajó hasta"
        if price is None:
            return f"{sym} cruzó los {thr} que habías marcado."
        return (f"{sym} {lado} {cur}. Vos habías marcado {thr}, "
                f"así que ya lo cruzó.")
    desde = ("desde que armaste la alerta"
             if (alert["baseline"] or "prev_close") == "set_price"
             else "desde el cierre de ayer")
    if change_pct is None:
        return f"{sym} se movió {desde}."
    verbo = "subió" if (change_pct or 0) >= 0 else "cayó"
    cotiza = f" y cotiza a {cur}" if price is not None else ""
    return f"{sym} {verbo} {_fmt_pct(change_pct)}% {desde}{cotiza}."


def _fire(conn, alert, symbol, price, change_pct, now: datetime, pendientes: list):
    """Dispara: log en alert_events + actualiza last_fired_* + ENCOLA la entrega.

    El mail y el push no salen acá. Se acumulan en `pendientes` y salen al
    cerrar el ciclo, agrupados por alerta (ver `_entregar_pendientes`): si no,
    una alerta de toda la cartera manda un mail por cada activo que se movió.

    El evento de la app se escribe igual, uno por activo y en el momento — es lo
    que alimenta la lista de "Últimos avisos" y el puntito del sidebar. Las dos
    banderas de entregado se completan cuando la entrega efectivamente sale."""
    message = _compose_message(alert, symbol, price, change_pct)
    cur = conn.execute(
        """INSERT INTO alert_events
           (alert_id, user_id, symbol, fired_at, price, message,
            delivered_push, delivered_email)
           VALUES (?,?,?,?,?,?,0,0)""",
        (alert["id"], alert["user_id"], symbol, now.isoformat(),
         price if price is not None else change_pct, message),
    )
    conn.execute(
        "UPDATE alerts SET last_fired_at=?, last_fired_price=? WHERE id=?",
        (now.isoformat(), price if price is not None else None, alert["id"]),
    )
    pendientes.append({
        "alert": alert, "symbol": symbol, "price": price,
        "change_pct": change_pct, "message": message,
        "label": _short_label(alert, symbol, price, change_pct),
        "line": _group_line(alert, symbol, price, change_pct),
        "event_id": cur.lastrowid,
    })
    log.info("alert %s fired (uid=%s sym=%s): %s",
             alert["id"], alert["user_id"], symbol, message)


def _entregar_pendientes(conn, pendientes: list) -> None:
    """Entrega todo lo que disparó en el ciclo, con un envío por alerta.

    Una alerta que falla al entregar no puede dejar sin avisar a las otras: cada
    grupo va en su propio try (misma guarda que el cron usa entre el motor de
    precios y el del libro del asesor)."""
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
        conn.executemany(
            "UPDATE alert_events SET delivered_push=?, delivered_email=? WHERE id=?",
            [(1 if push_ok else 0, 1 if email_ok else 0, it["event_id"]) for it in items])
        log.info("alert %s entregada (%s aviso/s, push=%s email=%s)",
                 alert["id"], len(items), push_ok, email_ok)


# ─── Loop principal ────────────────────────────────────────────────────────────

def evaluate_alerts(conn, only_user: int = None) -> dict:
    """Evalúa TODAS las alertas activas (o las de un user). Idempotente y seguro
    para correr cada N minutos desde un cron externo. Commit al final."""
    now = datetime.utcnow()
    q = "SELECT * FROM alerts WHERE active=1"
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
    quotes = _quotes_for(list(quote_syms)) if quote_syms else {}

    market_open = _market_open_now(now)
    # Los avisos de este ciclo se acumulan acá y salen todos juntos al final,
    # un envío por alerta. Ver `_entregar_pendientes`.
    pendientes: list = []
    fired = 0
    deactivated: set = set()   # alertas 'once' de pct_move ya disparadas este ciclo
    for a, sym in units:
        if a["id"] in deactivated:
            continue
        # Acciones/CEDEARs/bonos: solo disparan en horario de mercado (evita saltos
        # de madrugada sobre precios congelados). Cripto: 24/7.
        tradeable = (sym in _crypto_symbols()) or market_open

        if a["kind"] == "price_target":
            price = prices.get(sym)
            met = condition_met("price_target", a["direction"], a["threshold"], price, None)
            if met is None:
                continue  # sin precio → no adivinar
            if a["armed"] and met and tradeable:
                _fire(conn, a, sym, price, None, now, pendientes)
                fired += 1
                new_active = 0 if a["repeat"] == "once" else 1
                conn.execute("UPDATE alerts SET armed=0, active=? WHERE id=?",
                             (new_active, a["id"]))
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
                if a["repeat"] == "once":
                    conn.execute("UPDATE alerts SET active=0 WHERE id=?", (a["id"],))
                    deactivated.add(a["id"])
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
                if not armed or not tradeable or fired_today:
                    continue
                _fire(conn, a, sym, fire_price, change, now, pendientes)
                fired += 1
                _set_sym_fired(conn, a["id"], sym, today)
                if a["repeat"] == "once":
                    conn.execute("UPDATE alerts SET active=0 WHERE id=?", (a["id"],))
                    deactivated.add(a["id"])

    # La entrega va DESPUÉS del loop: recién cuando terminó de evaluarse toda la
    # cartera se sabe cuántos activos se movieron y puede salir un mail solo.
    _entregar_pendientes(conn, pendientes)

    conn.execute(
        "UPDATE alerts SET last_evaluated_at=? WHERE active=1"
        + ("" if only_user is None else " AND user_id=?"),
        (now.isoformat(),) + (() if only_user is None else (only_user,)),
    )
    conn.commit()
    return {"alerts": len(alerts), "evaluated": len(units), "fired": fired}
