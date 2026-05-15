"""Tests para backend/goals_diagnostic.py (Sprint 7 — Goals 2.0)."""
from __future__ import annotations
import pytest
from datetime import datetime
from goals_diagnostic import (
    build_goal_diagnostic,
    _months_between,
    _required_monthly_rate,
    _eta_months,
    _project_value,
    _pick_dominant_bias,
    SUGGESTION_MAP,
)


NOW = datetime(2026, 5, 1)


def make_goal(target=20000, date='2027-05-01'):
    return {'target_usd': target, 'target_date': date}


# ── Helpers de cálculo ────────────────────────────────────────────────────

def test_months_between_basic():
    assert _months_between('2026-05-01', NOW) == 0
    assert _months_between('2026-11-01', NOW) == 6
    assert _months_between('2027-05-01', NOW) == 12
    assert _months_between('2028-05-01', NOW) == 24


def test_months_between_past_returns_zero():
    assert _months_between('2025-01-01', NOW) == 0


def test_months_between_invalid_format():
    assert _months_between('not-a-date', NOW) is None
    assert _months_between(None, NOW) is None
    assert _months_between('', NOW) is None


def test_required_monthly_rate_double_in_12_months():
    # Necesitás duplicar en 12 meses
    r = _required_monthly_rate(10000, 20000, 12)
    # (1+r)^12 = 2 → r = 2^(1/12) - 1 ≈ 0.0595
    assert r == pytest.approx(0.0595, abs=1e-3)


def test_required_monthly_rate_edge_cases():
    assert _required_monthly_rate(0, 1000, 12) is None
    assert _required_monthly_rate(1000, 0, 12) is None
    assert _required_monthly_rate(1000, 2000, 0) is None


def test_eta_months_simple():
    # Tasa 5%/mes, current 10000, target 20000
    # ETA = log(2) / log(1.05) ≈ 14.2 → ceil = 15
    eta = _eta_months(10000, 20000, 0.05)
    assert eta == 15


def test_eta_months_already_reached():
    assert _eta_months(20000, 10000, 0.05) == 0


def test_eta_months_zero_rate_is_unreachable():
    assert _eta_months(10000, 20000, 0) is None
    assert _eta_months(10000, 20000, -0.01) is None


def test_eta_months_caps_very_long():
    # Rate microscópico, target lejano → unreachable (>600 meses)
    assert _eta_months(100, 1e9, 0.0001) is None


def test_project_value_compounds():
    # 10000 al 1%/mes durante 12 meses
    v = _project_value(10000, 0.01, 12)
    # (1.01)^12 ≈ 1.1268
    assert v == pytest.approx(11268.25, abs=1)


# ── Pick dominant bias ────────────────────────────────────────────────────

def test_pick_dominant_bias_picks_highest_severity():
    cards = [
        {'code': 'overtrade', 'severity': 'low'},
        {'code': 'disposition_effect', 'severity': 'high'},
        {'code': 'home_bias', 'severity': 'medium'},
    ]
    pick = _pick_dominant_bias(cards)
    assert pick['code'] == 'disposition_effect'


def test_pick_dominant_bias_skips_insufficient():
    cards = [
        {'code': 'overtrade', 'severity': 'high', 'insufficient_data': True},
        {'code': 'home_bias', 'severity': 'low'},
    ]
    pick = _pick_dominant_bias(cards)
    assert pick['code'] == 'home_bias'


def test_pick_dominant_bias_skips_unknown_code():
    cards = [
        {'code': 'unknown_bias', 'severity': 'high'},
        {'code': 'overtrade', 'severity': 'low'},
    ]
    pick = _pick_dominant_bias(cards)
    assert pick['code'] == 'overtrade'


def test_pick_dominant_bias_none_when_only_positive():
    cards = [
        {'code': 'overtrade', 'severity': 'positive'},
        {'code': 'concentration', 'severity': 'neutral'},
    ]
    assert _pick_dominant_bias(cards) is None


