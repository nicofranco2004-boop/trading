"""Parser de la FOTO de tenencia de Balanz (Resumen de Cuenta / Posición
consolidada, PDF → texto). Testea autodetección, secciones, cash de 2 columnas,
per-1/per-100 y los quirks reales del formato (descripción con comillas `S.A."B"`,
`$` embebido en la descripción de BYMA, FCI con precio sub-1).

Corre con: cd backend && python3 -m pytest tests/test_balanz_tenencia.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing import tenencia as tn


# Muestra sintética que replica la ESTRUCTURA real del Resumen de Balanz: bloque
# Monedas en 2 columnas (los montos caen a mitad de línea), las 4 secciones con su
# header, y los quirks (comillas, `$` embebido, FCI sub-1, bonos per-1).
SAMPLE = """BALANZ
Posición consolidada por concertación FULL INVESTMENT HOUSE
Información de cuenta | Tenencias
Cuenta TEST USER Fecha resumen 01/07/2026
N° Comitente 111 Fecha de emisión 01/07/2026
Total $ 1.500.000
Instrumentos Monedas
Acciones $ 21.912 Pesos $ 837,14
Bonos $ 3.853 Dólares USD 0,00
Cedears $ 23.140 US Dollar (Cable) USD 0,65
Fondos $ 407
BALANZ CAPITAL | Av. Corrientes 316 | CABA | www.balanz.com
BALANZ
Posición consolidada por concertación FULL INVESTMENT HOUSE
Distribución por tipo de activos
Acciones
Especie Descripción Cantidad Garantía Precio Valor Actual
BMA BANCO MACRO S.A."B" 1 V. ESCRIT 1,00 0.00 $ 13.930,00 $ 13.930
BYMA BOLSAS Y MERCADOS ARG. $ ORD. (BYMA) 26,00 0.00 $ 307,00 $ 7.982
Bonos
Especie Descripción Cantidad Garantía Precio Valor Actual
AE38 BONO REP. ARGENTINA USD STEP UP 2038 3,00 0.00 $ 1.284,40 $ 3.853
Cedears
Especie Descripción Cantidad Garantía Precio Valor Actual
AAPL CEDEAR APPLE INC. 1,00 0.00 $ 23.140,00 $ 23.140
Fondos
Especie Descripción Cantidad Garantía Precio Valor Actual
BAHUSDA Corporativo Clase A 287,27 0.00 $ 1,42 $ 407
BALANZ CAPITAL | Av. Corrientes 316 | CABA | www.balanz.com
BALANZ
La información detallada en este resumen corresponde a los activos... CUIT: 30-71063067-0 $ 999
Información de titulares y autorizados
Aram Nicolas Dotbachian Titular Jul 1 2026 2:33PM
"""

# Texto de la Tenencia de Bull Market (para chequear que NO se confunden).
BM_SAMPLE = """Tenencia valorizada
Tenencias al 26/06/2026 ARS 25.354.380,78
Acciones ARS 3.355.162,50
Ticker Nombre de la Especie Cantidad Precio Importe Total
BMA BANCO MACRO 30,00 14.110,00 423.300,00
"""


class BalanzTenenciaParse(unittest.TestCase):
    def setUp(self):
        self.snap = tn.parse_balanz_tenencia(SAMPLE)
        self.by = {h.ticker: h for h in self.snap.holdings}

    def test_autodeteccion(self):
        self.assertTrue(tn.looks_like_balanz_tenencia(SAMPLE))
        # No debe robarse la foto de Bull Market ni viceversa.
        self.assertFalse(tn.looks_like_balanz_tenencia(BM_SAMPLE))
        self.assertFalse(tn.looks_like_tenencia(SAMPLE))

    def test_fecha_y_total(self):
        self.assertEqual(self.snap.date, "2026-07-01")
        self.assertEqual(self.snap.total_ars, 1_500_000)

    def test_cash_dos_columnas(self):
        # Pesos → ARS; Dólares + Cable → USD (0.00 + 0.65).
        self.assertEqual(self.snap.cash_ars, 837.14)
        self.assertEqual(self.snap.cash_usd, 0.65)

    def test_holdings_count_y_tipos(self):
        self.assertEqual(len(self.snap.holdings), 5)   # BMA, BYMA, AE38, AAPL, BAHUSDA
        self.assertEqual(self.by["BMA"].asset_type, "STOCK")
        self.assertEqual(self.by["AE38"].asset_type, "BOND")
        self.assertEqual(self.by["AAPL"].asset_type, "CEDEAR")
        self.assertEqual(self.by["BAHUSDA"].asset_type, "FUND")

    def test_todo_ars(self):
        self.assertTrue(all(h.currency == "ARS" for h in self.snap.holdings))

    def test_quoted_description(self):
        # `S.A."B"` no rompe el parseo; qty/valor correctos.
        self.assertEqual(self.by["BMA"].quantity, 1.0)
        self.assertEqual(self.by["BMA"].value, 13_930)
        self.assertIn('S.A."B"', self.by["BMA"].name)

    def test_dollar_embebido_en_descripcion(self):
        # BYMA: la descripción trae un `$` literal → el ancla son los 2 últimos `$`.
        self.assertEqual(self.by["BYMA"].quantity, 26.0)
        self.assertEqual(self.by["BYMA"].value, 7_982)

    def test_bono_per1(self):
        # Balanz cotiza los bonos per-1 (3 × 1284,40 ≈ 3853).
        self.assertFalse(self.by["AE38"].per100)
        self.assertAlmostEqual(self.by["AE38"].price_per1, 3853 / 3, places=2)

    def test_fci_precio_sub1_en_pesos(self):
        # BAHUSDA: precio 1,42 y valor 407 en pesos (no inferir USD por el nombre).
        self.assertEqual(self.by["BAHUSDA"].currency, "ARS")
        self.assertAlmostEqual(self.by["BAHUSDA"].quantity, 287.27, places=2)
        self.assertEqual(self.by["BAHUSDA"].value, 407)

    def test_sin_warnings(self):
        self.assertEqual(self.snap.warnings, [])

    def test_disclaimer_no_genera_holdings(self):
        # La línea del disclaimer con `$ 999` NO debe crear un holding fantasma.
        self.assertNotIn("999", self.by)
        self.assertNotIn("LA", self.by)

    def test_garantia_no_cero_no_tira_la_fila(self):
        # Una tenencia con garantía ≠ 0 (caución) NO debe caerse de la foto — en
        # override eso la VENDERÍA por error. Aceptamos garantía en punto, AR o US.
        for gar in ("0.00", "1.234,00", "1,234.00", "500.00"):
            txt = (
                "Posición consolidada por concertación\n"
                "Fecha resumen 01/07/2026\n"
                "Acciones\n"
                "Especie Descripción Cantidad Garantía Precio Valor Actual\n"
                f"YPFD YPF S.A. ESCRIT. \"D\" 1 VOTO 14,00 {gar} $ 69.550,00 $ 973.700\n"
            )
            snap = tn.parse_balanz_tenencia(txt)
            got = {h.ticker: h for h in snap.holdings}
            self.assertIn("YPFD", got, f"garantía {gar!r} tiró la fila")
            self.assertEqual(got["YPFD"].quantity, 14.0, f"qty mal con garantía {gar!r}")
            self.assertEqual(got["YPFD"].value, 973_700, f"valor mal con garantía {gar!r}")


if __name__ == "__main__":
    unittest.main()
