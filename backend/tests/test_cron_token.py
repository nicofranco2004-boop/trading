"""RENDI-05: la puerta común de los crons externos (_validar_cron_token).

Antes cada cron comparaba el token con `!=` (cortaba en la primera letra distinta
→ adivinable a cronómetro) y lo aceptaba por la URL sin aviso. Ahora hay un helper
único: hmac.compare_digest, cabecera X-Cron-Token preferida, ?token= en modo compat
con aviso, y falla cerrado sin token configurado."""
import os
import sys
import unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402

TOK = "token-de-prueba-cron-123456789"


class _FakeReq:
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}
        self.url = type("U", (), {"path": "/api/test/cron"})()


class ValidarCronTokenTest(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("ALERTS_CRON_TOKEN")
        os.environ["ALERTS_CRON_TOKEN"] = TOK

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("ALERTS_CRON_TOKEN", None)
        else:
            os.environ["ALERTS_CRON_TOKEN"] = self._prev

    def _validar(self, **kw):
        main._validar_cron_token(_FakeReq(**kw), "ALERTS_CRON_TOKEN")

    def test_cabecera_correcta_pasa(self):
        self._validar(headers={"x-cron-token": TOK})  # no levanta

    def test_query_correcta_pasa_en_compat(self):
        self._validar(query={"token": TOK})  # no levanta

    def test_token_incorrecto_401(self):
        with self.assertRaises(HTTPException) as e:
            self._validar(headers={"x-cron-token": "otro-distinto"})
        self.assertEqual(e.exception.status_code, 401)

    def test_token_casi_igual_mismo_largo_401(self):
        # compare_digest no "pasa" por tener casi todo igual: cambia la última letra.
        with self.assertRaises(HTTPException) as e:
            self._validar(headers={"x-cron-token": TOK[:-1] + "X"})
        self.assertEqual(e.exception.status_code, 401)

    def test_sin_token_en_el_pedido_401(self):
        with self.assertRaises(HTTPException) as e:
            self._validar()
        self.assertEqual(e.exception.status_code, 401)

    def test_sin_variable_configurada_falla_cerrado_503(self):
        os.environ.pop("ALERTS_CRON_TOKEN", None)
        with self.assertRaises(HTTPException) as e:
            self._validar(headers={"x-cron-token": TOK})
        self.assertEqual(e.exception.status_code, 503)

    def test_fallback_a_segundo_nombre(self):
        # advisor/market brief aceptan su token O el de snapshots como respaldo.
        os.environ.pop("ALERTS_CRON_TOKEN", None)
        prev = os.environ.get("SNAPSHOT_CRON_TOKEN")
        os.environ["SNAPSHOT_CRON_TOKEN"] = TOK
        try:
            main._validar_cron_token(_FakeReq(headers={"x-cron-token": TOK}),
                                     "ADVISOR_BRIEF_TOKEN", "SNAPSHOT_CRON_TOKEN")
        finally:
            if prev is None:
                os.environ.pop("SNAPSHOT_CRON_TOKEN", None)
            else:
                os.environ["SNAPSHOT_CRON_TOKEN"] = prev


class CronEndpointCableadoTest(unittest.TestCase):
    """El endpoint real pasa por el helper: token correcto por cabecera entra,
    token mal da 401, sin variable configurada da 503."""

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self._prev = os.environ.get("IOL_LAB_CRON_TOKEN")
        os.environ["IOL_LAB_CRON_TOKEN"] = TOK

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("IOL_LAB_CRON_TOKEN", None)
        else:
            os.environ["IOL_LAB_CRON_TOKEN"] = self._prev

    def test_cabecera_correcta_no_da_401(self):
        r = self.client.post("/api/iol/lab/run-cron", headers={"X-Cron-Token": TOK})
        self.assertNotIn(r.status_code, (401, 503))

    def test_token_mal_da_401(self):
        r = self.client.post("/api/iol/lab/run-cron", headers={"X-Cron-Token": "mal"})
        self.assertEqual(r.status_code, 401)

    def test_sin_variable_da_503(self):
        os.environ.pop("IOL_LAB_CRON_TOKEN", None)
        r = self.client.post("/api/iol/lab/run-cron", headers={"X-Cron-Token": TOK})
        self.assertEqual(r.status_code, 503)
