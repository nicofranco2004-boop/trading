"""La regla de sólo lectura mira si el pedido ESCRIBE en el cliente, no el verbo
(auditoría E6, 29/10).

Una asesora con permiso de sólo lectura no podía ver la radiografía ni «Tu
lista» de su cliente, ni la tendencia del diario: son POST (mandan una lista)
que sólo leen, y la regla rechazaba todo lo que no fuera GET. Tampoco podía
guardar SUS dibujos mirando el gráfico del cliente, que se guardan en la cuenta
de ella, no en la del cliente.

Lo que se prueba, por HTTP con la cabecera de cliente:
  · con sólo lectura: cartera, lista y en-fechas → 200, y la base del cliente
    queda IGUAL (se cuentan las filas de todas las tablas antes y después);
  · los dibujos de la asesora se guardan, en SU cuenta;
  · lo que sí escribe en el cliente (tesis, alertas, watchlist) sigue en 403;
  · con lectura y escritura, todo como antes.

Corre con: cd backend && python3 -m pytest tests/test_asesor_solo_lectura_post.py
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
from fechas import hoy_art_date

LISTA = {"activos": [{"asset": "AAPL"}, {"asset": "KO"}]}


class AsesorSoloLecturaTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            ids = []
            for quien, tier in (("ase", "advisor"), ("ana", "free"), ("beto", "free")):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?, 'x', 1, 1, ?)", (f"solo-{quien}-{tag}@rendi.test", tier))
                ids.append(cur.lastrowid)
            self.ase, self.ana, self.beto = ids
            for cliente, permiso in ((self.ana, "read"), (self.beto, "read_write")):
                conn.execute(
                    "INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission, status, label) "
                    "VALUES (?, ?, 'linked', ?, 'active', 'C')", (self.ase, cliente, permiso))
            conn.commit()
        self.tok = {u: f"Bearer {main.create_token(u)}" for u in ids}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("alerts_engine.price_for_alert", lambda *a, **k: 100.0),
                   mock.patch("pricing.yahoo._historia", lambda *a, **k: None)]
        for p in self._p:
            p.start()
        getattr(main, "_freno_reiniciar", lambda: None)()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _h(self, cliente):
        return {"Authorization": self.tok[self.ase], "X-Rendi-Client-Id": str(cliente)}

    def _filas(self):
        with main.db_abierta() as conn:
            tablas = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
            return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tablas}

    def _leer(self, cliente):
        hoy = hoy_art_date().isoformat()
        return [
            self.client.post("/api/tecnico/cartera", json=LISTA, headers=self._h(cliente)).status_code,
            self.client.post("/api/tecnico/lista", json=LISTA, headers=self._h(cliente)).status_code,
            self.client.post("/api/tecnico/en-fechas", json={"items": [
                {"id": "1", "asset": "AAPL", "fecha": hoy}]}, headers=self._h(cliente)).status_code]

    def test_solo_lectura_ve_la_radiografia_tu_lista_y_el_diario_sin_escribir_nada(self):
        antes = self._filas()
        self.assertEqual(self._leer(self.ana), [200, 200, 200])
        self.assertEqual(self._filas(), antes, "leer no puede dejar ninguna fila nueva")

    def test_sus_dibujos_se_guardan_en_su_cuenta(self):
        r = self.client.put("/api/tecnico/AAPL/dibujos", json={"dibujos": [
            {"id": "h1", "tipo": "horizontal", "precio": 100}]}, headers=self._h(self.ana))
        self.assertEqual(r.status_code, 200, r.text)
        with main.db_abierta() as conn:
            duenos = [x[0] for x in conn.execute("SELECT user_id FROM dibujos_grafico").fetchall()]
        self.assertEqual(duenos, [self.ase])

    def test_lo_que_escribe_en_el_cliente_sigue_cerrado(self):
        h = self._h(self.ana)
        self.assertEqual(self.client.put("/api/tesis", json={"asset": "AAPL", "texto": "x"}, headers=h).status_code, 403)
        self.assertEqual(self.client.post("/api/alerts", json={"kind": "tecnica", "symbol": "AAPL",
                                                               "senal": "media200"}, headers=h).status_code, 403)
        self.assertEqual(self.client.post("/api/watchlist", json={"symbol": "AAPL"}, headers=h).status_code, 403)
        self.assertEqual(self.client.put("/api/tus-senales/canal", json={"canal": "mail"}, headers=h).status_code, 403)

    def test_con_escritura_todo_como_antes(self):
        self.assertEqual(self._leer(self.beto), [200, 200, 200])
        r = self.client.put("/api/tesis", json={"asset": "AAPL", "texto": "x"}, headers=self._h(self.beto))
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
