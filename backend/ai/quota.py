"""quota — tiers + límites SEMANALES + helpers de upgrade.
═══════════════════════════════════════════════════════════════════════════
Estrategia de monetización dual:

  Free:
    - 10 análisis contextuales por SEMANA (ISO week, lunes-domingo).
    - 5 queries del AI Hub por semana.
    - Modelo: claude-haiku-4-5.
    - System prompt: SIMPLE / DESCRIPTIVO (resume métricas sin profundizar).

  Pro:
    - 200 análisis por semana (cap suave de seguridad — efectivo ilimitado).
    - 200 queries del AI Hub.
    - Modelo: claude-haiku-4-5 (mismo motor que Free).
    - System prompt: PREMIUM / RESEARCH NOTE (interpretación, causalidad,
      comparación, insights memorables).
    El diferencial es CANTIDAD + CALIDAD de respuesta, no costo del modelo.

  Admin (dogfood, no se vende):
    - 1000/semana (cap absurdamente alto para uso interno).
    - System prompt: PREMIUM.

Cap semanal vs diario:
  El cap diario (5/día) penaliza al usuario que entra fines de semana o
  bursts de un día. El cap semanal (10/sem ISO) le da flexibilidad para
  usar 4 un día y 1 otro, total 5 — sin frustrar.

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

# Cap semanal. Cambiar acá afecta UI, mensaje 429, demo mock.
LIMITS = {
    "free": {
        "analyses_per_week": 10,
        "hub_queries_per_week": 5,
    },
    "pro": {
        "analyses_per_week": 200,
        "hub_queries_per_week": 200,
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
