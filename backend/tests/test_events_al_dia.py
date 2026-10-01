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

    def __call__(self, ticker):
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
        yahoo = _YahooLento(2.0)            # Yahoo lentísimo
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

    def test_la_cartera_usa_la_misma_regla(self):
        """/events/portfolio responde con lo guardado aunque Yahoo tarde."""
        conn = main.get_db()
        with conn:
            uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                               (f"cartera-{time.time()}@rendi.test", "x")).lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (uid, "IBKR", "USDT"))
            conn.execute("""INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, entry_date)
                            VALUES (?,?,?,?,?,0,?)""", (uid, "IBKR", "NVDA", 10, 1000, "2025-01-02"))
        conn.close()
        self._sembrar(["NVDA"])
        yahoo = _YahooLento(2.0)
        with patch.object(main, "_fetch_yf_events", yahoo):
            t0 = time.monotonic()
            r = self.client.get("/api/events/portfolio?days=90",
                                headers={"Authorization": f"Bearer {main.create_token(uid)}"})
            tardo = time.monotonic() - t0
            _esperar_fondo()
        self.assertEqual(r.status_code, 200)
        self.assertLess(tardo, 1.0)
        self.assertIn("NVDA", {e["ticker"] for e in r.json()["events"]})


if __name__ == "__main__":
    unittest.main()
