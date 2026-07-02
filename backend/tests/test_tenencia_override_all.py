"""Override (la foto PISA) para PPI / Cocos / Bull Market — unificado con Balanz/IEB.

Valida: (a) guards de completitud (BMB per-sección; PPI sección no reconocida) que
gatean el borrado; (b) el override vía el endpoint real para Cocos (reduce-only,
complete=False) y PPI (per-partición); (c) que Cocos NUNCA borra ausentes.

Corre con: cd backend && python3 -m pytest tests/test_tenencia_override_all.py
"""
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

import openpyxl  # noqa: E402
from importing import pipeline as pl        # noqa: E402
from importing import persister as ps        # noqa: E402
from importing import rebuild as rb          # noqa: E402
from importing import tenencia as tn         # noqa: E402
from importing.schema import NormalizedTx, OP_BUY, OP_DEPOSIT  # noqa: E402
import main                                  # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402


# ─── Unit: guards de completitud ──────────────────────────────────────────────
class BmbSectionReconcileTest(unittest.TestCase):
    def _pdf(self, cedears_total):
        return (
            "Tenencia valorizada\n"
            "Tenencias al 26/06/2026 ARS 1.000.000,00\n"
            "Acciones ARS 423.300,00\n"
            "Ticker Nombre de la Especie Cantidad Precio Importe Total\n"
            "BMA BANCO MACRO 30,00 14.110,00 423.300,00\n"
            f"Cedears ARS {cedears_total}\n"
            "Ticker Nombre de la Especie Cantidad Precio Importe Total\n"
            "MELI CEDEAR MERCADOLIBRE INC. 40,00 21.510,00 860.400,00\n")

    def test_section_that_reconciles_no_warning(self):
        snap = tn.parse_bullmarket_tenencia(self._pdf("860.400,00"))
        self.assertEqual(snap.warnings, [])

    def test_section_that_does_not_reconcile_warns(self):
        # El total declarado (500.000) NO cuadra con la fila (860.400) → OCR parcial.
        snap = tn.parse_bullmarket_tenencia(self._pdf("500.000,00"))
        self.assertTrue(any("no cuadra" in w for w in snap.warnings), snap.warnings)

    def test_small_drop_below_1pct_warns(self):
        # Un desvío del 0.5% (864.702 vs 860.400) — antes (tol 1%) NO avisaba y el
        # holding chico caído se borraba; ahora (0.1%) SÍ avisa.
        snap = tn.parse_bullmarket_tenencia(self._pdf("864.702,00"))
        self.assertTrue(any("no cuadra" in w for w in snap.warnings), snap.warnings)


class PpiSectionGuardTest(unittest.TestCase):
    HDR = ["Especie", "Descripcion", "Cant. Disponible", "Precio",
           "Valor Corriente", "Valor Moneda Cotizacion"]

    def _rows(self, section_name):
        return [
            ["Total cartera", "700000"],
            [section_name],
            list(self.HDR),
            ["GGAL", "GRUPO GALICIA", "100", "7000", "700000", "700000"],
            ["SUBTOTAL", "", "", "", "700000", ""],
        ]

    def test_known_section_no_warning(self):
        snap = tn.parse_ppi_tenencia(self._rows("ACCIONES"))
        self.assertEqual(snap.warnings, [])
        self.assertIn("GGAL", [h.ticker for h in snap.holdings])

    def test_unknown_section_warns(self):
        snap = tn.parse_ppi_tenencia(self._rows("RENTA FIJA X"))
        self.assertTrue(any("no reconocida" in w for w in snap.warnings), snap.warnings)
        self.assertNotIn("GGAL", [h.ticker for h in snap.holdings])

    def test_stray_lone_cell_midsection_is_noise(self):
        # Un page-header/footer mono-celda a MITAD de la tabla (después del header) es
        # RUIDO → NO cierra la sección: las filas que siguen se siguen leyendo y NO hay
        # warning (antes: dropeaba YPFD en silencio → complete=True → lo borraba).
        rows = [
            ["ESTADO DE CUENTA"], ["POR TIPO DE ACTIVO"], ["Total cartera", "1050000"],
            ["ACCIONES"], list(self.HDR),
            ["GGAL", "GALICIA", "100", "7000", "700000", "700000"],
            ["Pagina 2 de 3"],   # ruido mono-celda intra-sección
            ["YPFD", "YPF S.A.", "50", "7000", "350000", "350000"],
            ["SUBTOTAL", "", "", "", "1050000", ""],
        ]
        snap = tn.parse_ppi_tenencia(rows)
        tickers = [h.ticker for h in snap.holdings]
        self.assertIn("GGAL", tickers)
        self.assertIn("YPFD", tickers)          # NO se perdió
        self.assertEqual(snap.warnings, [])     # sin falso 'sección no reconocida'


# ─── E2E: override vía endpoint ───────────────────────────────────────────────
def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


