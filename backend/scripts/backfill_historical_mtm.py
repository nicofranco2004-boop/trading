"""Backfill one-time (CLI): valuación histórica a MERCADO de cuentas importadas.

Problema: una cuenta importada nunca capturó el mark-to-market NO REALIZADO de los
meses pasados (para meses cerrados pnl_unrealized=0 → capital_final ≈ COSTO). Por
eso el chart "Evolución" queda plano y recién "toma el % real" hoy (el salto), y el
CAGR sale bajísimo (p.ej. +2.84% vs +22.43% del broker). El ~22% es apreciación no
realizada que nunca entró en la serie histórica.

Este backfill, por cada mes CERRADO, reconstruye las tenencias a fin de mes (net
BUY−SELL del import_normalized_tx confirmado) y las valúa al precio de MERCADO
histórico, sumando esa apreciación a monthly_entries.capital_final (por-broker +
global) y re-derivando los snapshots que lee el chart.

  capital_final = (capital_inicio + deposits − withdrawals + pnl_realized)  [costo]
                +  Σ (valor_mercado − costo)  de las tenencias              [unrealized]

El primer término se RECOMPUTA de columnas estables cada corrida (idempotente — no
lee el capital_final que esta misma corrida pudo dejar en MTM). El cash ya está en
ese primer término (vía los flujos) → no se reconstruye.

Valuación = port fiel de snapshots_job.compute_broker_value_usd (live):
  - holding USD (broker USD/USDT)            → close USD histórico × qty
  - holding .BA (broker ARS / '· USD' / CEDEAR) → close .BA (ARS) ÷ MEP
  - cripto                                    → close <SYM>-USD histórico × qty
FX histórico: BLUE de fx_rates_daily (último ≤ fin de mes, sin fuga al futuro). MEP:
blue-proxy (Fase 1, sin schema nuevo; para cuentas en USD el FX ni se usa). Regla
cardinal: si falta precio/FX/historia o hay split → AL COSTO (jamás infla).

NO toca: positions, operations, cash, import_normalized_tx. Solo
monthly_entries.capital_final (UPDATE) + snapshots (UPSERT vía el helper de import).
Saltea cuentas sin import confirmado (manuales → no reconstruibles). El mes
calendario EN CURSO no se toca (lo maneja el flujo live).

Uso
───
    python scripts/backfill_historical_mtm.py            # DRY-RUN (sobre copia, no toca nada)
    python scripts/backfill_historical_mtm.py --apply    # aplica + commitea (por user)
    python scripts/backfill_historical_mtm.py --user 42  # una sola cuenta

⚠️  Backup antes de --apply:  python scripts/backup_db.py
"""
from __future__ import annotations

import argparse
import calendar
import math
import os
import sqlite3
import sys
import tempfile
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main                                              # noqa: E402
import snapshots_job as sj                               # noqa: E402
from importing.persister import _backfill_snapshots_from_monthly  # noqa: E402
from importing.recompute_backfill import _clone_db                 # noqa: E402


# ─── Fetch de cierre mensual histórico por símbolo de precio ──────────────────
_HIST_CACHE: dict = {}

def _fetch_monthly_close(price_key: str, start_iso: str) -> dict:
    """{YYYY-MM: close} para un price_key ('AAPL', 'GGAL.BA', 'BTC'), desde start a
    hoy. {} (→ costo) para lo que no tiene historia confiable en yfinance: FCI, bonos
    AR (data912 es live-only), CEDEAR cotizado en USD (BAC, necesita CCL histórico)."""
    ck = (price_key, start_iso)
    if ck in _HIST_CACHE:
        return _HIST_CACHE[ck]
    base = price_key[:-3] if price_key.endswith(".BA") else price_key
    out: dict = {}
    skip = (
        price_key.startswith("FCI:")
        or base in getattr(main, "AR_BONDS_DATA912", set())
        or main._is_data912_bond(base)   # cualquier bono/ON de data912 → costo histórico (data912 es live-only)
        or (price_key.endswith(".BA") and base in getattr(main, "CEDEAR_USD_RATIOS", {}))
    )
    if not skip:
        yf_sym = main.CRYPTO_YF.get(base, price_key) if base in main.CRYPTO_SYMBOLS else price_key
        try:
            import yfinance as yf
            # timeout acotado: una consulta que se cuelga (Yahoo rate-limit) degrada
            # al costo en vez de colgar todo el request de la tanda. Ver el panel de
            # Admin (MtmBackfillPanel) que además reintenta las tandas lentas.
            data = yf.Ticker(yf_sym).history(start=start_iso, interval="1mo", auto_adjust=False, timeout=8)
            if not data.empty:
                for idx, row in data.iterrows():
                    c = row.get("Close")
                    if c is not None and not (isinstance(c, float) and math.isnan(c)):
                        out[idx.strftime("%Y-%m")] = float(c)
        except Exception:
            out = {}
    _HIST_CACHE[ck] = out
    return out


