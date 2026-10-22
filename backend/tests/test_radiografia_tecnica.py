"""La radiografía técnica de la Cartera (tecnico.para_la_cartera + POST /api/tecnico/cartera).

Entra por el camino de producción, igual que test_tecnico.py: las posiciones se
cargan por HTTP, las velas las guarda el trabajo nocturno real
(`main._run_velas_diarias_job`) con Yahoo reemplazado en su punto más bajo, y la
lectura se pide por HTTP.

Los casos que importan:
  · cada activo trae la MISMA lectura que su ficha (GET /api/tecnico/{asset}):
    las palabras de la Cartera y de la ficha salen de la misma cuenta;
  · un CEDEAR se lee en dólares (bajista aunque en pesos suba);
  · una acción argentina se lee con su BYMA ÷ el MEP de cada día, no con el ADR;
  · «lo que cambió esta semana» trae el cruce de la media de 200 y de 50 de los
    últimos 7 días, con su fecha, y NO uno de hace un mes;
  · un bono, un fondo con espacios en el nombre o un activo sin velas vuelven
    «sin lectura», sin tirar abajo el resto del pedido.

Corre con: cd backend && python3 -m pytest tests/test_radiografia_tecnica.py
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
    """`precios[ticker](i, fecha)` da el cierre de la rueda i (0 = la más vieja).
    El mismo Yahoo de mentira que test_tecnico.py: reemplaza `pricing.yahoo._historia`."""

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


class RadiografiaTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"radio-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        self.n = len(self.dias)
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

    def _mep(self, f, desde=0):
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):
                if i >= desde:
                    conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                                 (d.isoformat(), f(i) * 1.1, f(i)))
            conn.commit()

    def _cartera(self, activos):
        r = self.client.post("/api/tecnico/cartera", json={"activos": activos}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return {(x["asset"], x["local"]): x for x in r.json()["lecturas"]}

    def _armar(self):
        self._broker("IOL", "ARS")
        self._broker("Schwab", "USD")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self._posicion("IOL", "GGAL", "ACCION")
        self._posicion("IOL", "AL30", "BONO")
        self._posicion("Schwab", "NVDA", "STOCK")
        self._posicion("Schwab", "KO", "STOCK")
        self._posicion("Schwab", "GGAL", "STOCK")      # el ADR: también queda guardado
        n = self.n
        self._mep(lambda i: 1000 + i)
        # AAPL: baja afuera; en pesos sube con el dólar. En la Cartera, bajista.
        self.yahoo.precios["AAPL"] = lambda i, d: 300 - i * 0.1
        self.yahoo.precios["AAPL.BA"] = lambda i, d: (300 - i * 0.1) * (1000 + i * 2) / 20
        # GGAL local: sube en pesos MÁS que el dólar → alcista en dólares.
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + i * 20
        # El ADR de Galicia baja: si la Cartera leyera el ADR, saldría bajista.
        self.yahoo.precios["GGAL"] = lambda i, d: 80 - i * 0.05
        # NVDA: venía bajando y hace 3 ruedas saltó arriba de las dos medias.
        self.yahoo.precios["NVDA"] = lambda i, d: 150.0 if i >= n - 3 else 100 - i * 0.01
        # KO: lo mismo, pero hace 30 ruedas: no es «de esta semana».
        self.yahoo.precios["KO"] = lambda i, d: 150.0 if i >= n - 30 else 100 - i * 0.01
        main._run_velas_diarias_job()

    def test_la_misma_lectura_que_la_ficha(self):
        self._armar()
        c = self._cartera([{"asset": "AAPL"}, {"asset": "GGAL", "local": True},
                           {"asset": "NVDA"}, {"asset": "KO"}])
        for (asset, local), x in c.items():
            ficha = self.client.get(f"/api/tecnico/{asset}?moneda=usd{'&local=1' if local else ''}",
                                    headers=self.h).json()
            self.assertTrue(x["disponible"], asset)
            self.assertEqual(x["lectura"], ficha["lectura"], f"{asset}: la Cartera y la ficha leen distinto")

        self.assertLess(c[("AAPL", False)]["lectura"]["dist_media200"], 0,
                        "un CEDEAR se mide en dólares: bajista aunque en pesos suba")
        ggal = c[("GGAL", True)]["lectura"]
        ultimo = self.n - 1
        self.assertAlmostEqual(ggal["precio"], (5000 + ultimo * 20) / (1000 + ultimo), places=6,
                               msg="acción argentina = su BYMA ÷ el MEP de ese día, no el ADR")
        self.assertGreater(ggal["dist_media200"], 0)
        adr = self._cartera([{"asset": "GGAL"}])[("GGAL", False)]["lectura"]
        self.assertLess(adr["dist_media200"], 0, "sin la marca `local` es el ADR, que baja: son dos lecturas")

    def test_lo_que_cambio_esta_semana(self):
        self._armar()
        c = self._cartera([{"asset": "NVDA"}, {"asset": "KO"}, {"asset": "AAPL"}])
        fecha = self.dias[self.n - 3].isoformat()
        self.assertEqual(c[("NVDA", False)]["cambios"], [
            {"media": 200, "direccion": "arriba", "fecha": fecha},
            {"media": 50, "direccion": "arriba", "fecha": fecha},
        ])
        self.assertEqual(c[("KO", False)]["cambios"], [], "un cruce de hace 30 ruedas no es de esta semana")
        self.assertEqual(c[("AAPL", False)]["cambios"], [])

    def test_velas_cortadas_no_son_de_esta_semana(self):
        # MSFT cruzó su media hace 28 ruedas y sus velas se cortaron 3 ruedas
        # después (Yahoo dejó de mandarlas). Contado desde su última vela, el
        # cruce caía «esta semana»; contado desde hoy, es de hace un mes.
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        n = self.n
        self.yahoo.precios["MSFT"] = lambda i, d: 150.0 if i >= n - 28 else 100 - i * 0.01
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol='MSFT' AND date > ?",
                         (self.dias[n - 26].isoformat(),))
            conn.commit()
        x = self._cartera([{"asset": "MSFT"}])[("MSFT", False)]
        self.assertEqual(x["lectura"]["fecha"], self.dias[n - 26].isoformat())
        self.assertEqual(x["cambios"], [], "un cruce de hace un mes no es de esta semana")

    def test_lo_que_no_tiene_lectura(self):
        self._armar()
        c = self._cartera([{"asset": "AL30", "local": True}, {"asset": "FCI PIONERO PESOS"},
                           {"asset": "ZZZZ"}, {"asset": "AAPL"}, {"asset": "AAPL"}])
        self.assertFalse(c[("AL30", True)]["disponible"], "un bono no tiene velas")
        self.assertFalse(c[("FCI PIONERO PESOS", False)]["disponible"],
                         "un fondo no es un ticker: sin lectura, sin romper el pedido")
        self.assertFalse(c[("ZZZZ", False)]["disponible"])
        self.assertTrue(c[("AAPL", False)]["disponible"])
        self.assertEqual(len(c), 4, "el mismo activo dos veces se lee una")

    def test_pocas_ruedas_no_tiene_media_de_200(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(lambda i: 1000.0, desde=self.n - 100)     # dólar sólo de los últimos 100 días
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        main._run_velas_diarias_job()
        x = self._cartera([{"asset": "GGAL", "local": True}])[("GGAL", True)]
        self.assertEqual(x["lectura"]["ruedas"], 100)
        self.assertIsNone(x["lectura"]["media200"], "con 100 ruedas no hay tendencia de fondo: sin lectura")

    def test_tope_y_sesion(self):
        r = self.client.post("/api/tecnico/cartera",
                             json={"activos": [{"asset": f"A{i}"} for i in range(tecnico.MAX_ACTIVOS_CARTERA + 1)]},
                             headers=self.h)
        self.assertEqual(r.status_code, 422, "el tope se corta al leer el pedido")
        r = self.client.post("/api/tecnico/cartera", json={"activos": [{"asset": "AAPL"}]})
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
