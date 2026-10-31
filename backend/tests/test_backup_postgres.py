"""El backup nocturno con Postgres: un volcado que se puede restaurar y un «OK»
que no miente.

Hasta el 31/10/2026 el backup copiaba SIEMPRE el archivo SQLite. Con
`DATABASE_URL` la app escribe en Postgres y ese archivo queda congelado el día
del pasaje: el backup habría seguido diciendo «Backup OK» sobre una base que ya
no usa nadie (tests/test_escritores_solo_sqlite.py).

Por el camino real:
  · el trabajo nocturno de verdad (`main._run_backup_db_job`) con la base de la
    app: deja un volcado de Postgres, el registro dice motor, tablas, filas de
    `users` y `operations` y tamaño, y NO deja una copia del SQLite;
  · LA PRUEBA DE RECUPERACIÓN: ese volcado se restaura en una base vacía con
    `pg_restore` y las filas de cada tabla coinciden con el original;
  · las fallas son fuertes y nunca caen al SQLite: sin `pg_dump`, con un
    `pg_dump` más viejo que el servidor, con un esquema vacío;
  · y con SQLite, un archivo que no cambia hace días no es «OK».
"""
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import pgsesion  # noqa: E402
from scripts import backup_db  # noqa: E402

PG = bool(getattr(main, "USANDO_PG", False))


def _bin_del_postgres_local():
    """Las herramientas del Postgres de las pruebas (paquete `pgserver`), o None."""
    try:
        import pgserver
    except ImportError:
        return None
    d = os.path.join(os.path.dirname(pgserver.__file__), "pginstall", "bin")
    return d if os.path.isfile(os.path.join(d, "pg_restore")) else None


BIN = _bin_del_postgres_local()


def _con_base(dsn: str, base: str) -> str:
    """El mismo DSN (key=value) apuntando a otra base, sin el search_path del módulo."""
    sin_opciones = re.sub(r"options='[^']*'|options=\S+", "", dsn)
    return re.sub(r"dbname=\S+", f"dbname={base}", sin_opciones)


