"""«Mover a otro broker»: el pase de títulos entre dos cuentas del mismo usuario.

QUÉ ES UN PASE. El usuario tiene los títulos en un broker (A) y los pasa a otro
suyo (B). No es una venta: los títulos siguen siendo suyos, con su costo y su
fecha de compra. Cada pase escribe dos lotes de import confirmados
(`parser_format = FORMATO`, uno por broker) y una fila en `traspasos_a_mano` que
los une y guarda la receta para deshacerlo (especificación, secciones A.1–A.7).

QUÉ HAY ACÁ HOY (etapas E3, E4 y E5).

  · E5, al final («Armar el pase»): cómo se arma un pase ANTES de escribirlo —
    las validaciones de la sección B.6, qué lotes se mueven, a qué pata de B va
    cada uno, cuánto valían ese día (V) y cuánto costaron (C), la comprobación
    contra el registro de lo importado y la firma—. `armar_plan` sólo LEE: lo usa
    la vista previa (`POST /api/positions/traspaso/vista-previa`) y lo va a usar
    el confirmar, que aplica las filas que el plan ya trae armadas.

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

El resto del módulo (aplicar el pase, deshacerlo, el antiduplicado, las
guardas) lo agregan las etapas siguientes.

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

MSG_APAGADO = "Esta opción no está disponible por ahora."
MSG_CARTERA_CAMBIO = ("Tu cartera cambió desde que armaste la vista previa. "
                      "Revisala de nuevo antes de confirmar.")
MSG_NO_SE_GUARDO = "No pudimos guardar el pase ({motivo}). No se cambió nada en tu cartera."

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
            p["v_nativo"] = p["cantidad"] * self.precio
            if self.moneda_precio == "ARS":
                p["v_usd"] = p["v_nativo"] / self.tc_pase if self.tc_pase else 0.0
                p["v_ars"] = p["v_nativo"]
            else:
                p["v_usd"] = p["v_nativo"]
                p["v_ars"] = p["v_usd"] * self.dolar_del_dia
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
    lotes de A ya no son los mismos."""
    datos = [[[l.lote_id, round(l.take, 9), l.entry_date, round(l.mov_inv, 9),
               round(l.mov_com, 9), l.pata_b] for l in lotes],
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


def _salida_posterior(conn, uid, patas, asset, fecha):
    """El último movimiento que sacó `asset` de esas patas DESPUÉS de `fecha`: una
    'Venta' de `operations` o una SELL viva del registro (las de un pase llevan
    `traspaso_id`). None si no hay. Devuelve {fecha, traspaso_id}."""
    mejor = None
    r = conn.execute(
        f"SELECT MAX(substr(date, 1, 10)) AS d FROM operations WHERE user_id=? "
        f"AND broker IN ({_ph(patas)}) AND asset=? AND op_type='Venta' "
        f"AND substr(date, 1, 10) > ?", (uid, *patas, asset, fecha)).fetchone()
    if r and r["d"]:
        mejor = {"fecha": r["d"], "traspaso_id": None}
    for s in conn.execute(
            f"""SELECT substr(n.date, 1, 10) AS d, n.traspaso_id AS tid FROM {TX_VIVAS}
                 WHERE b.user_id = ? AND n.broker IN ({_ph(patas)})
                   AND n.asset_symbol = ? AND n.operation_type = 'SELL'
                   AND substr(n.date, 1, 10) > ?
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
                # El precio que la persona cargó a mano. Para una cripto en una cuenta
                # en pesos es el spot en dólares: la valuación no le aplica el factor
                # del dólar cripto cuando hay precio cargado (`crypto_broker_factor`).
                moneda = "USD" if cripto_en_pesos else moneda_precio
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


# ── armar_plan ─────────────────────────────────────────────────────────────────

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
    from importing.tramo import costo_y_resultado_del_tramo
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

    # Los lotes de A de ese activo, en el orden FIFO del persister (`persister.py`).
    todos = [dict(r) for r in conn.execute(
        f"""SELECT * FROM positions
             WHERE user_id=? AND broker IN ({_ph(c.patas_a)}) AND asset=? AND is_cash=0
               AND quantity > 0
             ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
        (uid, *c.patas_a, asset)).fetchall()]
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
    # #16 — ventas posteriores en B (FIFO en B haría que se comieran los lotes movidos).
    post = _salida_posterior(conn, uid, c.patas_b, asset, fecha)
    if post:
        if post["traspaso_id"]:
            otro = _contraparte_de_pase(conn, uid, post["traspaso_id"])
            raise PaseInvalido(409, (
                f"El {_ddmmaaaa(post['fecha'])} ya pasaste {asset} de {B} a {otro}. Elegí una "
                f"fecha del {_ddmmaaaa(post['fecha'])} en adelante, o deshacé primero ese pase."))
        raise PaseInvalido(409, (
            f"Después del {_ddmmaaaa(fecha)} vendiste {asset} en {B}. Si lo pasamos con esa "
            f"fecha cambiarían esas ventas: elegí una fecha del {_ddmmaaaa(post['fecha'])} en "
            "adelante."))
    # #17 — no hay lotes que estuvieran ahí ese día.
    if not candidatos:
        salida = _salida_importada_cerca(conn, uid, c)
        if salida:
            raise PaseInvalido(400, (
                f"En {A} ya figura la salida de {asset} del {_ddmm(salida)} (vino en el archivo "
                f"de {A}). En Movimientos, filtrá por {A} y borrá la «Venta» de {asset} del "
                f"{_ddmm(salida)}. Después volvé y movelos desde acá: así llegan a {B} con lo "
                "que pagaste."))
        raise PaseInvalido(400, f"No tenés {asset} en {A} en {en_moneda} que estuvieran ahí el "
                                f"{_ddmmaaaa(fecha)}.")
    # #18 — más de lo que había.
    if cantidad > disponible + 1e-9:
        raise PaseInvalido(400, (
            f"En {A} tenés {_cant(disponible)} {asset} en {en_moneda} que estaban ahí el "
            f"{_ddmmaaaa(fecha)}. No podés pasar {_cant(cantidad)}."))

    # El prefijo FIFO hasta juntar la cantidad, partiendo el último (C.3).
    from fx import costo_del_lote
    lotes: List[LoteDelPlan] = []
    restante = cantidad
    for l in candidatos:
        if restante <= 1e-12:
            break
        # #19 — un lote sin fecha no se puede ubicar en la historia de A.
        if not str(l.get("entry_date") or "")[:10]:
            raise PaseInvalido(400, "Uno de los lotes que se moverían no tiene fecha de compra. "
                                    "Editalo, poné la fecha y volvé a intentar.")
        qty = float(l["quantity"] or 0)
        take = qty if restante >= qty - 1e-9 else restante
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
        avisos.append(f"Vamos a crear «{nombre}» para los lotes en dólares.")
    # #25 — pesos a una caja que no los acepta.
    no_aceptan = pipeline.brokers_que_no_aceptan_pesos(
        {b["name"]: b for b in c.brokers}, None)
    for l in lotes:
        if l.moneda == "ARS" and (l.pata_b in no_aceptan or l.pata_b in a_crear):
            raise PaseInvalido(400, f"{l.pata_b} no tiene caja en pesos, y estos {asset} se "
                                    "compraron en pesos.")

    # #26 — el precio de ese día (C.4).
    moneda_clave = "ARS" if (clave.endswith(".BA") or cripto_en_pesos) else "USD"
    precio, moneda_precio, fuente, fecha_precio, aviso_vela = _buscar_precio(
        conn, c, lotes, pedido, hoy=hoy, clave=clave, moneda_precio=moneda_clave,
        cripto_en_pesos=cripto_en_pesos, helpers=helpers)
    if aviso_vela:
        avisos.append(aviso_vela)

    # C.4.3 — dos dólares: el de C (por la moneda de los lotes, como el persister) y
    # el de V (por la moneda del precio).
    dolar_del_dia = fx.fx_for_date(conn, fecha, fallback=tc_blue) or tc_blue
    tc_pesos = dolar_del_dia if hist else tc_blue
    tc_venta = 1.0 if moneda == "USD" else tc_pesos
    if moneda_precio == "USD":
        tc_pase = 1.0
    elif moneda == "ARS":
        tc_pase = tc_venta
    else:
        tc_pase = dolar_del_dia

    # C.5 — C de cada lote, con la cuenta única del tramo (`importing/tramo.py`).
    for l in lotes:
        if moneda_precio == l.moneda:
            precio_en_su_moneda = precio
        elif moneda_precio == "ARS":
            precio_en_su_moneda = precio / tc_pase if tc_pase else 0.0
        else:
            precio_en_su_moneda = precio * dolar_del_dia
        t = costo_y_resultado_del_tramo(
            conn, lote={**l.lote, "currency": l.lote.get("currency") or l.moneda},
            take=l.take, currency=l.moneda, sell_currency=l.moneda,
            exit_price=precio_en_su_moneda, chunk_commission=0.0, tc_venta=tc_venta,
            tc_blue=tc_blue, hist=hist, op_date=fecha, transfer_out=False)
        l.c_usd = float(t["invested_usd"] or 0)

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
                avisos.append(f"Vamos a crear «{pata_gasto}» para el gasto en dólares.")
        monto = float(g_in.monto)
        caja = conn.execute(
            "SELECT COALESCE(SUM(invested), 0) AS c FROM positions "
            "WHERE user_id=? AND broker=? AND is_cash=1", (uid, pata_gasto)).fetchone()["c"]
        queda = float(caja or 0) - monto
        gasto = {"monto": monto, "moneda": g_moneda, "broker": pata_gasto,
                 "valor_usd": monto if g_moneda == "USD" else (monto / tc_pesos if tc_pesos else 0.0),
                 "caja_queda_negativa": queda < -0.005}
        if gasto["caja_queda_negativa"]:
            avisos.append(f"Con el gasto, la caja de {pata_gasto} queda en {_monto(queda, g_moneda)}.")

    # El precio cargado a mano en A viaja a B si B no tiene uno (C.7.8).
    override_a = next((l.lote["price_override"] for l in lotes
                       if l.lote.get("price_override") is not None), None)
    precio_en_destino = None
    if override_a is not None:
        hay_en_b = conn.execute(
            f"SELECT 1 FROM positions WHERE user_id=? AND broker IN ({_ph(c.patas_b)}) "
            f"AND asset=? AND is_cash=0 AND price_override IS NOT NULL LIMIT 1",
            (uid, *c.patas_b, asset)).fetchone()
        if not hay_en_b:
            precio_en_destino = {"brokers_destino": [B], "antes": None, "puesto": override_a}

    plan = Plan(cuentas=c, cantidad=cantidad, disponible=disponible, lotes=lotes,
                fx_version=hist_version, tc_blue=tc_blue, tc_venta=tc_venta, tc_pase=tc_pase,
                dolar_del_dia=dolar_del_dia, precio=precio, moneda_precio=moneda_precio,
                fuente=fuente, fecha_precio=fecha_precio, brokers_a_crear=a_crear, gasto=gasto,
                precio_cargado_en_destino=precio_en_destino, avisos=avisos)

    # Aviso: el precio lejísimos de lo que se pagó, comparando los dos en dólares.
    if plan.costo_usd > 0 and cantidad > 0:
        precio_usd = precio / tc_pase if moneda_precio == "ARS" and tc_pase else precio
        k = precio_usd / (plan.costo_usd / cantidad)
        if k < BANDA_DEL_PRECIO[0] or k > BANDA_DEL_PRECIO[1]:
            cola = (f"Revisá que esté en {_en_moneda(moneda_precio)}."
                    if fuente == "precio_a_mano"
                    else "Si no es correcto, escribí el precio a mano.")
            avisos.append(f"El precio de ese día está muy lejos de lo que pagaste (×{_veces(k)}). "
                          f"{cola}")

    plan.firma = firma_del_plan(lotes, fecha, moneda, B, gasto)
    return plan
