"""Tests para GET /api/admin/users/search — buscar usuarios por email/nombre/id
para regalar Pro sin scrollear miles de filas. Verifica auth admin, filtrado,
LIMIT, escape de comodines LIKE y que el shape sea el mismo que /api/admin/users."""
import unittest
import uuid

import main
from fastapi.testclient import TestClient


def _mk_user(conn, email, name=None, is_admin=0, tier=None):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, tier) "
        "VALUES (?, 'x', 1, ?, ?, ?)",
        (email, is_admin, name, tier),
    )
    return cur.lastrowid


class AdminUserSearchTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]           # namespace único de esta corrida
        conn = main.get_db()
        self.admin_uid = _mk_user(conn, f"admin-{self.tag}@rendi.test", is_admin=1)
        self.u_alice = _mk_user(conn, f"alice-{self.tag}@rendi.test", name="Alice Wonder")
        self.u_bob = _mk_user(conn, f"bob-{self.tag}@rendi.test", name="Bob Marley")
        conn.commit()
        conn.close()
        self.admin_h = {"Authorization": f"Bearer {main.create_token(self.admin_uid)}"}

    def _search(self, q, **kw):
        return self.client.get("/api/admin/users/search", params={"q": q, **kw}, headers=self.admin_h)

    def test_requires_admin(self):
        conn = main.get_db()
        plain = _mk_user(conn, f"plain-{self.tag}@rendi.test")
        conn.commit(); conn.close()
        r = self.client.get("/api/admin/users/search", params={"q": self.tag},
                            headers={"Authorization": f"Bearer {main.create_token(plain)}"})
        self.assertEqual(r.status_code, 403)

    def test_requires_auth(self):
        self.assertIn(self.client.get("/api/admin/users/search", params={"q": "ab"}).status_code,
                      (401, 403))

    def test_find_by_email_substring(self):
        r = self._search(f"alice-{self.tag}")
        self.assertEqual(r.status_code, 200)
        emails = {u["email"] for u in r.json()}
        self.assertIn(f"alice-{self.tag}@rendi.test", emails)
        self.assertNotIn(f"bob-{self.tag}@rendi.test", emails)

    def test_find_by_name_substring(self):
        emails = {u["email"] for u in self._search("Marley").json()}
        self.assertIn(f"bob-{self.tag}@rendi.test", emails)

    def test_find_by_id(self):
        rows = self._search(str(self.u_alice)).json()
        self.assertTrue(any(u["id"] == self.u_alice for u in rows))

    def test_min_two_chars(self):
        self.assertEqual(self._search("a").json(), [])
        self.assertEqual(self._search("").json(), [])

    def test_limit_capped(self):
        r = self._search(self.tag, limit=1)           # los 3 comparten el tag
        self.assertLessEqual(len(r.json()), 1)

    def test_same_shape_as_list(self):
        u = next(u for u in self._search(f"alice-{self.tag}").json())
        for k in ("id", "email", "name", "plan", "credit_active", "days_remaining",
                  "billing_affected", "is_admin", "approved", "positions_count"):
            self.assertIn(k, u)
        self.assertEqual(u["plan"], "free")

    def test_unicode_digit_does_not_crash(self):
        # str.isdigit() acepta '²'/'٥' pero int() los rechaza → sin el guard isascii()
        # el endpoint tiraba 500. Deben devolver 200 (sin match numérico).
        for q in ("²", "⁵", "٢٣"):
            r = self._search(q)
            self.assertEqual(r.status_code, 200, f"q={q!r} → {r.status_code}")

    def test_underscore_is_literal_not_wildcard(self):
        # '_' en LIKE matchea cualquier char; con ESCAPE debe ser literal → un query
        # con guión bajo NO trae a alice/bob (que no lo tienen).
        emails = {u["email"] for u in self._search(f"a_{self.tag}").json()}
        self.assertNotIn(f"alice-{self.tag}@rendi.test", emails)


if __name__ == "__main__":
    unittest.main()
