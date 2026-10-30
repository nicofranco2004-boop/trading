"""Tu tesis: por qué compraste un activo, con la fecha y la tendencia de ese día.

QUÉ ES. El texto que la persona escribe («el recambio de iPhone va a empujar
las ventas»), guardado en el servidor con el día en que lo escribió y cómo
estaba la tendencia de fondo ESE día (precio contra su promedio de 200 días,
`tecnico.tendencia_del_dia`, la misma regla de la ficha). Se muestra en
Movimientos (la posición abierta y las ventas que la tenían) y en la ficha.

POR ACTIVO, NO POR LOTE. Una tesis es de (usuario, activo): «GGAL», no «el lote
del 12/03 en IOL». Por qué:
  · los lotes no duran: una venta los achica o los BORRA (FIFO, main.py), y una
    tesis pegada a un lote vendido se perdería justo cuando más sirve, al mirar
    la venta;
  · cinco compras de GGAL en tres brokers son, para casi todos, una sola idea;
  · la ficha es por activo, y ahí también se muestra.

CON HISTORIA. Si la cambiás OTRO día, no se pisa: se guarda una nueva y la
vieja queda. Cada venta muestra la última tesis escrita hasta el día de esa
venta (la pantalla elige con `escrita_el`), así reescribirla en 2027 no cambia
lo que decías cuando vendiste en 2026. El mismo día se corrige en el lugar (un
error de tipeo no es una tesis nueva).

EL RECORDATORIO. «Recordarme revisarla» es una alerta del motor de siempre
(tabla `alerts`, `kind='recordatorio'`, una sola vez, mail + push): la evalúa el
cron de alertas (`alerts_engine.evaluar_recordatorios`) y la entrega
`_entregar_pendientes`, como cualquier aviso. La FECHA vive acá
(`recordar_el`), no en `alerts`: la alerta sólo dice «está pendiente / ya avisó».
No cuenta para el tope de alertas del plan: es un recordatorio tuyo, no un
aviso del mercado (`ai/plan._count_alerts` la excluye).
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta

import tecnico
from fechas import hoy_art_date

TEXTO_MAX = 1000
# Lo más lejos que se puede poner un recordatorio (una fecha a mano).
DIAS_MAX_RECORDATORIO = 2 * 366
TIPOS_RECORDATORIO = ("3m", "fecha", "balance")


class TesisError(ValueError):
    """Un pedido que no se puede cumplir, con el texto para la persona."""


def _sumar_meses(d: date, meses: int) -> date:
    m = d.month - 1 + meses
    anio, mes = d.year + m // 12, m % 12 + 1
    return date(anio, mes, min(d.day, calendar.monthrange(anio, mes)[1]))


def _fila(r) -> dict:
    d = dict(r)
    try:
        d["tendencia"] = json.loads(d.pop("tendencia_json") or "null")
    except (TypeError, ValueError):
        d["tendencia"] = None
    d["accion_local"] = bool(d.get("accion_local"))
    return d


def _ultima(conn, uid: int, asset: str):
    return conn.execute(
        """SELECT * FROM tesis WHERE user_id=? AND asset=?
           ORDER BY escrita_el DESC, id DESC LIMIT 1""", (uid, asset)).fetchone()


def ultimas(conn, uid: int) -> dict:
    """{activo: texto} de la ÚLTIMA tesis de cada activo (la que vale hoy). LA
    MISMA regla que todos los que eligen «la última»: `_ultima` y `listar` acá,
    `tesisVigente` / `tesisDeLaOperacion` en la pantalla (ficha y Movimientos):
    el activo con el nombre TAL CUAL se guardó (el de la posición, ver PUT
    /api/tesis), y entre versiones, la de fecha más nueva y, el mismo día, la de
    id más alto. Una por activo, no por lote ni por mercado: GGAL de BYMA y el
    ADR son la misma idea (ver arriba).

    Hasta el 29/10 esta función pasaba el nombre a mayúsculas y las otras no:
    una tesis guardada como «nvda» salía en «Tus señales» y no en la ficha ni en
    Movimientos (re-test de la auditoría C)."""
    out = {}
    for r in conn.execute("SELECT asset, texto FROM tesis WHERE user_id=? ORDER BY escrita_el, id",
                          (uid,)).fetchall():
        out[r["asset"]] = r["texto"]
    return out


# Lo que entra de una tesis en un renglón de un mail (el recordatorio, el
# resumen de los sábados): se puede escribir hasta TEXTO_MAX.
LARGO_EN_UN_MAIL = 280


def para_una_linea(texto: str) -> str:
    texto = texto or ""
    return texto if len(texto) <= LARGO_EN_UN_MAIL else texto[:LARGO_EN_UN_MAIL - 3].rstrip() + "…"


def _tendencia(conn, asset: str, local: bool, fecha: str) -> dict:
    pedido = [{"id": 0, "asset": asset, "local": local, "fecha": fecha}]
    return tecnico.tendencias_en_fechas(conn, pedido)[0]


def listar(conn, uid: int) -> dict:
    """Todas las tesis del usuario (con su historia) y, de la ÚLTIMA de cada
    activo, cómo está la tendencia hoy y su recordatorio.

    {items: [{id, asset, texto, escrita_el, tendencia, accion_local,
              recordatorio: {tipo, fecha, avisado_at} | None}],
     hoy: {asset: tendencia_del_dia(hoy)}}"""
    rows = conn.execute(
        """SELECT t.*, a.active AS _rec_activo, a.last_fired_at AS _rec_avisado
             FROM tesis t LEFT JOIN alerts a
               ON a.id = t.alert_id AND a.user_id = t.user_id AND a.kind = 'recordatorio'
            WHERE t.user_id=? ORDER BY t.asset, t.escrita_el, t.id""", (uid,)).fetchall()
    items, ultimas = [], {}
    for r in rows:
        d = _fila(r)
        activo, avisado = d.pop("_rec_activo"), d.pop("_rec_avisado")
        d["recordatorio"] = ({"tipo": d["recordar_tipo"], "fecha": d["recordar_el"],
                              "avisado_at": None if activo else avisado}
                             if d.get("alert_id") and d.get("recordar_el") else None)
        for k in ("recordar_tipo", "recordar_el", "alert_id", "user_id"):
            d.pop(k, None)
        items.append(d)
        ultimas[d["asset"]] = d
    hoy = hoy_art_date().isoformat()
    pedidos = [{"id": a, "asset": a, "local": t["accion_local"], "fecha": hoy}
               for a, t in ultimas.items()]
    return {"items": items, "hoy": tecnico.tendencias_en_fechas(conn, pedidos)}


def guardar(conn, uid: int, asset: str, texto: str, local: bool = False) -> int:
    """Escribe o corrige la tesis de `asset`. Devuelve su id.

    El mismo día se corrige la última; otro día se guarda una nueva (la vieja
    queda para las ventas que hiciste mientras valía) y el recordatorio
    pendiente se muda a la nueva. No hace commit."""
    texto = (texto or "").strip()
    if not texto:
        raise TesisError("Escribí por qué lo compraste.")
    if len(texto) > TEXTO_MAX:
        raise TesisError(f"La tesis puede tener hasta {TEXTO_MAX} letras.")
    hoy = hoy_art_date().isoformat()
    tendencia = json.dumps(_tendencia(conn, asset, local, hoy))
    ultima = _ultima(conn, uid, asset)
    # «Una por día» la hace cumplir la BASE (índice único `ux_tesis_un_dia`), no
    # este `ultima`: dos «Guardar» a la vez (doble click, dos pestañas) leen los
    # dos «no hay de hoy» antes de que el otro confirme, en Postgres y también en
    # SQLite. Por eso siempre es INSERT … ON CONFLICT: si la de hoy ya existe (la
    # vio `ultima` o la acaba de escribir el otro pedido), se corrige esa. El
    # recordatorio no se toca al corregir: lo tiene la fila de hoy.
    mudar = ultima and ultima["escrita_el"] != hoy and ultima["alert_id"]
    conn.execute(
        """INSERT INTO tesis (user_id, asset, texto, escrita_el, accion_local, tendencia_json,
                              recordar_tipo, recordar_el, alert_id)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT (user_id, asset, escrita_el) DO UPDATE SET
               texto=excluded.texto, accion_local=excluded.accion_local,
               tendencia_json=excluded.tendencia_json, updated_at=datetime('now')""",
        (uid, asset, texto, hoy, 1 if local else 0, tendencia,
         *((ultima["recordar_tipo"], ultima["recordar_el"], ultima["alert_id"])
           if mudar else (None, None, None))))
    if mudar:
        conn.execute("UPDATE tesis SET recordar_tipo=NULL, recordar_el=NULL, alert_id=NULL "
                     "WHERE id=? AND user_id=?", (ultima["id"], uid))
    return conn.execute("SELECT id FROM tesis WHERE user_id=? AND asset=? AND escrita_el=?",
                        (uid, asset, hoy)).fetchone()["id"]


def unificar_repetidas(conn) -> int:
    """Deja UNA tesis por (persona, activo, día): la última escrita. Devuelve
    cuántas borró. No hace commit.

    La corre el arranque ANTES de crear el índice único `ux_tesis_un_dia`: una
    base con dos del mismo día (de antes de la regla: dos «Guardar» a la vez) no
    deja crearlo, y en Postgres eso tiraría el arranque. Si alguna de las que se
    van tenía recordatorio y la que queda no, la que queda hereda el más reciente;
    los demás recordatorios quedarían sin tesis (no avisarían nunca y contarían
    como alertas de la persona), así que se borran. Sin repetidas no hace nada."""
    grupos = conn.execute(
        """SELECT user_id, asset, escrita_el FROM tesis
            GROUP BY user_id, asset, escrita_el HAVING COUNT(*) > 1""").fetchall()
    borradas = 0
    for g in grupos:
        filas = conn.execute(
            """SELECT id, recordar_tipo, recordar_el, alert_id FROM tesis
                WHERE user_id=? AND asset=? AND escrita_el=? ORDER BY id""",
            (g["user_id"], g["asset"], g["escrita_el"])).fetchall()
        queda, van = filas[-1], filas[:-1]
        hereda = None if queda["alert_id"] else next(
            (f for f in reversed(van) if f["alert_id"]), None)
        if hereda:
            conn.execute("UPDATE tesis SET recordar_tipo=?, recordar_el=?, alert_id=? WHERE id=?",
                         (hereda["recordar_tipo"], hereda["recordar_el"], hereda["alert_id"],
                          queda["id"]))
        for f in van:
            if f["alert_id"] and f is not hereda:
                conn.execute("DELETE FROM alerts WHERE id=? AND user_id=? AND kind='recordatorio'",
                             (f["alert_id"], g["user_id"]))
            conn.execute("DELETE FROM tesis WHERE id=?", (f["id"],))
            borradas += 1
    return borradas


def _de_la_persona(conn, uid: int, tesis_id: int):
    r = conn.execute("SELECT * FROM tesis WHERE id=? AND user_id=?", (tesis_id, uid)).fetchone()
    if not r:
        raise LookupError("No encontramos esa tesis.")
    return r


def fecha_del_recordatorio(tipo: str, fecha: str = None, balance: str = None,
                           hoy: date = None) -> date:
    """El día en que llega el aviso.
      · '3m': dentro de 3 meses.
      · 'fecha': la que eligió la persona (de mañana a 2 años).
      · 'balance': el día DESPUÉS del próximo balance de la empresa (`balance`,
        la fecha guardada en `financial_events`): el aviso llega con los números
        ya publicados, no la mañana en que salen."""
    hoy = hoy or hoy_art_date()
    if tipo == "3m":
        return _sumar_meses(hoy, 3)
    if tipo == "fecha":
        try:
            d = date.fromisoformat(str(fecha or "")[:10])
        except ValueError:
            raise TesisError("Elegí una fecha.")
        if d <= hoy:
            raise TesisError("Elegí una fecha de mañana en adelante.")
        if d > hoy + timedelta(days=DIAS_MAX_RECORDATORIO):
            raise TesisError("Elegí una fecha dentro de los próximos dos años.")
        return d
    if tipo == "balance":
        if not balance:
            raise TesisError("No sabemos cuándo es el próximo balance de esta empresa. "
                             "Elegí «En 3 meses» o una fecha.")
        return date.fromisoformat(balance[:10]) + timedelta(days=1)
    raise TesisError("Elegí cuándo te lo recordamos.")


def fijar_recordatorio(conn, uid: int, tesis_id: int, tipo: str, fecha: str = None,
                       balance: str = None) -> str:
    """Pone (o cambia) el recordatorio de una tesis. Devuelve la fecha del aviso.
    Reusa la misma fila de `alerts` si ya tenía una: la re-arma. No hace commit."""
    t = _de_la_persona(conn, uid, tesis_id)
    dia = fecha_del_recordatorio(tipo, fecha, balance).isoformat()
    alert_id = t["alert_id"]
    existe = alert_id and conn.execute(
        "SELECT 1 FROM alerts WHERE id=? AND user_id=? AND kind='recordatorio'",
        (alert_id, uid)).fetchone()
    if existe:
        conn.execute("UPDATE alerts SET active=1, armed=1, last_fired_at=NULL WHERE id=?",
                     (alert_id,))
    else:
        alert_id = conn.execute(
            """INSERT INTO alerts (user_id, kind, symbol, scope, direction, channel,
                                   repeat, cooldown_min, armed, active)
               VALUES (?, 'recordatorio', ?, 'ticker', 'either', 'both', 'once', 0, 1, 1)""",
            (uid, t["asset"])).lastrowid
    conn.execute("UPDATE tesis SET recordar_tipo=?, recordar_el=?, alert_id=? WHERE id=?",
                 (tipo, dia, alert_id, tesis_id))
    return dia


def quitar_recordatorio(conn, uid: int, tesis_id: int) -> None:
    t = _de_la_persona(conn, uid, tesis_id)
    if t["alert_id"]:
        _borrar_alerta(conn, uid, t["alert_id"])
    conn.execute("UPDATE tesis SET recordar_tipo=NULL, recordar_el=NULL, alert_id=NULL "
                 "WHERE id=?", (tesis_id,))


def _borrar_alerta(conn, uid: int, alert_id: int) -> None:
    # Lo mismo que /api/alerts/{id} DELETE, acotado a los recordatorios.
    conn.execute("DELETE FROM alert_events WHERE alert_id=? AND user_id=?", (alert_id, uid))
    conn.execute("DELETE FROM alerts WHERE id=? AND user_id=? AND kind='recordatorio'",
                 (alert_id, uid))


def borrar(conn, uid: int, tesis_id: int) -> None:
    """Borra una tesis (sólo esa versión) y su recordatorio. No hace commit."""
    t = _de_la_persona(conn, uid, tesis_id)
    if t["alert_id"]:
        _borrar_alerta(conn, uid, t["alert_id"])
    conn.execute("DELETE FROM tesis WHERE id=? AND user_id=?", (tesis_id, uid))


def para_el_aviso(conn, t) -> dict:
    """Lo que dice el recordatorio: título, oración y a dónde lleva. `t` es la
    fila de la tesis. Describe, no aconseja: ni «vendé» ni «mantené»."""
    from fechas import fecha_legible
    asset = t["asset"]
    escrita = date.fromisoformat(t["escrita_el"])
    try:
        antes = json.loads(t["tendencia_json"] or "null") or {}
    except (TypeError, ValueError):
        antes = {}
    ahora = _tendencia(conn, asset, bool(t["accion_local"]), hoy_art_date().isoformat())
    texto = para_una_linea(t["texto"])
    # El mail le antepone «Hola Nico, »: la oración arranca en minúscula.
    partes = [f"escribiste esta tesis el {fecha_legible(escrita)} de {escrita.year}: «{texto}»."]
    a, h = antes.get("tendencia"), ahora.get("tendencia")

    def _donde(x):
        return "arriba" if x == "alcista" else "abajo"
    if a and h and a == h:
        partes.append(f"Ese día el precio estaba {_donde(a)} de su promedio de 200 días "
                      f"(tendencia {a}) y hoy sigue {_donde(h)}.")
    elif a and h:
        partes.append(f"Ese día el precio estaba {_donde(a)} de su promedio de 200 días "
                      f"(tendencia {a}); hoy está {_donde(h)} ({h}).")
    elif h:
        partes.append(f"Hoy el precio está {_donde(h)} de su promedio de 200 días (tendencia {h}).")
    if h:
        # La misma línea que los avisos técnicos: la tendencia describe, no manda.
        partes.append("Muestra cómo se movió el precio: no es una recomendación para comprar ni vender.")
    return {
        "titulo": f"Quedaste en revisar tu tesis de {asset}",
        "detail": " ".join(partes),
        "cta_label": f"Ver {asset}",
        "cta_path": f"/activo/{asset}",
    }
