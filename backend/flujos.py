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

# Vocabulario de dirección en las filas CRUDAS. El normalizador mapea a tipos
# canónicos y en el camino descarta la descripción — pero la fila original
# queda guardada, y ahí el broker muchas veces dijo exactamente qué era.
ENTRADA = ("TRANSFERENCIA RECIBIDA", "TRANSFER IN", "TRANSFER_IN", "ACAT IN",
           "INGRESO DE TITULOS", "INGRESO DE TÍTULOS", "TRASPASO RECIBIDO",
           "JOURNALED SHARES IN", "RECEIVED", "DEPOSITO DE TITULOS")
SALIDA = ("TRANSFERENCIA ENVIADA", "TRANSFER OUT", "TRANSFER_OUT", "ACAT OUT",
          "EGRESO DE TITULOS", "EGRESO DE TÍTULOS", "TRASPASO ENVIADO",
          "JOURNALED SHARES OUT", "DELIVERED", "RETIRO DE TITULOS")


def _texto_crudo(raw_json: str) -> str:
    """El contenido de la fila original, aplanado para buscar palabras."""
    try:
        d = json.loads(raw_json or "{}")
    except (ValueError, TypeError):
        return str(raw_json or "").upper()
    if isinstance(d, dict):
        return " ".join(str(v) for v in d.values()).upper()
    return str(d).upper()


def candidatos(conn, uid: int) -> list:
    """Los movimientos que el pipeline no pudo clasificar y que mueven títulos.

    Salen de `import_raw_rows`: el validator los rechaza con un error, pero la
    fila cruda queda guardada. Ahí es donde hay que mirar antes de deducir nada
    — el broker suele haber escrito qué era.
    """
    filas = conn.execute(
        """SELECT r.id, r.batch_id, r.raw_json, r.errors_json, b.broker
           FROM import_raw_rows r JOIN import_batches b ON b.id = r.batch_id
           WHERE b.user_id = ? AND r.status != 'ok'
           ORDER BY r.id""", (uid,)).fetchall()

    out = []
    for r in filas:
        errs = (r["errors_json"] or "")
        # Sólo los que hablan de traspaso de títulos: un error de formato de
        # fecha no es un flujo ambiguo.
        if "TRANSFER" not in errs.upper():
            continue
        out.append({
            "raw_id": r["id"], "broker": r["broker"],
            "texto": _texto_crudo(r["raw_json"]),
            "raw_json": r["raw_json"],
        })
    return out


def direccion_por_texto(texto: str):
    """'entrada' | 'salida' | None, leyendo lo que escribió el broker."""
    t = (texto or "").upper()
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
