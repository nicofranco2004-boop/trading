"""Unit tests para _build_metrics_detail — el builder PURO del array
metrics_detail (wave 2) que alimenta la vista "Comparar".

Verifica: orden y set de keys estable (20), formato value_label (x/%/—),
direction por métrica, derivaciones (decimal→%, fcf_margin), y None-safety.

conftest.py aísla la DB, así que `import main` es seguro.
"""
import main


SPEC_KEYS = [
    "pe", "pe_fwd", "pb", "ev_ebitda", "peg",
    "rev_growth_3y", "rev_growth_5y", "eps_growth_3y", "rev_growth_yoy", "earnings_yoy",
    "roe", "roa", "net_margin", "oper_margin", "gross_margin",
    "debt_equity", "current_ratio", "quick_ratio", "payout", "fcf_margin",
]


def _by_key(arr):
    return {m["key"]: m for m in arr}


def test_always_20_keys_stable_order():
    arr = main._build_metrics_detail({}, {})
    assert [m["key"] for m in arr] == SPEC_KEYS
    assert len(arr) == 20
    # cada item tiene la forma del contrato
    for m in arr:
        assert set(m.keys()) == {"key", "label", "category", "value", "value_label", "direction"}


def test_all_null_when_no_data():
    arr = main._build_metrics_detail({}, {})
    for m in arr:
        assert m["value"] is None
        assert m["value_label"] == "—"


def test_directions_match_spec():
    arr = _by_key(main._build_metrics_detail({}, {}))
    assert arr["pe"]["direction"] == "lower"
    assert arr["peg"]["direction"] == "lower"
    assert arr["debt_equity"]["direction"] == "lower"
    assert arr["payout"]["direction"] == "lower"
    assert arr["roe"]["direction"] == "higher"
    assert arr["rev_growth_yoy"]["direction"] == "higher"
    assert arr["gross_margin"]["direction"] == "higher"


def test_categories_match_spec():
    arr = _by_key(main._build_metrics_detail({}, {}))
    assert arr["pe"]["category"] == "valuation"
    assert arr["rev_growth_yoy"]["category"] == "growth"
    assert arr["roe"]["category"] == "profitability"
    assert arr["debt_equity"]["category"] == "health"


def test_from_fund_and_metrics_block_formatting():
    fund = {
        "trailing_pe": 32.88,
        "forward_pe": 28.06,
        "price_to_book": 14.59,
        "enterprise_to_ebitda": 32.07,
        "return_on_assets": 0.2230,      # decimal → 22.30%
        "operating_margins": 0.3540,     # decimal → 35.40%
        "gross_margins": 0.6296,         # decimal → 62.96%
        "current_ratio": 4.10,
        "quick_ratio": 3.80,
        "earnings_growth": 0.8280,       # decimal → 82.80%
        "free_cashflow_usd": 2_000_000.0,
        "total_revenue_usd": 10_000_000.0,  # fcf_margin = 20.00%
    }
    mb = {
        "peg_ratio": 2.17,
        "revenue_growth_pct": 38.91,
        "roe_pct": 48.49,
        "profit_margin_pct": 22.30,
        "payout_ratio_pct": 1.9,
        "debt_to_equity": 0.54,
    }
    arr = _by_key(main._build_metrics_detail(fund, mb))

    # valuation (x)
    assert arr["pe"]["value"] == 32.88 and arr["pe"]["value_label"] == "32.88x"
    assert arr["pe_fwd"]["value_label"] == "28.06x"
    assert arr["pb"]["value_label"] == "14.59x"
    assert arr["ev_ebitda"]["value_label"] == "32.07x"
    assert arr["peg"]["value_label"] == "2.17x"

    # growth / profitability (%)
    assert arr["rev_growth_yoy"]["value"] == 38.91 and arr["rev_growth_yoy"]["value_label"] == "38.91%"
    assert arr["earnings_yoy"]["value"] == 82.80 and arr["earnings_yoy"]["value_label"] == "82.80%"
    assert arr["roe"]["value"] == 48.49 and arr["roe"]["value_label"] == "48.49%"
    assert arr["roa"]["value"] == 22.30 and arr["roa"]["value_label"] == "22.30%"
    assert arr["net_margin"]["value_label"] == "22.30%"
    assert arr["oper_margin"]["value_label"] == "35.40%"
    assert arr["gross_margin"]["value_label"] == "62.96%"

    # health
    assert arr["debt_equity"]["value_label"] == "0.54x"
    assert arr["current_ratio"]["value_label"] == "4.10x"
    assert arr["quick_ratio"]["value_label"] == "3.80x"
    assert arr["payout"]["value"] == 1.9 and arr["payout"]["value_label"] == "1.90%"
    assert arr["fcf_margin"]["value"] == 20.00 and arr["fcf_margin"]["value_label"] == "20.00%"


