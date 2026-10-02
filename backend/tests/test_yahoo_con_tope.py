"""Yahoo con tope: ninguna pantalla espera a Yahoo más que un tope corto, y dos
descargas a la vez no se pisan.

MEDIDO el 2026-10-02 (backend local, base y caché de yfinance nuevas):
GET /api/prices?symbols=AAPL,AL30,AMD,AMZN,BTC,GGAL,KO,MELI,META,MSFT,NVDA,TSLA,YPF
tardó 66 s UNA vez y 5,7-6,4 s las otras. Dos mecanismos, los dos reproducidos:

  1. `yf.download` guarda lo que baja en un diccionario GLOBAL de yfinance y lo
     vacía al empezar. Dos descargas a la vez en el mismo proceso (la cinta y los
     precios, en la misma pantalla) se lo vacían una a la otra: una devolvió
     tickers que no pidió (pedí SPY+QQQ, volvieron BTC-USD y META) y la otra quedó
     esperando un conteo que no llega — cortada a los 75 s, seguía esperando.
  2. Yahoo puede no contestar y yfinance espera hasta 30 s por pedido.

Y uno más, que apareció al medir las etapas: con una cripto en el pedido, la
"última fila" de la tabla es la de hoy (Bitcoin ya tiene vela) y las acciones
venían vacías → 11 pedidos de más a Yahoo, aviso de "precio viejo" en falso en
Cartera, y `fetch_prices_for_symbols` (Rendi AI, alertas) sin precio para ellas.

Acá yfinance se reemplaza SIEMPRE en `yfinance.Ticker` —el último eslabón antes
de la red—, así que cada prueba atraviesa el camino entero de producción:
endpoint → `pricing.yahoo.descargar` → pool con tope → lectura de la tabla →
último precio conocido. Nada sale a la red.
"""
import ast
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import pandas as pd  # noqa: E402
import main  # noqa: E402
import snapshots_job  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pricing import yahoo  # noqa: E402


class _YahooColgado:
    """`yfinance.Ticker` que NO contesta: toda pregunta se queda esperando hasta
    que la prueba lo suelta. Es lo que hace yfinance cuando Yahoo no responde."""

    def __init__(self):
        self.soltar = threading.Event()
        self.pedidos = []
        self._lock = threading.Lock()

    def __call__(self, ticker, *a, **k):
        colgado = self

        class _Ticker:
            def history(self, *a, **k):
                with colgado._lock:
                    colgado.pedidos.append(ticker)
                colgado.soltar.wait(60)
                return pd.DataFrame()

        return _Ticker()


def _velas(fechas, cierres, tz):
    """Lo que devuelve `Ticker.history` para velas diarias: índice con zona horaria."""
    idx = pd.DatetimeIndex(pd.to_datetime(fechas)).tz_localize(tz)
    return pd.DataFrame({"Open": cierres, "High": cierres, "Low": cierres,
                         "Close": cierres, "Volume": [1000] * len(cierres)}, index=idx)


class _YahooDeMentira:
    """`yfinance.Ticker` que contesta con velas fijas (y una demora opcional)."""

    def __init__(self, velas: dict, demora: float = 0.0):
        self.velas = velas
        self.demora = demora

    def __call__(self, ticker, *a, **k):
        yahoo_falso = self

        class _Ticker:
            def history(self, *a, **k):
                time.sleep(yahoo_falso.demora)
                if ticker not in yahoo_falso.velas:
                    return pd.DataFrame()
                return yahoo_falso.velas[ticker].copy()

        return _Ticker()


def _yahoo_es(falso):
    """Reemplaza `yfinance.Ticker` en las DOS puertas: la que usa todo el
    servidor y la que usaba `yf.download` por dentro (`yfinance.multi.Ticker`).
    Así nada sale a la red aunque alguien vuelva a escribir yf.download."""
    import yfinance
    import yfinance.multi
    return [patch.object(yfinance, "Ticker", falso),
            patch.object(yfinance.multi, "Ticker", falso)]


def _sin_data912():
    """data912 / BYMA fuera de la prueba: no tienen nada (y no salen a la red)."""
    return [patch.object(main, "_resolve_ar_bond_price", return_value=None),
            patch.object(main, "_resolve_ar_equity_price", return_value=None)]


