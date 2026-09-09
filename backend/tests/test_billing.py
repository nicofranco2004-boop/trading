"""Tests para los endpoints de billing — sin tocar la API real del procesador.

Mockeamos `billing.rebill.create_payment_link` / `cancel_subscription` y
verificamos que nuestro flow (DB + tier transitions) funcione.

⚠️ ESTOS TESTS MOCKEABAN `billing.mercadopago`. El procesador se migró a Rebill y
los endpoints dejaron de llamar a MP, así que el mock caía en el vacío: el request
llegaba al `rebill.create_payment_link` de verdad, moría con
"REBILL_PLAN_ID_PRO_MONTHLY no configurada en Railway" y el test veía un 502. O
sea: subscribe y cancel —dos endpoints de PLATA— se quedaron sin una sola prueba
que los ejerciera, y el rojo que lo avisaba estaba mezclado con otros 26."""
import unittest
import uuid
import json
from unittest.mock import patch

import main


def _new_user(conn, email_prefix="bill", is_admin=0):
    email = f"{email_prefix}-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?, 'x', 1, ?)",
        (email, is_admin),
    )
    return cur.lastrowid, email


class BillingSubscribeTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid, self.email = _new_user(conn)
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _link_rebill(self, link_id="mock-link-123"):
        """Respuesta de `rebill.create_payment_link`: {id, url} (billing/rebill.py:129).

        El host TIENE que ser uno de la allowlist de main.py (`_ALLOWED_PAYMENT_HOSTS`):
        si no, el endpoint devuelve 502 a propósito — es el guard anti-phishing por si
        la respuesta del procesador viniera tampereada."""
        return {"id": link_id, "url": f"https://checkout.rebill.com/{link_id}"}

    def test_subscribe_crea_el_payment_link_y_lo_guarda(self):
        with patch("billing.rebill.create_payment_link") as mock_create:
            mock_create.return_value = self._link_rebill("test-link-1")
            r = self.client.post(
                "/api/billing/subscribe",
                json={"period": "monthly"},
                headers=self.headers,
            )
            self.assertEqual(r.status_code, 200, r.text)
            data = r.json()
            self.assertEqual(data["subscription_id"], "test-link-1")
            self.assertIn("rebill.com", data["init_point"])

            mock_create.assert_called_once()
            kwargs = mock_create.call_args.kwargs
            self.assertEqual(kwargs["user_id"], self.uid)
            self.assertEqual(kwargs["user_email"], self.email)
            self.assertEqual(kwargs["period"], "monthly")
            self.assertEqual(kwargs["plan"], "pro")     # default por back-compat

        conn = main.get_db()
        row = conn.execute(
            "SELECT status, period, amount_ars, init_point, external_reference "
            "  FROM subscriptions WHERE user_id=?",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["period"], "monthly")
        self.assertEqual(row["init_point"], "https://checkout.rebill.com/test-link-1")
        self.assertEqual(row["external_reference"], f"rendi-{self.uid}-pro-monthly")
        # El importe lo fija el PLAN en el dashboard de Rebill, no nosotros: la fila
        # nace en 0 y la completa el webhook cuando el cobro ocurre. Con MP el monto
        # venía en la respuesta del preapproval y este test esperaba 12100.
        self.assertEqual(row["amount_ars"], 0)

    def test_subscribe_rechaza_una_url_que_no_es_de_rebill(self):
        """El guard anti-phishing: si el procesador devuelve otro dominio, 502."""
        with patch("billing.rebill.create_payment_link") as mock_create:
            mock_create.return_value = {"id": "x", "url": "https://evil.example.com/x"}
            r = self.client.post("/api/billing/subscribe",
                                 json={"period": "monthly"}, headers=self.headers)
        self.assertEqual(r.status_code, 502)
        conn = main.get_db()
        n = conn.execute("SELECT COUNT(*) c FROM subscriptions WHERE user_id=?",
                         (self.uid,)).fetchone()["c"]
        conn.close()
        self.assertEqual(n, 0, "no debe quedar una sub apuntando a un dominio ajeno")

    def test_subscribe_repetido_crea_OTRO_link_no_reusa_la_pending(self):
        """⚠️ CAMBIO DE COMPORTAMIENTO, no un bug de este test.

        Con Mercado Pago, un segundo POST sobre una sub `pending` devolvía el MISMO
        init_point con `reused: True` para que la persona terminara de pagar. El
        endpoint de Rebill no tiene esa rama: cada llamada crea un payment link
        nuevo y devuelve `reused: False` fijo (main.py:26874). Lo único que frena la
        acumulación es el rate limit de 5/600s, y la `x-idempotency-key` NO ayuda
        porque lleva un `uuid4()` adentro (billing/rebill.py:165), así que nunca hay
        dos llamadas con la misma clave.

        Este test fija lo que el código hace HOY. Si se decide volver a reusar la
        pending, tiene que fallar y avisar."""
        with patch("billing.rebill.create_payment_link") as mock_create:
            mock_create.side_effect = [self._link_rebill("link-a"), self._link_rebill("link-b")]
            r1 = self.client.post("/api/billing/subscribe", json={"period": "monthly"},
                                  headers=self.headers)
            r2 = self.client.post("/api/billing/subscribe", json={"period": "monthly"},
                                  headers=self.headers)
            self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertFalse(r2.json()["reused"])
        self.assertNotEqual(r1.json()["init_point"], r2.json()["init_point"])
        conn = main.get_db()
        n = conn.execute("SELECT COUNT(*) c FROM subscriptions WHERE user_id=? AND status='pending'",
                         (self.uid,)).fetchone()["c"]
        conn.close()
        self.assertEqual(n, 2, "quedan DOS pending por el mismo plan")

    def test_subscribe_rejects_when_already_authorized(self):
        """Si ya tenés una sub authorized, 409 (conflict)."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, 'existing-sub', 'rendi-x-monthly', 'monthly', 'authorized', 12100)""",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        r = self.client.post("/api/billing/subscribe", json={"period": "monthly"}, headers=self.headers)
        self.assertEqual(r.status_code, 409)

    def test_subscribe_invalid_period_400(self):
        r = self.client.post("/api/billing/subscribe", json={"period": "weekly"}, headers=self.headers)
        self.assertEqual(r.status_code, 422)  # pydantic validation

    def test_subscribe_requires_auth(self):
        r = self.client.post("/api/billing/subscribe", json={"period": "monthly"})
        self.assertIn(r.status_code, (401, 403))


class BillingCancelTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid, _ = _new_user(conn)
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _add_authorized_sub(self, sub_id="active-sub-1"):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'authorized', 12100)""",
            (self.uid, sub_id),
        )
        conn.commit()
        conn.close()

    def test_cancel_marks_subscription_cancelled(self):
        self._add_authorized_sub("to-cancel-1")
        with patch("billing.rebill.cancel_subscription") as mock_cancel:
            # Rebill devuelve el subscription object; `nextChargeDate` es la fecha
            # hasta la que la persona conserva el tier (main.py:27633).
            mock_cancel.return_value = {"id": "to-cancel-1", "status": "cancelled",
                                        "nextChargeDate": "2026-10-01"}
            r = self.client.post("/api/billing/cancel", headers=self.headers)
            self.assertEqual(r.status_code, 200, r.text)
            mock_cancel.assert_called_once_with("to-cancel-1")

        conn = main.get_db()
        row = conn.execute(
            "SELECT status, cancelled_at FROM subscriptions WHERE mp_subscription_id='to-cancel-1'"
        ).fetchone()
        conn.close()
        self.assertEqual(row["status"], "cancelled")
        self.assertIsNotNone(row["cancelled_at"])

    def test_cancel_404_when_no_active_subscription(self):
        r = self.client.post("/api/billing/cancel", headers=self.headers)
        self.assertEqual(r.status_code, 404)


class BillingWebhookTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.sub_id = f"wh-sub-{uuid.uuid4().hex[:8]}"
        conn = main.get_db()
        self.uid, _ = _new_user(conn)
        # Pre-cargar una subscription pending
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, ?, ?, 'monthly', 'pending', 12100)""",
            (self.uid, self.sub_id, f"rendi-{self.uid}-monthly"),
        )
        conn.commit()
        conn.close()

    def test_webhook_preapproval_authorized_promotes_user_to_pro(self):
        """Cuando MP avisa que el preapproval fue authorized, el user pasa a tier='pro'."""
        with patch("billing.mercadopago.get_preapproval") as mock_get:
            mock_get.return_value = {
                "id": self.sub_id,
                "status": "authorized",
                "external_reference": f"rendi-{self.uid}-monthly",
                "auto_recurring": {"start_date": "2026-05-18T00:00:00.000Z"},
                "next_payment_date": "2026-06-18T00:00:00.000Z",
            }
            payload = {"id": "evt-1", "type": "preapproval", "data": {"id": self.sub_id}}
            r = self.client.post(
                "/api/billing/webhook",
                content=json.dumps(payload),
                headers={"content-type": "application/json"},
            )
            self.assertEqual(r.status_code, 200)

        # User ahora es Pro
        conn = main.get_db()
        u = conn.execute("SELECT tier FROM users WHERE id = ?", (self.uid,)).fetchone()
        sub = conn.execute(
            "SELECT status, current_period_end FROM subscriptions WHERE mp_subscription_id = ?",
            (self.sub_id,),
        ).fetchone()
        evt = conn.execute(
            "SELECT processed, user_id FROM billing_events WHERE mp_data_id = ? ORDER BY id DESC LIMIT 1",
            (self.sub_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(u["tier"], "pro")
        self.assertEqual(sub["status"], "authorized")
        self.assertEqual(sub["current_period_end"], "2026-06-18T00:00:00.000Z")
        self.assertEqual(evt["processed"], 1)
        self.assertEqual(evt["user_id"], self.uid)

    def test_webhook_logs_all_events_for_audit(self):
        """Aunque el evento sea desconocido, queda en billing_events."""
        payload = {"id": "evt-unknown", "type": "merchant_order", "data": {"id": "999"}}
        r = self.client.post(
            "/api/billing/webhook",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(r.status_code, 200)
        conn = main.get_db()
        row = conn.execute(
            "SELECT mp_event_type FROM billing_events WHERE mp_event_id='evt-unknown'"
        ).fetchone()
        conn.close()
        self.assertEqual(row["mp_event_type"], "merchant_order")

    def test_webhook_handles_non_json_body_gracefully(self):
        r = self.client.post(
            "/api/billing/webhook",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(r.status_code, 400)


class BillingStatusTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid, _ = _new_user(conn)
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_status_returns_false_when_no_subscription(self):
        r = self.client.get("/api/billing/status", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["has_subscription"], False)

    def test_status_returns_active_subscription_details(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, next_charge_date)
               VALUES (?, 'sub-status-1', 'rendi-x-monthly', 'monthly', 'authorized',
                       12100, '2026-06-18')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/billing/status", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["has_subscription"])
        self.assertEqual(data["status"], "authorized")
        self.assertEqual(data["period"], "monthly")
        self.assertEqual(data["amount_ars"], 12100)
        self.assertEqual(data["next_charge_date"], "2026-06-18")


if __name__ == "__main__":
    unittest.main()
