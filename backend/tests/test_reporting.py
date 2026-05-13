"""Tests del módulo `reporting/`. Cubre:
- parse_period_bounds (day/week/month)
- builder: métricas core sobre data sintética
- detectors: cada uno gatilla y no gatilla en los casos esperados
- timeline: composición month → weeks
"""
import os
import sys
import unittest
import sqlite3
import uuid
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa
from reporting import builder, detectors, timeline
from reporting.schema import PeriodReport, PeriodMetrics, Insight


def _new_user_with_data(conn) -> int:
    """Crea un user de test con un broker y datos básicos en monthly_entries."""
    # Email único por test (uuid4) — evita colisiones entre tests que se reusan en CI
    email = f"reports-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (email,),
    )
    uid = cur.lastrowid
    conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?, 'Binance', 'USDT')",
        (uid,),
    )
    return uid


# ─── parse_period_bounds ────────────────────────────────────────────────────

class ParsePeriodBoundsTest(unittest.TestCase):
    def test_month_full_range(self):
        s, e = builder.parse_period_bounds("month", "2026-05")
        self.assertEqual(s, "2026-05-01")
        self.assertEqual(e, "2026-05-31")

    def test_month_feb_2024_leap_year(self):
        s, e = builder.parse_period_bounds("month", "2024-02")
        self.assertEqual(e, "2024-02-29")

    def test_week_iso_monday_to_sunday(self):
        # ISO week 19 of 2026 → Mon May 4 to Sun May 10
        s, e = builder.parse_period_bounds("week", "2026-W19")
        self.assertEqual(s, "2026-05-04")
        self.assertEqual(e, "2026-05-10")

    def test_day_is_single_day(self):
        s, e = builder.parse_period_bounds("day", "2026-05-13")
        self.assertEqual(s, "2026-05-13")
        self.assertEqual(e, "2026-05-13")

    def test_period_label_month(self):
        self.assertEqual(builder.period_label("month", "2026-05", "2026-05-01"), "May 2026")

    def test_period_label_week(self):
        self.assertEqual(builder.period_label("week", "2026-W19", "2026-05-04"), "Semana 19")


# ─── Builder: métricas core ─────────────────────────────────────────────────

class BuilderMetricsTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = _new_user_with_data(self.conn)
        # Seedeo una entrada mensual: $5k → $6k, depositó $500, gain realizado $200
        self.conn.execute(
            """INSERT INTO monthly_entries
                  (user_id, broker, year, month, capital_inicio, capital_final,
                   deposits, withdrawals, pnl_realized, pnl_unrealized)
                  VALUES (?, 'global', 2026, 3, 5000, 6000, 500, 0, 200, 300)""",
            (self.uid,),
        )
        # Una venta cerrada con +US$200 P&L
        self.conn.execute(
            """INSERT INTO operations
                  (user_id, date, broker, asset, op_type, quantity, entry_price,
                   exit_price, pnl_usd, pnl_pct)
               VALUES (?, '2026-03-15', 'Binance', 'BTC', 'Venta', 0.1, 60000, 62000, 200, 3.3)""",
            (self.uid,),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_month_metrics_from_monthly_entry(self):
        m, ops = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-03-01", "2026-03-31",
            broker_filter="global", bench=None,
        )
        self.assertEqual(m.start_value, 5000)
        self.assertEqual(m.end_value, 6000)
        self.assertEqual(m.deposits, 500)
        # delta_usd = end - start - flows = 6000 - 5000 - 500 = 500
        self.assertEqual(m.delta_usd, 500)
        # Modified Dietz: 500 / (5000 + 250) = 9.52%
        self.assertAlmostEqual(m.delta_pct, 9.52, places=1)
        self.assertEqual(m.realized_pnl, 200)
        self.assertEqual(m.trades_count, 1)
        self.assertEqual(m.win_rate, 100.0)

    def test_live_value_overrides_for_current_period(self):
        """Si el período está en curso y pasamos live_value, lo usa como end_value."""
        today = date.today()
        # Crear monthly_entry del mes ACTUAL
        self.conn.execute(
            """INSERT INTO monthly_entries
                  (user_id, broker, year, month, capital_inicio, capital_final,
                   deposits, withdrawals, pnl_realized, pnl_unrealized)
                  VALUES (?, 'global', ?, ?, 10000, 12000, 0, 0, 0, 2000)""",
            (self.uid, today.year, today.month),
        )
        self.conn.commit()
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month",
            f"{today.year:04d}-{today.month:02d}-01",
            f"{today.year:04d}-{today.month:02d}-28",
            broker_filter="global", bench=None, live_value=15000,
        )
        self.assertEqual(m.end_value, 15000)

    def test_build_period_report_e2e(self):
        rpt = builder.build_period_report(
            self.conn, self.uid, "month", "2026-03",
            broker_filter="global",
        )
        self.assertEqual(rpt.period_label, "Mar 2026")
        self.assertTrue(rpt.is_relevant)
        self.assertIn("+9.5%", rpt.headline)  # Modified Dietz ~9.52
        # Drivers debe incluir BTC con contribución 100% (única operación)
        self.assertEqual(len(rpt.drivers), 1)
        self.assertEqual(rpt.drivers[0].asset, "BTC")


# ─── Detectores ──────────────────────────────────────────────────────────────

