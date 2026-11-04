"""Backtesting (backtest.py): qué habría pasado siguiendo una regla técnica.

Lo que importa:
  · Las cuentas son las del estudio del 28/10, que se verificó contra
    TradingView: con los MISMOS precios de GGAL (fixtures/backtest_ggal.csv, los
    del estudio), el RSI y el ADX + Squeeze dan las mismas operaciones y el mismo
    resultado. Los números esperados salen de correr el script del estudio
    (~/Documents/estrategia-trading-latino/scripts/comparar_reglas.py, que usa su
    `simular`), no de este código: si alguien cambia una cuenta, esto se pone rojo.
  · Las señales son las de las alertas: cada compra de «precio y media» es el día
    después de un cruce que `tecnico.ultimo_cruce` también ve.
  · La simulación: se opera a la apertura del día siguiente, con comisión de los
    dos lados; la que sigue comprada al final se cuenta al último cierre.
  · El período se corta por calendario y nunca antes de que la regla exista.
  · La ruta pasa por el freno y prueba sobre la MISMA serie que la ficha.
"""
import csv
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

import backtest
import main
import tecnico
from fechas import hoy_art_date
from tests.test_tecnico import YahooFalso, _ruedas

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "backtest_ggal.csv")


def _ggal():
    with open(FIXTURE) as f:
        return [{"date": r["date"], "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"])} for r in csv.DictReader(f)]


def _velas(cierres, aperturas=None, desde=date(2020, 1, 6)):
    """Una vela por día hábil desde `desde`, con esos cierres (y aperturas)."""
    out, d = [], desde
    for k, c in enumerate(cierres):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        o = aperturas[k] if aperturas else c
        out.append({"date": d.isoformat(), "open": o, "high": max(o, c), "low": min(o, c), "close": c})
        d += timedelta(days=1)
    return out


def _sin_senales(n):
    return {"compra": [False] * n, "venta": [False] * n, "desde": 0}


class ContraElEstudio(unittest.TestCase):
    """Diferencial contra el canónico: el estudio del 28/10 con los mismos precios."""

    @classmethod
    def setUpClass(cls):
        cls.velas = _ggal()

    def _ops(self, r):
        return [(o["compra"], round(o["precio_compra"], 2), o["venta"], round(o["precio_venta"], 2),
                 round(o["resultado"], 2), o["abierta"]) for o in r["operaciones"]]

    def test_el_periodo_es_el_del_estudio(self):
        r = backtest.probar(self.velas, "rsi", 2)
        self.assertEqual((r["desde"], r["hasta"], r["ruedas"]), ("2024-10-28", "2026-10-27", 501))
        self.assertFalse(r["recortado"])

    def test_rsi_da_lo_mismo_que_el_estudio(self):
        r = backtest.probar(self.velas, "rsi", 2)
        self.assertAlmostEqual(r["con_regla"]["resultado"], 25.50, places=2)
        self.assertAlmostEqual(r["con_regla"]["peor_caida"], -58.92, places=2)
        self.assertEqual(r["con_regla"]["ruedas_comprada"], 223)
        self.assertEqual(self._ops(r), [
            ("2025-04-10", 51.70, "2025-11-10", 57.05, 10.13, False),
            ("2026-05-05", 40.66, "2026-06-17", 54.44, 33.62, False),
            ("2026-08-24", 41.12, "2026-10-27", 35.14, -14.71, True),
        ])

    def test_adx_squeeze_da_lo_mismo_que_el_estudio(self):
        r = backtest.probar(self.velas, "adx_squeeze", 2)
        c = r["con_regla"]
        self.assertAlmostEqual(c["resultado"], 17.61, places=2)
        self.assertAlmostEqual(c["peor_caida"], -14.40, places=2)
        self.assertEqual((c["operaciones"], c["ganadoras"], c["ruedas_comprada"]), (7, 4, 110))
        self.assertEqual([o[0] for o in self._ops(r)], [
            "2025-03-05", "2025-04-23", "2025-07-22", "2026-03-03", "2026-05-12", "2026-08-31", "2026-10-08"])

    def test_mantener_da_lo_mismo_que_el_estudio(self):
        m = backtest.probar(self.velas, "rsi", 2)["mantener"]
        self.assertAlmostEqual(m["resultado"], -35.39, places=2)
        self.assertAlmostEqual(m["peor_caida"], -63.38, places=2)

    def test_la_compra_que_explica_todo(self):
        s = backtest.probar(self.velas, "rsi", 2)["con_regla"]["sin_la_mejor"]
        self.assertEqual(s["compra"], "2026-05-05")
        self.assertAlmostEqual(s["resultado"], 33.62, places=2)
        self.assertAlmostEqual(s["sin_ella"], -6.08, places=2)

    def test_lo_que_leen_las_pruebas_de_la_pantalla_es_lo_que_da_el_servidor(self):
        """frontend/src/utils/backtesting.test.js y pages/Backtesting.render.test.jsx
        ponen en palabras fixtures/backtest_ggal.json: tiene que ser la respuesta
        de ESTE código (sin la curva, que es larga), no una armada a mano."""
        import json
        with open(os.path.join(os.path.dirname(FIXTURE), "backtest_ggal.json")) as f:
            guardado = json.load(f)
        self.assertEqual(sorted(guardado), sorted(backtest.REGLAS))
        for regla in backtest.REGLAS:
            with self.subTest(regla=regla):
                r = backtest.probar(self.velas, regla, 2)
                r.pop("curva")
                self.assertEqual(json.loads(json.dumps({"asset": "GGAL", **r})), guardado[regla])

    def test_el_resultado_es_el_de_sus_operaciones(self):
        """Todo adentro o todo afuera: el resultado es el producto de las
        operaciones, y los días comprada, la suma de los de cada una."""
        for regla in backtest.REGLAS:
            with self.subTest(regla=regla):
                r = backtest.probar(self.velas, regla, 2)
                prod = math.prod(1 + o["resultado"] / 100 for o in r["operaciones"])
                self.assertAlmostEqual(r["con_regla"]["resultado"], (prod - 1) * 100, places=6)
                self.assertEqual(r["con_regla"]["ruedas_comprada"], sum(o["ruedas"] for o in r["operaciones"]))
                self.assertAlmostEqual(r["curva"][-1]["regla"], r["con_regla"]["final"], places=1)


