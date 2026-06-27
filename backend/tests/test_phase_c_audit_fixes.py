"""Tests del audit fix C2: POST /api/snapshots NO debe hacer un fetch
sincrónico al dolarapi.com cuando el cache está stale.

Antes del fix: si _dolar_cache["data"] estaba vacío, el endpoint llamaba a
_fetch_dolar("blue") (timeout 5s) DENTRO del request — UX degradada en cada
snapshot manual cuando dolarapi laguea.

Después del fix: solo lee del cache. Si vacío, snapshot va con fx=NULL y el
cron diario lo hidrata después.

Esta verificación es a nivel de código (inspección del flujo) porque el
endpoint POST /api/snapshots requiere auth + FastAPI test client que no
está configurado en el resto de los tests. Acá testeamos directamente que
la función helper _persist_blue_for_date funciona con/sin valores y que el
flujo de stamping del snapshot endpoint NO invoca _fetch_dolar.
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


class TestPostSnapshotDoesNotBlock(unittest.TestCase):
    """Audit fix C2: el endpoint POST /api/snapshots no llama a _fetch_dolar
    sincrónicamente cuando el cache está stale.

    El test verifica esto leyendo el SOURCE del endpoint y asegurando que
    no contiene la llamada `_fetch_dolar(` dentro del bloque del POST.
    """

    def test_post_snapshot_source_does_not_call_fetch_dolar(self):
        """Source-level check: el cuerpo de post_snapshot no debe contener
        una llamada efectiva a _fetch_dolar (que es bloqueante con timeout 5s).

        Usamos AST parsing para filtrar comentarios (que sí pueden mencionar
        '_fetch_dolar' como referencia histórica del fix).
        """
        import ast
        main_py = os.path.join(BACKEND, 'main.py')
        with open(main_py, encoding='utf-8') as f:
            src = f.read()
        tree = ast.parse(src)

        # Localizar la función post_snapshot
        post_snapshot_fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'post_snapshot':
                post_snapshot_fn = node
                break
        self.assertIsNotNone(post_snapshot_fn, "No se encontró def post_snapshot")

        # Buscar Call nodes que invoquen _fetch_dolar dentro del body
        fetch_dolar_calls = []
        for node in ast.walk(post_snapshot_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == '_fetch_dolar':
                    fetch_dolar_calls.append(node.lineno)

        self.assertEqual(
            fetch_dolar_calls, [],
            f"audit fix C2 regresado: post_snapshot llama _fetch_dolar en "
            f"líneas {fetch_dolar_calls} (bloqueo sincrónico de 5s)"
        )

        # Pero SÍ debe leer del cache — verificamos con Subscript node
        reads_cache = False
        for node in ast.walk(post_snapshot_fn):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                if node.value.id == '_dolar_cache':
                    reads_cache = True
                    break
        self.assertTrue(
            reads_cache,
            "POST /api/snapshots debería leer _dolar_cache (cache hit-only)"
        )


class TestPersistBlueForDate(unittest.TestCase):
    """Test del helper _persist_blue_for_date — upsert idempotente en
    fx_rates_daily. Cubre los casos que el snapshot_job + POST /api/snapshots
    invocan implícitamente.
    """

    def setUp(self):
        # Aislamos cada test con su propia DB temporal y monkeypatchamos get_db
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE fx_rates_daily (
                date TEXT PRIMARY KEY,
                blue_venta REAL NOT NULL,
                mep_venta REAL,
                source TEXT DEFAULT 'unknown',
                fetched_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def _patch_get_db(self):
        """Devuelve un context manager que parcha main.get_db para apuntar
        a nuestra DB temporal en lugar de la real."""
        def fake_get_db():
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            return c
        return patch('main.get_db', side_effect=fake_get_db)

    def test_persist_inserts_new_row(self):
        from main import _persist_blue_for_date
        with self._patch_get_db():
            result = _persist_blue_for_date('2026-02-15', 1425.5, source='dolarapi')
        self.assertTrue(result)
        # Verificar persistencia
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT blue_venta, source FROM fx_rates_daily WHERE date='2026-02-15'"
        ).fetchone()
        c.close()
        self.assertIsNotNone(row)
        self.assertEqual(row['blue_venta'], 1425.5)
        self.assertEqual(row['source'], 'dolarapi')

    def test_persist_upserts_existing(self):
        """Si la fecha ya existe, el último valor gana (overwrite)."""
        from main import _persist_blue_for_date
        with self._patch_get_db():
            _persist_blue_for_date('2026-02-15', 1400, source='argentinadatos')
            _persist_blue_for_date('2026-02-15', 1425.5, source='dolarapi')
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT blue_venta, source FROM fx_rates_daily WHERE date='2026-02-15'"
        ).fetchall()
        c.close()
        self.assertEqual(len(rows), 1)  # No duplica
        self.assertEqual(rows[0]['blue_venta'], 1425.5)  # último valor
        self.assertEqual(rows[0]['source'], 'dolarapi')  # último source

    def test_persist_skips_invalid_blue(self):
        """blue=None / 0 / negativo no debe insertar nada."""
        from main import _persist_blue_for_date
        with self._patch_get_db():
            self.assertFalse(_persist_blue_for_date('2026-02-15', None))
            self.assertFalse(_persist_blue_for_date('2026-02-15', 0))
            self.assertFalse(_persist_blue_for_date('2026-02-15', -100))
        c = sqlite3.connect(self.db_path)
        cnt = c.execute("SELECT COUNT(*) FROM fx_rates_daily").fetchone()[0]
        c.close()
        self.assertEqual(cnt, 0)

    def test_persist_skips_empty_date(self):
        """date vacío / None no debe insertar."""
        from main import _persist_blue_for_date
        with self._patch_get_db():
            self.assertFalse(_persist_blue_for_date('', 1400))
            self.assertFalse(_persist_blue_for_date(None, 1400))


if __name__ == '__main__':
    unittest.main()
