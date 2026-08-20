"""Cuántos flujos ambiguos hay, de verdad, y en qué población caen.

Es la Fase 1 del agente reconstructor y no resuelve nada: MIDE. Todo lo caro
—guardas, vía de escritura, el agente— sólo se puede dimensionar después de
este número, y hasta ahora no existía.

READ-ONLY. Ni un INSERT, ni un UPDATE, ni una llamada a un modelo.

Las cuatro poblaciones, y por qué son distintas
───────────────────────────────────────────────
P1  RECHAZADAS — el traspaso que el validator tiró y quedó como fila cruda.
    Es la población que `flujos.candidatos()` lee. **Esperamos CERO**, y el
    punto del censo es COMPROBARLO en vez de suponerlo: varios parsers
    (iol.py, ppi.py) emiten el RowError y hacen `continue` sin appendear un
    RawRow, y `pipeline.py` sólo persiste errores colgados de una RawRow → el
    error existe en el preview y nunca se escribe. Si P1 da 0 y P2 da >0, eso
    confirma que la cola del agente está vacía por construcción.

P2a TRANSFER_OUT — la única marca ESTRUCTURADA que sobrevive el round-trip
    (columna real de import_normalized_tx, no un string). Es la pata que sale.

P2b EL DEPÓSITO COMPENSATORIO — la que YA contamina el TWR. Cuando entra un
    título por transferencia, tres parsers emiten DOS filas: la COMPRA y un
    DEPOSITO por el mismo monto (balanz_movimientos.py, balanz_internacional.py,
    ieb.py). Ese depósito viaja a monthly_entries.deposits →
    compute_net_deposited_db → twr._flujo. O sea: el traspaso no "falta", ya
    está contado como aporte del cliente. Esta población no se busca para
    llenar un agujero — se busca para DESHACER una decisión ya tomada.

P2c LA FIRMA NUMÉRICA — cantidad ≠ 0 con gross_amount = 0. Es la forma de un
    movimiento de títulos sin plata, independiente del idioma del broker.
    Sirve de red: caza lo que el vocabulario no conoce.

P3  NO REPRODUCIBLE — el ledger no puede recrear la cartera de HOY, que
    conocemos. Si no puede con el presente, tampoco con enero. Es el gate que
    la Fase 7 va a usar antes de gastar un token, y acá se mide su costo.

Todo desglosado POR BROKER, porque la tasa por broker es lo que dice dónde
conviene una regla determinística — mucho más barato que un agente.
"""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Los literales que los parsers escriben en `notes` al emitir el depósito
# compensatorio. Se matchea por la parte ESTABLE del string: varios parsers
# truncan la descripción del broker a desc_raw[:120], así que anclarse al final
# de la nota no es seguro.
#   balanz_movimientos.py:437   "Transferencia Externa (entrada de título)"
#   balanz_internacional.py:239 "Transferencia (entrada de título)"
#   ieb.py:382                  "<desc> (cash compensatorio)"
#   importing/tenencia.py:205   "aporte inicial sintético"
NOTAS_COMPENSATORIAS = (
    "(entrada de título)",
    "(entrada de titulo)",
    "(cash compensatorio)",
    "aporte inicial sintético",
    "aporte inicial sintetico",
)

# Tope de usuarios que P3 revisa. `verificar_contra_hoy` es N+1 sin techo: un
# censo global no puede correrlo sobre todo el padrón.
MUESTRA_P3 = 25


def _fila(broker: Optional[str]) -> str:
    return (broker or "?").strip() or "?"


def _p1_rechazadas(conn, uid: Optional[int]) -> Dict[str, int]:
    """Traspasos que quedaron como fila cruda rechazada — la cola real de
    `flujos.candidatos()`. Mismos filtros que candidatos(), a propósito: si
    este número y el de la cola difieren, uno de los dos está mal."""
    sql = """SELECT b.broker AS broker, COUNT(*) AS n
               FROM import_raw_rows r JOIN import_batches b ON b.id = r.batch_id
              WHERE r.status = 'invalid'
                AND b.status = 'confirmed'
                AND UPPER(COALESCE(r.errors_json,'')) LIKE '%TRANSFER%'
                {uf}
              GROUP BY b.broker"""
    return _agrupar(conn, sql, uid)


