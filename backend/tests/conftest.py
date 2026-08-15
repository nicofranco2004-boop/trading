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

# EL ORDEN DE ESTOS NÚMEROS ES EL ARREGLO, no un detalle de configuración:
#
#     idle_in_transaction  <  lock_timeout  <  --timeout de pytest
#
# · Si `lock_timeout` fuera el más chico, el test que espera se rendiría ANTES de
#   que Postgres mate a la conexión fugada: seguiría fallando pudiendo pasar.
#   Con este orden, la conexión fugada muere primero, suelta los locks, y el
#   test que esperaba SIGUE Y PASA.
# · `lock_timeout` es la red de abajo: si algo se bloquea por otro motivo, corta
#   con un error que dice "me bloqueé" en vez del `Failed: Timeout` de pytest,
#   que no dice nada.
#
# ⚠️ **LOS VALORES SUBIERON (3/7/10 → 6/12/20) Y EL MOTIVO ESTÁ MEDIDO.** Con 3
# segundos, la MISMA suite en el mismo commit daba:
#
#     #1  46 fallas  · 68s        #2  49 fallas · 133s        #3  46 fallas · 71s
#                                     ↑ las 3 extra: IdleInTransactionSessionTimeout
#
# Nada corría en paralelo: era la máquina. Cuando se pone lenta y la corrida tarda
# el doble, un test LEGÍTIMO pasa más de 3s con la transacción abierta y Postgres
# lo mata. O sea que el número de la suite volvía a depender de la carga de la
# máquina — el mismo problema que este proyecto ya se pasó tres sesiones
# arreglando, con otra cara.
#
# 🔴 **Y no se sube sólo el de 3s.** Si el idle cruza al `lock_timeout` se rompe la
# propiedad de arriba y los tests bloqueados vuelven a fallar pudiendo pasar. Se
# suben LOS TRES manteniendo el orden. Por eso el orden dejó de ser un comentario
# y ahora lo valida `pytest_configure` abajo: la suite no arranca mal configurada.
#
# Se pueden apretar en CI (máquina dedicada) o aflojar en una máquina cargada:
#     RENDI_TEST_IDLE_TX_S=3 RENDI_TEST_LOCK_S=7 pytest tests --timeout=10
_IDLE_TX_S_DEFAULT = 6
_LOCK_S_DEFAULT = 12
_PYTEST_TIMEOUT_SUGERIDO = 20        # el que va en `--timeout=`; ver el README de arriba


def _segundos(var: str, default: int) -> int:
    """Lee un reloj del entorno. Un valor inválido LEVANTA, no cae al default.

    Caer al default en silencio sería lo peor de los dos mundos: el que quiso
    apretar los relojes en CI creería que los apretó, y estaría midiendo con otros.
    """
    crudo = os.environ.get(var)
    if crudo is None or crudo.strip() == "":
        return default
    try:
        v = int(str(crudo).strip().rstrip("s"))
    except ValueError:
        raise RuntimeError(f"{var}={crudo!r} no es un número de segundos") from None
    if v <= 0:
        raise RuntimeError(f"{var}={crudo!r}: tiene que ser mayor que cero")
    return v


_IDLE_TX_S = _segundos("RENDI_TEST_IDLE_TX_S", _IDLE_TX_S_DEFAULT)
_LOCK_S = _segundos("RENDI_TEST_LOCK_S", _LOCK_S_DEFAULT)
_IDLE_TX_TIMEOUT = f"{_IDLE_TX_S}s"
_LOCK_TIMEOUT = f"{_LOCK_S}s"


def revisar_orden_de_relojes(idle_s, lock_s, pytest_timeout_s=None):
    """El orden, como función: `idle < lock < --timeout`. Devuelve el motivo o None.

    Es una función y no un `assert` suelto para que la pueda llamar el arranque de
    la suite **y** su test. Si viviera sólo adentro del hook, el test tendría que
    simular pytest para probarlo, y un test que simula demasiado deja de probar.

    `pytest_timeout_s=None` = no se pasó `--timeout`: ahí no hay tercer reloj y
    sólo se exige `idle < lock`. Ojo que eso NO es "está todo bien": es que el
    tercero no existe en esa corrida.
    """
    if idle_s >= lock_s:
        return (f"idle_in_transaction ({idle_s}s) tiene que ser MENOR que "
                f"lock_timeout ({lock_s}s). Al revés, el test que espera se rinde "
                f"antes de que muera la conexión fugada: falla pudiendo pasar.")
    if pytest_timeout_s is not None and lock_s >= pytest_timeout_s:
        return (f"lock_timeout ({lock_s}s) tiene que ser MENOR que el --timeout de "
                f"pytest ({pytest_timeout_s}s). Al revés, pytest corta primero y en "
                f"vez de un error que dice 'me bloqueé' queda un 'Failed: Timeout' "
                f"que no dice nada.")
    return None


