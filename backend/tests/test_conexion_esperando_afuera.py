"""Mientras se espera a Yahoo o a data912, el pedido no se queda con ninguna
conexión a la base tomada (fuera de la descarga a pedido de velas, que prueba
test_velas_a_pedido.py).

POR QUÉ. En Postgres hay 10 conexiones por copia de la app (`pgshim._Pozo`).
Medido el 05/11/2026 (audit/_scripts/medir_conexion_esperando_yahoo.py): 8
pantallas esperando a Yahoo tenían 8 de las 10 prestadas sin hacer nada, y con
otras 2 ocupadas un pedido liviano —chequear la sesión de cualquiera— esperó
7,6 s. El barrido de ese día encontró el mismo patrón en más de 70 lugares: la
ruta abre la base para el bloque entero y, varias funciones más abajo, algo
espera a la red. El arreglo está en las PUERTAS a la red (`pricing.yahoo`,
`pricing.data912`, data912 en vivo, la espera de los eventos): antes de esperar,
sueltan las conexiones del hilo (`pgsesion.antes_de_esperar_afuera`).

Cada prueba entra por HTTP, como la pantalla, y la red se reemplaza en su punto
más bajo (lo que de verdad sale a Yahoo o a data912). En cada espera se anota
cuántas conexiones DEL PEDIDO estaban tomadas: en SQLite con `_Contada` (simula
el pozo), en Postgres además si la conexión de verdad tenía su lugar del pozo.
Tienen que ser 0. Y dos que esperaban con una ESCRITURA abierta, que soltar no
arregla: ajustar el ratio de un lote (con el turno de la cuenta tomado) y los
cambios de ratio de varios papeles.

Las del pedido: las que abrieron los hilos que atienden la pantalla y las del
hilo que espera. No las de otros hilos: en el chat, un trabajo en paralelo
guarda los últimos precios conocidos (`_flush_last_prices_si_toca`) justo
mientras otro hilo espera a data912, y contarla daba un rojo falso (medido el
05/11 en Postgres; esa conexión no espera nada: escribe y cierra). Cuando ésos
esperan, su propia puerta los suelta.

Corre con: cd backend && python3 -m pytest tests/test_conexion_esperando_afuera.py
"""
import os
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, time, timedelta
from types import SimpleNamespace
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
import pgsesion
import snapshots_job
import velas_diarias
from fechas import hoy_art_date
from tests.test_lectura_tecnica_chat import ClaudeDelChat
from tests.test_tecnico import YahooFalso, _ruedas
from tests.test_variacion_una_fuente import _Resp, _vaciar_caches
from tests.test_velas_a_pedido import _Contada

# data912 en vivo, con la forma de su API (ver test_variacion_una_fuente).
DATA912_EN_VIVO = {
    "arg_cedears": [{"symbol": "AAPL", "c": 27300.0, "pct_change": 0.74, "v": 3.1e8},
                    {"symbol": "KO", "c": 18000.0, "pct_change": 0.10, "v": 1e7}],
    "arg_stocks": [{"symbol": "GGAL", "c": 5850.0, "pct_change": -2.50, "v": 2.2e9},
                   {"symbol": "YPFD", "c": 40000.0, "pct_change": 1.00, "v": 1e9}],
    "arg_bonds": [{"symbol": "AL30", "c": 86200.0, "pct_change": 0.47, "v": 7.4e9},
                  {"symbol": "AL30D", "c": 61.38, "pct_change": 0.30, "v": 1.1e6}],
    "arg_corp": [],
}

# Las esperas que se miran: Yahoo y data912 (las otras fuentes no son de esta prueba).
_DE_YAHOO_O_DATA912 = ("yahoo", "data912", "dividendos", "balances", "eventos", "splits",
                       "fundamentales", "turno de Yahoo", "pre/post")