class _OverrideE2EBase(unittest.TestCase):
    BROKER = "X"

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
            (f"ovr-{self.BROKER}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        self.conn.execute("INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
                          (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        self.token = main.create_token(self.uid)
        self.client = TestClient(main.app)

    def tearDown(self):
        self.conn.close()

    def _buy(self, tkr, qty, price, at="CEDEAR"):
        return NormalizedTx(row_index=0, date="2026-01-10", broker=self.BROKER,
                            operation_type=OP_BUY, asset_symbol=tkr, asset_type=at,
                            quantity=qty, unit_price=price, gross_amount=qty * price, currency="ARS")

    def _import_mov(self, txs):
        dep = NormalizedTx(row_index=0, date="2026-01-09", broker=self.BROKER,
                           operation_type=OP_DEPOSIT,
                           gross_amount=sum(t.gross_amount for t in txs) + 100000, currency="ARS")
        allt = [dep] + txs
        with self.conn:
            for i, t in enumerate(allt):
                t.row_index = -100 - i
            sid = pl.store_preview_txs(self.conn, self.uid, broker=self.BROKER,
                                       parser_format="x", file_name="mov", txs=allt)
            txs2, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs2,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)

    def _import_mov_broker(self, broker, ccy, txs):
        dep = NormalizedTx(row_index=0, date="2026-01-09", broker=broker,
                           operation_type=OP_DEPOSIT,
                           gross_amount=sum(t.gross_amount for t in txs) + 1000, currency=ccy)
        allt = [dep] + txs
        with self.conn:
            for i, t in enumerate(allt):
                t.row_index = -300 - i
            sid = pl.store_preview_txs(self.conn, self.uid, broker=broker,
                                       parser_format="x", file_name="movu", txs=allt)
            txs2, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs2,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid,
                                         tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))

    def _usd_buy(self, broker, tkr, qty, price):
        return NormalizedTx(row_index=0, date="2026-01-10", broker=broker, operation_type=OP_BUY,
                            asset_symbol=tkr, asset_type="CEDEAR", quantity=qty, unit_price=price,
                            gross_amount=qty * price, currency="USD")

    def _held(self, asset):
        r = self.conn.execute("SELECT COALESCE(SUM(quantity),0) q FROM positions "
                             "WHERE user_id=? AND asset=? AND is_cash=0", (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def _held_in(self, broker, asset):
        r = self.conn.execute("SELECT COALESCE(SUM(quantity),0) q FROM positions "
                             "WHERE user_id=? AND broker=? AND asset=? AND is_cash=0",
                             (self.uid, broker, asset)).fetchone()
        return float(r["q"] or 0)

    def _preview(self, fmt, fname, data, ctype):
        return self.client.post("/api/imports/tenencia/preview",
            headers={"Authorization": f"Bearer {self.token}"},
            data={"broker": self.BROKER, "format": fmt},
            files={"file": (fname, data, ctype)})

    def _confirm(self, sid):
        return self.client.post("/api/imports/confirm",
            headers={"Authorization": f"Bearer {self.token}"}, json={"session_id": sid})


class CocosOverrideE2E(_OverrideE2EBase):
    BROKER = "Cocos"

    def _csv(self, meli_qty):
        return ("instrumento;cantidad;precio;moneda;total\n"
                f"CEDEAR MERCADOLIBRE INC. (MELI);{meli_qty};21000;ARS;{meli_qty*21000}\n"
                "CEDEAR APPLE INC. (AAPL);20;22000;ARS;440000\n"
                "ARS;1000;1;ARS;1000\n")

    def test_reduces_but_never_removes(self):
        # Rendi: MELI 100, AAPL 20 (match), NVDA 15 (ausente en la foto).
        self._import_mov([self._buy("MELI", 100, 21000), self._buy("AAPL", 20, 22000),
                          self._buy("NVDA", 15, 12000)])
        pv = self._preview("cocos", "foto.csv", self._csv(60), "text/csv")
        self.assertEqual(pv.status_code, 200, pv.text)
        body = pv.json()
        # Cocos: reduce (MELI 100→60) pero NUNCA borra ausentes (complete=False).
        self.assertIn("MELI", {r["ticker"] for r in body["override"]["reduced"]})
        self.assertEqual(body["override"]["removed"], [])
        self._confirm(body["session_id"])
        self.assertAlmostEqual(self._held("MELI"), 60, places=3)   # reducido
        self.assertAlmostEqual(self._held("NVDA"), 15, places=3)   # NO borrado

    def test_reduces_usd_holding_in_sibling(self):
        """Cocos también pisa los holdings en DÓLARES (sibling USD): GLOB 100→60 en el
        sibling contra la foto USD (con AAPL/NVDA match). Reduce-only (no borra)."""
        SIB = "Cocos · USD"
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, SIB, "USDT")); self.conn.commit()
        self._import_mov([self._buy("MELI", 52, 21000)])            # ARS en el padre
        self._import_mov_broker(SIB, "USD", [                       # USD en el sibling
            self._usd_buy(SIB, "GLOB", 100, 50), self._usd_buy(SIB, "AAPL", 10, 200),
            self._usd_buy(SIB, "NVDA", 5, 120)])
        self.assertAlmostEqual(self._held_in(SIB, "GLOB"), 100)
        csv = ("instrumento;cantidad;precio;moneda;total\n"
               "CEDEAR MERCADOLIBRE INC. (MELI);52;21000;ARS;1092000\n"
               "CEDEAR GLOBANT (GLOB);60;50;USD;3000\n"
               "CEDEAR APPLE INC. (AAPL);10;200;USD;2000\n"
               "CEDEAR NVIDIA (NVDA);5;120;USD;600\n"
               "ARS;1000;1;ARS;1000\nUSD;10;1;USD;10\n")
        body = self._preview("cocos", "foto.csv", csv, "text/csv").json()
        self.assertIn("GLOB", {r["ticker"] for r in body["override"]["reduced"]})
        self.assertEqual(body["override"]["removed"], [])          # Cocos NUNCA borra
        self._confirm(body["session_id"])
        self.assertAlmostEqual(self._held_in(SIB, "GLOB"), 60, places=3)   # reducido en USD
        self.assertAlmostEqual(self._held_in(SIB, "AAPL"), 10, places=3)   # match, intacto


