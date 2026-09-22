"""Anti-duplicación por CONTEO, no por conjunto (reporte de un asesor, Cocos, 2026-09-20).

El caso: una orden ejecutada en 4 partes iguales (misma fecha, ticker, cantidad y
precio) son 4 filas con la MISMA huella. Dentro de un archivo se respetan las 4.
Pero si un intento anterior dejó 1 de las 4 confirmada, el re-intento preguntaba
"¿existe esta huella?" con sí/no y omitía LAS CUATRO: cada reintento comía
operaciones reales. Lo correcto es omitir SOLO las que ya están (1) y dejar
entrar las que faltan (3).

Corre con: cd backend && python3 -m pytest tests/test_reimport_dedup_multiplicidad.py
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

HDR = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;"
       "moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total\n")
DEP = "85601659;4608176;05-01-2026;05-01-2026;Recibo De Cobro;;ARS;;;;10.000.000;0;0;0;0;10.000.000\n"


def _fill(ticket, comprobante):
    # 4 ejecuciones parciales: mismo día, mismo ticker, misma cantidad, mismo precio.
    return (f"{ticket};{comprobante};06-01-2026;07-01-2026;Compra;CEDEAR TESLA, INC. (TSLA);"
            f"ARS;BYMA;10;44.760;-447.600;-2.014,2;-223,8;-469,98;0;-450.307,98\n")


CSV_1_DE_4 = (HDR + DEP + _fill(80067296, 151771)).encode("utf-8")
CSV_4_DE_4 = (HDR + DEP + _fill(80067296, 151771) + _fill(80067297, 151772)
              + _fill(80067298, 151773) + _fill(80067299, 151774)).encode("utf-8")


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


class DedupPorConteo(unittest.TestCase):
    BROKER = "Cocos"

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
            ("dedup_conteo@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes, file_name):
        """Espeja /imports/confirm (mismo camino que el test_reimport_dedup)."""
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name=file_name,
                broker_hint=self.BROKER, parser_format="cocos")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            skip = pl.already_imported_row_indices(self.conn, self.uid, sid, txs)
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
        return payload, len(skip)

    def _held(self, asset):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def test_cuatro_ejecuciones_iguales_entran_las_cuatro(self):
        self._import(CSV_4_DE_4, "mov_a.csv")
        self.assertEqual(self._held("TSLA"), 40.0)

    def test_el_reintento_completa_las_que_faltan_y_no_las_borra(self):
        # Intento 1: sólo entró 1 de las 4 (archivo parcial / corte a mitad).
        self._import(CSV_1_DE_4, "mov_parcial.csv")
        self.assertEqual(self._held("TSLA"), 10.0)
        # Intento 2: el export completo. Deben omitirse SOLO la que ya estaba (y el depósito).
        _, skipped = self._import(CSV_4_DE_4, "mov_completo.csv")
        self.assertEqual(skipped, 2, "1 compra ya estaba + 1 depósito ya estaba")
        self.assertEqual(self._held("TSLA"), 40.0, "las 3 compras que faltaban tienen que entrar")

    def test_el_preview_marca_por_conteo(self):
        self._import(CSV_1_DE_4, "mov_parcial.csv")
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=CSV_4_DE_4, file_name="mov_completo.csv",
                broker_hint=self.BROKER, parser_format="cocos")
        self.assertEqual(len(payload["duplicate_row_indices"]), 2,
                         "la previsualización tiene que anticipar lo mismo que hace el confirm")

    def test_mismo_archivo_dos_veces_sigue_siendo_noop(self):
        self._import(CSV_4_DE_4, "mov_a.csv")
        _, skipped = self._import(CSV_4_DE_4, "mov_a_de_nuevo.csv")
        self.assertEqual(skipped, 5)
        self.assertEqual(self._held("TSLA"), 40.0)


if __name__ == "__main__":
    unittest.main()
