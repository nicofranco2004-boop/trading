"""Qué fue cada movimiento ambiguo: ¿aporte del cliente o traslado interno?

Es la pregunta que el TWR necesita y los precios no contestan. Entran 12 AAPL
el 12/4: el precio histórico dice cuánto valían; de dónde salieron, no.
Y la diferencia es todo — un aporte se neutraliza, un rendimiento cuenta.

Esta es la PASADA DETERMINÍSTICA: lo que se resuelve con una consulta, sin
modelo y sin costo. Lo que queda después es lo genuinamente ambiguo, y recién
eso justifica un agente.

Compartido: no sabe qué es un asesor ni qué es un usuario.
"""
import json
import logging

log = logging.getLogger(__name__)

# Ventana para casar las dos patas de un traslado entre brokers. Un traspaso de
# títulos no liquida el mismo día en los dos lados.
DIAS_CRUCE = 4

# Tolerancia de cantidad al cruzar patas: los brokers redondean distinto.
TOL_CANTIDAD = 0.001

# Tope de filas que se traen de una vez. No es todavía el "300 ambigüedades =
# ledger roto, cortar y avisar" del diseño (eso es la Fase 3, con el conteo
# reportado): acá es sólo la guarda para no escanear la tabla más grande de la
# base — `import_raw_rows` son 3,1 de 3,4M de filas.
MAX_CANDIDATOS = 301

# Vocabulario de dirección en las filas CRUDAS. El normalizador mapea a tipos
# canónicos y en el camino descarta la descripción — pero la fila original
# queda guardada, y ahí el broker muchas veces dijo exactamente qué era.
#
# El texto llega DEACENTUADO por `_texto_crudo`, así que acá va todo sin tildes.
# Y las claves tienen que estar ANCLADAS al sustantivo: un "RECEIVED" suelto
# matchea el "Wire Received" de Schwab, que es un aporte REAL de plata — o sea
# que la clave más laxa convertía un aporte en un candidato a traslado.
ENTRADA = ("TRANSFERENCIA RECIBIDA", "TRANSFER IN", "TRANSFER_IN", "ACAT IN",
           "INGRESO DE TITULOS", "TRASPASO RECIBIDO",
           "JOURNALED SHARES IN", "SHARES RECEIVED", "DEPOSITO DE TITULOS")
SALIDA = ("TRANSFERENCIA ENVIADA", "TRANSFER OUT", "TRANSFER_OUT", "ACAT OUT",
          "EGRESO DE TITULOS", "TRASPASO ENVIADO",
          "JOURNALED SHARES OUT", "SHARES DELIVERED", "RETIRO DE TITULOS")


def _deaccent(s: str) -> str:
    """Sin tildes ni ñ. Los brokers escriben 'Retiro de Títulos' y el
    vocabulario está sin tildes: sin esto, la clave nunca matchea.
    Misma tabla que `importing.parsers.iol._deaccent` — se replica acá para no
    hacer que el núcleo compartido dependa de un parser puntual."""
    for a, b in (("ó", "o"), ("í", "i"), ("á", "a"), ("é", "e"), ("ú", "u"),
                 ("ñ", "n"), ("Ó", "O"), ("Í", "I"), ("Á", "A"), ("É", "E"),
                 ("Ú", "U"), ("Ñ", "N")):
        s = s.replace(a, b)
    return s


def _texto_crudo(raw_json: str) -> str:
    """El contenido de la fila original, aplanado y normalizado para buscar
    palabras: mayúsculas y sin tildes."""
    try:
        d = json.loads(raw_json or "{}")
    except (ValueError, TypeError):
        return _deaccent(str(raw_json or "")).upper()
    if isinstance(d, dict):
        return _deaccent(" ".join(str(v) for v in d.values())).upper()
    return _deaccent(str(d)).upper()


