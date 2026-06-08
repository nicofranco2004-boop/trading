"""Guarda anti-envío de emails en tests / dominios de prueba.

Regresión: los tests de auth/verify crean usuarios reset-*/verify-*@rendi.test y,
como main.py hace load_dotenv de backend/.env (con RESEND_API_KEY), la suite
mandaba alertas de "nuevo usuario" REALES al inbox del fundador. La guarda corta
el envío bajo pytest y hacia direcciones de dominio reservado.

Corre con: cd backend && python3 -m pytest tests/test_email_guard.py
"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from billing import emails


class EmailGuardTest(unittest.TestCase):
    def test_is_test_address(self):
        for a in ("reset-abc@rendi.test", "verify-x@rendi.test", "a@b.example",
                  "x@y.invalid", "z@w.localhost"):
            self.assertTrue(emails._is_test_address(a), a)
        for a in ("nicofranco2004@gmail.com", "user@rendi.finance", "a@b.com"):
            self.assertFalse(emails._is_test_address(a), a)

    def test_running_under_pytest_true(self):
        self.assertTrue(emails._running_under_pytest())

    def test_send_no_network_under_pytest(self):
        # Forzamos provider configurado para probar que la guarda corta ANTES
        # de tocar la red (httpx). Destinatario REAL → solo la guarda de pytest.
        with patch.object(emails, "_api_key", return_value="re_fake"), \
             patch("httpx.post") as mock_post:
            ok = emails._send("real@gmail.com", "Asunto", "<p>hi</p>", "hi")
        self.assertFalse(ok)
        self.assertFalse(mock_post.called, "no debe tocar la red bajo pytest")

    def test_send_skips_test_recipient(self):
        with patch.object(emails, "_api_key", return_value="re_fake"), \
             patch("httpx.post") as mock_post:
            ok = emails._send("reset-abc@rendi.test", "Asunto", "<p>hi</p>", "hi")
        self.assertFalse(ok)
        self.assertFalse(mock_post.called)

    def test_signup_admin_skips_test_user(self):
        # `to` (admin) es real, pero el usuario nuevo es de test → ni llama _send.
        with patch.object(emails, "_send") as mock_send:
            ok = emails.send_new_signup_admin(
                to="nicofranco2004@gmail.com",
                new_user_email="verify-x@rendi.test",
                new_user_name=None, count=1)
        self.assertFalse(ok)
        self.assertFalse(mock_send.called)


if __name__ == "__main__":
    unittest.main()
