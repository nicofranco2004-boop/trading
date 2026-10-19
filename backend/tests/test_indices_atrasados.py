"""La cinta de índices no muestra como «de hoy» una variación de una rueda vieja.

El 2026-10-19 Yahoo dejó de actualizar ^MERV: con BYMA abierta, la cinta decía
«Merval −0,35 %», que era la variación del viernes 16. La prueba entra por el
endpoint real (GET /api/home/indices → get_indices_strip → _fetch_batch_quotes),
con la cotización de ^MERV como la devolvió `main._variacion_del_dia` ese día
(medido: as_of '2026-10-16', change_pct −0,35).
"""
import datetime as dt
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402  (conftest ya seteó DB_PATH temporal)
import fuera_de_horario as fdh  # noqa: E402
from home import market  # noqa: E402

VIE, LUN = dt.date(2026, 10, 16), dt.date(2026, 10, 19)


def _cotizaciones(merval_as_of):
    def variacion(simbolos, tope=None):
        out = {}
        for s in simbolos:
            out[s] = {"symbol": s, "price": 100.0, "prev_close": 99.0, "change_pct": 1.01,
                      "mercado": "eeuu", "as_of": LUN.isoformat()}
        out["^MERV"] = {"symbol": "^MERV", "price": 2848945.0, "prev_close": 2859051.0,
                        "change_pct": -0.35, "mercado": "eeuu", "as_of": merval_as_of}
        return out
    return variacion


@pytest.fixture
def cinta(monkeypatch):
    monkeypatch.setattr("fechas.ahora_art", lambda: dt.datetime(2026, 10, 19, 14, 0))
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {dt.date(2026, 10, 15), VIE, LUN})
    market._cache.pop("indices_strip", None)
    market._QUOTE_CACHE.clear()
    main.app.dependency_overrides[main.get_effective_user] = lambda: 1

    def pedir(merval_as_of):
        monkeypatch.setattr(main, "_variacion_del_dia", _cotizaciones(merval_as_of))
        market._cache.pop("indices_strip", None)
        market._QUOTE_CACHE.clear()
        fdh._vaciar_cache()
        items = TestClient(main.app).get("/api/home/indices").json()["items"]
        return {it["symbol"]: it for it in items}
    try:
        yield pedir
    finally:
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        market._cache.pop("indices_strip", None)
        market._QUOTE_CACHE.clear()


def test_el_merval_del_viernes_con_byma_operando_hoy_no_trae_variacion(cinta):
    items = cinta(VIE.isoformat())
    merv = items["^MERV"]
    assert merv["atrasado"] is True
    assert merv["change_pct"] is None            # no «−0,35 %» como si fuera de hoy
    assert merv["price"] == 2848945.0            # el último valor sí se muestra…
    assert merv["as_of"] == "2026-10-16"         # …con su fecha («al 16/10»)
    # Los de Wall Street no se tocan.
    assert items["^GSPC"]["atrasado"] is False and items["^GSPC"]["change_pct"] == 1.01


def test_el_merval_al_dia_sigue_igual(cinta):
    merv = cinta(LUN.isoformat())["^MERV"]
    assert merv["atrasado"] is False and merv["change_pct"] == -0.35


def test_un_feriado_de_byma_no_lo_marca_atrasado(cinta, monkeypatch):
    # BYMA no operó el lunes (feriado): el dato del viernes ES la última rueda.
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {dt.date(2026, 10, 15), VIE})
    merv = cinta(VIE.isoformat())["^MERV"]
    assert merv["atrasado"] is False and merv["change_pct"] == -0.35
