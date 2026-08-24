"""Fase 4 del audit de variaciones (AUDIT_variaciones_2026-07-08.md) — motor de
reportes. Escenarios numéricos del audit como regresión:

- C-2: el período EN CURSO comparaba capital_inicio A COSTO contra un end MtM
  (live) → fabricaba el unrealized histórico como "P&L del mes/año".
- C-3: mes en curso SIN fila monthly → start 0 → "P&L del mes" = cartera entera.
- H-8: day/week con filtro de broker usaban snapshots GLOBALES → delta del
  portfolio entero mostrado como del broker.
- H-7: los Δ chips del summary pasaban netdep SIN baseline contra snapshots CON
  baseline → delta inflado en exactamente el baseline.
"""
import unittest
from datetime import datetime, timedelta

import main
from reporting.builder import compute_metrics_for_period, parse_period_bounds


def _new_user(conn, email):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)", (email, "x"),
    )
    return cur.lastrowid


def _iso(d):
    return d.strftime("%Y-%m-%d")


class VariacionesF4Test(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("monthly_entries", "snapshots", "operations", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(self.conn, f"f4-{id(self)}@rendi.test")
        self.now = datetime.utcnow()
        self.y, self.m = self.now.year, self.now.month
        self.month_key = f"{self.y:04d}-{self.m:02d}"
        self.month_start = f"{self.y:04d}-{self.m:02d}-01"
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _metrics(self, period_type, period_key, broker="global", live=None):
        start, end = parse_period_bounds(period_type, period_key)
        m, _ops = compute_metrics_for_period(
            self.conn, self.uid, period_type, start, end, broker,
            bench=None, live_value=live)
        return m

    def _metrics_month(self, live, broker="global"):
        return self._metrics("month", self.month_key, broker, live)

    def test_c2_mes_en_curso_start_mtm_no_costo(self):
        """Compra en feb 10k que hoy vale 13k; el mes actual FLAT → delta ≈ 0
        (ANTES: capital_inicio a costo 10k vs live 13k → '+3.000 (+30%)')."""
        # Cadena monthly A COSTO: el mes actual arranca en 10.000 (costo).
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, self.y, self.m))
        # Snapshot MtM del cierre del mes pasado: la cartera YA valía 13.000.
        # AUDIT D-1: tiene que ser un cierre MEDIDO (`source='cron'`). Sin esa
        # marca, una fila de fin de mes es indistinguible de la que fabrica
        # `_backfill_snapshots_from_monthly` al costo — ver el test de abajo.
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,13000,10000,10000,'cron')", (self.uid, prev_close))
        self.conn.commit()
        m = self._metrics_month(live=13000.0)
        self.assertAlmostEqual(m.start_value, 13000.0, delta=1)   # MtM, no 10.000
        self.assertAlmostEqual(m.delta_usd, 0.0, delta=1)          # NO +3.000
        self.assertFalse(m.basis_incomparable)                     # base sana
        if m.delta_pct is not None:
            self.assertLess(abs(m.delta_pct), 1.0)                 # NO +30%

    def test_d1_snapshot_sintetico_no_sirve_de_borde(self):
        """AUDIT D-1: el caso del usuario — −63,37% / −US$127.486 con 0 ops.

        El único snapshot del borde lo fabricó el import copiando `capital_final`
        (la cadena AL COSTO). C-2 lo aceptaba como si fuera mercado, así que el
        parche quedaba sin efecto justo en las cuentas que más lo necesitaban:
        start 201.119 (contabilidad) − end 73.764 (mercado) − 131 de aportes
        = −127.486, y Modified Dietz lo publicaba como −63,37%.
        Ahora esa resta no se publica.
        """
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',131,0,0,-2233,201119,199017)""",
            (self.uid, self.y, self.m))
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,201119,201119,201119,'import')", (self.uid, prev_close))
        self.conn.commit()
        m = self._metrics_month(live=73764.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct)        # NO −63,37%
        self.assertEqual(m.delta_usd, 0.0)    # NO −US$127.486
        # Lo medible sigue publicándose tal cual.
        self.assertAlmostEqual(m.deposits, 131.0, delta=1)
        self.assertAlmostEqual(m.end_value, 73764.0, delta=1)

    def test_d1_sin_snapshot_de_borde_no_publica_el_delta(self):
        """Sin NINGÚN snapshot, start cae en la cadena contable (capital_inicio).
        Ese par costo-vs-mercado es el que fabricaba la pérdida fantasma."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,201119,201119)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=73764.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct)
        self.assertEqual(m.delta_usd, 0.0)

    def test_d1_borde_viejo_no_sirve(self):
        """Un cierre medido pero de hace 3 semanas mete mercado ajeno al período."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, self.y, self.m))
        viejo = _iso(datetime(self.y, self.m, 1) - timedelta(days=21))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,13000,10000,10000,'cron')", (self.uid, viejo))
        self.conn.commit()
        m = self._metrics_month(live=13000.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct)

    def _fixture_del_bug(self):
        """monthly_entries del caso real + el único snapshot del borde, fabricado
        al costo por el import."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',131,0,0,-2233,201119,199017)""",
            (self.uid, self.y, self.m))
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,201119,201119,201119,'import')", (self.uid, prev_close))
        self.conn.commit()

    def test_d1_semana_y_dia_tampoco_publican(self):
        """El guard tiene que cubrir las CUATRO pestañas.

        Cubriendo sólo mes/año, el mes mostraba "—" y un click más allá la semana
        decía "perdiste US$127.486 (−63,4%)" — dentro de la misma tarjeta. Los dos
        escapes de la rama día/semana no alcanzan: `start_value > 0`, y el gap
        entre bordes da 0 porque snap_start y snap_end son la MISMA fila.
        """
        self._fixture_del_bug()
        iy, iw, _wd = self.now.isocalendar()
        for pt, pk in (("week", f"{iy}-W{iw:02d}"), ("day", self.now.strftime("%Y-%m-%d"))):
            with self.subTest(period=pt):
                m = self._metrics(pt, pk, live=73764.0)
                self.assertTrue(m.basis_incomparable)
                self.assertIsNone(m.delta_pct)
                self.assertEqual(m.delta_usd, 0.0)
                # `unrealized` de día/semana se deriva del delta → es el mismo
                # fantasma con otro nombre.
                self.assertEqual(m.unrealized_pnl, 0.0)

    def test_d1_over_contrib_no_publica_el_cero_fabricado(self):
        """`delta_pct_over_contrib` se calcula desde `delta_usd`. Con el guard
        tapando el monto a 0, publicaba "+0,0% sobre aportado": un número
        inventado más creíble que el anterior, no menos."""
        self._fixture_del_bug()
        m = self._metrics_month(live=73764.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct_over_contrib)

    def test_d1_anio_con_borde_medido_publica_aunque_falte_el_mes_vivo(self):
        """Falso positivo: el año se apagaba entero porque el mes VIVO no tenía
        borde medido, tirando un delta real punta a punta. El `continue` ya saca
        al mes vivo de la composición; el flag del año no debe prenderse."""
        for mm in range(1, self.m + 1):
            self.conn.execute(
                """INSERT INTO monthly_entries (user_id, year, month, broker,
                     deposits, withdrawals, pnl_realized, pnl_unrealized,
                     capital_inicio, capital_final)
                   VALUES (?,?,?,'global',0,0,0,0,100000,100000)""",
                (self.uid, self.y, mm))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source, holdings_json) "
            "VALUES (?,?,100000,90000,90000,'cron','{\"AAPL\":100000}')",
            (self.uid, f"{self.y - 1}-12-31"))
        self.conn.commit()
        m = self._metrics("year", str(self.y), live=112000.0)
        self.assertFalse(m.basis_incomparable)
        self.assertAlmostEqual(m.start_value, 100000.0, delta=1)
        self.assertAlmostEqual(m.delta_usd, 12000.0, delta=1)
        self.assertIsNotNone(m.delta_pct)

    def test_d1_detectores_no_afirman_con_base_incomparable(self):
        """El 0 del guard hacía disparar SIEMPRE a DEPOSITS_DRIVE_GROWTH (sus dos
        salidas comparan contra abs(0)) y afirmaba "el portfolio creció US$+0 por
        rendimiento de mercado" pegado al headline que dice que no se puede medir."""
        from reporting.detectors import run_detectors
        from reporting.builder import build_period_report
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',5000,0,0,0,201119,206119)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        rep = build_period_report(self.conn, self.uid, "month", self.month_key,
                                  broker_filter="global", bench=None, live_value=73764.0)
        self.assertTrue(rep.metrics.basis_incomparable)
        codes = [i.code for i in run_detectors(rep, positions=[], avg_trades_per_period=0,
                                               historical_win_rate=None)]
        self.assertNotIn("DEPOSITS_DRIVE_GROWTH", codes)
        # Y la narrativa no puede afirmar un resultado.
        self.assertNotIn("perdiste", (rep.narrative or ""))
        self.assertNotIn("ganaste", (rep.narrative or ""))
        # El período sigue siendo relevante: "no medible" no es "sin actividad".
        self.assertTrue(rep.is_relevant)

    def test_d2_vs_sp500_es_el_exceso_no_el_retorno(self):
        """El cambio de semántica no tenía NI UN test del lado que lo produce:
        ningún test pasaba un `bench` poblado, así que revertir
        `vs_sp500 = sp500_ret` dejaba la suite verde."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, self.y, self.m))
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,10000,10000,10000,'cron')", (self.uid, prev_close))
        self.conn.commit()
        py, pm = (self.y, self.m - 1) if self.m > 1 else (self.y - 1, 12)
        bench = {
            "sp500": {f"{py:04d}-{pm:02d}": 100.0, self.month_key: 102.5},
            "inflation_ar": {self.month_key: 1.9},
        }
        start, end = parse_period_bounds("month", self.month_key)
        m, _ops = compute_metrics_for_period(
            self.conn, self.uid, "month", start, end, "global", bench=bench, live_value=9000.0)
        self.assertAlmostEqual(m.sp500_return_pct, 2.5, delta=0.01)
        self.assertAlmostEqual(m.inflation_pct, 1.9, delta=0.01)
        self.assertIsNotNone(m.delta_pct)
        # El campo es el EXCESO, no el retorno del benchmark.
        self.assertAlmostEqual(m.vs_sp500_pct, round(m.delta_pct - 2.5, 2), delta=0.01)
        self.assertLess(m.vs_sp500_pct, 0)   # la cartera cayó: quedó por DEBAJO
        self.assertNotAlmostEqual(m.vs_sp500_pct, 2.5, delta=0.01)

    def test_d2_sin_delta_pct_no_hay_comparacion_contra_benchmark(self):
        """Sin resultado del período no se puede publicar un 'vs S&P': sería
        reintroducir el número tapado por la ventana."""
        self._fixture_del_bug()
        py, pm = (self.y, self.m - 1) if self.m > 1 else (self.y - 1, 12)
        bench = {"sp500": {f"{py:04d}-{pm:02d}": 100.0, self.month_key: 102.5}, "inflation_ar": {}}
        start, end = parse_period_bounds("month", self.month_key)
        m, _ops = compute_metrics_for_period(
            self.conn, self.uid, "month", start, end, "global", bench=bench, live_value=73764.0)
        self.assertIsNone(m.vs_sp500_pct)
        self.assertAlmostEqual(m.sp500_return_pct, 2.5, delta=0.01)  # el dato del S&P sigue

    def test_d1_base_chica_dominada_por_aportes_sigue_midiendo(self):
        """El guard mide cuánto capital SIN medir hay en juego, no si lo hay.

        Capital heredado 1.230 contra 47.756 de aportes nuevos: aunque el 1.230
        salga de la cadena, el error máximo que puede meter es el 2,5% de la base
        del período. Tapar ese número sería tan poco informativo como publicar el
        del bug — el umbral (`_UNMEASURED_BASE_TOL`) separa los dos casos.
        """
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',47756,0,0,0,1230,48986)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=48986.0)
        self.assertFalse(m.basis_incomparable)
        self.assertAlmostEqual(m.delta_usd, 0.0, delta=2)

    def test_d1_usuario_nuevo_primer_mes_sigue_midiendo(self):
        """Regresión: sin capital previo NO hay mezcla posible. El primer mes de
        un usuario nuevo (capital_inicio=0 con aportes) tiene que seguir
        mostrando su rendimiento — el guard no debe comerse el onboarding."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',5000,0,0,200,0,5200)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=5200.0)
        self.assertFalse(m.basis_incomparable)
        self.assertAlmostEqual(m.delta_usd, 200.0, delta=1)
        self.assertIsNotNone(m.delta_pct)

    def test_c3_mes_sin_fila_hereda_cierre_anterior(self):
        """Sin fila del mes actual (rollover no corrió): hereda capital_final del
        mes anterior (ANTES: start 0 → 'P&L del mes' = cartera ENTERA)."""
        py, pm = (self.y, self.m - 1) if self.m > 1 else (self.y - 1, 12)
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, py, pm))
        self.conn.commit()
        m = self._metrics_month(live=13000.0)
        self.assertGreater(m.start_value, 0)                       # heredó, no 0
        self.assertLess(abs(m.delta_usd), 13000 - 1)               # NO la cartera entera

    def test_c3_usuario_nuevo_sin_historia_periodo_incompleto(self):
        """Usuario nuevo sin monthly ni snapshots: período incompleto — delta 0
        honesto y % None (ANTES: '+US$13.000 (+0.0%) sobre capital inicial $0')."""
        m = self._metrics_month(live=13000.0)
        self.assertIsNone(m.delta_pct)
        self.assertAlmostEqual(m.delta_usd, 0.0, delta=1)

    def test_h8_week_con_broker_filter_solo_realized(self):
        """Week con filtro de broker: delta = SOLO el realized del broker, % None
        (ANTES: delta de snapshots GLOBALES atribuido al broker)."""
        # Snapshots globales que se movieron +1.500 esta semana (por OTRO broker).
        today = self.now
        monday = today - timedelta(days=today.weekday())
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,20000,18000,18000)", (self.uid, _iso(monday - timedelta(days=1))))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,21500,18000,18000)", (self.uid, _iso(today)))
        # Una venta del broker filtrado con P&L −100 esta semana.
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd)
               VALUES (?,?,'Binance','BTC','VENTA',-100)""",
            (self.uid, _iso(today)))
        self.conn.commit()
        iy, iw, _ = today.isocalendar()
        m = self._metrics("week", f"{iy}-W{iw:02d}", broker="Binance")
        self.assertIsNone(m.delta_pct)                             # no medible
        self.assertAlmostEqual(m.delta_usd, -100.0, delta=0.01)    # SOLO realized
        self.assertAlmostEqual(m.unrealized_pnl, 0.0, delta=0.01)  # sin universo mixto

    def test_h7_delta_chips_netdep_con_baseline(self):
        """Δ1d del summary: con baseline 50k en la cadena, el delta de un día de
        +500 es +500 (ANTES: +50.500 — el baseline entero como 'ganancia')."""
        # Cadena con baseline: primer mes capital_inicio 50.000.
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',10000,0,0,0,50000,61000)""",
            (self.uid, self.y, self.m))
        # Snapshot de ayer: 61.000 con netdep CANÓNICO (baseline+flows=60.000).
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,61000,60000,60000)", (self.uid, _iso(self.now - timedelta(days=1))))
        self.conn.commit()
        s = main._portfolio_snapshot_summary(
            self.conn, self.uid, broker_filter="global", live_value_override=61500.0)
        d1 = s["delta_1d"]
        self.assertIsNotNone(d1)
        self.assertAlmostEqual(d1["usd"], 500.0, delta=1)          # NO 50.500


    # ── Bloqueantes cazados por el review adversarial de F4 ──────────────────

    def test_b1_migracion_startup_no_rompe_delta_chips(self):
        """B1 (CRITICAL): la migración de startup re-estampa snapshots.net_deposited;
        debe usar la convención CANÓNICA (global + baseline). Antes re-escribía SIN
        baseline → tras cada deploy, Δ1d = −baseline entero como pérdida fantasma."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',10000,0,0,0,50000,61000)""",
            (self.uid, self.y, self.m))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,61000,60000,60000)", (self.uid, _iso(self.now - timedelta(days=1))))
        self.conn.commit()
        # Migración de startup ENTRE estampar y leer (el escenario del deploy).
        main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
        self.conn.commit()
        s = main._portfolio_snapshot_summary(
            self.conn, self.uid, broker_filter="global", live_value_override=61500.0)
        d1 = s["delta_1d"]
        self.assertIsNotNone(d1)
        self.assertAlmostEqual(d1["usd"], 500.0, delta=1)   # NO −49.500

    def test_b2_primer_mes_usuario_nuevo_con_depositos(self):
        """B2 (HIGH): primer mes (capital_inicio=0, deposits>0, sin snapshots):
        delta = live − deposits. La versión rota pisaba start=end → −deposits."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',5000,0,0,0,0,5000)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=5200.0)
        self.assertAlmostEqual(m.delta_usd, 200.0, delta=1)   # NO −5.000

    def test_b3_narrativa_perdida_sin_pct_dice_perdiste(self):
        """B3 (HIGH): semana per-broker con pérdida realized → la narrativa dice
        'perdiste' (antes: pct None→0.0 → 'ganaste US$ 300 (+0.0%) sobre un
        capital inicial de US$ 0')."""
        from reporting.builder import generate_narrative, generate_headline
        from reporting.schema import PeriodMetrics
        m = PeriodMetrics(
            start_value=0.0, end_value=0.0, delta_usd=-300.0, delta_pct=None,
            delta_pct_over_contrib=None, realized_pnl=-300.0, unrealized_pnl=0.0,
            deposits=0.0, withdrawals=0.0, trades_count=1, win_count=0,
            loss_count=1, win_rate=0.0, vs_sp500_pct=None, vs_inflation_pct=None)
        txt = generate_narrative(m, [], [], "week", "Semana 28")
        self.assertIn("perdiste", txt)
        self.assertNotIn("+0.0%", txt)
        self.assertNotIn("capital inicial de US$ 0", txt)
        head, _sub = generate_headline(m, [], "week")
        self.assertNotIn("+0.0%", head)
        self.assertIn("−US$ 300", head)


if __name__ == "__main__":
    unittest.main()
