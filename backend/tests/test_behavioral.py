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

    def test_cedears_count_as_international(self):
        """Bug fix: un CEDEAR (AAPL.BA en Cocos) es exposición económica
        INTERNACIONAL, no AR. El wrapper es AR pero el subyacente es Apple."""
        positions = [
            # Solo CEDEARs en Cocos — antes daba 100% AR, ahora debe dar 100% INTL
            {"broker": "Cocos", "asset": "AAPL.BA", "is_cash": 0, "quantity": 100, "invested": 1000000},
            {"broker": "Cocos", "asset": "NVDA.BA", "is_cash": 0, "quantity": 50, "invested": 800000},
            {"broker": "Cocos", "asset": "MSFT.BA", "is_cash": 0, "quantity": 30, "invested": 500000},
        ]
        result = detect_home_bias(positions)
        # ar_pct debería ser 0 (todo es CEDEAR internacional) → severity medium
        # (porque <5% en AR también es flagged como "casi sin exposición AR")
        self.assertLess(result["evidence"]["ar_pct"], 5)
        self.assertGreater(result["evidence"]["intl_pct"], 95)

    def test_ar_bonds_count_as_ar(self):
        """Bonos AR (AL30, GD30) son exposición AR real (riesgo país)."""
        positions = [
            {"broker": "Cocos", "asset": "AL30", "is_cash": 0, "quantity": 100, "invested": 5000000},
            {"broker": "Cocos", "asset": "GD30", "is_cash": 0, "quantity": 100, "invested": 5000000},
        ]
        result = detect_home_bias(positions)
        self.assertGreater(result["evidence"]["ar_pct"], 95)

    def test_cedears_with_prices_use_current_value(self):
        """Cuando hay precio actual, el valor USD debe ser price × qty / tc_blue,
        no invested. Esto fixea el bug donde el total daba muy bajo."""
        positions = [
            {"broker": "Cocos", "asset": "AAPL.BA", "is_cash": 0, "quantity": 100, "buy_price": 18800, "invested": 1880000},
        ]
        # Precio actual subió: 22400 → valor = 22400 × 100 / 1415 = ~1583 USD
        prices = {"AAPL.BA": 22400}
        result = detect_home_bias(positions, prices)
        # Debe usar el precio actual (más alto que invested al blue)
        # invested USD = 1880000/1415 = 1329; current USD = 22400*100/1415 = 1583
        self.assertGreater(result["evidence"]["intl_value_usd"], 1400)


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

    def test_ars_cedear_op_is_skipped(self):
        # REGRESIÓN (bug de moneda): 3 ventas USD + 1 CEDEAR cargado en pesos.
        # La de ARS (exit 32.640 pesos, pnl_usd 561) NO debe restarse contra el
        # precio actual de INTC en USD (~134) — antes daba un delta de −1,3M.
        ops = [
            _op("NVDA", "2024-01-01", "2024-02-01", 100, 120, 10),  # USD
            _op("AAPL", "2024-01-01", "2024-02-01", 100, 110, 10),  # USD
            _op("MSFT", "2024-01-01", "2024-02-01", 100, 115, 10),  # USD
            {  # CEDEAR de INTC en pesos — currency vacío, como en prod
                "asset": "INTC", "op_type": "Venta", "broker": "Cocos",
                "date": "2024-03-01", "entry_price": 13000, "exit_price": 32640,
                "quantity": 41, "pnl_usd": 561.07, "pnl_pct": 4.3, "commissions": 0,
            },
        ]
        prices = {"NVDA": 180, "AAPL": 130, "MSFT": 140, "INTC": 134}
        result = detect_counterfactual(ops, prices)
        self.assertEqual(result["evidence"]["trades_analyzed"], 3)
        self.assertEqual(result["evidence"]["trades_skipped_fx"], 1)
        # Delta sano (no millones) y la op en pesos no aparece en top_misses.
        self.assertLess(abs(result["evidence"]["delta_total_usd"]), 100_000)
        self.assertNotIn("INTC", [m["asset"] for m in result["evidence"]["top_misses"]])

    def test_declared_currency_respected(self):
        # currency='ARS' explícito ⇒ se omite aunque la escala coincida.
        ars = _op("AAPL", "2024-01-01", "2024-02-01", 100, 110, 10)
        ars["currency"] = "ARS"
        usd = [
            _op("NVDA", "2024-01-01", "2024-02-01", 100, 120, 10),
            _op("MSFT", "2024-01-01", "2024-02-01", 100, 115, 10),
            _op("GOOGL", "2024-01-01", "2024-02-01", 100, 130, 10),
        ]
        prices = {"NVDA": 180, "MSFT": 140, "GOOGL": 150, "AAPL": 130}
        result = detect_counterfactual([ars] + usd, prices)
        self.assertEqual(result["evidence"]["trades_analyzed"], 3)
        self.assertEqual(result["evidence"]["trades_skipped_fx"], 1)

    def test_only_ars_trades_insufficient(self):
        # Todas las ventas en pesos ⇒ no hay 3 en USD ⇒ insuficiente.
        ops = [
            {"asset": "INTC", "op_type": "Venta", "broker": "Cocos",
             "date": "2024-03-01", "entry_price": 13000, "exit_price": 32640,
             "quantity": 41, "pnl_usd": 561.07, "pnl_pct": 4.3, "commissions": 0},
            {"asset": "COIN", "op_type": "Venta", "broker": "Cocos",
             "date": "2024-03-01", "entry_price": 9145, "exit_price": 10700,
             "quantity": 46, "pnl_usd": 46.65, "pnl_pct": 1.0, "commissions": 0},
            {"asset": "MELI", "op_type": "Venta", "broker": "Cocos",
             "date": "2024-03-01", "entry_price": 22000, "exit_price": 24225,
             "quantity": 9, "pnl_usd": 14.0, "pnl_pct": 1.0, "commissions": 0},
        ]
        prices = {"INTC": 134, "COIN": 163, "MELI": 1635}
        result = detect_counterfactual(ops, prices)
        self.assertTrue(result.get("insufficient_data"))

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

    def test_cedear_uses_ars_price_not_us(self):
        """Bug fix: para CEDEAR (META en Cocos), comparar buy_price ARS con
        precio ARS del CEDEAR (no con la acción US en USD)."""
        positions = [
            {
                "broker": "Cocos",
                "asset": "META",  # CEDEAR exportado sin .BA por algunos brokers
                "is_cash": 0,
                "buy_price": 38300,  # ARS
                "quantity": 5,
                "invested": 191500,  # ARS
            },
        ]
        # prices tiene tanto el .BA (ARS, sube +20%) como el US (618 USD).
        # El detector debe usar el precio AR, no el US.
        prices = {"META.BA": 45960, "META": 618}
        result = detect_recency_bias(positions, prices)
        # buy 38300 vs current 45960 → ratio 0.83 → NO flagged
        self.assertEqual(result["evidence"]["flagged_count"], 0)
        self.assertEqual(result["severity"], "positive")

    def test_cedear_without_ba_price_skipped(self):
        """Si no hay precio del .BA, skipear la posición en lugar de usar el
        precio US que daría comparación absurda."""
        positions = [
            {
                "broker": "Cocos",
                "asset": "META",
                "is_cash": 0,
                "buy_price": 38300,
                "quantity": 5,
                "invested": 191500,
            },
        ]
        # Solo está el precio US — el detector debe ignorar esta posición
        prices = {"META": 618}
        result = detect_recency_bias(positions, prices)
        # No detected — todas las posiciones fueron skipeadas por falta de
        # precio en la moneda correcta. Severidad neutral (insuficiente data)
        # o positiva (sin instancias).
        self.assertFalse(result.get("detected", False))


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


