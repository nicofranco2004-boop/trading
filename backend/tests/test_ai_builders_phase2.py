"""Tests para los 6 builders de Phase 2 (Monthly + Position + Goals).

Cubre:
- ai/builders/monthly.py
- ai/builders/monthly_insight.py
- ai/builders/position.py
- ai/builders/position_chart.py
- ai/builders/position_lots.py
- ai/builders/goal.py

Estrategia: SQLite in-memory con las tablas que cada builder consume +
mocks para servicios externos (precios, snapshots) donde aplique.
"""
from __future__ import annotations
import sqlite3
import pytest
from unittest.mock import patch


# ── Fixtures compartidas ─────────────────────────────────────────────────────

def _base_db():
    """SQLite in-memory con TODAS las tablas que los builders Phase 2 tocan.
    Schema lo más liviano posible — solo lo que se lee."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, email TEXT, is_admin INTEGER DEFAULT 0
        );
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            broker TEXT, asset TEXT,
            quantity REAL, invested REAL,
            is_cash INTEGER DEFAULT 0,
            entry_date TEXT
        );
        CREATE TABLE brokers (
            user_id INTEGER, name TEXT, currency TEXT,
            PRIMARY KEY (user_id, name)
        );
        CREATE TABLE config (
            user_id INTEGER, key TEXT, value TEXT,
            PRIMARY KEY (user_id, key)
        );
        CREATE TABLE operations (
            id INTEGER PRIMARY KEY,
            user_id INTEGER, date TEXT, broker TEXT, asset TEXT,
            op_type TEXT, entry_price REAL, exit_price REAL,
            quantity REAL, pnl_usd REAL, pnl_pct REAL, commissions REAL,
            entry_date TEXT
        );
        CREATE TABLE snapshots (
            user_id INTEGER, date TEXT,
            total_value REAL, total_invested REAL, net_deposited REAL,
            PRIMARY KEY (user_id, date)
        );
        CREATE TABLE monthly_entries (
            id INTEGER PRIMARY KEY,
            user_id INTEGER, year INTEGER, month INTEGER, broker TEXT,
            deposits REAL DEFAULT 0, withdrawals REAL DEFAULT 0,
            pnl_realized REAL DEFAULT 0, pnl_unrealized REAL DEFAULT 0,
            capital_inicio REAL, capital_final REAL,
            UNIQUE (user_id, year, month, broker)
        );
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY,
            user_id INTEGER, label TEXT,
            target_usd REAL, target_date TEXT,
            monthly_contribution REAL,
            expected_return_pct REAL,
            current_capital REAL DEFAULT 0,
            created_at TEXT
        );
    """)
    # User Pro de prueba
    conn.execute("INSERT INTO users (id, email, is_admin) VALUES (1, 't@t.com', 0)")
    conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (1, 'Schwab', 'USD')")
    conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (1, 'Cocos', 'ARS')")
    conn.execute("INSERT INTO config (user_id, key, value) VALUES (1, 'tc_blue', '1415')")
    return conn


# ════════════════════════════════════════════════════════════════════════════
# monthly.py
# ════════════════════════════════════════════════════════════════════════════

