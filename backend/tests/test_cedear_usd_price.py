"""CEDEAR cotizado en USD por las fuentes (ej. BAC) toma el precio en pesos
correcto, computado del subyacente US × CCL ÷ ratio del cedear.

Bug reportado por un usuario Pro: el CEDEAR BAC figuraba a $9 (yfinance/data912
devuelven ~9 USD con currency=USD) cuando vale ~20.570 ARS. No alcanza con
multiplicar por un dólar (no hay dólar de ~2275). Fix: ARS = US × CCL ÷ ratio.

Corre con: cd backend && python3 -m pytest tests/test_cedear_usd_price.py
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import pandas as pd
import main

# precios USD que devolvería yfinance para los SUBYACENTES US y los .BA en ARS
_YF = {
    "BAC": 55.16,        # subyacente US (lo que usamos para el cedear roto)
    "AAPL.BA": 22050.0,  # cedear normal, ya en ARS → no se toca
    "GGAL.BA": 8270.0,   # acción AR en ARS → no se toca
}
_CCL = 1495.0


def _fake_fetch_one(yf_ticker):
    return _YF.get(yf_ticker)


class CedearUsdPriceTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("config", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cedear@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()
        # CCL live en el caché (lo que usa _display_ccl)
        main._dolar_cache["data"] = {"ccl": {"compra": 1480.0, "venta": _CCL}}
        main._dolar_cache["ts"] = 9e18

    def tearDown(self):
        main._dolar_cache["data"] = None
        main._dolar_cache["ts"] = 0.0
        self.conn.close()

    def _get(self, symbols):
        with patch.object(main.yf, "download", return_value=pd.DataFrame()), \
             patch.object(main, "_fetch_one", side_effect=_fake_fetch_one), \
             patch.object(main, "_prices_cache_get", side_effect=lambda syms: ({}, list(syms))), \
             patch.object(main, "_prices_cache_set"), \
             patch.object(main, "_resolve_ar_bond_price", return_value=None), \
             patch.object(main, "_fill_last_known_prices"):
            return main.get_prices(symbols, self.uid)

    def test_bac_cedear_computed_from_underlying(self):
        out = self._get("BAC.BA")
        # 55.16 USD × 1495 CCL ÷ 4 = 20.616,85 ARS (≈ los 20.570 reportados)
        self.assertAlmostEqual(out["BAC.BA"], 55.16 * _CCL / 4, places=2)
        # sanity: está en el orden de los 20 mil, NO en 9
        self.assertGreater(out["BAC.BA"], 19000)
        self.assertLess(out["BAC.BA"], 22000)

    def test_normal_cedear_untouched(self):
        # AAPL.BA ya viene en ARS de yfinance → NO se multiplica por CCL
        out = self._get("AAPL.BA")
        self.assertAlmostEqual(out["AAPL.BA"], 22050.0, places=2)

    def test_ar_stock_untouched(self):
        out = self._get("GGAL.BA")
        self.assertAlmostEqual(out["GGAL.BA"], 8270.0, places=2)

    def test_mixed_request(self):
        out = self._get("BAC.BA,AAPL.BA,GGAL.BA")
        self.assertAlmostEqual(out["BAC.BA"], 55.16 * _CCL / 4, places=2)  # cedear USD → US×CCL/ratio
        self.assertAlmostEqual(out["AAPL.BA"], 22050.0, places=2)          # cedear normal intacto
        self.assertAlmostEqual(out["GGAL.BA"], 8270.0, places=2)           # acción AR intacta

    def test_bac_in_map(self):
        # guard de regresión: BAC sigue en el mapa de ratios
        self.assertIn("BAC", main.CEDEAR_USD_RATIOS)
        self.assertEqual(main.CEDEAR_USD_RATIOS["BAC"], 4)


class SnapshotsJobCedearTest(unittest.TestCase):
    """El cron de snapshot diario (fetch_prices_for_symbols) también convierte el
    cedear USD-cotizado — si no, la historia del portfolio quedaba subvaluada."""

    def setUp(self):
        main._dolar_cache["data"] = {"ccl": {"compra": 1480.0, "venta": _CCL}}
        main._dolar_cache["ts"] = 9e18

    def tearDown(self):
        main._dolar_cache["data"] = None
        main._dolar_cache["ts"] = 0.0

    def _fetch(self, symbols):
        import snapshots_job

        class _FakeLast:
            index = ["BAC", "AAPL.BA", "GGAL.BA"]
            def __getitem__(self, k):
                return {"BAC": 55.16, "AAPL.BA": 22050.0, "GGAL.BA": 8270.0}[k]

        class _FakeClose:
            empty = False
            def dropna(self, how='all'):
                return self
            def __len__(self):
                return 5
            class _ILoc:
                def __getitem__(self, i):
                    return _FakeLast()
            iloc = _ILoc()

        class _FakeData:
            empty = False
            def get(self, k):
                return _FakeClose() if k == "Close" else None

        with patch.object(snapshots_job.yf, "download", return_value=_FakeData()):
            return snapshots_job.fetch_prices_for_symbols(symbols, main.CRYPTO_YF)

    def test_snapshot_converts_bac(self):
        out = self._fetch(["BAC.BA", "AAPL.BA", "GGAL.BA"])
        self.assertAlmostEqual(out["BAC.BA"], 55.16 * _CCL / 4, places=2)  # convertido
        self.assertAlmostEqual(out["AAPL.BA"], 22050.0, places=2)          # intacto
        self.assertAlmostEqual(out["GGAL.BA"], 8270.0, places=2)           # intacto


if __name__ == "__main__":
    unittest.main()
