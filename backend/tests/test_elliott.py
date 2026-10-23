"""Las ondas de Elliott de la ficha (elliott.py + GET /api/tecnico).

Las velas son dibujos con vértices conocidos (como en test_estructura.py): se
sabe de antemano qué conteo tiene que salir. Los casos:
  · un impulso de libro de 5 ondas, terminado y a mitad (en la 4, en la 5);
  · un impulso seguido de su corrección A-B-C (en la B, en la C);
  · una corrección A-B-C suelta, después de una suba;
  · la misma figura dada vuelta (una bajada);
  · cada regla dura rota: ese impulso NO se cuenta;
  · una A-B-C que no corrige nada (sin suba antes) no se cuenta;
  · pocos datos, y un conteo viejo que ya no describe el presente;
  · nunca mira el futuro: cada punto contado con la historia hasta un día es
    un pico o pozo ya confirmado ese día, y sigue siéndolo (mismo día, mismo
    precio) con toda la historia; el precio no pasó el nivel que lo invalida;
  · por HTTP, el camino de producción: velas guardadas por el trabajo nocturno
    y el conteo en la respuesta de la ficha.

Corre con: cd backend && python3 -m pytest tests/test_elliott.py
"""
import os
import random
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
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

import elliott
import estructura
import main
from fechas import hoy_art_date


def _dibujo(vertices, paso=6):
    """Cierres en línea recta de un vértice al siguiente, `paso` ruedas por
    segmento; antes, 40 ruedas quietas en el primer vértice (para que haya
    historia). El ÚLTIMO vértice es hoy: todavía no es pico ni pozo (se
    confirma 3 ruedas después), así que el último segmento es la onda en curso."""
    cierres = [vertices[0]] * 40
    for a, b in zip(vertices, vertices[1:]):
        for j in range(paso):
            cierres.append(a + (b - a) * j / paso)
    cierres.append(vertices[-1])
    return cierres


def _fecha_iso(i):
    return (date(2024, 1, 1) + timedelta(days=i)).isoformat()


def _velas(cierres, ancho=0.003):
    out, prev = [], cierres[0]
    for i, c in enumerate(cierres):
        out.append({"date": _fecha_iso(i), "open": prev, "high": max(prev, c) * (1 + ancho),
                    "low": min(prev, c) * (1 - ancho), "close": c})
        prev = c
    return out


def _conteo(vertices, **kw):
    return elliott.conteo(_velas(_dibujo(vertices, **kw)))


def _puntos(c):
    return [(o["onda"], round(o["precio"])) for o in c["ondas"]]


# Un impulso de libro: 1 = 100→120; la 2 devuelve el 60 % (108); la 3 mide
# 1,6 veces la 1 (108→140); la 4 devuelve el 37,5 % de la 3 (128); la 5 ≈ la 1
# (128→150). Antes, una bajada de 115 a 100 (de dónde arranca).
LIBRO = [115, 100, 120, 108, 140, 128, 150]


