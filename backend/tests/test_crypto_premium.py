"""Premium dólar-cripto: la cripto de un BROKER (Cocos/Balanz, no exchange) se
valúa al dólar MEP que muestra el broker (factor cripto/MEP a valor Y costo →
P&L% invariante). En un EXCHANGE (Binance) se queda al spot. Cubre el factor,
behavioral._position_value_usd y snapshots_job.compute_broker_value_usd, y la
PARIDAD entre los dos (no deben divergir)."""
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
    p = {'asset': 'BTC', 'broker': broker, 'currency': 'USDT',
         'quantity': QTY, 'invested': COST, 'is_cash': 0}
    p.update(kw)
    return p


class CryptoBrokerFactorTest(unittest.TestCase):
    def test_factor_cases(self):
        f = main.crypto_broker_factor
        self.assertAlmostEqual(f('BTC', 'Cocos', False, CRIPTO, MEP), PREMIUM)
        self.assertEqual(f('BTC', 'Binance', False, CRIPTO, MEP), 1.0)   # exchange
        self.assertEqual(f('AAPL', 'Cocos', False, CRIPTO, MEP), 1.0)    # no-cripto
        self.assertEqual(f('CVX', 'Cocos', False, CRIPTO, MEP), 1.0)     # colisión (no cripto)
        self.assertEqual(f('BTC', 'Cocos', True, CRIPTO, MEP), 1.0)      # override
        self.assertEqual(f('BTC', 'Cocos', False, None, MEP), 1.0)       # sin cripto
        self.assertEqual(f('BTC', 'Cocos', False, CRIPTO, 0), 1.0)       # sin mep

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

    def test_broker_crypto_value_and_cost_scaled(self):
        # VALOR a spot × premium
        v = behavioral._position_value_usd(_btc('Cocos'), {'BTC': SPOT}, BLUE, MEP)
        self.assertAlmostEqual(v, QTY * SPOT * PREMIUM, places=2)
        # COSTO (prices={}, honor_override=False) también × premium → P&L% invariante
        c = behavioral._position_value_usd(_btc('Cocos'), {}, BLUE, MEP, honor_override=False)
        self.assertAlmostEqual(c, COST * PREMIUM, places=2)
        self.assertAlmostEqual((v - c) / c, (QTY * SPOT - COST) / COST, places=5)

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

    def test_snapshot_premium_pnl_invariant(self):
        r = snapshots_job.compute_broker_value_usd([_btc('Cocos')], {'BTC': SPOT}, 'USDT', BLUE, 'Cocos', MEP)
        self.assertAlmostEqual(r['value'], QTY * SPOT * PREMIUM, places=2)
        self.assertAlmostEqual(r['invested'], COST * PREMIUM, places=2)
        self.assertAlmostEqual((r['value'] - r['invested']) / r['invested'],
                               (QTY * SPOT - COST) / COST, places=5)

    def test_snapshot_exchange_no_premium(self):
        r = snapshots_job.compute_broker_value_usd([_btc('Binance')], {'BTC': SPOT}, 'USDT', BLUE, 'Binance', MEP)
        self.assertAlmostEqual(r['value'], QTY * SPOT, places=2)
        self.assertAlmostEqual(r['invested'], COST, places=2)

    def test_snapshot_usd_subbroker_crypto(self):
        """Finding 1: cripto en un sub-broker '· USD' (ar_usd=True) → spot × premium
        (valor Y costo), NO ruteada a .BA. Sin el guard, escalaba costo-sin-valor."""
        p = {'asset': 'BTC', 'broker': 'Cocos · USD', 'currency': 'USDT',
             'quantity': QTY, 'invested': COST, 'is_cash': 0}
        r = snapshots_job.compute_broker_value_usd([p], {'BTC': SPOT}, 'USDT', BLUE, 'Cocos · USD', MEP)
        self.assertAlmostEqual(r['value'], QTY * SPOT * PREMIUM, places=2)
        self.assertAlmostEqual(r['invested'], COST * PREMIUM, places=2)
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
