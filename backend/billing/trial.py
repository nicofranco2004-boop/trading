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
TRIAL_PRO_DAYS = 10         # días en Pro
TRIAL_PLUS_DAYS = 10        # días en Plus, después de Pro
TRIAL_TOTAL_DAYS = TRIAL_PRO_DAYS + TRIAL_PLUS_DAYS   # 20

# ⚠️ Estos tres números NO se escriben en ningún otro lugar. Antes eran 7+8=15,
# cuando la prueba era un extra opcional encima del plan gratis. Desde el
# 2026-10-15 la prueba ES la puerta de entrada (no hay plan gratis para quien se
# registra), así que pasó a 10+10=20. Cualquier cosa que diga "15 días", "7 días
# de Pro" o "una semana de Pro" en un texto, un mail o un test está midiendo con
# la regla vieja: derivar de acá, nunca escribir el número.


def paywall_nuevos() -> bool:
    """¿Los que se registran de ahora en adelante nacen SIN plan gratis?

    True (el default desde el 2026-10-15) = al verificar el mail se les arranca
    la prueba de 20 días sola, y cuando se termina la cuenta queda en pausa
    hasta que elijan un plan. El plan gratis deja de existir para ellos.

    La válvula de escape es `PAYWALL_NUEVOS=0` en Railway: apaga el cambio para
    los registros NUEVOS sin tocar a nadie que ya lo tenga marcado. Se apaga
    en caliente si algo sale mal el día del cambio; no hay que redeployar.

    A los que ya existen NO les toca nada: su marca (`users.requires_plan`) se
    escribe en el registro, y pasarlos a todos es un UPDATE aparte el día que
    Nico decida hacerlo retroactivo.
    """
    return (os.environ.get("PAYWALL_NUEVOS") or "1").strip() not in ("0", "false", "False", "no")


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
    # Por FECHA, no por instante: tiene que dar el mismo resultado que el corte
    # que EJECUTA el cambio (step_down_due_trials, que compara date(...)). Con
    # el corte por instante, el día 7 el cron de la madrugada baja a Plus a toda
    # la cohorte de una, pero esta función seguía diciendo 'pro' hasta la hora
    # exacta en que cada uno había apretado el botón: el panel del dueño decía
    # "12 en la semana de Pro" mientras las 12 personas ya tenían Plus en su
    # app. Reproducido con la cohorte del día 7 hora por hora.
    hoy = (now or datetime.utcnow()).date()
    return "pro" if (hoy - ini.date()).days < TRIAL_PRO_DAYS else "plus"


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

    # ⚠️ Los dos frenos de abajo son frenos de PROMOCIÓN: existen porque el trial
    # nació como un extra opcional encima del plan gratis, y el peor caso de
    # frenarlo era que alguien siguiera gratis. Para quien nace SIN plan gratis
    # (`requires_plan`) el peor caso es el opuesto: sin prueba no tiene NADA, y
    # la pantalla de "elegí un plan" le aparecería el día que se registra, antes
    # de haber visto un solo número suyo en Rendi. Para ellos la prueba no es una
    # promoción: es la única puerta de entrada, y no se puede cerrar por un tope
    # mensual ni por un interruptor de campaña.
    if bool(g("requires_plan")):
        return {"can_start": True, "reason": None}

    if not trials_enabled():
        return {"can_start": False, "reason": "disabled"}
    cap = monthly_cap()
    if cap and _activations_this_month(conn) >= cap:
        return {"can_start": False, "reason": "monthly_cap_reached"}
    return {"can_start": True, "reason": None}


def _requiere_plan(conn, user_id: int) -> bool:
    """¿Este usuario nació sin plan gratis? (users.requires_plan)

    Tolera que la columna no exista todavía: una base que no corrió la
    migración responde False, o sea "como siempre".
    """
    try:
        row = conn.execute(
            "SELECT requires_plan FROM users WHERE id=?", (user_id,)).fetchone()
        return bool(row and row["requires_plan"])
    except Exception:
        return False


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
    # El tope del mes se chequea DOS veces: en eligibility() y otra vez adentro
    # de _start_tx, que es el que cuenta de verdad (corre en la transacción, a
    # prueba de dos altas simultáneas). Eximir sólo eligibility dejaba el
    # arreglo a medias: el alta seguía muriendo adentro con _TopeDelMes. Se
    # neutraliza en el ÚNICO lugar donde se decide el cap del alta — acá — y
    # `_start_tx` ya trata cap=0 como "sin tope".
    cap = 0 if _requiere_plan(conn, user_id) else monthly_cap()
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

