"""La tabla de ratios del servidor es la de la pantalla.

`ratios_cedear.CEDEAR_RATIOS` es COPIA de `CEDEAR_RATIOS` de
frontend/src/utils/cedearRatio.js: la imagen de producción lleva sólo `backend/`
y el servidor no puede leer la de la pantalla. Con ella el gráfico en pesos de un
CEDEAR sin su serie en pesos se lleva a la escala del CEDEAR (`tecnico.serie`) y
se valúa BAC (`main.CEDEAR_USD_RATIOS`). Si alguien corrige un ratio en una sola
copia (a mano o con scripts/check_cedear_ratios.py --write, que escribe la de la
pantalla), esto falla y dice cuál.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

import ratios_cedear  # noqa: E402
from check_cedear_ratios import leer_tabla_js  # noqa: E402


class TablaTest(unittest.TestCase):

    def test_la_del_servidor_es_la_de_la_pantalla(self):
        pantalla, _, _ = leer_tabla_js()
        servidor = {k: float(v) for k, v in ratios_cedear.CEDEAR_RATIOS.items()}
        distintos = sorted(k for k in set(pantalla) | set(servidor) if pantalla.get(k) != servidor.get(k))
        self.assertEqual(distintos, [], "CEDEAR_RATIOS cambió en frontend/src/utils/cedearRatio.js y no en "
                                       "backend/ratios_cedear.py (o al revés): " +
                                       ", ".join(f"{k} pantalla={pantalla.get(k)} servidor={servidor.get(k)}"
                                                 for k in distintos))
        self.assertGreater(len(servidor), 150, "la tabla entera, no un pedazo")

    def test_ratio_de(self):
        r = ratios_cedear.ratio_de
        self.assertEqual((r("AAPL"), r("aapl.ba"), r(" MELI ")), (20.0, 20.0, 120.0))
        self.assertAlmostEqual(r("ABEV"), 1 / 3)                 # un CEDEAR son tres acciones
        # Con el código con que BYMA cotiza el CEDEAR: «BRK.B» es BRKB.
        self.assertEqual((r("BRK.B"), r("BRK-B"), r("BRKB")), (22.0, 22.0, 22.0))
        # Lo que la tabla no tiene, None: Cloudflare (CEDEAR sin ratio conocido),
        # un ETF que no es CEDEAR, y «SI», que en Nueva York es otra empresa (no
        # se traduce a SID: su precio ÷ el ratio de CSN no es nada).
        self.assertEqual((r("NET"), r("SCHD"), r("SI"), r(""), r(None)), (None, None, None, None, None))

    def test_el_lector_de_la_tabla_no_saltea_lo_que_no_entiende(self):
        # La paridad depende de leer bien la tabla de la pantalla. Antes, una clave
        # nueva con comillas dobles, un ratio con decimales (2.5 se leía 2) o una
        # clave en minúscula separaban las copias sin ponerse rojo (auditoría 06/11,
        # pruebas: hallazgo 5).
        import tempfile

        def leer(cuerpo):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                f.write("// encabezado: GOOGL: 347.45 no es un ratio\nexport const CEDEAR_RATIOS = {\n"
                        f"{cuerpo}\n}}\nexport const OTRA = {{ X: 1 }}\n")
            try:
                return leer_tabla_js(f.name)[0]
            finally:
                os.unlink(f.name)
        self.assertEqual(leer("  AAPL: 20, 'BRK-B': 22, \"NET\": 30, // un comentario: 9\n  XLE: 2.5, ABEV: 1 / 3,"),
                         {"AAPL": 20.0, "BRK-B": 22.0, "NET": 30.0, "XLE": 2.5, "ABEV": 1 / 3})
        for malo in ("  net: 30,", "  XLE: dos,", "  XLE 2,"):
            with self.subTest(malo=malo), self.assertRaises(ValueError):
                leer("  AAPL: 20," + malo)

    def test_bac_se_valua_con_la_misma_tabla(self):
        import main
        self.assertEqual(main.CEDEAR_USD_RATIOS, {"BAC": ratios_cedear.CEDEAR_RATIOS["BAC"]})


if __name__ == "__main__":
    unittest.main()
