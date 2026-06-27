"""Parser de la Tenencia valorizada de Bull Market (foto de posiciones en PDF).
Lo importante: extrae cantidad + valor + tipo por sección, deriva el precio per-1
(resolviendo la convención per-100 de los bonos), y la suma de valores reconcilia
contra el total del reporte. Texto sintético con la MISMA estructura del PDF real
(no incluimos el PDF del usuario)."""
import unittest

from importing.tenencia import (
    parse_bullmarket_tenencia, looks_like_tenencia, TenenciaSnapshot)

# Estructura idéntica al PDF real (acción per-1, bono per-100, CEDEAR per-1).
SAMPLE = """Tenencia valorizada
Inicio > Mi cuenta > Otras consultas > Tenencia valorizada a una fecha
Tenencias al 26/06/2026 ARS 3.323.379,79
Cuenta Corriente ARS -343,21
Pesos 1 1,00 -1.561,65
U$S 0,51 1.468,00 748,68
Acciones ARS 423.300,00
Ticker Nombre de la Especie Cantidad Precio Importe Total
BMA BANCO MACRO 30,00 14.110,00 423.300,00
Titulos Publicos ARS 650.025,00
Ticker Nombre de la Especie Cantidad Precio Importe Total
AL30 BONO REP. ARGENTINA USD STEP UP 2030 675,00 96.300,00 650.025,00
Obligaciones Negociables ARS 558.558,00
Ticker Nombre de la Especie Cantidad Precio Importe Total
IRCPO ON IRSA INV. Y REP. V 31/03/35 341,00 163.800,00 558.558,00
Cedears ARS 441.760,00
Ticker Nombre de la Especie Cantidad Precio Importe Total
MELI CEDEAR MERCADOLIBRE INC. 40,00 21.510,00 860.400,00
AAPL CEDEAR APPLE INC. 38,00 21.880,00 831.440,00
"""


class TenenciaParserTest(unittest.TestCase):
    def setUp(self):
        self.snap = parse_bullmarket_tenencia(SAMPLE)
        self.by = {h.ticker: h for h in self.snap.holdings}

    def test_autodetect(self):
        self.assertTrue(looks_like_tenencia(SAMPLE))
        self.assertFalse(looks_like_tenencia("Liquida,Operado,Comprobante,Importe"))

    def test_date_and_total(self):
        self.assertEqual(self.snap.date, "2026-06-26")
        self.assertAlmostEqual(self.snap.total_ars, 3_323_379.79, places=2)

    def test_count_and_types(self):
        self.assertEqual(len(self.snap.holdings), 5)
        self.assertEqual(self.by["BMA"].asset_type, "STOCK")
        self.assertEqual(self.by["AL30"].asset_type, "BOND")
        self.assertEqual(self.by["IRCPO"].asset_type, "BOND")     # ON → BOND
        self.assertEqual(self.by["MELI"].asset_type, "CEDEAR")

    def test_stock_per1(self):
        h = self.by["BMA"]
        self.assertEqual(h.quantity, 30.0)
        self.assertAlmostEqual(h.value, 423_300.00, places=2)
        self.assertFalse(h.per100)
        self.assertAlmostEqual(h.price_per1, 14_110.00, places=2)

    def test_bond_per100_resolved(self):
        # AL30: 675 × 96.300 = 65M, pero importe = 650.025 → per-100. El precio
        # per-1 derivado = 650.025/675 = 963.
        h = self.by["AL30"]
        self.assertTrue(h.per100)
        self.assertAlmostEqual(h.value, 650_025.00, places=2)
        self.assertAlmostEqual(h.price_per1, 963.00, places=2)

    def test_no_false_warnings(self):
        # El bono per-100 NO debe generar warning (es convención esperada).
        self.assertEqual(self.snap.warnings, [])

    def test_value_reconciles(self):
        # Σ valores + cash (-343,21) = total del reporte.
        suma = sum(h.value for h in self.snap.holdings)
        self.assertAlmostEqual(suma - 343.21, self.snap.total_ars, places=1)

    def test_real_mismatch_flags(self):
        bad = "Acciones ARS 100,00\nTicker Nombre Cantidad Precio Importe Total\nXXX UNA COSA 10,00 5,00 999,00\n"
        snap = parse_bullmarket_tenencia(bad)
        self.assertTrue(any("XXX" in w for w in snap.warnings))


class TenenciaReconcileTest(unittest.TestCase):
    """La foto es la VERDAD; reconcilia por activo contra lo que Rendi ya tiene
    (sumando padre + sibling). Completa SOLO el hueco, no duplica, no inventa."""

    def setUp(self):
        from importing.tenencia import compute_reconcile, build_tenencia_seed_txs
        self.compute_reconcile = compute_reconcile
        self.build_seeds = build_tenencia_seed_txs
        self.snap = parse_bullmarket_tenencia(SAMPLE)   # BMA30, AL30 675, IRCPO 341, MELI 40, AAPL 38

    def test_matched_not_duplicated(self):
        # Rendi ya tiene BMA 30 (igual que la foto) → matched, no se seedea.
        rendi = {"BMA": 30.0}
        r = self.compute_reconcile(rendi, self.snap)
        self.assertIn("BMA", r.matched)
        self.assertFalse(any(h.ticker == "BMA" for h, _ in r.to_seed))

    def test_partial_seeds_only_the_gap(self):
        # Rendi tiene AL30 2 (la CC reconstruyó parcial), foto 675 → seed 673.
        rendi = {"AL30": 2.0}
        r = self.compute_reconcile(rendi, self.snap)
        al30 = [(h, g) for h, g in r.to_seed if h.ticker == "AL30"]
        self.assertEqual(len(al30), 1)
        self.assertAlmostEqual(al30[0][1], 673.0, places=4)

    def test_missing_seeds_full(self):
        # Rendi no tiene MELI → seed completo (40).
        r = self.compute_reconcile({}, self.snap)
        meli = [(h, g) for h, g in r.to_seed if h.ticker == "MELI"]
        self.assertAlmostEqual(meli[0][1], 40.0, places=4)

    def test_phantom_flagged_not_in_snapshot(self):
        # Rendi tiene XYZ que la foto no → not_in_snapshot (no se toca, se avisa).
        r = self.compute_reconcile({"XYZ": 5.0}, self.snap)
        self.assertTrue(any(t == "XYZ" for t, _ in r.not_in_snapshot))

    def test_seed_txs_have_type_per1_and_net_zero_cash(self):
        r = self.compute_reconcile({}, self.snap)   # todo es hueco
        txs = self.build_seeds("Bull Market", r, "2026-06-26")
        buys = [t for t in txs if t.operation_type == "BUY"]
        deps = [t for t in txs if t.operation_type == "DEPOSIT"]
        self.assertEqual(len(buys), len(self.snap.holdings))   # una compra por activo
        # asset_type viene de la foto (no OTHER) y el precio es per-1
        al30 = next(t for t in buys if t.asset_symbol == "AL30")
        self.assertEqual(al30.asset_type, "BOND")
        self.assertAlmostEqual(al30.unit_price, 963.0, places=2)   # per-1, no 96.300
        # cash net 0: el depósito = Σ de las compras
        self.assertAlmostEqual(deps[0].gross_amount,
                               sum(t.gross_amount for t in buys), places=2)


if __name__ == "__main__":
    unittest.main()
