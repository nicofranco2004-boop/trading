"""Extracción de CASH de las 3 fotos de tenencia (PPI MONEDAS, Bull Market
Cuenta Corriente, Cocos ARS/USD). El cash de la foto = verdad de HOY → habilita
que el import cierre el efectivo, no solo las posiciones.

Fixtures sintéticos que calcan el formato REAL verificado (números fake).
Corre: cd backend && python3 -m pytest tests/test_tenencia_cash.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.tenencia import (
    parse_ppi_tenencia, parse_bullmarket_tenencia, parse_cocos_tenencia,
)


class PpiCashTest(unittest.TestCase):
    # Filas crudas como las da excel.xlsx_to_rows (preámbulo + secciones).
    ROWS = [
        ["ESTADO DE CUENTA", "", "", "", "", ""],
        ["POR TIPO DE ACTIVO", "", "", "", "", ""],
        ["TOTAL CARTERA", "", "", "", "28000000", ""],
        ["MONEDAS", "", "", "", "", ""],
        ["MONEDA", "DESCRIPCIÓN", "CANT. DISPONIBLE", "PRECIO", "VALOR CORRIENTE", "% CARTERA"],
        ["$", "Peso", "845320.75", "1.0001", "845405.28", "3.0"],
        ["USD", "CV1100 - DIVISA", "6.75", "1378.62", "9305.68", "0.03"],
        ["SUBTOTAL", "", "", "", "854710.96", ""],
        ["ACCIONES", "", "", "", "", ""],
        ["ESPECIE", "DESCRIPCIÓN", "CANT. DISPONIBLE", "PRECIO", "VALOR CORRIENTE", "% CARTERA"],
        ["BMA", "BANCO MACRO", "39", "14110", "550290", "2.0"],
        ["SUBTOTAL", "", "", "", "550290", ""],
    ]

    def test_cash_from_monedas(self):
        snap = parse_ppi_tenencia(self.ROWS)
        self.assertAlmostEqual(snap.cash_ars, 845320.75, places=2)
        self.assertAlmostEqual(snap.cash_usd, 6.75, places=2)
        # La sección MONEDAS NO genera holdings (es cash); ACCIONES sí.
        self.assertEqual([h.ticker for h in snap.holdings], ["BMA"])

    def test_sin_monedas_no_inventa_cash(self):
        rows = [r for r in self.ROWS if r[0] not in ("MONEDAS",)]
        # quitar también las 2 filas de cash y su header/subtotal de MONEDAS
        rows = [["ESTADO DE CUENTA"], ["POR TIPO DE ACTIVO"],
                ["ACCIONES"],
                ["ESPECIE", "DESCRIPCIÓN", "CANT. DISPONIBLE", "PRECIO", "VALOR CORRIENTE"],
                ["BMA", "BANCO MACRO", "39", "14110", "550290"],
                ["SUBTOTAL", "", "", "", "550290"]]
        snap = parse_ppi_tenencia(rows)
        self.assertIsNone(snap.cash_ars)
        self.assertIsNone(snap.cash_usd)


class BullMarketCashTest(unittest.TestCase):
    TEXT = (
        "Tenencia valorizada\n"
        "Tenencias al 26/06/2026 ARS 25.354.380,78\n"
        "Cuenta Corriente ARS -343,21\n"
        "Ticker Nombre de la Especie Cantidad Precio Importe Total\n"
        "Pesos 1 1,00 -1.561,65\n"
        "U$S 0,51 1.468,00 748,68\n"
        "DOLAR MEP 0,32 1.468,00 469,76\n"
        "Acciones ARS 3.355.162,50\n"
        "Ticker Nombre de la Especie Cantidad Precio Importe Total\n"
        "BMA BANCO MACRO 30,00 14.110,00 423.300,00\n"
    )

    def test_cash_from_cuenta_corriente(self):
        snap = parse_bullmarket_tenencia(self.TEXT)
        self.assertAlmostEqual(snap.cash_ars, -1561.65, places=2)   # Pesos → ARS (importe)
        self.assertAlmostEqual(snap.cash_usd, 0.83, places=2)       # U$S 0,51 + DOLAR MEP 0,32
        # El total de la Cuenta Corriente cuadra: -1561.65 + (748.68+469.76) = -343.21
        self.assertAlmostEqual(snap.cash_ars + 748.68 + 469.76, -343.21, places=1)
        self.assertEqual([h.ticker for h in snap.holdings], ["BMA"])


class CocosCashTest(unittest.TestCase):
    CSV = (
        "instrumento;cantidad;precio;moneda;total\n"
        "CEDEAR NVIDIA CORPORATION (NVDA);28;12450;ARS;348600\n"
        "ARS;48763,5;1;ARS;48763,5\n"
        "USD;2,03;1;USD;2,03\n"
    )

    def test_cash(self):
        snap = parse_cocos_tenencia(self.CSV)
        self.assertAlmostEqual(snap.cash_ars, 48763.5, places=2)
        self.assertAlmostEqual(snap.cash_usd, 2.03, places=2)


if __name__ == "__main__":
    unittest.main()
