"""builders.news_item — packet de UNA noticia individual.
═══════════════════════════════════════════════════════════════════════════
Topic: news.item

Análisis IA de una noticia específica con context del portfolio del user.
Como las noticias son contenido externo, el LLM no analiza el contenido —
interpreta la RELEVANCIA para el portfolio: qué ticker toca, qué peso
tiene, qué pasó con esa posición recientemente.

Params (el frontend pasa la noticia tal cual):
  ticker: str           — ticker tocado por la noticia
  title: str            — headline
  source: str | None
  published_at: str | None  — ISO date
  summary: str | None   — resumen si lo trae el feed
  tags: list[str] | None
  url: str | None       — solo para tracking

Shape (~700 bytes):
{
  "screen": "news.item",
  "article": { ticker, title, source, published_at, summary, tags },
  "portfolio_context": {
    "holds_ticker": bool,
    "weight_pct": float | null,
    "pnl_pct": float | null,
    "broker": str | null,
    "days_held": int | null,
    "other_news_count_30d": int,
  },
}
"""
from __future__ import annotations
from typing import Dict, Any
from datetime import date, timedelta


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    ticker = (kwargs.get("ticker") or "").strip().upper()
    title = (kwargs.get("title") or "").strip()
    if not ticker:
        raise ValueError("Falta param 'ticker' — la noticia debe estar asociada a un activo.")
    if not title:
        raise ValueError("Falta param 'title' — headline obligatorio para el análisis.")

    article = {
        "ticker": ticker,
        "title": title,
        "source": (kwargs.get("source") or "").strip() or None,
        "published_at": (kwargs.get("published_at") or "").strip() or None,
        "summary": (kwargs.get("summary") or "").strip() or None,
        "tags": kwargs.get("tags") or [],
    }

    # ── Portfolio context — ¿tiene el ticker? cuánto pesa? cómo viene? ──────
    pos_rows = conn.execute(
        """SELECT broker, quantity, invested
             FROM positions
            WHERE user_id = ? AND asset = ? AND quantity > 0""",
        (user_id, ticker),
    ).fetchall()

    holds_ticker = len(pos_rows) > 0
    weight_pct = None
    pnl_pct = None
    broker = None
    days_held = None

    if holds_ticker:
        # Reusamos el builder position para coherencia (weight, pnl)
        try:
            from .position import build as build_position
            # Tomamos el broker del primer row si el user tiene la posición en
            # varios brokers — buscamos el broker dominante por invested
            pos_dicts = [dict(r) for r in pos_rows]
            pos_dicts.sort(key=lambda p: float(p.get("invested") or 0), reverse=True)
            broker = pos_dicts[0]["broker"]
            p = build_position(conn, user_id, asset=ticker, broker=broker)
            weight_pct = p.get("weight_pct")
            pnl_pct = p.get("pnl_pct")
            days_held = p.get("days_held")
        except Exception:
            pass

    # Other news count del mismo ticker en los últimos 30 días
    other_news_30d = 0
    try:
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM news
                WHERE ticker = ? AND published_at >= ?""",
            (ticker, cutoff),
        ).fetchone()
        other_news_30d = int(row["c"] or 0) if row else 0
        # Restamos esta noticia si está en la BD
        if other_news_30d > 0:
            other_news_30d = max(0, other_news_30d - 1)
    except Exception:
        other_news_30d = 0

    portfolio_context = {
        "holds_ticker": holds_ticker,
        "weight_pct": weight_pct,
        "pnl_pct": pnl_pct,
        "broker": broker,
        "days_held": days_held,
        "other_news_count_30d": other_news_30d,
    }

    return {
        "screen": "news.item",
        "article": article,
        "portfolio_context": portfolio_context,
    }
