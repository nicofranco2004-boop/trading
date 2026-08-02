"""Tests del BORRADO de operación con cascada TOTAL (main._delete_operation_cascade).

Verifica lo que el borrado viejo NO hacía: al borrar una venta importada, la op
desaparece de TODO cálculo (tenencia restaurada, P&L 0, cash revertido, snapshots
recomputados) y NO resucita al re-derivar. Undo la trae de vuelta.

Corre con: cd backend && python3 -m pytest tests/test_delete_operation_cascade.py
"""
import json
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

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows: str) -> bytes:
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


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


class DeleteCascade(unittest.TestCase):
    BROKER = "IBKR"
    BROKER_CCY = "USDT"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "deleted_ops_journal", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("del_cascade@rendi.test", "x"),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, self.BROKER_CCY),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    # ── infra ────────────────────────────────────────────────────────────────
    def _import(self, csv_bytes: bytes) -> str:
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic",
            )
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    def _open_qty(self, asset="AAPL"):
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset)).fetchone()["q"] or 0)

    def _ventas(self, asset="AAPL"):
        return self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND asset=? AND op_type='Venta'",
            (self.uid, asset)).fetchall()

    def _global_pnl(self):
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,)).fetchone()["p"] or 0)

    def _cash(self):
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) c FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, self.BROKER)).fetchone()["c"] or 0)

    def _sell_oid(self, asset="AAPL"):
        r = self.conn.execute(
            "SELECT id FROM operations WHERE user_id=? AND asset=? AND op_type='Venta' LIMIT 1",
            (self.uid, asset)).fetchone()
        return r["id"] if r else None

    def _probe(self):
        """Invariantes de consistencia — ninguna superficie cuenta de más."""
        op_pnl = float(self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) p FROM operations WHERE user_id=?",
            (self.uid,)).fetchone()["p"] or 0)
        self.assertAlmostEqual(op_pnl, self._global_pnl(), places=2,
                               msg="probe: SUM(operations.pnl) != SUM(monthly.pnl_realized)")
        leak = self.conn.execute(
            """SELECT COUNT(*) c FROM import_op_links l
                 JOIN import_normalized_tx n
                   ON n.batch_id=l.batch_id AND n.raw_row_id=l.raw_row_id
                WHERE n.excluded_at IS NOT NULL""").fetchone()["c"]
        self.assertEqual(leak, 0, "probe: hay links vivos a una tx excluida")

    # ── tests ────────────────────────────────────────────────────────────────
    def _setup_buy_sell(self):
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        sid = self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,10,200,2000,,,0,USD,"))
        # estado sano previo: 0 tenencia, P&L +500, cash +500
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 500.0, places=2)
        self.assertAlmostEqual(self._cash(), 500.0, places=2)
        return sid

    def test_delete_sell_full_cascade(self):
        sid = self._setup_buy_sell()
        oid = self._sell_oid()
        self.assertIsNotNone(oid)

        with self.conn:
            res = main._delete_operation_cascade(self.conn, self.uid, oid)
        self.assertTrue(res["ok"])

        # Tenencia RESTAURADA (el lote de 10 se re-abre), venta GONE, P&L 0.
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)
        self.assertEqual(len(self._ventas()), 0)
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        # Cash: se revierten los proceeds (+2000) → queda solo la compra (-1500).
        self.assertAlmostEqual(self._cash(), -1500.0, places=2)
        self._probe()

        # NO RESUCITA: re-derivar el batch (como un import futuro) la deja borrada.
        with self.conn:
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)
        self.assertEqual(len(self._ventas()), 0)
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        self._probe()

    def test_delete_sell_with_fees_reverses_net_cash(self):
        # Regresión del blocker del review: el persister acredita el NETO de
        # comisiones (2000−15=1985), NO el bruto. Al borrar, el cash tiene que
        # volver a −1500 (solo la compra), no −1515 (con la comisión de menos).
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,10,200,2000,,,15,USD,"))
        self.assertAlmostEqual(self._cash(), 485.0, places=2)   # -1500 + (2000-15)
        oid = self._sell_oid()
        with self.conn:
            main._delete_operation_cascade(self.conn, self.uid, oid)
        self.assertAlmostEqual(self._cash(), -1500.0, places=2)  # NETO revertido, sin residual del fee
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        self._probe()

    def test_delete_reverses_actual_credit_not_gross(self):
        # Regresión del blocker B1 del re-review: el persister acredita
        # reconciled_unit_price·qty (= precio·qty en no-bono), NO gross_amount.
        # Acá precio·qty = 100.10·3 = 300.30 pero el monto (settled) = 300.00 →
        # el persister acreditó 300.30; el borrado tiene que reversar 300.30, no
        # 300.00 (reversar el bruto dejaría +0.30 de residual en el saldo).
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,3,90,270,,,0,USD,"))
        self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,3,100.10,300,,,0,USD,"))
        self.assertAlmostEqual(self._cash(), 30.30, places=2)   # -270 + 300.30 (precio·qty)
        oid = self._sell_oid()
        with self.conn:
            main._delete_operation_cascade(self.conn, self.uid, oid)
        self.assertAlmostEqual(self._cash(), -270.0, places=2)  # solo la compra; SIN residual de 0.30
        self.assertAlmostEqual(self._open_qty(), 3.0, places=6)
        self._probe()

    def test_undo_restores_everything(self):
        self._setup_buy_sell()
        oid = self._sell_oid()
        with self.conn:
            res = main._delete_operation_cascade(self.conn, self.uid, oid)
        # deshacer (mismo camino que el endpoint undo)
        j = self.conn.execute(
            "SELECT * FROM deleted_ops_journal WHERE token=?", (res["undo_token"],)).fetchone()
        p = json.loads(j["payload_json"])
        with self.conn:
            self.conn.execute(
                "UPDATE import_normalized_tx SET excluded_at=NULL WHERE id=?", (p["tx_id"],))
            main._adjust_broker_cash(self.conn, self.uid, p["broker"], float(p["cash_reversed"]))
            rb.rebuild_pair_asset(self.conn, self.uid, p["broker"], p["asset"],
                                  tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))
            main._cascade_after_movement_delete(self.conn, self.uid, j["since_date"], {p["broker"]})
        # Todo vuelve al estado sano previo.
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 500.0, places=2)
        self.assertAlmostEqual(self._cash(), 500.0, places=2)
        self._probe()

    def test_manual_op_is_blocked(self):
        # Operación manual (sin import_op_links) → bloqueada con 400.
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, quantity,
                                       entry_price, exit_price, pnl_usd, currency)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (self.uid, "2025-01-10", self.BROKER, "MSFT", "Venta", 5, 100, 120, 100, "USD"))
        self.conn.commit()
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE asset='MSFT'").fetchone()["id"]
        with self.assertRaises(main.HTTPException) as cm:
            main._delete_operation_cascade(self.conn, self.uid, oid)
        self.assertEqual(cm.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
