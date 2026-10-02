"""Una sola regla de "¿esto es argentino?", la misma en la pantalla y en el servidor.

El servidor decidía "esto es argentino" en varios lugares, cada uno con su lista:
el diagnóstico de sesgo local (behavioral, 24 tickers), el análisis de Rendi AI
por país (ai/builders/insights, 45), los sectores (behavioral), los grupos del
asesor y el perfil de Rendi AI (su propia lista de prefijos de bonos). Ninguna
coincidía con la de la pantalla (frontend/src/utils/tickers.js, 64):
  - una cartera 100 % Telecom (TECO2) en Cocos salía "Casi sin exposición a
    Argentina" (0 %), porque TECO2 no estaba en la lista del diagnóstico;
  - TEN (Tsakos, una naviera griega) contaba como 100 % argentina;
  - Rendi AI clasificaba PAM en Schwab y GGAL.BA en Cocos como "us", y a Texas
    Instruments o GDX como argentinas por las dos primeras letras.

La primera versión del arreglo igualó la LISTA pero no la REGLA, y la auditoría
encontró que rompía casos que andaban: CELU o BOLT en Schwab (empresas de
EE.UU. con el mismo ticker) y la cripto ROSE pasaban a ser "100 % Argentina", y
PCAR (que en BYMA hoy es el CEDEAR de PACCAR) también. La regla de ahora es la
de la pantalla (frontend/src/utils/assetClass.js): primero qué es (cripto,
bono, letra), después en qué mercado está. Un ticker del panel argentino es
argentino sólo si la tenencia está en la bolsa argentina; sus ADRs (YPF, PAM,
GGAL) en cualquier broker.

Las pruebas pasan por las funciones de producción (detect_home_bias,
_classify_geography, _sector_for, el perfil de Rendi AI y el importador), no
por la lista suelta.
"""
import os
import re
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from ai.trade_tickers import AR_STOCK_TICKERS  # noqa: E402
from behavioral import (  # noqa: E402
    detect_home_bias, detect_sector_concentration, es_accion_argentina,
    _sector_for, _AR_ADRS, _SECTOR_AR_PANTALLA,
)
from ai.builders.insights import _classify_geography  # noqa: E402
from ai.builders.profile_card import _build_card_data  # noqa: E402
from importing.schema import RawRow  # noqa: E402
from importing.normalizer import normalize_rows  # noqa: E402

FRONT = os.path.join(BACKEND, '..', 'frontend', 'src', 'utils')
TICKERS_JS = os.path.join(FRONT, 'tickers.js')
SECTOR_JS = os.path.join(FRONT, 'assetSector.js')

ADRS = sorted(_AR_ADRS)
LISTA = sorted(AR_STOCK_TICKERS)


def _bloque(src, nombre):
    m = re.search(r'export const %s = \[(.*?)\n\]' % nombre, src, re.S)
    assert m, f'no encontré {nombre} en tickers.js'
    return m.group(1)


def _lista_de_la_pantalla():
    """Los `s:` de ARG_LIDER y ARG_GENERAL en tickers.js, con comillas simples
    o dobles. Si un bloque tiene un `s:` que el lector no entiende, rojo: si
    no, una acción escrita con otro formato quedaba en la pantalla y no en el
    servidor sin que nadie se enterara."""
    src = open(TICKERS_JS, encoding='utf-8').read()
    out = set()
    for nombre in ('ARG_LIDER', 'ARG_GENERAL'):
        bloque = _bloque(src, nombre)
        leidos = re.findall(r"""\bs:\s*['"]([A-Z0-9.]+)['"]""", bloque)
        assert len(leidos) == len(re.findall(r'\bs:', bloque)), \
            f'{nombre}: hay una entrada `s:` que no se pudo leer'
        out |= set(leidos)
    return out


def _sectores_de_la_pantalla():
    """ticker → clave de sector de assetSector.js (los bloques ...M('clave', [...]))."""
    src = open(SECTOR_JS, encoding='utf-8').read()
    out = {}
    for clave, cuerpo in re.findall(r"\.\.\.M\('(\w+)',\s*\[(.*?)\]\)", src, re.S):
        sin_comentarios = re.sub(r'//[^\n]*', '', cuerpo)
        for t in re.findall(r"""['"]([A-Z0-9.]+)['"]""", sin_comentarios):
            out.setdefault(t, clave)
    assert len(out) > 300, 'no pude leer el mapa de sectores de la pantalla'
    return out


