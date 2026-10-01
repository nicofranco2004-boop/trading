"""Mail "¿qué te está pareciendo Rendi?" a los que están en la prueba gratis.

Lo que estos tests protegen, en orden:

  1. Que la lista sea la de los que están probando HOY, con la misma regla que
     la barra de la app (`prueba_viva`): ni el que no arrancó, ni al que se le
     terminó, ni el que pagó a mitad de la prueba.
  2. Que al que le llega salga de la lista principal, y que volver a mandarle
     pase SOLO por el botón de "ya lo recibieron".
  3. Que un envío fallido no deje a nadie marcado, y que un doble click no le
     mande dos veces a nadie.
  4. Que el mail que muestra el panel sea el mismo que se manda.

Todo por HTTP, y las pruebas se arrancan con `trial.start` — el mismo alta que
usa la app — no escribiendo fechas a mano.

Corre con: cd backend && python3 -m pytest tests/test_feedback_prueba.py
"""
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
from billing import trial as tr
from billing import emails

URL = "/api/admin/email/feedback-prueba"


class FeedbackDeLaPrueba(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("credit_ledger", "subscriptions", "trial_consumed", "trial_email_log",
                  "operations", "positions", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, 1)", (f"admin-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.admin = cur.lastrowid
        self.conn.commit()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        for var in ("TRIALS_ENABLED", "TRIALS_MONTHLY_CAP", "PAYWALL_NUEVOS"):
            os.environ.pop(var, None)
        self.addCleanup(self.conn.close)

    # ── el mundo ────────────────────────────────────────────────────────────

    def _persona(self, *, admin=0, name=None):
        cur = self.conn.execute(
            "INSERT INTO users (email, name, password_hash, approved, email_verified, "
            "                   requires_plan, is_admin) VALUES (?,?,'x',1,1,1,?)",
            (f"u-{uuid.uuid4().hex[:10]}@rendi.test", name, admin))
        self.conn.commit()
        return cur.lastrowid

    def _con_prueba(self, uid, *, arrancó_hace=None):
        """Arranca la prueba con el alta real y después corre el reloj hacia
        atrás moviendo las TRES fechas juntas (si se mueve una sola, la persona
        queda 'terminada' con la prueba viva).

        Por defecto la deja con los días justos para entrar en la lista
        (FEEDBACK_PRUEBA_MIN_DIAS); con 0 queda "recién empezada"."""
        self.assertTrue(tr.start(self.conn, uid).get("ok"))
        if arrancó_hace is None:
            arrancó_hace = main.FEEDBACK_PRUEBA_MIN_DIAS
        if arrancó_hace:
            self._atrasar(uid, arrancó_hace)
        return uid

    def _atrasar(self, uid, dias):
        atras = timedelta(days=dias)
        r = self.conn.execute(
            "SELECT trial_started_at, credit_active_until, trial_ends_at "
            "FROM users WHERE id=?", (uid,)).fetchone()
        f = lambda s: (datetime.fromisoformat(s) - atras).isoformat()
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, trial_ends_at=? "
            "WHERE id=?",
            (f(r["trial_started_at"]), f(r["credit_active_until"]),
             f(r["trial_ends_at"]), uid))
        # El mail automático de arranque sale el día que arranca: si se atrasa
        # la prueba y no el mail, parece que le llegó "hace un rato".
        for m in self.conn.execute(
                "SELECT kind, sent_at FROM trial_email_log WHERE user_id=?", (uid,)).fetchall():
            self.conn.execute(
                "UPDATE trial_email_log SET sent_at=? WHERE user_id=? AND kind=?",
                (f(m["sent_at"]), uid, m["kind"]))
        self.conn.commit()

    def _envejecer_marca(self, uid, horas):
        """Corre hacia atrás la fecha en que le llegó ESTE mail."""
        m = self._marca(uid)
        self.conn.execute(
            "UPDATE users SET trial_feedback_email_sent_at=? WHERE id=?",
            ((datetime.fromisoformat(m) - timedelta(hours=horas)).isoformat(), uid))
        self.conn.commit()

    def _pagó(self, uid):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, "
            "                           period, amount_ars, created_at) "
            "VALUES (?, 'authorized', ?, 'monthly', 10000, ?)", (uid, f"ref-{uid}", ts))
        self.conn.execute(
            "INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, created_at) "
            "VALUES (?, 'payment', 9.0, 30, ?)", (uid, ts))
        self.conn.commit()

    def _vista(self):
        r = self.client.post(URL, json={"confirm": False}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _vistos(self, grupo="nuevos", vista=None):
        """Lo que manda el panel: cada fila del grupo con la fecha que se ve."""
        filas = (vista or self._vista())[grupo]
        return [{"id": f["id"], "sent_at": f["sent_at"]} for f in filas]

    def _mandar(self, grupo="nuevos", vistos=None, ok=True, side_effect=None,
                status=200):
        """Como el panel: arma `vistos` de una vista previa recién pedida,
        salvo que el test pase la suya (una vista VIEJA, para las carreras)."""
        if vistos is None:
            vistos = self._vistos(grupo)
        body = {"confirm": True, "grupo": grupo, "vistos": vistos}
        kw = {"side_effect": side_effect} if side_effect else {"return_value": ok}
        with patch("billing.emails.send_trial_feedback", **kw) as spy, \
             patch("billing.emails.PAUSA_ENTRE_ENVIOS", 0):
            r = self.client.post(URL, json=body, headers=self.headers)
        self.assertEqual(r.status_code, status, r.text)
        return r.json(), spy

    @staticmethod
    def _todas(v):
        return v["nuevos"] + v["ya_recibieron"] + v["recien_empezados"]

    def _marca(self, uid):
        return self.conn.execute(
            "SELECT trial_feedback_email_sent_at m FROM users WHERE id=?", (uid,)
        ).fetchone()["m"]

    @staticmethod
    def _ids(filas):
        return {f["id"] for f in filas}

    # ── 1. a quién le toca ──────────────────────────────────────────────────

    def test_solo_los_que_estan_probando_hoy(self):
        en_pro = self._con_prueba(self._persona())
        en_plus = self._con_prueba(self._persona(), arrancó_hace=tr.TRIAL_PRO_DAYS + 2)
        sin_arrancar = self._persona()
        terminada = self._con_prueba(self._persona(), arrancó_hace=tr.TRIAL_TOTAL_DAYS + 3)
        pagó = self._con_prueba(self._persona(), arrancó_hace=2)
        self._pagó(pagó)
        # Un admin no puede arrancar la prueba; el caso posible es una cuenta
        # que la arrancó y DESPUÉS pasó a admin.
        admin_probando = self._con_prueba(self._persona())
        self.conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (admin_probando,))
        self.conn.commit()

        v = self._vista()
        self.assertEqual(self._ids(v["nuevos"]), {en_pro, en_plus})
        self.assertEqual(v["ya_recibieron"], [])
        self.assertEqual(v["en_prueba"], 2)
        for quien, por_que in ((sin_arrancar, "no arrancó la prueba"),
                               (terminada, "se le terminó la prueba"),
                               (pagó, "pagó a mitad de la prueba"),
                               (admin_probando, "es admin")):
            self.assertNotIn(quien, self._ids(v["nuevos"]), por_que)

        etapas = {f["id"]: f["stage"] for f in v["nuevos"]}
        self.assertEqual(etapas[en_pro], "pro")
        self.assertEqual(etapas[en_plus], "plus")

    def test_cuenta_lo_mismo_que_el_panel_de_pruebas(self):
        # Sin admins de por medio, "En la prueba" tiene que ser el "En curso"
        # del panel de Pruebas: es la misma pregunta.
        for d in (0, 3, tr.TRIAL_PRO_DAYS + 1):
            self._con_prueba(self._persona(), arrancó_hace=d)
        self._con_prueba(self._persona(), arrancó_hace=tr.TRIAL_TOTAL_DAYS + 1)
        en_curso = tr.progreso(self.conn)["resumen"]["en_curso"]
        self.assertEqual(self._vista()["en_prueba"], en_curso)
        self.assertEqual(en_curso, 3)

    # ── 2. sale de la lista; volver a mandar es otro botón ──────────────────

    def test_al_que_le_llega_sale_de_la_lista_principal(self):
        a = self._con_prueba(self._persona())
        b = self._con_prueba(self._persona())
        res, spy = self._mandar("nuevos")
        self.assertEqual(res["sent_count"], 2)
        self.assertEqual(spy.call_count, 2)

        v = self._vista()
        self.assertEqual(v["nuevos"], [])
        self.assertEqual(self._ids(v["ya_recibieron"]), {a, b})
        self.assertTrue(all(f["sent_at"] for f in v["ya_recibieron"]))

        # Apretar otra vez el botón principal no le manda a nadie.
        res, spy = self._mandar("nuevos")
        self.assertEqual(res["sent_count"], 0)
        spy.assert_not_called()

    def test_volver_a_mandar_solo_a_los_que_ya_lo_recibieron(self):
        viejo = self._con_prueba(self._persona())
        self._mandar("nuevos")
        self._envejecer_marca(viejo, 48)
        marca_1 = self._marca(viejo)
        recien = self._con_prueba(self._persona())   # arrancó después del primer envío

        res, spy = self._mandar("ya_recibieron")
        self.assertEqual(res["sent_count"], 1)
        self.assertTrue(spy.call_args.kwargs["reenvio"], "el reenvío salió con el texto del primero")
        self.assertEqual([c.kwargs["to"] for c in spy.call_args_list],
                         [self.conn.execute("SELECT email FROM users WHERE id=?",
                                            (viejo,)).fetchone()["email"]])
        self.assertGreater(self._marca(viejo), marca_1, "la fecha de envío no se actualizó")
        self.assertIsNone(self._marca(recien), "el botón de reenvío alcanzó a uno nuevo")

    def test_al_que_se_le_termina_la_prueba_deja_de_aparecer(self):
        uid = self._con_prueba(self._persona())
        self._mandar("nuevos")
        self.assertEqual(self._ids(self._vista()["ya_recibieron"]), {uid})

        self._atrasar(uid, tr.TRIAL_TOTAL_DAYS + 1)
        v = self._vista()
        self.assertEqual(v["nuevos"], [])
        self.assertEqual(v["ya_recibieron"], [])
        res, spy = self._mandar("ya_recibieron")
        self.assertEqual(res["sent_count"], 0)
        spy.assert_not_called()

    # ── 3. fallas y carreras ────────────────────────────────────────────────

    def test_envio_fallido_no_marca_a_nadie(self):
        uid = self._con_prueba(self._persona())
        res, _ = self._mandar("nuevos", ok=False)
        self.assertEqual(res["failed_count"], 1)
        self.assertIsNone(self._marca(uid))
        self.assertEqual(self._ids(self._vista()["nuevos"]), {uid})

    def test_reenvio_fallido_deja_la_fecha_que_tenia(self):
        uid = self._con_prueba(self._persona())
        self._mandar("nuevos")
        self._envejecer_marca(uid, 48)
        antes = self._marca(uid)
        res, _ = self._mandar("ya_recibieron", ok=False)
        self.assertEqual(res["failed_count"], 1)
        self.assertEqual(self._marca(uid), antes)

    def test_solo_se_manda_a_los_que_se_vieron_en_la_vista_previa(self):
        visto = self._con_prueba(self._persona())
        vistos = self._vistos("nuevos")
        tarde = self._con_prueba(self._persona())   # arrancó después de mirar la lista

        res, spy = self._mandar("nuevos", vistos=vistos)
        self.assertEqual(res["sent_count"], 1)
        self.assertIsNotNone(self._marca(visto))
        self.assertIsNone(self._marca(tarde))

    def test_dos_pestañas_no_le_mandan_dos_veces_a_nadie(self):
        a = self._con_prueba(self._persona())
        b = self._con_prueba(self._persona())

        # Mientras esta pestaña le manda a A, otra pestaña le gana a B.
        def otra_pestaña_le_gana_a_b(*, to, user_name="", reenvio=False):
            otra = main.get_db()
            otra.execute("UPDATE users SET trial_feedback_email_sent_at=? WHERE id=?",
                         (datetime.utcnow().isoformat(), b))
            otra.commit()
            otra.close()
            return True

        # A arrancó primero, así que se le termina antes y va primero en la lista.
        res, spy = self._mandar("nuevos", side_effect=otra_pestaña_le_gana_a_b)
        self.assertEqual(spy.call_count, 1, "a B le llegó dos veces")
        self.assertEqual(res["sent_count"], 1)
        self.assertEqual(res["skipped_count"], 1)
        self.assertEqual({x["id"] for x in res["skipped"]}, {b})

    def test_grupo_invalido(self):
        r = self.client.post(URL, json={"grupo": "todos"}, headers=self.headers)
        self.assertEqual(r.status_code, 422)

    def test_solo_admin(self):
        uid = self._persona()
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        r = self.client.post(URL, json={"confirm": False}, headers=h)
        self.assertIn(r.status_code, (401, 403))

    # ── 5. el nombre con que saluda ─────────────────────────────────────────

    def test_saluda_por_el_nombre_de_pila_y_sin_nombre_si_no_sirve(self):
        casos = {"Lucía Gómez": "Lucía", "lucia": "Lucia", "MARTÍN RUIZ": "Martín",
                 "nico_2004": "", "nico@gmail.com": "", "Dr. Pérez": "", "": "",
                 "McKenzie": "McKenzie"}
        ids = {}
        for nombre in casos:
            ids[self._con_prueba(self._persona(name=nombre or None))] = nombre
        saludos = {f["id"]: f["saludo"] for f in self._vista()["nuevos"]}
        for uid, nombre in ids.items():
            self.assertEqual(saludos[uid], casos[nombre], f"nombre cargado: {nombre!r}")

        # Y el mail que sale dice exactamente eso.
        for nombre, esperado in (("lucia gomez", "Hola Lucia,"), ("nico_2004", "Hola,")):
            _a, html, texto = emails.feedback_prueba_contenido(nombre)
            self.assertTrue(texto.startswith(esperado + " "), texto[:30])
            self.assertIn(esperado, html)
            self.assertNotIn("nico_2004", html + texto)

    # ── 6. la prueba que se manda el admin ──────────────────────────────────

    def test_la_prueba_le_llega_solo_al_admin_y_no_marca_a_nadie(self):
        alguien = self._con_prueba(self._persona())
        self.conn.execute("UPDATE users SET name='Nicolás' WHERE id=?", (self.admin,))
        self.conn.commit()
        with patch("billing.emails.send_trial_feedback", return_value=True) as spy:
            r = self.client.post(URL, json={"prueba_a_mi": True, "confirm": True},
                                 headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        mail_admin = self.conn.execute("SELECT email FROM users WHERE id=?",
                                       (self.admin,)).fetchone()["email"]
        self.assertEqual(r.json(), {"prueba": True, "to": mail_admin, "sent": True})
        spy.assert_called_once_with(to=mail_admin, user_name="Nicolás", reenvio=False)
        self.assertIsNone(self._marca(alguien))
        self.assertIsNone(self._marca(self.admin))

    # ── 7. no pisarse con los mails automáticos de la prueba ────────────────

    def test_avisa_si_hace_poco_le_llego_otro_mail_de_la_prueba(self):
        reciente = self._con_prueba(self._persona(), arrancó_hace=0)
        viejo = self._con_prueba(self._persona(), arrancó_hace=5)
        nada = self._con_prueba(self._persona(), arrancó_hace=0)
        self.conn.execute("DELETE FROM trial_email_log")
        hace = lambda h: (datetime.utcnow() - timedelta(hours=h)).isoformat()
        self.conn.execute("INSERT INTO trial_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
                          (reciente, tr.MAIL_STARTED, hace(3)))
        self.conn.execute("INSERT INTO trial_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
                          (viejo, tr.MAIL_STARTED, hace(5 * 24)))
        self.conn.commit()
        horas = {f["id"]: f["otro_mail_hace_horas"] for f in self._todas(self._vista())}
        self.assertAlmostEqual(horas[reciente], 3, delta=0.2)
        self.assertGreater(horas[viejo], 24)
        self.assertIsNone(horas[nada])

    # ── 4. el mail que se ve es el que se manda ─────────────────────────────

    def test_el_mail_del_panel_es_el_que_sale(self):
        """Atraviesa `_send` entero hasta el pedido HTTP a Resend (sólo se
        reemplaza la red). Reemplazar `_send` se salteaba justo lo que le agrega
        al mail —el pie de WhatsApp del texto plano— y el remitente real."""
        self._con_prueba(self._persona(name="lucía gómez"))
        v = self._vista()
        pedidos = []

        class _Resp:
            status_code = 200
            text = "{}"

        def _post(url, headers=None, json=None, timeout=None):
            pedidos.append(json)
            return _Resp()

        with patch.object(emails, "_running_under_pytest", return_value=False), \
             patch.object(emails, "_is_test_address", return_value=False), \
             patch.object(emails, "_is_configured", return_value=True), \
             patch.object(emails, "_api_key", return_value="re_test"), \
             patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0), \
             patch("httpx.post", side_effect=_post):
            r = self.client.post(URL, json={"confirm": True, "vistos": self._vistos(vista=v)},
                                 headers=self.headers)
        self.assertEqual(r.json()["sent_count"], 1, r.text)
        m = pedidos[0]
        self.assertEqual(m["subject"], v["mail"]["asunto"])
        # El texto del panel, con el nombre de pila acomodado, y DESPUÉS el pie.
        esperado = v["mail"]["texto"].replace("(nombre)", "Lucía")
        self.assertTrue(m["text"].startswith(esperado), m["text"][:80])
        self.assertIn("WhatsApp", m["text"][len(esperado):])
        self.assertIn("Hola Lucía,", m["html"])
        self.assertNotIn("WhatsApp", m["html"])
        self.assertIn("soporte@rendi.finance", m["from"])
        self.assertEqual(m["reply_to"], "soporte@rendi.finance")

    # ── 8. lo que encontró la auditoría ─────────────────────────────────────

    def test_volver_a_mandar_dos_veces_con_la_misma_lista_no_duplica(self):
        """El doble click de "volver a mandar": la persona SIGUE en el mismo
        grupo después del primer envío. Reproducido antes del arreglo: 2 + 2."""
        a = self._con_prueba(self._persona())
        b = self._con_prueba(self._persona())
        self._mandar("nuevos")
        for u in (a, b):
            self._envejecer_marca(u, 48)
        en_pantalla = self._vistos("ya_recibieron")        # lo que ve el admin

        primero, spy1 = self._mandar("ya_recibieron", vistos=en_pantalla)
        segundo, spy2 = self._mandar("ya_recibieron", vistos=en_pantalla)
        self.assertEqual(primero["sent_count"], 2)
        self.assertEqual(spy1.call_count, 2)
        self.assertEqual(segundo["sent_count"], 0, "el segundo click volvió a mandar")
        spy2.assert_not_called()

    def test_reenvio_en_dos_pestañas_a_la_vez_no_duplica(self):
        """Las dos pestañas arman su lista ANTES de que la otra marque: la espera
        de 24 h no las frena, lo único que las frena es la marca comparada
        contra lo que vio cada una."""
        a = self._con_prueba(self._persona())
        b = self._con_prueba(self._persona())
        self._mandar("nuevos")
        for u in (a, b):
            self._envejecer_marca(u, 48)
        en_pantalla = self._vistos("ya_recibieron")

        def otra_pestaña_reenvia_a_b(*, to, user_name="", reenvio=False):
            otra = main.get_db()
            otra.execute("UPDATE users SET trial_feedback_email_sent_at=? WHERE id=?",
                         (datetime.utcnow().isoformat(), b))
            otra.commit()
            otra.close()
            return True

        res, spy = self._mandar("ya_recibieron", vistos=en_pantalla,
                                side_effect=otra_pestaña_reenvia_a_b)
        self.assertEqual(spy.call_count, 1, "a B le llegó dos veces")
        self.assertEqual({x["id"] for x in res["skipped"]}, {b})

    def test_los_recien_empezados_se_ven_pero_no_se_les_manda(self):
        hoy = self._con_prueba(self._persona(), arrancó_hace=0)
        casi = self._con_prueba(self._persona(),
                                arrancó_hace=main.FEEDBACK_PRUEBA_MIN_DIAS - 1)
        listo = self._con_prueba(self._persona())
        v = self._vista()
        self.assertEqual(self._ids(v["recien_empezados"]), {hoy, casi})
        self.assertEqual(self._ids(v["nuevos"]), {listo})
        self.assertEqual(v["en_prueba"], 3)

        # Aunque el pedido los nombre, no se les manda.
        colados = [{"id": hoy, "sent_at": None}, {"id": casi, "sent_at": None}]
        res, spy = self._mandar("nuevos", vistos=colados)
        self.assertEqual(res["sent_count"], 0)
        self.assertEqual(res["discarded_count"], 2)
        spy.assert_not_called()

    def test_manda_de_a_tandas_y_exige_la_lista_vista(self):
        lote = main.ENVIO_MASIVO_LOTE
        muchos = [{"id": i, "sent_at": None} for i in range(1, lote + 2)]
        self._mandar("nuevos", vistos=muchos, status=422)
        r = self.client.post(URL, json={"confirm": True, "grupo": "nuevos"},
                             headers=self.headers)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self._vista()["lote"], lote)

    def test_entre_mail_y_mail_hay_pausa(self):
        """La pausa la pone `emails._send` (ver test_ritmo_de_envio.py): se mide
        en los pedidos que le llegan a Resend, con el mail de verdad."""
        from tests._resend_falso import Reloj, red_de_mentira, separaciones
        for _ in range(3):
            self._con_prueba(self._persona())
        with red_de_mentira(Reloj(), direcciones_de_prueba=True,
                            todo_sleep_en_el_reloj=True) as resend:
            r = self.client.post(URL, json={"confirm": True, "vistos": self._vistos()},
                                 headers=self.headers)
        self.assertEqual(r.json()["sent_count"], 3)
        self.assertEqual(len(resend.pedidos), 3)
        # EXACTAMENTE la pausa (Resend de mentira tarda 0,3 s, menos que ella):
        # menos es sin pausa, más es una pausa de más (p. ej. un sleep propio del
        # loop además del de `_send`, que alargaba cada tanda).
        self.assertEqual([round(x, 6) for x in separaciones(resend.horas())],
                         [emails.PAUSA_ENTRE_ENVIOS] * 2, resend.pedidos)

    def test_si_no_se_puede_devolver_la_marca_se_informa(self):
        uid = self._con_prueba(self._persona())
        vistos = self._vistos()
        real_get_db = main.get_db

        class _ConnQueNoDeja:
            """Deja marcar, pero no deja devolver la marca (base trabada)."""
            def __init__(self):
                self._c = real_get_db()
            def execute(self, sql, params=()):
                if "SET trial_feedback_email_sent_at" in sql and len(params) == 3 \
                        and params[0] is None and params[2] is not None \
                        and "IS NULL" not in sql and params[1] == uid:
                    raise sqlite3.OperationalError("database is locked")
                return self._c.execute(sql, params)
            def __getattr__(self, n):
                return getattr(self._c, n)

        with patch("main.get_db", side_effect=lambda: _ConnQueNoDeja()):
            res, _ = self._mandar("nuevos", vistos=vistos, ok=False)
        self.assertEqual(res["failed_count"], 1)
        self.assertEqual([t["id"] for t in res["marcas_trabadas"]], [uid])


    # ── 9. segunda auditoría ────────────────────────────────────────────────

    def test_otro_mail_hace_poco_espera_a_mañana_aunque_venga_en_la_lista(self):
        hoy_aviso = self._con_prueba(self._persona())
        tranquilo = self._con_prueba(self._persona())
        self.conn.execute("INSERT OR REPLACE INTO trial_email_log (user_id, kind, sent_at) "
                          "VALUES (?,?,?)", (hoy_aviso, tr.MAIL_PRO_ENDING,
                                             (datetime.utcnow() - timedelta(hours=2)).isoformat()))
        self.conn.commit()
        v = self._vista()
        espera = {f["id"]: f["espera"] for f in v["nuevos"]}
        self.assertIn("hace 2 h", espera[hoy_aviso])
        self.assertIsNone(espera[tranquilo])

        # Aunque el pedido lo nombre, no sale; y se cuenta para que el total cierre.
        res, spy = self._mandar("nuevos", vistos=self._vistos(vista=v))
        self.assertEqual(res["sent_count"], 1)
        self.assertEqual(res["discarded_count"], 1)
        self.assertEqual([c.kwargs["to"] for c in spy.call_args_list],
                         [self.conn.execute("SELECT email FROM users WHERE id=?",
                                            (tranquilo,)).fetchone()["email"]])
        self.assertIsNone(self._marca(hoy_aviso))

    def test_recien_recibido_no_se_ofrece_para_reenviar(self):
        uid = self._con_prueba(self._persona())
        self._mandar("nuevos")
        fila = self._vista()["ya_recibieron"][0]
        self.assertEqual(fila["id"], uid)
        self.assertIn("lo recibió hace", fila["espera"])
        self._envejecer_marca(uid, 30)
        self.assertIsNone(self._vista()["ya_recibieron"][0]["espera"])

    def test_el_reenvio_no_es_el_mismo_mail(self):
        asunto1, _h1, t1 = emails.feedback_prueba_contenido("Lucía")
        asunto2, _h2, t2 = emails.feedback_prueba_contenido("Lucía", reenvio=True)
        self.assertEqual(asunto1, asunto2)          # misma conversación en Gmail
        self.assertNotEqual(t1.split("\n")[0], t2.split("\n")[0])
        self.assertTrue(t2.startswith("Hola Lucía, ya llevás un tiempo"))
        # No afirma un mail anterior: si una marca quedó sin envío, sería mentira.
        self.assertNotIn("te escrib", t2.lower())
        self.assertNotIn("te había", t2.lower())
        v = self._vista()
        self.assertEqual(v["mail_reenvio"]["texto"],
                         emails.feedback_prueba_contenido(nombre_literal="(nombre)",
                                                          reenvio=True)[2])

    def test_los_dias_se_cuentan_desde_que_arranco(self):
        """Una prueba que no dura exactamente TRIAL_TOTAL_DAYS (vencimiento
        movido): contando "total − lo que le queda" daba días negativos y la
        persona quedaba para siempre en "recién empezados"."""
        uid = self._con_prueba(self._persona(), arrancó_hace=5)
        r = self.conn.execute("SELECT trial_ends_at FROM users WHERE id=?", (uid,)).fetchone()
        mas_tarde = (datetime.fromisoformat(r["trial_ends_at"]) + timedelta(days=12)).isoformat()
        self.conn.execute("UPDATE users SET trial_ends_at=?, credit_active_until=? WHERE id=?",
                          (mas_tarde, mas_tarde, uid))
        self.conn.commit()
        v = self._vista()
        self.assertEqual(self._ids(v["nuevos"]), {uid})
        self.assertEqual(v["nuevos"][0]["dias_en_prueba"], 5)

    def test_nombres_con_coma_y_particulas(self):
        casos = {"Gómez, Lucía": "", "Lucía, Gómez": "", "de la Fuente": "",
                 "Del Valle": "", "Lucía,": "Lucía", "María José": "María",
                 "Ma. Laura": "", "Nico.": "Nico", "Jo. Pérez": "", "Ana.": "Ana",
                 "nico.pussetto": "", "Ma.José": "", "Mª José": "", "(Nico)": "Nico",
                 "Fede!": "Fede", "Contador Pérez": "", "O'Brien": "O'Brien"}
        for nombre, esperado in casos.items():
            self.assertEqual(emails.nombre_de_pila(nombre), esperado, nombre)


    # ── 10. tercera auditoría ───────────────────────────────────────────────

    def test_doble_click_de_reenvio_lo_frena_la_fecha_vista_aunque_no_haya_espera(self):
        """La espera de 24 h también frena el segundo click; con ella prendida,
        este test pasaba aunque se rompiera la comparación contra la fecha vista
        (lo comprobó el revisor). Con la espera en 0 queda sólo la comparación."""
        a = self._con_prueba(self._persona())
        b = self._con_prueba(self._persona())
        self._mandar("nuevos")
        for u in (a, b):
            self._envejecer_marca(u, 48)
        with patch.object(main, "FEEDBACK_PRUEBA_ESPERA_HORAS", 0):
            en_pantalla = self._vistos("ya_recibieron")
            primero, spy1 = self._mandar("ya_recibieron", vistos=en_pantalla)
            segundo, spy2 = self._mandar("ya_recibieron", vistos=en_pantalla)
        self.assertEqual(primero["sent_count"], 2)
        self.assertEqual(segundo["sent_count"], 0, "el segundo click volvió a mandar")
        self.assertEqual(segundo["skipped_count"], 2)
        spy2.assert_not_called()

    def test_los_otros_mails_del_panel_tambien_hacen_esperar(self):
        reeng = self._con_prueba(self._persona())
        libre = self._con_prueba(self._persona())
        tranquilo = self._con_prueba(self._persona())
        hace10 = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
        self.conn.execute("UPDATE users SET reengagement_email_sent_at=? WHERE id=?",
                          (hace10, reeng))
        # El mail libre guarda con el formato de SQLite (espacio, sin 'T').
        mail = self.conn.execute("SELECT email FROM users WHERE id=?", (libre,)).fetchone()["email"]
        self.conn.execute("INSERT INTO broadcast_send_log (content_hash, email, sent_at) "
                          "VALUES ('abc', ?, ?)",
                          (mail.upper(), (datetime.utcnow() - timedelta(hours=3))
                           .strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()
        espera = {f["id"]: f["espera"] for f in self._vista()["nuevos"]}
        self.assertIn("otro mail de Rendi hace un rato", espera[reeng])
        self.assertIn("hace 3 h", espera[libre])
        self.assertIsNone(espera[tranquilo])

    def test_espera_al_aviso_automatico_que_sale_mañana(self):
        # Fin de Pro le toca a los TRIAL_PRO_DAYS - 1 días: le faltan 12 h.
        mañana = self._con_prueba(self._persona(), arrancó_hace=0)
        self._atrasar(mañana, tr.TRIAL_PRO_DAYS - 1.5)
        lejos = self._con_prueba(self._persona(), arrancó_hace=4)
        espera = {f["id"]: f["espera"] for f in self._vista()["nuevos"]}
        self.assertIn("mañana termina Pro", espera[mañana])
        self.assertIsNone(espera[lejos])

    def test_un_aviso_que_nunca_salio_no_deja_esperando_para_siempre(self):
        """Si el cron no mandó el fin de Pro (caído, cuenta vieja), la persona
        no puede quedar esperando un mail que no va a llegar."""
        uid = self._con_prueba(self._persona(), arrancó_hace=tr.TRIAL_PRO_DAYS + 3)
        self.assertNotIn(tr.MAIL_PRO_ENDING, {r["kind"] for r in self.conn.execute(
            "SELECT kind FROM trial_email_log WHERE user_id=?", (uid,))})
        fila = [f for f in self._vista()["nuevos"] if f["id"] == uid][0]
        self.assertIsNone(fila["espera"])

    def test_fechas_con_zona_horaria_tambien_cuentan(self):
        uid = self._con_prueba(self._persona())
        self.conn.execute(
            "INSERT OR REPLACE INTO trial_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
            (uid, tr.MAIL_PRO_ENDING,
             (datetime.utcnow() - timedelta(hours=2)).isoformat() + "+00:00"))
        self.conn.commit()
        fila = [f for f in self._vista()["nuevos"] if f["id"] == uid][0]
        self.assertIn("hace 2 h", fila["espera"] or "")

    def test_ventanas_de_aviso_coinciden_con_el_cron(self):
        """Diferencial contra el canónico: se corre el cron de verdad y lo que
        manda tiene que ser exactamente lo que ventanas_de_aviso dice que
        corresponde. Si alguien cambia una condición del cron y no la función,
        este test se pone rojo."""
        # Los bordes de cada ventana: antes y después de que abra, y antes y
        # después de que cierre (fin de Pro cierra dos días después de abrir).
        edades = (tr.TRIAL_PRO_DAYS - 1.1, tr.TRIAL_PRO_DAYS - 0.9,
                  tr.TRIAL_PRO_DAYS + 0.9, tr.TRIAL_PRO_DAYS + 1.1,
                  tr.TRIAL_TOTAL_DAYS - tr.MAIL_AVISO_DIAS_ANTES - 0.1,
                  tr.TRIAL_TOTAL_DAYS - tr.MAIL_AVISO_DIAS_ANTES + 0.1)
        uids = []
        for e in edades:
            uid = self._con_prueba(self._persona(), arrancó_hace=0)
            self._atrasar(uid, e)
            uids.append(uid)
        with patch.object(emails, "send_trial_pro_ending", return_value=True), \
             patch.object(emails, "send_trial_ending_soon", return_value=True), \
             patch.object(emails, "send_trial_ended", return_value=True):
            tr.send_due_trial_emails(self.conn)
        ahora = datetime.utcnow()
        for uid in uids:
            r = self.conn.execute("SELECT trial_started_at, trial_ends_at FROM users "
                                  "WHERE id=?", (uid,)).fetchone()
            mandados = {x["kind"] for x in self.conn.execute(
                "SELECT kind FROM trial_email_log WHERE user_id=?", (uid,))}
            for kind in (tr.MAIL_PRO_ENDING, tr.MAIL_ENDING_SOON):
                desde, hasta = tr.ventanas_de_aviso(r["trial_started_at"],
                                                    r["trial_ends_at"])[kind]
                debia = desde <= ahora < hasta
                self.assertEqual(kind in mandados, debia, f"uid={uid} {kind}")


if __name__ == "__main__":
    unittest.main()
