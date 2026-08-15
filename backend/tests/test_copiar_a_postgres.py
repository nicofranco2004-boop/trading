"""¿El copiador copia todo, y falla cuando tiene que fallar?

Se corre UNA vez, un domingo, con la app abajo y 1.084 personas esperando. No hay
"lo reintento el lunes": hay una ventana. Así que todo lo que se pueda probar antes,
se prueba antes.

LOS TRES MODOS DE FALLA QUE ESTOS TESTS PERSIGUEN, en orden de lo que cuestan:

  1. **Reportar éxito sin haber copiado nada.** El peor, y no es hipotético:
     `with conn.transaction()` sólo commitea si es la transacción MÁS EXTERNA.
     Cualquier consulta previa sobre la misma conexión —el preflight, por
     ejemplo— ya abrió una, así que el bloque se degrada a SAVEPOINT y al cerrar
     la conexión el servidor rollbackea TODO. Medido acá abajo: adentro se ven 3
     filas, en la base quedan 0. La herramienta habría dicho "los cuatro niveles
     en cero", con el cronómetro completo, sobre una base vacía.
  2. **Cortar a mitad de la ventana** por un dato que se podía saber días antes:
     un texto en una columna numérica, un huérfano, un NULL en un NOT NULL. Para
     eso está el preflight, y por eso es precondición y no sugerencia.
  3. **Copiar de menos en silencio.** Una tabla que no viajó, una secuencia sin
     adelantar. Lo cubre `verificar_copia.py`; acá se prueba que el copiador la
     corra de verdad y **contra la base commiteada**, no contra su propia sesión.

Los tests que necesitan Postgres se saltean sin `PG_DSN_VERIF`. Los de orden de
copia y los de las guardas son Python puro y corren siempre.
"""
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import copiar_a_postgres as cp  # noqa: E402
import verificar_copia as vc    # noqa: E402


# ── Lo que no necesita Postgres ──────────────────────────────────────────────

class ElOrdenDeCopiaTest(unittest.TestCase):
    """Insertar en el orden equivocado viola una FK y corta la copia a mitad."""

    def test_el_padre_va_antes_que_el_hijo(self):
        orden, loops = cp.orden_de_copia(
            {"users", "brokers", "positions"},
            [("brokers", "user_id", "users"), ("positions", "user_id", "users")])
        self.assertEqual(loops, [])
        self.assertLess(orden.index("users"), orden.index("brokers"))
        self.assertLess(orden.index("users"), orden.index("positions"))

    def test_la_auto_referencia_sale_DERIVADA_no_escrita_a_mano(self):
        """Hoy la única es `brokers.parent_broker_id`. Si mañana aparece una
        segunda, el copiador tiene que manejarla sola: un nombre de tabla escrito
        a mano en dos lugares es cómo una defensa queda a medias sin que se note."""
        _orden, loops = cp.orden_de_copia(
            {"brokers", "categorias"},
            [("brokers", "parent_broker_id", "brokers"),
             ("categorias", "padre_id", "categorias")])
        self.assertEqual(sorted(loops),
                         [("brokers", "parent_broker_id"), ("categorias", "padre_id")])

    def test_un_ciclo_entre_DOS_tablas_LEVANTA_en_vez_de_elegir_cualquiera(self):
        """Con un ciclo real no hay orden posible, y elegir uno cualquiera
        insertaría filas que violan la FK: cortaría a mitad de la ventana. Es una
        decisión (cuál va en NULL primero), no algo para adivinar."""
        with self.assertRaises(cp.NoSePuedeCopiar):
            cp.orden_de_copia({"a", "b"}, [("a", "b_id", "b"), ("b", "a_id", "a")])

    def test_una_FK_hacia_una_tabla_que_no_se_copia_no_rompe_el_orden(self):
        orden, _ = cp.orden_de_copia({"a"}, [("a", "x", "no_existe")])
        self.assertEqual(orden, ["a"])


