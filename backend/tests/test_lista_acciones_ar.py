"""Una sola lista de acciones argentinas, la misma en la pantalla y en el servidor.

El servidor decidía "esto es argentino" en TRES lugares, cada uno con su lista:
el diagnóstico de sesgo local (behavioral, 24 tickers), el análisis de Rendi AI
por país (ai/builders/insights, 45) y los sectores (behavioral). Ninguna
coincidía con la de la pantalla (frontend/src/utils/tickers.js, 64):
  - una cartera 100 % Telecom (TECO2) en Cocos salía "Casi sin exposición a
    Argentina" (0 %), porque TECO2 no estaba en la lista del diagnóstico;
  - TEN (Tsakos, una naviera griega) contaba como 100 % argentina;
  - Rendi AI clasificaba PAM en Schwab y GGAL.BA en Cocos como "us".
Ahora los tres usan behavioral.es_accion_argentina, que lee
ai/trade_tickers.AR_STOCK_TICKERS, y esa lista se compara acá con la pantalla.
Las pruebas pasan por las funciones de producción (detect_home_bias,
_classify_geography, _sector_for), no por la lista suelta.
"""
import os
import re
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from ai.trade_tickers import AR_STOCK_TICKERS  # noqa: E402
from behavioral import detect_home_bias, es_accion_argentina, _sector_for  # noqa: E402
from ai.builders.insights import _classify_geography  # noqa: E402

TICKERS_JS = os.path.join(BACKEND, '..', 'frontend', 'src', 'utils', 'tickers.js')


def _lista_de_la_pantalla():
    """Los `s:` de ARG_LIDER y ARG_GENERAL en tickers.js."""
    src = open(TICKERS_JS, encoding='utf-8').read()
    out = set()
    for nombre in ('ARG_LIDER', 'ARG_GENERAL'):
        m = re.search(r'export const %s = \[(.*?)\n\]' % nombre, src, re.S)
        assert m, f'no encontré {nombre} en tickers.js'
        out |= set(re.findall(r"\{ s: '([A-Z0-9.]+)'", m.group(1)))
    return out


def _ar_pct(asset, broker='Cocos', invested=3_000_000):
    r = detect_home_bias([{'broker': broker, 'asset': asset, 'is_cash': 0,
                           'quantity': 100, 'invested': invested}])
    return r['evidence']['ar_pct']


class UnaSolaLista(unittest.TestCase):
    def test_el_servidor_tiene_la_misma_lista_que_la_pantalla(self):
        pantalla = _lista_de_la_pantalla()
        self.assertGreaterEqual(len(pantalla), 64)
        self.assertEqual(sorted(AR_STOCK_TICKERS), sorted(pantalla))

    def test_todas_las_de_la_lista_cuentan_como_argentinas(self):
        for t in sorted(AR_STOCK_TICKERS):
            self.assertTrue(es_accion_argentina(t), t)
            self.assertTrue(es_accion_argentina(t + '.BA'), t + '.BA')


class SesgoLocal(unittest.TestCase):
    """El diagnóstico de "sesgo local", por su camino de producción."""

    def test_una_cartera_toda_en_telecom_es_argentina(self):
        self.assertGreater(_ar_pct('TECO2'), 95)

    def test_con_o_sin_ba(self):
        self.assertGreater(_ar_pct('PAMP.BA'), 95)
        self.assertGreater(_ar_pct('MOLI'), 95)

    def test_ten_no_es_argentina(self):
        # TEN es Tsakos Energy Navigation; Ternium Argentina en BYMA es TXAR.
        self.assertLess(_ar_pct('TEN', broker='Schwab', invested=3000), 5)
        self.assertGreater(_ar_pct('TXAR'), 95)

    def test_un_cedear_sigue_siendo_internacional(self):
        self.assertLess(_ar_pct('AAPL.BA'), 5)


class RendiAIPorPais(unittest.TestCase):
    def test_acciones_y_adrs_argentinos_son_ar(self):
        self.assertEqual(_classify_geography('TECO2', 'cocos'), 'ar')
        self.assertEqual(_classify_geography('GGAL.BA', 'cocos'), 'ar')
        self.assertEqual(_classify_geography('PAM', 'schwab'), 'ar')

    def test_un_cedear_es_us(self):
        self.assertEqual(_classify_geography('AAPL.BA', 'cocos'), 'us')
        self.assertEqual(_classify_geography('TEN', 'schwab'), 'us')


class Sectores(unittest.TestCase):
    def test_una_accion_argentina_no_es_un_cedear(self):
        self.assertEqual(_sector_for('GGAL.BA'), 'AR · Financials')
        self.assertEqual(_sector_for('TECO2'), 'AR · Acciones')
        self.assertEqual(_sector_for('AAPL.BA').split(' (')[0], 'AR · CEDEAR')


if __name__ == '__main__':
    unittest.main()
