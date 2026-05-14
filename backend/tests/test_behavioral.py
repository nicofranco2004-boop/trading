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
    detect_concentration,
    detect_home_bias,
    detect_cash_drag,
    detect_inflation_loss,
    detect_counterfactual,
    detect_winrate_payoff,
    detect_recency_bias,
    detect_sector_concentration,
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


# ─── Detector 5: Win rate + payoff ───────────────────────────────────────────


class WinratePayoffTest(unittest.TestCase):

    def test_high_winrate_low_payoff_flagged(self):
        # 7 wins de $20 cada uno, 3 losses de $200 cada uno
        # win_rate 70%, avg_win 20, avg_loss 200, payoff 0.1, expectancy = 0.7*20 - 0.3*200 = -46
        ops = []
        for i in range(7):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-01-15", 100, 102, 10))  # +20
        for i in range(3):
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-01-15", 100, 80, 10))   # -200
        result = detect_winrate_payoff(ops)
        self.assertEqual(result["severity"], "high")
        self.assertTrue(result["detected"])
        self.assertLess(result["evidence"]["expectancy_usd"], 0)

    def test_balanced_winrate_and_payoff_positive(self):
        # 50% win rate con payoff 2× → expectancy positivo
        ops = []
        for i in range(5):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-01-15", 100, 120, 10))  # +200
        for i in range(5):
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-01-15", 100, 90, 10))   # -100
        result = detect_winrate_payoff(ops)
        self.assertIn(result["severity"], ("positive", "low"))
        self.assertGreater(result["evidence"]["expectancy_usd"], 0)
        self.assertGreater(result["evidence"]["payoff_ratio"], 1.5)

    def test_insufficient_data(self):
        result = detect_winrate_payoff([_op("X", "2024-01-01", "2024-01-15", 100, 110, 10)])
        self.assertTrue(result.get("insufficient_data"))


# ─── Detector 6: Concentration ───────────────────────────────────────────────


class ConcentrationTest(unittest.TestCase):

    def test_single_asset_dominance_high(self):
        positions = [
            {"broker": "Schwab", "asset": "NVDA", "is_cash": 0, "quantity": 100, "invested": 50000},
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "quantity": 50, "invested": 5000},
        ]
        prices = {"NVDA": 500, "AAPL": 100}  # NVDA = 50000, AAPL = 5000 → NVDA 90.9%
        result = detect_concentration(positions, prices)
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["top1_pct"], 80)
        self.assertEqual(result["evidence"]["top_asset"], "NVDA")

    def test_diversified_positive(self):
        positions = [
            {"broker": "Schwab", "asset": f"ASSET{i}", "is_cash": 0, "quantity": 10, "invested": 1000}
            for i in range(15)
        ]
        prices = {f"ASSET{i}": 100 for i in range(15)}
        result = detect_concentration(positions, prices)
        self.assertEqual(result["severity"], "positive")
        self.assertLess(result["evidence"]["top1_pct"], 15)

    def test_no_positions_insufficient(self):
        result = detect_concentration([])
        self.assertTrue(result.get("insufficient_data"))


# ─── Detector 7: Home bias ───────────────────────────────────────────────────


class HomeBiasTest(unittest.TestCase):

    def test_strong_home_bias_high(self):
        # 95% en Cocos AR + 5% en Schwab US
        positions = [
            {"broker": "Cocos", "asset": "GGAL", "is_cash": 0, "quantity": 100, "invested": 5000000},  # ~3535 USD al blue
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "quantity": 1, "invested": 200},
        ]
        result = detect_home_bias(positions)
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["ar_pct"], 80)

    def test_balanced_positive(self):
        positions = [
            {"broker": "Cocos", "asset": "GGAL", "is_cash": 0, "quantity": 100, "invested": 2000000},  # ~1414 USD
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "quantity": 10, "invested": 1800},
            {"broker": "Schwab", "asset": "MSFT", "is_cash": 0, "quantity": 5, "invested": 2000},
        ]
        result = detect_home_bias(positions)
        # Total ~5214, AR ~1414 (27%), INTL ~3800 (73%) → "positive" (20-50%) o "low"
        self.assertIn(result["severity"], ("positive", "low"))


# ─── Detector 8: Cash drag ───────────────────────────────────────────────────