class LasSenalesSonLasDeLasAlertas(unittest.TestCase):

    def test_cada_operacion_de_la_media_es_un_cruce_que_ve_la_alerta(self):
        velas = _ggal()
        cierres = [v["close"] for v in velas]
        m = tecnico.media(cierres, 50)
        fechas = [v["date"] for v in velas]
        r = backtest.probar(velas, "media50", 2)
        self.assertGreater(len(r["operaciones"]), 0)
        for o in r["operaciones"]:
            k = fechas.index(o["compra"]) - 1   # la señal es el cierre del día anterior
            self.assertEqual(tecnico.ultimo_cruce(cierres[:k + 1], m[:k + 1], k), (k, "arriba"), o)
            if not o["abierta"]:
                j = fechas.index(o["venta"]) - 1
                self.assertEqual(tecnico.ultimo_cruce(cierres[:j + 1], m[:j + 1], j), (j, "abajo"), o)

    def test_cruces_y_ultimo_cruce_dicen_lo_mismo(self):
        """`ultimo_cruce` (la ficha, las alertas) es el último de `cruces` (el
        backtesting): la misma cuenta, desde cualquier día."""
        rnd = random.Random(7)
        x, serie = 100.0, []
        for _ in range(400):
            x *= 1 + rnd.uniform(-0.03, 0.03)
            serie.append(x)
        m = tecnico.media(serie, 50)
        r = tecnico.rsi(serie)
        for valores, ref in ((serie, m), (r, 30.0), (r, 70.0)):
            for desde in (1, 49, 50, 51, 200, 390, 399, 400):
                todos = tecnico.cruces(valores, ref, desde)
                self.assertEqual(tecnico.ultimo_cruce(valores, ref, desde), todos[-1] if todos else None)
        self.assertGreater(len(tecnico.cruces(serie, m)), 5, "la serie de prueba cruza varias veces")

    def test_la_apertura_que_falta_es_el_cierre_anterior(self):
        velas = [{"date": "2026-01-05", "close": 10.0}, {"date": "2026-01-06", "open": None, "close": 11.0},
                 {"date": "2026-01-07", "open": 12.5, "close": 12.0}]
        self.assertEqual(tecnico.aperturas(velas), [10.0, 10.0, 12.5])


