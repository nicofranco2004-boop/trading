"""Cripto comprada en un broker ARS (ej. BTC en Cocos) toma el valor actual.

Unificación FX (2026-06): la cripto se valúa SIEMPRE como spot × factor
cripto/MEP (exchange→spot, broker AR→premium), NUNCA por un '.BA' = spot×blue.
El frontend ahora pide el símbolo BARE ('<CRIPTO>') = spot; el backend, si igual
recibe '<CRIPTO>.BA', lo resuelve a spot CRUDO (USD), sin multiplicar por el blue
— así ningún consumidor puede reconstruir spot×blue. (Antes: '<CRIPTO>.BA' se
devolvía × tc_blue; obsoleto.)

Corre con: cd backend && python3 -m pytest tests/test_crypto_ars_price.py
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

# precios USD simulados que devolvería yfinance
_YF = {"BTC-USD": 95000.0, "GGAL.BA": 4820.0, "ETH-USD": 3300.0}


def _fake_fetch_one(yf_ticker):
    return _YF.get(yf_ticker)


class CryptoArsPriceTest(unittest.TestCase):
    TC_BLUE = 1435.0

    def setUp(self):
        self.conn = main.get_db()
        for t in ("config", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("crypto@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", str(self.TC_BLUE)))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _get(self, symbols):
        # yf.download vacío → cae al fallback _fetch_one (determinístico).
        with patch.object(main.yf, "download", return_value=pd.DataFrame()), \
             patch.object(main, "_fetch_one", side_effect=_fake_fetch_one), \
             patch.object(main, "_prices_cache_get", side_effect=lambda syms: ({}, list(syms))), \
             patch.object(main, "_prices_cache_set"), \
             patch.object(main, "_resolve_ar_bond_price", return_value=None), \
             patch.object(main, "_fill_last_known_prices"):
            return main.get_prices(symbols, self.uid)

    def test_btc_ba_stays_spot_no_blue(self):
        # Unificación FX: '<c>.BA' de cripto devuelve el SPOT crudo (USD), NO × blue.
        out = self._get("BTC.BA")
        self.assertAlmostEqual(out["BTC.BA"], 95000.0, places=2)

    def test_btc_usd_broker_stays_usd(self):
        # BTC en broker USD/crypto (sin .BA) → precio USD, sin conversión.
        out = self._get("BTC")
        self.assertAlmostEqual(out["BTC"], 95000.0, places=2)

    def test_non_crypto_ars_not_converted(self):
        # GGAL.BA es un CEDEAR/acción → ya cotiza en ARS, no se multiplica por blue.
        out = self._get("GGAL.BA")
        self.assertAlmostEqual(out["GGAL.BA"], 4820.0, places=2)

    def test_mixed_request(self):
        out = self._get("BTC.BA,GGAL.BA,BTC")
        self.assertAlmostEqual(out["BTC.BA"], 95000.0, places=2)  # cripto .BA → spot crudo (sin blue)
        self.assertAlmostEqual(out["GGAL.BA"], 4820.0, places=2)  # CEDEAR ARS → sin tocar
        self.assertAlmostEqual(out["BTC"], 95000.0, places=2)     # cripto bare → spot

    def test_crypto_ba_ignores_blue_entirely(self):
        # Unificación FX: aunque el blue LIVE esté en caché, '<c>.BA' de cripto NO
        # se multiplica por el blue — queda en spot crudo. (Antes se convertía a
        # pesos con el blue live; ahora la cripto se valúa por spot×factor.)
        main._dolar_cache["data"] = {"blue": {"compra": 1480.0, "venta": 1500.0}}
        main._dolar_cache["ts"] = 9e18
        try:
            out = self._get("BTC.BA")
        finally:
            main._dolar_cache["data"] = None
            main._dolar_cache["ts"] = 0.0
        self.assertAlmostEqual(out["BTC.BA"], 95000.0, places=2)  # spot crudo, el blue NO aplica


if __name__ == "__main__":
    unittest.main()
