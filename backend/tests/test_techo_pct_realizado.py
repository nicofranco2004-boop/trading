"""F4 · guard C7 — el techo de credibilidad del % realizado, en TODOS los lectores.

El techo existía desde antes (`ratePct` en assetPnl.js, `_rate_pct` en main.py)
y lo aplicaban DOS superficies: la ficha de un activo y el libro del asesor. El
resto publicaba `operations.pnl_pct` crudo — incluido el Wrapped, que se exporta
como PNG, y seis paquetes que van al modelo. La fila medida en producción daba
+188.566,67 % sobre un lote de US$106.

⚠️ ESTO ES UN CINTURÓN, NO UN ARREGLO. Las dos causas conocidas siguen abiertas
y tienen nombre (el motor toma el costo de `gross_amount` y los ingresos de
`unit_price*qty` sin reconciliarlos; y la venta en moneda distinta a la del lote
no convierte el precio de salida). Ver /api/admin/diagnose-scale.

Corre con: cd backend && python3 -m pytest tests/test_techo_pct_realizado.py
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# El import va DENTRO de cada test que lo necesita, no acá arriba: si la
# función no existiera, un import de módulo tumbaría el archivo entero con un
# ImportError y no se podría distinguir "el techo no está" de "el techo está
# pero no se aplica en tal superficie". Cada test tiene que fallar por SU
# motivo — es lo que hace que el archivo sirva de medición y no sólo de alarma.

FRONTEND = os.path.join(os.path.dirname(BACKEND), "frontend", "src")


class ElTechoEnSiTest(unittest.TestCase):

    def setUp(self):
        from realized_pnl import pct_creible, rate_pct
        self.pct_creible, self.rate_pct = pct_creible, rate_pct

    def test_lo_normal_pasa_intacto(self):
        for v in (0.0, 18.2, -34.5, 711.3):
            self.assertEqual(self.pct_creible(v), v)

    def test_el_borde_es_1000_y_sigue_valiendo(self):
        self.assertEqual(self.pct_creible(1000), 1000.0)
        self.assertIsNone(self.pct_creible(1000.1))
        self.assertIsNone(self.pct_creible(-1000.1))

    def test_el_caso_de_produccion(self):
        """La fila que motivó todo: +188.566,67 % sobre un lote de US$106."""
        self.assertIsNone(self.pct_creible(188566.67))

    def test_lo_que_no_es_un_numero_tampoco_se_publica(self):
        for v in (None, float("nan"), float("inf"), float("-inf"), "", "x", []):
            self.assertIsNone(self.pct_creible(v))

    def test_las_dos_puertas_dan_lo_mismo(self):
        """`rate_pct` (par total/costo) y `pct_creible` (columna) son la misma
        regla en escalas distintas, porque pnl_pct ≡ 100·pnl/costo."""
        for total, cost in ((1463, 15), (1000, 100), (1001, 100), (50, 200)):
            desde_el_par = self.rate_pct(total, cost, False)
            desde_la_columna = self.pct_creible(total / cost * 100)
            self.assertEqual(desde_el_par is None, desde_la_columna is None,
                             f"discrepan en total={total} cost={cost}")


class ElEspejoConElFrontendTest(unittest.TestCase):
    """Las dos copias (Python y JS) tienen que decir el mismo número.

    No se pueden unificar —son lenguajes distintos— así que lo que queda es
    que nadie pueda moverlas por separado sin que esto se ponga rojo.
    """

    def setUp(self):
        from realized_pnl import MAX_PNL_PCT, MAX_PNL_TO_COST
        self.MAX_PNL_PCT, self.MAX_PNL_TO_COST = MAX_PNL_PCT, MAX_PNL_TO_COST

    def _js(self, archivo="utils/assetPnl.js"):
        with open(os.path.join(FRONTEND, archivo), encoding="utf-8") as f:
            return f.read()

    def test_misma_constante(self):
        m = re.search(r"const MAX_PNL_TO_COST = (\d+)", self._js())
        self.assertIsNotNone(m, "no encontré MAX_PNL_TO_COST en assetPnl.js")
        self.assertEqual(int(m.group(1)), self.MAX_PNL_TO_COST)

    def test_el_frontend_tambien_expone_el_techo_en_porcentaje(self):
        js = self._js()
        self.assertIn("MAX_PNL_PCT", js,
                      "assetPnl.js tiene que exportar MAX_PNL_PCT (espejo de realized_pnl)")
        self.assertIn("export function pctCreible", js,
                      "assetPnl.js tiene que exportar pctCreible (espejo de pct_creible)")
        self.assertEqual(self.MAX_PNL_PCT, self.MAX_PNL_TO_COST * 100)


class NadieLoRecopiaTest(unittest.TestCase):
    """Guard contra la copia número N+1.

    Lee CÓDIGO, no números: un test de comportamiento pasa igual el día que
    alguien escriba el techo a mano en otro archivo, y esa copia es el bug —
    es la causa raíz más frecuente de este repo (C1/C2).
    """

    def _archivos_py(self):
        for raiz, dirs, files in os.walk(BACKEND):
            dirs[:] = [d for d in dirs
                       if d not in ("tests", "scripts", "__pycache__", "node_modules", ".git")]
            for f in files:
                if f.endswith(".py") and f != "realized_pnl.py":
                    yield os.path.join(raiz, f)

    def test_el_numero_vive_en_un_solo_lado_del_backend(self):
        """Nadie compara contra 1000 ni contra `cost * 10` por su cuenta."""
        A_MANO = re.compile(r"MAX_PNL_TO_COST\s*=\s*\d|MAX_PNL_PCT\s*=\s*\d")
        culpables = []
        for ruta in self._archivos_py():
            with open(ruta, encoding="utf-8") as f:
                for i, linea in enumerate(f, 1):
                    if A_MANO.search(linea):
                        culpables.append(f"{os.path.relpath(ruta, BACKEND)}:{i}")
        self.assertEqual(culpables, [],
                         "el techo se define en realized_pnl.py y en ningún otro "
                         f"lado del backend; se re-definió en: {culpables}")

    def test_el_frontend_tampoco_lo_recopia(self):
        A_MANO = re.compile(r"MAX_PNL_TO_COST\s*=\s*\d")
        culpables = []
        for raiz, dirs, files in os.walk(FRONTEND):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
            for f in files:
                if not f.endswith((".js", ".jsx")) or f.endswith(".test.js"):
                    continue
                ruta = os.path.join(raiz, f)
                if os.path.basename(ruta) == "assetPnl.js":
                    continue
                with open(ruta, encoding="utf-8") as fh:
                    for i, linea in enumerate(fh, 1):
                        if A_MANO.search(linea):
                            culpables.append(f"{os.path.relpath(ruta, FRONTEND)}:{i}")
        self.assertEqual(culpables, [],
                         "en el frontend el techo vive en utils/assetPnl.js y en "
                         f"ningún otro lado; se re-definió en: {culpables}")


class LasSuperficiesLoAplicanTest(unittest.TestCase):
    """Las cinco que NO lo aplicaban. Cada una con su camino real."""

    def test_wrapped_no_publica_el_porcentaje_absurdo(self):
        """El Wrapped sale como PNG a redes: es lo que más lejos llega."""
        import wrapped
        roto = [{"asset": "AL30", "op_type": "Venta", "exit_price": 1.0,
                 "pnl_usd": 200000.0, "pnl_pct": 188566.67}]
        s = wrapped._slide_best_trade(roto)
        self.assertIsNotNone(s)
        self.assertNotIn("188", s["subtitle"], "publicó el % imposible")
        self.assertNotIn("%", s["subtitle"], "arriba del techo no va ninguna tasa")
        self.assertIn("200,000", s["subtitle"], "…pero el MONTO sí se publica")

    def test_wrapped_si_publica_el_porcentaje_normal(self):
        import wrapped
        sano = [{"asset": "AAPL", "op_type": "Venta", "exit_price": 1.0,
                 "pnl_usd": 500.0, "pnl_pct": 18.2}]
        self.assertIn("18.2%", wrapped._slide_best_trade(sano)["subtitle"])

    def test_los_paquetes_de_la_ia_lo_aplican(self):
        """Los builders que leen operations.pnl_pct y se lo pasan al modelo."""
        from ai.builders.operations import build as _b_ops          # noqa: F401
        from ai.builders.operation_trade import build as _b_trade   # noqa: F401
        import ai.builders.insights as _insights                    # noqa: F401
        for mod in ("ai/builders/operations.py", "ai/builders/operation_trade.py",
                    "ai/builders/insights.py"):
            with open(os.path.join(BACKEND, mod), encoding="utf-8") as f:
                self.assertIn("pct_creible", f.read(),
                              f"{mod} publica pnl_pct sin pasarlo por el techo")

    def test_reportes_lo_aplica_en_el_embudo(self):
        """Todo el módulo lee las ops por `fetch_ops_in_range`: ahí va."""
        with open(os.path.join(BACKEND, "reporting", "builder.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("pct_creible", src)

    def test_la_exportacion_a_planilla_lo_aplica(self):
        with open(os.path.join(BACKEND, "main.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index('rendi_operaciones_')
        bloque = src[max(0, i - 3000):i]
        self.assertIn("pct_creible", bloque,
                      "el CSV de operaciones llevaba el % crudo al contador")


if __name__ == "__main__":
    unittest.main()
