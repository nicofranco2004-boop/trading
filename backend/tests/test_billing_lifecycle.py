"""Tests para billing/subscriptions.py — el cron diario.

Cubre las 3 operaciones que hace el job:
  1. Downgrade post-cancelación
  2. Cleanup de pending abandonadas
  3. Sync con MP de subs authorized
"""
import sqlite3
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from billing import subscriptions


def _make_db():
    """In-memory DB con las tablas mínimas que el job necesita."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            name TEXT,
            is_admin INTEGER DEFAULT 0,
            tier TEXT,
            email_verified INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            -- Modelo de crédito tiempo-based (ver main.py init_db). El código de
            -- billing ya consulta estas columnas, así que el fixture debe tenerlas.
            credit_active_until TEXT,
            credit_anchor_plan TEXT,
            credit_anchor_period TEXT,
            credit_anchor_amount_usd REAL,
            credit_anchor_at TEXT
        );
        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mp_subscription_id TEXT,
            external_reference TEXT NOT NULL,
            period TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            amount_ars INTEGER NOT NULL,
            current_period_start TEXT,
            current_period_end TEXT,
            next_charge_date TEXT,
            init_point TEXT,
            cancelled_at TEXT,
            welcome_email_sent_at TEXT,
            cancellation_email_sent_at TEXT,
            expiration_reminder_sent_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        -- Tablas que _delete_unverified_accounts toca (verificación de "tiene
        -- data" + cleanup en cascada manual).
        CREATE TABLE email_verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT, expires_at TEXT, used_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE positions (id INTEGER PRIMARY KEY, user_id INTEGER);
        CREATE TABLE operations (id INTEGER PRIMARY KEY, user_id INTEGER);
        CREATE TABLE monthly_entries (id INTEGER PRIMARY KEY, user_id INTEGER);
        CREATE TABLE brokers (id INTEGER PRIMARY KEY, user_id INTEGER);
        -- Audit del modelo de crédito (ver main.py init_db). Los downgrades
        -- (_downgrade_expired_credit / _downgrade_expired_cancellations) escriben
        -- una fila 'expiration' acá, así que el fixture debe tener la tabla.
        CREATE TABLE credit_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            days_delta REAL NOT NULL,
            from_plan TEXT,
            from_period TEXT,
            to_plan TEXT,
            to_period TEXT,
            active_until_before TEXT,
            active_until_after TEXT,
            source_subscription_id TEXT,
            payment_id TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    return conn


def _add_user(conn, uid, tier='pro', is_admin=0):
    conn.execute(
        "INSERT INTO users (id, email, is_admin, tier) VALUES (?, ?, ?, ?)",
        (uid, f"u{uid}@test.com", is_admin, tier),
    )
    conn.commit()


def _add_sub(conn, user_id, status, *, period_end=None, created_days_ago=0, mp_id="sub-x"):
    created = (datetime.utcnow() - timedelta(days=created_days_ago)).isoformat()
    conn.execute(
        """INSERT INTO subscriptions
               (user_id, mp_subscription_id, external_reference, period, status,
                amount_ars, current_period_end, created_at, updated_at)
           VALUES (?, ?, ?, 'monthly', ?, 12100, ?, ?, datetime('now'))""",
        (user_id, mp_id, f"rendi-{user_id}-monthly", status, period_end, created),
    )
    conn.commit()


# ─── Downgrade post-cancelación ─────────────────────────────────────────────

class DowngradeTest(unittest.TestCase):

    def test_cancelled_sub_with_past_period_end_downgrades_user(self):
        """User cancelled + period_end ya pasó → tier='free' (NULL en realidad)."""
        conn = _make_db()
        _add_user(conn, 1, tier='pro')
        past = (datetime.utcnow() - timedelta(days=1)).isoformat()
        _add_sub(conn, 1, 'cancelled', period_end=past, mp_id="cancelled-expired")

        result = subscriptions._downgrade_expired_cancellations(conn)
        self.assertEqual(result, 1)

        # User ahora con tier=NULL (Free por default)
        u = conn.execute("SELECT tier FROM users WHERE id=1").fetchone()
        self.assertIsNone(u["tier"])
        # Sub marcada como expired
        s = conn.execute("SELECT status FROM subscriptions WHERE user_id=1").fetchone()
        self.assertEqual(s["status"], "expired")

    def test_cancelled_sub_with_future_period_end_keeps_pro(self):
        """User cancelled pero period_end todavía no pasó → mantiene Pro."""
        conn = _make_db()
        _add_user(conn, 2, tier='pro')
        future = (datetime.utcnow() + timedelta(days=10)).isoformat()
        _add_sub(conn, 2, 'cancelled', period_end=future, mp_id="cancelled-future")

        result = subscriptions._downgrade_expired_cancellations(conn)
        self.assertEqual(result, 0)
        u = conn.execute("SELECT tier FROM users WHERE id=2").fetchone()
        self.assertEqual(u["tier"], "pro")

    def test_authorized_sub_is_not_touched(self):
        """Subs authorized NUNCA se tocan por este step."""
        conn = _make_db()
        _add_user(conn, 3, tier='pro')
        past = (datetime.utcnow() - timedelta(days=1)).isoformat()
        _add_sub(conn, 3, 'authorized', period_end=past, mp_id="auth-expired")

        result = subscriptions._downgrade_expired_cancellations(conn)
        self.assertEqual(result, 0)
        u = conn.execute("SELECT tier FROM users WHERE id=3").fetchone()
        self.assertEqual(u["tier"], "pro")

    def test_already_free_user_is_skipped(self):
        """Si el user ya es Free, no procesamos (idempotente)."""
        conn = _make_db()
        _add_user(conn, 4, tier=None)  # Free
        past = (datetime.utcnow() - timedelta(days=1)).isoformat()
        _add_sub(conn, 4, 'cancelled', period_end=past)
        result = subscriptions._downgrade_expired_cancellations(conn)
        # Sub vieja pero user ya está free → no se contabiliza
        self.assertEqual(result, 0)


# ─── Cleanup de pending stale ──────────────────────────────────────────────

class StalePendingCleanupTest(unittest.TestCase):

    def test_pending_sub_older_than_7_days_is_cancelled(self):
        conn = _make_db()
        _add_user(conn, 1, tier=None)
        _add_sub(conn, 1, 'pending', created_days_ago=10, mp_id="stale-pending")

        result = subscriptions._cancel_stale_pending(conn)
        self.assertEqual(result, 1)
        s = conn.execute("SELECT status, cancelled_at FROM subscriptions WHERE user_id=1").fetchone()
        self.assertEqual(s["status"], "cancelled")
        self.assertIsNotNone(s["cancelled_at"])

    def test_recent_pending_sub_is_kept(self):
        conn = _make_db()
        _add_user(conn, 2, tier=None)
        _add_sub(conn, 2, 'pending', created_days_ago=2, mp_id="recent-pending")

        result = subscriptions._cancel_stale_pending(conn)
        self.assertEqual(result, 0)
        s = conn.execute("SELECT status FROM subscriptions WHERE user_id=2").fetchone()
        self.assertEqual(s["status"], "pending")

    def test_authorized_sub_not_touched_even_if_old(self):
        conn = _make_db()
        _add_user(conn, 3, tier='pro')
        _add_sub(conn, 3, 'authorized', created_days_ago=30)
        result = subscriptions._cancel_stale_pending(conn)
        self.assertEqual(result, 0)


# ─── Sync con MP ────────────────────────────────────────────────────────────

class SyncWithMpTest(unittest.TestCase):

    def test_sync_detects_mp_cancellation_we_missed(self):
        """MP dice 'cancelled' pero nosotros tenemos 'authorized' → corregir."""
        conn = _make_db()
        _add_user(conn, 1, tier='pro')
        _add_sub(conn, 1, 'authorized', mp_id="should-be-cancelled")

        with patch("billing.mercadopago.get_preapproval") as mp_get:
            mp_get.return_value = {"status": "cancelled"}
            result = subscriptions._sync_authorized_with_mp(conn)
            self.assertEqual(result, 1)
        s = conn.execute("SELECT status FROM subscriptions WHERE user_id=1").fetchone()
        self.assertEqual(s["status"], "cancelled")

    def test_sync_skips_when_mp_state_matches(self):
        conn = _make_db()
        _add_user(conn, 2, tier='pro')
        _add_sub(conn, 2, 'authorized', mp_id="still-active")

        with patch("billing.mercadopago.get_preapproval") as mp_get:
            mp_get.return_value = {"status": "authorized"}
            result = subscriptions._sync_authorized_with_mp(conn)
            self.assertEqual(result, 0)

    def test_sync_handles_mp_api_failure_gracefully(self):
        """Si MP devuelve error, NO rompemos el job — logueamos y seguimos."""
        conn = _make_db()
        _add_user(conn, 3, tier='pro')
        _add_sub(conn, 3, 'authorized', mp_id="mp-broken")

        with patch("billing.mercadopago.get_preapproval") as mp_get:
            mp_get.side_effect = Exception("MP timeout")
            # No debe levantar excepción
            result = subscriptions._sync_authorized_with_mp(conn)
            self.assertEqual(result, 0)
        s = conn.execute("SELECT status FROM subscriptions WHERE user_id=3").fetchone()
        self.assertEqual(s["status"], "authorized")  # mantiene estado


# ─── Job completo (orquestador) ─────────────────────────────────────────────

class FullLifecycleJobTest(unittest.TestCase):

    def test_runs_all_three_steps_and_returns_counts(self):
        conn = _make_db()
        # 1 user para downgrade
        _add_user(conn, 1, tier='pro')
        _add_sub(conn, 1, 'cancelled',
                 period_end=(datetime.utcnow() - timedelta(days=1)).isoformat(),
                 mp_id="to-downgrade")
        # 1 user para stale cleanup
        _add_user(conn, 2, tier=None)
        _add_sub(conn, 2, 'pending', created_days_ago=10, mp_id="to-cleanup")

        with patch("billing.mercadopago.get_preapproval") as mp_get:
            mp_get.return_value = {"status": "authorized"}
            result = subscriptions.run_lifecycle_job(conn)
        self.assertEqual(result["downgraded"], 1)
        self.assertEqual(result["stale_pending_cancelled"], 1)
        self.assertEqual(result["errors"], 0)


if __name__ == "__main__":
    unittest.main()
