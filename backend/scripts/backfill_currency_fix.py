"""Backfill de corrección de MONEDA para las cuentas con capital negativo gigante.

Las cuentas viejas tienen `import_normalized_tx` envenenado: pesos contados como
dólares (×~tc_blue) por tres mecanismos ya fixeados en los parsers pero que NO se
pueden re-aplicar retroactivamente (el archivo original no se guarda). Este backfill
CORRIGE las filas guardadas in-place y re-rebuildea (verificado: corregir la moneda
del log + recompute recupera el estado correcto al centavo — el rebuild re-lee
import_normalized_tx).

Tres correcciones (todas SOLO USD→ARS, nunca al revés; conservadoras):
  1. FCI money-market peso mal-etiquetado USD (Balanz): clase FUND + USD + VCP > 5.
     (USD money-market ≈ 1, peso ≥ 6 — gap limpio verificado en exports reales.)
  2. Retiro/depósito SINTÉTICO del seed peso-escala (notes "sintético" + USD/USDT +
     gross_amount_usd peso-escala): re-stampeamos ÷tc_blue.
  3. Conducto dólar-MEP con bono (Cocos): par BUY/SELL del MISMO ticker+|cantidad|,
     ambos USD, con precio_compra >> precio_venta (ratio ≈ tc_blue) → la pata BUY es
     el costo en PESOS → ARS.

apply=False → corre sobre una COPIA del DB (dry-run, no toca nada). apply=True →
commitea por usuario. Idempotente (re-correr no vuelve a tocar lo ya en ARS).
"""
from __future__ import annotations
from typing import Dict, List, Any, Callable

import main
from importing import persister as _persister
from importing.recompute_backfill import recompute_user, _clone_db


# Un VCP (cuotaparte) por encima de esto es PESOS; un FCI USD money-market queda ≈ 1.
_FCI_PESO_VCP_MIN = 5.0
# Un gross_amount en "USD" por encima de esto, en una fila sintética/conducto, es
# casi seguro pesos (nadie mueve millones de dólares en un retiro sintético).
_PESO_SCALE_USD_MIN = 50_000.0
# Ratio precio_compra/precio_venta de un conducto (≈ el dólar): usamos un piso amplio.
_CONDUIT_PRICE_RATIO_MIN = 100.0


def _confirmed_batches(conn, uid: int) -> List[str]:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'", (uid,)).fetchall()]


def correct_currency(conn, uid: int, tc_blue: float) -> Dict[str, int]:
    """Corrige in-place las filas envenenadas de import_normalized_tx del usuario.
    Devuelve el conteo por tipo de corrección. NO commitea (lo hace el caller)."""
    batches = _confirmed_batches(conn, uid)
    if not batches:
        return {"fci": 0, "seed": 0, "conduit": 0}
    ph = ",".join("?" * len(batches))
    blue = tc_blue if tc_blue and tc_blue > 0 else 1.0
    counts = {"fci": 0, "seed": 0, "conduit": 0}
    # Fondos FCI que la regla (1) toca — para EXPONERLOS en el dry-run: el riesgo es
    # un FCI USD de equity (VCP>5 legítimo) colado. El humano verifica que todos sean
    # money-market peso (RFPESOS/DOLINKA/…) antes de aplicar. {symbol: {count,vcp_min,vcp_max,max_amt}}
    fci_funds: Dict[str, Dict[str, float]] = {}

    # (1) FCI money-market peso mal-etiquetado USD → ARS + re-stamp ÷blue.
    cur = conn.execute(
        f"""SELECT id, asset_symbol, unit_price, gross_amount FROM import_normalized_tx
             WHERE batch_id IN ({ph}) AND asset_type='FUND'
               AND UPPER(COALESCE(currency,''))IN('USD','USDT')
               AND unit_price IS NOT NULL AND unit_price > ?""",
        (*batches, _FCI_PESO_VCP_MIN)).fetchall()
    for r in cur:
        conn.execute(
            "UPDATE import_normalized_tx SET currency='ARS', gross_amount_usd=? WHERE id=?",
            (round((r["gross_amount"] or 0) / blue, 4), r["id"]))
        sym = r["asset_symbol"] or "?"
        vcp = float(r["unit_price"] or 0)
        amt = abs(float(r["gross_amount"] or 0))
        f = fci_funds.setdefault(sym, {"count": 0, "vcp_min": vcp, "vcp_max": vcp, "max_amt": 0.0})
        f["count"] += 1
        f["vcp_min"] = min(f["vcp_min"], vcp)
        f["vcp_max"] = max(f["vcp_max"], vcp)
        f["max_amt"] = max(f["max_amt"], amt)
    counts["fci"] = len(cur)

    # (2) Retiro/depósito SINTÉTICO del seed peso-escala → re-stamp gross_amount_usd ÷blue.
    #     (No le cambiamos la moneda — la pata dólar-MEP es real; solo arreglamos el
    #      monto USD que se contó 1:1 desde un total compuesto en pesos.)
    cur = conn.execute(
        f"""SELECT id, gross_amount FROM import_normalized_tx
             WHERE batch_id IN ({ph})
               AND (LOWER(COALESCE(notes,'')) LIKE '%sintétic%' OR LOWER(COALESCE(notes,'')) LIKE '%estado inicial%')
               AND UPPER(COALESCE(currency,'')) IN ('USD','USDT')
               AND ABS(COALESCE(gross_amount_usd, gross_amount, 0)) > ?""",
        (*batches, _PESO_SCALE_USD_MIN)).fetchall()
    for r in cur:
        conn.execute("UPDATE import_normalized_tx SET gross_amount_usd=? WHERE id=?",
                     (round((r["gross_amount"] or 0) / blue, 4), r["id"]))
    counts["seed"] = len(cur)

    # (3) Conducto dólar-MEP con bono: par BUY/SELL mismo ticker+|cantidad|, ambos USD,
    #     precio_compra >> precio_venta (≈ blue) → la pata BUY es el COSTO en pesos → ARS.
    rows = conn.execute(
        f"""SELECT id, asset_symbol, operation_type, quantity, unit_price, gross_amount
             FROM import_normalized_tx
             WHERE batch_id IN ({ph}) AND operation_type IN ('BUY','SELL')
               AND UPPER(COALESCE(currency,'')) IN ('USD','USDT')
               AND asset_symbol IS NOT NULL AND quantity IS NOT NULL AND unit_price IS NOT NULL""",
        tuple(batches)).fetchall()
    sells = {}  # (asset, round(|qty|)) → min sell unit_price
    for r in rows:
        if r["operation_type"] == "SELL":
            k = (r["asset_symbol"], round(abs(r["quantity"] or 0), 2))
            up = r["unit_price"] or 0
            if up > 0 and (k not in sells or up < sells[k]):
                sells[k] = up
    for r in rows:
        if r["operation_type"] != "BUY":
            continue
        k = (r["asset_symbol"], round(abs(r["quantity"] or 0), 2))
        sp = sells.get(k)
        bp = r["unit_price"] or 0
        if sp and sp > 0 and bp > 0 and (bp / sp) >= _CONDUIT_PRICE_RATIO_MIN:
            conn.execute(
                "UPDATE import_normalized_tx SET currency='ARS', gross_amount_usd=? WHERE id=?",
                (round((r["gross_amount"] or 0) / blue, 4), r["id"]))
            counts["conduit"] += 1

    return counts, fci_funds


