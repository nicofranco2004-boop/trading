"""builders.insights — packet del screen "Insights".
═══════════════════════════════════════════════════════════════════════════
Topic: insights

El screen Insights es el análisis profundo: performance acumulada, riesgo
(drawdown), atribución por activo, vs benchmarks (S&P 500 + inflación AR).
La página calcula casi todo en el frontend — acá rehacemos los números
clave en Python con los mismos datos crudos (snapshots, monthly,
operations, positions) para no depender del frontend.

Mantenemos el packet lean (~1.2KB): TWR del período, drawdown actual y
máximo, top 3 contributors / detractors (P&L absoluto), win rate, exposure
mix, vs benchmarks.

Shape:
{
  "screen": "insights",
  "window_days": 365,
  "twr_pct": float | null,           # rendimiento acumulado del período
  "twr_realized_pct": float | null,  # solo P/L cerrado
  "vs_benchmarks": {
    "sp500_pct": float | null,
    "inflation_ar_pct": float | null,
    "delta_sp500_pp": float | null,  # tu return - SPY return (puntos %)
    "delta_inflation_pp": float | null,
  },
  "drawdown": {
    "current_pct": float,           # caída actual desde peak
    "max_pct": float,                # peor caída del período
    "days_since_peak": int | null,
  },
  "trades": {
    "closed_count": int,
    "winners_count": int,
    "losers_count": int,
    "win_rate": float,               # 0-1
    "best_trade_pct": float | null,
    "worst_trade_pct": float | null,
  },
  "attribution": {
    "top_contributors": [{ "ticker": str, "pnl_usd": float, "pnl_pct": float }],
    "top_detractors":   [{ "ticker": str, "pnl_usd": float, "pnl_pct": float }],
  },
  "exposure": {
    "cash_pct": float,
    "ar_pct": float,                 # % en activos AR (panel local)
    "us_pct": float,                 # % en US (Schwab + CEDEARs)
    "crypto_pct": float,
  },
}
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import date, datetime


_AR_BROKERS = {"cocos", "iol", "bull", "balanz", "naranja", "pppi", "invertironline", "lemon"}
_CRYPTO_HINT = {"BTC", "ETH", "USDT", "USDC", "AAVE", "SOL", "AVAX", "DOT", "DOGE", "ADA", "XRP", "LINK", "BNB"}

# Panel local AR — acciones argentinas (Merval). Lo que esté en un broker AR
# pero NO en esta lista lo tratamos como exposure US (CEDEAR). El criterio:
# para análisis de IA, un CEDEAR de MSFT es exposure US, no AR — el CEDEAR
# es solo el wrapper local.
_AR_LOCAL_TICKERS = {
    # Bancos y financieras
    "BMA", "GGAL", "BBAR", "BHIP", "SUPV", "VALO",
    # Energía / utilities
    "YPFD", "YPF", "TGSU2", "TGNO4", "CEPU", "EDN", "PAMP", "TRAN",
    "METR", "DGCU2", "DGCE", "COME", "AGRO",
    # Materiales / industrial / consumo
    "ALUA", "TXAR", "MIRG", "CRES", "CGPA2", "MOLI", "MOLA", "LOMA",
    "HARG", "GCDI", "GCLA", "SAMI", "FIPL", "GARO", "OEST",
    # Telecom / tech AR
    "TECO2", "BYMA", "GBAN", "AUSO",
    # Real estate / agropecuario
    "IRSA", "IRS", "MIRG", "CTIO", "INVJ", "MORI", "FERR",
    # Aerolíneas / transporte
    "TRAN", "TGN0", "AUSO",
}

# Bonos soberanos AR — prefijos (AL, GD, AE, etc.)
_AR_BOND_PREFIXES = ("AL", "GD", "AE", "TX", "TZ", "PARY", "DICY", "TZX", "TO", "T2X")


def _parse_date(s):
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except (TypeError, ValueError):
        return None


def _compute_drawdown(values: List[float]) -> Dict[str, Any]:
    """Drawdown sobre serie de valores. No es TWRR — solo MV/peak, suficiente
    para la narrativa. Devuelve current_pct, max_pct, days_since_peak."""
    if not values or len(values) < 2:
        return {"current_pct": 0.0, "max_pct": 0.0, "days_since_peak": None}

    peak = values[0]
    peak_idx = 0
    max_dd = 0.0
    for i, v in enumerate(values):
        if v > peak:
            peak = v
            peak_idx = i
        if peak > 0:
            dd = (v - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd

    current = values[-1]
    current_dd = ((current - peak) / peak * 100) if peak > 0 else 0.0
    days_since_peak = (len(values) - 1) - peak_idx
    return {
        "current_pct": round(current_dd, 2),
        "max_pct": round(max_dd, 2),
        "days_since_peak": days_since_peak,
    }


def _classify_geography(asset: str, broker: str) -> str:
    """ar | us | crypto — para exposure breakdown.

    Lógica:
    - Crypto: ticker en hint list o broker = binance.
    - AR real: ticker en panel local AR o bono soberano (AL, GD, etc.).
    - US: el resto, INCLUYE los CEDEARs (asset US-listed en broker AR).
      Económicamente un CEDEAR de MSFT es exposure US, no AR — solo el
      wrapper es local. Esa es la lectura útil para el LLM.
    """
    a = (asset or "").upper().strip()
    b = (broker or "").lower().strip()
    if a in _CRYPTO_HINT or b == "binance":
        return "crypto"
    if a in _AR_LOCAL_TICKERS or a.startswith(_AR_BOND_PREFIXES):
        return "ar"
    # CEDEARs en broker AR + acciones US en broker US → US exposure
    return "us"


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    window_days = int(kwargs.get("window_days", 365))
    today = date.today()

    # ── 1. Snapshots para TWR + drawdown ─────────────────────────────────────
    rows = conn.execute(
        """SELECT date, total_value, net_deposited
             FROM snapshots
            WHERE user_id = ? ORDER BY date ASC""",
        (user_id,),
    ).fetchall()
    snaps = [dict(r) for r in rows]
    # Filtrar al window
    cutoff = today.toordinal() - window_days
    window_snaps = [
        s for s in snaps
        if _parse_date(s["date"]) and _parse_date(s["date"]).toordinal() >= cutoff
    ]
    values = [float(s["total_value"] or 0) for s in window_snaps if s["total_value"] is not None]

    # TWR via monthly_entries (broker='global') — el backend ya guarda capital
    # inicio/final por mes con flujos neteados. Compoundeamos los % mensuales
    # para el período. Es mucho más confiable que computar TWR sobre snapshots
    # crudos porque net_deposited se popula retroactivamente al importar
    # operations y eso rompe el cálculo basado en deltas.
    twr_pct: Optional[float] = None
    try:
        from datetime import timedelta
        cutoff_date = today - timedelta(days=window_days)
        m_rows = conn.execute(
            """SELECT year, month, capital_inicio, capital_final, deposits, withdrawals
                 FROM monthly_entries
                WHERE user_id=? AND broker='global'
                ORDER BY year, month""",
            (user_id,),
        ).fetchall()
        compound = 1.0
        used = 0
        for r in m_rows:
            y, m = r["year"], r["month"]
            try:
                end_of_month = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
            except ValueError:
                continue
            if end_of_month < cutoff_date:
                continue
            ci = float(r["capital_inicio"] or 0)
            cf = float(r["capital_final"] or 0)
            dep = float(r["deposits"] or 0)
            wd = float(r["withdrawals"] or 0)
            # Retorno mensual aislando flujos: (cf - flow) / ci - 1
            denom = ci
            if denom <= 0:
                continue
            ret = ((cf - dep + wd) / denom) - 1
            # Cap defensivo a ±200% por mes — algo absurdo y rompería compound
            if ret < -0.95 or ret > 5:
                continue
            compound *= (1 + ret)
            used += 1
        if used > 0:
            twr_pct = round((compound - 1) * 100, 2)
    except Exception:
        twr_pct = None

    drawdown = _compute_drawdown(values)

    # ── 2. Operations: trades cerrados, win rate, best/worst, attribution ────
    ops = [dict(r) for r in conn.execute(
        "SELECT date, asset, op_type, entry_price, exit_price, quantity, pnl_usd, pnl_pct, broker "
        "FROM operations WHERE user_id=? ORDER BY date ASC",
        (user_id,),
    ).fetchall()]

    closed = [
        o for o in ops
        if o.get("pnl_usd") is not None
        and (o.get("op_type") or "") not in ("Compra", "Dividendo", "Interés", "")
        and not (o.get("op_type") or "").startswith(("CONVERSION", "Conversión"))
    ]
    winners = [o for o in closed if (o.get("pnl_usd") or 0) > 0]
    losers = [o for o in closed if (o.get("pnl_usd") or 0) < 0]
    win_rate = (len(winners) / len(closed)) if closed else 0.0

    best_pct = max((o.get("pnl_pct") or 0) for o in closed) if closed else None
    worst_pct = min((o.get("pnl_pct") or 0) for o in closed) if closed else None

    # Atribución: P&L cerrado por ticker (suma)
    pnl_by_ticker: Dict[str, float] = {}
    pct_by_ticker: Dict[str, List[float]] = {}
    for o in closed:
        t = (o.get("asset") or "").upper()
        if not t:
            continue
        pnl_by_ticker[t] = pnl_by_ticker.get(t, 0) + float(o.get("pnl_usd") or 0)
        pct_by_ticker.setdefault(t, []).append(float(o.get("pnl_pct") or 0))

    def _avg(xs):
        return sum(xs) / len(xs) if xs else 0

    contributors = sorted(pnl_by_ticker.items(), key=lambda kv: kv[1], reverse=True)
    detractors = sorted(pnl_by_ticker.items(), key=lambda kv: kv[1])

    top_contributors = [
        {"ticker": t, "pnl_usd": round(v, 2), "pnl_pct": round(_avg(pct_by_ticker.get(t, [])), 2)}
        for t, v in contributors[:3] if v > 0
    ]
    top_detractors = [
        {"ticker": t, "pnl_usd": round(v, 2), "pnl_pct": round(_avg(pct_by_ticker.get(t, [])), 2)}
        for t, v in detractors[:3] if v < 0
    ]

    twr_realized_pct = None
    invested_sum = sum(float(o.get("entry_price") or 0) * float(o.get("quantity") or 0)
                       for o in closed)
    pnl_sum = sum(float(o.get("pnl_usd") or 0) for o in closed)
    if invested_sum > 0:
        twr_realized_pct = round((pnl_sum / invested_sum) * 100, 2)

    # ── 3. Exposure: AR / US / crypto / cash sobre positions actuales ────────
    # Cargamos posiciones (incluye is_cash=1) + brokers para conocer la currency
    # real de cada uno (algunos tienen nombres con espacios — usar string match
    # del broker name no es suficiente).
    positions = [dict(r) for r in conn.execute(
        "SELECT asset, broker, quantity, invested, is_cash FROM positions "
        "WHERE user_id=? AND (quantity > 0 OR is_cash = 1)",
        (user_id,),
    ).fetchall()]
    brokers_rows = conn.execute(
        "SELECT name, currency FROM brokers WHERE user_id=?", (user_id,)
    ).fetchall()
    broker_currency = {b["name"]: (b["currency"] or "USD").upper() for b in brokers_rows}

    # Precios + tc_blue para market value real
    tc_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (user_id,)
    ).fetchone()
    try:
        tc_blue = float(tc_row["value"]) if tc_row and tc_row["value"] else 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0
    if tc_blue <= 0:
        tc_blue = 1415.0

    prices: Dict[str, float] = {}
    try:
        from home.market import _fetch_batch_quotes
        symbols = set()
        for p in positions:
            if p.get("is_cash"):
                continue
            asset = p.get("asset")
            if not asset:
                continue
            broker_n = (p.get("broker") or "").lower()
            if broker_n in _AR_BROKERS:
                symbols.add(f"{asset}.BA")
            else:
                symbols.add(asset)
        if symbols:
            quotes = _fetch_batch_quotes(list(symbols))
            prices = {s: q["price"] for s, q in quotes.items()
                      if q and q.get("price") is not None}
    except Exception:
        prices = {}

    geo_value: Dict[str, float] = {"ar": 0.0, "us": 0.0, "crypto": 0.0, "cash": 0.0}
    for p in positions:
        broker_name = p.get("broker") or ""
        broker_n = broker_name.lower()
        currency = broker_currency.get(broker_name, "USD").upper()
        is_ars = currency == "ARS"
        invested = float(p.get("invested") or 0)
        if p.get("is_cash"):
            cash_v = invested / tc_blue if is_ars else invested
            geo_value["cash"] += cash_v
            continue
        asset = (p.get("asset") or "").upper()
        qty = float(p.get("quantity") or 0)
        if is_ars:
            price = prices.get(f"{asset}.BA")
            v = (price * qty) / tc_blue if price else invested / tc_blue
        else:
            price = prices.get(asset)
            v = price * qty if price else invested
        geo_value[_classify_geography(asset, broker_n)] += v

    total_exposure = sum(geo_value.values()) or 1
    exposure = {
        "cash_pct": round(geo_value["cash"] / total_exposure * 100, 1),
        "ar_pct": round(geo_value["ar"] / total_exposure * 100, 1),
        "us_pct": round(geo_value["us"] / total_exposure * 100, 1),
        "crypto_pct": round(geo_value["crypto"] / total_exposure * 100, 1),
    }

    # ── 4. Benchmarks ────────────────────────────────────────────────────────
    sp500_pct: Optional[float] = None
    inflation_pct: Optional[float] = None
    try:
        import main as _m
        cache_bench = getattr(_m, "_bench_cache", {}) or {}
        data = cache_bench.get("data") or {}
        sp = data.get("sp500") or {}
        infl = data.get("inflation_ar") or {}

        # Ventana: tomamos los meses dentro del window y compoundeamos
        from datetime import timedelta
        cutoff_date = today - timedelta(days=window_days)

        # SPY: % change desde el primer close ≥ cutoff hasta el último close
        sp_in_window = sorted([(k, v) for k, v in sp.items() if k >= cutoff_date.strftime("%Y-%m")])
        if len(sp_in_window) >= 2:
            v0 = sp_in_window[0][1]
            vN = sp_in_window[-1][1]
            if v0:
                sp500_pct = round((vN - v0) / v0 * 100, 2)

        # Inflación: compound de los % mensuales dentro de la ventana
        infl_in_window = sorted([(k, v) for k, v in infl.items() if k >= cutoff_date.strftime("%Y-%m")])
        if infl_in_window:
            comp = 1.0
            for _, pct in infl_in_window:
                comp *= (1 + pct / 100)
            inflation_pct = round((comp - 1) * 100, 2)
    except Exception:
        pass

    vs_benchmarks = {
        "sp500_pct": sp500_pct,
        "inflation_ar_pct": inflation_pct,
        "delta_sp500_pp": (
            round(twr_pct - sp500_pct, 2)
            if twr_pct is not None and sp500_pct is not None else None
        ),
        "delta_inflation_pp": (
            round(twr_pct - inflation_pct, 2)
            if twr_pct is not None and inflation_pct is not None else None
        ),
    }

    return {
        "screen": "insights",
        "window_days": window_days,
        "twr_pct": twr_pct,
        "twr_realized_pct": twr_realized_pct,
        "vs_benchmarks": vs_benchmarks,
        "drawdown": drawdown,
        "trades": {
            "closed_count": len(closed),
            "winners_count": len(winners),
            "losers_count": len(losers),
            "win_rate": round(win_rate, 3),
            "best_trade_pct": round(best_pct, 2) if best_pct is not None else None,
            "worst_trade_pct": round(worst_pct, 2) if worst_pct is not None else None,
        },
        "attribution": {
            "top_contributors": top_contributors,
            "top_detractors": top_detractors,
        },
        "exposure": exposure,
    }
