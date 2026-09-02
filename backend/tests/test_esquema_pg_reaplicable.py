"""`schema_pg.sql` se re-aplica en CADA arranque. Tiene que aguantarlo.

EL PROBLEMA, medido y no razonado. `_init_db_postgres()` (`main.py:552`) abre
`schema_pg.sql` y lo ejecuta entero **cada vez que arranca el proceso**. Su
docstring decía *"idempotente: todo va con IF NOT EXISTS"* y era **falso para 12 de
las 132 sentencias**: las 12 `ALTER TABLE … ADD FOREIGN KEY`, que iban **sin
nombre**.

Y una FK sin nombre no falla al repetirse: Postgres le autogenera un nombre libre
(`brokers_user_id_fkey`, después `…_fkey1`, `…_fkey2`) y **crea una segunda
constraint idéntica, sin error**. Medido con tres ALTER seguidos: 3 constraints.

Lo que eso costaba:

  · cada `ADD FOREIGN KEY` **valida la tabla hija entera** tomando ACCESS
    EXCLUSIVE, y 5 de las 12 caen sobre tablas de ~1M de filas;
  · `init_db()` corre al IMPORTAR el módulo, o sea antes de que uvicorn abra el
    puerto → healthcheck rojo → Railway reinicia → otras 12. Es la forma exacta
    del 502 del 2026-08-02;
  · y cada INSERT posterior paga la verificación de N constraints repetidas.

⚠️ **Y LO PEOR ERA LA DEFENSA QUE NO DEFENDÍA.** `main.py:561` tiene un
`except psycopg.errors.DuplicateObject: pass` con el comentario *"la FK ya existía
(ADD FOREIGN KEY no tiene IF NOT EXISTS)"*. O sea que alguien vio el problema, lo
escribió, y puso una red para el error equivocado: sin nombre, ese error **nunca se
levanta**. Era letra muerta que hacía parecer resuelto lo que no lo estaba.

EL ARREGLO ESTÁ EN LA RAÍZ: las FKs salen con nombre desde `scripts/mkschema.py`,
que es el generador del archivo. Con nombre, repetir sí levanta `DuplicateObject`
y ahí el `except` de `main.py` recién hace lo que dice hacer.

ESTE TEST BUSCA LA CATEGORÍA, NO LAS 12 FK: revisa **todas** las sentencias del
archivo. Una sentencia nueva de cualquier tipo que no se pueda re-aplicar lo hace
fallar, aunque no sea una FK.
"""
import os
import re
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESQUEMA = os.path.join(RAIZ, "schema_pg.sql")


def sentencias():
    """Las sentencias del esquema, partidas igual que en `_init_db_postgres()`.

    El corte es `;\\n` y no `;` **a propósito**: es el mismo que hace main.py:558.
    Partir distinto acá mediría un archivo que en producción no existe.
    """
    ddl = open(ESQUEMA, encoding="utf-8").read()
    return [x.strip() for x in ddl.split(";\n") if x.strip()]


def no_reaplicables():
    """[(n, sentencia)] de las que fallarían —o peor, DUPLICARÍAN— al repetirse.

    Tres formas son seguras:
      · `IF NOT EXISTS` → Postgres no hace nada la segunda vez.
      · `ADD CONSTRAINT <nombre>` → la segunda vez levanta `DuplicateObject`, que
        es lo único que `_init_db_postgres()` sabe atrapar.
      · `CREATE OR REPLACE VIEW` → redefine sin error las veces que haga falta.
    Cualquier otra cosa se marca. Si mañana aparece una forma legítima nueva, se
    agrega acá **con el motivo escrito**, no se afloja el criterio.

    ⚠️ LA TERCERA SE AGREGÓ CON `snapshots_medibles`, y el motivo va escrito acá
    como pide el párrafo de arriba. Una vista no tiene `IF NOT EXISTS` en Postgres
    —la forma idiomática es `OR REPLACE`— así que sin esta rama el archivo no podía
    contener la vista, que es justo lo que hacía que Postgres no la tuviera. Y no
    alcanza con `DROP VIEW IF EXISTS` + `CREATE VIEW` (lo que hace la migración de
    SQLite): son dos sentencias, y la segunda cae en este mismo detector.

    Por qué `OR REPLACE` es de verdad re-aplicable y no una excusa: Postgres deja
    redefinir una vista mientras las columnas existentes no cambien de nombre ni de
    tipo, y **permite agregar columnas al final**. Como el esquema de `snapshots`
    sólo crece (cada ronda agregó columnas al final: `mtm_coverage`, `base`,
    `apto`), el `SELECT *` de la vista aguanta. Lo que SÍ rompería el arranque es
    RENOMBRAR o BORRAR una columna de `snapshots` — si algún día pasa, esta vista
    hay que actualizarla en el mismo commit.
    """
    malas = []
    for i, s in enumerate(sentencias(), 1):
        arriba = s.upper()
        if "IF NOT EXISTS" in arriba:
            continue
        if re.search(r"\bADD\s+CONSTRAINT\s+\S+", arriba):
            continue
        if re.search(r"\bCREATE\s+OR\s+REPLACE\s+VIEW\b", arriba):
            continue
        malas.append((i, s))
    return malas