def _pos(asset, broker='Cocos', currency=None, asset_type=None, invested=3_000_000):
    if currency is None:
        currency = 'ARS' if broker in ('Cocos', 'Santander') else 'USD'
    return {'broker': broker, 'asset': asset, 'is_cash': 0, 'quantity': 100,
            'invested': invested, 'currency': currency, 'asset_type': asset_type}


def _ar_pct(asset, broker='Cocos', **kw):
    if broker not in ('Cocos', 'Santander') and 'invested' not in kw:
        kw['invested'] = 3000
    r = detect_home_bias([_pos(asset, broker, **kw)])
    return r['evidence']['ar_pct']


def _pais(asset, broker='Cocos', **kw):
    return _classify_geography(_pos(asset, broker, **kw))


class UnaSolaLista(unittest.TestCase):
    def test_el_servidor_tiene_la_misma_lista_que_la_pantalla(self):
        pantalla = _lista_de_la_pantalla()
        self.assertGreaterEqual(len(pantalla), 64)
        self.assertEqual(LISTA, sorted(pantalla))

    def test_pcar_no_es_argentina(self):
        # Petrolera Pampa ya no cotiza: PCAR en BYMA es el CEDEAR de PACCAR.
        self.assertNotIn('PCAR', AR_STOCK_TICKERS)
        self.assertLess(_ar_pct('PCAR'), 5)
        self.assertLess(_ar_pct('PCAR.BA'), 5)

    def test_en_la_bolsa_argentina_cuentan_todas(self):
        for t in LISTA:
            self.assertTrue(es_accion_argentina(t, en_byma=True), t)
            self.assertTrue(es_accion_argentina(t + '.BA'), t + '.BA')

    def test_fuera_de_la_bolsa_argentina_solo_los_adrs(self):
        # GGAL, BMA, BBAR… tienen el MISMO código en BYMA y en Nueva York.
        for t in sorted(set(LISTA) - set(ADRS)):
            self.assertFalse(es_accion_argentina(t, en_byma=False), t)
        for t in ADRS:
            self.assertTrue(es_accion_argentina(t, en_byma=False), t)


class LasDeLaListaPorLosTresCaminos(unittest.TestCase):
    """Las 67, con y sin .BA, y los ADRs, por los caminos de producción. Antes
    cada lugar se probaba con 2 o 3 tickers, y una lista propia que cubriera
    justo esos pasaba en verde."""

    def test_sesgo_local(self):
        for t in LISTA:
            self.assertGreater(_ar_pct(t), 95, t)
            self.assertGreater(_ar_pct(t + '.BA'), 95, t + '.BA')
        for t in ADRS:
            self.assertGreater(_ar_pct(t, broker='Schwab'), 95, t)

    def test_rendi_ai_por_pais(self):
        for t in LISTA:
            self.assertEqual(_pais(t), 'ar', t)
            self.assertEqual(_pais(t + '.BA'), 'ar', t + '.BA')
        for t in ADRS:
            self.assertEqual(_pais(t, 'Schwab'), 'ar', t)

    def test_sectores(self):
        for t in LISTA:
            for a in (t, t + '.BA'):
                s = _sector_for(a, True)
                self.assertTrue(s.startswith('AR · '), (a, s))
                self.assertNotIn(s, ('AR · Acciones', 'AR · CEDEAR'), a)
                self.assertFalse(s.startswith('AR · CEDEAR'), (a, s))


