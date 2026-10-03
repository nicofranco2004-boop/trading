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
from typing import Optional

log = logging.getLogger("billing.subscriptions")


def _dias_que_quedan(fin) -> int:
    """Los días que faltan, con LA cuenta de la prueba (`trial.dias_restantes`:
    redondea para arriba, como la app) — una sola para todos los mails. El
    redondeo para abajo llegaba a decir "vence en 0 días" con horas por
    delante (con los reintentos, o al cancelar el día antes de renovar)."""
    from billing.trial import dias_restantes
    return dias_restantes(fin)


def _dia(valor) -> Optional[str]:
    """'YYYY-MM-DD' de una fecha de la base (con 'T' o con espacio), o None."""
    if not valor:
        return None
    dia = str(valor).replace("T", " ")[:10]
    return dia if len(dia) == 10 else None


def _avisar_vencimiento(conn, tanda, r, fin, days_before: int, que: str) -> bool:
    """UN aviso de vencimiento por persona y por vencimiento REAL. Devuelve si
    salió. `r`: la fila del usuario (user_id, email, name, tier y, si la hay,
    credit_anchor_plan); `fin`: cuándo se le termina de verdad el acceso.

    La marca es `users.aviso_vencimiento_de` = el día que se le avisó. Antes
    eran dos caminos (fin de crédito y suscripción cancelada), cada uno con su
    marca en una fila de `subscriptions` y su propia fecha: a quien pagó
    durante la prueba le avisaban la de Rebill (el cobro del mes siguiente)
    aunque su acceso durara hasta 19 días más; le podían llegar dos avisos; a
    quien recibió un regalo (sin fila de suscripción) no le llegaba ninguno; y
    a quien ya lo había recibido alguna vez, nunca más. Ahora: se avisa el día
    en que se termina el acceso, una vez; si la fecha cambia (renovó, le
    regalaron días) y vuelve a vencer, se avisa la fecha nueva."""
    from billing import emails
    from billing import trial as _trial
    from billing import plan_textos as _plan_textos
    dia = _dia(fin)
    if not dia:
        return False
    uid = r["user_id"]
    # Si hace poco le llegó "Cancelación confirmada", ese mail ya le dijo hasta
    # cuándo tiene acceso: no se le manda otro la misma mañana. (Sin marcar:
    # si el vencimiento queda más lejos, el aviso sale cuando corresponda.)
    corte = (datetime.utcnow() - timedelta(days=AVISO_TRAS_CANCELACION_DIAS)
             ).strftime("%Y-%m-%d %H:%M:%S")
    if conn.execute("""SELECT 1 FROM subscriptions WHERE user_id = ?
                         AND cancellation_email_sent_at >= ? LIMIT 1""",
                    (uid, corte)).fetchone():
        return False
    try:
        fin_dt = datetime.fromisoformat(str(fin).replace("Z", "").split(".")[0])
        days_left = _dias_que_quedan(fin_dt)
    except Exception:
        days_left = days_before
    keys = r.keys()
    # El plan que vence es el del ancla del crédito; si falta, el que tiene
    # puesto. Caía a "pro" y a un Plus sin ancla le avisaba que vencía su Pro.
    plan = (r["credit_anchor_plan"] if "credit_anchor_plan" in keys else None) or r["tier"]
    datos = dict(
        to=r["email"],
        user_name=(r["name"] or r["email"].split("@")[0]),
        days_left=days_left,
        expires_at=fin,
        plan=plan,
        # Nació sin plan gratis → no "pierde" features: queda en pausa.
        requiere_plan=_trial._requiere_plan(conn, uid),
        # Los cupos de ESTA persona, no los del plan: ver cupos_del_usuario.
        cupos=_plan_textos.cupos_del_usuario(conn, uid, plan),
    )

    # Marca ANTES de mandar, condicional (dos corridas a la vez no la ganan las
    # dos), y si el mail no sale vuelve la que había (ver `emails.Tanda`).
    def marcar():
        with conn:
            previa = conn.execute("SELECT aviso_vencimiento_de FROM users WHERE id = ?",
                                  (uid,)).fetchone()
            cur = conn.execute(
                """UPDATE users SET aviso_vencimiento_de = ?
                   WHERE id = ? AND (aviso_vencimiento_de IS NULL
                                     OR aviso_vencimiento_de <> ?)""",
                (dia, uid, dia))
        if cur.rowcount <= 0:
            return None
        return (dia, previa["aviso_vencimiento_de"] if previa else None)

    def desmarcar(m):
        nueva, previa = m
        with conn:
            conn.execute("""UPDATE users SET aviso_vencimiento_de = ?
                            WHERE id = ? AND aviso_vencimiento_de = ?""",
                         (previa, uid, nueva))

    res = tanda.enviar(marcar, lambda: emails.send_expiration_reminder(**datos), desmarcar,
                       que=que)
    if res == emails.ENVIADO:
        log.info("aviso de vencimiento enviado uid=%s (vence %s, days_left=%s)",
                 uid, dia, days_left)
        return True
    return False


