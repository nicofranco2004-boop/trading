"""La puerta del demo: su análisis técnico con el motor de las cuentas (19/11/2026).

Antes el demo no le preguntaba nada al servidor: la ficha caía a una línea de 30
días y el Panorama, Tu lista y las Señales decían «No pudimos cargar». Ahora la
pantalla del demo manda su cuenta de ejemplo a /api/demo/… y el servidor corre lo
mismo que para una cuenta (main.py, «La puerta del demo»), con las velas de verdad
estiradas a los precios del demo (escala_del_demo.py).

Entra por el camino de producción: una cuenta de verdad (Ana) tiene y sigue los
mismos papeles, y sus velas las guarda el trabajo nocturno real con Yahoo
reemplazado en su punto más bajo (como test_tus_senales). El demo pide por HTTP,
sin sesión, lo que pide su pantalla.

Lo que se fija:
  · la ficha del demo termina en el precio del demo y dice lo mismo que la de
    una cuenta: mismo RSI, misma tendencia; los promedios, estirados igual;
  · no lee ninguna cuenta, aunque el pedido llegue con la sesión de alguien;
  · lo del demo no le llega a una cuenta ni al revés (lo ya leído se guarda
    para todos: la llave lleva el factor);
  · las señales de la semana y el resumen del sábado, con la cartera del demo;
  · el gráfico de 1 hora también termina en el precio del demo, y el de una
    cuenta no; el demo no tiene vela en vivo de hoy (sin salir a Yahoo);
  · no baja la historia de lo que nadie sigue;
  · el demo no ocupa más de DEMO_PESADOS_A_LA_VEZ lugares de entre todos, y lo
    que piden todos se calcula una vez;
  · un pedido armado a mano (demasiados precios, un precio negativo) es 422.

Corre con: cd backend && python3 -m pytest tests/test_demo_tecnico.py
"""
import os
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

from fastapi.testclient import TestClient  # noqa: E402

import escala_del_demo  # noqa: E402
import main  # noqa: E402
import tecnico  # noqa: E402
import velas_diarias  # noqa: E402
import velas_horarias  # noqa: E402
from fechas import hoy_art_date  # noqa: E402
from tests.test_radiografia_tecnica import YahooFalso, _ruedas  # noqa: E402

MEP = 1000.0
# Lo que manda la pantalla del demo (utils/demo.js, `contextoTecnicoDelDemo`).
PRECIO_NVDA = 178.5
DEMO = {
    "precios": {"NVDA": PRECIO_NVDA, "GGAL.BA": 4820.0, "MSFT": 438.2},
    "cartera": {"tenencias": [{"asset": "NVDA", "local": False, "valor": 6000.0, "tipo": "STOCK"},
                              {"asset": "GGAL", "local": True, "valor": 700.0, "tipo": "STOCK_AR"}],
                "efectivo": 1000.0, "plazos_fijos": 0.0},
    "watchlist": [{"symbol": "MSFT", "asset_type": "stock", "added_at": "2025-01-02"}],
}


class DemoTecnicoTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily", "asset_last_price", "tendencia_semanal", "resumen_semanal_prefs"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Ana', 'x', 1, 1, 'pro')", (f"demo-tecnico-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.token = main.create_token(self.uid)
        self.h = {"Authorization": f"Bearer {self.token}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        self._p = [
            mock.patch("main._check_rate_limit"),
            mock.patch("main._fetch_data912_equities", lambda: {}),
            mock.patch("main._current_cedear_rate", lambda: MEP),
            mock.patch("pricing.yahoo._historia", self.yahoo),
            mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
            mock.patch("cambios_ratio._historia_byma", lambda c: {}),
        ]
        for p in self._p:
            p.start()
        main._olvidar_lo_del_demo()
        main._freno_reiniciar()
        tecnico.olvidar_lo_leido()
        velas_horarias._ARMADAS.clear()
        self._cartera_de_ana()

    def tearDown(self):
        for p in self._p:
            p.stop()
        main._freno_reiniciar()

    def _post(self, url, body):
        r = self.client.post(url, json=body, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _cartera_de_ana(self):
        """Ana tiene NVDA y GGAL (como el demo) y además KO, que el demo no tiene;
        sigue MSFT. Sus velas las guarda la noche."""
        dias = _ruedas(self.hoy, 760)
        n = self.n = len(dias)
        self._post("/api/brokers", {"name": "IOL", "currency": "ARS"})
        self._post("/api/brokers", {"name": "Schwab", "currency": "USD"})
        for broker, asset, tipo, compra in (("Schwab", "NVDA", "STOCK", 100), ("Schwab", "KO", "STOCK", 100),
                                            ("IOL", "GGAL", "ACCION", 7000)):
            self._post("/api/positions", {"broker": broker, "asset": asset, "quantity": 10,
                                          "buy_price": compra, "asset_type": tipo})
        self._post("/api/watchlist", {"symbol": "MSFT"})
        with main.db_abierta() as conn:
            for d in dias:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), MEP * 1.1, MEP))
            conn.commit()
        # NVDA cruzó sus promedios hace 3 ruedas; MSFT, hace 2.
        self.yahoo.precios["NVDA"] = lambda i, d: 150.0 if i >= n - 3 else 100 - i * 0.01
        self.yahoo.precios["KO"] = lambda i, d: 60 + i * 0.01
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + i * 20
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0 if i >= n - 2 else 300 - i * 0.01
        main._run_velas_diarias_job()

    def _demo(self, ruta, cuerpo=None, demo=None, **kw):
        """Un pedido del demo, como lo manda utils/api.js: POST sin sesión."""
        return self.client.post("/api/demo" + ruta, json={"demo": demo or DEMO, "cuerpo": cuerpo}, **kw)

    # — la ficha —

    def test_la_ficha_termina_en_el_precio_del_demo_con_las_mismas_cuentas(self):
        r = self._demo("/tecnico/NVDA?moneda=usd")
        self.assertEqual(r.status_code, 200, r.text)
        demo = r.json()
        real = self.client.get("/api/tecnico/NVDA?moneda=usd", headers=self.h).json()
        self.assertTrue(demo["disponible"] and real["disponible"])
        self.assertEqual(real["puntos"][-1]["c"], 150.0)
        self.assertAlmostEqual(demo["puntos"][-1]["c"], PRECIO_NVDA, places=2)
        k = PRECIO_NVDA / 150.0
        # Lo que es precio, estirado; lo que es proporción, igual.
        for a, b in zip(demo["puntos"][-40:], real["puntos"][-40:]):
            self.assertEqual(a["d"], b["d"])
            self.assertAlmostEqual(a["s200"], b["s200"] * k, delta=b["s200"] * k * 1e-3)
            self.assertAlmostEqual(a["rsi"], b["rsi"], places=1)
            self.assertAlmostEqual(a["adx"], b["adx"], places=1)
        for clave in ("tendencia", "tendencia_mediano", "rsi", "adx"):
            if clave in real["lectura"]:
                self.assertEqual(demo["lectura"][clave], real["lectura"][clave], clave)
        # Sin el resumen de Mervall-E: cuesta una llamada a la IA y hablaría de
        # los precios de verdad.
        self.assertIsNone(demo["resumen"])

    def test_no_baja_la_historia_de_lo_que_nadie_sigue(self):
        with mock.patch("main._velas_a_pedido", side_effect=AssertionError("el demo bajó velas")), \
                mock.patch("velas_diarias.asegurar", side_effect=AssertionError("el demo bajó velas")):
            r = self._demo("/tecnico/ZZZZ?moneda=usd")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["disponible"])
        # «Sin serie»: la ficha del demo dibuja su gráfico de 30 días, como antes.
        self.assertEqual(r.json()["motivo"], "sin_serie")

    # — no lee ninguna cuenta —

    def test_no_lee_ninguna_cuenta_aunque_llegue_con_la_sesion(self):
        self.client.cookies.set("rendi_token", self.token)
        r = self._demo("/tecnico/lista", {"activos": [{"asset": "MSFT"}]}, headers=self.h)
        self.client.cookies.clear()
        self.assertEqual(r.status_code, 200, r.text)
        ten = {(t["asset"], t["local"]): t["peso"] for t in r.json()["tenencias"]}
        # Las del demo con sus pesos (sobre US$ 7.700), no las de Ana (que tiene KO).
        self.assertEqual(set(ten), {("NVDA", False), ("GGAL", True)})
        self.assertAlmostEqual(ten[("NVDA", False)], 6000 / 7700, places=4)
        self.assertAlmostEqual(r.json()["sin_medir"]["efectivo"], 1000 / 7700, places=4)
        self.assertIn("MSFT", {x["asset"] for x in r.json()["lecturas"]})

    def test_lo_del_demo_no_le_llega_a_una_cuenta_ni_al_reves(self):
        def ultimo(res):
            return next(x for x in res["lecturas"] if x["asset"] == "NVDA")["linea"][-1]["c"]
        cuerpo = {"activos": [{"asset": "NVDA"}]}
        demo1 = self._demo("/tecnico/lista", cuerpo).json()
        real = self.client.post("/api/tecnico/lista", json=cuerpo, headers=self.h).json()
        main._olvidar_lo_del_demo()   # que el demo vuelva a leer (lo ya leído de tecnico sigue)
        demo2 = self._demo("/tecnico/lista", cuerpo).json()
        self.assertAlmostEqual(ultimo(demo1), PRECIO_NVDA, places=2)
        self.assertEqual(ultimo(real), 150.0)
        self.assertAlmostEqual(ultimo(demo2), PRECIO_NVDA, places=2)
        # Afuera de un pedido del demo no queda nada estirado.
        self.assertFalse(escala_del_demo.en_el_demo())

    # — las señales y el resumen del sábado —

    def test_las_senales_de_la_semana_y_el_resumen_del_sabado(self):
        r = self._demo("/tus-senales")
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        por = {}
        for x in s["senales"]:
            por.setdefault(x["asset"], []).append(x)
        nvda = {x["tipo"]: x for x in por["NVDA"]}
        self.assertIn("media200", nvda)
        self.assertTrue(nvda["media200"]["tenes"])
        self.assertAlmostEqual(nvda["media200"]["peso"], 6000 / 7700, places=4)
        self.assertFalse(por["MSFT"][0]["tenes"])
        self.assertTrue(por["MSFT"][0]["watchlist"])
        self.assertEqual(s["watchlist"], 1)
        # El % de la plata en tendencia alcista: NVDA y GGAL arriba de su promedio,
        # el efectivo sin lectura. Sin «semana pasada»: no hay nada guardado.
        self.assertEqual(s["alcista"]["pct"], 87)
        self.assertIsNone(s["alcista"]["semana_pasada"])
        self.assertEqual(s["canal"], main.DEMO_CANAL)
        self.assertEqual(date.fromisoformat(s["proximo_resumen"]).weekday(), 5)   # un sábado
        # Y la radiografía de la Cartera dice el MISMO %.
        rad = self._demo("/tecnico/cartera", {"activos": [{"asset": "NVDA"}, {"asset": "GGAL", "local": True}]})
        self.assertEqual(rad.status_code, 200, rad.text)
        self.assertEqual(rad.json()["reparto"]["pct"], 87)

    # — hoy y por hora —

    def test_el_demo_no_tiene_vela_de_hoy_y_una_cuenta_si(self):
        ultimo_dia = _ruedas(self.hoy, 1)[-1].isoformat()
        tanda = {"hoy": self.hoy.isoformat(), "actualizada": 1,
                 "ruedas": [{"date": ultimo_dia, "open": 150.0, "high": 151.0, "low": 149.0, "close": 150.0,
                             "volume": 10},
                            {"date": self.hoy.isoformat(), "open": 150.0, "high": 160.0, "low": 149.0,
                             "close": 159.0, "volume": 5}]}
        pedidas = []
        with mock.patch("velas_diarias._ruedas_recientes",
                        lambda t: (pedidas.append(t), tanda if t == "NVDA" else None)[1]):
            demo = self._demo("/tecnico/NVDA/hoy?moneda=usd").json()
            self.assertEqual(pedidas, [], "el demo salió a Yahoo por la vela de hoy")
            real = self.client.get("/api/tecnico/NVDA/hoy?moneda=usd", headers=self.h).json()
        # Con ella, el gráfico del demo terminaba en el precio de verdad de hoy
        # estirado (159 × 1,19), al lado del precio del demo.
        self.assertEqual(demo["velas"], [])
        self.assertEqual(demo["ultima_guardada"], ultimo_dia)
        self.assertEqual(real["velas"][0]["c"], 159.0)

    def test_las_velas_de_una_hora_terminan_en_la_ultima_rueda_cerrada(self):
        # 300 velas de la última rueda guardada y 5 de HOY (la vela en curso).
        t0 = 1_700_000_000
        ayer = _ruedas(self.hoy, 1)[-1].isoformat()
        crudas = [(t0 + i * 3600, ayer if i < 300 else self.hoy.isoformat(), 600 + i, 150.0, 151.0, 149.0,
                   150.0 + i * 0.01, 100.0) for i in range(305)]
        ultima_cerrada = crudas[299][6]
        with mock.patch("velas_horarias.velas_1h", lambda ticker, mercado, uid=None: (crudas, t0, 1)):
            demo = self._demo("/tecnico/NVDA/horas?cada=1h&moneda=usd").json()
            real = self.client.get("/api/tecnico/NVDA/horas?cada=1h&moneda=usd", headers=self.h).json()
            # El refresco de cada minuto pide desde su última vela: no hay nada
            # nuevo ni otro factor (con la vela en curso, cada refresco estiraba
            # todo de nuevo y la pantalla mostraba un escalón).
            refresco = self._demo(f"/tecnico/NVDA/horas?cada=1h&moneda=usd&desde={demo['puntos'][-1]['t']}").json()
        self.assertTrue(demo["disponible"], demo)
        self.assertAlmostEqual(demo["puntos"][-1]["c"], PRECIO_NVDA, places=2)
        self.assertNotIn(True, [x.get("enCurso") for x in demo["puntos"]])
        self.assertEqual(demo["puntos"][-1]["t"], crudas[299][0])
        k = PRECIO_NVDA / ultima_cerrada
        a = next(x for x in real["puntos"] if x["t"] == demo["puntos"][-50]["t"])
        self.assertAlmostEqual(demo["puntos"][-50]["c"], a["c"] * k, places=2)
        # La de una cuenta sigue hasta la vela de hoy, sin estirar.
        self.assertAlmostEqual(real["puntos"][-1]["c"], crudas[-1][6], places=2)
        self.assertEqual([x["c"] for x in refresco["puntos"]], [demo["puntos"][-1]["c"]])

    # — frenos y memoria —

    def test_el_demo_no_ocupa_mas_que_sus_lugares(self):
        with main._freno_candado:
            main._freno_de_cada_uno.update({f"demo:10.0.0.{i}": 1 for i in range(main.DEMO_PESADOS_A_LA_VEZ)})
            main._freno_total[0] = main.DEMO_PESADOS_A_LA_VEZ
        try:
            r = self._demo("/tecnico/NVDA?moneda=usd")
            self.assertEqual(r.status_code, 503, r.text)
            # Una cuenta sigue teniendo lugar.
            self.assertEqual(self.client.get("/api/tecnico/NVDA?moneda=usd", headers=self.h).status_code, 200)
        finally:
            main._freno_reiniciar()

    def test_lo_que_piden_todos_se_calcula_una_vez(self):
        with mock.patch("tecnico.para_la_ficha", wraps=tecnico.para_la_ficha) as cuenta:
            a = self._demo("/tecnico/NVDA?moneda=usd").json()
            b = self._demo("/tecnico/NVDA?moneda=usd").json()
            self.assertEqual(cuenta.call_count, 1)
            otro = {**DEMO, "precios": {**DEMO["precios"], "NVDA": 200.0}}
            c = self._demo("/tecnico/NVDA?moneda=usd", demo=otro).json()
            self.assertEqual(cuenta.call_count, 2)
        self.assertEqual(a, b)
        self.assertAlmostEqual(c["puntos"][-1]["c"], 200.0, places=2)

    def test_lo_mismo_a_la_vez_no_se_calcula_dos_veces(self):
        # Mientras alguien calcula esta respuesta, el que pide lo mismo recibe
        # «en un segundo» (la pantalla lo vuelve a pedir sola), sin esperar
        # ocupando un lugar del servidor; después, lo ya calculado.
        data = main.DemoPedidoIn.model_validate({"demo": DEMO, "cuerpo": None})
        clave = main._clave_del_demo("/api/demo/tecnico/NVDA", "moneda=usd", data)
        with main._respuestas_demo_candado:
            main._DEMO_CALCULANDO.add(clave)
        r = self._demo("/tecnico/NVDA?moneda=usd")
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(r.headers.get("retry-after"), "1")
        with main._respuestas_demo_candado:
            main._DEMO_CALCULANDO.discard(clave)
        self.assertEqual(self._demo("/tecnico/NVDA?moneda=usd").status_code, 200)
        # Y si el cálculo falla, no queda trabado: el próximo lo intenta.
        self.assertEqual(main._DEMO_CALCULANDO, set())
        with mock.patch("tecnico.para_la_ficha", side_effect=RuntimeError("falló")):
            with self.assertRaises(RuntimeError):
                self._demo("/tecnico/MSFT?moneda=usd")
        self.assertEqual(main._DEMO_CALCULANDO, set())

    def test_lo_que_manda_el_visitante_no_queda_en_las_memorias_de_las_cuentas(self):
        # Los precios los elige quien pide: con cada precio distinto quedaba otra
        # entrada en lo ya leído de las cuentas y en las series por hora armadas,
        # que crecían sin tope (revisión a ciegas, 19/11).
        crudas = [(1_700_000_000 + i * 3600, _ruedas(self.hoy, 1)[-1].isoformat(), 600 + i,
                   150.0, 151.0, 149.0, 150.0, 100.0) for i in range(300)]
        cuerpo = {"activos": [{"asset": "MSFT"}]}
        self.client.post("/api/tecnico/lista", json=cuerpo, headers=self.h)
        with mock.patch("velas_horarias.velas_1h", lambda ticker, mercado, uid=None: (crudas, 1, 1)):
            self.client.get("/api/tecnico/NVDA/horas?cada=1h&moneda=usd", headers=self.h)
            leidas, armadas = len(tecnico._leidas), len(velas_horarias._ARMADAS)
            for i in range(8):
                otro = {**DEMO, "precios": {**DEMO["precios"], "NVDA": 170.0 + i, "MSFT": 400.0 + i}}
                self.assertEqual(self._demo("/tecnico/lista", cuerpo, demo=otro).status_code, 200)
                self.assertEqual(self._demo("/tecnico/NVDA/horas?cada=1h&moneda=usd", demo=otro).status_code, 200)
                main._freno_reiniciar()
        self.assertEqual(len(tecnico._leidas), leidas)
        self.assertEqual(len(velas_horarias._ARMADAS), armadas)

    def test_lo_guardado_del_demo_tiene_tope_de_bytes(self):
        # Cada ficha de prueba pesa entre 100 y 300 KB: en 1,2 MB no entran las 12.
        tope = 1_200_000
        with mock.patch.object(main, "DEMO_RESPUESTAS_BYTES", tope):
            largos = []
            for i in range(12):
                r = self._demo(f"/tecnico/NVDA?moneda=usd&x={i}")
                self.assertEqual(r.status_code, 200)
                largos.append(len(r.content))
                main._freno_reiniciar()
            self.assertGreater(sum(largos), tope, largos)          # sin tope, no entrarían todas
            self.assertLess(max(largos), tope // 4)
            self.assertLessEqual(main._RESPUESTAS_DEMO_BYTES[0], tope)
            self.assertEqual(main._RESPUESTAS_DEMO_BYTES[0], sum(len(c) for _, c in main._RESPUESTAS_DEMO.values()))
            self.assertTrue(0 < len(main._RESPUESTAS_DEMO) < 12)

    def test_lo_guardado_tambien_cuenta_en_el_freno(self):
        self.assertEqual(self._demo("/tecnico/NVDA/peso").status_code, 200)
        with mock.patch.dict(main.FRENO_TECNICO, {"uno": (3, 3)}):
            estados = [self._demo("/tecnico/NVDA/peso").status_code for _ in range(4)]
        self.assertEqual(estados[-1], 429, estados)

    def test_un_pedido_armado_a_mano_es_422(self):
        muchos = {**DEMO, "precios": {f"T{i}": 1.0 for i in range(main.DEMO_MAX_PRECIOS + 1)}}
        self.assertEqual(self._demo("/tecnico/NVDA", demo=muchos).status_code, 422)
        negativo = {**DEMO, "precios": {"NVDA": -1.0}}
        self.assertEqual(self._demo("/tecnico/NVDA", demo=negativo).status_code, 422)
        # Uno gigante daba infinitos al estirar (y un 500 que quedaba guardado).
        enorme = {**DEMO, "precios": {"NVDA": 1e308}}
        self.assertEqual(self._demo("/tecnico/NVDA", demo=enorme).status_code, 422)
        tenencias = {**DEMO, "cartera": {"tenencias": [{"asset": "NVDA", "valor": 1.0}] * (main.DEMO_MAX_TENENCIAS + 1)}}
        self.assertEqual(self._demo("/tus-senales", demo=tenencias).status_code, 422)
        self.assertEqual(self._demo("/tecnico/lista", {"activos": "NVDA"}).status_code, 422)

    # — las otras pestañas —

    def test_backtesting_comparar_y_el_diario_contestan(self):
        r = self._demo("/tecnico/NVDA/backtest?reglas=media200&anios=2")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("disponible", r.json())
        r = self._demo("/backtest/cartera/hoy")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual({a["asset"] for a in r.json()["activos"]}, {"NVDA", "GGAL"})
        r = self._demo("/backtest/cartera?activos=NVDA,MSFT&pesos=50,50&anios=2")
        self.assertEqual(r.status_code, 200, r.text)
        r = self._demo("/comparar/precio?activos=NVDA,MSFT&plazo=1a")
        self.assertEqual(r.status_code, 200, r.text)
        fecha = (self.hoy - timedelta(days=60)).isoformat()
        r = self._demo("/tecnico/en-fechas", {"items": [{"id": "1", "asset": "NVDA", "fecha": fecha}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["resultados"]["1"]["tendencia"], "bajista")
        r = self._demo("/tecnico/NVDA/peso")
        self.assertAlmostEqual(r.json()["peso"], 6000 / 7700, places=4)
        r = self._demo("/liquidez/GGAL")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("disponible", r.json())

    def test_el_termometro_cuenta_la_plata_del_demo(self):
        # Un termómetro sin sectores conocidos: toda la plata va a «sin sector»,
        # papel por papel. Son los del demo, no los de Ana (que tiene KO).
        with mock.patch("termometro.ultimo", lambda conn, hoy: {"disponible": True, "sectores": {}}):
            r = self._demo("/termometro")
        self.assertEqual(r.status_code, 200, r.text)
        papeles = set(r.json()["tu_plata"]["sin_sector"]["papeles"])
        self.assertTrue({"NVDA", "GGAL"} <= papeles, papeles)
        self.assertNotIn("KO", papeles)


class EscalaDelDemoTest(unittest.TestCase):

    def test_fuera_del_bloque_no_estira_nada(self):
        velas = [{"date": "2026-11-17", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.0, "volume": 7},
                 {"date": "2026-11-18", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 7}]
        self.assertIs(escala_del_demo.velas("NVDA", velas), velas)
        self.assertFalse(escala_del_demo.en_el_demo())
        with escala_del_demo.usando({"nvda": 3.0}):
            v = escala_del_demo.velas("NVDA", velas)
            self.assertEqual((v[1]["open"], v[1]["high"], v[1]["low"], v[1]["close"], v[1]["volume"]),
                             (2.0, 4.0, 1.0, 3.0, 7))
            self.assertEqual(v[0]["close"], 2.0)
            self.assertIs(escala_del_demo.velas("AAPL", velas), velas)    # sin precio en el demo: la de verdad
            self.assertIsNone(escala_del_demo.tanda("NVDA", {"ruedas": []}))   # sin vela de hoy
            with escala_del_demo.usando({}):
                self.assertIsNone(escala_del_demo.clave("NVDA"))
                self.assertTrue(escala_del_demo.en_el_demo())
            self.assertEqual(escala_del_demo.clave("NVDA"), 3.0)
        self.assertIsNone(escala_del_demo.clave("NVDA"))
        self.assertFalse(escala_del_demo.en_el_demo())
        self.assertEqual(velas[1]["close"], 1.5)

    def test_una_vela_sin_maximo_sigue_sin_maximo(self):
        with escala_del_demo.usando({"NVDA": 20.0}):
            t = escala_del_demo.tuplas_de_hora("NVDA", [(1, "2026-11-18", 600, None, None, None, 10.0, None)])
        self.assertEqual(t, [(1, "2026-11-18", 600, None, None, None, 20.0, None)])


if __name__ == "__main__":
    unittest.main()