def _stub_metrics(**overrides) -> PeriodMetrics:
    base = dict(
        start_value=10000, end_value=11000, delta_usd=1000, delta_pct=10.0,
        delta_pct_over_contrib=5.0, realized_pnl=1000, unrealized_pnl=0,
        deposits=0, withdrawals=0, trades_count=5, win_count=3, loss_count=2,
        win_rate=60.0, vs_sp500_pct=8.0, vs_inflation_pct=3.0,
    )
    base.update(overrides)
    return PeriodMetrics(**base)


def _stub_report(**overrides) -> PeriodReport:
    metrics = overrides.pop("metrics", _stub_metrics())
    drivers = overrides.pop("drivers", [])
    base = dict(
        period_type="month", period_key="2026-05", period_label="May 2026",
        period_start="2026-05-01", period_end="2026-05-31",
        is_current=False, is_relevant=True,
        headline="x", subheadline=None,
        metrics=metrics, insights=[], highlights=[], drivers=drivers, children=[],
    )
    base.update(overrides)
    return PeriodReport(**base)


class DetectorsTest(unittest.TestCase):
    def test_concentration_risk_triggers_above_40pct(self):
        positions = [
            {"asset": "BTC", "value_usd": 6000, "is_cash": False},
            {"asset": "ETH", "value_usd": 4000, "is_cash": False},
        ]
        i = detectors.detect_concentration_risk(_stub_report(), positions)
        self.assertIsNotNone(i)
        self.assertEqual(i.code, "CONCENTRATION_RISK")
        self.assertIn("BTC", i.title)

    def test_concentration_risk_silent_when_diversified(self):
        positions = [
            {"asset": "BTC", "value_usd": 3000, "is_cash": False},
            {"asset": "ETH", "value_usd": 3500, "is_cash": False},
            {"asset": "SOL", "value_usd": 3500, "is_cash": False},
        ]
        self.assertIsNone(detectors.detect_concentration_risk(_stub_report(), positions))

    def test_driver_of_period_triggers_when_concentrated(self):
        from reporting.schema import AssetContribution
        r = _stub_report(drivers=[
            AssetContribution(asset="BTC", pnl_usd=800, contribution_pct=80),
            AssetContribution(asset="ETH", pnl_usd=200, contribution_pct=20),
        ])
        i = detectors.detect_driver_of_period(r)
        self.assertIsNotNone(i)
        self.assertIn("BTC", i.title)

    def test_driver_silent_when_low_pnl(self):
        """Si el driver tiene contribución 80% pero monto chico, no genera insight (ruido)."""
        from reporting.schema import AssetContribution
        r = _stub_report(drivers=[
            AssetContribution(asset="X", pnl_usd=10, contribution_pct=80),
        ])
        self.assertIsNone(detectors.detect_driver_of_period(r))

    def test_deposits_vs_gains_triggers_when_growth_came_from_flows(self):
        m = _stub_metrics(deposits=5000, delta_usd=100)
        r = _stub_report(metrics=m)
        i = detectors.detect_deposits_vs_gains(r)
        self.assertIsNotNone(i)
        self.assertEqual(i.code, "DEPOSITS_DRIVE_GROWTH")

    def test_win_rate_delta_up(self):
        i = detectors.detect_win_rate_delta(_stub_report(metrics=_stub_metrics(win_rate=80.0, trades_count=10)), historical_win_rate=50.0)
        self.assertIsNotNone(i)
        self.assertEqual(i.severity, "positive")

    def test_win_rate_delta_silent_below_threshold(self):
        i = detectors.detect_win_rate_delta(_stub_report(metrics=_stub_metrics(win_rate=55.0, trades_count=10)), historical_win_rate=50.0)
        self.assertIsNone(i)  # delta = 5pp < 10pp

    def test_vs_benchmark_beat(self):
        m = _stub_metrics(delta_pct=15.0, vs_sp500_pct=5.0)
        i = detectors.detect_vs_benchmark(_stub_report(metrics=m))
        self.assertIsNotNone(i)
        self.assertEqual(i.code, "BEAT_BENCHMARK")

    def test_consistency_triggers_when_all_weeks_positive(self):
        weeks = [
            _stub_report(period_type="week", period_key=f"2026-W{w}",
                        metrics=_stub_metrics(delta_pct=2.0))
            for w in [18, 19, 20, 21]
        ]
        r = _stub_report(children=weeks)
        i = detectors.detect_consistency(r)
        self.assertIsNotNone(i)
        self.assertEqual(i.code, "CONSISTENT_POSITIVE")


# ─── Timeline composition ────────────────────────────────────────────────────

class TimelineTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = _new_user_with_data(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_empty_user_returns_n_months_with_no_relevant(self):
        result = timeline.build_timeline(self.conn, self.uid, broker_filter="global", months=3)
        self.assertEqual(len(result), 3)
        for m in result:
            self.assertFalse(m.is_relevant, f"{m.period_key} should be irrelevant for empty user")

    def test_weeks_in_month_returns_valid_iso_keys(self):
        weeks = timeline._weeks_in_month(2026, 5)
        # Mayo 2026: lunes 4 = W19, lunes 11 = W20, lunes 18 = W21, lunes 25 = W22
        self.assertEqual(weeks, ["2026-W19", "2026-W20", "2026-W21", "2026-W22"])

    def test_timeline_includes_weeks_as_children(self):
        result = timeline.build_timeline(self.conn, self.uid, broker_filter="global", months=2)
        for m in result:
            # Cada mes debe tener entre 4 y 6 semanas
            self.assertGreaterEqual(len(m.children), 4)
            self.assertLessEqual(len(m.children), 6)
            for w in m.children:
                self.assertEqual(w.period_type, "week")


if __name__ == "__main__":
    unittest.main()
