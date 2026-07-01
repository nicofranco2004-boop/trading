"""Valuación .BA (BYMA) PARENT-AWARE: un holding se valúa por su precio local
`.BA` si el broker es ARS O su PADRE es ARS (parent_broker_id) — robusto al
rename del broker, y correcto para el sub-broker USD de un padre argentino
(un CEDEAR comprado por dólar-MEP sigue siendo un CEDEAR). Un broker USD raíz
(Schwab, sin padre AR) → acción US.

Corre: cd backend && python3 -m pytest tests/test_parent_broker_ccy.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from behavioral import byma_broker_names, stamp_byma, _price_is_ars
import snapshots_job as sj

# Números/nombres fake. El punto: la decisión NO depende del nombre.
_BROKERS = [
    {"id": 1, "name": "Balanz cuenta 1", "currency": "ARS", "parent_broker_id": None},   # top-level ARS renombrado
    {"id": 2, "name": "BZ dolares",      "currency": "USD", "parent_broker_id": 1},       # sub USD de padre ARS, SIN sufijo '· USD'
    {"id": 3, "name": "Charles Schwab",  "currency": "USD", "parent_broker_id": None},    # USD raíz genuino
    {"id": 4, "name": "Cocos · USD",     "currency": "USD", "parent_broker_id": None},    # sub '· USD' SIN parent_broker_id (dato viejo) → fallback por nombre
]


class BymaParentAwareTest(unittest.TestCase):
    def test_byma_broker_names(self):
        byma = byma_broker_names(_BROKERS)
        self.assertIn("Balanz cuenta 1", byma)   # ARS por currency (nombre irrelevante)
        self.assertIn("BZ dolares", byma)          # USD pero padre ARS → BYMA
        self.assertNotIn("Charles Schwab", byma)   # USD raíz → NO
        # 'Cocos · USD' no tiene parent_broker_id acá → byma_broker_names NO lo
        # agrega (es el fallback por nombre de snapshots/isArUsdBroker el que lo cubre).
        self.assertNotIn("Cocos · USD", byma)

    def test_stamp_byma_and_price_is_ars(self):
        pos = [
            {"asset": "AAPL", "broker": "Balanz cuenta 1", "asset_type": ""},
            {"asset": "AAPL", "broker": "BZ dolares", "asset_type": ""},
            {"asset": "AAPL", "broker": "Charles Schwab", "asset_type": ""},
        ]
        stamp_byma(pos, _BROKERS)
        self.assertTrue(_price_is_ars(pos[0]))    # Balanz cuenta 1 → .BA
        self.assertTrue(_price_is_ars(pos[1]))    # sub USD de padre ARS → .BA
        self.assertFalse(_price_is_ars(pos[2]))   # Schwab → ticker US (NYSE)

    def test_cedear_always_ba_even_in_us_broker(self):
        # Un asset_type=CEDEAR siempre .BA, aunque el broker sea USD raíz.
        p = {"asset": "AAPL", "broker": "Charles Schwab", "asset_type": "CEDEAR"}
        stamp_byma([p], _BROKERS)
        self.assertTrue(_price_is_ars(p))

    def test_snapshots_broker_name_sets_parent_aware(self):
        ars_names, ar_usd_names = sj._broker_name_sets(_BROKERS)
        self.assertIn("Balanz cuenta 1", ars_names)     # ARS por currency
        self.assertIn("BZ dolares", ar_usd_names)         # padre ARS (sin sufijo)
        self.assertIn("Cocos · USD", ar_usd_names)        # fallback por nombre (sin parent_broker_id)
        self.assertNotIn("Charles Schwab", ars_names)
        self.assertNotIn("Charles Schwab", ar_usd_names)

    def test_price_is_ars_legacy_fallback_sin_byma(self):
        # Sin estampar _byma, cae al comportamiento legacy (no regresión):
        # un '· USD' por nombre y un CEDEAR siguen dando .BA.
        self.assertTrue(_price_is_ars({"asset": "AAPL", "broker": "Cocos · USD", "asset_type": ""}))
        self.assertTrue(_price_is_ars({"asset": "AAPL", "broker": "X", "asset_type": "CEDEAR"}))
        self.assertFalse(_price_is_ars({"asset": "AAPL", "broker": "Schwab", "asset_type": "", "currency": "USD"}))


if __name__ == "__main__":
    unittest.main()
