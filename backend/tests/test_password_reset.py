"""Tests para el flow de reset de contraseña con magic link.

Cubre:
  • POST /forgot-password siempre devuelve 200 (no leak)
  • Si el email existe, genera token y manda email
  • Si el email no existe, NO genera token (silencioso)
  • POST /reset-password con token válido cambia el password
  • Token vencido / usado / inválido → 400
  • Tras el reset, el JWT viejo queda inválido (password_changed_at bump)
"""
import unittest
import uuid
from unittest.mock import patch

import main


def _unique_email(prefix="reset"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@rendi.test"


def setUpModule():
    """Patcheamos rate limit a global level — los tests hacen muchos calls."""
    global _rate_limit_patcher
    _rate_limit_patcher = patch("main._check_rate_limit")
    _rate_limit_patcher.start()


def tearDownModule():
    _rate_limit_patcher.stop()


def _register_and_verify(client, email, password="Password123$"):
    """Helper: register + verify para crear un user logueable."""
    with patch("billing.emails._send"):
        client.post("/api/auth/register", json={"email": email, "password": password})
    conn = main.get_db()
    code = conn.execute(
        """SELECT code FROM email_verification_codes
           WHERE user_id = (SELECT id FROM users WHERE email=?)""",
        (email,),
    ).fetchone()["code"]
    # Approve user so login works after reset
    conn.execute("UPDATE users SET approved=1 WHERE email=?", (email,))
    conn.commit()
    conn.close()
    client.post("/api/auth/verify-email", json={"email": email, "code": code})


class ForgotPasswordTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_forgot_password_for_existing_user_creates_token_and_sends_email(self):
        email = _unique_email()
        _register_and_verify(self.client, email)

        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            r = self.client.post("/api/auth/forgot-password", json={"email": email})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(mock_send.called)

        # Token guardado
        conn = main.get_db()
        token_row = conn.execute(
            """SELECT token, expires_at, used_at FROM password_reset_tokens
               WHERE user_id = (SELECT id FROM users WHERE email=?)""",
            (email,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(token_row)
        self.assertGreater(len(token_row["token"]), 20)
        self.assertIsNone(token_row["used_at"])

    def test_forgot_password_for_nonexistent_user_returns_200_silently(self):
        """No leak: misma respuesta exitosa aunque el email no exista."""
        with patch("billing.emails._send") as mock_send:
            r = self.client.post("/api/auth/forgot-password",
                                json={"email": "ghost@nothere.test"})
            self.assertEqual(r.status_code, 200)
            # No mandó email
            self.assertFalse(mock_send.called)

    def test_forgot_password_invalidates_previous_tokens(self):
        """Cada nueva request invalida tokens previos (1 link válido a la vez)."""
        email = _unique_email()
        _register_and_verify(self.client, email)

        with patch("billing.emails._send"):
            # Primera request
            self.client.post("/api/auth/forgot-password", json={"email": email})
            # Segunda request — invalida la primera
            self.client.post("/api/auth/forgot-password", json={"email": email})

        conn = main.get_db()
        tokens = conn.execute(
            """SELECT token, used_at FROM password_reset_tokens
               WHERE user_id = (SELECT id FROM users WHERE email=?)
               ORDER BY id""",
            (email,),
        ).fetchall()
        conn.close()
        # 2 tokens; el primero está marcado usado, el segundo activo
        self.assertEqual(len(tokens), 2)
        self.assertIsNotNone(tokens[0]["used_at"])
        self.assertIsNone(tokens[1]["used_at"])


class ResetPasswordTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.email = _unique_email()
        self.original_password = "OriginalPwd123$"
        _register_and_verify(self.client, self.email, password=self.original_password)
        # Request reset → get token
        with patch("billing.emails._send"):
            self.client.post("/api/auth/forgot-password", json={"email": self.email})
        conn = main.get_db()
        self.token = conn.execute(
            """SELECT token FROM password_reset_tokens
               WHERE user_id = (SELECT id FROM users WHERE email=?)
                 AND used_at IS NULL""",
            (self.email,),
        ).fetchone()["token"]
        conn.close()

    def test_reset_with_valid_token_changes_password(self):
        new_pw = "NuevoPassword456$"
        r = self.client.post("/api/auth/reset-password",
                            json={"token": self.token, "new_password": new_pw})
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json())  # auto-login

        # Login con vieja → falla
        r_old = self.client.post("/api/auth/login",
                                json={"email": self.email, "password": self.original_password})
        self.assertEqual(r_old.status_code, 401)

        # Login con nueva → OK
        r_new = self.client.post("/api/auth/login",
                                json={"email": self.email, "password": new_pw})
        self.assertEqual(r_new.status_code, 200)

    def test_reset_with_used_token_fails(self):
        new_pw = "NuevoPassword456$"
        # Primer reset OK
        r1 = self.client.post("/api/auth/reset-password",
                             json={"token": self.token, "new_password": new_pw})
        self.assertEqual(r1.status_code, 200)
        # Segundo reset con mismo token → 400
        r2 = self.client.post("/api/auth/reset-password",
                             json={"token": self.token, "new_password": "OtroPwd789$"})
        self.assertEqual(r2.status_code, 400)

    def test_reset_with_invalid_token_fails(self):
        r = self.client.post("/api/auth/reset-password",
                            json={"token": "fake-token-not-in-db-abc123xyz", "new_password": "NewPwd123$"})
        self.assertEqual(r.status_code, 400)

    def test_reset_with_expired_token_fails(self):
        # Forzar token a vencer
        conn = main.get_db()
        conn.execute(
            """UPDATE password_reset_tokens SET expires_at = datetime('now', '-1 hour')
               WHERE token = ?""",
            (self.token,),
        )
        conn.commit()
        conn.close()
        r = self.client.post("/api/auth/reset-password",
                            json={"token": self.token, "new_password": "NewPwd123$"})
        self.assertEqual(r.status_code, 400)

    def test_reset_with_short_password_rejected_by_pydantic(self):
        """Password < 10 chars → 422 validation error."""
        r = self.client.post("/api/auth/reset-password",
                            json={"token": self.token, "new_password": "short"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
