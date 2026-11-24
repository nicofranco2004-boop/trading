"""«Mover a otro broker»: el pase de títulos entre dos cuentas del mismo usuario.

QUÉ ES UN PASE. El usuario tiene los títulos en un broker (A) y los pasa a otro
suyo (B). No es una venta: los títulos siguen siendo suyos, con su costo y su
fecha de compra. Cada pase escribe dos lotes de import confirmados
(`parser_format = FORMATO`, uno por broker) y una fila en `traspasos_a_mano` que
los une y guarda la receta para deshacerlo (especificación, secciones A.1–A.7).

QUÉ HAY ACÁ HOY (etapas E3 a E11).

  · E5 («Armar el pase»): cómo se arma un pase ANTES de escribirlo —
    las validaciones de la sección B.6, qué lotes se mueven, a qué pata de B va
    cada uno, cuánto valían ese día (V) y cuánto costaron (C), la comprobación
    contra el registro de lo importado y la firma—. `armar_plan` sólo LEE: lo usan
    la vista previa (`POST /api/positions/traspaso/vista-previa`) y el confirmar.
  · E6, al final («Aplicar el pase»): el confirmar (`POST /api/positions/traspaso`)
    vuelve a armar el plan con los lotes tomados, compara la firma, fija la
    valuación que vio la persona (`Plan.fijar_valuacion`) y lo escribe todo o nada
    (`aplicar_plan`).
  · E7, al final («Deshacer el pase y las guardas»): el deshacer
    (`POST /api/positions/traspaso/{id}/deshacer`: `validar_deshacer` + `deshacer`),
    cómo está cada pase (`GET /api/positions/traspasos`: `traspasos_vivos`) y lo que
    usan las puertas que podrían desarmar un pase vivo para frenar
    (`pase_que_cambia`, `filas_origen_vivas`, `lotes_en_pases_vivos`,
    `pase_vivo_del_activo`, `pases_de_brokers`, `lotes_que_no_estaban`).
  · E8, al final («Los imports que llegan después de un pase»): el antiduplicado
    (`filas_ya_traspasadas`: la llegada o la salida que el pase ya anotó no entra
    otra vez, aunque se fuercen los repetidos), lo que se anota de lo omitido
    (`anotar_omitidas`) y el freno del importador (`freno_del_import`: la regla
    única `pase_que_cambia` sobre lo que queda del archivo). Lo usan la vista previa
    y el confirm del importador (`importing/pipeline.py`, `main.import_confirm`) y la
    lista de Importaciones (`lotes_de_pases`).
  · E9, al final («Cómo se muestra un pase»): lo que necesitan Movimientos, el CSV
    de transacciones y el total de comisiones (`main._build_movements`,
    `main.export_transactions_csv`) para mostrar las dos patas del pase y no las
    compras y ventas internas (`es_fila_interna_del_pase`, `lados_de_los_pases`,
    `contraparte_de_la_pata`, `monto_de_la_pata`, `nota_csv_de_la_pata`,
    `nota_de_compra_pasada`).
  · E10, al final («El detector de pases desfasados»): si algo se escapó de las
    puertas y el registro ya no cuadra con lo que movió un pase, el próximo rearmado
    lo marca desfasado (`marcar_desfasados`, lo llaman las dos reconstrucciones de
    `importing/rebuild.py`); GET /traspasos, Movimientos e Importaciones lo dicen, y
    el deshacer lo arregla.
  · E11, al final («La migración del dólar revalúa las patas»): cuando la cuenta
    pasa del dólar vivo al histórico (`importing/fx_migrate.migrate_user_fx`, v1 →
    v2), `revaluar_patas` vuelve a calcular V y C de cada pase con la regla nueva, con
    la misma cuenta que usa `armar_plan` (`dolares_del_pase`, `valor_del_par`,
    `costo_usd_de_lo_movido`, `gasto_en_usd`).

Las LECTURAS que necesitan los que leen el
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

Todas las lecturas del registro usan `TX_VIVAS` (import confirmado y sin lápida):
un pase deshecho deja sus dos lotes en `reverted`, así que deja de contar solo.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
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


def no_es_un_pase(alias: str = "") -> str:
    """Fragmento SQL: el lote de `import_batches` NO es uno de los dos de un pase.

    Un pase escribe dos lotes confirmados (A.7), pero no es un archivo que la persona
    importó: no trae datos nuevos, mueve los que ya estaban. Lo que pregunta «¿importó
    algo?» —si la cuenta tiene historia que reconstruir, la actividad de la prueba
    gratis, la de la semana en el panel— lo pregunta con esto. Uno solo para todos:
    escrito a mano en cada consulta, el día que cambie el formato se olvida uno.
    `alias`: el de la tabla en la consulta, con su punto ('b.'), o vacío."""
    return f"COALESCE({alias}parser_format, '') <> '{FORMATO}'"


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
    lote, en su moneda), currency, tc_compra, buy_price y notes (los de la foto),
    traspaso_id, k (su lugar en la receta, estable: lo usa el id de la fila de
    Movimientos)}. Lo leen la historia a mercado (E3) y, para que la compra
    original no desaparezca, Movimientos y `transactions.csv` (E9)."""
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
                "buy_price": foto.get("buy_price"),
                "notes": foto.get("notes"),
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
                   COALESCE(SUM(n.costo_nativo), 0) AS costo_nativo,
                   COALESCE(SUM(CASE WHEN n.operation_type = 'FEE'
                                     THEN ABS(n.gross_amount) END), 0) AS monto_nativo
              FROM {TX_VIVAS}
             WHERE {PATAS_Y_GASTOS_DONDE_SQL}{rango}
             GROUP BY n.traspaso_id, n.broker, substr(n.date, 1, 10), n.operation_type,
                      UPPER(COALESCE(n.currency, ''))""",
        tuple(args)).fetchall()
    return [{"traspaso_id": f["traspaso_id"], "broker": f["broker"], "fecha": f["fecha"],
             "op": f["op"], "moneda": f["moneda"], "valor_usd": _num(f["valor_usd"]),
             "costo_usd": _num(f["costo_usd"]), "valor_ars": _num(f["valor_ars"]),
             "costo_nativo": _num(f["costo_nativo"]),
             # El gasto en su moneda (la FEE guarda el monto en `gross_amount`).
             "monto_nativo": _num(f["monto_nativo"])} for f in filas]


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
      · puente_salida_ars / puente_entrada_ars (y sus `_ars_usd`): ese mismo puente
        de las patas en pesos, por lado y neto por pase como los de dólares (la
        pestaña en pesos de /mensual explica el puente en pesos: la parte de lotes
        en dólares la pasa al dólar del mes, como el realizado).
      · gasto_ars / gasto_ars_usd: el gasto pagado en pesos, en pesos y en dólares.
      · neto_usd / neto_pesos: entradas − salidas (V), con signo.
    Los de pesos y los de día no se netean por pase: sólo se usan para UN broker
    (salvo los `puente_*_ars`, que sí)."""
    S = None if brokers is None else set(brokers)
    out: Dict[str, Any] = {
        "dep_usd": 0.0, "wit_usd": 0.0,
        "puente_salida_usd": 0.0, "puente_entrada_usd": 0.0, "gasto_usd": 0.0,
        "entrada_valor_usd": 0.0, "entrada_costo_usd": 0.0,
        "salida_valor_usd": 0.0, "salida_costo_usd": 0.0,
        "pesos_dep": 0.0, "pesos_dep_usd": 0.0, "pesos_ret": 0.0, "pesos_ret_usd": 0.0,
        "usd_con_dia": {"dep": [], "ret": []},
        "puente_ars": 0.0, "puente_ars_usd": 0.0,
        "puente_salida_ars": 0.0, "puente_salida_ars_usd": 0.0,
        "puente_entrada_ars": 0.0, "puente_entrada_ars_usd": 0.0,
        "gasto_ars": 0.0, "gasto_ars_usd": 0.0,
        "neto_usd": 0.0, "neto_pesos": 0.0,
    }
    por_pase: Dict[Any, Dict[str, Any]] = {}
    for f in filas:
        if S is not None and f["broker"] not in S:
            continue
        if f["op"] == "FEE":
            out["gasto_usd"] += f["valor_usd"]
            if f["moneda"] == "ARS":
                out["gasto_ars"] += f.get("monto_nativo") or 0.0
                out["gasto_ars_usd"] += f["valor_usd"]
            continue
        entra = f["op"] == "TRASPASO_ENTRADA"
        lado = "ent" if entra else "sal"
        p = por_pase.setdefault(f["traspaso_id"], {
            "ent": False, "sal": False, "ent_v": 0.0, "ent_c": 0.0, "sal_v": 0.0,
            "sal_c": 0.0, "ent_ars": 0.0, "sal_ars": 0.0,
            "ent_pa": 0.0, "sal_pa": 0.0, "ent_pa_usd": 0.0, "sal_pa_usd": 0.0})
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
            p[lado + "_pa"] += f["valor_ars"] - f["costo_nativo"]
            p[lado + "_pa_usd"] += f["valor_usd"] - f["costo_usd"]
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
        pa = p[lado + "_pa"] - p[otro + "_pa"]
        pa_usd = p[lado + "_pa_usd"] - p[otro + "_pa_usd"]
        if lado == "ent":
            out["dep_usd"] += v
            out["entrada_valor_usd"] += v
            out["entrada_costo_usd"] += c
            out["puente_entrada_usd"] += v - c
            out["puente_entrada_ars"] += pa
            out["puente_entrada_ars_usd"] += pa_usd
        else:
            out["wit_usd"] += v
            out["salida_valor_usd"] += v
            out["salida_costo_usd"] += c
            out["puente_salida_usd"] += v - c
            out["puente_salida_ars"] += pa
            out["puente_salida_ars_usd"] += pa_usd
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


def flujos_al_costo(deposits: float, withdrawals: float, pases) -> Tuple[float, float]:
    """(aportes, retiros) de un período con las patas de un pase AL COSTO, para medir
    RENDIMIENTO sobre la cadena contable. LA cuenta: la usan Reportes
    (`reporting.builder`) y la rama contable del motor (`twr`, vía `filas_al_costo`).

    ⚠️ POR QUÉ. Un pase anota las patas al valor del día: B suma V a lo aportado y A
    lo resta, y el resultado del mes de cada uno lleva el puente V − C para que su
    capital cierre al costo (A baja C, B sube C). Con las dos puntas en la cadena al
    costo, el Dietz de A daba `(−C) − (−V)` = V − C de «ganancia» y el de B lo mismo
    con el signo al revés: con C = 1.000 y V = 1.200, A publicaba +50 % y B −33 % en un
    mes en que no se vendió nada. Contando cada pata a su costo (`dep − (V−C)` del
    lado que entró, `ret − (V−C)` del que salió) los dos dan 0. El gasto del pase no
    se toca: es una pérdida de verdad. `pases`: `entradas_y_salidas_del_periodo`.

    Sólo para la cadena al costo. Con las puntas a MERCADO (fotos, valor vivo) la
    pata al valor V es lo correcto: lo que llegó vale V en la foto."""
    if not pases:
        return deposits, withdrawals
    return (deposits - (pases["entrada_valor_usd"] - pases["entrada_costo_usd"]),
            withdrawals - (pases["salida_valor_usd"] - pases["salida_costo_usd"]))


def filas_al_costo(conn, uid: int, filas) -> List[Any]:
    """Las filas 'global' de `monthly_entries` con sus aportes y retiros AL COSTO para
    los meses con patas de un pase (`flujos_al_costo`), para la rama CONTABLE del motor
    de rendimiento (`twr`: el Dashboard, Métricas, el Wrapped y la IA). En 'global'
    las dos patas de un pase vivo se anulan y no cambia nada; con una sola viva (se
    borró un broker con `force`) el puente de esa pata ya no se publica como
    rendimiento: la misma regla que Reportes y /mensual (especificación 0.2: el
    puente no entra en el % del mes). Quien nunca hizo un pase no paga la consulta;
    una base sin las tablas devuelve las filas tal cual. Devuelve copias (dicts)."""
    import dberrors
    filas = list(filas or [])
    if not filas:
        return filas
    try:
        if conn.execute("SELECT 1 FROM traspasos_a_mano WHERE user_id = ? LIMIT 1",
                        (uid,)).fetchone() is None:
            return filas
        por_mes = entradas_y_salidas_del_periodo(conn, uid, None, None, None, por_mes=True)
    except dberrors.ERR_OPERACIONAL as ex:  # base recién creada, sin las tablas
        log.warning("traspaso_a_mano.filas_al_costo: %s", ex)
        return filas
    if not por_mes:
        return filas
    out = []
    for r in filas:
        d = dict(r)
        try:
            k = f"{int(d['year']):04d}-{int(d['month']):02d}"
        except (KeyError, TypeError, ValueError):
            out.append(d)
            continue
        p = por_mes.get(k)
        if p:
            d["deposits"], d["withdrawals"] = flujos_al_costo(
                float(d.get("deposits") or 0), float(d.get("withdrawals") or 0), p)
        out.append(d)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Armar el pase (etapa E5: especificación B.1, B.2, B.6, C.1–C.6, C.9)
# ══════════════════════════════════════════════════════════════════════════════
#
# QUÉ HACE. Dado lo que pidió la persona (de qué cuenta a cuál, qué activo, en qué
# moneda, qué día y cuánto), decide TODO lo que el pase va a escribir, sin escribir
# nada: qué lotes salen (primero los más viejos que ya estaban en A ese día), a qué
# pata de B llega cada uno, cuánto valían ese día (V) y cuánto costaron (C), las
# filas de los dos lotes de import y la firma. La vista previa lo muestra; el
# confirmar (etapa E6) lo vuelve a armar dentro de su transacción, compara la firma
# y aplica estas mismas filas. Así lo que se ve es exactamente lo que se guarda.
#
# DE QUÉ SE PROTEGE, EN ORDEN (tabla B.6 de la especificación; los textos son los
# de ahí, exactos): fecha, brokers que no son de la persona, misma cuenta, Wallbit,
# familias distintas, efectivo, bonos, fondos, códigos viejos, un traspaso que el
# importador ya cerró, una llegada que B ya trae importada, el capital declarado a
# mano, ventas posteriores en A o en B, lotes que no estaban, lotes sin fecha,
# cambios de ratio, la valuación que cambia de A a B, el registro de A que no
# coincide con lo que se ve, la pata «· USD» que no se puede crear, pesos a una
# caja en dólares, el precio que falta y el gasto en una moneda sin caja.
#
# LO QUE NO HACE. No crea brokers (`_pata_de_la_moneda(..., crear=False)`), no toma
# turnos ni candados y no sale a la red: lo que va a internet (los cambios de ratio
# de Yahoo, el dólar cripto) lo trae `precargar` ANTES, fuera de cualquier candado.

INTERRUPTOR = "mover_entre_brokers"
BASE_ROW_INDEX = -49999
DIAS_TRASPASO_TARDIO = 60
# Cuántos días puede tener la última vela para valer como «el precio de ese día»
# (un fin de semana largo o un feriado), y cuánto de fresco el último precio.
DIAS_DE_VELA = 7
DIAS_DE_PRECIO_FRESCO = 5
# La banda de «este precio está muy lejos de lo que pagaste» (B.6, aviso), en dólares.
BANDA_DEL_PRECIO = (0.002, 50.0)
# Las fuentes de un precio de mercado (se mueven solas entre la vista previa y el
# confirmar); las otras dos, `precio_a_mano` y `precio_cargado`, no.
_FUENTES_DE_MERCADO = ("cierre_del_dia", "ultimo_precio")

MSG_APAGADO = "Esta opción no está disponible por ahora."
MSG_CARTERA_CAMBIO = ("Tu cartera cambió desde que armaste la vista previa. "
                      "Revisala de nuevo antes de confirmar.")
MSG_NO_SE_GUARDO = "No pudimos guardar el pase ({motivo}). No se cambió nada en tu cartera."
# El confirmar (B.3 paso 5, B.6 #29): la valuación que vio la persona en la vista previa.
MSG_FALTA_LA_VISTA = "Falta la vista previa del pase."
MSG_PRECIO_INVALIDO = "Precio inválido."
MSG_DOLAR_CAMBIO = ("El dólar de ese día cambió (de {antes} a {ahora}). Revisá la vista previa "
                    "antes de confirmar.")
TOLERANCIA_DEL_DOLAR = 0.03
MSG_LISTO = "Listo: pasaste {q} {asset} de {A} a {B}."
SUFIJO_USD = " · USD"
# La cantidad más chica que se mueve, y el resto de un lote partido que no se deja:
# Rendi muestra los títulos con 6 decimales (`_cant`) y compara cantidades con
# 1e-6 (`_coinciden`). Por debajo, el plan quedaba sin lotes («se cotizan de dos
# formas distintas»), no coincidía con el registro, o decía «pasaste 0 NVDA».
CANTIDAD_MINIMA = 1e-6
MSG_CANTIDAD_CHICA = ("La cantidad es demasiado chica para pasarla: Rendi lleva los títulos "
                      "con hasta 6 decimales.")
# «B · USD» (o «A · USD», para un gasto en dólares) existe como broker SUELTO, con
# movimientos: el confirmar lo sumaría a la cuenta (`_ensure_usd_sibling` lo adopta)
# sin que el plan hubiera mirado sus ventas, sus llegadas ni sus lotes.
MSG_PATA_SUELTA = ("Tenés un broker «{nombre}» con movimientos que no está unido a {cuenta}. "
                   "Para pasar estos títulos Rendi lo tendría que sumar como la cuenta en "
                   "dólares de {cuenta}, y eso cambiaría su historia. Escribinos y lo "
                   "acomodamos.")

# Las notas de las filas (A.6). Sin nombres de broker (H16): el renombre no las
# toca y un pase no puede dejar escrito un nombre viejo.
ARCHIVO_DEL_PASE = "Pase entre brokers"
NOTA_SALIDA_IMPORTADOS = "Traspaso a otro broker tuyo el {fecha} — sale al costo, sin ganancia"
NOTA_PATA_SALIDA = "Salieron {q} {asset} a otro broker tuyo (valor del día)"
NOTA_LLEGADA = "Llegó desde otro broker tuyo el {fecha} · compra original del {compra}"
NOTA_PATA_ENTRADA = "Entraron {q} {asset} desde otro broker tuyo (valor del día)"
NOTA_GASTO = "Costo del pase de {asset} a otro broker tuyo"

_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")
_DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


class PaseInvalido(Exception):
    """Lo que el pase no puede hacer, con el status y el texto para la persona
    (`detalle` es un texto, o el objeto «sin precio» de B.6 #26)."""

    def __init__(self, status: int, detalle):
        super().__init__(detalle if isinstance(detalle, str) else str(detalle))
        self.status = status
        self.detalle = detalle


# ── fechas, cantidades y montos como se leen en es-AR ──────────────────────────

def _fecha_valida(texto: str) -> bool:
    if len(texto) != 10 or texto[4] != "-" or texto[7] != "-":
        return False
    try:
        date.fromisoformat(texto)
    except ValueError:
        return False
    return True


def _ddmm(iso) -> str:
    s = str(iso or "")[:10]
    return f"{s[8:10]}/{s[5:7]}" if len(s) == 10 else ""


def _ddmmaaaa(iso) -> str:
    s = str(iso or "")[:10]
    return f"{s[8:10]}/{s[5:7]}/{s[:4]}" if len(s) == 10 else ""


def _dia_de_la_semana(iso) -> str:
    """'2026-11-20' → 'viernes 20/11'."""
    return f"{_DIAS_SEMANA[date.fromisoformat(str(iso)[:10]).weekday()]} {_ddmm(iso)}"


def _dia_siguiente(iso) -> str:
    return (date.fromisoformat(str(iso)[:10]) + timedelta(days=1)).isoformat()


def _dias_entre(a, b) -> int:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except (TypeError, ValueError):
        return 10 ** 6


def _cant(q) -> str:
    """Una cantidad de títulos: '10', '2,5', '1.000' (hasta 6 decimales)."""
    from money_fmt import fmt_num
    s = fmt_num(float(q or 0), 6)
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def _monto(valor, moneda) -> str:
    """Un monto con la moneda ADELANTE ('$5.000', 'US$ 12,30'): así el «ojito» de la
    pantalla lo tapa (`taparMontos` sólo tapa lo que lleva moneda adelante)."""
    from money_fmt import fmt_money
    return fmt_money(valor, "ARS" if (moneda or "").upper() == "ARS" else "USD")


def _cotizacion(valor) -> str:
    """Un dólar en pesos con sus centavos y la moneda adelante ('$1.400,50'): la
    cotización de un día se lee con dos decimales (`_monto` la redondearía)."""
    from money_fmt import fmt_num
    return "$" + fmt_num(float(valor or 0), 2)


def _veces(k: float) -> str:
    from money_fmt import fmt_num
    if k >= 10:
        return fmt_num(k, 0)
    s = fmt_num(k, 4 if k < 1 else 2)
    return s.rstrip("0").rstrip(",") if "," in s else s


def _en_moneda(moneda) -> str:
    return "pesos" if (moneda or "").upper() == "ARS" else "dólares"


def _clave_nombre(nombre) -> str:
    """Como se comparan los nombres de broker (renombre_broker._clave)."""
    return str(nombre or "").strip().lower()


def _ph(lista) -> str:
    return ",".join("?" * len(lista))


# ── C.1: cuentas, patas y familia ──────────────────────────────────────────────

@dataclass
class Cuentas:
    """Las dos cuentas del pedido, ya validadas (B.6 #1–#7).

    `raiz_a`/`raiz_b`: el nombre de la cuenta (el padre, si se eligió una pata en
    dólares). `patas_a`/`patas_b`: la cuenta y su «· USD», siempre desde el padre
    (`persister.broker_pair`: desde un hijo no ve a los hermanos)."""
    asset: str
    moneda: str
    fecha: str
    raiz_a: str
    raiz_b: str
    fila_a: Dict[str, Any]
    fila_b: Dict[str, Any]
    patas_a: List[str]
    patas_b: List[str]
    familia: str
    brokers: List[Dict[str, Any]]


def _familia(nombre: str, brokers: List[Dict[str, Any]]) -> str:
    """'AR' | 'EXCHANGE' | 'EXTERIOR', con la misma fuente que la valuación (C.1.2)."""
    import snapshots_job
    from cripto import is_exchange_broker
    ars, ar_usd = snapshots_job._broker_name_sets(brokers)
    if nombre in ars or nombre in ar_usd:
        return "AR"
    if is_exchange_broker(nombre):
        return "EXCHANGE"
    return "EXTERIOR"


def _es_wallbit(conn, uid: int, nombre: str) -> bool:
    try:
        conectadas = {_clave_nombre(r["broker"]) for r in conn.execute(
            "SELECT broker FROM user_broker_credentials WHERE user_id=?", (uid,)).fetchall()}
    except Exception:  # base sin la tabla: nadie conectado
        conectadas = set()
    c = _clave_nombre(nombre)
    return c == "wallbit" or c in conectadas


def cuentas_del_pedido(conn, uid: int, pedido, *, hoy: str) -> Cuentas:
    """Valida B.6 #1–#7 y devuelve las cuentas. Sólo lee la tabla `brokers` del
    usuario: es lo que el confirmar necesita saber ANTES de tomar los lotes de A y
    de B (B.3, paso 2). Un broker de otra cuenta da el mismo 404 que uno que no
    existe (B.7)."""
    from importing.persister import broker_pair
    fecha = str(getattr(pedido, "fecha", None) or "").strip()
    if not fecha:
        raise PaseInvalido(400, "Elegí la fecha del pase.")
    if not _fecha_valida(fecha):
        raise PaseInvalido(400, "Fecha inválida. Usá el formato día/mes/año.")
    if fecha > hoy:
        raise PaseInvalido(400, "La fecha del pase no puede ser posterior a hoy.")
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, name, currency, parent_broker_id FROM brokers WHERE user_id=? ORDER BY id",
        (uid,)).fetchall()]
    por_nombre = {b["name"]: b for b in brokers}
    por_id = {b["id"]: b for b in brokers}
    origen = por_nombre.get(str(pedido.broker_origen or "").strip())
    if not origen:
        raise PaseInvalido(404, "No encontramos ese broker en tu cuenta.")
    destino = por_nombre.get(str(pedido.broker_destino or "").strip())
    if not destino:
        raise PaseInvalido(404, "No encontramos el broker al que querés pasarlo. "
                                "Si es nuevo, crealo primero.")
    fila_a = por_id.get(origen["parent_broker_id"]) or origen
    fila_b = por_id.get(destino["parent_broker_id"]) or destino
    if fila_a["id"] == fila_b["id"]:
        raise PaseInvalido(400, "Ése es el mismo broker: las dos monedas de una cuenta son "
                                "una sola. Elegí otro broker.")
    patas_a = broker_pair(conn, uid, fila_a["name"])
    patas_b = broker_pair(conn, uid, fila_b["name"])
    if any(_es_wallbit(conn, uid, n) for n in patas_a + patas_b):
        raise PaseInvalido(400, "Wallbit se sincroniza sola con tu cuenta real: no se le "
                                "pueden pasar ni sacar títulos a mano.")
    fam_a, fam_b = _familia(fila_a["name"], brokers), _familia(fila_b["name"], brokers)
    if fam_a != fam_b:
        A, B = fila_a["name"], fila_b["name"]
        if "EXCHANGE" in (fam_a, fam_b):
            raise PaseInvalido(400, f"No se puede pasar de {A} a {B}: uno es un exchange "
                                    "cripto y el otro un broker.")
        raise PaseInvalido(400, f"No se puede pasar de {A} a {B}: uno opera en el mercado "
                                "argentino y el otro afuera. Un CEDEAR no es lo mismo que la "
                                "acción de Estados Unidos.")
    return Cuentas(asset=str(pedido.asset or "").strip().upper(),
                   moneda="ARS" if str(pedido.moneda or "").upper() == "ARS" else "USD",
                   fecha=fecha, raiz_a=fila_a["name"], raiz_b=fila_b["name"],
                   fila_a=fila_a, fila_b=fila_b, patas_a=patas_a, patas_b=patas_b,
                   familia=fam_a, brokers=brokers)


