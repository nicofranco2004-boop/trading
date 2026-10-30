"""Las velas diarias que guarda Rendi para el análisis técnico.

Entra por las mismas puertas que producción: las posiciones y la watchlist se
cargan por HTTP, y la corrida es `main._run_velas_diarias_job`, lo mismo que se
llama al final de la foto diaria de cada noche. Lo único que se reemplaza es
Yahoo, en su punto más bajo (`pricing.yahoo._historia`): todo lo que está arriba
—qué activos se siguen, qué se baja, cómo se guarda— es el código real.

Los casos que importan:
  · qué activos se siguen: un CEDEAR guarda la acción de afuera (dólares) y el
    CEDEAR en pesos; los bonos, fondos y efectivo no tienen serie;
  · la primera vez se baja la historia entera (5 años), las noches siguientes
    sólo el último mes, y una vez por mes otra vez entera: así llegaron solos
    los 2 años de más cuando se pasó de 3 a 5;
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


def _ruedas_del_periodo(hoy: date, period: str) -> list:
    """Las ruedas que trae Yahoo para `period`, sin la de hoy. Un período en
    años ('5y') es de CALENDARIO, desde el mismo día de hace N años: medido el
    29/10/2026, «5y» de GGAL.BA y de BTC-USD arranca el 29/10/2021 (1.826 días
    antes) y el de AAPL el 01/11/2021. La puesta al día ('1mo'), las últimas 22."""
    if not period.endswith("y"):
        return _ruedas(hoy, 22)
    anios = int(period[:-1])
    try:
        d = hoy.replace(year=hoy.year - anios)
    except ValueError:                      # 29 de febrero
        d = hoy.replace(year=hoy.year - anios, day=28)
    out = []
    while d < hoy:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _tabla(filas: dict) -> pd.DataFrame:
    """{date: (o, h, l, c, v)} → la tabla que devuelve yfinance."""
    idx = pd.DatetimeIndex([pd.Timestamp(f) for f in sorted(filas)])
    cols = list(zip(*[filas[f] for f in sorted(filas)])) or [[]] * 5
    return pd.DataFrame({"Open": cols[0], "High": cols[1], "Low": cols[2],
                         "Close": cols[3], "Volume": cols[4]}, index=idx)


class YahooFalso:
    """Reemplaza a Yahoo. `precios[ticker](fecha)` da el cierre de ese día;
    anota cada pedido para poder ver qué se le pidió. El S&P 500, que se guarda
    todas las noches lo tenga alguien o no (velas_diarias.SP500), va anotado
    aparte (`pedidos_sp500`) y con un precio fijo: así cada prueba cuenta los
    pedidos de lo que la gente tiene, y una prueba propia cuenta el del S&P."""

    def __init__(self, hoy: date):
        self.hoy = hoy
        self.precios = {}
        self.pedidos = []
        self.pedidos_sp500 = []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        if ticker == velas_diarias.SP500:
            self.pedidos_sp500.append((ticker, period, auto_adjust))
        else:
            self.pedidos.append((ticker, period, auto_adjust))
        f = self.precios.get(ticker) or (
            (lambda d: 5000.0) if ticker == velas_diarias.SP500 else None)
        if f is None:
            return pd.DataFrame()
        # Incluye la rueda de HOY: Yahoo la devuelve aunque esté a medias.
        dias = _ruedas_del_periodo(self.hoy, period) + [self.hoy]
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
            for t in ("velas_diarias", "velas_estado", "velas_corridas", "splits_yahoo",
                      "watchlist", "positions", "brokers"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"velas-{tag}@rendi.test",))
            conn.commit()
            self.uid = cur.lastrowid
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        # Cuántas velas deja una bajada completa (sin la de hoy, que no entra).
        self.completa = len(_ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO))
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
                                    "NVDA", "YPFD.BA", velas_diarias.SP500})

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
        self.assertEqual(seguidos, {"SPY", "SPY.BA", "GGAL.BA", "BAC", velas_diarias.SP500},
                         "GGAL es acción local (sin serie de afuera); BAC sólo en dólares "
                         "(su '.BA' de Yahoo viene roto); USDC no tiene nada que medir")

    def test_sin_la_lista_de_byma_se_sigue_lo_etiquetado(self):
        self.byma = {}          # data912 no contestó
        self._broker("IOL", "ARS")
        self._posicion("IOL", "SPY")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self._posicion("IOL", "ZZZZ")
        with main.db_abierta() as conn:
            seguidos = set(velas_diarias.simbolos_a_seguir(conn))
        # SPY sin tipo es un CEDEAR de la lista fija de la app: se sigue igual que
        # con la lista de BYMA (en dólares y en pesos). Hasta el re-test A1c (29/10)
        # con data912 caído se guardaba sólo en pesos. Un «.BA» que no está en
        # ninguna lista (ZZZZ) sigue sólo en pesos.
        self.assertEqual(seguidos, {"SPY", "SPY.BA", "AAPL", "AAPL.BA", "ZZZZ.BA", velas_diarias.SP500})

    def test_el_sp500_se_guarda_aunque_nadie_lo_tenga(self):
        # Es contra lo que la ficha compara «un día normal» (movimiento.py).
        with main.db_abierta() as conn:
            self.assertEqual(velas_diarias.simbolos_a_seguir(conn), [velas_diarias.SP500])
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos_sp500, [(velas_diarias.SP500, velas_diarias.PERIODO_COMPLETO, False)])
        with main.db_abierta() as conn:
            self.assertTrue(velas_diarias.serie(conn, velas_diarias.SP500))

    def test_primera_noche_baja_la_historia_entera_y_la_siguiente_un_mes(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos, [("MSFT", velas_diarias.PERIODO_COMPLETO, False)],
                         "la primera vez: 5 años, cierre ajustado por splits y no por dividendos")
        velas = self._velas("MSFT")
        self.assertEqual(len(velas), self.completa, "la poda no le come el principio")
        # 5 años de CALENDARIO (desde el mismo día de hace 5 años, la regla de
        # Yahoo): 5 × 365 días se quedaba un día corto con un 29 de febrero en el
        # medio y daba rojo cuando ese día caía en un fin de semana (30/10/2026).
        self.assertEqual(velas[0]["date"],
                         _ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO)[0].isoformat(),
                         "5 años de calendario")
        self.assertLess(velas[-1]["date"], self.hoy.isoformat(), "la vela de hoy no entra")
        self.assertEqual(velas[-1]["high"], 404.0)

        self.yahoo.pedidos.clear()
        self.yahoo.precios["MSFT"] = lambda d: 410.0 if d == _ruedas(self.hoy, 1)[0] else 400.0
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos, [("MSFT", "1mo", False)])
        velas = self._velas("MSFT")
        self.assertEqual(len(velas), self.completa, "correr de nuevo no duplica")
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
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo", velas_diarias.PERIODO_COMPLETO],
                         "detecta que la historia cambió y la baja entera")
        cierres = {v["close"] for v in self._velas("NVDA")}
        self.assertEqual(cierres, {200.0},
                         "no puede quedar ningún 800 viejo: sería una caída de 75% inventada")
        self.assertEqual(len(self._velas("NVDA")), self.completa)

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
            if self.yahoo.pedidos and self.yahoo.pedidos[-1][1] == velas_diarias.PERIODO_COMPLETO:
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
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo", velas_diarias.PERIODO_COMPLETO])
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
        self.assertEqual([p[1] for p in self.yahoo.pedidos], [velas_diarias.PERIODO_COMPLETO])
        self.assertEqual(len(self._velas("MSFT")), self.completa)

    def test_los_que_tenian_3_anios_completan_5_con_la_bajada_del_mes(self):
        # Así se pasó de 3 a 5 años (29/10/2026) sin una noche especial: lo
        # guardado antes del cambio tiene 3 años, las noches de puesta al día
        # piden sólo el último mes (no lo alargan), y la bajada completa de cada
        # mes ya pide 5 años. La poda nueva no borra lo recién bajado.
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        with mock.patch("velas_diarias.PERIODO_COMPLETO", "3y"), \
                mock.patch("velas_diarias.DIAS_GUARDADOS", 3 * 366):    # el código de antes
            main._run_velas_diarias_job()
        tres = len(_ruedas_del_periodo(self.hoy, "3y"))
        self.assertEqual(len(self._velas("MSFT")), tres)

        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo"], "todavía no le toca la del mes")
        self.assertEqual(len(self._velas("MSFT")), tres)

        hace_31 = (self.hoy - timedelta(days=31)).isoformat() + " 03:00:00"
        with main.db_abierta() as conn:
            conn.execute("UPDATE velas_estado SET ultima_completa=? WHERE symbol='MSFT'", (hace_31,))
            conn.commit()
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos, [("MSFT", "5y", False)])
        velas = self._velas("MSFT")
        self.assertEqual(len(velas), self.completa, "los 2 años nuevos quedan guardados")
        self.assertGreater(self.completa, tres + 2 * 250)
        self.assertEqual(velas[0]["date"], _ruedas_del_periodo(self.hoy, "5y")[0].isoformat(),
                         "arranca el mismo día de hace 5 años: la poda no lo tocó")
        self.assertEqual(self._estado("MSFT")["ultima_completa"][:10], hoy_art_date().isoformat())

        # Y la noche siguiente sigue con lo de todas las noches, sin perder nada.
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo"])
        self.assertEqual(len(self._velas("MSFT")), self.completa)

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

    def test_sin_datos_queda_anotado_y_se_reintenta_al_final_de_la_fila(self):
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
        # Se reintenta con la historia entera, pero DESPUÉS de los que andan: un
        # símbolo que nunca trae datos no puede comerse la noche de los demás
        # (antes iba primero siempre; auditoría de seguridad 22/10).
        self.assertEqual(self.yahoo.pedidos, [("ZZZ", "1mo", False), ("AAA", velas_diarias.PERIODO_COMPLETO, False)])
        self.assertEqual(len(self._velas("AAA")), self.completa)

    # — Yahoo: lo que no es un ticker, lo que falla siempre y cuando corta —
    # (auditoría de capacidad 24/10/2026, medida otra vez sobre este motor el
    # 30/10: dos corridas seguidas, la primera bajó 717 de 2.468 y la segunda 75)

    def _ultima_noche(self):
        with main.db_abierta() as conn:
            return velas_diarias.ultima_noche(conn)

    def _admin(self):
        with main.db_abierta() as conn:
            conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.uid,))
            conn.commit()

    def test_lo_que_no_es_un_ticker_no_se_le_pide_a_yahoo(self):
        # Un fondo importado con el nombre entero: la ficha no lo aceptaría
        # nunca (main._SYMBOL_RE), y Yahoo tampoco lo tiene.
        fondo = "NOVUS RENTA VARIABLE - CLASE A"
        self._broker("IOL", "ARS")
        self._posicion("IOL", fondo, "ACCION")
        self._posicion("IOL", "GGAL", "ACCION")
        self.yahoo.precios["GGAL.BA"] = lambda d: 6000.0
        main._run_velas_diarias_job()
        self.assertEqual({p[0] for p in self.yahoo.pedidos}, {"GGAL.BA"})
        n = self._ultima_noche()
        # GGAL y el S&P 500 (que se guarda siempre).
        self.assertEqual((n["bajados"], n["no_son_tickers"], n["sin_datos"]), (2, 1, 0))
        # El S&P 500 (`^GSPC`, un índice de Yahoo) sí es un ticker: se pidió.
        self.assertTrue(velas_diarias.es_ticker(velas_diarias.SP500))
        self.assertEqual(len(self.yahoo.pedidos_sp500), 1)
        # /admin lo muestra.
        self._admin()
        e = self.client.get("/api/admin/velas", headers=self.h).json()
        self.assertEqual(e["ultima_noche"]["no_son_tickers"], 1)

    def _con_dia(self, dia: int, n: int = 1) -> list:
        """Nombres de ticker cuyo día semanal (`dia_de_la_semana`) es `dia`."""
        out, i = [], 0
        while len(out) < n:
            t = f"ZQ{i}"
            if velas_diarias.dia_de_la_semana(t) == dia:
                out.append(t)
            i += 1
        return out

    def test_lo_que_falla_tres_noches_seguidas_se_pide_una_vez_por_semana(self):
        hoy = self.hoy
        [toca] = self._con_dia(hoy.weekday())
        [no_toca] = self._con_dia((hoy.weekday() + 1) % 7)
        self._broker("Schwab", "USD")
        for t in (toca, no_toca, "MSFT"):
            self._posicion("Schwab", t, "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        for _ in range(3):                                  # tres noches seguidas sin datos
            main._run_velas_diarias_job()
        self.assertEqual(self._estado(no_toca)["fallas_seguidas"], 3)

        def _noche(dias_atras):
            # La última vez que se le pidió fue hace `dias_atras` días.
            antes = (hoy - timedelta(days=dias_atras)).isoformat() + " 03:00:00"
            with main.db_abierta() as conn:
                conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol IN (?, ?)",
                             (antes, toca, no_toca))
                conn.commit()
            self.yahoo.pedidos.clear()
            main._run_velas_diarias_job()
            return {p[0] for p in self.yahoo.pedidos}

        # Ayer: el de hoy se pide (es su día), el otro espera; MSFT se pide siempre.
        self.assertEqual(_noche(1), {toca, "MSFT"})
        self.assertEqual(self._ultima_noche()["en_espera_semanal"], 1)
        # Hace más de una semana (una noche que no corrió): se pide aunque no sea su día.
        self.assertEqual(_noche(8), {toca, no_toca, "MSFT"})
        # Hoy mismo (el botón de /admin dos veces): ninguno de los dos.
        self.assertEqual(_noche(0), {"MSFT"})
        # Si vuelve a andar, vuelve a pedirse todas las noches.
        self.yahoo.precios[no_toca] = lambda d: 7.0
        _noche(8)
        self.assertEqual(self._estado(no_toca)["fallas_seguidas"], 0)
        self.assertEqual(_noche(1), {toca, no_toca, "MSFT"})

    def test_la_ficha_a_pedido_no_espera_la_semana(self):
        # Lo semanal es de la noche: abrir la ficha lo pide (tiene sus frenos).
        [no_toca] = self._con_dia((self.hoy.weekday() + 1) % 7)
        with main.db_abierta() as conn:
            for _ in range(3):
                velas_diarias._anotar(conn, no_toca, completa=False, ok=False, error="x")
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol=?",
                         ((self.hoy - timedelta(days=1)).isoformat() + " 03:00:00", no_toca))
            conn.commit()
            velas_diarias.actualizar(conn, [no_toca], podar=False)
        self.assertEqual([p[0] for p in self.yahoo.pedidos], [no_toca])

    def _cartera_de(self, n):
        self._broker("Schwab", "USD")
        tickers = [f"T{i:02d}" for i in range(n)]
        for t in tickers:
            self._posicion("Schwab", t, "STOCK")
            self.yahoo.precios[t] = lambda d: 10.0
        return tickers

    def test_corte_de_yahoo_pausa_y_sigue_sin_anotar_fallas(self):
        tickers = self._cartera_de(12)
        with mock.patch("velas_diarias.TANDA", 4):
            main._run_velas_diarias_job()                 # noche 1: todos bien
            # Noche 2: Yahoo corta después de 4 pedidos (una tanda), sin error:
            # devuelve tablas vacías. La pausa lo deja contestar de nuevo.
            real, pedidos = self.yahoo, []
            estado = {"cortado": False}

            def yahoo(ticker, period, interval, auto_adjust, timeout):
                pedidos.append(ticker)
                if 4 < len(pedidos) <= 8:
                    estado["cortado"] = True
                if estado["cortado"]:
                    return pd.DataFrame()
                return real(ticker, period, interval, auto_adjust, timeout)
            pausas = []

            def dormir(seg):
                pausas.append(seg)
                estado["cortado"] = False
                pedidos.extend(["(pausa)"] * 4)   # lo que viene ya no cae en el corte
            with mock.patch("pricing.yahoo._historia", yahoo), \
                    mock.patch("velas_diarias._dormir", dormir):
                main._run_velas_diarias_job()
        self.assertEqual(pausas, [velas_diarias.PAUSA_CORTE_SEG])
        n = self._ultima_noche()
        # Los 12 y el S&P 500.
        self.assertEqual((n["bajados"], n["pausas"], n["cortados_por_yahoo"], n["sin_datos"]),
                         (13, 1, 0, 0))
        self.assertTrue(all(self._estado(t)["ok"] == 1 for t in tickers))

    def test_corte_que_no_se_levanta_deja_todo_para_manana_sin_fallas(self):
        tickers = self._cartera_de(12)
        with mock.patch("velas_diarias.TANDA", 4):
            main._run_velas_diarias_job()
            pausas = []
            with mock.patch("pricing.yahoo._historia", lambda *a: pd.DataFrame()), \
                    mock.patch("velas_diarias._dormir", pausas.append), \
                    self.assertLogs("velas_diarias", "INFO") as log:
                main._run_velas_diarias_job()
        self.assertEqual(len(pausas), velas_diarias.PAUSAS_MAX)
        n = self._ultima_noche()
        self.assertEqual((n["bajados"], n["cortados_por_yahoo"], n["sin_datos"]), (0, 13, 0))
        # Nadie quedó anotado como «no existe»: mañana se piden todos de nuevo.
        self.assertTrue(all(self._estado(t)["ok"] == 1 and self._estado(t)["fallas_seguidas"] == 0
                            for t in tickers))
        # El renglón «Velas diarias:» del registro dice cuántos cortó Yahoo (números,
        # no la lista de nombres).
        renglon = next(m for m in log.output if "Velas diarias: {" in m)
        self.assertIn("'cortados_por_yahoo': 13", renglon)
        self.assertIn("'no_son_tickers': 0", renglon)

    def test_uno_o_dos_que_dejaron_de_cotizar_no_son_un_corte(self):
        self._cartera_de(2)
        main._run_velas_diarias_job()
        for t in ("T00", "T01"):                           # los dos dejan de cotizar
            del self.yahoo.precios[t]
        with mock.patch("velas_diarias._dormir") as dormir:
            main._run_velas_diarias_job()
        dormir.assert_not_called()
        self.assertEqual(self._ultima_noche()["sin_datos"], 2)
        self.assertEqual(self._estado("T00")["fallas_seguidas"], 1)

    def test_lo_que_anoche_no_se_pidio_va_primero(self):
        # Con la fila siempre en el mismo orden, si Yahoo cortaba se caían todas
        # las noches los mismos (los últimos). Lo que hace más días que no se pide
        # va adelante, en la noche (turnos por persona) y en `actualizar`.
        tickers = self._cartera_de(12)
        main._run_velas_diarias_job()
        hace_dos = (self.hoy - timedelta(days=2)).isoformat() + " 03:00:00"

        def sin_pedir(t):
            with main.db_abierta() as conn:
                conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol=?", (hace_dos, t))
                conn.commit()
        sin_pedir("T11")
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos[0][0], "T11", "en la noche, primero")
        sin_pedir("T07")
        self.yahoo.pedidos.clear()
        with main.db_abierta() as conn:
            velas_diarias.actualizar(conn, tickers)
        self.assertEqual(self.yahoo.pedidos[0][0], "T07", "en actualizar, primero")

    def test_un_activo_bajado_entero_se_guarda_en_pocas_consultas(self):
        # En Postgres cada consulta es un viaje por la red: guardar vela por vela
        # eran ~1.260 viajes por activo bajado entero (5 años).
        self.yahoo.precios["MSFT"] = lambda d: 400.0

        class Contador:
            def __init__(self, conn):
                self._c, self.n = conn, 0

            def execute(self, *a):
                self.n += 1
                return self._c.execute(*a)

            def executemany(self, *a):
                self.n += 1
                return self._c.executemany(*a)

            def __getattr__(self, k):
                return getattr(self._c, k)
        with main.db_abierta() as conn:
            c = Contador(conn)
            velas_diarias.actualizar(c, ["MSFT"])
        self.assertEqual(len(self._velas("MSFT")), self.completa)
        # leer el estado + borrar + guardar + anotar + podar lo viejo
        self.assertLessEqual(c.n, 8)

    def test_se_borra_lo_mas_viejo_que_lo_guardado(self):
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
        self.assertEqual(len(self._velas("MSFT")), self.completa)


if __name__ == "__main__":
    unittest.main()
