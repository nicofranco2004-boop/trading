"""Migraciones de esquema de las tablas advisor_* sobre una base VIEJA.

Por qué existe esta suite: el alta grupal del asesor fallaba SIEMPRE en
producción con "table advisor_op_batch_items has no column named cost_debited",
y ningún test lo veía. La razón es que el `CREATE TABLE` de init_db ya trae las
4 columnas de undo, así que en una base NUEVA — la que usan todos los tests — la
tabla nace completa y el bug es invisible. Sólo rompe donde la tabla ya existía
con 5 columnas: producción.

La migración que las agrega estaba guardada detrás de `_table_cols()`, que tiene
una allowlist en la que esta tabla NO está → devolvía set() → el `if` era falso
→ el ALTER no corrió nunca.

Por eso estos tests hacen lo único que reproduce el caso: FABRICAN la tabla vieja
(5 columnas) y recién ahí corren init_db(). Un test que deje que init_db cree la
tabla desde cero no puede fallar nunca y no prueba nada.

Corre con: cd backend && python3 -m pytest tests/test_advisor_schema_migration.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main


# ─── Por qué esta suite es SÓLO-SQLITE, y no es una migración pendiente ──────
# Estos tests FABRICAN la tabla vieja y después esperan que `init_db()` le
# agregue columnas con ALTER. Ese mecanismo NO EXISTE en Postgres: `init_db()`
# sale en la primera línea (`if USANDO_PG: _init_db_postgres(); return`) y aplica
# `schema_pg.sql` entero — que no puede agregarle una columna a una tabla que ya
# existe. No es que la migración falle allá: es que allá no hay migraciones
# incrementales, a propósito (son la HISTORIA del schema de SQLite, y Postgres
# arranca del RESULTADO).
#
# ⚠️ NO "portar" estos tests a Postgres. Lo que probarían es otra cosa, y lo que
# de verdad importa allá ya está garantizado por otro lado: `schema_pg.sql` trae
# las 4 columnas de undo y las 3 de advisor_profile en el CREATE.
#
# Dos motivos por los que además ni siquiera arrancan: el setUp usa
# `AUTOINCREMENT` (sintaxis exclusiva de SQLite) y `PRAGMA table_info`.
_POR_QUE_SOLO_SQLITE = (
    "Sólo SQLite: prueba las migraciones incrementales de init_db(), que en "
    "Postgres no existen (se aplica schema_pg.sql, que ya trae las columnas)."
)


# Esquema EXACTO que tiene producción hoy (verificado contra el backup del
# 2026-08-16): 5 columnas, sin las 4 de undo.
_PROD_SCHEMA_5_COLS = """
    CREATE TABLE advisor_op_batch_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER NOT NULL REFERENCES advisor_op_batches(id),
        client_uid INTEGER NOT NULL,
        position_id INTEGER,
        status TEXT NOT NULL DEFAULT 'ok'
    );
