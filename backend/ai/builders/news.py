"""builders.news — packet del feed de noticias del portfolio.
═══════════════════════════════════════════════════════════════════════════
Topic: news

Analiza el flujo de noticias del PORTFOLIO del user — qué se publicó en
los últimos días tocando sus tickers. No analiza el contenido de las
noticias (eso es LLM territory), sino el patrón agregado: cantidad,
distribución por ticker, sentimiento implícito en los tags.

El packet trae headlines + tickers tocados + tags agregados. El LLM
interpreta "qué temáticas dominan tu radar hoy".

Shape (~1KB):
{
  "screen": "news",
  "window_days": int,
  "total_news": int,
  "tickers_covered": [ticker],          # tickers de tu portfolio con noticias recientes
  "tickers_silent_count": int,           # tickers de tu portfolio SIN noticias
  "top_tags": [{"tag": str, "count": int}],   # top 5 tags más frecuentes
  "top_sources": [{"source": str, "count": int}],  # top 3 sources
  "headlines": [                         # cap 10 con weight_pct si aplica
    { "ticker": str, "title": str, "source": str,
      "published_at": str, "weight_pct": float | null }
  ],
}
"""
from __future__ import annotations
from typing import Dict, Any, List
from datetime import date, timedelta
from collections import Counter


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    window_days = int(kwargs.get("window_days", 7))
    today = date.today()
    cutoff = today - timedelta(days=window_days)

    # Tickers del user (non-cash) — para saber qué noticias importan
    portfolio_assets = sorted({
        r["asset"] for r in conn.execute(
            """SELECT DISTINCT asset FROM positions
                WHERE user_id = ? AND is_cash = 0 AND quantity > 0""",
            (user_id,),
        ).fetchall() if r["asset"]
    })

    # Weight de cada ticker (para contextualizar relevancia de la noticia)
    weights: Dict[str, float] = {}
    try:
        from .dashboard_top_holdings import build as build_top
        top_packet = build_top(conn, user_id)
        for h in top_packet.get("top_holdings") or []:
            weights[h["ticker"]] = h.get("weight_pct") or 0
    except Exception:
        weights = {}

    # Pull news del cache que main mantiene + tabla `news` si está
    rows: List[Dict[str, Any]] = []
    try:
        # Mirror del endpoint /api/news/portfolio: consulta directa
        # (asumimos tabla `news` con campos ticker, title, source, published_at, tags)
        placeholders = ",".join("?" * len(portfolio_assets)) if portfolio_assets else "''"
        if portfolio_assets:
            results = conn.execute(
                f"""SELECT ticker, title, source, published_at, tags
                     FROM news
                    WHERE ticker IN ({placeholders})
                      AND published_at >= ?
                    ORDER BY published_at DESC LIMIT 60""",
                (*portfolio_assets, cutoff.isoformat()),
            ).fetchall()
            rows = [dict(r) for r in results]
    except Exception:
        rows = []

    # ── Agregados ────────────────────────────────────────────────────────────
    tickers_covered = sorted({r["ticker"] for r in rows if r.get("ticker")})
    tickers_silent_count = max(0, len(portfolio_assets) - len(tickers_covered))

    tag_counter: Counter = Counter()
    source_counter: Counter = Counter()
    for r in rows:
        if r.get("source"):
            source_counter[r["source"]] += 1
        tags = r.get("tags")
        if tags:
            # tags puede venir como string JSON o como CSV simple
            try:
                if isinstance(tags, str):
                    if tags.startswith("["):
                        import json as _json
                        tag_list = _json.loads(tags)
                    else:
                        tag_list = [t.strip() for t in tags.split(",")]
                else:
                    tag_list = list(tags)
                for t in tag_list:
                    if t:
                        tag_counter[str(t).strip()] += 1
            except Exception:
                pass

    top_tags = [{"tag": t, "count": c} for t, c in tag_counter.most_common(5)]
    top_sources = [{"source": s, "count": c} for s, c in source_counter.most_common(3)]

    # Headlines — cap 10, con weight_pct para que el LLM sepa relevancia
    headlines: List[Dict[str, Any]] = []
    for r in rows[:10]:
        ticker = r.get("ticker")
        headlines.append({
            "ticker": ticker,
            "title": r.get("title"),
            "source": r.get("source"),
            "published_at": str(r.get("published_at"))[:10] if r.get("published_at") else None,
            "weight_pct": weights.get(ticker),
        })

    return {
        "screen": "news",
        "window_days": window_days,
        "total_news": len(rows),
        "tickers_covered": tickers_covered,
        "tickers_silent_count": tickers_silent_count,
        "top_tags": top_tags,
        "top_sources": top_sources,
        "headlines": headlines,
    }
