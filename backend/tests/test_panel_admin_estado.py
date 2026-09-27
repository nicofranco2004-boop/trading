"""Lo que la columna Plan del panel de admin dice de la cohorte sin plan gratis.

El caso real (2026-09-26): una persona se registró tres veces en un minuto
(dos casillas mal tipeadas y la buena). La buena confirmó el mail y salió
"pro · 20d"; las otras dos salían **free** — y para quien nace sin plan gratis
eso no existe, así que parecía que la prueba no les había arrancado.

Lo que de verdad pasaba: nunca confirmaron el mail. La prueba arranca en
`verify_email`, no en el registro, y el panel derivaba el plan sólo de
`users.tier` (NULL para ellos → "free"). Lo mismo con quien terminó la prueba
sin pagar: "free", cuando lo que ve es la pantalla de elegir plan.

Todo por HTTP, como en producción: registro → panel → código del mail →
panel → reloj adelantado → panel. Ningún paso escribe la fila a mano salvo el
reloj (se corre el arranque de la prueba hacia atrás, como en
test_prueba_de_punta_a_punta.py).

Corre con: cd backend && python3 -m pytest tests/test_panel_admin_estado.py
"""
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from billing import trial as tr


def setUpModule():
    global _rl
    _rl = patch("main._check_rate_limit")
    _rl.start()


def tearDownModule():
    _rl.stop()