def pytest_configure(config):
    """La suite NO arranca con los relojes en un orden que rompe la propiedad.

    Antes el orden era un comentario de 12 líneas. Un comentario no impide que
    alguien suba sólo uno de los tres — que es exactamente el error que este
    cambio viene a evitar.
    """
    try:
        t = config.getoption("timeout", None)
    except Exception:
        t = None
    motivo = revisar_orden_de_relojes(_IDLE_TX_S, _LOCK_S,
                                      int(t) if t else None)
    if motivo:
        raise pytest.UsageError(f"relojes mal configurados: {motivo}")

_PG_DSN_BASE = None          # el DSN como vino del entorno, sin opciones
_PG_ESQUEMA_PREVIO = None    # se borra recién cuando ya nadie lo está usando

# ── Que DOS suites a la vez no se pisen ──────────────────────────────────────
# El aislamiento de abajo mata conexiones y dropea esquemas. Sin firma, mataba
# TODAS las conexiones de la base — incluidas las de otra corrida de la suite en
# otra terminal. El síntoma medido: la misma suite, en el mismo commit, daba 46,
# 47 y 49 fallas según qué otra cosa estuviera corriendo, con víctimas distintas
# cada vez y un `AdminShutdown: terminating connection due to administrator
# command` adentro del traceback. **El número dejaba de significar algo, que es
# justo lo que este proyecto se pasó tres sesiones arreglando.**
#
# Con el pid adentro del nombre, cada corrida mata sólo lo suyo. Y los esquemas
# también llevan el pid, así que dos corridas no comparten ni un nombre.
_APP_NAME = f"rendi_suite_{os.getpid()}"


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
                 f"-c idle_in_transaction_session_timeout={_IDLE_TX_TIMEOUT} "
                 f"-c application_name={_APP_NAME}"),
    )


def _aislar_postgres(main, nombre_modulo: str):
    global _PG_DSN_BASE, _PG_ESQUEMA_PREVIO
    import psycopg
    import pgshim

    if _PG_DSN_BASE is None:
        _PG_DSN_BASE = main.DATABASE_URL
        _barrer_esquemas_huerfanos(_PG_DSN_BASE)

    # Los identificadores de Postgres son de 63 bytes. Los nombres de módulo son
    # cortos, pero cortar acá evita que un archivo nuevo rompa la suite entera.
    # El pid va adelante para que dos corridas simultáneas NUNCA compartan un
    # nombre de esquema: si lo compartieran, una dropearía el esquema que la otra
    # está usando en ese mismo momento.
    _pre = f"t{os.getpid()}_"
    esquema = _pre + re.sub(r"\W", "_", nombre_modulo)[-(60 - len(_pre)):]

    with psycopg.connect(_PG_DSN_BASE, autocommit=True) as c:
        # SÓLO nuestras conexiones. Antes esto mataba todas las de la base y se
        # llevaba puesta cualquier otra corrida de la suite — ver _APP_NAME.
        c.execute("""
            SELECT pg_terminate_backend(pid)
              FROM pg_stat_activity
             WHERE datname = current_database()
               AND application_name = %s
               AND pid <> pg_backend_pid()""", (_APP_NAME,))
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


def _barrer_esquemas_huerfanos(dsn):
    """Borra los esquemas `t<pid>_…` de corridas que ya no existen.

    Con el pid adentro del nombre —que es lo que impide que dos corridas se pisen—
    una suite que muere a mitad (Ctrl-C, kill, un crash) deja sus esquemas para
    siempre. Al arrancar barremos los de pids que ya no están vivos. Los de la
    corrida de al lado, si la hay, se quedan: ese es justamente el punto.

    ⚠️ La pregunta "¿ese pid sigue vivo?" se contesta con `os.kill(pid, 0)` y NADA
    MÁS. La primera versión miraba ADEMÁS los pids de `pg_stat_activity`, y eso
    estaba mal: ésos son los procesos BACKEND del servidor Postgres, mientras que el
    pid del nombre del esquema es el del proceso CLIENTE (pytest). Son dos
    numeraciones distintas, así que la comparación casi nunca acertaba — y cuando
    acertaba por casualidad hacía justo lo contrario de lo que se busca: saltear un
    esquema realmente huérfano. Dos chequeos que parecían reforzarse eran uno
    correcto y uno equivocado.
    """
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as c:
        for (nombre,) in c.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname ~ '^t[0-9]+_'").fetchall():
            try:
                pid = int(nombre.split("_", 1)[0][1:])
            except ValueError:
                continue
            try:
                os.kill(pid, 0)          # ¿el proceso cliente todavía existe?
            except OSError:
                c.execute(f'DROP SCHEMA IF EXISTS "{nombre}" CASCADE')


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
