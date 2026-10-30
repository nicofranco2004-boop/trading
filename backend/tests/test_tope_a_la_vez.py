"""Diez pedidos juntos no pasan un tope (auditoría E5, 29/10).

Los topes por persona se escribían «contá y después guardá». sqlite3 abre la
transacción recién en la primera escritura, así que el conteo corre sin
candado: diez pedidos que llegan juntos cuentan todos «1 de 3» y guardan los
diez (la auditoría: Beto, plan Free, 11 alertas con tope 3). Lo mismo en
Postgres, donde cada conexión ve lo confirmado antes de su conteo.

Para que la prueba no dependa de la suerte, las diez lecturas que DECIDEN se
esperan entre sí (`_Cruce`, de test_dos_pedidos_a_la_vez.py): sin candado, las
diez cuentan lo mismo; con el turno (`main._tomar_turno` antes de contar), el
segundo espera a que el primero guarde y cuenta lo nuevo.

Las puertas con ese patrón en lo publicado: alertas de precio y de %
(`check_alert_quota`), brokers (`check_broker_quota`) y plantillas de
importación (`PLANTILLAS_MAX_POR_CUENTA`, que ya lo hacía bien desde el 11/10).

Corre con: cd backend && python3 -m pytest tests/test_tope_a_la_vez.py
"""
import os
import sys
import tempfile
import threading
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
import renombre_broker
from ai import trade_tickers
from tests.test_dos_pedidos_a_la_vez import _Conexion, _Cruce  # noqa: E402

CONOCIDOS = sorted(trade_tickers.US_TICKERS)
N = 10


class TopeALaVezTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            self.uids = []
            for quien in ("ana", "beto"):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?, 'x', 1, 1, 'free')", (f"alavez-{quien}-{tag}@rendi.test",))
                self.uids.append(cur.lastrowid)
            conn.commit()
        self.beto = {"Authorization": f"Bearer {main.create_token(self.uids[1])}"}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("alerts_engine.price_for_alert", lambda *a, **k: 100.0),
                   mock.patch("pricing.yahoo._historia", lambda *a, **k: None)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _a_la_vez(self, fragmento, pedidos, h=None):
        """Manda los `pedidos` (ruta, cuerpo) juntos; las lecturas con
        `fragmento` se esperan entre sí. Devuelve los códigos ordenados."""
        cruce = _Cruce(fragmento, partes=len(pedidos), espera=3.0)
        real = main.get_db
        codigos = []
        h = h or self.beto
        with mock.patch.object(main, "get_db", lambda: _Conexion(real(), cruce)):
            hilos = [threading.Thread(target=lambda r=r, b=b: codigos.append(
                self.client.post(r, json=b, headers=h).status_code)) for r, b in pedidos]
            for t in hilos:
                t.start()
            for t in hilos:
                t.join(60)
        return sorted(codigos)

    def _contar(self, sql):
        with main.db_abierta() as conn:
            return conn.execute(sql, (self.uids[1],)).fetchone()[0]

    def test_alertas_de_precio(self):
        codigos = self._a_la_vez("COUNT(*) AS c FROM alerts", [
            ("/api/alerts", {"kind": "price_target", "symbol": s, "scope": "ticker",
                             "direction": "above", "threshold": 1000}) for s in CONOCIDOS[:N]])
        self.assertEqual(self._contar("SELECT COUNT(*) FROM alerts WHERE user_id=?"), 3, codigos)

    def test_brokers(self):
        codigos = self._a_la_vez("COUNT(*) AS c FROM brokers", [
            ("/api/brokers", {"name": f"Broker {i}", "currency": "USD"}) for i in range(N)])
        self.assertEqual(self._contar("SELECT COUNT(*) FROM brokers WHERE user_id=? AND parent_broker_id IS NULL"),
                         1, codigos)

    def test_plantillas_de_importacion(self):
        tope = renombre_broker.PLANTILLAS_MAX_POR_CUENTA
        with main.db_abierta() as conn:
            for i in range(tope - 2):
                conn.execute("INSERT INTO import_mappings (user_id, name, mapping_json) VALUES (?, ?, '{}')",
                             (self.uids[1], f"vieja {i}"))
            conn.commit()
        codigos = self._a_la_vez("COUNT(*) FROM import_mappings", [
            ("/api/imports/mappings", {"name": f"nueva {i}", "mapping": {
                "columns": {"date": "Fecha", "asset": "Ticker"}, "defaults": {"broker": "Cocos"}}})
            for i in range(N)])
        self.assertEqual(self._contar("SELECT COUNT(*) FROM import_mappings WHERE user_id=?"), tope, codigos)

    def test_grupos_del_asesor(self):
        """Re-test E5: el patrón no se había propagado; el tope de 30 grupos
        llegó a 32. Mismo turno en clientes, pedidos de vínculo, invitaciones y
        los hechos de la IA (éstos sólo se pasaban en Postgres)."""
        import advisor_groups as ag
        with main.db_abierta() as conn:
            ase = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'advisor')", (f"alavez-ase-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            for i in range(ag.MAX_GROUPS - 2):
                conn.execute("INSERT INTO advisor_groups (advisor_uid, name, rules, excluded) "
                             "VALUES (?, ?, '{\"has_asset\": \"AMZN\"}', '[]')", (ase, f"viejo {i}"))
            conn.commit()
        h = {"Authorization": f"Bearer {main.create_token(ase)}"}
        codigos = self._a_la_vez("COUNT(*) c FROM advisor_groups", [
            ("/api/advisor/groups", {"name": f"nuevo {i}", "rules": {"has_asset": "AMZN"}}) for i in range(N)], h)
        with main.db_abierta() as conn:
            n = conn.execute("SELECT COUNT(*) FROM advisor_groups WHERE advisor_uid=?", (ase,)).fetchone()[0]
        self.assertEqual(n, ag.MAX_GROUPS, codigos)


if __name__ == "__main__":
    unittest.main()
