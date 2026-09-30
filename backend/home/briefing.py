"""Briefing personalizado del Home — "Lo que te afecta".

Selecciona 1-3 cards relevantes para el user basado en sus holdings:
- Holdings que se mueven fuerte hoy (top 3 por |%delta|)
- Earnings próximos de holdings (≤7 días)
- Dividendos próximos de holdings (≤7 días)

Reusa la idea de detectores de `reporting/`, pero genera **PersonalCards**
con shape simple (icon + headline + value + CTA) — no Insights con popover.

V1: solo holdings move + earnings/dividends.
V2: agregamos hitos (cost basis crossed, etc.).
V3: AI explanation de movimientos ("post earnings").
"""
from __future__ import annotations
from money_fmt import fmt_num

import logging
from dataclasses import dataclass, field, asdict
from datetime import date as date_cls, timedelta
from typing import List, Dict, Any, Optional

log = logging.getLogger("home.briefing")


@dataclass
class PersonalCard:
    kind: str                       # 'holding_move' | 'earnings_soon' | 'dividend_soon'
    icon: str                       # emoji
    headline: str                   # 1 línea
    value: str                      # número/string central (ej: "+4.2%")
    value_tone: str = "neutral"     # 'positive' | 'negative' | 'neutral'
    context: Optional[str] = None   # subtexto chico
    cta_label: Optional[str] = None # ej: "Ver posición →"
    cta_href: Optional[str] = None  # ruta interna
    # El número de `value` sin formatear, para que el frontend lo anime (cuenta
    # hasta el valor al aparecer). `value` sigue siendo lo que se lee.
    value_num: Optional[float] = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _user_holdings(conn, uid: int) -> List[Dict[str, Any]]:
    """Devuelve holdings (non-cash) consolidados por activo. Suma quantity
    e invested across brokers — el Home muestra "tenés AAPL" sin importar
    en qué broker está."""
    rows = conn.execute(
        """SELECT asset, SUM(quantity) AS qty, SUM(invested) AS invested
             FROM positions
            WHERE user_id = ? AND is_cash = 0
            GROUP BY asset
            HAVING SUM(quantity) > 0""",
        (uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def _holdings_with_quotes(holdings: List[Dict[str, Any]],
                          quotes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cruza holdings con quotes (de market.py). Devuelve solo los que tienen quote."""
    out = []
    for h in holdings:
        q = quotes.get(h["asset"])
        if not q:
            continue
        out.append({**h, **q})
    return out


# ─── Detectores de PersonalCard ──────────────────────────────────────────────

def _cuando(h: Dict[str, Any]) -> str:
    """"hoy" sólo si el porcentaje ES de la rueda de hoy (`is_today`, que estampa
    home.market._stamp_session). Si no, la fecha de la rueda que midió.

    Decía "subió hoy" siempre: un sábado, o a las 10 de la mañana antes de que
    abra Nueva York, la tarjeta contaba el movimiento del día anterior como de
    hoy — el mismo error que mandó las alertas del 15/09 con el lunes fechado
    como "hoy"."""
    if h.get("is_today"):
        return "hoy"
    as_of = h.get("as_of") or ""
    if len(as_of) == 10:
        return f"el {as_of[8:10]}/{as_of[5:7]}"
    return "en la última rueda"


def detect_holdings_movers(holdings_quoted: List[Dict[str, Any]], top_n: int = 6) -> List[PersonalCard]:
    """Holdings con movimiento ≥1.5% en el día — los más fuertes primero,
    cap top_n. El threshold es estricto en valor absoluto, así que tanto
    rallies como caídas relevantes entran."""
    candidates = [h for h in holdings_quoted if abs(h.get("change_pct", 0)) >= 1.5]
    candidates.sort(key=lambda h: abs(h["change_pct"]), reverse=True)
    out: List[PersonalCard] = []
    for h in candidates[:top_n]:
        pct = h["change_pct"]
        positive = pct > 0
        out.append(PersonalCard(
            kind="holding_move",
            icon="🚀" if positive else "📉",
            headline=f"{h['asset']} {'subió' if positive else 'bajó'} {_cuando(h)}",
            value=f"{'+' if positive else ''}{fmt_num(pct, 1)}%",
            value_num=round(pct, 1),
            value_tone="positive" if positive else "negative",
            context=f"US${fmt_num(h['price'], 2)}",
            cta_label="Ver posición →",
            cta_href=f"/posiciones?asset={h['asset']}",
        ))
    return out


def detect_earnings_soon(events: List[Dict[str, Any]],
                          holdings_assets: set) -> List[PersonalCard]:
    """Earnings de holdings en ≤7 días."""
    out: List[PersonalCard] = []
    today = date_cls.today()
    cutoff = today + timedelta(days=7)
    for ev in events:
        if ev.get("event_type") != "earnings":
            continue
        ticker = (ev.get("ticker") or "").upper()
        if ticker not in holdings_assets:
            continue
        try:
            ev_date = date_cls.fromisoformat(ev["event_date"])
        except (KeyError, ValueError):
            continue
        if not (today <= ev_date <= cutoff):
            continue
        days_until = (ev_date - today).days
        when = "hoy" if days_until == 0 else (
            "mañana" if days_until == 1 else f"en {days_until} días"
        )
        out.append(PersonalCard(
            kind="earnings_soon",
            icon="📊",
            headline=f"Earnings de {ticker}",
            value=when,
            value_tone="neutral",
            context=ev["event_date"],
            cta_label="Ver detalle →",
            cta_href=f"/novedades?tab=eventos",
        ))
    return out[:2]


def detect_dividends_soon(events: List[Dict[str, Any]],
                           holdings_assets: set) -> List[PersonalCard]:
    """Dividendos de holdings en ≤7 días (ex_dividend)."""
    out: List[PersonalCard] = []
    today = date_cls.today()
    cutoff = today + timedelta(days=7)
    for ev in events:
        if ev.get("event_type") != "ex_dividend":
            continue
        ticker = (ev.get("ticker") or "").upper()
        if ticker not in holdings_assets:
            continue
        try:
            ev_date = date_cls.fromisoformat(ev["event_date"])
        except (KeyError, ValueError):
            continue
        if not (today <= ev_date <= cutoff):
            continue
        days_until = (ev_date - today).days
        when = "hoy" if days_until == 0 else f"en {days_until}d"
        out.append(PersonalCard(
            kind="dividend_soon",
            icon="💰",
            headline=f"Dividendo de {ticker}",
            value=when,
            value_tone="positive",
            context=ev["event_date"],
            cta_label="Ver →",
            cta_href=f"/novedades?tab=eventos",
        ))
    return out[:2]


# ─── Orchestrator ────────────────────────────────────────────────────────────

def build_personal_cards(conn, uid: int, *,
                          all_quotes: Dict[str, Dict[str, Any]],
                          portfolio_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compone hasta 4 cards personales para el Home.

    Args:
        all_quotes: dict {symbol: {price, change_pct, prev_close}} — de market.py
        portfolio_events: lista de eventos del user (de /api/events/portfolio)
    """
    holdings = _user_holdings(conn, uid)
    if not holdings:
        return []  # user sin portfolio → no se renderiza la sección

    holdings_quoted = _holdings_with_quotes(holdings, all_quotes)
    holdings_assets = {h["asset"].upper() for h in holdings}

    cards: List[PersonalCard] = []
    cards.extend(detect_holdings_movers(holdings_quoted, top_n=6))
    cards.extend(detect_earnings_soon(portfolio_events, holdings_assets))
    cards.extend(detect_dividends_soon(portfolio_events, holdings_assets))

    # Cap a 8 — el grid del frontend es 4 cols (2 filas máx). Movers van
    # primero, luego earnings, luego dividends.
    return [asdict(c) for c in cards[:8]]
