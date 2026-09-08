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
                           position_cost_usd, position_price_key, _trust_mkt_value)


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


class ArsCostInUsdBrokerTest(unittest.TestCase):
    """Rama ESPEJO de la de arriba: lote de COSTO EN PESOS (currency='ARS') alojado en
    una cuenta USD. Es la rama 2 del canónico valuation.js `valuePositionLot`
    (costInPesos(p) && !isAR), que al backend le faltaba entera.

    Hallazgos A-1 y A-2 de la auditoría (tanda 1A). Sin la rama:
      · el costo en pesos se contaba como DÓLARES → invertido inflado ~MEP×, y
      · el guard _trust_mkt_value comparaba el valor en USD contra un costo en PESOS
        → múltiplo ~1/MEP, fuera de banda → RECHAZABA el precio real y persistía el
        costo inflado como valor de mercado. El guard de cobertura del 95 % no lo ve
        (hay precio) y encima pondera con el costo inflado.
    Los números esperados salen de correr el motor canónico JS sobre los mismos lotes.
    """

    def test_a1_cedear_en_pesos_en_subbroker_usd(self):
        # A-1 exacto: 100 MELI (CEDEAR) pagados ARS 1.500.000 en 'Cocos · USD'.
        # Viejo: invested = value = 1.500.000 (×MEP). Canónico: 1.034,48 / 1.103,45.
        pos = [_p(asset="MELI", asset_type="CEDEAR", currency="ARS",
                  quantity=100, invested=1_500_000.0, broker="Cocos · USD")]
        r = cbv(pos, {"MELI.BA": 16_000.0}, "USD", BLUE, "Cocos · USD", MEP)
        self.assertAlmostEqual(r["invested"], 1_500_000.0 / MEP, places=4)
        self.assertAlmostEqual(r["value"], 100 * 16_000.0 / MEP, places=4)

    def test_guard_compara_pesos_contra_pesos(self):
        # El corazón del bug: con el guard mal, el múltiplo daba ~1/MEP y el precio
        # REAL se descartaba → value caía al costo. Acá el value DEBE ser el de mercado.
        pos = [_p(asset="MELI", asset_type="CEDEAR", currency="ARS",
                  quantity=100, invested=1_500_000.0, broker="Cocos · USD")]
        r = cbv(pos, {"MELI.BA": 16_000.0}, "USD", BLUE, "Cocos · USD", MEP)
        self.assertNotAlmostEqual(r["value"], 1_500_000.0, places=2)   # no cae al costo
        self.assertGreater(r["value"], r["invested"])                  # el P&L real pasa

    def test_a2_accion_ar_en_pesos_en_broker_usd_genuino(self):
        # A-2: GGAL comprado en PESOS alojado en Schwab (USD genuino, sin padre AR).
        # Viejo: pedía y valuaba 'GGAL' (ADR de NYSE). Canónico: 'GGAL.BA' (BYMA).
        p = _p(asset="GGAL", currency="ARS", quantity=100,
               invested=500_000.0, commissions=1_000.0, broker="Schwab")
        self.assertEqual(position_price_key(p, set(), set()), "GGAL.BA")
        r = cbv([p], {"GGAL.BA": 7_000.0, "GGAL": 45.0}, "USD", BLUE, "Schwab", MEP)
        self.assertAlmostEqual(r["invested"], 501_000.0 / MEP, places=4)
        self.assertAlmostEqual(r["value"], 100 * 7_000.0 / MEP, places=4)   # .BA, NO el ADR

    def test_sin_precio_cae_a_costo_usd_pnl_cero(self):
        # Sin precio confiable: valor = costo-USD (÷MEP) → P&L exactamente 0.
        pos = [_p(asset="TXAR", currency="ARS", quantity=50,
                  invested=300_000.0, broker="Schwab")]
        r = cbv(pos, {}, "USD", BLUE, "Schwab", MEP)
        self.assertAlmostEqual(r["invested"], 300_000.0 / MEP, places=4)
        self.assertAlmostEqual(r["value"], 300_000.0 / MEP, places=4)

    def test_price_override_en_pesos(self):
        # El override es un precio LOCAL en pesos → también ÷MEP (mirror del canónico).
        pos = [_p(asset="TSLA", asset_type="CEDEAR", currency="ARS", quantity=20,
                  invested=400_000.0, price_override=25_000.0, broker="Cocos · USD")]
        r = cbv(pos, {}, "USD", BLUE, "Cocos · USD", MEP)
        self.assertAlmostEqual(r["invested"], 400_000.0 / MEP, places=4)
        self.assertAlmostEqual(r["value"], 20 * 25_000.0 / MEP, places=4)

    def test_renta_fija_en_pesos_en_cuenta_usd(self):
        # Banda angosta (0,02..4) y aun así el guard debe confiar: compara ARS vs ARS.
        pos = [_p(asset="AL30", asset_type="BONO", currency="ARS", quantity=100,
                  invested=7_000_000.0, broker="Schwab")]
        r = cbv(pos, {"AL30.BA": 82_000.0}, "USD", BLUE, "Schwab", MEP)
        self.assertAlmostEqual(r["invested"], 7_000_000.0 / MEP, places=4)
        self.assertAlmostEqual(r["value"], 100 * 82_000.0 / MEP, places=4)

    def test_cripto_marcada_ars_no_se_rutea_al_ba(self):
        # costInPesos excluye la cripto: se valúa SIEMPRE al spot USD, nunca por el MEP
        # (y 'BTC.BA' no cotiza en ningún lado). Sin la exclusión, el costo se dividía
        # por el MEP y el valor no → P&L invertido.
        p = _p(asset="BTC", currency="ARS", quantity=1, invested=90_000.0,
               broker="Cocos · USD")
        self.assertEqual(position_price_key(p, set(), set()), "BTC")

    def test_lote_usd_en_cuenta_usd_no_cambia(self):
        # Regresión: sin currency='ARS' nada se toca (comportamiento USD de siempre).
        pos = [_p(asset="AAPL", currency="USD", quantity=10,
                  invested=2_000.0, commissions=5.0, broker="Schwab")]
        r = cbv(pos, {"AAPL": 220.0}, "USD", BLUE, "Schwab", MEP)
        self.assertAlmostEqual(r["invested"], 2_005.0, places=4)
        self.assertAlmostEqual(r["value"], 2_200.0, places=4)


