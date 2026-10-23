"""La lectura técnica de la ficha del activo (tecnico.py + GET /api/tecnico).

Entra por el camino de producción: las posiciones se cargan por HTTP, las velas
las guarda el trabajo nocturno real (`main._run_velas_diarias_job`) con Yahoo
reemplazado en su punto más bajo, y la ficha se pide por HTTP. Así se prueba lo
que el usuario va a ver, no una función suelta.

Los casos que importan:
  · las cuentas (media, RSI) dan lo mismo que la referencia de pandas;
  · un CEDEAR se lee en dólares con la acción de afuera y en pesos con el CEDEAR;
  · una acción argentina se lee en dólares dividiendo CADA día por el MEP de
    ESE día (con el de hoy, la tendencia en dólares saldría igual a la de pesos);
  · lo que no tiene velas dice "no disponible", nunca inventa;
  · /admin muestra el estado del guardado y sólo lo ve un admin.

Corre con: cd backend && python3 -m pytest tests/test_tecnico.py
"""
import os
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

import main
import tecnico
from fechas import hoy_art_date


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class YahooFalso:
    """`precios[ticker](i, fecha)` da el cierre de la rueda i (0 = la más vieja)."""

    def __init__(self, hoy):
        self.hoy, self.precios, self.pedidos = hoy, {}, []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        self.pedidos.append((ticker, period, auto_adjust))
        f = self.precios.get(ticker)
        if f is None:
            return pd.DataFrame()
        dias = _ruedas(self.hoy, 760 if period == "3y" else 22)
        base = _ruedas(self.hoy, 760)
        filas = {}
        for d in dias:
            c = f(base.index(d), d)
            filas[pd.Timestamp(d)] = (c, c * 1.01, c * 0.99, c, 1000.0)
        idx = sorted(filas)
        o, h, l, c, v = zip(*[filas[k] for k in idx])
        return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                            index=pd.DatetimeIndex(idx))


class CuentasTest(unittest.TestCase):
    """Diferencial contra la referencia: pandas."""

    def test_media_igual_a_pandas(self):
        import random
        random.seed(3)
        xs = [100 + random.gauss(0, 5) for _ in range(400)]
        nuestra = tecnico.media(xs, 200)
        ref = pd.Series(xs).rolling(200).mean().tolist()
        for a, b in zip(nuestra, ref):
            if b != b:   # NaN
                self.assertIsNone(a)
            else:
                self.assertAlmostEqual(a, b, places=9)

    def test_rsi_igual_al_de_wilder(self):
        import random
        random.seed(5)
        xs, x = [], 100.0
        for _ in range(300):
            x *= 1 + random.gauss(0, 0.02)
            xs.append(x)
        nuestro = tecnico.rsi(xs, 14)
        # Wilder = media móvil exponencial con alfa 1/14, arrancando del promedio
        # simple de las primeras 14 (así lo calcula TradingView).
        d = pd.Series(xs).diff()
        sube, baja = d.clip(lower=0), (-d).clip(lower=0)
        s, b = sube[1:15].mean(), baja[1:15].mean()
        ref = [None] * 15
        ref[14] = 100 - 100 / (1 + s / b)
        for i in range(15, len(xs)):
            s = (s * 13 + sube[i]) / 14
            b = (baja[i] + b * 13) / 14
            ref.append(100 - 100 / (1 + s / b))
        for a, r in zip(nuestro[14:], ref[14:]):
            self.assertAlmostEqual(a, r, places=9)
        self.assertTrue(all(v is None for v in nuestro[:14]))

    def test_cruce_del_rsi(self):
        # Vuelve a pasar 30 para arriba hace 2 ruedas.
        r = [None, 40, 35, 28, 25, 27, 31, 33, 34]
        self.assertEqual(tecnico.cruce_rsi(r), {"tipo": "salio_de_abajo", "hace": 2})
        # Baja de 70 en la última rueda.
        self.assertEqual(tecnico.cruce_rsi([60, 72, 75, 69]), {"tipo": "salio_de_arriba", "hace": 0})
        # Entrar a la zona (bajar de 30) no es "salir": no se avisa.
        self.assertIsNone(tecnico.cruce_rsi([40, 35, 29, 25]))
        # Un cruce de hace más de 10 ruedas ya no cuenta.
        self.assertIsNone(tecnico.cruce_rsi([25, 35] + [40] * 12))

    def test_rsi_extremos(self):
        sube = [float(i) for i in range(1, 40)]
        self.assertEqual(tecnico.rsi(sube)[-1], 100.0)
        baja = [float(i) for i in range(40, 1, -1)]
        self.assertEqual(tecnico.rsi(baja)[-1], 0.0)


class FichaTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"tec-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier, is_admin) "
                "VALUES (?, 'x', 1, 1, 'pro', 1)", (f"tec-adm-{tag}@rendi.test",))
            self.admin = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_admin = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        self.yahoo = YahooFalso(self.hoy)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   # La corrida nocturna también arma la lista de cambios de ratio,
                   # que le pregunta a Yahoo sus splits y a data912 la historia:
                   # sin red, la prueba da lo mismo todos los días.
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        # El cupo de la hora de las fichas a pedido vive en memoria: cada
        # prueba arranca con la hora vacía.
        import velas_diarias
        velas_diarias._a_pedido_hechos.clear()

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

    def _mep(self, f):
        """Un MEP por día: `f(i)` para la rueda i, más fines de semana con el
        del viernes (como la tabla real, que tiene huecos)."""
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), f(i) * 1.1, f(i)))
            conn.commit()

    def _ficha(self, asset, moneda="usd", h=None, local=False):
        r = self.client.get(f"/api/tecnico/{asset}?moneda={moneda}{'&local=1' if local else ''}",
                            headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_cedear_en_dolares_y_en_pesos(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR")
        # Afuera, Apple baja de 300 a ~225; el CEDEAR en pesos SUBE porque el
        # dólar sube más rápido: la misma acción, dos tendencias.
        self.yahoo.precios["AAPL"] = lambda i, d: 300 - i * 0.1
        self.yahoo.precios["AAPL.BA"] = lambda i, d: (300 - i * 0.1) * (1000 + i * 2) / 20
        main._run_velas_diarias_job()

        usd = self._ficha("AAPL", "usd")
        self.assertTrue(usd["disponible"])
        self.assertEqual(usd["ticker"], "AAPL")
        self.assertIsNone(usd["convertida"])
        self.assertLess(usd["lectura"]["dist_media200"], 0, "en dólares está debajo de su media")
        self.assertLess(usd["lectura"]["pendiente_media200"], 0)
        # Dos años de CALENDARIO (no una cantidad fija de velas).
        piso = (self.dias[-1] - timedelta(days=tecnico.DIAS_GRAFICO)).isoformat()
        self.assertEqual(len(usd["puntos"]), sum(1 for d in self.dias if d.isoformat() > piso))
        self.assertIsNotNone(usd["puntos"][0]["s200"],
                             "la media de 200 del primer punto se calcula con la historia anterior")

        ars = self._ficha("AAPL", "ars")
        self.assertEqual(ars["ticker"], "AAPL.BA")
        self.assertGreater(ars["lectura"]["dist_media200"], 0, "en pesos parece alcista")

    def test_accion_argentina_en_dolares_con_el_mep_de_cada_dia(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(lambda i: 1000 + i)                    # el dólar sube todos los días
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + i * 5
        main._run_velas_diarias_job()

        f = self._ficha("GGAL", "usd")
        self.assertEqual(f["ticker"], "GGAL.BA")
        self.assertEqual(f["convertida"], "mep")
        ultimo = len(self.dias) - 1
        esperado = (5000 + ultimo * 5) / (1000 + ultimo)
        self.assertAlmostEqual(f["puntos"][-1]["c"], esperado, places=3)
        # La vela entera viaja convertida con el MISMO dólar del día (gráfico de velas).
        self.assertAlmostEqual(f["puntos"][-1]["h"], esperado * 1.01, places=3)
        self.assertAlmostEqual(f["puntos"][-1]["l"], esperado * 0.99, places=3)
        self.assertAlmostEqual(f["puntos"][-1]["o"], esperado, places=3)
        piso = (self.dias[-1] - timedelta(days=tecnico.DIAS_GRAFICO)).isoformat()
        primero = next(i for i, d in enumerate(self.dias) if d.isoformat() > piso)
        self.assertAlmostEqual(f["puntos"][0]["c"], (5000 + primero * 5) / (1000 + primero), places=3,
                               msg="cada día con SU dólar, no con el de hoy")

        p = self._ficha("GGAL", "ars")
        self.assertIsNone(p["convertida"])
        self.assertAlmostEqual(p["puntos"][-1]["c"], 5000 + ultimo * 5, places=3)

    def test_accion_local_no_usa_el_adr_de_otro_usuario(self):
        # Alguien tiene el ADR de Galicia en Schwab (10 acciones, ~US$ 50) y
        # vos tenés la acción local: tu ficha en dólares tiene que ser TU acción.
        with main.db_abierta() as conn:   # dos brokers: plan Pro
            conn.execute("UPDATE users SET tier='pro' WHERE id=?", (self.uid,))
            conn.commit()
        self._broker("IOL", "ARS")
        self._broker("Schwab", "USD")
        self._posicion("IOL", "GGAL", "ACCION")
        self._posicion("Schwab", "GGAL", "STOCK")
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        main._run_velas_diarias_job()
        r = self.client.get("/api/tecnico/GGAL?moneda=usd&local=1", headers=self.h).json()
        self.assertEqual((r["ticker"], r["convertida"]), ("GGAL.BA", "mep"))
        self.assertAlmostEqual(r["puntos"][-1]["c"], 5.0, places=6)
        adr = self.client.get("/api/tecnico/GGAL?moneda=usd", headers=self.h).json()
        self.assertEqual(adr["ticker"], "GGAL", "sin la marca, el ADR (lo que tiene el de Schwab)")

    def test_sin_dolar_ese_dia_no_se_inventa(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        # Sólo hay dólar para los últimos 100 días.
        with main.db_abierta() as conn:
            for d in self.dias[-100:]:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0, 1000.0))
            conn.commit()
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        main._run_velas_diarias_job()
        f = self._ficha("GGAL", "usd")
        self.assertEqual(f["puntos"][0]["d"], self.dias[-100].isoformat())
        self.assertEqual(f["lectura"]["ruedas"], 100)
        self.assertIsNone(f["lectura"]["media200"], "con 100 ruedas no hay media de 200")

    def test_bono_y_lo_que_no_tiene_velas(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AL30", "BONO")
        main._run_velas_diarias_job()
        self.assertFalse(self._ficha("AL30")["disponible"])
        self.assertFalse(self._ficha("ZZZZ")["disponible"])
        r = self.client.get("/api/tecnico/<script>", headers=self.h)
        self.assertIn(r.status_code, (400, 404))

    def test_admin_ve_el_estado_y_el_usuario_no(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self._posicion("Schwab", "NOEXISTE", "STOCK")
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        r = self.client.get("/api/admin/velas", headers=self.h)
        self.assertIn(r.status_code, (401, 403))

        antes = self.client.get("/api/admin/velas", headers=self.h_admin).json()
        self.assertEqual(antes["activos"], 0)
        main._run_velas_diarias_job()
        e = self.client.get("/api/admin/velas", headers=self.h_admin).json()
        self.assertEqual((e["activos"], e["ok"]), (2, 1))
        self.assertEqual([f["symbol"] for f in e["fallados"]], ["NOEXISTE"])
        self.assertEqual(e["filas"], 760)
        self.assertEqual(e["hasta"], self.dias[-1].isoformat())
        self.assertFalse(e["corriendo"])

    def test_el_boton_no_arranca_dos_corridas(self):
        main._tomar_corrida("velas_diarias")
        try:
            r = self.client.post("/api/admin/velas/correr", headers=self.h_admin)
            self.assertEqual(r.json()["status"], "already_running")
            # Y la de la foto diaria también se saltea mientras tanto.
            with mock.patch("velas_diarias.correr") as correr:
                main._run_velas_diarias_job()
            correr.assert_not_called()
        finally:
            main._soltar_corrida("velas_diarias")


    def test_cripto_el_anio_son_365_dias(self):
        # Bitcoin cotiza los 7 días: 252 velas son 8 meses. El máximo "del año"
        # tiene que mirar 12 meses de calendario.
        self._broker("Binance", "USDT")
        self._posicion("Binance", "BTC", "CRYPTO")
        hoy = self.hoy
        dias = [hoy - timedelta(days=k) for k in range(760, 0, -1)]   # todos los días
        pico = hoy - timedelta(days=300)                               # hace 10 meses

        def btc(ticker, period, interval, auto_adjust, timeout):
            idx = [pd.Timestamp(d) for d in dias]
            c = [120000.0 if d == pico else 80000.0 for d in dias]
            return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1.0] * len(c)},
                                index=pd.DatetimeIndex(idx))
        with mock.patch("pricing.yahoo._historia", btc):
            main._run_velas_diarias_job()
        f = self._ficha("BTC")
        self.assertEqual(f["lectura"]["maximo_12m"], 120000.0, "el pico de hace 10 meses es del año")
        self.assertAlmostEqual(f["lectura"]["dist_maximo_12m"], -33.33, places=1)
        self.assertGreater(f["puntos"][0]["d"], (hoy - timedelta(days=731)).isoformat())
        self.assertLess(f["puntos"][0]["d"], (hoy - timedelta(days=700)).isoformat(), "2A = 2 años de calendario")

    def test_cedear_en_pesos_sin_el_escalon_del_cambio_de_ratio(self):
        # El 5/12 BYMA pasa XLE de un ratio a otro el doble: el CEDEAR en pesos
        # cae 50 % ese día mientras afuera no se mueve. Yahoo no lo corrige.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "XLE", "CEDEAR")
        cambio = len(self.dias) - 200
        self.yahoo.precios["XLE"] = lambda i, d: 90.0
        self.yahoo.precios["XLE.BA"] = lambda i, d: 9000.0 if i < cambio else 4500.0
        main._run_velas_diarias_job()
        ars = self._ficha("XLE", "ars")
        cierres = {p["c"] for p in ars["puntos"]}
        self.assertEqual(cierres, {4500.0}, "toda la historia en la escala nueva, sin caída falsa")
        self.assertAlmostEqual(ars["lectura"]["dist_media200"], 0.0, places=6)

    def test_precio_roto_de_un_dia_se_saca(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "ETHA", "CEDEAR")
        roto = len(self.dias) - 10
        self.yahoo.precios["ETHA"] = lambda i, d: 20.0
        self.yahoo.precios["ETHA.BA"] = lambda i, d: 6810.0 if i == roto else 19650.0
        main._run_velas_diarias_job()
        ars = self._ficha("ETHA", "ars")
        self.assertNotIn(6810.0, {p["c"] for p in ars["puntos"]})
        self.assertNotIn(self.dias[roto].isoformat(), {p["d"] for p in ars["puntos"]})

    def test_dia_sin_mep_usa_el_ultimo_mep_como_el_resto_de_la_app(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(lambda i: 1000.0)
        hueco = self.dias[-3].isoformat()
        with main.db_abierta() as conn:   # ese día hay blue (1.100) pero no MEP
            conn.execute("UPDATE fx_rates_daily SET mep_venta=NULL WHERE date=?", (hueco,))
            conn.commit()
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        main._run_velas_diarias_job()
        f = self._ficha("GGAL", "usd", local=True)
        punto = next(p for p in f["puntos"] if p["d"] == hueco)
        self.assertAlmostEqual(punto["c"], 5.0, places=6, msg="con el MEP de antes, no con el blue de ese día")
        import fx
        with main.db_abierta() as conn:
            self.assertEqual(fx.fx_for_date(conn, hueco), 1000.0)

    def test_acciones_con_clase_se_piden_con_guion(self):
        import velas_diarias
        self.assertEqual(velas_diarias.ticker_de_afuera("BRK.B"), "BRK-B")
        self.assertEqual(velas_diarias.ticker_de_afuera("AAPL"), "AAPL")
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "BRK.B", "STOCK")
        self.yahoo.precios["BRK-B"] = lambda i, d: 480.0
        main._run_velas_diarias_job()
        f = self._ficha("BRK.B")
        self.assertTrue(f["disponible"])
        self.assertEqual(f["ticker"], "BRK-B")

    def test_lista_de_seguimiento_tiene_tope(self):
        with mock.patch("main.WATCHLIST_TOPE", 3):
            for t in ("AAA", "BBB", "CCC"):
                r = self.client.post("/api/watchlist", json={"symbol": t}, headers=self.h)
                self.assertEqual(r.status_code, 200, r.text)
            r = self.client.post("/api/watchlist", json={"symbol": "DDD"}, headers=self.h)
            self.assertEqual(r.status_code, 400)
            self.assertIn("llegó a 3", r.text)
            # Repetir uno que ya está no es sumar: sigue andando.
            self.assertEqual(self.client.post("/api/watchlist", json={"symbol": "AAA"}, headers=self.h).status_code, 200)

    def test_los_que_fallan_pasan_al_final_de_la_fila(self):
        import velas_diarias
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        for t in ("ZZA", "ZZB"):
            self.client.post("/api/watchlist", json={"symbol": t}, headers=self.h)
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        main._run_velas_diarias_job()                          # noche 1: ZZA y ZZB fallan
        self.yahoo.pedidos = []
        with main.db_abierta() as conn:
            velas_diarias.actualizar(conn, ["ZZA", "ZZB", "MSFT"])
        self.assertEqual(self.yahoo.pedidos[0], ("MSFT", "1mo", False), "los de verdad primero")

    def test_admin_cuenta_solo_lo_que_se_sigue_hoy(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:   # un activo viejo que ya nadie sigue, atrasado y fallado
            conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('VIEJO', '2025-01-02', 1)")
            conn.execute("INSERT INTO velas_estado (symbol, ok, error) VALUES ('VIEJO', 0, 'x')")
            conn.commit()
        e = self.client.get("/api/admin/velas", headers=self.h_admin).json()
        self.assertEqual((e["seguidos"], e["atrasados"], e["fallados"]), (1, [], []))


    def test_cierre_del_instrumento_de_tu_tenencia(self):
        # La ficha de AAPL en dólares es la acción de afuera, pero tu tenencia se
        # valúa con el CEDEAR en pesos: la ficha necesita SU último cierre para
        # saber cuánto se movió hoy.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        self.yahoo.precios["AAPL.BA"] = lambda i, d: 25000.0
        main._run_velas_diarias_job()
        f = self.client.get("/api/tecnico/AAPL?moneda=usd&ref=AAPL.BA", headers=self.h).json()
        self.assertEqual(f["cierre_ref"], {"fecha": self.dias[-1].isoformat(), "cierre": 25000.0})
        self.assertIsNone(self._ficha("AAPL")["cierre_ref"])
        r = self.client.get("/api/tecnico/AAPL?ref=<x>", headers=self.h)
        self.assertEqual(r.status_code, 400)

    # ─── Ficha de un activo que nadie sigue (mapa de calor, buscador) ────────

    def _pedidos(self, ticker):
        return [p for p in self.yahoo.pedidos if p[0] == ticker]

    def test_activo_que_nadie_sigue_se_baja_al_abrir_la_ficha(self):
        # NVDA no está en ninguna cartera ni watchlist: la noche no la baja.
        self.yahoo.precios["NVDA"] = lambda i, d: 100 + i * 0.2
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos("NVDA"), [], "la noche sólo baja lo que alguien sigue")
        f = self._ficha("NVDA")
        self.assertTrue(f["disponible"])
        self.assertEqual(f["ticker"], "NVDA")
        self.assertEqual(f["puntos"][-1]["d"], self.dias[-1].isoformat())
        self.assertEqual(self._pedidos("NVDA"), [("NVDA", "3y", False)])
        # La segunda vez (o la de otra persona) ya está guardada: no se pide de nuevo.
        self._ficha("NVDA")
        self._ficha("NVDA", "ars")
        self.assertEqual(len(self._pedidos("NVDA")), 1)

    def test_cedear_a_pedido_baja_solo_la_accion_de_afuera(self):
        # La serie en pesos de un CEDEAR necesita la lista de cambios de ratio,
        # que se arma de noche sólo para lo seguido: a pedido va la de afuera y
        # en pesos se multiplica por el MEP de cada día.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        self.yahoo.precios["AAPL.BA"] = lambda i, d: 25000.0
        with mock.patch("main._fetch_data912_equities", lambda: {"AAPL": {"mercado": "arg_cedears"}}):
            usd = self._ficha("AAPL.BA")
            ars = self._ficha("AAPL.BA", "ars")
        self.assertEqual((usd["ticker"], usd["convertida"]), ("AAPL", None))
        self.assertEqual((ars["ticker"], ars["convertida"]), ("AAPL", "mep"))
        self.assertAlmostEqual(ars["puntos"][-1]["c"], 250_000.0, places=3)
        self.assertEqual(self._pedidos("AAPL.BA"), [])

    def test_accion_argentina_a_pedido(self):
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0      # el ADR: otra cosa
        f = self._ficha("GGAL.BA", local=True)
        self.assertEqual((f["ticker"], f["convertida"]), ("GGAL.BA", "mep"))
        self.assertAlmostEqual(f["puntos"][-1]["c"], 5.0, places=6)
        self.assertEqual(self._pedidos("GGAL"), [], "el ADR no se baja para la acción local")
        # Un '.BA' sin saber si es CEDEAR (data912 caído en esta prueba) no se baja.
        g = self._ficha("YPFD.BA")
        self.assertEqual((g["disponible"], g["motivo"]), (False, "sin_serie"))
        self.assertEqual(self._pedidos("YPFD.BA"), [])

    def test_cupo_por_persona_y_por_hora(self):
        import velas_diarias
        for t in ("AAA", "BBB", "CCC"):
            self.yahoo.precios[t] = lambda i, d: 10.0
        with mock.patch.object(velas_diarias, "A_PEDIDO_POR_PERSONA_HORA", 2):
            self.assertTrue(self._ficha("AAA")["disponible"])
            self.assertTrue(self._ficha("BBB")["disponible"])
            f = self._ficha("CCC")
            self.assertEqual((f["disponible"], f["motivo"]), (False, "tope"))
            self.assertEqual(self._pedidos("CCC"), [], "pasado el cupo no se le pide nada a Yahoo")
            # Lo ya bajado se sigue viendo: el cupo frena descargas, no lecturas.
            self.assertTrue(self._ficha("AAA")["disponible"])
        with mock.patch.object(velas_diarias, "A_PEDIDO_TODOS_HORA", 2):
            otro = self.h_admin
            r = self.client.get("/api/tecnico/CCC", headers=otro).json()
            self.assertEqual(r.get("motivo"), "tope", "el cupo de todos juntos también frena")

    def test_lo_que_no_existe_no_se_reintenta_enseguida(self):
        f = self._ficha("ZZZZ")
        self.assertEqual((f["disponible"], f["motivo"]), (False, "sin_datos"))
        self._ficha("ZZZZ")
        self.assertEqual(len(self._pedidos("ZZZZ")), 1)
        self.assertEqual(self._ficha("AL30")["motivo"], "sin_serie")
        self.assertEqual(self._pedidos("AL30"), [], "un bono no tiene velas: ni se pide")

    def test_velas_viejas_se_ponen_al_dia_al_abrir(self):
        import velas_diarias
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0
        self._ficha("NVDA")
        # Pasaron días: las últimas velas no están y el último intento fue hace 7 horas.
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol='NVDA' AND date >= ?",
                         (self.dias[-3].isoformat(),))
            hace = (velas_diarias._ahora_utc() - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol='NVDA'", (hace,))
            conn.commit()
        f = self._ficha("NVDA")
        self.assertEqual(f["puntos"][-1]["d"], self.dias[-1].isoformat())
        self.assertEqual(self._pedidos("NVDA")[-1], ("NVDA", "1mo", False), "sólo el último mes")

    def test_la_noche_borra_lo_que_nadie_sigue_ni_mira(self):
        import velas_diarias
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0
        self.yahoo.precios["AMD"] = lambda i, d: 100.0
        self._ficha("NVDA")
        self._ficha("AMD")
        viejo = (velas_diarias._ahora_utc() - timedelta(days=50)).strftime("%Y-%m-%d %H:%M:%S")
        with main.db_abierta() as conn:
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol IN ('NVDA')", (viejo,))
            conn.commit()
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            hay = {r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM velas_diarias")}
            # Lo seguido nunca se borra, aunque su último intento sea viejo.
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol='MSFT'", (viejo,))
            conn.commit()
            self.assertEqual(velas_diarias._podar_a_pedido(conn, {"MSFT"}), 0)
        self.assertEqual(hay, {"MSFT", "AMD"}, "NVDA nadie la miró en 50 días; AMD sí")

    def test_dos_a_la_vez_bajan_una_sola_vez(self):
        import threading
        import time as _t
        import velas_diarias
        pedidos = []

        def lento(t, periodo):
            pedidos.append(t)
            _t.sleep(0.3)
            return self.yahoo(t, periodo, "1d", False, 10.0)
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0

        def abrir(uid):
            with main.db_abierta() as conn:
                velas_diarias.asegurar(conn, ["NVDA"], uid, bajar=lento)
        hilos = [threading.Thread(target=abrir, args=(u,)) for u in (1, 2, 3)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(pedidos, ["NVDA"])
        self.assertTrue(self._ficha("NVDA")["disponible"])


if __name__ == "__main__":
    unittest.main()