class ImpulsoTest(unittest.TestCase):

    def test_impulso_de_libro_terminado(self):
        r = _conteo(LIBRO + [141])
        self.assertTrue(r["disponible"], r)
        c = r["principal"]
        self.assertEqual((c["tipo"], c["dir"], c["ahora"]), ("impulso", "suba", "correccion"))
        self.assertEqual(_puntos(c), [("0", 100), ("1", 120), ("2", 108), ("3", 140), ("4", 128), ("5", 150)])
        self.assertEqual(c["confianza"], "alta")
        self.assertTrue(all(p["cumple"] for p in c["pautas"]), c["pautas"])
        # Terminado: la lectura deja de valer si pasa el final de la 5.
        self.assertEqual((c["invalida"]["lado"], c["invalida"]["por"]), ("encima", "final_5"))
        self.assertAlmostEqual(c["invalida"]["precio"], 150 * 1.003, places=2)
        # El alternativo dice otra cosa de hoy: que la 5 todavía no terminó.
        self.assertEqual(r["alternativo"]["ahora"], "onda_5")

    def test_en_la_onda_5_y_en_la_4(self):
        c = _conteo(LIBRO[:-1] + [141])["principal"]
        self.assertEqual((c["ahora"], _puntos(c)[-1]), ("onda_5", ("4", 128)))
        # En la 5 la regla que puede romperse es la de la 4: no bajar del final de la 1.
        self.assertEqual((c["invalida"]["lado"], c["invalida"]["por"]), ("debajo", "final_1"))
        self.assertAlmostEqual(c["invalida"]["precio"], 120 * 1.003, places=2)
        c = _conteo(LIBRO[:-2] + [131])["principal"]
        self.assertEqual((c["ahora"], _puntos(c)[-1]), ("onda_4", ("3", 140)))

    def test_en_la_onda_3(self):
        c = _conteo([115, 100, 120, 108, 125])["principal"]
        self.assertEqual((c["tipo"], c["ahora"]), ("impulso", "onda_3"))
        self.assertEqual(_puntos(c), [("0", 100), ("1", 120), ("2", 108)])
        # La 2 no puede bajar más que el arranque de la 1.
        self.assertEqual((c["invalida"]["lado"], c["invalida"]["por"]), ("debajo", "arranque_1"))
        # Con una sola pauta para mirar, la confianza no puede ser alta.
        self.assertNotEqual(c["confianza"], "alta")

    def test_impulso_y_su_correccion(self):
        # Después de la 5: A baja a 139, B rebota a 146 y ya baja → en la C.
        c = _conteo(LIBRO + [139, 146, 142])["principal"]
        self.assertEqual((c["tipo"], c["ahora"]), ("impulso_y_correccion", "onda_C"))
        self.assertEqual([o for o, _ in _puntos(c)], ["0", "1", "2", "3", "4", "5", "A", "B"])
        # La B no puede pasar el arranque de la A (el final de la 5).
        self.assertEqual((c["invalida"]["lado"], c["invalida"]["por"]), ("encima", "arranque_A"))
        # Sólo la A: en la B.
        c = _conteo(LIBRO + [139, 144])["principal"]
        self.assertEqual((c["ahora"], _puntos(c)[-1]), ("onda_B", ("A", 139)))
        # Terminada: la C pasó el final de la A.
        c = _conteo(LIBRO + [139, 146, 132, 136])["principal"]
        self.assertEqual((c["ahora"], _puntos(c)[-1]), ("fin_abc", ("C", 132)))

    def test_la_zona_de_cada_onda_en_curso(self):
        # En la 3: desde el final de la 2 (108), entre 1,38 y 1,9 veces la 1 (20).
        c = _conteo([115, 100, 120, 108, 125])["principal"]
        w1 = 120 * 1.003 - 100 * 0.997
        self.assertAlmostEqual(c["zona"]["desde"], 108 * 0.997 + 1.38 * w1, places=2)
        self.assertAlmostEqual(c["zona"]["hasta"], 108 * 0.997 + 1.90 * w1, places=2)
        self.assertEqual((c["zona"]["aciertos"], c["zona"]["casos"], c["zona"]["tonta"]),
                         elliott.ACIERTO_ZONA["onda_3"])
        # En la 4: devolviendo entre 24 % y 50 % de la 3, desde su final.
        c = _conteo(LIBRO[:-2] + [131])["principal"]
        w3 = 140 * 1.003 - 108 * 0.997
        self.assertAlmostEqual(c["zona"]["desde"], 140 * 1.003 - 0.50 * w3, places=2)
        self.assertAlmostEqual(c["zona"]["hasta"], 140 * 1.003 - 0.24 * w3, places=2)
        # Bajada: la zona en precios de verdad, de menor a mayor.
        c = _conteo([250 - x for x in [115, 100, 120, 108, 125]])["principal"]
        self.assertLess(c["zona"]["desde"], c["zona"]["hasta"])
        self.assertLess(c["zona"]["hasta"], 250 - 108)
        # Terminado (sin onda en curso que medir): sin zona.
        self.assertIsNone(_conteo(LIBRO + [141])["principal"]["zona"])

    def test_bajada_es_la_misma_figura_dada_vuelta(self):
        c = _conteo([250 - x for x in LIBRO + [141]])["principal"]
        self.assertEqual((c["tipo"], c["dir"], c["ahora"], c["confianza"]), ("impulso", "bajada", "correccion", "alta"))
        self.assertEqual(_puntos(c), [("0", 150), ("1", 130), ("2", 142), ("3", 110), ("4", 122), ("5", 100)])
        self.assertEqual([o["tipo"] for o in c["ondas"]], ["pico", "pozo", "pico", "pozo", "pico", "pozo"])
        self.assertEqual(c["invalida"]["lado"], "debajo")


