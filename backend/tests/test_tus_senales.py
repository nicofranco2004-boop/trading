"""«Tus señales» y el resumen de los sábados (pieza 15, senales_semana.py).

Entra por el camino de producción: las posiciones y la watchlist se cargan por
HTTP, las velas las guarda el trabajo nocturno real (`main._run_velas_diarias_job`)
con Yahoo reemplazado en su punto más bajo, la pantalla pide GET
/api/tus-senales y el resumen sale por el mismo cron que las alertas
(`main._resumen_semanal_job`, que llama `_evaluar_alertas_job`), con su
`now` en UTC como lo pega el cron.

Los casos que importan:
  · trae lo que TENÉS y lo que sigue tu WATCHLIST, cada uno marcado, con el
    peso de cada tenencia sobre toda tu plata;
  · un cruce de hace 30 días NO es «de esta semana»;
  · el resumen sale el sábado desde las 10:00 de ARGENTINA: no el viernes a las
    22 (en UTC ya es sábado), no a las 9:59, y una sola vez;
  · sin cambios en la semana no se manda nada (pero el % se guarda igual);
  · «No quiero» (o no haber elegido): no se manda nada;
  · el % de cada sábado se guarda y el sábado siguiente es «la semana pasada»;
  · el % es UNA cuenta (senales_semana.reparto, 28/10): la Cartera (POST
    /api/tecnico/cartera), el Panorama y la pestaña Señales (GET
    /api/tus-senales) y el mail dicen el MISMO número, con sus grupos y el
    porqué de cada «sin lectura»; y «la semana pasada» llega también a quien
    nunca pidió el resumen.

Corre con: cd backend && python3 -m pytest tests/test_tus_senales.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import senales_semana  # noqa: E402
from fechas import hoy_art_date  # noqa: E402
from tests.test_radiografia_tecnica import YahooFalso, _ruedas  # noqa: E402

MEP = 1000.0


class YahooConHuecos(YahooFalso):
    """Como YahooFalso, pero `precios[t](i, d)` puede dar None: ese día el papel
    no cotizaba (uno que salió a la bolsa hace poco)."""

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        import pandas as pd
        f = self.precios.get(ticker)
        base = _ruedas(self.hoy, 760)
        filas = {} if f is None else {
            pd.Timestamp(d): c for d in _ruedas(self.hoy, 760 if period == "3y" else 22)
            for c in [f(base.index(d), d)] if c is not None}
        if not filas:
            return pd.DataFrame()
        idx = sorted(filas)
        c = [filas[k] for k in idx]
        return pd.DataFrame({"Open": c, "High": [x * 1.01 for x in c], "Low": [x * 0.99 for x in c],
                             "Close": c, "Volume": [1000.0] * len(c)}, index=pd.DatetimeIndex(idx))


def _sabado_de(hoy):
    """El último sábado hasta `hoy` (inclusive): sus velas ya están en el pasado."""
    return hoy - timedelta(days=(hoy.weekday() - 5) % 7)


def _utc(dia, hora_art, minuto=0):
    """El instante UTC (naive, como `datetime.utcnow()`) de una hora ARGENTINA."""
    return datetime(dia.year, dia.month, dia.day, hora_art, minuto) + timedelta(hours=3)


class TusSenalesTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily", "asset_last_price", "tendencia_semanal",
                      "resumen_semanal_prefs", "plazos_fijos"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Nico Prueba', 'x', 1, 1, 'pro')", (f"senales-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            self.email = f"senales-{tag}@rendi.test"
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.mails, self.pushes = [], []
        self._p = [
            mock.patch("main._check_rate_limit"),
            mock.patch("main._fetch_data912_equities", lambda: {}),
            # El dólar de valuación (sin red): MEP 1000.
            mock.patch("main._current_cedear_rate", lambda: MEP),
            mock.patch("billing.emails._send",
                       lambda to, subject, html, text, **kw: (self.mails.append(
                           {"to": to, "asunto": subject, "html": html, "texto": text}), True)[1]),
            mock.patch("main._send_push_to_user",
                       lambda uid, payload: (self.pushes.append(payload), 1)[1]),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    # — armado, como la app —

    def _velas(self, hoy):
        """La cartera de la pantalla del mockup, con las velas hasta el día
        anterior a `hoy`: NVDA cruzó sus promedios hace 3 ruedas, KO hace 30,
        AAPL (CEDEAR) baja afuera, GGAL argentina sube en dólares; en la
        watchlist, MSFT cruzó hace 2 ruedas."""
        self.yahoo = YahooFalso(hoy)
        p = mock.patch("pricing.yahoo._historia", self.yahoo)
        p.start()
        self._p.append(p)
        dias = _ruedas(hoy, 760)
        n = len(dias)
        self.dias, self.n = dias, n
        self._post("/api/brokers", {"name": "IOL", "currency": "ARS"})
        self._post("/api/brokers", {"name": "Schwab", "currency": "USD"})
        # Compras a precios parecidos a los de hoy: la valuación desconfía de un
        # precio 200 veces el costo (`_trust_mkt_value`) y usa el costo.
        for broker, asset, tipo, compra in (("Schwab", "NVDA", "STOCK", 100), ("Schwab", "KO", "STOCK", 100),
                                            ("IOL", "AAPL", "CEDEAR", 18000), ("IOL", "GGAL", "ACCION", 7000)):
            self._post("/api/positions", {"broker": broker, "asset": asset, "quantity": 10,
                                          "buy_price": compra, "asset_type": tipo})
        self._post("/api/watchlist", {"symbol": "MSFT"})
        self._seguida_desde("MSFT", dias[0])
        with main.db_abierta() as conn:
            for i, d in enumerate(dias):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), MEP * 1.1, MEP))
            # El último precio guardado, el que usa la valuación del servidor.
            for s, precio in (("NVDA", 150.0), ("KO", 150.0), ("AAPL.BA", 20000.0), ("GGAL.BA", 8000.0)):
                conn.execute("INSERT INTO asset_last_price (symbol, price, updated_at) VALUES (?,?,datetime('now'))",
                             (s, precio))
            conn.commit()
        self.yahoo.precios["NVDA"] = lambda i, d: 150.0 if i >= n - 3 else 100 - i * 0.01
        self.yahoo.precios["KO"] = lambda i, d: 150.0 if i >= n - 30 else 100 - i * 0.01
        self.yahoo.precios["AAPL"] = lambda i, d: 300 - i * 0.1
        self.yahoo.precios["AAPL.BA"] = lambda i, d: (300 - i * 0.1) * MEP / 20
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + i * 20
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0 if i >= n - 2 else 300 - i * 0.01
        main._run_velas_diarias_job()

    def _post(self, url, body):
        r = self.client.post(url, json=body, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _seguida_desde(self, symbol, dia, uid=None):
        """La watchlist la sigue desde `dia` (la pestaña y el mail cuentan lo
        de la watchlist desde que se agregó: ver `agregado_a_la_watchlist`). El
        alta por HTTP la fecha hoy; esto es la historia de alguien que la sigue
        desde antes."""
        with main.db_abierta() as conn:
            conn.execute("UPDATE watchlist SET added_at=? WHERE user_id=? AND symbol=?",
                         (f"{dia.isoformat()} 12:00:00", uid or self.uid, symbol))
            conn.commit()

    def _canal(self, canal):
        r = self.client.put("/api/tus-senales/canal", json={"canal": canal}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _cron(self, now):
        with main.db_abierta() as conn:
            return main._resumen_semanal_job(conn, now)

    def _filas(self):
        with main.db_abierta() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM tendencia_semanal WHERE user_id=? ORDER BY semana", (self.uid,)).fetchall()]

    # — la pestaña —

    def test_la_pestana_trae_lo_tuyo_y_la_watchlist_de_esta_semana(self):
        self._velas(hoy_art_date())
        r = self.client.get("/api/tus-senales", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        por = {}
        for x in s["senales"]:
            por.setdefault(x["asset"], []).append(x)

        # NVDA: lo tenés, cruzó los dos promedios hace 3 ruedas, con su peso.
        nvda = {x["tipo"]: x for x in por["NVDA"]}
        fecha = self.dias[self.n - 3].isoformat()
        self.assertEqual((nvda["media200"]["sentido"], nvda["media200"]["fecha"]), ("arriba", fecha))
        self.assertEqual(nvda["media50"]["fecha"], fecha)
        self.assertTrue(nvda["media200"]["tenes"])
        self.assertFalse(nvda["media200"]["watchlist"])
        # Peso = su valor / toda tu plata, con la valuación del servidor:
        # NVDA y KO 10 × US$150; AAPL 10 × $20.000 ÷ 1000; GGAL 10 × $8.000 ÷ 1000.
        total = 1500 + 1500 + 200 + 80
        self.assertAlmostEqual(nvda["media200"]["peso"], 1500 / total, places=6)
        self.assertEqual(nvda["media200"]["texto"],
                         "superó su promedio de 200 días: la tendencia de largo plazo pasó a ser alcista.")
        self.assertEqual(nvda["media200"]["etiqueta"], "Tendencia de largo plazo")

        # MSFT: no la tenés, la seguís; sin peso; «Ver gráfico» abre su ficha.
        msft = {x["tipo"]: x for x in por["MSFT"]}["media200"]
        self.assertEqual((msft["tenes"], msft["watchlist"], msft["peso"], msft["ficha"]),
                         (False, True, None, "MSFT"))

        # KO cruzó hace 30 ruedas: no es de esta semana.
        self.assertNotIn("media200", {x["tipo"] for x in por.get("KO", [])})
        self.assertNotIn("media50", {x["tipo"] for x in por.get("KO", [])})

        # Orden: el día más nuevo primero.
        fechas = [x["fecha"] for x in s["senales"]]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

        # % en tendencia alcista con la regla de la radiografía: NVDA, KO y GGAL
        # (en dólares sube) alcistas; AAPL bajista. 3080 / 3280 → 94 %.
        self.assertEqual(s["alcista"]["pct"], 94)
        self.assertIsNone(s["alcista"]["semana_pasada"], "para atrás no se reconstruye")
        self.assertEqual(s["tenes"]["activos"], 4)
        self.assertEqual(s["tenes"]["con_cambios"], 1, "de lo tuyo, sólo NVDA cambió")
        self.assertEqual(s["watchlist"], 1)
        self.assertEqual(s["canal"], "no", "sin elegir, no te llega nada (opt-in)")
        # La frase de «no es una recomendación» no va en cada cambio; la pone la pantalla.
        self.assertTrue(all("compr" not in x["texto"] and "vend" not in x["texto"] for x in s["senales"]))

    def test_canal_se_guarda_y_se_valida(self):
        self._canal("ambos")
        self.assertEqual(self.client.get("/api/tus-senales", headers=self.h).json()["canal"], "ambos")
        r = self.client.put("/api/tus-senales/canal", json={"canal": "fax"}, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self._canal("no")
        self.assertEqual(self.client.get("/api/tus-senales", headers=self.h).json()["canal"], "no")

    def test_cuando_llega_el_proximo_resumen_lo_dice_el_que_lo_manda(self):
        # A9 (auditoría 29/10): el sábado a la tarde el Panorama decía «te llega
        # el sábado 31/10 a las 10:00» de un resumen que ya había salido. La
        # pantalla lo calculaba con la fecha sola; ahora lo dice el servidor con
        # la regla del envío (`toca`) y la fila de la semana que deja el envío.
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")

        def proximo(now):
            with mock.patch("senales_semana._ahora", lambda: now):
                return self.client.get("/api/tus-senales", headers=self.h).json()["proximo_resumen"]

        miercoles = sabado - timedelta(days=3)
        self.assertEqual(proximo(_utc(miercoles, 15)), sabado.isoformat())
        self.assertEqual(proximo(_utc(sabado, 9, 30)), sabado.isoformat(), "el sábado antes de las 10: hoy")
        self.assertEqual(proximo(_utc(sabado, 10, 3)), sabado.isoformat(),
                         "pasadas las 10 pero el cron todavía no pasó: sale hoy")
        self._cron(_utc(sabado, 10, 5))
        self.assertEqual(len(self.mails), 1)
        siguiente = (sabado + timedelta(days=7)).isoformat()
        self.assertEqual(proximo(_utc(sabado, 15)), siguiente, "el de hoy ya salió: el sábado que viene")
        self.assertEqual(proximo(_utc(sabado, 23, 30)), siguiente, "23:30 en Argentina ya es domingo en UTC")

    def test_sin_sesion_no(self):
        self.assertIn(self.client.get("/api/tus-senales").status_code, (401, 403))

    # — el sábado —

    def test_el_sabado_a_las_10_de_argentina_una_vez(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("ambos")
        viernes = sabado - timedelta(days=1)

        # Viernes 22:00 en Argentina = sábado 01:00 UTC: todavía no.
        self.assertIn("esperando", self._cron(_utc(viernes, 22)))
        # Sábado 9:59: todavía no.
        self.assertIn("esperando", self._cron(_utc(sabado, 9, 59)))
        self.assertEqual((self.mails, self.pushes, self._filas()), ([], [], []))

        r = self._cron(_utc(sabado, 10, 5))
        self.assertEqual(r["mandadas"], 1, r)
        self.assertEqual(len(self.mails), 1)
        self.assertEqual(len(self.pushes), 1)
        m = self.mails[0]
        self.assertEqual(m["to"], self.email)
        self.assertTrue(m["asunto"].startswith("Tu semana: NVDA superó su promedio de 200 días"),
                        m["asunto"])
        self.assertIn("Hola Nico, el 94% de tu cartera está en activos con tendencia alcista de largo plazo",
                      m["texto"])
        self.assertIn("MSFT (en tu watchlist) superó su promedio de 200 días", m["texto"],
                      "la watchlist también, y dice que no la tenés")
        self.assertIn("no es una recomendación para comprar ni vender", m["texto"])
        self.assertIn("no es una recomendación", self.pushes[0]["body"])
        # La pestaña «Señales de la semana» de Análisis técnico (antes, Novedades).
        self.assertEqual(self.pushes[0]["url"], "/analisis-tecnico?tab=senales")
        self.assertIn("/analisis-tecnico?tab=senales", m["html"])
        self.assertNotIn("/novedades?tab=senales", m["html"])
        fila = self._filas()[0]
        self.assertEqual((fila["semana"], fila["pct_alcista"], fila["canal"], fila["mail_ok"], fila["push_ok"]),
                         (sabado.isoformat(), 94, "ambos", 1, 1))

        # El cron vuelve a pegar cada 10 minutos: no manda dos veces.
        self._cron(_utc(sabado, 10, 15))
        self._cron(_utc(sabado, 21, 30))     # 00:30 UTC del domingo: sigue siendo sábado acá
        self.assertEqual((len(self.mails), len(self.pushes), len(self._filas())), (1, 1, 1))

    def test_por_el_cron_de_alertas(self):
        # El camino real: `_evaluar_alertas_job` (lo pega cron-job.org) llama al
        # resumen con la hora de verdad. Con un reloj que no es sábado a la
        # mañana, espera; el reloj simulado (reloj.dylib) lo corre en sábado.
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        r = main._evaluar_alertas_job()
        if senales_semana.toca(datetime.utcnow()):
            self.assertEqual(r["semana"].get("mandadas"), 1, r)
            self.assertEqual(len(self.mails), 1)
        else:
            self.assertIn("esperando", r["semana"])
            self.assertEqual(self.mails, [])

    def test_semana_sin_cambios_no_manda_pero_guarda_el_porcentaje(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        # Que nada haya cruzado esta semana: NVDA y MSFT quietos desde hace un mes.
        n = self.n
        self.yahoo.precios["NVDA"] = lambda i, d: 150.0 if i >= n - 30 else 100 - i * 0.01
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0 if i >= n - 30 else 300 - i * 0.01
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias")
            conn.execute("DELETE FROM velas_estado")
            conn.commit()
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            sem = senales_semana.armar_semana(conn, self.uid, sabado)
        self.assertEqual([(x["asset"], x["tipo"]) for x in sem["senales"]
                          if x["tipo"] in ("media200", "media50")], [])
        # Las únicas «señales» que podrían quedar son de otro tipo: se sacan para
        # que la semana esté quieta de verdad.
        with mock.patch("tecnico.cambios_desde", lambda velas, desde: []):
            r = self._cron(_utc(sabado, 10, 5))
        self.assertEqual(r["mandadas"], 0, r)
        self.assertEqual(self.mails, [])
        fila = self._filas()[0]
        self.assertEqual((fila["cambios"], fila["canal"]), (0, None))
        self.assertEqual(fila["pct_alcista"], 94, "el % se guarda igual: es la semana pasada del sábado que viene")

    def test_si_armar_el_mail_falla_no_se_come_la_semana(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        with mock.patch("senales_semana.contenido_del_mail", side_effect=KeyError("x")):
            r = self._cron(_utc(sabado, 10, 5))
        self.assertEqual((r["errores"], self.mails, self._filas()), (1, [], []))
        # Diez minutos después, arreglado: sale.
        self._cron(_utc(sabado, 10, 15))
        self.assertEqual(len(self.mails), 1)

    def test_una_persona_que_falla_en_la_base_no_deja_sin_resumen_a_las_siguientes(self):
        """Auditoría C1 (29/10), el resumen del sábado: en Postgres una consulta
        que falla aborta la transacción, y la persona SIGUIENTE reventaba en su
        primer SELECT: nadie después de ella recibía el resumen. En SQLite no se
        ve (una sentencia que falla no deja secuela): la corrida que importa es
        la de Postgres (DATABASE_URL)."""
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        with main.db_abierta() as conn:
            otro = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Ana', 'x', 1, 1, 'pro')", (f"otra-{self.uid}@rendi.test",)).lastrowid
            conn.execute("INSERT INTO watchlist (user_id, symbol, added_at) VALUES (?, 'MSFT', '2020-01-01 12:00:00')",
                         (otro,))
            conn.execute("INSERT INTO resumen_semanal_prefs (user_id, canal) VALUES (?, 'mail')", (otro,))
            conn.commit()
        real = senales_semana.armar_semana

        def armar(conn, uid, hoy, **kw):
            if uid == self.uid:
                conn.execute("SELECT * FROM tabla_que_no_existe")
            return real(conn, uid, hoy, **kw)
        with mock.patch("senales_semana.armar_semana", armar):
            r = self._cron(_utc(sabado, 10, 5))
        self.assertEqual((r["errores"], r["mandadas"]), (1, 1), r)
        self.assertEqual([m["to"] for m in self.mails], [f"otra-{self.uid}@rendi.test"])

    def test_el_mail_que_no_sale_no_se_reintenta_y_queda_anotado(self):
        """Decisión de Nico (29/10, re-test B): el mail del sábado que falla NO
        se reintenta (así nunca sale dos veces), pero cada falla queda en el
        registro del servidor con el usuario y el nombre del error. Antes, si el
        proveedor lo rechazaba (devolvía «no salió» sin excepción), no quedaba
        nada anotado: sólo un 0 en `mail_ok`."""
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        from billing import emails
        intentos = []

        def rechaza(to, subject, html, text, **kw):
            intentos.append(to)
            emails._anotar(emails.NO_SALIO)
            return False
        with mock.patch("billing.emails._send", rechaza), self.assertLogs("alerts", level="ERROR") as logs:
            self._cron(_utc(sabado, 10, 5))
            self._cron(_utc(sabado, 10, 15))
            self._cron(_utc(sabado, 10, 25))
        self.assertEqual(len(intentos), 1, "no se reintenta: nunca puede salir dos veces")
        self.assertTrue(any(f"uid={self.uid}" in x and emails.NO_SALIO in x for x in logs.output), logs.output)
        self.assertEqual(self._filas()[0]["mail_ok"], 0)

    def test_el_mail_que_revienta_tambien_queda_anotado_con_el_error(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        with mock.patch("billing.emails._send", side_effect=ConnectionError("Resend no contesta")), \
             self.assertLogs("alerts", level="ERROR") as logs:
            self._cron(_utc(sabado, 10, 5))
            self._cron(_utc(sabado, 10, 15))
        self.assertEqual(sum(f"uid={self.uid}" in x and "ConnectionError" in x for x in logs.output), 1)

    # — sacar un activo de la watchlist y volver a ponerlo (decisión de Nico) —

    def _volver_a_poner(self, symbol):
        r = self.client.delete(f"/api/watchlist/{symbol}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._post("/api/watchlist", {"symbol": symbol})

    def _msft(self, senales):
        return [x for x in senales if x["asset"] == "MSFT"]

    def test_lo_que_volviste_a_poner_en_la_watchlist_cuenta_desde_que_lo_pusiste_en_la_pestana(self):
        """Decisión de Nico (29/10, re-test B): si sacás un activo de la
        watchlist y lo volvés a poner, los cambios cuentan sólo desde el día en
        que lo volviste a agregar. MSFT cruzó hace 2 ruedas; se vuelve a poner
        hoy: la pestaña no lo cuenta."""
        self._velas(hoy_art_date())
        self.assertTrue(self._msft(self.client.get("/api/tus-senales", headers=self.h).json()["senales"]),
                        "control: sin sacarlo, el cruce de MSFT está")
        self._volver_a_poner("MSFT")
        self.assertEqual(self._msft(self.client.get("/api/tus-senales", headers=self.h).json()["senales"]), [])

    def test_lo_que_volviste_a_poner_en_la_watchlist_no_sale_en_el_mail(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        self._volver_a_poner("MSFT")          # hoy, después del cruce
        self._cron(_utc(sabado, 10, 5))
        self.assertTrue(self.mails, "NVDA sigue cambiando: el mail sale")
        self.assertNotIn("MSFT", self.mails[0]["texto"])

    def test_si_esta_en_la_cartera_y_en_la_watchlist_manda_la_cartera(self):
        """NVDA está en la cartera (cruzó hace 3 ruedas). Agregarla hoy a la
        watchlist no la recorta: lo que tenés cuenta siempre."""
        self._velas(hoy_art_date())
        self._post("/api/watchlist", {"symbol": "NVDA"})
        pestana = self.client.get("/api/tus-senales", headers=self.h).json()
        nvda = [x for x in pestana["senales"] if x["asset"] == "NVDA" and x["tipo"] == "media200"]
        self.assertTrue(nvda and nvda[0]["tenes"], pestana["senales"])

    def test_no_quiero_no_manda(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("no")
        r = self._cron(_utc(sabado, 10, 5))
        self.assertEqual((r["mandadas"], self.mails, self.pushes), (0, [], []))
        self.assertEqual(len(self._filas()), 1, "el % se guarda para todos")

    def test_la_semana_pasada_es_el_sabado_anterior(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO tendencia_semanal (user_id, semana, pct_alcista, cambios) VALUES (?,?,?,?)",
                         (self.uid, (sabado - timedelta(days=7)).isoformat(), 61.0, 3))
            # Una de hace un mes NO es «la semana pasada».
            conn.execute("INSERT INTO tendencia_semanal (user_id, semana, pct_alcista, cambios) VALUES (?,?,?,?)",
                         (self.uid, (sabado - timedelta(days=28)).isoformat(), 10.0, 3))
            conn.commit()
            sem = senales_semana.armar_semana(conn, self.uid, sabado)
            self.assertEqual(sem["alcista"]["semana_pasada"],
                             {"semana": (sabado - timedelta(days=7)).isoformat(), "pct": 61.0})
            hace_un_mes = senales_semana.semana_pasada(conn, self.uid, sabado - timedelta(days=8))
            self.assertIsNone(hace_un_mes, "más de 13 días: no aparece")
        self._cron(_utc(sabado, 10, 5))
        self.assertIn("94% de tu cartera está en activos con tendencia alcista de largo plazo (la semana pasada, 61%)",
                      self.mails[0]["texto"])

    # — el % es UNA cuenta (28/10) —

    def _cartera_pide(self):
        """Lo que pide la Cartera al abrirse (useLecturasCartera)."""
        r = self.client.post("/api/tecnico/cartera", json={"activos": [{"asset": "NVDA"}, {"asset": "GGAL", "local": True}]},
                             headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["reparto"]

    def test_el_mismo_porcentaje_en_cartera_panorama_senales_y_mail(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._post("/api/positions", {"broker": "IOL", "asset": "AL30", "quantity": 100, "buy_price": 800,
                                      "asset_type": "BONO"})
        self._canal("mail")
        cartera = self._cartera_pide()
        semana = self.client.get("/api/tus-senales", headers=self.h).json()["alcista"]   # Panorama y Señales
        self._cron(_utc(sabado, 10, 5))
        pct = cartera["pct"]
        self.assertEqual(semana["pct"], pct, "el Panorama y la pestaña Señales = la Cartera")
        self.assertIn(f"el {pct}% de tu cartera está en activos con tendencia alcista de largo plazo", self.mails[0]["texto"],
                      "el mail = la Cartera")
        self.assertEqual(self._filas()[0]["pct_alcista"], pct, "y lo que se guarda para «la semana pasada»")
        # Lo demás de la cuenta, igual en los dos pedidos: grupos que suman 100, de
        # más a menos plata, y el porqué de cada «sin lectura».
        self.assertEqual(semana["grupos"], cartera["grupos"])
        self.assertEqual(sum(g["pct"] for g in cartera["grupos"].values()), 100)
        self.assertEqual(cartera["grupos"]["alcista"]["nombres"], ["NVDA", "KO", "GGAL"])
        self.assertEqual(cartera["grupos"]["bajista"]["nombres"], ["AAPL"])
        self.assertIn("AL30", cartera["grupos"]["sin"]["nombres"])
        self.assertEqual(cartera["motivos"], [{"porque": "no_se_mide", "nombres": ["AL30"]}],
                         "un bono no se mide así: no es «todavía no hay historia»")

    def test_la_semana_pasada_llega_aunque_nunca_haya_pedido_el_resumen(self):
        # La mayoría nunca elige un canal (opt-in): el % se guarda igual cada
        # sábado, y el siguiente la Cartera y el Panorama dicen «la semana pasada».
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        anterior = sabado - timedelta(days=7)
        r = self._cron(_utc(anterior, 10, 5))
        self.assertEqual((r["guardadas"], r["mandadas"], self.mails, self.pushes), (1, 0, [], []))
        guardado = self._filas()[0]["pct_alcista"]
        cartera = self._cartera_pide()
        self.assertEqual(cartera["semana_pasada"], {"semana": anterior.isoformat(), "pct": guardado})
        self.assertEqual(self.client.get("/api/tus-senales", headers=self.h).json()["alcista"]["semana_pasada"],
                         cartera["semana_pasada"])

    def test_el_mismo_peso_en_tu_lista_y_en_senales(self):
        # «Sí · 12%» de Tu lista y «Lo tenés · 12% de tu plata» de Señales son el
        # MISMO número (senales_semana.cartera, 29/10): la pantalla ya no lo calcula.
        self._velas(hoy_art_date())
        lista = self.client.post("/api/tecnico/lista", json={"activos": [{"asset": "MSFT"}]}, headers=self.h)
        self.assertEqual(lista.status_code, 200, lista.text)
        lista = lista.json()
        pesos = {(t["asset"], t["local"]): t["peso"] for t in lista["tenencias"]}
        self.assertEqual(set(pesos), {("NVDA", False), ("KO", False), ("AAPL", False), ("GGAL", True)},
                         "lo que tenés lo pone el servidor, aunque la pantalla sólo mande la watchlist")
        self.assertAlmostEqual(sum(pesos.values()), 1.0, places=9, msg="sin efectivo ni plazos fijos, suman todo")
        self.assertEqual([t["asset"] for t in lista["tenencias"]][:2], ["NVDA", "KO"], "de más a menos plata")
        self.assertEqual({(x["asset"], x["local"]) for x in lista["lecturas"]} >= set(pesos) | {("MSFT", False)}, True,
                         "y de cada cosa que tenés viene su lectura")
        senales = self.client.get("/api/tus-senales", headers=self.h).json()["senales"]
        for x in senales:
            if x["tenes"]:
                self.assertAlmostEqual(x["peso"], pesos[(x["asset"], x["local"])], places=12, msg=x["asset"])
        self.assertTrue(any(x["tenes"] for x in senales), "la prueba tiene que comparar al menos uno")
        self.assertEqual(next(t["tipo"] for t in lista["tenencias"] if t["asset"] == "AAPL"), "CEDEAR")
        # Y la ficha («Es el 12% de tu cartera» en «Cuánto se mueve»): el mismo
        # número, pedido por su camino (GET /api/tecnico/{activo}/peso).
        for (a, l), p in pesos.items():
            r = self.client.get(f"/api/tecnico/{a}/peso", headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertAlmostEqual(r.json()["peso"], p, places=12, msg=a)
        self.assertIsNone(self.client.get("/api/tecnico/MSFT/peso", headers=self.h).json()["peso"],
                          "lo que sólo seguís no pesa nada en tu plata")

    def test_el_efectivo_y_los_plazos_fijos_son_tu_plata(self):
        # A0 (auditoría 29/10): el efectivo se guarda con el saldo en `invested` y
        # sin cantidad, y `cartera()` pedía «cantidad > 0»: la caja nunca entraba y
        # con US$ 1.500 en NVDA + US$ 1.500 en efectivo decía «100 % alcista» y
        # «NVDA es el 100 % de tu cartera». El efectivo se carga por donde lo carga
        # la pantalla (POST /api/cash/flow), en dólares y en pesos, y un plazo fijo
        # por POST /api/plazos-fijos. Lo esperado sale del valuador que ya valúa la
        # cartera entera (`compute_live_portfolio_value`, Reportes y el ✦ del
        # inicio) más los plazos fijos (`_pf_value` al MEP), no de esta cuenta.
        from snapshots_job import _LIVE_VALUE_CACHE, compute_live_portfolio_value, read_last_prices
        self._velas(hoy_art_date())
        self._post("/api/cash/flow", {"broker_name": "Schwab", "direction": "deposit", "amount": 1500})
        self._post("/api/cash/flow", {"broker_name": "IOL", "direction": "deposit", "amount": 500_000})
        self._post("/api/plazos-fijos", {"banco": "Galicia", "capital": 1_000_000, "moneda": "ARS", "tasa": 0.3,
                                         "fecha_inicio": hoy_art_date().isoformat(), "plazo_dias": 30})
        with main.db_abierta() as conn:
            caja = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=1 AND invested > 0",
                                (self.uid,)).fetchone()[0]
            self.assertEqual(caja, 2, "las dos cajas quedaron guardadas")
            _LIVE_VALUE_CACHE.clear()
            precios = read_last_prices(conn, [r[0] for r in conn.execute("SELECT symbol FROM asset_last_price")])
            posiciones = compute_live_portfolio_value(conn, self.uid, MEP, {}, precios=precios)
            pfs = sum(main._pf_value(dict(r))["valor_hoy"] / MEP for r in conn.execute(
                "SELECT * FROM plazos_fijos WHERE user_id=? AND closed_at IS NULL", (self.uid,)))
        total = posiciones + pfs
        # NVDA y KO: 10 × US$ 150 cada una (el último precio guardado).
        self.assertAlmostEqual(self.client.get("/api/tecnico/NVDA/peso", headers=self.h).json()["peso"],
                               1500 / total, places=9, msg="la ficha: el peso sobre TODA tu plata")
        lista = self.client.post("/api/tecnico/lista", json={"activos": []}, headers=self.h).json()
        pesos = {t["asset"]: t["peso"] for t in lista["tenencias"]}
        self.assertAlmostEqual(pesos["KO"], 1500 / total, places=9, msg="Tu lista")
        efectivo_y_pf = 1500 + 500 + pfs
        self.assertAlmostEqual(sum(pesos.values()), 1 - efectivo_y_pf / total, places=9,
                               msg="lo que falta para el 100 % es el efectivo y el plazo fijo")
        cartera = self._cartera_pide()
        semana = self.client.get("/api/tus-senales", headers=self.h).json()
        for r in (cartera, semana["alcista"]):
            self.assertEqual(r["grupos"]["sin"]["nombres"], ["efectivo", "plazos fijos"], "de más a menos plata (US$ 2.000 contra ~US$ 1.000)")
            self.assertAlmostEqual(r["grupos"]["sin"]["fraccion"], efectivo_y_pf / total, places=9)
        self.assertEqual(semana["alcista"]["grupos"], cartera["grupos"])
        self.assertTrue(all(abs(x["peso"] - pesos[x["asset"]]) < 1e-12 for x in semana["senales"] if x["tenes"]),
                        "Señales: el mismo peso")

    def test_mitad_en_efectivo_es_la_mitad_alcista(self):
        # El caso de la auditoría, en números redondos: NVDA (alcista) US$ 1.500 +
        # US$ 1.500 en efectivo en el mismo broker = 50 %, y NVDA pesa la mitad.
        hoy = hoy_art_date()
        self.yahoo = YahooFalso(hoy)
        p = mock.patch("pricing.yahoo._historia", self.yahoo)
        p.start()
        self._p.append(p)
        self._post("/api/brokers", {"name": "Schwab", "currency": "USD"})
        self._post("/api/positions", {"broker": "Schwab", "asset": "NVDA", "quantity": 10, "buy_price": 140,
                                      "asset_type": "STOCK"})
        self._post("/api/cash/flow", {"broker_name": "Schwab", "direction": "deposit", "amount": 1500})
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO asset_last_price (symbol, price, updated_at) VALUES ('NVDA', 150.0, datetime('now'))")
            conn.commit()
        self.yahoo.precios["NVDA"] = lambda i, d: 100 + i * 0.07
        main._run_velas_diarias_job()
        r = self.client.post("/api/tecnico/cartera", json={"activos": [{"asset": "NVDA"}]}, headers=self.h).json()
        self.assertEqual(r["reparto"]["pct"], 50)
        self.assertEqual(r["reparto"]["grupos"]["sin"]["nombres"], ["efectivo"])
        self.assertAlmostEqual(self.client.get("/api/tecnico/NVDA/peso", headers=self.h).json()["peso"], 0.5, places=9)

    def test_una_accion_argentina_seguida_se_lee_en_byma_en_todas_las_pantallas(self):
        # A1 + P4 (auditoría 29/10). «GGAL» lo guarda la estrella del buscador del
        # inicio (sin «.BA») y «BMA.BA» la de la ficha. Nadie las tiene en BYMA:
        # la noche tiene que bajar la serie de BYMA porque alguien la SIGUE. Los
        # ADR de Nueva York se caen abajo de su promedio de 200 hace 2 ruedas; en
        # BYMA ÷ MEP siguen subiendo. Señales (y el mail), Tu lista y la ficha a la
        # que lleva «Ver gráfico» tienen que leer lo mismo: la acción de BYMA.
        hoy = hoy_art_date()
        self.yahoo = YahooFalso(hoy)
        p = mock.patch("pricing.yahoo._historia", self.yahoo)
        p.start()
        self._p.append(p)
        dias = _ruedas(hoy, 760)
        n = len(dias)
        self._post("/api/watchlist", {"symbol": "GGAL"})
        self._post("/api/watchlist", {"symbol": "BMA.BA"})
        with main.db_abierta() as conn:
            for d in dias:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), MEP * 1.1, MEP))
            conn.commit()
        for a in ("GGAL", "BMA"):
            self.yahoo.precios[f"{a}.BA"] = lambda i, d: 5000 + i * 20
            self.yahoo.precios[a] = lambda i, d: 30.0 if i >= n - 2 else 50 + i * 0.02
        main._run_velas_diarias_job()

        senales = self.client.get("/api/tus-senales", headers=self.h).json()["senales"]
        # Lo que manda Tu lista: `activosDeLaLista` de la pantalla (accionLocal.test.js
        # prueba que GGAL y BMA.BA salen local=true con la misma tabla que el servidor).
        lista = self.client.post("/api/tecnico/lista", json={"activos": [{"asset": "GGAL", "local": True},
                                                                         {"asset": "BMA", "local": True}]},
                                 headers=self.h).json()["lecturas"]
        for a, ficha_de in (("GGAL", "GGAL"), ("BMA", "BMA.BA")):
            with self.subTest(a):
                suyas = [s for s in senales if s["asset"] == a]
                self.assertFalse([s for s in suyas if s["tipo"] == "media200"],
                                 "Señales no puede avisar el cruce del ADR")
                self.assertTrue(all(s["local"] and s["ficha"] == ficha_de for s in suyas))
                fila = next(x for x in lista if x["asset"] == a)
                self.assertTrue(fila["disponible"], "la noche bajó la serie de BYMA aunque nadie la tenga")
                self.assertGreater(fila["lectura"]["dist_media200"], 0)
                ficha = self.client.get(f"/api/tecnico/{a}?moneda=usd&local=1", headers=self.h).json()
                self.assertEqual(ficha["ticker"], f"{a}.BA")
                self.assertEqual(ficha["lectura"]["fecha"], fila["lectura"]["fecha"], "al día, la misma vela")
                self.assertAlmostEqual(ficha["lectura"]["dist_media200"], fila["lectura"]["dist_media200"], places=9)
        with main.db_abierta() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM velas_diarias WHERE symbol='GGAL' LIMIT 1").fetchone(),
                              "el ADR no lo sigue nadie: no se baja")

    def test_los_activos_con_cambios_son_parte_de_los_que_tienen_lectura(self):
        # A2 (auditoría 29/10): «6 cambios · en 2 de tus 1 activo con lectura».
        # NVDA tiene 3 años de precios; NUEVA cotiza hace 120 ruedas (tiene
        # promedio de 50 y RSI, no de 200) y cambió esta semana. Las dos tienen
        # algo que leer: «con lectura» y «con cambios» se cuentan con la MISMA
        # regla (la que decide si un cambio entra a la semana).
        hoy = hoy_art_date()
        self.yahoo = YahooConHuecos(hoy)
        p = mock.patch("pricing.yahoo._historia", self.yahoo)
        p.start()
        self._p.append(p)
        n = len(_ruedas(hoy, 760))
        self.yahoo.precios["NVDA"] = lambda i, d: 150.0 if i >= n - 3 else 100 - i * 0.01
        self.yahoo.precios["NUEVA"] = lambda i, d: (None if i < n - 120 else
                                                     60.0 if i >= n - 2 else 50 - 0.01 * (i - (n - 120)))
        self._post("/api/brokers", {"name": "Schwab", "currency": "USD"})
        for a, compra in (("NVDA", 140), ("NUEVA", 55)):
            self._post("/api/positions", {"broker": "Schwab", "asset": a, "quantity": 10, "buy_price": compra,
                                          "asset_type": "STOCK"})
        main._run_velas_diarias_job()
        s = self.client.get("/api/tus-senales", headers=self.h).json()
        cambiaron = {x["asset"] for x in s["senales"] if x["tenes"]}
        self.assertEqual(cambiaron, {"NVDA", "NUEVA"}, "la prueba necesita que cambien las dos")
        self.assertEqual(s["tenes"], {"activos": 2, "con_cambios": 2})
        self.assertLessEqual(s["tenes"]["con_cambios"], s["tenes"]["activos"])

    def test_sin_nada_con_lectura_no_hay_porcentaje(self):
        # Sólo un bono: no hay tendencia que medir. Ni la Cartera ni la pestaña
        # inventan un 0 % (la pantalla lo dice con palabras).
        self._post("/api/brokers", {"name": "IOL", "currency": "ARS"})
        self._post("/api/positions", {"broker": "IOL", "asset": "AL30", "quantity": 100, "buy_price": 800,
                                      "asset_type": "BONO"})
        cartera = self._cartera_pide()
        self.assertIsNone(cartera["pct"])
        self.assertIsNone(cartera["semana_pasada"])
        self.assertIsNone(self.client.get("/api/tus-senales", headers=self.h).json()["alcista"])

    def test_cuenta_administrada_le_llega_al_asesor(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        with main.db_abierta() as conn:
            adv = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Laura Asesora', 'x', 1, 1, 'pro')", (f"asesor-{self.uid}@rendi.test",)).lastrowid
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (adv, self.uid))
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, label) VALUES (?,?,?)",
                         (adv, self.uid, "Juan"))
            conn.commit()
        self._cron(_utc(sabado, 10, 5))
        self.assertEqual(self.mails[0]["to"], f"asesor-{self.uid}@rendi.test")
        self.assertTrue(self.mails[0]["asunto"].startswith("[Juan] Tu semana:"))

    def _asesor(self, label="Juan"):
        with main.db_abierta() as conn:
            adv = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Laura Asesora', 'x', 1, 1, 'pro')", (f"asesor-{self.uid}@rendi.test",)).lastrowid
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (adv, self.uid))
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, label) VALUES (?,?,?)",
                         (adv, self.uid, label))
            conn.commit()
        return adv

    def test_el_mail_del_asesor_dice_de_quien_es_y_lleva_a_sus_clientes(self):
        """Auditoría B, hallazgo B1 (29/10): el mail del sábado de Juan le decía
        a Laura «el 94% de TU plata» y sus dos links («Ver los cambios»,
        «Cambiar o apagar») abrían las señales de LAURA. Un aviso de una cuenta
        administrada se arma en UN lugar (`alerts_engine.entrega`), el mismo que
        usan las alertas: oración, botón, pie y push."""
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("ambos")          # el asesor lo elige ENTRANDO a la cuenta de Juan
        self._asesor("Juan")
        r = self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "Data centers"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._cron(_utc(sabado, 10, 5))
        self.assertEqual(len(self.mails), 1)
        m = self.mails[0]
        self.assertTrue(m["asunto"].startswith("[Juan] Tu semana:"))
        self.assertIn("Hola Laura, en la cuenta de Juan, el ", m["texto"])
        for tuyo in ("tu cartera", "tus activos", "tu watchlist", "Tu tesis"):
            self.assertNotIn(tuyo, m["texto"], f"«{tuyo}» le habla a Laura de la plata de Juan")
        self.assertIn("La tesis de Juan: «Data centers»", m["texto"])
        self.assertIn("(en la watchlist de Juan)", m["texto"])
        self.assertNotIn("/analisis-tecnico?tab=senales", m["html"],
                         "el botón y el pie abrían las señales DEL ASESOR, no las de Juan")
        self.assertIn("/clientes", m["html"])
        self.assertEqual([p["url"] for p in self.pushes], ["/clientes"])
        self.assertTrue(self.pushes[0]["body"].startswith("[Juan] Tu semana:"))

    def test_el_mail_de_la_cuenta_propia_sigue_hablando_de_vos(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("ambos")
        self._cron(_utc(sabado, 10, 5))
        m = self.mails[0]
        self.assertIn("Hola Nico, el ", m["texto"])
        self.assertIn("% de tu cartera", m["texto"])
        self.assertIn("(en tu watchlist)", m["texto"])
        self.assertNotIn("en la cuenta de", m["texto"])
        self.assertIn(senales_semana.URL_SENALES, m["html"])
        self.assertEqual([p["url"] for p in self.pushes], [senales_semana.URL_SENALES])

    # — la tesis (pieza 11) en la pestaña y en el mail —

    def test_la_tesis_escrita_sale_en_el_mail_del_sabado(self):
        """Auditoría B4 = A8 = C2 (29/10): `_tesis()` devolvía {} con un
        «al juntar: SELECT…» en un comentario; se juntó y nadie lo llenó."""
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        r = self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "Data centers e IA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._cron(_utc(sabado, 10, 5))
        self.assertIn("NVDA superó su promedio", self.mails[0]["texto"])
        self.assertIn("Tu tesis: «Data centers e IA».", self.mails[0]["texto"])

    def test_la_tesis_escrita_sale_en_la_pestana(self):
        self._velas(hoy_art_date())
        r = self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "Data centers e IA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        pestana = self.client.get("/api/tus-senales", headers=self.h).json()
        nvda = [x for x in pestana["senales"] if x["asset"] == "NVDA"]
        self.assertTrue(nvda)
        self.assertEqual({x["tesis"] for x in nvda}, {"Data centers e IA"})
        # La de un activo que no cambió no aparece (no hay renglón donde ponerla),
        # y la de otro activo no se mete en NVDA.
        self.assertTrue(all(x["tesis"] is None for x in pestana["senales"] if x["asset"] != "NVDA"))

    def test_vale_la_ultima_version_de_la_tesis(self):
        """La tesis se reescribe (una versión por día, `tesis.guardar`): vale la
        última, como en la pantalla del diario."""
        self._velas(hoy_art_date())
        hoy = hoy_art_date()
        with mock.patch("tesis.hoy_art_date", lambda: hoy - timedelta(days=5)):
            self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "v1"}, headers=self.h)
        self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "v2"}, headers=self.h)
        pestana = self.client.get("/api/tus-senales", headers=self.h).json()
        self.assertEqual({x["tesis"] for x in pestana["senales"] if x["asset"] == "NVDA"}, {"v2"})

    def test_la_tesis_se_busca_con_la_misma_regla_que_la_ficha_y_movimientos(self):
        """Re-test de la auditoría C (29/10): «la última tesis» vivía en 4 lugares
        y éste comparaba el nombre en mayúsculas: una tesis guardada como «nvda»
        salía en Señales y no en la ficha ni en Movimientos (que comparan el
        nombre tal cual, `tesisVigente`). Una sola regla: el nombre tal cual, el
        de la posición (lo que manda la pantalla)."""
        self._velas(hoy_art_date())
        self.client.put("/api/tesis", json={"asset": "nvda", "texto": "minúscula"}, headers=self.h)
        pestana = self.client.get("/api/tus-senales", headers=self.h).json()
        self.assertEqual({x["tesis"] for x in pestana["senales"] if x["asset"] == "NVDA"}, {None})
        # La que manda la pantalla (el nombre de la posición) sí.
        self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "la de la ficha"}, headers=self.h)
        pestana = self.client.get("/api/tus-senales", headers=self.h).json()
        self.assertEqual({x["tesis"] for x in pestana["senales"] if x["asset"] == "NVDA"}, {"la de la ficha"})
        # Y es la misma que elige GET /api/tesis (de donde la ficha y Movimientos
        # sacan «la vigente»): la última de ese nombre.
        items = [t for t in self.client.get("/api/tesis", headers=self.h).json()["items"] if t["asset"] == "NVDA"]
        self.assertEqual(max(items, key=lambda t: (t["escrita_el"], t["id"]))["texto"], "la de la ficha")

    def test_una_tesis_larga_va_cortada_en_el_mail_como_en_el_recordatorio(self):
        sabado = _sabado_de(hoy_art_date())
        self._velas(sabado)
        self._canal("mail")
        self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "x" * 900}, headers=self.h)
        self._cron(_utc(sabado, 10, 5))
        self.assertIn("Tu tesis: «" + "x" * 277 + "…».", self.mails[0]["texto"])


    # — auditoría chica de la junta (30/10): la tesis de un papel con el mismo
    # código que otro (AGRO: Adecoagro en Nueva York, Agrometal en BYMA) —

    def _agro(self, *, adecoagro=True):
        """Agrometal (AGRO.BA) en la watchlist, que cruza su promedio de 200 hace
        2 ruedas; con `adecoagro`, además tenés Adecoagro (AGRO) en Schwab."""
        hoy = hoy_art_date()
        self.yahoo = YahooFalso(hoy)
        p = mock.patch("pricing.yahoo._historia", self.yahoo)
        p.start()
        self._p.append(p)
        dias = _ruedas(hoy, 760)
        n = len(dias)
        if adecoagro:
            self._post("/api/brokers", {"name": "Schwab", "currency": "USD"})
            self._post("/api/positions", {"broker": "Schwab", "asset": "AGRO", "quantity": 10,
                                          "buy_price": 10, "asset_type": "STOCK"})
        self._post("/api/watchlist", {"symbol": "AGRO.BA"})
        self._seguida_desde("AGRO.BA", dias[0])
        with main.db_abierta() as conn:
            for d in dias:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), MEP * 1.1, MEP))
            conn.execute("INSERT INTO asset_last_price (symbol, price, updated_at) VALUES ('AGRO', 12, datetime('now'))")
            conn.commit()
        self.yahoo.precios["AGRO"] = lambda i, d: 10 + i * 0.001
        self.yahoo.precios["AGRO.BA"] = lambda i, d: 3000.0 if i >= n - 2 else 1000 - i * 0.01
        main._run_velas_diarias_job()

    def _tesis_de_agrometal(self):
        sen = self.client.get("/api/tus-senales", headers=self.h).json()["senales"]
        agrometal = [x for x in sen if x["asset"] == "AGRO" and x["local"]]
        self.assertTrue(agrometal, "Agrometal tiene que cambiar esta semana")
        return {x["tesis"] for x in agrometal}

    def test_agrometal_no_muestra_la_tesis_de_adecoagro(self):
        """Señales buscaba la tesis por el código pelado («AGRO») y la ficha por
        el nombre tal cual: debajo de Agrometal salía «Tu tesis: Adecoagro…» y la
        que escribiste en la ficha de AGRO.BA no salía nunca. Una regla: la de la
        ficha a la que lleva el botón (`tesis.de_la_senal`)."""
        self._agro()
        self.client.put("/api/tesis", json={"asset": "AGRO", "texto": "Adecoagro (NY)"}, headers=self.h)
        self.assertEqual(self._tesis_de_agrometal(), {None})
        r = self.client.put("/api/tesis", json={"asset": "AGRO.BA", "texto": "Agrometal, de su ficha", "local": True},
                            headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._tesis_de_agrometal(), {"Agrometal, de su ficha"})

    def test_la_tesis_del_mismo_papel_con_el_nombre_corto_sigue_saliendo(self):
        """La que escribiste cuando lo tenías (la ficha de tu lote la guarda sin
        «.BA», marcada como acción argentina) es la del mismo papel: sigue."""
        self._agro(adecoagro=False)
        self.client.put("/api/tesis", json={"asset": "AGRO", "texto": "Agrometal, cuando lo tenía", "local": True},
                        headers=self.h)
        self.assertEqual(self._tesis_de_agrometal(), {"Agrometal, cuando lo tenía"})


class _YahooConCripto(YahooFalso):
    """El Yahoo de mentira de siempre, más BTC-USD con velas los 7 días (la
    cripto cotiza sábados y domingos). `hasta_btc`: el primer día que Yahoo
    todavía NO publicó (la vela de ese día no existe)."""

    def __init__(self, hoy):
        super().__init__(hoy)
        self.btc = None
        self.hasta_btc = hoy

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        if ticker != "BTC-USD" or self.btc is None:
            return super().__call__(ticker, period, interval, auto_adjust, timeout)
        import pandas as pd
        n = 1100 if period == "3y" else 30
        dias = [self.hasta_btc - timedelta(days=k) for k in range(n, 0, -1)]
        cs = [self.btc(d) for d in dias]
        return pd.DataFrame({"Open": cs, "High": [c * 1.01 for c in cs], "Low": [c * 0.99 for c in cs],
                             "Close": cs, "Volume": [1000.0] * len(cs)},
                            index=pd.DatetimeIndex([pd.Timestamp(d) for d in dias]))


class CriptoDelSabadoTest(unittest.TestCase):
    """Auditoría B, hallazgo B3 (29/10): una cripto que cruza en una vela de
    SÁBADO no salía en ningún mail. El sábado S a las 10:00 su vela no existe
    (la de hoy no entra hasta la noche) y el del sábado siguiente miraba sólo
    «después de S». Dos sábados seguidos, cada uno con las velas que había ESE
    sábado a las 10:00."""
    setUp, tearDown = TusSenalesTest.setUp, TusSenalesTest.tearDown
    _post, _canal, _cron = TusSenalesTest._post, TusSenalesTest._canal, TusSenalesTest._cron
    _seguida_desde = TusSenalesTest._seguida_desde

    def _dos_sabados(self, dia_del_cruce, viernes_tarde=False, otro_al_dia=False, sin_cron_en=None, sabados=2):
        """`sabados` sábados seguidos (el último, el de esta semana), cada uno con
        las velas que había ESE sábado a las 10:00. `viernes_tarde`: la noche
        del viernes falló y las velas del viernes (de BTC) se guardaron el
        primer sábado DESPUÉS del resumen. `otro_al_dia`: MSFT en la watchlist,
        con sus velas al día (el viernes llegó). `sin_cron_en`: el índice del
        sábado en que el cron no corrió. El cruce es contando desde el primero."""
        ult = _sabado_de(hoy_art_date())
        sabs = [ult - timedelta(days=7 * (sabados - 1 - i)) for i in range(sabados)]
        s1 = sabs[0]
        cruce = s1 + timedelta(days=dia_del_cruce)
        self.yahoo = _YahooConCripto(s1)
        p = mock.patch("pricing.yahoo._historia", self.yahoo)
        p.start()
        self._p.append(p)
        self._post("/api/watchlist", {"symbol": "BTC"})
        self._seguida_desde("BTC", s1 - timedelta(days=30))
        if otro_al_dia:
            self.yahoo.precios["MSFT"] = lambda i, d: 300 - i * 0.01
            self._post("/api/watchlist", {"symbol": "MSFT"})
            self._seguida_desde("MSFT", s1 - timedelta(days=30))
        # Bajando hasta el cruce (abajo de su promedio), 150 desde ese día.
        self.yahoo.btc = lambda d: 150.0 if d >= cruce else 100.0 + (cruce - d).days * 0.001
        self._canal("mail")
        for j, s in enumerate(sabs):
            tarde = viernes_tarde and j == 0
            self.yahoo.hasta_btc = s - timedelta(days=1) if tarde else s
            main._run_velas_diarias_job()
            if j != sin_cron_en:
                self._cron(_utc(s, 10, 5))
            if tarde:
                self.yahoo.hasta_btc = s
                main._run_velas_diarias_job()
        return [m for m in self.mails if "BTC" in m["texto"] and "promedio de 200" in m["texto"]]

    def test_control_cruce_en_domingo_llega(self):
        self.assertEqual(len(self._dos_sabados(dia_del_cruce=1)), 1)

    def test_cruce_en_sabado_llega_el_sabado_siguiente(self):
        self.assertEqual(len(self._dos_sabados(dia_del_cruce=0)), 1,
                         "el cruce de una vela de SÁBADO no salía en ningún resumen")

    def test_viernes_cuyas_velas_llegaron_despues_del_resumen_sale_el_sabado_siguiente(self):
        self.assertEqual(len(self._dos_sabados(dia_del_cruce=-1, viernes_tarde=True)), 1)

    def test_un_activo_atrasado_no_pierde_su_cruce_por_otro_que_llego(self):
        """Re-test de la auditoría B (29/10): la marca de «hasta dónde ya
        conté» era UNA por persona (la vela más nueva de TODOS sus activos).
        BTC se atrasa una noche (su viernes llega después del resumen) y MSFT
        llegó: la marca quedaba en el viernes y el cruce del viernes de BTC no
        salía en ningún mail. Ahora es una por activo, como las alertas
        técnicas ('<activo>#velas')."""
        self.assertEqual(len(self._dos_sabados(dia_del_cruce=-1, viernes_tarde=True, otro_al_dia=True)), 1)

    def test_si_un_sabado_no_corre_el_cron_esa_semana_sale_el_siguiente(self):
        """Re-test de la auditoría B: el resumen anterior se buscaba sólo hasta
        13 días atrás. Si un sábado no corría, el siguiente no lo encontraba,
        contaba sólo sus 7 días y la semana del medio se perdía entera."""
        self.assertEqual(len(self._dos_sabados(dia_del_cruce=3, sabados=3, sin_cron_en=1)), 1)

    def test_con_el_cron_de_todos_los_sabados_no_se_repite(self):
        self.assertEqual(len(self._dos_sabados(dia_del_cruce=3, sabados=3)), 1)

    def test_cruce_en_viernes_sale_una_sola_vez(self):
        """La otra punta: lo que ya salió el sábado 1 no se repite el sábado 2."""
        self.assertEqual(len(self._dos_sabados(dia_del_cruce=-1)), 1)


if __name__ == "__main__":
    unittest.main()