class TestMonthlyBuilder:

    def test_requires_year_and_month(self):
        from ai.builders.monthly import build
        conn = _base_db()
        with pytest.raises(ValueError, match="year"):
            build(conn, 1)
        with pytest.raises(ValueError, match="month"):
            build(conn, 1, year=2026)

    def test_invalid_month_value(self):
        from ai.builders.monthly import build
        conn = _base_db()
        with pytest.raises(ValueError, match="month inválido"):
            build(conn, 1, year=2026, month=13)
        with pytest.raises(ValueError, match="month inválido"):
            build(conn, 1, year=2026, month=0)

    def test_non_int_params_raise(self):
        from ai.builders.monthly import build
        conn = _base_db()
        with pytest.raises(ValueError, match="enteros"):
            build(conn, 1, year="abc", month=5)

    def test_packet_shape_with_monthly_entry(self):
        """Builder con un monthly_entries básico — debe devolver shape completo."""
        conn = _base_db()
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id, year, month, broker, deposits, pnl_realized, pnl_unrealized,
                capital_inicio, capital_final)
               VALUES (1, 2026, 5, 'global', 1000, 200, 300, 10000, 11500)"""
        )
        from ai.builders.monthly import build
        # Mock external bench cache + snapshot live value
        with patch("main._bench_cache", {"data": {"inflation_ar": {}, "sp500": {}}}, create=True), \
             patch("main._latest_snapshot_value", return_value=11500.0, create=True):
            p = build(conn, 1, year=2026, month=5)

        assert p["screen"] == "monthly"
        assert p["period"]["year"] == 2026
        assert p["period"]["month"] == 5
        assert "metrics" in p
        assert "delta_pct" in p["metrics"]
        assert "delta_usd" in p["metrics"]
        # Best/worst trade pueden ser None si no hay ops — está bien
        assert "best_trade" in p
        assert "worst_trade" in p
        assert "top_drivers" in p


# ════════════════════════════════════════════════════════════════════════════
# monthly_insight.py
# ════════════════════════════════════════════════════════════════════════════

class TestMonthlyInsightBuilder:

    def test_requires_year_month_and_text(self):
        from ai.builders.monthly_insight import build
        conn = _base_db()
        with pytest.raises(ValueError, match="year"):
            build(conn, 1, text="something")
        with pytest.raises(ValueError, match="text"):
            build(conn, 1, year=2026, month=5)

    def test_packet_contains_observation_and_context(self):
        conn = _base_db()
        # Sumamos un monthly_entry para que el contexto se pueda calcular
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id, year, month, broker, capital_inicio, capital_final)
               VALUES (1, 2026, 5, 'global', 10000, 11000)"""
        )
        from ai.builders.monthly_insight import build
        with patch("main._bench_cache", {"data": {"inflation_ar": {}, "sp500": {}}}, create=True), \
             patch("main._latest_snapshot_value", return_value=11000.0, create=True):
            p = build(
                conn, 1,
                year=2026, month=5,
                code="gain_concentration",
                text="BTC explicó el 64% del rendimiento",
                severity="warn",
            )

        assert p["screen"] == "monthly.insight"
        assert p["insight"]["code"] == "gain_concentration"
        assert p["insight"]["severity"] == "warn"
        assert "BTC" in p["insight"]["text"]
        assert "month_context" in p
        assert "period" in p
        assert p["period"]["year"] == 2026

    def test_handles_missing_month_context_gracefully(self):
        """Si no hay datos del mes, el builder no rompe — devuelve insight
        + context vacío."""
        conn = _base_db()
        from ai.builders.monthly_insight import build
        # No monthly_entries — el build_monthly interno va a fallar
        with patch("main._bench_cache", {}, create=True), \
             patch("main._latest_snapshot_value", return_value=None, create=True):
            p = build(
                conn, 1,
                year=2099, month=1,
                code="test_code",
                text="Texto del insight",
                severity="info",
            )
        # No crash. insight viene, month_context puede venir vacío
        assert p["insight"]["text"] == "Texto del insight"


# ════════════════════════════════════════════════════════════════════════════
# position.py
# ════════════════════════════════════════════════════════════════════════════

