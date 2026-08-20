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
    """Cuántos trials se activaron en el mes calendario en curso (UTC).

    ⚠️ El piso se compara por DÍA, no con un timestamp ISO. `created_at` lo
    escribe SQLite con datetime('now') → 'YYYY-MM-DD HH:MM:SS' (con ESPACIO),
    mientras que datetime.utcnow().isoformat() pone una 'T'. La comparación es
    de texto y el espacio (0x20) ordena ANTES que la 'T' (0x54), así que
    '2026-09-01 14:00:00' < '2026-09-01T00:00:00': toda fila del día 1 caía
    debajo del piso y no se contaba NUNCA. Medido: con tope 3 entraron 8 trials
    el día 1 y el mes cerró con 11. Es la misma trampa que ya había arreglado
    13acf975 en el embudo; con substr(...,1,10) no hay forma de que vuelva.
    """
    month_start = datetime.utcnow().strftime("%Y-%m-01")
    # Se cuenta sobre el LEDGER, no sobre users: borrar la cuenta no puede
    # devolver un cupo (audit). El ledger es append-only.
    try:
        row = conn.execute(
            "SELECT COUNT(*) c FROM credit_ledger WHERE kind='trial' "
            "AND substr(replace(created_at,'T',' '),1,10) >= ?",
            (month_start,),
        ).fetchone()
        return int(row["c"] if hasattr(row, "keys") else row[0]) if row else 0
    except Exception as ex:
        # Fail-CLOSED: si no podemos contar, no activamos. El tope existe para
        # acotar el gasto — que se caiga solo justo bajo carga sería lo peor.
        log.warning("no pudimos contar los trials del mes: %s", ex)
        return 10 ** 9


def credit_is_trial(credit_active_until, trial_ends_at) -> bool:
    """¿El crédito de esta fila ES el del trial (y no un regalo o un pago)?

    El trial deja los anchors en NULL A PROPÓSITO: ponerle precio a los 15 días
    gratis los convertía en plata real y "cambiar de plan" los transformaba en
    41 días de Plus (audit). El efecto secundario es que "tier pago + anchor
    NULL" dejó de ser un estado raro y pasó a ser el estado NORMAL de toda la
    población en prueba — y cada camino de billing que asumía "tier pago ⇒ hay
    un plan pago detrás" se empezó a romper.

    La marca que sí distingue al trial es la VENTANA: credit_active_until quedó
    grabada exactamente igual que trial_ends_at. Se compara acá, en un solo
    lugar, para que los tres lectores (campaña de regalos, restore-tier, aviso
    de baja al admin) no lo decidan cada uno con su propio criterio."""
    return bool(credit_active_until and trial_ends_at
                and str(credit_active_until) == str(trial_ends_at))


def stage_by_calendar(started_at, now=None):
    """Qué etapa le TOCA por calendario: 'pro' la primera semana, 'plus' después.
    None si no hay fecha de arranque legible.

    Es la regla de los TRIAL_PRO_DAYS días, y vive acá para que exista una sola
    vez: si mañana el trial pasa a 5+10, cambiar la constante tiene que alcanzar
    — un panel de admin con su propia copia del 7 seguiría reparando mal."""
    if not started_at:
        return None
    try:
        ini = datetime.fromisoformat(str(started_at).replace("Z", ""))
    except (TypeError, ValueError):
        return None
    return "pro" if ((now or datetime.utcnow()) - ini) < timedelta(days=TRIAL_PRO_DAYS) else "plus"


def dias_restantes(hasta, ahora=None) -> int:
    """Cuántos días le quedan, redondeando HACIA ARRIBA la fracción de día.

    Una sola definición para toda la prueba. Había dos —la app redondeaba para
    arriba y el mail del día 14 truncaba— así que el mismo día la barra decía
    "te quedan 2 días" y el mail que llegaba esa mañana decía "te queda 1".
    Hacia arriba porque es lo que el usuario entiende: mientras le quede algo de
    hoy, hoy cuenta."""
    if not hasta:
        return 0
    try:
        fin = hasta if isinstance(hasta, datetime) else datetime.fromisoformat(
            str(hasta).replace("Z", ""))
    except (TypeError, ValueError):
        return 0
    d = fin - (ahora or datetime.utcnow())
    if d.total_seconds() <= 0:
        return 0
    return max(1, d.days + (1 if d.seconds or d.microseconds else 0))


