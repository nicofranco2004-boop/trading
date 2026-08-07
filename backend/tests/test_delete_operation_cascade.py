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

    def _import_dedup(self, csv_bytes: bytes) -> str:
        """Como `_import` pero replicando el paso de ANTI-DUPLICACIÓN del endpoint real
        (`import_confirm`, main.py:25697): saltea por fingerprint las filas ya presentes
        en otro batch confirmado y las borra del normalized del batch nuevo. `_import`
        lo omite, así que no sirve para probar el escenario de re-import solapado."""
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="y.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic",
            )
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            skip = pl.already_imported_row_indices(self.conn, self.uid, sid, txs,
                                                   already_skipped=set())
            if skip:
                txs = [t for t in txs if t.row_index not in skip]
                _ph = ",".join("?" * len(skip))
                self.conn.execute(
                    f"""DELETE FROM import_normalized_tx
                         WHERE batch_id=? AND raw_row_id IN (
                           SELECT id FROM import_raw_rows
                            WHERE batch_id=? AND row_index IN ({_ph}))""",
                    (sid, sid, *skip))
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


    # ── Fase 2.x: BONOS y renta fija (cupones/amortizaciones/dividendos) ─────────
    def _ops_count(self, asset):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM operations WHERE user_id=? AND asset=?",
            (self.uid, asset)).fetchone()["c"]

    def test_delete_asset_with_imported_dividend(self):
        # Antes BLOQUEADO. Ahora: una acción con un dividendo IMPORTADO se borra entera:
        # el dividendo se reversa (cash −monto, P&L −monto) junto con compras/ventas.
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2024-06-01,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,"))
        self.assertAlmostEqual(self._cash(), -1450.0, places=2)     # -1500 +50
        self.assertAlmostEqual(self._global_pnl(), 50.0, places=2)  # dividendo = income
        with self.conn:
            res = main._delete_asset_history_cascade(self.conn, self.uid, "AAPL")
        self.assertEqual(res["count"], 2)                           # compra + dividendo
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)
        self.assertAlmostEqual(self._cash(), 0.0, places=2)         # +1500 -50 revertido
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)   # dividendo fuera del P&L
        self.assertEqual(self._ops_count("AAPL"), 0)                # la fila del dividendo se fue
        self._probe()

    def test_delete_bond_with_coupon(self):
        # Un BONO (asset_type BOND) con compra + renta (cupón): antes bloqueado, ahora
        # se borra entero. La renta se reversa (cash) y desaparece de operations.
        self._import(_csv("2024-03-15,COMPRA,IBKR,AL30,100,60,6000,,,0,USD,"))
        self._import(_csv("2024-09-01,RENTA,IBKR,AL30,,,120,,,0,USD,"))
        # Tag de bono (data912 no está en el sandbox de tests) para ejercitar el path.
        self.conn.execute("UPDATE import_normalized_tx SET asset_type='BOND' WHERE asset_symbol='AL30'")
        self.conn.commit()
        self.assertAlmostEqual(self._cash(), -5880.0, places=2)     # -6000 +120
        with self.conn:
            main._delete_asset_history_cascade(self.conn, self.uid, "AL30")
        self.assertAlmostEqual(self._open_qty("AL30"), 0.0, places=6)
        self.assertAlmostEqual(self._cash(), 0.0, places=2)         # +6000 -120 revertido
        self.assertEqual(self._ops_count("AL30"), 0)
        self._probe()

    def test_undo_asset_with_dividend(self):
        # El undo recrea la fila del dividendo que el rebuild NO trae (la crea el
        # persister) + la re-linkea, y restaura cash y P&L. Replica el endpoint.
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2024-06-01,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,"))
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
            for snap in p.get("rf_ops", []):
                cur = self.conn.execute(
                    """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd,
                         quantity, commissions, notes, currency, fx_to_usd, cost_basis_consumed)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (self.uid, snap.get("date"), snap.get("broker"), snap.get("asset"),
                     snap.get("op_type"), snap.get("pnl_usd"), snap.get("quantity"),
                     snap.get("commissions"), snap.get("notes"), snap.get("currency"),
                     snap.get("fx_to_usd"), snap.get("cost_basis_consumed")))
                if snap.get("l_batch") is not None:
                    self.conn.execute(
                        "INSERT INTO import_op_links (batch_id, raw_row_id, operation_id) VALUES (?,?,?)",
                        (snap["l_batch"], snap["l_raw"], cur.lastrowid))
                _pnl = float(snap.get("pnl_usd") or 0)
                if _pnl and snap.get("date"):
                    _y, _m = int(snap["date"][:4]), int(snap["date"][5:7])
                    main._update_monthly_pnl_realized(self.conn, self.uid, snap["broker"], _y, _m, _pnl)
                    main._update_monthly_pnl_realized(self.conn, self.uid, "global", _y, _m, _pnl)
            main._cascade_after_movement_delete(self.conn, self.uid, j["since_date"], set(p["brokers"]))
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)
        self.assertAlmostEqual(self._cash(), -1450.0, places=2)
        self.assertAlmostEqual(self._global_pnl(), 50.0, places=2)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM operations WHERE user_id=? AND asset='AAPL' AND op_type='Dividendo'",
            (self.uid,)).fetchone()["c"], 1)                        # el dividendo volvió
        self._probe()

    # ── El tacho de CARTERA debe cascadear igual que el de Operaciones ─────────
    def test_delete_position_endpoint_cascades_when_imported(self):
        """`DELETE /api/positions/{id}` era un DELETE crudo: la fila desaparecía pero
        el cash quedaba debitado, la fuente sin tombstonear (el activo RESUCITABA al
        re-importar) y el link colgado (rompía el borrado bueno desde Movimientos)."""
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self.assertAlmostEqual(self._cash(), -1500.0, places=2)
        pid = self._pos_id()
        self.conn.commit()
        res = main.delete_position(pid, uid=self.uid)
        self.assertAlmostEqual(self._open_qty(), 0.0, places=6)
        self.assertAlmostEqual(self._cash(), 0.0, places=2)   # el cash volvió
        # La fuente quedó tombstoneada → no resucita al re-derivar.
        self.assertIsNotNone(self.conn.execute(
            "SELECT excluded_at FROM import_normalized_tx WHERE operation_type='BUY'"
        ).fetchone()["excluded_at"], "la compra no quedó tombstoneada → va a resucitar")
        self.assertTrue(res.get("undo_token"), "sin token no hay cómo deshacer")
        self._probe()

    def test_delete_position_endpoint_manual_still_works(self):
        """Las posiciones cargadas a mano (sin link de import) siguen borrándose
        directo — no hay eventos importados que re-derivar."""
        pid = self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash)
               VALUES (?,?,?,?,?,0)""", (self.uid, "IBKR", "MELI", 5, 1000)).lastrowid
        self.conn.commit()
        main.delete_position(pid, uid=self.uid)
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM positions WHERE id=?", (pid,)).fetchone())

    # ── El endpoint DEBE devolver el undo_token (el botón "Deshacer" depende) ──
    def test_delete_movement_returns_undo_token(self):
        """`delete_movement` descartaba el token de las cascadas y devolvía solo
        {'ok': True} → el frontend no tenía con qué deshacer y el confirm prometía
        algo imposible. Ahora lo propaga, y el token sirve de verdad."""
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2025-06-20,VENTA,IBKR,AAPL,4,200,800,,,0,USD,"))
        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='SELL'").fetchone()
        self.conn.commit()
        res = main.delete_movement(f"tx-{tx['id']}", uid=self.uid)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("undo_token"), "sin undo_token no hay cómo deshacer")
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)   # venta borrada
        # Y el token funciona contra el endpoint real de undo: la venta vuelve.
        main.undo_delete_operation(res["undo_token"], uid=self.uid)
        self.assertAlmostEqual(self._open_qty(), 6.0, places=6)
        self.assertEqual(len(self._ventas()), 1)
        self._probe()

    # ── Regresión: la base de amortización no puede contar filas borradas ──────
    def test_bond_genuine_net_excludes_deleted(self):
        """Antes `_bond_genuine_net` no filtraba `excluded_at`: tras borrar el
        historial de un bono y re-importarlo sumaba los nominales VIEJOS + los nuevos
        → base al doble, factor ≥1, el sweep no amortizaba y el bono se mostraba al
        100% del face."""
        from importing import maturity as mt
        self._import(_csv("2024-03-15,COMPRA,IBKR,AL30,720,60,43200,,,0,USD,"))
        self.conn.execute("UPDATE import_normalized_tx SET asset_type='BOND' WHERE asset_symbol='AL30'")
        self.conn.commit()
        pair = list(ps.broker_pair(self.conn, self.uid, "IBKR"))
        self.assertAlmostEqual(mt._bond_genuine_net(self.conn, self.uid, pair, "AL30"),
                               720.0, places=2)
        # Se borra el historial → las filas quedan tombstoneadas, no borradas.
        with self.conn:
            main._delete_asset_history_cascade(self.conn, self.uid, "AL30")
        self.assertAlmostEqual(
            mt._bond_genuine_net(self.conn, self.uid, pair, "AL30"), 0.0, places=2,
            msg="la base de amortización sigue contando el bono borrado → se duplica al re-importar")

    # ── Paso 1 de "borrar lo cargado a mano": cada camino deja su rastro ───────
    def test_manual_paths_stamp_undo_meta(self):
        """Una venta hecha con el botón 'Vender' y una tipeada en el formulario son
        IDÉNTICAS en la base, pero la primera movió cash y lotes. Sin estampar de dónde
        salió cada fila, borrarlas es adivinar. Cada camino guarda lo suyo."""
        import json as _j
        # (a) Trade tipeado: no toca cash ni lotes → basta con la marca.
        op = main.create_operation(main.OperationIn(
            date="2024-05-02", broker=self.BROKER, asset="AAPL", op_type="Venta",
            pnl_usd=25.0), uid=self.uid)
        meta = _j.loads(self.conn.execute(
            "SELECT undo_meta_json FROM operations WHERE id=?", (op["id"],)
        ).fetchone()["undo_meta_json"])
        self.assertEqual(meta["src"], "manual_form")

        # (b) Posición manual: guarda lo que debitó y el autodepósito que disparó
        #     (sin saldo previo, el alta AUTO-DEPOSITA → hay que poder revertirlo).
        pos = main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=2, buy_price=100,
            invested=200, entry_date="2024-05-03"), uid=self.uid)
        pmeta = _j.loads(self.conn.execute(
            "SELECT undo_meta_json FROM positions WHERE id=?", (pos["id"],)
        ).fetchone()["undo_meta_json"])
        self.assertEqual(pmeta["src"], "manual_position")
        self.assertAlmostEqual(pmeta["cost"], 200.0, places=2)
        self.assertIsNotNone(pmeta["autodep"], "no se guardó el autodepósito → capital fantasma al borrar")
        self.assertAlmostEqual(pmeta["autodep"]["native"], 200.0, places=2)
        self.assertEqual(pmeta["autodep"]["ym"], "2024-05")

        # (c) Venta FIFO: guarda una FOTO del lote que consumió — sin eso la
        #     tenencia es irrecuperable.
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=2, exit_price=150,
            date="2024-06-01"), uid=self.uid)
        smeta = _j.loads(self.conn.execute(
            "SELECT undo_meta_json FROM operations WHERE asset='MELI' AND op_type='Venta' "
            "ORDER BY id DESC LIMIT 1").fetchone()["undo_meta_json"])
        self.assertEqual(smeta["src"], "fifo_sell")
        self.assertAlmostEqual(smeta["cash"], 300.0, places=2)       # 2 × 150
        self.assertAlmostEqual(smeta["lot"]["quantity"], 2.0, places=6)
        self.assertAlmostEqual(smeta["lot"]["invested"], 200.0, places=2)
        self.assertAlmostEqual(smeta["lot"]["consumed"], 2.0, places=6)

    # ── Paso 2: borrar de verdad lo cargado a mano ────────────────────────────
    def test_delete_manual_form_operation(self):
        """Trade tipeado: no movió cash ni lotes → sale del P&L y listo."""
        op = main.create_operation(main.OperationIn(
            date="2024-05-02", broker=self.BROKER, asset="AAPL", op_type="Venta",
            pnl_usd=25.0), uid=self.uid)
        self.assertAlmostEqual(self._global_pnl(), 25.0, places=2)
        with self.conn:
            main._delete_operation_cascade(self.conn, self.uid, op["id"])
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        self.assertEqual(self._ops_count("AAPL"), 0)
        self._probe()

    def test_delete_manual_position_reverses_autodeposit(self):
        """Posición manual sin saldo previo: el alta AUTO-DEPOSITA. Borrarla tiene que
        dejar el cash Y el capital aportado como estaban — devolver el costo entero
        deja las dos cosas infladas."""
        pos = main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=2, buy_price=100,
            invested=200, entry_date="2024-05-03"), uid=self.uid)
        self.assertAlmostEqual(self._cash(), 0.0, places=2)        # autodep 200 − costo 200
        aportado = lambda: float(self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["d"] or 0)
        self.assertAlmostEqual(aportado(), 200.0, places=2)
        main.delete_position(pos["id"], uid=self.uid)
        self.assertAlmostEqual(self._open_qty("MELI"), 0.0, places=6)
        self.assertAlmostEqual(self._cash(), 0.0, places=2,
                               msg="quedó cash fantasma (se devolvió el costo entero)")
        self.assertAlmostEqual(aportado(), 0.0, places=2,
                               msg="quedó capital aportado fantasma del autodepósito")

    def test_delete_manual_fifo_sell_restores_lot(self):
        """Venta con el botón 'Vender': borrarla tiene que RESTAURAR el lote que
        consumió y descontar el cash que acreditó."""
        main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=2, buy_price=100,
            invested=200, entry_date="2024-05-03"), uid=self.uid)
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=2, exit_price=150,
            date="2024-06-01"), uid=self.uid)
        self.assertAlmostEqual(self._open_qty("MELI"), 0.0, places=6)   # lote consumido
        self.assertAlmostEqual(self._cash(), 300.0, places=2)           # 2 × 150
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE asset='MELI' AND op_type='Venta' "
            "ORDER BY id DESC LIMIT 1").fetchone()["id"]
        with self.conn:
            main._delete_operation_cascade(self.conn, self.uid, oid)
        self.assertAlmostEqual(self._open_qty("MELI"), 2.0, places=6,
                               msg="el lote consumido NO se restauró")
        self.assertAlmostEqual(self._cash(), 0.0, places=2,
                               msg="no se descontó el cash que la venta acreditó")
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        self._probe()

    # ── Deshacer el borrado manual (round-trip completo) ──────────────────────
    def _aportado(self):
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["d"] or 0)

    def test_undo_manual_form_operation(self):
        op = main.create_operation(main.OperationIn(
            date="2024-05-02", broker=self.BROKER, asset="AAPL", op_type="Venta",
            pnl_usd=25.0), uid=self.uid)
        self.conn.commit()
        res = main.delete_operation(op["id"], uid=self.uid)
        self.assertTrue(res.get("undo_token"), "el borrado manual no ofrece deshacer")
        self.assertAlmostEqual(self._global_pnl(), 0.0, places=2)
        main.undo_delete_operation(res["undo_token"], uid=self.uid)
        self.assertAlmostEqual(self._global_pnl(), 25.0, places=2)
        self.assertEqual(self._ops_count("AAPL"), 1)
        self._probe()

    def test_undo_manual_position_restores_cash_and_aportado(self):
        pos = main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=2, buy_price=100,
            invested=200, entry_date="2024-05-03"), uid=self.uid)
        self.conn.commit()
        cash0, ap0 = self._cash(), self._aportado()
        res = main.delete_position(pos["id"], uid=self.uid)
        self.assertTrue(res.get("undo_token"))
        self.assertAlmostEqual(self._aportado(), 0.0, places=2)
        main.undo_delete_operation(res["undo_token"], uid=self.uid)
        self.assertAlmostEqual(self._open_qty("MELI"), 2.0, places=6, msg="la posición no volvió")
        self.assertAlmostEqual(self._cash(), cash0, places=2, msg="el cash no volvió a como estaba")
        self.assertAlmostEqual(self._aportado(), ap0, places=2,
                               msg="el capital aportado no volvió (autodepósito)")

    def test_undo_manual_fifo_sell_reconsumes_lot(self):
        main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=2, buy_price=100,
            invested=200, entry_date="2024-05-03"), uid=self.uid)
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=2, exit_price=150,
            date="2024-06-01"), uid=self.uid)
        self.conn.commit()
        qty0, cash0, pnl0 = self._open_qty("MELI"), self._cash(), self._global_pnl()
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE asset='MELI' AND op_type='Venta' "
            "ORDER BY id DESC LIMIT 1").fetchone()["id"]
        res = main.delete_operation(oid, uid=self.uid)
        self.assertAlmostEqual(self._open_qty("MELI"), 2.0, places=6)   # lote restaurado
        main.undo_delete_operation(res["undo_token"], uid=self.uid)
        # Deshacer = la venta vuelve: el lote se re-consume y el cash vuelve a entrar.
        self.assertAlmostEqual(self._open_qty("MELI"), qty0, places=6,
                               msg="el lote no se volvió a consumir")
        self.assertAlmostEqual(self._cash(), cash0, places=2)
        self.assertAlmostEqual(self._global_pnl(), pnl0, places=2)
        self._probe()

    def test_undo_manual_is_idempotent(self):
        op = main.create_operation(main.OperationIn(
            date="2024-05-02", broker=self.BROKER, asset="AAPL", op_type="Venta",
            pnl_usd=25.0), uid=self.uid)
        self.conn.commit()
        res = main.delete_operation(op["id"], uid=self.uid)
        main.undo_delete_operation(res["undo_token"], uid=self.uid)
        with self.assertRaises(main.HTTPException) as cm:   # doble-click no duplica
            main.undo_delete_operation(res["undo_token"], uid=self.uid)
        self.assertIn(cm.exception.status_code, (404, 409))
        self.assertEqual(self._ops_count("AAPL"), 1)
        self.assertAlmostEqual(self._global_pnl(), 25.0, places=2)

    def test_delete_manual_position_blocked_if_lot_changed(self):
        """Hallazgo del review (reproducido): el lote es MUTABLE — una venta parcial lo
        achica pero la foto del alta NO se actualiza. Devolver el `cost` de la foto
        fabricaba cash (alta 400 → vender 2 → borrar el remanente devolvía 400 en vez
        de 200). Se bloquea, igual que una compra importada parcialmente vendida."""
        main._adjust_broker_cash(self.conn, self.uid, self.BROKER, 1000.0)
        self.conn.commit()
        pos = main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=4, buy_price=100,
            invested=400, entry_date="2024-05-03"), uid=self.uid)
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=2, exit_price=150,
            date="2024-06-01"), uid=self.uid)
        cash_antes = self._cash()
        with self.assertRaises(main.HTTPException) as cm:
            main.delete_position(pos["id"], uid=self.uid)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertAlmostEqual(self._cash(), cash_antes, places=2,
                               msg="se fabricó cash con el costo congelado")

    def test_restored_lot_keeps_its_autodeposit(self):
        """Reproducido en el audit: el lote que el borrado de una venta RE-CREA nacía sin
        la foto del autodepósito → borrarlo después fabricaba cash Y capital aportado
        (200 y 200 de la nada). Ahora la venta guarda la foto del lote y se la devuelve."""
        aportado = lambda: float(self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["d"] or 0)
        # SIN saldo previo → el alta dispara autodepósito.
        main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=2, buy_price=100,
            invested=200, entry_date="2024-05-03"), uid=self.uid)
        self.assertAlmostEqual(aportado(), 200.0, places=2)
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=2, exit_price=150,
            date="2024-06-01"), uid=self.uid)
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE op_type='Venta' ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
        self.conn.commit()
        main.delete_operation(oid, uid=self.uid)          # re-crea el lote
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND is_cash=0", (self.uid,)).fetchone()["id"]
        main.delete_position(pid, uid=self.uid)           # y ahora lo borramos
        self.assertAlmostEqual(self._cash(), 0.0, places=2, msg="se fabricó cash")
        self.assertAlmostEqual(aportado(), 0.0, places=2, msg="quedó capital aportado fantasma")
        self.assertAlmostEqual(self._open_qty("MELI"), 0.0, places=6)

    def test_recreated_lot_keeps_its_autodeposit(self):
        """Backlog del review, REPRODUCIDO: si la venta barre el lote entero y después se
        borra la venta, el lote se RE-CREA. Nacía sin la foto del autodepósito → borrarlo
        después fabricaba cash y capital aportado (medido: +200 y +200 sobre una cuenta
        que debía quedar en cero)."""
        aportado = lambda: float(self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["d"] or 0)
        # SIN saldo previo → el alta dispara el autodepósito.
        main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=2, buy_price=100,
            invested=200, entry_date="2024-05-03"), uid=self.uid)
        self.assertAlmostEqual(aportado(), 200.0, places=2)
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=2, exit_price=150,
            date="2024-06-01"), uid=self.uid)
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE op_type='Venta' ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
        self.conn.commit()
        main.delete_operation(oid, uid=self.uid)          # el lote se RE-CREA
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND is_cash=0", (self.uid,)).fetchone()["id"]
        main.delete_position(pid, uid=self.uid)           # y ahora se borra
        self.assertAlmostEqual(self._cash(), 0.0, places=2,
                               msg="el lote re-creado fabricó cash al borrarlo")
        self.assertAlmostEqual(aportado(), 0.0, places=2,
                               msg="el lote re-creado dejó capital aportado fantasma")

    def test_undo_manual_blocked_if_world_changed(self):
        """El undo manual re-aplica deltas guardados contra el mundo de HOY. Si el lote
        cambió, esos deltas dejan de ser un reverso (tenencia negativa). Se frena."""
        main._adjust_broker_cash(self.conn, self.uid, self.BROKER, 1000.0)
        self.conn.commit()
        main.create_position(main.PositionIn(
            broker=self.BROKER, asset="MELI", quantity=10, buy_price=50,
            invested=500, entry_date="2024-05-03"), uid=self.uid)
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=4, exit_price=80,
            date="2024-06-01"), uid=self.uid)
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE op_type='Venta' ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
        self.conn.commit()
        res = main.delete_operation(oid, uid=self.uid)          # lote vuelve a 10
        # Entre el borrado y el deshacer, el usuario vende casi todo.
        main.sell_position_fifo(main.SellIn(
            broker=self.BROKER, asset="MELI", quantity=9, exit_price=90,
            date="2024-07-01"), uid=self.uid)
        self.conn.commit()
        qty_antes = self._open_qty("MELI")
        with self.assertRaises(main.HTTPException) as cm:
            main.undo_delete_operation(res["undo_token"], uid=self.uid)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertAlmostEqual(self._open_qty("MELI"), qty_antes, places=6,
                               msg="el undo dejó la tenencia negativa")
        self.assertGreaterEqual(self._open_qty("MELI"), 0.0)

    def test_delete_manual_legacy_row_is_blocked(self):
        """Fila vieja (sin la foto de reverso): su reverso NO es derivable → se
        bloquea con mensaje claro en vez de arriesgar saldo/tenencia."""
        oid = self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd)
               VALUES (?,?,?,?,?,?)""",
            (self.uid, "2023-01-05", self.BROKER, "AAPL", "Venta", 10)).lastrowid
        self.conn.commit()
        with self.assertRaises(main.HTTPException) as cm:
            main._delete_operation_cascade(self.conn, self.uid, oid)
        self.assertEqual(cm.exception.status_code, 400)

    # ── Regresión: borrar un cash-flow NO puede revivir en el próximo import ────
    def test_deleted_cashflow_is_tombstoned_not_deleted(self):
        """Antes se hacía DELETE físico de la fila fuente: como el dedup del import
        usa los fingerprints que SIGUEN en la tabla, el próximo export solapado la
        re-importaba y volvía a sumar la plata. Ahora queda tombstoneada."""
        self._import(_csv("2024-03-10,DEPOSITO,IBKR,,,,10000,,,0,USD,"))
        self.assertAlmostEqual(self._cash(), 10000.0, places=2)
        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='DEPOSIT'").fetchone()
        with self.conn:
            main._route_tx_delete(self.conn, self.uid, f"tx-{tx['id']}")
        self.assertAlmostEqual(self._cash(), 0.0, places=2)
        # La fila SIGUE existiendo (tombstone) → su fingerprint frena el re-import.
        row = self.conn.execute(
            "SELECT excluded_at FROM import_normalized_tx WHERE id=?", (tx["id"],)).fetchone()
        self.assertIsNotNone(row, "la fila se borró físicamente → va a resucitar")
        self.assertIsNotNone(row["excluded_at"], "la fila no quedó tombstoneada")
        # Y el capital aportado quedó en 0 (el filtro de excluded_at en flows).
        self.assertAlmostEqual(float(self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["d"] or 0),
            0.0, places=2, msg="el depósito borrado sigue contando en capital aportado")

    def test_deleted_deposit_does_not_come_back_on_overlapping_reimport(self):
        """EL escenario real de la resurrección: borrás un depósito y al mes siguiente
        subís el export SOLAPADO del broker (Balanz/Cocos/PPI/IEB mandan el histórico
        completo). El depósito NO puede volver ni re-sumar la plata."""
        self._import(_csv("2024-03-10,DEPOSITO,IBKR,,,,10000,,,0,USD,"))
        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='DEPOSIT'").fetchone()
        with self.conn:
            main._route_tx_delete(self.conn, self.uid, f"tx-{tx['id']}")
        self.assertAlmostEqual(self._cash(), 0.0, places=2)

        # Export del mes siguiente: MISMO depósito + una compra nueva (con el dedup
        # real del endpoint, que es donde vive la anti-duplicación).
        self._import_dedup(_csv("2024-03-10,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                                "2024-04-05,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        # El depósito quedó fuera (dedup por fingerprint, que sobrevive al tombstone);
        # solo entró la compra → cash = -1500, no +8500.
        self.assertAlmostEqual(self._cash(), -1500.0, places=2,
                               msg="el depósito borrado RESUCITÓ en el import solapado")
        self.assertAlmostEqual(float(self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["d"] or 0),
            0.0, places=2, msg="el depósito borrado volvió al capital aportado")
        self._probe()

    def test_seed_rows_are_blocked_everywhere(self):
        """La compra semilla y el depósito sintético de la foto de tenencia no se
        pueden borrar sueltos: los fondea un depósito COMPARTIDO. La guarda estaba
        solo en el borrado por-activo."""
        self._import(_csv("2024-01-02,DEPOSITO,IBKR,,,,900000,,,0,USD,"
                          "Tenencia — aporte inicial sintético (Rendi)"))
        self._import(_csv("2024-01-02,COMPRA,IBKR,GGAL,100,5000,500000,,,0,USD,"
                          "Tenencia — aporte inicial sintético (Rendi)"))
        dep = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='DEPOSIT'").fetchone()
        buy = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='BUY'").fetchone()
        for tid, what in ((dep["id"], "depósito sintético"), (buy["id"], "compra semilla")):
            with self.assertRaises(main.HTTPException, msg=f"{what} no bloqueado") as cm:
                main._route_tx_delete(self.conn, self.uid, f"tx-{tid}")
            self.assertEqual(cm.exception.status_code, 400, f"{what}: status inesperado")

    # ── Regresión CRÍTICA: borrar NO puede destruir la curva real a mercado ─────
    def test_delete_preserves_real_snapshots(self):
        """Antes: la cascada purgaba TODOS los snapshots desde la fecha del ítem
        borrado y el backfill los reescribía al COSTO → borrar un dividendo viejo
        aplanaba años de curva, irrecuperable. Ahora la medición se conserva y solo
        se le recomputa el capital aportado."""
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2024-06-01,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,"))
        # Foto REAL del cron (tiene blue + composición): vale 25.000 a mercado.
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                 net_deposited, fx_to_usd_blue, holdings_json)
               VALUES (?,?,?,?,?,?,?)""",
            (self.uid, "2024-07-10", 25000.0, 1500.0, 1500.0, 1180.0, '[{"a":"AAPL"}]'))
        # Foto SINTÉTICA del backfill (sin blue ni composición): es derivada.
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited)
               VALUES (?,?,?,?,?)""",
            (self.uid, "2024-07-31", 1550.0, 1500.0, 1500.0))
        self.conn.commit()

        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='DIVIDEND'").fetchone()
        with self.conn:
            main._route_tx_delete(self.conn, self.uid, f"tx-{tx['id']}")

        real = self.conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=? AND date='2024-07-10'",
            (self.uid,)).fetchone()
        self.assertIsNotNone(real, "la foto REAL a mercado se borró (curva destruida)")
        self.assertAlmostEqual(real["total_value"], 25000.0, places=2,
                               msg="la foto real fue reescrita al costo")
        # La sintética sí se regenera desde monthly (ya corregido) — no queda stale.
        syn = self.conn.execute(
            "SELECT fx_to_usd_blue, holdings_json FROM snapshots WHERE user_id=? AND date='2024-07-31'",
            (self.uid,)).fetchone()
        if syn:
            self.assertIsNone(syn["fx_to_usd_blue"])   # si existe, es la recreada

    def test_delete_preserves_cold_cache_dashboard_snapshot(self):
        """`POST /api/snapshots` (el que escribe el Dashboard) guarda fx=NULL cuando el
        caché del dólar está frío, y NUNCA escribe holdings. O sea que una MEDICIÓN real
        matchea la heurística 'sin blue ni holdings' y se borraba igual. El backfill solo
        escribe FIN DE MES → exigimos también esa fecha."""
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2024-06-01,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,"))
        # Medición real del Dashboard, media de mes, con el caché frío.
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                 net_deposited, fx_to_usd_blue) VALUES (?,?,?,?,?,NULL)""",
            (self.uid, "2024-07-15", 25000.0, 1500.0, 1500.0))
        self.conn.commit()
        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='DIVIDEND'").fetchone()
        with self.conn:
            main._route_tx_delete(self.conn, self.uid, f"tx-{tx['id']}")
        row = self.conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=? AND date='2024-07-15'",
            (self.uid,)).fetchone()
        self.assertIsNotNone(row, "se borró una medición real del Dashboard (caché frío)")
        self.assertAlmostEqual(row["total_value"], 25000.0, places=2)

    def test_stale_synthetic_month_end_is_still_regenerated(self):
        """Contracara: la sintética de FIN DE MES sí tiene que regenerarse, si no queda
        con el capital_final viejo (que es justo lo que el borrado acaba de cambiar)."""
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2024-06-01,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,"))
        # El backfill ya escribió el fin de mes: lo ensuciamos para simular el stale.
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, date) DO UPDATE SET total_value=excluded.total_value,
                 fx_to_usd_blue=NULL, holdings_json=NULL""",
            (self.uid, "2024-06-30", 99999.0, 1500.0, 1500.0))
        self.conn.commit()
        tx = self.conn.execute(
            "SELECT id FROM import_normalized_tx WHERE operation_type='DIVIDEND'").fetchone()
        with self.conn:
            main._route_tx_delete(self.conn, self.uid, f"tx-{tx['id']}")
        row = self.conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=? AND date='2024-06-30'",
            (self.uid,)).fetchone()
        # O se borró, o se recreó con el valor corregido — lo que NO puede es
        # quedarse con el 99999 stale.
        if row:
            self.assertNotAlmostEqual(row["total_value"], 99999.0, places=2,
                                      msg="la sintética de fin de mes quedó stale")

    def test_undo_asset_with_dividend_via_endpoint(self):
        # Cobertura del ENDPOINT real de undo (no replay a mano): recrea el dividendo,
        # re-linkea, re-corre el sweep y restaura P&L/cash. Cubre lo que el replay omite.
        self._import(_csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"))
        self._import(_csv("2024-06-01,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,"))
        with self.conn:
            res = main._delete_asset_history_cascade(self.conn, self.uid, "AAPL")
        self.conn.commit()
        main.undo_delete_asset_history(res["undo_token"], uid=self.uid)
        self.assertAlmostEqual(self._open_qty(), 10.0, places=6)
        self.assertAlmostEqual(self._cash(), -1450.0, places=2)
        self.assertAlmostEqual(self._global_pnl(), 50.0, places=2)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM operations WHERE user_id=? AND asset='AAPL' AND op_type='Dividendo'",
            (self.uid,)).fetchone()["c"], 1)
        self._probe()

    def test_delete_asset_manual_coupon_blocked(self):
        # Cupón CARGADO A MANO (1-click, sin import link) sobre un activo importado:
        # su P&L se modela distinto que el importado → bloqueamos el borrado entero
        # (mejor bloquear que dejar el P&L inconsistente) con un 400 claro.
        self._import(_csv("2024-03-15,COMPRA,IBKR,AL30,100,60,6000,,,0,USD,"))
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd, currency, fx_to_usd)
               VALUES (?,?,?,?,?,?,?,?)""",
            (self.uid, "2024-09-01", "IBKR", "AL30", "Cupón", 100, "USD", 1.0))
        self.conn.commit()
        with self.assertRaises(main.HTTPException) as cm:
            main._delete_asset_history_cascade(self.conn, self.uid, "AL30")
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
