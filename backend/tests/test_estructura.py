"""El Fibonacci automático de la ficha (estructura.py + GET /api/tecnico).

Entra por el camino de producción: las velas las guarda el trabajo nocturno
real (`main._run_velas_diarias_job`) con Yahoo reemplazado en su punto más bajo
(`pricing.yahoo._historia`), y el Fibonacci se lee de la ficha por HTTP. Las
velas falsas son un dibujo con vértices conocidos, así se sabe de antemano qué
tramo tiene que encontrar, en qué fecha se rompe y en qué nivel está hoy.

Los casos:
  · una suba con picos y pozos cada vez más altos que se rompe: el tramo va del
    pozo de arranque al pico, la ruptura es el primer cierre debajo del último
    pozo más alto, y los niveles y el retroceso de hoy son los esperados;
  · la misma figura al revés (una bajada);
  · un activo lateral: "sin tramo claro" (tramos chicos), no uno inventado;
  · una suba larga que nunca se rompió: lo dice y cuenta la suba en curso;
  · un tramo de hace más de un año: no se mide;
  · pocos datos: lo dice;
  · velas rotas (sin máximo/mínimo): no se cae ni inventa una mecha;
  · una acción argentina: los niveles salen en la moneda del gráfico;
  · nunca mira el futuro: lo confirmado con la historia hasta un día es lo
    mismo que se ve después.

Corre con: cd backend && python3 -m pytest tests/test_estructura.py
"""
import math
import os
import random
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import pandas as pd
from fastapi.testclient import TestClient

import estructura
import main
from fechas import hoy_art_date


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _dibujo(vertices, paso=6):
    """Cierres que van en línea recta de un vértice al siguiente, `paso` ruedas
    por segmento. Devuelve (cierres, {vértice: índice})."""
    cierres, donde = [], {}
    for k, (a, b) in enumerate(zip(vertices, vertices[1:])):
        donde.setdefault(k, len(cierres))
        for j in range(paso):
            cierres.append(a + (b - a) * j / paso)
    donde[len(vertices) - 1] = len(cierres)
    cierres.append(vertices[-1])
    return cierres, donde


class YahooDibujo:
    """`velas[ticker]` = lista de (o, h, l, c) para las ÚLTIMAS ruedas; las de
    antes no existen (como un activo que cotiza hace poco)."""

    def __init__(self, hoy):
        self.hoy, self.velas = hoy, {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        velas = self.velas.get(ticker)
        if not velas:
            return pd.DataFrame()
        dias = _ruedas(self.hoy, len(velas))
        o, h, l, c = zip(*velas)
        return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": [1000.0] * len(c)},
                            index=pd.DatetimeIndex([pd.Timestamp(d) for d in dias]))


def _velas_de(cierres, ancho=0.01):
    """La apertura es el cierre anterior; máximo y mínimo, ±`ancho` del cierre."""
    out, prev = [], cierres[0]
    for c in cierres:
        out.append((prev, max(prev, c) * (1 + ancho), min(prev, c) * (1 - ancho), c))
        prev = c
    return out


# La figura de la suba (ver el docstring del módulo):
#   140 plano → sube a 160 → 120 → 140 (techo más bajo) → 100 (pozo más bajo):
#   una bajada para que la historia arranque en algún lado (no se informa).
#   Desde 100: 130 → 118 → 150 → 138 → 170 (picos y pozos cada vez más altos)
#   → baja a 128 (rompe 138: fin de la suba) → 140 → 133 (hoy).
SUBA = [140, 140, 160, 120, 140, 100, 130, 118, 150, 138, 170, 128, 140, 133]


class EstructuraPuraTest(unittest.TestCase):

    def test_un_pivote_se_confirma_n_dias_despues_y_el_empate_es_del_primero(self):
        v = [{"date": f"d{i}", "open": c, "high": c, "low": c, "close": c}
             for i, c in enumerate([1, 2, 3, 5, 5, 4, 3, 2, 1, 2, 3, 4])]
        picos = [p for p in estructura.pivotes(v, 3) if p["tipo"] == "pico"]
        self.assertEqual([(p["i"], p["confirmado"]) for p in picos], [(3, 6)],
                         "dos días con el mismo máximo: el pico es el primero")
        pozos = [p for p in estructura.pivotes(v, 3) if p["tipo"] == "pozo"]
        self.assertEqual([p["i"] for p in pozos], [8])

    def test_nunca_mira_el_futuro(self):
        # Lo que se confirmó con la historia hasta un día no cambia al sumar días.
        random.seed(7)
        x, v = 100.0, []
        for i in range(500):
            x *= 1 + random.gauss(0, 0.02)
            v.append({"date": f"{i:04d}", "open": x, "high": x * 1.01, "low": x * 0.99, "close": x})
        final = estructura.tramos(v)["confirmados"]
        self.assertGreater(len(final), 5)
        for corte in range(60, 500, 7):
            parcial = estructura.tramos(v[:corte])["confirmados"]
            self.assertEqual(parcial, final[:len(parcial)], f"cambió el pasado al agregar días (corte {corte})")

    def test_tramo_de_hace_mas_de_un_anio_no_se_mide(self):
        # La suba de la figura y después más de un año quieto: no se mide.
        cierres, _ = _dibujo(SUBA)
        cierres += [cierres[-1]] * (estructura.MAX_RUEDAS_DESDE_EL_FINAL + 30)
        v = [{"date": f"{i:04d}", "open": o, "high": h, "low": l, "close": c}
             for i, (o, h, l, c) in enumerate(_velas_de(cierres))]
        f = estructura.fibonacci(v)
        self.assertEqual((f["disponible"], f["motivo"]), (False, "tramo_viejo"))
        self.assertEqual(f["viejo"]["dir"], "suba")

    def test_superado_cuenta_el_tramo_vivo(self):
        # Después de la suba rota, el precio vuelve a subir y pasa el pico (sin
        # que la bajada en el medio sea un movimiento claro): el Fibonacci de esa
        # suba ya no describe nada.
        cierres, _ = _dibujo(SUBA[:-2] + [165, 190])
        v = [{"date": f"{i:04d}", "open": o, "high": h, "low": l, "close": c}
             for i, (o, h, l, c) in enumerate(_velas_de(cierres))]
        f = estructura.fibonacci(v)
        self.assertFalse(f["disponible"])
        self.assertIn(f["motivo"], ("superado",))
        self.assertEqual(f["en_curso"]["dir"], "suba")


class FibonacciFichaTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"fib-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooDibujo(self.hoy)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _tener(self, broker, currency, asset, asset_type):
        r = self.client.post("/api/brokers", json={"name": broker, "currency": currency}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type},
                             headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _fib(self, asset, query=""):
        main._run_velas_diarias_job()
        r = self.client.get(f"/api/tecnico/{asset}{query}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _fecha(self, i, total):
        return _ruedas(self.hoy, total)[i].isoformat()

    def test_suba_que_se_rompe(self):
        self._tener("Schwab", "USD", "ZZFB", "STOCK")
        cierres, donde = _dibujo(SUBA)
        velas = _velas_de(cierres)
        self.yahoo.velas["ZZFB"] = velas
        f = self._fib("ZZFB")["fibonacci"]
        n = len(velas)
        self.assertTrue(f["disponible"], f)
        self.assertEqual(f["dir"], "suba")

        i100, i170, i138 = donde[5], donde[10], donde[9]
        # Desde el MÍNIMO de la vela del pozo de arranque hasta el MÁXIMO de la del pico.
        self.assertEqual(f["desde"], {"fecha": self._fecha(i100, n), "precio": round(velas[i100][2], 4)})
        self.assertEqual(f["hasta"], {"fecha": self._fecha(i170, n), "precio": round(velas[i170][1], 4)})
        # La ruptura: el primer cierre, después del pico, debajo del mínimo del pozo de 138.
        piso = velas[i138][2]
        i_rup = next(i for i in range(i170, n) if cierres[i] < piso)
        self.assertEqual(f["ruptura"]["fecha"], self._fecha(i_rup, n))
        self.assertEqual(f["ruptura"]["nivel"], round(piso, 4))
        self.assertEqual(f["ruptura"]["nivel_fecha"], self._fecha(i138, n))

        p0, p1 = velas[i100][2], velas[i170][1]
        self.assertEqual([x["nivel"] for x in f["niveles"]], [0.236, 0.382, 0.5, 0.618, 0.786])
        for x in f["niveles"]:
            self.assertAlmostEqual(x["precio"], p1 - x["nivel"] * (p1 - p0), places=3)
        hoy = (p1 - 133) / (p1 - p0)
        self.assertAlmostEqual(f["retroceso_hoy"], hoy, places=3)
        self.assertEqual(f["entre"], [0.5, 0.618])
        # Lo más que bajó: el mínimo de la vela de 128.
        i128 = donde[11]
        self.assertAlmostEqual(f["retroceso_maximo"]["valor"], (p1 - velas[i128][2]) / (p1 - p0), places=3)
        self.assertEqual(f["retroceso_maximo"]["fecha"], self._fecha(i128, n))
        self.assertEqual(f["retroceso_maximo"]["precio"], round(velas[i128][2], 4))
        # El tramo vivo es la bajada desde el pico, y todavía no se rompió.
        self.assertEqual(f["en_curso"]["dir"], "bajada")
        self.assertEqual(f["en_curso"]["desde"]["fecha"], self._fecha(i170, n))

    def test_bajada_que_se_rompe(self):
        # La misma figura dada vuelta: 300 − cada cierre.
        self._tener("Schwab", "USD", "ZZFB", "STOCK")
        cierres, donde = _dibujo([300 - x for x in SUBA])
        velas = _velas_de(cierres)
        self.yahoo.velas["ZZFB"] = velas
        f = self._fib("ZZFB")["fibonacci"]
        n = len(velas)
        self.assertTrue(f["disponible"], f)
        self.assertEqual(f["dir"], "bajada")
        i200, i130 = donde[5], donde[10]
        self.assertEqual(f["desde"]["fecha"], self._fecha(i200, n))
        self.assertEqual(f["desde"]["precio"], round(velas[i200][1], 4), "una bajada arranca en el MÁXIMO")
        self.assertEqual(f["hasta"]["precio"], round(velas[i130][2], 4))
        self.assertLess(f["niveles"][0]["precio"], f["niveles"][-1]["precio"],
                        "en una bajada los niveles suben desde el piso")
        self.assertEqual(f["entre"], [0.5, 0.618])

    def test_lateral_dice_sin_tramo_claro(self):
        # Un año dando vueltas alrededor de 100 (entre 98 y 102,5): la regla
        # encuentra dos "tramos", pero cada uno mide lo que el precio se mueve
        # en un par de días. No se inventa un Fibonacci con eso.
        self._tener("Schwab", "USD", "ZZFB", "STOCK")
        random.seed(4)
        x, cierres = 0.0, []
        for _ in range(260):
            x = 0.7 * x + random.gauss(0, 0.6)
            cierres.append(100 + x)
        self.yahoo.velas["ZZFB"] = _velas_de(cierres)
        ficha = self._fib("ZZFB")
        f = ficha["fibonacci"]
        self.assertFalse(f["disponible"])
        self.assertEqual(f["motivo"], "tramos_chicos")
        velas = [{"date": p["d"], "open": p["o"], "high": p["h"], "low": p["l"], "close": p["c"]}
                 for p in ficha["puntos"]]
        crudos = estructura.tramos(velas)["confirmados"]
        self.assertGreaterEqual(len(crudos), 1, "hay tramos: los descarta el tamaño, no la falta de pivotes")
        self.assertFalse(any(estructura._es_claro(velas, t) for t in crudos))

    def test_suba_que_nunca_se_rompio(self):
        # De 100 a 300 en 400 ruedas con picos y pozos cada vez más altos y
        # ningún cierre debajo del último pozo: no terminó ningún tramo.
        self._tener("Schwab", "USD", "ZZFB", "STOCK")
        vertices = [100]
        for k in range(40):
            vertices += [vertices[-1] + 8, vertices[-1] + 3]
        cierres, _ = _dibujo(vertices, paso=5)
        self.yahoo.velas["ZZFB"] = _velas_de(cierres)
        f = self._fib("ZZFB")["fibonacci"]
        self.assertEqual((f["disponible"], f["motivo"]), (False, "sin_tramo_terminado"))
        self.assertEqual(f["en_curso"]["dir"], "suba")
        self.assertIn("debajo_de", f["en_curso"]["se_rompe_si_cierra"])

    def test_pocos_datos(self):
        self._tener("Schwab", "USD", "ZZFB", "STOCK")
        self.yahoo.velas["ZZFB"] = _velas_de([100 + i for i in range(20)])
        f = self._fib("ZZFB")["fibonacci"]
        self.assertEqual((f["disponible"], f["motivo"], f["ruedas"]), (False, "pocos_datos", 20))

    def test_velas_rotas_no_inventan_mechas(self):
        # Yahoo manda velas con el máximo vacío (NaN): se guardan sólo con cierre.
        # Rotas también la vela del pico y la siguiente (que abre en 170 y tendría
        # la mecha más alta): el pico es su cierre, no una mecha inventada.
        self._tener("Schwab", "USD", "ZZFB", "STOCK")
        cierres, donde = _dibujo(SUBA)
        velas = _velas_de(cierres)
        nan = float("nan")
        rotas = {donde[10], donde[10] + 1, 3, 17, 40, 41, 42}
        velas = [(o, nan, l, c) if i in rotas else (o, h, l, c) for i, (o, h, l, c) in enumerate(velas)]
        self.yahoo.velas["ZZFB"] = velas
        ficha = self._fib("ZZFB")
        self.assertIsNone(ficha["puntos"][donde[10]]["h"], "la vela rota se guardó sin máximo")
        f = ficha["fibonacci"]
        self.assertTrue(f["disponible"], f)
        self.assertEqual(f["dir"], "suba")
        o, _, _, c = velas[donde[10]]
        self.assertEqual(f["hasta"]["precio"], round(max(o, c), 4))

    def test_accion_argentina_en_la_moneda_del_grafico(self):
        # GGAL en pesos con un dólar fijo de 1000: en dólares, la misma figura ÷ 1000.
        self._tener("IOL", "ARS", "GGAL", "ACCION")
        cierres, donde = _dibujo(SUBA)
        velas = _velas_de([c * 1000 for c in cierres])
        self.yahoo.velas["GGAL.BA"] = velas
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy, len(velas)):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0, 1000.0))
            conn.commit()
        usd = self._fib("GGAL", "?moneda=usd&local=1")["fibonacci"]
        ars = self.client.get("/api/tecnico/GGAL?moneda=ars&local=1", headers=self.h).json()["fibonacci"]
        self.assertTrue(usd["disponible"] and ars["disponible"])
        self.assertAlmostEqual(ars["hasta"]["precio"], velas[donde[10]][1], places=2)
        self.assertAlmostEqual(usd["hasta"]["precio"], velas[donde[10]][1] / 1000, places=4)
        self.assertEqual(usd["ruptura"]["fecha"], ars["ruptura"]["fecha"])


if __name__ == "__main__":
    unittest.main()
