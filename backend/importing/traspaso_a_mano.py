"""«Mover a otro broker»: el pase de títulos entre dos cuentas del mismo usuario.

QUÉ ES UN PASE. El usuario tiene los títulos en un broker (A) y los pasa a otro
suyo (B). No es una venta: los títulos siguen siendo suyos, con su costo y su
fecha de compra. Cada pase escribe dos lotes de import confirmados
(`parser_format = FORMATO`, uno por broker) y una fila en `traspasos_a_mano` que
los une y guarda la receta para deshacerlo (especificación, secciones A.1–A.7).

QUÉ HAY ACÁ HOY (etapas E3 y E4). Las LECTURAS que necesitan los que leen el
registro: el capital, el resultado del mes y los reportes (E4, abajo, «Las patas
de capital y el puente») y la historia a mercado (E3,
`scripts/backfill_historical_mtm.py`), que no tiene que perder ni duplicar un lote
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
from typing import Any, Dict, List, Optional, Tuple

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


# ── Las patas de capital y el puente, al leer (especificación D.8 y D.15) ───────
#
# QUÉ SON. Cada pase deja en el registro una fila TRASPASO_SALIDA en la pata de A y
# una TRASPASO_ENTRADA en la de B, con los mismos cuatro números: V (lo que valían
# los títulos ese día, en dólares y en pesos) y C (lo que costaron, en dólares y en
# la moneda de los lotes). Y, si el pase tuvo gasto, una FEE con `traspaso_id`.
# Nadie las «aplica» al escribirlas: el capital y el resultado se calculan AL LEER,
# acá. Así, borrar A o B (que revierte su lote) hace lo correcto solo.
#
# QUÉ SALE DE ACÁ, PARA UN CONJUNTO DE CUENTAS (`resumen`):
#   · el capital aportado: B suma V (como un depósito) y A resta V (como un retiro);
#   · el «puente» V − C, que entra al resultado del mes: A gana V − C y B pierde lo
#     mismo, así el capital de cada uno cierra al costo (A baja C, B sube C);
#   · el gasto, como pérdida del broker que lo pagó.
# En el conjunto «todas las cuentas» (la fila 'global') las dos patas de un mismo
# pase se ANULAN: el aportado y el resultado de la cuenta entera no cambian. Si un
# broker se borró, queda la pata que sigue viva, y eso es lo que tiene que contar.
#
# POR QUÉ UNA SOLA LECTURA Y UNA SOLA CUENTA. El recálculo del mes, /api/monthly, el
# CSV mensual, Movimientos (lo manual es «total − importado») y los reportes
# preguntan lo mismo. Cada uno con su consulta es como se generó la deuda de este
# repo (CLAUDE.md, regla de propagación): todos leen `patas_del_registro` y la
# resumen con `resumen`.

# Las filas que lee: las dos patas y el gasto de un pase. Fechas mal formadas
# afuera, igual que el resto de los lectores del recálculo (en Postgres el CAST de
# una fecha rota corta la consulta).
PATAS_Y_GASTOS_DONDE_SQL = """b.user_id = ?
                   AND n.date IS NOT NULL AND n.date LIKE '____-__-__%'
                   AND (n.operation_type IN ('TRASPASO_SALIDA', 'TRASPASO_ENTRADA')
                        OR (n.operation_type = 'FEE' AND n.traspaso_id IS NOT NULL))"""

# Bajo esto (en dólares) un neto vale cero: las dos patas guardan los mismos
# números, pero una suma de flotantes puede dejar un resto de centavos.
_CERO = 0.005


def patas_del_registro(conn, uid: int, *, desde: Optional[str] = None,
                       hasta: Optional[str] = None) -> List[Dict[str, Any]]:
    """Las patas y los gastos de los pases VIVOS del usuario (por `TX_VIVAS`: un pase
    deshecho deja sus lotes en `reverted`, y un broker borrado revierte el suyo).

    Una fila por (pase, broker, día, tipo, moneda), con las sumas de `valor_usd`,
    `costo_usd`, `valor_ars` y `costo_nativo` (NULL cuenta 0). `desde`/`hasta`
    (AAAA-MM-DD, inclusive) acotan por fecha. El llamador decide qué hacer si las
    tablas no existen todavía (base recién creada)."""
    rango, args = "", [uid]
    if desde:
        rango += " AND substr(n.date, 1, 10) >= ?"
        args.append(str(desde)[:10])
    if hasta:
        rango += " AND substr(n.date, 1, 10) <= ?"
        args.append(str(hasta)[:10])
    filas = conn.execute(
        f"""SELECT n.traspaso_id AS traspaso_id, n.broker AS broker,
                   substr(n.date, 1, 10) AS fecha, n.operation_type AS op,
                   UPPER(COALESCE(n.currency, '')) AS moneda,
                   COALESCE(SUM(n.valor_usd), 0) AS valor_usd,
                   COALESCE(SUM(n.costo_usd), 0) AS costo_usd,
                   COALESCE(SUM(n.valor_ars), 0) AS valor_ars,
                   COALESCE(SUM(n.costo_nativo), 0) AS costo_nativo
              FROM {TX_VIVAS}
             WHERE {PATAS_Y_GASTOS_DONDE_SQL}{rango}
             GROUP BY n.traspaso_id, n.broker, substr(n.date, 1, 10), n.operation_type,
                      UPPER(COALESCE(n.currency, ''))""",
        tuple(args)).fetchall()
    return [{"traspaso_id": f["traspaso_id"], "broker": f["broker"], "fecha": f["fecha"],
             "op": f["op"], "moneda": f["moneda"], "valor_usd": _num(f["valor_usd"]),
             "costo_usd": _num(f["costo_usd"]), "valor_ars": _num(f["valor_ars"]),
             "costo_nativo": _num(f["costo_nativo"])} for f in filas]


def mes_de(fila: Dict[str, Any]) -> Tuple[str, str]:
    """('AAAA', 'MM') de una fila de `patas_del_registro`: el mes de su fecha, el
    mismo que `strftime` le da a cualquier otra fila del recálculo."""
    return fila["fecha"][:4], fila["fecha"][5:7]


def agrupar_por_mes(filas: List[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Las filas de `patas_del_registro` agrupadas por mes: {('AAAA', 'MM'): [filas]}."""
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for f in filas:
        out.setdefault(mes_de(f), []).append(f)
    return out


