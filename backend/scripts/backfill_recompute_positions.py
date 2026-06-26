"""Backfill one-time: recomputa las posiciones de las cuentas YA importadas, para
que los fixes de FIFO (currency-aware + neteo cross-broker dólar-MEP) + la
amortización de bonos se apliquen SIN que el usuario tenga que re-importar.

Por qué hace falta
──────────────────
El rebuild FIFO (que netea los fantasmas dólar-MEP y aplica el FIFO por moneda)
corre SOLO dentro de import_confirm. Las cuentas importadas ANTES de los fixes
quedan con el estado viejo (ej. BMA/YPFD fantasma en `· USD`) hasta re-importar.
Este script corre la MISMA secuencia post-import que import_confirm —
rebuild_fifo_after_import (por cada batch confirmado) → sweep_matured_letras →
sweep_bond_amortizations → _recalc_pnl_realized_from_ops— sobre todos los
usuarios, una vez.

Seguridad
─────────
- Reusa las funciones de producción (una sola fuente de verdad).
- El rebuild es idempotente y NO toca cash; saltea (broker,activo) con posiciones
  MANUALES no vinculadas a imports (no corrompe data no reproducible).
- Correrlo sobre una cuenta ya correcta es un no-op (recomputa al mismo estado).
- Dry-run por default: muestra el antes→después por posición; --apply commitea.

Uso
───
    python scripts/backfill_recompute_positions.py            # DRY-RUN (no cambia nada)
    python scripts/backfill_recompute_positions.py --apply    # aplica + commitea
    python scripts/backfill_recompute_positions.py --user 42  # una sola cuenta

⚠️  Backup antes de --apply:  python scripts/backup_db.py
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from importing import rebuild as _rebuild  # noqa: E402
from importing import persister as _persister  # noqa: E402
from importing import maturity as _maturity  # noqa: E402


def _positions_snapshot(conn, uid):
    """{(broker, asset): qty} de las posiciones no-cash con qty>0."""
    rows = conn.execute(
        "SELECT broker, asset, COALESCE(SUM(quantity),0) q FROM positions "
        "WHERE user_id=? AND is_cash=0 AND quantity>0 GROUP BY broker, asset",
        (uid,),
    ).fetchall()
    return {(r["broker"], r["asset"]): float(r["q"] or 0) for r in rows}


def _cash_total(conn, uid):
    r = conn.execute(
        "SELECT COALESCE(SUM(invested),0) c FROM positions WHERE user_id=? AND is_cash=1",
        (uid,),
    ).fetchone()
    return round(float(r["c"] or 0), 2)


def _recompute_user(conn, uid):
    """Corre la misma secuencia post-persist que import_confirm. Muta en la
    transacción abierta (el caller decide commit/rollback)."""
    tc_blue = _persister._read_tc_blue(conn, uid)
    batches = [r["id"] for r in conn.execute(
        "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'", (uid,)
    ).fetchall()]
    for bid in batches:
        _rebuild.rebuild_fifo_after_import(conn, uid, bid, tc_blue=tc_blue)
    _maturity.sweep_matured_letras(conn, uid)
    _maturity.sweep_bond_amortizations(conn, uid)
    main._recalc_pnl_realized_from_ops(conn, uid)


def _process(conn, users, *, apply: bool) -> tuple:
    """Recorre los usuarios, recomputa y reporta el diff. `conn` es la DB real
    (apply) o una COPIA (dry-run); en ambos casos commiteamos por usuario — en la
    copia es inocuo. Devuelve (users_changed, cash_warnings)."""
    users_changed = 0
    cash_warnings = 0
    for uid in users:
        before = _positions_snapshot(conn, uid)
        cash_before = _cash_total(conn, uid)
        try:
            _recompute_user(conn, uid)
        except Exception as ex:
            conn.rollback()
            print(f"  uid={uid}: ERROR {ex} → se saltea")
            continue
        after = _positions_snapshot(conn, uid)
        cash_after = _cash_total(conn, uid)

        changes = []
        for k in sorted(set(before) | set(after)):
            b, a = before.get(k, 0.0), after.get(k, 0.0)
            if abs(b - a) > 1e-6:
                changes.append((k, b, a))
        if changes:
            users_changed += 1
            for (brk, asset), b, a in changes:
                tag = "ELIMINADA" if a == 0 else "ajustada"
                print(f"  uid={uid:<5} {brk:<14} {asset:<8} {b:>14,.2f} → {a:>14,.2f}  ({tag})")
        # Chequeo de seguridad: el rebuild NO debe tocar cash.
        if abs(cash_before - cash_after) > 1.0:
            cash_warnings += 1
            print(f"  ⚠️  uid={uid}: cash cambió {cash_before:,.2f} → {cash_after:,.2f} "
                  f"(NO debería — revisar antes de --apply)")
        conn.commit()
    return users_changed, cash_warnings


def run(apply: bool, only_uid=None) -> int:
    real = main.get_db()
    if only_uid is not None:
        users = [only_uid]
    else:
        users = [r["id"] for r in real.execute("SELECT id FROM users ORDER BY id").fetchall()]

    mode = "APLICANDO (commit)" if apply else "DRY-RUN (sin cambios — sobre copia)"
    print(f"== Backfill recompute de posiciones · {mode} · {len(users)} usuarios ==\n")

    if apply:
        users_changed, cash_warnings = _process(real, users, apply=True)
        real.close()
    else:
        # DRY-RUN a prueba de balas: clonamos el DB (snapshot consistente, incluye
        # WAL) y recomputamos sobre la COPIA. La DB real NUNCA se toca — esto evita
        # cualquier sorpresa con los SAVEPOINT del rebuild + el manejo de
        # transacciones de sqlite3 (un rollback en la conn real no es confiable acá).
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        clone = sqlite3.connect(tmp.name)
        clone.row_factory = sqlite3.Row
        real.backup(clone)
        real.close()
        try:
            users_changed, cash_warnings = _process(clone, users, apply=False)
        finally:
            clone.close()
            for p in (tmp.name, tmp.name + "-wal", tmp.name + "-shm"):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    print(f"\n== {'Aplicado' if apply else 'Simulado'}: {users_changed} usuarios con cambios "
          f"en posiciones · {cash_warnings} alertas de cash ==")
    if not apply and users_changed:
        print("   Revisá el detalle y re-corré con --apply. Backup antes: python scripts/backup_db.py")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill: recomputa posiciones (FIFO + amort) sin re-import.")
    ap.add_argument("--apply", action="store_true", help="aplica y commitea (default: dry-run)")
    ap.add_argument("--user", type=int, default=None, help="recomputar solo este user_id")
    args = ap.parse_args()
    sys.exit(run(args.apply, args.user))
