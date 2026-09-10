"""Reset de ADMIN por email (POST /api/admin/reset-user): deja una cuenta como el
día que se registró, SIN tocar el login ni el plan pago.

Por qué existe: "Empezar de cero" (el botón del usuario) está pausado desde el
13/08 porque un borrado masivo desbordaba el escritor único de SQLite y el
`database is locked` le salía a TODOS. Este camino lo dispara una sola persona,
en el momento que elige, midiendo antes cuántas filas son y frenando entre tandas.

Lo que estos tests fijan, en orden de gravedad:
  1. NO puede tocar plata ni identidad (plan, suscripción, crédito, login).
  2. Borra de verdad TODO lo demás, incluidas las tablas que el reset del usuario
     no borraba (alertas, seguidos, credenciales, prefs, perfil de inversor) y
     `futures_positions`, que nació después del allowlist original.
  3. El preview no escribe, y su número coincide con lo que después se borra.
  4. No corre sobre la cuenta equivocada.

Corre con: cd backend && python3 -m pytest tests/test_reset_admin.py
"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
import main


# Lo que el reset NUNCA puede tocar: plata, identidad y los contadores sobre los
# que se apoya un límite (si se borran, "resetear" pasa a ser regalarse cuota).
PROHIBIDAS = {
    "users", "subscriptions", "credit_ledger", "billing_events", "plan_events",
    "login_history", "password_reset_tokens", "email_verification_codes",
    "push_subscriptions", "ai_usage_daily", "ai_tool_usage", "trial_consumed",
    "advisor_clients", "advisor_profile", "advisor_reports",
}


class ResetAdminTest(unittest.TestCase):
    _seq = 8800

    def setUp(self):
        ResetAdminTest._seq += 1
        self.UID = ResetAdminTest._seq          # el usuario a resetear
        self.ADMIN = ResetAdminTest._seq + 500  # quien aprieta el botón
        self.EMAIL = f"reset{self.UID}@t.com"
        self.conn = main.get_db()
        c = self.conn
        c.execute("INSERT INTO users (id,email,password_hash,approved,tier,"
                  "credit_active_until,credit_anchor_plan,investor_profile) "
                  "VALUES (?,?,?,1,'pro','2026-12-01','pro','moderado')",
                  (self.UID, self.EMAIL, "HASH"))
        c.execute("INSERT INTO users (id,email,password_hash,approved,is_admin) VALUES (?,?,?,1,1)",
                  (self.ADMIN, f"admin{self.ADMIN}@t.com", "HASH"))
        # ── PLATA E IDENTIDAD (tiene que sobrevivir enterito) ──────────────
        c.execute("INSERT INTO subscriptions (user_id,external_reference,period,status,"
                  "amount_ars,mp_subscription_id) VALUES (?,?,'monthly','authorized',9999,'MP-1')",
                  (self.UID, f"rendi-{self.UID}-monthly"))
        c.execute("INSERT INTO credit_ledger (user_id,kind,amount_usd,days_delta) "
                  "VALUES (?,'comp',0,30)", (self.UID,))
        c.execute("INSERT INTO push_subscriptions (user_id,endpoint,p256dh,auth) "
                  "VALUES (?,'https://push/x','K','A')", (self.UID,))
        c.execute("INSERT INTO ai_usage_daily (user_id,date,analyses_count) VALUES (?,'2026-09-01',7)",
                  (self.UID,))
        c.execute("INSERT INTO login_history (user_id) VALUES (?)", (self.UID,))
        # ── CARTERA Y CONFIGURACIÓN (tiene que irse todo) ──────────────────
        c.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,'Cocos','ARS')", (self.UID,))
        c.execute("INSERT INTO positions (user_id,broker,asset,quantity,invested,is_cash) "
                  "VALUES (?,'Cocos','MSFT',10,1000,0)", (self.UID,))
        c.execute("INSERT INTO operations (user_id,broker,asset,op_type,quantity,date) "
                  "VALUES (?,'Cocos','MSFT','Compra',10,'2026-02-06')", (self.UID,))
        c.execute("INSERT INTO snapshots (user_id,date,total_value,total_invested,net_deposited) "
                  "VALUES (?,'2026-08-01',5000,4000,4000)", (self.UID,))
        c.execute("INSERT INTO futures_positions (user_id,broker,symbol,side,quantity,entry_price,opened_at) "
                  "VALUES (?,'BingX','BTCUSDT','long',1,60000,'2026-08-01')", (self.UID,))
        c.execute("INSERT INTO alerts (user_id,kind) VALUES (?,'price_target')", (self.UID,))
        c.execute("INSERT INTO alert_events (alert_id,user_id) VALUES (1,?)", (self.UID,))
        c.execute("INSERT INTO watchlist (user_id,symbol) VALUES (?,'AAPL')", (self.UID,))
        c.execute("INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) "
                  "VALUES (?,'wallbit','ENC')", (self.UID,))
        c.execute("INSERT INTO import_mappings (user_id,name,mapping_json) VALUES (?,'cocos','{}')",
                  (self.UID,))
        c.execute("INSERT INTO config (user_id,key,value) VALUES (?,'onboarding','done'),"
                  "(?,'display_currency','ARS'),(?,'fx_version','v2')",
                  (self.UID, self.UID, self.UID))
        self.conn.commit()

    def tearDown(self):
        for t in ("users", "subscriptions", "credit_ledger", "push_subscriptions",
                  "ai_usage_daily", "login_history", "config",
                  *main._reset_admin_tablas()):
            for u in (self.UID, self.ADMIN):
                try:
                    self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (u,))
                except Exception:
                    try:
                        self.conn.execute(f"DELETE FROM {t} WHERE id=?", (u,))
                    except Exception:
                        pass
        self.conn.commit()
        self.conn.close()
        main._reset_progress.pop(self.UID, None)

    # ── helpers ───────────────────────────────────────────────────────────
    def _n(self, tbl, extra=""):
        c = main.get_db()
        try:
            return c.execute(f"SELECT COUNT(*) FROM {tbl} WHERE user_id=? {extra}",
                             (self.UID,)).fetchone()[0]
        finally:
            c.close()

    def _resetear(self, email=None, confirmar=None):
        """Dispara el reset por el MISMO camino que produce y espera el final."""
        out = main.admin_reset_user(
            main.AdminResetUserIn(email=email or self.EMAIL,
                                  confirmar_email=confirmar or email or self.EMAIL),
            uid=self.ADMIN)
        self.assertTrue(out["ok"])
        for _ in range(200):                      # 200 × 50ms = 10s de techo
            st = main.admin_reset_user_status(user_id=self.UID, uid=self.ADMIN)
            if st["estado"] != "corriendo":
                self.assertEqual(st["estado"], "listo", st.get("error"))
                return st
            time.sleep(0.05)
        self.fail("el reset no terminó en 10s")

    # ── 1) lo que NO se puede tocar ───────────────────────────────────────
    def test_conserva_login_plan_y_contadores(self):
        self._resetear()
        c = main.get_db()
        try:
            u = c.execute("SELECT email, password_hash, tier, credit_active_until "
                          "FROM users WHERE id=?", (self.UID,)).fetchone()
        finally:
            c.close()
        self.assertIsNotNone(u, "el usuario NO se borra: sigue pudiendo entrar")
        self.assertEqual(u["email"], self.EMAIL)
        self.assertEqual(u["password_hash"], "HASH", "la contraseña no se toca")
        self.assertEqual(u["tier"], "pro", "el plan PAGO no se toca")
        self.assertEqual(u["credit_active_until"], "2026-12-01")
        self.assertEqual(self._n("subscriptions"), 1, "la suscripción paga no se toca")
        self.assertEqual(self._n("credit_ledger"), 1)
        self.assertEqual(self._n("push_subscriptions"), 1,
                         "el permiso de notificaciones del dispositivo no se toca")
        self.assertEqual(self._n("ai_usage_daily"), 1,
                         "el contador de cuota de IA no se toca: borrarlo es regalar cuota")
        self.assertEqual(self._n("login_history"), 1)

    def test_ninguna_tabla_de_plata_en_el_allowlist(self):
        """El allowlist es explícito justamente para esto. Si alguien agrega una
        tabla de billing/identidad, este test lo caza antes que un usuario que pagó."""
        self.assertEqual(set(main._reset_admin_tablas()) & PROHIBIDAS, set())

    def test_allowlist_solo_tablas_con_user_id(self):
        """Una tabla GLOBAL (cache por ticker, sin user_id) en el allowlist borraría
        datos de TODOS. Antes pasó con `asset_last_price`, y el error se tragaba."""
        conn = main.get_db()
        try:
            for t in main._reset_admin_tablas():
                cols = [c["name"] for c in conn.execute(f"PRAGMA table_info({t})")]
                self.assertTrue(cols, f"{t} no existe como tabla")
                self.assertIn("user_id", cols, f"{t} no tiene user_id — es global")
        finally:
            conn.close()

    # ── 2) borra de verdad ────────────────────────────────────────────────
    def test_deja_la_cuenta_en_cero(self):
        self._resetear()
        for tbl in main._reset_admin_tablas():
            self.assertEqual(self._n(tbl), 0, f"{tbl} debería quedar vacío")
        self.assertEqual(self._n("config"), 0,
                         "las prefs se van TODAS (incluye onboarding y moneda elegida)")
        c = main.get_db()
        try:
            perfil = c.execute("SELECT investor_profile FROM users WHERE id=?",
                               (self.UID,)).fetchone()[0]
        finally:
            c.close()
        self.assertIsNone(perfil, "el perfil de inversor declarado en el onboarding se limpia")

    def test_borra_futuros(self):
        """`futures_positions` es cartera y nació DESPUÉS del allowlist original:
        el reset viejo dejaba futuros abiertos en una cuenta supuestamente vacía."""
        self.assertEqual(self._n("futures_positions"), 1)
        self._resetear()
        self.assertEqual(self._n("futures_positions"), 0)

    def test_idempotente(self):
        self._resetear()
        st2 = self._resetear()
        self.assertEqual(st2["cleared"], {}, "la segunda corrida no tiene nada que borrar")

    def test_invalida_el_cache_del_chat_de_ia(self):
        """Sin esto el chat sigue contestando sobre la cartera RECIÉN BORRADA hasta
        60s — el fantasma exacto que este botón existe para matar."""
        main._CHAT_VAL_CACHE[self.UID] = (9e18, ["cartera vieja"], {"total": 999})
        self._resetear()
        self.assertNotIn(self.UID, main._CHAT_VAL_CACHE)

    # ── 3) el preview mide y no escribe ───────────────────────────────────
    def test_preview_no_escribe_nada(self):
        antes = {t: self._n(t) for t in main._reset_admin_tablas()}
        antes["config"] = self._n("config")
        pv = main.admin_reset_user_preview(email=self.EMAIL, uid=self.ADMIN)
        self.assertTrue(pv["ok"])
        for t, n in antes.items():
            self.assertEqual(self._n(t), n, f"el preview tocó {t}")

    def test_preview_cuenta_lo_mismo_que_despues_borra(self):
        """El número que mirás para decidir tiene que ser el número real. Si el
        preview mintiera, la decisión de 'corrolo ahora o a la madrugada' sería
        una corazonada con cara de dato."""
        pv = main.admin_reset_user_preview(email=self.EMAIL, uid=self.ADMIN)
        st = self._resetear()
        borradas = sum(v for k, v in st["cleared"].items() if k != "users.investor_profile")
        self.assertEqual(pv["total_filas"], borradas)
        self.assertEqual(pv["tablas_ausentes"], [], "no puede haber tablas sin contar")

    def test_preview_avisa_si_tiene_suscripcion_activa(self):
        avisos = " ".join(main.admin_reset_user_preview(email=self.EMAIL, uid=self.ADMIN)["avisos"])
        self.assertIn("suscripción ACTIVA", avisos)

    # ── 4) no resetear a la persona equivocada ────────────────────────────
    def test_confirmacion_que_no_coincide_no_borra_nada(self):
        with self.assertRaises(main.HTTPException) as cm:
            main.admin_reset_user(
                main.AdminResetUserIn(email=self.EMAIL, confirmar_email="otro@t.com"),
                uid=self.ADMIN)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(self._n("positions"), 1, "no se borró nada")

    def test_email_inexistente_da_404(self):
        with self.assertRaises(main.HTTPException) as cm:
            main.admin_reset_user(
                main.AdminResetUserIn(email="nadie@t.com", confirmar_email="nadie@t.com"),
                uid=self.ADMIN)
        self.assertEqual(cm.exception.status_code, 404)

    def test_no_hereda_el_contexto_de_cliente_del_plan_asesor(self):
        """El hallazgo más grave posible es resetear la cuenta EQUIVOCADA. Si estos
        endpoints colgaran de `get_effective_user`, un asesor con un cliente abierto
        dispararía el borrado sobre el cliente. Cuelgan de `get_admin_user`, que a su
        vez cuelga de `get_current_user`: inmunes por construcción. Se deja clavado."""
        import inspect
        for fn in (main.admin_reset_user, main.admin_reset_user_preview,
                   main.admin_reset_user_status):
            dep = inspect.signature(fn).parameters["uid"].default
            self.assertIs(dep.dependency, main.get_admin_user,
                          f"{fn.__name__} tiene que depender de get_admin_user")
        self.assertIs(
            inspect.signature(main.get_admin_user).parameters["uid"].default.dependency,
            main.get_current_user,
            "get_admin_user NO puede pasar por get_effective_user")


class ResetAdminHttpTest(unittest.TestCase):
    """Los tests de arriba llaman a las funciones. Estos entran por HTTP, que es
    como entra producción: verifican el ruteo, el gate de admin y el ida y vuelta
    completo (pedir → seguir el progreso → terminar). Un endpoint puede estar
    perfecto por dentro y quedar abierto a cualquiera por fuera."""

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.tag = f"http{int(time.time() * 1000) % 10 ** 8}"
        conn = main.get_db()
        cur = conn.execute("INSERT INTO users (email,password_hash,approved,is_admin) "
                           "VALUES (?,'x',1,1)", (f"adm-{self.tag}@rendi.test",))
        self.admin = cur.lastrowid
        cur = conn.execute("INSERT INTO users (email,password_hash,approved) VALUES (?,'x',1)",
                           (f"pl-{self.tag}@rendi.test",))
        self.plain = cur.lastrowid
        self.email = f"vic-{self.tag}@rendi.test"
        cur = conn.execute("INSERT INTO users (email,password_hash,approved,tier) "
                           "VALUES (?,'x',1,'pro')", (self.email,))
        self.victima = cur.lastrowid
        conn.execute("INSERT INTO positions (user_id,broker,asset,quantity,invested,is_cash) "
                     "VALUES (?,'Cocos','MSFT',10,1000,0)", (self.victima,))
        conn.execute("INSERT INTO watchlist (user_id,symbol) VALUES (?,'AAPL')", (self.victima,))
        conn.commit()
        conn.close()
        self.h_admin = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self.h_plain = {"Authorization": f"Bearer {main.create_token(self.plain)}"}

    def tearDown(self):
        conn = main.get_db()
        for t in ("positions", "watchlist", "config"):
            conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.victima,))
        for u in (self.admin, self.plain, self.victima):
            conn.execute("DELETE FROM users WHERE id=?", (u,))
        conn.commit()
        conn.close()
        main._reset_progress.pop(self.victima, None)

    def test_un_usuario_comun_no_puede_ni_mirar_ni_borrar(self):
        r = self.client.get("/api/admin/reset-user/preview",
                            params={"email": self.email}, headers=self.h_plain)
        self.assertEqual(r.status_code, 403)
        r = self.client.get("/api/admin/reset-user/status",
                            params={"user_id": self.victima}, headers=self.h_plain)
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/admin/reset-user", headers=self.h_plain,
                             json={"email": self.email, "confirmar_email": self.email})
        self.assertEqual(r.status_code, 403)
        conn = main.get_db()
        try:
            n = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=?",
                             (self.victima,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 1, "un no-admin no borró nada")

    def test_sin_sesion_tampoco(self):
        r = self.client.get("/api/admin/reset-user/preview", params={"email": self.email})
        self.assertIn(r.status_code, (401, 403))

    def test_ida_y_vuelta_completo_por_http(self):
        pv = self.client.get("/api/admin/reset-user/preview",
                             params={"email": self.email}, headers=self.h_admin)
        self.assertEqual(pv.status_code, 200, pv.text)
        self.assertEqual(pv.json()["total_filas"], 2)   # 1 posición + 1 seguido

        r = self.client.post("/api/admin/reset-user", headers=self.h_admin,
                             json={"email": self.email, "confirmar_email": self.email})
        self.assertEqual(r.status_code, 200, r.text)
        for _ in range(200):
            st = self.client.get("/api/admin/reset-user/status",
                                 params={"user_id": self.victima}, headers=self.h_admin).json()
            if st["estado"] != "corriendo":
                break
            time.sleep(0.05)
        self.assertEqual(st["estado"], "listo", st.get("error"))
        conn = main.get_db()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=?",
                                          (self.victima,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=?",
                                          (self.victima,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT tier FROM users WHERE id=?",
                                          (self.victima,)).fetchone()[0], "pro",
                             "el plan pago sigue en pie")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