def repair_stage(conn, user_id: int):
    """El tier que le corresponde HOY a alguien cuyo crédito vigente es el del
    trial ('pro'|'plus'), o None si su crédito NO es el del trial.

    Existe para reparar users.tier desde el panel de admin. No se saca de
    status()['stage'] a propósito: esa etapa es el tier EFECTIVO (sale de
    quota.get_tier, que lee users.tier) — justo la columna que está rota cuando
    hace falta repararla. Preguntarle a ella devolvería 'free' y no repararía
    nada. El calendario, en cambio, no se desincroniza."""
    try:
        row = conn.execute(
            """SELECT trial_started_at, trial_ends_at, credit_active_until
                 FROM users WHERE id=?""", (user_id,)).fetchone()
    except Exception as ex:
        log.warning("repair_stage falló uid=%s: %s", user_id, ex)
        return None
    if not row:
        return None
    cau = row["credit_active_until"]
    if not credit_is_trial(cau, row["trial_ends_at"]):
        return None
    # Un trial ya vencido no se repara: el usuario es Free y corresponde que lo
    # sea. Restaurarle el tier le devolvería acceso que ya se terminó.
    if str(cau) <= datetime.utcnow().isoformat():
        return None
    return stage_by_calendar(row["trial_started_at"])


def _email_of(conn, user_id: int):
    try:
        r = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        return r["email"] if r else None
    except Exception:
        return None


