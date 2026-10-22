"""La baja de los mails promocionales (Ley 25.326, art. 27).

Las seis campañas del panel de admin no ofrecían forma de dejar de recibirlas.
Ahora cada mail que sale por `_envio_masivo` lleva al pie un link firmado
(/api/email/baja) y los encabezados List-Unsubscribe; quien se da de baja
queda fuera de la lista de cada campaña y, aunque el panel lo tenga en una
vista vieja, el motor no le manda.

Las pruebas pasan por el camino de producción: el endpoint del panel → el
motor → `send_custom` → `_send` → el pedido a Resend (interceptado justo ahí,
con la guarda de pytest apagada sólo para ese tramo).

Corre con: cd backend && python3 -m pytest tests/test_baja_promocionales.py
"""
import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

import main
from billing import emails
from fastapi.testclient import TestClient


def _mk(conn, email, name=None, is_admin=0, verified=1):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, email_verified) "
        "VALUES (?, 'x', 1, ?, ?, ?)",
        (email, is_admin, name, verified),
    ).lastrowid


def _ruta(url):
    """'/api/email/baja?u=..&t=..' a partir de la URL completa del mail."""
    p = urlparse(url)
    return f"{p.path}?{p.query}"


class _Resend:
    """Lo que `_send` le habría mandado a Resend, por destinatario."""

    def __init__(self):
        self.pedidos = {}

    def __call__(self, payload, to, subject):
        self.pedidos[to] = payload
        return True

    def activo(self):
        pila = ExitStack()
        pila.enter_context(patch.object(emails, "_running_under_pytest", return_value=False))
        pila.enter_context(patch.object(emails, "_is_test_address", return_value=False))
        pila.enter_context(patch.object(emails, "_is_configured", return_value=True))
        pila.enter_context(patch.object(emails, "_pedir_a_resend", side_effect=self))
        return pila


class BajaPorElPanelTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        conn = main.get_db()
        self.admin = _mk(conn, f"adm-{self.tag}@rendi.test", is_admin=1)
        self.a = _mk(conn, f"a-{self.tag}@rendi.test", name="Ana")
        self.b = _mk(conn, f"b-{self.tag}@rendi.test", name="Beto")
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}

    def _broadcast(self, **body):
        body = {"subject": f"Novedad {self.tag}", "body": "Hola {nombre}", **body}
        r = self.client.post("/api/admin/email/broadcast", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _mios(self, filas):
        return {f["id"] for f in filas if f["email"].endswith(f"-{self.tag}@rendi.test")}

    def test_cada_mail_lleva_su_link_y_los_encabezados(self):
        resend = _Resend()
        with resend.activo():
            self._broadcast(confirm=True, vistos=[{"id": self.a}, {"id": self.b}])
        for uid, letra in ((self.a, "a"), (self.b, "b")):
            p = resend.pedidos[f"{letra}-{self.tag}@rendi.test"]
            url = main._url_de_baja(uid)
            self.assertEqual(p["headers"]["List-Unsubscribe"], f"<{url}>")
            self.assertEqual(p["headers"]["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
            self.assertIn(url, p["text"])
            self.assertIn(url.replace("&", "&amp;"), p["html"])
        # Cada uno el SUYO: el link de Ana no está en el mail de Beto.
        self.assertNotIn(main._url_de_baja(self.a),
                         resend.pedidos[f"b-{self.tag}@rendi.test"]["text"])

    def test_quien_se_dio_de_baja_no_recibe_mas(self):
        r = self.client.post(_ruta(main._url_de_baja(self.b)))
        self.assertEqual(r.status_code, 200, r.text)

        # La vista previa ya no lo muestra…
        prev = self._broadcast()
        self.assertEqual(self._mios(prev["recipients"]), {self.a})

        # …y aunque el panel lo mande igual (una vista vieja), el motor no le manda.
        resend = _Resend()
        with resend.activo():
            res = self._broadcast(confirm=True, vistos=[{"id": self.a}, {"id": self.b}])
        self.assertIn(f"a-{self.tag}@rendi.test", resend.pedidos)
        self.assertNotIn(f"b-{self.tag}@rendi.test", resend.pedidos)
        self.assertEqual({x["id"] for x in res["sent"]}, {self.a})

    def test_el_motor_frena_aunque_la_campana_no_filtre(self):
        """El chequeo del motor no depende de la consulta de cada campaña: una
        campaña nueva que se olvide del filtro igual no le manda."""
        conn = main.get_db()
        try:
            conn.execute("UPDATE users SET marketing_baja_at='2026-10-22T00:00:00' WHERE id=?",
                         (self.b,))
            conn.commit()
            mandados = []
            dest = [{"id": self.b, "email": f"b-{self.tag}@rendi.test"}]
            res = main._envio_masivo(
                conn, dest, [self.b],
                marcar=lambda t: "m", desmarcar=lambda t, m: None,
                mandar=lambda t: mandados.append(t["id"]) or True, campaña="prueba")
        finally:
            conn.close()
        self.assertEqual(mandados, [])
        self.assertEqual(res["sent_count"], 0)
        self.assertEqual(res["discarded_count"], 1)


class LinkDeBajaTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        conn = main.get_db()
        self.a = _mk(conn, f"la-{self.tag}@rendi.test")
        self.b = _mk(conn, f"lb-{self.tag}@rendi.test")
        conn.commit(); conn.close()

    def _baja(self, uid):
        conn = main.get_db()
        try:
            return main._se_dio_de_baja(conn, uid)
        finally:
            conn.close()

    def test_abrir_el_link_no_da_de_baja(self):
        """Los antivirus del correo abren los links solos: el GET sólo muestra."""
        r = self.client.get(_ruta(main._url_de_baja(self.a)))
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn('method="post"', r.text)
        self.assertFalse(self._baja(self.a))

    def test_baja_y_me_equivoque(self):
        ruta = _ruta(main._url_de_baja(self.a))
        self.assertEqual(self.client.post(ruta).status_code, 200)
        self.assertTrue(self._baja(self.a))
        self.assertFalse(self._baja(self.b))
        # Volver a abrir el link ofrece deshacerlo.
        self.assertIn("/api/email/alta?", self.client.get(ruta).text)
        self.assertEqual(self.client.post(ruta.replace("/baja?", "/alta?")).status_code, 200)
        self.assertFalse(self._baja(self.a))

    def test_la_firma_de_uno_no_sirve_para_otro(self):
        q = parse_qs(urlparse(main._url_de_baja(self.a)).query)
        r = self.client.post(f"/api/email/baja?u={self.b}&t={q['t'][0]}")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self._baja(self.b))
        for ruta in (f"/api/email/baja?u={self.b}", f"/api/email/baja?u=x&t=abc",
                     "/api/email/baja"):
            self.assertEqual(self.client.post(ruta).status_code, 400, ruta)
            self.assertEqual(self.client.get(ruta).status_code, 400, ruta)
        self.assertFalse(self._baja(self.b))

    def test_boton_de_gmail_un_click(self):
        """List-Unsubscribe-Post: el cliente hace un POST con ese cuerpo."""
        r = self.client.post(_ruta(main._url_de_baja(self.a)),
                             data={"List-Unsubscribe": "One-Click"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self._baja(self.a))


class SeisCampanasTest(unittest.TestCase):
    """Las seis funciones de campaña pasan por `_send`: adentro de `con_baja`
    todas salen con el link. Si una armara su propio pedido, saldría sin él."""

    def test_las_seis_llevan_el_link(self):
        url = "https://rendi.finance/api/email/baja?u=1&t=abc"
        campañas = {
            "reengagement": lambda to: emails.send_reengagement(to=to, user_name="Ana"),
            "regalo": lambda to: emails.send_gift_plan_history(to=to, user_name="Ana"),
            "invitacion": lambda to: emails.send_trial_invite(to=to, user_name="Ana"),
            "feedback": lambda to: emails.send_trial_feedback(to=to, user_name="Ana"),
            "pausa": lambda to: emails.send_reactivar_pausa(to=to, user_name="Ana",
                                                            con_cartera=True),
            "libre": lambda to: emails.send_custom(to=to, subject="Hola", body="Che"),
        }
        resend = _Resend()
        with resend.activo(), emails.envio_masivo(), emails.con_baja(url):
            for nombre, mandar in campañas.items():
                mandar(f"{nombre}@ejemplo.com")
        for nombre in campañas:
            p = resend.pedidos[f"{nombre}@ejemplo.com"]
            self.assertEqual(p.get("headers", {}).get("List-Unsubscribe"), f"<{url}>", nombre)
            self.assertIn(url, p["text"], nombre)

    def test_un_transaccional_no_lleva_baja(self):
        resend = _Resend()
        with resend.activo(), emails.envio_masivo():
            emails.send_password_reset(to="t@ejemplo.com", user_name="Ana", reset_url="https://rendi.finance/r")
        p = resend.pedidos["t@ejemplo.com"]
        self.assertNotIn("headers", p)
        self.assertNotIn("/api/email/baja", p["text"])


if __name__ == "__main__":
    unittest.main()