# Cuántos días antes del final sale el aviso de "elegí un plan". Eran 2 (escrito
# a mano en el timedelta de la consulta Y en el default del mail, en dos
# archivos distintos). Con la prueba de 20 días pasa a 3: es el mail que más
# convierte y 48 horas es poco margen para decidir un gasto mensual.
MAIL_AVISO_DIAS_ANTES = 3


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
    #
    # Fuera del loop porque cuenta CUENTAS, no filas: el sub-broker "· USD" que
    # crea el importador solo no es un broker que el usuario haya conectado, y
    # éste es justo el mail que empuja a pagar. Decía "2 brokers" a quien
    # conectó 1. Misma definición que la cuota del plan, a propósito.
    try:
        from ai import plan as _plan
        n_brokers = _plan.count_broker_accounts(conn, user_id)
        if n_brokers:
            out["brokers"] = n_brokers
    except Exception:
        pass
    for key, sql, params in (
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

    # ── la víspera del paso a Plus (solo a quien SIGUE en la etapa Pro) ────
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
                                         plus_days=TRIAL_PLUS_DAYS,
                                         pro_days=TRIAL_PRO_DAYS)
            sent += 1
        except Exception as ex:
            log.warning("mail trial pro_ending falló uid=%s: %s", r["id"], ex)

    # ── el aviso de MAIL_AVISO_DIAS_ANTES días antes del final ─────────────
    try:
        rows = conn.execute(
            """SELECT id, email, name, trial_ends_at, requires_plan FROM users
                WHERE trial_ends_at IS NOT NULL
                  AND credit_active_until = trial_ends_at
                  AND trial_ends_at > ? AND trial_ends_at <= ?""",
            (now.isoformat(),
             (now + timedelta(days=MAIL_AVISO_DIAS_ANTES)).isoformat()),
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
            emails.send_trial_ending_soon(
                to=r["email"], user_name=_name(r),
                days_left=dias_restantes(r["trial_ends_at"], now),
                requiere_plan=bool(r["requires_plan"]))
            sent += 1
        except Exception as ex:
            log.warning("mail trial ending_soon falló uid=%s: %s", r["id"], ex)

    # ── terminó (el crédito ya venció; el tier lo bajó el otro paso) ───────
    try:
        rows = conn.execute(
            # El guard de credit_active_until faltaba acá (las otras dos
            # ventanas sí lo tienen): sin él, a quien terminó el trial y después
            # recibió un regalo de Pro le llegaba "tu cuenta volvió a Free"
            # empujándolo a pagar algo que ya tenía (audit 2026-08-10).
            """SELECT id, email, name, requires_plan FROM users
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
                                    stats=_trial_stats(conn, r["id"]),
                                    total_days=TRIAL_TOTAL_DAYS,
                                    requiere_plan=bool(r["requires_plan"]))
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

# ─── Probar Pro sin dejar el plan que ya se paga ────────────────────────────

PRO_UPSELL_DAYS = 7    # al que ya paga no hay que convencerlo de que la app sirve


def pro_upsell_eligibility(conn, user_id: int) -> dict:
    """¿Puede probar Pro por encima de su plan pago?

    Es para el suscriptor de PLUS: ya demostró que paga y ya usa la app, así
    que es el mejor candidato que hay para Pro — y hasta ahora era justo el
    único al que no se le ofrecía nada. El trial normal lo excluye con razón
    (le pisaría la ventana que compró); esto es otro mecanismo.

    No aplica a: quien ya está en Pro (no hay nada que mostrarle), quien no
    paga (ése tiene el trial normal), admin, asesor y cuentas administradas.
    """
    try:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    except Exception as ex:
        log.warning("pro_upsell_eligibility falló uid=%s: %s", user_id, ex)
        return {"can_start": False, "reason": "unknown_user"}
    if not row:
        return {"can_start": False, "reason": "unknown_user"}
    k = row.keys()

    def g(c, d=None):
        return row[c] if c in k else d

    if g("pro_trial_used_at"):
        return {"can_start": False, "reason": "already_used"}
    if bool(g("is_admin")):
        return {"can_start": False, "reason": "not_applicable"}
    tier = (g("tier") or "").strip().lower()
    if tier == "advisor" or g("managed_by") is not None:
        return {"can_start": False, "reason": "not_applicable"}
    if not trials_enabled():
        return {"can_start": False, "reason": "disabled"}
    # Ya lo está usando.
    hasta = g("pro_trial_until")
    if hasta and str(hasta) > datetime.utcnow().isoformat():
        return {"can_start": False, "reason": "already_active"}
    # Tiene que estar PAGANDO un plan por debajo de Pro. Se mira el crédito con
    # anchor —el plan pago de verdad— y no users.tier, que durante el trial
    # normal dice 'pro' sin que nadie haya pagado nada.
    if not credit_is_trial(g("credit_active_until"), g("trial_ends_at")):
        anchor = (g("credit_anchor_plan") or "").strip().lower()
        cau = g("credit_active_until")
        vigente = bool(cau and str(cau) > datetime.utcnow().isoformat())
        if vigente and anchor == "plus":
            return {"can_start": True, "reason": None}
        if vigente and anchor == "pro":
            return {"can_start": False, "reason": "already_pro"}
    return {"can_start": False, "reason": "not_paying"}


def start_pro_upsell(conn, user_id: int) -> dict:
    """Le da PRO_UPSELL_DAYS días de Pro SIN tocar su plan pago.

    No se escribe users.tier, ni credit_active_until, ni los anchors: su
    suscripción, su fecha de renovación y su crédito quedan exactamente igual.
    Cuando la fecha pasa, get_tier deja de devolver 'pro' y vuelve a su Plus
    solo — sin cron, sin nada que reparar.

    El UPDATE es condicional sobre pro_trial_used_at IS NULL: dos requests
    simultáneos activan UNA sola vez.
    """
    el = pro_upsell_eligibility(conn, user_id)
    if not el.get("can_start"):
        return {"ok": False, **el}
    ahora = datetime.utcnow()
    hasta = ahora + timedelta(days=PRO_UPSELL_DAYS)
    try:
        with conn:
            cur = conn.execute(
                """UPDATE users SET pro_trial_until=?, pro_trial_used_at=?
                    WHERE id=? AND pro_trial_used_at IS NULL""",
                (hasta.isoformat(), ahora.isoformat(), user_id))
            if not cur.rowcount:
                return {"ok": False, "can_start": False, "reason": "already_used"}
    except Exception as ex:
        log.error("start_pro_upsell falló uid=%s: %s", user_id, ex)
        return {"ok": False, "can_start": False, "reason": "error"}
    # El corte de la ventana de cuota, para que su consumo de Plus no le coma
    # la cuota de Pro que le acabamos de dar.
    try:
        from ai import quota as _q
        _q.note_tier_change(conn, user_id)
    except Exception as ex:
        log.warning("pro upsell: no se pudo marcar el corte de cuota uid=%s: %s", user_id, ex)
    log.info("pro upsell activado uid=%s hasta=%s", user_id, hasta.isoformat())
    return {"ok": True, **pro_upsell_status(conn, user_id)}


def pro_upsell_status(conn, user_id: int) -> dict:
    """Estado para la UI: {active, used, can_start, days_left, ends_at, days}."""
    out = {"active": False, "used": False, "can_start": False,
           "days_left": None, "ends_at": None, "days": PRO_UPSELL_DAYS}
    try:
        row = conn.execute(
            "SELECT pro_trial_until, pro_trial_used_at FROM users WHERE id=?",
            (user_id,)).fetchone()
    except Exception:
        return out
    if not row:
        return out
    out["used"] = bool(row["pro_trial_used_at"])
    hasta = row["pro_trial_until"]
    ahora = datetime.utcnow()
    if hasta:
        try:
            fin = datetime.fromisoformat(str(hasta).replace("Z", ""))
        except (TypeError, ValueError):
            fin = None
        if fin and fin > ahora:
            out["active"] = True
            out["ends_at"] = str(hasta)
            # Por la definición única: la barra de la app y cualquier otro
            # lector tienen que decir el mismo número.
            out["days_left"] = dias_restantes(fin, ahora)
    if not out["active"]:
        out["can_start"] = bool(pro_upsell_eligibility(conn, user_id).get("can_start"))
    return out


def prueba_viva(conn, row, ahora=None):
    """¿Esta persona está PROBANDO ahora mismo? Devuelve cuándo se le termina,
    o None si no.

    Es el corte que usa la app para decidir si le muestra la barra de "estás
    probando Rendi Pro", y son tres preguntas, no una:

      1. ¿el crédito que tiene vigente es el de la prueba? (`credit_is_trial`)
         — el que compró un plan tiene crédito, pero no es el de la prueba;
      2. ¿no se venció todavía?
      3. ¿no pagó? — el que activó la prueba y a los dos días pagó conserva su
         `trial_ends_at` futuro, así que por fecha sigue "en curso" cuando ya
         es un cliente. Contarlo como que está probando mezcla a los que
         todavía no decidieron con los que ya decidieron que sí.

    Vive acá y no adentro de activos() porque el panel de seguimiento tiene que
    hacerse la misma pregunta: con el corte escrito dos veces, alcanza con que
    alguien toque uno para que los dos paneles cuenten poblaciones distintas y
    nada avise.
    """
    ahora = ahora or datetime.utcnow()
    if not credit_is_trial(row["credit_active_until"], row["trial_ends_at"]):
        return None
    try:
        fin = datetime.fromisoformat(str(row["trial_ends_at"]).replace("Z", ""))
    except (TypeError, ValueError):
        return None
    if fin <= ahora:
        return None
    if _has_paid_sub(conn, row["id"]):
        return None
    return fin


def activos(conn, limit: int = 200) -> dict:
    """Quiénes tienen la prueba corriendo AHORA MISMO, con nombre y apellido.

    El embudo ya traía `en_curso`, pero ese número cuenta por `trial_ends_at >
    ahora` y NO pregunta si el crédito sigue siendo el del trial. Alguien que
    activó la prueba y a los dos días PAGÓ conserva su trial_ends_at futuro, así
    que seguía contando como "en curso" cuando ya es un cliente pago: el número
    mezclaba a los que están probando con los que ya decidieron.

    Acá el corte es `credit_is_trial` —el mismo discriminador que usan
    status(), el step-down y restore-tier— más que no haya vencido y que no
    tenga una suscripción paga. Es la misma pregunta que se hace la app para
    decidir si le muestra la barra de "estás probando Rendi Pro".

    La etapa sale del CALENDARIO (stage_by_calendar), no de users.tier: si el
    cron todavía no corrió, el tier dice 'pro' pero por calendario ya le toca
    Plus, y para mirar la población desde afuera importa dónde va cada uno.
    """
    ahora = datetime.utcnow()
    salida = {"total": 0, "en_pro": 0, "en_plus": 0, "usuarios": []}
    try:
        filas = conn.execute(
            """SELECT id, email, name, trial_started_at, trial_ends_at,
                      credit_active_until
                 FROM users
                WHERE trial_started_at IS NOT NULL
                  AND trial_ends_at IS NOT NULL
                ORDER BY trial_ends_at ASC""").fetchall()
    except Exception as ex:
        log.warning("activos: no se pudo leer la tabla: %s", ex)
        return salida

    for r in filas:
        fin = prueba_viva(conn, r, ahora)
        if not fin:
            continue
        etapa = stage_by_calendar(r["trial_started_at"], ahora)
        salida["total"] += 1
        salida["en_plus" if etapa == "plus" else "en_pro"] += 1
        if len(salida["usuarios"]) < max(1, limit):
            salida["usuarios"].append({
                "id": r["id"],
                "email": r["email"],
                "name": r["name"],
                "stage": etapa,
                # Por la definición única (`dias_restantes`), para que la
                # barra de la app, el mail y este panel no digan números
                # distintos sobre la misma persona el mismo día.
                "days_left": dias_restantes(fin, ahora),
                "ends_at": r["trial_ends_at"],
            })
    return salida


def pro_upsell_stats(conn, days: int = 90, limit: int = 200) -> dict:
    """La prueba de Pro sobre un plan pago, medida aparte del free trial.

    Va separada a propósito: son dos preguntas distintas. En el trial la
    conversión es "¿pasó a pagar algo?"; acá el que prueba YA PAGA, así que la
    pregunta es "¿subió de Plus a Pro?". Sumarlas en un solo número borraría
    las dos.

    El upgrade se detecta en el credit_ledger (`to_plan='pro'` después de haber
    activado la prueba), que es donde queda registrado tanto el cambio de plan
    como un pago nuevo de Pro. Igual que en el embudo: se le pregunta al ledger
    y no a `subscriptions`, donde hay fila desde que se genera el link de pago.
    """
    desde = (datetime.utcnow() - timedelta(days=max(1, days))).isoformat()
    ahora = datetime.utcnow()
    # `days` es la VENTANA que se mira hacia atrás; `dias_prueba` es cuánto dura
    # la prueba. Nombrarlas igual es cómo el panel termina diciendo "90 días de
    # Pro" en vez de 7.
    out = {"days": days, "dias_prueba": PRO_UPSELL_DAYS,
           "activaron": 0, "activos": 0, "terminados": 0,
           "subieron_a_pro": 0, "pct_upgrade": None, "usuarios": []}

    def _uno(sql, params=()):
        try:
            r = conn.execute(sql, params).fetchone()
            return int(r["c"]) if r else 0
        except Exception as ex:
            log.warning("pro_upsell_stats falló: %s", ex)
            return 0

    out["activaron"] = _uno(
        "SELECT COUNT(*) c FROM users WHERE pro_trial_used_at >= ?", (desde,))
    out["subieron_a_pro"] = _uno(
        """SELECT COUNT(DISTINCT u.id) c FROM users u
             JOIN credit_ledger l ON l.user_id = u.id AND l.to_plan = 'pro'
            WHERE u.pro_trial_used_at >= ?
              AND l.created_at >= substr(replace(u.pro_trial_used_at,'T',' '),1,19)""",
        (desde,))

    # Quiénes la tienen corriendo AHORA (no depende de la ventana de días: es
    # una foto del presente, igual que `activos` del trial).
    try:
        filas = conn.execute(
            """SELECT id, email, name, pro_trial_until, credit_anchor_plan
                 FROM users
                WHERE pro_trial_until IS NOT NULL
                ORDER BY pro_trial_until ASC""").fetchall()
    except Exception as ex:
        log.warning("pro_upsell_stats: no se pudo leer la tabla: %s", ex)
        filas = []
    for r in filas:
        try:
            fin = datetime.fromisoformat(str(r["pro_trial_until"]).replace("Z", ""))
        except (TypeError, ValueError):
            continue
        if fin <= ahora:
            continue
        out["activos"] += 1
        if len(out["usuarios"]) < max(1, limit):
            out["usuarios"].append({
                "id": r["id"], "email": r["email"], "name": r["name"],
                "plan": (r["credit_anchor_plan"] or "plus"),
                "days_left": dias_restantes(fin, ahora),
                "ends_at": r["pro_trial_until"],
            })
    out["terminados"] = max(0, out["activaron"] - out["activos"])
    # La tasa sobre los que ya TERMINARON: el que sigue probando todavía no
    # tuvo su chance de decidir. Mismo criterio que la del trial.
    if out["terminados"]:
        subieron_cerrados = _uno(
            """SELECT COUNT(DISTINCT u.id) c FROM users u
                 JOIN credit_ledger l ON l.user_id = u.id AND l.to_plan = 'pro'
                WHERE u.pro_trial_used_at >= ? AND u.pro_trial_until <= ?
                  AND l.created_at >= substr(replace(u.pro_trial_used_at,'T',' '),1,19)""",
            (desde, ahora.isoformat()))
        out["pct_upgrade"] = round(subieron_cerrados / out["terminados"] * 100, 1)
    return out


# ⭐ QUÉ ES "CONVERTIR". Una sola definición para todo el admin.
#
# Es ENTRÓ PLATA después de arrancar la prueba, y la fuente es
# `credit_ledger` con kind='payment', que sólo tiene fila cuando se acreditó un
# cobro de verdad. NO se le pregunta a `subscriptions`: ahí hay fila desde que
# se GENERA EL LINK de pago, y el cron la pasa a 'cancelled' a los 7 días — o
# sea que 'cancelled' es el estado final de un CHECKOUT ABANDONADO, no de
# alguien que pagó y se dio de baja. Reproducido: 3 personas que abrieron el
# link y nunca pagaron + 1 que pagó daban "convirtieron 4, conversión 100%"
# cuando la respuesta es 1 y 25%.
#
# Están acá arriba y no adentro de funnel() porque el panel de pruebas cuenta
# la misma conversión: con la definición escrita dos veces, los dos números se
# separan el día que alguien toque uno y nada avisa.
def _pct(n, base):
    """Porcentaje con un decimal, o None si no hay de qué sacarlo. Nunca 0%
    cuando el denominador es cero: "0%" y "todavía no hay nadie" son cosas
    distintas y la pantalla tiene que poder distinguirlas."""
    return round(n / base * 100, 1) if base else None


SQL_JOIN_PAGO = """JOIN credit_ledger l ON l.user_id = u.id AND l.kind='payment'"""
SQL_PAGO_DESPUES_DE_ARRANCAR = (
    """l.created_at >= substr(replace(u.trial_started_at,'T',' '),1,19)""")


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
    # La ventana es el DÍA del arranque, no el instante. El botón estrella del
    # trial vive en la pantalla de "importación terminada" (es el mejor momento:
    # la cartera acaba de entrar), así que por ese camino el batch se crea
    # SIEMPRE unos minutos ANTES de que exista trial_started_at — y quedaba
    # excluido por definición justo el caso más común. La pregunta que el panel
    # quiere contestar es "¿la prueba corrió sobre una app con datos?", no
    # "¿importó después del click?".
    importaron = _one(
        """SELECT COUNT(DISTINCT u.id) c FROM users u
            JOIN import_batches b ON b.user_id = u.id
           WHERE u.trial_started_at >= ? AND b.status='confirmed'
             AND substr(b.created_at,1,10)
                 >= substr(replace(u.trial_started_at,'T',' '),1,10)""", (since,))

    # Usó la IA durante el trial (la razón principal para pasarse a un plan pago).
    #
    # Se cuenta desde el día SIGUIENTE al arranque, y se pierde a propósito el
    # uso del día 0: ai_usage_daily agrega POR DÍA y no guarda hora, así que la
    # fila del día del arranque mezcla lo de antes y lo de después de apretar el
    # botón. Y el camino más común es justamente ese —gastar el análisis
    # semanal de Free, chocar con el paywall y activar la prueba ahí mismo—;
    # tanto, que start() resetea la ventana de cuota por ese motivo. Contando
    # el día 0 daba "100% usó la IA" con gente que no la tocó ni una vez ya en
    # la prueba. Preferimos quedarnos cortos: un número que sobra hace creer que
    # el trial funciona cuando no, y esa es la equivocación cara.
    usaron_ia = _one(
        """SELECT COUNT(DISTINCT u.id) c FROM users u
            JOIN ai_usage_daily a ON a.user_id = u.id
           WHERE u.trial_started_at >= ?
             AND a.date > date(u.trial_started_at)
             AND COALESCE(a.analyses_count,0) + COALESCE(a.chat_count,0) > 0""", (since,))

    # ⭐ Convirtió = ENTRÓ PLATA después de arrancar el trial.
    #
    # La fuente es credit_ledger kind='payment', que solo tiene fila cuando
    # grant_payment_credit acreditó un cobro. Antes se le preguntaba a
    # `subscriptions`, y ahí hay fila desde que se GENERA EL LINK de pago:
    # /api/billing/subscribe inserta 'pending' antes de que entre un peso, y el
    # cron diario _cancel_stale_pending pasa esa fila a 'cancelled' a los 7
    # días. O sea que 'cancelled' es el estado final de un CHECKOUT ABANDONADO,
    # no de alguien que pagó y se dio de baja. Reproducido: 3 personas que
    # abrieron el link y nunca pagaron + 1 que pagó de verdad daban
    # "convirtieron 4, conversión 100%" cuando la respuesta es 1 y 25%.
    # Abandonar un checkout es lo más común que hay, así que el error no era de
    # borde: inflaba justo el número con el que se decide escalar el gasto.
    _PAGO, _DESPUES = SQL_JOIN_PAGO, SQL_PAGO_DESPUES_DE_ARRANCAR
    convirtieron = _one(
        f"""SELECT COUNT(DISTINCT u.id) c FROM users u {_PAGO}
            WHERE u.trial_started_at >= ? AND {_DESPUES}""", (since,))

    en_curso = _one(
        """SELECT COUNT(*) c FROM users
            WHERE trial_started_at >= ? AND trial_ends_at > ?""", (since, now))
    terminados = max(0, activados - en_curso)

    # Conversiones SOLO de los que ya terminaron: el numerador y el denominador
    # tienen que hablar de la misma gente. Mezclarlos daba más de 100% justo
    # cuando el trial funciona bien —mucha conversión temprana— que es cuando
    # más se mira el número (audit 2026-08-10).
    convirtieron_cerrados = _one(
        f"""SELECT COUNT(DISTINCT u.id) c FROM users u {_PAGO}
            WHERE u.trial_started_at >= ? AND u.trial_ends_at <= ?
              AND {_DESPUES}""", (since, now))

    # ¿En qué momento pagan? Dice si conviene mover el corte de Pro o los avisos.
    #
    # La fecha sale del ledger y no de subscriptions.created_at, que es cuándo
    # se generó el LINK y no cuándo se pagó: el webhook actualiza esa fila a
    # 'authorized' sin tocar created_at, así que alguien que abrió el checkout
    # el día 13 y pagó el 20 —ya terminado el trial— figuraba como "pagó durante
    # los días de Plus". Reproducido.
    etapas = {"durante_pro": 0, "durante_plus": 0, "despues": 0}
    try:
        for r in conn.execute(
            f"""SELECT u.trial_started_at ini, MIN(l.created_at) pago
                 FROM users u {_PAGO}
                WHERE u.trial_started_at >= ? AND {_DESPUES}
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
        # QUIÉNES la tienen corriendo ahora. `en_curso` de arriba cuenta por
        # fecha y se lleva puestos a los que ya pagaron; esto usa el mismo
        # criterio que la app para decidir si sigue siendo una prueba.
        "activos": activos(conn),
        # La prueba de Pro sobre un plan pago: otro mecanismo, otra pregunta.
        # Sin esto, quien la activaba no figuraba en NINGÚN lado del panel — el
        # embudo se alimenta de trial_started_at y el upsell ni lo escribe.
        "pro_upsell": pro_upsell_stats(conn, days),
        "enabled": trials_enabled(),
        "monthly_cap": monthly_cap(),
        "activados_este_mes": _activations_this_month(conn),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SEGUIMIENTO: ¿se nota el progreso de cada prueba?
# ═══════════════════════════════════════════════════════════════════════════
# El embudo de arriba cuenta cabezas: cuántos activaron, cuántos importaron,
# cuántos pagaron. Contesta "¿la prueba funciona?" pero no contesta "¿ESTA
# persona está enganchando?" — que es la única pregunta que se puede mirar
# MIENTRAS la prueba corre, o sea cuando todavía se puede hacer algo.
#
# ⚠️ DE DÓNDE SALE CADA NÚMERO, porque no todo lo que se carga queda fechado:
#
#  · Lo que entra por IMPORTACIÓN sí. `import_batches` guarda cuándo se
#    confirmó el archivo y `import_op_links` ata cada posición y cada operación
#    creada a ese archivo. Es exacto, y —esto es lo que importa— sobrevive a
#    los recálculos: el rebuild borra y rehace las ventas, pero las vuelve a
#    atar al MISMO lote, cuya fecha nadie toca. Si en cambio fechásemos las
#    filas con una columna propia, cualquier backfill administrativo
#    restamparía media base y el panel mostraría un pico de actividad que no
#    pasó nunca.
#  · Lo cargado A MANO no. `positions` y `operations` no tienen columna de
#    "cuándo se creó esta fila", y ponérsela es tocar los 330 lugares que
#    insertan ahí. Así que de lo cargado a mano se muestra el TOTAL, y nunca
#    repartido por día: fechar esas filas sería inventar.
#  · La IA se guarda POR DÍA (`ai_usage_daily` no tiene hora), así que la
#    ventana de 1 día es el día de HOY en UTC, no las últimas 24 horas.
#
# ⏰ LOS TRES RELOJES SON EL MISMO, y está verificado y no supuesto: los lotes y
# los logins se fechan con el DEFAULT de la base (`now() at time zone 'utc'`),
# `ai_usage_daily.date` con `date.today()` del proceso —que en Railway es UTC—
# y esta función con `datetime.utcnow()`. Si alguno pasara a hora argentina,
# su actividad caería hasta 3 horas corrida de bucket y las noches argentinas
# aparecerían en el día siguiente: mirar esto ANTES de explicar un número raro.
#
# Las ventanas son días de calendario en UTC terminando hoy, y se calculan
# sobre el MISMO array de días que dibuja la tira de la pantalla. Una sola
# fuente para las dos vistas: el número de la tabla y el dibujo no pueden
# discrepar.

# Cuántos días mira cada ventana. Cambiar esto cambia la tabla Y la pantalla:
# el frontend las lee de la respuesta, no las tiene escritas.
VENTANAS_PROGRESO = (1, 3, 7, 15)

# Tope de días que devuelve la tira por persona. La prueba dura
# TRIAL_TOTAL_DAYS; el resto es para ver qué hizo DESPUÉS del vencimiento.
_TOPE_TIRA = 45


def _dia_de(valor):
    """'2026-09-10', salga como salga el timestamp guardado.

    Conviven dos formatos: `datetime.utcnow().isoformat()` escribe con 'T' y
    microsegundos, y los DEFAULT de la base escriben con espacio y al segundo.
    Compararlos crudos deja afuera justo lo del mismo día."""
    if not valor:
        return None
    return str(valor).replace("T", " ")[:10]


def _sql_dia(col: str) -> str:
    """La misma normalización, del lado del SQL."""
    return f"substr(replace({col},'T',' '),1,10)"


def _rango_de_dias(desde: str, hasta: str) -> list:
    """Todos los días entre dos fechas, las dos incluidas, terminando en
    `hasta`. Si no entran en el tope, se recortan los MÁS VIEJOS.

    ⚠️ Recortar por el otro lado es un bug caro y silencioso: las ventanas se
    calculan como "los últimos N días de la tira", así que una tira que arranca
    en el día 1 de una prueba de hace dos meses y se corta a los 45 hace que
    «los últimos 3 días» miren el día 43 de esa prueba. El panel diría "cargó
    90 filas hoy" con una importación de hace dos meses, y al revés: una carga
    de ayer no aparecería en ninguna ventana. Reproducido con la ventana de 90
    días del selector.

    Los días SIN actividad tienen que existir igual: el hueco es el dato."""
    try:
        d = datetime.fromisoformat(str(desde)).date()
        fin = datetime.fromisoformat(str(hasta)).date()
    except (TypeError, ValueError):
        return []
    # El piso: como mucho _TOPE_TIRA días hacia atrás desde el final.
    piso = fin - timedelta(days=_TOPE_TIRA - 1)
    if d < piso:
        d = piso
    dias = []
    while d <= fin:
        dias.append(d.isoformat())
        d += timedelta(days=1)
    return dias


def _dia_vacio() -> dict:
    return {"filas": 0, "archivos": 0, "ia": 0, "entradas": 0}


def _sumar_dias(dias: list) -> dict:
    total = _dia_vacio()
    for d in dias:
        for k in total:
            total[k] += int(d.get(k) or 0)
    # Días DISTINTOS en los que entró, que NO es la cantidad de entradas:
    # alguien que abrió la app seis veces un martes y no volvió usó Rendi un
    # día, no seis. Es la "frecuencia" de la tabla ("6/7 días").
    total["dias_entro"] = sum(1 for d in dias if d.get("entradas"))
    return total


def _hubo_algo(dias: list) -> bool:
    return any(d["filas"] or d["archivos"] or d["ia"] or d["entradas"]
               for d in dias)


def _estado_de_uso(dias: list, tiene_datos: bool) -> str:
    """Una palabra que resume la tira, para no tener que leer 20 celdas.

      · `sin_datos` — nunca entró nada. La prueba está corriendo sobre una app
        vacía, así que no está probando nada: es el peor caso y el más barato
        de arreglar, porque el problema es el onboarding y no el precio.
      · `avanzando` — hubo algo en los últimos 3 días.
      · `tibio`     — hubo algo en los últimos 7, pero nada en los últimos 3.
      · `frenado`   — cargó alguna vez y hace más de una semana que no aparece.
    """
    if not tiene_datos:
        return "sin_datos"
    if _hubo_algo(dias[-3:]):
        return "avanzando"
    if _hubo_algo(dias[-7:]):
        return "tibio"
    return "frenado"


def _orden_fecha(dia) -> int:
    """'2026-09-10' → 20260910, para ordenar sin parsear."""
    try:
        return int(str(dia).replace("-", "")[:8])
    except (TypeError, ValueError):
        return 0


def _brokers_de(conn, uid: int) -> int:
    """Cuántas CUENTAS de broker tiene.

    Va por `count_broker_accounts` y no por un COUNT(*) a `brokers`: el
    sub-broker en dólares es una fila más pero NO es una cuenta más, y el panel
    tiene que decir el mismo número que la persona ve en su Cartera.

    Sí, es una consulta por persona en vez de una agrupada para toda la tanda.
    Es a propósito: agruparla obliga a reescribir la condición acá, y esa
    condición tiene UN solo dueño —`count_broker_accounts`— porque ya pasó que
    dos copias contaran distinto y a alguien le comieran un cupo que pagó. Son
    COUNTs indexados sobre un tope de 200 filas en una pantalla de admin."""
    try:
        from ai.plan import count_broker_accounts
        return int(count_broker_accounts(conn, uid) or 0)
    except Exception as ex:
        log.warning("progreso: brokers de uid=%s falló: %s", uid, ex)
        return 0


def progreso(conn, days: int = 30, limit: int = 200, detalle: bool = False) -> dict:
    """Persona por persona: cuándo arrancó, cuánto le queda y si avanza.

    `days` cuenta hacia atrás desde hoy: entran las pruebas vivas y las que
    terminaron hace menos de eso. Ver a quién se le venció sin pagar es la
    mitad del valor del panel — es la lista de a quién preguntarle por qué.

    `detalle` agrega el array día por día de cada persona. Va apagado por
    defecto y NO cambia ningún número: la tira se construye igual siempre,
    porque las ventanas, la frecuencia y el estado de uso salen de ella. Lo
    único que decide es si se serializa. Medido: con 200 filas de 45 días son
    1,2 MB de respuesta que la tabla no dibuja — la pantalla quedó con columnas
    y no con tiras. Se prende para mirar una prueba en detalle y en el test que
    compara la ventana contra la suma de la tira."""
    ahora = datetime.utcnow()
    hoy = ahora.date().isoformat()
    # `days or 30` convertía un 0 en 30 sin decir nada: pedir "cero días" y
    # recibir un mes es la clase de sorpresa silenciosa que después se lee como
    # un bug de los datos. None sigue siendo el default; el resto se recorta.
    ventana = max(1, min(int(30 if days is None else days), 365))
    corte = (ahora - timedelta(days=ventana)).date().isoformat()

    salida = {
        "days": ventana,
        "hoy": hoy,
        "ventanas": list(VENTANAS_PROGRESO),
        "total_dias": TRIAL_TOTAL_DAYS,
        "dias_pro": TRIAL_PRO_DAYS,
        "activas": 0,
        "total_en_ventana": 0,
        "truncado": False,
        "personas": [],
    }

    try:
        filas = conn.execute(
            f"""SELECT id, email, name, trial_started_at, trial_ends_at,
                       credit_active_until
                  FROM users
                 WHERE trial_started_at IS NOT NULL
                   AND trial_ends_at IS NOT NULL
                   AND {_sql_dia('trial_ends_at')} >= ?
                 ORDER BY trial_ends_at DESC""", (corte,)).fetchall()
    except Exception as ex:
        log.warning("progreso: no se pudo leer la cohorte: %s", ex)
        return salida

    # ⚠️ Si la tanda no entra entera, el resumen se calcula sobre lo que SÍ
    # entró — así que hay que decirlo. Un total que miente por lo bajo sin
    # avisar es peor que no mostrarlo: se toman decisiones con él.
    salida["total_en_ventana"] = len(filas)
    salida["truncado"] = len(filas) > max(1, limit)
    filas = filas[:max(1, limit)]
    if not filas:
        # ⭐ El resumen VACÍO se manda igual. Si faltara, la pantalla no puede
        # distinguir "no hay ninguna prueba todavía" de "el backend no responde
        # este panel" —que es el mensaje que muestra cuando no viene resumen— y
        # esas dos cosas piden acciones opuestas. Por eso la salida por ERROR de
        # arriba sí se va sin resumen: ahí sí está roto.
        salida["resumen"] = _resumen([], set())
        return salida

    ids = [int(r["id"]) for r in filas]
    ph = ",".join("?" for _ in ids)
    # El día más viejo que hay que traer: el arranque de la prueba más antigua
    # de la tanda, pero nunca más atrás de donde empieza la tira — traer meses
    # de actividad que después se descarta es trabajo de la base para nada.
    tope_tira = (ahora.date() - timedelta(days=_TOPE_TIRA - 1)).isoformat()
    primer_dia = max(tope_tira,
                     min((_dia_de(r["trial_started_at"]) or hoy) for r in filas))

    # ── Actividad por persona y por día ─────────────────────────────────────
    # Un diccionario (uid, día) → contadores. Tres consultas para TODA la
    # tanda, no tres por persona: con 40 personas serían 120 consultas.
    act = {}

    def _celda(uid, dia):
        return act.setdefault((int(uid), dia), _dia_vacio())

    _DIA_LOTE = _sql_dia("COALESCE(b.confirmed_at, b.created_at)")
    try:
        # LEFT JOIN a propósito: un archivo que no creó ninguna fila (una foto
        # de tenencia que sólo confirma lo que ya estaba) es actividad igual —
        # la persona entró e hizo algo. Con JOIN normal desaparecía.
        for r in conn.execute(
            f"""SELECT b.user_id uid, {_DIA_LOTE} d,
                       COUNT(DISTINCT b.id) archivos,
                       COUNT(CASE WHEN l.position_id IS NOT NULL
                                    OR l.operation_id IS NOT NULL
                                  THEN 1 END) filas
                  FROM import_batches b
                  LEFT JOIN import_op_links l ON l.batch_id = b.id
                 WHERE b.user_id IN ({ph})
                   AND b.status = 'confirmed'
                   AND {_DIA_LOTE} >= ?
                 GROUP BY b.user_id, {_DIA_LOTE}""", (*ids, primer_dia)):
            c = _celda(r["uid"], r["d"])
            c["archivos"] += int(r["archivos"] or 0)
            c["filas"] += int(r["filas"] or 0)
    except Exception as ex:
        log.warning("progreso: importaciones por día falló: %s", ex)

    try:
        for r in conn.execute(
            f"""SELECT user_id AS uid, date AS d,
                       COALESCE(analyses_count,0) + COALESCE(chat_count,0) AS ia
                  FROM ai_usage_daily
                 WHERE user_id IN ({ph}) AND date >= ?""", (*ids, primer_dia)):
            _celda(r["uid"], r["d"])["ia"] += int(r["ia"] or 0)
    except Exception as ex:
        log.warning("progreso: uso de IA por día falló: %s", ex)

    try:
        for r in conn.execute(
            f"""SELECT user_id uid, {_sql_dia('created_at')} d, COUNT(*) n
                  FROM login_history
                 WHERE user_id IN ({ph}) AND {_sql_dia('created_at')} >= ?
                 GROUP BY user_id, {_sql_dia('created_at')}""",
                (*ids, primer_dia)):
            _celda(r["uid"], r["d"])["entradas"] += int(r["n"] or 0)
    except Exception as ex:
        log.warning("progreso: entradas por día falló: %s", ex)

    # ── Lo que hay cargado HOY: es una foto, no una serie ────────────────────
    def _conteo(nombre, sql, params=()) -> dict:
        out = {}
        try:
            for r in conn.execute(sql, params):
                out[int(r["uid"])] = int(r["n"] or 0)
        except Exception as ex:
            log.warning("progreso: conteo de %s falló: %s", nombre, ex)
        return out

    # `is_cash=0`: las filas de efectivo son saldo, no posiciones cargadas.
    posiciones = _conteo("posiciones",
        f"""SELECT user_id uid, COUNT(*) n FROM positions
             WHERE user_id IN ({ph}) AND COALESCE(is_cash,0) = 0
             GROUP BY user_id""", tuple(ids))
    operaciones = _conteo("operaciones",
        f"""SELECT user_id uid, COUNT(*) n FROM operations
             WHERE user_id IN ({ph}) GROUP BY user_id""", tuple(ids))
    # A mano = lo que no vino de ninguna importación. Es justo lo que el resto
    # del panel NO puede fechar; se muestra aparte para que se vea que existe y
    # que un "0 esta semana" con 12 acá no significa que la persona no hizo nada.
    #
    # Van las DOS tablas y no sólo las posiciones: una venta registrada por el
    # chat del Coach también es una carga a mano, y contando sólo `positions`
    # esa persona se leía como que no había hecho nada.
    a_mano = _conteo("posiciones a mano",
        f"""SELECT p.user_id uid, COUNT(*) n FROM positions p
             WHERE p.user_id IN ({ph}) AND COALESCE(p.is_cash,0) = 0
               AND NOT EXISTS (SELECT 1 FROM import_op_links l
                                WHERE l.position_id = p.id)
             GROUP BY p.user_id""", tuple(ids))
    for uid_, n in _conteo("operaciones a mano",
        f"""SELECT o.user_id uid, COUNT(*) n FROM operations o
             WHERE o.user_id IN ({ph})
               AND NOT EXISTS (SELECT 1 FROM import_op_links l
                                WHERE l.operation_id = o.id)
             GROUP BY o.user_id""", tuple(ids)).items():
        a_mano[uid_] = a_mano.get(uid_, 0) + n

    def _ultimo(nombre, sql, params=()) -> dict:
        out = {}
        try:
            for r in conn.execute(sql, params):
                out[int(r["uid"])] = _dia_de(r["t"])
        except Exception as ex:
            log.warning("progreso: último %s falló: %s", nombre, ex)
        return out

    # Estos dos miran TODA la historia, no la ventana: "no entra hace 9 días"
    # es exactamente el dato que se busca, y 9 puede caer fuera de la tira.
    ultimo_login = _ultimo("login",
        f"""SELECT user_id uid, MAX(created_at) t FROM login_history
             WHERE user_id IN ({ph}) GROUP BY user_id""", tuple(ids))
    ultimo_import = _ultimo("importación",
        f"""SELECT user_id uid, MAX(COALESCE(confirmed_at, created_at)) t
              FROM import_batches
             WHERE user_id IN ({ph}) AND status='confirmed'
             GROUP BY user_id""", tuple(ids))

    # Quiénes pusieron plata DESPUÉS de arrancar la prueba. Es la misma
    # definición que usa el embudo (`SQL_JOIN_PAGO`), y de acá salen las dos
    # cosas: la etiqueta "Pagó" de la fila y el numerador de la conversión. Si
    # la etiqueta saliera de `subscriptions` y la tasa del ledger, la tabla
    # podría mostrar 3 "Pagó" con una conversión que cuenta 1 y nadie
    # entendería cuál de los dos miente.
    pagaron = set()
    try:
        for r in conn.execute(
            f"""SELECT DISTINCT u.id uid FROM users u {SQL_JOIN_PAGO}
                 WHERE u.id IN ({ph}) AND {SQL_PAGO_DESPUES_DE_ARRANCAR}""",
                tuple(ids)):
            pagaron.add(int(r["uid"]))
    except Exception as ex:
        log.warning("progreso: quiénes pagaron falló: %s", ex)

    # ── Armar cada persona ──────────────────────────────────────────────────
    for r in filas:
        uid = int(r["id"])
        inicio = _dia_de(r["trial_started_at"]) or hoy
        fin_dia = _dia_de(r["trial_ends_at"])
        fin = prueba_viva(conn, r, ahora)
        # "Pagó" va primero: entró plata, y ése es el desenlace de la prueba
        # aunque por fecha todavía le queden días.
        estado = "pago" if uid in pagaron else ("activa" if fin else "terminada")
        # ¿Se le venció la fecha? Es el denominador de la conversión y tiene
        # que ser el mismo criterio que usa el embudo: el que sigue probando
        # todavía no tuvo su chance de decidir.
        try:
            vencida = datetime.fromisoformat(
                str(r["trial_ends_at"]).replace("Z", "")) <= ahora
        except (TypeError, ValueError):
            vencida = False

        # La tira va del arranque hasta hoy. Si ya terminó, los días de después
        # también entran: sirven para ver si volvió después del muro.
        dias = [dict(d=d, **_dia_vacio()) for d in _rango_de_dias(inicio, hoy)]
        for d in dias:
            c = act.get((uid, d["d"]))
            if c:
                d.update(c)

        try:
            transcurridos = (datetime.fromisoformat(hoy).date()
                             - datetime.fromisoformat(inicio).date()).days + 1
        except (TypeError, ValueError):
            transcurridos = 1

        tiene_datos = bool(posiciones.get(uid, 0) or operaciones.get(uid, 0))
        salida["personas"].append({
            "id": uid,
            "email": r["email"],
            "name": r["name"],
            "estado": estado,
            "vencida": vencida,
            "stage": stage_by_calendar(r["trial_started_at"], ahora) if fin else None,
            "inicio": inicio,
            "termina": fin_dia,
            # "día 7 de 20". Si ya terminó muestra el total, no un número que
            # sigue creciendo para siempre.
            "dia": min(max(1, transcurridos), TRIAL_TOTAL_DAYS),
            "days_left": dias_restantes(fin, ahora) if fin else 0,
            "tiene": {
                "brokers": _brokers_de(conn, uid),
                "posiciones": posiciones.get(uid, 0),
                "operaciones": operaciones.get(uid, 0),
                "a_mano": a_mano.get(uid, 0),
            },
            # Los números de abajo se calculan SIEMPRE sobre `dias`; el array
            # se manda sólo si lo piden (ver el docstring).
            "ventanas": {str(n): _sumar_dias(dias[-n:]) for n in VENTANAS_PROGRESO},
            "ultimo_login": ultimo_login.get(uid),
            "ultima_importacion": ultimo_import.get(uid),
            "estado_uso": _estado_de_uso(dias, tiene_datos),
        })
        if detalle:
            salida["personas"][-1]["dias"] = dias

    # Primero los que están probando (y de ésos, al que menos le queda), después
    # los que pagaron, y al final los terminados del más reciente al más viejo.
    # Es el orden en que se actúa: a los vivos todavía se los puede ayudar.
    orden = {"activa": 0, "pago": 1, "terminada": 2}
    salida["personas"].sort(key=lambda p: (
        orden.get(p["estado"], 3),
        p["days_left"] if p["estado"] == "activa" else -_orden_fecha(p["termina"])))
    salida["activas"] = sum(1 for p in salida["personas"] if p["estado"] == "activa")
    salida["resumen"] = _resumen(salida["personas"], pagaron)
    return salida


def _resumen(personas: list, pagaron: set) -> dict:
    """Las tasas de la tanda, cada una derivada de lo que ya decidió la tabla.

    Nada se vuelve a calcular con otro criterio: «app vacía», «frenado» y
    «Pagó» ya están resueltos fila por fila, y el resumen sólo cuenta. Así es
    imposible que la tabla muestre 4 con la app vacía y el resumen diga 3 —
    que es la forma en que un panel pierde la confianza y no vuelve.
    """
    activas = [p for p in personas if p["estado"] == "activa"]
    # "Llegó a cargar datos" es exactamente lo contrario de `sin_datos`, que es
    # lo que la fila ya muestra como «app vacía».
    con_datos = [p for p in personas if p["estado_uso"] != "sin_datos"]
    # Abandono = cargó datos y hace más de una semana que no da señales. Es la
    # misma definición que pinta la fila de rojo con «Frenado».
    frenados = [p for p in personas if p["estado_uso"] == "frenado"]
    # El denominador de la conversión son las prubas VENCIDAS por fecha, igual
    # que en el embudo: el que sigue probando todavía no tuvo su chance de
    # decidir, y meterlo abajo hace que el número parezca peor de lo que es.
    cerradas = [p for p in personas if p["vencida"]]
    convirtieron = [p for p in cerradas if p["id"] in pagaron]

    return {
        "total": len(personas),
        "con_datos": len(con_datos),
        "sin_datos": len(personas) - len(con_datos),
        "tasa_uso": _pct(len(con_datos), len(personas)),
        "frenados": len(frenados),
        "tasa_abandono": _pct(len(frenados), len(con_datos)),
        "terminadas": len(cerradas),
        "convirtieron": len(convirtieron),
        "tasa_conversion": _pct(len(convirtieron), len(cerradas)),
        "en_curso": len(activas),
        "en_pro": sum(1 for p in activas if p["stage"] != "plus"),
        "en_plus": sum(1 for p in activas if p["stage"] == "plus"),
        # Los que están por vencer, con el MISMO corte que dispara el mail de
        # aviso: si algún día el mail sale con otra anticipación, el panel se
        # mueve solo y los dos siguen hablando de la misma gente.
        "por_terminar": sum(1 for p in activas
                            if p["days_left"] <= MAIL_AVISO_DIAS_ANTES),
        "dias_aviso": MAIL_AVISO_DIAS_ANTES,
        "pagaron": sum(1 for p in personas if p["estado"] == "pago"),
        # ⭐ El cuarto pedazo de la barra, calculado por RESTA y no por su
        # propia consulta. Así los cuatro tramos —en Pro, en Plus, pagaron y
        # esto— suman el total EXACTO por construcción, y la barra no puede
        # quedar corta. Con una cuenta propia se escapaba un caso raro (alguien
        # cuyo crédito vigente ya no es el de la prueba antes de vencerse) y la
        # barra se dibujaba al 95% sin que nada avisara.
        "terminadas_sin_pagar": (len(personas) - len(activas)
                                 - sum(1 for p in personas if p["estado"] == "pago")),
    }
