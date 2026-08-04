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


    # ── Fase 2: borrar el historial ENTERO de un activo ─────────────────────
    def test_delete_entire_asset_history(self):
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,4,200,800,,,0,USD,"))
        self.assertAlmostEqual(self._open_qty(), 6.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 200.0, places=2)   # 4*(200-150)
        self.assertAlmostEqual(self._cash(), -700.0, places=2)        # -1500 + 800

        with self.conn:
            res = main._delete_asset_history_cascade(self.conn, self.uid, "AAPL")
        self.assertEqual(res["count"], 2)
        # Activo entero fuera: sin lotes fantasma, sin ventas, P&L 0, cash sin huella.
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)
        self.assertEqual(len(self._ventas()), 0)
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        self.assertAlmostEqual(self._cash(), 0.0, places=2)           # +1500 -800 revertido
        self._probe()

        # NO resucita al re-derivar.
        with self.conn:
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_pair_asset(self.conn, self.uid, "IBKR", "AAPL", tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)

    def test_undo_asset_history(self):
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,4,200,800,,,0,USD,"))
        with self.conn:
            res = main._delete_asset_history_cascade(self.conn, self.uid, "AAPL")
        j = self.conn.execute(
            "SELECT * FROM deleted_ops_journal WHERE token=?", (res["undo_token"],)).fetchone()
        p = json.loads(j["payload_json"])
        with self.conn:
            for tid in p["tx_ids"]:
                self.conn.execute("UPDATE import_normalized_tx SET excluded_at=NULL WHERE id=?", (tid,))
            for b, delta in p["cash_by_broker"].items():
                main._adjust_broker_cash(self.conn, self.uid, b, -float(delta))
            for pr in p["pairs"]:
                rb.rebuild_pair_asset(self.conn, self.uid, pr[0], "AAPL",
                                      tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))
            main._cascade_after_movement_delete(self.conn, self.uid, j["since_date"], set(p["brokers"]))
        self.assertAlmostEqual(self._open_qty(), 6.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 200.0, places=2)
        self.assertAlmostEqual(self._cash(), -700.0, places=2)
        self._probe()


    def test_delete_asset_blocked_if_dividend(self):
        # Blocker del review: un activo con un dividendo enlazado NO se puede borrar
        # entero todavía (dejaría el dividendo vivo) → 400.
        self._import(_csv("2024-03-15,COMPRA,IBKR,GGAL,10,20,200,,,0,USD,"))
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd, currency)
               VALUES (?,?,?,?,?,?,?)""",
            (self.uid, "2024-06-01", "IBKR", "GGAL", "Dividendo", 5, "USD"))
        self.conn.commit()
        with self.assertRaises(main.HTTPException) as cm:
            main._delete_asset_history_cascade(self.conn, self.uid, "GGAL")
        self.assertEqual(cm.exception.status_code, 400)


    # ── Fase 2.x: borrar un LOTE ABIERTO (compra sin vender) desde Movimientos ──
    def _pos_id(self, asset="AAPL"):
        r = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset=? AND is_cash=0 LIMIT 1",
            (self.uid, asset)).fetchone()
        return r["id"] if r else None

    def test_delete_open_position(self):
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)
        self.assertAlmostEqual(self._cash(), -1500.0, places=2)
        with self.conn:
            main._delete_position_cascade(self.conn, self.uid, self._pos_id())
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)   # lote borrado
        self.assertAlmostEqual(self._cash(), 0.0, places=2)       # -1500 + 1500 devuelto
        self._probe()

    def test_delete_position_blocked_if_partially_sold(self):
        # La compra ya se vendió en parte → borrar el lote dejaría la venta huérfana → 409.
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,4,200,800,,,0,USD,"))
        self.assertAlmostEqual(self._open_qty(), 6.0, places=6)
        with self.assertRaises(main.HTTPException) as cm:
            main._delete_position_cascade(self.conn, self.uid, self._pos_id())
        self.assertEqual(cm.exception.status_code, 409)

    def test_undo_open_position(self):
        # El undo de una COMPRA re-debita el cash (signo opuesto a la venta).
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        with self.conn:
            res = main._delete_position_cascade(self.conn, self.uid, self._pos_id())
        j = self.conn.execute(
            "SELECT * FROM deleted_ops_journal WHERE token=?", (res["undo_token"],)).fetchone()
        p = json.loads(j["payload_json"])
        with self.conn:
            self.conn.execute("UPDATE import_normalized_tx SET excluded_at=NULL WHERE id=?", (p["tx_id"],))
            main._adjust_broker_cash(self.conn, self.uid, p["broker"], float(p["cash_reversed"]))
            rb.rebuild_pair_asset(self.conn, self.uid, p["broker"], p["asset"],
                                  tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))
            main._cascade_after_movement_delete(self.conn, self.uid, j["since_date"], {p["broker"]})
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)
        self.assertAlmostEqual(self._cash(), -1500.0, places=2)   # re-debitado
        self._probe()


    # ── Wiring end-to-end: borrar trades importados desde Movimientos (id tx-) ──
    def test_delete_imported_buy_via_tx_route(self):
        # Una COMPRA importada aparece como tx- (no pos-). El router la manda a
        # _delete_position_cascade. (El bug que el review cazó: antes daba 400.)
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='BUY' AND asset_symbol='AAPL'"
        ).fetchone()
        with self.conn:
            main._route_tx_delete(self.conn, self.uid, f"tx-{tx['id']}")
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)
        self.assertAlmostEqual(self._cash(), 0.0, places=2)
        self._probe()

    def test_delete_imported_sell_via_tx_route(self):
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,4,200,800,,,0,USD,"))
        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='SELL' AND asset_symbol='AAPL'"
        ).fetchone()
        with self.conn:
            main._route_tx_delete(self.conn, self.uid, f"tx-{tx['id']}")
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)   # tenencia restaurada
        self.assertEqual(len(self._ventas()), 0)
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        self._probe()


    # ── Fase 2.x: depósito manual EN PESOS ahora se puede borrar (aproximado) ──
    def test_delete_manual_ars_deposit_unblocked(self):
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", "1000"))
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (self.uid, "Cocos", "ARS"))
        # cash del broker: 50.000 pesos
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
            (self.uid, "Cocos", "ARS", 50000.0))
        # depósito manual de 50 USD (= 50.000 pesos al blue 1000)
        self.conn.execute(
            """INSERT INTO monthly_entries
                 (user_id, broker, year, month, deposits, withdrawals,
                  capital_inicio, capital_final, pnl_realized, manual_deposits, manual_withdrawals)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (self.uid, "Cocos", 2025, 1, 50, 0, 0, 50, 0, 50.0, 0))
        self.conn.commit()
        me_id = self.conn.execute(
            "SELECT id FROM monthly_entries WHERE broker='Cocos'").fetchone()["id"]

        with self.conn:
            main._delete_one_movement(self.conn, self.uid, f"me-{me_id}-dep")

        # Aportado EXACTO: el manual del mes queda en 0.
        md = self.conn.execute(
            "SELECT manual_deposits FROM monthly_entries WHERE id=?", (me_id,)).fetchone()["manual_deposits"]
        self.assertAlmostEqual(md or 0, 0.0, places=6)
        # Cash: 50.000 − (50 USD × 1000) = 0.
        cash = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker='Cocos' AND is_cash=1",
            (self.uid,)).fetchone()["invested"]
        self.assertAlmostEqual(cash, 0.0, places=2)


    def test_delete_manual_ars_deposit_native_exact(self):
        # Con el nativo guardado al crear, la reversa es EXACTA (no aproxima al blue).
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", "1200"))   # blue de HOY distinto al de creación
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (self.uid, "Cocos", "ARS"))
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
            (self.uid, "Cocos", "ARS", 50000.0))
        # Crear el depósito por el flujo: 50.000 pesos nativo, 50 USD (blue de creación 1000).
        with self.conn:
            main._update_monthly_flow(self.conn, self.uid, "Cocos", 2025, 1, "deposit",
                                      50.0, is_manual=True, native_amount=50000.0)
        me_id = self.conn.execute(
            "SELECT id FROM monthly_entries WHERE broker='Cocos'").fetchone()["id"]
        nat = self.conn.execute(
            "SELECT manual_deposits_native FROM monthly_entries WHERE id=?", (me_id,)).fetchone()[0]
        self.assertAlmostEqual(nat or 0, 50000.0, places=2)   # nativo persistido
        with self.conn:
            main._delete_one_movement(self.conn, self.uid, f"me-{me_id}-dep")
        cash = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker='Cocos' AND is_cash=1",
            (self.uid,)).fetchone()["invested"]
        # EXACTO: 50.000 − 50.000 = 0 (no 50.000 − 50×1200 = −10.000 del aproximado).
        self.assertAlmostEqual(cash, 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
