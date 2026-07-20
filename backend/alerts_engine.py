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


# ─── Lógica de condición ──────────────────────────────────────────────────────

def condition_met(kind: str, direction: str, threshold: float,
                  price, change_pct):
    """¿La alerta está CUMPLIDA ahora? Devuelve True/False, o None si no hay
    dato para decidir (precio/quote ausente → NO disparar, no adivinar)."""
    if kind == "price_target":
        if price is None:
            return None
        if direction == "above":
            return price >= threshold
        if direction == "below":
            return price <= threshold
        return None  # 'either' no aplica a price_target
    if kind == "pct_move":
        if change_pct is None:
            return None
        mag = abs(threshold)
        if direction == "above":
            return change_pct >= mag
        if direction == "below":
            return change_pct <= -mag
        return abs(change_pct) >= mag  # either
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
            return f"{sym} alcanzó {cur} (tu alerta: ≥ {thr})"
        return f"{sym} bajó a {cur} (tu alerta: ≤ {thr})"
    # pct_move
    verbo = "subió" if (change_pct or 0) >= 0 else "cayó"
    return f"{sym} {verbo} {abs(change_pct):.1f}% hoy (tu alerta: {_pct_desc(alert)})"


def _pct_desc(alert) -> str:
    mag = abs(alert["threshold"])
    if alert["direction"] == "above":
        return f"sube ≥ {mag:.0f}%"
    if alert["direction"] == "below":
        return f"cae ≥ {mag:.0f}%"
    return f"se mueve ≥ {mag:.0f}%"


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
    units: list = []          # [(alert_row, symbol)]
    price_syms: set = set()   # necesitan precio actual (price_target)
    quote_syms: set = set()   # necesitan change_pct (pct_move)
    holdings_cache: dict = {}
    for a in alerts:
        if a["scope"] == "holdings":
            uid = a["user_id"]
            if uid not in holdings_cache:
                holdings_cache[uid] = _holding_symbols(conn, uid)
            for sym in holdings_cache[uid]:
                units.append((a, sym))
                (quote_syms if a["kind"] == "pct_move" else price_syms).add(sym)
        else:
            sym = a["symbol"]
            if not sym:
                continue
            units.append((a, sym))
            (quote_syms if a["kind"] == "pct_move" else price_syms).add(sym)

    prices = _prices_for(list(price_syms)) if price_syms else {}
    quotes = _quotes_for(list(quote_syms)) if quote_syms else {}

    fired = 0
    for a, sym in units:
        if a["kind"] == "price_target":
            price = prices.get(sym)
            met = condition_met("price_target", a["direction"], a["threshold"], price, None)
            if met is None:
                continue  # sin precio → no adivinar
            if a["armed"] and met:
                _fire(conn, a, sym, price, None, now)
                fired += 1
                # once → inactiva; recurrente → desarma hasta que vuelva a cruzar
                new_active = 0 if a["repeat"] == "once" else 1
                conn.execute("UPDATE alerts SET armed=0, active=? WHERE id=?",
                             (new_active, a["id"]))
            elif not a["armed"] and not met:
                conn.execute("UPDATE alerts SET armed=1 WHERE id=?", (a["id"],))  # re-arma
        else:  # pct_move — anti-spam por cooldown per (alerta, símbolo)
            quote = quotes.get(sym)
            change = quote.get("change_pct") if quote else None
            met = condition_met("pct_move", a["direction"], a["threshold"], None, change)
            if not met:
                continue
            if _recently_fired(conn, a["id"], sym, a["cooldown_min"], now):
                continue
            _fire(conn, a, sym, (quote or {}).get("price"), change, now)
            fired += 1

    conn.execute(
        "UPDATE alerts SET last_evaluated_at=? WHERE active=1"
        + ("" if only_user is None else " AND user_id=?"),
        (now.isoformat(),) + (() if only_user is None else (only_user,)),
    )
    conn.commit()
    return {"alerts": len(alerts), "evaluated": len(units), "fired": fired}