class EsquemaSeReaplicaTest(unittest.TestCase):

    def test_ninguna_sentencia_del_esquema_rompe_al_repetirse(self):
        malas = no_reaplicables()
        if malas:
            detalle = "\n".join(f"  #{i}: {s[:100]}" for i, s in malas)
            self.fail(
                f"{len(malas)} sentencia(s) de schema_pg.sql no se pueden re-aplicar.\n"
                f"`_init_db_postgres()` corre este archivo ENTERO en cada arranque.\n"
                f"Una FK sin nombre no da error al repetirse: Postgres la DUPLICA en "
                f"silencio, y cada copia valida la tabla hija entera.\n"
                f"Arreglo: que salgan con `ADD CONSTRAINT <nombre>` desde "
                f"scripts/mkschema.py, que es quien genera este archivo.\n{detalle}")

    def test_las_15_FK_tienen_nombre_propio_y_distinto(self):
        """Un nombre repetido haría fallar el arranque LIMPIO, que es peor."""
        nombres = re.findall(r"ADD CONSTRAINT (\S+) FOREIGN KEY", "\n".join(sentencias()))
        # 15 desde IOL Lab (iol_lab_runs + iol_lab_token_log + iol_lab_imports → users). Si cambia, mirá
        # que la FK nueva tenga nombre propio (el generador lo pone solo).
        self.assertEqual(len(nombres), 15, f"cambió la cantidad de FKs: {len(nombres)}")
        self.assertEqual(len(set(nombres)), len(nombres),
                         f"hay nombres de FK repetidos: {nombres}")

    def test_ningun_nombre_pasa_el_limite_de_postgres(self):
        """63 bytes. Postgres TRUNCA sin avisar, y dos nombres largos que compartan
        los primeros 63 caracteres colisionarían recién en producción."""
        nombres = re.findall(r"ADD CONSTRAINT (\S+) ", "\n".join(sentencias()))
        largos = [n for n in nombres if len(n.strip('"')) > 63]
        self.assertEqual(largos, [], f"Postgres los va a truncar: {largos}")
        truncados = [n.strip('"')[:63] for n in nombres]
        self.assertEqual(len(set(truncados)), len(truncados),
                         "dos nombres colisionan una vez truncados a 63")

    def test_el_detector_agarra_una_sentencia_plantada(self):
        """Sin esto el test de arriba no prueba nada: podría estar mirando mal."""
        import unittest.mock
        plantada = sentencias() + [
            "ALTER TABLE brokers ADD FOREIGN KEY (user_id) REFERENCES users(id)"]
        with unittest.mock.patch(f"{__name__}.sentencias", return_value=plantada):
            malas = no_reaplicables()
        self.assertEqual(len(malas), 1, malas)
        self.assertIn("ADD FOREIGN KEY", malas[0][1])


@unittest.skipUnless(os.environ.get("PG_DSN_VERIF"),
                     "necesita PG_DSN_VERIF (una base Postgres APARTE de la de la suite)")
class ReaplicarDeVerdadTest(unittest.TestCase):
    """La prueba de comportamiento: aplicar el archivo DOS veces, como dos arranques.

    El test estructural de arriba mira el texto; éste mira lo que hace Postgres. Los
    dos hacen falta: el texto no puede saber que una FK sin nombre se duplica en vez
    de fallar, y eso —que se duplique en silencio— es el bug entero.
    """

    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.dsn = os.environ["PG_DSN_VERIF"]

    def _aplicar(self, c):
        """Igual que `_init_db_postgres()`: mismo corte, mismo except."""
        for s in sentencias():
            try:
                c.execute(s)
            except self.psycopg.errors.DuplicateObject:
                pass

    def test_dos_arranques_NO_duplican_las_claves_foraneas(self):
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS reapl CASCADE")
            c.execute("CREATE SCHEMA reapl")
            c.execute("SET search_path = reapl")
            try:
                self._aplicar(c)
                una = c.execute("SELECT count(*) FROM pg_constraint con "
                                "JOIN pg_namespace n ON n.oid = con.connamespace "
                                "WHERE n.nspname='reapl' AND con.contype='f'").fetchone()[0]
                self._aplicar(c)                       # el segundo arranque
                dos = c.execute("SELECT count(*) FROM pg_constraint con "
                                "JOIN pg_namespace n ON n.oid = con.connamespace "
                                "WHERE n.nspname='reapl' AND con.contype='f'").fetchone()[0]
            finally:
                c.execute("DROP SCHEMA IF EXISTS reapl CASCADE")
        self.assertEqual(una, 12, f"el primer arranque dejó {una} FKs, esperaba 12")
        self.assertEqual(dos, una,
                         f"el segundo arranque las DUPLICÓ: {una} → {dos}. Cada una "
                         f"valida la tabla hija entera con ACCESS EXCLUSIVE.")

    def test_el_except_DuplicateObject_de_main_AHORA_SI_se_dispara(self):
        """La defensa que existía y no defendía.

        Con la FK sin nombre, `DuplicateObject` no se levantaba nunca y el
        `except` de `main.py:561` era decorativo. Este test fija que el error que
        esa red dice atrapar es el que de verdad ocurre.
        """
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS reapl2 CASCADE")
            c.execute("CREATE SCHEMA reapl2")
            c.execute("SET search_path = reapl2")
            try:
                c.execute("CREATE TABLE users (id bigint PRIMARY KEY)")
                c.execute("CREATE TABLE brokers (id bigint PRIMARY KEY, user_id bigint)")
                alter = ("ALTER TABLE brokers ADD CONSTRAINT fk_brokers_user_id_users "
                         "FOREIGN KEY (user_id) REFERENCES users(id)")
                c.execute(alter)
                with self.assertRaises(self.psycopg.errors.DuplicateObject):
                    c.execute(alter)
            finally:
                c.execute("DROP SCHEMA IF EXISTS reapl2 CASCADE")


if __name__ == "__main__":
    unittest.main()