# ─── FX histórico — BLUE de fx_rates_daily (último ≤ fin de mes) ──────────────
def _hist_blue(conn, month_end_iso: str, fallback: float) -> float:
    row = conn.execute(
        "SELECT blue_venta FROM fx_rates_daily WHERE date <= ? ORDER BY date DESC LIMIT 1",
        (month_end_iso,),
    ).fetchone()
    try:
        v = float(row["blue_venta"]) if row and row["blue_venta"] is not None else None
        return v if (v and v > 0) else fallback
    except (TypeError, ValueError):
        return fallback


# ─── Tenencias a fin de mes (net BUY−SELL + costo promedio) ───────────────────
def _holdings_asof(conn, uid: int, date_iso: str) -> list:
    """[{broker, asset, asset_type, quantity, invested(costo)}] tenidas a date_iso.
    qty = Σ BUY − Σ SELL; costo = precio promedio de compra × qty tenida."""
    rows = conn.execute(
        """SELECT n.broker AS broker, n.asset_symbol AS asset, n.asset_type AS asset_type,
                  UPPER(COALESCE(n.currency,'')) AS currency,
                  SUM(CASE n.operation_type WHEN 'BUY'  THEN COALESCE(n.quantity,0)
                                            WHEN 'SELL' THEN -COALESCE(n.quantity,0)
                                            ELSE 0 END) AS qty,
                  SUM(CASE n.operation_type WHEN 'BUY'
                        THEN COALESCE(n.gross_amount, COALESCE(n.quantity,0)*COALESCE(n.unit_price,0))
                        ELSE 0 END) AS buy_amt,
                  SUM(CASE n.operation_type WHEN 'BUY' THEN COALESCE(n.quantity,0) ELSE 0 END) AS buy_qty
             FROM import_normalized_tx n
             JOIN import_batches b ON n.batch_id = b.id
            WHERE b.user_id = ? AND b.status = 'confirmed'
              AND n.asset_symbol IS NOT NULL AND n.asset_symbol != ''
              AND n.operation_type IN ('BUY','SELL')
              AND n.date <= ?
            GROUP BY n.broker, n.asset_symbol, n.asset_type, UPPER(COALESCE(n.currency,''))""",
        (uid, date_iso),
    ).fetchall()
    out = []
    for r in rows:
        qty = r["qty"] or 0
        if qty <= 1e-9:        # cerrada / sobre-vendida → no es tenencia
            continue
        buy_qty = r["buy_qty"] or 0
        avg_cost = (r["buy_amt"] / buy_qty) if buy_qty > 0 else 0
        # currency: para que compute_broker_value_usd respete el costo USD (sin ÷MEP)
        # de bonos/ONs/FCI-USD/CEDEAR-MEP en un broker ARS. Particiona por moneda (un
        # mismo activo con lotes ARS y USD sale en 2 filas, cada una con su costo).
        out.append({
            "broker": r["broker"], "asset": r["asset"], "asset_type": r["asset_type"],
            "currency": (r["currency"] or None), "quantity": qty, "invested": avg_cost * qty,
        })
    return out


def _month_end(year: int, month: int) -> str:
    return _date(year, month, calendar.monthrange(year, month)[1]).isoformat()