class _TickerFalso:
    """`yfinance.Ticker` de mentira para lo que va a Yahoo sin una puerta propia
    en esta prueba (los benchmarks, los días de BYMA): anota la espera como
    «yahoo directo» y devuelve poco. Así nada sale a la red de verdad."""
    anotar = None

    def __init__(self, ticker, *a, **k):
        self.ticker = ticker

    def _anotar(self):
        if _TickerFalso.anotar:
            _TickerFalso.anotar("yahoo directo", self.ticker)

    def history(self, *a, **k):
        self._anotar()
        idx = pd.DatetimeIndex([pd.Timestamp("2026-08-31"), pd.Timestamp("2026-09-30"), pd.Timestamp("2026-10-30")])
        return pd.DataFrame({"Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0, "Volume": 1000.0},
                            index=idx)

    @property
    def splits(self):
        self._anotar()
        return pd.Series(dtype=float)

    dividends = splits

    @property
    def info(self):
        self._anotar()
        return {}

    @property
    def fast_info(self):
        self._anotar()
        return SimpleNamespace(previous_close=None, last_price=None)

    def get_earnings_dates(self, *a, **k):
        self._anotar()
        return None


class _Base(unittest.TestCase):
    """Ana (Pro, para que ninguna pantalla se corte por el plan), con una cuenta
    en pesos y otra en dólares, y su asesora. La red, de mentira; cada espera
    anota (qué, cuántas conexiones tomadas, cuántas prestadas en Postgres,
    cuántas con una escritura abierta)."""

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "splits_yahoo", "watchlist",
                      "positions", "brokers", "operations", "goals", "advisor_clients",
                      "dividendos_emisor", "dividendos_pagados", "financial_events", "yfinance_cache",
                      "fx_rates_daily", "interruptores"):
                conn.execute(f"DELETE FROM {t}")

            def usuario(nombre, tier):
                return conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                                    "VALUES (?, 'x', 1, 1, ?)", (f"{nombre}-{tag}@rendi.test", tier)).lastrowid
            self.ana = usuario("ana", "pro")
            self.asesora = usuario("asesora", "advisor")
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission, status) "
                         "VALUES (?, ?, 'linked', 'read_write', 'active')", (self.asesora, self.ana))
            for nombre, moneda in (("IOL", "ARS"), ("Schwab", "USD")):
                conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, ?)",
                             (self.ana, nombre, moneda))
            conn.commit()
        self.h_ana = {"Authorization": f"Bearer {main.create_token(self.ana)}"}
        self.h_asesora = {"Authorization": f"Bearer {main.create_token(self.asesora)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        for t in ("AAPL", "MSFT", "KO", "GGAL.BA", "YPFD.BA", "^GSPC"):
            self.yahoo.precios[t] = lambda i, d: 100.0
        self.splits_ba, self.splits = {}, {}
        self.tomadas, self.esperas, self.orden = set(), [], []
        self.abiertas_por_el_pedido = 0
        de_verdad = main.get_db

        def abrir():
            c = _Contada(de_verdad(), self.tomadas)
            c.__dict__["_hilo_que_la_abrio"] = threading.current_thread()
            if self._es_del_pedido(threading.current_thread()):
                self.abiertas_por_el_pedido += 1
            return c
        self._p = [mock.patch.object(main, "get_db", abrir),
                   mock.patch("main._check_rate_limit"),
                   mock.patch("main._kick_bench_refresh", lambda: None),
                   mock.patch("requests.get", self._http),
                   mock.patch("pricing.yahoo._historia", self._historia),
                   mock.patch("main._fetch_prev_close_one", self._de_a_uno),
                   mock.patch("main._fetch_one", self._de_a_uno),
                   mock.patch("dividendos._consultar_yahoo", self._dividendos),
                   mock.patch("main._fetch_yf_earnings_pasados", self._balances_pasados),
                   mock.patch("main._fetch_yf_events", self._eventos),
                   mock.patch("main._splits_de_yahoo", self._splits_main),
                   mock.patch("cambios_ratio._splits_de_yahoo", self._splits_cr),
                   mock.patch("fuera_de_horario._pedir_yahoo", self._pre_post),
                   mock.patch("main._ensure_news_batch_parallel", lambda *a, **k: None),
                   mock.patch("yfinance.Ticker", _TickerFalso),
                   mock.patch.object(_TickerFalso, "anotar", staticmethod(self._anotar))]
        for p in self._p:
            p.start()
        self._vaciar()
        self.addCleanup(self._vaciar)

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def _vaciar(self):
        import fuera_de_horario
        from home import market as hm
        _vaciar_caches()
        fuera_de_horario._vaciar_cache()
        main._bench_cache.update({"data": None, "ts": 0.0})
        # Lo que el chat guarda en memoria POR NÚMERO DE USUARIO también: en Postgres
        # cada archivo de pruebas tiene su esquema y los números vuelven a empezar,
        # así que un borrador de compra que quedara acá le aparecía a la persona del
        # mismo número en otro archivo («Registro pendiente: COMPRA…», visto el 05/11
        # en test_lectura_tecnica_chat).
        for c in (main._FUENTE_CAIDA, main._PRICE_CACHE, main._PREVCLOSE_VENCE, main._splits_cache,
                  main._earnings_pasados_at, main._events_fetched_at, main._CHAT_PRECIOS,
                  main._CARTERA_HOY_CACHE, main._CHAT_VAL_CACHE, main._MAPA_DEL_DIA_CACHE,
                  main._TRADE_DRAFT, main._LAST_CHAT_TRADE, main._GROUP_DRAFT,
                  snapshots_job._LIVE_VALUE_CACHE, hm._QUOTE_CACHE, velas_diarias._a_pedido_hechos):
            c.clear()
        main._freno_reiniciar()

    # ── La red de mentira: cada puerta anota la espera ──────────────────────
    @staticmethod
    def _es_del_pedido(hilo) -> bool:
        """Los hilos que atienden la pantalla: los de FastAPI («AnyIO worker») y el
        del bucle. Si cambiaran de nombre, `_mirando` lo dice (no pasa en blanco)."""
        return hilo is not None and hilo.name.startswith(("AnyIO worker", "asyncio"))

    def _del_pedido(self) -> list:
        """Las conexiones tomadas del pedido: las que abrieron los hilos que
        atienden la pantalla y las del hilo que espera ahora. Ver el docstring
        del módulo."""
        yo = threading.current_thread()
        out = []
        for c in list(self.tomadas):
            h = c.__dict__.get("_hilo_que_la_abrio")
            if h is yo or self._es_del_pedido(h):
                out.append(c)
        return out

    def _anotar(self, que, *detalle):
        mias = self._del_pedido()
        # En Postgres, además, si la conexión de verdad tenía su lugar del pozo.
        prestadas = sum(1 for c in mias if main.USANDO_PG and c._real._c is not None)
        abiertas = sum(1 for c in mias if c._real.in_transaction)
        self.esperas.append((que, *detalle, len(mias), prestadas, abiertas))
        self.orden.append(que)

    def _http(self, url, *a, **k):
        if "data912.com/live/" in url:
            self._anotar("data912 en vivo", url.rsplit("/", 1)[1])
            return _Resp(DATA912_EN_VIVO.get(url.rsplit("/", 1)[1], []))
        if "data912.com/historical/" in url:
            self._anotar("data912 historia", url.split("/historical/", 1)[1])
            return _Resp([])
        if "argentinadatos.com/v1/finanzas/indices/inflacion" in url:
            # No es Yahoo ni data912 (no entra en `_mirando`), pero Reportes la
            # espera junto con el S&P 500: la prueba de los benchmarks la mira.
            self._anotar("inflación", url)
        return _Resp([], 404)        # el dólar, la inflación y lo demás: no hay

    def _historia(self, ticker, period, interval, auto_adjust, timeout):
        self._anotar("yahoo", ticker)
        return self.yahoo(ticker, period, interval, auto_adjust, timeout)

    def _de_a_uno(self, *a, **k):
        self._anotar("yahoo de a uno", *a)
        return None

    def _dividendos(self, pedido):
        self._anotar("dividendos", pedido[0])
        return {"pagos": [], "pais": "United States", "tipo": "EQUITY"}

    def _balances_pasados(self, ticker):
        self._anotar("balances pasados", ticker)
        return []

    def _eventos(self, ticker, fallas=None):
        self._anotar("eventos", ticker)
        return []

    def _splits_main(self, ba_symbol):
        self._anotar("splits", ba_symbol)
        lista = self.splits_ba.get(ba_symbol, [])
        return pd.Series([f for _, f in lista], index=pd.DatetimeIndex([d for d, _ in lista]), dtype=float)

    def _splits_cr(self, ticker):
        self._anotar("splits", ticker)
        return list(self.splits.get(ticker, []))

    def _pre_post(self, simbolos):
        self._anotar("pre/post", *simbolos)
        return [{"symbol": s, "marketState": "REGULAR", "regularMarketPrice": 100.0,
                 "regularMarketPreviousClose": 100.0} for s in simbolos]

    # ── Mirar ────────────────────────────────────────────────────────────────
    def _mirando(self, pedir, *debe_esperar):
        """Hace el pedido y verifica que en cada espera a Yahoo o data912 no había
        ninguna conexión tomada. `debe_esperar`: qué esperas tienen que haber
        pasado (si no, la prueba no prueba nada)."""
        del self.esperas[:], self.orden[:]
        self.abiertas_por_el_pedido = 0
        r = pedir()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.abiertas_por_el_pedido,
                        "el pedido no abrió ninguna conexión que la prueba reconozca como suya "
                        "(¿cambió el nombre de los hilos de FastAPI?): no se midió nada")
        mias = [e for e in self.esperas if e[0].startswith(_DE_YAHOO_O_DATA912)]
        for que in debe_esperar:
            self.assertIn(que, [e[0] for e in mias], f"no esperó «{que}»: la prueba no prueba nada")
        tomadas = [e for e in mias if any(e[-3:])]
        self.assertEqual(tomadas, [], "esperas con conexiones tomadas "
                                      "(qué, …, tomadas, prestadas en Postgres, con escritura abierta)")
        return r.json()

    def _posicion(self, broker, asset, asset_type, cantidad, invertido, moneda, entrada="2025-01-10"):
        with main.db_abierta() as conn:
            pid = conn.execute(
                "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, quantity, "
                "commissions, price_override, currency, entry_date, buy_price) "
                "VALUES (?, ?, ?, ?, 0, ?, ?, 0, NULL, ?, ?, ?)",
                (self.ana, broker, asset, asset_type, invertido, cantidad, moneda, entrada,
                 invertido / cantidad)).lastrowid
            conn.commit()
        return pid

    def _cartera(self):
        self._posicion("Schwab", "MSFT", "STOCK", 10, 4000.0, "USD")
        self._posicion("IOL", "GGAL", "ACCION", 100, 500000.0, "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR", 50, 1200000.0, "ARS")

    def _velas(self, simbolo, n=60, precio=100.0):
        with main.db_abierta() as conn:
            conn.executemany("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                             "VALUES (?, ?, ?, ?, ?, ?, 1000)",
                             [(simbolo, d.isoformat(), precio, precio, precio, precio)
                              for d in _ruedas(self.hoy, n)])
            conn.execute("INSERT INTO velas_estado (symbol, ultima_corrida, ok, filas) "
                         "VALUES (?, datetime('now'), 1, ?)", (simbolo, n))
            conn.commit()