class PpiOverrideE2E(_OverrideE2EBase):
    BROKER = "PPI"
    HDR = ["Especie", "Descripcion", "Cant. Disponible", "Precio",
           "Valor Corriente", "Valor Moneda Cotizacion"]

    def _xlsx(self, meli_qty):
        wb = openpyxl.Workbook(); ws = wb.active
        rows = [
            ["ESTADO DE CUENTA"],
            ["POR TIPO DE ACTIVO"],
            ["Total cartera", "5000000"],
            ["ACCIONES"], list(self.HDR),
            ["MELI", "MERCADOLIBRE", str(meli_qty), "21000", str(meli_qty * 21000), str(meli_qty * 21000)],
            ["GGAL", "GALICIA", "50", "7000", "350000", "350000"],
            ["NVDA", "NVIDIA", "15", "12000", "180000", "180000"],
            ["SUBTOTAL", "", "", "", "0", ""],
            ["MONEDAS"], list(self.HDR),
            ["$", "Pesos", "1000", "1", "1000", "1000"],
            ["SUBTOTAL", "", "", "", "0", ""],
        ]
        for r in rows:
            ws.append(r)
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

    def test_ppi_reduces_over_per_partition(self):
        # Rendi: MELI 150 (foto 100 → over), GGAL 50 y NVDA 15 (match) → sólo MELI
        # se reduce (1 de 3 → no capea).
        self._import_mov([self._buy("MELI", 150, 21000), self._buy("GGAL", 50, 7000, at=""),
                          self._buy("NVDA", 15, 12000)])
        pv = self._preview("ppi", "foto.xlsx", self._xlsx(100),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(pv.status_code, 200, pv.text)
        body = pv.json()
        self.assertTrue(body["foto_completa"], body.get("warnings"))
        self.assertIn("MELI", {r["ticker"] for r in body["override"]["reduced"]})
        self._confirm(body["session_id"])
        self.assertAlmostEqual(self._held("MELI"), 100, places=3)   # reducido a la foto
        self.assertAlmostEqual(self._held("GGAL"), 50, places=3)    # match, intacto

    def test_cross_currency_no_duplicate_seed(self):
        # Rendi tiene AL30 100 en el PADRE (ARS). La foto lo clasifica USD (VMC≠VC) →
        # la partición USD ve gap=100. SIN el fix sembraría 100 en el sibling (total
        # 200); con el fix descuenta lo ya tenido en el par → held=100 (no duplica).
        self._import_mov([self._buy("AL30", 100, 700, at="BOND")])
        wb = openpyxl.Workbook(); ws = wb.active
        for r in [["ESTADO DE CUENTA"], ["POR TIPO DE ACTIVO"], ["Total cartera", "70000"],
                  ["BONOS"], list(self.HDR),
                  ["AL30", "BONO 2030", "100", "70", "700000", "70000"],  # VC≠VMC → USD
                  ["SUBTOTAL", "", "", "", "700000", ""]]:
            ws.append(r)
        buf = io.BytesIO(); wb.save(buf)
        pv = self._preview("ppi", "foto.xlsx", buf.getvalue(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(pv.status_code, 200, pv.text)
        self._confirm(pv.json()["session_id"])
        self.assertAlmostEqual(self._held("AL30"), 100, places=3)   # NO duplicado (×2)


if __name__ == "__main__":
    unittest.main()
