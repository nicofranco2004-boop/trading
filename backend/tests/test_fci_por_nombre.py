"""FCI cargado por NOMBRE con la plantilla manual de Rendi.

Caso real (2026-09-08): un usuario subió su FCI de Ualá con la plantilla y en la
columna del activo escribió el nombre del fondo, no un ticker — porque para un
fondo el usuario NO tiene ticker, su app le muestra "Ualintec Renta Dolares -
Clase A". El normalizer resuelve FCI contra un mapa de tickers de broker, así que
no matcheó nada y la posición quedó al costo, sin precio y con el activo
"UALINTEC-RENTA-DOLARES---CLASE-A" (los tres guiones son la firma del `\\s+`→`-`
del normalizer sobre " - ").

Se fija que la clave canónica colapse las tres formas al MISMO símbolo que
produce `_slug` sobre el nombre oficial, y que el resolver no adivine cuando no
debe (ambiguo, ticker suelto, catálogo vacío).
"""
import os, sqlite3, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

from pricing import fci
from importing.fci_map import _name_key, resolve_fci_by_name

FUNDS = [
    {"fondo": "Ualintec Renta Dólares - Clase A", "fecha": "2026-09-04", "vcp": 1214.527, "_cat": "rentaFija"},
    {"fondo": "Ualintec Renta Dólares - Clase C", "fecha": "2026-09-04", "vcp": 1226.460, "_cat": "rentaFija"},
    {"fondo": "Ualintec Ahorro Pesos - Clase A",  "fecha": "2026-09-04", "vcp": 8506.463, "_cat": "mercadoDinero"},
    {"fondo": "Mercado Fondo - Clase A",          "fecha": "2026-09-04", "vcp": 2000.0,   "_cat": "mercadoDinero"},
]


class NameKeyTest(unittest.TestCase):
    def test_las_tres_formas_dan_la_misma_clave(self):
        """Lo que escribe el usuario, lo que le hace el normalizer y el nombre
        oficial tienen que caer en la misma clave."""
        esperado = fci._slug("Ualintec Renta Dólares - Clase A")
        self.assertEqual(esperado, "UALINTEC-RENTA-DOLARES-A")
        for forma in ("Ualintec Renta Dólares - Clase A",       # como lo copia del factsheet
                      "UALINTEC-RENTA-DOLARES---CLASE-A",       # como lo dejó el normalizer
                      "ualintec renta dolares clase a",         # tipeado a mano, sin acento
                      "  Ualintec  Renta  Dolares - Clase A "): # con espacios de más
            self.assertEqual(_name_key(forma), esperado, forma)

    def test_no_confunde_clases(self):
        self.assertNotEqual(_name_key("Ualintec Renta Dólares - Clase A"),
                            _name_key("Ualintec Renta Dólares - Clase C"))


class ResolveByNameTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        fci.ensure_tables(self.conn)
        fci.seed_catalog(self.conn, funds=FUNDS)

    def test_resuelve_el_caso_del_usuario(self):
        self.assertEqual(
            resolve_fci_by_name(self.conn, "UALINTEC-RENTA-DOLARES---CLASE-A"),
            "FCI:UALINTEC-RENTA-DOLARES-A")

    def test_resuelve_el_nombre_tal_cual_lo_escribe(self):
        self.assertEqual(
            resolve_fci_by_name(self.conn, "Ualintec Renta Dólares - Clase A"),
            "FCI:UALINTEC-RENTA-DOLARES-A")
        self.assertEqual(
            resolve_fci_by_name(self.conn, "Ualintec Ahorro Pesos - Clase A"),
            "FCI:UALINTEC-AHORRO-PESOS-A")

    def test_respeta_la_clase(self):
        """La trampa cara: mapear a otra clase valúa mal. C tiene que dar C."""
        self.assertEqual(
            resolve_fci_by_name(self.conn, "Ualintec Renta Dolares - Clase C"),
            "FCI:UALINTEC-RENTA-DOLARES-C")

    def test_no_toca_lo_que_no_es_fondo(self):
        for x in ("AAPL", "GGAL.BA", "AL30", "", None, "BRK-B"):
            self.assertIsNone(resolve_fci_by_name(self.conn, x), x)

    def test_no_toca_un_simbolo_ya_resuelto(self):
        self.assertIsNone(resolve_fci_by_name(self.conn, "FCI:UALINTEC-RENTA-DOLARES-A"))

    def test_sin_match_no_inventa(self):
        """Un fondo que no está en el catálogo queda como está (= al costo),
        nunca se mapea 'al más parecido'."""
        self.assertIsNone(resolve_fci_by_name(self.conn, "Cocos Pesos Plus - Clase A"))
        self.assertIsNone(resolve_fci_by_name(self.conn, "Ualintec Renta Dolares - Clase Z"))

    def test_catalogo_vacio_no_rompe(self):
        vacia = sqlite3.connect(":memory:")
        vacia.row_factory = sqlite3.Row
        self.assertIsNone(resolve_fci_by_name(vacia, "Ualintec Renta Dolares - Clase A"))


if __name__ == "__main__":
    unittest.main()
