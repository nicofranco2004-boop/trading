"""Qué tenía esta persona a la FECHA DE LA FOTO, para poder reconciliar antes de confirmar.

`compute_reconcile` compara la foto contra el estado de HOY. Eso vale sólo si la
foto ES de hoy. Si los movimientos del import llegan más allá de su fecha, toda
compra posterior aparece como "Rendi tiene de más" y toda venta posterior como un
falso "coincide". Este módulo produce el otro lado de la comparación: la tenencia
a la fecha D, contando además lo que el preview agregaría.

🔴 ANCLA EN `positions`, NO EN UN REPLAY DEL LEDGER — Y ESA ES LA DECISIÓN
   IMPORTANTE DEL MÓDULO.

   Existe `ledger_replay.tenencia_en(uid, fecha)`, que replaya `import_normalized_tx`
   hacia adelante. Usarla acá tendría un costo que este repo ya pagó: sería un
   SEGUNDO MOTOR DE TENENCIA. Cuando el resultado y la foto no coincidieran, no
   habría forma de saber si el import está mal o si el segundo motor está mal. Es
   exactamente lo que pasó con `valor_en`, que terminó siendo un segundo motor de
   valuación y hubo que enderezarlo para que delegara en el canónico —su propio
   docstring lo cuenta: "tener un segundo motor de valuación es como se vuelve a
   los ~15 motores de retorno que este trabajo viene a cerrar".

   Anclando en `positions` se compara LO QUE EL USUARIO EFECTIVAMENTE VE, rodado
   hacia atrás, contra lo que el broker dijo. Una sola cadena, un solo motor.

   Efecto secundario que importa: la reproducibilidad del replay contra
   `positions` (37,4% base-wide, 41,2% en cuentas de un solo import) deja de ser
   relevante. Ese número mide la distancia entre una suma ingenua de BUY−SELL y
   un FIFO completo —con cancelación de conductos, spill cross-currency, sweeps,
   splits y lotes semilla—, no corrupción de datos. Con el ancla correcta esa
   distancia no se mide y no bloquea a nadie.

LO QUE NO SE PUEDE RODAR HACIA ATRÁS
────────────────────────────────────
No todo movimiento deja rastro reversible. Lo que no se puede deshacer con
confianza NO se adivina: sale en `no_reconciliable` con su motivo, y el override
no lo toca. Los motivos están medidos contra la copia de prod del 2026-08-16:

  · `datos_manuales`        — alta/venta/edición desde la UI: no hay fila en el
                              ledger que restar. 1.082 de 31.433 lotes vivos.
  · `vencimiento_en_ventana`— `sweep_matured_letras` BORRÓ la posición entre D y
                              hoy; `positions` ya no tiene el nominal que había.
  · `split_en_ventana`      — el ajuste multiplicó la cantidad sin dejar
                              movimiento, y el watermark es un piso, no el total.

Lo que SÍ se corrige, porque la función que lo produjo acepta fecha:

  · amortización de bonos — `positions.quantity` de hoy es
    `nominal × residual_factor(HOY)`; a la fecha D era `nominal ×
    residual_factor(D)`. Se re-escala por el cociente.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Motivos por los que un activo NO se puede proyectar con confianza. Enum cerrado:
# un motivo nuevo se agrega acá y no como string suelto en el sitio de uso.
MOTIVO_MANUAL = "datos_manuales"
MOTIVO_VENCIMIENTO = "vencimiento_en_ventana"
MOTIVO_SPLIT = "split_en_ventana"


def _norm(s) -> str:
    return (s or "").strip().upper()


def proyectar(conn, uid: int, *, pair: List[str], fecha: str,
              session_id: str = None, hoy: str = None) -> Tuple[Dict[str, float], List[dict]]:
    """`({activo: cantidad}, [no_reconciliable])` a la fecha `fecha`.

    `pair` son los brokers del par padre↔'· USD' (ver `persister.broker_pair`):
    el mismo activo comprado en una moneda y vendido en la otra queda partido
    entre los dos, así que la tenencia se mide sobre el par y no sobre un broker.

    `session_id` suma además las filas de un batch en preview — es la parte de
    "qué quedaría si confirmo esto".
    """
    from datetime import datetime, timedelta
    from pricing.bond_amortization import residual_factor
    from .maturity import letra_maturity

    D = str(fecha)[:10]
    HOY = hoy or (datetime.utcnow() - timedelta(hours=3)).date().isoformat()
    ph = ",".join("?" * len(pair))

    # ── 1. El ancla: lo que el usuario ve HOY, por el par de brokers ─────────
    qty: Dict[str, float] = {}
    for r in conn.execute(
            f"SELECT asset, SUM(quantity) q FROM positions "
            f"WHERE user_id=? AND COALESCE(is_cash,0)=0 AND broker IN ({ph}) "
            f"GROUP BY asset", (uid, *pair)):
        qty[_norm(r["asset"])] = qty.get(_norm(r["asset"]), 0.0) + float(r["q"] or 0)

    dudosos: Dict[str, str] = {}

    # ── 2. Deshacer los movimientos POSTERIORES a D ──────────────────────────
    # Una compra posterior a la foto no estaba ahí: se resta. Una venta
    # posterior sí estaba: se suma. Es la única forma de que una operación hecha
    # después del corte no aparezca como discrepancia contra el broker.
    for r in conn.execute(
            f"""SELECT n.asset_symbol a, n.operation_type op, n.quantity q
                  FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id
                 WHERE b.user_id=? AND n.excluded_at IS NULL
                   AND b.status='confirmed' AND n.broker IN ({ph})
                   AND n.date > ? AND n.asset_symbol IS NOT NULL
                   AND n.operation_type IN ('BUY','SELL')""", (uid, *pair, D)):
        v = float(r["q"] or 0)
        if v <= 0:
            continue
        a = _norm(r["a"])
        qty[a] = qty.get(a, 0.0) - (v if r["op"] == "BUY" else -v)

    # ── 3. Sumar lo que el PREVIEW agregaría hasta D ─────────────────────────
    if session_id:
        for r in conn.execute(
                """SELECT n.asset_symbol a, n.operation_type op, n.quantity q
                     FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id
                    WHERE b.user_id=? AND b.id=? AND n.excluded_at IS NULL
                      AND n.date <= ? AND n.asset_symbol IS NOT NULL
                      AND n.operation_type IN ('BUY','SELL')""", (uid, session_id, D)):
            v = float(r["q"] or 0)
            if v <= 0:
                continue
            a = _norm(r["a"])
            qty[a] = qty.get(a, 0.0) + (v if r["op"] == "BUY" else -v)

    # ── 4. Los que NO se pueden rodar hacia atrás ────────────────────────────
    # Operaciones manuales posteriores a D: no hay fila en el ledger que restar,
    # así que el paso 2 no las deshizo y el número queda mal sin avisar.
    for r in conn.execute(
            f"""SELECT DISTINCT o.asset a FROM operations o
                 WHERE o.user_id=? AND o.date > ? AND o.broker IN ({ph})
                   AND NOT EXISTS (SELECT 1 FROM import_op_links l
                                    WHERE l.operation_id = o.id)""",
            (uid, D, *pair)):
        if _norm(r["a"]):
            dudosos[_norm(r["a"])] = MOTIVO_MANUAL

    # Splits ajustados dentro de la ventana: la cantidad de hoy está multiplicada
    # por un factor que no dejó movimiento.
    for r in conn.execute(
            f"""SELECT asset a, split_adjusted_through s FROM positions
                 WHERE user_id=? AND COALESCE(is_cash,0)=0 AND broker IN ({ph})
                   AND split_adjusted_through IS NOT NULL""", (uid, *pair)):
        if str(r["s"] or "")[:10] > D:
            dudosos.setdefault(_norm(r["a"]), MOTIVO_SPLIT)

    # ── 5. Correctores FECHADOS ──────────────────────────────────────────────
    for a in list(qty):
        # Letra que venció ENTRE D y hoy: el sweep borró la posición, así que
        # `positions` ya no tiene el nominal que la persona sí tenía en D.
        # Recuperarlo del ledger sería reintroducir el segundo motor.
        v = letra_maturity(a)
        if v and D < v[:10] <= HOY:
            dudosos.setdefault(a, MOTIVO_VENCIMIENTO)
            continue
        # Bono amortizante: hoy vale nominal × rf(hoy); en D valía nominal × rf(D).
        rf_hoy, rf_d = residual_factor(a, HOY), residual_factor(a, D)
        if rf_hoy > 0 and abs(rf_d - rf_hoy) > 1e-9:
            qty[a] = qty[a] * (rf_d / rf_hoy)

    no_rec = [{"ticker": a, "motivo": m,
               "rendi_qty_hoy": round(qty.get(a, 0.0), 6)}
              for a, m in sorted(dudosos.items())]
    limpio = {a: round(v, 6) for a, v in qty.items()
              if v > 1e-9 and a not in dudosos}
    return limpio, no_rec


MOTIVO_NO_VERIFICA = "proyeccion_no_verifica"


def verificar_contra_snapshot(conn, uid: int, fecha: str,
                              proyectado: Dict[str, float]) -> Optional[dict]:
    """¿La proyección reproduce la composición que el cron estampó ese día?

    Es la prueba más dura disponible y sale gratis: `snapshots.holdings_json` con
    `source='cron'` es una referencia INDEPENDIENTE — no sale del replay del
    ledger ni de la foto del broker, la escribió el cron nocturno. Si el
    retroceso está bien, coincide.

    Devuelve None si no hay con qué comparar, o el detalle del desacuerdo.

    Validado contra la copia de prod del 2026-08-16 sobre 3.855 pares
    (usuario, fecha): **98,6% de composición exacta**, y 13 de 440 usuarios
    (3,0%) no coinciden. De esos 13, 3 se explican porque confirmaron un import
    DESPUÉS del snapshot —o sea que el cron no podía saber— y 10 quedan sin
    explicar. Dos hipótesis probadas y DESCARTADAS: que el snapshot omitiera
    activos sin precio (15 de 16 sí aparecen en snapshots de otros usuarios), y
    que fuera un desfase de fechas de import (sólo 3 de 13).

    ⚠️ LÍMITE DE LA REFERENCIA: el snapshot registra lo que Rendi SABÍA ese día,
    no lo que la persona tenía. Un import cargado después lo deja corto — y en
    ese caso la proyección está MÁS en lo cierto que la referencia. Por eso el
    desacuerdo no invalida el número: marca que no se pudo verificar, que es
    distinto.

    ⚠️ Y compara COMPOSICIÓN, no cantidades: `holdings_json` guarda `value_usd`.
    Alcanza para lo que importa, porque los dos veredictos peligrosos del
    reconcile —"sobra un activo", que el override cierra con una venta
    sintética, y "falta un activo", que crea un lote— son de composición.
    """
    import json as _json
    fila = conn.execute(
        """SELECT date, holdings_json FROM snapshots
            WHERE user_id=? AND source='cron' AND date <= ?
              AND holdings_json IS NOT NULL AND holdings_json <> ''
            ORDER BY date DESC LIMIT 1""", (uid, str(fecha)[:10])).fetchone()
    if not fila:
        return None
    try:
        esperado = {_norm(h.get("asset")) for h in _json.loads(fila["holdings_json"])
                    if h.get("asset")}
    except (ValueError, TypeError):
        return None
    if not esperado:
        return None
    obtenido = set(proyectado)
    falta, sobra = sorted(esperado - obtenido), sorted(obtenido - esperado)
    if not falta and not sobra:
        return None
    return {
        "motivo": MOTIVO_NO_VERIFICA,
        "snapshot_fecha": fila["date"],
        "falta": falta[:20],   # el cron lo tenía y la proyección no
        "sobra": sobra[:20],   # la proyección lo tiene y el cron no
        "detalle": ("la proyección a esa fecha no reproduce la composición que "
                    "el cron habia estampado. Puede ser que la proyección esté "
                    "mal, o que el cron no supiera todavía (un import cargado "
                    "después lo deja corto). En cualquiera de los dos casos no "
                    "se puede afirmar que la comparación contra la foto sea "
                    "válida."),
    }
