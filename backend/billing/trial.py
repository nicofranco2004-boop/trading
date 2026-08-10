"""Free trial de 15 días — 7 de Pro y 8 de Plus, encadenados.

Por qué encadenado y no "elegí un plan": pedirle a alguien que elija entre Pro
y Plus lo obliga a entender la tabla de precios ANTES de usar el producto, y el
que elige Plus nunca ve Pro (así que nunca lo desea). Encadenado, la pérdida es
gradual y hay DOS momentos de venta: el día 8 pierde Pro y el día 16 pierde Plus
—y ahí Plus se siente barato, porque ya sabe lo que es tenerlo.

    día 1-7   → pro    (el techo: chat libre, 60 análisis/semana)
    día 8-15  → plus   (pierde lo premium, sigue cómodo)
    día 16 →    free   (1 análisis/semana)

Se apoya ENTERO en el modelo de crédito que ya existía para "Regalar Pro":

  · Al activar: users.tier='pro' + credit_active_until = arranque + 15 días
    (TODO el trial de una) + trial_started_at + trial_used_at.
  · Día 8: el cron diario cambia tier a 'plus'. NO toca credit_active_until.
  · Día 16: vence el crédito y get_tier() devuelve 'free' solo — el mismo
    mecanismo que ya corta los regalos, en tiempo real y sin depender del cron.

El vencimiento se graba a 15 días DESDE EL ARRANQUE a propósito: si el cron
fallara, el usuario se queda en Pro de más en vez de quedarse sin acceso. El
error cae siempre a favor del usuario, nunca en cortarle el servicio.

Los 7 días de Pro tampoco son arbitrarios: la cuota de Pro se mide en ventanas
de 7 días, así que el trial consume EXACTAMENTE UNA ventana. El costo queda
acotado por diseño (~USD 1,50 en el peor caso absoluto), no por confianza.
"""

from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger("billing.trial")

# ─── Parámetros (cambiarlos NO requiere tocar nada más) ─────────────────────
TRIAL_PRO_DAYS = 7          # días en Pro
TRIAL_PLUS_DAYS = 8         # días en Plus, después de Pro
TRIAL_TOTAL_DAYS = TRIAL_PRO_DAYS + TRIAL_PLUS_DAYS


def trials_enabled() -> bool:
    """Interruptor para apagar el trial sin deployar (variable de entorno).
    Default: ENCENDIDO. Con 'false'/'0'/'off' deja de ofrecerse y de activarse
    — los trials YA activos siguen su curso normal (no se le corta a nadie
    lo que ya se le dio)."""
    v = (os.environ.get("TRIALS_ENABLED", "true") or "").strip().lower()
    return v not in ("false", "0", "off", "no")


def monthly_cap() -> int:
    """Tope de activaciones por mes calendario. Al llegar, el botón deja de
    ofrecerse y el usuario ve el paywall normal. Así el gasto máximo mensual
    lo fija el negocio y no la demanda. 0 = sin tope."""
    try:
        return max(0, int(os.environ.get("TRIALS_MONTHLY_CAP", "0") or 0))
    except (TypeError, ValueError):
        return 0


def _activations_this_month(conn) -> int:
    """Cuántos trials se activaron en el mes calendario en curso (UTC)."""
    month_start = datetime.utcnow().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    # Se cuenta sobre el LEDGER, no sobre users: borrar la cuenta no puede
    # devolver un cupo (audit). El ledger es append-only.
    try:
        row = conn.execute(
            "SELECT COUNT(*) c FROM credit_ledger WHERE kind='trial' AND created_at >= ?",
            (month_start,),
        ).fetchone()
        return int(row["c"] if hasattr(row, "keys") else row[0]) if row else 0
    except Exception as ex:
        # Fail-CLOSED: si no podemos contar, no activamos. El tope existe para
        # acotar el gasto — que se caiga solo justo bajo carga sería lo peor.
        log.warning("no pudimos contar los trials del mes: %s", ex)
        return 10 ** 9


