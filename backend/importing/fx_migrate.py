"""Migrador FX v1 → v2: pasa UNA cuenta al TC histórico, con las DOS patas juntas.

POR QUÉ EXISTE (el problema de la migración a mitad de camino)
──────────────────────────────────────────────────────────────
El motor gateado por `fx_version` garantiza que el deploy no le cambia el número a
nadie. Pero migrar una cuenta exige tocar DOS patas a la vez:

  · las VENTAS: se re-derivan replayando (rebuild) con `fx_for_date`
  · los FLUJOS: `import_normalized_tx.gross_amount_usd` está estampado con el
    dólar del día del import (medido en prod: 80.868 de 84.123 al mismo 1415,
    desde 2013) y NADA lo re-deriva — hay que re-estamparlo acá

Si se migra una sola pata, los dos errores dejan de cancelarse en el cociente del
Total Return: medido, el error pasa de 1,23× a 9,1×. Por eso este módulo hace
re-estampado + rebuild + recalc + snapshots + `fx_version=v2` en UNA transacción:
o sale todo, o no sale nada.

QUÉ NO HACE (a propósito)
─────────────────────────
  · NO llama a `_remove_trajectory_outlier_snapshots` ni a repair-snapshots-all:
    esa rutina se ancla al capital_final y puede borrar la curva diaria real.
  · NO toca cash (`positions is_cash=1`): el rebuild no lo recompone y este
    migrador tampoco — el cash per-100 es un problema aparte con dos poblaciones
    de signo opuesto (ver project_sell_scale_per100).
  · NO toca operaciones manuales: los pares (broker, activo) con data manual los
    saltea el rebuild (`_is_safe_to_rebuild`) y quedan reportados en
    `pares_salteados` — esas ventas conservan su TC viejo y se miran a mano.

DAÑO COLATERAL DEL REBUILD, MITIGADO ACÁ
────────────────────────────────────────
El rebuild reinserta las positions con `tc_compra`, `price_override` y `notes` en
NULL (rebuild.py `_write_rebuilt`). Este migrador los captura ANTES por
(broker, activo, currency) y los restaura DESPUÉS cuando el valor viejo era único
para ese grupo; los ambiguos (dos lotes del mismo activo con overrides distintos)
se reportan en `overrides_ambiguos` en vez de adivinarse.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

try:
    from fx import fx_for_date, fx_version, set_fx_version, FX_V1, FX_V2
except ImportError:  # pragma: no cover
    from ..fx import fx_for_date, fx_version, set_fx_version, FX_V1, FX_V2

from . import rebuild as _rebuild
from . import persister as _persister

log = logging.getLogger(__name__)


def _metricas(conn, uid: int) -> Dict[str, Any]:
    """La foto contra la que se mide el antes/después. Todo agregados, sin PII."""
    ops = conn.execute(
        "SELECT COUNT(*) n, ROUND(COALESCE(SUM(pnl_usd),0),2) s "
        "FROM operations WHERE user_id=? AND op_type='Venta'", (uid,)).fetchone()
    mon = conn.execute(
        "SELECT ROUND(COALESCE(SUM(deposits),0),2) dep, "
        "       ROUND(COALESCE(SUM(withdrawals),0),2) ret, "
        "       ROUND(COALESCE(SUM(pnl_realized),0),2) pnl "
        "FROM monthly_entries WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    cap = conn.execute(
        "SELECT capital_final FROM monthly_entries "
        "WHERE user_id=? AND broker='global' ORDER BY year DESC, month DESC LIMIT 1",
        (uid,)).fetchone()
    tcs = conn.execute(
        "SELECT COUNT(DISTINCT ROUND(gross_amount/gross_amount_usd, 0)) n "
        "FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
        "WHERE b.user_id=? AND b.status='confirmed' "
        "  AND UPPER(COALESCE(n.currency,''))='ARS' "
        "  AND n.gross_amount_usd IS NOT NULL AND n.gross_amount_usd<>0", (uid,)).fetchone()
    return {
        "ventas": ops["n"], "pnl_ventas_usd": ops["s"],
        "deposits_usd": mon["dep"], "withdrawals_usd": mon["ret"],
        "pnl_realized_usd": mon["pnl"],
        "capital_final": round(cap["capital_final"], 2) if cap and cap["capital_final"] is not None else None,
        "tcs_distintos_en_flujos": tcs["n"],
    }


def migrate_user_fx(conn, uid: int, helpers, *, recalc, backfill_snapshots,
                    recompute_netdep) -> Dict[str, Any]:
    """Migra la cuenta `uid` a FX v2. NO commitea ni rollbackea: el caller decide
    (así el dry-run corre esta MISMA función sobre una copia de la base y el apply
    la corre sobre la real — un solo código, cero divergencia dry-run/apply).
    """
    version = fx_version(conn, uid)
    if version == FX_V2:
        return {"ok": False, "motivo": "la cuenta ya está en v2", "user_id": uid}

    # ── GUARD: cuentas con el bug de ESCALA (per-100) no se migran por acá ────
    # El rebuild de la migración les "arreglaría" el P&L de escala de paso (el
    # guard de reconciled_unit_price corre en el replay), pero el CASH quedaría
    # inflado ×100 sin la firma pnl_pct que hoy lo delata — el "crimen perfecto"
    # documentado en project_sell_scale_per100. Esas ~25 cuentas necesitan su
    # procedimiento propio (cash + foto de tenencia) ANTES de migrar FX.
    escala_rota = conn.execute(
        """SELECT COUNT(*) n FROM operations o
             JOIN import_op_links l ON l.operation_id = o.id
             JOIN import_normalized_tx n2
                  ON n2.batch_id = l.batch_id AND n2.raw_row_id = l.raw_row_id
            WHERE o.user_id=? AND o.op_type='Venta'
              AND o.exit_price IS NOT NULL AND o.quantity IS NOT NULL
              AND n2.gross_amount IS NOT NULL AND n2.gross_amount <> 0
              AND n2.quantity IS NOT NULL AND n2.quantity <> 0
              AND ABS((o.exit_price * o.quantity) /
                      (n2.gross_amount * o.quantity / n2.quantity) - 1) > 0.02""",
        (uid,)).fetchone()["n"]
    if escala_rota:
        return {"ok": False, "user_id": uid,
                "motivo": (f"la cuenta tiene {escala_rota} venta(s) con el bug de "
                           "ESCALA (per-100). Migrarla ahora dejaría el cash inflado "
                           "sin la firma que lo detecta. Primero el procedimiento de "
                           "escala (ver /api/admin/diagnose-scale), después el FX."),
                "ventas_con_escala_rota": escala_rota}

    antes = _metricas(conn, uid)
    resultado: Dict[str, Any] = {"ok": True, "user_id": uid, "antes": antes}

    # ── PATA 1: re-estampar los flujos con el TC de la fecha de cada uno ──────
    # Se re-estampa TODA fila ARS con gross_amount (no solo DEPOSIT/WITHDRAW):
    # gross_amount_usd lo leen también el recalc de monthly y /api/movements.
    filas = conn.execute(
        """SELECT n.id, n.date, n.gross_amount
             FROM import_normalized_tx n
             JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id=? AND b.status='confirmed'
              AND UPPER(COALESCE(n.currency,''))='ARS'
              AND n.gross_amount IS NOT NULL""", (uid,)).fetchall()
    cache: Dict[str, Optional[float]] = {}
    sin_tc = 0
    restamped = 0
    for f in filas:
        d = (f["date"] or "")[:10]
        if d not in cache:
            cache[d] = fx_for_date(conn, d)
        tc = cache[d]
        if not tc or tc <= 0:
            sin_tc += 1        # fecha fuera de la serie: se deja el stamp viejo
            continue
        conn.execute(
            "UPDATE import_normalized_tx SET gross_amount_usd = ? WHERE id = ?",
            (float(f["gross_amount"]) / tc, f["id"]))
        restamped += 1
    resultado["flujos"] = {"ars_totales": len(filas), "re_estampados": restamped,
                           "sin_tc_en_serie": sin_tc}

    # ── Capturar overrides que el rebuild pisa ────────────────────────────────
    overrides = conn.execute(
        """SELECT broker, asset, COALESCE(currency,'') ccy,
                  price_override, tc_compra, notes
             FROM positions
            WHERE user_id=? AND is_cash=0
              AND (price_override IS NOT NULL OR tc_compra IS NOT NULL
                   OR notes IS NOT NULL)""", (uid,)).fetchall()
    por_grupo: Dict[tuple, list] = {}
    for o in overrides:
        por_grupo.setdefault((o["broker"], o["asset"], o["ccy"]), []).append(o)

    # ── Marcar v2 ANTES del rebuild: el rebuild lee fx_version de la cuenta ──
    set_fx_version(conn, uid, FX_V2)

    # ── PATA 2: replayar todas las ventas importadas con el TC histórico ─────
    batches = [r["id"] for r in conn.execute(
        "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed' "
        "ORDER BY confirmed_at", (uid,))]
    tc_fallback = _persister._read_tc_blue(conn, uid=uid)
    salteados: list = []
    errores: list = []
    reconstruidos = 0
    for bid in batches:
        r = _rebuild.rebuild_fifo_after_import(conn, uid, bid, tc_blue=tc_fallback)
        reconstruidos += len(r.get("rebuilt") or [])
        for s in (r.get("skipped_manual") or []):
            if s not in salteados:
                salteados.append(s)
        errores.extend(r.get("errors") or [])
    resultado["rebuild"] = {"batches": len(batches), "grupos_reconstruidos": reconstruidos,
                            "pares_salteados": salteados, "errores": errores}

    # ── Restaurar overrides no ambiguos ───────────────────────────────────────
    restaurados, ambiguos = 0, []
    for (broker, asset, ccy), lst in por_grupo.items():
        vals = {(o["price_override"], o["tc_compra"], o["notes"]) for o in lst}
        if len(vals) != 1:
            ambiguos.append({"broker": broker, "asset": asset,
                             "valores_distintos": len(vals)})
            continue
        po, tcc, nt = next(iter(vals))
        cur = conn.execute(
            """UPDATE positions
                  SET price_override = COALESCE(price_override, ?),
                      tc_compra      = COALESCE(tc_compra, ?),
                      notes          = COALESCE(notes, ?)
                WHERE user_id=? AND broker=? AND asset=? AND is_cash=0
                  AND COALESCE(currency,'')=?""",
            (po, tcc, nt, uid, broker, asset, ccy))
        restaurados += cur.rowcount
    resultado["overrides"] = {"restaurados": restaurados, "overrides_ambiguos": ambiguos}

    # ── Sincronizar la cadena y los snapshots (sin el borrador de outliers) ───
    recalc(conn, uid)
    backfill_snapshots(conn, uid)
    recompute_netdep(conn, uid)

    despues = _metricas(conn, uid)
    resultado["despues"] = despues
    resultado["delta"] = {
        k: round((despues[k] or 0) - (antes[k] or 0), 2)
        for k in ("pnl_ventas_usd", "deposits_usd", "withdrawals_usd",
                  "pnl_realized_usd", "capital_final")
        if isinstance(antes.get(k), (int, float)) or isinstance(despues.get(k), (int, float))
    }
    return resultado
