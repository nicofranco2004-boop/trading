"""Simular una cartera (cartera_simulada.py): US$ 100 repartidos, comprados el
primer día y sin tocar, al lado del S&P 500 y del Nasdaq.

Lo que importa:
  · La cuenta: cada activo en 100 con LA regla del comparador (`comparar.base_cien`)
    y la cartera, la suma de cada uno por su peso. Un activo solo, al 100 %, da
    exactamente su serie en 100 (diferencial contra el canónico).
  · Sin tocarla: el que sube pesa cada vez más; los aportes suman el resultado.
  · Los días son los de cualquier activo; el que no cotizó vale su último cierre.
  · Arranca cuando existe el último en llegar, y lo dice; un activo sin precios
    de la última semana no se simula; un índice que falta no frena la cartera.
  · Sin comisiones ni dividendos: un activo quieto da 0 %.
  · La ruta pasa por el freno y simula sobre LAS series de la ficha.
"""
import json
import math
import os
import random
import sys
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fastapi.testclient import TestClient

import cartera_simulada as cs
import comparar
import main
import tecnico
import velas_diarias
from fechas import hoy_art_date
from tests.test_tecnico import YahooFalso, _ruedas

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FIN = date(2026, 10, 30)


def _habiles(n: int, f, fin: date = FIN) -> list:
    """`n` ruedas de lunes a viernes que terminan en `fin`; cierre = f(i)."""
    dias, d = [], fin
    while len(dias) < n:
        if d.weekday() < 5:
            dias.append(d)
        d -= timedelta(days=1)
    dias.reverse()
    return [{"date": x.isoformat(), "open": f(i), "high": f(i) * 1.01, "low": f(i) * 0.99, "close": f(i)}
            for i, x in enumerate(dias)]


def _todos(n: int, f, fin: date = FIN) -> list:
    """`n` días corridos (una cripto: también sábados y domingos)."""
    dias = [fin - timedelta(days=n - 1 - i) for i in range(n)]
    return [{"date": x.isoformat(), "open": f(i), "high": f(i), "low": f(i), "close": f(i)} for i, x in enumerate(dias)]


def _activo(asset, peso, velas, local=False):
    return {"asset": asset, "local": local, "peso": peso, "velas": velas, "ticker": asset, "convertida": None}


def _indices(sp=None, nq=None):
    return {"sp500": sp if sp is not None else _habiles(800, lambda i: 4000 + i),
            "nasdaq": nq if nq is not None else _habiles(800, lambda i: 12000 + 5 * i)}


