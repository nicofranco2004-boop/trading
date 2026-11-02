"""El tope de datos que la IA recuerda, con varios pedidos a la vez.

POR QUÉ EXISTE. `_atomic_insert_fact` (main.py) hace cumplir dos topes contando
y escribiendo en UNA sola sentencia:

    INSERT INTO ai_user_facts(…) SELECT …
     WHERE (SELECT COUNT(*) … ) < tope

Su docstring dice que esa forma evita el TOCTOU («leo, después escribo, y en el
medio entra otro»). En SQLite es cierto —el motor deja escribir a uno por vez—,
pero esa garantía la pone EL MOTOR, no la sentencia. En Postgres cada
transacción lee su propia foto: varios pedidos simultáneos cuentan lo mismo y
entran todos.

Medido el 22/10/2026 sobre el tope HERMANO (las pruebas gratis del mes, mismo
patrón): con tope 5 y 20 pedidos a la vez entraron 10. Por eso acá va el mismo
`turno_exclusivo` y por eso existe este test: el otro tope tenía quien lo
vigilara y éste no tenía NINGUNA prueba.

⚠️ Con SQLite este test pasa con y sin el arreglo —allá el motor ya serializa—,
así que **sólo prueba algo corriendo contra Postgres**. Ahí falla sin el turno.
"""
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
import pgshim


class TopeDeFactsSimultaneosTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"facts-{id(self)}@rendi.test", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM ai_user_facts WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        finally:
            self.conn.close()

    def test_el_tope_de_activos_aguanta_pedidos_simultaneos(self):
        """Con el tope lleno menos uno, N pedidos a la vez dejan entrar UNO."""
        tope = main.MAX_ACTIVE_FACTS
        # Llenar hasta tope-1: el siguiente es el ÚLTIMO lugar que queda.
        for i in range(tope - 1):
            self.conn.execute(
                "INSERT INTO ai_user_facts(user_id, content, source) VALUES (?,?,?)",
                (self.uid, f"previo {i}", "test"))
        self.conn.commit()

        n = 8
        # Con vencimiento: si un hilo no llega (no consiguió conexión), los demás
        # cortan con error en vez de esperar para siempre. Sin él, el 31/10 los
        # hilos colgados dejaron a pytest sin poder cerrarse durante un día y medio.
        listo = threading.Barrier(n, timeout=30)
        entraron = []

        def pedir(i):
            c = main.get_db()
            try:
                listo.wait()
                if main._atomic_insert_fact(c, self.uid, f"carrera {i}", "test"):
                    entraron.append(i)
            except Exception:
                pass
            finally:
                try: c.close()
                except Exception: pass

        hilos = [threading.Thread(target=pedir, args=(i,)) for i in range(n)]
        # Cada hilo toma su conexión ANTES de la barrera, y self.conn ya tiene una:
        # son n+1 a la vez. Con el pozo en 8 (la suite contra Supabase) el último
        # hilo esperaba un lugar que nadie devolvía. Ver pgshim.tope_temporal.
        with pgshim.tope_temporal(n + 5):
            [h.start() for h in hilos]
            [h.join(timeout=60) for h in hilos]

        vivos = self.conn.execute(
            "SELECT COUNT(*) c FROM ai_user_facts WHERE user_id=? AND is_active=1",
            (self.uid,)).fetchone()["c"]
        self.assertLessEqual(
            vivos, tope,
            f"el tope de {tope} no aguantó: quedaron {vivos} datos activos")
        self.assertEqual(
            len(entraron), 1,
            f"quedaba UN lugar y entraron {len(entraron)}")


if __name__ == "__main__":
    unittest.main()
