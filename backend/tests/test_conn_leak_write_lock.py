"""Una excepción en un handler no puede dejar tomado el lock de escritura.

EL INCIDENTE (2026-08-12). El volumen de Railway llegó al 97% y SQLite empezó a
devolver SQLITE_FULL en cada escritura. Eso solo ya rompía la app, pero lo que lo
convirtió en una caída larga fue esto: 17 rutas de escritura hacían

    conn = get_db()
    ...  conn.execute(INSERT...)  ...
    conn.commit()
    conn.close()          # ← sólo en el camino FELIZ

Cuando algo lanzaba entre el INSERT y el close, la conexión quedaba viva CON LA
TRANSACCIÓN DE ESCRITURA ABIERTA. En SQLite eso es un lock RESERVED sobre el
archivo: TODAS las escrituras de TODOS los usuarios pasan a esperar el
busy_timeout (15s) y morir con "database is locked", mientras las lecturas siguen
andando perfecto (WAL). Es exactamente lo que reportó el usuario: "se queda
tildado y al rato tira un error, pero la app carga bien".

POR QUÉ NO SE LIBERA SOLA. El traceback de la excepción sostiene el frame del
handler, y el frame sostiene `conn`. frame↔traceback es un CICLO de referencias,
así que el refcounting de CPython NO puede liberarlo: hay que esperar al GC
generacional. En un server con poco tráfico eso son MINUTOS. (Medido con uvicorn
real durante el post-mortem: 12 sondas seguidas a 15,3s cada una, y seguía
bloqueado a t+110s sin tráfico. Con TestClient se liberaba solo — por eso el
primer intento de reproducirlo dio negativo y la teoría se descartó de más.)

Estos tests fijan las dos mitades: que el ciclo de verdad retiene la conexión
(si no, no hay bug que prevenir) y que el try/finally la cierra igual.

Corre con: cd backend && python3 -m pytest tests/test_conn_leak_write_lock.py
"""
import ast
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402


def _sonda_escritura(path, timeout_ms=800):
    """¿Se puede escribir en `path` ahora mismo? Devuelve (pudo, error)."""
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA busy_timeout={timeout_ms}")
    try:
        c.execute("CREATE TABLE IF NOT EXISTS sonda(x)")
        c.execute("INSERT INTO sonda VALUES (1)")
        c.commit()
        return True, None
    except sqlite3.OperationalError as ex:
        return False, str(ex)
    finally:
        c.close()


def test_una_conexion_retenida_por_un_traceback_bloquea_a_todos_los_escritores():
    """La mitad 'el bug es real': sin esto, el test de abajo no prueba nada.

    Reproducimos la retención igual que uvicorn: guardamos la excepción, que
    arrastra su traceback → el frame → `conn`. El refcount no alcanza.
    """
    # OJO: la ruta se lee EN EL MOMENTO. El conftest le da a cada módulo de test
    # su propia base y repunta main.DB_PATH; sondear TMP_DB.name daría un archivo
    # distinto del que usa get_db() y el test pasaría siempre, sin probar nada.
    path = main.DB_PATH
    guardada = None

    def handler_sin_finally():
        conn = main.get_db()
        conn.execute("CREATE TABLE IF NOT EXISTS x_leak(id INTEGER)")
        conn.execute("INSERT INTO x_leak VALUES (1)")   # abre la tx de escritura
        raise RuntimeError("disco lleno a mitad del handler")

    try:
        handler_sin_finally()
    except RuntimeError as ex:
        guardada = ex          # ← como hace Starlette al propagar el error

    assert guardada is not None and guardada.__traceback__ is not None

    pudo, err = _sonda_escritura(path)
    assert not pudo, "esperaba el lock tomado — si esto pasa, el bug no se reprodujo"
    assert "locked" in (err or "").lower(), err

    # Y se destraba SOLO cuando se rompe el ciclo (en prod: el GC, o el reinicio).
    del guardada
    import gc
    gc.collect()
    pudo, err = _sonda_escritura(path)
    assert pudo, f"tras romper el ciclo debería escribir: {err}"


def test_con_try_finally_la_excepcion_no_deja_el_lock_tomado():
    """La mitad 'el fix funciona': mismo escenario, con el patrón que ahora
    tienen las 17 rutas."""
    # OJO: la ruta se lee EN EL MOMENTO. El conftest le da a cada módulo de test
    # su propia base y repunta main.DB_PATH; sondear TMP_DB.name daría un archivo
    # distinto del que usa get_db() y el test pasaría siempre, sin probar nada.
    path = main.DB_PATH
    guardada = None

    def handler_con_finally():
        conn = main.get_db()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS x_ok(id INTEGER)")
            conn.execute("INSERT INTO x_ok VALUES (1)")
            raise RuntimeError("disco lleno a mitad del handler")
        finally:
            conn.close()

    try:
        handler_con_finally()
    except RuntimeError as ex:
        guardada = ex

    assert guardada is not None and guardada.__traceback__ is not None
    pudo, err = _sonda_escritura(path)
    assert pudo, f"el finally tenía que soltar el lock, pero: {err}"


def test_ninguna_ruta_de_escritura_deja_el_close_fuera_de_un_try():
    """Guarda estructural: el día que alguien agregue la ruta 18, esto la caza.

    Un test de comportamiento sólo cubre las rutas que se le ocurren a quien lo
    escribe. Esto recorre el AST y exige que TODA ruta que escribe tenga su
    `conn = get_db()` cubierto por un try (con finally o con except que cierre).
    """
    src = open(os.path.join(BACKEND, "main.py")).read()
    tree = ast.parse(src)
    lineas = src.split("\n")

    def es_ruta_de_escritura(fn):
        for d in fn.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and getattr(d.func.value, "id", None) == "app"
                    and d.func.attr in ("post", "put", "patch", "delete")):
                return True
        return False

    culpables = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not es_ruta_de_escritura(fn):
            continue
        cuerpo = "\n".join(lineas[fn.lineno - 1:fn.end_lineno])
        if "get_db()" not in cuerpo:
            continue
        if not any(p in cuerpo.upper() for p in ("INSERT ", "UPDATE ", "DELETE ", "COMMIT")):
            continue
        # ¿queda alguna escritura de primer nivel, fuera de todo try?
        def escribe(node):
            # El docstring NO cuenta: casi todos estos handlers explican en prosa
            # qué borran o actualizan, y buscar la palabra suelta daba 8 falsos
            # positivos (delete_broker, bond_cashflow, …) que ya estaban bien.
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                return False
            seg = "\n".join(lineas[node.lineno - 1:(node.end_lineno or node.lineno)]).upper()
            return any(p in seg for p in ("INSERT ", "UPDATE ", "DELETE ", "COMMIT()"))

        for st in fn.body:
            if isinstance(st, (ast.Try, ast.With)):
                continue
            if escribe(st):
                culpables.append(f"{fn.name} (main.py:{st.lineno})")
                break

    assert not culpables, (
        "Estas rutas escriben fuera de todo try: si algo lanza ahí, la conexión "
        "queda viva con la transacción abierta y BLOQUEA LAS ESCRITURAS DE TODOS "
        "LOS USUARIOS hasta que corra el GC. Envolvé el cuerpo en "
        "try/finally: conn.close().\n  - " + "\n  - ".join(culpables)
    )
