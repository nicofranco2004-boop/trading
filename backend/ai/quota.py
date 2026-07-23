"""quota — tiers + límites SEMANALES + helpers de upgrade.
═══════════════════════════════════════════════════════════════════════════
Estrategia de monetización dual (paywall agresivo para sostener Free a escala):

  Free (gratis, "tasting menu"):
    - 6 análisis contextuales por SEMANA (ISO week, lunes-domingo).
    - 0 queries del AI Hub (Hub es feature exclusiva Pro).
    - 0 follow-ups (también exclusivo Pro).
    - Modelo: claude-haiku-4-5.
    - System prompt: SIMPLE / DESCRIPTIVO (resume métricas sin profundizar).

  Pro ($7 USD/mes — sustentable a 3k+ usuarios):
    - 60 análisis por semana (10× más que Free).
    - 60 queries del AI Hub por semana.
    - 1 follow-up por análisis (preguntas libres de profundización).
    - Modelo: claude-haiku-4-5 (mismo motor que Free).
    - System prompt: PREMIUM / RESEARCH NOTE (interpretación, causalidad,
      comparación, insights memorables).
    El diferencial es CANTIDAD (10×) + CALIDAD (causalidad vs descripción)
    + FEATURES (Hub, follow-ups), no costo del modelo.

  Admin (dogfood, no se vende):
    - 1000/semana (cap absurdamente alto para uso interno).
    - System prompt: PREMIUM.

Economía a 3000 Free users (worst case sin cache):
    3000 × 6 análisis/sem × 4.33 sem/mes × $0.007/call ≈ $540/mes
  vs ingresos Pro a 5% conversión:
    150 Pro × ($7 − $2 costo Pro real) = $750/mes
  Net: +$210/mes ✓ (más margen con cache hits y conversión 7%+).

Cap rolling 7-day vs ISO week:
  Usamos ventana móvil de 7 días (hoy y los 6 días anteriores). Esto
  evita el surprise reset de los lunes: si hiciste 3 análisis el domingo,
  el lunes seguís viendo "3/6" en lugar de "0/6". Cada día, el más viejo
  se va "cayendo" del bucket.

Reset:
  No hay un día fijo de reset. resets_on devuelve el día en que el slot
  más antiguo del window "se libera" (= fecha del análisis más viejo + 7).
  Si no hay análisis en el window, resets_on es null.

Tracking:
  Cada call al LLM (cache MISS de Rendi) incrementa ai_usage_daily.analyses_count.
  Los cache HITS de Rendi NO descuentan cupo (gratuito para el user).
"""

from __future__ import annotations
from typing import Literal
from datetime import date, datetime, timedelta

Tier = Literal["free", "plus", "pro", "advisor", "admin"]

