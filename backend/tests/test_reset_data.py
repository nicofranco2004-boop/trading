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

    def test_borra_la_cartera(self):
        main.reset_my_data(uid=self.UID)
        for tbl in ("brokers", "positions", "operations", "snapshots"):
            self.assertEqual(self._n(tbl), 0, f"{tbl} debería quedar vacío")
        # las 3 keys de config de CARTERA se van...
        self.assertEqual(self._n("config", "AND key IN ('fx_version','tc_blue','tc_mep')"), 0)

    def test_conserva_identidad_plan_y_prefs(self):
        main.reset_my_data(uid=self.UID)
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
        out = main.reset_my_data(uid=self.UID)
        self.assertTrue(out["ok"])
        cleared = out["cleared"]
        self.assertEqual(set(cleared) & {"subscriptions", "credit_ledger",
                         "user_broker_credentials", "users", "alerts", "watchlist"}, set(),
                         "el reporte NO debe incluir ninguna tabla protegida")
        self.assertIn("positions", cleared)
        self.assertEqual(cleared["config"], 3)  # solo las 3 keys de cartera

    def test_idempotente(self):
        main.reset_my_data(uid=self.UID)
        out2 = main.reset_my_data(uid=self.UID)  # segunda vez: nada que borrar
        self.assertTrue(out2["ok"])
        self.assertEqual(out2["cleared"], {})


if __name__ == "__main__":
    unittest.main()
