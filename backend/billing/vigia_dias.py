"""El vigía de días: ¿el plan de cada cuenta vence cuando lo que pagó dice?

POR QUÉ EXISTE. En octubre de 2026 el aviso de Rebill «cambió la suscripción»
(lo manda cuando se edita un precio o alguien cambia la tarjeta) se acreditaba
como un cobro, y el primer pago llegaba como dos avisos que sumaban los dos.
El arreglo (`bc732476`, 16/10) frenó la causa, pero el daño quedó: tres cuentas
siguieron con 52 a 90 días de más hasta el 23/11, una de ellas usando Plus
gratis con la suscripción cancelada. Nadie lo vio en cinco semanas porque
NADA comparaba los días que tiene una cuenta con lo que pagó: se descubrió
mirando el panel a ojo. Este módulo es esa comparación, todas las noches.

CÓMO DECIDE. Rehace el vencimiento leyendo `credit_ledger` en orden, que es
el registro de cada vez que se tocaron los días de una cuenta:

  · Lo que hizo una PERSONA o una regla de producto —la prueba gratis, un
    regalo, un cambio de plan, una corrección del admin— se toma como verdad:
    el vencimiento esperado pasa a ser el que dejó ese renglón.
  · Un COBRO suma lo que ese cobro agregó por sí mismo
    (`después − max(antes, cuándo llegó)`), así las conversiones entre planes
    y los días de prueba que se respetan al pagar quedan bien sin casos
    especiales.
  · Salvo que sea un COBRO REPETIDO: mismo plan y período que el último cobro
    contado, llegado antes de 2/3 del período (20 días en el mensual, 240 en
    el anual), y sin dos ids de cobro distintos que prueben que fueron dos
    cobros de verdad. Ése no suma: es exactamente la forma del error de
    octubre (alta + cobro el mismo día; «cambió el precio» a los diez días).

Si el plan vigente vence más de `TOLERANCIA_DIAS` después de lo que el
registro explica, la cuenta sale en la lista.

LO QUE NO VE (a propósito). Si un renglón «de persona» se calculó sobre días
que ya estaban de más (por ejemplo, un cambio de plan sobre un crédito
inflado), el vigía lo toma como verdad y arrastra la diferencia. Es el precio
de no auditar lo que hace el admin; la alternativa era marcar todos los
regalos y cambios de plan.

Y una cuenta con plan vigente y SIN NINGÚN renglón en el registro sale con
motivo «sin_registro»: alguien le escribió días sin dejar rastro, que es
justamente lo que hay que mirar.

Para cerrar un hallazgo sin cambiar la fecha («lo dejo así»), el admin usa
«Corregir vencimiento» con la misma fecha: deja un renglón de corrección que
desde ahí cuenta como verdad, y el aviso deja de salir.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from billing import credits as _credits

log = logging.getLogger("billing.vigia_dias")

# Por encima de esto, sale en la lista. Tres días cubren la diferencia entre
# la hora del cobro y la hora en que Rebill lo avisa, y los redondeos.
TOLERANCIA_DIAS = 3

# Un cobro del mismo plan antes de esta fracción del período es "repetido".
# Rebill cobra cada 30 (o 365) días: un segundo cobro a los 10 no es una
# renovación. 2/3 deja margen a un cobro adelantado o a un reintento tardío.
VENTANA_REPETIDO = 2 / 3


def _fecha(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return _credits._parse_iso(str(s))
    except Exception:
        return None


def _dias_del_periodo(plan, period) -> Optional[float]:
    try:
        return float(_credits.plan_period_days(plan, period))
    except Exception:
        return None


def vencimiento_explicado(filas) -> dict:
    """Rehace el vencimiento desde los renglones del registro de UNA cuenta.

    `filas`: renglones de `credit_ledger` (dicts o filas con claves), en
    cualquier orden. Devuelve:
      · `esperado`: datetime o None si no hay ningún renglón que lo explique.
      · `repetidos`: los cobros que NO se contaron, para mostrarle al admin de
        dónde salen los días de más.
    """
    ordenadas = sorted(
        (dict(f) for f in filas),
        key=lambda f: (_fecha(f.get("created_at")) or datetime.min, f.get("id") or 0))
    esperado: Optional[datetime] = None
    ultimo_cobro: Optional[dict] = None
    repetidos = []
    for f in ordenadas:
        despues = _fecha(f.get("active_until_after"))
        if despues is None:
            continue          # trial_step y similares: no mueven la fecha
        llegada = _fecha(f.get("created_at")) or despues
        if f.get("kind") != "payment":
            esperado = despues
            continue

        plan, period = f.get("to_plan"), f.get("to_period")
        periodo = _dias_del_periodo(plan, period)
        pid = f.get("payment_id")
        if ultimo_cobro is not None and periodo:
            mismo_plan = (plan, period) == (ultimo_cobro["plan"], ultimo_cobro["period"])
            separacion = (llegada - ultimo_cobro["llegada"]).total_seconds() / 86400.0
            dos_cobros_reales = bool(pid and ultimo_cobro["pid"] and pid != ultimo_cobro["pid"])
            if mismo_plan and separacion < periodo * VENTANA_REPETIDO and not dos_cobros_reales:
                antes = _fecha(f.get("active_until_before"))
                repetidos.append({
                    "fecha": str(f.get("created_at") or "")[:10],
                    "dias": round((despues - max(antes or llegada, llegada)).total_seconds() / 86400.0),
                    "nota": f.get("note") or "",
                    "dias_despues_del_anterior": round(separacion, 1),
                })
                continue

        antes = _fecha(f.get("active_until_before"))
        suma = despues - max(antes or llegada, llegada)
        esperado = max(esperado or llegada, llegada) + suma
        ultimo_cobro = {"plan": plan, "period": period, "llegada": llegada, "pid": pid}
    return {"esperado": esperado, "repetidos": repetidos}


def evaluar(usuario: dict, filas, now: Optional[datetime] = None) -> Optional[dict]:
    """El hallazgo de una cuenta, o None si sus días cierran con el registro."""
    now = now or datetime.utcnow()
    vence = _fecha(usuario.get("credit_active_until"))
    if vence is None or vence <= now:
        return None
    r = vencimiento_explicado(filas)
    esperado = r["esperado"]
    base = {
        "id": usuario.get("id"),
        "email": usuario.get("email"),
        "name": usuario.get("name"),
        "plan": usuario.get("tier"),
        "vence": usuario.get("credit_active_until"),
        "repetidos": r["repetidos"],
    }
    if esperado is None:
        return {**base, "motivo": "sin_registro", "deberia_vencer": None,
                "dias_de_mas": round((vence - now).total_seconds() / 86400.0)}
    de_mas = (vence - esperado).total_seconds() / 86400.0
    if de_mas <= TOLERANCIA_DIAS:
        return None
    return {**base,
            "motivo": "cobro_repetido" if r["repetidos"] else "sin_explicacion",
            "deberia_vencer": esperado.isoformat(),
            "dias_de_mas": round(de_mas)}


def revisar(conn, now: Optional[datetime] = None) -> dict:
    """Recorre TODAS las cuentas con plan vigente. Sólo lee."""
    now = now or datetime.utcnow()
    usuarios = conn.execute(
        """SELECT id, email, name, tier, credit_active_until
             FROM users
            WHERE credit_active_until IS NOT NULL
              AND credit_active_until > ?
              AND COALESCE(is_admin, 0) = 0
            ORDER BY id""",
        (now.isoformat(),)).fetchall()
    hallazgos = []
    for u in usuarios:
        filas = conn.execute(
            """SELECT id, kind, created_at, to_plan, to_period, payment_id,
                      active_until_before, active_until_after, note
                 FROM credit_ledger WHERE user_id = ?""",
            (u["id"],)).fetchall()
        h = evaluar(dict(u), filas, now)
        if h:
            hallazgos.append(h)
    hallazgos.sort(key=lambda h: -(h["dias_de_mas"] or 0))
    return {"revisadas": len(usuarios), "hallazgos": hallazgos}


def correr_y_avisar(conn, tanda=None) -> int:
    """El paso del ciclo de vida de la madrugada: revisa y, si hay algo, le
    manda UN mail al admin con la lista. Devuelve cuántas cuentas encontró.

    Llega todas las noches mientras haya hallazgos A PROPÓSITO: lo que dejó
    el error de octubre duró cinco semanas porque corregirlo quedó como
    "decisión pendiente" y nada lo volvía a poner adelante. Para callarlo hay
    que decidir: corregir la fecha, o dejarla como está desde el mismo botón.

    `tanda`: la de los avisos de la corrida. Si Resend está caído y la tanda
    se frenó, este mail tampoco se intenta (lo cazó test_ritmo_de_envio): la
    lista sigue ahí y sale la noche siguiente."""
    res = revisar(conn)
    if res["hallazgos"] and tanda is not None and tanda.frenado:
        log.warning("vigía de días: %d cuentas no cierran, pero los mails están "
                    "frenados (Resend caído); el aviso sale la próxima noche",
                    len(res["hallazgos"]))
    elif res["hallazgos"]:
        try:
            from billing import emails
            emails.send_vigia_dias_admin(hallazgos=res["hallazgos"])
        except Exception as ex:
            log.warning("vigía de días: el aviso al admin falló (%d cuentas): %s",
                        len(res["hallazgos"]), ex)
    log.info("vigía de días: %d cuentas con plan vigente, %d no cierran",
             res["revisadas"], len(res["hallazgos"]))
    return len(res["hallazgos"])


def nueva_fecha(vence_actual: str, fecha: str) -> datetime:
    """La fecha que elige el admin (YYYY-MM-DD) con la HORA del vencimiento
    actual: así «14/12» vence a la misma hora en que vencía el plan y la
    próxima renovación de Rebill (que suma desde ahí) no corre ni un día."""
    actual = _credits._parse_iso(vence_actual)
    dia = datetime.strptime(fecha[:10], "%Y-%m-%d")
    return dia.replace(hour=actual.hour, minute=actual.minute,
                       second=actual.second, microsecond=actual.microsecond)


def corregir(conn, user_id: int, fecha: Optional[str], motivo: str,
             admin_uid: int, confirm: bool, antes_visto: Optional[str] = None,
             now: Optional[datetime] = None) -> dict:
    """Acorta (o deja igual) el vencimiento de UNA cuenta. Nunca lo alarga:
    para dar días está «Regalar Pro», que además deja claro que es un regalo.

    `fecha=None` = «dejar como está»: no cambia nada, pero deja el renglón que
    el vigía toma como decisión del admin.

    Conserva el plan y lo que la cuenta pagó (los anchors): sólo mueve la
    fecha.

    `antes_visto` (obligatorio para escribir): el vencimiento que devolvió la
    vista previa y que el admin leyó en el cartel. Si entre la vista previa y
    el click entró un cobro, el vencimiento ya es otro y no se escribe nada.
    Releerlo recién al confirmar no alcanza: protege el instante entre leer y
    escribir, no los segundos que el admin pasa mirando el cartel (lo cazó la
    prueba del cobro en el medio).
    """
    now = now or datetime.utcnow()
    u = conn.execute(
        "SELECT id, email, tier, credit_active_until FROM users WHERE id = ?",
        (user_id,)).fetchone()
    if not u:
        return {"ok": False, "motivo": "no_existe"}
    antes = u["credit_active_until"]
    if not antes or _fecha(antes) is None:
        return {"ok": False, "motivo": "sin_plan"}
    if fecha:
        try:
            despues_dt = nueva_fecha(antes, fecha)
        except ValueError:
            return {"ok": False, "motivo": "fecha_invalida"}
        if despues_dt > _fecha(antes):
            return {"ok": False, "motivo": "alarga"}
    else:
        despues_dt = _fecha(antes)
    despues = despues_dt.isoformat()
    dias = round((despues_dt - _fecha(antes)).total_seconds() / 86400.0, 2)
    salida = {
        "ok": True, "id": u["id"], "email": u["email"], "plan": u["tier"],
        "antes": antes, "despues": despues, "dias": dias,
        "pierde_el_plan_ahora": despues_dt <= now < _fecha(antes),
        "aplicado": False,
    }
    if not confirm:
        return salida
    if antes_visto != antes:
        return {"ok": False, "motivo": "cambio_mientras_mirabas"}
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        return {"ok": False, "motivo": "falta_motivo"}
    que = ("Se deja como está" if fecha is None else "Corrección de vencimiento")
    with conn:
        cur = conn.execute(
            "UPDATE users SET credit_active_until = ? WHERE id = ? AND credit_active_until = ?",
            (despues, u["id"], antes))
        if cur.rowcount == 0:
            return {"ok": False, "motivo": "cambio_mientras_mirabas"}
        conn.execute(
            """INSERT INTO credit_ledger
                   (user_id, kind, amount_usd, days_delta, from_plan, to_plan,
                    active_until_before, active_until_after, note)
               VALUES (?, 'manual_adjust', 0, ?, ?, ?, ?, ?, ?)""",
            (u["id"], dias, u["tier"], u["tier"], antes, despues,
             f"{que} (admin uid={admin_uid}): {motivo}"))
    log.info("vigía de días: admin %s %s user %s: %s → %s",
             admin_uid, que.lower(), u["id"], antes, despues)
    return {**salida, "aplicado": True}
