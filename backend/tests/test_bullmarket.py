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


class TestBullMarketMovimientos(unittest.TestCase):
    """Layout 'Movimientos' (CSV compacto, distinto a la Cuenta Corriente):
    columna `Cpbt.` con CÓDIGOS, cantidad+precio PEGADOS en un campo, signo de
    Importe INVERTIDO (negativo = ingreso) y fechas dd/mm/aa (año 2 dígitos).
    Datos SINTÉTICOS (no de nadie). Mismo `format_id='bullmarket'`: el parser
    detecta el layout por el header y despacha solo."""

    MOV = (
        "Liquida;Operado;Cpbt.;Numero;Importe;Especie;Referencia/Cantidad/Precio\n"
        "07/08/23;07/08/23;COBA;806694;-100000;;CREDITO CTA. CTE.\n"
        "08/08/23;08/08/23;CPRA;3677542;7323,04;CRM;1                       7272.0000\n"
        "13/12/23;11/12/23;VTAS;7635587;-899,65;IRSA;-1                       906.0000\n"
        "18/09/23;18/09/23;PAGA;489915;3993,23;;TRANSFERENCIA VIA MEP\n"
        # MEP: compra de AL30 en pesos + venta paridad (VTU$) → bono netea a 0; la
        # compra en pesos se carga como RETIRO ("Dólar MEP vía AL30").
        "20/12/23;20/12/23;CPRA;7950889;99025,15;AL30;267                    36903.0000\n"
        "21/12/23;21/12/23;VTU$;7981867;;AL30;-267                   31068.3596\n"
        # FCI: suscripción (cash out) → RETIRO ; rescate (con cantidad) → VENTA.
        "23/08/24;23/08/24;SFCI;355160;10000;CONAAFA;\n"
        "04/11/24;01/11/24;LRFD;466687;-11857;CONAAFA;-1.1972                    0.0000\n"
        # Dividendos: sin monto se omiten; con monto cuentan, y el SIGNO manda
        # (negativo = entró plata → DIVIDENDO; positivo = salió → retención/FEE).
        "18/08/23;18/08/23;DIV;763092;;AAPL;\n"
        "11/06/24;11/06/24;DIV;427507;-676,63;NVDA;\n"
        "12/06/24;12/06/24;DIV;427508;45,5;NVDA;\n"
        # Bono RETENIDO (no MEP): precio viene per-100 → se pasa a per-1.
        "12/07/24;12/07/24;CPRA;5856212;322778,86;TX26;450                    71370.0000\n"
        # Filas de leyenda/totales al pie (sin fecha) → se saltean.
        ";;;;-11,35;CDIV;PAGO DIV\n"
        ";;;;6477189,46;CPRA;COMPRA\n"
    )

    def setUp(self):
        self.r = BullMarketParser().parse(self.MOV, file_name="bmb.CSV")

    def _by(self):
        d = {}
        for x in self.r.raw_rows:
            d.setdefault(x.data["tipo"], []).append(x.data)
        return d

    def test_can_handle_cpbt_layout(self):
        self.assertTrue(BullMarketParser().can_handle(
            ["Liquida", "Operado", "Cpbt.", "Numero", "Importe", "Especie",
             "Referencia/Cantidad/Precio"]))

    def test_not_silently_empty(self):
        # Regresión: antes el header 'Cpbt.' no matcheaba 'Comprobante' y todas las
        # filas se salteaban → import VACÍO sin error. Ahora produce filas.
        self.assertGreater(len(self.r.raw_rows), 0)
        self.assertEqual(len(self.r.parse_errors), 0)

    def test_row_count_and_types(self):
        # 1 DEPOSITO + 2 COMPRA (CRM, TX26) + 2 VENTA (IRSA, CONAAFA-rescate)
        # + 3 RETIRO (PAGA, MEP-AL30, SFCI) + 1 DIVIDENDO (NVDA) + 1 FEE (la
        # retención de NVDA) = 10. VTU$, el DIV sin monto y la leyenda → 0.
        self.assertEqual(len(self.r.raw_rows), 10)
        tipos = sorted(x.data["tipo"] for x in self.r.raw_rows)
        self.assertEqual(
            tipos, ["COMPRA", "COMPRA", "DEPOSITO", "DIVIDENDO", "FEE", "RETIRO",
                    "RETIRO", "RETIRO", "VENTA", "VENTA"])

    def test_inverted_signs_cash(self):
        by = self._by()
        dep = by["DEPOSITO"][0]
        self.assertEqual(dep["activo"], "")
        self.assertEqual(float(dep["monto"]), 100000.0)   # COBA -100000 → DEPOSITO
        pagos = [d for d in by["RETIRO"] if "MEP" not in d["notas"]
                 and float(d["monto"]) == 3993.23]
        self.assertEqual(len(pagos), 1)                    # PAGA +3993.23 → RETIRO

    def test_merged_qty_price_split_and_iso_date(self):
        compra_crm = next(d for d in self._by()["COMPRA"] if d["activo"] == "CRM")
        self.assertEqual(float(compra_crm["cantidad"]), 1.0)
        self.assertEqual(float(compra_crm["precio"]), 7272.0)
        self.assertEqual(float(compra_crm["monto"]), 7323.04)
        self.assertEqual(compra_crm["fecha"], "2023-08-08")  # dd/mm/aa → ISO
        venta_irsa = next(d for d in self._by()["VENTA"] if d["activo"] == "IRSA")
        self.assertEqual(float(venta_irsa["cantidad"]), 1.0)  # -1 → abs
        self.assertEqual(venta_irsa["fecha"], "2023-12-11")   # Operado, no Liquida

    def test_mep_nets_bond_and_records_peso_outflow(self):
        # AL30 NO queda como tenencia; la compra en pesos es un RETIRO "Dólar MEP".
        activos = {x.data["activo"] for x in self.r.raw_rows}
        self.assertNotIn("AL30", activos)
        mep = [d for d in self._by()["RETIRO"] if "Dólar MEP vía AL30" in d["notas"]]
        self.assertEqual(len(mep), 1)
        self.assertEqual(float(mep[0]["monto"]), 99025.15)
        self.assertEqual(mep[0]["activo"], "")

    def test_dividends_solo_los_que_traen_monto(self):
        # DIV/CDIV/RTA SIN monto se omiten (no hay nada que registrar); CON monto
        # se importan. La columna Saldo del export los acumula, así que saltearlos
        # descuadraba la caja — en el histórico de un usuario real eran $70M de
        # renta de bonos que quedaban afuera (reporte 2026-07-29).
        by = self._by()
        divs = by.get("DIVIDENDO", [])
        self.assertEqual(len(divs), 1)                  # el DIV de AAPL no trae monto
        self.assertEqual(divs[0]["activo"], "NVDA")
        self.assertEqual(float(divs[0]["monto"]), 676.63)
        # El de signo invertido es una retención, no un ingreso
        fees = by.get("FEE", [])
        self.assertEqual([float(f["monto"]) for f in fees], [45.5])

    def test_fci_cash_reconciles(self):
        by = self._by()
        susc = [d for d in by["RETIRO"] if float(d["monto"]) == 10000.0]
        self.assertEqual(len(susc), 1)                     # SFCI → RETIRO
        rescate = next(d for d in by["VENTA"] if d["activo"] == "CONAAFA")
        self.assertEqual(float(rescate["monto"]), 11857.0)  # LRFD → VENTA
        self.assertAlmostEqual(float(rescate["cantidad"]), 1.1972, places=4)

    def test_held_bond_per100_to_per1(self):
        tx26 = next(d for d in self._by()["COMPRA"] if d["activo"] == "TX26")
        # precio venía per-100 (71370) → per-1 = 713.70
        self.assertAlmostEqual(float(tx26["precio"]), 713.70, places=2)
        self.assertEqual(float(tx26["cantidad"]), 450.0)


