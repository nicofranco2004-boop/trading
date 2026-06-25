"""builders.insights_attribution — packet de atribución de Insights.
═══════════════════════════════════════════════════════════════════════════
Topic: insights.attribution

Sub-componente del Insights — qué activos manejaron tu P&L absoluto en el
período. A diferencia del 'dashboard.top_holdings' (que mira weight), acá
enfocamos en quién aportó/restó plata en USD absolutos.

Combina:
- P&L cerrado (operations con pnl_usd) por ticker.
- P&L no realizado (precio actual vs invested) por posición abierta.

CRÍTICO — separación de scope por item:
  Cada contributor/detractor lleva BOTH realized_usd Y unrealized_usd
  separados. Además agregamos `pnl_source` y `in_portfolio_now` para que
  el LLM razone correctamente:
    • pnl_source='realized_only': solo trades cerrados, ya no en cartera
    • pnl_source='unrealized_only': posición abierta sin trades cerrados
    • pnl_source='mixed': tiene ambos (closed + open lots del mismo ticker)
  El LLM debe inferir riesgo PRESENTE solo de unrealized_usd
  (cuando in_portfolio_now=true).

Shape (~1100 bytes):
{
  "screen": "insights.attribution",
  "total_realized_usd": float,
  "total_unrealized_usd": float,
  "total_pnl_usd": float,
  "top_contributors": [
    { "ticker": str, "realized_usd": float, "unrealized_usd": float,
      "combined_pnl_usd": float,           # realized + unrealized (back-compat: total_usd)
      "total_usd": float,                  # alias de combined_pnl_usd
      "share_pct": float,                  # % del |total_pnl| que explica este ticker
      "pnl_source": "realized_only"|"unrealized_only"|"mixed",
      "in_portfolio_now": bool }
  ],
  "top_detractors": [ ... same shape ],
  "top1_share_pct": float,                 # qué % del P&L explica el top1
  "concentration_flag": bool,              # True si top1 > 50% del combined
  "concentration_source": "realized_only"|"unrealized_only"|"mixed"|null,
                                           # de dónde viene la concentración:
                                           # importante para distinguir
                                           # concentración HISTÓRICA (realized
                                           # de un trade cerrado puntual) de
                                           # concentración PRESENTE (riesgo).
}
"""
from __future__ import annotations
from typing import Dict, Any, List


