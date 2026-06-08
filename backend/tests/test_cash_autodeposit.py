"""El cash nunca queda negativo en una alta MANUAL de posición.

Si el user agrega una posición/compra sin haber cargado el depósito antes, el
sistema auto-deposita el faltante (sube cash a 0 + lo registra como capital
aportado, para que el P&L no muestre una ganancia falsa).

Corre con: cd backend && python3 -m pytest tests/test_cash_autodeposit.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main


class CashAutodepositTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("positions", "operations", "monthly_entries", "config",
                  "brokers", "users", "import_op_links", "import_normalized_tx",
                  "import_raw_rows", "import_batches", "snapshots"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cash@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _broker(self, name, ccy):
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, name, ccy))
        self.conn.commit()

    def _seed_cash(self, broker, asset, amount):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
            (self.uid, broker, asset, amount))
        self.conn.commit()

    def _cash(self, broker):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) c FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()
        return float(r["c"] or 0)

    def _global_deposits(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,)).fetchone()
        return float(r["d"] or 0)

    def _pos(self, broker, asset="BTC", invested=1000.0):
        return main.PositionIn(broker=broker, asset=asset, is_cash=False,
                               invested=invested, quantity=0.01, buy_price=100000.0,
                               entry_date="2026-01-15")

    # ── casos ────────────────────────────────────────────────────────────────
    def test_usd_buy_no_cash_floors_at_zero(self):
        self._broker("Binance", "USDT")
        main.create_position(self._pos("Binance"), self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 0.0, places=2)      # no negativo
        self.assertAlmostEqual(self._global_deposits(), 1000.0, places=2)  # capital aportado +1000

    def test_buy_with_enough_cash_no_autodeposit(self):
        self._broker("Binance", "USDT")
        self._seed_cash("Binance", "USDT", 5000)
        main.create_position(self._pos("Binance"), self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 4000.0, places=2)   # 5000 - 1000
        self.assertAlmostEqual(self._global_deposits(), 0.0, places=2)    # nada auto-depositado

    def test_partial_cash_autodeposits_only_shortfall(self):
        self._broker("Binance", "USDT")
        self._seed_cash("Binance", "USDT", 300)
        main.create_position(self._pos("Binance"), self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 0.0, places=2)      # 300 + 700 - 1000
        self.assertAlmostEqual(self._global_deposits(), 700.0, places=2)  # solo el faltante

    def test_ars_buy_autodeposit_converted_usd(self):
        self._broker("Cocos", "ARS")
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        main.create_position(self._pos("Cocos", asset="GGAL", invested=100000.0), self.uid)
        self.assertAlmostEqual(self._cash("Cocos"), 0.0, places=2)
        # capital aportado en USD = 100.000 ARS / 1000 = 100
        self.assertAlmostEqual(self._global_deposits(), 100.0, places=2)

    def test_cash_position_itself_not_affected(self):
        # Agregar una posición de CASH (is_cash) no debe disparar auto-deposit.
        self._broker("Binance", "USDT")
        p = main.PositionIn(broker="Binance", asset="USDT", is_cash=True, invested=500.0,
                            entry_date="2026-01-15")
        main.create_position(p, self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 500.0, places=2)
        self.assertAlmostEqual(self._global_deposits(), 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
