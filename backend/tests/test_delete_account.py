"""Cierre de cuenta self-service (DELETE /api/me → delete_my_account).

Verifica que borra TODOS los datos del usuario (tablas con user_id + hijas de import
por batch_id + la fila users) y que NO toca a otros usuarios (scope estricto)."""
import os, sys, tempfile, unittest
from unittest import mock

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
        # ⚠️ `users` va ÚLTIMO: con `PRAGMA foreign_keys=ON` borrarlo primero falla
        # por FK, el `except` se lo come y los usuarios del test anterior quedan
        # vivos. Con un solo test del archivo no se notaba; al agregar el segundo
        # sí (emails duplicados → se borra uno y el otro sigue recibiendo mails).
        for t in ("brokers", "positions", "operations", "monthly_entries",
                  "config", "watchlist", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "subscriptions", "users"):
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


class CancelaElCobroAlBorrarTest(unittest.TestCase):
    """El panel de admin también tiene que cortar el cobro externo.

    No lo hacía: borraba al usuario de Rendi y dejaba la suscripción viva en
    Rebill. A esa persona le seguían llegando los cobros —y los avisos de
    cobro— de una cuenta que ya no existe. El cierre self-service sí lo hacía:
    es el mismo arreglo aplicado a un solo camino de dos."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("brokers", "subscriptions", "users"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.admin = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,is_admin) "
            "VALUES ('adm@t','x',1,1)").lastrowid
        self.pagador = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES ('paga@t','x',1)").lastrowid
        self.conn.execute(
            "INSERT INTO subscriptions (user_id,external_reference,mp_subscription_id,"
            "status,period,amount_ars) VALUES (?,?,?,?,?,?)",
            (self.pagador, "ref1", "sub_ABC", "authorized", "monthly", 12100))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_admin_borrar_cancela_la_suscripcion(self):
        from billing import rebill
        with mock.patch.object(rebill, "cancel_subscription") as cancel:
            main.admin_delete_user(self.pagador, uid=self.admin)
        cancel.assert_called_once_with("sub_ABC")

    def test_si_la_cancelacion_falla_no_se_pierde_en_silencio(self):
        """La fila de `subscriptions` se va con la cuenta: si la cancelación
        falla y nadie avisa, no queda de dónde reintentar ni a quién reclamarle,
        y el cobro sigue saliendo para siempre."""
        from billing import rebill
        from billing import emails
        with mock.patch.object(rebill, "cancel_subscription",
                               side_effect=RuntimeError("Rebill 503")), \
             mock.patch.object(emails, "send_orphan_subscription_admin") as aviso:
            res = main.admin_delete_user(self.pagador, uid=self.admin)
        self.assertFalse(res["deleted"]["suscripcion_cancelada"])
        self.assertEqual(aviso.call_args.kwargs["sub_id"], "sub_ABC")
        # La cuenta SÍ se borró: el derecho a irse no depende de que Rebill responda.
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM users WHERE id=?", (self.pagador,)).fetchone()["c"], 0)


class BaseTrabadaTest(unittest.TestCase):
    """`database is locked` no es un error del borrado: es que otra escritura
    tiene agarrada la base (SQLite deja escribir de a uno). Antes salía como un
    500 con la frase cruda de SQLite y sin reintentar ni una vez."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("brokers", "subscriptions", "users"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.admin = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,is_admin) "
            "VALUES ('adm2@t','x',1,1)").lastrowid
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES ('x@t','x',1)").lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_reintenta_y_si_no_afloja_contesta_503_legible(self):
        import sqlite3
        trabada = sqlite3.OperationalError("database is locked")
        with mock.patch.object(main, "_borrar_usuario_y_datos", side_effect=trabada) as wipe:
            with self.assertRaises(main.HTTPException) as caja:
                main.admin_delete_user(self.uid, uid=self.admin)
        self.assertEqual(caja.exception.status_code, 503)
        self.assertIn("ocupada", caja.exception.detail.lower())
        self.assertIn("no se borró nada", caja.exception.detail.lower())
        self.assertEqual(wipe.call_count, 3, "tiene que reintentar, no rendirse al primer lock")

    def test_un_lock_transitorio_no_se_le_muestra_al_usuario(self):
        """El caso real: el import/cron que tenía el lock lo suelta y el borrado entra."""
        import sqlite3
        real = main._borrar_usuario_y_datos
        llamadas = {"n": 0}

        def _primera_vez_trabada(conn, uid):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return real(conn, uid)

        with mock.patch.object(main, "_borrar_usuario_y_datos", _primera_vez_trabada):
            res = main.admin_delete_user(self.uid, uid=self.admin)
        self.assertTrue(res["ok"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM users WHERE id=?", (self.uid,)).fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