# Días después de cancelar durante los cuales el ciclo de vida reintenta el
# mail "Cancelación confirmada" si Resend lo rechazó (`_send_pending_cancellation_emails`).
CANCELACION_REINTENTO_DIAS = 2
# Días después del mail de cancelación durante los cuales NO sale el aviso
# "vence en N días": el de cancelación ya le dijo hasta cuándo tiene acceso, y
# llegaban los dos la misma mañana.
AVISO_TRAS_CANCELACION_DIAS = 3


def enviar_mail_de_cancelacion(conn, mp_subscription_id: str, tanda=None) -> bool:
    """El mail "Cancelación confirmada", UNA vez por suscripción. Lo mandan el
    botón de cancelar (`main._maybe_send_cancellation_email`) y, si Resend lo
    rechazó, el ciclo de vida (`_send_pending_cancellation_emails`). Devuelve
    si salió.

    Antes se anotaba DESPUÉS y sin mirar si había salido —un rechazo quedaba
    como enviado y el mail no llegaba nunca—; un doble click mandaba dos (los
    dos pedidos llegaban al mail antes de que el primero anotara); y decía
    siempre "Rendi Pro" (a quien cancelaba Plus) con la fecha del próximo cobro
    de Rebill en lugar de la del fin real del acceso (`credit_active_until`)."""
    from billing import emails
    from billing import trial as _trial
    tanda = tanda or emails.Tanda()
    row = conn.execute(
        """SELECT s.current_period_end, u.id AS uid, u.email, u.name, u.tier,
                  u.credit_anchor_plan, u.credit_active_until
             FROM subscriptions s JOIN users u ON u.id = s.user_id
            WHERE s.mp_subscription_id = ?""", (mp_subscription_id,)).fetchone()
    if not row or not row["email"]:
        return False
    # Hasta cuándo tiene acceso DE VERDAD: el crédito; la fecha de la
    # suscripción sólo en el modelo viejo (sin crédito).
    hasta = row["credit_active_until"] or row["current_period_end"]
    if not hasta:
        from fechas import hoy_art
        hasta = hoy_art()
    datos = dict(
        to=row["email"],
        user_name=(row["name"] or row["email"].split("@")[0]),
        valid_until=hasta,
        plan=row["credit_anchor_plan"] or row["tier"] or "pro",
        # Quien nació sin plan gratis no "vuelve a Free": queda en pausa.
        requiere_plan=_trial._requiere_plan(conn, row["uid"]),
    )

    def marcar():
        marca = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with conn:
            cur = conn.execute(
                """UPDATE subscriptions SET cancellation_email_sent_at = ?
                   WHERE mp_subscription_id = ? AND cancellation_email_sent_at IS NULL""",
                (marca, mp_subscription_id))
        return marca if cur.rowcount > 0 else None

    def desmarcar(marca):
        with conn:
            conn.execute(
                """UPDATE subscriptions SET cancellation_email_sent_at = NULL
                   WHERE mp_subscription_id = ? AND cancellation_email_sent_at = ?""",
                (mp_subscription_id, marca))

    res = tanda.enviar(marcar, lambda: emails.send_cancellation(**datos), desmarcar,
                       que=f"mail de cancelación sub={mp_subscription_id}")
    return res == emails.ENVIADO


