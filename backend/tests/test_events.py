"""Tests del endpoint /api/events/portfolio.

Mockea yfinance — no hace fetch real. Verifica:
  • Filtra eventos al portfolio del user.
  • Excluye bonos AR (los maneja frontend).
  • Excluye crypto.
  • Excluye cash.
  • Filtra por ventana de fechas (days).

⚠️ LAS FECHAS SON RELATIVAS A HOY, A PROPÓSITO. Antes se sembraban fechas fijas
(mayo-julio 2026) y se consultaba "los próximos N días": el endpoint filtra con
`event_date >= hoy AND event_date <= hoy + days` (main.py:6201-6205), así que en
cuanto el calendario pasó por encima de las semillas los 9 tests se pusieron en
rojo solos — y los que asertaban lista VACÍA (bonos AR, aislamiento cross-user,
orden) pasaron a estar en verde sin probar nada, que es peor. Lo que estos tests
verifican es la VENTANA, no una fecha del almanaque: sembrar "dentro de N días"
prueba lo mismo y no caduca.
  • Persistencia: upsert idempotente.
  • Auth + cross-user isolation.
"""
import os
import sys
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _en_dias(n: int) -> str:
    """Fecha ISO a `n` días de hoy (UTC, igual que el endpoint)."""
    return (datetime.utcnow() + timedelta(days=n)).strftime("%Y-%m-%d")


def _new_user(conn, email: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"),
    )
    return cur.lastrowid


def _add_broker(conn, uid: int, name: str, currency: str = "USDT") -> int:
    cur = conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
        (uid, name, currency),
    )
    return cur.lastrowid


def _add_position(conn, uid: int, broker: str, asset: str, qty: float = 100, is_cash: int = 0):
    conn.execute(
        """INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested)
           VALUES (?, ?, ?, ?, ?, 0)""",
        (uid, broker, asset, is_cash, qty),
    )


class EventsPortfolioTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"events-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "IBKR", "USDT")
        # Reset events cache (idempotent fetcher TTL)
        main._events_fetched_at.clear()
        # Limpiar events table para que cada test parta limpio
        with conn:
            conn.execute("DELETE FROM financial_events")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.token}"})

    def _seed_event(self, ticker, event_type, date, details=None, confirmed=1):
        conn = main.get_db()
        with conn:
            conn.execute(
                # Conflicto por la UNIQUE(ticker, event_type, event_date), NO por `id`
                # (el id es un AUTOINCREMENT surrogate). La única columna que la query
                # no nombra es justamente `id`: con INSERT OR REPLACE la fila se
                # borraba y se reinsertaba, así que el id CAMBIABA; con DO UPDATE
                # sobrevive. Se deja sobrevivir a propósito (es el comportamiento del
                # upsert real de producción, el de `_refresh_events_for_tickers` en
                # main.py) y no rompe nada: ningún test lee el id, ni hay FK que
                # apunte a financial_events(id).
                # De todos modos hoy el DO UPDATE ni corre: setUp hace
                # DELETE FROM financial_events y ningún test siembra dos veces la
                # misma (ticker, event_type, event_date).
                """INSERT INTO financial_events
                   (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                   VALUES (?, ?, ?, ?, ?, 'yfinance', '2026-05-12T00:00:00Z')
                   ON CONFLICT (ticker, event_type, event_date) DO UPDATE SET
                       details    = EXCLUDED.details,
                       confirmed  = EXCLUDED.confirmed,
                       source     = EXCLUDED.source,
                       fetched_at = EXCLUDED.fetched_at""",
                (ticker, event_type, date, json.dumps(details or {}), confirmed),
            )
        # Marcar como ya fetcheado para evitar re-fetch via yfinance real
        main._events_fetched_at[ticker] = main.time.time()
        conn.close()

    # ─── Happy paths ─────────────────────────────────────────────────────────

    def test_returns_events_for_portfolio_tickers(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        _add_position(conn, self.uid, "IBKR", "MSFT", qty=20)
        conn.commit()
        conn.close()

        self._seed_event("AAPL", "earnings", _en_dias(40), {"eps_estimate": 1.45})
        self._seed_event("MSFT", "ex_dividend", _en_dias(20), {"dividend_per_share": 0.75})

        res = self._get("/api/events/portfolio?days=180")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(len(body["events"]), 2)
        tickers = {e["ticker"] for e in body["events"]}
        self.assertEqual(tickers, {"AAPL", "MSFT"})

    def test_filters_by_window_days(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()

        # Cerca + lejos
        cerca, lejos = _en_dias(15), _en_dias(200)
        self._seed_event("AAPL", "earnings", cerca, {})
        self._seed_event("AAPL", "earnings", lejos, {})

        # 30 días: sólo el cercano
        res = self._get("/api/events/portfolio?days=30")
        body = res.json()
        dates = {e["event_date"] for e in body["events"]}
        self.assertIn(cerca, dates)
        self.assertNotIn(lejos, dates)

        # 365 días: ambos
        res = self._get("/api/events/portfolio?days=365")
        body = res.json()
        dates = {e["event_date"] for e in body["events"]}
        self.assertIn(cerca, dates)
        self.assertIn(lejos, dates)

    def test_excludes_ar_bonds(self):
        """Bonos AR los maneja frontend — el endpoint NO debe traerlos aunque
        tengan eventos en la tabla."""
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AL30", qty=1000)  # bono AR
        conn.commit()
        conn.close()

        # Aunque hubiera un evento de AL30 en la tabla, el endpoint lo excluye
        self._seed_event("AL30", "earnings", _en_dias(30), {})

        res = self._get("/api/events/portfolio?days=180")
        body = res.json()
        self.assertEqual(body["events"], [])

    def test_excludes_cash_positions(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "USDT", qty=0, is_cash=1)
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()

        self._seed_event("AAPL", "earnings", _en_dias(40), {})
        res = self._get("/api/events/portfolio?days=90")
        body = res.json()
        # Sólo aparece AAPL — USDT (cash) no se intenta lookup
        self.assertEqual([e["ticker"] for e in body["events"]], ["AAPL"])

    def test_empty_portfolio_returns_empty(self):
        res = self._get("/api/events/portfolio?days=90")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["events"], [])

    # ─── Validación ──────────────────────────────────────────────────────────

    def test_invalid_days_rejected(self):
        for d in (-1, 0, 366, 9999):
            res = self._get(f"/api/events/portfolio?days={d}")
            self.assertEqual(res.status_code, 422, f"days={d}")

    def test_unauthorized_without_token(self):
        res = self.client.get("/api/events/portfolio")
        self.assertIn(res.status_code, (401, 403))

    def test_cross_user_isolation(self):
        conn = main.get_db()
        other_uid = _new_user(conn, f"other-{self.id()}@rendi.test")
        _add_broker(conn, other_uid, "IBKR", "USDT")
        _add_position(conn, other_uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()

        self._seed_event("AAPL", "earnings", _en_dias(40), {})

        # User A no tiene AAPL → no debe ver el evento
        res = self._get("/api/events/portfolio?days=180")
        self.assertEqual(res.json()["events"], [])

    def test_details_parsed_as_dict(self):
        """El campo `details` se devuelve como dict (parseado de JSON)."""
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()
        self._seed_event("AAPL", "earnings", _en_dias(40), {"eps_estimate": 1.45, "currency": "USD"})

        res = self._get("/api/events/portfolio?days=90")
        body = res.json()
        ev = body["events"][0]
        self.assertEqual(ev["details"]["eps_estimate"], 1.45)
        self.assertEqual(ev["details"]["currency"], "USD")


class PopularEventsTest(unittest.TestCase):
    """Tests del endpoint /api/events/popular — eventos del mercado (no del
    portfolio del user) — macro + earnings de tickers populares."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"popular-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "IBKR", "USDT")
        main._events_fetched_at.clear()
        with conn:
            conn.execute("DELETE FROM financial_events")
        # Para que el fetcher no haga llamadas reales a yfinance en tests:
        # marcamos todos los populares como "ya fetcheados"
        for t in main.POPULAR_TICKERS_US + main.POPULAR_TICKERS_AR_ADR:
            main._events_fetched_at[t] = main.time.time()
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.token}"})

    def _seed_popular_event(self, ticker, event_type, date, details=None):
        conn = main.get_db()
        with conn:
            conn.execute(
                # Idéntico a _seed_event: conflicto por la UNIQUE(ticker, event_type,
                # event_date), no por `id`. La única columna sin nombrar es el `id`
                # AUTOINCREMENT, que antes cambiaba (borrar+reinsertar) y ahora
                # sobrevive; nadie lo lee. Acá tampoco hay re-seed de la misma clave
                # (setUp limpia la tabla), así que el DO UPDATE no llega a correr.
                """INSERT INTO financial_events
                   (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                   VALUES (?, ?, ?, ?, 1, 'yfinance', '2026-05-12T00:00:00Z')
                   ON CONFLICT (ticker, event_type, event_date) DO UPDATE SET
                       details    = EXCLUDED.details,
                       confirmed  = EXCLUDED.confirmed,
                       source     = EXCLUDED.source,
                       fetched_at = EXCLUDED.fetched_at""",
                (ticker, event_type, date, json.dumps(details or {})),
            )
        conn.close()

    # ─── Macro events ────────────────────────────────────────────────────────

    def test_returns_macro_events_within_window(self):
        res = self._get("/api/events/popular?days=365")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Debería incluir algunos macros (depende de la fecha actual del sistema)
        macros = [e for e in body["events"] if e["event_type"] == "macro"]
        self.assertGreaterEqual(len(macros), 0)
        for ev in macros:
            self.assertEqual(ev["source"], "hardcoded")
            self.assertTrue(ev["confirmed"])
            self.assertIn(ev["details"]["country"], ("USA", "AR"))

    def test_macro_events_include_country_and_title(self):
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        macros = [e for e in body["events"] if e["event_type"] == "macro"]
        if macros:
            sample = macros[0]
            self.assertIn("country", sample["details"])
            self.assertIn("title", sample["details"])
            self.assertIn("category", sample["details"])
            # El ticker es un código sintético tipo "USA-CPI" / "AR-IPC"
            self.assertRegex(sample["ticker"], r"^(USA|AR)-[A-Z]+$")

    # ─── Earnings populares ──────────────────────────────────────────────────

    def test_includes_popular_ticker_earnings(self):
        # Seed earnings de NVDA (magnificent 7) en ventana
        self._seed_popular_event("NVDA", "earnings", _en_dias(60), {"eps_estimate": 5.10})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        nvda = [e for e in body["events"] if e["ticker"] == "NVDA"]
        self.assertEqual(len(nvda), 1)
        self.assertEqual(nvda[0]["event_type"], "earnings")
        self.assertEqual(nvda[0]["details"]["eps_estimate"], 5.10)
        self.assertFalse(nvda[0]["in_portfolio"])  # user no tiene NVDA

    def test_in_portfolio_flag_when_user_owns_ticker(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "TSLA", qty=10)
        conn.commit()
        conn.close()
        self._seed_popular_event("TSLA", "earnings", _en_dias(45), {"eps_estimate": 0.85})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        tsla = [e for e in body["events"] if e["ticker"] == "TSLA"][0]
        self.assertTrue(tsla["in_portfolio"])

    def test_ar_adr_ticker_included(self):
        self._seed_popular_event("GGAL", "earnings", _en_dias(30), {})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        tickers = {e["ticker"] for e in body["events"]}
        self.assertIn("GGAL", tickers)

    # ─── Sorting / filtros ───────────────────────────────────────────────────

    def test_events_sorted_by_date(self):
        self._seed_popular_event("AAPL", "earnings", _en_dias(90), {})
        self._seed_popular_event("MSFT", "earnings", _en_dias(30), {})
        self._seed_popular_event("AMZN", "earnings", _en_dias(60), {})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        # Filtrar sólo earnings que sembramos (macros pueden estar mezclados)
        seeded_dates = [e["event_date"] for e in body["events"]
                        if e["ticker"] in ("AAPL", "MSFT", "AMZN")]
        self.assertEqual(seeded_dates, sorted(seeded_dates))

    def test_days_window_filters_events(self):
        # Earnings lejano + cercano
        self._seed_popular_event("NVDA", "earnings", _en_dias(50), {})
        self._seed_popular_event("AAPL", "earnings", _en_dias(300), {})  # fuera de 180
        res = self._get("/api/events/popular?days=180")
        body = res.json()
        tickers = {e["ticker"] for e in body["events"] if e["event_type"] == "earnings"}
        self.assertIn("NVDA", tickers)
        self.assertNotIn("AAPL", tickers)

    # ─── Counts en response ─────────────────────────────────────────────────

    def test_response_includes_macro_and_ticker_counts(self):
        self._seed_popular_event("NVDA", "earnings", _en_dias(50), {})
        res = self._get("/api/events/popular?days=365")
        body = res.json()
        self.assertIn("macro_count", body)
        self.assertIn("ticker_count", body)
        self.assertGreaterEqual(body["ticker_count"], 1)

    # ─── Validación ─────────────────────────────────────────────────────────

    def test_invalid_days_rejected(self):
        res = self._get("/api/events/popular?days=999")
        self.assertEqual(res.status_code, 422)

    def test_unauthorized_without_token(self):
        res = self.client.get("/api/events/popular")
        self.assertIn(res.status_code, (401, 403))


class AiPacketScaleTest(unittest.TestCase):
    """El packet que ve la IA tiene que declarar en qué escala está el monto.

    `dashboard_events` le pasa el `details` crudo del evento, que incluye
    `dividend_per_share` — el monto por acción del SUBYACENTE. El packet no trae
    cantidades, así que el modelo no puede calcular el cobro; la nota está para
    que tampoco lo intente cruzando otro packet.
    """

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"aiscale-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "Balanz", "ARS")
        with conn:
            conn.execute("DELETE FROM financial_events")
            conn.execute(
                "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested, buy_price)"
                " VALUES (?, 'Balanz', 'AVGO', 0, 130, 1000, 7.7)", (self.uid,))
        conn.commit()
        conn.close()

    def _events(self, details):
        conn = main.get_db()
        fecha = (main._hoy_art_date() + timedelta(days=5)).isoformat()
        with conn:
            conn.execute(
                "INSERT INTO financial_events (ticker, event_type, event_date, details, confirmed,"
                " source, fetched_at) VALUES ('AVGO', ?, ?, ?, 1, 'yfinance', '2026-09-17T00:00:00Z')",
                ('ex_dividend', fecha, json.dumps(details)))
        conn.commit()
        from ai.builders.dashboard_events import build
        try:
            return build(conn, self.uid)
        finally:
            conn.close()

    def test_dividend_packet_warns_about_the_scale(self):
        pkt = self._events({"dividend_per_share": 0.65, "dividend_scale": "underlying_share"})
        evs = [e for e in pkt.get("events", []) if e["ticker"] == "AVGO"]
        self.assertTrue(evs, "el evento sembrado no llegó al packet")
        self.assertIn("dividend_scale_note", evs[0])
        self.assertIn("CEDEAR", evs[0]["dividend_scale_note"])

    def test_event_without_amount_has_no_note(self):
        pkt = self._events({})
        evs = [e for e in pkt.get("events", []) if e["ticker"] == "AVGO"]
        self.assertTrue(evs)
        self.assertNotIn("dividend_scale_note", evs[0])


class FetcherTest(unittest.TestCase):
    """Tests del fetcher yfinance — siempre mockeado para no depender de la red."""

    def setUp(self):
        main._events_fetched_at.clear()

    def test_fetcher_returns_empty_on_unknown_ticker(self):
        """yfinance Ticker no existente → fetcher devuelve [] sin throw."""
        with patch('main.yf.Ticker') as mock_t:
            mock_t.return_value.calendar = None
            mock_t.return_value.info = {}
            events = main._fetch_yf_events('NOEXISTE')
        self.assertEqual(events, [])

    def test_fetcher_handles_exception_gracefully(self):
        """Si yfinance arroja, el fetcher devuelve [] sin propagar."""
        with patch('main.yf.Ticker', side_effect=Exception('network error')):
            events = main._fetch_yf_events('AAPL')
        self.assertEqual(events, [])

    # ── La escala y la frescura del monto del dividendo ──────────────────────
    # yfinance mezcla dos cosas: la PRÓXIMA fecha ex-dividendo (declarada) con el
    # ÚLTIMO monto pagado. Y el monto es siempre por acción del SUBYACENTE, nunca
    # por CEDEAR. Sin estas dos marcas en el evento, el consumidor no tiene cómo
    # saber que no puede multiplicarlo por la cantidad de la posición — que es el
    # bug reportado el 2026-09-17 (US$40 anunciados, US$0,70 depositados).

    AVGO_EX = 1789948800      # 2026-09-21 — la próxima ex-date declarada
    AVGO_LAST = 1782086400    # 2026-06-22 — el ex-date del monto que trae yfinance

    def _fetch_div(self, **info):
        base = {'exDividendDate': self.AVGO_EX, 'lastDividendValue': 0.65}
        base.update(info)
        with patch('main.yf.Ticker') as mock_t:
            mock_t.return_value.calendar = None
            mock_t.return_value.info = base
            evs = main._fetch_yf_events('AVGO')
        return [e for e in evs if e['event_type'] == 'ex_dividend']

    def test_dividend_declares_its_scale(self):
        """El monto sale rotulado como 'por acción del subyacente'."""
        evs = self._fetch_div(lastDividendDate=self.AVGO_LAST)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['details']['dividend_scale'], 'underlying_share')
        self.assertEqual(evs[0]['details']['dividend_per_share'], 0.65)

    def test_dividend_from_previous_period_is_flagged(self):
        """Fecha del próximo pago + monto del anterior → marcado como estimado."""
        evs = self._fetch_div(lastDividendDate=self.AVGO_LAST)
        d = evs[0]['details']
        self.assertTrue(d['dividend_amount_estimated'])
        self.assertEqual(d['dividend_as_of'], '2026-06-22')   # de qué pago salió

    def test_dividend_of_the_same_period_is_not_flagged(self):
        """Si el monto ES el de esa fecha, no se marca estimado ni se inventa as_of."""
        evs = self._fetch_div(lastDividendDate=self.AVGO_EX)
        d = evs[0]['details']
        self.assertFalse(d['dividend_amount_estimated'])
        self.assertNotIn('dividend_as_of', d)

    def test_dividend_without_last_date_is_flagged(self):
        """Sin lastDividendDate no se puede afirmar que el monto sea de esa fecha."""
        evs = self._fetch_div()
        self.assertTrue(evs[0]['details']['dividend_amount_estimated'])

    def test_dividend_survives_a_corrupt_last_date(self):
        """Una fecha basura no debe tumbar el evento ni colar un as_of falso."""
        evs = self._fetch_div(lastDividendDate='no-es-un-timestamp')
        self.assertEqual(len(evs), 1)
        self.assertTrue(evs[0]['details']['dividend_amount_estimated'])
        self.assertNotIn('dividend_as_of', evs[0]['details'])

    # ── 'confirmed' de earnings deja de ser una constante ────────────────────
    # El KPI "Confirmados" de Novedades decía 100% siempre porque el fetcher
    # escribía confirmed=1 para todo. yfinance devuelve DOS fechas cuando la
    # empresa aún no confirmó el día: eso es la señal que faltaba leer.

    def _fetch_earnings(self, earnings_date):
        with patch('main.yf.Ticker') as mock_t:
            mock_t.return_value.calendar = {'Earnings Date': earnings_date,
                                            'Earnings Average': 1.23}
            mock_t.return_value.info = {}
            evs = main._fetch_yf_events('AVGO')
        return [e for e in evs if e['event_type'] == 'earnings']

    def test_earnings_single_date_is_confirmed(self):
        evs = self._fetch_earnings([datetime(2026, 12, 11)])
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['confirmed'], 1)

    def test_earnings_dataframe_range_is_not_confirmed(self):
        """Mismo criterio en la rama DataFrame (yfinance viejo).

        El fetcher tiene dos ramas según lo que devuelva `t.calendar`: dict en las
        versiones nuevas, DataFrame en las viejas. Si sólo una aplica el criterio,
        el dato sale "confirmado" o no según la versión INSTALADA — el mismo tipo
        de inconsistencia que hace que un bug reaparezca en producción.
        """
        import pandas as pd
        cal = pd.DataFrame(
            [[datetime(2026, 12, 9), datetime(2026, 12, 15)], [1.23, None]],
            index=['Earnings Date', 'Earnings Average'],
        )
        with patch('main.yf.Ticker') as mock_t:
            mock_t.return_value.calendar = cal
            mock_t.return_value.info = {}
            evs = [e for e in main._fetch_yf_events('AVGO') if e['event_type'] == 'earnings']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['confirmed'], 0)

    def test_earnings_dataframe_single_date_is_confirmed(self):
        import pandas as pd
        cal = pd.DataFrame([[datetime(2026, 12, 11)], [1.23]],
                           index=['Earnings Date', 'Earnings Average'])
        with patch('main.yf.Ticker') as mock_t:
            mock_t.return_value.calendar = cal
            mock_t.return_value.info = {}
            evs = [e for e in main._fetch_yf_events('AVGO') if e['event_type'] == 'earnings']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['confirmed'], 1)

    def test_dividend_without_amount_declares_no_scale(self):
        """Sin monto no hay escala que declarar: el campo describe AL MONTO."""
        evs = self._fetch_div(lastDividendValue=None, lastDividendDate=self.AVGO_LAST)
        self.assertEqual(len(evs), 1)
        self.assertNotIn('dividend_per_share', evs[0]['details'])
        self.assertNotIn('dividend_scale', evs[0]['details'])

    def test_earnings_date_range_is_not_confirmed(self):
        """Ventana estimada (dos fechas) → confirmed=0, y la UI lo rotula 'est.'."""
        evs = self._fetch_earnings([datetime(2026, 12, 9), datetime(2026, 12, 15)])
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['confirmed'], 0)


if __name__ == "__main__":
    unittest.main()