class Cuentas(unittest.TestCase):

    def test_dos_activos_cada_uno_por_su_peso_y_sin_tocarla(self):
        a = _habiles(800, lambda i: 100 + i * 0.25)     # sube
        b = _habiles(800, lambda i: 50.0)               # quieto
        r = cs.simular([_activo("A", 60, a), _activo("B", 40, b)], _indices(), 1)
        self.assertTrue(r["disponible"], r)
        base = next(v for v in a if v["date"] >= r["desde"])["close"]
        va = a[-1]["close"] / base * 100
        final = 60 * va / 100 + 40
        self.assertAlmostEqual(r["cartera"]["final"], final, places=2)
        self.assertAlmostEqual(r["cartera"]["resultado"], final - 100, places=2)
        x, y = r["activos"]
        self.assertAlmostEqual(x["resultado"], va - 100, places=2)
        self.assertEqual(y["resultado"], 0.0, "sin comisiones ni dividendos: un activo quieto da 0 %")
        # Sin rebalancear, el que sube pesa cada vez más; los aportes suman el resultado.
        # (La serie en 100 del comparador va con 4 decimales: `comparar.base_cien`.)
        self.assertAlmostEqual(x["peso_final"], 60 * va / final, places=4)
        self.assertGreater(x["peso_final"], 60)
        self.assertAlmostEqual(x["peso_final"] + y["peso_final"], 100, places=6)
        self.assertAlmostEqual(x["aporte"] + y["aporte"], r["cartera"]["resultado"], places=6)
        self.assertEqual(r["curva"][0]["cartera"], 100.0)

    def test_un_activo_al_cien_es_su_serie_en_cien(self):
        """Diferencial contra el canónico: la regla de «arrancar en 100» del
        comparador de precios (`comparar.base_cien`), día por día."""
        rnd = random.Random(7)
        precio, cierres = 100.0, []
        for _ in range(900):
            precio *= 1 + rnd.gauss(0, 0.02)
            cierres.append(precio)
        a = _habiles(900, lambda i: cierres[i])
        r = cs.simular([_activo("A", 100, a)], _indices(), 2)
        canonico = comparar.base_cien([(v["date"], v["close"]) for v in a], r["desde"])
        self.assertEqual([p["d"] for p in r["curva"]], [p["d"] for p in canonico])
        for p, c in zip(r["curva"], canonico):
            self.assertAlmostEqual(p["cartera"], c["v"], delta=0.006, msg=p["d"])

    def test_los_dias_son_los_de_cualquier_activo_y_el_que_no_cotizo_vale_su_ultimo_cierre(self):
        accion = _habiles(800, lambda i: 100 + i)
        cripto = _todos(1100, lambda i: 30000 + 50 * i)
        r = cs.simular([_activo("ACC", 50, accion), _activo("BTC", 50, cripto)], _indices(), 1)
        sabados = [p for p in r["curva"] if date.fromisoformat(p["d"]).weekday() == 5]
        self.assertTrue(sabados, "con una cripto en la cartera, también los fines de semana")
        sab = sabados[-1]
        viernes = (date.fromisoformat(sab["d"]) - timedelta(days=1)).isoformat()
        acc = {v["date"]: v["close"] for v in accion}
        btc = {v["date"]: v["close"] for v in cripto}
        b_acc = acc[next(d for d in sorted(acc) if d >= r["desde"])]
        b_btc = btc[r["desde"]]
        esperado = 50 * acc[viernes] / b_acc + 50 * btc[sab["d"]] / b_btc
        self.assertAlmostEqual(sab["cartera"], esperado, places=1)
        # El S&P 500 de ese sábado es el del viernes.
        vie = next(p for p in r["curva"] if p["d"] == viernes)
        self.assertEqual(sab["sp500"], vie["sp500"])

    def test_arranca_cuando_existe_el_ultimo_en_llegar_y_lo_dice(self):
        viejo = _habiles(800, lambda i: 100 + i)
        nuevo = _habiles(150, lambda i: 20 + i * 0.1)        # cotiza hace ~7 meses
        r = cs.simular([_activo("VIEJO", 50, viejo), _activo("NUEVO", 50, nuevo)], _indices(), 1)
        self.assertTrue(r["disponible"], r)
        self.assertEqual((r["recortado"], r["recorte_por"], r["desde"]), (True, "NUEVO", nuevo[0]["date"]))
        # Unos días después del pedido no es un recorte (el borde de lo guardado).
        casi = _habiles(258, lambda i: 20 + i * 0.1)
        r2 = cs.simular([_activo("VIEJO", 50, viejo), _activo("CASI", 50, casi)], _indices(), 1)
        self.assertLessEqual(comparar._dias(r2["pedido_desde"], r2["desde"]), comparar.DIAS_MARGEN)
        self.assertEqual((r2["recortado"], r2["recorte_por"]), (False, None))

    def test_un_activo_sin_precios_de_la_ultima_semana_no_se_simula(self):
        al_dia = _habiles(800, lambda i: 100 + i)
        parado = _habiles(800, lambda i: 100 + i, fin=FIN - timedelta(days=12))
        r = cs.simular([_activo("AL_DIA", 50, al_dia), _activo("PARADO", 50, parado)], _indices(), 1)
        self.assertEqual((r["disponible"], r["motivo"]), (False, "vieja"))
        self.assertEqual(r["faltan"], [{"asset": "PARADO", "motivo": "vieja", "hasta": parado[-1]["date"]}])

    def test_sin_precios_o_con_poca_historia(self):
        r = cs.simular([_activo("A", 50, _habiles(800, lambda i: 100.0)), _activo("FCI", 50, [])], _indices(), 1)
        self.assertEqual((r["disponible"], r["motivo"], r["faltan"]),
                         (False, "sin_serie", [{"asset": "FCI", "motivo": "sin_serie"}]))
        r = cs.simular([_activo("A", 50, _habiles(800, lambda i: 100.0)),
                        _activo("NUEVITO", 50, _habiles(20, lambda i: 10.0))], _indices(), 1)
        self.assertEqual((r["disponible"], r["motivo"], r["recorte_por"]), (False, "poca_historia", "NUEVITO"))

    def test_los_indices_al_lado_y_el_que_falta_no_frena_la_cartera(self):
        a = _habiles(800, lambda i: 100 + i)
        r = cs.simular([_activo("A", 100, a)], _indices(nq=[]), 2)
        self.assertTrue(r["disponible"], r)
        self.assertEqual([x["clave"] for x in r["indices"]], ["sp500"])
        self.assertEqual(r["faltan"], [{"clave": "nasdaq", "motivo": "sin_datos"}])
        self.assertEqual(set(r["curva"][0]), {"d", "cartera", "sp500"})
        sp = _indices()["sp500"]
        base = next(v for v in sp if v["date"] >= r["desde"])["close"]
        self.assertAlmostEqual(r["indices"][0]["resultado"], (sp[-1]["close"] / base - 1) * 100, places=2)
        # Un índice que dejó de actualizarse no se muestra como si fuera hoy.
        r = cs.simular([_activo("A", 100, a)], _indices(nq=_habiles(800, lambda i: 1.0, fin=FIN - timedelta(days=20))), 1)
        self.assertEqual([f["motivo"] for f in r["faltan"]], ["vieja"])

    def test_la_peor_caida_se_cuenta_desde_los_100(self):
        # Cotiza hace ~9 meses: la prueba de 1 año arranca en su primer día.
        cierres = [100, 80, 90, 120] + [120] * 196
        a = _habiles(len(cierres), lambda i: float(cierres[i]))
        r = cs.simular([_activo("A", 100, a)], _indices(), 1)
        self.assertEqual((r["desde"], r["recortado"]), (a[0]["date"], True))
        self.assertAlmostEqual(r["cartera"]["peor_caida"], -20.0, places=6)
        self.assertAlmostEqual(r["cartera"]["resultado"], 20.0, places=6)


