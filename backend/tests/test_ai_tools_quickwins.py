"""Audit IA #2 — quick-wins de tools/prompt (M12 FX, M10/B-8 bonos, M20 gating,
B-4 few-shot). Todos verifican comportamiento observable por el LLM."""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main


class TestM20ToolGating(unittest.TestCase):
    """Free/Plus reciben solo tools de datos propios + chips de onboarding; las
    de investigación de mercado externa quedan Pro-only."""

    def test_free_set_has_onboarding_chips_and_own_data(self):
        free = {t["name"] for t in main._AI_TOOLS_FREE}
        for must in ("get_value_scorecard", "get_earnings_history",
                     "get_realized_vs_unrealized"):
            self.assertIn(must, free)

    def test_free_set_excludes_market_research(self):
        free = {t["name"] for t in main._AI_TOOLS_FREE}
        # get_current_prices volvió a Free con el registro conversacional
        # (default de precio-de-hoy del flujo register_trade; el prompt FREE
        # lo limita a ese uso). El resto del research de mercado sigue Pro.
        for pro_only in ("get_fx_rates", "get_market_news",
                         "get_stock_fundamentals", "get_analyst_ratings",
                         "get_company_profile", "get_recent_news_for_assets",
                         "get_ar_bond_metadata"):
            self.assertNotIn(pro_only, free, f"{pro_only} no debería ser Free")

    def test_free_is_strict_subset_of_full(self):
        full = {t["name"] for t in main._AI_TOOLS}
        free = {t["name"] for t in main._AI_TOOLS_FREE}
        self.assertTrue(free < full)
        self.assertGreater(len(full) - len(free), 3)  # varias tools Pro-only


class TestM20PromptToolConsistency(unittest.TestCase):
    """El prompt FREE no puede anunciar tools que el request no lleva — el
    modelo las emite por NOMBRE EXACTO y sin enforcement se ejecutarían
    (bypass del gating). Este test fuerza que prompt y subset no diverjan."""

    def test_free_prompt_only_mentions_free_tools(self):
        import re
        mentioned = set(re.findall(r"\b(get_[a-z_]+|remember_[a-z_]+)\b",
                                   main._AI_CHAT_SYSTEM_FREE))
        leaked = mentioned - main._AI_TOOLS_FREE_NAMES
        self.assertEqual(leaked, set(),
                         f"El prompt FREE menciona tools fuera del subset: {leaked}")

    def test_pro_prompt_mentions_fx_tool(self):
        """El inventario Pro incluye get_fx_rates (sin esto el modelo rutea
        '¿a cuánto está el dólar?' a get_market_news y no da el número)."""
        self.assertIn("get_fx_rates", main._AI_CHAT_SYSTEM)


class TestM20ExecutionEnforcement(unittest.TestCase):
    """El gate por tier se aplica también en EJECUCIÓN: un tool_use Pro-only
    emitido en un request Free se rechaza sin ejecutar."""

    class _Block:
        type = "tool_use"
        id = "tu_1"

        def __init__(self, name):
            self.name = name
            self.input = {}

    def test_out_of_tier_tool_rejected_without_executing(self):
        free_names = frozenset(t["name"] for t in main._AI_TOOLS_FREE)
        with patch.object(main, "_execute_ai_tool") as mock_exec:
            results, total = main._ai_chat_exec_tools(
                [self._Block("get_stock_fundamentals")], uid=1, tier="free",
                tool_calls_total=0, max_calls=3, allowed_names=free_names)
        mock_exec.assert_not_called()                      # NO se ejecutó
        self.assertEqual(total, 0)                          # no consumió slot
        self.assertIn("no está disponible", results[0]["content"])

    def test_in_tier_tool_executes(self):
        free_names = frozenset(t["name"] for t in main._AI_TOOLS_FREE)
        with patch.object(main, "_execute_ai_tool", return_value={"ok": 1}) as mock_exec:
            results, total = main._ai_chat_exec_tools(
                [self._Block("get_value_scorecard")], uid=1, tier="free",
                tool_calls_total=0, max_calls=3, allowed_names=free_names)
        mock_exec.assert_called_once()
        self.assertEqual(total, 1)

    def test_no_allowed_set_backward_compatible(self):
        """allowed_names=None (callers legacy) → sin restricción."""
        with patch.object(main, "_execute_ai_tool", return_value={"ok": 1}) as mock_exec:
            main._ai_chat_exec_tools(
                [self._Block("get_stock_fundamentals")], uid=1, tier="pro",
                tool_calls_total=0, max_calls=3)
        mock_exec.assert_called_once()


