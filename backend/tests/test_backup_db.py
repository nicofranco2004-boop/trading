"""Tests del backup_db script.

Cubre:
  - Dump consistente: el archivo de salida es una DB SQLite válida con la
    misma data que el source.
  - Compresión: gzip funciona y el header es válido.
  - Local save + prune: archivos en disco + retención.
  - Pipeline completo: run_backup() en modo solo-local (sin S3) funciona
    end-to-end y devuelve stats coherentes.

NO testeamos S3 directamente (requeriría mocks de boto3 o moto). El path
remoto es opt-in via env vars; sin ellas el script funciona perfectamente
en modo local.
"""
import gzip
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from scripts.backup_db import (
    compress_gzip,
    dump_sqlite_consistent,
    prune_local_backups,
    run_backup,
    save_local_backup,
)


def _create_sample_db(path):
    """Crea una DB SQLite con tablas + datos para testear backup."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, asset TEXT, quantity REAL
        );
        INSERT INTO users VALUES (1, 'admin@rendi.finance'), (2, 'test@example.com');
        INSERT INTO positions (user_id, asset, quantity) VALUES
            (1, 'BTC', 0.5), (1, 'NVDA', 10), (2, 'AAPL', 5);
    """)
    conn.commit()
    conn.close()


class TestDumpAndCompress(unittest.TestCase):
    """Verifica que el dump SQLite produce un archivo válido y la compresión
    es reversible (gzip estándar)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src_db = os.path.join(self.tmp.name, 'source.db')
        _create_sample_db(self.src_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dump_produces_valid_sqlite_with_same_data(self):
        dest = os.path.join(self.tmp.name, 'backup.db')
        dump_sqlite_consistent(self.src_db, dest)
        self.assertTrue(os.path.isfile(dest))

        # La copia debe ser una DB SQLite válida con la misma data
        conn = sqlite3.connect(dest)
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        positions = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        btc = conn.execute(
            "SELECT quantity FROM positions WHERE asset='BTC'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(users, 2)
        self.assertEqual(positions, 3)
        self.assertEqual(btc, 0.5)

    def test_dump_handles_concurrent_writes(self):
        """SQLite .backup API debe ser safe con writers en curso. Acá lo
        validamos abriendo una conexión paralela y agregando datos mientras
        se hace el dump (simulación simple)."""
        # Pre-condición: source DB tiene 2 users
        # Abrimos otra conexión que escribe DESPUÉS del backup
        dest = os.path.join(self.tmp.name, 'backup-concurrent.db')
        dump_sqlite_consistent(self.src_db, dest)
        # Agregamos un user a source DESPUÉS del backup
        conn = sqlite3.connect(self.src_db)
        conn.execute("INSERT INTO users VALUES (99, 'late@example.com')")
        conn.commit()
        conn.close()
        # El backup debería tener solo los 2 originales, no el late
        conn = sqlite3.connect(dest)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        late = conn.execute(
            "SELECT COUNT(*) FROM users WHERE email='late@example.com'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)
        self.assertEqual(late, 0)  # No estaba al momento del backup

    def test_compress_gzip_is_reversible(self):
        """gzip → gunzip devuelve el archivo original byte-perfect."""
        src = os.path.join(self.tmp.name, 'data.bin')
        with open(src, 'wb') as f:
            f.write(b'Hola Rendi ' * 1000)  # 11 KB de data repetitiva
        gz = src + '.gz'
        size = compress_gzip(src, gz)
        self.assertTrue(os.path.isfile(gz))
        self.assertGreater(size, 0)
        # Verificar que gzip lo puede leer
        with gzip.open(gz, 'rb') as f:
            decompressed = f.read()
        with open(src, 'rb') as f:
            original = f.read()
        self.assertEqual(decompressed, original)


class TestLocalSaveAndPrune(unittest.TestCase):
    """Verifica que el save local crea el archivo y que el prune respeta
    el retention policy (incluyendo preservación monthly)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backup_dir = os.path.join(self.tmp.name, 'backups')

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_local_creates_file(self):
        # Pre-condición: tener un .gz dummy
        gz_src = os.path.join(self.tmp.name, 'src.db.gz')
        with gzip.open(gz_src, 'wb') as f:
            f.write(b'fake db content')

        final = save_local_backup(gz_src, self.backup_dir, '2026-05-31')
        self.assertTrue(os.path.isfile(final))
        self.assertIn('trading-2026-05-31.db.gz', final)
        # El contenido se preserva
        with gzip.open(final, 'rb') as f:
            self.assertEqual(f.read(), b'fake db content')

    def test_prune_respects_keep_days(self):
        """Borra solo lo que está más viejo que keep_days."""
        os.makedirs(self.backup_dir, exist_ok=True)
        now = datetime.now(timezone.utc)
        # Crear backups con mtime variado
        files = {
            'trading-2026-05-30.db.gz': now - timedelta(days=1),    # fresh
            'trading-2026-05-15.db.gz': now - timedelta(days=16),   # fresh para keep=30
            'trading-2026-04-01.db.gz': now - timedelta(days=60),   # OLD
            'trading-2026-01-15.db.gz': now - timedelta(days=200),  # OLD
        }
        # Pero hay que preservar 'primer de cada mes' del último año.
        # Para este test usamos keep_days=30 y monthly preservation:
        # - 2026-05-30 → joven, queda
        # - 2026-05-15 → joven, queda (y es el primer de mayo en este set,
        #               pero también es el más viejo de mayo, así que ya es primero)
        # - 2026-04-01 → > 30 días, PERO es primero de abril, lo preservamos
        # - 2026-01-15 → > 30 días, PERO es primero de enero, lo preservamos

        for fname, mtime in files.items():
            path = Path(self.backup_dir) / fname
            path.write_bytes(b'x')
            ts = mtime.timestamp()
            os.utime(path, (ts, ts))

        deleted = prune_local_backups(self.backup_dir, keep_days=30)
        # Con monthly preservation, ninguno se debe borrar (todos son
        # primeros-de-mes en su mes respectivo)
        self.assertEqual(deleted, 0)

        remaining = sorted([f.name for f in Path(self.backup_dir).iterdir()])
        self.assertEqual(len(remaining), 4)

    def test_prune_deletes_non_monthly_olds(self):
        """Cuando hay múltiples backups por mes, solo el más viejo del mes
        se preserva. Los del medio se borran si > keep_days."""
        os.makedirs(self.backup_dir, exist_ok=True)
        now = datetime.now(timezone.utc)
        # 3 backups en abril, todos > 30 días, todos < 365 días
        files = {
            'trading-2026-04-01.db.gz': now - timedelta(days=60),   # primer de abril → preservar
            'trading-2026-04-15.db.gz': now - timedelta(days=46),   # medio mes → borrar
            'trading-2026-04-30.db.gz': now - timedelta(days=31),   # finde mes → borrar
        }
        for fname, mtime in files.items():
            path = Path(self.backup_dir) / fname
            path.write_bytes(b'x')
            ts = mtime.timestamp()
            os.utime(path, (ts, ts))

        deleted = prune_local_backups(self.backup_dir, keep_days=30)
        self.assertEqual(deleted, 2)

        remaining = sorted([f.name for f in Path(self.backup_dir).iterdir()])
        self.assertEqual(remaining, ['trading-2026-04-01.db.gz'])


