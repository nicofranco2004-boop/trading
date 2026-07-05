"""builders.goal — packet de un objetivo financiero.
═══════════════════════════════════════════════════════════════════════════
Topic: goal

Params:
  goal_id: int — id del registro en goals

Reusa /api/goals/{id}/diagnostic logic si está disponible. Si falla,
arma un packet básico desde el row de la tabla.
"""
from __future__ import annotations
from typing import Dict, Any
from datetime import date


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    goal_id = kwargs.get("goal_id")
    if goal_id is None:
        raise ValueError("Falta param 'goal_id'.")
    try:
        goal_id = int(goal_id)
    except (TypeError, ValueError):
        raise ValueError("goal_id debe ser entero.")

    row = conn.execute(
        "SELECT * FROM goals WHERE id=? AND user_id=?",
        (goal_id, user_id),
    ).fetchone()
    if not row:
        raise ValueError(f"Goal {goal_id} no encontrado.")
    g = dict(row)

    target_usd = float(g.get("target_usd") or 0)
    target_date_iso = g.get("target_date")
    monthly_contribution = float(g.get("monthly_contribution") or 0)
    expected_return_pct = float(g.get("expected_return_pct") or 0)

    # Capital actual del user (snapshot más reciente)
    snap = conn.execute(
        "SELECT total_value FROM snapshots WHERE user_id=? ORDER BY date DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    current_capital_usd = float(snap["total_value"]) if snap and snap["total_value"] else 0.0

    # Progreso simple
    progress_pct = (current_capital_usd / target_usd * 100) if target_usd > 0 else None
    gap_usd = max(0.0, target_usd - current_capital_usd)

    # Months to target (si hay target_date)
    months_left = None
    if target_date_iso:
        try:
            td = date.fromisoformat(str(target_date_iso)[:10])
            today = date.today()
            months_left = max(0, (td.year - today.year) * 12 + (td.month - today.month))
        except (TypeError, ValueError):
            months_left = None

    # CAGR histórico real del portfolio (mismo origen que /api/goals/cagr:
    # snapshots MTM). Es el "ritmo" del user que usan el diagnóstico y el
    # escenario histórico. Import diferido de main (mismo idioma que dashboard.py).
    user_cagr_pct = None
    try:
        from main import _historical_cagr_global
        user_cagr_pct = _historical_cagr_global(conn, user_id).get("cagr")
    except Exception:
        user_cagr_pct = None

    # Diagnóstico REAL vía goals_diagnostic — la MISMA lógica que el endpoint
    # /api/goals/{id}/diagnostic. ANTES importaba 'goals.diagnostic'
    # (módulo/función inexistentes) → el except lo tragaba y el diagnóstico
    # salía SIEMPRE vacío (status/eta/required en null), degradando el análisis
    # de Objetivos al MISMO costo de LLM. Ahora se llama la función real con el
    # capital actual y el CAGR del propio portfolio.
    diagnostic: Dict[str, Any] = {}
    try:
        from goals_diagnostic import build_goal_diagnostic
        diagnostic = build_goal_diagnostic(
            g,
            current_value=current_capital_usd,
            user_cagr_pct=user_cagr_pct,
        ) or {}
    except Exception:
        diagnostic = {}

    # Escenarios de proyección al target_date por tasa de retorno anual, SIN
    # aportes (mismo criterio que build_goal_diagnostic._project_value).
    # 'objetivo' = tasa que asume la meta; 'histórico' = ritmo real del portfolio
    # → alimenta la comparación de escenarios que pide el prompt.
    scenarios: list = []
    if months_left and current_capital_usd > 0 and target_usd > 0:
        try:
            from goals_diagnostic import _project_value
            for label, annual_pct in (("objetivo", expected_return_pct),
                                       ("histórico", user_cagr_pct)):
                if annual_pct is None:
                    continue
                monthly = (1 + float(annual_pct) / 100) ** (1 / 12) - 1
                proj = _project_value(current_capital_usd, monthly, months_left)
                scenarios.append({
                    "label": label,
                    "annual_return_pct": round(float(annual_pct), 2),
                    "projected_value_usd": round(proj, 2),
                    "reaches_target": proj >= target_usd,
                })
        except Exception:
            scenarios = []

    return {
        "screen": "goal",
        "goal": {
            "id": goal_id,
            "label": g.get("label") or g.get("name"),
            "target_usd": round(target_usd, 2),
            "target_date": str(target_date_iso)[:10] if target_date_iso else None,
            "monthly_contribution": round(monthly_contribution, 2),
            "expected_return_pct": round(expected_return_pct, 2),
        },
        "progress": {
            "current_capital_usd": round(current_capital_usd, 2),
            "gap_usd": round(gap_usd, 2),
            "progress_pct": round(progress_pct, 2) if progress_pct is not None else None,
            "months_left": months_left,
        },
        "scenarios": scenarios,
        "diagnostic": {
            "status": diagnostic.get("status"),
            "eta_months": diagnostic.get("eta_months_at_current_rate"),
            "required_return_pct": diagnostic.get("required_annual_pct"),
            "delta_pct_required": diagnostic.get("delta_pct_required"),
            "projected_value_usd": diagnostic.get("projected_value_at_target_date"),
            "diagnostic_text": diagnostic.get("diagnostic"),
            "behavioral_suggestion": diagnostic.get("suggestion"),
            "user_cagr_pct": user_cagr_pct,
        },
    }
