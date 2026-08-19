"""Cortar el link público de un informe del asesor.

El informe del período viaja por WhatsApp como /i/{token}: sin cuenta, sin
login. Adentro va la cartera del cliente y su rendimiento. El token no se podía
revocar ni vencía nunca, así que un link reenviado a un grupo equivocado —o una
captura— dejaba esos números legibles para siempre y no había ninguna palanca
para cortarlo.

Ahora: revoked_at (el asesor lo apaga y lo puede volver a prender) y un TTL por
defecto de 180 días, porque un informe se lee cuando llega y después no se abre
más — pero el link sigue circulando. REPORTS_TTL_DAYS lo cambia sin deployar.

Al público las dos causas se ven igual (404): decirle "vencido" a quien tiene un
link filtrado le confirma que el informe existe y de cuándo es. Al asesor sí se
le distingue, en su historial.

Corre con: cd backend && python3 -m pytest tests/test_advisor_report_revoke.py
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

from fastapi.testclient import TestClient   # noqa: E402
import main                                 # noqa: E402


class InformePublicoBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        self._ttl = os.environ.get("REPORTS_TTL_DAYS")
        self.addCleanup(self._restore_ttl)
        os.environ.pop("REPORTS_TTL_DAYS", None)
        for t in ("advisor_reports", "advisor_clients", "advisor_profile", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.asesor = self._user("asesor@rendi.test", tier="advisor")
        self.otro = self._user("otro-asesor@rendi.test", tier="advisor")
        self.cliente = self._user("cliente@rendi.test")
        self.conn.commit()
        self.tok = self._informe(self.asesor, self.cliente, "tok-informe-0001")

    def _restore_ttl(self):
        if self._ttl is None:
            os.environ.pop("REPORTS_TTL_DAYS", None)
        else:
            os.environ["REPORTS_TTL_DAYS"] = self._ttl

    def _user(self, email, tier=None):
        return self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
            "VALUES (?,?,1,1,?)", (email, "x", tier)).lastrowid

    def _informe(self, advisor, cliente, token, created_at=None):
        self.conn.execute(
            """INSERT INTO advisor_reports
                   (advisor_uid, client_uid, period_start, period_end, token,
                    payload, wa_text, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (advisor, cliente, "2026-01-01", "2026-06-30", token,
             json.dumps({"label": "Cliente", "value_end_usd": 12345}), "wa",
             created_at or datetime.utcnow().isoformat(sep=" ", timespec="seconds")))
        self.conn.commit()
        return token

    def _id_de(self, token):
        return self.conn.execute(
            "SELECT id FROM advisor_reports WHERE token=?", (token,)).fetchone()["id"]

    def _headers(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _abrir(self, token):
        return self.client.get(f"/api/reports/public/{token}")

    def _revocar(self, uid, report_id, revoke=True):
        return self.client.post(
            f"/api/advisor/reports/{report_id}/revoke?revoke={'true' if revoke else 'false'}",
            headers=self._headers(uid))


class RevocarTest(InformePublicoBase):
    def test_antes_de_revocar_el_link_abre(self):
        r = self._abrir(self.tok)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["report"]["value_end_usd"], 12345)

    def test_revocado_deja_de_abrir(self):
        """EL punto: hasta ahora no había forma de cortar un link filtrado."""
        rv = self._revocar(self.asesor, self._id_de(self.tok))
        self.assertEqual(rv.status_code, 200, rv.text)
        self.assertTrue(rv.json()["revoked"])
        self.assertEqual(self._abrir(self.tok).status_code, 404)

    def test_se_puede_reactivar(self):
        """Revocar por error no puede ser irreversible: el informe está
        congelado, el token es el mismo y el cliente ya lo tiene."""
        rid = self._id_de(self.tok)
        self._revocar(self.asesor, rid)
        self.assertEqual(self._abrir(self.tok).status_code, 404)
        self._revocar(self.asesor, rid, revoke=False)
        self.assertEqual(self._abrir(self.tok).status_code, 200)

    def test_otro_asesor_no_puede_revocarlo(self):
        """Sin el advisor_uid en el WHERE, cualquier asesor apagaría los
        informes de otro."""
        rv = self._revocar(self.otro, self._id_de(self.tok))
        self.assertEqual(rv.status_code, 404)
        self.assertEqual(self._abrir(self.tok).status_code, 200)

    def test_un_cliente_no_puede_revocar(self):
        rv = self._revocar(self.cliente, self._id_de(self.tok))
        self.assertIn(rv.status_code, (401, 403))

    def test_informe_inexistente(self):
        self.assertEqual(self._revocar(self.asesor, 999999).status_code, 404)


