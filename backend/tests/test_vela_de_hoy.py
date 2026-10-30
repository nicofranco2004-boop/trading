"""La vela de HOY del gráfico de la ficha (GET /api/tecnico/{asset}/hoy).

Entra por el camino de producción, como test_tecnico.py: las posiciones por
HTTP, las velas guardadas por el trabajo nocturno real
(`main._run_velas_diarias_job`) con Yahoo reemplazado en su punto más bajo
(`pricing.yahoo._historia`), y la vela de hoy pedida por HTTP.

Los casos que importan:
  · la vela de hoy sale de la MISMA serie que el gráfico (la acción de afuera
    de un CEDEAR en dólares; la de BYMA ÷ el MEP de una acción argentina);
  · un '.BA' con la diaria de hoy vacía se arma con las velas de 1 hora;
  · sin vela de hoy (antes de la apertura, fecha ya guardada, vela rota, sin
    MEP de hoy) no se inventa nada;
  · varios pedidos dentro del minuto le piden a Yahoo UNA vez;
  · la ficha y su lectura no cambian: la vela de hoy no se guarda.

Corre con: cd backend && python3 -m pytest tests/test_vela_de_hoy.py
"""
import math
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


class YahooFalso:
    """Las ruedas cerradas: `precios[ticker]` fijo. La de HOY: `hoy_diaria[ticker]`
    (o, h, l, c, v) sólo en la descarga corta de la vela en curso ('5d'), y
    `hoy_horas[ticker]` [(hora, (o, h, l, c, v))] para las de 1 hora."""

    def __init__(self, hoy):
        self.hoy, self.precios, self.hoy_diaria, self.hoy_horas, self.pedidos = hoy, {}, {}, {}, []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        if ticker != "^GSPC":
            self.pedidos.append((ticker, period, interval))
        hoy = pd.Timestamp(session_today(ticker))
        if interval == "1h":
            filas = {hoy + pd.Timedelta(hours=hh): f for hh, f in self.hoy_horas.get(ticker, [])}
            return _tabla(filas) if filas else pd.DataFrame()
        c = self.precios.get(ticker) or (5000.0 if ticker == "^GSPC" else None)
        if c is None:
            return pd.DataFrame()
        dias = _ruedas(self.hoy, 760 if period == "3y" else 22)
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
        self.dolar = {"mep": {"compra": 990.0, "venta": 1010.0, "medio": 1000.0}}
        self.en_horario = True
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("main._get_dolar_data", lambda: self.dolar),
                   mock.patch("alerts_engine.rueda_en_horario", lambda m, now: self.en_horario)]
        for p in self._p:
            p.start()
        velas_diarias._en_curso.clear()
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

    def test_cedear_en_dolares_trae_la_vela_de_hoy_de_la_accion_de_afuera(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertEqual(r["vela"], {"d": session_today("AAPL"), "o": 301.0, "h": 306.0,
                                     "l": 299.0, "c": 304.5, "v": 5_000_000.0})
        self.assertTrue(r["en_rueda"])
        self.assertTrue(r["actualizada"])
        # La ficha no cambia: la vela de hoy no se guarda en la tabla.
        ficha = self.client.get("/api/tecnico/AAPL", headers=self.h).json()
        self.assertLess(ficha["puntos"][-1]["d"], r["vela"]["d"])
        with main.db_abierta() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM velas_diarias WHERE date >= ?",
                             (r["vela"]["d"],)).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_cedear_en_pesos_es_el_cedear(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL.BA"] = (15000.0, 15400.0, 14900.0, 15300.0, 80_000.0)
        r = self._hoy("AAPL", "ars")
        self.assertEqual((r["vela"]["o"], r["vela"]["c"]), (15000.0, 15300.0))

    def test_varios_pedidos_en_el_minuto_son_un_pedido_a_yahoo(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        self._hoy("AAPL")
        self._hoy("AAPL", h=self.h_otro)
        self._hoy("AAPL")
        cortos = [p for p in self.yahoo.pedidos if p == ("AAPL", "5d", "1d")]
        self.assertEqual(len(cortos), 1)

    def test_accion_argentina_con_la_diaria_vacia_se_arma_con_las_horas(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(1000.0)
        self.yahoo.precios["GGAL.BA"] = 5000.0
        main._run_velas_diarias_job()
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
        self.assertEqual(r["vela"], {"d": session_today("GGAL.BA"), "o": 5000.0, "h": 5200.0,
                                     "l": 4900.0, "c": 4980.0, "v": 600.0})
        # En dólares: el mismo papel de BYMA ÷ el MEP de HOY (el medio, como el resto).
        usd = self._hoy("GGAL", "usd", local=True)
        self.assertAlmostEqual(usd["vela"]["c"], 4.98, places=6)
        self.assertAlmostEqual(usd["vela"]["h"], 5.2, places=6)

    def test_sin_mep_de_hoy_no_se_inventa(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(1000.0)
        self.yahoo.precios["GGAL.BA"] = 5000.0
        main._run_velas_diarias_job()
        self.yahoo.hoy_diaria["GGAL.BA"] = (5000.0, 5100.0, 4950.0, 5050.0, 100.0)
        self.dolar = {}
        self.assertIsNone(self._hoy("GGAL", "usd", local=True)["vela"])

    def test_antes_de_la_apertura_no_hay_vela_ni_se_piden_horas(self):
        self._cedear_apple()
        self.en_horario = False
        r = self._hoy("AAPL")
        self.assertIsNone(r["vela"])
        self.assertNotIn(("AAPL", "5d", "1h"), self.yahoo.pedidos)

    def test_cerrada_la_rueda_se_sigue_viendo_hasta_que_se_guarda(self):
        self._cedear_apple()
        self.en_horario = False
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        r = self._hoy("AAPL")
        self.assertEqual(r["vela"]["c"], 304.5)
        self.assertFalse(r["en_rueda"])

    def test_si_esa_fecha_ya_esta_guardada_no_hay_vela_doble(self):
        self._cedear_apple()
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 306.0, 299.0, 304.5, 5_000_000.0)
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                         "VALUES ('AAPL', ?, 301, 306, 299, 304.5, 1)", (session_today("AAPL"),))
            conn.commit()
        self.assertIsNone(self._hoy("AAPL")["vela"])

    def test_vela_rota_no_se_dibuja(self):
        self._cedear_apple()
        self.en_horario = False
        self.yahoo.hoy_diaria["AAPL"] = (301.0, 299.0, 298.0, 304.5, 1.0)   # máximo < cierre
        self.assertIsNone(self._hoy("AAPL")["vela"])

    def test_activo_sin_velas_no_tiene_vela_de_hoy(self):
        self.assertEqual(self._hoy("ZZZZ"), {"vela": None})

    def test_simbolo_invalido(self):
        r = self.client.get("/api/tecnico/<x>/hoy", headers=self.h)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
