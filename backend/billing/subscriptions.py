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


def _dias_que_quedan(fin) -> int:
    """Los días que faltan, con LA cuenta de la prueba (`trial.dias_restantes`:
    redondea para arriba, como la app) — una sola para todos los mails. El
    redondeo para abajo llegaba a decir "vence en 0 días" con horas por
    delante (con los reintentos, o al cancelar el día antes de renovar)."""
    from billing.trial import dias_restantes
    return dias_restantes(fin)


def _ahora_db() -> str:
    """La hora UTC en el formato de `datetime('now')` de SQLite, que es como se
    escribían estas marcas. Se arma en Python para saber QUÉ marca se puso y
    poder devolver justo esa si el mail no sale."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def run_lifecycle_job(conn) -> dict:
    """Corre el job completo del ciclo de vida. Devuelve dict con counts
    de cada operación para que el caller pueda loguear / monitorear."""
    from billing import emails
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
        "unverified_accounts_deleted": 0,
        "avisos_frenados": False,
        "errors": 0,
    }
    # Source of truth = users.credit_active_until (modelo de crédito tiempo-based).
    # El downgrade post-cancelación queda como fallback para subs viejas que
    # nunca pasaron por el nuevo modelo.
    try:
        result["credit_expired_downgraded"] = _downgrade_expired_credit(conn)
    except Exception as ex:
        log.error("credit expiration downgrade failed: %s", ex)
        result["errors"] += 1
    # Trials que ya cumplieron su semana de Pro → pasan a Plus. Va ANTES de los
    # recordatorios para que el mail del día salga con el plan correcto.
    try:
        from billing import trial as _trial
        result["trials_stepped_down"] = _trial.step_down_due_trials(conn)
    except Exception as ex:
        log.error("trial step-down failed: %s", ex)
        result["errors"] += 1
    # Los avisos van DESPUÉS del step-down para que el estado ya esté acomodado
    # cuando se decide qué mail corresponde.
    try:
        from billing import trial as _trial
        result["trial_emails_sent"] = _trial.send_due_trial_emails(conn, tanda)
    except Exception as ex:
        log.error("trial emails failed: %s", ex)
        result["errors"] += 1
    try:
        result["credit_expiring_reminders_sent"] = _send_credit_expiring_reminders(conn, tanda=tanda)
    except Exception as ex:
        log.error("credit expiring reminders failed: %s", ex)
        result["errors"] += 1
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
        result["expiration_reminders_sent"] = _send_expiration_reminders(conn, tanda=tanda)
    except Exception as ex:
        log.error("Expiration reminders failed: %s", ex)
        result["errors"] += 1
    try:
        result["unverified_accounts_deleted"] = _delete_unverified_accounts(conn)
    except Exception as ex:
        log.error("Unverified accounts cleanup failed: %s", ex)
        result["errors"] += 1
    # Resend no confirmó los envíos y la tanda se frenó: lo que faltaba queda
    # sin marca para la corrida siguiente (dentro de la ventana de cada aviso;
    # el job corre dos veces por día). Que se vea en el resultado del job.
    result["avisos_frenados"] = tanda.frenado
    if tanda.frenado:
        log.error("ciclo de vida: Resend no confirma los envíos; se frenaron los avisos "
                  "y lo que faltaba queda para la próxima corrida")
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
    """Email "tu crédito se acaba en N días" a users sin sub autorizada.

    Idempotente: reusamos expiration_reminder_sent_at en la subscription más
    reciente del user. Si el user nunca tuvo sub (caso raro), creamos un
    placeholder no-op (skip).

    NOTA: Si en el futuro queremos un canal separado por crédito vs cancel,
    se puede agregar una col `credit_reminder_sent_at` en users.
    """
    from billing import emails
    tanda = tanda or emails.Tanda()
    today = datetime.utcnow().date()
    target_str = (datetime.utcnow() + timedelta(days=days_before)).isoformat()
    today_str = datetime.utcnow().isoformat()
    rows = conn.execute(
        """SELECT u.id as user_id, u.email, u.name, u.credit_active_until,
                  u.credit_anchor_plan, u.credit_anchor_period, u.tier
           FROM users u
           WHERE u.tier IN ('pro', 'plus', 'advisor')
             AND u.credit_active_until IS NOT NULL
             AND u.credit_active_until BETWEEN ? AND ?
             -- El trial NO entra acá: tiene su propia secuencia de avisos, y
             -- este mail se apoya en la tabla subscriptions para no repetirse
             -- (un usuario de trial no tiene fila ahí, así que le llegaba TODOS
             -- los días de los últimos 4, y encima diciendo "tu plan Pro" —
             -- audit). Se compara contra trial_ends_at: un ex-trial que después
             -- pague sí tiene que recibir su aviso normal.
             AND (u.trial_ends_at IS NULL OR u.credit_active_until <> u.trial_ends_at)
             AND NOT EXISTS (
                SELECT 1 FROM subscriptions s
                WHERE s.user_id = u.id AND s.status = 'authorized'
             )""",
        (today_str, target_str),
    ).fetchall()
    if not rows:
        return 0

    sent = 0
    for r in rows:
        if tanda.frenado:      # Resend no confirma: lo que falta, mañana
            break
        try:
            # Idempotencia: chequear si la última subscription cancelled ya recibió
            # el reminder para este window.
            existing_sent = conn.execute(
                """SELECT id FROM subscriptions
                   WHERE user_id = ? AND expiration_reminder_sent_at IS NOT NULL
                   ORDER BY updated_at DESC LIMIT 1""",
                (r["user_id"],),
            ).fetchone()
            if existing_sent:
                continue  # ya mandado
            # Sin fila en subscriptions no hay dónde marcar que ya se envió, así
            # que el mail saldría en CADA corrida. Preferimos no mandarlo antes
            # que mandarlo cuatro veces (audit).
            _has_sub = conn.execute(
                "SELECT 1 FROM subscriptions WHERE user_id=? LIMIT 1", (r["user_id"],)
            ).fetchone()
            if not _has_sub:
                log.info("credit expiring reminder salteado uid=%s: sin suscripción "
                         "donde registrar el envío", r["user_id"])
                continue

            try:
                period_end = datetime.fromisoformat(
                    r["credit_active_until"].replace("Z", "").split(".")[0]
                )
                days_left = _dias_que_quedan(period_end)
            except Exception:
                days_left = days_before

            from billing import trial as _trial
            from billing import plan_textos as _plan_textos
            # El plan que vence es el del ancla del crédito; si falta, el que
            # tiene puesto (la consulta ya lo limita a pro/plus/advisor). Caía
            # a "pro" y a un Plus sin ancla le avisaba que vencía su Pro.
            plan = r["credit_anchor_plan"] or r["tier"]
            datos = dict(
                to=r["email"],
                user_name=(r["name"] or r["email"].split("@")[0]),
                days_left=days_left,
                expires_at=r["credit_active_until"],
                plan=plan,
                # Nació sin plan gratis → no "pierde" features: queda en pausa.
                requiere_plan=_trial._requiere_plan(conn, r["user_id"]),
                # Los cupos de ESTA persona, no los del plan: ver cupos_del_usuario.
                cupos=_plan_textos.cupos_del_usuario(conn, r["user_id"], plan),
            )

            # La marca va en la sub más reciente del user, ANTES de mandar y
            # sólo si ninguna de sus subs la tiene (el mismo chequeo de arriba,
            # pero en el UPDATE: dos corridas a la vez no la ganan las dos).
            # Antes se anotaba DESPUÉS y sin mirar si el mail había salido: un
            # rechazo de Resend quedaba como enviado y el aviso no llegaba nunca.
            def marcar(uid=r["user_id"]):
                marca = _ahora_db()
                with conn:
                    sub = conn.execute(
                        """SELECT id FROM subscriptions WHERE user_id = ?
                           ORDER BY created_at DESC LIMIT 1""", (uid,)).fetchone()
                    if not sub:
                        return None
                    # `IS NULL` sobre la fila que se marca, además del NOT
                    # EXISTS: en Postgres la segunda de dos corridas a la vez
                    # re-chequea la fila al destrabarse, pero el NOT EXISTS lo
                    # ve con la foto de antes y las dos ganaban.
                    cur = conn.execute(
                        """UPDATE subscriptions
                           SET expiration_reminder_sent_at = ?
                           WHERE id = ? AND expiration_reminder_sent_at IS NULL
                             AND NOT EXISTS (SELECT 1 FROM subscriptions
                                             WHERE user_id = ?
                                               AND expiration_reminder_sent_at IS NOT NULL)""",
                        (marca, sub["id"], uid),
                    )
                return (sub["id"], marca) if cur.rowcount > 0 else None

            def desmarcar(m):
                sub_id, marca = m
                with conn:
                    conn.execute(
                        """UPDATE subscriptions SET expiration_reminder_sent_at = NULL
                           WHERE id = ? AND expiration_reminder_sent_at = ?""",
                        (sub_id, marca),
                    )

            res = tanda.enviar(
                marcar, lambda: emails.send_expiration_reminder(**datos), desmarcar,
                que=f"aviso de fin de crédito uid={r['user_id']}")
            if res == emails.ENVIADO:
                sent += 1
                log.info("Credit expiring reminder enviado a user %s (days_left=%s)",
                         r["user_id"], days_left)
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
    """Manda recordatorio a users cuya sub cancelada está por expirar en N días.

    Solo afecta a subs `cancelled` (no a `authorized` activas — esas se renuevan
    automáticamente). Idempotente vía expiration_reminder_sent_at.

    Nota: 'superseded' subs (cambio de plan) NO entran acá porque su current_period_end
    ya no es el source of truth — usamos users.credit_active_until en
    _send_credit_expiring_reminders.
    """
    from billing import emails
    tanda = tanda or emails.Tanda()
    rows = conn.execute(
        """SELECT s.id, s.mp_subscription_id, s.current_period_end,
                  u.email, u.name, u.tier, u.id AS user_id
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
        if tanda.frenado:      # Resend no confirma: lo que falta, mañana
            break
        try:
            from datetime import datetime
            try:
                period_end = datetime.fromisoformat(
                    r["current_period_end"].replace("Z", "").split(".")[0]
                )
                days_left = _dias_que_quedan(period_end)
            except Exception:
                days_left = days_before

            from billing import trial as _trial
            from billing import plan_textos as _plan_textos
            plan = r["tier"]
            if plan not in ("plus", "pro", "advisor"):
                # Ya no tiene un plan pago (lo bajaron a mano, o un reembolso):
                # "tu plan Pro vence en 3 días" le anunciaría algo que no tiene.
                # Antes caía a "pro". No se marca: si el plan vuelve, el aviso sale.
                log.info("aviso de vencimiento salteado sub=%s: el tier es %r, "
                         "no un plan pago", r["mp_subscription_id"], plan)
                continue
            datos = dict(
                to=r["email"],
                user_name=(r["name"] or r["email"].split("@")[0]),
                days_left=days_left,
                expires_at=r["current_period_end"],
                plan=plan,
                # Nació sin plan gratis → no "pierde" features: queda en pausa.
                requiere_plan=_trial._requiere_plan(conn, r["user_id"]),
                # Los cupos de ESTA persona, no los del plan: ver cupos_del_usuario.
                cupos=_plan_textos.cupos_del_usuario(conn, r["user_id"], plan),
            )

            # Marca ANTES de mandar, condicional, y se devuelve si el mail no
            # salió (ver `emails.Tanda`). Antes se anotaba después sin mirar el
            # resultado: un rechazo de Resend quedaba como enviado.
            def marcar(sub_id=r["id"]):
                marca = _ahora_db()
                with conn:
                    cur = conn.execute(
                        """UPDATE subscriptions SET expiration_reminder_sent_at = ?
                           WHERE id = ? AND expiration_reminder_sent_at IS NULL""",
                        (marca, sub_id),
                    )
                return marca if cur.rowcount > 0 else None

            def desmarcar(marca, sub_id=r["id"]):
                with conn:
                    conn.execute(
                        """UPDATE subscriptions SET expiration_reminder_sent_at = NULL
                           WHERE id = ? AND expiration_reminder_sent_at = ?""",
                        (sub_id, marca),
                    )

            res = tanda.enviar(
                marcar, lambda: emails.send_expiration_reminder(**datos), desmarcar,
                que=f"aviso de vencimiento sub={r['mp_subscription_id']}")
            if res == emails.ENVIADO:
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