# ── el plan ────────────────────────────────────────────────────────────────────

@dataclass
class LoteDelPlan:
    """Un lote de A que se mueve (entero o la parte que se toma)."""
    lote: Dict[str, Any]                  # la fila de `positions` tal como está antes del pase
    origen: str                           # 'importado' | 'a_mano'
    fila_origen: Optional[Dict[str, Any]]  # {batch_id, raw_row_id} si es importado
    asset_type: Optional[str]             # el del lote o, si no tiene, el de su fila de origen
    asset_name: Optional[str]
    take: float                           # cuánto se mueve
    parcial: bool
    mov_inv: float                        # inversión movida, en su moneda, sin comisiones
    mov_com: float                        # comisiones movidas
    moneda: str                           # la del lote ('ARS' | 'USD')
    pata_a: str
    pata_b: str = ""
    c_usd: float = 0.0                    # C de lo movido (tramo.costo_y_resultado_del_tramo)

    @property
    def lote_id(self):
        return self.lote["id"]

    @property
    def entry_date(self) -> str:
        return str(self.lote.get("entry_date") or "")[:10]


@dataclass
class Plan:
    """Lo que el pase va a escribir, ya decidido. Sólo datos: no lee la base."""
    cuentas: Cuentas
    cantidad: float
    disponible: float
    lotes: List[LoteDelPlan]
    fx_version: str
    tc_blue: float
    tc_venta: float                       # el dólar de C (por la moneda de los lotes, C.4.3)
    tc_pase: float                        # el dólar de V
    dolar_del_dia: float                  # fx_for_date(fecha): pasa V en dólares a pesos
    precio: float
    moneda_precio: str
    fuente: str
    fecha_precio: str
    brokers_a_crear: List[str]            # «· USD» que el confirmar crea (B y el gasto de A)
    gasto: Optional[Dict[str, Any]]       # {monto, moneda, broker, valor_usd, caja_queda_negativa}
    precio_cargado_en_destino: Optional[Dict[str, Any]]
    avisos: List[str] = field(default_factory=list)
    firma: str = ""

    # ── lo que se deriva de los lotes y del precio ──
    @property
    def asset(self) -> str:
        return self.cuentas.asset

    @property
    def moneda(self) -> str:
        return self.cuentas.moneda

    @property
    def fecha(self) -> str:
        return self.cuentas.fecha

    def pares(self) -> List[Dict[str, Any]]:
        """Una entrada por (pata de A → pata de B), en el orden en que aparece en la
        cola FIFO, con sus V y C. Las dos patas de un par guardan estos mismos
        cuatro números (C.4.4)."""
        out: List[Dict[str, Any]] = []
        idx: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for l in self.lotes:
            k = (l.pata_a, l.pata_b)
            if k not in idx:
                idx[k] = {"pata_a": l.pata_a, "pata_b": l.pata_b, "cantidad": 0.0,
                          "asset_type": l.asset_type, "c_usd": 0.0, "c_nativo": 0.0}
                out.append(idx[k])
            p = idx[k]
            p["cantidad"] += l.take
            p["c_usd"] += l.c_usd
            p["c_nativo"] += l.mov_inv + l.mov_com
        for p in out:
            p["v_nativo"], p["v_usd"], p["v_ars"] = valor_del_par(
                p["cantidad"], self.precio, self.moneda_precio, tc_pase=self.tc_pase,
                dolar_del_dia=self.dolar_del_dia)
        return out

    def tramos(self) -> List[Dict[str, Any]]:
        return tramos_de_salida(self.lotes)

    @property
    def valor_nativo(self) -> float:
        return sum(p["v_nativo"] for p in self.pares())

    @property
    def valor_usd(self) -> float:
        return sum(p["v_usd"] for p in self.pares())

    @property
    def valor_ars(self) -> float:
        return sum(p["v_ars"] for p in self.pares())

    @property
    def costo_usd(self) -> float:
        return sum(l.c_usd for l in self.lotes)

    @property
    def patas_tocadas(self) -> List[str]:
        """Las patas donde el pase deja filas (para la cola de las puertas, B.3 paso 8)."""
        out: List[str] = []
        for n in ([l.pata_a for l in self.lotes] + [l.pata_b for l in self.lotes]
                  + ([self.gasto["broker"]] if self.gasto else [])):
            if n and n not in out:
                out.append(n)
        return out

    def valuacion(self) -> Dict[str, Any]:
        """B.1 `ValuacionIn`: lo que la pantalla devuelve al confirmar, tal cual."""
        dolar = self.tc_pase if self.moneda_precio == "ARS" else self.dolar_del_dia
        return {"precio_unitario": self.precio, "moneda_precio": self.moneda_precio,
                "fuente": self.fuente, "fecha_precio": self.fecha_precio, "dolar": dolar}

    def aviso_de_banda(self) -> Optional[str]:
        """El aviso «el precio está muy lejos de lo que pagaste» (B.6), comparando los
        dos en dólares (precio ÷ dólar del pase contra C ÷ cantidad). No frena. Lo
        usan la vista previa y el confirmar, que valúa con el precio que vio la
        persona (`fijar_valuacion`)."""
        if self.costo_usd <= 0 or self.cantidad <= 0:
            return None
        precio_usd = (self.precio / self.tc_pase if self.moneda_precio == "ARS" and self.tc_pase
                      else self.precio)
        k = precio_usd / (self.costo_usd / self.cantidad)
        if BANDA_DEL_PRECIO[0] <= k <= BANDA_DEL_PRECIO[1]:
            return None
        cola = (f"Revisá que esté en {_en_moneda(self.moneda_precio)}."
                if self.fuente == "precio_a_mano"
                else "Si no es correcto, escribí el precio a mano.")
        return (f"El precio de ese día está muy lejos de lo que pagaste (×{_veces(k)}). "
                f"{cola}")

    def fijar_valuacion(self, valuacion) -> None:
        """B.3 paso 5: el confirmar valúa con el precio que la persona vio en la vista
        previa (`valuacion`, la de `para_la_pantalla`), no con el de este instante: el
        último precio se reescribe cada minuto, y con el de ahora V no sería el que
        confirmó. Aceptar el precio del pedido no abre nada nuevo: con `precio_manual`
        ya puede escribir el que quiera.

        Valida (B.6 #29): que venga (400), que el precio esté en la moneda del precio
        de este plan (400 «Precio inválido.»), que el dólar que vio esté a ±3 % del que
        el servidor calcula para esa fecha (409: si no, la vista previa se armó con otra
        historia del dólar) y que la fecha del precio sea un día entre la semana
        anterior y el pase (400 «Precio inválido.»). El dólar con que se escribe es
        SIEMPRE el del servidor: el del pedido sólo se compara. La etiqueta del precio
        tampoco la decide el pedido (ver abajo). V se recalcula solo (sale de
        `pares()`); C no depende del precio."""
        if valuacion is None:
            raise PaseInvalido(400, MSG_FALTA_LA_VISTA)
        v = valuacion if isinstance(valuacion, dict) else valuacion.model_dump()
        if str(v.get("moneda_precio") or "") != self.moneda_precio:
            raise PaseInvalido(400, MSG_PRECIO_INVALIDO)
        servidor = float(self.valuacion()["dolar"] or 0)
        visto = float(v.get("dolar") or 0)
        if servidor <= 0 or abs(visto - servidor) > TOLERANCIA_DEL_DOLAR * servidor:
            raise PaseInvalido(409, MSG_DOLAR_CAMBIO.format(antes=_cotizacion(visto),
                                                            ahora=_cotizacion(servidor)))
        # La fecha del precio tiene que ser un día de verdad, entre la última vela que
        # vale como «el precio de ese día» y el día del pase: la receta la guarda y la
        # leen el deshacer y la revaluación de las patas (C.10).
        fecha_v = str(v.get("fecha_precio") or "")
        desde = (date.fromisoformat(self.fecha) - timedelta(days=DIAS_DE_VELA)).isoformat()
        if not _fecha_valida(fecha_v) or not (desde <= fecha_v <= self.fecha):
            raise PaseInvalido(400, MSG_PRECIO_INVALIDO)
        precio = float(v["precio_unitario"])
        fuente = str(v.get("fuente") or "")
        # La etiqueta del precio no la decide el pedido. Si es el precio del servidor,
        # van su fuente y su fecha. Si no lo es, sólo se conserva la del pedido cuando
        # las dos son de mercado y el precio está cerca del de ahora (el último precio
        # se reescribe cada minuto: es el motivo de que el confirmar use el que vio la
        # persona). Cualquier otro precio es lo que es: uno que vino en el pedido
        # («precio_a_mano», con la fecha del pase).
        if abs(precio - self.precio) <= 1e-9 * max(1.0, abs(self.precio)):
            fuente, fecha_v = self.fuente, self.fecha_precio
        elif not (fuente in _FUENTES_DE_MERCADO and self.fuente in _FUENTES_DE_MERCADO
                  and self.precio > 0 and 0.5 <= precio / self.precio <= 2.0):
            fuente, fecha_v = "precio_a_mano", self.fecha
        banda_antes = self.aviso_de_banda()
        self.precio = precio
        self.fuente = fuente
        self.fecha_precio = fecha_v
        self.avisos = [a for a in self.avisos if a != banda_antes]
        banda = self.aviso_de_banda()
        if banda:
            self.avisos.append(banda)

    # ── las filas que el confirmar va a aplicar (A.6, C.6) ──
    def filas(self, traspaso_id: str):
        """(filas del lote de A, filas del lote de B), como `NormalizedTx`, con el id
        del pase en todas. El orden es el de C.6 y `row_index` cuenta desde -49999
        en cada lote, así el orden del persister coincide con el `n.id` del rebuild."""
        from importing.schema import (NormalizedTx, OP_BUY, OP_SELL, OP_FEE,
                                      OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA)
        from behavioral import _native_ccy
        from fx import costo_del_lote
        f, asset, dd = self.fecha, self.asset, _ddmmaaaa(self.fecha)
        filas_a: List[Any] = []
        filas_b: List[Any] = []

        def _fila(lista, **kw):
            lista.append(NormalizedTx(row_index=BASE_ROW_INDEX + len(lista), date=f,
                                      traspaso_id=traspaso_id, **kw))

        for t in self.tramos():
            _fila(filas_a, broker=t["pata"], operation_type=OP_SELL, asset_symbol=asset,
                  asset_type=t["asset_type"], quantity=t["cantidad"], unit_price=0.0,
                  gross_amount=0.0, fees=0.0, currency=self.moneda, transfer_out=True,
                  costo_nativo=t["inv"], notes=NOTA_SALIDA_IMPORTADOS.format(fecha=dd))
        pares = self.pares()
        for p in pares:
            _fila(filas_a, broker=p["pata_a"], operation_type=OP_TRASPASO_SALIDA,
                  asset_symbol=asset, asset_type=p["asset_type"], quantity=p["cantidad"],
                  unit_price=self.precio, gross_amount=None, fees=0.0, currency=self.moneda,
                  valor_usd=p["v_usd"], valor_ars=p["v_ars"], costo_usd=p["c_usd"],
                  costo_nativo=p["c_nativo"],
                  notes=NOTA_PATA_SALIDA.format(q=_cant(p["cantidad"]), asset=asset))
        if self.gasto:
            g = self.gasto
            _fila(filas_a, broker=g["broker"], operation_type=OP_FEE, gross_amount=g["monto"],
                  fees=0.0, currency=g["moneda"], valor_usd=g["valor_usd"],
                  notes=NOTA_GASTO.format(asset=asset))
        for l in self.lotes:
            lote = l.lote
            qty = float(lote.get("quantity") or 0)
            precio = lote.get("buy_price")
            if precio is None:
                base = costo_del_lote(lote.get("invested"), lote.get("buy_price"), qty) or 0.0
                precio = base / qty if qty else 0.0
            _fila(filas_b, broker=l.pata_b, operation_type=OP_BUY, asset_symbol=asset,
                  asset_type=l.asset_type, asset_name=l.asset_name, quantity=l.take,
                  unit_price=float(precio), gross_amount=l.mov_inv, fees=l.mov_com,
                  currency=_native_ccy(dict(lote)), tc_compra=lote.get("tc_compra"),
                  fecha_compra=l.entry_date,
                  notes=NOTA_LLEGADA.format(fecha=dd, compra=_ddmmaaaa(l.entry_date)))
        for p in pares:
            _fila(filas_b, broker=p["pata_b"], operation_type=OP_TRASPASO_ENTRADA,
                  asset_symbol=asset, asset_type=p["asset_type"], quantity=p["cantidad"],
                  unit_price=self.precio, gross_amount=None, fees=0.0, currency=self.moneda,
                  valor_usd=p["v_usd"], valor_ars=p["v_ars"], costo_usd=p["c_usd"],
                  costo_nativo=p["c_nativo"],
                  notes=NOTA_PATA_ENTRADA.format(q=_cant(p["cantidad"]), asset=asset))
        return filas_a, filas_b

    def receta(self) -> Dict[str, Any]:
        """`traspasos_a_mano.receta_json`, versión 1 (A.2), sin lo que sólo se sabe al
        escribir: `fila_destino_raw_row_id` de cada lote lo completa el confirmar con
        `load_session_for_confirm` del lote de B (C.7.5)."""
        fotos = ("id", "broker", "asset", "quantity", "invested", "commissions", "buy_price",
                 "entry_date", "currency", "tc_compra", "asset_type", "notes",
                 "undo_meta_json", "price_override", "split_adjusted_through",
                 "en_broker_desde")
        return {
            "v": 1,
            "broker_origen": self.cuentas.raiz_a,
            "broker_destino": self.cuentas.raiz_b,
            "fx_version": self.fx_version,
            "lotes": [{
                "origen": l.origen, "lote_id": l.lote_id, "broker": l.pata_a,
                "broker_destino": l.pata_b, "fila_origen": l.fila_origen,
                "fila_destino_raw_row_id": None,
                "cantidad": l.take, "invested": l.mov_inv, "commissions": l.mov_com,
                "parcial": l.parcial,
                "foto": {c: l.lote.get(c) for c in fotos},
            } for l in self.lotes],
            "gasto": ({"broker": self.gasto["broker"], "monto": self.gasto["monto"],
                       "moneda": self.gasto["moneda"]} if self.gasto else None),
            "precio": {"unitario": self.precio, "moneda": self.moneda_precio,
                       "fuente": self.fuente, "fecha": self.fecha_precio},
            "valor_nativo": self.valor_nativo, "valor_usd": self.valor_usd,
            "valor_ars": self.valor_ars, "costo_usd": self.costo_usd,
            "tc_pase": self.tc_pase, "tc_venta": self.tc_venta,
            "brokers_usd_creados": list(self.brokers_a_crear),
            "precio_cargado_en_destino": self.precio_cargado_en_destino,
        }

    def para_la_pantalla(self) -> Dict[str, Any]:
        """La respuesta de la vista previa (B.2). Los nombres son los que lee la
        pantalla (`VistaPreviaDelPase`, `MoverDeBrokerModal`, `moverDeBroker.js`)."""
        c = self.cuentas
        V, C = self.valor_usd, self.costo_usd
        return {
            "ok": True,
            "origen": {"cuenta": c.raiz_a, "etiqueta": f"{c.raiz_a} · en {_en_moneda(c.moneda)}"},
            "destino": {"cuenta": c.raiz_b,
                        "brokers_a_crear": [n for n in self.brokers_a_crear
                                            if n == f"{c.raiz_b} · USD"]},
            "asset": c.asset, "moneda": c.moneda, "fecha": c.fecha,
            "cantidad": self.cantidad, "cantidad_disponible": self.disponible,
            "lotes": [{"lote_id": l.lote_id, "a_mano": l.origen == "a_mano",
                       "fecha_compra": l.entry_date, "cantidad": l.take,
                       "de_un_lote_de": float(l.lote.get("quantity") or 0),
                       "costo": round(l.mov_inv, 2), "comisiones": round(l.mov_com, 2),
                       "moneda": l.moneda, "broker_origen": l.pata_a,
                       "broker_destino": l.pata_b} for l in self.lotes],
            "valuacion": self.valuacion(),
            "valor_nativo": round(self.valor_nativo, 2), "valor_ars": round(self.valor_ars, 2),
            "valor_usd": round(V, 2), "costo_usd": round(C, 2), "puente_usd": round(V - C, 2),
            "gasto": ({"monto": self.gasto["monto"], "moneda": self.gasto["moneda"],
                       "broker": self.gasto["broker"],
                       "caja_queda_negativa": self.gasto["caja_queda_negativa"]}
                      if self.gasto else None),
            "avisos": list(self.avisos),
            "firma": self.firma,
        }


def tramos_de_salida(lotes: List[LoteDelPlan]) -> List[Dict[str, Any]]:
    """Las SELL de salida de los lotes IMPORTADOS: una por tramo contiguo de la cola
    FIFO que vive en la misma pata (A.6, nota 1: [hija 5, padre 3, hija 2] → tres SELL,
    en ese orden, así cada una consume justo los lotes de su pata). Los cargados a
    mano salen por `positions` y no tienen fila. La usan las filas del plan y la
    comprobación en seco contra el registro: las mismas salidas en los dos."""
    out: List[Dict[str, Any]] = []
    for l in lotes:
        if l.origen != "importado":
            continue
        if out and out[-1]["pata"] == l.pata_a:
            t = out[-1]
        else:
            t = {"pata": l.pata_a, "cantidad": 0.0, "inv": 0.0, "asset_type": l.asset_type,
                 "lotes": []}
            out.append(t)
        t["cantidad"] += l.take
        t["inv"] += l.mov_inv
        t["lotes"].append(l)
    return out


def firma_del_plan(lotes: List[LoteDelPlan], fecha: str, moneda: str, raiz_b: str,
                   gasto: Optional[Dict[str, Any]]) -> str:
    """C.9. Sin precio ni dólar: el último precio se reescribe cada minuto y con él
    adentro el confirmar daba «tu cartera cambió» sin que nada cambiara. El precio
    viaja aparte (`valuacion`). Frena el doble envío: después del primer pase, los
    lotes de A ya no son los mismos.

    Lleva también la cantidad que el lote tenía ANTES del pase (no está en la lista
    de C.9): en un pase PARCIAL el segundo envío arma un plan con el mismo lote, la
    misma cantidad y el mismo costo en proporción —4 de 10 y después 4 de 6 cuestan
    lo mismo—, y sin esto el segundo click hacía un segundo pase."""
    datos = [[[l.lote_id, round(float(l.lote.get("quantity") or 0), 9), round(l.take, 9),
               l.entry_date, round(l.mov_inv, 9), round(l.mov_com, 9), l.pata_b]
              for l in lotes],
             fecha, moneda, raiz_b,
             ({"monto": round(float(gasto["monto"]), 9), "moneda": gasto["moneda"]}
              if gasto else None)]
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()[:16]


# ── lo que va a la red, antes de cualquier candado ─────────────────────────────

def precargar(conn, uid: int, pedido, *, helpers) -> None:
    """Trae a las cachés lo que `armar_plan` va a necesitar de internet (B.3 paso 0):
    los cambios de ratio de Yahoo del activo (sólo si algún lote de A los puede
    tener) y, para una cripto, el dólar cripto. Nunca falla: si la red no contesta,
    `armar_plan` decide con lo que haya (sin dólar cripto, «sin precio»)."""
    asset = str(getattr(pedido, "asset", "") or "").strip().upper()
    if not asset:
        return
    try:
        import snapshots_job
        from cripto import is_exchange_broker
        from importing.persister import broker_pair
        fila = conn.execute(
            "SELECT id, name, parent_broker_id FROM brokers WHERE user_id=? AND name=?",
            (uid, str(getattr(pedido, "broker_origen", "") or "").strip())).fetchone()
        if not fila:
            return
        raiz = fila["name"]
        if fila["parent_broker_id"]:
            p = conn.execute("SELECT name FROM brokers WHERE user_id=? AND id=?",
                             (uid, fila["parent_broker_id"])).fetchone()
            raiz = p["name"] if p else raiz
        patas = broker_pair(conn, uid, raiz)
        if asset in snapshots_job._crypto_symbol_set():
            # El dólar cripto sólo hace falta para una cripto en una cuenta EN PESOS
            # que no es un exchange (C.4.2 c).
            en_pesos = conn.execute(
                f"SELECT name FROM brokers WHERE user_id=? AND name IN ({_ph(patas)}) "
                f"AND currency='ARS'", (uid, *patas)).fetchall()
            if any(not is_exchange_broker(r["name"]) for r in en_pesos):
                helpers._get_dolar_data()
            return
        lotes = conn.execute(
            f"SELECT * FROM positions WHERE user_id=? AND broker IN ({_ph(patas)}) AND asset=? "
            f"AND is_cash=0 AND quantity > 0", (uid, *patas, asset)).fetchall()
        if any(helpers._por_que_no_se_ajusta_el_ratio(conn, uid, l) is None for l in lotes):
            base = asset[:-3] if asset.endswith(".BA") else asset
            helpers._fetch_ba_splits(f"{base}.BA", conn)
    except Exception as ex:  # la red o una tabla que falta: armar_plan decide sin esto
        log.warning("traspaso_a_mano.precargar: %s", ex)


# ── las validaciones que miran el registro (B.6 #12–#16) ───────────────────────

def _traspaso_automatico_ya_cerrado(conn, uid, c: Cuentas):
    """B.6 #12: el importador ya cerró este activo de A hacia B (la SELL «Traspaso a
    {B}» que escribe el cruce automático, sin `traspaso_id`) a ±4 días."""
    from importing.traspasos import destino_de
    import renombre_broker
    nombres_b = {_clave_nombre(n) for n in c.patas_b}
    anteriores = renombre_broker.nombres_anteriores(conn, uid)
    for n in c.patas_b:
        nombres_b |= {_clave_nombre(x) for x in anteriores.get(_clave_nombre(n), [])}
    for r in conn.execute(
            f"""SELECT substr(n.date, 1, 10) AS d, n.notes AS notes FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND n.broker IN ({_ph(c.patas_a)})
                   AND n.asset_symbol = ? AND n.operation_type = 'SELL'
                   AND n.traspaso_id IS NULL AND n.notes LIKE '%Traspaso a %'
                 ORDER BY substr(n.date, 1, 10) DESC, n.id DESC""",
            (uid, *c.patas_a, c.asset)).fetchall():
        if (_clave_nombre(destino_de(r["notes"])) in nombres_b
                and _dias_entre(r["d"], c.fecha) <= 4):
            return r["d"]
    return None


def _llegadas_importadas_en_b(conn, uid, c: Cuentas):
    """Las ENTRADAS de este activo que B ya trae de un archivo (`transfer_in` o la
    marca IEB:DETR), sin pase: [(fecha, cantidad)], la más nueva primero."""
    return [(r["d"], float(r["q"] or 0)) for r in conn.execute(
        f"""SELECT substr(n.date, 1, 10) AS d, n.quantity AS q FROM {TX_VIVAS}
             WHERE b.user_id = ? AND n.broker IN ({_ph(c.patas_b)})
               AND n.asset_symbol = ? AND n.operation_type = 'BUY'
               AND n.traspaso_id IS NULL
               AND (COALESCE(n.transfer_in, 0) = 1 OR n.notes LIKE '%IEB:DETR%')
             ORDER BY substr(n.date, 1, 10) DESC, n.id DESC""",
        (uid, *c.patas_b, c.asset)).fetchall()]


