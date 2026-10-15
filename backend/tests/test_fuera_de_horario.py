"""Pre y post mercado (`fuera_de_horario.py` + GET /api/fuera-de-horario).

Yahoo se reemplaza por cotizaciones con la MISMA forma que devolvió el
2026-10-15 a las 7:58 de Nueva York (`/v7/finance/quote`, medido): los ADRs
poco operados vienen sin los campos de pre-mercado y el CEDEAR (.BA) viene con
`market` argentino. Los pedidos pasan por el endpoint real, como en producción.
"""
import datetime as dt
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402  (conftest ya seteó DB_PATH temporal)
import fuera_de_horario as fdh  # noqa: E402

AR = fdh.ZONA_AR
CIERRE = 1792008000          # 14/10 16:00 de NY (regularMarketTime)
PRE = CIERRE + 15 * 3600     # 15/10 7:00 de NY
POST = CIERRE + 2 * 3600     # 14/10 18:00 de NY


def q(sym, estado="PRE", pre=None, post=None, pre_t=PRE, post_t=POST, market="us_market", cierre=CIERRE):
    d = {"symbol": sym, "marketState": estado, "market": market, "regularMarketTime": cierre,
         "regularMarketPrice": 100.0}
    if pre is not None:
        d.update(preMarketChangePercent=pre, preMarketPrice=100 * (1 + pre / 100), preMarketTime=pre_t)
    if post is not None:
        d.update(postMarketChangePercent=post, postMarketPrice=100 * (1 + post / 100), postMarketTime=post_t)
    return d


class Yahoo:
    """Yahoo de mentira: cuenta los pedidos y devuelve lo que se le cargó."""
    def __init__(self, cotizaciones, falla=False):
        self.cot = {c["symbol"]: c for c in cotizaciones}
        self.pedidos = []
        self.falla = falla

    def __call__(self, simbolos):
        self.pedidos.append(list(simbolos))
        if self.falla:
            raise RuntimeError("Yahoo caído")
        return [self.cot[s] for s in simbolos if s in self.cot]


PRE_MERCADO = [
    q("SPY", pre=-0.33), q("AAPL", pre=0.6444), q("NVDA", pre=-1.6049),
    q("PAM"),                                                   # todavía no operó
    q("AAPL.BA", estado="PREPRE", market="ar_market"),          # el CEDEAR en BYMA
]

# 15/10/2026 8:58 hora argentina (7:58 de NY): pre-mercado, BYMA cerrada.
AHORA_PRE = dt.datetime(2026, 10, 15, 8, 58, tzinfo=AR)


@pytest.fixture(autouse=True)
def limpio():
    fdh._vaciar_cache()
    yield
    fdh._vaciar_cache()


def test_en_el_pre_mercado_da_el_porcentaje_de_cada_accion():
    r = fdh.estado(["AAPL", "NVDA"], ahora=AHORA_PRE, pedir=Yahoo(PRE_MERCADO))
    assert r["sesion"] == "pre"
    assert r["cotizaciones"]["AAPL"]["pct"] == pytest.approx(0.6444)
    assert r["cotizaciones"]["NVDA"]["pct"] == pytest.approx(-1.6049)


def test_la_que_no_opero_es_sin_operar_no_cero():
    r = fdh.estado(["PAM"], ahora=AHORA_PRE, pedir=Yahoo(PRE_MERCADO))
    assert r["cotizaciones"]["PAM"] == {"pct": None, "precio": None}


def test_lo_que_no_cotiza_en_eeuu_no_aparece():
    r = fdh.estado(["AAPL.BA", "NOEXISTE"], ahora=AHORA_PRE, pedir=Yahoo(PRE_MERCADO))
    assert r["cotizaciones"] == {}


def test_un_pre_mercado_viejo_no_se_muestra_como_de_hoy():
    # Hora del pre ANTERIOR al último cierre: es de otro día.
    viejo = [q("SPY", pre=-0.3), q("AAPL", pre=2.0, pre_t=CIERRE - 3600)]
    r = fdh.estado(["AAPL"], ahora=AHORA_PRE, pedir=Yahoo(viejo))
    assert r["cotizaciones"]["AAPL"]["pct"] is None


def test_la_hora_de_cierre_va_en_hora_argentina_y_sigue_al_cambio_de_hora_de_eeuu():
    r = fdh.estado([], ahora=AHORA_PRE, pedir=Yahoo(PRE_MERCADO))
    assert r["cierra"] == "10:30"                      # octubre: NY = AR − 1
    nov = dt.datetime(2026, 11, 5, 9, 0, tzinfo=AR)    # EE.UU. ya atrasó el reloj
    r = fdh.estado([], ahora=nov, pedir=Yahoo(PRE_MERCADO))
    assert r["cierra"] == "11:30"