class LaFichaTest(_Base):
    """Prioridad 1: la misma ficha y el mismo freno de 8 que la descarga a pedido."""

    def test_los_eventos_del_grafico(self):
        # Balances y dividendos de AAPL: nada guardado, se espera a Yahoo (5 s + 5 s).
        self._velas("AAPL")
        f = self._mirando(lambda: self.client.get("/api/tecnico/AAPL/eventos", headers=self.h_ana),
                          "dividendos", "balances pasados")
        self.assertEqual(f["empresa"], "AAPL")

    def test_con_los_eventos_al_dia_no_la_suelta(self):
        # La segunda vez no hay nada que esperar: soltarla igual obligaba a pedir
        # otra al pozo, y con el pozo lleno, a esperar un lugar que ya tenía.
        self._velas("AAPL")
        self._mirando(lambda: self.client.get("/api/tecnico/AAPL/eventos", headers=self.h_ana),
                      "dividendos", "balances pasados")
        sueltas = []
        de_verdad = pgsesion.antes_de_esperar_afuera
        with mock.patch.object(pgsesion, "antes_de_esperar_afuera",
                               lambda que=None: sueltas.append(que) or de_verdad(que)):
            r = self.client.get("/api/tecnico/AAPL/eventos", headers=self.h_ana)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(sueltas, [], "con todo al día no hay espera: no se suelta la conexión")

    def test_el_historial_de_dividendos(self):
        r = self._mirando(lambda: self.client.get("/api/dividendos/historial?tickers=KO,PEP",
                                                  headers=self.h_ana), "dividendos")
        self.assertEqual(sorted(r["tickers"]), ["KO", "PEP"])


