"""Parser de la Tenencia valorizada de Bull Market (foto de posiciones en PDF).
Lo importante: extrae cantidad + valor + tipo por sección, deriva el precio per-1
(resolviendo la convención per-100 de los bonos), y la suma de valores reconcilia
contra el total del reporte. Texto sintético con la MISMA estructura del PDF real
(no incluimos el PDF del usuario)."""
import unittest

from importing.tenencia import (
    parse_bullmarket_tenencia, looks_like_tenencia, TenenciaSnapshot,
    parse_ppi_tenencia, looks_like_ppi_tenencia,
    compute_reconcile, build_tenencia_seed_txs)

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


# ─── PPI — Estado de Cuenta (Excel → filas crudas) ───────────────────────────
# Filas como las da openpyxl (números float/int, texto str, None). Estructura real:
# preámbulo + "POR TIPO DE ACTIVO" + secciones con header de columnas + SUBTOTAL.
_H8 = ['ESPECIE', 'DESCRIPCIÓN', 'CANT. DISPONIBLE', 'CANT. GARANTÍA', 'PRECIO',
       'VALOR MONEDA COTIZACIÓN', 'VALOR CORRIENTE', '% CARTERA']
PPI_ROWS = [
    ['ESTADO DE CUENTA'],
    [],
    ['TITULAR', None, 'FECHA'],
    ['RAMOS MARTIN', None, '17/07/2026'],
    ['COMITENTE'],
    ['548213'],
    [],
    ['TOTAL CARTERA EXPRESADO EN PESOS $', None, 19859387.78],
    ['TOTAL USD EXPRESADO EN DOLARES U$D', None, 15425.36],
    [],
    ['POR TIPO DE ACTIVO'],
    [],
    ['MONEDAS'],
    ['MONEDA', 'DESCRIPCIÓN', 'CANT. DISPONIBLE', 'PRECIO', 'VALOR CORRIENTE', '% CARTERA'],
    ['$', 'Peso', 7543.22, 1, 7543.22, 0.03],                          # cash ARS → se saltea
    ['USD', 'CV6200 - DIVISA - Caja Valores', 18.75, 1287.45, 24139.69, 0.12],  # cash USD → se saltea
    ['SUBTOTAL', None, None, None, 31682.91, 0.15],
    [],
    ['ACCIONES'],
    _H8,
    ['GGAL', 'Grupo Financiero Galicia S.A.', 120, 0, 7800, 936000, 936000, 4.7],   # STOCK ARS (garantía 0)
    ['YPFD', 'YPF S.A.', 85, 6, 43500, 3958500, 3958500, 19.9],                     # garantía=6 → qty=91, value=(85+6)×43500
    ['SUBTOTAL', None, None, None, None, None, 4894500, 24.6],
    [],
    ['BONOS'],
    _H8,
    ['AL30', 'BONO REP. ARGENTINA USD 2030', 850, 0, 1241.36, 1055160, 1055160, 5.3],  # col5==col6 → BOND ARS
    ['SUBTOTAL', None, None, None, None, None, 1055160, 5.3],
    [],
    ['CEDEARS'],
    _H8,
    ['TSLA', 'Tesla Inc.', 18, 0, 30727.22, 553090, 553090, 2.7],                   # CEDEAR ARS
    ['SUBTOTAL', None, None, None, None, None, 553090, 2.7],
    [],
    ['ONS'],
    _H8,
    ['RPC2D', 'ON RIZOBACTER CL.2 U$S', 150, 0, 1.0881, 163.21, 225010.08, 1.1],    # col5≠col6 → BOND USD
    ['SUBTOTAL', None, None, None, None, None, 225010.08, 1.1],
    [],
    ['FCI'],
    _H8,
    ['SBS.DOL.A', 'SBS Estrategia Dólar Clase A', 842.2371, 0, 1.18472, 1002.93, 1382656.48, 6.9],  # USD por nombre
    ['SBS.PESOS.A', 'SBS Ahorro Pesos Clase A', 1025.438721, 0, 1.236482, 1267.94, 1632404.87, 8.2],  # TRAMPA: ARS por nombre
    ['COMP.DEUDA.A', 'Compass Deuda Argentina Clase A', 632.4175, 0, 2103.09, 1330032.95, 1330032.95, 6.6],  # ARS: sin tag → default ARS
    ['ADCAP.AH.A', 'Adcap Ahorro Clase A', 1000, 0, 1.5, 1500.0, 1934250.0, 9.7],   # untagged + VMC≠VC → ARS (NO USD); value=VC
    ['ADCAP.DL.A', 'Adcap Dolar Linked Clase A', 500, 0, 3265.0, 1632500.0, 1632500.0, 8.2],  # dolar-linked → ARS pese a "Dólar"
    ['SUBTOTAL', None, None, None, None, None, 4345094.30, 21.7],
]


