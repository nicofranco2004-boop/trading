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


def recompute_user(conn, uid: int, *, recalc: Callable) -> None:
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
    recalc(conn, uid)


def run_backfill(conn, users: List[int], *, recalc: Callable,
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
            recompute_user(conn, uid, recalc=recalc)
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


def _after_state_on_clone(real_conn, uid: int, recalc: Callable) -> Dict[tuple, float]:
    """Clona el DB, corre el recompute completo sobre la copia y devuelve el estado
    'ideal' por (broker, asset). La DB real NUNCA se toca."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    clone = sqlite3.connect(tmp.name)
    clone.row_factory = sqlite3.Row
    try:
        real_conn.backup(clone)
        recompute_user(clone, uid, recalc=recalc)
        return positions_snapshot(clone, uid)
    finally:
        clone.close()
        for p in (tmp.name, tmp.name + "-wal", tmp.name + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass


def _classify_safe(real_conn, uid: int, before: Dict[tuple, float],
                   after: Dict[tuple, float]) -> List[Dict[str, Any]]:
    """De todos los cambios (before→after del recompute), devuelve SOLO los
    INEQUÍVOCOS, clasificados a nivel del PAR de brokers (para no confundir un
    MOVIMIENTO genuino padre↔sibling con una eliminación):
      - fantasma de acción/CEDEAR dólar-MEP → 0 (no es bono)
      - letra vencida → 0
      - bono 100% amortizado → 0
      - amortización limpia (bono, after ≈ before × factor_residual)
    Todo lo demás (inflaciones, bonos→0 con residual>0, movimientos, reducciones que
    no cierran con el cronograma) se OMITE."""
    from datetime import date
    from .persister import broker_pair
    from .maturity import is_bond_like_name, letra_maturity, maturity_from_name
    from pricing.bond_amortization import residual_factor, is_amortizing_bond
    try:
        from ai.ar_bonds_metadata import is_known_ar_bond
    except Exception:
        def is_known_ar_bond(_t):
            return False

    today = date.today().isoformat()
    name_map: Dict[tuple, str] = {}
    for r in real_conn.execute(
        "SELECT DISTINCT n.broker, n.asset_symbol, n.asset_name FROM import_normalized_tx n "
        "JOIN import_batches b ON b.id=n.batch_id WHERE b.user_id=? AND n.asset_symbol != ''",
        (uid,),
    ).fetchall():
        name_map.setdefault((r["broker"], r["asset_symbol"]), r["asset_name"] or "")

    pair_cache: Dict[str, tuple] = {}
    def _pair(b):
        if b not in pair_cache:
            pair_cache[b] = tuple(broker_pair(real_conn, uid, b))
        return pair_cache[b]

    groups: Dict[tuple, Dict[str, Any]] = {}
    for (b, a) in set(before) | set(after):
        g = groups.setdefault((_pair(b), a), {"before": 0.0, "after": 0.0, "name": ""})
        g["before"] += before.get((b, a), 0.0)
        g["after"] += after.get((b, a), 0.0)
        if not g["name"]:
            g["name"] = name_map.get((b, a), "")

    safe: List[Dict[str, Any]] = []
    for (pair, a), g in groups.items():
        bq, aq, name = g["before"], g["after"], g["name"]
        if abs(aq - bq) <= 1e-6:
            continue
        amort_key = a if is_amortizing_bond(a) else (name if is_amortizing_bond(name) else None)
        is_bond = bool(is_known_ar_bond(a) or is_bond_like_name(name))
        mat = letra_maturity(a) or maturity_from_name(name)
        is_letra_matured = bool(mat and mat <= today)

        if aq <= 1e-9 < bq:                          # eliminación (par → 0)
            if (not is_bond) or is_letra_matured:
                safe.append({"pair": pair, "asset": a, "before": bq, "after": 0.0,
                             "kind": "letra vencida" if is_letra_matured else "fantasma dólar-MEP"})
            elif amort_key and residual_factor(amort_key, today) <= 1e-9:
                safe.append({"pair": pair, "asset": a, "before": bq, "after": 0.0,
                             "kind": "bono 100% amortizado"})
            # bono → 0 con residual>0, o bono no-amortizante → AMBIGUO → omitir
            continue
        if aq < bq and amort_key:                    # amortización limpia (× factor)
            R = residual_factor(amort_key, today)
            if 0 < R < 1 and abs(aq - bq * R) <= max(0.5, 0.005 * bq):
                safe.append({"pair": pair, "asset": a, "before": bq, "after": aq,
                             "kind": "amortización"})
        # inflación / movimiento / reducción rara → omitir
    return safe


def _apply_safe(real_conn, uid: int, safe: List[Dict[str, Any]], linked: set) -> None:
    """Aplica los cambios seguros a la DB REAL: escala los lotes import-linked del
    par a su nominal objetivo (borra si es 0). Respeta lotes manuales."""
    for ch in safe:
        pair, a, target = ch["pair"], ch["asset"], ch["after"]
        _ph = ",".join("?" * len(pair))
        lots = real_conn.execute(
            f"SELECT id, quantity, invested, commissions FROM positions "
            f"WHERE user_id=? AND broker IN ({_ph}) AND asset=? AND is_cash=0 AND quantity>0",
            (uid, *pair, a),
        ).fetchall()
        linked_lots = [l for l in lots if l["id"] in linked]
        cur = sum((l["quantity"] or 0) for l in linked_lots)
        if cur <= 1e-9:
            continue
        factor = target / cur
        for l in linked_lots:
            nq = (l["quantity"] or 0) * factor
            if nq <= 1e-9:
                real_conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (l["id"], uid))
            else:
                real_conn.execute(
                    "UPDATE positions SET quantity=?, invested=?, commissions=? WHERE id=? AND user_id=?",
                    (round(nq, 6), round((l["invested"] or 0) * factor, 6),
                     round((l["commissions"] or 0) * factor, 6), l["id"], uid))


def safe_backfill(real_conn, users: List[int], *, recalc: Callable, apply: bool) -> Dict[str, Any]:
    """Backfill SOLO de cambios seguros (ver _classify_safe). El estado 'ideal' se
    computa sobre una COPIA (la real no se toca para clasificar); solo los cambios
    inequívocos se aplican a la real (si apply). Devuelve resumen con `kind` por cambio."""
    from .maturity import _import_linked_position_ids
    summary: Dict[str, Any] = {
        "mode": "safe", "total_users": len(users), "users_changed": 0,
        "positions_changed": 0, "changes": [], "errors": [], "truncated": False,
    }
    for uid in users:
        before = positions_snapshot(real_conn, uid)
        try:
            after = _after_state_on_clone(real_conn, uid, recalc)
        except Exception as ex:
            summary["errors"].append({"uid": uid, "error": str(ex)})
            continue
        safe = _classify_safe(real_conn, uid, before, after)
        if not safe:
            continue
        if apply:
            _apply_safe(real_conn, uid, safe, _import_linked_position_ids(real_conn, uid))
            real_conn.commit()
        summary["users_changed"] += 1
        for ch in safe:
            summary["positions_changed"] += 1
            if len(summary["changes"]) < 1000:
                summary["changes"].append({
                    "uid": uid,
                    "broker": ch["pair"][0] if len(ch["pair"]) == 1 else "+".join(ch["pair"]),
                    "asset": ch["asset"], "before": round(ch["before"], 4),
                    "after": round(ch["after"], 4), "kind": ch["kind"],
                })
            else:
                summary["truncated"] = True
    return summary


def dry_run_summary(real_conn, users: List[int], *, recalc: Callable) -> Dict[str, Any]:
    """Clona el DB (snapshot consistente, incluye WAL) y corre el backfill sobre
    la COPIA → la base real NUNCA se toca. Devuelve el mismo resumen que
    run_backfill, sin haber mutado nada real."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    clone = sqlite3.connect(tmp.name)
    clone.row_factory = sqlite3.Row
    try:
        real_conn.backup(clone)
        return run_backfill(clone, users, recalc=recalc)
    finally:
        clone.close()
        for p in (tmp.name, tmp.name + "-wal", tmp.name + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass
