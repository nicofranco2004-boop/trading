"""Tests para el flow de verificación de email post-register.

Cubre:
  • Register de user nuevo NO devuelve token, marca email_verified=0
  • Register manda código de 6 dígitos
  • verify-email con código válido marca email_verified=1 + devuelve token
  • verify-email con código incorrecto / vencido / ya usado falla con 400
  • Login con email_verified=0 falla con 403 EMAIL_NOT_VERIFIED
  • Resend genera código nuevo + invalida previos
  • Admin signup salta verificación
"""
import unittest
import uuid
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch

import main


def _unique_email(prefix="verify"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@rendi.test"


# Rate limit deshabilitado para todos los tests — hacemos múltiples calls
# que normalmente rebotarían contra el cap por-IP de 5/5min.
def setUpModule():
    global _rate_limit_patcher
    _rate_limit_patcher = patch("main._check_rate_limit")
    _rate_limit_patcher.start()


def tearDownModule():
    _rate_limit_patcher.stop()


class RegisterEmailVerificationTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_register_sends_code_and_does_not_issue_token(self):
        email = _unique_email()
        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            r = self.client.post("/api/auth/register",
                                 json={"email": email, "password": "Password123$"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get("needs_verification"))
        self.assertEqual(data["email"], email)
        self.assertNotIn("token", data)

        # En DB: user existe con email_verified=0 y hay 1 código
        conn = main.get_db()
        u = conn.execute("SELECT email_verified FROM users WHERE email=?", (email,)).fetchone()
        codes = conn.execute(
            """SELECT code, used_at, expires_at FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchall()
        conn.close()
        self.assertEqual(u["email_verified"], 0)
        self.assertEqual(len(codes), 1)
        self.assertEqual(len(codes[0]["code"]), 6)
        self.assertIsNone(codes[0]["used_at"])

    def test_verify_email_with_valid_code_returns_token(self):
        email = _unique_email()
        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})

        # Leer el código real desde DB
        conn = main.get_db()
        code = conn.execute(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchone()["code"]
        conn.close()

        r = self.client.post("/api/auth/verify-email",
                            json={"email": email, "code": code})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("token", data)
        self.assertTrue(data["verified"])

        # User ahora verificado, código marcado como used
        conn = main.get_db()
        u = conn.execute("SELECT email_verified FROM users WHERE email=?", (email,)).fetchone()
        c = conn.execute(
            """SELECT used_at FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchone()
        conn.close()
        self.assertEqual(u["email_verified"], 1)
        self.assertIsNotNone(c["used_at"])

    def test_verify_email_with_wrong_code_fails(self):
        email = _unique_email()
        with patch("billing.emails._send"):
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})
        r = self.client.post("/api/auth/verify-email",
                            json={"email": email, "code": "000000"})
        self.assertEqual(r.status_code, 400)

    def test_verify_email_with_used_code_fails(self):
        """Una vez usado, el código no se puede reusar."""
        email = _unique_email()
        with patch("billing.emails._send"):
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})
        conn = main.get_db()
        code = conn.execute(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchone()["code"]
        conn.close()

        # Primer verify OK
        r1 = self.client.post("/api/auth/verify-email",
                             json={"email": email, "code": code})
        self.assertEqual(r1.status_code, 200)
        # Segundo verify con mismo código → falla
        r2 = self.client.post("/api/auth/verify-email",
                             json={"email": email, "code": code})
        self.assertEqual(r2.status_code, 400)

    def test_verify_email_with_expired_code_fails(self):
        email = _unique_email()
        with patch("billing.emails._send"):
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})
        # Forzamos el código a estar vencido
        conn = main.get_db()
        conn.execute(
            """UPDATE email_verification_codes
               SET expires_at = datetime('now', '-1 hour')
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        )
        conn.commit()
        code = conn.execute(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchone()["code"]
        conn.close()

        r = self.client.post("/api/auth/verify-email",
                            json={"email": email, "code": code})
        self.assertEqual(r.status_code, 400)


class LoginVerificationGateTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_login_blocked_when_email_not_verified(self):
        email = _unique_email()
        with patch("billing.emails._send"):
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})
        # User no aprobó verificación todavía
        r = self.client.post("/api/auth/login",
                            json={"email": email, "password": "Password123$"})
        self.assertEqual(r.status_code, 403)
        # Detail tiene code 'EMAIL_NOT_VERIFIED'
        detail = r.json().get("detail", {})
        self.assertEqual(detail.get("code"), "EMAIL_NOT_VERIFIED")

    def test_login_works_after_verifying(self):
        email = _unique_email()
        with patch("billing.emails._send"):
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})
        conn = main.get_db()
        # Approve + get code
        conn.execute("UPDATE users SET approved=1 WHERE email=?", (email,))
        code = conn.execute(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchone()["code"]
        conn.commit()
        conn.close()
        # Verify
        self.client.post("/api/auth/verify-email",
                        json={"email": email, "code": code})
        # Login OK
        r = self.client.post("/api/auth/login",
                            json={"email": email, "password": "Password123$"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json())


class ResendVerificationTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_resend_generates_new_code_invalidates_old(self):
        email = _unique_email()
        with patch("billing.emails._send"):
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})
        conn = main.get_db()
        old_code = conn.execute(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchone()["code"]
        conn.close()

        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            # Sleep para evitar rate limit cooldown — usamos mock del check.
            with patch("main._check_rate_limit"):
                r = self.client.post("/api/auth/resend-verification",
                                    json={"email": email})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(mock_send.called)

        # Old code marked used; new code exists
        conn = main.get_db()
        codes = conn.execute(
            """SELECT code, used_at FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)
               ORDER BY id""",
            (email,),
        ).fetchall()
        conn.close()
        self.assertGreaterEqual(len(codes), 2)
        # Primero está usado
        self.assertEqual(codes[0]["code"], old_code)
        self.assertIsNotNone(codes[0]["used_at"])
        # Último no
        self.assertIsNone(codes[-1]["used_at"])
        self.assertNotEqual(codes[-1]["code"], old_code)

    def test_resend_for_already_verified_user_is_silent_ok(self):
        """Idempotente: no leakea que el user ya verificó."""
        email = _unique_email()
        with patch("billing.emails._send"):
            self.client.post("/api/auth/register",
                            json={"email": email, "password": "Password123$"})
        # Marco como verificado
        conn = main.get_db()
        conn.execute("UPDATE users SET email_verified=1 WHERE email=?", (email,))
        conn.commit()
        conn.close()

        with patch("billing.emails._send") as mock_send, \
             patch("main._check_rate_limit"):
            r = self.client.post("/api/auth/resend-verification",
                                json={"email": email})
            self.assertEqual(r.status_code, 200)
            # NO debe mandar email (ya está verificado)
            self.assertFalse(mock_send.called)


class AdminSignupBypassTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_admin_signup_skips_verification(self):
        """Admin emails (hash matches ADMIN_EMAIL_HASH) saltean el flow.
        Como no podemos saber el admin email en tests, sólo validamos que
        users existentes con email_verified=1 NO necesitan verificación."""
        # Setup: crear un user manualmente con email_verified=1
        email = _unique_email("admin-test")
        conn = main.get_db()
        from main import pwd_ctx
        h = pwd_ctx.hash("Password123$")
        conn.execute(
            """INSERT INTO users (email, password_hash, approved, email_verified)
               VALUES (?, ?, 1, 1)""",
            (email, h),
        )
        conn.commit()
        conn.close()
        # Login OK directo
        r = self.client.post("/api/auth/login",
                            json={"email": email, "password": "Password123$"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json())


if __name__ == "__main__":
    unittest.main()