"""

_UNDO_COLS = ('cost_debited', 'autodep_native', 'autodep_usd', 'autodep_ym')


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _new_user(conn):
    """Usuario real: advisor_op_batches.advisor_uid tiene FK a users(id)."""
    import uuid
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (f"schema-mig-{uuid.uuid4().hex[:8]}@rendi.test",),
    )
    return cur.lastrowid


@unittest.skipIf(getattr(main, "USANDO_PG", False), _POR_QUE_SOLO_SQLITE)
class TestBatchItemsMigration(unittest.TestCase):
    """advisor_op_batch_items: la tabla de 5 columnas de prod tiene que migrar."""

    def setUp(self):
        # Reproducimos la base VIEJA: borramos la tabla que init_db ya creó
        # completa y la recreamos como está en producción.
        conn = main.get_db()
        conn.execute("DROP TABLE IF EXISTS advisor_op_batch_items")
        conn.executescript(_PROD_SCHEMA_5_COLS)
        conn.commit()
        conn.close()

    def test_base_vieja_arranca_sin_las_columnas_de_undo(self):
        """Guard del propio test: si esto falla, el setUp dejó de reproducir prod."""
        conn = main.get_db()
        try:
            cols = _cols(conn, 'advisor_op_batch_items')
            self.assertEqual(len(cols), 5, f"el setUp debería dejar 5 columnas, dejó {cols}")
            for c in _UNDO_COLS:
                self.assertNotIn(c, cols)
        finally:
            conn.close()

    def test_init_db_agrega_las_4_columnas_de_undo(self):
        """ESTE es el test del bug: con la migración muerta, init_db no agregaba nada."""
        main.init_db()
        conn = main.get_db()
        try:
            cols = _cols(conn, 'advisor_op_batch_items')
            faltantes = [c for c in _UNDO_COLS if c not in cols]
            self.assertEqual(
                faltantes, [],
                f"init_db() no migró la tabla vieja. Faltan: {faltantes}. "
                f"Es el bug que hacía fallar el alta grupal en producción.",
            )
        finally:
            conn.close()

    def test_el_insert_del_alta_grupal_no_explota(self):
        """El síntoma real: el INSERT de 7 columnas de _advisor_group_op_apply.

        Sin la migración esto tira exactamente el error de producción:
        'table advisor_op_batch_items has no column named cost_debited'.
        """
        main.init_db()
        conn = main.get_db()
        try:
            uid = _new_user(conn)
            cur = conn.execute(
                "INSERT INTO advisor_op_batches (advisor_uid, asset, op_kind) "
                "VALUES (?,?, 'buy')", (uid, 'AL30'),
            )
            conn.execute(
                """INSERT INTO advisor_op_batch_items
                       (batch_id, client_uid, position_id, cost_debited,
                        autodep_native, autodep_usd, autodep_ym)
                   VALUES (?,?,?,?,?,?,?)""",
                (cur.lastrowid, 1, 1, 100.0, 5000.0, 4.0, '2026-08'),
            )
            conn.commit()
            row = conn.execute(
                "SELECT cost_debited, autodep_ym FROM advisor_op_batch_items"
            ).fetchone()
            self.assertEqual(row["cost_debited"], 100.0)
            self.assertEqual(row["autodep_ym"], '2026-08')
        finally:
            conn.close()

    def test_migracion_es_idempotente(self):
        """Correrla dos veces no puede tirar 'duplicate column name'."""
        main.init_db()
        main.init_db()
        conn = main.get_db()
        try:
            cols = _cols(conn, 'advisor_op_batch_items')
            for c in _UNDO_COLS:
                self.assertIn(c, cols)
        finally:
            conn.close()

    def test_no_pierde_las_filas_existentes(self):
        """ALTER ADD COLUMN no debe tocar los datos ya cargados."""
        conn = main.get_db()
        try:
            uid = _new_user(conn)
            cur = conn.execute(
                "INSERT INTO advisor_op_batches (advisor_uid, asset, op_kind) VALUES (?,?, 'buy')",
                (uid, 'GD30'),
            )
            conn.execute(
                "INSERT INTO advisor_op_batch_items (batch_id, client_uid, position_id, status) "
                "VALUES (?,?,?,?)", (cur.lastrowid, 42, 99, 'ok'),
            )
            conn.commit()
        finally:
            conn.close()

        main.init_db()

        conn = main.get_db()
        try:
            row = conn.execute(
                "SELECT client_uid, position_id, status, cost_debited "
                "FROM advisor_op_batch_items WHERE client_uid=42"
            ).fetchone()
            self.assertIsNotNone(row, "la migración perdió la fila preexistente")
            self.assertEqual(row["position_id"], 99)
            self.assertEqual(row["status"], 'ok')
            self.assertIsNone(row["cost_debited"], "la columna nueva debe quedar NULL")
        finally:
            conn.close()


@unittest.skipIf(getattr(main, "USANDO_PG", False), _POR_QUE_SOLO_SQLITE)
class TestAdvisorProfileMigration(unittest.TestCase):
    """advisor_profile: mismo bug latente (en prod no muerde porque la columna
    llegó por otro camino, pero la migración estaba igual de muerta)."""

    def setUp(self):
        conn = main.get_db()
        conn.execute("DROP TABLE IF EXISTS advisor_profile")
        conn.executescript("""
            CREATE TABLE advisor_profile (
                advisor_uid INTEGER PRIMARY KEY,
                display_name TEXT,
                cnv_matricula TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        conn.close()

    def test_init_db_agrega_logo_data_y_prefs_del_brief(self):
        main.init_db()
        conn = main.get_db()
        try:
            cols = _cols(conn, 'advisor_profile')
            for c in ('logo_data', 'brief_open', 'brief_close'):
                self.assertIn(c, cols, f"init_db() no migró advisor_profile: falta {c}")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
