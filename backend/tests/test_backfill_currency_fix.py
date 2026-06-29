"""Backfill de corrección de moneda (scripts/backfill_currency_fix.py).

Verifica que `correct_currency` dispara las 3 correcciones SOLO en las filas
envenenadas y NO toca las legítimas (FCI USD real, bono USD suelto), y que es
idempotente. Las pruebas E2E (recupera el estado correcto al centavo + recompute)
están verificadas con archivos reales vía sim_import; acá fijamos la detección."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
from scripts.backfill_currency_fix import correct_currency

BLUE = 1444.0


class CorrectCurrencyTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_normalized_tx", "import_raw_rows", "import_batches", "users"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)", ("bf@t", "x")).lastrowid
        self.bid = "b-bf"
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,?)", (self.bid, self.uid, "Balanz", "generic", "h", "confirmed"))
        self.rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) VALUES (?,?,?,?)",
            (self.bid, 0, "{}", "valid")).lastrowid

    def tearDown(self):
        self.conn.close()

    def _tx(self, **k):
        cols = ("batch_id", "raw_row_id", "date", "broker", "operation_type", "asset_symbol",
                "asset_type", "quantity", "unit_price", "gross_amount", "gross_amount_usd",
                "currency", "notes")
        vals = {"batch_id": self.bid, "raw_row_id": self.rr, "date": "2025-09-09",
                "broker": "Balanz", **k}
        ph = ",".join("?" * len(cols))
        return self.conn.execute(
            f"INSERT INTO import_normalized_tx ({','.join(cols)}) VALUES ({ph})",
            tuple(vals.get(c) for c in cols)).lastrowid

    def _ccy(self, tid):
        return self.conn.execute("SELECT currency, gross_amount_usd FROM import_normalized_tx WHERE id=?",
                                 (tid,)).fetchone()

    def test_corrige_fci_peso_pero_no_usd_real(self):
        fci_peso = self._tx(operation_type="BUY", asset_symbol="RFPESOSA", asset_type="FUND",
                            quantity=8000, unit_price=197.5, gross_amount=1580000, gross_amount_usd=1580000, currency="USD")
        fci_usd = self._tx(operation_type="BUY", asset_symbol="BAHUSD", asset_type="FUND",
                           quantity=740, unit_price=1.35, gross_amount=1000, gross_amount_usd=1000, currency="USD")
        self.conn.commit()
        c = correct_currency(self.conn, self.uid, BLUE)
        self.assertEqual(c["fci"], 1)
        self.assertEqual(self._ccy(fci_peso)["currency"], "ARS")            # peso VCP>5 → ARS
        self.assertAlmostEqual(self._ccy(fci_peso)["gross_amount_usd"], 1580000 / BLUE, places=1)
        self.assertEqual(self._ccy(fci_usd)["currency"], "USD")            # USD real (VCP 1.35) intacto

    def test_restampa_seed_sintetico_pesoescala(self):
        seed = self._tx(operation_type="WITHDRAW", gross_amount=43000000, gross_amount_usd=43000000,
                        currency="USDT", notes="Estado inicial — retiro sintético (Rendi)")
        self.conn.commit()
        c = correct_currency(self.conn, self.uid, BLUE)
        self.assertEqual(c["seed"], 1)
        self.assertAlmostEqual(self._ccy(seed)["gross_amount_usd"], 43000000 / BLUE, places=1)  # ÷blue
        self.assertEqual(self._ccy(seed)["currency"], "USDT")             # la moneda no cambia (pata dólar real)

    def test_corrige_conducto_buy_pero_no_bono_usd_suelto(self):
        # par conducto: BUY precio 1.083 + SELL precio 0.00075 (ratio ~1444) mismo ticker+qty
        buy = self._tx(operation_type="BUY", asset_symbol="DHS9O", asset_type="BOND",
                       quantity=874080, unit_price=1.083, gross_amount=946628, gross_amount_usd=946628, currency="USD")
        self._tx(operation_type="SELL", asset_symbol="DHS9O", asset_type="BOND",
                 quantity=874080, unit_price=0.00075, gross_amount=655, gross_amount_usd=655, currency="USD")
        # bono USD legítimo suelto (sin par, precio ~par USD) → NO tocar
        gd30 = self._tx(operation_type="BUY", asset_symbol="GD30", asset_type="BOND",
                        quantity=100, unit_price=0.72, gross_amount=72, gross_amount_usd=72, currency="USD")
        self.conn.commit()
        c = correct_currency(self.conn, self.uid, BLUE)
        self.assertEqual(c["conduit"], 1)
        self.assertEqual(self._ccy(buy)["currency"], "ARS")               # pata BUY del conducto → ARS
        self.assertEqual(self._ccy(gd30)["currency"], "USD")              # bono USD suelto intacto

    def test_idempotente(self):
        self._tx(operation_type="BUY", asset_symbol="RFPESOSA", asset_type="FUND",
                 quantity=8000, unit_price=197.5, gross_amount=1580000, gross_amount_usd=1580000, currency="USD")
        self.conn.commit()
        c1 = correct_currency(self.conn, self.uid, BLUE)
        c2 = correct_currency(self.conn, self.uid, BLUE)
        self.assertEqual(c1["fci"], 1)
        self.assertEqual(sum(c2.values()), 0)   # 2da corrida no toca nada


if __name__ == "__main__":
    unittest.main()
