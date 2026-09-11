"""F4 · el denominador de cualquier % sobre capital aportado, en UN solo lugar.

Antes de unificar, la misma regla estaba escrita SIETE veces con TRES
criterios distintos, y el mismo usuario veía números diferentes según la
pantalla:

  · max(nd, nd_máx) con piso 100   — el libro del asesor
  · max(nd, pico de CARTERA × 0,8) — la curva del Dashboard
  · nd si nd ≥ 60 % del pico       — Análisis, en CINCO copias

El pico de la CARTERA estaba MAL y no es opinable: mete la ganancia no
realizada adentro del denominador de un porcentaje sobre capital aportado.

Corre con: cd backend && python3 -m pytest tests/test_denominador_aportado.py
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import twr
FRONTEND = os.path.join(os.path.dirname(BACKEND), "frontend", "src")


class LaReglaTest(unittest.TestCase):

    def test_el_mayor_entre_hoy_y_el_maximo(self):
        self.assertEqual(twr.denominador_aportado(1_000, 100_000), 100_000)
        self.assertEqual(twr.denominador_aportado(100_000, 1_000), 100_000)
        self.assertEqual(twr.denominador_aportado(10_000, 10_000), 10_000)

    def test_un_aportado_negativo_no_rompe(self):
        """Retiros por encima de los aportes es un dato legítimo (11,7 % de las
        filas de producción al 16/08), no un error."""
        self.assertEqual(twr.denominador_aportado(-10_000, 100_000), 100_000)

    def test_abajo_del_piso_no_se_publica(self):
        """US$3 de capital con US$30 de resultado son +1000 % y se llevan
        puesto el Mejor/Peor de cualquier ranking."""
        self.assertIsNone(twr.denominador_aportado(50, 50))
        self.assertIsNone(twr.denominador_aportado(0, 0))
        self.assertIsNone(twr.denominador_aportado(99.99, 0))
        self.assertEqual(twr.denominador_aportado(100, 0), 100)   # el borde vale

    def test_es_continua(self):
        """El umbral del 60 % que había en Análisis era discontinuo: retirar un
        dólar de más lo cruzaba y el denominador saltaba de golpe. `max()` no
        puede hacer eso — el denominador nunca baja al retirar."""
        anterior = None
        for retirado in range(0, 100_000, 5_000):
            d = twr.denominador_aportado(100_000 - retirado, 100_000)
            if anterior is not None:
                self.assertEqual(d, anterior, "el denominador se movió con un retiro")
            anterior = d

    def test_nunca_devuelve_cero(self):
        """None es 'no lo puedo calcular'. Cero es 'no ganaste nada', que es
        otra afirmación — y la que se publicaba antes."""
        for a, b in ((0, 0), (-5, -5), (None, None), ("x", None)):
            self.assertIsNot(twr.denominador_aportado(a, b), 0)


class ElPisoEstaEnDolaresTest(unittest.TestCase):
    """Lo que encontró auditar la unificación: el piso es en USD y se estaba
    comparando contra montos en PESOS."""

    def test_las_dos_monedas_dan_el_MISMO_veredicto(self):
        FX = 1400.0
        for nd_usd in (50, 99, 100, 150, 5_000):
            en_usd = twr.denominador_aportado(nd_usd, nd_usd)
            en_ars = twr.denominador_aportado(nd_usd * FX, nd_usd * FX, FX)
            self.assertEqual(en_usd is None, en_ars is None,
                             f"con US${nd_usd} una moneda publica y la otra no")

    def test_sin_fx_los_pesos_pasaban_todos(self):
        """La medición del bug: 70.000 pesos son US$50 —abajo del piso— pero
        contra un piso de 100 a secas pasaban igual."""
        self.assertIsNotNone(twr.denominador_aportado(70_000, 70_000))       # sin fx: pasa
        self.assertIsNone(twr.denominador_aportado(70_000, 70_000, 1400))    # con fx: no

    def test_un_fx_invalido_no_rompe_el_guard(self):
        for fx in (0, -1, None, "x", float("nan")):
            self.assertIsNone(twr.denominador_aportado(50, 50, fx),
                              f"con fx={fx!r} el piso tiene que seguir filtrando")


class ElEspejoConElFrontendTest(unittest.TestCase):
    """No se pueden unificar —son lenguajes distintos— así que lo que queda es
    que nadie pueda moverlas por separado sin que esto se ponga rojo."""

    def _evolution_js(self):
        with open(os.path.join(FRONTEND, "utils", "evolution.js"), encoding="utf-8") as f:
            return f.read()

    def test_mismo_piso(self):
        m = re.search(r"PISO_DENOMINADOR_USD\s*=\s*(\d+)", self._evolution_js())
        self.assertIsNotNone(m, "no encontré PISO_DENOMINADOR_USD en evolution.js")
        self.assertEqual(int(m.group(1)), twr.PISO_DENOMINADOR_USD)

    def test_el_frontend_expone_la_misma_funcion(self):
        self.assertIn("export function denominadorAportado", self._evolution_js())

    def test_el_frontend_tambien_acepta_el_fx_del_piso(self):
        """Si un lado convierte el piso y el otro no, vuelve la divergencia
        entre monedas por la puerta de atrás."""
        self.assertRegex(self._evolution_js(),
                         r"export function denominadorAportado\([^)]*fxDelPiso")


class NadieLaRecopiaTest(unittest.TestCase):
    """Guard contra la copia número 8. Lee CÓDIGO, no números: un test de
    comportamiento pasa igual el día que alguien escriba la copia siguiente en
    otro archivo, y esa copia es el bug."""

    # Las tres formas que había: el umbral del 60 %, el pico de cartera × 0,8,
    # y el piso escrito a mano.
    FORMAS = re.compile(r"\*\s*0\.6\b.*>\s*1000|>\s*1000\b.*\*\s*0\.6"
                        r"|peakValue\w*\s*\*\s*0\.8"
                        r"|base_nd\s*<\s*100")

    def _archivos(self, raiz, exts, saltear):
        for base, dirs, files in os.walk(raiz):
            dirs[:] = [d for d in dirs
                       if d not in ("node_modules", "__pycache__", ".git", "tests", "scripts", "dist")]
            for f in files:
                if f.endswith(exts) and ".test." not in f and f not in saltear:
                    yield os.path.join(base, f)

    def test_ni_en_el_backend_ni_en_el_frontend(self):
        culpables = []
        for ruta in self._archivos(BACKEND, (".py",), {"twr.py"}):
            with open(ruta, encoding="utf-8") as f:
                for i, l in enumerate(f, 1):
                    if l.lstrip().startswith("#"):
                        continue          # los comentarios pueden CONTAR la historia
                    if self.FORMAS.search(l):
                        culpables.append(f"{os.path.relpath(ruta, BACKEND)}:{i}")
        for ruta in self._archivos(FRONTEND, (".js", ".jsx"), {"evolution.js"}):
            with open(ruta, encoding="utf-8") as f:
                for i, l in enumerate(f, 1):
                    ls = l.lstrip()
                    if ls.startswith(("//", "*", "/*")):
                        continue
                    if self.FORMAS.search(l):
                        culpables.append(f"{os.path.relpath(ruta, FRONTEND)}:{i}")
        self.assertEqual(culpables, [],
                         "el denominador vive en twr.py y evolution.js y en ningún "
                         f"otro lado; se re-escribió en: {culpables}")


if __name__ == "__main__":
    unittest.main()
