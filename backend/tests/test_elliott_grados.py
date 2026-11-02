"""Elliott sobre más historia y el Fibonacci del impulso entero, con INTC.

EL CASO (Nico, 31/10/26, mirando INTC en velas diarias): un impulso clarísimo
de 5 ondas desde ~US$ 35 hasta el máximo de US$ 142,35 (30/06/26) —la 1 un
piquito en enero, la 2 cerca de la media de 200 en marzo, la 3 en mayo, la 4
en junio y la 5 en el máximo— y después la corrección A-B. Rendi sólo mostraba
la A-B, y el Fibonacci decía «sin tramo para medir».

LA CAUSA, MEDIDA (02/11): el motor buscaba sólo en los últimos 26 picos y
pozos (`MAX_PUNTOS`). Con N = 3 velas, en INTC eso llegaba hasta el 03/02/26:
el arranque (nov./dic. 2025) y la onda 1 (22/01/26) quedaban afuera. Con más
puntos el impulso aparece y cumple todas las reglas. No se buscó sobre todos
los puntos (con 100 o 200 la búsqueda tarda segundos): se suman grados más
grandes, el mismo zigzag quedándose con los giros grandes (`elliott._grados`).

Las velas son las REALES de Yahoo (tests/fixtures/intc_velas_3_anios.json,
bajadas el 02/11/26), y la prueba principal va por el camino de producción:
el trabajo nocturno las guarda y GET /api/tecnico las lee.

Corre con: cd backend && python3 -m pytest tests/test_elliott_grados.py
"""
import json
import os
import sys
import tempfile
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

import elliott
import estructura
import main
from ai import resumen_tecnico_hechos
from fechas import hoy_art_date
from tests.test_elliott import YahooDibujo


def _intc():
    with open(os.path.join(HERE, "fixtures", "intc_velas_3_anios.json")) as f:
        filas = json.load(f)["velas"]
    return [{"date": d, "open": o, "high": h, "low": l, "close": c} for d, o, h, l, c in filas]


# Lo que vio Nico: (onda, precio). El arranque es el mínimo del 21/11/25.
IMPULSO = [("0", 32.89), ("1", 54.6), ("2", 40.63), ("3", 132.75), ("4", 98.33), ("5", 142.35)]
CORRECCION = [("A", 81.79), ("B", 127.44)]


def _ondas(c):
    return [(o["onda"], round(o["precio"], 2)) for o in c["ondas"]]


