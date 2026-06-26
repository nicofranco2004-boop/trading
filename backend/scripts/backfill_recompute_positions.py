"""Backfill one-time (CLI): recomputa las posiciones de las cuentas YA importadas
para aplicar los fixes de FIFO (currency-aware + neteo cross-broker dólar-MEP) +
la amortización de bonos SIN que el usuario re-importe.

El motor vive en importing/recompute_backfill.py (compartido con el botón admin
/api/admin/backfill-recompute). Este archivo es solo el wrapper de línea de comando.

Uso
───
    python scripts/backfill_recompute_positions.py            # DRY-RUN (sobre copia, no toca nada)
    python scripts/backfill_recompute_positions.py --apply    # aplica + commitea
    python scripts/backfill_recompute_positions.py --user 42  # una sola cuenta

⚠️  Backup antes de --apply:  python scripts/backup_db.py
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from importing import recompute_backfill as _rb  # noqa: E402

# Aliases retro-compatibles (los usan los tests).
_positions_snapshot = _rb.positions_snapshot
_cash_total = _rb.cash_total


def _recompute_user(conn, uid):
    _rb.recompute_user(conn, uid, recalc=main._recalc_pnl_realized_from_ops)


def _print_summary(summary, apply):
    for ch in summary["changes"]:
        if ch.get("cash_warning"):
            print(f"  ⚠️  uid={ch['uid']}: cash {ch['cash_before']:,.2f} → {ch['cash_after']:,.2f} "
                  f"(NO debería — revisar antes de --apply)")
        else:
            print(f"  uid={ch['uid']:<5} {ch['broker']:<14} {ch['asset']:<8} "
                  f"{ch['before']:>14,.2f} → {ch['after']:>14,.2f}  ({ch['tag']})")
    for e in summary["errors"]:
        print(f"  uid={e['uid']}: ERROR {e['error']} → se saltea")
    if summary.get("truncated"):
        print("  … (lista truncada; ver los totales)")
    print(f"\n== {'Aplicado' if apply else 'Simulado'}: {summary['users_changed']} usuarios con cambios "
          f"({summary['positions_changed']} posiciones) · {summary['cash_warnings']} alertas de cash "
          f"· {len(summary['errors'])} errores ==")
    if not apply and summary["users_changed"]:
        print("   Revisá el detalle y re-corré con --apply. Backup antes: python scripts/backup_db.py")


def run(apply: bool, only_uid=None) -> int:
    real = main.get_db()
    try:
        if only_uid is not None:
            users = [only_uid]
        else:
            users = [r["id"] for r in real.execute("SELECT id FROM users ORDER BY id").fetchall()]
        recalc = main._recalc_pnl_realized_from_ops
        mode = "APLICANDO (commit)" if apply else "DRY-RUN (sin cambios — sobre copia)"
        print(f"== Backfill recompute de posiciones · {mode} · {len(users)} usuarios ==\n")
        if apply:
            summary = _rb.run_backfill(real, users, recalc=recalc)
        else:
            summary = _rb.dry_run_summary(real, users, recalc=recalc)
        _print_summary(summary, apply)
    finally:
        real.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill: recomputa posiciones (FIFO + amort) sin re-import.")
    ap.add_argument("--apply", action="store_true", help="aplica y commitea (default: dry-run)")
    ap.add_argument("--user", type=int, default=None, help="recomputar solo este user_id")
    args = ap.parse_args()
    sys.exit(run(args.apply, args.user))