class LaVariacionDelDiaTest(_Base):
    """Prioridad 2: la variación del día (`_variacion_del_dia`), que baja de
    Yahoo y de data912, pedida con la conexión de la ruta abierta."""

    def test_la_lista_de_seguimiento(self):
        with main.db_abierta() as conn:
            for s in ("MSFT", "GGAL.BA"):
                conn.execute("INSERT INTO watchlist (user_id, symbol, asset_type) VALUES (?, ?, 'STOCK')",
                             (self.ana, s))
            conn.commit()
        r = self._mirando(lambda: self.client.get("/api/watchlist", headers=self.h_ana),
                          "yahoo", "data912 en vivo")
        self.assertEqual(len(r["items"]), 2)

    def test_la_lista_de_seguimiento_con_los_bonos_ya_en_memoria(self):
        # Con la lista de bonos de data912 fresca en memoria no se la pide (ni se
        # pasa por su puerta): la única que suelta es la de las acciones.
        import time as _t
        main._data912_cache.update({"data": {"AL30": 862.0}, "ts": _t.time()})
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO watchlist (user_id, symbol, asset_type) VALUES (?, 'GGAL.BA', 'STOCK')",
                         (self.ana,))
            conn.commit()
        self._mirando(lambda: self.client.get("/api/watchlist", headers=self.h_ana), "data912 en vivo")
        self.assertEqual({e[1] for e in self.esperas if e[0] == "data912 en vivo"},
                         {"arg_cedears", "arg_stocks"}, "tenía que pedir sólo las acciones")

    def test_lo_que_te_afecta_en_el_inicio(self):
        self._cartera()
        self._mirando(lambda: self.client.get("/api/home/personal", headers=self.h_ana),
                      "yahoo", "data912 en vivo")

    def test_el_wrapped(self):
        self._cartera()
        self._mirando(lambda: self.client.get(f"/api/wrapped/{self.hoy.year}", headers=self.h_ana),
                      "yahoo")

    def test_los_insights_de_comportamiento(self):
        self._cartera()
        self._mirando(lambda: self.client.get("/api/behavioral/insights", headers=self.h_ana), "yahoo")

    def test_el_diagnostico_de_una_meta(self):
        self._cartera()
        with main.db_abierta() as conn:
            gid = conn.execute("INSERT INTO goals (user_id, target_usd, target_date, label) "
                               "VALUES (?, 50000, ?, 'Casa')",
                               (self.ana, (self.hoy + timedelta(days=900)).isoformat())).lastrowid
            conn.commit()
        self._mirando(lambda: self.client.get(f"/api/goals/{gid}/diagnostic", headers=self.h_ana), "yahoo")


