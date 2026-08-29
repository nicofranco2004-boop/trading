"""Packet de las tortas de distribución (tipo / sector).

El builder recibe el corte ya calculado del frontend a propósito (ver la
cabecera de ai/builders/distribution.py). Su trabajo es sanear la entrada y
calcular la LECTURA — quién rinde, quién aporta, qué no se puede medir. Estos
tests cubren las dos cosas.
"""
import json
import pytest

from ai.builders.distribution import build_type, build_sector
from ai.registry import REGISTRY
from ai import prompts


def _params(**over):
    base = {
        "total_usd": 66980,
        "unclassified_pct": 1.4,
        "slices": [
            {"label": "Acciones AR", "value_usd": 13939, "weight_pct": 20.8,
             "pnl_usd": -430, "pnl_pct": -3.1,
             "assets": [{"a": "GGAL", "w": 8.1, "p": -7.4}, {"a": "YPFD", "w": 6.1, "p": 17.6}]},
            {"label": "CEDEARs", "value_usd": 12459, "weight_pct": 18.6,
             "pnl_usd": 1700, "pnl_pct": 15.8, "assets": [{"a": "NVDA", "w": 5.8, "p": 33.7}]},
            {"label": "Cripto", "value_usd": 9800, "weight_pct": 14.6,
             "pnl_usd": 1410, "pnl_pct": 16.8},
            {"label": "Bonos y letras", "value_usd": 8114, "weight_pct": 12.1,
             "pnl_usd": 1147, "pnl_pct": 14.1},
            {"label": "Efectivo", "value_usd": 2879, "weight_pct": 4.3},
        ],
    }
    base.update(over)
    return base


# ── Los dos topics existen y renderean ─────────────────────────────────────

@pytest.mark.parametrize("topic", ["portfolio.distribution_type",
                                   "portfolio.distribution_sector"])
def test_topic_registrado_con_prompt(topic):
    assert topic in REGISTRY
    builder, render = REGISTRY[topic]
    assert callable(builder) and callable(render)
    for tier in ("free", "plus", "pro"):
        assert len(render(tier=tier)) > 200


def test_los_dos_ejes_se_identifican_distinto():
    t = build_type(None, 1, **_params())
    s = build_sector(None, 1, **_params())
    assert t["screen"] == "portfolio.distribution_type"
    assert s["screen"] == "portfolio.distribution_sector"
    assert t["eje"] != s["eje"]


# ── Saneamiento de la entrada ──────────────────────────────────────────────

def test_descarta_entradas_malformadas_sin_explotar():
    p = build_type(None, 1, **_params(slices=[
        "no soy un dict",
        {"label": "sin peso"},
        {"weight_pct": 10},                       # sin nombre
        {"label": "ok", "weight_pct": 10, "value_usd": 100},
        None,
    ]))
    assert [x["nombre"] for x in p["porciones"]] == ["ok"]


def test_sin_params_devuelve_packet_vacio_valido():
    p = build_type(None, 1)
    assert p["porciones"] == []
    assert p["total_usd"] == 0
    json.dumps(p)  # serializable


def test_no_inventa_el_porcentaje_cuando_falta():
    # El frontend oculta la tasa cuando no puede despejar el costo. Acá
    # tampoco se estima a partir del monto.
    p = build_type(None, 1, **_params(slices=[
        {"label": "Acciones US", "weight_pct": 13.3, "value_usd": 8914, "pnl_usd": 844},
    ]))
    porcion = p["porciones"][0]
    assert porcion["resultado_usd"] == 844
    assert "resultado_pct" not in porcion


def test_valores_no_finitos_no_pasan():
    p = build_type(None, 1, **_params(slices=[
        {"label": "Raro", "weight_pct": float("nan"), "value_usd": 10},
        {"label": "Bien", "weight_pct": 10, "value_usd": float("inf")},
    ]))
    assert [x["nombre"] for x in p["porciones"]] == ["Bien"]
    assert p["porciones"][0]["valor_usd"] == 0


def test_topes_de_tamano():
    slices = [{"label": f"S{i}", "weight_pct": 5, "value_usd": 100,
               "assets": [{"a": f"T{j}", "w": 1} for j in range(20)]}
              for i in range(30)]
    p = build_type(None, 1, **_params(slices=slices))
    assert len(p["porciones"]) <= 12
    assert all(len(x.get("activos", [])) <= 6 for x in p["porciones"])
    assert len(json.dumps(p)) < 6000


