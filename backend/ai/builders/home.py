"""builders.home — packet del Home (snapshot rápido del día).
═══════════════════════════════════════════════════════════════════════════
Topic: home

El Home es la primera vista cuando entrás. Mezcla 3 dimensiones:
- Estado de mercado (índices del día — SPY/NDX/blue/etc.).
- Cómo viene la cartera: el MISMO número que muestra la pantalla (ver
  `_resultado_de_la_cartera`; este builder no resta fotos).
- Cards de "lo que te afecta hoy" (holdings que se movieron, eventos
  próximos en tus tickers).

El análisis IA acá responde a la pregunta "¿qué pasó hoy con el mercado
y mi cartera?" sin entrar en el detalle profundo (eso lo hace
Dashboard/Insights).

Shape (~1KB):
{
  "screen": "home",
  "market": {
    "indices": [{ "symbol": str, "kind": str, "change_pct": float | null }],
    "summary": "mostly_up" | "mostly_down" | "mixed" | "flat",
  },
  "portfolio_today": {                  # ver `_resultado_de_la_cartera`
    "origen": "pantalla" | "servidor",
    "hoy": {resultado_usd, resultado_pct, desde, dias, ...} | null,
    "este_mes": {...} | null,           # sólo cuando lo manda la pantalla
    "ultimos_30_dias": {...} | null,
    "nota": str,
  },
  "personal_cards_count": int,         # cuántas cards condicionales aparecen
  "portfolio_events_window": {
    "total": int,                       # eventos próximos en sus tickers
    "weight_at_risk_pct": float,        # % cartera con evento próximo
    "next_event": { ticker, type, days_ahead } | null,
  },
  "top_holdings_pulse": [               # top 3 holdings con su delta del día
    { ticker, weight_pct, change_pct_today | null }
  ],
}
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import date, timedelta

from . import rendimiento_pantalla

# Lo que manda el home del CELULAR (HomeMobile.jsx): las tres cards que muestra,
# "P&L Día", "P&L Mes" y "Últimos 30 días", con la forma de `rendimiento_pantalla`.
_CLAVES_PANTALLA = ("hoy", "mes", "ultimos_30_dias")

# Un número llamado "hoy" puede cubrir varios días (después de un fin de semana
# la card dice "P&L 3d"), y "30 días" puede medir desde otra fecha si faltan
# cierres. El modelo tiene que decir lo mismo que la pantalla, con la fecha.
_NOTA_DIAS = ("`dias` y `desde` dicen qué tramo cubre cada número: si no coinciden con "
              "el nombre (un 'hoy' de 3 días, unos '30 días' que arrancan en otra "
              "fecha), decí desde qué fecha mide. `hasta` es la fecha del final: si "
              "no es hoy, el número no incluye el movimiento de hoy.")


def _resultado_de_la_cartera(conn, uid: int, params: Dict[str, Any]) -> Dict[str, Any]:
    """Cómo viene la cartera — con UN solo dueño por número, y el paquete dice cuál.

    ⚠️ ACÁ HABÍA UNA RESTA A SECAS: el último cierre menos el anterior. Un
    depósito de ayer salía como ganancia de hoy; si los dos últimos cierres eran
    de hace dos semanas, esa resta igual se llamaba "hoy"; y terminaba en el
    cierre de anoche, no en la cartera de ahora. La card "P&L Día" del mismo home
    descuenta los aportes y mide hasta el valor vivo, así que la IA contradecía a
    la pantalla desde la que la llamaron.

      · "pantalla" — el home del CELULAR muestra las tres cards y las manda tal
        cual (ver `rendimiento_pantalla.py`). Si una card dice "—", la IA recibe
        null para esa: no se completa con otra cuenta.
      · "servidor" — el home de ESCRITORIO no muestra ningún número de la
        cartera, y la pregunta del botón es "¿Cómo vengo hoy?". Se usa el de
        Reportes: `_snapshot_delta` hasta el valor vivo de `_valor_vivo_mercado`,
        la misma regla que la card "Hoy" del Dashboard. No es una cuenta nueva:
        es la que ya publica otra pantalla.
    """
    if any(k in params for k in _CLAVES_PANTALLA):
        out = {
            "origen": "pantalla",
            "hoy": rendimiento_pantalla.leer(params.get("hoy")),
            "este_mes": rendimiento_pantalla.leer(params.get("mes")),
            "ultimos_30_dias": rendimiento_pantalla.leer(params.get("ultimos_30_dias")),
            "nota": ("Son los números que el usuario tiene en pantalla: citá esos. "
                     "null = esa card no muestra número; decilo así, no lo calcules. "
                     + _NOTA_DIAS),
        }
        _moneda = rendimiento_pantalla.nota_moneda(params)
        if _moneda:
            out["nota_moneda"] = _moneda
        return out
    try:
        import main as _m
        s = _m._portfolio_snapshot_summary(
            conn, uid, broker_filter="global",
            live_value_override=_m._valor_vivo_mercado(conn, uid)) or {}
    except Exception:
        s = {}
    _hasta = s.get("latest_date")
    return {
        "origen": "servidor",
        "hoy": _de_reportes(s.get("delta_1d"), _hasta),
        "este_mes": None,
        "ultimos_30_dias": _de_reportes(s.get("delta_30d"), _hasta),
        "nota": ("Esta pantalla no muestra números de la cartera: son los de Reportes "
                 "(Δ último cierre y Δ 30 días), con la misma regla que la card 'Hoy' "
                 "del Dashboard. null = no hay un cierre medido con qué comparar. "
                 + _NOTA_DIAS),
    }


def _de_reportes(d, hasta=None) -> Optional[Dict[str, Any]]:
    """Un Δ de `_snapshot_delta`, con la misma forma que los de la pantalla.
    (`pct` ya viene en porcentaje; `flows` son los aportes netos del tramo.)
    `hasta` es la punta: hoy con valor vivo, o el último cierre si faltaron los
    precios — y en ese caso el número no es el de hoy, y el modelo lo tiene que
    saber para no llamarlo así."""
    if not isinstance(d, dict) or d.get("usd") is None or d.get("pct") is None:
        return None
    out: Dict[str, Any] = {"resultado_usd": round(float(d["usd"]), 2),
                           "resultado_pct": round(float(d["pct"]), 2)}
    if d.get("prev_date"):
        out["desde"] = str(d["prev_date"])[:10]
    if d.get("dias"):
        out["dias"] = int(d["dias"])
    if d.get("flows") is not None:
        out["aportes_netos_usd"] = round(float(d["flows"]), 2)
    if d.get("desde"):
        out["rotulo_con_fecha"] = True
    if hasta:
        out["hasta"] = str(hasta)[:10]
    return out


def _market_summary(indices: List[Dict[str, Any]]) -> str:
    """Clasifica el día de mercado en 4 categorías."""
    if not indices:
        return "flat"
    deltas = [i.get("change_pct") for i in indices if i.get("change_pct") is not None]
    if not deltas:
        return "flat"
    up = sum(1 for d in deltas if d > 0.5)
    down = sum(1 for d in deltas if d < -0.5)
    if up >= 4 and down == 0:
        return "mostly_up"
    if down >= 4 and up == 0:
        return "mostly_down"
    if abs(up - down) <= 1:
        return "mixed"
    return "mostly_up" if up > down else "mostly_down"


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    # ── 1. Índices de mercado ────────────────────────────────────────────────
    # Llamamos directo al fetcher de home.market (mismo que /api/home/indices).
    # Tiene su propio cache TTL internamente, así que no duplicamos.
    indices_list: List[Dict[str, Any]] = []
    try:
        from home.market import get_indices_strip
        data = get_indices_strip() or []
        for item in data[:6]:
            indices_list.append({
                "symbol": item.get("symbol") or item.get("name"),
                "kind": item.get("kind") or "index",
                "change_pct": (
                    round(float(item["change_pct"]), 2)
                    if item.get("change_pct") is not None else None
                ),
            })
    except Exception:
        indices_list = []

    market = {
        "indices": indices_list,
        "summary": _market_summary(indices_list),
    }

    # ── 2. Cómo viene la cartera: el número de la pantalla ───────────────────
    portfolio_today = _resultado_de_la_cartera(conn, user_id, kwargs)

    # ── 3. Personal cards count (lo que cambió hoy para el user) ─────────────
    personal_cards_count = 0
    try:
        import main as _m
        rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
                WHERE user_id = ? AND is_cash = 0 AND quantity > 0""",
            (user_id,),
        ).fetchall()
        symbols = [r["asset"] for r in rows if r["asset"]]
        quotes = _m._fetch_batch_quotes(symbols) if symbols else {}
        try:
            events = _m._get_portfolio_events_cached(user_id)
        except Exception:
            events = []
        cards = _m.build_personal_cards(
            conn, user_id, all_quotes=quotes, portfolio_events=events,
        )
        personal_cards_count = len(cards or [])
    except Exception:
        personal_cards_count = 0

    # ── 4. Eventos próximos (14d) ────────────────────────────────────────────
    today = date.today()
    cutoff = today + timedelta(days=14)
    portfolio_assets = [r["asset"] for r in conn.execute(
        """SELECT DISTINCT asset FROM positions
            WHERE user_id = ? AND is_cash = 0 AND quantity > 0""",
        (user_id,),
    ).fetchall() if r["asset"]]

    events_window = {"total": 0, "weight_at_risk_pct": 0.0, "next_event": None}
    if portfolio_assets:
        placeholders = ",".join("?" * len(portfolio_assets))
        ev_rows = conn.execute(
            f"""SELECT ticker, event_type, event_date FROM financial_events
                 WHERE ticker IN ({placeholders})
                   AND event_date >= ? AND event_date <= ?
                 ORDER BY event_date ASC""",
            (*portfolio_assets, today.isoformat(), cutoff.isoformat()),
        ).fetchall()
        events_window["total"] = len(ev_rows)
        if ev_rows:
            first = ev_rows[0]
            try:
                d = date.fromisoformat(str(first["event_date"])[:10])
                days_ahead = (d - today).days
            except (TypeError, ValueError):
                days_ahead = None
            events_window["next_event"] = {
                "ticker": first["ticker"],
                "type": first["event_type"],
                "days_ahead": days_ahead,
            }

            # weight_at_risk_pct: peso combinado de tickers únicos con evento
            # próximo (usamos weights de top_holdings que reusamos arriba).
            try:
                from .dashboard_top_holdings import build as build_top_w
                weights_packet = build_top_w(conn, user_id)
                weights_by_ticker = {
                    h.get("ticker"): h.get("weight_pct", 0)
                    for h in (weights_packet.get("top_holdings") or [])
                }
                affected = {ev["ticker"] for ev in ev_rows if ev["ticker"]}
                w_sum = sum(
                    weights_by_ticker.get(t, 0) for t in affected
                )
                events_window["weight_at_risk_pct"] = round(w_sum, 2)
            except Exception:
                pass

    # ── 5. Top 3 holdings con su delta del día ───────────────────────────────
    # change_pct_today viene de las quotes (cada quote trae change_pct del día).
    top_holdings_pulse: List[Dict[str, Any]] = []
    try:
        from .dashboard_top_holdings import build as build_top
        top_packet = build_top(conn, user_id)
        top_list = top_packet.get("top_holdings") or []

        # Map ticker → change_pct del día desde las quotes que ya fetcheamos
        ticker_change: Dict[str, float] = {}
        try:
            import main as _m
            symbols_for_change = set()
            for h in top_list[:3]:
                t = h.get("ticker")
                if not t:
                    continue
                # broker AR → símbolo termina en .BA
                broker_n = (h.get("broker") or "").lower()
                if broker_n in {"cocos", "cocos capital", "iol", "bull", "balanz", "naranja", "pppi", "invertironline"}:
                    symbols_for_change.add(f"{t}.BA")
                else:
                    symbols_for_change.add(t)
            if symbols_for_change:
                quotes = _m._fetch_batch_quotes(list(symbols_for_change))
                for sym, q in (quotes or {}).items():
                    # `change_pct_today` dice "today" en el nombre, así que sólo
                    # se llena si el quote es de la rueda de HOY. Antes de que
                    # abra el mercado el proveedor sirve el cierre a cierre de
                    # AYER y la IA lo repetía como movimiento del día — el mismo
                    # agujero que mandó cuatro mails de alerta con el
                    # movimiento del lunes fechados como "hoy" (15/09/2026).
                    if q and q.get("change_pct") is not None and q.get("is_today"):
                        base = sym.replace(".BA", "")
                        ticker_change[base] = round(float(q["change_pct"]), 2)
        except Exception:
            ticker_change = {}

        for h in top_list[:3]:
            ticker = h.get("ticker")
            top_holdings_pulse.append({
                "ticker": ticker,
                "weight_pct": h.get("weight_pct"),
                "change_pct_today": ticker_change.get(ticker),
            })
    except Exception:
        top_holdings_pulse = []

    return {
        "screen": "home",
        "market": market,
        "portfolio_today": portfolio_today,
        "personal_cards_count": personal_cards_count,
        "portfolio_events_window": events_window,
        "top_holdings_pulse": top_holdings_pulse,
    }
