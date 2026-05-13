"""Tests del feature de noticias (PR #3).

Mockea Google News RSS — no hace fetch real. Cubre:
  • Parser RSS funciona con XML típico de Google News.
  • Endpoint /news/market trae items macro/market.
  • Endpoint /news/portfolio filtra a tickers del user.
  • Dedup por (source, external_id).
  • Cache TTL: no refetch si stale<TTL.
  • Validación de query params.
"""
import os
import sys
import tempfile
import unittest
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


# Sample RSS XML (estructura real de Google News, recortado).
# Lo armamos como string y luego .encode() para que los caracteres no-ASCII
# (acentos en español) no rompan el bytes literal.
SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>AAPL stock - Google Noticias</title>
    <item>
      <title>Apple stock: UBS explains Q2 earnings - TradingView</title>
      <link>https://www.tradingview.com/news/apple-q2-earnings/</link>
      <guid isPermaLink="false">https://www.tradingview.com/news/apple-q2-earnings/</guid>
      <pubDate>Tue, 28 Apr 2026 17:00:22 GMT</pubDate>
      <description>UBS analysts give their take on Apple Q2.</description>
      <source url="https://www.tradingview.com">TradingView</source>
    </item>
    <item>
      <title>Apple acciones caen 4% por retrasos - Investing.com</title>
      <link>https://es.investing.com/news/apple-cae-4-pct</link>
      <guid isPermaLink="false">https://es.investing.com/news/apple-cae-4-pct</guid>
      <pubDate>Mon, 27 Apr 2026 07:00:00 GMT</pubDate>
      <description>Las acciones de Apple caen 4% en pre-market.</description>
      <source url="https://es.investing.com">Investing.com Espana</source>
    </item>
    <item>
      <title>Sin link valido</title>
      <link></link>
      <guid isPermaLink="false">empty-link-skip</guid>
      <pubDate>Mon, 27 Apr 2026 07:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""".encode('utf-8')


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


class RssParserTest(unittest.TestCase):
    """El parser puro — no depende de HTTP."""

    def test_parses_basic_items(self):
        items = main._parse_google_news_rss(SAMPLE_RSS_XML)
        # 3 items en el XML pero 1 sin link → filtrado, quedan 2
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['title'], 'Apple stock: UBS explains Q2 earnings - TradingView')
        self.assertIn('tradingview.com', items[0]['url'])

    def test_skips_items_without_required_fields(self):
        items = main._parse_google_news_rss(SAMPLE_RSS_XML)
        # El item sin link no debe estar
        titles = [i['title'] for i in items]
        self.assertNotIn('Sin link valido', titles)

    def test_pubdate_converted_to_iso(self):
        items = main._parse_google_news_rss(SAMPLE_RSS_XML)
        # RFC 822 → ISO
        self.assertIn('2026-04-28', items[0]['published_at'])

    def test_handles_malformed_xml(self):
        items = main._parse_google_news_rss(b'<not valid xml')
        self.assertEqual(items, [])

    def test_limit_respected(self):
        items = main._parse_google_news_rss(SAMPLE_RSS_XML, limit=1)
        self.assertEqual(len(items), 1)


class MarketRelevanceFilterTest(unittest.TestCase):
    """El filtro de relevancia para market/macro."""

    def test_passes_clear_market_news(self):
        cases = [
            "Apple stock soars on earnings beat",
            "Federal Reserve holds interest rates steady",
            "S&P 500 closes at record high",
            "El Merval subió 4% en la jornada",
            "Inflación de mayo: el IPC fue de 4.2%",
            "El dólar blue cerró a $1.500",
            "Bonos argentinos suben tras reunión con el FMI",
            "BCRA bajó la tasa de interés 5 puntos",
            "Nvidia earnings beat expectations on AI demand",
        ]
        for title in cases:
            self.assertTrue(
                main._is_market_relevant({'title': title, 'summary': None}),
                f"Falsamente rechazada: {title!r}",
            )

    def test_rejects_clearly_irrelevant_news(self):
        cases = [
            "Conocé los mejores destinos turísticos para julio",
            "Receta: cómo hacer milanesas crocantes",
            "Lionel Messi marcó un golazo ante Brasil",
            "Argentina: paro nacional de transportes para mañana",
            "Pronóstico: lluvias intensas en el AMBA",
            "Famous singer announces new world tour",
            "Recipe: 5-minute pasta dishes you can make tonight",
            "Local school district approves new curriculum",
        ]
        for title in cases:
            self.assertFalse(
                main._is_market_relevant({'title': title, 'summary': None}),
                f"Falsamente aceptada: {title!r}",
            )

    def test_passes_when_summary_has_keyword_but_title_doesnt(self):
        """Si el summary tiene la keyword, alcanza para que pase."""
        item = {
            'title': 'Reunión de funcionarios en Washington',
            'summary': 'Funcionarios del Tesoro y representantes del FMI debatieron sobre la deuda externa.',
        }
        self.assertTrue(main._is_market_relevant(item))

    def test_passes_empty_title_defensive(self):
        """Sin title, dejamos pasar (defensivo — raro en RSS bien-formado)."""
        self.assertTrue(main._is_market_relevant({'title': '', 'summary': None}))
        self.assertTrue(main._is_market_relevant({}))

    def test_case_insensitive(self):
        """Capitalización del title no debe afectar match."""
        self.assertTrue(main._is_market_relevant({'title': 'STOCKS RALLY', 'summary': None}))
        self.assertTrue(main._is_market_relevant({'title': 'Stocks Rally', 'summary': None}))
        self.assertTrue(main._is_market_relevant({'title': 'stocks rally', 'summary': None}))


class FetcherTest(unittest.TestCase):
    """Fetcher HTTP — mockeado."""

    def setUp(self):
        main._news_fetched_at.clear()

    def test_fetcher_returns_empty_on_http_error(self):
        with patch('main.requests.get') as mock_get:
            mock_get.return_value.status_code = 500
            items = main._fetch_google_news_rss("AAPL")
        self.assertEqual(items, [])

    def test_fetcher_returns_empty_on_exception(self):
        with patch('main.requests.get', side_effect=Exception('network')):
            items = main._fetch_google_news_rss("AAPL")
        self.assertEqual(items, [])

    def test_fetcher_uses_es_locale_for_spanish(self):
        with patch('main.requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = SAMPLE_RSS_XML
            main._fetch_google_news_rss("BCRA", lang="es")
            url = mock_get.call_args[0][0]
        self.assertIn('hl=es', url)
        self.assertIn('gl=AR', url)


class MarketNewsEndpointTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"market-news-{self.id()}@rendi.test")
        main._news_fetched_at.clear()
        with conn:
            conn.execute("DELETE FROM news")
        # Marcar todos los queries macro como ya fetcheados (evita fetch real en tests)
        for q, _, _ in main.MARKET_NEWS_QUERIES:
            main._news_fetched_at[f"market:{q}"] = main.time.time()
            main._news_fetched_at[f"macro:{q}"] = main.time.time()
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.token}"})

    def _seed_news(self, title, url, category='market', query='S&P 500', external_id=None):
        conn = main.get_db()
        external_id = external_id or url
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO news
                   (source, external_id, title, summary, url, image_url,
                    published_at, tickers, category, query_source, fetched_at)
                   VALUES ('google_news_rss', ?, ?, NULL, ?, NULL,
                           '2026-05-12T10:00:00Z', NULL, ?, ?, '2026-05-12T10:00:00Z')""",
                (external_id, title, url, category, query),
            )
        conn.close()

    def test_market_news_returns_items(self):
        self._seed_news('FED holds rates steady', 'http://example.com/fed1')
        self._seed_news('Merval cae 2%', 'http://example.com/merval', category='market', query='Merval Argentina')
        res = self._get("/api/news/market?limit=10")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertGreaterEqual(body['count'], 2)
        titles = {n['title'] for n in body['news']}
        self.assertIn('FED holds rates steady', titles)

    def test_market_news_ordered_by_recency(self):
        conn = main.get_db()
        with conn:
            conn.execute("""INSERT INTO news (source, external_id, title, url, published_at, category, query_source, fetched_at)
                            VALUES ('google_news_rss', 'a1', 'Old news', 'http://x/1', '2026-01-01T10:00:00Z', 'market', 'q', '2026-05-12T00:00:00Z')""")
            conn.execute("""INSERT INTO news (source, external_id, title, url, published_at, category, query_source, fetched_at)
                            VALUES ('google_news_rss', 'a2', 'New news', 'http://x/2', '2026-05-10T10:00:00Z', 'market', 'q', '2026-05-12T00:00:00Z')""")
        conn.close()
        res = self._get("/api/news/market?limit=10")
        body = res.json()
        self.assertEqual(body['news'][0]['title'], 'New news')

    def test_market_news_limit_validation(self):
        for limit in (-1, 0, 200):
            res = self._get(f"/api/news/market?limit={limit}")
            self.assertEqual(res.status_code, 422, f"limit={limit}")

    def test_market_news_dedup_by_external_id(self):
        """Insertar 2 veces el mismo (source, external_id) sólo persiste una vez."""
        self._seed_news('FED news', 'http://x/fed', external_id='dedup-1')
        self._seed_news('FED news copia', 'http://x/fed', external_id='dedup-1')  # mismo external_id
        conn = main.get_db()
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM news WHERE external_id='dedup-1'"
        ).fetchone()
        conn.close()
        self.assertEqual(rows['n'], 1)


class PortfolioNewsEndpointTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"portfolio-news-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "IBKR", "USDT")
        main._news_fetched_at.clear()
        with conn:
            conn.execute("DELETE FROM news")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.token}"})

    def _seed_portfolio_news(self, title, ticker, query=None):
        query = query or f"{ticker} stock"
        # Marcar como ya fetcheado para evitar HTTP real
        main._news_fetched_at[f"portfolio:{query}"] = main.time.time()
        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT INTO news (source, external_id, title, url, published_at,
                                     category, query_source, fetched_at)
                   VALUES ('google_news_rss', ?, ?, ?, '2026-05-12T10:00:00Z',
                           'portfolio', ?, '2026-05-12T10:00:00Z')""",
                (f"{ticker}-{title[:20]}", title, f"http://x/{ticker}", query),
            )
        conn.close()

    def test_empty_portfolio_returns_empty(self):
        res = self._get("/api/news/portfolio")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['news'], [])

    def test_filters_to_user_tickers(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()
        self._seed_portfolio_news('AAPL good news', 'AAPL')
        self._seed_portfolio_news('NVDA news', 'NVDA')  # user no tiene NVDA

        res = self._get("/api/news/portfolio")
        body = res.json()
        titles = [n['title'] for n in body['news']]
        self.assertIn('AAPL good news', titles)
        self.assertNotIn('NVDA news', titles)

    def test_excludes_crypto_and_cash(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "BTC", qty=0.5)  # crypto excluido
        _add_position(conn, self.uid, "IBKR", "USDT", qty=0, is_cash=1)  # cash excluido
        conn.commit()
        conn.close()

        # Si hay noticias de BTC en la tabla igual, no deben aparecer
        self._seed_portfolio_news('BTC crash', 'BTC')

        res = self._get("/api/news/portfolio")
        body = res.json()
        # BTC está en CRYPTO_SYMBOLS, no debe haber sido refetcheado ni filtrado
        # El test es por endpoint behavior, not por refetch — basta verificar que
        # las noticias seedeadas para BTC no aparecen porque el filtro excluye BTC.
        # En este caso, no se seedea ningún query para tickers válidos, así que vacío.
        titles = [n['title'] for n in body['news']]
        self.assertNotIn('BTC crash', titles)

    def test_news_includes_ticker_field(self):
        conn = main.get_db()
        _add_position(conn, self.uid, "IBKR", "AAPL", qty=10)
        conn.commit()
        conn.close()
        self._seed_portfolio_news('AAPL good news', 'AAPL')

        res = self._get("/api/news/portfolio")
        body = res.json()
        self.assertGreaterEqual(len(body['news']), 1)
        self.assertEqual(body['news'][0]['ticker'], 'AAPL')

    def test_unauthorized_without_token(self):
        res = self.client.get("/api/news/portfolio")
        self.assertIn(res.status_code, (401, 403))


class RefreshNewsQueryFilterTest(unittest.TestCase):
    """Verifica que _refresh_news_query aplica el filtro market/macro pero
    no filtra noticias de portfolio (que ya están limitadas por ticker)."""

    def setUp(self):
        conn = main.get_db()
        with conn:
            conn.execute("DELETE FROM news")
        conn.close()
        main._news_fetched_at.clear()

    def _make_items(self, *titles):
        return [
            {
                'external_id': f'id-{i}',
                'title': t,
                'summary': None,
                'url': f'http://example.com/{i}',
                'published_at': '2026-05-12T10:00:00Z',
            }
            for i, t in enumerate(titles)
        ]

    def test_market_category_filters_irrelevant(self):
        items = self._make_items(
            "Federal Reserve holds interest rates",       # relevante
            "Receta de milanesas paso a paso",            # NO relevante
            "S&P 500 closes at record high",              # relevante
        )
        with patch('main._fetch_google_news_rss', return_value=items):
            inserted = main._refresh_news_query(main.get_db(), "Fed", "en", "market")
        # 2 relevantes deberían haber pasado, 1 descartada
        self.assertEqual(inserted, 2)
        conn = main.get_db()
        rows = conn.execute("SELECT title FROM news ORDER BY external_id").fetchall()
        conn.close()
        titles = [r['title'] for r in rows]
        self.assertIn("Federal Reserve holds interest rates", titles)
        self.assertIn("S&P 500 closes at record high", titles)
        self.assertNotIn("Receta de milanesas paso a paso", titles)

    def test_macro_category_also_filters(self):
        items = self._make_items(
            "Inflación de abril: el IPC subió 3.5%",
            "Lluvias intensas afectan a Buenos Aires",
        )
        with patch('main._fetch_google_news_rss', return_value=items):
            inserted = main._refresh_news_query(main.get_db(), "IPC", "es", "macro")
        self.assertEqual(inserted, 1)

    def test_portfolio_category_does_not_filter(self):
        """Las noticias de portfolio ya vienen filtradas por ticker — no aplicamos
        el filtro genérico de keywords."""
        items = self._make_items(
            "AAPL announces new iPhone in fall event",   # sin keywords financieras
            "Apple reports record quarterly earnings",    # con keyword
        )
        with patch('main._fetch_google_news_rss', return_value=items):
            inserted = main._refresh_news_query(main.get_db(), "AAPL stock", "en", "portfolio")
        # Ambas deben entrar (filtro no aplica a portfolio)
        self.assertEqual(inserted, 2)


class EnsureNewsBatchParallelTest(unittest.TestCase):
    """Tests del helper paralelo — TTL skip, aislamiento de errores, timestamps."""

    def setUp(self):
        main._news_fetched_at.clear()
        conn = main.get_db()
        with conn:
            conn.execute("DELETE FROM news")
        conn.close()

    def test_skips_queries_within_ttl(self):
        """Si la query está fresh (dentro de TTL), no se llama a _refresh_news_query."""
        now = main.time.time()
        # Marcamos query como fetcheada hace 10s; TTL es 60s → debe saltar.
        main._news_fetched_at["test:fresh-query"] = now - 10
        with patch('main._refresh_news_query') as mock_refresh:
            main._ensure_news_batch_parallel(
                [("fresh-query", "en", "test")],
                ttl_seconds=60,
            )
        mock_refresh.assert_not_called()

    def test_calls_refresh_for_stale_queries(self):
        """Si la query es stale (más allá del TTL), se refresca."""
        now = main.time.time()
        main._news_fetched_at["test:stale-query"] = now - 9999  # muy viejo
        with patch('main._refresh_news_query') as mock_refresh:
            main._ensure_news_batch_parallel(
                [("stale-query", "en", "test")],
                ttl_seconds=60,
            )
        mock_refresh.assert_called_once()
        # Args posicionales: (conn, query, lang, category)
        args, kwargs = mock_refresh.call_args
        self.assertEqual(args[1], "stale-query")
        self.assertEqual(args[2], "en")
        self.assertEqual(args[3], "test")

    def test_calls_refresh_for_unknown_queries(self):
        """Una query sin entry previa en _news_fetched_at es tratada como stale."""
        with patch('main._refresh_news_query') as mock_refresh:
            main._ensure_news_batch_parallel(
                [("first-time", "en", "test")],
                ttl_seconds=60,
            )
        mock_refresh.assert_called_once()

    def test_empty_queries_no_op(self):
        """Sin queries no spawnea threads ni llama a refresh."""
        with patch('main._refresh_news_query') as mock_refresh:
            main._ensure_news_batch_parallel([], ttl_seconds=60)
        mock_refresh.assert_not_called()

    def test_marks_query_as_fetched_after_success(self):
        """Tras un fetch exitoso, _news_fetched_at se updatea con timestamp reciente."""
        before = main.time.time()
        with patch('main._refresh_news_query', return_value=0):
            main._ensure_news_batch_parallel(
                [("query1", "en", "cat-a")],
                ttl_seconds=60,
            )
        after = main.time.time()
        ts = main._news_fetched_at.get("cat-a:query1")
        self.assertIsNotNone(ts)
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)

    def test_error_in_one_worker_does_not_break_batch(self):
        """Una query que falla no impide que las otras se procesen."""
        def _flaky(conn, query, lang, cat):
            if query == "bad":
                raise RuntimeError("simulated failure")
            return 0

        with patch('main._refresh_news_query', side_effect=_flaky):
            main._ensure_news_batch_parallel(
                [
                    ("good-1", "en", "test"),
                    ("bad",    "en", "test"),
                    ("good-2", "en", "test"),
                ],
                ttl_seconds=60,
            )

        # good-1 y good-2 deben quedar marcados; "bad" NO debe quedar marcado
        # (porque la excepción aborta la asignación de timestamp en el worker).
        self.assertIn("test:good-1", main._news_fetched_at)
        self.assertIn("test:good-2", main._news_fetched_at)
        self.assertNotIn("test:bad", main._news_fetched_at)

    def test_parallel_execution_is_faster_than_serial(self):
        """Smoke test: con queries que tardan 0.2s cada una, paralelo termina <1s
        para 5 queries (serial tomaría 1.0s+). Verifica que efectivamente
        corre en paralelo, no de forma secuencial.
        """
        def _slow(conn, query, lang, cat):
            main.time.sleep(0.2)
            return 0

        queries = [(f"q{i}", "en", "test") for i in range(5)]
        with patch('main._refresh_news_query', side_effect=_slow):
            start = main.time.time()
            main._ensure_news_batch_parallel(queries, ttl_seconds=60)
            elapsed = main.time.time() - start

        # Serial sería ~1.0s. Paralelo con 5 workers debería ser ~0.3s.
        # Damos margen amplio (0.8s) para entornos lentos como CI.
        self.assertLess(elapsed, 0.8, f"parallel took {elapsed:.2f}s, expected <0.8s")

    def test_respects_max_workers_cap(self):
        """Con max_workers=2 y 4 queries lentas, el wall time debe ser ~2x duración,
        no 1x (no todas en paralelo) ni 4x (no secuencial).
        """
        def _slow(conn, query, lang, cat):
            main.time.sleep(0.15)
            return 0

        queries = [(f"q{i}", "en", "test") for i in range(4)]
        with patch('main._refresh_news_query', side_effect=_slow):
            start = main.time.time()
            main._ensure_news_batch_parallel(queries, ttl_seconds=60, max_workers=2)
            elapsed = main.time.time() - start

        # Con 4 queries × 0.15s y max 2 workers: 2 batches de 2 → ~0.3s.
        # Aceptamos 0.25-0.7s (margen para overhead).
        self.assertGreater(elapsed, 0.25, f"too fast — workers not capped? {elapsed:.2f}s")
        self.assertLess(elapsed, 0.7,    f"too slow — not parallel?      {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
