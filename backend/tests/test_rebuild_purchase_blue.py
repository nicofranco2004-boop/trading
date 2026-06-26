"""Fix #2: rebuild debe valuar el costo de un lote ARS vendido en USD (dólar-MEP)
al blue de la FECHA DE COMPRA (blue_for_date), igual que el persister — NO al blue
de hoy. Sin esto la P&L realizada se inflaba con la devaluación y divergía entre
persister y rebuild según cuándo corría el rebuild (rebuild pisaba al final)."""
import unittest

import main
from importing import rebuild as rb
from importing.schema import OP_BUY, OP_SELL


def _ev(op, qty, price, gross, currency, date, raw=1):
    return {
        "operation_type": op, "quantity": qty, "unit_price": price,
        "gross_amount": gross, "fees": 0, "currency": currency, "date": date,
        "batch_id": "b", "raw_row_id": raw, "broker": "IEB", "asset_symbol": "AL30",
    }


class RebuildPurchaseBlueTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.conn.execute("DELETE FROM fx_rates_daily")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _events(self):
        return [
            _ev(OP_BUY, 100, 1000, 100000, "ARS", "2022-01-10", raw=1),  # 100k ARS
            _ev(OP_SELL, 100, 3, 300, "USD", "2023-01-10", raw=2),        # 100 @ 3 USD = 300 USD
        ]

    def test_uses_purchase_date_blue(self):
        # Blue de la compra = 500 (tc_blue de hoy = 1415).
        # Costo USD = 100.000 / 500 = 200 → pnl = 300 − 200 = +100.
        self.conn.execute("INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta) VALUES ('2022-01-10', 500)")
        self.conn.commit()
        out = rb._replay_asset(self._events(), "ARS", 1415.0, conn=self.conn)
        self.assertEqual(len(out["operations"]), 1)
        self.assertAlmostEqual(out["operations"][0]["pnl_usd"], 100.0, places=1)

    def test_fallback_without_conn_uses_today_blue(self):
        # Sin conn → tc_blue de hoy (back-compat). Costo = 100.000/1415 = 70,67
        # → pnl = 300 − 70,67 = 229,33 (el comportamiento viejo, inflado).
        out = rb._replay_asset(self._events(), "ARS", 1415.0, conn=None)
        self.assertAlmostEqual(out["operations"][0]["pnl_usd"], 229.33, places=1)


if __name__ == "__main__":
    unittest.main()
