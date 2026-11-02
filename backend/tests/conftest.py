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

# 🔴 Contra una base con datos de personas, la suite NO arranca: el primer
# `import main` le correría el arranque (reparaciones incluidas) a esos datos.
# En `pytest_sessionstart`, que corre ANTES de que pytest junte los archivos
# (que es cuando se importa `main`). Ver tests/_candado_base_con_datos.py.
def pytest_sessionstart(session):
    if os.environ.get("DATABASE_URL"):
        from tests._candado_base_con_datos import filas_de_personas, mensaje
        con_filas = filas_de_personas(os.environ["DATABASE_URL"].strip())
        if con_filas:
            import pytest as _pytest
            _pytest.exit(mensaje(con_filas), returncode=3)


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
# queda con los locks de todo lo que tocó. (Desde el 29/10/2026 el shim abre la
# transacción al escribir, como sqlite3 — `pgshim.es_lectura_pura` —; lo de
# abajo sigue haciendo falta para las conexiones que sí escribieron.)
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
# ── La suite NO es un deploy ─────────────────────────────────────────────────
# `mantenimiento.py` arranca CERRADO cuando hay `DATABASE_URL` y no está la marca
# de que el pasaje terminó. Es a propósito y protege producción: el día que se
# prenda Postgres, la app levanta cerrada aunque nadie se acuerde de nada.
#
# Pero la suite corre con `DATABASE_URL` puesta para elegir el motor, así que
# heredaría ese default y **todos los tests de endpoints darían 503**. Medido: 460
# fallas.
#
# Se apaga ACÁ y no allá, y la distinción importa: el que sabe que esto es un test
# es el arnés, no el código de producción. Aflojar el default del lado de la app
# para que la suite pase sería debilitar la red que protege a los 1.084.
#
# ⚠️ Y si alguien borra esta línea, no falla en silencio: explotan ~460 tests de
# una. Es la clase de señal que uno quiere.
os.environ.setdefault("RENDI_MANTENIMIENTO", "0")

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


def _timeout_de_pytest_real() -> int:
    """El `--timeout=` que ESTÁ CORRIENDO, no el sugerido.

    🔴 POR QUÉ EXISTE. `test_relojes_del_conftest` se llama
    `test_los_valores_QUE_ESTAN_CORRIENDO_cumplen_el_orden` y dice en su docstring
    "no los defaults: los de esta corrida". Pero de los tres relojes leía dos del
    entorno y **el tercero de una constante de 20 escrita a mano**. O sea:
    prometía medir lo que corre y medía otra cosa — el error exacto que este
    proyecto ya pagó varias veces.

    Se descubrió corriendo la suite contra Supabase (19/08/2026). Ahí todo tarda
    ~35× más, así que hubo que escalar los relojes a 45 < 90 < 240; el test falló
    diciendo "lock (90s) tiene que ser MENOR que el --timeout de pytest (20s)"
    cuando el `--timeout` real era 240. El test tenía razón sobre la constante y
    estaba equivocado sobre la realidad.

    Se lee de la config de pytest, que es donde vive el valor de verdad. Si no se
    puede (pytest-timeout ausente, o import fuera de una corrida), se cae al
    sugerido: es el mismo comportamiento que había, no uno nuevo.
    """
    try:
        import _pytest.config
        cfg = _pytest.config.get_config()
        v = cfg.getoption("timeout", None) if cfg else None
        if v:
            return int(float(v))
    except Exception:
        pass
    # Plan B: leerlo de la línea de comandos. pytest-timeout acepta las dos formas.
    import sys
    for i, a in enumerate(sys.argv):
        if a.startswith("--timeout="):
            try:
                return int(float(a.split("=", 1)[1]))
            except ValueError:
                pass
        if a == "--timeout" and i + 1 < len(sys.argv):
            try:
                return int(float(sys.argv[i + 1]))
            except ValueError:
                pass
    return _PYTEST_TIMEOUT_SUGERIDO


