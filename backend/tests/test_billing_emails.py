"""Tests para los 5 emails transaccionales de billing.

Mockeamos billing.emails._send y verificamos que:
  • Cada evento dispara la función correcta
  • La idempotencia evita doble-envío
  • Los argumentos son correctos
"""
import unittest
import uuid
import json
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import main
from billing import emails, subscriptions as billing_subs


def _new_user(conn, name="Test User"):
    email = f"e-{uuid.uuid4().hex[:10]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, name, password_hash, approved) VALUES (?, ?, 'x', 1)",
        (email, name),
    )
    return cur.lastrowid, email


# ─── Welcome email ─────────────────────────────────────────────────────────

class WelcomeEmailTest(unittest.TestCase):
    def setUp(self):
        self.sub_id = f"sub-welcome-{uuid.uuid4().hex[:8]}"  # único por test run
        conn = main.get_db()
        self.uid, self.email = _new_user(conn, name="Nicolas")
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, ?, ?, 'monthly', 'pending', 12100)""",
            (self.uid, self.sub_id, f"rendi-{self.uid}-monthly"),
        )
        conn.commit()
        conn.close()

    def test_welcome_email_sent_on_first_authorized_event(self):
        """Cuando _process_preapproval_event lleva la sub a authorized, manda welcome."""
        with patch("billing.emails._send") as mock_send, \
             patch("billing.mercadopago.get_preapproval") as mp_get:
            mock_send.return_value = True
            mp_get.return_value = {
                "id": self.sub_id,
                "status": "authorized",
                "external_reference": f"rendi-{self.uid}-monthly",
                "next_payment_date": "2026-06-18",
            }
            conn = main.get_db()
            main._process_preapproval_event(conn, self.sub_id)
            conn.close()

            self.assertTrue(mock_send.called, "Debió enviar email")
            call_args = mock_send.call_args
            # Posicional: to, subject, html, text
            self.assertEqual(call_args[0][0], self.email)  # to
            self.assertIn("Bienvenido", call_args[0][1])   # subject

    def test_welcome_email_not_sent_twice(self):
        """Si welcome_email_sent_at ya tiene valor, no se reenvía."""
        conn = main.get_db()
        conn.execute(
            "UPDATE subscriptions SET welcome_email_sent_at=datetime('now') WHERE mp_subscription_id=?",
            (self.sub_id,),
        )
        conn.commit()
        conn.close()

        with patch("billing.emails._send") as mock_send, \
             patch("billing.mercadopago.get_preapproval") as mp_get:
            mp_get.return_value = {
                "id": self.sub_id,
                "status": "authorized",
                "external_reference": f"rendi-{self.uid}-monthly",
            }
            conn = main.get_db()
            main._process_preapproval_event(conn, self.sub_id)
            conn.close()
            self.assertFalse(mock_send.called)


# ─── Cancellation email ────────────────────────────────────────────────────

class CancellationEmailTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.sub_id = f"sub-cancel-{uuid.uuid4().hex[:8]}"
        conn = main.get_db()
        self.uid, self.email = _new_user(conn)
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, current_period_end)
               VALUES (?, ?, ?, 'monthly', 'authorized', 12100, '2026-06-18')""",
            (self.uid, self.sub_id, f"rendi-{self.uid}-monthly"),
        )
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_cancellation_triggers_email(self):
        with patch("billing.emails._send") as mock_send, \
             patch("billing.rebill.cancel_subscription") as rebill_cancel:
            mock_send.return_value = True
            rebill_cancel.return_value = {
                "id": self.sub_id,
                "status": "cancelled",
                "nextChargeDate": "2026-06-18",
            }
            r = self.client.post("/api/billing/cancel", headers=self.headers)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(mock_send.called)
            self.assertIn("Cancelación", mock_send.call_args[0][1])


# ─── Expiration reminder ───────────────────────────────────────────────────

