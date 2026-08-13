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
import re

import pytest


# ─── Postgres: un ESQUEMA por módulo, no una base compartida ─────────────────
# En SQLite cada módulo recibe su propio ARCHIVO. El equivalente en Postgres NO
# es "vaciar la base y volver a crearla": eso es lo que hacía la versión anterior
# (`DROP SCHEMA public CASCADE`) y es justo lo que se colgaba.
#
# El mecanismo, medido en vivo con `pg_stat_activity` durante una corrida:
#
#   estado                 consulta
#   ---------------------  ---------------------------------------------
#   idle in transaction    (un test anterior que escribió y no cerró)
#   active + Lock          INSERT INTO users (email, ...)   ← esperando
#
# Un test deja una conexión con la transacción abierta y un `users.email`
# adentro. El test siguiente inserta ese mismo email y queda esperando a que la
# primera transacción termine — para siempre, porque nadie la cierra. A los 10s
# pytest lo mata y sale como `Failed: Timeout`. NO es una falla de la app.
#
# En SQLite esto no pasaba por dos motivos: cada módulo tenía su archivo, y una
# conexión de sqlite3 sólo abre transacción al ESCRIBIR. psycopg con
# autocommit=False abre transacción hasta para un SELECT, y esa transacción se
# queda con los locks de todo lo que tocó.
#
# El arreglo tiene tres partes, y las tres hacen falta:
#
#   1. Un esquema propio por módulo. Un esquema recién creado no puede tener a
#      nadie esperándolo: el bloqueo ENTRE módulos deja de ser posible, en vez
#      de quedar "poco probable".
#   2. Cortar las conexiones que dejó abiertas el módulo anterior. Además de
#      soltar los locks, libera lugar: Postgres acepta 100 conexiones y una
#      suite con cientos de fallas se las come (cada traceback que pytest guarda
#      para el reporte final mantiene viva la conexión de ese test).
#   3. Dos relojes de Postgres, puestos en la conexión de la app:
#      · `lock_timeout` — si algo igual se bloquea, corta con un error que DICE
#        que se bloqueó. La diferencia entre una falla que se puede leer y un
#        `Failed: Timeout` que no dice nada.
#      · `idle_in_transaction_session_timeout` — Postgres mata solo a la
#        conexión que quedó con la transacción abierta sin hacer nada. Es la red
#        de contención para las fugas DENTRO de un mismo módulo, que el esquema
#        por módulo no cubre.
#
# Los dos relojes van por el DSN (`options`), así los toma TODA conexión que
# abra `get_db()` sin tocar una línea del código de la app.

# EL ORDEN DE ESTOS DOS NÚMEROS ES EL ARREGLO, no un detalle de configuración:
#
#     idle_in_transaction (3s)  <  lock_timeout (7s)  <  --timeout de pytest (10s)
#
# · Si `lock_timeout` fuera el más chico, el test que espera se rendiría ANTES de
#   que Postgres mate a la conexión fugada: seguiría fallando pudiendo pasar.
#   Con este orden, a los 3s la conexión fugada muere, suelta los locks, y el
#   test que esperaba SIGUE Y PASA.
# · `lock_timeout` es la red de abajo: si algo se bloquea por otro motivo, corta
#   con un error que dice "me bloqueé" en vez del `Failed: Timeout` de pytest,
#   que no dice nada.
_IDLE_TX_TIMEOUT = "3s"
_LOCK_TIMEOUT = "7s"

_PG_DSN_BASE = None          # el DSN como vino del entorno, sin opciones
_PG_ESQUEMA_PREVIO = None    # se borra recién cuando ya nadie lo está usando


def _pg_dsn(esquema: str) -> str:
    from psycopg.conninfo import make_conninfo
    # make_conninfo y no pegar texto a mano: el DSN de pgserver viene con el
    # host en un path de socket, y armar el query string a mano es pedir que
    # algo se escape mal.
    # El search_path lleva SÓLO el esquema del módulo, sin `public` de respaldo.
    # Con respaldo, una tabla que faltara en el esquema del módulo se leería de
    # `public` —que puede tener tablas viejas de corridas anteriores— y el test
    # pasaría con datos de otro. Sin respaldo eso es un error que se ve.
    # (Las funciones y tipos de Postgres viven en `pg_catalog`, que está siempre
    # en el path aunque no se lo nombre: no hace falta `public` para eso.)
    return make_conninfo(
        _PG_DSN_BASE,
        options=(f"-c search_path={esquema} "
                 f"-c lock_timeout={_LOCK_TIMEOUT} "
                 f"-c idle_in_transaction_session_timeout={_IDLE_TX_TIMEOUT}"),
    )


def _aislar_postgres(main, nombre_modulo: str):
    global _PG_DSN_BASE, _PG_ESQUEMA_PREVIO
    import psycopg
    import pgshim

    if _PG_DSN_BASE is None:
        _PG_DSN_BASE = main.DATABASE_URL

    # Los identificadores de Postgres son de 63 bytes. Los nombres de módulo son
    # cortos, pero cortar acá evita que un archivo nuevo rompa la suite entera.
    esquema = "t_" + re.sub(r"\W", "_", nombre_modulo)[-58:]

    with psycopg.connect(_PG_DSN_BASE, autocommit=True) as c:
        c.execute("""
            SELECT pg_terminate_backend(pid)
              FROM pg_stat_activity
             WHERE datname = current_database()
               AND pid <> pg_backend_pid()""")
        # El esquema del módulo anterior se borra ACÁ y no en su teardown: ahí
        # todavía tenía conexiones vivas y el DROP se habría colgado igual que
        # antes. Recién ahora, con los backends cortados, no hay quién bloquee.
        # Sin esto quedarían ~157 esquemas (uno por módulo) llenando el catálogo.
        if _PG_ESQUEMA_PREVIO and _PG_ESQUEMA_PREVIO != esquema:
            c.execute(f'DROP SCHEMA IF EXISTS "{_PG_ESQUEMA_PREVIO}" CASCADE')
        c.execute(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE')
        c.execute(f'CREATE SCHEMA "{esquema}"')

    _PG_ESQUEMA_PREVIO = esquema
    main.DATABASE_URL = _pg_dsn(esquema)
    pgshim.limpiar_caches()
    main.init_db()


@pytest.fixture(autouse=True, scope="module")
def _db_por_modulo(request):
    import main
    # Correr LA MISMA suite contra los dos motores es todo el punto de la
    # migración: acá cambia CÓMO se aísla la base, no qué se testea.
    if getattr(main, "USANDO_PG", False):
        _aislar_postgres(main, request.module.__name__)
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
