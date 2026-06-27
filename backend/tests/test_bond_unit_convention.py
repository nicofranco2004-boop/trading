"""data912 NO cotiza todos los bonos en la misma unidad: soberanos/BOPREAL/ONs
vienen per-100 face, pero los CER (TX*/TZX*) vienen per-1. _resolve_ar_bond_price
debe devolver per-1 en AMBOS casos (÷100 solo a los per-100). Antes dividía TODO
por 100 → los CER quedaban valuados 100× para abajo (bug 2026-06-27).
"""
import unittest
from unittest.mock import patch

import main

# Snapshot de valores LIVE reales de data912 (2026-06-27).
STUB = {
    # Soberanos / ON / BOPREAL → per-100 face
    "AL30": 96300.0, "AL30D": 64.23, "GD30": 98770.0, "GD30D": 65.09,
    "AE38": 126430.0, "AL35": 122800.0, "AO28": 146990.0,
    "YM39O": 171050.0, "BPOA7": 155860.0, "PNDCO": 64580.0,
    # CER → per-1
    "TX26": 702.9, "TX26D": 0.465, "TX28": 1665.0, "TX28D": 1.106,
    "TZX26": 394.65, "TZX27": 375.25, "TZX28": 337.85,
}


class BondUnitConventionTest(unittest.TestCase):
    def _resolve(self, sym):
        with patch.object(main, "_fetch_data912_bonds", return_value=STUB):
            return main._resolve_ar_bond_price(sym)

    def test_sovereign_ars_is_per100_divided(self):
        self.assertAlmostEqual(self._resolve("AL30.BA"), 963.0, places=2)
        self.assertAlmostEqual(self._resolve("AO28.BA"), 1469.9, places=2)

    def test_sovereign_usd_is_per100_divided(self):
        self.assertAlmostEqual(self._resolve("AL30"), 0.6423, places=4)
        self.assertAlmostEqual(self._resolve("GD30"), 0.6509, places=4)

    def test_cer_ars_is_per1_not_divided(self):
        # EL bug: estos NO se dividen por 100.
        self.assertAlmostEqual(self._resolve("TX26.BA"), 702.9, places=2)
        self.assertAlmostEqual(self._resolve("TX28.BA"), 1665.0, places=2)
        self.assertAlmostEqual(self._resolve("TZX26.BA"), 394.65, places=2)

    def test_cer_usd_is_per1_not_divided(self):
        self.assertAlmostEqual(self._resolve("TX26"), 0.465, places=4)
        self.assertAlmostEqual(self._resolve("TX28"), 1.106, places=4)

    def test_bond_price_per1_for_backfill_reference(self):
        # _bond_price_per1 (referencia del normalizador del backfill) per-1 correcto
        with patch.object(main, "_fetch_data912_bonds", return_value=STUB):
            self.assertAlmostEqual(main._bond_price_per1("TX26", "ARS"), 702.9, places=2)
            self.assertAlmostEqual(main._bond_price_per1("TX26", "USD"), 0.465, places=4)
            self.assertAlmostEqual(main._bond_price_per1("AL30", "ARS"), 963.0, places=2)

    def test_non_bond_returns_none(self):
        self.assertIsNone(self._resolve("AAPL"))
        self.assertIsNone(self._resolve("MELI.BA"))

    def test_mep_derived_from_data912(self):
        self.assertAlmostEqual(main._data912_peso_per_usd(STUB), 96300.0 / 64.23, places=1)

    def test_mep_fallback_when_no_pair(self):
        self.assertEqual(main._data912_peso_per_usd({"TX26": 702.9}), 1450.0)


if __name__ == "__main__":
    unittest.main()
