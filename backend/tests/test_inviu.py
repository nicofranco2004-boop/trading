"""Tests del parser de inviu (Reporte de cuenta corriente)."""
import unittest
from importing.parsers.inviu import InviuParser
from importing.parsers.registry import autodetect
from importing.excel import _rows_to_csv_headerdetect


# CSV como lo deja excel.xlsx_to_csv tras el guard anti-preámbulo: header real +
# filas de sección ("PESOS - $") + movimientos. Cubre las dos monedas.
SAMPLE = (
    "Fecha de Concertación,Fecha de Liquidación,Descripción,Tipo de Operación,"
    "Ticker,Cantidad VN,Precio,Import Bruto,Importe Neto,Saldo,_hoja\n"
    "Disponible - Cartera monetaria,,,,,,,,,,\n"
    "PESOS - $,,,,,,,,,,\n"
    "13/3/2024,13/3/2024,Recibo de Cobro / 103382,Recibo de Cobro,-,-,0,300000,300000,300000,\n"
    "14/3/2024,14/3/2024,Movimiento Manual / Rendimiento diario,-,-,-,0,575.8,575.8,300575.8,\n"
    "13/3/2024,15/3/2024,Boleto / 378418 / CPRA / 2 / NVDA / $,CPRA,NVDA,4,39316.5,-157266,-159321.15,141254.65,\n"
    "14/1/2025,15/1/2025,Boleto / 104377 / VENTA / 1 / AL30 / $,VENTA,AL30,-68,796.6,54168.8,53621.69,195423,\n"
    "23/5/2024,23/5/2024,Dividendo en efectivo / GGAL,Dividendo en efectivo,GGAL,-,0,2715.64,2715.64,198138.64,\n"
    "3/2/2025,3/2/2025,Dividendo en efectivo / SPY,Dividendo en efectivo,SPY,-,0,-457.22,-457.22,197681.42,\n"
    "28/6/2024,28/6/2024,Movimiento Manual / Retención Impositiva GGAL,-,-,-,0,-346.81,-346.81,197334.61,\n"
    "2/12/2025,2/12/2025,Comprobante de Pago / 410804,Comprobante de Pago,-,-,0,-4,-4,197330.61,\n"
    "Dólar MEP - U$S,,,,,,,,,,\n"
    "16/2/2024,16/2/2024,Recibo de Cobro / 69500,Recibo de Cobro,-,-,0,4.61,4.61,4.61,\n"
    "19/2/2024,19/2/2024,Boleto / 251243 / CPRA / 0 / MRCAO / U$S,CPRA,MRCAO,1,0.8447,-0.84,-0.85,3.76,\n"
    "5/6/2024,5/6/2024,Amortización / MRCAO,Amortización,MRCAO,-,0,25.89,25.89,29.65,\n"
)


def _by_tipo(rows, tipo):
    return [r for r in rows if r.data["tipo"] == tipo]


