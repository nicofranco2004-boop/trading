"""subscriptions — lógica del ciclo de vida de subscripciones.
═══════════════════════════════════════════════════════════════════════════
Job que corre diariamente y se encarga de:

  1. **Downgrade post-cancelación**:
     Cuando un user cancela su sub, la dejamos en status='cancelled' pero
     mantenemos tier='pro' hasta `current_period_end`. Este job chequea
     cancelladas con period_end ya pasado y los baja a tier='free'.

  2. **Cleanup de pendientes abandonadas**:
     Subs que quedaron en 'pending' por > 7 días (user abrió checkout y
     nunca pagó) se marcan como 'cancelled' para liberar el slot — si
     el user vuelve a clickear "Suscribirme", crea una nueva limpia.

  3. **Sync de salud**:
     Para cada sub 'authorized', verificamos con MP que sigue activa.
     Si MP dice 'cancelled' o 'paused' y nosotros tenemos 'authorized',
     hay desync — actualizamos nuestra DB. Esto cubre webhooks perdidos.

  Diseño: cada operación es idempotente. Si el cron falla a mitad de camino
  y retry, no rompe nada. Logs detallados para auditar comportamiento.
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta

log = logging.getLogger("billing.subscriptions")


def run_lifecycle_job(conn) -> dict:
    """Corre el job completo del ciclo de vida. Devuelve dict con counts
    de cada operación para que el caller pueda loguear / monitorear."""
    result = {
        "downgraded": 0,
        "stale_pending_cancelled": 0,
        "synced_from_mp": 0,
        "expiration_reminders_sent": 0,
        "errors": 0,
    }
    try:
        result["downgraded"] = _downgrade_expired_cancellations(conn)
    except Exception as ex:
        log.error("downgrade step failed: %s", ex)
        result["errors"] += 1
    try:
        result["stale_pending_cancelled"] = _cancel_stale_pending(conn)
    except Exception as ex:
        log.error("stale pending cleanup failed: %s", ex)
        result["errors"] += 1
    try:
        result["synced_from_mp"] = _sync_authorized_with_mp(conn)
    except Exception as ex:
        log.error("MP sync step failed: %s", ex)
        result["errors"] += 1
    try:
        result["expiration_reminders_sent"] = _send_expiration_reminders(conn)
    except Exception as ex:
        log.error("Expiration reminders failed: %s", ex)
        result["errors"] += 1
    return result


def _send_expiration_reminders(conn, days_before: int = 3) -> int:
    """Manda recordatorio a users cuya sub cancelada está por expirar en N días.

    Solo afecta a subs `cancelled` (no a `authorized` activas — esas se renuevan
    automáticamente). Idempotente vía expiration_reminder_sent_at."""
    from billing import emails
    rows = conn.execute(
        """SELECT s.id, s.mp_subscription_id, s.current_period_end,
                  u.email, u.name
           FROM subscriptions s
           JOIN users u ON u.id = s.user_id
           WHERE s.status = 'cancelled'
             AND s.expiration_reminder_sent_at IS NULL
             AND s.current_period_end IS NOT NULL
             AND date(s.current_period_end) BETWEEN date('now')
                                                AND date('now', ?)""",
        (f"+{days_before} days",),
    ).fetchall()
    if not rows:
        return 0

    sent_count = 0
    for r in rows:
        try:
            from datetime import datetime
            try:
                period_end = datetime.fromisoformat(
                    r["current_period_end"].replace("Z", "").split(".")[0]
                )
                days_left = max(0, (period_end - datetime.utcnow()).days)
            except Exception:
                days_left = days_before

            emails.send_expiration_reminder(
                to=r["email"],
                user_name=(r["name"] or r["email"].split("@")[0]),
                days_left=days_left,
                expires_at=r["current_period_end"],
            )
            with conn:
                conn.execute(
                    """UPDATE subscriptions SET expiration_reminder_sent_at = datetime('now')
                       WHERE id = ?""",
                    (r["id"],),
                )
            sent_count += 1
        except Exception as ex:
            log.error("Expiration reminder failed for sub %s: %s",
                     r["mp_subscription_id"], ex)
    return sent_count


def _downgrade_expired_cancellations(conn) -> int:
    """Encuentra subs canceladas cuyo `current_period_end` ya pasó y baja
    al user a tier='free'. Devuelve count de users degradados."""
    now = datetime.utcnow().isoformat()
    rows = conn.execute(
        """SELECT s.id, s.user_id, s.mp_subscription_id, s.current_period_end
           FROM subscriptions s
           WHERE s.status = 'cancelled'
             AND s.current_period_end IS NOT NULL
             AND s.current_period_end < ?
             AND s.user_id IN (SELECT id FROM users WHERE tier = 'pro')""",
        (now,),
    ).fetchall()
    if not rows:
        return 0

    count = 0
    with conn:
        for r in rows:
            # Limpiar el tier override → vuelve a la lógica is_admin
            # (admin sigue siendo admin; el resto vuelve a 'free' default)
            conn.execute(
                "UPDATE users SET tier = NULL WHERE id = ?",
                (r["user_id"],),
            )
            conn.execute(
                """UPDATE subscriptions SET status = 'expired',
                   updated_at = datetime('now') WHERE id = ?""",
                (r["id"],),
            )
            count += 1
            log.info(
                "User %s downgraded (sub %s expired at %s)",
                r["user_id"], r["mp_subscription_id"], r["current_period_end"],
            )
    return count


def _cancel_stale_pending(conn, stale_days: int = 7) -> int:
    """Subs en 'pending' por más de `stale_days` se cancelan automáticamente.
    Esto libera el slot para que el user pueda crear una sub nueva sin que
    el endpoint /billing/subscribe le devuelva el init_point viejo (que
    probablemente ya expiró en MP)."""
    cutoff = (datetime.utcnow() - timedelta(days=stale_days)).isoformat()
    rows = conn.execute(
        """SELECT id, user_id, mp_subscription_id, created_at
           FROM subscriptions
           WHERE status = 'pending'
             AND created_at < ?""",
        (cutoff,),
    ).fetchall()
    if not rows:
        return 0
    with conn:
        for r in rows:
            conn.execute(
                """UPDATE subscriptions SET status = 'cancelled',
                   cancelled_at = datetime('now'),
                   updated_at = datetime('now') WHERE id = ?""",
                (r["id"],),
            )
            log.info("Stale pending sub %s cancelled (user %s, created %s)",
                    r["mp_subscription_id"], r["user_id"], r["created_at"])
    return len(rows)


def _sync_authorized_with_mp(conn) -> int:
    """Para cada sub 'authorized' en nuestra DB, consulta a MP por su estado
    actual. Si MP dice algo distinto (cancelled, paused, etc.), actualizamos
    nuestra fila. Esto recupera webhooks que se hayan perdido.

    NOTA: hace 1 request a MP por sub authorized. A escala podemos throttlear
    o batchear, pero a <100 subs activas no es problema."""
    from billing import mercadopago
    rows = conn.execute(
        """SELECT id, mp_subscription_id, status
           FROM subscriptions WHERE status = 'authorized'
             AND mp_subscription_id IS NOT NULL"""
    ).fetchall()
    if not rows:
        return 0

    updated = 0
    for r in rows:
        try:
            mp_state = mercadopago.get_preapproval(r["mp_subscription_id"])
        except Exception as ex:
            log.warning("MP get_preapproval failed for %s: %s",
                       r["mp_subscription_id"], ex)
            continue
        mp_status = (mp_state.get("status") or "").lower()
        status_map = {
            "authorized": "authorized",
            "paused": "paused",
            "cancelled": "cancelled",
            "finished": "cancelled",
        }
        new_status = status_map.get(mp_status, "authorized")
        if new_status != r["status"]:
            with conn:
                conn.execute(
                    """UPDATE subscriptions SET status = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (new_status, r["id"]),
                )
            log.info("Sub %s synced from MP: %s → %s",
                    r["mp_subscription_id"], r["status"], new_status)
            updated += 1
    return updated
