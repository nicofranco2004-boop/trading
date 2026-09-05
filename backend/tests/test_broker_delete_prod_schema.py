"""Borrar el broker padre contra el schema REAL de producción.

Por qué existe este archivo aparte, si `test_importer.py` ya tiene
`test_delete_parent_broker_cleans_sibling_data`:

Ese test pasa, y pasa por la razón equivocada. Corre sobre la DB que arma
`init_db()`, o sea el `CREATE TABLE` de main.py, que declara
`parent_broker_id INTEGER REFERENCES brokers(id) ON DELETE CASCADE`. Pero
ninguna base de producción se creó así: en toda base preexistente la columna
llegó por `ALTER TABLE brokers ADD COLUMN parent_broker_id INTEGER
REFERENCES brokers(id)` (main.py, migración), y SQLite **no admite acción
referencial en un ADD COLUMN** — la FK queda en NO ACTION.

O sea que el schema existe en dos formas y la suite sólo probaba la que no
tiene el bug. Con `PRAGMA foreign_keys=ON`, borrar el padre en la forma de
producción tiraba `FOREIGN KEY constraint failed`; y como el endpoint corre
todos sus DELETE dentro del mismo `with conn:`, el rollback deshacía también
el cleanup de positions/operations/monthly_entries → 500 genérico y la cuenta
quedaba INDELETEABLE.

Este archivo reconstruye `brokers` con la forma del ALTER, una sola vez por
clase, y la restaura en tearDownClass. El aislamiento por módulo del conftest
mantiene el DDL contenido en esta DB.

Postgres nunca tuvo el bug (declara el constraint aparte, que sí es válido),
así que este test es específico de SQLite.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402

# El schema tal como queda en una base migrada: la tabla SIN la columna, y la
# columna agregada después por ALTER. Reproduce la FK sin acción referencial.
_BROKERS_SIN_LA_COLUMNA = """
    CREATE TABLE brokers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        currency TEXT NOT NULL DEFAULT 'USDT',
        UNIQUE(user_id, name)
    )
"""
_ALTER = ("ALTER TABLE brokers ADD COLUMN parent_broker_id "
          "INTEGER REFERENCES brokers(id)")


def _es_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


@unittest.skipIf(_es_postgres(), "el bug es de SQLite-migrado; PG declara el "
                                 "constraint aparte y sí cascadea")
class DeleteBrokerSchemaMigradoTest(unittest.TestCase):
    """El schema de producción: FK a brokers(id) SIN ON DELETE CASCADE."""

    @classmethod
    def setUpClass(cls):
        conn = main.get_db()
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='brokers'"
        ).fetchone()
        cls._schema_original = row["sql"] if row else None

        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DROP TABLE IF EXISTS brokers")
        conn.execute(_BROKERS_SIN_LA_COLUMNA)
        conn.execute(_ALTER)
        conn.commit()

        # Sin esto el test no prueba nada: si la FK quedara con cascade,
        # pasaría igual y volveríamos a certificar el schema equivocado.
        fks = conn.execute("PRAGMA foreign_key_list(brokers)").fetchall()
        cls._on_delete = [f["on_delete"] for f in fks] or ["(sin FK)"]
        conn.close()

        assert "CASCADE" not in cls._on_delete, (
            f"El fixture no reprodujo el schema de producción: on_delete="
            f"{cls._on_delete}. Sin FK sin-cascade este test es vacuo."
        )

    @classmethod
    def tearDownClass(cls):
        if not cls._schema_original:
            return
        conn = main.get_db()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DROP TABLE IF EXISTS brokers")
        conn.execute(cls._schema_original)
        conn.commit()
        conn.close()

    def setUp(self):
        conn = main.get_db()
        conn.execute("PRAGMA foreign_keys=ON")
        for t in ("operations", "monthly_entries", "brokers", "positions"):
            conn.execute(f"DELETE FROM {t}")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"delschema-{id(self)}@rendi.test", "x"),
        )
        self.uid = cur.lastrowid

        self.padre_id = conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,'Cocos','ARS')",
            (self.uid,),
        ).lastrowid
        self.sibling_id = conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
            "VALUES (?,'Cocos · USD','USDT',?)",
            (self.uid, self.padre_id),
        ).lastrowid

        # Data en las dos patas — el cleanup las busca por NOMBRE, no por FK.
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity) "
            "VALUES (?,'Cocos','GGAL',0,100000,100)", (self.uid,))
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity) "
            "VALUES (?,'Cocos · USD','AL30',0,40,50)", (self.uid,))
        conn.execute(
            "INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd) "
            "VALUES (?,'2026-05-01','Cocos · USD','AL30','Venta',5)", (self.uid,))
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id, year, month, broker, deposits, withdrawals,
                pnl_realized, pnl_unrealized, capital_inicio, capital_final)
               VALUES (?,2026,5,'Cocos · USD',200,0,0,0,0,200)""", (self.uid,))
        conn.commit()
        conn.close()

        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_borrar_el_padre_no_tira_foreign_key_constraint_failed(self):
        """La regresión exacta: sin el DELETE explícito del hijo, este DELETE
        devolvía 500 y la cuenta quedaba imposible de borrar."""
        res = self.client.delete(
            f"/api/brokers/{self.padre_id}?force=true",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)

        conn = main.get_db()
        quedan = conn.execute(
            "SELECT name FROM brokers WHERE user_id=?", (self.uid,)
        ).fetchall()
        conn.close()
        self.assertEqual(
            [r["name"] for r in quedan], [],
            "El padre y el sibling tienen que irse los dos: sin cascade, el "
            "hijo hay que borrarlo a mano.",
        )

    def test_no_quedan_huerfanos_de_ninguna_de_las_dos_patas(self):
        """El rollback del bug deshacía también el cleanup por nombre, así que
        un 200 no alcanza: hay que ver que las 4 tablas quedaron limpias."""
        res = self.client.delete(
            f"/api/brokers/{self.padre_id}?force=true",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)

        conn = main.get_db()
        for tabla in ("positions", "operations", "monthly_entries"):
            n = conn.execute(
                f"SELECT COUNT(*) c FROM {tabla} WHERE user_id=? "
                f"AND broker IN ('Cocos','Cocos · USD')", (self.uid,),
            ).fetchone()["c"]
            self.assertEqual(n, 0, f"quedaron huérfanos en {tabla}")
        conn.close()

    def test_borrar_el_padre_con_dos_hijos(self):
        """`POST /api/brokers` acepta un parent_broker_id arbitrario, así que un
        padre puede tener más de un hijo. El lookup usaba fetchone() y dejaba
        afuera del cleanup al segundo en adelante."""
        conn = main.get_db()
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
            "VALUES (?,'Cocos · EUR','EUR',?)", (self.uid, self.padre_id))
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity) "
            "VALUES (?,'Cocos · EUR','X',0,10,1)", (self.uid,))
        conn.commit()
        conn.close()

        res = self.client.delete(
            f"/api/brokers/{self.padre_id}?force=true",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)

        conn = main.get_db()
        quedan = [r["name"] for r in conn.execute(
            "SELECT name FROM brokers WHERE user_id=?", (self.uid,)).fetchall()]
        huerfanas = conn.execute(
            "SELECT COUNT(*) c FROM positions WHERE user_id=? AND broker='Cocos · EUR'",
            (self.uid,)).fetchone()["c"]
        conn.close()
        self.assertEqual(quedan, [], f"quedaron brokers sin borrar: {quedan}")
        self.assertEqual(huerfanas, 0, "el segundo hijo dejó positions huérfanas")


if __name__ == "__main__":
    unittest.main()
