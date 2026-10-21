"""RENDI-B01: los períodos CERRADOS de Reportes son de plan pago, y el corte vive
en el SERVIDOR, no sólo en la pantalla. Antes /reports/period y /reports/timeline
servían todo a una cuenta Free (el front lo escondía); /reports/years ya cortaba.
"""
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402


def _mk_user(tier=None):
    conn = main.get_db()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
        "VALUES (?,?,1,1,?)",
        (f"gate-{tier or 'free'}-{os.urandom(4).hex()}@rendi.test", "x", tier))
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return uid


class ReportsPlanGateTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.free = _mk_user(tier=None)
        self.plus = _mk_user(tier="plus")
        hoy = main._hoy_art_date()
        self.anio_actual = str(hoy.year)
        self.anio_pasado = str(hoy.year - 5)
        self.mes_actual = hoy.strftime("%Y-%m")

    def _hdr(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _get(self, path, uid):
        return self.client.get(path, headers=self._hdr(uid))

    # ── period_detail: el candado nuevo ────────────────────────────────────
    def test_free_no_ve_un_anio_cerrado(self):
        r = self._get(f"/api/reports/period/year/{self.anio_pasado}", self.free)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["code"], "plan_requerido")

    def test_free_si_ve_el_periodo_en_curso(self):
        # El año y el mes en curso son gratis: pasan el candado (200 o 400 por
        # datos, pero nunca 403).
        self.assertNotEqual(
            self._get(f"/api/reports/period/year/{self.anio_actual}", self.free).status_code, 403)
        self.assertNotEqual(
            self._get(f"/api/reports/period/month/{self.mes_actual}", self.free).status_code, 403)

    def test_plus_ve_un_anio_cerrado(self):
        self.assertNotEqual(
            self._get(f"/api/reports/period/year/{self.anio_pasado}", self.plus).status_code, 403)

    # ── timeline: Free sólo el mes en curso ─────────────────────────────────
    def test_timeline_free_se_recorta_al_mes_en_curso(self):
        with patch("main.build_timeline", return_value=[]) as mb:
            self._get("/api/reports/timeline?months=12", self.free)
        self.assertEqual(mb.call_args.kwargs["months"], 1)

    def test_timeline_plus_recibe_todos_los_meses(self):
        with patch("main.build_timeline", return_value=[]) as mb:
            self._get("/api/reports/timeline?months=12", self.plus)
        self.assertEqual(mb.call_args.kwargs["months"], 12)
