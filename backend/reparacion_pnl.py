"""El hermano de ESCRITURA de `diagnostico.py` — corrige la renta con la moneda ignorada.

`diagnostico.py` mide y no toca nada; ese contrato es lo que lo hace confiable.
Acá se escribe, y por eso vive aparte: si el mismo módulo midiera y escribiera,
el `_Fallas` que hoy garantiza que una sonda rota no se lea como "cuenta sana"
pasaría a ser el que decide si se escribe.

QUÉ CORRIGE — y sólo eso
────────────────────────
R4 (`R4_renta_moneda_ignorada`): `_persist_dividend_or_interest` convierte por
`brokers.currency` e ignora el `gross_amount_usd` que la fila importada ya trae
bien, así que un dividendo de ARS 1.055.645,75 entró a `operations.pnl_usd` como
si fueran 1.055.645,75 dólares. De ahí viaja a `monthly_entries.pnl_realized` y
a `capital_final`, que es el número que la persona ve.

NO corrige R1 ni R3, y no es un descuido:

  • R3 (per-100) parece el más fácil y es el más peligroso. El repo YA tiene un
    guard deployado que se niega a reconstruir exactamente estas cuentas
    (`importing/fx_migrate.py:249-276`) y le puso nombre: **el crimen perfecto**.
    El rebuild "arregla" la P&L, borra la firma `pnl_pct` que delata la cuenta,
    y deja el cash inflado ×100 en `snapshots.total_value`. Medido: 151 ventas
    per-100 acreditaron ARS 55.977.251.272 + USD 16.580.658 de caja fantasma.
    R3 es de dos pasos —cash primero, después P&L— y el orden lo fija ese guard.
  • R1 (conducto MEP) reescribe `import_normalized_tx`, que es la tabla FUENTE y
    NO tiene `undo_meta_json`. Necesita journal propio y ciclo propio, calcado
    de `/api/admin/fx-migrate-user`, que mueve las dos patas en una transacción.

EL SELECTOR DE REPARACIÓN ES MÁS ANGOSTO QUE EL DE DIAGNÓSTICO
──────────────────────────────────────────────────────────────
🔴 Y tiene que serlo. Dos subconjuntos que el diagnóstico cuenta y acá NO se
tocan, los dos medidos contra la copia de prod del 2026-08-16:

  1. MONEDA INFERIDA (`notes LIKE '%divisa=OTHER%'`): 27 filas de uid 870 que
     HOY ESTÁN BIEN. Son dólares con `currency` rotulada 'ARS' porque el parser
     ieb no supo la divisa y el normalizer cayó a ARS. Se confirma solo:
     reaparecen días después como acreditación en USD por el MISMO monto exacto
     (ARS 25,36 del 2025-07-10 ↔ USD 25,36 del 2025-07-14). "Corregirlas" las
     achica ~1.200× y borra US$424 de renta real.
  2. SELLO 1415 (`gross_amount / gross_amount_usd == 1415,00` exacto): 49 filas
     en cuentas `fx_version=v1`, donde TODOS los flujos están al mismo sello
     plano. Poner el P&L al MEP histórico dejando los flujos al 1415 es migrar
     UNA SOLA PATA del FX — el patrón que en este repo ya llevó un error de
     1,23× a 9,1×.

Lo excluido no desaparece: sale en `no_tocadas` con el motivo. Descartar en
silencio es lo único inaceptable.

CÓMO ESCRIBE
────────────
`pnl_usd` queda en USD y `currency` en 'USD'; `fx_to_usd` se deja en NULL a
propósito. `realized_pnl._NATIVE_CCY_OPS` es hoy `('Cupón','Amortización')`, así
que `realized_usd_sql` NO divide a `Dividendo`/`Interés` —que es el 100% de esta
familia: 90 y 22 filas—. Si mañana alguien agrega estos tipos a esa tupla (el
propio módulo lo discute para `Interés PF`), una fila que hubiéramos dejado en
ARS con `fx_to_usd` sellado se dividiría DOS veces. Con `currency='USD'` la
condición `currency = 'ARS'` no matchea nunca y la fila queda a salvo del cambio.

REVERSIBLE. El valor viejo va a `operations.undo_meta_json` bajo
`pnl_escala_reparada`, MERGEADO con lo que hubiera — esa columna guarda el CAMINO
de creación (`src`) y la cascada de borrado lo lee: pisarla rompe el borrado.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, List

log = logging.getLogger(__name__)

# El TC plano con el que el 52% de las filas ARS quedó estampado.
SELLO_TC = 1415.0
SELLO_TOL = 0.01

# Marca del normalizer cuando el parser no supo la divisa y cayó a ARS.
MARCA_MONEDA_INFERIDA = '%DIVISA=OTHER%'

_VIVO = "b.status = 'confirmed' AND n.excluded_at IS NULL"

# El corazón del selector, compartido por `candidatos` y `no_tocadas` para que
# no puedan divergir: la diferencia entre los dos es SÓLO el filtro de exclusión.
_BASE = f"""
      FROM operations o
      JOIN import_op_links l ON l.operation_id = o.id
      JOIN import_normalized_tx n ON n.raw_row_id = l.raw_row_id
                                 AND l.batch_id = n.batch_id
      JOIN import_batches b ON b.id = n.batch_id
     WHERE o.user_id = ? AND {_VIVO}
       AND n.currency = 'ARS'
       AND ABS(COALESCE(o.pnl_usd,0) - COALESCE(n.gross_amount,0)) < 0.01
       AND ABS(COALESCE(n.gross_amount,0) - COALESCE(n.gross_amount_usd,0)) > 1