def _capital_declarado_despues(conn, uid, c: Cuentas):
    """B.6 #14: (pata, año, mes) del primer renglón de A o de B en `monthly_entries`
    si arranca DESPUÉS del mes del pase con un capital inicial cargado a mano.
    `_repair_monthly_chain` nunca toca el primer renglón: uno más viejo lo volvería
    segundo y le pisaría el capital declarado con el de la cadena."""
    mes_pase = (int(c.fecha[:4]), int(c.fecha[5:7]))
    for pata in c.patas_a + c.patas_b:
        r = conn.execute(
            "SELECT year, month, capital_inicio FROM monthly_entries "
            "WHERE user_id=? AND broker=? ORDER BY year ASC, month ASC, id ASC LIMIT 1",
            (uid, pata)).fetchone()
        if r and abs(float(r["capital_inicio"] or 0)) > 0.005 \
                and mes_pase < (int(r["year"]), int(r["month"])):
            return pata, int(r["year"]), int(r["month"])
    return None


def _contraparte_de_pase(conn, uid, traspaso_id) -> str:
    """El broker de destino de un pase (el nombre de hoy, por su lote de entrada)."""
    r = conn.execute(
        """SELECT b.broker AS broker, t.receta_json AS receta FROM traspasos_a_mano t
             LEFT JOIN import_batches b ON b.id = t.lote_entrada AND b.user_id = t.user_id
            WHERE t.id = ? AND t.user_id = ?""", (traspaso_id, uid)).fetchone()
    if not r:
        return "otro broker"
    if r["broker"]:
        return r["broker"]
    try:
        return json.loads(r["receta"] or "{}").get("broker_destino") or "otro broker"
    except (TypeError, ValueError):
        return "otro broker"


def _salida_posterior(conn, uid, patas, asset, fecha, *, desde_el_mismo_dia=False):
    """El último movimiento que sacó `asset` de esas patas DESPUÉS de `fecha` (o
    desde ese mismo día, con `desde_el_mismo_dia`): una 'Venta' de `operations` o
    una SELL viva del registro (las de un pase llevan `traspaso_id`). None si no
    hay. Devuelve {fecha, traspaso_id}.

    `desde_el_mismo_dia` es para B (#16). Una venta de B del MISMO día del pase que
    ya estaba consumió, cuando se guardó, un lote propio de B; el próximo rebuild de
    B ordena el mismo día «la compra antes que la venta» y, por fecha de compra
    (H2), la haría consumir el lote que llegó, que es más viejo: cambiarían los
    lotes y el resultado de esa venta sin que nadie haga nada. En A no pasa: las dos
    salidas del mismo día se ordenan por id y la del pase va después."""
    mejor = None
    op = ">=" if desde_el_mismo_dia else ">"
    r = conn.execute(
        f"SELECT MAX(substr(date, 1, 10)) AS d FROM operations WHERE user_id=? "
        f"AND broker IN ({_ph(patas)}) AND asset=? AND op_type='Venta' "
        f"AND substr(date, 1, 10) {op} ?", (uid, *patas, asset, fecha)).fetchone()
    if r and r["d"]:
        mejor = {"fecha": r["d"], "traspaso_id": None}
    for s in conn.execute(
            f"""SELECT substr(n.date, 1, 10) AS d, n.traspaso_id AS tid FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND n.broker IN ({_ph(patas)})
                   AND n.asset_symbol = ? AND n.operation_type = 'SELL'
                   AND substr(n.date, 1, 10) {op} ?
                 ORDER BY substr(n.date, 1, 10) DESC, n.id DESC""",
            (uid, *patas, asset, fecha)).fetchall():
        # La más nueva gana; a igual fecha, la de un pase (su texto pide deshacerlo).
        if mejor is None or s["d"] > mejor["fecha"] or (
                s["d"] == mejor["fecha"] and s["tid"] and not mejor["traspaso_id"]):
            mejor = {"fecha": s["d"], "traspaso_id": s["tid"]}
    return mejor


def _salida_importada_cerca(conn, uid, c: Cuentas):
    """B.6 #17, la segunda forma: A ya trae de su archivo la salida del activo (una
    SELL `transfer_out` sin pase a ±60 días). Las de una foto de tenencia
    («Tenencia …») no cuentan: no son la salida de un traspaso."""
    mejor = None
    for r in conn.execute(
            f"""SELECT substr(n.date, 1, 10) AS d FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND n.broker IN ({_ph(c.patas_a)})
                   AND n.asset_symbol = ? AND n.operation_type = 'SELL'
                   AND COALESCE(n.transfer_out, 0) = 1 AND n.traspaso_id IS NULL
                   AND COALESCE(n.notes, '') NOT LIKE 'Tenencia%'
                 ORDER BY substr(n.date, 1, 10) DESC, n.id DESC""",
            (uid, *c.patas_a, c.asset)).fetchall():
        dd = _dias_entre(r["d"], c.fecha)
        if dd <= DIAS_TRASPASO_TARDIO and (mejor is None or dd < mejor[0]):
            mejor = (dd, r["d"])
    return mejor[1] if mejor else None


# ── C.2.6: la comprobación contra el registro, en seco ─────────────────────────

_ID_EN_SECO = "pase-en-seco"


def _replay_en_seco(conn, uid, c: Cuentas, tramos, *, hist: bool, tc_blue: float):
    """El registro de A replayado como lo haría el próximo rebuild, con las SELL del
    pase agregadas (eventos en memoria, nada se escribe). Devuelve (replay con las
    salidas, replay sin ellas)."""
    from importing import rebuild as rb
    eventos = rb._full_events(conn, uid, c.patas_a, c.asset)
    tope = max((int(e["id"]) for e in eventos), default=0)
    sinteticos = [{
        "id": tope + 1 + k, "batch_id": None, "raw_row_id": None, "date": c.fecha,
        "broker": t["pata"], "asset_symbol": c.asset, "asset_name": None,
        "operation_type": "SELL", "quantity": t["cantidad"], "unit_price": 0.0,
        "gross_amount": 0.0, "fees": 0.0, "currency": c.moneda,
        "asset_type": t["asset_type"], "transfer_out": 1, "created_position_id": None,
        "tc_compra": None, "traspaso_id": _ID_EN_SECO, "fecha_compra": None,
    } for k, t in enumerate(tramos)]
    # El orden de `_full_events`: fecha, la compra antes que la venta, id.
    orden = lambda e: (str(e["date"]), 0 if e["operation_type"] == "BUY" else 1, int(e["id"]))
    moneda_cuenta = rb._moneda_del_par(conn, uid, c.patas_a)
    exchange = any(rb._is_exchange_broker(b) for b in c.patas_a)

    def _correr(evs):
        evs = sorted(evs, key=orden)
        return rb._replay_asset(rb._cancel_conduit_pairs(evs, is_exchange=exchange),
                                moneda_cuenta, tc_blue, use_hist=hist, conn=conn,
                                is_exchange=exchange)
    return _correr(eventos + sinteticos), _correr(list(eventos))


def _coinciden(plan_items, registro_items) -> bool:
    """Multiconjunto de (fecha de compra, cantidad, inversión, comisiones), con
    tolerancia 1e-6 en la cantidad y 1e-4 relativo en los montos (C.2.6)."""
    def _monto_igual(a, b):
        a, b = float(a or 0), float(b or 0)
        return abs(a - b) <= max(1e-6, 1e-4 * max(abs(a), abs(b)))
    libres = list(registro_items)
    for p in plan_items:
        hallado = None
        for i, r in enumerate(libres):
            if (str(r["entry_date"] or "")[:10] == p["entry_date"]
                    and abs(float(r["qty"] or 0) - p["qty"]) <= 1e-6
                    and _monto_igual(r["invested"], p["invested"])
                    and _monto_igual(r["commissions"], p["commissions"])):
                hallado = i
                break
        if hallado is None:
            return False
        libres.pop(hallado)
    return not libres


def _que_cambio(lote: Dict[str, Any], reg: Dict[str, Any]) -> List[str]:
    """Qué campos de un lote importado difieren de lo que dice su archivo."""
    out = []
    if abs(float(reg.get("qty") or 0) - float(lote.get("quantity") or 0)) > 1e-6:
        out.append("cantidad")
    a, b = float(reg.get("invested") or 0), float(lote.get("invested") or 0)
    ca, cb = float(reg.get("commissions") or 0), float(lote.get("commissions") or 0)
    if (abs(a - b) > max(1e-6, 1e-4 * max(abs(a), abs(b)))
            or abs(ca - cb) > max(1e-6, 1e-4 * max(abs(ca), abs(cb)))):
        out.append("costo")
    if str(reg.get("entry_date") or "")[:10] != str(lote.get("entry_date") or "")[:10]:
        out.append("fecha")
    return out


def _y(partes: List[str]) -> str:
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def _comprobar_con_el_registro(conn, uid, c: Cuentas, lotes: List[LoteDelPlan],
                               tramos, *, hist: bool, tc_blue: float) -> None:
    """B.6 #23. Si A va a quedar «a salvo» después del pase (todo lo que le queda de
    este activo vino de archivos), el próximo rebuild lo va a rearmar desde el
    registro: el registro, con las salidas del pase, tiene que llevarse justo los
    lotes importados que el plan mueve. Si no, el persister movería un lote (el que
    se ve) y el rebuild consumiría otro (el del archivo)."""
    from importing import rebuild as rb
    se_van_enteros = [l.lote_id for l in lotes if not l.parcial]
    if not rb._is_safe_to_rebuild(conn, uid, c.patas_a, c.asset, sin_lotes=se_van_enteros):
        return   # A sigue con lotes cargados a mano: manda `positions` (C.2.7)
    importados = [l for l in lotes if l.origen == "importado"]
    con_salida, sin_salida = _replay_en_seco(conn, uid, c, tramos, hist=hist, tc_blue=tc_blue)
    plan_items = [{"entry_date": l.entry_date, "qty": l.take, "invested": l.mov_inv,
                   "commissions": l.mov_com} for l in importados]
    if _coinciden(plan_items, con_salida["traspasos"].get(_ID_EN_SECO, [])):
        return
    A = c.raiz_a
    registro = {(l.get("batch_id"), l.get("raw_row_id")): l for l in sin_salida["open_lots"]
                if l.get("batch_id")}
    for l in importados:
        fo = l.fila_origen or {}
        reg = registro.get((fo.get("batch_id"), fo.get("raw_row_id")))
        cambios = _que_cambio(l.lote, reg) if reg else []
        if cambios:
            raise PaseInvalido(409, (
                f"El lote de {c.asset} del {_ddmmaaaa(l.entry_date)} en {A} vino de un archivo "
                f"y lo cambiaste a mano ({_y(cambios)}). Rendi arma {A} desde tus archivos, así "
                "que el pase no cuadraría. Para corregirlo de forma que quede: Importaciones → "
                "ese archivo → «Editar y rehacer», corregí la fila y volvé a moverlo."))
    raise PaseInvalido(409, (f"En {A} los lotes de {c.asset} no coinciden con tus archivos, así "
                             "que no podemos saber cuáles pasar. Escribinos y lo revisamos."))


# ── C.4: el precio del día ─────────────────────────────────────────────────────

def _sin_precio(asset, fecha, moneda_precio):
    return PaseInvalido(409, {
        "codigo": "sin_precio",
        "mensaje": (f"No encontramos a cuánto cotizaba {asset} el {_ddmmaaaa(fecha)}. Escribí "
                    f"el precio de ese día (en {_en_moneda(moneda_precio)}) para calcular "
                    "cuánto valía lo que pasaste."),
        "moneda_precio": moneda_precio,
    })


def _simbolo_de_velas(clave: str) -> str:
    """El símbolo con que `velas_diarias` guarda la serie de una clave de precio: el
    de Yahoo ('NVDA.BA' igual, 'BTC' → 'BTC-USD', 'DISN' → 'DIS')."""
    if clave.endswith(".BA"):
        return clave
    from cripto import yahoo_de_cripto
    import velas_diarias
    return yahoo_de_cripto(clave) or velas_diarias.ticker_de_afuera(clave)


def _moneda_del_precio_cargado(lote: Dict[str, Any], pata: str,
                               brokers: List[Dict[str, Any]]) -> str:
    """En qué moneda lee Cartera el precio cargado a mano (`price_override`) de este
    lote si vive en `pata`. Es la regla de la valuación (`snapshots_job.
    compute_broker_value_usd` y `valuation.js`), y NO la de la clave de precio:
      · una cripto: el spot en dólares (también en una cuenta en pesos: con precio
        cargado no lleva el factor del dólar cripto, `crypto_broker_factor`);
      · un lote en dólares en una cuenta en dólares (un CEDEAR en «Cocos · USD»): en
        dólares, aunque su clave de precio sea la .BA en pesos;
      · todo lo demás (un lote en pesos, o uno en dólares en una cuenta en pesos,
        que se valúa por su .BA): en pesos.
    Una pata que todavía no existe (la «· USD» que el confirmar va a crear) es una
    cuenta en dólares."""
    import snapshots_job
    from behavioral import _native_ccy
    if str(lote.get("asset") or "").upper() in snapshots_job._crypto_symbol_set():
        return "USD"
    fila = next((b for b in brokers if b["name"] == pata), None)
    en_pesos = bool(fila) and (fila.get("currency") or "").upper() == "ARS"
    return "USD" if (not en_pesos and _native_ccy(dict(lote)) == "USD") else "ARS"


def _buscar_precio(conn, c: Cuentas, lotes: List[LoteDelPlan], pedido, *, hoy, clave,
                   moneda_precio, cripto_en_pesos, helpers):
    """(precio unitario, moneda del precio, fuente, fecha del precio, aviso | None),
    en el orden de C.4.2. Todo de la base salvo el dólar cripto, que trajo `precargar`."""
    import snapshots_job
    if getattr(pedido, "precio_manual", None):
        return float(pedido.precio_manual), moneda_precio, "precio_a_mano", c.fecha, None
    if c.fecha == hoy:
        for l in lotes:
            if l.lote.get("price_override") is not None:
                # El precio que la persona cargó a mano, en la moneda en que lo lee
                # Cartera en la pata donde vive el lote (no en la de la clave de
                # precio: un CEDEAR en «Cocos · USD» lo tiene en dólares).
                moneda = _moneda_del_precio_cargado(l.lote, l.pata_a, c.brokers)
                return float(l.lote["price_override"]), moneda, "precio_cargado", hoy, None
    fresco = (date.fromisoformat(hoy) - timedelta(days=DIAS_DE_PRECIO_FRESCO)).isoformat()
    if cripto_en_pesos:
        # No hay dólar cripto de otros días: con fecha pasada, sólo a mano y en pesos.
        if c.fecha == hoy:
            spot = snapshots_job.read_last_prices(conn, [c.asset], fresh_since=fresco).get(c.asset)
            dolar_cripto = helpers._current_cripto_rate()
            if spot and dolar_cripto:
                return float(spot) * float(dolar_cripto), "ARS", "ultimo_precio", hoy, None
        raise _sin_precio(c.asset, c.fecha, "ARS")
    if c.fecha == hoy:
        p = snapshots_job.read_last_prices(conn, [clave], fresh_since=fresco).get(clave)
        if p and float(p) > 0:
            return float(p), moneda_precio, "ultimo_precio", hoy, None
    import velas_diarias
    desde = (date.fromisoformat(c.fecha) - timedelta(days=DIAS_DE_VELA + 3)).isoformat()
    velas = [v for v in velas_diarias.serie(conn, _simbolo_de_velas(clave), desde)
             if str(v.get("date"))[:10] <= c.fecha and v.get("close")
             and float(v["close"]) > 0 and _dias_entre(v["date"], c.fecha) <= DIAS_DE_VELA]
    if velas:
        v = velas[-1]
        dia = str(v["date"])[:10]
        if dia == c.fecha:
            return float(v["close"]), moneda_precio, "cierre_del_dia", dia, None
        return (float(v["close"]), moneda_precio, "ultimo_precio", dia,
                f"Usamos el cierre del {_dia_de_la_semana(dia)}.")
    raise _sin_precio(c.asset, c.fecha, moneda_precio)


def _aviso_de_la_pata_a_crear(conn, uid: int, nombre: str, cuenta: str, para: str) -> str:
    """El aviso de la «· USD» que el confirmar va a crear (C.1.3, #24), o el 409 si ya
    existe un broker con ese nombre SUELTO y con movimientos.

    Si existe con ese nombre es que no es la pata de la cuenta (si lo fuera, el plan
    la usaría y no la crearía), y el confirmar lo ADOPTA (`_ensure_usd_sibling`: le
    pone el padre y lo pasa a dólares; `por_que_no_hay_pata_usd` ya frenó al que
    está en pesos con datos o es de otro). El plan no miró sus ventas (#16), sus
    llegadas (#13), su capital declarado (#14) ni sus lotes: una venta suya
    posterior pasaba a consumir el lote que llegó, más viejo, en el próximo rebuild;
    y del lado de A, la salida del pase podía llevarse un lote suyo. Vacío, adoptarlo
    no cambia nada: se avisa que se suma."""
    from importing import pipeline
    if not conn.execute("SELECT 1 FROM brokers WHERE user_id=? AND name=?",
                        (uid, nombre)).fetchone():
        return f"Vamos a crear «{nombre}» para {para}."
    if pipeline.broker_tiene_datos(conn, uid, nombre) or conn.execute(
            "SELECT 1 FROM flujos_a_mano WHERE user_id=? AND broker=? LIMIT 1",
            (uid, nombre)).fetchone():
        raise PaseInvalido(409, MSG_PATA_SUELTA.format(nombre=nombre, cuenta=cuenta))
    return f"Vamos a sumar tu broker «{nombre}» como la cuenta en dólares de {cuenta}."


# ── C.4.3–C.5: los dólares, V y C de un pase (UNA sola cuenta) ──────────────────
#
# La usan `armar_plan` (al armar el pase) y `revaluar_patas` (cuando la cuenta pasa
# del dólar vivo al histórico, C.10). Para el mismo pase y la misma versión del dólar
# las dos tienen que dar EXACTAMENTE lo mismo: si no, la migración dejaría patas que
# un pase hecho después de migrar no escribiría (es la regla de propagación de
# CLAUDE.md; antes la cuenta vivía adentro de `armar_plan`).

def dolares_del_pase(conn, fecha: str, moneda: str, moneda_precio: str, *, hist: bool,
                     tc_blue: float) -> Dict[str, float]:
    """C.4.3, los dos dólares del pase:
      · `tc_venta`, el de C: por la moneda de los LOTES, como el persister (un lote en
        dólares → 1; en pesos → el dólar del día en una cuenta v2, el de la config en
        una v1);
      · `tc_pase`, el de V: precio en dólares → 1; precio en pesos de un lote en pesos
        → el mismo `tc_venta` (así el puente es justo el resultado de vender a V ese
        día); precio en pesos de un lote en dólares (un CEDEAR en dólares, que Cartera
        valúa .BA ÷ MEP) → el dólar del día, en las dos versiones.
    Más `dolar_del_dia` (pasa a pesos un V en dólares) y `tc_pesos` (el de los pesos
    según la versión: lo usa también el gasto). `tc_blue` es el de la config en v1 y,
    en v2, sólo el respaldo de una fecha que no está en la serie."""
    import fx
    dolar_del_dia = fx.fx_for_date(conn, fecha, fallback=tc_blue) or tc_blue
    tc_pesos = dolar_del_dia if hist else tc_blue
    tc_venta = 1.0 if moneda == "USD" else tc_pesos
    if moneda_precio == "USD":
        tc_pase = 1.0
    elif moneda == "ARS":
        tc_pase = tc_venta
    else:
        tc_pase = dolar_del_dia
    return {"dolar_del_dia": dolar_del_dia, "tc_pesos": tc_pesos, "tc_venta": tc_venta,
            "tc_pase": tc_pase}


def valor_del_par(cantidad: float, precio: float, moneda_precio: str, *, tc_pase: float,
                  dolar_del_dia: float) -> Tuple[float, float, float]:
    """C.4.4: (V en la moneda del precio, V en dólares, V en pesos) de `cantidad`
    títulos a `precio`. Las dos patas del par guardan estos mismos números."""
    v_nativo = cantidad * precio
    if moneda_precio == "ARS":
        return v_nativo, (v_nativo / tc_pase if tc_pase else 0.0), v_nativo
    return v_nativo, v_nativo, v_nativo * dolar_del_dia


def costo_usd_de_lo_movido(conn, lote: Dict[str, Any], take: float, moneda_lote: str, *,
                           precio: float, moneda_precio: str, dolares: Dict[str, float],
                           tc_blue: float, hist: bool, fecha: str) -> float:
    """C.5: C (en dólares, comisiones incluidas) de tomar `take` títulos de `lote` (la
    fila de `positions` tal como estaba antes del pase: en la receta, su `foto`), con la
    cuenta única del tramo (`importing/tramo.py`): la misma con que el persister y el
    rebuild costean una venta. En una cuenta v2 es el costo al dólar de la COMPRA
    (`tc_compra` del lote o, si no tiene, el de su fecha); en una v1, al de la config."""
    from importing.tramo import costo_y_resultado_del_tramo
    tc_pase, dolar_del_dia = dolares["tc_pase"], dolares["dolar_del_dia"]
    if moneda_precio == moneda_lote:
        precio_en_su_moneda = precio
    elif moneda_precio == "ARS":
        precio_en_su_moneda = precio / tc_pase if tc_pase else 0.0
    else:
        precio_en_su_moneda = precio * dolar_del_dia
    t = costo_y_resultado_del_tramo(
        conn, lote={**lote, "currency": lote.get("currency") or moneda_lote},
        take=take, currency=moneda_lote, sell_currency=moneda_lote,
        exit_price=precio_en_su_moneda, chunk_commission=0.0, tc_venta=dolares["tc_venta"],
        tc_blue=tc_blue, hist=hist, op_date=fecha, transfer_out=False)
    return float(t["invested_usd"] or 0)


def gasto_en_usd(monto: float, moneda: str, tc_pesos: float) -> float:
    """El gasto del pase en dólares (la `valor_usd` de su FEE): en pesos, al dólar de
    los pesos de la versión (`dolares_del_pase()["tc_pesos"]`)."""
    if moneda == "USD":
        return monto
    return monto / tc_pesos if tc_pesos else 0.0


# ── armar_plan ─────────────────────────────────────────────────────────────────

