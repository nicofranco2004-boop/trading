"""builders.insights — packet del screen "Insights".
═══════════════════════════════════════════════════════════════════════════
Topic: insights

El screen Insights es el análisis profundo: performance acumulada, riesgo
(drawdown), atribución por activo, vs benchmarks (S&P 500 + inflación AR).
La página calcula casi todo en el frontend — acá rehacemos los números
clave en Python con los mismos datos crudos (snapshots, monthly,
operations, positions) para no depender del frontend.

Mantenemos el packet lean (~1.5KB): TWR del período, drawdown actual y
máximo, atribución de trades CERRADOS (top contributors/detractors REALIZADO),
HOLDINGS ACTUALES (top 3 posiciones abiertas por market value), win rate,
exposure mix, vs benchmarks.

CRÍTICO — separación open vs closed:
  • `realized_attribution`: trades YA CERRADOS. Su P&L es histórico, no
    afecta el portfolio actual. NO se puede inferir riesgo presente desde acá.
  • `current_holdings_top`: posiciones ACTUALMENTE ABIERTAS. Su unrealized
    P&L sí está expuesto al movimiento de mercado — acá sí razonar riesgo.

Shape:
{
  "screen": "insights",
  "window_days": 365,
  "twr_pct": float | null,           # rendimiento acumulado total del período
                                     # (compuesto via monthly_entries — combina P&L
                                     #  realizado por mes + unrealized del mes en curso)
  "realized_pnl_usd": float | null,  # P&L USD absoluto sumado de trades cerrados
  "realized_avg_pct_per_trade": float | null,  # promedio simple de pnl_pct por trade
                                     # (NO es return sobre capital — es la performance
                                     #  promedio por operación cerrada)
  "unrealized_pnl_total_usd": float | null,  # USD mark-to-market actual de TODAS
                                     # las posiciones abiertas (mv - invested), sumado.
                                     # Null si no hay precios live. CRÍTICO para
                                     # explicar el origen del twr_pct: si twr_pct
                                     # alto pero realized_pnl_usd bajo, casi todo
                                     # viene de este número (P&L "sobre papel").
  "unrealized_pnl_total_pct": float | null,  # % sobre el costo de las posiciones
                                     # abiertas con precio live.
  "total_equity_usd": float,         # Valor TOTAL de la cartera HOY en USD
                                     # (holdings con mv live + cash).
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
  "realized_attribution": {
    # ESTOS SON TRADES YA CERRADOS — P&L histórico, no exposure actual.
    # El ticker puede o no seguir en el portfolio. NUNCA inferir riesgo
    # presente desde acá.
    "scope": "closed_trades",
    "period": "all_time",
    "top_contributors": [
      { "ticker": str, "pnl_usd": float, "pnl_pct": float,
        "status": "closed", "in_portfolio_now": bool }
    ],
    "top_detractors": [
      { "ticker": str, "pnl_usd": float, "pnl_pct": float,
        "status": "closed", "in_portfolio_now": bool }
    ],
  },
  "current_holdings_top": [
    # POSICIONES ABIERTAS — exposure actual al mercado. Acá SÍ razonar
    # sobre riesgo presente y movimientos futuros. Ordenado por market value.
    { "ticker": str, "market_value_usd": float, "share_pct": float,
      "unrealized_pnl_usd": float | null, "unrealized_pnl_pct": float | null,
      "broker": str, "status": "open" }
  ],
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

from behavioral import _native_ccy


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

    # Atribución de TRADES CERRADOS: P&L realizado por ticker (suma).
    # Esto es histórico — un ticker puede no estar más en portfolio. Por eso
    # cruzamos contra positions abajo para marcar in_portfolio_now.
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

    # Top contributors/detractors construidos abajo (necesitan tickers_open
    # para cruzar con posiciones abiertas — se completa después de la sección 3).

    # P&L absoluto de trades cerrados — métrica honesta sin distorsión por
    # capital rotativo. Antes computábamos twr_realized_pct como
    # pnl_sum / sum(entry_price * qty) — pero eso sumaba el MISMO capital
    # rotando entre trades, inflando el denominador y produciendo % minúsculos
    # (ej. 0.01%) que confundían al LLM y al user.
    realized_pnl_usd = round(sum(float(o.get("pnl_usd") or 0) for o in closed), 2) if closed else None

    # Promedio simple de pnl_pct por trade — performance promedio operación,
    # independiente del capital total. No es un return acumulado.
    realized_avg_pct = None
    pcts = [float(o.get("pnl_pct") or 0) for o in closed if o.get("pnl_pct") is not None]
    if pcts:
        realized_avg_pct = round(sum(pcts) / len(pcts), 2)

    # ── 3. Posiciones ABIERTAS: exposure + current_holdings_top + market value
    # Cargamos posiciones (incluye is_cash=1) + brokers para conocer la currency
    # real de cada uno (algunos tienen nombres con espacios — usar string match
    # del broker name no es suficiente).
    positions = [dict(r) for r in conn.execute(
        "SELECT asset, broker, quantity, invested, is_cash, currency FROM positions "
        "WHERE user_id=? AND (quantity > 0 OR is_cash = 1)",
        (user_id,),
    ).fetchall()]
    # Estampar moneda autoritativa del broker (brokers.currency) en posiciones
    # con currency NULL — _native_ccy infiere por nombre y no cubre brokers AR
    # fuera de la lista de hints (Santander/Galicia/PPI…) → ARS contado USD 1415×.
    from behavioral import stamp_positions_currency, _is_ars_broker
    _bccy = {
        r["name"]: (r["currency"] or "")
        for r in conn.execute("SELECT name, currency FROM brokers WHERE user_id=?", (user_id,)).fetchall()
    }
    stamp_positions_currency(positions, _bccy)

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

    # tc_mep (dólar-MEP) para valuar HOLDINGS AR (CEDEARs/acciones .BA) y su
    # cost_usd igual que la sección Análisis del frontend. El CASH en pesos
    # sigue por tc_blue. Fallback a tc_blue si no existe la config.
    mep_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_mep'", (user_id,)
    ).fetchone()
    try:
        tc_mep = float(mep_row["value"]) if mep_row and mep_row["value"] else tc_blue
    except (TypeError, ValueError):
        tc_mep = tc_blue
    if tc_mep <= 0:
        tc_mep = tc_blue
    tc_cedear = tc_mep if tc_mep > 0 else tc_blue

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
            # EJE DEL PRECIO: el precio live de un broker AR-residente cotiza en
            # ARS (.BA) — incluido el sub-broker '· USD', cuyo CEDEAR igual
            # cotiza en pesos en BYMA. Por eso el .BA se decide por _is_ars_broker
            # (residencia), NO por _native_ccy (que es el eje del COST BASIS).
            # Sin esto, un CEDEAR en 'Cocos · USD' se valuaba con el precio de la
            # acción US completa × cantidad de CEDEARs (error por el ratio).
            if _is_ars_broker(p.get("broker")):
                symbols.add(f"{asset}.BA")
            else:
                symbols.add(asset)
        if symbols:
            quotes = _fetch_batch_quotes(list(symbols))
            prices = {s: q["price"] for s, q in quotes.items()
                      if q and q.get("price") is not None}
    except Exception:
        prices = {}

    # Para cada posición abierta, calculamos market value en USD + unrealized P&L.
    # También agregamos por ticker (multi-broker → un solo holding) para
    # `current_holdings_top` y para cruzar con `in_portfolio_now` en attribution.
    geo_value: Dict[str, float] = {"ar": 0.0, "us": 0.0, "crypto": 0.0, "cash": 0.0}
    holdings_agg: Dict[str, Dict[str, Any]] = {}  # ticker → {market_value_usd, invested_usd, brokers}
    # Premium dólar-cripto (broker no-exchange) + guard cripto (nunca es .BA).
    try:
        from main import (CRYPTO_SYMBOLS as _CRYPTO_SYMBOLS,
                          crypto_broker_factor as _cb_factor, _current_cripto_rate)
        _cripto_rate = _current_cripto_rate()
    except Exception:
        _CRYPTO_SYMBOLS = set()
        _cb_factor = lambda *a: 1.0
        _cripto_rate = None
    for p in positions:
        broker_name = p.get("broker") or ""
        broker_n = broker_name.lower()
        # DOS ejes de moneda (como behavioral._position_value_usd):
        #  - cost_is_ars (_native_ccy): moneda del cost basis (invested/cash).
        #    Un sub-broker '· USD' tiene cost en USD aunque cotice en BYMA.
        #  - price_is_ars (_is_ars_broker): el precio live viene en ARS (.BA)
        #    para todo broker AR-residente. Decide el lookup y la conversión.
        cost_is_ars = _native_ccy(p) == "ARS"
        price_is_ars = _is_ars_broker(broker_name)
        invested = float(p.get("invested") or 0)
        # Unificación FX: TODO lo ARS (cash y holdings) → USD por el dólar-MEP
        # (tc_cedear), igual que la sección Análisis del frontend. Antes el cash iba al blue.
        if cost_is_ars:
            _rate = tc_cedear if (tc_cedear and tc_cedear > 0) else tc_blue
            cost_usd = invested / _rate if _rate > 0 else invested
        else:
            cost_usd = invested
        if p.get("is_cash"):
            geo_value["cash"] += cost_usd
            continue
        asset = (p.get("asset") or "").upper()
        qty = float(p.get("quantity") or 0)
        is_crypto = asset in _CRYPTO_SYMBOLS
        if price_is_ars and not is_crypto:
            # El precio live .BA está en ARS → a USD por el MEP (no blue) para
            # matchear cómo lo valúa Análisis. (La cripto NUNCA es .BA → spot.)
            price = prices.get(f"{asset}.BA")
            mv = (price * qty) / tc_cedear if price else cost_usd
        else:
            price = prices.get(asset)
            mv = price * qty if price else cost_usd
        # Premium dólar-cripto (broker no-exchange): al VALOR (spot-USD) siempre; al
        # COSTO solo si está en USD (cost_is_ars=False). Un costo en pesos ya pasó a
        # dólar-MEP con /tc_cedear → no se multiplica de nuevo (compondría /MEP²).
        cf = _cb_factor(asset, broker_name, p.get("price_override") is not None, _cripto_rate, tc_cedear)
        if cf != 1.0:
            mv *= cf
            if not cost_is_ars:
                cost_usd *= cf
        geo_value[_classify_geography(asset, broker_n)] += mv
        if asset not in holdings_agg:
            holdings_agg[asset] = {
                "market_value_usd": 0.0,
                "invested_usd": 0.0,
                "brokers": set(),
                "has_live_price": False,
            }
        h = holdings_agg[asset]
        h["market_value_usd"] += mv
        h["invested_usd"] += cost_usd
        h["brokers"].add(broker_name)
        if price is not None:
            h["has_live_price"] = True

    total_exposure = sum(geo_value.values()) or 1
    exposure = {
        "cash_pct": round(geo_value["cash"] / total_exposure * 100, 1),
        "ar_pct": round(geo_value["ar"] / total_exposure * 100, 1),
        "us_pct": round(geo_value["us"] / total_exposure * 100, 1),
        "crypto_pct": round(geo_value["crypto"] / total_exposure * 100, 1),
    }

    # ── 3.5 Unrealized P&L total — agregado de TODAS las posiciones abiertas
    # (no solo top 3). Crítico para explicar el origen del twr_pct: si el TWR
    # del año es 59% pero realized_pnl_usd es bajo, casi todo viene de
    # unrealized — ese campo permite que la IA cuantifique cuánto sería el
    # P&L "sobre papel" si el user cerrara todo hoy.
    unrealized_pnl_total_usd = 0.0
    cost_total_for_unr = 0.0
    has_any_live_price = False
    for h in holdings_agg.values():
        if h["has_live_price"]:
            unrealized_pnl_total_usd += h["market_value_usd"] - h["invested_usd"]
            cost_total_for_unr += h["invested_usd"]
            has_any_live_price = True
    # Si NO tenemos precios live para ninguna posición, devolvemos None en
    # lugar de 0 (que sería engañoso — sugeriría que no hay unrealized).
    if not has_any_live_price:
        unrealized_pnl_total_usd = None
        unrealized_pnl_total_pct = None
    else:
        unrealized_pnl_total_usd = round(unrealized_pnl_total_usd, 2)
        unrealized_pnl_total_pct = round(
            unrealized_pnl_total_usd / cost_total_for_unr * 100, 2
        ) if cost_total_for_unr > 0 else None

    # Total equity USD: market value de holdings abiertos (con prices live) +
    # cash. Es el valor de la cartera HOY.
    total_equity_usd = round(total_exposure, 2)

    # ── 3b. Current holdings top — top 3 por market value en USD ─────────────
    # Es la exposure ACTUAL real al mercado. Usar para razonar sobre riesgo
    # presente (si X cae 20%, mi cartera pierde Y). Esto es lo que faltaba
    # antes y causaba que la IA infiriera mal usando realized_attribution.
    holdings_sorted = sorted(
        holdings_agg.items(),
        key=lambda kv: kv[1]["market_value_usd"],
        reverse=True,
    )
    current_holdings_top: List[Dict[str, Any]] = []
    for ticker, h in holdings_sorted[:3]:
        mv = h["market_value_usd"]
        cost = h["invested_usd"]
        # Unrealized P&L solo si tenemos precio live — si no, sería P&L=0 falso.
        if h["has_live_price"] and cost > 0:
            unrealized_pnl = mv - cost
            unrealized_pct = (unrealized_pnl / cost) * 100
        else:
            unrealized_pnl = None
            unrealized_pct = None
        # share_pct sobre exposure total (incluye cash). Útil para "esta
        # posición pesa X% de mi cartera".
        share_pct = (mv / total_exposure * 100) if total_exposure > 0 else 0
        brokers_str = ", ".join(sorted(h["brokers"]))
        current_holdings_top.append({
            "ticker": ticker,
            "market_value_usd": round(mv, 2),
            "share_pct": round(share_pct, 1),
            "unrealized_pnl_usd": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
            "unrealized_pnl_pct": round(unrealized_pct, 2) if unrealized_pct is not None else None,
            "broker": brokers_str,
            "status": "open",
        })

    # Set de tickers actualmente en portfolio — para etiquetar attribution.
    tickers_in_portfolio = set(holdings_agg.keys())

    # ── 3c. Realized attribution con flag in_portfolio_now ───────────────────
    # Ahora SÍ construimos top_contributors / top_detractors con etiquetado
    # explícito. El campo `in_portfolio_now` le dice al LLM si el ticker sigue
    # en el portfolio actual (clave para razonar correctamente sobre riesgo).
    top_contributors = [
        {
            "ticker": t,
            "pnl_usd": round(v, 2),
            "pnl_pct": round(_avg(pct_by_ticker.get(t, [])), 2),
            "status": "closed",
            "in_portfolio_now": t in tickers_in_portfolio,
        }
        for t, v in contributors[:3] if v > 0
    ]
    top_detractors = [
        {
            "ticker": t,
            "pnl_usd": round(v, 2),
            "pnl_pct": round(_avg(pct_by_ticker.get(t, [])), 2),
            "status": "closed",
            "in_portfolio_now": t in tickers_in_portfolio,
        }
        for t, v in detractors[:3] if v < 0
    ]

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

    # ── 4. Metadata de bonos AR (Ola 3-K) — enriquece cuando hay bonos
    # en cartera. Inyectamos descripción + maturity + ley + mecánica CER
    # para que la IA narre con contexto real. Solo aparece si hay bonos.
    from ai.ar_bonds_metadata import enrich_bond_holdings
    ar_bond_holdings = enrich_bond_holdings(positions)

    return {
        "screen": "insights",
        # _field_docs — descripciones inline para el LLM (Ola 2-E del audit).
        # No es metadata interna; el LLM lo lee con el packet y desambigua
        # cada field sin tener que inferir del nombre. Solo documentamos los
        # campos ambiguos donde históricamente confundió scope.
        "_field_docs": {
            # _doc_scope explica al LLM que la ausencia de doc NO indica
            # incertidumbre del campo — solo documentamos los AMBIGUOS donde
            # confundió scope históricamente. Campos auto-descriptivos por
            # nombre (window_days, drawdown, vs_benchmarks, trades.*) son
            # confiables sin doc. Audit #3 B9.
            "_doc_scope": "Solo documentamos campos ambiguos donde el nombre no basta. Los demás (window_days, drawdown, vs_benchmarks, trades, attribution, monthly_summary, geo_distribution, behavioral) son explícitos por su nombre — confiá en ellos.",
            "twr_pct": "TWR del período. Compuesto via monthly_entries. Combina P&L realizado de meses cerrados + unrealized mark-to-market del mes en curso. NO descompone realizado vs unrealized — usar realized_pnl_usd + unrealized_pnl_total_usd para eso.",
            "realized_pnl_usd": "USD ABSOLUTO sumado de trades CERRADOS. No es %, no es vs invested. Si negativo, perdiste en operaciones cerradas. Si chico vs total_equity_usd, casi todo el resultado está en unrealized.",
            "realized_avg_pct_per_trade": "Promedio simple de pnl_pct por trade cerrado. NO acumulado, NO compounded. Solo describe performance media por operación.",
            "unrealized_pnl_total_usd": "USD mark-to-market HOY de TODAS las posiciones abiertas. Cambia con el mercado. Si twr_pct alto y realized_pnl_usd bajo, este campo explica la diferencia.",
            "total_equity_usd": "Valor TOTAL de la cartera HOY (holdings con market value live + cash). Referencia absoluta para cuantificar % en USD.",
            "realized_attribution.top_contributors": "Trades CERRADOS por contribución de P&L. status='closed' siempre. in_portfolio_now indica si el ticker sigue abierto. NUNCA inferir riesgo presente desde acá — el P&L ya está realizado.",
            "realized_attribution.top_detractors": "Idem contributors pero negativos.",
            "current_holdings_top": "Posiciones ABIERTAS por market value en USD. status='open' siempre. Para razonar riesgo presente, exposure, concentración: usar SOLO esto.",
            "ar_bond_holdings": "Metadata enriquecida de bonos AR en cartera (solo si hay). Cada item: ticker, position_qty, metadata={kind, maturity, law, indexed_by, step_up, description}. USAR para narrar bonos con contexto específico (maturity, ley aplicable, mecánica CER vs USD step-up). Sin esto, NO tratar bonos como acciones genéricas.",
        },
        "window_days": window_days,
        "twr_pct": twr_pct,
        # Métricas de trades cerrados — REPLACE del viejo twr_realized_pct
        # que era engañoso (denominador inflado por capital rotativo). Ahora:
        # - realized_pnl_usd: cuánto se ganó/perdió neto en USD (claro)
        # - realized_avg_pct_per_trade: % promedio por trade (no acumulado)
        "realized_pnl_usd": realized_pnl_usd,
        "realized_avg_pct_per_trade": realized_avg_pct,
        # P&L unrealized total — la pieza que faltaba para entender el twr_pct.
        # Si twr_pct=59% pero realized_pnl_usd es chico, este campo dice
        # cuánto del 59% es mark-to-market vivo (sobre papel, sin realizar).
        "unrealized_pnl_total_usd": unrealized_pnl_total_usd,
        "unrealized_pnl_total_pct": unrealized_pnl_total_pct,
        # Equity total HOY — referencia absoluta para que la IA cuantifique.
        # Si "+59%" y total_equity_usd=$160K, era $100K hace 12 meses.
        "total_equity_usd": total_equity_usd,
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
        # Atribución de TRADES CERRADOS — histórico, NO exposure presente.
        # Renombrado de `attribution` para que el LLM entienda inmediatamente
        # que es P&L realizado. Cada item lleva status:"closed" + flag
        # in_portfolio_now que indica si el ticker sigue en cartera.
        "realized_attribution": {
            "scope": "closed_trades",
            "period": "all_time",
            "top_contributors": top_contributors,
            "top_detractors": top_detractors,
        },
        # Posiciones ABIERTAS — exposure actual al mercado. Para razonar
        # sobre riesgo presente y movimientos futuros, usar SOLO esto
        # (nunca realized_attribution).
        "current_holdings_top": current_holdings_top,
        "exposure": exposure,
        # Metadata enriquecida de bonos AR (Ola 3-K). Solo aparece si el
        # user tiene bonos AR conocidos en cartera. Cada item: ticker,
        # cantidad, y metadata con maturity/kind/law/indexed_by/description.
        # Usar para que el LLM razone correctamente sobre yields, duration,
        # ley aplicable, mecánica CER. Sin este bloque la IA trata bonos
        # como acciones genéricas.
        "ar_bond_holdings": ar_bond_holdings,
    }
