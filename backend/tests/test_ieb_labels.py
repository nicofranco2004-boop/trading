"""Tests del parser de IEB contra el export REAL de la web (etiquetas largas).

El export que baja el usuario no trae los códigos cortos (CPRA/VTAS/DETR…) sino
la descripción completa de la operación ("COMPRA NORMAL", "DEPOSITO TITULOS
TRANSF.", "R.COBRO"). El parser se había escrito contra un demo con códigos, así
que sobre el archivo real rechazaba las 305 filas.

Las filas de acá son las 19 variantes de `Operación` que trae un export real
(cuenta de un usuario, montos redondeados), incluidas las erratas del propio
broker: doble espacio en 'VENTA  PARIDAD' y 'TRAIDING'/'TRAINDIG' en la misma
planilla.

Corre con: cd backend && python3 -m pytest tests/test_ieb_labels.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.parsers.ieb import IebParser, _label_to_code

_HEAD = ("Referencia,Operación,Fecha emisión,Fecha liquidación,Nro. de operación,"
         "Cantidad,Precio,Importe ARS,Importe divisas,Divisa\n")

_ROWS = (
    # Trades en pesos y en dólares ("PARIDAD" = la pata en dólares).
    "STNE,COMPRA NORMAL,2025-12-01 03:00:00,2025-12-01 03:00:00,1001,23,8660,-199300.5,-,ARS\n"
    "META,COMPRA PARIDAD,2025-12-02 03:00:00,2025-12-02 03:00:00,1002,11,25.6054545,-,-281.66,USD\n"
    "SUPV,COMPRA TRAIDING PARIDAD,2025-12-03 03:00:00,2025-12-03 03:00:00,1003,1,2.36,-,-2.36,USD\n"
    "SMH,VENTA,2025-12-04 03:00:00,2025-12-04 03:00:00,1004,-24,12020,288305.47,-,ARS\n"
    "BBAR,VENTA  PARIDAD,2025-12-05 03:00:00,2025-12-05 03:00:00,1005,-19,5.2768421,-,100.26,USD\n"
    "SUPV,VENTA  TRAINDIG PARIDAD,2025-12-06 03:00:00,2025-12-06 03:00:00,1006,-1,2.37,-,2.37,USD\n"
    # Renta y su retención (la retención NO puede quedar como ingreso).
    "GGAL,DIVIDENDOS,2025-12-07 03:00:00,2025-12-07 03:00:00,1007,-,-,659.79,-,ARS\n"
    "STNE,DEBITO RET DIVIDENDOS,2025-12-08 03:00:00,2025-12-08 03:00:00,1008,-,-,-46.24,-,ARS\n"
    # Cargos.
    "META,GASTOS CV C/IVA,2025-12-09 03:00:00,2025-12-09 03:00:00,1009,-,-,-763.62,-,ARS\n"
    "BBAR,NOTA DE DEBITO MEMBRESIA PESOS,2025-12-10 03:00:00,2025-12-10 03:00:00,1010,-,-,-6050,-,ARS\n"
    "MSFT,NOTA DE CRED. MEMBRESIA PESOS,2025-12-11 03:00:00,2025-12-11 03:00:00,1011,-,-,6050,-,ARS\n"
    # Caja en pesos y en dólares.
    "BBAR,R.COBRO,2025-12-12 03:00:00,2025-12-12 03:00:00,1012,-,-,110000,-,ARS\n"
    "-,RECIBO DE COBRO,2025-12-13 03:00:00,2025-12-13 03:00:00,1013,-,-,8000,-,ARS\n"
    "-,RECIBO DE COBRO WEB,2025-12-14 03:00:00,2025-12-14 03:00:00,1014,-,-,200000,-,ARS\n"
    "DOLAR,RECIBO DE COBRO USD WEB,2025-12-15 03:00:00,2025-12-15 03:00:00,1015,-,-,-,2500,USD\n"
    "MELI,O.PAGO,2025-12-16 03:00:00,2025-12-16 03:00:00,1016,-,-,-220000,-,ARS\n"
    "PVR1Q,ORDEN  DE PAGO WEB,2025-12-17 03:00:00,2025-12-17 03:00:00,1017,-,-,-4277160,-,ARS\n"
    "DOLAR,ORDEN DE PAGO USD WEB,2025-12-18 03:00:00,2025-12-18 03:00:00,1018,-,-,-,-2218.34,USD\n"
    # El movimiento que reportó el usuario.
    "SPY,DEPOSITO TITULOS TRANSF.,2025-11-07 03:00:00,2025-11-07 03:00:00,1019,106,49340,5230040,-,ARS\n"
)


def _parse(csv_text):
    return IebParser().parse(csv_text, "IEB.xlsx")


class TestIebEtiquetasReales(unittest.TestCase):

    def setUp(self):
        self.res = _parse(_HEAD + _ROWS)
        self.by_nro = {}
        for r in self.res.raw_rows:
            self.by_nro.setdefault(r.data["notas"].split(" · ")[0], []).append(r.data)

    def test_ninguna_fila_del_export_real_se_rechaza(self):
        """La regresión que reportó el usuario: 305/305 filas caían en
        IEB_OP_UNKNOWN porque el parser esperaba códigos cortos."""
        self.assertEqual(self.res.parse_errors, [], "el export real no debe tirar errores")
        self.assertTrue(self.res.raw_rows)

    def test_compras_y_ventas_con_su_moneda(self):
        # La moneda sale de QUÉ columna de importe viene llena, no del texto:
        # "PARIDAD" es la pata en dólares de la misma especie.
        self.assertEqual(self.by_nro["Op. 1001"][0]["tipo"], "COMPRA")
        self.assertEqual(self.by_nro["Op. 1001"][0]["moneda"], "ARS")
        self.assertEqual(self.by_nro["Op. 1002"][0]["tipo"], "COMPRA")
        self.assertEqual(self.by_nro["Op. 1002"][0]["moneda"], "USD")
        self.assertEqual(self.by_nro["Op. 1004"][0]["tipo"], "VENTA")
        self.assertEqual(self.by_nro["Op. 1005"][0]["tipo"], "VENTA")
        self.assertEqual(self.by_nro["Op. 1005"][0]["moneda"], "USD")

    def test_erratas_del_broker_no_cambian_el_mapeo(self):
        """'TRAIDING' y 'TRAINDIG' conviven en la MISMA planilla, y 'VENTA
        PARIDAD' viene con doble espacio."""
        self.assertEqual(self.by_nro["Op. 1003"][0]["tipo"], "COMPRA")
        self.assertEqual(self.by_nro["Op. 1006"][0]["tipo"], "VENTA")

    def test_la_retencion_de_dividendos_es_cargo_no_ingreso(self):
        """'DEBITO RET DIVIDENDOS' contiene 'DIVIDENDO': si el patrón de renta se
        evalúa primero, una retención se cuenta como ingreso."""
        self.assertEqual(self.by_nro["Op. 1007"][0]["tipo"], "DIVIDENDO")
        self.assertEqual(self.by_nro["Op. 1008"][0]["tipo"], "FEE")

    def test_cargos_y_devolucion(self):
        self.assertEqual(self.by_nro["Op. 1009"][0]["tipo"], "FEE")   # comisión c/IVA
        self.assertEqual(self.by_nro["Op. 1010"][0]["tipo"], "FEE")   # membresía
        self.assertEqual(self.by_nro["Op. 1011"][0]["tipo"], "DEPOSITO")  # devolución

    def test_caja_entra_y_sale(self):
        for nro in ("Op. 1012", "Op. 1013", "Op. 1014", "Op. 1015"):
            self.assertEqual(self.by_nro[nro][0]["tipo"], "DEPOSITO", nro)
        for nro in ("Op. 1016", "Op. 1017", "Op. 1018"):
            self.assertEqual(self.by_nro[nro][0]["tipo"], "RETIRO", nro)
        self.assertEqual(self.by_nro["Op. 1015"][0]["moneda"], "USD")
        self.assertEqual(self.by_nro["Op. 1018"][0]["moneda"], "USD")

    def test_transferencia_de_titulos_entrante(self):
        """Lo que reportó el usuario. Crea la posición con su costo + un depósito
        compensatorio: la tenencia queda y el cash netea a 0 (la plata nunca
        salió de la cuenta)."""
        filas = self.by_nro["Op. 1019"]
        self.assertEqual(len(filas), 2)
        compra, dep = filas[0], filas[1]
        self.assertEqual(compra["tipo"], "COMPRA")
        self.assertEqual(compra["activo"], "SPY")
        self.assertEqual(float(compra["cantidad"]), 106)
        self.assertEqual(float(compra["monto"]), 5230040)
        self.assertEqual(dep["tipo"], "DEPOSITO")
        self.assertEqual(dep["activo"], "")
        self.assertEqual(float(dep["monto"]), 5230040)

    def test_transferencia_saliente_cierra_a_costo(self):
        """El título SALE de la cuenta: no es una venta (no entró plata) →
        `_transfer_out` cierra el lote a costo con P&L 0."""
        res = _parse(_HEAD +
                     "SPY,RETIRO TITULOS TRANSF.,2026-01-05 03:00:00,"
                     "2026-01-05 03:00:00,2001,-40,49340,-1973600,-,ARS\n")
        self.assertEqual(res.parse_errors, [])
        self.assertEqual(len(res.raw_rows), 1)
        d = res.raw_rows[0].data
        self.assertEqual(d["tipo"], "VENTA")
        self.assertEqual(d["activo"], "SPY")
        self.assertEqual(float(d["cantidad"]), 40)
        self.assertEqual(d["_transfer_out"], "1")
        self.assertEqual(float(d["monto"]), 0)

    def test_el_wash_pago_cobro_sigue_funcionando_con_etiquetas(self):
        """O.PAGO + RECIBO DE COBRO del mismo día/ticker/monto son un movimiento
        interno: netean a 0. En el export real hay un par así (STNE, 500.000)."""
        res = _parse(_HEAD +
                     "STNE,O.PAGO,2025-11-12 03:00:00,2025-11-12 03:00:00,3001,-,-,-500000,-,ARS\n"
                     "STNE,RECIBO DE COBRO WEB,2025-11-12 03:00:00,2025-11-12 03:00:00,3002,-,-,500000,-,ARS\n")
        self.assertEqual(res.parse_errors, [])
        self.assertEqual(res.raw_rows, [], "el par pago↔cobro tiene que netear")

    def test_los_codigos_cortos_del_demo_siguen_andando(self):
        """La normalización no debe romper los exports con códigos."""
        for code, esperado in (("CPRA", "CPRA"), ("VTAS", "VTAS"), ("CPU$", "CPU$"),
                               ("VTU$", "VTU$"), ("DETR", "DETR"), ("NDMP", "NDMP"),
                               ("COBW", "COBW"), ("PAGW", "PAGW"), ("CU$V", "CU$V"),
                               ("DIV", "DIV"), ("CCCD", "CCCD"), ("CCTE", "CCTE")):
            self.assertEqual(_label_to_code(code), esperado, code)

    def test_una_etiqueta_desconocida_se_reporta_no_se_traga(self):
        """Preferimos un error visible en el wizard antes que una fila que
        desaparece sin dejar rastro."""
        res = _parse(_HEAD +
                     "XX,OPERACION NUEVA DE IEB,2026-01-01 03:00:00,"
                     "2026-01-01 03:00:00,4001,-,-,100,-,ARS\n")
        self.assertEqual(len(res.raw_rows), 0)
        self.assertEqual(len(res.parse_errors), 1)
        self.assertEqual(res.parse_errors[0].code, "IEB_OP_UNKNOWN")
        # El mensaje lleva el texto ORIGINAL, que es lo que se le pide al usuario.
        self.assertIn("OPERACION NUEVA DE IEB", res.parse_errors[0].message)


