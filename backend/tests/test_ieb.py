"""Tests del parser de IEB (Invertir en Bolsa) — mapeo de códigos de operación.

Corre con: cd backend && python3 -m pytest tests/test_ieb.py
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.parsers.ieb import IebParser
from importing.parsers.registry import autodetect

# Fixture: header real de IEB + filas representativas (point-decimal, '-' = vacío).
_CSV = (
    "Referencia,Operación,Fecha emisión,Fecha liquidación,Nro. de operación,"
    "Cantidad,Precio,Importe ARS,Importe divisas,Divisa\n"
    "EWZ,CPRA,2025-07-04 03:00:00,2025-07-04 03:00:00,51085,591,283.13,-167329.83,-,ARS\n"
    "EWZ,VTAS,2025-09-23 03:00:00,2025-09-23 03:00:00,233244,-426,473.57,201740.82,-,ARS\n"
    "AL30,CPRA,2025-12-10 03:00:00,2025-12-10 03:00:00,326109,492,234.82,-115531.44,-,ARS\n"
    "AL30,CPU$,2025-10-03 03:00:00,2025-10-03 03:00:00,249333,270,138.92,-,-37508.4,USD\n"
    "AL30,VTU$,2025-09-12 03:00:00,2025-09-12 03:00:00,219740,-83,84.02,-,6973.66,USD\n"
    "AL30,RENTA,2025-07-10 03:00:00,2025-07-10 03:00:00,57364,-,-,-,260.91,USD\n"
    "AL30,AMORTIZA,2025-07-10 03:00:00,2025-07-10 03:00:00,62458,-,-,-,270.24,USD\n"
    "EWZ,DIV,2025-06-24 03:00:00,2025-06-24 03:00:00,39785,-,-,-3337.3,-,ARS\n"
    "EWZ,DIV,2025-06-24 03:00:00,2025-06-24 03:00:00,40969,-,-,1918.87,-,OTHER\n"
    "CAUCION,CCCD,2025-08-26 03:00:00,2025-08-26 03:00:00,80104,100,-,-5862.63,-,ARS\n"
    "CAUCION,CCTE,2025-08-27 03:00:00,2025-08-27 03:00:00,87772,-100,-,4453.88,-,ARS\n"
    "DOLAR,COUW,2025-12-10 03:00:00,2025-12-10 03:00:00,308302,-,-,-,296,USD\n"
    "DOLAR,PAUW,2026-06-03 03:00:00,2026-06-03 03:00:00,788241,-,-,-,-289,USD\n"
    "EWZ,NDMP,2025-07-08 03:00:00,2025-07-08 03:00:00,52740,-,-,-510,-,ARS\n"
    # Códigos del export real (v2) que el demo no tenía:
    "TGNO4,COBR,2025-08-01 03:00:00,2025-08-01 03:00:00,900001,-,-,1018,-,ARS\n"
    "GGAL,NDIT,2025-08-02 03:00:00,2025-08-02 03:00:00,900002,-,-,-671.09,-,ARS\n"
    "DOLAR,CU$V,2025-08-03 03:00:00,2025-08-03 03:00:00,900003,-,-,-,52,USD\n"
)


class IebParserTest(unittest.TestCase):
    def setUp(self):
        self.res = IebParser().parse(_CSV)
        self.by_nro = {}
        for r in self.res.raw_rows:
            m = re.search(r"Op\. (\d+)", r.data["notas"])
            if m:
                self.by_nro[m.group(1)] = r.data

    def test_autodetect(self):
        p = autodetect("Referencia,Operación,Nro. de operación,Importe ARS,"
                       "Importe divisas,Divisa".split(","))
        self.assertIsNotNone(p)
        self.assertEqual(p.format_id, "ieb")

    def test_all_rows_parsed_no_errors(self):
        self.assertEqual(len(self.res.raw_rows), 17)
        self.assertEqual(len(self.res.parse_errors), 0)

    def test_v2_codes_cobr_ndit_cuv(self):
        # Códigos del export real que rompían el import (eran "no soportado").
        self.assertEqual(self.by_nro["900001"]["tipo"], "DEPOSITO")  # COBR (cobro)
        self.assertEqual(self.by_nro["900002"]["tipo"], "FEE")       # NDIT (nota débito impuesto)
        self.assertEqual((self.by_nro["900003"]["tipo"],
                          self.by_nro["900003"]["moneda"]), ("DEPOSITO", "USD"))  # CU$V

    def test_compra_ars(self):
        d = self.by_nro["51085"]
        self.assertEqual((d["tipo"], d["moneda"], d["activo"]), ("COMPRA", "ARS", "EWZ"))
        self.assertEqual(d["monto"], "167329.83")  # abs del Importe ARS

    def test_venta_ars(self):
        d = self.by_nro["233244"]
        self.assertEqual((d["tipo"], d["moneda"]), ("VENTA", "ARS"))

    def test_dual_currency_same_ticker(self):
        # AL30: comprado en ARS (CPRA), comprado y vendido en USD (CPU$ / VTU$).
        self.assertEqual(self.by_nro["326109"]["moneda"], "ARS")   # CPRA
        self.assertEqual((self.by_nro["249333"]["tipo"],
                          self.by_nro["249333"]["moneda"]), ("COMPRA", "USD"))  # CPU$
        self.assertEqual((self.by_nro["219740"]["tipo"],
                          self.by_nro["219740"]["moneda"]), ("VENTA", "USD"))   # VTU$

    def test_renta_y_amortizacion_usd_son_dividendo(self):
        self.assertEqual((self.by_nro["57364"]["tipo"],
                          self.by_nro["57364"]["moneda"]), ("DIVIDENDO", "USD"))
        self.assertEqual(self.by_nro["62458"]["tipo"], "DIVIDENDO")

    def test_dividendo_bruto_fee_neto_dividendo(self):
        self.assertEqual(self.by_nro["39785"]["tipo"], "FEE")        # negativo (retención)
        self.assertEqual(self.by_nro["40969"]["tipo"], "DIVIDENDO")  # positivo (neto, OTHER)

    def test_caucion_legs(self):
        self.assertEqual(self.by_nro["80104"]["tipo"], "RETIRO")    # CCCD constitución
        self.assertEqual(self.by_nro["87772"]["tipo"], "DEPOSITO")  # CCTE vencimiento

    def test_dolar_fx(self):
        self.assertEqual((self.by_nro["308302"]["tipo"],
                          self.by_nro["308302"]["moneda"]), ("DEPOSITO", "USD"))  # COUW
        self.assertEqual((self.by_nro["788241"]["tipo"],
                          self.by_nro["788241"]["moneda"]), ("RETIRO", "USD"))    # PAUW

    def test_fee(self):
        self.assertEqual(self.by_nro["52740"]["tipo"], "FEE")  # NDMP

    def test_non_asset_buckets_have_no_ticker(self):
        # CAUCION/DOLAR no son activos operables → sin ticker.
        self.assertEqual(self.by_nro["80104"]["activo"], "")
        self.assertEqual(self.by_nro["308302"]["activo"], "")


if __name__ == "__main__":
    unittest.main()