def _send_pending_cancellation_emails(conn, tanda=None) -> int:
    """El reintento del mail "Cancelación confirmada" que Resend rechazó: bajas
    que la PERSONA pidió con el botón (`cancelacion_pedida_at`) en los últimos
    CANCELACION_REINTENTO_DIAS, sin el mail anotado, de quien todavía tiene
    acceso y no se volvió a suscribir.

    Sólo las del botón: 'cancelled' también lo ponen Rebill por falta de pago
    ("defaulted") y la limpieza de un alta que nunca se pagó
    (`_cancel_stale_pending`, a quien puede estar en la prueba con crédito), y
    a ninguno de los dos se le puede decir "cancelaste, no te cobramos más".
    Una baja hecha desde el portal de Rebill tampoco entra: no hay forma de
    distinguirla de la de falta de pago."""
    from billing import emails
    tanda = tanda or emails.Tanda()
    ahora = datetime.utcnow()
    desde = (ahora - timedelta(days=CANCELACION_REINTENTO_DIAS)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT s.mp_subscription_id FROM subscriptions s JOIN users u ON u.id = s.user_id
            WHERE s.status = 'cancelled' AND s.cancellation_email_sent_at IS NULL
              AND s.mp_subscription_id IS NOT NULL AND s.mp_subscription_id <> ''
              AND s.cancelacion_pedida_at IS NOT NULL
              AND replace(s.cancelacion_pedida_at, 'T', ' ') >= ?
              AND (u.credit_active_until > ?
                   OR (u.credit_active_until IS NULL AND s.current_period_end > ?))
              AND NOT EXISTS (SELECT 1 FROM subscriptions s2
                               WHERE s2.user_id = s.user_id AND s2.status = 'authorized')""",
        (desde, ahora.isoformat(), ahora.isoformat())).fetchall()
    sent = 0
    for r in rows:
        if tanda.frenado:      # Resend no confirma: lo que falta, la próxima vuelta
            break
        try:
            if enviar_mail_de_cancelacion(conn, r["mp_subscription_id"], tanda):
                sent += 1
        except Exception as ex:
            log.error("reintento del mail de cancelación sub=%s falló: %s",
                      r["mp_subscription_id"], ex)
    return sent


def _migrar_aviso_vencimiento(conn) -> int:
    """Una vez, al crear `users.aviso_vencimiento_de`: a quien recibió un aviso
    de vencimiento en los últimos 15 días (la marca vieja, en `subscriptions`)
    se le anota el día que ya se le avisó, para que el código nuevo no se lo
    repita. Si el aviso viejo salió por la suscripción cancelada, el día
    anotado es el de esa suscripción (la fecha de Rebill): si su acceso dura
    más, el aviso con la fecha real va a salir cuando corresponda."""
    corte = (datetime.utcnow() - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT u.id, u.credit_active_until,
                  (SELECT s.current_period_end FROM subscriptions s
                    WHERE s.user_id = u.id AND s.status = 'cancelled'
                      AND s.current_period_end IS NOT NULL
                      AND s.expiration_reminder_sent_at >= ?
                    ORDER BY s.expiration_reminder_sent_at DESC LIMIT 1) AS fin_sub
             FROM users u
            WHERE u.aviso_vencimiento_de IS NULL
              AND EXISTS (SELECT 1 FROM subscriptions s
                           WHERE s.user_id = u.id
                             AND s.expiration_reminder_sent_at >= ?)""",
        (corte, corte)).fetchall()
    n = 0
    with conn:
        for r in rows:
            dia = _dia(r["fin_sub"] or r["credit_active_until"])
            if dia:
                n += conn.execute(
                    """UPDATE users SET aviso_vencimiento_de = ?
                       WHERE id = ? AND aviso_vencimiento_de IS NULL""",
                    (dia, r["id"])).rowcount or 0
    if n:
        log.info("migración: %d avisos de vencimiento recientes pasados a users", n)
    return n