def resumen(filas: List[Dict[str, Any]], brokers=None) -> Dict[str, Any]:
    """Lo que dicen las patas y los gastos de `filas` para un conjunto de cuentas.

    `brokers`: los nombres de las cuentas (un broker, o sus dos patas: «Cocos» y
    «Cocos · USD»). None = todas, la fila 'global'. No lee la base.

    POR PASE, NETO DENTRO DEL CONJUNTO. Si las dos patas de un pase caen en el
    conjunto (siempre, en 'global'), se anulan; si cae una sola, cuenta entera. Eso
    es lo que da «el neto de las patas vivas»: con un broker borrado sobrevive su
    contraparte. Para un broker solo es la suma de sus patas (un pase nunca tiene las
    dos en la misma cuenta).

    Devuelve (dólares salvo que diga pesos):
      · dep_usd / wit_usd: lo que suma al capital aportado (las entradas, V) y lo
        que resta (las salidas, V).
      · puente_salida_usd / puente_entrada_usd: V − C de las salidas y de las
        entradas, CON SIGNO (V < C es una pérdida). Al resultado del mes entra
        `puente_salida − puente_entrada − gasto`.
      · gasto_usd: lo que costó el pase, en dólares (`valor_usd` de su FEE).
      · entrada_valor_usd / entrada_costo_usd / salida_valor_usd / salida_costo_usd:
        V y C de cada lado (los reportes miden el rendimiento con las patas al costo).
      · pesos_dep / pesos_dep_usd / pesos_ret / pesos_ret_usd: las patas de lotes en
        PESOS, con V en pesos y en dólares (el «Capital aportado» en pesos).
      · usd_con_dia: las patas de lotes en DÓLARES con su día, {dep: [[fecha, V]], ret}.
      · puente_ars / puente_ars_usd: el puente de las patas en pesos, en pesos
        (V − C de los lotes) y en dólares: lo que suma al «realizado en pesos».
      · neto_usd / neto_pesos: entradas − salidas (V), con signo.
    Los de pesos y los de día no se netean por pase: sólo se usan para UN broker."""
    S = None if brokers is None else set(brokers)
    out: Dict[str, Any] = {
        "dep_usd": 0.0, "wit_usd": 0.0,
        "puente_salida_usd": 0.0, "puente_entrada_usd": 0.0, "gasto_usd": 0.0,
        "entrada_valor_usd": 0.0, "entrada_costo_usd": 0.0,
        "salida_valor_usd": 0.0, "salida_costo_usd": 0.0,
        "pesos_dep": 0.0, "pesos_dep_usd": 0.0, "pesos_ret": 0.0, "pesos_ret_usd": 0.0,
        "usd_con_dia": {"dep": [], "ret": []},
        "puente_ars": 0.0, "puente_ars_usd": 0.0,
        "neto_usd": 0.0, "neto_pesos": 0.0,
    }
    por_pase: Dict[Any, Dict[str, Any]] = {}
    for f in filas:
        if S is not None and f["broker"] not in S:
            continue
        if f["op"] == "FEE":
            out["gasto_usd"] += f["valor_usd"]
            continue
        entra = f["op"] == "TRASPASO_ENTRADA"
        lado = "ent" if entra else "sal"
        p = por_pase.setdefault(f["traspaso_id"], {
            "ent": False, "sal": False, "ent_v": 0.0, "ent_c": 0.0, "sal_v": 0.0,
            "sal_c": 0.0, "ent_ars": 0.0, "sal_ars": 0.0})
        p[lado] = True
        p[lado + "_v"] += f["valor_usd"]
        p[lado + "_c"] += f["costo_usd"]
        p[lado + "_ars"] += f["valor_ars"]
        if f["moneda"] == "ARS":
            if entra:
                out["pesos_dep"] += f["valor_ars"]
                out["pesos_dep_usd"] += f["valor_usd"]
            else:
                out["pesos_ret"] += f["valor_ars"]
                out["pesos_ret_usd"] += f["valor_usd"]
            signo = -1.0 if entra else 1.0
            out["puente_ars"] += signo * (f["valor_ars"] - f["costo_nativo"])
            out["puente_ars_usd"] += signo * (f["valor_usd"] - f["costo_usd"])
        elif f["valor_usd"]:
            out["usd_con_dia"]["dep" if entra else "ret"].append(
                [f["fecha"], round(f["valor_usd"], 6)])
    for p in por_pase.values():
        out["neto_usd"] += p["ent_v"] - p["sal_v"]
        out["neto_pesos"] += p["ent_ars"] - p["sal_ars"]
        # El lado que queda: el único que cae en el conjunto o, si caen los dos, el
        # que gana el neto. Su V y su C son los de ese lado menos los del otro.
        if p["ent"] and not p["sal"]:
            lado = "ent"
        elif p["sal"] and not p["ent"]:
            lado = "sal"
        else:
            lado = "ent" if p["ent_v"] >= p["sal_v"] else "sal"
        otro = "sal" if lado == "ent" else "ent"
        v = p[lado + "_v"] - p[otro + "_v"]
        c = p[lado + "_c"] - p[otro + "_c"]
        if abs(v) < _CERO and abs(c) < _CERO:
            continue
        if lado == "ent":
            out["dep_usd"] += v
            out["entrada_valor_usd"] += v
            out["entrada_costo_usd"] += c
            out["puente_entrada_usd"] += v - c
        else:
            out["wit_usd"] += v
            out["salida_valor_usd"] += v
            out["salida_costo_usd"] += c
            out["puente_salida_usd"] += v - c
    for k in ("neto_usd", "neto_pesos"):
        if abs(out[k]) < _CERO:
            out[k] = 0.0
    return out