class InviuParseTest(unittest.TestCase):
    def setUp(self):
        self.res = InviuParser().parse(SAMPLE)
        self.rows = self.res.raw_rows

    def test_autodetect(self):
        headers = SAMPLE.splitlines()[0].split(",")
        p = autodetect(headers)
        self.assertIsNotNone(p)
        self.assertEqual(p.format_id, "inviu")

    def test_sin_errores(self):
        self.assertEqual(self.res.parse_errors, [])

    def test_seccion_define_moneda(self):
        # NVDA/AL30/GGAL en PESOS → ARS ; MRCAO en Dólar MEP → USD
        nvda = [r for r in self.rows if r.data.get("activo") == "NVDA"][0]
        self.assertEqual(nvda.data["moneda"], "ARS")
        mrcao_rows = [r for r in self.rows if r.data.get("activo") == "MRCAO"]
        self.assertTrue(mrcao_rows and all(r.data["moneda"] == "USD" for r in mrcao_rows))

    def test_compra_extrae_comision(self):
        nvda = [r for r in self.rows if r.data.get("activo") == "NVDA"][0]
        self.assertEqual(nvda.data["tipo"], "COMPRA")
        self.assertEqual(float(nvda.data["monto"]), 157266.0)         # bruto
        self.assertAlmostEqual(float(nvda.data["comisiones"]), 2055.15, places=2)

    def test_venta_cantidad_abs_y_comision(self):
        al30 = _by_tipo(self.rows, "VENTA")[0]
        self.assertEqual(al30.data["activo"], "AL30")
        self.assertEqual(float(al30.data["cantidad"]), 68.0)          # abs de -68
        self.assertEqual(float(al30.data["monto"]), 54168.8)
        self.assertAlmostEqual(float(al30.data["comisiones"]), 547.11, places=2)

    def test_deposito_y_retiro(self):
        self.assertEqual(len(_by_tipo(self.rows, "DEPOSITO")), 2)     # 2 Recibos
        retiros = _by_tipo(self.rows, "RETIRO")
        self.assertEqual(len(retiros), 1)
        self.assertEqual(float(retiros[0].data["monto"]), 4.0)

    def test_dividendo_positivo_y_negativo(self):
        divs = _by_tipo(self.rows, "DIVIDENDO")
        self.assertTrue(any(r.data.get("activo") == "GGAL" for r in divs))
        # el dividendo negativo (SPY −457.22) va a IMPUESTO, no a DIVIDENDO
        imp = _by_tipo(self.rows, "IMPUESTO")
        self.assertTrue(any(abs(float(r.data["monto"]) - 457.22) < 0.01 for r in imp))

    def test_rendimiento_es_interes(self):
        intr = _by_tipo(self.rows, "INTERES")
        self.assertTrue(any(abs(float(r.data["monto"]) - 575.8) < 0.01 for r in intr))

    def test_retencion_es_impuesto(self):
        imp = _by_tipo(self.rows, "IMPUESTO")
        self.assertTrue(any(abs(float(r.data["monto"]) - 346.81) < 0.01 for r in imp))

    def test_amortizacion_cuenta_como_ingreso(self):
        # v1: amortización → DIVIDENDO (cash in); el nominal lo reconcilia la foto
        divs = _by_tipo(self.rows, "DIVIDENDO")
        self.assertTrue(any(r.data.get("activo") == "MRCAO" and abs(float(r.data["monto"]) - 25.89) < 0.01 for r in divs))

    def test_cash_reconcilia(self):
        # Suma firmada de las tx = saldos finales del sample (ARS 197330.61, USD 29.65)
        sign = {"DEPOSITO": 1, "DIVIDENDO": 1, "INTERES": 1, "RETIRO": -1, "FEE": -1, "IMPUESTO": -1}
        cash = {}
        for r in self.rows:
            d = r.data
            m = float(d.get("monto") or 0)
            c = float(d.get("comisiones") or 0)
            tp = d["tipo"]
            if tp == "VENTA":
                eff = m - c
            elif tp == "COMPRA":
                eff = -(m + c)
            else:
                eff = sign.get(tp, 0) * m
            cash[d["moneda"]] = cash.get(d["moneda"], 0.0) + eff
        # Invariante: cash = Σ Importe Neto (300000+575.8−159321.15+53621.69
        # +2715.64−457.22−346.81−4 = 196783.95 ; 4.61−0.85+25.89 = 29.65).
        self.assertAlmostEqual(cash["ARS"], 196783.95, places=2)
        self.assertAlmostEqual(cash["USD"], 29.65, places=2)


class InviuPreambleTest(unittest.TestCase):
    """El guard anti-preámbulo detecta el header aunque haya filas de título arriba."""
    def test_headerdetect_encuentra_fila_ancha(self):
        rows = [
            ["Reporte de cuenta corriente", "", "", ""],
            ["Rango", "1/1/2024 a 22/8/2026", "", ""],
            ["Fecha", "Descripción", "Importe", "Saldo"],
            ["13/3/2024", "Recibo", "300000", "300000"],
        ]
        csv_out = _rows_to_csv_headerdetect(rows)
        lines = csv_out.splitlines()
        self.assertTrue(lines[0].startswith("Fecha,Descripción,Importe,Saldo"))
        self.assertIn("13/3/2024", lines[1])




# ─── Foto de Tenencias (inviu) ────────────────────────────────────────────────
from importing.tenencia import (
    looks_like_inviu_tenencia, parse_inviu_tenencia, looks_like_ppi_tenencia,
)

