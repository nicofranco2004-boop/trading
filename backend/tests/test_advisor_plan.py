"""Plan Asesor F0–F2: resolver de contexto de cliente (get_effective_user),
endpoints /api/advisor/* y operación grupal.

get_effective_user es LA superficie de seguridad nueva: un bug filtra la
cartera completa de un cliente al asesor equivocado. Esta suite es la batería
IDOR dedicada — cualquier cambio al resolver tiene que pasar por acá.

Corre con: cd backend && python3 -m pytest tests/test_advisor_plan.py
"""
import os
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
from fastapi.testclient import TestClient
from ai import quota, plan


def _new_user(conn, email, tier=None):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,?)",
        (email, "x", tier))
    return cur.lastrowid


def _link(conn, advisor_uid, client_uid, link_type="managed",
          permission="read_write", status="active", label="Cliente"):
    conn.execute(
        """INSERT INTO advisor_clients
               (advisor_uid, client_uid, link_type, permission, status, label)
           VALUES (?,?,?,?,?,?)""",
        (advisor_uid, client_uid, link_type, permission, status, label))


class AdvisorBase(unittest.TestCase):
    """Fixture común: un asesor (tier advisor), un cliente shadow con broker
    ARS + cash, y un segundo usuario suelto para los tests de IDOR."""

    def setUp(self):
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        self.advisor = _new_user(conn, f"asesor-{tag}@rendi.test", tier="advisor")
        self.client_uid = _new_user(conn, f"cliente-{tag}@rendi.test")
        self.stranger = _new_user(conn, f"ajeno-{tag}@rendi.test")
        conn.execute("UPDATE users SET managed_by=? WHERE id=?",
                     (self.advisor, self.client_uid))
        _link(conn, self.advisor, self.client_uid, label="Juan P")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.client_uid, "Cocos", "ARS"))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.advisor, "IOL", "ARS"))
        conn.commit()
        conn.close()
        self.http = TestClient(main.app)

    def _hdr(self, uid, client_ctx=None):
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        if client_ctx is not None:
            h["X-Rendi-Client-Id"] = str(client_ctx)
        return h

    def _add_pos(self, uid_headers, **kw):
        body = dict(broker="Cocos", asset="AL30", quantity=10, buy_price=100)
        body.update(kw)
        return self.http.post("/api/positions", json=body, headers=uid_headers)


# ─── F0: resolver / IDOR ─────────────────────────────────────────────────────

