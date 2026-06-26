"""Backfill one-time: aplica el residual de amortización a los bonos YA importados.

Contexto
────────
`sweep_bond_amortizations` corre en cada import_confirm, así que los imports
NUEVOS ya bajan los bonos amortizantes (AL29/AL30/…) a su nominal residual. Pero
las tenencias importadas ANTES del deploy NO se ajustan hasta el próximo import.
Este script corre el MISMO sweep sobre todos los usuarios, una vez, para que se
corrijan sin que nadie tenga que re-importar.

Seguridad
─────────
- Reusa la función de producción (una sola fuente de verdad, sin lógica duplicada).
- Idempotente: correrlo dos veces no baja de más (target = (comprado−vendido)×R,
  recalculado desde los movimientos importados, estable).
- Solo toca lotes import-linked; respeta posiciones manuales; NO toca cash.
- Solo afecta bonos con cronograma VERIFICADO (AL29/GD29, AL30/GD30); el resto
  tiene R=1 → no-op.

Uso
───
    python scripts/backfill_bond_amortizations.py            # DRY-RUN (no cambia nada)
    python scripts/backfill_bond_amortizations.py --apply    # aplica + commitea

⚠️  Hacé backup de la DB antes de --apply:  python scripts/backup_db.py
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from importing.maturity import sweep_bond_amortizations  # noqa: E402


def _bond_qty(conn, uid, broker, asset) -> float:
    r = conn.execute(
        "SELECT COALESCE(SUM(quantity),0) q FROM positions "
        "WHERE user_id=? AND broker=? AND asset=? AND is_cash=0",
        (uid, broker, asset),
    ).fetchone()
    return float(r["q"] or 0)


def run(apply: bool) -> int:
    ref = date.today().isoformat()
    conn = main.get_db()
    users = [r["id"] for r in conn.execute("SELECT id FROM users ORDER BY id").fetchall()]

    mode = "APLICANDO (commit)" if apply else "DRY-RUN (sin cambios)"
    print(f"== Backfill amortización de bonos · {mode} · ref_date={ref} · {len(users)} usuarios ==\n")

    users_affected = 0
    rows_affected = 0
    for uid in users:
        # El sweep muta dentro de la transacción abierta; capturamos `adjusted`.
        res = sweep_bond_amortizations(conn, uid, ref_date=ref)
        adj = res.get("adjusted") or []
        if not adj:
            conn.rollback()
            continue
        users_affected += 1
        for a in adj:
            after = _bond_qty(conn, uid, a["broker"], a["asset"])  # ya reducido en la tx
            before = after + a["reduced"]
            rows_affected += 1
            print(f"  uid={uid:<5} {a['broker']:<14} {a['asset']:<8} "
                  f"{before:>14,.2f} → {after:>14,.2f} VN   (R={a['residual_factor']:.4f})")
        if apply:
            conn.commit()
        else:
            conn.rollback()

    print(f"\n== {'Aplicado' if apply else 'Simulado'}: "
          f"{rows_affected} posiciones de bono en {users_affected} usuarios ==")
    if not apply and rows_affected:
        print("   Revisá el detalle de arriba y re-corré con --apply para aplicar.")
        print("   Antes de --apply hacé backup:  python scripts/backup_db.py")
    conn.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill del residual de amortización de bonos AR.")
    ap.add_argument("--apply", action="store_true",
                    help="aplica y commitea los cambios (default: dry-run, no cambia nada)")
    sys.exit(run(ap.parse_args().apply))
