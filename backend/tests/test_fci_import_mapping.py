"""Valuación live de FCI propietarios importados (Cocos/Balanz).

Antes: un fondo importado se persistía con el ticker crudo del broker (COCOA,
BAHUSDA…) que NO existe en `fci_prices` → la posición se valuaba al COSTO para
siempre. Ahora el normalizer traduce el ticker al símbolo del catálogo
(`FCI:<slug>`) para los fondos del mapa curado, así cotizan con el VCP live igual
que un FCI cargado a mano. Fondos no confirmados (COCOSPPA, BAHUSDA, ALRTAFA)
quedan crudos = al costo (sin regresión).

Invariante clave testeado: para cada fondo del mapa, (a) su ad_name PASA el
filtro de seed → estará en el catálogo, y (b) el símbolo que emite el importador
== el símbolo que seedea el catálogo (mismo `_slug`). Sin eso, el precio no
resolvería.

Corre con: cd backend && python3 -m pytest tests/test_fci_import_mapping.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.fci_map import resolve_fci_symbol, BROKER_FCI_AD_NAME
from importing.normalizer import normalize_rows
from importing.schema import RawRow
from importing.parsers.cocos import CocosParser
from pricing import fci


COCOS_HEADER = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
                "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")


def _cocos_csv(*rows):
    return "\n".join([COCOS_HEADER, *rows]) + "\n"


class ResolveTest(unittest.TestCase):
    def test_known_tickers_resolve_to_catalog_symbols(self):
        self.assertEqual(resolve_fci_symbol("COCOA"), "FCI:COCOS-AHORRO-A")
        self.assertEqual(resolve_fci_symbol("COCOUSDPA"), "FCI:COCOS-DOLARES-PLUS-A")
        self.assertEqual(resolve_fci_symbol("SBSACAR"), "FCI:SBS-ACCIONES-ARGENTINA-A")

    def test_case_insensitive_and_whitespace(self):
        self.assertEqual(resolve_fci_symbol("  cocoa "), "FCI:COCOS-AHORRO-A")

    def test_unknown_ticker_returns_none(self):
        # COCOSPPA / BAHUSDA / ALRTAFA quedaron fuera a propósito (al costo).
        self.assertIsNone(resolve_fci_symbol("COCOSPPA"))
        self.assertIsNone(resolve_fci_symbol("BAHUSDA"))
        self.assertIsNone(resolve_fci_symbol("ALRTAFA"))
        self.assertIsNone(resolve_fci_symbol(""))
        self.assertIsNone(resolve_fci_symbol(None))


class CatalogInvariantTest(unittest.TestCase):
    """Garantías sin red: cada fondo mapeado seedea y su símbolo coincide."""

    def test_every_mapped_ad_name_passes_seed_filter(self):
        # Si un ad_name no pasa _is_seed_fund, nunca entra al catálogo → el
        # importador emitiría un FCI:<slug> sin precio. Eso debe NO pasar.
        for ticker, ad_name in BROKER_FCI_AD_NAME.items():
            self.assertTrue(fci._is_seed_fund(ad_name),
                            f"{ticker} → {ad_name!r} no pasa el filtro de seed del catálogo")

    def test_importer_symbol_matches_catalog_symbol(self):
        # El símbolo que emite el importador == el que seedea el catálogo.
        for ticker, ad_name in BROKER_FCI_AD_NAME.items():
            self.assertEqual(resolve_fci_symbol(ticker),
                             fci.FCI_PREFIX + fci._slug(ad_name),
                             f"drift de símbolo para {ticker}")

    def test_usd_funds_seed_as_usd(self):
        # Los fondos en dólares deben quedar con moneda USD en el catálogo.
        self.assertEqual(fci._parse_moneda(BROKER_FCI_AD_NAME["COCOUSDPA"]), "USD")
        self.assertEqual(fci._parse_moneda(BROKER_FCI_AD_NAME["COCOAUSD"]), "USD")
        self.assertEqual(fci._parse_moneda(BROKER_FCI_AD_NAME["COCOA"]), "ARS")


class NormalizerTest(unittest.TestCase):
    def test_mapped_fund_rewrites_symbol(self):
        norm, errs = normalize_rows([RawRow(1, {
            "fecha": "2025-03-01", "tipo": "COMPRA", "broker": "Cocos",
            "activo": "COCOA", "cantidad": "1000", "precio": "2.29",
            "moneda": "ARS", "asset_type": "FUND"})])
        self.assertEqual(errs, [])
        self.assertEqual(norm[0].asset_symbol, "FCI:COCOS-AHORRO-A")
        self.assertEqual(norm[0].asset_type, "FUND")

    def test_unmapped_fund_stays_raw(self):
        norm, _ = normalize_rows([RawRow(1, {
            "fecha": "2025-03-01", "tipo": "COMPRA", "broker": "Cocos",
            "activo": "COCOSPPA", "cantidad": "1000", "precio": "5",
            "moneda": "ARS", "asset_type": "FUND"})])
        self.assertEqual(norm[0].asset_symbol, "COCOSPPA")  # al costo, sin tocar

    def test_non_fund_never_rewritten(self):
        # Un ticker que casualmente está en el mapa pero NO es FUND no se toca.
        norm, _ = normalize_rows([RawRow(1, {
            "fecha": "2025-03-01", "tipo": "COMPRA", "broker": "Cocos",
            "activo": "COCOA", "cantidad": "10", "precio": "100",
            "moneda": "ARS", "asset_type": "STOCK"})])
        self.assertEqual(norm[0].asset_symbol, "COCOA")


class CocosEndToEndTest(unittest.TestCase):
    def test_cocos_fund_row_resolves_to_fci_symbol(self):
        # Fila real de suscripción de FCI Cocos Ahorro → debe terminar en FCI:...
        csv = _cocos_csv(
            "1;;01-03-2025;01-03-2025;Liq Suscripcion Fci;"
            "FCI COCOS AHORRO CL.A $ ESC (COCOA);ARS;;1000;2.29;2290;0;0;0;0;-2290")
        res = CocosParser().parse(csv)
        # El parser emite el ticker crudo + FUND…
        d = res.raw_rows[0].data
        self.assertEqual(d["activo"], "COCOA")
        self.assertEqual(d["asset_type"], "FUND")
        # …y el normalizer lo traduce al símbolo del catálogo.
        norm, _ = normalize_rows(res.raw_rows)
        self.assertEqual(norm[0].asset_symbol, "FCI:COCOS-AHORRO-A")


if __name__ == "__main__":
    unittest.main()
