"""registry — mapeo topic_id → (builder, prompt).
═══════════════════════════════════════════════════════════════════════════
Sprint AI v2. Cada topic_id es un screen o sub-componente del producto.
Notación con puntos para sub-topics:
    dashboard                  — análisis general
    dashboard.composition      — solo la composición (top holdings + HHI)
    dashboard.evolution        — solo la curva de valor
    dashboard.top_holdings     — solo el top de posiciones con P/L

El router (endpoint /api/ai/analyze) recibe `screen` y busca acá:
    fn_builder, fn_prompt = REGISTRY[screen]
    packet = fn_builder(conn, uid, **params)
    system = fn_prompt()

Agregar un topic = agregar una entrada acá + escribir el builder + el
prompt. No tocar nada del endpoint.
"""

from __future__ import annotations
from typing import Callable, Dict, Tuple

from . import prompts
from .builders.dashboard import build as build_dashboard
from .builders.dashboard_composition import build as build_dashboard_composition
from .builders.dashboard_evolution import build as build_dashboard_evolution
from .builders.dashboard_top_holdings import build as build_dashboard_top_holdings
from .builders.dashboard_brokers import build as build_dashboard_brokers
from .builders.dashboard_events import build as build_dashboard_events
from .builders.behavioral import build as build_behavioral
from .builders.behavioral_card import build as build_behavioral_card
from .builders.profile_card import build as build_profile_card
from .builders.profile_summary import build as build_profile_summary
from .builders.metrics_pro_card import build as build_metrics_pro_card
from .builders.insights import build as build_insights
from .builders.insights_summary import build as build_insights_summary
from .builders.insights_evolution import build as build_insights_evolution
from .builders.insights_drawdown import build as build_insights_drawdown
from .builders.insights_attribution import build as build_insights_attribution
from .builders.insights_benchmarks import build as build_insights_benchmarks
from .builders.insights_observation import build as build_insights_observation
from .builders.monthly import build as build_monthly
from .builders.monthly_insight import build as build_monthly_insight
from .builders.position import build as build_position
from .builders.position_chart import build as build_position_chart
from .builders.position_lots import build as build_position_lots
from .builders.goal import build as build_goal
from .builders.home import build as build_home
from .builders.news import build as build_news
from .builders.news_item import build as build_news_item
from .builders.events import build as build_events
from .builders.events_item import build as build_events_item
from .builders.reports import build as build_reports
from .builders.operations import build as build_operations
from .builders.operation_trade import build as build_operation_trade
from .builders.fundamentals_category import build as build_fundamentals_category


# topic_id → (builder_fn, prompt_fn)
REGISTRY: Dict[str, Tuple[Callable, Callable]] = {
    "dashboard": (build_dashboard, prompts.render_dashboard_prompt),
    "dashboard.composition": (build_dashboard_composition, prompts.render_dashboard_composition_prompt),
    "dashboard.evolution": (build_dashboard_evolution, prompts.render_dashboard_evolution_prompt),
    "dashboard.top_holdings": (build_dashboard_top_holdings, prompts.render_dashboard_top_holdings_prompt),
    "dashboard.brokers": (build_dashboard_brokers, prompts.render_dashboard_brokers_prompt),
    "dashboard.upcoming_events": (build_dashboard_events, prompts.render_dashboard_events_prompt),
    "behavioral": (build_behavioral, prompts.render_behavioral_prompt),
    "behavioral.card": (build_behavioral_card, prompts.render_behavioral_card_prompt),
    "profile.card": (build_profile_card, prompts.render_profile_card_prompt),
    "profile.summary": (build_profile_summary, prompts.render_profile_summary_prompt),
    "metrics_pro.card": (build_metrics_pro_card, prompts.render_metrics_pro_card_prompt),
    "insights": (build_insights, prompts.render_insights_prompt),
    "insights.summary": (build_insights_summary, prompts.render_insights_summary_prompt),
    "insights.evolution": (build_insights_evolution, prompts.render_insights_evolution_prompt),
    "insights.drawdown": (build_insights_drawdown, prompts.render_insights_drawdown_prompt),
    "insights.attribution": (build_insights_attribution, prompts.render_insights_attribution_prompt),
    "insights.benchmarks": (build_insights_benchmarks, prompts.render_insights_benchmarks_prompt),
    "insights.observation": (build_insights_observation, prompts.render_insights_observation_prompt),
    # Phase 2: Monthly + Position + Goals
    "monthly": (build_monthly, prompts.render_monthly_prompt),
    "monthly.insight": (build_monthly_insight, prompts.render_monthly_insight_prompt),
    "position": (build_position, prompts.render_position_prompt),
    "position.chart": (build_position_chart, prompts.render_position_chart_prompt),
    "position.lots": (build_position_lots, prompts.render_position_lots_prompt),
    "goal": (build_goal, prompts.render_goal_prompt),
    # Phase 3: Home + Novedades (News + Events)
    "home": (build_home, prompts.render_home_prompt),
    "news": (build_news, prompts.render_news_prompt),
    "news.item": (build_news_item, prompts.render_news_item_prompt),
    "events": (build_events, prompts.render_events_prompt),
    "events.item": (build_events_item, prompts.render_events_item_prompt),
    "reports": (build_reports, prompts.render_reports_prompt),
    "operations": (build_operations, prompts.render_operations_prompt),
    "operations.trade": (build_operation_trade, prompts.render_operation_trade_prompt),
    # Calidad de cartera — análisis curado de UNA dimensión fundamental de una acción.
    "fundamentals.category": (build_fundamentals_category, prompts.render_fundamentals_category_prompt),
}


def get_topic(screen: str) -> Tuple[Callable, Callable] | None:
    """Devuelve (builder, prompt) o None si el topic no existe."""
    return REGISTRY.get(screen.strip().lower())


def list_topics() -> list[str]:
    """Lista todos los topics registrados — útil para validación + docs."""
    return sorted(REGISTRY.keys())
