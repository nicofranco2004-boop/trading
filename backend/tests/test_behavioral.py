"""Tests de behavioral insights — fixtures de casos conocidos.

Cada test arma un set de operations sintético que dispara (o no dispara)
un sesgo específico. La idea: si en producción alguien dice "esto no me
aplica", el test demuestra qué patrón de operations dispara el detector.
"""
import sys
import os
import unittest
from datetime import datetime, timedelta

# Ruta del paquete backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from behavioral import (
    detect_disposition_effect,
    detect_overtrade,
    detect_loss_aversion,
    detect_averaging_down,
    build_behavioral_insights,
)


def _op(asset, entry_date, exit_date, entry_price, exit_price, qty, op_type="LONG"):
    """Helper para construir una operation closed."""
    return {
        "asset": asset,
        "op_type": op_type,
        "broker": "Schwab",
        "entry_date": entry_date,
        "date": exit_date,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": qty,
        "pnl_usd": (exit_price - entry_price) * qty,
        "pnl_pct": (exit_price / entry_price - 1) * 100,
        "commissions": 0,
    }


def _buy(asset, date, price, qty):
    """Helper para una operación de compra (sin exit)."""
    return {
        "asset": asset,
        "op_type": "Compra",
        "broker": "Schwab",
        "date": date,
        "entry_date": date,
        "entry_price": price,
        "exit_price": None,
        "quantity": qty,
        "pnl_usd": None,
        "pnl_pct": None,
        "commissions": 0,
    }


# ─── Detector 1: Disposition Effect ──────────────────────────────────────────


class DispositionEffectTest(unittest.TestCase):

    def test_classic_disposition_effect_detected(self):
        # Caso textbook: winners vendidos en ~10 días, losers aguantados ~120 días
        ops = []
        for i, asset in enumerate(["AAPL", "MSFT", "NVDA", "GOOGL"]):
            ops.append(_op(asset, "2024-01-01", f"2024-01-{10+i}", 100, 120, 10))  # winners, 10-13d
        for i, asset in enumerate(["TSLA", "META", "AMD", "INTC"]):
            ops.append(_op(asset, "2024-01-01", f"2024-0{4 + (i//3)}-{10+i*4:02d}", 100, 80, 10))  # losers, 90+d

        result = detect_disposition_effect(ops)
        self.assertEqual(result["code"], "disposition_effect")
        self.assertEqual(result["severity"], "high")
        self.assertTrue(result["detected"])
        self.assertLess(result["evidence"]["ratio"], 0.5)

    def test_balanced_holding_times_not_flagged(self):
        # Holding times similares en winners y losers
        ops = []
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-02-15", 100, 110, 10))  # 45d
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-02-20", 100, 90, 10))   # 50d
        result = detect_disposition_effect(ops)
        self.assertEqual(result["severity"], "positive")
        self.assertFalse(result["detected"])

    def test_diamond_hands_flagged_separately(self):
        # Winners aguantados muy largo, losers vendidos rápido (poco común
        # pero sucede — anti-disposition).
        ops = []
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-06-15", 100, 130, 10))  # 165d
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-01-10", 100, 92, 10))   # 9d
        result = detect_disposition_effect(ops)
        # Ratio > 2 → "diamond hands"
        self.assertIn(result["severity"], ("low", "medium"))
        self.assertGreater(result["evidence"]["ratio"], 2)

    def test_insufficient_data_returns_neutral(self):
        ops = [_op("AAPL", "2024-01-01", "2024-01-10", 100, 110, 10)]  # 1 op
        result = detect_disposition_effect(ops)
        self.assertTrue(result.get("insufficient_data"))
        self.assertEqual(result["severity"], "neutral")

    def test_excludes_breakeven_trades(self):
        # Trades con pnl = 0 deberían ignorarse en el cálculo
        ops = [_op(f"X{i}", "2024-01-01", "2024-01-10", 100, 100, 10) for i in range(10)]
        result = detect_disposition_effect(ops)
        self.assertTrue(result.get("insufficient_data"))

    def test_excludes_non_trade_op_types(self):
        # Dividendos y conversiones no son trades — no deberían contar
        ops = []
        for i in range(5):
            ops.append({
                "asset": "AAPL", "op_type": "Dividendo", "broker": "Schwab",
                "date": "2024-01-10", "entry_date": "2024-01-01",
                "entry_price": 100, "exit_price": 100, "quantity": 1,
                "pnl_usd": 0.5, "pnl_pct": 0.5, "commissions": 0,
            })
        result = detect_disposition_effect(ops)
        self.assertTrue(result.get("insufficient_data"))

    def test_evidence_contains_sample_trades(self):
        ops = []
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-01-15", 100, 110, 10))
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-06-01", 100, 90, 10))
        result = detect_disposition_effect(ops)
        self.assertIn("sample_winners", result["evidence"])
        self.assertIn("sample_losers", result["evidence"])


# ─── Detector 2: Overtrade Ratio ─────────────────────────────────────────────