class SesgoLocal(unittest.TestCase):
    """El diagnóstico de "sesgo local", por su camino de producción."""

    def test_una_cartera_toda_en_telecom_es_argentina(self):
        self.assertGreater(_ar_pct('TECO2'), 95)

    def test_ten_no_es_argentina(self):
        # TEN es Tsakos Energy Navigation; Ternium Argentina en BYMA es TXAR.
        self.assertLess(_ar_pct('TEN', broker='Schwab'), 5)
        self.assertGreater(_ar_pct('TXAR'), 95)

    def test_un_cedear_sigue_siendo_internacional(self):
        self.assertLess(_ar_pct('AAPL.BA'), 5)
        self.assertLess(_ar_pct('AAPL', asset_type='CEDEAR'), 5)

    def test_adrs_en_un_broker_del_exterior(self):
        for t in ('PAM', 'YPF', 'GGAL'):
            self.assertGreater(_ar_pct(t, broker='Schwab'), 95, t)

    def test_mismo_ticker_en_eeuu_no_es_argentina(self):
        # CELU (Celularity), BOLT (Bolt Biotherapeutics), SEMI, HAVA en Schwab.
        for t in ('CELU', 'BOLT', 'SEMI', 'HAVA'):
            self.assertLess(_ar_pct(t, broker='Schwab'), 5, t)

    def test_broker_en_pesos_que_no_esta_en_la_lista_de_nombres(self):
        # La cuenta en pesos se reconoce por la moneda, no por el nombre.
        for t in ('GGAL', 'TECO2'):
            self.assertGreater(_ar_pct(t, broker='Santander'), 95, t)

    def test_la_cripto_rose_no_es_el_instituto_rosenbusch(self):
        self.assertLess(_ar_pct('ROSE', broker='Binance', currency='USDT',
                                asset_type='CRYPTO'), 5)
        # Comprada en un exchange en pesos: el tipo que puso el importador manda.
        self.assertLess(_ar_pct('ROSE', broker='Santander', asset_type='CRYPTO'), 5)
        self.assertGreater(_ar_pct('ROSE'), 95)            # en Cocos: la acción

    def test_letras_y_obligaciones_negociables(self):
        self.assertGreater(_ar_pct('S31E5'), 95)            # LECAP
        self.assertGreater(_ar_pct('YMCJO', asset_type='ON'), 95)
        self.assertGreater(_ar_pct('AL30'), 95)
        # Un bono del Tesoro de EE.UU. en Schwab no es deuda argentina.
        self.assertLess(_ar_pct('US912828', broker='Schwab', asset_type='BOND'), 5)

    def test_texas_instruments_y_gdx_no_son_bonos_argentinos(self):
        for t in ('TXN', 'GD', 'GDX', 'ALL', 'AEM'):
            self.assertLess(_ar_pct(t, broker='Schwab'), 5, t)


class RendiAIPorPais(unittest.TestCase):
    def test_acciones_y_adrs_argentinos_son_ar(self):
        self.assertEqual(_pais('TECO2'), 'ar')
        self.assertEqual(_pais('GGAL.BA'), 'ar')
        self.assertEqual(_pais('PAM', 'Schwab'), 'ar')
        self.assertEqual(_pais('GGAL', 'Santander'), 'ar')

    def test_un_cedear_es_us(self):
        self.assertEqual(_pais('AAPL.BA'), 'us')
        self.assertEqual(_pais('TEN', 'Schwab'), 'us')

    def test_prefijos_sin_numero_no_son_bonos(self):
        for t in ('TXN', 'GD', 'GDX', 'ALL', 'AEM', 'CELU', 'BOLT'):
            self.assertEqual(_pais(t, 'Schwab'), 'us', t)
        self.assertNotEqual(_pais('ALGO', 'Kraken', asset_type='CRYPTO'), 'ar')

    def test_deuda_argentina_es_ar(self):
        self.assertEqual(_pais('S31E5'), 'ar')
        self.assertEqual(_pais('YMCJO', asset_type='ON'), 'ar')
        self.assertEqual(_pais('TX26'), 'ar')


