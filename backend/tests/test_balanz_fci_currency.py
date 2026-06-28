"""Regresión: el export de Balanz mal-etiqueta los FCI money-market en PESOS como
'Dólares'. La ESCALA del VCP (cuotaparte) discrimina con gap limpio: USD money-market
≈ 1, peso ≥ 6. Un FCI (clase Fondos) en 'Dólares' con VCP > 5 es en PESOS y hay que
corregirlo a ARS — si no, sus pesos se cuentan como dólares (×~tc_blue) → P&L/cash
peso-escala → el capital_final negativo gigante (mitad Balanz de las 78 cuentas).

Casos reales: RFPESOS A (VCP 107-206), DOLINKA (VCP 29-171) = peso mal-etiquetado;
BAHUSD (VCP ~1.3) = USD legítimo, NO tocar.

Corre con: cd backend && python3 -m pytest tests/test_balanz_fci_currency.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.parsers.balanz_movimientos import BalanzMovimientosParser

HDR = "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe"


def _parse(*rows):
    return BalanzMovimientosParser().parse(HDR + "\n" + "\n".join(rows) + "\n")


def _ccy_by_ticker(res):
    out = {}
    for rr in res.raw_rows:
        d = rr.data
        tk = (d.get("activo") or "").upper().replace(" ", "")
        if tk:
            out[tk] = d.get("moneda")
    return out


class BalanzFciCurrencyTest(unittest.TestCase):
    def test_fci_peso_maletiquetado_dolares_se_corrige_a_ars(self):
        # RFPESOS A: VCP 197.5 (peso-escala) etiquetado 'Dólares' → debe quedar ARS.
        res = _parse(
            "Liquidación de Suscripción / 8 / RFPESOS,RFPESOS A,Fondos,2026-02-01,8000,197.5,2026-02-01,Dólares,-1580000",
            "Liquidación de Rescate / 9 / DOLINKA,DOLINKA,Fondos,2026-03-01,5000,171.7,2026-03-01,Dólares,858500",
        )
        ccy = _ccy_by_ticker(res)
        self.assertEqual(ccy.get("RFPESOSA"), "ARS",
                         "FCI peso (VCP 197.5) mal-etiquetado 'Dólares' debe corregirse a ARS")
        self.assertEqual(ccy.get("DOLINKA"), "ARS",
                         "DOLINKA (VCP 171.7, peso) debe corregirse a ARS")

    def test_fci_usd_legitimo_queda_usd(self):
        # BAHUSD: VCP 1.35 (≈ cuotaparte en dólares) → es un FCI USD real, NO tocar.
        res = _parse(
            "Liquidación de Suscripción / 7 / BAHUSD,BAHUSD,Fondos,2026-02-01,740,1.35,2026-02-01,Dólares,-1000",
        )
        ccy = _ccy_by_ticker(res)
        self.assertEqual(ccy.get("BAHUSD"), "USD",
                         "FCI USD real (VCP ~1.3) NO debe tocarse — queda USD")

    def test_no_toca_bonos_usd_ni_otras_clases(self):
        # Un bono USD (clase Bonos/Corporativos, no FUND) con precio alto NO se toca:
        # el override es SOLO para FCI (clase FUND).
        res = _parse(
            "Boleto / 113 / VENTA / 0 / GD30 / U$S,GD30,Bonos,2025-11-02,800,72.5,2025-11-02,Dólares,58000",
        )
        ccy = _ccy_by_ticker(res)
        self.assertEqual(ccy.get("GD30"), "USD",
                         "un bono USD (no FUND) con VCP>5 NO debe tocarse — queda USD")


if __name__ == "__main__":
    unittest.main()
