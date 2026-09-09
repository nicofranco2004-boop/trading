"""Premium dólar-cripto: SOLO para la cripto de una cuenta EN PESOS, cuyo valor
natural son pesos (spot×dólar-cripto) y pasa a USD por el MEP como el resto de la
app — factor cripto/MEP a valor Y costo, P&L% invariante. En una cuenta EN DÓLARES
(y en un EXCHANGE) el factor es 1: la persona puso dólares, el broker le muestra
dólares y no hubo pesos que convertir.

Hasta 2026-09-09 el premium se aplicaba por "broker argentino" sin mirar la moneda
de la cuenta. Un usuario con un broker argentino y saldo en dólares veía USD 2.956
contra los USD 2.840 de su broker, y un "Invertido" ~4% mayor al que había puesto.
Ver test_reporte_2026_09_09.

Cubre el factor, behavioral._position_value_usd y snapshots_job.compute_broker_value_usd,
y la PARIDAD entre los dos (no deben divergir)."""
import unittest

import main
import behavioral
import snapshots_job

CRIPTO, MEP, BLUE = 1554.0, 1499.0, 1530.0
SPOT, QTY, COST = 59281.0, 0.0114, 700.0
PREMIUM = CRIPTO / MEP  # ~1.0367


def _set_dolar(cripto=CRIPTO, mep=MEP, blue=BLUE):
    d = {'blue': {'venta': blue}, 'mep': {'venta': mep}}
    if cripto:
        d['cripto'] = {'venta': cripto}
    main._dolar_cache['data'] = d


def _btc(broker, **kw):
    """Lote de BTC. Por default en una cuenta EN DÓLARES (currency USDT)."""
    p = {'asset': 'BTC', 'broker': broker, 'currency': 'USDT',
         'quantity': QTY, 'invested': COST, 'is_cash': 0}
    p.update(kw)
    return p


def _btc_ars(broker, **kw):
    """El MISMO lote comprado con PESOS: mismo costo económico (COST × MEP pesos)."""
    return _btc(broker, currency='ARS', invested=COST * MEP, **kw)


class CryptoBrokerFactorTest(unittest.TestCase):
    def test_factor_cases(self):
        # OJO: todo caso que espere 1.0 por OTRO motivo (exchange, no-cripto,
        # override, rate faltante) pasa 'ARS' igual. Sin la moneda el factor
        # devuelve 1.0 sólo por eso y el caso quedaría verde sin ejercitar nunca
        # su propio mecanismo — verde por la razón equivocada.
        f = main.crypto_broker_factor
        self.assertAlmostEqual(f('BTC', 'Cocos', False, CRIPTO, MEP, 'ARS'), PREMIUM)
        self.assertEqual(f('BTC', 'Binance', False, CRIPTO, MEP, 'ARS'), 1.0)  # exchange
        self.assertEqual(f('AAPL', 'Cocos', False, CRIPTO, MEP, 'ARS'), 1.0)   # no-cripto
        self.assertEqual(f('CVX', 'Cocos', False, CRIPTO, MEP, 'ARS'), 1.0)    # colisión (no cripto)
        self.assertEqual(f('BTC', 'Cocos', True, CRIPTO, MEP, 'ARS'), 1.0)     # override
        self.assertEqual(f('BTC', 'Cocos', False, None, MEP, 'ARS'), 1.0)      # sin cripto
        self.assertEqual(f('BTC', 'Cocos', False, CRIPTO, 0, 'ARS'), 1.0)      # sin mep

    def test_cuenta_en_dolares_no_lleva_premium(self):
        """Un broker ARGENTINO con saldo en dólares: no hubo pesos que convertir."""
        f = main.crypto_broker_factor
        self.assertEqual(f('BTC', 'Cocos', False, CRIPTO, MEP, 'USD'), 1.0)
        self.assertEqual(f('BTC', 'Cocos', False, CRIPTO, MEP, 'USDT'), 1.0)
        self.assertEqual(f('BTC', 'Cocos', False, CRIPTO, MEP, ' usd '), 1.0)

    def test_sin_moneda_de_cuenta_no_infla(self):
        """Omitir la moneda cae al lado conservador (1.0), nunca al que infla."""
        self.assertEqual(main.crypto_broker_factor('BTC', 'Cocos', False, CRIPTO, MEP), 1.0)

    def test_reporte_2026_09_09(self):
        """Números exactos del usuario y los dólares de ese día."""
        qty, spot = 0.03637049, 78110.70
        cripto, mep = 1591.56, (1528.8 + 1530) / 2
        # Lo que Rendi mostraba: el premium aplicado a una cuenta en dólares.
        self.assertAlmostEqual(qty * spot * (cripto / mep), 2956.39, places=2)
        # Lo que muestra su broker, y lo que Rendi muestra ahora.
        f = main.crypto_broker_factor('BTC', 'Cocos', False, cripto, mep, 'USDT')
        self.assertAlmostEqual(qty * spot * f, 2840.92, places=2)

    def test_is_exchange(self):
        self.assertTrue(main.is_exchange_broker('Binance'))
        self.assertTrue(main.is_exchange_broker('  ripio '))
        self.assertFalse(main.is_exchange_broker('Cocos'))
        self.assertFalse(main.is_exchange_broker('Balanz'))
        self.assertFalse(main.is_exchange_broker('lemon'))  # ARS, no exchange