class PpiTenenciaTest(unittest.TestCase):
    def setUp(self):
        self.snap = parse_ppi_tenencia(PPI_ROWS)
        self.by = {h.ticker: h for h in self.snap.holdings}

    def test_looks_like_ppi(self):
        self.assertTrue(looks_like_ppi_tenencia(PPI_ROWS))
        self.assertFalse(looks_like_ppi_tenencia([['Foo'], ['bar', 1]]))

    def test_skips_monedas_and_subtotals(self):
        # 2 STOCK + 1 BOND ARS + 1 CEDEAR + 1 BOND USD + 5 FCI = 10 holdings; nada de cash.
        self.assertEqual(len(self.snap.holdings), 10)
        self.assertNotIn('$', self.by)
        self.assertNotIn('USD', self.by)
        self.assertFalse(any(h.ticker == 'SUBTOTAL' for h in self.snap.holdings))

    def test_asset_type_from_section(self):
        self.assertEqual(self.by['GGAL'].asset_type, 'STOCK')
        self.assertEqual(self.by['AL30'].asset_type, 'BOND')
        self.assertEqual(self.by['TSLA'].asset_type, 'CEDEAR')
        self.assertEqual(self.by['RPC2D'].asset_type, 'BOND')   # ONS → BOND
        self.assertEqual(self.by['SBS.DOL.A'].asset_type, 'FUND')

    def test_currency_detection(self):
        self.assertEqual(self.by['GGAL'].currency, 'ARS')        # acción
        self.assertEqual(self.by['AL30'].currency, 'ARS')        # bono col5==col6
        self.assertEqual(self.by['TSLA'].currency, 'ARS')        # CEDEAR
        self.assertEqual(self.by['RPC2D'].currency, 'USD')       # ON col5≠col6
        self.assertEqual(self.by['SBS.DOL.A'].currency, 'USD')   # FCI nombre "Dólar"
        self.assertEqual(self.by['SBS.PESOS.A'].currency, 'ARS') # TRAMPA: nombre "Pesos" manda
        self.assertEqual(self.by['COMP.DEUDA.A'].currency, 'ARS')  # FCI sin tag → default ARS
        self.assertEqual(self.by['ADCAP.AH.A'].currency, 'ARS')    # untagged + VMC≠VC → ARS (no USD)
        self.assertAlmostEqual(self.by['ADCAP.AH.A'].value, 1934250.0, places=2)  # value=VC, no la cotización
        self.assertEqual(self.by['ADCAP.DL.A'].currency, 'ARS')    # dolar-linked → ARS pese a "Dólar"

    def test_value_is_native_currency(self):
        # USD holding: value en USD (col5), NO el equivalente en ARS (col6).
        self.assertAlmostEqual(self.by['RPC2D'].value, 163.21, places=2)
        self.assertAlmostEqual(self.by['SBS.DOL.A'].value, 1002.93, places=2)
        # ARS holding: value en ARS (col6).
        self.assertAlmostEqual(self.by['AL30'].value, 1055160.0, places=2)
        self.assertAlmostEqual(self.by['SBS.PESOS.A'].value, 1632404.87, places=2)

    def test_price_per1_and_qty(self):
        self.assertAlmostEqual(self.by['GGAL'].quantity, 120.0)
        self.assertAlmostEqual(self.by['GGAL'].price_per1, 936000 / 120, places=4)
        self.assertAlmostEqual(self.by['RPC2D'].price_per1, 163.21 / 150, places=6)

    def test_garantia_counted_in_quantity(self):
        # YPFD: DISPONIBLE 85 + GARANTÍA 6 = 91; price_per1 = value/91 = 43500 (el
        # precio real, no value/85 inflado). Sin esto la qty queda corta y P&L mal.
        self.assertAlmostEqual(self.by['YPFD'].quantity, 91.0)
        self.assertAlmostEqual(self.by['YPFD'].price_per1, 43500.0, places=2)
        self.assertAlmostEqual(self.by['YPFD'].value, 3958500.0, places=2)

    def test_invalid_date_falls_back_to_none(self):
        bad = [list(r) for r in PPI_ROWS]
        bad[3] = ['RAMOS MARTIN', None, '31/13/2026']   # mes 13 imposible
        self.assertIsNone(parse_ppi_tenencia(bad).date)

    def test_dual_currency_seed_row_index_unique_after_renumber(self):
        # Espeja el combinado del endpoint: build por moneda (cada uno arranca en
        # -20000 → colisionan) + re-numeración a índices únicos (fix del bug que
        # colapsaba el mapa raw_id↔row_index en el confirm y rompía el revert).
        ars = [h for h in self.snap.holdings if h.currency == 'ARS']
        usd = [h for h in self.snap.holdings if h.currency == 'USD']
        txs = (build_tenencia_seed_txs('PPI', compute_reconcile({}, TenenciaSnapshot(holdings=ars)), '2026-07-17', currency='ARS')
               + build_tenencia_seed_txs('PPI · USD', compute_reconcile({}, TenenciaSnapshot(holdings=usd)), '2026-07-17', currency='USD'))
        self.assertNotEqual(len(txs), len({t.row_index for t in txs}))  # colisión antes
        for i, t in enumerate(txs):
            t.row_index = -20000 - i
        self.assertEqual(len(txs), len({t.row_index for t in txs}))     # único después

    def test_date_and_total(self):
        self.assertEqual(self.snap.date, '2026-07-17')
        self.assertAlmostEqual(self.snap.total_ars, 19859387.78, places=2)

    def test_reconcile_from_zero_then_no_dup(self):
        # Desde cartera vacía → todo va a to_seed.
        rec = compute_reconcile({}, self.snap)
        self.assertEqual(len(rec.to_seed), 10)
        self.assertEqual(rec.matched, [])
        # Re-subir cuando Rendi YA tiene la foto → todo matched, nada que seedear (no duplica).
        current = {h.ticker: h.quantity for h in self.snap.holdings}
        rec2 = compute_reconcile(current, self.snap)
        self.assertEqual(len(rec2.matched), 10)
        self.assertEqual(rec2.to_seed, [])

    def test_seed_partitioned_by_currency(self):
        # ARS: GGAL,YPFD,AL30,TSLA,SBS.PESOS.A,COMP.DEUDA.A,ADCAP.AH.A,ADCAP.DL.A = 8 ; USD: RPC2D,SBS.DOL.A = 2
        ars = [h for h in self.snap.holdings if h.currency == 'ARS']
        usd = [h for h in self.snap.holdings if h.currency == 'USD']
        self.assertEqual(len(ars), 8)
        self.assertEqual(len(usd), 2)
        rec_usd = compute_reconcile({}, TenenciaSnapshot(holdings=usd))
        txs = build_tenencia_seed_txs('PPI · USD', rec_usd, '2026-07-17', currency='USD')
        buys = [t for t in txs if t.operation_type == 'BUY']
        deps = [t for t in txs if t.operation_type == 'DEPOSIT']
        self.assertEqual(len(buys), 2)
        self.assertEqual(len(deps), 1)
        self.assertTrue(all(t.currency == 'USD' and t.broker == 'PPI · USD' for t in txs))
        # depósito = Σ compras (cash net 0)
        self.assertAlmostEqual(deps[0].gross_amount, sum(t.gross_amount for t in buys), places=2)


if __name__ == "__main__":
    unittest.main()
