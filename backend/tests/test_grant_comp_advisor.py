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
from datetime import datetime, timedelta
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

    def _vence(self):
        conn = main.get_db()
        try:
            return conn.execute("SELECT credit_active_until FROM users WHERE id = ?",
                                (self.target_uid,)).fetchone()["credit_active_until"]
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


class GrantCompDiasExactosTest(unittest.TestCase):
    """Desde cuándo se cuentan los `days` (pedido de Nico: "que sean 30 exactos").

    Cambiar de plan NO apila sobre el vencimiento viejo — el plan viejo se va,
    así que los 30 días son 30 del plan nuevo. Extender el MISMO plan sí apila:
    "dale 30 días más" tiene que sumar, nunca reiniciar.
    """

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin_uid = _mk_user(conn, f"adm2-{self.tag}@rendi.test", is_admin=1)
        self.target = f"p2-{self.tag}@rendi.test"
        self.target_uid = _mk_user(conn, self.target, tier="plus")
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin_uid)}"}

    def _set_credito(self, plan, dias_por_delante):
        hasta = (datetime.utcnow() + timedelta(days=dias_por_delante)).isoformat()
        conn = main.get_db()
        conn.execute("UPDATE users SET credit_active_until = ?, credit_anchor_plan = ? WHERE id = ?",
                     (hasta, plan, self.target_uid))
        conn.commit(); conn.close()
        return hasta

    def _dias_restantes(self):
        conn = main.get_db()
        try:
            row = conn.execute("SELECT credit_active_until FROM users WHERE id = ?",
                               (self.target_uid,)).fetchone()
        finally:
            conn.close()
        return (datetime.fromisoformat(row["credit_active_until"]) - datetime.utcnow()).days

    def _grant(self, plan, force=False, days=30):
        return self.client.post(
            "/api/admin/billing/grant-comp",
            params={"email": self.target, "plan": plan, "days": days, "force": force},
            headers=self.h,
        )

    def test_cambiar_de_plan_arranca_HOY(self):
        """Plus con 60 días por delante + Asesor 30 → 30 días de Asesor, no 90."""
        self._set_credito("plus", 60)
        with patch.object(main, "_notify_plan_change", return_value=None):
            self._grant("advisor", force=True)
        self.assertEqual(self._dias_restantes(), 29)   # 30 días desde hoy (redondeo a días enteros)

    def test_sin_plan_ancla_tambien_arranca_hoy(self):
        """Prueba gratis (anchor NULL) con tiempo suelto: no hay plan que extender."""
        self._set_credito(None, 45)
        with patch.object(main, "_notify_plan_change", return_value=None):
            self._grant("advisor", force=True)
        self.assertEqual(self._dias_restantes(), 29)

    def test_el_MISMO_plan_sigue_apilando(self):
        """Extender no puede acortar: 40 días de Pro + 30 más = 70, no 30."""
        self._set_credito("pro", 40)
        with patch.object(main, "_notify_plan_change", return_value=None):
            self._grant("pro", force=True)
        self.assertEqual(self._dias_restantes(), 69)

    def test_el_preview_promete_la_MISMA_fecha_que_se_escribe(self):
        """El cartel del panel sale de would_be_active_until. Si la previa y el
        grant calculan distinto, el admin acepta una fecha y se guarda otra."""
        self._set_credito("plus", 60)
        prometido = self._grant("advisor").json()["would_be_active_until"]
        with patch.object(main, "_notify_plan_change", return_value=None):
            self._grant("advisor", force=True)
        conn = main.get_db()
        try:
            escrito = conn.execute("SELECT credit_active_until FROM users WHERE id = ?",
                                   (self.target_uid,)).fetchone()["credit_active_until"]
        finally:
            conn.close()
        self.assertEqual(prometido[:10], escrito[:10])

    def test_cambiar_de_plan_puede_ACORTAR_y_el_preview_lo_deja_ver(self):
        """Caso incómodo a propósito: tenía Plus por 120 días y pasa a Asesor
        30. Le acorta, y tiene que poder verse ANTES de aceptar (el panel avisa
        comparando estas dos fechas)."""
        antes = self._set_credito("plus", 120)
        body = self._grant("advisor").json()
        self.assertLess(body["would_be_active_until"], antes)


class PanelMuestraAsesorTest(unittest.TestCase):
    """Lo que el panel MUESTRA en la columna Plan.

    Nico regalo el Plan Asesor, el grant lo escribio bien... y la fila siguio
    diciendo `free`. `_shape_admin_user_row` derivaba el plan con
    `raw_tier in ("plus","pro")` y 'advisor' caia en el else. Parecia que el
    regalo no se habia aplicado, cuando en la base ya era asesor.
    """

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin_uid = _mk_user(conn, f"adm3-{self.tag}@rendi.test", is_admin=1)
        self.asesor_uid = _mk_user(conn, f"ases-{self.tag}@rendi.test", tier="advisor")
        conn.execute("UPDATE users SET credit_active_until = ?, credit_anchor_plan = 'advisor' WHERE id = ?",
                     ((datetime.utcnow() + timedelta(days=30)).isoformat(), self.asesor_uid))
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin_uid)}"}

    def _fila(self):
        r = self.client.get("/api/admin/users/search",
                            params={"q": f"ases-{self.tag}@rendi.test"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        filas = r.json()["users"] if isinstance(r.json(), dict) else r.json()
        self.assertEqual(len(filas), 1)
        return filas[0]

    def test_la_columna_plan_dice_advisor_no_free(self):
        self.assertEqual(self._fila()["plan"], "advisor")

    def test_no_lo_marca_como_afectado_por_el_bug_de_downgrade(self):
        """`billing_affected` significa 'pago y le quedo el tier en free'. Un
        asesor bien seteado no es eso; marcarlo invitaria a 'restaurarlo' y
        pisarle el plan."""
        self.assertFalse(self._fila()["billing_affected"])


if __name__ == "__main__":
    unittest.main()
