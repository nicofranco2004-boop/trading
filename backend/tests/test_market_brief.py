"""Resumen del mercado por mail — backend/market_brief.py.

⚠️ CASI TODOS ESTOS TESTS ENTRAN POR EL ENDPOINT DEL CRON, no llamando a
`run_briefs()` a mano. Es la regla del repo y acá no es ceremonia: lo que se
quiere certificar es justamente que el cron trae las noticias ANTES de
redactar. Un test que llamara al armador directo dejaría ese paso afuera y
saldría en verde mientras producción manda el diario de ayer.

El endpoint lanza un hilo y contesta al instante (para no comerse el 502 del
gateway), así que `_ThreadSincrono` lo hace correr en el acto: sin eso el test
chequearía el resultado antes de que el trabajo empiece.

⚠️ SIN RED Y SIN MODELO: el fetch de noticias, el envío de mails y la narración
están mockeados. El mock del modelo vive en `setUp` justamente para que no
dependa de que cada test se acuerde — sin él la suite salía a la API con la key
del entorno, tardaba 50 segundos en vez de 1 y gastaba plata en cada corrida.
La calidad de lo que escribe el modelo NO se mide acá: eso se mira a mano
contra material real, porque un test con un texto esperado a mano certifica una
redacción que ya no existe.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402  (conftest ya seteó DB_PATH temporal)
import market_brief              # noqa: E402
# Importado acá a propósito: `run_briefs` hace `from billing import emails`
# adentro y resuelve `send_market_brief` en el momento de la llamada, así que
# parchear el atributo del módulo alcanza — pero el módulo tiene que existir
# antes, o `patch("billing.emails...")` no lo encuentra.
from billing import emails       # noqa: E402

TOKEN = "tok-market-brief-test"


class _NarracionFake:
    """Lo que devolvería el modelo. Misma forma que MarketNarrative."""

    def __init__(self, titular="El mercado miró la tasa de la Fed",
                 mercado=None, tu_cartera=None):
        self.titular = titular
        self.mercado = mercado if mercado is not None else [
            "El rendimiento del bono de Estados Unidos a diez años tocó su nivel "
            "más alto desde 2007."]
        self.tu_cartera = tu_cartera if tu_cartera is not None else []


class _ThreadSincrono:
    """Thread de mentira: corre el target en start(). El endpoint del cron
    devuelve 200 apenas lanza el hilo; sin esto el assert corre antes."""

    def __init__(self, target=None, daemon=None, **kw):
        self._target = target

    def start(self):
        if self._target:
            self._target()


class MarketBriefTest(unittest.TestCase):

    def setUp(self):
        self.http = TestClient(main.app)
        os.environ["MARKET_BRIEF_TOKEN"] = TOKEN
        conn = main.get_db()
        try:
            for t in ("market_brief_log", "market_brief_prefs", "news",
                      "financial_events", "positions", "brokers", "users"):
                try:
                    conn.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            conn.execute("INSERT INTO users (id,email,name,password_hash) "
                         "VALUES (1,'nico@test.co','Nico','x')")
            conn.execute("INSERT INTO users (id,email,name,password_hash) "
                         "VALUES (2,'otro@test.co','Otro','x')")
            conn.execute("INSERT INTO brokers (id,user_id,name,currency) "
                         "VALUES (1,1,'Balanz','USD')")
            conn.commit()
        finally:
            conn.close()
        self.addCleanup(lambda: os.environ.pop("MARKET_BRIEF_TOKEN", None))

        # ⚠️ NINGÚN test llama al modelo de verdad. Sin esto la suite salía a
        # la API de Anthropic con la key del entorno: pasó de 1 segundo a 50 y
        # gastaba plata en cada corrida. El mock vive en setUp (no en cada
        # test) para que un test nuevo no se olvide y vuelva a abrir la
        # canilla; el que quiera otra narración la sobreescribe.
        p = patch.object(market_brief, "narrate", lambda *a, **k: _NarracionFake())
        p.start()
        self.addCleanup(p.stop)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _pos(self, asset, uid=1, qty=10):
        conn = main.get_db()
        try:
            conn.execute(
                """INSERT INTO positions (user_id, broker, asset, quantity,
                                          invested, is_cash)
                   VALUES (?,?,?,?,?,0)""", (uid, "Balanz", asset, qty, 1000))
            conn.commit()
        finally:
            conn.close()

    def _news(self, ticker, title, hours_ago=2, sentiment="neutral"):
        # ⚠️ utcnow, no now: producción estampa las dos fechas en UTC
        # (`_persist_news_items` y `_rfc822_to_iso`). Con el reloj LOCAL el
        # `fetched_at` de prueba quedaba 3 horas atrasado contra el corte real
        # y el test medía un reloj que no es el de producción.
        ahora = datetime.utcnow()
        pub = (ahora - timedelta(hours=hours_ago)).isoformat()
        conn = main.get_db()
        try:
            conn.execute(
                """INSERT INTO news (source, external_id, title, summary, url,
                                     published_at, category, query_source,
                                     sentiment, fetched_at)
                   VALUES ('google_news_rss',?,?,'',?,?,'portfolio',?,?,?)""",
                (f"{ticker}-{title}", title, f"https://x.co/{ticker}", pub,
                 f"{ticker} acciones", sentiment, ahora.isoformat() + "Z"))
            conn.commit()
        finally:
            conn.close()

    def _evento(self, ticker, tipo, day):
        conn = main.get_db()
        try:
            conn.execute(
                """INSERT INTO financial_events (ticker, event_type, event_date,
                                                 fetched_at)
                   VALUES (?,?,?,?)""",
                (ticker, tipo, day, datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def _suscribir(self, uid=1, enabled=1):
        conn = main.get_db()
        try:
            conn.execute("INSERT OR REPLACE INTO market_brief_prefs "
                         "(user_id, enabled) VALUES (?,?)", (uid, enabled))
            conn.commit()
        finally:
            conn.close()

    def _correr_cron(self, refresh_ret=3):
        """Dispara el cron real y devuelve (respuesta, mails, mock_refresh)."""
        enviados = []

        def _fake_send(*, to, user_name="", brief):
            enviados.append({"to": to, "brief": brief})
            return True

        with patch.object(main.threading, "Thread", _ThreadSincrono), \
             patch.object(emails, "send_market_brief", _fake_send), \
             patch.object(market_brief, "_refresh_news_for",
                          return_value=refresh_ret) as m_refresh, \
             patch.object(market_brief, "SEND_GAP_SECONDS", 0):
            r = self.http.post(f"/api/market-brief/run-cron?token={TOKEN}")
        return r, enviados, m_refresh

    # ── el gate del cron ─────────────────────────────────────────────────────

    def test_cron_sin_token_cerrado(self):
        r = self.http.post("/api/market-brief/run-cron")
        self.assertIn(r.status_code, (401, 503))

    def test_cron_token_invalido_es_401_no_503(self):
        """401 = la variable está seteada; 503 = falta. Es el truco que permite
        chequear si el cron está configurado SIN dispararlo (y sin mandarle
        mails a usuarios reales)."""
        r = self.http.post("/api/market-brief/run-cron?token=cualquier-cosa")
        self.assertEqual(r.status_code, 401)

    # ── el camino completo ───────────────────────────────────────────────────

    def test_suscripto_recibe_sus_noticias(self):
        self._pos("NVDA")
        self._news("NVDA", "Nvidia presenta resultados")
        self._suscribir()

        r, enviados, _ = self._correr_cron()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(enviados), 1)
        self.assertEqual(enviados[0]["to"], "nico@test.co")
        titulos = [n["title"] for n in enviados[0]["brief"]["news"]]
        self.assertIn("Nvidia presenta resultados", titulos)

    def test_no_suscripto_no_recibe_nada(self):
        """Opt-in de verdad: sin fila de preferencia, no se manda."""
        self._pos("NVDA")
        self._news("NVDA", "Nvidia presenta resultados")
        # a propósito: NO se llama a _suscribir()

        _, enviados, _ = self._correr_cron()
        self.assertEqual(enviados, [])

    def test_apagado_explicito_no_recibe(self):
        self._pos("NVDA")
        self._news("NVDA", "Algo de Nvidia")
        self._suscribir(enabled=0)

        _, enviados, _ = self._correr_cron()
        self.assertEqual(enviados, [])

    def test_las_noticias_se_traen_ANTES_de_redactar(self):
        """EL test de esta fase.

        El recolector de noticias de Rendi no tiene reloj propio: corre al
        arrancar el proceso y cuando alguien abre la app. Quien activa este
        mail es justamente el que no entra todos los días, así que si el cron
        no sale a buscar, su cartera nunca tiene prensa fresca y el mail sale
        con lo de ayer.

        Se verifica de dos maneras, porque una sola no alcanza: que el fetch
        haya ocurrido, y que haya ocurrido ANTES de armar el primer mail.
        """
        self._pos("NVDA")
        self._news("NVDA", "Algo de Nvidia")
        self._suscribir()

        orden = []

        def _fake_refresh(tickers, get_db=None):
            orden.append(("fetch", sorted(tickers)))
            return 1

        def _fake_send(*, to, user_name="", brief):
            orden.append(("send", to))
            return True

        with patch.object(main.threading, "Thread", _ThreadSincrono), \
             patch.object(emails, "send_market_brief", _fake_send), \
             patch.object(market_brief, "_refresh_news_for", _fake_refresh), \
             patch.object(market_brief, "SEND_GAP_SECONDS", 0):
            self.http.post(f"/api/market-brief/run-cron?token={TOKEN}")

        self.assertEqual([p[0] for p in orden], ["fetch", "send"],
                         "el mail se armó antes de traer las noticias")
        self.assertEqual(orden[0][1], ["NVDA"])

    def test_el_fetch_es_uno_solo_para_la_union(self):
        """Dos personas con el mismo activo no lo buscan dos veces."""
        self._pos("GGAL", uid=1)
        self._pos("GGAL", uid=2)
        self._pos("NVDA", uid=2)
        self._news("GGAL", "Galicia sube")
        self._news("NVDA", "Nvidia sube")
        self._suscribir(1)
        self._suscribir(2)

        _, enviados, m_refresh = self._correr_cron()
        self.assertEqual(len(enviados), 2)
        self.assertEqual(m_refresh.call_count, 1)
        self.assertEqual(sorted(m_refresh.call_args[0][0]), ["GGAL", "NVDA"])

    def test_el_contador_de_noticias_nuevas_no_miente(self):
        """`_ensure_news_batch_parallel` NO devuelve nada — sus workers
        persisten cada uno por su lado. Leer su retorno daba un log que decía
        siempre "0 noticias nuevas" aunque entraran 45 (medido en vivo contra
        Google News). Un contador clavado en cero es peor que ninguno: el día
        que el cron falle de verdad, el log dice lo mismo que cuando anda.

        Acá se simula el batch real: no devuelve nada, pero escribe filas.
        """
        def _batch_que_escribe_pero_no_devuelve(specs, ttl, **kw):
            for q, _lang, _cat in specs:
                self._news(q.split(" ")[0], f"fresca de {q}", hours_ago=1)
            return None          # tal cual la función real

        with patch.object(main, "_ensure_news_batch_parallel",
                          _batch_que_escribe_pero_no_devuelve):
            n = market_brief._refresh_news_for(["NVDA", "GGAL"], main.get_db)
        self.assertEqual(n, 2, "el contador no vio las filas que entraron")

    def test_el_contador_no_suma_lo_que_ya_estaba(self):
        """Mide lo que entró en ESTA corrida, no el acumulado de la tabla."""
        self._news("NVDA", "vieja, de antes de la corrida", hours_ago=3)
        with patch.object(main, "_ensure_news_batch_parallel",
                          lambda *a, **k: None):
            n = market_brief._refresh_news_for(["NVDA"], main.get_db)
        self.assertEqual(n, 0)

    # ── idempotencia ─────────────────────────────────────────────────────────

    def test_correr_el_cron_dos_veces_manda_un_solo_mail(self):
        self._pos("NVDA")
        self._news("NVDA", "Algo de Nvidia")
        self._suscribir()

        _, primeros, _ = self._correr_cron()
        _, segundos, _ = self._correr_cron()
        self.assertEqual(len(primeros), 1)
        self.assertEqual(segundos, [], "el segundo disparo duplicó el mail")

    def test_el_rechazo_del_envio_no_marca_como_enviado(self):
        """Si el servicio de mail rechaza, esa persona NO puede quedar sellada:
        se quedaría sin su resumen y nadie se entera. La próxima corrida tiene
        que reintentar."""
        self._pos("NVDA")
        self._news("NVDA", "Algo de Nvidia")
        self._suscribir()

        with patch.object(main.threading, "Thread", _ThreadSincrono), \
             patch.object(emails, "send_market_brief", return_value=False), \
             patch.object(market_brief, "_refresh_news_for", return_value=0), \
             patch.object(market_brief, "SEND_GAP_SECONDS", 0):
            self.http.post(f"/api/market-brief/run-cron?token={TOKEN}")

        conn = main.get_db()
        try:
            marcado = conn.execute(
                "SELECT 1 FROM market_brief_log WHERE user_id=1").fetchone()
        finally:
            conn.close()
        self.assertIsNone(marcado, "quedó sellado un mail que nunca salió")

        # Y la corrida siguiente lo reintenta.
        _, enviados, _ = self._correr_cron()
        self.assertEqual(len(enviados), 1)

    # ── nunca un mail vacío ──────────────────────────────────────────────────

    def test_sin_noticias_ni_eventos_no_se_manda(self):
        """Un mail vacío entrena a la persona a no abrirlo, y el día que haya
        algo importante ya no lo mira."""
        self._pos("NVDA")            # tiene cartera…
        self._suscribir()            # …y está suscripto, pero no hay prensa

        _, enviados, _ = self._correr_cron()
        self.assertEqual(enviados, [])

    def test_sin_cartera_no_se_manda(self):
        self._suscribir()
        self._news("NVDA", "Algo de Nvidia")   # noticia de un activo que no tiene

        _, enviados, _ = self._correr_cron()
        self.assertEqual(enviados, [])

    def test_solo_eventos_sin_noticias_NO_alcanza(self):
        """"Hoy AAPL presenta balance" es una línea de calendario, no un
        resumen del mercado. Sin material para narrar no hay mail: el mail
        promete contarte qué pasó, y una agenda sola no cumple esa promesa."""
        self._pos("AAPL")
        self._evento("AAPL", "earnings", market_brief._today_art())
        self._suscribir()

        _, enviados, _ = self._correr_cron()
        self.assertEqual(enviados, [])

    def test_los_eventos_viajan_junto_a_la_narracion(self):
        """Cuando SÍ hay material, la agenda va igual — y no pasa por el
        modelo: son datos duros del calendario."""
        self._pos("AAPL")
        self._news("AAPL", "Apple presenta resultados hoy")
        self._evento("AAPL", "earnings", market_brief._today_art())
        self._suscribir()

        _, enviados, _ = self._correr_cron()
        self.assertEqual(len(enviados), 1)
        eventos = enviados[0]["brief"]["events"]
        self.assertEqual(eventos[0]["ticker"], "AAPL")
        self.assertEqual(eventos[0]["label"], "Reporte trimestral")

    # ── contenido ────────────────────────────────────────────────────────────

    def test_no_se_cuelan_noticias_de_activos_ajenos(self):
        self._pos("NVDA")
        self._news("NVDA", "Noticia mía")
        self._news("TSLA", "Noticia ajena")
        self._suscribir()

        _, enviados, _ = self._correr_cron()
        titulos = [n["title"] for n in enviados[0]["brief"]["news"]]
        self.assertIn("Noticia mía", titulos)
        self.assertNotIn("Noticia ajena", titulos)

    def test_un_activo_con_mucha_prensa_no_tapa_al_resto(self):
        """Tope por ticker: si no, NVDA con 8 notas deja a GGAL afuera."""
        self._pos("NVDA")
        self._pos("GGAL")
        for i in range(8):
            self._news("NVDA", f"Nvidia nota {i}", hours_ago=1)
        self._news("GGAL", "Galicia única nota", hours_ago=5)
        self._suscribir()

        _, enviados, _ = self._correr_cron()
        news = enviados[0]["brief"]["news"]
        por_ticker = {}
        for n in news:
            por_ticker[n["ticker"]] = por_ticker.get(n["ticker"], 0) + 1
        self.assertLessEqual(por_ticker.get("NVDA", 0),
                             market_brief.MAX_NEWS_PER_TICKER)
        self.assertEqual(por_ticker.get("GGAL"), 1)

    def test_las_viejas_quedan_afuera(self):
        self._pos("NVDA")
        self._news("NVDA", "De hoy", hours_ago=2)
        self._news("NVDA", "De la semana pasada", hours_ago=24 * 8)
        self._suscribir()

        _, enviados, _ = self._correr_cron()
        titulos = [n["title"] for n in enviados[0]["brief"]["news"]]
        self.assertIn("De hoy", titulos)
        self.assertNotIn("De la semana pasada", titulos)

    # ── la narración ─────────────────────────────────────────────────────────

    def _macro(self, title, hours_ago=4, categoria="macro",
               query="Federal Reserve interest rates"):
        ahora = datetime.utcnow()
        conn = main.get_db()
        try:
            conn.execute(
                """INSERT INTO news (source, external_id, title, summary, url,
                                     published_at, category, query_source,
                                     sentiment, fetched_at)
                   VALUES ('google_news_rss',?,?,'','https://x.co/m',?,?,?, 'neutral',?)""",
                (f"macro-{title}", title,
                 (ahora - timedelta(hours=hours_ago)).isoformat(),
                 categoria, query, ahora.isoformat() + "Z"))
            conn.commit()
        finally:
            conn.close()

    def test_el_mail_lleva_la_narracion_no_los_titulares(self):
        """El cambio de fondo: el cuerpo es prosa, no una lista. Los titulares
        siguen viajando en el dict (vista previa y auditoría) pero el mail no
        los muestra — eso es lo que se sacó."""
        self._pos("NVDA")
        self._news("NVDA", "Nvidia sube")
        self._macro("La Fed define la tasa el miércoles")
        self._suscribir()

        _, enviados, _ = self._correr_cron()
        brief = enviados[0]["brief"]
        self.assertIn("narrative", brief)
        self.assertTrue(brief["narrative"]["titular"])
        self.assertTrue(brief["narrative"]["mercado"])

        # Y el HTML del mail no lista los titulares crudos.
        cuerpo = {}
        with patch.object(emails, "_send",
                          lambda to, subject, html, text, **kw: cuerpo.update(
                              html=html, text=text, subject=subject) or True):
            emails.send_market_brief(to="a@b.co", user_name="Nico", brief=brief)
        self.assertNotIn("Nvidia sube", cuerpo["html"])
        self.assertIn(brief["narrative"]["titular"], cuerpo["html"])
        self.assertEqual(cuerpo["subject"], brief["narrative"]["titular"])

    def test_el_contexto_macro_entra_aunque_no_tenga_ese_activo(self):
        """Lo que convierte esto en un resumen del MERCADO: la tasa de la Fed
        y el petróleo importan tengas o no un activo que los mencione."""
        self._pos("GGAL")
        self._macro("El crudo sube por tensiones en Medio Oriente")
        self._macro("La inflación de agosto fue del 2,1% según el INDEC")
        self._suscribir()

        visto = {}
        with patch.object(market_brief, "narrate",
                          lambda ctx, news, tk: visto.update(
                              ctx=ctx, news=news) or _NarracionFake()):
            _, enviados, _ = self._correr_cron()

        self.assertEqual(len(enviados), 1, "no se mandó pese a haber macro")
        titulos = [c["title"] for c in visto["ctx"]]
        self.assertIn("El crudo sube por tensiones en Medio Oriente", titulos)
        self.assertEqual(visto["news"], [], "no tiene noticias de sus activos")

    def test_un_tema_ruidoso_no_tapa_a_los_demas(self):
        """Un día movido de tasas genera veinte notas sobre tasas. Sin cupo por
        tema se llevan todos los lugares del contexto y el petróleo, la
        inflación argentina y el dólar no entran ni una vez — el resumen queda
        monotemático justo el día que más pasa."""
        for i in range(20):
            self._macro(f"Nota de tasas número {i}", hours_ago=1)
        self._macro("El petróleo sube por tensiones", hours_ago=6,
                    query="petroleo Brent barril")
        self._macro("La inflación fue del 2,1%", hours_ago=8,
                    query="inflación Argentina INDEC")

        conn = main.get_db()
        try:
            ctx = market_brief.market_context(
                conn, market_brief._news_window_start(market_brief._today_art()))
        finally:
            conn.close()

        temas = {c["tema"] for c in ctx}
        self.assertIn("petroleo Brent barril", temas,
                      "las notas de tasas taparon al petróleo")
        self.assertIn("inflación Argentina INDEC", temas)
        de_tasas = sum(1 for c in ctx
                       if c["tema"] == "Federal Reserve interest rates")
        self.assertLessEqual(de_tasas, market_brief.MAX_CONTEXT_PER_TOPIC)

    def test_el_contexto_no_deja_entrar_noticias_viejas(self):
        """La tabla `news` ACUMULA histórico: nunca se purga. Sin el corte por
        fecha, un resumen de hoy podría contar el mundo de hace tres semanas
        con total aplomo — y no habría forma de notarlo leyéndolo.

        Ya pasó de verdad, aunque del lado bueno: las primeras búsquedas de
        petróleo trajeron notas del 19 de agosto y la ventana las descartó.
        """
        self._macro("Noticia de esta mañana", hours_ago=3)
        self._macro("Noticia de hace tres semanas", hours_ago=24 * 21,
                    query="US CPI inflation")
        self._macro("Noticia de hace cuatro días", hours_ago=24 * 4,
                    query="Merval acciones Argentina")

        conn = main.get_db()
        try:
            ctx = market_brief.market_context(
                conn, market_brief._news_window_start(market_brief._today_art()))
        finally:
            conn.close()

        titulos = [c["title"] for c in ctx]
        self.assertIn("Noticia de esta mañana", titulos)
        self.assertNotIn("Noticia de hace tres semanas", titulos)
        self.assertNotIn("Noticia de hace cuatro días", titulos)

    def test_el_filtro_deja_pasar_petroleo_en_castellano(self):
        """La lista de commodities estaba entera en inglés: "Oil prices surge"
        entraba y "El petróleo Brent sube 3%" —un titular normal de cualquier
        medio argentino— se caía del feed."""
        for titulo in ("El petróleo Brent sube 3% y se acerca a los 108 dólares",
                       "El crudo trepa por la tensión en Medio Oriente",
                       "El barril de WTI cerró en alza"):
            self.assertTrue(main._is_market_relevant({"title": titulo, "summary": ""}),
                            f"el filtro descarta: {titulo}")

    def test_sin_narracion_no_se_manda_el_mail(self):
        """No hay degradado a lista: si el modelo falla, no sale nada. Un mail
        que no cumple lo que promete es peor que ninguno."""
        self._pos("NVDA")
        self._news("NVDA", "Nvidia sube")
        self._macro("La Fed define la tasa")
        self._suscribir()

        with patch.object(market_brief, "narrate", lambda *a, **k: None):
            _, enviados, _ = self._correr_cron()
        self.assertEqual(enviados, [])

        # Y NO queda sellado: mañana se reintenta.
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM market_brief_log WHERE user_id=1").fetchone())
        finally:
            conn.close()

    def test_el_modelo_no_ve_los_activos_sin_noticias(self):
        """🔴 El bug que apareció en el primer ejemplo con material 100% real.

        Cartera de siete activos, titulares de sólo dos, y el modelo habló de
        los siete: escribió "el petróleo en alza beneficia a YPFD y PAMP: sus
        acciones subieron" sin tener una sola noticia de ninguna de las dos.

        La causa no era el prompt (que ya lo prohibía) sino el packet: le
        pasábamos la lista COMPLETA de activos, y un modelo que ve siete
        nombres siente que tiene que cubrirlos. Lo que no sabe lo deduce del
        contexto y lo escribe como hecho. El fix es sacarle el dato, no pedirle
        que no lo use.
        """
        news = [{"ticker": "NVDA", "title": "Nvidia sube"},
                {"ticker": "AAPL", "title": "Apple firme"}]
        cartera = ["GGAL", "YPFD", "AL30", "PAMP", "NVDA", "MELI", "AAPL"]

        packet = market_brief._packet_para_narrar([], news, cartera)
        crudo = json.dumps(packet, ensure_ascii=False)

        self.assertEqual(packet["activos_con_noticias"], ["AAPL", "NVDA"])
        for sin_noticias in ("GGAL", "YPFD", "AL30", "PAMP", "MELI"):
            self.assertNotIn(sin_noticias, crudo,
                             f"{sin_noticias} no tiene noticias y llegó al modelo")

    def test_el_modelo_no_ve_los_montos_de_la_cartera(self):
        """La frontera que evita que un resumen invente un dividendo: el
        modelo recibe titulares y códigos de activo, nunca cuánto tiene ni
        cuánto vale."""
        self._pos("NVDA", qty=999)
        self._news("NVDA", "Nvidia sube")
        self._macro("La Fed define la tasa")
        self._suscribir()

        visto = {}
        with patch.object(market_brief, "narrate",
                          lambda ctx, news, tk: visto.update(
                              ctx=ctx, news=news, tk=tk) or _NarracionFake()):
            self._correr_cron()

        packet = market_brief._packet_para_narrar(
            visto["ctx"], visto["news"], visto["tk"])
        crudo = json.dumps(packet, ensure_ascii=False)
        self.assertIn("NVDA", crudo, "tiene que saber de qué activos hablar")
        for prohibido in ("999", "quantity", "invested", "cantidad"):
            self.assertNotIn(prohibido, crudo,
                             f"el modelo está viendo '{prohibido}'")

    def test_la_narracion_queda_guardada_para_releerla(self):
        self._pos("NVDA")
        self._news("NVDA", "Nvidia sube")
        self._macro("La Fed define la tasa")
        self._suscribir()

        self._correr_cron()
        conn = main.get_db()
        try:
            guardada = market_brief.sent_narrative(
                conn, 1, market_brief._today_art())
        finally:
            conn.close()
        self.assertIsNotNone(guardada, "no quedó registro de lo que se mandó")
        self.assertEqual(guardada["titular"], _NarracionFake().titular)

    # ── la ventana del lunes ─────────────────────────────────────────────────

    def test_el_lunes_la_ventana_cubre_el_fin_de_semana(self):
        """De martes a viernes miramos 24 horas. El lunes tienen que ser 72, o
        el cierre de Wall Street del viernes y todo lo del sábado y el domingo
        no aparecen nunca en ningún mail."""
        lunes = "2026-09-14"      # lunes
        martes = "2026-09-15"     # martes
        self.assertEqual(datetime.fromisoformat(lunes).weekday(), 0)

        ini_lunes = datetime.fromisoformat(market_brief._news_window_start(lunes))
        ini_martes = datetime.fromisoformat(market_brief._news_window_start(martes))

        self.assertEqual(datetime.fromisoformat(lunes) - ini_lunes,
                         timedelta(hours=72))
        self.assertEqual(datetime.fromisoformat(martes) - ini_martes,
                         timedelta(hours=24))

    # ── preferencia por endpoint ─────────────────────────────────────────────

    def test_prefs_arrancan_apagadas_y_se_prenden(self):
        hdr = {"Authorization": f"Bearer {main.create_token(1)}"}
        got = self.http.get("/api/market-brief/prefs", headers=hdr)
        self.assertEqual(got.status_code, 200, got.text)
        self.assertFalse(got.json()["enabled"], "no es opt-in: vino prendido")

        r = self.http.patch("/api/market-brief/prefs", json={"enabled": True},
                            headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(
            self.http.get("/api/market-brief/prefs", headers=hdr).json()["enabled"])

        # y se puede volver a apagar
        self.http.patch("/api/market-brief/prefs", json={"enabled": False},
                        headers=hdr)
        self.assertFalse(
            self.http.get("/api/market-brief/prefs", headers=hdr).json()["enabled"])

    def test_borrar_la_cuenta_se_lleva_las_dos_tablas(self):
        """Las columnas se llaman `user_id` justamente para que el barrido
        genérico del borrado de cuenta las limpie sin que nadie las liste a
        mano. Si alguien las renombra, este test lo caza."""
        conn = main.get_db()
        try:
            cols_prefs = [r[1] for r in conn.execute(
                "PRAGMA table_info(market_brief_prefs)").fetchall()]
            cols_log = [r[1] for r in conn.execute(
                "PRAGMA table_info(market_brief_log)").fetchall()]
        finally:
            conn.close()
        self.assertIn("user_id", cols_prefs)
        self.assertIn("user_id", cols_log)


if __name__ == "__main__":
    unittest.main()
