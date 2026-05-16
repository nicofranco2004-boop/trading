"""Integration smoke tests para TODOS los builders de IA contra la DB real.

═══════════════════════════════════════════════════════════════════════════
Objetivo: detectar el tipo de bug que se nos coló en el builder del Home
(claves vacías por mismatch, campos importantes que quedan en None o lista
vacía silenciosamente).

Strategy: cargamos la BD de dev (`trading.db`) con cuenta admin (uid=2)
que tiene datos reales (posiciones, operaciones, snapshots, eventos).
Para cada topic, instanciamos el builder y verificamos un set de
"healthy data assertions" — campos clave que NO deberían estar vacíos
para esta cuenta específica.

Si un campo viene en None / [] / 0 inesperadamente, falla con un
mensaje explicando qué campo y para qué builder. Cuando agreguemos un
topic nuevo, sumamos su assertion acá y queda blindado contra
regresiones tipo "se me olvidó popular el field".

Si no existe `trading.db` (ej. CI fresh), los tests se SKIP — no
queremos romper la suite en environments sin datos cargados.
"""
from __future__ import annotations
import os
import sqlite3
import pytest


TRADING_DB = os.path.join(
    os.path.dirname(__file__), "..", "trading.db"
)
ADMIN_UID = 2


def _real_db():
    """Conexión a la DB real de dev. Skip si no existe o no tiene data."""
    if not os.path.exists(TRADING_DB):
        pytest.skip("trading.db no existe — saltando integration tests")
    conn = sqlite3.connect(TRADING_DB)
    conn.row_factory = sqlite3.Row
    # Verificar que el admin existe y tiene datos
    try:
        row = conn.execute(
            "SELECT 1 FROM users WHERE id = ? AND is_admin = 1", (ADMIN_UID,)
        ).fetchone()
        if not row:
            pytest.skip(f"Admin uid={ADMIN_UID} no existe en trading.db")
    except sqlite3.OperationalError:
        pytest.skip("trading.db no tiene tabla users")
    return conn


# ════════════════════════════════════════════════════════════════════════════
# Helpers para assertions densas
# ════════════════════════════════════════════════════════════════════════════

def _assert_packet_screen(packet, expected_screen):
    assert isinstance(packet, dict), (
        f"Packet debe ser dict, recibido: {type(packet).__name__}"
    )
    assert packet.get("screen") == expected_screen, (
        f"screen esperado='{expected_screen}', recibido='{packet.get('screen')}'"
    )


def _assert_nonempty_list(packet, key, min_len=1):
    val = packet.get(key)
    assert isinstance(val, list), (
        f"{key} debería ser lista (es {type(val).__name__}). Packet: {packet}"
    )
    assert len(val) >= min_len, (
        f"{key} viene con {len(val)} items, esperábamos >= {min_len}. "
        f"Posible bug de claves vacías (estilo Home → top_holdings)."
    )


def _assert_nonzero(packet, key):
    val = packet.get(key)
    assert val is not None and val != 0, (
        f"{key} viene en {val!r} — sospechoso, esperábamos algo > 0 con datos reales."
    )


def _assert_has(packet, key):
    assert key in packet, f"Falta key '{key}' en packet"


# ════════════════════════════════════════════════════════════════════════════
# Dashboard (6 topics)
# ════════════════════════════════════════════════════════════════════════════

