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
    "export.csv",                   # Export CSV de operaciones / posiciones / monthly
    "tax.helper",                   # Tax helper AFIP (próximamente, todavía no construido)
    "alerts.pct_move",              # Alertas de % sobre la cartera ("cae/sube X%") — Plus+
}

# Límites + accesos por tier.
#   `None` en un límite numérico = sin tope.
#   `False` en can_access = bloqueado.
PLAN_LIMITS = {
    "free": {
        "brokers_max": 1,
        "insights_diagnostic_visible": 3,
        "behavioral_tags_visible": 3,
        "alerts_max": 3,                           # solo precio objetivo (pct_move = Plus+)
        "can_access": {
            "ai.followup": False,
            "ai.hub": False,                       # próximamente
            "comportamiento.full": False,          # parcial (behavioral_tags_visible=3 de 12)
            "insights.distribucion_activo": False,
            "reportes.historicos": False,
            "export.csv": False,
            "tax.helper": False,                   # próximamente (no construido)
            "alerts.pct_move": False,              # el desbloqueo de funcionalidad = Plus
        },
    },
    # Plus — tier intermedio. Captura users que necesitan multi-broker,
    # reportes históricos, distribución por activo, pero no necesitan IA
    # avanzada. La IA queda igual que Free (Hub y follow-ups son Pro-only)
    # para preservar el upgrade path por features de IA.
    "plus": {
        "brokers_max": 3,
        "insights_diagnostic_visible": 6,
        "behavioral_tags_visible": 6,
        "alerts_max": 25,                          # desbloquea alertas de % sobre la cartera
        "can_access": {
            "ai.followup": False,                  # Pro-only
            "ai.hub": False,                       # Pro-only
            "comportamiento.full": False,          # parcial (behavioral_tags_visible=6 de 12)
            "insights.distribucion_activo": True,
            "reportes.historicos": True,
            "export.csv": True,
            "tax.helper": False,                   # Pro-only (cuando exista)
            "alerts.pct_move": True,               # ★ el desbloqueo Free→Plus
        },
    },
    "pro": {
        "brokers_max": None,
        "insights_diagnostic_visible": None,
        "behavioral_tags_visible": None,
        "alerts_max": None,                        # sin tope (Pro no tiene límites de cantidad)
        "can_access": {
            "ai.followup": True,
            "ai.hub": False,                       # próximamente (todavía no liberado)
            "comportamiento.full": True,
            "insights.distribucion_activo": True,
            "reportes.historicos": True,
            "export.csv": True,
            "tax.helper": False,                   # próximamente (todavía no construido)
            "alerts.pct_move": True,
        },
    },
    "admin": {
        "brokers_max": None,
        "insights_diagnostic_visible": None,
        "behavioral_tags_visible": None,
        "alerts_max": None,
        "can_access": {
            "ai.followup": True,
            "ai.hub": True,                        # admin ve todo, incluso flags en desarrollo
            "comportamiento.full": True,
            "insights.distribucion_activo": True,
            "reportes.historicos": True,
            "export.csv": True,
            "tax.helper": True,                    # admin ve todo, incluso si Pro no lo tiene aún
            "alerts.pct_move": True,
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


def _count_alerts(conn, user_id: int) -> int:
    """COUNT de alertas del user. Si la tabla `alerts` no existe todavía
    (DB parcial de un test, o schema viejo pre-migración) → 0 (fail-open)."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM alerts WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(row["c"] or 0) if row else 0
    except Exception:
        return 0


def check_alert_quota(conn, user_id: int) -> tuple[bool, dict]:
    """¿Puede el user crear una alerta nueva? Mismo patrón que check_broker_quota.

    Free = 3 alertas (solo precio objetivo). Plus = 25 (+ alertas de %).
    Pro/Admin = sin tope. Grandfather-aware (si ya tiene más que el tope por
    un downgrade, no puede crear más pero conserva las existentes)."""
    tier = quota.get_tier(conn, user_id)
    limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["free"])
    limit = limits.get("alerts_max")

    current = _count_alerts(conn, user_id)

    if limit is None:
        return True, {"tier": tier, "current_count": current, "limit": None,
                      "can_create": True, "grandfather": False}
    can_create = current < limit
    return can_create, {
        "tier": tier, "current_count": current, "limit": limit,
        "can_create": can_create, "grandfather": current > limit,
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

    alerts_max = limits.get("alerts_max")
    current_alerts = _count_alerts(conn, user_id)
    alerts_can_create = alerts_max is None or current_alerts < alerts_max

    return {
        "tier": tier,
        "limits": {
            "brokers_max": brokers_max,
            "brokers_current": current_brokers,
            "brokers_can_create": brokers_can_create,
            "brokers_grandfather": brokers_max is not None and current_brokers > brokers_max,
            "insights_diagnostic_visible": limits["insights_diagnostic_visible"],
            "behavioral_tags_visible": limits["behavioral_tags_visible"],
            "alerts_max": alerts_max,
            "alerts_current": current_alerts,
            "alerts_can_create": alerts_can_create,
        },
        "access": dict(limits["can_access"]),
    }