_PYTEST_TIMEOUT_REAL = _timeout_de_pytest_real()


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

    # El pid va adelante para que dos corridas simultáneas NUNCA compartan un
    # nombre de esquema: si lo compartieran, una dropearía el esquema que la otra
    # está usando en ese mismo momento.
    #
    # 🔴 UN SOLO NOMBRE POR CORRIDA, no uno por módulo. El pooler de Supabase
    # (Supavisor, modo sesión) arma una fila propia por cada `search_path` distinto
    # del DSN y la deja abierta: medido el 02/11/2026, cada `search_path` nuevo dejó
    # 2 conexiones ocupadas en la base, que no se soltaron. Con un esquema por
    # módulo (~160), la base (60 lugares, 3 reservados) se llenaba hacia el módulo
    # 24 y la corrida del 31/10 dio 211 errores «remaining connection slots are
    # reserved». El aislamiento entre módulos no depende del nombre: abajo se matan
    # las conexiones de esta corrida y el esquema se borra y se vuelve a crear vacío.
    _pre = f"t{os.getpid()}_"
    esquema = _pre + "suite"

    # Las conexiones que quedaron quietas en el pozo apuntan al esquema anterior.
    pgshim.cerrar_pozos()
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
    _forzar_ajustes_por_set(esquema)
    pgshim.limpiar_caches()
    main.init_db()
    _exigir_que_los_ajustes_hayan_entrado(esquema)


# Los ajustes originales de pgsesion, antes de que les agreguemos los de la suite.
# Se guarda una sola vez: si se releyera en cada módulo, el segundo módulo tomaría
# como "base" la tupla ya extendida del primero y los SET se irían apilando.
_AJUSTES_BASE = None


def _forzar_ajustes_por_set(esquema: str):
    """Repite por `SET` los ajustes que el DSN manda en `options=`.

    🔴 POR QUÉ, y no es teórico — medido contra el Supabase real el 19/08/2026.
    Los poolers de Supabase (Supavisor) **se comen casi todo el `options=`**:

        opción del DSN                        Postgres normal   Supabase (los 2 poolers)
        ------------------------------------  ---------------   ------------------------
        search_path                           ✅                ✅  llega
        lock_timeout                          ✅                🔴  queda en 0
        idle_in_transaction_session_timeout   ✅                🔴  queda en 0
        application_name                      ✅                🔴  queda 'Supavisor'

    Las tres que se pierden son **exactamente** las tres que sostienen el
    aislamiento, y las tres fallan hacia el lado peligroso:
      · `lock_timeout=0` → una consulta trabada espera PARA SIEMPRE en vez de
        cortar. Es la cuelgue que el arreglo del aislamiento vino a matar.
      · `idle_in_transaction_session_timeout=0` → una conexión filtrada retiene
        sus locks para siempre.
      · `application_name='Supavisor'` → el `pg_terminate_backend` de arriba
        filtra por ese nombre y **no matchea nada**: las huérfanas no se matan.
        (Y aflojar ese filtro NO es opción: en esa base viven las conexiones de
        Supabase mismo —PostgREST, su exportador de métricas, el pooler—, así que
        un terminate sin filtro se lleva puesto el proyecto entero.)

    Un módulo suelto pasa igual porque no hay contención; la suite completa se
    cuelga. O sea: el modo de falla es silencioso hasta que es caro.

    `SET` sí atraviesa los dos poolers (verificado), y en un Postgres normal es
    redundante e inofensivo. Se hace por `pgsesion.AJUSTES_DE_SESION`, que es la
    única puerta por donde pasan TODAS las conexiones de Rendi.
    """
    global _AJUSTES_BASE
    import pgsesion
    if _AJUSTES_BASE is None:
        _AJUSTES_BASE = tuple(pgsesion.AJUSTES_DE_SESION)
    # ⚠️ `search_path` NO va acá, y la primera versión lo puso "por las dudas".
    # Es el ÚNICO que sí atraviesa los dos poolers, así que no hay nada que
    # arreglar — y forzarlo rompe: `test_pgshim_pk_cache` abre a propósito una
    # conexión con `options=-c search_path=zz_vacio` para probar que un esquema
    # vacío levanta, y el SET se la pisaba mandándola al esquema del módulo. Los
    # dos tests de ese archivo fallaban, y de yapa la tabla sin PK del primero
    # quedaba contaminando el esquema y hacía fallar al segundo.
    # Regla: repetir por SET SÓLO lo que se pierde de verdad.
    pgsesion.AJUSTES_DE_SESION = _AJUSTES_BASE + (
        f"SET lock_timeout = '{_LOCK_TIMEOUT}'",
        f"SET idle_in_transaction_session_timeout = '{_IDLE_TX_TIMEOUT}'",
        f"SET application_name = '{_APP_NAME}'",
    )