class TestDashboardIntegration:

    def test_dashboard_general(self):
        from ai.builders.dashboard import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "dashboard")
        # Dashboard general anida en `portfolio` + `behavioral` + `benchmarks`
        _assert_has(p, "portfolio")
        portfolio = p["portfolio"] or {}
        # El builder usa `value_usd` históricamente — no tocamos para no
        # romper el prompt actual de dashboard que ya espera ese nombre.
        assert portfolio.get("value_usd") is not None, (
            f"portfolio.value_usd faltante en packet: {list(portfolio.keys())}"
        )
        # Métricas core deben estar
        assert "twr_30d_pct" in portfolio or "twr_lifetime_pct" in portfolio
        assert "positions_count" in portfolio

    def test_dashboard_composition_top_holdings(self):
        from ai.builders.dashboard_composition import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "dashboard.composition")
        # Composition: top holdings con peso
        _assert_nonempty_list(p, "top_holdings", min_len=3)
        # Cada holding debe tener weight_pct válido
        for h in p["top_holdings"]:
            assert h.get("weight_pct") is not None, f"holding sin weight: {h}"
        # HHI debe estar en [0, 1]
        assert 0 <= p.get("hhi", 0) <= 1, f"hhi fuera de rango: {p.get('hhi')}"

    def test_dashboard_evolution_has_points(self):
        from ai.builders.dashboard_evolution import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "dashboard.evolution")
        # Evolution usa `points`, no `series`
        if not p.get("insufficient_data"):
            _assert_has(p, "points")
            # Debe tener al menos peak/trough/delta para que el LLM tenga material
            _assert_has(p, "peak")
            _assert_has(p, "trough")

    def test_dashboard_top_holdings_field_consistency(self):
        """Verifica el fix del bug — clave 'top_holdings' (no 'holdings')."""
        from ai.builders.dashboard_top_holdings import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "dashboard.top_holdings")
        # CRÍTICO: la clave debe ser 'top_holdings', no 'holdings'.
        assert "top_holdings" in p, (
            "Clave 'top_holdings' falta — esto rompe 4 builders downstream "
            "(home, news, events, insights.observation). Ver fix anterior."
        )
        assert "holdings" not in p, (
            "Clave 'holdings' aparece — debería ser 'top_holdings'."
        )
        _assert_nonempty_list(p, "top_holdings", min_len=3)
        # Cada item debe tener 'ticker' (no 'asset')
        for h in p["top_holdings"]:
            assert "ticker" in h, f"falta 'ticker' en holding: {h}"
            assert h.get("weight_pct") is not None

    def test_dashboard_brokers_has_breakdown(self):
        from ai.builders.dashboard_brokers import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "dashboard.brokers")
        _assert_has(p, "broker_count")
        if p.get("broker_count", 0) > 0:
            _assert_nonempty_list(p, "brokers")

    def test_dashboard_upcoming_events_shape(self):
        from ai.builders.dashboard_events import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "dashboard.upcoming_events")
        _assert_has(p, "events")
        _assert_has(p, "total_events")


# ════════════════════════════════════════════════════════════════════════════
# Behavioral (2 topics)
# ════════════════════════════════════════════════════════════════════════════

class TestBehavioralIntegration:

    def test_behavioral_general(self):
        from ai.builders.behavioral import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "behavioral")
        # Siempre debe traer las 12 cards
        _assert_nonempty_list(p, "cards", min_len=12)
        for c in p["cards"]:
            assert "code" in c
            assert "severity" in c

    def test_behavioral_card_specific(self):
        from ai.builders.behavioral_card import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, code="winrate_payoff")
        _assert_packet_screen(p, "behavioral.card")
        assert p["card"]["code"] == "winrate_payoff"
        assert p["card"].get("evidence") is not None
        _assert_has(p, "context")


# ════════════════════════════════════════════════════════════════════════════
# Insights (5 topics)
# ════════════════════════════════════════════════════════════════════════════