class CoverageWeightTest(unittest.TestCase):
    """`position_cost_usd` — el peso con el que cada lote entra en el guard de
    cobertura del 95 %. Antes eran DOS closures duplicadas (snapshots_job.py:769 y
    :924) que decidían por la moneda del BROKER en vez de la del LOTE, así que
    ponderaban un número que la valuación ya no usaba.

    El invariante que estos tests defienden: el peso del guard tiene que ser
    EXACTAMENTE el `invested` que el motor va a registrar. Si divergen, el guard
    decide si escribe o no mirando una cartera que no existe.
    """

    def _invested(self, pos, broker_ccy, broker_name, prices=None):
        return cbv([pos], prices or {}, broker_ccy, BLUE,
                   broker_name=broker_name, cedear_rate=MEP)["invested"]

    def test_peso_igual_al_invested_registrado(self):
        # EL invariante. Vale para las cuatro combinaciones de (moneda lote × moneda cuenta).
        casos = [
            (_p(asset="MELI", asset_type="CEDEAR", currency="ARS", quantity=100,
                invested=1_500_000.0, broker="Cocos · USD"), "USD", "Cocos · USD"),
            (_p(asset="GGAL", currency="ARS", quantity=100, invested=500_000.0,
                commissions=1_000.0, broker="Schwab"), "USD", "Schwab"),
            (_p(asset="RUCEO", asset_type="BOND", currency="USD", quantity=100,
                invested=100.0, broker="Balanz"), "ARS", "Balanz"),
            (_p(asset="MELI", asset_type="CEDEAR", currency="ARS", quantity=10,
                invested=30_000.0, broker="Balanz"), "ARS", "Balanz"),
            (_p(asset="AAPL", currency="USD", quantity=10, invested=2_000.0,
                commissions=5.0, broker="Schwab"), "USD", "Schwab"),
        ]
        for pos, ccy, name in casos:
            with self.subTest(asset=pos["asset"], lote=pos["currency"], cuenta=ccy):
                self.assertAlmostEqual(position_cost_usd(pos, ccy, BLUE, MEP),
                                       self._invested(pos, ccy, name), places=6)

    def test_lote_en_pesos_en_cuenta_usd_no_pesa_por_mep(self):
        # A-1: el costo en pesos NO se pondera como si fueran dólares.
        # Viejo: 1.500.000 (broker USD → sin ÷MEP). Canónico: 1.500.000/MEP.
        pos = _p(asset="MELI", asset_type="CEDEAR", currency="ARS", quantity=100,
                 invested=1_500_000.0, broker="Cocos · USD")
        self.assertAlmostEqual(position_cost_usd(pos, "USD", BLUE, MEP),
                               1_500_000.0 / MEP, places=6)

    def test_lote_en_dolares_en_broker_ars_no_se_divide(self):
        # La dirección ESPEJO, rota por el mismo motivo: el viejo dividía por el MEP
        # (broker ARS) un costo que ya estaba en dólares → casi no pesaba.
        pos = _p(asset="RUCEO", asset_type="BOND", currency="USD",
                 quantity=100, invested=100.0, broker="Balanz")
        self.assertAlmostEqual(position_cost_usd(pos, "ARS", BLUE, MEP), 100.0, places=6)

    def test_ponderacion_relativa_deja_de_estar_dominada(self):
        # El efecto que importa: con el peso inflado, la posición PEOR valuada se
        # comía el 99,9 % del guard. Con el fix pesa lo que realmente vale.
        malo = _p(asset="MELI", asset_type="CEDEAR", currency="ARS", quantity=100,
                  invested=1_500_000.0, broker="Cocos · USD")
        sano = _p(asset="AAPL", currency="USD", quantity=10, invested=2_000.0,
                  commissions=5.0, broker="Schwab")
        w_malo = position_cost_usd(malo, "USD", BLUE, MEP)
        w_sano = position_cost_usd(sano, "USD", BLUE, MEP)
        self.assertLess(w_malo / (w_malo + w_sano), 0.50)   # viejo: 0.9987

    def test_control_lote_ars_en_broker_ars_no_cambia(self):
        # Regresión: el caso mayoritario (lote en pesos en broker ARS) sigue ÷MEP.
        pos = _p(asset="MELI", asset_type="CEDEAR", currency="ARS",
                 quantity=10, invested=30_000.0, broker="Balanz")
        self.assertAlmostEqual(position_cost_usd(pos, "ARS", BLUE, MEP),
                               30_000.0 / MEP, places=6)

    def test_control_lote_usd_en_broker_usd_no_cambia(self):
        pos = _p(asset="AAPL", currency="USD", quantity=10,
                 invested=2_000.0, commissions=5.0, broker="Schwab")
        self.assertAlmostEqual(position_cost_usd(pos, "USD", BLUE, MEP), 2_005.0, places=6)

    def test_comisiones_entran_en_el_peso(self):
        pos = _p(asset="AAPL", currency="USD", quantity=10,
                 invested=2_000.0, commissions=5.0, broker="Schwab")
        sin = _p(asset="AAPL", currency="USD", quantity=10,
                 invested=2_000.0, commissions=0, broker="Schwab")
        self.assertAlmostEqual(position_cost_usd(pos, "USD", BLUE, MEP)
                               - position_cost_usd(sin, "USD", BLUE, MEP), 5.0, places=6)

    def test_el_peso_no_depende_de_los_precios(self):
        # position_cost_usd pasa prices={} a propósito: `invested` no lee precios en
        # ninguna rama. Si algún día alguna lo hiciera, este test lo caza.
        pos = _p(asset="MELI", asset_type="CEDEAR", currency="ARS", quantity=100,
                 invested=1_500_000.0, broker="Cocos · USD")
        self.assertAlmostEqual(
            position_cost_usd(pos, "USD", BLUE, MEP),
            self._invested(pos, "USD", "Cocos · USD", {"MELI.BA": 16_000.0}), places=6)


if __name__ == "__main__":
    unittest.main()
