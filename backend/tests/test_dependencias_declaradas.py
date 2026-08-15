"""Ningún código de producción puede importar un paquete que nadie declaró.

EL PROBLEMA, y no es teórico: `pgshim.py`, `dberrors.py` y `main.py` importan
`psycopg`, y **`psycopg` no estaba en `requirements.txt`**. O sea que el paso 10 del
plan de pasaje —"prender `DATABASE_URL` y reiniciar"— era imposible: `init_db()`
corre al importar el módulo, uvicorn no levanta, y Railway queda en crash-loop. La
app no contesta ni `/api/health`.

⚠️ **Y ES INVISIBLE HASTA EL PEOR MOMENTO.** `get_db()` importa `pgshim` de forma
perezosa y **sólo si `USANDO_PG`** (`main.py:344-347`), así que mergear el código de
Postgres sin la variable deploya verde y el faltante no se nota. Se nota el domingo,
con la app abajo y el reloj corriendo.

BUSCANDO LA CATEGORÍA Y NO EL PAQUETE, apareció el segundo caso: **`httpx`**. Lo
importan `billing/emails.py`, `billing/mercadopago.py` y `billing/rebill.py` —
producción, plata de verdad— y andaba **de casualidad**, porque lo arrastraba
`anthropic` como dependencia propia. El día que anthropic cambie de cliente HTTP,
los mails de billing y los webhooks de pago dejan de andar sin que nadie haya
tocado eso.

QUÉ MARCA: un `import` de un paquete de TERCEROS, en un archivo que NO es de tests,
que no aparece en `requirements.txt`.

CÓMO SE DISTINGUE TERCEROS DE LA BIBLIOTECA ESTÁNDAR: resolviendo cada módulo a su
ruta real y mirando si vive adentro de la stdlib. **No con una lista escrita a
mano**, y tampoco con `sys.stdlib_module_names` — que no existe en Python 3.9 y
devuelve vacío en silencio, con lo cual TODO parece de terceros. (Pasó: el primer
barrido dio 48 falsos positivos por eso. Un detector que denuncia todo es ruido que
se aprende a ignorar.)
"""
import ast
import importlib.util
import os
import sys
import sysconfig
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(RAIZ, "requirements.txt")
_STDLIB = sysconfig.get_paths()["stdlib"]

# paquete → por qué se importa en producción sin estar en requirements.txt.
# Si no podés escribir el motivo, probablemente haya que declararlo.
PERMITIDOS = {
    "starlette":
        "`main.py` lo importa directo, pero es la base sobre la que ESTÁ CONSTRUIDO "
        "FastAPI: no es una dependencia que pueda desaparecer sin que desaparezca "
        "FastAPI. Y `fastapi==0.115.0` pinnea el rango de starlette que acepta, así "
        "que declararlo acá con otra versión rompería la resolución en vez de "
        "arreglar algo. Es el caso donde declarar es PEOR.",
}

# Los tests pueden usar lo que quieran: no se deployan. `pytest`, `numpy` y
# `pandas` viven acá. ⚠️ Que no haya `requirements-dev.txt` es un hueco real —
# quien clone el repo no sabe qué instalar para correr la suite— pero es otra
# decisión y no la que este test vigila.
_PREFIJOS_DE_TESTS = ("tests/", "scripts/test_")


def _es_stdlib(modulo: str) -> bool:
    if modulo in sys.builtin_module_names:
        return True
    try:
        spec = importlib.util.find_spec(modulo)
    except (ImportError, ValueError, ModuleNotFoundError):
        return False
    if spec is None:
        return False
    if not spec.origin:                       # namespace packages
        return False
    return spec.origin.startswith(_STDLIB) and "site-packages" not in spec.origin


def _modulos_locales() -> set:
    """Todo lo que es del propio backend: archivos .py y paquetes."""
    out = set()
    for base, dirs, files in os.walk(RAIZ):
        if any(x in base for x in ("node_modules", ".git", "venv")):
            continue
        for f in files:
            if f.endswith(".py"):
                out.add(f[:-3])
        if "__init__.py" in files:
            out.add(os.path.basename(base))
        out.update(dirs)
    return out


