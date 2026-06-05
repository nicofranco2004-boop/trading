"""E2E: parser REAL de Bull Market + pipeline + rebuild FIFO, fuera de orden.

Valida exactamente los 2 CSVs sintéticos que se le entregan al usuario para
probar (uno con fechas 2024, otro 2025). Sube el de 2025 PRIMERO (ventas sin sus
compras → estado corrupto), después el de 2024 (las compras) y verifica que el
rebuild reconstruye el FIFO correcto.

Corre con: cd backend && python3 -m pytest tests/test_rebuild_bullmarket_e2e.py
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


# ─── Contenido EXACTO de los CSVs que se entregan (formato Bull Market) ──────
BM_HEADER = "Liquida,Operado,Comprobante,Numero,Cantidad,Especie,Precio,Importe,Saldo,Referencia\n"

CSV_2024 = (BM_HEADER +
    "2024-03-12,2024-03-10,RECIBO DE COBRO,1001,0,,0,500000,500000,CREDITO CTA. CTE.\n"
    "2024-03-16,2024-03-15,COMPRA NORMAL,1002,10,YPF,20000,-200000,300000,\n"
    "2024-06-21,2024-06-20,COMPRA NORMAL,1003,20,GGAL,5000,-100000,200000,\n"
).encode("utf-8")

CSV_2025 = (BM_HEADER +
    "2025-02-11,2025-02-10,VENTA,2001,-10,YPF,28000,280000,480000,\n"
    "2025-05-16,2025-05-15,VENTA,2002,-20,GGAL,7000,140000,620000,\n"
    "2025-08-02,2025-08-01,COMPRA NORMAL,2003,5,YPF,30000,-150000,470000,\n"
    "2025-09-11,2025-09-10,ORDEN DE PAGO,2004,0,,0,-100000,370000,TRANSFERENCIA VIA MEP\n"
).encode("utf-8")


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


class BullMarketOutOfOrderE2E(unittest.TestCase):
    BROKER = "Bull Market"

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
            ("bm_e2e@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", "1000"))   # 1 USD = 1000 ARS → math redonda
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes, *, rebuild):
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="bm.csv",
                broker_hint=self.BROKER, parser_format="bullmarket")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            if rebuild:
                tc = ps._read_tc_blue(self.conn, uid=self.uid)
                rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
                main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    def _held(self, asset):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def _gpnl(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,)).fetchone()
        return float(r["p"] or 0)

    def test_upload_2025_then_2024_heals(self):
        # 1) Sube 2025 PRIMERO (fuera de orden) → ventas sin sus compras.
        self._import(CSV_2025, rebuild=False)
        # 2) Sube 2024 (las compras) SIN rebuild → estado corrupto: la compra de
        #    2024 (10 YPF) entra como lote abierto fantasma → YPFD = 10 + 5 = 15.
        self._import(CSV_2024, rebuild=False)
        self.assertAlmostEqual(self._held("YPFD"), 15.0, places=6)   # corrupto
        # 3) Disparar el rebuild (como lo haría el confirm en producción).
        with self.conn:
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(
                self.conn, self.uid,
                self.conn.execute(
                    "SELECT id FROM import_batches WHERE user_id=? ORDER BY confirmed_at DESC LIMIT 1",
                    (self.uid,)).fetchone()["id"],
                tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)

        # SANO:
        #  YPFD: compra 10@20000 (2024) consumida por venta 10@28000 (2025) →
        #        pnl 80000 ARS; queda la compra 5@30000 (2025-08) abierta → 5 held.
        #  GGAL: compra 20@5000 consumida por venta 20@7000 → pnl 40000 ARS; 0 held.
        self.assertAlmostEqual(self._held("YPFD"), 5.0, places=6)
        self.assertAlmostEqual(self._held("GGAL"), 0.0, places=6)
        # pnl total ARS = 120000 / tc_blue 1000 = 120 USD
        self.assertAlmostEqual(self._gpnl(), 120.0, places=2)

        # Ticker mapeado: YPF → YPFD (no debe quedar "YPF" suelto)
        self.assertAlmostEqual(self._held("YPF"), 0.0, places=6)

    def test_parser_reads_both_files(self):
        # sanity: el parser real de Bull Market lee ambos sin errores
        from importing.parsers.bullmarket import BullMarketParser
        p = BullMarketParser()
        r24 = p.parse(CSV_2024.decode("utf-8"))
        r25 = p.parse(CSV_2025.decode("utf-8"))
        self.assertEqual(len(r24.parse_errors), 0)
        self.assertEqual(len(r25.parse_errors), 0)
        # 2024: 1 depósito + 2 compras = 3 filas
        self.assertEqual(len(r24.raw_rows), 3)
        # 2025: 2 ventas + 1 compra + 1 retiro = 4 filas
        self.assertEqual(len(r25.raw_rows), 4)


if __name__ == "__main__":
    unittest.main()
