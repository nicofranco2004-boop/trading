"""Regresión del bug ALTO (hallado en auditoría adversarial): las filas que el
usuario marca para SALTEAR en el preview (skip_row_indices) quedaban en
import_normalized_tx y el rebuild FIFO las RESUCITABA → holdings/P&L corruptos.

Testea el endpoint REAL import_confirm (no persist_batch directo) porque el bug
y su fix viven en el flujo del confirm.

Corre con: cd backend && python3 -m pytest tests/test_rebuild_skip_bug.py
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
import main


HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


class SkipRowNotResurrected(unittest.TestCase):
    BROKER = "IBKR"

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
            ("skip_test@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, "USDT"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _held(self, asset):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def test_skipped_buy_stays_skipped_after_rebuild(self):
        csv = (HDR +
            "2024-01-10,COMPRA,IBKR,AAPL,10,100,1000,,,0,USD,\n"   # fila 1
            "2024-02-10,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,\n"   # fila 2 ← SE SALTEA
            "2025-01-10,VENTA,IBKR,AAPL,5,200,1000,,,0,USD,\n"     # fila 3
        ).encode("utf-8")

        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic")
        sid = payload["session_id"]

        # Identificar el row_index de la compra de 150 (la que se saltea).
        skip_idx = self.conn.execute(
            """SELECT r.row_index FROM import_normalized_tx n
                 JOIN import_raw_rows r ON r.id = n.raw_row_id
                WHERE n.batch_id=? AND n.unit_price=150""",
            (sid,)).fetchone()["row_index"]

        # Confirmar SALTEANDO la fila 2 — vía el endpoint REAL (incluye rebuild).
        data = main.ImportConfirmIn(session_id=sid, skip_row_indices=[skip_idx])
        main.import_confirm(data, self.uid)

        # Esperado: solo se cargó compra 10@100 y venta 5 → 5 AAPL en cartera.
        # Bug (pre-fix): el rebuild resucitaba la compra salteada → 15.
        self.assertAlmostEqual(self._held("AAPL"), 5.0, places=6)

        # La fila salteada NO debe quedar en import_normalized_tx (log de aplicados).
        leftover = self.conn.execute(
            "SELECT COUNT(*) c FROM import_normalized_tx WHERE batch_id=? AND unit_price=150",
            (sid,)).fetchone()["c"]
        self.assertEqual(leftover, 0)


if __name__ == "__main__":
    unittest.main()