class TestPositionBuilder:

    def test_requires_asset(self):
        from ai.builders.position import build
        conn = _base_db()
        with pytest.raises(ValueError, match="asset"):
            build(conn, 1)

    def test_position_not_found_raises(self):
        from ai.builders.position import build
        conn = _base_db()
        with pytest.raises(ValueError, match="no encontrada"):
            build(conn, 1, asset="NONEXISTENT")

    def test_packet_shape_basic_usd(self):
        """Posición en Schwab (USD) — sin requiere conversión ni precio externo
        (fallback a invested)."""
        conn = _base_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested)
               VALUES (1, 'Schwab', 'NVDA', 10, 5000)"""
        )
        from ai.builders.position import build
        # Mock fetch_batch_quotes para que falle silenciosamente → fallback
        with patch("home.market._fetch_batch_quotes", side_effect=Exception("no internet")):
            p = build(conn, 1, asset="NVDA")
        assert p["screen"] == "position"
        assert p["asset"] == "NVDA"
        assert p["broker"] == "Schwab"
        assert p["currency"] == "USD"
        assert p["qty"] == 10.0
        assert p["avg_price"] == 500.0
        assert p["invested_usd"] == 5000.0
        # Sin precio actual → current_value ≈ invested
        assert p["current_value_usd"] == 5000.0
        assert p["pnl_usd"] == 0.0

    def test_aggregates_multiple_rows(self):
        """Dos lotes de la misma posición → builder agrega qty + invested."""
        conn = _base_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'NVDA', 5, 2500)"
        )
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'NVDA', 10, 6000)"
        )
        from ai.builders.position import build
        with patch("home.market._fetch_batch_quotes", side_effect=Exception):
            p = build(conn, 1, asset="NVDA", broker="Schwab")
        assert p["qty"] == 15.0
        assert p["invested_usd"] == 8500.0
        # avg_price = invested / qty = 8500 / 15 ≈ 566.67
        assert abs(p["avg_price"] - 566.67) < 0.01

    def test_ars_broker_uses_tc_blue_conversion(self):
        """Posición en Cocos (ARS): invested = pesos, builder convierte a USD."""
        conn = _base_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Cocos', 'GGAL', 100, 141500)"  # 100 ARS each
        )
        from ai.builders.position import build
        with patch("home.market._fetch_batch_quotes", side_effect=Exception):
            p = build(conn, 1, asset="GGAL")
        # 141500 ARS / 1415 tc_blue = 100 USD
        assert p["currency"] == "ARS"
        assert p["invested_usd"] == 100.0

    def test_broker_filter_disambiguates(self):
        """Mismo asset en dos brokers — broker param filtra correctamente."""
        conn = _base_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'AAPL', 10, 1500)"
        )
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Cocos', 'AAPL', 20, 280000)"  # CEDEAR en ARS
        )
        from ai.builders.position import build
        with patch("home.market._fetch_batch_quotes", side_effect=Exception):
            p_schwab = build(conn, 1, asset="AAPL", broker="Schwab")
            p_cocos = build(conn, 1, asset="AAPL", broker="Cocos")
        assert p_schwab["qty"] == 10
        assert p_schwab["currency"] == "USD"
        assert p_cocos["qty"] == 20
        assert p_cocos["currency"] == "ARS"


# ════════════════════════════════════════════════════════════════════════════
# position_chart.py
# ════════════════════════════════════════════════════════════════════════════

class TestPositionChartBuilder:

    def test_shape_with_no_price_history(self):
        """Sin price history → builder devuelve series vacía pero no crashea."""
        conn = _base_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'AAPL', 10, 1500)"
        )
        from ai.builders.position_chart import build
        with patch("home.market._fetch_batch_quotes", side_effect=Exception), \
             patch("main._fetch_price_history", return_value={}, create=True):
            p = build(conn, 1, asset="AAPL")
        assert p["screen"] == "position.chart"
        assert p["asset"] == "AAPL"
        assert p["price_series_30d"] == []
        assert p["drawdown_recent_pct"] == 0.0

    def test_drawdown_computation_with_history(self):
        """Con historia: peak en el medio + caída al final → drawdown negativo."""
        conn = _base_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'AAPL', 10, 1500)"
        )
        # Serie con peak 200 y último valor 180 → DD = -10%
        hist = {
            "2026-05-01": 150.0,
            "2026-05-10": 200.0,
            "2026-05-20": 180.0,
        }
        from ai.builders.position_chart import build
        with patch("home.market._fetch_batch_quotes", side_effect=Exception), \
             patch("main._fetch_price_history", return_value=hist, create=True):
            p = build(conn, 1, asset="AAPL")
        assert p["drawdown_recent_pct"] == -10.0
        assert len(p["price_series_30d"]) == 3


# ════════════════════════════════════════════════════════════════════════════
# position_lots.py
# ════════════════════════════════════════════════════════════════════════════

class TestPositionLotsBuilder:

    def test_requires_asset(self):
        from ai.builders.position_lots import build
        conn = _base_db()
        with pytest.raises(ValueError, match="asset"):
            build(conn, 1)

    def test_no_lots_returns_single_pattern(self):
        from ai.builders.position_lots import build
        conn = _base_db()
        p = build(conn, 1, asset="XYZ")
        assert p["pattern"] == "single"
        assert p["lots_count"] == 0

    def test_averaging_up_pattern(self):
        """Tres compras a precios crecientes → averaging_up."""
        conn = _base_db()
        for i, price in enumerate([100, 120, 140]):
            conn.execute(
                """INSERT INTO operations
                   (user_id, date, asset, op_type, entry_price, quantity)
                   VALUES (1, ?, 'NVDA', 'Compra', ?, 5)""",
                (f"2026-0{i+1}-01", price),
            )
        from ai.builders.position_lots import build
        p = build(conn, 1, asset="NVDA")
        assert p["pattern"] == "averaging_up"
        assert p["lots_count"] == 3
        # avg = (100*5 + 120*5 + 140*5) / 15 = 120
        assert p["avg_buy_price"] == 120.0

    def test_averaging_down_pattern(self):
        """Tres compras a precios decrecientes → averaging_down."""
        conn = _base_db()
        for i, price in enumerate([150, 130, 110]):
            conn.execute(
                """INSERT INTO operations
                   (user_id, date, asset, op_type, entry_price, quantity)
                   VALUES (1, ?, 'XYZ', 'Compra', ?, 5)""",
                (f"2026-0{i+1}-01", price),
            )
        from ai.builders.position_lots import build
        p = build(conn, 1, asset="XYZ")
        assert p["pattern"] == "averaging_down"

    def test_single_buy_returns_single_pattern(self):
        conn = _base_db()
        conn.execute(
            """INSERT INTO operations
               (user_id, date, asset, op_type, entry_price, quantity)
               VALUES (1, '2026-01-01', 'AAPL', 'Compra', 150, 10)"""
        )
        from ai.builders.position_lots import build
        p = build(conn, 1, asset="AAPL")
        assert p["pattern"] == "single"
        assert p["lots_count"] == 1

    def test_includes_closes_when_sells(self):
        """Sells (con pnl_usd) cuentan como closes."""
        conn = _base_db()
        conn.execute(
            """INSERT INTO operations
               (user_id, date, asset, op_type, entry_price, exit_price,
                quantity, pnl_usd)
               VALUES (1, '2026-02-01', 'NVDA', 'Venta', 100, 150, 5, 250)"""
        )
        from ai.builders.position_lots import build
        p = build(conn, 1, asset="NVDA")
        assert p["closes_count"] == 1

    def test_caps_at_15_lots(self):
        """Más de 15 operaciones → solo devuelve las primeras 15."""
        conn = _base_db()
        for i in range(20):
            conn.execute(
                """INSERT INTO operations
                   (user_id, date, asset, op_type, entry_price, quantity)
                   VALUES (1, ?, 'NVDA', 'Compra', 100, 1)""",
                (f"2026-{(i % 12) + 1:02d}-01",),
            )
        from ai.builders.position_lots import build
        p = build(conn, 1, asset="NVDA")
        assert len(p["lots"]) == 15
        assert p["lots_count"] == 20  # total real


# ════════════════════════════════════════════════════════════════════════════
# goal.py
# ════════════════════════════════════════════════════════════════════════════

class TestGoalBuilder:

    def test_requires_goal_id(self):
        from ai.builders.goal import build
        conn = _base_db()
        with pytest.raises(ValueError, match="goal_id"):
            build(conn, 1)

    def test_non_int_goal_id_raises(self):
        from ai.builders.goal import build
        conn = _base_db()
        with pytest.raises(ValueError, match="entero"):
            build(conn, 1, goal_id="abc")

    def test_goal_not_found_raises(self):
        from ai.builders.goal import build
        conn = _base_db()
        with pytest.raises(ValueError, match="no encontrado"):
            build(conn, 1, goal_id=999)

    def test_packet_shape_basic(self):
        conn = _base_db()
        conn.execute(
            """INSERT INTO goals
               (id, user_id, label, target_usd, target_date,
                monthly_contribution, expected_return_pct)
               VALUES (1, 1, 'Casa', 50000, '2028-01-01', 500, 8)"""
        )
        # Snapshot para current_capital
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value) "
            "VALUES (1, '2026-05-15', 10000)"
        )
        from ai.builders.goal import build
        p = build(conn, 1, goal_id=1)
        assert p["screen"] == "goal"
        assert p["goal"]["id"] == 1
        assert p["goal"]["target_usd"] == 50000.0
        assert p["goal"]["label"] == "Casa"
        assert p["progress"]["current_capital_usd"] == 10000.0
        assert p["progress"]["progress_pct"] == 20.0
        assert p["progress"]["gap_usd"] == 40000.0

    def test_goal_user_isolation(self):
        """Goal de user 1 no es accesible para user 2 (defensa cross-user)."""
        conn = _base_db()
        conn.execute("INSERT INTO users (id, email) VALUES (2, 'other@t.com')")
        conn.execute(
            """INSERT INTO goals (id, user_id, label, target_usd, target_date,
                                  monthly_contribution, expected_return_pct)
               VALUES (1, 1, 'Mío', 50000, '2028-01-01', 500, 8)"""
        )
        from ai.builders.goal import build
        # User 2 intenta acceder al goal de user 1 → raises
        with pytest.raises(ValueError, match="no encontrado"):
            build(conn, 2, goal_id=1)


# ════════════════════════════════════════════════════════════════════════════
# Phase 3 builders — home + news + events
# ════════════════════════════════════════════════════════════════════════════

def _phase3_db():
    """DB con tablas adicionales que home/news/events necesitan."""
    conn = _base_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS financial_events (
            id INTEGER PRIMARY KEY,
            ticker TEXT, event_type TEXT, event_date TEXT, details TEXT
        );
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY,
            ticker TEXT, title TEXT, source TEXT,
            published_at TEXT, tags TEXT, url TEXT
        );
    """)
    return conn