def imports_de_terceros():
    """{paquete: {archivos}} de lo importado por código que NO es de tests."""
    locales = _modulos_locales()
    out = {}
    for base, dirs, files in os.walk(RAIZ):
        if any(x in base for x in ("node_modules", ".git", "venv")):
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(base, f), RAIZ)
            if rel.startswith(_PREFIJOS_DE_TESTS) or f.startswith("test_"):
                continue
            try:
                arbol = ast.parse(open(os.path.join(base, f), encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for n in ast.walk(arbol):
                mods = []
                if isinstance(n, ast.Import):
                    mods = [a.name.split(".")[0] for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    mods = [n.module.split(".")[0]]
                for m in mods:
                    if m in locales or m.startswith("_") or _es_stdlib(m):
                        continue
                    out.setdefault(m, set()).add(rel)
    return out


def no_declarados():
    req = open(REQUIREMENTS, encoding="utf-8").read().lower()
    # Se mira sólo lo que NO es comentario: un paquete nombrado en un comentario
    # explicando por qué NO está no puede contar como declarado.
    lineas = [l.split("#")[0].strip() for l in req.splitlines()]
    declarado = "\n".join(l for l in lineas if l)
    return {m: v for m, v in imports_de_terceros().items()
            if m.lower() not in declarado and m not in PERMITIDOS}


class LasDependenciasEstanDeclaradasTest(unittest.TestCase):

    def test_ningun_import_de_produccion_queda_sin_declarar(self):
        malos = no_declarados()
        if malos:
            detalle = "\n".join(
                f"  {m}: importado por {sorted(v)[:3]}" for m, v in sorted(malos.items()))
            self.fail(
                f"{len(malos)} paquete(s) que usa el código de producción no están "
                f"en requirements.txt.\n"
                f"Si hoy funcionan es porque otra dependencia los arrastra — y eso "
                f"se corta el día que esa otra dependencia cambie, sin que nadie "
                f"haya tocado el código que se rompe.\n{detalle}")

    def test_psycopg_esta_declarado_y_PINNEADO(self):
        """El que faltaba. Va pinneado porque está en el camino crítico: es lo
        único que separa 'prender DATABASE_URL' de un crash-loop."""
        req = open(REQUIREMENTS, encoding="utf-8").read()
        lineas = [l.split("#")[0].strip() for l in req.splitlines()]
        psy = [l for l in lineas if l.startswith("psycopg")]
        self.assertEqual(len(psy), 1, f"esperaba una línea de psycopg, hay {psy}")
        self.assertIn("==", psy[0], f"psycopg tiene que ir pinneado: {psy[0]!r}")
        self.assertIn("[binary]", psy[0],
                      "tiene que ser psycopg[binary]: trae libpq adentro del wheel, "
                      "y en Railway no está garantizado que el sistema lo tenga")

    def test_la_lista_de_permitidos_no_tiene_muertos(self):
        """Un permiso que ya no apunta a nada hace creer que se revisó algo que no
        existe. Misma regla que los otros dos barridos."""
        usados = set(imports_de_terceros())
        muertos = sorted(k for k in PERMITIDOS if k not in usados)
        self.assertEqual(muertos, [], f"estos permisos no apuntan a nada: {muertos}")

    def test_el_detector_agarra_uno_plantado(self):
        """Sin esto el test de arriba no prueba nada: podría estar mirando mal."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=RAIZ,
                                         prefix="zz_sonda_") as f:
            f.write("import paquete_que_no_existe_ni_en_pypi\n")
            tmp = f.name
        try:
            self.assertIn("paquete_que_no_existe_ni_en_pypi", no_declarados())
        finally:
            os.unlink(tmp)

    def test_el_detector_NO_marca_la_biblioteca_estandar(self):
        """La contracara, y sin ella el detector sería ruido.

        Es el modo de falla que este archivo ya tuvo: `sys.stdlib_module_names` no
        existe en Python 3.9 y devuelve vacío EN SILENCIO, con lo cual `json`,
        `sqlite3` y `datetime` pasaban por dependencias sin declarar. 48 falsos
        positivos.
        """
        for m in ("json", "sqlite3", "datetime", "hashlib", "argparse", "decimal"):
            self.assertTrue(_es_stdlib(m), f"{m} es stdlib y el detector no lo ve")
        self.assertNotIn("json", no_declarados())

    def test_el_detector_NO_mira_los_tests(self):
        """`pytest`, `numpy` y `pandas` sólo viven en tests y no se deployan.
        Marcarlos sería ruido — el riesgo es lo que corre en producción."""
        self.assertNotIn("pytest", no_declarados())


if __name__ == "__main__":
    unittest.main()
