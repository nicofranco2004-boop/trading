"""Aislamiento de la DB para TODA la suite de tests.

Causa raíz que esto resuelve: main.py lee DB_PATH a import-time (main.py:95) y
default-ea a la DB de desarrollo real (backend/trading.db). Los tests que NO
seteaban os.environ['DB_PATH'] antes de importar main (24 de 41 archivos)
escribían sus usuarios/posiciones en la DB real → contaminación medida de
cuentas @rendi.test que inflaba métricas y casi manda un número falso a la
landing.

pytest importa este conftest ANTES de colectar/importar cualquier test module,
así que al setear DB_PATH acá garantizamos que ningún `import main` posterior
caiga en la DB real. init_db() corre solo al importar main (main.py:1477) sobre
este temp, creando el schema. El temp se borra al terminar la sesión.

Los archivos que ya seteaban su propio temp siguen funcionando (usan el suyo);
lo importante es que el DEFAULT dejó de ser la DB real.
"""
import os
import tempfile
import atexit

# Solo si nadie lo seteó ya (respetamos un DB_PATH explícito del entorno).
if not os.environ.get("DB_PATH"):
    _tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp.close()
    os.environ["DB_PATH"] = _tmp.name

    @atexit.register
    def _cleanup_test_db(path=_tmp.name):
        for p in (path, path + "-wal", path + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass


# ─── Una base POR ARCHIVO de test ────────────────────────────────────────────
# Raíz del problema (medida): main.py lee DB_PATH a IMPORT-TIME y lo guarda en una
# constante de módulo que usa get_db(). pytest importa TODOS los módulos de test antes
# de correr nada, así que el PRIMER archivo que hace `import main` fija la base para
# todo el proceso: los otros 57 setean su temp y no tiene ningún efecto. Los 58
# terminan compartiendo UNA sola base → se pisan los datos y aparece "database is
# locked". Por eso pasan aislados y fallan juntos.
#
# `--forked` NO alcanza: el padre ya congeló la ruta antes de forkear, así que cada
# fork hereda la misma y siguen escribiendo al mismo archivo (probado: sigue fallando
# con UNIQUE constraint failed: users.email).
#
# Esto le da a cada MÓDULO su propia base y re-crea el schema. Se re-apunta la
# constante de main (no solo el env var, que main ya no vuelve a leer).
import pytest


@pytest.fixture(autouse=True, scope="module")
def _db_por_modulo():
    import main
    # ── Modo Postgres (DATABASE_URL seteada) ─────────────────────────────────
    # No hay archivo que reemplazar: el aislamiento por módulo se consigue
    # vaciando el schema y recreándolo. Correr LA MISMA suite contra los dos
    # motores es todo el punto de la migración — si acá se bifurcara la lógica
    # de test, estaríamos comparando dos cosas distintas.
    if getattr(main, "USANDO_PG", False):
        import psycopg
        with psycopg.connect(main.DATABASE_URL, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        main.init_db()
        yield
        return
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    previo = main.DB_PATH
    main.DB_PATH = tmp.name
    os.environ["DB_PATH"] = tmp.name
    main.init_db()
    yield
    main.DB_PATH = previo
    for p in (tmp.name, tmp.name + "-wal", tmp.name + "-shm"):
        try:
            os.unlink(p)
        except OSError:
            pass
