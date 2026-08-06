"""Alertas del LIBRO del asesor: "avisame si la cartera de cualquiera de mis
clientes sube o baja X% en el día".

Es el equivalente a la alerta de variación % de un usuario común, pero un nivel
más arriba: en vez de mirar un ACTIVO, mira la CARTERA COMPLETA de cada cliente.

Reusa las lecciones del motor de alertas de precio (aprendidas a los golpes):
  • Se compara el valor VIVO contra el último snapshot del cliente (su cierre
    anterior) → el % es "cuánto se movió su cartera hoy".
  • EDGE-TRIGGER por cliente: dispara al cruzar el umbral, no mientras sigue
    del otro lado; se re-arma cuando vuelve dentro de la banda.
  • TOPE de 1 aviso por cliente por día: si oscila alrededor del umbral no
    manda diez mails (el bug de ADBE 16:20/16:50).
  • Solo en horario de mercado: fuera de rueda el % queda congelado y no se
    puede confundir el movimiento de ayer con el de hoy.
  • Nunca dispara sin dato (precio ausente → no se evalúa ese cliente).

Lo evalúa el MISMO cron que las alertas de precio (cada ~10 min) → el asesor no
tiene que dar de alta nada nuevo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("advisor_alerts")

HISTORY_DAYS = 3   # el historial es un feed, no un archivo: se limpia solo


def _today_art() -> str:
    return (datetime.utcnow() - timedelta(hours=3)).date().isoformat()


def get_config(conn, uid: int) -> dict:
    row = conn.execute(
        "SELECT a.up_pct, a.down_pct, a.channel, a.active, "
        "       CASE WHEN g.id IS NULL THEN NULL ELSE a.group_id END group_id "
        "FROM advisor_alerts a LEFT JOIN advisor_groups g "
        "  ON g.id = a.group_id AND g.advisor_uid = a.advisor_uid "
        "WHERE a.advisor_uid=?", (uid,)).fetchone()
    if not row:
        return {"up_pct": None, "down_pct": None, "channel": "both",
                "active": False, "group_id": None}
    return {"up_pct": row["up_pct"], "down_pct": row["down_pct"],
            "channel": row["channel"] or "both", "active": bool(row["active"]),
            "group_id": row["group_id"]}


def set_config(conn, uid: int, up_pct=None, down_pct=None, channel=None, active=None,
               group_id="__keep__"):
    conn.execute("INSERT OR IGNORE INTO advisor_alerts (advisor_uid) VALUES (?)", (uid,))
    sets, params = [], []
    if up_pct is not None:
        sets.append("up_pct=?"); params.append(up_pct or None)
    if down_pct is not None:
        sets.append("down_pct=?"); params.append(down_pct or None)
    if channel is not None:
        sets.append("channel=?"); params.append(channel)
    if group_id != "__keep__":
        # None = todo el libro. Re-armamos SOLO si el alcance cambió de verdad:
        # el front manda el campo en cada guardado (tocar el canal no debería
        # resetear el estado de nadie).
        prev = conn.execute("SELECT group_id FROM advisor_alerts WHERE advisor_uid=?",
                            (uid,)).fetchone()
        sets.append("group_id=?"); params.append(group_id)
        if (prev["group_id"] if prev else None) != group_id:
            conn.execute("UPDATE advisor_alert_state SET armed=1 WHERE advisor_uid=?", (uid,))
    if active is not None:
        sets.append("active=?"); params.append(1 if active else 0)
        # Prender de nuevo re-arma a todos: el movimiento que ya pasó no
        # dispara retroactivamente (misma regla que las alertas de precio).
        if active:
            conn.execute("UPDATE advisor_alert_state SET armed=1 WHERE advisor_uid=?", (uid,))
    if sets:
        sets.append("updated_at=datetime('now')")
        params.append(uid)
        conn.execute(f"UPDATE advisor_alerts SET {', '.join(sets)} WHERE advisor_uid=?", params)


def history(conn, uid: int, limit: int = 30) -> list:
    purge_old(conn)
    rows = conn.execute(
        """SELECT id, client_uid, kind, message, pct, fired_at,
                  delivered_push, delivered_email
           FROM advisor_alert_events WHERE advisor_uid=?
           ORDER BY fired_at DESC LIMIT ?""", (uid, limit)).fetchall()
    return [dict(r) for r in rows]


def purge_old(conn, days: int = HISTORY_DAYS):
    """El historial se renueva solo: lo más viejo que `days` se borra."""
    try:
        conn.execute("DELETE FROM advisor_alert_events WHERE fired_at < ?",
                     ((datetime.utcnow() - timedelta(days=days)).isoformat(),))
    except Exception:
        pass


def _net_deposited_now(conn, cid: int):
    """Aportado neto ACTUAL del cliente (misma fuente que el snapshot). None si
    no se puede calcular → en ese caso no se descuenta nada (conservador)."""
    try:
        from snapshots_job import compute_net_deposited_db
        return float(compute_net_deposited_db(conn, cid, include_baseline=True) or 0.0)
    except Exception:
        return None


def _side(pct, up_pct, down_pct):
    """'up' | 'down' | None — umbrales asimétricos, cualquiera puede ser None."""
    if pct is None:
        return None
    if up_pct is not None and pct >= abs(up_pct):
        return "up"
    if down_pct is not None and pct <= -abs(down_pct):
        return "down"
    return None


def _sym_state(conn, uid: int, cid: int):
    r = conn.execute(
        "SELECT armed, last_fired_date FROM advisor_alert_state WHERE advisor_uid=? AND client_uid=?",
        (uid, cid)).fetchone()
    return (1, None) if not r else (int(r["armed"]), r["last_fired_date"])


def _set_state(conn, uid: int, cid: int, armed: int, fired_date=None):
    conn.execute(
        "INSERT INTO advisor_alert_state (advisor_uid, client_uid, armed, last_fired_date) "
        "VALUES (?,?,?,?) ON CONFLICT(advisor_uid, client_uid) DO UPDATE SET "
        "armed=excluded.armed, last_fired_date=COALESCE(excluded.last_fired_date, last_fired_date)",
        (uid, cid, armed, fired_date))


def _deliver(conn, uid: int, channel: str, title: str, body: str) -> tuple:
    push_ok = email_ok = False
    if channel in ("push", "both"):
        try:
            import main
            push_ok = main._send_push_to_user(uid, {
                "title": title, "body": body, "url": "/alertas", "tag": "advisor-alert"}) > 0
        except Exception as ex:
            log.warning("advisor alert push uid=%s: %s", uid, ex)
    if channel in ("email", "both"):
        try:
            row = conn.execute("SELECT email, name FROM users WHERE id=?", (uid,)).fetchone()
            if row and row["email"]:
                from billing import emails
                email_ok = emails.send_alert_email(
                    to=row["email"], user_name=(row["name"] or ""),
                    heading=body,
                    detail="Entrá a Rendi para ver su cartera y decidir si lo llamás.",
                    cta_path="/clientes")
        except Exception as ex:
            log.warning("advisor alert email uid=%s: %s", uid, ex)
    return push_ok, email_ok


def evaluate(conn, market_open: bool, only_uid: int = None) -> dict:
    """Evalúa las alertas de todos los asesores que las tengan activas.
    Idempotente y barato: si nadie las configuró, sale al instante."""
    # El JOIN al tier es la diferencia entre "avisa mientras pagás" y "avisa
    # para siempre": sin él, un asesor con el plan vencido seguía recibiendo
    # los nombres y los movimientos de sus ex-clientes sin poder apagarlo
    # (la UI ya no le muestra el switch). Mismo criterio que advisor_brief.
    q = ("SELECT a.advisor_uid, a.up_pct, a.down_pct, a.channel, a.group_id "
         "FROM advisor_alerts a "
         "JOIN users u ON u.id = a.advisor_uid "
         "WHERE a.active=1 AND (a.up_pct IS NOT NULL OR a.down_pct IS NOT NULL) "
         "AND u.tier='advisor' AND COALESCE(u.managed_by,0)=0")
    params: tuple = ()
    if only_uid is not None:
        q += " AND a.advisor_uid=?"
        params = (only_uid,)
    cfgs = conn.execute(q, params).fetchall()
    if not cfgs:
        return {"advisors": 0, "fired": 0}

    purge_old(conn)
    conn.commit()   # cerrar la transacción de escritura ANTES de tocar la red
    if not market_open:
        # Fuera de rueda el % del día está congelado — evaluar sería re-disparar
        # el movimiento de ayer (la lección del motor de precios).
        return {"advisors": len(cfgs), "fired": 0, "skipped": "mercado cerrado"}

    today = _today_art()
    price_cache: dict = {}
    fired = 0
    for cfg in cfgs:
        uid = cfg["advisor_uid"]
        try:
            links = conn.execute(
                """SELECT ac.client_uid, ac.label, ac.phone, u.name
                   FROM advisor_clients ac JOIN users u ON u.id = ac.client_uid
                   WHERE ac.advisor_uid=? AND ac.status='active'""", (uid,)).fetchall()
            if not links:
                continue
            labels = {r["client_uid"]: (r["label"] or r["name"] or f"Cliente {r['client_uid']}")
                      for r in links}
            # Alcance: todo el libro, o sólo los clientes del grupo elegido.
            # El grupo es una REGLA, así que se re-evalúa en cada corrida: si
            # hoy ya no cumple, hoy no genera aviso. Grupo borrado → sin avisos
            # (no caemos a "todo el libro", que sería avisar de más en silencio).
            gid = cfg["group_id"] if "group_id" in cfg.keys() else None
            if gid:
                import advisor_groups as ag
                g = ag.get_group(conn, uid, gid)
                if not g:
                    continue
                members = {c["client_uid"] for c in ag.evaluate(conn, uid, g["rules"], g["excluded"])}
                # Al que queda AFUERA hay que re-armarlo igual. Si no, uno que
                # ya disparó y después dejó de cumplir la regla se quedaba con
                # armed=0 para siempre: el día que volvía al grupo —justo
                # cuando el asesor lo quiere mirar— no avisaba nunca más.
                # (Al que ya disparó HOY no: sigue valiendo 1 aviso por día.)
                _out = [k for k in labels if k not in members]
                if _out:
                    _oph = ",".join("?" * len(_out))
                    conn.execute(
                        "UPDATE advisor_alert_state SET armed=1 WHERE advisor_uid=? "
                        "AND COALESCE(last_fired_date,'') <> ? "
                        f"AND client_uid IN ({_oph})",
                        (uid, today, *_out))
                labels = {k: v for k, v in labels.items() if k in members}
                if not labels:
                    continue
            ids = list(labels)

            import advisor_brief
            live = advisor_brief.live_book_values(conn, ids, price_cache)
            # live_book_values PERSISTE los precios que trajo → deja abierta una
            # transacción de escritura. Se cierra ACÁ: lo que sigue hace red
            # (push + email) y con el lock tomado toda la app come
            # 'database is locked' cada 10 minutos.
            conn.commit()
            if not live:
                continue
            ph = ",".join("?" * len(ids))
            # La base tiene que ser un cierre RECIENTE: sin cota, un cliente con
            # el cron frenado (o recién importado, con un snapshot sintético al
            # costo) se comparaba contra semanas atrás y el "% del día" era un
            # invento (audit). 4 días cubre un finde largo.
            _floor = (datetime.utcnow() - timedelta(hours=3) - timedelta(days=4)).date().isoformat()
            snaps, base_nd = {}, {}
            for r in conn.execute(
                    f"""SELECT s.user_id, s.total_value, s.net_deposited, s.date FROM snapshots s
                        WHERE s.user_id IN ({ph})
                          AND s.date = (SELECT MAX(s2.date) FROM snapshots s2
                                        WHERE s2.user_id = s.user_id)""", ids).fetchall():
                if str(r["date"]) < _floor:
                    continue          # base vieja → este cliente no se evalúa
                snaps[r["user_id"]] = float(r["total_value"] or 0)
                base_nd[r["user_id"]] = float(r["net_deposited"] or 0)

            for cid, now_v in live.items():
                base = snaps.get(cid) or 0.0
                if base <= 0:
                    continue
                # Descontar los flujos ocurridos DESPUÉS de la base: un depósito
                # de hoy no es "la cartera subió" (audit). El net_deposited vivo
                # sale del mismo lugar que el del snapshot.
                _nd_now = _net_deposited_now(conn, cid)
                _flow = (_nd_now - base_nd.get(cid, 0.0)) if _nd_now is not None else 0.0
                pct = ((now_v - _flow) - base) / base * 100.0
                side = _side(pct, cfg["up_pct"], cfg["down_pct"])
                armed, last_date = _sym_state(conn, uid, cid)
                fired_today = (last_date == today)

                if not side:
                    if not armed and not fired_today:
                        _set_state(conn, uid, cid, 1)      # volvió a la banda → re-arma
                    continue
                if not armed or fired_today:
                    continue

                verbo = "subió" if side == "up" else "cayó"
                msg = f"La cartera de {labels.get(cid)} {verbo} {abs(pct):.1f}% hoy"
                # Sellar el estado y el evento ANTES de mandar: el envío son dos
                # llamadas HTTP y no puede correr con el write-lock tomado. Si el
                # push/email falla, el aviso igual queda registrado UNA vez —
                # mejor eso que mandarlo dos veces o trabar la app entera.
                _set_state(conn, uid, cid, 0, today)
                _ev = conn.execute(
                    """INSERT INTO advisor_alert_events
                       (advisor_uid, client_uid, kind, message, pct, fired_at,
                        delivered_push, delivered_email)
                       VALUES (?,?,'client_move',?,?,?,0,0)""",
                    (uid, cid, msg, round(pct, 2), datetime.utcnow().isoformat()))
                _evid = _ev.lastrowid
                conn.commit()
                p_ok, e_ok = _deliver(conn, uid, cfg["channel"] or "both",
                                      "Rendi · Movimiento en tu libro", msg)
                conn.execute("UPDATE advisor_alert_events SET delivered_push=?, "
                             "delivered_email=? WHERE id=?",
                             (1 if p_ok else 0, 1 if e_ok else 0, _evid))
                conn.commit()
                fired += 1
        except Exception as ex:
            log.error("advisor alerts uid=%s falló: %s", uid, ex)
    conn.commit()
    return {"advisors": len(cfgs), "fired": fired}
