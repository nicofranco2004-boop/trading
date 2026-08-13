"""Tests para regalar el PLAN ASESOR desde el panel de admin (grant-comp).

Nico intentó pasarle el Plan Asesor a un piloto que ya tenía tiempo activo y el
panel le contestó "ya tiene Plus activo — extender 30 días → Plus". Nada de eso
era cierto: ni el plan que tenía era Plus, ni el que le estaba dando.

La raíz es una sola y estaba repartida en tres lugares: 'advisor' se sumó al
grant pero NUNCA a los helpers que ponen el NOMBRE del plan, así que caía en el
`else` de cada uno — 'Plus' en los confirms del admin y, peor, 'Pro' en el mail
que recibe el usuario, con la lista de features de Pro adentro.

Estos tests cubren la parte de backend (el mail y el endpoint). El fix del panel
va en frontend/src/pages/Admin.jsx (constante PLAN_LABEL).
"""
import unittest
import uuid
from unittest.mock import patch

import main
from billing import emails
from fastapi.testclient import TestClient


def _mk_user(conn, email, is_admin=0, tier=None):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, tier) "
        "VALUES (?, 'x', 1, ?, 'Piloto', ?)",
        (email, is_admin, tier),
    )
    return cur.lastrowid


class PlanLabelAsesorTest(unittest.TestCase):
    """El nombre del plan. Sin el fix, 'advisor' se anunciaba como 'Pro'."""

    def test_label_de_cada_plan(self):
        self.assertEqual(emails._plan_label("plus"), "Plus")
        self.assertEqual(emails._plan_label("pro"), "Pro")
        # ↓ la regresión: caía en el else y devolvía "Pro"
        self.assertEqual(emails._plan_label("advisor"), "Asesor")

    def test_features_del_asesor_no_son_las_de_pro(self):
        """El Asesor no es 'un Pro más grande': el mail le prometía análisis de
        IA por semana y brokers ilimitados en vez de sus clientes y su libro."""
        html = emails._plan_features_html("advisor")
        pro = emails._plan_features_html("pro")
        self.assertNotEqual(html, pro)
        self.assertIn("clientes", html.lower())
        self.assertIn("libro", html.lower())
        texto = emails._plan_features_text("advisor")
        self.assertNotEqual(texto, emails._plan_features_text("pro"))
        self.assertIn("clientes", texto.lower())

    def test_el_mail_del_regalo_dice_asesor(self):
        with patch.object(emails, "_send", return_value=True) as send:
            emails.send_gifted_plan(to="a@rendi.test", user_name="Ana",
                                    plan="advisor", days=30,
                                    active_until="2026-10-12T00:00:00")
        self.assertTrue(send.called)
        cuerpo = " ".join(str(a) for a in send.call_args.args) + " " + str(send.call_args.kwargs)
        self.assertIn("Asesor", cuerpo)
        # Sin el fix el mail decía "Rendi Pro" — el plan equivocado, por escrito.
        self.assertNotIn("Rendi Pro", cuerpo)


class GrantCompAsesorTest(unittest.TestCase):
    """El endpoint: regalar Asesor a alguien CON tiempo activo tiene que
    reemplazarle el plan, no dejarlo como estaba."""

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin_uid = _mk_user(conn, f"admin-{self.tag}@rendi.test", is_admin=1)
        self.target = f"piloto-{self.tag}@rendi.test"
        self.target_uid = _mk_user(conn, self.target, tier="plus")
        # Tiempo activo por delante, como el caso real.
        conn.execute(
            "UPDATE users SET credit_active_until = ?, credit_anchor_plan = 'plus' WHERE id = ?",
            ("2099-09-12T00:00:00", self.target_uid),
        )
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin_uid)}"}

    def _tier(self):
        conn = main.get_db()
        try:
            return conn.execute("SELECT tier FROM users WHERE id = ?",
                                (self.target_uid,)).fetchone()["tier"]
        finally:
            conn.close()

    def _grant(self, plan, force=False):
        return self.client.post(
            "/api/admin/billing/grant-comp",
            params={"email": self.target, "plan": plan, "days": 30, "force": force},
            headers=self.h,
        )

    def test_preview_dice_QUE_tiene_y_QUE_le_estas_dando(self):
        """El panel arma el cartel con estos dos campos. Si no distinguen el
        plan actual del pedido, el admin no puede saber qué va a pasar."""
        r = self._grant("advisor")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "credit_already_active")
        self.assertEqual(body["current_plan"], "plus")
        self.assertEqual(body["requested_plan"], "advisor")
        self.assertEqual(self._tier(), "plus")   # el preview NO toca nada

    def test_con_force_el_plan_de_usuario_SE_VA_y_queda_asesor(self):
        with patch.object(main, "_notify_plan_change", return_value=None):
            r = self._grant("advisor", force=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))
        self.assertEqual(self._tier(), "advisor")

    def test_sin_plan_ancla_igual_lo_deja_asesor(self):
        """El estado de quien está en prueba gratis: tiempo activo y anchor
        NULL. El panel lo leía como 'ya tiene Plus'."""
        conn = main.get_db()
        conn.execute("UPDATE users SET credit_anchor_plan = NULL, tier = 'free' WHERE id = ?",
                     (self.target_uid,))
        conn.commit(); conn.close()
        r = self._grant("advisor")
        self.assertIsNone(r.json()["current_plan"])
        with patch.object(main, "_notify_plan_change", return_value=None):
            self._grant("advisor", force=True)
        self.assertEqual(self._tier(), "advisor")


if __name__ == "__main__":
    unittest.main()