class ReglasDurasTest(unittest.TestCase):
    """Cada regla rota: ningún conteo usa esos seis puntos como 0-1-2-3-4-5."""

    def _impulsos_con(self, vertices, puntos):
        lista = elliott.candidatos(_velas(_dibujo(vertices + [vertices[-1] - 8])))
        return [c for c in lista if c["tipo"] != "correccion" and len(c["pts"]) >= 6
                and [round(abs(p["precio"])) for p in c["pts"][:6]] == puntos]

    def test_la_2_baja_mas_que_el_arranque_de_la_1(self):
        self.assertEqual(self._impulsos_con([115, 100, 120, 98, 140, 128, 150], [100, 120, 98, 140, 128, 150]), [])
        # Con la 2 en 98 el arranque pasa a ser 98: 100→120 no es una onda 1.
        lista = elliott.candidatos(_velas(_dibujo([115, 100, 120, 98, 140, 128, 150, 142])))
        self.assertFalse(any(round(c["pts"][0]["precio"]) == 100 and c["tipo"] == "impulso"
                             and len(c["pts"]) >= 3 and round(c["pts"][2]["precio"]) == 98 for c in lista))

    def test_la_3_es_la_mas_corta(self):
        # 1 = 30, 3 = 17, 5 = 32: la 3 es la más corta.
        v = [115, 100, 130, 118, 135, 128, 160]
        self.assertEqual(self._impulsos_con(v, [100, 130, 118, 135, 128, 160]), [])

    def test_la_4_se_mete_en_la_1(self):
        # La 4 baja a 115, debajo del final de la 1 (120).
        v = [115, 100, 120, 108, 140, 115, 150]
        self.assertEqual(self._impulsos_con(v, [100, 120, 108, 140, 115, 150]), [])

    def test_la_5_no_pasa_a_la_3(self):
        # La 5 "truncada" (128 → 138, sin llegar a 140): no se cuenta.
        v = [115, 100, 120, 108, 140, 128, 138]
        self.assertEqual(self._impulsos_con(v, [100, 120, 108, 140, 128, 138]), [])

    def test_una_onda_de_un_dia_no_es_una_onda(self):
        # La figura de libro con la onda 2 hecha en 2 días (pico y pozo casi
        # pegados): ningún conteo usa esa onda 2.
        cierres = [115.0] * 40 + [115 - 15 * j / 6 for j in range(6)]
        cierres += [100 + 20 * j / 6 for j in range(6)] + [120, 108]
        cierres += [108 + 32 * j / 6 for j in range(1, 7)] + [140 - 12 * j / 6 for j in range(1, 7)]
        cierres += [128 + 22 * j / 6 for j in range(1, 7)] + [145, 141]
        v = _velas(cierres)
        piv = {p["i"] for p in estructura.pivotes(v)}
        i120 = cierres.index(120)
        self.assertTrue({i120, i120 + 1} <= piv, "la figura tiene el pico y el pozo pegados")
        for c in elliott.candidatos(v):
            I = [p["i"] for p in c["pts"]]
            self.assertFalse(i120 in I and i120 + 1 in I, c["ondas"])

    def test_la_3_no_pasa_a_la_1(self):
        v = [115, 100, 120, 108, 118, 110, 130]
        self.assertEqual(self._impulsos_con(v, [100, 120, 108, 118, 110, 130]), [])

    def test_en_la_4_bajar_del_final_de_la_1_la_invalida(self):
        # 1-2-3 de libro y la 4 en curso ya en 117 (debajo de 120): no hay "en la 4".
        r = _conteo([115, 100, 120, 108, 140, 117, 125])
        for c in (r.get("principal"), r.get("alternativo")):
            if c and c["ahora"] == "onda_4":
                self.assertNotEqual(_puntos(c)[:4], [("0", 100), ("1", 120), ("2", 108), ("3", 140)])

    def test_la_b_no_pasa_el_arranque_de_la_a(self):
        # Suba a 150, baja a 135 y "rebota" a 155: eso no es una B.
        lista = elliott.candidatos(_velas(_dibujo([90, 150, 135, 155, 140])))
        self.assertFalse(any(c["tipo"] == "correccion" and round(c["pts"][0]["precio"]) == 150 for c in lista))

    def test_una_abc_que_no_corrige_nada_no_se_cuenta(self):
        # 100 → 120 → 108 → 140 con apenas un tropiezo antes (106 → 100, menos
        # que la A): no es una A-B-C al alza (no corrige nada); sí puede ser un
        # impulso en la 4.
        lista = elliott.candidatos(_velas(_dibujo([106, 100, 120, 108, 140, 132])))
        self.assertFalse(any(c["tipo"] == "correccion" and c["dir"] == "suba" for c in lista))
        self.assertEqual(lista[0]["ahora"], "onda_4")