def _exigir_que_los_ajustes_hayan_entrado(esquema: str):
    """Aborta la corrida si los ajustes NO quedaron puestos.

    Sin esto el arreglo de arriba sería una red opt-in: si mañana un pooler nuevo
    también se comiera los `SET`, o alguien cambiara la puerta por la que se
    conecta, la suite volvería a colgarse y el motivo estaría a diez capas de
    distancia. Preguntarle a la base **qué quedó puesto de verdad** cuesta cuatro
    consultas por módulo y convierte un cuelgue mudo en un error que se lee.

    Se pregunta por una conexión abierta como las que usan los tests —no una
    aparte—, porque lo que hay que verificar es justamente ESA.
    """
    import main as _main
    conn = _main.get_db()
    try:
        real = {k: conn.execute(f"SHOW {k}").fetchone()[0] for k in
                ("search_path", "lock_timeout",
                 "idle_in_transaction_session_timeout", "application_name")}
    finally:
        conn.close()
    mal = []
    if esquema not in real["search_path"]:
        mal.append(f"search_path={real['search_path']!r} (esperaba {esquema!r})")
    if real["lock_timeout"] in ("0", "0ms"):
        mal.append("lock_timeout=0 (sin límite: una consulta trabada espera para siempre)")
    if real["idle_in_transaction_session_timeout"] in ("0", "0ms"):
        mal.append("idle_in_transaction_session_timeout=0 (una conexión filtrada "
                   "retiene locks para siempre)")
    if real["application_name"] != _APP_NAME:
        mal.append(f"application_name={real['application_name']!r} (esperaba "
                   f"{_APP_NAME!r}: sin esto el limpiador de huérfanas no matchea "
                   f"NADA, y aflojar su filtro mataría las conexiones de Supabase)")
    if mal:
        raise RuntimeError(
            "Los ajustes de sesión de la suite NO quedaron puestos, así que el "
            "aislamiento entre módulos no está garantizado y la corrida se va a "
            "colgar más adelante sin decir por qué:\n  · "
            + "\n  · ".join(mal)
            + "\nVer `_forzar_ajustes_por_set` en este archivo."
        )


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


# ═══════════════════════════════════════════════════════════════════════════
# LA RED DE SEGURIDAD: que una falla NUEVA se note sola.
#
# ⚠️ POR QUÉ ESTO EXISTE. Durante siete rondas se dio por hecho que la suite
# completa "moría al 23-28%" y toda la verificación se hizo sobre ~44 archivos
# elegidos a mano. Era falso: `pytest` a secas colectaba `backend/scripts/`, donde
# hay tres archivos `test_*.py` que NO son tests (uno manda mails de verdad). Con
# eso resuelto (ver `pytest.ini`) la suite corre entera en ~52 s.
#
# Pero correr no alcanza: quedan fallas preexistentes, y con 29 rojos de fondo una
# regresión nueva se pierde en el ruido. Comparar CONTEOS no sirve —la suite varía
# entre entornos y un número no distingue "se arregló una y se rompió otra"—, así
# que esto compara CONJUNTOS DE NOMBRES contra `fallas_conocidas.txt`.
#
# Las dos direcciones importan:
#   · NUEVAS  → algo se rompió en esta corrida. Es lo que hay que ver.
#   · las que ya no fallan → alguien las arregló y la lista quedó vieja.
#
# ⚠️ SÓLO GRITA POR LAS NUEVAS, Y SÓLO SI CORRIÓ LA SUITE ENTERA. Con un subconjunto
# (`pytest tests/test_x.py`) las que faltan no están arregladas: no se ejecutaron.
# Confundir esas dos cosas convertiría el guard en ruido, y un guard ruidoso se
# termina ignorando — que es exactamente cómo estas 29 se volvieron invisibles.
_FALLAS_ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fallas_conocidas.txt")
_fallas_vistas = set()
_tests_corridos = set()