class CashDragTest(unittest.TestCase):

    def test_high_cash_pct_flagged(self):
        positions = [
            {"broker": "Schwab", "asset": "USD", "is_cash": 1, "invested": 10000},
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "invested": 5000},
        ]
        result = detect_cash_drag(positions)
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["cash_pct"], 50)

    def test_ars_cash_specifically_flagged(self):
        # 20% cash pero TODO en ARS → high por el monto en ARS
        positions = [
            {"broker": "Cocos", "asset": "ARS", "is_cash": 1, "invested": 3000000},  # ~2120 USD
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "invested": 10000},
        ]
        result = detect_cash_drag(positions)
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["cash_ars_pct"], 15)

    def test_low_cash_positive(self):
        positions = [
            {"broker": "Schwab", "asset": "USD", "is_cash": 1, "invested": 500},
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "invested": 10000},
        ]
        result = detect_cash_drag(positions)
        # 4.7% en cash → low (sin cushion)
        self.assertEqual(result["severity"], "low")


# ─── Detector 9: Inflation loss ──────────────────────────────────────────────


class InflationLossTest(unittest.TestCase):

    def test_inflation_loss_with_ars_cash_high(self):
        positions = [
            {"broker": "Cocos", "asset": "ARS", "is_cash": 1, "invested": 5000000},
        ]
        # Inflación 100% acumulada en 12 meses
        inflation = {f"2024-{m:02d}": 6.0 for m in range(1, 13)}  # ~100% cum
        result = detect_inflation_loss(positions, inflation)
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["loss_usd"], 500)

    def test_no_ars_cash_no_loss(self):
        positions = [
            {"broker": "Schwab", "asset": "USD", "is_cash": 1, "invested": 5000},
        ]
        result = detect_inflation_loss(positions, {})
        self.assertFalse(result["detected"])
        self.assertEqual(result["evidence"]["cash_ars_pesos"], 0)


# ─── Detector 10: Counterfactual ─────────────────────────────────────────────


class CounterfactualTest(unittest.TestCase):

    def test_would_have_been_better_holding(self):
        # Vendiste NVDA a $120 (entry $100, qty 10) → +200
        # Hoy NVDA vale $180 → hubieras tenido +800. Delta = +600
        ops = [
            _op("NVDA", "2024-01-01", "2024-02-01", 100, 120, 10),
            _op("AAPL", "2024-01-01", "2024-02-01", 100, 110, 10),
            _op("MSFT", "2024-01-01", "2024-02-01", 100, 115, 10),
        ]
        prices = {"NVDA": 180, "AAPL": 130, "MSFT": 140}
        result = detect_counterfactual(ops, prices)
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["delta_total_usd"], 1000)

    def test_selling_was_smart_positive(self):
        # Vendiste a $120, hoy vale $50 → cerrar a tiempo fue acierto
        ops = [
            _op("CRASH", "2024-01-01", "2024-02-01", 100, 120, 10),
            _op("AAPL", "2024-01-01", "2024-02-01", 100, 110, 10),
            _op("MSFT", "2024-01-01", "2024-02-01", 100, 115, 10),
        ]
        prices = {"CRASH": 50, "AAPL": 100, "MSFT": 100}
        result = detect_counterfactual(ops, prices)
        self.assertEqual(result["severity"], "positive")
        self.assertLess(result["evidence"]["delta_total_usd"], -300)

    def test_no_prices_insufficient(self):
        ops = [_op("AAPL", "2024-01-01", "2024-02-01", 100, 110, 10)] * 5
        result = detect_counterfactual(ops, None)
        self.assertTrue(result.get("insufficient_data"))


# ─── Detector 11: Recency bias ───────────────────────────────────────────────