class ExpirationReminderTest(unittest.TestCase):

    def _make_conn(self):
        """Conn mínima — replicamos schema relevante."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, email TEXT, name TEXT,
                is_admin INTEGER DEFAULT 0, tier TEXT
            );
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mp_subscription_id TEXT,
                external_reference TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL,
                amount_ars INTEGER NOT NULL,
                current_period_end TEXT,
                expiration_reminder_sent_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        return conn

    def test_reminder_sent_for_cancelled_sub_expiring_in_3_days(self):
        conn = self._make_conn()
        conn.execute("INSERT INTO users (id, email, name) VALUES (1, 'a@x.com', 'Ana')")
        period_end = (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%d")
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, current_period_end)
               VALUES (1, 'sub-x', 'rendi-1-monthly', 'monthly', 'cancelled', 12100, ?)""",
            (period_end,),
        )
        conn.commit()

        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            count = billing_subs._send_expiration_reminders(conn, days_before=3)
            self.assertEqual(count, 1)
            self.assertTrue(mock_send.called)
            self.assertIn("vence en", mock_send.call_args[0][1].lower())

    def test_reminder_not_resent_when_already_sent(self):
        conn = self._make_conn()
        conn.execute("INSERT INTO users (id, email, name) VALUES (1, 'a@x.com', 'Ana')")
        period_end = (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%d")
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, current_period_end,
                                          expiration_reminder_sent_at)
               VALUES (1, 'sub-x', 'rendi-1-monthly', 'monthly', 'cancelled', 12100, ?, datetime('now'))""",
            (period_end,),
        )
        conn.commit()

        with patch("billing.emails._send") as mock_send:
            count = billing_subs._send_expiration_reminders(conn, days_before=3)
            self.assertEqual(count, 0)
            self.assertFalse(mock_send.called)

    def test_reminder_not_sent_for_authorized_sub(self):
        """Subs activas (no canceladas) NO necesitan reminder — se renuevan auto."""
        conn = self._make_conn()
        conn.execute("INSERT INTO users (id, email, name) VALUES (1, 'a@x.com', 'Ana')")
        period_end = (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%d")
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, current_period_end)
               VALUES (1, 'sub-active', 'rendi-1-monthly', 'monthly', 'authorized', 12100, ?)""",
            (period_end,),
        )
        conn.commit()

        with patch("billing.emails._send") as mock_send:
            count = billing_subs._send_expiration_reminders(conn, days_before=3)
            self.assertEqual(count, 0)
            self.assertFalse(mock_send.called)


# ─── Email functions producen el output esperado ────────────────────────────

class EmailContentTest(unittest.TestCase):

    def test_welcome_email_contains_user_name_and_amount(self):
        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            emails.send_welcome_pro(
                to="x@y.com",
                user_name="Pedro",
                period="monthly",
                amount_ars=12100,
                next_charge_date="2026-06-18",
            )
            html = mock_send.call_args[0][2]
            text = mock_send.call_args[0][3]
            self.assertIn("Pedro", html)
            self.assertIn("12.100", html)
            self.assertIn("18/06/2026", html)
            self.assertIn("Pedro", text)

    def test_receipt_email_has_payment_id(self):
        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            emails.send_receipt(
                to="x@y.com",
                user_name="Pedro",
                amount_ars=12100,
                payment_date="2026-06-18",
                next_charge_date="2026-07-18",
                payment_id="PAY-12345",
            )
            html = mock_send.call_args[0][2]
            self.assertIn("PAY-12345", html)
            self.assertIn("18/07/2026", html)

    def test_payment_failed_has_urgency_marker(self):
        with patch("billing.emails._send") as mock_send:
            mock_send.return_value = True
            emails.send_payment_failed(
                to="x@y.com",
                user_name="Pedro",
                retry_date="2026-06-25",
            )
            html = mock_send.call_args[0][2]
            self.assertIn("rechazado", html)


if __name__ == "__main__":
    unittest.main()