def _email_of(conn, user_id: int):
    try:
        r = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        return r["email"] if r else None
    except Exception:
        return None


def _email_key(email) -> str:
    """Clave estable del email para recordar quién ya usó su trial. Se guarda
    HASHEADA: sirve para comparar, no para reconstruir la casilla."""
    import hashlib
    return hashlib.sha256((email or "").strip().lower().encode()).hexdigest()


def _email_consumed(conn, email) -> bool:
    """¿Este email ya consumió su trial alguna vez? La marca vive en su propia
    tabla porque borrar la cuenta borra la fila de users — y con ella
    trial_used_at, lo que habilitaba trials infinitos con el mismo mail
    (audit)."""
    if not email:
        return False
    try:
        return conn.execute(
            "SELECT 1 FROM trial_consumed WHERE email_key=? LIMIT 1",
            (_email_key(email),),
        ).fetchone() is not None
    except Exception:
        return False   # la tabla puede no existir en esquemas viejos


def _mark_email_consumed(conn, email) -> None:
    if not email:
        return
    try:
        conn.execute(
            "INSERT OR IGNORE INTO trial_consumed (email_key, consumed_at) VALUES (?, ?)",
            (_email_key(email), datetime.utcnow().isoformat()),
        )
    except Exception as ex:
        log.warning("no pudimos marcar el email como consumido: %s", ex)


def _has_paid_sub(conn, user_id: int) -> bool:
    """Si la consulta falla asumimos QUE SÍ paga (fail-closed): dar por error un
    trial a un suscriptor le pisaría el plan y le quemaría su único trial. Es
    preferible no activarlo y que lo reintente (audit)."""
    try:
        return conn.execute(
            "SELECT 1 FROM subscriptions WHERE user_id=? AND status='authorized' LIMIT 1",
            (user_id,),
        ).fetchone() is not None
    except Exception as ex:
        log.warning("no pudimos verificar la suscripción uid=%s: %s", user_id, ex)
        return True


def eligibility(conn, user_id: int) -> dict:
    """¿Puede activar el trial? Devuelve {can_start, reason, ...} — el mismo
    dict lo usa el endpoint para decidir y el frontend para saber si mostrar
    el botón. `reason` es un código estable; el texto lo pone la UI."""
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return {"can_start": False, "reason": "unknown_user"}
    keys = row.keys()

    def g(k, default=None):
        return row[k] if k in keys else default

    if g("trial_used_at") or _email_consumed(conn, g("email")):
        return {"can_start": False, "reason": "already_used"}
    # Un admin tiene límites MÁS altos que Pro: activarlo lo degradaría 15 días
    # (get_tier prioriza el override pago sobre is_admin) y le quemaría su
    # único trial (audit).
    if bool(g("is_admin")):
        return {"can_start": False, "reason": "not_applicable"}
    # El plan Asesor es B2B y se otorga aparte; una cuenta administrada por un
    # asesor ya ve Pro por su cuenta.
    tier = (g("tier") or "").strip().lower()
    if tier == "advisor" or g("managed_by") is not None:
        return {"can_start": False, "reason": "not_applicable"}
    if _has_paid_sub(conn, user_id):
        return {"can_start": False, "reason": "already_paying"}
    # Ya tiene un plan pago vigente (regalo, crédito) → el trial no aporta nada
    # y encima le acortaría el vencimiento.
    cau = g("credit_active_until")
    if cau and str(cau) > datetime.utcnow().isoformat():
        return {"can_start": False, "reason": "already_premium"}
    # Corta el abuso trivial de crear cuentas descartables. No frena a un
    # decidido con dos casillas de correo, y no queremos más fricción que esa.
    if "email_verified" in keys and not bool(g("email_verified")):
        return {"can_start": False, "reason": "email_not_verified"}
    if not trials_enabled():
        return {"can_start": False, "reason": "disabled"}
    cap = monthly_cap()
    if cap and _activations_this_month(conn) >= cap:
        return {"can_start": False, "reason": "monthly_cap_reached"}
    return {"can_start": True, "reason": None}


