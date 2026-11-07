"""BAC se valúa y se dibuja con su CEDEAR en pesos de la Bolsa: «BA.C» (Nico, 06/11/2026).

El CEDEAR de Bank of America en pesos cotiza en BYMA con otro código, 'BA.C'. El
'BAC' de data912 es otro papel, en dólares (7,29 el 06/11/2026), y el 'BAC.BA' de
Yahoo es ese mismo. Hasta acá Rendi lo ESTIMABA (Nueva York × contado con liqui ÷
4) en las cinco cuentas de BAC: el precio de ahora, el cierre anterior, la foto de
la noche, el mini-gráfico y el gráfico de la ficha. Ahora las cinco leen BA.C
(`snapshots_job.codigo_en_byma`); el estimado queda de respaldo si la Bolsa no lo
tiene, y para las velas de 1 y 4 horas, que de BA.C no existen en ninguna fuente
(audit/_scripts/medir_ba_c.out). De paso, la liquidez de la ficha dejó de medir el
otro papel (con el precio de Boeing).

Todo entra por HTTP o por los trabajos de la noche, con la red reemplazada en su
punto más bajo: `requests.get` para data912 (el precio en vivo y la historia de
cada rueda) y `pricing.yahoo._historia` (y `yf.Ticker`, el del mini-gráfico) para
Yahoo.

En el mundo de la prueba BA.C está 2 % ARRIBA del estimado, como en 2023, cuando
el contado con liqui de los bonos se separó del dólar de los CEDEARs: cada número
dice de cuál de los dos salió.

Corre con: cd backend && python3 -m pytest tests/test_bac_con_ba_c.py
"""
import os
import sys
import tempfile
import unittest
import uuid
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
import liquidez
import velas_diarias
import velas_horarias
from fechas import hoy_art, hoy_art_date

N = 760            # las ruedas de la historia (~3 años)
RATIO = 4          # CEDEARs de BAC por acción (la tabla de ratios)
CCL_AHORA = 1985.0
MEP = 1450.0


def ny(i):
    """Bank of America en Nueva York, la rueda i (0 = la más vieja)."""
    return 50.0 + i * 0.01


def ccl(i):
    """El contado con liqui de la rueda i (el medio)."""
    return 1600.0 + i * 0.5


def estimado(i):
    return ny(i) * ccl(i) / RATIO


def ba_c(i):
    """El CEDEAR en pesos de la Bolsa: 2 % arriba del estimado."""
    return round(estimado(i) * 1.02, 2)


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _tabla(filas: dict) -> pd.DataFrame:
    idx = sorted(filas)
    o, h, l, c, v = zip(*[filas[k] for k in idx])
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                        index=pd.DatetimeIndex(idx))


class _Resp:
    def __init__(self, cuerpo, status=200):
        self._cuerpo, self.status_code = cuerpo, status

    def json(self):
        return self._cuerpo


