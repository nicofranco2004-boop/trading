"""Tests para GET /api/admin/users/mails-meta.csv — la lista de mails para el
"público personalizado" de Meta. Verifica que sólo la baje un admin, que el
encabezado sea el que Meta reconoce solo (email, fn, ln), que deje afuera a
admins y cuentas de prueba, y cómo parte el nombre."""
import csv
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient


def _mk_user(conn, email, name=None, is_admin=0, verified=1):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, email_verified) "
        "VALUES (?, 'x', 1, ?, ?, ?)",
        (email, is_admin, name, verified),
    )
    return cur.lastrowid


class AdminMailsMetaTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin_uid = _mk_user(conn, f"admin-{self.tag}@ejemplo.com", is_admin=1)
        _mk_user(conn, f"Ana-{self.tag}@Ejemplo.com ", name="Ana María Pérez")
        _mk_user(conn, f"solo-{self.tag}@ejemplo.com", name="Juan")
        _mk_user(conn, f"sinnombre-{self.tag}@ejemplo.com")
        _mk_user(conn, f"noconfirmo-{self.tag}@ejemplo.com", verified=0)
        _mk_user(conn, f"prueba-{self.tag}@rendi.test", name="No Va")
        conn.commit()
        conn.close()
        self.admin_h = {"Authorization": f"Bearer {main.create_token(self.admin_uid)}"}

    def _filas(self):
        r = self.client.get("/api/admin/users/mails-meta.csv", headers=self.admin_h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["content-type"])
        self.assertIn("attachment", r.headers["content-disposition"])
        lector = csv.reader(io.StringIO(r.text))
        encabezado = next(lector)
        self.assertEqual(encabezado, ["email", "fn", "ln"])
        return {f[0]: f for f in lector if self.tag in f[0]}

    def test_solo_admin(self):
        conn = main.get_db()
        comun = _mk_user(conn, f"comun-{self.tag}@ejemplo.com")
        conn.commit(); conn.close()
        r = self.client.get("/api/admin/users/mails-meta.csv",
                            headers={"Authorization": f"Bearer {main.create_token(comun)}"})
        self.assertEqual(r.status_code, 403)
        self.assertIn(self.client.get("/api/admin/users/mails-meta.csv").status_code, (401, 403))

    def test_quienes_van(self):
        filas = self._filas()
        self.assertEqual(set(filas), {
            f"ana-{self.tag}@ejemplo.com",
            f"solo-{self.tag}@ejemplo.com",
            f"sinnombre-{self.tag}@ejemplo.com",
            f"noconfirmo-{self.tag}@ejemplo.com",
        })

    def test_parte_el_nombre(self):
        filas = self._filas()
        self.assertEqual(filas[f"ana-{self.tag}@ejemplo.com"], [f"ana-{self.tag}@ejemplo.com", "Ana", "María Pérez"])
        self.assertEqual(filas[f"solo-{self.tag}@ejemplo.com"][1:], ["Juan", ""])
        self.assertEqual(filas[f"sinnombre-{self.tag}@ejemplo.com"][1:], ["", ""])


if __name__ == "__main__":
    unittest.main()
