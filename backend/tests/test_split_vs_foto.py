"""Fix: el split-check / adjust-ratio NO deben ofrecer "Ajustar split" en posiciones
que la foto de tenencia (Resumen) ya concilió.

La foto trae la cantidad ACTUAL del broker (que YA refleja todos los splits hasta su
fecha). El watermark efectivo de splits se deriva READ-TIME de las tx seed 'Tenencia —
apertura' (fechadas a la fecha REAL de la foto = seed_date) → _applicable_splits filtra
los splits previos. Sin esto, apretar "Ajustar" multiplica un lote pre-split ya
compensado por el seed → tenencia inflada (NVDA 33→60).

Cubre los 4 hallazgos del review adversarial:
  • no pisa positions.split_adjusted_through (que consume el backfill MTM);
  • usa la fecha REAL de la foto (seed_date), no la de las ventas de ajuste (red_date);
  • es DURABLE ante un re-import de Movimientos (read-time, lee import_normalized_tx);
  • un split POSTERIOR a la foto se sigue detectando; un CEDEAR sin foto también.
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


class SplitVsFotoTest(unittest.TestCase):
    FOTO = "2026-06-30"

    def setUp(self):
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"svf-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "IOL", "ARS"))
        self.conn.commit()
        self.token = main.create_token(self.uid)

    def tearDown(self):
        self.conn.close()

    def _import_mov(self, txs, tag="mov"):
        # Movimientos (import-linked) vía persist_batch + rebuild.
        allt = [NormalizedTx(row_index=-10, date="2023-11-17", broker="IOL",
                             operation_type=OP_DEPOSIT, gross_amount=5_000_000, currency="ARS")] + txs
        with self.conn:
            for i, t in enumerate(allt):
                t.row_index = -100 - i
            sid = pl.store_preview_txs(self.conn, self.uid, broker="IOL",
                                       parser_format="iol", file_name=tag, txs=allt)
            t2, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=t2,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid,
                                         tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))

    def _buy(self, tk, qty, date):
        return NormalizedTx(row_index=0, date=date, broker="IOL", operation_type=OP_BUY,
                            asset_symbol=tk, asset_type="CEDEAR", quantity=qty, unit_price=1000,
                            gross_amount=qty * 1000, currency="ARS")

    def _confirm_foto(self, ticker, seed_qty, extra=None):
        # Foto (Resumen) vía el ENDPOINT de confirm. seed BUY 'Tenencia — apertura' a la
        # fecha de la foto; `extra` = tx adicionales (ej. una VENTA de ajuste a otra fecha).
        txs = [NormalizedTx(row_index=-20, date=self.FOTO, broker="IOL", operation_type=OP_DEPOSIT,
                            gross_amount=seed_qty * 1000, currency="ARS",
                            notes="Tenencia — aporte inicial sintético (Rendi)"),
               NormalizedTx(row_index=-21, date=self.FOTO, broker="IOL", operation_type=OP_BUY,
                            asset_symbol=ticker, asset_type="CEDEAR", quantity=seed_qty, unit_price=1000,
                            gross_amount=seed_qty * 1000, currency="ARS",
                            notes=f"Tenencia — apertura {ticker} a precio de {self.FOTO} (P&L 0)")]
        if extra:
            txs += extra
        with self.conn:
            sid = pl.store_preview_txs(self.conn, self.uid, broker="IOL",
                                       parser_format="iol_tenencia", file_name="r.pdf", txs=txs)
        r = self.client.post("/api/imports/confirm",
                             headers={"Authorization": f"Bearer {self.token}"},
                             json={"session_id": sid})
        self.assertEqual(r.status_code, 200, r.text)

    def _split_check(self, splits):
        with patch.object(main, "_fetch_ba_splits", return_value=list(splits)):
            r = self.client.get("/api/positions/split-check",
                                headers={"Authorization": f"Bearer {self.token}"})
        return r.json()["suggestions"]

    def _offers(self, ticker, splits):
        return any(s["asset"] == ticker for s in self._split_check(splits))

    # ── el fix ─────────────────────────────────────────────────────────────────
    def test_split_before_foto_not_offered(self):
        self._import_mov([self._buy("NVDA", 3, "2023-11-17")])   # lote pre-split
        self._confirm_foto("NVDA", 27)                           # foto → 30 (post-split)
        self.assertFalse(self._offers("NVDA", [("2024-06-10", 10.0)]))   # ya reflejado por la foto

    def test_does_not_touch_split_adjusted_through(self):
        # #3: NO estampamos split_adjusted_through (lo consume el backfill MTM) → NULL.
        self._import_mov([self._buy("NVDA", 3, "2023-11-17")])
        self._confirm_foto("NVDA", 27)
        wms = [row["split_adjusted_through"] for row in self.conn.execute(
            "SELECT split_adjusted_through FROM positions WHERE user_id=? AND asset='NVDA' AND is_cash=0",
            (self.uid,))]
        self.assertTrue(wms and all(w is None for w in wms), wms)

    def test_durable_across_movimientos_reimport(self):
        # #2: un re-import de Movimientos (cuyo rebuild borra columnas de la posición) NO
        # reintroduce el bug — el watermark de la foto es read-time (import_normalized_tx).
        self._import_mov([self._buy("NVDA", 3, "2023-11-17")])
        self._confirm_foto("NVDA", 27)
        self.assertFalse(self._offers("NVDA", [("2024-06-10", 10.0)]))
        # segundo import de Movimientos que toca NVDA (venta parcial)
        self._import_mov([NormalizedTx(row_index=0, date="2026-07-05", broker="IOL",
                                       operation_type=OP_SELL, asset_symbol="NVDA", asset_type="CEDEAR",
                                       quantity=1, unit_price=2000, gross_amount=2000, currency="ARS")],
                         tag="mov2")
        self.assertFalse(self._offers("NVDA", [("2024-06-10", 10.0)]))   # sigue filtrado

    def test_reduction_date_does_not_inflate_watermark(self):
        # #1/#4: una VENTA de ajuste de la foto va a red_date > seed_date. El watermark de
        # NVDA debe ser su fecha de foto (seed_date), NO la de la venta → un split entre
        # ambas fechas SÍ se ofrece (no se traga por un red_date inflado).
        self._import_mov([self._buy("NVDA", 3, "2023-11-17"), self._buy("KO", 20, "2023-05-01")])
        red = NormalizedTx(row_index=-30, date="2026-07-20", broker="IOL", operation_type=OP_SELL,
                           asset_symbol="KO", asset_type="CEDEAR", quantity=5, unit_price=0.0,
                           gross_amount=0.0, currency="ARS", transfer_out=True,
                           notes=f"Tenencia — ajuste a foto de {self.FOTO}: cierre de KO a costo (P&L 0)")
        self._confirm_foto("NVDA", 27, extra=[red])              # foto NVDA 2026-06-30 + venta KO 2026-07-20
        # split de NVDA el 2026-07-10 (entre seed_date y red_date) → NO reflejado por la
        # foto (posterior a ella) → SÍ se ofrece. Con el bug (MAX=red_date) se tragaría.
        self.assertTrue(self._offers("NVDA", [("2026-07-10", 4.0)]))

    def test_split_after_foto_still_offered(self):
        self._import_mov([self._buy("NVDA", 3, "2023-11-17")])
        self._confirm_foto("NVDA", 27)
        self.assertTrue(self._offers("NVDA", [("2026-08-01", 4.0)]))     # posterior a la foto

    def test_split_within_7d_after_foto_still_offered(self):
        # Finding A del review: un split 1-7 días DESPUÉS de la foto NO se debe tragar
        # por la ventana de dedup (esa ventana es para re-logs del MISMO evento vs el
        # watermark de AJUSTE, no vs la fecha de la foto, que no es un evento de split).
        self._import_mov([self._buy("NVDA", 3, "2023-11-17")])
        self._confirm_foto("NVDA", 27)                                   # foto 2026-06-30
        self.assertTrue(self._offers("NVDA", [("2026-07-03", 4.0)]))     # 3 días después → SÍ

    def test_non_foto_asset_still_offered(self):
        self._import_mov([self._buy("KO", 5, "2023-05-01")])            # sin foto
        self.assertTrue(self._offers("KO", [("2024-06-10", 2.0)]))

    def test_adjust_ratio_noop_after_foto(self):
        # El botón "Ajustar" (adjust-ratio) también respeta la foto → no-op (no infla).
        self._import_mov([self._buy("NVDA", 3, "2023-11-17")])
        self._confirm_foto("NVDA", 27)
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='NVDA' AND is_cash=0 "
            "AND entry_date < '2024-01-01' LIMIT 1", (self.uid,)).fetchone()["id"]
        before = self.conn.execute("SELECT quantity FROM positions WHERE id=?", (pid,)).fetchone()["quantity"]
        with patch.object(main, "_fetch_ba_splits", return_value=[("2024-06-10", 10.0)]):
            r = self.client.post(f"/api/positions/{pid}/adjust-ratio",
                                 headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("already_applied"))            # no-op
        after = self.conn.execute("SELECT quantity FROM positions WHERE id=?", (pid,)).fetchone()["quantity"]
        self.assertEqual(before, after)                            # cantidad intacta


if __name__ == "__main__":
    unittest.main()
