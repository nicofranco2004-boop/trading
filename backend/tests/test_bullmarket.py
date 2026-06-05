"""Tests del parser de Bull Market + lectura de Excel (.xlsx).

Usa un xlsx SINTÉTICO construido en memoria (no datos reales de nadie) que
cubre cada tipo de comprobante: compra, venta, depósito, retiro, caución
(descartada) y FCI (descartado), más el mapeo YPF→YPFD.

Corre con: cd backend && python3 -m pytest tests/test_bullmarket.py
"""
import io
import os
import sys
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import openpyxl

from importing.excel import is_xlsx, xlsx_to_csv, to_csv_text
from importing.parsers.bullmarket import BullMarketParser


def _build_bm_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cuenta Corriente PESOS 05-06-26"
    ws.append(["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
               "Especie", "Precio", "Importe", "Saldo", "Referencia"])
    rows = [
        [datetime(2025, 6, 21), datetime(2025, 6, 20), "COMPRA NORMAL", 5250025, 8, "YPF", 20591.677275, -164733.42, -164733.42, None],
        [datetime(2025, 6, 24), datetime(2025, 6, 21), "VENTA", 5308533, -7, "GGAL", 27478.848015, 192351.94, 27618.78, None],
        [datetime(2025, 8, 12), datetime(2025, 8, 12), "RECIBO DE COBRO", 1176600, 0, None, 0, 1003000, 1030618.78, "CREDITO CTA. CTE."],
        [datetime(2025, 8, 11), datetime(2025, 8, 11), "ORDEN DE PAGO", 1240291, 0, None, 0, -737000, 293618.78, "TRANSFERENCIA VIA MEP"],
        # Cauciones → no se cargan como activo; su neto (+5000) se carga como INTERÉS
        [datetime(2025, 8, 7), datetime(2025, 8, 7), "COMPRA CAUCION CONTADO", 6165202, 72, "VARIAS", 14082.147006, -1000000, -1000000, None],
        [datetime(2025, 8, 8), datetime(2025, 8, 8), "VENTA CAUCION TERMINO", 6188676, -124, "VARIAS", 14878.704946, 1005000, 5000, None],
        # FCI → debe descartarse
        [datetime(2025, 6, 28), datetime(2025, 6, 28), "SUSCRIPCION FCI", 478531, 0, "PPII", 0, -5060.18, -725355.98, None],
        [datetime(2025, 8, 12), datetime(2025, 8, 12), "LIQUIDACION RESCATE FCI", 766535, -800, "PPII", 7.514478, 6011.58, -719344.4, None],
    ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestExcelReader(unittest.TestCase):
    def setUp(self):
        self.xlsx = _build_bm_xlsx()

    def test_is_xlsx_detects_magic_bytes(self):
        self.assertTrue(is_xlsx(self.xlsx))
        self.assertFalse(is_xlsx(b"Liquida,Operado,Comprobante\n2025-01-01,..."))
        self.assertFalse(is_xlsx(b""))

    def test_xlsx_to_csv_first_sheet_iso_dates(self):
        csv_text = xlsx_to_csv(self.xlsx)
        lines = csv_text.strip().split("\n")
        self.assertTrue(lines[0].startswith("Liquida,Operado,Comprobante"))
        # Fecha ISO en la primera fila de datos
        self.assertIn("2025-06-21,2025-06-20,COMPRA NORMAL", lines[1])

    def test_to_csv_text_handles_both(self):
        # xlsx → convierte; csv en texto → decodifica
        self.assertIn("COMPRA NORMAL", to_csv_text(self.xlsx))
        self.assertIn("hola", to_csv_text(b"col\nhola"))


class TestBullMarketParser(unittest.TestCase):
    def setUp(self):
        self.parser = BullMarketParser()
        self.csv = to_csv_text(_build_bm_xlsx())

    def _parse(self):
        return self.parser.parse(self.csv, file_name="bm.xlsx")

    def test_keeps_real_ops_plus_caucion_interest(self):
        """Descarta FCI (2); deja compra, venta, depósito, retiro + 1 fila de
        INTERÉS con el neto de las cauciones."""
        r = self._parse()
        self.assertEqual(len(r.raw_rows), 5)
        self.assertEqual(len(r.parse_errors), 0)
        tipos = sorted(row.data["tipo"] for row in r.raw_rows)
        self.assertEqual(tipos, ["COMPRA", "DEPOSITO", "INTERES", "RETIRO", "VENTA"])

    def test_caucion_net_becomes_interest_gain(self):
        """El neto de cauciones (+5000) se carga como INTERÉS (ganancia), sin
        activo y sin crear VARIAS."""
        r = self._parse()
        interes = next(x for x in r.raw_rows if x.data["tipo"] == "INTERES")
        self.assertEqual(float(interes.data["monto"]), 5000.0)
        self.assertEqual(interes.data["activo"], "")
        self.assertEqual(interes.data["moneda"], "ARS")
        self.assertIn("caucion", interes.data["notas"].lower())

    def test_no_caucion_no_fci_assets(self):
        r = self._parse()
        activos = {row.data["activo"] for row in r.raw_rows}
        self.assertNotIn("VARIAS", activos)
        self.assertNotIn("PPII", activos)

    def test_ypf_mapped_to_ypfd(self):
        r = self._parse()
        compra = next(x for x in r.raw_rows if x.data["tipo"] == "COMPRA")
        self.assertEqual(compra.data["activo"], "YPFD")
        self.assertEqual(compra.data["moneda"], "ARS")
        self.assertEqual(compra.data["broker"], "Bull Market")

    def test_abs_values_and_date_from_operado(self):
        r = self._parse()
        venta = next(x for x in r.raw_rows if x.data["tipo"] == "VENTA")
        # Cantidad venía -7 → abs; monto venía 192351.94
        self.assertEqual(float(venta.data["cantidad"]), 7.0)
        self.assertEqual(float(venta.data["monto"]), 192351.94)
        self.assertEqual(venta.data["fecha"], "2025-06-21")  # Operado, no Liquida

    def test_cash_flows_have_no_asset(self):
        r = self._parse()
        dep = next(x for x in r.raw_rows if x.data["tipo"] == "DEPOSITO")
        ret = next(x for x in r.raw_rows if x.data["tipo"] == "RETIRO")
        self.assertEqual(dep.data["activo"], "")
        self.assertEqual(float(dep.data["monto"]), 1003000.0)
        self.assertEqual(ret.data["activo"], "")
        self.assertEqual(float(ret.data["monto"]), 737000.0)

    def test_can_handle_headers(self):
        self.assertTrue(self.parser.can_handle(
            ["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
             "Especie", "Precio", "Importe", "Saldo", "Referencia"]))
        self.assertFalse(self.parser.can_handle(["foo", "bar", "baz"]))


class TestBullMarketMultiCurrency(unittest.TestCase):
    """Multi-moneda: la moneda sale del nombre de la hoja (columna _hoja que
    agrega el conversor de Excel). Dólares: dividendos = ganancia; las
    conversiones cable↔MEP (NOTA DE CRÉDITO/DÉBITO U$S) se omiten."""

    HEADER = ("Liquida,Operado,Comprobante,Numero,Cantidad,Especie,Precio,"
              "Importe,Saldo,Referencia,_hoja\n")

    def _parse(self, body):
        return BullMarketParser().parse(self.HEADER + body)

    def test_currency_detected_per_row_from_sheet(self):
        body = (
            "2025-06-21,2025-06-20,COMPRA NORMAL,1,8,YPF,20591.67,-164733.42,-164733.42,,Cuenta Corriente PESOS 05-06-26\n"
            "2025-06-18,2025-06-18,DIVIDENDOS,2,0,GOOGL,0,0.28,0.28,GOOGL BYMA,Cuenta Corriente DOLARES CABLE 05-06-26\n"
        )
        r = self._parse(body)
        by = {x.data["tipo"]: x.data for x in r.raw_rows}
        self.assertEqual(by["COMPRA"]["moneda"], "ARS")
        self.assertEqual(by["COMPRA"]["activo"], "YPFD")
        self.assertEqual(by["DIVIDENDO"]["moneda"], "USD")
        self.assertEqual(by["DIVIDENDO"]["activo"], "GOOGL")
        self.assertEqual(float(by["DIVIDENDO"]["monto"]), 0.28)

    def test_usd_internal_conversions_skipped(self):
        body = (
            "2025-05-07,2025-05-07,NOTA DE CREDITO U$S,1,0,,0,4.32,4.73,conv cable a me,Cuenta Corriente DOLARES 05-06-26\n"
            "2025-05-07,2025-05-07,NOTA DE DEBITOS U$S,2,0,,0,-4.32,0,conv cable a me,Cuenta Corriente DOLARES CABLE 05-06-26\n"
        )
        r = self._parse(body)
        self.assertEqual(len(r.raw_rows), 0)  # conversiones cable↔MEP → no se importan
        self.assertEqual(len(r.parse_errors), 0)

    def test_usd_caucion_interest_separate_from_ars(self):
        body = (
            "2025-08-07,2025-08-07,COMPRA CAUCION CONTADO,1,1,VARIAS,1,-100,-100,,Cuenta Corriente DOLARES 05-06-26\n"
            "2025-08-08,2025-08-08,VENTA CAUCION TERMINO,2,-1,VARIAS,1,103,3,,Cuenta Corriente DOLARES 05-06-26\n"
        )
        r = self._parse(body)
        interes = [x for x in r.raw_rows if x.data["tipo"] == "INTERES"]
        self.assertEqual(len(interes), 1)
        self.assertEqual(interes[0].data["moneda"], "USD")
        self.assertEqual(float(interes[0].data["monto"]), 3.0)


if __name__ == "__main__":
    unittest.main()
