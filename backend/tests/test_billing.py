"""Tests para los endpoints de billing — sin tocar la API real de MP.

Mockeamos `billing.mercadopago.create_preapproval` / cancel / get y
verificamos que nuestro flow (DB + tier transitions) funcione."""
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

    def _mock_preapproval(self, sub_id="mock-sub-123"):
        """Helper: mock que devuelve un preapproval payload simulado de MP."""
        return {
            "id": sub_id,
            "init_point": f"https://mercadopago.com/checkout/{sub_id}",
            "status": "pending",
            "auto_recurring": {"transaction_amount": 12100, "currency_id": "ARS"},
        }

    def test_subscribe_creates_preapproval_and_saves_to_db(self):
        with patch("billing.mercadopago.create_preapproval") as mock_create:
            mock_create.return_value = self._mock_preapproval("test-sub-1")
            r = self.client.post(
                "/api/billing/subscribe",
                json={"period": "monthly"},
                headers=self.headers,
            )
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["subscription_id"], "test-sub-1")
            self.assertIn("checkout", data["init_point"])

            mock_create.assert_called_once()
            # MP recibe email y period correctos
            call_kwargs = mock_create.call_args.kwargs
            self.assertEqual(call_kwargs["user_id"], self.uid)
            self.assertEqual(call_kwargs["user_email"], self.email)
            self.assertEqual(call_kwargs["period"], "monthly")

        # DB tiene la subscription en estado pending
        conn = main.get_db()
        row = conn.execute(
            "SELECT status, period, amount_ars FROM subscriptions WHERE user_id=?",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["period"], "monthly")
        self.assertEqual(row["amount_ars"], 12100)

    def test_subscribe_reuses_pending_subscription(self):
        """Si el user ya tiene una sub pending, no creamos duplicado — devolvemos
        el mismo init_point para que termine de pagar."""
        with patch("billing.mercadopago.create_preapproval") as mock_create:
            mock_create.return_value = self._mock_preapproval("test-sub-pending")
            # Primera llamada crea
            r1 = self.client.post("/api/billing/subscribe", json={"period": "monthly"}, headers=self.headers)
            # Segunda llamada reutiliza
            r2 = self.client.post("/api/billing/subscribe", json={"period": "monthly"}, headers=self.headers)
            self.assertEqual(r2.json()["reused"], True)
            self.assertEqual(r1.json()["init_point"], r2.json()["init_point"])
            # MP llamado UNA sola vez
            mock_create.assert_called_once()

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
        with patch("billing.mercadopago.cancel_preapproval") as mock_cancel:
            mock_cancel.return_value = {"id": "to-cancel-1", "status": "cancelled"}
            r = self.client.post("/api/billing/cancel", headers=self.headers)
            self.assertEqual(r.status_code, 200)
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
