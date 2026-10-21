"""RENDI-A04: los detectores de comportamiento se recortan por plan EN EL SERVIDOR
(no sólo en la pantalla), en los tres lugares que exponen el dato: el endpoint
/api/behavioral/insights y los dos builders de IA (behavioral y behavioral.card).

Se mockea el motor para tener 12 detectores fijos: lo que se prueba es el recorte,
no el cálculo.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402
import behavioral as _behav  # noqa: E402
from ai.builders import behavioral as _b_build  # noqa: E402
from ai.builders import behavioral_card as _b_card  # noqa: E402


def _doce_cards():
    return {
        "cards": [
            {"code": f"d{i}", "title": f"Sesgo {i}", "severity": "high",
             "detected": True, "value_label": f"{i}%", "one_liner": f"linea {i}",
             "evidence": {"instancias": [{"secreto": i}]}, "references": [{"x": i}]}
            for i in range(12)
        ],
        "summary": {}, "generated_at": "z",
    }


def _mk(tier=None):
    conn = main.get_db()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
        "VALUES (?,?,1,1,?)", (f"bg-{tier or 'free'}-{os.urandom(4).hex()}@rendi.test", "x", tier))
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return uid


class BehavioralPlanGateTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.free = _mk(None)
        self.plus = _mk("plus")

    def _hdr(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    # ── endpoint de la pantalla ─────────────────────────────────────────────
    def test_insights_free_solo_las_primeras_completas(self):
        with patch.object(_behav, "build_behavioral_insights", return_value=_doce_cards()):
            r = self.client.get("/api/behavioral/insights", headers=self._hdr(self.free))
        self.assertEqual(r.status_code, 200)
        cards = r.json()["cards"]
        self.assertEqual(len(cards), 12)                 # siguen las 12 (para el teaser)
        self.assertIn("evidence", cards[0])              # las 3 primeras, completas
        self.assertIn("evidence", cards[2])
        self.assertEqual(cards[3], {"code": "d3"})       # del resto, SÓLO el code
        self.assertEqual(cards[11], {"code": "d11"})

    def test_insights_plus_todas_completas(self):
        with patch.object(_behav, "build_behavioral_insights", return_value=_doce_cards()):
            r = self.client.get("/api/behavioral/insights", headers=self._hdr(self.plus))
        cards = r.json()["cards"]
        self.assertTrue(all("evidence" in c for c in cards))  # las 12 completas

    # ── builder de IA: el listado ───────────────────────────────────────────
    def test_builder_behavioral_free_le_pasa_a_la_ia_solo_las_permitidas(self):
        conn = main.get_db()
        try:
            with patch.object(_behav, "build_behavioral_insights", return_value=_doce_cards()):
                out_free = _b_build.build(conn, self.free)
                out_plus = _b_build.build(conn, self.plus)
        finally:
            conn.close()
        self.assertEqual(len(out_free["cards"]), 3)
        self.assertEqual(len(out_plus["cards"]), 12)

    # ── builder de IA: una card puntual ─────────────────────────────────────
    def test_builder_card_free_no_narra_un_detector_bloqueado(self):
        conn = main.get_db()
        try:
            with patch.object(_behav, "build_behavioral_insights", return_value=_doce_cards()):
                # d0 es visible (índice 0 < 3): se narra.
                self.assertIsNotNone(_b_card.build(conn, self.free, code="d0"))
                # d5 está bloqueado para Free (índice 5 >= 3): no se narra.
                with self.assertRaises(ValueError):
                    _b_card.build(conn, self.free, code="d5")
                # Para Plus, d5 se narra.
                self.assertIsNotNone(_b_card.build(conn, self.plus, code="d5"))
        finally:
            conn.close()
