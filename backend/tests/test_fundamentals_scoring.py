"""Unit tests para el scoring de la feature Fundamentals.

Wave 3: la ÚNICA fuente de verdad es `categories_detail` (5 categorías con
status per-métrica). `_score_categories(categories_detail)` deriva los 4 scores
headline + overall desde ese array. Esto garantiza que las category cards y el
detalle no se contradigan.

Puntos: green=90, amber=55, red=18; na/info EXCLUIDOS.
overall = media ponderada renormalizada de las 4 core (valuation .30,
profitability .25, health .25, growth .20). Dividendos NO entra al overall.

conftest.py aísla la DB, así que `import main` es seguro.
"""
import main


def _m(key, status, direction="higher"):
    """Métrica sintética con status (para armar categories_detail a mano)."""
    return {
        "key": key,
        "label": key,
        "value": 1.0,
        "value_label": "1.00x",
        "direction": direction,
        "status": status,
        "status_label": "",
        "info": "info",
    }


def _cat(key, metrics):
    return {
        "key": key,
        "label": key,
        "question": "?",
        "score": main._category_score_from_metrics(metrics),
        "metrics": metrics,
    }


def _by_key(result):
    return {c["key"]: c for c in result["categories"]}


# ── _category_score_from_metrics (derivación per-categoría) ─────────────────

def test_category_score_status_points():
    """green=90, amber=55, red=18; round(mean)."""
    # mean(55, 55, 18) = 42.67 → 43
    assert main._category_score_from_metrics(
        [_m("a", "amber"), _m("b", "amber"), _m("c", "red")]
    ) == 43
    # mean(90) = 90
    assert main._category_score_from_metrics([_m("a", "green")]) == 90
    # mean(90, 55) = 72.5 → 72 (round-half-to-even)
    assert main._category_score_from_metrics([_m("a", "green"), _m("b", "amber")]) == 72


def test_na_and_info_excluded():
    """na/info no aportan; si todas excluidas → None."""
    assert main._category_score_from_metrics([_m("a", "na"), _m("b", "green")]) == 90
    assert main._category_score_from_metrics([_m("a", "na"), _m("b", "na")]) is None
    assert main._category_score_from_metrics([]) is None


# ── _score_categories (headline 4 cats + overall) ──────────────────────────

def test_score_categories_means():
    detail = [
        _cat("valuation", [_m("pe", "amber"), _m("peg", "amber"), _m("pb", "red")]),
        _cat("growth", [_m("rev", "green")]),
        _cat("profitability", [_m("roe", "green"), _m("net", "green")]),
        _cat("health", [_m("de", "green"), _m("cr", "amber")]),
        _cat("dividends", [_m("dy", "green")]),
    ]
    res = main._score_categories(detail)
    cats = _by_key(res)
    # valuation: mean(55, 55, 18) = 42.67 → 43
    assert cats["valuation"]["score"] == 43
    assert cats["growth"]["score"] == 90
    assert cats["profitability"]["score"] == 90
    # health: mean(90, 55) = 72.5 → 72
    assert cats["health"]["score"] == 72
    # headline solo expone las 4 core (dividends no es card)
    assert set(cats.keys()) == {"valuation", "growth", "profitability", "health"}


def test_overall_weighted_renormalized():
    """overall = media ponderada renormalizada sobre core disponibles."""
    detail = [
        _cat("valuation", [_m("pe", "green")]),   # 90
        _cat("growth", [_m("rev", "red")]),       # 18
        _cat("profitability", []),                 # None
        _cat("health", []),                        # None
        _cat("dividends", [_m("dy", "green")]),
    ]
    res = main._score_categories(detail)
    # weighted = (90*.30 + 18*.20) / (.30+.20) = (27 + 3.6)/.5 = 61.2 → 61
    assert res["overall"] == 61
    assert res["label"] == "Mixto"  # 61 está en [45, 65)


def test_dividends_excluded_from_overall():
    """Dividendos NO entra al overall aunque tenga score."""
    # Sin dividendos:
    base = [
        _cat("valuation", [_m("pe", "amber")]),     # 55
        _cat("growth", [_m("rev", "amber")]),        # 55
        _cat("profitability", [_m("roe", "amber")]), # 55
        _cat("health", [_m("de", "amber")]),         # 55
    ]
    res_no_div = main._score_categories(base)
    # Con un Dividendos perfecto (90) que NO debe mover el overall:
    with_div = base + [_cat("dividends", [_m("dy", "green"), _m("payout", "green")])]
    res_with_div = main._score_categories(with_div)
    assert res_no_div["overall"] == res_with_div["overall"] == 55


def test_labels_thresholds():
    def overall_of(status):
        detail = [
            _cat("valuation", [_m("pe", status)]),
            _cat("growth", [_m("rev", status)]),
            _cat("profitability", [_m("roe", status)]),
            _cat("health", [_m("de", status)]),
        ]
        return main._score_categories(detail)["label"]

    assert overall_of("green") == "Excelente"   # 90
    assert overall_of("amber") == "Mixto"        # 55 (>=45, <65)
    assert overall_of("red") == "Débil"          # 18


def test_no_categories_available():
    detail = [_cat(k, []) for k in ("valuation", "growth", "profitability", "health", "dividends")]
    res = main._score_categories(detail)
    assert res["overall"] is None
    assert res["label"] == "Sin datos"
    assert len(res["categories"]) == 4
    assert all(c["score"] is None for c in res["categories"])


def test_empty_input_does_not_crash():
    res = main._score_categories([])
    assert res["overall"] is None
    assert res["label"] == "Sin datos"
    assert len(res["categories"]) == 4


def test_non_list_input_does_not_crash():
    res = main._score_categories(None)
    assert res["overall"] is None
    assert len(res["categories"]) == 4
