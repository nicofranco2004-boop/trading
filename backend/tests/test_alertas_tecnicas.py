"""Alertas técnicas: «avisame cuando AAPL cruce su promedio de 200 días».

Entra por las mismas puertas que producción:
  · la alerta se crea por HTTP (POST /api/alerts), como el botón «Avisame»;
  · las velas las guarda `main._run_velas_diarias_job`, el trabajo de cada
    noche (lo único reemplazado es Yahoo, en su punto más bajo:
    `pricing.yahoo._historia`);
  · la evaluación es `main._evaluar_alertas_job`, lo que corre el cron de
    alertas;
  · el mail se arma con `billing.emails.send_alert_email` de verdad: lo único
    reemplazado es el envío (`emails._send`) y el push (`_send_push_to_user`).

La hora de los avisos (desde las 9, `HORA_AVISO_TECNICO`) se baja a 0 en las
pruebas del camino para que no dependan de la hora en que corre la suite; la
regla de la hora se prueba aparte, con el reloj en la mano.

Corre con: cd backend && python3 -m pytest tests/test_alertas_tecnicas.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta
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
import alerts_engine as ae
import tecnico
from fechas import hoy_art_date

NAN = float("nan")


def _ruedas(hasta: date, n: int) -> list:
    """Las últimas `n` ruedas (lunes a viernes) antes de `hasta`, sin incluirla."""
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class YahooFalso:
    """Reemplaza a Yahoo. `precios[ticker](fecha)` da el cierre de ese día (NaN =
    Yahoo no lo tiene). `hasta` es el último día que Yahoo ya publicó: correrlo
    un día es "pasó una noche"."""

    def __init__(self, hasta: date):
        self.hasta = hasta
        self.precios = {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        f = self.precios.get(ticker)
        if f is None:
            return pd.DataFrame()
        n = 760 if period == "3y" else 22
        dias = _ruedas(self.hasta, n - 1) + [self.hasta]
        filas = {d: f(d) for d in dias}
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in sorted(filas)])
        cs = [filas[d] for d in sorted(filas)]
        return pd.DataFrame({"Open": cs, "High": [c * 1.01 for c in cs], "Low": [c * 0.99 for c in cs],
                             "Close": cs, "Volume": [1000.0] * len(cs)}, index=idx)


class AlertasTecnicasTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "velas_correcciones", "watchlist",
                      "positions", "brokers", "alerts", "alert_events", "alert_symbol_state"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Nico Prueba', 'x', 1, 1, 'pro')", (f"tec-{tag}@rendi.test",))
            conn.commit()
            self.uid = cur.lastrowid
            self.email = f"tec-{tag}@rendi.test"
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        r = _ruedas(self.hoy, 30)
        self.ayer, self.anteayer = r[-1], r[-2]     # las dos últimas ruedas cerradas
        self.yahoo = YahooFalso(self.anteayer)
        self.mails, self.pushes = [], []
        self._p = [
            mock.patch("main._check_rate_limit"),
            mock.patch("pricing.yahoo._historia", self.yahoo),
            mock.patch("main._fetch_data912_equities", lambda: {}),
            # El alta prueba el precio de ahora (¿existe el ticker?): es red.
            mock.patch("alerts_engine._prices_for", lambda syms: {s: 100.0 for s in syms}),
            mock.patch("billing.emails._send",
                       lambda to, subject, html, text, **kw: (self.mails.append(
                           {"to": to, "asunto": subject, "html": html, "texto": text}), True)[1]),
            mock.patch("main._send_push_to_user",
                       lambda uid, payload: (self.pushes.append(payload), 1)[1]),
            mock.patch("alerts_engine.HORA_AVISO_TECNICO", 0),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    # — armado, como la app —

    def _noche(self, hasta):
        """Pasa una noche: Yahoo publica hasta `hasta` y corre el trabajo de velas."""
        self.yahoo.hasta = hasta
        main._run_velas_diarias_job()

    def _crear(self, **kw):
        body = {"kind": "tecnica", "symbol": "MSFT", "senal": "media200",
                "direction": "either", "channel": "both", "repeat": "always", **kw}
        r = self.client.post("/api/alerts", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _cron(self):
        return main._evaluar_alertas_job()

    def _eventos(self):
        with main.db_abierta() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM alert_events WHERE user_id=? ORDER BY id", (self.uid,)).fetchall()]

    def _alerta(self, aid):
        with main.db_abierta() as conn:
            return dict(conn.execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone())

    def _sube_ayer(self, d):
        """Dos años en 100, las últimas 8 semanas en 90 (abajo del promedio de 200)
        y AYER salta a 120: cruza para arriba en la última rueda."""
        if d >= self.ayer:
            return 120.0
        return 90.0 if d >= self.ayer - timedelta(days=56) else 100.0

    # — los casos —

    def test_cruza_su_promedio_de_200_y_avisa_una_sola_vez_con_el_mail_armado(self):
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)                       # llega la vela del cruce
        self._cron()
        ev = self._eventos()
        self.assertEqual(len(ev), 1, "el cruce de ayer avisa")
        self.assertEqual(ev[0]["message"],
                         "MSFT pasó para arriba su promedio de 200 días: la tendencia de fondo se volvió alcista")
        self.assertEqual(ev[0]["delivered_email"], 1)
        self.assertEqual(ev[0]["delivered_push"], 1)

        # El mail, armado por send_alert_email de verdad.
        self.assertEqual(len(self.mails), 1)
        m = self.mails[0]
        self.assertEqual(m["to"], self.email)
        self.assertEqual(m["asunto"], ev[0]["message"])
        self.assertIn("Hola Nico, ", m["texto"])
        self.assertIn("MSFT cerró en US$ 120,00 y su promedio de 200 días está en US$ ", m["texto"])
        self.assertIn("la señal más usada de que la tendencia de fondo es alcista", m["texto"])
        self.assertIn("no es una recomendación para comprar ni vender", m["texto"])
        self.assertIn("no es una recomendación para comprar ni vender", m["html"])
        self.assertIn("/activo/MSFT", m["html"])
        self.assertIn("Te volvemos a avisar la próxima vez que pase.", m["texto"])
        # El push: la misma frase, con la aclaración, y abre la ficha.
        self.assertEqual(len(self.pushes), 1)
        self.assertIn("no es una recomendación", self.pushes[0]["body"])
        self.assertEqual(self.pushes[0]["url"], "/activo/MSFT")

        # Una sola vez: el cron vuelve a pegar, y las velas se vuelven a guardar
        # la misma noche (el botón de /admin): nada nuevo.
        self._cron()
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(len(self._eventos()), 1, "el mismo cruce no se avisa dos veces")
        self.assertEqual(len(self.mails), 1)

    def _seguir_por_alerta_y_crear(self, hasta=None, **kw):
        """El camino del botón «Avisame» de la ficha: alguien ya seguía MSFT (acá,
        por la watchlist), la noche guardó velas hasta anteayer y la ficha las
        mostraba; ahí se crea la alerta, que mira desde esa última vela."""
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(hasta or self.anteayer)
        res = self._crear(**kw)
        self.assertTrue(res["velas"])
        self._cron()
        self.assertEqual(self._eventos(), [], "con las velas de antes de crearla no avisa nada")
        return res

    def test_la_alerta_hace_que_se_guarden_las_velas_de_un_activo_que_nadie_tiene(self):
        self.yahoo.precios["MSFT"] = lambda d: 100.0
        self._crear()
        self._noche(self.ayer)
        with main.db_abierta() as conn:
            import velas_diarias
            self.assertIn("MSFT", velas_diarias.simbolos_a_seguir(conn))
            self.assertTrue(velas_diarias.serie(conn, "MSFT"))

    def test_creada_sin_velas_mira_desde_lo_que_cierre_hoy(self):
        """Un activo que nadie tenía: al crearla no hay velas; esa noche se baja
        la historia entera y lo de antes de crearla no avisa (es un cruce viejo)."""
        self.yahoo.precios["MSFT"] = self._sube_ayer
        res = self._crear()
        self.assertFalse(res["velas"])
        self.assertTrue(res["resolved"], "el ticker existe: tiene precio")
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])

    def test_un_cruce_viejo_no_avisa(self):
        """La alerta se crea cuando el cruce ya está en las velas: no avisa."""
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._noche(self.ayer)
        self._crear()
        self._cron()
        self.assertEqual(self._eventos(), [])
        self.assertEqual(self.mails, [])

    def test_sin_velas_suficientes_no_avisa(self):
        """Con 100 días de mercado no hay promedio de 200: el salto no es un cruce."""
        corte = self.ayer - timedelta(days=140)
        base = self._sube_ayer
        self.yahoo.precios["MSFT"] = lambda d: base(d) if d >= corte else NAN
        self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])
        with main.db_abierta() as conn:
            n = len(tecnico.serie(conn, "MSFT")["velas"])
        self.assertLess(n, 200)

    def test_solo_para_abajo_no_avisa_una_suba(self):
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear(direction="below")
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])

    def test_una_vez_se_apaga_al_avisar(self):
        self.yahoo.precios["MSFT"] = self._sube_ayer
        res = self._seguir_por_alerta_y_crear(repeat="once")
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(len(self._eventos()), 1)
        self.assertEqual(self._alerta(res["id"])["active"], 0)
        self.assertIn("Esta alerta ya cumplió.", self.mails[0]["texto"])

    def test_reactivarla_mira_desde_ahora(self):
        """Pausada mientras cruzó: al reactivarla no avisa ese cruce de golpe."""
        self.yahoo.precios["MSFT"] = self._sube_ayer
        res = self._seguir_por_alerta_y_crear()
        self.client.patch(f"/api/alerts/{res['id']}", json={"active": False}, headers=self.h)
        self._noche(self.ayer)
        self._cron()
        r = self.client.patch(f"/api/alerts/{res['id']}", json={"active": True}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._cron()
        self.assertEqual(self._eventos(), [])

    def test_un_cruce_que_llega_tarde_no_avisa(self):
        """Las velas se trabaron dos semanas y vuelven: el cruce de hace 15 días
        ya no es noticia. La marca se corre igual (no queda pendiente)."""
        hace15 = self.hoy - timedelta(days=15)
        r = _ruedas(hace15, 2)
        self.yahoo.precios["MSFT"] = lambda d: (120.0 if d >= hace15 else
                                                90.0 if d >= hace15 - timedelta(days=56) else 100.0)
        res = self._seguir_por_alerta_y_crear(hasta=r[-1])     # velas hasta antes del cruce
        self._noche(self.ayer)                  # vuelven, con el cruce adentro
        self._cron()
        self.assertEqual(self._eventos(), [])
        with main.db_abierta() as conn:
            self.assertEqual(ae._visto_hasta(conn, res["id"], "MSFT"), self.ayer.isoformat())

    def test_antes_de_las_9_no_avisa_ni_gasta_el_cruce(self):
        self.yahoo.precios["MSFT"] = self._sube_ayer
        res = self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)
        hoy = datetime.combine(self.hoy, datetime.min.time())
        with mock.patch("alerts_engine.HORA_AVISO_TECNICO", 9), main.db_abierta() as conn:
            # 08:30 en Argentina = 11:30 UTC.
            r = ae.evaluar_tecnicas(conn, now=hoy + timedelta(hours=11, minutes=30))
            self.assertEqual(r.get("fired", 0), 0)
            self.assertEqual(ae._visto_hasta(conn, res["id"], "MSFT"), self.anteayer.isoformat(),
                             "a las 8:30 no se mira nada: la marca no se mueve")
            # 09:10 en Argentina.
            r = ae.evaluar_tecnicas(conn, now=hoy + timedelta(hours=12, minutes=10))
            self.assertEqual(r["fired"], 1)

    def test_el_cron_en_vivo_no_la_mira_como_si_fuera_de_precio(self):
        """`evaluate_alerts` (cada 10 minutos, precios en vivo) no toca las
        técnicas: antes de filtrarlas, una técnica caía en la rama del %."""
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._noche(self.ayer)
        self._crear()
        with main.db_abierta() as conn:
            r = ae.evaluate_alerts(conn)
        self.assertEqual(r["alerts"], 0)

    def test_el_alta_rechaza_lo_que_no_se_puede_mirar(self):
        for body, motivo in (({"senal": "inventada"}, "señal"),
                             ({"symbol": None}, "activo"),
                             ({"scope": "holdings", "symbol": None}, "cartera"),
                             ({"symbol": "FCI:BALANZ"}, "fondo")):
            r = self.client.post("/api/alerts", json={"kind": "tecnica", "symbol": "MSFT",
                                                      "senal": "media200", **body}, headers=self.h)
            self.assertEqual(r.status_code, 400, (motivo, r.text))

    def test_el_cedear_se_guarda_pelado_y_la_accion_argentina_con_su_marca(self):
        a = self._crear(symbol="AAPL.BA")
        b = self._crear(symbol="GGAL.BA", accion_local=True, currency="ARS")
        self.assertEqual(self._alerta(a["id"])["symbol"], "AAPL")
        g = self._alerta(b["id"])
        self.assertEqual((g["symbol"], g["accion_local"], g["currency"]), ("GGAL", 1, "ARS"))
        self.assertEqual(g["direction"], "either")


class SenalesTest(unittest.TestCase):
    """Las señales sobre velas armadas a mano (`tecnico.senal_desde`)."""

    @staticmethod
    def _velas(cierres, hasta=date(2026, 10, 21)):
        dias = _ruedas(hasta + timedelta(days=1), len(cierres))
        return [{"date": d.isoformat(), "close": c} for d, c in zip(dias, cierres)]

    def test_rsi(self):
        # De costado (RSI cerca de 50), sube parejo (pasa 70), cae fuerte (baja
        # de 30) y rebota (vuelve a pasar 30).
        cierres = [100 + (i % 2) for i in range(20)] + [100 + i for i in range(40)] + [140 - 3 * i for i in range(1, 15)] + [98 + 4 * i for i in range(1, 6)]
        v = self._velas(cierres)
        r = tecnico.rsi(cierres)
        baja = tecnico.senal_desde(v, "rsi_bajo_30")
        sube = tecnico.senal_desde(v, "rsi_sube_30")
        self.assertIsNotNone(baja)
        self.assertIsNotNone(sube)
        self.assertLess(baja["fecha"], sube["fecha"])
        i = [x["date"] for x in v].index(baja["fecha"])
        self.assertTrue(r[i - 1] >= 30 > r[i], "bajó de 30 ese día, con el RSI de la ficha")
        self.assertIsNone(tecnico.senal_desde(v, "rsi_bajo_30", desde=baja["fecha"]),
                          "desde ese día no volvió a bajar: el mismo cruce no se cuenta dos veces")
        # Pasó 70 subiendo, al principio.
        self.assertIsNotNone(tecnico.senal_desde(v, "rsi_sobre_70"))

    def test_el_rsi_del_mail_no_contradice_el_cruce(self):
        """«Bajó de 30» con «quedó en 30 de 100» se contradice (era 29,6): con el
        redondeo justo en el nivel, va un decimal. Visto en la copia de prueba con
        GGAL el 14/10/2026."""
        self.assertEqual(ae._fmt_rsi(29.6, 30.0), "29,6")
        self.assertEqual(ae._fmt_rsi(27.4, 30.0), "27")
        self.assertEqual(ae._fmt_rsi(70.3, 70.0), "70,3")

    def test_maximo_del_anio_avisa_la_primera_vez(self):
        # Un año y medio bajando despacito (ningún día es el máximo de su año);
        # después sube a récord y hace máximos 5 días seguidos.
        base = [100.0 - 0.01 * i for i in range(380)]
        cierres = base + [111.0, 112.0, 113.0, 114.0, 115.0]
        v = self._velas(cierres)
        ev = tecnico.senal_desde(v, "maximo_12m")
        self.assertEqual(ev["fecha"], v[380]["date"], "el PRIMER máximo, no el último de la racha")
        self.assertIsNone(tecnico.senal_desde(v, "maximo_12m", desde=v[380]["date"]),
                          "los máximos de los días siguientes no vuelven a avisar")

    def test_maximo_sin_un_anio_de_velas_no_avisa(self):
        v = self._velas([100.0] * 100 + [120.0])
        self.assertIsNone(tecnico.senal_desde(v, "maximo_12m"))

    def test_cruce_de_media_con_sentido(self):
        cierres = [100.0] * 250 + [90.0] * 20 + [120.0]
        v = self._velas(cierres)
        self.assertEqual(tecnico.senal_desde(v, "media200", sentido="arriba")["fecha"], v[-1]["date"])
        ab = tecnico.senal_desde(v, "media200", sentido="abajo")
        self.assertEqual(ab["fecha"], v[250]["date"], "la bajada a 90 fue el cruce para abajo")
        self.assertIsNone(tecnico.senal_desde(v, "media200", desde=v[-1]["date"]))


if __name__ == "__main__":
    unittest.main()
