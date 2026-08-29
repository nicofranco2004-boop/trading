"""Tests del CAGR histórico leído de SNAPSHOTS (Fase 2 — durable, consistente con el
chart). Verifica: TWRR desde snapshots, neutral a flujos, durabilidad (ignora el
monthly al costo), y fallback a monthly sin snapshots.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main


class CagrFromSnapshotsTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cagr@t", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _snap(self, date, val, dep):
        self.conn.execute(
            # `source='cron'` = lo que estampa el snapshot diario real. Sin eso la
            # fila es indistinguible de las que fabrica el import copiando la cadena
            # contable, y `twr.clasificar_fila` la descarta con razón.
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,?,?,?,'cron')", (self.uid, date, val, dep, dep))

    def _monthly(self, y, mo, ci, cf, dep=0):
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker, capital_inicio,
                   capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized)
               VALUES (?,?,?,'global',?,?,?,0,0,0)""", (self.uid, y, mo, ci, cf, dep))

    def test_cagr_from_snapshots_simple(self):
        self._snap("2024-08-31", 1000, 1000)
        self._snap("2024-09-30", 1100, 1000)   # +10% en un mes, sin flujos
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertEqual(r["months"], 1)
        self.assertAlmostEqual(r["cagr"], round((1.1 ** 12 - 1) * 100, 2), places=1)

    def test_flows_do_not_distort(self):
        # Depósito de 1000 entre meses NO debe inflar el retorno (TWRR ajusta por flujo).
        self._snap("2024-08-31", 1000, 1000)
        self._snap("2024-09-30", 2100, 2000)   # +1000 aporte, +100 ganancia real
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        # r_mes = (2100-1000-1000)/(1000+0.5*1000) = 100/1500 = 6.67% → no +110%
        self.assertLess(r["cagr"], 200)        # NO el disparate de value/dep
        self.assertGreater(r["cagr"], 0)

    def test_durable_ignores_cost_based_monthly(self):
        # Snapshots a MERCADO (suben) pero monthly al COSTO (plano) → el CAGR usa snapshots.
        self._snap("2024-08-31", 1000, 1000)
        self._snap("2024-09-30", 1220, 1000)
        self._snap("2024-10-31", 1500, 1000)
        for (y, mo) in [(2024, 8), (2024, 9), (2024, 10)]:
            self._monthly(y, mo, 1000, 1000)   # cost-based: 0% retorno
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertGreater(r["cagr"], 50)      # refleja la suba real, no el 0% del monthly

    def test_fallback_to_monthly_NO_publica_un_cagr(self):
        """⚠️ RONDA 11 · ESTE TEST AFIRMABA EL DEFECTO. `monthly_entries` de meses
        cerrados está AL COSTO (pnl_unrealized forzado a 0) — lo dice el docstring
        de `_cagr_from_monthly_rows`—, así que este fallback publicaba la cadena
        contable como si fuera el rendimiento de mercado. Medido: −78,34% anual el
        mismo día en que `twr.curva_indexada` medía 0,0% para esa cuenta.

        El número contable NO se tira: viaja con nombre propio (`cagr_contable_pct`)
        y con `basis`, para que nadie lo publique creyendo que es de mercado.
        """
        self._monthly(2024, 8, 1000, 1100)
        self._monthly(2024, 9, 1100, 1210)
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertIsNone(r["cagr"])
        self.assertEqual(r.get("basis"), "contable")
        self.assertTrue(r.get("reason"))
        self.assertIsNotNone(r.get("cagr_contable_pct"))
        self.assertGreater(r["cagr_contable_pct"], 0)

    def test_one_snapshot_falls_back(self):
        """Con una sola medición se cae al mismo fallback, y tampoco publica."""
        self._snap("2024-08-31", 1000, 1000)   # 1 solo fin de mes → fallback
        self._monthly(2024, 8, 1000, 1100)
        self._monthly(2024, 9, 1100, 1210)
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertIsNone(r["cagr"])           # el fallback ya no publica (ronda 11)
        self.assertEqual(r.get("basis"), "contable")

    def test_month_end_reduction(self):
        # Varios snapshots en un mes → solo cuenta el último (fin de mes).
        self._snap("2024-08-15", 1000, 1000)
        self._snap("2024-08-31", 1050, 1000)   # este es el de agosto
        self._snap("2024-09-30", 1100, 1000)
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertEqual(r["months"], 1)       # ago→sep = 1 período (no 2)


if __name__ == "__main__":
    unittest.main()
