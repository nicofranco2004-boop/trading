"""Eventos: una sola regla para tenerlos al día, en paralelo y sin repetir.

MEDIDO el 2026-10-01 en producción: /api/events/popular tardaba 10,7 s la
primera vez después de cada publicación (la memoria de "ya buscado" se borra al
reiniciar) porque pedía las ~20 empresas a yfinance DE A UNA y esperando.
/api/events/portfolio tardaba 0,4 s porque YA tenía la regla de "responder con
lo guardado y renovar de fondo" — copiada a mano en dos endpoints y no en éste.
Ahora `_eventos_al_dia` es la regla única y `_refresh_events_for_tickers` busca
en paralelo sin repetir. yfinance siempre reemplazado: nada sale a la red.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _en_dias(n: int) -> str:
    return (datetime.utcnow() + timedelta(days=n)).strftime("%Y-%m-%d")


POPULARES = main.POPULAR_TICKERS_US + main.POPULAR_TICKERS_AR_ADR


class _YahooLento:
    """yfinance de mentira: tarda `demora` por ticker y cuenta los pedidos."""

    def __init__(self, demora):
        self.demora = demora
        self.pedidos = []
        self.lock = threading.Lock()

    def __call__(self, ticker, fallas=None):
        with self.lock:
            self.pedidos.append(ticker)
        time.sleep(self.demora)
        return [{"ticker": ticker, "event_type": "earnings", "event_date": _en_dias(20),
                 "details": {"eps_estimate": 1.0}, "confirmed": 1}]


def _esperar_fondo():
    """Que terminen las búsquedas de fondo antes de mirar o de la prueba siguiente."""
    for _ in range(200):
        with main._events_en_vuelo_lock:
            pendientes = list(main._events_en_vuelo.values())
        if not pendientes:
            return
        main._esperar_futuros(pendientes, timeout=5)


class EventosAlDiaTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        _esperar_fondo()
        main._events_fetched_at.clear()
        conn = main.get_db()
        with conn:
            conn.execute("DELETE FROM financial_events")
            uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                               (f"aldia-{self.id()}-{time.time()}@rendi.test", "x")).lastrowid
        conn.close()
        self.token = main.create_token(uid)

    def tearDown(self):
        _esperar_fondo()

    def _sembrar(self, tickers):
        conn = main.get_db()
        with conn:
            for t in tickers:
                conn.execute(
                    """INSERT INTO financial_events
                       (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                       VALUES (?, 'earnings', ?, '{}', 1, 'yfinance', '2026-09-30T00:00:00Z')""",
                    (t, _en_dias(30)))
        conn.close()

    def _filas(self, tickers):
        conn = main.get_db()
        try:
            ph = ",".join("?" for _ in tickers)
            return conn.execute(f"SELECT COUNT(*) FROM financial_events WHERE ticker IN ({ph})",
                                tuple(tickers)).fetchone()[0]
        finally:
            conn.close()

    def test_busca_en_paralelo(self):
        """8 empresas de 0,3 s cada una: de a una serían 2,4 s."""
        yahoo = _YahooLento(0.3)
        tickers = [f"T{i}" for i in range(8)]
        with patch.object(main, "_fetch_yf_events", yahoo):
            t0 = time.monotonic()
            main._refresh_events_for_tickers(tickers, esperar_segundos=5)
            tardo = time.monotonic() - t0
        self.assertLess(tardo, 1.2, f"tardó {tardo:.2f} s: no fue en paralelo")
        self.assertEqual(sorted(yahoo.pedidos), sorted(tickers))
        self.assertEqual(self._filas(tickers), 8)

    def test_dos_pedidos_a_la_vez_buscan_una_sola_vez(self):
        yahoo = _YahooLento(0.3)
        tickers = ["AA", "BB", "CC"]
        with patch.object(main, "_fetch_yf_events", yahoo):
            hilos = [threading.Thread(target=main._refresh_events_for_tickers,
                                      args=(tickers,), kwargs={"esperar_segundos": 5}) for _ in range(3)]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join()
        self.assertEqual(sorted(yahoo.pedidos), sorted(tickers))

    def test_una_busqueda_que_falla_no_cuenta_como_renovada(self):
        """Si guardar falla, no se marca como buscado (se reintenta en el
        próximo pedido) y no suma en `refreshed_tickers`."""
        def yahoo_roto(ticker, fallas=None):
            return [{"ticker": ticker}]          # sin fecha ni tipo: guardar revienta
        with patch.object(main, "_fetch_yf_events", yahoo_roto):
            renovadas = main._refresh_events_for_tickers(["AA", "BB"], esperar_segundos=5)
        self.assertEqual(renovadas, 0)
        self.assertNotIn("AA", main._events_fetched_at)
        yahoo = _YahooLento(0.01)
        with patch.object(main, "_fetch_yf_events", yahoo):
            self.assertEqual(main._refresh_events_for_tickers(["AA", "BB"], esperar_segundos=5), 2)
        self.assertEqual(sorted(yahoo.pedidos), ["AA", "BB"])

    def _fechas(self, ticker, tipo):
        conn = main.get_db()
        try:
            return sorted(r[0] for r in conn.execute(
                "SELECT event_date FROM financial_events WHERE ticker=? AND event_type=?",
                (ticker, tipo)).fetchall())
        finally:
            conn.close()

    def _guardar(self, ticker, tipo, fecha, source="yfinance"):
        conn = main.get_db()
        with conn:
            conn.execute("""INSERT INTO financial_events
                (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                VALUES (?, ?, ?, '{}', 0, ?, 'x')""", (ticker, tipo, fecha, source))
        conn.close()

    def test_una_fecha_que_yahoo_movio_no_queda_duplicada(self):
        """Visto el 2026-10-01: NVDA quedó con dos earnings (la estimada vieja y
        la nueva) y la tarjeta del inicio anunciaba la que ya no existe. Por el
        camino de la pantalla: /events/portfolio responde con lo guardado y la
        búsqueda de fondo deja una sola fecha futura."""
        auth = self._usuario_con_nvda()
        self._guardar("NVDA", "earnings", _en_dias(3))      # la estimada vieja
        self._guardar("NVDA", "earnings", _en_dias(-80))    # el trimestre pasado: historia
        self._guardar("NVDA", "earnings", _en_dias(10), source="manual")  # cargado a mano
        yahoo = _YahooLento(0.01)                            # Yahoo dice: dentro de 20 días
        with patch.object(main, "_fetch_yf_events", yahoo):
            self.client.get("/api/events/portfolio?days=90", headers=auth)
            _esperar_fondo()
        self.assertEqual(self._fechas("NVDA", "earnings"),
                         sorted([_en_dias(-80), _en_dias(10), _en_dias(20)]))

    def test_si_yahoo_no_trae_un_tipo_lo_guardado_se_respeta(self):
        """La lectura de earnings de _fetch_yf_events puede fallar en silencio
        y devolver sólo el dividendo: eso NO significa que el earnings se fue."""
        self._guardar("KO", "earnings", _en_dias(5))
        def solo_dividendo(ticker, fallas=None):
            return [{"ticker": ticker, "event_type": "ex_dividend", "event_date": _en_dias(15),
                     "details": {}, "confirmed": 1}]
        with patch.object(main, "_fetch_yf_events", solo_dividendo):
            main._refresh_events_for_tickers(["KO"], esperar_segundos=5)
        self.assertEqual(self._fechas("KO", "earnings"), [_en_dias(5)])
        self.assertEqual(self._fechas("KO", "ex_dividend"), [_en_dias(15)])

    def test_yahoo_que_no_contesta_no_queda_al_dia_6_horas(self):
        """Hallado por la revisión independiente (2026-10-01): con Yahoo
        rechazando por exceso de pedidos, _fetch_yf_events devolvía [] igual
        que "no tiene eventos" y el ticker quedaba "al día" 6 horas. Por la
        función REAL de Yahoo, con yf.Ticker tirando el error."""
        with patch.object(main.yf, "Ticker", side_effect=Exception("429 Too Many Requests")):
            renovadas = main._refresh_events_for_tickers(["AA"], esperar_segundos=5)
            self.assertEqual(renovadas, 0)
            # No se reintenta en cada visita…
            self.assertEqual(main._refresh_events_for_tickers(["AA"], esperar_segundos=5), 0)
        falta = main.EVENTS_TTL - (time.time() - main._events_fetched_at["AA"])
        # …sino a los EVENTOS_REINTENTO_SEG (10 min), no a las 6 h.
        self.assertAlmostEqual(falta, main.EVENTOS_REINTENTO_SEG, delta=5)

    def test_si_falla_un_solo_pedido_lo_que_llego_cuenta(self):
        """El calendario falló pero el dividendo llegó: queda al día con lo que
        hay (y el earnings guardado se respeta — ver el test de abajo)."""
        class T:
            @property
            def calendar(self):
                raise Exception("calendar caído")
            info = {"exDividendDate": int(time.time()) + 15 * 86400, "lastDividendValue": 0.5}
        with patch.object(main.yf, "Ticker", return_value=T()):
            self.assertEqual(main._refresh_events_for_tickers(["KO"], esperar_segundos=5), 1)
        self.assertEqual(len(self._fechas("KO", "ex_dividend")), 1)

    def test_el_adelanto_del_inicio_no_espera_en_semanas_tranquilas(self):
        """Lo guardado está a 30 días y el inicio pide 14: no es una base
        vacía, es una semana tranquila. Hallado por la revisión independiente:
        esperaba a Yahoo (3,0 s medidos); tiene que responder ya."""
        conn = main.get_db()
        with conn:
            for t in POPULARES:
                conn.execute("""INSERT INTO financial_events
                    (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                    VALUES (?, 'earnings', ?, '{}', 1, 'yfinance', 'x')""", (t, _en_dias(30)))
        conn.close()
        yahoo = _YahooLento(1.0)
        with patch.object(main, "_fetch_yf_events", yahoo):
            t0 = time.monotonic()
            r = self.client.get("/api/events/popular?days=14",
                                headers={"Authorization": f"Bearer {self.token}"})
            tardo = time.monotonic() - t0
            _esperar_fondo()
        self.assertEqual(r.status_code, 200)
        self.assertLess(tardo, 0.5, f"tardó {tardo:.2f} s esperando a Yahoo")

    def test_al_apagar_se_descarta_lo_que_no_arranco(self):
        """Los hilos de las colas no son "daemon": sin cancelar, el proceso
        viejo de cada deploy esperaba la cola entera antes de cerrarse. Con
        colas propias de la prueba (las globales siguen sirviendo al resto)."""
        from concurrent.futures import ThreadPoolExecutor
        traba = threading.Event()
        colas = [ThreadPoolExecutor(max_workers=1) for _ in range(3)]
        corriendo = colas[0].submit(traba.wait, 5)
        en_cola = [colas[0].submit(time.sleep, 0) for _ in range(5)]
        with patch.object(main, "_events_fetch_executor", colas[0]), \
             patch.object(main, "_yf_executor", colas[1]), \
             patch.object(main, "_news_fetch_executor", colas[2]):
            main._stop_scheduler()
        traba.set()
        self.assertTrue(all(f.cancelled() for f in en_cola))
        self.assertFalse(corriendo.cancelled())   # lo que ya corría termina

    def test_el_evento_de_hoy_no_se_borra_aunque_yahoo_ya_informe_el_siguiente(self):
        """Revisión independiente 2 (2026-10-01): el mismo día del ex-dividendo
        Yahoo puede ya informar el próximo (PSEC, dividendo mensual). Borrar el
        de HOY lo sacaba del mail del día, de la agenda y del inicio."""
        hoy = main._iso_today()
        self._guardar("PSEC", "ex_dividend", hoy)
        def el_proximo(ticker, fallas=None):
            return [{"ticker": ticker, "event_type": "ex_dividend", "event_date": _en_dias(28),
                     "details": {}, "confirmed": 1}]
        with patch.object(main, "_fetch_yf_events", el_proximo):
            main._refresh_events_for_tickers(["PSEC"], esperar_segundos=5)
        self.assertIn(hoy, self._fechas("PSEC", "ex_dividend"))

    def test_yahoo_caido_con_error_de_servidor_tambien_reintenta_pronto(self):
        """Con un 5xx yfinance devuelve el calendario VACÍO sin error (esconde
        la excepción) y sólo pedir el info revienta. Esperar a que fallaran los
        dos dejaba la caída marcada "al día" 6 h (revisión independiente 2)."""
        class Caido:
            calendar = {}
            @property
            def info(self):
                raise TypeError("'NoneType' object is not subscriptable")   # lo que tira yfinance con 503
        with patch.object(main.yf, "Ticker", return_value=Caido()):
            self.assertEqual(main._refresh_events_for_tickers(["AA"], esperar_segundos=5), 0)
        falta = main.EVENTS_TTL - (time.time() - main._events_fetched_at["AA"])
        self.assertAlmostEqual(falta, main.EVENTOS_REINTENTO_SEG, delta=5)

    def test_un_ticker_que_yahoo_no_conoce_no_cuenta_como_caida(self):
        """ALUA, TXAR: Yahoo contesta "no hay nada", sin error (medido con
        Yahoo real). Quedan en las 6 h normales, no se reintentan cada 10 min."""
        class Desconocido:
            calendar = {}
            info = {"trailingPegRatio": None}
        with patch.object(main.yf, "Ticker", return_value=Desconocido()):
            self.assertEqual(main._refresh_events_for_tickers(["ALUA"], esperar_segundos=5), 1)
        falta = main.EVENTS_TTL - (time.time() - main._events_fetched_at["ALUA"])
        self.assertGreater(falta, main.EVENTS_TTL - 5)

    def test_las_noticias_sin_tope_no_se_cuelgan_al_apagar(self):
        """`as_completed` no se entera de un futuro cancelado por el apagado:
        el camino sin tope de _ensure_news_batch_parallel esperaba para
        siempre (revisión independiente 2). Con una cola propia de la prueba."""
        from concurrent.futures import ThreadPoolExecutor
        cola = ThreadPoolExecutor(max_workers=1)
        traba = threading.Event()
        def noticias_lentas(conn, q, lang, cat):
            traba.wait(5)
        specs = [(f"apagado-{i}", "es", "prueba") for i in range(3)]
        for q, _, cat in specs:
            main._news_fetched_at.pop(main._cache_key_for("google_news", cat, q), None)
        with patch.object(main, "_news_fetch_executor", cola), \
             patch.object(main, "_refresh_news_query", noticias_lentas):
            h = threading.Thread(target=main._ensure_news_batch_parallel,
                                 args=(specs, 60), daemon=True)
            h.start()
            time.sleep(0.2)
            cola.shutdown(wait=False, cancel_futures=True)   # lo que hace el apagado
            traba.set()
            h.join(5)
        self.assertFalse(h.is_alive(), "se quedó esperando un futuro cancelado")

    def test_calendario_vacio_sin_error_usa_la_fecha_de_la_ficha(self):
        """Medido el 2026-10-02: con Yahoo frío y muchos pedidos a la vez, el
        calendario vuelve VACÍO sin error (yfinance esconde el 401) y AAPL,
        MSFT, NVDA, META, AMZN y TSLA quedaban "sin earnings" 6 h. La ficha trae
        la misma fecha en earningsTimestampStart. Por el camino real
        (_refresh_events_for_tickers → _fetch_yf_events → base)."""
        en_20 = int(time.time()) + 20 * 86400
        class CalendarioVacio:
            calendar = {}
            info = {"earningsTimestampStart": en_20, "earningsTimestamp": en_20 - 90 * 86400,
                    "isEarningsDateEstimate": True}
        with patch.object(main.yf, "Ticker", return_value=CalendarioVacio()):
            self.assertEqual(main._refresh_events_for_tickers(["NVDA"], esperar_segundos=5), 1)
        fecha = datetime.utcfromtimestamp(en_20).strftime("%Y-%m-%d")
        self.assertEqual(self._fechas("NVDA", "earnings"), [fecha])
        conn = main.get_db()
        try:
            confirmado = conn.execute("SELECT confirmed FROM financial_events WHERE ticker='NVDA'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(confirmado, 0)   # Yahoo dice que es estimada

    def test_con_calendario_la_ficha_no_agrega_otro_earnings(self):
        cal = _en_dias(25)
        class ConCalendario:
            calendar = {"Earnings Date": [datetime.strptime(cal, "%Y-%m-%d").date()]}
            info = {"earningsTimestampStart": int(time.time()) + 30 * 86400}
        with patch.object(main.yf, "Ticker", return_value=ConCalendario()):
            evs = main._fetch_yf_events("KO")
        self.assertEqual([e["event_date"] for e in evs if e["event_type"] == "earnings"], [cal])

    def test_el_earnings_anterior_de_la_ficha_no_se_usa(self):
        """`earningsTimestamp` a veces es el resultado ANTERIOR (TSLA: 22/07 con
        el próximo el 21/10): sin earningsTimestampStart no se inventa nada."""
        class SoloElAnterior:
            calendar = {}
            info = {"earningsTimestamp": int(time.time()) - 70 * 86400}
        with patch.object(main.yf, "Ticker", return_value=SoloElAnterior()):
            evs = main._fetch_yf_events("TSLA")
        self.assertEqual([e for e in evs if e["event_type"] == "earnings"], [])

    def test_lo_buscado_hace_poco_no_se_vuelve_a_pedir(self):
        yahoo = _YahooLento(0.01)
        with patch.object(main, "_fetch_yf_events", yahoo):
            main._refresh_events_for_tickers(["AA"], esperar_segundos=5)
            main._refresh_events_for_tickers(["AA"], esperar_segundos=5)
        self.assertEqual(yahoo.pedidos, ["AA"])

    def test_mercado_con_datos_guardados_responde_al_instante(self):
        """Lo que pasaba después de cada publicación: memoria vacía, base con
        datos. Antes esperaba la búsqueda entera; ahora responde ya."""
        self._sembrar(POPULARES)
        yahoo = _YahooLento(1.0)            # Yahoo lento: de a una serían 20 s
        with patch.object(main, "_fetch_yf_events", yahoo):
            t0 = time.monotonic()
            r = self.client.get("/api/events/popular?days=90",
                                headers={"Authorization": f"Bearer {self.token}"})
            tardo = time.monotonic() - t0
            self.assertEqual(r.status_code, 200)
            self.assertLess(tardo, 1.0, f"tardó {tardo:.2f} s esperando a Yahoo")
            tickers = {e["ticker"] for e in r.json()["events"] if e["event_type"] == "earnings"}
            self.assertTrue(set(POPULARES) <= tickers)
            # …y lo vencido se renueva de fondo
            _esperar_fondo()
        self.assertEqual(sorted(yahoo.pedidos), sorted(set(POPULARES)))

    def test_mercado_con_base_vacia_espera_pero_en_paralelo(self):
        yahoo = _YahooLento(0.3)
        with patch.object(main, "_fetch_yf_events", yahoo):
            t0 = time.monotonic()
            r = self.client.get("/api/events/popular?days=90",
                                headers={"Authorization": f"Bearer {self.token}"})
            tardo = time.monotonic() - t0
        self.assertEqual(r.status_code, 200)
        # ~20 empresas de 0,3 s: de a una serían ~6 s.
        self.assertLess(tardo, 3.0, f"tardó {tardo:.2f} s")
        tickers = {e["ticker"] for e in r.json()["events"] if e["event_type"] == "earnings"}
        self.assertTrue(set(POPULARES) <= tickers)

    def _usuario_con_nvda(self):
        conn = main.get_db()
        with conn:
            uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                               (f"cartera-{self.id()}-{time.time()}@rendi.test", "x")).lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (uid, "IBKR", "USDT"))
            conn.execute("""INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, entry_date)
                            VALUES (?,?,?,?,?,0,?)""", (uid, "IBKR", "NVDA", 10, 1000, "2025-01-02"))
        conn.close()
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def test_la_cartera_usa_la_misma_regla(self):
        """/events/portfolio responde con lo guardado aunque Yahoo tarde."""
        auth = self._usuario_con_nvda()
        self._sembrar(["NVDA"])
        yahoo = _YahooLento(1.0)
        with patch.object(main, "_fetch_yf_events", yahoo):
            t0 = time.monotonic()
            r = self.client.get("/api/events/portfolio?days=90", headers=auth)
            tardo = time.monotonic() - t0
            _esperar_fondo()
        self.assertEqual(r.status_code, 200)
        self.assertLess(tardo, 0.8)
        self.assertIn("NVDA", {e["ticker"] for e in r.json()["events"]})
        self.assertEqual(r.json()["refreshed_tickers"], 0)   # no esperó a nadie
        self.assertEqual(yahoo.pedidos, ["NVDA"])             # …pero renovó de fondo

    def test_cartera_sin_nada_guardado_espera_y_cuenta_lo_que_llego(self):
        auth = self._usuario_con_nvda()
        yahoo = _YahooLento(0.1)
        with patch.object(main, "_fetch_yf_events", yahoo):
            r = self.client.get("/api/events/portfolio?days=90", headers=auth)
        self.assertEqual(r.status_code, 200)
        self.assertIn("NVDA", {e["ticker"] for e in r.json()["events"]})
        self.assertEqual(r.json()["refreshed_tickers"], 1)

    def test_nunca_espera_mas_que_el_tope(self):
        """Yahoo colgado y nada guardado: la pantalla responde al tope, vacía y
        diciendo que no renovó nada; lo que llega después se guarda igual."""
        auth = self._usuario_con_nvda()
        yahoo = _YahooLento(1.0)
        with patch.object(main, "_fetch_yf_events", yahoo), \
             patch.object(main, "EVENTOS_ESPERA_MAX_SEG", 0.2):
            t0 = time.monotonic()
            r = self.client.get("/api/events/portfolio?days=90", headers=auth)
            tardo = time.monotonic() - t0
            self.assertEqual(r.status_code, 200)
            self.assertLess(tardo, 0.8, f"tardó {tardo:.2f} s: no respetó el tope")
            self.assertEqual(r.json()["events"], [])
            self.assertEqual(r.json()["refreshed_tickers"], 0)
            _esperar_fondo()
        self.assertEqual(self._filas(["NVDA"]), 1)   # llegó tarde, pero quedó guardado


if __name__ == "__main__":
    unittest.main()
