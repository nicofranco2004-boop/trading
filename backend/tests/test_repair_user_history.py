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
        # Secuencia de snapshots NO destructiva del endpoint (sin _recalc, que
        # necesita operations; el recalc es el self-heal canónico cubierto aparte):
        # UPSERT fin de mes + net_deposited + borrar V-shapes + outliers de trayectoria.
        with self.conn:
            ps._backfill_snapshots_from_monthly(self.conn, self.uid)
            main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
            main._detect_and_remove_corrupt_snapshots(self.conn, self.uid)
            main._remove_trajectory_outlier_snapshots(self.conn, self.uid)

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

    def test_outlier_borra_contaminado_pero_no_diario_legitimo(self):
        # No destructivo: un snapshot diario con valor cerca del capital queda;
        # solo cae el contaminado (ratio absurdo).
        self._monthly(2026, 6, 0, 20000)
        self.conn.execute(
            "INSERT INTO snapshots (user_id,date,total_value,total_invested,net_deposited) VALUES (?,?,?,?,?)",
            (self.uid, "2026-06-10", 22000, 20000, 20000))  # ratio 1.1 → legítimo
        self.conn.execute(
            "INSERT INTO snapshots (user_id,date,total_value,total_invested,net_deposited) VALUES (?,?,?,?,?)",
            (self.uid, "2026-06-12", 400, 20000, 20000))     # ratio 0.02 → contaminado
        self.conn.commit()
        with self.conn:
            removed = main._remove_trajectory_outlier_snapshots(self.conn, self.uid)
        dates = [r["date"] for r in self.conn.execute(
            "SELECT date FROM snapshots WHERE user_id=?", (self.uid,))]
        self.assertEqual(len(removed), 1)
        self.assertIn("2026-06-10", dates)       # diario legítimo: queda
        self.assertNotIn("2026-06-12", dates)    # contaminado: se fue

    def test_mass_dry_run_no_toca_la_base_real(self):
        # _repair_snapshots_summary(apply=False) corre sobre una COPIA → la real
        # queda intacta (el snapshot contaminado SIGUE hasta que se aplique de verdad).
        self._monthly(2026, 6, 0, 20000)
        self.conn.execute(
            "INSERT INTO snapshots (user_id,date,total_value,total_invested,net_deposited) VALUES (?,?,?,?,?)",
            (self.uid, "2026-06-12", 400, 20000, 20000))
        self.conn.commit()
        summary = main._repair_snapshots_summary(self.conn, [self.uid], apply=False)
        self.assertTrue("users_changed" in summary)
        still = self.conn.execute(
            "SELECT COUNT(*) c FROM snapshots WHERE user_id=? AND total_value=400",
            (self.uid,)).fetchone()["c"]
        self.assertEqual(still, 1)   # dry-run NO tocó la base real

    def test_repair_idempotente_aunque_global_difiera_de_broker(self):
        # Reproduce los "13 que reaparecían": el agregado 'global' y la suma
        # per-broker tienen net_deposited DISTINTO (10000 vs 8000). _backfill setea
        # net_deposited desde 'global' y _recompute desde los brokers → se pisaban
        # cada corrida y el contador marcaba "a reparar" para siempre. Con la medición
        # antes/después, la 2da corrida NO debe reportar cambio.
        for broker, dep in (("global", 10000), ("Balanz", 8000)):
            self.conn.execute(
                """INSERT INTO monthly_entries
                     (user_id, broker, year, month, capital_inicio, deposits, withdrawals,
                      manual_deposits, manual_withdrawals, pnl_realized, pnl_unrealized, capital_final)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (self.uid, broker, 2026, 6, 0, dep, 0, dep, 0, 0, 0, dep))
        self.conn.commit()
        with self.conn:
            main._repair_user_snapshots(self.conn, self.uid)     # 1ra reparación
        with self.conn:
            r2 = main._repair_user_snapshots(self.conn, self.uid)  # 2da
        self.assertFalse(r2["changed"])   # idempotente: la 2da no marca cambio
        # y el resumen masivo tampoco la cuenta de nuevo
        s = main._repair_snapshots_summary(self.conn, [self.uid], apply=True)
        self.assertEqual(s["users_changed"], 0)


if __name__ == "__main__":
    unittest.main()