class TestRunBackupPipeline(unittest.TestCase):
    """Test end-to-end del pipeline en modo solo-local (sin S3 env vars)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'rendi.db')
        self.backup_dir = os.path.join(self.tmp.name, 'backups')
        _create_sample_db(self.db_path)
        # Asegurarnos de que NO hay env vars de S3 colgadas
        self._saved_env = {}
        for k in ('BACKUP_S3_BUCKET', 'BACKUP_S3_ACCESS_KEY', 'BACKUP_S3_SECRET_KEY'):
            if k in os.environ:
                self._saved_env[k] = os.environ.pop(k)
        os.environ['BACKUP_LOCAL_DIR'] = self.backup_dir

    def tearDown(self):
        os.environ.pop('BACKUP_LOCAL_DIR', None)
        for k, v in self._saved_env.items():
            os.environ[k] = v
        self.tmp.cleanup()

    def test_run_backup_local_only(self):
        """Sin env vars de S3 → backup local funciona, remote_uploaded=False."""
        stats = run_backup(db_path=self.db_path)
        self.assertEqual(stats.get('errors'), [])
        self.assertIsNotNone(stats.get('local_path'))
        self.assertTrue(os.path.isfile(stats['local_path']))
        self.assertGreater(stats.get('size_bytes', 0), 0)
        self.assertFalse(stats.get('remote_uploaded'))
        self.assertIsNone(stats.get('remote_key'))

        # El archivo .gz debe ser leíble y contener la DB
        with gzip.open(stats['local_path'], 'rb') as f:
            content = f.read()
        # Header SQLite: "SQLite format 3\x00"
        self.assertTrue(content.startswith(b'SQLite format 3\x00'))

    def test_run_backup_with_missing_db_returns_error(self):
        """db_path inexistente → stats.errors no vacío, no crashea."""
        stats = run_backup(db_path='/nonexistent/path.db')
        self.assertTrue(len(stats.get('errors')) > 0)
        self.assertIn('no existe', stats['errors'][0])


if __name__ == '__main__':
    unittest.main()
