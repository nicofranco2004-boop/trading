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
from datetime import date, timedelta

Tier = Literal["free", "pro", "admin"]

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
    },
    "pro": {
        "analyses_per_week": 60,        # 10× Free
        "hub_queries_per_week": 60,
    },
    "admin": {
        "analyses_per_week": 1000,
        "hub_queries_per_week": 1000,
    },
}


def get_tier(conn, user_id: int) -> Tier:
    """Resuelve tier del user con override explícito.

    Precedencia:
      1. users.tier (override) — si está seteado a 'pro' o 'free', devuelve eso.
         Permite que un admin se ponga en 'pro' para ver la UX de paywall y
         conserve sus is_admin powers (Admin page sigue accesible).
      2. is_admin=1 → 'admin' (default histórico)
      3. fallback → 'free'

    Cuando exista checkout real, la tabla subscriptions setea users.tier='pro'
    y este helper sigue funcionando sin cambios."""
    try:
        row = conn.execute(
            "SELECT is_admin, tier FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row:
            override = (row["tier"] or "").strip().lower()
            if override in ("pro", "free"):
                return override  # type: ignore[return-value]
            if row["is_admin"]:
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
    row = conn.execute(
        """SELECT COALESCE(SUM(analyses_count), 0) AS a,
                  COALESCE(SUM(hub_queries_count), 0) AS h,
                  date(MIN(date), '+7 days') AS resets_on
             FROM ai_usage_daily
            WHERE user_id = ? AND date >= ?
              AND (analyses_count > 0 OR hub_queries_count > 0)""",
        (user_id, window_start.isoformat()),
    ).fetchone()
    analyses = int(row["a"] or 0) if row else 0
    hub = int(row["h"] or 0) if row else 0
    resets_on = row["resets_on"] if row else None

    tier = get_tier(conn, user_id)
    limits = LIMITS[tier]
    a_limit = limits["analyses_per_week"]
    h_limit = limits["hub_queries_per_week"]

    return {
        "tier": tier,
        "period": "rolling_7d",
        "analyses_count": analyses,
        "analyses_limit": a_limit,
        "analyses_remaining": max(0, a_limit - analyses),
        "hub_queries_count": hub,
        "hub_queries_limit": h_limit,
        "hub_queries_remaining": max(0, h_limit - hub),
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