class TestInsightsIntegration:

    def test_insights_general(self):
        from ai.builders.insights import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, window_days=365)
        _assert_packet_screen(p, "insights")
        # Crítico: TWR no debe venir absurdamente negativo (bug previo
        # detectado y arreglado — usar monthly_entries, no snapshot deltas).
        if p.get("twr_pct") is not None:
            assert p["twr_pct"] > -50, (
                f"twr_pct={p['twr_pct']}% — sospechosamente negativo. "
                f"Posible regresión del cálculo TWR via snapshots crudos."
            )
        _assert_has(p, "exposure")
        # Exposure mix no debería ser todo 0 con cuenta con posiciones
        exposure = p["exposure"]
        total_exp = sum(
            v for v in exposure.values() if isinstance(v, (int, float))
        )
        assert total_exp > 0, f"exposure todo en 0: {exposure}"

    def test_insights_evolution(self):
        from ai.builders.insights_evolution import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, window_days=365)
        _assert_packet_screen(p, "insights.evolution")
        _assert_has(p, "monthly_returns")

    def test_insights_drawdown(self):
        from ai.builders.insights_drawdown import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, window_days=365)
        _assert_packet_screen(p, "insights.drawdown")
        _assert_has(p, "current_pct")
        _assert_has(p, "max_pct")

    def test_insights_attribution(self):
        from ai.builders.insights_attribution import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "insights.attribution")
        # Con cuenta con trades cerrados, debería haber contributors
        _assert_has(p, "top_contributors")
        _assert_has(p, "total_pnl_usd")

    def test_insights_benchmarks(self):
        from ai.builders.insights_benchmarks import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, window_days=365)
        _assert_packet_screen(p, "insights.benchmarks")
        # benchmarks pueden ser None si bench cache no está poblado — OK
        _assert_has(p, "benchmarks")
        _assert_has(p, "deltas_pp")

    def test_insights_observation_with_context(self):
        from ai.builders.insights_observation import build
        conn = _real_db()
        p = build(
            conn, ADMIN_UID,
            title="Concentración elevada",
            text="NVDA representa el 28% del portfolio",
            category="Riesgo",
            level="warning",
            id="D7",
        )
        _assert_packet_screen(p, "insights.observation")
        # Verifica que portfolio_context se popula (bug detectado en Home).
        ctx = p.get("portfolio_context") or {}
        # Al menos uno de estos campos críticos debe tener data
        critical_fields = ["total_value_usd", "twr_pct", "top_contributors"]
        has_any = any(
            ctx.get(f) is not None and ctx.get(f) != [] for f in critical_fields
        )
        assert has_any, (
            f"portfolio_context viene vacío. Campos críticos: "
            f"{ {f: ctx.get(f) for f in critical_fields} }"
        )


# ════════════════════════════════════════════════════════════════════════════
# Phase 2 — Reports, Position, Goal, Monthly
# ════════════════════════════════════════════════════════════════════════════

class TestPhase2Integration:

    def test_monthly_with_data(self):
        """Test monthly del mes en curso para el admin."""
        from datetime import date
        from ai.builders.monthly import build
        conn = _real_db()
        today = date.today()
        p = build(conn, ADMIN_UID, year=today.year, month=today.month)
        _assert_packet_screen(p, "monthly")
        _assert_has(p, "metrics")

    def test_position_real(self):
        """Si el admin tiene posiciones, position builder debe responder."""
        from ai.builders.position import build
        conn = _real_db()
        row = conn.execute(
            "SELECT asset, broker FROM positions "
            "WHERE user_id=? AND is_cash=0 AND quantity>0 LIMIT 1",
            (ADMIN_UID,),
        ).fetchone()
        if not row:
            pytest.skip("Admin sin posiciones para testear position builder")
        p = build(conn, ADMIN_UID, asset=row["asset"], broker=row["broker"])
        _assert_packet_screen(p, "position")
        _assert_nonzero(p, "qty")
        _assert_nonzero(p, "invested_usd")

    def test_position_lots_real(self):
        from ai.builders.position_lots import build
        conn = _real_db()
        row = conn.execute(
            "SELECT asset FROM positions "
            "WHERE user_id=? AND is_cash=0 AND quantity>0 LIMIT 1",
            (ADMIN_UID,),
        ).fetchone()
        if not row:
            pytest.skip("Admin sin posiciones")
        p = build(conn, ADMIN_UID, asset=row["asset"])
        _assert_packet_screen(p, "position.lots")
        _assert_has(p, "pattern")
        _assert_has(p, "lots_count")

    def test_reports_year(self):
        """reports debe tener consistency, twr y best/worst month."""
        from datetime import date
        from ai.builders.reports import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, year=date.today().year)
        _assert_packet_screen(p, "reports")
        _assert_has(p, "consistency")
        _assert_has(p, "winrate_monthly")
        _assert_has(p, "twr_year_pct")
        # Si total_months_active > 0, best_month no puede ser None
        if p["total_months_active"] > 0:
            assert p["best_month"] is not None, (
                f"reports con {p['total_months_active']} meses activos pero "
                f"best_month=None — bug del detector best/worst."
            )

    def test_goal_real(self):
        from ai.builders.goal import build
        conn = _real_db()
        row = conn.execute(
            "SELECT id FROM goals WHERE user_id=? LIMIT 1", (ADMIN_UID,)
        ).fetchone()
        if not row:
            pytest.skip("Admin sin goals")
        p = build(conn, ADMIN_UID, goal_id=row["id"])
        _assert_packet_screen(p, "goal")
        _assert_has(p, "goal")
        _assert_has(p, "progress")
        # Con datos reales, target_usd debe ser > 0
        _assert_nonzero(p["goal"], "target_usd")


