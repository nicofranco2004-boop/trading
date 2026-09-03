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
        # ⚠️ YA NO SE ANUALIZA UN MES. Este test fijaba `1,1 ** 12` — el retorno de
        # un mes elevado a la doceava potencia—, que es justo lo que producía
        # "+16.841 % anual" en producción. El motor canónico no anualiza bajo medio
        # año; lo que se publica es el ACUMULADO del período, con su ventana.
        self.assertIsNone(r["cagr"])
        self.assertAlmostEqual(r["total_return_pct"], 10.0, places=1)

    def test_flows_do_not_distort(self):
        # Depósito de 1000 entre meses NO debe inflar el retorno (TWRR ajusta por flujo).
        self._snap("2024-08-31", 1000, 1000)
        self._snap("2024-09-30", 2100, 2000)   # +1000 aporte, +100 ganancia real
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        # r_mes = (2100-1000-1000)/(1000+0.5*1000) = 100/1500 = 6.67% → no +110%
        self.assertIsNone(r["cagr"])           # < medio año: no se anualiza
        self.assertLess(r["total_return_pct"], 200)   # NO el disparate de value/dep
        self.assertGreater(r["total_return_pct"], 0)

    def test_durable_ignores_cost_based_monthly(self):
        # Snapshots a MERCADO (suben) pero monthly al COSTO (plano) → el CAGR usa snapshots.
        self._snap("2024-08-31", 1000, 1000)
        self._snap("2024-09-30", 1220, 1000)
        self._snap("2024-10-31", 1500, 1000)
        for (y, mo) in [(2024, 8), (2024, 9), (2024, 10)]:
            self._monthly(y, mo, 1000, 1000)   # cost-based: 0% retorno
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        # refleja la suba real (no el 0 % de la cadena al costo), sin anualizar:
        # 1000 → 1500 con el aportado quieto es exactamente +50 %.
        self.assertAlmostEqual(r["total_return_pct"], 50.0, places=6)

    def test_fallback_to_monthly_NO_publica_un_cagr(self):
        """⚠️ RONDA 11 · ESTE TEST AFIRMABA EL DEFECTO. `monthly_entries` de meses
        cerrados está AL COSTO (pnl_unrealized forzado a 0) — lo dice el docstring
        de `_cagr_from_monthly_rows`—, así que este fallback publicaba la cadena
        contable como si fuera el rendimiento de mercado. Medido: −78,34% anual el
        mismo día en que `twr.curva_indexada` medía 0,0% para esa cuenta.

        (El fallback a `monthly_entries` ya no existe: la historia contable se ve
        con el modo ESTIMADO del mismo motor, no con un campo aparte.)
        y con `basis`, para que nadie lo publique creyendo que es de mercado.
        """
        self._monthly(2024, 8, 1000, 1100)
        self._monthly(2024, 9, 1100, 1210)
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertIsNone(r["cagr"])
        # `basis` desapareció: el motor ya no cae a `monthly_entries`, y el campo
        # con la regla ahora se llama `base_del_twr` (mercado|contable).
        self.assertIsNone(r.get("total_return_pct"))
        self.assertTrue(r.get("reason"))
        # `cagr_contable_pct` era del fallback a `monthly_entries`, que ya no existe:
        # la historia contable se expone por el modo ESTIMADO, no por un campo
        # aparte. Lo que este test protege —que el CERTERO no publique un número
        # sacado de la contabilidad— sigue valiendo.
        self.assertIsNone(r.get("total_return_pct"))
        self.assertEqual(r.get("base_del_twr"), "mercado")
        self.assertTrue(r.get("reason"))

    def test_one_snapshot_falls_back(self):
        """Con una sola medición se cae al mismo fallback, y tampoco publica."""
        self._snap("2024-08-31", 1000, 1000)   # 1 solo fin de mes → fallback
        self._monthly(2024, 8, 1000, 1100)
        self._monthly(2024, 9, 1100, 1210)
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertIsNone(r["cagr"])           # el fallback ya no publica (ronda 11)
        # `basis` desapareció: el motor ya no cae a `monthly_entries`, y el campo
        # con la regla ahora se llama `base_del_twr` (mercado|contable).
        self.assertIsNone(r.get("total_return_pct"))

    def test_month_end_reduction(self):
        # Varios snapshots en un mes → solo cuenta el último (fin de mes).
        self._snap("2024-08-15", 1000, 1000)
        self._snap("2024-08-31", 1050, 1000)   # este es el de agosto
        self._snap("2024-09-30", 1100, 1000)
        self.conn.commit()
        r = main._historical_cagr_global(self.conn, self.uid)
        # ⚠️ YA NO SE REDUCE A FIN DE MES. El motor canónico usa TODOS los puntos
        # medidos (la serie es diaria), así que la ventana arranca el 15/08 y no el
        # 31/08: 46 días ≈ 2 meses. Reducir a fin de mes era una limitación del
        # motor viejo, no una decisión — tiraba mediciones reales.
        self.assertEqual(r["months"], 2)
        self.assertEqual(r["desde"], "2024-08-15")


if __name__ == "__main__":
    unittest.main()