# ── La lectura ─────────────────────────────────────────────────────────────

def test_rankea_por_tasa_y_por_monto_por_separado():
    # No es lo mismo quién rinde más que quién aporta más plata: CEDEARs rinde
    # menos que Cripto pero aporta más dólares. Confundirlos es EL error de
    # lectura de esta vista.
    p = build_type(None, 1, **_params())
    assert p["mejores"][0]["nombre"] == "Cripto"
    assert p["mas_aporta_usd"][0]["nombre"] == "CEDEARs"


def test_una_porcion_chica_no_entra_en_los_rankings():
    # Un +400% sobre el 0,3% de la cartera es ruido; arriba de un análisis se
    # leería como señal.
    p = build_type(None, 1, **_params(slices=_params()["slices"] + [
        {"label": "Migaja", "weight_pct": 0.4, "value_usd": 30, "pnl_usd": 24, "pnl_pct": 400},
    ]))
    assert any(x["nombre"] == "Migaja" for x in p["porciones"])
    assert all(x["nombre"] != "Migaja" for x in p["mejores"])


def test_reporta_cuanta_cartera_no_tiene_rendimiento_medible():
    # Efectivo (4,3%) no tiene tasa. Sin este número el modelo lee los % como
    # si cubrieran toda la cartera.
    p = build_type(None, 1, **_params())
    assert p["sin_rendimiento_medible_pct"] == 4.3
    assert p["sin_clasificar_pct"] == 1.4


def test_concentracion():
    p = build_type(None, 1, **_params())
    assert p["concentracion"]["top1_pct"] == 20.8
    assert p["concentracion"]["top3_pct"] == pytest.approx(54.0, abs=0.1)


# ── El prompt tiene las guardas que importan ───────────────────────────────

@pytest.mark.parametrize("render", [prompts.render_distribution_type_prompt,
                                    prompts.render_distribution_sector_prompt])
def test_el_prompt_prohibe_sumar_tasas(render):
    # Sumar % de resultado entre porciones es matemáticamente inválido (bases
    # distintas) y es el error más fácil de cometer con este packet.
    assert "NUNCA sumar los porcentajes de resultado" in render(tier="pro")


def test_mejores_y_peores_no_se_solapan():
    # Con 5 porciones medibles, la del medio aparecía en las dos listas.
    slices = [{"label": f"S{i}", "weight_pct": 15, "value_usd": 1000,
               "pnl_usd": 100 * i, "pnl_pct": 10 * i} for i in range(1, 6)]
    p = build_type(None, 1, **_params(slices=slices))
    mejores = {x["nombre"] for x in p["mejores"]}
    peores = {x["nombre"] for x in p["menos_rinden"]}
    assert mejores == {"S5", "S4", "S3"}
    assert peores == {"S1", "S2"}
    assert not (mejores & peores)


def test_una_porcion_chica_pero_real_si_entra():
    # Salud con 2,7% es chica pero no es ruido — el caso que motivó bajar el
    # umbral. La que se filtra es la de 0,4%.
    slices = _params()["slices"] + [
        {"label": "Salud", "weight_pct": 2.7, "value_usd": 1804, "pnl_usd": -60, "pnl_pct": -3.2},
        {"label": "Migaja", "weight_pct": 0.4, "value_usd": 30, "pnl_usd": 24, "pnl_pct": 400},
    ]
    p = build_type(None, 1, **_params(slices=slices))
    rankeadas = {x["nombre"] for x in p["mejores"]} | {x["nombre"] for x in p["menos_rinden"]}
    assert "Salud" in rankeadas
    assert "Migaja" not in rankeadas


@pytest.mark.parametrize("render", [prompts.render_distribution_type_prompt,
                                    prompts.render_distribution_sector_prompt])
def test_el_prompt_aclara_que_la_cola_no_es_perdida(render):
    # `menos_rinden` puede traer números positivos: en una cartera que anda
    # bien, la última del ranking igual ganó plata.
    assert "NO una lista de pérdidas" in render(tier="pro")
