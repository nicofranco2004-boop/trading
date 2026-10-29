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
  · el % de cada sábado se guarda y el sábado siguiente es «la semana pasada».

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
                         "pasó arriba de su promedio de 200 días: la tendencia de fondo se volvió alcista.")
        self.assertEqual(nvda["media200"]["etiqueta"], "Tendencia de fondo")

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
        self.assertTrue(m["asunto"].startswith("Tu semana: NVDA pasó arriba de su promedio de 200 días"),
                        m["asunto"])
        self.assertIn("Hola Nico, el 94% de tu plata está en activos con tendencia de fondo alcista",
                      m["texto"])
        self.assertIn("MSFT (en tu watchlist) pasó arriba de su promedio de 200 días", m["texto"],
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
        self.assertIn("94% de tu plata está en activos con tendencia de fondo alcista (la semana pasada, 61%)",
                      self.mails[0]["texto"])

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


if __name__ == "__main__":
    unittest.main()