class TestHomeBuilder:

    def test_shape_with_empty_db(self):
        conn = _phase3_db()
        from ai.builders.home import build
        # Sin posiciones, sin snapshots — el builder no debe crashear
        p = build(conn, 1)
        assert p["screen"] == "home"
        assert "market" in p
        assert "portfolio_today" in p
        assert "portfolio_events_window" in p
        assert p["portfolio_events_window"]["total"] == 0

    def test_portfolio_today_computes_delta(self):
        """Con 2 snapshots consecutivos el builder computa delta_pct/usd."""
        conn = _phase3_db()
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value) "
            "VALUES (1, '2026-05-14', 10000)"
        )
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value) "
            "VALUES (1, '2026-05-15', 10500)"
        )
        from ai.builders.home import build
        p = build(conn, 1)
        assert p["portfolio_today"]["total_value_usd"] == 10500.0
        # 10500/10000 - 1 = 5%
        assert p["portfolio_today"]["delta_pct_today"] == 5.0
        assert p["portfolio_today"]["delta_usd_today"] == 500.0


class TestNewsBuilder:

    def test_empty_db_zero_news(self):
        from ai.builders.news import build
        conn = _phase3_db()
        p = build(conn, 1)
        assert p["screen"] == "news"
        assert p["total_news"] == 0
        assert p["tickers_covered"] == []

    def test_aggregates_tickers_and_tags(self):
        conn = _phase3_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'NVDA', 10, 5000)"
        )
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'AAPL', 5, 1000)"
        )
        # 2 noticias de NVDA con tags 'earnings'; 1 de AAPL con 'macro'
        from datetime import date, timedelta
        recent = date.today().isoformat()
        for _ in range(2):
            conn.execute(
                """INSERT INTO news (ticker, title, source, published_at, tags)
                   VALUES ('NVDA', 'NVDA up', 'Reuters', ?, '[\"earnings\"]')""",
                (recent,),
            )
        conn.execute(
            """INSERT INTO news (ticker, title, source, published_at, tags)
               VALUES ('AAPL', 'AAPL macro', 'BBG', ?, '[\"macro\"]')""",
            (recent,),
        )

        from ai.builders.news import build
        p = build(conn, 1, window_days=7)
        assert p["total_news"] == 3
        assert "NVDA" in p["tickers_covered"]
        assert "AAPL" in p["tickers_covered"]
        # earnings aparece 2 veces, macro 1 vez
        tag_counts = {t["tag"]: t["count"] for t in p["top_tags"]}
        assert tag_counts.get("earnings") == 2
        assert tag_counts.get("macro") == 1