class ResolverIdorTest(AdvisorBase):

    def test_sin_header_devuelve_lo_propio(self):
        r = self.http.get("/api/positions", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        # El asesor no tiene posiciones propias no-cash
        self.assertEqual([p for p in r.json() if not p.get("is_cash")], [])

    def test_ctx_valido_lee_la_cuenta_del_cliente(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, buy_price, is_cash)
               VALUES (?,?,?,?,?,0)""",
            (self.client_uid, "Cocos", "GGAL", 5, 1000))
        conn.commit(); conn.close()
        r = self.http.get("/api/positions",
                          headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 200)
        assets = [p["asset"] for p in r.json() if not p.get("is_cash")]
        self.assertEqual(assets, ["GGAL"])

    def test_sin_vinculo_403(self):
        r = self.http.get("/api/positions",
                          headers=self._hdr(self.advisor, client_ctx=self.stranger))
        self.assertEqual(r.status_code, 403)

    def test_vinculo_revocado_403(self):
        conn = main.get_db()
        conn.execute(
            "UPDATE advisor_clients SET status='revoked' WHERE advisor_uid=? AND client_uid=?",
            (self.advisor, self.client_uid))
        conn.commit(); conn.close()
        r = self.http.get("/api/positions",
                          headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 403)

    def test_otro_usuario_no_accede_al_cliente_ajeno(self):
        # El ataque IDOR clásico: un user cualquiera manda el header apuntando
        # al cliente de OTRO asesor.
        r = self.http.get("/api/positions",
                          headers=self._hdr(self.stranger, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 403)

    def test_header_malformado_400(self):
        h = self._hdr(self.advisor)
        h["X-Rendi-Client-Id"] = "abc"
        r = self.http.get("/api/positions", headers=h)
        self.assertEqual(r.status_code, 400)

    def test_prefijo_exento_ignora_el_header(self):
        # /api/auth/me con ctx activo tiene que devolver al ASESOR (el shell
        # muestra su identidad), nunca al cliente.
        r = self.http.get("/api/auth/me",
                          headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["id"], self.advisor)

    def test_ctx_a_uno_mismo_es_noop(self):
        r = self.http.get("/api/positions",
                          headers=self._hdr(self.advisor, client_ctx=self.advisor))
        self.assertEqual(r.status_code, 200)

    def test_write_con_vinculo_read_es_403(self):
        conn = main.get_db()
        conn.execute(
            "UPDATE advisor_clients SET permission='read' WHERE advisor_uid=? AND client_uid=?",
            (self.advisor, self.client_uid))
        conn.commit(); conn.close()
        # GET sigue funcionando…
        r = self.http.get("/api/positions",
                          headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 200)
        # …pero el POST se bloquea en el resolver
        r = self._add_pos(self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 403)

    def test_write_managed_escribe_en_la_cuenta_del_cliente(self):
        r = self._add_pos(self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        owner = conn.execute("SELECT user_id FROM positions WHERE id=?",
                             (r.json()["id"],)).fetchone()["user_id"]
        n_advisor = conn.execute(
            "SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0",
            (self.advisor,)).fetchone()["c"]
        conn.close()
        self.assertEqual(owner, self.client_uid)
        self.assertEqual(n_advisor, 0)  # nada se filtró a la cuenta del asesor

    def test_plan_features_con_ctx_es_lente_pro(self):
        r = self.http.get("/api/plan/features",
                          headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["tier"], "pro")          # lente Pro sobre el cliente
        self.assertTrue(d["client_ctx"])
        # Sin ctx: el tier real del asesor
        r2 = self.http.get("/api/plan/features", headers=self._hdr(self.advisor))
        self.assertEqual(r2.json()["tier"], "advisor")
        self.assertFalse(r2.json()["client_ctx"])


# ─── Tier 'advisor' ──────────────────────────────────────────────────────────

class AdvisorTierTest(AdvisorBase):

    def test_get_tier_advisor(self):
        conn = main.get_db()
        self.assertEqual(quota.get_tier(conn, self.advisor), "advisor")
        conn.close()

    def test_limits_declarados(self):
        self.assertIn("advisor", quota.LIMITS)
        self.assertIn("advisor", plan.PLAN_LIMITS)
        # Mismas claves que el resto de los tiers (el contrato que validan
        # los tests existentes de plan)
        self.assertEqual(set(plan.PLAN_LIMITS["advisor"]["can_access"].keys()),
                         set(plan.PLAN_LIMITS["pro"]["can_access"].keys()))


# ─── F1: gestión de clientes ─────────────────────────────────────────────────

class AdvisorClientsTest(AdvisorBase):

    def test_endpoints_gateados_por_tier(self):
        r = self.http.get("/api/advisor/clients", headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)
        r = self.http.post("/api/advisor/clients", json={"label": "X"},
                           headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)

    def test_crear_cliente_managed(self):
        r = self.http.post("/api/advisor/clients", json={"label": "Ana G"},
                           headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        cid = r.json()["client_uid"]
        conn = main.get_db()
        u = conn.execute("SELECT * FROM users WHERE id=?", (cid,)).fetchone()
        link = conn.execute(
            "SELECT * FROM advisor_clients WHERE advisor_uid=? AND client_uid=?",
            (self.advisor, cid)).fetchone()
        conn.close()
        self.assertEqual(u["managed_by"], self.advisor)
        self.assertEqual(u["approved"], 0)            # no puede loguear (hasta F4)
        self.assertIn("shadow.rendi.internal", u["email"])
        self.assertEqual(link["status"], "active")
        self.assertEqual(link["permission"], "read_write")
        # Y el ctx ya funciona sobre el cliente nuevo
        rr = self.http.get("/api/positions",
                           headers=self._hdr(self.advisor, client_ctx=cid))
        self.assertEqual(rr.status_code, 200)

    def test_roster_lista_aum_null_sin_snapshot(self):
        r = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        clients = r.json()["clients"]
        me = [c for c in clients if c["client_uid"] == self.client_uid]
        self.assertEqual(len(me), 1)
        self.assertEqual(me[0]["label"], "Juan P")
        self.assertIsNone(me[0]["aum_usd"])           # sin snapshot todavía
        self.assertEqual(me[0]["brokers_count"], 1)

    def test_roster_aum_del_ultimo_snapshot(self):
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested) VALUES (?,?,?,?)",
                (self.client_uid, "2026-07-20", 1000.0, 900.0))
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested) VALUES (?,?,?,?)",
                (self.client_uid, "2026-07-21", 1234.5, 900.0))
            conn.commit()
        finally:
            conn.close()
        r = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor))
        me = [c for c in r.json()["clients"] if c["client_uid"] == self.client_uid][0]
        self.assertEqual(me["aum_usd"], 1234.5)
        self.assertEqual(me["aum_date"], "2026-07-21")

    def test_patch_label_y_notas(self):
        r = self.http.patch(f"/api/advisor/clients/{self.client_uid}",
                            json={"label": "Juan Pérez", "notes": "fee 1% · conservador"},
                            headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        r2 = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor))
        me = [c for c in r2.json()["clients"] if c["client_uid"] == self.client_uid][0]
        self.assertEqual(me["label"], "Juan Pérez")
        self.assertEqual(me["notes"], "fee 1% · conservador")

    def test_revoke_saca_del_roster_y_corta_el_ctx(self):
        r = self.http.post(f"/api/advisor/clients/{self.client_uid}/revoke",
                           headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        r2 = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor))
        self.assertEqual([c for c in r2.json()["clients"]
                          if c["client_uid"] == self.client_uid], [])
        r3 = self.http.get("/api/positions",
                           headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r3.status_code, 403)

    def test_patch_de_cliente_ajeno_404(self):
        # Otro asesor no puede tocar el vínculo de este
        conn = main.get_db()
        otro = _new_user(conn, f"asesor2-{uuid.uuid4().hex[:10]}@rendi.test", tier="advisor")
        conn.commit(); conn.close()
        r = self.http.patch(f"/api/advisor/clients/{self.client_uid}",
                            json={"label": "hackeado"}, headers=self._hdr(otro))
        self.assertEqual(r.status_code, 404)

    def test_lifecycle_no_borra_shadows(self):
        # _delete_unverified_accounts borra signups abandonados (email_verified=0
        # > 7 días). Los shadows del asesor cumplen ese perfil POR DISEÑO — el
        # guard managed_by IS NULL es lo único que los protege.
        #
        # Corre sobre una DB TEMPORAL aislada: contra el dev-db, la función
        # procesaría todo el backlog de users legacy en una transacción gigante
        # (lenta + write-lock que voltea al resto de la suite).
        import sqlite3, tempfile
        from billing import subscriptions as subs
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT,
                    email_verified INTEGER DEFAULT 0, created_at TEXT,
                    managed_by INTEGER);
                CREATE TABLE positions (user_id INTEGER);
                CREATE TABLE operations (user_id INTEGER);
                CREATE TABLE monthly_entries (user_id INTEGER);
                CREATE TABLE email_verification_codes (user_id INTEGER);
                CREATE TABLE brokers (user_id INTEGER);
            """)
            conn.execute(
                "INSERT INTO users (id, email, email_verified, created_at, managed_by) "
                "VALUES (1, 'shadow@shadow.rendi.internal', 0, '2020-01-01T00:00:00', 99)")
            conn.execute(
                "INSERT INTO users (id, email, email_verified, created_at, managed_by) "
                "VALUES (2, 'abandonado@x.com', 0, '2020-01-01T00:00:00', NULL)")
            conn.commit()
            subs._delete_unverified_accounts(conn)
            alive = {r["id"] for r in conn.execute("SELECT id FROM users").fetchall()}
            conn.close()
        self.assertIn(1, alive)        # el shadow sobrevive
        self.assertNotIn(2, alive)     # el signup abandonado se borra como siempre