class CorreccionSueltaTest(unittest.TestCase):

    def test_abc_de_libro_despues_de_una_suba(self):
        # Sube de 70 a 120 en dos patas; corrige: A a 100, B a 110 (50 %), C a 90
        # (C = A): terminada.
        r = _conteo([70, 105, 95, 120, 100, 110, 90, 96])
        cs = [r["principal"], r["alternativo"]]
        abc = next((c for c in cs if c and c["tipo"] == "correccion"), None)
        self.assertIsNotNone(abc, cs)
        self.assertEqual((abc["dir"], abc["ahora"]), ("bajada", "fin_abc"))
        self.assertEqual(_puntos(abc), [("0", 120), ("A", 100), ("B", 110), ("C", 90)])
        self.assertTrue(all(p["cumple"] for p in abc["pautas"]), abc["pautas"])

    def test_en_la_c(self):
        r = _conteo([70, 105, 95, 120, 100, 110, 104])
        abc = next(c for c in (r["principal"], r["alternativo"]) if c and c["tipo"] == "correccion")
        self.assertEqual((abc["ahora"], _puntos(abc)), ("onda_C", [("0", 120), ("A", 100), ("B", 110)]))
        self.assertEqual((abc["invalida"]["lado"], abc["invalida"]["por"]), ("encima", "arranque_A"))