def candidatos(conn, uid: int) -> list:
    """Los movimientos que el pipeline no pudo clasificar y que mueven títulos.

    Salen de `import_raw_rows`: el validator los rechaza con un error, pero la
    fila cruda queda guardada. Ahí es donde hay que mirar antes de deducir nada
    — el broker suele haber escrito qué era.
    """
    # El filtro va en SQL, no en Python. `r.status != 'ok'` era SIEMPRE
    # verdadero —el pipeline escribe 'valid'/'invalid', nunca 'ok'— así que
    # esto se traía las filas crudas ENTERAS del usuario, sin tope, para
    # descartarlas después en memoria.
    # Y `b.status='confirmed'` importa por dos motivos: saca los batches de
    # 'preview' (que se limpian por TTL a la hora, así que no son un caso
    # pendiente de nadie) y saca los REVERTIDOS — el usuario ya deshizo ese
    # import y sus filas no son una ambigüedad a resolver.
    filas = conn.execute(
        """SELECT r.id, r.batch_id, r.raw_json, r.errors_json, b.broker
           FROM import_raw_rows r JOIN import_batches b ON b.id = r.batch_id
           WHERE b.user_id = ?
             AND r.status = 'invalid'
             AND b.status = 'confirmed'
             AND UPPER(COALESCE(r.errors_json,'')) LIKE '%TRANSFER%'
           ORDER BY r.id
           LIMIT ?""", (uid, MAX_CANDIDATOS)).fetchall()

    if len(filas) >= MAX_CANDIDATOS:
        # Nunca truncar en silencio: si esto suena, el conteo que reporte
        # `reconciliar()` es un piso, no el total.
        log.warning("[flujos] uid=%s alcanzó el tope de %s candidatos — "
                    "la lista está TRUNCADA", uid, MAX_CANDIDATOS)

    out = []
    for r in filas:
        out.append({
            "raw_id": r["id"], "broker": r["broker"],
            "texto": _texto_crudo(r["raw_json"]),
            "raw_json": r["raw_json"],
        })
    return out


def direccion_por_texto(texto: str):
    """'entrada' | 'salida' | None, leyendo lo que escribió el broker.

    Deacentúa por su cuenta: se la llama tanto con el texto ya normalizado por
    `_texto_crudo` como con una nota suelta de un parser."""
    t = _deaccent(texto or "").upper()
    if any(k in t for k in ENTRADA):
        return "entrada"
    if any(k in t for k in SALIDA):
        return "salida"
    return None


def cruce_entre_brokers(conn, uid: int, asset: str, fecha: str,
                        cantidad: float, broker: str):
    """¿Hay una pata opuesta en OTRO broker de la misma persona?

    Salen 12 AAPL de Balanz el 12/4 y entran 12 AAPL en IOL el 12/4 → es un
    traslado interno, NO un aporte. Esto no es un juicio: es una consulta, y se
    lleva la mayoría de los casos sin gastar un token.
    """
    from datetime import date, timedelta
    d = date.fromisoformat(str(fecha)[:10])
    desde = (d - timedelta(days=DIAS_CRUCE)).isoformat()
    hasta = (d + timedelta(days=DIAS_CRUCE)).isoformat()

    filas = conn.execute(
        """SELECT n.id, n.broker, n.date, n.quantity, n.operation_type
           FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
           WHERE b.user_id = ? AND n.excluded_at IS NULL
             AND UPPER(n.asset_symbol) = ? AND n.date BETWEEN ? AND ?
             AND n.broker != ?""",
        (uid, (asset or "").upper(), desde, hasta, broker or "")).fetchall()

    tol = max(abs(cantidad) * TOL_CANTIDAD, 1e-6)
    for f in filas:
        if abs(abs(float(f["quantity"] or 0)) - abs(cantidad)) <= tol:
            return {"broker": f["broker"], "date": f["date"],
                    "quantity": float(f["quantity"] or 0), "tx_id": f["id"]}
    return None


