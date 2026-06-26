"""Motor del backfill de recompute — compartido por el script CLI
(scripts/backfill_recompute_positions.py) y el endpoint admin
(/api/admin/backfill-recompute).

Corre la MISMA secuencia post-import que import_confirm sobre cuentas YA
importadas — rebuild_fifo_after_import (por cada batch confirmado) →
sweep_matured_letras → sweep_bond_amortizations → recalc — para aplicar los fixes
de FIFO (currency-aware + neteo cross-broker dólar-MEP) y la amortización de bonos
SIN que el usuario re-importe.

Seguro: reusa las funciones de producción; el rebuild es idempotente, NO toca cash
y saltea cuentas con posiciones manuales. El dry-run corre sobre una COPIA del DB
(backup API de sqlite) → la base real nunca se toca.

`recalc` se inyecta (callable _recalc_pnl_realized_from_ops) para no importar main.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from typing import Any, Callable, Dict, List

from . import rebuild as _rebuild
from . import persister as _persister
from . import maturity as _maturity


def positions_snapshot(conn, uid: int) -> Dict[tuple, float]:
    rows = conn.execute(
        "SELECT broker, asset, COALESCE(SUM(quantity),0) q FROM positions "
        "WHERE user_id=? AND is_cash=0 AND quantity>0 GROUP BY broker, asset",
        (uid,),
    ).fetchall()
    return {(r["broker"], r["asset"]): float(r["q"] or 0) for r in rows}


def cash_total(conn, uid: int) -> float:
    r = conn.execute(
        "SELECT COALESCE(SUM(invested),0) c FROM positions WHERE user_id=? AND is_cash=1",
        (uid,),
    ).fetchone()
    return round(float(r["c"] or 0), 2)


_FIXED_INCOME_TYPES = {"BOND", "BONO", "ON", "LETRA", "LECAP"}


def _is_known_ar_bond(symbol: str) -> bool:
    try:
        from ai.ar_bonds_metadata import is_known_ar_bond
    except Exception:
        return False
    return bool(is_known_ar_bond(symbol))


def bond_per100_factor(unit_cost: float, market_per1: float) -> float:
    """Factor para llevar el cost basis de un bono a per-1 VN (canónico del sistema).

    1.0 si ya está per-1; 0.01 si está per-100 (hay que ÷100). Decide por el ratio
    costo/precio-de-mercado: per-1 ≈ 1×, per-100 ≈ 100×. El umbral 10 (media
    geométrica de 1 y 100) los separa — el precio de un bono no varía 10× entre la
    compra y hoy, así que es robusto y no confunde "compré barato/caro" con un cambio
    de unidad. Fuera de (10, 1000) → 1.0 (no es un per-100 limpio: no tocar)."""
    if not unit_cost or not market_per1 or market_per1 <= 0:
        return 1.0
    ratio = unit_cost / market_per1
    return 0.01 if 10.0 < ratio < 1000.0 else 1.0


def normalize_bond_units(conn, uid: int, *, bond_price_per1: Callable) -> int:
    """Lleva a per-1 VN el cost basis de los bonos guardados per-100 (bug del
    importador: IEB exporta por 100 nominales, Balanz a veces también; el precio
    actual ya se trae per-1 → P&L -99% fantasma). Detecta la unidad comparando el
    costo unitario contra el precio de mercado per-1, así NO rompe los lotes que ya
    vienen per-1 (Balanz USD/ARS). Idempotente (tras ÷100 el ratio ≈1, no re-dispara).
    No toca cash. Devuelve nº de posiciones ajustadas. `bond_price_per1(sym, ccy)`
    devuelve el precio per-1 del bono en esa moneda, o None."""
    rows = conn.execute(
        "SELECT id, asset, quantity, invested, buy_price, currency, asset_type "
        "FROM positions WHERE user_id=? AND is_cash=0 AND quantity>0", (uid,)
    ).fetchall()
    n = 0
    for r in rows:
        sym = (r["asset"] or "").upper()
        at = (r["asset_type"] or "").upper()
        if not (at in _FIXED_INCOME_TYPES or _is_known_ar_bond(sym)):
            continue
        qty = r["quantity"] or 0
        if qty <= 0:
            continue
        inv = r["invested"]
        unit_cost = (inv / qty) if inv else (r["buy_price"] or 0)
        m1 = bond_price_per1(sym, r["currency"])
        if not m1:
            continue
        factor = bond_per100_factor(unit_cost, m1)
        if factor == 1.0:
            continue
        new_inv = round((inv or 0) * factor, 6) if inv is not None else None
        new_bp = round((r["buy_price"] or 0) * factor, 6) if r["buy_price"] is not None else None
        conn.execute(
            "UPDATE positions SET invested=?, buy_price=? WHERE id=? AND user_id=?",
            (new_inv, new_bp, r["id"], uid),
        )
        n += 1
    return n


def recompute_user(conn, uid: int, *, recalc: Callable,
                   bond_price_per1: Callable = None) -> None:
    """Misma secuencia post-persist que import_confirm. Muta en la transacción
    abierta (el caller commitea)."""
    tc_blue = _persister._read_tc_blue(conn, uid)
    batches = [r["id"] for r in conn.execute(
        "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'", (uid,)
    ).fetchall()]
    for bid in batches:
        _rebuild.rebuild_fifo_after_import(conn, uid, bid, tc_blue=tc_blue)
    _maturity.sweep_matured_letras(conn, uid)
    _maturity.sweep_bond_amortizations(conn, uid)
    if bond_price_per1 is not None:
        normalize_bond_units(conn, uid, bond_price_per1=bond_price_per1)
    recalc(conn, uid)


def run_backfill(conn, users: List[int], *, recalc: Callable,
                 bond_price_per1: Callable = None,
                 max_changes: int = 1000) -> Dict[str, Any]:
    """Recorre `users`, recomputa y COMMITEA por usuario. Devuelve un resumen
    estructurado. Para dry-run, pasar una conn a una COPIA del DB (ver
    dry_run_summary) — ahí el commit es inocuo."""
    summary: Dict[str, Any] = {
        "total_users": len(users), "users_changed": 0, "positions_changed": 0,
        "cash_warnings": 0, "changes": [], "errors": [], "truncated": False,
    }
    for uid in users:
        before = positions_snapshot(conn, uid)
        cash_before = cash_total(conn, uid)
        try:
            recompute_user(conn, uid, recalc=recalc, bond_price_per1=bond_price_per1)
        except Exception as ex:
            conn.rollback()
            summary["errors"].append({"uid": uid, "error": str(ex)})
            continue
        after = positions_snapshot(conn, uid)
        cash_after = cash_total(conn, uid)

        user_changes = []
        for k in sorted(set(before) | set(after)):
            b, a = before.get(k, 0.0), after.get(k, 0.0)
            if abs(b - a) > 1e-6:
                user_changes.append({
                    "uid": uid, "broker": k[0], "asset": k[1],
                    "before": round(b, 4), "after": round(a, 4),
                    "tag": "eliminada" if a == 0 else "ajustada",
                })
        if user_changes:
            summary["users_changed"] += 1
            summary["positions_changed"] += len(user_changes)
            for ch in user_changes:
                if len(summary["changes"]) < max_changes:
                    summary["changes"].append(ch)
                else:
                    summary["truncated"] = True
        # El rebuild NO debe tocar cash → si cambia, lo flageamos fuerte.
        if abs(cash_before - cash_after) > 1.0:
            summary["cash_warnings"] += 1
            summary["changes"].append({
                "uid": uid, "cash_warning": True,
                "cash_before": cash_before, "cash_after": cash_after,
            })
        conn.commit()
    return summary


def dry_run_summary(real_conn, users: List[int], *, recalc: Callable,
                    bond_price_per1: Callable = None) -> Dict[str, Any]:
    """Clona el DB (snapshot consistente, incluye WAL) y corre el backfill sobre
    la COPIA → la base real NUNCA se toca. Devuelve el mismo resumen que
    run_backfill, sin haber mutado nada real."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    clone = sqlite3.connect(tmp.name)
    clone.row_factory = sqlite3.Row
    try:
        real_conn.backup(clone)
        return run_backfill(clone, users, recalc=recalc, bond_price_per1=bond_price_per1)
    finally:
        clone.close()
        for p in (tmp.name, tmp.name + "-wal", tmp.name + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass
