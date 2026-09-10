"""Transferencia Externa de Balanz: el título que SALE tiene que salir.

Reporte de un usuario (2026-09-09): Rendi le mostraba USD 71.634 de cartera
contra los u$s 51.735 que mostraba Balanz. El 18/2/2026 había transferido SEIS
tenencias a otro broker (TO26, YPFD, UNH, PBR, GLOB, GOOGL); el export las trae
como "Transferencia Externa (Débito)" con la CANTIDAD EN NEGATIVO e Importe 0.

El parser tomaba `abs(qty)` y emitía siempre COMPRA — solo se había visto la
transferencia que ENTRA — así que cada salida SUMABA en vez de restar: la
tenencia quedaba al DOBLE y encima se creaba un DEPOSITO de capital que nunca
existió. Las seis explicaban ≈ USD 20.300 de los ≈ USD 19.900 de diferencia.

El test corre el PIPELINE COMPLETO (preview → confirm → persist → rebuild), no
el parser suelto, por dos motivos:

  • El confirm RELEE las filas desde `import_normalized_tx`. La marca
    `transfer_out` —la que hace que el lote cierre A COSTO, con P&L 0, en vez de
    bookear el costo entero como pérdida— viajaba en el objeto pero NO se
    escribía en ese INSERT, así que moría en el round-trip. Un test contra el
    parser da verde igual y no ve nada.
  • Ese agujero afectaba también a IEB (código RETR), PPI ("Retiro de Títulos")
    y Binance (retiro a wallet), que emiten la misma marca por el mismo camino.

Corre con: cd backend && python3 -m pytest tests/test_balanz_transferencia_externa.py
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
from importing.parsers.balanz_movimientos import BalanzMovimientosParser
import main


HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
       "Liquidacion,Moneda,Importe,_hoja\n")

# Compra 100 GLOB a 10.000 y en junio los transfiere a otro broker, ya valiendo
# 40.000 (×4). Si la salida se leyera como compra quedarían 200; si se cerrara
# como venta a precio 0 sin la marca, aparecería una pérdida de 1.000.000.
CSV = (HDR +
    "Recibo de Cobro / 1,,,2025-01-02,0,-1,2025-01-02,Pesos,2000000,mov\n"
    "Boleto / 100 / COMPRA ,GLOB,Cedears,2025-01-10,100,10000,2025-01-10,Pesos,-1000000,mov\n"
    "Transferencia Externa (Débito) / 1/6/2026,GLOB,Cedears,2026-06-01,-100,40000,2026-06-01,,0,mov\n"
).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


class TransferenciaExternaE2E(unittest.TestCase):
    BROKER = "Balanz"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("balanz_transfer@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=CSV, file_name="movimientos.csv",
                broker_hint=self.BROKER, parser_format="balanz_movimientos")
        self.sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(
                self.conn, uid=self.uid, session_id=self.sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=self.sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(
                self.conn, self.uid, self.sid,
                tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))

    def tearDown(self):
        self.conn.close()

    def test_el_titulo_que_sale_no_queda_en_la_cartera(self):
        q = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions "
            "WHERE user_id=? AND asset='GLOB' AND is_cash=0", (self.uid,)).fetchone()["q"]
        self.assertEqual(float(q), 0.0,
                         "el título transferido a otro broker sigue en la cartera")

    def test_no_inventa_capital_aportado(self):
        # El único depósito real son los 2.000.000 del "Recibo de Cobro".
        dep = self.conn.execute(
            "SELECT COALESCE(SUM(gross_amount),0) s FROM import_normalized_tx "
            "WHERE batch_id=? AND operation_type='DEPOSIT'", (self.sid,)).fetchone()["s"]
        self.assertAlmostEqual(float(dep), 2000000.0, places=2)

    def test_la_marca_transfer_out_sobrevive_el_viaje_a_la_base(self):
        # El confirm relee de esta tabla: si la marca no se guarda acá, muere.
        r = self.conn.execute(
            "SELECT transfer_out FROM import_normalized_tx "
            "WHERE batch_id=? AND operation_type='SELL' AND asset_symbol='GLOB'",
            (self.sid,)).fetchone()
        self.assertIsNotNone(r, "no se emitió la salida del título")
        self.assertEqual(int(r["transfer_out"]), 1,
                         "la marca se perdió en el INSERT → el persister va a "
                         "bookear el costo como pérdida fantasma")

    def test_mudarse_de_broker_no_es_ganancia_ni_perdida(self):
        pnl = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) s FROM operations "
            "WHERE user_id=? AND asset='GLOB'", (self.uid,)).fetchone()["s"]
        self.assertAlmostEqual(float(pnl), 0.0, places=6,
                               msg="el papel se mudó de broker, no se vendió")

    def test_la_caja_no_se_toca(self):
        # 2.000.000 de depósito − 1.000.000 de la compra. La transferencia no
        # mueve efectivo (Importe 0) y no debe acreditar ni debitar nada.
        cash = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) s FROM positions "
            "WHERE user_id=? AND is_cash=1", (self.uid,)).fetchone()["s"]
        self.assertAlmostEqual(float(cash), 1000000.0, places=2)


class DireccionPorElSigno(unittest.TestCase):
    """La dirección la da el signo de la CANTIDAD — el Importe siempre viene 0."""

    def _una(self, fila):
        res = BalanzMovimientosParser().parse(HDR.replace(",_hoja", "") + fila)
        return [r.data for r in res.raw_rows]

    def test_debito_saca_el_titulo(self):
        d = self._una("Transferencia Externa (Débito) / 1/6/2026,GLOB,Cedears,"
                      "2026-06-01,-100,40000,2026-06-01,,0\n")
        self.assertEqual([x["tipo"] for x in d], ["VENTA"])
        self.assertEqual(d[0]["cantidad"], "100.0")
        self.assertEqual(d[0]["_transfer_out"], "1")   # cierra a costo, P&L 0

    def test_credito_lo_mete_con_su_valor(self):
        d = self._una("Transferencia Externa (Crédito) / 1/6/2026,GLOB,Cedears,"
                      "2026-06-01,100,40000,2026-06-01,,0\n")
        self.assertEqual([x["tipo"] for x in d], ["COMPRA", "DEPOSITO"])
        # El cash NETEA a 0: la compra gasta lo mismo que el depósito acredita.
        self.assertEqual(d[0]["monto"], d[1]["monto"])

    def test_una_cantidad_microscopica_no_genera_un_deposito_de_cero(self):
        # Hallazgo de auditar el propio fix: el valor se redondea a 4 decimales,
        # así que una cuotaparte de FCI chiquísima daba monto 0 — y un DEPOSITO
        # de monto 0 lo rechaza el validador. Si no queda monto, no hay depósito.
        d = self._una("Transferencia Externa (Crédito) / 1/6/2026,BMM A,Fondos,"
                      "2026-06-01,0.00001,1,2026-06-01,,0\n")
        self.assertEqual([x["tipo"] for x in d], ["COMPRA"])

    def test_sin_precio_la_salida_igual_sale(self):
        d = self._una("Transferencia Externa (Débito) / 1/6/2026,GLOB,Cedears,"
                      "2026-06-01,-100,-1,2026-06-01,,0\n")
        self.assertEqual([x["tipo"] for x in d], ["VENTA"])
        self.assertEqual(d[0]["_transfer_out"], "1")


if __name__ == "__main__":
    unittest.main()