class VencimientoTest(InformePublicoBase):
    def test_un_informe_viejo_deja_de_abrir(self):
        viejo = self._informe(
            self.asesor, self.cliente, "tok-informe-viejo1",
            created_at=(datetime.utcnow() - timedelta(days=200)).isoformat(sep=" ", timespec="seconds"))
        self.assertEqual(self._abrir(viejo).status_code, 404)

    def test_uno_reciente_sigue_abriendo(self):
        reciente = self._informe(
            self.asesor, self.cliente, "tok-informe-nuevo1",
            created_at=(datetime.utcnow() - timedelta(days=30)).isoformat(sep=" ", timespec="seconds"))
        self.assertEqual(self._abrir(reciente).status_code, 200)

    def test_el_ttl_se_puede_alargar_sin_deployar(self):
        viejo = self._informe(
            self.asesor, self.cliente, "tok-informe-viejo2",
            created_at=(datetime.utcnow() - timedelta(days=200)).isoformat(sep=" ", timespec="seconds"))
        os.environ["REPORTS_TTL_DAYS"] = "365"
        self.assertEqual(self._abrir(viejo).status_code, 200)

    def test_ttl_0_es_para_siempre(self):
        viejo = self._informe(
            self.asesor, self.cliente, "tok-informe-viejo3",
            created_at=(datetime.utcnow() - timedelta(days=5000)).isoformat(sep=" ", timespec="seconds"))
        os.environ["REPORTS_TTL_DAYS"] = "0"
        self.assertEqual(self._abrir(viejo).status_code, 200)

    def test_vencido_y_revocado_se_ven_igual_desde_afuera(self):
        """404 los dos: un 410 le confirmaría a quien tiene el link filtrado que
        el informe existe."""
        viejo = self._informe(
            self.asesor, self.cliente, "tok-informe-viejo4",
            created_at=(datetime.utcnow() - timedelta(days=200)).isoformat(sep=" ", timespec="seconds"))
        self._revocar(self.asesor, self._id_de(self.tok))
        self.assertEqual(self._abrir(viejo).status_code, 404)
        self.assertEqual(self._abrir(self.tok).status_code, 404)
        self.assertEqual(self._abrir("tok-que-no-existe-0").status_code, 404)


class HistorialDelAsesorTest(InformePublicoBase):
    def _historial(self):
        r = self.client.get("/api/advisor/reports", headers=self._headers(self.asesor))
        self.assertEqual(r.status_code, 200, r.text)
        return {x["id"]: x for x in r.json()["reports"]}

    def test_el_asesor_si_distingue_los_estados(self):
        rid = self._id_de(self.tok)
        viejo = self._informe(
            self.asesor, self.cliente, "tok-informe-viejo5",
            created_at=(datetime.utcnow() - timedelta(days=200)).isoformat(sep=" ", timespec="seconds"))
        self._revocar(self.asesor, rid)
        h = self._historial()
        self.assertEqual(h[rid]["estado"], "revocado")
        self.assertIsNotNone(h[rid]["revoked_at"])
        self.assertEqual(h[self._id_de(viejo)]["estado"], "vencido")

    def test_uno_activo_se_ve_activo(self):
        self.assertEqual(self._historial()[self._id_de(self.tok)]["estado"], "activo")


if __name__ == "__main__":
    unittest.main()
