"""Sin el plan Asesor no se entra a la cuenta de ningún cliente (10/11/2026).

Hasta acá, la puerta por la que el asesor mira a un cliente (el encabezado
X-Rendi-Client-Id, `_resolve_client_context`) sólo pedía un vínculo activo en
`advisor_clients`. El vínculo no se borra cuando el plan vence, así que a quien
se le venció o se le quitó el plan Asesor seguía leyendo y escribiendo las
carteras de sus clientes desde cualquier pantalla. Todo /api/advisor/* ya pedía
el plan; esta puerta no. Se vio al quitarle el plan a mano a una cuenta de
prueba de producción, que conservaba tres vínculos de lectura y escritura.

Todo pasa por los caminos de producción: el plan se da con el botón del panel
(grant-comp), el cliente se crea con el endpoint del asesor, el vencimiento lo
procesa el mismo proceso de la noche, y el acceso se mide pidiendo la cartera
por HTTP con el encabezado, como la pantalla.

Corre con: cd backend && python3 -m pytest tests/test_asesor_sin_plan.py
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
from billing import emails
from billing import subscriptions
from fastapi.testclient import TestClient

SIN_PLAN = "Requiere el plan Asesor"


class AsesorSinPlanTest(unittest.TestCase):

    def setUp(self):
        self.http = TestClient(main.app)
        tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?, 'x', 1, 1)",
            (f"admin-{tag}@rendi.test",)).lastrowid
        self.email = f"asesora-{tag}@rendi.test"
        self.asesora = conn.execute(
            "INSERT INTO users (email, password_hash, approved, name) VALUES (?, 'x', 1, 'Asesora')",
            (self.email,)).lastrowid
        conn.commit()
        conn.close()
        self._regalar_plan()
        r = self.http.post("/api/advisor/clients", json={"label": "Juan P"},
                           headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        self.cliente = r.json()["client_uid"]
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'Cocos', 'ARS')",
                     (self.cliente,))
        conn.commit()
        conn.close()

    def tearDown(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.asesora,))
            conn.commit()
        finally:
            conn.close()

    # ── ayudantes ────────────────────────────────────────────────────────────
    def _hdr(self, cliente=None):
        h = {"Authorization": f"Bearer {main.create_token(self.asesora)}"}
        if cliente is not None:
            h["X-Rendi-Client-Id"] = str(cliente)
        return h

    def _regalar_plan(self, force=False):
        """El botón «Asesor» del panel de admin."""
        with patch.object(emails, "_send", return_value=True):
            r = self.http.post(
                "/api/admin/billing/grant-comp",
                params={"email": self.email, "plan": "advisor", "days": 30, "force": force},
                headers={"Authorization": f"Bearer {main.create_token(self.admin)}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("ok"), r.text)

    def _ver_cartera(self):
        return self.http.get("/api/positions", headers=self._hdr(self.cliente))

    def _comprar(self):
        return self.http.post("/api/positions", headers=self._hdr(self.cliente),
                              json=dict(broker="Cocos", asset="AL30", quantity=10, buy_price=100))

    def _posiciones_del_cliente(self):
        conn = main.get_db()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM positions WHERE user_id=? AND asset='AL30'",
                (self.cliente,)).fetchone()["n"]
        finally:
            conn.close()

    def _sql(self, sql, params):
        conn = main.get_db()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _assert_sin_plan(self, r):
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json().get("detail"), SIN_PLAN)

    # ── con el plan, todo como siempre ──────────────────────────────────────
    def test_con_el_plan_mira_y_escribe_en_su_cliente(self):
        self.assertEqual(self._ver_cartera().status_code, 200)
        self.assertEqual(self._comprar().status_code, 200)
        self.assertEqual(self._posiciones_del_cliente(), 1)

    # ── sin el plan, la puerta se cierra ────────────────────────────────────
    def test_plan_quitado_a_mano_no_mira_ni_escribe(self):
        # Lo mismo que se hizo en producción el 10/11 con nicolas@rendi.finance:
        # pasar a Free y vencer el crédito ahora.
        self._sql("UPDATE users SET tier=NULL, credit_active_until=? WHERE id=?",
                  (datetime.utcnow().isoformat(), self.asesora))
        self._assert_sin_plan(self._ver_cartera())
        self._assert_sin_plan(self._comprar())
        self.assertEqual(self._posiciones_del_cliente(), 0)

    def test_plan_vencido_corta_en_el_acto_y_despues_de_la_noche(self):
        # Vence a mitad del día: la columna todavía dice 'advisor' porque el
        # proceso de la noche no corrió, y aun así no entra.
        self._sql("UPDATE users SET credit_active_until=? WHERE id=?",
                  ((datetime.utcnow() - timedelta(minutes=1)).isoformat(), self.asesora))
        self._assert_sin_plan(self._ver_cartera())
        # Corre el proceso de la noche (el mismo de producción) y sigue sin entrar.
        conn = main.get_db()
        try:
            with patch.object(emails, "_send", return_value=True):
                subscriptions._downgrade_expired_credit(conn)
        finally:
            conn.close()
        self._assert_sin_plan(self._ver_cartera())
        self._assert_sin_plan(self._comprar())
        self.assertEqual(self._posiciones_del_cliente(), 0)

    def test_ser_admin_no_reemplaza_al_plan(self):
        # Misma regla que /api/advisor/* (fix 35a2521): is_admin no alcanza.
        self._sql("UPDATE users SET tier=NULL, credit_active_until=NULL, is_admin=1 WHERE id=?",
                  (self.asesora,))
        self._assert_sin_plan(self._ver_cartera())

    # ── lo que NO tiene que cambiar ─────────────────────────────────────────
    def test_si_vuelve_a_tener_el_plan_recupera_a_sus_clientes(self):
        self._sql("UPDATE users SET tier=NULL, credit_active_until=? WHERE id=?",
                  (datetime.utcnow().isoformat(), self.asesora))
        self._assert_sin_plan(self._ver_cartera())
        self._regalar_plan(force=True)
        self.assertEqual(self._ver_cartera().status_code, 200)

    def test_sin_el_plan_su_propia_cuenta_sigue_andando(self):
        self._sql("UPDATE users SET tier=NULL, credit_active_until=? WHERE id=?",
                  (datetime.utcnow().isoformat(), self.asesora))
        # Sin encabezado: lo suyo.
        self.assertEqual(self.http.get("/api/positions", headers=self._hdr()).status_code, 200)
        # /api/auth ignora el encabezado: la pantalla se entera de que ya no es
        # asesora aunque le quede el cliente guardado (y lo suelta, AuthContext).
        r = self.http.get("/api/auth/me", headers=self._hdr(self.cliente))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["tier"], "free")

    def test_sin_vinculo_sigue_diciendo_sin_acceso(self):
        # Con el plan y sin vínculo, el mensaje no cambia: no es un problema de plan.
        r = self.http.get("/api/positions", headers=self._hdr(self.admin))
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json().get("detail"), "Sin acceso a ese cliente")


if __name__ == "__main__":
    unittest.main()
