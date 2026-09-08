"""La venta manual sella el TC que REALMENTE usó para dividir el P&L.

CONTEXTO. En `POST /api/positions/sell` el campo "TC de venta"
(`SellIn.tc_venta`) es **opcional**: si el usuario lo deja vacío, el cálculo del
P&L cae al TC de la fecha de la operación (`fx_for_date`) para las cuentas en
FX v2. Eso está bien y es deliberado.

EL BUG (auditoría 1A, hallazgo A-7). El P&L se dividía por el TC resuelto, pero
había otros dos lugares que seguían mirando el campo CRUDO del formulario:

  · `fx_stamp = (data.tc_venta or 1)` → la fila de `operations` quedaba con
    `fx_to_usd = 1.0` mientras su `pnl_usd` estaba dividido por ~1.400. Todo
    lector que use ese campo para reconstruir el nominal en pesos
    (`Positions.jsx`, `useHistoricalMoney`) mostraba el número ~1.400× mal, y la
    fila era indistinguible de una venta en dólares genuina.
  · `tc_v = data.tc_venta or 1` → `monthly_entries.pnl_realized` del broker
    recibía el P&L EN PESOS como si fueran dólares, y de ahí pasaba a
    `capital_final`, propagado hacia adelante por `_repair_monthly_chain`.

El motor del import (`rebuild.py:492`) ya estampaba el TC resuelto: el bug estaba
en 1 de los 2 escritores de ventas.

Corre con: cd backend && python3 -m pytest tests/test_sell_fifo_fx_stamp.py
"""
import unittest

import main
from fastapi.testclient import TestClient


class SellFifoFxStampTest(unittest.TestCase):
    BROKER = "TestVenta"
    FECHA = "2024-03-15"
    TC_DE_LA_FECHA = 1000.0        # lejos de 1 y de cualquier default

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "snapshots",
                  "brokers", "fx_rates_daily", "config", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('venta@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'ARS')",
                     (self.uid, self.BROKER))
        # Cuenta en FX v2 (la que resuelve el TC por fecha).
        conn.execute("INSERT INTO config (user_id,key,value) VALUES (?,?,?)",
                     (self.uid, "fx_version", "v2"))
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
            (self.FECHA, 950.0, self.TC_DE_LA_FECHA))
        # Lote: 10 unidades compradas a 1.000 ARS = 10.000 ARS invertidos.
        self.pid = conn.execute(
            """INSERT INTO positions
               (user_id,broker,asset,is_cash,buy_price,quantity,invested,
                currency,entry_date,commissions)
               VALUES (?,?,'GGAL',0,1000,10,10000,'ARS','2024-01-10',0)""",
            (self.uid, self.BROKER)).lastrowid
        conn.commit()
        conn.close()
        self.client = TestClient(main.app)
        self.hdr = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _vender_sin_tc(self):
        """El caso real: el usuario deja vacío el campo opcional 'TC de venta'."""
        r = self.client.post("/api/positions/sell", headers=self.hdr,
                             json={"broker": self.BROKER, "asset": "GGAL",
                                   "quantity": 10, "exit_price": 2000,
                                   "date": self.FECHA})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _venta(self):
        conn = main.get_db()
        row = conn.execute(
            "SELECT pnl_usd, fx_to_usd, currency FROM operations "
            "WHERE user_id=? AND op_type='Venta' LIMIT 1", (self.uid,)).fetchone()
        conn.close()
        return row

    def test_sella_el_tc_de_la_fecha_y_no_uno(self):
        """REGRESIÓN A-7: `fx_to_usd = 1.0` en una venta en pesos dice que un peso
        vale un dólar. No existe caso legítimo."""
        self._vender_sin_tc()
        row = self._venta()
        self.assertEqual(row["currency"], "ARS")
        self.assertAlmostEqual(float(row["fx_to_usd"]), self.TC_DE_LA_FECHA, places=2)
        self.assertNotAlmostEqual(float(row["fx_to_usd"]), 1.0, places=2)

    def test_el_pnl_sellado_es_coherente_con_el_tc_sellado(self):
        """El invariante que el bug rompía: `pnl_usd × fx_to_usd` tiene que dar el
        P&L en pesos. Con el sello en 1.0, la fila se auto-contradecía."""
        self._vender_sin_tc()
        row = self._venta()
        pnl_ars = 2000 * 10 - 10000          # 10.000 ARS de ganancia
        self.assertAlmostEqual(float(row["pnl_usd"]) * float(row["fx_to_usd"]),
                               pnl_ars, places=1)
        self.assertAlmostEqual(float(row["pnl_usd"]),
                               pnl_ars / self.TC_DE_LA_FECHA, places=2)

    def test_el_mensual_del_broker_queda_en_dolares(self):
        """`monthly_entries.pnl_realized` vive en USD. Con `tc_v = 1` entraba el
        nominal en PESOS, y de ahí a capital_final."""
        self._vender_sin_tc()
        conn = main.get_db()
        row = conn.execute(
            "SELECT pnl_realized FROM monthly_entries "
            "WHERE user_id=? AND broker=? AND year=2024 AND month=3",
            (self.uid, self.BROKER)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(float(row["pnl_realized"]),
                               10000 / self.TC_DE_LA_FECHA, places=2)

    def test_si_el_usuario_manda_el_tc_gana_el_suyo(self):
        """El fix no le quita el control al usuario: si completa el campo, se
        sella lo que escribió."""
        r = self.client.post("/api/positions/sell", headers=self.hdr,
                             json={"broker": self.BROKER, "asset": "GGAL",
                                   "quantity": 10, "exit_price": 2000,
                                   "date": self.FECHA, "tc_venta": 1200.0})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(float(self._venta()["fx_to_usd"]), 1200.0, places=2)


if __name__ == "__main__":
    unittest.main()