class AuditoriaTest(unittest.TestCase):
    """Lo que encontró la auditoría independiente del 23/10, un caso por hallazgo."""

    def test_la_zona_nunca_cae_donde_el_conteo_ya_no_vale(self):
        # En la 4 la zona bajaba hasta el 50 % de la 3, debajo del final de la 1
        # (justo el nivel que la invalida). Ahora se recorta o no hay zona.
        lista = elliott.candidatos(_velas(_dibujo([115, 100, 120, 108, 124, 122])))
        en4 = [c for c in lista if c["ahora"] == "onda_4"]
        self.assertTrue(en4, "la figura tiene una onda 4 en curso")
        for c in en4:
            z = elliott.zona(c)
            if z:
                self.assertGreaterEqual(z[0], c["pts"][1]["precio"], "la zona de la 4 no baja del final de la 1")
        # Y en general, en recorridos al azar: toda zona queda entre los límites del conteo.
        for semilla in (5, 17):
            random.seed(semilla)
            x, v = 100.0, []
            for i in range(300):
                x *= 1 + random.gauss(0, 0.02)
                v.append({"date": _fecha_iso(i), "open": x, "high": x * 1.01, "low": x * 0.99, "close": x})
            for corte in range(80, 300, 11):
                for c in elliott.candidatos(v[:corte]):
                    z = elliott.zona(c)
                    if z:
                        piso, techo = elliott._limites(c)
                        self.assertTrue(piso <= z[0] < z[1] <= techo, (corte, c["ahora"], z, piso, techo))

    def test_en_la_5_con_la_3_corta_hay_un_techo_y_se_dice(self):
        # 1 = 30, 3 = 22: la 5 no puede medir más que la 3. Ese techo ahora sale
        # como segundo nivel y la zona no lo pasa.
        c = _conteo([115, 100, 130, 118, 140, 133, 150])["principal"]
        self.assertEqual(c["ahora"], "onda_5")
        otro = c["invalida"]["otro"]
        self.assertEqual((otro["lado"], otro["por"]), ("encima", "tope_3_corta"))
        if c["zona"]:
            self.assertLessEqual(c["zona"]["hasta"], otro["precio"])

    def test_despues_de_la_5_tambien_cae_si_devuelve_todo(self):
        c = _conteo(LIBRO + [141])["principal"]
        self.assertEqual(c["ahora"], "correccion")
        self.assertEqual((c["invalida"]["otro"]["lado"], c["invalida"]["otro"]["por"]), ("debajo", "arranque_1"))
        self.assertAlmostEqual(c["invalida"]["otro"]["precio"], 100 * 0.997, places=2)

    def test_una_c_que_ya_borro_lo_que_corregia_no_se_ofrece(self):
        # Suba 90 → 120, A a 105, B a 115 y ahora 70: la caída ya borró toda la suba.
        for hoy in (85, 70):
            lista = elliott.candidatos(_velas(_dibujo([90, 120, 105, 115, hoy])))
            self.assertFalse(any(c["tipo"] == "correccion" and c["ahora"] == "onda_C" and not c["espejo"]
                                 for c in lista), hoy)
        # Con la C todavía arriba del arranque de la suba, sí, y con ese piso como segundo nivel.
        lista = elliott.candidatos(_velas(_dibujo([90, 120, 105, 115, 100])))
        c = next(c for c in lista if c["tipo"] == "correccion" and c["ahora"] == "onda_C" and not c["espejo"])
        self.assertEqual(c["otro"][1:], ("borro_lo_corregido", "debajo"))

    def test_un_dia_pico_y_pozo_entra_con_el_tipo_que_alterna(self):
        # Pico en 120; después una vela enorme (máximo 125, mínimo 90) que es pico
        # y pozo a la vez. Venía un pico: entra el pozo (antes se perdía).
        cierres = [100.0] * 10 + [105, 110, 115, 120, 116, 112, 108, 108, 108]
        v = [{"date": _fecha_iso(i), "open": c, "high": c, "low": c, "close": c} for i, c in enumerate(cierres)]
        k = len(v)
        v.append({"date": _fecha_iso(k), "open": 108, "high": 125, "low": 90, "close": 108})
        v += [{"date": _fecha_iso(k + 1 + j), "open": 108, "high": 109, "low": 107, "close": 108} for j in range(5)]
        zz = elliott._zigzag(v, estructura.N_PIVOTE)
        enorme = [p for p in zz if p["i"] == k]
        self.assertEqual([p["tipo"] for p in enorme], ["pozo"], zz)


class SinConteoTest(unittest.TestCase):

    def test_pocos_datos(self):
        r = elliott.conteo(_velas([100 + i for i in range(20)]))
        self.assertEqual((r["disponible"], r["motivo"]), (False, "pocos_datos"))

    def test_plano_no_inventa(self):
        r = elliott.conteo(_velas([100.0] * 200))
        self.assertEqual((r["disponible"], r["motivo"]), (False, "sin_conteo"))

    def test_conteo_viejo_no_se_ofrece(self):
        # El impulso de libro y después un año y medio quieto en 141 (un
        # "después de la 5" que dura más que todo el impulso).
        cierres = _dibujo(LIBRO + [141]) + [141.0] * 400
        lista = elliott.candidatos(_velas(cierres))
        self.assertFalse(any(len(c["pts"]) == 6 and round(c["pts"][5]["precio"]) == 150 for c in lista))