def run_lifecycle_job(conn, solo_avisos: bool = False) -> dict:
    """Corre el job completo del ciclo de vida. Devuelve dict con counts
    de cada operación para que el caller pueda loguear / monitorear.

    `solo_avisos=True` es la vuelta de la tarde (`_start_scheduler`): corre
    SÓLO los pasos que mandan avisos, para que uno que Resend rechazó a la
    madrugada tenga reintento el mismo día ("mañana termina tu Pro" vale un
    solo día). Las bajas de plan quedan para la de la madrugada: la cuota de IA
    se cuenta por día entero (`ai.quota._window_floor`) y una baja al mediodía
    le cobraba al plan nuevo lo usado esa mañana con el viejo — una semana sin
    cuota —; y el resumen de pruebas terminadas le llegaba al admin dos veces."""
    from billing import emails
    from billing import trial as _trial
    # UNA tanda para todos los avisos de la corrida: si Resend se cae a mitad de
    # los de la prueba, los de vencimiento no siguen quemando gente.
    tanda = emails.Tanda()
    result = {
        "credit_expired_downgraded": 0,
        "downgraded": 0,
        "stale_pending_cancelled": 0,
        "synced_from_mp": 0,
        "expiration_reminders_sent": 0,
        "credit_expiring_reminders_sent": 0,
        "trials_stepped_down": 0,
        "trial_emails_sent": 0,
        "cancellation_emails_sent": 0,
        "unverified_accounts_deleted": 0,
        "avisos_frenados": False,
        "solo_avisos": solo_avisos,
        "errors": 0,
    }
    # (clave del resultado, paso, ¿manda avisos?) — EN ESTE ORDEN:
    pasos = (
        # Source of truth = users.credit_active_until (modelo de crédito
        # tiempo-based). El downgrade post-cancelación (más abajo) queda como
        # fallback para subs viejas que nunca pasaron por el nuevo modelo.
        ("credit_expired_downgraded", lambda: _downgrade_expired_credit(conn), False),
        # Trials que ya cumplieron su etapa de Pro → pasan a Plus. Va ANTES de
        # los avisos para que el mail del día salga con el plan correcto.
        ("trials_stepped_down", lambda: _trial.step_down_due_trials(conn), False),
        ("trial_emails_sent", lambda: _trial.send_due_trial_emails(conn, tanda), True),
        # Antes que los de vencimiento: si sale "Cancelación confirmada", el
        # "vence en N días" de esa persona no sale pegado.
        ("cancellation_emails_sent", lambda: _send_pending_cancellation_emails(conn, tanda), True),
        ("credit_expiring_reminders_sent",
         lambda: _send_credit_expiring_reminders(conn, tanda=tanda), True),
        ("downgraded", lambda: _downgrade_expired_cancellations(conn), False),
        ("stale_pending_cancelled", lambda: _cancel_stale_pending(conn), False),
        ("expiration_reminders_sent", lambda: _send_expiration_reminders(conn, tanda=tanda), True),
        ("unverified_accounts_deleted", lambda: _delete_unverified_accounts(conn), False),
    )
    for clave, paso, es_aviso in pasos:
        if solo_avisos and not es_aviso:
            continue
        try:
            result[clave] = paso()
        except Exception as ex:
            log.error("ciclo de vida: el paso %s falló: %s", clave, ex)
            result["errors"] += 1
    # Resend no confirmó los envíos y la tanda se frenó: lo que faltaba queda
    # sin marca para la próxima vuelta (dentro de la ventana de cada aviso).
    # Que se vea en el resultado del job.
    result["avisos_frenados"] = tanda.frenado
    if tanda.frenado:
        log.error("ciclo de vida: Resend no confirma los envíos; se frenaron los avisos "
                  "y lo que faltaba queda para la próxima vuelta (dentro de su ventana)")
    return result


def _notify_admin_downgrades(downgraded, source: str) -> None:
    """Best-effort: avisa al admin de cada baja a Free (plus/pro → free).

    Se llama DESPUÉS de commitear el `with conn:` para no bloquear la
    transacción con la llamada de red (Resend). Nunca levanta. `downgraded` es
    una lista de tuplas (email, tier_anterior). La pausa entre un mail y el
    siguiente la pone `emails._send`."""
    if not downgraded:
        return
    try:
        from billing import emails
    except Exception:
        return
    for email, before_tier in downgraded:
        try:
            emails.send_plan_change_admin(
                user_email=email,
                old_plan=before_tier,
                new_plan=None,  # → 'Free'
                source=source,
            )
        except Exception as ex:
            log.warning("plan-change admin notify (downgrade) falló para %s: %s", email, ex)