class PositionValueCryptoTest(unittest.TestCase):
    def setUp(self):
        self._orig_dolar = main._dolar_cache.get('data')
        _set_dolar()

    def tearDown(self):
        main._dolar_cache['data'] = self._orig_dolar  # no contaminar el global a otros tests

    def test_cuenta_en_dolares_sin_premium(self):
        """Broker argentino, saldo en dólares: valor a spot y costo tal cual se puso."""
        v = behavioral._position_value_usd(_btc('Cocos'), {'BTC': SPOT}, BLUE, MEP)
        self.assertAlmostEqual(v, QTY * SPOT, places=2)
        c = behavioral._position_value_usd(_btc('Cocos'), {}, BLUE, MEP, honor_override=False)
        self.assertAlmostEqual(c, COST, places=2)   # lo que puso, no puso × 1,0367
        self.assertAlmostEqual((v - c) / c, (QTY * SPOT - COST) / COST, places=5)

    def test_cuenta_en_pesos_con_premium(self):
        """Cuenta EN PESOS: el valor natural son pesos y pasan a USD por el MEP."""
        v = behavioral._position_value_usd(_btc_ars('Cocos'), {'BTC': SPOT}, BLUE, MEP)
        self.assertAlmostEqual(v, QTY * SPOT * PREMIUM, places=2)
        # El costo en pesos ya pasa a dólar-MEP con /MEP → NO se multiplica de nuevo
        # (compondría /MEP²). El P&L% queda con el premium sólo del lado del valor.
        c = behavioral._position_value_usd(_btc_ars('Cocos'), {}, BLUE, MEP, honor_override=False)
        self.assertAlmostEqual(c, COST, places=2)

    def test_exchange_no_premium(self):
        v = behavioral._position_value_usd(_btc('Binance'), {'BTC': SPOT}, BLUE, MEP)
        self.assertAlmostEqual(v, QTY * SPOT, places=2)

    def test_non_crypto_no_premium(self):
        p = {'asset': 'AAPL', 'broker': 'Cocos', 'currency': 'USDT',
             'quantity': 10, 'invested': 1500, 'is_cash': 0}
        v = behavioral._position_value_usd(p, {'AAPL': 150}, BLUE, MEP)
        self.assertAlmostEqual(v, 1500.0, places=2)

    def test_usdt_cash_no_premium(self):
        p = {'asset': 'USDT', 'broker': 'Binance', 'currency': 'USDT',
             'quantity': 0, 'invested': 1000, 'is_cash': 1}
        v = behavioral._position_value_usd(p, {}, BLUE, MEP)
        self.assertAlmostEqual(v, 1000.0, places=2)

    def test_override_no_premium(self):
        v = behavioral._position_value_usd(_btc('Cocos', price_override=60000), {'BTC': SPOT}, BLUE, MEP)
        self.assertAlmostEqual(v, QTY * 60000, places=2)  # override directo, sin premium

    def test_missing_cripto_fallback_to_spot(self):
        _set_dolar(cripto=None)
        v = behavioral._position_value_usd(_btc('Cocos'), {'BTC': SPOT}, BLUE, MEP)
        self.assertAlmostEqual(v, QTY * SPOT, places=2)


