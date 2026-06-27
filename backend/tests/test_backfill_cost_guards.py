"""Guards anti-corrupción del modo COMPLETO del backfill (auditoría 2026-06-27):
  - normalize_bond_units: NO ÷100 a un bono per-1 distressed (costo de escala per-1
    aunque el ratio caiga en (10,1000)); SÍ ÷100 a un per-100 genuino.
  - normalize_usd_commissions: NO toca un fee USD chico de un lote dust (com>inv pero
    de magnitud-USD); SÍ convierte una comisión en pesos (magnitud-pesos).
  - Ambas: respetan linked_ids (no tocan posiciones manuales).
"""
import sqlite3
import unittest

from importing import recompute_backfill as rb


def _mkdb():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE positions (
        id INTEGER PRIMARY KEY, user_id INTEGER, asset TEXT, quantity REAL,
        invested REAL, buy_price REAL, commissions REAL, currency TEXT,
        asset_type TEXT, is_cash INTEGER DEFAULT 0)""")
    return c


def _ins(c, **k):
    cols = "user_id,asset,quantity,invested,buy_price,commissions,currency,asset_type,is_cash"
    d = {"user_id": 1, "asset": "X", "quantity": 1, "invested": 0, "buy_price": 0,
         "commissions": 0, "currency": "USD", "asset_type": "BOND", "is_cash": 0}
    d.update(k)
    c.execute(f"INSERT INTO positions ({cols}) VALUES ({','.join('?'*9)})",
              tuple(d[x] for x in cols.split(",")))
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]


class BondUnitGuardTest(unittest.TestCase):
    def test_distressed_per1_usd_not_divided(self):
        # Bono USD per-1 comprado a la par (1.0) hoy desplomado a 0.03 → ratio 33
        # cae en (10,1000) PERO el costo (1.0) es escala per-1 → NO tocar.
        c = _mkdb()
        pid = _ins(c, asset="DEFAULTUSD", quantity=100, invested=100.0, buy_price=1.0, currency="USD")
        rb.normalize_bond_units(c, 1, bond_price_per1=lambda s, ccy: 0.03, tc_blue=1450)
        r = c.execute("SELECT invested, buy_price FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["invested"], 100.0)   # SIN tocar
        self.assertAlmostEqual(r["buy_price"], 1.0)

    def test_distressed_per1_ars_not_divided(self):
        # Bono ARS per-1 (costo 700) desplomado, market 35 → ratio 20 → NO tocar
        # (700/1450 = 0.48 USD-equiv < 3 → escala per-1).
        c = _mkdb()
        pid = _ins(c, asset="CERARS", quantity=100, invested=70000.0, buy_price=700.0, currency="ARS")
        rb.normalize_bond_units(c, 1, bond_price_per1=lambda s, ccy: 35.0, tc_blue=1450)
        r = c.execute("SELECT invested FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["invested"], 70000.0)   # SIN tocar

    def test_genuine_per100_usd_divided(self):
        # Bono USD per-100 (costo 64 = par) vs market per-1 0.64 → ratio 100, costo
        # escala per-100 (64 ≥ 3) → ÷100.
        c = _mkdb()
        pid = _ins(c, asset="AL30", quantity=10, invested=640.0, buy_price=64.0, currency="USD")
        rb.normalize_bond_units(c, 1, bond_price_per1=lambda s, ccy: 0.64, tc_blue=1450)
        r = c.execute("SELECT invested, buy_price FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["invested"], 6.4)     # ÷100
        self.assertAlmostEqual(r["buy_price"], 0.64)

    def test_genuine_per100_ars_divided(self):
        # ARS per-100 (costo 96000) vs market 963 → ratio 100, 96000/1450=66 ≥3 → ÷100
        c = _mkdb()
        pid = _ins(c, asset="AL30", quantity=10, invested=960000.0, buy_price=96000.0, currency="ARS")
        rb.normalize_bond_units(c, 1, bond_price_per1=lambda s, ccy: 963.0, tc_blue=1450)
        r = c.execute("SELECT invested FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["invested"], 9600.0)   # ÷100

    def test_manual_position_skipped(self):
        c = _mkdb()
        pid = _ins(c, asset="AL30", quantity=10, invested=960000.0, buy_price=96000.0, currency="ARS")
        rb.normalize_bond_units(c, 1, bond_price_per1=lambda s, ccy: 963.0, tc_blue=1450, linked_ids=set())
        r = c.execute("SELECT invested FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["invested"], 960000.0)   # manual → no tocar


class UsdCommissionGuardTest(unittest.TestCase):
    def test_dust_usd_commission_not_divided(self):
        # Fee USD genuino chico (0.95) > invertido ínfimo (0.30) pero magnitud-USD → no tocar
        c = _mkdb()
        pid = _ins(c, asset="X", quantity=1, invested=0.30, commissions=0.95, currency="USD")
        rb.normalize_usd_commissions(c, 1, tc_blue=1450)
        r = c.execute("SELECT commissions FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["commissions"], 0.95)   # SIN tocar

    def test_peso_commission_divided(self):
        # YM39O real: com 31701 (ARS) > invertido 5028 (USD), magnitud-pesos → ÷tc_blue
        c = _mkdb()
        pid = _ins(c, asset="YM39O", quantity=50, invested=5028.0, commissions=31701.0, currency="USD")
        rb.normalize_usd_commissions(c, 1, tc_blue=1450)
        r = c.execute("SELECT commissions FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["commissions"], 31701.0 / 1450, places=3)

    def test_manual_commission_skipped(self):
        c = _mkdb()
        pid = _ins(c, asset="YM39O", quantity=50, invested=5028.0, commissions=31701.0, currency="USD")
        rb.normalize_usd_commissions(c, 1, tc_blue=1450, linked_ids=set())
        r = c.execute("SELECT commissions FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertAlmostEqual(r["commissions"], 31701.0)   # manual → no tocar


if __name__ == "__main__":
    unittest.main()
