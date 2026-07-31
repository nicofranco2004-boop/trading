"""El PUT de una posición no puede DESTRUIR el tc_compra que ya estaba.

Bug real: `UPDATE positions SET ... tc_compra=?` pisaba el valor con lo que
mandara el cliente. El campo del formulario es un <input type="number"> y, según
el browser, tipear "1448,6" (coma decimal es-AR) llega como null → editar
cualquier otro campo de la posición borraba en silencio un TC correcto, y con él
la vista "Costo en dólares → dólar de la compra".
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


class PutTcCompraTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("positions", "brokers", "users", "fx_rates_daily"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("puttc@test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "Balanz", "ARS"))
        self.conn.execute(
            "INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?,?,?,?)", ("2026-03-03", 1440.0, 1448.6, "test"))
        self.pid = self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
               invested, tc_compra, entry_date, commissions, currency, asset_type)
               VALUES (?,?,?,0,?,?,?,?,?,?,?,?)""",
            (self.uid, "Balanz", "MELI", 21530, 10, 216732.82, 1448.6,
             "2026-03-03", 1432.83, "ARS", "CEDEAR")).lastrowid
        self.conn.commit()
        self.conn.close()

    def _tc(self):
        c = main.get_db()
        try:
            r = c.execute("SELECT tc_compra FROM positions WHERE id=?", (self.pid,)).fetchone()
            return r["tc_compra"] if r else None
        finally:
            c.close()

    def _put(self, **over):
        campos = dict(broker="Balanz", asset="MELI", is_cash=False, buy_price=21530,
                      quantity=10, invested=216732.82, tc_compra=None, price_override=None,
                      notes=None, commissions=1432.83, entry_date="2026-03-03",
                      asset_type="CEDEAR", currency="ARS")
        campos.update(over)
        return main.update_position(self.pid, main.PositionIn(**campos), uid=self.uid)

    def test_un_null_no_borra_el_tc_existente(self):
        self._put(quantity=12)              # editar OTRO campo, sin mandar TC
        self.assertAlmostEqual(self._tc(), 1448.6, places=2)

    def test_se_puede_actualizar_el_tc_con_un_valor_nuevo(self):
        self._put(tc_compra=1500.0)
        self.assertAlmostEqual(self._tc(), 1500.0, places=2)

    def test_lote_en_pesos_sin_tc_lo_completa_con_el_historico(self):
        c = main.get_db()
        c.execute("UPDATE positions SET tc_compra=NULL WHERE id=?", (self.pid,))
        c.commit()
        c.close()
        self._put(quantity=10)
        self.assertAlmostEqual(self._tc(), 1448.6, places=2)   # el MEP de la fecha


if __name__ == "__main__":
    unittest.main()
