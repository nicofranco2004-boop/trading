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

from unittest.mock import patch

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


class TestCedearValuationInUsdSubbroker(unittest.TestCase):
    """C1 regression — un CEDEAR comprado por dólar-MEP vive en un sub-broker
    '<Padre> · USD' (currency='USDT') con asset_type='CEDEAR'. DEBE valuarse por
    su precio LOCAL .BA (ARS) ÷ dólar-MEP, NO por el ticker US (que vale 15-100×
    más). Ver CORRECTNESS_AUDIT_2026-06-25.md (C1) y frontend valuation.js:184-193.
    """

    def test_cedear_in_usd_subbroker_values_via_ba_and_mep(self):
        # 15 CEDEARs de TSLA: la acción US vale 440, el CEDEAR .BA vale 14.000 ARS.
        # Correcto: 14.000 × 15 / MEP(1200) = 175 USD. Bug: 440 × 15 = 6.600 USD.
        positions = [
            {'asset': 'TSLA', 'asset_type': 'CEDEAR', 'is_cash': False,
             'invested': 6000, 'quantity': 15, 'commissions': 0, 'price_override': None},
        ]
        prices = {'TSLA': 440, 'TSLA.BA': 14000}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000,
                                     broker_name='Cocos Capital · USD', cedear_rate=1200)
        self.assertAlmostEqual(r['value'], 14000 * 15 / 1200, places=4)
        self.assertNotAlmostEqual(r['value'], 6600, places=0)

    def test_cedear_detected_by_asset_type_without_subbroker_name(self):
        # asset_type='CEDEAR' por sí solo dispara la rama .BA/MEP, sin importar el
        # nombre del broker (mismo criterio que el frontend).
        positions = [
            {'asset': 'AAPL', 'asset_type': 'CEDEAR', 'is_cash': False,
             'invested': 5000, 'quantity': 20, 'commissions': 0, 'price_override': None},
        ]
        prices = {'AAPL': 250, 'AAPL.BA': 30000}
        r = compute_broker_value_usd(positions, prices, 'USD', tc_blue=1000,
                                     broker_name='Balanz', cedear_rate=1200)
        self.assertAlmostEqual(r['value'], 30000 * 20 / 1200, places=4)

    def test_ar_usd_subbroker_values_ar_stock_via_ba_and_mep(self):
        # Una acción AR (PAMP, sin acción US) en un sub-broker '· USD' se valúa por
        # .BA/MEP aunque asset_type no sea 'CEDEAR' — la detecta el nombre '· USD'.
        positions = [
            {'asset': 'PAMP', 'asset_type': 'STOCK_AR', 'is_cash': False,
             'invested': 100, 'quantity': 50, 'commissions': 0, 'price_override': None},
        ]
        prices = {'PAMP.BA': 6000}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000,
                                     broker_name='IOL · USD', cedear_rate=1200)
        self.assertAlmostEqual(r['value'], 6000 * 50 / 1200, places=4)

    def test_normal_us_stock_unaffected(self):
        # Regresión: una acción US normal en un broker USD se sigue valuando por su
        # ticker US, NO por .BA.
        positions = [
            {'asset': 'NVDA', 'asset_type': 'STOCK', 'is_cash': False,
             'invested': 1000, 'quantity': 10, 'commissions': 0, 'price_override': None},
        ]
        prices = {'NVDA': 150, 'NVDA.BA': 999999}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000,
                                     broker_name='IBKR', cedear_rate=1200)
        self.assertEqual(r['value'], 1500)

    def test_trust_guard_caps_absurd_cedear_price(self):
        # Si el .BA está roto/colisionado y da un valor absurdo (>50× el costo),
        # caemos a costo en vez de distorsionar la cartera.
        positions = [
            {'asset': 'X', 'asset_type': 'CEDEAR', 'is_cash': False,
             'invested': 100, 'quantity': 1, 'commissions': 0, 'price_override': None},
        ]
        prices = {'X.BA': 6_000_000}  # /1000 = 6000 USD vs costo 100 → mult 60 >50
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000,
                                     broker_name='Cocos · USD', cedear_rate=1000)
        self.assertEqual(r['value'], 100)  # cae a costo

    def test_price_override_on_cedear_respected(self):
        # price_override (USD a mano) siempre gana, incluso para un CEDEAR.
        positions = [
            {'asset': 'TSLA', 'asset_type': 'CEDEAR', 'is_cash': False,
             'invested': 100, 'quantity': 10, 'commissions': 0, 'price_override': 20},
        ]
        prices = {'TSLA.BA': 14000}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000,
                                     broker_name='Cocos · USD', cedear_rate=1200)
        self.assertEqual(r['value'], 200)  # 20 × 10, en USD directo

    def test_override_zero_values_at_zero(self):
        # price_override=0 (activo marcado sin valor) → value 0, NO el de mercado.
        # Audit Fase 1: `is not None`, no `or` (mirror del `??` del frontend).
        positions = [
            {'asset': 'DEAD', 'asset_type': 'STOCK', 'is_cash': False,
             'invested': 1000, 'quantity': 10, 'commissions': 0, 'price_override': 0},
        ]
        r = compute_broker_value_usd(positions, {'DEAD': 150}, 'USDT', tc_blue=1000,
                                     broker_name='IBKR', cedear_rate=1200)
        self.assertEqual(r['value'], 0)

    def test_genuine_usd_broker_not_treated_as_subbroker(self):
        # Un broker USD genuino llamado '... USD' (sin '·') NO es sub-broker AR:
        # sus acciones US se valúan por su ticker US, no por .BA/MEP. Audit Fase 1.
        positions = [
            {'asset': 'NVDA', 'asset_type': 'STOCK', 'is_cash': False,
             'invested': 1000, 'quantity': 10, 'commissions': 0, 'price_override': None},
        ]
        prices = {'NVDA': 150, 'NVDA.BA': 999999}
        r = compute_broker_value_usd(positions, prices, 'USDT', tc_blue=1000,
                                     broker_name='Mi Broker USD', cedear_rate=1200)
        self.assertEqual(r['value'], 1500)  # ticker US, NO .BA

    def test_ars_broker_holdings_and_cash_use_mep(self):
        # Convención única (audit variaciones H-1): en un broker ARS, TENENCIAS y
        # CASH se valúan al dólar-MEP (cedear_rate) — espejo del frontend
        # (pickFinancialRate = MEP para todo). Antes el cash iba al blue → snapshot
        # de sabor mixto y el live-vs-snapshot fabricaba el spread blue−MEP como
        # "P&L Día" fantasma permanente. GGAL 100 @ .BA 1500 = 150.000 ARS.
        holding = [{'asset': 'GGAL', 'asset_type': 'STOCK_AR', 'is_cash': False,
                    'invested': 140000, 'quantity': 100, 'commissions': 0, 'price_override': None}]
        r = compute_broker_value_usd(holding, {'GGAL.BA': 1500}, 'ARS', tc_blue=1530,
                                     broker_name='Balanz', cedear_rate=1499)
        self.assertAlmostEqual(r['value'], 150000 / 1499, places=2)     # MEP, no /1530
        self.assertAlmostEqual(r['invested'], 140000 / 1499, places=2)
        cash = [{'asset': 'ARS', 'is_cash': True, 'invested': 153000, 'quantity': 0,
                 'commissions': 0, 'price_override': None}]
        rc = compute_broker_value_usd(cash, {}, 'ARS', tc_blue=1530,
                                      broker_name='Balanz', cedear_rate=1499)
        self.assertAlmostEqual(rc['value'], 153000 / 1499, places=2)    # cash TAMBIÉN al MEP

    def test_ars_cash_without_cedear_rate_falls_back_to_tc_blue(self):
        # Callers legacy (sin cedear_rate): default = tc_blue → sin cambio.
        cash = [{'asset': 'ARS', 'is_cash': True, 'invested': 153000, 'quantity': 0,
                 'commissions': 0, 'price_override': None}]
        rc = compute_broker_value_usd(cash, {}, 'ARS', tc_blue=1530)
        self.assertAlmostEqual(rc['value'], 153000 / 1530, places=2)


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
                price_override REAL, asset_type TEXT, currency TEXT
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
                fx_to_usd_blue REAL, holdings_json TEXT,
                UNIQUE(user_id, date)
            );
            CREATE TABLE fx_rates_daily (
                date TEXT PRIMARY KEY,
                blue_venta REAL NOT NULL,
                source TEXT DEFAULT 'unknown',
                fetched_at TEXT DEFAULT (datetime('now'))
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
        # Mock de precios: determinístico (BTC=60000) y con cobertura completa.
        # Sin esto, estos tests dependían de la red real de yfinance — y con el
        # gate de cobertura (no escribir snapshot subvaluado) un fetch fallido
        # los haría skipear. El mock los vuelve estables y offline.
        self._price_patch = patch(
            'snapshots_job.fetch_prices_for_symbols',
            side_effect=lambda syms, cy: {s: 60000.0 for s in syms},
        )
        self._price_patch.start()
        self.addCleanup(self._price_patch.stop)

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

    def test_take_snapshot_stamps_fx_to_usd_blue(self):
        """Phase C: cada snapshot persiste el tc_blue usado, para que el
        frontend pueda renderizar el valor histórico en ARS con el TC de
        esa fecha (no el actual)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        with conn:
            take_snapshot_for_user(conn, uid=1, tc_blue=1500.5,
                                    crypto_yf={'BTC': 'BTC-USD'},
                                    target_date='2026-01-15')
        snap = conn.execute(
            "SELECT fx_to_usd_blue FROM snapshots WHERE user_id=1 AND date='2026-01-15'"
        ).fetchone()
        self.assertIsNotNone(snap)
        self.assertEqual(snap['fx_to_usd_blue'], 1500.5)
        conn.close()

    def test_take_snapshot_upsert_preserves_existing_fx(self):
        """Si el snapshot ya tenía fx stampeado y el upsert llega con NULL,
        no perdemos el dato — COALESCE(excluded.fx, snapshots.fx)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Primera escritura con fx=1500
        with conn:
            take_snapshot_for_user(conn, 1, 1500, {'BTC': 'BTC-USD'}, '2026-01-15')
        # Update manual a NULL (simulando un legacy upsert sin fx)
        conn.execute(
            "UPDATE snapshots SET total_value=9999 WHERE user_id=1 AND date='2026-01-15'"
        )
        conn.commit()
        # Segunda escritura con fx=1600 — debería actualizar
        with conn:
            take_snapshot_for_user(conn, 1, 1600, {'BTC': 'BTC-USD'}, '2026-01-15')
        snap = conn.execute(
            "SELECT fx_to_usd_blue FROM snapshots WHERE user_id=1 AND date='2026-01-15'"
        ).fetchone()
        # El nuevo valor (1600) prevalece — última fuente confiable
        self.assertEqual(snap['fx_to_usd_blue'], 1600)
        conn.close()


class TestRunDailySnapshotFxPersistence(unittest.TestCase):
    """Phase C: el cron también persiste el blue del día en fx_rates_daily
    (tabla global, no per-user). Verifica que esto funciona."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE brokers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, name TEXT NOT NULL,
                currency TEXT NOT NULL, parent_broker_id INTEGER
            );
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, broker TEXT NOT NULL,
                asset TEXT NOT NULL, is_cash INTEGER DEFAULT 0,
                invested REAL, quantity REAL, commissions REAL DEFAULT 0,
                price_override REAL, asset_type TEXT, currency TEXT
            );
            CREATE TABLE monthly_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, year INTEGER NOT NULL,
                month INTEGER NOT NULL, broker TEXT NOT NULL,
                capital_inicio REAL DEFAULT 0, capital_final REAL DEFAULT 0,
                deposits REAL DEFAULT 0, withdrawals REAL DEFAULT 0,
                pnl_realized REAL DEFAULT 0, pnl_unrealized REAL DEFAULT 0
            );
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, date TEXT NOT NULL,
                total_value REAL NOT NULL, total_invested REAL NOT NULL,
                net_deposited REAL NOT NULL DEFAULT 0,
                fx_to_usd_blue REAL, holdings_json TEXT,
                UNIQUE(user_id, date)
            );
            CREATE TABLE fx_rates_daily (
                date TEXT PRIMARY KEY,
                blue_venta REAL NOT NULL,
                source TEXT DEFAULT 'unknown',
                fetched_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO users (id, email) VALUES (1, 'test@example.com');
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_run_daily_persists_fx_rate(self):
        """El cron del job persiste el blue del día en fx_rates_daily."""
        r = run_daily_snapshot(
            self.db_path,
            fetch_tc_blue=lambda: 1425.5,
            crypto_yf={},
            target_date='2026-02-20',
        )
        self.assertTrue(r['ok'])
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT blue_venta, source FROM fx_rates_daily WHERE date='2026-02-20'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['blue_venta'], 1425.5)
        self.assertEqual(row['source'], 'snapshot_cron')
        conn.close()

    def test_run_daily_fx_rate_idempotent(self):
        """Correr el cron dos veces el mismo día upsertea sin duplicar."""
        run_daily_snapshot(self.db_path, lambda: 1500, {}, '2026-02-20')
        run_daily_snapshot(self.db_path, lambda: 1510, {}, '2026-02-20')
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT blue_venta FROM fx_rates_daily WHERE date='2026-02-20'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['blue_venta'], 1510)  # último valor gana
        conn.close()


class TestRunDailySnapshotMepFailClosed(TestRunDailySnapshotFxPersistence):
    """M-7 (audit variaciones): el job resuelve el MEP con fetch directo y si NO
    resuelve, ABORTA (fail-closed) — mejor un día sin snapshot que toda la corrida
    valuada a un rate stale (config default 1415 → ±15% fantasma en la serie).
    Hereda la fixture de TestRunDailySnapshotFxPersistence."""

    def _rows(self, table):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def test_mep_fetch_raises_aborts_job(self):
        def boom():
            raise RuntimeError("dolarapi caído")
        r = run_daily_snapshot(self.db_path, lambda: 1500, {}, '2026-02-20',
                               fetch_tc_mep=boom)
        self.assertFalse(r['ok'])
        self.assertEqual(r['reason'], 'mep_fetch_failed')
        # Fail-closed TOTAL: ni snapshots ni fx_rates_daily de esa corrida.
        self.assertEqual(self._rows('snapshots'), 0)
        self.assertEqual(self._rows('fx_rates_daily'), 0)

    def test_mep_invalid_aborts_job(self):
        for bad in (None, 0, -1):
            r = run_daily_snapshot(self.db_path, lambda: 1500, {}, '2026-02-20',
                                   fetch_tc_mep=lambda: bad)
            self.assertFalse(r['ok'])
            self.assertEqual(r['reason'], 'invalid_mep')
        self.assertEqual(self._rows('snapshots'), 0)

    def test_mep_rate_drives_valuation_not_blue(self):
        """El tc_mep del job valúa el cash ARS (÷MEP, no ÷blue) — H-1."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (1, 'Balanz', 'ARS')")
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
            "VALUES (1, 'Balanz', 'ARS', 1, 150000)")
        conn.commit()
        conn.close()
        r = run_daily_snapshot(self.db_path, lambda: 1500, {}, '2026-02-20',
                               fetch_tc_mep=lambda: 1000)
        self.assertTrue(r['ok'])
        conn = sqlite3.connect(self.db_path)
        val = conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=1 AND date='2026-02-20'"
        ).fetchone()[0]
        conn.close()
        # 150.000 ARS ÷ MEP 1000 = 150 (si usara el blue 1500 daría 100)
        self.assertAlmostEqual(val, 150.0, places=2)

    def test_legacy_call_without_fetch_tc_mep_still_works(self):
        """Callers legacy (sin fetch_tc_mep): sin abort, comportamiento previo."""
        r = run_daily_snapshot(self.db_path, lambda: 1500, {}, '2026-02-20')
        self.assertTrue(r['ok'])


