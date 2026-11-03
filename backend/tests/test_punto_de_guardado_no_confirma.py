"""El punto de guardado (`pgsesion.si_falla_se_deshace_solo_esto`) no confirma
nada por su cuenta, tampoco en SQLite cuando todavía no había transacción.

En SQLite, un SAVEPOINT sin transacción abierta abre una y su RELEASE la
confirma. La venta lo usaba antes de cualquier escritura: la pata en dólares
quedaba creada aunque la venta rebotara (03/11/2026,
`test_pata_de_la_moneda.test_venta_en_dolares_no_alcanza_no_usa_los_de_pesos`).
"""
import sqlite3
import unittest

import pgsesion


class ElPuntoDeGuardadoNoConfirma(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE t (x INTEGER)")
        self.conn.commit()

    def _filas(self):
        return self.conn.execute("SELECT x FROM t ORDER BY x").fetchall()

    def test_sin_transaccion_previa_lo_de_adentro_se_deshace_con_el_rollback(self):
        self.assertFalse(self.conn.in_transaction)
        with pgsesion.si_falla_se_deshace_solo_esto(self.conn, "prueba"):
            self.conn.execute("INSERT INTO t VALUES (1)")
        self.conn.rollback()
        self.assertEqual(self._filas(), [])

    def test_sin_transaccion_previa_lo_de_adentro_se_guarda_con_el_commit(self):
        with pgsesion.si_falla_se_deshace_solo_esto(self.conn, "prueba"):
            self.conn.execute("INSERT INTO t VALUES (1)")
        self.conn.commit()
        self.assertEqual(self._filas(), [(1,)])

    def test_si_falla_se_deshace_solo_eso_y_lo_de_antes_queda(self):
        self.conn.execute("INSERT INTO t VALUES (1)")
        with self.assertRaises(ZeroDivisionError):
            with pgsesion.si_falla_se_deshace_solo_esto(self.conn, "prueba"):
                self.conn.execute("INSERT INTO t VALUES (2)")
                1 / 0
        self.conn.commit()
        self.assertEqual(self._filas(), [(1,)])


if __name__ == "__main__":
    unittest.main()