def test_post_mercado_usa_el_post_y_cierra_a_las_21():
    post = [q("SPY", estado="POST", post=0.11), q("NVDA", estado="POST", post=0.85, pre=-1.6)]
    ahora = dt.datetime(2026, 10, 14, 18, 40, tzinfo=AR)
    r = fdh.estado(["NVDA"], ahora=ahora, pedir=Yahoo(post))
    assert r["sesion"] == "post"
    assert r["cierra"] == "21:00"
    assert r["cotizaciones"]["NVDA"]["pct"] == pytest.approx(0.85)


@pytest.mark.parametrize("estado,hubo_post,esperado", [
    ("POSTPOST", True, "post_cerrado"),
    ("PREPRE", True, "post_cerrado"),
    ("CLOSED", True, "post_cerrado"),     # fin de semana: el del viernes
    ("CLOSED", False, None),
    ("REGULAR", True, None),              # en la rueda manda la «Var. día»
])
def test_que_momento_es(estado, hubo_post, esperado):
    spy = q("SPY", estado=estado, post=0.2 if hubo_post else None)
    assert fdh.sesion_de(spy) == esperado


def test_en_la_rueda_normal_no_hay_nada_que_mostrar():
    rueda = [q("SPY", estado="REGULAR", post=0.1), q("AAPL", estado="REGULAR", pre=0.5)]
    r = fdh.estado(["AAPL"], ahora=AHORA_PRE, pedir=Yahoo(rueda))
    assert r["sesion"] is None
    assert r["cotizaciones"] == {}


def test_byma_abierta_de_11_a_17_de_lunes_a_viernes():
    assert fdh.byma_abierto(dt.datetime(2026, 10, 15, 11, 0, tzinfo=AR))
    assert not fdh.byma_abierto(dt.datetime(2026, 10, 15, 10, 59, tzinfo=AR))
    assert not fdh.byma_abierto(dt.datetime(2026, 10, 15, 17, 0, tzinfo=AR))
    assert not fdh.byma_abierto(dt.datetime(2026, 10, 17, 12, 0, tzinfo=AR))   # sábado


def test_un_solo_pedido_a_yahoo_y_un_minuto_de_cache():
    y = Yahoo(PRE_MERCADO)
    fdh.estado(["AAPL", "NVDA", "PAM"], ahora=AHORA_PRE, pedir=y)
    assert len(y.pedidos) == 1
    fdh.estado(["AAPL", "NVDA", "PAM"], ahora=AHORA_PRE, pedir=y)
    assert len(y.pedidos) == 1              # todo salió del caché, incluso lo que no existe


def test_si_yahoo_falla_no_se_guarda_la_falla():
    caido = Yahoo(PRE_MERCADO, falla=True)
    r = fdh.estado(["AAPL"], ahora=AHORA_PRE, pedir=caido)
    assert r["sesion"] is None and r["cotizaciones"] == {}
    sano = Yahoo(PRE_MERCADO)
    r = fdh.estado(["AAPL"], ahora=AHORA_PRE, pedir=sano)
    assert r["sesion"] == "pre"             # el siguiente refresco volvió a preguntar


# ─── El endpoint, como lo llama la pantalla ─────────────────────────────────

@pytest.fixture
def cliente(monkeypatch):
    y = Yahoo(PRE_MERCADO + [q(x["s"], pre=0.1) for x in fdh.ADRS + fdh.POPULARES + fdh.INDICES
                              if x["s"] not in ("SPY", "AAPL", "NVDA", "PAM")])
    monkeypatch.setattr(fdh, "_pedir_yahoo", y)
    main.app.dependency_overrides[main.get_effective_user] = lambda: 1
    try:
        yield TestClient(main.app), y
    finally:
        main.app.dependency_overrides.pop(main.get_effective_user, None)


def test_el_endpoint_limpia_los_simbolos(cliente):
    c, y = cliente
    r = c.get("/api/fuera-de-horario", params={"symbols": "aapl, NVDA,AAPL,;DROP,"})
    assert r.status_code == 200
    # Mayúsculas, sin repetidos, sin lo que no es un ticker; SPY siempre (dice qué momento es).
    assert sorted(y.pedidos[0]) == ["AAPL", "NVDA", "SPY"]
    assert "listas" not in r.json()


def test_el_endpoint_con_listas_trae_indices_adrs_y_populares(cliente):
    c, y = cliente
    r = c.get("/api/fuera-de-horario", params={"listas": "1"}).json()
    assert [x["s"] for x in r["listas"]["indices"]] == ["SPY", "QQQ", "DIA"]
    assert "GGAL" in {x["s"] for x in r["listas"]["adrs"]}
    assert "MELI" in {x["s"] for x in r["listas"]["populares"]}
    # Todo lo de las listas se pidió en el mismo viaje a Yahoo.
    assert len(y.pedidos) == 1