def normalizar_email(email) -> str:
    """El email reducido a LA BANDEJA que lo recibe.

    Sin esto, una sola casilla de Gmail saca trials infinitos: 'juan.perez@',
    'juanperez@', 'j.u.a.n.perez@', 'juan.perez+loquesea@' y el mismo usuario en
    'googlemail.com' son la MISMA bandeja y daban cinco claves distintas. El
    +alias se corta en todos los proveedores (es estándar y no cambia el
    destino); los puntos SOLO en Gmail, donde son decorativos — en otros
    dominios 'a.b@x.com' y 'ab@x.com' pueden ser dos personas distintas.

    No pretende frenar a un decidido con dos casillas de verdad: corta el abuso
    trivial, que es el que escala."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    usuario, dominio = e.rsplit("@", 1)
    usuario = usuario.split("+", 1)[0]           # +alias → misma bandeja, siempre
    if dominio in ("gmail.com", "googlemail.com"):
        usuario = usuario.replace(".", "")       # los puntos son decorativos
        dominio = "gmail.com"                    # googlemail es un alias de gmail
    return f"{usuario}@{dominio}"


def _email_key(email) -> str:
    """Clave estable del email para recordar quién ya usó su trial. Se guarda
    HASHEADA: sirve para comparar, no para reconstruir la casilla."""
    import hashlib
    return hashlib.sha256(normalizar_email(email).encode()).hexdigest()


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


class _TopeDelMes(Exception):
    """Interna: el tope del mes se llenó DENTRO de la transacción del alta, así
    que hay que deshacerla entera."""


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
    cap = monthly_cap()
    try:
        return _start_tx(conn, user_id, until, now_iso, cap)
    except _TopeDelMes:
        # El `with conn` de _start_tx ya deshizo el alta al propagarse.
        return {"ok": False, "can_start": False, "reason": "monthly_cap_reached"}


def _start_tx(conn, user_id: int, until: str, now_iso: str, cap: int) -> dict:
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
                      -- La prueba arranca con la cuota LIMPIA: si esta semana ya
                      -- gastó su análisis de Free, el primer día de Pro no puede
                      -- salirle 1/60 (el día 1 es el que decide si la prueba se
                      -- usa o se quema).
                      quota_window_from=date('now','localtime'),
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
        _nota = f"Free trial: {TRIAL_PRO_DAYS}d Pro + {TRIAL_PLUS_DAYS}d Plus"
        if cap:
            # CON TOPE, el ledger deja de ser solo auditoría: es el que lo hace
            # cumplir. El chequeo de eligibility() es check-then-act —lee el
            # conteo, después escribe— y entre las dos cosas entran todas las
            # activaciones que quieran: medido, con tope 5 y 20 pedidos
            # simultáneos entraron los 20. Acá el conteo y la escritura son UN
            # solo statement, así que el tope se respeta bajo carga (mismo patrón
            # que reserve_chat). Si no entra, se levanta para que el `with conn`
            # DESHAGA el alta: sin eso el usuario quedaría con la prueba puesta y
            # sin fila en el ledger, o sea invisible para el tope del mes que viene.
            led = conn.execute(
                """INSERT INTO credit_ledger
                       (user_id, kind, amount_usd, days_delta,
                        from_plan, from_period, to_plan, to_period,
                        active_until_before, active_until_after, note)
                   SELECT ?, 'trial', 0, ?, NULL, NULL, 'pro', NULL, NULL, ?, ?
                    WHERE (SELECT COUNT(*) FROM credit_ledger
                            WHERE kind='trial'
                              AND substr(replace(created_at,'T',' '),1,10) >= ?) < ?""",
                (user_id, TRIAL_TOTAL_DAYS, until, _nota,
                 datetime.utcnow().strftime("%Y-%m-01"), cap),
            )
            if led.rowcount == 0:
                raise _TopeDelMes()
        else:
            try:
                conn.execute(
                    """INSERT INTO credit_ledger
                           (user_id, kind, amount_usd, days_delta,
                            from_plan, from_period, to_plan, to_period,
                            active_until_before, active_until_after, note)
                       VALUES (?, 'trial', 0, ?, NULL, NULL, 'pro', NULL, NULL, ?, ?)""",
                    (user_id, TRIAL_TOTAL_DAYS, until, _nota),
                )
            except Exception as ex:   # sin tope el ledger es auditoría: no voltea el alta
                log.warning("trial ledger insert falló uid=%s: %s", user_id, ex)
    log.info("trial started uid=%s until=%s", user_id, until)
    # Mail de bienvenida en el momento: el primer día es el que decide si el
    # trial se usa o se quema. No puede esperar al cron de mañana.
    try:
        from billing import emails
        row = conn.execute("SELECT email, name FROM users WHERE id=?", (user_id,)).fetchone()
        _gano = False
        if row and row["email"]:
            with conn:      # transacción propia: sin esto la marca se perdía al
                _gano = _mark_sent(conn, user_id, MAIL_STARTED)   # cerrar la conexión
        # El envío va FUERA de toda transacción: httpx tarda hasta 10s y no
        # puede tener tomado el lock de escritura de SQLite (audit 2026-08-10).
        if _gano:
            emails.send_trial_started(
                to=row["email"],
                user_name=(row["name"] or row["email"].split("@")[0]),
                pro_days=TRIAL_PRO_DAYS, total_days=TRIAL_TOTAL_DAYS)
    except Exception as ex:
        log.warning("mail de bienvenida del trial falló uid=%s: %s", user_id, ex)
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
    # El crédito vigente tiene que ser EL DEL TRIAL, no cualquiera. Este era el
    # cuarto lector de credit_active_until y el único que nunca preguntó de quién
    # era ese crédito — y justo el que alimenta la UI. Como trial_started_at
    # queda para siempre, cualquier crédito POSTERIOR heredaba la etiqueta:
    #   · el que pagó Plus anual veía "Estás probando Rendi Plus, te quedan 365
    #     días" después de poner USD 54;
    #   · el que pagó Pro y canceló veía "En prueba · no cargamos ninguna
    #     tarjeta" al lado de "Reactivar suscripción" — le cobraron y la pantalla
    #     se lo negaba;
    #   · al que le regalaron Pro le repetía "Mañana pasás a Plus" todos los días.
    # _has_paid_sub solo tapaba el caso de una sub 'authorized': 'cancelled' y
    # 'superseded' pasaban derecho.
    es_del_trial = credit_is_trial(cau, row["trial_ends_at"] if "trial_ends_at" in keys else None)
    if until_dt and now < until_dt and es_del_trial and not _has_paid_sub(conn, user_id):
        out["active"] = True
        # La etapa es el tier EFECTIVO, no el que dice el calendario: si el cron
        # todavía no corrió, el usuario sigue teniendo Pro de verdad y la UI no
        # puede anunciarle que ya está en Plus (audit).
        try:
            from ai import quota as _q
            real = _q.get_tier(conn, user_id)
            out["stage"] = real if real in ("pro", "plus") else None
        except Exception:
            out["stage"] = stage_by_calendar(started_dt, now)
        # Días completos que faltan para que se termine TODO el trial.
        out["days_left"] = dias_restantes(until_dt, now)
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
    # El corte va por DÍA, no por instante — mismo umbral, otra unidad.
    #
    # Con el instante, el corte caía un día tarde: el trial arranca a la hora que
    # el usuario aprieta el botón (digamos 14:00) y el cron corre de madrugada,
    # así que en la corrida del día 8 a las 03:00 todavía no habían pasado los 7
    # días exactos y el step-down esperaba a la del día 9. Resultado: la etapa
    # Pro duraba 8 días calendario y se comía DOS ventanas de cuota —el día 8 la
    # ventana ya había soltado el día 1 y le devolvía los 60 análisis— o sea 120
    # análisis y 80 chats, el doble del modelo de costo con el que se eligió el
    # plazo de 7 días. Por fecha, el corte cae siempre el día 8 y la etapa Pro
    # ocupa exactamente una ventana, que es el diseño.
    #
    # El replace('T',' ') es porque trial_started_at lo escribe Python con 'T' y
    # date() de SQLite necesita el formato con espacio.
    cutoff = (datetime.utcnow().date() - timedelta(days=TRIAL_PRO_DAYS)).isoformat()
    try:
        rows = conn.execute(
            """SELECT id, email, trial_started_at FROM users
                WHERE tier='pro'
                  AND trial_started_at IS NOT NULL
                  AND date(replace(trial_started_at,'T',' ')) <= ?
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
            # quota_window_from va en el MISMO UPDATE (no por note_tier_change):
            # estamos dentro de un `with conn` y abrir otra transacción adentro
            # commitearía la de afuera a la mitad.
            #
            # La cuota del tramo Plus arranca HOY. Sin esto, los 60 análisis que
            # el propio trial le regaló en la semana de Pro se le descontaban del
            # techo de 6 de Plus —la ventana de cuota mide 7 días y la etapa Pro
            # dura 7 días exactos— y entraba a Plus con el badge en 60/6 y un 429
            # invitándolo a pasarse a Pro. Justo al revés de lo que la etapa Plus
            # tiene que provocar: cuanto mejor le había ido en la prueba, peor le
            # iba después.
            conn.execute(
                "UPDATE users SET tier='plus', quota_window_from=? WHERE id=? AND tier='pro'",
                # Fecha LOCAL, el mismo reloj con el que ai_usage_daily guarda
                # el consumo (date.today()). Con utcnow() el piso quedaba un día
                # adelante en cualquier servidor que no corra en UTC, la ventana
                # daba vacía y el usuario tenía cuota infinita hasta que el reloj
                # lo alcanzaba.
                (datetime.now().date().isoformat(), r["id"]))
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


