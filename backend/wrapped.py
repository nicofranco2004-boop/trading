"""wrapped — reseña anual del usuario.
═════════════════════════════════════════════════════════════════════════════
Sprint 6. Esto es la versión "Spotify Wrapped" de Rendi:
una secuencia de highlights del año (rendimiento, mejor/peor mes,
mejor trade, sesgo dominante, vs benchmark, vs inflación).

El frontend después arma un carrusel de slides y deja exportar cada uno
como PNG con shareCard.js.

Diseño:
- Función pura `build_wrapped(year, monthly, operations, behavioral, ...)`.
- Sin dependencias del módulo `behavioral` ni de la DB — recibe todo.
- Devuelve dict con shape estable, slides ordenados por orden de presentación.

Cada slide tiene:
  - code: identificador estable
  - kind: 'intro' | 'pnl' | 'best_month' | 'worst_month' | 'best_trade' |
          'vs_benchmark' | 'vs_inflation' | 'dominant_bias' | 'stats' | 'outro'
  - title: headline corto
  - subtitle: contexto
  - metric: { value, label } (lo que va grande)
  - stats: [{ label, value }] adicional
  - tone: 'positive' | 'negative' | 'neutral'
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from collections import Counter


# ── Helpers de cálculo ───────────────────────────────────────────────────────

MONTHS_ES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]


def _monthly_for_year(monthly: List[dict], year: int, broker: str = 'global') -> List[dict]:
    """Filtra entries del año en cuestión, broker dado, ordenadas."""
    rows = [
        m for m in monthly
        if m.get('year') == year and (m.get('broker') or 'global') == broker
    ]
    return sorted(rows, key=lambda m: m.get('month') or 0)


def _twr_for_period(rows: List[dict]) -> Optional[float]:
    """Time-weighted return geométrico para una serie de meses."""
    if not rows:
        return None
    prod = 1.0
    valid = 0
    for r in rows:
        ci = r.get('capital_inicio') or 0
        cf = r.get('capital_final') or 0
        net = (r.get('deposits') or 0) - (r.get('withdrawals') or 0)
        if ci <= 0:
            continue
        ret = (cf - ci - net) / ci
        # Clamp para evitar outliers locos arruinar el geom mean
        ret = max(-0.95, min(5.0, ret))
        prod *= (1 + ret)
        valid += 1
    if valid == 0:
        return None
    return prod - 1


def _operations_for_year(operations: List[dict], year: int) -> List[dict]:
    """Operaciones cerradas del año."""
    out = []
    for op in operations:
        date = str(op.get('date') or '')
        if len(date) >= 4 and date[:4].isdigit() and int(date[:4]) == year:
            out.append(op)
    return out


# ── Slide builders ──────────────────────────────────────────────────────────

def _slide_intro(year: int, teaser: Optional[dict] = None) -> dict:
    """Intro hero. Si hay `teaser`, mostramos un mini-resumen del año para
    que no quede vacío. Teaser shape:
      { twr, pnl_usd, total_trades, months_count, best_month_label }
    """
    stats = []
    if teaser:
        twr = teaser.get('twr')
        if twr is not None:
            sign = '+' if twr >= 0 else '−'
            stats.append({'label': 'Rendimiento', 'value': f'{sign}{abs(twr) * 100:.2f}%'})
        pnl_usd = teaser.get('pnl_usd')
        if pnl_usd is not None:
            sign = '+' if pnl_usd >= 0 else '−'
            stats.append({'label': 'P&L total', 'value': f'{sign}${abs(pnl_usd):,.0f}'})
        total_trades = teaser.get('total_trades')
        if total_trades is not None and total_trades > 0:
            stats.append({'label': 'Operaciones', 'value': str(total_trades)})
        best_month = teaser.get('best_month_label')
        if best_month:
            stats.append({'label': 'Mejor mes', 'value': str(best_month)})
        months_count = teaser.get('months_count')
        if months_count and not best_month:
            stats.append({'label': 'Meses operados', 'value': str(months_count)})

    return {
        'code': 'intro',
        'kind': 'intro',
        'title': f'Tu {year} en Rendi',
        'subtitle': 'Un repaso a tus inversiones del año.',
        'metric': {'value': str(year), 'label': 'AÑO'},
        'stats': stats,
        'tone': 'neutral',
    }


def _slide_pnl(rows: List[dict], year: int) -> dict:
    twr = _twr_for_period(rows)
    if twr is None:
        return {
            'code': 'pnl',
            'kind': 'pnl',
            'title': 'Aún no hay suficiente historial',
            'subtitle': f'Cargá tus meses de {year} para ver el rendimiento.',
            'metric': {'value': '—', 'label': 'RENDIMIENTO'},
            'stats': [],
            'tone': 'neutral',
            'insufficient_data': True,
        }
    capital_inicio = rows[0].get('capital_inicio') or 0
    capital_final = rows[-1].get('capital_final') or 0
    pnl_usd = sum((r.get('pnl_realized') or 0) + (r.get('pnl_unrealized') or 0) for r in rows)
    sign = '+' if twr >= 0 else '−'
    return {
        'code': 'pnl',
        'kind': 'pnl',
        'title': f'{sign}{abs(twr) * 100:.2f}%',
        'subtitle': f'Tu rendimiento TWR de {year}',
        'metric': {'value': f'{sign}${abs(pnl_usd):,.0f}', 'label': 'P&L TOTAL'},
        'stats': [
            {'label': 'Capital inicio', 'value': f'${capital_inicio:,.0f}'},
            {'label': 'Capital final', 'value': f'${capital_final:,.0f}'},
            {'label': 'Meses operados', 'value': str(len(rows))},
        ],
        'tone': 'positive' if twr >= 0 else 'negative',
    }


def _slide_best_month(rows: List[dict]) -> Optional[dict]:
    candidates = []
    for r in rows:
        ci = r.get('capital_inicio') or 0
        if ci <= 0:
            continue
        ret = ((r.get('pnl_realized') or 0) + (r.get('pnl_unrealized') or 0)) / ci
        candidates.append((ret, r))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    ret, row = candidates[0]
    month_name = MONTHS_ES[(row.get('month') or 1) - 1].capitalize()
    sign = '+' if ret >= 0 else '−'
    return {
        'code': 'best_month',
        'kind': 'best_month',
        'title': f'{month_name} fue tu mejor mes',
        'subtitle': f'{sign}{abs(ret) * 100:.2f}% — ${row.get("capital_inicio", 0):,.0f} → ${row.get("capital_final", 0):,.0f}',
        'metric': {'value': f'{sign}{abs(ret) * 100:.2f}%', 'label': f'{month_name.upper()}'},
        'stats': [],
        'tone': 'positive' if ret >= 0 else 'negative',
    }


def _slide_worst_month(rows: List[dict]) -> Optional[dict]:
    candidates = []
    for r in rows:
        ci = r.get('capital_inicio') or 0
        if ci <= 0:
            continue
        ret = ((r.get('pnl_realized') or 0) + (r.get('pnl_unrealized') or 0)) / ci
        candidates.append((ret, r))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    ret, row = candidates[0]
    if ret >= 0:
        # No hay mes en negativo — skip
        return None
    month_name = MONTHS_ES[(row.get('month') or 1) - 1].capitalize()
    return {
        'code': 'worst_month',
        'kind': 'worst_month',
        'title': f'{month_name} fue el más duro',
        'subtitle': f'−{abs(ret) * 100:.2f}% — todos tenemos meses así.',
        'metric': {'value': f'−{abs(ret) * 100:.2f}%', 'label': f'{month_name.upper()}'},
        'stats': [],
        'tone': 'negative',
    }


def _slide_best_trade(ops: List[dict]) -> Optional[dict]:
    closed = [o for o in ops if (o.get('exit_price') or o.get('pnl_usd'))]
    if not closed:
        return None
    closed_sorted = sorted(closed, key=lambda o: o.get('pnl_usd') or 0, reverse=True)
    best = closed_sorted[0]
    pnl_usd = best.get('pnl_usd') or 0
    pnl_pct = best.get('pnl_pct')
    asset = best.get('asset') or '—'
    if pnl_usd <= 0:
        return None
    pct_str = ''
    if pnl_pct is not None:
        # pnl_pct viene como número (no fracción): 18.2 = 18.2%
        pct_str = f' ({"+" if pnl_pct >= 0 else "−"}{abs(pnl_pct):.1f}%)'
    return {
        'code': 'best_trade',
        'kind': 'best_trade',
        'title': f'{asset} fue tu mejor trade',
        'subtitle': f'+${pnl_usd:,.0f}{pct_str}',
        'metric': {'value': f'+${pnl_usd:,.0f}', 'label': asset.upper()},
        'stats': [
            {'label': 'Activo', 'value': asset},
            {'label': 'Fecha', 'value': str(best.get('date') or '—')},
        ],
        'tone': 'positive',
    }


def _slide_activity(ops: List[dict]) -> Optional[dict]:
    if not ops:
        return None
    asset_counts = Counter()
    for op in ops:
        a = op.get('asset')
        if a:
            asset_counts[a] += 1
    most_traded = asset_counts.most_common(3)
    total = len(ops)
    # Stats: top 3 activos operados como filas separadas
    stats = []
    for asset, count in most_traded:
        stats.append({'label': asset, 'value': f'{count}×'})
    stats.append({'label': 'Distintos activos', 'value': str(len(asset_counts))})
    top_label = most_traded[0][0] if most_traded else '—'
    return {
        'code': 'activity',
        'kind': 'stats',
        'title': f'{total} operaciones cerradas',
        'subtitle': f'Tu activo más operado fue {top_label}.',
        'metric': {'value': str(total), 'label': 'TRADES'},
        'stats': stats,
        'tone': 'neutral',
        'bars': [  # data extra para gráfico de barras horizontal
            {'label': asset, 'value': count} for asset, count in most_traded
        ],
    }


def _slide_dominant_bias(behavioral_cards: List[dict]) -> Optional[dict]:
    """Sesgo dominante = el de mayor severidad detectado. Si todos están sanos
    o sin datos, devuelve None (skipped por el caller)."""
    if not behavioral_cards:
        return None
    # Orden: high > medium > low > positive > neutral
    rank = {'high': 4, 'medium': 3, 'low': 2, 'positive': 1, 'neutral': 0}
    flagged = [c for c in behavioral_cards if not c.get('insufficient_data')]
    if not flagged:
        return None
    flagged.sort(key=lambda c: rank.get(c.get('severity') or 'neutral', 0), reverse=True)
    top = flagged[0]
    sev = top.get('severity') or 'neutral'
    if sev in ('neutral', 'positive'):
        # No hay sesgo a destacar — devolver positivo si hay algún 'positive'
        positives = [c for c in flagged if c.get('severity') == 'positive']
        if positives:
            p = positives[0]
            return {
                'code': 'dominant_bias',
                'kind': 'dominant_bias',
                'title': 'Operaste con cabeza',
                'subtitle': p.get('title') or p.get('one_liner') or '',
                'metric': {'value': '✓', 'label': 'PATRÓN SANO'},
                'stats': [{'label': 'Detector', 'value': p.get('code') or ''}],
                'tone': 'positive',
            }
        return None
    return {
        'code': 'dominant_bias',
        'kind': 'dominant_bias',
        'title': top.get('title') or 'Tu sesgo dominante',
        'subtitle': top.get('one_liner') or '',
        'metric': {'value': sev.upper(), 'label': 'SEVERIDAD'},
        'stats': [
            {'label': 'Tipo', 'value': top.get('code') or ''},
            {'label': 'Indicador', 'value': str(top.get('value_label') or '—')},
        ],
        'tone': 'negative' if sev in ('high', 'medium') else 'neutral',
    }


def _slide_vs_benchmark(twr_user: Optional[float], benchmarks: Optional[dict], year: int) -> Optional[dict]:
    """Compara tu TWR vs S&P 500 y vs MERVAL (en USD) del año.
    Espera benchmarks como dict {'sp500_ytd': 0.12, 'merval_ytd': 0.05}.
    Si no hay datos, retorna None."""
    if twr_user is None or not benchmarks:
        return None
    sp500 = benchmarks.get('sp500_ytd')
    merval = benchmarks.get('merval_ytd')
    if sp500 is None and merval is None:
        return None
    stats = []
    deltas = []
    if sp500 is not None:
        delta = twr_user - sp500
        deltas.append(delta)
        sign = '+' if delta >= 0 else '−'
        stats.append({
            'label': 'vs S&P 500',
            'value': f'{sign}{abs(delta) * 100:.2f}pp',
        })
    if merval is not None:
        delta = twr_user - merval
        deltas.append(delta)
        sign = '+' if delta >= 0 else '−'
        stats.append({
            'label': 'vs MERVAL',
            'value': f'{sign}{abs(delta) * 100:.2f}pp',
        })
    avg_delta = sum(deltas) / len(deltas) if deltas else 0
    if avg_delta >= 0:
        title = 'Le ganaste a los índices'
        subtitle = f'Tu rendimiento estuvo por encima del promedio de benchmarks ({year}).'
        tone = 'positive'
    else:
        title = 'Los índices te ganaron'
        subtitle = f'Tu rendimiento estuvo por debajo del promedio de benchmarks ({year}).'
        tone = 'negative'
    # Bars: tu rendimiento vs benchmarks. value = fracción (0.12 = 12%)
    bars = [{'label': 'Tu cartera', 'value': twr_user, 'highlight': True}]
    if sp500 is not None:
        bars.append({'label': 'S&P 500', 'value': sp500})
    if merval is not None:
        bars.append({'label': 'MERVAL', 'value': merval})
    return {
        'code': 'vs_benchmark',
        'kind': 'vs_benchmark',
        'title': title,
        'subtitle': subtitle,
        'metric': {
            'value': f'{"+" if twr_user >= 0 else "−"}{abs(twr_user) * 100:.2f}%',
            'label': 'TU RENDIMIENTO',
        },
        'stats': stats,
        'tone': tone,
        'bars': bars,
    }


def _slide_vs_inflation(twr_user: Optional[float], inflation_ytd: Optional[float], year: int) -> Optional[dict]:
    """Sólo aplica cuando hay inflación AR del año disponible. La idea: aún
    rindiendo positivo en USD, el dato cultural es 'le ganaste a la inflación
    en ARS'. Lo dejamos opcional."""
    if twr_user is None or inflation_ytd is None:
        return None
    delta = twr_user - inflation_ytd
    sign = '+' if delta >= 0 else '−'
    bars = [
        {'label': 'Tu cartera', 'value': twr_user, 'highlight': True},
        {'label': f'Inflación AR {year}', 'value': inflation_ytd},
    ]
    if delta >= 0:
        return {
            'code': 'vs_inflation',
            'kind': 'vs_inflation',
            'title': 'Le ganaste a la inflación AR',
            'subtitle': f'Tu rendimiento estuvo {sign}{abs(delta) * 100:.2f}pp por encima de la inflación de {year}.',
            'metric': {'value': f'{sign}{abs(delta) * 100:.2f}pp', 'label': 'VS INFLACIÓN AR'},
            'stats': [
                {'label': 'Tu rendimiento', 'value': f'{"+" if twr_user >= 0 else "−"}{abs(twr_user) * 100:.2f}%'},
                {'label': f'Inflación {year}', 'value': f'{inflation_ytd * 100:.2f}%'},
            ],
            'tone': 'positive',
            'bars': bars,
        }
    return {
        'code': 'vs_inflation',
        'kind': 'vs_inflation',
        'title': 'La inflación te ganó',
        'subtitle': f'Tu rendimiento quedó {abs(delta) * 100:.2f}pp por debajo de la inflación AR.',
        'metric': {'value': f'−{abs(delta) * 100:.2f}pp', 'label': 'VS INFLACIÓN AR'},
        'stats': [
            {'label': 'Tu rendimiento', 'value': f'{"+" if twr_user >= 0 else "−"}{abs(twr_user) * 100:.2f}%'},
            {'label': f'Inflación {year}', 'value': f'{inflation_ytd * 100:.2f}%'},
        ],
        'tone': 'negative',
        'bars': bars,
    }


