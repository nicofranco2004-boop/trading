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

Entrega: reusa _send_push_to_user (Web Push) + billing.emails.send_alert_email
(Resend). Cada disparo queda logueado en alert_events (dedup + feed in-app).
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


def _market_open_now(now) -> bool:
    """Aproximado: L-V, ~13:00–21:00 UTC (cubre US 9:30–16 ET + BYMA 11–17 ART).
    Las alertas de acciones/CEDEARs/bonos SOLO disparan en esta ventana — así no
    saltan de madrugada/finde sobre el `change_pct` congelado del último cierre.
    Cripto no pasa por acá (opera 24/7)."""
    if now.weekday() >= 5:      # 5=sábado, 6=domingo
        return False
    return 13 <= now.hour < 21


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

def _sym_armed(conn, alert_id: int, symbol) -> int:
    row = conn.execute(
        "SELECT armed FROM alert_symbol_state WHERE alert_id=? AND symbol=?",
        (alert_id, symbol),
    ).fetchone()
    return int(row["armed"]) if row else 1   # sin registro = armado


def _set_sym_armed(conn, alert_id: int, symbol, armed: int):
    conn.execute(
        "INSERT INTO alert_symbol_state (alert_id, symbol, armed, updated_at) "
        "VALUES (?,?,?,datetime('now')) "
        "ON CONFLICT(alert_id, symbol) DO UPDATE SET "
        "armed=excluded.armed, updated_at=excluded.updated_at",
        (alert_id, symbol, armed),
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


def _fmt(price, currency) -> str:
    if price is None:
        return "—"
    if (currency or "").upper() == "ARS":
        return f"${price:,.0f}".replace(",", ".")
    return f"US${price:,.2f}"


def _compose_message(alert, symbol, price, change_pct) -> str:
    sym = _display_symbol(symbol)
    if alert["kind"] == "price_target":
        thr = _fmt(alert["threshold"], alert["currency"])
        cur = _fmt(price, alert["currency"])
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


# ─── Entrega ──────────────────────────────────────────────────────────────────

def _deliver(conn, alert, symbol, price, change_pct, message) -> tuple:
    """Manda push + email según channel. Devuelve (push_ok, email_ok)."""
    uid = alert["user_id"]
    channel = alert["channel"] or "both"
    push_ok = email_ok = False

    if channel in ("push", "both"):
        try:
            import main
            sent = main._send_push_to_user(uid, {
                "title": "Rendi · Alerta",
                "body": message,
                "url": "/config?tab=notificaciones",
                "tag": f"alert-{alert['id']}-{symbol or ''}",
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
                    to=row["email"], user_name=(row["name"] or ""),
                    heading=message, detail=_email_detail(alert, symbol))
        except Exception as ex:
            log.warning("alerts email uid=%s falló: %s", uid, ex)

    return push_ok, email_ok


def _email_detail(alert, symbol) -> str:
    sym = _display_symbol(symbol)
    if alert["kind"] == "price_target":
        return (f"El precio de {sym} cruzó el valor que definiste. "
                "Entrá a Rendi para ver el detalle y decidir tu próximo paso.")
    return (f"{sym} tuvo un movimiento importante hoy. "
            "Entrá a Rendi para ver cómo impacta en tu cartera.")


def _fire(conn, alert, symbol, price, change_pct, now: datetime):
    """Dispara: entrega + log en alert_events + actualiza last_fired_*."""
    message = _compose_message(alert, symbol, price, change_pct)
    push_ok, email_ok = _deliver(conn, alert, symbol, price, change_pct, message)
    conn.execute(
        """INSERT INTO alert_events
           (alert_id, user_id, symbol, fired_at, price, message,
            delivered_push, delivered_email)
           VALUES (?,?,?,?,?,?,?,?)""",
        (alert["id"], alert["user_id"], symbol, now.isoformat(),
         price if price is not None else change_pct, message,
         1 if push_ok else 0, 1 if email_ok else 0),
    )
    conn.execute(
        "UPDATE alerts SET last_fired_at=?, last_fired_price=? WHERE id=?",
        (now.isoformat(), price if price is not None else None, alert["id"]),
    )
    log.info("alert %s fired (uid=%s sym=%s push=%s email=%s): %s",
             alert["id"], alert["user_id"], symbol, push_ok, email_ok, message)


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
                _fire(conn, a, sym, price, None, now)
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
            side = pct_move_side(change, a["up_pct"], a["down_pct"])

            if base == "set_price":
                # "Desde ahora": la dedup la da el re-ancla (no edge-trigger por símbolo).
                if not side or not tradeable:
                    continue
                _fire(conn, a, sym, fire_price, change, now)
                fired += 1
                if a["repeat"] != "once" and fire_price:
                    # "Siempre" = avisar CADA X%: re-anclar al precio actual.
                    conn.execute("UPDATE alerts SET anchor_price=? WHERE id=?",
                                 (fire_price, a["id"]))
                if a["repeat"] == "once":
                    conn.execute("UPDATE alerts SET active=0 WHERE id=?", (a["id"],))
                    deactivated.add(a["id"])
            else:
                # "En el día": edge-trigger POR SÍMBOLO. Dispara al cruzar el umbral;
                # se re-arma cuando el % vuelve DENTRO de la banda (al abrir el mercado
                # el change_pct resetea) → el movimiento de AYER no re-dispara HOY.
                armed = _sym_armed(conn, a["id"], sym)
                if not side:
                    if change is not None and not armed:
                        _set_sym_armed(conn, a["id"], sym, 1)   # dentro de la banda → re-arma
                    continue
                if not armed or not tradeable:
                    continue
                _fire(conn, a, sym, fire_price, change, now)
                fired += 1
                _set_sym_armed(conn, a["id"], sym, 0)
                if a["repeat"] == "once":
                    conn.execute("UPDATE alerts SET active=0 WHERE id=?", (a["id"],))
                    deactivated.add(a["id"])

    conn.execute(
        "UPDATE alerts SET last_evaluated_at=? WHERE active=1"
        + ("" if only_user is None else " AND user_id=?"),
        (now.isoformat(),) + (() if only_user is None else (only_user,)),
    )
    conn.commit()
    return {"alerts": len(alerts), "evaluated": len(units), "fired": fired}
