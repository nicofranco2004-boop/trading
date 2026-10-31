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
    ("scripts/fixture_compra_y_mantiene_ars.py", "copiar_historia_del_dolar"):
        "Sólo LEE `fx_rates_daily` de una copia descargada de la base (un archivo, no la "
        "base de la app) para armar la cuenta de prueba; lo que escribe va por get_db().",
    ("importing/recompute_backfill.py", "_clone_db"):
        "El ensayo por clon, marcado sólo-SQLite a propósito y con guard "
        "(dberrors.exigir_clon_soportado).",
    ("main.py", "_repair_snapshots_summary"):
        "Clon del ensayo, con guard.",
    ("main.py", "admin_fx_migrate_user"):
        "Clon del ensayo, con guard.",
    ("main.py", "admin_fx_migrate_batch"):
        "Clon del ensayo, con guard.",
    ("scripts/seed_cuenta_unificada.py", "<module>"):
        "Fixture de DESARROLLO LOCAL: siembra el usuario de prueba de la cuenta "
        "unificada (padre ARS + sub-broker '· USD', con el mismo ticker en las dos "
        "patas, que no existe en ninguna base real) para poder mirar la pantalla a "
        "mano. Nunca corre en producción ni en CI: se invoca a mano contra "
        "backend/trading.db. Si algún día hace falta en Postgres, tiene que pasar "
        "por get_db() — los placeholders '?' tampoco sobrevivirían al cambio.",
    ("scripts/backup_db.py", "dump_sqlite_consistent"):
        "El backup nocturno CUANDO LA APP USA SQLITE. Con DATABASE_URL, `run_backup` "
        "hace el volcado de Postgres (`dump_postgres`) y no llama a esto; si el "
        "volcado falla, NO cae acá (31/10/2026). Lo prueba por el camino real "
        "tests/test_backup_postgres.py, recuperación incluida.",
    ("snapshots_job.py", "run_daily_snapshot"):
        "Sólo para los tests que arman su propia base SQLite y pasan `db_path`. "
        "Los TRES disparadores de producción (APScheduler 02:59, el cron externo "
        "/api/snapshots/run-cron y el botón admin) pasan `abrir=get_db` desde el "
        "29/10/2026 y la foto se guarda en la base que lee la app — lo prueba "
        "tests/test_foto_diaria_en_la_base_de_la_app.py por la puerta real.",
    ("seed.py", "seed"):
        "Script de desarrollo, no corre en producción.",
    ("scripts/escala_foto_bonos.py", "<module>"):
        "Herramienta de MEDICIÓN, no código de la app: abre una COPIA de prod en "
        "`immutable=1` para contrastar la escala (nominal vs residual) que reporta "
        "cada broker en su foto de tenencia. No corre en el servidor.",
    ("scripts/backtest_dividendos.py", "<module>"):
        "Herramienta de MEDICIÓN, no código de la app: abre una COPIA de prod en "
        "`immutable=1` para comparar el dividendo que calcula la bandeja contra el "
        "que pagó cada broker (de ahí salen las REGLAS de backend/dividendos.py). "
        "No corre en el servidor.",
    ("scripts/diag_brokers_moneda.py", "main"):
        "Herramienta de MEDICIÓN, no código de la app: abre una COPIA de prod en "
        "`immutable=1` para contar las cuentas con pesos guardados en un broker en "
        "dólares (AUDIT_plantilla_rendi_2026-10-27.md, PL1). No corre en el servidor.",
    ("scripts/verificar_proyeccion.py", "<module>"):
        "Herramienta de MEDICIÓN, no código de la app: abre una COPIA de la base "
        "de producción en modo `immutable=1` (sólo lectura, físicamente incapaz "
        "de escribir) para contrastar la proyección hacia atrás contra "
        "`snapshots.holdings_json` del cron. No corre en el servidor y no toca "
        "la base viva.",
    ("scripts/copiar_a_postgres.py", "abrir_origen"):
        "ES el copiador: su trabajo es leer la SQLite para migrarla a Postgres, "
        "así que abrirla directo no es saltearse el interruptor, es el punto. Y la "
        "abre **sólo lectura** (`mode=ro`): es la base de la que dependen 1.084 "
        "personas y si el copiador tuviera un bug, que no pueda escribir.",
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

    def test_el_backup_con_postgres_no_pasa_por_el_sqlite(self):
        """La deuda que fijaba este test (el backup sólo-SQLite) se pagó el
        31/10/2026: con `dsn`, `run_backup` vuelca Postgres. Lo que queda fijado
        ahora es que esa rama no toque el SQLite ni de casualidad — ni cuando el
        volcado falla. (La foto diaria salió de esta lista el 29/10/2026.)"""
        import unittest.mock as _m
        import sys
        sys.path.insert(0, RAIZ)
        from scripts import backup_db
        with _m.patch.object(backup_db, "dump_sqlite_consistent",
                             side_effect=AssertionError("copió el SQLite con Postgres")), \
                _m.patch.object(backup_db, "dump_postgres",
                                side_effect=backup_db.BackupFallido("sin pg_dump")):
            stats = backup_db.run_backup(db_path=__file__, dsn="dbname=x")
        self.assertEqual(stats["motor"], "postgres")
        self.assertTrue(any("sin pg_dump" in e for e in stats["errors"]), stats["errors"])

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