def test_cagr_metrics_always_null():
    """3Y/5Y CAGR no se derivan de .info → siempre null (evita latencia)."""
    fund = {"trailing_pe": 10.0}
    arr = _by_key(main._build_metrics_detail(fund, {}))
    assert arr["rev_growth_3y"]["value"] is None and arr["rev_growth_3y"]["value_label"] == "—"
    assert arr["rev_growth_5y"]["value"] is None
    assert arr["eps_growth_3y"]["value"] is None


def test_fcf_margin_needs_both_and_nonzero_revenue():
    # falta revenue → None
    arr = _by_key(main._build_metrics_detail({"free_cashflow_usd": 5.0}, {}))
    assert arr["fcf_margin"]["value"] is None
    # revenue 0 → None (no division por cero)
    arr = _by_key(main._build_metrics_detail({"free_cashflow_usd": 5.0, "total_revenue_usd": 0}, {}))
    assert arr["fcf_margin"]["value"] is None
    # revenue negativo (data corrupta) → None (no margen sin sentido)
    arr = _by_key(main._build_metrics_detail({"free_cashflow_usd": 5.0, "total_revenue_usd": -1_000_000.0}, {}))
    assert arr["fcf_margin"]["value"] is None


def test_handles_nan_and_bad_types():
    fund = {
        "trailing_pe": float("nan"),
        "forward_pe": "n/a",
        "price_to_book": True,           # bool no es número válido
        "return_on_assets": float("inf"),
    }
    arr = _by_key(main._build_metrics_detail(fund, {}))
    assert arr["pe"]["value"] is None
    assert arr["pe_fwd"]["value"] is None
    assert arr["pb"]["value"] is None
    assert arr["roa"]["value"] is None


def test_none_args_do_not_crash():
    arr = main._build_metrics_detail(None, None)
    assert len(arr) == 20
    assert all(m["value"] is None for m in arr)


def test_cagr_passed_through_when_provided():
    """Si se pasa el dict cagr (del fetcher 'financials'), los 3 CAGR se llenan."""
    cagr = {"rev_growth_3y_pct": 38.91, "rev_growth_5y_pct": 25.0, "eps_growth_3y_pct": 86.40}
    arr = _by_key(main._build_metrics_detail({}, {}, cagr))
    assert arr["rev_growth_3y"]["value"] == 38.91 and arr["rev_growth_3y"]["value_label"] == "38.91%"
    assert arr["rev_growth_5y"]["value"] == 25.0
    assert arr["eps_growth_3y"]["value"] == 86.40


def test_cagr_from_series_requires_strictly_positive_series():
    """CAGR solo sobre series estrictamente positivas: base<=0, final 0, o pérdida
    intermedia (sign flip) → None (no -100% falso ni CAGR engañoso)."""
    f = main._cagr_from_series
    assert f([100.0, 200.0]) == 100.0          # caso válido
    assert f([100.0]) is None                  # < 2 puntos
    assert f([0.0, 200.0]) is None             # base 0
    assert f([-50.0, 200.0]) is None           # base negativa
    assert f([1000.0, 500.0, 0.0]) is None     # final 0 → antes daba -100%
    assert f([1000.0, 500.0, -10.0]) is None   # final negativo
    assert f([1.0, -0.5, 2.0]) is None         # pérdida intermedia (sign flip)


# ── categories_detail (wave 3) ─────────────────────────────────────────────

CAT_KEYS = ["valuation", "growth", "profitability", "health", "dividends"]


def _cats_by_key(arr):
    return {c["key"]: c for c in arr}


def _metrics_by_key(cat):
    return {m["key"]: m for m in cat["metrics"]}


def test_categories_detail_shape():
    arr = main._build_categories_detail({}, {})
    assert [c["key"] for c in arr] == CAT_KEYS
    for c in arr:
        assert set(c.keys()) == {"key", "label", "question", "score", "metrics"}
        for m in c["metrics"]:
            assert set(m.keys()) == {
                "key", "label", "value", "value_label", "direction", "status", "status_label", "info"
            }


def test_categories_detail_all_null():
    """Sin data → "—", status na, score None, sin crash."""
    arr = _cats_by_key(main._build_categories_detail({}, {}))
    for c in arr.values():
        assert c["score"] is None
        for m in c["metrics"]:
            assert m["value"] is None
            assert m["value_label"] == "—"
            assert m["status"] == "na"
            assert m["status_label"] == ""