# ─── Avisos ─────────────────────────────────────────────────────────────────
# Cuatro mails en 15 días, cada uno con un trabajo distinto:
#   día 1  → arrancó (con TRES cosas concretas para hacer hoy)
#   día 7  → mañana termina Pro   ← el que más convierte: avisa ANTES
#   día 14 → quedan 2 días
#   día 16 → terminó (con su propio resumen)
# El del día 8 (ya pasaste a Plus) va SOLO dentro de la app: se avisó el día
# anterior y dos mails seguidos por lo mismo hacen que dejen de abrirlos justo
# antes del aviso que importa.
#
# La idempotencia es propia (tabla trial_email_log) y NO se apoya en la tabla
# subscriptions como el resto de los avisos: un usuario de trial no tiene fila
# ahí, y por eso el aviso genérico de vencimiento le salía todos los días
# (audit).

MAIL_STARTED = "started"
MAIL_PRO_ENDING = "pro_ending"
MAIL_ENDING_SOON = "ending_soon"
MAIL_ENDED = "ended"


def _already_sent(conn, user_id: int, kind: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM trial_email_log WHERE user_id=? AND kind=? LIMIT 1",
            (user_id, kind),
        ).fetchone() is not None
    except Exception:
        # Sin poder verificar, NO mandamos: repetir un mail es peor que
        # saltearlo (audit: el aviso genérico salía 4 días seguidos).
        return True


def _mark_sent(conn, user_id: int, kind: str) -> bool:
    """Marca ANTES de mandar y devuelve si ganó la carrera. La PK (user_id,
    kind) hace que dos corridas simultáneas del cron no puedan mandar dos
    veces el mismo mail."""
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO trial_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
            (user_id, kind, datetime.utcnow().isoformat()),
        )
        return cur.rowcount > 0
    except Exception as ex:
        log.warning("no pudimos registrar el mail de trial %s uid=%s: %s", kind, user_id, ex)
        return False


