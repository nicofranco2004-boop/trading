"""RENDI-B06 / A01: cerrar las puertas para llenar el disco con una cuenta gratis.

- /api/plan/track: props gigante se descarta (antes se guardaba tal cual, sin tope).
- editar un grupo de posiciones: un nombre de activo gigante se rechaza (antes sin
  largo máximo, y ese nombre se guarda en cada lote y en el deshacer).
"""
import os
import sys
import unittest

import pydantic

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402


def _mk():
    conn = main.get_db()
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?,?,1,1)",
        (f"disco-{os.urandom(4).hex()}@rendi.test", "x")).lastrowid
    conn.commit()
    conn.close()
    return uid


class LimitesDiscoTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.uid = _mk()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _props_guardado(self):
        conn = main.get_db()
        try:
            r = conn.execute(
                "SELECT props_json FROM plan_events WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (self.uid,)).fetchone()
            return r["props_json"] if r else None
        finally:
            conn.close()

    def test_plan_track_descarta_props_gigante(self):
        r = self.client.post("/api/plan/track", headers=self.h,
                             json={"event": "upgrade_promo_clicked", "props": {"x": "A" * 5000}})
        self.assertEqual(r.status_code, 204)
        guardado = self._props_guardado()
        self.assertEqual(guardado, "{}")                 # el gigante no se guardó
        self.assertLess(len(guardado), main._PLAN_TRACK_PROPS_MAX)

    def test_plan_track_guarda_props_normal(self):
        r = self.client.post("/api/plan/track", headers=self.h,
                             json={"event": "upgrade_promo_clicked", "props": {"code": "disposition"}})
        self.assertEqual(r.status_code, 204)
        self.assertIn("disposition", self._props_guardado())

    def test_editar_grupo_rechaza_nombre_gigante(self):
        # new_asset más largo que MAX_STR → Pydantic lo rechaza antes de tocar la base.
        with self.assertRaises(pydantic.ValidationError):
            main.PositionGroupEditIn(broker="Cocos", asset="GGAL", new_asset="A" * 500)
        # El caso normal sigue construyéndose bien.
        ok = main.PositionGroupEditIn(broker="Cocos", asset="GGAL", new_asset="GGAL2")
        self.assertEqual(ok.new_asset, "GGAL2")
