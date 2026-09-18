"""Tests del parser de ratios de `scripts/check_cedear_ratios.py`.

Sin red y sin base: lo único con lógica propia es leer el ratio tal como lo
escribe Comafi y leer la tabla del módulo JS. Si el parser se equivoca, el
chequeo diría "todo bien" sobre una tabla mal — que es peor que no tenerlo.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

import check_cedear_ratios as chk  # noqa: E402


class ParseRatioTest(unittest.TestCase):
    """Formatos REALES de la columna 'Ratio Cedear/Acción ó ADR' (362 filas)."""

    def test_formato_normal(self):
        self.assertEqual(chk.parse_ratio("4:1"), 4)
        self.assertEqual(chk.parse_ratio("15:1"), 15)
        self.assertEqual(chk.parse_ratio("120:1"), 120)

    def test_con_espacios(self):
        # 'GILD' viene como '4 : 1' y 'NVDA' como '24 : 1'
        self.assertEqual(chk.parse_ratio("4 : 1"), 4)
        self.assertEqual(chk.parse_ratio("24 : 1"), 24)
        self.assertEqual(chk.parse_ratio("144 : 1"), 144)

    def test_punto_en_vez_de_dos_puntos(self):
        # 6 filas reales lo traen así ('ORCL' = '3.1', 'DECK' = '25.1'). Leerlo
        # como decimal daría 3,1 en vez de 3 — un ratio 3 veces menor.
        self.assertEqual(chk.parse_ratio("3.1"), 3)
        self.assertEqual(chk.parse_ratio("25.1"), 25)

    def test_ratio_menor_a_uno(self):
        # 'NG' viene '1 :4': un CEDEAR representa 4 acciones.
        self.assertEqual(chk.parse_ratio("1 :4"), 0.25)

    def test_basura_no_inventa_un_numero(self):
        for v in ("", "s/d", None, "n/a", "-", "1:0", "0:1"):
            self.assertIsNone(chk.parse_ratio(v), f"{v!r} debería ser None")


class LeerTablaTest(unittest.TestCase):
    """La tabla que se compara es la que realmente usa el frontend."""

    def test_lee_el_modulo_real(self):
        tabla, src, (ini, fin) = chk.leer_tabla_js()
        self.assertGreater(len(tabla), 100)
        # Los dos ratios verificados contra el reporte del usuario.
        self.assertEqual(tabla["GOOGL"], 58)
        self.assertEqual(tabla["AVGO"], 39)
        # Fracciones (1 CEDEAR = 3 acciones) y claves con guión.
        self.assertAlmostEqual(tabla["ABEV"], 1 / 3, places=6)
        self.assertEqual(tabla["BRK-B"], 22)
        # Los comentarios de la tabla no deben colarse como ratios.
        self.assertNotIn("CEDEAR", tabla)
        self.assertNotIn("Comafi", tabla)

    def test_los_indices_delimitan_solo_la_tabla(self):
        _tabla, src, (ini, fin) = chk.leer_tabla_js()
        bloque = src[ini:fin]
        self.assertIn("GOOGL: 58", bloque)
        self.assertNotIn("export function", bloque)


class AplicarCorreccionesTest(unittest.TestCase):
    """`--write` reescribe código con una expresión regular: si se equivoca, deja
    la tabla peor que antes y en silencio. Estos son los casos que la pueden
    romper, probados sobre un bloque igual al real."""

    BLOQUE = (
        "export const CEDEAR_RATIOS = {\n"
        "  AAPL: 20, ABEV: 1/3, BABA: 9, BA: 24, 'BRK-B': 22, GOOGL: 58,\n"
        "}\n"
        "// comentario con un número que NO es un ratio: GOOGL: 347.45\n"
    )

    def _aplicar(self, diferentes):
        src = self.BLOQUE
        ini = src.index("CEDEAR_RATIOS = {") + len("CEDEAR_RATIOS = {")
        fin = src.index("\n}")
        return chk.aplicar_correcciones(src, ini, fin, diferentes)

    def test_corrige_un_entero(self):
        out = self._aplicar([("GOOGL", 99, 58, "Alphabet")])
        self.assertIn("GOOGL: 58", out)
        self.assertNotIn("GOOGL: 99", out)

    def test_corrige_a_fraccionario(self):
        # 1 CEDEAR = 3 acciones se escribe 1/3, no 0.3333
        out = self._aplicar([("ABEV", 7, 1 / 3, "Ambev")])
        self.assertIn("ABEV: 1/3", out)

    def test_clave_con_guion_conserva_las_comillas(self):
        out = self._aplicar([("BRK-B", 3, 22, "Berkshire")])
        self.assertIn("'BRK-B': 22", out)
        self.assertNotIn("BRK-B: 22", out.replace("'BRK-B': 22", ""))

    def test_corregir_BA_no_pisa_BABA(self):
        """El caso que rompe un regex ingenuo: un ticker que es prefijo de otro.

        El bloque pone BABA ANTES que BA a propósito. Con el orden natural
        (alfabético) este test pasa aunque el guard no exista, porque `count=1`
        encuentra BA primero de casualidad — o sea, certificaría en verde un
        regex roto. Invertido, sin el lookbehind 'BABA: 9' se convierte en
        'BABA: 24' y BA queda sin corregir.
        """
        out = self._aplicar([("BA", 2, 24, "Boeing")])
        self.assertIn("BA: 24", out)
        self.assertIn("BABA: 9", out)        # intacto
        self.assertNotIn("BABA: 24", out)

    def test_no_toca_los_numeros_de_los_comentarios(self):
        """Fuera del bloque hay `GOOGL: 347.45` (un PRECIO de ejemplo). Pisarlo
        rompería la documentación del módulo sin que nadie lo note."""
        out = self._aplicar([("GOOGL", 99, 58, "Alphabet")])
        self.assertIn("GOOGL: 347.45", out)

    def test_una_clave_ausente_aborta_en_vez_de_escribir_a_medias(self):
        with self.assertRaises(RuntimeError):
            self._aplicar([("NOEXISTE", 1, 5, "X")])

    def test_es_idempotente(self):
        """Corregir algo que ya está bien deja el texto igual."""
        out = self._aplicar([("GOOGL", 58, 58, "Alphabet")])
        self.assertEqual(out, self.BLOQUE)


if __name__ == "__main__":
    unittest.main()
