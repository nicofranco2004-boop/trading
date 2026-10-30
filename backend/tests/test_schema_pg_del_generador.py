"""`schema_pg.sql` es exactamente lo que escribe el generador.

`scripts/mkschema.py` arma el esquema de Postgres a partir del de SQLite y
REESCRIBE `schema_pg.sql` entero, sin preguntar. Así que una edición a mano allá
vive hasta la próxima vez que alguien lo corra, y lo que el generador haga mal
llega a Postgres el día que se lo corra. Las dos cosas pasaban a la vez
(auditoría C, hallazgo 5, 29/10): la tabla `resumen_semanal_prefs` se escribió a
mano, y corriendo el generador su `user_id` pasaba de «el número de la persona»
a «un número que la base inventa sola». No era culpa de esa tabla: el generador
le hacía lo mismo a otras cuatro que ya estaban (`market_brief_prefs`,
`mtm_huella`, `advisor_alerts`, `advisor_profile`) y daba vuelta el orden de la
clave de `uso_diario`.

La causa de proceso: nada comparaba el archivo con lo que sale del generador, así
que podían separarse sin que nadie se enterara. Este test es esa comparación,
byte a byte. Si da rojo:
  · si cambiaste main.py (una tabla, una columna, un índice) → corré
    `python3 scripts/mkschema.py` desde backend/ y commiteá el archivo;
  · si lo que querés que diga Postgres NO sale del generador → arreglá el
    generador, no el archivo.

Corre con: cd backend && python3 -m pytest tests/test_schema_pg_del_generador.py
"""
import difflib
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
SCHEMA_PG = os.path.join(BACKEND, "schema_pg.sql")
GENERADOR = os.path.join(BACKEND, "scripts", "mkschema.py")


class SchemaPgDelGenerador(unittest.TestCase):

    def test_el_archivo_es_lo_que_escribe_el_generador(self):
        with tempfile.TemporaryDirectory() as tmp:
            salida = os.path.join(tmp, "schema_pg.sql")
            entorno = {k: v for k, v in os.environ.items()
                       if k not in ("DATABASE_URL", "DB_PATH")}   # SQLite propio, siempre
            r = subprocess.run([sys.executable, GENERADOR, salida], cwd=BACKEND,
                               env=entorno, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            generado = open(salida, encoding="utf-8").read()
        commiteado = open(SCHEMA_PG, encoding="utf-8").read()
        if generado != commiteado:
            diff = "".join(list(difflib.unified_diff(
                commiteado.splitlines(True), generado.splitlines(True),
                "schema_pg.sql (commiteado)", "lo que escribe mkschema.py", n=1))[:80])
            self.fail("schema_pg.sql no es lo que escribe el generador:\n" + diff)


if __name__ == "__main__":
    unittest.main()
