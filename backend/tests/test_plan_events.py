"""Tests para /api/plan/track + /api/admin/plan/conversion.

Verifica el flujo de telemetría del paywall:
  • POST /plan/track inserta filas en plan_events
  • Eventos no whitelist son silenciosamente ignorados (no error)
  • GET /admin/plan/conversion agrega correctamente
"""
import unittest
import uuid

import main


def _new_user(conn, is_admin: int = 0) -> int:
    email = f"plan-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?, 'x', 1, ?)",
        (email, is_admin),
    )
    return cur.lastrowid


class PlanTrackTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = _new_user(conn)
        self.admin_uid = _new_user(conn, is_admin=1)
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.admin_token = main.create_token(self.admin_uid)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def _track(self, **kwargs):
        return self.client.post("/api/plan/track", json=kwargs, headers=self.headers)

    def test_track_inserts_row(self):
        r = self._track(
            event="feature_blocked_clicked",
            feature_id="comportamiento.full",
            source="behavioral_grid",
        )
        self.assertEqual(r.status_code, 204)

        conn = main.get_db()
        row = conn.execute(
            "SELECT user_id, event_name, feature_id, source, tier FROM plan_events WHERE user_id = ?",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["event_name"], "feature_blocked_clicked")
        self.assertEqual(row["feature_id"], "comportamiento.full")
        self.assertEqual(row["source"], "behavioral_grid")
        self.assertEqual(row["tier"], "free")

    def test_track_unauthorized_event_ignored_silently(self):
        """Eventos fuera de _ALLOWED_PLAN_EVENTS no fallan, pero tampoco insertan."""
        r = self._track(event="some.random.event", feature_id="x")
        self.assertEqual(r.status_code, 204)
        # No debe haber row
        conn = main.get_db()
        row = conn.execute(
            "SELECT 1 FROM plan_events WHERE user_id = ?",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNone(row)

    def test_track_requires_auth(self):
        r = self.client.post(
            "/api/plan/track",
            json={"event": "feature_blocked_clicked"},
        )
        self.assertIn(r.status_code, (401, 403))

    def test_track_stores_tier_at_event_time(self):
        """tier se snapshotea al insertar — admin queda con 'admin'."""
        r = self.client.post(
            "/api/plan/track",
            json={"event": "feature_blocked_clicked"},
            headers=self.admin_headers,
        )
        self.assertEqual(r.status_code, 204)
        conn = main.get_db()
        row = conn.execute(
            "SELECT tier FROM plan_events WHERE user_id = ?",
            (self.admin_uid,),
        ).fetchone()
        conn.close()
        self.assertEqual(row["tier"], "admin")

    def test_admin_conversion_aggregations(self):
        """GET /admin/plan/conversion agrega por feature, source, totals."""
        # Insertar varios eventos
        self._track(event="feature_blocked_clicked", feature_id="comportamiento.full", source="behavioral_grid")
        self._track(event="feature_blocked_clicked", feature_id="comportamiento.full", source="behavioral_grid")
        self._track(event="upgrade_modal_cta_clicked", feature_id="brokers.create", source="config_add_broker")

        r = self.client.get("/api/admin/plan/conversion", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()

        # Totales por event_name
        self.assertGreaterEqual(data["totals"].get("feature_blocked_clicked", 0), 2)
        self.assertGreaterEqual(data["totals"].get("upgrade_modal_cta_clicked", 0), 1)

        # Por feature debería tener comportamiento.full primero (2 clicks)
        feat_ids = [f["feature_id"] for f in data["by_feature"]]
        self.assertIn("comportamiento.full", feat_ids)
        self.assertIn("brokers.create", feat_ids)

        # By source
        sources = [s["source"] for s in data["by_source"]]
        self.assertIn("behavioral_grid", sources)
        self.assertIn("config_add_broker", sources)

        # last_30d_total y distinct_free_users_with_intent presentes
        self.assertIn("last_30d_total", data)
        self.assertIn("distinct_free_users_with_intent", data)
        self.assertIn("recent", data)

    def test_admin_conversion_requires_admin(self):
        """Free user NO puede ver el dashboard de admin."""
        r = self.client.get("/api/admin/plan/conversion", headers=self.headers)
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
