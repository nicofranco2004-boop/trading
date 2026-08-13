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


def _new_user(conn, email, tier=None, approved=1):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,?,?)",
        (email, "x", approved, tier))
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
        # approved=0: representa un shadow SIN reclamar — el estado real que
        # crea advisor_create_client. get_tier fuerza 'pro' solo en ese estado
        # (F4a: una vez reclamada, approved=1 y cae a su tier real/free).
        self.client_uid = _new_user(conn, f"cliente-{tag}@rendi.test", approved=0)
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

    def tearDown(self):
        # Limpieza de las tablas del plan asesor que REFERENCIAN users (FK):
        # sin esto, las filas que deja esta suite hacían fallar el
        # "DELETE FROM users" del setUp de OTRAS suites cuando se corren
        # juntas (audit: 98 fallas en cascada por IntegrityError — cada suite
        # pasaba sola y el combo enmascaraba regresiones reales).
        conn = main.get_db()
        try:
            conn.execute(
                """DELETE FROM advisor_op_batch_items WHERE batch_id IN
                   (SELECT id FROM advisor_op_batches WHERE advisor_uid=?)""",
                (self.advisor,))
            conn.execute("DELETE FROM advisor_op_batches WHERE advisor_uid=?", (self.advisor,))
            conn.execute("DELETE FROM advisor_claim_tokens WHERE advisor_uid=?", (self.advisor,))
            conn.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.advisor,))
            conn.commit()
        finally:
            conn.close()

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
        # Audit: el undo revierte TAMBIÉN el autodepósito que disparó el alta
        # (antes quedaba +1000 de cash y capital aportado fantasma).
        self.assertAlmostEqual(self._cash(self.client_uid, "Cocos"),
                               cash_before, places=4)
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
        # FX conocido para aserciones (clave = fecha de hoy). Acá el conflicto SÍ
        # pasa: AdvisorBase NO limpia fx_rates_daily y otras clases del módulo
        # siembran la MISMA fecha de hoy (líneas ~1171 y ~1558), sobre la misma
        # base del módulo. Tiene que ser DO UPDATE y no DO NOTHING para que el
        # 1400/1000 quede sí o sí (aunque hoy las 3 escriban lo mismo, un cambio
        # de valores en una sola clase no puede depender del orden de ejecución).
        # `fetched_at` no se nombra: ningún SELECT de la app la lee.
        import datetime as _d
        self.today = _d.date.today()
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?, 1400, 1000, 'manual') ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source", (self.today.isoformat(),))
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
        # asset_last_price tiene 3 columnas (symbol, price, updated_at) y las
        # nombra a las 3 ⇒ la conversión es EQUIVALENTE, no se pierde nada.
        # El conflicto sí ocurre (GGAL.BA lo siembran también las clases de las
        # líneas ~1182 y ~1571 sobre la misma base del módulo), por eso DO UPDATE.
        for sym, price in (("GGAL.BA", 15000.0), ("AL30.BA", 10000.0)):
            conn.execute(
                "INSERT INTO asset_last_price (symbol, price, updated_at) "
                "VALUES (?,?,datetime('now')) ON CONFLICT (symbol) DO UPDATE SET "
                "price=EXCLUDED.price, updated_at=EXCLUDED.updated_at",
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
        # Audit: drawdown solo con resultado pico >= USD 500 (acá adj_mx=200)
        # y medido resultado-sobre-resultado, no sobre el valor de cartera.
        self.assertNotIn("drawdown", kinds)
        self.assertIn("cash_ocioso", kinds)   # USD 500 de pesos sobre tv 700

    def test_book_drawdown_resultado_sobre_resultado(self):
        import datetime as _d
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        big = _new_user(conn, f"grande-{tag}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, big))
        _link(conn, self.advisor, big, label="Grande")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (big, "Cocos", "ARS"))
        today = _d.date.today()
        # pico: resultado 8000 (10000-2000); hoy: resultado 2000 → dd = -75%
        for date_s, tv in (((today - _d.timedelta(days=10)).isoformat(), 10000.0),
                           (today.isoformat(), 4000.0)):
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
                "VALUES (?,?,?,?,?)", (big, date_s, tv, 2000.0, 2000.0))
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/book", headers=self._hdr(self.advisor))
        by_uid = {q["client_uid"]: q for q in r.json()["queues"]}
        self.assertIn(big, by_uid)
        dd = next(x for x in by_uid[big]["reasons"] if x["kind"] == "drawdown")
        self.assertIn("75%", dd["detail"])   # "Su ganancia cayó 75% desde..."

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


# ─── F4a: claim flow (invite + set-password) ─────────────────────────────────

class ClaimFlowTest(AdvisorBase):

    def setUp(self):
        super().setUp()
        # _check_rate_limit usa un dict GLOBAL en memoria (main._rate_store)
        # keyeado por IP (constante en TestClient) + suffix. El suffix de
        # /api/auth/claim es "claim_ip" (fijo, sin distinguir por token/user
        # — correcto en producción: un atacante no debería poder probar más
        # de 10 tokens cada 5 min desde la misma IP). Esta clase invoca claim
        # en ~10 tests → sin resetear, los últimos chocan un 429 legítimo
        # que no tiene nada que ver con lo que cada test intenta probar.
        main._rate_store.pop(f"testclient|claim_ip", None)
        main._rate_store.pop("testclient|reset_pw_ip", None)

    def _invite(self, email=None, uid=None):
        # Email único por default: la tabla de users es COMPARTIDA entre tests
        # de la clase (misma DB) — un email fijo colisionaría con el "ya existe
        # una cuenta con ese email" de un test previo que ya reclamó el suyo.
        email = email or f"cliente.real.{uuid.uuid4().hex[:10]}@example.com"
        return self.http.post(
            f"/api/advisor/clients/{self.client_uid}/invite",
            json={"email": email}, headers=self._hdr(uid or self.advisor))

    def _token_for_client(self):
        conn = main.get_db()
        row = conn.execute(
            "SELECT token FROM advisor_claim_tokens WHERE user_id=? AND used_at IS NULL",
            (self.client_uid,)).fetchone()
        conn.close()
        return row["token"] if row else None

    def _claim(self, token, password="unaClaveLarga1"):
        # /api/auth/claim setea la cookie de sesión del CLIENTE en la respuesta.
        # TestClient persiste cookies (como un browser real) — en la vida real
        # asesor y cliente están en dispositivos DISTINTOS, así que limpiamos
        # el jar después para no contaminar las siguientes llamadas "como
        # asesor" de este mismo test (que usan Authorization header, pero
        # get_current_user prioriza la cookie si está presente).
        r = self.http.post("/api/auth/claim", json={"token": token, "new_password": password})
        self.http.cookies.clear()
        return r

    def test_invite_solo_el_asesor_dueno(self):
        conn = main.get_db()
        otro = _new_user(conn, f"asesor2-{uuid.uuid4().hex[:8]}@rendi.test", tier="advisor")
        conn.commit(); conn.close()
        r = self._invite(uid=otro)
        self.assertEqual(r.status_code, 404)

    def test_invite_email_ya_usado_por_otra_cuenta(self):
        r = self._invite(email=f"asesor-{uuid.uuid4().hex[:6]}@rendi.test")  # email de self.advisor no, uno cualquiera existente
        # probamos contra el email real del stranger (ya existe)
        conn = main.get_db()
        stranger_email = conn.execute("SELECT email FROM users WHERE id=?", (self.stranger,)).fetchone()["email"]
        conn.close()
        r2 = self._invite(email=stranger_email)
        self.assertEqual(r2.status_code, 400)

    def test_invite_ok_crea_token_y_manda_mail(self):
        r = self._invite()
        self.assertEqual(r.status_code, 200, r.text)
        token = self._token_for_client()
        self.assertIsNotNone(token)

    def test_reinvite_invalida_el_token_anterior(self):
        self._invite()
        old_token = self._token_for_client()
        self._invite()
        conn = main.get_db()
        old_row = conn.execute("SELECT used_at FROM advisor_claim_tokens WHERE token=?",
                               (old_token,)).fetchone()
        conn.close()
        self.assertIsNotNone(old_row["used_at"])

    def test_invite_a_cliente_ya_reclamado_400(self):
        self._invite()
        token = self._token_for_client()
        self._claim(token, "unaClaveLarga1")
        r = self._invite(email="segunda-vez@example.com")
        self.assertEqual(r.status_code, 400)

    def test_claim_preview_muestra_asesor_y_label(self):
        self._invite()
        token = self._token_for_client()
        r = self.http.get(f"/api/auth/claim/preview?token={token}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["label"], "Juan P")

    def test_claim_preview_token_invalido_400(self):
        r = self.http.get("/api/auth/claim/preview?token=noexiste")
        self.assertEqual(r.status_code, 400)

    def test_claim_exitoso_setea_password_y_loguea(self):
        self._invite(email="juan.real@example.com")
        token = self._token_for_client()
        r = self.http.post("/api/auth/claim",
                           json={"token": token, "new_password": "unaClaveLarga1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("token", r.json())
        conn = main.get_db()
        row = conn.execute("SELECT email, approved, email_verified, managed_by FROM users WHERE id=?",
                           (self.client_uid,)).fetchone()
        conn.close()
        self.assertEqual(row["email"], "juan.real@example.com")
        self.assertEqual(row["approved"], 1)
        self.assertEqual(row["email_verified"], 1)
        # managed_by → NULL: la cuenta pasa a ser independiente de verdad. El
        # vínculo con el asesor sigue en advisor_clients (no acá) — ver el test
        # de la cascada de borrado, que es EXACTAMENTE por qué esto importa.
        self.assertIsNone(row["managed_by"])

    def test_claim_managed_by_null_protege_de_la_cascada_del_asesor(self):
        # Hallazgo del review de seguridad F4a: antes de este fix, un cliente
        # RECLAMADO (cuenta independiente, login propio) seguía teniendo
        # managed_by=asesor. Si el asesor cerraba SU cuenta (DELETE /api/me),
        # la cascada de borrado (que trata managed_by IS NOT NULL como "shadow,
        # seguro borrar") volaba la cuenta del cliente YA INDEPENDIENTE sin su
        # consentimiento. Este test reproduce el escenario completo.
        self._invite()
        token = self._token_for_client()
        self._claim(token)
        # El cliente incluso revoca el vínculo — ya no tiene NADA que ver con
        # el asesor, ni en advisor_clients ni (gracias al fix) en managed_by.
        conn = main.get_db()
        conn.execute(
            "UPDATE advisor_clients SET status='revoked' WHERE advisor_uid=? AND client_uid=?",
            (self.advisor, self.client_uid))
        conn.commit(); conn.close()

        r = self.http.delete("/api/me", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)

        conn = main.get_db()
        client_alive = conn.execute("SELECT 1 FROM users WHERE id=?", (self.client_uid,)).fetchone()
        conn.close()
        self.assertIsNotNone(client_alive)  # sobrevive: ya no es un shadow de nadie

    def test_claim_login_directo_ve_tier_free(self):
        # El corazón del fix: reclamada, la cuenta deja de forzar 'pro' cuando
        # el CLIENTE la mira directo (sin contexto de asesor).
        self._invite()
        token = self._token_for_client()
        claim_r = self._claim(token)
        client_token = claim_r.json()["token"]
        r = self.http.get("/api/plan/features",
                          headers={"Authorization": f"Bearer {client_token}"})
        self.assertEqual(r.json()["tier"], "free")
        # El asesor, viendo la MISMA cuenta vía contexto, sigue con lente Pro
        r2 = self.http.get("/api/plan/features",
                           headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r2.json()["tier"], "pro")

    def test_claim_token_usado_dos_veces_400(self):
        self._invite()
        token = self._token_for_client()
        self._claim(token, "unaClaveLarga1")
        r2 = self._claim(token, "otraClaveLarga2")
        self.assertEqual(r2.status_code, 400)
        # Y la contraseña activa sigue siendo la de la PRIMERA claim, no la
        # segunda (si la segunda hubiese corrido igual, la pisaría).
        conn = main.get_db()
        row = conn.execute("SELECT password_hash FROM users WHERE id=?",
                           (self.client_uid,)).fetchone()
        conn.close()
        self.assertTrue(main.pwd_ctx.verify("unaClaveLarga1", row["password_hash"]))

    def test_claim_update_atomico_no_permite_doble_marcado(self):
        # Hallazgo del 2do review de seguridad F4a: el UPDATE que marca el
        # token usado no tenía "AND used_at IS NULL" + chequeo de rowcount —
        # dos claims CONCURRENTES del mismo link (ej. alguien interceptó el
        # email) pasaban ambas el SELECT inicial antes de que cualquiera lo
        # marcara usado, y la segunda pisaba la contraseña de la primera.
        # No podemos reproducir dos threads reales acá, pero sí probar que el
        # UPDATE atómico en sí sólo deja ganar a UNA conexión: la segunda
        # ejecución (token ya usado) debe reportar rowcount==0, nunca 1.
        self._invite()
        token = self._token_for_client()
        token_id = main.get_db().execute(
            "SELECT id FROM advisor_claim_tokens WHERE token=?", (token,)).fetchone()["id"]
        conn_a = main.get_db()
        cur_a = conn_a.execute(
            "UPDATE advisor_claim_tokens SET used_at=datetime('now') WHERE id=? AND used_at IS NULL",
            (token_id,))
        conn_a.commit(); conn_a.close()
        conn_b = main.get_db()
        cur_b = conn_b.execute(
            "UPDATE advisor_claim_tokens SET used_at=datetime('now') WHERE id=? AND used_at IS NULL",
            (token_id,))
        conn_b.commit(); conn_b.close()
        self.assertEqual(cur_a.rowcount, 1)
        self.assertEqual(cur_b.rowcount, 0)

    def test_claim_token_expirado_400(self):
        self._invite()
        token = self._token_for_client()
        conn = main.get_db()
        conn.execute("UPDATE advisor_claim_tokens SET expires_at='2000-01-01T00:00:00' WHERE token=?",
                     (token,))
        conn.commit(); conn.close()
        r = self._claim(token, "unaClaveLarga1")
        self.assertEqual(r.status_code, 400)

    def test_revoke_invalida_invitacion_pendiente(self):
        self._invite()
        token = self._token_for_client()
        self.http.post(f"/api/advisor/clients/{self.client_uid}/revoke",
                       headers=self._hdr(self.advisor))
        r = self._claim(token, "unaClaveLarga1")
        self.assertEqual(r.status_code, 400)

    def test_roster_muestra_claim_status(self):
        r0 = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor))
        me0 = [c for c in r0.json()["clients"] if c["client_uid"] == self.client_uid][0]
        self.assertEqual(me0["claim_status"], "shadow")

        self._invite()
        r1 = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor))
        me1 = [c for c in r1.json()["clients"] if c["client_uid"] == self.client_uid][0]
        self.assertEqual(me1["claim_status"], "invited")

        token = self._token_for_client()
        self._claim(token, "unaClaveLarga1")
        r2 = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor))
        me2 = [c for c in r2.json()["clients"] if c["client_uid"] == self.client_uid][0]
        self.assertEqual(me2["claim_status"], "claimed")

    def test_cliente_ve_y_revoca_a_su_asesor(self):
        self._invite()
        token = self._token_for_client()
        claim_r = self._claim(token)
        client_token = claim_r.json()["token"]
        h = {"Authorization": f"Bearer {client_token}"}

        r = self.http.get("/api/me/advisor", headers=h)
        self.assertEqual(r.status_code, 200)
        advisors = r.json()["advisors"]
        self.assertEqual(len(advisors), 1)
        self.assertEqual(advisors[0]["advisor_uid"], self.advisor)
        self.assertEqual(advisors[0]["permission"], "read_write")

        r2 = self.http.post(f"/api/me/advisor/{self.advisor}/revoke", headers=h)
        self.assertEqual(r2.status_code, 200)
        # El asesor pierde el acceso de inmediato
        r3 = self.http.get("/api/positions",
                           headers=self._hdr(self.advisor, client_ctx=self.client_uid))
        self.assertEqual(r3.status_code, 403)

    def test_otro_user_no_puede_revocar_asesor_ajeno(self):
        self._invite()
        token = self._token_for_client()
        self._claim(token, "unaClaveLarga1")
        # El "stranger" intenta revocar un vínculo que no es suyo
        r = self.http.post(f"/api/me/advisor/{self.advisor}/revoke",
                           headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 404)


