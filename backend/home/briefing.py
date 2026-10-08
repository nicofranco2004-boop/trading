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
# El "hoy" de Rendi es el argentino (fechas.py). Con `date.today()` el
# servidor (UTC) ya está en "mañana" de 21 a 24 h de Buenos Aires.
from fechas import hoy_art_date
from reporting.builder import period_label
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


def _precio_txt(h: Dict[str, Any]) -> str:
    """El precio en la moneda en que cotiza: `.BA` es BYMA, en pesos. Decía
    "US$" siempre — un CEDEAR a $27.100 salía "US$27.100,00"."""
    from money_fmt import fmt_money
    ccy = "ARS" if str(h.get("symbol") or "").upper().endswith(".BA") else "USD"
    return fmt_money(h["price"], ccy)


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
            context=_precio_txt(h),
            cta_label="Ver posición →",
            cta_href=f"/posiciones?asset={h['asset']}",
        ))
    return out


# Las tarjetas de eventos dicen lo MISMO que la fila de la agenda de Eventos,
# que es adonde llevan (frontend/src/pages/Events.jsx: `Earnings de X`,
# `Ex-dividendo de X`, "hoy" / "mañana" / "en N días"). Hasta 2026-10-01 la de
# dividendos decía "Dividendo de X · en 2d" en verde — y nunca se vio, porque
# la lectura de eventos apuntaba a una tabla que no existe (ver
# eventos_guardados.py). El ex-dividendo NO es el pago: es el día de corte (hay
# que tener la acción antes para cobrarlo; la plata llega después). Por eso va
# en tono neutro, no verde como si entrara plata.
_TARJETAS_DE_EVENTO = {
    "earnings":    ("earnings_soon", "📊", "Earnings"),
    "ex_dividend": ("dividend_soon", "💰", "Ex-dividendo"),
}


def _en_cuantos_dias(n: int) -> str:
    return "hoy" if n == 0 else ("mañana" if n == 1 else f"en {n} días")


def detect_events_soon(events: List[Dict[str, Any]], holdings_assets: set,
                       event_type: str, dias: int = 7, maximo: int = 2) -> List[PersonalCard]:
    """Eventos `event_type` de activos que el user tiene, en los próximos
    `dias` (contados desde el hoy ARGENTINO)."""
    kind, icon, rotulo = _TARJETAS_DE_EVENTO[event_type]
    out: List[PersonalCard] = []
    today = hoy_art_date()
    cutoff = today + timedelta(days=dias)
    for ev in events:
        if ev.get("event_type") != event_type:
            continue
        ticker = (ev.get("ticker") or "").upper()
        if ticker not in holdings_assets:
            continue
        try:
            ev_date = date_cls.fromisoformat(str(ev["event_date"])[:10])
        except (KeyError, ValueError):
            continue
        if not (today <= ev_date <= cutoff):
            continue
        fecha = period_label("day", ev_date.isoformat(), ev_date.isoformat())
        out.append(PersonalCard(
            kind=kind,
            icon=icon,
            headline=f"{rotulo} de {ticker}",
            value=_en_cuantos_dias((ev_date - today).days),
            value_tone="neutral",
            # "Dom 4 oct", como los informes — no "2026-10-04". Si la empresa
            # todavía no confirmó el día, Yahoo da una estimación (la agenda de
            # Eventos le pone "· est."): la tarjeta no la presenta como un hecho.
            context=fecha if ev.get("confirmed", True) else f"{fecha} · estimada",
            cta_label="Ver detalle →",
            cta_href="/novedades?tab=eventos",
        ))
    return out[:maximo]


def detect_earnings_soon(events: List[Dict[str, Any]],
                          holdings_assets: set) -> List[PersonalCard]:
    """Earnings de holdings en ≤7 días."""
    return detect_events_soon(events, holdings_assets, "earnings")


def detect_dividends_soon(events: List[Dict[str, Any]],
                           holdings_assets: set) -> List[PersonalCard]:
    """Ex-dividendos de holdings en ≤7 días."""
    return detect_events_soon(events, holdings_assets, "ex_dividend")


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
