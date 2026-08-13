"""El shim no puede revertir la transacción del que lo llama.

EL BUG QUE FIJA ESTE ARCHIVO. Para emular `lastrowid`, el shim necesita saber cuál
es la clave primaria de cada tabla, y lo lee del catálogo UNA vez por proceso. Ese
lookup terminaba con un `rollback()` —puesto para "no dejar colgada" la transacción
que abría el SELECT—, pero la transacción no era del SELECT: era la del llamador.
Y el lookup corre desde `execute()` justo ANTES de un INSERT.

Resultado: en el **primer INSERT de cada proceso**, todo lo que el llamador venía
haciendo en esa misma transacción se revertía. Sin error, sin log. La secuencia
`CREATE TABLE` + `INSERT` fallaba con "relation does not exist", y cualquier
escritura anterior a ese INSERT simplemente desaparecía.

Lo peor era cómo se escondía: con el caché ya cargado la misma secuencia anda
perfecto, así que el problema sólo aparece en la PRIMERA transacción después de
arrancar — y desaparece si algo la calentó antes. En la suite estuvo tapado
durante toda la migración porque otro test corría primero.

Estos tests corren SÓLO en Postgres: en SQLite el shim ni se usa.
"""
import unittest

import main


@unittest.skipUnless(getattr(main, "USANDO_PG", False),
                     "el shim sólo actúa en modo Postgres")
class ElShimNoRevierteLoDelLlamadorTest(unittest.TestCase):
    def setUp(self):
        import pgshim
        # Caché FRÍO: es el estado del primer INSERT de cada proceso, que es
        # exactamente cuando se disparaba el bug. Sin esto el test no prueba nada.
        pgshim.limpiar_caches()
        self.conn = main.get_db()

    def tearDown(self):
        try:
            self.conn.rollback()
        finally:
            self.conn.close()

    def test_un_create_y_su_insert_sobreviven_con_el_cache_frio(self):
        """La forma exacta en que se manifestaba."""
        self.conn.execute("CREATE TABLE IF NOT EXISTS x_shim_tmp (id INTEGER)")
        self.conn.execute("INSERT INTO x_shim_tmp VALUES (1)")
        n = self.conn.execute("SELECT COUNT(*) FROM x_shim_tmp").fetchone()[0]
        self.assertEqual(n, 1, "el shim revirtió la transacción del que llamó")

    def test_una_escritura_ANTERIOR_al_primer_insert_no_se_pierde(self):
        """El caso que de verdad asusta: no es la tabla nueva, es la plata.

        Un UPDATE hecho antes del primer INSERT del proceso desaparecía sin dejar
        rastro. Se usa `config`, que existe siempre y no es de nadie en particular.
        """
        self.conn.execute(
            "INSERT INTO config (key, value, user_id) VALUES ('x_shim_probe','1',0) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value = EXCLUDED.value")
        self.conn.commit()

        import pgshim
        pgshim.limpiar_caches()                     # de vuelta a frío
        conn2 = main.get_db()
        try:
            conn2.execute("UPDATE config SET value='2' "
                          "WHERE key='x_shim_probe' AND user_id=0")
            # este INSERT es el primero del proceso → dispara el lookup del catálogo
            conn2.execute("CREATE TABLE IF NOT EXISTS x_shim_tmp2 (id INTEGER)")
            conn2.execute("INSERT INTO x_shim_tmp2 VALUES (1)")
            v = conn2.execute("SELECT value FROM config WHERE key='x_shim_probe' "
                              "AND user_id=0").fetchone()[0]
            self.assertEqual(v, "2", "el UPDATE previo se perdió: el shim revirtió "
                                     "la transacción del llamador")
            conn2.rollback()
        finally:
            conn2.close()


if __name__ == "__main__":
    unittest.main()