class Mundo:
    """data912 y Yahoo de mentira, con la forma de sus respuestas."""

    def __init__(self, hoy):
        self.hoy = hoy
        self.dias = _ruedas(hoy, N)
        # BA.C ahora: 1 % abajo de su cierre de ayer (el feed manda el −1 %).
        self.c_hoy = round(ba_c(N - 1) * 0.99, 2)
        self.ba_c_en_el_feed = True
        # BA.C aparece en el feed recién desde este pedido de 'arg_cedears' (1 = siempre):
        # el feed que se renueva en el medio de un pedido.
        self.ba_c_desde_el_pedido = 1
        self.pedidos_cedears = 0
        self.historia_no_contesta = False
        self.rueda_de_hoy = None      # (o, h, l, c, v) de BA.C hoy en la historia de data912
        self.pedidos_yahoo = []       # (ticker, period, interval)
        self.yahoo_sin = set()        # los que Yahoo devuelve vacíos
        self.msft_hasta_hoy = False   # Yahoo trae MSFT con la rueda de hoy (BAC no)
        self.bac_ba_entera = False    # el 'BAC.BA' de Yahoo (el otro papel) con un mes de ruedas
        self.splits_pedidos = []      # a qué tickers se les preguntaron los splits

    # — data912 —

    def get(self, url, *a, **k):
        if "data912.com/live/" in url:
            endpoint = url.rsplit("/", 1)[1]
            if endpoint == "arg_cedears":
                self.pedidos_cedears += 1
            return _Resp(self.feed().get(endpoint, []))
        if "data912.com/historical/" in url:
            if self.historia_no_contesta:
                return _Resp({"detail": "caído"}, 503)
            tipo, papel = url.split("/historical/", 1)[1].split("/", 1)
            return _Resp(self.historia(tipo, papel))
        return _Resp([], 404)        # dolarapi, ArgentinaDatos y lo demás: no hay

    def feed(self):
        cedears = [
            # El 'BAC' del feed: OTRO papel, en dólares y casi sin operar.
            {"symbol": "BAC", "c": 7.29, "pct_change": 3.25, "v": 62.0, "q_op": 1.0,
             "px_bid": 6.82, "px_ask": 7.46},
            # Boeing: la ficha vieja tomaba su precio como «especie base» de 'BAC'.
            {"symbol": "BA", "c": 12050.0, "pct_change": 3.52, "v": 2983.0, "q_op": 40.0,
             "px_bid": 12000.0, "px_ask": 12100.0},
            {"symbol": "SPY", "c": 20540.0, "pct_change": -0.14, "v": 448937.0, "q_op": 9284.0,
             "px_bid": 20420.0, "px_ask": 20540.0},
        ]
        if self.ba_c_en_el_feed and self.pedidos_cedears >= self.ba_c_desde_el_pedido:
            cedears.append({"symbol": "BA.C", "c": self.c_hoy, "pct_change": -1.0, "v": 1889.0,
                            "q_op": 90.0, "px_bid": round(self.c_hoy * 0.997, 2),
                            "px_ask": round(self.c_hoy * 1.003, 2)})
        return {"arg_cedears": cedears, "arg_stocks": [], "arg_bonds": [], "arg_notes": [], "arg_corp": []}

    def historia(self, tipo, papel):
        if (tipo, papel) == ("cedears", "BA.C"):
            filas = [{"date": d.isoformat(), "o": round(ba_c(i) * 0.995, 2), "h": round(ba_c(i) * 1.01, 2),
                      "l": round(ba_c(i) * 0.99, 2), "c": ba_c(i), "v": 4000.0, "dr": 0.0, "sa": 0.25}
                     for i, d in enumerate(self.dias)]
            if self.rueda_de_hoy:
                o, h, l, c, v = self.rueda_de_hoy
                filas.append({"date": self.hoy.isoformat(), "o": o, "h": h, "l": l, "c": c, "v": v})
            return filas
        if (tipo, papel) == ("stocks", "GGAL"):
            # La referencia con que la liquidez cuenta las ruedas de BYMA.
            return [{"date": d.isoformat(), "c": 6000.0, "v": 1e6} for d in self.dias]
        return {"Error": "Nahh no tengo ese ticker loko"}

    # — Yahoo —

    def yahoo(self, ticker, period, interval, auto_adjust, timeout):
        if ticker not in velas_diarias.INDICES:
            self.pedidos_yahoo.append((ticker, period, interval))
        if ticker in self.yahoo_sin:
            return pd.DataFrame()
        if ticker == "BAC.BA":
            # El de Yahoo es el otro papel, en dólares: una sola rueda (o un mes).
            dias = self.dias[-22:] if self.bac_ba_entera else [self.hoy]
            return _tabla({pd.Timestamp(d): (7.29, 7.29, 7.29, 7.29, 62.0) for d in dias})
        if interval != "1d":
            return self.horas_ny() if ticker == "BAC" else pd.DataFrame()
        if ticker in velas_diarias.INDICES:
            precio = lambda i: 5000.0          # noqa: E731
        elif ticker == "BAC":
            precio = ny
        elif ticker == "MSFT":
            precio = lambda i: 500.0           # noqa: E731
        else:
            return pd.DataFrame()
        dias = self.dias if period == velas_diarias.PERIODO_COMPLETO else self.dias[-22:]
        filas = {pd.Timestamp(d): (precio(self.dias.index(d)),) * 4 + (1_000_000.0,) for d in dias}
        if ticker == "MSFT" and self.msft_hasta_hoy:
            filas[pd.Timestamp(self.hoy)] = (501.0, 501.0, 501.0, 501.0, 1_000_000.0)
        return _tabla(filas)

    def splits(self, ticker):
        """`cambios_ratio._splits_de_yahoo`: ninguno, pero anotado."""
        self.splits_pedidos.append(ticker)
        return []

    def horas_ny(self):
        """Las de 1 hora de las últimas 3 ruedas de Nueva York, alrededor del cierre."""
        filas = {}
        for d in self.dias[-3:]:
            c = ny(self.dias.index(d))
            for hh in range(10, 16):
                t = pd.Timestamp(datetime(d.year, d.month, d.day, hh, 30)).tz_localize("America/New_York")
                filas[t] = (c, c * 1.002, c * 0.998, c, 1000.0)
        return _tabla(filas)

    def ticker(self, sym):
        """`yf.Ticker`, el que usa el mini-gráfico."""
        mundo = self

        class _Ticker:
            def history(self, period="1mo", interval="1d", auto_adjust=True, **k):
                return mundo.yahoo(sym, period, interval, auto_adjust, None)
        return _Ticker()

    def le_pidieron_a_yahoo(self, ticker):
        return [p for p in self.pedidos_yahoo if p[0] == ticker]


