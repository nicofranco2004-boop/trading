"""Toda lectura pesada pasa por el mismo freno, y una ruta nueva sin él se ve
(re-test E1, ronda 2).

El freno de las lecturas técnicas se ponía ruta por ruta, y cada ronda de la
auditoría encontró otra que lo leía sin él («Tus señales», la ficha, tus tesis,
el peso). Ahora las funciones pesadas están marcadas donde se definen
(`pesado.pesado`), y el conftest pone en rojo cualquier test en el que una de
ellas corrió dentro de un pedido HTTP sin `main._freno_tecnico`.

Lo que se prueba:
  · que el guardián VE una ruta sin freno (una ruta de prueba que lee la serie
    de un activo sin freno queda anotada) y no anota la misma lectura con freno
    ni fuera de un pedido (la noche, los mails);
  · que las funciones marcadas son las que leen mucho: la serie y la ficha, las
    lecturas de muchos activos y la valuación de toda la cartera.

Corre con: cd backend && python3 -m pytest tests/test_lecturas_pesadas_con_freno.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi import Depends, Request
from fastapi.testclient import TestClient

import main
import pesado
import senales_semana
import tecnico


def _ruta_sin_freno(uid: int = Depends(main.get_effective_user)):
    with main.db_abierta() as conn:
        tecnico.serie(conn, "AAPL")
    return {"ok": True}


def _ruta_con_freno(request: Request, uid: int = Depends(main.get_effective_user)):
    with main._freno_tecnico(request, uid, "uno"), main.db_abierta() as conn:
        tecnico.serie(conn, "AAPL")
    return {"ok": True}


class GuardianTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Dos rutas de prueba, sólo mientras corre este archivo: la suite es un
        # proceso y otros tests recorren todas las rutas de la app.
        antes = list(main.app.router.routes)
        main.app.add_api_route("/api/_prueba/pesada_sin_freno", _ruta_sin_freno, methods=["GET"])
        main.app.add_api_route("/api/_prueba/pesada_con_freno", _ruta_con_freno, methods=["GET"])
        cls._nuevas = [r for r in main.app.router.routes if r not in antes]

    @classmethod
    def tearDownClass(cls):
        for r in cls._nuevas:
            main.app.router.routes.remove(r)

    def setUp(self):
        self.client = TestClient(main.app)
        with main.db_abierta() as conn:
            uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"pesado-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        self._p = mock.patch("main._check_rate_limit")
        self._p.start()
        pesado.SIN_FRENO.clear()

    def tearDown(self):
        self._p.stop()
        pesado.SIN_FRENO.clear()    # lo provocado a propósito no pone en rojo a este test

    def test_una_ruta_sin_freno_queda_anotada(self):
        self.assertEqual(self.client.get("/api/_prueba/pesada_sin_freno", headers=self.h).status_code, 200)
        self.assertEqual(pesado.SIN_FRENO, [("GET /api/_prueba/pesada_sin_freno", "serie")])

    def test_con_freno_o_fuera_de_un_pedido_no(self):
        self.assertEqual(self.client.get("/api/_prueba/pesada_con_freno", headers=self.h).status_code, 200)
        with main.db_abierta() as conn:     # la noche, los mails: no es un pedido
            tecnico.serie(conn, "AAPL")
        self.assertEqual(pesado.SIN_FRENO, [])

    def test_las_marcadas_son_las_lecturas_que_pesan(self):
        marcadas = sorted(f"{m.__name__}.{n}" for m in (tecnico, senales_semana)
                          for n, f in vars(m).items() if getattr(f, "_rendi_pesado", False)
                          and getattr(f, "__module__", None) == m.__name__)
        self.assertEqual(marcadas, ["senales_semana.cartera", "tecnico.para_la_cartera", "tecnico.para_la_ficha",
                                    "tecnico.para_la_lista", "tecnico.serie", "tecnico.tendencias_en_fechas"])


if __name__ == "__main__":
    unittest.main()
