"""Mail a las cuentas EN PAUSA (terminó la prueba y no eligieron plan).

Lo que estos tests protegen, en orden:

  1. Que la lista sea la de las cuentas en pausa HOY, con la misma regla que el
     muro de la app (`cuenta_en_pausa`): ni el que está probando, ni el que
     pagó, ni el que no confirmó el mail, ni las cuentas viejas sin muro.
  2. Que el mail lleve lo de cada persona —nombre, desde cuándo, lo que dejó
     guardado— y que el que no cargó nada reciba el otro mail.
  3. Que el botón principal mande sólo a los que nunca lo recibieron, y el de
     "todos" a todos, con la versión de reenvío para los que ya lo tenían.
  4. Que no se pise con el aviso automático "Terminó tu prueba" ni con otros
     mails del día, que un envío fallido no marque a nadie y que un doble
     click no duplique.
  5. Que el mail que muestra el panel sea el que sale.

Todo por HTTP, y las pruebas se arrancan con `trial.start` — el mismo alta que
usa la app — y se terminan corriendo el reloj hacia atrás.

Corre con: cd backend && python3 -m pytest tests/test_reactivar_pausa.py
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
from fechas import dia_art

URL = "/api/admin/email/reactivar-pausa"


class MailCuentasEnPausa(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("credit_ledger", "subscriptions", "trial_consumed", "trial_email_log",
                  "broadcast_send_log", "operations", "positions", "brokers", "users"):
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

    def _persona(self, *, name=None, verificado=1, requires_plan=1):
        cur = self.conn.execute(
            "INSERT INTO users (email, name, password_hash, approved, email_verified, "
            "                   requires_plan) VALUES (?,?,'x',1,?,?)",
            (f"u-{uuid.uuid4().hex[:10]}@rendi.test", name, verificado, requires_plan))
        self.conn.commit()
        return cur.lastrowid

    def _en_pausa(self, uid=None, *, dias=5, aviso_fin=True, **kw):
        """Arranca la prueba con el alta real y la termina hace `dias` días,
        moviendo las tres fechas juntas. Con `aviso_fin` deja anotado el aviso
        automático "Terminó tu prueba" como lo deja el cron: unas horas después
        del final."""
        uid = uid or self._persona(**kw)
        self.assertTrue(tr.start(self.conn, uid).get("ok"))
        self._atrasar(uid, tr.TRIAL_TOTAL_DAYS + dias)
        if aviso_fin:
            fin = datetime.fromisoformat(self.conn.execute(
                "SELECT trial_ends_at t FROM users WHERE id=?", (uid,)).fetchone()["t"])
            self.conn.execute(
                "INSERT OR REPLACE INTO trial_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
                (uid, tr.MAIL_ENDED, (fin + timedelta(hours=6)).isoformat()))
            self.conn.commit()
        self.assertTrue(main.cuenta_en_pausa(self.conn, uid), "el armado no la dejó en pausa")
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
        for m in self.conn.execute(
                "SELECT kind, sent_at FROM trial_email_log WHERE user_id=?", (uid,)).fetchall():
            self.conn.execute(
                "UPDATE trial_email_log SET sent_at=? WHERE user_id=? AND kind=?",
                (f(m["sent_at"]), uid, m["kind"]))
        self.conn.commit()

    def _cartera(self, uid, posiciones, brokers=("Cocos",)):
        """posiciones = {asset: operaciones}; todas abiertas."""
        for b in brokers:
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                              (uid, b))
        for asset, n_ops in posiciones.items():
            self.conn.execute(
                "INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity) "
                "VALUES (?,?,?,0,100,10)", (uid, brokers[0], asset))
            for i in range(n_ops):
                self.conn.execute(
                    "INSERT INTO operations (user_id, date, broker, asset, op_type, "
                    "                        entry_price, quantity) "
                    "VALUES (?, ?, ?, ?, 'buy', 100, 1)",
                    (uid, f"2026-09-{i + 1:02d}", brokers[0], asset))
        self.conn.commit()

    def _envejecer_marca(self, uid, horas):
        m = self._marca(uid)
        self.conn.execute(
            "UPDATE users SET pausa_email_sent_at=? WHERE id=?",
            ((datetime.fromisoformat(m) - timedelta(hours=horas)).isoformat(), uid))
        self.conn.commit()

    def _vista(self):
        r = self.client.post(URL, json={"confirm": False}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    @staticmethod
    def _todas(v):
        return v["nuevos"] + v["ya_recibieron"]

    def _fila(self, uid, v=None):
        return [f for f in self._todas(v or self._vista()) if f["id"] == uid][0]

    def _vistos(self, grupo="nuevos", vista=None):
        """Lo que manda el panel: cada fila que se puede mandar, con su fecha."""
        v = vista or self._vista()
        filas = v["nuevos"] if grupo == "nuevos" else self._todas(v)
        return [{"id": f["id"], "sent_at": f["sent_at"]} for f in filas if not f["espera"]]

    def _mandar(self, grupo="nuevos", vistos=None, ok=True, side_effect=None):
        if vistos is None:
            vistos = self._vistos(grupo)
        body = {"confirm": True, "grupo": grupo, "vistos": vistos}
        kw = {"side_effect": side_effect} if side_effect else {"return_value": ok}
        with patch("billing.emails.send_reactivar_pausa", **kw) as spy, \
             patch("billing.emails.PAUSA_ENTRE_ENVIOS", 0):
            r = self.client.post(URL, json=body, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), spy

    def _marca(self, uid):
        return self.conn.execute(
            "SELECT pausa_email_sent_at m FROM users WHERE id=?", (uid,)).fetchone()["m"]

    def _mail(self, uid):
        return self.conn.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()["email"]

    @staticmethod
    def _ids(filas):
        return {f["id"] for f in filas}

    # ── 1. a quién le toca ──────────────────────────────────────────────────

    def test_solo_las_cuentas_en_pausa(self):
        pausada = self._en_pausa()
        probando = self._persona()
        self.assertTrue(tr.start(self.conn, probando).get("ok"))
        pagó = self._en_pausa()
        self.conn.execute("UPDATE users SET tier='plus', credit_active_until=? WHERE id=?",
                          ((datetime.utcnow() + timedelta(days=30)).isoformat(), pagó))
        sin_confirmar = self._persona(verificado=0)
        vieja = self._persona(requires_plan=0)    # nació con plan gratis: sin muro
        pasó_a_admin = self._en_pausa()
        self.conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (pasó_a_admin,))
        self.conn.commit()

        v = self._vista()
        self.assertEqual(self._ids(self._todas(v)), {pausada})
        self.assertEqual(v["en_pausa"], 1)
        for quien, por_que in ((probando, "está probando"), (pagó, "pagó"),
                               (sin_confirmar, "no confirmó el mail"),
                               (vieja, "cuenta vieja sin muro"), (pasó_a_admin, "es admin")):
            self.assertNotIn(quien, self._ids(self._todas(v)), por_que)

    def test_el_que_paga_sale_de_la_lista_aunque_lo_haya_visto(self):
        uid = self._en_pausa()
        vistos = self._vistos()
        self.conn.execute("UPDATE users SET tier='plus', credit_active_until=? WHERE id=?",
                          ((datetime.utcnow() + timedelta(days=30)).isoformat(), uid))
        self.conn.commit()
        res, spy = self._mandar(vistos=vistos)
        self.assertEqual(res["sent_count"], 0)
        self.assertEqual(res["discarded_count"], 1)
        spy.assert_not_called()

    # ── 2. lo personalizado ─────────────────────────────────────────────────

    def test_el_mail_lleva_lo_que_dejo_guardado(self):
        uid = self._en_pausa(name="lucía gómez")
        self._cartera(uid, {"GGAL.BA": 5, "AAPL": 3, "MELI": 1, "TSLA": 0,
                            "FCI BALANZ AHORRO EN PESOS": 9},
                      brokers=("Cocos", "IOL"))
        f = self._fila(uid)
        self.assertTrue(f["con_cartera"])
        self.assertEqual(f["saludo"], "Lucía")
        self.assertEqual(f["resumen"], "2 brokers y 18 movimientos")
        # Los que más movió primero, sin ".BA", y el fondo con nombre largo afuera.
        self.assertEqual(f["activos"], ["GGAL", "AAPL", "MELI"])
        texto = f["mail"]["texto"]
        self.assertTrue(texto.startswith("Hola Lucía, tu cuenta de Rendi está en pausa desde el "),
                        texto[:80])
        self.assertIn("2 brokers y 18 movimientos, con GGAL, AAPL y MELI adentro", texto)
        self.assertEqual(f["mail"]["asunto"], "Tu cartera sigue guardada en Rendi")
        self.assertIn("Nicolás — Rendi", texto)
        self.assertNotIn("_resumen", f, "los datos internos viajaron al panel")

    def test_el_resumen_es_el_mismo_que_ve_en_el_muro(self):
        uid = self._en_pausa()
        self._cartera(uid, {"GGAL": 2})
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        me = self.client.get("/api/auth/me", headers=h).json()
        self.assertTrue(me["cuenta_en_pausa"])
        self.assertEqual(me["pausa_resumen"], self._fila(uid)["resumen"])
        self.assertEqual(me["pausa_resumen"], "1 broker y 2 movimientos")

    def test_el_que_no_cargo_nada_recibe_el_otro_mail(self):
        uid = self._en_pausa(name="Martín")
        f = self._fila(uid)
        self.assertFalse(f["con_cartera"])
        self.assertIsNone(f["resumen"])
        self.assertEqual(f["activos"], [])
        self.assertEqual(f["mail"]["asunto"], "Una pregunta corta sobre Rendi")
        self.assertIn("no llegaste a cargar tu cartera", f["mail"]["texto"])
        self.assertNotIn("adentro", f["mail"]["texto"])

    def test_desde_cuando_esta_en_pausa(self):
        uid = self._en_pausa(dias=5)
        fin = datetime.fromisoformat(self.conn.execute(
            "SELECT trial_ends_at t FROM users WHERE id=?", (uid,)).fetchone()["t"])
        f = self._fila(uid)
        self.assertEqual(f["dias_en_pausa"], 5)
        self.assertEqual(f["pausa_desde"], dia_art(fin).isoformat())
        self.assertEqual(f["motivo"], "prueba_terminada")
        from fechas import fecha_legible
        self.assertIn(f"en pausa desde el {fecha_legible(dia_art(fin))},", f["mail"]["texto"])

    def test_el_que_ya_habia_usado_la_prueba_cuenta_desde_que_se_registro(self):
        """La prueba nunca arrancó en esta cuenta (esa casilla ya la había
        usado): está en pausa desde que se creó, no desde un fin que no hubo."""
        uid = self._persona()
        hace = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("UPDATE users SET created_at=? WHERE id=?", (hace, uid))
        self.conn.commit()
        self.assertTrue(main.cuenta_en_pausa(self.conn, uid))
        f = self._fila(uid)
        self.assertEqual(f["motivo"], "prueba_usada")
        self.assertEqual(f["dias_en_pausa"], 10)
        self.assertIsNone(f["espera"])

    # ── 3. los dos botones ──────────────────────────────────────────────────

    def test_el_boton_principal_manda_solo_a_los_que_nunca_lo_recibieron(self):
        a, b = self._en_pausa(), self._en_pausa()
        res, spy = self._mandar("nuevos")
        self.assertEqual(res["sent_count"], 2)
        self.assertFalse(any(c.kwargs["reenvio"] for c in spy.call_args_list))

        v = self._vista()
        self.assertEqual(v["nuevos"], [])
        self.assertEqual(self._ids(v["ya_recibieron"]), {a, b})

        c = self._en_pausa()    # entró en pausa después
        for u in (a, b):
            self._envejecer_marca(u, 48)
        res, spy = self._mandar("nuevos")
        self.assertEqual(res["sent_count"], 1)
        self.assertEqual([x.kwargs["to"] for x in spy.call_args_list], [self._mail(c)])

        # Aunque el pedido del botón principal traiga a alguien que ya lo
        # recibió (con la fecha que se vio), el servidor no se lo manda.
        res, spy = self._mandar("nuevos", vistos=[{"id": a, "sent_at": self._marca(a)}])
        self.assertEqual(res["sent_count"], 0)
        spy.assert_not_called()

    def test_mandar_a_todos_incluye_a_los_que_ya_lo_recibieron_con_el_reenvio(self):
        viejo = self._en_pausa()
        self._mandar("nuevos")
        self._envejecer_marca(viejo, 48)
        marca_1 = self._marca(viejo)
        nuevo = self._en_pausa()

        self.assertIn("recordatorio corto", self._fila(viejo)["mail"]["texto"])
        self.assertNotIn("recordatorio corto", self._fila(nuevo)["mail"]["texto"])

        res, spy = self._mandar("todos")
        self.assertEqual(res["sent_count"], 2)
        reenvio = {c.kwargs["to"]: c.kwargs["reenvio"] for c in spy.call_args_list}
        self.assertEqual(reenvio, {self._mail(viejo): True, self._mail(nuevo): False})
        self.assertGreater(self._marca(viejo), marca_1)

    def test_doble_click_en_todos_no_duplica(self):
        a = self._en_pausa()
        self._mandar("nuevos")
        self._envejecer_marca(a, 48)
        b = self._en_pausa()
        en_pantalla = self._vistos("todos")
        primero, _ = self._mandar("todos", vistos=en_pantalla)
        segundo, spy2 = self._mandar("todos", vistos=en_pantalla)
        self.assertEqual(primero["sent_count"], 2)
        self.assertEqual(segundo["sent_count"], 0, "el segundo click volvió a mandar")
        spy2.assert_not_called()
        self.assertTrue(self._marca(b))

    def test_solo_se_manda_a_los_que_se_vieron(self):
        visto = self._en_pausa()
        vistos = self._vistos()
        tarde = self._en_pausa()
        res, _ = self._mandar(vistos=vistos)
        self.assertEqual(res["sent_count"], 1)
        self.assertIsNotNone(self._marca(visto))
        self.assertIsNone(self._marca(tarde))

    def test_envio_fallido_no_marca_a_nadie(self):
        uid = self._en_pausa()
        res, _ = self._mandar(ok=False)
        self.assertEqual(res["failed_count"], 1)
        self.assertIsNone(self._marca(uid))
        self.assertEqual(self._ids(self._vista()["nuevos"]), {uid})

    # ── 4. no pisarse con otros mails ───────────────────────────────────────

    def test_recien_pausados_se_ven_pero_no_se_les_manda(self):
        uid = self._en_pausa(dias=1)
        f = self._fila(uid)
        self.assertIn("lleva 1 día en pausa", f["espera"])
        res, spy = self._mandar(vistos=[{"id": uid, "sent_at": None}])
        self.assertEqual(res["sent_count"], 0)
        self.assertEqual(res["discarded_count"], 1)
        spy.assert_not_called()

    def test_espera_al_aviso_automatico_de_fin_de_prueba(self):
        uid = self._en_pausa(dias=4, aviso_fin=False)
        self.assertIn("terminó tu prueba", self._fila(uid)["espera"] or "")
        # Si la ventana del cron ya cerró, ese aviso no va a salir: no espera.
        viejo = self._en_pausa(dias=tr.MAIL_FIN_VENTANA_DIAS + 2, aviso_fin=False)
        self.assertIsNone(self._fila(viejo)["espera"])

    def test_otro_mail_de_rendi_hace_poco_hace_esperar(self):
        reeng = self._en_pausa()
        libre = self._en_pausa()
        tranquilo = self._en_pausa()
        hace10 = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
        self.conn.execute("UPDATE users SET reengagement_email_sent_at=? WHERE id=?",
                          (hace10, reeng))
        self.conn.execute("INSERT INTO broadcast_send_log (content_hash, email, sent_at) "
                          "VALUES ('abc', ?, ?)",
                          (self._mail(libre).upper(), (datetime.utcnow() - timedelta(hours=3))
                           .strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()
        v = self._vista()
        self.assertIn("otro mail de Rendi hace un rato", self._fila(reeng, v)["espera"])
        self.assertIn("hace 3 h", self._fila(libre, v)["espera"])
        self.assertIsNone(self._fila(tranquilo, v)["espera"])
        res, _ = self._mandar(vistos=[{"id": reeng, "sent_at": None}])
        self.assertEqual(res["sent_count"], 0)

    def test_recien_recibido_no_se_ofrece_en_todos(self):
        uid = self._en_pausa()
        self._mandar("nuevos")
        f = self._fila(uid)
        self.assertIn("lo recibió hace un rato", f["espera"])
        res, spy = self._mandar("todos", vistos=[{"id": uid, "sent_at": f["sent_at"]}])
        self.assertEqual(res["sent_count"], 0)
        spy.assert_not_called()

    def test_el_feedback_de_la_prueba_tambien_ve_este_mail(self):
        """La regla de "otro mail hace poco" es una sola para los dos mails."""
        uid = self._en_pausa()
        antes, _ = main._otros_mails_de_rendi(self.conn, {uid: "x@rendi.test"},
                                              propia="trial_feedback_email_sent_at")
        self.conn.execute("UPDATE users SET pausa_email_sent_at=? WHERE id=?",
                          (datetime.utcnow().isoformat(), uid))
        self.conn.commit()
        otros, _ = main._otros_mails_de_rendi(self.conn, {uid: "x@rendi.test"},
                                              propia="trial_feedback_email_sent_at")
        self.assertEqual(len(otros[uid]), len(antes[uid]) + 1)

    # ── 5. el mail que se ve es el que sale ─────────────────────────────────

    def test_el_mail_del_panel_es_el_que_sale(self):
        """Atraviesa `_send` entero hasta el pedido a Resend (sólo se reemplaza
        la red)."""
        uid = self._en_pausa(name="lucía gómez")
        self._cartera(uid, {"GGAL": 2, "AL30": 1})
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
        f = self._fila(uid, v)
        self.assertEqual(m["subject"], f["mail"]["asunto"])
        self.assertTrue(m["text"].startswith(f["mail"]["texto"]), m["text"][:80])
        self.assertIn("Hola Lucía,", m["html"])
        self.assertIn("con GGAL y AL30 adentro", m["html"])
        self.assertIn('href="https://rendi.finance/planes"', m["html"])
        self.assertIn("soporte@rendi.finance", m["from"])
        self.assertEqual(m["reply_to"], "soporte@rendi.finance")

    def test_la_prueba_le_llega_solo_al_admin_y_no_marca_a_nadie(self):
        alguien = self._en_pausa()
        self.conn.execute("UPDATE users SET name='Nicolás' WHERE id=?", (self.admin,))
        self.conn.commit()
        for con_cartera in (True, False):
            with patch("billing.emails.send_reactivar_pausa", return_value=True) as spy:
                r = self.client.post(URL, json={"prueba_a_mi": True, "confirm": True,
                                                "con_cartera": con_cartera},
                                     headers=self.headers)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json(), {"prueba": True, "to": self._mail(self.admin),
                                        "sent": True})
            kw = spy.call_args.kwargs
            self.assertEqual(kw["to"], self._mail(self.admin))
            self.assertEqual(kw["user_name"], "Nicolás")
            # Sin cartera propia, la versión con cartera sale con un ejemplo.
            self.assertEqual(bool(kw["resumen"]), con_cartera)
        self.assertIsNone(self._marca(alguien))
        self.assertIsNone(self._marca(self.admin))

    # ── varios ──────────────────────────────────────────────────────────────

    def test_grupo_invalido(self):
        r = self.client.post(URL, json={"grupo": "ya_recibieron"}, headers=self.headers)
        self.assertEqual(r.status_code, 422)

    def test_solo_admin(self):
        uid = self._persona()
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        r = self.client.post(URL, json={"confirm": False}, headers=h)
        self.assertIn(r.status_code, (401, 403))

    def test_manda_de_a_tandas_y_exige_la_lista_vista(self):
        self._en_pausa()
        r = self.client.post(URL, json={"confirm": True}, headers=self.headers)
        self.assertEqual(r.status_code, 422)
        muchos = [{"id": i, "sent_at": None} for i in range(main.ENVIO_MASIVO_LOTE + 1)]
        r = self.client.post(URL, json={"confirm": True, "vistos": muchos}, headers=self.headers)
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