# ─── F2: operación grupal ────────────────────────────────────────────────────

class GroupOpTest(AdvisorBase):

    def setUp(self):
        super().setUp()
        # Segundo cliente con broker propio (Balanz) y un tercero SIN broker
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        self.client2 = _new_user(conn, f"cliente2-{tag}@rendi.test")
        self.client3 = _new_user(conn, f"cliente3-{tag}@rendi.test")
        for c in (self.client2, self.client3):
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, c))
            _link(conn, self.advisor, c, label=f"C{c}")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.client2, "Balanz", "ARS"))
        conn.commit(); conn.close()

    def _cash(self, uid, broker):
        conn = main.get_db()
        row = conn.execute(
            "SELECT COALESCE(SUM(invested),0) v FROM positions "
            "WHERE user_id=? AND broker=? AND is_cash=1", (uid, broker)).fetchone()
        conn.close()
        return float(row["v"] or 0)

    def test_prep_sugiere_broker_con_el_activo(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, buy_price, is_cash)
               VALUES (?,?,?,?,?,0)""", (self.client_uid, "Cocos", "AL30", 3, 100))
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/group-op/prep?asset=AL30",
                          headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        by_uid = {c["client_uid"]: c for c in r.json()["clients"]}
        self.assertEqual(by_uid[self.client_uid]["suggested_broker"], "Cocos")
        self.assertTrue(by_uid[self.client_uid]["has_asset"])
        self.assertEqual(by_uid[self.client2]["suggested_broker"], "Balanz")  # único broker
        self.assertIsNone(by_uid[self.client3]["suggested_broker"])           # sin brokers

    def test_group_op_aplica_validos_y_saltea_invalidos(self):
        body = {
            "asset": "AL30", "currency": "ARS", "entry_date": "2026-07-22",
            "rows": [
                {"client_uid": self.client_uid, "broker": "Cocos", "quantity": 100, "buy_price": 58.9},
                {"client_uid": self.client2, "broker": "Balanz", "quantity": 50, "buy_price": 58.9},
                {"client_uid": self.client3, "broker": "NoExiste", "quantity": 10, "buy_price": 58.9},
                {"client_uid": self.stranger, "broker": "Cocos", "quantity": 10, "buy_price": 58.9},
            ],
        }
        r = self.http.post("/api/advisor/group-op", json=body, headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(len(d["applied"]), 2)
        reasons = {s["client_uid"]: s["reason"] for s in d["skipped"]}
        self.assertIn(self.client3, reasons)     # broker inexistente
        self.assertIn(self.stranger, reasons)    # sin vínculo
        # Las posiciones quedaron en las cuentas correctas
        conn = main.get_db()
        for cid, qty in ((self.client_uid, 100), (self.client2, 50)):
            row = conn.execute(
                "SELECT quantity FROM positions WHERE user_id=? AND asset='AL30' AND is_cash=0",
                (cid,)).fetchone()
            self.assertIsNotNone(row, f"cliente {cid}")
            self.assertEqual(row["quantity"], qty)
        conn.close()
        self.batch_id = d["batch_id"]

    def test_undo_borra_y_reacredita(self):
        cash_before = self._cash(self.client_uid, "Cocos")
        body = {
            "asset": "GD30", "currency": "ARS",
            "rows": [{"client_uid": self.client_uid, "broker": "Cocos",
                      "quantity": 10, "buy_price": 100}],
        }
        r = self.http.post("/api/advisor/group-op", json=body, headers=self._hdr(self.advisor))
        batch = r.json()["batch_id"]
        r2 = self.http.post(f"/api/advisor/group-op/{batch}/undo",
                            headers=self._hdr(self.advisor))
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(len(r2.json()["undone"]), 1)
        conn = main.get_db()
        pos = conn.execute(
            "SELECT 1 FROM positions WHERE user_id=? AND asset='GD30' AND is_cash=0",
            (self.client_uid,)).fetchone()
        conn.close()
        self.assertIsNone(pos)                     # la posición del lote se fue
        # Cash neto igual que antes (débito + autodepósito + re-crédito = neutro
        # respecto del costo; el autodepósito queda documentado como flujo)
        self.assertAlmostEqual(self._cash(self.client_uid, "Cocos"),
                               cash_before + 1000, places=4)
        # Idempotencia: segundo undo → 409
        r3 = self.http.post(f"/api/advisor/group-op/{batch}/undo",
                            headers=self._hdr(self.advisor))
        self.assertEqual(r3.status_code, 409)

    def test_undo_de_lote_ajeno_404(self):
        body = {"asset": "GD35",
                "rows": [{"client_uid": self.client_uid, "broker": "Cocos",
                          "quantity": 1, "buy_price": 100}]}
        r = self.http.post("/api/advisor/group-op", json=body, headers=self._hdr(self.advisor))
        batch = r.json()["batch_id"]
        conn = main.get_db()
        otro = _new_user(conn, f"asesor3-{uuid.uuid4().hex[:10]}@rendi.test", tier="advisor")
        conn.commit(); conn.close()
        r2 = self.http.post(f"/api/advisor/group-op/{batch}/undo", headers=self._hdr(otro))
        self.assertEqual(r2.status_code, 404)


if __name__ == "__main__":
    unittest.main()


# ─── Fixes del review adversarial (regresiones) ─────────────────────────────

class ReviewFixesTest(AdvisorBase):

    def test_delete_me_en_ctx_borra_al_ASESOR_con_cascada_de_shadows(self):
        # BLOCKER del review: DELETE /api/me con ctx activo borraba la cuenta
        # del CLIENTE apuntado. /api/me es prefijo exento → siempre borra la
        # cuenta PROPIA del logueado. Semántica de la cascada (audit):
        #   • shadows managed del asesor → se borran CON él (si no, quedan
        #     como PII financiera huérfana sin login ni camino de borrado);
        #   • un cliente REAL vinculado (managed_by NULL) → sobrevive, solo
        #     pierde el vínculo.
        conn = main.get_db()
        real_linked = _new_user(conn, f"real-{uuid.uuid4().hex[:8]}@rendi.test")
        _link(conn, self.advisor, real_linked, link_type="linked",
              permission="read", label="Real")
        conn.commit(); conn.close()

        r = self.http.delete("/api/me",
                             headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        advisor_alive = conn.execute("SELECT 1 FROM users WHERE id=?", (self.advisor,)).fetchone()
        shadow_alive = conn.execute("SELECT 1 FROM users WHERE id=?", (self.client_uid,)).fetchone()
        shadow_data = conn.execute("SELECT 1 FROM brokers WHERE user_id=?", (self.client_uid,)).fetchone()
        real_alive = conn.execute("SELECT 1 FROM users WHERE id=?", (real_linked,)).fetchone()
        links = conn.execute("SELECT 1 FROM advisor_clients WHERE advisor_uid=?", (self.advisor,)).fetchone()
        conn.close()
        self.assertIsNone(advisor_alive)    # se borró el ASESOR (el logueado)
        self.assertIsNone(shadow_alive)     # el shadow managed cascadeó
        self.assertIsNone(shadow_data)      # …con sus datos (brokers incluidos)
        self.assertIsNotNone(real_alive)    # el cliente REAL vinculado sobrevive
        self.assertIsNone(links)            # y todos los vínculos se limpiaron

    def test_shadow_managed_resuelve_tier_pro(self):
        # Lente Pro server-side: mientras la cuenta esté administrada, TODOS
        # los gates la tratan como Pro (sin esto: 403 "Free permite 1 broker"
        # al cargar el 2do broker del cliente = workflow central roto).
        conn = main.get_db()
        self.assertEqual(quota.get_tier(conn, self.client_uid), "pro")
        conn.close()

    def test_cliente_managed_puede_multi_broker(self):
        # El gate de brokers ya no corta en 1 para cuentas administradas
        h = self._hdr(self.advisor, client_ctx=self.client_uid)
        r2 = self.http.post("/api/brokers", json={"name": "IOL2", "currency": "ARS"}, headers=h)
        r3 = self.http.post("/api/brokers", json={"name": "Binance2", "currency": "USDT"}, headers=h)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r3.status_code, 200, r3.text)

    def test_group_op_saltea_fila_con_moneda_cruzada(self):
        # Lote ARS asignado a un broker USD del cliente → fila salteada con
        # razón explícita (antes: lote ARS adentro de cuenta dólar = FIFO roto)
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.client_uid, "Schwab", "USD"))
        conn.commit(); conn.close()
        body = {"asset": "AL30", "currency": "ARS",
                "rows": [{"client_uid": self.client_uid, "broker": "Schwab",
                          "quantity": 10, "buy_price": 58.9}]}
        r = self.http.post("/api/advisor/group-op", json=body, headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 400)  # ninguna fila válida

    def test_undo_parcial_no_marca_lote_y_permite_reintento(self):
        # Lote a 2 clientes → revocar B → undo revierte A y NO estampa
        # undone_at → re-activar B → segundo undo revierte B y cierra el lote.
        conn = main.get_db()
        tagb = uuid.uuid4().hex[:8]
        b = _new_user(conn, f"cliente-b-{tagb}@rendi.test")
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, b))
        _link(conn, self.advisor, b, label="B")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (b, "Cocos", "ARS"))
        conn.commit(); conn.close()

        body = {"asset": "GD41", "currency": "ARS",
                "rows": [
                    {"client_uid": self.client_uid, "broker": "Cocos", "quantity": 5, "buy_price": 100},
                    {"client_uid": b, "broker": "Cocos", "quantity": 7, "buy_price": 100},
                ]}
        r = self.http.post("/api/advisor/group-op", json=body, headers=self._hdr(self.advisor))
        batch = r.json()["batch_id"]

        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET status='revoked' WHERE advisor_uid=? AND client_uid=?",
                     (self.advisor, b))
        conn.commit(); conn.close()

        r1 = self.http.post(f"/api/advisor/group-op/{batch}/undo", headers=self._hdr(self.advisor))
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json()["fully_undone"])
        self.assertEqual(len(r1.json()["undone"]), 1)   # A revertido, B pendiente

        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET status='active' WHERE advisor_uid=? AND client_uid=?",
                     (self.advisor, b))
        conn.commit(); conn.close()

        r2 = self.http.post(f"/api/advisor/group-op/{batch}/undo", headers=self._hdr(self.advisor))
        self.assertEqual(r2.status_code, 200, r2.text)   # NO 409: el lote no estaba cerrado
        self.assertTrue(r2.json()["fully_undone"])
        conn = main.get_db()
        pos_b = conn.execute(
            "SELECT 1 FROM positions WHERE user_id=? AND asset='GD41' AND is_cash=0", (b,)).fetchone()
        conn.close()
        self.assertIsNone(pos_b)
        # Tercer undo → ahora sí 409
        r3 = self.http.post(f"/api/advisor/group-op/{batch}/undo", headers=self._hdr(self.advisor))
        self.assertEqual(r3.status_code, 409)

    def test_feedback_exento_se_atribuye_al_asesor(self):
        # /api/feedback es prefijo exento: una recomendación mandada en ctx
        # sale a nombre del ASESOR, no del shadow (email sintético inservible)
        r = self.http.post("/api/feedback/recommendation",
                           json={"subject": "Plan Asesor", "body": "quiero mas metricas de libro"},
                           headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        # La intención: el RESOLVER exime /api/feedback (no 400/403 de ctx).
        # En sandbox Resend no está configurado → 503 send_failed es aceptable
        # (significa que llegó hasta el envío con el uid del ASESOR resuelto).
        self.assertNotIn(r.status_code, (400, 403), r.text)


# ─── F3: el libro (/api/advisor/book) ────────────────────────────────────────

class AdvisorBookTest(AdvisorBase):

    def setUp(self):
        super().setUp()
        conn = main.get_db()
        # FX conocido para aserciones (OR REPLACE: clave = fecha de hoy)
        import datetime as _d
        self.today = _d.date.today()
        conn.execute(
            "INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?, 1400, 1000, 'manual')", (self.today.isoformat(),))
        # Cliente 1 (self.client_uid, broker Cocos ARS): snapshots + posiciones
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,?,?,?)",
            (self.client_uid, (self.today - _d.timedelta(days=10)).isoformat(), 1000.0, 800.0, 800.0))
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,?,?,?)",
            (self.client_uid, self.today.isoformat(), 700.0, 800.0, 800.0))  # -30% del máximo
        # GGAL ganadora: invested 100k ARS, precio .BA 15000 × 10 = 150k ARS
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,0,'ARS')""",
            (self.client_uid, "Cocos", "GGAL", 10, 100000))
        # AL30 perdedora: invested 200k ARS, precio .BA 10000 × 10 = 100k ARS
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,0,'ARS')""",
            (self.client_uid, "Cocos", "AL30", 10, 200000))
        # Cash ARS ocioso: 500.000 ARS (= USD 500 al MEP 1000) sobre tv 700 → >15%
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,1,'ARS')""",
            (self.client_uid, "Cocos", "Pesos", 1, 500000))
        for sym, price in (("GGAL.BA", 15000.0), ("AL30.BA", 10000.0)):
            conn.execute(
                "INSERT OR REPLACE INTO asset_last_price (symbol, price, updated_at) VALUES (?,?,datetime('now'))",
                (sym, price))
        conn.commit()
        conn.close()

    def test_book_gateado_por_tier(self):
        r = self.http.get("/api/advisor/book", headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)

    def test_book_aum_y_distribucion(self):
        r = self.http.get("/api/advisor/book", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["aum"]["total_usd"], 700.0)     # último snapshot del único con datos
        self.assertEqual(d["aum"]["with_data"], 1)
        self.assertEqual(d["aum"]["clients"], 1)
        # Distribución: tv 700 vs aportado 800 → en rojo
        self.assertEqual(d["distribution"]["red"], 1)
        self.assertEqual(d["distribution"]["worst"]["client_uid"], self.client_uid)

    def test_book_motor_estrella(self):
        r = self.http.get("/api/advisor/book", headers=self._hdr(self.advisor))
        d = r.json()
        star = d["star"]
        self.assertIsNotNone(star)
        winners = {w["asset"]: w for w in star["winners"]}
        losers = {l["asset"]: l for l in star["losers"]}
        self.assertIn("GGAL", winners)                     # 150k vs 100k → verde
        self.assertEqual(winners["GGAL"]["clients_green"], 1)
        self.assertIn("AL30", losers)                      # 100k vs 200k → rojo
        self.assertEqual(losers["AL30"]["clients_red"], 1)
        self.assertGreater(winners["GGAL"]["pnl_usd"], 0)
        self.assertLess(losers["AL30"]["pnl_usd"], 0)

    def test_book_colas(self):
        r = self.http.get("/api/advisor/book", headers=self._hdr(self.advisor))
        d = r.json()
        by_uid = {q["client_uid"]: q for q in d["queues"]}
        self.assertIn(self.client_uid, by_uid)
        kinds = {re["kind"] for re in by_uid[self.client_uid]["reasons"]}
        self.assertIn("drawdown", kinds)      # 700 vs máx 1000 = -30%
        self.assertIn("cash_ocioso", kinds)   # USD 500 de pesos sobre tv 700

    def test_book_posicion_sin_precio_se_excluye(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,0,'ARS')""",
            (self.client_uid, "Cocos", "SINPRECIO", 5, 50000))
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/book", headers=self._hdr(self.advisor))
        star = r.json()["star"]
        all_assets = {x["asset"] for x in star["winners"] + star["losers"]}
        self.assertNotIn("SINPRECIO", all_assets)          # sin precio ≠ P&L 0
        self.assertGreaterEqual(star["skipped_no_price"], 1)


# ─── Audit F0-F3 (fixes del audit comprensivo) ───────────────────────────────

class AuditFixesTest(AdvisorBase):

    def test_header_overflow_da_400_no_500(self):
        # Un entero > 2^63 pasaba int() pero explotaba en el bind de SQLite → 500
        h = self._hdr(self.advisor)
        h["X-Rendi-Client-Id"] = "99999999999999999999999999"
        r = self.http.get("/api/positions", headers=h)
        self.assertEqual(r.status_code, 400)

    def test_cap_de_clientes_activos(self):
        import main as m
        orig = m.ADVISOR_MAX_CLIENTS
        m.ADVISOR_MAX_CLIENTS = 1  # el fixture ya creó 1 vínculo activo
        try:
            r = self.http.post("/api/advisor/clients", json={"label": "Uno más"},
                               headers=self._hdr(self.advisor))
            self.assertEqual(r.status_code, 400)
            self.assertIn("máximo", r.json()["detail"])
        finally:
            m.ADVISOR_MAX_CLIENTS = orig

    def test_alertas_de_cuenta_administrada_se_entregan_al_asesor(self):
        # El shadow no tiene devices ni email real: la entrega tiene que
        # resolverse al ASESOR, con el label del cliente como prefijo.
        import alerts_engine
        conn = main.get_db()
        target, label = alerts_engine._delivery_target(conn, self.client_uid)
        self.assertEqual(target, self.advisor)
        self.assertEqual(label, "Juan P")
        # Cuenta normal (sin managed_by): se entrega al dueño, sin prefijo
        target2, label2 = alerts_engine._delivery_target(conn, self.stranger)
        conn.close()
        self.assertEqual(target2, self.stranger)
        self.assertIsNone(label2)

    def test_prep_con_moneda_sugiere_broker_compatible(self):
        # Cliente tiene AL30D en su broker ARS (importado) pero también un
        # sub-broker dólar: con currency=USD la sugerencia tiene que ser el
        # broker USD, no el ARS donde "ya tiene el activo" (el guard del apply
        # saltearía esa fila).
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.client_uid, "Cocos · USD", "USD"))
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,0,'USD')""",
            (self.client_uid, "Cocos", "AL30D", 100, 750))
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/group-op/prep?asset=AL30D&currency=USD",
                          headers=self._hdr(self.advisor))
        me = [c for c in r.json()["clients"] if c["client_uid"] == self.client_uid][0]
        self.assertEqual(me["suggested_broker"], "Cocos · USD")
        # Sin currency: prevalece donde ya tiene el activo (comportamiento previo)
        r2 = self.http.get("/api/advisor/group-op/prep?asset=AL30D",
                           headers=self._hdr(self.advisor))
        me2 = [c for c in r2.json()["clients"] if c["client_uid"] == self.client_uid][0]
        self.assertEqual(me2["suggested_broker"], "Cocos")

    def test_crypto_price_key_no_rutea_a_ba(self):
        # BTC en sub-broker '· USD' pedía 'BTC.BA' (inexistente) → costo/skip.
        # Espejo del fix del frontend: cripto SIEMPRE por su símbolo pelado.
        from snapshots_job import position_price_key
        key = position_price_key(
            {"asset": "BTC", "broker": "Cocos · USD", "asset_type": None},
            ars_names={"Cocos"}, ar_usd_names={"Cocos · USD"})
        self.assertEqual(key, "BTC")
        # Una acción AR en el mismo sub-broker sigue ruteando a .BA
        key2 = position_price_key(
            {"asset": "GGAL", "broker": "Cocos · USD", "asset_type": None},
            ars_names={"Cocos"}, ar_usd_names={"Cocos · USD"})
        self.assertEqual(key2, "GGAL.BA")
