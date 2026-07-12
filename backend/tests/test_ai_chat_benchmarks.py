"""M-benchmark (quick win de conversión): summary.benchmarks en el snapshot del
chat — retornos REALES precalculados server-side. Fecha INYECTADA (_today) para
determinismo total: sin esto, 2 tests explotaban todos los eneros por colisión
ym_prev == dec_prev en las fixtures (review)."""
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import main

TODAY = date(2026, 7, 15)  # fija: julio (caso general); enero se testea aparte


def _fake_bench(indec_lag_months=1):
    """Series sintéticas ancladas a TODAY (jul-2026). Inflación 2%/mes publicada
    hasta (7 − indec_lag_months); S&P 100(dic)→110(jun)→112(jul); blue
    1000(dic)→1200(feb)→1250(jul, key mensual completa)."""
    inflation = {f"2026-{m:02d}": 2.0 for m in range(1, 8 - indec_lag_months)}
    sp500 = {"2025-12": 100.0, "2026-06": 110.0, "2026-07": 112.0}
    blue = {"2025-12": 1000.0, "2026-02": 1200.0, "2026-06": 1240.0, "2026-07": 1250.0}
    merval = {"2025-12": 2_000_000.0, "2026-07": 2_600_000.0}
    return {"inflation_ar": inflation, "sp500": sp500,
            "dolar_blue": blue, "merval": merval}


def _summary(ytd_since="2026-01-01", ytd_pct=10.0, d30=3.0):
    def _fake(*a, **k):
        return {"delta_30d": {"pct": d30, "usd": 300},
                "ytd": {"pct": ytd_pct, "usd": 1000, "since_date": ytd_since}}
    return _fake


