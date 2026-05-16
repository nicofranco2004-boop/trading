"""builders.operations — packet del historial de trades cerrados.
═══════════════════════════════════════════════════════════════════════════
Topic: operations

Análisis de la pestaña /operaciones — todo el historial de trades
cerrados del user (no incluye compras abiertas ni dividendos). Distinto
de insights.attribution (que mira P&L por ticker) — éste enfoca la
DISTRIBUCIÓN del comportamiento del trader: win rate, payoff, mejor/
peor trade, frecuencia por año, sesgos visibles en la muestra.

Shape (~1KB):
{
  "screen": "operations",
  "total_closed": int,
  "winners_count": int,
  "losers_count": int,
  "win_rate": float,             # 0-1
  "total_pnl_usd": float,
  "avg_win_usd": float | null,
  "avg_loss_usd": float | null,
  "payoff_ratio": float | null,  # avg_win / |avg_loss|
  "expectancy_usd": float | null,
  "best_trade": { ticker, pnl_usd, pnl_pct, date } | null,
  "worst_trade": { ticker, pnl_usd, pnl_pct, date } | null,
  "trades_by_year": { "2024": int, "2025": int, ... },
  "tickers_traded": int,         # cantidad de tickers distintos cerrados
  "top_traded_tickers": [        # top 5 por frecuencia
    { "ticker": str, "count": int, "net_pnl_usd": float }
  ],
}
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from collections import Counter


def _is_trade(op: Dict[str, Any]) -> bool:
    op_type = (op.get("op_type") or "").strip()
    if op_type in ("Compra", "Dividendo", "Interés", ""):
        return False
    if op_type.startswith(("CONVERSION", "Conversión")):
        return False
    return op.get("pnl_usd") is not None


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    rows = conn.execute(
        """SELECT date, asset, broker, op_type, entry_price, exit_price,
                  quantity, pnl_usd, pnl_pct
             FROM operations
            WHERE user_id = ? AND pnl_usd IS NOT NULL
            ORDER BY date DESC""",
        (user_id,),
    ).fetchall()
    ops = [dict(r) for r in rows]
    closed = [o for o in ops if _is_trade(o)]

    if not closed:
        return {
            "screen": "operations",
            "total_closed": 0,
            "winners_count": 0,
            "losers_count": 0,
            "win_rate": 0.0,
            "total_pnl_usd": 0.0,
            "avg_win_usd": None,
            "avg_loss_usd": None,
            "payoff_ratio": None,
            "expectancy_usd": None,
            "best_trade": None,
            "worst_trade": None,
            "trades_by_year": {},
            "tickers_traded": 0,
            "top_traded_tickers": [],
        }

    winners = [o for o in closed if (o.get("pnl_usd") or 0) > 0]
    losers = [o for o in closed if (o.get("pnl_usd") or 0) < 0]
    n = len(closed)

    total_pnl = sum(float(o.get("pnl_usd") or 0) for o in closed)
    avg_win = (
        sum(float(o.get("pnl_usd") or 0) for o in winners) / len(winners)
        if winners else None
    )
    avg_loss = (
        sum(float(o.get("pnl_usd") or 0) for o in losers) / len(losers)
        if losers else None
    )
    payoff = (avg_win / abs(avg_loss)) if (avg_win and avg_loss) else None
    win_rate = len(winners) / n if n > 0 else 0.0
    expectancy = None
    if avg_win is not None and avg_loss is not None:
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    # Mejor / peor por P&L absoluto
    def _trade_record(o):
        return {
            "ticker": (o.get("asset") or "").upper(),
            "pnl_usd": round(float(o.get("pnl_usd") or 0), 2),
            "pnl_pct": round(float(o.get("pnl_pct") or 0), 2) if o.get("pnl_pct") is not None else None,
            "date": str(o.get("date") or "")[:10],
        }

    best = max(closed, key=lambda o: float(o.get("pnl_usd") or 0))
    worst = min(closed, key=lambda o: float(o.get("pnl_usd") or 0))

    # Distribución por año
    by_year: Counter = Counter()
    for o in closed:
        date_str = str(o.get("date") or "")[:4]
        if date_str.isdigit():
            by_year[date_str] += 1

    # Tickers más operados + P&L neto por ticker
    ticker_counter: Counter = Counter()
    ticker_pnl: Dict[str, float] = {}
    for o in closed:
        t = (o.get("asset") or "").upper()
        if not t:
            continue
        ticker_counter[t] += 1
        ticker_pnl[t] = ticker_pnl.get(t, 0) + float(o.get("pnl_usd") or 0)

    top_traded = [
        {
            "ticker": t,
            "count": c,
            "net_pnl_usd": round(ticker_pnl.get(t, 0), 2),
        }
        for t, c in ticker_counter.most_common(5)
    ]

    return {
        "screen": "operations",
        "total_closed": n,
        "winners_count": len(winners),
        "losers_count": len(losers),
        "win_rate": round(win_rate, 3),
        "total_pnl_usd": round(total_pnl, 2),
        "avg_win_usd": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss_usd": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff_ratio": round(payoff, 2) if payoff is not None else None,
        "expectancy_usd": round(expectancy, 2) if expectancy is not None else None,
        "best_trade": _trade_record(best),
        "worst_trade": _trade_record(worst),
        "trades_by_year": dict(by_year),
        "tickers_traded": len(ticker_counter),
        "top_traded_tickers": top_traded,
    }
