"""Las velas diarias que guarda Rendi para el análisis técnico.

Entra por las mismas puertas que producción: las posiciones y la watchlist se
cargan por HTTP, y la corrida es `main._run_velas_diarias_job`, lo mismo que se
llama al final de la foto diaria de cada noche. Lo único que se reemplaza es
Yahoo, en su punto más bajo (`pricing.yahoo._historia`): todo lo que está arriba
—qué activos se siguen, qué se baja, cómo se guarda— es el código real.

Los casos que importan:
  · qué activos se siguen: un CEDEAR guarda la acción de afuera (dólares) y el
    CEDEAR en pesos; los bonos, fondos y efectivo no tienen serie;
  · la primera vez se bajan 3 años, las noches siguientes sólo el último mes;
  · un split reescribe la historia en Yahoo: si lo guardado no se reemplaza, la
    pantalla mostraría una caída de 75% que no existió;
  · la vela de hoy (incompleta) y las filas rotas de Yahoo no entran;
  · si la foto diaria falla, las velas corren igual.

Corre con: cd backend && python3 -m pytest tests/test_velas_diarias.py
"""
import os
import sqlite3
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

import pandas as pd
from fastapi.testclient import TestClient

import main
import velas_diarias
from fechas import hoy_art_date

NAN = float("nan")


def _ruedas(hasta: date, n: int) -> list:
    """Las últimas `n` ruedas (lunes a viernes) antes de `hasta`, sin incluirla."""
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _tabla(filas: dict) -> pd.DataFrame:
    """{date: (o, h, l, c, v)} → la tabla que devuelve yfinance."""
    idx = pd.DatetimeIndex([pd.Timestamp(f) for f in sorted(filas)])
    cols = list(zip(*[filas[f] for f in sorted(filas)])) or [[]] * 5
    return pd.DataFrame({"Open": cols[0], "High": cols[1], "Low": cols[2],
                         "Close": cols[3], "Volume": cols[4]}, index=idx)


class YahooFalso:
    """Reemplaza a Yahoo. `precios[ticker](fecha)` da el cierre de ese día;
    anota cada pedido para poder ver qué se le pidió."""

    def __init__(self, hoy: date):
        self.hoy = hoy
        self.precios = {}
        self.pedidos = []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        self.pedidos.append((ticker, period, auto_adjust))
        f = self.precios.get(ticker)
        if f is None:
            return pd.DataFrame()
        n = 760 if period == "3y" else 22
        # Incluye la rueda de HOY: Yahoo la devuelve aunque esté a medias.
        dias = _ruedas(self.hoy, n) + [self.hoy]
        filas = {}
        for d in dias:
            c = f(d)
            filas[d] = (c, c * 1.01, c * 0.99, c, 1000.0)
        return _tabla(filas)


class VelasDiariasTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions",
                      "brokers"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"velas-{tag}@rendi.test",))
            conn.commit()
            self.uid = cur.lastrowid
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        # La lista de CEDEARs de BYMA (data912) también es red: vacía salvo en
        # el test que la necesita.
        self.byma = {}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   # La corrida nocturna también arma la lista de cambios de ratio,
                   # que le pregunta a Yahoo sus splits y a data912 la historia:
                   # sin red, la prueba da lo mismo todos los días.
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: self.byma)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    # — armado por HTTP, como la app —

    def _broker(self, name, currency):
        r = self.client.post("/api/brokers", json={"name": name, "currency": currency},
                             headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _posicion(self, broker, asset, asset_type=None, **extra):
        body = {"broker": broker, "asset": asset, "quantity": 10, "buy_price": 100,
                "asset_type": asset_type, **extra}
        r = self.client.post("/api/positions", json=body, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _seguir(self, symbol, asset_type=None):
        r = self.client.post("/api/watchlist", json={"symbol": symbol, "asset_type": asset_type},
                             headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _velas(self, ticker):
        with main.db_abierta() as conn:
            return velas_diarias.serie(conn, ticker)

    def _estado(self, ticker):
        with main.db_abierta() as conn:
            r = conn.execute("SELECT * FROM velas_estado WHERE symbol=?", (ticker,)).fetchone()
            return dict(r) if r else None

    # — los casos —

    def test_que_activos_se_siguen(self):
        self._broker("IOL", "ARS")
        self._broker("Schwab", "USD")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self._posicion("IOL", "GGAL", "ACCION")
        self._posicion("IOL", "AL30", "BONO")
        self._posicion("Schwab", "MSFT", "STOCK")
        self._posicion("Schwab", "BTC", "CRYPTO")
        self._seguir("NVDA")
        self._seguir("YPFD.BA")
        with main.db_abierta() as conn:
            seguidos = set(velas_diarias.simbolos_a_seguir(conn))
        self.assertEqual(seguidos, {"AAPL", "AAPL.BA", "GGAL.BA", "MSFT", "BTC-USD",
                                    "NVDA", "YPFD.BA"})

    def test_cedear_sin_etiqueta_bac_y_monedas_estables(self):
        # SPY cargado en IOL sin tipo, como llega de muchos imports: BYMA lo lista
        # como CEDEAR, así que también se guarda SPY de Nueva York (dólares).
        self.byma = {"SPY": {"mercado": "arg_cedears"}, "GGAL": {"mercado": "arg_stocks"},
                     "BAC": {"mercado": "arg_cedears"}}
        self._broker("IOL", "ARS")
        self._broker("Binance", "USDT")
        self._posicion("IOL", "SPY")
        self._posicion("IOL", "GGAL")
        self._posicion("IOL", "BAC", "CEDEAR")
        self._posicion("Binance", "USDC", "CRYPTO")
        with main.db_abierta() as conn:
            seguidos = set(velas_diarias.simbolos_a_seguir(conn))
        self.assertEqual(seguidos, {"SPY", "SPY.BA", "GGAL.BA", "BAC"},
                         "GGAL es acción local (sin serie de afuera); BAC sólo en dólares "
                         "(su '.BA' de Yahoo viene roto); USDC no tiene nada que medir")

    def test_sin_la_lista_de_byma_se_sigue_lo_etiquetado(self):
        self.byma = {}          # data912 no contestó
        self._broker("IOL", "ARS")
        self._posicion("IOL", "SPY")
        self._posicion("IOL", "AAPL", "CEDEAR")
        with main.db_abierta() as conn:
            seguidos = set(velas_diarias.simbolos_a_seguir(conn))
        self.assertEqual(seguidos, {"SPY.BA", "AAPL", "AAPL.BA"})

    def test_primera_noche_baja_3_anios_y_la_siguiente_un_mes(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos, [("MSFT", "3y", False)],
                         "la primera vez: 3 años, cierre ajustado por splits y no por dividendos")
        velas = self._velas("MSFT")
        self.assertEqual(len(velas), 760)
        self.assertLess(velas[-1]["date"], self.hoy.isoformat(), "la vela de hoy no entra")
        self.assertEqual(velas[-1]["high"], 404.0)

        self.yahoo.pedidos.clear()
        self.yahoo.precios["MSFT"] = lambda d: 410.0 if d == _ruedas(self.hoy, 1)[0] else 400.0
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos, [("MSFT", "1mo", False)])
        velas = self._velas("MSFT")
        self.assertEqual(len(velas), 760, "correr de nuevo no duplica")
        self.assertEqual(velas[-1]["close"], 410.0, "la última rueda se actualiza")

    def test_un_split_reemplaza_toda_la_historia(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "NVDA", "STOCK")
        self.yahoo.precios["NVDA"] = lambda d: 800.0
        main._run_velas_diarias_job()
        # Split 4 a 1: Yahoo ahora devuelve TODA la historia dividida por 4.
        self.yahoo.precios["NVDA"] = lambda d: 200.0
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo", "3y"],
                         "detecta que la historia cambió y la baja entera")
        cierres = {v["close"] for v in self._velas("NVDA")}
        self.assertEqual(cierres, {200.0},
                         "no puede quedar ningún 800 viejo: sería una caída de 75% inventada")
        self.assertEqual(len(self._velas("NVDA")), 760)

    def test_split_que_yahoo_ajusta_tarde(self):
        # Split hace 15 ruedas. Las primeras noches Yahoo muestra la caída real
        # (800 → 200) sin ajustar lo viejo; recién después reescribe la historia.
        # En el último mes, 15 días ya coinciden y 7 no: con la regla de "la
        # mayoría" esto pasaba de largo y quedaba una caída de 75% inventada.
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "NVDA", "STOCK")
        split = _ruedas(self.hoy, 15)[0]
        self.yahoo.precios["NVDA"] = lambda d: 200.0 if d >= split else 800.0
        main._run_velas_diarias_job()

        libre = []

        def ajustado(d):
            # Mientras Rendi rebaja la historia, otro tiene que poder escribir.
            if self.yahoo.pedidos and self.yahoo.pedidos[-1][1] == "3y":
                c = sqlite3.connect(main.DB_PATH, timeout=0)
                try:
                    c.execute("BEGIN IMMEDIATE")
                    c.rollback()
                    libre.append(True)
                except sqlite3.OperationalError:
                    libre.append(False)
                finally:
                    c.close()
            return 200.0
        self.yahoo.precios["NVDA"] = ajustado
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo", "3y"])
        self.assertEqual({v["close"] for v in self._velas("NVDA")}, {200.0})
        self.assertTrue(libre and all(libre),
                        "Rendi no puede tener la base tomada mientras espera a Yahoo")

    def test_una_correccion_suelta_no_rebaja_todo(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        main._run_velas_diarias_job()
        corregido = _ruedas(self.hoy, 5)[0]
        self.yahoo.precios["MSFT"] = lambda d: 420.0 if d == corregido else 400.0
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo"])
        self.assertIn(420.0, {v["close"] for v in self._velas("MSFT")})

    def test_cada_30_dias_se_baja_la_historia_entera(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        main._run_velas_diarias_job()
        hace_31 = (self.hoy - timedelta(days=31)).isoformat() + " 03:00:00"
        with main.db_abierta() as conn:
            conn.execute("UPDATE velas_estado SET ultima_completa=? WHERE symbol='MSFT'", (hace_31,))
            conn.commit()
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["3y"])
        self.assertEqual(len(self._velas("MSFT")), 760)

    def test_filas_rotas_de_yahoo_no_entran(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        ruedas = _ruedas(self.hoy, 3)

        def rara(ticker, period, interval, auto_adjust, timeout):
            return _tabla({
                ruedas[0]: (NAN, NAN, NAN, NAN, 5000.0),     # volumen sin precio
                ruedas[1]: (6000.0, 0.0, 0.0, 6100.0, 3000.0),  # máximo/mínimo en 0
                ruedas[2]: (6100.0, 6300.0, 6000.0, 6200.0, 2000.0),
            })
        with mock.patch("pricing.yahoo._historia", rara):
            main._run_velas_diarias_job()
        velas = self._velas("GGAL.BA")
        self.assertEqual([v["date"] for v in velas], [ruedas[1].isoformat(), ruedas[2].isoformat()])
        self.assertIsNone(velas[0]["high"], "un máximo de 0 arruinaría el máximo del año")
        self.assertEqual(velas[0]["close"], 6100.0)

    def test_sin_datos_queda_anotado_y_va_primero_la_noche_siguiente(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "AAA", "STOCK")
        self._posicion("Schwab", "ZZZ", "STOCK")
        self.yahoo.precios["ZZZ"] = lambda d: 10.0      # AAA: Yahoo no devuelve nada
        main._run_velas_diarias_job()
        self.assertEqual(self._estado("AAA")["ok"], 0)
        self.assertIsNone(self._estado("AAA")["ultima_completa"])
        self.yahoo.precios["AAA"] = lambda d: 5.0
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos[0], ("AAA", "3y", False),
                         "lo que nunca se bajó va primero y con la historia entera")
        self.assertEqual(len(self._velas("AAA")), 760)

    def test_se_borra_lo_de_mas_de_3_anios(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        viejo = (self.hoy - timedelta(days=velas_diarias.DIAS_GUARDADOS + 5)).isoformat()
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('MSFT', ?, 1)",
                         (viejo,))
            conn.commit()
        main._run_velas_diarias_job()
        self.assertNotIn(viejo, {v["date"] for v in self._velas("MSFT")})

    def test_si_la_foto_diaria_falla_las_velas_corren_igual(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        with mock.patch("main.run_daily_snapshot", side_effect=RuntimeError("foto rota")):
            main._run_daily_snapshot_job()
        self.assertEqual(len(self._velas("MSFT")), 760)


if __name__ == "__main__":
    unittest.main()