class TestNewsItemBuilder:

    def test_requires_ticker_and_title(self):
        from ai.builders.news_item import build
        conn = _phase3_db()
        with pytest.raises(ValueError, match="ticker"):
            build(conn, 1, title="x")
        with pytest.raises(ValueError, match="title"):
            build(conn, 1, ticker="NVDA")

    def test_holds_ticker_false_when_no_position(self):
        from ai.builders.news_item import build
        conn = _phase3_db()
        p = build(conn, 1, ticker="MSFT", title="MSFT does something")
        assert p["screen"] == "news.item"
        assert p["article"]["ticker"] == "MSFT"
        assert p["portfolio_context"]["holds_ticker"] is False

    def test_holds_ticker_true_with_position(self):
        from ai.builders.news_item import build
        conn = _phase3_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'NVDA', 10, 5000)"
        )
        from unittest.mock import patch
        with patch("home.market._fetch_batch_quotes", side_effect=Exception):
            p = build(conn, 1, ticker="NVDA", title="NVDA news")
        assert p["portfolio_context"]["holds_ticker"] is True
        assert p["portfolio_context"]["broker"] == "Schwab"


class TestEventsBuilder:

    def test_empty_returns_zero(self):
        from ai.builders.events import build
        conn = _phase3_db()
        p = build(conn, 1)
        assert p["screen"] == "events"
        assert p["total_events"] == 0
        assert p["concentrated_week"] is False

    def test_aggregates_by_type_and_horizon(self):
        conn = _phase3_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'NVDA', 10, 5000)"
        )
        # 2 earnings esta semana + 1 dividend más adelante
        from datetime import date, timedelta
        today = date.today()
        for delta_days in [3, 5]:
            conn.execute(
                "INSERT INTO financial_events (ticker, event_type, event_date) "
                "VALUES (?, ?, ?)",
                ("NVDA", "earnings", (today + timedelta(days=delta_days)).isoformat()),
            )
        conn.execute(
            "INSERT INTO financial_events (ticker, event_type, event_date) "
            "VALUES (?, ?, ?)",
            ("NVDA", "dividend", (today + timedelta(days=40)).isoformat()),
        )

        from ai.builders.events import build
        p = build(conn, 1, window_days=60)
        assert p["total_events"] == 3
        assert p["by_type"]["earnings"] == 2
        assert p["by_type"]["dividend"] == 1
        assert p["by_horizon"]["this_week"] == 2
        assert p["by_horizon"]["later"] == 1