_AR_BROKERS = {"cocos", "iol", "bull", "balanz", "naranja", "pppi", "invertironline", "lemon"}


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    # ── Realized: agregamos P&L de operations cerradas por ticker ────────────
    ops = conn.execute(
        """SELECT asset, op_type, pnl_usd
             FROM operations
            WHERE user_id=? AND pnl_usd IS NOT NULL""",
        (user_id,),
    ).fetchall()

    realized_by_ticker: Dict[str, float] = {}
    for o in ops:
        op_type = (o["op_type"] or "").strip()
        if op_type in ("Compra", "Dividendo", "Interés", ""):
            continue
        if op_type.startswith(("CONVERSION", "Conversión")):
            continue
        ticker = (o["asset"] or "").upper()
        if not ticker:
            continue
        realized_by_ticker[ticker] = realized_by_ticker.get(ticker, 0) + float(o["pnl_usd"] or 0)

    # ── Unrealized: precio actual * qty - invested por posición abierta ──────
    positions = [dict(r) for r in conn.execute(
        "SELECT asset, asset_type, broker, currency, quantity, invested, is_cash FROM positions "
        "WHERE user_id=? AND quantity > 0 AND (is_cash = 0 OR is_cash IS NULL)",
        (user_id,),
    ).fetchall()]

    # Valuación canónica de Análisis (estampa moneda, precios .BA-aware, MEP).
    # Antes valuaba holdings AR al blue y un CEDEAR en sub-broker '· USD' por el
    # ticker US (C1). Ahora value e invested salen del mismo valuador → sin
    # FX-phantom y con MEP. Ver CORRECTNESS_AUDIT (C1 / M-AI1).
    from analysis_prep import currency_context
    from behavioral import _position_value_usd
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, positions)

    unrealized_by_ticker: Dict[str, float] = {}
    for p in positions:
        asset = (p.get("asset") or "").upper()
        if not asset:
            continue
        mv_usd = _position_value_usd(p, prices, tc_blue, tc_cedear)
        invested_usd = _position_value_usd(p, {}, tc_blue, tc_cedear, honor_override=False)
        unrealized_by_ticker[asset] = unrealized_by_ticker.get(asset, 0) + (mv_usd - invested_usd)

    # Tickers presentes EN CARTERA HOY (positions con quantity > 0). Sirve
    # para el flag in_portfolio_now de cada item de attribution.
    tickers_in_portfolio = {
        (p.get("asset") or "").upper()
        for p in positions
        if p.get("asset") and float(p.get("quantity") or 0) > 0
    }

    # ── Combinar realized + unrealized por ticker ────────────────────────────
    all_tickers = set(realized_by_ticker.keys()) | set(unrealized_by_ticker.keys())
    combined: List[Dict[str, Any]] = []
    for t in all_tickers:
        r = realized_by_ticker.get(t, 0)
        u = unrealized_by_ticker.get(t, 0)
        combined_pnl = r + u

        # pnl_source: clasifica de dónde viene el P&L de este ticker.
        # Umbral pequeño para considerar "tiene presencia" en cada lado.
        has_realized = abs(r) > 0.5
        has_unrealized = abs(u) > 0.5
        if has_realized and has_unrealized:
            source = "mixed"
        elif has_realized:
            source = "realized_only"
        elif has_unrealized:
            source = "unrealized_only"
        else:
            source = "realized_only"  # fallback — ambos cero, irrelevante

        combined.append({
            "ticker": t,
            "realized_usd": round(r, 2),
            "unrealized_usd": round(u, 2),
            "combined_pnl_usd": round(combined_pnl, 2),
            # total_usd: alias de combined_pnl_usd para back-compat con
            # consumers viejos. Idéntico al nuevo.
            "total_usd": round(combined_pnl, 2),
            "pnl_source": source,
            "in_portfolio_now": t in tickers_in_portfolio,
        })

    total_realized = sum(c["realized_usd"] for c in combined)
    total_unrealized = sum(c["unrealized_usd"] for c in combined)
    total_pnl = total_realized + total_unrealized
    # Para share_pct, usamos magnitud para no dividir por algo cercano a 0
    abs_total = max(abs(total_pnl), 1)

    def with_share(items):
        return [
            {**c, "share_pct": round(c["combined_pnl_usd"] / abs_total * 100, 1)}
            for c in items
        ]

    sorted_desc = sorted(combined, key=lambda c: c["combined_pnl_usd"], reverse=True)
    sorted_asc = sorted(combined, key=lambda c: c["combined_pnl_usd"])
    contributors = with_share([c for c in sorted_desc if c["combined_pnl_usd"] > 0][:5])
    detractors = with_share([c for c in sorted_asc if c["combined_pnl_usd"] < 0][:5])

    top1_share = contributors[0]["share_pct"] if contributors else 0.0
    # Origen de la concentración: si el top1 es realized_only (trade cerrado
    # único), la "concentración" es histórica, no exposure presente. Si es
    # unrealized_only/mixed con in_portfolio_now=true, sí es riesgo presente.
    concentration_source = contributors[0]["pnl_source"] if contributors else None

    return {
        "screen": "insights.attribution",
        # _field_docs — descripciones inline para el LLM (Ola 2-E).
        # Documentamos solo los fields ambiguos.
        "_field_docs": {
            "_doc_scope": "Solo documentamos campos ambiguos donde el nombre no basta. Los demás (period, ticker, asset, broker) son explícitos por su nombre — confiá en ellos.",
            "total_realized_usd": "USD de P&L de trades CERRADOS, sumado all-time. SOLO realized.",
            "total_unrealized_usd": "USD mark-to-market HOY de posiciones abiertas, sumado. SOLO unrealized.",
            "total_pnl_usd": "Suma de realized + unrealized. Es contexto, no exposure.",
            "top_contributors[].realized_usd": "USD realized del ticker (trades cerrados).",
            "top_contributors[].unrealized_usd": "USD unrealized del ticker (posiciones abiertas, mark-to-market).",
            "top_contributors[].combined_pnl_usd": "realized + unrealized del ticker. Es el field usado para sortear.",
            "top_contributors[].pnl_source": "De dónde viene el P&L: 'realized_only'=trades cerrados (histórico), 'unrealized_only'=posición abierta sin trades cerrados, 'mixed'=ambos. Para riesgo presente, mirar solo unrealized_only/mixed con in_portfolio_now=true.",
            "top_contributors[].in_portfolio_now": "true si el ticker tiene posición abierta hoy. false si solo apareció en operations cerradas.",
            "concentration_flag": "True si el top1 explica >50% del combined P&L. NO implica exposure concentrada — chequear concentration_source.",
            "concentration_source": "Si top1.pnl_source='realized_only', la concentración es HISTÓRICA (un trade cerrado puntual). Si 'unrealized_only' o 'mixed' con in_portfolio_now=true, es exposure PRESENTE real (riesgo).",
        },
        "total_realized_usd": round(total_realized, 2),
        "total_unrealized_usd": round(total_unrealized, 2),
        "total_pnl_usd": round(total_pnl, 2),
        "top_contributors": contributors,
        "top_detractors": detractors,
        "top1_share_pct": top1_share,
        "concentration_flag": top1_share > 50.0,
        "concentration_source": concentration_source,
    }
