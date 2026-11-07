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

# La de verdad: la suite la reemplaza en cada prueba por una que no da nada
# (conftest, `_ccl_sin_red`); acá se toma antes, para probarla a ella.
_CCL_DE_DOLARAPI = main._ccl_cerrado_de_dolarapi


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
    si hay `hoy_diaria[ticker]` (o, h, l, c, v); con `hoy_en_historia`, también
    la historia larga (la noche que ya la guarda). `cierres[ticker]`: el cierre
    de cada día (una función de la fecha), para una serie que se mueve; si no,
    `precios[ticker]` todos los días. `hoy_horas[ticker]`:
    [(hora, (o, h, l, c, v))] para las de 1 hora. `reescrita[ticker]`: un split
    de hoy (Yahoo devuelve lo de antes dividido). `espera`: cuánto tarda."""

    def __init__(self, hoy):
        self.hoy, self.precios, self.hoy_diaria, self.hoy_horas, self.cierres = hoy, {}, {}, {}, {}
        self.reescrita, self.espera, self.pedidos = {}, 0.0, []
        # La noche ya guardó la rueda de hoy (corrió con el reloj en mañana).
        self.hoy_en_historia = False
        # La fecha de la rueda de hoy, fija (si no, la de `session_today`).
        self.dia_de_hoy = {}
        self._lock = threading.Lock()

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        if ticker != "^GSPC":
            with self._lock:
                self.pedidos.append((ticker, period, interval))
        if self.espera:
            time.sleep(self.espera)
        hoy = pd.Timestamp(self.dia_de_hoy.get(ticker) or session_today(ticker))
        if interval == "1h":
            filas = {hoy + pd.Timedelta(hours=hh): f for hh, f in self.hoy_horas.get(ticker, [])}
            return _tabla(filas) if filas else pd.DataFrame()
        cierre = self.cierres.get(ticker)
        c = self.precios.get(ticker) or (5000.0 if ticker == "^GSPC" else None)
        if c is None and cierre is None:
            return pd.DataFrame()
        escala = self.reescrita.get(ticker, 1.0) if period == "5d" else 1.0
        # La historia entera (lo que pide la corrida de la noche la primera vez,
        # `PERIODO_COMPLETO`): 760 ruedas, tres años; alcanza para la media de 200.
        dias = _ruedas(self.hoy, {velas_diarias.PERIODO_COMPLETO: 760, "5d": 5}.get(period, 22))
        filas = {}
        for d in dias:
            x = (cierre(d) if cierre else c) / escala
            filas[pd.Timestamp(d)] = (x, x * 1.01, x * 0.99, x, 1000.0)
        if (period == "5d" or self.hoy_en_historia) and ticker in self.hoy_diaria:
            filas[hoy] = self.hoy_diaria[ticker]
        return _tabla(filas)


class VelaDeHoyTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "positions", "brokers",
                      "fx_rates_daily", "bond_indices_daily"):
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

    def test_cedear_estimado_en_pesos_trae_la_vela_de_hoy_en_su_escala(self):
        # Un CEDEAR que nadie sigue en pesos: la ficha lo estima con la acción de
        # afuera × el MEP ÷ 20 (tecnico.serie). La vela de hoy va en la MISMA
        # escala: sin dividir, la rueda se dibujaba 20 veces más alta que la
        # historia (la acción entera en pesos).
        self._mep(1000.0)
        self.yahoo.precios["AAPL"] = 300.0
        ficha = self.client.get("/api/tecnico/AAPL?moneda=ars", headers=self.h).json()
        self.assertEqual((ficha["ticker"], ficha["convertida"]), ("AAPL", "mep"))
        self.assertAlmostEqual(ficha["puntos"][-1]["c"], 300.0 * 1000.0 / 20, places=3)
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        v = self._hoy("AAPL", "ars")["velas"][-1]
        self.assertTrue(v["hoy"])
        self.assertEqual((v["o"], v["h"], v["l"], v["c"]), (301.0 * 50, 306.0 * 50, 299.0 * 50, 304.5 * 50),
                         "el MEP de hoy (1000) ÷ 20 = × 50")

    def test_cedear_estimado_la_vela_de_hoy_va_con_el_contado_con_liqui_de_ahora(self):
        # Con el contado con liqui de cada día guardado, el estimado es la acción ×
        # ESE dólar ÷ 20 (Nico, 06/11): la vela de hoy, con el de AHORA (el caché
        # de dolarapi, con la misma regla del medio), no con el MEP. Si el de hoy
        # ya está guardado, con el guardado, como la historia.
        self._mep(1000.0)
        dias = _ruedas(self.hoy, 760)
        with mock.patch("main._bajar_ccl", lambda: [(d.isoformat(), 1059.0, 1061.0) for d in dias]):
            main._actualizar_ccl()
        self.dolar = {"mep": {"compra": 990.0, "venta": 1010.0, "medio": 1000.0, "updated_at": _ahora_iso()},
                      "ccl": {"compra": 1079.0, "venta": 1081.0, "medio": 1080.0, "updated_at": _ahora_iso()}}
        self.yahoo.precios["AAPL"] = 300.0
        ficha = self.client.get("/api/tecnico/AAPL?moneda=ars", headers=self.h).json()
        self.assertAlmostEqual(ficha["puntos"][-1]["c"], 300.0 * 1060.0 / 20, places=3)
        self.assertEqual((ficha["ticker"], ficha["convertida"], ficha["escala"]), ("AAPL", "ccl", 20))
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        v = self._hoy("AAPL", "ars")["velas"][-1]
        self.assertTrue(v["hoy"])
        self.assertEqual((v["o"], v["c"]), (301.0 * 54, 304.5 * 54), "el contado con liqui de ahora (1080) ÷ 20")
        # El cierre de cada día lo anota el servidor de dolarapi, con la fecha del
        # DATO. Antes del cierre (`fx.HORA_CIERRE_CCL`, 18 h) no: guardado a la
        # mañana (un arranque), la vela de hoy quedaba con el dólar de esa hora y la
        # Cartera de BAC con el de ahora. La fila de HOY de argentinadatos no se usa
        # nunca: es el valor del momento. Y la corrida de la noche que termina pasada
        # la medianoche lo anota con el día del dato, no con el del reloj.
        hoy = session_today("AAPL")
        manana = (datetime.fromisoformat(hoy) + timedelta(days=1)).date().isoformat()
        for reloj, dato, guarda in ((f"{hoy} 11:00", f"{hoy}T14:00:00Z", False),
                                    (f"{hoy} 17:59", f"{hoy}T20:59:00Z", False),
                                    (f"{hoy} 18:00", f"{hoy}T21:00:00Z", True),
                                    (f"{manana} 00:05", f"{hoy}T21:00:00Z", True)):
            with main.db_abierta() as conn:
                conn.execute("DELETE FROM bond_indices_daily WHERE date = ?", (hoy,))
                conn.commit()
            dolarapi = {"compra": 1099.0, "venta": 1101.0, "medio": 1100.0, "updated_at": dato}
            with mock.patch("main._bajar_ccl", lambda: [(hoy, 1199.0, 1201.0)]), \
                    mock.patch("main._ccl_cerrado_de_dolarapi", _CCL_DE_DOLARAPI), \
                    mock.patch("main._fetch_dolar", lambda casa: dolarapi if casa == "contadoconliqui" else None), \
                    mock.patch("fechas.ahora_art", lambda: datetime.fromisoformat(reloj)):
                main._actualizar_ccl()
            v = self._hoy("AAPL", "ars")["velas"][-1]
            self.assertEqual(v["c"], 304.5 * (55 if guarda else 54),
                             f"a las {reloj}: {'el cierre de hoy (1100)' if guarda else 'el de ahora (1080)'} ÷ 20")
        # Sin contado con liqui reciente en el caché, no se inventa: sin vela de hoy.
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM bond_indices_daily WHERE date = ?", (session_today("AAPL"),))
            conn.commit()
        self.dolar = {"mep": self.dolar["mep"],
                      "ccl": {"compra": 1079.0, "venta": 1081.0, "medio": 1080.0, "updated_at": _ahora_iso(10)}}
        self.assertEqual(self._hoy("AAPL", "ars")["velas"], [])

    def test_cedear_estimado_sin_contado_con_liqui_en_el_cache_no_hay_vela_de_hoy(self):
        # dolarapi no dio el contado con liqui (el caché tiene sólo el MEP): la vela de
        # hoy de una serie armada con el contado con liqui NO se pasa con el MEP de
        # ahora (quedaría ~5 % abajo de la historia, un pozo que no existió): sin vela
        # de hoy, como cuando el de ahora es viejo. (Auditoría de las pruebas, 06/11.)
        self._mep(1000.0)
        dias = _ruedas(self.hoy, 760)
        with mock.patch("main._bajar_ccl", lambda: [(d.isoformat(), 1059.0, 1061.0) for d in dias]):
            main._actualizar_ccl()
        self.yahoo.precios["AAPL"] = 300.0
        ficha = self.client.get("/api/tecnico/AAPL?moneda=ars", headers=self.h).json()
        self.assertEqual((ficha["convertida"], ficha["escala"]), ("ccl", 20))
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        self.assertNotIn("ccl", self.dolar)
        self.assertEqual(self._hoy("AAPL", "ars")["velas"], [])

    # — BAC: su precio en pesos en la Cartera, en su mini-gráfico y en la foto de
    # la noche, con el mismo dólar que su gráfico (`main._ccl_de_las_fechas`) —

    def _cache_del_dolar(self, datos):
        """La caché del dólar del servidor, la que leen /api/prices y la foto (la
        de esta prueba, `self.dolar`, es la de `_get_dolar_data`): `datos`, o None
        = recién arrancado, antes del primer /api/dolar."""
        previo = dict(main._dolar_cache)
        self.addCleanup(lambda: (main._dolar_cache.clear(), main._dolar_cache.update(previo)))
        main._dolar_cache.update({"data": datos, "ts": time.time() if datos else 0.0})
        for c in (main._PREVCLOSE_CACHE, main._PREVCLOSE_ULTIMO, main._PREVCLOSE_RUEDA,
                  main._PREVCLOSE_VENCE, main._PRICE_CACHE, main._history_cache):
            c.clear()

    def _ccl_guardado(self, dias, compra, venta):
        with mock.patch("main._bajar_ccl", lambda: [(d.isoformat(), compra, venta) for d in dias]):
            main._actualizar_ccl()

    def test_bac_con_el_dolar_frio_no_se_mueve_si_nada_se_movio(self):
        # Recién publicado, antes del primer /api/dolar, la caché del dólar está
        # vacía: el precio de ahora de BAC caía al blue de la configuración (1.415)
        # y su cierre anterior iba con el contado con liqui guardado (1.660): la
        # Cartera decía −14,8 % en el día y el mini-gráfico caía al final, sin que se
        # moviera nada (auditoría del contado con liqui, H3 del servidor). Con la
        # caché fría, el último guardado.
        self._ccl_guardado(_ruedas(self.hoy, 40), 1659.0, 1661.0)
        self._cache_del_dolar(None)
        self.yahoo.precios["BAC"] = 50.0
        precio = self.client.get("/api/prices?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
        previo = self.client.get("/api/prices/prev-close?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
        self.assertEqual((precio, previo), (50 * 1660 / 4, 50 * 1660 / 4))
        ruedas = _ruedas(self.hoy, 21) + [self.hoy]

        class _Ticker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, period, interval, auto_adjust):
                return pd.DataFrame({"Close": [50.0] * len(ruedas)},
                                    index=pd.DatetimeIndex([pd.Timestamp(d) for d in ruedas]))
        with mock.patch("main.yf.Ticker", _Ticker):
            mini = self.client.get("/api/prices/history?symbol=BAC.BA&period=1m", headers=self.h).json()
        self.assertEqual({p["close"] for p in mini["points"]}, {50 * 1660 / 4}, "una línea chata")

    def test_bac_la_vela_de_hoy_y_la_cartera_van_con_el_mismo_contado_con_liqui(self):
        # Con la rueda abierta, la vela de hoy del gráfico de BAC y su precio en la
        # Cartera van con el contado con liqui de AHORA (1.090) y con la misma regla
        # del medio (`tecnico.dolar_de_la_cache`); no con el de ayer (1.060) ni con
        # la fila de hoy que la fuente trae a la mañana (1.070). (Auditoría del
        # contado con liqui, H4 y S3 del servidor.)
        self._mep(1000.0)
        dias = _ruedas(self.hoy, 760)
        with mock.patch("main._bajar_ccl", lambda: [(d.isoformat(), 1059.0, 1061.0) for d in dias]
                        + [(session_today("BAC"), 1069.0, 1071.0)]):
            main._actualizar_ccl()
        self.dolar = {"mep": self.dolar["mep"],
                      "ccl": {"compra": 1089.0, "venta": 1091.0, "medio": 1090.0, "updated_at": _ahora_iso()}}
        self._cache_del_dolar(self.dolar)
        self.yahoo.precios["BAC"] = 50.0
        ficha = self.client.get("/api/tecnico/BAC.BA?moneda=ars", headers=self.h).json()
        self.assertEqual((ficha["convertida"], ficha["escala"]), ("ccl", 4))
        self.yahoo.hoy_diaria["BAC"] = (50.0, 50.0, 50.0, 50.0, 5e6)       # Nueva York quieta en 50
        vela = self._hoy("BAC.BA", "ars")["velas"][-1]
        self.yahoo.hoy_en_historia = True       # la rueda de hoy también en la bajada de la Cartera
        precio = self.client.get("/api/prices?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
        self.assertEqual((vela["c"], precio), (50 * 1090 / 4, 50 * 1090 / 4))

    def test_la_foto_de_la_noche_pasa_bac_con_el_contado_con_liqui_de_su_cierre(self):
        # La foto de cada noche (`snapshots_job.fetch_prices_for_symbols`) valúa BAC
        # como la Cartera: su último cierre de Nueva York × el contado con liqui de
        # la fecha de ESE cierre ÷ 4, no el de ahora. Con la caché fría y nada
        # guardado, dolarapi directo, con la misma regla del medio que el gráfico
        # (con una compra que no tiene sentido, la venta).
        import snapshots_job
        self._ccl_guardado(_ruedas(self.hoy, 40), 1059.0, 1061.0)
        self._cache_del_dolar({"ccl": {"compra": 1089.0, "venta": 1091.0, "medio": 1090.0,
                                       "updated_at": _ahora_iso()}})
        self.yahoo.precios["BAC"] = 50.0
        self.assertEqual(snapshots_job.fetch_prices_for_symbols(["BAC.BA"], {})["BAC.BA"], 50 * 1060 / 4)
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM bond_indices_daily WHERE index_name = 'CCL'")
            conn.commit()
        self._cache_del_dolar(None)
        directo = {"compra": 950.0, "venta": 1100.0, "medio": 1025.0, "updated_at": _ahora_iso()}
        with mock.patch("main._fetch_dolar", lambda casa: directo if casa == "contadoconliqui" else None):
            self.assertEqual(snapshots_job.fetch_prices_for_symbols(["BAC.BA"], {})["BAC.BA"], 50 * 1100 / 4)
            # Y si la base falla justo ahí, dolarapi directo: no la foto de todos sin precios.
            with mock.patch("main._ccl_de_las_fechas", side_effect=RuntimeError("la base no contesta")), \
                    self.assertLogs("snapshots_job", level="WARNING"):
                self.assertEqual(snapshots_job.fetch_prices_for_symbols(["BAC.BA"], {})["BAC.BA"], 50 * 1100 / 4)

    def test_vela_de_hoy_en_la_escala_medida_de_la_serie_guardada(self):
        # MELI.BA quedó guardada (alguien la tuvo): la ficha estima con SU escala
        # (125), no con la de la tabla (120). La vela de hoy, en la MISMA. (Auditoría
        # 06/11, pruebas: con sólo AAPL a pedido, la tabla en todos lados pasaba.)
        self._mep(1000.0)
        self.yahoo.precios["MELI"] = 100.0
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy, 760)[:-14]:
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('MELI.BA', ?, ?)",
                             (d.isoformat(), 100.0 * 1000.0 / 125))
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            ficha = self.client.get("/api/tecnico/MELI.BA?moneda=ars", headers=self.h).json()
            self.assertAlmostEqual(ficha["escala"], 125.0, places=6)
            self.yahoo.hoy_diaria["MELI"] = (101.0, 102.0, 100.0, 101.5, 1000.0)
            v = self._hoy("MELI.BA", "ars")["velas"][-1]
        self.assertTrue(v["hoy"])
        self.assertAlmostEqual(v["c"], 101.5 * 1000.0 / 125, places=3)

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

    # ─── Hoy contra el cierre (el aviso abajo de la tarjeta, Nico 02/11) ──────
    # La lectura sigue con el cierre; el pedido de la vela de hoy dice qué
    # lectura da vuelta lo que la noche todavía no guardó, con el MISMO precio
    # que dibuja el gráfico: en curso (rueda abierta) o ya cerrado. Todo por
    # HTTP, con las velas guardadas por la corrida de la noche.

    def _sembrar(self, asset, tipo, ticker, broker=("IOL", "ARS"), ultimo=240.0):
        """Meses a US$ 250 y los últimos 10 días de mercado abajo de su promedio
        de 200 días (≈ 249,5): la tarjeta dice «Bajista». `ultimo`: el cierre
        del último día (para dejarlo cerrado y sin guardar)."""
        self._broker(*broker)
        self._posicion(broker[0], asset, tipo)
        ruedas = _ruedas(self.hoy, 10)
        self.yahoo.cierres[ticker] = (lambda d: ultimo if d == ruedas[-1] else 240.0 if d >= ruedas[0] else 250.0)
        if ticker == "AAPL":
            self.yahoo.precios["AAPL.BA"] = 15000.0
        main._run_velas_diarias_job()

    def _caso_nico(self):
        """El caso del 02/11: un activo en dólares a US$ 240, abajo de su
        promedio de 200 días."""
        self._sembrar("AAPL", "CEDEAR", "AAPL")
        ficha = self.client.get("/api/tecnico/AAPL", headers=self.h).json()
        self.assertEqual(ficha["lectura"]["tendencia"], "bajista")
        self.assertLess(ficha["lectura"]["dist_media50"], 0)
        return ficha

    def test_rueda_abierta_hoy_arriba_del_promedio_con_el_cierre_bajista_avisa_en_curso(self):
        ficha = self._caso_nico()
        self.yahoo.hoy_diaria["AAPL"] = (241.0, 257.0, 240.0, 256.0, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertEqual(r["velas"][-1]["c"], 256.0)         # lo que dibuja el gráfico
        self.assertEqual(r["ultima_guardada"], ficha["lectura"]["fecha"])
        self.assertEqual(r["mercado"], "us")
        por = {x["senal"]: x for x in r["contra_el_cierre"]}
        self.assertEqual(set(por), {"media200", "media50", "maximo_12m"})
        # El promedio de hoy es el de mañana si cierra así: 189 días a 250, 10 a
        # 240 y hoy a 256 → 249,53; el precio, 2,6 % arriba.
        m200_hoy = (189 * 250 + 10 * 240 + 256) / 200
        self.assertEqual(por["media200"], {"senal": "media200", "estado": "en_curso", "fecha": session_today("AAPL"),
                                           "cierre": "bajista", "pasa_a": "alcista",
                                           "dist": round((256 / m200_hoy - 1) * 100, 2)})
        self.assertEqual((por["media50"]["cierre"], por["media50"]["pasa_a"]), ("bajista", "alcista"))
        # Al cierre estaba 4 % abajo del máximo (250); hoy lo supera 2,4 %.
        self.assertEqual(por["maximo_12m"]["dist"], 2.4)
        # La lectura no cambia: sigue con el cierre.
        self.assertEqual(self.client.get("/api/tecnico/AAPL", headers=self.h).json()["lectura"], ficha["lectura"])

    def test_hoy_del_mismo_lado_no_avisa(self):
        self._caso_nico()
        self.yahoo.hoy_diaria["AAPL"] = (240.0, 242.0, 239.0, 241.0, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertEqual(r["velas"][-1]["c"], 241.0)
        self.assertEqual(r["contra_el_cierre"], [])
        self.horario = lambda m, now: False                  # ni ya cerrada
        velas_diarias._en_curso.clear()
        self.assertEqual(self._hoy("AAPL")["contra_el_cierre"], [])

    def test_pegado_al_promedio_no_avisa_por_ruido(self):
        # 250,5: 0,2 % arriba del promedio de 200 de hoy (249,95), dentro del
        # margen: no avisa (cada minuto cruzaría para un lado y para el otro).
        # El de 50 (248,01) queda 1 % abajo: ese sí. Del máximo (250), 0,2 %: no.
        # El mismo margen ya cerrada la rueda.
        self._caso_nico()
        self.yahoo.hoy_diaria["AAPL"] = (240.0, 251.0, 239.0, 250.5, 5_000_000.0)
        self.assertEqual([x["senal"] for x in self._hoy("AAPL")["contra_el_cierre"]], ["media50"])
        self.horario = lambda m, now: False
        velas_diarias._en_curso.clear()
        self.assertEqual([(x["senal"], x["estado"]) for x in self._hoy("AAPL")["contra_el_cierre"]],
                         [("media50", "cerro")])

    def test_rueda_cerrada_antes_del_guardado_avisa_que_cerro(self):
        # Después del cierre la vela de hoy se sigue dibujando hasta que la noche
        # la guarda: el aviso sigue, ahora con lo que cerró (Nico, 02/11).
        self._caso_nico()
        self.horario = lambda m, now: False
        self.yahoo.hoy_diaria["AAPL"] = (241.0, 257.0, 240.0, 256.0, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertFalse(r["en_rueda"])
        self.assertEqual(r["velas"][-1]["c"], 256.0)
        por = {x["senal"]: x for x in r["contra_el_cierre"]}
        self.assertEqual(set(por), {"media200", "media50", "maximo_12m"})
        self.assertEqual({x["estado"] for x in por.values()}, {"cerro"})
        self.assertEqual((por["media200"]["cierre"], por["media200"]["pasa_a"], por["media200"]["fecha"]),
                         ("bajista", "alcista", session_today("AAPL")))

    def test_despues_del_guardado_la_lectura_cambio_y_no_hay_aviso(self):
        # La corrida de la noche guarda la rueda de hoy (corre con el reloj ya
        # en mañana): la lectura pasa a alcista y no queda nada sin guardar.
        self._caso_nico()
        self.yahoo.hoy_diaria["AAPL"] = (241.0, 257.0, 240.0, 256.0, 5_000_000.0)
        self.horario = lambda m, now: False
        self.assertTrue(self._hoy("AAPL")["contra_el_cierre"])
        self.yahoo.hoy_en_historia = True
        manana = (self.hoy + timedelta(days=1)).isoformat()
        # La noche corre con el reloj en mañana; la rueda de hoy sigue fechada hoy.
        self.yahoo.dia_de_hoy["AAPL"] = session_today("AAPL")
        with mock.patch("fechas.hoy_art", lambda: manana):
            main._run_velas_diarias_job()
        velas_diarias._en_curso.clear()
        ficha = self.client.get("/api/tecnico/AAPL", headers=self.h).json()
        self.assertEqual((ficha["lectura"]["fecha"], ficha["lectura"]["tendencia"]),
                         (session_today("AAPL"), "alcista"))
        r = self._hoy("AAPL")
        self.assertEqual(r["velas"], [])
        self.assertEqual(r["contra_el_cierre"], [])

    def test_fin_de_semana_no_avisa(self):
        # Sábado: no hubo rueda hoy. Si el viernes quedó sin guardar (una noche
        # que falló) y cerró del otro lado, igual no se avisa: no es «hoy».
        self._sembrar("AAPL", "CEDEAR", "AAPL", ultimo=256.0)
        self._borrar_ultimas("AAPL", 1)
        self.horario = lambda m, now: False
        r = self._hoy("AAPL")
        self.assertEqual([(v["c"], v["hoy"]) for v in r["velas"]], [(256.0, False)])
        self.assertEqual(r["contra_el_cierre"], [])

    def test_bolsa_un_dia_sin_guardar_con_la_rueda_abierta_no_avisa(self):
        # Sólo un día cerrado de antes sin guardar (Yahoo todavía no trae nada
        # de hoy): no es la rueda de hoy.
        self._sembrar("AAPL", "CEDEAR", "AAPL", ultimo=256.0)
        self._borrar_ultimas("AAPL", 1)
        r = self._hoy("AAPL")
        self.assertTrue(r["en_rueda"])
        self.assertEqual(r["contra_el_cierre"], [])

    def test_cripto_antes_de_las_21_avisa_en_curso(self):
        self._sembrar("BTC", "CRYPTO", "BTC-USD", broker=("Binance", "USDT"))
        self.yahoo.hoy_diaria["BTC-USD"] = (241.0, 257.0, 240.0, 256.0, 1.0)
        r = self._hoy("BTC")
        self.assertEqual(r["mercado"], "cripto")
        por = {x["senal"]: x for x in r["contra_el_cierre"]}
        self.assertEqual((por["media200"]["estado"], por["media200"]["pasa_a"]), ("en_curso", "alcista"))

    def test_cripto_despues_de_las_21_su_dia_cerro_y_lo_dice(self):
        # Su día (UTC) cerró a las 21 arriba del promedio y la noche todavía no
        # lo guardó; el nuevo día va en curso, de vuelta abajo. Lo que vale es
        # lo que cerró: la lectura cambia con el guardado de esta noche.
        self._sembrar("BTC", "CRYPTO", "BTC-USD", broker=("Binance", "USDT"), ultimo=256.0)
        self._borrar_ultimas("BTC-USD", 1)
        self.yahoo.hoy_diaria["BTC-USD"] = (256.0, 257.0, 240.0, 241.0, 1.0)
        r = self._hoy("BTC")
        cerrado = _ruedas(self.hoy, 1)[0].isoformat()
        self.assertEqual([v["hoy"] for v in r["velas"]], [False, True])
        por = {x["senal"]: x for x in r["contra_el_cierre"]}
        self.assertEqual((por["media200"]["estado"], por["media200"]["fecha"], por["media200"]["pasa_a"]),
                         ("cerro", cerrado, "alcista"))

    def test_ya_en_su_maximo_no_avisa_del_maximo(self):
        import tecnico
        velas = [{"date": d.isoformat(), "close": 100.0 + k * 0.1} for k, d in enumerate(_ruedas(self.hoy, 300))]
        hoy = [{"d": self.hoy.isoformat(), "c": velas[-1]["close"] * 1.05, "hoy": True}]
        self.assertEqual(tecnico.hoy_contra_el_cierre(velas, hoy, True), [])
        self.assertEqual(tecnico.hoy_contra_el_cierre(velas, hoy, False), [])

    def test_simbolo_invalido(self):
        r = self.client.get("/api/tecnico/<x>/hoy", headers=self.h)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
