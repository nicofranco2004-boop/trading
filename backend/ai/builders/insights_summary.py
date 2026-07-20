"""builders.insights_summary — packet de la LECTURA PERSONALIZADA del Diagnóstico.
═══════════════════════════════════════════════════════════════════════════
Topic: insights.summary

Análogo a profile.summary pero para el tab Diagnóstico: la IA sintetiza el
diagnóstico de la cartera (exposición, concentración, atribución, riesgo,
comportamiento) en UNA lectura conectada arriba del tablero.

Reusa `builders.insights.build()` para toda la valuación server-side canónica
(currency_context: exposure, holdings top, atribución realizado/unrealized,
drawdown, trade stats, benchmark returns) — números CONFIABLES que no dependen
del motor TWR del frontend.

CRÍTICO — retorno fantasma: el `twr_pct` compuesto es la métrica con el bug
conocido (−64.9% fantasma / TWR peso por cost-basis). Acá NO se expone como
número duro: va bajo `twr_pct_low_confidence` y el prompt tiene PROHIBIDO
citarlo. La IA narra "le ganás/perdés a X" SOLO con lo que el frontend ya
mostró (`verdicts` + `top_findings` pasados como params), así la lectura NO
contradice las cards que tiene debajo (la lección de profile.summary).

Params (del frontend, vía el endpoint /api/ai/analyze):
  archetype       — 'empty'|'new'|'crypto'|'conservador_ar'|'completo'
  findings        — top-N del diagnóstico [{category, severity, text}]
  verdicts        — items del veredicto comparativo [{label, pct}] (ya computados,
                    currency-consistentes con la pantalla)
  months_tracked  — meses con historial (para el modo onboarding)
  missing_prices  — [tickers] sin precio (valuados a costo)

Shape (~2KB):
{
  "screen": "insights.summary",
  "archetype": str|null,
  "context": { months_tracked, n_positions, missing_prices, total_equity_usd },
  "exposure": {...}, "current_holdings_top": [...], "realized_attribution": {...},
  "drawdown": {...}, "trades": {...},
  "vs_benchmarks": { sp500_pct, inflation_ar_pct },   # SOLO returns propios del bench
  "twr_pct_low_confidence": float|null,               # NO citar como número
  "top_findings": [...], "verdicts": [...],            # lo que el user ya ve
  "ar_bond_holdings": [...],
}
"""
from __future__ import annotations
from typing import Dict, Any, List
import math

from .insights import build as build_insights


def _clean_findings(raw) -> List[Dict[str, Any]]:
    """Sanea los findings que manda el frontend a un shape mínimo y acotado.
    Los findings son diagnósticos ya computados (texto controlado por la app,
    no por el user) — igual recortamos a lo esencial y capeamos el largo."""
    out = []
    if not isinstance(raw, list):
        return out
    for f in raw[:6]:
        if not isinstance(f, dict):
            continue
        out.append({
            "category": str(f.get("category") or "")[:40],
            "severity": str(f.get("severity") or "")[:16],
            "text": str(f.get("text") or "")[:400],
        })
    return out