class TestEventsItemBuilder:

    def test_requires_ticker_and_type(self):
        from ai.builders.events_item import build
        conn = _phase3_db()
        with pytest.raises(ValueError, match="ticker"):
            build(conn, 1, event_type="earnings")
        with pytest.raises(ValueError, match="event_type"):
            build(conn, 1, ticker="NVDA")

    def test_packet_shape_with_position(self):
        from ai.builders.events_item import build
        conn = _phase3_db()
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested) "
            "VALUES (1, 'Schwab', 'NVDA', 10, 5000)"
        )
        from unittest.mock import patch
        with patch("home.market._fetch_batch_quotes", side_effect=Exception):
            p = build(
                conn, 1,
                ticker="NVDA", event_type="earnings",
                event_date="2026-05-20",
            )
        assert p["screen"] == "events.item"
        assert p["event"]["ticker"] == "NVDA"
        assert p["event"]["type"] == "earnings"
        assert p["portfolio_context"]["holds_ticker"] is True

    def test_days_ahead_computation(self):
        from ai.builders.events_item import build
        from datetime import date, timedelta
        conn = _phase3_db()
        future_date = (date.today() + timedelta(days=10)).isoformat()
        p = build(
            conn, 1,
            ticker="UNKNOWN", event_type="dividend",
            event_date=future_date,
        )
        assert p["event"]["days_ahead"] == 10
        assert p["portfolio_context"]["holds_ticker"] is False