def _slide_outro(year: int) -> dict:
    return {
        'code': 'outro',
        'kind': 'outro',
        'title': f'Gracias por usar Rendi en {year}',
        'subtitle': 'Compartí tu Wrapped y ayudanos a hacer crecer la comunidad de inversores Latam.',
        'metric': {'value': 'RENDI', 'label': 'COMPARTILO'},
        'stats': [],
        'tone': 'neutral',
    }


# ── Builder principal ──────────────────────────────────────────────────────

def build_wrapped(
    year: int,
    monthly: List[dict],
    operations: List[dict],
    behavioral_cards: Optional[List[dict]] = None,
    benchmarks: Optional[dict] = None,
    inflation_ytd: Optional[float] = None,
) -> dict:
    """Orquesta los slides. Retorna {year, slides: [...], summary: {...}}.

    Slides en orden de presentación. Aquellos sin datos se filtran (excepto
    el intro/outro y pnl, que siempre van). Si no hay monthly para el año,
    devuelve un wrapped 'vacío' con un solo slide informando que falta data.
    """
    rows = _monthly_for_year(monthly, year)
    ops = _operations_for_year(operations or [], year)
    twr = _twr_for_period(rows)

    # Computar teaser para el intro
    pnl_usd_total = None
    best_month_label = None
    if rows:
        pnl_usd_total = sum(
            (r.get('pnl_realized') or 0) + (r.get('pnl_unrealized') or 0)
            for r in rows
        )
        # Best month label (mismo cálculo que el slide best_month)
        best_candidates = []
        for r in rows:
            ci = r.get('capital_inicio') or 0
            if ci <= 0:
                continue
            ret = ((r.get('pnl_realized') or 0) + (r.get('pnl_unrealized') or 0)) / ci
            best_candidates.append((ret, r))
        if best_candidates:
            best_candidates.sort(key=lambda t: t[0], reverse=True)
            best_row = best_candidates[0][1]
            month_idx = (best_row.get('month') or 1) - 1
            if 0 <= month_idx < 12:
                best_month_label = MONTHS_ES[month_idx].capitalize()

    teaser = {
        'twr': twr,
        'pnl_usd': pnl_usd_total,
        'total_trades': len(ops) if ops else None,
        'months_count': len(rows) if rows else None,
        'best_month_label': best_month_label,
    }

    slides: List[dict] = []
    slides.append(_slide_intro(year, teaser=teaser))
    slides.append(_slide_pnl(rows, year))

    # Si no hay data del año, terminamos acá con un mensaje claro
    if not rows:
        slides.append({
            'code': 'no_data',
            'kind': 'stats',
            'title': f'No tenemos datos de {year}',
            'subtitle': 'Cargá tu Resumen Mensual para ver tu Wrapped el próximo año.',
            'metric': {'value': '0', 'label': 'MESES'},
            'stats': [],
            'tone': 'neutral',
        })
        return {'year': year, 'slides': slides, 'summary': {'has_data': False}}

    best_month = _slide_best_month(rows)
    if best_month:
        slides.append(best_month)

    worst_month = _slide_worst_month(rows)
    if worst_month:
        slides.append(worst_month)

    best_trade = _slide_best_trade(ops)
    if best_trade:
        slides.append(best_trade)

    activity = _slide_activity(ops)
    if activity:
        slides.append(activity)

    vs_bm = _slide_vs_benchmark(twr, benchmarks, year)
    if vs_bm:
        slides.append(vs_bm)

    vs_inf = _slide_vs_inflation(twr, inflation_ytd, year)
    if vs_inf:
        slides.append(vs_inf)

    bias = _slide_dominant_bias(behavioral_cards or [])
    if bias:
        slides.append(bias)

    slides.append(_slide_outro(year))

    return {
        'year': year,
        'slides': slides,
        'summary': {
            'has_data': True,
            'twr': twr,
            'months_count': len(rows),
            'operations_count': len(ops),
            'slide_count': len(slides),
        },
    }