class TestM12FxTool(unittest.TestCase):
    def test_get_fx_rates_returns_all_dollars(self):
        fake = {
            "mep": {"venta": 1400}, "ccl": {"venta": 1450},
            "blue": {"venta": 1480}, "cripto": {"venta": 1460},
        }
        with patch.object(main, "_get_dolar_data", return_value=fake):
            r = main._execute_ai_tool_inner("get_fx_rates", {}, 1)
        self.assertIn("rates_ars_per_usd", r)
        self.assertEqual(r["rates_ars_per_usd"]["mep"], 1400)
        self.assertEqual(r["rates_ars_per_usd"]["blue"], 1480)
        self.assertIn("MEP", r["note"])  # aclara la base de valuación

    def test_get_fx_rates_handles_empty(self):
        with patch.object(main, "_get_dolar_data", return_value={}):
            r = main._execute_ai_tool_inner("get_fx_rates", {}, 1)
        self.assertIn("error", r)

    def test_get_fx_rates_handles_source_failure(self):
        with patch.object(main, "_get_dolar_data", side_effect=RuntimeError("down")):
            r = main._execute_ai_tool_inner("get_fx_rates", {}, 1)
        self.assertIn("error", r)


class TestM10BondFallback(unittest.TestCase):
    """get_current_prices resuelve bonos AR por data912 (per-1), no null."""

    def test_bond_fallback_overrides_yfinance_none(self):
        # yfinance no cotiza AL30 → None; el fallback de bonos lo resuelve.
        with patch.object(main, "_fetch_one", return_value=None), \
             patch.object(main, "_resolve_ar_bond_price",
                          side_effect=lambda s: 0.72 if s == "AL30" else None):
            r = main._execute_ai_tool_inner("get_current_prices",
                                            {"symbols": ["AL30"]}, 1)
        self.assertEqual(r["prices"]["AL30"], 0.72)

    def test_non_bond_keeps_yfinance_price(self):
        with patch.object(main, "_fetch_one", return_value=215.0), \
             patch.object(main, "_resolve_ar_bond_price", return_value=None):
            r = main._execute_ai_tool_inner("get_current_prices",
                                            {"symbols": ["NVDA"]}, 1)
        self.assertEqual(r["prices"]["NVDA"], 215.0)

    def test_bond_dc_variant_normalized(self):
        """AL30D (especie MEP): se normaliza a la base para el lookup — antes
        buscaba 'AL30DD' → null teniendo el precio exacto en data912."""
        def fake_resolve(s):
            return 0.72 if s == "AL30" else None
        with patch.object(main, "_fetch_one", return_value=None), \
             patch.object(main, "_resolve_ar_bond_price", side_effect=fake_resolve):
            r = main._execute_ai_tool_inner("get_current_prices",
                                            {"symbols": ["AL30D"]}, 1)
        self.assertEqual(r["prices"]["AL30D"], 0.72)


class TestB4FewShotNoOperationalAdvice(unittest.TestCase):
    """El few-shot 'bueno' del Pro ya no modela consejo operativo prohibido."""

    def test_no_take_partial_profit_in_good_example(self):
        sys_pro = main._AI_CHAT_SYSTEM
        # La regla prohíbe 'sacale ganancia parcial'; el ejemplo bueno no debe
        # modelar 'tomar ganancia parcial'.
        self.assertNotIn("tomar ganancia parcial", sys_pro.lower())
        # Y ya no debe decir "justifican mantener" (recomendación de holdear).
        self.assertNotIn("justifican mantener", sys_pro.lower())


if __name__ == "__main__":
    unittest.main()
