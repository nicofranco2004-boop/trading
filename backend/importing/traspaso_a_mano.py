"""«Mover a otro broker»: el pase de títulos entre dos cuentas del mismo usuario.

QUÉ ES UN PASE. El usuario tiene los títulos en un broker (A) y los pasa a otro
suyo (B). No es una venta: los títulos siguen siendo suyos, con su costo y su
fecha de compra. Cada pase escribe dos lotes de import confirmados
(`parser_format = FORMATO`, uno por broker) y una fila en `traspasos_a_mano` que
los une y guarda la receta para deshacerlo (especificación, secciones A.1–A.7).

QUÉ HAY ACÁ HOY (etapa E3). Sólo las dos LECTURAS que necesita la historia a
mercado (`scripts/backfill_historical_mtm.py`) para no perder ni duplicar un lote
que cambió de broker:

  · `lotes_a_mano_que_salieron`: los lotes CARGADOS A MANO que salieron de A por un
    pase. El registro de lo importado nunca los vio (no son de un archivo) y, como
    el pase los saca de `positions`, después del pase tampoco están ahí. Sin esta
    lista, la historia de A los perdía en los meses en que todavía estaban en A.
  · `llegadas_por_lote`: qué día llegó a B cada lote que vino por un pase. Una
    venta posterior en B guarda la fecha de compra original; sin el día de
    llegada, la historia lo contaba en B también en los meses en que estaba en A.

El resto del módulo (armar y aplicar el pase, deshacerlo, el antiduplicado, las
guardas) lo agregan las etapas siguientes.

Todas las lecturas del registro usan `TX_VIVAS` (import confirmado y sin lápida):
un pase deshecho deja sus dos lotes en `reverted`, así que deja de contar solo.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

try:
    from importing.schema import TX_VIVAS
except ImportError:  # pragma: no cover — import relativo según cómo se cargue el paquete
    from .schema import TX_VIVAS

log = logging.getLogger(__name__)

# `import_batches.parser_format` de los dos lotes de un pase. Sin la palabra
# «tenencia» a propósito (A.7): los lectores que reconocen una foto de tenencia por
# esa palabra no tienen que tomar un pase por una foto.
FORMATO = "traspaso_a_mano"


def raices_de_brokers(conn, uid: int) -> Dict[str, str]:
    """{nombre de broker: nombre de su cuenta raíz}.

    Una cuenta argentina tiene su pata en dólares aparte («Cocos · USD», hija de
    «Cocos»). Un pase va de una cuenta raíz a otra (dentro de la misma familia no
    se puede), así que «de qué cuenta es este lote» se contesta con la raíz: el
    lote pudo llegar a la pata en pesos y venderse desde la de dólares."""
    filas = conn.execute(
        "SELECT id, name, parent_broker_id FROM brokers WHERE user_id=?", (uid,)).fetchall()
    nombre_por_id = {r["id"]: r["name"] for r in filas}
    raiz = {}
    for r in filas:
        padre = nombre_por_id.get(r["parent_broker_id"]) if r["parent_broker_id"] else None
        raiz[r["name"]] = padre or r["name"]
    return raiz


def _dia(valor) -> str:
    return str(valor)[:10] if valor else None


def _num(valor) -> float:
    try:
        return float(valor) if valor is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def lotes_a_mano_que_salieron(conn, uid: int) -> List[Dict[str, Any]]:
    """Los lotes cargados a mano que salieron de su broker por un pase vigente.

    Uno por lote de la receta con `origen = 'a_mano'`, de los pases que no se
    deshicieron y cuyo lote de salida (A) sigue confirmado: si la persona borró A,
    esos lotes ya no son de ningún broker y la historia no los tiene que contar.

    Cada elemento: {broker (la pata de A donde vivía), asset, entry_date (la compra
    original), fecha_pase, cantidad, invested, commissions (lo que se movió de ese
    lote, en su moneda), currency, tc_compra, traspaso_id, k (su lugar en la receta,
    estable: lo usa el id de la fila de Movimientos)}."""
    out: List[Dict[str, Any]] = []
    filas = conn.execute(
        """SELECT t.id, t.fecha, t.asset, t.moneda, t.receta_json
             FROM traspasos_a_mano t
             JOIN import_batches b ON b.id = t.lote_salida AND b.user_id = t.user_id
                                  AND b.status = 'confirmed'
            WHERE t.user_id = ? AND t.deshecho_at IS NULL
            ORDER BY t.fecha, t.id""",
        (uid,)).fetchall()
    for t in filas:
        try:
            receta = json.loads(t["receta_json"] or "{}")
        except (TypeError, ValueError):
            # Sin receta legible no se puede saber qué lotes salieron. No se
            # inventa nada: la historia queda como si el pase no tuviera lotes a mano.
            log.warning("traspaso_a_mano: receta ilegible en el pase %s", t["id"])
            continue
        for k, lote in enumerate(receta.get("lotes") or []):
            if not isinstance(lote, dict) or lote.get("origen") != "a_mano":
                continue
            foto = lote.get("foto") or {}
            out.append({
                "broker": lote.get("broker") or foto.get("broker"),
                "asset": t["asset"] or foto.get("asset"),
                "entry_date": _dia(foto.get("entry_date")),
                "fecha_pase": _dia(t["fecha"]),
                "cantidad": _num(lote.get("cantidad")),
                "invested": _num(lote.get("invested")),
                "commissions": _num(lote.get("commissions")),
                "currency": foto.get("currency") or t["moneda"],
                "tc_compra": foto.get("tc_compra"),
                "traspaso_id": t["id"],
                "k": k,
            })
    return out


def llegadas_por_lote(conn, uid: int) -> Dict[Tuple[str, str, str], str]:
    """{(cuenta raíz de B, activo, fecha de compra original): día en que llegó}.

    Sale de las COMPRAS vivas de un pase (la llegada a B lleva `traspaso_id` y la
    fecha de compra original en `fecha_compra`). Si dos pases traen a la misma
    cuenta lotes del mismo activo comprados el mismo día, gana la llegada MÁS
    VIEJA: la historia los cuenta de más (cobertura más baja) antes que perder uno."""
    raiz = raices_de_brokers(conn, uid)
    out: Dict[Tuple[str, str, str], str] = {}
    for r in conn.execute(
            f"""SELECT n.broker AS broker, n.asset_symbol AS asset,
                       n.fecha_compra AS fecha_compra, n.date AS fecha
                  FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND n.operation_type = 'BUY'
                   AND n.traspaso_id IS NOT NULL AND n.fecha_compra IS NOT NULL""",
            (uid,)).fetchall():
        clave = (raiz.get(r["broker"], r["broker"]), r["asset"], _dia(r["fecha_compra"]))
        dia = _dia(r["fecha"])
        if dia and (clave not in out or dia < out[clave]):
            out[clave] = dia
    return out