class ElBotonAnalizarTest(_Base):
    """Prioridad 2: los builders de IA. El ✦ Analizar del Dashboard pasa por el
    chat y arma el paquete con `currency_context`, que pide la variación del
    día con la conexión de la ruta abierta."""

    def test_analizar_el_dashboard(self):
        self._cartera()
        claude = ClaudeDelChat(["Tu cartera está repartida entre tres activos."], herramienta=None)
        cuerpo = {"messages": [{"role": "user", "content": "Analizá mi dashboard"}], "stream": False,
                  "snapshot": {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []},
                  "analisis": {"screen": "dashboard", "params": {}}}
        with mock.patch.object(main, "_get_anthropic_client", return_value=claude):
            self._mirando(lambda: self.client.post("/api/ai/chat", headers=self.h_ana, json=cuerpo), "yahoo")


class LosFundamentalesTest(_Base):
    """Prioridad 3: `_yf_fetch_cached` abre su propia conexión y espera con ella
    el turno (un semáforo de 8) y a Yahoo, 5 veces seguidas para los fundamentales."""

    def setUp(self):
        super().setUp()
        test = self

        class _Turno:
            """El semáforo de 8: se anota cuando se empieza a esperar el turno."""
            def __enter__(s):
                test._anotar("turno de Yahoo")
                return s

            def __exit__(s, *a):
                return False

        def fetcher(nombre, disponible=False):
            def f(yf_ticker):
                self._anotar("fundamentales", nombre, yf_ticker)
                return {"available": disponible}
            return f
        self._p2 = [mock.patch.object(main, "_yf_fetch_semaphore", _Turno()),
                    mock.patch.object(main, "_yf_scorecard_fetcher", fetcher("scorecard", True))]
        for n in ("fundamentals", "analysts", "profile", "financials"):
            self._p2.append(mock.patch.object(main, f"_yf_{n}_fetcher", fetcher(n)))
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in reversed(self._p2):
            p.stop()
        super().tearDown()

    def test_los_fundamentales_de_una_accion(self):
        self._mirando(lambda: self.client.get("/api/fundamentals/AAPL", headers=self.h_ana),
                      "turno de Yahoo", "fundamentales")
        self.assertEqual(len([e for e in self.esperas if e[0] == "fundamentales"]), 5)