class Simulacion(unittest.TestCase):

    def test_compra_y_vende_a_la_apertura_del_dia_siguiente(self):
        cierres = [100, 101, 102, 103, 104, 105, 106, 107]
        aperturas = [99.5, 100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5]
        velas = _velas(cierres, aperturas)
        s = _sin_senales(8)
        s["compra"][2], s["venta"][5] = True, True
        sim = backtest.simular(velas, s, 0, 7, comision=0.01)
        (o,) = sim["operaciones"]
        self.assertEqual((o["compra"], o["precio_compra"]), (velas[3]["date"], 102.5))
        self.assertEqual((o["venta"], o["precio_venta"]), (velas[6]["date"], 105.5))
        self.assertAlmostEqual(o["resultado"], 105.5 * 0.99 * 0.99 / 102.5 - 1)
        self.assertEqual((o["ruedas"], sim["ruedas_comprada"]), (3, 3))
        self.assertFalse(o["abierta"])
        # Afuera la plata no se mueve; adentro sigue al cierre.
        self.assertEqual(sim["curva"][:3], [1.0, 1.0, 1.0])
        self.assertAlmostEqual(sim["curva"][3], 0.99 / 102.5 * 103)
        self.assertAlmostEqual(sim["curva"][7], 1 + o["resultado"])

    def test_la_senal_del_ultimo_dia_no_se_opera(self):
        velas = _velas([100] * 5)
        s = _sin_senales(5)
        s["compra"][4] = True
        self.assertEqual(backtest.simular(velas, s, 0, 4)["operaciones"], [])

    def test_la_que_sigue_comprada_se_cuenta_al_ultimo_cierre(self):
        velas = _velas([100, 100, 110, 120], [100, 100, 105, 118])
        s = _sin_senales(4)
        s["compra"][0] = True
        sim = backtest.simular(velas, s, 0, 3, comision=0.0)
        (o,) = sim["operaciones"]
        self.assertTrue(o["abierta"])
        self.assertEqual((o["precio_compra"], o["precio_venta"], o["venta"]), (100, 120, velas[3]["date"]))
        self.assertEqual((o["ruedas"], sim["ruedas_comprada"]), (3, 3))

    def test_mantener_paga_la_comision_de_los_dos_lados(self):
        curva = backtest.mantener(_velas([100.0] * 10), 0, 9, comision=0.001)
        self.assertAlmostEqual(curva[0], 0.999)
        self.assertAlmostEqual(curva[-1], 0.999 * 0.999)

    def test_peor_caida(self):
        self.assertAlmostEqual(backtest.peor_caida([1.0, 1.2, 0.6, 0.9, 1.3]), -0.5)
        self.assertEqual(backtest.peor_caida([1.0, 1.1, 1.2]), 0.0)

    def test_sin_la_mejor_necesita_dos(self):
        self.assertIsNone(backtest.sin_la_mejor([{"compra": "2026-01-05", "resultado": 0.3}]))
        s = backtest.sin_la_mejor([{"compra": "a", "resultado": 0.1}, {"compra": "b", "resultado": 0.5},
                                   {"compra": "c", "resultado": -0.2}])
        self.assertEqual(s["compra"], "b")
        self.assertAlmostEqual(s["sin_ella"], (1.1 * 0.8 - 1) * 100)


class Periodo(unittest.TestCase):

    def test_por_calendario_desde_la_ultima_vela(self):
        velas = _velas([100.0 + (k % 7) for k in range(900)])
        r = backtest.probar(velas, "rsi", 2)
        corte = (date.fromisoformat(velas[-1]["date"]) - timedelta(days=730)).isoformat()
        self.assertEqual(r["desde"], next(v["date"] for v in velas if v["date"] > corte))
        self.assertEqual(r["hasta"], velas[-1]["date"])
        self.assertFalse(r["recortado"])

    def test_nunca_antes_de_que_exista_la_media(self):
        """300 ruedas y 4 años pedidos: la media de 200 recién existe en la
        rueda 200; antes, la regla no puede decir nada."""
        velas = _velas([100.0 + math.sin(k / 9) * 10 for k in range(300)])
        r = backtest.probar(velas, "media200", 4)
        self.assertTrue(r["recortado"])
        self.assertEqual(r["desde"], velas[200]["date"])
        self.assertEqual(r["primera_vela"], velas[0]["date"])
        self.assertEqual(r["ruedas"], 100)

    def test_poca_historia_no_se_prueba(self):
        velas = _velas([100.0 + k for k in range(100)])
        r = backtest.probar(velas, "media50", 1)
        self.assertFalse(r["disponible"])
        self.assertEqual(r["motivo"], "poca_historia")

    def test_las_reglas_y_los_periodos_que_se_ofrecen(self):
        self.assertEqual(backtest.REGLAS, ("media200", "media50", "rsi", "adx_squeeze"))
        self.assertEqual(backtest.ANIOS, (1, 2, 3, 4))
        with self.assertRaises(ValueError):
            backtest.senales(_velas([100.0] * 10), "otra")


