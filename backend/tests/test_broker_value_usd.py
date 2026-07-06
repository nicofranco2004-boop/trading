"""Port backend de la valuación (snapshots_job.compute_broker_value_usd) — foco en el
fix del COSTO EN DÓLARES de lotes que viven en un broker ARS (bono/ON/FCI-USD, o CEDEAR
comprado en dólar-MEP → currency='USD').

Bug real (usuario Balanz): el path ARS dividía TODO el costo por el MEP → el costo USD
colapsaba (~1/MEP) y el guard _trust_mkt_value descartaba el precio real → la tenencia
dólar caía a ~u$s0. Fix = rama espejo de costInPesos (respetar currency='USD' por lote).
Debe dar números idénticos al frontend (computeBrokerValue / usdLotValue).
"""
import unittest

from snapshots_job import (compute_broker_value_usd as cbv,
                           position_price_key, _trust_mkt_value)


def _p(**kw):
    p = {"asset": "X", "asset_type": None, "is_cash": False, "invested": 0,
         "quantity": 0, "commissions": 0, "price_override": None, "currency": None}
    p.update(kw)
    return p


MEP = 1500.0
BLUE = 1200.0


class UsdCostInArsBrokerTest(unittest.TestCase):
    def test_bono_usd_no_colapsa(self):
        # ON en dólares en broker ARS: costo YA en USD (sin ÷MEP); valor = .BA×qty÷MEP.
        pos = [_p(asset="RUCEO", asset_type="BOND", currency="USD", quantity=100, invested=100)]
        r = cbv(pos, {"RUCEO.BA": 1650}, "ARS", BLUE, "Balanz", MEP)
        self.assertAlmostEqual(r["invested"], 100, places=4)              # NO ÷MEP
        self.assertAlmostEqual(r["value"], 100 * 1650 / MEP, places=4)    # 110

    def test_fci_usd_por_nav(self):
        # FCI-USD en broker ARS: valor = NAV × qty (USD directo, sin ÷MEP).
        pos = [_p(asset="FCI:BALANZ-AHORRO-EN-DOLARES-A", asset_type="FUND",
                  currency="USD", quantity=1000, invested=1400)]
        r = cbv(pos, {"FCI:BALANZ-AHORRO-EN-DOLARES-A": 1.42}, "ARS", BLUE, "Balanz", MEP)
        self.assertAlmostEqual(r["value"], 1420, places=4)
        self.assertAlmostEqual(r["invested"], 1400, places=4)

    def test_cedear_comprado_en_usd(self):
        pos = [_p(asset="JPM", asset_type="CEDEAR", currency="USD", quantity=73, invested=1573)]
        r = cbv(pos, {"JPM.BA": 33000}, "ARS", BLUE, "Balanz", MEP)
        self.assertAlmostEqual(r["value"], 73 * 33000 / MEP, places=4)
        self.assertAlmostEqual(r["invested"], 1573, places=4)

    def test_lote_costo_ars_no_cambia(self):
        # Regresión: un lote de costo ARS (currency='ARS') sigue por el path viejo (÷MEP).
        pos = [_p(asset="MELI", asset_type="CEDEAR", currency="ARS", quantity=10, invested=30000)]
        r = cbv(pos, {"MELI.BA": 4500}, "ARS", BLUE, "Balanz", MEP)
        self.assertAlmostEqual(r["invested"], 30000 / MEP, places=4)
        self.assertAlmostEqual(r["value"], 10 * 4500 / MEP, places=4)

    def test_sin_precio_cae_a_costo_usd(self):
        pos = [_p(asset="OT42O", asset_type="BOND", currency="USD", quantity=50, invested=54)]
        r = cbv(pos, {}, "ARS", BLUE, "Balanz", MEP)
        self.assertAlmostEqual(r["value"], 54, places=4)     # costo-USD, no ÷MEP
        self.assertAlmostEqual(r["invested"], 54, places=4)

    def test_mix_no_colapsa_total(self):
        # El total del broker ARS con tenencias USD deja de colapsar.
        pos = [
            _p(asset="RUCEO", asset_type="BOND", currency="USD", quantity=100, invested=100),
            _p(asset="FCI:BALANZ-AHORRO-EN-DOLARES-A", asset_type="FUND", currency="USD", quantity=1000, invested=1400),
            _p(asset="MELI", asset_type="CEDEAR", currency="ARS", quantity=10, invested=30000),
        ]
        prices = {"RUCEO.BA": 1650, "FCI:BALANZ-AHORRO-EN-DOLARES-A": 1.42, "MELI.BA": 4500}
        r = cbv(pos, prices, "ARS", BLUE, "Balanz", MEP)
        want = (100 * 1650 / MEP) + 1420 + (10 * 4500 / MEP)
        self.assertAlmostEqual(r["value"], want, places=4)


class RoutedUsdBrokerTest(unittest.TestCase):
    def test_fci_en_sibling_usd_por_nav(self):
        # Caso ruteado: FCI-USD en el sub-broker 'Balanz · USD' → NAV USD, no ÷MEP.
        pos = [_p(asset="FCI:BALANZ-AHORRO-EN-DOLARES-A", asset_type="FUND",
                  currency="USDT", quantity=1000, invested=1400)]
        r = cbv(pos, {"FCI:BALANZ-AHORRO-EN-DOLARES-A": 1.42}, "USDT", BLUE, "Balanz · USD", MEP)
        self.assertAlmostEqual(r["value"], 1420, places=4)

    def test_cedear_en_sibling_usd_por_ba_mep(self):
        pos = [_p(asset="JPM", asset_type="CEDEAR", currency="USDT", quantity=73, invested=1573)]
        r = cbv(pos, {"JPM.BA": 33000}, "USDT", BLUE, "Balanz · USD", MEP)
        self.assertAlmostEqual(r["value"], 73 * 33000 / MEP, places=4)


class AuditFixesTest(unittest.TestCase):
    """Fixes del audit pre-merge: FCI se precia por su símbolo (no .BA) y el override
    de renta fija se clampea igual que el frontend."""

    def test_fci_price_key_is_bare_not_ba(self):
        # position_price_key debe devolver el símbolo FCI crudo (NAV), NUNCA 'FCI:...BA',
        # aun en un broker ARS — mismo criterio que el frontend priceSymbol.
        p = {"asset": "FCI:BALANZ-AHORRO-EN-DOLARES-A", "asset_type": "FUND", "broker": "Balanz"}
        self.assertEqual(position_price_key(p, {"Balanz"}, set()), "FCI:BALANZ-AHORRO-EN-DOLARES-A")

    def test_non_fci_ars_broker_still_ba(self):
        p = {"asset": "MELI", "asset_type": "CEDEAR", "broker": "Balanz"}
        self.assertEqual(position_price_key(p, {"Balanz"}, set()), "MELI.BA")

    def test_override_fixed_income_clamped(self):
        # Override absurdo (per-100: 97 vs 0,97 → ×100) en renta fija → NO se confía
        # (mirror del frontend). mult = 4850/54 ≈ 90.
        self.assertFalse(_trust_mkt_value(4850, 54, "BOND", has_override=True))

    def test_override_non_fixed_income_respected(self):
        # Override en una acción/CEDEAR (no renta fija) → se respeta aunque sea grande.
        self.assertTrue(_trust_mkt_value(4850, 54, "CEDEAR", has_override=True))

    def test_fixed_income_in_band_trusted(self):
        self.assertTrue(_trust_mkt_value(60, 54, "BOND", has_override=True))   # mult 1.11


if __name__ == "__main__":
    unittest.main()
