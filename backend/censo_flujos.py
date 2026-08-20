"""Cuántos flujos ambiguos hay, de verdad, y en qué población caen.

Es la Fase 1 del agente reconstructor y no resuelve nada: MIDE. Todo lo caro
—guardas, vía de escritura, el agente— sólo se puede dimensionar después de
este número, y hasta ahora no existía.

READ-ONLY. Ni un INSERT, ni un UPDATE, ni una llamada a un modelo.

Dos reglas que este módulo aprendió en su PRIMERA corrida contra producción
─────────────────────────────────────────────────────────────────────────────
1. **Nunca sumar plata entre monedas.** La v1 reportó "3.043 millones" sumando
   pesos y dólares en un solo número. No significaba nada. Todo monto va
   agrupado por `currency`, siempre.
2. **Una suma grande puede ser UNA fila corrupta.** En la misma corrida, la
   suma en dólares de una familia era 1.700.860.670 — y 1.700.854.139 de eso
   era **una sola fila**. Por eso cada monto viaja con el máximo de una fila y
   hay una sección `alertas` aparte: si no, el censo reporta un problema
   enorme donde hay un dato roto.
Y una tercera, que es la que hacía el censo inútil: **contar usuarios, no sólo
filas.** 286 filas sonaban a mucho; eran dos mecanismos distintos sobre 15 y
127 usuarios respectivamente.

Las poblaciones
───────────────
P1  RECHAZADAS — el traspaso que el validator tiró y quedó como fila cruda.
    Es la población que `flujos.candidatos()` lee, o sea la cola real del
    agente. Se espera que sea CASI CERO, y el punto del censo es COMPROBARLO:
    varios parsers (iol.py, ppi.py) emiten el RowError y hacen `continue` sin
    appendear un RawRow, y `pipeline.py` sólo persiste errores colgados de una
    RawRow → el error existe en el preview y nunca se escribe.

P2a TRANSFER_OUT — la única marca ESTRUCTURADA que sobrevive el round-trip
    (columna real de import_normalized_tx, no un string). Es la pata que sale.

P2b EL TRASPASO CONTADO COMO APORTE — **el objetivo del reconstructor.** Un
    título entra por transferencia y el parser emite la COMPRA más un DEPOSITO
    por el mismo monto, que viaja a monthly_entries.deposits →
    compute_net_deposited_db → twr._flujo. El traspaso no "falta": ya está
    contado como plata nueva del cliente. No se busca para llenar un agujero,
    se busca para DESHACER una decisión ya tomada.

P2c LA FIRMA NUMÉRICA — cantidad ≠ 0 con gross_amount = 0: la forma de un
    movimiento de títulos sin plata, independiente del idioma del broker.
    Sirve de red para lo que el vocabulario no conoce. ⚠️ Se reporta con su
    concentración por broker al lado, porque un solo broker con un artefacto
    de parser puede ser el 88% del total y hacerlo parecer una epidemia.

P2d LA SEMILLA SINTÉTICA — el import de una FOTO de tenencia no tiene el
    historial y siembra la posición con un depósito fabricado. Es intencional,
    es OTRO problema, y se cuenta **aparte**: mezclarla con P2b fue el error de
    la v1. Toca muchísimos más usuarios que P2b, así que confundirlas
    sobredimensiona el proyecto por un factor grande.

P3  NO REPRODUCIBLE — el ledger no puede recrear la cartera de HOY, que
    conocemos. Si no puede con el presente, tampoco con enero. Es el gate que
    la Fase 7 va a usar antes de gastar un token, y acá se mide su costo.

Todo desglosado POR BROKER, porque la tasa por broker es lo que dice dónde
conviene una regla determinística — mucho más barato que un agente.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ─── Dos familias que NO son la misma cosa ───────────────────────────────────
#
# P2b — EL TRASPASO CONTADO COMO APORTE (el objetivo).
#   balanz_movimientos.py:437   "Transferencia Externa (entrada de título)"
#   balanz_internacional.py:239 "Transferencia (entrada de título)"
#   ieb.py:382                  "<desc> (cash compensatorio)"
# Se matchea por la parte ESTABLE del string: varios parsers truncan la
# descripción del broker a desc_raw[:120], así que anclarse al final no es seguro.
NOTAS_TRASPASO = (
    "(entrada de título)",
    "(entrada de titulo)",
    "(cash compensatorio)",
)

# P2d — LA SEMILLA SINTÉTICA (otro mecanismo, se cuenta aparte). Hay MÁS DE UN
# string para lo mismo, y matchear sólo uno subestima la familia entera — fue
# exactamente lo que pasó en la primera corrida.
NOTAS_SEMILLA = (
    "aporte inicial sintético",
    "aporte inicial sintetico",
    "depósito sintético",
    "deposito sintetico",
    "estado inicial",
)

# Monto que ninguna fila real puede tener. No es un umbral de negocio: es un
# detector de corrupción de ESCALA (el patrón conocido del proyecto: un monto
# en pesos que quedó en un broker marcado USD y se cuenta 1:1 como dólares).
ABSURDO = {"USD": 1_000_000.0, "ARS": 500_000_000.0}
ABSURDO_DEFAULT = 1_000_000.0

# Tope de usuarios que P3 revisa. `verificar_contra_hoy` es N+1 sin techo.
MUESTRA_P3 = 25

_VIVO = "b.status = 'confirmed' AND n.excluded_at IS NULL"


def _like(campo: str, patrones) -> str:
    return "(" + " OR ".join([f"LOWER(COALESCE({campo},'')) LIKE ?"] * len(patrones)) + ")"


def _params(patrones) -> List[str]:
    return [f"%{p.lower()}%" for p in patrones]


def _uf(uid: Optional[int], params: List[Any]) -> str:
    """Filtro por usuario, inyectado igual en todas las queries."""
    if uid is None:
        return ""
    params.append(int(uid))
    return "AND b.user_id = ?"


def _poblacion(conn, sql_where: str, params: List[Any], uid: Optional[int],
               con_plata: bool = True) -> Dict[str, Any]:
    """Corre una población y devuelve filas/usuarios/por_broker, y si es de
    plata, los montos SEPARADOS POR MONEDA con el máximo de una sola fila.

    El máximo importa tanto como la suma: una familia cuya suma es enorme pero
    cuyo máximo es casi toda la suma NO es un problema grande, es un dato roto.
    """
    p = list(params)
    filtro_uid = _uf(uid, p)
    sql = f"""SELECT COALESCE(NULLIF(n.broker,''), b.broker) AS broker,
                     COALESCE(NULLIF(n.currency,''),'?')     AS ccy,
                     COUNT(*)                    AS filas,
                     COUNT(DISTINCT b.user_id)   AS usuarios,
                     SUM(ABS(COALESCE(n.gross_amount,0)))  AS suma,
                     MAX(ABS(COALESCE(n.gross_amount,0)))  AS max_fila
                FROM import_normalized_tx n
                JOIN import_batches b ON b.id = n.batch_id
               WHERE {_VIVO} AND {sql_where} {filtro_uid}
               GROUP BY 1, 2"""
    filas = usuarios_set = 0
    por_broker: Dict[str, Dict[str, Any]] = {}
    por_moneda: Dict[str, Dict[str, float]] = {}
    for r in conn.execute(sql, p).fetchall():
        b = (r["broker"] or "?").strip() or "?"
        filas += r["filas"]
        d = por_broker.setdefault(b, {"filas": 0, "usuarios": 0})
        d["filas"] += r["filas"]
        d["usuarios"] = max(d["usuarios"], r["usuarios"])
        if con_plata:
            m = por_moneda.setdefault(r["ccy"], {"suma": 0.0, "max_fila": 0.0})
            m["suma"] += float(r["suma"] or 0)
            m["max_fila"] = max(m["max_fila"], float(r["max_fila"] or 0))

    # usuarios DISTINTOS de la población entera (no la suma de los por-grupo,
    # que double-contaría a quien tiene el caso en dos brokers).
    p2 = list(params)
    fu2 = _uf(uid, p2)
    usuarios_set = conn.execute(
        f"""SELECT COUNT(DISTINCT b.user_id) c
              FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
             WHERE {_VIVO} AND {sql_where} {fu2}""", p2).fetchone()["c"]

    out: Dict[str, Any] = {
        "filas": filas,
        "usuarios": usuarios_set,
        "por_broker": dict(sorted(por_broker.items(), key=lambda kv: -kv[1]["filas"])),
    }
    if con_plata:
        out["por_moneda"] = {k: {"suma": round(v["suma"], 2),
                                 "max_fila": round(v["max_fila"], 2)}
                             for k, v in sorted(por_moneda.items())}
    return out


def _p1_rechazadas(conn, uid: Optional[int]) -> Dict[str, Any]:
    """La cola REAL de `flujos.candidatos()` — mismos filtros, a propósito: si
    este número y el de la cola difieren, uno de los dos está mal."""
    p: List[Any] = []
    filtro = _uf(uid, p)
    rows = conn.execute(
        f"""SELECT b.broker, b.parser_format, COUNT(*) n,
                   COUNT(DISTINCT b.user_id) usuarios
              FROM import_raw_rows r JOIN import_batches b ON b.id = r.batch_id
             WHERE r.status = 'invalid' AND b.status = 'confirmed'
               AND UPPER(COALESCE(r.errors_json,'')) LIKE '%TRANSFER%' {filtro}
             GROUP BY 1, 2""", p).fetchall()
    return {
        "filas": sum(r["n"] for r in rows),
        "usuarios": sum(r["usuarios"] for r in rows),
        "por_parser": {f"{r['broker']} [{r['parser_format']}]": r["n"] for r in rows},
    }


def _alertas(conn, uid: Optional[int]) -> List[Dict[str, Any]]:
    """Filas con un monto que ninguna operación real puede tener. Salen del
    censo por derecha en vez de por casualidad: la v1 encontró la fila de
    USD 1.700.854.139 sólo porque un total no cerraba."""
    out: List[Dict[str, Any]] = []
    for ccy, techo in ABSURDO.items():
        p: List[Any] = [ccy, techo]
        filtro = _uf(uid, p)
        for r in conn.execute(
                f"""SELECT b.user_id, b.broker, b.parser_format, n.date,
                           n.currency, n.gross_amount, substr(n.notes,1,70) notas
                      FROM import_normalized_tx n
                      JOIN import_batches b ON b.id = n.batch_id
                     WHERE {_VIVO} AND n.currency = ?
                       AND ABS(COALESCE(n.gross_amount,0)) > ? {filtro}
                     ORDER BY ABS(n.gross_amount) DESC LIMIT 15""", p).fetchall():
            out.append({
                "user_id": r["user_id"], "broker": r["broker"],
                "parser_format": r["parser_format"], "date": r["date"],
                "currency": r["currency"],
                "gross_amount": round(float(r["gross_amount"] or 0), 2),
                "notas": r["notas"],
            })
    out.sort(key=lambda x: -abs(x["gross_amount"]))
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
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] or 1

    p2b = _poblacion(
        conn, f"n.operation_type = 'DEPOSIT' AND {_like('n.notes', NOTAS_TRASPASO)}",
        _params(NOTAS_TRASPASO), uid)
    p2d = _poblacion(
        conn, f"n.operation_type = 'DEPOSIT' AND {_like('n.notes', NOTAS_SEMILLA)}",
        _params(NOTAS_SEMILLA), uid)
    p2a = _poblacion(conn, "COALESCE(n.transfer_out,0) = 1", [], uid, con_plata=False)
    p2c = _poblacion(
        conn, """n.quantity IS NOT NULL AND ABS(n.quantity) > 0
                 AND COALESCE(n.gross_amount,0) = 0
                 AND n.operation_type IN ('BUY','SELL')""", [], uid, con_plata=False)

    # Concentración de P2c: si un solo broker es la mayoría, el total engaña.
    top = next(iter(p2c["por_broker"].items()), None)
    if top and p2c["filas"]:
        p2c["concentracion"] = (
            f"{top[0]} es el {round(100.0 * top[1]['filas'] / p2c['filas'])}% "
            f"de P2c ({top[1]['filas']} filas, {top[1]['usuarios']} usuarios)")

    out: Dict[str, Any] = {
        "universo": {"usuarios_en_la_base": total_users},
        "p1_rechazadas": _p1_rechazadas(conn, uid),
        "p2a_transfer_out": p2a,
        "p2b_traspaso_como_aporte": p2b,
        "p2c_firma_numerica": p2c,
        "p2d_semilla_sintetica": p2d,
        "alertas_monto_imposible": _alertas(conn, uid),
    }
    out["lectura"] = _lectura(out, total_users)

    if incluir_p3:
        if uid is not None:
            ids = [int(uid)]
        else:
            ids = [r["user_id"] for r in conn.execute(
                f"""SELECT DISTINCT b.user_id
                      FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
                     WHERE {_VIVO} AND COALESCE(n.transfer_out,0) = 1
                     LIMIT ?""", (MUESTRA_P3,)).fetchall()]
        out["p3_reproducibilidad"] = _p3_no_reproducible(conn, ids)

    return out


def _lectura(o: Dict[str, Any], total_users: int) -> str:
    """La conclusión en frases, para no tener que interpretar el dict. Lo que
    dimensiona el proyecto es el % de USUARIOS de P2b, no el conteo de filas."""
    b, d = o["p2b_traspaso_como_aporte"], o["p2d_semilla_sintetica"]
    pct = 100.0 * b["usuarios"] / max(total_users, 1)
    partes = [
        f"OBJETIVO (P2b): {b['filas']} filas en {b['usuarios']} usuarios "
        f"= {pct:.1f}% del padrón ({total_users}). Son traspasos que HOY están "
        f"contados como aporte del cliente.",
        f"APARTE (P2d, semilla de foto — otro mecanismo): {d['filas']} filas en "
        f"{d['usuarios']} usuarios. NO se suma a P2b.",
        f"COLA REAL del agente (P1): {o['p1_rechazadas']['filas']} filas.",
    ]
    if o["p1_rechazadas"]["filas"] <= 2 and b["filas"] > 10:
        partes.append("→ La cola está prácticamente VACÍA mientras el problema "
                      "SÍ existe: confirma que hay que crearla (Fase 2) antes "
                      "de que el agente tenga trabajo.")
    if o["alertas_monto_imposible"]:
        a = o["alertas_monto_imposible"][0]
        partes.append(f"🔴 {len(o['alertas_monto_imposible'])} fila(s) con monto "
                      f"imposible; la mayor: uid={a['user_id']} {a['currency']} "
                      f"{a['gross_amount']:,.0f} ({a['parser_format']}). Es "
                      f"corrupción de escala, no volumen — mirala aparte.")
    return " ".join(partes)
