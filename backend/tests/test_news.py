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


if __name__ == "__main__":
    unittest.main()
