"""Cierre de cuenta self-service (DELETE /api/me → delete_my_account).

Verifica que borra TODOS los datos del usuario (tablas con user_id + hijas de import
por batch_id + la fila users) y que NO toca a otros usuarios (scope estricto)."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main


class _Resp:
    def delete_cookie(self, *a, **k): pass
    def set_cookie(self, *a, **k): pass


class DeleteAccountTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("users", "brokers", "positions", "operations", "monthly_entries",
                  "config", "watchlist", "import_batches", "import_raw_rows", "import_normalized_tx"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.victim = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES ('del@t','x',1)").lastrowid
        self.bystander = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES ('keep@t','x',1)").lastrowid
        for u in (self.victim, self.bystander):
            self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)", (u, "X", "ARS"))
            self.conn.execute("INSERT INTO positions (user_id,broker,asset) VALUES (?,?,?)", (u, "X", "AAPL"))
            self.conn.execute("INSERT INTO operations (user_id,date,broker,asset) VALUES (?,?,?,?)", (u, "2025-01-01", "X", "AAPL"))
            self.conn.execute("INSERT INTO config (user_id,key,value) VALUES (?,?,?)", (u, "k", "v"))
        # imports (hijas por batch_id) — solo del victim
        bid = f"b{self.victim}"
        self.conn.execute("INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
                          "VALUES (?,?,?,?,?,?)", (bid, self.victim, "X", "g", "h", "confirmed"))
        rr = self.conn.execute("INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                               "VALUES (?,?,?,?)", (bid, 0, "{}", "valid")).lastrowid
        self.conn.execute("INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,operation_type) "
                          "VALUES (?,?,?,?,?)", (bid, rr, "2025-01-01", "X", "BUY"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _count(self, table, uid):
        return self.conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE user_id=?", (uid,)).fetchone()["c"]

    def test_borra_todo_del_usuario_y_no_toca_otros(self):
        res = main.delete_my_account(_Resp(), uid=self.victim)
        self.assertTrue(res["ok"])
        # todo lo del victim borrado
        for t in ("brokers", "positions", "operations", "config"):
            self.assertEqual(self._count(t, self.victim), 0, f"{t} del victim no se borró")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM users WHERE id=?", (self.victim,)).fetchone()["c"], 0)
        # hijas de import (por batch_id) borradas
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM import_normalized_tx WHERE batch_id=?",
                                           (f"b{self.victim}",)).fetchone()["c"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM import_batches WHERE user_id=?",
                                           (self.victim,)).fetchone()["c"], 0)
        # el bystander INTACTO
        for t in ("brokers", "positions", "operations", "config"):
            self.assertEqual(self._count(t, self.bystander), 1, f"{t} del bystander se tocó (BUG de scope)")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM users WHERE id=?", (self.bystander,)).fetchone()["c"], 1)


if __name__ == "__main__":
    unittest.main()
