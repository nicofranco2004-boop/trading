"""Normalización de unidad de bonos: costo guardado "por 100 nominales" → "por 1 VN".

Bug real (IEB): el export trae los bonos por 100 nominales (AL30 PPP 59.59) pero el
precio actual se resuelve por 1 VN (data912 ÷100 → 0.64) → P&L -99% fantasma. El fix
detecta la unidad comparando el costo contra el precio de mercado per-1 y divide por
100 SOLO los que están per-100 — sin romper los que ya vienen per-1 (Balanz).

Corre con: cd backend && python3 -m pytest tests/test_bond_unit_normalization.py
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

import main  # noqa: E402
from importing import recompute_backfill as rb  # noqa: E402
from importing.normalizer import guess_asset_type  # noqa: E402


class BondPer100FactorTest(unittest.TestCase):
    """La función pura de detección de unidad."""

    def test_per100_detected(self):
        # AL30 real: costo 59.59 vs mercado 0.6434 → ratio ~93 → per-100 → ÷100.
        self.assertEqual(rb.bond_per100_factor(59.59, 0.6434), 0.01)

    def test_per1_left_alone(self):
        # Ya per-1 (costo ≈ mercado) → factor 1.
        self.assertEqual(rb.bond_per100_factor(0.5959, 0.6434), 1.0)

    def test_bought_cheap_still_per1(self):
        # Comprado barato (0.30) vs mercado 0.84 → ratio 0.36 → NO es cambio de
        # unidad, factor 1 (no confundir "compré barato" con per-100).
        self.assertEqual(rb.bond_per100_factor(0.30, 0.84), 1.0)

    def test_ars_per1_left_alone(self):
        # Balanz AO28 ARS: costo 1367 vs mercado per-1 ARS 1387 → ratio ~1 → factor 1.
        self.assertEqual(rb.bond_per100_factor(1367.0, 1387.0), 1.0)

    def test_no_market_price_no_change(self):
        self.assertEqual(rb.bond_per100_factor(59.59, None), 1.0)
        self.assertEqual(rb.bond_per100_factor(59.59, 0.0), 1.0)

    def test_garbage_ratio_not_touched(self):
        # Ratio absurdo (>1000): no es un per-100 limpio → no tocar (evita romper
        # un valor con otro problema, ej. moneda).
        self.assertEqual(rb.bond_per100_factor(50000.0, 0.64), 1.0)


class NormalizeBondUnitsTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("positions", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("bondunit@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "IEB", "ARS"))
        self.conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                          "VALUES (?,?,?,(SELECT id FROM brokers WHERE user_id=? AND name='IEB'))",
                          (self.uid, "IEB · USD", "USD", self.uid))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _add(self, broker, asset, qty, invested, buy_price, ccy, at="BOND"):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested, "
            "buy_price, currency, asset_type) VALUES (?,?,?,0,?,?,?,?,?)",
            (self.uid, broker, asset, qty, invested, buy_price, ccy, at))
        self.conn.commit()

    def _get(self, asset):
        return self.conn.execute(
            "SELECT quantity, invested, buy_price FROM positions WHERE user_id=? AND asset=?",
            (self.uid, asset)).fetchone()

    # Resolver de precio de mercado per-1 fake (sin red).
    _MKT = {("AL30", "USD"): 0.6434, ("GD35", "USD"): 0.8435,
            ("AL35", "USD"): 0.84, ("AO28", "ARS"): 1387.0}

    def _resolver(self, sym, ccy):
        return self._MKT.get((str(sym).upper(), (ccy or "").upper()))

    def test_ieb_per100_bond_divided(self):
        # AL30 IEB per-100: 100 nominales, invested 5959 (=59.59×100), bp 59.59.
        self._add("IEB · USD", "AL30", 100, 5959.0, 59.59, "USD")
        n = rb.normalize_bond_units(self.conn, self.uid, bond_price_per1=self._resolver)
        self.assertEqual(n, 1)
        r = self._get("AL30")
        self.assertAlmostEqual(r["invested"], 59.59, places=4)   # ÷100
        self.assertAlmostEqual(r["buy_price"], 0.5959, places=6)

    def test_balanz_per1_bond_untouched(self):
        # AL35 ya per-1 (0.46): NO tocar.
        self._add("IEB · USD", "AL35", 1000, 460.0, 0.46, "USD")
        rb.normalize_bond_units(self.conn, self.uid, bond_price_per1=self._resolver)
        r = self._get("AL35")
        self.assertAlmostEqual(r["invested"], 460.0, places=4)
        self.assertAlmostEqual(r["buy_price"], 0.46, places=6)

    def test_ars_bond_untouched(self):
        # AO28 ARS per-1 (1367 ≈ mercado 1387): NO tocar.
        self._add("IEB", "AO28", 3019, 4126973.0, 1367.0, "ARS")
        rb.normalize_bond_units(self.conn, self.uid, bond_price_per1=self._resolver)
        r = self._get("AO28")
        self.assertAlmostEqual(r["buy_price"], 1367.0, places=4)

    def test_cedear_never_touched(self):
        # Una CEDEAR cara (SPY 12 USD) NO debe normalizarse (no es bono).
        self._add("IEB · USD", "SPY", 10, 124.0, 12.4, "USD", at="CEDEAR")
        rb.normalize_bond_units(self.conn, self.uid, bond_price_per1=self._resolver)
        r = self._get("SPY")
        self.assertAlmostEqual(r["buy_price"], 12.4, places=4)

    def test_idempotent(self):
        self._add("IEB · USD", "GD35", 100, 6716.0, 67.16, "USD")
        n1 = rb.normalize_bond_units(self.conn, self.uid, bond_price_per1=self._resolver)
        n2 = rb.normalize_bond_units(self.conn, self.uid, bond_price_per1=self._resolver)
        self.assertEqual((n1, n2), (1, 0))   # 2da corrida no cambia nada
        r = self._get("GD35")
        self.assertAlmostEqual(r["buy_price"], 0.6716, places=6)


class GuessAssetTypeBondTest(unittest.TestCase):
    def test_known_ar_bond_tagged(self):
        self.assertEqual(guess_asset_type("AL30"), "BOND")
        self.assertEqual(guess_asset_type("GD35"), "BOND")
        self.assertEqual(guess_asset_type("TZX28"), "BOND")

    def test_non_bond_not_tagged(self):
        self.assertNotEqual(guess_asset_type("SPY"), "BOND")
        self.assertNotEqual(guess_asset_type("MELI"), "BOND")


if __name__ == "__main__":
    unittest.main()