@unittest.skipUnless(PG and BIN, "el volcado de Postgres necesita Postgres y pg_dump local")
class ElBackupDePostgres(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"BACKUP_LOCAL_DIR": self.tmp.name, "BACKUP_PG_BIN": BIN}
        for k in ("BACKUP_S3_BUCKET", "BACKUP_S3_ACCESS_KEY", "BACKUP_S3_SECRET_KEY"):
            env[k] = ""
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        conn = main.get_db()
        try:
            for i in range(3):
                uid = conn.execute(
                    "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                    (f"backup-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
                for d in ("2026-01-02", "2026-02-03"):
                    conn.execute("INSERT INTO operations (user_id, date, broker, asset, op_type) "
                                 "VALUES (?,?,?,?,?)", (uid, d, "IBKR", "AAPL", "Venta"))
            conn.commit()
            self.esquema = conn.execute("SELECT current_schema()").fetchone()[0]
        finally:
            conn.close()

    def _conteos(self, dsn, esquema):
        with pgsesion.conectar(dsn, autocommit=True) as c:
            tablas = [r[0] for r in c.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type='BASE TABLE'", (esquema,)).fetchall()]
            return {t: c.execute(f'SELECT count(*) FROM "{esquema}"."{t}"').fetchone()[0]
                    for t in tablas}

    def _archivos(self, patron):
        return sorted(f for f in os.listdir(self.tmp.name) if re.match(patron, f))

    def test_el_nocturno_vuelca_postgres_y_lo_dice(self):
        with self.assertLogs("backup_db", level=logging.INFO) as reg:
            main._run_backup_db_job()
        linea = [m for m in reg.output if "Backup" in m][-1]
        print(f"\n>>> {linea}")
        self.assertIn("Backup OK", linea)
        self.assertIn("motor=postgres", linea)
        self.assertRegex(linea, r"users=\d+ operations=\d+")
        self.assertRegex(linea, r"size=\d+ bytes")
        self.assertEqual(len(self._archivos(r"rendi-pg-\d{4}-\d{2}-\d{2}\.dump$")), 1)
        self.assertEqual(self._archivos(r"trading-"), [],
                         "con Postgres copió el SQLite: es una base congelada")

    def test_la_recuperacion_trae_las_mismas_filas_en_cada_tabla(self):
        stats = backup_db.run_backup(dsn=main.DATABASE_URL)
        self.assertEqual(stats["errors"], [])
        base = f"restaurar_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        adm = pgsesion.conectar(_con_base(main.DATABASE_URL, "postgres"), autocommit=True)
        adm.execute(f'CREATE DATABASE "{base}"')
        try:
            destino = _con_base(main.DATABASE_URL, base)
            p = subprocess.run([os.path.join(BIN, "pg_restore"), "--no-owner", "--no-privileges",
                                "--exit-on-error", "--dbname", destino, stats["local_path"]],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(p.returncode, 0, p.stderr[-2000:])
            original = self._conteos(main.DATABASE_URL, self.esquema)
            restaurado = self._conteos(destino, self.esquema)
        finally:
            adm.execute(f'DROP DATABASE IF EXISTS "{base}" WITH (FORCE)')
            adm.close()
        print(f"\n>>> recuperación: {len(restaurado)} tablas restauradas, "
              f"users={restaurado.get('users')} operations={restaurado.get('operations')}")
        self.assertEqual(restaurado, original)
        self.assertEqual(stats["conteos"], original,
                         "lo que dice el registro no es lo que trae el archivo")
        self.assertGreaterEqual(restaurado["users"], 3)
        self.assertGreaterEqual(restaurado["operations"], 6)

    def test_sin_pg_dump_falla_y_no_copia_el_sqlite(self):
        vacia = tempfile.mkdtemp(dir=self.tmp.name)
        sqlite_viejo = os.path.join(self.tmp.name, "congelado.db")
        sqlite3.connect(sqlite_viejo).close()
        with mock.patch.dict(os.environ, {"BACKUP_PG_BIN": vacia}), \
                mock.patch.object(main, "DB_PATH", sqlite_viejo), \
                self.assertLogs("backup_db", level=logging.ERROR) as reg:
            main._run_backup_db_job()
        print(f"\n>>> sin pg_dump: {reg.output[-1][:200]}")
        self.assertIn("pg_dump/pg_restore no están instalados", reg.output[-1])
        self.assertEqual(self._archivos(r"(trading-|rendi-pg-)"), [])

    def test_un_pg_dump_mas_viejo_que_el_servidor_falla(self):
        falsa = tempfile.mkdtemp(dir=self.tmp.name)
        for nombre in ("pg_dump", "pg_restore"):
            ruta = os.path.join(falsa, nombre)
            with open(ruta, "w") as f:
                f.write("#!/bin/sh\necho 'pg_dump (PostgreSQL) 9.6.1'\n")
            os.chmod(ruta, 0o755)
        with mock.patch.dict(os.environ, {"BACKUP_PG_BIN": falsa}):
            stats = backup_db.run_backup(dsn=main.DATABASE_URL)
        self.assertTrue(any("hay que subir la versión" in e for e in stats["errors"]),
                        stats["errors"])

    def test_un_esquema_sin_tablas_no_es_ok(self):
        esquema = f"vacio_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        adm = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
        adm.execute(f'CREATE SCHEMA "{esquema}"')
        try:
            dsn = _con_base(main.DATABASE_URL, re.search(r"dbname=(\S+)", main.DATABASE_URL).group(1))
            dsn += f" options='-c search_path={esquema}'"
            stats = backup_db.run_backup(dsn=dsn)
        finally:
            adm.execute(f'DROP SCHEMA "{esquema}" CASCADE')
            adm.close()
        self.assertTrue(any("volcado vacío" in e for e in stats["errors"]), stats["errors"])


class UnSQLiteCongeladoNoEsOK(unittest.TestCase):

    def test_un_sqlite_que_no_cambia_hace_dias_no_es_ok(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"BACKUP_LOCAL_DIR": os.path.join(d, "b"),
                                             "BACKUP_S3_BUCKET": ""}):
            db = os.path.join(d, "trading.db")
            c = sqlite3.connect(db)
            c.execute("CREATE TABLE users (id INTEGER)")
            c.execute("INSERT INTO users VALUES (1)")
            c.commit()
            c.close()
            hace_tres_dias = time.time() - 3 * 86400
            os.utime(db, (hace_tres_dias, hace_tres_dias))
            stats = backup_db.run_backup(db_path=db)
        self.assertEqual(stats["motor"], "sqlite")
        self.assertTrue(any("no cambia hace" in e for e in stats["errors"]), stats["errors"])
        self.assertEqual(stats["filas"]["users"], 1)


if __name__ == "__main__":
    unittest.main()