def start(conn, user_id: int) -> dict:
    """Activa el trial. Idempotente por `trial_used_at`: un segundo intento
    devuelve can_start=False/already_used sin tocar nada.

    Escribe en credit_ledger igual que un regalo (kind='trial'), así el "por
    qué" de un tier siempre se puede reconstruir desde el ledger."""
    elig = eligibility(conn, user_id)
    if not elig["can_start"]:
        return {"ok": False, **elig}

    now = datetime.utcnow()
    until = (now + timedelta(days=TRIAL_TOTAL_DAYS)).isoformat()
    now_iso = now.isoformat()
    with conn:
        # trial_ends_at fija CUÁL crédito es el del trial. Sin esto, "usó el
        # trial alguna vez" quedaba pegado para siempre y el cron le bajaba el
        # Pro a cualquiera que después recibiera un regalo o pagara y cancelara
        # (audit: reproducido con usuarios pagos).
        #
        # Los anchors se limpian EXPLÍCITAMENTE: son los que le ponen precio a
        # un crédito. Si quedaba pegado el anchor de una suscripción vieja,
        # get_credit_state valuaba los 15 días gratis como plata real y
        # "cambiar de plan" los convertía en 41 días de Plus (audit: plata
        # fabricada, reproducido).
        cur = conn.execute(
            """UPDATE users
                  SET tier='pro', credit_active_until=?,
                      trial_started_at=?, trial_used_at=?, trial_ends_at=?,
                      credit_anchor_plan=NULL, credit_anchor_period=NULL,
                      credit_anchor_amount_usd=NULL, credit_anchor_at=NULL
                WHERE id=? AND trial_used_at IS NULL
                  AND (credit_active_until IS NULL OR credit_active_until <= ?)""",
            (until, now_iso, now_iso, until, user_id, now_iso),
        )
        if cur.rowcount == 0:
            return {"ok": False, "can_start": False, "reason": "already_used"}
        _mark_email_consumed(conn, _email_of(conn, user_id))
        try:
            conn.execute(
                """INSERT INTO credit_ledger
                       (user_id, kind, amount_usd, days_delta,
                        from_plan, from_period, to_plan, to_period,
                        active_until_before, active_until_after, note)
                   VALUES (?, 'trial', 0, ?, NULL, NULL, 'pro', NULL, NULL, ?, ?)""",
                (user_id, TRIAL_TOTAL_DAYS, until,
                 f"Free trial: {TRIAL_PRO_DAYS}d Pro + {TRIAL_PLUS_DAYS}d Plus"),
            )
        except Exception as ex:   # el ledger es auditoría, no puede voltear el alta
            log.warning("trial ledger insert falló uid=%s: %s", user_id, ex)
    log.info("trial started uid=%s until=%s", user_id, until)
    return {"ok": True, **status(conn, user_id)}


