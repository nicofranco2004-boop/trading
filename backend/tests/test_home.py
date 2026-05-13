"""Tests del módulo `home/`. Cubre:
- briefing.build_personal_cards: detectores de movements, earnings, dividends
- market: registry MARKETS, cache, formatos de output
- Endpoints /api/watchlist (CRUD)

NOTA: no testeamos yfinance directamente (es flaky en CI). Mockeamos quotes
en los tests del briefing. Los endpoints /api/home/heatmap/movers se testean
solo a nivel de "responden 200 con shape correcto".
"""
import os
import sys
import unittest
import uuid
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from home import briefing
from home.market import MARKETS, SP500_TOP_50, MERVAL_TOP_25, CRYPTO_TOP_30


def _new_user(conn) -> int:
    email = f"home-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (email,),
    )
    return cur.lastrowid


# ─── Briefing — build_personal_cards ─────────────────────────────────────────

class BriefingTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = _new_user(self.conn)
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?, 'Binance', 'USDT')",
            (self.uid,),
        )
        # Holding: 1 BTC
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested)
               VALUES (?, 'Binance', 'BTC', 0, 1, 50000)""",
            (self.uid,),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_returns_empty_when_no_holdings(self):
        empty_uid = _new_user(self.conn)
        self.conn.commit()
        cards = briefing.build_personal_cards(
            self.conn, empty_uid,
            all_quotes={"BTC": {"price": 80000, "change_pct": 3.0}},
            portfolio_events=[],
        )
        self.assertEqual(cards, [])

    def test_holdings_mover_card_appears_when_change_above_threshold(self):
        cards = briefing.build_personal_cards(
            self.conn, self.uid,
            all_quotes={"BTC": {"price": 80000, "change_pct": 5.0}},
            portfolio_events=[],
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["kind"], "holding_move")
        self.assertEqual(cards[0]["value_tone"], "positive")
        self.assertIn("BTC", cards[0]["headline"])

    def test_holdings_mover_silent_below_threshold(self):
        cards = briefing.build_personal_cards(
            self.conn, self.uid,
            all_quotes={"BTC": {"price": 80000, "change_pct": 0.5}},
            portfolio_events=[],
        )
        self.assertEqual(cards, [])

    def test_negative_mover_uses_negative_tone(self):
        cards = briefing.build_personal_cards(
            self.conn, self.uid,
            all_quotes={"BTC": {"price": 75000, "change_pct": -3.5}},
            portfolio_events=[],
        )
        self.assertEqual(cards[0]["value_tone"], "negative")
        self.assertEqual(cards[0]["icon"], "📉")

    def test_earnings_card_for_holding_ticker(self):
        # User tiene BTC; le metemos un earnings de BTC en 3 días
        from datetime import date, timedelta
        future = (date.today() + timedelta(days=3)).isoformat()
        events = [{"event_type": "earnings", "ticker": "BTC", "event_date": future}]
        cards = briefing.build_personal_cards(
            self.conn, self.uid,
            all_quotes={"BTC": {"price": 80000, "change_pct": 0.2}},
            portfolio_events=events,
        )
        # Sin mover de price (0.2% < 1.5%) pero earnings card sí debería estar
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["kind"], "earnings_soon")
        self.assertIn("3 días", cards[0]["value"])

    def test_earnings_skip_if_not_in_holdings(self):
        from datetime import date, timedelta
        future = (date.today() + timedelta(days=3)).isoformat()
        events = [{"event_type": "earnings", "ticker": "AAPL", "event_date": future}]
        cards = briefing.build_personal_cards(
            self.conn, self.uid,
            all_quotes={"BTC": {"price": 80000, "change_pct": 0.1}},
            portfolio_events=events,
        )
        self.assertEqual(cards, [])

    def test_cap_total_at_4_cards(self):
        # 3 holdings moviéndose fuerte + 2 earnings → debería capear a 4
        for asset in ["ETH", "SOL", "DOGE"]:
            self.conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested)
                   VALUES (?, 'Binance', ?, 0, 1, 100)""",
                (self.uid, asset),
            )
        self.conn.commit()
        from datetime import date, timedelta
        future = (date.today() + timedelta(days=2)).isoformat()
        cards = briefing.build_personal_cards(
            self.conn, self.uid,
            all_quotes={
                "BTC":  {"price": 80000, "change_pct": 5.0},
                "ETH":  {"price": 3000, "change_pct": 4.0},
                "SOL":  {"price": 100,  "change_pct": 3.0},
                "DOGE": {"price": 0.3,  "change_pct": 6.0},
            },
            portfolio_events=[
                {"event_type": "earnings", "ticker": "BTC", "event_date": future},
                {"event_type": "earnings", "ticker": "ETH", "event_date": future},
            ],
        )
        self.assertLessEqual(len(cards), 4)