class RadarTest(AdvisorBase):
    """Radar cross-cliente (nav del asesor, Fase 2): /api/advisor/radar/*.

    Los helpers de refresh pegan a yfinance/Google News — acá se anulan
    (no-op) y se siembran las tablas de cache (financial_events / news)
    directo: lo que se testea es la agregación + atribución, no el fetcher.
    """

    def setUp(self):
        super().setUp()
        self._saved = (
            main._refresh_events_in_background, main._refresh_events_for_tickers,
            main._refresh_news_in_background, main._ensure_news_batch_parallel,
        )
        main._refresh_events_in_background = lambda *a, **k: None
        main._refresh_events_for_tickers = lambda *a, **k: None
        main._refresh_news_in_background = lambda *a, **k: None
        main._ensure_news_batch_parallel = lambda *a, **k: None
        # Segundo cliente para probar la atribución ("lo tienen 2 clientes")
        conn = main.get_db()
        self.client2 = _new_user(conn, f"cliente2-{uuid.uuid4().hex[:8]}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, self.client2))
        _link(conn, self.advisor, self.client2, label="Ana G")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.client2, "IOL", "ARS"))
        conn.commit(); conn.close()

    def tearDown(self):
        (main._refresh_events_in_background, main._refresh_events_for_tickers,
         main._refresh_news_in_background, main._ensure_news_batch_parallel) = self._saved
        super().tearDown()  # limpieza FK de AdvisorBase

    def _pos(self, uid, asset, broker="Cocos", qty=10):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, buy_price, is_cash)
               VALUES (?,?,?,?,?,0)""", (uid, broker, asset, qty, 100))
        conn.commit(); conn.close()

    def _seed_event(self, ticker, days_ahead=5, event_type="earnings"):
        from datetime import datetime, timedelta
        conn = main.get_db()
        conn.execute(
            """INSERT OR IGNORE INTO financial_events
                   (ticker, event_type, event_date, details, confirmed, source, fetched_at)
               VALUES (?,?,?,?,1,'yfinance',datetime('now'))""",
            (ticker, event_type,
             (datetime.utcnow() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), '{}'))
        conn.commit(); conn.close()

    def _seed_news(self, ticker, title):
        conn = main.get_db()
        conn.execute(
            """INSERT OR IGNORE INTO news
                   (source, external_id, title, url, published_at, category,
                    query_source, fetched_at)
               VALUES ('google_news_rss', ?, ?, 'https://example.com/n',
                       datetime('now'), 'portfolio', ?, datetime('now'))""",
            (f"ext-{uuid.uuid4().hex[:10]}", title, f"{ticker} acciones"))
        conn.commit(); conn.close()

    def test_radar_events_agrega_y_atribuye_clientes(self):
        # AAPL lo tienen los dos clientes; GGAL solo el segundo. MSFT lo tiene
        # un usuario AJENO al asesor — no debe aparecer.
        self._pos(self.client_uid, "AAPL")
        self._pos(self.client2, "AAPL", broker="IOL")
        self._pos(self.client2, "GGAL", broker="IOL")
        self._pos(self.stranger, "MSFT")
        for t in ("AAPL", "GGAL", "MSFT"):
            self._seed_event(t)

        r = self.http.get("/api/advisor/radar/events", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        events = {e["ticker"]: e for e in r.json()["events"]}
        self.assertIn("AAPL", events)
        self.assertIn("GGAL", events)
        self.assertNotIn("MSFT", events)
        self.assertEqual(len(events["AAPL"]["clients"]), 2)
        self.assertEqual({c["label"] for c in events["AAPL"]["clients"]}, {"Juan P", "Ana G"})
        self.assertEqual([c["label"] for c in events["GGAL"]["clients"]], ["Ana G"])

    def test_radar_events_requiere_plan_asesor(self):
        r = self.http.get("/api/advisor/radar/events", headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)

    def test_radar_events_cliente_revocado_no_cuenta(self):
        self._pos(self.client2, "GGAL", broker="IOL")
        self._seed_event("GGAL")
        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET status='revoked' WHERE client_uid=?",
                     (self.client2,))
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/radar/events", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("GGAL", {e["ticker"] for e in r.json()["events"]})

    def test_radar_events_sin_clientes_con_posiciones_vacio(self):
        r = self.http.get("/api/advisor/radar/events", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["events"], [])

    def test_radar_news_agrega_y_atribuye(self):
        self._pos(self.client_uid, "AAPL")
        self._pos(self.stranger, "MSFT")
        self._seed_news("AAPL", "Apple sube fuerte")
        self._seed_news("MSFT", "Microsoft cae")

        r = self.http.get("/api/advisor/radar/news", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        news = r.json()["news"]
        # La tabla news es compartida entre archivos del suite — no asumimos
        # cuántas noticias de AAPL hay, sino que TODAS son de tickers del
        # libro (nunca MSFT del ajeno) y que la atribución es correcta.
        self.assertTrue(any(n["title"] == "Apple sube fuerte" for n in news))
        for n in news:
            self.assertEqual(n["ticker"], "AAPL")
            self.assertEqual([c["label"] for c in n["clients"]], ["Juan P"])

    def test_radar_news_requiere_plan_asesor(self):
        r = self.http.get("/api/advisor/radar/news", headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)


class BookChatContextTest(AdvisorBase):
    """F3 (IA del libro): _advisor_book_chat_context + selección de tools.

    No pega al LLM — testea el contexto que ai_chat inyecta en book-mode y
    que el book-mode NO expone el write-path personal (register_trade
    escribiría en la cuenta vacía del asesor)."""

    def setUp(self):
        super().setUp()
        conn = main.get_db()
        import datetime as _d
        today = _d.date.today()
        # Misma fecha de hoy que siembran otras clases del módulo ⇒ el conflicto
        # ocurre y tiene que PISAR (DO UPDATE). `fetched_at` no se nombra: nadie
        # la lee, así que da lo mismo que sobreviva.
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?, 1400, 1000, 'manual') ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source", (today.isoformat(),))
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,?,?,?)", (self.client_uid, today.isoformat(), 700.0, 800.0, 500.0))
        # GGAL: invested 100k ARS, precio .BA 15000 × 10 = 150k ARS (USD 150 al MEP 1000)
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,0,'ARS')""",
            (self.client_uid, "Cocos", "GGAL", 10, 100000))
        # Las 3 columnas de la tabla están nombradas ⇒ equivalente al OR REPLACE.
        conn.execute(
            "INSERT INTO asset_last_price (symbol, price, updated_at) "
            "VALUES (?,?,datetime('now')) ON CONFLICT (symbol) DO UPDATE SET "
            "price=EXCLUDED.price, updated_at=EXCLUDED.updated_at",
            ("GGAL.BA", 15000.0))
        conn.commit(); conn.close()

    def test_contexto_trae_clientes_y_exposicion(self):
        ctx = main._advisor_book_chat_context(self.advisor)
        self.assertEqual(ctx["_kind"], "advisor_book")
        self.assertEqual(len(ctx["clients"]), 1)
        c = ctx["clients"][0]
        self.assertEqual(c["id"], self.client_uid)
        self.assertEqual(c["label"], "Juan P")
        self.assertEqual(c["aum_usd"], 700)
        self.assertEqual(c["n_pos"], 1)
        self.assertEqual(c["top"][0]["asset"], "GGAL")
        self.assertEqual(c["top"][0]["value_usd"], 150)  # 150k ARS al MEP 1000
        # Exposición cross-cliente: GGAL con el cliente atribuido
        exp = {e["asset"]: e for e in ctx["exposure"]}
        self.assertIn("GGAL", exp)
        self.assertEqual(exp["GGAL"]["clients"][0]["id"], self.client_uid)
        self.assertEqual(exp["GGAL"]["clients"][0]["label"], "Juan P")
        # Los agregados del libro viajan también (mismo motor del Dashboard)
        self.assertEqual(ctx["aum"]["total_usd"], 700.0)

    def test_contexto_sin_clientes_no_rompe(self):
        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET status='revoked' WHERE advisor_uid=?",
                     (self.advisor,))
        conn.commit(); conn.close()
        ctx = main._advisor_book_chat_context(self.advisor)
        self.assertEqual(ctx["clients"], [])
        self.assertEqual(ctx["exposure"], [])

    def test_tools_de_book_mode_sin_write_path_personal(self):
        names = {t["name"] for t in main._AI_TOOLS_ADVISOR}
        self.assertNotIn("register_trade", names)
        self.assertNotIn("undo_last_trade", names)
        # Las de lectura siguen (precios, noticias, memoria)
        self.assertIn("get_current_prices", names)
        self.assertIn("remember_user_fact", names)

    def test_addendum_ensena_client_list_y_rutas(self):
        s = main._AI_CHAT_SYSTEM_ADVISOR
        self.assertIn("client_list", s)
        self.assertIn("/clientes?groupop=", s)
        self.assertIn("register_group_op", s)
        self.assertIn("register_trade y undo_last_trade NO EXISTEN", s)


class GroupOpChatTest(AdvisorBase):
    """F3.3: register_group_op (registro grupal por chat) — el write-path del
    book-mode. Se testea el HANDLER directo (sin LLM): armado del draft,
    confirmación enforced en turno distinto, ejecución del payload guardado,
    resolución de nombres y undo."""

    def setUp(self):
        super().setUp()
        main._GROUP_DRAFT.clear()
        main._LAST_GROUP_BATCH.clear()
        conn = main.get_db()
        self.client2 = _new_user(conn, f"ana-{uuid.uuid4().hex[:8]}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, self.client2))
        _link(conn, self.advisor, self.client2, label="Ana G")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.client2, "IOL", "ARS"))
        conn.commit(); conn.close()

    def _build(self, req_id="req-1", **overrides):
        inp = {"asset": "TSLA", "currency": "ARS", "price": 58900.0,
               "rows": [{"client": "Juan P", "amount": 300000},
                        {"client": "Ana G", "amount": 400000}]}
        inp.update(overrides)
        return main._register_group_op_handler(inp, self.advisor, request_id=req_id)

    def test_flujo_completo_montos_a_cantidades(self):
        r = self._build()
        self.assertEqual(r["status"], "needs_confirmation", r)
        self.assertIn("Juan P", r["summary"])
        self.assertIn("Ana G", r["summary"])
        # Confirmación desde OTRO turno (request_id distinto)
        # Audit: sin señal de 'sí' NO se ejecuta (aunque el modelo confirme)
        r_amb = main._register_group_op_handler(
            {"confirm_pending": True}, self.advisor, request_id="req-2")
        self.assertEqual(r_amb["status"], "needs_confirmation", r_amb)
        r2 = main._register_group_op_handler(
            {"confirm_pending": True}, self.advisor, request_id="req-2",
            confirm_signal="yes")
        self.assertEqual(r2["status"], "registered", r2)
        self.assertEqual(r2["applied"], 2)
        conn = main.get_db()
        p1 = conn.execute(
            "SELECT quantity, buy_price, broker FROM positions WHERE user_id=? AND asset='TSLA'",
            (self.client_uid,)).fetchone()
        p2 = conn.execute(
            "SELECT quantity, broker FROM positions WHERE user_id=? AND asset='TSLA'",
            (self.client2,)).fetchone()
        conn.close()
        self.assertAlmostEqual(p1["quantity"], 300000 / 58900.0, places=6)
        self.assertEqual(p1["broker"], "Cocos")
        self.assertAlmostEqual(p2["quantity"], 400000 / 58900.0, places=6)
        self.assertEqual(p2["broker"], "IOL")

    def test_confirmar_en_el_mismo_turno_rechazado(self):
        self._build(req_id="mismo-turno")
        r = main._register_group_op_handler(
            {"confirm_pending": True}, self.advisor, request_id="mismo-turno")
        self.assertIn("error", r)
        self.assertIn("mismo turno", r["error"])
        # El draft sigue vivo — el próximo turno SÍ puede confirmar
        self.assertTrue(main._group_flow_open(self.advisor))

    def test_cliente_desconocido_repregunta_con_roster(self):
        r = self._build(rows=[{"client": "Roberto X", "amount": 100000}])
        self.assertEqual(r["status"], "needs_info")
        joined = " ".join(r["missing"])
        self.assertIn("Roberto X", joined)
        self.assertIn("Juan P", joined)  # le lista el roster real

    def test_no_asesor_rechazado(self):
        r = main._register_group_op_handler(
            {"asset": "TSLA"}, self.stranger, request_id="r")
        self.assertIn("error", r)

    def test_faltan_datos_needs_info(self):
        r = main._register_group_op_handler(
            {"asset": "TSLA"}, self.advisor, request_id="r")
        self.assertEqual(r["status"], "needs_info")
        self.assertTrue(any("moneda" in m for m in r["missing"]))
        self.assertTrue(any("precio" in m for m in r["missing"]))

    def test_moneda_incompatible_queda_afuera(self):
        # Lote USD pero ambos clientes solo tienen brokers ARS → nadie entra
        r = self._build(currency="USD", price=250.0)
        self.assertEqual(r["status"], "needs_info")
        self.assertTrue(any("no tiene ningún broker en USD" in m for m in r["missing"]))

    def test_vinculo_solo_lectura_excluido(self):
        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET permission='read' WHERE client_uid=?",
                     (self.client2,))
        conn.commit(); conn.close()
        r = self._build()
        self.assertEqual(r["status"], "needs_confirmation")
        self.assertIn("Juan P", r["summary"])
        # Audit: los excluidos DEBEN viajar dentro del summary (antes se
        # devolvían solo al modelo y podían no narrarse nunca).
        self.assertIn("NO entran", r["summary"])
        self.assertIn("Ana G", r["summary"])
        self.assertIn("solo lectura", r["summary"])
        self.assertIn("TOTAL", r["summary"])
        self.assertTrue(any("solo lectura" in p for p in r["excluded"]))

    def test_undo_del_ultimo_lote(self):
        self._build()
        main._register_group_op_handler({"confirm_pending": True}, self.advisor,
                                        request_id="req-2", confirm_signal="yes")
        r = main._register_group_op_handler({"undo_last": True}, self.advisor,
                                            request_id="req-3")
        self.assertEqual(r["status"], "undone", r)
        conn = main.get_db()
        left = conn.execute(
            "SELECT COUNT(*) c FROM positions WHERE asset='TSLA' AND user_id IN (?,?)",
            (self.client_uid, self.client2)).fetchone()["c"]
        conn.close()
        self.assertEqual(left, 0)

    def test_short_circuit_confirma_payload_guardado(self):
        self._build()
        r = main._confirm_pending_group_by_uid(self.advisor)
        self.assertEqual(r["status"], "registered")
        # Segundo intento: el draft ya fue claimeado — no hay doble write
        r2 = main._confirm_pending_group_by_uid(self.advisor)
        self.assertIn("error", r2)

    def test_tool_solo_en_lista_advisor(self):
        self.assertIn("register_group_op", {t["name"] for t in main._AI_TOOLS_ADVISOR})
        self.assertNotIn("register_group_op", {t["name"] for t in main._AI_TOOLS})
        self.assertNotIn("register_group_op", {t["name"] for t in main._AI_TOOLS_FREE})


class BookHistoryTest(AdvisorBase):
    """Evolución del capital administrado (idea de Nico): serie diaria de AUM
    con forward-fill por cliente — un hipo del cron no hace caer la serie y
    un cliente nuevo suma desde su primer snapshot (salto real)."""

    def setUp(self):
        super().setUp()
        conn = main.get_db()
        import datetime as _d
        self.today = _d.date.today()
        self.d10 = (self.today - _d.timedelta(days=10)).isoformat()
        self.d1 = (self.today - _d.timedelta(days=1)).isoformat()
        self.client2 = _new_user(conn, f"ana-{uuid.uuid4().hex[:8]}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, self.client2))
        _link(conn, self.advisor, self.client2, label="Ana G")
        # Cliente 1: dos snapshots; Cliente 2: entra recién en d-1
        for (u, d, tv, nd) in ((self.client_uid, self.d10, 1000.0, 800.0),
                               (self.client_uid, self.d1, 1200.0, 900.0),
                               (self.client2, self.d1, 500.0, 500.0)):
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
                "VALUES (?,?,?,?,?)", (u, d, tv, tv, nd))
        conn.commit(); conn.close()

    def test_serie_suma_y_cliente_nuevo(self):
        r = self.http.get("/api/advisor/book/history?days=30",
                          headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()["series"]
        self.assertEqual(len(s), 2)
        p10 = next(p for p in s if p["date"] == self.d10)
        p1 = next(p for p in s if p["date"] == self.d1)
        self.assertEqual(p10["aum_usd"], 1000.0)      # solo el cliente 1
        self.assertEqual(p10["clients"], 1)
        self.assertEqual(p1["aum_usd"], 1700.0)       # 1200 + 500 (Ana entró)
        self.assertEqual(p1["net_deposited_usd"], 1400.0)
        self.assertEqual(p1["clients"], 2)

    def test_seed_pre_ventana_forward_fill(self):
        # Snapshot VIEJO (fuera de la ventana) de un 3er cliente: la serie
        # arranca sumándolo igual — sin rampa falsa desde cero.
        conn = main.get_db()
        import datetime as _d
        c3 = _new_user(conn, f"c3-{uuid.uuid4().hex[:8]}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, c3))
        _link(conn, self.advisor, c3, label="Viejo V")
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,?,?,?)",
            (c3, (self.today - _d.timedelta(days=40)).isoformat(), 300.0, 300.0, 300.0))
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/book/history?days=30",
                          headers=self._hdr(self.advisor))
        s = r.json()["series"]
        p10 = next(p for p in s if p["date"] == self.d10)
        self.assertEqual(p10["aum_usd"], 1300.0)  # 1000 del c1 + 300 seed del c3
        self.assertEqual(p10["clients"], 2)

    def test_revocado_no_cuenta(self):
        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET status='revoked' WHERE client_uid=?",
                     (self.client2,))
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/book/history?days=30",
                          headers=self._hdr(self.advisor))
        p1 = next(p for p in r.json()["series"] if p["date"] == self.d1)
        self.assertEqual(p1["aum_usd"], 1200.0)  # sin Ana

    def test_gateado_por_tier(self):
        r = self.http.get("/api/advisor/book/history",
                          headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)