# Cap semanal. Cambiar acá afecta UI, mensaje 429, demo mock, tests.
#
# Cálculo costo Free a 3000 users (worst case sin cache):
#   3000 × 6/sem × 4.33 sem × $0.007 ≈ $545/mes.
# Free no tiene acceso a Hub ni follow-ups — el contador hub_queries_per_week=0
# es un gate explícito que el endpoint del Hub leerá para responder 403.
#
# Cálculo costo Pro a $7 USD/mes con 60 análisis/sem + 1 follow-up + 60 hub:
#   60 análisis × 2 (con follow-up) + 60 hub = 180 calls/sem worst case.
#   180 × 4.33 sem × $0.007 ≈ $5.46/mes worst case → margen 22%.
#   En la práctica con cache hits de 24h y uso real (~40% de la cuota):
#   ≈ $1.80-$2.50/mes → margen 65-75%.
LIMITS = {
    "free": {
        "analyses_per_week": 6,
        "hub_queries_per_week": 0,     # Hub es Pro-only — gate en endpoint
        # chat_per_week: cuántas consultas al Coach IA por ventana 7d.
        # Free/Plus tienen acceso SOLO a las 12 preguntas pre-fijadas
        # (whitelist en el endpoint /api/ai/chat). No pueden tipear libre.
        # Free=3 (taster — engancha pero empuja a upgrade), Plus=9 (3× Free).
        "chat_per_week": 3,
        # diag_dismiss_per_week: cuántos "No me interesa" del diagnóstico puede
        # descartar por ventana 7d. Free ve la grilla completa pero puede
        # personalizarla solo 2×/sem → al pasarse, upsell a Plus. None = ∞.
        "diag_dismiss_per_week": 2,
    },
    # Plus diferencial IA: 3× más chat que Free (9 vs 3). Mismos análisis 6
    # (que se cachean 24h → uso efectivo similar). Plus es upgrade de
    # "más broker + algo más de IA descriptiva". Pro sigue siendo el motor
    # IA premium real (chat libre + causalidad + 60 análisis).
    "plus": {
        "analyses_per_week": 6,
        "hub_queries_per_week": 0,
        "chat_per_week": 9,             # 3× Free
        "diag_dismiss_per_week": None,  # ilimitado (el diferencial vs Free)
    },
    "pro": {
        "analyses_per_week": 60,        # 10× Free
        "hub_queries_per_week": 60,
        # Pro desbloquea CHAT LIBRE — pueden tipear cualquier pregunta.
        # Cap 40/sem tras audit #3 (down de 60) — Pro user real usa ~40%
        # de la cuota = 16 chats/sem promedio, 40 deja headroom 2.5×.
        # Worst case proyectado: ~$3.50/Pro/mes (chat + analyses + hub).
        "chat_per_week": 40,
        "diag_dismiss_per_week": None,  # ilimitado
    },
    # Advisor — Plan Asesor Financiero (B2B). Pool PROPIO del asesor: toda la
    # IA que use (en su cuenta o dentro de un cliente vía contexto) descuenta
    # de acá, nunca de la cuota del cliente. Arranca a niveles Pro; cuando
    # exista la IA de libro (cross-cliente) se recalibra.
    "advisor": {
        "analyses_per_week": 60,
        "hub_queries_per_week": 60,
        "chat_per_week": 40,
        "diag_dismiss_per_week": None,  # ilimitado
    },
    "admin": {
        "analyses_per_week": 1000,
        "hub_queries_per_week": 1000,
        "chat_per_week": 1000,
        "diag_dismiss_per_week": None,  # ilimitado
    },
}


def _paid_override_expired(conn, user_id: int, credit_active_until) -> bool:
    """True si un override pago (tier 'pro'/'plus') debe considerarse VENCIDO
    ahora mismo: credit_active_until está seteado y ya pasó, y el user NO tiene
    una suscripción 'authorized' que lo renueve.

    Red de seguridad en TIEMPO REAL (no depende del cron diario): mismo criterio
    que _downgrade_expired_credit, pero por request. Para regalos (comp) esto
    corta el acceso apenas vence — sin esperar a que corra el cron, y aunque el
    cron falle. Fail-open si no hay fecha (no podemos saber si expiró → no
    cortamos) o ante cualquier error (no bloqueamos acceso por un bug acá)."""
    if not credit_active_until:
        return False  # sin vencimiento conocido → no cortamos (fail-open)
    try:
        if str(credit_active_until) >= datetime.utcnow().isoformat():
            return False  # crédito todavía vigente
        # Crédito vencido: solo cortamos si NO hay sub paga que renueve (las
        # pagas se refillan solas; no las cortamos por un lapso entre cobros).
        sub = conn.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND status = 'authorized' LIMIT 1",
            (user_id,),
        ).fetchone()
        return sub is None
    except Exception:
        return False  # ante la duda, no cortar acceso


