"""¿Acción argentina o no? — la copia del servidor contra la tabla de casos que
también lee la pantalla (frontend/src/utils/fixtures/accionLocal.json, con
utils/accionLocal.test.js).

Auditoría A 29/10: la regla vivía en cuatro lugares que decían cosas
distintas. «GGAL» seguido desde el buscador era el ADR para Señales y el mail
y la acción de BYMA para Tu lista y la ficha (A1); un CEDEAR sin ratio
conocido era «acción argentina» en la pantalla y CEDEAR en el servidor (P1); y
con data912 caído, el servidor tomaba todo «X.BA» por acción argentina (P2).

Corre con: cd backend && python3 -m pytest tests/test_accion_local.py
"""
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import accion_local  # noqa: E402
from snapshots_job import _broker_name_sets  # noqa: E402

with open(os.path.join(BACKEND, "..", "frontend", "src", "utils", "fixtures", "accionLocal.json"),
          encoding="utf-8") as _f:
    CASOS = json.load(_f)


class AccionLocal(unittest.TestCase):

    def test_lo_que_tenes(self):
        ars, ar_usd = _broker_name_sets(CASOS["brokers"])
        for c in CASOS["lotes"]:
            with self.subTest(c["por_que"]):
                self.assertEqual(accion_local.es_lote_local(c["lote"], ars, ar_usd), c["local"])

    def test_lo_que_seguis(self):
        for c in CASOS["seguidos"]:
            with self.subTest(c["por_que"]):
                self.assertEqual(accion_local.seguido(c["simbolo"]), (c["asset"], c["local"]))

    def test_no_depende_de_data912(self):
        # P2: con data912 caído (lista de CEDEARs de BYMA vacía) la respuesta
        # es la misma: la regla no la mira.
        ars, ar_usd = _broker_name_sets(CASOS["brokers"])
        with mock.patch("velas_diarias._cedears_de_byma", lambda: frozenset()):
            for c in CASOS["lotes"]:
                self.assertEqual(accion_local.es_lote_local(c["lote"], ars, ar_usd), c["local"], c["por_que"])
            for c in CASOS["seguidos"]:
                self.assertEqual(accion_local.seguido(c["simbolo"]), (c["asset"], c["local"]), c["por_que"])


if __name__ == "__main__":
    unittest.main()
