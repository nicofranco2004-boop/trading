"""Vaciar tablas entre tests, en el orden que la base acepta. Una sola vez, acá.

POR QUÉ EXISTE. 22 archivos de test copiaban la misma limpieza:

    for t in ("snapshots", ..., "users", "brokers", ...):
        try: conn.execute(f"DELETE FROM {t}")
        except Exception: pass            # (o `conn.rollback()`)

y tenía tres agujeros que se tapaban entre sí:

  · EL ORDEN. `brokers.user_id REFERENCES users(id)` sin cascada, con
    `foreign_keys=ON` en los dos motores: si un test dejó un broker, borrar
    `users` antes que `brokers` falla SIEMPRE.
  · EL `except: pass`. En SQLite el usuario quedaba vivo sin avisar (por eso los
    tests usan un email distinto cada vez: era el parche del síntoma). En
    Postgres el error deja la transacción ENTERA abortada y el INSERT de abajo
    revienta con `InFailedSqlTransaction` (medido el 30/10/2026:
    test_audit_bloqueantes B5, rojo sólo en Postgres desde hacía días).
  · EL `rollback()` que algunas copias pusieron en su lugar deshace también los
    borrados de ANTES —fotos, posiciones, operaciones— en los dos motores: la
    limpieza no limpiaba y nadie lo veía.

QUÉ HACE `vaciar`. Le pregunta a la base qué tabla apunta a cuál (no a una lista
escrita a mano que se desactualiza), suma las hijas sin cascada de cada tabla
pedida —vaciar `users` implica vaciar `brokers`: si no, no se puede—, borra
hijas antes que madres y NO atrapa errores: una limpieza que no limpia tiene que
decirlo.
"""
import sqlite3


def _dependencias(conn):
    """{madre: {hijas que la apuntan SIN `ON DELETE CASCADE`}}, leído de la base.

    Las que tienen cascada no hacen falta: borrar la madre se lleva a las hijas.
    """
    deps = {}
    if isinstance(conn, sqlite3.Connection):
        tablas = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for hija in tablas:
            for fk in conn.execute(f'PRAGMA foreign_key_list("{hija}")'):
                madre, al_borrar = fk[2], (fk[6] or "").upper()
                if madre != hija and al_borrar != "CASCADE":
                    deps.setdefault(madre, set()).add(hija)
    else:
        filas = conn.execute(
            "SELECT h.relname, m.relname, c.confdeltype FROM pg_constraint c "
            "JOIN pg_class h ON h.oid = c.conrelid "
            "JOIN pg_class m ON m.oid = c.confrelid "
            "JOIN pg_namespace n ON n.oid = h.relnamespace "
            "WHERE c.contype = 'f' AND n.nspname = current_schema()").fetchall()
        for hija, madre, al_borrar in filas:
            if madre != hija and al_borrar != "c":
                deps.setdefault(madre, set()).add(hija)
    return deps


def orden_de_borrado(conn, tablas):
    """Las tablas pedidas más sus hijas sin cascada, cada hija antes que su madre."""
    deps = _dependencias(conn)
    orden, visitadas = [], set()

    def visitar(t):
        if t in visitadas:
            return
        visitadas.add(t)
        for hija in sorted(deps.get(t, ())):
            visitar(hija)
        orden.append(t)

    for t in tablas:
        visitar(t)
    return orden


def vaciar(conn, *tablas):
    """`DELETE FROM` de cada tabla (y de sus hijas sin cascada), sin commit."""
    for t in orden_de_borrado(conn, tablas):
        conn.execute(f"DELETE FROM {t}")
