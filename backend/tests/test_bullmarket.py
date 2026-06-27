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
        # FCI → el CASH reconcilia: suscripción (sin cantidad) = RETIRO; rescate
        # (con cantidad+precio) = VENTA del fondo. La tenencia del FCI sigue siendo
        # follow-up (la suscripción no trae unidades).
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
        """Deja compra, venta, depósito, retiro + 1 INTERÉS (neto cauciones) + el
        cash del FCI (suscripción→RETIRO, rescate→VENTA). Nada se flaggea."""
        r = self._parse()
        self.assertEqual(len(r.raw_rows), 7)
        self.assertEqual(len(r.parse_errors), 0)
        tipos = sorted(row.data["tipo"] for row in r.raw_rows)
        self.assertEqual(tipos, ["COMPRA", "DEPOSITO", "INTERES", "RETIRO", "RETIRO", "VENTA", "VENTA"])

    def test_caucion_net_becomes_interest_gain(self):
        """El neto de cauciones (+5000) se carga como INTERÉS (ganancia), sin
        activo y sin crear VARIAS."""
        r = self._parse()
        interes = next(x for x in r.raw_rows if x.data["tipo"] == "INTERES")
        self.assertEqual(float(interes.data["monto"]), 5000.0)
        self.assertEqual(interes.data["activo"], "")
        self.assertEqual(interes.data["moneda"], "ARS")
        self.assertIn("caucion", interes.data["notas"].lower())

    def test_caucion_no_asset_fci_cash_reconciles(self):
        # Caución (VARIAS) = caja, nunca activo. FCI: el RESCATE sí crea el activo
        # (VENTA con cantidad+precio); la SUSCRIPCION sin cantidad es solo cash
        # (RETIRO) → el cash del FCI reconcilia sin inventar una tenencia falsa.
        r = self._parse()
        self.assertNotIn("VARIAS", {row.data["activo"] for row in r.raw_rows})
        by = {}
        for row in r.raw_rows:
            by.setdefault(row.data["tipo"], []).append(row.data)
        rescate = [d for d in by.get("VENTA", []) if d["activo"] == "PPII"]
        self.assertEqual(len(rescate), 1)
        self.assertEqual(float(rescate[0]["monto"]), 6011.58)
        susc = [d for d in by.get("RETIRO", []) if abs(float(d["monto"]) - 5060.18) < 1e-6]
        self.assertEqual(len(susc), 1)

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