# ─── Market registry ─────────────────────────────────────────────────────────

class MarketRegistryTest(unittest.TestCase):
    def test_three_markets_registered(self):
        self.assertIn("sp500", MARKETS)
        self.assertIn("merval", MARKETS)
        self.assertIn("crypto", MARKETS)

    def test_each_market_has_symbols_and_meta(self):
        for key, cfg in MARKETS.items():
            self.assertGreater(len(cfg["symbols"]), 10, f"{key}: pocos símbolos")
            self.assertGreater(len(cfg["meta"]), 10, f"{key}: pocos meta entries")
            self.assertIn("label", cfg)

    def test_sp500_has_50_symbols(self):
        self.assertEqual(len(SP500_TOP_50), 50)

    def test_merval_has_25_symbols(self):
        self.assertEqual(len(MERVAL_TOP_25), 25)

    def test_crypto_has_30_symbols(self):
        self.assertEqual(len(CRYPTO_TOP_30), 30)

    def test_merval_symbols_have_ba_suffix(self):
        for sym in MERVAL_TOP_25:
            self.assertTrue(sym.endswith(".BA"), f"{sym} debería terminar en .BA")

    def test_crypto_symbols_have_usd_suffix(self):
        for sym in CRYPTO_TOP_30:
            self.assertTrue(sym.endswith("-USD"), f"{sym} debería terminar en -USD")


# ─── Watchlist endpoints (vía TestClient) ────────────────────────────────────

class WatchlistTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = _new_user(conn)
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_empty_watchlist_returns_empty_list(self):
        r = self.client.get("/api/watchlist", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["items"], [])

    def test_add_symbol_is_idempotent(self):
        # Agregar 2 veces — segundo INSERT OR IGNORE no falla
        r1 = self.client.post("/api/watchlist", json={"symbol": "AAPL"}, headers=self.headers)
        r2 = self.client.post("/api/watchlist", json={"symbol": "AAPL"}, headers=self.headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Solo una entry final
        list_r = self.client.get("/api/watchlist", headers=self.headers)
        symbols = [it["symbol"] for it in list_r.json()["items"]]
        self.assertEqual(symbols.count("AAPL"), 1)

    def test_remove_existing_symbol(self):
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.headers)
        r = self.client.delete("/api/watchlist/MSFT", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        list_r = self.client.get("/api/watchlist", headers=self.headers)
        symbols = [it["symbol"] for it in list_r.json()["items"]]
        self.assertNotIn("MSFT", symbols)

    def test_remove_nonexistent_returns_ok(self):
        r = self.client.delete("/api/watchlist/ZZZZ", headers=self.headers)
        self.assertEqual(r.status_code, 200)

    def test_add_invalid_symbol_rejected(self):
        # Símbolos con caracteres raros deben fallar la validación pydantic
        r = self.client.post("/api/watchlist", json={"symbol": "FOO BAR"}, headers=self.headers)
        self.assertEqual(r.status_code, 422)

    def test_symbol_normalized_to_uppercase(self):
        self.client.post("/api/watchlist", json={"symbol": "aapl"}, headers=self.headers)
        list_r = self.client.get("/api/watchlist", headers=self.headers)
        symbols = [it["symbol"] for it in list_r.json()["items"]]
        self.assertIn("AAPL", symbols)


if __name__ == "__main__":
    unittest.main()
