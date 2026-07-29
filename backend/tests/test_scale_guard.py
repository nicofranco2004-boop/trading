"""Guard de escala en el MOTOR (persister + rebuild): el bug per-100 no se replaya.

El normalizer ya reconcilia el triángulo al PARSEAR (test_normalizer_triangle.py),
pero el rebuild replaya `import_normalized_tx` YA GUARDADO — y en prod hay 1.526
ventas de 25 usuarios con el precio en escala per-100/×1000 almacenado así. Sin el
guard en el motor, cada rebuild (re-import, foto de tenencia, backfill) re-imprime
la corrupción; con él, el rebuild ES la reparación.

Habilitado por la medición de prod (2026-07-28, /api/admin/diagnose-scale sobre
129.607 filas): el cluster per-100 tiene p50 = 100,000 EXACTO ⇒ `gross_amount` es
BRUTO ⇒ derivar `precio = monto/cantidad` no absorbe ninguna comisión.
"""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False); TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from importing import persister as ps
from importing import rebuild as rb
from importing.schema import NormalizedTx
import main


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


class ReconciledUnitPriceTest(unittest.TestCase):
    """La función pura, con los números del fixture real de Balanz."""

    def test_per_100(self):
        # GD30: 1000 nominales, precio 66,04, monto 660,4 → per-1
        self.assertAlmostEqual(ps.reconciled_unit_price(66.04, 1000, 660.4), 0.6604, places=6)

    def test_vcp_1000(self):
        self.assertAlmostEqual(ps.reconciled_unit_price(2290, 1000, 2290), 2.29, places=6)

    def test_inverso(self):
        self.assertAlmostEqual(ps.reconciled_unit_price(0.5, 10, 500), 50.0, places=6)

    def test_comision_embebida_intacta(self):
        self.assertEqual(ps.reconciled_unit_price(10.30, 100, 1000), 10.30)   # ratio 1,03

    def test_triangulo_exacto_intacto(self):
        self.assertEqual(ps.reconciled_unit_price(150, 10, 1500), 150)

    def test_gap_4x_intacto(self):
        self.assertEqual(ps.reconciled_unit_price(40, 10, 100), 40)           # frontera <5×

    def test_sin_monto_intacto(self):
        self.assertEqual(ps.reconciled_unit_price(66.04, 1000, None), 66.04)
        self.assertEqual(ps.reconciled_unit_price(66.04, 1000, 0), 66.04)

    def test_transfer_out_precio_cero_intacto(self):
        self.assertEqual(ps.reconciled_unit_price(0, 1000, 660.4), 0)


class _Db(unittest.TestCase):
    BROKER = "IEB"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("scale_guard@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "USDT"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _batch(self, bid):
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,'confirmed')", (bid, self.uid, self.BROKER, "ieb", bid))

    def _raw(self, bid):
        return self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) VALUES (?,?,?,?)",
            (bid, 0, "{}", "valid")).lastrowid

    def _ventas(self, asset):
        return self.conn.execute(
            "SELECT pnl_usd, exit_price, entry_price, quantity FROM operations "
            "WHERE user_id=? AND asset=? AND op_type='Venta' ORDER BY id",
            (self.uid, asset)).fetchall()