class DeHoy(unittest.TestCase):
    """«Mi cartera de hoy»: lo que se puede simular, sobre 100 entre ellos."""

    def _car(self, tenencias):
        return {"tenencias": {(a, l): v for a, l, v, _ in tenencias},
                "tipos": {(a, l): t for a, l, _, t in tenencias}}

    def test_solo_lo_que_tiene_precio_de_todos_los_dias_y_sobre_cien(self):
        r = cs.de_hoy(self._car([("AAPL", False, 600.0, "STOCK"), ("GGAL", True, 300.0, "ACCION"),
                                 ("AL30", False, 50.0, "BOND"), ("FCI:AHORRO", False, 30.0, "FCI"),
                                 ("USDT", False, 20.0, "CRYPTO"), ("BTC", False, 100.0, "CRYPTO"),
                                 ("USD", False, 500.0, None)]))
        self.assertEqual([(a["asset"], a["local"], a["peso"]) for a in r["activos"]],
                         [("AAPL", False, 60.0), ("GGAL", True, 30.0), ("BTC", False, 10.0)])
        self.assertEqual([(x["asset"], x["motivo"]) for x in r["afuera"]],
                         [("AL30", "sin_serie"), ("FCI:AHORRO", "sin_serie"), ("USD", "sin_serie"), ("USDT", "sin_serie")])
        self.assertEqual(set(json.dumps(r)) & set("$"), set())
        self.assertNotIn("valor", json.dumps(r), "sólo porcentajes: nunca la plata")

    def test_suman_exactamente_cien_y_mas_de_diez_quedan_los_que_mas_pesan(self):
        r = cs.de_hoy(self._car([(f"T{i:02d}", False, float(20 - i), "STOCK") for i in range(12)]))
        self.assertEqual(len(r["activos"]), cs.MAX_ACTIVOS)
        self.assertAlmostEqual(sum(a["peso"] for a in r["activos"]), 100.0, places=9)
        self.assertEqual([x["asset"] for x in r["afuera"]], ["T10", "T11"])
        self.assertEqual({x["motivo"] for x in r["afuera"]}, {"tope"})
        tercios = cs.de_hoy(self._car([("A", False, 1.0, "STOCK"), ("B", False, 1.0, "STOCK"), ("C", False, 1.0, "STOCK")]))
        self.assertEqual(sorted(a["peso"] for a in tercios["activos"]), [33.3, 33.3, 33.4])

    def test_el_mismo_papel_en_byma_y_en_nueva_york_va_junto(self):
        r = cs.de_hoy(self._car([("GGAL", True, 300.0, "ACCION"), ("GGAL", False, 100.0, "STOCK"),
                                 ("AAPL", False, 400.0, "STOCK")]))
        self.assertEqual([(a["asset"], a["local"], a["peso"]) for a in r["activos"]],
                         [("AAPL", False, 50.0), ("GGAL", True, 50.0)])


