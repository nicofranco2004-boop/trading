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

    def _con_prueba(self, uid, *, arrancó_hace=0):
        """Arranca la prueba con el alta real y después corre el reloj hacia
        atrás moviendo las TRES fechas juntas (si se mueve una sola, la persona
        queda 'terminada' con la prueba viva)."""
        self.assertTrue(tr.start(self.conn, uid).get("ok"))
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

    def _mandar(self, grupo="nuevos", ids=None, ok=True, side_effect=None):
        body = {"confirm": True, "grupo": grupo}
        if ids is not None:
            body["ids"] = list(ids)
        kw = {"side_effect": side_effect} if side_effect else {"return_value": ok}
        with patch("billing.emails.send_trial_feedback", **kw) as spy:
            r = self.client.post(URL, json=body, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), spy

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
        marca_1 = self._marca(viejo)
        recien = self._con_prueba(self._persona())   # arrancó después del primer envío

        res, spy = self._mandar("ya_recibieron")
        self.assertEqual(res["sent_count"], 1)
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
        antes = self._marca(uid)
        res, _ = self._mandar("ya_recibieron", ok=False)
        self.assertEqual(res["failed_count"], 1)
        self.assertEqual(self._marca(uid), antes)

    def test_solo_se_manda_a_los_que_se_vieron_en_la_vista_previa(self):
        visto = self._con_prueba(self._persona())
        ids_vistos = self._ids(self._vista()["nuevos"])
        tarde = self._con_prueba(self._persona())   # arrancó después de mirar la lista

        res, spy = self._mandar("nuevos", ids=ids_vistos)
        self.assertEqual(res["sent_count"], 1)
        self.assertIsNotNone(self._marca(visto))
        self.assertIsNone(self._marca(tarde))

    def test_dos_pestañas_no_le_mandan_dos_veces_a_nadie(self):
        a = self._con_prueba(self._persona())
        b = self._con_prueba(self._persona())

        # Mientras esta pestaña le manda a A, otra pestaña le gana a B.
        def otra_pestaña_le_gana_a_b(*, to, user_name=""):
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

    # ── 4. el mail que se ve es el que se manda ─────────────────────────────

    def test_el_mail_del_panel_es_el_que_sale(self):
        self._con_prueba(self._persona(name="Lucía"))
        v = self._vista()
        enviados = []

        def _send(to, subject, html, text, **kw):
            enviados.append({"to": to, "subject": subject, "html": html,
                             "text": text, **kw})
            return True

        with patch.object(emails, "_send", side_effect=_send):
            r = self.client.post(URL, json={"confirm": True}, headers=self.headers)
        self.assertEqual(r.json()["sent_count"], 1)
        m = enviados[0]
        self.assertEqual(m["subject"], v["mail"]["asunto"])
        self.assertEqual(m["text"], v["mail"]["texto"].replace("(nombre)", "Lucía"))
        self.assertIn("Lucía", m["html"])
        self.assertIn("Nicolás — Rendi", m["text"])
        self.assertEqual(m["reply_to"], "soporte@rendi.finance")


if __name__ == "__main__":
    unittest.main()