class TestIebReconciliacion(unittest.TestCase):
    """La prueba de que el mapeo es correcto no es que no tire errores, es que la
    caja cierre: un tipo mal mapeado (un cargo tomado como ingreso, un retiro
    como depósito) no rompe ningún test de tipos pero mueve el saldo.

    Sobre el export real completo del usuario que lo reportó, el mismo cálculo da
    **US$ 90,95 = exactamente el saldo de la hoja `Saldos` de su Portafolio**, y
    en pesos 34 millones de flujo bruto netean a 26,93. Acá se verifica el mismo
    invariante sobre el subconjunto del fixture, con la suma a mano.
    """

    def test_el_cash_cierra(self):
        res = _parse(_HEAD + _ROWS)
        signo = {"COMPRA": -1, "VENTA": +1, "DEPOSITO": +1,
                 "RETIRO": -1, "DIVIDENDO": +1, "FEE": -1}
        caja = {"ARS": 0.0, "USD": 0.0}
        for r in res.raw_rows:
            if r.data["monto"]:
                caja[r.data["moneda"]] += signo[r.data["tipo"]] * float(r.data["monto"])
        # ARS: −199.300,50 +288.305,47 +659,79 −46,24 −763,62 −6.050 +6.050
        #      +110.000 +8.000 +200.000 −220.000 −4.277.160
        #      + el par de la transferencia (−5.230.040 compra +5.230.040 depósito = 0)
        self.assertAlmostEqual(caja["ARS"], -4_090_305.10, places=2)
        # USD: −281,66 −2,36 +100,26 +2,37 +2.500 −2.218,34
        self.assertAlmostEqual(caja["USD"], 100.27, places=2)


if __name__ == "__main__":
    unittest.main()
