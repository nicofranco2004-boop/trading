"""goals_diagnostic — proyección y sugerencias para una meta.
═════════════════════════════════════════════════════════════════════════════
Sprint 7. Cruza:
- Velocidad real del usuario (CAGR histórico)
- Velocidad necesaria (requerida para llegar al target en la fecha)
- Sesgo dominante (del behavioral) → sugerencia accionable

Output:
  {
    status: 'on_track' | 'behind' | 'ahead' | 'unreachable',
    projected_value_at_target_date: float,
    eta_months_at_current_rate: int | None,
    delta_pct_required: float | None,  # diferencia entre lo necesario y lo real
    diagnostic: str,                   # mensaje plain-text
    suggestion: { code, title, action } | None,
  }
"""

from __future__ import annotations
from typing import Dict, List, Optional
from datetime import datetime


# ── Suggestions: mapeo sesgo → acción concreta para acercarse a la meta ───

SUGGESTION_MAP = {
    'overtrade': {
        'code': 'overtrade',
        'title': 'Operás demasiado',
        'action': 'Cada operación restá comisiones y spread. Reducí frecuencia y vas a ver más capital trabajando para tu meta.',
    },
    'disposition_effect': {
        'code': 'disposition_effect',
        'title': 'Vendés ganadoras muy rápido',
        'action': 'Tus ganadoras tienen menos tiempo de capitalizar. Definí un criterio de salida basado en tesis, no en miedo.',
    },
    'loss_aversion': {
        'code': 'loss_aversion',
        'title': 'Mantenés perdedoras demasiado tiempo',
        'action': 'El capital trabado en perdedoras no compone. Revisá tu stop-loss antes de entrar.',
    },
    'averaging_down': {
        'code': 'averaging_down',
        'title': 'Promediás a la baja',
        'action': 'Promediar refuerza posiciones que ya te están mostrando una tesis equivocada. Cortá antes de duplicar.',
    },
    'concentration': {
        'code': 'concentration',
        'title': 'Cartera muy concentrada',
        'action': 'Una sola posición puede definir si llegás a la meta. Diversificá entre 8-15 activos.',
    },
    'cash_drag': {
        'code': 'cash_drag',
        'title': 'Demasiado cash sin invertir',
        'action': 'El cash en ARS pierde por inflación; en USD no compone. Decidí destinos para tus reservas.',
    },
    'inflation_loss': {
        'code': 'inflation_loss',
        'title': 'Pérdida por inflación',
        'action': 'Tu cash ARS pierde poder adquisitivo. Convertí o invertí en CER/MEP para preservar valor.',
    },
    'home_bias': {
        'code': 'home_bias',
        'title': 'Sesgo a activos locales',
        'action': 'Demasiada exposición a un país amplifica volatilidad. Considerá diversificar geográficamente.',
    },
    'recency_bias': {
        'code': 'recency_bias',
        'title': 'Compraste arriba',
        'action': 'Entrar en máximos suele preceder un drawdown. Esperá retrocesos o promediá en el tiempo.',
    },
    'sector_concentration': {
        'code': 'sector_concentration',
        'title': 'Concentración sectorial',
        'action': 'Demasiada exposición a un sector. Si ese sector cae, tu meta se aleja.',
    },
    'winrate_payoff': {
        'code': 'winrate_payoff',
        'title': 'Expectancy negativa',
        'action': 'Tus losers superan a tus winners en magnitud. Mejorá los stops o reducí tamaño de posición.',
    },
}