class MotorConINTCTest(unittest.TestCase):

    def setUp(self):
        self.velas = _intc()

    def test_cuenta_el_impulso_grande_y_la_correccion_juntos(self):
        e = elliott.conteo(self.velas)
        c = e["principal"]
        self.assertEqual((c["tipo"], c["dir"], c["ahora"]), ("impulso_y_correccion", "suba", "onda_C"))
        self.assertEqual(_ondas(c), IMPULSO + CORRECCION)
        self.assertEqual([o["fecha"] for o in c["ondas"]][1:6],
                         ["2026-01-22", "2026-03-30", "2026-05-11", "2026-06-05", "2026-06-30"])

    def test_con_solo_el_grado_chico_no_aparecia(self):
        # El mecanismo del error, para que no vuelva: los últimos MAX_PUNTOS
        # picos y pozos no llegan a la onda 1 (22/01/26).
        zz = elliott._zigzag(self.velas, estructura.N_PIVOTE)
        chico = zz[-elliott.MAX_PUNTOS:]
        self.assertGreater(self.velas[chico[0]["i"]]["date"], "2026-01-22")
        with mock.patch.object(elliott, "_grados", lambda z: [z[-elliott.MAX_PUNTOS:]]):
            c = elliott.conteo(self.velas)["principal"]
        self.assertNotIn(("5", 142.35), _ondas(c))

    def test_la_otra_lectura_no_es_el_mismo_conteo_con_otro_arranque(self):
        # Con los grados grandes salía «en la C» y, de otra lectura, «en la
        # corrección después de 5 ondas» con las mismas ondas 1 a 5 y el
        # arranque en otro pozo (34,95 en vez de 32,89): decía lo mismo.
        e = elliott.conteo(self.velas)
        a = e["alternativo"]
        if a:
            ondas_p = [o["fecha"] for o in e["principal"]["ondas"][1:6]]
            ondas_a = [o["fecha"] for o in a["ondas"][1:6]]
            self.assertNotEqual(ondas_p, ondas_a, a)
        pts = lambda *ii: [{"i": i, "tipo": "pozo" if k % 2 == 0 else "pico"} for k, i in enumerate(ii)]
        base = {"dir": "suba", "espejo": False}
        en_c = {**base, "ahora": "onda_C", "pts": pts(1, 10, 20, 30, 40, 50, 60, 70)}
        fin_5 = {**base, "ahora": "correccion", "pts": pts(5, 10, 20, 30, 40, 50)}
        self.assertFalse(elliott._dice_otra_cosa(en_c, fin_5))
        en_3 = {**base, "ahora": "onda_3", "pts": pts(5, 10, 20)}
        self.assertTrue(elliott._dice_otra_cosa(en_c, en_3))

    def test_los_grados_grandes_son_los_mismos_picos_y_pozos(self):
        # Ningún punto nuevo ni corrido: un grado grande es un subconjunto del
        # zigzag (mismo día, mismo tipo, mismo precio), y el último grado
        # cubre la historia entera.
        zz = elliott._zigzag(self.velas, estructura.N_PIVOTE)
        todos = {(p["i"], p["tipo"], p["precio"]) for p in zz}
        grados = elliott._grados(zz)
        self.assertGreater(len(grados), 1)
        for g in grados:
            self.assertLessEqual(len(g), elliott.MAX_PUNTOS)
            self.assertTrue({(p["i"], p["tipo"], p["precio"]) for p in g} <= todos)
            self.assertTrue(all(a["tipo"] != b["tipo"] for a, b in zip(g, g[1:])))
        self.assertLess(self.velas[grados[-1][0]["i"]]["date"], "2024-01-01")

    def test_fibonacci_del_impulso_entero(self):
        e = elliott.conteo(self.velas)
        f = estructura.fibonacci(self.velas, impulso=elliott.impulso_para_fibonacci(e))
        self.assertEqual(f["de"], "impulso")
        self.assertEqual((f["desde"]["precio"], f["hasta"]["precio"]), (32.89, 142.35))
        self.assertEqual((f["desde"]["fecha"], f["hasta"]["fecha"]), ("2025-11-21", "2026-06-30"))
        # Al cierre del 30/10/26 (65,76) devolvió ~70 % del impulso.
        self.assertAlmostEqual(f["retroceso_hoy"], (142.35 - 65.76) / (142.35 - 32.89), places=3)
        self.assertEqual(f["entre"], [0.618, 0.786])
        # Los niveles: la misma cuenta que el tramo (nivel r → final − r × tamaño).
        for n in f["niveles"]:
            self.assertAlmostEqual(n["precio"], 142.35 - n["nivel"] * (142.35 - 32.89), places=3)
        # La extensión es la MEDIDA de la C en curso contra la A, no un objetivo.
        x = f["extension"]
        self.assertFalse(x["terminada"])
        self.assertEqual((x["desde_b"], x["hasta"]["precio"], x["hasta"]["fecha"]), (127.44, 63.2, "2026-10-30"))
        self.assertAlmostEqual(x["veces_a"], (127.44 - 63.2) / (142.35 - 81.79), places=3)
        # El último tramo sigue ahí (lo usa el resumen de Mervall-E).
        self.assertEqual(f["tramo"]["motivo"], "superado")

    def test_sin_impulso_terminado_el_fibonacci_es_el_de_siempre(self):
        self.assertEqual(estructura.fibonacci(self.velas), estructura.fibonacci(self.velas, impulso=None))
        self.assertIsNone(elliott.impulso_para_fibonacci({"disponible": False}))
        # Un impulso en la onda 5 (sin terminar) no se mide entero.
        c = {"tipo": "impulso", "ahora": "onda_5", "dir": "suba", "ondas": []}
        self.assertIsNone(elliott.impulso_para_fibonacci({"disponible": True, "principal": c}))
        # Una fecha que no está en las velas: no se inventa, queda el tramo.
        imp = {"dir": "suba", "fechas": {"0": "1999-01-01", "5": "2026-06-30"}}
        self.assertNotIn("de", estructura.fibonacci(self.velas, impulso=imp))

    def test_el_precio_fuera_del_impulso_no_lo_mide(self):
        # Si el último cierre está fuera del impulso (0 a 1), sus niveles no
        # describen dónde está: queda el tramo de siempre.
        imp = {"dir": "suba", "fechas": {"0": "2026-03-30", "5": "2026-06-30"}}
        f = estructura.fibonacci(self.velas, impulso=imp)   # de 40,63 a 142,35: hoy 65,76 adentro
        self.assertEqual(f.get("de"), "impulso")
        imp = {"dir": "suba", "fechas": {"0": "2026-06-05", "5": "2026-06-30"}}   # de 98,33: hoy afuera
        self.assertNotIn("de", estructura.fibonacci(self.velas, impulso=imp))