def backfill_user(conn, uid: int, *, recalc: Callable, min_capital: float = -50000.0) -> Dict[str, Any]:
    """Corrige la moneda + recompute. NO commitea. Devuelve resumen con before/after
    del peor capital_final global.

    GATE de seguridad: solo toca cuentas con capital_final AFECTADO (peor global <
    min_capital). Una cuenta SANA (ej con un FCI USD de equity VCP>5 legítimo) NO se
    toca → limita el blast-radius del falso positivo de la regla FCI a cuentas que ya
    están rotas por el peso-como-dólar (nunca corrompe una sana)."""
    res = {"uid": uid, "skipped": False, "corrections": {"fci": 0, "seed": 0, "conduit": 0},
           "worst_before": None, "worst_after": None, "fci_funds": {}}
    if not _confirmed_batches(conn, uid):
        res["skipped"] = True
        return res
    worst = conn.execute(
        "SELECT MIN(capital_final) m FROM monthly_entries WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    res["worst_before"] = round((worst["m"] or 0), 2) if worst else None
    # Gate: solo cuentas afectadas (capital negativo gigante). Las sanas se saltean.
    if res["worst_before"] is None or res["worst_before"] >= min_capital:
        res["skipped"] = True
        res["worst_after"] = res["worst_before"]
        return res

    tc_blue = _persister._read_tc_blue(conn, uid)
    res["corrections"], res["fci_funds"] = correct_currency(conn, uid, tc_blue)
    if sum(res["corrections"].values()) == 0:
        res["worst_after"] = res["worst_before"]
        return res
    recompute_user(conn, uid, recalc=recalc)

    worst = conn.execute(
        "SELECT MIN(capital_final) m FROM monthly_entries WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    res["worst_after"] = round((worst["m"] or 0), 2) if worst else None
    return res


def backfill_summary(real_conn, users, apply: bool, recalc: Callable,
                     min_capital: float = -50000.0) -> Dict[str, Any]:
    """apply=False → sobre COPIA del DB (no toca nada). apply=True → commitea por user.
    Solo toca cuentas con peor capital_final < min_capital (gate anti-falso-positivo)."""
    def _loop(conn):
        out = {"users_changed": 0, "skipped": 0, "changes": [], "errors": [],
               "fci_funds_touched": {}}
        for uid in users:
            try:
                s = backfill_user(conn, uid, recalc=recalc, min_capital=min_capital)
            except Exception as ex:
                conn.rollback()
                out["errors"].append({"uid": uid, "error": str(ex)})
                continue
            if s["skipped"]:
                out["skipped"] += 1
                continue
            total = sum(s["corrections"].values())
            if total > 0:
                out["users_changed"] += 1
                out["changes"].append({
                    "uid": uid, "corrections": s["corrections"], "total_rows": total,
                    "worst_before": s["worst_before"], "worst_after": s["worst_after"],
                    "delta": round((s["worst_after"] or 0) - (s["worst_before"] or 0), 2),
                })
                # Agregar los fondos FCI tocados (para verificación humana: ¿todos money-market?).
                for sym, f in (s.get("fci_funds") or {}).items():
                    g = out["fci_funds_touched"].setdefault(
                        sym, {"count": 0, "vcp_min": f["vcp_min"], "vcp_max": f["vcp_max"], "max_amt": 0.0})
                    g["count"] += f["count"]
                    g["vcp_min"] = min(g["vcp_min"], f["vcp_min"])
                    g["vcp_max"] = max(g["vcp_max"], f["vcp_max"])
                    g["max_amt"] = max(g["max_amt"], f["max_amt"])
            if apply:
                conn.commit()
        out["changes"].sort(key=lambda c: c["worst_before"] or 0)
        return out

    if apply:
        return _loop(real_conn)
    with _clone_db(real_conn) as clone:
        return _loop(clone)