class LaFotoDeLaCarteraTest(_Base):
    """Prioridad 4: `fetch_prices_for_symbols` (la foto, el valor vivo, el brief)."""

    def test_el_valor_vivo_de_reportes(self):
        # `compute_live_portfolio_value` tenía DOS conexiones a la vez: la de la
        # ruta y la suya propia.
        self._cartera()
        self._mirando(lambda: self.client.get("/api/reports/timeline", headers=self.h_ana), "yahoo")

    def test_los_benchmarks_de_reportes_con_el_cache_frio(self):
        # El S&P 500 mensual y diario se bajan de Yahoo en la misma pantalla
        # (`_bench_para_reportes` → `_yf_history`), sin pasar por pricing.yahoo.
        self._cartera()
        self._mirando(lambda: self.client.get("/api/reports/timeline", headers=self.h_ana), "yahoo directo")
        self.assertIn("^SP500TR", [e[1] for e in self.esperas if e[0] == "yahoo directo"])
        # La inflación (argentinadatos, hasta 8 s) se pide ANTES que el S&P 500.
        inflacion = [e for e in self.esperas if e[0] == "inflación"]
        self.assertTrue(inflacion, "no esperó la inflación: la prueba no prueba nada")
        self.assertEqual([e for e in inflacion if any(e[-3:])], [], "esperó la inflación con la conexión tomada")

    def test_el_rendimiento_con_el_cache_frio(self):
        # `/api/insights/performance` espera las diez series juntas (hasta 25 s).
        self._cartera()
        self._mirando(lambda: self.client.get("/api/insights/performance", headers=self.h_ana),
                      "yahoo directo")

    def test_la_vista_previa_del_brief_de_la_asesora(self):
        self._cartera()
        self._mirando(lambda: self.client.get("/api/advisor/brief/preview?kind=close",
                                              headers=self.h_asesora), "yahoo")