# Filas crudas como las devuelve excel.xlsx_to_rows sobre el export real
# (estructura verificada contra Tenencias-202689_*.xlsx; números de fantasía).
TEN_ROWS = [
    [None] * 14,
    ["Fecha de solicitud:", "22/07/2026 12:25:13", None, None, "Comitente:", "202689"] + [None] * 8,
    ["Fecha de valuación:", "23/07/2026"] + [None] * 12,
    ["TC USD MEP:", 1510.881] + [None] * 12,
    ["TC USD CCL:", 1572.42] + [None] * 12,
    [None] * 14,
    ["Tenencias en Portfolio"] + [None] * 13,
    [None] * 14,
    ["Tipo de Activo: Moneda"] + [None] * 13,
    ["Ticker", "Nombre", "Cantidad", "Garantía", "Disponibles", "Moneda",
     "Precio actual", "Monto $", "Equivalente U$S", "Costo (PPC)",
     "Monto invertido", "Resultado", "Var %", "MTM Acumulado"],
    ["ARS", "Pesos", None, 0, 1302.92, "ARS", 1, None, None, 0, None, None, 0, None],
    ["USD", "Dólar", None, 0, 127.49, "ARS", 1510.881, None, None, 0, None, None, 0, None],
    [None, "Subtotal Disponibilidades"] + [None] * 12,
    ["Tipo de Activo: Bonos"] + [None] * 13,
    ["Ticker", "Nombre", "Cantidad", "Garantía", "Disponibles", "Moneda",
     "Precio actual", "Monto $", "Equivalente U$S", "Costo (PPC)",
     "Monto invertido", "Resultado", "Var %", "MTM Acumulado"],
    ["RUCDO", "USD ON MSU Energy Vto. 05/12/2030", None, 0, 1813, "ARS",
     1632, None, None, 1175.146906, None, None, 38.87, None],
    [None, "Subtotal Bonos"] + [None] * 12,
    ["Tipo de Activo: Acciones"] + [None] * 13,
    ["Ticker", "Nombre", "Cantidad", "Garantía", "Disponibles", "Moneda",
     "Precio actual", "Monto $", "Equivalente U$S", "Costo (PPC)",
     "Monto invertido", "Resultado", "Var %", "MTM Acumulado"],
    ["GGAL", "Grupo Financiero Galicia", None, 0, 54, "ARS",
     8145, None, None, 3885.840569, None, None, 109.6, None],
    [None, "Subtotal Acciones"] + [None] * 12,
    ["Tipo de Activo: Cedear"] + [None] * 13,
    ["Ticker", "Nombre", "Cantidad", "Garantía", "Disponibles", "Moneda",
     "Precio actual", "Monto $", "Equivalente U$S", "Costo (PPC)",
     "Monto invertido", "Resultado", "Var %", "MTM Acumulado"],
    ["NVDA", "NVIDIA Corp", None, 0, 175, "ARS",
     13920, None, None, 5334.86032, None, None, 160.9, None],
    [None, "Subtotal Cedears"] + [None] * 12,
    [None, "Total"] + [None] * 12,
]


class InviuTenenciaTest(unittest.TestCase):
    def setUp(self):
        self.snap = parse_inviu_tenencia(TEN_ROWS)

    def test_looks_like(self):
        self.assertTrue(looks_like_inviu_tenencia(TEN_ROWS))

    def test_no_colisiona_con_ppi(self):
        # La foto de inviu NO debe matchear el detector de PPI (y viceversa el
        # classify prueba PPI primero) — si esto falla, classify-tenencia la
        # rutearía al parser equivocado.
        self.assertFalse(looks_like_ppi_tenencia(TEN_ROWS))

    def test_meta(self):
        self.assertEqual(self.snap.date, "2026-07-23")
        self.assertAlmostEqual(self.snap.fx_mep, 1510.881, places=3)

    def test_cash(self):
        self.assertAlmostEqual(self.snap.cash_ars, 1302.92, places=2)
        self.assertAlmostEqual(self.snap.cash_usd, 127.49, places=2)

    def test_holdings_tipos_y_cantidades(self):
        by = {h.ticker: h for h in self.snap.holdings}
        self.assertEqual(set(by), {"RUCDO", "GGAL", "NVDA"})   # cash NO es holding
        self.assertEqual(by["RUCDO"].asset_type, "BOND")
        self.assertEqual(by["GGAL"].asset_type, "STOCK")
        self.assertEqual(by["NVDA"].asset_type, "CEDEAR")
        self.assertEqual(by["RUCDO"].quantity, 1813)           # qty desde Disponibles
        self.assertEqual(by["NVDA"].quantity, 175)

    def test_costo_ppc_sembrado(self):
        by = {h.ticker: h for h in self.snap.holdings}
        self.assertAlmostEqual(by["NVDA"].price_per1, 5334.86032, places=4)  # PPC, no mercado
        self.assertAlmostEqual(by["NVDA"].value, 175 * 13920, places=2)      # value = mercado

    def test_moneda_ars_y_sin_warnings(self):
        self.assertTrue(all(h.currency == "ARS" for h in self.snap.holdings))
        self.assertEqual(self.snap.warnings, [])

    def test_seccion_desconocida_avisa(self):
        rows = TEN_ROWS[:13] + [["Tipo de Activo: Opciones"] + [None] * 13] + TEN_ROWS[13:]
        snap = parse_inviu_tenencia(rows)
        self.assertTrue(any("no reconocemos" in w for w in snap.warnings))