class PersisterScaleGuardTest(_Db):
    """El persister no puede inflar ×100 aunque la tx llegue con el precio per-100
    (una tx construida a mano simula lo que el normalizer viejo dejaba pasar)."""

    def _persist(self, txs, bid="b-p"):
        self._batch(bid)
        raw_ids = {t.row_index: self._raw(bid) for t in txs}
        with self.conn:
            ps.persist_batch(self.conn, uid=self.uid, batch_id=bid, txs=txs,
                             raw_row_ids_by_index=raw_ids, helpers=_helpers())

    def test_venta_per100_pnl_sano(self):
        # Compra sana (monto real) + venta con precio per-100 y monto real.
        self._persist([
            NormalizedTx(row_index=1, date="2026-01-10", broker=self.BROKER,
                         operation_type="BUY", asset_symbol="GD30", quantity=1000,
                         unit_price=0.6604, gross_amount=660.4, currency="USD"),
            NormalizedTx(row_index=2, date="2026-02-10", broker=self.BROKER,
                         operation_type="SELL", asset_symbol="GD30", quantity=1000,
                         unit_price=70.0, gross_amount=700.0, currency="USD"),
        ])
        v = self._ventas("GD30")
        self.assertEqual(len(v), 1)
        # SIN guard: pnl = 70×1000 − 660,4 = 69.339,60. CON guard: 700 − 660,4 = 39,60.
        self.assertAlmostEqual(v[0]["pnl_usd"], 39.60, delta=0.01)
        self.assertAlmostEqual(v[0]["exit_price"], 0.70, places=6)

    def test_oversell_per100_seed_al_precio_reconciliado(self):
        # Venta sin compra previa (history-as-truth): el seed nacía al precio
        # per-100 → costo inflado ×100 en positions. Ahora nace reconciliado.
        self._persist([
            NormalizedTx(row_index=1, date="2026-02-10", broker=self.BROKER,
                         operation_type="SELL", asset_symbol="AL29", quantity=1000,
                         unit_price=70.0, gross_amount=700.0, currency="USD"),
        ])
        v = self._ventas("AL29")
        self.assertEqual(len(v), 1)
        self.assertAlmostEqual(v[0]["pnl_usd"], 0.0, delta=0.01)      # seed: P&L 0
        self.assertAlmostEqual(v[0]["entry_price"], 0.70, places=6)   # NO 70

    def test_trade_sano_byte_identico(self):
        self._persist([
            NormalizedTx(row_index=1, date="2026-01-10", broker=self.BROKER,
                         operation_type="BUY", asset_symbol="AAPL", quantity=10,
                         unit_price=150.0, gross_amount=1500.0, currency="USD"),
            NormalizedTx(row_index=2, date="2026-02-10", broker=self.BROKER,
                         operation_type="SELL", asset_symbol="AAPL", quantity=10,
                         unit_price=180.0, gross_amount=1800.0, currency="USD"),
        ])
        v = self._ventas("AAPL")
        self.assertAlmostEqual(v[0]["pnl_usd"], 300.0, delta=0.01)
        self.assertAlmostEqual(v[0]["exit_price"], 180.0, places=6)


class RebuildSelfHealTest(_Db):
    """LA prueba que convierte al rebuild en la reparación: tx guardadas con el
    precio per-100 (como las 1.526 de prod) → el rebuild produce P&L sano."""

    def _stored_tx(self, bid, *, op, asset, qty, price, monto, fecha):
        rr = self._raw(bid)
        self.conn.execute(
            "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
            "operation_type,asset_symbol,quantity,unit_price,gross_amount,currency) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (bid, rr, fecha, self.BROKER, op, asset, qty, price, monto, "USD"))

    def test_replay_de_tx_per100_guardada_se_autosanea(self):
        bid = "b-heal"
        self._batch(bid)
        # Lo que hay en prod: compra con monto real, venta con precio per-100.
        self._stored_tx(bid, op="BUY", asset="GD30", qty=1000,
                        price=66.04, monto=660.4, fecha="2026-01-10")   # ¡compra per-100 tb!
        self._stored_tx(bid, op="SELL", asset="GD30", qty=1000,
                        price=70.0, monto=700.0, fecha="2026-02-10")
        self.conn.commit()

        with self.conn:
            rb.rebuild_fifo_after_import(self.conn, self.uid, bid, tc_blue=1450.0)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)

        v = self._ventas("GD30")
        self.assertEqual(len(v), 1)
        # costo = monto de la compra (660,4); proceeds = monto de la venta (700).
        self.assertAlmostEqual(v[0]["pnl_usd"], 39.60, delta=0.05)
        # y el pnl_realized global queda sano, no 69.339
        pr = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["p"]
        self.assertAlmostEqual(pr, 39.60, delta=0.05)

    def test_replay_sano_no_cambia(self):
        bid = "b-ok"
        self._batch(bid)
        self._stored_tx(bid, op="BUY", asset="AAPL", qty=10,
                        price=150.0, monto=1500.0, fecha="2026-01-10")
        self._stored_tx(bid, op="SELL", asset="AAPL", qty=10,
                        price=180.0, monto=1800.0, fecha="2026-02-10")
        self.conn.commit()
        with self.conn:
            rb.rebuild_fifo_after_import(self.conn, self.uid, bid, tc_blue=1450.0)
        v = self._ventas("AAPL")
        self.assertAlmostEqual(v[0]["pnl_usd"], 300.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
