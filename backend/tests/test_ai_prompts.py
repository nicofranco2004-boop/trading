"""Tests para backend/ai/prompts.py — system prompts duales por tier."""
from __future__ import annotations
import pytest

from ai import prompts


# Lista canónica de todos los render_*_prompt — si cambia, agregar acá
ALL_RENDERS = [
    "render_dashboard_prompt",
    "render_position_prompt",
    "render_behavioral_prompt",
    "render_behavioral_card_prompt",
    "render_dashboard_composition_prompt",
    "render_dashboard_evolution_prompt",
    "render_dashboard_top_holdings_prompt",
    "render_dashboard_brokers_prompt",
    "render_dashboard_events_prompt",
    "render_insights_prompt",
    "render_insights_evolution_prompt",
    "render_insights_drawdown_prompt",
    "render_insights_attribution_prompt",
    "render_insights_benchmarks_prompt",
    "render_insights_observation_prompt",
    "render_monthly_prompt",
    # Phase 2 — Reports / Position / Goals
    "render_monthly_insight_prompt",
    "render_position_chart_prompt",
    "render_position_lots_prompt",
    "render_goal_prompt",
]


# ── SYSTEM_BASE_FREE / PRO existen y son distintos ───────────────────────────

def test_system_base_free_exists_and_nonempty():
    assert hasattr(prompts, "SYSTEM_BASE_FREE")
    assert len(prompts.SYSTEM_BASE_FREE) > 200


def test_system_base_pro_exists_and_nonempty():
    assert hasattr(prompts, "SYSTEM_BASE_PRO")
    assert len(prompts.SYSTEM_BASE_PRO) > 1000


def test_system_base_free_is_simpler_than_pro():
    """Free tiene que ser claramente más corto / simple que Pro."""
    assert len(prompts.SYSTEM_BASE_FREE) < len(prompts.SYSTEM_BASE_PRO)


def test_system_base_legacy_alias_is_pro():
    """SYSTEM_BASE (alias legacy) debe apuntar al manifiesto Pro."""
    assert prompts.SYSTEM_BASE == prompts.SYSTEM_BASE_PRO


def test_free_prompt_forbids_interpretation():
    """El manifiesto Free debe instruir explícitamente a NO interpretar."""
    free = prompts.SYSTEM_BASE_FREE.lower()
    # Una de estas palabras clave tiene que aparecer — instrucción explícita
    assert any(
        phrase in free
        for phrase in ["no interpretar", "no interpretarlos", "describir, no interpretar",
                       "describir", "resumen plano", "sin interpretar"]
    )


def test_pro_prompt_requires_insight_memorable():
    """El manifiesto Pro debe pedir explícitamente insight memorable."""
    pro = prompts.SYSTEM_BASE_PRO.lower()
    assert "insight memorable" in pro


def test_free_prompt_forbids_operative_advice():
    """El manifiesto Free debe explicitar la prohibición de asesorar operaciones."""
    free = prompts.SYSTEM_BASE_FREE.lower()
    # Debe mencionar explícitamente la regla anti-asesoramiento. Buscamos
    # cualquiera de las formas en que pudimos haberla escrito.
    assert any(
        s in free for s in [
            "cero asesoramiento", "no recomendar", "sin asesoramiento",
            "asesoramiento operativo", "operatoria",
        ]
    )


# ── Cada render funciona en ambos tiers ──────────────────────────────────────

@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_pro_returns_pro_manifesto(render_name):
    fn = getattr(prompts, render_name)
    out = fn(tier="pro")
    assert out.startswith(prompts.SYSTEM_BASE_PRO[:200])  # arranca con base Pro
    assert len(out) > len(prompts.SYSTEM_BASE_PRO)  # tiene bloque específico además


@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_free_returns_free_manifesto(render_name):
    fn = getattr(prompts, render_name)
    out = fn(tier="free")
    assert out.startswith(prompts.SYSTEM_BASE_FREE[:200])
    assert len(out) > len(prompts.SYSTEM_BASE_FREE)


@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_default_tier_is_pro(render_name):
    """Sin args, los renders devuelven el prompt Pro (back-compat)."""
    fn = getattr(prompts, render_name)
    default = fn()
    pro = fn(tier="pro")
    assert default == pro


@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_pro_and_free_are_different(render_name):
    """Para todos los topics, Pro y Free devuelven prompts distintos."""
    fn = getattr(prompts, render_name)
    assert fn(tier="pro") != fn(tier="free")


@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_pro_is_longer_than_free(render_name):
    """Pro siempre tiene más contenido (manifiesto + insight examples + pitfalls)."""
    fn = getattr(prompts, render_name)
    assert len(fn(tier="pro")) > len(fn(tier="free"))


# ── Determinismo: misma llamada siempre devuelve el mismo string ─────────────

@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_is_deterministic(render_name):
    """Crítico para prompt caching de Anthropic — mismo input = mismo output."""
    fn = getattr(prompts, render_name)
    a = fn(tier="pro")
    b = fn(tier="pro")
    assert a == b


# ── Cacheabilidad: no debe haber timestamps/UUIDs ────────────────────────────

@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_pro_has_no_timestamps(render_name):
    """El system prompt no puede tener nada volátil — invalidaría el cache."""
    fn = getattr(prompts, render_name)
    out = fn(tier="pro")
    # Heurística: no debe haber año actual ni patrones de timestamp ISO
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", out)
    assert not re.search(r"\d{4}-\d{2}-\d{2}\s\d{2}:", out)


@pytest.mark.parametrize("render_name", ALL_RENDERS)
def test_render_free_has_no_timestamps(render_name):
    fn = getattr(prompts, render_name)
    out = fn(tier="free")
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", out)
    assert not re.search(r"\d{4}-\d{2}-\d{2}\s\d{2}:", out)


# ── Tier unknown → tratado como Pro (failsafe) ───────────────────────────────

def test_unknown_tier_falls_back_to_pro():
    """Si alguien pasa tier='enterprise' o similar, no rompe — usa Pro."""
    out_unknown = prompts.render_dashboard_prompt(tier="enterprise")
    out_pro = prompts.render_dashboard_prompt(tier="pro")
    assert out_unknown == out_pro


# ── Anti-regression: el Free no debe pedir insights memorables ───────────────

def test_free_prompt_does_not_request_insight_memorable():
    """Crítico: si el Free pide 'insight memorable', se desdibuja la
    diferenciación con Pro."""
    free = prompts.render_dashboard_prompt(tier="free")
    # 'insight memorable' no debe aparecer como instrucción al LLM
    # (aunque podría aparecer en el bloque "Diferenciación con Pro" del manifiesto)
    free_lower = free.lower()
    # Solo verificamos que NO esté en el bloque de "qué describir" (topic-specific)
    # Tomamos solo la parte después del SYSTEM_BASE_FREE para mirar el bloque del topic
    topic_block = free_lower[len(prompts.SYSTEM_BASE_FREE):]
    assert "insight memorable" not in topic_block
