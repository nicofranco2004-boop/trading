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
    """DB en memoria con el schema REAL, no con uno escrito a mano.

    ⚠️ POR QUÉ NO SE ESCRIBEN MÁS LAS TABLAS ACÁ. Este fixture las declaraba a mano
    y había que acordarse de espejar cada columna nueva de `main.init_db()`. Cuando
    alguien no se acordaba no explotaba nada visible: el job atrapa sus propios
    errores y los CUENTA, así que el "no such column: trial_ends_at" salía por el
    log y el test moría comparando `errors == 0` contra un 2 que no tenía nada que
    ver con el job. Faltaban cuatro columnas de tres features distintas
    (`trial_ends_at`, `trial_started_at`, `quota_window_from`, `managed_by`) — o
    sea que el fixture venía atrasado desde hacía rato y el test ya no probaba el
    cron: probaba el fixture.

    Copiando el DDL de la base que arma `main.init_db()` (tests/conftest.py le da
    una por módulo), el schema no puede volver a divergir. Sigue siendo `:memory:`,
    así que cada test arranca aislado como antes.
    """
    import main
    if getattr(main, "USANDO_PG", False):
        raise unittest.SkipTest("el fixture copia el DDL de SQLite (sqlite_master)")
    real = main.get_db()
    try:
        ddl = [r[0] for r in real.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
            "  AND name NOT LIKE 'sqlite_%' "   # sqlite_sequence la crea el motor
            "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END").fetchall()]
    finally:
        real.close()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for stmt in ddl:
        conn.execute(stmt)
    return conn


def _add_user(conn, uid, tier='pro', is_admin=0):
    # `password_hash` es NOT NULL en el schema real. El fixture hecho a mano ni
    # siquiera declaraba la columna, así que además de faltarle columnas dejaba
    # entrar filas que producción rechaza.
    conn.execute(
        "INSERT INTO users (id, email, password_hash, is_admin, tier) VALUES (?, ?, 'x', ?, ?)",
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