def _trial_stats(conn, user_id: int) -> dict:
    """Lo que hizo DURANTE el trial — para el mail final. Un dato suyo convierte
    mucho más que una lista de features, pero tiene que ser verdad: sin acotar
    por fecha, a un usuario de un año que no tocó nada en los 15 días el mail le
    decía "en estos 15 días: 3.480 operaciones importadas" (audit 2026-08-10).
    Justo al que NO usó el trial, que es el que había que detectar."""
    out = {}
    try:
        ini = conn.execute(
            "SELECT trial_started_at t FROM users WHERE id=?", (user_id,)).fetchone()
        desde = str(ini["t"]) if ini and ini["t"] else None
    except Exception:
        desde = None
    if not desde:
        return out
    dia = desde[:10]
    # Los brokers no tienen fecha de alta confiable → se informa el total, que
    # para "brokers conectados" es lo que el usuario entiende igual.
    for key, sql, params in (
        ("brokers", "SELECT COUNT(*) c FROM brokers WHERE user_id=?", (user_id,)),
        # Cuántas operaciones CARGÓ en la prueba, no cuántas OCURRIERON en esos
        # días. operations.date es la fecha de la operación (cuándo compró), así
        # que a quien importó sus 343 movimientos de los últimos tres años el
        # mail le decía "3 operaciones importadas" — contaba solo las que además
        # habían pasado en los últimos 15 días. Justo el mail que empuja a pagar,
        # y justo el usuario que SÍ usó la prueba. La fecha de CARGA vive en
        # import_batches.created_at; se suma valid_rows de los batches confirmados
        # en la ventana. Lo cargado a mano no entra (no tiene fecha de carga),
        # pero el que carga a mano carga de a una y no es el caso que importa.
        ("operations",
         "SELECT COALESCE(SUM(valid_rows),0) c FROM import_batches "
         "WHERE user_id=? AND status='confirmed' "
         "AND substr(replace(created_at,'T',' '),1,10) >= ?", (user_id, dia)),
        ("analyses",
         "SELECT COALESCE(SUM(analyses_count),0) c FROM ai_usage_daily "
         "WHERE user_id=? AND date >= ?", (user_id, dia)),
    ):
        try:
            r = conn.execute(sql, params).fetchone()
            if r and r["c"]:
                out[key] = int(r["c"])
        except Exception:
            pass
    return out


