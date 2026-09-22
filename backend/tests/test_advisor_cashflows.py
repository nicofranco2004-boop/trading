"""Cobros del libro (asesor), fase 1: /api/advisor/cashflows/positions.

El servidor entrega QUÉ renta fija tiene cada cliente elegido; el cronograma lo
arma el frontend con el mismo motor que la Cartera. Acá se prueba el contrato
del endpoint: alcance (sólo mis clientes, elegidos con casillas), agregación por (cliente, ticker,
moneda), clasificación de renta fija, y permisos.

Corre con: cd backend && python3 -m pytest tests/test_advisor_cashflows.py
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


# Feed de letras como lo publica ArgentinaDatos (valores medidos el 2026-09-22).
# En los tests NUNCA se baja de la red: la fuente se reemplaza en setUp.
_FEED_LETRAS = {
    "S30O6": {"ticker": "S30O6", "price_per_100": 132.45, "tem_pct": 1.71,
              "maturity": "2026-10-30", "currency": "ARS"},
    "S13N6": {"ticker": "S13N6", "price_per_100": 106.04, "tem_pct": 1.98,
              "maturity": "2026-11-13", "currency": "ARS"},
}
_HOY_FIJO = "2026-09-22"   # para que el monto no dependa del día en que corra


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
        # Lote en DÓLARES dentro del broker padre ARS (así lo estampa el importador
        # en un AL30D o un bono liquidado en USD sin sibling): la Cartera lo pone
        # en "Bonos USD" por positions.currency, y acá tiene que salir igual.
        _pos(conn, self.c1, "Cocos", "GD30", 40, asset_type="BOND", currency="USD")
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
        # La fuente de letras no se baja en los tests: la red no es parte del
        # contrato del endpoint (y sin esto cada corrida saldría a internet).
        p = mock.patch.object(main, "_fetch_argentinadatos_letras_raw",
                              lambda: dict(_FEED_LETRAS))
        p.start(); self.addCleanup(p.stop)
        self.http = TestClient(main.app)

    def _hoy_fijo(self):
        """Congela el día argentino: el monto de una letra depende de cuántos
        días le faltan, y un test que se mueve con el calendario se pone en rojo
        solo cuando la letra vence."""
        p = mock.patch.object(main, "_iso_today", lambda: _HOY_FIJO)
        p.start(); self.addCleanup(p.stop)

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
        pos = {(p["client_uid"], p["asset"], p["account_currency"]): p for p in d["positions"]}
        # Dos lotes en pesos → UNA tenencia de 150; la pata dólar aparte.
        self.assertEqual(pos[(self.c1, "AL30", "ARS")]["quantity"], 150)
        self.assertEqual(pos[(self.c1, "AL30", "ARS")]["first_entry_date"], "2026-01-15")
        self.assertEqual(pos[(self.c1, "AL30", "USD")]["quantity"], 200)
        self.assertEqual(pos[(self.c1, "AL30", "USD")]["brokers"], ["Cocos · USD"])
        # Misma regla que la Cartera: la moneda es la de la POSICIÓN, no la del broker.
        self.assertEqual(pos[(self.c1, "GD30", "USD")]["brokers"], ["Cocos"])
        self.assertNotIn((self.c1, "GD30", "ARS"), pos)
        self.assertEqual(pos[(self.c1, "S30O6", "ARS")]["category"], "LETRA")
        self.assertEqual(pos[(self.c1, "FCI:COCOS-AHORRO", "ARS")]["category"], "FCI")
        self.assertEqual(pos[(self.c2, "GD35", "ARS")]["quantity"], 70)
        # Ni la acción, ni la posición cerrada, ni el cliente del otro asesor.
        assets = {(p["client_uid"], p["asset"]) for p in d["positions"]}
        self.assertNotIn((self.c1, "GGAL"), assets)
        self.assertNotIn((self.c1, "AE38"), assets)
        self.assertFalse(any(p["client_uid"] == self.ajeno for p in d["positions"]))
        self.assertIn("tc_mep", d); self.assertIn("as_of", d); self.assertIn("fx_date", d)
        # Orden único: clientes por etiqueta, posiciones siguiendo ese orden.
        self.assertEqual([p["client_uid"] for p in d["positions"]],
                         sorted([p["client_uid"] for p in d["positions"]],
                                key=lambda c: [x["client_uid"] for x in d["clients"]].index(c)))

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

    def test_vinculo_revocado_queda_afuera(self):
        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET status='revoked' WHERE advisor_uid=? AND client_uid=?",
                     (self.adv, self.c2))
        conn.commit(); conn.close()
        d = self._call().json()
        self.assertEqual([c["client_uid"] for c in d["clients"]], [self.c1])
        self.assertFalse(any(p["client_uid"] == self.c2 for p in d["positions"]))
        # Ni pidiéndolo explícitamente.
        d = self._call({"client_uids": [self.c2]}).json()
        self.assertEqual(d["clients"], []); self.assertEqual(d["positions"], [])

    def test_broker_huerfano_se_excluye_y_se_cuenta(self):
        conn = main.get_db()
        _pos(conn, self.c2, "Broker Borrado", "AE38", 500, asset_type="BOND")
        conn.commit(); conn.close()
        d = self._call({"client_uids": [self.c2]}).json()
        self.assertEqual({p["asset"] for p in d["positions"]}, {"GD35"})
        self.assertEqual(d["skipped"], {"orphan_broker": 1})

    # ─── Letras ───────────────────────────────────────────────────────────────
    # El cronograma de un bono sale del catálogo del frontend; una letra no tiene
    # catálogo (no tiene prospecto: devuelve todo junto al vencer, capitalizado),
    # así que su único pago viaja en la respuesta, leído del mercado.

    def test_la_letra_de_la_cartera_viaja_con_su_pago(self):
        self._hoy_fijo()
        d = self._call({"client_uids": [self.c1]}).json()
        self.assertEqual(list(d["letras"]), ["S30O6"])      # la que TIENE el cliente
        l = d["letras"]["S30O6"]
        self.assertEqual(l["maturity"], "2026-10-30")
        self.assertEqual(l["currency"], "ARS")
        self.assertAlmostEqual(l["payout_per_100"], 135.33, places=1)
        # Capitaliza: el pago es mayor que el nominal (100) y que el precio de hoy.
        self.assertGreater(l["payout_per_100"], l["price_per_100"])
        self.assertGreater(l["payout_per_100"], 100.0)

    def test_no_viaja_el_catalogo_entero_sino_lo_que_el_libro_tiene(self):
        self._hoy_fijo()
        d = self._call({"client_uids": [self.c1]}).json()
        self.assertNotIn("S13N6", d["letras"])   # está en la fuente, no en la cartera
        # Un cliente sin letras no recibe ninguna.
        self.assertEqual(self._call({"client_uids": [self.c2]}).json()["letras"], {})

    def test_si_la_fuente_se_cae_no_se_inventa_el_pago(self):
        # Sin catálogo la pantalla muestra la letra en "sin cronograma conocido",
        # que es exactamente lo que hacía antes de esto.
        with mock.patch.object(main, "_fetch_argentinadatos_letras_raw",
                               side_effect=RuntimeError("fuente caída")):
            d = self._call({"client_uids": [self.c1]}).json()
        self.assertEqual(d["letras"], {})
        self.assertTrue(any(p["asset"] == "S30O6" for p in d["positions"]))

    def test_una_letra_vencida_no_viaja(self):
        p = mock.patch.object(main, "_iso_today", lambda: "2026-11-01")  # después del venc.
        p.start(); self.addCleanup(p.stop)
        self.assertEqual(self._call({"client_uids": [self.c1]}).json()["letras"], {})


if __name__ == "__main__":
    unittest.main()
