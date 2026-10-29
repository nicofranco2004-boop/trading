"""Lo que entra a la descarga de la noche tiene tope por persona, por todas las
puertas (auditoría E4, 29/10).

La noche le pide a Yahoo lo que alguien tiene, sigue, vigila con una alerta
técnica u operó (`velas_diarias._seguimiento`). El 22/10 se le puso tope de 100
a la watchlist; las alertas técnicas fueron una puerta NUEVA a la misma lista,
sin tope en Plus/Pro y con cualquier símbolo con forma de ticker: una cuenta
Pro metió 89 inventados, y lo que nunca se intentó va primero en la fila.

Lo que se prueba, con `velas_diarias.simbolos_a_seguir` (la lista que usa la
corrida real) y lo cargado por HTTP:
  · cada persona aporta hasta `TICKERS_POR_PERSONA`, en orden: lo que tiene, lo
    que sigue, sus alertas técnicas, lo que operó; a otra persona no le cambia nada;
  · una alerta técnica de un activo que no es válido (una vieja, de antes de
    que el alta lo pidiera) no entra.

Corre con: cd backend && python3 -m pytest tests/test_noche_tope.py
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

from fastapi.testclient import TestClient

import main
import velas_diarias


class NocheTopeTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("alerts", "watchlist", "positions", "brokers", "operations"):
                conn.execute(f"DELETE FROM {t}")
            self.uids = []
            for quien in ("ana", "beto"):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?, 'x', 1, 1, 'pro')", (f"noche-{quien}-{tag}@rendi.test",))
                self.uids.append(cur.lastrowid)
            conn.commit()
        self.ana = {"Authorization": f"Bearer {main.create_token(self.uids[0])}"}
        self.beto = {"Authorization": f"Bearer {main.create_token(self.uids[1])}"}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("velas_diarias._cedears_de_byma", lambda: frozenset()),
                   mock.patch("alerts_engine.price_for_alert", lambda *a, **k: 100.0),
                   mock.patch("pricing.yahoo._historia", lambda *a, **k: None)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _ok(self, ruta, cuerpo, h):
        r = self.client.post(ruta, json=cuerpo, headers=h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _noche(self):
        with main.db_abierta() as conn:
            return set(velas_diarias.simbolos_a_seguir(conn))

    def test_cada_persona_aporta_hasta_su_tope_y_en_orden(self):
        self._ok("/api/brokers", {"name": "Schwab", "currency": "USD"}, self.ana)
        self._ok("/api/positions", {"broker": "Schwab", "asset": "AAPL", "quantity": 1,
                                    "buy_price": 100, "asset_type": "STOCK"}, self.ana)
        for s in ("MSFT", "NVDA"):
            self._ok("/api/watchlist", {"symbol": s}, self.ana)
        for s in ("KO", "TSLA"):
            self._ok("/api/alerts", {"kind": "tecnica", "symbol": s, "senal": "media200",
                                     "direction": "either"}, self.ana)
        self._ok("/api/watchlist", {"symbol": "AMZN"}, self.beto)
        with mock.patch("velas_diarias.TICKERS_POR_PERSONA", 4, create=True):
            noche = self._noche()
        self.assertTrue({"AAPL", "MSFT", "NVDA", "KO"} <= noche, noche)
        self.assertNotIn("TSLA", noche, "la quinta de Ana queda afuera")
        self.assertIn("AMZN", noche, "a Beto no le cambia nada")
        # Sin el tope chico, entra todo.
        self.assertIn("TSLA", self._noche())

    def test_una_alerta_tecnica_de_un_activo_invalido_no_entra(self):
        with main.db_abierta() as conn:   # una vieja, de antes de que el alta lo pidiera
            conn.execute("INSERT INTO alerts (user_id, kind, symbol, scope, direction, currency, "
                         "channel, repeat, cooldown_min, armed, active, senal, accion_local) "
                         "VALUES (?, 'tecnica', 'QX0001', 'ticker', 'either', 'USD', 'both', "
                         "'once', 0, 1, 1, 'media200', 0)", (self.uids[1],))
            conn.commit()
        self._ok("/api/alerts", {"kind": "tecnica", "symbol": "KO", "senal": "media200",
                                 "direction": "either"}, self.beto)
        noche = self._noche()
        self.assertNotIn("QX0001", noche)
        self.assertIn("KO", noche)


if __name__ == "__main__":
    unittest.main()