def _marcar_corte_de_cuota(conn, user_ids) -> None:
    """Marca que desde hoy corre la cuota del plan nuevo, DESPUÉS de commitear
    la baja y por separado.

    Va aparte del UPDATE que baja el tier a propósito: esa consulta es la que
    hace cumplir el vencimiento del acceso pago y no puede fallar por una
    columna que solo decide cómo se cuenta la cuota. Metida en el mismo
    statement, un esquema sin quota_window_from tiraba el job entero y NADIE
    bajaba a Free — cambiar de plan no puede volverse la forma de no perderlo.

    Sin la marca, el consumo que hizo con el techo del plan que se le venció se
    le descuenta del techo nuevo y queda pasado de cuota sin haber usado nada
    (la ventana de cuota es móvil de 7 días)."""
    if not user_ids:
        return
    try:
        from ai import quota
        for uid in user_ids:
            quota.note_tier_change(conn, uid)
    except Exception as ex:
        log.warning("no pudimos marcar el corte de cuota de %d bajas: %s", len(user_ids), ex)


def _notify_admin_trials_ended(emails_list) -> None:
    """Best-effort: UN mail al admin con todas las pruebas gratis que se
    terminaron en esta corrida, en vez de uno por usuario.

    Se llama DESPUÉS de commitear, igual que _notify_admin_downgrades, para no
    tener la transacción tomada durante la llamada de red. Nunca levanta."""
    if not emails_list:
        return
    try:
        from billing import emails
        emails.send_trials_ended_admin(emails_list=list(emails_list))
    except Exception as ex:
        log.warning("aviso agregado de trials terminados falló (%d): %s",
                    len(emails_list), ex)


def _downgrade_expired_credit(conn) -> int:
    """Baja a Free a users cuya credit_active_until ya pasó.

    Solo afecta a users que NO tienen una suscripción 'authorized' activa.
    Si tienen authorized → el próximo cobro de Rebill va a refillar el
    crédito, así que dejamos pasar.

    Acá caen también las pruebas gratis que se terminan (día 16), y son la
    mayoría del volumen. Se las separa para el aviso al admin: una prueba que se
    apaga sola NO es un cliente que se fue, y avisarla igual que una baja real
    tapaba la señal de churn. Ver _notify_admin_trials_ended.

    Devuelve count de users degradados."""
    from billing import trial as _trial
    now = datetime.utcnow().isoformat()
    _sql = """SELECT u.id, u.email, u.tier, u.credit_active_until{extra}
           FROM users u
           WHERE u.tier IN ('pro', 'plus', 'advisor')
             AND u.credit_active_until IS NOT NULL
             AND u.credit_active_until < ?
             AND NOT EXISTS (
                SELECT 1 FROM subscriptions s
                WHERE s.user_id = u.id AND s.status = 'authorized'
             )"""
    # trial_ends_at solo decide A QUIÉN se le avisa, pero esta consulta es la que
    # hace cumplir el vencimiento del acceso pago: si un esquema no tuviera la
    # columna, el job entero dejaría de correr y NADIE bajaría a Free. Se
    # degrada en vez de fallar — sin el dato, todas las bajas se avisan una por
    # una, como antes de que existiera el trial.
    con_trial = True
    try:
        rows = conn.execute(_sql.format(extra=", u.trial_ends_at"), (now,)).fetchall()
    except Exception as ex:
        log.warning("sin columna trial_ends_at (%s): las bajas se avisan sin "
                    "distinguir pruebas gratis", ex)
        con_trial = False
        try:
            conn.rollback()   # la consulta fallida deja la transacción abortada
        except Exception:
            pass
        rows = conn.execute(_sql.format(extra=""), (now,)).fetchall()
    if not rows:
        return 0
    count = 0
    downgraded = []       # (email, tier_anterior) → un mail al admin por cada uno
    trials_vencidos = []  # emails de pruebas que se terminaron → un solo mail
    with conn:
        for r in rows:
            conn.execute(
                "UPDATE users SET tier = NULL WHERE id = ?",
                (r["id"],),
            )
            # Audit en el ledger para que se pueda reconstruir el "por qué"
            conn.execute(
                """INSERT INTO credit_ledger
                       (user_id, kind, amount_usd, days_delta,
                        from_plan, from_period, to_plan, to_period,
                        active_until_before, active_until_after,
                        note)
                   VALUES (?, 'expiration', 0, 0, ?, NULL, NULL, NULL, ?, ?, ?)""",
                (
                    r["id"], r["tier"], r["credit_active_until"], r["credit_active_until"],
                    "Credit window expired — downgraded to free",
                ),
            )
            count += 1
            if con_trial and _trial.credit_is_trial(
                    r["credit_active_until"], r["trial_ends_at"]):
                trials_vencidos.append(r["email"])
            else:
                downgraded.append((r["email"], r["tier"]))
            log.info(
                "Credit expired for user %s (was %s, active_until=%s) — downgraded to free",
                r["id"], r["tier"], r["credit_active_until"],
            )
    _marcar_corte_de_cuota(conn, [r["id"] for r in rows])
    _notify_admin_downgrades(downgraded, "credit_expired")
    _notify_admin_trials_ended(trials_vencidos)
    return count


