"""Una conexión a Postgres sin ajustar lee floats redondeados, y no da error.

EL PROBLEMA, medido contra el Supabase real. `extra_float_digits` vale **0** en los
dos poolers de Supabase (y **1** en un Postgres normal, que es el default desde PG
12). Con 0, Postgres imprime los `double precision` con 15 dígitos significativos —
que **no alcanzan** para reconstruir un `double`. El cliente parsea ese texto y
obtiene otro número.

Sobre 350 filas de `operations.pnl_usd` recién copiadas a Supabase:

    filas cuyos BITS GUARDADOS difieren del origen:   0 de 350
    filas cuya LECTURA difiere del origen:           73 de 350
        y con extra_float_digits = 3:                 0 de 350

El dato viajó perfecto; el que mentía era el lector.

⚠️ **POR QUÉ NO ALCANZA CON ARREGLAR LA VERIFICACIÓN.** Mientras sea sólo lectura,
1e-14 es invisible. Pero el rebuild hace **leer → modificar → escribir** sobre estos
mismos campos: si lee `31.450000000000003`, recibe `31.45` y lo reescribe, **ahí los
bits en disco SÍ cambian**, y desde ese momento la verificación compara bien y no ve
nada porque los dos lados coinciden en el valor redondeado. De invisible a real en
un paso.

POR ESO EL BARRIDO ES DE LA CATEGORÍA Y NO DE UN SITIO: cualquier
`psycopg.connect()` que no pase por `pgsesion.conectar()` es una conexión que lee
distinto. No falla, no avisa: devuelve otro número.
"""
import ast
import os
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (archivo, función) → por qué puede abrir una conexión sin pasar por pgsesion.
PERMITIDOS = {
    ("pgsesion.py", "conectar"):
        "ES la puerta: adentro de `conectar()` está el `psycopg.connect` que todos "
        "los demás tienen que usar.",
}


def _sitios():
    """[(archivo, función, línea)] de cada `psycopg.connect(...)` directo.

    No mira `tests/`: un test que abre una conexión cruda a propósito —para
    verificar por afuera, sin los ajustes— es legítimo y es lo que hace el test de
    abajo. Lo que este barrido protege es el código que corre en producción.
    """
    fuera = []
    for base, _dirs, files in os.walk(RAIZ):
        partes = base.split(os.sep)
        if "tests" in partes or "node_modules" in base or "venv" in base:
            continue
        for nombre in files:
            if not nombre.endswith(".py") or nombre.startswith("test_"):
                continue
            ruta = os.path.join(base, nombre)
            rel = os.path.relpath(ruta, RAIZ)
            try:
                arbol = ast.parse(open(ruta, encoding="utf-8").read())
            except SyntaxError:
                continue
            duenio = {}
            for n in ast.walk(arbol):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fin = max((getattr(x, "lineno", 0) for x in ast.walk(n)),
                              default=n.lineno)
                    for ln in range(n.lineno, fin + 1):
                        previo = duenio.get(ln)
                        if previo is None or n.lineno > previo[1]:
                            duenio[ln] = (n.name, n.lineno)
            for n in ast.walk(arbol):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "connect"
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "psycopg"):
                    fn = duenio.get(n.lineno, ("<module>", 0))[0]
                    fuera.append((rel, fn, n.lineno))
    return fuera


