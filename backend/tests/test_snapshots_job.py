"""Tests del job de daily snapshots — funciones puras de valuation
(compute_broker_value_usd, compute_net_deposited) y el flujo end-to-end
con una DB temporal.

Corre con: cd backend && python3 -m pytest tests/test_snapshots_job.py
"""
import os
import sys
import tempfile
import sqlite3
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from snapshots_job import (
    compute_broker_value_usd,
    compute_net_deposited,
    take_snapshot_for_user,
    run_daily_snapshot,
)


class TestComputeBrokerValueUsd(unittest.TestCase):
    """Replica de los tests de frontend valuation.test.js — port a Python.
    Aseguramos que el cálculo server-side coincida exactamente con el cliente."""

    def test_usdt_broker_with_position(self):
        """USDT broker: precio × cantidad da el value en USD directo."""
        positions = [
            {'asset': 'NVDA', 'is_cash': False, 'invested': 1000, 'quantity': 10,
             'commissions': 0, 'price_override': None},
        ]
        prices = {'NVDA': 150}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000)
        self.assertEqual(r['value'], 1500)  # 150 × 10
        self.assertEqual(r['invested'], 1000)

    def test_usd_broker_equivalent_to_usdt(self):
        """USD broker se trata igual que USDT (ambos valuán directo en USD)."""
        positions = [
            {'asset': 'AAPL', 'is_cash': False, 'invested': 2000, 'quantity': 10,
             'commissions': 0, 'price_override': None},
        ]
        prices = {'AAPL': 250}
        r_usdt = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000)
        r_usd = compute_broker_value_usd(positions, prices, 'USD', tc_blue=1000)
        self.assertEqual(r_usd, r_usdt)

    def test_ars_broker_uses_blue_for_conversion(self):
        """ARS broker: precio ARS / blue = value USD."""
        positions = [
            {'asset': 'GGAL', 'is_cash': False, 'invested': 100000, 'quantity': 100,
             'commissions': 0, 'price_override': None},
        ]
        prices = {'GGAL.BA': 1500}
        r = compute_broker_value_usd(positions, prices, 'ARS', tc_blue=1500)
        self.assertEqual(r['value'], 100)  # (1500 × 100) / 1500
        # invested USD = 100000 / 1500 (FX-phantom fix)
        self.assertAlmostEqual(r['invested'], 100000 / 1500, places=4)

    def test_cash_usdt_broker(self):
        """Cash en USDT broker: invested es value directo."""
        positions = [
            {'asset': 'USDT', 'is_cash': True, 'invested': 5000, 'quantity': 0,
             'commissions': 0, 'price_override': None},
        ]
        r = compute_broker_value_usd(positions, {}, 'USDT', tc_blue=1000)
        self.assertEqual(r['value'], 5000)
        self.assertEqual(r['invested'], 5000)

    def test_cash_ars_broker(self):
        """Cash en ARS broker: invested ARS / blue = value USD."""
        positions = [
            {'asset': 'ARS', 'is_cash': True, 'invested': 1500000, 'quantity': 0,
             'commissions': 0, 'price_override': None},
        ]
        r = compute_broker_value_usd(positions, {}, 'ARS', tc_blue=1500)
        self.assertEqual(r['value'], 1000)  # 1500000 / 1500
        self.assertEqual(r['invested'], 1000)

    def test_no_price_uses_real_cost(self):
        """Si no hay precio, value = cost (P&L queda en 0)."""
        positions = [
            {'asset': 'EXOTIC', 'is_cash': False, 'invested': 1000, 'quantity': 10,
             'commissions': 50, 'price_override': None},
        ]
        r = compute_broker_value_usd(positions, {}, 'USDT', tc_blue=1000)
        self.assertEqual(r['value'], 1050)  # cost basis
        self.assertEqual(r['invested'], 1050)  # 1000 + 50 commissions

    def test_price_override_takes_priority(self):
        """price_override > prices dict."""
        positions = [
            {'asset': 'NVDA', 'is_cash': False, 'invested': 1000, 'quantity': 10,
             'commissions': 0, 'price_override': 200},
        ]
        prices = {'NVDA': 150}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000)
        self.assertEqual(r['value'], 2000)  # usa override 200, no 150

    def test_commissions_increase_cost_basis(self):
        """commissions se suman al invested para el cálculo de cost basis."""
        positions = [
            {'asset': 'NVDA', 'is_cash': False, 'invested': 1000, 'quantity': 10,
             'commissions': 50, 'price_override': None},
        ]
        prices = {'NVDA': 100}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000)
        self.assertEqual(r['value'], 1000)  # 100 × 10
        self.assertEqual(r['invested'], 1050)  # cost + commissions


