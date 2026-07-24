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
