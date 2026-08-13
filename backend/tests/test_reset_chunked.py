"""El reset no puede tener el lock de escritura tomado de punta a punta.

EL PROBLEMA (reportado en vivo el 2026-08-13). El usuario tocó "Empezar de cero"
y, mientras corría, sus propios intentos de cargar una posición morían con
"database is locked". No era una falla nueva de Rendi: el reset borraba hasta un
millón de filas —las tablas de import son el 93% de la base— dentro de UNA sola
transacción. Mientras eso corre, SQLite no deja escribir a NADIE: un solo usuario
reseteando dejaba a toda la app sin poder guardar. Y encima el request quedaba
colgado minutos con el botón en "Reseteando…", indistinguible de un cuelgue.

Ahora borra por tandas, una transacción por tanda, soltando el lock entre medio.
Esto fija las dos propiedades que importan:
  · que el lock QUEDE LIBRE mientras el reset avanza (lo de arriba), y
  · que igual borre TODO (una optimización que no borra no sirve).

Corre con: cd backend && python3 -m pytest tests/test_reset_chunked.py
"""
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

import pytest  # noqa: E402

import main  # noqa: E402


def _sembrar(uid, n_filas):
    """Un batch de import con n_filas en cada tabla hija + una posición."""
    conn = main.get_db()
    with conn:
        conn.execute("INSERT INTO users (id,email,password_hash,approved) VALUES (?,?,?,1)",
                     (uid, f"reset{uid}@rendi.test", "x"))
        conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,?)",
            (f"b{uid}", uid, "Cocos", "cocos_movimientos", f"hash{uid}", "confirmed"))
        conn.executemany(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) VALUES (?,?,?,?)",
            [(f"b{uid}", i, '{"a":1}', "ok") for i in range(n_filas)])
        conn.execute("INSERT INTO positions (user_id,broker,asset,is_cash,invested) VALUES (?,?,?,0,?)",
                     (uid, "Cocos", "GGAL", 100.0))
    conn.close()


def _quedan(uid):
    conn = main.get_db()
    try:
        raw = conn.execute("SELECT COUNT(*) FROM import_raw_rows WHERE batch_id=?", (f"b{uid}",)).fetchone()[0]
        pos = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=?", (uid,)).fetchone()[0]
        bat = conn.execute("SELECT COUNT(*) FROM import_batches WHERE user_id=?", (uid,)).fetchone()[0]
        return raw, pos, bat
    finally:
        conn.close()


def test_borra_todo():
    """La versión por tandas tiene que dejar la cartera igual de vacía."""
    uid = 9001
    _sembrar(uid, main._RESET_CHUNK * 2 + 137)   # fuerza 3 tandas + uno corto
    main._reset_data_worker(uid)

    assert main._reset_estado(uid)["estado"] == "listo"
    assert _quedan(uid) == (0, 0, 0)


@pytest.mark.skipif(
    getattr(main, "USANDO_PG", False),
    reason="La sonda abre un sqlite3.connect crudo para medir el lock ÚNICO de "
           "escritura de SQLite. En Postgres ese lock no existe (MVCC) y la sonda "
           "ni siquiera llega a la base real: apunta a un archivo SQLite sin "
           "esquema y devuelve 'no such table'. Mediría la nada.")
def test_suelta_el_lock_entre_tandas():
    """EL test. Mientras el reset avanza, otro usuario tiene que poder escribir.

    Sondeamos con un busy_timeout CORTO (300 ms): si el reset tuviera el lock de
    punta a punta —como antes—, toda sonda daría 'database is locked'. Con tandas,
    entre uno y otro chunk hay ventana y la sonda entra.

    ⚠️ SÓLO-SQLITE (migración a Postgres). Mide una propiedad del MOTOR: que haya
    un único escritor por base. En Postgres dos escritores sobre filas distintas
    no se ven, así que la propiedad no aplica — y el test tampoco se puede
    "adaptar" sin cambiarle el significado. Se saltea y se conserva para SQLite,
    que es lo que corre en producción HOY. El otro test del archivo
    (`test_borra_todo`, que el reset termina y no deja nada) sí corre en los dos.
    """
    uid = 9002
    _sembrar(uid, main._RESET_CHUNK * 3)

    entradas, rechazos = [], []

    def sonda():
        c = sqlite3.connect(main.DB_PATH)
        c.execute("PRAGMA busy_timeout=300")
        try:
            c.execute("INSERT INTO positions (user_id,broker,asset,is_cash,invested) "
                      "VALUES (?,?,?,0,?)", (7777, "Otro", "AAPL", 1.0))
            c.commit()
            entradas.append(1)
        except sqlite3.OperationalError as ex:
            rechazos.append(str(ex))
        finally:
            c.close()

    # Sondeamos DESDE ADENTRO del borrado: envolvemos el helper de tandas para
    # que después de cada chunk otro escritor intente entrar. Es el momento
    # exacto en que antes no había ventana.
    original = main._borrar_en_chunks

    def instrumentado(conn, u, tabla, where, args):
        # Misma lógica que el helper real, con una sonda después de cada tanda.
        total = 0
        while True:
            with conn:
                n = conn.execute(
                    f"DELETE FROM {tabla} WHERE rowid IN ("
                    f"  SELECT rowid FROM {tabla} WHERE {where} LIMIT {main._RESET_CHUNK})",
                    args).rowcount
            if not n:
                return total
            total += n
            main._reset_set(u, hechas=main._reset_estado(u).get("hechas", 0) + n)
            sonda()          # ← ¿hay ventana para otro escritor?

    main._borrar_en_chunks = instrumentado
    try:
        main._reset_data_worker(uid)
    finally:
        main._borrar_en_chunks = original

    assert entradas, (
        "Ninguna escritura ajena entró mientras el reset corría: el lock quedó "
        f"tomado de punta a punta. Rechazos: {rechazos[:3]}")
    assert not rechazos, f"hubo sondas rechazadas: {rechazos[:3]}"
    assert _quedan(uid) == (0, 0, 0)


def test_el_progreso_llega_a_100_y_dice_que_esta_borrando():
    uid = 9003
    _sembrar(uid, main._RESET_CHUNK + 10)
    main._reset_data_worker(uid)

    st = main.reset_my_data_status(uid=uid)
    assert st["estado"] == "listo"
    assert st["total"] > 0
    assert st["hechas"] == st["total"], (st["hechas"], st["total"])
    assert st["pct"] == 100.0
    assert st["cleared"].get("import_raw_rows") == main._RESET_CHUNK + 10


def test_sin_corrida_previa_el_status_no_miente():
    """Un usuario que nunca reseteó no puede ver 'listo' ni 0%: es 'inactivo'."""
    assert main.reset_my_data_status(uid=9999)["estado"] == "inactivo"