def _olvidar_precios(*syms):
    with main._PRICE_CACHE_LOCK:
        for s in syms:
            main._PRICE_CACHE.pop(s, None)
    with main._last_price_buf_lock:
        for s in syms:
            main._last_price_buf.pop(s, None)


class PreciosConYahooColgadoTest(unittest.TestCase):
    """EL test pedido: Yahoo colgado → /api/prices contesta igual, y rápido."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        with conn:
            uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                               (f"colgado-{self.id()}-{time.time()}@rendi.test", "x")).lastrowid
        conn.close()
        self.token = main.create_token(uid)
        _olvidar_precios("AAPL", "MSFT")
        # El último precio que se conoció de AAPL (lo que ya se había guardado
        # en una visita anterior). MSFT nunca tuvo precio.
        with main._last_price_buf_lock:
            main._last_price_buf["AAPL"] = 190.5

    def tearDown(self):
        _olvidar_precios("AAPL", "MSFT")

    def test_yahoo_colgado_no_cuelga_los_precios(self):
        colgado = _YahooColgado()
        parches = _sin_data912() + [*_yahoo_es(colgado),
                                    patch.object(main, "PRECIOS_TOPE_YAHOO_SEG", 1.0, create=True)]
        for p in parches:
            p.start()
        try:
            t0 = time.monotonic()
            r = self.client.get("/api/prices?symbols=AAPL,MSFT",
                                headers={"Authorization": f"Bearer {self.token}"})
            tardo = time.monotonic() - t0
        finally:
            colgado.soltar.set()        # los hilos colgados terminan solos
            for p in parches:
                p.stop()

        self.assertEqual(r.status_code, 200)
        # El tope es 1 s; sin él, esta prueba esperaba los 60 s del Yahoo colgado.
        self.assertLess(tardo, 2.5, f"tardó {tardo:.1f} s esperando a Yahoo")
        # Yahoo SÍ estaba en el camino (no se salteó por otro lado).
        self.assertIn("AAPL", colgado.pedidos)
        self.assertIn("MSFT", colgado.pedidos)
        body = r.json()
        # Lo que se conocía se sirve, MARCADO como último conocido.
        self.assertEqual(body["AAPL"], 190.5)
        self.assertEqual(body["__meta"]["AAPL"]["src"], "last_known")
        self.assertTrue(body["__meta"]["AAPL"]["stale"])
        # Lo que nunca tuvo precio no se inventa.
        self.assertIsNone(body["MSFT"])

    def test_el_tope_es_uno_para_todo_el_pedido(self):
        """El lote y los pedidos de a uno comparten el tope: con Yahoo colgado,
        cinco símbolos no esperan cinco veces."""
        colgado = _YahooColgado()
        syms = ["AAPL", "MSFT", "KO", "AMD", "NVDA"]
        _olvidar_precios(*syms)
        parches = _sin_data912() + [*_yahoo_es(colgado),
                                    patch.object(main, "PRECIOS_TOPE_YAHOO_SEG", 1.0, create=True)]
        for p in parches:
            p.start()
        try:
            t0 = time.monotonic()
            main.get_prices(",".join(syms), 1)
            tardo = time.monotonic() - t0
        finally:
            colgado.soltar.set()
            for p in parches:
                p.stop()
            _olvidar_precios(*syms)
        self.assertLess(tardo, 2.5, f"tardó {tardo:.1f} s")


class DescargasALaVezTest(unittest.TestCase):
    """Dos descargas al mismo tiempo: cada una recibe exactamente lo suyo."""

    def test_dos_descargas_a_la_vez_no_se_pisan(self):
        fechas = ["2026-09-30", "2026-10-01"]
        velas = {t: _velas(fechas, [float(i + 1), float(i + 1) + 0.5], "America/New_York")
                 for i, t in enumerate(["AAPL", "AMD", "AMZN", "KO", "MELI", "META",
                                        "MSFT", "NVDA", "TSLA", "SPY", "QQQ", "DIA"])}
        A = ["AAPL", "AMD", "AMZN", "KO", "MELI", "META", "MSFT", "NVDA", "TSLA"]
        B = ["SPY", "QQQ", "DIA"]
        res = {}

        def bajar(nombre, tks):
            res[nombre] = yahoo.descargar(tks, tope=10)

        with patch.object(yahoo.yf, "Ticker", _YahooDeMentira(velas, demora=0.05)):
            hilos = [threading.Thread(target=bajar, args=("A", A)),
                     threading.Thread(target=bajar, args=("B", B))]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join(15)
        self.assertEqual(sorted(res["A"]["Close"].columns), sorted(A))
        self.assertEqual(sorted(res["B"]["Close"].columns), sorted(B))
        # Y cada número es el de SU ticker.
        self.assertEqual(float(res["B"]["Close"]["QQQ"].iloc[-1]), velas["QQQ"]["Close"].iloc[-1])

    def test_misma_tabla_que_yf_download(self):
        """La forma que leen los cuatro lugares que antes usaban yf.download."""
        velas = {"AAPL": _velas(["2026-09-30", "2026-10-01"], [330.0, 331.0], "America/New_York"),
                 "GGAL.BA": _velas(["2026-09-30", "2026-10-01"], [6000.0, 6100.0],
                                   "America/Argentina/Buenos_Aires")}
        with patch.object(yahoo.yf, "Ticker", _YahooDeMentira(velas)):
            por_dato = yahoo.descargar(["AAPL", "GGAL.BA", "NOEXISTE"], tope=5)
            por_ticker = yahoo.descargar("AAPL GGAL.BA", group_by="ticker", tope=5)
        # (dato, ticker): tabla["Close"] da una columna por ticker.
        self.assertEqual(list(por_dato["Close"].columns), ["AAPL", "GGAL.BA"])
        # Las velas del mismo día de Nueva York y Buenos Aires caen en la MISMA fila.
        self.assertEqual(len(por_dato), 2)
        self.assertIsNone(por_dato.index.tz)
        self.assertEqual(str(por_dato.index[-1])[:10], "2026-10-01")
        # (ticker, dato): tabla["AAPL"]["Close"].
        self.assertIn("AAPL", por_ticker)
        self.assertEqual(float(por_ticker["AAPL"]["Close"].iloc[-1]), 331.0)
        # Un ticker que Yahoo no tiene NO aparece (antes: columna vacía).
        self.assertNotIn("NOEXISTE", por_dato["Close"].columns)

    def test_lo_que_no_llega_a_tiempo_queda_afuera_y_lo_demas_llega(self):
        velas = {"AAPL": _velas(["2026-10-01"], [331.0], "America/New_York")}

        class _UnoColgado(_YahooDeMentira):
            def __call__(self, ticker, *a, **k):
                if ticker == "LENTO":
                    return _YahooColgado.__call__(colgado, ticker)
                return super().__call__(ticker)

        colgado = _YahooColgado()
        try:
            with patch.object(yahoo.yf, "Ticker", _UnoColgado(velas)):
                t0 = time.monotonic()
                tabla = yahoo.descargar(["AAPL", "LENTO"], tope=0.5)
                tardo = time.monotonic() - t0
        finally:
            colgado.soltar.set()
        self.assertLess(tardo, 1.5)
        self.assertEqual(list(tabla["Close"].columns), ["AAPL"])


class CriptoEnElPedidoTest(unittest.TestCase):
    """09:40 del 2026-10-02: Bitcoin ya tiene la vela de hoy, las acciones no."""

    VELAS = {
        "AAPL": _velas(["2026-09-30", "2026-10-01"], [333.0, 330.32], "America/New_York"),
        "MSFT": _velas(["2026-09-30", "2026-10-01"], [512.9, 512.8], "America/New_York"),
        "BTC-USD": _velas(["2026-09-30", "2026-10-01", "2026-10-02"],
                          [83553.0, 84853.0, 86745.0], "UTC"),
    }

    def setUp(self):
        _olvidar_precios("AAPL", "MSFT", "BTC")

    def tearDown(self):
        _olvidar_precios("AAPL", "MSFT", "BTC")

    def test_las_acciones_salen_del_lote_y_no_se_marcan_viejas(self):
        uno_a_uno = MagicMock(return_value=None)
        parches = _sin_data912() + [*_yahoo_es(_YahooDeMentira(self.VELAS)),
                                    patch.object(main, "_fetch_one", uno_a_uno),
                                    patch.object(main, "_fill_last_known_prices")]
        for p in parches:
            p.start()
        try:
            out = main.get_prices("AAPL,MSFT,BTC", 1)
        finally:
            for p in parches:
                p.stop()
        self.assertAlmostEqual(out["AAPL"], 330.32)
        self.assertAlmostEqual(out["MSFT"], 512.8)
        self.assertAlmostEqual(out["BTC"], 86745.0)
        # Antes: 2 pedidos de más a Yahoo y "precio del 01/10" en Cartera.
        self.assertEqual(uno_a_uno.call_count, 0)
        self.assertFalse(out["__meta"]["AAPL"]["stale"])
        self.assertEqual(out["__meta"]["AAPL"]["as_of"], "2026-10-01")
        self.assertFalse(out["__meta"]["BTC"]["stale"])

    def test_la_accion_que_se_salteo_la_rueda_sigue_marcada(self):
        """El aviso de Cartera existe por las velas .BA en NaN: eso NO se pierde.
        Una acción atrasada respecto de las OTRAS acciones sigue marcada."""
        velas = dict(self.VELAS)
        velas["KO"] = _velas(["2026-09-30"], [86.1], "America/New_York")   # se salteó el 01/10
        _olvidar_precios("KO")
        parches = _sin_data912() + [*_yahoo_es(_YahooDeMentira(velas)),
                                    patch.object(main, "_fill_last_known_prices")]
        for p in parches:
            p.start()
        try:
            out = main.get_prices("AAPL,KO,BTC", 1)
        finally:
            for p in parches:
                p.stop()
            _olvidar_precios("KO")
        self.assertAlmostEqual(out["KO"], 86.1)              # mejor viejo que ninguno
        self.assertTrue(out["__meta"]["KO"]["stale"])
        self.assertEqual(out["__meta"]["KO"]["as_of"], "2026-09-30")
        self.assertFalse(out["__meta"]["AAPL"]["stale"])

    def test_fetch_prices_for_symbols_trae_las_acciones(self):
        """Rendi AI, las alertas y la foto diaria: antes AAPL y MSFT volvían None."""
        parches = _sin_data912() + [*_yahoo_es(_YahooDeMentira(self.VELAS))]
        for p in parches:
            p.start()
        try:
            out = snapshots_job.fetch_prices_for_symbols(["AAPL", "MSFT", "BTC"], main.CRYPTO_YF)
        finally:
            for p in parches:
                p.stop()
        self.assertAlmostEqual(out["AAPL"], 330.32)
        self.assertAlmostEqual(out["MSFT"], 512.8)
        self.assertAlmostEqual(out["BTC"], 86745.0)

    def test_un_ticker_que_falta_no_se_lleva_el_precio_de_otro(self):
        """La lectura vieja hacía `float(última_fila)` cuando el ticker no estaba:
        con una sola columna en la tabla, el que faltaba se llevaba el precio del
        otro."""
        tabla = pd.concat({"Close": pd.DataFrame({"AAPL": [330.0]},
                                                 index=pd.to_datetime(["2026-10-01"]))}, axis=1)
        self.assertEqual(yahoo.ultimos_cierres(tabla, ["AL30", "AAPL"]),
                         {"AAPL": (330.0, "2026-10-01")})
        serie = pd.DataFrame({"Close": [330.0]}, index=pd.to_datetime(["2026-10-01"]))
        self.assertEqual(yahoo.ultimos_cierres(serie, ["AL30", "AAPL"]), {})


class ComparativasConYahooColgadoTest(unittest.TestCase):
    def test_las_diez_series_comparten_un_tope(self):
        """Antes: 25 s POR serie, esperadas una detrás de otra → con Yahoo
        colgado, hasta 10 × 25 s en la primera visita después de un deploy."""
        soltar = threading.Event()

        def colgada(*a, **k):
            soltar.wait(30)
            return {}

        pool = ThreadPoolExecutor(max_workers=4)   # el global queda limpio
        fuentes = ["_fetch_inflation_ar", "_fetch_sp500_monthly", "_fetch_dolar_blue_monthly",
                   "_fetch_shv_monthly", "_fetch_gld_monthly", "_fetch_merval_monthly",
                   "_fetch_uva_monthly", "_fetch_sp500_daily", "_fetch_yf_daily"]
        parches = [patch.object(main, f, colgada) for f in fuentes] + [
            patch.object(main, "_bench_fetch_executor", pool),
            patch.object(main, "BENCH_TOPE_SEG", 0.5),
            patch.dict(main._bench_cache, {"data": {"sp500": {"2026-09": 1.0}}, "ts": 0})]
        for p in parches:
            p.start()
        try:
            t0 = time.monotonic()
            data = main._benchmarks_fetch_and_cache()
            tardo = time.monotonic() - t0
        finally:
            soltar.set()
            for p in parches:
                p.stop()
            pool.shutdown(wait=False, cancel_futures=True)
        self.assertLess(tardo, 1.5, f"tardó {tardo:.1f} s")
        self.assertEqual(data["sp500"], {"2026-09": 1.0})   # lo que había, no un vacío


class NadieMasUsaYfDownloadTest(unittest.TestCase):
    """Guard del mecanismo: `yf.download` comparte un diccionario global entre
    TODAS las descargas del proceso. Una sola llamada nueva en el servidor vuelve
    a abrir la puerta al cuelgue de 66 s. Va por `pricing.yahoo.descargar`."""

    def test_ningun_modulo_del_servidor_llama_a_yf_download(self):
        culpables = []
        for f in sorted(Path(BACKEND).rglob("*.py")):
            rel = f.relative_to(BACKEND).as_posix()
            if rel.startswith(("tests/", "scripts/")):
                continue
            try:
                arbol = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for nodo in ast.walk(arbol):
                if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                        and nodo.func.attr == "download"
                        and isinstance(nodo.func.value, ast.Name)
                        and nodo.func.value.id in ("yf", "yfinance", "_yf")):
                    culpables.append(f"{rel}:{nodo.lineno}")
                if (isinstance(nodo, ast.ImportFrom) and nodo.module == "yfinance"
                        and any(a.name == "download" for a in nodo.names)):
                    culpables.append(f"{rel}:{nodo.lineno}")
        self.assertEqual(culpables, [], "usar pricing.yahoo.descargar en vez de yf.download")


class AlApagarTest(unittest.TestCase):
    def test_al_apagar_se_descarta_lo_que_no_salio_a_yahoo(self):
        """Mismo criterio que las colas de eventos y noticias: los hilos del pool
        no son "daemon" y el proceso viejo de cada deploy esperaría la cola entera."""
        traba = threading.Event()
        pools = [ThreadPoolExecutor(max_workers=1) for _ in range(4)]
        corriendo = pools[3].submit(traba.wait, 5)
        en_cola = [pools[3].submit(time.sleep, 0) for _ in range(5)]
        with patch.object(main, "_events_fetch_executor", pools[0]), \
             patch.object(main, "_yf_executor", pools[1]), \
             patch.object(main, "_news_fetch_executor", pools[2]), \
             patch.object(yahoo, "_pool", pools[3]):
            main._stop_scheduler()
            # Queda un pool nuevo: lo que llega durante el apagado sigue andando.
            self.assertIsNot(yahoo._pool, pools[3])
            self.assertEqual(yahoo.con_tope(lambda: 7, tope=2), 7)
        traba.set()
        self.assertTrue(all(f.cancelled() for f in en_cola))
        self.assertFalse(corriendo.cancelled())

    def test_un_pool_apagado_es_yahoo_que_no_respondio(self):
        """`_yf_fetch_cached` usa `_yf_executor`, que el apagado cierra para
        siempre: un pedido ahí no puede reventar la pantalla, cae a la caché."""
        muerto = ThreadPoolExecutor(max_workers=1)
        muerto.shutdown()
        with self.assertRaises(yahoo.YahooNoRespondio):
            yahoo.con_tope(time.sleep, 0, pool=muerto)
        with patch.object(yahoo, "_pool", muerto):
            self.assertEqual(yahoo.varios(time.sleep, [0, 0.0001], tope=1), ({}, [0, 0.0001]))


if __name__ == "__main__":
    unittest.main()