# ─── Audit de moneda (regresión) ─────────────────────────────────────────────


class CurrencyAuditTest(unittest.TestCase):
    """Regresión del deep-audit: la moneda se resuelve por la moneda REAL
    (currency/asset/sub-broker '· USD'), NO por el nombre del broker."""

    def test_native_ccy_usd_subbroker(self):
        from behavioral import _native_ccy
        # Sub-broker '· USD' aunque contenga 'cocos' → USD
        self.assertEqual(_native_ccy({"broker": "Cocos Capital · USD", "asset": "PMCAO"}), "USD")
        # Cash USDT en sub-broker AR → USD
        self.assertEqual(_native_ccy({"broker": "Cocos Capital · USD", "asset": "USDT", "is_cash": 1}), "USD")
        # CEDEAR en Cocos regular → ARS
        self.assertEqual(_native_ccy({"broker": "Cocos Capital", "asset": "GGAL"}), "ARS")
        # currency explícita gana
        self.assertEqual(_native_ccy({"broker": "Cocos Capital", "asset": "X", "currency": "USD"}), "USD")
        # Schwab → USD
        self.assertEqual(_native_ccy({"broker": "Schwab", "asset": "AAPL"}), "USD")

    def test_usd_subbroker_position_not_divided(self):
        # CRÍTICO: posición USD en 'Cocos Capital · USD' NO se divide por tc_blue.
        from behavioral import _position_value_usd
        p = {"broker": "Cocos Capital · USD", "asset": "PMCAO", "is_cash": 0,
             "buy_price": 30, "quantity": 1000, "invested": 30000, "currency": "USD"}
        v = _position_value_usd(p, prices=None, tc_blue=1415.0)
        self.assertAlmostEqual(v, 30000.0, places=2)  # antes daba 30000/1415 ≈ 21

    def test_usd_cash_in_ar_broker_not_divided(self):
        from behavioral import _position_value_usd
        p = {"broker": "Cocos Capital · USD", "asset": "USDT", "is_cash": 1, "invested": 5000}
        self.assertAlmostEqual(_position_value_usd(p, None, 1415.0), 5000.0, places=2)
        # Cash ARS sí se convierte
        p_ars = {"broker": "Cocos Capital", "asset": "ARS", "is_cash": 1, "invested": 1_415_000}
        self.assertAlmostEqual(_position_value_usd(p_ars, None, 1415.0), 1000.0, places=2)

    # ── C1 final-audit: la resolución de PRECIO (.BA vs ticker US) es ESTRUCTURAL
    #    (asset_type/·USD/AR/currency), no por nombre de broker. Sin esto, un
    #    CEDEAR en 'PPI · USD' se valuaba por el ticker US (15-100× inflado).
    def test_cedear_in_nonhint_usd_subbroker_values_via_ba_mep(self):
        from behavioral import _position_value_usd, _price_is_ars
        p = {"broker": "Mi Cartera · USD", "asset": "TSLA", "asset_type": "CEDEAR",
             "is_cash": 0, "invested": 180, "quantity": 15, "currency": "USD"}
        self.assertTrue(_price_is_ars(p))
        v = _position_value_usd(p, {"TSLA.BA": 14000}, tc_blue=1500, tc_cedear=1200)
        self.assertAlmostEqual(v, 14000 * 15 / 1200, places=2)  # 175, NO 6600

    def test_cedear_by_asset_type_in_plain_usd_broker(self):
        from behavioral import _position_value_usd
        p = {"broker": "PPI", "asset": "AAPL", "asset_type": "CEDEAR",
             "is_cash": 0, "invested": 200, "quantity": 20, "currency": "USD"}
        v = _position_value_usd(p, {"AAPL.BA": 30000}, tc_blue=1500, tc_cedear=1200)
        self.assertAlmostEqual(v, 30000 * 20 / 1200, places=2)

    def test_genuine_usd_broker_not_routed_to_ba(self):
        # 'Mi Broker USD' (sin '·') es USD genuino → ticker US, NO .BA.
        from behavioral import _position_value_usd, _price_is_ars
        p = {"broker": "Mi Broker USD", "asset": "NVDA", "asset_type": "STOCK",
             "is_cash": 0, "invested": 1000, "quantity": 10, "currency": "USD"}
        self.assertFalse(_price_is_ars(p))
        v = _position_value_usd(p, {"NVDA": 150, "NVDA.BA": 999999}, tc_blue=1500, tc_cedear=1200)
        self.assertAlmostEqual(v, 1500.0, places=2)

    def test_nonhint_ars_broker_holding_values_via_mep(self):
        from behavioral import _position_value_usd
        p = {"broker": "Santander", "asset": "GGAL", "asset_type": "STOCK_AR",
             "is_cash": 0, "invested": 50000, "quantity": 10, "currency": "ARS"}
        v = _position_value_usd(p, {"GGAL.BA": 7000}, tc_blue=1500, tc_cedear=1200)
        self.assertAlmostEqual(v, 7000 * 10 / 1200, places=2)

    def test_price_override_honored_for_value_not_cost(self):
        from behavioral import _position_value_usd
        p = {"broker": "Schwab", "asset": "X", "is_cash": 0, "invested": 300,
             "quantity": 10, "price_override": 50, "currency": "USD"}
        self.assertAlmostEqual(_position_value_usd(p, {}, 1500, 1200), 500.0, places=2)
        self.assertAlmostEqual(
            _position_value_usd(p, {}, 1500, 1200, honor_override=False), 300.0, places=2)

    def test_position_size_usd_converts_ars(self):
        from behavioral import _position_size_usd
        # Op en broker AR (ARS) → notional convertido a USD
        ars_op = {"broker": "Cocos Capital", "asset": "GGAL", "entry_price": 14150, "quantity": 10}
        self.assertAlmostEqual(_position_size_usd(ars_op, 1415.0), 100.0, places=2)
        # Op USD → sin tocar
        usd_op = {"broker": "Schwab", "asset": "AAPL", "entry_price": 100, "quantity": 10}
        self.assertAlmostEqual(_position_size_usd(usd_op, 1415.0), 1000.0, places=2)

    def test_concentration_usd_subbroker_not_shrunk(self):
        # La posición USD grande domina la concentración (no se encoge 1415x).
        positions = [
            {"broker": "Cocos Capital · USD", "asset": "PMCAO", "is_cash": 0,
             "buy_price": 30, "quantity": 1000, "invested": 30000, "currency": "USD"},
            {"broker": "Binance", "asset": "ETH", "is_cash": 0, "buy_price": 2400,
             "quantity": 1.2, "invested": 2880, "currency": "USD"},
            {"broker": "Binance", "asset": "BTC", "is_cash": 0, "buy_price": 58000,
             "quantity": 0.046, "invested": 2672, "currency": "USD"},
        ]
        r = detect_concentration(positions, prices=None, tc_blue=1415.0)
        self.assertEqual(r["evidence"]["top_asset"], "PMCAO")
        self.assertGreater(r["evidence"]["top1_pct"], 60)
        self.assertEqual(r["severity"], "high")

    def test_cash_drag_negative_cash_guard(self):
        # Cash neto negativo (margen/registración) → card neutral, no −201%.
        positions = [
            {"broker": "Cocos Capital · USD", "asset": "USDT", "is_cash": 1, "invested": -30857},
            {"broker": "Cocos Capital · USD", "asset": "PMCAO", "is_cash": 0,
             "buy_price": 30, "quantity": 1000, "invested": 30000, "currency": "USD"},
            {"broker": "Binance", "asset": "BTC", "is_cash": 0, "invested": 5000, "currency": "USD"},
        ]
        r = detect_cash_drag(positions, tc_blue=1415.0)
        self.assertEqual(r["title"], "Cash neto negativo")
        self.assertGreaterEqual(r["evidence"]["cash_pct"], 0)  # nunca negativo

    def test_inflation_loss_ignores_usd_cash_in_ar_subbroker(self):
        # El cash USDT del sub-broker '· USD' NO se cuenta como pesos.
        positions = [
            {"broker": "Cocos Capital · USD", "asset": "USDT", "is_cash": 1, "invested": 30000},
        ]
        r = detect_inflation_loss(positions, {"2026-01": 5.0, "2026-02": 5.0}, 1415.0)
        self.assertEqual(r["evidence"]["cash_ars_pesos"], 0)