def _fallas_conocidas():
    try:
        with open(_FALLAS_ARCHIVO, encoding="utf-8") as fh:
            return {l.strip() for l in fh
                    if l.strip() and not l.lstrip().startswith("#")}
    except FileNotFoundError:
        return set()


def pytest_runtest_logreport(report):
    """Anota qué corrió y qué falló. `nodeid` es el mismo id que escribe `-rfE`."""
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _tests_corridos.add(report.nodeid)
    if report.failed and report.when in ("setup", "call", "teardown"):
        _fallas_vistas.add(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    conocidas = _fallas_conocidas()
    if not conocidas:
        return
    nuevas = sorted(_fallas_vistas - conocidas)
    # Una conocida sólo cuenta como "arreglada" si de verdad se ejecutó.
    arregladas = sorted((conocidas & _tests_corridos) - _fallas_vistas)
    tw = getattr(session.config, "get_terminal_writer", lambda: None)()
    def _decir(msg, **kw):
        if tw is not None:
            tw.line(msg, **kw)
        else:
            print(msg)
    if nuevas:
        _decir("")
        _decir("=" * 72, red=True, bold=True)
        _decir(f"🔴 {len(nuevas)} FALLA(S) NUEVA(S) — no están en fallas_conocidas.txt",
               red=True, bold=True)
        for n in nuevas:
            _decir(f"    {n}", red=True)
        _decir("Si es esperado, agregalas al archivo CON EL MOTIVO. Si no, rompiste algo.",
               red=True)
        _decir("=" * 72, red=True, bold=True)
        # No se toca `exitstatus`: pytest ya sale != 0 cuando algo falla, y
        # pisarlo escondería el código real de salida.
    if arregladas:
        _decir("")
        _decir(f"✅ {len(arregladas)} falla(s) conocida(s) ya no fallan — sacalas de "
               f"fallas_conocidas.txt:", green=True)
        for n in arregladas:
            _decir(f"    {n}", green=True)


@pytest.fixture(autouse=True)
def _fuentes_sin_marca_de_caida():
    """`main._FUENTE_CAIDA` recuerda un rato que data912 o ArgentinaDatos no
    contestaron, para no repetirles el pedido. Entre tests eso contamina: un
    test que simula la caída dejaría al siguiente sin preguntar. Cada test
    arranca sin marcas."""
    import sys
    m = sys.modules.get("main")
    if m is not None and hasattr(m, "_FUENTE_CAIDA"):
        m._FUENTE_CAIDA.clear()
    yield


# ─── Ningún test le pregunta a Yahoo por el pre/post mercado ────────────────
# La tool del chat «¿qué pasó hoy?» consulta el pre y post mercado de Wall
# Street (fuera_de_horario.py). Sin esto, cada test que pasa por ella haría un
# pedido REAL a Yahoo (hasta 8 s) y su resultado dependería de la hora a la que
# corre la suite. Acá Yahoo "no conoce nada" → no hay sesión. El test que quiere
# pre o post lo dice (monkeypatch de `_pedir_yahoo` o `pedir=`).
@pytest.fixture(autouse=True)
def _yahoo_pre_post_mudo(monkeypatch):
    try:
        import fuera_de_horario
    except Exception:
        yield
        return
    monkeypatch.setattr(fuera_de_horario, "_pedir_yahoo", lambda simbolos: [])
    monkeypatch.setattr(fuera_de_horario, "_traer_velas", lambda simbolo: ([], {}))
    monkeypatch.setattr(fuera_de_horario, "_traer_sesiones_byma", lambda: set())
    fuera_de_horario._franjas_cache.clear()
    fuera_de_horario._vaciar_cache()
    yield
    fuera_de_horario._vaciar_cache()
