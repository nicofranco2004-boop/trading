"""La conexión abre la transacción al ESCRIBIR, no al leer — en los dos motores.

sqlite3 (isolation_level='') manda el BEGIN recién antes de la primera escritura.
El shim de Postgres lo mandaba en el primer SELECT (autocommit=False), y su
comentario decía que era «lo mismo que sqlite3». No lo era: todo pedido que lee
y después sale a la red dejaba la transacción abierta y ociosa durante la espera.
Medido el 29/10/2026 en `/api/wrapped`: con la inflación tardando más que el
reloj de la suite, la conexión moría y el mejor mes salía «+0,00%»
(`test_rendimientos_mensuales.test_el_wrapped_no_pierde_el_mes_si_la_inflacion_tarda`).

Las pruebas de comportamiento corren con la conexión de la app (`main.get_db()`)
en el motor que toque, así SQLite hace de referencia: lo que da allá tiene que
dar acá.
"""
import os
import sys
import unittest
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
import main  # noqa: E402
from pgshim import es_lectura_pura  # noqa: E402


@pytest.mark.parametrize("sql", [
    "SELECT * FROM users WHERE id=%s",
    "  select count(*) from operations",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "SELECT updated_at, last_update FROM positions",       # «update» dentro de un nombre
    "SHOW search_path",
])
def test_lo_que_corre_suelto(sql):
    assert es_lectura_pura(sql)


@pytest.mark.parametrize("sql", [
    "INSERT INTO users (email) VALUES (%s)",
    "UPDATE users SET tier=tier WHERE id=%s",              # el turno
    "DELETE FROM monthly_entries WHERE id=%s",
    "SAVEPOINT recalc",
    "SELECT pg_advisory_xact_lock(%s)",                    # el turno exclusivo
    "SELECT pg_advisory_xact_lock(%s, %s)",
    "SELECT * FROM users WHERE id=%s FOR UPDATE",
    "SELECT * FROM users FOR NO KEY UPDATE",
    "SELECT set_config('x.y', '1', true)",                 # el SET LOCAL
    "SELECT * INTO copia FROM users",
    "WITH b AS (DELETE FROM snapshots RETURNING id) SELECT count(*) FROM b",
    "CREATE TABLE t (x int)",
    "LOCK TABLE users",
])
def test_lo_que_abre_la_transaccion(sql):
    assert not es_lectura_pura(sql)


class LeerNoDejaNadaAbierto(unittest.TestCase):

    def setUp(self):
        self.conn = main.get_db()

    def tearDown(self):
        try:
            self.conn.rollback()
        finally:
            self.conn.close()

    def test_un_select_no_abre_la_transaccion(self):
        self.conn.execute("SELECT COUNT(*) FROM users").fetchone()
        self.assertFalse(self.conn.in_transaction,
                         "leer dejó una transacción abierta: en Postgres queda ociosa "
                         "mientras el pedido sale a la red")

    def test_escribir_si_la_abre_y_lo_leido_antes_no_cambia_eso(self):
        self.conn.execute("SELECT COUNT(*) FROM users").fetchone()
        self.conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
                          (f"abre-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertFalse(self.conn.in_transaction)

    def test_lo_que_no_se_confirma_no_queda(self):
        email = f"abre-{uuid.uuid4().hex[:8]}@rendi.test"
        self.conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
                          (email,))
        self.conn.rollback()
        n = self.conn.execute("SELECT COUNT(*) FROM users WHERE email=?", (email,)).fetchone()[0]
        self.assertEqual(n, 0, "el INSERT corrió suelto y el rollback no se lo llevó")


@unittest.skipUnless(getattr(main, "USANDO_PG", False), "el candado de asesoría es de Postgres")
class ElTurnoExclusivoSigueDurandoHastaElCommit(unittest.TestCase):
    """`pg_advisory_xact_lock` viene en un SELECT. Si corriera suelto, el candado
    se soltaría en el mismo instante y el turno exclusivo no protegería nada."""

    def test_el_candado_lo_tiene_hasta_confirmar(self):
        clave = 7_290_001
        a, b = main.get_db(), main.get_db()
        try:
            a.execute("SELECT pg_advisory_xact_lock(?)", (clave,))
            libre = b.execute("SELECT pg_try_advisory_xact_lock(?)", (clave,)).fetchone()[0]
            b.rollback()
            self.assertFalse(libre, "el candado se soltó antes del commit")
            a.commit()
            libre = b.execute("SELECT pg_try_advisory_xact_lock(?)", (clave,)).fetchone()[0]
            b.rollback()
            self.assertTrue(libre)
        finally:
            a.close()
            b.close()


if __name__ == "__main__":
    unittest.main()
