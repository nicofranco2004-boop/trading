"""builders.dashboard — context packet del Dashboard.
═══════════════════════════════════════════════════════════════════════════
Devuelve un dict (~400-600 tokens serializados) que captura el estado del
portfolio "ahora" + qué cambió en los últimos 30 días + sesgo dominante.

Sin lecturas externas en este file: todo va a través de helpers ya
existentes (behavioral, wrapped) y queries a la DB que el caller pasa.

Shape del packet (estable — cambios acá invalidan el cache existente):
{
  "screen": "dashboard",
  "period": "30d",
  "portfolio": {
    "value_usd": int,
    "twr_30d_pct": float,           # decimal, ej 0.032 = +3.2%
    "twr_lifetime_pct": float|null,
    "delta_30d_usd": float|null,    # value_now - value_30d_ago
    "best_position": {"asset": str, "pnl_pct": float} | null,
    "worst_position": {"asset": str, "pnl_pct": float} | null,
    "cash_pct": float,
    "positions_count": int,
  },
  "benchmarks": {                    # diferencia en puntos porcentuales
    "vs_sp500_30d_pp": float|null,
    "vs_inflation_ar_30d_pp": float|null,
  },
  "behavioral": {                    # solo el sesgo dominante
    "dominant_code": str|null,       # ej 'overtrade'
    "severity": str|null,            # 'high'|'medium'|'low'|'positive'|'neutral'
    "one_liner": str|null,
  },
  "anomalies": [str],                # flags accionables, ej 'concentration_top1_28pct'
}
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List


def _safe_round(v, decimals: int = 4):
    """Redondea floats, deja None y otros tipos como están."""
    try:
        return round(float(v), decimals)
    except (TypeError, ValueError):
        return None


def _compute_pnl_pct_for_position(p: dict, prices: dict, is_ar: bool, tc_blue: float) -> Optional[float]:
    """% de P/L de una posición individual. Returns decimal (0.32 = 32%)."""
    if p.get("is_cash"):
        return None
    qty = p.get("quantity") or 0
    invested = p.get("invested") or 0
    if invested <= 0 or qty <= 0:
        return None
    if is_ar:
        price = p.get("price_override") or prices.get(f"{p.get('asset')}.BA")
        if not price:
            return None
        value_usd = (price * qty) / tc_blue
        invested_usd = invested / tc_blue
    else:
        price = p.get("price_override") or prices.get(p.get("asset"))
        if not price:
            return None
        value_usd = price * qty
        invested_usd = invested
    if invested_usd <= 0:
        return None
    return (value_usd - invested_usd) / invested_usd


def build(conn, user_id: int, period: str = "30d") -> Dict[str, Any]:
    """Construye el packet del Dashboard para `user_id`.

    Hace todas las queries acá adentro para mantener el builder autosuficiente.
    El caller solo necesita pasar `conn` (sqlite3.Connection) y `user_id`.

    `period` está fijo en '30d' por ahora — futura expansión a '90d' / '1y'.
    """
    from datetime import datetime, timedelta
    from collections import Counter

    # ─── Pull data ────────────────────────────────────────────────────────
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]
    brokers = [dict(r) for r in conn.execute(
        "SELECT * FROM brokers WHERE user_id=?", (user_id,)
    ).fetchall()]
    monthly = [dict(r) for r in conn.execute(
        "SELECT * FROM monthly_entries WHERE user_id=? AND broker='global' "
        "ORDER BY year, month",
        (user_id,)
    ).fetchall()]
    snapshots = [dict(r) for r in conn.execute(
        "SELECT date, total_value FROM snapshots WHERE user_id=? "
        "ORDER BY date DESC LIMIT 90",
        (user_id,)
    ).fetchall()]

    # tc_blue (precio del dolar) — fallback 1
    # config es tabla key-value (key, value, user_id), no columnas
    tc_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (user_id,)
    ).fetchone()
    try:
        tc_blue = float(tc_row["value"]) if tc_row and tc_row["value"] else 1
    except (TypeError, ValueError):
        tc_blue = 1
    if tc_blue <= 0:
        tc_blue = 1

    # ─── Prices: fetch desde cache para non-cash positions ────────────────
    prices: Dict[str, float] = {}
    try:
        from home.market import _fetch_batch_quotes
        ars_brokers = {b["name"] for b in brokers if b.get("currency") == "ARS"}
        symbols = set()
        for p in positions:
            if p.get("is_cash") or not p.get("asset"):
                continue
            if p.get("broker") in ars_brokers:
                symbols.add(f"{p['asset']}.BA")
            else:
                symbols.add(p["asset"])
        if symbols:
            quotes = _fetch_batch_quotes(list(symbols))
            prices = {s: q["price"] for s, q in quotes.items() if q and q.get("price")}
    except Exception:
        prices = {}

    # ─── Compute portfolio value + per-position P/L ───────────────────────
    ars_broker_names = {b["name"] for b in brokers if b.get("currency") == "ARS"}
    total_value_usd = 0.0
    cash_usd = 0.0
    position_pnls: List[Dict[str, Any]] = []

    for p in positions:
        is_ar = p.get("broker") in ars_broker_names
        if p.get("is_cash"):
            invested = p.get("invested") or 0
            value_usd = invested / tc_blue if is_ar else invested
            cash_usd += value_usd
            total_value_usd += value_usd
            continue
        qty = p.get("quantity") or 0
        invested = p.get("invested") or 0
        if is_ar:
            price = p.get("price_override") or prices.get(f"{p['asset']}.BA")
            value_usd = (price * qty) / tc_blue if price else invested / tc_blue
        else:
            price = p.get("price_override") or prices.get(p.get("asset"))
            value_usd = price * qty if price else invested
        total_value_usd += value_usd

        pnl_pct = _compute_pnl_pct_for_position(p, prices, is_ar, tc_blue)
        if pnl_pct is not None:
            position_pnls.append({"asset": p["asset"], "pnl_pct": pnl_pct, "weight": value_usd})

    cash_pct = (cash_usd / total_value_usd) if total_value_usd > 0 else 0

    # best / worst position por P/L%
    position_pnls.sort(key=lambda x: x["pnl_pct"], reverse=True)
    best = position_pnls[0] if position_pnls else None
    worst = position_pnls[-1] if position_pnls else None

    # ─── 30d delta desde snapshots ────────────────────────────────────────
    # snapshots vienen DESC. Tomamos el más viejo dentro de 30d y el más reciente.
    twr_30d_pct = None
    delta_30d_usd = None
    if snapshots:
        # ordenar ascendente para tomar primero y último
        sorted_snaps = sorted(snapshots, key=lambda s: s["date"])
        cutoff = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
        in_window = [s for s in sorted_snaps if s["date"] >= cutoff]
        if len(in_window) >= 2 and in_window[0]["total_value"]:
            start_val = float(in_window[0]["total_value"])
            end_val = float(in_window[-1]["total_value"])
            if start_val > 0:
                twr_30d_pct = (end_val - start_val) / start_val
                delta_30d_usd = end_val - start_val

    # ─── TWR lifetime desde monthly_entries (mismo cálculo que /goals/cagr) ──
    twr_lifetime_pct = None
    if len(monthly) >= 2:
        prod = 1.0
        for m in monthly:
            ci = m.get("capital_inicio") or 0
            cf = m.get("capital_final") or 0
            net = (m.get("deposits") or 0) - (m.get("withdrawals") or 0)
            if ci <= 0:
                continue
            ret = (cf - ci - net) / ci
            ret = max(-0.95, min(5.0, ret))
            prod *= (1 + ret)
        twr_lifetime_pct = prod - 1

    # ─── Benchmarks 30d (S&P 500 + inflación AR) ──────────────────────────
    vs_sp500_pp = None
    vs_inflation_pp = None
    try:
        from main import _bench_cache
        data = (_bench_cache.get("data") or {})
        # S&P: comparar último cierre vs cierre ~30d atrás (de la serie mensual)
        sp = data.get("sp500") or {}
        if sp and twr_30d_pct is not None:
            sorted_keys = sorted(sp.keys())
            if len(sorted_keys) >= 2:
                last = sp[sorted_keys[-1]]
                prev = sp[sorted_keys[-2]]
                if prev > 0:
                    sp_30d_pct = (last / prev) - 1
                    vs_sp500_pp = twr_30d_pct - sp_30d_pct
        # Inflación AR del último mes disponible
        infl = data.get("inflation_ar") or {}
        if infl and twr_30d_pct is not None:
            sorted_keys = sorted(infl.keys())
            if sorted_keys:
                last_infl = infl[sorted_keys[-1]] / 100  # viene en %, ej 4.5 → 0.045
                vs_inflation_pp = twr_30d_pct - last_infl
    except Exception:
        pass

    # ─── Behavioral: solo el sesgo dominante ──────────────────────────────
    dominant_code = None
    severity = None
    bias_one_liner = None
    try:
        from behavioral import build_behavioral_insights
        ops = [dict(r) for r in conn.execute(
            "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC", (user_id,)
        ).fetchall()]
        inflation_monthly = {}
        try:
            from main import _bench_cache
            inflation_monthly = (_bench_cache.get("data") or {}).get("inflation_ar") or {}
        except Exception:
            pass
        cards = build_behavioral_insights(
            ops, positions, prices, inflation_monthly, tc_blue
        ).get("cards") or []
        # Ranking de severidad
        rank = {"high": 4, "medium": 3, "low": 2, "positive": 1, "neutral": 0}
        flagged = [c for c in cards if not c.get("insufficient_data")]
        flagged.sort(key=lambda c: rank.get(c.get("severity"), 0), reverse=True)
        if flagged:
            top = flagged[0]
            dominant_code = top.get("code")
            severity = top.get("severity")
            bias_one_liner = top.get("one_liner")
    except Exception:
        pass

    # ─── Anomalías auto-detectadas ────────────────────────────────────────
    anomalies: List[str] = []
    if best and best["weight"] and total_value_usd > 0:
        top1_pct = best["weight"] / total_value_usd
        if top1_pct > 0.25:
            anomalies.append(f"concentration_top1_{int(top1_pct * 100)}pct")
    if cash_pct > 0.30:
        anomalies.append(f"high_cash_{int(cash_pct * 100)}pct")
    if twr_30d_pct is not None and twr_30d_pct < -0.05:
        anomalies.append("drawdown_30d_high")

    # ─── Compose final packet ─────────────────────────────────────────────
    return {
        "screen": "dashboard",
        "period": period,
        "portfolio": {
            "value_usd": int(round(total_value_usd)),
            "twr_30d_pct": _safe_round(twr_30d_pct, 4),
            "twr_lifetime_pct": _safe_round(twr_lifetime_pct, 4),
            "delta_30d_usd": _safe_round(delta_30d_usd, 0),
            "best_position": (
                {"asset": best["asset"], "pnl_pct": _safe_round(best["pnl_pct"], 4)}
                if best else None
            ),
            "worst_position": (
                {"asset": worst["asset"], "pnl_pct": _safe_round(worst["pnl_pct"], 4)}
                if worst and worst is not best else None
            ),
            "cash_pct": _safe_round(cash_pct, 3),
            "positions_count": len([p for p in positions if not p.get("is_cash")]),
        },
        "benchmarks": {
            "vs_sp500_30d_pp": _safe_round(vs_sp500_pp, 4),
            "vs_inflation_ar_30d_pp": _safe_round(vs_inflation_pp, 4),
        },
        "behavioral": {
            "dominant_code": dominant_code,
            "severity": severity,
            "one_liner": bias_one_liner,
        },
        "anomalies": anomalies,
    }