class FichaConINTCTest(unittest.TestCase):
    """Por el camino de producción: el trabajo nocturno guarda las velas reales
    de INTC y la ficha las lee (GET /api/tecnico)."""

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"intc-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.yahoo = YahooDibujo(hoy_art_date())
        self.yahoo.velas["ZZIN"] = _intc()
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        r = self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "ZZIN", "quantity": 10,
                                                     "buy_price": 100, "asset_type": "STOCK"}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_la_ficha_trae_el_impulso_la_correccion_y_su_fibonacci(self):
        r = self.client.get("/api/tecnico/ZZIN", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        c = j["elliott"]["principal"]
        self.assertEqual((c["tipo"], c["ahora"]), ("impulso_y_correccion", "onda_C"))
        self.assertEqual(_ondas(c), IMPULSO + CORRECCION)
        f = j["fibonacci"]
        self.assertEqual((f["de"], f["dir"]), ("impulso", "suba"))
        # El Fibonacci mide del arranque de la onda 1 al final de la 5: las
        # MISMAS fechas y precios que el conteo (las del gráfico).
        por_onda = {o["onda"]: o for o in c["ondas"]}
        self.assertEqual(f["desde"], {"fecha": por_onda["0"]["fecha"], "precio": por_onda["0"]["precio"]})
        self.assertEqual(f["hasta"], {"fecha": por_onda["5"]["fecha"], "precio": por_onda["5"]["precio"]})
        fechas = {p["d"] for p in j["puntos"]}
        self.assertTrue(all(o["fecha"] in fechas for o in c["ondas"]))
        self.assertIsNotNone(f["extension"])

    def test_el_resumen_de_mervalle_sigue_contando_el_ultimo_tramo(self):
        # El resumen cuenta los movimientos recientes: no tiene que hablar del
        # impulso de 32,89 a 142,35 (eso lo dice la tarjeta del Fibonacci).
        j = self.client.get("/api/tecnico/ZZIN", headers=self.h).json()
        h = json.dumps(resumen_tecnico_hechos.hechos("Intel", j), ensure_ascii=False)
        self.assertNotIn("32,89", h)
        sin_impulso = {**j, "fibonacci": j["fibonacci"]["tramo"]}
        self.assertEqual(resumen_tecnico_hechos.hechos("Intel", j), resumen_tecnico_hechos.hechos("Intel", sin_impulso))


if __name__ == "__main__":
    unittest.main()