def get_tier(conn, user_id: int) -> Tier:
    """Resuelve tier del user con override explícito.

    Precedencia:
      1. users.tier (override) — si está seteado a 'pro'/'plus'/'free', devuelve
         eso. PERO si es 'pro'/'plus' y el crédito que lo habilita ya venció (y
         no hay sub que renueve), se trata como expirado → free/admin. Esto es la
         red de seguridad en tiempo real: cubre la ventana entre el vencimiento
         y la corrida del cron diario, y el caso de que el cron falle.
      2. is_admin=1 → 'admin' (default histórico)
      3. fallback → 'free'

    Cuando exista checkout real, la tabla subscriptions setea users.tier='pro'
    y este helper sigue funcionando sin cambios."""
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row:
            keys = row.keys()
            # Plan Asesor: una cuenta ADMINISTRADA (shadow, managed_by seteado)
            # se comporta como Pro para todos los gates — el asesor la opera y
            # su plan lo paga. PERO esto aplica SOLO mientras sea shadow SIN
            # RECLAMAR (approved=0, no puede loguear ella misma): en ese caso
            # el único que la ve es el asesor, vía contexto, con su propio plan.
            #
            # Una vez que el cliente RECLAMA la cuenta (F4a: /api/auth/claim),
            # el endpoint pone approved=1 Y managed_by=NULL (la cuenta pasa a
            # ser independiente de verdad — el vínculo con el asesor sigue
            # vivo en advisor_clients, no acá). Esta rama queda inalcanzable
            # para ella de las dos formas: managed_by ya es NULL, y aunque no
            # lo fuera, approved=1 la saca del check. Cae a la resolución
            # normal de abajo (override pago si existe, si no 'free'). Es la
            # regla de negocio explícita: "el cliente entra a SU cuenta y ve
            # visión Free — el plan del asesor no incluye a los clientes."
            # (El asesor, viendo la MISMA cuenta vía X-Rendi-Client-Id, sigue
            # viendo Pro: /api/plan/features fuerza tier_override='pro' en
            # contexto, sin pasar por acá.)
            approved = bool(row["approved"]) if "approved" in keys else True
            if "managed_by" in keys and row["managed_by"] is not None and not approved:
                return "pro"
            override = ((row["tier"] if "tier" in keys else None) or "").strip().lower()
            is_admin = bool(row["is_admin"]) if "is_admin" in keys else False
            if override in ("pro", "plus", "advisor"):
                # credit_active_until puede no existir en esquemas mínimos (tests
                # viejos): en ese caso no aplicamos la red de seguridad y el tier
                # se resuelve como antes. 'advisor' entra por la misma rama: el
                # grant-comp le pone vencimiento y esta red lo corta igual.
                cau = row["credit_active_until"] if "credit_active_until" in keys else None
                if _paid_override_expired(conn, user_id, cau):
                    return "admin" if is_admin else "free"
                return override  # type: ignore[return-value]
            if override == "free":
                return "free"
            if is_admin:
                return "admin"
    except Exception:
        pass
    return "free"


def _window_start(today: date) -> date:
    """Inicio de la ventana móvil de 7 días: hoy − 6 días.

    Resultado: el sum WHERE date >= window_start captura HOY + 6 días previos
    = 7 días totales. Si Pablo usó IA ayer (domingo) y hoy es lunes, ese análisis
    sigue contando — evita el surprise reset de los lunes."""
    return today - timedelta(days=6)


# Back-compat: callers viejos que importan _week_start siguen funcionando
# (devuelve el mismo valor que _window_start ahora).
_week_start = _window_start


def get_current_usage(conn, user_id: int) -> dict:
    """Counters de los últimos 7 días + límites del tier.

    Devuelve dict con shape estable para el frontend:
      tier, period='rolling_7d',
      analyses_count/limit/remaining,
      hub_queries_count/limit/remaining,
      resets_on (ISO date en que se libera el slot más antiguo, o null si
                 no hay análisis en el window).
      window_starts_on (ISO date — hoy menos 6 días).
    """
    today = date.today()
    window_start = _window_start(today)

    # SQL hace el cálculo de resets_on directamente con date(MIN(date), '+7 days')
    # para evitar dependencias del módulo `date` de Python (más limpio + testeable).
    # COALESCE(SUM(col), 0) convierte el NULL del SUM sobre 0 filas en 0 (NO
    # protege de una columna inexistente — eso falla al preparar el SELECT). Las
    # columnas chat_count/diag_dismiss_count las garantiza init_db (CREATE + ALTER
    # al boot) antes de servir requests.
    row = conn.execute(
        """SELECT COALESCE(SUM(analyses_count), 0) AS a,
                  COALESCE(SUM(hub_queries_count), 0) AS h,
                  COALESCE(SUM(chat_count), 0) AS c,
                  COALESCE(SUM(diag_dismiss_count), 0) AS d,
                  date(MIN(date), '+7 days') AS resets_on
             FROM ai_usage_daily
            WHERE user_id = ? AND date >= ?
              AND (analyses_count > 0 OR hub_queries_count > 0 OR chat_count > 0
                   OR diag_dismiss_count > 0)""",
        (user_id, window_start.isoformat()),
    ).fetchone()
    analyses = int(row["a"] or 0) if row else 0
    hub = int(row["h"] or 0) if row else 0
    chat = int(row["c"] or 0) if row else 0
    diag_dismiss = int(row["d"] or 0) if row else 0
    resets_on = row["resets_on"] if row else None

    tier = get_tier(conn, user_id)
    limits = LIMITS[tier]
    a_limit = limits["analyses_per_week"]
    h_limit = limits["hub_queries_per_week"]
    c_limit = limits.get("chat_per_week", 0)
    # diag_dismiss_per_week puede ser None (ilimitado en plus/pro/admin).
    dd_limit = limits.get("diag_dismiss_per_week")

    return {
        "tier": tier,
        "period": "rolling_7d",
        "analyses_count": analyses,
        "analyses_limit": a_limit,
        "analyses_remaining": max(0, a_limit - analyses),
        "hub_queries_count": hub,
        "hub_queries_limit": h_limit,
        "hub_queries_remaining": max(0, h_limit - hub),
        "chat_count": chat,
        "chat_limit": c_limit,
        "chat_remaining": max(0, c_limit - chat),
        "diag_dismiss_count": diag_dismiss,
        "diag_dismiss_limit": dd_limit,  # None = ilimitado
        "diag_dismiss_remaining": None if dd_limit is None else max(0, dd_limit - diag_dismiss),
        "resets_on": resets_on,
        "window_starts_on": window_start.isoformat(),
        # Alias back-compat para callers viejos.
        "week_starts_on": window_start.isoformat(),
    }