def _ahora_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BacConBaCTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "bond_indices_daily", "snapshots"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"bac-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.mundo = Mundo(hoy_art_date())
        self.dias = self.mundo.dias
        dolar = {"ccl": {"compra": CCL_AHORA - 5, "venta": CCL_AHORA + 5, "medio": CCL_AHORA,
                         "updated_at": _ahora_iso()},
                 "mep": {"compra": MEP - 5, "venta": MEP + 5, "medio": MEP, "updated_at": _ahora_iso()}}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("requests.get", side_effect=self.mundo.get),
                   mock.patch("pricing.yahoo._historia", self.mundo.yahoo),
                   mock.patch("main.yf.Ticker", self.mundo.ticker),
                   mock.patch("cambios_ratio._splits_de_yahoo", self.mundo.splits),
                   mock.patch.dict(main._dolar_cache, {"data": dolar, "ts": 9e18}),
                   # Lo que el servidor tiene en memoria de la Bolsa: lo que trajo el feed.
                   mock.patch("main._data912_en_memoria", lambda: main._fetch_data912_equities() or {})]
        for p in self._p:
            p.start()
        self._vaciar_memorias()
        # El contado con liqui de cada día, guardado como lo guarda la app.
        with mock.patch("main._bajar_ccl",
                        lambda: [(d.isoformat(), ccl(i) - 5, ccl(i) + 5) for i, d in enumerate(self.dias)]):
            main._actualizar_ccl()
        with main.db_abierta() as conn:
            for d in self.dias:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), MEP * 1.1, MEP))
            conn.commit()

    def tearDown(self):
        for p in self._p:
            p.stop()
        self._vaciar_memorias()

    def _vaciar_memorias(self):
        main._data912_eq_cache.update({"data": None, "ts": 0})
        for c in (main._PRICE_CACHE, main._PREVCLOSE_CACHE, main._PREVCLOSE_RUEDA,
                  main._PREVCLOSE_ULTIMO, main._history_cache, liquidez._cache,
                  velas_diarias._en_curso, velas_diarias._a_pedido_hechos,
                  velas_horarias._CACHE, velas_horarias._ARMADAS, velas_horarias._FALLAS,
                  velas_horarias._NUEVOS):
            c.clear()

    # — por HTTP, como la pantalla —

    def _tener_bac(self):
        r = self.client.post("/api/brokers", json={"name": "IOL", "currency": "ARS"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "IOL", "asset": "BAC", "quantity": 10,
                                                     "buy_price": 20000, "asset_type": "CEDEAR"},
                             headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _cartera(self):
        """El precio de ahora, el cierre anterior y la variación del día de BAC.BA."""
        self._vaciar_memorias()
        precio = self.client.get("/api/prices?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
        anterior = self.client.get("/api/prices/prev-close?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
        variacion = main._variacion_del_dia(["BAC.BA"], self.uid)["BAC.BA"]
        return precio, anterior, variacion

    def _ficha(self, asset, moneda):
        r = self.client.get(f"/api/tecnico/{asset}?moneda={moneda}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _mini(self, period):
        main._history_cache.clear()
        r = self.client.get(f"/api/prices/history?symbol=BAC.BA&period={period}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["points"]

    # — las cinco cuentas —

    def test_la_cartera_valua_bac_con_su_cedear_de_la_bolsa(self):
        # Antes: Nueva York × el contado con liqui de ahora ÷ 4, y el cierre
        # anterior, el de Nueva York de ayer × el contado con liqui de ayer ÷ 4.
        precio, anterior, variacion = self._cartera()
        self.assertEqual(precio, self.mundo.c_hoy)
        self.assertAlmostEqual(anterior, ba_c(N - 1), delta=0.01)
        self.assertEqual(variacion["price"], self.mundo.c_hoy)
        self.assertAlmostEqual(variacion["prev_close"], ba_c(N - 1), delta=0.01)
        self.assertAlmostEqual(variacion["change_pct"], -1.0, places=2)
        self.assertEqual(variacion["mercado"], "byma", "la rueda que la mide es la de la Bolsa")

    def test_si_el_feed_se_renueva_en_el_medio_ba_c_no_pasa_por_la_cuenta_del_estimado(self):
        # El feed de la Bolsa vive unos minutos en memoria. Si vence en el medio de
        # un pedido —sin BA.C al principio, con BA.C cuando se reintenta lo que
        # Yahoo no trajo—, ese precio ya está en pesos: pasarlo por el contado con
        # liqui ÷ 4 lo multiplicaba ~500 veces.
        self.mundo.ba_c_desde_el_pedido = 2
        self.mundo.yahoo_sin = {"BAC"}
        with mock.patch("main.DATA912_TTL", 0):
            precio, _, _ = self._cartera()
        self.assertEqual(precio, self.mundo.c_hoy)

    def test_el_estimado_del_cierre_anterior_no_mezcla_el_precio_de_la_bolsa(self):
        # Lo mismo en el cierre anterior: BAC va por su estimado (sin BA.C en el
        # feed) y su vela de Nueva York quedó una rueda atrás de otra del mismo
        # pedido (MSFT ya tiene la de hoy). Si en ese momento el feed ya trae BA.C,
        # el último precio del estimado no puede ser el de la Bolsa (ya en pesos)
        # pasado otra vez a pesos.
        self.mundo.ba_c_desde_el_pedido = 2
        self.mundo.msft_hasta_hoy = True
        self._vaciar_memorias()
        with mock.patch("main.DATA912_TTL", 0):
            v = main._variacion_del_dia(["BAC.BA", "MSFT"], self.uid)["BAC.BA"]
        self.assertAlmostEqual(v["price"], estimado(N - 1), places=2)
        self.assertAlmostEqual(v["prev_close"], estimado(N - 2), places=2)

    def test_sin_ba_c_en_la_bolsa_bac_vuelve_al_estimado(self):
        # El respaldo: el feed no trae BA.C (sí el otro 'BAC', en dólares, que no
        # se usa). Precio = Nueva York × contado con liqui de ahora ÷ 4; cierre
        # anterior = el de Nueva York de su día × el contado con liqui de ese día.
        self.mundo.ba_c_en_el_feed = False
        precio, anterior, _ = self._cartera()
        self.assertAlmostEqual(precio, ny(N - 1) * CCL_AHORA / RATIO, places=2)
        self.assertAlmostEqual(anterior, estimado(N - 2), places=2)

    def test_la_foto_de_la_noche_valua_bac_con_ba_c(self):
        # La foto de cada noche (`snapshots_job.fetch_prices_for_symbols`) por la
        # puerta real: el mismo trabajo que dispara el reloj. Valúa al dólar MEP.
        self._tener_bac()
        with mock.patch.object(main, "_get_blue_for_scheduler", lambda: MEP * 1.1), \
                mock.patch.object(main, "_get_mep_for_scheduler", lambda: MEP), \
                mock.patch.object(main, "_run_velas_diarias_job", lambda: None):
            main._run_daily_snapshot_job()
        with main.db_abierta() as conn:
            foto = conn.execute("SELECT total_value FROM snapshots WHERE user_id=? AND date=?",
                                (self.uid, hoy_art())).fetchone()
        self.assertIsNotNone(foto, "la foto de la noche no se guardó")
        self.assertAlmostEqual(float(foto["total_value"]), 10 * self.mundo.c_hoy / MEP, places=2)

    def test_la_noche_guarda_ba_c_y_la_ficha_en_pesos_lo_dibuja(self):
        self._tener_bac()
        # Un split que Yahoo anotó alguna vez en SU 'BAC.BA' (el otro papel), guardado:
        # no es del CEDEAR, y no puede volverse un «cambio de ratio» de BAC.
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO splits_yahoo (ticker, splits, consultado) VALUES (?, ?, datetime('now'))",
                         ("BAC.BA", f'[["{self.dias[-100].isoformat()}", 2.0]]'))
            conn.commit()
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            guardada = velas_diarias.serie(conn, "BAC.BA")
            cambios = conn.execute("SELECT COUNT(*) FROM cambios_ratio WHERE cedear='BAC'").fetchone()[0]
        self.assertEqual(len(guardada), N, "la historia de la Bolsa entera (sin la rueda de hoy)")
        self.assertEqual((guardada[0]["date"], guardada[0]["close"]), (self.dias[0].isoformat(), ba_c(0)))
        self.assertEqual((guardada[-1]["date"], guardada[-1]["close"]), (self.dias[-1].isoformat(), ba_c(N - 1)))
        self.assertEqual(self.mundo.le_pidieron_a_yahoo("BAC.BA"), [], "a Yahoo nunca: es otro papel")
        self.assertEqual(cambios, 0, "BA.C nunca cambió de ratio")
        # La lista de cambios de ratio le pregunta los splits a la acción de
        # afuera, nunca a los '.BA' de Yahoo, que son otro papel.
        self.assertIn("BAC", self.mundo.splits_pedidos)
        self.assertEqual([t for t in self.mundo.splits_pedidos if t in ("BAC.BA", "BACD.BA")], [])

        ars = self._ficha("BAC", "ars")
        self.assertEqual((ars["ticker"], ars["convertida"], ars.get("escala")), ("BAC.BA", None, None))
        vela = {p["d"]: p["c"] for p in ars["puntos"]}
        self.assertAlmostEqual(vela[self.dias[-1].isoformat()], ba_c(N - 1), places=2)
        self.assertAlmostEqual(vela[self.dias[-200].isoformat()], ba_c(N - 200), places=2)
        # El cierre anterior de la Cartera es la última vela del gráfico.
        _, anterior, _ = self._cartera()
        self.assertAlmostEqual(anterior, vela[self.dias[-1].isoformat()], delta=0.01)
        # En dólares no cambia nada: la acción de Nueva York.
        usd = self._ficha("BAC", "usd")
        self.assertEqual((usd["ticker"], usd["convertida"]), ("BAC", None))
        self.assertAlmostEqual(usd["puntos"][-1]["c"], ny(N - 1), places=4)

    def test_sin_la_serie_de_la_bolsa_el_grafico_en_pesos_es_el_estimado(self):
        # data912 no contestó la noche: no hay 'BAC.BA' guardada y el gráfico en
        # pesos es el estimado (Nueva York × contado con liqui de cada día ÷ 4).
        self._tener_bac()
        self.mundo.historia_no_contesta = True
        main._run_velas_diarias_job()
        ars = self._ficha("BAC", "ars")
        self.assertEqual((ars["ticker"], ars["convertida"], ars["escala"]), ("BAC", "ccl", RATIO))
        self.assertAlmostEqual(ars["puntos"][-1]["c"], estimado(N - 1), places=2)
        self.assertEqual(self.mundo.le_pidieron_a_yahoo("BAC.BA"), [])

    def test_si_ba_c_dice_otro_ratio_el_estimado_no_se_dibuja(self):
        # El respaldo se controla con el precio de verdad: sin la serie de la Bolsa
        # guardada, el estimado (÷ 4, la tabla) se compara con BA.C en vivo. Si BA.C
        # cotiza a la mitad (Comafi pasó a 8 por acción y la tabla quedó vieja), la
        # escala no cierra y en pesos no hay gráfico: mejor nada que uno el doble
        # de alto. Antes, el precio de BAC en la Bolsa era el del otro papel y no
        # se miraba.
        self._tener_bac()
        self.mundo.historia_no_contesta = True
        self.mundo.c_hoy = round(ba_c(N - 1) / 2, 2)
        main._run_velas_diarias_job()
        main._fetch_data912_equities()         # lo que el servidor tiene en memoria de la Bolsa
        ars = self._ficha("BAC", "ars")
        self.assertEqual((ars["disponible"], ars.get("motivo")), (False, "sin_escala"))

    def test_el_mini_grafico_de_bac_es_ba_c(self):
        dia = {d.isoformat(): i for i, d in enumerate(self.dias)}
        mes = self._mini("1m")
        self.assertTrue(20 <= len(mes) <= 23, len(mes))         # un mes, no la historia entera
        self.assertEqual(mes[-1]["date"], self.dias[-1].isoformat())
        for p in mes:
            self.assertAlmostEqual(p["close"], ba_c(dia[p["date"]]), places=2, msg=p["date"])
        # Un año, en vela semanal como la da Yahoo: fechada el lunes, con el
        # último cierre de esa semana.
        semana = {}
        for i, d in enumerate(self.dias):
            semana[(d - timedelta(days=d.weekday())).isoformat()] = ba_c(i)
        anio = self._mini("1y")
        self.assertTrue(50 <= len(anio) <= 54, len(anio))
        for p in anio:
            self.assertAlmostEqual(p["close"], semana[p["date"]], places=2, msg=p["date"])
        self.assertEqual(self.mundo.le_pidieron_a_yahoo("BAC"), [], "nada de Nueva York")

        # Sin la Bolsa, el estimado: cada día con SU contado con liqui.
        self.mundo.historia_no_contesta = True
        respaldo = self._mini("1m")
        self.assertEqual(len(respaldo), 22)
        for p in respaldo:
            self.assertAlmostEqual(p["close"], estimado(dia[p["date"]]), places=2, msg=p["date"])

    def test_la_vela_de_hoy_de_bac_sale_de_la_bolsa(self):
        self._tener_bac()
        main._run_velas_diarias_job()
        c = self.mundo.c_hoy
        self.mundo.rueda_de_hoy = (round(c * 1.01, 2), round(c * 1.02, 2), round(c * 0.98, 2), c, 1889.0)
        r = self.client.get("/api/tecnico/BAC/hoy?moneda=ars", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        velas = r.json()["velas"]
        self.assertEqual(len(velas), 1, velas)
        v = velas[0]
        self.assertTrue(v["hoy"])
        self.assertEqual((v["d"], v["o"], v["h"], v["l"], v["c"]),
                         (self.mundo.hoy.isoformat(), *self.mundo.rueda_de_hoy[:4]))
        self.assertEqual(self.mundo.le_pidieron_a_yahoo("BAC.BA"), [])

    def test_las_velas_por_hora_de_bac_en_pesos_son_el_estimado_desde_el_precio_real(self):
        # De BA.C no hay velas por hora en ninguna fuente: en pesos, el estimado
        # (Nueva York de cada hora × contado con liqui de su día ÷ escala), con la
        # escala MEDIDA contra la serie de la Bolsa: arranca donde termina el
        # precio real (4 ÷ 1,02), no donde diría la tabla (4).
        self._tener_bac()
        main._run_velas_diarias_job()
        self._ficha("BAC", "ars")
        r = self.client.get("/api/tecnico/BAC/horas?cada=1h&moneda=ars", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        h1 = r.json()
        self.assertTrue(h1["disponible"], h1)
        self.assertEqual((h1["ticker"], h1["convertida"]), ("BAC", "ccl"))
        self.assertAlmostEqual(h1["escala"], RATIO / 1.02, places=3)
        ultima = h1["puntos"][-1]
        self.assertAlmostEqual(ultima["c"], ba_c(N - 1), delta=ba_c(N - 1) * 0.001)
        self.assertEqual(self.mundo.le_pidieron_a_yahoo("BAC.BA"), [])

    def test_la_liquidez_de_bac_es_la_de_su_cedear_en_pesos(self):
        # Antes: la fila 'BAC' (en dólares, 62 operados) con el precio de Boeing
        # como «especie base»: «poca», $ 747.100 por día. BA.C se opera 4.000
        # CEDEARs por día (≈ $ 115 millones).
        r = self.client.get("/api/liquidez/BAC", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        liq = r.json()
        self.assertTrue(liq["disponible"], liq)
        self.assertEqual((liq["papel"], liq["es_cedear"], liq["en_dolares"]), ("BAC", True, False))
        self.assertEqual((liq["fuente"], liq["ruedas"], liq["dias_sin_operar"]), ("data912", 20, 0))
        self.assertAlmostEqual(liq["pesos_por_dia"], 4000 * self.mundo.c_hoy, delta=1)
        self.assertEqual(liq["nivel"], "media")
        self.assertEqual(self.mundo.le_pidieron_a_yahoo("BAC.BA"), [])

    def test_la_liquidez_sin_la_historia_de_la_bolsa_no_le_cree_a_yahoo(self):
        # Sin la historia de data912, la ficha cae a la última rueda del precio en
        # vivo (BA.C: 1.889 CEDEARs hoy), no al 'BAC.BA' de Yahoo: es otro papel
        # (62 por día) y decía «poca».
        self.mundo.historia_no_contesta = True
        self.mundo.bac_ba_entera = True
        liq = self.client.get("/api/liquidez/BAC", headers=self.h).json()
        self.assertEqual((liq["fuente"], liq["periodo"]), ("data912_vivo", "ultima_rueda"))
        self.assertAlmostEqual(liq["pesos_por_dia"], 1889 * self.mundo.c_hoy, delta=1)
        self.assertEqual(liq["nivel"], "media")
        self.assertEqual(self.mundo.le_pidieron_a_yahoo("BAC.BA"), [])


if __name__ == "__main__":
    unittest.main()