"""

# Las dos exclusiones, como expresión SQL reutilizable.
_ES_MONEDA_INFERIDA = f"UPPER(COALESCE(n.notes,'')) LIKE '{MARCA_MONEDA_INFERIDA}'"
_ES_SELLO = (f"ABS(COALESCE(n.gross_amount,0) / NULLIF(n.gross_amount_usd,0) - {SELLO_TC})"
             f" < {SELLO_TOL}")


def candidatos(conn, uid: int) -> List[Dict[str, Any]]:
    """Las filas que se pueden reparar. FUNCIÓN PURA: sólo SELECT.

    La selección ES la parte peligrosa de un repair, así que se testea sola,
    antes de que exista un solo UPDATE.
    """
    filas = conn.execute(f"""
        SELECT o.id op_id, o.date, o.op_type, o.pnl_usd pnl_actual,
               o.currency ccy_actual, o.undo_meta_json,
               n.gross_amount ars, n.gross_amount_usd usd,
               n.asset_symbol, o.broker
        {_BASE}
           AND NOT ({_ES_MONEDA_INFERIDA})
           AND NOT ({_ES_SELLO})
         ORDER BY o.date, o.id""", (uid,)).fetchall()
    return [{
        "op_id": r["op_id"], "date": r["date"], "op_type": r["op_type"],
        "broker": r["broker"], "activo": r["asset_symbol"],
        "pnl_actual": round(float(r["pnl_actual"] or 0), 2),
        "pnl_correcto": round(float(r["usd"] or 0), 2),
        "monto_ars": round(float(r["ars"] or 0), 2),
        "tc_implicito": (round(float(r["ars"]) / float(r["usd"]), 2)
                         if r["usd"] else None),
        "_undo": r["undo_meta_json"], "_ccy": r["ccy_actual"],
    } for r in filas]


def no_tocadas(conn, uid: int) -> List[Dict[str, Any]]:
    """Lo que el DIAGNÓSTICO cuenta y la REPARACIÓN no toca, con el motivo.

    Sin esto el repair diría "reparé todo" mientras deja filas de la misma
    familia sin tocar, y el que lo corre no tendría cómo enterarse.
    """
    filas = conn.execute(f"""
        SELECT o.id op_id, o.date, o.pnl_usd pnl_actual,
               n.gross_amount ars, n.gross_amount_usd usd, n.notes,
               ({_ES_MONEDA_INFERIDA}) inferida, ({_ES_SELLO}) sello
        {_BASE}
           AND (({_ES_MONEDA_INFERIDA}) OR ({_ES_SELLO}))
         ORDER BY o.date, o.id""", (uid,)).fetchall()
    out = []
    for r in filas:
        if r["inferida"]:
            motivo = ("moneda_inferida: el parser no supo la divisa (divisa=OTHER) "
                      "y el normalizer cayó a ARS. La fila HOY ESTÁ BIEN — son "
                      "dólares. Corregirla la achicaría ~1.200×.")
        else:
            motivo = (f"sello_{SELLO_TC:.0f}: el TC está estampado plano. La cuenta "
                      "es fx v1 y TODOS sus flujos tienen el mismo sello; mover "
                      "sólo el P&L al MEP histórico migra una sola pata del FX.")
        out.append({
            "op_id": r["op_id"], "date": r["date"],
            "pnl_actual": round(float(r["pnl_actual"] or 0), 2),
            "motivo": motivo,
        })
    return out


def medir(conn, uid: int) -> Dict[str, Any]:
    """Las tres cifras del antes/después. FUNCIÓN PURA.

    🔴 LEE POR UN CAMINO DISTINTO AL DEL SELECTOR, y eso es el punto. El daño
    DECLARADO sale de `diagnostico` (operations + import_normalized_tx); el
    delta MEDIDO sale de acá (monthly_entries + snapshots), con la cadena de
    recomputo en el medio. Si las dos cifras salieran del mismo código, el
    criterio de éxito se estaría verificando contra sí mismo y cerraría siempre.
    """
    pico = conn.execute(
        "SELECT COALESCE(MAX(ABS(capital_final)),0) m FROM monthly_entries "
        "WHERE user_id=? AND broker='global'", (uid,)).fetchone()["m"]
    # 🔴 LA IDENTIDAD SE CHEQUEA CONTRA ESTA SUMA, NO CONTRA EL PICO.
    # `pico` es un MAX sobre meses: sacarle plata a unos meses NO baja el máximo
    # en esa misma cantidad si el máximo se muda a otro mes. Medido en uid 54:
    # el selector esperaba un delta de 5.737.497,01 y el pico se movió
    # 5.736.345,48 — 1.151,53 de diferencia que no era ningún error, era la
    # comparación mal planteada. `pnl_realized` sí es aditivo:
    # SUM(pnl_realized) == SUM(operations.pnl_usd), así que su delta tiene que
    # dar EXACTO. El pico queda como cifra de titular (es lo que ve la persona),
    # no como test.
    suma = conn.execute(
        "SELECT COALESCE(SUM(pnl_realized),0) s FROM monthly_entries "
        "WHERE user_id=? AND broker='global'", (uid,)).fetchone()["s"]
    snap = conn.execute(
        "SELECT COALESCE(MAX(ABS(total_value)),0) m FROM snapshots "
        "WHERE user_id=?", (uid,)).fetchone()["m"]
    ult = conn.execute(
        "SELECT total_value tv, date FROM snapshots WHERE user_id=? "
        "ORDER BY date DESC LIMIT 1", (uid,)).fetchone()
    return {
        "pico_capital_final": round(float(pico), 2),
        "suma_pnl_realized": round(float(suma), 2),
        "snapshot_max_abs": round(float(snap), 2),
        "cartera_ultimo_snapshot": round(float(ult["tv"]), 2) if ult else None,
        "fecha_ultimo_snapshot": ult["date"] if ult else None,
    }


def snapshots_derivados(conn, uid: int) -> List[Dict[str, Any]]:
    """Los snapshots que el repair INVALIDA, por PROCEDENCIA y no por valor.

    Un snapshot con `source='import'` lo escribió `_backfill_snapshots_from_monthly`
    copiando `capital_final`: es un DERIVADO, y si el repair cambia su fuente
    queda mintiendo. Ésos hay que refrescarlos.

    Todo lo demás es una MEDICIÓN (el cron nocturno la tomó a mercado) y el
    repair no la invalida — puede estar mal por su cuenta, pero por otra causa.
    Pisarla con `capital_final` sería reemplazar un valor a mercado por uno al
    costo, que es exactamente el "diente hacia abajo" que
    `persister._backfill_snapshots_from_monthly:1274-1287` documenta como
    destructivo e irrecuperable.

    ⚠️ Medido contra prod: de 40.717 snapshots, sólo 475 tienen `source='import'`.
    uid 54 —el caso piloto— tiene CERO: sus 49 snapshots son mediciones con
    `source` NULL. O sea que para esa cuenta el repair no invalida ninguno, y el
    residuo se reporta en vez de arreglarse (ver `snapshots_sucios`).
    """
    return [dict(r) for r in conn.execute(
        """SELECT date, total_value, source FROM snapshots
            WHERE user_id=? AND source='import' ORDER BY date""", (uid,)).fetchall()]


def snapshots_sucios(conn, uid: int, umbral: float) -> Dict[str, Any]:
    """Los snapshots que quedan inconsistentes y que el repair NO puede arreglar.

    Son registros CONGELADOS de un estado pasado que de verdad incluía el
    fantasma (en uid 54 el `total_value` salta de 7.795,82 el 2026-01-31 a
    1.063.234,61 el 2026-02-28, que es la renta de ARS 1.055.645,75 del 27/02).
    No son recomputables: la app no guarda precios históricos, así que no hay
    forma de saber cuánto valía de verdad la cartera ese día.

    Se REPORTAN. Un repair que arregla `capital_final` y calla que el gráfico de
    Evolución sigue mostrando el pico es cirugía con el paciente viéndose igual
    de enfermo.
    """
    filas = conn.execute(
        """SELECT date, total_value FROM snapshots
            WHERE user_id=? AND ABS(COALESCE(total_value,0)) > ?
            ORDER BY date""", (uid, umbral)).fetchall()
    return {
        "cantidad": len(filas),
        "umbral_usd": round(umbral, 2),
        "desde": filas[0]["date"] if filas else None,
        "hasta": filas[-1]["date"] if filas else None,
        "max_abs": round(max((abs(float(f["total_value"] or 0)) for f in filas),
                             default=0.0), 2),
        "muestra": [{"date": f["date"],
                     "total_value": round(float(f["total_value"] or 0), 2)}
                    for f in filas[:10]],
        "por_que_no_se_arreglan": (
            "son mediciones congeladas de un estado que de verdad incluía el "
            "monto inflado; la app no guarda precios históricos, así que el "
            "valor real de esa fecha no es recomputable. Se reportan para que el "
            "veredicto no diga 'reparado' mientras el gráfico sigue mostrando el "
            "pico."),
    }


def aplicar(conn, uid: int, cands: List[Dict[str, Any]], *,
            fecha: str, batch_ref: str = None) -> int:
    """Escribe las correcciones sobre `operations`. Devuelve cuántas filas movió.

    Sólo toca `operations`. La cadena de recomputo (`_recalc_pnl_realized_from_ops`
    y los snapshots) la corre el endpoint, DESPUÉS y fuera de este módulo, para
    que acá no haya que importar `main` y los selectores se puedan testear solos.

    El WHERE lleva un LOCK OPTIMISTA sobre el valor viejo: si alguien tocó la
    fila entre el ensayo y el apply, el UPDATE no matchea y la fila no se mueve
    en vez de pisar un valor que ya no es el que medimos.
    """
    hechas = 0
    for c in cands:
        try:
            meta = json.loads(c["_undo"]) if c["_undo"] else {}
            if not isinstance(meta, dict):
                meta = {}
        except (ValueError, TypeError):
            meta = {}
        meta["pnl_escala_reparada"] = {
            "antes": c["pnl_actual"],
            "despues": c["pnl_correcto"],
            "currency_antes": c["_ccy"],
            "monto_ars": c["monto_ars"],
            "tc_implicito": c["tc_implicito"],
            "fecha": fecha,
            "batch_ref": batch_ref,
            "via": "import_normalized_tx.gross_amount_usd",
        }
        cur = conn.execute(
            """UPDATE operations
                  SET pnl_usd = ?, currency = 'USD', undo_meta_json = ?
                WHERE id = ? AND user_id = ?
                  AND ABS(COALESCE(pnl_usd,0) - ?) < 0.01""",
            (c["pnl_correcto"], json.dumps(meta, ensure_ascii=False),
             c["op_id"], uid, c["pnl_actual"]))
        hechas += cur.rowcount
    return hechas


def revertir(conn, uid: int, batch_ref: str) -> int:
    """Deshace una corrida entera leyendo `undo_meta_json`. Devuelve cuántas volvió.

    La reversibilidad fue el principio que sostuvo todo lo demás en este
    proyecto, así que el repair no se considera terminado sin esto.
    """
    filas = conn.execute(
        """SELECT id, pnl_usd, undo_meta_json FROM operations
            WHERE user_id=? AND undo_meta_json IS NOT NULL
              AND undo_meta_json LIKE '%pnl_escala_reparada%'""", (uid,)).fetchall()
    vueltas = 0
    for r in filas:
        try:
            meta = json.loads(r["undo_meta_json"]) or {}
        except (ValueError, TypeError):
            continue
        m = meta.get("pnl_escala_reparada")
        if not isinstance(m, dict) or (batch_ref and m.get("batch_ref") != batch_ref):
            continue
        meta.pop("pnl_escala_reparada", None)
        cur = conn.execute(
            """UPDATE operations SET pnl_usd=?, currency=?, undo_meta_json=?
                WHERE id=? AND user_id=?""",
            (m.get("antes"), m.get("currency_antes"),
             json.dumps(meta, ensure_ascii=False) if meta else None,
             r["id"], uid))
        vueltas += cur.rowcount
    return vueltas
