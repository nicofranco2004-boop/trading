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
from velas_diarias import PERIODO_COMPLETO

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
        # Yahoo tiene 760 ruedas (~3 años) de cada papel de prueba: menos que lo que
        # pide la bajada completa (5 años), como un papel que cotiza hace poco.
        n = 760 if period == PERIODO_COMPLETO else 22
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
            for t in ("velas_diarias", "velas_estado", "watchlist",
                      "positions", "brokers", "alerts", "alert_events", "alert_symbol_state",
                      "dibujos_grafico"):
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
        self.byma = {}          # la lista de CEDEARs de BYMA (data912)
        self.mails, self.pushes = [], []
        self._p = [
            mock.patch("main._check_rate_limit"),
            mock.patch("pricing.yahoo._historia", self.yahoo),
            mock.patch("main._fetch_data912_equities", lambda: self.byma),
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

    def _crear(self, creada_el=None, **kw):
        """Crea la alerta por HTTP. `creada_el`: el día (Argentina) en que se
        creó, a la tarde, antes del cierre: lo que cierra ESE día es nuevo. Sin
        él, se crea hoy."""
        body = {"kind": "tecnica", "symbol": "MSFT", "senal": "media200",
                "direction": "either", "channel": "both", "repeat": "always", **kw}
        with self._el_dia(creada_el):
            r = self.client.post("/api/alerts", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _el_dia(self, d):
        return mock.patch("fechas.hoy_art_date", lambda: d) if d else mock.MagicMock()

    @staticmethod
    def _siguiente(d):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

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

    def test_el_umbral_del_salto_sale_de_la_lista_de_cambios_de_ratio(self):
        # ficha-tecnica mudó SALTO_SIN_EXPLICAR de velas_diarias a cambios_ratio.
        # Leído del lugar viejo, CADA alerta técnica reventaba en el cron (las 5
        # pruebas de aviso de este archivo se ponen rojas). Ver 11f57c03.
        import cambios_ratio
        self.assertEqual(ae._salto_sospechoso(), cambios_ratio.SALTO_SIN_EXPLICAR)

    def test_un_error_de_las_tecnicas_queda_a_la_vista_y_no_corta_las_de_precio(self):
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)
        roto = mock.patch("tecnico.senal_desde", side_effect=AttributeError("algo se mudó"))
        with roto, self.assertLogs("alerts", level="ERROR") as logs:
            r = self._cron()
        self.assertEqual(r["tecnicas"].get("errores"), 1, "el cron cuenta el error")
        self.assertTrue(any("AttributeError" in x and "algo se mudó" in x for x in logs.output),
                        "el registro dice QUÉ error fue")
        self.assertIn("alerts", r, "las alertas de precio se evaluaron igual")
        # Arreglado el error, la vela que no se pudo mirar se mira en la pasada siguiente.
        self._cron()
        self.assertEqual(len(self._eventos()), 1)

    def test_un_error_despues_de_avisar_no_repite_el_mail_cada_10_minutos(self):
        """Auditoría C, hallazgo 1 (29/10), la forma que se ve también en SQLite:
        la alerta avisa (`_fire` escribe el evento y encola el mail) y DESPUÉS
        algo de esa misma alerta falla (acá, correr su marca). Antes: el mail
        salía igual y la marca quedaba atrás → el cron, 10 minutos después,
        volvía a avisar el mismo cruce, y así toda la jornada. Ahora lo de esa
        alerta se deshace entero (su punto de guardado) y no se manda nada hasta
        que se pueda guardar; arreglado el error, avisa una vez."""
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)
        roto = mock.patch("alerts_engine._marcar_visto", side_effect=RuntimeError("la base no responde"))
        with roto, self.assertLogs("alerts", level="ERROR") as logs:
            r1 = self._cron()
            r2 = self._cron()
        self.assertEqual((r1["tecnicas"].get("errores"), r2["tecnicas"].get("errores")), (1, 1))
        self.assertTrue(any("RuntimeError" in x for x in logs.output))
        self.assertEqual(len(self.mails), 0, "no se manda un aviso que no quedó guardado")
        self.assertEqual(self._eventos(), [], "lo de la alerta rota se deshizo entero")
        self._cron()
        self._cron()
        self.assertEqual((len(self.mails), len(self._eventos())), (1, 1), "arreglado, avisa UNA vez")

    def test_una_alerta_rota_en_la_base_no_se_lleva_el_aviso_de_la_otra(self):
        """C1 tal cual lo midió la auditoría: dos alertas cruzan, a la de AAPL le
        falla una consulta a la BASE. En Postgres eso abortaba la transacción
        compartida: el commit de después deshacía el aviso de MSFT, que salía
        igual y se repetía cada 10 minutos (pgshim de esta punta) o no salía
        nunca (pgshim de la migración). En los dos motores: MSFT avisa una vez
        y queda guardado; AAPL queda contada como error."""
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self.yahoo.precios["AAPL"] = self._sube_ayer
        for sym in ("MSFT", "AAPL"):
            self.client.post("/api/watchlist", json={"symbol": sym}, headers=self.h)
        self._noche(self.anteayer)
        for sym in ("MSFT", "AAPL"):
            self._crear(creada_el=self._siguiente(self.anteayer), symbol=sym)
        self._noche(self.ayer)
        original = ae._serie_tecnica

        def serie(conn, alert):
            if alert["symbol"] == "AAPL":
                conn.execute("SELECT * FROM tabla_que_no_existe")
            return original(conn, alert)
        with mock.patch("alerts_engine._serie_tecnica", serie), self.assertLogs("alerts", level="ERROR"):
            r = [self._cron() for _ in range(3)]
        self.assertEqual([x["tecnicas"].get("errores") for x in r], [1, 1, 1])
        self.assertEqual([e["symbol"] for e in self._eventos()], ["MSFT"])
        self.assertEqual(len(self.mails), 1)

    def test_si_lo_disparado_no_quedo_guardado_no_se_entrega(self):
        """La otra mitad del C1: el commit puede «salir bien» sin guardar (en
        Postgres, el de una transacción abortada es un ROLLBACK callado). La
        entrega pregunta a la base qué avisos existen y sólo manda esos."""
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)

        class CommitQueMiente:
            """El commit «sale bien» pero lo disparado no está en la base (en
            Postgres: el commit de una transacción abortada). En SQLite el punto
            de guardado ya confirma al soltarse, así que la mentira se arma
            borrando lo escrito: lo que se mide es que la entrega le pregunte a
            la BASE y no al commit."""
            def __init__(self, c):
                self._c = c

            def commit(self):
                self._c.commit()
                self._c.execute("DELETE FROM alert_events")
                self._c.commit()

            def __getattr__(self, k):
                return getattr(self._c, k)
        with main.db_abierta() as conn, self.assertLogs("alerts", level="ERROR") as logs:
            ae.evaluar_tecnicas(CommitQueMiente(conn))
        self.assertEqual(len(self.mails), 0)
        self.assertTrue(any("no quedó guardado" in x for x in logs.output))

    def test_cruza_su_promedio_de_200_y_avisa_una_sola_vez_con_el_mail_armado(self):
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)                       # llega la vela del cruce
        self._cron()
        ev = self._eventos()
        self.assertEqual(len(ev), 1, "el cruce de ayer avisa")
        self.assertEqual(ev[0]["message"],
                         "MSFT superó su promedio de 200 días: la tendencia de largo plazo pasó a ser alcista")
        self.assertEqual(ev[0]["delivered_email"], 1)
        self.assertEqual(ev[0]["delivered_push"], 1)

        # El mail, armado por send_alert_email de verdad.
        self.assertEqual(len(self.mails), 1)
        m = self.mails[0]
        self.assertEqual(m["to"], self.email)
        self.assertEqual(m["asunto"], ev[0]["message"])
        self.assertIn("Hola Nico, ", m["texto"])
        self.assertIn("MSFT cerró en US$ 120,00 y su promedio de 200 días está en US$ ", m["texto"])
        self.assertIn("la referencia más usada para decir que la tendencia de largo plazo es alcista", m["texto"])
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

    def test_de_un_cliente_el_push_y_el_mail_llevan_a_mis_clientes(self):
        """Auditoría B, hallazgo B2 (29/10): el push de la alerta técnica de
        Juan abría «Mis alertas» de LAURA (donde la de Juan no está) mientras el
        mail llevaba a /clientes; y «en la cuenta de Juan» quedaba pegado al
        final de la lectura («…la tendencia de fondo es alcista, en la cuenta
        de Juan.»). El destino del push y el del botón se calculaban en dos
        lugares; ahora salen de `alerts_engine.entrega`."""
        with main.db_abierta() as conn:
            adv = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Laura Asesora', 'x', 1, 1, 'pro')",
                (f"asesor-{uuid.uuid4().hex[:6]}@rendi.test",)).lastrowid
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (adv, self.uid))
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, label) VALUES (?,?,?)",
                         (adv, self.uid, "Juan"))
            conn.commit()
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear()
        self._noche(self.ayer)
        self._cron()
        self.assertEqual((len(self.mails), len(self.pushes)), (1, 1))
        m, p = self.mails[0], self.pushes[0]
        self.assertTrue(m["asunto"].startswith("[Juan] MSFT superó su promedio"))
        self.assertIn("Hola Laura, en la cuenta de Juan, ", m["texto"])
        self.assertIn("la tendencia de largo plazo es alcista.\n", m["texto"],
                      "la lectura termina en su punto, sin «, en la cuenta de Juan» pegado")
        self.assertIn("/clientes", m["html"])
        self.assertNotIn("/activo/MSFT", m["html"], "la ficha del asesor no es la de Juan")
        self.assertEqual(p["url"], "/clientes",
                         "el push abría «Mis alertas» del ASESOR, donde la alerta de Juan no está")
        self.assertTrue(p["body"].startswith("[Juan] MSFT superó su promedio"))
        self.assertIn("no es una recomendación", p["body"])

    def _seguir_por_alerta_y_crear(self, hasta=None, **kw):
        """El camino del botón «Avisame» de la ficha: alguien ya seguía MSFT (acá,
        por la watchlist), la noche guardó velas hasta anteayer y al día
        siguiente (ayer, antes del cierre) la ficha las mostraba y se creó la
        alerta: lo que cerró ayer es nuevo."""
        hasta = hasta or self.anteayer
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(hasta)
        res = self._crear(creada_el=self._siguiente(hasta), **kw)
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

    def test_velas_atrasadas_al_crear_no_avisan_un_cruce_de_antes(self):
        """Alguien seguía MSFT hasta hace semanas: la última vela guardada es
        vieja. La alerta se crea hoy; esa noche se bajan los días que faltaban,
        con un cruce de hace 3 días adentro: es de antes de crearla, no avisa.
        (Auditoría 22/10: con la marca en la última vela, avisaba.)"""
        r = _ruedas(self.hoy, 30)
        self.yahoo.precios["MSFT"] = lambda d: (120.0 if d >= r[-3] else
                                                90.0 if d >= r[-3] - timedelta(days=56) else 100.0)
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(r[-12])
        self._crear()
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])

    def test_reactivar_una_alerta_que_era_lo_unico_que_seguia_el_activo(self):
        """Pausada, nadie más sigue el activo: sus velas dejan de bajarse. Cruza
        mientras tanto; al reactivarla se bajan los días que faltaban y ese cruce
        no avisa (auditoría 22/10)."""
        r = _ruedas(self.hoy, 30)
        self.yahoo.precios["MSFT"] = lambda d: (120.0 if d >= r[-3] else
                                                90.0 if d >= r[-3] - timedelta(days=56) else 100.0)
        res = self._crear(creada_el=r[-8])
        self._noche(r[-8])
        self.client.patch(f"/api/alerts/{res['id']}", json={"active": False}, headers=self.h)
        self._noche(self.ayer)
        with main.db_abierta() as conn:
            self.assertEqual(tecnico.serie(conn, "MSFT")["velas"][-1]["date"], r[-8].isoformat(),
                             "pausada, sus velas no se bajan")
        self.client.patch(f"/api/alerts/{res['id']}", json={"active": True}, headers=self.h)
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])

    def test_dos_dias_juntos_que_cruzan_y_vuelven_no_avisan(self):
        """Una noche no corrió: llegan dos días juntos. Cruzó para arriba y al día
        siguiente volvió abajo: la ficha dice «Bajista» y la alerta «para arriba»
        no avisa (auditoría 22/10: avisaba «se volvió alcista»)."""
        r = _ruedas(self.hoy, 30)
        self.yahoo.precios["MSFT"] = lambda d: (90.0 if d >= self.ayer else 120.0 if d >= self.anteayer else
                                                90.0 if d >= r[-2] - timedelta(days=56) else 100.0)
        self._seguir_por_alerta_y_crear(hasta=r[-3], direction="above")
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
            antes = ae._visto_hasta(conn, res["id"], "MSFT")
            # 08:30 en Argentina = 11:30 UTC.
            r = ae.evaluar_tecnicas(conn, now=hoy + timedelta(hours=11, minutes=30))
            self.assertEqual(r.get("fired", 0), 0)
            self.assertEqual(ae._visto_hasta(conn, res["id"], "MSFT"), antes,
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

    def test_un_split_que_yahoo_tarda_dos_noches_en_reescribir_no_avisa(self):
        """Yahoo a veces publica los cierres de después del split SIN reescribir
        la historia, y tarda varias noches: la acción "cae" 75 % y quedaría
        abajo de su promedio de 200 días. Se espera hasta que el precio nuevo
        se sostenga 3 días; antes de eso Yahoo reescribió todo y no hubo cruce.
        (Auditoría 22/10: esperar sólo el último día avisaba la 2da noche.)"""
        r = _ruedas(self.hoy, 30)
        dia_split = r[-3]

        def base(d):
            return 110.0 if d >= self.ayer - timedelta(days=90) else 100.0
        self.yahoo.precios["MSFT"] = lambda d: base(d) / 4 if d >= dia_split else base(d)
        self._seguir_por_alerta_y_crear(hasta=r[-4])
        for noche in (r[-3], r[-2]):                # dos noches con la historia sin dividir
            self._noche(noche)
            self._cron()
            self.assertEqual(self._eventos(), [], f"la noche del {noche} se espera")
        # La tercera noche Yahoo ya reescribió todo: no hubo cruce.
        self.yahoo.precios["MSFT"] = lambda d: base(d) / 4
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])

    def test_una_caida_de_verdad_avisa_cuando_se_sostiene(self):
        """Si el salto era real (la acción se desplomó y se quedó ahí), avisa
        cuando el precio nuevo se sostiene 3 días, una sola vez, con la fecha
        del día del cruce."""
        r = _ruedas(self.hoy, 30)
        dia = r[-3]
        self.yahoo.precios["MSFT"] = lambda d: (50.0 if d >= dia else
                                                110.0 if d >= self.ayer - timedelta(days=90) else 100.0)
        self._seguir_por_alerta_y_crear(hasta=r[-4])
        for noche in (r[-3], r[-2]):
            self._noche(noche)
            self._cron()
            self.assertEqual(self._eventos(), [])
        self._noche(self.ayer)
        self._cron()
        self._cron()
        ev = self._eventos()
        self.assertEqual(len(ev), 1)
        self.assertTrue(ev[0]["message"].startswith("MSFT cayó por debajo de su promedio de 200 días"))
        self.assertIn(f"{dia.day}/{dia.month}", self.mails[0]["texto"], "el mail dice el día del cruce")

    def test_la_misma_alerta_dos_veces_no(self):
        """Dos alertas que avisan el mismo cruce son dos mails: la segunda se
        rechaza si pide lo mismo o si alguna es «los dos lados»."""
        def otra(direction):
            return self.client.post("/api/alerts", json={"kind": "tecnica", "symbol": "MSFT", "senal": "media200",
                                                         "direction": direction}, headers=self.h).status_code
        self._crear(direction="above")
        self.assertEqual(otra("above"), 409)
        self.assertEqual(otra("either"), 409, "«los dos lados» incluye el de arriba")
        self.assertEqual(otra("below"), 200, "el otro lado sí es otra alerta")
        self.assertEqual(otra("below"), 409)
        # Otra señal u otra moneda, sí.
        self._crear(senal="media50")
        self._crear(currency="ARS")

    def test_se_siguen_las_velas_que_mira_cada_alerta(self):
        """Lo que guarda la noche tiene que ser lo que lee la alerta: un CEDEAR
        en dólares (la acción de afuera), un CEDEAR en pesos (también su '.BA'),
        una acción argentina (su '.BA')."""
        self.byma = {"AAPL": {"mercado": "arg_cedears"}, "GGAL": {"mercado": "arg_stocks"}}
        self._crear(symbol="MSFT")
        self._crear(symbol="AAPL", currency="ARS")
        self._crear(symbol="GGAL", accion_local=True)
        with main.db_abierta() as conn:
            import velas_diarias
            self.assertEqual(set(velas_diarias.simbolos_a_seguir(conn)),
                             {"MSFT", "AAPL", "AAPL.BA", "GGAL.BA", velas_diarias.SP500})

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

    def test_precio_tecnica_linea_y_recordatorio_en_la_misma_pasada_cada_una_por_su_camino(self):
        """Todas las clases de alerta del mismo motor, en UNA pasada del cron de
        siempre (`main._evaluar_alertas_job`): la de precio la mira
        `evaluate_alerts` (precios en vivo); la técnica y la de tu línea
        dibujada (`kind='tecnica'`, `senal='linea'`) `evaluar_tecnicas` (las
        velas de la noche: la línea se mira contra el mínimo y el máximo del
        día, que en vivo no hay); el recordatorio de una tesis
        `evaluar_recordatorios` (su día). Cada una dispara una vez y por su
        rama: si el filtro de `evaluate_alerts` (`KINDS_EN_VIVO`) dejara entrar
        a las técnicas o al recordatorio, caerían en la rama del % (pieza 11 +
        alertas técnicas + líneas, mezclas del 29/10)."""
        # La técnica: MSFT cruza ayer su promedio de 200 días.
        self.yahoo.precios["MSFT"] = self._sube_ayer
        self._seguir_por_alerta_y_crear()
        # Tu línea: una horizontal en 120 que el precio toca ayer (de 90 a 120).
        self._dibujar(self._horizontal(120))
        self._crear_linea()
        self._noche(self.ayer)
        # La de precio: KO arriba de 110 (está en 100 al crearla).
        r = self.client.post("/api/alerts", json={
            "kind": "price_target", "symbol": "KO", "threshold": 110, "direction": "above",
            "channel": "both", "repeat": "always"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        # El recordatorio: la tesis de NVDA, con su día hoy.
        r = self.client.put("/api/tesis", json={"asset": "NVDA", "texto": "Data centers e IA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["id"]
        r = self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        with main.db_abierta() as conn:
            conn.execute("UPDATE tesis SET recordar_el=? WHERE id=?", (self.hoy.isoformat(), tid))
            conn.commit()

        with mock.patch("alerts_engine._prices_for", lambda syms: {s: 120.0 for s in syms}), \
             mock.patch("alerts_engine._market_open_now", lambda now: True), \
             mock.patch("alerts_engine.HORA_RECORDATORIO", 0):
            res = self._cron()
            self._cron()                       # la segunda pasada no repite nada
        # La pasada en vivo mira SÓLO la de precio: las técnicas y el
        # recordatorio no disparan por ahí (no tienen límite de precio), así que
        # lo que se ve de afuera es cuántas alertas miró.
        self.assertEqual(res["alerts"], 1, res)
        self.assertEqual(res["tecnicas"]["fired"], 2, res)      # el cruce y la línea
        self.assertEqual(res["recordatorios"], 1, res)
        with main.db_abierta() as conn:
            ev = [dict(x) for x in conn.execute(
                "SELECT a.kind, e.symbol, e.message, e.delivered_email, e.delivered_push "
                "FROM alert_events e JOIN alerts a ON a.id = e.alert_id WHERE e.user_id=? ORDER BY e.id",
                (self.uid,)).fetchall()]
        self.assertEqual(sorted((e["kind"], e["symbol"]) for e in ev),
                         [("price_target", "KO"), ("recordatorio", "NVDA"), ("tecnica", "MSFT"), ("tecnica", "MSFT")], ev)
        por = {e["kind"]: e for e in ev}
        self.assertTrue(por["price_target"]["message"].startswith("KO"), por["price_target"])
        self.assertEqual(sorted(e["message"][:40] for e in ev if e["kind"] == "tecnica"),
                         ["MSFT subió hasta tu línea horizontal, en", "MSFT superó su promedio de 200 días: la "])
        self.assertEqual(por["recordatorio"]["message"], "Quedaste en revisar tu tesis de NVDA")
        for e in ev:
            self.assertEqual((e["delivered_email"], e["delivered_push"]), (1, 1), e)
        # Cada push abre lo suyo: la de precio «Mis alertas», las técnicas la
        # ficha con el gráfico (el cruce, tu línea), el recordatorio la ficha con
        # tu tesis.
        self.assertEqual(sorted(p["url"] for p in self.pushes),
                         ["/activo/MSFT", "/activo/MSFT?linea=h1&moneda=usd", "/activo/NVDA", "/alertas?tab=mis"])
        self.assertEqual(len(self.mails), 4)

    # — tu línea: «avisame si el precio toca esta línea» (Nico, 28/10) —
    # La línea se guarda como la guarda la ficha (PUT /api/tecnico/…/dibujos) y
    # el aviso se crea como lo crea el botón del cartel de la línea elegida.

    def _dibujar(self, *dibujos, asset="MSFT", moneda="usd", headers=None):
        r = self.client.put(f"/api/tecnico/{asset}/dibujos?moneda={moneda}",
                            json={"dibujos": list(dibujos)}, headers=headers or self.h)
        self.assertEqual(r.status_code, 200, r.text)

    @staticmethod
    def _horizontal(precio, id="h1"):
        return {"id": id, "tipo": "horizontal", "precio": precio}

    def _crear_linea(self, dibujo="h1", esperado=200, **kw):
        body = {"kind": "tecnica", "symbol": "MSFT", "senal": "linea", "dibujo": dibujo,
                "currency": "USD", "channel": "both", "repeat": "once", **kw}
        with self._el_dia(self._siguiente(self.anteayer)):
            r = self.client.post("/api/alerts", json=body, headers=self.h)
        self.assertEqual(r.status_code, esperado, r.text)
        return r.json()

    def _preparar_linea(self, *dibujos, **kw):
        """Alguien seguía MSFT, la noche guardó hasta anteayer; ayer (antes del
        cierre) dibujaste y pediste el aviso. Lo que cerró ayer es nuevo."""
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(self.anteayer)
        self._dibujar(*dibujos)
        res = self._crear_linea(**kw)
        self._cron()
        self.assertEqual(self._eventos(), [], "lo que cerró antes de pedirlo no avisa")
        return res

    def _salta_ayer(self, d):
        return 110.0 if d >= self.ayer else 100.0    # ayer: de 108,90 a 111,10

    def test_linea_horizontal_tocada_en_el_dia_avisa_una_vez_con_el_minimo_y_el_maximo(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        res = self._preparar_linea(self._horizontal(109.5))
        self._noche(self.ayer)
        self._cron()
        ev = self._eventos()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["message"], "MSFT subió hasta tu línea horizontal, en US$ 109,50")
        self.assertEqual(self.mails[0]["asunto"], ev[0]["message"])
        texto = self.mails[0]["texto"]
        self.assertIn("tocó tu línea horizontal, que ese día estaba en US$ 109,50", texto)
        self.assertIn("fue de US$ 108,90 a US$ 111,10 y cerró en US$ 110,00", texto)
        self.assertIn("no es una recomendación", texto)
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self._alerta(res["id"])["active"], 0, "«una vez»: avisó y se apagó")
        self._cron()
        self.assertEqual(len(self._eventos()), 1, "no repite")

    def test_linea_que_el_precio_no_toca_no_avisa(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        res = self._preparar_linea(self._horizontal(115))
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])
        self.assertEqual(self._alerta(res["id"])["active"], 1)

    def test_linea_de_tendencia_sigue_en_su_direccion_despues_del_segundo_punto(self):
        # De 80 a 100 en 10 ruedas (2 por rueda): ayer, 10 ruedas después del
        # segundo punto, la línea pasa por 120; anteayer estaba en 118 y el
        # precio en 100 (no la tocaba). Ayer el precio salta a 120 y la toca.
        r = _ruedas(self.hoy, 30)
        a, b = r[-21], r[-11]        # 20 y 10 ruedas antes de ayer
        self.yahoo.precios["MSFT"] = lambda d: 120.0 if d >= self.ayer else 100.0
        linea = {"id": "t1", "tipo": "tendencia", "a": {"d": a.isoformat(), "mas": 0, "precio": 80},
                 "b": {"d": b.isoformat(), "mas": 0, "precio": 100}}
        self._preparar_linea(linea, dibujo="t1")
        self._noche(self.ayer)
        self._cron()
        ev = self._eventos()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["message"], "MSFT subió hasta tu línea de tendencia, en US$ 120,00")

    def test_si_moves_la_linea_el_aviso_la_sigue(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        self._preparar_linea(self._horizontal(130))
        self._dibujar(self._horizontal(109.5))       # la arrastraste (mismo id)
        self._noche(self.ayer)
        self._cron()
        self.assertEqual([e["message"] for e in self._eventos()],
                         ["MSFT subió hasta tu línea horizontal, en US$ 109,50"])

    def test_si_borras_la_linea_el_aviso_se_apaga_sin_avisar(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        res = self._preparar_linea(self._horizontal(109.5))
        self._dibujar(self._horizontal(50, id="otra"))
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])
        self.assertEqual(self._alerta(res["id"])["active"], 0)

    def test_el_alta_de_una_linea_pide_que_sea_tuya_y_una_sola_vez(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        self._noche(self.anteayer)
        self._crear_linea(esperado=404)                         # todavía no está guardada
        # La de otra persona tampoco.
        with main.db_abierta() as conn:
            otro = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Otra', 'x', 1, 1, 'pro')", (f"otra-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        self._dibujar(self._horizontal(109.5), headers={"Authorization": f"Bearer {main.create_token(otro)}"})
        self._crear_linea(esperado=404)
        # Un Fibonacci no es una línea.
        self._dibujar({"id": "f1", "tipo": "fibonacci", "a": {"d": self.anteayer.isoformat(), "mas": 0, "precio": 90},
                       "b": {"d": self.anteayer.isoformat(), "mas": 3, "precio": 110}})
        self._crear_linea(dibujo="f1", esperado=400)
        self._dibujar(self._horizontal(109.5))
        self._crear_linea()
        self.assertIn("Ya te avisamos", self._crear_linea(esperado=409)["detail"])
        # En pesos es otra línea (otro dibujo): no choca con la de dólares.
        self._dibujar(self._horizontal(150000), moneda="ars")
        self._crear_linea(currency="ARS")

    def test_toque_de_linea_tambien_con_un_salto_por_encima(self):
        # Sin máximo ni mínimo (una vela guardada sólo con cierre): pasar de un
        # lado al otro de la línea entre un cierre y el siguiente es tocarla.
        velas = [{"date": "2026-10-01", "close": 100.0}, {"date": "2026-10-02", "close": 104.0}]
        ev = tecnico.toque_de_linea(velas, {"tipo": "horizontal", "precio": 102}, "2026-10-01")
        self.assertEqual((ev["fecha"], ev["sentido"]), ("2026-10-02", "arriba"))
        ev = tecnico.toque_de_linea(velas, {"tipo": "horizontal", "precio": 106}, "2026-10-01")
        self.assertIsNone(ev)
        bajando = [{"date": "2026-10-01", "close": 104.0}, {"date": "2026-10-02", "close": 100.0}]
        self.assertEqual(tecnico.toque_de_linea(bajando, {"tipo": "horizontal", "precio": 102}, "2026-10-01")["sentido"], "abajo")

    # — tu canal: «avisame si sale del canal» (Nico, 29/10) —
    # Lo dibuja la ficha (PUT …/dibujos: la línea a → b y la paralela `ancho`
    # más arriba) y el aviso sale del cartel del canal elegido, con por qué
    # borde (`direction`) y cuándo cuenta (`modo`).

    def _canal(self, ancho=10.0, id="c1", piso=95.0):
        """Un canal plano de `piso` a `piso + ancho`: el precio en 100 va adentro."""
        r = _ruedas(self.hoy, 30)
        return {"id": id, "tipo": "canal", "a": {"d": r[-21].isoformat(), "mas": 0, "precio": piso},
                "b": {"d": r[-11].isoformat(), "mas": 0, "precio": piso}, "ancho": ancho}

    def test_canal_tocado_por_arriba_avisa_con_el_borde_del_dia(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer      # ayer: de 108,90 a 111,10, cierra 110
        res = self._preparar_linea(self._canal(), dibujo="c1", direction="either")
        g = self._alerta(res["id"])
        self.assertEqual(g["direction"], "either")
        self.assertEqual(ae.referencia_de_linea(g["dibujo"])["modo"], "toque")
        self._noche(self.ayer)
        self._cron()
        ev = self._eventos()
        self.assertEqual([e["message"] for e in ev], ["MSFT subió hasta el borde de arriba de tu canal, en US$ 105,00"])
        texto = self.mails[0]["texto"]
        self.assertIn("tocó el borde de arriba de tu canal, que ese día estaba en US$ 105,00", texto)
        self.assertIn("fue de US$ 108,90 a US$ 111,10 y cerró en US$ 110,00. Es el canal que dibujaste", texto)
        # El botón del mail y el push abren la ficha con el canal elegido.
        self.assertIn("/activo/MSFT?linea=c1&amp;moneda=usd", self.mails[0]["html"])
        self.assertEqual(self.pushes[0]["url"], "/activo/MSFT?linea=c1&moneda=usd")

    def test_canal_pedido_por_abajo_no_avisa_si_sale_por_arriba(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        res = self._preparar_linea(self._canal(), dibujo="c1", direction="below")
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [])
        self.assertEqual(self._alerta(res["id"])["active"], 1)

    def test_canal_que_baja_avisa_por_el_borde_de_abajo(self):
        self.yahoo.precios["MSFT"] = lambda d: 90.0 if d >= self.ayer else 100.0
        self._preparar_linea(self._canal(), dibujo="c1", direction="either")
        self._noche(self.ayer)
        self._cron()
        self.assertEqual([e["message"] for e in self._eventos()],
                         ["MSFT bajó hasta el borde de abajo de tu canal, en US$ 95,00"])

    def test_canal_si_cierra_afuera_no_avisa_un_toque_que_vuelve_adentro(self):
        # Borde de arriba en 110,50: ayer lo tocó (máximo 111,10) pero cerró en 110.
        self.yahoo.precios["MSFT"] = self._salta_ayer
        self._preparar_linea(self._canal(ancho=15.5), dibujo="c1", direction="either", modo="cierre")
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [], "cerró adentro: con «si cierra afuera» no avisa")

    def test_canal_que_cierra_afuera_avisa_con_el_cierre(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        self._preparar_linea(self._canal(ancho=14.5), dibujo="c1", direction="above", modo="cierre")
        self._noche(self.ayer)
        self._cron()
        self.assertEqual([e["message"] for e in self._eventos()],
                         ["MSFT cerró arriba de tu canal: US$ 110,00, con el borde en US$ 109,50"])
        self.assertIn("cerró en US$ 110,00, arriba del borde de arriba de tu canal, que ese día estaba en US$ 109,50",
                      self.mails[0]["texto"])

    def test_canal_tocado_que_cierra_adentro_lo_dice(self):
        # Pedido ANTEAYER: el toque de ayer es de un día entero posterior al
        # pedido. Pedido ayer, ese toque que vuelve adentro podría ser de antes
        # del pedido y no cuenta (`pedida_el`, al juntar con la auditoría chica,
        # 30/10).
        self.yahoo.precios["MSFT"] = self._salta_ayer
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(self.anteayer)
        self._dibujar(self._canal(ancho=15.5))
        body = {"kind": "tecnica", "symbol": "MSFT", "senal": "linea", "dibujo": "c1", "direction": "either",
                "currency": "USD", "channel": "both", "repeat": "once"}
        with self._el_dia(self.anteayer):
            r = self.client.post("/api/alerts", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._noche(self.ayer)
        self._cron()
        self.assertIn("y cerró en US$ 110,00, o sea que volvió a quedar adentro.", self.mails[0]["texto"])

    def test_salida_de_canal_no_avisa_cada_dia_que_sigue_afuera(self):
        canal = {"tipo": "canal", "a": {"d": "2026-10-01", "mas": 0, "precio": 95},
                 "b": {"d": "2026-10-02", "mas": 0, "precio": 95}, "ancho": 10}
        afuera = [{"date": f"2026-10-0{d}", "close": c} for d, c in ((1, 108), (2, 109), (3, 110))]
        self.assertIsNone(tecnico.salida_de_canal(afuera, canal, "2026-10-01"),
                          "ya andaba afuera: avisa la próxima vez que salga, no cada día")
        vuelve = afuera + [{"date": "2026-10-06", "close": 100}, {"date": "2026-10-07", "close": 106}]
        self.assertEqual(tecnico.salida_de_canal(vuelve, canal, "2026-10-01")["fecha"], "2026-10-07")

    # — lo que encontró la auditoría a ciegas del 29/10 —

    def test_un_canal_anclado_antes_de_la_historia_guardada_sigue_vigilando(self):
        # Las velas viejas se borran: el punto a (28/09) queda antes de la
        # primera vela guardada. Antes daba None y el aviso se callaba.
        velas = [{"date": d, "close": 100.0} for d in ("2026-10-05", "2026-10-06", "2026-10-07")]
        canal = {"tipo": "canal", "a": {"d": "2026-09-28", "mas": 0, "precio": 90},
                 "b": {"d": "2026-10-05", "mas": 0, "precio": 95}, "ancho": 10}
        # De a (5 días hábiles antes) a b, sube 1 por día: el 07/10 está en 97..107.
        self.assertEqual(tecnico.bordes_de_canal(velas, canal, 2), (97.0, 107.0))
        sube = velas + [{"date": "2026-10-08", "close": 109.0}]
        self.assertEqual(tecnico.salida_de_canal(sube, canal, "2026-10-07")["referencia"], 108.0)

    def test_tocar_cuenta_tambien_con_el_cierre_si_el_maximo_vino_mal(self):
        canal = {"tipo": "canal", "a": {"d": "2026-10-01", "mas": 0, "precio": 95},
                 "b": {"d": "2026-10-02", "mas": 0, "precio": 95}, "ancho": 10}
        velas = [{"date": "2026-10-01", "close": 100.0, "high": 101, "low": 99},
                 {"date": "2026-10-02", "close": 106.0, "high": 104, "low": 99}]   # el máximo, parcial
        self.assertEqual(tecnico.salida_de_canal(velas, canal, "2026-10-01")["sentido"], "arriba")
        self.assertEqual(tecnico.toque_de_linea(velas, {"tipo": "horizontal", "precio": 105}, "2026-10-01")["fecha"], "2026-10-02")

    def test_una_salida_vieja_por_velas_atrasadas_no_tapa_una_nueva(self):
        r = _ruedas(self.hoy, 30)
        vieja = r[-15]                       # más de una semana: llega tarde, no se avisa
        self.yahoo.precios["MSFT"] = lambda d: 110.0 if d in (vieja, self.ayer) else 100.0
        res = self._preparar_linea(self._canal(), dibujo="c1", direction="either")
        # Velas atrasadas: el aviso quedó mirando desde antes de la salida vieja,
        # y la vieja y la nueva llegan juntas.
        with main.db_abierta() as conn:
            ae._marcar_visto(conn, res["id"], "MSFT", r[-20].isoformat())
            conn.commit()
        self._noche(self.ayer)
        self._cron()
        self.assertEqual([e["message"] for e in self._eventos()],
                         ["MSFT subió hasta el borde de arriba de tu canal, en US$ 105,00"])

    def test_los_precios_de_tu_linea_con_los_decimales_que_hacen_falta(self):
        self.assertEqual(ae._fmt_linea(45.5, "ARS"), "$45,50")       # no «$46» al lado de un borde en «$45»
        self.assertEqual(ae._fmt_linea(7350, "ARS"), "$7.350")
        self.assertEqual(ae._fmt_linea(187.6, "USD"), "US$ 187,60")
        self.assertEqual(ae._fmt_linea(0.00456, "USD"), "US$ 0,00456")   # una cripto de centavos, no «US$ 0,00»
        r = ae.resumen_de_dibujo([{"date": "2026-10-01", "close": 0.0000098}, {"date": "2026-10-02", "close": 0.0000099}],
                                 {"id": "h", "tipo": "horizontal", "precio": 0.00000975})
        self.assertEqual((r["ultimo"], r["hoy"]), (0.0000099, [0.00000975]))

    def test_reactivar_un_aviso_pausado_no_deja_dos_para_el_mismo_canal(self):
        self.yahoo.precios["MSFT"] = lambda d: 100.0
        self._noche(self.anteayer)
        self._dibujar(self._canal())
        a = self._crear_linea(dibujo="c1", direction="either")
        self.assertIn("salga de este canal", self._crear_linea(dibujo="c1", direction="either", esperado=409)["detail"])
        self.assertEqual(self.client.patch(f"/api/alerts/{a['id']}", json={"active": False}, headers=self.h).status_code, 200)
        b = self._crear_linea(dibujo="c1", direction="above")     # pausado el primero, se puede armar otro
        r = self.client.patch(f"/api/alerts/{a['id']}", json={"active": True}, headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(self._alerta(a["id"])["active"], 0)
        self.assertEqual(self._alerta(b["id"])["active"], 1)

    def test_alertas_encuentra_tus_lineas_aunque_la_ficha_se_haya_abierto_como_ba(self):
        self.yahoo.precios["MSFT"] = lambda d: 100.0
        self._noche(self.anteayer)
        self._dibujar(self._canal(), asset="MSFT.BA")              # la ficha abierta desde el buscador
        lineas = self.client.get("/api/tecnico/MSFT/lineas?moneda=usd", headers=self.h).json()["lineas"]
        self.assertEqual([(x["id"], x["asset"]) for x in lineas], [("c1", "MSFT.BA")])
        # Y el alta, con ese activo, la encuentra.
        body = {"kind": "tecnica", "symbol": "MSFT.BA", "senal": "linea", "dibujo": "c1", "currency": "USD",
                "direction": "either", "channel": "both", "repeat": "once"}
        r = self.client.post("/api/alerts", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(ae.referencia_de_linea(self._alerta(r.json()["id"])["dibujo"])["asset"], "MSFT.BA")

    def test_el_alta_de_un_canal_y_cambiarle_el_borde_y_cuando_cuenta(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        self._noche(self.anteayer)
        self._dibujar(self._canal(), self._horizontal(130))
        res = self._crear_linea(dibujo="c1", direction="above", modo="cierre")
        g = self._alerta(res["id"])
        self.assertEqual(g["direction"], "above")
        self.assertEqual(ae.referencia_de_linea(g["dibujo"]),
                         {"asset": "MSFT", "moneda": "usd", "id": "c1", "tipo": "canal", "modo": "cierre"})
        r = self.client.patch(f"/api/alerts/{res['id']}", json={"direction": "either", "modo": "toque"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        g = self._alerta(res["id"])
        self.assertEqual((g["direction"], ae.referencia_de_linea(g["dibujo"])["modo"]), ("either", "toque"))
        # Una línea horizontal no tiene borde ni «cuándo cuenta»: avisa la toque de donde venga.
        h = self._crear_linea(dibujo="h1", direction="above")
        self.assertEqual(self._alerta(h["id"])["direction"], "either")
        r = self.client.patch(f"/api/alerts/{h['id']}", json={"modo": "cierre"}, headers=self.h)
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/alerts/{h['id']}", json={"direction": "above"}, headers=self.h)
        self.assertEqual(r.status_code, 400)

    def test_mis_alertas_sabe_donde_esta_hoy_cada_linea_y_cual_borraste(self):
        self.yahoo.precios["MSFT"] = lambda d: 100.0
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(self.anteayer)
        self._dibujar(self._canal(), self._horizontal(130))
        c = self._crear_linea(dibujo="c1", direction="either")
        h = self._crear_linea(dibujo="h1")
        r = self.client.get("/api/alerts/lineas", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        lineas = r.json()["lineas"]
        self.assertEqual(lineas[str(c["id"])]["hoy"], [95.0, 105.0])
        self.assertEqual(lineas[str(c["id"])]["ultimo"], 100.0)
        self.assertEqual(len(lineas[str(c["id"])]["lineas"]), 2, "los dos bordes del canal")
        self.assertEqual(lineas[str(h["id"])]["hoy"], [130])
        self.assertEqual(len(lineas[str(h["id"])]["serie"]), len(lineas[str(h["id"])]["lineas"][0]))
        # Borraste el canal (la ficha guarda la lista sin él).
        self._dibujar(self._horizontal(130))
        lineas = self.client.get("/api/alerts/lineas", headers=self.h).json()["lineas"]
        self.assertEqual(lineas[str(c["id"])], {"borrada": True})
        # Y el formulario de Alertas ofrece tus líneas del activo (no un Fibonacci).
        self._dibujar(self._canal(), self._horizontal(130),
                      {"id": "f1", "tipo": "fibonacci", "a": {"d": self.anteayer.isoformat(), "mas": 0, "precio": 90},
                       "b": {"d": self.anteayer.isoformat(), "mas": 3, "precio": 110}})
        r = self.client.get("/api/tecnico/MSFT/lineas?moneda=usd", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([(x["id"], x["tipo"], x["hoy"]) for x in r.json()["lineas"]],
                         [("c1", "canal", [95.0, 105.0]), ("h1", "horizontal", [130])])

    # — auditoría chica de la integración (30/10), sobre lo que trajo la barra
    # lateral (ae7b8636) y ninguna auditoría había revisado —

    def test_el_dia_que_la_pedis_no_avisa_por_lo_que_el_precio_hizo_antes(self):
        """Dibujás la línea donde está el precio (100) y pedís el aviso a la
        tarde. Ese día el precio no se movió (de 99 a 101, cierre 100). Antes
        avisaba «bajó hasta tu línea» a la mañana siguiente: la vela del día
        contaba entera, también las horas de antes de pedirlo. El aviso de
        precio ya nacía desarmado en ese caso (`armed = 0 if met`)."""
        self.yahoo.precios["MSFT"] = lambda d: 100.0
        res = self._preparar_linea(self._horizontal(100))
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [], "el día que lo pediste sólo cuenta si el cierre la cruzó")
        self.assertEqual(self._alerta(res["id"])["active"], 1)

    def test_un_dia_entero_despues_de_pedirla_cuenta_el_minimo_y_el_maximo(self):
        """Lo mismo, pero pedida un día antes: la vela de ayer es entera
        posterior al pedido y la tocó. Sin venir de un lado (cerró en la línea
        el día anterior), no se inventa «subió» ni «bajó»."""
        self.yahoo.precios["MSFT"] = lambda d: 100.0
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(self.anteayer)
        self._dibujar(self._horizontal(100))
        body = {"kind": "tecnica", "symbol": "MSFT", "senal": "linea", "dibujo": "h1",
                "currency": "USD", "channel": "both", "repeat": "once"}
        with self._el_dia(self.anteayer):
            r = self.client.post("/api/alerts", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._noche(self.ayer)
        self._cron()
        self.assertEqual([e["message"] for e in self._eventos()],
                         ["MSFT tocó tu línea horizontal, en US$ 100,00"])

    def test_el_dia_que_la_pedis_cuenta_si_el_cierre_la_cruzo(self):
        # El caso de siempre (de 100 a 110 con la línea en 109,50, pedida ayer):
        # el cierre quedó del otro lado, eso es posterior a pedirlo.
        self.yahoo.precios["MSFT"] = self._salta_ayer
        self._preparar_linea(self._horizontal(109.5))
        self._noche(self.ayer)
        self._cron()
        self.assertEqual([e["message"] for e in self._eventos()],
                         ["MSFT subió hasta tu línea horizontal, en US$ 109,50"])

    def _asesor_de_mi_cuenta(self, permiso="read_write"):
        with main.db_abierta() as conn:
            asesor = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Laura', 'x', 1, 1, 'advisor')", (f"asesora-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, status, permission) "
                         "VALUES (?, ?, 'active', ?)", (asesor, self.uid, permiso))
            conn.commit()
        return asesor, {"Authorization": f"Bearer {main.create_token(asesor)}",
                        "X-Rendi-Client-Id": str(self.uid)}

    def test_la_asesora_con_permiso_pide_el_aviso_de_su_linea_en_la_ficha_del_cliente(self):
        """Los dibujos son de quien los hace (la asesora); la alerta vive en la
        cuenta del cliente. Antes la alerta buscaba la línea entre los dibujos
        del cliente: 404 «Probá de nuevo en un momento», siempre."""
        self.yahoo.precios["MSFT"] = self._salta_ayer
        asesor, h = self._asesor_de_mi_cuenta()
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(self.anteayer)
        self._dibujar(self._horizontal(109.5), headers=h)
        body = {"kind": "tecnica", "symbol": "MSFT", "senal": "linea", "dibujo": "h1",
                "currency": "USD", "channel": "both", "repeat": "once"}
        with self._el_dia(self.ayer):
            r = self.client.post("/api/alerts", json=body, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self._noche(self.ayer)
        self._cron()
        self.assertEqual([e["message"] for e in self._eventos()],
                         ["MSFT subió hasta tu línea horizontal, en US$ 109,50"])

    def test_si_la_asesora_deja_de_poder_escribir_el_aviso_de_su_linea_se_apaga(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        asesor, h = self._asesor_de_mi_cuenta()
        self.client.post("/api/watchlist", json={"symbol": "MSFT"}, headers=self.h)
        self._noche(self.anteayer)
        self._dibujar(self._horizontal(109.5), headers=h)
        body = {"kind": "tecnica", "symbol": "MSFT", "senal": "linea", "dibujo": "h1",
                "currency": "USD", "channel": "both", "repeat": "once"}
        with self._el_dia(self.ayer):
            aid = self.client.post("/api/alerts", json=body, headers=h).json()["id"]
        with main.db_abierta() as conn:
            conn.execute("UPDATE advisor_clients SET permission='read' WHERE advisor_uid=?", (asesor,))
            conn.commit()
        self._noche(self.ayer)
        self._cron()
        self.assertEqual(self._eventos(), [], "la línea de alguien que ya no escribe en tu cuenta no te avisa")
        self.assertEqual(self._alerta(aid)["active"], 0)

    def test_una_linea_de_tendencia_sin_inclinacion_no_se_acepta(self):
        """Las dos puntas en el mismo día: no se puede seguir. Antes la alerta
        quedaba activa y no avisaba nunca, sin decirlo."""
        self._noche(self.anteayer)
        d = self.anteayer.isoformat()
        self._dibujar({"id": "t1", "tipo": "tendencia", "a": {"d": d, "mas": 0, "precio": 90},
                       "b": {"d": d, "mas": 0, "precio": 110}})
        r = self._crear_linea(dibujo="t1", esperado=400)
        self.assertIn("mismo día", r["detail"])

    def test_el_aviso_de_linea_pide_un_activo_valido_como_las_otras_tecnicas(self):
        # Un dibujo guardado de antes de que los dibujos pidieran activo válido.
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO dibujos_grafico (user_id, asset, moneda, datos) VALUES (?, 'QXZZQ', 'usd', ?)",
                         (self.uid, '[{"id": "h1", "tipo": "horizontal", "precio": 10}]'))
            conn.commit()
        r = self._crear_linea(symbol="QXZZQ", esperado=400)
        self.assertNotIn("Listo", r.get("detail", ""))

    def test_reactivar_un_aviso_cuya_linea_borraste_lo_dice(self):
        self.yahoo.precios["MSFT"] = self._salta_ayer
        res = self._preparar_linea(self._horizontal(109.5))
        self.client.patch(f"/api/alerts/{res['id']}", json={"active": False}, headers=self.h)
        self._dibujar()                                    # borraste la línea
        r = self.client.patch(f"/api/alerts/{res['id']}", json={"active": True}, headers=self.h)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("ya no está", r.json()["detail"])
        self.assertEqual(self._alerta(res["id"])["active"], 0)

    def test_un_toque_viejo_no_tapa_el_nuevo_de_tu_linea(self):
        """Si llegan muchas velas juntas (Yahoo atrasado), el primer toque puede
        ser viejo y el motor lo descarta; el de anteayer, que sí es noticia, se
        perdía. El motor vuelve a buscar DESDE el viejo (`_evaluar_una_tecnica`),
        el mismo mecanismo que el canal (al juntar la barra, 30/10: lo habían
        arreglado las dos ramas, cada una a su manera; quedó uno)."""
        velas = [{"date": f"2026-10-{d:02d}", "close": c, "high": c + 1, "low": c - 1}
                 for d, c in [(1, 90.0), (2, 100.0), (3, 90.0), (15, 90.0), (16, 100.0)]]
        linea = {"tipo": "horizontal", "precio": 100}
        self.assertEqual(tecnico.toque_de_linea(velas, linea, "2026-10-01")["fecha"], "2026-10-02")
        self.assertEqual(tecnico.toque_de_linea(velas, linea, "2026-10-02")["fecha"], "2026-10-16")

    def test_el_dia_que_pedis_el_aviso_del_canal_cuenta_por_el_cierre(self):
        """Lo mismo que la línea (propagado al juntar, 30/10): el día del pedido,
        en modo «toque», un máximo que llegó al borde ANTES de pedirlo no avisa;
        un cierre afuera sí."""
        canal = {"tipo": "canal", "a": {"d": "2026-10-01", "mas": 0, "precio": 100},
                 "b": {"d": "2026-10-02", "mas": 0, "precio": 100}, "ancho": 10}
        quieto = [{"date": "2026-10-01", "close": 105.0, "high": 106, "low": 104},
                  {"date": "2026-10-02", "close": 105.0, "high": 110.5, "low": 104}]
        self.assertIsNotNone(tecnico.salida_de_canal(quieto, canal, "2026-10-01"))
        self.assertIsNone(tecnico.salida_de_canal(quieto, canal, "2026-10-01", pedida_el="2026-10-02"))
        afuera = [quieto[0], {"date": "2026-10-02", "close": 111.0, "high": 112, "low": 104}]
        self.assertIsNotNone(tecnico.salida_de_canal(afuera, canal, "2026-10-01", pedida_el="2026-10-02"))


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
        fondo = 74                                  # el último día de la caída
        baja = tecnico.senal_desde(v[:fondo], "rsi_bajo_30")
        sube = tecnico.senal_desde(v, "rsi_sube_30")
        self.assertIsNotNone(baja)
        self.assertIsNotNone(sube)
        self.assertLess(baja["fecha"], sube["fecha"])
        self.assertIsNone(tecnico.senal_desde(v, "rsi_bajo_30"),
                          "con el rebote, lo último del 30 es para arriba: «bajó de 30» ya no vale")
        i = [x["date"] for x in v].index(baja["fecha"])
        self.assertTrue(r[i - 1] >= 30 > r[i], "bajó de 30 ese día, con el RSI de la ficha")
        self.assertIsNone(tecnico.senal_desde(v[:fondo], "rsi_bajo_30", desde=baja["fecha"]),
                          "desde ese día no volvió a bajar: el mismo cruce no se cuenta dos veces")
        # Pasó 70 subiendo, al principio, y volvió a bajar de 70 al empezar la caída.
        sobre = tecnico.senal_desde(v[:60], "rsi_sobre_70")
        vuelve = tecnico.senal_desde(v[:fondo], "rsi_baja_70")
        self.assertIsNotNone(sobre)
        self.assertLess(sobre["fecha"], vuelve["fecha"])
        self.assertLess(vuelve["fecha"], baja["fecha"])
        # La ficha anuncia la misma vuelta con `cruce_rsi` (salio_de_arriba).
        j = [x["date"] for x in v].index(vuelve["fecha"])
        self.assertEqual(tecnico.cruce_rsi(r[:j + 1]), {"tipo": "salio_de_arriba", "hace": 0})

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

    def test_maximo_entre_avisos_es_un_mes_de_calendario_tambien_en_cripto(self):
        """Una cripto cotiza los 7 días: «un mes sin máximos» son 30 días
        corridos, no 20 velas (auditoría 22/10)."""
        hasta = date(2026, 10, 21)
        cierres = [100.0 - 0.01 * i for i in range(400)]
        cierres[380] = 120.0                    # máximo del año
        for k in range(381, 400):
            cierres[k] = 110.0
        # Otro máximo 25 días después (25 velas: con "20 velas" avisaba) y otro
        # 35 días después de ése.
        cierres += [110.0] * 5 + [121.0] + [110.0] * 34 + [122.0]
        v = [{"date": (hasta - timedelta(days=len(cierres) - 1 - i)).isoformat(), "close": c}
             for i, c in enumerate(cierres)]
        i25 = 405
        self.assertIsNone(tecnico.senal_desde(v[:i25 + 1], "maximo_12m", desde=v[i25 - 1]["date"]),
                          "a los 25 días corridos todavía no pasó un mes")
        self.assertEqual(tecnico.senal_desde(v, "maximo_12m", desde=v[i25]["date"])["fecha"], v[-1]["date"],
                         "después de 35 días sin máximos, sí")

    def test_maximo_sin_un_anio_de_velas_no_avisa(self):
        v = self._velas([100.0] * 100 + [120.0])
        self.assertIsNone(tecnico.senal_desde(v, "maximo_12m"))

    def test_cruce_de_media_con_sentido(self):
        cierres = [100.0] * 250 + [90.0] * 20 + [120.0]
        v = self._velas(cierres)
        self.assertEqual(tecnico.senal_desde(v, "media200", sentido="arriba")["fecha"], v[-1]["date"])
        self.assertIsNone(tecnico.senal_desde(v, "media200", sentido="abajo"),
                          "la bajada a 90 ya se dio vuelta: hoy está arriba")
        ab = tecnico.senal_desde(v[:-1], "media200", sentido="abajo")
        self.assertEqual(ab["fecha"], v[250]["date"], "la bajada a 90 fue el cruce para abajo")
        self.assertIsNone(tecnico.senal_desde(v, "media200", desde=v[-1]["date"]))

    def test_vale_el_ultimo_cruce_del_periodo(self):
        """Cruza para arriba y al día siguiente vuelve abajo: lo último es «abajo»
        (lo que muestra la tarjeta); una alerta «para arriba» no avisa."""
        v = self._velas([100.0] * 250 + [90.0] * 20 + [120.0, 90.0])
        desde = v[-3]["date"]
        self.assertIsNone(tecnico.senal_desde(v, "media200", desde, "arriba"))
        self.assertEqual(tecnico.senal_desde(v, "media200", desde, "abajo")["fecha"], v[-1]["date"])
        self.assertEqual(tecnico.senal_desde(v, "media200", desde)["sentido"], "abajo")


class TestDetalleNoPromete(unittest.TestCase):
    """El texto del mail describe lo que pasó; no anticipa. Medido (backtest 28/10
    y «Tus señales», 70 activos, 2 años): después de «pasa 70» el precio siguió
    subiendo en promedio, así que «suele frenar» era falso. La única con algo de
    ventaja es la caída debajo de 30, y su frase es la de senales_semana."""

    def test_detalle_tecnico_no_promete(self):
        from senales_semana import POSIBILIDAD_REBOTE
        hoy = hoy_art_date().isoformat()
        casos = [("rsi_bajo_30", "abajo", 30.0), ("rsi_sobre_70", "arriba", 70.0),
                 ("rsi_sube_30", "arriba", 30.0), ("rsi_baja_70", "abajo", 70.0),
                 ("media200", "arriba", 95.0), ("media200", "abajo", 95.0),
                 ("media50", "arriba", 95.0), ("media50", "abajo", 95.0)]
        for senal, sentido, ref in casos:
            ev = {"fecha": hoy, "sentido": sentido, "cierre": 100.0, "referencia": ref, "rsi": 25.0}
            txt = ae._detalle_tecnico({"currency": "USD", "senal": senal}, "AAPL", ev)
            with self.subTest(senal=senal, sentido=sentido):
                self.assertNotRegex(txt.lower(), r"suele|rebota|frena|se viene|va a (subir|bajar)", txt)
        bajo = ae._detalle_tecnico({"currency": "USD", "senal": "rsi_bajo_30"}, "AAPL",
                                   {"fecha": hoy, "sentido": "abajo", "cierre": 100.0, "referencia": 30.0, "rsi": 25.0})
        self.assertIn(POSIBILIDAD_REBOTE, bajo, "la caída lleva la MISMA frase que «Tus señales»")

if __name__ == "__main__":
    unittest.main()