def _casos_de_la_pantalla():
    """Las respuestas que leen las pruebas de la pantalla (utils/carteraSimulada.test.js,
    pages/SimularCartera.render.test.jsx), sin la curva, que es larga."""
    sube = _habiles(800, lambda i: 150 + 40 * math.sin(i / 40) + i * 0.12)
    baja = _habiles(800, lambda i: 60 - i * 0.03 + 4 * math.sin(i / 25))
    cripto = _todos(1150, lambda i: 40000 + 9000 * math.sin(i / 90) + i * 8)
    sp = _habiles(800, lambda i: 4200 + i * 1.4 + 120 * math.sin(i / 60))
    nq = _habiles(800, lambda i: 13000 + i * 6 + 500 * math.sin(i / 55))
    activos = [_activo("AAPL", 50, sube), _activo("GGAL", 30, baja, local=True), _activo("BTC", 20, cripto)]
    casos = {
        "tres": cs.simular(activos, {"sp500": sp, "nasdaq": nq}, 2),
        "sin_nasdaq": cs.simular(activos, {"sp500": sp, "nasdaq": []}, 2),
        "recortada": cs.simular(activos[:2] + [_activo("NUEVA", 20, _habiles(200, lambda i: 10 + i * 0.05))],
                                {"sp500": sp, "nasdaq": nq}, 2),
        "vieja": cs.simular(activos[:2] + [_activo("PARADA", 20, _habiles(800, lambda i: 5.0, fin=FIN - timedelta(days=30)))],
                            {"sp500": sp, "nasdaq": nq}, 2),
    }
    for r in casos.values():
        r.pop("curva", None)
    return json.loads(json.dumps(casos))


class LoQueLeeLaPantalla(unittest.TestCase):

    def test_las_pruebas_de_la_pantalla_leen_lo_que_da_el_servidor(self):
        """fixtures/cartera_simulada.json tiene que ser la salida de ESTE código, no
        una armada a mano. Para rearmarlo: CARTERA_REESCRIBIR=1."""
        ruta = os.path.join(FIXTURES, "cartera_simulada.json")
        casos = _casos_de_la_pantalla()
        if os.environ.get("CARTERA_REESCRIBIR"):
            with open(ruta, "w") as f:
                json.dump(casos, f, ensure_ascii=False, indent=1)
        with open(ruta) as f:
            self.assertEqual(json.load(f), casos)
        self.assertTrue(casos["tres"]["disponible"])
        self.assertEqual(casos["sin_nasdaq"]["faltan"], [{"clave": "nasdaq", "motivo": "sin_datos"}])
        self.assertTrue(casos["recortada"]["recortado"])
        self.assertEqual(casos["vieja"]["motivo"], "vieja")