if __name__ == "__main__":
    unittest.main()


class TestBullMarketHistorico(unittest.TestCase):
    """Export "Histórico de cuenta corriente" — el que Bull Market MANDA POR MAIL
    a las cuentas con historia larga (reporte de un usuario, 2026-07-29). Mismo
    layout de códigos que Movimientos pero SIN la columna `Operado` (el gate lo
    rechazaba entero), con cauciones, futuros de dólar A3 y la LEYENDA de códigos
    al pie. Datos sintéticos con la misma forma que el archivo real."""

    HIST = (
        "Liquida;Cpbt.;Numero;Importe;Saldo;Especie;Referencia/Cantidad/Precio\n"
        "31/12/22;Ant.;;-1000;-1000;;S.ANTERIOR\n"
        "19/01/23;COBA;53066;-100000;-101000;;CREDITO CTA. CTE.\n"
        # Caución: colocó 50.000 y volvieron 50.400 → 400 de interés, sin activo.
        "20/01/23;CCDO;553763;50000;-51000;VARIAS;100                    50000.0000\n"
        "21/01/23;VTCT;553764;-50400;-101400;VARIAS;-100                  50400.0000\n"
        # Futuros de dólar A3: ganancia 900 y pérdida 300 → neto +600, sin activo.
        "22/01/23;CRGI;468435;-900;-102300;DLR072023;\n"
        "23/01/23;DBPI;449982;300;-102000;DLR072023;\n"
        # MEP comprando dólares: CPRA (sale plata) + VTU$ (pata dólar, sin importe)
        "24/01/23;CPRA;251989;40000;-62000;AL30;1000                      40.0000\n"
        "25/01/23;VTU$;269422;;-62000;AL30;-1000                     32.0000\n"
        # MEP VENDIENDO dólares: CPU$ (pata dólar) + VTAS (ENTRA plata en pesos).
        # Este par se descartaba entero y se perdía el ingreso.
        "26/01/23;CPU$;1244685;;-62000;AL30;500                       33.0000\n"
        "27/01/23;VTAS;1245671;-21000;-83000;AL30;-500                      42.0000\n"
        # Compra y venta comunes de OTRA cantidad del mismo bono (no son MEP).
        "28/01/23;CPRA;251990;12000;-71000;AL30;300                       40.0000\n"
        "29/01/23;VTAS;1245672;-13000;-84000;AL30;-300                      43.3333\n"
        # Renta de bono CON monto: es cash real, tiene que contar.
        "30/01/23;RTA;232438;-5000;-89000;S31M3;\n"
        "31/01/23;DREP;894647;200;-88800;;BYMA RETENCION\n"
        "31/01/23;PAGA;29070;88800;0;;TRANSFERENCIA VIA MEP\n"
        # Leyenda del pie (sin fecha): código → descripción larga.
        ";;;;;CCDO;COMPRA CAUCION CONTADO\n"
        ";;;;;VTCT;VENTA  CAUCION TERMINO\n"
        ";;;;;COBA;RECIBO DE COBRO\n"
        ";;;;;PAGA;ORDEN  DE PAGO\n"
        ";;;;;CPRA;COMPRA\n"
        ";;;;;VTAS;VENTA\n"
        ";;;;;RTA;RENTA Y AMORTIZ\n"
        ";;;;;DREP;RETENCION\n"
        ";;;;;CRGI;CREDITO POR GANANCIA INDICE\n"
        ";;;;;DBPI;DEBITO POR PERDIDA INDICE\n"
        ";Total;;-88800;;;\n"
    )

    @classmethod
    def setUpClass(cls):
        cls.r = BullMarketParser().parse(cls.HIST, "HC40419.CSV")

    def _by(self):
        out = {}
        for x in self.r.raw_rows:
            out.setdefault(x.data["tipo"], []).append(x.data)
        return out

    def test_se_acepta_sin_columna_operado(self):
        # El bug reportado: el gate exigía `Operado` y rechazaba el archivo con
        # "no parece un export de Bull Market".
        self.assertEqual(self.r.parse_errors, [])
        self.assertTrue(self.r.raw_rows)

    def test_la_caja_cierra_con_el_saldo_del_broker(self):
        # Invariante fuerte: reconstruir el cash desde lo importado tiene que dar
        # el saldo final del propio archivo (acá 88.800 de salida → 0).
        signo = {"DEPOSITO": 1, "VENTA": 1, "DIVIDENDO": 1, "INTERES": 1,
                 "RETIRO": -1, "COMPRA": -1, "FEE": -1}
        cash = sum(signo[x.data["tipo"]] * float(x.data["monto"] or 0)
                   for x in self.r.raw_rows)
        self.assertAlmostEqual(cash, 0.0, places=2)

    def test_mep_vendiendo_dolares_entra_como_deposito(self):
        # CPU$ + VTAS del mismo lote (500) → DEPOSITO, no VENTA del bono.
        dep = [d for d in self._by()["DEPOSITO"] if "MEP" in d["notas"]]
        self.assertEqual(len(dep), 1)
        self.assertEqual(float(dep[0]["monto"]), 21000.0)
        self.assertEqual(dep[0]["activo"], "")          # el bono netea, no es tenencia

    def test_mep_comprando_dolares_sale_como_retiro(self):
        ret = [d for d in self._by()["RETIRO"] if "Dólar MEP" in d["notas"]]
        self.assertEqual(len(ret), 1)
        self.assertEqual(float(ret[0]["monto"]), 40000.0)

    def test_compraventa_comun_del_mismo_bono_no_se_come(self):
        # La regresión que motivó el fix: antes se descartaba TODA fila de una
        # especie que alguna vez hizo MEP → se perdían ventas reales.
        by = self._by()
        compra = [d for d in by["COMPRA"] if d["activo"] == "AL30"]
        venta = [d for d in by["VENTA"] if d["activo"] == "AL30"]
        self.assertEqual(len(compra), 1)
        self.assertEqual(float(compra[0]["cantidad"]), 300.0)
        self.assertEqual(len(venta), 1)
        self.assertEqual(float(venta[0]["monto"]), 13000.0)

    def test_cauciones_y_futuros_netean_sin_crear_activos(self):
        by = self._by()
        # Caución: 50.400 − 50.000 = 400 de interés. Futuros: 900 − 300 = 600.
        intereses = {d["notas"]: float(d["monto"]) for d in by["INTERES"]}
        self.assertEqual(intereses.get("Neto de cauciones"), 400.0)
        self.assertEqual(intereses.get("Neto de futuros de dólar (A3)"), 600.0)
        # Y NO entran como tenencias fantasma
        activos = {x.data["activo"] for x in self.r.raw_rows}
        self.assertNotIn("VARIAS", activos)
        self.assertNotIn("DLR072023", activos)

    def test_saldo_anterior_entra_como_cash_inicial(self):
        dep = [d for d in self._by()["DEPOSITO"] if d["notas"] == "Saldo anterior"]
        self.assertEqual(len(dep), 1)
        self.assertEqual(float(dep[0]["monto"]), 1000.0)

    def test_renta_con_monto_cuenta_y_retencion_es_fee(self):
        by = self._by()
        self.assertEqual(float(by["DIVIDENDO"][0]["monto"]), 5000.0)   # RTA
        fees = [d for d in by["FEE"] if float(d["monto"]) == 200.0]
        self.assertEqual(len(fees), 1)                                 # DREP


