"""La suite se niega a arrancar contra una base con datos de personas
(`tests/_candado_base_con_datos.py`). Por el camino real: un `pytest` de verdad,
en otro proceso, con `DATABASE_URL` apuntando a un esquema con UNA fila en
`users`. Tiene que cortar antes de cargar `main` —o sea, sin que el arranque
toque esa base— y decir por qué.
"""
import os
import subprocess
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pgsesion  # noqa: E402
from tests._candado_base_con_datos import filas_de_personas  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSN_CRUDO = os.environ.get("DATABASE_URL", "")


def _dsn_con_esquema(esquema: str) -> str:
    # `-c search_path=…` CON espacio, armado por make_conninfo como en conftest.
    # Postgres acepta también `-csearch_path=…` pegado, pero el pooler de Supabase
    # no: lo ignora y la conexión cae en `public` (medido 02/11/2026). Así esta
    # prueba daba rojo contra Supabase con el candado funcionando bien.
    from psycopg.conninfo import make_conninfo
    return make_conninfo(DSN_CRUDO, options=f"-c search_path={esquema}")


@unittest.skipUnless(DSN_CRUDO, "el candado es para Postgres (DATABASE_URL)")
class LaSuiteNoArrancaContraUnaBaseConDatos(unittest.TestCase):

    def setUp(self):
        self.esquema = f"candado_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        self.adm = pgsesion.conectar(DSN_CRUDO, autocommit=True)
        self.adm.execute(f'CREATE SCHEMA "{self.esquema}"')
        self.adm.execute(f'CREATE TABLE "{self.esquema}".users (id bigint, email text)')
        self.dsn = _dsn_con_esquema(self.esquema)

    def tearDown(self):
        self.adm.execute(f'DROP SCHEMA "{self.esquema}" CASCADE')
        self.adm.close()

    def _tablas(self):
        return sorted(r[0] for r in self.adm.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
            (self.esquema,)).fetchall())

    def test_vacia_deja_pasar(self):
        self.assertEqual(filas_de_personas(self.dsn), [])

    def test_con_una_persona_corta_antes_de_cargar_main(self):
        self.adm.execute(f'INSERT INTO "{self.esquema}".users VALUES (1, %s)',
                         ("alguien@ejemplo.com",))
        self.assertEqual(filas_de_personas(self.dsn), [f"{self.esquema}.users"])
        env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
        env["DATABASE_URL"] = self.dsn
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
             "tests/test_limpieza_borra_hijas_primero.py"],
            cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)
        salida = p.stdout + p.stderr
        print(f"\n>>> pytest contra una base con una persona: código {p.returncode}\n"
              + "\n".join(l for l in salida.splitlines() if "SUITE" in l or "datos" in l))
        self.assertEqual(p.returncode, 3, salida[-2000:])
        self.assertIn("LA SUITE NO ARRANCA", salida)
        self.assertIn(f"{self.esquema}.users", salida)
        # El arranque no corrió: no creó ni una tabla al lado de `users`.
        self.assertEqual(self._tablas(), ["users"])


if __name__ == "__main__":
    unittest.main()
