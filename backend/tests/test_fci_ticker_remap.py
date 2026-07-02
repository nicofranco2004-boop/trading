"""Remap retroactivo de tickers crudos de FCI (main._remap_fci_broker_tickers).

Cuando un FCI se agrega a fci_map DESPUÉS de que el usuario ya importó, la posición
quedó con el ticker crudo (ej CONIOLA) → al costo. Este remap lo lleva al símbolo de
catálogo (FCI:<slug>) en positions/operations/tx para que tome precio sin re-importar.
Verifica: remapea el crudo, no toca otras posiciones, es idempotente."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main


class FciTickerRemapTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("users", "positions", "operations", "import_batches", "import_raw_rows", "import_normalized_tx"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES ('t','x',1)").lastrowid
        self.conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,is_cash) VALUES (?,?,?,?,0)",
                          (self.uid, "IOL", "CONIOLA", 10))
        self.conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,is_cash) VALUES (?,?,?,?,0)",
                          (self.uid, "IOL", "AAPL", 5))  # sana, NO se toca
        self.conn.execute("INSERT INTO operations (user_id,date,broker,asset) VALUES (?,?,?,?)",
                          (self.uid, "2025-01-01", "IOL", "CONIOLA"))
        self.conn.execute("INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
                          "VALUES ('b',?,'IOL','g','h','confirmed')", (self.uid,))
        rr = self.conn.execute("INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                               "VALUES ('b',0,'{}','valid')").lastrowid
        self.conn.execute("INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,operation_type,asset_symbol) "
                          "VALUES ('b',?,'2025-01-01','IOL','BUY','CONIOLA')", (rr,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_remapea_coniola_a_catalogo_y_es_idempotente(self):
        n = main._remap_fci_broker_tickers(self.conn)
        self.conn.commit()
        self.assertGreaterEqual(n, 3)   # positions + operations + tx
        assets = {r["asset"] for r in self.conn.execute(
            "SELECT asset FROM positions WHERE user_id=?", (self.uid,))}
        self.assertIn("FCI:ADCAP-ACCIONES-A", assets)   # remapeado
        self.assertIn("AAPL", assets)                    # sana intacta
        self.assertNotIn("CONIOLA", assets)              # el crudo ya no está
        self.assertEqual(self.conn.execute(
            "SELECT asset FROM operations WHERE user_id=?", (self.uid,)).fetchone()["asset"],
            "FCI:ADCAP-ACCIONES-A")
        self.assertEqual(self.conn.execute(
            "SELECT asset_symbol FROM import_normalized_tx WHERE batch_id='b'").fetchone()["asset_symbol"],
            "FCI:ADCAP-ACCIONES-A")
        # idempotente: 2da corrida no toca nada (guard: ya no hay ticker crudo)
        self.assertEqual(main._remap_fci_broker_tickers(self.conn), 0)


if __name__ == "__main__":
    unittest.main()
