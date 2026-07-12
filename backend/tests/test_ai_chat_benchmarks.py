"""M-benchmark (quick win de conversión): summary.benchmarks en el snapshot del
chat — retornos REALES de inflación/S&P/blue + los del user, precalculados
server-side. Las series se arman relativas a date.today() (no se pudren)."""
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import main


def _keys():
    t = date.today()
    ym = f"{t.year:04d}-{t.month:02d}"
    py, pm = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
    return t, ym, f"{py:04d}-{pm:02d}", f"{t.year - 1:04d}-12"


def _fake_bench():
    """Series sintéticas: inflación 2%/mes todos los meses del año hasta el mes
    pasado; S&P 100→110 (mes pasado)→112 (hoy); blue 1000→1200→1250."""
    t, ym, ym_prev, dec_prev = _keys()
    inflation = {}
    for m in range(1, t.month):  # meses CERRADOS del año (sin el actual)
        inflation[f"{t.year:04d}-{m:02d}"] = 2.0
    sp500 = {dec_prev: 100.0, ym_prev: 110.0, ym: 112.0}
    blue = {dec_prev: 1000.0, ym_prev: 1200.0, ym: 1250.0}
    merval = {dec_prev: 2_000_000.0, ym: 2_600_000.0}
    return {"inflation_ar": inflation, "sp500": sp500,
            "dolar_blue": blue, "merval": merval}


def _fake_summary(*a, **k):
    return {"delta_30d": {"pct": 3.0, "usd": 300},
            "ytd": {"pct": 10.0, "usd": 1000, "since_date": f"{date.today().year}-01-01"}}


class TestBuildChatBenchmarks(unittest.TestCase):
    def _build(self, bench_data=None):
        data = bench_data if bench_data is not None else _fake_bench()
        with patch.dict(main._bench_cache, {"data": data, "ts": 9e18}), \
             patch.object(main, "_portfolio_snapshot_summary", side_effect=_fake_summary):
            return main._build_chat_benchmarks(None, 1)

    def test_inflation_month_and_ytd_compound(self):
        t = date.today()
        b = self._build()
        if t.month == 1:
            # Enero: sin meses cerrados del año — inflación YTD legítimamente None
            self.assertIsNone(b["inflation_ar"]["ytd_pct"])
            return
        n = t.month - 1  # meses cerrados
        expected = round(((1.02 ** n) - 1) * 100, 2)
        self.assertAlmostEqual(b["inflation_ar"]["ytd_pct"], expected, places=2)
        self.assertEqual(b["inflation_ar"]["month_pct"], 2.0)  # último publicado

    def test_sp500_month_and_ytd(self):
        b = self._build()
        sp = b["sp500_total_return_usd"]
        self.assertAlmostEqual(sp["month_pct"], round((112 / 110 - 1) * 100, 2))
        self.assertAlmostEqual(sp["ytd_pct"], 12.0)

    def test_user_ars_approx_composition(self):
        """ars_ytd_pct_approx = (1 + usd_ytd) × (1 + blue_ytd) − 1:
        10% USD × 25% devaluación = 37.5% en pesos."""
        b = self._build()
        self.assertAlmostEqual(b["dolar_blue_move"]["ytd_pct"], 25.0)
        self.assertAlmostEqual(b["user_portfolio"]["ars_ytd_pct_approx"], 37.5)
        self.assertEqual(b["user_portfolio"]["usd_ytd_pct"], 10.0)

    def test_note_has_comparison_rules(self):
        b = self._build()
        self.assertIn("NUNCA compares el retorno USD directo", b["_note"])

    def test_cold_cache_returns_none_and_warms_background(self):
        submitted = []
        with patch.dict(main._bench_cache, {"data": None, "ts": 0}), \
             patch.dict(main._bench_refresh_inflight, {"flag": False}), \
             patch.object(main._bench_fetch_executor, "submit",
                          side_effect=lambda fn: submitted.append(fn)):
            r = main._build_chat_benchmarks(None, 1)
        self.assertIsNone(r)              # no bloquea el chat
        self.assertEqual(len(submitted), 1)  # pero calienta en background

    def test_user_summary_failure_degrades(self):
        """Si el summary del user falla, los benchmarks salen igual (user en null)."""
        with patch.dict(main._bench_cache, {"data": _fake_bench(), "ts": 9e18}), \
             patch.object(main, "_portfolio_snapshot_summary",
                          side_effect=RuntimeError("db")):
            b = main._build_chat_benchmarks(None, 1)
        self.assertIsNotNone(b)
        self.assertIsNone(b["user_portfolio"]["usd_ytd_pct"])


class TestEnrichChatBenchmarks(unittest.TestCase):
    def test_attaches_under_summary(self):
        with patch.object(main, "_build_chat_benchmarks",
                          return_value={"inflation_ar": {}, "_note": "x"}):
            out = main._enrich_chat_benchmarks(1, {"summary": {"a": 1}})
        self.assertIn("benchmarks", out["summary"])
        self.assertEqual(out["summary"]["a"], 1)  # preserva lo demás

    def test_never_raises_and_degrades(self):
        snap = {"summary": {"a": 1}}
        with patch.object(main, "_build_chat_benchmarks",
                          side_effect=RuntimeError("boom")):
            out = main._enrich_chat_benchmarks(1, snap)
        self.assertEqual(out, snap)  # snapshot intacto, sin excepción

    def test_none_bench_keeps_snapshot(self):
        with patch.object(main, "_build_chat_benchmarks", return_value=None):
            out = main._enrich_chat_benchmarks(1, {"summary": {"a": 1}})
        self.assertNotIn("benchmarks", out["summary"])


if __name__ == "__main__":
    unittest.main()
