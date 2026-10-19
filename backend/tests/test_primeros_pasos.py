"""GET /api/primeros-pasos: lo que la lista de primeros pasos de Inicio no puede
saber desde el navegador en el que está abierta (2026-10-19).

Todo por HTTP y con la sesión del usuario, como lo hace la app:
- «Agregá Rendi a tu celular» se tilda con `users.app_instalada_at`, que
  escribe POST /api/primeros-pasos/instalada cuando el celular abre Rendi desde
  el ícono. Vale mirando desde la compu.
- «Activá las notificaciones»: algún dispositivo suscripto.
- «Armá tu primera alerta»: alguna alerta.
- resumen_activo: para no ofrecer el resumen a quien ya lo tiene.

Corre con: cd backend && python3 -m pytest tests/test_primeros_pasos.py
"""
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


def setUpModule():
    global _rl
    _rl = patch("main._check_rate_limit")
    _rl.start()


def tearDownModule():
    _rl.stop()


class PrimerosPasos(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        try:
            self.uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified) "
                "VALUES (?, 'x', 1, 1)", (f"pp-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        finally:
            conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def pasos(self):
        r = self.client.get("/api/primeros-pasos", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_cuenta_nueva_no_tiene_nada(self):
        self.assertEqual(self.pasos(), {
            "app_instalada": False, "dispositivos_push": 0, "alertas": 0, "resumen_activo": False})

    def test_abrir_desde_el_icono_tilda_instalar(self):
        """El celular avisa con POST /api/primeros-pasos/instalada (utils/instalarApp.js,
        al arrancar la sesión). Guarda la PRIMERA vez y repetirlo no la pisa."""
        r = self.client.post("/api/primeros-pasos/instalada", json={}, headers=self.h)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertTrue(self.pasos()["app_instalada"])
        primera = self._q("SELECT app_instalada_at FROM users WHERE id=?", (self.uid,))[0][0]
        self.assertTrue(primera)
        self.client.post("/api/primeros-pasos/instalada", json={}, headers=self.h)
        self.assertEqual(self._q("SELECT app_instalada_at FROM users WHERE id=?", (self.uid,))[0][0], primera)

    def test_la_medicion_de_uso_ya_no_decide_el_paso(self):
        """Antes salía de uso_diario: se poda a los 13 meses y sólo viaja si la
        persona tocó la pantalla (auditoría 2026-10-19). Ahora es otra cosa."""
        self.client.post("/api/uso/eventos",
                         json={"eventos": {"vista:app_abierta_instalada": 1}}, headers=self.h)
        self.assertFalse(self.pasos()["app_instalada"])

    def test_instalada_sin_sesion_no_escribe(self):
        self.assertEqual(self.client.post("/api/primeros-pasos/instalada", json={}).status_code, 401)

    def test_suscribir_un_dispositivo_tilda_notificaciones(self):
        r = self.client.post("/api/push/subscribe", headers=self.h, json={
            "endpoint": f"https://push.example/{uuid.uuid4().hex}", "p256dh": "p", "auth": "a",
            "user_agent": "Mozilla/5.0 (iPhone)"})
        self.assertIn(r.status_code, (200, 201), r.text)
        self.assertEqual(self.pasos()["dispositivos_push"], 1)
        # /api/push/status cuenta con la MISMA función: no pueden discrepar.
        st = self.client.get("/api/push/status", headers=self.h).json()
        self.assertEqual(st["subscribed_devices"], 1)

    def test_crear_una_alerta_tilda_el_paso(self):
        r = self.client.post("/api/alerts", headers=self.h, json={
            "kind": "price_target", "scope": "ticker", "symbol": "AAPL",
            "direction": "above", "threshold": 999, "currency": "USD",
            "channel": "both", "repeat": "once"})
        self.assertIn(r.status_code, (200, 201), r.text)
        self.assertEqual(self.pasos()["alertas"], 1)

    def test_prender_el_resumen(self):
        r = self.client.patch("/api/market-brief/prefs", json={"enabled": True}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.pasos()["resumen_activo"])

    def test_sin_sesion_no_responde(self):
        self.assertEqual(self.client.get("/api/primeros-pasos").status_code, 401)

    def _q(self, sql, params=()):
        conn = main.get_db()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
