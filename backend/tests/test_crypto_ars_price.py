"""Cripto comprada en un broker ARS (ej. BTC en Cocos) toma el valor actual en
pesos.

Bug: el frontend pide 'BTC.BA' (sufijo ARS, como un CEDEAR) pero la cripto no
cotiza en BYMA → /api/prices devolvía None → el activo caía a cost basis ("no
toma el valor actual en pesos"). Fix: el backend resuelve '<CRIPTO>.BA' como
'<CRIPTO>-USD' y lo devuelve convertido a pesos con el tc_blue del user.

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

    def test_btc_ars_converted_to_pesos(self):
        out = self._get("BTC.BA")
        # 95.000 USD × 1435 = 136.325.000 ARS
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * self.TC_BLUE, places=2)

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
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * self.TC_BLUE, places=2)  # cripto ARS → pesos
        self.assertAlmostEqual(out["GGAL.BA"], 4820.0, places=2)                  # CEDEAR ARS → sin tocar
        self.assertAlmostEqual(out["BTC"], 95000.0, places=2)                     # cripto USD → USD

    def test_uses_live_blue_over_config(self):
        # Si el blue LIVE está en caché (el mismo que usa el frontend como tcBlue),
        # la cripto se convierte con ESE, no con el tc_blue del config (1435). Así
        # sigue los updates automáticos del blue.
        # forma real de /api/dolar: blue = {compra, venta, ...} (el front usa .venta)
        main._dolar_cache["data"] = {"blue": {"compra": 1480.0, "venta": 1500.0}}
        main._dolar_cache["ts"] = 9e18
        try:
            out = self._get("BTC.BA")
        finally:
            main._dolar_cache["data"] = None
            main._dolar_cache["ts"] = 0.0
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * 1500.0, places=2)  # blue live, no config


if __name__ == "__main__":
    unittest.main()