def _send_credit_expiring_reminders(conn, days_before: int = 3, tanda=None) -> int:
    """Email "tu plan vence en N días" a quien se le termina el acceso pago
    (`users.credit_active_until`, la fuente de verdad del acceso) en los
    próximos `days_before` días y no tiene una suscripción que lo renueve.
    Incluye a quien recibió un regalo (no tiene fila en `subscriptions`). UN
    aviso por vencimiento: ver `_avisar_vencimiento`."""
    from billing import emails
    tanda = tanda or emails.Tanda()
    target_str = (datetime.utcnow() + timedelta(days=days_before)).isoformat()
    today_str = datetime.utcnow().isoformat()
    rows = conn.execute(
        """SELECT u.id as user_id, u.email, u.name, u.credit_active_until,
                  u.credit_anchor_plan, u.credit_anchor_period, u.tier
           FROM users u
           WHERE u.tier IN ('pro', 'plus', 'advisor')
             AND u.credit_active_until IS NOT NULL
             AND u.credit_active_until BETWEEN ? AND ?
             -- El trial NO entra acá: tiene su propia secuencia de avisos. Se
             -- compara contra trial_ends_at: un ex-trial que después pague sí
             -- tiene que recibir su aviso normal.
             AND (u.trial_ends_at IS NULL OR u.credit_active_until <> u.trial_ends_at)
             -- Con una suscripción que cobra sola (incluida la nueva de quien
             -- apretó "Reactivar"), el acceso no se termina.
             AND NOT EXISTS (
                SELECT 1 FROM subscriptions s
                WHERE s.user_id = u.id AND s.status = 'authorized'
             )""",
        (today_str, target_str),
    ).fetchall()
    sent = 0
    for r in rows:
        if tanda.frenado:      # Resend no confirma: lo que falta, la próxima vuelta
            break
        try:
            if _avisar_vencimiento(conn, tanda, r, r["credit_active_until"], days_before,
                                   que=f"aviso de fin de crédito uid={r['user_id']}"):
                sent += 1
        except Exception as ex:
            log.error("Credit expiring reminder falló para user %s: %s", r["user_id"], ex)
    return sent


