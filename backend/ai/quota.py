"""quota — Free vs Pro vs Admin tier + límites diarios.
═══════════════════════════════════════════════════════════════════════════
Cuotas por tier (configurables — empezamos generosos para no frustrar
mientras no haya paywall real):

  Free:
    - 5 análisis "contextuales" por día (analyze cualquier screen)
    - 3 queries del AI Hub por día
    - Modelo: claude-haiku-4-5

  Pro:
    - Ilimitado (cap soft 100/día por seguridad)
    - Modelo: claude-sonnet-4-6 para análisis "profundos" (insights,
      wrapped, behavioral). Resto sigue en Haiku.

  Admin (interno, no se vende):
    - Cap muy alto (1000/día) para dogfood + debugging sin tener que
      esperar al reset diario. Solo el user con is_admin=1.

Hoy NO hay tabla de subscriptions todavía — todos los users non-admin
son Free. Cuando agreguemos pricing, este módulo lee el plan del user
y devuelve el tier real.

Tracking:
  Cada call (HIT o MISS) incrementa ai_usage_daily.analyses_count.
  El frontend lee /api/ai/usage para mostrar "3/5 análisis hoy" en Free.
"""

from __future__ import annotations
from typing import Literal
from datetime import date

Tier = Literal["free", "pro", "admin"]

# Límites por tier
LIMITS = {
    "free": {
        "analyses_per_day": 5,
        "hub_queries_per_day": 3,
    },
    "pro": {
        "analyses_per_day": 100,
        "hub_queries_per_day": 100,
    },
    "admin": {
        "analyses_per_day": 1000,
        "hub_queries_per_day": 1000,
    },
}


def get_tier(conn, user_id: int) -> Tier:
    """Tier del user. Admin (is_admin=1) tiene cupo casi ilimitado; el resto
    queda en 'free' hasta que exista paywall.

    TODO: cuando exista subscriptions table, leer plan real de ahí para
    distinguir free vs pro pago."""
    try:
        row = conn.execute(
            "SELECT is_admin FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row and row["is_admin"]:
            return "admin"
    except Exception:
        # Tabla / columna no existe (entornos legacy) — no rompemos, fallback Free
        pass
    return "free"


def get_today_usage(conn, user_id: int) -> dict:
    """Devuelve dict con counts del día + límites del tier."""
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT analyses_count, hub_queries_count FROM ai_usage_daily "
        "WHERE user_id = ? AND date = ?",
        (user_id, today),
    ).fetchone()
    analyses = row["analyses_count"] if row else 0
    hub = row["hub_queries_count"] if row else 0
    tier = get_tier(conn, user_id)
    limits = LIMITS[tier]
    return {
        "tier": tier,
        "analyses_count": analyses,
        "analyses_limit": limits["analyses_per_day"],
        "hub_queries_count": hub,
        "hub_queries_limit": limits["hub_queries_per_day"],
        "analyses_remaining": max(0, limits["analyses_per_day"] - analyses),
        "hub_queries_remaining": max(0, limits["hub_queries_per_day"] - hub),
    }


def can_analyze(conn, user_id: int) -> tuple[bool, dict]:
    """Devuelve (allowed, usage_dict). Si False, el endpoint responde 429."""
    usage = get_today_usage(conn, user_id)
    return usage["analyses_remaining"] > 0, usage


def can_hub_query(conn, user_id: int) -> tuple[bool, dict]:
    """Igual que can_analyze pero para el AI Hub."""
    usage = get_today_usage(conn, user_id)
    return usage["hub_queries_remaining"] > 0, usage


def record_analysis(conn, user_id: int, cost_usd_cents: int = 0) -> None:
    """Suma 1 al contador del día + acumula costo."""
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
