"""Toda columna que apunta a otra tabla (REFERENCES) tiene un índice que empieza por ella.

EL PROBLEMA, medido el 06/11/2026 sobre la copia de producción del 04/11 cargada en
Postgres. `import_normalized_tx.raw_row_id` e `import_op_links.raw_row_id` apuntan a
`import_raw_rows` con ON DELETE CASCADE. Cuando se borra una fila cruda, la base
tiene que buscar las que la nombran para borrarlas también, y sin índice esa
búsqueda recorre la tabla ENTERA —la de todos los usuarios, 850.000 filas— una vez
por cada fila que se borra:

    borrar 200 filas crudas, sin índice:    16 s  (15,8 en esas dos búsquedas)
    borrar 5.000 filas crudas, con índice:  0,03 s

Lo pagaba todo lo que borra filas crudas: «Empezar de cero» (885.000 filas del
usuario más grande = medio día de búsquedas), el reset de admin, borrar la cuenta y
la limpieza de borradores de import vencidos, que corre adentro de CADA vista previa
de CSV (`importing/pipeline.cleanup_stale_previews`).

POR QUÉ NADIE LO VIO. En SQLite la referencia se cumple igual (`PRAGMA
foreign_keys=ON`), pero el borrado grande estaba pausado por otra razón —el
escritor único— y el pasaje a Postgres tradujo las referencias sin una regla que
dijera «cada una con su índice». La regla es ésta.

Mira el MISMO esquema que traduce `scripts/mkschema.py`: el que arma `init_db()` en
una base nueva MÁS las tablas que `pricing/fci.py:ensure_tables()` crea en caliente.
`schema_pg.sql` sale de ahí (y `test_schema_pg_del_generador` traba que no se separen),
así que lo que vale acá vale en Postgres. Y para que esta receta no se quede atrás si
el generador suma otra fuente de tablas, `test_mira_las_mismas_tablas_que_el_generador`
compara las tablas de acá con las de `schema_pg.sql` (auditoría del 07/11: una tabla de
FCI con una referencia sin índice pasaba sin que esto la viera).

Qué cuenta como índice de una referencia: uno COMPLETO (no parcial: un `WHERE` deja
filas afuera y Postgres no lo usa para buscar las hijas) cuyas primeras columnas son
las de la referencia; la clave primaria también. Una referencia de varias columnas
necesita un índice que las tenga a todas adelante, no uno por columna.

Si da rojo: agregá el `CREATE INDEX IF NOT EXISTS` al lado del CREATE TABLE (o
DESPUÉS del ALTER que crea la columna, nunca antes: project_migration_index_order) y
regenerá `schema_pg.sql` con `python3 scripts/mkschema.py`.

Corre con: cd backend && python3 -m pytest tests/test_referencias_con_indice.py
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)


# La receta de `scripts/mkschema.py` (líneas «import main» y «_fci.ensure_tables»).
_ARMAR_ESQUEMA = (
    "import sqlite3, main, pricing.fci as f\n"
    "c = sqlite3.connect(main.DB_PATH); f.ensure_tables(c); c.commit(); c.close()\n"
)


def _esquema_nuevo(ruta: str) -> None:
    """Arma el esquema en un SQLite vacío en otro proceso: así no importa con qué
    motor corre la suite (la de Postgres trae DATABASE_URL)."""
    entorno = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "DB_PATH")}
    entorno["DB_PATH"] = ruta
    entorno.setdefault("SECRET_KEY", "x")
    r = subprocess.run([sys.executable, "-c", _ARMAR_ESQUEMA], cwd=BACKEND, env=entorno,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]


def _indices_completos(conn, t) -> list:
    """Las columnas, en orden, de cada índice COMPLETO de la tabla (la clave
    primaria incluida). Los parciales no cuentan."""
    pk = sorted((r[5], r[1]) for r in conn.execute(f'PRAGMA table_info("{t}")') if r[5])
    indices = [[c for _, c in pk]] if pk else []
    for ix in conn.execute(f'PRAGMA index_list("{t}")').fetchall():
        if ix[4]:                      # partial: tiene WHERE
            continue
        indices.append([r[2] for r in conn.execute(f'PRAGMA index_info("{ix[1]}")')])
    return indices


def referencias_sin_indice(conn) -> list:
    """[(tabla, columnas, tabla_apuntada)] de cada referencia sin índice propio."""
    faltan = []
    tablas = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tablas:
        indices = _indices_completos(conn, t)
        refs = {}
        for fk in conn.execute(f'PRAGMA foreign_key_list("{t}")').fetchall():
            refs.setdefault(fk[0], (fk[2], []))[1].append((fk[1], fk[3]))
        for padre, cols in refs.values():
            cols = [c for _, c in sorted(cols)]
            if not any(set(ix[:len(cols)]) == set(cols) for ix in indices):
                faltan.append((t, ",".join(cols), padre))
    return sorted(set(faltan))


class ReferenciasConIndice(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ruta = os.path.join(cls._tmp.name, "nueva.db")
        _esquema_nuevo(cls.ruta)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_toda_referencia_tiene_su_indice(self):
        conn = sqlite3.connect(self.ruta)
        try:
            faltan = referencias_sin_indice(conn)
        finally:
            conn.close()
        self.assertEqual(faltan, [], "Referencias sin índice (tabla, columna, apunta a): "
                         f"{faltan}. Ver el docstring de este archivo.")

    def test_el_detector_ve_una_referencia_sin_indice(self):
        """El instrumento primero: sobre una tabla plantada a propósito, la tiene que ver."""
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript("""
                CREATE TABLE padre (id INTEGER PRIMARY KEY);
                CREATE TABLE hija (id INTEGER PRIMARY KEY,
                                   padre_id INTEGER REFERENCES padre(id) ON DELETE CASCADE);
            """)
            self.assertEqual(referencias_sin_indice(conn), [("hija", "padre_id", "padre")])
            # Un índice PARCIAL no alcanza: Postgres no lo usa para buscar las hijas.
            conn.execute("CREATE INDEX ix_parcial ON hija(padre_id) WHERE id > 10")
            self.assertEqual(referencias_sin_indice(conn), [("hija", "padre_id", "padre")])
            # Uno de expresión tampoco.
            conn.execute("CREATE INDEX ix_expr ON hija(padre_id + 0)")
            self.assertEqual(referencias_sin_indice(conn), [("hija", "padre_id", "padre")])
            conn.execute("CREATE INDEX ix_hija_padre ON hija(padre_id)")
            self.assertEqual(referencias_sin_indice(conn), [])
        finally:
            conn.close()

    def test_el_detector_entiende_las_referencias_de_varias_columnas(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript("""
                CREATE TABLE padre (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
                CREATE TABLE hija (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER,
                                   FOREIGN KEY (a, b) REFERENCES padre(a, b));
                CREATE INDEX ix_a ON hija(a);
                CREATE INDEX ix_b ON hija(b);
            """)
            # Uno por columna no sirve: la búsqueda va por las dos juntas.
            self.assertEqual(referencias_sin_indice(conn), [("hija", "a,b", "padre")])
            # Las dos adelante, en cualquier orden, sí.
            conn.execute("CREATE INDEX ix_ba ON hija(b, a, id)")
            self.assertEqual(referencias_sin_indice(conn), [])
        finally:
            conn.close()

    def test_mira_las_mismas_tablas_que_el_generador(self):
        """Si `scripts/mkschema.py` suma otra fuente de tablas (como ya pasó con las de
        FCI), esta prueba tiene que mirarla también: si no, una referencia ahí pasa sin
        que nadie la vea."""
        import re
        sql = open(os.path.join(BACKEND, "schema_pg.sql"), encoding="utf-8").read()
        del_generador = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \(", sql))
        conn = sqlite3.connect(self.ruta)
        try:
            de_aca = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        finally:
            conn.close()
        self.assertEqual(sorted(del_generador - de_aca), [],
                         "tablas de schema_pg.sql que esta prueba no arma")
        self.assertIn("fci_catalog", de_aca)

    def test_las_dos_de_las_filas_crudas_estan(self):
        """Las dos que costaban 16 s cada 200 filas, nombradas: si alguien relaja el
        detector, éstas siguen trabadas."""
        conn = sqlite3.connect(self.ruta)
        try:
            for t in ("import_normalized_tx", "import_op_links"):
                self.assertTrue(any(ix[:1] == ["raw_row_id"] for ix in _indices_completos(conn, t)), t)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