# Legacy alias para callers existentes que esperan `get_today_usage`.
# Devuelve lo mismo que get_current_usage — el shape sigue compatible.
get_today_usage = get_current_usage


def can_analyze(conn, user_id: int) -> tuple[bool, dict]:
    """(allowed, usage_dict). Si False, el endpoint responde 429."""
    usage = get_current_usage(conn, user_id)
    return usage["analyses_remaining"] > 0, usage


def can_hub_query(conn, user_id: int) -> tuple[bool, dict]:
    usage = get_current_usage(conn, user_id)
    return usage["hub_queries_remaining"] > 0, usage


def can_chat(conn, user_id: int) -> tuple[bool, dict]:
    """(allowed, usage_dict) para /api/ai/chat. Si False → 429."""
    usage = get_current_usage(conn, user_id)
    return usage["chat_remaining"] > 0, usage


def record_analysis(conn, user_id: int, cost_usd_cents: int = 0) -> None:
    """Suma 1 al contador del día actual (lo agrupamos por día en BD; el cap
    semanal se computa al leer)."""
    today = date.today().isoformat()
    with conn:
        conn.execute(
            """INSERT INTO ai_usage_daily (user_id, date, analyses_count, cost_usd_cents)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(user_id, date) DO UPDATE SET
                 analyses_count = analyses_count + 1,
                 cost_usd_cents = cost_usd_cents + excluded.cost_usd_cents""",
            (user_id, today, cost_usd_cents),
        )


def record_hub_query(conn, user_id: int, cost_usd_cents: int = 0) -> None:
    today = date.today().isoformat()
    with conn:
        conn.execute(
            """INSERT INTO ai_usage_daily (user_id, date, hub_queries_count, cost_usd_cents)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(user_id, date) DO UPDATE SET
                 hub_queries_count = hub_queries_count + 1,
                 cost_usd_cents = cost_usd_cents + excluded.cost_usd_cents""",
            (user_id, today, cost_usd_cents),
        )


def record_chat(conn, user_id: int, cost_usd_cents: int = 0) -> None:
    """LEGACY (pre B-9): suma 1 al contador chat del día. El flujo actual usa
    reserve_chat (ANTES del LLM) + record_chat_cost (después) + refund_chat en
    fallo. Se conserva para compat de tests/scripts."""
    today = date.today().isoformat()
    with conn:
        conn.execute(
            """INSERT INTO ai_usage_daily (user_id, date, chat_count, cost_usd_cents)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(user_id, date) DO UPDATE SET
                 chat_count = chat_count + 1,
                 cost_usd_cents = cost_usd_cents + excluded.cost_usd_cents""",
            (user_id, today, cost_usd_cents),
        )


