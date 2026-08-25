"""FASE 4b — el rendimiento ANUAL y MENSUAL de Reportes deja de ser contable.

Para un mes CERRADO, `start` y `end` salen de la MISMA fila de monthly_entries
(builder.py:386-387), y `_repair_monthly_chain` (main.py:9316-9318) garantiza
    capital_final = capital_inicio + deposits - withdrawals + pnl_realized
con lo cual `end - start - flows` es, algebraicamente, `pnl_realized` y nada más.
Por eso una cuenta que vendió con ganancia y después se derrumbó a mercado
publicaba un año POSITIVO, y "9 de 12 meses positivos" perdiendo plata.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
from reporting import builder


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("rep@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,100,?)",
            (self.uid, "IBKR", "AAPL", "2024-01-01"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def me(self, y, m, ci, cf, dep=0.0, wd=0.0, rz=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,?,?,?,0)", (self.uid, y, m, ci, cf, dep, wd, rz))
        self.conn.commit()

    def snap(self, d, v, source="cron"):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,?,?,?)",
            (self.uid, d, v, v, source, 1200.0, "[]"))
        self.conn.commit()

    def metrics(self, ptype, start, end, live=None):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, ptype, start, end, "global", None, live_value=live)
        return m


class AnualTest(_Base):
    """Vendió US$3.600 con ganancia; a mercado la cartera se derrumbó."""
    def _cuenta_que_vendio_con_ganancia_y_se_derrumbo(self):
        # Contabilidad: 100.000 → 103.600 (todo pnl_realized). Sin aportes.
        self.me(2025, 1, 100000.0, 101200.0, rz=1200.0)
        self.me(2025, 6, 101200.0, 102400.0, rz=1200.0)
        self.me(2025, 12, 102400.0, 103600.0, rz=1200.0)

    def test_sin_bordes_medidos_sigue_siendo_contable_y_lo_dice(self):
        self._cuenta_que_vendio_con_ganancia_y_se_derrumbo()
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertEqual(m.basis, "contable")
        # El defecto reproducido: +3,6% que es exactamente lo realizado sobre costo.
        self.assertAlmostEqual(m.delta_usd, 3600.0, places=1)

    def test_con_bordes_medidos_el_anual_mide_el_MERCADO(self):
        self._cuenta_que_vendio_con_ganancia_y_se_derrumbo()
        # A mercado: arrancó en 100.000 y terminó en 62.000.
        self.snap("2024-12-31", 100000.0)
        self.snap("2025-12-30", 62000.0)
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertEqual(m.basis, "mercado")
        self.assertAlmostEqual(m.start_value, 100000.0, places=1)
        self.assertAlmostEqual(m.end_value, 62000.0, places=1)
        self.assertLess(m.delta_usd, 0)               # NO "+3.600"
        self.assertLess(m.delta_pct, 0)               # NO "+3,6%"

    def test_el_anual_no_puede_contradecir_a_diagnostico(self):
        """Criterio de aceptación: Diagnóstico y Reportes no pueden dar distinto
        para el mismo período. El anual sale del MISMO `twr.curva_indexada`."""
        import twr
        self._cuenta_que_vendio_con_ganancia_y_se_derrumbo()
        # Cadencia real del cron: un cierre por mes (huecos < max_hueco_dias, así
        # que la serie es un solo tramo y el TWR se puede encadenar).
        import calendar as _c
        valor = 100000.0
        self.snap("2024-12-31", valor)
        for mes in range(1, 13):
            valor *= 0.9605                      # el mercado la va bajando
            self.snap(f"2025-{mes:02d}-{_c.monthrange(2025, mes)[1]:02d}", round(valor, 2))
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        # Misma ventana que usa el builder: el borde de apertura cae ANTES del 1/1.
        c = twr.curva_indexada(self.conn, self.uid, "2024-12-27", "2025-12-31")
        self.assertIsNotNone(c["twr"])
        self.assertIsNotNone(m.delta_pct)
        self.assertAlmostEqual(m.delta_pct, round(c["twr"] * 100, 2), places=2)
        self.assertLess(m.delta_pct, 0)          # NO "+3,6%"

    def test_dos_mediciones_muy_separadas_NO_dan_cero(self):
        """Con un hueco de casi un año la serie se parte y no hay tramo medible.
        Devolver 0,0% ahí sería publicar "el año fue plano" sin haber medido nada
        — la misma clase de defecto, con otro disfraz."""
        import twr
        self._cuenta_que_vendio_con_ganancia_y_se_derrumbo()
        self.snap("2024-12-31", 100000.0)
        self.snap("2025-12-30", 62000.0)
        c = twr.curva_indexada(self.conn, self.uid, "2024-12-27", "2025-12-31")
        self.assertIsNone(c["twr"])
        self.assertIn(c["motivo"], ("serie_partida", "sin_tramo_continuo"))
        self.assertTrue(c["motivo_texto"])

    def test_una_sola_punta_medida_NO_alcanza(self):
        """Mezclar bases es lo que fabrica el fantasma: con un solo borde medido
        se sigue con la contabilidad, no con una punta de cada lado."""
        self._cuenta_que_vendio_con_ganancia_y_se_derrumbo()
        self.snap("2025-12-30", 62000.0)      # sólo el cierre
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertEqual(m.basis, "contable")
        self.assertAlmostEqual(m.start_value, 100000.0, places=1)

    def test_una_foto_FABRICADA_no_sirve_de_borde(self):
        self._cuenta_que_vendio_con_ganancia_y_se_derrumbo()
        self.snap("2024-12-31", 100000.0, source="import")
        self.snap("2025-12-30", 62000.0, source="import")
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertEqual(m.basis, "contable")

    def test_una_foto_RECONSTRUIDA_a_mercado_SI_sirve(self):
        """El objetivo de negocio: el que importa su historial obtiene valor."""
        self._cuenta_que_vendio_con_ganancia_y_se_derrumbo()
        for d, v in (("2024-12-31", 100000.0), ("2025-12-30", 62000.0)):
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                "net_deposited, source, mtm_coverage) VALUES (?,?,?,?,0,'mtm_backfill',0.9)",
                (self.uid, d, v, v))
        self.conn.commit()
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertEqual(m.basis, "mercado")
        self.assertLess(m.delta_usd, 0)


class MensualTest(_Base):
    def test_mes_cerrado_con_bordes_medidos_mide_mercado(self):
        # Contable: el mes "gana" 500 porque vendió con ganancia.
        self.me(2025, 6, 50000.0, 50500.0, rz=500.0)
        self.snap("2025-05-31", 50000.0)
        self.snap("2025-06-30", 44000.0)      # a mercado, cayó
        m = self.metrics("month", "2025-06-01", "2025-06-30")
        self.assertEqual(m.basis, "mercado")
        self.assertAlmostEqual(m.end_value, 44000.0, places=1)
        self.assertLess(m.delta_usd, 0)

    def test_mes_cerrado_sin_bordes_queda_contable_sin_regresion(self):
        self.me(2025, 6, 50000.0, 50500.0, rz=500.0)
        m = self.metrics("month", "2025-06-01", "2025-06-30")
        self.assertEqual(m.basis, "contable")
        self.assertAlmostEqual(m.start_value, 50000.0, places=1)
        self.assertAlmostEqual(m.end_value, 50500.0, places=1)

    def test_con_filtro_de_broker_no_se_usan_snapshots(self):
        """Los snapshots son por USUARIO, no por broker: con un filtro activo la
        pregunta no se puede responder y se sigue con la contabilidad."""
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'IBKR',2025,6,50000,50500,0,0,500,0)", (self.uid,))
        self.conn.commit()
        self.snap("2025-05-31", 50000.0)
        self.snap("2025-06-30", 44000.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2025-06-01", "2025-06-30", "IBKR", None)
        self.assertEqual(m.basis, "contable")
        self.assertAlmostEqual(m.end_value, 50500.0, places=1)


if __name__ == "__main__":
    unittest.main()