class Ruta(unittest.TestCase):
    """GET /api/backtest/cartera: LAS series de la ficha, los índices de cada noche
    y el freno."""

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"cs-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        self.yahoo.precios["AAPL"] = lambda i, d: 200 + 40 * math.sin(i / 12) + i * 0.05
        self.yahoo.precios["MSFT"] = lambda i, d: 300 + i * 0.1
        self.yahoo.precios[velas_diarias.SP500] = lambda i, d: 4000 + i
        self.yahoo.precios[velas_diarias.NASDAQ] = lambda i, d: 12000 + 3 * i
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        velas_diarias._a_pedido_hechos.clear()
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy, 760):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0, 1000.0))
            conn.commit()
        self._posicion("Schwab", "USD", "AAPL", "STOCK")
        self._posicion("Schwab", "USD", "MSFT", "STOCK")
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _posicion(self, broker, moneda, asset, tipo):
        r = self.client.post("/api/brokers", json={"name": broker, "currency": moneda}, headers=self.h)
        self.assertIn(r.status_code, (200, 400), r.text)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": tipo}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _get(self, q):
        return self.client.get(f"/api/backtest/cartera?{q}", headers=self.h)

    def test_simula_sobre_las_series_de_la_ficha_y_los_indices_de_cada_noche(self):
        r = self._get("activos=AAPL,MSFT&pesos=60,40&anios=2")
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()
        self.assertTrue(res["disponible"], res)
        with main.db_abierta() as conn:
            esperado = cs.simular(
                [{"asset": s, "local": False, "peso": p, "velas": tecnico.serie(conn, s, "usd")["velas"],
                  "ticker": s, "convertida": None} for s, p in (("AAPL", 60.0), ("MSFT", 40.0))],
                {c: tecnico.indice(conn, t) for c, _, t in cs.INDICES}, 2)
        self.assertEqual(res, json.loads(json.dumps(esperado)))
        self.assertEqual([x["clave"] for x in res["indices"]], ["sp500", "nasdaq"])
        self.assertEqual(res["faltan"], [])

    def test_accion_argentina_con_su_precio_de_byma(self):
        self._posicion("IOL", "ARS", "GGAL", "ACCION")
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + 800 * math.sin(i / 10)
        main._run_velas_diarias_job()
        res = self._get("activos=GGAL,AAPL&pesos=50,50&local=GGAL&anios=1").json()
        self.assertTrue(res["disponible"], res)
        ggal = res["activos"][0]
        self.assertEqual((ggal["asset"], ggal["local"], ggal["ticker"], ggal["convertida"]),
                         ("GGAL", True, "GGAL.BA", "mep"))

    def test_mi_cartera_de_hoy_sale_de_tu_plata_sin_mostrarla(self):
        r = self.client.get("/api/backtest/cartera/hoy", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()
        self.assertEqual(sorted(a["asset"] for a in res["activos"]), ["AAPL", "MSFT"])
        self.assertAlmostEqual(sum(a["peso"] for a in res["activos"]), 100.0, places=9)
        self.assertEqual(res["afuera"], [])
        self.assertEqual(set(res), {"activos", "afuera"})
        self.assertEqual({k for a in res["activos"] for k in a}, {"asset", "local", "peso", "tipo"})
        # Y lo que arma se puede simular tal cual.
        q = (f"activos={','.join(a['asset'] for a in res['activos'])}"
             f"&pesos={','.join(str(a['peso']) for a in res['activos'])}&anios=1")
        self.assertTrue(self._get(q).json()["disponible"])

    def test_lo_que_no_se_puede_simular_dice_por_que(self):
        res = self._get("activos=AAPL,ZZZZ&pesos=50,50&anios=1").json()
        self.assertEqual((res["disponible"], res["motivo"]), (False, "sin_serie"))
        self.assertEqual(res["faltan"], [{"asset": "ZZZZ", "motivo": "sin_serie"}])

    def test_lo_que_no_se_ofrece_da_400(self):
        for q in ("activos=&pesos=", "activos=AAPL&pesos=60", "activos=AAPL,AAPL&pesos=50,50",
                  "activos=AAPL,MSFT&pesos=50", "activos=AAPL,MSFT&pesos=70,40", "activos=AAPL,MSFT&pesos=0,100",
                  "activos=AAPL,MSFT&pesos=50,x", "activos=AAPL&pesos=100&anios=5", "activos=AAPL&pesos=100&anios=0",
                  "activos=A%20B&pesos=100", "activos=AAPL&pesos=100&local=A%20B",
                  "activos=" + ",".join(f"T{i}" for i in range(cs.MAX_ACTIVOS + 1))
                  + "&pesos=" + ",".join(["10"] * (cs.MAX_ACTIVOS + 1))):
            with self.subTest(q=q):
                self.assertEqual(self._get(q).status_code, 400)
        # Decimales que suman 100 sí.
        self.assertEqual(self._get("activos=AAPL,MSFT&pesos=33.33,66.67&anios=1").status_code, 200)


if __name__ == "__main__":
    unittest.main()
