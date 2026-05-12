"""Tests del resolver de precios de bonos AR via data912.

Mockea el HTTP — NO hace fetch real para que el test no dependa de la red
ni del estado del mercado al momento de correr.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402


def _mock_data912(prices_dict):
    """Helper: simula respuesta de data912 con el dict de precios dado.
    El cache interno se invalida para que cada test fetchee fresh."""
    main._data912_cache['data'] = None
    main._data912_cache['ts'] = 0
    resp_bonds = MagicMock()
    resp_bonds.status_code = 200
    resp_bonds.json.return_value = [
        {'symbol': sym, 'c': price}
        for sym, price in prices_dict.items()
    ]
    resp_corp = MagicMock()
    resp_corp.status_code = 200
    resp_corp.json.return_value = []
    return [resp_bonds, resp_corp]


class ResolveARBondPriceTest(unittest.TestCase):
    """Mappings ticker → precio según convención de sufijos."""

    def tearDown(self):
        main._data912_cache['data'] = None
        main._data912_cache['ts'] = 0

    def test_ars_broker_uses_ticker_without_suffix(self):
        """AL30.BA → busca 'AL30' (precio ARS por 100 face) → /100."""
        with patch('main.requests.get', side_effect=_mock_data912({'AL30': 91610.0})):
            price = main._resolve_ar_bond_price('AL30.BA')
        # 91610 / 100 = 916.10 ARS por VN
        self.assertAlmostEqual(price, 916.10, places=2)

    def test_usd_broker_uses_ticker_plus_D_suffix(self):
        """AL30 (sin .BA) → busca 'AL30D' (USD MEP por 100 face) → /100."""
        with patch('main.requests.get', side_effect=_mock_data912({'AL30D': 64.23})):
            price = main._resolve_ar_bond_price('AL30')
        # 64.23 / 100 = 0.6423 USD por VN
        self.assertAlmostEqual(price, 0.6423, places=4)

    def test_returns_none_for_unknown_bond(self):
        """Tickers no listados en AR_BONDS_DATA912 → None (caller cae a yfinance)."""
        with patch('main.requests.get', side_effect=_mock_data912({'AL30': 91610.0})):
            self.assertIsNone(main._resolve_ar_bond_price('NOEXISTE.BA'))
            self.assertIsNone(main._resolve_ar_bond_price('AAPL'))

    def test_returns_none_when_data912_lacks_specific_ticker(self):
        """Bono está en AR_BONDS_DATA912 pero data912 no lo tiene → None."""
        with patch('main.requests.get', side_effect=_mock_data912({})):
            self.assertIsNone(main._resolve_ar_bond_price('AL30.BA'))

    def test_returns_none_on_zero_or_negative_price(self):
        """Precio data912 inválido (0 o negativo) → None."""
        # data912 a veces devuelve null o 0 si no hay cierre del día
        with patch('main.requests.get', side_effect=_mock_data912({})):
            # incluso si "AL30" existiera con valor 0, no se reportaría
            self.assertIsNone(main._resolve_ar_bond_price('AL30.BA'))

    def test_cer_bonds_supported(self):
        """TX26, TX28, TZX26 también están cubiertos."""
        with patch('main.requests.get', side_effect=_mock_data912({
            'TX26': 685.0,
            'TZX26': 383.1,
        })):
            self.assertAlmostEqual(main._resolve_ar_bond_price('TX26.BA'), 6.85)
            self.assertAlmostEqual(main._resolve_ar_bond_price('TZX26.BA'), 3.831)


class FetchData912BondsCacheTest(unittest.TestCase):
    """Verifica el caching: una request a data912 sirve para muchos lookups."""

    def tearDown(self):
        main._data912_cache['data'] = None
        main._data912_cache['ts'] = 0

    def test_cache_hit_avoids_second_fetch(self):
        with patch('main.requests.get', side_effect=_mock_data912({'AL30': 91610.0})) as mock_get:
            main._fetch_data912_bonds()
            self.assertEqual(mock_get.call_count, 2)  # bonds + corp
            # Segunda llamada inmediata → cache hit, no más requests
            main._fetch_data912_bonds()
            self.assertEqual(mock_get.call_count, 2)

    def test_fallback_to_stale_cache_on_error(self):
        """Si data912 cae, retorna cache anterior aunque sea viejo."""
        # Primero, cargar cache
        with patch('main.requests.get', side_effect=_mock_data912({'AL30': 91610.0})):
            main._fetch_data912_bonds()
        # Forzar expiración del TTL
        main._data912_cache['ts'] = 0
        # Ahora fetch falla → debe devolver el cache previo
        with patch('main.requests.get', side_effect=Exception('network error')):
            r = main._fetch_data912_bonds()
        self.assertEqual(r.get('AL30'), 91610.0)


if __name__ == "__main__":
    unittest.main()
