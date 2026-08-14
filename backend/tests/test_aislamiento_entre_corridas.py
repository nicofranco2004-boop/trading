"""Dos corridas de la suite a la vez no pueden pisarse.

EL SÍNTOMA, MEDIDO. La misma suite, en el mismo commit, daba **46, 47 o 49 fallas**
según qué otra cosa estuviera corriendo, con víctimas distintas cada vez. Nueve
corridas aisladas dieron 46 las nueve; alcanzaba con lanzar un segundo pytest
contra la misma base para que el número saltara a 49 y aparecieran fallas en tests
que no tenían nada que ver.

LA CAUSA. `_aislar_postgres` hace dos cosas destructivas al empezar cada módulo:
mata conexiones y dropea/crea esquemas. Las dos estaban sin firma:

  · `pg_terminate_backend` sobre **TODOS** los pids de la base → se llevaba puesta
    la conexión de la otra corrida en medio de un test. En el traceback quedaba
    `AdminShutdown: terminating connection due to administrator command`.
  · los nombres de esquema salían del nombre del módulo, o sea que **las dos
    corridas usaban el mismo** → una dropeaba el esquema que la otra estaba usando.

POR QUÉ IMPORTA MÁS QUE 3 FALLAS. Este proyecto se pasó tres sesiones logrando que
el número de la suite **signifique algo** (antes daba 77,4% y 71,9% en el mismo
commit según qué se trabara con qué). Un número que cambia según lo que corra en
otra terminal es el mismo problema disfrazado, y arruina la única herramienta que
tenemos para decir "esto no rompió nada".

EL ARREGLO: el pid va en el `application_name` de cada conexión Y adelante de cada
nombre de esquema. Cada corrida mata sólo lo suyo y toca sólo lo suyo.

Estos tests miran el conftest, no simulan dos corridas: levantar un segundo pytest
adentro de un test sería lento y frágil. Lo que fijan es que las dos firmas estén
puestas — que es lo que se puede perder en un refactor.
"""
import os
import re
import unittest

import main

CONFTEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conftest.py")


class LasDosFirmasEstanPuestasTest(unittest.TestCase):

    def setUp(self):
        self.src = open(CONFTEST, encoding="utf-8").read()

    def test_el_terminate_filtra_por_application_name(self):
        """Sin este filtro, cambiar de módulo mata las conexiones de cualquier
        otra corrida — y de cualquier otra cosa conectada a esa base."""
        m = re.search(r"pg_terminate_backend\(pid\).*?(?=\"\"\")", self.src, re.S)
        self.assertIsNotNone(m, "no se encontró el pg_terminate_backend")
        consulta = m.group(0)
        self.assertIn("application_name", consulta,
                      "el terminate no filtra por application_name: se lleva puesta "
                      "cualquier otra corrida contra la misma base")

    def test_el_application_name_lleva_el_pid(self):
        self.assertRegex(self.src, r"_APP_NAME\s*=\s*f?\"rendi_suite_\{os\.getpid\(\)\}\"")
        self.assertIn("application_name={_APP_NAME}", self.src,
                      "el DSN de los módulos no declara el application_name, así que "
                      "el filtro del terminate no encontraría nada que matar")

    def test_el_nombre_del_esquema_lleva_el_pid(self):
        """Si dos corridas comparten el nombre del esquema, una dropea el que la
        otra está usando. El filtro del terminate no alcanza para eso."""
        self.assertIn('f"t{os.getpid()}_"', self.src,
                      "los esquemas no llevan el pid: dos corridas simultáneas "
                      "comparten nombre y se dropean el esquema entre sí")

    def test_se_barren_los_esquemas_de_corridas_muertas(self):
        """El precio de meter el pid en el nombre: los esquemas de una corrida que
        murió a mitad ya no se pisan con los de nadie, así que hay que barrerlos."""
        self.assertIn("_barrer_esquemas_huerfanos", self.src)
        self.assertIn("os.kill(pid, 0)", self.src,
                      "el barrido tiene que confirmar que el proceso está MUERTO "
                      "antes de dropear: si no, borra los esquemas de la corrida "
                      "de al lado, que es el problema que veníamos a arreglar")


@unittest.skipUnless(getattr(main, "USANDO_PG", False),
                     "sólo tiene sentido en modo Postgres")
class LasFirmasLLEGANaLaBaseTest(unittest.TestCase):
    """Que estén escritas en el conftest no alcanza: tienen que llegar al motor."""

    def test_esta_conexion_declara_el_application_name_de_la_suite(self):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT current_setting('application_name')").fetchone()
        finally:
            conn.close()
        self.assertEqual(r[0], f"rendi_suite_{os.getpid()}")

    def test_el_esquema_activo_lleva_el_pid_de_esta_corrida(self):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT current_schema()").fetchone()
        finally:
            conn.close()
        self.assertTrue(str(r[0]).startswith(f"t{os.getpid()}_"),
                        f"el esquema activo es {r[0]!r} y no lleva el pid")


if __name__ == "__main__":
    unittest.main()
