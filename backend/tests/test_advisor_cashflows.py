"""Cobros del libro (asesor), fase 1: /api/advisor/cashflows/positions.

El servidor entrega QUÉ renta fija tiene cada cliente elegido; el cronograma lo
arma el frontend con el mismo motor que la Cartera. Acá se prueba el contrato
del endpoint: alcance (sólo mis clientes), agregación por (cliente, ticker,
moneda), clasificación de renta fija, y permisos.

Corre con: cd backend && python3 -m pytest tests/test_advisor_cashflows.py
"""
import os
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _TMP.close()
os.environ["DB_PATH"] = _TMP.name

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _new_user(conn, email, approved=1, tier=None):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,?,?)",
        (email, "x", approved, tier))
    return cur.lastrowid


def _link(conn, advisor, client, label, permission="read_write"):
    conn.execute(
        """INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission, status, label)
           VALUES (?,?,?,?,?,?)""", (advisor, client, "managed", permission, "active", label))


def _pos(conn, uid, broker, asset, qty, asset_type="", currency=None, entry_date=None):
    conn.execute(
        """INSERT INTO positions (user_id, broker, asset, asset_type, quantity, invested, is_cash, currency, entry_date)
           VALUES (?,?,?,?,?,?,0,?,?)""",
        (uid, broker, asset, asset_type, qty, qty * 100.0, currency, entry_date))


class CobrosLibro(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        tag = uuid.uuid4().hex[:8]
        self.adv = _new_user(conn, f"asesor-{tag}@rendi.test", tier="advisor")
        self.otro_adv = _new_user(conn, f"otro-asesor-{tag}@rendi.test", tier="advisor")
        self.c1 = _new_user(conn, f"c1-{tag}@rendi.test", approved=0)
        self.c2 = _new_user(conn, f"c2-{tag}@rendi.test", approved=0)
        self.ajeno = _new_user(conn, f"ajeno-{tag}@rendi.test", approved=0)
        _link(conn, self.adv, self.c1, "Ferreyra")
        _link(conn, self.adv, self.c2, "Ocampo", permission="read")
        _link(conn, self.otro_adv, self.ajeno, "De otro")
        # c1: Cocos (ARS) con sibling USD. Dos lotes de AL30 en pesos + uno en la
        # pata dólar; una letra; una acción (no viaja); un FCI.
        cur = conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                           (self.c1, "Cocos", "ARS"))
        conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
                     (self.c1, "Cocos · USD", "USD", cur.lastrowid))
        _pos(conn, self.c1, "Cocos", "AL30", 100, asset_type="BOND", entry_date="2026-03-01")
        _pos(conn, self.c1, "Cocos", "AL30", 50, asset_type="BOND", entry_date="2026-01-15")
        _pos(conn, self.c1, "Cocos · USD", "AL30", 200, asset_type="BOND", currency="USD")
        _pos(conn, self.c1, "Cocos", "S30O6", 1000)                 # letra: por patrón del ticker
        _pos(conn, self.c1, "Cocos", "GGAL", 300)                   # acción: no es renta fija
        _pos(conn, self.c1, "Cocos", "FCI:COCOS-AHORRO", 500, asset_type="FUND")
        _pos(conn, self.c1, "Cocos", "AE38", 0)                     # cerrada: no viaja
        # c2: Balanz ARS con un GD35
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (self.c2, "Balanz", "ARS"))
        _pos(conn, self.c2, "Balanz", "GD35", 70, asset_type="BOND")
        # el cliente de OTRO asesor también tiene bonos
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (self.ajeno, "IOL", "ARS"))
        _pos(conn, self.ajeno, "IOL", "AL30", 999, asset_type="BOND")
        conn.commit(); conn.close()
        self.http = TestClient(main.app)

    def tearDown(self):
        conn = main.get_db()
        conn.execute("DELETE FROM advisor_clients WHERE advisor_uid IN (?,?)", (self.adv, self.otro_adv))
        conn.commit(); conn.close()

    def _hdr(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _call(self, body=None, uid=None):
        return self.http.post("/api/advisor/cashflows/positions", json=body or {},
                              headers=self._hdr(uid or self.adv))

    def test_requiere_plan_asesor(self):
        r = self._call(uid=self.c1)
        self.assertEqual(r.status_code, 403)

    def test_todo_el_libro_agregado_por_cliente_ticker_y_moneda(self):
        r = self._call()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual([c["label"] for c in d["clients"]], ["Ferreyra", "Ocampo"])
        self.assertTrue(all(c["has_fixed_income"] for c in d["clients"]))
        pos = {(p["client_uid"], p["asset"], p["currency"]): p for p in d["positions"]}
        # Dos lotes en pesos → UNA tenencia de 150; la pata dólar aparte.
        self.assertEqual(pos[(self.c1, "AL30", "ARS")]["quantity"], 150)
        self.assertEqual(pos[(self.c1, "AL30", "ARS")]["first_entry_date"], "2026-01-15")
        self.assertEqual(pos[(self.c1, "AL30", "USD")]["quantity"], 200)
        self.assertEqual(pos[(self.c1, "AL30", "USD")]["brokers"], ["Cocos · USD"])
        self.assertEqual(pos[(self.c1, "S30O6", "ARS")]["category"], "LETRA")
        self.assertEqual(pos[(self.c1, "FCI:COCOS-AHORRO", "ARS")]["category"], "FCI")
        self.assertEqual(pos[(self.c2, "GD35", "ARS")]["quantity"], 70)
        # Ni la acción, ni la posición cerrada, ni el cliente del otro asesor.
        assets = {(p["client_uid"], p["asset"]) for p in d["positions"]}
        self.assertNotIn((self.c1, "GGAL"), assets)
        self.assertNotIn((self.c1, "AE38"), assets)
        self.assertFalse(any(p["client_uid"] == self.ajeno for p in d["positions"]))
        self.assertIn("tc_mep", d); self.assertIn("as_of", d)

    def test_subconjunto_de_clientes(self):
        d = self._call({"client_uids": [self.c2]}).json()
        self.assertEqual([c["client_uid"] for c in d["clients"]], [self.c2])
        self.assertEqual({p["asset"] for p in d["positions"]}, {"GD35"})

    def test_un_cliente_ajeno_en_la_lista_se_ignora(self):
        d = self._call({"client_uids": [self.c1, self.ajeno]}).json()
        self.assertEqual([c["client_uid"] for c in d["clients"]], [self.c1])
        self.assertFalse(any(p["client_uid"] == self.ajeno for p in d["positions"]))

    def test_solo_lectura_alcanza(self):
        # c2 está vinculado con permission='read': igual viaja (no escribimos nada).
        d = self._call({"client_uids": [self.c2]}).json()
        self.assertEqual(len(d["positions"]), 1)

    def test_cliente_sin_renta_fija_no_rompe_y_se_marca(self):
        conn = main.get_db()
        c3 = _new_user(conn, f"c3-{uuid.uuid4().hex[:6]}@rendi.test", approved=0)
        _link(conn, self.adv, c3, "Sin bonos")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (c3, "IOL", "ARS"))
        _pos(conn, c3, "IOL", "YPFD", 10)
        conn.commit(); conn.close()
        d = self._call({"client_uids": [c3]}).json()
        self.assertEqual(d["positions"], [])
        self.assertEqual(d["clients"], [{"client_uid": c3, "label": "Sin bonos", "has_fixed_income": False}])

    def test_grupo_inexistente_es_404(self):
        self.assertEqual(self._call({"group_id": 999999}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
