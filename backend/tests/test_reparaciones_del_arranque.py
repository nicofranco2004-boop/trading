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

Hasta el 2026-10-29 **en Postgres no corría ninguna**, y sin dejar rastro: el
`return` pasaba antes. Se midieron las dos preguntas por separado, porque el
arreglo dependía de la respuesta:

  1. ¿el SQL FUNCIONA en Postgres?  → **SÍ** → no había nada que traducir
  2. ¿`init_db` las CORRE?          → **NO** → el arreglo es estructural

Arreglado sacándolas a `main.reparaciones_de_arranque(conn)`, que `init_db` llama
en LOS DOS MOTORES. Este archivo se queda como el candado de que siga así: si
alguien vuelve a meterlas detrás del `return`, el segundo test se pone rojo sólo
en Postgres.
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

    def test_el_arranque_la_corre_en_LOS_DOS_motores(self):
        """`init_db()` por el camino real tiene que reparar en los dos.

        Antes del 2026-10-29 esto era al revés: el test exigía que en Postgres
        quedara SIN reparar, y su mensaje decía «si esto se pone rojo es la
        noticia buena». Se puso rojo, y acá está dado vuelta.
        """
        main.init_db()
        self.assertEqual(
            self._caja(), "USD",
            f"[{_motor()}] init_db no reparó la caja. En Postgres el sospechoso "
            f"es el `return` de init_db: las reparaciones tienen que estar en "
            f"`reparaciones_de_arranque`, llamada en LOS DOS motores.")

    def test_la_funcion_de_reparaciones_existe_y_init_db_la_llama_dos_veces(self):
        """El candado estructural: que la llamada esté en las DOS ramas.

        Un test de comportamiento no alcanza acá: alguien puede dejar la función
        y borrar la llamada de la rama de Postgres, y el otro test sólo se cae
        cuando la suite corre contra Postgres — que no es lo que corre siempre.
        """
        import ast, inspect, textwrap
        arbol = ast.parse(textwrap.dedent(inspect.getsource(main.init_db)))
        llamadas = [n for n in ast.walk(arbol)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "reparaciones_de_arranque"]
        self.assertEqual(
            len(llamadas), 2,
            "`init_db` tiene que llamar a `reparaciones_de_arranque` DOS veces: "
            "una en la rama de Postgres (después de _init_db_postgres) y una al "
            f"final de la de SQLite. Encontré {len(llamadas)}.")


if __name__ == "__main__":
    unittest.main()
