"""El pedido dice de qué persona es, y el servidor no lo atiende con la sesión de otra.

🔴 POR QUÉ (re-test a ciegas 4, 30/10). La sesión es UNA cookie para todo el
navegador. Si en otra pestaña entra otra persona, la cookie cambia en el acto,
pero la pestaña vieja se entera recién cuando le llega el aviso del navegador
(milisegundos después). En esa ventana, lo que se tocaba —una compra, un mes—
salía con la cookie nueva y se guardaba en la cuenta de la otra persona. La
pantalla no puede cerrar esa ventana: no puede leer la cookie (HttpOnly).

Ahora cada pedido de la app manda `X-Rendi-Persona` (el email de quien la
pestaña cree que está logueado) y `get_current_user` —el único lugar por el
que pasan todos los pedidos con sesión— lo compara con la persona de la
sesión. Si es otra: 409 con code `persona_cambiada`, sin tocar nada. Sin el
encabezado sigue andando (una pestaña con la versión anterior el día que se
publica, scripts, links del mail).

Corre con: cd backend && python3 -m pytest tests/test_persona_de_la_pestana.py
"""
import os
import sys
import tempfile
import unittest
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

from fastapi.testclient import TestClient   # noqa: E402
import main                                 # noqa: E402

PERSONA = "X-Rendi-Persona"


class PersonaDeLaPestana(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        try:
            for t in ("positions", "brokers", "advisor_clients", "users"):
                try:
                    conn.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            alta = ("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?,?,1,1,?)")
            self.ana = conn.execute(alta, ("ana@rendi.test", "x", "pro")).lastrowid
            self.bruno = conn.execute(alta, ("bruno@rendi.test", "x", "pro")).lastrowid
            self.asesora = conn.execute(alta, ("asesora@rendi.test", "x", "advisor")).lastrowid
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, status) VALUES (?,?,?)",
                         (self.asesora, self.ana, "active"))
            conn.commit()
        finally:
            conn.close()

    def _pedido(self, metodo, ruta, uid, persona=None, cliente=None, por_cookie=False, **kw):
        headers = {}
        token = main.create_token(uid)
        if por_cookie:
            self.client.cookies.set(main.COOKIE_NAME, token)
        else:
            headers["Authorization"] = f"Bearer {token}"
        if persona is not None:
            headers[PERSONA] = persona
        if cliente is not None:
            headers["X-Rendi-Client-Id"] = str(cliente)
        try:
            return self.client.request(metodo, ruta, headers=headers, **kw)
        finally:
            self.client.cookies.clear()

    def _rechazo(self, r):
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "persona_cambiada")

    # ── La sesión es de OTRA persona que la que dice el pedido ───────────────
    def test_sesion_de_bruno_con_el_pedido_de_ana_se_rechaza(self):
        for metodo, ruta, kw in (
            ("GET", "/api/positions", {}),
            ("GET", "/api/auth/me", {}),
            ("POST", "/api/brokers", {"json": {"name": "Balanz", "currency": "ARS"}}),
        ):
            with self.subTest(ruta=ruta):
                self._rechazo(self._pedido(metodo, ruta, self.bruno, persona="ana@rendi.test", **kw))

    def test_el_rechazo_no_toca_nada(self):
        r = self._pedido("POST", "/api/brokers", self.bruno, persona="ana@rendi.test",
                         json={"name": "Balanz", "currency": "ARS"})
        self._rechazo(r)
        conn = main.get_db()
        try:
            n = conn.execute("SELECT COUNT(*) AS n FROM brokers").fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(n, 0)

    def test_tambien_con_la_cookie(self):
        self._rechazo(self._pedido("GET", "/api/positions", self.bruno,
                                   persona="ana@rendi.test", por_cookie=True))

    # ── La misma persona, o un pedido que no lo dice ─────────────────────────
    def test_sin_el_encabezado_sigue_andando(self):
        self.assertEqual(self._pedido("GET", "/api/positions", self.bruno).status_code, 200)
        self.assertEqual(self._pedido("GET", "/api/positions", self.bruno, persona="").status_code, 200)

    def test_la_misma_persona_pasa_aunque_cambien_mayusculas_espacios_o_venga_codificado(self):
        for persona in ("ana@rendi.test", " ANA@Rendi.test ", quote("ana@rendi.test")):
            with self.subTest(persona=persona):
                r = self._pedido("GET", "/api/positions", self.ana, persona=persona)
                self.assertEqual(r.status_code, 200, r.text)

    def test_el_asesor_en_un_cliente_es_la_persona_del_asesor(self):
        # La persona es la de la SESIÓN (la asesora), no la del cliente que mira.
        r = self._pedido("GET", "/api/positions", self.asesora, persona="asesora@rendi.test", cliente=self.ana)
        self.assertEqual(r.status_code, 200, r.text)
        self._rechazo(self._pedido("GET", "/api/positions", self.asesora, persona="ana@rendi.test", cliente=self.ana))

    def test_las_pantallas_publicas_que_miran_si_hay_sesion_tambien_rechazan(self):
        # /api/auth/link-request/respond es público pero «aceptar» exige ser el
        # dueño: mira la sesión con _optional_uid. Con la persona equivocada no
        # la trata como «sin sesión»: rechaza igual que el resto.
        token = "t" * 40
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_link_requests")
            conn.execute(
                "INSERT INTO advisor_link_requests (advisor_uid, client_uid, token, email, expires_at) "
                "VALUES (?,?,?,?, datetime('now', '+1 day'))",
                (self.asesora, self.bruno, main._hash_token(token), "bruno@rendi.test"))
            conn.commit()
        finally:
            conn.close()
        r = self._pedido("POST", "/api/auth/link-request/respond", self.bruno, persona="ana@rendi.test",
                         json={"token": token, "accept": True})
        self._rechazo(r)
        conn = main.get_db()
        try:
            estado = conn.execute("SELECT status FROM advisor_link_requests").fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(estado, "pending", "el pedido de acceso no se aceptó")

    def test_una_sesion_invalida_sigue_siendo_401(self):
        r = self.client.get("/api/positions", headers={"Authorization": "Bearer basura",
                                                       PERSONA: "ana@rendi.test"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