def _p2a_transfer_out(conn, uid: Optional[int]) -> Dict[str, int]:
    """La marca estructurada: la pata que SALE, ya reconocida por el parser."""
    sql = """SELECT COALESCE(NULLIF(n.broker,''), b.broker) AS broker, COUNT(*) AS n
               FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
              WHERE b.status = 'confirmed'
                AND n.excluded_at IS NULL
                AND COALESCE(n.transfer_out,0) = 1
                {uf}
              GROUP BY 1"""
    return _agrupar(conn, sql, uid)


def _p2b_deposito_compensatorio(conn, uid: Optional[int]) -> Dict[str, int]:
    """El depósito que el parser fabricó junto a la entrada de título. ESTA es
    la población que hoy está inflando el capital aportado y el TWR."""
    like = " OR ".join(["LOWER(COALESCE(n.notes,'')) LIKE ?"] * len(NOTAS_COMPENSATORIAS))
    sql = f"""SELECT COALESCE(NULLIF(n.broker,''), b.broker) AS broker, COUNT(*) AS n,
                     ROUND(SUM(ABS(COALESCE(n.gross_amount,0))), 2) AS monto
                FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
               WHERE b.status = 'confirmed'
                 AND n.excluded_at IS NULL
                 AND n.operation_type = 'DEPOSIT'
                 AND ({like})
                 {{uf}}
               GROUP BY 1"""
    params: List[Any] = [f"%{s.lower()}%" for s in NOTAS_COMPENSATORIAS]
    return _agrupar(conn, sql, uid, extra_params=params, con_monto=True)


def _p2c_firma_numerica(conn, uid: Optional[int]) -> Dict[str, int]:
    """Cantidad sin plata: la forma de un movimiento de títulos, sin depender
    de cómo lo haya escrito el broker."""
    sql = """SELECT COALESCE(NULLIF(n.broker,''), b.broker) AS broker, COUNT(*) AS n
               FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
              WHERE b.status = 'confirmed'
                AND n.excluded_at IS NULL
                AND n.quantity IS NOT NULL
                AND ABS(n.quantity) > 0
                AND COALESCE(n.gross_amount,0) = 0
                AND n.operation_type IN ('BUY','SELL')
                {uf}
              GROUP BY 1"""
    return _agrupar(conn, sql, uid)


def _agrupar(conn, sql: str, uid: Optional[int], extra_params=None,
             con_monto: bool = False) -> Dict[str, Any]:
    """Corre una de las queries de arriba y devuelve {broker: n} (o
    {broker: {n, monto}}). El filtro por usuario se inyecta acá para no repetir
    la misma rama cuatro veces."""
    params: List[Any] = list(extra_params or [])
    if uid is None:
        sql = sql.replace("{uf}", "")
    else:
        sql = sql.replace("{uf}", "AND b.user_id = ?")
        params.append(int(uid))
    out: Dict[str, Any] = {}
    for r in conn.execute(sql, params).fetchall():
        k = _fila(r["broker"])
        out[k] = ({"n": r["n"], "monto": r["monto"]} if con_monto else r["n"])
    return out