def resolver(conn, uid: int, cand: dict) -> dict:
    """Intenta cerrar UN caso sin modelo. Devuelve el veredicto y de dónde
    salió — la evidencia importa tanto como la conclusión."""
    direccion = direccion_por_texto(cand.get("texto", ""))
    if direccion:
        return {
            "resuelto": True,
            "naturaleza": "aporte" if direccion == "entrada" else "retiro",
            "via": "texto_crudo",
            "evidencia": "el export lo dice en la fila original",
        }

    asset, fecha, qty = cand.get("asset"), cand.get("fecha"), cand.get("cantidad")
    if asset and fecha and qty:
        par = cruce_entre_brokers(conn, uid, asset, fecha, float(qty),
                                  cand.get("broker"))
        if par:
            return {
                "resuelto": True,
                "naturaleza": "traslado_interno",   # NO es flujo: no se neutraliza
                "via": "cruce_entre_brokers",
                "evidencia": f"pata opuesta en {par['broker']} el {par['date']}",
                "par": par,
            }

    return {"resuelto": False, "naturaleza": None, "via": None,
            "evidencia": "sin contraparte ni texto que lo diga"}


def reconciliar(conn, uid: int) -> dict:
    """Corre la pasada determinística completa sobre un usuario.

    Lo que queda sin resolver es lo que justifica un agente — y recién con este
    número se sabe qué tan grande es ese trabajo, en vez de estimarlo.
    """
    cands = candidatos(conn, uid)
    resueltos, pendientes = [], []
    for c in cands:
        v = resolver(conn, uid, c)
        (resueltos if v["resuelto"] else pendientes).append({**c, **v})

    por_via = {}
    for r in resueltos:
        por_via[r["via"]] = por_via.get(r["via"], 0) + 1

    return {
        "candidatos": len(cands),
        "resueltos": len(resueltos),
        "pendientes": len(pendientes),
        "por_via": por_via,
        # Sin candidatos la tasa es 100%: no hay nada ambiguo que resolver.
        "tasa_pct": round(len(resueltos) / len(cands) * 100, 1) if cands else 100.0,
        "detalle_pendientes": [
            {k: p[k] for k in ("raw_id", "broker", "evidencia")} for p in pendientes[:20]
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# FASE 5 — la vía de escritura: dónde vive un veredicto y cómo llega al número
# ═══════════════════════════════════════════════════════════════════════════

# Las vías cuya evidencia es un HECHO verificable contra la base (hay una pata
# opuesta, hay un par COMPRA+DEPOSITO con el mismo pair_id), no una lectura de
# texto ni una deducción. Sólo éstas se auto-aplican.
VIAS_AUTOAPLICABLES = ("par_compra_deposito", "cruce_entre_brokers")


def registrar(conn, uid: int, *, scope_tipo: str, scope_id, naturaleza: str,
              fecha: str, monto_usd: float, via: str, evidencia=None,
              broker: str = None, activo: str = None, batch_id: str = None,
              confianza: float = None, modelo: str = None,
              batch_ref: str = None, aplicado: bool = False,
              aprobado_por: int = None) -> int:
    """Escribe UN veredicto. Append-only: si ya había uno para el mismo scope,
    entra como revisión nueva y la vieja queda legible.

    `aplicado` es un acto SEPARADO de resolver: el agente escribe siempre con
    aplicado=0 y alguien —una regla determinística exacta, o un humano— lo
    promueve después. Devuelve el id de la fila nueva.
    """
    import json as _json
    prev = conn.execute(
        """SELECT MAX(revision) r FROM flujo_resoluciones
            WHERE user_id=? AND scope_tipo=? AND scope_id=?""",
        (uid, scope_tipo, str(scope_id))).fetchone()
    rev = int((prev["r"] or 0)) + 1
    cur = conn.execute(
        """INSERT INTO flujo_resoluciones
           (user_id, scope_tipo, scope_id, batch_id, fecha, broker, activo,
            monto_usd, naturaleza, confianza, via, evidencia_json, modelo,
            revision, aplicado, aprobado_por, aprobado_at, batch_ref)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (uid, scope_tipo, str(scope_id), batch_id, fecha, broker, activo,
         float(monto_usd or 0), naturaleza, confianza, via,
         _json.dumps(evidencia, ensure_ascii=False) if evidencia is not None else None,
         modelo, rev, 1 if aplicado else 0, aprobado_por,
         (_ahora(conn) if aplicado else None), batch_ref))
    return cur.lastrowid


def _ahora(conn) -> str:
    return conn.execute("SELECT datetime('now') d").fetchone()["d"]


def vigentes(conn, uid: int) -> list:
    """La revisión VIGENTE de cada scope resuelto, sin las revocadas."""
    return conn.execute(
        """SELECT * FROM flujo_resoluciones f
            WHERE f.user_id = ? AND f.revocado_at IS NULL
              AND f.revision = (SELECT MAX(f2.revision) FROM flujo_resoluciones f2
                                 WHERE f2.user_id = f.user_id
                                   AND f2.scope_tipo = f.scope_tipo
                                   AND f2.scope_id = f.scope_id)
            ORDER BY f.fecha""", (uid,)).fetchall()


def revocar(conn, uid: int, res_id: int, motivo: str = None) -> bool:
    """Deshace una resolución sin borrarla: marca `revocado_at` en la fila.

    Es el único UPDATE de este módulo y es deliberado — a diferencia de
    twr_periods, acá no hay nadie que haya "visto" la fila: revocar no reescribe
    una publicación, la saca de circulación. Lo que se publicó vive en
    twr_periods, y ahí sí la corrección entra como revisión nueva: revocar mueve
    `flow_usd`, que está en _CAMPOS_SELLO, así que el próximo sellado escribe
    revision+1 y `sellados()` toma la máxima. Se auto-corrige sin borrar nada.
    """
    cur = conn.execute(
        """UPDATE flujo_resoluciones SET revocado_at = datetime('now'),
               evidencia_json = COALESCE(evidencia_json,'') || ?
            WHERE id = ? AND user_id = ? AND revocado_at IS NULL""",
        (f" | revocada: {motivo}" if motivo else "", res_id, uid))
    return cur.rowcount == 1


def revocar_lote(conn, uid: int, batch_ref: str, motivo: str = None) -> int:
    """Deshace una corrida entera del agente. Devuelve cuántas revocó."""
    cur = conn.execute(
        """UPDATE flujo_resoluciones SET revocado_at = datetime('now')
            WHERE user_id = ? AND batch_ref = ? AND revocado_at IS NULL""",
        (uid, batch_ref))
    return cur.rowcount


def aplicar(conn, uid: int, batch_ref: str = None) -> dict:
    """Corre la pasada determinística y ESCRIBE lo que se puede aplicar solo.

    Sólo se auto-aplica lo resuelto por una vía cuya evidencia es un hecho
    verificable (VIAS_AUTOAPLICABLES). Lo que salió del texto crudo NUNCA se
    aplica automático: el texto contesta DIRECCIÓN, no NATURALEZA, y ahí es
    justo donde una lectura equivocada fabrica o borra un aporte.

    Nada de lo que resuelva un modelo pasa por acá: eso entra con aplicado=0.
    """
    escritas = auto = ambiguos = 0
    for c in candidatos(conn, uid):
        v = resolver(conn, uid, c)
        if not v["resuelto"]:
            continue
        # Guarda de ambigüedad: si hay más de un candidato posible para el mismo
        # movimiento y no hay un par explícito, no se resuelve. Dos traspasos
        # del mismo monto el mismo día se cruzarían entre sí.
        if v.get("via") == "cruce_entre_brokers" and v.get("ambiguo"):
            ambiguos += 1
            continue
        auto_aplicable = (v["via"] in VIAS_AUTOAPLICABLES
                          and v["naturaleza"] == "traslado_interno")
        registrar(
            conn, uid,
            scope_tipo="raw", scope_id=c["raw_id"],
            naturaleza=v["naturaleza"], fecha=(c.get("fecha") or ""),
            monto_usd=float(c.get("monto_usd") or 0),
            via=v["via"], evidencia=v.get("evidencia"),
            broker=c.get("broker"), activo=c.get("asset"),
            confianza=1.0 if auto_aplicable else None,
            batch_ref=batch_ref, aplicado=auto_aplicable)
        escritas += 1
        auto += 1 if auto_aplicable else 0
    return {"escritas": escritas, "auto_aplicadas": auto,
            "ambiguos_omitidos": ambiguos}