class BookDetailTest(AdvisorBase):
    """GET /api/advisor/book/detail — desglose por cliente del hero.
    Invariante clave: la suma de los Δ7d por cliente cierra EXACTO con el
    delta agregado (misma regla de comparabilidad que advisor_book)."""

    def setUp(self):
        super().setUp()
        import datetime as _d
        self.today = _d.date.today()
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        # Cliente 2: con base de 7 días y APORTE en la ventana
        self.client2 = _new_user(conn, f"cliente2-{tag}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?",
                     (self.advisor, self.client2))
        _link(conn, self.advisor, self.client2, label="Ana G")
        # Cliente 3: snapshot único (sin base de 7 días → state new)
        self.client3 = _new_user(conn, f"cliente3-{tag}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?",
                     (self.advisor, self.client3))
        _link(conn, self.advisor, self.client3, label="Leo N")
        # Cliente 4: sin ningún snapshot → state no_snapshot
        self.client4 = _new_user(conn, f"cliente4-{tag}@rendi.test", approved=0)
        conn.execute("UPDATE users SET managed_by=? WHERE id=?",
                     (self.advisor, self.client4))
        _link(conn, self.advisor, self.client4, label="Sin Datos")

        old = (self.today - _d.timedelta(days=10)).isoformat()
        now = self.today.isoformat()
        rows = [
            # Cliente 1 (Juan P): 1000 → 700, sin flujos → mercado −300
            (self.client_uid, old, 1000.0, 800.0),
            (self.client_uid, now, 700.0, 800.0),
            # Cliente 2 (Ana G): 2000 → 2600 con +500 aportados → mercado +100
            (self.client2, old, 2000.0, 1500.0),
            (self.client2, now, 2600.0, 2000.0),
            # Cliente 3 (Leo N): solo snapshot de hoy
            (self.client3, now, 900.0, 900.0),
        ]
        for cid, date_s, tv, nd in rows:
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
                "VALUES (?,?,?,?,?)", (cid, date_s, tv, nd, nd))
        conn.commit()
        conn.close()

    def _get(self):
        r = self.http.get("/api/advisor/book/detail", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_gateado_por_tier(self):
        r = self.http.get("/api/advisor/book/detail", headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)

    def test_total_y_shares(self):
        d = self._get()
        # AUM = 700 + 2600 + 900 (el sin-snapshot no aporta)
        self.assertEqual(d["total_usd"], 4200.0)
        self.assertEqual(d["clients_total"], 4)
        by = {c["label"]: c for c in d["clients"]}
        self.assertEqual(by["Ana G"]["value_usd"], 2600.0)
        self.assertEqual(by["Ana G"]["share_pct"], round(2600 / 4200 * 100, 1))
        # Orden default: capital desc, sin-snapshot al final
        self.assertEqual([c["label"] for c in d["clients"]],
                         ["Ana G", "Leo N", "Juan P", "Sin Datos"])

    def test_delta_separa_mercado_de_aportes(self):
        d = self._get()
        ana = next(c for c in d["clients"] if c["label"] == "Ana G")
        self.assertEqual(ana["state"], "ok")
        self.assertEqual(ana["delta_7d_usd"], 600.0)
        self.assertEqual(ana["flows_7d_usd"], 500.0)   # aportó 500
        self.assertEqual(ana["market_7d_usd"], 100.0)  # mercado real +100
        juan = next(c for c in d["clients"] if c["label"] == "Juan P")
        self.assertEqual(juan["delta_7d_usd"], -300.0)
        self.assertEqual(juan["flows_7d_usd"], 0.0)
        self.assertEqual(juan["market_7d_usd"], -300.0)

    def test_suma_de_deltas_cierra_con_el_agregado(self):
        d = self._get()
        suma = sum(c["delta_7d_usd"] for c in d["clients"]
                   if c["delta_7d_usd"] is not None)
        self.assertEqual(round(suma, 2), d["delta_7d_usd"])  # 600 − 300 = 300
        self.assertEqual(d["delta_7d_usd"], 300.0)
        # Y cierra también con el hero del libro
        book = self.http.get("/api/advisor/book",
                             headers=self._hdr(self.advisor)).json()
        self.assertEqual(book["aum"]["delta_7d_usd"], d["delta_7d_usd"])

    def test_estados_new_y_no_snapshot(self):
        d = self._get()
        leo = next(c for c in d["clients"] if c["label"] == "Leo N")
        self.assertEqual(leo["state"], "new")
        self.assertIsNone(leo["delta_7d_usd"])
        self.assertEqual(leo["value_usd"], 900.0)  # cuenta en el AUM igual
        sin = next(c for c in d["clients"] if c["label"] == "Sin Datos")
        self.assertEqual(sin["state"], "no_snapshot")
        self.assertIsNone(sin["value_usd"])

    def test_sin_clientes_devuelve_vacio(self):
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        solo = _new_user(conn, f"solo-{tag}@rendi.test", tier="advisor")
        conn.commit()
        conn.close()
        r = self.http.get("/api/advisor/book/detail", headers=self._hdr(solo))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["clients"], [])


