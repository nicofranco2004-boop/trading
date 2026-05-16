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

    # Diagnostic via endpoint logic — reusamos si está
    diagnostic: Dict[str, Any] = {}
    try:
        from goals.diagnostic import build_diagnostic
        diagnostic = build_diagnostic(conn, user_id, goal_id) or {}
    except Exception:
        diagnostic = {}

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
        "diagnostic": {
            "status": diagnostic.get("status"),
            "eta_months": diagnostic.get("eta_months"),
            "behavioral_suggestion": diagnostic.get("behavioral_suggestion"),
            "required_return_pct": diagnostic.get("required_return_pct"),
            "scenarios": diagnostic.get("scenarios", []),
        },
    }
