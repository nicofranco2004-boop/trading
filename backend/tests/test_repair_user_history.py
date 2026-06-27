"""Repair de histórico: borra snapshots contaminados (de ciclos import/revert/
reimport) y regenera limpios desde monthly_entries — para que los % de 30d/anual
dejen de explotar (+5941%). Cubre el core de /api/admin/repair-user-history."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False); TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
import importing.persister as ps


class RepairUserHistoryTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "monthly_entries", "operations", "positions", "brokers", "users"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("repair@test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "Balanz", "ARS"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _monthly(self, y, m, dep, capf):
        # Insertamos por-broker (Balanz) Y el agregado 'global': _backfill_snapshots
        # lee 'global' (→ total_value) y _recompute_netdep lee broker<>'global'.
        for broker in ("Balanz", "global"):
            self.conn.execute(
                """INSERT INTO monthly_entries
                     (user_id, broker, year, month, capital_inicio, deposits, withdrawals,
                      pnl_realized, pnl_unrealized, capital_final)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (self.uid, broker, y, m, 0, dep, 0, 0, 0, capf))

    def _repair(self):
        # Misma secuencia de snapshots que el endpoint (sin _recalc, que necesita
        # operations; el recalc es el self-heal canónico ya cubierto aparte).
        with self.conn:
            self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
            ps._backfill_snapshots_from_monthly(self.conn, self.uid)
            main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
            main._detect_and_remove_corrupt_snapshots(self.conn, self.uid)

    def test_repair_borra_contaminado_y_regenera_limpio(self):
        # 3 meses: deposita y la cuenta crece (capital_final 10k → 19k → 22k).
        self._monthly(2026, 4, 10000, 10000)
        self._monthly(2026, 5, 8000, 19000)
        self._monthly(2026, 6, 0, 22000)
        # Snapshot CONTAMINADO: fecha intra-mes con total_value anómalo bajo (370),
        # como el que tomó el cron mientras la data estaba rota → rompe el % 30d.
        self.conn.execute(
            "INSERT INTO snapshots (user_id,date,total_value,total_invested,net_deposited) VALUES (?,?,?,?,?)",
            (self.uid, "2026-05-15", 370.0, 18000, 18000))
        self.conn.commit()

        self._repair()

        snaps = self.conn.execute(
            "SELECT date, total_value, net_deposited FROM snapshots WHERE user_id=? ORDER BY date",
            (self.uid,)).fetchall()
        byd = {s["date"]: s for s in snaps}
        # El contaminado desapareció (ni la fecha ni el valor 370 sobreviven).
        self.assertNotIn("2026-05-15", byd)
        self.assertFalse(any(abs((s["total_value"] or 0) - 370.0) < 1 for s in snaps))
        # Quedan SOLO los de fin de mes, con total_value = capital_final.
        self.assertEqual(byd["2026-04-30"]["total_value"], 10000)
        self.assertEqual(byd["2026-05-31"]["total_value"], 19000)
        self.assertEqual(byd["2026-06-30"]["total_value"], 22000)
        # net_deposited acumulado correcto (10k, 18k, 18k).
        self.assertEqual(byd["2026-05-31"]["net_deposited"], 18000)

    def test_repair_es_idempotente(self):
        self._monthly(2026, 4, 10000, 10500)
        self._monthly(2026, 5, 0, 11000)
        self._monthly(2026, 6, 0, 11200)
        self.conn.commit()
        self._repair()
        n1 = self.conn.execute("SELECT COUNT(*) c FROM snapshots WHERE user_id=?", (self.uid,)).fetchone()["c"]
        self._repair()
        n2 = self.conn.execute("SELECT COUNT(*) c FROM snapshots WHERE user_id=?", (self.uid,)).fetchone()["c"]
        self.assertEqual(n1, n2)   # re-correr no duplica ni rompe


if __name__ == "__main__":
    unittest.main()