class LasGuardasTest(unittest.TestCase):

    def test_el_origen_con_WAL_sin_checkpoint_ABORTA(self):
        """🔴 El peor error posible del día. Si se copia el `.db` sin su `-wal`,
        una lectura ingenua pierde en silencio las últimas transacciones de TODOS
        los usuarios — y ningún nivel de la verificación lo puede ver, porque el
        destino se compara contra esa misma lectura mal hecha."""
        import tempfile
        d = tempfile.mkdtemp()
        base = os.path.join(d, "t.db")
        sqlite3.connect(base).close()
        with open(base + "-wal", "wb") as f:
            f.write(b"x" * 100)
        with self.assertRaises(cp.NoSePuedeCopiar) as ctx:
            cp.abrir_origen(base)
        self.assertIn("wal_checkpoint", str(ctx.exception))

    def test_el_origen_con_WAL_VACIO_abre_normal(self):
        """La contracara: un `-wal` de 0 bytes es lo normal después del
        checkpoint. Si esto abortara, la guarda sería ruido que se aprende a
        saltear — y ahí sí alguien le saca el `mode=ro`."""
        import tempfile
        d = tempfile.mkdtemp()
        base = os.path.join(d, "t.db")
        sqlite3.connect(base).close()
        open(base + "-wal", "wb").close()
        cp.abrir_origen(base).close()

    def test_el_origen_se_abre_SOLO_LECTURA(self):
        """Es la base de la que dependen 1.084 personas: si el copiador tiene un
        bug, que no pueda escribir."""
        import tempfile
        base = os.path.join(tempfile.mkdtemp(), "t.db")
        c = sqlite3.connect(base)
        c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        c.commit()
        c.close()
        ro = cp.abrir_origen(base)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("INSERT INTO t VALUES (1)")
        finally:
            ro.close()

    def test_los_subcomandos_que_ESCRIBEN_abortan_con_DATABASE_URL_puesta(self):
        """Si la app ya está migrada, `DATABASE_URL` apunta a la base VIVA. Un
        `preparar-destino` ahí borra todo."""
        previo = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://vivo/prod"
        try:
            with self.assertRaises(cp.NoSePuedeCopiar):
                cp._guarda_de_escritura("preparar-destino")
        finally:
            if previo is None:
                del os.environ["DATABASE_URL"]
            else:
                os.environ["DATABASE_URL"] = previo


# ── Lo que necesita Postgres ─────────────────────────────────────────────────

DDL_ORIGEN = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL);
CREATE TABLE brokers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    name TEXT NOT NULL, parent_broker_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (parent_broker_id) REFERENCES brokers(id));
-- `user_id` va SIN NOT NULL a propósito: es la divergencia real que P3 existe
-- para agarrar. En SQLite no se puede agregar una columna NOT NULL sin default a
-- una tabla que ya existe, así que producción tiene columnas nullable que el
-- esquema de Postgres declara NOT NULL.
CREATE TABLE positions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    broker TEXT, asset TEXT, is_cash INTEGER, quantity REAL, invested REAL,
    commissions REAL, nota TEXT);
CREATE TABLE operations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    asset TEXT, pnl_usd REAL);
"""
# ⚠️ El fixture tiene que traer las columnas que consulta el NIVEL 2
# (`is_cash`, `quantity`, `commissions`, `pnl_usd`): la verificación las nombra
# explícitamente y falla fuerte si no están — que es lo correcto, pero significa
# que un mini-esquema de juguete no alcanza para ejercitarla.

DDL_DESTINO = """
CREATE TABLE users (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    email text NOT NULL);
CREATE TABLE brokers (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL, name text NOT NULL, parent_broker_id bigint);
CREATE TABLE positions (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL, broker text, asset text, is_cash bigint,
    quantity double precision, invested double precision,
    commissions double precision, nota text);
CREATE TABLE operations (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL, asset text, pnl_usd double precision);
ALTER TABLE brokers ADD CONSTRAINT fk_brokers_user_id_users
    FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE brokers ADD CONSTRAINT fk_brokers_parent_broker_id_brokers
    FOREIGN KEY (parent_broker_id) REFERENCES brokers(id);