def entradas_y_salidas_del_periodo(conn, uid: int, brokers, desde: str, hasta: str, *,
                                   por_mes: bool = False):
    """V y C de las patas de pase de un período, para medir el RENDIMIENTO con las
    patas al costo (reportes, D.15). `brokers`: las cuentas del filtro, o None para
    'global' (el neto de las patas vivas: 0 si viven las dos).

    Devuelve {entrada_valor_usd, entrada_costo_usd, salida_valor_usd,
    salida_costo_usd, puente_usd (salida − entrada), gasto_usd}. Con `por_mes`,
    un dict así por mes: {'AAAA-MM': {...}} (sólo los meses con patas)."""
    filas = patas_del_registro(conn, uid, desde=desde, hasta=hasta)

    def _corto(fs):
        r = resumen(fs, brokers)
        return {"entrada_valor_usd": r["entrada_valor_usd"],
                "entrada_costo_usd": r["entrada_costo_usd"],
                "salida_valor_usd": r["salida_valor_usd"],
                "salida_costo_usd": r["salida_costo_usd"],
                "puente_usd": r["puente_salida_usd"] - r["puente_entrada_usd"],
                "gasto_usd": r["gasto_usd"]}
    if por_mes:
        return {f"{y}-{m}": _corto(fs) for (y, m), fs in agrupar_por_mes(filas).items()}
    return _corto(filas)
