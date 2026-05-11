"""Tests del endpoint /api/bond-indices/{CER|UVA|A3500} — serie diaria de
índices para bonos AR ajustados. Corre con:
  cd backend && python3 -m pytest tests/test_bond_indices.py

Cubre:
- GET con date range, sin params, con date único.
- Validación de índice soportado, fechas ISO.
- Cache hit (consulta SQLite sin fetch externo).
- Cache miss + fallback graceful si la fuente externa falla.
- Datos persisten correctamente.

NO hace fetch real al BCRA / argentinadatos — mockea el HTTP.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _new_user(conn, email: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"),
    )
    return cur.lastrowid


def _seed_cer(conn, rows):
    """Inserta directamente en bond_indices_daily, bypassing el fetcher."""
    with conn:
        for date, value in rows:
            conn.execute(
                """INSERT OR REPLACE INTO bond_indices_daily
                   (index_name, date, value, source, updated_at)
                   VALUES ('CER', ?, ?, 'test', '2026-05-11T00:00:00Z')""",
                (date, value),
            )


class BondIndicesEndpointTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"cer-{self.id()}@rendi.test")
        conn.commit()
        # Limpiar índices entre tests para que no se contaminen
        with conn:
            conn.execute("DELETE FROM bond_indices_daily")
        conn.close()
        self.token = main.create_token(self.uid)
        # Marcar el cache como "ya fetcheado hace 1 minuto" para que no
        # intente fetch externo durante los tests (evita ruido + flakiness).
        main._indices_fetched['CER'] = main.time.time()

    def tearDown(self):
        main._indices_fetched.pop('CER', None)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.token}"})

    # ─── Happy path ──────────────────────────────────────────────────────────

    def test_returns_full_series_when_no_filter(self):
        conn = main.get_db()
        _seed_cer(conn, [
            ('2026-01-01', 100.0),
            ('2026-02-01', 105.0),
            ('2026-03-01', 110.0),
        ])
        conn.close()

        res = self._get("/api/bond-indices/CER")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["index_name"], "CER")
        self.assertEqual(body["count"], 3)
        self.assertEqual(body["series"]["2026-01-01"], 100.0)
        self.assertEqual(body["series"]["2026-03-01"], 110.0)
        self.assertEqual(body["latest_date"], "2026-03-01")

    def test_filters_by_date_range(self):
        conn = main.get_db()
        _seed_cer(conn, [
            ('2026-01-01', 100.0),
            ('2026-02-01', 105.0),
            ('2026-03-01', 110.0),
            ('2026-04-01', 115.0),
        ])
        conn.close()

        res = self._get("/api/bond-indices/CER?date_from=2026-02-01&date_to=2026-03-15")
        body = res.json()
        self.assertEqual(body["count"], 2)
        self.assertIn("2026-02-01", body["series"])
        self.assertIn("2026-03-01", body["series"])
        self.assertNotIn("2026-01-01", body["series"])
        self.assertNotIn("2026-04-01", body["series"])

    def test_single_date_shortcut(self):
        conn = main.get_db()
        _seed_cer(conn, [('2026-02-15', 107.5)])
        conn.close()

        res = self._get("/api/bond-indices/CER?date=2026-02-15")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["series"]["2026-02-15"], 107.5)

    # ─── Validación ──────────────────────────────────────────────────────────

    def test_unsupported_index_rejected(self):
        res = self._get("/api/bond-indices/FOO")
        self.assertEqual(res.status_code, 400)

    def test_invalid_date_format_rejected(self):
        res = self._get("/api/bond-indices/CER?date=15/02/2026")
        self.assertEqual(res.status_code, 422)

    def test_date_and_range_simultaneously_rejected(self):
        res = self._get("/api/bond-indices/CER?date=2026-02-15&date_from=2026-01-01")
        self.assertEqual(res.status_code, 400)

    def test_unauthorized_without_token(self):
        res = self.client.get("/api/bond-indices/CER")
        self.assertIn(res.status_code, (401, 403))

    # ─── Cache / fetch behavior ──────────────────────────────────────────────

    def test_empty_cache_returns_empty_series_no_500(self):
        """Sin data y sin BCRA → respuesta válida con series vacía, no error."""
        # Mockeo el fetcher para que NO traiga nada (simula BCRA fallando).
        main._indices_fetched.pop('CER', None)  # Reset TTL
        with patch.object(main, '_fetch_cer_series', return_value={}):
            res = self._get("/api/bond-indices/CER")
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertEqual(body["count"], 0)
            self.assertEqual(body["series"], {})
            self.assertIsNone(body["latest_date"])

    def test_fetcher_populates_cache_on_first_hit(self):
        """Cache miss → fetcher se invoca → datos se persisten en SQLite."""
        main._indices_fetched.pop('CER', None)
        fake_series = {
            '2026-01-01': 100.0,
            '2026-02-01': 105.0,
        }
        with patch.object(main, '_fetch_cer_series', return_value=fake_series):
            res = self._get("/api/bond-indices/CER")
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertEqual(body["count"], 2)

        # Verificar persistencia
        conn = main.get_db()
        rows = conn.execute(
            "SELECT date, value, source FROM bond_indices_daily WHERE index_name='CER'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["source"] == "argentinadatos" for r in rows))

    def test_cache_hit_skips_fetch(self):
        """TTL no expirado → no se invoca fetcher (cache hit)."""
        conn = main.get_db()
        _seed_cer(conn, [('2026-01-01', 100.0)])
        conn.close()
        # _indices_fetched ya fue marcado en setUp como reciente

        with patch.object(main, '_fetch_cer_series') as mock_fetch:
            res = self._get("/api/bond-indices/CER")
            self.assertEqual(res.status_code, 200)
            mock_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
