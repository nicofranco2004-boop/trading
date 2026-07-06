"""BalanzInternacionalParser — export de Movimientos de la cuenta exterior (USD).

Verifica: trades COMPRAEXT/VENTAEXT (por signo) + limpieza del punto del ticker,
FCI Liquidación de Suscripción/Rescate con Precio=-1 (sin VCP), Reverse Split,
Tax Withholding + reversal, US Treasuries (CSBNG/VSBNG), amortización, dividendo,
conversión por Movimiento Manual, y reconciliación de cash.
"""
import unittest

from importing.parsers.balanz_internacional import BalanzInternacionalParser
from importing.parsers.registry import get_parser, autodetect

HDR = "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe"


def _parse(*rows):
    return BalanzInternacionalParser().parse(HDR + "\n" + "\n".join(rows) + "\n")


def _by_ticker(res, ticker):
    return [r.data for r in res.raw_rows if r.data.get("activo") == ticker]


class BalanzInternacionalTest(unittest.TestCase):
    def test_compraext_ventaext_trades(self):
        res = _parse(
            "Boleto / 66388 / COMPRAEXT / 1 / ADBE. / U$S,ADBE.,Acciones,2026-06-30,1,202.79,2026-07-01,US Dollar (Cable),-212.8",
            "Boleto / 57092 / VENTAEXT / 1 / SMR. / U$S,SMR.,Acciones,2026-06-05,-48,10.7301,2026-06-08,US Dollar (Cable),505.04",
        )
        self.assertEqual(len(res.parse_errors), 0)
        adbe = _by_ticker(res, "ADBE")   # punto limpiado
        self.assertEqual(len(adbe), 1)
        self.assertEqual(adbe[0]["tipo"], "COMPRA")       # importe negativo → compra
        self.assertEqual(adbe[0]["asset_type"], "STOCK")
        self.assertEqual(adbe[0]["moneda"], "USD")        # US Dollar (Cable) → USD
        self.assertAlmostEqual(float(adbe[0]["monto"]), 212.8)   # |Importe| (con comisión)
        smr = _by_ticker(res, "SMR")
        self.assertEqual(smr[0]["tipo"], "VENTA")          # importe positivo → venta
        self.assertAlmostEqual(float(smr[0]["cantidad"]), 48)

    def test_fci_liquidacion_sin_precio(self):
        # Precio = -1 (Balanz no manda VCP) → NO debe caer en "no reconocido".
        res = _parse(
            "Liquidación de Suscripción / 4791 / BALANZ GLOBAL EQUITY,BGLOBALE.,Fondos,2026-06-12,1000,-1,2026-06-16,US Dollar (Cable),-1227.14",
            "Liquidación de Rescate / 3980 / BALANZ INCOME,BINCOME.,Fondos,2026-05-21,-2000,-1,2026-05-26,US Dollar (Cable),2182.14",
        )
        self.assertEqual(len(res.parse_errors), 0)
        sus = _by_ticker(res, "BGLOBALE")[0]
        self.assertEqual(sus["tipo"], "COMPRA")            # suscripción = compra
        self.assertEqual(sus["asset_type"], "FUND")
        self.assertAlmostEqual(float(sus["cantidad"]), 1000)
        self.assertAlmostEqual(float(sus["monto"]), 1227.14)
        self.assertNotIn("precio", sus)                    # sin VCP → precio derivado
        res_ = _by_ticker(res, "BINCOME")[0]
        self.assertEqual(res_["tipo"], "VENTA")            # rescate = venta
        self.assertAlmostEqual(float(res_["cantidad"]), 2000)

    def test_reverse_split_dos_patas(self):
        res = _parse(
            "Reverse Split,US92864M4006,Acciones,2025-04-09,-1335,-1,2025-04-09,,0",
            "Reverse Split,ETHU.,Acciones,2025-04-09,67,-1,2025-04-09,,0",
        )
        self.assertEqual(len(res.parse_errors), 0)
        old = _by_ticker(res, "US92864M4006")[0]
        self.assertEqual(old["tipo"], "VENTA")             # sale el viejo
        self.assertEqual(old["precio"], "0")
        self.assertTrue(old.get("_corporate_close"))
        new = _by_ticker(res, "ETHU")[0]
        self.assertEqual(new["tipo"], "COMPRA")            # entra el nuevo
        self.assertEqual(new["precio"], "0")

    def test_tax_withholding_y_reversal(self):
        res = _parse(
            "Tax Withholding DR-US74347W6012,,,2025-04-28,0,-1,2025-04-28,US Dollar (Cable),-389.57",
            "Tax Witholding Reversal,,,2025-05-23,0,-1,2025-05-23,US Dollar (Cable),389.57",
        )
        self.assertEqual(len(res.parse_errors), 0)
        types = [r.data["tipo"] for r in res.raw_rows]
        self.assertIn("IMPUESTO", types)                   # retención (sale)
        self.assertIn("DIVIDENDO", types)                  # reversal (entra, reconcilia)

    def test_us_treasuries_y_bono_csbng(self):
        res = _parse(
            "Boleto / 19667 / CSBNG / 1 / US912797GL51 / U$S,B 0 09/05/24.,US Treasuries,2024-04-11,24400,0.981915,2024-04-12,US Dollar (Cable),-23958.73",
            "Boleto / 52564 / CSBNG / 0 / XS3017143432 / U$S,XS3017143432,Bonos,2025-07-22,5000,0.82,2025-07-22,US Dollar (Cable),-4100",
        )
        self.assertEqual(len(res.parse_errors), 0)
        t = _by_ticker(res, "B 0 09/05/24")[0]
        self.assertEqual(t["tipo"], "COMPRA")
        self.assertEqual(t["asset_type"], "BOND")          # US Treasuries → BOND
        b = _by_ticker(res, "XS3017143432")[0]
        self.assertEqual(b["asset_type"], "BOND")

    def test_amortizacion_cierra_nominal(self):
        # Amortización devuelve capital (qty−, cash in) → VENTA a su valor de rescate.
        res = _parse(
            "Amortización / XS2740843086,XS2740843086,Bonos,2026-04-27,-10000,-1,2026-04-27,US Dollar (Cable),9500",
        )
        self.assertEqual(len(res.parse_errors), 0)
        a = _by_ticker(res, "XS2740843086")[0]
        self.assertEqual(a["tipo"], "VENTA")
        self.assertAlmostEqual(float(a["cantidad"]), 10000)
        self.assertAlmostEqual(float(a["monto"]), 9500)

    def test_dividendo_en_efectivo(self):
        res = _parse(
            "Dividendo en efectivo / MSFT.,MSFT.,Acciones,2026-06-11,0,-1,2026-06-11,US Dollar (Cable),10.19",
        )
        self.assertEqual(len(res.parse_errors), 0)
        d = res.raw_rows[0].data
        self.assertEqual(d["tipo"], "DIVIDENDO")
        self.assertAlmostEqual(float(d["monto"]), 10.19)

    def test_movimiento_manual_conversion_cierra_viejo(self):
        # "Cambio notas estructuradas a fondos" (qty−, sin cash) → cierra el título
        # viejo (VENTA precio 0), no lo deja fantasma.
        res = _parse(
            "Movimiento Manual / Cambio notas estructuradas a fondos,XS2707193509.,Bonos,2024-07-16,-30000,-1,2024-07-16,,0",
        )
        self.assertEqual(len(res.parse_errors), 0)
        m = _by_ticker(res, "XS2707193509")[0]
        self.assertEqual(m["tipo"], "VENTA")
        self.assertEqual(m["precio"], "0")

    def test_cash_reconciliation(self):
        # El neto de cash emitido debe igualar la suma de Importe.
        rows = [
            "Boleto / 1 / COMPRAEXT / 1 / ADBE. / U$S,ADBE.,Acciones,2026-06-30,1,202.79,2026-07-01,US Dollar (Cable),-212.8",
            "Boleto / 2 / VENTAEXT / 1 / SMR. / U$S,SMR.,Acciones,2026-06-05,-48,10.7301,2026-06-08,US Dollar (Cable),505.04",
            "Liquidación de Suscripción / 3 / BALANZ GLOBAL EQUITY,BGLOBALE.,Fondos,2026-06-12,1000,-1,2026-06-16,US Dollar (Cable),-1227.14",
            "Dividendo en efectivo / MSFT.,MSFT.,Acciones,2026-06-11,0,-1,2026-06-11,US Dollar (Cable),10.19",
        ]
        res = _parse(*rows)
        cash_in = {"VENTA", "DEPOSITO", "DIVIDENDO", "INTERES"}
        cash_out = {"COMPRA", "RETIRO", "FEE", "IMPUESTO"}
        emitted = 0.0
        for r in res.raw_rows:
            t = r.data.get("tipo"); m = float(r.data.get("monto") or 0)
            if t in cash_in: emitted += m
            elif t in cash_out: emitted -= m
        truth = -212.8 + 505.04 - 1227.14 + 10.19
        self.assertAlmostEqual(emitted, truth, places=2)

    def test_registered_and_no_autodetect(self):
        # Registrado por format_id, pero NO autodetecta (mismas columnas que el local).
        self.assertIsNotNone(get_parser("balanz_internacional"))
        p = BalanzInternacionalParser()
        self.assertFalse(p.can_handle(HDR.split(",")))
        self.assertEqual(p.platform, "balanz")


if __name__ == "__main__":
    unittest.main()