class FueraDeHorarioTest(_Base):
    """Prioridad 5: el pre y post mercado de `get_portfolio_today` (el chat)."""

    def test_como_viene_hoy_en_el_chat(self):
        self._cartera()
        claude = ClaudeDelChat(["Hoy tu cartera viene tranquila."], herramienta=("get_portfolio_today", {}))
        cuerpo = {"messages": [{"role": "user", "content": "¿Cómo viene hoy mi cartera?"}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []}}
        # A las 9 de Argentina Nueva York no está en la rueda normal: se le pide
        # a Yahoo el pre y el post (en la rueda no se pide nada).
        a_las_9 = datetime.combine(self.hoy, time(9, 0))
        with mock.patch.object(main, "_get_anthropic_client", return_value=claude), \
                mock.patch("fechas.ahora_art", return_value=a_las_9):
            self._mirando(lambda: self.client.post("/api/ai/chat", headers=self.h_ana, json=cuerpo),
                          "pre/post")


class RegistrarDesdeElChatTest(_Base):
    """Del mismo barrido: «comprá AAPL a precio de mercado» en el chat. El precio
    lo baja el servidor en otro hilo (`_trade_market_price`, hasta 8 s) y el chat
    lo espera con la base abierta para registrar."""

    def test_una_compra_al_precio_de_mercado(self):
        pedido = {"action": "buy", "asset": "AAPL", "asset_type": "CEDEAR", "broker": "IOL",
                  "amount": 500000, "price_source": "market_today"}
        claude = ClaudeDelChat(["Listo, ¿la confirmo?"], herramienta=("register_trade", pedido))
        cuerpo = {"messages": [{"role": "user", "content": "Comprá 500 mil pesos de AAPL a precio de mercado"}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []}}
        with mock.patch.object(main, "_get_anthropic_client", return_value=claude):
            self._mirando(lambda: self.client.post("/api/ai/chat", headers=self.h_ana, json=cuerpo),
                          "data912 en vivo")


class LosSplitsTest(_Base):
    """Prioridades 6 y 7: el chequeo de splits de la cartera y el ajuste de un lote."""

    def setUp(self):
        super().setUp()
        self.pid = self._posicion("IOL", "AAPL", "CEDEAR", 50, 1200000.0, "ARS", entrada="2025-01-10")
        # Yahoo anota un 10 a 1 en AAPL.BA después de la compra.
        self.splits_ba["AAPL.BA"] = [("2025-06-02", 10.0)]

    def test_el_chequeo_de_splits_de_la_cartera(self):
        r = self._mirando(lambda: self.client.get("/api/positions/split-check", headers=self.h_ana), "splits")
        self.assertEqual([s["asset"] for s in r["suggestions"]], ["AAPL"])

    def test_ajustar_el_ratio_trae_los_splits_antes_de_tomar_el_turno(self):
        # El turno de la cuenta es una ESCRITURA (en Postgres; en SQLite no hace
        # nada): con él tomado la conexión no se puede soltar. Se anota cuándo se toma.
        de_verdad = main._tomar_turno_de_la_puerta

        def turno(conn, uid):
            self.orden.append("turno")
            return de_verdad(conn, uid)
        with mock.patch.object(main, "_tomar_turno_de_la_puerta", turno):
            r = self._mirando(lambda: self.client.post(f"/api/positions/{self.pid}/adjust-ratio",
                                                       headers=self.h_ana), "splits")
        self.assertEqual((r["already_applied"], r["factor"]), (False, 10.0))
        self.assertIn("turno", self.orden)
        self.assertNotIn("splits", self.orden[self.orden.index("turno"):],
                         f"esperó a Yahoo con el turno de la cuenta tomado: {self.orden}")

    def test_un_lote_que_no_se_ajusta_no_le_pide_splits_a_yahoo(self):
        # Efectivo, un bono y un fondo: el mismo 400 de siempre, sin pasar antes
        # por Yahoo (la auditoría del 05/11 lo encontró al traer los splits antes
        # del turno: se pedían también para los lotes que después se rechazan).
        with main.db_abierta() as conn:
            pids = [conn.execute(
                "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, quantity, "
                "commissions, currency, entry_date) VALUES (?, 'IOL', ?, ?, ?, 1000, 10, 0, 'ARS', '2025-01-10')",
                (self.ana, asset, tipo, efectivo)).lastrowid
                for asset, tipo, efectivo in (("ARS", None, 1), ("AL30", "BOND", 0), ("FCI:COCOS-AHORRO-A", "FCI", 0))]
            # Y una acción de EEUU en la cuenta en dólares: no cotiza en BYMA.
            pids.append(conn.execute(
                "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, quantity, "
                "commissions, currency, entry_date) VALUES (?, 'Schwab', 'MSFT', 'STOCK', 0, 4000, 10, 0, "
                "'USD', '2025-01-10')", (self.ana,)).lastrowid)
            conn.commit()
        for pid in pids:
            del self.orden[:]
            r = self.client.post(f"/api/positions/{pid}/adjust-ratio", headers=self.h_ana)
            self.assertEqual(r.status_code, 400, r.text)
            self.assertNotIn("splits", self.orden, f"lote {pid}: le pidió splits a Yahoo para rechazarlo")