class TestBuildChatBenchmarks(unittest.TestCase):
    def _build(self, bench=None, summary=None, today=TODAY):
        data = bench if bench is not None else _fake_bench()
        with patch.dict(main._bench_cache, {"data": data, "ts": 9e18}), \
             patch.object(main, "_portfolio_snapshot_summary",
                          side_effect=(summary or _summary())):
            return main._build_chat_benchmarks(None, 1, _today=today)

    def test_inflation_ytd_compound_and_coverage(self):
        """6 meses publicados al 2%: YTD = 1.02^6−1 = 12.62%, con ytd_through."""
        b = self._build()
        self.assertAlmostEqual(b["inflation_ar"]["ytd_pct"], 12.62, places=2)
        self.assertEqual(b["inflation_ar"]["ytd_through"], "2026-06")
        self.assertEqual(b["inflation_ar"]["month_pct"], 2.0)
        self.assertEqual(b["inflation_ar"]["month"], "2026-06")

    def test_indec_two_month_lag(self):
        """El caso REAL cazado en vivo: en julio lo último publicado es mayo —
        el lookup debe encontrar el último key, no null."""
        b = self._build(bench=_fake_bench(indec_lag_months=2))
        self.assertEqual(b["inflation_ar"]["month"], "2026-05")
        self.assertEqual(b["inflation_ar"]["month_pct"], 2.0)
        self.assertEqual(b["inflation_ar"]["ytd_through"], "2026-05")

    def test_sp500_month_and_ytd(self):
        b = self._build()
        sp = b["sp500_total_return_usd"]
        self.assertAlmostEqual(sp["month_pct"], round((112 / 110 - 1) * 100, 2))
        self.assertAlmostEqual(sp["ytd_pct"], 12.0)

    def test_ars_approx_full_year_window(self):
        """User desde enero: blue base = dic-2025 → (1.10 × 1.25) − 1 = 37.5%."""
        b = self._build()
        self.assertAlmostEqual(b["user_portfolio"]["ars_ytd_pct_approx"], 37.5)

    def test_ars_approx_partial_year_uses_user_window(self):
        """BLOQUEANTE del review: user desde MARZO → la pata blue va desde
        feb-2026 (1200), NO desde diciembre (1000). (1.10 × 1250/1200) − 1 =
        14.58% — no 37.5% (23pts de sobreestimación con ventanas mezcladas)."""
        b = self._build(summary=_summary(ytd_since="2026-03-01"))
        # 14.58 exacto; 14.59 por el redondeo intermedio de _pct_move (2 dec).
        self.assertAlmostEqual(b["user_portfolio"]["ars_ytd_pct_approx"], 14.58,
                               delta=0.02)
        # Lo que NO tiene que dar: la composición con ventanas mezcladas.
        self.assertLess(b["user_portfolio"]["ars_ytd_pct_approx"], 20.0)

    def test_ars_approx_null_without_blue_base(self):
        """User desde marzo pero SIN key feb en el blue → null (no inventar)."""
        bench = _fake_bench()
        del bench["dolar_blue"]["2026-02"]
        b = self._build(bench=bench, summary=_summary(ytd_since="2026-03-01"))
        self.assertIsNone(b["user_portfolio"]["ars_ytd_pct_approx"])

    def test_note_has_window_and_coverage_rules(self):
        b = self._build()
        self.assertIn("ytd_through", b["_note"])
        self.assertIn("NUNCA compares el retorno USD directo", b["_note"])
        self.assertIn("ventana del user es más corta", b["_note"])

    def test_january_no_bomb(self):
        """Enero: sin meses publicados del año → inflación YTD/through null,
        el resto del bloque sale igual (la bomba de enero del review)."""
        jan = date(2026, 1, 15)
        bench = {"inflation_ar": {"2025-11": 2.5, "2025-12": 2.0},
                 "sp500": {"2025-11": 108.0, "2025-12": 100.0, "2026-01": 103.0},
                 "dolar_blue": {"2025-12": 1000.0, "2026-01": 1020.0},
                 "merval": {"2025-12": 2_000_000.0, "2026-01": 2_100_000.0}}
        b = self._build(bench=bench, today=jan)
        self.assertIsNone(b["inflation_ar"]["ytd_pct"])
        self.assertIsNone(b["inflation_ar"]["ytd_through"])
        self.assertEqual(b["inflation_ar"]["month"], "2025-12")  # último publicado
        self.assertAlmostEqual(b["sp500_total_return_usd"]["month_pct"], 3.0)
        self.assertAlmostEqual(b["sp500_total_return_usd"]["ytd_pct"], 3.0)

    def test_partial_summary_user_nuevo(self):
        """delta_30d presente pero ytd None (user nuevo): bloque coherente,
        ars_approx null."""
        def _partial(*a, **k):
            return {"delta_30d": {"pct": 3.0}, "ytd": None}
        b = self._build(summary=_partial)
        self.assertEqual(b["user_portfolio"]["usd_30d_pct"], 3.0)
        self.assertIsNone(b["user_portfolio"]["usd_ytd_pct"])
        self.assertIsNone(b["user_portfolio"]["ars_ytd_pct_approx"])

    def test_cold_cache_returns_none_and_warms_background(self):
        submitted = []
        with patch.dict(main._bench_cache, {"data": None, "ts": 0}), \
             patch.dict(main._bench_refresh_inflight, {"flag": False}), \
             patch.object(main._bench_fetch_executor, "submit",
                          side_effect=lambda fn: submitted.append(fn)):
            r = main._build_chat_benchmarks(None, 1, _today=TODAY)
        self.assertIsNone(r)
        self.assertEqual(len(submitted), 1)

    def test_stale_cache_served_and_refreshed(self):
        """SWR completo (review): data vencida se SIRVE + dispara refresh."""
        submitted = []
        with patch.dict(main._bench_cache, {"data": _fake_bench(), "ts": 1.0}), \
             patch.dict(main._bench_refresh_inflight, {"flag": False}), \
             patch.object(main, "_portfolio_snapshot_summary",
                          side_effect=_summary()), \
             patch.object(main._bench_fetch_executor, "submit",
                          side_effect=lambda fn: submitted.append(fn)):
            b = main._build_chat_benchmarks(None, 1, _today=TODAY)
        self.assertIsNotNone(b)                  # sirve lo stale
        self.assertEqual(len(submitted), 1)      # y refresca en background

    def test_user_summary_failure_degrades(self):
        with patch.dict(main._bench_cache, {"data": _fake_bench(), "ts": 9e18}), \
             patch.object(main, "_portfolio_snapshot_summary",
                          side_effect=RuntimeError("db")):
            b = main._build_chat_benchmarks(None, 1, _today=TODAY)
        self.assertIsNotNone(b)
        self.assertIsNone(b["user_portfolio"]["usd_ytd_pct"])


class TestEnrichChatBenchmarks(unittest.TestCase):
    def test_attaches_under_summary(self):
        with patch.object(main, "_build_chat_benchmarks",
                          return_value={"inflation_ar": {}, "_note": "x"}):
            out = main._enrich_chat_benchmarks(1, {"summary": {"a": 1}})
        self.assertIn("benchmarks", out["summary"])
        self.assertEqual(out["summary"]["a"], 1)

    def test_never_raises_and_degrades(self):
        snap = {"summary": {"a": 1}}
        with patch.object(main, "_build_chat_benchmarks",
                          side_effect=RuntimeError("boom")):
            out = main._enrich_chat_benchmarks(1, snap)
        self.assertEqual(out, snap)

    def test_none_bench_keeps_snapshot(self):
        with patch.object(main, "_build_chat_benchmarks", return_value=None):
            out = main._enrich_chat_benchmarks(1, {"summary": {"a": 1}})
        self.assertNotIn("benchmarks", out["summary"])


if __name__ == "__main__":
    unittest.main()