class SnapshotCryptoTest(unittest.TestCase):
    def setUp(self):
        self._orig_dolar = main._dolar_cache.get('data')
        _set_dolar()

    def tearDown(self):
        main._dolar_cache['data'] = self._orig_dolar

    def test_snapshot_cuenta_en_dolares_sin_premium(self):
        r = snapshots_job.compute_broker_value_usd([_btc('Cocos')], {'BTC': SPOT}, 'USDT', BLUE, 'Cocos', MEP)
        self.assertAlmostEqual(r['value'], QTY * SPOT, places=2)
        self.assertAlmostEqual(r['invested'], COST, places=2)
        self.assertAlmostEqual((r['value'] - r['invested']) / r['invested'],
                               (QTY * SPOT - COST) / COST, places=5)

    def test_snapshot_cuenta_en_pesos_con_premium(self):
        """La foto diaria de una cuenta EN PESOS conserva el premium — el mismo
        número que la Cartera saca del precio '<c>.BA' (spot×cripto) ÷ MEP."""
        r = snapshots_job.compute_broker_value_usd([_btc_ars('Cocos')], {'BTC': SPOT}, 'ARS', BLUE, 'Cocos', MEP)
        self.assertAlmostEqual(r['value'], QTY * SPOT * PREMIUM, places=2)

    def test_snapshot_exchange_no_premium(self):
        r = snapshots_job.compute_broker_value_usd([_btc('Binance')], {'BTC': SPOT}, 'USDT', BLUE, 'Binance', MEP)
        self.assertAlmostEqual(r['value'], QTY * SPOT, places=2)
        self.assertAlmostEqual(r['invested'], COST, places=2)

    def test_snapshot_usd_subbroker_crypto(self):
        """Cripto en un sub-broker '· USD' (ar_usd=True): la pata dólar de un broker
        argentino ES una cuenta en dólares → spot, sin premium. Sigue sin rutearse a
        .BA (sin ese guard escalaba el costo sin escalar el valor → P&L invertido)."""
        p = {'asset': 'BTC', 'broker': 'Cocos · USD', 'currency': 'USDT',
             'quantity': QTY, 'invested': COST, 'is_cash': 0}
        r = snapshots_job.compute_broker_value_usd([p], {'BTC': SPOT}, 'USDT', BLUE, 'Cocos · USD', MEP)
        self.assertAlmostEqual(r['value'], QTY * SPOT, places=2)
        self.assertAlmostEqual(r['invested'], COST, places=2)
        self.assertAlmostEqual((r['value'] - r['invested']) / r['invested'],
                               (QTY * SPOT - COST) / COST, places=5)

    def test_parity_behavioral_vs_snapshot(self):
        """behavioral (value) y snapshots (value/invested) NO deben divergir."""
        bv = behavioral._position_value_usd(_btc('Cocos'), {'BTC': SPOT}, BLUE, MEP)
        bc = behavioral._position_value_usd(_btc('Cocos'), {}, BLUE, MEP, honor_override=False)
        r = snapshots_job.compute_broker_value_usd([_btc('Cocos')], {'BTC': SPOT}, 'USDT', BLUE, 'Cocos', MEP)
        self.assertAlmostEqual(bv, r['value'], places=2)
        self.assertAlmostEqual(bc, r['invested'], places=2)


if __name__ == "__main__":
    unittest.main()