class LosCambiosDeRatioTest(_Base):
    """Prioridad 7: los cambios de ratio de VARIOS papeles juntos. El comparador
    con dos acciones argentinas nuevas los arma en el momento; Yahoo anota un 10
    a 1 que el precio no muestra y hay que ir a data912 por la historia de BYMA,
    papel por papel. Desde el segundo, lo guardado del primero quedaba abierto
    toda la espera."""

    def test_dos_acciones_argentinas_nuevas_en_el_comparador(self):
        for t in ("GGAL.BA", "YPFD.BA"):
            self.splits[t] = [(_ruedas(self.hoy, 200)[0].isoformat(), 10.0)]
        self._mirando(lambda: self.client.get(
            "/api/comparar/precio?activos=GGAL.BA,YPFD.BA&local=GGAL.BA,YPFD.BA&moneda=ars&plazo=1a",
            headers=self.h_ana), "splits", "data912 historia")
        papeles = [e[1].rsplit("/", 1)[1] for e in self.esperas if e[0] == "data912 historia"]
        self.assertIn("GGAL", papeles)
        self.assertIn("YPFD", papeles)


class LaHistoriaDeData912Test(_Base):
    """La puerta de `pricing.data912.filas`. Hoy ningún camino llega a ella con una
    conexión en la mano sin pasar antes por otra puerta (los cambios de ratio
    sueltan antes; la vela de BYMA corre adentro de `varios`; la liquidez no abre
    la base). Por eso se la llama directo, como lo haría el próximo que la use."""

    def test_suelta_la_conexion_de_quien_la_llama(self):
        from pricing import data912
        del self.esperas[:]
        with main.db_abierta() as conn:
            conn.execute("SELECT 1").fetchone()
            data912.filas("bonds", "AL30")
            self.assertEqual(conn.execute("SELECT 2").fetchone()[0], 2, "se sigue usando después")
        self.assertEqual([e[0] for e in self.esperas], ["data912 historia"])
        self.assertEqual([e for e in self.esperas if any(e[-3:])], [], "esperó con la conexión tomada")


class LosEventosDeLaCarteraTest(_Base):
    """Del mismo barrido: la cartera sin eventos guardados espera la búsqueda."""

    def test_los_eventos_de_la_cartera(self):
        self._cartera()
        self._mirando(lambda: self.client.get("/api/events/portfolio", headers=self.h_ana), "eventos")


if __name__ == "__main__":
    unittest.main()
