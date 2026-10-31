"""La vela de HOY del gráfico de la ficha (GET /api/tecnico/{asset}/hoy).

Entra por el camino de producción, como test_tecnico.py: las posiciones por
HTTP, las velas guardadas por el trabajo nocturno real
(`main._run_velas_diarias_job`) con Yahoo reemplazado en su punto más bajo
(`pricing.yahoo._historia`), y la vela de hoy pedida por HTTP.

Los casos que importan:
  · la vela de hoy sale de la MISMA serie que el gráfico (la acción de afuera
    de un CEDEAR en dólares; la de BYMA ÷ el MEP de una acción argentina);
  · un '.BA' con la diaria de hoy vacía se arma con las velas de 1 hora, también
    en los 20 minutos de demora después del cierre;
  · sin vela de hoy la respuesta igual dice si la rueda sigue (la pantalla no
    deja de pedir antes de la apertura);
  · un día sin guardar (la cripto entre las 21 y la noche) va junto con la de
    hoy; una serie atrasada, un split de hoy o un cambio de ratio no se dibujan;
  · el dólar: el medio con su filtro y nunca uno de hace más de una semana;
  · muchos pedidos a la vez le piden a Yahoo UNA vez;
  · la ficha y su lectura no cambian: la vela de hoy no se guarda.

Corre con: cd backend && python3 -m pytest tests/test_vela_de_hoy.py
"""
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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

import main
import velas_diarias
from fechas import hoy_art_date
from home.market import session_today


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _tabla(filas):
    idx = sorted(filas)
    o, h, l, c, v = zip(*[filas[k] for k in idx])
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                        index=pd.DatetimeIndex(idx))


def _ahora_iso(dias=0):
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat().replace("+00:00", "Z")


class YahooFalso:
    """Las ruedas cerradas: `precios[ticker]` fijo. La descarga corta de la vela
    en curso ('5d') trae, como Yahoo, sólo las últimas 5 ruedas, más la de HOY
    si hay `hoy_diaria[ticker]` (o, h, l, c, v). `hoy_horas[ticker]`:
    [(hora, (o, h, l, c, v))] para las de 1 hora. `reescrita[ticker]`: un split
    de hoy (Yahoo devuelve lo de antes dividido). `espera`: cuánto tarda."""

    def __init__(self, hoy):
        self.hoy, self.precios, self.hoy_diaria, self.hoy_horas = hoy, {}, {}, {}
        self.reescrita, self.espera, self.pedidos = {}, 0.0, []
        self._lock = threading.Lock()

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        if ticker != "^GSPC":
            with self._lock:
                self.pedidos.append((ticker, period, interval))
        if self.espera:
            time.sleep(self.espera)
        hoy = pd.Timestamp(session_today(ticker))
        if interval == "1h":
            filas = {hoy + pd.Timedelta(hours=hh): f for hh, f in self.hoy_horas.get(ticker, [])}
            return _tabla(filas) if filas else pd.DataFrame()
        c = self.precios.get(ticker) or (5000.0 if ticker == "^GSPC" else None)
        if c is None:
            return pd.DataFrame()
        if period == "5d":
            c = c / self.reescrita.get(ticker, 1.0)
        dias = _ruedas(self.hoy, {"3y": 760, "5d": 5}.get(period, 22))
        filas = {pd.Timestamp(d): (c, c * 1.01, c * 0.99, c, 1000.0) for d in dias}
        if period == "5d" and ticker in self.hoy_diaria:
            filas[hoy] = self.hoy_diaria[ticker]
        return _tabla(filas)


class VelaDeHoyTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "positions", "brokers",
                      "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"hoy-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"hoy-otro-{tag}@rendi.test",))
            self.otro = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_otro = {"Authorization": f"Bearer {main.create_token(self.otro)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        self.dolar = {"mep": {"compra": 990.0, "venta": 1010.0, "medio": 1000.0, "updated_at": _ahora_iso()}}
        self.horario = lambda mercado, now: True
        self.horarios = []
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("main._get_dolar_data", lambda: self.dolar),
                   mock.patch("alerts_engine.rueda_en_horario", self._horario),
                   # Desde las 13 de Nueva York `en_rueda` le pregunta a Yahoo (SPY)
                   # si la rueda cerró temprano: sin red, lo que diga `estado_ny`.
                   mock.patch("fuera_de_horario._pedir_yahoo",
                              lambda simbolos: [{"symbol": "SPY", "marketState": self.estado_ny}])]
        self.estado_ny = "REGULAR"
        for p in self._p:
            p.start()
        velas_diarias._en_curso.clear()
        velas_diarias._a_pedido_hechos.clear()

    def _horario(self, mercado, now):
        self.horarios.append((mercado, now))
        return self.horario(mercado, now)

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _broker(self, name, currency):
        r = self.client.post("/api/brokers", json={"name": name, "currency": currency}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _posicion(self, broker, asset, asset_type):
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type},
                             headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _mep(self, valor):
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy, 760):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), valor * 1.1, valor))
            conn.commit()

    def _hoy(self, asset, moneda="usd", local=False, h=None):
        r = self.client.get(f"/api/tecnico/{asset}/hoy?moneda={moneda}{'&local=1' if local else ''}",
                            headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _cedear_apple(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self.yahoo.precios["AAPL"] = 300.0
        self.yahoo.precios["AAPL.BA"] = 15000.0
        main._run_velas_diarias_job()

    def _galicia(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(1000.0)
        self.yahoo.precios["GGAL.BA"] = 5000.0
        main._run_velas_diarias_job()

    def _borrar_ultimas(self, ticker, n):
        with main.db_abierta() as conn:
            fechas = [r["date"] for r in conn.execute(
                "SELECT date FROM velas_diarias WHERE symbol=? ORDER BY date DESC LIMIT ?", (ticker, n))]
            for f in fechas:
                conn.execute("DELETE FROM velas_diarias WHERE symbol=? AND date=?", (ticker, f))
            conn.commit()

    def test_cedear_en_dolares_trae_la_vela_de_hoy_de_la_accion_de_afuera(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertEqual(r["velas"], [{"d": session_today("AAPL"), "o": 301.0, "h": 306.0,
                                       "l": 299.0, "c": 304.5, "v": 5_000_000.0, "hoy": True}])
        self.assertTrue(r["en_rueda"])
        self.assertEqual(r["demora_min"], 0)
        self.assertTrue(r["actualizada"])
        self.assertEqual(r["ultima_guardada"], _ruedas(self.hoy, 1)[0].isoformat())
        # La ficha no cambia: la vela de hoy no se guarda en la tabla.
        ficha = self.client.get("/api/tecnico/AAPL", headers=self.h).json()
        self.assertLess(ficha["puntos"][-1]["d"], session_today("AAPL"))
        with main.db_abierta() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM velas_diarias WHERE date >= ?",
                             (session_today("AAPL"),)).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_nueva_york_cierra_temprano_y_la_vela_de_hoy_deja_de_estar_en_rueda(self):
        # Viernes 27/11/2026 (después de Acción de Gracias) Nueva York cierra a
        # las 13:00. La vela diaria de hoy usaba el reloj sin el cierre temprano
        # (sólo lo sabían las de 1 y 4 horas): «en curso» y la pantalla pidiendo
        # cada minuto hasta las 16:00. Ahora es UNA cuenta (`en_rueda_de`).
        import fuera_de_horario
        de_verdad = next(p.temp_original for p in self._p if p.attribute == "rueda_en_horario")
        from zoneinfo import ZoneInfo
        self._cedear_apple()
        self.horario = de_verdad
        ny = ZoneInfo("America/New_York")
        a_las = lambda h, m: datetime(2026, 11, 27, h, m, tzinfo=ny).astimezone(timezone.utc)
        fuera_de_horario._vaciar_cache()
        self.estado_ny = "POST"
        self.assertFalse(velas_diarias.en_rueda("AAPL", a_las(13, 10)), "Yahoo dice que cerró")
        self.assertTrue(velas_diarias.en_rueda("AAPL", a_las(12, 45)), "antes de las 13 no se pregunta")
        with mock.patch("velas_diarias._ahora_utc", lambda: a_las(13, 10).replace(tzinfo=None)):
            self.assertFalse(self._hoy("AAPL")["en_rueda"])
            fuera_de_horario._vaciar_cache()
            self.estado_ny = "REGULAR"                   # un día normal: sigue
            self.assertTrue(self._hoy("AAPL")["en_rueda"])
        # Las velas de 1 y 4 horas usan la misma cuenta y la misma demora.
        import velas_horarias
        self.assertIs(velas_horarias.DEMORA_MIN, velas_diarias.DEMORA_MIN)
        self.assertFalse(hasattr(velas_horarias, "_ny_cerro_antes"))

    def test_cedear_en_pesos_es_el_cedear(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL.BA"] = (15000.0, 15400.0, 14900.0, 15300.0, 80_000.0)
        v = self._hoy("AAPL", "ars")["velas"][-1]
        self.assertEqual((v["o"], v["c"]), (15000.0, 15300.0))

    def test_sin_vela_todavia_dice_si_la_rueda_sigue(self):
        # Antes de la apertura (o con BYMA abierta pero sin el primer dato, que
        # llega 20 min tarde): sin velas, pero `en_rueda` viaja igual. Antes la
        # respuesta era {vela: None} y la pantalla dejaba de pedir para siempre.
        self._cedear_apple()
        r = self._hoy("AAPL")
        self.assertEqual(r["velas"], [])
        self.assertTrue(r["en_rueda"])
        self.horario = lambda m, now: False
        velas_diarias._en_curso.clear()
        self.assertFalse(self._hoy("AAPL")["en_rueda"])

    def test_muchos_pedidos_a_la_vez_son_un_pedido_a_yahoo(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        self.yahoo.espera = 0.3
        # Lo que se mide es que Yahoo reciba UN pedido, no el freno de la
        # persona (3 a la vez, test_tecnico_freno): acá se lo abre.
        with mock.patch.dict(main.FRENO_TECNICO, {"uno": (90, 20)}), \
                mock.patch("main.PESADOS_A_LA_VEZ", 40), ThreadPoolExecutor(max_workers=8) as ex:
            respuestas = list(ex.map(lambda _: self._hoy("AAPL"), range(8)))
        self.assertTrue(all(r["velas"] and r["velas"][-1]["c"] == 304.5 for r in respuestas))
        cortos = [p for p in self.yahoo.pedidos if p == ("AAPL", "5d", "1d")]
        self.assertEqual(len(cortos), 1)
        # Y dentro del minuto, otra persona: de lo guardado.
        self._hoy("AAPL", h=self.h_otro)
        self.assertEqual(len([p for p in self.yahoo.pedidos if p == ("AAPL", "5d", "1d")]), 1)

    def test_accion_argentina_con_la_diaria_vacia_se_arma_con_las_horas(self):
        self._galicia()
        nan = float("nan")
        # Lo que pasó el 04/08 con los '.BA': volumen y los cuatro precios en NaN.
        self.yahoo.hoy_diaria["GGAL.BA"] = (nan, nan, nan, nan, 2_000_000.0)
        self.yahoo.hoy_horas["GGAL.BA"] = [
            (11, (5000.0, 5100.0, 4950.0, 5050.0, 100.0)),
            (12, (5050.0, 5200.0, 5040.0, 5180.0, 200.0)),
            (13, (5180.0, 5190.0, 4900.0, 4980.0, 300.0)),
            (14, (nan, nan, nan, nan, 50.0)),            # una hora rota no cuenta
        ]
        r = self._hoy("GGAL", "ars", local=True)
        self.assertEqual(r["velas"], [{"d": session_today("GGAL.BA"), "o": 5000.0, "h": 5200.0,
                                       "l": 4900.0, "c": 4980.0, "v": 600.0, "hoy": True}])
        # BYMA llega con ~20 min de demora: se dice, y «en rueda» se mide 20 min
        # atrás (lo de 16:40 a 17 llega hasta las 17:20).
        self.assertEqual(r["demora_min"], 20)
        mercado, cuando = self.horarios[-1]
        self.assertEqual(mercado, "byma")
        atras = (datetime.now(timezone.utc) - cuando).total_seconds() / 60
        self.assertAlmostEqual(atras, 20, delta=1)
        # En dólares: el mismo papel de BYMA ÷ el MEP de HOY (el medio, como el resto).
        usd = self._hoy("GGAL", "usd", local=True)
        self.assertAlmostEqual(usd["velas"][-1]["c"], 4.98, places=6)
        self.assertAlmostEqual(usd["velas"][-1]["h"], 5.2, places=6)

    def test_el_plan_b_de_las_horas_sigue_en_los_20_minutos_despues_del_cierre(self):
        # 17:05: la rueda cerró, pero lo de 16:40 a 17 todavía llega. El plan B
        # y `en_rueda` miran el MISMO reloj (antes el plan B se apagaba a las 17).
        self._galicia()
        nan = float("nan")
        self.yahoo.hoy_diaria["GGAL.BA"] = (nan, nan, nan, nan, 1.0)
        self.yahoo.hoy_horas["GGAL.BA"] = [(11, (5000.0, 5100.0, 4950.0, 5050.0, 100.0))]
        ahora = datetime.now(timezone.utc)
        self.horario = lambda m, now: (ahora - now) > timedelta(minutes=10)   # sólo 20 min atrás
        r = self._hoy("GGAL", "ars", local=True)
        self.assertEqual(r["velas"][-1]["c"], 5050.0)
        self.assertTrue(r["en_rueda"])

    def test_sin_mep_reciente_no_se_inventa(self):
        self._galicia()
        self.yahoo.hoy_diaria["GGAL.BA"] = (5000.0, 5100.0, 4950.0, 5050.0, 100.0)
        # La caché del dólar conserva el último que llegó aunque la fuente esté
        # caída días: uno de hace 10 días no es el de hoy.
        self.dolar = {"mep": {"compra": 990.0, "venta": 1010.0, "medio": 1000.0, "updated_at": _ahora_iso(10)}}
        self.assertEqual(self._hoy("GGAL", "usd", local=True)["velas"], [])
        velas_diarias._en_curso.clear()
        self.dolar = {}
        self.assertEqual(self._hoy("GGAL", "usd", local=True)["velas"], [])
        # En pesos no hace falta dólar.
        self.assertEqual(self._hoy("GGAL", "ars", local=True)["velas"][-1]["c"], 5050.0)

    def test_el_mep_es_el_medio_con_el_filtro_de_la_historia(self):
        self._galicia()
        self.yahoo.hoy_diaria["GGAL.BA"] = (5000.0, 5100.0, 4950.0, 5050.0, 100.0)
        # Una compra 45 % abajo de la venta es un dato podrido: se usa la venta,
        # como `fx.punta_media` en la historia (el medio daría 755).
        self.dolar = {"mep": {"compra": 500.0, "venta": 1010.0, "medio": 755.0, "updated_at": _ahora_iso()}}
        self.assertAlmostEqual(self._hoy("GGAL", "usd", local=True)["velas"][-1]["c"], 5050.0 / 1010.0, places=4)

    def test_un_dia_sin_guardar_va_junto_con_el_de_hoy(self):
        # La cripto entre las 21 y la corrida de la noche: el día UTC ya es
        # «mañana» y el de «hoy» todavía no se guardó. Antes la de mañana quedaba
        # pegada a la de anteayer; ahora van las dos, en orden.
        self._cedear_apple()
        self._borrar_ultimas("AAPL", 1)
        ayer = _ruedas(self.hoy, 1)[0].isoformat()
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertEqual([(v["d"], v["hoy"]) for v in r["velas"]],
                         [(ayer, False), (session_today("AAPL"), True)])
        self.assertEqual(r["velas"][0]["c"], 300.0)

    def test_una_serie_atrasada_no_dibuja_la_de_hoy_pegada(self):
        # Lo guardado termina hace dos semanas: Yahoo sólo trae los últimos 5
        # días, no se sabe qué hay en el medio. Mejor sin vela que una pegada.
        self._cedear_apple()
        self._borrar_ultimas("AAPL", 10)
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        self.assertEqual(self._hoy("AAPL")["velas"], [])

    def test_el_dia_del_split_no_dibuja_una_caida_falsa(self):
        # Split 4 a 1 hoy: Yahoo ya devuelve lo de antes dividido por 4, y lo
        # guardado está en la escala vieja. Hasta que la noche baje todo de
        # nuevo, la vela de hoy (100) al lado de las guardadas (300) sería −67 %.
        self._cedear_apple()
        self.yahoo.reescrita["AAPL"] = 4.0
        self.yahoo.hoy_diaria["AAPL"] = (75.0, 76.0, 74.0, 75.5, 1.0)
        self.assertEqual(self._hoy("AAPL")["velas"], [])

    def test_un_cambio_de_ratio_del_cedear_no_dibuja_una_caida_falsa(self):
        # El CEDEAR pasa de 15.000 a 7.500 porque cambió el ratio (Yahoo no lo
        # corrige en la especie en pesos y la noche todavía no lo vio).
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL.BA"] = (7500.0, 7600.0, 7450.0, 7520.0, 1.0)
        self.assertEqual(self._hoy("AAPL", "ars")["velas"], [])

    def test_una_suba_grande_de_verdad_si_se_dibuja(self):
        # +40 % en un día (pasó con los papeles argentinos): no es un factor
        # redondo, es mercado.
        self._galicia()
        self.yahoo.hoy_diaria["GGAL.BA"] = (6800.0, 7100.0, 6700.0, 7000.0, 1.0)
        self.assertEqual(self._hoy("GGAL", "ars", local=True)["velas"][-1]["c"], 7000.0)

    def test_cerrada_la_rueda_se_sigue_viendo_hasta_que_se_guarda(self):
        self._cedear_apple()
        self.horario = lambda m, now: False
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertEqual(r["velas"][-1]["c"], 304.5)
        self.assertFalse(r["en_rueda"])
        self.assertNotIn(("AAPL", "5d", "1h"), self.yahoo.pedidos)

    def test_si_esa_fecha_ya_esta_guardada_no_hay_vela_doble(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                         "VALUES ('AAPL', ?, 301, 306, 299, 304.5, 1)", (session_today("AAPL"),))
            conn.commit()
        self.assertEqual(self._hoy("AAPL")["velas"], [])

    def test_vela_rota_no_se_dibuja(self):
        self._cedear_apple()
        self.horario = lambda m, now: False
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 299.0, 298.0, 304.5, 1.0)   # máximo < cierre
        self.assertEqual(self._hoy("AAPL")["velas"], [])

    def test_activo_sin_velas_no_sale_a_yahoo(self):
        self.assertEqual(self._hoy("ZZZZ")["velas"], [])
        self.assertEqual([p for p in self.yahoo.pedidos if p[0] == "ZZZZ"], [])

    def test_simbolo_invalido(self):
        r = self.client.get("/api/tecnico/<x>/hoy", headers=self.h)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
