"""Una rueda que yfinance devuelve en NaN no debe servirse como precio de hoy.

Reporte real (2026-08-04): un usuario comparó su cartera contra la app de su
broker y le faltaban ~50 mil pesos en MSFT y otro tanto en AMZN. Medido: ese día
`yf.download` devolvió la barra del 03-08 de MSFT.BA y AMZN.BA **con volumen
(1,2 M y 3,3 M de nominales) pero con Close/Open/High/Low en NaN**. El fallback
per-símbolo toma el último cierre NO nulo → devolvía el del 31-07, dos ruedas
antes, mientras TSLA.BA y el resto de la tabla mostraban el del día. MSFT quedaba
en 24.340 contra 25.660 reales (−5,4%) y AMZN en 2.978 contra 3.117,50 (−4,7%).

No alcanza con mirar dentro de la barra: los cuatro campos OHLC vienen nulos.
Hace falta otra fuente — el mismo feed live de BYMA (data912) que ya se usa para
bonos — y sólo cuando yfinance falló, para no cambiarle el precio a los símbolos
que resuelve bien.

Corre con: cd backend && python3 -m pytest tests/test_ba_nan_bar.py
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
import numpy as np
import main

# La forma EXACTA de lo que devolvió yfinance ese día: MSFT.BA con la última
# barra en NaN, TSLA.BA con dato. Las dos fechas son ruedas consecutivas
# (31-07 viernes → 03-08 lunes).
_FECHAS = pd.to_datetime(["2026-07-30", "2026-07-31", "2026-08-03"])
_CLOSE = pd.DataFrame(
    {"MSFT.BA": [23600.0, 24340.0, np.nan],
     "TSLA.BA": [32280.0, 32880.0, 33940.0]},
    index=_FECHAS,
)

# Lo que devuelve el feed live de BYMA para el que yfinance se salteó.
_BYMA = {"MSFT": {"c": 25660.0, "pct": 5.42}}

# Lo que devolvería el fallback de yfinance: el último cierre no nulo = 31-07.
_STALE = {"MSFT.BA": 24340.0}


def _fake_download(*a, **k):
    return pd.concat({"Close": _CLOSE}, axis=1)


class BaNanBarTest(unittest.TestCase):
    _n = 0

    def setUp(self):
        self.conn = main.get_db()
        # Email único por test: `users.email` es UNIQUE y la base temp se comparte
        # entre los tests del módulo — con uno fijo, el primero pasa y el resto
        # revienta en setUp (y falla el test entero por una razón que no es la suya).
        BaNanBarTest._n += 1
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"nanbar{BaNanBarTest._n}@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _prices(self, symbols, byma=None):
        with patch.object(main.yf, "download", side_effect=_fake_download), \
             patch.object(main, "_fetch_one", side_effect=lambda t: _STALE.get(t)), \
             patch.object(main, "_prices_cache_get", side_effect=lambda s: ({}, list(s))), \
             patch.object(main, "_prices_cache_set"), \
             patch.object(main, "_resolve_ar_bond_price", return_value=None), \
             patch.object(main, "_fetch_data912_equities",
                          return_value=(_BYMA if byma is None else byma)), \
             patch.object(main, "_fill_last_known_prices"):
            return main.get_prices(symbols, self.uid)

    def test_la_barra_en_nan_se_sirve_del_feed_de_byma(self):
        """Lo que reportó el usuario: 24.340 (de dos ruedas antes) → 25.660."""
        out = self._prices("MSFT.BA")
        self.assertEqual(out["MSFT.BA"], 25660.0)
        self.assertNotEqual(out["MSFT.BA"], 24340.0)

    def test_el_simbolo_que_yfinance_resolvio_bien_no_se_toca(self):
        """La corrección tiene que ser quirúrgica: si yfinance trae la rueda del
        día, ese precio manda. Si no, le cambiaríamos el número a todos."""
        out = self._prices("TSLA.BA")
        self.assertEqual(out["TSLA.BA"], 33940.0)

    def test_pedido_mixto(self):
        out = self._prices("MSFT.BA,TSLA.BA")
        self.assertEqual(out["MSFT.BA"], 25660.0)
        self.assertEqual(out["TSLA.BA"], 33940.0)

    def test_sin_cobertura_en_byma_cae_al_camino_de_siempre(self):
        """Si el feed no tiene el ticker, no se inventa nada: sigue el fallback
        de yfinance (aunque el precio sea viejo, es mejor que ninguno)."""
        out = self._prices("MSFT.BA", byma={})
        self.assertEqual(out["MSFT.BA"], 24340.0)

    def test_no_toca_cripto_ni_tickers_sin_sufijo(self):
        """`BTC.BA` no cotiza en BYMA (se resuelve por BTC-USD × dólar cripto) y
        un ticker sin `.BA` viene de un broker en DÓLARES: servirle ahí el precio
        en pesos de BYMA sería un error de ~1500×."""
        self.assertIsNone(main._resolve_ar_equity_price("AAPL"))
        with patch.object(main, "_fetch_data912_equities",
                          return_value={"BTC": {"c": 1.0, "pct": 0.0}}):
            self.assertIsNone(main._resolve_ar_equity_price("BTC.BA"))

    def test_meta_marca_de_donde_salio_cada_precio(self):
        """El precio deja de ser un número pelado: viene con su fuente y su rueda.
        Ese dato es el que faltaba para que un hueco se vea en vez de pasar por
        precio de hoy."""
        out = self._prices("MSFT.BA,TSLA.BA")
        meta = out["__meta"]
        # MSFT lo rescató el feed live → no está atrasado.
        self.assertEqual(meta["MSFT.BA"]["src"], "byma")
        self.assertFalse(meta["MSFT.BA"]["stale"])
        # TSLA salió del batch de yfinance, de la rueda más nueva.
        self.assertEqual(meta["TSLA.BA"]["src"], "yf")
        self.assertEqual(meta["TSLA.BA"]["as_of"], "2026-08-03")
        self.assertFalse(meta["TSLA.BA"]["stale"])

    def test_meta_marca_stale_cuando_el_precio_es_de_una_rueda_vieja(self):
        """EL CASO QUE IMPORTA: sin cobertura de BYMA, el precio sale igual (mejor
        viejo que ninguno) pero queda MARCADO como de otra rueda. Antes salía
        idéntico a uno del día y nada lo distinguía."""
        out = self._prices("MSFT.BA", byma={})
        self.assertEqual(out["MSFT.BA"], 24340.0)
        m = out["__meta"]["MSFT.BA"]
        self.assertEqual(m["src"], "yf")
        self.assertEqual(m["as_of"], "2026-07-31")   # su última barra válida
        self.assertTrue(m["stale"])                  # el lote llegó al 03-08

    def test_prev_close_no_saltea_la_rueda(self):
        """La variación diaria tiene que comparar ruedas CONSECUTIVAS. Si el precio
        de hoy sale del feed (03-08) y el anterior se toma como `iloc[-2]` de la
        serie de yfinance, se compara contra el 30-07 y un movimiento de dos ruedas
        atrás aparece como si fuera de hoy — eso es lo que mostraba "+15,7% hoy" en
        AMZN. Para un símbolo atrasado el cierre anterior es su último dato (31-07)."""
        with patch.object(main.yf, "download", side_effect=_fake_download), \
             patch.object(main, "_prevclose_cache_get", side_effect=lambda s: ({}, list(s))), \
             patch.object(main, "_prevclose_cache_set", create=True), \
             patch.object(main, "_fetch_prev_close_one", return_value=None), \
             patch.object(main, "_fetch_data912_equities", return_value=_BYMA):
            out = main.get_prev_close("MSFT.BA,TSLA.BA", self.uid)
        # MSFT se quedó en el 31-07 → su "cierre anterior" es ese, no el del 30-07.
        self.assertEqual(out["MSFT.BA"], 24340.0)
        # TSLA está al día → cierre anterior normal (la rueda previa).
        self.assertEqual(out["TSLA.BA"], 32880.0)


if __name__ == "__main__":
    unittest.main()