class EstadoEnElPanel(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        conn = main.get_db()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin, email_verified) "
            "VALUES (?, 'x', 1, 1, 1)", (f"adm-{self.tag}@rendi.test",))
        self.admin = cur.lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self._mails = patch("billing.emails._send", return_value=True)
        self._mails.start()

    def tearDown(self):
        self._mails.stop()

    # ── el camino real ──────────────────────────────────────────────────────

    def _registrarse(self, email):
        r = self.client.post("/api/auth/register",
                             json={"email": email, "password": "Password123$",
                                   "name": "benjamin"})
        self.assertEqual(r.status_code, 200, r.text)
        return self._uid(email)

    def _uid(self, email):
        conn = main.get_db()
        try:
            return conn.execute("SELECT id FROM users WHERE email=?",
                                (email,)).fetchone()["id"]
        finally:
            conn.close()

    def _confirmar_mail(self, email):
        conn = main.get_db()
        try:
            code = conn.execute(
                """SELECT code FROM email_verification_codes
                   WHERE user_id = (SELECT id FROM users WHERE email=?)
                   ORDER BY created_at DESC LIMIT 1""", (email,)).fetchone()["code"]
        finally:
            conn.close()
        r = self.client.post("/api/auth/verify-email",
                             json={"email": email, "code": code})
        self.assertEqual(r.status_code, 200, r.text)
        # verify-email loguea (deja la cookie de sesión del usuario nuevo) y la
        # cookie le gana al header del admin en los pedidos siguientes.
        self.client.cookies.clear()

    def _fila(self, email):
        """La fila del panel, por los DOS endpoints que la sirven: la lista y la
        búsqueda comparten el armado y tienen que decir lo mismo."""
        r = self.client.get("/api/admin/users/search",
                            params={"q": email}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = [f for f in r.json() if f["email"] == email]
        self.assertEqual(len(filas), 1)
        r2 = self.client.get("/api/admin/users", headers=self.h)
        self.assertEqual(r2.status_code, 200, r2.text)
        en_lista = [f for f in r2.json() if f["email"] == email]
        self.assertEqual(len(en_lista), 1)
        for k in ("plan", "estado", "pausa_motivo", "requires_plan", "days_remaining"):
            self.assertEqual(filas[0][k], en_lista[0][k],
                             f"la búsqueda y la lista no coinciden en {k}")
        return filas[0]

    def _termino_la_prueba(self, uid):
        """Corre el arranque 21 días atrás: los tres campos viajan juntos."""
        ini = datetime.utcnow() - timedelta(days=tr.TRIAL_TOTAL_DAYS + 1)
        fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
        conn = main.get_db()
        try:
            conn.execute(
                "UPDATE users SET trial_started_at=?, credit_active_until=?, "
                "trial_ends_at=? WHERE id=?",
                (ini.isoformat(), fin.isoformat(), fin.isoformat(), uid))
            conn.commit()
        finally:
            conn.close()

    def _auth_me(self, uid):
        r = self.client.get("/api/auth/me",
                            headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── los casos ───────────────────────────────────────────────────────────

    def test_registrado_sin_confirmar_no_sale_free(self):
        """El caso de la captura: se registró y no confirmó el mail."""
        email = f"benja-{self.tag}@rendi.test"
        self._registrarse(email)
        f = self._fila(email)
        self.assertTrue(f["requires_plan"], "el registro no le puso la marca")
        self.assertEqual(f["estado"], "sin_confirmar")
        self.assertFalse(f["email_verified"])

    def test_al_confirmar_arranca_la_prueba_y_el_panel_lo_dice(self):
        email = f"benja-{self.tag}@rendi.test"
        self._registrarse(email)
        self._confirmar_mail(email)
        f = self._fila(email)
        self.assertEqual(f["plan"], "pro")
        self.assertEqual(f["days_remaining"], tr.TRIAL_TOTAL_DAYS)
        self.assertIsNone(f["estado"])

    def test_termino_la_prueba_sin_pagar_sale_en_pausa_como_ve_el_muro(self):
        email = f"benja-{self.tag}@rendi.test"
        uid = self._registrarse(email)
        self._confirmar_mail(email)
        self._termino_la_prueba(uid)
        f = self._fila(email)
        self.assertEqual(f["estado"], "en_pausa")
        self.assertEqual(f["pausa_motivo"], "prueba_terminada")
        # El panel y la pantalla que ve la persona salen de la MISMA regla.
        me = self._auth_me(uid)
        self.assertTrue(me["cuenta_en_pausa"])
        self.assertEqual(me["pausa_motivo"], f["pausa_motivo"])

    def test_casilla_que_ya_uso_la_prueba_sale_en_pausa_sin_prueba(self):
        """+alias = la misma bandeja: la segunda cuenta no recibe otra prueba."""
        primera = f"benja-{self.tag}@rendi.test"
        self._registrarse(primera)
        self._confirmar_mail(primera)
        segunda = f"benja-{self.tag}+otra@rendi.test"
        uid2 = self._registrarse(segunda)
        self._confirmar_mail(segunda)
        f = self._fila(segunda)
        self.assertEqual(f["estado"], "en_pausa")
        self.assertEqual(f["pausa_motivo"], "prueba_usada")
        self.assertEqual(self._auth_me(uid2)["pausa_motivo"], "prueba_usada")

    def test_cuenta_vieja_con_plan_gratis_sigue_diciendo_free(self):
        """La cohorte de antes del 22/09 SÍ tiene plan gratis: no se toca."""
        email = f"vieja-{self.tag}@rendi.test"
        conn = main.get_db()
        conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, requires_plan) "
            "VALUES (?, 'x', 1, 1, 0)", (email,))
        conn.commit()
        conn.close()
        f = self._fila(email)
        self.assertEqual(f["plan"], "free")
        self.assertIsNone(f["estado"])
        self.assertFalse(f["requires_plan"])

    def test_cuenta_vieja_sin_confirmar_tampoco_es_free(self):
        """Sin confirmar no puede entrar, tenga o no plan gratis."""
        email = f"vieja-{self.tag}@rendi.test"
        conn = main.get_db()
        conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, requires_plan) "
            "VALUES (?, 'x', 1, 0, 0)", (email,))
        conn.commit()
        conn.close()
        f = self._fila(email)
        self.assertEqual(f["estado"], "sin_confirmar")
        self.assertFalse(f["requires_plan"])

    def test_el_afectado_por_el_bug_de_cobro_se_sigue_marcando(self):
        """Pagó (crédito vigente con anchor pago) y el tier quedó en free: el
        panel lo tiene que seguir marcando como restaurable aunque la cuenta,
        por nacer sin plan gratis, esté además en pausa."""
        email = f"benja-{self.tag}@rendi.test"
        uid = self._registrarse(email)
        self._confirmar_mail(email)
        conn = main.get_db()
        conn.execute(
            "UPDATE users SET tier='free', credit_anchor_plan='pro', credit_active_until=? "
            "WHERE id=?",
            ((datetime.utcnow() + timedelta(days=10)).isoformat(), uid))
        conn.commit()
        conn.close()
        self.assertTrue(self._fila(email)["billing_affected"])


if __name__ == "__main__":
    unittest.main()