# ─── MONEDA_DE_LOS_PRECIOS (behavioral.py) ───────────────────────────────────


def _precios_con_moneda(evidence):
    """Cada fila de la evidencia que muestra un PRECIO (compra, venta, hoy)."""
    filas = []
    for v in (evidence or {}).values():
        if not isinstance(v, list):
            continue
        for item in v:
            if isinstance(item, dict) and any(
                    k.endswith("_price") or k in ("first_buy", "second_buy") for k in item):
                filas.append(item)
    return filas


class MonedaDeLosPreciosTest(unittest.TestCase):
    """23/11/2026, cuenta de ejemplo: «Chase the pump» decía de Galicia (Cocos,
    en pesos) «Compraste a US$ 6.240 · hoy US$ 4.557,5». El detector comparaba
    bien pesos con pesos; lo que faltaba era DECIR la moneda: la pantalla le
    ponía «US$» a todo precio.

    Por el camino de producción: el pedido a /api/behavioral/insights, con el
    estampado de monedas por broker (currency_context) y el pedido de precios
    .BA de verdad (fetch_ba_aware_prices). Lo único reemplazado es la llamada a
    internet (_fetch_batch_quotes), por precios fijos."""

    PRECIOS = {"GGAL.BA": 4557.5, "PAMP.BA": 2900.0, "NVDA": 170.0}

    def setUp(self):
        import main
        from tests._limpieza import vaciar
        self.main = main
        conn = main.get_db()
        self.addCleanup(conn.close)
        vaciar(conn, "operations", "positions", "brokers", "users")
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
            "VALUES (?,?,1,1,'pro')", ("moneda-precios@rendi.test", "x")).lastrowid
        for nombre, moneda in (("Cocos", "ARS"), ("Banco Santander", "ARS"),
                               ("Interactive Brokers", "USD")):
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, nombre, moneda))
        # Galicia en Cocos (como la cuenta de ejemplo); Pampa en un broker en
        # pesos SIN nombre conocido y sin moneda en la fila (la estampa el broker);
        # NVDA en dólares.
        for broker, asset, moneda, compra, qty in (
                ("Cocos", "GGAL", "ARS", 6240.0, 400),
                ("Banco Santander", "PAMP", None, 4030.0, 500),
                ("Interactive Brokers", "NVDA", "USD", 250.0, 10)):
            conn.execute(
                "INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity, "
                "invested, currency) VALUES (?,?,?,0,?,?,?,?)",
                (self.uid, broker, asset, compra, qty, compra * qty, moneda))
        # Compras de GGAL: dos en pesos que bajan (una instancia real de
        # «promediar a la baja») y después el ADR en dólares, que comparte
        # ticker: $5.000 → US$ 30 NO es una caída del 99 %.
        for fecha, broker, precio, moneda in (("2024-03-01", "Cocos", 6000.0, "ARS"),
                                              ("2024-03-10", "Cocos", 5000.0, "ARS"),
                                              ("2024-03-20", "Interactive Brokers", 30.0, "USD")):
            conn.execute(
                "INSERT INTO operations (user_id, date, asset, broker, op_type, quantity, "
                "entry_price, entry_date, currency) VALUES (?,?,?,?,?,?,?,?,?)",
                (self.uid, fecha, "GGAL", broker, "Compra", 10, precio, fecha, moneda))
        # Tres ventas en dólares para que corra la contrafáctica.
        # (de NVDA: el servidor sólo pide el precio de hoy de lo que está en cartera)
        for i, (asset, entrada, salida) in enumerate((("NVDA", 90, 120), ("NVDA", 110, 130),
                                                      ("NVDA", 100, 140))):
            fecha = f"2024-0{i + 4}-15"
            conn.execute(
                "INSERT INTO operations (user_id, date, asset, broker, op_type, quantity, "
                "entry_price, exit_price, entry_date, pnl_usd, currency) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (self.uid, fecha, asset, "Interactive Brokers", "LONG", 1, entrada, salida,
                 "2024-01-02", salida - entrada, "USD"))
        conn.commit()

    def _tarjetas(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        main = self.main
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)

        def cotizaciones(simbolos, *a, **k):
            return {s: {"price": self.PRECIOS[s]} for s in simbolos if s in self.PRECIOS}

        with patch("home.market._fetch_batch_quotes", side_effect=cotizaciones):
            r = TestClient(main.app).get("/api/behavioral/insights")
        self.assertEqual(r.status_code, 200, r.text)
        return {c["code"]: c for c in r.json()["cards"]}

    def test_chase_the_pump_dice_la_moneda_de_cada_precio(self):
        ev = self._tarjetas()["recency_bias"]["evidence"]
        por_activo = {a["asset"]: a for a in ev["flagged_assets"]}
        galicia = por_activo["GGAL"]
        self.assertEqual((galicia["buy_price"], galicia["current_price"], galicia["moneda"]),
                         (6240.0, 4557.5, "ARS"))
        self.assertEqual(por_activo["NVDA"]["moneda"], "USD")

    def test_broker_en_pesos_sin_nombre_conocido_entra_al_detector(self):
        """Antes la moneda del precio se decidía por el NOMBRE del broker: un
        «Banco Santander» en pesos quedaba afuera aunque su precio .BA estaba
        pedido. Ahora se decide igual que al pedir el precio y al valuar."""
        ev = self._tarjetas()["recency_bias"]["evidence"]
        pampa = {a["asset"]: a for a in ev["flagged_assets"]}.get("PAMP")
        self.assertIsNotNone(pampa, ev)
        self.assertEqual((pampa["current_price"], pampa["moneda"]), (2900.0, "ARS"))

    def test_promediar_a_la_baja_no_mezcla_pesos_con_dolares(self):
        ev = self._tarjetas()["averaging_down"]["evidence"]
        self.assertEqual(ev["total_instances"], 1, ev)
        par = ev["instances"][0]
        self.assertEqual(par["moneda"], "ARS")
        self.assertEqual((par["first_buy"]["price"], par["second_buy"]["price"]), (6000.0, 5000.0))
        self.assertEqual(ev["total_assets_checked"], 1)  # GGAL es UN activo, en dos monedas

    def test_contrafactica_dice_dolares(self):
        ev = self._tarjetas()["counterfactual"]["evidence"]
        self.assertTrue(ev["top_misses"], ev)
        self.assertEqual({m["moneda"] for m in ev["top_misses"]}, {"USD"})

    def test_ningun_precio_viaja_sin_moneda(self):
        """La regla general: un detector nuevo que muestre precios sin decir la
        moneda falla acá, antes de que la pantalla tenga que adivinarla."""
        vistos = 0
        for code, card in self._tarjetas().items():
            for fila in _precios_con_moneda(card.get("evidence")):
                vistos += 1
                self.assertIn(fila.get("moneda"), ("ARS", "USD"), f"{code}: {fila}")
        self.assertGreaterEqual(vistos, 5)  # que el recorrido no pase vacío


if __name__ == "__main__":
    unittest.main()
