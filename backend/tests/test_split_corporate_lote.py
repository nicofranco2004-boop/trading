"""Fix: cuando Balanz informa un split / cambio de ratio como un LOTE en los Movimientos
(un BUY $0 con la cantidad ya post-split, o un SELL $0 en un split inverso), la posición
importada YA queda al ratio nuevo. El split-check / adjust-ratio NO deben ofrecer
"Ajustar" sobre el lote viejo — hacerlo multiplica de nuevo → "cantidad errónea" (el bug
reportado por un usuario real de Balanz con CEDEARs).

Mecanismo (análogo a la foto de tenencia, pero con fuente = movimiento corporate):
`_corporate_split_watermarks` deriva READ-TIME de import_normalized_tx la fecha del
movimiento de split/ratio por (broker, activo) y la combina con el watermark de ajuste
vía max() → hereda su ventana de dedup (evento de split real; cubre el skew Balanz↔
yfinance). No pisa positions.split_adjusted_through. Es durable ante un re-import.
"""
import unittest
import uuid
from unittest.mock import patch

import main
from fastapi.testclient import TestClient
from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
from importing.schema import NormalizedTx, OP_BUY, OP_SELL, OP_DEPOSIT


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


class SplitCorporateLoteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"scl-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Balanz", "ARS"))
        self.conn.commit()
        self.token = main.create_token(self.uid)

    def tearDown(self):
        self.conn.close()

    def _import_mov(self, txs, tag="mov"):
        allt = [NormalizedTx(row_index=-10, date="2023-01-02", broker="Balanz",
                             operation_type=OP_DEPOSIT, gross_amount=5_000_000, currency="ARS")] + txs
        with self.conn:
            for i, t in enumerate(allt):
                t.row_index = -100 - i
            sid = pl.store_preview_txs(self.conn, self.uid, broker="Balanz",
                                       parser_format="balanz_movimientos", file_name=tag, txs=allt)
            t2, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=t2,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid,
                                         tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))
        return sid

    def _buy(self, tk, qty, date):
        return NormalizedTx(row_index=0, date=date, broker="Balanz", operation_type=OP_BUY,
                            asset_symbol=tk, asset_type="CEDEAR", quantity=qty, unit_price=1000,
                            gross_amount=qty * 1000, currency="ARS")

    def _corp(self, tk, delta, date, note, sell=False):
        # Un split/ratio de Balanz llega como acción societaria: BUY $0 (entran acciones)
        # o SELL $0 (split inverso), con la descripción cruda como `notes`.
        return NormalizedTx(row_index=0, date=date, broker="Balanz",
                            operation_type=OP_SELL if sell else OP_BUY,
                            asset_symbol=tk, asset_type="CEDEAR", quantity=delta, unit_price=0,
                            gross_amount=0, currency="ARS", notes=note)

    def _split_check(self, splits):
        with patch.object(main, "_fetch_ba_splits", return_value=list(splits)):
            r = self.client.get("/api/positions/split-check",
                                headers={"Authorization": f"Bearer {self.token}"})
        return r.json()["suggestions"]

    def _offers(self, ticker, splits):
        return any(s["asset"] == ticker for s in self._split_check(splits))

    # ── el fix ─────────────────────────────────────────────────────────────────
    def test_corporate_split_not_offered(self):
        # Caso central: Balanz bookeó el split como lote (BUY $0, nota "Split") → la qty ya
        # es post-split → NO ofrecer "Ajustar" (sino duplica).
        self._import_mov([self._buy("NVDA", 3, "2023-11-17"),
                          self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        self.assertFalse(self._offers("NVDA", [("2024-06-10", 10.0)]))

    def test_corporate_ratio_change_not_offered(self):
        # "Acreditación cambio de ratio" (con tilde) → matchea '%cambio de ratio%'.
        self._import_mov([self._buy("MELI", 2, "2023-05-01"),
                          self._corp("MELI", 18, "2024-03-15", "Acreditación cambio de ratio / MELI")])
        self.assertFalse(self._offers("MELI", [("2024-03-15", 10.0)]))

    def test_corporate_skew_within_window_not_offered(self):
        # El ex_date de yfinance cae 3 días DESPUÉS del movimiento corporate (skew Balanz↔
        # yfinance) → la ventana de dedup (heredada de la vía `wm`) lo trata como el mismo evento.
        self._import_mov([self._buy("NVDA", 3, "2023-11-17"),
                          self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        self.assertFalse(self._offers("NVDA", [("2024-06-13", 10.0)]))

    def test_split_without_corporate_still_offered(self):
        # Sin movimiento corporate → SÍ se ofrece (no rompe el caso legítimo: un split que
        # Balanz NO reportó como lote y que SÍ hay que ajustar).
        self._import_mov([self._buy("KO", 5, "2023-05-01")])
        self.assertTrue(self._offers("KO", [("2024-06-10", 2.0)]))

    def test_split_after_corporate_still_offered(self):
        # Un split POSTERIOR (fuera de la ventana) al movimiento corporate → SÍ se ofrece.
        self._import_mov([self._buy("NVDA", 3, "2023-11-17"),
                          self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        self.assertTrue(self._offers("NVDA", [("2024-06-10", 10.0), ("2026-08-01", 4.0)]))

    def test_dividendo_en_acciones_does_not_suppress(self):
        # Un "dividendo en acciones" es corporate pero NO es split → no debe crear watermark
        # → un split real posterior SÍ se sigue ofreciendo.
        self._import_mov([self._buy("AAPL", 4, "2023-02-01"),
                          self._corp("AAPL", 1, "2024-01-10", "Dividendo en acciones / AAPL")])
        self.assertTrue(self._offers("AAPL", [("2024-06-10", 4.0)]))

    def test_inverse_split_corporate_not_offered(self):
        # Split inverso (reverse): Balanz saca acciones vía VENTA $0 con nota "Split".
        # El watermark incluye operation_type SELL → tampoco se ofrece.
        self._import_mov([self._buy("GGAL", 100, "2023-04-01"),
                          self._corp("GGAL", 90, "2024-07-01", "Split / GGAL", sell=True)])
        self.assertFalse(self._offers("GGAL", [("2024-07-01", 0.1)]))

    def test_does_not_touch_split_adjusted_through(self):
        # El watermark corporate NO estampa positions.split_adjusted_through (lo consume el
        # backfill MTM) → queda NULL.
        self._import_mov([self._buy("NVDA", 3, "2023-11-17"),
                          self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        wms = [row["split_adjusted_through"] for row in self.conn.execute(
            "SELECT split_adjusted_through FROM positions WHERE user_id=? AND asset='NVDA' AND is_cash=0",
            (self.uid,))]
        self.assertTrue(wms and all(w is None for w in wms), wms)

    def test_durable_across_reimport(self):
        # Read-time (import_normalized_tx) → un re-import de Movimientos no reintroduce el bug.
        self._import_mov([self._buy("NVDA", 3, "2023-11-17"),
                          self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        self.assertFalse(self._offers("NVDA", [("2024-06-10", 10.0)]))
        self._import_mov([NormalizedTx(row_index=0, date="2026-07-05", broker="Balanz",
                                       operation_type=OP_SELL, asset_symbol="NVDA", asset_type="CEDEAR",
                                       quantity=1, unit_price=2000, gross_amount=2000, currency="ARS")],
                         tag="mov2")
        self.assertFalse(self._offers("NVDA", [("2024-06-10", 10.0)]))

    def test_reverted_batch_offers_again(self):
        # Guard load-bearing: un movimiento corporate en un batch REVERTIDO no debe crear
        # watermark → el split se vuelve a ofrecer (si alguien rompe el filtro status, esto falla).
        sid = self._import_mov([self._buy("NVDA", 3, "2023-11-17"),
                                self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        self.assertFalse(self._offers("NVDA", [("2024-06-10", 10.0)]))
        with self.conn:
            self.conn.execute("UPDATE import_batches SET status='reverted' WHERE id=?", (sid,))
        self.assertTrue(self._offers("NVDA", [("2024-06-10", 10.0)]))

    def test_preview_batch_does_not_watermark(self):
        # Una SESIÓN de preview (status='preview', sin confirmar) con el corp split NO debe
        # suprimir el ajuste del lote ya confirmado.
        self._import_mov([self._buy("NVDA", 3, "2023-11-17")])
        self.assertTrue(self._offers("NVDA", [("2024-06-10", 10.0)]))
        with self.conn:
            pl.store_preview_txs(self.conn, self.uid, broker="Balanz",
                                 parser_format="balanz_movimientos", file_name="prev",
                                 txs=[self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        self.assertTrue(self._offers("NVDA", [("2024-06-10", 10.0)]))

    def test_freetext_split_note_on_real_buy_not_watermark(self):
        # Guard estructural (nit del review): una nota manual "Split ..." en un BUY REAL
        # (precio > 0, ej. template genérico) NO debe crear watermark → el split real se ofrece.
        self._import_mov([NormalizedTx(row_index=0, date="2023-11-17", broker="Balanz",
                                       operation_type=OP_BUY, asset_symbol="NVDA", asset_type="CEDEAR",
                                       quantity=3, unit_price=1000, gross_amount=3000, currency="ARS",
                                       notes="Split de acciones (nota manual del usuario)")])
        self.assertTrue(self._offers("NVDA", [("2024-06-10", 10.0)]))

    def test_adjust_ratio_noop_after_corporate(self):
        # El botón "Ajustar" (adjust-ratio) sobre el lote viejo → no-op (no duplica).
        self._import_mov([self._buy("NVDA", 3, "2023-11-17"),
                          self._corp("NVDA", 27, "2024-06-10", "Split / NVDA")])
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='NVDA' AND is_cash=0 "
            "AND entry_date < '2024-01-01' LIMIT 1", (self.uid,)).fetchone()["id"]
        before = self.conn.execute("SELECT quantity FROM positions WHERE id=?", (pid,)).fetchone()["quantity"]
        with patch.object(main, "_fetch_ba_splits", return_value=[("2024-06-10", 10.0)]):
            r = self.client.post(f"/api/positions/{pid}/adjust-ratio",
                                 headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("already_applied"))
        after = self.conn.execute("SELECT quantity FROM positions WHERE id=?", (pid,)).fetchone()["quantity"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
