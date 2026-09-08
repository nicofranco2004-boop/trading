"""Tests para backend/wrapped.py (Sprint 6 — Wrapped anual)."""
from __future__ import annotations
import pytest
from wrapped import (
    build_wrapped,
    _monthly_for_year,
    _twr_for_period,
    _operations_for_year,
    _slide_intro,
    _slide_pnl,
    _slide_best_month,
    _slide_worst_month,
    _slide_best_trade,
    _slide_activity,
    _slide_dominant_bias,
    _slide_vs_benchmark,
    _slide_vs_inflation,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def make_monthly(year, month, ci=10000, cf=10500, dep=0, wd=0, pnl_r=500, pnl_u=0, broker='global'):
    return {
        'year': year,
        'month': month,
        'broker': broker,
        'capital_inicio': ci,
        'capital_final': cf,
        'deposits': dep,
        'withdrawals': wd,
        'pnl_realized': pnl_r,
        'pnl_unrealized': pnl_u,
    }


def make_op(date, asset, pnl_usd=100, pnl_pct=5, exit_price=110):
    return {
        'date': date,
        'asset': asset,
        'pnl_usd': pnl_usd,
        'pnl_pct': pnl_pct,
        'entry_price': 100,
        'exit_price': exit_price,
        'quantity': 1,
    }


# ── Helpers de filtrado ───────────────────────────────────────────────────

def test_monthly_for_year_filters_correctly():
    data = [
        make_monthly(2025, 12),
        make_monthly(2026, 1),
        make_monthly(2026, 3),
        make_monthly(2027, 1),
    ]
    rows = _monthly_for_year(data, 2026)
    assert len(rows) == 2
    assert all(r['year'] == 2026 for r in rows)


def test_monthly_for_year_sorts_by_month():
    data = [
        make_monthly(2026, 5),
        make_monthly(2026, 1),
        make_monthly(2026, 3),
    ]
    rows = _monthly_for_year(data, 2026)
    assert [r['month'] for r in rows] == [1, 3, 5]


def test_monthly_for_year_default_broker_global():
    data = [
        make_monthly(2026, 1, broker='global'),
        make_monthly(2026, 1, broker='Cocos'),
    ]
    rows = _monthly_for_year(data, 2026)
    assert len(rows) == 1
    assert rows[0]['broker'] == 'global'


def test_operations_for_year_strips_other_years():
    data = [
        make_op('2025-12-15', 'AAPL'),
        make_op('2026-01-15', 'TSLA'),
        make_op('2026-06-20', 'MSFT'),
        make_op('2027-01-10', 'NVDA'),
    ]
    ops = _operations_for_year(data, 2026)
    assert len(ops) == 2
    assert {o['asset'] for o in ops} == {'TSLA', 'MSFT'}


# ── TWR ────────────────────────────────────────────────────────────────────

def test_twr_geometric_compounding():
    rows = [
        make_monthly(2026, 1, ci=10000, cf=10500, pnl_r=500),   # +5%
        make_monthly(2026, 2, ci=10500, cf=11025, pnl_r=525),   # +5%
    ]
    twr = _twr_for_period(rows)
    # (1.05 * 1.05) - 1 = 0.1025
    assert twr == pytest.approx(0.1025, abs=1e-4)


def test_twr_excludes_capital_zero():
    rows = [
        make_monthly(2026, 1, ci=0, cf=0, pnl_r=0),
        make_monthly(2026, 2, ci=10000, cf=11000, pnl_r=1000),
    ]
    twr = _twr_for_period(rows)
    assert twr == pytest.approx(0.10, abs=1e-4)


def test_twr_neutralizes_deposits():
    # Mes con depósito grande no debe inflar el rendimiento.
    #
    # ⚠️ EL VALOR CAMBIÓ, LA INTENCIÓN NO. El test afirmaba +5,00% = 500/10.000,
    # o sea el denominador VIEJO (`capital_inicio` a secas). El aporte entró a
    # mitad del mes: el denominador de Modified Dietz es 10.000 + 0,5·1.000 =
    # 10.500 y el retorno es 500/10.500 = +4,7619%. Lo que el test venía a fijar
    # —que el depósito no se lea como ganancia (+15%)— sigue fijado.
    rows = [
        make_monthly(2026, 1, ci=10000, cf=11500, dep=1000, pnl_r=500),
    ]
    twr = _twr_for_period(rows)
    assert twr == pytest.approx(500 / 10500, abs=1e-6)
    assert twr < 0.05        # y menos que el número viejo, no más


def test_twr_usa_el_primitivo_canonico_y_no_su_propia_cuenta():
    """El caso del audit, con los números medidos.

    ci=1000, cf=2100, dep=1000. Dividiendo por `capital_inicio` el slide decía
    +10,00%; el motor mide +6,67%. Compuesto a doce meses eso es +213,8% contra
    +115,7% — y el slide sale de la app como PNG.
    """
    import twr as _twr
    rows = [make_monthly(2026, 1, ci=1000, cf=2100, dep=1000, pnl_r=100)]
    ret = _twr_for_period(rows)
    assert ret == pytest.approx(0.0667, abs=1e-4)
    assert ret == pytest.approx(_twr.dietz(1000, 2100, 1000), abs=1e-12)
    # El número viejo, para que quede escrito de qué se está saliendo.
    assert ret != pytest.approx(0.10, abs=1e-4)
    # Y a doce meses, la brecha compuesta: el mismo mes doce veces da +116,9%
    # con el primitivo y +213,8% con el denominador viejo (1,10**12 - 1). El
    # informe redondea el mensual a 6,67% y publica +115,7%; acá se compone el
    # valor exacto, que es lo que hace el código.
    doce = [make_monthly(2026, m, ci=1000, cf=2100, dep=1000) for m in range(1, 13)]
    assert _twr_for_period(doce) == pytest.approx((1 + 100 / 1500) ** 12 - 1, abs=1e-9)
    assert _twr_for_period(doce) == pytest.approx(1.1694, abs=1e-3)
    assert (1 + 100 / 1000) ** 12 - 1 == pytest.approx(2.1384, abs=1e-3)   # el viejo


def test_mejor_y_peor_mes_usan_EL_MISMO_retorno_que_el_slide_de_rendimiento():
    """Antes cada slide derivaba el suyo: el de rendimiento dividía por `ci` y
    los de mejor/peor hacían `(pnl_realized + pnl_unrealized) / ci` sin restar
    los flujos. Con un depósito grande, el "mejor mes" podía ser el mes en que
    entró la plata y no el mes en que la cartera rindió."""
    import twr as _twr
    # Enero: +1.000 sobre 10.000 sin flujos           ⇒ +10,00% con las dos.
    # Febrero: +1.050 pero con un depósito de 10.000  ⇒ la quinta fórmula lo
    #   ponía en +10,50% (divide por el capital de inicio, ignora que la mitad
    #   de la plata entró a mitad de mes); el primitivo lo pone en +7,00%.
    # O sea: el mes del depósito le GANABA al mes que rindió.
    rows = [
        make_monthly(2026, 1, ci=10000, cf=11000, dep=0, pnl_r=1000, pnl_u=0),
        make_monthly(2026, 2, ci=10000, cf=21050, dep=10000, pnl_r=1050, pnl_u=0),
    ]
    assert (1050 / 10000) > (1000 / 10000)          # lo que decía la quinta fórmula
    assert _twr.dietz(10000, 21050, 10000) == pytest.approx(0.07, abs=1e-9)
    best = _slide_best_month(rows)
    assert best['metric']['label'] == 'ENERO'
    assert best['metric']['value'] == '+10.00%'


def test_un_mes_que_no_se_puede_medir_no_entra_a_ningun_slide():
    """`dietz` devuelve None cuando el denominador no da (un retiro que se lleva
    el capital). Se decide UNA vez, para los tres slides."""
    rows = [make_monthly(2026, 1, ci=1000, cf=0, dep=0, wd=3000, pnl_r=0)]
    assert _twr_for_period(rows) is None
    assert _slide_best_month(rows) is None
    assert _slide_worst_month(rows) is None


def test_twr_returns_none_if_no_valid_rows():
    assert _twr_for_period([]) is None
    assert _twr_for_period([make_monthly(2026, 1, ci=0, cf=0)]) is None


# ── Slides individuales ───────────────────────────────────────────────────

def test_slide_intro_has_correct_year():
    s = _slide_intro(2026)
    assert s['code'] == 'intro'
    assert '2026' in s['title']
    assert s['metric']['value'] == '2026'
    assert s['stats'] == []  # sin teaser → sin stats


def test_slide_intro_with_teaser_shows_summary_stats():
    teaser = {
        'twr': 0.1432,
        'pnl_usd': 4287,
        'total_trades': 14,
        'months_count': 12,
        'best_month_label': 'Marzo',
    }
    s = _slide_intro(2026, teaser=teaser)
    labels = [st['label'] for st in s['stats']]
    assert 'Rendimiento' in labels
    assert 'P&L total' in labels
    assert 'Operaciones' in labels
    assert 'Mejor mes' in labels
    # twr formato con + porque es positivo
    rendimiento = next(st for st in s['stats'] if st['label'] == 'Rendimiento')
    assert rendimiento['value'].startswith('+')
    pnl = next(st for st in s['stats'] if st['label'] == 'P&L total')
    assert pnl['value'].startswith('+$')


def test_slide_intro_with_negative_teaser_uses_minus():
    teaser = {'twr': -0.05, 'pnl_usd': -250, 'total_trades': None, 'months_count': 6, 'best_month_label': None}
    s = _slide_intro(2026, teaser=teaser)
    rendimiento = next(st for st in s['stats'] if st['label'] == 'Rendimiento')
    assert rendimiento['value'].startswith('−')
    pnl = next(st for st in s['stats'] if st['label'] == 'P&L total')
    assert pnl['value'].startswith('−$')
    # Sin best_month, cae a meses operados
    labels = [st['label'] for st in s['stats']]
    assert 'Meses operados' in labels
    assert 'Operaciones' not in labels  # total_trades None → skipped


def test_slide_pnl_positive_tone():
    rows = [make_monthly(2026, 1, ci=10000, cf=11000, pnl_r=1000)]
    s = _slide_pnl(rows, 2026)
    assert s['tone'] == 'positive'
    assert s['title'].startswith('+')
    assert '1,000' in s['metric']['value'] or '+$1,000' in s['metric']['value']


def test_slide_pnl_negative_tone():
    rows = [make_monthly(2026, 1, ci=10000, cf=9000, pnl_r=-1000)]
    s = _slide_pnl(rows, 2026)
    assert s['tone'] == 'negative'
    assert '−' in s['title']  # unicode minus


def test_slide_pnl_insufficient_data():
    s = _slide_pnl([], 2026)
    assert s.get('insufficient_data') is True
    assert s['metric']['value'] == '—'


def test_slide_best_month_picks_highest_return():
    rows = [
        make_monthly(2026, 1, ci=10000, cf=10300, pnl_r=300),  # +3%
        make_monthly(2026, 2, ci=10300, cf=11330, pnl_r=1030), # +10%
        make_monthly(2026, 3, ci=11330, cf=11200, pnl_r=-130), # -1.15%
    ]
    s = _slide_best_month(rows)
    assert s is not None
    assert 'Febrero' in s['title']
    assert s['tone'] == 'positive'


def test_slide_worst_month_only_if_negative_exists():
    # Todos positivos → no debería devolver slide
    rows = [
        make_monthly(2026, 1, ci=10000, cf=10500, pnl_r=500),
        make_monthly(2026, 2, ci=10500, cf=11000, pnl_r=500),
    ]
    assert _slide_worst_month(rows) is None


def test_slide_worst_month_picks_most_negative():
    rows = [
        make_monthly(2026, 1, ci=10000, cf=10500, pnl_r=500),
        make_monthly(2026, 2, ci=10500, cf=8500, pnl_r=-2000),
        make_monthly(2026, 3, ci=8500, cf=8000, pnl_r=-500),
    ]
    s = _slide_worst_month(rows)
    assert s is not None
    assert 'Febrero' in s['title']
    assert s['tone'] == 'negative'


def test_slide_best_trade_picks_highest_pnl():
    ops = [
        make_op('2026-01-15', 'AAPL', pnl_usd=200),
        make_op('2026-02-20', 'TSLA', pnl_usd=850),
        make_op('2026-03-10', 'MSFT', pnl_usd=400),
    ]
    s = _slide_best_trade(ops)
    assert s is not None
    assert 'TSLA' in s['title']
    assert s['tone'] == 'positive'


def test_slide_best_trade_skipped_if_no_positive():
    ops = [
        make_op('2026-01-15', 'AAPL', pnl_usd=-100),
        make_op('2026-02-20', 'TSLA', pnl_usd=-50),
    ]
    assert _slide_best_trade(ops) is None


def test_slide_activity_counts_correctly():
    ops = [
        make_op('2026-01-15', 'AAPL'),
        make_op('2026-02-20', 'AAPL'),
        make_op('2026-03-10', 'TSLA'),
    ]
    s = _slide_activity(ops)
    assert s is not None
    assert '3' in s['metric']['value']
    # El top asset es AAPL con 2× y aparece como primera stat
    assert s['stats'][0]['label'] == 'AAPL'
    assert s['stats'][0]['value'] == '2×'
    # También se expone como `bars` para gráfico
    assert s['bars'][0]['label'] == 'AAPL'
    assert s['bars'][0]['value'] == 2


# ── Dominant bias ──────────────────────────────────────────────────────────

def test_slide_dominant_bias_picks_highest_severity():
    cards = [
        {'code': 'overtrade', 'severity': 'low', 'title': 'Trades moderados', 'one_liner': '...'},
        {'code': 'disposition_effect', 'severity': 'high', 'title': 'Vendés ganadoras rápido', 'one_liner': '...'},
        {'code': 'home_bias', 'severity': 'medium', 'title': 'Cartera concentrada en AR', 'one_liner': '...'},
    ]
    s = _slide_dominant_bias(cards)
    assert s is not None
    assert 'ganadoras' in s['title']
    assert s['tone'] == 'negative'


def test_slide_dominant_bias_skips_insufficient_data():
    cards = [
        {'code': 'overtrade', 'severity': 'high', 'insufficient_data': True},
        {'code': 'home_bias', 'severity': 'low', 'title': 'OK', 'one_liner': '...'},
    ]
    s = _slide_dominant_bias(cards)
    assert s is not None
    assert 'OK' in s['title']  # el otro fue filtrado


def test_slide_dominant_bias_returns_positive_when_only_positives():
    cards = [
        {'code': 'concentration', 'severity': 'positive', 'title': 'Bien diversificado', 'one_liner': '...'},
    ]
    s = _slide_dominant_bias(cards)
    assert s is not None
    assert s['tone'] == 'positive'
    assert 'cabeza' in s['title'].lower()


def test_slide_dominant_bias_none_if_empty():
    assert _slide_dominant_bias([]) is None
    assert _slide_dominant_bias([{'insufficient_data': True}]) is None


# ── Benchmarks / inflación ─────────────────────────────────────────────────

def test_slide_vs_benchmark_positive_when_beats_avg():
    s = _slide_vs_benchmark(0.20, {'sp500_ytd': 0.10, 'merval_ytd': 0.08}, 2026)
    assert s is not None
    assert s['tone'] == 'positive'
    assert 'ganaste' in s['title'].lower()


def test_slide_vs_benchmark_negative_when_loses():
    s = _slide_vs_benchmark(0.05, {'sp500_ytd': 0.15, 'merval_ytd': 0.20}, 2026)
    assert s is not None
    assert s['tone'] == 'negative'


def test_slide_vs_benchmark_none_when_no_data():
    assert _slide_vs_benchmark(0.10, None, 2026) is None
    assert _slide_vs_benchmark(None, {'sp500_ytd': 0.05}, 2026) is None
    assert _slide_vs_benchmark(0.10, {}, 2026) is None


def test_slide_vs_inflation_positive():
    s = _slide_vs_inflation(0.30, 0.20, 2026)
    assert s is not None
    assert s['tone'] == 'positive'
    assert 'ganaste' in s['title'].lower()


def test_slide_vs_inflation_negative():
    s = _slide_vs_inflation(0.10, 0.30, 2026)
    assert s is not None
    assert s['tone'] == 'negative'


# ── Build wrapped (integration) ────────────────────────────────────────────

def test_build_wrapped_empty_year_returns_no_data_slide():
    out = build_wrapped(2026, [], [])
    assert out['year'] == 2026
    assert out['summary']['has_data'] is False
    codes = [s['code'] for s in out['slides']]
    assert 'intro' in codes
    assert 'pnl' in codes
    assert 'no_data' in codes


def test_build_wrapped_complete_year():
    monthly = [
        make_monthly(2026, i, ci=10000 + (i - 1) * 500, cf=10000 + i * 500, pnl_r=500)
        for i in range(1, 13)
    ]
    ops = [
        make_op('2026-03-10', 'AAPL', pnl_usd=400),
        make_op('2026-06-15', 'TSLA', pnl_usd=850),
        make_op('2026-09-20', 'AAPL', pnl_usd=-100),
    ]
    behavioral = [
        {'code': 'overtrade', 'severity': 'medium', 'title': 'Operás mucho', 'one_liner': '...'},
    ]
    benchmarks = {'sp500_ytd': 0.10, 'merval_ytd': 0.08}
    out = build_wrapped(2026, monthly, ops, behavioral, benchmarks, inflation_ytd=0.20)

    assert out['summary']['has_data'] is True
    codes = [s['code'] for s in out['slides']]
    assert codes[0] == 'intro'
    assert codes[-1] == 'outro'
    assert 'pnl' in codes
    assert 'best_month' in codes
    assert 'best_trade' in codes
    assert 'activity' in codes
    assert 'vs_benchmark' in codes
    assert 'vs_inflation' in codes
    assert 'dominant_bias' in codes

    # El intro ahora tiene teaser con stats del año
    intro = out['slides'][0]
    intro_labels = [st['label'] for st in intro['stats']]
    assert 'Rendimiento' in intro_labels
    assert 'P&L total' in intro_labels
    assert 'Operaciones' in intro_labels  # 3 ops del año

    # vs_benchmark trae bars para gráfico comparativo
    vs_bm = next(s for s in out['slides'] if s['code'] == 'vs_benchmark')
    assert 'bars' in vs_bm
    assert any(b.get('highlight') for b in vs_bm['bars'])
    # activity también trae bars (top 3 assets)
    act = next(s for s in out['slides'] if s['code'] == 'activity')
    assert 'bars' in act


def test_build_wrapped_skips_optional_slides_with_no_data():
    # Solo monthly, sin ops ni behavioral ni benchmarks
    monthly = [make_monthly(2026, 1, ci=10000, cf=10500, pnl_r=500)]
    out = build_wrapped(2026, monthly, [])
    codes = [s['code'] for s in out['slides']]
    assert 'best_trade' not in codes
    assert 'activity' not in codes
    assert 'vs_benchmark' not in codes
    assert 'dominant_bias' not in codes
    # Pero el intro, pnl, best_month y outro sí van
    assert 'intro' in codes
    assert 'pnl' in codes
    assert 'best_month' in codes
    assert 'outro' in codes


def test_build_wrapped_summary_counts():
    monthly = [make_monthly(2026, i) for i in range(1, 4)]
    ops = [make_op('2026-01-15', 'AAPL'), make_op('2026-02-15', 'TSLA')]
    out = build_wrapped(2026, monthly, ops)
    assert out['summary']['months_count'] == 3
    assert out['summary']['operations_count'] == 2
    assert out['summary']['slide_count'] == len(out['slides'])
    assert out['summary']['twr'] is not None
