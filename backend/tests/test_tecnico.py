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
        self.hoy, self.precios = hoy, {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
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
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily"):
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
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()

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

    def _ficha(self, asset, moneda="usd", h=None):
        r = self.client.get(f"/api/tecnico/{asset}?moneda={moneda}", headers=h or self.h)
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
        self.assertEqual(len(usd["puntos"]), tecnico.RUEDAS_GRAFICO)
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
        primero = len(self.dias) - tecnico.RUEDAS_GRAFICO
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


if __name__ == "__main__":
    unittest.main()
