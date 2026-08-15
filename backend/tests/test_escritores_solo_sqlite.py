"""Nadie puede abrir SQLite por la ventana sin que este test se entere.

EL PROBLEMA. Casi todo el backend habla con la base por `get_db()`, que es lo que
mira `DATABASE_URL` y decide el motor. Pero hay código que abre
`sqlite3.connect(...)` **directo**, salteando ese interruptor. Ese código, después
del pasaje a Postgres, **le sigue escribiendo al archivo SQLite congelado** — y no
falla: reporta éxito. Es el modo de falla más caro de este proyecto, con un agravante
propio: un job roto se ve, y éste se ve *sano*.

Los dos que importan se encontraron así:

  · `scripts/backup_db.py` — el backup nocturno. Seguiría guardando copias
    impecables de una base que ya no usa nadie.
  · `snapshots_job.py` — la foto diaria. La escribe en la base muerta, y la app —
    que lee de Postgres— se queda sin el dato de ayer: variación diaria, resúmenes
    mensuales, TWR e informes del asesor pierden la medición.

⚠️ **Y ESA ES LA LECCIÓN, más que los dos casos.** El primero se encontró a mano y
ahí se paró. El segundo apareció en una revisión adversarial, no buscándolo. **Se
encontró el patrón y no se barrió la categoría**, que es exactamente el error que
este proyecto ya pagó cinco veces. Este test barre la categoría entera con AST y
obliga a que cada sitio nuevo sea una decisión anotada, no un descuido.

CÓMO SE AGREGA UNO NUEVO: si de verdad hace falta abrir SQLite directo, sumalo a
`PERMITIDOS` con el motivo. Si no podés escribir el motivo, probablemente tenga que
usar `get_db()`.
"""
import ast
import os
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (archivo, función) → por qué está permitido abrir SQLite directo.
PERMITIDOS = {
    ("main.py", "get_db"):
        "ES el interruptor: la rama SQLite de get_db() tiene que abrir SQLite.",
    ("importing/recompute_backfill.py", "_clone_db"):
        "El ensayo por clon, marcado sólo-SQLite a propósito y con guard "
        "(dberrors.exigir_clon_soportado).",
    ("main.py", "_repair_snapshots_summary"):
        "Clon del ensayo, con guard.",
    ("main.py", "admin_fx_migrate_user"):
        "Clon del ensayo, con guard.",
    ("main.py", "admin_fx_migrate_batch"):
        "Clon del ensayo, con guard.",
    ("scripts/backup_db.py", "dump_sqlite_consistent"):
        "⚠️ PENDIENTE: es el backup nocturno y HOY es sólo-SQLite. Después del "
        "pasaje seguiría copiando el archivo congelado reportando éxito. Está "
        "anotado en el PLAN DE PASAJE (punto 0c) como algo a resolver ANTES de "
        "cortar — no como algo que esté bien.",
    ("snapshots_job.py", "run_daily_snapshot"):
        "⚠️ PENDIENTE: la foto diaria, también sólo-SQLite, con TRES disparadores "
        "(APScheduler 02:59, el cron externo /api/snapshots/run-cron y el botón "
        "admin). Mismo problema y mismo lugar en el plan.",
    ("seed.py", "seed"):
        "Script de desarrollo, no corre en producción.",
    ("scripts/mkschema.py", "<module>"):
        "GENERA `schema_pg.sql` leyendo el schema final de SQLite. Es sólo-SQLite "
        "por definición: su trabajo es traducir DE SQLite. Corre a mano, nunca en "
        "producción, y sobre un tempfile — no toca `/data/trading.db`.",
    ("scripts/base_sintetica.py", "_crear_esquema"):
        "Fabrica la base de PRUEBA con la forma de producción para cronometrar el "
        "copiador. Es sólo-SQLite por definición: el origen de la migración ES "
        "SQLite. No corre en producción y no toca `/data/trading.db`.",
    ("scripts/base_sintetica.py", "poblar"):
        "Ídem: la llena. Misma base desechable, mismo motivo.",
}


def _sitios():
    """[(archivo_relativo, función, línea)] de cada `sqlite3.connect(...)` directo."""
    fuera = []
    for base, _dirs, files in os.walk(RAIZ):
        if "tests" in base.split(os.sep) or "node_modules" in base:
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
            # mapa línea → función que la contiene (la más interna)
            duenio = {}
            for n in ast.walk(arbol):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fin = max((getattr(x, "lineno", 0) for x in ast.walk(n)), default=n.lineno)
                    for ln in range(n.lineno, fin + 1):
                        previo = duenio.get(ln)
                        if previo is None or n.lineno > previo[1]:
                            duenio[ln] = (n.name, n.lineno)
            for n in ast.walk(arbol):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "connect"
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id in ("sqlite3", "_sq")):
                    fn = duenio.get(n.lineno, ("<module>", 0))[0]
                    fuera.append((rel, fn, n.lineno))
    return fuera


class EscritoresSoloSqliteTest(unittest.TestCase):

    def test_no_hay_ningun_sitio_nuevo_que_abra_sqlite_directo(self):
        nuevos = [(a, f, l) for (a, f, l) in _sitios() if (a, f) not in PERMITIDOS]
        if nuevos:
            detalle = "\n".join(f"  {a}:{l}  en {f}()" for a, f, l in nuevos)
            self.fail(
                f"{len(nuevos)} sitio(s) abren SQLite directo, salteando get_db().\n"
                f"Después del pasaje a Postgres eso le escribe al archivo CONGELADO "
                f"y NO falla: reporta éxito.\n"
                f"Si es a propósito, agregalo a PERMITIDOS con el motivo escrito.\n"
                f"{detalle}")

    def test_la_lista_de_permitidos_no_tiene_muertos(self):
        """Un permiso que ya no corresponde a ningún sitio real es ruido: hace
        creer que se revisó algo que no existe."""
        reales = {(a, f) for (a, f, _l) in _sitios()}
        muertos = sorted(k for k in PERMITIDOS if k not in reales)
        self.assertEqual(muertos, [],
                         f"estos permisos ya no apuntan a nada: {muertos}. "
                         f"Sacalos de PERMITIDOS.")

    def test_los_dos_pendientes_siguen_marcados_como_pendientes(self):
        """Fija la deuda para que no se olvide.

        El día que `backup_db` y `snapshots_job` pasen por `get_db()`, estos dos
        permisos hay que sacarlos — y este test lo va a pedir solo (el de arriba
        falla si quedan permisos muertos).
        """
        for clave in [("scripts/backup_db.py", "dump_sqlite_consistent"),
                      ("snapshots_job.py", "run_daily_snapshot")]:
            self.assertIn("PENDIENTE", PERMITIDOS[clave],
                          f"{clave} dejó de estar marcado como deuda")

    def test_el_barrido_encuentra_uno_plantado(self):
        """El barrido tiene que fallar con código malo, si no no prueba nada."""
        import tempfile
        malo = "import sqlite3\ndef handler():\n    return sqlite3.connect('x.db')\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         dir=RAIZ, prefix="zz_sonda_") as f:
            f.write(malo)
            tmp = f.name
        try:
            rel = os.path.relpath(tmp, RAIZ)
            nuevos = [(a, fn) for (a, fn, _l) in _sitios() if a == rel]
            self.assertEqual(nuevos, [(rel, "handler")], nuevos)
        finally:
            os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
