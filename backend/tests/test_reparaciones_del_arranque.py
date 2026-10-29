"""Las reparaciones del arranque: ¿corren en Postgres, y funcionarían si corrieran?

`init_db()` arranca con `if USANDO_PG: _init_db_postgres(); return`. El motivo es
correcto PARA EL ESQUEMA: las 46 migraciones incrementales son la HISTORIA del
esquema de SQLite y Postgres arranca del resultado (`schema_pg.sql`). Pero
adentro de esa misma función, después del esquema, hay **18 sentencias que tocan
DATOS** — y varias están escritas para correr en CADA boot, con su «quedan 0»
como confirmación:

    main.py:3736  las cajas 'USDT' de brokers en DÓLARES se renombran a 'USD'
    main.py:3756  las cajas vacías pierden el precio de compra que ya no tienen
    main.py:3019  last_login_at se completa desde el historial de ingresos

En Postgres **ninguna corre**, y no deja rastro: el `return` pasa antes. Esto
separa las dos preguntas, porque el arreglo depende de la respuesta:

  1. ¿corren?            → NO (lo prueba el test de abajo, en los dos motores)
  2. ¿funcionarían?      → si la respuesta es SÍ, el arreglo es sacarlas de
                           `init_db` y llamarlas en los dos motores. Si es NO,
                           además hay que traducir el SQL.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)
import main
import efectivo as _efectivo


def _motor():
    return "Postgres" if getattr(main, "USANDO_PG", False) else "SQLite"


class ReparacionesDelArranqueTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"arranque-{os.urandom(5).hex()}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "SchwabArranque", "USD"))
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
            "VALUES (?,?,'USDT',1,?)", (self.uid, "SchwabArranque", 1234.5))
        self.conn.commit()

    def tearDown(self):
        try:
            for t in ("positions", "brokers"):
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def _caja(self):
        self.conn.rollback()
        return self.conn.execute(
            "SELECT asset FROM positions WHERE user_id=? AND is_cash=1",
            (self.uid,)).fetchone()["asset"]

    def test_la_reparacion_de_las_cajas_FUNCIONA_en_los_dos_motores(self):
        """El SQL de la reparación, corrido a mano: tiene que renombrar la caja.

        Si esto es verde en los dos motores, el arreglo de que no corra en
        Postgres es SÓLO sacarla de `init_db` — no hay que traducir nada.
        """
        donde = ("is_cash=1 AND asset='USDT' AND EXISTS (SELECT 1 FROM brokers b "
                 "WHERE b.user_id=positions.user_id AND b.name=positions.broker "
                 "AND b.currency='USD')")
        n = self.conn.execute(f"UPDATE positions SET asset=? WHERE {donde}",
                              (_efectivo.asset_de_caja('USD'),)).rowcount
        self.conn.commit()
        self.assertGreaterEqual(n, 1, f"[{_motor()}] la reparación no tocó ninguna fila")
        self.assertEqual(self._caja(), "USD",
                         f"[{_motor()}] la caja quedó sin renombrar")

    def test_el_arranque_NO_la_corre_en_postgres(self):
        """`init_db()` por el camino real. En SQLite repara; en Postgres no.

        Este test no es un deseo: documenta el agujero con un número. Cuando las
        reparaciones salgan de `init_db` y se llamen en los dos motores, se cae
        la rama de Postgres de acá y hay que darlo vuelta — eso es lo que se
        quiere.
        """
        main.init_db()
        quedo = self._caja()
        if getattr(main, "USANDO_PG", False):
            self.assertEqual(
                quedo, "USDT",
                "init_db ya repara en Postgres: dar vuelta este test (es la "
                "noticia buena) y sacar la nota del docstring")
        else:
            self.assertEqual(quedo, "USD",
                             "[SQLite] init_db dejó de reparar: eso sí es una regresión")


if __name__ == "__main__":
    unittest.main()
