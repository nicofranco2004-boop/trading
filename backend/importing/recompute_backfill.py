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
import time as _time
from contextlib import contextmanager as _contextmanager
from typing import Any, Callable, Dict, List

from . import rebuild as _rebuild
from . import persister as _persister
from . import maturity as _maturity


def _db_dir_of(real_conn):
    """Directorio donde vive la DB real, derivado de la PROPIA conexión (sin
    importar main, para no crear ciclo). El clon temporal del dry-run se escribe
    AHÍ — en prod el volumen persistente /data, que es escribible y tiene espacio
    — y NO en el /tmp efímero del contenedor (otro filesystem) que rompía el
    backup con un 500. Si no se puede resolver, devuelve None → NamedTemporaryFile
    cae al tmpdir por defecto (comportamiento previo)."""
    try:
        for row in real_conn.execute("PRAGMA database_list"):
            name, file = row[1], row[2]            # (seq, name, file)
            if name == "main" and file:
                d = os.path.dirname(file)
                if d and os.path.isdir(d):
                    return d
    except Exception:
        pass
    return None


@_contextmanager
def _clone_db(real_conn):
    """Clona la DB real a una copia temporal (snapshot consistente vía backup API,
    incluye WAL) y cede una conexión sqlite a esa copia. La copia se crea JUNTO a
    la DB real (mismo volumen escribible, no el /tmp efímero) y backup() se
    reintenta ante un lock transitorio. Limpia el .db + sidecars -wal/-shm en el
    finally, SIEMPRE. Reemplaza el patrón tempfile+backup+try/finally duplicado en
    cada call-site del dry-run."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, dir=_db_dir_of(real_conn))
    tmp.close()
    clone = sqlite3.connect(tmp.name)
    clone.row_factory = sqlite3.Row
    try:
        last_exc = None
        for attempt in range(5):               # ~0.25+0.5+0.75+1.0s de backoff
            try:
                real_conn.backup(clone)
                last_exc = None
                break
            except sqlite3.OperationalError as ex:
                if "locked" in str(ex).lower() or "busy" in str(ex).lower():
                    last_exc = ex
                    _time.sleep(0.25 * (attempt + 1))
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        yield clone
    finally:
        clone.close()
        for p in (tmp.name, tmp.name + "-wal", tmp.name + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass


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


def normalize_usd_commissions(conn, uid: int, *, tc_blue: float) -> int:
    """Corrige comisiones en ARS guardadas en posiciones USD. Balanz reporta los
    Gastos en PESOS aun para trades en dólares/cable, y el parser los guarda crudos
    → en un bono USD la comisión queda ×MEP, infla el cost basis y da P&L fantasma
    (ej. YM39O: comisión 31.701 sobre invertido 5.028 → -84%). Heurística a prueba de
    balas: una comisión MAYOR que el invertido es imposible para una comisión real →
    está en pesos → se pasa a USD ÷ tc_blue. Idempotente (tras dividir queda chica).
    No toca posiciones ARS (ahí invertido y comisión están en la misma moneda)."""
    if not tc_blue or tc_blue <= 0:
        return 0
    rows = conn.execute(
        "SELECT id, invested, commissions, currency FROM positions "
        "WHERE user_id=? AND is_cash=0 AND quantity>0", (uid,)
    ).fetchall()
    n = 0
    for r in rows:
        if (r["currency"] or "").upper() not in ("USD", "USDT"):
            continue
        inv = r["invested"] or 0
        com = r["commissions"] or 0
        if inv > 0 and com > inv:   # comisión > trade entero → está en pesos
            conn.execute("UPDATE positions SET commissions=? WHERE id=? AND user_id=?",
                         (round(com / tc_blue, 6), r["id"], uid))
            n += 1
    return n


def tag_bonds_from_data912(conn, uid: int, *, is_bond_ticker: Callable) -> int:
    """Tagea asset_type='BOND' a posiciones de renta fija que data912 cotiza
    (soberanos, CER, BOPREAL y OBLIGACIONES NEGOCIABLES) y que están sin tipo o como
    OTHER — típico de IEB, que no etiqueta el tipo. Así se agrupan solas en la zona
    Renta Fija sin mantener una lista curada. NO toca posiciones con tipo específico
    (CEDEAR/STOCK/FUND/CRYPTO). `is_bond_ticker(ticker)` consulta el universo data912.
    Devuelve nº tageadas."""
    rows = conn.execute(
        "SELECT id, asset, asset_type FROM positions WHERE user_id=? AND is_cash=0 AND quantity>0",
        (uid,),
    ).fetchall()
    n = 0
    for r in rows:
        at = (r["asset_type"] or "").upper()
        if at and at != "OTHER":
            continue   # ya tiene un tipo específico → no tocar
        if is_bond_ticker(r["asset"]):
            conn.execute("UPDATE positions SET asset_type='BOND' WHERE id=? AND user_id=?",
                         (r["id"], uid))
            n += 1
    return n


def recompute_user(conn, uid: int, *, recalc: Callable,
                   bond_price_per1: Callable = None,
                   tag_bond_ticker: Callable = None) -> None:
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
    if tag_bond_ticker is not None:
        tag_bonds_from_data912(conn, uid, is_bond_ticker=tag_bond_ticker)
    if bond_price_per1 is not None:
        normalize_bond_units(conn, uid, bond_price_per1=bond_price_per1)
    normalize_usd_commissions(conn, uid, tc_blue=tc_blue)
    recalc(conn, uid)


def run_backfill(conn, users: List[int], *, recalc: Callable,
                 bond_price_per1: Callable = None, tag_bond_ticker: Callable = None,
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
            recompute_user(conn, uid, recalc=recalc, bond_price_per1=bond_price_per1,
                           tag_bond_ticker=tag_bond_ticker)
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
    with _clone_db(real_conn) as clone:
        recompute_user(clone, uid, recalc=recalc)
        return positions_snapshot(clone, uid)


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


def safe_backfill(real_conn, users: List[int], *, recalc: Callable, apply: bool,
                  bond_price_per1: Callable = None, tag_bond_ticker: Callable = None) -> Dict[str, Any]:
    """Backfill SOLO de cambios seguros (ver _classify_safe). El estado 'ideal' se
    computa sobre UNA copia (no por usuario — clonar el DB por cada usuario hacía
    timeout-ear el endpoint); solo los cambios inequívocos se aplican a la real.
    Pensado para correr por TANDAS (el caller pasa un chunk de `users`)."""
    from .maturity import _import_linked_position_ids
    summary: Dict[str, Any] = {
        "mode": "safe", "total_users": len(users), "users_changed": 0,
        "positions_changed": 0, "changes": [], "errors": [], "truncated": False,
    }
    # Saltear usuarios sin posiciones (vacíos): no hay nada que recomputar.
    with_pos = [u for u in users if real_conn.execute(
        "SELECT 1 FROM positions WHERE user_id=? AND is_cash=0 AND quantity>0 LIMIT 1",
        (u,)).fetchone()]
    if not with_pos:
        return summary

    # Clonar UNA vez (snapshot consistente). Recomputamos cada usuario sobre la MISMA
    # copia (commit por usuario para aislar fallos) y guardamos su estado 'ideal'.
    after_by_user: Dict[int, Dict[tuple, float]] = {}
    with _clone_db(real_conn) as clone:
        for uid in with_pos:
            try:
                recompute_user(clone, uid, recalc=recalc, bond_price_per1=bond_price_per1,
                               tag_bond_ticker=tag_bond_ticker)
                clone.commit()
                after_by_user[uid] = positions_snapshot(clone, uid)
            except Exception as ex:
                clone.rollback()
                summary["errors"].append({"uid": uid, "error": str(ex)})

    for uid in with_pos:
        after = after_by_user.get(uid)
        if after is None:
            continue
        before = positions_snapshot(real_conn, uid)
        try:
            safe = _classify_safe(real_conn, uid, before, after)
        except Exception as ex:
            summary["errors"].append({"uid": uid, "error": "classify: " + str(ex)})
            continue
        if not safe:
            continue
        if apply:
            try:
                _apply_safe(real_conn, uid, safe, _import_linked_position_ids(real_conn, uid))
                real_conn.commit()
            except Exception as ex:
                real_conn.rollback()
                summary["errors"].append({"uid": uid, "error": "apply: " + str(ex)})
                continue
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


def dry_run_summary(real_conn, users: List[int], *, recalc: Callable,
                    bond_price_per1: Callable = None, tag_bond_ticker: Callable = None) -> Dict[str, Any]:
    """Clona el DB (snapshot consistente, incluye WAL) y corre el backfill sobre
    la COPIA → la base real NUNCA se toca. Devuelve el mismo resumen que
    run_backfill, sin haber mutado nada real."""
    with _clone_db(real_conn) as clone:
        return run_backfill(clone, users, recalc=recalc, bond_price_per1=bond_price_per1,
                            tag_bond_ticker=tag_bond_ticker)