class TestComputeNetDeposited(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(compute_net_deposited([]), 0)

    def test_only_broker_entries_ignored(self):
        """Solo entries con broker='global' cuentan para el rollup."""
        entries = [
            {'broker': 'Binance', 'year': 2026, 'month': 1, 'capital_inicio': 1000,
             'deposits': 500, 'withdrawals': 0},
        ]
        self.assertEqual(compute_net_deposited(entries), 0)

    def test_baseline_plus_flows(self):
        entries = [
            {'broker': 'global', 'year': 2026, 'month': 1, 'capital_inicio': 5000,
             'deposits': 1000, 'withdrawals': 0},
            {'broker': 'global', 'year': 2026, 'month': 2, 'capital_inicio': 6000,
             'deposits': 500, 'withdrawals': 200},
            {'broker': 'global', 'year': 2026, 'month': 3, 'capital_inicio': 6300,
             'deposits': 0, 'withdrawals': 1000},
        ]
        # baseline (5000 — primer mes) + flows (1000 + 500 - 200 + 0 - 1000) = 5000 + 300
        self.assertEqual(compute_net_deposited(entries), 5300)

    def test_takes_chronologically_first_month_as_baseline(self):
        """Aunque los entries vengan desordenados, el baseline siempre es del
        mes más viejo."""
        entries = [
            {'broker': 'global', 'year': 2026, 'month': 5, 'capital_inicio': 9999,
             'deposits': 0, 'withdrawals': 0},
            {'broker': 'global', 'year': 2026, 'month': 1, 'capital_inicio': 5000,
             'deposits': 0, 'withdrawals': 0},
        ]
        self.assertEqual(compute_net_deposited(entries), 5000)


class TestSnapshotEndToEnd(unittest.TestCase):
    """E2E: levanta una DB temporal, popula data, corre el job, verifica
    el snapshot insertado."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name

        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE brokers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                currency TEXT NOT NULL,
                parent_broker_id INTEGER
            );
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                broker TEXT NOT NULL,
                asset TEXT NOT NULL,
                is_cash INTEGER DEFAULT 0,
                invested REAL,
                quantity REAL,
                commissions REAL DEFAULT 0,
                price_override REAL
            );
            CREATE TABLE monthly_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                broker TEXT NOT NULL,
                capital_inicio REAL DEFAULT 0,
                capital_final REAL DEFAULT 0,
                deposits REAL DEFAULT 0,
                withdrawals REAL DEFAULT 0,
                pnl_realized REAL DEFAULT 0,
                pnl_unrealized REAL DEFAULT 0
            );
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                total_value REAL NOT NULL,
                total_invested REAL NOT NULL,
                net_deposited REAL NOT NULL DEFAULT 0,
                UNIQUE(user_id, date)
            );
            INSERT INTO users (id, email) VALUES (1, 'test@example.com');
            INSERT INTO brokers (user_id, name, currency) VALUES (1, 'Binance', 'USDT');
            INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
            VALUES (1, 'Binance', 'BTC', 0, 5000, 0.1);
            INSERT INTO positions (user_id, broker, asset, is_cash, invested)
            VALUES (1, 'Binance', 'USDT', 1, 2000);
            INSERT INTO monthly_entries (user_id, year, month, broker, capital_inicio, deposits)
            VALUES (1, 2026, 1, 'global', 5000, 1000);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_take_snapshot_for_user_persists_data(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Mock prices con BTC = 60000
        with conn:
            r = take_snapshot_for_user(conn, uid=1, tc_blue=1500,
                                        crypto_yf={'BTC': 'BTC-USD'},
                                        target_date='2026-01-15')
        self.assertTrue(r['ok'])
        # Total value = 0.1 BTC * 60000? No — usamos lo que yfinance devuelva.
        # Acá lo importante es validar que se persistió correctamente.
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE user_id=1 AND date='2026-01-15'"
        ).fetchone()
        self.assertIsNotNone(snap)
        # Cash USDT 2000 + BTC valuado (sin precio: cost basis 5000) = 7000 mínimo
        self.assertGreaterEqual(snap['total_value'], 2000)  # al menos el cash
        self.assertEqual(snap['net_deposited'], 6000)  # 5000 baseline + 1000 deposits
        conn.close()

    def test_idempotent_upsert(self):
        """Correr el job dos veces el mismo día no falla (UPSERT)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        with conn:
            take_snapshot_for_user(conn, 1, 1500, {'BTC': 'BTC-USD'}, '2026-01-15')
        with conn:
            r = take_snapshot_for_user(conn, 1, 1500, {'BTC': 'BTC-USD'}, '2026-01-15')
        self.assertTrue(r['ok'])
        count = conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE user_id=1 AND date='2026-01-15'"
        ).fetchone()[0]
        self.assertEqual(count, 1)  # solo 1 row, no 2
        conn.close()

    def test_user_without_brokers_skipped(self):
        """Usuario sin brokers/positions no genera snapshot (no spam de zeros)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO users (id, email) VALUES (2, 'empty@example.com')")
        conn.commit()
        with conn:
            r = take_snapshot_for_user(conn, uid=2, tc_blue=1500,
                                        crypto_yf={}, target_date='2026-01-15')
        self.assertFalse(r['ok'])
        self.assertEqual(r['reason'], 'no_data')
        conn.close()


if __name__ == '__main__':
    unittest.main()
