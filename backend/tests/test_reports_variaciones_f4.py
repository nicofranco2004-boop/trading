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
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,13000,10000,10000)", (self.uid, prev_close))
        self.conn.commit()
        m = self._metrics_month(live=13000.0)
        self.assertAlmostEqual(m.start_value, 13000.0, delta=1)   # MtM, no 10.000
        self.assertAlmostEqual(m.delta_usd, 0.0, delta=1)          # NO +3.000
        if m.delta_pct is not None:
            self.assertLess(abs(m.delta_pct), 1.0)                 # NO +30%

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