# ════════════════════════════════════════════════════════════════════════════
# Phase 3 — Home, News, Events
# ════════════════════════════════════════════════════════════════════════════

class TestPhase3Integration:

    def test_home_packet_complete(self):
        """REGRESIÓN: Home no debe traer top_holdings_pulse=[] ni indices=[].
        Este es exactamente el bug del review."""
        from ai.builders.home import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "home")

        # Bug fix verifications:
        _assert_nonempty_list(
            p["market"], "indices", min_len=1
        )
        _assert_nonempty_list(
            p, "top_holdings_pulse", min_len=1
        )
        # Cada top holding debe tener weight_pct
        for h in p["top_holdings_pulse"]:
            assert h.get("weight_pct") is not None, (
                f"top_holdings_pulse item sin weight_pct: {h}"
            )
        # Eventos próximos: si total > 0, weight_at_risk_pct debe ser > 0
        ev = p.get("portfolio_events_window") or {}
        if ev.get("total", 0) > 0:
            assert ev.get("weight_at_risk_pct", 0) > 0, (
                f"events_window con total={ev['total']} pero "
                f"weight_at_risk_pct={ev.get('weight_at_risk_pct')} — "
                f"bug del calculator weight_at_risk."
            )

    def test_news_general(self):
        from ai.builders.news import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, window_days=7)
        _assert_packet_screen(p, "news")
        _assert_has(p, "total_news")
        _assert_has(p, "tickers_covered")
        _assert_has(p, "headlines")

    def test_news_item_with_position(self):
        """news.item para un ticker que el user tiene debe mostrar holds_ticker=True."""
        from ai.builders.news_item import build
        conn = _real_db()
        row = conn.execute(
            "SELECT asset FROM positions "
            "WHERE user_id=? AND is_cash=0 AND quantity>0 LIMIT 1",
            (ADMIN_UID,),
        ).fetchone()
        if not row:
            pytest.skip("Admin sin posiciones")
        p = build(
            conn, ADMIN_UID,
            ticker=row["asset"],
            title=f"Noticia sobre {row['asset']}",
            source="Test",
        )
        _assert_packet_screen(p, "news.item")
        ctx = p["portfolio_context"]
        assert ctx["holds_ticker"] is True, (
            f"holds_ticker=False para ticker que el user tiene ({row['asset']})"
        )
        # weight_pct y broker deben estar populados
        assert ctx.get("weight_pct") is not None, (
            f"weight_pct=None para ticker que el user tiene"
        )
        assert ctx.get("broker") is not None

    def test_events_general(self):
        from ai.builders.events import build
        conn = _real_db()
        p = build(conn, ADMIN_UID, window_days=60)
        _assert_packet_screen(p, "events")
        _assert_has(p, "total_events")
        _assert_has(p, "by_type")
        _assert_has(p, "by_horizon")
        # Si hay eventos, weight_at_risk_pct debe estar populado (no 0
        # si los tickers tienen weight)
        if p["total_events"] > 0:
            _assert_has(p, "weight_at_risk_pct")


# ════════════════════════════════════════════════════════════════════════════
# Operations (2 topics)
# ════════════════════════════════════════════════════════════════════════════