def test_pick_dominant_bias_none_when_empty():
    assert _pick_dominant_bias([]) is None
    assert _pick_dominant_bias(None) is None


# ── build_goal_diagnostic — integration ───────────────────────────────────

def test_diagnostic_already_reached():
    out = build_goal_diagnostic(make_goal(10000), 15000, user_cagr_pct=10, now=NOW)
    assert out['status'] == 'ahead'
    assert 'alcanzada' in out['diagnostic'].lower()
    assert out['eta_months_at_current_rate'] == 0
    assert out['suggestion'] is None


def test_diagnostic_on_track():
    # Necesita duplicar en 12 meses → 5.95%/mes ≈ 100% anual.
    # Si user tiene 100% anual, va on_track.
    out = build_goal_diagnostic(
        make_goal(20000, '2027-05-01'),
        current_value=10000,
        user_cagr_pct=100,
        now=NOW,
    )
    assert out['status'] == 'on_track'
    assert out['suggestion'] is None  # No abrumar si va bien


def test_diagnostic_behind_with_suggestion():
    # Necesita mucho más de lo que rinde, y tiene un sesgo dominante
    cards = [
        {'code': 'overtrade', 'severity': 'high', 'title': 'Operás demasiado', 'one_liner': '...'}
    ]
    out = build_goal_diagnostic(
        make_goal(50000, '2027-05-01'),
        current_value=10000,
        user_cagr_pct=5,
        behavioral_cards=cards,
        now=NOW,
    )
    assert out['status'] == 'behind'
    assert out['suggestion'] is not None
    assert out['suggestion']['code'] == 'overtrade'
    assert 'comisiones' in out['suggestion']['action'].lower()


def test_diagnostic_behind_without_suggestion_when_no_bias():
    out = build_goal_diagnostic(
        make_goal(50000, '2027-05-01'),
        current_value=10000,
        user_cagr_pct=5,
        behavioral_cards=[],
        now=NOW,
    )
    assert out['status'] == 'behind'
    assert out['suggestion'] is None


def test_diagnostic_unreachable_with_no_rate():
    out = build_goal_diagnostic(
        make_goal(50000, '2027-05-01'),
        current_value=10000,
        user_cagr_pct=-50,  # rinde negativo
        now=NOW,
    )
    assert out['status'] == 'behind'
    assert out['eta_months_at_current_rate'] is None


def test_diagnostic_projection_present():
    out = build_goal_diagnostic(
        make_goal(20000, '2027-05-01'),
        current_value=10000,
        user_cagr_pct=12,
        now=NOW,
    )
    # 12% anual durante 12 meses → 10000 * 1.12 = 11200
    assert out['projected_value_at_target_date'] == pytest.approx(11200, abs=1)
    assert out['months_left'] == 12
    assert out['required_annual_pct'] is not None


def test_diagnostic_invalid_date():
    out = build_goal_diagnostic(
        {'target_usd': 20000, 'target_date': 'invalid'},
        current_value=10000,
        user_cagr_pct=10,
        now=NOW,
    )
    assert out['status'] == 'unknown'
    assert out['suggestion'] is None


def test_all_suggestion_codes_match_behavioral_codes():
    """Smoke test: códigos de SUGGESTION_MAP deben matchear con los
    códigos del módulo behavioral. Si esto rompe, alguien renombró un
    detector y olvidó actualizar acá."""
    from behavioral import build_behavioral_insights
    out = build_behavioral_insights([], [], {}, {}, 1000)
    actual_codes = {c.get('code') for c in out.get('cards', [])}
    suggestion_codes = set(SUGGESTION_MAP.keys())
    # Cada code en SUGGESTION_MAP debe existir en behavioral (al menos como insufficient_data)
    missing = suggestion_codes - actual_codes
    assert not missing, f'Suggestion codes not in behavioral: {missing}'