def _p3_no_reproducible(conn, uids: List[int]) -> Dict[str, Any]:
    """Sobre una MUESTRA: a cuántos el replay del ledger no les puede recrear
    la cartera de hoy. Es el gate del agente, medido antes de depender de él."""
    import ledger_replay
    revisados = ok = fallados = 0
    rotos: List[Dict[str, Any]] = []
    for u in uids[:MUESTRA_P3]:
        try:
            r = ledger_replay.verificar_contra_hoy(conn, u)
        except Exception:                      # una cuenta rota no tumba el censo
            log.exception("[censo] verificar_contra_hoy falló para uid=%s", u)
            fallados += 1
            continue
        revisados += 1
        if r and r.get("reproducible"):
            ok += 1
        else:
            rotos.append({"user_id": u,
                          "diferencias": len((r or {}).get("diferencias") or [])})
    return {
        "revisados": revisados, "reproducibles": ok,
        "no_reproducibles": len(rotos), "fallados": fallados,
        "muestra_tope": MUESTRA_P3, "detalle": rotos[:20],
        # ⚠️ verificar_contra_hoy es ciega al CASH y a los activos ya VENDIDOS
        # (los dos lados descartan ceros). "reproducible" acá es un piso, no un
        # certificado — taparle esos dos agujeros es tarea de la Fase 4.
        "caveat": "ciega al cash y a los cerrados — es un piso, no un certificado",
    }


def contar(conn, uid: Optional[int] = None, incluir_p3: bool = True) -> Dict[str, Any]:
    """El censo. `uid=None` = toda la base. NO ESCRIBE NADA."""
    p1 = _p1_rechazadas(conn, uid)
    p2a = _p2a_transfer_out(conn, uid)
    p2b = _p2b_deposito_compensatorio(conn, uid)
    p2c = _p2c_firma_numerica(conn, uid)

    brokers = sorted(set(p1) | set(p2a) | set(p2b) | set(p2c))
    por_broker = []
    for b in brokers:
        celda = p2b.get(b) or {}
        por_broker.append({
            "broker": b,
            "p1_rechazadas": p1.get(b, 0),
            "p2a_transfer_out": p2a.get(b, 0),
            "p2b_deposito_compensatorio": celda.get("n", 0),
            "p2b_monto": celda.get("monto", 0) or 0,
            "p2c_firma_numerica": p2c.get(b, 0),
        })
    por_broker.sort(key=lambda x: -(x["p2b_deposito_compensatorio"] + x["p1_rechazadas"]))

    tot = {
        "p1_rechazadas": sum(p1.values()),
        "p2a_transfer_out": sum(p2a.values()),
        "p2b_deposito_compensatorio": sum(c.get("n", 0) for c in p2b.values()),
        "p2b_monto": round(sum(c.get("monto", 0) or 0 for c in p2b.values()), 2),
        "p2c_firma_numerica": sum(p2c.values()),
    }

    out: Dict[str, Any] = {
        "totales": tot,
        "por_broker": por_broker,
        "lectura": _lectura(tot),
    }

    if incluir_p3:
        if uid is not None:
            ids = [int(uid)]
        else:
            ids = [r["user_id"] for r in conn.execute(
                """SELECT DISTINCT b.user_id
                     FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
                    WHERE b.status='confirmed' AND n.excluded_at IS NULL
                      AND COALESCE(n.transfer_out,0)=1
                    LIMIT ?""", (MUESTRA_P3,)).fetchall()]
        out["p3_reproducibilidad"] = _p3_no_reproducible(conn, ids)

    return out


def _lectura(tot: Dict[str, Any]) -> str:
    """La conclusión en una frase, para no tener que interpretar el dict."""
    if tot["p1_rechazadas"] == 0 and tot["p2b_deposito_compensatorio"] > 0:
        return ("CONFIRMADO: la cola de `flujos.candidatos()` está VACÍA (P1=0) "
                "mientras que hay traspasos YA CONTADOS COMO APORTE (P2b>0). El "
                "problema no es que el traspaso desaparezca — es que ya está "
                "sumado al capital aportado. Fase 2 crea la cola; Fase 5 corrige.")
    if tot["p1_rechazadas"] > 0:
        return ("Hay filas rechazadas persistidas: la cola NO está del todo vacía. "
                "Revisar qué parser las produjo antes de dar por hecho el "
                "diagnóstico de la Fase 2.")
    return ("Ni cola ni depósitos compensatorios en esta base. Si es la base de "
            "desarrollo, el censo hay que correrlo contra datos reales.")