class TestOperationsIntegration:

    def test_operations_general(self):
        from ai.builders.operations import build
        conn = _real_db()
        p = build(conn, ADMIN_UID)
        _assert_packet_screen(p, "operations")
        _assert_has(p, "total_closed")
        _assert_has(p, "win_rate")
        # Si hay trades cerrados, los campos críticos deben estar populados
        if p["total_closed"] > 0:
            assert p["best_trade"] is not None, "best_trade=None con trades cerrados"
            assert p["worst_trade"] is not None, "worst_trade=None con trades cerrados"
            assert p["avg_win_usd"] is not None or p["winners_count"] == 0
            _assert_nonempty_list(p, "top_traded_tickers", min_len=1)

    def test_operations_trade_specific(self):
        from ai.builders.operation_trade import build
        conn = _real_db()
        row = conn.execute(
            """SELECT id FROM operations
               WHERE user_id=? AND pnl_usd IS NOT NULL
                 AND op_type NOT IN ('Compra', 'Dividendo', 'Interés', '')
                 AND op_type NOT LIKE 'CONVERSION%'
                 AND op_type NOT LIKE 'Conversión%'
               LIMIT 1""",
            (ADMIN_UID,),
        ).fetchone()
        if not row:
            pytest.skip("Admin sin trades cerrados")
        p = build(conn, ADMIN_UID, operation_id=row["id"])
        _assert_packet_screen(p, "operations.trade")
        _assert_has(p, "trade")
        _assert_has(p, "user_context")
        # rank_in_year debe estar populado (no None) si hay trades
        ctx = p["user_context"]
        assert ctx.get("rank_in_year") is not None, (
            f"rank_in_year=None — bug del ranker."
        )


# ════════════════════════════════════════════════════════════════════════════
# Catch-all: every topic in REGISTRY corre sin crash con datos reales
# ════════════════════════════════════════════════════════════════════════════

def test_all_topics_smoke_no_crash():
    """Sanity: cada topic del REGISTRY se puede ejecutar sin crash con
    params mínimos viables. Si falla, el topic no estaba dimensionado para
    correr en datos reales — bug latente."""
    from ai.registry import REGISTRY
    from datetime import date
    conn = _real_db()

    # Datos auxiliares
    pos_row = conn.execute(
        "SELECT asset, broker FROM positions "
        "WHERE user_id=? AND is_cash=0 AND quantity>0 LIMIT 1",
        (ADMIN_UID,),
    ).fetchone()
    op_row = conn.execute(
        """SELECT id FROM operations
           WHERE user_id=? AND pnl_usd IS NOT NULL
             AND op_type NOT IN ('Compra', 'Dividendo', 'Interés', '')
           LIMIT 1""",
        (ADMIN_UID,),
    ).fetchone()
    goal_row = conn.execute(
        "SELECT id FROM goals WHERE user_id=? LIMIT 1", (ADMIN_UID,)
    ).fetchone()
    today = date.today()

    # Params por topic (los que necesitan params)
    params_by_topic = {
        "behavioral.card": {"code": "winrate_payoff"},
        "insights.observation": {
            "title": "Test obs", "text": "Test",
            "category": "Riesgo", "level": "info", "id": "T1",
        },
        "monthly": {"year": today.year, "month": today.month},
        "monthly.insight": {
            "year": today.year, "month": today.month,
            "code": "test", "text": "Test", "severity": "info",
        },
        "news.item": {
            "ticker": (pos_row["asset"] if pos_row else "NVDA"),
            "title": "Test news",
        },
        "events.item": {
            "ticker": (pos_row["asset"] if pos_row else "NVDA"),
            "event_type": "earnings",
            "event_date": "2026-06-01",
        },
    }

    if pos_row:
        params_by_topic["position"] = {"asset": pos_row["asset"], "broker": pos_row["broker"]}
        params_by_topic["position.chart"] = {"asset": pos_row["asset"], "broker": pos_row["broker"]}
        params_by_topic["position.lots"] = {"asset": pos_row["asset"], "broker": pos_row["broker"]}
    if op_row:
        params_by_topic["operations.trade"] = {"operation_id": op_row["id"]}
    if goal_row:
        params_by_topic["goal"] = {"goal_id": goal_row["id"]}

    failures = []
    for topic, (builder, _) in REGISTRY.items():
        if topic in {"position", "position.chart", "position.lots"} and not pos_row:
            continue
        if topic == "operations.trade" and not op_row:
            continue
        if topic == "goal" and not goal_row:
            continue
        params = params_by_topic.get(topic, {})
        try:
            packet = builder(conn, ADMIN_UID, **params)
            assert isinstance(packet, dict), (
                f"{topic} no devolvió dict"
            )
            assert packet.get("screen"), (
                f"{topic} sin 'screen' field"
            )
        except Exception as ex:
            failures.append(f"{topic}: {type(ex).__name__}: {ex}")

    assert not failures, (
        f"Builders que crashearon en datos reales:\n  " + "\n  ".join(failures)
    )