class Ruta(unittest.TestCase):
    """GET /api/tecnico/{asset}/backtest: la serie de la ficha, con el freno."""

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"bt-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        # Sube y baja: el RSI pasa por 30 y por 70 varias veces.
        self.yahoo.precios["AAPL"] = lambda i, d: 200 + 40 * math.sin(i / 12) + i * 0.05
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        import velas_diarias
        velas_diarias._a_pedido_hechos.clear()
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy, 760):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0, 1000.0))
            conn.commit()
        self._posicion("Schwab", "USD", "AAPL", "STOCK")
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _posicion(self, broker, moneda, asset, tipo):
        r = self.client.post("/api/brokers", json={"name": broker, "currency": moneda}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": tipo}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def test_accion_argentina_con_su_precio_de_byma(self):
        """`local=1`: la acción de BYMA ÷ el MEP de cada día, como la ficha, y no
        el ADR de Nueva York."""
        with main.db_abierta() as conn:
            conn.execute("UPDATE users SET tier='pro' WHERE id=?", (self.uid,))
            conn.commit()
        self._posicion("IOL", "ARS", "GGAL", "ACCION")
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + 800 * math.sin(i / 10)
        main._run_velas_diarias_job()
        local = self.client.get("/api/tecnico/GGAL/backtest?regla=rsi&anios=1&local=1", headers=self.h).json()
        self.assertTrue(local["disponible"], local)
        self.assertEqual((local["ticker"], local["convertida"]), ("GGAL.BA", "mep"))
        adr = self.client.get("/api/tecnico/GGAL/backtest?regla=rsi&anios=1", headers=self.h).json()
        self.assertEqual(adr["ticker"], "GGAL", "sin la marca, el ADR")
        self.assertAlmostEqual(adr["mantener"]["resultado"], (0.999 * 0.999 - 1) * 100, places=6,
                               msg="el ADR de prueba no se mueve: mantener sólo paga la comisión")

    def test_prueba_sobre_la_serie_de_la_ficha(self):
        r = self.client.get("/api/tecnico/AAPL/backtest?regla=rsi&anios=2", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()
        self.assertTrue(res["disponible"], res)
        self.assertEqual((res["asset"], res["ticker"], res["regla"], res["anios"], res["moneda"]),
                         ("AAPL", "AAPL", "rsi", 2, "usd"))
        with main.db_abierta() as conn:
            velas = tecnico.serie(conn, "AAPL", "usd")["velas"]
        esperado = backtest.probar(velas, "rsi", 2)
        self.assertAlmostEqual(res["con_regla"]["resultado"], esperado["con_regla"]["resultado"], places=6)
        self.assertEqual(len(res["operaciones"]), len(esperado["operaciones"]))
        self.assertGreater(len(res["operaciones"]), 0, "la serie de prueba tiene que dar compras")
        self.assertEqual(len(res["curva"]), res["ruedas"])

    def test_lo_que_no_se_ofrece_no_se_prueba(self):
        for q in ("regla=otra&anios=2", "regla=rsi&anios=5", "regla=rsi&anios=0"):
            with self.subTest(q=q):
                r = self.client.get(f"/api/tecnico/AAPL/backtest?{q}", headers=self.h)
                self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.client.get("/api/tecnico/<x>/backtest", headers=self.h).status_code, 400)

    def test_sin_velas_dice_por_que(self):
        res = self.client.get("/api/tecnico/ZZZZ/backtest?regla=rsi&anios=1", headers=self.h).json()
        self.assertFalse(res["disponible"])
        self.assertIn(res["motivo"], ("sin_serie", "sin_datos", "tope", "bajando"))

    def test_sin_sesion_no(self):
        self.assertEqual(self.client.get("/api/tecnico/AAPL/backtest").status_code, 401)


if __name__ == "__main__":
    unittest.main()