class RecencyBiasTest(unittest.TestCase):

    def test_high_chase_pump_flagged(self):
        # 80% del invested compró >30% más caro que el precio actual
        positions = [
            {"broker": "Schwab", "asset": "TSLA", "is_cash": 0, "buy_price": 280, "invested": 8000},
            {"broker": "Schwab", "asset": "PLTR", "is_cash": 0, "buy_price": 35,  "invested": 2000},
        ]
        prices = {"TSLA": 200, "PLTR": 28}  # ambos -28%/-20% desde la compra
        result = detect_recency_bias(positions, prices)
        # TSLA: 280/200 = 1.4 → flagged. PLTR: 35/28 = 1.25 → no flagged.
        # Solo TSLA (8000 / 10000 = 80%) → high
        self.assertEqual(result["severity"], "high")
        self.assertGreater(result["evidence"]["chase_pct"], 70)

    def test_no_chase_when_buy_close_to_current(self):
        positions = [
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "buy_price": 190, "invested": 5000},
            {"broker": "Schwab", "asset": "MSFT", "is_cash": 0, "buy_price": 430, "invested": 5000},
        ]
        prices = {"AAPL": 192, "MSFT": 438}
        result = detect_recency_bias(positions, prices)
        self.assertEqual(result["severity"], "positive")
        self.assertLess(result["evidence"]["chase_pct"], 5)

    def test_insufficient_data_without_prices(self):
        positions = [{"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "buy_price": 190, "invested": 5000}]
        result = detect_recency_bias(positions, None)
        self.assertTrue(result.get("insufficient_data"))


# ─── Detector 12: Sector concentration ───────────────────────────────────────


class SectorConcentrationTest(unittest.TestCase):

    def test_all_tech_flagged_high(self):
        positions = [
            {"broker": "Schwab", "asset": "NVDA", "is_cash": 0, "quantity": 10, "invested": 5000},
            {"broker": "Schwab", "asset": "AAPL", "is_cash": 0, "quantity": 10, "invested": 5000},
            {"broker": "Schwab", "asset": "MSFT", "is_cash": 0, "quantity": 10, "invested": 5000},
        ]
        prices = {"NVDA": 500, "AAPL": 500, "MSFT": 500}
        result = detect_sector_concentration(positions, prices)
        self.assertEqual(result["severity"], "high")
        self.assertEqual(result["evidence"]["top_sector"], "Tech")
        self.assertGreaterEqual(result["evidence"]["top1_pct"], 90)

    def test_diversified_across_sectors_positive(self):
        positions = [
            {"broker": "Schwab", "asset": "NVDA", "is_cash": 0, "quantity": 5, "invested": 2500},  # Tech
            {"broker": "Schwab", "asset": "JPM", "is_cash": 0,  "quantity": 5, "invested": 2500},  # Financials
            {"broker": "Schwab", "asset": "LLY", "is_cash": 0,  "quantity": 5, "invested": 2500},  # Healthcare
            {"broker": "Schwab", "asset": "XOM", "is_cash": 0,  "quantity": 5, "invested": 2500},  # Energy
            {"broker": "Schwab", "asset": "KO", "is_cash": 0,   "quantity": 5, "invested": 2500},  # Consumer
        ]
        prices = {"NVDA": 500, "JPM": 500, "LLY": 500, "XOM": 500, "KO": 500}
        result = detect_sector_concentration(positions, prices)
        self.assertEqual(result["severity"], "positive")
        self.assertLess(result["evidence"]["top1_pct"], 30)

    def test_cedear_mapped_to_us_sector(self):
        # AAPL.BA debería resolver al sector de AAPL (Tech)
        positions = [
            {"broker": "Cocos", "asset": "AAPL.BA", "is_cash": 0, "invested": 1000000},
        ]
        result = detect_sector_concentration(positions, {})
        # Debería tener "CEDEAR (Tech)" en el breakdown
        sectors = [b["sector"] for b in result["evidence"]["breakdown"]]
        self.assertTrue(any("Tech" in s for s in sectors))


# ─── Orchestrator ────────────────────────────────────────────────────────────


class BuildBehavioralInsightsTest(unittest.TestCase):

    def test_returns_twelve_cards(self):
        result = build_behavioral_insights([], [])
        self.assertEqual(len(result["cards"]), 12)

    def test_summary_counts_correctly(self):
        # Disposition effect fuerte + concentración alta
        ops = []
        for i in range(4):
            ops.append(_op(f"WIN{i}", "2024-01-01", "2024-01-10", 100, 110, 10))
            ops.append(_op(f"LOS{i}", "2024-01-01", "2024-06-01", 100, 90, 50))
        positions = [{"broker": "Schwab", "asset": "NVDA", "is_cash": 0, "quantity": 100, "invested": 50000}]
        result = build_behavioral_insights(ops, positions, prices={"NVDA": 500})

        self.assertEqual(result["summary"]["total_cards"], 12)
        codes_detected = [c["code"] for c in result["cards"] if c.get("detected")]
        self.assertIn("disposition_effect", codes_detected)
        self.assertIn("concentration", codes_detected)

    def test_empty_inputs_dont_crash(self):
        result = build_behavioral_insights([], [])
        self.assertEqual(result["summary"]["total_detected"], 0)
        # Las 4 cards deberían tener insufficient_data
        for c in result["cards"]:
            self.assertTrue(c.get("insufficient_data") or not c.get("detected"))


if __name__ == "__main__":
    unittest.main()