class NoMiraElFuturoTest(unittest.TestCase):

    def test_lo_contado_un_dia_ya_estaba_confirmado_y_no_cambia(self):
        n = estructura.N_PIVOTE
        for semilla in (3, 11, 29):
            random.seed(semilla)
            x, v = 100.0, []
            for i in range(420):
                x *= 1 + random.gauss(0.0005, 0.018)
                v.append({"date": _fecha_iso(i), "open": x, "high": x * 1.008, "low": x * 0.992, "close": x})
            piv_final = {(p["i"], p["tipo"]): p["precio"] for p in estructura.pivotes(v, n)}
            fecha_a_i = {d["date"]: i for i, d in enumerate(v)}
            contados = 0
            for corte in range(60, len(v) + 1, 3):
                r = elliott.conteo(v[:corte])
                for c in (r.get("principal"), r.get("alternativo")):
                    if not c:
                        continue
                    contados += 1
                    for o in c["ondas"]:
                        i = fecha_a_i[o["fecha"]]
                        self.assertLessEqual(i + n, corte - 1, f"punto sin confirmar (corte {corte})")
                        self.assertAlmostEqual(piv_final[(i, o["tipo"])], o["precio"], places=3,
                                               msg=f"el punto cambió con el futuro (corte {corte})")
                    # Desde el último punto hasta el corte, el precio no pasó el nivel que invalida.
                    ult = fecha_a_i[c["ondas"][-1]["fecha"]]
                    tramo = v[ult + 1:corte]
                    inv = c["invalida"]
                    if inv["lado"] == "debajo":
                        self.assertTrue(all(d["low"] > inv["precio"] - 1e-6 for d in tramo), (corte, c))
                    else:
                        self.assertTrue(all(d["high"] < inv["precio"] + 1e-6 for d in tramo), (corte, c))
            self.assertGreater(contados, 40, "la prueba tiene que ver conteos de verdad")


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class YahooDibujo:
    def __init__(self, hoy):
        self.hoy, self.velas = hoy, {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        velas = self.velas.get(ticker)
        if not velas:
            return pd.DataFrame()
        dias = _ruedas(self.hoy, len(velas))
        return pd.DataFrame({"Open": [x["open"] for x in velas], "High": [x["high"] for x in velas],
                             "Low": [x["low"] for x in velas], "Close": [x["close"] for x in velas],
                             "Volume": [1000.0] * len(velas)},
                            index=pd.DatetimeIndex([pd.Timestamp(d) for d in dias]))


class ElliottFichaTest(unittest.TestCase):
    """Por el camino de producción: el trabajo nocturno guarda las velas y la
    ficha las lee (velas_diarias.serie, que corrige cambios de ratio)."""

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"ell-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.yahoo = YahooDibujo(hoy_art_date())
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        r = self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "ZZEL", "quantity": 10,
                                                     "buy_price": 100, "asset_type": "STOCK"}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_la_ficha_trae_el_conteo(self):
        self.yahoo.velas["ZZEL"] = _velas(_dibujo(LIBRO + [141]))
        main._run_velas_diarias_job()
        r = self.client.get("/api/tecnico/ZZEL", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        e = r.json()["elliott"]
        self.assertTrue(e["disponible"], e)
        c = e["principal"]
        self.assertEqual((c["tipo"], c["ahora"], c["confianza"]), ("impulso", "correccion", "alta"))
        self.assertEqual([round(o["precio"]) for o in c["ondas"]], [100, 120, 108, 140, 128, 150])
        # Las fechas son las del gráfico (las mismas ruedas que `puntos`).
        fechas = {p["d"] for p in r.json()["puntos"]}
        self.assertTrue(all(o["fecha"] in fechas for o in c["ondas"]))


if __name__ == "__main__":
    unittest.main()
