"""Al que se registró sin plan gratis, ningún mail le dice "tu cuenta vuelve a Free".

Desde el 22/09/2026 quien se registra NACE sin plan gratis (`users.requires_plan`):
arranca la prueba de 20 días y, cuando se le termina lo que tiene, la cuenta
queda EN PAUSA hasta que elija un plan. Los mails de la prueba ya lo decían así.
El de la baja y el del plan regalado no: le prometían un Free que no existe, en
el momento justo en que tiene que decidir si paga.

Los tests importantes van por el camino de producción —el endpoint que cancela
(`/api/billing/cancel`) y el que regala (`/api/admin/billing/grant-comp`)— y
leen el mail que se arma de verdad. Llamar a `send_cancellation(requiere_plan=True)`
a mano certificaría la función y dejaría afuera justo lo que faltaba: que el
que la llama le pase el dato.

Corre con: cd backend && python3 -m pytest tests/test_sin_plan_gratis_al_terminar.py
"""
import unittest
import uuid
from unittest.mock import patch

import main
from billing import emails
from fastapi.testclient import TestClient


def _mk_user(conn, email, *, requires_plan, is_admin=0, tier=None):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, tier, "
        "                   requires_plan) VALUES (?, 'x', 1, ?, 'Ana', ?, ?)",
        (email, is_admin, tier, 1 if requires_plan else 0),
    )
    return cur.lastrowid


def _lo_que_se_mando(send_mock) -> str:
    """Asunto + HTML + texto de todo lo que pasó por `_send`, en un string."""
    partes = []
    for c in send_mock.call_args_list:
        partes += [str(a) for a in c.args] + [str(v) for v in c.kwargs.values()]
    return "\n".join(partes)


class ElMailDeLaBaja(unittest.TestCase):
    """Cancelar desde la app: POST /api/billing/cancel → mail de confirmación."""

    def setUp(self):
        self.client = TestClient(main.app)

    def _cancelar(self, *, requires_plan):
        conn = main.get_db()
        uid = _mk_user(conn, f"baja-{uuid.uuid4().hex[:10]}@rendi.test",
                       requires_plan=requires_plan)
        sub_id = f"sub-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'authorized', 5990)""",
            (uid, sub_id),
        )
        conn.commit()
        conn.close()
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        with patch("billing.rebill.cancel_subscription",
                   return_value={"id": sub_id, "status": "cancelled"}), \
             patch.object(emails, "_send", return_value=True) as send:
            r = self.client.post("/api/billing/cancel", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(send.called, "la baja no mandó el mail de confirmación")
        return _lo_que_se_mando(send)

    def test_al_que_nacio_sin_plan_gratis_le_dice_que_queda_en_pausa(self):
        mail = self._cancelar(requires_plan=True)
        self.assertNotIn("vuelve a Free", mail)
        self.assertIn("queda en pausa hasta que elijas un plan", mail)
        # Y lo que más asusta, dicho: no se pierde nada.
        self.assertIn("tus datos no se borran", mail)

    def test_al_que_ya_tenia_el_free_le_sigue_diciendo_que_vuelve(self):
        """El contrapeso: la cuenta vieja SÍ tiene Free, y eso no cambió."""
        mail = self._cancelar(requires_plan=False)
        self.assertIn("vuelve a Free", mail)
        self.assertNotIn("en pausa", mail)


class ElMailDelRegalo(unittest.TestCase):
    """Regalar un plan desde /admin: el mail al usuario y el aviso al admin."""

    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        admin = _mk_user(conn, f"admin-{uuid.uuid4().hex[:10]}@rendi.test",
                         requires_plan=False, is_admin=1)
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(admin)}"}

    def _regalar(self, *, requires_plan):
        conn = main.get_db()
        email = f"regalo-{uuid.uuid4().hex[:10]}@rendi.test"
        _mk_user(conn, email, requires_plan=requires_plan, tier="free")
        conn.commit()
        conn.close()
        with patch.object(main, "_notify_plan_change", return_value=None), \
             patch.object(emails, "_send", return_value=True) as send:
            r = self.client.post(
                "/api/admin/billing/grant-comp",
                params={"email": email, "plan": "pro", "days": 30},
                headers=self.h,
            )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("ok"), r.text)
        self.assertTrue(send.called, "el regalo no mandó el mail al usuario")
        return _lo_que_se_mando(send), r.json()["detail"]

    def test_al_que_nacio_sin_plan_gratis_no_le_promete_el_free(self):
        mail, aviso_al_admin = self._regalar(requires_plan=True)
        self.assertNotIn("vuelve a Free", mail)
        self.assertIn("queda en pausa", mail)
        # El panel de admin tampoco: Nico leía "vuelve a Free solo".
        self.assertNotIn("vuelve a Free", aviso_al_admin)
        self.assertIn("pausa", aviso_al_admin)

    def test_a_la_cuenta_vieja_le_sigue_diciendo_que_vuelve_a_free(self):
        mail, aviso_al_admin = self._regalar(requires_plan=False)
        self.assertIn("vuelve a Free", mail)
        self.assertIn("vuelve a Free", aviso_al_admin)


