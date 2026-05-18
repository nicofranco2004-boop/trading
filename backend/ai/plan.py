"""plan — feature gates + cuotas por tier (Free / Pro / Admin).
═══════════════════════════════════════════════════════════════════════════
Modelo de permisos centralizado. Cada feature paywallable del producto se
declara acá con su gate por tier:

  • Boolean en `can_access` para acceso categórico (Comportamiento full,
    Distribución por activo, Reportes históricos, AI Hub, etc.).
  • Numérico en `limits` para cuotas cuantitativas (brokers_max,
    insights_diagnostic_visible, behavioral_tags_visible).
  • Cuotas semanales de IA viven en `ai.quota.LIMITS` (no se duplican acá).

Modo GRANDFATHER:
  Para usuarios Free preexistentes con N brokers > limit_free, los N
  brokers se preservan (no se borran). Sólo NO pueden agregar más hasta
  upgrade. Esto evita romper la experiencia de cuentas anteriores al
  paywall. La función check_broker_quota() implementa esa lógica.

Convención de feature IDs:
  namespace.action (lowercase + dot). Ej: "comportamiento.full",
  "insights.distribucion_activo", "ai.followup".
"""

from __future__ import annotations
from typing import Optional
from ai import quota

Tier = quota.Tier  # 'free' | 'pro' | 'admin'

# Feature IDs canónicos. Si agregás una nueva feature paywallable, suma acá
# y agregá la entrada en PLAN_LIMITS de los 3 tiers. Tests validan que esté.
FEATURE_IDS = {
    "ai.followup",                  # Follow-ups en análisis IA
    "ai.hub",                       # AI Hub (próximamente para todos)
    "comportamiento.full",          # Todas las tags de comportamiento (vs 1 sample en Free)
    "insights.distribucion_activo", # Card "Distribución por activo" en Insights
    "reportes.historicos",          # Meses históricos en Reportes (Free ve teaser último)
}

# Límites + accesos por tier.
#   `None` en un límite numérico = sin tope.
#   `False` en can_access = bloqueado.
PLAN_LIMITS = {
    "free": {
        "brokers_max": 1,
        "insights_diagnostic_visible": 3,
        "behavioral_tags_visible": 1,
        "can_access": {
            "ai.followup": False,
            "ai.hub": False,                       # próximamente
            "comportamiento.full": False,
            "insights.distribucion_activo": False,
            "reportes.historicos": False,
        },
    },
    "pro": {
        "brokers_max": None,
        "insights_diagnostic_visible": None,
        "behavioral_tags_visible": None,
        "can_access": {
            "ai.followup": True,
            "ai.hub": False,                       # próximamente (todavía no liberado)
            "comportamiento.full": True,
            "insights.distribucion_activo": True,
            "reportes.historicos": True,
        },
    },
    "admin": {
        "brokers_max": None,
        "insights_diagnostic_visible": None,
        "behavioral_tags_visible": None,
        "can_access": {
            "ai.followup": True,
            "ai.hub": True,                        # admin ve todo, incluso flags en desarrollo
            "comportamiento.full": True,
            "insights.distribucion_activo": True,
            "reportes.historicos": True,
        },
    },
}


def can_access(conn, user_id: int, feature_id: str) -> bool:
    """¿El user tiene acceso a esta feature por flag boolean?

    Para gates cuantitativos (brokers_max, etc.) usar check_broker_quota()
    u otras funciones específicas. Devuelve False si el feature_id no está
    declarado (defensivo — feature nueva sin declarar = no accesible)."""
    if feature_id not in FEATURE_IDS:
        # Feature no declarada. Por defecto NEGAMOS acceso (fail-safe).
        return False
    tier = quota.get_tier(conn, user_id)
    limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["free"])
    return bool(limits["can_access"].get(feature_id, False))


def check_broker_quota(conn, user_id: int) -> tuple[bool, dict]:
    """¿Puede el user crear un broker nuevo? Grandfather-aware.

    Si tier=free y current_count >= brokers_max=1, devuelve False.
    Si tier=free y current_count > brokers_max (grandfather), también
    devuelve False — los brokers existentes se mantienen pero no puede
    crear más.

    Para tiers sin límite (Pro/Admin), siempre True.

    Devuelve (allowed, info) donde info incluye tier, current_count, limit,
    can_create — útil para el 403 payload."""
    tier = quota.get_tier(conn, user_id)
    limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["free"])
    limit = limits["brokers_max"]

    row = conn.execute(
        "SELECT COUNT(*) AS c FROM brokers WHERE user_id = ?", (user_id,)
    ).fetchone()
    current = int(row["c"] or 0) if row else 0

    if limit is None:
        return True, {
            "tier": tier,
            "current_count": current,
            "limit": None,
            "can_create": True,
            "grandfather": False,
        }

    can_create = current < limit
    return can_create, {
        "tier": tier,
        "current_count": current,
        "limit": limit,
        "can_create": can_create,
        # Grandfather: ya tiene MÁS que el límite — preexistente al paywall
        "grandfather": current > limit,
    }


def get_plan_features(conn, user_id: int) -> dict:
    """Resuelve TODOS los flags + límites del tier del user para el frontend.

    Shape estable consumido por hooks/usePlanFeatures() en el frontend:
        tier
        limits.brokers_max / brokers_current / brokers_can_create
        limits.insights_diagnostic_visible
        limits.behavioral_tags_visible
        access.<feature_id>: bool
    """
    tier = quota.get_tier(conn, user_id)
    limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["free"])

    broker_row = conn.execute(
        "SELECT COUNT(*) AS c FROM brokers WHERE user_id = ?", (user_id,)
    ).fetchone()
    current_brokers = int(broker_row["c"] or 0) if broker_row else 0

    brokers_max = limits["brokers_max"]
    brokers_can_create = brokers_max is None or current_brokers < brokers_max

    return {
        "tier": tier,
        "limits": {
            "brokers_max": brokers_max,
            "brokers_current": current_brokers,
            "brokers_can_create": brokers_can_create,
            "brokers_grandfather": brokers_max is not None and current_brokers > brokers_max,
            "insights_diagnostic_visible": limits["insights_diagnostic_visible"],
            "behavioral_tags_visible": limits["behavioral_tags_visible"],
        },
        "access": dict(limits["can_access"]),
    }
