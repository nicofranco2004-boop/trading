"""El aviso de los cambios en la política de privacidad (06/11/2026).

Es un AVISO DE SERVICIO, no un promocional: le llega también a quien se dio de
baja de los promocionales —la política (§14) promete avisar por mail los
cambios importantes, y darse de baja de la publicidad no es darse de baja de los
avisos sobre tus datos—, con el texto fijo de billing/emails.py y el link de
baja de cada uno adentro, sin el pie automático de los promocionales. Las demás
campañas, el envío libre incluido, siguen sin poder mandarle nada a quien se dio
de baja.

Por el camino de producción: el endpoint del panel → el motor (`_envio_masivo`)
→ `send_aviso_privacidad` → `send_custom` → `_send` → el pedido a Resend
(interceptado justo ahí, como en test_baja_promocionales.py).

Corre con: cd backend && python3 -m pytest tests/test_aviso_privacidad.py
"""
import inspect
import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import urlparse

import main
from billing import emails
from fastapi.testclient import TestClient


def _mk(conn, email, name=None, is_admin=0, verified=1, baja=None, managed_by=None):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, email_verified, "
        "marketing_baja_at, managed_by) VALUES (?, 'x', 1, ?, ?, ?, ?, ?)",
        (email, is_admin, name, verified, baja, managed_by),
    ).lastrowid


class _Resend:
    """Lo que `_send` le habría mandado a Resend, por destinatario."""

    def __init__(self):
        self.pedidos = {}

    def __call__(self, payload, to, subject):
        self.pedidos[to] = {**payload, "_asunto": subject}
        return True

    def activo(self):
        pila = ExitStack()
        pila.enter_context(patch.object(emails, "_running_under_pytest", return_value=False))
        pila.enter_context(patch.object(emails, "_is_test_address", return_value=False))
        pila.enter_context(patch.object(emails, "_is_configured", return_value=True))
        pila.enter_context(patch.object(emails, "_pedir_a_resend", side_effect=self))
        return pila


class AvisoPrivacidadTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        conn = main.get_db()
        self.admin = _mk(conn, f"adm-{self.tag}@rendi.test", is_admin=1)
        self.ana = _mk(conn, f"ana-{self.tag}@rendi.test", name="Ana")
        # Se dio de baja de los promocionales: el aviso le llega igual.
        self.beto = _mk(conn, f"beto-{self.tag}@rendi.test", name="Beto", baja="2026-11-01T10:00:00")
        self.sin = _mk(conn, f"sin-{self.tag}@rendi.test")
        # No reciben: sin mail confirmado y cliente de un asesor.
        self.noconf = _mk(conn, f"noconf-{self.tag}@rendi.test", verified=0)
        self.cliente = _mk(conn, f"cli-{self.tag}@rendi.test", managed_by=self.admin)
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}

    def _aviso(self, **body):
        r = self.client.post("/api/admin/email/aviso-privacidad", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _mios(self, filas):
        return {f["id"] for f in filas if f["email"].endswith(f"-{self.tag}@rendi.test")}

    def _mail(self, resend, quien):
        return resend.pedidos[f"{quien}-{self.tag}@rendi.test"]

    def test_a_quienes_les_llega_y_que_dice(self):
        prev = self._aviso()
        self.assertEqual(self._mios(prev["recipients"]), {self.ana, self.beto, self.sin})
        self.assertTrue(next(f for f in prev["recipients"] if f["id"] == self.beto)["dado_de_baja"])
        self.assertFalse(next(f for f in prev["recipients"] if f["id"] == self.ana)["dado_de_baja"])
        # El panel muestra el texto que va a salir: el del servidor, no uno propio.
        self.assertEqual(prev["asunto"], emails.AVISO_PRIVACIDAD_ASUNTO)
        self.assertEqual(prev["cuerpo"], emails.AVISO_PRIVACIDAD_CUERPO)
        # Lo que Nico pidió que quede claro primero.
        self.assertIn("los datos de tu cartera", prev["cuerpo"])
        self.assertIn("no se usan para publicidad", prev["cuerpo"])

    def test_le_llega_tambien_a_quien_se_dio_de_baja_con_su_link_y_sin_el_pie_promocional(self):
        resend = _Resend()
        with resend.activo():
            res = self._aviso(confirm=True, vistos=[{"id": u} for u in (self.ana, self.beto, self.sin)])
        self.assertEqual({x["id"] for x in res["sent"]}, {self.ana, self.beto, self.sin})
        for uid, quien in ((self.ana, "ana"), (self.beto, "beto"), (self.sin, "sin")):
            p = self._mail(resend, quien)
            self.assertEqual(p["_asunto"], emails.AVISO_PRIVACIDAD_ASUNTO)
            # Su link para salir de la lista de Meta y de los promocionales…
            self.assertIn(main._url_de_baja(uid), p["text"])
            # …y no el pie de los promocionales ni sus encabezados: no lo es.
            self.assertNotIn("Si no querés recibir más mails como este", p["text"])
            self.assertNotIn("List-Unsubscribe", p.get("headers") or {})
            self.assertNotIn("{baja}", p["text"])
            self.assertNotIn("{saludo}", p["text"])
        self.assertTrue(self._mail(resend, "ana")["text"].startswith("Hola Ana,"))
        self.assertTrue(self._mail(resend, "sin")["text"].startswith("Hola,"))
        # Cada uno el SUYO.
        self.assertNotIn(main._url_de_baja(self.ana), self._mail(resend, "beto")["text"])

    def test_aunque_el_panel_mande_a_otros_no_les_llega(self):
        # Una lista vieja o armada a mano: el servidor vuelve a filtrar.
        resend = _Resend()
        with resend.activo():
            res = self._aviso(confirm=True, vistos=[{"id": self.noconf}, {"id": self.cliente},
                                                     {"id": self.admin}])
        self.assertEqual(res["sent_count"], 0)
        self.assertEqual(resend.pedidos, {})

    def test_el_mismo_aviso_no_le_llega_dos_veces(self):
        resend = _Resend()
        with resend.activo():
            self._aviso(confirm=True, vistos=[{"id": self.ana}])
        otra = _Resend()
        with otra.activo():
            res = self._aviso(confirm=True, vistos=[{"id": self.ana}])
        self.assertEqual(otra.pedidos, {})
        self.assertEqual(res["skipped_count"], 1)
        prev = self._aviso()
        self.assertTrue(next(f for f in prev["recipients"] if f["id"] == self.ana)["ya_recibio"])

    def test_el_envio_libre_sigue_sin_llegarle_a_quien_se_dio_de_baja(self):
        resend = _Resend()
        with resend.activo():
            r = self.client.post("/api/admin/email/broadcast", headers=self.h, json={
                "subject": f"Promo {self.tag}", "body": "Hola {nombre}", "confirm": True,
                "vistos": [{"id": self.ana}, {"id": self.beto}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(f"ana-{self.tag}@rendi.test", resend.pedidos)
        self.assertNotIn(f"beto-{self.tag}@rendi.test", resend.pedidos)

    def test_la_prueba_va_sola_a_la_direccion_dada(self):
        resend = _Resend()
        with resend.activo():
            r = self._aviso(test_to=f"prueba-{self.tag}@rendi.test")
        self.assertTrue(r["test"])
        self.assertTrue(r["sent"])
        self.assertEqual(set(resend.pedidos), {f"prueba-{self.tag}@rendi.test"})

    def test_solo_un_admin(self):
        r = self.client.post("/api/admin/email/aviso-privacidad", json={},
                             headers={"Authorization": f"Bearer {main.create_token(self.ana)}"})
        self.assertEqual(r.status_code, 403)
        self.assertIn(self.client.post("/api/admin/email/aviso-privacidad", json={}).status_code, (401, 403))

    def test_darse_de_baja_dice_que_tambien_saca_de_la_lista_de_meta(self):
        p = urlparse(main._url_de_baja(self.ana))
        r = self.client.post(f"{p.path}?{p.query}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("lista que le pasamos a Meta", r.text)

    def test_solo_el_aviso_usa_la_excepcion_a_la_baja(self):
        """La excepción a la baja (`aviso_de_servicio`) se pasa sólo desde el
        aviso con texto fijo: en el envío libre —o en una campaña— sería una
        puerta para mandarle promociones a quien pidió no recibirlas. Se mira el
        CÓDIGO (cada llamada al motor), no el texto: un comentario que la nombra
        no cuenta, y una variable con True adentro sí."""
        import ast
        arbol = ast.parse(inspect.getsource(main))
        quienes = set()
        for funcion in ast.walk(arbol):
            if not isinstance(funcion, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for nodo in ast.walk(funcion):
                if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                        and nodo.func.id in ("_envio_masivo", "_envio_masivo_en_fila")):
                    for kw in nodo.keywords:
                        apagada = isinstance(kw.value, ast.Constant) and kw.value.value is False
                        if kw.arg == "aviso_de_servicio" and not apagada:
                            quienes.add(funcion.name)
        # `_envio_masivo` se la pasa a su fila; además, sólo el aviso.
        self.assertEqual(quienes, {"_envio_masivo", "admin_email_aviso_privacidad"})

if __name__ == "__main__":
    unittest.main()
