"""Reporte real (Bull Market): "No se pudo limpiar el broker: database is locked".
El wipe es una escritura pesada (deletes + rebackfill de snapshots) que puede chocar
con otro import/snapshot concurrente. Fix: busy_timeout más alto + _run_with_lock_retry
(reintento con backoff) sobre la operación idempotente."""
import os
import sqlite3
import tempfile
import unittest

import main


class LockRetryLogicTest(unittest.TestCase):
    def test_retries_then_succeeds(self):
        calls = {"n": 0}
        def flaky():
            calls["n"] += 1
            if calls["n"] <= 2:
                raise sqlite3.OperationalError("database is locked")
            return 42
        self.assertEqual(main._run_with_lock_retry(flaky, base_delay=0.001), 42)
        self.assertEqual(calls["n"], 3)

    def test_gives_up_and_reraises(self):
        def always():
            raise sqlite3.OperationalError("database is locked")
        with self.assertRaises(sqlite3.OperationalError):
            main._run_with_lock_retry(always, attempts=3, base_delay=0.001)

    def test_non_lock_error_not_retried(self):
        calls = {"n": 0}
        def other():
            calls["n"] += 1
            raise sqlite3.OperationalError("no such table: foo")
        with self.assertRaises(sqlite3.OperationalError):
            main._run_with_lock_retry(other, base_delay=0.001)
        self.assertEqual(calls["n"], 1)     # no reintenta errores que no son de lock


class RealLockContentionTest(unittest.TestCase):
    """Lock REAL de SQLite: una conexión toma el write-lock, otra reintenta hasta que
    se suelta. Reproduce el escenario del wipe chocando con otra escritura."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        c = sqlite3.connect(self.tmp.name)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
        c.commit(); c.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_retry_survives_real_write_lock(self):
        # Determinístico (sin threads): la conexión `holder` tiene el write-lock; en el
        # 3er intento "otra operación" lo suelta (holder.commit) y el writer entra.
        holder = sqlite3.connect(self.tmp.name)
        holder.execute("BEGIN IMMEDIATE")               # toma el write-lock
        holder.execute("INSERT INTO t (v) VALUES (1)")
        writer = sqlite3.connect(self.tmp.name)
        writer.execute("PRAGMA busy_timeout=50")        # falla rápido → fuerza el retry
        attempt = {"n": 0}
        def do_write():
            attempt["n"] += 1
            if attempt["n"] == 3:                       # el lock se suelta recién acá
                holder.commit()
            with writer:                                # intentos 1-2 → 'database is locked'
                writer.execute("INSERT INTO t (v) VALUES (2)")
            return "ok"
        self.assertEqual(main._run_with_lock_retry(do_write, attempts=6, base_delay=0.01), "ok")
        self.assertEqual(attempt["n"], 3)               # reintentó hasta que se soltó
        n = writer.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        holder.close(); writer.close()
        self.assertEqual(n, 2)                          # ambas escrituras entraron


if __name__ == "__main__":
    unittest.main()