class TodaConexionPasaPorPgsesionTest(unittest.TestCase):

    def test_ningun_sitio_de_produccion_abre_psycopg_por_su_cuenta(self):
        nuevos = [(a, f, l) for (a, f, l) in _sitios() if (a, f) not in PERMITIDOS]
        if nuevos:
            detalle = "\n".join(f"  {a}:{l}  en {f}()" for a, f, l in nuevos)
            self.fail(
                f"{len(nuevos)} sitio(s) abren psycopg sin pasar por "
                f"`pgsesion.conectar()`.\n"
                f"Una conexión sin ajustar lee los `double precision` redondeados a "
                f"15 dígitos: NO falla, devuelve otro número. Y si el rebuild "
                f"reescribe lo que leyó, la diferencia se vuelve real en disco.\n"
                f"{detalle}")

    def test_la_lista_de_permitidos_no_tiene_muertos(self):
        reales = {(a, f) for (a, f, _l) in _sitios()}
        muertos = sorted(k for k in PERMITIDOS if k not in reales)
        self.assertEqual(muertos, [], f"permisos que no apuntan a nada: {muertos}")

    def test_el_barrido_encuentra_uno_plantado(self):
        """El barrido tiene que fallar con código malo, si no no prueba nada."""
        import tempfile
        malo = ("import psycopg\n"
                "def handler():\n"
                "    return psycopg.connect('postgresql://x')\n")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         dir=RAIZ, prefix="zz_sonda_") as f:
            f.write(malo)
            tmp = f.name
        try:
            rel = os.path.relpath(tmp, RAIZ)
            self.assertEqual([(a, fn) for (a, fn, _l) in _sitios() if a == rel],
                             [(rel, "handler")])
        finally:
            os.unlink(tmp)

    def test_los_ajustes_incluyen_extra_float_digits(self):
        """Fija el ajuste concreto: si alguien vacía la tupla, el barrido de arriba
        sigue verde (todos pasan por la puerta) pero la puerta no ajusta nada."""
        import sys
        sys.path.insert(0, RAIZ)
        import pgsesion
        self.assertTrue(any("extra_float_digits" in s for s in pgsesion.AJUSTES_DE_SESION),
                        f"se perdió el ajuste: {pgsesion.AJUSTES_DE_SESION}")


@unittest.skipUnless(os.environ.get("PG_DSN_VERIF"),
                     "necesita PG_DSN_VERIF (una base Postgres APARTE de la de la suite)")
class ElFloatVuelveExactoTest(unittest.TestCase):
    """La prueba de comportamiento: un float que necesita 17 dígitos, ida y vuelta.

    El test estructural de arriba mira quién abre la conexión; éste mira si el
    número vuelve igual. Los dos hacen falta: se puede pasar por la puerta correcta
    y que la puerta no ajuste nada.
    """

    def setUp(self):
        import sys
        sys.path.insert(0, RAIZ)
        import psycopg
        import pgsesion
        self.psycopg = psycopg
        self.pgsesion = pgsesion
        self.dsn = os.environ["PG_DSN_VERIF"]

    # Un valor que NO se puede representar con 15 dígitos significativos: hace
    # falta el 17º para volver al mismo double. Es el caso real que apareció en
    # `operations.pnl_usd` (guardado 31.450000000000003, leído 31.45).
    VALOR = 31.450000000000003

    def _con_esquema(self, conn):
        conn.execute("DROP SCHEMA IF EXISTS flt CASCADE")
        conn.execute("CREATE SCHEMA flt")
        conn.execute("SET search_path = flt")
        conn.execute("CREATE TABLE t (id bigint, v double precision)")
        conn.execute("INSERT INTO t VALUES (1, %s)", (self.VALOR,))

    def test_una_conexion_AJUSTADA_devuelve_el_float_exacto(self):
        with self.pgsesion.conectar(self.dsn, autocommit=True) as c:
            try:
                self._con_esquema(c)
                leido = c.execute("SELECT v FROM t").fetchone()[0]
                self.assertEqual(leido, self.VALOR,
                                 f"leyó {leido!r} donde había {self.VALOR!r}")
                self.assertEqual(repr(leido), repr(self.VALOR))
            finally:
                c.execute("DROP SCHEMA IF EXISTS flt CASCADE")

    def test_y_los_BITS_son_los_mismos_no_sólo_el_número(self):
        """La comparación que de verdad distingue "el dato está bien" de "el lector
        miente": si se comparan lecturas, las dos cosas se ven igual."""
        import struct
        with self.pgsesion.conectar(self.dsn, autocommit=True) as c:
            try:
                self._con_esquema(c)
                hexd = c.execute("SELECT encode(float8send(v),'hex') FROM t").fetchone()[0]
                self.assertEqual(hexd, struct.pack(">d", self.VALOR).hex())
            finally:
                c.execute("DROP SCHEMA IF EXISTS flt CASCADE")

    def test_el_ajuste_llega_a_la_sesion(self):
        with self.pgsesion.conectar(self.dsn, autocommit=True) as c:
            self.assertEqual(c.execute("SHOW extra_float_digits").fetchone()[0], "3")


if __name__ == "__main__":
    unittest.main()
