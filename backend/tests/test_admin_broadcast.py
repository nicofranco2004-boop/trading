"""Tests del broadcast de email admin: POST /api/admin/email/broadcast + emails.send_custom.
Verifica auth, dry-run/targeting, test_to (mail de prueba sin tocar users), envío
mockeado, y la conversión texto→HTML + personalización de {nombre}."""
import unittest
import uuid
from unittest.mock import patch

import main
from billing import emails
from fastapi.testclient import TestClient


def _mk(conn, email, name=None, is_admin=0, verified=1, tier=None):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, email_verified, tier) "
        "VALUES (?, 'x', 1, ?, ?, ?, ?)",
        (email, is_admin, name, verified, tier),
    ).lastrowid


class SendCustomTest(unittest.TestCase):
    def test_body_to_html_paragraphs_and_links(self):
        h = emails._custom_body_to_html("Hola\n\nMirá https://rendi.finance ahora")
        self.assertEqual(h.count("<p "), 2)                       # dos párrafos
        self.assertIn('href="https://rendi.finance"', h)          # URL auto-linkeada

    def test_body_to_html_escapes(self):
        h = emails._custom_body_to_html("2 < 3 & <script>x")
        self.assertNotIn("<script>", h)                           # escapado
        self.assertIn("&lt;script&gt;", h)

    def test_personalizes_name(self):
        cap = {}
        def fake_send(to, subject, html, text, **kw):
            cap["subject"] = subject; cap["html"] = html; cap["text"] = text; return True
        with patch.object(emails, "_send", side_effect=fake_send):
            emails.send_custom(to="x@y.com", user_name="Juan",
                               subject="Hola {nombre}", body="Che {nombre}, mirá esto")
        self.assertEqual(cap["subject"], "Hola Juan")
        self.assertIn("Che Juan", cap["text"])
        self.assertIn("Che Juan", cap["html"])

    def test_missing_name_blank(self):
        cap = {}
        with patch.object(emails, "_send", side_effect=lambda to, s, h, t, **k: cap.update(s=s) or True):
            emails.send_custom(to="x@y.com", user_name="", subject="Hola {nombre}", body="hi")
        self.assertEqual(cap["s"], "Hola")                        # sin nombre → placeholder vacío


class BroadcastEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        conn = main.get_db()
        self.admin = _mk(conn, f"adm-{self.tag}@rendi.test", is_admin=1)
        self.u_pro = _mk(conn, f"pro-{self.tag}@rendi.test", name="Pro Guy", tier="pro")
        self.u_free = _mk(conn, f"free-{self.tag}@rendi.test", name="Free Guy", tier=None)
        self.u_unverif = _mk(conn, f"unv-{self.tag}@rendi.test", verified=0)
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}

    def _post(self, **body):
        return self.client.post("/api/admin/email/broadcast", json=body, headers=self.h)

    def _mine(self, recipients):
        return [r for r in recipients if r["email"].endswith(f"-{self.tag}@rendi.test")]

    def test_requires_admin(self):
        conn = main.get_db(); plain = _mk(conn, f"pl-{self.tag}@rendi.test"); conn.commit(); conn.close()
        r = self.client.post("/api/admin/email/broadcast", json={"subject": "a", "body": "b"},
                             headers={"Authorization": f"Bearer {main.create_token(plain)}"})
        self.assertEqual(r.status_code, 403)

    def test_dry_run_lists_verified_only(self):
        b = self._post(subject="Hola", body="cuerpo").json()
        self.assertTrue(b["dry_run"])
        emails_in = {r["email"] for r in self._mine(b["recipients"])}
        self.assertIn(f"pro-{self.tag}@rendi.test", emails_in)
        self.assertIn(f"free-{self.tag}@rendi.test", emails_in)
        self.assertNotIn(f"unv-{self.tag}@rendi.test", emails_in)   # no verificado excluido
        self.assertNotIn(f"adm-{self.tag}@rendi.test", emails_in)   # admin excluido

    def test_plan_filter(self):
        b = self._post(subject="Hola", body="cuerpo", plan="pro").json()
        mine = self._mine(b["recipients"])
        self.assertEqual({r["email"] for r in mine}, {f"pro-{self.tag}@rendi.test"})
        self.assertTrue(all(r["plan"] == "pro" for r in mine))

    def test_test_to_sends_one_and_skips_users(self):
        with patch.object(emails, "send_custom", return_value=True) as m:
            r = self._post(subject="S", body="B", test_to="me@rendi.test").json()
        self.assertTrue(r["test"])
        self.assertTrue(r["sent"])
        self.assertEqual(m.call_count, 1)                          # UN solo mail
        self.assertEqual(m.call_args.kwargs["to"], "me@rendi.test")

    def test_confirm_sends_to_targets(self):
        with patch.object(emails, "send_custom", return_value=True) as m:
            r = self._post(subject="S", body="B", confirm=True, plan="pro").json()
        self.assertFalse(r["dry_run"])
        self.assertGreaterEqual(r["sent_count"], 1)
        tos = [c.kwargs["to"] for c in m.call_args_list]
        self.assertIn(f"pro-{self.tag}@rendi.test", tos)

    def test_empty_subject_rejected(self):
        self.assertEqual(self._post(subject="  ", body="B").status_code, 400)

    def test_test_to_rejects_malformed(self):
        # el fix del review: regex real, no sólo "hay un @"
        self.assertEqual(self._post(subject="S", body="B", test_to="notanemail").status_code, 400)
        self.assertEqual(self._post(subject="S", body="B", test_to="a@b").status_code, 400)  # sin TLD

    def test_targeting_uses_effective_tier(self):
        # User stampeado 'pro' pero con crédito VENCIDO y sin sub authorized → el
        # resolver canónico (get_tier) lo trata como 'free'. Antes del fix (tier crudo)
        # habría caído bajo plan='pro'. Ancla: el pro genuino SÍ aparece (descarta que
        # la lista se haya truncado y falseado el negativo).
        conn = main.get_db()
        lapsed = _mk(conn, f"lapsed-{self.tag}@rendi.test", name="Lapsed", tier="pro")
        conn.execute("UPDATE users SET credit_active_until=? WHERE id=?",
                     ("2000-01-01T00:00:00", lapsed))
        conn.commit(); conn.close()
        pro = {r["email"] for r in self._post(subject="H", body="c", plan="pro").json()["recipients"]}
        self.assertIn(f"pro-{self.tag}@rendi.test", pro)             # pro genuino (ancla)
        self.assertNotIn(f"lapsed-{self.tag}@rendi.test", pro)       # pro vencido NO cuenta como pro

    def test_dedup_skips_already_sent_on_resend(self):
        # Reintentar el MISMO contenido no re-mailea a quien ya recibió (send-log).
        body = f"cuerpo unico {self.tag}"   # contenido fresco → content_hash nuevo
        with patch.object(emails, "send_custom", return_value=True):
            r1 = self._post(subject="S", body=body, confirm=True, plan="pro").json()
        self.assertIn(f"pro-{self.tag}@rendi.test", {x["email"] for x in r1["sent"]})
        # 2do envío idéntico → mi user ya está logueado → skipped, NO se re-llama send_custom
        with patch.object(emails, "send_custom", return_value=True) as m2:
            r2 = self._post(subject="S", body=body, confirm=True, plan="pro").json()
        self.assertNotIn(f"pro-{self.tag}@rendi.test",
                         [c.kwargs["to"] for c in m2.call_args_list])
        self.assertIn(f"pro-{self.tag}@rendi.test", {x["email"] for x in r2["skipped"]})

    def test_dedup_different_content_resends(self):
        # Cambiar el texto = otro content_hash = se manda de nuevo (no lo bloquea el log).
        with patch.object(emails, "send_custom", return_value=True):
            self._post(subject="S", body=f"v1 {self.tag}", confirm=True, plan="pro").json()
        with patch.object(emails, "send_custom", return_value=True) as m2:
            r2 = self._post(subject="S", body=f"v2 {self.tag}", confirm=True, plan="pro").json()
        self.assertIn(f"pro-{self.tag}@rendi.test", {x["email"] for x in r2["sent"]})
        self.assertIn(f"pro-{self.tag}@rendi.test", [c.kwargs["to"] for c in m2.call_args_list])


if __name__ == "__main__":
    unittest.main()
