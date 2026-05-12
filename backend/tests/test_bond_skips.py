"""Tests del inbox de cobranzas pendientes (Phase 3E).

Endpoints:
  • GET    /api/bonds/cashflow/skips   — lista skips del user
  • POST   /api/bonds/cashflow/skip    — marca un pago como saltado
  • DELETE /api/bonds/cashflow/skip    — quita un skip

Cubre: happy paths, idempotencia (upsert), aislamiento entre users,
validación de fecha, broker desconocido.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _new_user(conn, email: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"),
    )
    return cur.lastrowid


def _add_broker(conn, uid: int, name: str, currency: str = "USDT") -> int:
    cur = conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
        (uid, name, currency),
    )
    return cur.lastrowid


class BondCashflowSkipsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"skip-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _post(self, body):
        return self.client.post(
            "/api/bonds/cashflow/skip",
            json=body,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _delete(self, params):
        return self.client.delete(
            "/api/bonds/cashflow/skip",
            params=params,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _list(self):
        return self.client.get(
            "/api/bonds/cashflow/skips",
            headers={"Authorization": f"Bearer {self.token}"},
        )

    # ─── Happy paths ─────────────────────────────────────────────────────────

    def test_create_skip(self):
        res = self._post({
            "broker": "Cocos", "asset": "AL30",
            "date": "2026-07-09",
            "reason": "Bono vendido antes",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["asset"], "AL30")

        # Verificar persistencia
        conn = main.get_db()
        row = conn.execute(
            "SELECT * FROM bond_cashflow_skips WHERE user_id=? AND date='2026-07-09'",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["reason"], "Bono vendido antes")

    def test_skip_without_reason(self):
        """`reason` es opcional."""
        res = self._post({
            "broker": "Cocos", "asset": "TX26",
            "date": "2026-05-09",
        })
        self.assertEqual(res.status_code, 200, res.text)

    def test_skip_is_idempotent(self):
        """Re-skip mismo (broker, asset, date) actualiza el reason — no falla."""
        self._post({
            "broker": "Cocos", "asset": "AL30",
            "date": "2026-07-09",
            "reason": "Reason original",
        })
        res = self._post({
            "broker": "Cocos", "asset": "AL30",
            "date": "2026-07-09",
            "reason": "Reason actualizado",
        })
        self.assertEqual(res.status_code, 200)
        # Solo debe haber UN row (no dos)
        conn = main.get_db()
        rows = conn.execute(
            "SELECT * FROM bond_cashflow_skips WHERE user_id=? AND date='2026-07-09'",
            (self.uid,),
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "Reason actualizado")

    def test_list_skips_returns_user_skips_only(self):
        # Crear 3 skips para self.uid
        for date in ("2026-01-09", "2026-04-09", "2026-07-09"):
            self._post({"broker": "Cocos", "asset": "AL30", "date": date})
        res = self._list()
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(len(body), 3)
        # Ordenados por fecha ASC
        self.assertEqual(body[0]["date"], "2026-01-09")
        self.assertEqual(body[-1]["date"], "2026-07-09")

    def test_delete_skip_removes_it(self):
        self._post({"broker": "Cocos", "asset": "AL30", "date": "2026-07-09"})
        res = self._delete({"broker": "Cocos", "asset": "AL30", "date": "2026-07-09"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["deleted"], 1)
        # Confirmar que ya no aparece en la lista
        list_res = self._list()
        self.assertEqual(len(list_res.json()), 0)

    def test_delete_nonexistent_skip_returns_zero(self):
        """DELETE de un skip que no existe no falla; devuelve deleted=0."""
        res = self._delete({"broker": "Cocos", "asset": "AL30", "date": "2099-01-01"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["deleted"], 0)

    def test_asset_normalized_to_uppercase(self):
        """asset lowercase se normaliza a uppercase al persistir."""
        res = self._post({"broker": "Cocos", "asset": "al30", "date": "2026-07-09"})
        self.assertEqual(res.json()["asset"], "AL30")
        conn = main.get_db()
        row = conn.execute(
            "SELECT asset FROM bond_cashflow_skips WHERE user_id=?", (self.uid,)
        ).fetchone()
        conn.close()
        self.assertEqual(row["asset"], "AL30")

    # ─── Validación ──────────────────────────────────────────────────────────

    def test_invalid_date_format_rejected(self):
        res = self._post({"broker": "Cocos", "asset": "AL30", "date": "09/07/2026"})
        self.assertEqual(res.status_code, 422)

    def test_unknown_broker_rejected(self):
        res = self._post({"broker": "NoExiste", "asset": "AL30", "date": "2026-07-09"})
        self.assertEqual(res.status_code, 404)

    def test_unauthorized_without_token(self):
        res = self.client.post(
            "/api/bonds/cashflow/skip",
            json={"broker": "Cocos", "asset": "AL30", "date": "2026-07-09"},
        )
        self.assertIn(res.status_code, (401, 403))

    def test_cross_user_isolation(self):
        """Un user no ve los skips de otro."""
        conn = main.get_db()
        other_uid = _new_user(conn, f"other-skip-{self.id()}@rendi.test")
        _add_broker(conn, other_uid, "Cocos", "ARS")
        conn.commit()
        conn.close()
        other_token = main.create_token(other_uid)

        # User A crea un skip
        self._post({"broker": "Cocos", "asset": "AL30", "date": "2026-07-09"})

        # User B lista — no debería ver nada
        res = self.client.get(
            "/api/bonds/cashflow/skips",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])


if __name__ == "__main__":
    unittest.main()