def lotes_del_activo(conn, uid: int, patas, asset: str) -> List[Dict[str, Any]]:
    """Los lotes abiertos de `asset` en esas patas, en el orden FIFO del persister
    (`persister.py`): el más viejo primero, los sin fecha al final. Los usan el pase
    (`armar_plan`) y el «tal cual» (`main._plan_tal_cual`): la misma fila de Cartera."""
    return [dict(r) for r in conn.execute(
        f"""SELECT * FROM positions
             WHERE user_id=? AND broker IN ({_ph(patas)}) AND asset=? AND is_cash=0
               AND quantity > 0
             ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
        (uid, *patas, asset)).fetchall()]


def armar_plan(conn, uid: int, pedido, *, hoy: str, helpers, para_confirmar: bool,
               cuentas: Optional[Cuentas] = None) -> Plan:
    """B.6 (en ese orden), C.1–C.6 y C.9. Sólo LEE: la vista previa la llama sin
    candado y el confirmar dentro de su transacción, con los lotes ya tomados.
    `pedido`: un `PaseIn` (o cualquier objeto con sus campos). Levanta
    `PaseInvalido` con el status y el texto de B.6."""
    import fx
    import snapshots_job
    import tickers_renombrados
    from behavioral import _native_ccy
    from cripto import is_exchange_broker
    from importing import pipeline
    from importing.maturity import is_bond_like_name
    try:
        from ai.ar_bonds_metadata import is_known_ar_bond
    except Exception:  # pragma: no cover
        def is_known_ar_bond(_t):
            return False

    c = cuentas or cuentas_del_pedido(conn, uid, pedido, hoy=hoy)
    asset, moneda, fecha = c.asset, c.moneda, c.fecha
    A, B = c.raiz_a, c.raiz_b
    en_moneda = _en_moneda(moneda)

    # #8 — el efectivo no es un título.
    if asset in ("USD", "USDT", "ARS") or conn.execute(
            f"SELECT 1 FROM positions WHERE user_id=? AND broker IN ({_ph(c.patas_a)}) "
            f"AND asset=? AND is_cash=1 LIMIT 1", (uid, *c.patas_a, asset)).fetchone():
        raise PaseInvalido(400, "El efectivo no se mueve con esta opción. Usá Retirar en un "
                                "broker y Depositar en el otro.")

    todos = lotes_del_activo(conn, uid, c.patas_a, asset)
    tipos = {(l.get("asset_type") or "").upper() for l in todos}

    # #9 — bonos y letras.
    if "BOND" in tipos or is_known_ar_bond(asset) or is_bond_like_name(asset):
        raise PaseInvalido(400, "Por ahora los bonos y las letras no se pueden pasar entre "
                                "brokers desde Rendi.")
    # #10 — fondos comunes.
    if asset.startswith("FCI:") or "FUND" in tipos:
        raise PaseInvalido(400, "Los fondos comunes no se pasan entre brokers: se rescatan en "
                                "uno y se suscriben en el otro. Registralo como una venta y "
                                "una compra.")
    # #11 — un código viejo (la fila de B nacería con el nuevo: `NormalizedTx`).
    nuevo_codigo = tickers_renombrados.ticker_importado(asset)
    if nuevo_codigo and nuevo_codigo != asset:
        raise PaseInvalido(409, f"{asset} ahora cotiza como {nuevo_codigo}. Editá el lote para "
                                f"que diga {nuevo_codigo} y volvé a moverlo.")

    # C.2: los de la moneda pedida (el criterio de la venta, `_native_ccy`) que YA
    # estaban en A ese día. Un lote que llegó por un pase anterior está acá desde
    # `en_broker_desde`, no desde su compra. Los que no tienen fecha van al final
    # (como en el SQL) y, si hay que tomarlos, frenan (#19).
    candidatos = []
    for l in todos:
        if _native_ccy(dict(l)) != moneda:
            continue
        compra = str(l.get("entry_date") or "")[:10]
        if not compra:
            candidatos.append(l)
            continue
        if str(l.get("en_broker_desde") or compra)[:10] <= fecha:
            candidatos.append(l)
    disponible = sum(float(l["quantity"] or 0) for l in candidatos)
    pedida = getattr(pedido, "cantidad", None)
    cantidad = float(pedida) if pedida else disponible

    # #12 — el importador ya pasó estos títulos a B.
    cerrado = _traspaso_automatico_ya_cerrado(conn, uid, c)
    if cerrado:
        raise PaseInvalido(409, f"Rendi ya pasó estos {asset} de {A} a {B} el {_ddmm(cerrado)}, "
                                f"cuando importaste el archivo de {B}. No hace falta moverlos "
                                "otra vez.")
    # #13 — B ya trae la llegada en su archivo (y el aviso si está lejos).
    avisos: List[str] = []
    for d, q in _llegadas_importadas_en_b(conn, uid, c):
        dd = _dias_entre(d, fecha)
        if dd <= DIAS_TRASPASO_TARDIO and q <= cantidad + 1e-6:
            raise PaseInvalido(409, (
                f"{B} ya tiene registrada la llegada de {_cant(q)} {asset} el {_ddmm(d)} (vino en "
                "el archivo que importaste). Si la movés también a mano, se cuentan dos veces.\n\n"
                f"Hacé esto: en Movimientos, filtrá por {B} y borrá la «Compra» de {asset} del "
                f"{_ddmm(d)} y el «Depósito» del mismo día. Después volvé y mové los {asset} desde "
                f"{A} con fecha {_ddmm(d)}: así quedan con lo que pagaste originalmente."))
        if dd > DIAS_TRASPASO_TARDIO and not avisos:
            avisos.append(f"Ojo: {B} ya tiene una entrada de {asset} por traspaso del {_ddmm(d)} "
                          "(del archivo). Si es la misma, no la muevas a mano.")
    # #14 — el capital declarado a mano.
    declarado = _capital_declarado_despues(conn, uid, c)
    if declarado:
        pata, y, m = declarado
        raise PaseInvalido(409, (
            f"Tu historia de {pata} en Rendi arranca en {_MESES[m - 1]} de {y} con un capital "
            "inicial que cargaste a mano. El pase no puede tener una fecha anterior: elegí desde "
            f"el 01/{m:02d}/{y}."))
    # #15 — movimientos posteriores en A.
    post = _salida_posterior(conn, uid, c.patas_a, asset, fecha)
    if post:
        if post["traspaso_id"]:
            otro = _contraparte_de_pase(conn, uid, post["traspaso_id"])
            raise PaseInvalido(409, (
                f"El {_ddmmaaaa(post['fecha'])} ya pasaste {asset} de {A} a {otro}. Elegí una "
                f"fecha del {_ddmmaaaa(post['fecha'])} en adelante, o deshacé primero ese pase."))
        raise PaseInvalido(409, (
            f"Después del {_ddmmaaaa(fecha)} vendiste {asset} en {A}. Para no cambiar esas "
            f"ventas, elegí una fecha del {_ddmmaaaa(post['fecha'])} en adelante."))
    # #16 — ventas en B desde ese mismo día (FIFO en B haría que se comieran los lotes
    # movidos, que son más viejos). Desde el mismo día: ver `_salida_posterior`. Por eso
    # la fecha que se propone es la del día SIGUIENTE a la última salida.
    post = _salida_posterior(conn, uid, c.patas_b, asset, fecha, desde_el_mismo_dia=True)
    if post:
        siguiente = _ddmmaaaa(_dia_siguiente(post["fecha"]))
        if post["traspaso_id"]:
            otro = _contraparte_de_pase(conn, uid, post["traspaso_id"])
            raise PaseInvalido(409, (
                f"El {_ddmmaaaa(post['fecha'])} ya pasaste {asset} de {B} a {otro}. Elegí una "
                f"fecha del {siguiente} en adelante, o deshacé primero ese pase."))
        cuando = (f"El {_ddmmaaaa(fecha)}" if post["fecha"] == fecha
                  else f"Después del {_ddmmaaaa(fecha)}")
        raise PaseInvalido(409, (
            f"{cuando} vendiste {asset} en {B}. Si lo pasamos con esa fecha cambiarían esas "
            f"ventas: elegí una fecha del {siguiente} en adelante."))
    # #17 — no hay lotes que estuvieran ahí ese día.
    if not candidatos:
        salida = _salida_importada_cerca(conn, uid, c)
        if salida:
            raise PaseInvalido(400, (
                f"En {A} ya figura la salida de {asset} del {_ddmm(salida)} (vino en el archivo "
                f"de {A}). En Movimientos, filtrá por {A} y tocá «Reabrir» en la «Venta» de "
                f"{asset} del {_ddmm(salida)}. Después volvé y movelos desde acá: así llegan "
                f"a {B} con lo que pagaste."))
        raise PaseInvalido(400, f"No tenés {asset} en {A} en {en_moneda} que estuvieran ahí el "
                                f"{_ddmmaaaa(fecha)}.")
    # #18 — más de lo que había.
    if cantidad > disponible + 1e-9:
        raise PaseInvalido(400, (
            f"En {A} tenés {_cant(disponible)} {asset} en {en_moneda} que estaban ahí el "
            f"{_ddmmaaaa(fecha)}. No podés pasar {_cant(cantidad)}."))
    # Una cantidad por debajo de lo que Rendi distingue (`CANTIDAD_MINIMA`).
    if cantidad < CANTIDAD_MINIMA:
        raise PaseInvalido(400, MSG_CANTIDAD_CHICA)

    # El prefijo FIFO hasta juntar la cantidad, partiendo el último (C.3).
    from fx import costo_del_lote
    lotes: List[LoteDelPlan] = []
    restante = cantidad
    for l in candidatos:
        # Lo que falta juntar, o lo que quedaría del último lote, por debajo de lo que
        # Rendi distingue: no se parte un lote para dejar (o llevar) polvo.
        if restante < CANTIDAD_MINIMA:
            break
        # #19 — un lote sin fecha no se puede ubicar en la historia de A.
        if not str(l.get("entry_date") or "")[:10]:
            raise PaseInvalido(400, "Uno de los lotes que se moverían no tiene fecha de compra. "
                                    "Editalo, poné la fecha y volvé a intentar.")
        qty = float(l["quantity"] or 0)
        take = qty if restante >= qty - CANTIDAD_MINIMA else restante
        com = float(l.get("commissions") or 0)
        base_inv = costo_del_lote(l.get("invested"), l.get("buy_price"), qty) or 0.0
        parcial = take < qty - 1e-9
        if parcial:
            ratio = take / qty
            mov_inv = base_inv - round(base_inv * (1 - ratio), 6)
            mov_com = com - round(com * (1 - ratio), 6)
        else:
            take, mov_inv, mov_com = qty, base_inv, com
        src = helpers._src_tx_for_position(conn, uid, l["id"])
        src = dict(src) if src else None
        lotes.append(LoteDelPlan(
            lote=l, origen="importado" if src else "a_mano",
            fila_origen=({"batch_id": src["batch_id"], "raw_row_id": src["raw_row_id"]}
                         if src else None),
            asset_type=l.get("asset_type") or (src or {}).get("asset_type"),
            asset_name=(src or {}).get("asset_name"),
            take=take, parcial=parcial, mov_inv=mov_inv, mov_com=mov_com,
            moneda=_native_ccy(dict(l)), pata_a=l["broker"]))
        restante -= take
    # Lo que se mueve de verdad (sin el polvo que no se partió).
    cantidad = sum(l.take for l in lotes)

    # C.1.3 — la pata de B de cada lote (sin crear nada).
    por_nombre = {b["name"]: b for b in c.brokers}
    raiz_b_ars = (c.fila_b.get("currency") or "").upper() == "ARS"
    raiz_a_ars = (c.fila_a.get("currency") or "").upper() == "ARS"
    a_crear: List[str] = []
    for l in lotes:
        pata = por_nombre.get(l.pata_a) or {}
        pata_en_dolares = (pata.get("currency") or "").upper() != "ARS"
        es_hija = l.pata_a != A
        if es_hija and pata_en_dolares and l.moneda != "ARS":
            destino = helpers._pata_de_la_moneda(conn, uid, B, "USD", crear=False)
            if destino == B and raiz_b_ars:
                destino = f"{B} · USD"
                if destino not in a_crear:
                    a_crear.append(destino)
            l.pata_b = destino
        else:
            # La raíz de A va a la raíz de B. Y la excepción de C.1.3: un lote EN PESOS
            # que vive en una pata en dólares de A va a la raíz de B (el freno de pesos
            # del persister lo rechazaría en una pata en dólares).
            l.pata_b = B

    # #20 y #21 — los cambios de ratio, con la fuente única (`_cambios_a_ofrecer`).
    nuevo = helpers.interruptor(helpers.AVISO_RATIO_NUEVO, conn)
    marcas = helpers._marcas_de_split(conn, uid)
    marcas_b = {"foto": marcas["foto"], "corp": marcas["corp"],
                "cero": {k: list(v) for k, v in (marcas.get("cero") or {}).items()}}
    base_sym = asset[:-3] if asset.endswith(".BA") else asset
    for l in lotes:
        # La marca «$0» del lote (un lote gratis de un split) viaja con él (D.11).
        if not float(l.lote.get("buy_price") or 0) and not float(l.lote.get("invested") or 0):
            marcas_b["cero"].setdefault((l.pata_b, base_sym), []).append(l.entry_date)
    cache: Dict[str, Any] = {}
    for l in lotes:
        if helpers._por_que_no_se_ajusta_el_ratio(conn, uid, l.lote) is not None:
            continue
        ofrecidos_a, _ = helpers._cambios_a_ofrecer(conn, uid, l.lote, marcas, cache, nuevo)
        if ofrecidos_a:
            raise PaseInvalido(409, (
                f"{asset} tuvo un cambio de ratio que todavía no ajustaste en {A}. Primero "
                "ajustalo en Cartera (el aviso «Ajustar» de esa fila) y después volvé a moverlo."))
    for l in lotes:
        if helpers._por_que_no_se_ajusta_el_ratio(conn, uid, l.lote) is not None:
            continue
        en_b = {**l.lote, "broker": l.pata_b, "split_adjusted_through": None}
        if helpers._por_que_no_se_ajusta_el_ratio(conn, uid, en_b) is not None:
            continue
        ofrecidos_b, _ = helpers._cambios_a_ofrecer(conn, uid, en_b, marcas_b, cache, nuevo)
        if ofrecidos_b:
            raise PaseInvalido(409, (
                f"En {A} estos {asset} ya tienen aplicado un cambio de ratio que {B} no conoce: "
                "si los pasamos, quedarían contados dos veces. Por ahora no se pueden pasar. Si "
                f"los pasaste de verdad, podés registrar una venta en {A} y una compra en {B} "
                "(así sí cuenta como venta)."))

    # #22 — la valuación no puede cambiar de A a B (C.1.4).
    ars, ar_usd = snapshots_job._broker_name_sets(c.brokers)
    ar_usd_b = set(ar_usd) | ({n for n in a_crear} if raiz_b_ars else set())
    cripto = snapshots_job._crypto_symbol_set()

    def _cuenta_en_pesos(nombre) -> bool:
        b = por_nombre.get(nombre)
        return bool(b) and (b.get("currency") or "").upper() == "ARS"

    claves = set()
    for l in lotes:
        clave_a = snapshots_job.position_price_key(l.lote, ars, ar_usd)
        clave_b = snapshots_job.position_price_key({**l.lote, "broker": l.pata_b}, ars, ar_usd_b)
        # La moneda de la cuenta sólo cambia la valuación de una CRIPTO (en una cuenta en
        # pesos lleva el factor del dólar cripto; en una en dólares, no). Es el motivo de
        # la segunda condición de C.1.4, y aplicada a todo frenaba el lote en pesos que
        # vive en una pata en dólares (la excepción de C.1.3, caso #9 de las pruebas).
        en_pesos_a = _cuenta_en_pesos(l.pata_a) and not is_exchange_broker(l.pata_a)
        en_pesos_b = _cuenta_en_pesos(l.pata_b) and not is_exchange_broker(l.pata_b)
        cambia_la_cuenta = asset in cripto and en_pesos_a != en_pesos_b
        if clave_a != clave_b or cambia_la_cuenta:
            raise PaseInvalido(400, f"En {B} {asset} se cotiza distinto que en {A}, así que no "
                                    "se puede pasar.")
        claves.add((clave_a, asset in cripto and en_pesos_a))
    if len(claves) != 1:
        # Lotes de la misma moneda que se cotizan de dos formas (un CEDEAR y la acción de
        # afuera en la misma cuenta): no hay UN precio del día para todos.
        raise PaseInvalido(409, f"En {A} tus lotes de {asset} se cotizan de dos formas "
                                "distintas, así que no podemos calcular cuánto valían. "
                                "Escribinos y lo revisamos.")
    clave, cripto_en_pesos = next(iter(claves))

    # #23 — el registro de A tiene que llevarse los mismos lotes que el plan.
    hist_version = fx.fx_version(conn, uid) if para_confirmar else fx.fx_version_lectura(conn, uid)
    hist = hist_version == fx.FX_V2
    tc_blue = helpers._config_tc_blue(conn, uid)
    _comprobar_con_el_registro(conn, uid, c, lotes, tramos_de_salida(lotes), hist=hist,
                               tc_blue=tc_blue)

    # #24 — la «· USD» de B que haga falta tiene que poder crearse.
    for nombre in a_crear:
        motivo = pipeline.por_que_no_hay_pata_usd(conn, uid, c.fila_b)
        if motivo:
            raise PaseInvalido(409, motivo)
        avisos.append(_aviso_de_la_pata_a_crear(conn, uid, nombre, B, "los lotes en dólares"))
    # #25 — pesos a una caja que no los acepta.
    no_aceptan = pipeline.brokers_que_no_aceptan_pesos(
        {b["name"]: b for b in c.brokers}, None)
    for l in lotes:
        if l.moneda == "ARS" and (l.pata_b in no_aceptan or l.pata_b in a_crear):
            raise PaseInvalido(400, f"{l.pata_b} no tiene caja en pesos, y estos {asset} se "
                                    "compraron en pesos.")

    # #26 — el precio de ese día (C.4).
    moneda_clave = "ARS" if (clave.endswith(".BA") or cripto_en_pesos) else "USD"
    try:
        precio, moneda_precio, fuente, fecha_precio, aviso_vela = _buscar_precio(
            conn, c, lotes, pedido, hoy=hoy, clave=clave, moneda_precio=moneda_clave,
            cripto_en_pesos=cripto_en_pesos, helpers=helpers)
    except PaseInvalido as ex:
        # El confirmar valúa con el precio que la persona VIO (B.3): si entre la vista
        # previa y el confirmar el servidor se quedó sin precio (pasó la medianoche y
        # no hay vela de esos días, el último precio quedó viejo, no llegó el dólar
        # cripto), se usa el de la valuación, como escrito a mano. Sin esto el 409
        # «sin precio» (un objeto) llegaba al modal como JSON crudo. Una valuación en
        # otra moneda no sirve: frena como siempre.
        val = getattr(pedido, "valuacion", None)
        if not (para_confirmar and isinstance(ex.detalle, dict)
                and ex.detalle.get("codigo") == "sin_precio" and val is not None
                and str(getattr(val, "moneda_precio", "")).upper() == moneda_clave
                and float(getattr(val, "precio_unitario", 0) or 0) > 0):
            raise
        precio, moneda_precio = float(val.precio_unitario), moneda_clave
        fuente, fecha_precio, aviso_vela = "precio_a_mano", c.fecha, None
    if aviso_vela:
        avisos.append(aviso_vela)

    # C.4.3 — dos dólares: el de C (por la moneda de los lotes, como el persister) y
    # el de V (por la moneda del precio). La misma cuenta que la revaluación (C.10).
    dolares = dolares_del_pase(conn, fecha, moneda, moneda_precio, hist=hist, tc_blue=tc_blue)
    dolar_del_dia, tc_pesos = dolares["dolar_del_dia"], dolares["tc_pesos"]
    tc_venta, tc_pase = dolares["tc_venta"], dolares["tc_pase"]

    # C.5 — C de cada lote, con la cuenta única del tramo (`importing/tramo.py`).
    for l in lotes:
        l.c_usd = costo_usd_de_lo_movido(conn, l.lote, l.take, l.moneda, precio=precio,
                                         moneda_precio=moneda_precio, dolares=dolares,
                                         tc_blue=tc_blue, hist=hist, fecha=fecha)

    # #27 — el gasto, siempre de la caja de A.
    gasto = None
    g_in = getattr(pedido, "gasto", None)
    if g_in:
        g_moneda = "ARS" if str(g_in.moneda).upper() == "ARS" else "USD"
        pata_gasto = helpers._pata_de_la_moneda(conn, uid, A, g_moneda, crear=False)
        fila_gasto = por_nombre.get(pata_gasto) or {}
        caja_en_pesos = (fila_gasto.get("currency") or "").upper() == "ARS"
        if g_moneda == "ARS" and not caja_en_pesos:
            raise PaseInvalido(400, f"{A} no tiene caja en pesos.")
        if g_moneda == "USD" and caja_en_pesos and raiz_a_ars:
            # Una cuenta argentina sin su «· USD» todavía: el gasto en dólares la crea,
            # como cualquier otra puerta que mueve dólares en esa cuenta.
            pata_gasto = f"{A} · USD"
            motivo = pipeline.por_que_no_hay_pata_usd(conn, uid, c.fila_a)
            if motivo:
                raise PaseInvalido(409, motivo)
            if pata_gasto not in a_crear:
                a_crear.append(pata_gasto)
                avisos.append(_aviso_de_la_pata_a_crear(conn, uid, pata_gasto, A,
                                                        "el gasto en dólares"))
        monto = float(g_in.monto)
        caja = conn.execute(
            "SELECT COALESCE(SUM(invested), 0) AS c FROM positions "
            "WHERE user_id=? AND broker=? AND is_cash=1", (uid, pata_gasto)).fetchone()["c"]
        queda = float(caja or 0) - monto
        gasto = {"monto": monto, "moneda": g_moneda, "broker": pata_gasto,
                 "valor_usd": gasto_en_usd(monto, g_moneda, tc_pesos),
                 "caja_queda_negativa": queda < -0.005}
        if gasto["caja_queda_negativa"]:
            avisos.append(f"Con el gasto, la caja de {pata_gasto} queda en {_monto(queda, g_moneda)}.")

    # El precio cargado a mano en A viaja a B si B no tiene uno (C.7.8), y SÓLO a las
    # patas de B que reciben los lotes que lo tenían: cada pata lee el precio cargado
    # en su moneda (`_moneda_del_precio_cargado`), y el de una pata en pesos copiado a
    # la «· USD» valía 62.000 dólares por título. Una pata que lo leería en otra moneda
    # que la de origen tampoco lo recibe.
    con_precio = [l for l in lotes if l.lote.get("price_override") is not None]
    precio_en_destino = None
    if con_precio:
        override_a = float(con_precio[0].lote["price_override"])
        destinos: List[str] = []
        for l in con_precio:
            if (float(l.lote["price_override"]) == override_a
                    and l.pata_b not in destinos
                    and _moneda_del_precio_cargado(l.lote, l.pata_a, c.brokers)
                    == _moneda_del_precio_cargado(l.lote, l.pata_b, c.brokers)):
                destinos.append(l.pata_b)
        hay_en_b = destinos and conn.execute(
            f"SELECT 1 FROM positions WHERE user_id=? AND broker IN ({_ph(destinos)}) "
            f"AND asset=? AND is_cash=0 AND price_override IS NOT NULL LIMIT 1",
            (uid, *destinos, asset)).fetchone()
        if destinos and not hay_en_b:
            precio_en_destino = {"brokers_destino": destinos, "antes": None,
                                 "puesto": override_a}

    plan = Plan(cuentas=c, cantidad=cantidad, disponible=disponible, lotes=lotes,
                fx_version=hist_version, tc_blue=tc_blue, tc_venta=tc_venta, tc_pase=tc_pase,
                dolar_del_dia=dolar_del_dia, precio=precio, moneda_precio=moneda_precio,
                fuente=fuente, fecha_precio=fecha_precio, brokers_a_crear=a_crear, gasto=gasto,
                precio_cargado_en_destino=precio_en_destino, avisos=avisos)

    # Aviso: el precio lejísimos de lo que se pagó, comparando los dos en dólares.
    banda = plan.aviso_de_banda()
    if banda:
        avisos.append(banda)

    plan.firma = firma_del_plan(lotes, fecha, moneda, B, gasto)
    return plan


# ── C.7: aplicar el pase, todo dentro de la transacción del confirmar ──────────
#
# QUÉ HACE. Escribe lo que `armar_plan` ya decidió, en este orden: crea la «· USD»
# que haga falta, saca de `positions` los lotes CARGADOS A MANO de A (no tienen
# fila en ningún archivo), guarda los dos lotes del pase (el de A y el de B) con
# `store_preview_txs`, anota la receta en `traspasos_a_mano` y los confirma con el
# persister de siempre (`persist_batch`): la SELL de A consume los lotes importados,
# las BUY de B los abren con su costo y su fecha de compra, las patas no mueven nada
# (las lee el recálculo) y la FEE baja la caja de A.
#
# TODO O NADA. No hace `commit()` ni deja que nada lo haga: corre adentro del
# `with conn:` del endpoint. Cualquier cosa que no se pueda guardar sale como
# `PaseInvalido` y el `with` deshace TODO, incluida la «B · USD» recién creada:
#   · una fila que el persister salteó (`skipped_rows`: el persister atrapa los
#     errores de cada fila y sigue con la siguiente; en un pase eso dejaría A sin
#     los títulos y B sin recibirlos) → 500 «No pudimos guardar el pase…»;
#   · el freno de pesos del persister, que sale antes de las filas → 409 con su texto;
#   · la «· USD» que no se puede crear (`_ensure_usd_sibling`) → 409 con su motivo;
#   · un lote cargado a mano que cambió entre la lectura y la escritura → 409 «Tu
#     cartera cambió…».
#
# LO QUE NO HACE. No rearma A ni B (C.7.7): el persister consumió exactamente los
# lotes del plan (lo comprobó `armar_plan` contra el registro, C.2.6), y lo que
# escribió es lo mismo que daría un rebuild; sin rebuild, los ids de lo que queda en
# A no cambian. Tampoco recalcula el mes: eso lo hace el endpoint después
# (`_cascade_after_movement_delete`, la cola de cualquier puerta: cadena, RECÁLCULO
# —que es el que lee las patas— y fotos).

def _motivo(mensaje) -> str:
    """El texto de una fila salteada, para ir entre paréntesis en MSG_NO_SE_GUARDO:
    sin el punto final y con minúscula ('No alcanzan…' → 'no alcanzan…')."""
    s = str(mensaje or "").strip().rstrip(".")
    return (s[:1].lower() + s[1:]) if s else "un error inesperado"


def aplicar_plan(conn, uid: int, plan: Plan, *, helpers) -> Dict[str, Any]:
    """C.7. Devuelve {traspaso_id, lote_salida, lote_entrada, mensaje, patas_tocadas}.
    Levanta `PaseInvalido` (ver arriba): quien llama tiene la transacción abierta y la
    deshace entera."""
    import secrets
    from fx import costo_del_lote
    from importing import pipeline
    from importing.persister import PersistError, persist_batch

    c = plan.cuentas
    tid = secrets.token_hex(16)

    # C.7.2 — las «· USD» que hagan falta, antes de cualquier otra escritura.
    for nombre in plan.brokers_a_crear:
        raiz = nombre[:-len(SUFIJO_USD)] if nombre.endswith(SUFIJO_USD) else nombre
        try:
            creada = helpers._pata_de_la_moneda(conn, uid, raiz, "USD", crear=True)
        except PaseInvalido:
            raise
        except Exception as ex:
            # `_ensure_usd_sibling` contesta con un HTTPException (409 si no se puede
            # adoptar un «· USD» que ya existe con datos): acá se traduce, para que el
            # endpoint lo responda con su motivo y no como un 500 crudo.
            status = getattr(ex, "status_code", None)
            if status is None:
                raise
            raise PaseInvalido(int(status), getattr(ex, "detail", None) or str(ex))
        if creada != nombre:
            raise PaseInvalido(409, MSG_CARTERA_CAMBIO)

    # C.7.3 — los lotes cargados a mano de A salen de `positions`, primero. Con la
    # cantidad que se leyó en la condición: si otro pedido lo cambió, no se toca nada.
    # El prefijo FIFO garantiza que, después de esto, los importados elegidos son los
    # primeros de la cola que queda (los consume la SELL de abajo).
    for l in plan.lotes:
        if l.origen != "a_mano":
            continue
        q = float(l.lote.get("quantity") or 0)
        if l.parcial:
            base_inv = costo_del_lote(l.lote.get("invested"), l.lote.get("buy_price"), q) or 0.0
            n = conn.execute(
                "UPDATE positions SET quantity=?, invested=?, commissions=? "
                "WHERE id=? AND user_id=? AND quantity=?",
                (q - l.take, base_inv - l.mov_inv,
                 float(l.lote.get("commissions") or 0) - l.mov_com,
                 l.lote_id, uid, l.lote.get("quantity"))).rowcount
        else:
            n = conn.execute("DELETE FROM positions WHERE id=? AND user_id=? AND quantity=?",
                             (l.lote_id, uid, l.lote.get("quantity"))).rowcount
        if n != 1:
            raise PaseInvalido(409, MSG_CARTERA_CAMBIO)

    # C.7.4 — los dos lotes del pase, en 'preview' (los confirma el persister abajo).
    filas_a, filas_b = plan.filas(tid)
    sid_a = pipeline.store_preview_txs(conn, uid, broker=c.raiz_a, parser_format=FORMATO,
                                       file_name=ARCHIVO_DEL_PASE, txs=filas_a)
    sid_b = pipeline.store_preview_txs(conn, uid, broker=c.raiz_b, parser_format=FORMATO,
                                       file_name=ARCHIVO_DEL_PASE, txs=filas_b)

    # C.7.5 — la receta, con la fila de B de cada lote (la BUY k es la fila k del lote
    # de B: `filas()` las pone primero, en el orden de los lotes).
    receta = plan.receta()
    # Hasta qué 'Venta' existía al hacer el pase: una venta a mano del MISMO día del
    # pase anotada antes no frena el deshacer (C.8 #3); una anotada después, sí.
    _ops = conn.execute("SELECT MAX(id) AS m FROM operations WHERE user_id=?", (uid,)).fetchone()
    receta["ops_hasta"] = int(_ops["m"] or 0) if _ops else 0
    _, raw_b = pipeline.load_session_for_confirm(conn, uid=uid, session_id=sid_b)
    for k, lote in enumerate(receta["lotes"]):
        lote["fila_destino_raw_row_id"] = raw_b.get(BASE_ROW_INDEX + k)
    conn.execute(
        "INSERT INTO traspasos_a_mano (id, user_id, lote_salida, lote_entrada, fecha, asset, "
        "cantidad, moneda, receta_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (tid, uid, sid_a, sid_b, plan.fecha, plan.asset, plan.cantidad, plan.moneda,
         json.dumps(receta)))

    # C.7.6 — el persister de siempre, lote por lote. Una fila salteada es un pase a
    # medias: se deshace todo.
    for sid in (sid_a, sid_b):
        txs, raw = pipeline.load_session_for_confirm(conn, uid=uid, session_id=sid)
        try:
            r = persist_batch(conn, uid=uid, batch_id=sid, txs=txs, raw_row_ids_by_index=raw,
                              helpers=helpers)
        except PersistError as ex:
            raise PaseInvalido(409, ex.message)
        if r.get("skipped_rows"):
            primera = r["skipped_rows"][0]
            log.error("traspaso_a_mano.aplicar_plan: uid=%s pase=%s fila salteada %s",
                      uid, tid, primera)
            # El texto de una excepción interna (un error de la base, con nombres de
            # tablas y columnas) no se le muestra a la persona: queda en el log.
            motivo = ("un error inesperado" if primera.get("interno")
                      else _motivo(primera.get("message")))
            raise PaseInvalido(500, MSG_NO_SE_GUARDO.format(motivo=motivo))

    # C.7.8 — el precio cargado a mano en A viaja a las patas de B que recibieron los
    # lotes que lo tenían, si no tenían uno (lo anotó el plan en la receta, con esas
    # mismas patas, para deshacerlo). La «· USD» que nació recién ya existe con su nombre
    # (lo comprobó C.7.2).
    if plan.precio_cargado_en_destino:
        destinos = list(plan.precio_cargado_en_destino["brokers_destino"])
        conn.execute(
            f"UPDATE positions SET price_override=? WHERE user_id=? AND broker IN ({_ph(destinos)}) "
            f"AND asset=? AND is_cash=0",
            (plan.precio_cargado_en_destino["puesto"], uid, *destinos, plan.asset))

    return {"traspaso_id": tid, "lote_salida": sid_a, "lote_entrada": sid_b,
            "mensaje": MSG_LISTO.format(q=_cant(plan.cantidad), asset=plan.asset,
                                        A=c.raiz_a, B=c.raiz_b),
            "patas_tocadas": plan.patas_tocadas}


# ── E7: deshacer el pase (C.8), cómo está cada pase (B.5) y las guardas (D.10) ──
#
# QUÉ ES DESHACER. Volver la cuenta a como estaba antes del pase: los dos lotes del
# pase quedan 'reverted' (así las patas, el puente y la llegada dejan de contar
# solas: todo lector del registro usa `TX_VIVAS`), los lotes que llegaron a B se
# van, los de A vuelven con su costo y su fecha de compra, el gasto vuelve a la
# caja y el precio cargado a mano que viajó a B se saca. Después el endpoint corre
# la cola de cualquier puerta (`_cascade_after_movement_delete`: la cadena de cada
# pata, el RECÁLCULO y las fotos). NO usa `revert_batch`: esa primitiva borra las
# fotos medidas desde la fecha del lote, y deshacer un pase no cambia lo que valía
# la cartera ningún día.
#
# CÓMO VUELVEN LOS LOTES DE A. Los IMPORTADOS: si A se puede rearmar desde el
# registro (`_is_safe_to_rebuild`), se rearma (`rebuild_pair_asset`): el registro ya
# no tiene la salida del pase y los repone exactos. Si no (A tiene otros lotes de
# ese activo cargados a mano), cada uno vuelve por el vínculo con su fila de origen
# (`import_op_links`), no por su id: un rebuild de A posterior al pase les cambió el
# id. Los CARGADOS A MANO vuelven al final, con su foto (`_devolver_al_lote`, la
# misma regla que borrar una venta hecha a mano).
#
# EL PASE INCOMPLETO. Si se borró uno de los dos brokers, su lote del pase ya está
# 'reverted' (lo revirtió el borrado del broker) y queda la pata del otro lado,
# viva: el deshacer hace sólo lo de ese lado. Así ningún estado queda sin salida.
#
# LAS GUARDAS. Mientras un pase está vivo, las puertas que reescribirían lo que el
# pase movió frenan y apuntan a «Deshacer pase»: revertir o rehacer un lote del pase
# o el archivo de donde salieron sus títulos, borrar sus filas, sus lotes o el
# historial del activo, limpiar el broker, editar el ticker en grupo y cambiarle el
# broker a un lote. `pase_que_cambia` (C.11) es la regla única de «esto cambia la
# historia anterior a un pase».

MSG_NO_ENCONTRADO = "No encontramos ese pase."
MSG_YA_DESHECHO = "Ese pase ya se deshizo."
MSG_NO_SE_DESHIZO = "No pudimos deshacer el pase ({motivo}). No se cambió nada en tu cartera."
MSG_DESHECHO = "Listo: los {q} {asset} volvieron a {A}."
MSG_DESHECHO_SIN_B = "Listo: {B} ya no existe, así que los {q} {asset} volvieron a {A}."
MSG_DESHECHO_SIN_A = "Listo: los {q} {asset} salieron de {B}."
MSG_DESHECHO_SIN_NINGUNO = ("Listo: {A} y {B} ya no existen, así que no había títulos que "
                            "mover. El pase quedó deshecho.")
# C.8 #2: una fila de un archivo posterior que se omitió porque ya estaba este pase.
MSG_OMITIDAS = ("Cuando importaste el archivo de {broker} del {fecha}, Rendi no cargó la "
                "{cual} de {asset} porque ya estaba este pase. Si lo deshacés, esos títulos "
                "quedarían sin registrar. Primero revertí ese archivo (Importaciones → el "
                "archivo del {fecha} → Revertir), después deshacé el pase y volvé a subir el "
                "archivo.")
# C.8 #3: A después del pase.
MSG_A_VENDIO = ("Después de este pase vendiste {asset} en {A} el {fecha}. Para deshacerlo, "
                "primero borrá esa venta.")
MSG_A_PASO = ("Después de este pase pasaste {asset} de {A} a {C} el {fecha}. Deshacé "
              "primero ese pase.")
# C.8 #4: B tal como llegó.
MSG_B_PASO = "Los {asset} que llegaron a {B} los pasaste a {C} el {fecha}. Deshacé primero ese pase."
MSG_B_VENDIO = ("Los {asset} que llegaron a {B} ya no están como llegaron: vendiste {q} de los "
                "{n}. Para deshacer el pase, primero borrá esa venta.")
MSG_B_EDITADO = ("Los {asset} que llegaron a {B} ya no están como llegaron: los editaste. "
                 "Volvé a dejarlos como llegaron ({como}) para poder deshacer el pase.")
# B.5: el pase quedó desactualizado (lo marca el detector, `marcar_desfasados`).
MSG_DESFASADO = ("Cambió la historia de {broker} y este pase quedó desactualizado: deshacelo y "
                 "hacelo de nuevo.")
# C.8: deshacer un pase desfasado del lado de A cuando A ya no se puede rearmar desde
# los archivos (ver `_por_que_no_se_deshace`).
MSG_DESFASADO_CON_A_MANO = ("Este pase quedó desactualizado y en {A} tenés {asset} cargados a "
                            "mano, así que Rendi no puede rearmar {A} desde tus archivos para "
                            "devolverle bien los títulos. Borrá en {A} lo que cargaste a mano "
                            "de {asset}, deshacé el pase y después volvé a cargarlo.")

# Dónde se deshace un pase, en la pantalla de Rendi (no es un menú de un broker:
# `tests/test_caminos.py` lo sabe por su nombre). Una sola vez: lo nombran todos los
# textos que mandan a deshacer el pase.
CAMINO_DESHACER = "Movimientos → la fila «Pase» → Deshacer"

# D.3.4 y D.10: las puertas que desarmarían un pase vivo.
MSG_DESHACE_EL_PASE = ("Esto es parte de un pase de títulos entre tus brokers. Para sacarlo, "
                       f"deshacé el pase entero: {CAMINO_DESHACER}.")
MSG_REVERT_ES_PASE = ("Este lote es un pase de títulos entre tus brokers: no se revierte desde "
                      "acá. Deshacé el pase entero desde Movimientos (la fila «Pase» → Deshacer).")
MSG_ORIGEN_DE_UN_PASE = ("Hay títulos de esta importación que pasaste a {B} el {fecha}. "
                         f"Deshacé ese pase ({CAMINO_DESHACER}) antes de revertir el archivo.")
MSG_COMPRA_PASADA = ("Parte de esta compra se pasó a {B} el {fecha}. Para borrarla, primero "
                     "deshacé ese pase.")
MSG_LOTE_PASADO = ("Parte de este lote se pasó a otro broker. Para borrarlo, primero deshacé "
                   "ese pase.")
MSG_ACTIVO_CON_PASE = ("Este activo tiene un pase entre brokers. Deshacelo primero "
                       f"({CAMINO_DESHACER}).")
MSG_EDITAR_ACTIVO_CON_PASE = ("Este activo tiene un pase entre brokers. Deshacé primero el pase "
                              "y después editalo.")
MSG_LIMPIAR_CON_PASE = ("Este broker tiene títulos que pasaste a otro broker (o que llegaron "
                        "desde otro). Deshacé esos pases antes de limpiarlo; si no, al "
                        "reimportar vas a ver los títulos en los dos lados.")
# La cuenta en dólares («B · USD») sola, con filas de un pase vivo: su lote del pase es
# el de la cuenta (la raíz) y el borrado no lo revierte. Sin este freno quedaban las
# patas vivas sin títulos y un deshacer imposible (D.19 cubre borrar la CUENTA).
MSG_BORRAR_PATA_CON_PASE = ("«{nombre}» tiene títulos de un pase entre tus brokers. Deshacé "
                            f"primero el pase ({CAMINO_DESHACER}) y después borralo.")
MSG_PUT_OTRO_BROKER = ("Para pasar este lote a otro broker usá «Mover a otro broker» (en el "
                       "menú ⋯ de la fila). Si lo cargaste en el broker equivocado, elegí "
                       "«Tal cual»: queda como si siempre hubiera estado en el otro.")
# El mismo freno con el interruptor apagado: la opción «Mover a otro broker» no se ve
# (la pantalla la esconde), así que el texto no puede mandar ahí.
MSG_PUT_OTRO_BROKER_SIN_MOVER = ("Un lote no se cambia de broker editándolo. Si lo cargaste en "
                                 "el broker equivocado, borralo y cargalo de nuevo en el "
                                 "correcto.")


def msg_put_otro_broker(habilitado: bool) -> str:
    """El 409 de cambiarle el broker a un lote editándolo (D.19): manda a «Mover a otro
    broker» sólo si la opción existe (el interruptor prendido)."""
    return MSG_PUT_OTRO_BROKER if habilitado else MSG_PUT_OTRO_BROKER_SIN_MOVER


# «Tal cual» (2026-11-24): la posición estaba cargada en el broker equivocado (con el
# plan gratis, un solo broker, muchos cargaron todo en uno). Por qué no se puede.
MSG_TAL_CUAL_IMPORTADO = ("Tus {asset} en {broker} vienen de un archivo de {broker} que "
                          "importaste, así que no se pueden pasar tal cual. Si los "
                          "transferiste, usá «En una fecha».")
MSG_TAL_CUAL_CON_PASE = ("Parte de estos {asset} ya se movió con un pase. Deshacelo primero "
                         "(" + CAMINO_DESHACER + ") y volvé a intentar.")
MSG_TAL_CUAL_CAMBIO = ("Una compra de {asset} en {broker} tiene una venta anotada o la "
                       "editaste después de cargarla, así que no se puede pasar tal cual. "
                       "Borrá primero la venta (o cargá la compra de nuevo) y volvé a intentar.")
MSG_TAL_CUAL_SIN_DEPOSITO = ("El depósito que pagó una compra de {asset} en {broker} ya no está "
                             "registrado, así que pasarla descuadraría el saldo. Restauralo "
                             "primero.")
MSG_TAL_CUAL_HECHO = ("Listo: {cantidad} {asset} pasaron de {origen} a {destino} tal cual, con "
                      "su fecha y su costo de compra. {origen} queda como si nunca los "
                      "hubiera tenido.")
# Compras cargadas antes del 06/08/2026 (sin receta): no se sabe con qué plata se
# pagaron, así que la plata pasa con ellas. Lo dicen la vista previa y el «Listo».
MSG_TAL_CUAL_PLATA = ("La plata con que las pagaste pasó con ellas: en Movimientos vas a ver "
                      "que salió de {origen} y entró en {destino} el día de cada compra.")
MOTIVO_ASESOR = "se pasó a otro broker: deshacé primero ese pase"
# C.11, la regla única de lo que cambia la historia anterior a un pase.
MSG_CAMBIA_UN_PASE = ("Esto cambia la historia de {asset} en {broker} antes de tu pase del "
                      "{fecha} {hacia} {contraparte}, y el pase quedaría con otros lotes. Primero "
                      "deshacé el pase (" + CAMINO_DESHACER + "), hacé este cambio y después "
                      "volvé a moverlos.")
MSG_IMPORT_CAMBIA_UN_PASE = ("Este archivo trae {que} de {asset} en {broker} del {fecha_fila}, "
                             "anteriores a tu pase del {fecha} {hacia} {contraparte}. Si lo "
                             "confirmamos, el pase quedaría con otros lotes. Deshacé el pase "
                             "(" + CAMINO_DESHACER + "), importá el archivo y volvé a moverlos.")
# Una venta a mano no consume lotes que todavía no estaban en ese broker (hueco C4 de
# la revisión): el lote que llegó por un pase lleva su compra vieja (va primero en la
# cola) pero está acá desde `en_broker_desde`.
MSG_VENTA_ANTES_DE_LLEGAR = ("El {fecha} todavía no tenías en {broker} todos estos {asset}: "
                             "{q} llegaron desde otro broker tuyo el {llegada}. Elegí una fecha "
                             "del {llegada} en adelante o vendé hasta {disp}.")
# Lo mismo cuando ese día no había NADA que vender: «vendé hasta 0» no se puede (la
# cantidad tiene que ser mayor que cero).
MSG_VENTA_ANTES_DE_LLEGAR_SIN_NADA = ("El {fecha} todavía no tenías {asset} en {broker}: "
                                      "llegaron desde otro broker tuyo el {llegada}. Elegí una "
                                      "fecha del {llegada} en adelante.")


def texto_venta_antes_de_llegar(*, fecha: str, broker: str, asset: str, q: float,
                                llegada: str, disp: float) -> str:
    """El 409 de una venta a mano con fecha anterior a la llegada de un pase (regla C4).
    Lo usan la venta (`sell_position_fifo`) y la vista previa de la venta del chat."""
    if disp <= 1e-9:
        return MSG_VENTA_ANTES_DE_LLEGAR_SIN_NADA.format(
            fecha=_ddmmaaaa(fecha), broker=broker, asset=asset, llegada=_ddmmaaaa(llegada))
    return MSG_VENTA_ANTES_DE_LLEGAR.format(
        fecha=_ddmmaaaa(fecha), broker=broker, asset=asset, q=_cant(q),
        llegada=_ddmmaaaa(llegada), disp=_cant(disp))


# Deshacer un pase incompleto cuyo broker borrado se volvió a crear con el mismo nombre
# y ya tiene ese activo (C.8): deshacer no sabe si lo que hay ahí es lo que el pase
# movió (un archivo que se volvió a importar trae la llegada o la salida), y mover los
# títulos los contaría dos veces o los haría desaparecer. Frena con las dos salidas.
MSG_RECREADO_B = ("Borraste {B} después de este pase y lo volviste a crear, y ahora tiene "
                  "{asset}. Si deshacemos el pase, los {q} {asset} volverían a {A} sin salir de "
                  "{B} y quedarían contados dos veces. Si los {asset} ya están bien en {B} (por "
                  "ejemplo, porque volviste a importar su archivo), no hace falta deshacer el "
                  "pase. Para deshacerlo igual, primero sacá de {B} esos {asset} (si vinieron en "
                  "un archivo: Importaciones → ese archivo → Revertir) y volvé a intentar.")
MSG_RECREADO_A = ("Borraste {A} después de este pase y lo volviste a crear, y ahora tiene "
                  "{asset}. Si deshacemos el pase, los {q} {asset} saldrían de {B} y no "
                  "volverían a {A}. Si tu cartera ya está bien así, no hace falta deshacer el "
                  "pase. Para deshacerlo igual, primero sacá de {A} esos {asset} (si vinieron en "
                  "un archivo: Importaciones → ese archivo → Revertir) y volvé a intentar.")

# Tolerancias: la cantidad de un lote se compara con 1e-6 (como la comprobación del
# plan, `_coinciden`).
_TOL_CANT = 1e-6


@dataclass
class Registro:
    """Un pase guardado, con cómo está cada lado HOY.

    `a_vivo`/`b_vivo`: el lote del pase de ese lado sigue 'confirmed' (si se borró el
    broker, lo revirtió el borrado). `raiz_a`/`raiz_b`: el nombre de hoy de cada
    cuenta (`import_batches.broker`, que el renombre mantiene); si un lado se borró,
    el de la receta. `patas_a`/`patas_b`: la cuenta y su «· USD» (vacío si ese lado
    ya no está)."""
    id: str
    fecha: str
    asset: str
    cantidad: float
    moneda: str
    receta: Dict[str, Any]
    lote_salida: str
    lote_entrada: str
    a_vivo: bool
    b_vivo: bool
    raiz_a: str
    raiz_b: str
    patas_a: List[str]
    patas_b: List[str]
    creado_at: Optional[str] = None
    deshecho_at: Optional[str] = None
    desfasado_at: Optional[str] = None
    desfasado_motivo: Optional[str] = None
    omitidas: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def estado(self) -> str:
        if not (self.a_vivo and self.b_vivo):
            return "incompleto"
        return "desfasado" if self.desfasado_at else "vivo"

    def lotes(self, origen: Optional[str] = None) -> List[Dict[str, Any]]:
        return [l for l in (self.receta.get("lotes") or [])
                if isinstance(l, dict) and (origen is None or l.get("origen") == origen)]

    @property
    def compra_mas_nueva(self) -> str:
        """La fecha de compra más nueva de lo que se movió (C.11, lado A)."""
        fechas = [_dia((l.get("foto") or {}).get("entry_date")) for l in self.lotes()]
        fechas = [f for f in fechas if f]
        return max(fechas) if fechas else self.fecha


def _registros(conn, uid: int, *, tid: Optional[str] = None,
               vivos: bool = True) -> List[Registro]:
    """Los pases del usuario (los no deshechos, con `vivos`), con el estado de sus
    dos lotes. Toda lectura filtra por `user_id` (B.7)."""
    from importing.persister import broker_pair
    donde, args = "t.user_id = ?", [uid]
    if tid is not None:
        donde += " AND t.id = ?"
        args.append(tid)
    if vivos:
        donde += " AND t.deshecho_at IS NULL"
    filas = conn.execute(
        f"""SELECT t.*, ba.status AS st_a, ba.broker AS br_a, bb.status AS st_b, bb.broker AS br_b
              FROM traspasos_a_mano t
              LEFT JOIN import_batches ba ON ba.id = t.lote_salida AND ba.user_id = t.user_id
              LEFT JOIN import_batches bb ON bb.id = t.lote_entrada AND bb.user_id = t.user_id
             WHERE {donde}
             ORDER BY t.fecha, t.creado_at, t.id""", tuple(args)).fetchall()
    out: List[Registro] = []
    for t in filas:
        try:
            receta = json.loads(t["receta_json"] or "{}") or {}
        except (TypeError, ValueError):
            log.warning("traspaso_a_mano: receta ilegible en el pase %s", t["id"])
            receta = {}
        try:
            omitidas = json.loads(t["omitidas_json"] or "[]") or []
        except (TypeError, ValueError):
            omitidas = []
        raiz_a = t["br_a"] or receta.get("broker_origen") or ""
        raiz_b = t["br_b"] or receta.get("broker_destino") or ""
        # Vivo = su lote sigue confirmado. Borrar el broker (o limpiarlo) revierte
        # los lotes de esa cuenta, el del pase incluido.
        a_vivo = t["st_a"] == "confirmed"
        b_vivo = t["st_b"] == "confirmed"
        out.append(Registro(
            id=t["id"], fecha=_dia(t["fecha"]), asset=t["asset"], cantidad=_num(t["cantidad"]),
            moneda=t["moneda"], receta=receta, lote_salida=t["lote_salida"],
            lote_entrada=t["lote_entrada"], a_vivo=a_vivo, b_vivo=b_vivo,
            raiz_a=raiz_a, raiz_b=raiz_b,
            patas_a=broker_pair(conn, uid, raiz_a) if a_vivo else [],
            patas_b=broker_pair(conn, uid, raiz_b) if b_vivo else [],
            creado_at=t["creado_at"], deshecho_at=t["deshecho_at"],
            desfasado_at=t["desfasado_at"], desfasado_motivo=t["desfasado_motivo"],
            omitidas=[o for o in omitidas if isinstance(o, dict)]))
    return out


def cargar_registro(conn, uid: int, traspaso_id: str) -> Registro:
    """El pase `traspaso_id` del usuario: 404 si no existe o es de otra cuenta (el
    mismo texto, B.7), 409 si ya se deshizo (C.8 #1)."""
    regs = _registros(conn, uid, tid=str(traspaso_id or ""), vivos=False)
    if not regs:
        raise PaseInvalido(404, MSG_NO_ENCONTRADO)
    if regs[0].deshecho_at:
        raise PaseInvalido(409, MSG_YA_DESHECHO)
    return regs[0]


def _canon(asset) -> str:
    return str(asset or "").strip().upper()


def _id_mas_alto_del_pase(conn, lote: str, traspaso_id: str) -> int:
    """El id más alto de las filas del pase `traspaso_id` en su lote `lote` (que sigue
    confirmado: lo pregunta quien llama). Lo escrito DESPUÉS del pase tiene un id
    mayor: la regla de «posterior al pase» del deshacer (C.8 #3) y del detector de
    desfase (`marcar_desfasados`, lado B)."""
    r = conn.execute(f"SELECT MAX(n.id) AS m FROM {TX_VIVAS} WHERE n.batch_id=? "
                     f"AND n.traspaso_id=?", (lote, traspaso_id)).fetchone()
    return int(r["m"] or 0) if r else 0


def _ids_de_las_filas_del_pase(conn, reg: Registro, lote: str) -> int:
    return _id_mas_alto_del_pase(conn, lote, reg.id)


def _salida_de_a_despues(conn, uid: int, reg: Registro):
    """C.8 #3: lo que sacó el activo de las patas de A DESDE el día del pase y DESPUÉS
    de él. Una SELL del registro (importada o de otro pase) con fecha posterior, o del
    mismo día pero escrita después que las filas de este pase (su id es mayor); una
    'Venta' cargada a mano con fecha posterior, o del mismo día y anotada después
    del pase (`ops_hasta` de la receta). Las 'Venta' de un import ya están contadas
    por su SELL. Devuelve {fecha, traspaso_id} (la más nueva; a igual fecha, la de un
    pase: su texto pide deshacerlo) o None."""
    if not reg.patas_a:
        return None
    mejor = None
    ultimo = _ids_de_las_filas_del_pase(conn, reg, reg.lote_salida)
    for s in conn.execute(
            f"""SELECT substr(n.date, 1, 10) AS d, n.traspaso_id AS tid, n.id AS nid
                  FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND n.broker IN ({_ph(reg.patas_a)})
                   AND UPPER(n.asset_symbol) = ? AND n.operation_type = 'SELL'
                   AND substr(n.date, 1, 10) >= ?
                   AND COALESCE(n.traspaso_id, '') <> ?""",
            (uid, *reg.patas_a, _canon(reg.asset), reg.fecha, reg.id)).fetchall():
        if s["d"] == reg.fecha and int(s["nid"] or 0) < ultimo:
            continue                    # del mismo día y anterior al pase: ya estaba
        if mejor is None or s["d"] > mejor["fecha"] or (
                s["d"] == mejor["fecha"] and s["tid"] and not mejor["traspaso_id"]):
            mejor = {"fecha": s["d"], "traspaso_id": s["tid"]}
    ops_hasta = reg.receta.get("ops_hasta")
    # Una 'Venta' a mano anotada DESPUÉS del pase cuenta aunque su fecha sea anterior
    # (la venta a mano ya no deja anotarla —C.11 en `sell_position_fifo`—, pero si
    # alguna puerta lo hiciera, deshacer la dejaría pagada con otros lotes).
    for o in conn.execute(
            f"""SELECT substr(o.date, 1, 10) AS d, o.id AS oid FROM operations o
                 WHERE o.user_id = ? AND o.broker IN ({_ph(reg.patas_a)})
                   AND UPPER(o.asset) = ? AND o.op_type = 'Venta'
                   AND (substr(o.date, 1, 10) >= ? OR o.id > ?)
                   AND NOT EXISTS (SELECT 1 FROM import_op_links k WHERE k.operation_id = o.id)""",
            (uid, *reg.patas_a, _canon(reg.asset), reg.fecha,
             int(ops_hasta) if ops_hasta is not None else 2 ** 62)).fetchall():
        if o["d"] == reg.fecha and ops_hasta is not None and int(o["oid"]) <= int(ops_hasta):
            continue
        if mejor is None or o["d"] > mejor["fecha"]:
            mejor = {"fecha": o["d"], "traspaso_id": None}
    return mejor


def _llegadas_de_b(conn, reg: Registro) -> List[Dict[str, Any]]:
    """Las COMPRAS del lote de B (una por lote que llegó), con el lote de `positions`
    al que apunta hoy su vínculo (None si ya no existe). Se lee con el lote de B
    confirmado (el deshacer la pide ANTES de revertirlo)."""
    out = []
    for f in conn.execute(
            f"""SELECT n.raw_row_id, n.quantity, n.unit_price, n.currency, n.broker
                  FROM {TX_VIVAS}
                 WHERE n.batch_id = ? AND n.operation_type = 'BUY'
                 ORDER BY n.id""", (reg.lote_entrada,)).fetchall():
        link = conn.execute(
            "SELECT position_id FROM import_op_links WHERE batch_id=? AND raw_row_id=? "
            "AND position_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (reg.lote_entrada, f["raw_row_id"])).fetchone()
        out.append({"fila": dict(f), "position_id": link["position_id"] if link else None})
    return out


def _lote_vivo(conn, uid: int, pid):
    if pid is None:
        return None
    return conn.execute("SELECT id, quantity FROM positions WHERE id=? AND user_id=? "
                        "AND is_cash=0", (pid, uid)).fetchone()


def _pase_posterior_desde_b(conn, uid: int, reg: Registro):
    """Un pase VIVO, posterior, que sacó este activo de la cuenta B (su lote de salida
    es de B y sigue confirmado). Devuelve el registro o None."""
    for otro in _registros(conn, uid, vivos=True):
        if (otro.id != reg.id and otro.a_vivo and otro.raiz_a == reg.raiz_b
                and _canon(otro.asset) == _canon(reg.asset) and otro.fecha >= reg.fecha):
            return otro
    return None


def _lado_borrado_que_volvio(conn, uid: int, reg: Registro) -> Optional[str]:
    """'destino' u 'origen' si el lado borrado de un pase incompleto se volvió a crear
    (hoy hay un broker con su nombre) y ya tiene el activo: un lote suyo o una fila
    viva del registro (una compra y su «Débito» dejan el lote en 0, pero están). Un
    lado que se borró y no volvió, o volvió vacío de ese activo, no frena: deshacer
    hace lo de siempre (C.8, pase incompleto). Sólo lee."""
    from importing.persister import broker_pair
    for vivo, raiz, lado in ((reg.b_vivo, reg.raiz_b, "destino"),
                             (reg.a_vivo, reg.raiz_a, "origen")):
        if vivo or not raiz:
            continue
        if not conn.execute("SELECT 1 FROM brokers WHERE user_id=? AND name=?",
                            (uid, raiz)).fetchone():
            continue
        patas = broker_pair(conn, uid, raiz)
        asset = _canon(reg.asset)
        if conn.execute(
                f"SELECT 1 FROM positions WHERE user_id=? AND broker IN ({_ph(patas)}) "
                f"AND UPPER(asset)=? AND is_cash=0 AND quantity > 0 LIMIT 1",
                (uid, *patas, asset)).fetchone() or conn.execute(
                f"SELECT 1 FROM {TX_VIVAS} WHERE b.user_id=? AND n.broker IN ({_ph(patas)}) "
                f"AND UPPER(n.asset_symbol)=? AND n.operation_type IN ('BUY', 'SELL') LIMIT 1",
                (uid, *patas, asset)).fetchone():
            return lado
    return None


def _por_que_no_se_deshace(conn, uid: int, reg: Registro) -> Optional[str]:
    """C.8, validaciones 2 a 4 (la 1 es `cargar_registro`). Devuelve el texto (409) o
    None si se puede deshacer. Sólo lee: la usan el deshacer y `GET /traspasos`."""
    # 2 — filas de un archivo posterior que no entraron porque ya estaba este pase. La
    # fecha es la que muestra Importaciones (`created_at`, en el día ARGENTINO): la
    # marca se guarda en UTC y de 21 a 24 hs es otro día, y el texto manda a buscar
    # ese archivo en la lista.
    from fechas import dia_art_de_texto
    for o in reg.omitidas:
        b = conn.execute(
            "SELECT broker, status, created_at FROM import_batches WHERE id=? AND user_id=?",
            (o.get("batch_id"), uid)).fetchone()
        if b and b["status"] == "confirmed":
            return MSG_OMITIDAS.format(
                broker=b["broker"],
                fecha=_ddmmaaaa(dia_art_de_texto(b["created_at"]) or b["created_at"]),
                asset=reg.asset,
                cual="llegada" if o.get("lado") in ("entrada", "destino") else "salida")
    # El broker borrado de un pase incompleto que se volvió a crear y ya tiene el activo.
    recreado = _lado_borrado_que_volvio(conn, uid, reg)
    if recreado:
        return (MSG_RECREADO_B if recreado == "destino" else MSG_RECREADO_A).format(
            A=reg.raiz_a, B=reg.raiz_b, asset=reg.asset, q=_cant(reg.cantidad))
    # 3 — A después del pase.
    if reg.a_vivo:
        s = _salida_de_a_despues(conn, uid, reg)
        if s:
            if s["traspaso_id"]:
                return MSG_A_PASO.format(asset=reg.asset, A=reg.raiz_a,
                                         C=_contraparte_de_pase(conn, uid, s["traspaso_id"]),
                                         fecha=_ddmm(s["fecha"]))
            return MSG_A_VENDIO.format(asset=reg.asset, A=reg.raiz_a, fecha=_ddmm(s["fecha"]))
    # 4 — B tal como llegó.
    if reg.b_vivo:
        llegadas = _llegadas_de_b(conn, reg)
        vivos = [(ll, _lote_vivo(conn, uid, ll["position_id"])) for ll in llegadas]
        if any(v is None or abs(_num(v["quantity"]) - _num(ll["fila"]["quantity"])) > _TOL_CANT
               for ll, v in vivos):
            posterior = _pase_posterior_desde_b(conn, uid, reg)
            if posterior:
                return MSG_B_PASO.format(asset=reg.asset, B=reg.raiz_b, C=posterior.raiz_b,
                                         fecha=_ddmm(posterior.fecha))
            n = sum(_num(ll["fila"]["quantity"]) for ll in llegadas)
            if _salida_posterior(conn, uid, reg.patas_b, reg.asset, reg.fecha,
                                 desde_el_mismo_dia=True):
                quedan = sum(min(_num(v["quantity"]), _num(ll["fila"]["quantity"]))
                             for ll, v in vivos if v is not None)
                return MSG_B_VENDIO.format(asset=reg.asset, B=reg.raiz_b,
                                           q=_cant(max(n - quedan, 0.0)), n=_cant(n))
            como = " y ".join(
                f"{_cant(ll['fila']['quantity'])} a "
                f"{_monto(ll['fila']['unit_price'], ll['fila']['currency'])}"
                for ll in llegadas)
            return MSG_B_EDITADO.format(asset=reg.asset, B=reg.raiz_b, como=como)
    # Desfasado del lado de A y A ya no se puede rearmar. El detector marca «origen»
    # sólo al rearmar A desde el registro: desde ese rearmado, los lotes de A son los
    # que dejó el REGISTRO (la salida del pase se llevó otros lotes que los de la
    # receta: por eso se marcó). Deshacer por el vínculo (C.8 paso 3 b) devolvería los
    # de la receta encima: la misma cantidad pero con otros costos y fechas, y un lote
    # con más títulos que su compra. Rearmar no se puede (hay algo cargado a mano que
    # el rearmado borraría). Se frena con la salida: sacar lo cargado a mano deja A a
    # salvo y el deshacer la rearma desde el registro (paso 3 a), que es lo correcto.
    if reg.a_vivo and reg.desfasado_at and reg.desfasado_motivo == "origen" \
            and reg.lotes("importado"):
        from importing.rebuild import _is_safe_to_rebuild
        if not _is_safe_to_rebuild(conn, uid, reg.patas_a, reg.asset):
            return MSG_DESFASADO_CON_A_MANO.format(A=reg.raiz_a, asset=reg.asset)
    return None


def validar_deshacer(conn, uid: int, traspaso_id: str) -> Registro:
    """C.8, las validaciones en orden. Levanta `PaseInvalido` (404/409)."""
    reg = cargar_registro(conn, uid, traspaso_id)
    motivo = _por_que_no_se_deshace(conn, uid, reg)
    if motivo:
        raise PaseInvalido(409, motivo)
    return reg


def _devolver_importado(conn, uid: int, lote: Dict[str, Any], helpers) -> None:
    """C.8 paso 3 (b): un lote IMPORTADO vuelve a A por el vínculo con su fila de
    origen. Si el lote de esa fila sigue vivo (el pase se llevó una parte), se le
    suma; si no, vuelve con su foto (el mismo id si está libre) y el vínculo queda
    apuntándole: es por donde lo encuentran el revert del archivo y las guardas."""
    fo = lote.get("fila_origen") or {}
    link = (fo.get("batch_id"), fo.get("raw_row_id")) if fo.get("batch_id") else None
    foto = dict(lote.get("foto") or {})
    if link:
        r = conn.execute(
            "SELECT position_id FROM import_op_links WHERE batch_id=? AND raw_row_id=? "
            "AND position_id IS NOT NULL ORDER BY id DESC LIMIT 1", link).fetchone()
        if r and _lote_vivo(conn, uid, r["position_id"]):
            foto["id"] = r["position_id"]
    helpers._devolver_al_lote(conn, uid, foto, _num(lote.get("cantidad")),
                              lote.get("invested"), _num(lote.get("commissions")), link=link)


def _devolver_a_mano(conn, uid: int, lote: Dict[str, Any], helpers) -> None:
    """C.8 paso 4: un lote CARGADO A MANO vuelve con su foto (`_devolver_al_lote`). Un
    lote viejo sin `invested` (su costo es precio × cantidad) vuelve sin él cuando
    queda entero como estaba: el pase le escribió el costo de lo que quedaba."""
    foto = dict(lote.get("foto") or {})
    r = helpers._devolver_al_lote(conn, uid, foto, _num(lote.get("cantidad")),
                                  _num(lote.get("invested")), _num(lote.get("commissions")))
    if foto.get("invested") is None:
        conn.execute("UPDATE positions SET invested=NULL WHERE id=? AND user_id=? "
                     "AND ABS(quantity - ?) <= ?",
                     (r["id"], uid, _num(foto.get("quantity")), 1e-9))


def deshacer(conn, uid: int, reg: Registro, *, helpers) -> Dict[str, Any]:
    """C.8, los pasos, adentro de la transacción del endpoint (que ya tomó el turno y
    los lotes de A y de B, y validó con `validar_deshacer`). Devuelve {mensaje,
    patas_tocadas}. Levanta `PaseInvalido` si otro pedido lo deshizo en el medio."""
    from importing.rebuild import _is_safe_to_rebuild, rebuild_pair_asset

    # Lo que llegó a B, leído mientras su lote sigue confirmado (abajo se revierte).
    llegadas = _llegadas_de_b(conn, reg) if reg.b_vivo else []
    # 7 (primero, como candado): marcar el pase deshecho. Un segundo pedido que llegó
    # a la vez toca 0 filas y sale sin hacer nada.
    if conn.execute(
            "UPDATE traspasos_a_mano SET deshecho_at=datetime('now') "
            "WHERE id=? AND user_id=? AND deshecho_at IS NULL", (reg.id, uid)).rowcount != 1:
        raise PaseInvalido(409, MSG_YA_DESHECHO)
    # 1 — los lotes del pase que siguen vivos, a 'reverted' (así dejan de contar: todo
    # lector del registro usa TX_VIVAS). Tienen que ser exactamente esos.
    lotes = [x for x, vivo in ((reg.lote_salida, reg.a_vivo), (reg.lote_entrada, reg.b_vivo))
             if vivo]
    if lotes and conn.execute(
            f"UPDATE import_batches SET status='reverted', reverted_at=datetime('now') "
            f"WHERE user_id=? AND id IN ({_ph(lotes)}) AND status='confirmed'",
            (uid, *lotes)).rowcount != len(lotes):
        raise PaseInvalido(409, MSG_YA_DESHECHO)

    patas: List[str] = []
    q, asset = _cant(reg.cantidad), reg.asset
    if reg.b_vivo:
        # 2 — B: se van los lotes que llegaron (la validación 4 garantizó que están
        # como llegaron) y sus vínculos. B no se rearma: lo suyo queda como estaba.
        for ll in llegadas:
            if ll["position_id"] is not None:
                conn.execute("DELETE FROM positions WHERE id=? AND user_id=? AND is_cash=0",
                             (ll["position_id"], uid))
        conn.execute("DELETE FROM import_op_links WHERE batch_id=?", (reg.lote_entrada,))
        # 5 — el precio cargado a mano que viajó a B vuelve a lo que había, en los
        # lotes que siguen con el que puso el pase.
        pc = reg.receta.get("precio_cargado_en_destino")
        if pc and pc.get("brokers_destino") and pc.get("puesto") is not None:
            destinos = list(pc["brokers_destino"])
            conn.execute(
                f"UPDATE positions SET price_override=? WHERE user_id=? "
                f"AND broker IN ({_ph(destinos)}) AND asset=? AND is_cash=0 "
                f"AND ABS(price_override - ?) <= ?",
                (pc.get("antes"), uid, *destinos, asset, float(pc["puesto"]),
                 1e-9 * max(1.0, abs(float(pc["puesto"])))))
        patas += reg.patas_b
    if reg.a_vivo:
        # 3 — A, los importados: rearmar si A se puede rearmar; si no, por el vínculo.
        importados = reg.lotes("importado")
        if importados:
            if _is_safe_to_rebuild(conn, uid, reg.patas_a, asset):
                rebuild_pair_asset(conn, uid, reg.raiz_a, asset,
                                   tc_blue=helpers._config_tc_blue(conn, uid))
            else:
                for l in importados:
                    _devolver_importado(conn, uid, l, helpers)
        # 4 — A, los que eran cargados a mano, al final.
        for l in reg.lotes("a_mano"):
            _devolver_a_mano(conn, uid, l, helpers)
        # El precio cargado a mano de A es del ACTIVO (vive en cada lote): si el pase
        # se llevó todos los lotes, el rearmado no tiene de dónde copiarlo. Vuelve el
        # de la foto a los lotes de A que quedaron sin uno.
        po = next((l["foto"]["price_override"] for l in reg.lotes()
                   if (l.get("foto") or {}).get("price_override") is not None), None)
        if po is not None:
            conn.execute(
                f"UPDATE positions SET price_override=? WHERE user_id=? "
                f"AND broker IN ({_ph(reg.patas_a)}) AND asset=? AND is_cash=0 "
                f"AND price_override IS NULL", (po, uid, *reg.patas_a, asset))
        # 6 — el gasto vuelve a la caja de A (la única puerta de la caja).
        g = reg.receta.get("gasto")
        if g and _num(g.get("monto")) > 0 and g.get("broker"):
            helpers._adjust_broker_cash(conn, uid, g["broker"], _num(g["monto"]))
            patas.append(g["broker"])
        patas += reg.patas_a

    if reg.a_vivo and reg.b_vivo:
        mensaje = MSG_DESHECHO.format(q=q, asset=asset, A=reg.raiz_a)
    elif reg.a_vivo:
        mensaje = MSG_DESHECHO_SIN_B.format(q=q, asset=asset, A=reg.raiz_a, B=reg.raiz_b)
    elif reg.b_vivo:
        mensaje = MSG_DESHECHO_SIN_A.format(q=q, asset=asset, B=reg.raiz_b)
    else:
        mensaje = MSG_DESHECHO_SIN_NINGUNO.format(A=reg.raiz_a, B=reg.raiz_b)
    return {"mensaje": mensaje, "patas_tocadas": list(dict.fromkeys(p for p in patas if p))}


def aviso_del_pase(reg: "Registro") -> Optional[str]:
    """El renglón de aviso de un pase desfasado (B.5), o None si no lo está. Nombra la
    cuenta cuya historia cambió: la de destino si el detector lo marcó por ese lado
    (`desfasado_motivo='destino'`), la de origen si no. UN solo texto para GET
    /traspasos (`aviso`) y las patas de Movimientos (`aviso`, que la pantalla dibuja
    debajo de la fila): antes Movimientos lo armaba en la pantalla y nombraba siempre
    al origen, aunque lo que cambió fuera el destino."""
    if not reg.desfasado_at:
        return None
    return MSG_DESFASADO.format(
        broker=reg.raiz_b if reg.desfasado_motivo == "destino" else reg.raiz_a)


def traspasos_vivos(conn, uid: int) -> List[Dict[str, Any]]:
    """B.5: los pases que no se deshicieron, con su estado y si se pueden deshacer
    (y si no, por qué: el mismo texto que daría el deshacer). Sólo lee."""
    out = []
    for reg in _registros(conn, uid, vivos=True):
        motivo = _por_que_no_se_deshace(conn, uid, reg)
        aviso = aviso_del_pase(reg)
        out.append({
            "id": reg.id, "fecha": reg.fecha, "asset": reg.asset, "cantidad": reg.cantidad,
            "moneda": reg.moneda, "broker_origen": reg.raiz_a, "broker_destino": reg.raiz_b,
            "valor_usd": round(_num(reg.receta.get("valor_usd")), 2),
            "costo_usd": round(_num(reg.receta.get("costo_usd")), 2),
            "estado": reg.estado, "puede_deshacer": motivo is None, "motivo": motivo,
            "aviso": aviso,
        })
    return out


# ── las guardas (D.3.4, D.10) ──────────────────────────────────────────────────

def lotes_en_pases_vivos(conn, uid: int) -> set:
    """Los `lote_id` (ids de `positions` en A al momento del pase) de las recetas de
    los pases vivos: un lote cargado a mano que se llevó una parte, o el que el
    asesor cargó y el cliente pasó."""
    out = set()
    for reg in _registros(conn, uid, vivos=True):
        for l in reg.lotes():
            if l.get("lote_id") is not None:
                out.add(l["lote_id"])
    return out


def lotes_de_pases_vivos(conn, uid: int) -> set:
    """Los ids de `positions` que son parte de un pase vivo: los de A de su receta
    (`lotes_en_pases_vivos`) y los que LLEGARON a B (el vínculo de cada COMPRA de su
    lote de entrada, si sigue confirmado). Es la guarda del PUT de un lote que le
    cambia el activo o la moneda (D.10.14 propagado)."""
    out = set(lotes_en_pases_vivos(conn, uid))
    for reg in _registros(conn, uid, vivos=True):
        if reg.b_vivo:
            out |= {ll["position_id"] for ll in _llegadas_de_b(conn, reg)
                    if ll["position_id"] is not None}
    return out


def filas_origen_vivas(conn, uid: int) -> Dict[Tuple[str, Any], Tuple[str, str]]:
    """{(batch_id, raw_row_id) de la COMPRA importada de donde salieron títulos de un
    pase vivo: (cuenta de destino, fecha del pase)}."""
    out: Dict[Tuple[str, Any], Tuple[str, str]] = {}
    for reg in _registros(conn, uid, vivos=True):
        for l in reg.lotes("importado"):
            fo = l.get("fila_origen") or {}
            if fo.get("batch_id") is not None:
                out.setdefault((fo["batch_id"], fo.get("raw_row_id")), (reg.raiz_b, reg.fecha))
    return out


def pase_vivo_del_activo(conn, uid: int, asset: str, patas=None, *,
                         creado_desde: Optional[str] = None) -> Optional[Registro]:
    """El primer pase vivo de `asset` (en esas patas, si se dan: de cualquiera de los
    dos lados que siga vivo). `creado_desde`: sólo los creados desde ese momento
    (texto 'AAAA-MM-DD HH:MM:SS', como `datetime('now')`)."""
    patas = set(patas) if patas else None
    for reg in _registros(conn, uid, vivos=True):
        if _canon(reg.asset) != _canon(asset):
            continue
        if patas is not None and not (patas & (set(reg.patas_a) | set(reg.patas_b))):
            continue
        if creado_desde and str(reg.creado_at or "") < str(creado_desde):
            continue
        return reg
    return None


def pases_de_brokers(conn, uid: int, nombres) -> List[str]:
    """Los pases vivos que tocan esos brokers: su lote de A o de B sigue confirmado y
    es de una de esas cuentas, o tiene filas en una de esas patas. Es el conteo
    «traspasos» del borrado de un broker (D.10.8) y el freno de «Limpiar» (D.10.7)."""
    nombres = [n for n in (nombres or []) if n]
    if not nombres:
        return []
    tocados = {r["tid"] for r in conn.execute(
        f"""SELECT DISTINCT n.traspaso_id AS tid FROM {TX_VIVAS}
             WHERE b.user_id = ? AND b.parser_format = ? AND n.traspaso_id IS NOT NULL
               AND (b.broker IN ({_ph(nombres)}) OR n.broker IN ({_ph(nombres)}))""",
        (uid, FORMATO, *nombres, *nombres)).fetchall()}
    return [r["id"] for r in conn.execute(
        "SELECT id FROM traspasos_a_mano WHERE user_id = ? AND deshecho_at IS NULL "
        "ORDER BY fecha, id", (uid,)).fetchall() if r["id"] in tocados]


def pases_de_brokers_por_lado(conn, uid: int, nombres) -> Dict[str, List[str]]:
    """Los pases vivos que tocan esos brokers (`pases_de_brokers`), separados por el
    lado que esos brokers son en cada uno: 'salida' (los títulos salieron de acá) o
    'entrada' (llegaron acá). El aviso de borrar un broker dice cosas distintas: lo
    que salió se queda en el otro broker; lo que llegó se borra con éste y no vuelve
    al de origen, salvo que se deshaga el pase."""
    nombres = [n for n in (nombres or []) if n]
    out: Dict[str, List[str]] = {"salida": [], "entrada": []}
    ids = pases_de_brokers(conn, uid, nombres)
    if not ids:
        return out
    lados = {}
    for r in conn.execute(
            f"""SELECT DISTINCT n.traspaso_id AS tid, n.batch_id AS bid FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND b.parser_format = ? AND n.traspaso_id IS NOT NULL
                   AND (b.broker IN ({_ph(nombres)}) OR n.broker IN ({_ph(nombres)}))""",
            (uid, FORMATO, *nombres, *nombres)).fetchall():
        lados.setdefault(r["tid"], set()).add(r["bid"])
    for t in conn.execute(
            f"SELECT id, lote_salida, lote_entrada FROM traspasos_a_mano WHERE user_id = ? "
            f"AND id IN ({_ph(ids)})", (uid, *ids)).fetchall():
        bids = lados.get(t["id"], set())
        if t["lote_salida"] in bids:
            out["salida"].append(t["id"])
        if t["lote_entrada"] in bids:
            out["entrada"].append(t["id"])
    return out


def _moneda_de(valor) -> Optional[str]:
    """'ARS', 'USD' (cualquier otra moneda de un título: USD, USDT…) o None si no se
    sabe."""
    v = str(valor or "").strip().upper()
    return None if not v else ("ARS" if v == "ARS" else "USD")


def _compra_que_no_toca_el_pase(conn, uid: int, reg: Registro, f: Dict[str, Any],
                                cache: Dict[Any, bool]) -> bool:
    """¿Una COMPRA del lado A en OTRA moneda que la del pase no puede cambiar lo que
    el pase consumió? El persister y el rebuild consumen por moneda: el pase (que
    nunca cruza de moneda) se lleva lotes de SU moneda. Una compra en la otra moneda
    sólo los toca a través del «pool único» (`rebuild._replay_asset`): una VENTA en
    esa otra moneda que no alcanza con sus lotes sigue con los de la moneda del pase
    (o se los deja, si la compra aparece). Sin ventas en esa moneda hasta el día del
    pase en las patas de A, no hay por dónde: la compra no cambia el pase. Con una,
    se frena como siempre (ante la duda, frenar). Una fila sin moneda conocida
    cuenta como de la moneda del pase."""
    moneda = _moneda_de(f.get("currency"))
    if moneda is None or moneda == _moneda_de(reg.moneda):
        return False
    clave = (reg.id, moneda)
    if clave not in cache:
        cache[clave] = conn.execute(
            f"""SELECT 1 FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND n.broker IN ({_ph(reg.patas_a)})
                   AND UPPER(n.asset_symbol) = ? AND n.operation_type = 'SELL'
                   AND n.traspaso_id IS NULL AND substr(n.date, 1, 10) <= ?
                   AND (CASE WHEN UPPER(COALESCE(n.currency, '')) = 'ARS' THEN 'ARS'
                             ELSE 'USD' END) = ?
                 LIMIT 1""",
            (uid, *reg.patas_a, _canon(reg.asset), reg.fecha, moneda)).fetchone() is None
    return cache[clave]


def pase_que_cambia(conn, uid: int, filas, *, excluir=None,
                    plantilla: Optional[str] = None, lados=("origen", "destino"),
                    el_dia_del_pase: bool = True) -> Optional[Dict[str, Any]]:
    """C.11, la regla única. `filas`: dicts {broker, asset, op, date, fecha_compra,
    traspaso_id} que una puerta está por agregar, sacar o reescribir en el registro.
    Devuelve el primer pase vivo cuya historia anterior cambiaría —{traspaso_id, lado
    ('origen'|'destino'), fecha, contraparte, asset, broker, op, fecha_fila,
    mensaje}— o None. `mensaje` sale de `plantilla` (por defecto `MSG_CAMBIA_UN_PASE`;
    el importador pasa `MSG_IMPORT_CAMBIA_UN_PASE`, que además nombra si el archivo
    trae compras o ventas y de qué día).
      · Lado A (su lote sigue confirmado, la fila en una pata de A, el mismo activo, no
        es del pase): una COMPRA del día del pase o antes y comprada no después que lo
        más nuevo que se movió (cambia los lotes que el pase consumió), o una VENTA del
        día del pase o antes.
      · Lado B (su lote sigue confirmado, la fila en una pata de B): una VENTA anterior
        al pase (el rearmado de B fabricaría un lote semilla y dejaría los movidos
        enteros: títulos de más).
    Una COMPRA del lado A en otra moneda que la del pase no lo cambia si no hay por
    dónde cruzar de moneda (`_compra_que_no_toca_el_pase`): sin eso, borrar o
    importar una compra del mismo CEDEAR en dólares frenaba por un pase de los de
    pesos. `filas` puede traer `currency` (si no, cuenta como de la moneda del pase).
    `lados`: qué lados mirar; `el_dia_del_pase=False` deja afuera, del lado A, una
    fila del MISMO día del pase (la venta a mano anotada después del pase: la cuenta
    como posterior, igual que el deshacer, C.8 #3)."""
    filas = [f for f in (filas or [])
             if f and str(f.get("op") or "").upper() in ("BUY", "SELL")]
    if not filas:
        return None
    excluir = set(excluir or ())
    cache: Dict[Any, bool] = {}
    for reg in _registros(conn, uid, vivos=True):
        if reg.id in excluir:
            continue
        asset = _canon(reg.asset)
        for f in filas:
            if f.get("traspaso_id") == reg.id or _canon(f.get("asset")) != asset:
                continue
            op = str(f.get("op")).upper()
            d = _dia(f.get("date")) or ""
            fc = _dia(f.get("fecha_compra")) or d
            lado = None
            antes_del_pase = d and (d <= reg.fecha if el_dia_del_pase else d < reg.fecha)
            if "origen" in lados and reg.a_vivo and f.get("broker") in reg.patas_a \
                    and antes_del_pase:
                # Una venta que sólo puede consumir lotes de SU moneda (la venta a
                # mano, cuando hay lotes de esa moneda: no hace spill) y no es la del
                # pase, no toca lo que el pase se llevó.
                otra_moneda = (f.get("solo_su_moneda")
                               and _moneda_de(f.get("currency")) not in (None, _moneda_de(reg.moneda)))
                if (op == "SELL" and not otra_moneda) or (
                        op == "BUY" and fc <= reg.compra_mas_nueva
                        and not _compra_que_no_toca_el_pase(conn, uid, reg, f, cache)):
                    lado = "origen"
            if lado is None and "destino" in lados and reg.b_vivo \
                    and f.get("broker") in reg.patas_b and op == "SELL" and d and d < reg.fecha:
                lado = "destino"
            if lado:
                broker = reg.raiz_a if lado == "origen" else reg.raiz_b
                contraparte = reg.raiz_b if lado == "origen" else reg.raiz_a
                hacia = "a" if lado == "origen" else "desde"
                return {"traspaso_id": reg.id, "lado": lado, "fecha": reg.fecha,
                        "contraparte": contraparte, "asset": reg.asset, "broker": broker,
                        "op": op, "fecha_fila": d,
                        "mensaje": (plantilla or MSG_CAMBIA_UN_PASE).format(
                            asset=reg.asset, broker=broker, fecha=_ddmmaaaa(reg.fecha),
                            hacia=hacia, contraparte=contraparte,
                            que="ventas" if op == "SELL" else "compras",
                            fecha_fila=_ddmmaaaa(d))}
    return None


def fila_del_registro(fila) -> Dict[str, Any]:
    """Una fila de `import_normalized_tx` en la forma que pide `pase_que_cambia`."""
    d = dict(fila)
    return {"broker": d.get("broker"), "asset": d.get("asset_symbol"),
            "op": d.get("operation_type"), "date": d.get("date"),
            "fecha_compra": d.get("fecha_compra"), "traspaso_id": d.get("traspaso_id"),
            "currency": d.get("currency")}


def lotes_que_no_estaban(lotes, fecha: str):
    """Hueco C4: de la cola FIFO de una venta a mano (`lotes`, filas de `positions`
    ya en orden), los que llegaron a esta cuenta por un pase DESPUÉS de `fecha` (su
    `en_broker_desde` es posterior). Una venta de ese día no los puede consumir: no
    estaban. Los lotes sin `en_broker_desde` siguen como siempre."""
    f = _dia(fecha) or ""
    return [l for l in lotes if l["en_broker_desde"] and _dia(l["en_broker_desde"]) > f]


# ═══ E8: los imports que llegan DESPUÉS de un pase ════════════════════════════
#
# EL ANTIDUPLICADO (D.7, decisión 7). El pase ya anotó la salida de A y la llegada a
# B. Si después la persona importa el archivo de B, trae esa misma llegada
# («Transferencia Externa (Crédito)» de Balanz, el DETR de IEB) con su depósito
# compensatorio; el de A trae la salida («Débito», RETR). Entraría dos veces: B con
# los títulos al doble y el aportado contado dos veces. `filas_ya_traspasadas` las
# reconoce y el confirm las omite (siempre: también cuando la persona fuerza los
# repetidos por huella, que es otra cosa). Lo omitido queda anotado en el pase
# (`omitidas_json`): deshacer el pase dejaría esos títulos sin registrar, y el
# deshacer frena con el camino (C.8 #2).
#
# Las tres ventanas, por fila, contra la fecha del pase:
#   · hasta `flujos.DIAS_CRUCE` (4) días → es el mismo movimiento (un traspaso no
#     liquida el mismo día en los dos brokers): se omite;
#   · hasta `DIAS_TRASPASO_TARDIO` (60) → puede ser el mismo con la fecha del pase mal
#     anotada: el import frena y dice qué fecha poner;
#   · más lejos → es otro movimiento: entra, con un aviso.
# Sólo cuenta lo que entra en lo que el pase movió en esa cuenta (su «presupuesto»):
# ante la duda se omite de menos (PLAN §12.1). La salida de A cuenta sólo la parte
# importada (las SELL del pase): un Débito que incluye lotes que eran cargados a
# mano no se omite —el mismo archivo trae sus compras, y la regla única frena el
# import entero (C.11)—.
#
# EL FRENO (D.10.16). Un import que cambiaría la historia anterior a un pase vivo
# (compras o ventas en A hasta el día del pase, ventas en B antes del pase) frena con
# `MSG_IMPORT_CAMBIA_UN_PASE`: es la misma regla que las demás puertas
# (`pase_que_cambia`), sobre lo que queda después de deduplicar. La vista previa lo
# anticipa (`cambian_un_pase`) y el confirm lo vuelve a mirar dentro de su transacción.

MSG_FRENO_ENTRADA = ("El archivo de {B} dice que los {asset} llegaron el {fila} y el pase "
                     "lo anotaste el {pase}. Para no contarlos dos veces, deshacé el pase y "
                     "hacelo de nuevo con fecha {fila}; después importá el archivo.")
MSG_FRENO_SALIDA = ("El archivo de {A} dice que los {asset} salieron el {fila} y el pase "
                    "lo anotaste el {pase}. Para no contarlos dos veces, deshacé el pase y "
                    "hacelo de nuevo con fecha {fila}; después importá el archivo.")
# Lo que entra igual, con un aviso: muy lejos de la fecha del pase, o más títulos de
# los que el pase movió en esa cuenta.
AVISO_ENTRADA_LEJOS = ("Ojo: este archivo trae una llegada de {q} {asset} a {B} el {fila}, "
                       "lejos de tu pase desde {A} del {pase}: la cargamos como otra llegada. "
                       "Si es la misma, deshacé el pase antes de importar el archivo.")
AVISO_SALIDA_LEJOS = ("Ojo: este archivo trae una salida de {q} {asset} de {A} el {fila}, "
                      "lejos de tu pase a {B} del {pase}: la cargamos como otra salida. "
                      "Si es la misma, deshacé el pase antes de importar el archivo.")
AVISO_ENTRADA_DE_MAS = ("Ojo: este archivo trae una llegada de {q} {asset} a {B} el {fila}, "
                        "cerca de tu pase desde {A} del {pase}, pero son más de los {n} que "
                        "pasaste: la cargamos. Si incluye los del pase, deshacé el pase antes "
                        "de importar el archivo.")
AVISO_SALIDA_DE_MAS = ("Ojo: este archivo trae una salida de {q} {asset} de {A} el {fila}, "
                       "cerca de tu pase a {B} del {pase}, pero son más de los {n} que salieron "
                       "de tus archivos: la cargamos. Si incluye los del pase, deshacé el pase "
                       "antes de importar el archivo.")
# Cabía en lo que el pase movió, pero otra fila del mismo archivo ya lo explicó (se
# omitió esa): ésta entra.
AVISO_ENTRADA_YA_EXPLICADA = ("Ojo: este archivo trae otra llegada de {q} {asset} a {B} el "
                              "{fila}, cerca de tu pase desde {A} del {pase}, pero los {n} que "
                              "pasaste ya los explica otra fila del archivo: la cargamos. Si es "
                              "la misma llegada repetida, deshacé el pase antes de importar el "
                              "archivo.")
AVISO_SALIDA_YA_EXPLICADA = ("Ojo: este archivo trae otra salida de {q} {asset} de {A} el "
                             "{fila}, cerca de tu pase a {B} del {pase}, pero los {n} que "
                             "salieron de tus archivos ya los explica otra fila del archivo: la "
                             "cargamos. Si es la misma salida repetida, deshacé el pase antes "
                             "de importar el archivo.")


@dataclass
class YaTraspasadas:
    """Lo que `filas_ya_traspasadas` encontró en un import.

    `indices`: los `row_index` que el confirm omite (las llegadas o salidas del pase
    y el depósito compensatorio de cada llegada). `detalle`: una línea por título
    omitido, para la vista previa (`ya_traspasados`: fecha, activo, cantidad, broker,
    lado, más row_index y traspaso_id). `omitidas`: lo que se anota en cada pase
    ({traspaso_id, row_index, lado}, el depósito incluido). `frenos`: las filas a más
    de 4 y hasta 60 días (el import no entra; cada una con su `mensaje`). `avisos`:
    textos de lo que entra igual."""
    indices: set = field(default_factory=set)
    detalle: List[Dict[str, Any]] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    frenos: List[Dict[str, Any]] = field(default_factory=list)
    omitidas: List[Dict[str, Any]] = field(default_factory=list)


def _lado_de_la_fila(t) -> Optional[str]:
    """'entrada' si la fila del archivo es la llegada de títulos desde otro broker
    (una COMPRA con `transfer_in`, o el DETR de IEB, que no la marca); 'salida' si es
    su salida hacia otro (una VENTA con `transfer_out` que no es de una foto de
    tenencia); None si no es ninguna de las dos."""
    if getattr(t, "traspaso_id", None):
        return None                     # una fila de un pase nunca viene en un archivo
    op = str(getattr(t, "operation_type", "") or "").upper()
    notas = str(getattr(t, "notes", "") or "")
    if op == "BUY" and (getattr(t, "transfer_in", False) or "IEB:DETR" in notas):
        return "entrada"
    if op == "SELL" and getattr(t, "transfer_out", False) and not notas.startswith("Tenencia"):
        return "salida"
    return None


def _presupuesto(conn, reg: Registro, lado: str) -> float:
    """Cuántos títulos del pase puede explicar un archivo de ese lado: lo que llegó a
    las patas de B (las COMPRAS del lote de B) o lo que salió de las patas de A por
    sus archivos (las VENTAS del pase: sólo la parte importada)."""
    if lado == "entrada":
        lote, op, patas = reg.lote_entrada, "BUY", reg.patas_b
    else:
        lote, op, patas = reg.lote_salida, "SELL", reg.patas_a
    if not patas:
        return 0.0
    r = conn.execute(
        f"""SELECT COALESCE(SUM(n.quantity), 0) AS q FROM {TX_VIVAS}
             WHERE n.batch_id = ? AND n.traspaso_id = ? AND n.operation_type = ?
               AND n.broker IN ({_ph(patas)})""",
        (lote, reg.id, op, *patas)).fetchone()
    return _num(r["q"]) if r else 0.0


def _deposito_hermano(t, txs, usados: set):
    """El DEPÓSITO compensatorio que el lector emite junto con una llegada de títulos
    (Balanz: «Transferencia Externa (entrada de título)»; IEB: «IEB:DETR … (cash
    compensatorio)»): la misma pata, el mismo día, la misma moneda y el mismo monto
    (±1 %, o ±1 unidad). Uno por llegada, el primero libre."""
    monto = abs(_num(getattr(t, "gross_amount", None)))
    if monto <= 0:
        return None                     # una llegada sin valor no trae depósito
    tol = max(0.01 * monto, 1.0)
    for d in sorted(txs, key=lambda x: x.row_index):
        if d.row_index in usados or str(d.operation_type or "").upper() != "DEPOSIT":
            continue
        notas = str(d.notes or "")
        if not ("entrada de título" in notas.lower() or "entrada de titulo" in notas.lower()
                or "IEB:DETR" in notas):
            continue
        if (_clave_nombre(d.broker) != _clave_nombre(t.broker) or _dia(d.date) != _dia(t.date)
                or str(d.currency or "").upper() != str(t.currency or "").upper()):
            continue
        if abs(abs(_num(d.gross_amount)) - monto) <= tol:
            return d
    return None


def filas_ya_traspasadas(conn, uid: int, txs, *, already_skipped=()) -> YaTraspasadas:
    """El antiduplicado semántico de un import posterior a un pase (D.7). `txs`: las
    filas del archivo (`NormalizedTx`); `already_skipped`: las que ya no van a entrar
    por otro motivo (la persona las destildó o esperan aprobación) y no cuentan. Va
    antes que los repetidos por huella (`pipeline.repeticiones`): el «Débito» del día
    del pase tiene la huella de la salida del pase, y lo omitido por el pase tiene
    que quedar anotado. Mira los pases vivos: del lado de la llegada con el lote de
    B confirmado, del de la salida con el de A confirmado. Cada fila se compara con el
    pase más cercano en fecha que la pueda explicar (el mismo activo, una pata de esa
    cuenta y no más títulos de los que le quedan al pase por explicar). Sólo lee."""
    out = YaTraspasadas()
    skip = set(already_skipped or ())
    candidatas = sorted((t for t in (txs or []) if t.row_index not in skip and _lado_de_la_fila(t)),
                        key=lambda t: t.row_index)
    if not candidatas:
        return out
    regs = _registros(conn, uid, vivos=True)
    if not regs:
        return out
    from flujos import DIAS_CRUCE
    presupuesto: Dict[Tuple[str, str], float] = {}
    for reg in regs:
        if reg.b_vivo:
            presupuesto[(reg.id, "entrada")] = _presupuesto(conn, reg, "entrada")
        if reg.a_vivo:
            presupuesto[(reg.id, "salida")] = _presupuesto(conn, reg, "salida")
    movido = dict(presupuesto)          # lo que el pase movió (no se descuenta)
    usados = set(skip)
    for t in candidatas:
        lado = _lado_de_la_fila(t)
        fila = _dia(t.date) or ""
        q = _num(t.quantity)
        suyos = [reg for reg in regs if (reg.id, lado) in presupuesto
                 and _canon(reg.asset) == _canon(t.asset_symbol)
                 and _clave_nombre(t.broker) in {_clave_nombre(p) for p in
                                                 (reg.patas_b if lado == "entrada" else reg.patas_a)}]
        if not suyos or not fila or q <= 0:
            continue
        suyos.sort(key=lambda r: (_dias_entre(fila, r.fecha), r.fecha, r.id))
        reg = next((r for r in suyos if q <= presupuesto[(r.id, lado)] + _TOL_CANT), None)
        datos = dict(asset=t.asset_symbol, q=_cant(q), fila=_ddmm(fila), A=None, B=None)
        if reg is None:
            # Más títulos de los que el pase movió en esa cuenta: no es seguro que sean
            # los mismos (ante la duda se omite de menos). Entra, con un aviso. El
            # número del aviso es lo que el pase MOVIÓ en esa cuenta (el presupuesto de
            # arriba se va descontando con cada fila omitida: decía «más de los 0»).
            cerca = suyos[0]
            if _dias_entre(fila, cerca.fecha) <= DIAS_TRASPASO_TARDIO:
                total = movido[(cerca.id, lado)]
                datos.update(A=cerca.raiz_a, B=cerca.raiz_b, pase=_ddmm(cerca.fecha),
                             n=_cant(total))
                if q <= total + _TOL_CANT:
                    # Cabía en el pase, pero otra fila del archivo ya lo explicó.
                    plantilla = (AVISO_ENTRADA_YA_EXPLICADA if lado == "entrada"
                                 else AVISO_SALIDA_YA_EXPLICADA)
                else:
                    plantilla = AVISO_ENTRADA_DE_MAS if lado == "entrada" else AVISO_SALIDA_DE_MAS
                out.avisos.append(plantilla.format(**datos))
            continue
        dias = _dias_entre(fila, reg.fecha)
        datos.update(A=reg.raiz_a, B=reg.raiz_b, pase=_ddmm(reg.fecha))
        if dias <= DIAS_CRUCE:
            presupuesto[(reg.id, lado)] -= q
            usados.add(t.row_index)
            out.indices.add(t.row_index)
            out.detalle.append({"fecha": fila, "activo": t.asset_symbol, "cantidad": q,
                                "broker": t.broker, "lado": lado, "row_index": t.row_index,
                                "traspaso_id": reg.id})
            out.omitidas.append({"traspaso_id": reg.id, "row_index": t.row_index, "lado": lado})
            if lado == "entrada":
                d = _deposito_hermano(t, txs, usados)
                if d is not None:
                    usados.add(d.row_index)
                    out.indices.add(d.row_index)
                    out.omitidas.append({"traspaso_id": reg.id, "row_index": d.row_index,
                                         "lado": lado})
        elif dias <= DIAS_TRASPASO_TARDIO:
            out.frenos.append({
                "traspaso_id": reg.id, "lado": "destino" if lado == "entrada" else "origen",
                "fecha": reg.fecha, "fecha_fila": fila, "asset": reg.asset,
                "broker": reg.raiz_b if lado == "entrada" else reg.raiz_a,
                "contraparte": reg.raiz_a if lado == "entrada" else reg.raiz_b,
                "op": "BUY" if lado == "entrada" else "SELL", "row_index": t.row_index,
                "mensaje": (MSG_FRENO_ENTRADA if lado == "entrada"
                            else MSG_FRENO_SALIDA).format(**datos)})
        else:
            out.avisos.append((AVISO_ENTRADA_LEJOS if lado == "entrada"
                               else AVISO_SALIDA_LEJOS).format(**datos))
    return out


def fila_de_tx(t) -> Dict[str, Any]:
    """Una fila de un archivo (`NormalizedTx`) en la forma que pide `pase_que_cambia`."""
    return {"broker": getattr(t, "broker", None), "asset": getattr(t, "asset_symbol", None),
            "op": getattr(t, "operation_type", None), "date": getattr(t, "date", None),
            "fecha_compra": getattr(t, "fecha_compra", None),
            "traspaso_id": getattr(t, "traspaso_id", None),
            "currency": getattr(t, "currency", None)}


def freno_del_import(conn, uid: int, txs, *, ya: YaTraspasadas, sin=()) -> Optional[Dict[str, Any]]:
    """D.10.16: por qué un import no puede entrar a causa de un pase, o None. Lo usan
    la vista previa (`cambian_un_pase`) y el confirm (409), con la MISMA cuenta.
      1. Lo que el antiduplicado no pudo decidir solo (`ya.frenos`: una llegada o una
         salida del archivo a más de 4 días y hasta 60 de la fecha del pase): su texto
         dice qué fecha ponerle al pase. Va primero porque es más preciso que la regla
         general para la misma fila.
      2. La regla única (C.11) sobre lo que queda: sin `sin` (lo que no va a entrar) ni
         lo que el antiduplicado omite."""
    if ya.frenos:
        return ya.frenos[0]
    fuera = set(sin or ()) | set(ya.indices)
    filas = [fila_de_tx(t) for t in (txs or []) if t.row_index not in fuera]
    return pase_que_cambia(conn, uid, filas, plantilla=MSG_IMPORT_CAMBIA_UN_PASE)


def anotar_omitidas(conn, uid: int, batch_id: str, ya: YaTraspasadas) -> None:
    """Anota en cada pase las filas del lote `batch_id` que el confirm omitió por él
    (`omitidas_json`: [{batch_id, row_index, lado}]). Va dentro de la transacción del
    confirm: si el import no entra, no queda anotado. Mientras ese lote siga
    confirmado, deshacer el pase frena (C.8 #2)."""
    por_pase: Dict[str, List[Dict[str, Any]]] = {}
    for o in ya.omitidas:
        por_pase.setdefault(o["traspaso_id"], []).append(
            {"batch_id": batch_id, "row_index": o["row_index"], "lado": o["lado"]})
    for tid, nuevas in por_pase.items():
        r = conn.execute("SELECT omitidas_json FROM traspasos_a_mano WHERE id=? AND user_id=?",
                         (tid, uid)).fetchone()
        if not r:
            continue
        try:
            todas = [o for o in (json.loads(r["omitidas_json"] or "[]") or [])
                     if isinstance(o, dict)]
        except (TypeError, ValueError):
            todas = []
        ya_estan = {(o.get("batch_id"), o.get("row_index")) for o in todas}
        todas += [o for o in nuevas if (o["batch_id"], o["row_index"]) not in ya_estan]
        conn.execute("UPDATE traspasos_a_mano SET omitidas_json=? WHERE id=? AND user_id=?",
                     (json.dumps(todas), tid, uid))


def lotes_de_pases(conn, uid: int) -> Dict[str, Dict[str, Any]]:
    """{import_batches.id de un lote de pase: {id, asset, cantidad, lado, contraparte,
    estado}} para la lista de Importaciones (D.2.6). `lado`: 'salida' (el lote de A) o
    'entrada' (el de B); `contraparte`: el nombre de hoy de la otra cuenta; `estado`:
    vivo, incompleto, desfasado o deshecho."""
    out: Dict[str, Dict[str, Any]] = {}
    for reg in _registros(conn, uid, vivos=False):
        estado = "deshecho" if reg.deshecho_at else reg.estado
        base = {"id": reg.id, "asset": reg.asset, "cantidad": reg.cantidad, "estado": estado}
        out[reg.lote_salida] = {**base, "lado": "salida", "contraparte": reg.raiz_b}
        out[reg.lote_entrada] = {**base, "lado": "entrada", "contraparte": reg.raiz_a}
    return out


# ── E9: cómo se MUESTRA un pase (Movimientos, el CSV del contador, D.9) ──────────
#
# Un pase escribe en el registro filas que no son operaciones de la persona: la
# VENTA de salida de A (a precio 0, sólo para que A suelte los lotes) y una COMPRA de
# llegada en B por cada lote (la copia del costo, las comisiones y la fecha de compra
# de A). Mostradas, Movimientos y `transactions.csv` tenían una venta y una compra que
# nadie hizo, y la comisión de cada lote se contaba DOS veces (la compra original en
# A y su copia en B) en el KPI «Comisiones» y en /api/insights/commissions. Del pase
# se muestran sus dos patas (TRASPASO_SALIDA y TRASPASO_ENTRADA, con lo que valían
# los títulos ese día) y el gasto del trámite. Y la compra original de un lote
# CARGADO A MANO, que el pase sacó de `positions` (sin ella desaparecía de
# Movimientos, con su comisión), sale de la receta (`lotes_a_mano_que_salieron`).

# Las notas del CSV de transacciones en las dos patas: hacia dónde fueron (o de dónde
# vinieron) y lo que costaron. Se arman al leer, así llevan el nombre de HOY de la
# otra cuenta (las notas guardadas en el registro no llevan ninguno, A.6).
NOTA_CSV_SALIDA = "pasaron a {contraparte} · costo original US$ {costo:.2f}"
NOTA_CSV_ENTRADA = "llegaron desde {contraparte} · costo original US$ {costo:.2f}"
# La compra original de un lote cargado a mano que se pasó (Movimientos y el CSV).
NOTA_COMPRA_PASADA = "La pasaste a {B} el {fecha}"


def es_fila_interna_del_pase(op, traspaso_id) -> bool:
    """¿Es una de las compras o ventas que el pase escribió para mover los lotes? No
    son operaciones de la persona: no se muestran (D.9.1, D.9.3)."""
    return bool(traspaso_id) and str(op or "").upper() in ("BUY", "SELL")


def lados_de_los_pases(conn, uid: int) -> Dict[str, Dict[str, Any]]:
    """{traspaso_id: {origen, destino, estado, aviso}} de los pases que no se
    deshicieron: el nombre de HOY de cada cuenta (si un lado se borró, el de la
    receta), cómo está el pase (vivo, incompleto o desfasado: la misma regla que GET
    /traspasos) y, si está desfasado, el MISMO aviso que GET /traspasos
    (`aviso_del_pase`). Lo usan Movimientos y el CSV para decir hacia dónde fue cada
    pata. Una lectura por pedido, no una por fila."""
    return {reg.id: {"origen": reg.raiz_a, "destino": reg.raiz_b, "estado": reg.estado,
                     "aviso": aviso_del_pase(reg)}
            for reg in _registros(conn, uid, vivos=True)}


def contraparte_de_la_pata(lado: Optional[Dict[str, Any]], op) -> Optional[str]:
    """La OTRA cuenta del pase, vista desde una de sus patas: la de destino para la
    que salió, la de origen para la que entró."""
    if not lado:
        return None
    return lado["destino"] if str(op or "").upper() == "TRASPASO_SALIDA" else lado["origen"]


def monto_de_la_pata(fila) -> Dict[str, Optional[float]]:
    """Lo que valían los títulos de una pata del pase (V de ese par, el MISMO número
    en las dos patas, A.6): en dólares (`usd`), en pesos (`ars`), en la moneda de los
    lotes (`nativo`: los pesos si los lotes son en pesos, los dólares si no) y por
    título en esa moneda (`precio`).

    El `unit_price` guardado en la fila está en la moneda del PRECIO, que no siempre
    es la de los lotes (un CEDEAR comprado en dólares se valúa con su precio en
    pesos): al lado de un monto en dólares no cuadraba. Movimientos y el CSV muestran
    `precio`, que sí: cantidad × precio = monto."""
    usd, ars = _num(fila["valor_usd"]), _num(fila["valor_ars"])
    nativo = ars if str(fila["currency"] or "").upper() == "ARS" else usd
    q = abs(_num(fila["quantity"]))
    return {"usd": usd, "ars": ars, "nativo": nativo, "precio": (nativo / q) if q else None}


def nota_csv_de_la_pata(fila, lado: Optional[Dict[str, Any]]) -> str:
    """Las notas de una pata del pase en `transactions.csv` (D.9.3): hacia dónde
    pasaron (o de dónde llegaron) y lo que costaron en dólares (C de ese par)."""
    op = str(fila["operation_type"] or "").upper()
    plantilla = NOTA_CSV_SALIDA if op == "TRASPASO_SALIDA" else NOTA_CSV_ENTRADA
    return plantilla.format(contraparte=contraparte_de_la_pata(lado, op) or "otro broker tuyo",
                            costo=_num(fila["costo_usd"]))


def nota_de_compra_pasada(lote: Dict[str, Any], lado: Optional[Dict[str, Any]], *,
                          con_notas: bool = True) -> str:
    """La nota de la compra original de un lote cargado a mano que se pasó
    (`lotes_a_mano_que_salieron`): a qué cuenta y cuándo. Con `con_notas`, seguida
    de las notas que tenía el lote (Movimientos las mostraba antes del pase)."""
    destino = (lado or {}).get("destino") or "otro broker tuyo"
    nota = NOTA_COMPRA_PASADA.format(B=destino, fecha=_ddmmaaaa(lote.get("fecha_pase")))
    return f"{nota} · {lote['notes']}" if (con_notas and lote.get("notes")) else nota


# ── E10: el detector de pases desfasados (D.5.5) ───────────────────────────────
#
# Las puertas (`pase_que_cambia`, C.11, y las guardas de D.10) frenan lo que
# reescribiría la historia anterior a un pase vivo. Si algo se les escapa —una fila
# escrita por un camino que no las pasa, un script, una edición que no estaba en la
# lista—, el próximo rearmado del registro lo hace visible: el pase queda
# «desfasado», GET /traspasos y Movimientos lo dicen con el aviso, y el deshacer
# deja la cuenta como si el pase no hubiera existido.
#
# Corre en las DOS reconstrucciones (`rebuild.rebuild_fifo_after_import` y
# `rebuild.rebuild_pair_asset`, después de escribir y dentro de su SAVEPOINT), que
# son las únicas que reescriben lotes desde el registro: las llaman el import, el
# backfill (`recompute_user`), la migración del dólar (`migrate_user_fx`), los
# borrados de operaciones e historial y el deshacer de un pase. Cada llamada mira
# UN (par de brokers, activo): el lado de A de los pases cuya salida está en ese par
# y el lado de B de los que llegaron a él.


def _lo_que_movio_de_archivos(receta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Los lotes IMPORTADOS que movió el pase, en la forma que compara `_coinciden`:
    fecha de compra, cantidad, inversión y comisiones movidas. Son los mismos números
    que el confirmar escribió en las COMPRAS de llegada de B (C.6) y los que comparó
    la comprobación en seco antes de escribir (C.2.6): por eso la receta sirve también
    cuando B ya no existe. Los cargados a mano no están: salieron por `positions`, no
    por la salida del registro."""
    return [{"entry_date": _dia((l.get("foto") or {}).get("entry_date")) or "",
             "qty": _num(l.get("cantidad")), "invested": _num(l.get("invested")),
             "commissions": _num(l.get("commissions"))}
            for l in (receta.get("lotes") or [])
            if isinstance(l, dict) and l.get("origen") == "importado"]


def _ventas_nuevas_sin_lotes(replay, llegada: str, ultimo: int) -> List[Dict[str, Any]]:
    """Las semillas del replay de B anteriores a la llegada del pase que fabricó una
    venta (no de otro pase) escrita DESPUÉS del pase (su fila tiene un id mayor que
    las del pase). Una que ya estaba cuando se hizo el pase —un archivo de B con la
    historia cortada vendió títulos de antes— es dato normal: el pase se armó con
    ella a la vista (B.6 sólo frena las ventas de B desde el día del pase)."""
    return [s for s in (replay.get("semillas_detalle") or [])
            if (_dia(s.get("fecha")) or "") < llegada and not s.get("traspaso_id")
            and int(s.get("fila") or 0) > ultimo]


def _lados_que_no_cuadran(conn, t, salidas, llegadas, replay):
    """(lados que no cuadran, lados que sí) del pase `t` (fila de `traspasos_a_mano`)
    según este replay. Un pase aparece en un replay de un solo lado: A y B nunca son
    el mismo par (B.6 #3)."""
    tid = t["id"]
    malos, buenos = [], []
    if tid in salidas:
        try:
            receta = json.loads(t["receta_json"] or "{}") or {}
        except (TypeError, ValueError):
            receta = {}
        # LADO A (origen): lo que la salida del pase se llevó del registro tiene que
        # ser justo lo que el pase movió de archivos. Es la MISMA comparación que la
        # comprobación en seco antes de escribir (`_comprobar_con_el_registro`): si
        # cuadró entonces, un registro que nadie tocó cuadra en cada rearmado.
        (buenos if _coinciden(_lo_que_movio_de_archivos(receta), salidas[tid])
         else malos).append("origen")
    if tid in llegadas:
        # LADO B (destino): una venta anterior a la llegada que encontró B sin títulos
        # (el replay fabricó una semilla y dejó los que llegaron enteros: B queda con
        # títulos de más) y que se escribió después del pase.
        ultimo = _id_mas_alto_del_pase(conn, t["lote_entrada"], tid)
        (malos if _ventas_nuevas_sin_lotes(replay, _dia(llegadas[tid]) or "", ultimo)
         else buenos).append("destino")
    return malos, buenos


def marcar_desfasados(conn, uid: int, replay) -> Dict[str, Optional[str]]:
    """D.5.5. Con el replay de UN (par, activo) recién escrito, marca o desmarca los
    pases vivos que pasan por él:
      · si un lado no cuadra y el pase no estaba marcado → `desfasado_at` = ahora y
        `desfasado_motivo` = ese lado ('origen' | 'destino');
      · si el lado vuelve a cuadrar y el motivo era ese lado → los dos a NULL.
    Devuelve {traspaso_id: motivo puesto | None si se desmarcó}, sólo los cambios.

    Sin pases en el replay no hace ninguna consulta (la enorme mayoría de los
    rearmados). No tumba la reconstrucción: corre en su propio punto de guardado y,
    si algo le falla, lo deshace, lo anota en el log y sigue (el aviso es un aviso;
    los lotes ya están bien escritos)."""
    salidas = (replay or {}).get("traspasos") or {}
    llegadas = (replay or {}).get("llegadas_de_pases") or {}
    tids = sorted(set(salidas) | set(llegadas))
    if not tids:
        return {}
    import pgsesion
    try:
        with pgsesion.si_falla_se_deshace_solo_esto(conn, "marcar_desfasados"):
            return _marcar_desfasados(conn, uid, tids, salidas, llegadas, replay)
    except Exception:
        log.exception("traspaso_a_mano: el detector de desfase falló (user=%s, pases=%s)",
                      uid, tids)
        return {}


def _marcar_desfasados(conn, uid, tids, salidas, llegadas, replay):
    cambios: Dict[str, Optional[str]] = {}
    for t in conn.execute(
            f"SELECT id, lote_entrada, receta_json, desfasado_at, desfasado_motivo "
            f"FROM traspasos_a_mano WHERE user_id = ? AND deshecho_at IS NULL "
            f"AND id IN ({_ph(tids)})", (uid, *tids)).fetchall():
        malos, buenos = _lados_que_no_cuadran(conn, t, salidas, llegadas, replay)
        if malos and not t["desfasado_at"]:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=datetime('now'), "
                         "desfasado_motivo=? WHERE id=? AND user_id=? AND desfasado_at IS NULL",
                         (malos[0], t["id"], uid))
            cambios[t["id"]] = malos[0]
            log.warning("traspaso_a_mano: el pase %s (user=%s) quedó desfasado por %s",
                        t["id"], uid, malos[0])
        elif t["desfasado_at"] and not malos and t["desfasado_motivo"] in buenos:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=NULL, desfasado_motivo=NULL "
                         "WHERE id=? AND user_id=?", (t["id"], uid))
            cambios[t["id"]] = None
    return cambios


# ═══════════════════════════════════════════════════════════════════════════════
# E11 — La migración del dólar revalúa las patas (C.10, D.17)
# ═══════════════════════════════════════════════════════════════════════════════
#
# QUÉ PROBLEMA RESUELVE. Las patas de un pase guardan V y C en dólares, calculados
# con la regla del dólar que tenía la cuenta ese día. Una cuenta vieja (v1) pasa
# pesos a dólares con UN dólar, el de la config; la migración (`migrate_user_fx`) la
# pasa al dólar de CADA fecha (v2) y rearma todo lo demás con esa regla: los flujos,
# las ventas y los lotes. Las patas no las rearma nadie: quedaban con los números
# viejos. Como el capital de A baja C y el de B sube C, B terminaba con el C viejo de
# capital y lotes cuyo costo, con la regla nueva, es otro: la identidad «capital =
# lo aportado + el costo de lo que llegó» quedaba corrida en C_v1 − C_v2 (y A al
# revés), para siempre. Cualquier import posterior dispara la migración sola
# (`main._auto_migrar_fx_post_import`), así que no es un caso raro.
#
# QUÉ HACE. `revaluar_patas` vuelve a calcular, desde la receta de cada pase no
# deshecho (el precio que vio la persona, la fecha y los lotes con su inversión,
# comisiones, fecha y dólar de compra), los dos dólares, V y C de cada par y el gasto
# en dólares, con la MISMA cuenta que usa `armar_plan` (`dolares_del_pase`,
# `valor_del_par`, `costo_usd_de_lo_movido`, `gasto_en_usd`) y la versión del dólar
# que tiene la cuenta AHORA. Reescribe las dos patas de cada par con los mismos
# números, la FEE y la receta (`fx_version`, los dos dólares, V y C, que lee GET
# /traspasos). La llama `migrate_user_fx` después del rebuild y antes del recálculo,
# en la misma transacción: el recálculo lee las patas nuevas.
#
# LO QUE NO CAMBIA. El precio y V en pesos de un precio en pesos, C en la moneda de
# los lotes (`costo_nativo`), las cantidades y todo lo que mira el detector de
# desfase (que compara en la moneda de los lotes): sólo los números en dólares que
# dependen de la regla. Un pase de lotes en dólares con precio en dólares queda
# igual. El deshacer no usa V ni C (C.8): un pase revaluado se deshace igual.
#
# LA PATA DE UN LADO BORRADO. Se lee y se escribe por `TX_VIVAS`, como todo lector
# del registro: la pata del broker que se borró (pase incompleto) está en un lote
# revertido que nadie vuelve a leer (no hay puerta que des-revierta un lote), así que
# queda como estaba. La del lado vivo sí se revalúa: es la que cuenta en 'global'.

MOTIVO_RECETA_ILEGIBLE = "su receta no tiene el precio del pase"
MOTIVO_FILAS_NO_CUADRAN = "sus patas no coinciden con la receta"


def revaluar_patas(conn, uid: int, *, tc_blue: float) -> Dict[str, Any]:
    """C.10. Revalúa las patas de todos los pases no deshechos del usuario con la
    versión del dólar que tiene la cuenta ahora (`fx.fx_version`). `tc_blue`: el
    dólar de respaldo de la versión (en v2, el de una fecha que no está en la serie;
    la migración pasa el mismo con que rearma los lotes).

    No hace commit: corre adentro de la transacción de quien llama. Devuelve
    {"version", "revaluados": [ids], "sin_cambios": [ids], "salteados": [{id,
    motivo}]}. Un pase salteado (receta sin precio, o patas que no coinciden con la
    receta) NO se toca a medias: quien llama decide (la migración se revierte
    entera, ver `migrate_user_fx`)."""
    import fx
    version = fx.fx_version(conn, uid)
    hist = version == fx.FX_V2
    out: Dict[str, Any] = {"version": version, "revaluados": [], "sin_cambios": [],
                           "salteados": []}
    for reg in _registros(conn, uid):
        try:
            cambio = _revaluar_un_pase(conn, uid, reg, version=version, hist=hist,
                                       tc_blue=tc_blue)
        except _NoSeRevalua as ex:
            log.warning("traspaso_a_mano: no se revaluó el pase %s (user=%s): %s",
                        reg.id, uid, ex.motivo)
            out["salteados"].append({"id": reg.id, "motivo": ex.motivo})
            continue
        out["revaluados" if cambio else "sin_cambios"].append(reg.id)
    return out


class _NoSeRevalua(Exception):
    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def _filas_de_la_pata(conn, lote: str, traspaso_id: str, op: str) -> List[Any]:
    """Las filas `op` del pase en su lote, en el orden en que se escribieron, que es
    el de `Plan.pares()` (`store_preview_txs` las inserta en el orden de `Plan.filas`,
    y el `n.id` es el que usa el rebuild). Por `TX_VIVAS`: un lote revertido (broker
    borrado) no devuelve nada."""
    return conn.execute(
        f"SELECT n.id, n.quantity, n.valor_usd, n.valor_ars, n.costo_usd FROM {TX_VIVAS} "
        f"WHERE n.batch_id=? AND n.traspaso_id=? AND n.operation_type=? "
        f"ORDER BY n.id", (lote, traspaso_id, op)).fetchall()


def _distinto(a, b) -> bool:
    return abs(_num(a) - _num(b)) > 1e-9 * max(1.0, abs(_num(a)), abs(_num(b)))


def _revaluar_un_pase(conn, uid: int, reg: Registro, *, version: str, hist: bool,
                      tc_blue: float) -> bool:
    """Revalúa un pase. Devuelve si cambió algún número. Primero calcula y compara
    todo; recién después escribe (nada a medias)."""
    receta = reg.receta
    precio_r = receta.get("precio") or {}
    moneda_precio = str(precio_r.get("moneda") or "")
    if precio_r.get("unitario") is None or moneda_precio not in ("ARS", "USD"):
        raise _NoSeRevalua(MOTIVO_RECETA_ILEGIBLE)
    precio = _num(precio_r.get("unitario"))
    dol = dolares_del_pase(conn, reg.fecha, reg.moneda, moneda_precio, hist=hist,
                           tc_blue=tc_blue)

    # Los pares en el orden de la cola FIFO, como `Plan.pares()`. Todos los lotes de un
    # pase son de la moneda del pase (C.2: el plan sólo toma los de esa moneda).
    pares: List[Dict[str, Any]] = []
    idx: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for l in reg.lotes():
        k = (str(l.get("broker") or ""), str(l.get("broker_destino") or ""))
        if k not in idx:
            idx[k] = {"cantidad": 0.0, "c_usd": 0.0}
            pares.append(idx[k])
        take = _num(l.get("cantidad"))
        idx[k]["cantidad"] += take
        idx[k]["c_usd"] += costo_usd_de_lo_movido(
            conn, dict(l.get("foto") or {}), take, reg.moneda, precio=precio,
            moneda_precio=moneda_precio, dolares=dol, tc_blue=tc_blue, hist=hist,
            fecha=reg.fecha)
    if not pares:
        raise _NoSeRevalua(MOTIVO_RECETA_ILEGIBLE)
    for p in pares:
        p["v_nativo"], p["v_usd"], p["v_ars"] = valor_del_par(
            p["cantidad"], precio, moneda_precio, tc_pase=dol["tc_pase"],
            dolar_del_dia=dol["dolar_del_dia"])

    # Las filas a reescribir: las dos patas de cada par (en el lote de cada lado que
    # siga vivo) y la FEE del gasto. Tienen que coincidir con la receta, par por par.
    updates: List[Tuple[float, float, float, int]] = []
    for lote, op in ((reg.lote_salida, "TRASPASO_SALIDA"), (reg.lote_entrada, "TRASPASO_ENTRADA")):
        filas = _filas_de_la_pata(conn, lote, reg.id, op)
        if not filas:
            continue                  # ese lado se borró: su lote está revertido
        if len(filas) != len(pares) or any(abs(_num(f["quantity"]) - p["cantidad"]) > _TOL_CANT
                                           for f, p in zip(filas, pares)):
            raise _NoSeRevalua(MOTIVO_FILAS_NO_CUADRAN)
        for f, p in zip(filas, pares):
            if (_distinto(f["valor_usd"], p["v_usd"]) or _distinto(f["valor_ars"], p["v_ars"])
                    or _distinto(f["costo_usd"], p["c_usd"])):
                updates.append((p["v_usd"], p["v_ars"], p["c_usd"], f["id"]))
    gasto = receta.get("gasto") or None
    fees = _filas_de_la_pata(conn, reg.lote_salida, reg.id, "FEE")
    gasto_usd = None
    if fees:
        if not gasto or len(fees) != 1:
            raise _NoSeRevalua(MOTIVO_FILAS_NO_CUADRAN)
        gasto_usd = gasto_en_usd(_num(gasto.get("monto")),
                                 "USD" if str(gasto.get("moneda") or "").upper() == "USD" else "ARS",
                                 dol["tc_pesos"])
        if _distinto(fees[0]["valor_usd"], gasto_usd):
            conn.execute("UPDATE import_normalized_tx SET valor_usd=? WHERE id=?",
                         (gasto_usd, fees[0]["id"]))
    for v_usd, v_ars, c_usd, nid in updates:
        conn.execute("UPDATE import_normalized_tx SET valor_usd=?, valor_ars=?, costo_usd=? "
                     "WHERE id=?", (v_usd, v_ars, c_usd, nid))

    # La receta: la versión con que quedaron V y C, los dos dólares y los totales (los
    # que muestra GET /traspasos).
    nueva = dict(receta)
    nueva.update({
        "fx_version": version, "tc_venta": dol["tc_venta"], "tc_pase": dol["tc_pase"],
        "valor_nativo": sum(p["v_nativo"] for p in pares),
        "valor_usd": sum(p["v_usd"] for p in pares),
        "valor_ars": sum(p["v_ars"] for p in pares),
        "costo_usd": sum(p["c_usd"] for p in pares),
    })
    cambio_receta = any(
        (nueva[k] != receta.get(k)) if k == "fx_version" else _distinto(nueva[k], receta.get(k))
        for k in ("fx_version", "tc_venta", "tc_pase", "valor_nativo", "valor_usd",
                  "valor_ars", "costo_usd"))
    if cambio_receta:
        conn.execute("UPDATE traspasos_a_mano SET receta_json=? WHERE id=? AND user_id=?",
                     (json.dumps(nueva), reg.id, uid))
    return bool(updates) or cambio_receta or (
        gasto_usd is not None and _distinto(fees[0]["valor_usd"], gasto_usd))
