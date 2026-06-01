"""Tests del detector de snapshots V-shape corruptos (2026-06-01).

El detector tiene 2 tracks:
  Track 1: drop > 15% + recovery > 20% (caso original, conservador)
  Track 2: drop 5-15% + sin flujos + recovery >= 80% (caso real del bug
           del 31/may con fetch parcial de yfinance)
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _create_test_db():
    """DB temporal con tabla snapshots minimal."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            total_invested REAL NOT NULL DEFAULT 0,
            net_deposited REAL NOT NULL DEFAULT 0,
            fx_to_usd_blue REAL,
            UNIQUE(user_id, date)
        );
    """)
    conn.commit()
    return conn, tmp.name


def _insert(conn, uid, snaps):
    """snaps = [(date, total_value, net_deposited), ...]"""
    for d, v, nd in snaps:
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, net_deposited) "
            "VALUES (?, ?, ?, ?)",
            (uid, d, v, nd),
        )
    conn.commit()


class TestCorruptSnapshotDetector(unittest.TestCase):

    def setUp(self):
        self.conn, self.db_path = _create_test_db()

    def tearDown(self):
        self.conn.close()
        os.unlink(self.db_path)

    def _detect(self, uid):
        # Importamos late para que use la DB temporal del test
        from main import _detect_and_remove_corrupt_snapshots
        return _detect_and_remove_corrupt_snapshots(self.conn, uid)

    # ─── Track 2 (la heurística nueva) ─────────────────────────────────────

    def test_real_case_31may_corrupt_with_fetch_partial(self):
        """Caso real Nicolas 31/may: drop 6.2% + recovery 6.6% sin flujos →
        debe detectar como corrupto."""
        _insert(self.conn, 1, [
            ("2026-05-30", 8452.78, 7073.94),
            ("2026-05-31", 7924.23, 7073.94),  # ← corrupto
            ("2026-06-01", 8447.67, 7073.94),
        ])
        corrupt = self._detect(1)
        self.assertEqual(len(corrupt), 1, "Esperaba 1 corrupto, vi: " + str(corrupt))
        # Verificar que se borró
        remaining = self.conn.execute("SELECT date FROM snapshots WHERE user_id=1").fetchall()
        dates = [r["date"] for r in remaining]
        self.assertNotIn("2026-05-31", dates)
        self.assertIn("2026-05-30", dates)
        self.assertIn("2026-06-01", dates)

    def test_legit_loss_with_recovery_not_full_NOT_corrupt(self):
        """Pérdida real con recovery parcial NO se debe marcar como corrupto.
        Ej: día del crash + rebote pequeño al día siguiente."""
        _insert(self.conn, 1, [
            ("2026-04-01", 10000, 9000),
            ("2026-04-02", 9300, 9000),   # -7%
            ("2026-04-03", 9500, 9000),   # +2% recovery, solo 28% del drop
        ])
        corrupt = self._detect(1)
        self.assertEqual(corrupt, [], "No debería detectar — recovery muy parcial")

    def test_withdrawal_explains_drop_NOT_corrupt(self):
        """Si net_deposited cambió entre snapshots (retiro), el drop tiene
        explicación legítima → NO marcar como corrupto."""
        _insert(self.conn, 1, [
            ("2026-04-01", 10000, 9000),
            ("2026-04-02", 9300, 8300),   # value cayó pero net_dep también (retiro $700)
            ("2026-04-03", 9400, 8300),   # recupera
        ])
        corrupt = self._detect(1)
        self.assertEqual(corrupt, [], "Drop explicado por retiro, NO corrupto")

    def test_drop_4pct_NOT_corrupt(self):
        """Drop < 5% no entra en Track 2 (no es V-shape, es ruido normal)."""
        _insert(self.conn, 1, [
            ("2026-04-01", 10000, 9000),
            ("2026-04-02", 9650, 9000),   # -3.5%
            ("2026-04-03", 10000, 9000),  # recovery full
        ])
        corrupt = self._detect(1)
        self.assertEqual(corrupt, [], "Drop < 5%, debajo del threshold")

    # ─── Track 1 (heurística original, back-compat) ─────────────────────────

    def test_track1_extreme_v_shape_still_detected(self):
        """Caso original — drop 20% + recovery 25% — sigue detectado."""
        _insert(self.conn, 1, [
            ("2026-04-01", 10000, 7000),
            ("2026-04-02", 7800, 7000),   # -22%
            ("2026-04-03", 10100, 7000),  # +29% recovery
        ])
        corrupt = self._detect(1)
        self.assertEqual(len(corrupt), 1)

    # ─── Edge cases ────────────────────────────────────────────────────────

    def test_no_data_returns_empty(self):
        self.assertEqual(self._detect(1), [])

    def test_only_2_snapshots_returns_empty(self):
        """Necesita 3 snapshots mínimo para hacer V-shape detection."""
        _insert(self.conn, 1, [
            ("2026-04-01", 10000, 9000),
            ("2026-04-02", 9300, 9000),
        ])
        self.assertEqual(self._detect(1), [])

    def test_gap_more_than_2_days_track2_skipped(self):
        """Track 2 require gap ≤ 2 días. Si pasaron 5 días entre drop y
        recovery, no entra en Track 2."""
        _insert(self.conn, 1, [
            ("2026-04-01", 10000, 9000),
            ("2026-04-02", 9400, 9000),   # -6%
            ("2026-04-10", 10000, 9000),  # +6.4% pero 8 días después
        ])
        corrupt = self._detect(1)
        self.assertEqual(corrupt, [], "Gap > 2 días → no V-shape")


if __name__ == "__main__":
    unittest.main()