class ElAvisoDeVencimiento(unittest.TestCase):
    """3 días antes de que venza un plan cancelado. Va por `run_lifecycle_job`,
    el mismo job que corre el cron diario (`/api/billing/run-cron`)."""

    def _aviso(self, *, requires_plan):
        from datetime import datetime, timedelta
        from billing import subscriptions
        conn = main.get_db()
        email = f"vence-{uuid.uuid4().hex[:10]}@rendi.test"
        uid = _mk_user(conn, email, requires_plan=requires_plan, tier="plus")
        fin = (datetime.utcnow() + timedelta(days=2)).isoformat()
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, current_period_end)
               VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'cancelled', 5990, ?)""",
            (uid, f"sub-{uuid.uuid4().hex[:10]}", fin),
        )
        conn.commit()
        try:
            with patch.object(emails, "_send", return_value=True) as send:
                subscriptions.run_lifecycle_job(conn)
        finally:
            conn.close()
        # El job recorre TODA la base: me quedo con lo que le llegó a esta
        # persona, y de eso, con el aviso de vencimiento.
        mios = [c for c in send.call_args_list
                if c.args and c.args[0] == email and "vence en" in str(c.args[1])]
        self.assertTrue(mios, "no salió el aviso de vencimiento")
        return "\n".join(str(a) for c in mios for a in c.args)

    def test_al_que_nacio_sin_plan_gratis_no_le_lista_lo_que_le_queda_en_free(self):
        mail = self._aviso(requires_plan=True)
        self.assertNotIn("vas a quedar con 1", mail)
        self.assertIn("queda en pausa hasta que elijas un plan", mail)

    def test_a_la_cuenta_vieja_le_sigue_listando_lo_que_pierde(self):
        mail = self._aviso(requires_plan=False)
        self.assertIn("vas a perder", mail)
        self.assertNotIn("en pausa", mail)


class ElAvisoInternoDePruebasTerminadas(unittest.TestCase):
    """El mail agregado que le llega al admin cuando el cron cierra pruebas."""

    def test_dice_los_dias_de_hoy_y_distingue_free_de_pausa(self):
        from billing import subscriptions
        from billing.trial import TRIAL_TOTAL_DAYS
        # Dirección de verdad a propósito: las de dominios de prueba se filtran
        # antes de armar el mail (y `_send` está reemplazado, no sale nada).
        with patch.object(emails, "_send", return_value=True) as send:
            subscriptions._notify_admin_trials_ended(["ana.prueba@gmail.com"])
        self.assertTrue(send.called)
        mail = _lo_que_se_mando(send)
        # Decía "la prueba de 15 días" con la prueba ya en 20.
        self.assertIn(f"prueba de {TRIAL_TOTAL_DAYS} días", mail)
        self.assertIn("en pausa", mail)


if __name__ == "__main__":
    unittest.main()