def send_due_trial_emails(conn) -> int:
    """Paso del cron: manda los avisos que correspondan hoy. Devuelve cuántos
    mails salieron. Cada uno se marca ANTES de enviarse, así un fallo del
    proveedor no genera un reenvío al día siguiente (preferimos perder un
    aviso antes que repetirlo)."""
    from billing import emails
    now = datetime.utcnow()
    sent = 0

    def _name(r):
        return (r["name"] or (r["email"] or "").split("@")[0] or "Hola")

    # ── día 7: mañana termina Pro (solo a quien SIGUE en la etapa Pro) ──────
    try:
        rows = conn.execute(
            # SIN borde inferior ni filtro por tier: la idempotencia ya la da
            # trial_email_log. Con una ventana de 24h exactas, un cron atrasado
            # (o el step-down corriendo antes) hacía que este aviso —el que más
            # convierte— no saliera NUNCA para esa cohorte (audit 2026-08-10).
            """SELECT id, email, name FROM users
                WHERE trial_ends_at IS NOT NULL
                  AND credit_active_until = trial_ends_at
                  AND trial_ends_at > ?
                  AND trial_started_at <= ?""",
            (now.isoformat(),
             (now - timedelta(days=TRIAL_PRO_DAYS - 1)).isoformat()),
        ).fetchall()
    except Exception as ex:
        log.error("trial mails (pro_ending) falló: %s", ex)
        rows = []
    for r in rows:
        if _already_sent(conn, r["id"], MAIL_PRO_ENDING):
            continue
        with conn:
            if not _mark_sent(conn, r["id"], MAIL_PRO_ENDING):
                continue
        try:
            emails.send_trial_pro_ending(to=r["email"], user_name=_name(r),
                                         plus_days=TRIAL_PLUS_DAYS)
            sent += 1
        except Exception as ex:
            log.warning("mail trial pro_ending falló uid=%s: %s", r["id"], ex)

    # ── día 14: quedan 2 días ──────────────────────────────────────────────
    try:
        rows = conn.execute(
            """SELECT id, email, name, trial_ends_at FROM users
                WHERE trial_ends_at IS NOT NULL
                  AND credit_active_until = trial_ends_at
                  AND trial_ends_at > ? AND trial_ends_at <= ?""",
            (now.isoformat(), (now + timedelta(days=2)).isoformat()),
        ).fetchall()
    except Exception as ex:
        log.error("trial mails (ending_soon) falló: %s", ex)
        rows = []
    for r in rows:
        if _already_sent(conn, r["id"], MAIL_ENDING_SOON):
            continue
        with conn:
            if not _mark_sent(conn, r["id"], MAIL_ENDING_SOON):
                continue
        try:
            # Mismo helper que la app: si acá truncábamos y allá redondeábamos
            # para arriba, el mismo día el mail decía "te queda 1" y la barra
            # "te quedan 2".
            emails.send_trial_ending_soon(to=r["email"], user_name=_name(r),
                                          days_left=dias_restantes(r["trial_ends_at"], now))
            sent += 1
        except Exception as ex:
            log.warning("mail trial ending_soon falló uid=%s: %s", r["id"], ex)

    # ── día 16: terminó (el crédito ya venció; el tier lo bajó el otro paso) ─
    try:
        rows = conn.execute(
            # El guard de credit_active_until faltaba acá (las otras dos
            # ventanas sí lo tienen): sin él, a quien terminó el trial y después
            # recibió un regalo de Pro le llegaba "tu cuenta volvió a Free"
            # empujándolo a pagar algo que ya tenía (audit 2026-08-10).
            """SELECT id, email, name FROM users
                WHERE trial_ends_at IS NOT NULL AND trial_ends_at <= ?
                  AND trial_ends_at > ?
                  AND (credit_active_until IS NULL
                       OR credit_active_until <= ?
                       OR credit_active_until = trial_ends_at)
                  AND NOT EXISTS (SELECT 1 FROM subscriptions s
                                   WHERE s.user_id = users.id AND s.status='authorized')""",
            (now.isoformat(), (now - timedelta(days=7)).isoformat(), now.isoformat()),
        ).fetchall()
    except Exception as ex:
        log.error("trial mails (ended) falló: %s", ex)
        rows = []
    for r in rows:
        if _already_sent(conn, r["id"], MAIL_ENDED):
            continue
        with conn:
            if not _mark_sent(conn, r["id"], MAIL_ENDED):
                continue
        try:
            emails.send_trial_ended(to=r["email"], user_name=_name(r),
                                    stats=_trial_stats(conn, r["id"]))
            sent += 1
        except Exception as ex:
            log.warning("mail trial ended falló uid=%s: %s", r["id"], ex)

    if sent:
        log.info("avisos de trial enviados: %d", sent)
    return sent


# ─── Medición ───────────────────────────────────────────────────────────────
# Sin esto no se puede saber si el trial convierte o solo está regalando Pro.
# No hace falta instrumentar eventos nuevos: todo sale de lo que ya se guarda
# (trial_started_at, subscriptions, brokers, operations, ai_usage_daily).
#
# Las dos preguntas que importan, en este orden:
#   1. ¿USARON la app durante el trial? Un trial sin uso no falló al convertir:
#      falló antes, y el problema es el onboarding, no el precio.
#   2. De los que la usaron, ¿cuántos pagaron y cuándo?