class OvertradeTest(unittest.TestCase):

    def test_high_turnover_detected(self):
        # 30 ops de $5000 cada una en 6 meses, capital de $10000 → turnover ~30x/year
        ops = []
        for i in range(30):
            date = (datetime(2024, 1, 1) + timedelta(days=i * 6)).isoformat()[:10]
            ops.append(_op(f"OP{i}", date, date, 100, 105, 50))
        positions = [{"asset": "AAPL", "invested": 10000, "is_cash": 0}]
        result = detect_overtrade(ops, positions)
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["annual_turnover"], 4)

    def test_buy_and_hold_flagged_positive(self):
        # 3 ops en 18 meses con poco notional, capital grande
        ops = [
            _op("AAPL", "2023-01-01", "2024-02-01", 100, 110, 5),
            _op("MSFT", "2023-03-01", "2024-04-01", 200, 215, 3),
            _op("NVDA", "2023-06-01", "2024-06-01", 50, 80, 10),
        ]
        positions = [{"asset": "AAPL", "invested": 50000, "is_cash": 0}]
        result = detect_overtrade(ops, positions)
        self.assertEqual(result["severity"], "positive")
        self.assertLess(result["evidence"]["annual_turnover"], 1)

    def test_insufficient_data_with_two_ops(self):
        ops = [_op("AAPL", "2024-01-01", "2024-01-10", 100, 110, 10)]
        result = detect_overtrade(ops, [])
        self.assertTrue(result.get("insufficient_data"))


# ─── Detector 3: Loss Aversion ───────────────────────────────────────────────


class LossAversionTest(unittest.TestCase):

    def test_losers_much_bigger_than_winners_detected(self):
        # Winners de $1000 vs losers de $5000
        ops = []
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-02-01", 100, 110, 10))  # size 1000
        for i in range(4):
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-02-01", 100, 90, 50))   # size 5000
        result = detect_loss_aversion(ops)
        self.assertEqual(result["severity"], "high")
        self.assertGreaterEqual(result["evidence"]["ratio"], 2)

    def test_balanced_sizes_positive(self):
        ops = []
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-02-01", 100, 110, 10))  # 1000
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-02-01", 100, 90, 12))   # 1200
        result = detect_loss_aversion(ops)
        self.assertEqual(result["severity"], "positive")

    def test_winners_bigger_than_losers_is_healthy(self):
        # Patrón healthy: cortar pérdidas chicas y dejar correr ganadoras grandes
        ops = []
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-02-01", 100, 130, 30))  # 3000
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-02-01", 100, 92, 10))   # 1000
        result = detect_loss_aversion(ops)
        self.assertEqual(result["severity"], "positive")
        self.assertLess(result["evidence"]["ratio"], 0.7)

    def test_insufficient_data(self):
        ops = [_op("AAPL", "2024-01-01", "2024-02-01", 100, 110, 10)]
        result = detect_loss_aversion(ops)
        self.assertTrue(result.get("insufficient_data"))


# ─── Detector 4: Averaging Down ──────────────────────────────────────────────


class AveragingDownTest(unittest.TestCase):

    def test_classic_averaging_down_detected(self):
        # Compra AAPL a $200, a los 20 días a $170, a los 40 días a $140
        ops = [
            _buy("AAPL", "2024-01-01", 200, 10),
            _buy("AAPL", "2024-01-21", 170, 15),
            _buy("AAPL", "2024-02-10", 140, 20),
        ]
        result = detect_averaging_down(ops)
        self.assertTrue(result["detected"])
        self.assertGreaterEqual(result["evidence"]["total_instances"], 2)

    def test_no_averaging_down_when_prices_stable(self):
        # Compras del mismo ticker a precios similares → no es averaging down
        ops = [
            _buy("AAPL", "2024-01-01", 200, 10),
            _buy("AAPL", "2024-01-15", 198, 10),
            _buy("AAPL", "2024-02-01", 205, 10),
        ]
        result = detect_averaging_down(ops)
        self.assertEqual(result["evidence"]["total_instances"], 0)
        self.assertEqual(result["severity"], "positive")

    def test_no_flag_when_gap_too_long(self):
        # Compras de mismo ticker a precios más bajos pero con >60 días entre
        # ellas → puede ser DCA legítimo, no averaging down compulsivo
        ops = [
            _buy("AAPL", "2024-01-01", 200, 10),
            _buy("AAPL", "2024-04-15", 170, 10),  # 100 días después
        ]
        result = detect_averaging_down(ops)
        self.assertEqual(result["evidence"]["total_instances"], 0)

    def test_ignores_non_buy_operations(self):
        # Las ventas no deberían entrar al análisis (no son compras a la baja)
        ops = [
            _op("AAPL", "2024-01-01", "2024-01-10", 200, 180, 10, op_type="LONG"),
            _op("AAPL", "2024-01-15", "2024-01-25", 175, 160, 10, op_type="LONG"),
        ]
        result = detect_averaging_down(ops)
        self.assertEqual(result["evidence"]["total_instances"], 0)


# ─── Orchestrator ────────────────────────────────────────────────────────────


class BuildBehavioralInsightsTest(unittest.TestCase):

    def test_returns_four_cards(self):
        result = build_behavioral_insights([], [])
        self.assertEqual(len(result["cards"]), 4)

    def test_summary_counts_correctly(self):
        # Caso donde dos detectores van a flag y dos no por insuficiente data
        ops = []
        # Disposition effect fuerte
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-01-10", 100, 110, 10))
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-06-01", 100, 90, 50))
        result = build_behavioral_insights(ops, [{"asset": "AAPL", "invested": 5000, "is_cash": 0}])

        self.assertEqual(result["summary"]["total_cards"], 4)
        # Al menos disposition_effect debería estar detected como high
        codes_detected = [c["code"] for c in result["cards"] if c.get("detected")]
        self.assertIn("disposition_effect", codes_detected)

    def test_empty_inputs_dont_crash(self):
        result = build_behavioral_insights([], [])
        self.assertEqual(result["summary"]["total_detected"], 0)
        # Las 4 cards deberían tener insufficient_data
        for c in result["cards"]:
            self.assertTrue(c.get("insufficient_data") or not c.get("detected"))


if __name__ == "__main__":
    unittest.main()
