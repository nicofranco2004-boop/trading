"""'Empezar de cero' (POST /api/me/reset-data): borra la CARTERA pero conserva la
identidad, el plan pago, las credenciales de brokers y las prefs.

Contexto: borrar un broker y re-importar NO resetea del todo (varios overlays
sobreviven al re-import a propósito). La única salida limpia era borrar la cuenta
y recrearla —perdiendo login y plan—. Este endpoint da el "como la primera vez"
sin ese costo. La garantía crítica: NO puede tocar billing/identidad (un allowlist
mal armado le resetearía el plan a alguien que pagó).

Corre con: cd backend && python3 -m pytest tests/test_reset_data.py
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


class ResetDataTest(unittest.TestCase):
    _seq = 770

    def setUp(self):
        # UID único por test: la DB temp se comparte entre tests del módulo; con
        # uno fijo el 2º setUp choca con el PK del users ya insertado.
        ResetDataTest._seq += 1
        self.UID = ResetDataTest._seq
        self.conn = main.get_db()
        c = self.conn
        # Identidad + plan PAGO (debe sobrevivir).
        c.execute("INSERT INTO users (id,email,password_hash,approved,tier,credit_active_until,credit_anchor_plan) "
                  "VALUES (?,?,?,1,'pro','2026-12-01','pro')", (self.UID, f"u{self.UID}@t.com", "HASH"))
        c.execute("INSERT INTO subscriptions (user_id,external_reference,period,status,amount_ars,mp_subscription_id) "
                  "VALUES (?,?,'monthly','authorized',9999,'MP-1')", (self.UID, f"rendi-{self.UID}-monthly"))
        c.execute("INSERT INTO credit_ledger (user_id,kind,amount_usd,days_delta) VALUES (?,'comp',0,30)", (self.UID,))
        c.execute("INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (?,'wallbit','ENC')", (self.UID,))
        c.execute("INSERT INTO alerts (user_id,kind) VALUES (?,'price_target')", (self.UID,))
        c.execute("INSERT INTO watchlist (user_id,symbol) VALUES (?,'AAPL')", (self.UID,))
        c.execute("INSERT INTO config (user_id,key,value) VALUES (?,'onboarding','done'),(?,'welcome_email_sent_at','x')",
                  (self.UID, self.UID))
        # Cartera + config de cartera (debe borrarse).
        c.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,'Cocos','ARS')", (self.UID,))
        c.execute("INSERT INTO positions (user_id,broker,asset,quantity,invested,is_cash) VALUES (?,'Cocos','MSFT',10,1000,0)", (self.UID,))
        c.execute("INSERT INTO operations (user_id,broker,asset,op_type,quantity,date) VALUES (?,'Cocos','MSFT','Compra',10,'2026-02-06')", (self.UID,))
        c.execute("INSERT INTO snapshots (user_id,date,total_value,total_invested,net_deposited) VALUES (?,'2026-08-01',5000,4000,4000)", (self.UID,))
        c.execute("INSERT INTO config (user_id,key,value) VALUES (?,'fx_version','v2'),(?,'tc_blue','1500'),(?,'tc_mep','1520')",
                  (self.UID, self.UID, self.UID))
        self.conn.commit()

    def tearDown(self):
        for t in ("users", "subscriptions", "credit_ledger", "user_broker_credentials",
                  "alerts", "watchlist", "config", "brokers", "positions", "operations", "snapshots"):
            try:
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=? OR id=?", (self.UID, self.UID))
            except Exception:
                try:
                    self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.UID,))
                except Exception:
                    pass
        self.conn.commit()
        self.conn.close()

    def _n(self, tbl, extra=""):
        c = main.get_db()
        try:
            return c.execute(f"SELECT COUNT(*) FROM {tbl} WHERE user_id=? {extra}", (self.UID,)).fetchone()[0]
        finally:
            c.close()

    def _resetear(self):
        """Dispara el reset y ESPERA a que termine, devolviendo el estado final.

        El endpoint dejó de ser síncrono: borrar hasta un millón de filas en una
        sola transacción tenía el lock de escritura tomado minutos y dejaba a
        toda la app sin poder guardar (incidente del 13/08). Ahora arranca un
        thread que borra por tandas y devuelve al instante; `cleared` —lo que
        estos tests verifican— pasó a viajar en GET /api/me/reset-data/status.

        Sin este wait los tests serían una carrera contra el thread.
        """
        # El endpoint está PAUSADO en prod (503) porque el reset desbordaba la cola de
        # escritura de SQLite y el "database is locked" le salía a TODOS los usuarios,
        # no al que reseteaba. La MAQUINARIA sigue siendo correcta y se sigue testeando:
        # abrimos la palanca acá para no perder la cobertura cuando se reactive.
        # El bloqueo en sí lo cubre ResetDataPausadoTest.
        os.environ["RENDI_RESET_DATA_ENABLED"] = "1"
        try:
            out = main.reset_my_data(uid=self.UID)
        finally:
            os.environ.pop("RENDI_RESET_DATA_ENABLED", None)
        self.assertTrue(out["ok"])
        for _ in range(200):                      # 200 × 50ms = 10s de techo
            st = main.reset_my_data_status(uid=self.UID)
            if st["estado"] != "corriendo":
                self.assertEqual(st["estado"], "listo", st.get("error"))
                return st
            time.sleep(0.05)
        self.fail("el reset no terminó en 10s")

    def test_borra_la_cartera(self):
        self._resetear()
        for tbl in ("brokers", "positions", "operations", "snapshots"):
            self.assertEqual(self._n(tbl), 0, f"{tbl} debería quedar vacío")
        # las 3 keys de config de CARTERA se van...
        self.assertEqual(self._n("config", "AND key IN ('fx_version','tc_blue','tc_mep')"), 0)

    def test_conserva_identidad_plan_y_prefs(self):
        self._resetear()
        # el usuario sigue, con su plan
        c = main.get_db()
        tier = c.execute("SELECT tier FROM users WHERE id=?", (self.UID,)).fetchone()
        c.close()
        self.assertIsNotNone(tier, "el usuario NO debe borrarse")
        self.assertEqual(tier[0], "pro")
        # billing / credenciales / prefs intactos
        self.assertEqual(self._n("subscriptions"), 1, "la suscripción PAGA no se toca")
        self.assertEqual(self._n("credit_ledger"), 1)
        self.assertEqual(self._n("user_broker_credentials"), 1, "las API keys de brokers no se tocan")
        self.assertEqual(self._n("alerts"), 1)
        self.assertEqual(self._n("watchlist"), 1)
        # ...pero las prefs de UX en config SÍ sobreviven (onboarding, welcome)
        self.assertEqual(self._n("config", "AND key IN ('onboarding','welcome_email_sent_at')"), 2)

    def test_reporta_lo_que_borro(self):
        cleared = self._resetear()["cleared"]
        self.assertEqual(set(cleared) & {"subscriptions", "credit_ledger",
                         "user_broker_credentials", "users", "alerts", "watchlist"}, set(),
                         "el reporte NO debe incluir ninguna tabla protegida")
        self.assertIn("positions", cleared)
        self.assertEqual(cleared["config"], 3)  # solo las 3 keys de cartera

    def test_idempotente(self):
        self._resetear()
        st2 = self._resetear()   # segunda vez: nada que borrar
        self.assertEqual(st2["cleared"], {})


    def test_invalida_el_cache_del_chat_de_ia(self):
        """AUDIT: sin esto el chat de IA sigue contestando con la cartera RECIÉN
        BORRADA hasta 60s (_CHAT_VAL_CACHE, TTL 60) — justo el síntoma de datos
        fantasma que este botón existe para eliminar. Las demás mutaciones ya
        llamaban a _ai_cache_invalidate; el reset se lo había olvidado."""
        main._CHAT_VAL_CACHE[self.UID] = (9e18, ["cartera vieja"], {"total": 999})
        self._resetear()
        self.assertNotIn(self.UID, main._CHAT_VAL_CACHE,
                         "el cache de valuación del chat tiene que quedar invalidado")

    def test_allowlist_solo_tablas_con_user_id(self):
        """AUDIT: `asset_last_price` y `financial_events` estaban en el allowlist y
        son caches GLOBALES (keyed por symbol/ticker, sin user_id) → el DELETE
        tiraba OperationalError y se salteaba en silencio. Peor: si mañana ganaran
        una columna user_id, el reset empezaría a borrarlas de verdad. Este test
        falla si alguien vuelve a meter una tabla sin user_id."""
        conn = main.get_db()
        try:
            for t in main._RESET_PORTFOLIO_TABLES:
                cols = [c["name"] for c in conn.execute(f"PRAGMA table_info({t})")]
                self.assertTrue(cols, f"{t} no existe como tabla")
                self.assertIn("user_id", cols,
                              f"{t} no tiene user_id — es global, no va en el allowlist")
        finally:
            conn.close()

    def test_no_toca_billing_aunque_agreguen_tablas(self):
        """AUDIT: el allowlist es explícito justamente para que una tabla de billing
        futura no se borre sola. Se fija la invariante: ninguna tabla cuyo nombre
        huela a billing/identidad puede estar en la lista."""
        prohibidas = {"users", "subscriptions", "credit_ledger", "billing_events",
                      "plan_events", "user_broker_credentials", "login_history",
                      "password_reset_tokens", "email_verification_codes",
                      "push_subscriptions", "ai_usage_daily", "ai_tool_usage"}
        self.assertEqual(set(main._RESET_PORTFOLIO_TABLES) & prohibidas, set())


class ResetDataContextTest(unittest.TestCase):
    """AUDIT — el hallazgo más grave posible: que el reset corra sobre la cuenta
    EQUIVOCADA. `get_effective_user` resuelve el contexto de cliente del Plan
    Asesor, así que si `/api/me/reset-data` NO estuviera exento, un asesor con un
    cliente abierto le borraría la cartera AL CLIENTE al tocar su propio botón.
    Hoy está exento (el prefijo '/api/me' matchea por límite de segmento), pero el
    propio código avisa que la lista es FAIL-OPEN: todo endpoint nuevo fuera de
    esos prefijos hereda el contexto. Este test lo deja clavado."""

    def test_el_endpoint_esta_exento_del_contexto_de_cliente(self):
        path = "/api/me/reset-data"
        exento = any(path == p or path.startswith(p + "/")
                     for p in main.CLIENT_CTX_EXEMPT_PREFIXES)
        self.assertTrue(exento,
                        "/api/me/reset-data DEBE estar exento del contexto de cliente: "
                        "si no, un asesor reseteando SUS datos borra los del cliente abierto")


if __name__ == "__main__":
    unittest.main()


class ResetDataPausadoTest(unittest.TestCase):
    """El botón está pausado a propósito: sin la palanca, el endpoint tiene que
    RECHAZAR. Si alguien lo reactiva sin querer, este test lo caza."""

    def test_sin_la_palanca_devuelve_503(self):
        os.environ.pop("RENDI_RESET_DATA_ENABLED", None)
        with self.assertRaises(main.HTTPException) as cm:
            main.reset_my_data(uid=1)
        self.assertEqual(cm.exception.status_code, 503)
        self.assertIn("pausado", cm.exception.detail.lower())