def funnel(conn, days: int = 90) -> dict:
    """Embudo del trial de los últimos `days` días."""
    since = (datetime.utcnow() - timedelta(days=max(1, days))).isoformat()
    now = datetime.utcnow().isoformat()

    def _one(sql, params=()):
        try:
            r = conn.execute(sql, params).fetchone()
            return int(r[0] if not hasattr(r, "keys") else r["c"]) if r else 0
        except Exception as ex:
            log.warning("funnel query falló: %s", ex)
            return 0

    activados = _one(
        "SELECT COUNT(*) c FROM users WHERE trial_started_at >= ?", (since,))

    # Importó DESPUÉS de activar: es la señal de que la app tiene datos adentro.
    # Las fechas se normalizan a 'YYYY-MM-DD HH:MM:SS': import_batches guarda al
    # segundo y el trial con microsegundos, así que comparadas crudas TODO lo del
    # mismo día quedaba afuera — y el día 0 es donde más imports hay, porque el
    # trial se ofrece justo al terminar uno (audit 2026-08-10).
    # Sin esto el trial corre sobre una app vacía y no demuestra nada.
    importaron = _one(
        """SELECT COUNT(DISTINCT u.id) c FROM users u
            JOIN import_batches b ON b.user_id = u.id
           WHERE u.trial_started_at >= ? AND b.status='confirmed'
             AND b.created_at >= substr(replace(u.trial_started_at,'T',' '),1,19)""", (since,))

    # Usó la IA durante el trial (la razón principal para pasarse a un plan pago).
    usaron_ia = _one(
        """SELECT COUNT(DISTINCT u.id) c FROM users u
            JOIN ai_usage_daily a ON a.user_id = u.id
           WHERE u.trial_started_at >= ?
             AND a.date >= date(u.trial_started_at)
             AND COALESCE(a.analyses_count,0) + COALESCE(a.chat_count,0) > 0""", (since,))

    # Convirtió = se suscribió DESPUÉS de arrancar el trial.
    convirtieron = _one(
        """SELECT COUNT(DISTINCT u.id) c FROM users u
            JOIN subscriptions s ON s.user_id = u.id
           WHERE u.trial_started_at >= ?
             AND s.created_at >= substr(replace(u.trial_started_at,'T',' '),1,19)
             AND s.status IN ('authorized','cancelled','superseded')""", (since,))

    en_curso = _one(
        """SELECT COUNT(*) c FROM users
            WHERE trial_started_at >= ? AND trial_ends_at > ?""", (since, now))
    terminados = max(0, activados - en_curso)

    # Conversiones SOLO de los que ya terminaron: el numerador y el denominador
    # tienen que hablar de la misma gente. Mezclarlos daba más de 100% justo
    # cuando el trial funciona bien —mucha conversión temprana— que es cuando
    # más se mira el número (audit 2026-08-10).
    convirtieron_cerrados = _one(
        """SELECT COUNT(DISTINCT u.id) c FROM users u
            JOIN subscriptions s ON s.user_id = u.id
           WHERE u.trial_started_at >= ? AND u.trial_ends_at <= ?
             AND s.created_at >= substr(replace(u.trial_started_at,'T',' '),1,19)
             AND s.status IN ('authorized','cancelled','superseded')""", (since, now))

    # ¿En qué momento pagan? Dice si conviene mover el corte de Pro o los avisos.
    etapas = {"durante_pro": 0, "durante_plus": 0, "despues": 0}
    try:
        for r in conn.execute(
            """SELECT u.trial_started_at ini, MIN(s.created_at) pago
                 FROM users u JOIN subscriptions s ON s.user_id = u.id
                WHERE u.trial_started_at >= ?
                  AND s.created_at >= substr(replace(u.trial_started_at,'T',' '),1,19)
                  AND s.status IN ('authorized','cancelled','superseded')
                GROUP BY u.id""", (since,)):
            try:
                d = (datetime.fromisoformat(str(r["pago"]).replace("Z", ""))
                     - datetime.fromisoformat(str(r["ini"]).replace("Z", ""))).days
            except (TypeError, ValueError):
                continue
            if d < TRIAL_PRO_DAYS:
                etapas["durante_pro"] += 1
            elif d < TRIAL_TOTAL_DAYS:
                etapas["durante_plus"] += 1
            else:
                etapas["despues"] += 1
    except Exception as ex:
        log.warning("funnel etapas falló: %s", ex)

    def _pct(n, base):
        return round(n / base * 100, 1) if base else None

    return {
        "days": days,
        "activados": activados,
        "en_curso": en_curso,
        "terminados": terminados,
        "importaron": importaron,
        "usaron_ia": usaron_ia,
        "convirtieron": convirtieron,
        # Sobre los ACTIVADOS: cuánto del embudo se pierde en cada paso.
        "pct_importaron": _pct(importaron, activados),
        "pct_usaron_ia": _pct(usaron_ia, activados),
        "pct_convirtieron": _pct(convirtieron, activados),
        # La tasa que de verdad mide el trial: sobre los que lo TERMINARON
        # (los que están en curso todavía no tuvieron su chance de decidir).
        "convirtieron_cerrados": convirtieron_cerrados,
        "pct_conversion_cerrada": _pct(convirtieron_cerrados, terminados),
        "cuando_pagan": etapas,
        "enabled": trials_enabled(),
        "monthly_cap": monthly_cap(),
        "activados_este_mes": _activations_this_month(conn),
    }