def test_per_metric_status_valuation():
    """P/E: <=15 green, <=30 amber, else red; negativo → red."""
    cats = _cats_by_key(main._build_categories_detail(
        {"trailing_pe": 12.0, "price_to_book": 2.0, "enterprise_to_ebitda": 9.0},
        {"peg_ratio": 0.8},
    ))
    m = _metrics_by_key(cats["valuation"])
    assert m["pe"]["status"] == "green" and m["pe"]["status_label"] == "Excelente"
    assert m["pb"]["status"] == "green"
    assert m["ev_ebitda"]["status"] == "green"
    assert m["peg"]["status"] == "green"

    cats = _cats_by_key(main._build_categories_detail({"trailing_pe": 38.0}, {}))
    m = _metrics_by_key(cats["valuation"])
    assert m["pe"]["status"] == "red" and m["pe"]["status_label"] == "Muy caro"

    cats = _cats_by_key(main._build_categories_detail({"trailing_pe": 22.0}, {}))
    assert _metrics_by_key(cats["valuation"])["pe"]["status"] == "amber"

    # P/E negativo (sin ganancias) → red, nunca verde por ser "bajo".
    cats = _cats_by_key(main._build_categories_detail({"trailing_pe": -5.0}, {}))
    assert _metrics_by_key(cats["valuation"])["pe"]["status"] == "red"


def test_per_metric_status_growth_and_profitability():
    cats = _cats_by_key(main._build_categories_detail(
        {"return_on_assets": 0.10, "operating_margins": 0.20, "gross_margins": 0.50},
        {"roe_pct": 20.0, "profit_margin_pct": 18.0, "revenue_growth_pct": 18.0},
        {"rev_growth_3y_pct": 20.0, "eps_growth_3y_pct": 3.0},
    ))
    g = _metrics_by_key(cats["growth"])
    assert g["rev_growth_3y"]["status"] == "green" and g["rev_growth_3y"]["status_label"] == "Excelente"
    assert g["eps_growth_3y"]["status"] == "red" and g["eps_growth_3y"]["status_label"] == "Bajo"
    assert g["rev_growth_yoy"]["status"] == "green"
    p = _metrics_by_key(cats["profitability"])
    assert p["roe"]["status"] == "green"
    assert p["roa"]["status"] == "green"   # 10 >= 8
    assert p["gross_margin"]["status"] == "green"  # 50 >= 40


def test_health_info_metrics_have_no_status():
    """Caja Total / Deuda Total son info: status na, status_label "", value visible."""
    cats = _cats_by_key(main._build_categories_detail(
        {"total_cash_usd": 1_200_000_000, "total_debt_usd": 500_000_000,
         "current_ratio": 2.5, "quick_ratio": 1.2},
        {"debt_to_equity": 0.3},
    ))
    h = _metrics_by_key(cats["health"])
    assert h["total_cash"]["direction"] == "info"
    assert h["total_cash"]["status"] == "na" and h["total_cash"]["status_label"] == ""
    assert h["total_cash"]["value_label"] == "$1.20B"
    assert h["total_debt"]["value_label"] == "$500.0M"
    assert h["debt_equity"]["status"] == "green"
    assert h["current_ratio"]["status"] == "green"  # 2.5 >= 2
    assert h["quick_ratio"]["status"] == "green"     # 1.2 >= 1


def test_debt_equity_excluded_for_financials():
    """Bancos (Financial Services) → D/E status na (igual que el scorecard)."""
    cats = _cats_by_key(main._build_categories_detail(
        {}, {"debt_to_equity": 5.0}, sector="Financial Services",
    ))
    assert _metrics_by_key(cats["health"])["debt_equity"]["status"] == "na"
    # En otro sector el mismo D/E alto → red.
    cats = _cats_by_key(main._build_categories_detail(
        {}, {"debt_to_equity": 5.0}, sector="Technology",
    ))
    assert _metrics_by_key(cats["health"])["debt_equity"]["status"] == "red"


def test_dividends_no_payer_is_na():
    """Sin dividendo (yield 0 / payout 0) → na, no red."""
    cats = _cats_by_key(main._build_categories_detail({}, {"dividend_yield_pct": 0, "payout_ratio_pct": 0}))
    d = _metrics_by_key(cats["dividends"])
    assert d["dividend_yield"]["status"] == "na"
    assert d["payout"]["status"] == "na"
    assert cats["dividends"]["score"] is None

    # Pagador sólido: yield 3.5 (green), payout 40 (green).
    cats = _cats_by_key(main._build_categories_detail({}, {"dividend_yield_pct": 3.5, "payout_ratio_pct": 40}))
    d = _metrics_by_key(cats["dividends"])
    assert d["dividend_yield"]["status"] == "green"
    assert d["payout"]["status"] == "green"


def test_interest_coverage_guards_zero_interest():
    """interest expense 0 → None (no div por cero)."""
    cats = _cats_by_key(main._build_categories_detail(
        {"ebit_usd": 1_000_000, "interest_expense_usd": 0}, {},
    ))
    assert _metrics_by_key(cats["health"])["interest_coverage"]["value"] is None
    # Con interés válido: 1M / 100K = 10x → green.
    cats = _cats_by_key(main._build_categories_detail(
        {"ebit_usd": 1_000_000, "interest_expense_usd": 100_000}, {},
    ))
    ic = _metrics_by_key(cats["health"])["interest_coverage"]
    assert ic["value"] == 10.0 and ic["status"] == "green"
