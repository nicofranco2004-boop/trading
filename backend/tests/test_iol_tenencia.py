"""Parser del Resumen de Cuenta de IOL (PDF, foto de tenencia) — parse_iol_tenencia.

Mismo rol/mecanismo que Balanz/BMB: la foto de HOY que PISA lo que los Movimientos
dejaron. Trae cotización (no PPP) → siembra a precio de hoy (P&L 0). Guard de
completitud: la suma de importes (ARS) reconcilia contra "Títulos Valorizados".

Corre con: cd backend && python3 -m pytest tests/test_iol_tenencia.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.tenencia import (  # noqa: E402
    parse_iol_tenencia, looks_like_iol_tenencia, _iol_asset_type,
)

# Total declarado = suma de importes: 566000 + 2926,5 + 18000 + 17319,424 + 7810 = 612055,924
_HEAD = (
    "www.invertironline.com | Tel.: (54 11) 4000 1400\n"
    "Resumen de Cuenta\n"
    "Fecha Estado de Cta: 30/6/2026\n"
    "Detalle de Saldos Moneda Saldo\n"
    "Disponible Pesos * AR$ 13268,40\n"
    "Disponible Pesos Operable ** AR$ 99999,99\n"      # Operable = duplicado → NO se cuenta
    "Disponible Dólares US$ 1,58\n"
    "Disponible Dólares Operable ** US$ 88888,88\n"
    "Títulos Valorizados AR$ 612055,92\n"
    "Detalle de Títulos Valorizados\n"
    "Título Símbolo Mercado Cantidad Moneda Cotización Importe\n"
    "Cedear Apple Inc. AAPL BCBA 25,0000 AR$ 22640,000 566000,000\n"
    "Bono Rep. Argentina Usd Step Up 2030 AL30 BCBA 3,0000 AR$ 97550,000 2926,500\n"
    "Cedear Citigroup C BCBA 4,0000 AR$ 4500,000 18000,000\n"
    "Adcap Renta Dólar ADCGLOA BCBA 8,6390 US$ 1,3410 17319,4240\n"
    "Grupo Financiero Galicia S.A GGAL BCBA 1,0000 AR$ 7810,000 7810,000\n"
)
_TXT = _HEAD + "Saldo Total Títulos Val.: AR$ 612055,92\n"


class IolTenenciaTest(unittest.TestCase):
    def setUp(self):
        self.snap = parse_iol_tenencia(_TXT)
        self.by = {h.ticker: h for h in self.snap.holdings}

    def test_detects_format(self):
        self.assertTrue(looks_like_iol_tenencia(_TXT))
        self.assertFalse(looks_like_iol_tenencia("Tenencias al 26/06/2026 ARS 1.000,00"))

    def test_date_and_cash_excludes_operable(self):
        self.assertEqual(self.snap.date, "2026-06-30")
        self.assertAlmostEqual(self.snap.cash_ars, 13268.40)   # NO 99999,99 (Operable)
        self.assertAlmostEqual(self.snap.cash_usd, 1.58)       # NO 88888,88

    def test_cedear_per1(self):
        h = self.by["AAPL"]
        self.assertEqual(h.asset_type, "CEDEAR")
        self.assertAlmostEqual(h.quantity, 25.0)
        self.assertEqual(h.currency, "ARS")
        self.assertFalse(h.per100)
        self.assertAlmostEqual(h.value, 566000.0)

    def test_bond_per100(self):
        h = self.by["AL30"]
        self.assertEqual(h.asset_type, "BOND")
        self.assertTrue(h.per100)                # cotización per-100 (qty×cotiz/100=importe)
        self.assertAlmostEqual(h.value, 2926.5)

    def test_usd_fci_native_value(self):
        # USD: el importe (17319 ARS) es la conversión MEP → el valor NATIVO en USD es
        # qty×cotización (8,639 × 1,341 = 11,585), NO el importe.
        h = self.by["ADCGLOA"]
        self.assertEqual(h.asset_type, "FUND")
        self.assertEqual(h.currency, "USD")
        self.assertAlmostEqual(h.value, 8.6390 * 1.3410, places=3)

    def test_single_letter_symbol_and_ar_stock(self):
        self.assertEqual(self.by["C"].asset_type, "CEDEAR")     # símbolo de 1 letra
        self.assertEqual(self.by["GGAL"].asset_type, "")        # acción AR → .BA

    def test_completeness_reconciles_no_warning(self):
        self.assertEqual(self.snap.warnings, [])

    def test_truncated_read_warns(self):
        # Sacamos una fila (AAPL) pero dejamos el total declarado → la suma NO cuadra.
        truncated = _TXT.replace(
            "Cedear Apple Inc. AAPL BCBA 25,0000 AR$ 22640,000 566000,000\n", "")
        snap = parse_iol_tenencia(truncated)
        self.assertTrue(any("no cuadra" in w for w in snap.warnings), snap.warnings)

    def test_missing_total_line_warns(self):
        # Sin línea de total (OCR se la comió) NO hay ancla → avisa (no marca completa).
        # _HEAD sin la línea 'Títulos Valorizados' y sin el 'Saldo Total' (que va en _TXT).
        no_total = _HEAD.replace("Títulos Valorizados AR$ 612055,92\n", "")
        snap = parse_iol_tenencia(no_total)
        self.assertIsNone(snap.total_ars)
        self.assertTrue(snap.holdings)
        self.assertTrue(any("verificar" in w for w in snap.warnings), snap.warnings)

    def test_bond_keywords_tag_ON_and_ar_bonds(self):
        self.assertEqual(_iol_asset_type("ON YPF 2026 Clase XXXIX"), "BOND")
        self.assertEqual(_iol_asset_type("Bopreal Serie 1"), "BOND")
        self.assertEqual(_iol_asset_type("Bono Rep. Argentina Usd Step Up 2030"), "BOND")
        self.assertEqual(_iol_asset_type("Cedear Apple Inc."), "CEDEAR")
        self.assertEqual(_iol_asset_type("Grupo Financiero Galicia S.A"), "")


if __name__ == "__main__":
    unittest.main()
