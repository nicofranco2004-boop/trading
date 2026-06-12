"""Red de seguridad en tiempo real: quota.get_tier corta el acceso pago apenas
vence el crédito (regalo/comp), sin esperar al cron diario y aunque el cron falle.

Cubre el gap HIGH del deep audit: antes get_tier leía solo users.tier y un regalo
vencido seguía dando Pro hasta que corriera el cron (hasta ~24h, o para siempre
si el cron fallaba).

Corre con: cd backend && python3 -m pytest tests/test_credit_realtime_gating.py
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402  (crea el schema)
from ai import quota  # noqa: E402


def _iso(days_from_now=0):
    return (datetime.utcnow() + timedelta(days=days_from_now)).isoformat()


class CreditRealtimeGatingTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("users", "subscriptions"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _user(self, *, tier=None, credit_active_until=None, is_admin=0):
        cur = self.conn.execute(
            """INSERT INTO users (email, password_hash, approved, is_admin, tier, credit_active_until)
               VALUES (?,?,1,?,?,?)""",
            (f"u{self._n()}@gmail.com", "x", is_admin, tier, credit_active_until))
        self.conn.commit()
        return cur.lastrowid

    _counter = 0
    def _n(self):
        CreditRealtimeGatingTest._counter += 1
        return CreditRealtimeGatingTest._counter

    def _auth_sub(self, uid):
        self.conn.execute(
            """INSERT INTO subscriptions (user_id, external_reference, period, status, amount_ars)
               VALUES (?, ?, 'monthly', 'authorized', 0)""",
            (uid, f"rendi-{uid}-pro-monthly"))
        self.conn.commit()

    # ── casos ────────────────────────────────────────────────────────────────
    def test_gift_active_returns_pro(self):
        # Regalo vigente (vence en 10 días), sin sub → Pro.
        uid = self._user(tier="pro", credit_active_until=_iso(10))
        self.assertEqual(quota.get_tier(self.conn, uid), "pro")

    def test_gift_expired_returns_free(self):
        # Regalo vencido ayer, sin sub → Free EN TIEMPO REAL (sin esperar el cron).
        uid = self._user(tier="pro", credit_active_until=_iso(-1))
        self.assertEqual(quota.get_tier(self.conn, uid), "free")

    def test_gift_expired_plus_returns_free(self):
        uid = self._user(tier="plus", credit_active_until=_iso(-0.001))
        self.assertEqual(quota.get_tier(self.conn, uid), "free")

    def test_paid_expired_with_authorized_sub_stays_pro(self):
        # Pagó (sub authorized) y el crédito quedó vencido por un lapso entre
        # cobros → NO lo cortamos (se renueva solo). Protege a los que pagan.
        uid = self._user(tier="pro", credit_active_until=_iso(-1))
        self._auth_sub(uid)
        self.assertEqual(quota.get_tier(self.conn, uid), "pro")

    def test_pro_without_credit_date_stays_pro(self):
        # tier='pro' sin credit_active_until (no sabemos si expiró) → fail-open.
        uid = self._user(tier="pro", credit_active_until=None)
        self.assertEqual(quota.get_tier(self.conn, uid), "pro")

    def test_admin_with_expired_gift_stays_admin(self):
        # Admin con regalo vencido → conserva 'admin' (pierde features Pro pero
        # no el panel). Mismo resultado que el cron (tier=NULL → get_tier=admin).
        uid = self._user(tier="pro", credit_active_until=_iso(-2), is_admin=1)
        self.assertEqual(quota.get_tier(self.conn, uid), "admin")

    def test_free_override_unaffected(self):
        uid = self._user(tier="free", credit_active_until=None)
        self.assertEqual(quota.get_tier(self.conn, uid), "free")

    def test_no_override_admin(self):
        uid = self._user(tier=None, is_admin=1)
        self.assertEqual(quota.get_tier(self.conn, uid), "admin")

    def test_no_override_free(self):
        uid = self._user(tier=None, is_admin=0)
        self.assertEqual(quota.get_tier(self.conn, uid), "free")


class RebillActivateFallbackCreditTest(unittest.TestCase):
    """Si grant_payment_credit falla en _rebill_activate, el user NO debe quedar
    Pro sin fecha de vencimiento (Pro permanente). Debe setearse un crédito
    fallback para que el cron / la red de seguridad lo bajen al vencer."""

    def setUp(self):
        from unittest.mock import patch
        self.patch = patch
        self.conn = main.get_db()
        for t in ("users", "subscriptions"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier, credit_active_until) VALUES (?,?,1,NULL,NULL)",
            ("rebillfail@gmail.com", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _cau(self):
        return self.conn.execute(
            "SELECT tier, credit_active_until FROM users WHERE id=?", (self.uid,)).fetchone()

    def test_grant_failure_sets_fallback_credit(self):
        with self.patch("billing.credits.grant_payment_credit", side_effect=Exception("boom")):
            main._rebill_activate(
                self.conn, self.uid,
                {"rendi_plan": "pro", "rendi_period": "monthly"},
                "sub_test", {})
        row = self._cau()
        self.assertEqual(row["tier"], "pro")                 # tier quedó pago
        self.assertIsNotNone(row["credit_active_until"])     # pero CON fecha de fin
        # y ~30 días en el futuro (no permanente)
        exp = datetime.fromisoformat(row["credit_active_until"])
        self.assertGreater(exp, datetime.utcnow() + timedelta(days=25))
        self.assertLess(exp, datetime.utcnow() + timedelta(days=35))

    def test_invalid_plan_normalizes_to_pro(self):
        # metadata con plan inválido → no rompe; tier termina en 'pro'.
        with self.patch("billing.credits.grant_payment_credit", side_effect=Exception("boom")):
            main._rebill_activate(
                self.conn, self.uid,
                {"rendi_plan": "enterprise", "rendi_period": "weird"},
                "sub_test2", {})
        self.assertEqual(self._cau()["tier"], "pro")


if __name__ == "__main__":
    unittest.main()