class TestSnapshotCoverageGate(unittest.TestCase):
    """INTEGRIDAD: el cron NO debe persistir un snapshot subvaluado cuando
    yfinance no devolvió precio para una porción grande del portfolio. Mejor
    un día sin dato que un dato corrupto (que rompe la variación diaria)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE brokers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, currency TEXT, parent_broker_id INTEGER);
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, broker TEXT, asset TEXT,
                is_cash INTEGER DEFAULT 0, invested REAL, quantity REAL, commissions REAL DEFAULT 0, price_override REAL, asset_type TEXT, currency TEXT
            );
            CREATE TABLE monthly_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, year INTEGER, month INTEGER,
                broker TEXT, capital_inicio REAL DEFAULT 0, deposits REAL DEFAULT 0, withdrawals REAL DEFAULT 0
            );
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date TEXT,
                total_value REAL NOT NULL, total_invested REAL NOT NULL, net_deposited REAL DEFAULT 0,
                fx_to_usd_blue REAL, holdings_json TEXT, UNIQUE(user_id, date)
            );
            CREATE TABLE asset_last_price (
                symbol TEXT PRIMARY KEY, price REAL NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO users (id, email) VALUES (1, 't@x.com');
            INSERT INTO brokers (user_id, name, currency) VALUES (1, 'Schwab', 'USD');
            -- AAPL grande (9700) + XYZ chico (100). Cubrir AAPL = 98.9% del cost.
            INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
            VALUES (1, 'Schwab', 'AAPL', 0, 9700, 50);
            INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
            VALUES (1, 'Schwab', 'XYZ', 0, 100, 1);
            INSERT INTO monthly_entries (user_id, year, month, broker, capital_inicio)
            VALUES (1, 2026, 1, 'global', 9000);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def _snap_count(self, conn, date='2026-06-02'):
        return conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE user_id=1 AND date=?", (date,)
        ).fetchone()[0]

    def test_low_coverage_skips_write(self):
        """yfinance no devuelve ningún precio → cobertura 0% → NO escribe."""
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        with patch('snapshots_job.fetch_prices_for_symbols',
                   side_effect=lambda syms, cy: {s: None for s in syms}):
            with conn:
                r = take_snapshot_for_user(conn, 1, 1500, {}, '2026-06-02')
        self.assertFalse(r['ok'])
        self.assertEqual(r['reason'], 'low_price_coverage')
        self.assertEqual(self._snap_count(conn), 0)  # nada escrito
        conn.close()

    def test_low_coverage_does_not_overwrite_existing(self):
        """Si ya hay un snapshot bueno y el fetch falla, NO lo pisa."""
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (1, '2026-06-02', 12345.0, 9800.0, 9000.0)")
        conn.commit()
        with patch('snapshots_job.fetch_prices_for_symbols',
                   side_effect=lambda syms, cy: {s: None for s in syms}):
            with conn:
                r = take_snapshot_for_user(conn, 1, 1500, {}, '2026-06-02')
        self.assertFalse(r['ok'])
        snap = conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=1 AND date='2026-06-02'").fetchone()
        self.assertEqual(snap['total_value'], 12345.0)  # intacto
        conn.close()

    def test_full_coverage_writes(self):
        """Todos los símbolos con precio → escribe normal."""
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        with patch('snapshots_job.fetch_prices_for_symbols',
                   side_effect=lambda syms, cy: {s: 100.0 for s in syms}):
            with conn:
                r = take_snapshot_for_user(conn, 1, 1500, {}, '2026-06-02')
        self.assertTrue(r['ok'])
        self.assertEqual(self._snap_count(conn), 1)
        conn.close()

    def test_small_unpriced_fraction_still_writes(self):
        """Un activo chico sin precio (98.9% cubierto) NO bloquea el snapshot."""
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        # AAPL con precio, XYZ (100 de 9800 = 1%) sin precio → cobertura 98.9%
        with patch('snapshots_job.fetch_prices_for_symbols',
                   side_effect=lambda syms, cy: {s: (150.0 if s == 'AAPL' else None) for s in syms}):
            with conn:
                r = take_snapshot_for_user(conn, 1, 1500, {}, '2026-06-02')
        self.assertTrue(r['ok'])
        self.assertEqual(self._snap_count(conn), 1)
        conn.close()

    def test_uses_last_known_price_not_cost(self):
        """Sin precio hoy pero CON último precio conocido → valúa al último
        precio real (no a cost basis) → sin salto fantasma + cobertura pasa."""
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        # Última vez: AAPL=200, XYZ=50 (costos: AAPL 9700/50u=194, XYZ 100/1u=100)
        conn.execute("INSERT INTO asset_last_price VALUES ('AAPL', 200.0, '2026-06-01')")
        conn.execute("INSERT INTO asset_last_price VALUES ('XYZ', 50.0, '2026-06-01')")
        conn.commit()
        with patch('snapshots_job.fetch_prices_for_symbols',
                   side_effect=lambda syms, cy: {s: None for s in syms}):  # yfinance caído hoy
            with conn:
                r = take_snapshot_for_user(conn, 1, 1500, {}, '2026-06-02')
        self.assertTrue(r['ok'])  # cobertura OK porque last-known completa
        snap = conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=1 AND date='2026-06-02'").fetchone()
        # AAPL 200×50 + XYZ 50×1 = 10050 (NO el cost basis 9800)
        self.assertAlmostEqual(snap['total_value'], 10050.0, places=1)
        conn.close()

    def test_persists_fresh_prices_as_last_known(self):
        """Un fetch exitoso guarda el precio en asset_last_price para mañana."""
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        with patch('snapshots_job.fetch_prices_for_symbols',
                   side_effect=lambda syms, cy: {s: 175.0 for s in syms}):
            with conn:
                take_snapshot_for_user(conn, 1, 1500, {}, '2026-06-02')
        row = conn.execute("SELECT price FROM asset_last_price WHERE symbol='AAPL'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['price'], 175.0)
        conn.close()


class TestSnapshotCedearValuationE2E(unittest.TestCase):
    """C1 end-to-end: un CEDEAR en sub-broker '· USD' (currency='USDT') se persiste
    valuado por su precio .BA ÷ MEP, NO por el ticker US. Prueba el wiring completo
    de take_snapshot_for_user (SELECT asset_type, build_price_symbols pide .BA, la
    cobertura mira .BA, compute usa cedear_rate=MEP)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE brokers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, currency TEXT, parent_broker_id INTEGER);
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, broker TEXT, asset TEXT,
                is_cash INTEGER DEFAULT 0, invested REAL, quantity REAL, commissions REAL DEFAULT 0, price_override REAL, asset_type TEXT, currency TEXT
            );
            CREATE TABLE monthly_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, year INTEGER, month INTEGER,
                broker TEXT, capital_inicio REAL DEFAULT 0, deposits REAL DEFAULT 0, withdrawals REAL DEFAULT 0
            );
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date TEXT,
                total_value REAL NOT NULL, total_invested REAL NOT NULL, net_deposited REAL DEFAULT 0,
                fx_to_usd_blue REAL, holdings_json TEXT, UNIQUE(user_id, date)
            );
            CREATE TABLE asset_last_price (symbol TEXT PRIMARY KEY, price REAL NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE config (user_id INTEGER, key TEXT, value REAL);
            INSERT INTO users (id, email) VALUES (1, 't@x.com');
            INSERT INTO brokers (user_id, name, currency) VALUES (1, 'Cocos Capital · USD', 'USDT');
            INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity, asset_type)
            VALUES (1, 'Cocos Capital · USD', 'TSLA', 0, 180, 15, 'CEDEAR');
            INSERT INTO monthly_entries (user_id, year, month, broker, capital_inicio)
            VALUES (1, 2026, 1, 'global', 180);
            INSERT INTO config (user_id, key, value) VALUES (1, 'tc_mep', 1200), (1, 'tc_blue', 1500);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_cedear_persisted_via_ba_and_mep_not_us_ticker(self):
        seen = {}

        def fake_fetch(syms, cy):
            seen['syms'] = list(syms)
            # Devolvemos SOLO el .BA (14.000 ARS). Si el código pidiera el ticker US,
            # quedaría sin precio → cobertura 0% → no escribiría.
            return {s: (14000.0 if s == 'TSLA.BA' else None) for s in syms}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        with patch('snapshots_job.fetch_prices_for_symbols', side_effect=fake_fetch):
            with conn:
                r = take_snapshot_for_user(conn, 1, 1500, {}, '2026-06-02')
        # Pidió el .BA, NO el ticker US (que daría ~6.600 USD).
        self.assertIn('TSLA.BA', seen['syms'])
        self.assertNotIn('TSLA', seen['syms'])
        self.assertTrue(r['ok'])
        snap = conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=1 AND date='2026-06-02'"
        ).fetchone()
        # 14.000 × 15 / 1200 (MEP) = 175. NO 440×15=6.600 (US), NI /1500 (blue).
        self.assertAlmostEqual(snap['total_value'], 14000 * 15 / 1200, places=2)
        conn.close()


if __name__ == '__main__':
    unittest.main()
