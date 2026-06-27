"""Cripto comprada en un broker ARS (ej. BTC en Cocos) toma el valor actual en
pesos al DÓLAR CRIPTO.

Bug original: el frontend pide 'BTC.BA' (sufijo ARS, como un CEDEAR) pero la
cripto no cotiza en BYMA → /api/prices devolvía None → el activo caía a cost
basis. Fix: el backend resuelve '<CRIPTO>.BA' como '<CRIPTO>-USD' y lo devuelve
convertido a pesos.

Regla del dólar (2026-06): la cripto de un BROKER AR se muestra al DÓLAR CRIPTO,
no al blue ni al MEP. Por eso prices['<c>.BA'] = spot × dólar-cripto. La
valuación divide ese precio por el MEP (cedearRate) → spot × (cripto/MEP) = el
premium cripto/MEP que muestra el broker. Cascada del rate en el backend:
_current_cripto_rate() → _current_cedear_rate() (MEP, sin premium) → blue (frío).

Las aserciones load-bearing patchean _current_cripto_rate/_current_cedear_rate
directamente (test hermético, inmune a polución de _dolar_cache por otros tests
en corridas grandes). `test_reads_live_dolar_cache` cubre aparte la integración
caché→rate sin patchear.

Corre con: cd backend && python3 -m pytest tests/test_crypto_ars_price.py
"""
import contextlib
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
_SENTINEL = object()


def _fake_fetch_one(yf_ticker):
    return _YF.get(yf_ticker)


class CryptoArsPriceTest(unittest.TestCase):
    TC_BLUE = 1435.0     # config + caché.blue (fallback final de la cascada)
    TC_MEP = 1480.0      # dólar MEP (cedearRate) — sin premium
    TC_CRIPTO = 1520.0   # dólar cripto (> MEP → premium del broker)

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
        main._dolar_cache["data"] = None
        main._dolar_cache["ts"] = 0.0
        self.conn.close()

    def _get(self, symbols, cripto=_SENTINEL, cedear=_SENTINEL):
        """get_prices con yfinance/cachés mockeados. Si se pasan `cripto`/`cedear`,
        patchea _current_cripto_rate / _current_cedear_rate (test hermético). Si no,
        usa la implementación real (lee _dolar_cache)."""
        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(main.yf, "download", return_value=pd.DataFrame()))
            st.enter_context(patch.object(main, "_fetch_one", side_effect=_fake_fetch_one))
            st.enter_context(patch.object(main, "_prices_cache_get", side_effect=lambda syms: ({}, list(syms))))
            st.enter_context(patch.object(main, "_prices_cache_set"))
            st.enter_context(patch.object(main, "_resolve_ar_bond_price", return_value=None))
            st.enter_context(patch.object(main, "_fill_last_known_prices"))
            if cripto is not _SENTINEL:
                st.enter_context(patch.object(main, "_current_cripto_rate", return_value=cripto))
            if cedear is not _SENTINEL:
                st.enter_context(patch.object(main, "_current_cedear_rate", return_value=cedear))
            return main.get_prices(symbols, self.uid)

    def test_btc_ars_at_cripto_rate(self):
        # BTC en broker AR → pesos al DÓLAR CRIPTO (no blue, no MEP).
        out = self._get("BTC.BA", cripto=self.TC_CRIPTO)
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * self.TC_CRIPTO, places=2)

    def test_btc_usd_broker_stays_usd(self):
        # BTC en broker USD/crypto (sin .BA) → precio USD, sin conversión.
        out = self._get("BTC", cripto=self.TC_CRIPTO)
        self.assertAlmostEqual(out["BTC"], 95000.0, places=2)

    def test_non_crypto_ars_not_converted(self):
        # GGAL.BA es un CEDEAR/acción → ya cotiza en ARS, no se multiplica.
        out = self._get("GGAL.BA", cripto=self.TC_CRIPTO)
        self.assertAlmostEqual(out["GGAL.BA"], 4820.0, places=2)

    def test_mixed_request(self):
        out = self._get("BTC.BA,GGAL.BA,BTC", cripto=self.TC_CRIPTO)
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * self.TC_CRIPTO, places=2)  # cripto ARS → ×cripto
        self.assertAlmostEqual(out["GGAL.BA"], 4820.0, places=2)                    # CEDEAR ARS → sin tocar
        self.assertAlmostEqual(out["BTC"], 95000.0, places=2)                       # cripto USD → USD

    def test_premium_realized_when_divided_by_mep(self):
        # El precio en pesos (spot×cripto), al dividirse por el MEP en la valuación,
        # da el premium cripto/MEP. Verifica la cadena completa que ve el usuario.
        out = self._get("BTC.BA", cripto=self.TC_CRIPTO)
        usd_visto = out["BTC.BA"] / self.TC_MEP
        esperado = 95000.0 * (self.TC_CRIPTO / self.TC_MEP)  # spot × premium
        self.assertAlmostEqual(usd_visto, esperado, places=2)
        self.assertGreater(usd_visto, 95000.0)  # premium > spot (cripto > MEP)

    def test_fallback_to_mep_when_no_cripto(self):
        # Sin dólar cripto → cae al MEP (cedearRate). Sin premium (factor 1).
        out = self._get("BTC.BA", cripto=None, cedear=self.TC_MEP)
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * self.TC_MEP, places=2)

    def test_fallback_to_blue_when_no_cripto_no_mep(self):
        # Sin cripto ni MEP → último escalón: blue (caché frío → config 1435).
        out = self._get("BTC.BA", cripto=None, cedear=None)
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * self.TC_BLUE, places=2)

    def test_reads_live_dolar_cache(self):
        # Integración (SIN patchear los rates): get_prices consulta de verdad
        # _current_cripto_rate → _dolar_cache. Forma real de /api/dolar: casa={venta}.
        main._dolar_cache["data"] = {"cripto": {"venta": 1600.0},
                                     "mep": {"venta": self.TC_MEP},
                                     "blue": {"venta": self.TC_BLUE}}
        main._dolar_cache["ts"] = 9e18
        out = self._get("BTC.BA")
        self.assertAlmostEqual(out["BTC.BA"], 95000.0 * 1600.0, places=2)  # usa el cripto del caché


if __name__ == "__main__":
    unittest.main()
