"""Regresión de los tipos de operación de Cocos que antes se dropeaban/skipeaban.

Un usuario de bonos/LECAPs/FCI importó 3 años de movimientos y la cartera salía
mal: el parser dropeaba "Renta Y Amortizacion" (cupón/amortización de bonos),
nucleaba TODO "Dividendos En Especie" (incluida una maduración de 16M de pesos),
y dropeaba notas de crédito/débito, cauciones, etc. → ~39M ARS de flujos de caja
perdidos. Estos tests fijan el mapeo correcto.

Corre con: cd backend && python3 -m pytest tests/test_cocos_optypes.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.parsers.cocos import CocosParser
from importing.normalizer import normalize_rows

HEADER = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
          "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")


def _csv(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def _parse(*rows):
    return CocosParser().parse(_csv(*rows))


def _by_tipo(result):
    return [r.data["tipo"] for r in result.raw_rows]


class TestRentaAmortizacion(unittest.TestCase):
    def test_renta_y_amortizacion_es_ingreso(self):
        # Antes: UNKNOWN (dropeada) → se perdían millones de pesos de bonos.
        r = _parse("1;;12-12-2024;12-12-2024;Renta Y Amortizacion;"
                   "LT REP ARGENTINA CAP V13/12/24 $ CG;ARS;;;;;0;0;0;0;225.677,25")
        self.assertEqual(_by_tipo(r), ["DIVIDENDO"])
        norm, errs = normalize_rows(r.raw_rows)
        self.assertEqual(len(errs), 0)
        self.assertAlmostEqual(norm[0].gross_amount, 225677.25, places=2)

    def test_renta_amortizacion_en_especie_pesos_es_ingreso(self):
        # "RENTA Y AMORTIZACION EN ESPECIE" en pesos = cash real (maduración).
        r = _parse("1;;17-10-2025;17-10-2025;RENTA Y AMORTIZACION EN ESPECIE;"
                   "Peso argentino;ARS;;;;;0;0;0;0;6.908.957,22")
        self.assertEqual(_by_tipo(r), ["DIVIDENDO"])
        norm, _ = normalize_rows(r.raw_rows)
        self.assertAlmostEqual(norm[0].gross_amount, 6908957.22, places=2)


class TestEnEspecie(unittest.TestCase):
    def test_dividendos_en_especie_pesos_se_toma(self):
        # Crédito real en pesos (16M) — NO se debe skipear.
        r = _parse("1;;31-10-2025;31-10-2025;DIVIDENDOS EN ESPECIE;"
                   "Peso argentino;ARS;;;;;0;0;0;0;16.135.014,05")
        self.assertEqual(_by_tipo(r), ["DIVIDENDO"])
        norm, _ = normalize_rows(r.raw_rows)
        self.assertAlmostEqual(norm[0].gross_amount, 16135014.05, places=2)

    def test_dividendos_en_especie_usd_se_skipea(self):
        # Retención de dividendo USD pagado en especie (el cash real entra como
        # Nota De Credito Conversion) → skip silencioso, sin error.
        r = _parse("1;;04-02-2025;04-02-2025;DIVIDENDOS EN ESPECIE;"
                   "Dólar estadounidense;ARS;;0,59;0;0;0;-2,2183;-0,4658;0;-2,68")
        self.assertEqual(len(r.raw_rows), 0)
        self.assertEqual(len(r.parse_errors), 0)

    def test_dividendos_en_especie_acciones_se_skipea(self):
        # Dividendo en ACCIONES (instrumento = ticker): no auto-agregamos especie.
        r = _parse("1;;08-09-2025;08-09-2025;DIVIDENDOS EN ESPECIE;"
                   "MORIXE HNOS. S.A.  ORD. 1 VOTO (MORI);ARS;;1.273;0;0;0;-1,273;-0,2673;0;-1,54")
        self.assertEqual(len(r.raw_rows), 0)
        self.assertEqual(len(r.parse_errors), 0)


class TestNotasYCauciones(unittest.TestCase):
    def test_nota_de_credito_es_deposito(self):
        r = _parse("1;;11-11-2024;11-11-2024;Nota De Credito;;ARS;;;;;0;0;0;0;617.549,16")
        self.assertEqual(_by_tipo(r), ["DEPOSITO"])

    def test_nota_credito_dividendos_es_dividendo(self):
        # "Nota Credito Dividendos ARS" debe caer como dividendo, no como depósito.
        r = _parse("1;;14-02-2025;14-02-2025;Nota Credito Dividendos ARS;;ARS;;;;;0;0;0;0;177.604,57")
        self.assertEqual(_by_tipo(r), ["DIVIDENDO"])

    def test_nota_debito_es_fee(self):
        r = _parse("1;;30-04-2025;30-04-2025;Nota Debito Bp Gcias;;ARS;;;;;0;0;0;0;-2.905,56")
        self.assertEqual(_by_tipo(r), ["FEE"])
        norm, _ = normalize_rows(r.raw_rows)
        self.assertEqual(norm[0].operation_type, "FEE")

    def test_cauciones_contado_y_termino(self):
        r = _parse(
            "1;;29-08-2025;29-08-2025;Colocador Caucion Contado;;ARS;BYMA;;;-278.000;0;0;0;0;-278.000",
            "2;;05-09-2025;05-09-2025;Colocador Caucion Termino;;ARS;BYMA;;;280.585,78;-272,79;-9,82;-59,35;0;280.243,82",
        )
        self.assertEqual(_by_tipo(r), ["RETIRO", "DEPOSITO"])


class TestSkipsSinError(unittest.TestCase):
    def test_canje_skip_silencioso(self):
        r = _parse("1;;26-01-2024;26-01-2024;Canje;CEDEAR APPLE INC. (AAPL);ARS;;;;0;0;0;0;0;0")
        self.assertEqual(len(r.raw_rows), 0)
        self.assertEqual(len(r.parse_errors), 0)

    def test_moneda_ext_skip_silencioso(self):
        # EXT (cable/exterior, migración): moneda no soportada, montos marginales.
        r = _parse(
            "1;;01-10-2024;01-10-2024;Concepto EXT migracion;;EXT;;;;;0;0;0;0;0,3",
            "2;;15-01-2025;15-01-2025;Nota De Credito Conversion Cable;;EXT;;;;;0;0;0;0;0,26",
        )
        self.assertEqual(len(r.raw_rows), 0)
        self.assertEqual(len(r.parse_errors), 0)


class TestTickerWithSpace(unittest.TestCase):
    def test_fci_ticker_con_espacio(self):
        from importing.parsers.cocos import _extract_ticker
        # 'SBSACAR AR' tiene espacio → antes quedaba sin activo y se dropeaba.
        self.assertEqual(_extract_ticker("SBS ACCIONES ARGENTINA CL.A $ FCI (SBSACAR AR)"), "SBSACAR")
        # los tickers normales siguen funcionando.
        self.assertEqual(_extract_ticker("CEDEAR APPLE INC. (AAPL)"), "AAPL")

    def test_fci_se_clasifica_fund(self):
        r = _parse("1;;30-01-2025;30-01-2025;Liquidacion Suscripcion Fci;"
                   "FCI COCOS RENDIMIENTO CL. A $ ESC (COCORMA);ARS;;16215,39;7380,20;-119673;0;0;0;0;-119673")
        self.assertEqual(r.raw_rows[0].data["activo"], "COCORMA")
        self.assertEqual(r.raw_rows[0].data["asset_type"], "FUND")


class TestDividendoSigno(unittest.TestCase):
    def test_dividendo_negativo_es_fee(self):
        # Retención de impuesto sobre dividendo CEDEAR (total negativo) → FEE.
        r = _parse("1;;01-02-2024;01-02-2024;Dividendos;CEDEAR SPDR S&P 500 (SPY);ARS;;;;;-0,7;0;0;0;-0,7")
        self.assertEqual(_by_tipo(r), ["FEE"])

    def test_dividendo_positivo_sigue_dividendo(self):
        r = _parse("1;;23-05-2024;23-05-2024;Dividendos;GRUPO FINANCIERO GALICIA (GGAL);ARS;;;;;18013,72;0;0;0;18013,72")
        self.assertEqual(_by_tipo(r), ["DIVIDENDO"])

    def test_nota_debito_dividendos_es_fee(self):
        # "Nota Debito Dividendos ARS" contiene "dividendo" pero es un cargo → FEE.
        r = _parse("1;;30-10-2025;30-10-2025;Nota Debito Dividendos ARS;;ARS;;;;;0;0;0;0;-30,71")
        self.assertEqual(_by_tipo(r), ["FEE"])

    def test_nota_credito_dividendos_sigue_dividendo(self):
        r = _parse("1;;14-02-2025;14-02-2025;Nota Credito Dividendos ARS;;ARS;;;;;0;0;0;0;177604,57")
        self.assertEqual(_by_tipo(r), ["DIVIDENDO"])


class TestMepConduits(unittest.TestCase):
    def test_compra_venta_dolar_mep_mismo_bono_es_conversion(self):
        # RCCPO: Compra ARS + Venta Dolar Mep USD del mismo bono, misma cantidad →
        # conversión de moneda (RETIRO/DEPOSITO), NO tenencia → sin posición fantasma.
        r = _parse(
            "1;;06-05-2025;06-05-2025;Compra;ON ARCOR CL.24 V07/10/25 $ CG (RCCPO);ARS;BYMA;128103;103,8;-132.970,91;0;-13,30;0;0;-132.984,21",
            "2;;06-05-2025;06-05-2025;Venta Dolar Mep;ON ARCOR CL.24 V07/10/25 $ CG (RCCPO);USD;BYMA;-128103;0,087;111,45;0;-0,01;0;0;111,44",
        )
        self.assertEqual(_by_tipo(r), ["RETIRO", "DEPOSITO"])
        self.assertTrue(all(not row.data["activo"] for row in r.raw_rows))

    def test_esp_app_es_conversion(self):
        # 'Compra Esp App Pesos' + 'Venta Esp App Dolares' (AL30) → RETIRO/DEPOSITO.
        r = _parse(
            "1;;03-01-2024;03-01-2024;Compra Esp App Pesos;BONO REP. ARGENTINA (AL30);ARS;BYMA;167;38408;-64142,2;0;-6,41;0;0;-64790,03",
            "2;;04-01-2024;04-01-2024;Venta Esp App Dolares;BONO REP. ARGENTINA (AL30);USD;BYMA;-167;0;62,59;0;-0,01;0;0;62,42",
        )
        self.assertEqual(_by_tipo(r), ["RETIRO", "DEPOSITO"])

    def test_compra_dolar_mep_accion_sigue_siendo_compra(self):
        # Compra Dolar Mep de un CEDEAR (sin par ARS) = compra real en USD, NO conduit.
        r = _parse("1;;17-09-2024;17-09-2024;Compra Dolar Mep;CEDEAR MERCADOLIBRE INC. (MELI);USD;BYMA;32;18,05;-577,6;-1,44;-0,46;-0,4;0;-579,9")
        self.assertEqual(_by_tipo(r), ["COMPRA"])
        self.assertEqual(r.raw_rows[0].data["activo"], "MELI")


class TestNoUnknownErrors(unittest.TestCase):
    def test_mix_no_deja_ops_desconocidas(self):
        # Un mix representativo no debe dejar NINGÚN COCOS_OP_UNKNOWN.
        r = _parse(
            "1;;02-01-2024;02-01-2024;Recibo De Cobro;;ARS;;;;70.000;0;0;0;0;70.000",
            "2;;12-12-2024;12-12-2024;Renta Y Amortizacion;Peso argentino;ARS;;;;;0;0;0;0;225.677",
            "3;;11-11-2024;11-11-2024;Nota De Credito;;ARS;;;;;0;0;0;0;617.549",
            "4;;30-04-2025;30-04-2025;Nota Debito Bp Gcias;;ARS;;;;;0;0;0;0;-2.905",
            "5;;29-08-2025;29-08-2025;Colocador Caucion Contado;;ARS;BYMA;;;-278.000;0;0;0;0;-278.000",
            "6;;26-01-2024;26-01-2024;Canje;CEDEAR APPLE INC. (AAPL);ARS;;;;0;0;0;0;0;0",
        )
        unknown = [e for e in r.parse_errors if e.code == "COCOS_OP_UNKNOWN"]
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
