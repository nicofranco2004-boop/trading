"""E2E: el importador de CSV guarda tc_compra en las compras (para la vista
'costo al dólar de la compra'). Reproduce el reporte del usuario BMB: el CSV
tiene columna 'tc' pero no llegaba a positions.tc_compra.

Recorre el flujo REAL: run_preview → load_session_for_confirm (rehidratación
desde import_normalized_tx) → persist_batch → rebuild. El punto crítico es que
tc_compra sobreviva la rehidratación Y el rebuild.
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

from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
import main

HEADER = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    h._recalc_pnl_realized_from_ops = main._recalc_pnl_realized_from_ops
    return h


class ImportTcCompraE2E(unittest.TestCase):
    BROKER = "BMB"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("tccompra@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        self.conn.execute("INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
                          (self.uid, "tc_blue", "1500"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes):
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    def _tc(self, asset):
        r = self.conn.execute(
            "SELECT tc_compra FROM positions WHERE user_id=? AND asset=? AND is_cash=0 "
            "ORDER BY id LIMIT 1", (self.uid, asset)).fetchone()
        return r["tc_compra"] if r else None

    def test_tc_column_stored_and_survives_rebuild(self):
        # el caso literal de BMB: compra de AMZN con tc 1248.59 en el CSV
        csv = (HEADER +
               "5/3/2025,COMPRA NORMAL,BMB,AMZN,144,1755,252720,202.40,1248.59,0,ARS,\n"
               ).encode("utf-8")
        self._import(csv)
        tc = self._tc("AMZN")
        self.assertIsNotNone(tc, "tc_compra debería estar seteado")
        self.assertAlmostEqual(tc, 1248.59, places=2)

    def test_tc_derived_from_monto_usd_when_no_tc_column(self):
        # sin columna tc pero con monto + monto_usd → tc = monto/monto_usd
        csv = (HEADER +
               "5/3/2025,COMPRA NORMAL,BMB,GGAL,10,5000,50000,40,,0,ARS,\n"
               ).encode("utf-8")
        self._import(csv)
        tc = self._tc("GGAL")
        self.assertIsNotNone(tc)
        self.assertAlmostEqual(tc, 50000 / 40, places=2)  # 1250

    def test_usd_lot_no_spurious_tc(self):
        # lote en USD (moneda USD) → NO derivar un tc espurio
        csv = (HEADER +
               "5/3/2025,COMPRA NORMAL,BMB,AAPL,10,200,2000,2000,,0,USD,\n"
               ).encode("utf-8")
        self._import(csv)
        self.assertIsNone(self._tc("AAPL"))


if __name__ == "__main__":
    unittest.main()