class Sectores(unittest.TestCase):
    def test_una_accion_argentina_no_es_un_cedear(self):
        self.assertEqual(_sector_for('GGAL.BA'), 'AR · Financials')
        self.assertEqual(_sector_for('TECO2'), 'AR · Communication')
        self.assertEqual(_sector_for('AAPL.BA').split(' (')[0], 'AR · CEDEAR')

    def test_el_adr_y_la_accion_local_tienen_el_mismo_sector(self):
        self.assertEqual(_sector_for('YPF', False), _sector_for('YPFD', True))
        self.assertEqual(_sector_for('TEO', False), _sector_for('TECO2', True))

    def test_mismo_reparto_que_la_torta_de_la_pantalla(self):
        pantalla = _sectores_de_la_pantalla()
        servidor = {t: clave for clave, ts in _SECTOR_AR_PANTALLA.items() for t in ts}
        for t in LISTA + ADRS:
            self.assertIn(t, servidor, f'{t} sin sector en el servidor')
            self.assertEqual(servidor[t], pantalla.get(t), t)

    def test_cuatro_empresas_de_cuatro_sectores_no_son_concentracion(self):
        # Antes: "Concentración fuerte en AR · Acciones 100 %".
        r = detect_sector_concentration(
            [_pos(t) for t in ('TECO2', 'IRSA', 'MOLI', 'GGAL')], tc_blue=1000)
        self.assertEqual(r['evidence']['total_sectors'], 4)
        self.assertNotIn('AR · Acciones', r['title'])

    def test_la_cripto_rose_no_tiene_sector_argentino(self):
        r = detect_sector_concentration(
            [_pos('ROSE', 'Santander', asset_type='CRYPTO')], tc_blue=1000)
        self.assertFalse(r['evidence']['top_sector'].startswith('AR · '))


class PerfilDeRendiAI(unittest.TestCase):
    """La renta fija del perfil de Rendi AI = "Bonos y letras" de la torta."""

    def _renta_fija(self, *posiciones):
        card = _build_card_data('allocation', {}, list(posiciones), [], [], None, 1,
                                1000.0, 1000.0)
        return card['actual']['buckets_pct']['fixed_income']

    def test_letras_ons_y_soberanos_son_renta_fija(self):
        for p in (_pos('S31E5'), _pos('YMCJO', asset_type='ON'), _pos('AL30D'),
                  _pos('TX26'), _pos('TO26')):
            self.assertEqual(self._renta_fija(p), 100, p['asset'])

    def test_acciones_y_fondos_no(self):
        for p in (_pos('TGSU2'), _pos('TGNO4'), _pos('TXN', 'Schwab'),
                  _pos('SPY', 'Schwab'), _pos('FCI:BALANZ-AHORRO')):
            self.assertEqual(self._renta_fija(p), 0, p['asset'])


class PataDolarEnElImportador(unittest.TestCase):
    """La pata en dólares de una acción argentina se guarda como la acción, por
    el mismo camino que una importación real (normalize_rows), también cuando el
    archivo no dice el tipo (IEB)."""

    def _guardado(self, activo, moneda='USD', tipo=''):
        fila = RawRow(row_index=1, data={
            "fecha": "2026-03-10", "tipo": "VENTA", "broker": "IEB", "activo": activo,
            "cantidad": "100", "precio": "4", "monto": "", "monto_usd": "", "tc": "",
            "comisiones": "0", "moneda": moneda, "asset_type": tipo, "asset_name": activo,
            "notas": ""})
        out, errs = normalize_rows([fila])
        self.assertEqual(errs, [])
        return out[0].asset_symbol

    def test_telecom_y_las_gasiferas(self):
        # En BYMA la D reemplaza el número: TECO2 → TECOD, TGNO4 → TGN4D.
        self.assertEqual(self._guardado('TECOD'), 'TECO2')
        self.assertEqual(self._guardado('TGSUD'), 'TGSU2')
        self.assertEqual(self._guardado('TGN4D', tipo='STOCK'), 'TGNO4')

    def test_sin_tipo_tambien_se_junta(self):
        self.assertEqual(self._guardado('GGALD'), 'GGAL')
        self.assertEqual(self._guardado('YPFDD'), 'YPFD')
        self.assertEqual(self._guardado('PAMPC'), 'PAMP')

    def test_lo_que_termina_en_d_de_verdad_no_se_toca(self):
        self.assertEqual(self._guardado('YPFD', 'ARS'), 'YPFD')
        self.assertEqual(self._guardado('CARC', 'ARS'), 'CARC')
        self.assertEqual(self._guardado('AMD'), 'AMD')
        self.assertEqual(self._guardado('GGALD', tipo='FUND'), 'GGALD')


if __name__ == '__main__':
    unittest.main()
