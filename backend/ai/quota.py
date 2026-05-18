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

Cap semanal vs diario:
  El cap diario penaliza al usuario que entra fines de semana o bursts.
  El cap semanal le da flexibilidad para usar 3 un día y 1 otro — sin
  frustrar.

Reset:
  ISO week — empieza lunes a las 00:00 timezone local. La columna
  `date` de ai_usage_daily está en formato ISO date (server-local), y
  sumamos los días dentro de la semana en curso.

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
    """Resuelve tier del user. Hoy: admin si is_admin=1, sino free.

    Cuando exista paywall + tabla subscriptions, leer plan pago de ahí
    y devolver 'pro' para suscriptos activos."""
    try:
        row = conn.execute(
            "SELECT is_admin FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row and row["is_admin"]:
            return "admin"
    except Exception:
        pass
    return "free"


def _week_start(today: date) -> date:
    """Lunes de la semana ISO en curso. weekday() devuelve 0=lunes, 6=domingo."""
    return today - timedelta(days=today.weekday())


def get_current_usage(conn, user_id: int) -> dict:
    """Counters de la semana en curso + límites del tier + fecha de reset.

    Devuelve dict con shape estable para el frontend:
      tier, period='week', analyses_count/limit/remaining,
      hub_queries_count/limit/remaining, resets_on (ISO date del próximo lunes).
    """
    today = date.today()
    week_start = _week_start(today)
    next_reset = week_start + timedelta(days=7)

    row = conn.execute(
        """SELECT COALESCE(SUM(analyses_count), 0) AS a,
                  COALESCE(SUM(hub_queries_count), 0) AS h
             FROM ai_usage_daily
            WHERE user_id = ? AND date >= ?""",
        (user_id, week_start.isoformat()),
    ).fetchone()
    analyses = int(row["a"] or 0) if row else 0
    hub = int(row["h"] or 0) if row else 0

    tier = get_tier(conn, user_id)
    limits = LIMITS[tier]
    a_limit = limits["analyses_per_week"]
    h_limit = limits["hub_queries_per_week"]

    return {
        "tier": tier,
        "period": "week",
        "analyses_count": analyses,
        "analyses_limit": a_limit,
        "analyses_remaining": max(0, a_limit - analyses),
        "hub_queries_count": hub,
        "hub_queries_limit": h_limit,
        "hub_queries_remaining": max(0, h_limit - hub),
        "resets_on": next_reset.isoformat(),
        "week_starts_on": week_start.isoformat(),
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