def _clean_verdicts(raw) -> List[Dict[str, Any]]:
    """Veredictos comparativos ya computados por el frontend ({label, pct})."""
    out = []
    if not isinstance(raw, list):
        return out
    for v in raw[:8]:
        if not isinstance(v, dict):
            continue
        pct = v.get("pct")
        try:
            pct = float(pct) if pct is not None else None
            # NaN/inf (float('nan') NO tira ValueError) → None, para no filtrar
            # valores no-finitos al packet del LLM.
            pct = round(pct, 2) if (pct is not None and math.isfinite(pct)) else None
        except (TypeError, ValueError):
            pct = None
        out.append({"label": str(v.get("label") or "")[:48], "pct": pct})
    return out


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    # ── Toda la valuación pesada la hace el builder de insights (canónica) ──
    base = build_insights(conn, user_id, **kwargs)

    # El TWR compuesto es la métrica con el bug del fantasma → NO como número
    # duro. Lo dejamos con nombre explícito para que el prompt lo bloquee.
    twr_lc = base.get("twr_pct")

    # vs_benchmarks: nos quedamos SOLO con los returns propios de cada benchmark
    # (confiables); los delta_*_pp dependen del twr fantasma → fuera.
    vb = base.get("vs_benchmarks") or {}
    vs_benchmarks = {
        "sp500_pct": vb.get("sp500_pct"),
        "inflation_ar_pct": vb.get("inflation_ar_pct"),
    }

    # Contexto para el modo onboarding + flags de calidad.
    # CONTEO REAL de holdings — NO el largo de current_holdings_top (capado a
    # top-3): mandarle n_positions=3 a la IA la haría narrar "con solo 3
    # posiciones tu cartera está poco diversificada", contradiciendo la card de
    # composición que muestra todas. Contamos activos distintos no-cash.
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT asset) AS c FROM positions "
            "WHERE user_id=? AND is_cash=0 AND quantity>0", (user_id,)
        ).fetchone()
        n_positions = int(row["c"]) if row and row["c"] is not None else len(base.get("current_holdings_top") or [])
    except Exception:  # noqa: BLE001
        n_positions = len(base.get("current_holdings_top") or [])
    # months_tracked lo manda el frontend (globalMonthly.length); si no vino,
    # lo dejamos None (el prompt no asume historial). isfinite: int(inf) lanza
    # OverflowError (no ValueError) → guarda explícita ante un body crafteado.
    months_tracked = kwargs.get("months_tracked")
    try:
        mt = float(months_tracked) if months_tracked is not None else None
        months_tracked = int(mt) if (mt is not None and math.isfinite(mt)) else None
    except (TypeError, ValueError):
        months_tracked = None

    missing = kwargs.get("missing_prices")
    missing_prices = [str(t)[:16] for t in missing[:12]] if isinstance(missing, list) else []

    archetype = kwargs.get("archetype")
    archetype = str(archetype)[:24] if archetype else None

    return {
        "screen": "insights.summary",
        "archetype": archetype,
        "_field_docs": {
            "_doc_scope": "Números server-side canónicos (exposure, holdings, atribución, drawdown, trades) — confiables. NO hay TWR compuesto acá.",
            "twr_pct_low_confidence": "TWR compuesto con baja confianza (bug conocido del motor de retorno). PROHIBIDO citarlo como número. NO digas 'tu cartera hizo X%'. Para performance usá SOLO `verdicts` (lo que el user ya ve).",
            "verdicts": "Veredictos comparativos YA computados y mostrados al user ({label, pct}). Son la ÚNICA fuente para afirmar performance vs inflación/plazo fijo/dólar/S&P. Citá estos, no inventes otros.",
            "top_findings": "Diagnósticos ya rankeados por el motor de la app (lo que el user ve en la lista). Sintetizá 2-3, no los repitas literal.",
            "realized_attribution": "Trades CERRADOS (P&L histórico). status='closed'. NO inferir riesgo presente.",
            "current_holdings_top": "Posiciones ABIERTAS por market value. Para razonar riesgo/concentración usá SOLO esto.",
            "exposure": "Reparto cash/ar/us/crypto en % — server-side canónico.",
        },
        "context": {
            "months_tracked": months_tracked,
            "n_positions": n_positions,
            "missing_prices": missing_prices,
            "total_equity_usd": base.get("total_equity_usd"),
        },
        "exposure": base.get("exposure"),
        "current_holdings_top": base.get("current_holdings_top") or [],
        "realized_attribution": base.get("realized_attribution") or {},
        "unrealized_pnl_total_usd": base.get("unrealized_pnl_total_usd"),
        "drawdown": base.get("drawdown"),
        "trades": base.get("trades"),
        "vs_benchmarks": vs_benchmarks,
        "twr_pct_low_confidence": twr_lc,
        "top_findings": _clean_findings(kwargs.get("findings")),
        "verdicts": _clean_verdicts(kwargs.get("verdicts")),
        "ar_bond_holdings": base.get("ar_bond_holdings") or [],
    }
