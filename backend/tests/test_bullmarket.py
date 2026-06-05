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
        # Caución → debe descartarse
        [datetime(2025, 8, 7), datetime(2025, 8, 7), "COMPRA CAUCION CONTADO", 6165202, 72, "VARIAS", 14082.147006, -1013914.58, -720295.8, None],
        [datetime(2025, 8, 8), datetime(2025, 8, 7), "VENTA CAUCION TERMINO", 6188676, -124, "VARIAS", 14878.704946, 1844959.41, 1124663.61, None],
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

    def test_keeps_only_real_ops(self):
        """Descarta cauciones (2) + FCI (2); deja compra, venta, depósito, retiro."""
        r = self._parse()
        self.assertEqual(len(r.raw_rows), 4)
        self.assertEqual(len(r.parse_errors), 0)
        tipos = sorted(row.data["tipo"] for row in r.raw_rows)
        self.assertEqual(tipos, ["COMPRA", "DEPOSITO", "RETIRO", "VENTA"])

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


if __name__ == "__main__":
    unittest.main()
