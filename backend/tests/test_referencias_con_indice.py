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

Mira el esquema de SQLite que arma `init_db()` en una base nueva: `schema_pg.sql`
sale de ahí (`scripts/mkschema.py`, y `test_schema_pg_del_generador` traba que no se
separen), así que lo que vale acá vale en Postgres. La clave primaria cuenta como
índice.

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


def _esquema_nuevo(ruta: str) -> None:
    """Corre `init_db()` sobre un SQLite vacío en otro proceso: así no importa con
    qué motor corre la suite (la de Postgres trae DATABASE_URL)."""
    entorno = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "DB_PATH")}
    entorno["DB_PATH"] = ruta
    entorno.setdefault("SECRET_KEY", "x")
    r = subprocess.run([sys.executable, "-c", "import main"], cwd=BACKEND, env=entorno,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]


def referencias_sin_indice(conn) -> list:
    """[(tabla, columna, tabla_apuntada)] de cada referencia sin índice propio."""
    faltan = []
    tablas = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tablas:
        primeras = {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")') if r[5] == 1}
        for ix in conn.execute(f'PRAGMA index_list("{t}")').fetchall():
            cols = [r[2] for r in conn.execute(f'PRAGMA index_info("{ix[1]}")')]
            if cols:
                primeras.add(cols[0])
        for fk in conn.execute(f'PRAGMA foreign_key_list("{t}")').fetchall():
            if fk[3] not in primeras:
                faltan.append((t, fk[3], fk[2]))
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
            conn.execute("CREATE INDEX ix_hija_padre ON hija(padre_id)")
            self.assertEqual(referencias_sin_indice(conn), [])
        finally:
            conn.close()

    def test_las_dos_de_las_filas_crudas_estan(self):
        """Las dos que costaban 16 s cada 200 filas, nombradas: si alguien relaja el
        detector, éstas siguen trabadas."""
        conn = sqlite3.connect(self.ruta)
        try:
            for t in ("import_normalized_tx", "import_op_links"):
                primeras = set()
                for ix in conn.execute(f'PRAGMA index_list("{t}")').fetchall():
                    cols = [r[2] for r in conn.execute(f'PRAGMA index_info("{ix[1]}")')]
                    if cols:
                        primeras.add(cols[0])
                self.assertIn("raw_row_id", primeras, t)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