def _months_between(target_date_str: str, now: Optional[datetime] = None) -> Optional[int]:
    """Calcula meses entre hoy y la fecha objetivo. Si la fecha es inválida → None."""
    try:
        td = datetime.strptime(target_date_str, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
    n = now or datetime.utcnow()
    months = (td.year - n.year) * 12 + (td.month - n.month)
    return max(0, months)


def _required_monthly_rate(current_value: float, target_value: float, months: int) -> Optional[float]:
    """Tasa mensual compuesta requerida para ir de current → target en `months` meses,
    SIN aportes. Devuelve fracción mensual (0.01 = 1%/mes). None si imposible."""
    if months <= 0 or current_value <= 0 or target_value <= 0:
        return None
    return (target_value / current_value) ** (1 / months) - 1


def _eta_months(current_value: float, target_value: float, monthly_rate: float) -> Optional[int]:
    """En cuántos meses, al rate actual, llegás al target. None si nunca."""
    if current_value <= 0 or target_value <= 0 or monthly_rate <= 0:
        return None
    if current_value >= target_value:
        return 0
    import math
    n = math.log(target_value / current_value) / math.log(1 + monthly_rate)
    if n > 600:  # más de 50 años → tratamos como "unreachable"
        return None
    return int(math.ceil(n))


def _project_value(current_value: float, monthly_rate: float, months: int) -> float:
    """Valor proyectado a `months` con rate compuesto mensual y sin aportes."""
    if monthly_rate is None or current_value <= 0:
        return current_value
    return current_value * ((1 + monthly_rate) ** months)


def _pick_dominant_bias(behavioral_cards: Optional[List[dict]]) -> Optional[dict]:
    """Selecciona el sesgo dominante (high > medium > low) del que tengamos
    suggestion. None si no hay nada accionable."""
    if not behavioral_cards:
        return None
    rank = {'high': 4, 'medium': 3, 'low': 2}
    candidates = []
    for c in behavioral_cards:
        if c.get('insufficient_data'):
            continue
        sev = c.get('severity')
        if sev not in rank:
            continue
        code = c.get('code')
        if code not in SUGGESTION_MAP:
            continue
        candidates.append((rank[sev], c))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def build_goal_diagnostic(
    goal: dict,
    current_value: float,
    user_cagr_pct: Optional[float],  # como porcentaje, no fracción (ej 12.5 = 12.5%)
    behavioral_cards: Optional[List[dict]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Construye el diagnóstico de un goal específico."""
    target = float(goal.get('target_usd') or 0)
    target_date = goal.get('target_date') or ''
    months_left = _months_between(target_date, now)

    if months_left is None:
        return {
            'status': 'unknown',
            'projected_value_at_target_date': current_value,
            'eta_months_at_current_rate': None,
            'delta_pct_required': None,
            'diagnostic': 'Fecha objetivo inválida o sin definir.',
            'suggestion': None,
        }

    # Caso ya alcanzado
    if current_value >= target:
        return {
            'status': 'ahead',
            'projected_value_at_target_date': current_value,
            'eta_months_at_current_rate': 0,
            'delta_pct_required': None,
            'diagnostic': '¡Meta alcanzada!',
            'suggestion': None,
        }

    # Datos insuficientes de verdad: sin valor actual o sin target.
    # (Se chequea ANTES del caso "fecha vencida" para no marcar 'behind' sin datos.)
    if current_value <= 0 or target <= 0:
        return {
            'status': 'unreachable',
            'projected_value_at_target_date': current_value,
            'eta_months_at_current_rate': None,
            'delta_pct_required': None,
            'months_left': months_left,
            'diagnostic': 'Datos insuficientes para proyectar. Cargá tu valor actual y reintenta.',
            'suggestion': None,
        }

    # Fecha objetivo ya llegó/pasó y todavía estás por debajo del target.
    # No faltan datos: simplemente venció la fecha → status 'behind' con mensaje claro.
    if months_left <= 0:
        falta = target - current_value
        diag = f'La fecha objetivo ya llegó y todavía estás a US$ {falta:,.0f} de la meta de US$ {target:,.0f}.'
        bias = _pick_dominant_bias(behavioral_cards)
        suggestion = None
        if bias and bias.get('code') in SUGGESTION_MAP:
            suggestion = dict(SUGGESTION_MAP[bias['code']])
            suggestion['evidence'] = bias.get('one_liner') or bias.get('title') or ''
        return {
            'status': 'behind',
            'projected_value_at_target_date': current_value,
            'eta_months_at_current_rate': None,
            'delta_pct_required': None,
            'months_left': months_left,
            'diagnostic': diag,
            'suggestion': suggestion,
        }

    # Tasa requerida vs real
    required_monthly = _required_monthly_rate(current_value, target, months_left)
    user_cagr_frac = (user_cagr_pct or 0) / 100
    user_monthly = (1 + user_cagr_frac) ** (1 / 12) - 1 if user_cagr_frac > -1 else 0

    # Proyectar valor al ritmo actual del usuario
    projected = _project_value(current_value, user_monthly, months_left)
    eta = _eta_months(current_value, target, user_monthly)

    # Determinar status
    if required_monthly is None:
        status = 'unreachable'
    elif user_monthly >= required_monthly * 0.95:
        status = 'on_track' if user_monthly <= required_monthly * 1.10 else 'ahead'
    elif user_monthly > 0:
        status = 'behind'
    else:
        status = 'behind'

    # Diagnóstico textual
    if status == 'on_track':
        diag = f'Vas muy cerca del ritmo necesario: proyección US$ {projected:,.0f} vs meta US$ {target:,.0f} en {months_left} meses.'
    elif status == 'ahead':
        eta_str = f'{eta}' if eta is not None else '?'
        diag = f'Vas por encima del ritmo necesario. Proyección: US$ {projected:,.0f} en {months_left} meses (vs meta US$ {target:,.0f}).'
        if eta is not None and eta < months_left:
            diag += f' Llegarías {months_left - eta} meses antes.'
    elif status == 'unreachable':
        diag = 'Datos insuficientes para proyectar. Cargá tu valor actual y reintenta.'
    else:  # behind
        if eta is not None:
            extra = eta - months_left
            diag = f'A este ritmo llegás en ~{eta} meses ({extra} más que tu objetivo). Necesitás acelerar o aumentar aportes.'
        else:
            diag = 'Al ritmo actual, no llegás a la meta sin aportes adicionales.'

    delta_pp = None
    if required_monthly is not None:
        delta_pp = (required_monthly - user_monthly) * 12 * 100  # diferencia anualizada en pp

    # Sugerencia (sólo si está behind / unreachable — no abrumamos al user que va bien)
    suggestion = None
    if status in ('behind', 'unreachable'):
        bias = _pick_dominant_bias(behavioral_cards)
        if bias and bias.get('code') in SUGGESTION_MAP:
            suggestion = dict(SUGGESTION_MAP[bias['code']])
            suggestion['evidence'] = bias.get('one_liner') or bias.get('title') or ''

    return {
        'status': status,
        'projected_value_at_target_date': round(projected, 2),
        'eta_months_at_current_rate': eta,
        'delta_pct_required': round(delta_pp, 2) if delta_pp is not None else None,
        'months_left': months_left,
        'required_annual_pct': round(((1 + required_monthly) ** 12 - 1) * 100, 2) if required_monthly is not None else None,
        'diagnostic': diag,
        'suggestion': suggestion,
    }
