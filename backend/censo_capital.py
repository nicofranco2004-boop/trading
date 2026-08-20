"""Quiénes tienen el número roto HOY — el censo que mira el resultado, no el import.

Hermano de `censo_flujos.py` y complementario a propósito. Aquél mide el
ANDAMIO (import_normalized_tx: qué entró y cómo se clasificó); éste mide el
RESULTADO (monthly_entries / positions / snapshots: qué número está viendo el
usuario). La diferencia no es académica: en la corrida del 2026-08-20, de los
45 usuarios con el capital más roto de la base, **27 eran invisibles para el
censo de imports** — su corrupción no vive en ninguna fila normalizada grande,
sino en un `pnl_realized` o un `positions.invested` que se inflaron después.
El caso extremo es un usuario con 1e17 en `invested` y CERO filas de import
por encima de un millón.

READ-ONLY. Ni un INSERT, ni un UPDATE.

Las señales
───────────
C1  CAPITAL DECLARADO ≫ CARTERA REAL. El `capital_final` de `monthly_entries`
    (broker='global') contra el `total_value` del último snapshot. Es la señal
    más directa de "este usuario ve un número que no es el suyo": con capital
    declarado de US$1,7bn y una cartera de US$18k, el rendimiento sale
    −99,999%. Se mide como RATIO, no como diferencia — la diferencia sola
    ordena por tamaño de cuenta, el ratio ordena por gravedad.

C2  PNL_REALIZED IMPOSIBLE. Una ganancia/pérdida realizada global que ninguna
    cuenta real puede tener. Es la familia que el censo de imports no ve.

C3  INVESTED IMPOSIBLE en `positions`. El costo de una tenencia viva. Idem: se
    infla por precio mal escalado y no deja fila grande en el import.

C4  SNAPSHOTS NEGATIVOS. Un `total_value` o `net_deposited` negativo es
    imposible por construcción; cuando aparece, suele venir en rachas y a
    veces se "cancela" después con una ganancia falsa del mismo tamaño — que
    es peor, porque tapa la señal.

ATRIBUCIÓN. Para cada usuario de C1 se cruza cuánto de su capital declarado se
explica por el SEED SINTÉTICO (las filas que Rendi fabrica al importar una
foto o un CSV parcial). Ese cruce es el que dice si el arreglo es "re-derivar
la moneda del seed" o si hay que buscar en otro lado. En la corrida real, sólo
18 de 45 se explicaban por el seed.

⚠️ Trampa de SQL que este módulo evita a propósito: hay ~7.300 filas vivas de
DEPOSIT/WITHDRAW con `notes IS NULL`. Un `NOT (notes LIKE ...)` las hace
desaparecer (NULL no es TRUE) y subestima lo "real" en ~15%. Siempre
`CASE WHEN (cond) THEN 'sintetico' ELSE 'real' END`.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# 🔴 REGLA DURA DE ESTE MÓDULO: **un umbral de plata SIEMPRE va por moneda.**
# Esta lección costó tres veces en la misma sesión (la v1 de censo_flujos sumó
# ARS+USD; la v2 lo arregló ahí; y la v1 de ESTE módulo volvió a caer con
# `positions.invested`). Un millón de pesos son ~US$700: con un umbral único de
# 1e6 salían "350 usuarios con costo imposible" cuando 349 eran cuentas
# normales en pesos y la señal real eran 3 filas.
UMBRAL_IMPOSIBLE = {"USD": 1_000_000.0, "USDT": 1_000_000.0,
                    "ARS": 1_000_000_000.0}   # ~US$700k al blue
UMBRAL_DEFAULT = 1_000_000.0

# Un precio unitario por encima de esto no existe en ningún mercado que la app
# soporte (el caso real: buy_price 3,66e14 para SPY). Va aparte de `invested`
# porque la corrupción de precio deja el costo CHICO —a veces negativo— y por
# `invested` sola es invisible.
PRECIO_IMPOSIBLE = 1_000_000_000.0

# monthly_entries y snapshots están SIEMPRE en USD (el cron y el persister
# convierten al escribir), así que acá el umbral único sí es correcto.
RATIO_SOSPECHOSO = 10.0        # capital declarado / cartera real
RATIO_GRAVE = 100.0
CAPITAL_MINIMO = 1_000_000.0   # por debajo de esto un ratio alto es una cuenta chica
PNL_IMPOSIBLE = 1_000_000.0

# Piso para "negativo de verdad": por debajo de cero hay una cola larga de
# centavos de redondeo (247 usuarios contra 88 si se exige −100).
NEGATIVO_REAL = -100.0

TOPE_DETALLE = 60

# El discriminador de seed que usa el repo (main.py `_is_synthetic_seed_row`):
# se ancla al PREFIJO de la nota, no a la palabra "sintético" — hay variantes
# ('Tenencia — apertura', 'Tenencia — ajuste a foto') que no la llevan y que
# son la contrapartida contable del mismo mecanismo.
SEED_SQL = "(n.notes LIKE 'Estado inicial%' OR n.notes LIKE 'Tenencia —%')"


# Subquery: el último snapshot de cada usuario — su cartera de verdad, hoy.
_ULTIMA_CARTERA = """SELECT s.user_id AS uid, s.total_value AS tv, s.date AS d
                       FROM snapshots s
                      WHERE s.date = (SELECT MAX(x.date) FROM snapshots x
                                       WHERE x.user_id = s.user_id)"""


def c1_capital_vs_cartera(conn, uid: Optional[int] = None) -> Dict[str, Any]:
    """Capital declarado contra la cartera que el usuario tiene de verdad."""
    p: List[Any] = [CAPITAL_MINIMO, RATIO_SOSPECHOSO]
    filtro = "AND mx.uid = ?" if uid is not None else ""
    if uid is not None:
        p.append(int(uid))
    sql = f"""
        WITH mx AS (SELECT user_id uid, MAX(ABS(capital_final)) cap
                      FROM monthly_entries WHERE broker='global' GROUP BY 1),
             last AS ({_ULTIMA_CARTERA}),
             seed AS (SELECT b.user_id uid,
                             SUM(COALESCE(n.gross_amount_usd,0)) s
                        FROM import_normalized_tx n
                        JOIN import_batches b ON b.id = n.batch_id
                       WHERE b.status='confirmed' AND n.excluded_at IS NULL
                         AND n.operation_type='DEPOSIT' AND {SEED_SQL}
                       GROUP BY 1)
        SELECT mx.uid, mx.cap, last.tv, last.d, COALESCE(seed.s, 0) seed_usd
          FROM mx JOIN last ON last.uid = mx.uid
          LEFT JOIN seed ON seed.uid = mx.uid
         WHERE mx.cap > ? AND last.tv > 0 AND mx.cap / last.tv > ? {filtro}
         ORDER BY mx.cap / last.tv DESC"""
    filas = conn.execute(sql, p).fetchall()

    det, expl, no_expl, graves = [], 0, 0, 0
    for r in filas:
        ratio = r["cap"] / r["tv"]
        # ¿El seed explica el capital declarado? Con que cubra la mitad alcanza
        # para decir "el arreglo pasa por re-derivar la moneda del seed".
        explica = r["seed_usd"] > 0 and (r["seed_usd"] / r["cap"]) > 0.5
        expl += 1 if explica else 0
        no_expl += 0 if explica else 1
        graves += 1 if ratio > RATIO_GRAVE else 0
        if len(det) < TOPE_DETALLE:
            det.append({
                "user_id": r["uid"],
                "capital_declarado": round(float(r["cap"]), 2),
                "cartera_real": round(float(r["tv"]), 2),
                "ratio": round(ratio, 1),
                "seed_usd": round(float(r["seed_usd"]), 2),
                "causa": "seed_sintetico" if explica else "OTRA_COSA",
                "ultimo_snapshot": r["d"],
            })
    return {
        "usuarios": len(filas),
        "graves_ratio_100x": graves,
        "explicados_por_seed": expl,
        "NO_explicados_por_seed": no_expl,
        "detalle": det,
    }


def _simple(conn, sql: str, params: List[Any]) -> Dict[str, Any]:
    filas = conn.execute(sql, params).fetchall()
    return {
        "usuarios": len({r["uid"] for r in filas}),
        "filas": len(filas),
        "detalle": [dict(r) for r in filas[:TOPE_DETALLE]],
    }


def c2_pnl_imposible(conn, uid: Optional[int] = None) -> Dict[str, Any]:
    # OJO con el orden: el filtro por usuario va en el WHERE (antes del
    # GROUP BY) y el umbral en el HAVING (después), así que el uid va PRIMERO
    # en la lista de params. Invertirlos no da error de SQL: da un resultado
    # silenciosamente equivocado.
    p: List[Any] = []
    f = ""
    if uid is not None:
        f = "AND user_id = ?"
        p.append(int(uid))
    p.append(PNL_IMPOSIBLE)
    return _simple(conn, f"""
        SELECT user_id uid, MAX(ABS(pnl_realized)) peor, COUNT(*) meses
          FROM monthly_entries WHERE broker='global' {f}
         GROUP BY 1 HAVING MAX(ABS(pnl_realized)) > ?
         ORDER BY 2 DESC""", p)


def c3_posicion_imposible(conn, uid: Optional[int] = None) -> Dict[str, Any]:
    """Costo o precio de una tenencia que no puede existir.

    Tres cosas que la v1 hacía mal y que juntas escondían el peor caso de la
    base: (a) umbral único para todas las monedas; (b) excluía `is_cash`, y el
    1e17 de uid 160 vive justo ahí; (c) miraba sólo `invested`, y la corrupción
    de PRECIO deja el costo chico —a veces negativo— con un `buy_price` de
    3,66e14 al lado.
    """
    caso_ccy = " ".join(
        f"WHEN COALESCE(NULLIF(currency,''),'?')='{k}' THEN {v}"
        for k, v in UMBRAL_IMPOSIBLE.items())
    p: List[Any] = [PRECIO_IMPOSIBLE]
    f = ""
    if uid is not None:
        f = "AND user_id = ?"
        p.append(int(uid))
    return _simple(conn, f"""
        SELECT user_id uid, broker, asset, currency, is_cash,
               ROUND(invested,2) invested, buy_price,
               CASE WHEN ABS(COALESCE(buy_price,0)) > ? THEN 'precio' ELSE 'costo' END señal
          FROM positions
         WHERE (ABS(COALESCE(invested,0)) > (CASE {caso_ccy} ELSE {UMBRAL_DEFAULT} END)
                OR ABS(COALESCE(buy_price,0)) > {PRECIO_IMPOSIBLE}) {f}
         ORDER BY MAX(ABS(COALESCE(invested,0)), ABS(COALESCE(buy_price,0))) DESC""", p)


def c4_snapshots_negativos(conn, uid: Optional[int] = None) -> Dict[str, Any]:
    """Valor o capital aportado negativo — imposible por construcción.

    Se exige NEGATIVO_REAL y no simplemente <0: hay una cola larga de centavos
    de redondeo (247 usuarios contra 88 exigiendo −100) que ahogaría la señal.
    """
    p: List[Any] = [NEGATIVO_REAL, NEGATIVO_REAL]
    f = ""
    if uid is not None:
        f = "AND user_id = ?"
        p.append(int(uid))
    return _simple(conn, f"""
        SELECT user_id uid, COUNT(*) ruedas,
               ROUND(MIN(total_value),2) peor_valor,
               ROUND(MIN(net_deposited),2) peor_aportado,
               MIN(date) desde, MAX(date) hasta
          FROM snapshots
         WHERE (total_value < ? OR net_deposited < ?) {f}
         GROUP BY 1 ORDER BY 2 DESC""", p)


def contar(conn, uid: Optional[int] = None) -> Dict[str, Any]:
    """El censo de capital. `uid=None` = toda la base. NO ESCRIBE NADA."""
    total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] or 1
    c1 = c1_capital_vs_cartera(conn, uid)
    c2 = c2_pnl_imposible(conn, uid)
    c3 = c3_posicion_imposible(conn, uid)
    c4 = c4_snapshots_negativos(conn, uid)

    afectados = set()
    for d in c1["detalle"]:
        afectados.add(d["user_id"])
    for grupo in (c2, c3, c4):
        for d in grupo["detalle"]:
            afectados.add(d["uid"])

    out = {
        "universo": {"usuarios_en_la_base": total},
        "c1_capital_vs_cartera": c1,
        "c2_pnl_imposible": c2,
        "c3_posicion_imposible": c3,
        "c4_snapshots_negativos": c4,
        "blast_radius": {
            "usuarios": len(afectados),
            "pct_del_padron": round(100.0 * len(afectados) / max(total, 1), 1),
            # ⚠️ Piso, no total: el detalle de cada señal está capeado en
            # TOPE_DETALLE, así que la unión puede quedar corta si alguna
            # señal desborda. Nunca reportar esto como "son exactamente N".
            "caveat": (f"unión de los detalles (cap {TOPE_DETALLE} por señal) — "
                       f"es un PISO, no un total exacto"),
        },
    }
    out["lectura"] = _lectura(out)
    return out


def _lectura(o: Dict[str, Any]) -> str:
    c1 = o["c1_capital_vs_cartera"]
    partes = [
        f"{c1['usuarios']} usuarios con el capital declarado >{RATIO_SOSPECHOSO:.0f}× "
        f"su cartera real ({c1['graves_ratio_100x']} por encima de "
        f"{RATIO_GRAVE:.0f}×). Esos ven hoy un rendimiento que no es el suyo.",
        f"ATRIBUCIÓN: {c1['explicados_por_seed']} se explican por el seed "
        f"sintético mal-monedeado; {c1['NO_explicados_por_seed']} NO — y ésos "
        f"son invisibles para el censo de imports.",
        f"Blast radius (piso): {o['blast_radius']['usuarios']} usuarios = "
        f"{o['blast_radius']['pct_del_padron']}% del padrón.",
    ]
    if c1["NO_explicados_por_seed"] > c1["explicados_por_seed"]:
        partes.append("→ La causa dominante NO es el seed. Arreglar sólo el "
                      "seed deja afuera a la mayoría.")
    return " ".join(partes)
