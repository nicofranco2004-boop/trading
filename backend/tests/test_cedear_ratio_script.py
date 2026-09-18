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


if __name__ == "__main__":
    unittest.main()
