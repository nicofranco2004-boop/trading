"""E2E: anti-duplicación al re-importar (pipeline + persister + rebuild).

Reproduce el caso del usuario: sube el historial, después sube un export
ACTUALIZADO que se SOLAPA con lo anterior. El confirm debe omitir SOLO las filas
ya importadas (mismo fingerprint) e importar las nuevas — sin duplicar y sin
borrar el historial previo. Espeja la lógica del endpoint /imports/confirm.

Corre con: cd backend && python3 -m pytest tests/test_reimport_dedup.py
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

BM_HEADER = "Liquida,Operado,Comprobante,Numero,Cantidad,Especie,Precio,Importe,Saldo,Referencia\n"

# Historial inicial: depósito + 2 compras.
CSV_HIST = (BM_HEADER +
    "2024-03-12,2024-03-10,RECIBO DE COBRO,1001,0,,0,500000,500000,CREDITO CTA. CTE.\n"
    "2024-03-16,2024-03-15,COMPRA NORMAL,1002,10,YPF,20000,-200000,300000,\n"
    "2024-06-21,2024-06-20,COMPRA NORMAL,1003,20,GGAL,5000,-100000,200000,\n"
).encode("utf-8")

# Export ACTUALIZADO: las MISMAS 3 filas (se solapan) + 1 compra NUEVA.
CSV_UPDATE = (BM_HEADER +
    "2024-03-12,2024-03-10,RECIBO DE COBRO,1001,0,,0,500000,500000,CREDITO CTA. CTE.\n"
    "2024-03-16,2024-03-15,COMPRA NORMAL,1002,10,YPF,20000,-200000,300000,\n"
    "2024-06-21,2024-06-20,COMPRA NORMAL,1003,20,GGAL,5000,-100000,200000,\n"
    "2025-08-02,2025-08-01,COMPRA NORMAL,2003,5,YPF,30000,-150000,50000,\n"
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


class ReimportDedupE2E(unittest.TestCase):
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
            ("dedup_e2e@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes, *, dedup=True):
        """Espeja /imports/confirm: preview → load → dedup → skip → persist → rebuild."""
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="bullmarket")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            skip = set()
            if dedup:
                skip |= pl.already_imported_row_indices(self.conn, self.uid, sid, txs, already_skipped=skip)
            if skip:
                txs = [t for t in txs if t.row_index not in skip]
                ph = ",".join("?" * len(skip))
                self.conn.execute(
                    f"""DELETE FROM import_normalized_tx WHERE batch_id=? AND raw_row_id IN (
                          SELECT id FROM import_raw_rows WHERE batch_id=? AND row_index IN ({ph}))""",
                    (sid, sid, *skip))
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid, len(skip)

    def _held(self, asset):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def test_reimport_overlap_solo_agrega_lo_nuevo(self):
        # 1) Historial: YPFD 10, GGAL 20.
        self._import(CSV_HIST)
        self.assertEqual(self._held("YPFD"), 10.0)
        self.assertEqual(self._held("GGAL"), 20.0)
        # 2) Export actualizado (3 viejas solapadas + 1 nueva) con dedup.
        _, skipped = self._import(CSV_UPDATE)
        self.assertEqual(skipped, 3)               # las 3 ya importadas se omiten
        self.assertEqual(self._held("YPFD"), 15.0)  # 10 + 5 nueva (NO 25 duplicado)
        self.assertEqual(self._held("GGAL"), 20.0)  # sin duplicar (NO 40)

    def test_reimport_mismo_archivo_es_noop(self):
        self._import(CSV_HIST)
        _, skipped = self._import(CSV_HIST)         # mismo archivo de nuevo
        self.assertEqual(skipped, 3)                # todo es duplicado
        self.assertEqual(self._held("YPFD"), 10.0)  # sin cambios
        self.assertEqual(self._held("GGAL"), 20.0)

    def test_include_duplicates_apila_a_proposito(self):
        # Sin dedup (include_duplicates=true) el comportamiento viejo: apila.
        self._import(CSV_HIST)
        _, skipped = self._import(CSV_HIST, dedup=False)
        self.assertEqual(skipped, 0)
        self.assertEqual(self._held("YPFD"), 20.0)  # 10 + 10 (duplicado a propósito)


if __name__ == "__main__":
    unittest.main()