"""


@unittest.skipUnless(os.environ.get("PG_DSN_VERIF"),
                     "necesita PG_DSN_VERIF (una base Postgres APARTE de la de la suite)")
class ContraPostgresTest(unittest.TestCase):

    def setUp(self):
        import psycopg
        import tempfile
        self.psycopg = psycopg
        self.dsn = os.environ["PG_DSN_VERIF"]
        self.ruta = os.path.join(tempfile.mkdtemp(), "origen.db")
        o = sqlite3.connect(self.ruta)
        o.executescript(DDL_ORIGEN)
        o.executemany("INSERT INTO users VALUES (?,?)",
                      [(1, "ana@x.test"), (2, "beto@x.test")])
        o.executemany("INSERT INTO brokers VALUES (?,?,?,?)",
                      [(1, 1, "Cocos", None), (2, 1, "Cocos USD", 1), (3, 2, "IOL", None)])
        o.executemany("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?)",
                      [(1, 1, "Cocos", "AAPL", 0, 10.0, 1500.25, 3.5, "x"),
                       (2, 2, "IOL", "AL30", 0, 1000.0, 62000.0, 12.125, None)])
        o.executemany("INSERT INTO operations VALUES (?,?,?,?)",
                      [(1, 1, "AAPL", 123.45), (2, 2, "AL30", -67.89)])
        o.commit()
        o.close()
        self._crear_destino()

    def _crear_destino(self):
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS cop CASCADE")
            c.execute("CREATE SCHEMA cop")
            c.execute("SET search_path = cop")
            for s in [x.strip() for x in DDL_DESTINO.split(";") if x.strip()]:
                c.execute(s)

    def tearDown(self):
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS cop CASCADE")

    def _dsn_cop(self):
        from psycopg.conninfo import make_conninfo
        return make_conninfo(self.dsn, options="-c search_path=cop")

    def _copiar(self):
        class Args:
            origen = self.ruta
            destino = self._dsn_cop()
        return cp.cmd_copiar(Args())

    # ── 🔴 el bloqueante: reportar éxito sin haber copiado ───────────────────
    def test_los_datos_QUEDAN_despues_de_cerrar_la_conexion(self):
        """EL test. Se abre una conexión NUEVA, después de que el copiador
        terminó y cerró la suya. Si el commit no fuera explícito —si fuera un
        `with conn.transaction()` que el preflight degradó a SAVEPOINT— esto daría
        cero y el copiador ya habría dicho "cuatro niveles en verde"."""
        self.assertEqual(self._copiar(), 0)
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("SET search_path = cop")
            self.assertEqual(c.execute("SELECT count(*) FROM users").fetchone()[0], 2)
            self.assertEqual(c.execute("SELECT count(*) FROM brokers").fetchone()[0], 3)
            self.assertEqual(c.execute("SELECT count(*) FROM positions").fetchone()[0], 2)

    def test_el_with_transaction_PIERDE_TODO_y_por_eso_no_se_usa(self):
        """La contraprueba del bloqueante, medida y no razonada.

        Reproduce el patrón que el diseño proponía: una consulta previa (el
        preflight) + `with conn.transaction()`. Adentro se ven las filas; en la
        base no queda ninguna. Este test deja constancia de POR QUÉ el copiador
        usa `commit()` explícito, para que nadie lo "simplifique" de vuelta.
        """
        con = self.psycopg.connect(self.dsn, autocommit=False)
        con.execute("SET search_path = cop")
        con.execute("SELECT 1 FROM information_schema.tables LIMIT 1")   # el preflight
        with con.transaction():
            con.execute("INSERT INTO users (id, email) VALUES (99, 'z@z.z')")
            adentro = con.execute("SELECT count(*) FROM users").fetchone()[0]
        con.close()
        self.assertEqual(adentro, 1, "adentro del bloque las ve")
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("SET search_path = cop")
            self.assertEqual(c.execute("SELECT count(*) FROM users").fetchone()[0], 0,
                             "si esto dejó de dar 0, psycopg cambió y hay que "
                             "revisar el comentario de `copiar`")

    # ── la auto-referencia ───────────────────────────────────────────────────
    def test_el_broker_hijo_queda_apuntando_a_su_padre(self):
        """La segunda pasada. Si no corriera, `parent_broker_id` quedaría en NULL
        y el CEDEAR pagado por MEP volvería a aparecer dos veces — sin error."""
        self._copiar()
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("SET search_path = cop")
            self.assertEqual(
                c.execute("SELECT parent_broker_id FROM brokers WHERE id=2").fetchone()[0], 1)

    # ── las secuencias ───────────────────────────────────────────────────────
    def test_el_proximo_alta_NO_choca_contra_un_id_existente(self):
        """Sin `setval` la secuencia arranca en 1 y el primer usuario que se
        registre después del pasaje choca contra un id que ya existe."""
        self._copiar()
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("SET search_path = cop")
            nuevo = c.execute(
                "INSERT INTO users (email) VALUES ('nuevo@x.test') RETURNING id"
            ).fetchone()[0]
        self.assertGreater(nuevo, 2)

    # ── la virginidad del destino ────────────────────────────────────────────
    def test_copiar_DOS_veces_aborta_en_vez_de_duplicar(self):
        self.assertEqual(self._copiar(), 0)
        with self.assertRaises(cp.NoSePuedeCopiar) as ctx:
            self._copiar()
        self.assertIn("NO está vacío", str(ctx.exception))

    def test_preparar_destino_deja_todo_listo_para_reintentar(self):
        self._copiar()

        class Args:
            origen = self.ruta
            destino = self._dsn_cop()
        self.assertEqual(cp.cmd_preparar_destino(Args()), 0)
        self.assertEqual(self._copiar(), 0)

    # ── qué queda si se corta a mitad ────────────────────────────────────────
    def test_si_se_corta_a_mitad_el_destino_queda_LIMPIO(self):
        """El escenario del domingo: se corta la copia con 1 GB a medio subir.

        Todo el copiado va en UNA transacción, así que el servidor rollbackea solo
        cuando la conexión muere. Medido a escala real matando el proceso a los 12
        segundos (a mitad de `import_raw_rows`): quedaron **0 filas** y **0
        conexiones colgadas**, y el reintento anduvo DIRECTO.

        ⚠️ **Eso corrige el plan**, que decía "`preparar-destino` + reintentar".
        Después de un corte NO hace falta: el destino ya está vacío.
        `preparar-destino` sirve para rehacer una copia que TERMINÓ bien.

        Acá se fuerza el corte de forma determinística —haciendo fallar el paso
        siguiente al COPY— en vez de matar un proceso, que sería lento y flaky.
        """
        import unittest.mock
        with unittest.mock.patch.object(cp, "correr_setval",
                                        side_effect=RuntimeError("se cortó la red")):
            with self.assertRaises(RuntimeError):
                self._copiar()
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("SET search_path = cop")
            for t in ("users", "brokers", "positions", "operations"):
                self.assertEqual(c.execute(f"SELECT count(*) FROM {t}").fetchone()[0], 0,
                                 f"{t} quedó con filas a medias después del corte")
        self.assertEqual(self._copiar(), 0, "el reintento tiene que andar directo")

    # ── el preflight, cada chequeo con su dato plantado ──────────────────────
    def _preflight(self):
        o = cp.abrir_origen(self.ruta)
        try:
            with self.psycopg.connect(self._dsn_cop(), autocommit=True) as d:
                return cp.preflight(o, vc.CursorPg(d))
        finally:
            o.close()

    def test_el_preflight_de_una_base_sana_esta_LIMPIO(self):
        """Sin esto, un preflight que denunciara siempre también pasaría todos los
        tests de abajo — y sería ruido que se aprende a ignorar."""
        self.assertEqual(self._preflight(), [])

    def test_P3_un_NULL_en_una_columna_NOT_NULL(self):
        o = sqlite3.connect(self.ruta)
        o.execute("INSERT INTO positions (id, user_id, asset, is_cash) "
                  "VALUES (9, NULL, 'X', 0)")
        o.commit()
        o.close()
        self.assertTrue([h for h in self._preflight() if h["chequeo"] == "P3"])

    def test_P4_un_TEXTO_en_una_columna_numerica(self):
        """SQLite lo acepta; Postgres corta la copia a mitad de la ventana."""
        o = sqlite3.connect(self.ruta)
        o.execute("UPDATE positions SET invested = 'N/A' WHERE id = 1")
        o.commit()
        o.close()
        h = [x for x in self._preflight() if x["chequeo"] == "P4"]
        self.assertTrue(h)
        self.assertEqual(h[0]["columna"], "invested")

    def test_P5_un_BLOB_en_una_columna_text(self):
        """Sin esto entraría como el string `\\x616263` y sólo lo agarraría el
        NIVEL 1, después del pasaje y sin decir qué columna."""
        o = sqlite3.connect(self.ruta)
        o.execute("UPDATE positions SET nota = ? WHERE id = 1", (b"\x01\x02\x03",))
        o.commit()
        o.close()
        self.assertTrue([h for h in self._preflight() if h["chequeo"] == "P5"])

    def test_P6_una_fila_huerfana(self):
        """SQLite la aguanta (las FKs están apagadas por defecto) y Postgres la
        rechaza. Es una DECISIÓN que hay que tomar días antes, no un domingo."""
        o = sqlite3.connect(self.ruta)
        o.execute("INSERT INTO brokers VALUES (9, 999, 'Fantasma', NULL)")
        o.commit()
        o.close()
        h = [x for x in self._preflight() if x["chequeo"] == "P6"]
        self.assertTrue(h)
        self.assertIn("huérfanas", h[0]["que"])

    def test_P1_una_tabla_del_origen_que_el_destino_no_tiene(self):
        o = sqlite3.connect(self.ruta)
        o.execute("CREATE TABLE fci_prices (symbol TEXT PRIMARY KEY, price REAL)")
        o.commit()
        o.close()
        h = [x for x in self._preflight() if x["chequeo"] == "P1"]
        self.assertTrue(h)
        self.assertEqual(h[0]["tabla"], "fci_prices")

    def test_el_preflight_es_PRECONDICION_de_copiar_no_una_sugerencia(self):
        """Se re-corre adentro de `copiar`, sobre esta base y en esta corrida. No
        se acepta la prueba de un preflight anterior: un papel se copia de otra
        corrida, una lectura de la base no."""
        o = sqlite3.connect(self.ruta)
        o.execute("UPDATE positions SET invested = 'N/A' WHERE id = 1")
        o.commit()
        o.close()
        with self.assertRaises(cp.NoSePuedeCopiar) as ctx:
            self._copiar()
        self.assertIn("preflight", str(ctx.exception))
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("SET search_path = cop")
            self.assertEqual(c.execute("SELECT count(*) FROM users").fetchone()[0], 0,
                             "abortó DESPUÉS de haber escrito: tiene que abortar antes")


if __name__ == "__main__":
    unittest.main()
