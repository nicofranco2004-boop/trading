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


if __name__ == "__main__":
    unittest.main()