class TestBullMarketIndiceA3CuentaCorriente(unittest.TestCase):
    """Futuros de dólar en A3/Matba-Rofex dentro del layout Cuenta Corriente.
    Caían en "tipo de comprobante no soportado" (58 filas en el export real de
    un usuario) y su resultado se perdía. Ahora netean como las cauciones."""

    HEADER = ("Liquida,Operado,Comprobante,Numero,Cantidad,Especie,Precio,"
              "Importe,Saldo,Referencia\n")
    CSV = HEADER + (
        "2025-07-24,2025-07-24,RECIBO DE COBRO,1,0,,0,100000,100000,CREDITO CTA. CTE.\n"
        "2025-07-25,2025-07-25,CPRA INDICE A3 MTR,2,2,DLR092025,0,-1000,99000,\n"
        "2025-07-26,2025-07-26,CREDITO POR GANANCIA INDICE,3,0,DLR092025,0,2500,101500,\n"
        "2025-07-27,2025-07-27,DEBITO POR PERDIDA INDICE,4,0,DLR092025,0,-400,101100,\n"
        "2025-07-28,2025-07-28,VTA INDICE A3 MTR,5,-2,DLR092025,0,900,102000,\n"
    )

    @classmethod
    def setUpClass(cls):
        cls.r = BullMarketParser().parse(cls.CSV, "Cuenta Corriente PESOS.xlsx")

    def test_sin_errores_de_comprobante(self):
        self.assertEqual([e.code for e in self.r.parse_errors], [])

    def test_netea_a_una_sola_fila_de_resultado(self):
        # −1000 + 2500 − 400 + 900 = +2000 de ganancia
        fut = [x.data for x in self.r.raw_rows
               if x.data["notas"].startswith("Resultado de futuros")]
        self.assertEqual(len(fut), 1)
        self.assertEqual(fut[0]["tipo"], "INTERES")
        self.assertEqual(float(fut[0]["monto"]), 2000.0)

    def test_no_crea_el_contrato_como_tenencia(self):
        self.assertNotIn("DLR092025", {x.data["activo"] for x in self.r.raw_rows})

    def test_la_caja_cierra(self):
        signo = {"DEPOSITO": 1, "VENTA": 1, "DIVIDENDO": 1, "INTERES": 1,
                 "RETIRO": -1, "COMPRA": -1, "FEE": -1}
        cash = sum(signo[x.data["tipo"]] * float(x.data["monto"] or 0)
                   for x in self.r.raw_rows)
        self.assertAlmostEqual(cash, 102000.0, places=2)   # el saldo del archivo
