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
  · si la foto diaria falla, las velas corren igual;
  · un '.BA' que Yahoo trae clavado (el mismo cierre sin volumen, días o años) se
    guarda con los precios de BYMA: la racha que sigue clavada y la que ya se había
    corregido, nunca una vieja que nunca se corrigió (le cambiaría el factor a un
    cambio de ratio); sin mezclar escalas y sin pisar lo corregido cuando data912 no
    contesta, cuando Yahoo se destraba o cuando reescribe la historia.

Corre con: cd backend && python3 -m pytest tests/test_velas_diarias.py
"""
import contextlib
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from datetime import date, datetime, timedelta
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
from fechas import ART_OFFSET_HORAS, dia_art, hoy_art_date

NAN = float("nan")


def _dia_argentino(marca: str) -> date:
    """El día de acá de una marca de `velas_estado` (UTC, como datetime('now')),
    con la regla de `fechas` y no con la de velas_diarias: si la app la leyera
    mal, esto no la copia."""
    return dia_art(datetime.fromisoformat(str(marca)[:19]))


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
    """Reemplaza a Yahoo. `precios[ticker](fecha)` da el cierre de ese día, o
    (cierre, volumen): con volumen 0 es una rueda «clavada», como las da Yahoo
    (apertura, máximo y mínimo iguales al cierre). Anota cada pedido para poder
    ver qué se le pidió. Los índices, que se guardan todas las noches los tenga
    alguien o no (velas_diarias.INDICES: el S&P 500 y el Nasdaq), van anotados
    aparte (`pedidos_indices`) y con un precio fijo: así cada prueba cuenta los
    pedidos de lo que la gente tiene, y una prueba propia cuenta los de los índices."""

    def __init__(self, hoy: date):
        self.hoy = hoy
        self.precios = {}
        self.pedidos = []
        self.pedidos_indices = []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        if ticker in velas_diarias.INDICES:
            self.pedidos_indices.append((ticker, period, auto_adjust))
        else:
            self.pedidos.append((ticker, period, auto_adjust))
        f = self.precios.get(ticker) or (
            (lambda d: 5000.0) if ticker in velas_diarias.INDICES else None)
        if f is None:
            return pd.DataFrame()
        # Incluye la rueda de HOY: Yahoo la devuelve aunque esté a medias.
        dias = _ruedas_del_periodo(self.hoy, period) + [self.hoy]
        filas = {}
        for d in dias:
            c = f(d)
            c, v = c if isinstance(c, tuple) else (c, 1000.0)
            filas[d] = (c, c * 1.01, c * 0.99, c, v) if v else (c, c, c, c, 0.0)
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
        # La historia de BYMA (data912), con la que se corrige un '.BA' que Yahoo
        # trae clavado: {papel: [filas como las da data912]}; `byma_cae`: no contesta.
        self.historia_byma, self.byma_cae, self.pedidos_byma = {}, False, []

        def _data912(tipo, papel, timeout=10):
            self.pedidos_byma.append(papel)
            if self.byma_cae:
                raise RuntimeError("data912 no contesta")
            return self.historia_byma.get(papel, [])
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("pricing.data912.filas", _data912),
                   # La corrida nocturna también arma la lista de cambios de ratio,
                   # que le pregunta a Yahoo sus splits y a data912 la historia:
                   # sin red, la prueba da lo mismo todos los días.
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("main._fetch_data912_equities", lambda: self.byma)]
        for p in self._p:
            p.start()
        # Los cupos de la ficha a pedido viven en memoria: cada prueba arranca vacía.
        velas_diarias._a_pedido_hechos.clear()

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
                                    "NVDA", "YPFD.BA", *velas_diarias.INDICES})

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
        self.assertEqual(seguidos, {"SPY", "SPY.BA", "GGAL.BA", "BAC", "BAC.BA", *velas_diarias.INDICES},
                         "GGAL es acción local (sin serie de afuera); BAC, el par como "
                         "cualquier CEDEAR; USDC no tiene nada que medir")
        # BAC.BA: su '.BA' de Yahoo es OTRO papel (en dólares). Se baja de la
        # Bolsa, con el código de su CEDEAR en pesos ('BA.C'); a Yahoo, nunca.
        self.yahoo.precios["BAC"] = lambda d: 50.0
        self.yahoo.precios["BAC.BA"] = lambda d: 7.29
        dias = _ruedas(self.hoy, 30)
        self.historia_byma["BA.C"] = [{"date": d.isoformat(), "o": 20000.0, "h": 20100.0, "l": 19900.0,
                                       "c": 20000.0 + i, "v": 4000.0} for i, d in enumerate(dias)]
        with main.db_abierta() as conn:
            velas_diarias.actualizar(conn, ["BAC", "BAC.BA"])
        self.assertEqual([p for p in self.yahoo.pedidos if p[0] == "BAC.BA"], [])
        self.assertIn("BA.C", self.pedidos_byma)
        guardada = self._velas("BAC.BA")
        self.assertEqual([(v["date"], v["close"]) for v in guardada],
                         [(d.isoformat(), 20000.0 + i) for i, d in enumerate(dias)])

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
        self.assertEqual(seguidos, {"SPY", "SPY.BA", "AAPL", "AAPL.BA", "ZZZZ.BA", *velas_diarias.INDICES})

    def test_los_indices_se_guardan_aunque_nadie_los_tenga(self):
        # El S&P 500 es contra lo que la ficha compara «un día normal»
        # (movimiento.py); el Nasdaq, contra lo que «Simular una cartera» compara
        # (cartera_simulada.py). La primera noche bajan su historia entera.
        with main.db_abierta() as conn:
            self.assertEqual(velas_diarias.simbolos_a_seguir(conn), sorted(velas_diarias.INDICES))
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos_indices,
                         [(t, velas_diarias.PERIODO_COMPLETO, False) for t in velas_diarias.INDICES])
        with main.db_abierta() as conn:
            for t in velas_diarias.INDICES:
                self.assertTrue(velas_diarias.serie(conn, t), t)

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

    def _con_dia_de_completa(self, toca: bool, prefijo: str = "ZC") -> str:
        """Un ticker cuyo día de la bajada entera del mes (`dia_de_la_completa`)
        es hoy (`toca`) o no."""
        hoy = self.hoy.toordinal() % velas_diarias.DIAS_ENTRE_COMPLETAS
        i = 0
        while (velas_diarias.dia_de_la_completa(f"{prefijo}{i}") == hoy) != toca:
            i += 1
        return f"{prefijo}{i}"

    def _completa_hace(self, dias, *tickers):
        # 03:00 UTC = 00:00 de acá: el día UTC y el argentino coinciden, así que
        # esto no ve lo anotado de 21 a 24 h (para eso, `_a_las`).
        hace = (self.hoy - timedelta(days=dias)).isoformat() + " 03:00:00"
        with main.db_abierta() as conn:
            for t in tickers:
                conn.execute("UPDATE velas_estado SET ultima_completa=? WHERE symbol=?", (hace, t))
            conn.commit()

    @contextlib.contextmanager
    def _a_las(self, dia: date, hora: int, minuto: int = 0):
        """La app a esa hora ARGENTINA de `dia`: los dos relojes que lee la
        corrida, el de las marcas (`_ahora_utc`, UTC) y el día de acá
        (`fechas.ahora_art`), y Yahoo contestando como ese día."""
        art = datetime(dia.year, dia.month, dia.day, hora, minuto)
        utc = art + timedelta(hours=ART_OFFSET_HORAS)
        antes, self.yahoo.hoy = self.yahoo.hoy, dia
        try:
            with mock.patch("velas_diarias._ahora_utc", lambda: utc), \
                    mock.patch("fechas.ahora_art", lambda: art):
                yield
        finally:
            self.yahoo.hoy = antes

    def test_cada_30_dias_se_baja_la_historia_entera(self):
        # Una vez por mes, cada uno en SU día (`dia_de_la_completa`): con la
        # misma `ultima_completa` (la primera noche, o al forzar los 5 años) no
        # se rebajan todos juntos cada 30 días (auditoría final C4).
        toca, no_toca = self._con_dia_de_completa(True), self._con_dia_de_completa(False)
        self._broker("Schwab", "USD")
        for t in (toca, no_toca):
            self._posicion("Schwab", t, "STOCK")
            self.yahoo.precios[t] = lambda d: 400.0
        main._run_velas_diarias_job()
        self._completa_hace(31, toca, no_toca)
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(sorted(self.yahoo.pedidos),
                         sorted([(toca, velas_diarias.PERIODO_COMPLETO, False), (no_toca, "1mo", False)]),
                         "pasó un mes: el de hoy se baja entero, el otro espera su día")
        self.assertEqual(len(self._velas(toca)), self.completa)
        # Antes de la mitad del mes no toca aunque sea su día.
        self._completa_hace(10, toca)
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual({p[1] for p in self.yahoo.pedidos}, {"1mo"})
        # Pasado mes y medio (su día cayó en una noche que no corrió), toca igual.
        self._completa_hace(46, toca, no_toca)
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual({p[1] for p in self.yahoo.pedidos}, {velas_diarias.PERIODO_COMPLETO})

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

        # Le toca la bajada entera (pasado mes y medio, sea o no su día).
        self._completa_hace(46, "MSFT")
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos, [("MSFT", "5y", False)])
        velas = self._velas("MSFT")
        self.assertEqual(len(velas), self.completa, "los 2 años nuevos quedan guardados")
        self.assertGreater(self.completa, tres + 2 * 250)
        self.assertEqual(velas[0]["date"], _ruedas_del_periodo(self.hoy, "5y")[0].isoformat(),
                         "arranca el mismo día de hace 5 años: la poda no lo tocó")
        # La marca es UTC: su día es el de acá, no sus primeros 10 caracteres
        # (de 21 a 24 h dicen mañana).
        self.assertEqual(_dia_argentino(self._estado("MSFT")["ultima_completa"]), hoy_art_date())

        # Y la noche siguiente sigue con lo de todas las noches, sin perder nada.
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual([p[1] for p in self.yahoo.pedidos], ["1mo"])
        self.assertEqual(len(self._velas("MSFT")), self.completa)

    def test_la_bajada_entera_de_21_a_24_cuenta_desde_el_dia_de_aca(self):
        # La marca se guarda en UTC: bajado entero a las 22 de acá, ya dice
        # «mañana». Cortada con [:10], a los 15 días la cuenta daba 14 y, si ese
        # era su día del mes, la bajada entera saltaba al siguiente: 30 días tarde.
        hoy = self.hoy
        t = self._con_dia_de_completa(True)
        self._broker("Schwab", "USD")
        self._posicion("Schwab", t, "STOCK")
        self.yahoo.precios[t] = lambda d: 400.0
        # Hace 15 días, a las 22: lo pidió su ficha por primera vez (entero).
        with self._a_las(hoy - timedelta(days=15), 22), main.db_abierta() as conn:
            velas_diarias.asegurar(conn, [t], self.uid)
        self.assertEqual(self.yahoo.pedidos, [(t, velas_diarias.PERIODO_COMPLETO, False)])
        self.assertEqual(_dia_argentino(self._estado(t)["ultima_completa"]), hoy - timedelta(days=15))
        # Esta noche pasaron 15 días (acá) y es su día del mes: entero otra vez.
        self.yahoo.pedidos.clear()
        with self._a_las(hoy, 0, 30):
            main._run_velas_diarias_job()
        self.assertEqual(self.yahoo.pedidos, [(t, velas_diarias.PERIODO_COMPLETO, False)])

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
        # GGAL y los índices (que se guardan siempre).
        self.assertEqual((n["bajados"], n["no_son_tickers"], n["sin_datos"]), (1 + len(velas_diarias.INDICES), 1, 0))
        # Los índices (`^GSPC`, `^IXIC`: índices de Yahoo) sí son tickers: se pidieron.
        for t in velas_diarias.INDICES:
            self.assertTrue(velas_diarias.es_ticker(t), t)
        self.assertEqual(len(self.yahoo.pedidos_indices), len(velas_diarias.INDICES))
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

    def test_lo_pedido_de_21_a_24_cuenta_para_el_dia_de_aca_en_lo_semanal(self):
        # La marca se guarda en UTC: a las 22 de acá ya dice «mañana». Cortada
        # con [:10], la noche siguiente creía que ya se había pedido HOY y lo que
        # falla, en su día de la semana, esperaba una semana más.
        hoy = self.hoy
        [t] = self._con_dia(hoy.weekday())
        self._broker("Schwab", "USD")
        self._posicion("Schwab", t, "STOCK")               # Yahoo no trae nada: falla
        for atras in (4, 3, 2):                             # tres noches seguidas sin datos
            with self._a_las(hoy - timedelta(days=atras), 0, 30):
                main._run_velas_diarias_job()
        self.assertEqual(self._estado(t)["fallas_seguidas"], 3)
        # Ayer a las 22 alguien abrió su ficha: se le pidió (y falló otra vez).
        self.yahoo.pedidos.clear()
        with self._a_las(hoy - timedelta(days=1), 22), main.db_abierta() as conn:
            velas_diarias.asegurar(conn, [t], self.uid)
        self.assertEqual([p[0] for p in self.yahoo.pedidos], [t])
        # Esta noche es su día y hoy (acá) todavía no se le pidió: se pide.
        self.yahoo.pedidos.clear()
        with self._a_las(hoy, 0, 30):
            main._run_velas_diarias_job()
        self.assertEqual([p[0] for p in self.yahoo.pedidos], [t])

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
        # Los 12 y los índices.
        self.assertEqual((n["bajados"], n["pausas"], n["cortados_por_yahoo"], n["sin_datos"]),
                         (12 + len(velas_diarias.INDICES), 1, 0, 0))
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
        self.assertEqual((n["bajados"], n["cortados_por_yahoo"], n["sin_datos"]), (0, 12 + len(velas_diarias.INDICES), 0))
        # Nadie quedó anotado como «no existe»: mañana se piden todos de nuevo.
        self.assertTrue(all(self._estado(t)["ok"] == 1 and self._estado(t)["fallas_seguidas"] == 0
                            for t in tickers))
        # El renglón «Velas diarias:» del registro dice cuántos cortó Yahoo (números,
        # no la lista de nombres).
        renglon = next(m for m in log.output if "Velas diarias: {" in m)
        self.assertIn(f"'cortados_por_yahoo': {12 + len(velas_diarias.INDICES)}", renglon)
        self.assertIn("'no_son_tickers': 0", renglon)

    def test_lo_que_sale_de_la_bolsa_no_tapa_un_corte_de_yahoo(self):
        # BAC.BA se baja de la Bolsa (data912), no de Yahoo. Si Yahoo corta y la
        # Bolsa contesta, la tanda con BAC.BA no dice «Yahoo contestó»: si no, los
        # demás de la tanda quedaban anotados como que no existen.
        tickers = self._cartera_de(3)
        self.historia_byma["BA.C"] = [{"date": d.isoformat(), "o": 20000.0, "h": 20100.0, "l": 19900.0,
                                       "c": 20000.0, "v": 4000.0} for d in _ruedas(self.hoy, 30)]
        with main.db_abierta() as conn:
            velas_diarias.actualizar(conn, tickers + ["BAC.BA"])       # todos andan
        pausas = []
        with mock.patch("velas_diarias.TANDA", 4), \
                mock.patch("pricing.yahoo._historia", lambda *a: pd.DataFrame()), \
                mock.patch("velas_diarias._dormir", pausas.append), main.db_abierta() as conn:
            res = velas_diarias.actualizar(conn, tickers + ["BAC.BA"])
        self.assertEqual(len(pausas), velas_diarias.PAUSAS_MAX, "Yahoo cortó: se espera")
        self.assertEqual((res["sin_datos"], res["cortados_por_yahoo"]), ([], 4))
        self.assertTrue(all(self._estado(t)["fallas_seguidas"] == 0 for t in tickers))

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

    # — auditoría final C (31/10/2026), por la corrida de la noche —

    def test_c1_una_tanda_de_lo_que_fallo_durante_un_corte_no_suma_fallas(self):
        # Lo que falló una vez va al final de la fila, justo donde Yahoo ya
        # cortó. La tanda sola no tiene «los que andaban» para darse cuenta: sin
        # el canario (el S&P 500) se anotaba una falla por noche y a las tres
        # quedaba semanal siendo real.
        buenos = self._cartera_de(7)
        fallados = ["FA0", "FA1", "FA2", "FA3"]
        for t in fallados:
            self._posicion("Schwab", t, "STOCK")          # sin precio: la noche 1 fallan
        with mock.patch("velas_diarias.TANDA", 4):
            main._run_velas_diarias_job()
            self.assertEqual(self._estado("FA0")["fallas_seguidas"], 1)
            for t in fallados:
                self.yahoo.precios[t] = lambda d: 7.0     # existen: aquello fue un corte
            real, n, cortado = self.yahoo, [0], {"si": False}

            def yahoo(ticker, period, interval, auto_adjust, timeout):
                n[0] += 1
                if n[0] > 8:                              # S&P 500 + 7: después, Yahoo corta
                    cortado["si"] = True
                return pd.DataFrame() if cortado["si"] else real(ticker, period, interval, auto_adjust, timeout)

            def dormir(seg):
                cortado["si"], n[0] = False, -1000
            with mock.patch("pricing.yahoo._historia", yahoo), mock.patch("velas_diarias._dormir", dormir):
                main._run_velas_diarias_job()
        noche = self._ultima_noche()
        self.assertEqual((noche["pausas"], noche["sin_datos"]), (1, 0))
        for t in fallados:
            self.assertEqual((self._estado(t)["ok"], self._estado(t)["fallas_seguidas"]), (1, 0), t)
        self.assertTrue(all(self._estado(t)["ok"] for t in buenos))

    def test_c1_si_el_canario_contesta_la_falla_es_de_verdad(self):
        self._broker("Schwab", "USD")
        for t in ("NOA", "NOB", "NOC", "NOD"):
            self._posicion("Schwab", t, "STOCK")          # no existen en Yahoo
        with mock.patch("velas_diarias.TANDA", 2), mock.patch("velas_diarias._dormir") as dormir:
            main._run_velas_diarias_job()
        dormir.assert_not_called()
        self.assertEqual(self._ultima_noche()["sin_datos"], 4)
        self.assertEqual(self._estado("NOA")["fallas_seguidas"], 1)

    def test_c2_lo_que_tarda_no_es_una_falla(self):
        tickers = self._cartera_de(2)
        main._run_velas_diarias_job()
        real = self.yahoo

        def lento(ticker, period, interval, auto_adjust, timeout):
            if ticker == "T01":
                time.sleep(1.0)
            return real(ticker, period, interval, auto_adjust, timeout)
        with mock.patch("pricing.yahoo._historia", lento), mock.patch("velas_diarias.TOPE_TANDA_SEG", 0.3):
            main._run_velas_diarias_job()
        time.sleep(1.0)                                   # que termine el pedido lento
        e = self._estado("T01")
        self.assertEqual((e["ok"], e["fallas_seguidas"]), (1, 0), "tardar no es «no existe»")
        n = self._ultima_noche()
        self.assertEqual((n["demorados"], n["sin_datos"]), (1, 0))
        self.assertTrue(all(self._estado(t)["ok"] for t in tickers))

    def test_c3_si_la_bajada_entera_vuelve_vacia_se_pide_el_ultimo_mes(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        main._run_velas_diarias_job()
        real = self.yahoo

        def sin_cinco_anios(ticker, period, interval, auto_adjust, timeout):
            if ticker == "MSFT" and period == velas_diarias.PERIODO_COMPLETO:
                return pd.DataFrame()
            return real(ticker, period, interval, auto_adjust, timeout)
        with mock.patch("pricing.yahoo._historia", sin_cinco_anios):
            for k in range(3):                            # tres noches en que le toca la entera
                self._completa_hace(46, "MSFT")
                self._borrar_desde("MSFT", _ruedas(self.hoy, 2)[0])
                main._run_velas_diarias_job()
                e = self._estado("MSFT")
                self.assertEqual((e["ok"], e["fallas_seguidas"]), (1, 0), f"noche {k + 1}")
                self.assertEqual(self._velas("MSFT")[-1]["date"], _ruedas(self.hoy, 1)[0].isoformat(),
                                 "la vela no se congela")
        self.assertEqual(self._ultima_noche()["completas_por_el_mes"], 1)
        self.assertEqual(len(self._velas("MSFT")), self.completa, "lo guardado sigue entero")

    def _borrar_desde(self, ticker, d):
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol=? AND date>=?", (ticker, d.isoformat()))
            conn.commit()

    def test_c4_forzar_los_5_anios_de_2500_se_reparte_en_noches_y_despues_cada_uno_en_su_dia(self):
        # Al publicar se fuerzan los 5 años: `ultima_completa` en NULL para todos.
        # Sin tope, los 2.500 pedían 5 años la misma noche y quedaban con la misma
        # fecha: cada 30 días, todos juntos otra vez.
        hoy = date(2026, 11, 2)
        ts = [f"F{i:04d}" for i in range(2500)]
        with main.db_abierta() as conn:
            conn.executemany("INSERT INTO velas_estado (symbol, ultima_corrida, ultima_completa, ok, filas, "
                             "fallas_seguidas) VALUES (?, '2026-11-01 03:00:00', NULL, 1, 3, 0)",
                             [(t,) for t in ts])
            conn.commit()
        df = _tabla({d: (10.0, 10.1, 9.9, 10.0, 1.0) for d in _ruedas(hoy, 3)})
        por_noche, enteras = [], set()

        def noche(k):
            dia = hoy + timedelta(days=k)
            cuenta = {}

            def bajar(t, periodo):
                cuenta[periodo] = cuenta.get(periodo, 0) + 1
                if periodo == velas_diarias.PERIODO_COMPLETO:
                    enteras.add(t)
                return df
            reloj = datetime(dia.year, dia.month, dia.day, 3, 0)
            with mock.patch("velas_diarias._ahora_utc", lambda: reloj), main.db_abierta() as conn:
                velas_diarias.actualizar(conn, ts, bajar=bajar, hoy=dia.isoformat(), semanal=True, podar=False)
                faltan = conn.execute("SELECT COUNT(*) AS n FROM velas_estado "
                                      "WHERE ultima_completa IS NULL").fetchone()["n"]
            return cuenta.get(velas_diarias.PERIODO_COMPLETO, 0), cuenta.get("1mo", 0), faltan
        for k in range(4):
            por_noche.append(noche(k))
        self.assertEqual(por_noche, [(700, 1800, 1800), (700, 1800, 1100), (700, 1800, 400), (400, 2100, 0)],
                         "4 noches, nunca más de COMPLETAS_POR_DIA enteras por noche")
        # Después, cada uno en su día: antes de los 15 días no toca a nadie, y
        # del día 15 al 47 cada uno tiene su bajada entera del mes sin que
        # ninguna noche junte más que una fracción (antes: 2.500 el día 30).
        self.assertEqual(noche(10)[0], 0)
        enteras.clear()
        siguientes = [noche(k)[0] for k in range(15, 48)]
        self.assertEqual(len(enteras), 2500, "todos tuvieron su bajada entera del mes")
        self.assertLessEqual(max(siguientes), 200, siguientes)

    def test_c5_una_bajada_entera_cortada_no_borra_lo_guardado(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        main._run_velas_diarias_job()
        ultimas = _ruedas(self.hoy, 10)
        cortada = lambda ticker, period, interval, auto_adjust, timeout: _tabla(
            {d: (400.0, 404.0, 396.0, 400.0, 1.0) for d in ultimas})
        self._completa_hace(46, "MSFT")
        with mock.patch("pricing.yahoo._historia", cortada):
            main._run_velas_diarias_job()
        self.assertEqual(len(self._velas("MSFT")), self.completa, "no quedan sólo las últimas 10")
        self.assertEqual(self._estado("MSFT")["ultima_completa"],
                         (self.hoy - timedelta(days=46)).isoformat() + " 03:00:00",
                         "no cuenta como bajada entera: la marca quedó como estaba")
        self.assertEqual(self._ultima_noche()["completas_cortadas"], 1)
        # Con un split sí se reemplaza aunque venga corta: mezclar escalas es peor.
        partida = lambda ticker, period, interval, auto_adjust, timeout: _tabla(
            {d: (100.0, 101.0, 99.0, 100.0, 1.0) for d in ultimas})
        with mock.patch("pricing.yahoo._historia", partida):
            main._run_velas_diarias_job()
        self.assertEqual({v["close"] for v in self._velas("MSFT")}, {100.0})

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

    # — Un '.BA' que Yahoo trae clavado se corrige con BYMA —
    # DISN.BA quedó en 10.416 sin volumen desde el 24/05/2024 (601 ruedas) con BYMA
    # en 16.200 (medido el 05 y el 06/11/2026). Los días de la racha salen de la
    # historia de BYMA (data912) antes de guardar. Varias pruebas de acá las escribió
    # la auditoría del 06/11 (los errores plantados que ninguna prueba veía).

    def _disney_clavado(self, ruedas: int = 300, byma=lambda c: c, operado=True):
        """Disney en IOL (CEDEAR). Yahoo deja DISN.BA clavado desde `ruedas` ruedas
        antes del final; BYMA tiene el precio de verdad de cada día (`byma(c)`: para
        darlo en otra escala; sin `operado`, BYMA no tiene los días de la racha).
        Devuelve ({fecha: cierre de verdad} hasta ayer, el día en que se clavó)."""
        self._broker("IOL", "ARS")
        self._posicion("IOL", "DISN", "CEDEAR")
        dias = [d.isoformat() for d in _ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO)]
        real = {f: 10000.0 + 10 * i for i, f in enumerate(dias + [self.hoy.isoformat()])}
        corte = dias[-ruedas]

        def yahoo(d):
            f = d.isoformat()
            return real[f] if f <= corte else (real[corte], 0.0)
        self.yahoo.precios["DISN.BA"] = yahoo
        self.yahoo.precios["DIS"] = lambda d: 100.0
        self.historia_byma["DISN"] = [
            {"date": f, "o": byma(c), "h": byma(c) * 1.01, "l": byma(c) * 0.99, "c": byma(c), "v": 500.0}
            for f, c in sorted(real.items()) if operado or f <= corte]
        return {f: real[f] for f in dias}, corte

    def _cierres(self, ticker):
        return {v["date"]: v["close"] for v in self._velas(ticker)}

    def _pedidos_de(self, ticker):
        return [p[1] for p in self.yahoo.pedidos if p[0] == ticker]

    def _mes(self):
        """Las ruedas que trae la bajada de cada noche (el último mes)."""
        return [d.isoformat() for d in _ruedas(self.hoy, 22)]

    def _destrabado_desde(self, real, desde):
        """Yahoo se destrabó: desde `desde` trae el precio de verdad, con volumen; lo
        de antes sigue como estaba (clavado): Yahoo no reescribe lo de atrás."""
        viejo = self.yahoo.precios["DISN.BA"]
        self.yahoo.precios["DISN.BA"] = lambda d: real.get(d.isoformat(), 1.0) if d.isoformat() >= desde else viejo(d)

    def test_un_ba_que_yahoo_trae_clavado_se_guarda_con_los_precios_de_byma(self):
        real, corte = self._disney_clavado()
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA"), real, "cada día de la racha, el cierre de BYMA")
        velas = {v["date"]: v for v in self._velas("DISN.BA")}
        dia = next(f for f in sorted(velas) if f > corte)
        c = real[dia]
        self.assertEqual((velas[dia]["open"], velas[dia]["high"], velas[dia]["low"], velas[dia]["volume"]),
                         (c, c * 1.01, c * 0.99, 500.0), "la vela entera de BYMA, con su volumen")
        self.assertEqual(velas[corte]["volume"], 1000.0, "el primer día (operado) queda como lo dio Yahoo")
        self.assertEqual(self.pedidos_byma, ["DISN"], "una vez, por la dirección de los CEDEARs")
        noche = self._ultima_noche()
        self.assertEqual((noche["corregidos_con_byma"], noche["dias_corregidos_con_byma"]), (1, 299))
        # La ficha en pesos (por HTTP, como la pantalla) dibuja el precio de BYMA.
        r = self.client.get("/api/tecnico/DISN?moneda=ars", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["ticker"], r.json()["puntos"][-1]["c"]), ("DISN.BA", real[max(real)]))

    def test_la_noche_siguiente_no_vuelve_a_bajar_la_historia_entera(self):
        # Lo corregido no es «la historia cambió» (`_historia_reescrita`): si no, se
        # bajaba entera cada noche y la bajada entera la volvía a clavar.
        real, _ = self._disney_clavado()
        main._run_velas_diarias_job()
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos_de("DISN.BA"), ["1mo"])
        self.assertEqual(self._cierres("DISN.BA"), real)

    def test_lo_que_quedo_guardado_clavado_se_arregla_la_noche_siguiente(self):
        # Así está DISN.BA hoy en la base. La noche de antes data912 no tenía DISN y
        # se guardó lo de Yahoo, clavado; la siguiente, el último mes corregido no
        # coincide con lo guardado: se baja la historia entera y se corrige entera.
        real, corte = self._disney_clavado()
        historia = self.historia_byma.pop("DISN")
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA")[max(real)], real[corte], "lo de Yahoo, clavado")
        self.historia_byma["DISN"] = historia
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos_de("DISN.BA"), ["1mo", "5y"])
        self.assertEqual(self._cierres("DISN.BA"), real)

    def test_si_data912_no_contesta_no_se_pisa_lo_corregido(self):
        real, _ = self._disney_clavado()
        main._run_velas_diarias_job()
        self.byma_cae = True
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA"), real, "lo corregido sigue")
        self.assertEqual(self._pedidos_de("DISN.BA"), ["1mo"], "sin bajarla entera")
        self.assertEqual(self._ultima_noche()["byma_sin_respuesta"], 1)
        self.byma_cae = False
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA"), real)

    def test_si_data912_no_contesta_varios_dias_la_serie_sigue_al_dia(self):
        # Antes el papel no se guardaba mientras data912 no contestaba: a los
        # `tecnico.DIAS_ATRASO` días la ficha en pesos pasaba a la acción de afuera ×
        # el MEP, que es la acción ENTERA en pesos (~10 veces el CEDEAR; auditoría del
        # 06/11). Lo nuevo va con el último precio de verdad, sin volumen.
        real, _ = self._disney_clavado()
        main._run_velas_diarias_job()
        ultimos = sorted(real)[-6:]
        self._borrar_desde("DISN.BA", date.fromisoformat(ultimos[0]))   # la última noche fue hace 6 ruedas
        self.byma_cae = True
        main._run_velas_diarias_job()
        guardado = self._cierres("DISN.BA")
        antes = sorted(real)[-7]
        self.assertEqual({f: guardado[f] for f in ultimos}, {f: real[antes] for f in ultimos},
                         "al día, con el último precio de verdad (no el clavado)")
        r = self.client.get("/api/tecnico/DISN?moneda=ars", headers=self.h)
        self.assertEqual((r.json()["ticker"], r.json()["convertida"]), ("DISN.BA", None),
                         "el CEDEAR, no la acción entera en pesos")
        self.byma_cae = False
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA"), real, "con data912 de vuelta, se corrige")

    def test_si_byma_esta_en_otra_escala_no_se_mezcla(self):
        # data912 corrige algunos cambios de ratio viejos (AAPL en 2024): su historia
        # en otra escala no se pega a la de Yahoo. Y la noche siguiente tampoco: si
        # no, cada noche «la historia cambió» y se bajaba entera.
        real, corte = self._disney_clavado(byma=lambda c: c / 2)
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA")[max(real)], real[corte])
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos_de("DISN.BA"), ["1mo"])
        self.assertEqual(self._cierres("DISN.BA")[max(real)], real[corte])

    def test_un_papel_que_no_se_opero_queda_como_lo_dio_yahoo(self):
        # Sin operaciones en BYMA esos días, el mismo cierre sin volumen es la verdad.
        real, corte = self._disney_clavado(operado=False)
        main._run_velas_diarias_job()
        guardado = self._cierres("DISN.BA")
        self.assertEqual({guardado[f] for f in guardado if f >= corte}, {real[corte]})
        self.assertEqual(self.pedidos_byma, ["DISN"], "se miró BYMA")
        self.assertEqual(self._ultima_noche().get("corregidos_con_byma"), 0)

    def test_lo_que_se_opera_no_le_pide_nada_a_byma(self):
        # Una racha necesita el mismo cierre SIN volumen: un precio quieto que se opera
        # (GGAL.BA a 6.000 con volumen) no es un dato muerto, y no le pide nada a data912.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self.yahoo.precios["GGAL.BA"] = lambda d: 6000.0
        main._run_velas_diarias_job()
        self.assertEqual(self.pedidos_byma, [])

    def test_una_racha_vieja_que_nunca_se_corrigio_queda_como_la_dio_yahoo(self):
        # Una racha que TERMINÓ hace mucho y nunca se corrigió queda como la dio
        # Yahoo, sin pedirle nada a data912: corregir días al lado de un cambio de
        # ratio le cambia el factor (AMD: de ×20, el de verdad, a ×19). Tampoco si la
        # bajada entera del mes la trae con otro redondeo, ni si Yahoo corrige un
        # día suelto de ella: eso no es «ya corregida».
        self._broker("IOL", "ARS")
        self._posicion("IOL", "DISN", "CEDEAR")
        dias = [d.isoformat() for d in _ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO)]
        real = {f: 10000.0 + 10 * i for i, f in enumerate(dias + [self.hoy.isoformat()])}
        desde, hasta = dias[-500], dias[-400]
        clavado = {"c": real[desde], "suelto": None}

        def yahoo(d):
            f = d.isoformat()
            if f == clavado["suelto"]:
                return clavado["c"] * 1.001, 0.0
            return (clavado["c"], 0.0) if desde < f <= hasta else real[f]
        self.yahoo.precios["DISN.BA"] = yahoo
        self.yahoo.precios["DIS"] = lambda d: 100.0
        self.historia_byma["DISN"] = [{"date": f, "o": c, "h": c, "l": c, "c": c, "v": 500.0}
                                      for f, c in sorted(real.items())]
        main._run_velas_diarias_job()
        clavado["c"], clavado["suelto"] = real[desde] * 1.000001, dias[-450]
        self._completa_hace(46, "DISN.BA")
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos_de("DISN.BA"), ["5y"], "le tocaba la bajada entera del mes")
        guardado = self._cierres("DISN.BA")
        self.assertNotIn(real[dias[-420]], guardado.values(), "la racha sigue con lo de Yahoo")
        self.assertEqual(self.pedidos_byma, [], "una racha vieja nunca corregida no se mira")

    def test_una_racha_vieja_no_se_corrige_aunque_el_papel_este_clavado_hoy(self):
        # El mismo papel estuvo clavado hace años (nunca se corrigió) y lo está otra
        # vez: se le pide BYMA por la racha de hoy, y la vieja igual queda como la dio
        # Yahoo (la regla de AMD).
        real, corte = self._disney_clavado(ruedas=50)
        dias = sorted(real)
        desde, hasta = dias[-500], dias[-400]
        hoy_clavado = self.yahoo.precios["DISN.BA"]
        self.yahoo.precios["DISN.BA"] = lambda d: (real[desde], 0.0) if desde < d.isoformat() <= hasta \
            else hoy_clavado(d)
        main._run_velas_diarias_job()
        guardado = self._cierres("DISN.BA")
        self.assertEqual({guardado[f] for f in dias if desde <= f <= hasta}, {real[desde]}, "la vieja, como Yahoo")
        self.assertEqual({f: guardado[f] for f in dias if f > corte}, {f: real[f] for f in dias if f > corte},
                         "la de hoy, con BYMA")

    def test_cuando_yahoo_se_destraba_la_bajada_entera_del_mes_no_la_vuelve_a_clavar(self):
        real, _ = self._disney_clavado()
        main._run_velas_diarias_job()
        self._destrabado_desde(real, sorted(real)[-30])
        self._completa_hace(46, "DISN.BA")
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos_de("DISN.BA"), ["5y"])
        self.assertEqual(self._cierres("DISN.BA"), real)

    def test_cuando_yahoo_se_destraba_la_cola_de_la_racha_no_vuelve_a_lo_clavado(self):
        # Noche tras noche, la bajada del mes trae cada vez menos días de la racha
        # vieja al principio (4, 3, 2, 1): ya no son una racha, y con 2 o menos ni
        # siquiera «la historia cambió». Antes esos días volvían al precio clavado
        # (−35 % en Disney) hasta la bajada entera del mes, y con 3 o 4 se bajaba la
        # historia entera cada noche (HARG real: 23 veces en 239 noches).
        real, _ = self._disney_clavado()
        clavado = self.yahoo.precios["DISN.BA"]
        main._run_velas_diarias_job()
        mes = self._mes()
        for k in (4, 3, 2, 1):
            with self.subTest(dias_clavados=k):
                self.yahoo.precios["DISN.BA"] = clavado
                self._destrabado_desde(real, mes[k])
                self.yahoo.pedidos.clear()
                main._run_velas_diarias_job()
                self.assertEqual(self._pedidos_de("DISN.BA"), ["1mo"], "sin bajarla entera")
                self.assertEqual(self._cierres("DISN.BA"), real)

    def test_los_dias_que_byma_no_tiene_van_con_su_ultimo_cierre(self):
        # Un papel poco operado: data912 tiene filas sólo los días con operaciones
        # (POLL: 20 días seguidos sin una). Esos días van con el último cierre de
        # BYMA, aunque sea de hace más de una semana, nunca con lo clavado de Yahoo
        # en el medio de lo corregido: eso armaba escalones falsos que la lista de
        # cambios de ratio podía dar por un cambio de cantidad.
        real, corte = self._disney_clavado()
        dias = sorted(real)
        hueco = dias[-100:-92]                       # 8 ruedas, más de 10 días corridos
        self.historia_byma["DISN"] = [f for f in self.historia_byma["DISN"] if f["date"] not in hueco]
        main._run_velas_diarias_job()
        guardado = self._cierres("DISN.BA")
        self.assertEqual({f: guardado[f] for f in hueco}, {f: real[dias[-101]] for f in hueco})

    def test_una_racha_que_empieza_adentro_del_mes(self):
        # Una noche Yahoo anda; otra trae las últimas 3 ruedas clavadas (todavía no es
        # racha); otra, las últimas 6: la racha empieza adentro del mes.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "DISN", "CEDEAR")
        dias = [d.isoformat() for d in _ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO)]
        real = {f: 16000.0 * (1.01 ** (i % 7)) for i, f in enumerate(dias + [self.hoy.isoformat()])}
        self.yahoo.precios["DIS"] = lambda d: 100.0
        self.historia_byma["DISN"] = [{"date": f, "o": c, "h": c, "l": c, "c": c, "v": 500.0}
                                      for f, c in sorted(real.items())]
        self.yahoo.precios["DISN.BA"] = lambda d: real[d.isoformat()]
        main._run_velas_diarias_job()

        def clavado_desde(corte):
            self.yahoo.precios["DISN.BA"] = lambda d: real[d.isoformat()] if d.isoformat() <= corte \
                else (real[corte], 0.0)
        clavado_desde(dias[-4])
        main._run_velas_diarias_job()
        clavado_desde(dias[-7])
        main._run_velas_diarias_job()
        self.assertEqual({f: self._cierres("DISN.BA")[f] for f in dias[-7:]}, {f: real[f] for f in dias[-7:]})

    def test_una_accion_argentina_clavada_se_corrige_con_la_historia_de_acciones(self):
        # data912 tiene una dirección para acciones y otra para CEDEARs: una acción
        # argentina se pide por la suya, de noche y en la ficha a pedido (alguien abre
        # la de algo que nadie sigue: `velas_diarias.asegurar`).
        dias = [d.isoformat() for d in _ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO)]
        real = {f: 5000.0 + 5 * i for i, f in enumerate(dias + [self.hoy.isoformat()])}
        corte = dias[-50]
        self.yahoo.precios["GGAL.BA"] = lambda d: real[d.isoformat()] if d.isoformat() <= corte \
            else (real[corte], 0.0)
        filas = [{"date": f, "o": c, "h": c, "l": c, "c": c, "v": 10.0} for f, c in sorted(real.items())]
        pedidos = []

        def _data912(tipo, papel, timeout=10):
            pedidos.append((tipo, papel))
            return filas if (tipo, papel) == ("stocks", "GGAL") else []
        with mock.patch("pricing.data912.filas", _data912):
            r = self.client.get("/api/tecnico/GGAL.BA?moneda=ars&local=1", headers=self.h)   # a pedido
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["puntos"][-1]["c"], real[dias[-1]])
            self.assertEqual(pedidos, [("stocks", "GGAL")])
            self._broker("IOL", "ARS")
            self._posicion("IOL", "GGAL", "ACCION")
            self._borrar_desde("GGAL.BA", date.fromisoformat(dias[-3]))           # la noche: lo que falta
            main._run_velas_diarias_job()
        self.assertEqual(self._cierres("GGAL.BA"), {f: real[f] for f in dias})
        self.assertEqual(pedidos, [("stocks", "GGAL")] * 2, "una vez a pedido y una de noche")

    def test_un_cambio_de_ratio_adentro_de_la_racha_queda_a_la_vista(self):
        # data912 guarda el cierre como fue cada día: un cambio de ratio en medio de la
        # racha (cada CEDEAR pasa a valer la mitad) queda en lo guardado, y la lista
        # de cambios de ratio lo empalma en el gráfico, como uno de cualquier CEDEAR.
        real, corte = self._disney_clavado()
        dias = sorted(real)
        cambio = dias[-100]
        verdad = {f: (c / 2 if f >= cambio else c) for f, c in real.items()}
        self.historia_byma["DISN"] = [{"date": f, "o": c, "h": c, "l": c, "c": c, "v": 500.0}
                                      for f, c in sorted(verdad.items())]
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            crudo = {r["date"]: r["close"] for r in conn.execute(
                "SELECT date, close FROM velas_diarias WHERE symbol='DISN.BA'").fetchall()}
            import tecnico
            dibujado = {v["date"]: v["close"] for v in tecnico.serie(conn, "DISN", "ars")["velas"]}
        self.assertEqual(crudo, verdad, "lo guardado es lo de BYMA de cada día")
        anterior = max(f for f in dibujado if f < cambio)
        self.assertAlmostEqual(dibujado[cambio] / dibujado[anterior], 1.0, delta=0.01,
                               msg="el gráfico en pesos empalma el cambio de ratio")

    def test_no_se_espera_a_data912_con_una_escritura_abierta(self):
        # Como `test_split_que_yahoo_ajusta_tarde` con Yahoo: mientras se espera a
        # data912, otro tiene que poder escribir.
        real, _ = self._disney_clavado()
        libre, historia = [], self.historia_byma["DISN"]

        def _data912(tipo, papel, timeout=10):
            c = sqlite3.connect(main.DB_PATH, timeout=0)
            try:
                c.execute("BEGIN IMMEDIATE")
                c.rollback()
                libre.append(True)
            except sqlite3.OperationalError:
                libre.append(False)
            finally:
                c.close()
            return historia if papel == "DISN" else []
        with mock.patch("pricing.data912.filas", _data912):
            main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA"), real)
        self.assertTrue(libre and all(libre), f"base tomada mientras se espera a data912: {libre}")

    def test_en_postgres_no_queda_una_transaccion_abierta_mientras_se_espera_a_data912(self):
        if not main.USANDO_PG:
            self.skipTest("sólo Postgres")
        import pgsesion
        real, _ = self._disney_clavado()
        vistas, historia = [], self.historia_byma["DISN"]

        def _data912(tipo, papel, timeout=10):
            with pgsesion.conectar(main.DATABASE_URL, autocommit=True) as c:
                vistas.append(c.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND state LIKE 'idle in transaction%%' AND pid <> pg_backend_pid()").fetchone()[0])
            return historia if papel == "DISN" else []
        with mock.patch("pricing.data912.filas", _data912):
            main._run_velas_diarias_job()
        self.assertEqual(self._cierres("DISN.BA"), real)
        self.assertTrue(vistas and not any(vistas), f"transacciones abiertas mientras se espera: {vistas}")

    def _clavados_al_final(self, casos: dict):
        """{papel: (ruedas clavadas al final, BYMA = verdad × esto)}: CEDEARs en IOL
        cuyo '.BA' Yahoo trae clavado sus últimas ruedas. {papel: verdad}."""
        self._broker("IOL", "ARS")
        dias = [d.isoformat() for d in _ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO)]
        verdades = {}
        for papel, (n, escala) in casos.items():
            self._posicion("IOL", papel, "CEDEAR")
            real = {f: 1000.0 + i for i, f in enumerate(dias + [self.hoy.isoformat()])}
            corte = dias[-n - 1]
            self.yahoo.precios[f"{papel}.BA"] = (lambda real, corte: lambda d: real[d.isoformat()]
                                                 if d.isoformat() <= corte else (real[corte], 0.0))(real, corte)
            self.historia_byma[papel] = [{"date": f, "o": c * escala, "h": c * escala, "l": c * escala,
                                          "c": c * escala, "v": 5.0} for f, c in sorted(real.items())]
            verdades[papel] = {f: real[f] for f in dias}
        return verdades

    def test_una_racha_son_4_ruedas_clavadas_despues_de_una_operada(self):
        # `RACHA_CLAVADA`: la rueda operada y 4 iguales sin volumen ya es una racha;
        # con 3 todavía no (puede no haberse operado).
        v = self._clavados_al_final({"AAPL": (4, 1.0), "MSFT": (3, 1.0)})
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("AAPL.BA"), v["AAPL"])
        self.assertEqual(self._cierres("MSFT.BA")[max(v["MSFT"])], v["MSFT"][sorted(v["MSFT"])[-4]])

    def test_byma_tiene_que_dar_lo_mismo_el_ultimo_dia_de_verdad(self):
        # `TOLERANCIA_BYMA`: a 3 % del último precio de verdad es la misma escala; a 8 %
        # no (data912 en otra escala no se pega a la de Yahoo).
        v = self._clavados_al_final({"AAPL": (10, 1.03), "MSFT": (10, 1.08)})
        main._run_velas_diarias_job()
        aapl, msft = self._cierres("AAPL.BA"), self._cierres("MSFT.BA")
        self.assertAlmostEqual(aapl[max(aapl)], v["AAPL"][max(aapl)] * 1.03)
        self.assertEqual(msft[max(msft)], v["MSFT"][sorted(v["MSFT"])[-11]], "queda lo de Yahoo")

    def test_un_split_que_yahoo_reescribe_en_un_papel_poco_operado_se_aplica(self):
        # Guardián: una acción poco operada (ruedas sin volumen, igual en Yahoo y en
        # BYMA) a la que Yahoo le reescribe la historia por un split (÷ 10) se
        # reescribe como siempre: eso no es «lo corregido en otra escala».
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        dias = [d.isoformat() for d in _ruedas_del_periodo(self.hoy, velas_diarias.PERIODO_COMPLETO)]
        real = {f: 5000.0 + (i // 5) * 10 for i, f in enumerate(dias + [self.hoy.isoformat()])}
        poco = lambda f: dias.index(f) % 5 if f in dias else 0     # de cada 5 ruedas, 4 sin operar
        self.yahoo.precios["GGAL.BA"] = lambda d: (real[d.isoformat()], 0.0) if poco(d.isoformat()) \
            else real[d.isoformat()]
        self.historia_byma["GGAL"] = [{"date": f, "o": c, "h": c, "l": c, "c": c, "v": 1.0}
                                      for f, c in sorted(real.items()) if not poco(f)]
        main._run_velas_diarias_job()
        self.assertEqual(self._cierres("GGAL.BA"), {f: real[f] for f in dias})
        self.yahoo.precios["GGAL.BA"] = lambda d: (real[d.isoformat()] / 10, 0.0) if poco(d.isoformat()) \
            else real[d.isoformat()] / 10
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos_de("GGAL.BA"), ["1mo", "5y"])
        self.assertEqual(self._cierres("GGAL.BA"), {f: real[f] / 10 for f in dias}, "la historia reescrita")

    def _yahoo_reescribe_a_la_mitad(self, real):
        """Yahoo reescribe la historia de DISN.BA por un split (todo ÷ 2), con la
        racha vieja (clavada) adentro, y ya se destrabó hace 30 ruedas. La última
        noche fue hace 2 ruedas: hay 2 días nuevos."""
        destrabe, viejo = sorted(real)[-30], self.yahoo.precios["DISN.BA"]

        def partido(d):
            v = real.get(d.isoformat(), 1.0) if d.isoformat() >= destrabe else viejo(d)
            return (v[0] / 2, v[1]) if isinstance(v, tuple) else v / 2
        self.yahoo.precios["DISN.BA"] = partido
        nuevos = sorted(real)[-2:]
        self._borrar_desde("DISN.BA", date.fromisoformat(nuevos[0]))
        return nuevos

    def test_un_split_de_yahoo_sobre_lo_corregido_no_mezcla_escalas(self):
        # Lo corregido está en la escala de BYMA y Yahoo pasó a otra: no se mezclan
        # (eso arma un escalón ×2 que la lista de cambios de ratio daría por un cambio
        # de cantidad), ni se pierde lo corregido. Lo nuevo sale de BYMA.
        real, _ = self._disney_clavado()
        main._run_velas_diarias_job()
        self._yahoo_reescribe_a_la_mitad(real)
        self.yahoo.pedidos.clear()
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos_de("DISN.BA"), ["1mo", "5y"])
        self.assertEqual(self._cierres("DISN.BA"), real, "lo corregido queda, y lo nuevo es de BYMA")
        self.assertEqual(self._ultima_noche()["byma_otra_escala"], 1)

    def test_un_split_de_yahoo_con_data912_caido_no_pisa_lo_corregido(self):
        real, _ = self._disney_clavado()
        main._run_velas_diarias_job()
        nuevos = self._yahoo_reescribe_a_la_mitad(real)
        self.byma_cae = True
        main._run_velas_diarias_job()
        guardado = self._cierres("DISN.BA")
        antes = sorted(real)[-3]
        self.assertEqual({f: guardado[f] for f in guardado if f < nuevos[0]},
                         {f: real[f] for f in real if f < nuevos[0]}, "lo corregido queda")
        self.assertEqual({guardado[f] for f in nuevos}, {real[antes]},
                         "lo nuevo, con el último precio de verdad: ni ÷ 2 ni clavado")
        self.assertEqual(self._ultima_noche()["byma_sin_respuesta"], 1)

    def test_si_la_foto_diaria_falla_las_velas_corren_igual(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda d: 400.0
        with mock.patch("main.run_daily_snapshot", side_effect=RuntimeError("foto rota")):
            main._run_daily_snapshot_job()
        self.assertEqual(len(self._velas("MSFT")), self.completa)


if __name__ == "__main__":
    unittest.main()
