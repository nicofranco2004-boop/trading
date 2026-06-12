"""Email al admin en cada CAMBIO DE PLAN (free/plus/pro).

Cubre la lógica de decisión + composición de emails.send_plan_change_admin
(idempotencia old==new, guard de dominio test, ADMIN_NOTIFY_EMAIL, normalización
de tiers, escape de HTML, monto, origen) y el helper main._notify_plan_change
(resuelve email del user y delega; best-effort, no crashea).

El transporte (_send) se mockea para no pegar a la red y capturar el contenido.

Corre con: cd backend && python3 -m pytest tests/test_plan_change_email.py
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from billing import emails  # noqa: E402


class SendPlanChangeAdminTest(unittest.TestCase):
    """Unit tests de emails.send_plan_change_admin (decisión + composición)."""

    def _call(self, *, env_admin="admin@rendi.finance", **kwargs):
        """Llama la función con _send mockeado. Devuelve (ret, send_mock)."""
        send_mock = MagicMock(return_value=True)
        env = dict(os.environ)
        if env_admin is None:
            env.pop("ADMIN_NOTIFY_EMAIL", None)
        else:
            env["ADMIN_NOTIFY_EMAIL"] = env_admin
        with patch.object(emails, "_send", send_mock), \
             patch.dict(os.environ, env, clear=True):
            ret = emails.send_plan_change_admin(**kwargs)
        return ret, send_mock

    # ── decisión ────────────────────────────────────────────────────────────
    def test_sends_on_real_change(self):
        ret, send = self._call(user_email="buyer@gmail.com", old_plan="free",
                               new_plan="pro", source="payment")
        self.assertTrue(ret)
        self.assertEqual(send.call_count, 1)
        # to = ADMIN_NOTIFY_EMAIL, subject con la transición y el email
        args, kwargs = send.call_args
        to, subject = args[0], args[1]
        self.assertEqual(to, "admin@rendi.finance")
        self.assertIn("Free", subject)
        self.assertIn("Pro", subject)
        self.assertIn("buyer@gmail.com", subject)

    def test_no_send_when_same_tier(self):
        # pro→pro (ej. cambio solo de período, o reintento de webhook) → NO manda
        ret, send = self._call(user_email="buyer@gmail.com", old_plan="pro",
                               new_plan="pro", source="plan_change")
        self.assertFalse(ret)
        send.assert_not_called()

    def test_webhook_retry_idempotent(self):
        # 1er evento free→pro manda; el reintento ve old=pro==new → no reenvía
        ret1, send1 = self._call(user_email="b@gmail.com", old_plan="free",
                                new_plan="pro", source="payment")
        ret2, send2 = self._call(user_email="b@gmail.com", old_plan="pro",
                                new_plan="pro", source="payment")
        self.assertTrue(ret1)
        self.assertFalse(ret2)
        send2.assert_not_called()

    def test_no_send_for_test_domain_user(self):
        ret, send = self._call(user_email="verify-123@rendi.test", old_plan="free",
                               new_plan="pro", source="payment")
        self.assertFalse(ret)
        send.assert_not_called()

    def test_falls_back_to_default_admin(self):
        # Sin ADMIN_NOTIFY_EMAIL en el env, cae al default soporte@rendi.finance
        # (mismo default que el aviso de signup) y SÍ manda. Antes quedaba con
        # destinatario vacío → no salía nunca (bug del upgrade que no llegaba).
        ret, send = self._call(env_admin=None, user_email="buyer@gmail.com",
                               old_plan="free", new_plan="pro", source="payment")
        self.assertTrue(ret)
        self.assertEqual(send.call_args[0][0], "soporte@rendi.finance")

    # ── normalización de tiers ───────────────────────────────────────────────
    def test_none_normalizes_to_free(self):
        # downgrade a free (new_plan=None) sí manda y muestra "Pro → Free"
        ret, send = self._call(user_email="x@gmail.com", old_plan="pro",
                               new_plan=None, source="credit_expired")
        self.assertTrue(ret)
        subject = send.call_args[0][1]
        self.assertIn("Pro", subject)
        self.assertIn("Free", subject)

    def test_free_to_plus(self):
        ret, send = self._call(user_email="x@gmail.com", old_plan=None,
                               new_plan="plus", source="payment")
        self.assertTrue(ret)
        self.assertIn("Plus", send.call_args[0][1])

    # ── contenido ─────────────────────────────────────────────────────────────
    def test_html_escaped(self):
        ret, send = self._call(user_email="a<script>@gmail.com", old_plan="free",
                               new_plan="pro", source="payment")
        self.assertTrue(ret)
        html_body = send.call_args[0][2]
        self.assertNotIn("<script>", html_body)
        self.assertIn("&lt;script&gt;", html_body)

    def test_amount_included(self):
        ret, send = self._call(user_email="x@gmail.com", old_plan="free",
                               new_plan="pro", source="payment", amount_usd=9.0)
        html_body, text = send.call_args[0][2], send.call_args[0][3]
        self.assertIn("USD 9.00", html_body)
        self.assertIn("USD 9.00", text)

    def test_source_label_humanized(self):
        ret, send = self._call(user_email="x@gmail.com", old_plan="free",
                               new_plan="pro", source="payment")
        self.assertIn("Pago (Rebill)", send.call_args[0][2])

    def test_from_is_noreply(self):
        ret, send = self._call(user_email="x@gmail.com", old_plan="free",
                               new_plan="pro", source="payment")
        # from_addr se pasa como kwarg
        self.assertIn("no_reply@rendi.finance", send.call_args.kwargs.get("from_addr", ""))


class NotifyPlanChangeHelperTest(unittest.TestCase):
    """main._notify_plan_change: resuelve email del user y delega; no crashea."""

    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def setUp(self):
        self.conn = self.main.get_db()
        try:
            self.conn.execute("DELETE FROM users")
        except Exception:
            pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, name, tier) VALUES (?,?,1,?,?)",
            ("payer@gmail.com", "x", "Pay Er", "free"))
        self.uid = cur.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_resolves_email_and_delegates(self):
        with patch.object(self.main, "_notify_plan_change", wraps=self.main._notify_plan_change), \
             patch("billing.emails.send_plan_change_admin", MagicMock(return_value=True)) as spc:
            self.main._notify_plan_change(self.conn, self.uid, "free", "pro", "payment", amount_usd=9.0)
            self.assertEqual(spc.call_count, 1)
            kw = spc.call_args.kwargs
            self.assertEqual(kw["user_email"], "payer@gmail.com")
            self.assertEqual(kw["user_name"], "Pay Er")
            self.assertEqual(kw["old_plan"], "free")
            self.assertEqual(kw["new_plan"], "pro")
            self.assertEqual(kw["source"], "payment")
            self.assertEqual(kw["amount_usd"], 9.0)

    def test_unknown_uid_no_crash_no_send(self):
        with patch("billing.emails.send_plan_change_admin", MagicMock()) as spc:
            self.main._notify_plan_change(self.conn, 999999, "free", "pro", "payment")
            spc.assert_not_called()

    def test_never_raises(self):
        # Si emails.send_plan_change_admin explota, el helper lo traga.
        with patch("billing.emails.send_plan_change_admin", side_effect=Exception("boom")):
            try:
                self.main._notify_plan_change(self.conn, self.uid, "free", "pro", "payment")
            except Exception:
                self.fail("_notify_plan_change no debe propagar excepciones")


class SendGiftedPlanTest(unittest.TestCase):
    """emails.send_gifted_plan: mail al USUARIO cuando un admin le regala el plan."""

    def _call(self, **kwargs):
        send_mock = MagicMock(return_value=True)
        with patch.object(emails, "_send", send_mock):
            ret = emails.send_gifted_plan(**kwargs)
        return ret, send_mock

    def test_sends_to_user(self):
        ret, send = self._call(to="winner@gmail.com", user_name="Juan", plan="pro",
                               days=30, active_until="2026-07-15T00:00:00")
        self.assertTrue(ret)
        self.assertEqual(send.call_count, 1)
        to, subject, html_body = send.call_args[0][0], send.call_args[0][1], send.call_args[0][2]
        self.assertEqual(to, "winner@gmail.com")            # va al USUARIO, no al admin
        self.assertIn("Pro", subject)
        self.assertIn("Juan", html_body)
        self.assertIn("30", html_body)                       # días de regalo
        # from = soporte (el user puede responder)
        self.assertIn("soporte@rendi.finance", send.call_args.kwargs.get("from_addr", ""))

    def test_plus_label(self):
        ret, send = self._call(to="w@gmail.com", user_name="Ana", plan="plus",
                               days=15, active_until="2026-07-01T00:00:00")
        self.assertIn("Plus", send.call_args[0][1])

    def test_name_escaped(self):
        ret, send = self._call(to="w@gmail.com", user_name="<b>x</b>", plan="pro",
                               days=7, active_until=None)
        self.assertNotIn("<b>x</b>", send.call_args[0][2])
        self.assertIn("&lt;b&gt;", send.call_args[0][2])

    def test_no_name_no_crash(self):
        ret, send = self._call(to="anon@gmail.com", user_name=None, plan="pro",
                               days=7, active_until=None)
        self.assertTrue(ret)  # usa el local-part del email, no crashea

    def test_test_domain_not_sent(self):
        # Sin mock: el guard de _send (pytest + dominio de prueba) corta el envío.
        ret = emails.send_gifted_plan(to="x@rendi.test", user_name="T", plan="pro",
                                      days=30, active_until=None)
        self.assertFalse(ret)


if __name__ == "__main__":
    unittest.main()
