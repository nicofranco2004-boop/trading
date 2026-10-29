"""«Confirmar» una transacción que Postgres ya descartó tiene que AVISAR.

psycopg no avisa: después de un error de SQL, `commit()` manda un COMMIT, el
servidor contesta ROLLBACK y no se levanta nada. Con la forma «try → except que
loguea → commit → 200» (28 funciones, hallazgo 11) eso era perder el pedido entero
contestando éxito. `pgshim.Connection` ahora lo deshace explícito y levanta.

Sólo en Postgres: en SQLite un error no arruina la transacción y el commit guarda
lo de antes, que es justamente lo que el código suponía.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)
import main


@unittest.skipUnless(getattr(main, "USANDO_PG", False), "sólo Postgres aborta la transacción")
class ConfirmarLoDescartadoAvisa(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.email = f"commit-{os.urandom(5).hex()}@rendi.test"

    def tearDown(self):
        try: self.conn.rollback()
        except Exception: pass
        self.conn.execute("DELETE FROM users WHERE email=?", (self.email,))
        self.conn.commit()
        self.conn.close()

    def _escribir_y_romper(self):
        self.conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                          (self.email, "x"))
        try:
            self.conn.execute("SELECT columna_que_no_existe FROM users")
        except Exception:
            pass   # la forma de las 28: el error se traga y se sigue

    def _quedo(self):
        return self.conn.execute("SELECT 1 FROM users WHERE email=?", (self.email,)).fetchone()

    def test_commit_levanta_y_no_queda_nada(self):
        self._escribir_y_romper()
        with self.assertRaises(Exception) as ctx:
            self.conn.commit()
        self.assertIn("se descartó", str(ctx.exception))
        self.assertIsNone(self._quedo())
        # La conexión queda usable: el rollback ya se hizo.
        self.assertIsNotNone(self.conn.execute("SELECT 1 AS x").fetchone())

    def test_with_conn_tambien_levanta(self):
        with self.assertRaises(Exception):
            with self.conn:
                self._escribir_y_romper()
        self.assertIsNone(self._quedo())

    def test_un_commit_normal_sigue_guardando(self):
        self.conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                          (self.email, "x"))
        self.conn.commit()
        self.assertIsNotNone(self._quedo())

    def test_con_punto_de_guardado_lo_de_antes_se_guarda(self):
        self.conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                          (self.email, "x"))
        try:
            with main._si_falla_se_deshace_solo_esto(self.conn, "prueba"):
                self.conn.execute("SELECT columna_que_no_existe FROM users")
        except Exception:
            pass
        self.conn.commit()
        self.assertIsNotNone(self._quedo())


if __name__ == "__main__":
    unittest.main()
