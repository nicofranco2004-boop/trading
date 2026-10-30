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
aviso del mercado (`ai/plan._count_alerts` la excluye). Tiene su PROPIO tope
(`RECORDATORIOS_MAX`): el de alertas era también, sin que nadie lo dijera, el
tope de mails por cuenta, y al sacarlo de ahí no se puso otro (auditoría E2,
29/10: 300 recordatorios de una cuenta gratis → 302 mails en una pasada).

QUÉ ACTIVO. Uno que existe: lo valida la API (`main._exigir_activo_valido`,
la misma regla que los dibujos y las alertas técnicas) antes de llegar acá.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from urllib.parse import quote

import tecnico
from fechas import hoy_art_date

TEXTO_MAX = 1000
# Lo más lejos que se puede poner un recordatorio (una fecha a mano).
DIAS_MAX_RECORDATORIO = 2 * 366
TIPOS_RECORDATORIO = ("3m", "fecha", "balance")
# Tesis NUEVAS por persona por día (corregir la de hoy no es una nueva). Una
# persona escribe unas pocas; esto frena a un script.
TESIS_NUEVAS_POR_DIA = 20
# Recordatorios pendientes por persona: cada uno es un mail y una notificación.
RECORDATORIOS_MAX = 20


class TesisError(ValueError):
    """Un pedido que no se puede cumplir, con el texto para la persona."""


class TesisTope(TesisError):
    """Llegó al tope de tesis nuevas del día (la API contesta 429)."""


def _tomar_turno(conn, uid: int) -> None:
    # Contar y guardar en un solo turno: el de main (sin él, diez pedidos juntos
    # contaban todos «18 de 20» y guardaban los diez).
    from main import _tomar_turno as tomar
    tomar(conn, uid)


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
    _tomar_turno(conn, uid)
    ultima = _ultima(conn, uid, asset)
    if not (ultima and ultima["escrita_el"] == hoy):
        _contar_una_nueva(conn, uid, hoy)
    if ultima and ultima["escrita_el"] == hoy:
        conn.execute(
            """UPDATE tesis SET texto=?, accion_local=?, tendencia_json=?,
                      updated_at=datetime('now') WHERE id=? AND user_id=?""",
            (texto, 1 if local else 0, tendencia, ultima["id"], uid))
        return ultima["id"]
    cur = conn.execute(
        """INSERT INTO tesis (user_id, asset, texto, escrita_el, accion_local, tendencia_json,
                              recordar_tipo, recordar_el, alert_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (uid, asset, texto, hoy, 1 if local else 0, tendencia,
         *((ultima["recordar_tipo"], ultima["recordar_el"], ultima["alert_id"])
           if ultima and ultima["alert_id"] else (None, None, None))))
    if ultima and ultima["alert_id"]:
        conn.execute("UPDATE tesis SET recordar_tipo=NULL, recordar_el=NULL, alert_id=NULL "
                     "WHERE id=? AND user_id=?", (ultima["id"], uid))
    return cur.lastrowid


def _contar_una_nueva(conn, uid: int, hoy: str) -> None:
    """Anota una tesis nueva de hoy, o TesisTope si ya van `TESIS_NUEVAS_POR_DIA`.
    Cuenta en `tesis_del_dia`, no las filas de `tesis`: borrar una tesis no
    devuelve el cupo (antes, 3 rondas de 20 en menos de un minuto borrando;
    re-test E2, 29/10). Con el turno ya tomado."""
    fila = conn.execute("SELECT nuevas FROM tesis_del_dia WHERE dia=? AND user_id=?",
                        (hoy, uid)).fetchone()
    # Las de hoy que ya estaban escritas antes de que existiera el contador.
    ya = max(fila["nuevas"] if fila else 0, conn.execute(
        "SELECT COUNT(*) FROM tesis WHERE user_id=? AND escrita_el=?", (uid, hoy)).fetchone()[0])
    if ya >= TESIS_NUEVAS_POR_DIA:
        raise TesisTope(f"Hoy ya escribiste {TESIS_NUEVAS_POR_DIA} tesis. Mañana podés seguir.")
    if not fila:
        conn.execute("DELETE FROM tesis_del_dia WHERE dia < ? AND user_id=?", (hoy, uid))
    conn.execute("""INSERT INTO tesis_del_dia (user_id, dia, nuevas) VALUES (?, ?, ?)
                    ON CONFLICT (dia, user_id) DO UPDATE SET nuevas = excluded.nuevas""",
                 (uid, hoy, ya + 1))


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
    _tomar_turno(conn, uid)
    existe = alert_id and conn.execute(
        "SELECT active FROM alerts WHERE id=? AND user_id=? AND kind='recordatorio'",
        (alert_id, uid)).fetchone()
    # Mover la fecha de uno pendiente no suma; activar uno (nuevo o ya avisado), sí.
    if not (existe and existe["active"]) and conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE user_id=? AND kind='recordatorio' AND active=1",
            (uid,)).fetchone()[0] >= RECORDATORIOS_MAX:
        raise TesisError(f"Ya tenés {RECORDATORIOS_MAX} recordatorios pendientes. "
                         "Sacale el recordatorio a alguna tesis para poner otro.")
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
    texto = t["texto"] if len(t["texto"]) <= 280 else t["texto"][:277].rstrip() + "…"
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
        # Codificado, como el de las alertas técnicas (alerts_engine): un fondo
        # lleva «:», espacios y «/», y el link tiene que abrir SU ficha.
        "cta_path": f"/activo/{quote(asset, safe='')}",
    }
