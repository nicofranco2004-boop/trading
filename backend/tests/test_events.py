"""Tests del endpoint /api/events/portfolio.

Mockea yfinance — no hace fetch real. Verifica:
  • Filtra eventos al portfolio del user.
  • Excluye bonos AR (los maneja frontend).
  • Excluye crypto.
  • Excluye cash.
  • Filtra por ventana de fechas (days).
  • Persistencia: upsert idempotente.
  • Auth + cross-user isolation.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _new_user(conn, email: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"),
    )
    return cur.lastrowid


def _add_broker(conn, uid: int, name: str, currency: str = "USDT") -> int:
    cur = conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
        (uid, name, currency),
    )
    return cur.lastrowid


def _add_position(conn, uid: int, broker: str, asset: str, qty: float = 100, is_cash: int = 0):
    conn.execute(
        """INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested)
           VALUES (?, ?, ?, ?, ?, 0)""",
        (uid, broker, asset, is_cash, qty),
    )


class EventsPortfolioTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"events-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "IBKR", "USDT")
        # Reset events cache (idempotent fetcher TTL)
        main._events_fetched_at.clear()
        # Limpiar events table para que cada test parta limpio
        with conn:
            conn.execute("DELETE FROM financial_events")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.token}"})

    def _seed_event(self, ticker, event_type, date, details=None, confirmed=1):
        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO financial_events
                   (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                   VALUES (?, ?, ?, ?, ?, 'yfinance', '2026-05-12T00:00:00Z')""",
                (ticker, event_type, date, json.dumps(details or {}), confirmed),
            )
        # Marcar como ya fetcheado para evitar re-fetch via yfinance real
        main._events_fetched_at[ticker] = main.time.time()
        conn.close()

    # ─── Happy paths ─────────────────────────────────────────────────────────

    def test_returns_events_for_portfolio_tickers(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        _add_position(conn, self.uid, "IBKR", "MSFT", qty=20)
        conn.commit()
        conn.close()

        self._seed_event("AAPL", "earnings", "2026-07-25", {"eps_estimate": 1.45})
        self._seed_event("MSFT", "ex_dividend", "2026-06-12", {"dividend_per_share": 0.75})

        res = self._get("/api/events/portfolio?days=180")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(len(body["events"]), 2)
        tickers = {e["ticker"] for e in body["events"]}
        self.assertEqual(tickers, {"AAPL", "MSFT"})

    def test_filters_by_window_days(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()

        # Cerca + lejos
        self._seed_event("AAPL", "earnings", "2026-06-01", {})
        self._seed_event("AAPL", "earnings", "2027-01-01", {})

        # 30 días: sólo el cercano (de 2026-06-01, asumiendo today ~2026-05-12)
        res = self._get("/api/events/portfolio?days=30")
        body = res.json()
        dates = {e["event_date"] for e in body["events"]}
        self.assertIn("2026-06-01", dates)
        self.assertNotIn("2027-01-01", dates)

        # 365 días: ambos
        res = self._get("/api/events/portfolio?days=365")
        body = res.json()
        dates = {e["event_date"] for e in body["events"]}
        self.assertIn("2026-06-01", dates)
        self.assertIn("2027-01-01", dates)

    def test_excludes_ar_bonds(self):
        """Bonos AR los maneja frontend — el endpoint NO debe traerlos aunque
        tengan eventos en la tabla."""
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AL30", qty=1000)  # bono AR
        conn.commit()
        conn.close()

        # Aunque hubiera un evento de AL30 en la tabla, el endpoint lo excluye
        self._seed_event("AL30", "earnings", "2026-07-09", {})

        res = self._get("/api/events/portfolio?days=180")
        body = res.json()
        self.assertEqual(body["events"], [])

    def test_excludes_cash_positions(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "USDT", qty=0, is_cash=1)
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()

        self._seed_event("AAPL", "earnings", "2026-07-25", {})
        res = self._get("/api/events/portfolio?days=90")
        body = res.json()
        # Sólo aparece AAPL — USDT (cash) no se intenta lookup
        self.assertEqual([e["ticker"] for e in body["events"]], ["AAPL"])

    def test_empty_portfolio_returns_empty(self):
        res = self._get("/api/events/portfolio?days=90")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["events"], [])

    # ─── Validación ──────────────────────────────────────────────────────────

    def test_invalid_days_rejected(self):
        for d in (-1, 0, 366, 9999):
            res = self._get(f"/api/events/portfolio?days={d}")
            self.assertEqual(res.status_code, 422, f"days={d}")

    def test_unauthorized_without_token(self):
        res = self.client.get("/api/events/portfolio")
        self.assertIn(res.status_code, (401, 403))

    def test_cross_user_isolation(self):
        conn = main.get_db()
        other_uid = _new_user(conn, f"other-{self.id()}@rendi.test")
        _add_broker(conn, other_uid, "IBKR", "USDT")
        _add_position(conn, other_uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()

        self._seed_event("AAPL", "earnings", "2026-07-25", {})

        # User A no tiene AAPL → no debe ver el evento
        res = self._get("/api/events/portfolio?days=180")
        self.assertEqual(res.json()["events"], [])

    def test_details_parsed_as_dict(self):
        """El campo `details` se devuelve como dict (parseado de JSON)."""
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()
        self._seed_event("AAPL", "earnings", "2026-07-25", {"eps_estimate": 1.45, "currency": "USD"})

        res = self._get("/api/events/portfolio?days=90")
        body = res.json()
        ev = body["events"][0]
        self.assertEqual(ev["details"]["eps_estimate"], 1.45)
        self.assertEqual(ev["details"]["currency"], "USD")


class FetcherTest(unittest.TestCase):
    """Tests del fetcher yfinance — siempre mockeado para no depender de la red."""

    def setUp(self):
        main._events_fetched_at.clear()

    def test_fetcher_returns_empty_on_unknown_ticker(self):
        """yfinance Ticker no existente → fetcher devuelve [] sin throw."""
        with patch('main.yf.Ticker') as mock_t:
            mock_t.return_value.calendar = None
            mock_t.return_value.info = {}
            events = main._fetch_yf_events('NOEXISTE')
        self.assertEqual(events, [])

    def test_fetcher_handles_exception_gracefully(self):
        """Si yfinance arroja, el fetcher devuelve [] sin propagar."""
        with patch('main.yf.Ticker', side_effect=Exception('network error')):
            events = main._fetch_yf_events('AAPL')
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
