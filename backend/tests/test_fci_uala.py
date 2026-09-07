"""Fondos de Ualá en el catálogo de FCI.

Un usuario reportó (2026-09-07) que "no están los fondos de Ualá". La razón no
era la fuente: en CAFCI/ArgentinaDatos NO se llaman "Ualá" sino "Ualintec" (la
administradora es Ualintec Capital), así que nunca entraron al allowlist.

Este test fija las dos mitades del arreglo, SIN red (fixture con la forma real
de la fuente, valores tomados de ArgentinaDatos el 2026-09-07):
  • el allowlist los seedea, con la moneda y el precio (vcp/1000) correctos;
  • el emisor sale como "Ualá (Ualintec)" — es uno de los dos campos por los que
    busca el selector de fondos, así que sin eso el usuario que tipea "Ualá"
    sigue sin encontrarlos aunque el fondo ya esté en el catálogo.
"""
import os, sqlite3, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

from pricing import fci

# Forma real de la fuente. vcp = valor por 1000 cuotapartes.
FUNDS = [
    {"fondo": "Ualintec Ahorro Pesos - Clase A",     "fecha": "2026-09-04", "vcp": 8506.463,  "_cat": "mercadoDinero"},
    {"fondo": "Ualintec Ahorro Pesos - Clase C",     "fecha": "2026-09-04", "vcp": 8831.724,  "_cat": "mercadoDinero"},
    {"fondo": "Ualintec Renta Dólares - Clase A",    "fecha": "2026-09-04", "vcp": 1214.527,  "_cat": "rentaFija"},
    {"fondo": "Ualintec Cobertura - Clase A",        "fecha": "2026-09-04", "vcp": 1805.673,  "_cat": "rentaFija"},
    {"fondo": "Ualintec Pesos Plus - Clase A",       "fecha": "2026-09-04", "vcp": 1979.074,  "_cat": "rentaFija"},
    {"fondo": "Ualintec Renta Fija Pesos - Clase A", "fecha": "2026-09-04", "vcp": 13206.075, "_cat": "rentaFija"},
    {"fondo": "Ualintec Renta Variable Pesos - Clase A", "fecha": "2026-09-04", "vcp": 2197.47, "_cat": "rentaVariable"},
    # Ruido: un fondo de otro emisor no debe verse afectado por el override.
    {"fondo": "Mercado Fondo - Clase A",             "fecha": "2026-09-04", "vcp": 2000.0,    "_cat": "mercadoDinero"},
]


class FciUalaTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        fci.ensure_tables(self.conn)
        fci.seed_catalog(self.conn, funds=FUNDS)
        fci.refresh_prices(self.conn, funds=FUNDS)
        self.cat = {r["symbol"]: r for r in fci.list_catalog(self.conn)}

    def test_seedea_las_seis_familias(self):
        """Las 6 familias entran al catálogo (si una se cae del allowlist, salta acá)."""
        for sym in ("FCI:UALINTEC-AHORRO-PESOS-A", "FCI:UALINTEC-RENTA-DOLARES-A",
                    "FCI:UALINTEC-COBERTURA-A", "FCI:UALINTEC-PESOS-PLUS-A",
                    "FCI:UALINTEC-RENTA-FIJA-PESOS-A", "FCI:UALINTEC-RENTA-VARIABLE-PESOS-A"):
            self.assertIn(sym, self.cat, f"{sym} no quedó en el catálogo")

    def test_emisor_dice_uala(self):
        """El buscador filtra por emisor: sin esto, tipear "Ualá" no los encuentra."""
        for sym, row in self.cat.items():
            if sym.startswith("FCI:UALINTEC"):
                self.assertEqual(row["emisor"], "Ualá (Ualintec)")
        # El override es por prefijo: no debe pisar a otros emisores.
        self.assertEqual(self.cat["FCI:MERCADO-FONDO-A"]["emisor"], "Mercado Fondo")

    def test_moneda_por_fondo(self):
        """Renta Dólares es el único en USD. Cobertura es dollar-linked pero su
        cuotaparte cotiza en PESOS — marcarlo USD lo inflaría ~1400x."""
        self.assertEqual(self.cat["FCI:UALINTEC-RENTA-DOLARES-A"]["moneda"], "USD")
        for sym in ("FCI:UALINTEC-COBERTURA-A", "FCI:UALINTEC-AHORRO-PESOS-A",
                    "FCI:UALINTEC-PESOS-PLUS-A", "FCI:UALINTEC-RENTA-FIJA-PESOS-A",
                    "FCI:UALINTEC-RENTA-VARIABLE-PESOS-A"):
            self.assertEqual(self.cat[sym]["moneda"], "ARS", sym)

    def test_precio_es_vcp_sobre_mil(self):
        """El VCP de la fuente es por 1000 cuotapartes: sin dividir, la tenencia
        del usuario se muestra 1000x."""
        self.assertAlmostEqual(self.cat["FCI:UALINTEC-RENTA-DOLARES-A"]["price"], 1.214527, places=6)
        self.assertAlmostEqual(self.cat["FCI:UALINTEC-AHORRO-PESOS-A"]["price"], 8.506463, places=6)

    def test_clases_no_se_pisan(self):
        """Cada clase es su propio símbolo: A y C tienen VCP distinto y mezclarlas
        da una valuación mal (la trampa que documenta fci_map)."""
        self.assertNotEqual(self.cat["FCI:UALINTEC-AHORRO-PESOS-A"]["price"],
                            self.cat["FCI:UALINTEC-AHORRO-PESOS-C"]["price"])


if __name__ == "__main__":
    unittest.main()