class AdvisorReportsTest(AdvisorBase):
    """Informe del período (prioridad #1 del research): generación en lote,
    payload congelado, link público y branding."""

    def setUp(self):
        super().setUp()
        conn = main.get_db()
        import datetime as _d
        self.today = _d.date.today()
        self.start = (self.today - _d.timedelta(days=30)).isoformat()
        self.end = self.today.isoformat()
        # Misma fecha de hoy que siembran otras clases del módulo ⇒ el conflicto
        # ocurre y tiene que PISAR (DO UPDATE). `fetched_at` no se nombra: nadie
        # la lee, así que da lo mismo que sobreviva.
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?, 1400, 1000, 'manual') ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source", (self.today.isoformat(),))
        # Base ANTERIOR al período + cierre: mercado = (1200-1000) - (900-800) = +100
        for (d, tv, nd) in ((self.today - _d.timedelta(days=40), 1000.0, 800.0),
                            (self.today - _d.timedelta(days=1), 1200.0, 900.0)):
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
                "VALUES (?,?,?,?,?)", (self.client_uid, d.isoformat(), tv, tv, nd))
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,0,'ARS')""",
            (self.client_uid, "Cocos", "GGAL", 10, 100000))
        # Las 3 columnas de la tabla están nombradas ⇒ equivalente al OR REPLACE.
        conn.execute(
            "INSERT INTO asset_last_price (symbol, price, updated_at) "
            "VALUES (?,?,datetime('now')) ON CONFLICT (symbol) DO UPDATE SET "
            "price=EXCLUDED.price, updated_at=EXCLUDED.updated_at",
            ("GGAL.BA", 15000.0))
        conn.commit(); conn.close()
        main._rate_store.pop("testclient|report_pub_ip", None)
        main._rate_store.pop(f"testclient|advreport:{self.advisor}", None)

    def test_generar_lote_y_abrir_publico(self):
        r = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self.start, "period_end": self.end,
                                 "note": "Buen mes, hablamos el martes."},
                           headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        reps = r.json()["reports"]
        self.assertEqual(len(reps), 1)
        rep = reps[0]
        self.assertEqual(rep["label"], "Juan P")
        self.assertIn("/i/", rep["url"])
        self.assertIn("US$", rep["wa_text"])
        # Link público sin auth
        pub = self.http.get(f"/api/reports/public/{rep['token']}")
        self.assertEqual(pub.status_code, 200, pub.text)
        p = pub.json()["report"]
        self.assertEqual(p["value_end_usd"], 1200.0)
        self.assertEqual(p["flows_usd"], 100.0)     # nd 800 → 900
        self.assertEqual(p["market_usd"], 100.0)    # (1200-1000) − 100
        self.assertEqual(p["ret_pct"], 9.52)        # Dietz: 100 / (1000 + 100/2)
        self.assertEqual(p["note"], "Buen mes, hablamos el martes.")
        self.assertEqual(p["holdings"][0]["asset"], "GGAL")
        self.assertFalse(p["claimed"])              # shadow sin reclamar

    def test_payload_congelado_no_cambia_con_branding_posterior(self):
        r = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self.start, "period_end": self.end},
                           headers=self._hdr(self.advisor))
        token = r.json()["reports"][0]["token"]
        # Cambia el branding DESPUÉS de generar
        self.http.patch("/api/advisor/profile",
                        json={"display_name": "Estudio Nuevo", "cnv_matricula": "999"},
                        headers=self._hdr(self.advisor))
        p = self.http.get(f"/api/reports/public/{token}").json()["report"]
        self.assertNotEqual(p["branding"]["name"], "Estudio Nuevo")  # quedó el del momento

    def test_branding_persistido_y_usado(self):
        self.http.patch("/api/advisor/profile",
                        json={"display_name": "Martín Beltrán", "cnv_matricula": "1.234"},
                        headers=self._hdr(self.advisor))
        r = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self.start, "period_end": self.end},
                           headers=self._hdr(self.advisor))
        p = self.http.get(f"/api/reports/public/{r.json()['reports'][0]['token']}").json()["report"]
        self.assertEqual(p["branding"]["name"], "Martín Beltrán")
        self.assertEqual(p["branding"]["matricula"], "1.234")

    def test_cliente_ajeno_salteado(self):
        r = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self.start, "period_end": self.end,
                                 "client_uids": [self.stranger]},
                           headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reports"], [])
        self.assertEqual(r.json()["skipped"][0]["reason"], "sin vínculo activo")

    def test_gateado_por_tier_y_token_invalido(self):
        r = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self.start, "period_end": self.end},
                           headers=self._hdr(self.stranger))
        self.assertEqual(r.status_code, 403)
        pub = self.http.get("/api/reports/public/token-inexistente-123")
        self.assertEqual(pub.status_code, 404)

    def test_holdings_fallback_costo_y_movers(self):
        # Con precio cacheado: basis market + movers (GGAL vale 150 vs 100 invertidos)
        r = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self.start, "period_end": self.end},
                           headers=self._hdr(self.advisor))
        p = self.http.get(f"/api/reports/public/{r.json()['reports'][0]['token']}").json()["report"]
        self.assertEqual(p["holdings_basis"], "market")
        self.assertEqual(p["movers"]["winners"][0]["asset"], "GGAL")
        self.assertEqual(p["movers"]["winners"][0]["pnl_usd"], 50)  # 150−100 USD al MEP 1000
        # Sin precio cacheado: basis cost, tenencias PRESENTES igual (feedback Nico)
        conn = main.get_db()
        conn.execute("DELETE FROM asset_last_price WHERE symbol='GGAL.BA'")
        conn.commit(); conn.close()
        r2 = self.http.post("/api/advisor/reports/generate",
                            json={"period_start": self.start, "period_end": self.end},
                            headers=self._hdr(self.advisor))
        p2 = self.http.get(f"/api/reports/public/{r2.json()['reports'][0]['token']}").json()["report"]
        self.assertEqual(p2["holdings_basis"], "cost")
        self.assertEqual(p2["holdings"][0]["asset"], "GGAL")
        self.assertEqual(p2["holdings"][0]["value_usd"], 100)  # invested 100k ARS al MEP 1000
        self.assertIsNone(p2["movers"])

    def test_logo_guardado_congelado_y_validado(self):
        logo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
        r = self.http.patch("/api/advisor/profile",
                            json={"display_name": "MB", "logo_data": logo},
                            headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["logo"], logo)
        # Congelado en el informe
        g = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self.start, "period_end": self.end},
                           headers=self._hdr(self.advisor))
        p = self.http.get(f"/api/reports/public/{g.json()['reports'][0]['token']}").json()["report"]
        self.assertEqual(p["branding"]["logo"], logo)
        # Borrar con "" — y un SVG se rechaza (solo raster)
        self.http.patch("/api/advisor/profile", json={"logo_data": ""},
                        headers=self._hdr(self.advisor))
        self.assertIsNone(self.http.get("/api/advisor/profile",
                                        headers=self._hdr(self.advisor)).json()["logo"])
        bad = self.http.patch("/api/advisor/profile",
                              json={"logo_data": "data:image/svg+xml;base64,PHN2Zz4="},
                              headers=self._hdr(self.advisor))
        self.assertEqual(bad.status_code, 422)


# ─── Audit grande del plan asesor (2026-07-27) ───────────────────────────────

class AuditGrandeTest(AdvisorBase):
    """Fixes del audit de 5 frentes: consentimiento del lote por chat, undo
    exacto, cascadas de borrado y base honesta del informe."""

    def test_undo_acredita_el_costo_guardado_no_el_editado(self):
        conn = main.get_db()
        # Cliente con cash de sobra: sin autodepósito de por medio
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency)
               VALUES (?,?,?,?,?,1,'ARS')""",
            (self.client_uid, "Cocos", "Pesos", 1, 50000))
        conn.commit(); conn.close()
        body = {"asset": "GD30", "currency": "ARS",
                "rows": [{"client_uid": self.client_uid, "broker": "Cocos",
                          "quantity": 10, "buy_price": 100}]}
        r = self.http.post("/api/advisor/group-op", json=body, headers=self._hdr(self.advisor))
        batch = r.json()["batch_id"]
        pid = r.json()["applied"][0]["position_id"]
        conn = main.get_db()
        # El cliente "edita" la posición: invested x3 (el bug acreditaba 3000)
        conn.execute("UPDATE positions SET invested=3000 WHERE id=?", (pid,))
        conn.commit(); conn.close()
        r2 = self.http.post(f"/api/advisor/group-op/{batch}/undo",
                            headers=self._hdr(self.advisor))
        self.assertEqual(r2.status_code, 200, r2.text)
        conn = main.get_db()
        cash = float(conn.execute(
            "SELECT COALESCE(SUM(invested),0) v FROM positions "
            "WHERE user_id=? AND broker='Cocos' AND is_cash=1",
            (self.client_uid,)).fetchone()["v"])
        conn.close()
        self.assertAlmostEqual(cash, 50000.0, places=4)  # 50000 - 1000 + 1000

    def test_delete_my_account_borra_informes_perfil_y_publico(self):
        conn = main.get_db()
        conn.execute(
            "INSERT INTO advisor_reports (advisor_uid, client_uid, token, payload, period_start, period_end) "
            "VALUES (?,?,?,?,?,?)",
            (self.advisor, self.client_uid, "tok-audit-xyz", "{}", "2026-07-01", "2026-07-27"))
        conn.execute(
            "INSERT INTO advisor_profile (advisor_uid, display_name) VALUES (?,?)",
            (self.advisor, "Estudio X"))
        conn.commit(); conn.close()
        r = self.http.delete("/api/me", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        reps = conn.execute("SELECT COUNT(*) c FROM advisor_reports WHERE advisor_uid=?",
                            (self.advisor,)).fetchone()["c"]
        prof = conn.execute("SELECT COUNT(*) c FROM advisor_profile WHERE advisor_uid=?",
                            (self.advisor,)).fetchone()["c"]
        conn.close()
        self.assertEqual((reps, prof), (0, 0))
        # El link público muere con la cuenta (audit: quedaba vivo para siempre)
        pub = self.http.get("/api/reports/public/tok-audit-xyz")
        self.assertEqual(pub.status_code, 404)

    def test_admin_puede_borrar_usuario_del_plan_asesor(self):
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        admin = _new_user(conn, f"admin-{tag}@rendi.test")
        conn.execute("UPDATE users SET is_admin=1, approved=1 WHERE id=?", (admin,))
        conn.commit(); conn.close()
        # Audit: la lista hardcodeada fallaba por FOREIGN KEY con cualquier
        # usuario del plan asesor (advisor_clients referencia users).
        r = self.http.delete(f"/api/admin/users/{self.advisor}",
                             headers=self._hdr(admin))
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        left = conn.execute("SELECT COUNT(*) c FROM users WHERE id IN (?,?)",
                            (self.advisor, self.client_uid)).fetchone()["c"]
        conn.close()
        self.assertEqual(left, 0)   # asesor + shadow, ambos purgados

    def test_informe_base_onboarding_no_infla_aportes(self):
        import datetime as _d
        today = _d.date.today()
        start = (today - _d.timedelta(days=20)).isoformat()
        end = today.isoformat()
        conn = main.get_db()
        # Historia importada ANTERIOR al período (posición vieja) + snapshots
        # solo DENTRO del período (cliente recién dado de alta en Rendi).
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash, currency, entry_date)
               VALUES (?,?,?,?,?,0,'ARS',?)""",
            (self.client_uid, "Cocos", "GGAL", 10, 100000,
             (today - _d.timedelta(days=400)).isoformat()))
        for date_s, tv, nd in (((today - _d.timedelta(days=10)).isoformat(), 65000.0, 50000.0),
                               (end, 66000.0, 50000.0)):
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
                "VALUES (?,?,?,?,?)", (self.client_uid, date_s, tv, nd, nd))
        conn.commit()
        p = main._advisor_report_payload(conn, self.advisor, self.client_uid, "Juan P",
                                         start, end, None, {"name": "A"}, 1400.0, 1000.0)
        conn.close()
        # Audit #2: la base cero presentaba los 50.000 de depósitos históricos
        # como aportes DEL período. Ahora mide desde el alta (primer snapshot).
        self.assertEqual(p["base_note"], "onboarding")
        self.assertEqual(p["flows_usd"], 0.0)
        self.assertEqual(p["market_usd"], 1000.0)

    def test_informe_cuenta_nueva_sigue_con_base_cero(self):
        import datetime as _d
        today = _d.date.today()
        start = (today - _d.timedelta(days=20)).isoformat()
        end = today.isoformat()
        conn = main.get_db()
        # SIN historia previa: el aporte inicial debe contar como aporte
        for date_s, tv, nd in (((today - _d.timedelta(days=5)).isoformat(), 10000.0, 10000.0),
                               (end, 10500.0, 10000.0)):
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
                "VALUES (?,?,?,?,?)", (self.client_uid, date_s, tv, nd, nd))
        conn.commit()
        p = main._advisor_report_payload(conn, self.advisor, self.client_uid, "Juan P",
                                         start, end, None, {"name": "A"}, 1400.0, 1000.0)
        conn.close()
        self.assertIsNone(p["base_note"])
        self.assertEqual(p["flows_usd"], 10000.0)
        self.assertEqual(p["market_usd"], 500.0)


class PhoneAndReportsTest(AdvisorBase):
    def test_phone_crud_y_normalizacion(self):
        r = self.http.post("/api/advisor/clients",
                           json={"label": "Tel Test", "phone": "+54 9 11 2233-4455"},
                           headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        cid = r.json()["client_uid"]
        roster = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor)).json()["clients"]
        me = next(c for c in roster if c["client_uid"] == cid)
        self.assertEqual(me["phone"], "5491122334455")   # normalizado a dígitos
        # PATCH actualiza y re-normaliza
        r = self.http.patch(f"/api/advisor/clients/{cid}",
                            json={"phone": "549 (291) 437-0000"},
                            headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        roster = self.http.get("/api/advisor/clients", headers=self._hdr(self.advisor)).json()["clients"]
        me = next(c for c in roster if c["client_uid"] == cid)
        self.assertEqual(me["phone"], "5492914370000")

    def test_reports_list_solo_asesor(self):
        r = self.http.get("/api/advisor/reports", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("reports", r.json())
        # un usuario común no puede listar informes de asesor
        conn = main.get_db()
        conn.execute("INSERT INTO users (id,email,name,password_hash) VALUES (9901,'comun@x.co','C','x')")
        conn.commit(); conn.close()
        r = self.http.get("/api/advisor/reports", headers=self._hdr(9901))
        self.assertEqual(r.status_code, 403)


class AdvisorBriefTest(AdvisorBase):
    """Brief del libro 2x/día (apertura + cierre). Seeds idempotentes y una
    sola conexión por test: la suite comparte la DB y el lock es real."""

    def _seed(self):
        import advisor_brief
        from datetime import datetime as _d, timedelta as _t
        today = advisor_brief._today_art()
        ayer = (_d.utcnow() - _t(hours=3) - _t(days=1)).date().isoformat()
        conn = main.get_db()
        try:
            conn.execute("INSERT OR IGNORE INTO fx_rates_daily (date,blue_venta,mep_venta) VALUES (?,1500,1450)", (today,))
            conn.execute("INSERT OR IGNORE INTO brokers (user_id,name,currency) VALUES (?,'BriefBroker','ARS')",
                         (self.client_uid,))
            if not conn.execute("SELECT 1 FROM positions WHERE user_id=? AND broker='BriefBroker'",
                                (self.client_uid,)).fetchone():
                conn.execute("INSERT INTO positions (user_id,broker,asset,is_cash,invested) "
                             "VALUES (?,'BriefBroker','ARS',1,29000000)", (self.client_uid,))
            conn.execute("INSERT OR IGNORE INTO snapshots (user_id,date,total_value,total_invested,net_deposited) "
                         "VALUES (?,?,20000,20000,20000)", (self.client_uid, ayer))
            conn.commit()
        finally:
            conn.close()
        return today

    def test_brief_apertura_trae_a_quien_llamar(self):
        import advisor_brief
        self._seed()
        conn = main.get_db()
        try:
            b = advisor_brief.build_brief(conn, self.advisor, "open")
        finally:
            conn.close()
        self.assertTrue(b, "el brief de apertura no debería venir vacío")
        self.assertIn("Para llamar hoy", [s["title"] for s in b["sections"]])

    def test_brief_idempotente_por_dia_y_kind(self):
        import advisor_brief
        today = self._seed()
        conn = main.get_db()
        try:
            self.assertFalse(advisor_brief.already_sent(conn, self.advisor, "open", today))
            advisor_brief.mark_sent(conn, self.advisor, "open", today)
            conn.commit()
            self.assertTrue(advisor_brief.already_sent(conn, self.advisor, "open", today))
            # el otro brief del MISMO día sigue pendiente
            self.assertFalse(advisor_brief.already_sent(conn, self.advisor, "close", today))
        finally:
            conn.close()

    def test_prefs_toggle_y_respeto(self):
        import advisor_brief
        r = self.http.patch("/api/advisor/brief/prefs", json={"brief_open": False},
                            headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        got = self.http.get("/api/advisor/brief/prefs", headers=self._hdr(self.advisor)).json()
        self.assertFalse(got["brief_open"])
        self.assertTrue(got["brief_close"])
        conn = main.get_db()
        try:
            self.assertFalse(advisor_brief.brief_enabled(conn, self.advisor, "open"))
            self.assertTrue(advisor_brief.brief_enabled(conn, self.advisor, "close"))
        finally:
            conn.close()

    def test_cron_sin_token_cerrado(self):
        r = self.http.post("/api/advisor/brief/run-cron?kind=open")
        self.assertIn(r.status_code, (401, 503))

    def test_cron_kind_invalido(self):
        import os
        os.environ["ADVISOR_BRIEF_TOKEN"] = "tok-test"
        try:
            r = self.http.post("/api/advisor/brief/run-cron?kind=medianoche&token=tok-test")
            self.assertEqual(r.status_code, 400)
        finally:
            os.environ.pop("ADVISOR_BRIEF_TOKEN", None)

    def test_preview_solo_asesor(self):
        r = self.http.get("/api/advisor/brief/preview?kind=open", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        # uid único (la DB es compartida entre tests: un id fijo colisiona o
        # se lo lleva puesto otro test que lo convirtió en asesor)
        conn = main.get_db()
        try:
            cur = conn.execute(
                "INSERT INTO users (email,name,password_hash) VALUES (?,'N','x')",
                (f"nobrief.{uuid.uuid4().hex[:8]}@x.co",))
            otro = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        r = self.http.get("/api/advisor/brief/preview?kind=open", headers=self._hdr(otro))
        self.assertEqual(r.status_code, 403)


class AdvisorClientAlertsTest(AdvisorBase):
    """Alertas del LIBRO: movimiento de la cartera de un cliente."""

    def test_config_crud_y_gate(self):
        r = self.http.patch("/api/advisor/alerts",
                            json={"up_pct": 5, "down_pct": 3, "active": True},
                            headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        cfg = r.json()["config"]
        self.assertEqual(cfg["up_pct"], 5)
        self.assertEqual(cfg["down_pct"], 3)
        self.assertTrue(cfg["active"])
        got = self.http.get("/api/advisor/alerts", headers=self._hdr(self.advisor)).json()
        self.assertTrue(got["config"]["active"])
        self.assertEqual(got["history_days"], 3)
        # un usuario común no accede
        conn = main.get_db()
        try:
            cur = conn.execute("INSERT INTO users (email,name,password_hash) VALUES (?,'N','x')",
                               (f"noadv.{uuid.uuid4().hex[:8]}@x.co",))
            otro = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.http.get("/api/advisor/alerts", headers=self._hdr(otro)).status_code, 403)

    def test_side_umbral_asimetrico(self):
        import advisor_alerts as aa
        self.assertEqual(aa._side(6, 5, 3), "up")
        self.assertEqual(aa._side(-4, 5, 3), "down")
        self.assertIsNone(aa._side(2, 5, 3))       # dentro de la banda
        self.assertIsNone(aa._side(-2, 5, 3))
        self.assertIsNone(aa._side(None, 5, 3))    # sin dato → no dispara
        self.assertIsNone(aa._side(-9, 5, None))   # solo mira subas

    def test_edge_trigger_y_uno_por_dia(self):
        import advisor_alerts as aa, advisor_brief
        from datetime import datetime as _d, timedelta as _t
        ayer = (_d.utcnow() - _t(hours=3) - _t(days=1)).date().isoformat()
        conn = main.get_db()
        try:
            conn.execute("INSERT OR IGNORE INTO snapshots (user_id,date,total_value,total_invested,net_deposited) "
                         "VALUES (?,?,10000,9000,9000)", (self.client_uid, ayer))
            conn.commit()
            aa.set_config(conn, self.advisor, up_pct=5, down_pct=5, active=True)
            conn.commit()
            _orig_deliver, _orig_live = aa._deliver, advisor_brief.live_book_values
            aa._deliver = lambda *a, **k: (True, True)
            try:
                advisor_brief.live_book_values = lambda c, i, p: {self.client_uid: 10600}
                self.assertEqual(aa.evaluate(conn, market_open=True,
                                             only_uid=self.advisor)["fired"], 1)
                # sigue arriba → NO re-dispara (edge-trigger)
                advisor_brief.live_book_values = lambda c, i, p: {self.client_uid: 10700}
                self.assertEqual(aa.evaluate(conn, market_open=True,
                                             only_uid=self.advisor)["fired"], 0)
                # vuelve a la banda y se dispara de nuevo el MISMO día → tope 1/día
                advisor_brief.live_book_values = lambda c, i, p: {self.client_uid: 10100}
                aa.evaluate(conn, market_open=True, only_uid=self.advisor)
                advisor_brief.live_book_values = lambda c, i, p: {self.client_uid: 10900}
                self.assertEqual(aa.evaluate(conn, market_open=True,
                                             only_uid=self.advisor)["fired"], 0)
                # mercado cerrado → nunca evalúa (el % del día está congelado)
                conn.execute("UPDATE advisor_alert_state SET last_fired_date='2000-01-01', armed=1")
                conn.commit()
                self.assertEqual(aa.evaluate(conn, market_open=False,
                                             only_uid=self.advisor)["fired"], 0)
                self.assertEqual(aa.evaluate(conn, market_open=True,
                                             only_uid=self.advisor)["fired"], 1)
            finally:
                aa._deliver, advisor_brief.live_book_values = _orig_deliver, _orig_live
            # el historial registró los disparos
            self.assertGreaterEqual(len(aa.history(conn, self.advisor)), 1)
        finally:
            conn.close()

    def test_historial_se_purga(self):
        import advisor_alerts as aa
        from datetime import datetime as _d, timedelta as _t
        conn = main.get_db()
        try:
            conn.execute("""INSERT INTO advisor_alert_events
                            (advisor_uid, client_uid, kind, message, pct, fired_at)
                            VALUES (?,?,'client_move','viejo',1.0,?)""",
                         (self.advisor, self.client_uid,
                          (_d.utcnow() - _t(days=5)).isoformat()))
            conn.execute("""INSERT INTO advisor_alert_events
                            (advisor_uid, client_uid, kind, message, pct, fired_at)
                            VALUES (?,?,'client_move','fresco',1.0,?)""",
                         (self.advisor, self.client_uid, _d.utcnow().isoformat()))
            conn.commit()
            msgs = [e["message"] for e in aa.history(conn, self.advisor)]
            self.assertIn("fresco", msgs)
            self.assertNotIn("viejo", msgs)   # >3 días se purga solo
        finally:
            conn.close()


class AdvisorAlertsAuditTest(AdvisorBase):
    """Fixes del audit adversarial: los tres caminos por los que la alerta
    podía MENTIR (tier vencido, base vieja, flujo disfrazado de mercado)."""

    def _base_snapshot(self, days_ago=1, value=10000, nd=9000):
        from datetime import datetime as _d, timedelta as _t
        day = (_d.utcnow() - _t(hours=3) - _t(days=days_ago)).date().isoformat()
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.client_uid,))
            conn.execute("INSERT INTO snapshots (user_id,date,total_value,total_invested,net_deposited) "
                         "VALUES (?,?,?,?,?)", (self.client_uid, day, value, value, nd))
            conn.commit()
        finally:
            conn.close()

    def _run(self, live_value):
        import advisor_alerts as aa, advisor_brief
        conn = main.get_db()
        try:
            aa.set_config(conn, self.advisor, up_pct=5, down_pct=5, active=True)
            conn.execute("DELETE FROM advisor_alert_state WHERE advisor_uid=?", (self.advisor,))
            conn.commit()
            _d0, _l0 = aa._deliver, advisor_brief.live_book_values
            aa._deliver = lambda *a, **k: (True, True)
            advisor_brief.live_book_values = lambda c, i, p: {self.client_uid: live_value}
            try:
                return aa.evaluate(conn, market_open=True, only_uid=self.advisor)
            finally:
                aa._deliver, advisor_brief.live_book_values = _d0, _l0
        finally:
            conn.close()

    def test_asesor_con_plan_vencido_no_recibe(self):
        self._base_snapshot()
        conn = main.get_db()
        try:
            conn.execute("UPDATE users SET tier=NULL WHERE id=?", (self.advisor,))
            conn.commit()
        finally:
            conn.close()
        try:
            # +6%: dispararía si no fuera por el tier
            self.assertEqual(self._run(10600)["advisors"], 0)
        finally:
            conn = main.get_db()
            conn.execute("UPDATE users SET tier='advisor' WHERE id=?", (self.advisor,))
            conn.commit(); conn.close()

    def test_base_vieja_no_se_evalua(self):
        self._base_snapshot(days_ago=30)          # cron frenado / import viejo
        self.assertEqual(self._run(10600)["fired"], 0)

    def test_deposito_no_se_disfraza_de_suba(self):
        from datetime import datetime as _d, timedelta as _t
        self._base_snapshot(value=10000, nd=9000)
        hoy = (_d.utcnow() - _t(hours=3)).date()
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM monthly_entries WHERE user_id=? AND broker='global'",
                         (self.client_uid,))
            # el cliente aportó 1.000 hoy → nd pasa de 9.000 a 10.000
            conn.execute("""INSERT INTO monthly_entries
                            (user_id,broker,year,month,deposits,withdrawals,
                             capital_inicio,capital_final,pnl_realized,pnl_unrealized)
                            VALUES (?,'global',?,?,10000,0,0,0,0,0)""",
                         (self.client_uid, hoy.year, hoy.month))
            conn.commit()
        finally:
            conn.close()
        # vale 11.000 pero 1.000 fue depósito → 0% real → NO dispara
        self.assertEqual(self._run(11000)["fired"], 0)
        # y con una suba REAL (12.000 = +10% descontando el depósito) sí dispara
        self.assertEqual(self._run(12000)["fired"], 1)


class AdvisorGroupsIsolationTest(AdvisorBase):
    """El grupo de un asesor no existe para otro — ni para leerlo, ni para
    borrarlo, ni para apuntarle una alerta."""

    def test_grupo_ajeno_invisible_e_intocable(self):
        # el "otro" tiene que ser asesor también: si no, el 403 del tier taparía
        # el aislamiento que queremos probar
        conn = main.get_db()
        try:
            conn.execute("UPDATE users SET tier='advisor' WHERE id=?", (self.stranger,))
            conn.commit()
        finally:
            conn.close()
        h1 = self._hdr(self.advisor)
        h2 = self._hdr(self.stranger)
        gid = self.http.post("/api/advisor/groups",
                             json={"name": "mio", "rules": {"has_asset": "AMZN"}},
                             headers=h1).json()["id"]
        self.assertEqual(self.http.get(f"/api/advisor/groups/{gid}/clients", headers=h2).status_code, 404)
        self.assertEqual(self.http.patch("/api/advisor/alerts", json={"group_id": gid},
                                         headers=h2).status_code, 404)
        # borrar el ajeno: 404 y el grupo sigue vivo (antes devolvía 200 sin
        # borrar nada — un "listo" que no era cierto)
        self.assertEqual(self.http.delete(f"/api/advisor/groups/{gid}", headers=h2).status_code, 404)
        self.assertEqual([g["name"] for g in self.http.get("/api/advisor/groups", headers=h1).json()["groups"]],
                         ["mio"])
        self.assertEqual(self.http.delete(f"/api/advisor/groups/{gid}", headers=h1).status_code, 200)
        self.assertEqual(self.http.delete(f"/api/advisor/groups/{gid}", headers=h1).status_code, 404)


class AdvisorSnapshotWriteTest(AdvisorBase):
    """El asesor no escribe la serie del cliente por mirarla."""

    def _snaps(self):
        conn = main.get_db()
        try:
            return conn.execute("SELECT COUNT(*) c FROM snapshots WHERE user_id=?",
                                (self.client_uid,)).fetchone()["c"]
        finally:
            conn.close()

    def test_con_la_lente_puesta_no_escribe_el_snapshot_del_cliente(self):
        # El Dashboard postea solo al cargar, con los totales del browser y el
        # toggle de dolar de QUIEN mira, y hace UPSERT sobre la fila del dia:
        # el asesor le pisaba la foto de hoy a su cliente con solo abrirla.
        antes = self._snaps()
        r = self.http.post("/api/snapshots",
                           headers=self._hdr(self.advisor, client_ctx=self.client_uid),
                           json={"total_value": 999, "total_invested": 999, "net_deposited": 0})
        self.assertEqual(r.status_code, 200)          # no le mostramos un error
        self.assertEqual(self._snaps(), antes)        # pero no escribio nada

    def test_el_cliente_si_escribe_el_suyo(self):
        # La contracara: sin lente, el flujo normal tiene que seguir andando.
        antes = self._snaps()
        r = self.http.post("/api/snapshots", headers=self._hdr(self.client_uid),
                           json={"total_value": 500, "total_invested": 400, "net_deposited": 400})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._snaps(), antes + 1)


class AdvisorBriefFixesTest(AdvisorBase):
    """Errores del backlog: el brief y la base del % del día."""

    def test_eventos_de_hoy_aparecen_en_el_brief(self):
        # La sección consultaba columnas que no existen (kind/date/title vs
        # event_type/event_date) → explotaba y un except la borraba en
        # silencio: NUNCA se mostró desde que se escribió.
        import advisor_brief
        hoy = advisor_brief._today_art()
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,invested,is_cash) "
                         "VALUES (?,?,?,?,?,0)", (self.client_uid, "Cocos", "AAPL", 10, 1000))
            conn.execute("INSERT INTO financial_events (ticker,event_type,event_date,fetched_at) "
                         "VALUES ('AAPL','earnings',?,datetime('now'))", (hoy,))
            conn.commit()
            out = advisor_brief.build_brief(conn, self.advisor, "open")
        finally:
            conn.close()
        titulos = [sec["title"] for sec in (out or {}).get("sections", [])]
        self.assertIn("Eventos de hoy", titulos)
        sec = next(x for x in out["sections"] if x["title"] == "Eventos de hoy")
        self.assertEqual(sec["items"][0]["label"], "AAPL")
        # y en criollo, no con el código interno del evento
        self.assertIn("Reporte trimestral", sec["items"][0]["detail"])
        self.assertNotIn("earnings", sec["items"][0]["detail"])

    def test_asunto_del_cierre_no_dice_tu_libro_hoy(self):
        from billing import emails
        capt = {}
        _o = emails._send
        emails._send = lambda to, subj, *a, **k: capt.setdefault("s", subj) or True
        try:
            emails.send_advisor_brief(to="x@y.com", user_name="Nico",
                                      brief={"kind": "close", "date": "2026-08-06",
                                             "sections": [], "aum_total_usd": 1000})
        finally:
            emails._send = _o
        self.assertNotIn("Tu libro hoy", capt.get("s", ""))

    def test_snapshot_se_fecha_en_hora_argentina(self):
        # A las 21:30 ART ya es el día siguiente en UTC: el snapshot quedaba
        # fechado mañana y pisaba al del cierre real.
        # Determinístico: se fuerza el helper ART a una fecha reconocible. Con
        # un assert contra "hoy" a secas el test sólo fallaría entre las 21 y
        # las 24 (las 3 horas en que UTC y ART difieren de día).
        h = self._hdr(self.client_uid)
        _o = main._iso_today
        main._iso_today = lambda: "2020-01-15"
        try:
            self.http.post("/api/snapshots", headers=h,
                           json={"total_value": 100, "total_invested": 90, "net_deposited": 90})
        finally:
            main._iso_today = _o
        conn = main.get_db()
        try:
            d = conn.execute("SELECT date FROM snapshots WHERE user_id=?",
                             (self.client_uid,)).fetchone()["date"]
        finally:
            conn.close()
        self.assertEqual(d, "2020-01-15", "el snapshot no usa el día ART")


class AdvisorAlertBaseTest(AdvisorAlertsAuditTest):
    """La base del % del día tiene que ser el CIERRE ANTERIOR."""

    def test_un_snapshot_de_hoy_no_puede_ser_la_base(self):
        # El browser escribe un snapshot intradiario al abrir la app. Si ese
        # pasaba a ser la base, el % del día se comparaba contra sí mismo:
        # daba ~0 y la alerta no disparaba nunca.
        from datetime import datetime as _d, timedelta as _t
        # nd=0 en las dos puntas: si no, el descuento de flujos (net_deposited
        # del snapshot vs el vivo) mete un delta propio y el test pasa por el
        # motivo equivocado — pasaba aun con el bug puesto.
        self._base_snapshot(days_ago=1, value=10000, nd=0)
        hoy = (_d.utcnow() - _t(hours=3)).date().isoformat()
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO snapshots (user_id,date,total_value,total_invested,"
                         "net_deposited) VALUES (?,?,?,?,?)",
                         (self.client_uid, hoy, 12000, 12000, 0))
            conn.commit()
        finally:
            conn.close()
        # +20% contra el cierre de AYER → tiene que avisar igual
        self.assertEqual(self._run(12000)["fired"], 1)


class ReconstruccionVsMedicionTest(AdvisorBase):
    """La prueba mas dura, y sale gratis: reconstruir un cierre que el cron YA
    midio y comparar. Si el motor reconstruye distinto de lo que la app midio,
    un borde reconstruido NO se puede encadenar con uno medido — y sin eso, la
    reconstruccion entera no sirve por bien que razone el agente."""

    def _setup(self, broker="IBKR", ccy="USD"):
        import uuid as _u
        bid = _u.uuid4().hex[:12]
        conn = main.get_db()
        try:
            conn.execute("INSERT OR IGNORE INTO brokers (user_id,name,currency) "
                         "VALUES (?,?,?)", (self.client_uid, broker, ccy))
            conn.execute(
                "INSERT INTO import_batches (id,user_id,broker,parser_format,"
                "file_hash,status) VALUES (?,?,?,'test',?,'done')",
                (bid, self.client_uid, broker, bid))
            conn.commit()
        finally:
            conn.close()
        return bid

    def _tx(self, bid, fecha, op, asset, qty, monto, broker="IBKR", ccy="USD"):
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','ok')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity,gross_amount,currency) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (bid, rid, fecha, broker, op, asset, qty, monto, ccy))
            conn.commit()
        finally:
            conn.close()

    def test_el_borde_reconstruido_coincide_con_el_que_midio_el_cron(self):
        # Mismo motor, misma tenencia, mismos precios -> mismo numero.
        import ledger_replay as lr, price_history as ph
        from snapshots_job import compute_broker_value_usd

        bid = self._setup()
        self._tx(bid, "2026-01-10", "DEPOSIT", None, None, 5000.0)
        self._tx(bid, "2026-01-15", "BUY", "AAPL", 10, 2000.0)

        conn = main.get_db()
        try:
            ph.guardar(conn, "AAPL", {"2026-01-31": 210.0})
            conn.commit()

            # Lo que mediria el cron con esa misma foto.
            pos = [{"asset": "AAPL", "asset_type": None, "is_cash": 0,
                    "quantity": 10, "invested": 2000.0, "commissions": 0,
                    "price_override": None},
                   {"asset": "USD", "asset_type": None, "is_cash": 1,
                    "quantity": 0, "invested": 3000.0, "commissions": 0,
                    "price_override": None}]
            medido = compute_broker_value_usd(pos, {"AAPL": 210.0}, "USD", 1400.0,
                                              broker_name="IBKR")["value"]
            recon = lr.valor_en(conn, self.client_uid, "2026-01-31")
        finally:
            conn.close()

        self.assertIsNotNone(recon["valor"])
        self.assertAlmostEqual(recon["valor"], medido, places=2)

    def test_el_borde_reconstruido_incluye_el_cash(self):
        # El cron cuenta el efectivo en total_value. Un borde reconstruido sin
        # cash no es la misma magnitud: encadenarlos fabrica un escalon del
        # tamano de la liquidez (un cliente 30% en pesos veria -30% que no fue).
        import ledger_replay as lr, price_history as ph
        bid = self._setup()
        # Activo propio: asset_price_history persiste entre tests de la misma
        # corrida y a propósito NO pisa un precio ya guardado — con el mismo
        # ticker, otro test le fija el precio a éste.
        self._tx(bid, "2026-01-10", "DEPOSIT", None, None, 5000.0)
        self._tx(bid, "2026-01-15", "BUY", "CASHT", 10, 2000.0)
        conn = main.get_db()
        try:
            ph.guardar(conn, "CASHT", {"2026-01-31": 200.0})
            conn.commit()
            v = lr.valor_en(conn, self.client_uid, "2026-01-31")
            saldo = lr.cash_en(conn, self.client_uid, "2026-01-31")
        finally:
            conn.close()
        self.assertAlmostEqual(saldo[("IBKR", "USD")], 3000.0, places=2)
        # 10 x 200 en acciones + 3000 de cash
        self.assertAlmostEqual(v["valor"], 5000.0, places=2)

    def test_un_CEDEAR_ya_vendido_se_valua_por_su_BA_y_no_por_el_ticker_US(self):
        # El asset_type salia de `positions`; para un activo ya vendido esa fila
        # no existe y el simbolo caia al ticker US -> el bug C1, 15-100x
        # inflado. Ahora el tipo sale del LEDGER, que si lo conserva.
        import ledger_replay as lr, price_history as ph
        # Broker en DÓLARES a propósito: con un broker en pesos el símbolo cae
        # en '.BA' igual, sin mirar el tipo — y el test pasaría por el motivo
        # equivocado. Sólo acá el asset_type es lo único que decide.
        bid = self._setup(broker="IBKR", ccy="USD")
        self._tx(bid, "2026-01-10", "BUY", "CEDT", 10, 100.0, broker="IBKR", ccy="USD")
        conn = main.get_db()
        try:
            conn.execute("UPDATE import_normalized_tx SET asset_type='CEDEAR' "
                         "WHERE batch_id=?", (bid,))
            # NO hay fila en positions: el activo se vendio.
            ph.guardar(conn, "CEDT.BA", {"2026-01-31": 7000.0})
            # Otro test del módulo siembra la MISMA fecha con los MISMOS valores
            # (1500/1400), así que el DO UPDATE es un no-op cuando choca.
            # `source` y `fetched_at` quedan fuera del SET a propósito: el
            # OR REPLACE las reseteaba a su DEFAULT y ahora sobreviven, pero
            # ninguno de los dos escritores de esta fecha pone `source`
            # (queda 'unknown' igual) y `ledger_replay` sólo lee `mep_venta`.
            conn.execute("INSERT INTO fx_rates_daily (date,blue_venta,mep_venta) "
                         "VALUES ('2026-01-31',1500,1400) "
                         "ON CONFLICT (date) DO UPDATE SET "
                         "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta")
            conn.commit()
            v = lr.valor_en(conn, self.client_uid, "2026-01-31")
        finally:
            conn.close()
        # Resolvio por '.BA': si hubiera pedido el ticker US no habria precio.
        self.assertEqual(v["faltan"], [])
        self.assertIsNotNone(v["valor"])

    def test_un_activo_sin_precio_ni_costo_no_certifica_cobertura(self):
        # Peso desconocido != peso cero. Certificar una cobertura que no se
        # midio es exactamente como se publica un borde corto.
        import ledger_replay as lr, price_history as ph
        bid = self._setup()
        self._tx(bid, "2026-01-15", "BUY", "AAPL", 10, 2000.0)
        self._tx(bid, "2026-01-15", "BUY", "RARO", 5, 0)      # sin monto
        conn = main.get_db()
        try:
            ph.guardar(conn, "AAPL", {"2026-01-31": 200.0})
            conn.commit()
            v = lr.valor_en(conn, self.client_uid, "2026-01-31")
        finally:
            conn.close()
        self.assertIsNone(v["valor"])
        self.assertIsNone(v["cobertura_pct"])


class FlujosDeterministaTest(AdvisorBase):
    """La pasada que resuelve sin modelo. Lo que queda es lo que justifica uno."""

    def _batch(self, uid, broker="Cocos"):
        import uuid as _u
        bid = _u.uuid4().hex[:12]
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO import_batches (id,user_id,broker,parser_format,"
                "file_hash,status) VALUES (?,?,?,'test',?,'done')",
                (bid, uid, broker, bid))
            conn.commit()
        finally:
            conn.close()
        return bid

    def _cruda(self, bid, texto, errores="TRANSFER_NOT_SUPPORTED"):
        import json as _j
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status,"
                "errors_json) VALUES (?,0,?,'error',?)",
                (bid, _j.dumps({"tipo": texto}), errores)).lastrowid
            conn.commit()
            return rid
        finally:
            conn.close()

    def _tx(self, bid, fecha, op, asset, qty, broker):
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','ok')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity) VALUES (?,?,?,?,?,?,?)",
                (bid, rid, fecha, broker, op, asset, qty))
            conn.commit()
        finally:
            conn.close()

    def _conn(self):
        return main.get_db()

    # ── vía 1: lo que el broker escribió en la fila cruda ───────────────────
    def test_el_texto_original_dice_la_direccion(self):
        # El normalizador mapea a tipos canónicos y descarta la descripción,
        # pero la fila cruda queda. Ahí hay que mirar ANTES de deducir nada.
        import flujos
        self.assertEqual(flujos.direccion_por_texto("Transferencia Recibida de titulos"),
                         "entrada")
        self.assertEqual(flujos.direccion_por_texto("ACAT OUT — journaled shares"),
                         "salida")
        self.assertIsNone(flujos.direccion_por_texto("Movimiento varios"))

    def test_resuelve_por_texto_crudo_sin_tocar_el_modelo(self):
        import flujos
        bid = self._batch(self.client_uid)
        self._cruda(bid, "Transferencia Recibida")
        conn = self._conn()
        try:
            r = flujos.reconciliar(conn, self.client_uid)
        finally:
            conn.close()
        self.assertEqual(r["candidatos"], 1)
        self.assertEqual(r["resueltos"], 1)
        self.assertEqual(r["por_via"], {"texto_crudo": 1})

    # ── vía 2: el cruce entre brokers ──────────────────────────────────────
    def test_una_salida_en_otro_broker_prueba_que_fue_traslado_interno(self):
        # Salen 12 AAPL de Balanz y entran 12 en IOL: NO es un aporte. Esto no
        # es un juicio, es una consulta.
        import flujos
        bid = self._batch(self.client_uid, broker="Balanz")
        self._tx(bid, "2026-04-12", "SELL", "AAPL", 12, "Balanz")
        conn = self._conn()
        try:
            par = flujos.cruce_entre_brokers(conn, self.client_uid, "AAPL",
                                             "2026-04-13", 12, "IOL")
        finally:
            conn.close()
        self.assertIsNotNone(par)
        self.assertEqual(par["broker"], "Balanz")

    def test_no_casa_una_cantidad_distinta(self):
        import flujos
        bid = self._batch(self.client_uid, broker="Balanz")
        self._tx(bid, "2026-04-12", "SELL", "AAPL", 12, "Balanz")
        conn = self._conn()
        try:
            self.assertIsNone(flujos.cruce_entre_brokers(
                conn, self.client_uid, "AAPL", "2026-04-13", 30, "IOL"))
        finally:
            conn.close()

    def test_no_casa_fuera_de_la_ventana(self):
        # Un traspaso no liquida el mismo día, pero tampoco tres semanas después.
        import flujos
        bid = self._batch(self.client_uid, broker="Balanz")
        self._tx(bid, "2026-04-12", "SELL", "AAPL", 12, "Balanz")
        conn = self._conn()
        try:
            self.assertIsNone(flujos.cruce_entre_brokers(
                conn, self.client_uid, "AAPL", "2026-05-20", 12, "IOL"))
        finally:
            conn.close()

    def test_no_casa_contra_el_mismo_broker(self):
        # Una compra y una venta en el MISMO broker no son un traslado.
        import flujos
        bid = self._batch(self.client_uid, broker="Cocos")
        self._tx(bid, "2026-04-12", "SELL", "AAPL", 12, "Cocos")
        conn = self._conn()
        try:
            self.assertIsNone(flujos.cruce_entre_brokers(
                conn, self.client_uid, "AAPL", "2026-04-13", 12, "Cocos"))
        finally:
            conn.close()

    def test_una_venta_borrada_no_sirve_de_contraparte(self):
        import flujos
        bid = self._batch(self.client_uid, broker="Balanz")
        self._tx(bid, "2026-04-12", "SELL", "AAPL", 12, "Balanz")
        conn = self._conn()
        try:
            conn.execute("UPDATE import_normalized_tx SET excluded_at=datetime('now')")
            conn.commit()
            self.assertIsNone(flujos.cruce_entre_brokers(
                conn, self.client_uid, "AAPL", "2026-04-13", 12, "IOL"))
        finally:
            conn.close()

    # ── lo que NO resuelve ─────────────────────────────────────────────────
    def test_sin_texto_ni_contraparte_queda_para_el_agente(self):
        import flujos
        bid = self._batch(self.client_uid)
        self._cruda(bid, "Movimiento sin descripcion")
        conn = self._conn()
        try:
            r = flujos.reconciliar(conn, self.client_uid)
        finally:
            conn.close()
        self.assertEqual(r["pendientes"], 1)
        self.assertEqual(r["resueltos"], 0)
        self.assertTrue(r["detalle_pendientes"][0]["evidencia"])

    def test_un_error_que_no_es_de_traspaso_no_es_candidato(self):
        # Una fecha mal formateada no es un flujo ambiguo.
        import flujos
        bid = self._batch(self.client_uid)
        self._cruda(bid, "Compra", errores="BAD_DATE")
        conn = self._conn()
        try:
            self.assertEqual(flujos.reconciliar(conn, self.client_uid)["candidatos"], 0)
        finally:
            conn.close()

    def test_sin_ambiguedades_la_tasa_es_cien(self):
        import flujos
        conn = self._conn()
        try:
            r = flujos.reconciliar(conn, self.client_uid)
        finally:
            conn.close()
        self.assertEqual(r["candidatos"], 0)
        self.assertEqual(r["tasa_pct"], 100.0)


class LedgerReplayTest(AdvisorBase):
    """Reconstruir QUÉ tenía una persona en una fecha pasada."""

    def _batch(self, uid):
        import uuid as _u
        bid = _u.uuid4().hex[:12]
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO import_batches (id,user_id,broker,parser_format,"
                "file_hash,status) VALUES (?,?,'Cocos','test',?,'done')",
                (bid, uid, bid))
            conn.commit()
        finally:
            conn.close()
        return bid

    def _tx(self, bid, fecha, op, asset, qty, broker="Cocos"):
        conn = main.get_db()
        try:
            # raw_row_id es FK: el ledger normalizado siempre cuelga de la
            # fila cruda del export (que es donde el agente va a mirar cuando
            # el normalizador simplificó algo).
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','ok')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity) VALUES (?,?,?,?,?,?,?)",
                (bid, rid, fecha, broker, op, asset, qty))
            conn.commit()
        finally:
            conn.close()

    def _pos(self, uid, asset, qty, broker="Cocos", ccy="ARS"):
        conn = main.get_db()
        try:
            conn.execute("INSERT OR IGNORE INTO brokers (user_id,name,currency) "
                         "VALUES (?,?,?)", (uid, broker, ccy))
            conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,"
                         "invested,is_cash) VALUES (?,?,?,?,100,0)",
                         (uid, broker, asset, qty))
            conn.commit()
        finally:
            conn.close()

    def _conn(self):
        return main.get_db()

    # ── el replay ──────────────────────────────────────────────────────────
    def test_reconstruye_la_tenencia_a_una_fecha_pasada(self):
        import ledger_replay as lr
        bid = self._batch(self.client_uid)
        self._tx(bid, "2026-01-10", "BUY", "AAPL", 10)
        self._tx(bid, "2026-02-15", "BUY", "AAPL", 5)
        self._tx(bid, "2026-03-20", "SELL", "AAPL", 4)
        conn = self._conn()
        try:
            self.assertEqual(lr.tenencia_en(conn, self.client_uid, "2026-01-31"),
                             {("Cocos", "AAPL"): 10.0})
            self.assertEqual(lr.tenencia_en(conn, self.client_uid, "2026-02-28"),
                             {("Cocos", "AAPL"): 15.0})
            self.assertEqual(lr.tenencia_en(conn, self.client_uid, "2026-03-31"),
                             {("Cocos", "AAPL"): 11.0})
        finally:
            conn.close()

    def test_una_venta_borrada_no_cuenta(self):
        # El borrado es un tombstone: si el replay ignora excluded_at, la
        # cartera reconstruida no coincide con la real.
        import ledger_replay as lr
        bid = self._batch(self.client_uid)
        self._tx(bid, "2026-01-10", "BUY", "GGAL", 100)
        self._tx(bid, "2026-01-20", "SELL", "GGAL", 40)
        conn = self._conn()
        try:
            conn.execute("UPDATE import_normalized_tx SET excluded_at=datetime('now') "
                         "WHERE batch_id=? AND operation_type='SELL'", (bid,))
            conn.commit()
            self.assertEqual(lr.tenencia_en(conn, self.client_uid, "2026-02-01"),
                             {("Cocos", "GGAL"): 100.0})
        finally:
            conn.close()

    # ── el chequeo que decide si se le puede creer ─────────────────────────
    def test_si_el_replay_reproduce_hoy_se_le_puede_creer(self):
        import ledger_replay as lr
        bid = self._batch(self.client_uid)
        self._tx(bid, "2026-01-10", "BUY", "AAPL", 10)
        self._pos(self.client_uid, "AAPL", 10)
        conn = self._conn()
        try:
            v = lr.verificar_contra_hoy(conn, self.client_uid)
        finally:
            conn.close()
        self.assertTrue(v["reproducible"])
        self.assertEqual(v["diferencias"], [])

    def test_un_traspaso_de_titulos_deja_el_ledger_corto_y_se_detecta(self):
        # Las transferencias las filtra el validator y NO crean posición: un
        # export de IOL con traspasos deja la tenencia corta. Si el replay no
        # lo detecta, devuelve una cartera MÁS CHICA que la real y eso,
        # encadenado, se lee como una pérdida que nunca existió.
        import ledger_replay as lr
        bid = self._batch(self.client_uid)
        self._tx(bid, "2026-01-10", "BUY", "AAPL", 10)
        self._pos(self.client_uid, "AAPL", 10)
        self._pos(self.client_uid, "MELI", 3)        # llegó por traspaso, sin ledger
        conn = self._conn()
        try:
            v = lr.verificar_contra_hoy(conn, self.client_uid)
        finally:
            conn.close()
        self.assertFalse(v["reproducible"])
        self.assertEqual(v["motivo"], "ledger_incompleto")
        self.assertEqual([d["asset"] for d in v["diferencias"]], ["MELI"])

    def test_posiciones_cargadas_a_mano_no_se_pueden_replayear(self):
        import ledger_replay as lr
        self._pos(self.client_uid, "YPFD", 50)       # nunca pasó por un import
        conn = self._conn()
        try:
            v = lr.verificar_contra_hoy(conn, self.client_uid)
        finally:
            conn.close()
        self.assertFalse(v["reproducible"])
        self.assertEqual(v["motivo"], "sin_ledger")

    # ── el valor ───────────────────────────────────────────────────────────
    def test_valua_la_tenencia_con_el_precio_de_esa_fecha(self):
        import ledger_replay as lr, price_history as ph
        bid = self._batch(self.client_uid)
        # Ticker propio: los precios persisten entre tests y no se pisan.
        self._tx(bid, "2026-01-10", "BUY", "VALT", 10, broker="IBKR")
        self._pos(self.client_uid, "VALT", 10, broker="IBKR", ccy="USD")
        conn = self._conn()
        try:
            ph.guardar(conn, "VALT", {"2026-01-31": 200.0})
            conn.commit()
            v = lr.valor_en(conn, self.client_uid, "2026-01-31")
        finally:
            conn.close()
        self.assertEqual(v["valor"], 2000.0)
        self.assertEqual(v["cobertura_pct"], 100.0)
        self.assertEqual(v["fx_basis"], "usd")

    def test_una_pata_en_pesos_pasa_por_el_MEP_de_esa_fecha(self):
        import ledger_replay as lr, price_history as ph
        bid = self._batch(self.client_uid)
        self._tx(bid, "2026-01-10", "BUY", "GGAL", 100)
        self._pos(self.client_uid, "GGAL", 100)      # broker Cocos = ARS
        conn = self._conn()
        try:
            ph.guardar(conn, "GGAL.BA", {"2026-01-31": 7000.0})
            # Gemelo del sitio de arriba: misma fecha, mismos valores. El MEP
            # 1400 es el que este test asserta (100×7000/1400), así que pisar es
            # obligatorio (DO NOTHING dejaría el que puso el otro test).
            conn.execute("INSERT INTO fx_rates_daily (date,blue_venta,mep_venta) "
                         "VALUES ('2026-01-31',1500,1400) "
                         "ON CONFLICT (date) DO UPDATE SET "
                         "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta")
            conn.commit()
            v = lr.valor_en(conn, self.client_uid, "2026-01-31")
        finally:
            conn.close()
        self.assertAlmostEqual(v["valor"], 100 * 7000.0 / 1400, places=2)
        self.assertEqual(v["fx_basis"], "mep_venta")

    def test_sin_precio_de_un_activo_NO_se_publica_un_valor_corto(self):
        # Publicar un borde al que le falta un activo es fabricar una caída.
        import ledger_replay as lr, price_history as ph
        bid = self._batch(self.client_uid)
        self._tx(bid, "2026-01-10", "BUY", "AAPL", 10, broker="IBKR")
        self._tx(bid, "2026-01-10", "BUY", "RARO", 5, broker="IBKR")
        self._pos(self.client_uid, "AAPL", 10, broker="IBKR", ccy="USD")
        conn = self._conn()
        try:
            ph.guardar(conn, "AAPL", {"2026-01-31": 200.0})
            conn.commit()
            v = lr.valor_en(conn, self.client_uid, "2026-01-31")
        finally:
            conn.close()
        self.assertIsNone(v["valor"])
        self.assertEqual(v["motivo"], "cobertura_insuficiente")
        # La cobertura se mide por VALOR, no por conteo. Acá el activo sin
        # precio tampoco tiene costo conocido, así que su peso es DESCONOCIDO
        # — y peso desconocido no se certifica como cobertura.
        self.assertIsNone(v["cobertura_pct"])

    def test_sin_FX_no_se_inventa_una_tasa(self):
        import ledger_replay as lr, price_history as ph
        bid = self._batch(self.client_uid)
        self._tx(bid, "2026-01-10", "BUY", "GGAL", 100)
        self._pos(self.client_uid, "GGAL", 100)
        conn = self._conn()
        try:
            ph.guardar(conn, "GGAL.BA", {"2019-01-31": 7000.0})
            conn.execute("DELETE FROM fx_rates_daily WHERE date <= '2019-01-31'")
            conn.commit()
            v = lr.valor_en(conn, self.client_uid, "2019-01-31")
        finally:
            conn.close()
        self.assertIsNone(v["valor"])


class PrecioHistoricoTest(AdvisorBase):
    """El almacén de precios por fecha — prerrequisito de la reconstrucción."""

    def _conn(self):
        return main.get_db()

    def _sym(self, base):
        # asset_price_history persiste entre tests de la misma corrida y a
        # propósito NO se pisa un precio ya registrado — sin sufijo único, un
        # test le fija el precio a otro y el fallo parece del código.
        return f"{base}-{uuid.uuid4().hex[:6]}"

    def test_guarda_y_lee_el_precio_de_esa_fecha(self):
        import price_history as ph
        conn = self._conn()
        try:
            sym = self._sym("AAPL")
            ph.guardar(conn, sym, {"2026-01-29": 190.0, "2026-01-30": 195.5})
            conn.commit()
            self.assertEqual(ph.precio_en(conn, sym, "2026-01-30"), 195.5)
        finally:
            conn.close()

    def test_finde_toma_el_ultimo_cierre_anterior(self):
        # Los mercados cierran: pedir el precio de un domingo tiene que dar el
        # cierre del viernes, no None.
        import price_history as ph
        conn = self._conn()
        try:
            sym = self._sym("GGAL.BA")
            ph.guardar(conn, sym, {"2026-01-30": 100.0})   # viernes
            conn.commit()
            self.assertEqual(ph.precio_en(conn, sym, "2026-02-01"), 100.0)
        finally:
            conn.close()

    def test_un_precio_viejo_no_se_sirve_como_el_de_hoy(self):
        # Un ticker que dejó de cotizar no puede "tener precio" para siempre:
        # es lo que deja la serie PLANA, que pasa todos los guards y es peor
        # que un hueco porque el hueco se ve.
        import price_history as ph
        conn = self._conn()
        try:
            sym = self._sym("MUERTO")
            ph.guardar(conn, sym, {"2026-01-05": 50.0})
            conn.commit()
            self.assertEqual(ph.precio_en(conn, sym, "2026-01-08"), 50.0)
            self.assertIsNone(ph.precio_en(conn, sym, "2026-03-01"))
        finally:
            conn.close()

    def test_no_pisa_un_precio_ya_registrado(self):
        # Un precio guardado es un hecho de esa fecha. Si otra fuente devuelve
        # algo distinto después, el que vale es el primero.
        import price_history as ph
        conn = self._conn()
        try:
            sym = self._sym("AAPL")
            ph.guardar(conn, sym, {"2026-01-30": 195.5})
            n = ph.guardar(conn, sym, {"2026-01-30": 999.0}, source="otra")
            conn.commit()
            self.assertEqual(n, 0)
            self.assertEqual(ph.precio_en(conn, sym, "2026-01-30"), 195.5)
        finally:
            conn.close()

    def test_descarta_basura_de_la_fuente(self):
        # yfinance devuelve ruedas de '.BA' con volumen pero OHLC en NaN. Si eso
        # entra, después se sirve como si fuera un cierre real.
        import price_history as ph
        conn = self._conn()
        try:
            sym = self._sym("X.BA")
            ph.guardar(conn, sym, {"2026-01-05": 0, "2026-01-06": None,
                                   "2026-01-07": -3, "2026-01-08": 12.5})
            conn.commit()
            self.assertIsNone(ph.precio_en(conn, sym, "2026-01-05"))
            self.assertEqual(ph.precio_en(conn, sym, "2026-01-08"), 12.5)
        finally:
            conn.close()

    def test_cobertura_dice_cuales_faltan(self):
        # Con un símbolo sin precio, el total NO es el total: quien arma un
        # borde reconstruido tiene que saberlo ANTES de publicar un valor.
        import price_history as ph
        conn = self._conn()
        try:
            sym = self._sym("AAPL")
            ph.guardar(conn, sym, {"2026-01-30": 190.0})
            conn.commit()
            raro = self._sym("RARO")
            c = ph.cobertura(conn, [sym, raro], "2026-01-30")
            self.assertEqual(c["con_precio"], 1)
            self.assertEqual(c["faltan"], [raro])
            self.assertEqual(c["pct"], 50.0)
        finally:
            conn.close()

    def test_backfill_es_resumible_y_un_simbolo_roto_no_frena_la_tanda(self):
        import price_history as ph
        llamados = []

        def fake(sym, desde):
            llamados.append(sym)
            if sym == "ROTO":
                raise RuntimeError("la fuente falló")
            return {"2026-01-30": 10.0}

        conn = self._conn()
        try:
            a, roto, m = self._sym("AAPL"), "ROTO", self._sym("MSFT")
            r = ph.backfill(conn, [a, roto, m], "2026-01-01", fetcher=fake)
            conn.commit()
            self.assertEqual(r["resueltos"], 2)
            self.assertEqual(r["sin_serie"], ["ROTO"])
            # Segunda corrida: lo resuelto no se vuelve a pedir.
            llamados.clear()
            ph.backfill(conn, [a, roto, m], "2026-01-01", fetcher=fake)
            self.assertEqual(llamados, [roto])
        finally:
            conn.close()

    def test_el_lote_acota_las_llamadas_a_la_red(self):
        # El cuello de botella no son los tokens: son los rate limits.
        import price_history as ph
        llamados = []

        def fake(sym, desde):
            llamados.append(sym)
            return {"2026-01-30": 1.0}

        conn = self._conn()
        try:
            r = ph.backfill(conn, [self._sym(f"S{i}") for i in range(10)], "2026-01-01",
                            fetcher=fake, lote=3)
            conn.commit()
            self.assertEqual(len(llamados), 3)
            self.assertEqual(r["faltan"], 7)
        finally:
            conn.close()

    def test_los_simbolos_salen_de_la_misma_resolucion_que_el_snapshot(self):
        # Un CEDEAR en broker ARS se pide como '.BA'. Reinventar esta resolución
        # es lo que hizo que un CEDEAR comprado por dólar-MEP pidiera su ticker
        # US y quedara 15-100x inflado.
        import price_history as ph
        conn = self._conn()
        try:
            conn.execute("INSERT INTO positions (user_id,broker,asset,asset_type,"
                         "quantity,invested,is_cash) VALUES (?,?,?,?,1,100,0)",
                         (self.client_uid, "Cocos", "AAPL", "CEDEAR"))
            conn.commit()
            syms = ph.simbolos_de(conn, self.client_uid)
        finally:
            conn.close()
        self.assertIn("AAPL.BA", syms)
        self.assertNotIn("AAPL", syms)


class TwrInvariantesTest(AdvisorBase):
    """LAS INVARIANTES. Son la red que atrapa una deducción equivocada del
    agente reconstructor, y por eso van ANTES que él. Si alguna falla, el
    número NO se muestra — da igual lo convincente que se vea."""

    def _cliente(self, email):
        # Sufijo único: la clase del endpoint HEREDA estos tests, así que cada
        # email se usaría dos veces en la misma corrida y chocaría con el UNIQUE.
        email = f"{uuid.uuid4().hex[:8]}-{email}"
        conn = main.get_db()
        try:
            uid = conn.execute(
                "INSERT INTO users (email,password_hash,name) VALUES (?,?,'x')",
                (email, "h")).lastrowid
            conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,"
                         "invested,is_cash) VALUES (?,?,?,1,100,0)", (uid, "B", "AAPL"))
            conn.commit()
            return uid
        finally:
            conn.close()

    def _serie(self, uid, puntos, flujos=None):
        """puntos: [(fecha, valor)] como cierres REALES del cron.
        flujos: {'YYYY-MM': aporte_neto} escrito en monthly_entries (la SSoT)."""
        import json as _j
        conn = main.get_db()
        try:
            for d, v in puntos:
                conn.execute(
                    "INSERT INTO snapshots (user_id,date,total_value,total_invested,"
                    "fx_to_usd_blue,holdings_json,source) VALUES (?,?,?,?,1400,?,'cron')",
                    (uid, d, v, v, _j.dumps([{"asset": "AAPL", "value_usd": v}])))
            for mes, dep in (flujos or {}).items():
                y, m = (int(x) for x in mes.split("-"))
                conn.execute(
                    "INSERT INTO monthly_entries (user_id,broker,year,month,"
                    "capital_inicio,capital_final,deposits,withdrawals,pnl_realized,"
                    "pnl_unrealized) VALUES (?,'global',?,?,0,0,?,?,0,0)",
                    (uid, y, m, max(dep, 0), max(-dep, 0)))
            conn.commit()
        finally:
            conn.close()

    def _twr(self, uid):
        import twr
        conn = main.get_db()
        try:
            twr.sellar(conn, uid, hasta_mes="2027-01")
            conn.commit()
            return twr.twr_de(conn, uid)
        finally:
            conn.close()

    # ── 1. IDENTIDAD ───────────────────────────────────────────────────────
    def test_sin_flujos_el_encadenado_da_exactamente_final_sobre_inicial(self):
        # Sin plata entrando ni saliendo, el TWR NO es una aproximación: tiene
        # que dar EXACTAMENTE v_final/v_inicial − 1. Si no da, el encadenado
        # está mal y no hay nada más que discutir.
        uid = self._cliente("ident@x.com")
        self._serie(uid, [("2026-01-31", 100.0), ("2026-02-28", 110.0),
                          ("2026-03-31", 99.0), ("2026-04-30", 121.0)])
        r = self._twr(uid)
        self.assertAlmostEqual(r["twr"], 121.0 / 100.0 - 1.0, places=9)

    # ── 2. NEUTRALIDAD A FLUJOS (la propiedad que DEFINE time-weighted) ─────
    def test_misma_curva_flujos_distintos_mismo_twr(self):
        # Dos clientes con exactamente el mismo rendimiento de mercado pero
        # flujos completamente distintos tienen que dar el MISMO TWR. Es lo que
        # significa "time-weighted". Si difieren, el número NO es TWR.
        quieto = self._cliente("quieto@x.com")
        self._serie(quieto, [("2026-01-31", 100.0), ("2026-02-28", 110.0),
                             ("2026-03-31", 121.0)])

        # Mismos retornos (+10% y +10%) pero con un aporte de 50 en febrero:
        #   feb: v0=100, aporta 50 → (v1 − 100 − 50)/(100 + 25) = 0,10 → v1 = 162,5
        #   mar: +10% sobre 162,5 = 178,75
        aporta = self._cliente("aporta@x.com")
        self._serie(aporta, [("2026-01-31", 100.0), ("2026-02-28", 162.5),
                             ("2026-03-31", 178.75)], flujos={"2026-02": 50.0})

        a, b = self._twr(quieto), self._twr(aporta)
        self.assertAlmostEqual(a["twr"], b["twr"], places=9)
        self.assertAlmostEqual(a["twr"], 1.10 * 1.10 - 1, places=9)

    def test_un_retiro_tampoco_mueve_el_twr(self):
        # La contracara: sacar plata no puede leerse como una caída.
        #   feb: v0=100, retira 40 → (v1 − 100 + 40)/(100 − 20) = 0,10 → v1 = 68
        uid = self._cliente("retira@x.com")
        self._serie(uid, [("2026-01-31", 100.0), ("2026-02-28", 68.0)],
                    flujos={"2026-02": -40.0})
        self.assertAlmostEqual(self._twr(uid)["twr"], 0.10, places=9)

    # ── 3. EL DEPÓSITO NO ES RENDIMIENTO (el bug del hero, en test) ─────────
    def test_un_deposito_no_puede_leerse_como_ganancia(self):
        # Hoy el Δ7d del hero cuenta un depósito entero como rendimiento: en la
        # simulación daba +58% donde el real era +6,4%. Acá tiene que dar ~0.
        uid = self._cliente("dep@x.com")
        self._serie(uid, [("2026-01-31", 100.0), ("2026-02-28", 200.0)],
                    flujos={"2026-02": 100.0})
        r = self._twr(uid)
        self.assertAlmostEqual(r["twr"], 0.0, places=6)

    # ── 4. SELLADO: la historia no se mueve sola ───────────────────────────
    def test_sellar_dos_veces_no_duplica_ni_cambia_nada(self):
        import twr
        uid = self._cliente("idem@x.com")
        self._serie(uid, [("2026-01-31", 100.0), ("2026-02-28", 110.0)])
        primero = self._twr(uid)
        conn = main.get_db()
        try:
            r2 = twr.sellar(conn, uid, hasta_mes="2027-01")
            conn.commit()
            n = conn.execute("SELECT COUNT(*) c FROM twr_periods WHERE user_id=?",
                             (uid,)).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(r2, {"sellados": 0, "revisados": 0})
        self.assertEqual(n, 1)
        self.assertAlmostEqual(primero["twr"], self._twr(uid)["twr"], places=9)

    def test_si_le_reescriben_la_historia_se_guarda_revision_nueva(self):
        # Un import viejo (o el hook que corre en cada deploy) cambia el
        # aportado hacia atrás. La revisión vieja NO se pisa: queda, y el
        # asesor tiene que poder ver que la historia le cambió.
        import twr
        uid = self._cliente("rev@x.com")
        self._serie(uid, [("2026-01-31", 100.0), ("2026-02-28", 150.0)])
        self._twr(uid)
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO monthly_entries (user_id,broker,year,month,"
                         "capital_inicio,capital_final,deposits,withdrawals,"
                         "pnl_realized,pnl_unrealized) VALUES (?,'global',2026,2,0,0,40,0,0,0)",
                         (uid,))
            conn.commit()
            r = twr.sellar(conn, uid, hasta_mes="2027-01")
            conn.commit()
            revs = [x["revision"] for x in conn.execute(
                "SELECT revision FROM twr_periods WHERE user_id=? AND month='2026-02' "
                "ORDER BY revision", (uid,)).fetchall()]
        finally:
            conn.close()
        self.assertEqual(r["revisados"], 1)
        self.assertEqual(revs, [1, 2])                       # la vieja sigue ahí
        self.assertIn("2026-02", self._twr(uid)["meses_revisados"])

    def test_el_periodo_sellado_sobrevive_al_borrado_de_sus_snapshots(self):
        # revert_batch y delete_broker borran snapshots por rango y se llevan
        # mediciones que no se recuperan. El número sellado no puede irse con
        # ellas.
        uid = self._cliente("borra@x.com")
        self._serie(uid, [("2026-01-31", 100.0), ("2026-02-28", 110.0)])
        antes = self._twr(uid)["twr"]
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM snapshots WHERE user_id=?", (uid,))
            conn.commit()
            import twr
            despues = twr.twr_de(conn, uid)["twr"]
        finally:
            conn.close()
        self.assertAlmostEqual(antes, despues, places=9)

    # ── 5. SOLO MEDICIONES ─────────────────────────────────────────────────
    def test_una_foto_intradia_no_puede_ser_borde_de_periodo(self):
        import twr
        uid = self._cliente("intra@x.com")
        self._serie(uid, [("2026-01-31", 100.0), ("2026-03-31", 110.0)])
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO snapshots (user_id,date,total_value,"
                         "total_invested,fx_to_usd_blue,source) "
                         "VALUES (?,'2026-02-28',999,999,1400,'browser')", (uid,))
            conn.commit()
            meses = [t["month"] for t in twr.tramos(conn, uid, hasta_mes="2027-01")]
        finally:
            conn.close()
        self.assertNotIn("2026-02", meses)     # el 999 no entra a la cadena
        self.assertEqual(meses, ["2026-03"])

    def test_el_mes_en_curso_no_se_sella(self):
        import twr
        from datetime import datetime, timedelta
        hoy = (datetime.utcnow() - timedelta(hours=3)).date()
        uid = self._cliente("curso@x.com")
        conn = main.get_db()
        try:
            twr.sellar(conn, uid)
            n = conn.execute("SELECT COUNT(*) c FROM twr_periods WHERE user_id=? "
                             "AND month=?", (uid, hoy.strftime("%Y-%m"))).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(n, 0)

    # ── 6. SIN TECHO ───────────────────────────────────────────────────────
    def test_un_mes_de_mas_80_por_ciento_no_se_trunca(self):
        # El clamp de +50% del lado retail trunca meses reales y NO se le aplica
        # al benchmark: el sesgo va sistemáticamente en contra del usuario.
        import twr
        self.assertAlmostEqual(twr.dietz(100.0, 180.0, 0.0), 0.80, places=9)
        self.assertIsNone(twr.dietz(0.0, 50.0, 0.0))          # sin capital no hay retorno
        self.assertAlmostEqual(twr.dietz(100.0, 0.0, 0.0), -1.0, places=9)


class TwrEndpointTest(TwrInvariantesTest):
    """El TWR expuesto: cobertura pegada, y piso de meses."""

    def test_endpoint_devuelve_el_twr_con_su_cobertura(self):
        conn = main.get_db()
        try:
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, self.client_uid))
            conn.commit()
        finally:
            conn.close()
        self._serie(self.client_uid, [("2026-01-31", 100.0), ("2026-02-28", 110.0),
                                      ("2026-03-31", 121.0), ("2026-04-30", 133.1)])
        r = self.http.get("/api/advisor/twr", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        c = r.json()["clientes"][0]
        self.assertAlmostEqual(c["twr"], 1.331 - 1, places=6)
        self.assertEqual(c["meses"], 3)

    def test_con_menos_de_tres_meses_no_se_publica_un_porcentaje(self):
        self._serie(self.client_uid, [("2026-01-31", 100.0), ("2026-02-28", 110.0)])
        r = self.http.get("/api/advisor/twr", headers=self._hdr(self.advisor)).json()
        c = r["clientes"][0]
        self.assertIsNone(c["twr"])
        self.assertEqual(c["motivo"], "pocos_meses")
        self.assertEqual(c["meses"], 1)


class TwrFase0Test(AdvisorBase):
    """Semáforo de datos: clasificar cada snapshot por quién lo escribió."""

    def _snap(self, uid, d, v, fx=None, hold=None, source=None):
        import json as _j
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO snapshots (user_id,date,total_value,total_invested,"
                "fx_to_usd_blue,holdings_json,source) VALUES (?,?,?,?,?,?,?)",
                (uid, d, v, v, fx, _j.dumps(hold) if hold else None, source))
            conn.commit()
        finally:
            conn.close()

    def _pos(self, uid, is_cash=0):
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,invested,is_cash) "
                         "VALUES (?,?,?,1,100,?)", (uid, "Cocos", "AAPL", is_cash))
            conn.commit()
        finally:
            conn.close()

    def _diag(self, uid):
        import twr
        conn = main.get_db()
        try:
            return twr.diagnosticar(conn, [uid])[uid]
        finally:
            conn.close()

    # ── La prueba negativa dura del plan ────────────────────────────────────
    def test_cliente_solo_con_cron_no_tiene_ni_un_sintetico(self):
        # Si acá aparece un sintético, la heurística tiene falsos positivos y NO
        # se puede usar para excluir tramos. Es el mismo error que ya se cometió
        # una vez con la detección de fotos "sintéticas" del Dashboard, que
        # terminó borrando mediciones REALES.
        import twr
        self._pos(self.client_uid)
        for d, v in (("2026-07-10", 100), ("2026-07-11", 101), ("2026-07-12", 102)):
            self._snap(self.client_uid, d, v, fx=1400,
                       hold=[{"asset": "AAPL", "value_usd": v}])
        d = self._diag(self.client_uid)
        self.assertEqual(d["por_clase"][twr.SINTETICO_COSTO], 0)
        self.assertEqual(d["por_clase"][twr.MEDICION], 3)
        self.assertEqual(d["medible_desde"], "2026-07-10")
        self.assertIsNone(d["motivo"])

    def test_cliente_todo_en_pesos_igual_es_medible(self):
        # El cron excluye el cash de holdings, así que una cartera 100% en pesos
        # deja holdings_json en NULL aunque el cron haya corrido perfecto.
        # Exigir esa columna lo marcaría "no medible" mintiendo.
        import twr
        self._pos(self.client_uid, is_cash=1)
        self._snap(self.client_uid, "2026-07-10", 50, fx=1400)
        self._snap(self.client_uid, "2026-07-11", 51, fx=1400)
        d = self._diag(self.client_uid)
        self.assertEqual(d["por_clase"][twr.MEDICION], 2)
        self.assertEqual(d["medible_desde"], "2026-07-10")

    def test_historia_importada_no_es_medible(self):
        import twr
        self._pos(self.client_uid)
        self._snap(self.client_uid, "2026-05-31", 80)   # fin de mes, nada estampado
        self._snap(self.client_uid, "2026-06-30", 82)
        d = self._diag(self.client_uid)
        self.assertEqual(d["por_clase"][twr.SINTETICO_COSTO], 2)
        self.assertIsNone(d["medible_desde"])
        self.assertEqual(d["motivo"], "importado_sin_mediciones")

    def test_una_sola_medicion_no_alcanza(self):
        # Con un solo borde no hay tramo que medir.
        self._pos(self.client_uid)
        self._snap(self.client_uid, "2026-07-10", 100, fx=1400,
                   hold=[{"asset": "AAPL", "value_usd": 100}])
        d = self._diag(self.client_uid)
        self.assertIsNone(d["medible_desde"])
        self.assertEqual(d["motivo"], "una_sola_medicion")

    def test_la_columna_source_manda_sobre_la_heuristica(self):
        # Una fila con composición estampada pero source='browser' NO es una
        # medición: el hecho gana sobre la deducción.
        import twr
        self._pos(self.client_uid)
        self._snap(self.client_uid, "2026-07-10", 100, fx=1400,
                   hold=[{"asset": "AAPL", "value_usd": 100}], source="browser")
        d = self._diag(self.client_uid)
        self.assertEqual(d["por_clase"][twr.INTRADIA], 1)
        self.assertEqual(d["por_clase"][twr.MEDICION], 0)

    def test_serie_congelada_se_marca(self):
        # Un precio congelado (ticker delisted en asset_last_price, sin TTL) deja
        # la serie plana. Es peor que un hueco: el hueco se ve.
        self._pos(self.client_uid)
        for d_ in ("2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13"):
            self._snap(self.client_uid, d_, 100.0, fx=1400,
                       hold=[{"asset": "AAPL", "value_usd": 100.0}])
        d = self._diag(self.client_uid)
        self.assertTrue(d["tramos_planos"])
        self.assertGreaterEqual(d["tramos_planos"][0]["ruedas"], 3)

    def test_endpoint_del_libro_devuelve_cobertura(self):
        self._pos(self.client_uid)
        self._snap(self.client_uid, "2026-07-10", 100, fx=1400,
                   hold=[{"asset": "AAPL", "value_usd": 100}], source="cron")
        self._snap(self.client_uid, "2026-07-11", 101, fx=1400,
                   hold=[{"asset": "AAPL", "value_usd": 101}], source="cron")
        r = self.http.get("/api/advisor/data-health", headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["resumen"]["total"], 1)
        self.assertEqual(body["resumen"]["medibles"], 1)
        self.assertEqual(body["resumen"]["cobertura_pct"], 100.0)
        self.assertEqual(body["clientes"][0]["medible_desde"], "2026-07-10")

    def test_el_semaforo_no_escribe_nada(self):
        # Read-only es parte del contrato de la Fase 0.
        self._pos(self.client_uid)
        self._snap(self.client_uid, "2026-07-10", 100, fx=1400,
                   hold=[{"asset": "AAPL", "value_usd": 100}])
        conn = main.get_db()
        try:
            antes = conn.execute("SELECT COUNT(*) c FROM snapshots").fetchone()["c"]
        finally:
            conn.close()
        self.http.get("/api/advisor/data-health", headers=self._hdr(self.advisor))
        conn = main.get_db()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM snapshots").fetchone()["c"], antes)
        finally:
            conn.close()


class AdvisorGroupsAuditTest(AdvisorBase):
    """Regresiones del audit de los grupos (ff6f7b7)."""

    def _pos(self, cid, asset, qty, invested, broker="IBKR"):
        conn = main.get_db()
        try:
            conn.execute("INSERT OR IGNORE INTO brokers (user_id,name,currency) VALUES (?,?,'USD')",
                         (cid, broker))
            conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,invested,is_cash) "
                         "VALUES (?,?,?,?,?,0)", (cid, broker, asset, qty, invested))
            # Helper llamado VARIAS veces por test con el mismo activo (3 lotes
            # de AAPL) ⇒ el conflicto es la norma acá. Las 3 columnas de la
            # tabla están nombradas, así que DO UPDATE es exactamente lo mismo
            # que el borrar-y-reinsertar de antes.
            conn.execute("INSERT INTO asset_last_price (symbol,price,updated_at) "
                         "VALUES (?,?,datetime('now')) "
                         "ON CONFLICT (symbol) DO UPDATE SET "
                         "price=EXCLUDED.price, updated_at=EXCLUDED.updated_at",
                         (asset, 100.0))
            conn.commit()
        finally:
            conn.close()

    def test_varios_lotes_del_mismo_activo_no_inflan_la_cartera(self):
        # 3 compras de 50 AAPL a US$ 100 = US$ 15.000, no 45.000. Antes se
        # agregaba por activo y después se sumaba ese total en CADA fila, así
        # que la cartera escalaba con la cantidad de lotes y el cliente entraba
        # a un grupo "más de US$ 20.000" que no le correspondía.
        import advisor_groups as ag
        for _ in range(3):
            self._pos(self.client_uid, "AAPL", 50, 5000)
        conn = main.get_db()
        try:
            prof = ag.client_profiles(conn, self.advisor)
            self.assertAlmostEqual(prof[self.client_uid]["total_usd"], 15000, places=2)
            self.assertEqual(ag.evaluate(conn, self.advisor, {"aum_min": 20000}), [])
            self.assertEqual(len(ag.evaluate(conn, self.advisor, {"aum_min": 10000})), 1)
        finally:
            conn.close()

    def test_patch_sin_excluded_no_borra_las_exclusiones(self):
        # El asesor sacó a alguien a mano; editar las condiciones no puede
        # devolverlo al grupo en silencio.
        import json as _j
        h = self._hdr(self.advisor)
        r = self.http.post("/api/advisor/groups", headers=h,
                             json={"name": "g", "rules": {"has_asset": "AMZN"}, "excluded": [999]})
        gid = r.json()["id"]
        self.http.patch(f"/api/advisor/groups/{gid}", headers=h,
                          json={"name": "g", "rules": {"has_asset": "AMZN", "aum_min": 100}})
        conn = main.get_db()
        try:
            row = conn.execute("SELECT excluded FROM advisor_groups WHERE id=?", (gid,)).fetchone()
            self.assertEqual(_j.loads(row["excluded"]), [999])
        finally:
            conn.close()

    def test_excluded_invalido_da_422_y_no_500(self):
        h = self._hdr(self.advisor)
        r = self.http.post("/api/advisor/groups", headers=h,
                             json={"name": "g", "rules": {"has_asset": "AMZN"},
                                   "excluded": ["no-soy-un-id"]})
        self.assertEqual(r.status_code, 422)

    def test_borrar_el_grupo_apaga_la_alerta_en_vez_de_dejarla_muda(self):
        # Activa-y-muda es la peor combinación: el panel dice "Activa", no
        # llega nada nunca más, y todo PATCH rebotaba con 404.
        import advisor_alerts as aa
        h = self._hdr(self.advisor)
        gid = self.http.post("/api/advisor/groups", headers=h,
                               json={"name": "g", "rules": {"has_asset": "AMZN"}}).json()["id"]
        self.http.patch("/api/advisor/alerts", headers=h,
                          json={"up_pct": 5, "down_pct": 5, "active": True, "group_id": gid})
        self.assertEqual(self.http.delete(f"/api/advisor/groups/{gid}", headers=h).status_code, 200)
        cfg = self.http.get("/api/advisor/alerts", headers=h).json()["config"]
        self.assertIsNone(cfg["group_id"])
        self.assertFalse(cfg["active"])
        # y el panel se puede seguir usando (antes: 404 en cada guardado)
        self.assertEqual(self.http.patch("/api/advisor/alerts", headers=h,
                                           json={"active": False}).status_code, 200)

    def test_borrar_la_cuenta_se_lleva_los_grupos(self):
        h = self._hdr(self.advisor)
        self.http.post("/api/advisor/groups", headers=h,
                         json={"name": "privado", "rules": {"has_asset": "AMZN"}})
        self.http.delete("/api/me", headers=h)
        conn = main.get_db()
        try:
            n = conn.execute("SELECT COUNT(*) c FROM advisor_groups WHERE advisor_uid=?",
                             (self.advisor,)).fetchone()["c"]
            self.assertEqual(n, 0)
        finally:
            conn.close()


class AdvisorAlertsGroupScopeTest(AdvisorAlertsAuditTest):
    """La alerta del libro acotada a un grupo: sólo avisa de los que cumplen
    la regla HOY. Hereda el harness (_run / _base_snapshot) del audit."""

    def _mk_group(self, rules):
        import json as _j
        conn = main.get_db()
        try:
            cur = conn.execute(
                "INSERT INTO advisor_groups (advisor_uid, name, rules, excluded) VALUES (?,?,?,?)",
                (self.advisor, "Grupo", _j.dumps(rules), "[]"))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _set_scope(self, gid):
        import advisor_alerts as aa
        conn = main.get_db()
        try:
            aa.set_config(conn, self.advisor, group_id=gid)
            conn.commit()
        finally:
            conn.close()

    def test_cliente_fuera_del_grupo_no_dispara(self):
        # El cliente no tiene AMZN → el grupo "los de Amazon" lo deja afuera,
        # así que su +20% no genera aviso.
        self._base_snapshot()
        gid = self._mk_group({"has_asset": "AMZN"})
        self._set_scope(gid)
        self.assertEqual(self._run(12000)["fired"], 0)

    def test_sin_grupo_avisa_de_todo_el_libro(self):
        # Volver a "todos" reabre el aviso: el scope no queda pegado.
        self._base_snapshot()
        self._set_scope(None)
        self.assertEqual(self._run(12000)["fired"], 1)

    def test_el_que_sale_del_grupo_y_vuelve_sigue_avisando(self):
        # Disparó una vez, después dejó de cumplir la regla, y cuando vuelve
        # —justo cuando el asesor lo quiere mirar— tiene que poder avisar de
        # nuevo. Antes quedaba con armed=0 para siempre porque el filtro lo
        # sacaba antes de la rama que re-arma.
        import advisor_alerts as aa, advisor_brief
        self._base_snapshot()
        gid = self._mk_group({"has_asset": "AMZN"})
        conn = main.get_db()
        try:
            aa.set_config(conn, self.advisor, up_pct=5, down_pct=5, active=True)
            conn.commit()
        finally:
            conn.close()
        self._set_scope(gid)          # el cliente NO tiene AMZN → queda afuera
        # El armed=0 se siembra DESPUÉS del scope: cambiar el alcance re-arma a
        # todos, así que sembrarlo antes hacía pasar el test sin probar nada.
        conn = main.get_db()
        try:
            # ⚠️ ÚNICO sitio de este archivo donde el OR REPLACE SÍ borraba una
            # columna: `advisor_alert_state` tiene 4 (advisor_uid, client_uid,
            # armed, last_fired_date) y acá se nombran 3. El borrado de
            # `last_fired_date` es INTENCIONAL y load-bearing, así que se
            # replica poniéndola explícita en el SET:
            #   la rama que este test prueba (advisor_alerts.py:221) re-arma con
            #   `... WHERE COALESCE(last_fired_date,'') <> hoy`. Si dejáramos
            #   sobrevivir un last_fired_date = HOY, el UPDATE no tocaría la
            #   fila, armed seguiría en 0 y el test fallaría por una razón que
            #   no tiene nada que ver con el bug que fija.
            # Hoy la fila todavía no existe cuando se llega acá (set_config y
            # _set_scope sólo hacen UPDATE, no INSERT, y este test no pasa por
            # _run), o sea que el DO UPDATE no llega a correr — pero se deja
            # escrito para que siga siendo el estado "nunca disparó" si mañana
            # alguien mete una corrida antes.
            conn.execute("INSERT INTO advisor_alert_state "
                         "(advisor_uid,client_uid,armed) VALUES (?,?,0) "
                         "ON CONFLICT (advisor_uid, client_uid) DO UPDATE SET "
                         "armed=EXCLUDED.armed, last_fired_date=NULL",
                         (self.advisor, self.client_uid))
            conn.commit()
        finally:
            conn.close()
        # OJO: no se usa self._run — ese helper BORRA advisor_alert_state antes
        # de cada corrida, y por eso la suite nunca probaba dos corridas
        # encadenadas (que es exactamente donde vivía este bug).
        conn = main.get_db()
        try:
            _d0, _l0 = aa._deliver, advisor_brief.live_book_values
            aa._deliver = lambda *a, **k: (True, True)
            advisor_brief.live_book_values = lambda c, i, p: {self.client_uid: 10000}
            try:
                aa.evaluate(conn, market_open=True, only_uid=self.advisor)
            finally:
                aa._deliver, advisor_brief.live_book_values = _d0, _l0
        finally:
            conn.close()
        conn = main.get_db()
        try:
            armed = conn.execute("SELECT armed FROM advisor_alert_state WHERE advisor_uid=? "
                                 "AND client_uid=?", (self.advisor, self.client_uid)).fetchone()["armed"]
            self.assertEqual(armed, 1, "el que queda fuera del grupo tiene que re-armarse")
        finally:
            conn.close()

    def test_grupo_borrado_no_avisa_de_mas(self):
        # Si el grupo ya no existe NO caemos a "todo el libro" en silencio:
        # avisar de más es peor que no avisar.
        self._base_snapshot()
        gid = self._mk_group({"has_asset": "AMZN"})
        self._set_scope(gid)
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_groups WHERE id=?", (gid,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self._run(12000)["fired"], 0)


class AdvisorGroupsTest(AdvisorBase):
    """Grupos de clientes: filtros guardados y DINÁMICOS."""

    def test_classify_no_inventa_clases(self):
        import advisor_groups as ag
        self.assertEqual(ag.classify("GGAL.BA"), "ar_stock")
        self.assertEqual(ag.classify("YPFD.BA"), "ar_stock")
        self.assertEqual(ag.classify("AAPL.BA", "CEDEAR"), "cedear")
        self.assertEqual(ag.classify("AL30", "BOND"), "bond")
        self.assertEqual(ag.classify("FCI:balanz-money-market"), "fund")
        self.assertEqual(ag.classify("BTC", "CRYPTO"), "crypto")
        self.assertEqual(ag.classify("AAPL"), "us_stock")
        # lo que no reconoce NO se clasifica (mejor 'otro' que mentir en el %)
        self.assertEqual(ag.classify("ZZZQQQ"), "otro")

    def test_normalize_descarta_basura(self):
        import advisor_groups as ag
        self.assertEqual(ag.normalize_rules({}), {})
        self.assertEqual(ag.normalize_rules({"aum_min": "no-es-numero"}), {})
        self.assertEqual(ag.normalize_rules({"aum_min": -5}), {})
        self.assertEqual(ag.normalize_rules({"class": "inventada"}), {})
        self.assertEqual(ag.normalize_rules({"class_pct_min": 30}), {})
        r = ag.normalize_rules({"class": "ar_stock"})
        self.assertEqual(r["class"], "ar_stock")
        self.assertEqual(r["class_pct_min"], 1.0)

    def test_crud_y_gate(self):
        r = self.http.post("/api/advisor/groups",
                           json={"name": "Los de Amazon", "rules": {"has_asset": "amzn"}},
                           headers=self._hdr(self.advisor))
        self.assertEqual(r.status_code, 200, r.text)
        gid = r.json()["id"]
        self.assertEqual(r.json()["rules"]["has_asset"], "AMZN")
        got = self.http.get("/api/advisor/groups", headers=self._hdr(self.advisor)).json()
        self.assertTrue(any(g["id"] == gid for g in got["groups"]))
        self.assertTrue(any(c["key"] == "ar_stock" for c in got["classes"]))
        self.assertEqual(self.http.post("/api/advisor/groups",
                                        json={"name": "Vacio", "rules": {}},
                                        headers=self._hdr(self.advisor)).status_code, 400)
        conn = main.get_db()
        try:
            cur = conn.execute("INSERT INTO users (email,name,password_hash) VALUES (?,'N','x')",
                               (f"nogrp.{uuid.uuid4().hex[:8]}@x.co",))
            otro = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.http.get("/api/advisor/groups",
                                       headers=self._hdr(otro)).status_code, 403)
        self.assertEqual(self.http.delete(f"/api/advisor/groups/{gid}",
                                          headers=self._hdr(self.advisor)).status_code, 200)

    def test_grupo_es_dinamico_y_aisla_por_asesor(self):
        import advisor_groups as ag
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM positions WHERE user_id=?", (self.client_uid,))
            conn.execute("INSERT OR IGNORE INTO brokers (user_id,name,currency) VALUES (?,'GrpBroker','USDT')",
                         (self.client_uid,))
            conn.commit()
            rules = ag.normalize_rules({"has_asset": "AMZN"})
            self.assertEqual(len(ag.evaluate(conn, self.advisor, rules)), 0)
            conn.execute("""INSERT INTO positions (user_id,broker,asset,asset_type,currency,
                            is_cash,invested,quantity) VALUES (?,'GrpBroker','AMZN.BA','CEDEAR','USD',0,5000,1)""",
                         (self.client_uid,))
            conn.commit()
            res = ag.evaluate(conn, self.advisor, rules)
            self.assertEqual([c["client_uid"] for c in res], [self.client_uid])
            self.assertEqual(len(ag.evaluate(conn, self.advisor, rules,
                                             excluded=[self.client_uid])), 0)
            cur = conn.execute("INSERT INTO users (email,name,password_hash,tier) VALUES (?,'Otro','x','advisor')",
                               (f"otroadv.{uuid.uuid4().hex[:8]}@x.co",))
            otro_adv = cur.lastrowid
            conn.commit()
            self.assertEqual(len(ag.evaluate(conn, otro_adv, rules)), 0)
        finally:
            conn.close()