def _delete_unverified_accounts(conn, stale_days: int = 7) -> int:
    """Elimina users con email_verified=0 creados hace > 7 días.

    Estos son signups abandonados: el user se registró pero nunca confirmó.
    Sin esto se acumulan filas zombie + emails ocupados que nadie usa.

    SAFE: solo borra users sin posiciones/operaciones/monthly (un user que
    nunca verificó no debería tener nada cargado, pero por las dudas chequeamos)."""
    from datetime import datetime, timedelta
    # ⚠️ La fecha se normaliza en las DOS puntas: created_at lo escribe SQLite
    # con datetime('now') → 'YYYY-MM-DD HH:MM:SS' (espacio) y el cutoff sale de
    # Python con 'T'. Como la comparación es de texto y ' ' < 'T', una fila del
    # mismo día quedaba SIEMPRE por debajo del corte y entraba en el barrido
    # hasta un día antes de lo que dice la política.
    cutoff = (datetime.utcnow() - timedelta(days=stale_days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT id, email FROM users
           WHERE email_verified = 0
             AND substr(replace(created_at,'T',' '),1,19) < ?
             AND managed_by IS NULL  -- shadows del Plan Asesor: NUNCA borrarlos acá
        """,
        (cutoff,),
    ).fetchall()
    if not rows:
        return 0
    deleted = 0
    with conn:
        for r in rows:
            # Defensa: si por algún motivo el user cargó data, no lo borramos
            has_data = conn.execute(
                """SELECT 1 FROM positions WHERE user_id=? UNION
                   SELECT 1 FROM operations WHERE user_id=? UNION
                   SELECT 1 FROM monthly_entries WHERE user_id=? LIMIT 1""",
                (r["id"], r["id"], r["id"]),
            ).fetchone()
            if has_data:
                log.warning("Skipping unverified user %s — has data", r["id"])
                continue
            # Cleanup en cascada manual (SQLite no soporta FK ON DELETE CASCADE
            # sin enable_foreign_keys=ON, y nuestras FKs no están declaradas).
            conn.execute("DELETE FROM email_verification_codes WHERE user_id = ?", (r["id"],))
            conn.execute("DELETE FROM brokers WHERE user_id = ?", (r["id"],))
            conn.execute("DELETE FROM users WHERE id = ?", (r["id"],))
            log.info("Deleted unverified user %s (%s, created > %dd ago)",
                    r["id"], r["email"], stale_days)
            deleted += 1
    return deleted


def _send_expiration_reminders(conn, days_before: int = 3, tanda=None) -> int:
    """El mismo aviso que `_send_credit_expiring_reminders`, para el modelo
    VIEJO: suscripciones canceladas de quien no tiene `credit_active_until`
    (anteriores al modelo de crédito), donde el fin del acceso es el
    `current_period_end` de la suscripción.

    Antes corría para TODA suscripción cancelada y avisaba su fecha (la del
    próximo cobro de Rebill) aunque el acceso real —el crédito— durara más: a
    quien pagó durante la prueba le avisaba hasta 19 días antes, y con el otro
    camino le llegaban dos avisos."""
    from billing import emails
    tanda = tanda or emails.Tanda()
    rows = conn.execute(
        """SELECT s.id, s.mp_subscription_id, s.current_period_end,
                  u.email, u.name, u.tier, u.id AS user_id
           FROM subscriptions s
           JOIN users u ON u.id = s.user_id
           WHERE s.status = 'cancelled'
             AND s.current_period_end IS NOT NULL
             AND u.credit_active_until IS NULL
             AND date(s.current_period_end) BETWEEN date('now')
                                                AND date('now', ?)
             AND NOT EXISTS (SELECT 1 FROM subscriptions s2
                              WHERE s2.user_id = u.id AND s2.status = 'authorized')""",
        (f"+{days_before} days",),
    ).fetchall()
    sent_count = 0
    for r in rows:
        if tanda.frenado:      # Resend no confirma: lo que falta, la próxima vuelta
            break
        try:
            if r["tier"] not in ("plus", "pro", "advisor"):
                # Ya no tiene un plan pago (lo bajaron a mano, o un reembolso):
                # "tu plan vence en 3 días" le anunciaría algo que no tiene.
                log.info("aviso de vencimiento salteado sub=%s: el tier es %r, "
                         "no un plan pago", r["mp_subscription_id"], r["tier"])
                continue
            if _avisar_vencimiento(conn, tanda, r, r["current_period_end"], days_before,
                                   que=f"aviso de vencimiento sub={r['mp_subscription_id']}"):
                sent_count += 1
        except Exception as ex:
            log.error("Expiration reminder failed for sub %s: %s",
                     r["mp_subscription_id"], ex)
    return sent_count


def _downgrade_expired_cancellations(conn) -> int:
    """Encuentra subs canceladas cuyo `current_period_end` ya pasó y baja
    al user a tier='free' (limpiando el override de plus o pro).
    Devuelve count de users degradados.

    GUARDAS (defensa en profundidad — source of truth = credit_active_until):
      • Solo baja si el crédito del user YA venció (credit_active_until null o
        en el pasado). Si todavía tiene crédito vigente, el tier es legítimo y
        NO se toca, aunque exista una sub cancelada vieja con period_end
        vencido.
      • Solo baja si el user NO tiene ninguna sub 'authorized'. Una authorized
        = plan vigente que se renueva solo; una cancelada vieja no debe pisarlo.

    Sin estas guardas, un user que se suscribe → cancela → vuelve a suscribirse
    quedaba expuesto: la sub cancelada vieja (period_end en el pasado) actuaba
    de mina y el primer cron tras la re-suscripción le borraba el tier recién
    pagado. El path1 (_downgrade_expired_credit) ya tenía el guard de
    'authorized'; este path era el que faltaba alinear."""
    now = datetime.utcnow().isoformat()
    rows = conn.execute(
        """SELECT s.id, s.user_id, s.mp_subscription_id, s.current_period_end,
                  u.tier, u.email, u.credit_active_until
           FROM subscriptions s
           JOIN users u ON u.id = s.user_id
           WHERE s.status = 'cancelled'
             AND s.current_period_end IS NOT NULL
             AND s.current_period_end < ?
             AND u.tier IN ('pro', 'plus', 'advisor')
             AND (u.credit_active_until IS NULL OR u.credit_active_until < ?)
             AND NOT EXISTS (
                SELECT 1 FROM subscriptions a
                WHERE a.user_id = s.user_id AND a.status = 'authorized'
             )""",
        (now, now),
    ).fetchall()
    if not rows:
        return 0

    count = 0
    downgraded = []  # (email, tier_anterior) para avisar al admin tras commitear
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
            # Audit en el ledger — mismo formato que _downgrade_expired_credit,
            # para que el endpoint de diagnóstico reconstruya el "por qué".
            conn.execute(
                """INSERT INTO credit_ledger
                       (user_id, kind, amount_usd, days_delta,
                        from_plan, from_period, to_plan, to_period,
                        active_until_before, active_until_after, note)
                   VALUES (?, 'expiration', 0, 0, ?, NULL, NULL, NULL, ?, ?, ?)""",
                (
                    r["user_id"], r["tier"], r["credit_active_until"],
                    r["credit_active_until"],
                    "Cancelled sub period_end passed — downgraded to free",
                ),
            )
            count += 1
            downgraded.append((r["email"], r["tier"]))
            log.info(
                "User %s downgraded (sub %s expired at %s, credit_until=%s)",
                r["user_id"], r["mp_subscription_id"], r["current_period_end"],
                r["credit_active_until"],
            )
    _marcar_corte_de_cuota(conn, [r["user_id"] for r in rows])
    _notify_admin_downgrades(downgraded, "cancellation_expired")
    return count


def _cancel_stale_pending(conn, stale_days: int = 7) -> int:
    """Subs en 'pending' por más de `stale_days` se cancelan automáticamente.
    Esto libera el slot para que el user pueda crear una sub nueva sin que
    el endpoint /billing/subscribe le devuelva el init_point viejo (que
    probablemente ya expiró en MP)."""
    # ⚠️ La fecha se normaliza en las DOS puntas: created_at lo escribe SQLite
    # con datetime('now') → 'YYYY-MM-DD HH:MM:SS' (espacio) y el cutoff sale de
    # Python con 'T'. Como la comparación es de texto y ' ' < 'T', una fila del
    # mismo día quedaba SIEMPRE por debajo del corte y entraba en el barrido
    # hasta un día antes de lo que dice la política.
    cutoff = (datetime.utcnow() - timedelta(days=stale_days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT id, user_id, mp_subscription_id, created_at
           FROM subscriptions
           WHERE status = 'pending'
             AND substr(replace(created_at,'T',' '),1,19) < ?""",
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
