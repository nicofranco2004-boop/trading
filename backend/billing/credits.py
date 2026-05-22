"""credits — modelo de crédito basado en tiempo (Rendi-managed proration)
═══════════════════════════════════════════════════════════════════════════
Cuando un user cambia de plan o cancela mid-período, NO le cobramos de
nuevo ni le devolvemos plata. Convertimos el tiempo no consumido en una
"ventana de crédito" tracked en `users`:

  credit_active_until: timestamp hasta el que el user mantiene tier ≠ free
  credit_anchor_*:     plan/period/amount que originó el último anchor

Operaciones principales:
  • grant_payment_credit:  Rebill cobró → extender la ventana N días al
                           daily_rate del plan cobrado.
  • convert_plan:          User cambió plan → remaining_credit_usd al
                           daily_rate del plan nuevo (más días si el nuevo
                           es más barato, menos si es más caro).
  • compute_remaining:     Cuánto crédito queda en USD al daily_rate vigente.
  • expire:                credit_active_until vencido → bajar tier a free
                           + email re-suscribirse.

Cada operación escribe una fila en `credit_ledger` para auditoría.
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

log = logging.getLogger("billing.credits")


# ─── Pricing source of truth ────────────────────────────────────────────────
# Mantener sincronizado con Planes.jsx y los plan IDs de Rebill.
# Si cambian los precios, también hay que ajustar daily_rate aquí.

PLAN_PRICES_USD = {
    ('plus', 'monthly'):  4.0,
    ('plus', 'annual'):  40.0,
    ('pro',  'monthly'):  9.0,
    ('pro',  'annual'):  90.0,
}

PERIOD_DAYS = {
    'monthly': 30.0,
    'annual':  365.0,
}


def daily_rate(plan: str, period: str) -> float:
    """USD/día para un plan+período. Anual es más barato por día que mensual
    (que es el incentivo natural del descuento por compromiso largo)."""
    price = PLAN_PRICES_USD.get((plan, period))
    days = PERIOD_DAYS.get(period)
    if price is None or days is None:
        raise ValueError(f"Plan/period inválido: {plan}/{period}")
    return price / days


def plan_period_days(plan: str, period: str) -> float:
    """Total días que cubre un período del plan (30 o 365)."""
    days = PERIOD_DAYS.get(period)
    if days is None:
        raise ValueError(f"Período inválido: {period}")
    return days


# ─── Estado del crédito de un user ──────────────────────────────────────────

def get_credit_state(conn, user_id: int) -> dict:
    """Snapshot del crédito del user. Útil para /auth/me, /config, cron.

    Devuelve:
      active_until:        ISO ts o None
      is_active:           True si active_until > NOW
      days_remaining:      float (puede ser 0 o negativo si vencido)
      remaining_usd:       valor monetario restante al daily_rate del anchor
      anchor_plan:         'plus' | 'pro' | None
      anchor_period:       'monthly' | 'annual' | None
      anchor_amount_usd:   USD del último anchor (pago o conversión)
      anchor_at:           ISO ts del último anchor
    """
    row = conn.execute(
        """SELECT credit_active_until, credit_anchor_plan, credit_anchor_period,
                  credit_anchor_amount_usd, credit_anchor_at, tier
           FROM users WHERE id = ?""",
        (user_id,),
    ).fetchone()
    if not row:
        return _empty_state()

    active_until_str = row["credit_active_until"]
    if not active_until_str:
        return _empty_state(anchor_plan=row["credit_anchor_plan"],
                            anchor_period=row["credit_anchor_period"])

    try:
        active_until = _parse_iso(active_until_str)
    except Exception:
        log.warning("credit_active_until inválido para user %s: %r", user_id, active_until_str)
        return _empty_state()

    now = datetime.utcnow()
    days_remaining = (active_until - now).total_seconds() / 86400.0
    is_active = days_remaining > 0

    anchor_plan = row["credit_anchor_plan"]
    anchor_period = row["credit_anchor_period"]
    remaining_usd = 0.0
    if is_active and anchor_plan and anchor_period:
        try:
            remaining_usd = max(0.0, days_remaining * daily_rate(anchor_plan, anchor_period))
        except Exception:
            remaining_usd = 0.0

    return {
        "active_until":      active_until_str,
        "is_active":         bool(is_active),
        "days_remaining":    round(days_remaining, 3) if days_remaining > 0 else 0.0,
        "remaining_usd":     round(remaining_usd, 2),
        "anchor_plan":       anchor_plan,
        "anchor_period":     anchor_period,
        "anchor_amount_usd": row["credit_anchor_amount_usd"],
        "anchor_at":         row["credit_anchor_at"],
    }


def _empty_state(anchor_plan=None, anchor_period=None) -> dict:
    return {
        "active_until":      None,
        "is_active":         False,
        "days_remaining":    0.0,
        "remaining_usd":     0.0,
        "anchor_plan":       anchor_plan,
        "anchor_period":     anchor_period,
        "anchor_amount_usd": None,
        "anchor_at":         None,
    }


# ─── Grant: Rebill cobró un período ─────────────────────────────────────────

def grant_payment_credit(
    conn,
    user_id: int,
    plan: str,
    period: str,
    amount_usd: Optional[float] = None,
    subscription_id: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Extiende la ventana de crédito del user porque Rebill cobró un período.

    Comportamiento:
      • Si el user ya tiene credit_active_until > NOW (ej. anchored a otro plan):
        - El crédito remanente al plan VIEJO se preserva (no se pisa)
        - Se EXTIENDE active_until por los días del nuevo período al rate nuevo
        - El anchor pasa a ser el plan/period nuevos
      • Si el user no tenía credit_active_until o ya venció:
        - active_until = NOW + period_days
        - anchor = plan/period del cobro

    `amount_usd`: si no se provee, usa el precio del catálogo (PLAN_PRICES_USD).
                  Útil cuando Rebill no nos manda el monto en el webhook payload.
    """
    if amount_usd is None:
        amount_usd = PLAN_PRICES_USD.get((plan, period))
        if amount_usd is None:
            raise ValueError(f"Plan/period inválido: {plan}/{period}")

    period_days = plan_period_days(plan, period)
    now = datetime.utcnow()

    state = get_credit_state(conn, user_id)
    before_iso = state["active_until"]

    if state["is_active"] and state["anchor_plan"] and state["anchor_period"]:
        # Hay crédito vigente — convertir remaining al rate nuevo y SUMAR período comprado.
        remaining_usd_at_old_rate = state["remaining_usd"]
        new_rate = daily_rate(plan, period)
        remaining_days_at_new_rate = remaining_usd_at_old_rate / new_rate if new_rate > 0 else 0
        total_days = remaining_days_at_new_rate + period_days
        new_active_until = now + timedelta(days=total_days)
    else:
        # Sin crédito previo — empieza ventana desde NOW.
        new_active_until = now + timedelta(days=period_days)

    after_iso = new_active_until.isoformat()
    days_delta = (new_active_until - now).total_seconds() / 86400.0 - state["days_remaining"]

    with conn:
        conn.execute(
            """UPDATE users
               SET credit_active_until = ?,
                   credit_anchor_plan = ?,
                   credit_anchor_period = ?,
                   credit_anchor_amount_usd = ?,
                   credit_anchor_at = ?
               WHERE id = ?""",
            (after_iso, plan, period, amount_usd, now.isoformat(), user_id),
        )
        conn.execute(
            """INSERT INTO credit_ledger
                  (user_id, kind, amount_usd, days_delta,
                   from_plan, from_period, to_plan, to_period,
                   active_until_before, active_until_after,
                   source_subscription_id, note)
               VALUES (?, 'payment', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, amount_usd, days_delta,
                state["anchor_plan"], state["anchor_period"], plan, period,
                before_iso, after_iso,
                subscription_id, note or f"Rebill payment ({plan} {period})",
            ),
        )

    log.info(
        "credits.grant_payment user=%s plan=%s period=%s amount=%.2f days_delta=%.2f "
        "active_until=%s",
        user_id, plan, period, amount_usd, days_delta, after_iso,
    )
    return {
        "active_until":   after_iso,
        "days_remaining": round((new_active_until - now).total_seconds() / 86400.0, 3),
        "anchor_plan":    plan,
        "anchor_period":  period,
    }


# ─── Convert: user cambió de plan (upgrade/downgrade mid-credit) ────────────

def convert_plan(
    conn,
    user_id: int,
    new_plan: str,
    new_period: str,
    cancelled_subscription_id: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Cambia el plan del user manteniendo el crédito remanente.

    Calcula remaining_usd al rate viejo, lo divide por el rate nuevo para
    obtener los nuevos días, y reajusta credit_active_until.

    Ejemplo:
      Plus annual, 9 meses restantes → remaining = 9/12 × $40 = $30
      Cambia a Pro mensual ($9/30 = $0.30/día)
      Nuevos días = $30 / $0.30 = 100 días de Pro
      → credit_active_until = NOW + 100 días

    Si el user no tenía crédito previo: error. Esto solo se llama desde
    /api/billing/change-plan, que valida que haya crédito.
    """
    state = get_credit_state(conn, user_id)
    if not state["is_active"]:
        raise ValueError("El user no tiene crédito activo para convertir.")
    if not state["anchor_plan"] or not state["anchor_period"]:
        raise ValueError("Crédito sin anchor (estado inconsistente).")

    if state["anchor_plan"] == new_plan and state["anchor_period"] == new_period:
        # Cambio a mismo plan/period — no-op para el crédito.
        return {
            "active_until":   state["active_until"],
            "days_remaining": state["days_remaining"],
            "anchor_plan":    new_plan,
            "anchor_period":  new_period,
            "converted":      False,
        }

    now = datetime.utcnow()
    before_iso = state["active_until"]
    remaining_usd = state["remaining_usd"]
    new_rate = daily_rate(new_plan, new_period)
    new_days = remaining_usd / new_rate if new_rate > 0 else 0.0
    new_active_until = now + timedelta(days=new_days)
    after_iso = new_active_until.isoformat()
    days_delta = new_days - state["days_remaining"]

    with conn:
        conn.execute(
            """UPDATE users
               SET tier = ?,
                   credit_active_until = ?,
                   credit_anchor_plan = ?,
                   credit_anchor_period = ?,
                   credit_anchor_at = ?
               WHERE id = ?""",
            (new_plan, after_iso, new_plan, new_period, now.isoformat(), user_id),
        )
        conn.execute(
            """INSERT INTO credit_ledger
                  (user_id, kind, amount_usd, days_delta,
                   from_plan, from_period, to_plan, to_period,
                   active_until_before, active_until_after,
                   source_subscription_id, note)
               VALUES (?, 'plan_change', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, remaining_usd, days_delta,
                state["anchor_plan"], state["anchor_period"], new_plan, new_period,
                before_iso, after_iso,
                cancelled_subscription_id,
                note or f"Plan change {state['anchor_plan']}/{state['anchor_period']} → {new_plan}/{new_period}",
            ),
        )

    log.info(
        "credits.convert_plan user=%s %s/%s → %s/%s remaining_usd=%.2f new_days=%.2f",
        user_id, state["anchor_plan"], state["anchor_period"],
        new_plan, new_period, remaining_usd, new_days,
    )
    return {
        "active_until":   after_iso,
        "days_remaining": round(new_days, 3),
        "anchor_plan":    new_plan,
        "anchor_period":  new_period,
        "converted":      True,
        "remaining_usd":  round(remaining_usd, 2),
    }


# ─── Preview: estimación de un cambio de plan sin ejecutarlo ────────────────

def preview_plan_change(conn, user_id: int, new_plan: str, new_period: str) -> dict:
    """Devuelve lo que pasaría si el user cambia a (new_plan, new_period) sin
    ejecutarlo. Útil para el frontend antes de confirmar.

    Si no hay crédito activo, devuelve `eligible=False` con motivo."""
    state = get_credit_state(conn, user_id)
    if not state["is_active"]:
        return {
            "eligible": False,
            "reason": "no_active_credit",
            "current_state": state,
        }
    if state["anchor_plan"] == new_plan and state["anchor_period"] == new_period:
        return {
            "eligible": False,
            "reason": "same_plan",
            "current_state": state,
        }
    remaining_usd = state["remaining_usd"]
    new_rate = daily_rate(new_plan, new_period)
    new_days = remaining_usd / new_rate if new_rate > 0 else 0.0
    return {
        "eligible":            True,
        "from_plan":           state["anchor_plan"],
        "from_period":         state["anchor_period"],
        "to_plan":             new_plan,
        "to_period":           new_period,
        "remaining_usd":       round(remaining_usd, 2),
        "current_days":        state["days_remaining"],
        "new_days":            round(new_days, 3),
        "current_state":       state,
    }


# ─── Helpers ────────────────────────────────────────────────────────────────

def _parse_iso(s: str) -> datetime:
    """Parsea ISO con o sin sufijo Z / microsegundos."""
    if not s:
        raise ValueError("ISO string vacío")
    s = s.replace("Z", "").split("+")[0]
    # Probar varias variantes
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)
