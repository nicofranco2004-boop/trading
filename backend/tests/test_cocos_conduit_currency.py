"""Regresión: conductos dólar-MEP con bono — la pata de COMPRA en ARS NO debe forzarse a USD.

Causa raíz del capital negativo de miles de millones (78 cuentas): Cocos exporta la
conversión ARS→USD como un par de filas del MISMO bono — "Compra bono Operatoria dolar
MEP ARS" (pagás pesos) + "Venta … dolar MEP USD" (cobrás dólares). El parser FORZABA
moneda=USD a TODO lo que dijera "dolar mep" (cocos.py), así que los pesos de la compra
(ej -946.628) se contaban como dólares (×~tc_blue) → el FIFO calculaba
pnl = proceeds_USD − costo_PESOS = P&L peso-escala.

El fix: la columna `moneda` es autoritativa cuando es explícita (ARS/USD). Acá fijamos:
la pata ARS queda ARS, la pata USD queda USD, y la tenencia del bono netea a 0.

Corre con: cd backend && python3 -m pytest tests/test_cocos_conduit_currency.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.parsers.cocos import CocosParser

HEADER = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
          "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")

_INSTR = "ON CREDICUOTAS CONSUMO 9 V27/09/25 $ CG (DHS9O)"


def _csv(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def _rows_for(result, ticker):
    """[(tipo, moneda, monto)] de las filas del ticker dado."""
    out = []
    for r in result.raw_rows:
        d = r.data
        if d.get("activo") == ticker:
            out.append((d.get("tipo"), d.get("moneda"), d.get("monto")))
    return out


class TestConduitCurrency(unittest.TestCase):
    def test_compra_dolar_mep_ars_queda_ars(self):
        # La pata ARS de un conducto dólar-MEP NO debe forzarse a USD.
        res = CocosParser().parse(_csv(
            f"1;1;09-09-2025;09-09-2025;Compra bono Operatoria dolar MEP ARS;{_INSTR};ARS;BYMA;874080;108,3;-946628,64;0;0;0;0;-946628,64",
            f"2;2;09-09-2025;09-09-2025;Venta bono Operatoria dolar MEP USD;{_INSTR};USD;BYMA;-874080;0,075;655,56;0;0;0;0;655,56",
        ))
        rows = _rows_for(res, "DHS9O")
        monedas = {tipo: mon for (tipo, mon, _) in rows}
        self.assertEqual(monedas.get("COMPRA"), "ARS",
                         "la pata de COMPRA del conducto debe quedar en ARS (no forzada a USD)")
        self.assertEqual(monedas.get("VENTA"), "USD",
                         "la pata de VENTA del conducto queda en USD (de la columna)")

    def test_columna_moneda_es_autoritativa(self):
        # Aunque el tipo diga "dolar mep", si la columna dice ARS → ARS.
        res = CocosParser().parse(_csv(
            f"1;1;09-09-2025;09-09-2025;Compra Dolar Mep;{_INSTR};ARS;BYMA;1000;1,0;-1000;0;0;0;0;-1000",
        ))
        rows = _rows_for(res, "DHS9O")
        self.assertTrue(rows, "la fila debe parsearse")
        self.assertEqual(rows[0][1], "ARS",
                         "la columna moneda explícita (ARS) manda sobre el force-USD de 'dolar mep'")


if __name__ == "__main__":
    unittest.main()


class BondHintCedearFalsePositive(unittest.TestCase):
    """Un CEDEAR no es un bono, aunque su nombre contenga "on ".

    El detector de conductos dólar-MEP sólo mira BONOS: cuando aparea una compra
    en ARS con una venta MEP en USD del mismo papel, BORRA las dos operaciones y
    las reemplaza por un retiro + un depósito. Eso es correcto para un bono usado
    de puente; para un CEDEAR que el usuario tradeó de verdad le hace desaparecer
    la compra, la venta y el P&L.

    Las pistas de bono se buscaban por subcadena, y el formato real de Cocos es
    "CEDEAR NVIDIA CORPORATION (NVDA)": el "on " de "corporati|on |(" las
    disparaba. 6 de cada 12 CEDEARs con nombre real entraban como bono.
    """

    def test_los_cedears_reales_no_son_bonos(self):
        from importing.parsers.cocos import _is_bond_instrument
        for nombre in ("CEDEAR NVIDIA CORPORATION (NVDA)",
                       "CEDEAR MICROSOFT CORPORATION (MSFT)",
                       "CEDEAR INTEL CORPORATION (INTC)",
                       "CEDEAR EXXON MOBIL CORP (XOM)",
                       "CEDEAR ORACLE CORPORATION (ORCL)",
                       "CEDEAR VERIZON COMM (VZ)",
                       "CEDEAR APPLE INC. (AAPL)",
                       "CEDEAR TESLA, INC. (TSLA)"):
            self.assertFalse(_is_bond_instrument(nombre),
                             f"{nombre} es un CEDEAR, no un bono")

    def test_los_bonos_de_verdad_siguen_siendo_bonos(self):
        """El espejo: si el fix se pasa de estricto, un conducto MEP real deja de
        detectarse y el usuario termina con un bono fantasma en la cartera."""
        from importing.parsers.cocos import _is_bond_instrument
        for nombre in ("BONO AL30", "ON YPF 2029", "ON PAMPA",
                       "Obligaciones Negociables YPF", "LETRA X16E4",
                       "LECAP S31M4", "BONCER TX26", "BONAR AL35",
                       "BOPREAL BPY26", "TITULO PUBLICO", "LT X18J5", "CER TX28"):
            self.assertTrue(_is_bond_instrument(nombre),
                            f"{nombre} SÍ es un bono y dejó de detectarse")