def status(conn, user_id: int) -> dict:
    """Estado del trial para la UI. Se calcula EN CADA REQUEST desde las
    fechas — no depende del cron, así que el contador de días que ve el
    usuario siempre es correcto aunque el cron falle."""
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return {"active": False, "used": False, "can_start": False}
    keys = row.keys()
    started = (row["trial_started_at"] if "trial_started_at" in keys else None)
    used = bool(row["trial_used_at"] if "trial_used_at" in keys else None)
    cau = (row["credit_active_until"] if "credit_active_until" in keys else None)
    out = {"active": False, "used": used, "can_start": False,
           "stage": None, "days_left": None, "days_to_switch": None,
           "ends_at": cau if started else None,
           "pro_days": TRIAL_PRO_DAYS, "plus_days": TRIAL_PLUS_DAYS,
           "total_days": TRIAL_TOTAL_DAYS}
    if not started:
        e = eligibility(conn, user_id)
        out["can_start"] = e["can_start"]
        out["reason"] = e["reason"]
        return out
    now = datetime.utcnow()
    try:
        started_dt = datetime.fromisoformat(str(started).replace("Z", ""))
        until_dt = datetime.fromisoformat(str(cau).replace("Z", "")) if cau else None
    except (TypeError, ValueError):
        return out
    if until_dt and now < until_dt and not _has_paid_sub(conn, user_id):
        out["active"] = True
        # La etapa es el tier EFECTIVO, no el que dice el calendario: si el cron
        # todavía no corrió, el usuario sigue teniendo Pro de verdad y la UI no
        # puede anunciarle que ya está en Plus (audit).
        try:
            from ai import quota as _q
            real = _q.get_tier(conn, user_id)
            out["stage"] = real if real in ("pro", "plus") else None
        except Exception:
            elapsed = (now - started_dt).days
            out["stage"] = "pro" if elapsed < TRIAL_PRO_DAYS else "plus"
        # Días completos que faltan para que se termine TODO el trial.
        out["days_left"] = max(0, (until_dt - now).days + (1 if (until_dt - now).seconds else 0))
        # Días que faltan para el cambio de Pro a Plus (None si ya pasó).
        if out["stage"] == "pro":
            switch_at = started_dt + timedelta(days=TRIAL_PRO_DAYS)
            d = switch_at - now
            out["days_to_switch"] = max(0, d.days + (1 if d.seconds else 0))
    return out


def step_down_due_trials(conn) -> int:
    """Paso del cron diario: los trials que ya pasaron su semana de Pro bajan
    a Plus. NO toca credit_active_until (el trial sigue venciendo cuando tenía
    que vencer) ni a quien ya se suscribió — al que pagó no se le saca nada.

    Idempotente: solo matchea tier='pro', así que correrlo dos veces no hace
    nada la segunda. Devuelve cuántos bajó."""
    cutoff = (datetime.utcnow() - timedelta(days=TRIAL_PRO_DAYS)).isoformat()
    try:
        rows = conn.execute(
            """SELECT id, email, trial_started_at FROM users
                WHERE tier='pro'
                  AND trial_started_at IS NOT NULL
                  AND trial_started_at <= ?
                  AND credit_active_until > ?
                  -- CLAVE: solo si el crédito vigente ES el del trial. Sin esto
                  -- bajaba a Plus a cualquiera que hubiera hecho el trial y
                  -- después tuviera Pro por otra vía (regalo, pago cancelado en
                  -- su período de gracia, cambio de plan) — audit, reproducido.
                  AND trial_ends_at IS NOT NULL
                  AND credit_active_until = trial_ends_at
                  AND NOT EXISTS (SELECT 1 FROM subscriptions s
                                   WHERE s.user_id = users.id AND s.status='authorized')""",
            (cutoff, datetime.utcnow().isoformat()),
        ).fetchall()
    except Exception as ex:
        log.error("step_down_due_trials query falló: %s", ex)
        return 0
    if not rows:
        return 0
    n = 0
    with conn:
        for r in rows:
            conn.execute("UPDATE users SET tier='plus' WHERE id=? AND tier='pro'", (r["id"],))
            try:
                conn.execute(
                    """INSERT INTO credit_ledger
                           (user_id, kind, amount_usd, days_delta,
                            from_plan, from_period, to_plan, to_period,
                            active_until_before, active_until_after, note)
                       VALUES (?, 'trial_step', 0, 0, 'pro', NULL, 'plus', NULL, NULL, NULL, ?)""",
                    (r["id"], f"Trial: terminó la semana de Pro, sigue {TRIAL_PLUS_DAYS} días en Plus"),
                )
            except Exception:
                pass
            n += 1
    log.info("trial step-down pro→plus: %d usuarios", n)
    return n