class TestBullMarketNewTypes(unittest.TestCase):
    """Tipos que aparecen en los exports de DÓLARES/CABLE y en PESOS más amplios:
    trades de bono (COMPRA/VENTA PARIDAD), título del exterior, renta+amortización,
    retenciones y dividendos con signo invertido. Regla: `Importe` = efecto en caja
    → el tipo se elige por el SIGNO para reconciliar por construcción."""

    HEADER = ("Liquida,Operado,Comprobante,Numero,Cantidad,Especie,Precio,"
              "Importe,Saldo,Referencia,_hoja\n")
    DOL = "Cuenta Corriente DOLARES 25-06-26"
    PES = "Cuenta Corriente PESOS 25-06-26"

    def _parse(self, body):
        return BullMarketParser().parse(self.HEADER + body)

    def _by(self, r):
        d = {}
        for x in r.raw_rows:
            d.setdefault(x.data["tipo"], []).append(x.data)
        return d

    def test_compra_y_venta_paridad_son_trades(self):
        body = (
            f"2025-07-14,2025-07-11,COMPRA PARIDAD,1,688,TLCPO,1.05577,-726.37,1.75,,{self.DOL}\n"
            f"2025-09-18,2025-09-17,VENTA PARIDAD,2,-1439,MTCGO,1.002036,1441.93,1443,,{self.DOL}\n"
        )
        by = self._by(self._parse(body))
        self.assertEqual(by["COMPRA"][0]["activo"], "TLCPO")
        self.assertEqual(float(by["COMPRA"][0]["cantidad"]), 688)
        self.assertEqual(float(by["COMPRA"][0]["monto"]), 726.37)
        self.assertEqual(by["VENTA"][0]["activo"], "MTCGO")
        self.assertEqual(float(by["VENTA"][0]["cantidad"]), 1439)

    def test_renta_y_amortiz_y_exterior(self):
        body = (
            f"2025-07-10,2025-07-10,RENTA Y AMORTIZ,1,0,AL30,0,230.73,231,AL30 BYMA,{self.DOL}\n"
            f"2025-07-01,2025-07-01,COMPRA EXTERIOR V,2,4,NKE,80,-320,0,,{self.DOL}\n"
        )
        by = self._by(self._parse(body))
        self.assertEqual(by["DIVIDENDO"][0]["activo"], "AL30")          # cupón/amort = ingreso
        self.assertEqual(float(by["DIVIDENDO"][0]["monto"]), 230.73)
        self.assertEqual(by["COMPRA"][0]["activo"], "NKE")             # exterior = compra

    def test_retencion_es_fee_y_dividendo_negativo_tambien(self):
        # RETENCION (sale) → FEE; un "DIVIDENDOS" con Importe NEGATIVO (retención
        # disfrazada) también → FEE, no ingreso (reconciliación por signo).
        body = (
            f"2025-07-02,2025-07-02,RETENCION,1,0,,0,-269.26,0,,{self.PES}\n"
            f"2025-07-02,2025-07-02,DIVIDENDOS,2,0,GGAL,0,-269.26,0,,{self.PES}\n"
        )
        r = self._parse(body)
        self.assertEqual(r.parse_errors, [])
        fees = self._by(r).get("FEE", [])
        self.assertEqual(len(fees), 2)
        self.assertTrue(all(float(f["monto"]) == 269.26 for f in fees))

    def test_rec_cobro_dolares_es_deposito(self):
        # Variante abreviada "REC COBRO DOLARES" (USD) = depósito, igual que
        # "RECIBO DE COBRO". Antes caía como tipo no soportado.
        body = f"2025-06-26,2025-06-26,REC COBRO DOLARES,1,0,MEP,0,39.12,40,CREDITO CTA. CTE.,{self.DOL}\n"
        r = self._parse(body)
        self.assertEqual(r.parse_errors, [])
        dep = self._by(r)["DEPOSITO"][0]
        self.assertEqual(dep["moneda"], "USD")
        self.assertEqual(float(dep["monto"]), 39.12)

    def test_fci_cash_reconcilia(self):
        # SUSCRIPCION FCI (sin cantidad) → RETIRO ; LIQUIDACION RESCATE FCI (con
        # cantidad+precio) → VENTA del fondo. El cash neto reconcilia.
        body = (
            f"2025-06-28,2025-06-28,SUSCRIPCION FCI,1,0,BZCAAAA,0,-50944.24,0,,{self.PES}\n"
            f"2025-06-29,2025-06-29,LIQUIDACION RESCATE FCI,2,-922.11,BZCAAAA,152.21,140358.39,0,,{self.PES}\n"
        )
        r = self._parse(body)
        self.assertEqual(r.parse_errors, [])
        by = self._by(r)
        self.assertEqual(float(by["RETIRO"][0]["monto"]), 50944.24)
        self.assertEqual(by["VENTA"][0]["activo"], "BZCAAAA")
        self.assertEqual(float(by["VENTA"][0]["monto"]), 140358.39)
        # cash neto = -50944.24 + 140358.39 = +89414.15
        net = -float(by["RETIRO"][0]["monto"]) + float(by["VENTA"][0]["monto"])
        self.assertAlmostEqual(net, 89414.15, places=2)

    def test_reconcilia_por_signo(self):
        # Σ del cash emitido (firmado por tipo) = Σ Importe del archivo.
        body = (
            f"2025-07-01,2025-07-01,RECIBO DE COBRO,1,0,,0,1000,1000,,{self.PES}\n"
            f"2025-07-02,2025-07-02,COMPRA NORMAL,2,20,GGB,14501,-290021.18,0,,{self.PES}\n"
            f"2025-07-03,2025-07-03,VENTA,3,-26,T,11717,304646.88,0,,{self.PES}\n"
            f"2025-07-04,2025-07-04,RENTA Y AMORTIZ,4,0,AL30,0,11860,0,,{self.PES}\n"
            f"2025-07-05,2025-07-05,RETENCION,5,0,,0,-1745,0,,{self.PES}\n"
            f"2025-07-06,2025-07-06,ORDEN DE PAGO,6,0,,0,-22614.97,0,,{self.PES}\n"
        )
        importes = [1000, -290021.18, 304646.88, 11860, -1745, -22614.97]
        r = self._parse(body)
        self.assertEqual(r.parse_errors, [])
        OUT = {"COMPRA", "RETIRO", "FEE"}
        IN = {"VENTA", "DEPOSITO", "DIVIDENDO", "INTERES"}
        emit = sum((-float(x.data["monto"]) if x.data["tipo"] in OUT
                    else float(x.data["monto"]) if x.data["tipo"] in IN else 0)
                   for x in r.raw_rows if x.data.get("monto"))
        self.assertAlmostEqual(emit, sum(importes), places=2)


if __name__ == "__main__":
    unittest.main()
