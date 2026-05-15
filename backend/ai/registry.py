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


# topic_id → (builder_fn, prompt_fn)
REGISTRY: Dict[str, Tuple[Callable, Callable]] = {
    "dashboard": (build_dashboard, prompts.render_dashboard_prompt),
    "dashboard.composition": (build_dashboard_composition, prompts.render_dashboard_composition_prompt),
    "dashboard.evolution": (build_dashboard_evolution, prompts.render_dashboard_evolution_prompt),
    "dashboard.top_holdings": (build_dashboard_top_holdings, prompts.render_dashboard_top_holdings_prompt),
    "dashboard.brokers": (build_dashboard_brokers, prompts.render_dashboard_brokers_prompt),
    "dashboard.upcoming_events": (build_dashboard_events, prompts.render_dashboard_events_prompt),
    "behavioral": (build_behavioral, prompts.render_behavioral_prompt),
}


def get_topic(screen: str) -> Tuple[Callable, Callable] | None:
    """Devuelve (builder, prompt) o None si el topic no existe."""
    return REGISTRY.get(screen.strip().lower())


def list_topics() -> list[str]:
    """Lista todos los topics registrados — útil para validación + docs."""
    return sorted(REGISTRY.keys())
