"""Fix: el reporte del MES en curso usa el valor VIVO del portfolio (positions ×
precios, igual que Posiciones), no el último snapshot.

Bug: la timeline mensual tomaba end_value = _latest_snapshot_value (último
snapshot guardado). Si el cron del snapshot estaba stale/0, el mes en curso
mostraba una pérdida fantasma (ej. -195%) aunque la cartera valiera bien en
Posiciones. Ahora se usa compute_live_portfolio_value para el período en curso,
con fallback al snapshot si el cálculo live falla.
"""
import unittest
from unittest.mock import patch
from datetime import datetime

import main


def _new_user(conn, email):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)", (email, "x"),
    )
    return cur.lastrowid


class ReportsLiveValueMonthTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        for t in ("monthly_entries", "snapshots", "operations", "positions", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, f"rep-live-{id(self)}@rendi.test")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (self.uid, "IOL", "ARS"))
        now = datetime.utcnow()
        self.y, self.m = now.year, now.month
        # Mes en curso: aportó 47.756 sobre un capital inicial de 1.230, pero el
        # capital_final del monthly quedó stale en 0 (el escenario del bug).
        conn.execute(
            """INSERT INTO monthly_entries
                 (user_id, year, month, broker, deposits, withdrawals,
                  pnl_realized, pnl_unrealized, capital_inicio, capital_final,
                  manual_deposits, manual_withdrawals)
               VALUES (?,?,?, 'global', 47756, 0, 0, 0, 1230, 0, 47756, 0)""",
            (self.uid, self.y, self.m),
        )
        # snapshot STALE: total_value=0 (no refleja los ~49k reales)
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) VALUES (?,?,0,0,48986)",
            (self.uid, now.strftime("%Y-%m-%d")),
        )
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _timeline(self):
        return self.client.get(
            "/api/reports/timeline?broker=global&months=2",
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _current_month(self, res):
        reports = res.json()["reports"]
        return next(r for r in reports if r["period_type"] == "month" and r["is_current"])

    def test_current_month_uses_live_value_not_stale_snapshot(self):
        """Con valor vivo = 48.986 (= 1.230 + 47.756), el mes queda plano (~0%),
        no -195%."""
        LIVE = 48986.0
        with patch.object(main, "compute_live_portfolio_value", return_value=LIVE), \
             patch.object(main, "_fetch_sp500_monthly", return_value={}), \
             patch.object(main, "_fetch_inflation_ar", return_value={}):
            res = self._timeline()
        self.assertEqual(res.status_code, 200, res.text)
        cur = self._current_month(res)
        self.assertAlmostEqual(cur["metrics"]["end_value"], LIVE, delta=1)
        self.assertAlmostEqual(cur["metrics"]["delta_usd"], 0, delta=2)   # NO -49.008

    def test_falls_back_to_snapshot_when_live_unavailable(self):
        """Si el cálculo live no está disponible (None), cae al snapshot (best-effort)."""
        with patch.object(main, "compute_live_portfolio_value", return_value=None), \
             patch.object(main, "_fetch_sp500_monthly", return_value={}), \
             patch.object(main, "_fetch_inflation_ar", return_value={}):
            res = self._timeline()
        cur = self._current_month(res)
        self.assertAlmostEqual(cur["metrics"]["end_value"], 0, delta=1)   # snapshot stale


if __name__ == "__main__":
    unittest.main()
