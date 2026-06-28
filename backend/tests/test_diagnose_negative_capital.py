"""Diagnóstico READ-ONLY de capital negativo gigante (GET /api/admin/diagnose-negative-capital).

Reproduce el bug raíz: un broker AR marcado brokers.currency='USD' con tx/ops en ARS →
pnl_realized peso-escala → capital_final negativo de millones que el carryforward arrastra.
Verifica que el diagnóstico (a) detecta la cuenta, (b) flaggea el broker como suspect,
(c) localiza el mes del salto + el término culpable, (d) confirma H1. Y que una cuenta
sana NO aparece. NO escribe nada (read-only)."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False); TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main


class DiagnoseNegCapTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("monthly_entries", "operations", "brokers", "users",
                  "import_normalized_tx", "import_batches"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("diag@test", "x")).lastrowid
        # Broker AR marcado USD = el bug.
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "USD"))
        # batch confirmado + tx en ARS (la contradicción AR-marcado-USD).
        bid = "b-diag"
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,?)", (bid, self.uid, "Cocos", "generic", "h", "confirmed"))
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) VALUES (?,?,?,?)",
            (bid, 0, "{}", "valid")).lastrowid
        for _ in range(3):
            self.conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,operation_type,asset_symbol,gross_amount,currency) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (bid, rr, "2024-06-15", "Cocos", "SELL", "AL30", 24000000, "ARS"))
        # Operación rota: SELL con pnl_usd peso-escala (no dividido por el MEP), ARS, fx NULL.
        self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,quantity,exit_price,pnl_usd,currency,fx_to_usd) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.uid, "2024-06-15", "Cocos", "AL30", "SELL", 100, 240000, -24000000, "ARS", None))
        # Cadena mensual: salta a -24M en 2024-06 por pnl_realized, se arrastra a 2024-07.
        for (y, m, ci, pnl, cf) in [(2024, 5, 0, 0, 5000),
                                    (2024, 6, 5000, -24000000, -23995000),
                                    (2024, 7, -23995000, 0, -23995000)]:
            for broker in ("Cocos", "global"):
                self.conn.execute(
                    "INSERT INTO monthly_entries (user_id,broker,year,month,capital_inicio,deposits,"
                    "withdrawals,pnl_realized,pnl_unrealized,capital_final) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (self.uid, broker, y, m, ci, 0, 0, pnl, 0, cf))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_detecta_y_confirma_h1(self):
        res = main.admin_diagnose_negative_capital(min_capital=-50000.0, limit_accounts=80, uid=self.uid)
        self.assertTrue(res["ok"])
        self.assertEqual(res["affected_count"], 1)
        self.assertEqual(res["confirms_h1_broker_ar_usd"], 1)
        rep = res["reports"][0]
        self.assertEqual(rep["user_id"], self.uid)
        cocos = next(b for b in rep["brokers"] if b["name"] == "Cocos")
        self.assertTrue(cocos["suspect"])               # AR marcado USD con tx ARS
        self.assertEqual(cocos["currency"], "USD")
        self.assertGreaterEqual(cocos["ars_tx"], 1)
        self.assertEqual(rep["jump"]["ym"], "2024-06")  # mes del salto
        self.assertEqual(rep["jump"]["term_mas_negativo"], "pnl_realized")
        self.assertEqual(rep["culprit_broker"]["broker"], "Cocos")
        self.assertEqual(rep["culprit_broker"]["currency"], "USD")
        self.assertEqual(rep["top_op"]["asset"], "AL30")   # el SELL roto
        self.assertEqual(rep["top_op"]["currency"], "ARS")
        self.assertLess(rep["top_op"]["pnl_usd"], -1000000)
        self.assertIn("AR marcado USD", rep["summary"])

    def test_cuenta_sana_no_aparece(self):
        u2 = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)", ("ok@test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)", (u2, "IBKR", "USD"))
        for broker in ("IBKR", "global"):
            self.conn.execute(
                "INSERT INTO monthly_entries (user_id,broker,year,month,capital_inicio,deposits,"
                "withdrawals,pnl_realized,pnl_unrealized,capital_final) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (u2, broker, 2024, 6, 0, 1000, 0, 0, 0, 1000))
        self.conn.commit()
        res = main.admin_diagnose_negative_capital(min_capital=-50000.0, limit_accounts=80, uid=self.uid)
        uids = [r["user_id"] for r in res["reports"]]
        self.assertIn(self.uid, uids)
        self.assertNotIn(u2, uids)   # cuenta positiva no entra


if __name__ == "__main__":
    unittest.main()
