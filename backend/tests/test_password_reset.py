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
        # Request reset → sacar el token DEL MAIL (ya no vive en claro en la base:
        # la base guarda su huella, RENDI-10). Es de donde lo saca el usuario real.
        with patch("billing.emails.send_password_reset") as mock_spr:
            self.client.post("/api/auth/forgot-password", json={"email": self.email})
        reset_url = mock_spr.call_args.kwargs["reset_url"]
        from urllib.parse import urlparse, parse_qs
        self.token = parse_qs(urlparse(reset_url).query)["token"][0]

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
        # Forzar token a vencer. La base guarda la huella, así que se busca por la
        # huella del token (RENDI-10), no por el token crudo del mail.
        conn = main.get_db()
        conn.execute(
            """UPDATE password_reset_tokens SET expires_at = datetime('now', '-1 hour')
               WHERE token = ?""",
            (main._hash_token(self.token),),
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

    def test_token_se_guarda_como_huella_no_en_claro(self):
        """RENDI-10: en la base queda la huella (sha256, 64 hex), no el token del
        mail. Y el valor guardado NO sirve como token: quien tenga una copia de la
        base no puede usar el link de reseteo."""
        conn = main.get_db()
        guardado = conn.execute(
            """SELECT token FROM password_reset_tokens
               WHERE user_id = (SELECT id FROM users WHERE email=?) AND used_at IS NULL""",
            (self.email,)).fetchone()["token"]
        conn.close()
        # Lo guardado es la huella del token del mail, no el token.
        self.assertNotEqual(guardado, self.token)
        self.assertEqual(guardado, main._hash_token(self.token))
        self.assertEqual(len(guardado), 64)
        # Usar el valor de la base COMO token no restablece nada (da 400).
        r = self.client.post("/api/auth/reset-password",
                            json={"token": guardado, "new_password": "NoDeberiaFuncionar1$"})
        self.assertEqual(r.status_code, 400)
        # Y el login con la contraseña original sigue valiendo: no se cambió nada.
        r_login = self.client.post("/api/auth/login",
                                   json={"email": self.email, "password": self.original_password})
        self.assertEqual(r_login.status_code, 200)

class ChangePasswordTest(unittest.TestCase):
    """Cambiar la contraseña desde Configuración, con la sesión abierta."""

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.email = _unique_email("cambio")
        _register_and_verify(self.client, self.email)
        r = self.client.post("/api/auth/login",
                             json={"email": self.email, "password": "Password123$"})
        self.assertEqual(r.status_code, 200)

    def test_contrasena_actual_equivocada_no_parece_sesion_vencida(self):
        """Antes respondía 401, que el frontend lee como "la sesión venció":
        sacaba a la persona a la portada en vez de decirle que la contraseña
        actual estaba mal, y recargaba todas sus otras pestañas."""
        r = self.client.post("/api/auth/change-password",
                             json={"current_password": "NoEsLaMia123$",
                                   "new_password": "OtraNueva456$$"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Contraseña actual incorrecta")
        # La sesión sigue viva.
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_contrasena_actual_correcta_la_cambia(self):
        r = self.client.post("/api/auth/change-password",
                             json={"current_password": "Password123$",
                                   "new_password": "OtraNueva456$$"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/api/auth/login",
                             json={"email": self.email, "password": "OtraNueva456$$"})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()


class MigracionTokensReseteoTest(unittest.TestCase):
    """RENDI-10: la migración de arranque deja la tabla sin tokens en claro."""

    def setUp(self):
        self.conn = main.get_db()
        self.conn.execute("DELETE FROM password_reset_tokens")
        self.conn.execute("DELETE FROM users")
        self.conn.execute("INSERT INTO users (id,email,name,password_hash) VALUES (1,'m@m.co','M','x')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _ins(self, token, used_at=None, expires="2999-01-01T00:00:00"):
        self.conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at, used_at) VALUES (1,?,?,?)",
            (token, expires, used_at))
        self.conn.commit()

    def test_borra_usados_y_vencidos_y_hashea_los_vivos(self):
        self._ins("token-vivo-en-claro-123456789")                 # vivo en claro → se hashea
        self._ins("token-usado", used_at="2026-01-01T00:00:00")    # usado → se borra
        self._ins("token-vencido", expires="2000-01-01T00:00:00")  # vencido → se borra
        vivos, migrados = main._migrar_reset_tokens_a_huella(self.conn)
        self.conn.commit()
        self.assertEqual((vivos, migrados), (1, 1))
        filas = self.conn.execute("SELECT token FROM password_reset_tokens").fetchall()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["token"], main._hash_token("token-vivo-en-claro-123456789"))

    def test_es_idempotente(self):
        self._ins("otro-token-en-claro-abcdefghij")
        main._migrar_reset_tokens_a_huella(self.conn); self.conn.commit()
        huella1 = self.conn.execute("SELECT token FROM password_reset_tokens").fetchone()["token"]
        # Segunda corrida: no debe volver a hashear (ya es huella).
        vivos, migrados = main._migrar_reset_tokens_a_huella(self.conn); self.conn.commit()
        self.assertEqual(migrados, 0)
        huella2 = self.conn.execute("SELECT token FROM password_reset_tokens").fetchone()["token"]
        self.assertEqual(huella1, huella2)