# ─── Backfill de un usuario ───────────────────────────────────────────────────
def backfill_user(conn, uid: int, today: _date) -> dict:
    """Devuelve {uid, skipped, reason, months:[{ym, before, after}], cost_fallbacks,
    cash_warning}. NO commitea (lo hace el caller). Idempotente."""
    res = {"uid": uid, "skipped": False, "reason": None, "months": [],
           "cost_fallbacks": 0, "cash_warning": False}

    # Cuenta reconstruible solo si hay import confirmado.
    has_import = conn.execute(
        "SELECT 1 FROM import_batches WHERE user_id=? AND status='confirmed' LIMIT 1", (uid,),
    ).fetchone()
    if not has_import:
        res.update(skipped=True, reason="sin import confirmado (cuenta manual)")
        return res

    me_rows = conn.execute(
        "SELECT year, month FROM monthly_entries WHERE user_id=? AND broker='global' "
        "ORDER BY year, month", (uid,),
    ).fetchall()
    if not me_rows:
        res.update(skipped=True, reason="sin monthly_entries")
        return res

    brokers = [dict(r) for r in conn.execute(
        "SELECT name, currency FROM brokers WHERE user_id=?", (uid,)).fetchall()]
    ars_names, ar_usd_names = sj._broker_name_sets(brokers)
    bcur = {b["name"]: (b["currency"] or "USDT") for b in brokers}

    # Activos con split aplicado → costo (qty actual post-split × precio histórico
    # pre-split inflaría). Conservador: cualquier asset con split_adjusted_through.
    split_assets = set()
    try:
        for r in conn.execute(
            "SELECT DISTINCT asset FROM positions WHERE user_id=? AND split_adjusted_through IS NOT NULL", (uid,)):
            split_assets.add(r["asset"])
    except Exception:
        pass

    cur_ym = (today.year, today.month)         # mes en curso → NO tocar
    start_iso = _month_end(me_rows[0]["year"], me_rows[0]["month"])[:8] + "01"

    for me in me_rows:
        y, m = me["year"], me["month"]
        if (y, m) >= cur_ym:                   # mes en curso / futuro → skip
            continue
        d = _month_end(y, m)
        ym = f"{y}-{m:02d}"
        hold = _holdings_asof(conn, uid, d)
        try:
            live_blue = main._user_tc_blue(conn, uid)
        except Exception:
            live_blue = 1415.0
        blue = _hist_blue(conn, d, live_blue)
        mep = blue                              # Fase 1: MEP = blue-proxy

        # Unrealized por broker (valor_mercado − costo), con guardas → costo.
        unreal_by_broker: dict = {}
        for h in hold:
            b = h["broker"]
            btype = bcur.get(b, "USDT")
            pkey = sj.position_price_key(
                {"asset": h["asset"], "broker": b, "asset_type": h["asset_type"]},
                ars_names, ar_usd_names)
            # precio histórico del mes (None si no hay / split → costo)
            price = None
            if h["asset"] not in split_assets:
                hist = _fetch_monthly_close(pkey, start_iso)
                price = hist.get(ym)
            prices = {pkey: price} if price is not None else {}
            r = sj.compute_broker_value_usd(
                [h], prices, btype, blue, broker_name=b, cedear_rate=mep)
            val = r.get("value", 0) or 0
            inv = r.get("invested", 0) or 0
            u = val - inv
            # ── Guard anti-distorsión (espejo de trustMktValue del front) ─────────
            # Si el valor a mercado se va absurdamente lejos del costo, NO lo
            # confiamos → degradamos a costo (u=0). Atrapa precios per-100 de bonos,
            # colisiones de ticker, y cross-currency mal valuado que si no metían un
            # capital_final NEGATIVO gigante (ej: 485 → -592.944). Renta fija cotiza
            # cerca de par → banda estrecha [0.02×, 4×]; el resto permite multibaggers
            # reales → [0.002×, 50×]. Un valor ≤ 0 con costo > 0 es siempre bug.
            trusted = True
            if val < 0:
                trusted = False                 # valor de mercado < 0 = SIEMPRE bug
                                                # (incluso con costo 0 → free lots)
            elif inv > 0:
                _fixed = (h.get("asset_type") or "").upper() in (
                    "BOND", "BONO", "ON", "LETRA", "LECAP")
                _mult = val / inv
                _lo, _hi = (0.02, 4.0) if _fixed else (0.002, 50.0)
                if _mult < _lo or _mult > _hi:
                    trusted = False
            if not trusted:
                u = 0.0                         # precio no confiable → costo
            unreal_by_broker[b] = unreal_by_broker.get(b, 0.0) + u
            if price is None or not trusted:
                res["cost_fallbacks"] += 1

        total_unreal = sum(unreal_by_broker.values())

        # Escribir capital_final = costo(recomputado) + unrealized, por-broker + global.
        rows = conn.execute(
            "SELECT broker, capital_inicio, deposits, withdrawals, pnl_realized, capital_final "
            "FROM monthly_entries WHERE user_id=? AND year=? AND month=?", (uid, y, m)).fetchall()
        before_global = after_global = 0.0
        for row in rows:
            b = row["broker"]
            cost = ((row["capital_inicio"] or 0) + (row["deposits"] or 0)
                    - (row["withdrawals"] or 0) + (row["pnl_realized"] or 0))
            u = total_unreal if b == "global" else unreal_by_broker.get(b, 0.0)
            new_cf = cost + u
            # Clamp definitivo: el MTM NUNCA debe DEJAR un capital_final negativo por
            # culpa de la valuación, ni EMPEORAR uno que ya venía negativo.
            #   • costo sano (≥0) que el unrealized flipearía a negativo → al costo
            #     (ej #417: 485 → -592k → 485; cross-currency / free lots mal valuados).
            #   • costo YA negativo (corrupción vieja de pnl_realized, ej #725/#791): el
            #     MTM no puede empeorarlo → nos quedamos en el MENOS negativo entre costo
            #     y resultado (max). Si el unrealized lo MEJORA (lo acerca a 0 o lo cruza
            #     a positivo), eso sí se respeta.
            # Los corruptos siguen rotos: el costo en sí está mal → es otro fix.
            if new_cf < 0:
                new_cf = max(cost, new_cf)
            conn.execute(
                "UPDATE monthly_entries SET capital_final=? WHERE user_id=? AND broker=? AND year=? AND month=?",
                (new_cf, uid, b, y, m))
            if b == "global":
                before_global = row["capital_final"] or 0
                after_global = new_cf
        res["months"].append({"ym": ym, "before": before_global, "after": after_global})

    # Re-derivar snapshots desde global.capital_final (lo que lee el chart).
    _backfill_snapshots_from_monthly(conn, uid)
    return res


