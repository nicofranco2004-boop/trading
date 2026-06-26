"""Tests del cascade de rename de brokers (PUT /api/brokers/{bid}).

Bug original (user real): un broker "Cocos Capital" con posiciones se renombraba
desde el UI y TODAS las posiciones desaparecían — porque las tablas de data
linkean al broker por NOMBRE (string), no por broker_id, y el endpoint viejo solo
hacía UPDATE brokers SET name=... sin cascadear el cambio. Estos tests cubren:
cascade a las 6 tablas name-keyed, rename del sibling USD, colisión → 409, no-op
de moneda, round-trip y 404/IDOR.

Idioma de test: unittest.TestCase + TestClient(main.app), _new_user(conn) helper,
main.create_token(uid), header Authorization Bearer, seeding raw-SQL con main.get_db().
"""
import unittest
import uuid

import main


def _new_user(conn) -> int:
    email = f"brk-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?, 'x', 1, 0)",
        (email,),
    )
    return cur.lastrowid


def _insert_broker(conn, uid, name, currency="ARS", parent_id=None):
    cur = conn.execute(
        "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
        (uid, name, currency, parent_id),
    )
    return cur.lastrowid


def _count(conn, table, uid, broker):
    # import_normalized_tx no tiene user_id: se scopea por batch_id → import_batches.
    if table == "import_normalized_tx":
        return conn.execute(
            """SELECT COUNT(*) FROM import_normalized_tx
               WHERE broker=?
                 AND batch_id IN (SELECT id FROM import_batches WHERE user_id=?)""",
            (broker, uid),
        ).fetchone()[0]
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE user_id=? AND broker=?", (uid, broker)
    ).fetchone()[0]


class BrokerRenameTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = _new_user(conn)
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _put(self, bid, body):
        return self.client.put(f"/api/brokers/{bid}", json=body, headers=self._auth())

    # ── Seeders de una fila en cada tabla name-keyed para un broker dado ──────
    def _seed_all_tables(self, conn, broker):
        uid = self.uid
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, commissions, entry_date)
               VALUES (?, 'NVDA', ?, 0, 10, 1000.0, 0, '2025-08-12')""",
            (uid, broker),
        )
        conn.execute(
            """INSERT INTO operations (user_id, date, entry_date, asset, broker,
                                       op_type, quantity, entry_price, exit_price,
                                       pnl_usd, pnl_pct, commissions)
               VALUES (?, '2025-08-20', '2025-08-01', 'NVDA', ?,
                       'LONG', 10, 120.0, 145.0, 250.0, 20.83, 5.0)""",
            (uid, broker),
        )
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2026, 2, ?, 1000, 1100, 100, 0, 0)""",
            (uid, broker),
        )
        conn.execute(
            """INSERT INTO import_batches (id, user_id, broker, parser_format,
                                           file_hash, status)
               VALUES (?, ?, ?, 'cocos', 'hash123', 'confirmed')""",
            (uuid.uuid4().hex, uid, broker),
        )
        # import_normalized_tx necesita un batch_id + raw_row_id (FKs). Creamos un
        # batch propio y una raw_row para satisfacer las referencias.
        batch_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO import_batches (id, user_id, broker, parser_format,
                                           file_hash, status)
               VALUES (?, ?, ?, 'cocos', 'hashnorm', 'confirmed')""",
            (batch_id, uid, broker),
        )
        raw_cur = conn.execute(
            """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status)
               VALUES (?, 0, '{}', 'valid')""",
            (batch_id,),
        )
        raw_id = raw_cur.lastrowid
        conn.execute(
            """INSERT INTO import_normalized_tx (batch_id, raw_row_id, date, broker,
                                                 operation_type, asset_symbol)
               VALUES (?, ?, '2025-08-20', ?, 'BUY', 'NVDA')""",
            (batch_id, raw_id, broker),
        )
        conn.execute(
            """INSERT INTO bond_cashflow_skips (user_id, broker, asset, date, created_at)
               VALUES (?, ?, 'AL30', '2025-09-09', datetime('now'))""",
            (uid, broker),
        )

    ALL_TABLES = (
        "positions", "operations", "monthly_entries",
        "import_batches", "import_normalized_tx", "bond_cashflow_skips",
    )

    def test_rename_cascades_all_name_keyed_tables(self):
        conn = main.get_db()
        bid = _insert_broker(conn, self.uid, "Cocos Capital", "ARS")
        self._seed_all_tables(conn, "Cocos Capital")
        # counts originales por tabla (import_batches tiene 2 filas por el seed)
        orig = {t: _count(conn, t, self.uid, "Cocos Capital") for t in self.ALL_TABLES}
        conn.commit()
        conn.close()

        r = self._put(bid, {"name": "Cocos", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)

        conn = main.get_db()
        for t in self.ALL_TABLES:
            self.assertEqual(_count(conn, t, self.uid, "Cocos Capital"), 0,
                             f"{t} aún tiene filas bajo el nombre viejo")
            self.assertEqual(_count(conn, t, self.uid, "Cocos"), orig[t],
                             f"{t} no migró todas las filas al nombre nuevo")
        conn.close()

    def test_rename_parent_also_renames_usd_sibling_and_its_data(self):
        conn = main.get_db()
        parent_id = _insert_broker(conn, self.uid, "IOL", "ARS")
        sib_id = _insert_broker(conn, self.uid, "IOL · USD", "USDT", parent_id=parent_id)
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, commissions, entry_date)
               VALUES (?, 'GGAL', 'IOL', 0, 5, 500.0, 0, '2025-08-12')""",
            (self.uid,),
        )
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, commissions, entry_date)
               VALUES (?, 'AAPL', 'IOL · USD', 0, 2, 300.0, 0, '2025-08-12')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        r = self._put(parent_id, {"name": "IOL Nuevo", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)

        conn = main.get_db()
        sib_name = conn.execute(
            "SELECT name FROM brokers WHERE id=?", (sib_id,)
        ).fetchone()["name"]
        self.assertEqual(sib_name, "IOL Nuevo · USD")
        self.assertEqual(_count(conn, "positions", self.uid, "IOL"), 0)
        self.assertEqual(_count(conn, "positions", self.uid, "IOL · USD"), 0)
        self.assertEqual(_count(conn, "positions", self.uid, "IOL Nuevo"), 1)
        self.assertEqual(_count(conn, "positions", self.uid, "IOL Nuevo · USD"), 1)
        conn.close()

    def test_rename_into_existing_name_returns_409_not_500(self):
        conn = main.get_db()
        a_id = _insert_broker(conn, self.uid, "A", "ARS")
        b_id = _insert_broker(conn, self.uid, "B", "ARS")
        conn.commit()
        conn.close()

        r = self._put(b_id, {"name": "A", "currency": "ARS"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "broker_name_taken")

        conn = main.get_db()
        b_name = conn.execute("SELECT name FROM brokers WHERE id=?", (b_id,)).fetchone()["name"]
        a_name = conn.execute("SELECT name FROM brokers WHERE id=?", (a_id,)).fetchone()["name"]
        self.assertEqual(b_name, "B")  # no se renombró
        self.assertEqual(a_name, "A")  # no hubo merge
        conn.close()

    def test_rename_sibling_directly_is_rejected_400(self):
        conn = main.get_db()
        parent_id = _insert_broker(conn, self.uid, "IOL", "ARS")
        sib_id = _insert_broker(conn, self.uid, "IOL · USD", "USDT", parent_id=parent_id)
        conn.commit()
        conn.close()

        r = self._put(sib_id, {"name": "Hacked", "currency": "USDT"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"]["code"], "sibling_rename_forbidden")

        conn = main.get_db()
        sib_name = conn.execute("SELECT name FROM brokers WHERE id=?", (sib_id,)).fetchone()["name"]
        self.assertEqual(sib_name, "IOL · USD")
        conn.close()

    def test_currency_only_change_is_noop_for_names(self):
        conn = main.get_db()
        bid = _insert_broker(conn, self.uid, "Schwab", "USD")
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, commissions, entry_date)
               VALUES (?, 'NVDA', 'Schwab', 0, 10, 1000.0, 0, '2025-08-12')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        r = self._put(bid, {"name": "Schwab", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)

        conn = main.get_db()
        ccy = conn.execute("SELECT currency FROM brokers WHERE id=?", (bid,)).fetchone()["currency"]
        self.assertEqual(ccy, "ARS")
        self.assertEqual(_count(conn, "positions", self.uid, "Schwab"), 1)
        conn.close()

    def test_rename_round_trip_preserves_data(self):
        conn = main.get_db()
        bid = _insert_broker(conn, self.uid, "Cocos Capital", "ARS")
        for tbl_broker in ("Cocos Capital",):
            conn.execute(
                """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                          invested, commissions, entry_date)
                   VALUES (?, 'NVDA', ?, 0, 10, 1000.0, 0, '2025-08-12')""",
                (self.uid, tbl_broker),
            )
            conn.execute(
                """INSERT INTO operations (user_id, date, entry_date, asset, broker,
                                           op_type, quantity, entry_price, exit_price,
                                           pnl_usd, pnl_pct, commissions)
                   VALUES (?, '2025-08-20', '2025-08-01', 'NVDA', ?,
                           'LONG', 10, 120.0, 145.0, 250.0, 20.83, 5.0)""",
                (self.uid, tbl_broker),
            )
            conn.execute(
                """INSERT INTO monthly_entries (user_id, year, month, broker,
                                                capital_inicio, capital_final,
                                                deposits, withdrawals, pnl_realized)
                   VALUES (?, 2026, 2, ?, 1000, 1100, 100, 0, 0)""",
                (self.uid, tbl_broker),
            )
        conn.commit()
        conn.close()

        tables = ("positions", "operations", "monthly_entries")

        r = self._put(bid, {"name": "Cocos", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        for t in tables:
            self.assertEqual(_count(conn, t, self.uid, "Cocos"), 1)
            self.assertEqual(_count(conn, t, self.uid, "Cocos Capital"), 0)
        conn.close()

        r = self._put(bid, {"name": "Cocos Capital", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        for t in tables:
            self.assertEqual(_count(conn, t, self.uid, "Cocos Capital"), 1)
            self.assertEqual(_count(conn, t, self.uid, "Cocos"), 0)
        conn.close()

    def test_rename_nonexistent_broker_404(self):
        r = self._put(999999, {"name": "Whatever", "currency": "ARS"})
        self.assertEqual(r.status_code, 404, r.text)

    def test_rename_to_reserved_global_returns_409_not_500(self):
        # 'global' es la clave del agregado cross-broker en monthly_entries — NO es un
        # broker real. Renombrar a 'global' chocaría con esas filas (UNIQUE) y
        # corrompería los agregados → debe rechazarse con 409 (no 500).
        conn = main.get_db()
        bid = _insert_broker(conn, self.uid, "Cocos Capital", "ARS")
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2026, 2, 'global', 1000, 1100, 100, 0, 0)""",
            (self.uid,),
        )
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2026, 2, 'Cocos Capital', 1000, 1100, 100, 0, 0)""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        r = self._put(bid, {"name": "global", "currency": "ARS"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "broker_name_reserved")

        conn = main.get_db()
        name = conn.execute("SELECT name FROM brokers WHERE id=?", (bid,)).fetchone()["name"]
        self.assertEqual(name, "Cocos Capital")  # no se renombró
        # El agregado 'global' sigue siendo 1 fila (no se fusionó ni duplicó)
        self.assertEqual(_count(conn, "monthly_entries", self.uid, "global"), 1)
        conn.close()

    def test_rename_colliding_with_orphan_row_returns_409_not_500(self):
        # Fila HUÉRFANA en monthly_entries bajo un nombre sin broker (p.ej. de un rename
        # del endpoint viejo bugueado, o de una tabla que delete_broker no limpia). El
        # guard de `brokers` no la ve, pero el cascade chocaría con
        # UNIQUE(user_id,year,month,broker) → debe ser 409 (no 500) y el rename debe
        # revertirse ENTERO (atomicidad).
        conn = main.get_db()
        bid = _insert_broker(conn, self.uid, "Cocos Capital", "ARS")
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2026, 2, 'Cocos Capital', 1000, 1100, 100, 0, 0)""",
            (self.uid,),
        )
        # huérfana bajo 'Ghost' en el MISMO período → colisiona al cascadear
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2026, 2, 'Ghost', 500, 600, 50, 0, 0)""",
            (self.uid,),
        )
        # posición del broker real → confirmamos que el rollback la deja intacta
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, commissions, entry_date)
               VALUES (?, 'NVDA', 'Cocos Capital', 0, 10, 1000.0, 0, '2025-08-12')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        r = self._put(bid, {"name": "Ghost", "currency": "ARS"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "broker_rename_conflict")

        # Atomicidad: NADA se renombró (rollback completo).
        conn = main.get_db()
        name = conn.execute("SELECT name FROM brokers WHERE id=?", (bid,)).fetchone()["name"]
        self.assertEqual(name, "Cocos Capital")
        self.assertEqual(_count(conn, "positions", self.uid, "Cocos Capital"), 1)
        self.assertEqual(_count(conn, "positions", self.uid, "Ghost"), 0)
        self.assertEqual(_count(conn, "monthly_entries", self.uid, "Cocos Capital"), 1)
        self.assertEqual(_count(conn, "monthly_entries", self.uid, "Ghost"), 1)  # huérfana intacta
        conn.close()


if __name__ == "__main__":
    unittest.main()