class InviuConsolidadaTest(unittest.TestCase):
    """Export "Cuenta Corriente Consolidada": trae la sección "Disponible -
    Instrumentos" (movimientos de títulos por especie, nominales sin cash) que es
    redundante — el parseo CORTA ahí. Sin el corte, cada boleto se contaba dos
    veces y la segunda con montos peso/nominal etiquetados USD (cartera ×miles)."""

    SAMPLE = (
        "Fecha de Concertación,Fecha de Liquidación,Descripción,Tipo de Operación,"
        "Ticker,Cantidad VN,Precio,Import Bruto,Importe Neto,Saldo,_hoja\n"
        "PESOS - $,,,,,,,,,,\n"
        "13/3/2024,13/3/2024,Recibo de Cobro / 1,Recibo de Cobro,-,-,0,300000,300000,300000,\n"
        "13/3/2024,15/3/2024,Boleto / 1 / CPRA / 2 / NVDA / $,CPRA,NVDA,4,39316.5,-157266,-159321.15,140678.85,\n"
        "Dólar Cable - U$C,,,,,,,,,,\n"
        "16/2/2024,16/2/2024,Recibo de Cobro / 2,Recibo de Cobro,-,-,0,378.10,378.10,378.10,\n"
        "Dólar MEP - U$S,,,,,,,,,,\n"
        "16/2/2024,16/2/2024,Recibo de Cobro / 3,Recibo de Cobro,-,-,0,127.49,127.49,127.49,\n"
        "Disponible - Instrumentos,,,,,,,,,,\n"
        "CEDEAR NVIDIA CORPORATION - NVDA /8469,,,,,,,,,,\n"
        "13/3/2024,15/3/2024,Boleto / 1 / CPRA / 2 / NVDA / $,CPRA,NVDA,4,39316.5,-157266,4,4,\n"
        "1/6/2026,2/6/2026,Boleto / 9 / CPRA / 1 / YPFD / $,CPRA,YPFD,2,83000,-166000,2,6,\n"
    )

    def setUp(self):
        self.res = InviuParser().parse(self.SAMPLE)
        self.rows = self.res.raw_rows

    def test_corta_en_instrumentos(self):
        # Solo UNA compra (la de la sección monetaria) — las filas de Instrumentos
        # (NVDA repetido + YPFD en nominales) NO se importan.
        compras = _by_tipo(self.rows, "COMPRA")
        self.assertEqual(len(compras), 1)
        self.assertEqual(compras[0].data["activo"], "NVDA")
        self.assertNotIn("YPFD", [r.data.get("activo") for r in self.rows])

    def test_dolar_cable_es_usd(self):
        deps = _by_tipo(self.rows, "DEPOSITO")
        usd = [r for r in deps if r.data["moneda"] == "USD"]
        self.assertEqual(len(usd), 2)   # cable 378.10 + MEP 127.49
        self.assertAlmostEqual(sum(float(r.data["monto"]) for r in usd), 505.59, places=2)

    def test_cash_reconcilia_consolidada(self):
        cash = {}
        for r in self.rows:
            d = r.data
            m = float(d.get("monto") or 0); c = float(d.get("comisiones") or 0)
            tp = d["tipo"]
            eff = (m - c) if tp == "VENTA" else -(m + c) if tp == "COMPRA" else m * {"DEPOSITO": 1, "DIVIDENDO": 1, "INTERES": 1, "RETIRO": -1, "FEE": -1, "IMPUESTO": -1}.get(tp, 0)
            cash[d["moneda"]] = cash.get(d["moneda"], 0.0) + eff
        self.assertAlmostEqual(cash["ARS"], 140678.85, places=2)
        self.assertAlmostEqual(cash["USD"], 505.59, places=2)


class InviuTenenciaCableTest(unittest.TestCase):
    def test_cash_usd_suma_mep_y_cable(self):
        rows = [r[:] for r in TEN_ROWS]
        # insertar fila USD.C (Dólar Cable) en la sección Moneda, después de USD
        idx = next(i for i, r in enumerate(rows) if r[0] == "USD")
        rows.insert(idx + 1, ["USD.C", "Dólar Cable", None, 0, 378.10, "ARS", 1564.84, None, None, 0, None, None, 0, None])
        snap = parse_inviu_tenencia(rows)
        self.assertAlmostEqual(snap.cash_usd, 127.49 + 378.10, places=2)


if __name__ == "__main__":
    unittest.main()