def reserve_chat(conn, user_id: int) -> tuple[bool, dict]:
    """Reserva ATÓMICA de 1 slot de chat ANTES del LLM (audit IA #2 B-9).

    El flujo viejo (can_chat → LLM → record_chat) era check-then-act sin lock:
    N requests concurrentes leían el mismo count y TODOS pasaban el gate — un
    Free en 0/3 disparaba N llamadas al LLM. Acá el conteo y el incremento
    ocurren en UN statement: el WHERE re-verifica el cap DENTRO de la
    transacción de escritura de SQLite (serializada) → sin ventana.

    Devuelve (ok, usage). Con ok=True el slot ya está tomado: si el LLM falla,
    el caller debe devolverlo con refund_chat. usage refleja el estado
    POST-reserva (la consulta en curso ya cuenta).
    """
    tier = get_tier(conn, user_id)
    limit = LIMITS[tier]["chat_per_week"]
    today = date.today()
    window_start = _window_start(today).isoformat()
    with conn:
        cur = conn.execute(
            """INSERT INTO ai_usage_daily (user_id, date, chat_count, cost_usd_cents)
               SELECT ?, ?, 1, 0
                WHERE (SELECT COALESCE(SUM(chat_count), 0) FROM ai_usage_daily
                        WHERE user_id = ? AND date >= ?) < ?
               ON CONFLICT(user_id, date) DO UPDATE SET
                 chat_count = chat_count + 1
               WHERE (SELECT COALESCE(SUM(chat_count), 0) FROM ai_usage_daily
                        WHERE user_id = ? AND date >= ?) < ?""",
            (user_id, today.isoformat(), user_id, window_start, limit,
             user_id, window_start, limit),
        )
        ok = cur.rowcount > 0
    return ok, get_current_usage(conn, user_id)


def refund_chat(conn, user_id: int) -> None:
    """Devuelve el slot reservado por reserve_chat cuando el LLM falló — el
    usuario no recibió respuesta, no se le cobra la consulta. Resta de la fila
    MÁS RECIENTE con chat_count > 0 (no de "hoy": una reserva a las 23:59 con
    error a las 00:01 refundaría un día sin fila = slot perdido 7 días).
    Nunca por debajo de 0."""
    with conn:
        conn.execute(
            """UPDATE ai_usage_daily SET chat_count = MAX(0, chat_count - 1)
                WHERE user_id = ?
                  AND date = (SELECT MAX(date) FROM ai_usage_daily
                               WHERE user_id = ? AND chat_count > 0)""",
            (user_id, user_id),
        )


def record_chat_cost(conn, user_id: int, cost_usd_cents: int = 0) -> None:
    """Registra SOLO el costo del chat exitoso (el slot ya lo tomó
    reserve_chat — sumar acá de nuevo sería doble descuento)."""
    if not cost_usd_cents:
        return
    today = date.today().isoformat()
    with conn:
        conn.execute(
            """INSERT INTO ai_usage_daily (user_id, date, cost_usd_cents)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, date) DO UPDATE SET
                 cost_usd_cents = cost_usd_cents + excluded.cost_usd_cents""",
            (user_id, today, cost_usd_cents),
        )


def can_diag_dismiss(conn, user_id: int) -> tuple[bool, dict]:
    """(allowed, usage) para el "No me interesa" del diagnóstico. Ilimitado
    (remaining None) → siempre True."""
    usage = get_current_usage(conn, user_id)
    rem = usage["diag_dismiss_remaining"]
    return (rem is None or rem > 0), usage


def reserve_diag_dismiss(conn, user_id: int) -> tuple[bool, dict]:
    """Reserva ATÓMICA de 1 "No me interesa" del diagnóstico (mismo patrón que
    reserve_chat, sin refund — no hay LLM detrás, la acción es instantánea).

    Tiers con límite None (plus/pro/admin) → siempre permitido, no descuenta.
    Free (cap 2/sem) → conteo + incremento en UN statement (el WHERE re-verifica
    el cap dentro de la transacción serializada de SQLite → sin race).

    Devuelve (ok, usage). ok=False → el endpoint responde 429 con upgrade payload.
    """
    tier = get_tier(conn, user_id)
    limit = LIMITS[tier].get("diag_dismiss_per_week")
    if limit is None:  # ilimitado
        return True, get_current_usage(conn, user_id)
    today = date.today()
    window_start = _window_start(today).isoformat()
    with conn:
        cur = conn.execute(
            """INSERT INTO ai_usage_daily (user_id, date, diag_dismiss_count, cost_usd_cents)
               SELECT ?, ?, 1, 0
                WHERE (SELECT COALESCE(SUM(diag_dismiss_count), 0) FROM ai_usage_daily
                        WHERE user_id = ? AND date >= ?) < ?
               ON CONFLICT(user_id, date) DO UPDATE SET
                 diag_dismiss_count = diag_dismiss_count + 1
               WHERE (SELECT COALESCE(SUM(diag_dismiss_count), 0) FROM ai_usage_daily
                        WHERE user_id = ? AND date >= ?) < ?""",
            (user_id, today.isoformat(), user_id, window_start, limit,
             user_id, window_start, limit),
        )
        ok = cur.rowcount > 0
    return ok, get_current_usage(conn, user_id)