# ─── Engine para el endpoint admin (resumen estructurado) ────────────────────
def backfill_summary(real_conn, users, today, apply: bool) -> dict:
    """Corre el backfill MTM sobre `users` y devuelve un resumen estructurado para el
    panel de Admin. apply=False → sobre una COPIA del DB (la real NO se toca);
    apply=True → commitea por user. Espeja recompute_backfill.run_backfill/dry_run."""
    def _loop(conn):
        out = {"users_changed": 0, "skipped": 0, "changes": [], "errors": []}
        for uid in users:
            try:
                s = backfill_user(conn, uid, today)
            except Exception as ex:
                conn.rollback()
                out["errors"].append({"uid": uid, "error": str(ex)})
                continue
            if s["skipped"]:
                out["skipped"] += 1
                continue
            changed = [m for m in s["months"] if abs(m["after"] - m["before"]) > 0.01]
            if changed:
                out["users_changed"] += 1
                first, last = changed[0], changed[-1]
                out["changes"].append({
                    "uid": uid, "months_changed": len(changed),
                    "first_ym": first["ym"], "first_before": round(first["before"], 2), "first_after": round(first["after"], 2),
                    "last_ym": last["ym"], "last_before": round(last["before"], 2), "last_after": round(last["after"], 2),
                    "cost_fallbacks": s["cost_fallbacks"],
                })
            if apply:
                conn.commit()
        return out

    if apply:
        return _loop(real_conn)
    with _clone_db(real_conn) as clone:
        return _loop(clone)


# ─── Runner CLI (dry-run sobre copia / --apply commitea por user) ──────────────
def _run_on(conn, users, today, apply):
    summaries = []
    for uid in users:
        try:
            s = backfill_user(conn, uid, today)
            summaries.append(s)
            if apply and not s["skipped"]:
                conn.commit()
        except Exception as ex:
            conn.rollback()
            summaries.append({"uid": uid, "skipped": True, "reason": f"ERROR {ex}",
                              "months": [], "cost_fallbacks": 0, "cash_warning": False})
    return summaries


def _print(summaries, apply):
    changed = 0
    for s in summaries:
        if s["skipped"]:
            print(f"  uid={s['uid']:<5} SKIP — {s['reason']}")
            continue
        months = [m for m in s["months"] if abs(m["after"] - m["before"]) > 0.01]
        if not months:
            print(f"  uid={s['uid']:<5} sin cambios ({s['cost_fallbacks']} holding-meses al costo)")
            continue
        changed += 1
        first, last = s["months"][0], s["months"][-1]
        print(f"  uid={s['uid']:<5} {len(months)} meses con MTM · "
              f"global {first['ym']}: {first['before']:,.0f}→{first['after']:,.0f} … "
              f"{last['ym']}: {last['before']:,.0f}→{last['after']:,.0f} "
              f"({s['cost_fallbacks']} holding-meses al costo)")
    print(f"\n== {'Aplicado' if apply else 'Simulado (copia)'}: {changed} usuarios con MTM histórico ==")
    if not apply and changed:
        print("   Revisá y re-corré con --apply. Backup antes: python scripts/backup_db.py")


def run(apply: bool, only_uid=None) -> int:
    from datetime import datetime
    today = datetime.utcnow().date()
    real = main.get_db()
    try:
        if only_uid is not None:
            users = [only_uid]
        else:
            users = [r["id"] for r in real.execute("SELECT id FROM users ORDER BY id")]
        mode = "APLICANDO (commit por user)" if apply else "DRY-RUN (sobre copia — no toca nada)"
        print(f"== Backfill MTM histórico · {mode} · {len(users)} usuarios ==\n")
        if apply:
            summaries = _run_on(real, users, today, apply=True)
        else:
            with _clone_db(real) as clone:
                summaries = _run_on(clone, users, today, apply=False)
        _print(summaries, apply)
    finally:
        real.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill: valuación histórica a mercado (MTM) sin re-import.")
    ap.add_argument("--apply", action="store_true", help="aplica y commitea (default: dry-run sobre copia)")
    ap.add_argument("--user", type=int, default=None, help="solo este user_id")
    args = ap.parse_args()
    sys.exit(run(args.apply, args.user))
