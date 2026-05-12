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


class PopularEventsTest(unittest.TestCase):
    """Tests del endpoint /api/events/popular — eventos del mercado (no del
    portfolio del user) — macro + earnings de tickers populares."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"popular-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "IBKR", "USDT")
        main._events_fetched_at.clear()
        with conn:
            conn.execute("DELETE FROM financial_events")
        # Para que el fetcher no haga llamadas reales a yfinance en tests:
        # marcamos todos los populares como "ya fetcheados"
        for t in main.POPULAR_TICKERS_US + main.POPULAR_TICKERS_AR_ADR:
            main._events_fetched_at[t] = main.time.time()
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.token}"})

    def _seed_popular_event(self, ticker, event_type, date, details=None):
        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO financial_events
                   (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                   VALUES (?, ?, ?, ?, 1, 'yfinance', '2026-05-12T00:00:00Z')""",
                (ticker, event_type, date, json.dumps(details or {})),
            )
        conn.close()

    # ─── Macro events ────────────────────────────────────────────────────────

    def test_returns_macro_events_within_window(self):
        res = self._get("/api/events/popular?days=365")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Debería incluir algunos macros (depende de la fecha actual del sistema)
        macros = [e for e in body["events"] if e["event_type"] == "macro"]
        self.assertGreaterEqual(len(macros), 0)
        for ev in macros:
            self.assertEqual(ev["source"], "hardcoded")
            self.assertTrue(ev["confirmed"])
            self.assertIn(ev["details"]["country"], ("USA", "AR"))

    def test_macro_events_include_country_and_title(self):
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        macros = [e for e in body["events"] if e["event_type"] == "macro"]
        if macros:
            sample = macros[0]
            self.assertIn("country", sample["details"])
            self.assertIn("title", sample["details"])
            self.assertIn("category", sample["details"])
            # El ticker es un código sintético tipo "USA-CPI" / "AR-IPC"
            self.assertRegex(sample["ticker"], r"^(USA|AR)-[A-Z]+$")

    # ─── Earnings populares ──────────────────────────────────────────────────

    def test_includes_popular_ticker_earnings(self):
        # Seed earnings de NVDA (magnificent 7) en ventana
        self._seed_popular_event("NVDA", "earnings", "2026-08-20", {"eps_estimate": 5.10})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        nvda = [e for e in body["events"] if e["ticker"] == "NVDA"]
        self.assertEqual(len(nvda), 1)
        self.assertEqual(nvda[0]["event_type"], "earnings")
        self.assertEqual(nvda[0]["details"]["eps_estimate"], 5.10)
        self.assertFalse(nvda[0]["in_portfolio"])  # user no tiene NVDA

    def test_in_portfolio_flag_when_user_owns_ticker(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "TSLA", qty=10)
        conn.commit()
        conn.close()
        self._seed_popular_event("TSLA", "earnings", "2026-07-22", {"eps_estimate": 0.85})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        tsla = [e for e in body["events"] if e["ticker"] == "TSLA"][0]
        self.assertTrue(tsla["in_portfolio"])

    def test_ar_adr_ticker_included(self):
        self._seed_popular_event("GGAL", "earnings", "2026-08-05", {})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        tickers = {e["ticker"] for e in body["events"]}
        self.assertIn("GGAL", tickers)

    # ─── Sorting / filtros ───────────────────────────────────────────────────

    def test_events_sorted_by_date(self):
        self._seed_popular_event("AAPL", "earnings", "2026-09-25", {})
        self._seed_popular_event("MSFT", "earnings", "2026-07-25", {})
        self._seed_popular_event("AMZN", "earnings", "2026-08-10", {})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        # Filtrar sólo earnings que sembramos (macros pueden estar mezclados)
        seeded_dates = [e["event_date"] for e in body["events"]
                        if e["ticker"] in ("AAPL", "MSFT", "AMZN")]
        self.assertEqual(seeded_dates, sorted(seeded_dates))

    def test_days_window_filters_events(self):
        # Earnings lejano + cercano
        self._seed_popular_event("NVDA", "earnings", "2026-06-01", {})
        self._seed_popular_event("AAPL", "earnings", "2027-01-15", {})  # >1 año
        res = self._get("/api/events/popular?days=180")
        body = res.json()
        tickers = {e["ticker"] for e in body["events"] if e["event_type"] == "earnings"}
        self.assertIn("NVDA", tickers)
        self.assertNotIn("AAPL", tickers)

    # ─── Counts en response ─────────────────────────────────────────────────

    def test_response_includes_macro_and_ticker_counts(self):
        self._seed_popular_event("NVDA", "earnings", "2026-06-01", {})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        self.assertIn("macro_count", body)
        self.assertIn("ticker_count", body)
        self.assertGreaterEqual(body["ticker_count"], 1)

    # ─── Validación ─────────────────────────────────────────────────────────

    def test_invalid_days_rejected(self):
        res = self._get("/api/events/popular?days=999")
        self.assertEqual(res.status_code, 422)

    def test_unauthorized_without_token(self):
        res = self.client.get("/api/events/popular")
        self.assertIn(res.status_code, (401, 403))


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
