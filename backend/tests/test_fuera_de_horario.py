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
    # Y con contra qué cierre se mide (el del 14/10, 16:00 de NY): lo usan las alertas.
    assert r["cotizaciones"]["PAM"] == {"pct": None, "precio": None, "base": "2026-10-14"}


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


def test_si_yahoo_falla_no_se_guarda_el_dato_y_se_espera_un_rato():
    caido = Yahoo(PRE_MERCADO, falla=True)
    r = fdh.estado(["AAPL"], ahora=AHORA_PRE, pedir=caido)
    assert r["sesion"] is None and r["cotizaciones"] == {}
    # Durante la pausa NO se le vuelve a preguntar (nadie espera el tope entero).
    sano = Yahoo(PRE_MERCADO)
    r = fdh.estado(["AAPL"], ahora=AHORA_PRE, pedir=sano)
    assert sano.pedidos == [] and r["sesion"] is None
    # Pasada la pausa, vuelve a preguntar: la falla no quedó guardada como dato.
    fdh._falla_hasta = 0.0
    r = fdh.estado(["AAPL"], ahora=AHORA_PRE, pedir=sano)
    assert r["sesion"] == "pre"


def test_en_la_rueda_normal_ni_se_le_pregunta_a_yahoo():
    y = Yahoo(PRE_MERCADO)
    a_las_13 = dt.datetime(2026, 10, 15, 13, 0, tzinfo=AR)      # 12:00 de Nueva York
    r = fdh.estado(["AAPL"], ahora=a_las_13, pedir=y)
    assert y.pedidos == [] and r["sesion"] is None


# ─── El endpoint, como lo llama la pantalla ─────────────────────────────────

@pytest.fixture
def cliente(monkeypatch):
    y = Yahoo(PRE_MERCADO + [q(x["s"], pre=0.1) for x in fdh.ADRS + fdh.POPULARES + fdh.INDICES
                              if x["s"] not in ("SPY", "AAPL", "NVDA", "PAM")])
    monkeypatch.setattr(fdh, "_pedir_yahoo", y)
    # A las 8:58: pre-mercado (en la rueda normal ni se le pregunta a Yahoo).
    monkeypatch.setattr("fechas.ahora_art", lambda: AHORA_PRE.replace(tzinfo=None))
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


# ─── Las tablas de traducción: la pantalla y el chat traducen igual ─────────

def _tabla_js(nombre):
    """Lee `export const <nombre> = { ... }` de frontend/src/utils/tickers.js."""
    import re
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "frontend", "src", "utils", "tickers.js")
    texto = open(ruta, encoding="utf-8").read()
    m = re.search(r"export const " + nombre + r"\s*=\s*\{(.*?)\}", texto, re.S)
    assert m, f"no encontré {nombre} en tickers.js"
    return dict(re.findall(r"([A-Z0-9]+)\s*:\s*'([A-Z0-9.\-]+)'", m.group(1)))


@pytest.mark.parametrize("nombre", ["CEDEAR_EN_EEUU", "CEDEAR_ESPECIE_ALIAS", "ADR_DE_ACCION_AR"])
def test_las_tablas_del_servidor_son_las_de_la_pantalla(nombre):
    assert getattr(fdh, nombre) == _tabla_js(nombre), (
        f"{nombre} cambió en frontend/src/utils/tickers.js y no en fuera_de_horario.py (o al revés)")


@pytest.mark.parametrize("clave,tipo,esperado", [
    ("AAPL.BA", "CEDEAR", ("AAPL", "eeuu")),
    ("DISN.BA", None, ("DIS", "eeuu")),        # el CEDEAR de Disney es DIS en EE.UU.
    ("YPFD.BA", None, ("YPF", "adr")),
    ("AGRO.BA", None, None),                   # sin ADR: AGRO tal cual sería Adecoagro
    ("AL30.BA", "BOND", None),
    ("AL30.BA", None, None),
    ("GD30", None, None),                      # bono en un broker del exterior
    ("BTC", None, None),
    ("FCI:ALGO", None, None),
    ("NVDA", None, ("NVDA", "propio")),
    ("GGAL", None, ("GGAL", "propio")),        # el ADR en Schwab es él mismo
    ("SPY.BA", None, ("SPY", "eeuu")),         # CEDEAR de un ETF
])
def test_a_que_accion_de_eeuu_mira_cada_tenencia(clave, tipo, esperado):
    assert fdh.referencia_en_eeuu(clave, tipo) == esperado


# ─── El post de anoche y el pre de hoy, desde las velas (para el mail) ──────

def _v(dia, h, m, c):
    return (dt.datetime.combine(dia, dt.time(h, m), fdh.ZONA_NY), c)


def test_las_velas_dan_el_post_de_la_rueda_anterior_y_el_pre_de_hoy():
    mie, jue = dt.date(2026, 10, 14), dt.date(2026, 10, 15)
    velas = [_v(mie, 15, 55, 343.04),          # última vela de la rueda (no es el cierre oficial)
             _v(mie, 17, 0, 344.0), _v(mie, 19, 55, 344.78),
             _v(jue, 4, 0, 345.0), _v(jue, 9, 25, 346.9),
             _v(jue, 9, 35, 350.0)]            # ya es la rueda de hoy: no es pre
    f = fdh.franjas_de_velas(velas, {dt.date(2026, 10, 13): 341.27, mie: 342.96}, jue)
    # Contra el cierre OFICIAL del 14 (342,96), como la cotización en vivo.
    assert f["post"] == {"pct": pytest.approx((344.78 / 342.96 - 1) * 100, abs=1e-4), "dia": "2026-10-14", "hasta": "19:55"}
    assert f["pre"]["pct"] == pytest.approx((346.9 / 342.96 - 1) * 100, abs=1e-4)
    assert f["pre"]["hasta"] == "09:25"


def test_sin_velas_fuera_de_la_rueda_no_hay_franja():
    mie, jue = dt.date(2026, 10, 14), dt.date(2026, 10, 15)
    f = fdh.franjas_de_velas([_v(mie, 15, 55, 80.0)], {mie: 80.75}, jue)
    assert f == {"post": None, "pre": None}


def test_antes_de_las_930_de_nueva_york_el_pre_viene_abierto():
    jue = dt.date(2026, 10, 15)
    por = {"NVDA": {"post": None, "pre": {"pct": 1.0, "dia": "2026-10-15", "hasta": "08:00"}}}
    lotes = [{"asset": "NVDA", "valor": 1000.0, "ref": ("NVDA", "propio")}]
    temprano = dt.datetime(2026, 11, 5, 11, 0, tzinfo=AR)     # desde el 1/11: 9:00 de NY
    assert fdh.resumen_de_la_manana(lotes, por, ahora=temprano)["pre"]["abierto"] is True
    tarde = dt.datetime(2026, 10, 15, 11, 0, tzinfo=AR)        # octubre: 10:00 de NY
    assert fdh.resumen_de_la_manana(lotes, por, ahora=tarde)["pre"]["abierto"] is False



def test_la_lista_de_cedears_es_la_de_la_pantalla():
    import re
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "frontend", "src", "utils", "tickers.js")
    texto = open(ruta, encoding="utf-8").read()
    m = re.search(r"export const CEDEARS_LIST = \[(.*?)\n\]", texto, re.S)
    pantalla = set(re.findall(r"s: '([A-Z0-9.\-]+)'", m.group(1)))
    assert fdh.CEDEARS == pantalla, (
        "CEDEARS_LIST cambió en tickers.js y no en fuera_de_horario.CEDEARS (o al revés)")


@pytest.mark.parametrize("clave,esperado", [
    ("BRKB.BA", ("BRK-B", "eeuu")),     # faltaba en la lista del servidor (auditoría)
    ("MCD.BA", ("MCD", "eeuu")),
    ("NOKA.BA", ("NOK", "eeuu")),
    ("BRK-B", ("BRK-B", "propio")),     # en Schwab: la clave de precio ya viene con guión
])
def test_los_cedears_que_faltaban(clave, esperado):
    assert fdh.referencia_en_eeuu(clave) == esperado


def test_el_post_del_viernes_no_se_llama_anoche_un_domingo():
    # El fin de semana sigue a la vista el post del viernes. El sábado ES «anoche»;
    # el domingo (y el lunes antes del pre) ya no.
    datos = {"sesion": "post_cerrado", "byma_abierto": False,
             "cotizaciones": {"NVDA": {"pct": 1.0, "precio": 101.0, "base": "2026-10-16"}}}
    lote = [{"asset": "NVDA", "valor": 1000.0, "ref": ("NVDA", "propio")}]
    sabado = dt.datetime(2026, 10, 17, 12, 0, tzinfo=AR)
    domingo = dt.datetime(2026, 10, 18, 12, 0, tzinfo=AR)
    assert fdh.resumen_de_lotes(lote, datos, ahora=sabado)["cuando"] == "anoche"
    r = fdh.resumen_de_lotes(lote, datos, ahora=domingo)
    assert r["cuando"] == "el viernes a la noche"
    assert r["abierto"] is False
    assert r["sin_operar_todavia"] == []


# ─── CEDEARs: desde el cierre de BYMA, no desde el de NY ────────────────────
# Desde el 1/11 (EE.UU. atrasa el reloj) BYMA cierra a las 17:00 de acá = 15:00
# de NY. La última hora de la rueda de NY no está en el precio del CEDEAR ni en
# el % contra el cierre de NY: el anticipo del CEDEAR se mide contra el precio
# de la acción a las 15:00 de NY. Medido 2026-10-15 con Yahoo en vivo: las
# velas de 5 minutos traen la de las 14:55 (termina 15:00) y la diaria del
# Merval no trae el 12/10 (feriado acá, NY abierta).

NY = fdh.ZONA_NY


def _ts(dia, h, m=0):
    return int(dt.datetime.combine(dia, dt.time(h, m), NY).timestamp())


def _cot(sym, estado, cierre_dia, cierre, post=None, pre=None):
    """Cotización de Yahoo con la forma medida: el % contra `cierre` (el de la
    rueda del `cierre_dia`, 16:00 de NY)."""
    t = _ts(cierre_dia, 16)
    d = {"symbol": sym, "marketState": estado, "market": "us_market",
         "regularMarketTime": t, "regularMarketPrice": cierre}
    if post is not None:
        d.update(postMarketPrice=post, postMarketTime=t + 3600,
                 postMarketChangePercent=(post / cierre - 1) * 100)
    if pre is not None:
        d.update(preMarketPrice=pre, preMarketTime=t + 15 * 3600,
                 preMarketChangePercent=(pre / cierre - 1) * 100)
    return d


class Velas:
    """Velas de 5 minutos de mentira, por símbolo; cuenta los pedidos."""
    def __init__(self, por_simbolo, falla=False):
        self.por = por_simbolo
        self.pedidos = []
        self.falla = falla

    def __call__(self, simbolo):
        self.pedidos.append(simbolo)
        if self.falla:
            raise RuntimeError("Yahoo caído")
        return self.por.get(simbolo, ([], {}))


LUN_16_11 = dt.date(2026, 11, 16)
# AAPL el lunes 16/11 (invierno): 100 a las 15:00 de NY (cierre de BYMA), cierra
# la rueda en 102 y en el post va 103.
VELAS_AAPL_INVIERNO = ([(dt.datetime.combine(LUN_16_11, dt.time(h, m), NY), c) for h, m, c in (
    (14, 50, 99.5), (14, 55, 100.0),   # la de las 14:55 termina a las 15:00: ESA
    (15, 0, 101.0), (15, 55, 101.9),   # la última hora de la rueda de NY
    (16, 0, 102.0), (17, 0, 103.0))],  # el post
    {dt.date(2026, 11, 13): 98.0, LUN_16_11: 102.0})


@pytest.fixture
def invierno(monkeypatch):
    """El endpoint el lunes 16/11 a las 19:00 de acá (17:00 de NY): post abierto."""
    y = Yahoo([_cot("SPY", "POST", LUN_16_11, 600.0, post=601.0),
               _cot("AAPL", "POST", LUN_16_11, 102.0, post=103.0),
               _cot("NVDA", "POST", LUN_16_11, 200.0, post=202.0)])
    v = Velas({"AAPL": VELAS_AAPL_INVIERNO})
    monkeypatch.setattr(fdh, "_pedir_yahoo", y)
    monkeypatch.setattr(fdh, "_traer_velas", v)
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {dt.date(2026, 11, 13), LUN_16_11})
    monkeypatch.setattr("fechas.ahora_art", lambda: dt.datetime(2026, 11, 16, 19, 0))
    main.app.dependency_overrides[main.get_effective_user] = lambda: 1
    try:
        yield TestClient(main.app), y, v
    finally:
        main.app.dependency_overrides.pop(main.get_effective_user, None)


def test_en_invierno_el_cedear_se_mide_desde_el_cierre_de_byma(invierno):
    c, _y, v = invierno
    r = c.get("/api/fuera-de-horario", params={"symbols": "AAPL,NVDA", "byma": "AAPL"}).json()
    aapl = r["cotizaciones"]["AAPL"]
    # La acción misma (Schwab): contra el cierre de NY, 103 / 102.
    assert aapl["pct"] == pytest.approx((103 / 102 - 1) * 100, abs=1e-4)
    # El CEDEAR: contra la acción a las 15:00 de NY, 103 / 100 = +3 %. Incluye
    # la última hora de la rueda (+2 %), que no estaba en ningún lado.
    assert aapl["pct_byma"] == pytest.approx(3.0, abs=1e-4)
    assert aapl["base_byma"] == "2026-11-16"
    # NVDA no la sigue ningún CEDEAR: ni se piden sus velas.
    assert "pct_byma" not in r["cotizaciones"]["NVDA"]
    assert v.pedidos == ["AAPL"]
    # El precio de un cierre que ya pasó no cambia: el próximo refresco no repide velas.
    fdh._cache.clear()
    c.get("/api/fuera-de-horario", params={"symbols": "AAPL,NVDA", "byma": "AAPL"})
    assert v.pedidos == ["AAPL"]


def test_en_invierno_el_cedear_sin_operar_en_el_post_igual_tiene_la_ultima_hora(monkeypatch):
    # La acción todavía no operó en el post: su precio es el cierre (102), y la
    # hora de 15 a 16 de NY sigue pendiente para el CEDEAR.
    y = Yahoo([_cot("SPY", "POST", LUN_16_11, 600.0, post=601.0),
               _cot("AAPL", "POST", LUN_16_11, 102.0)])
    v = Velas({"AAPL": VELAS_AAPL_INVIERNO})
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {LUN_16_11})
    r = fdh.estado(["AAPL"], byma=["AAPL"], pedir=y, traer=v,
                   ahora=dt.datetime(2026, 11, 16, 19, 0, tzinfo=AR))
    aapl = r["cotizaciones"]["AAPL"]
    assert aapl["pct"] is None                                    # la acción: «sin operar»
    assert aapl["pct_byma"] == pytest.approx(2.0, abs=1e-4)       # el CEDEAR: 102 / 100


def test_en_invierno_el_pre_se_mide_desde_el_cierre_de_byma_de_ayer(monkeypatch):
    mar = dt.date(2026, 11, 17)
    y = Yahoo([_cot("SPY", "PRE", LUN_16_11, 600.0, pre=601.0),
               _cot("AAPL", "PRE", LUN_16_11, 102.0, pre=104.0)])
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {LUN_16_11})
    r = fdh.estado(["AAPL"], byma=["AAPL"], pedir=y, traer=Velas({"AAPL": VELAS_AAPL_INVIERNO}),
                   ahora=dt.datetime.combine(mar, dt.time(9, 0), AR))
    assert r["cotizaciones"]["AAPL"]["pct_byma"] == pytest.approx(4.0, abs=1e-4)   # 104 / 100


def test_en_verano_los_dos_porcentajes_coinciden_y_no_se_piden_velas(monkeypatch):
    # Octubre: 17:00 de acá = 16:00 de NY, el mismo cierre de Yahoo.
    mie = dt.date(2026, 10, 14)
    y = Yahoo([_cot("SPY", "POST", mie, 600.0, post=601.0), _cot("AAPL", "POST", mie, 102.0, post=103.0)])
    v = Velas({})
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {mie})
    r = fdh.estado(["AAPL"], byma=["AAPL"], pedir=y, traer=v,
                   ahora=dt.datetime(2026, 10, 14, 18, 0, tzinfo=AR))
    aapl = r["cotizaciones"]["AAPL"]
    assert aapl["pct_byma"] == aapl["pct"]
    assert v.pedidos == []


def test_con_byma_cerrada_por_feriado_se_mide_desde_su_ultimo_cierre(monkeypatch):
    # Lunes 12/10/2026: feriado acá, NY abierta (medido: el Merval no tiene vela
    # ese día). El CEDEAR sigue con el precio del viernes 9: le falta TODO el
    # lunes de NY, no sólo el post.
    vie, lun = dt.date(2026, 10, 9), dt.date(2026, 10, 12)
    velas = ([(dt.datetime.combine(lun, dt.time(15, 55), NY), 104.0)], {vie: 100.0, lun: 105.0})
    y = Yahoo([_cot("SPY", "POST", lun, 600.0, post=601.0), _cot("AAPL", "POST", lun, 105.0, post=106.0)])
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {dt.date(2026, 10, 8), vie})
    r = fdh.estado(["AAPL"], byma=["AAPL"], pedir=y, traer=Velas({"AAPL": velas}),
                   ahora=dt.datetime(2026, 10, 12, 18, 0, tzinfo=AR))
    aapl = r["cotizaciones"]["AAPL"]
    assert aapl["base_byma"] == "2026-10-09"
    assert aapl["pct_byma"] == pytest.approx(6.0, abs=1e-4)      # 106 contra el cierre oficial del 9 (100)


def test_con_nueva_york_cerrada_el_cedear_ya_tiene_adentro_el_post_anterior(monkeypatch):
    # Jueves 26/11/2026, Acción de Gracias: NY cerrada, BYMA abierta. El CEDEAR
    # cerró a las 17:00 de acá con el post del miércoles ya adentro: mostrarle el
    # post del miércoles como anticipo era contarlo dos veces.
    mie, jue = dt.date(2026, 11, 25), dt.date(2026, 11, 26)
    velas = ([(dt.datetime.combine(mie, dt.time(h, m), NY), c) for h, m, c in
              ((14, 55, 100.0), (15, 55, 101.0), (19, 55, 103.0))], {mie: 101.0})
    y = Yahoo([_cot("SPY", "CLOSED", mie, 600.0, post=601.0), _cot("AAPL", "CLOSED", mie, 101.0, post=103.0)])
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {mie, jue})
    r = fdh.estado(["AAPL"], byma=["AAPL"], pedir=y, traer=Velas({"AAPL": velas}),
                   ahora=dt.datetime(2026, 11, 26, 20, 0, tzinfo=AR))
    assert r["sesion"] == "post_cerrado"
    aapl = r["cotizaciones"]["AAPL"]
    assert aapl["pct"] == pytest.approx((103 / 101 - 1) * 100, abs=1e-4)   # la acción, contra su cierre
    assert aapl["pct_byma"] == pytest.approx(0.0, abs=1e-4)                # el CEDEAR ya lo tiene


def test_sin_velas_va_contra_el_cierre_de_ny_y_no_hace_esperar_cada_refresco(monkeypatch):
    y = Yahoo([_cot("SPY", "POST", LUN_16_11, 600.0, post=601.0),
               _cot("AAPL", "POST", LUN_16_11, 102.0, post=103.0)])
    v = Velas({}, falla=True)
    monkeypatch.setattr(fdh, "_traer_sesiones_byma", lambda: {LUN_16_11})
    ahora = dt.datetime(2026, 11, 16, 19, 0, tzinfo=AR)
    r = fdh.estado(["AAPL"], byma=["AAPL"], pedir=y, traer=v, ahora=ahora)
    aapl = r["cotizaciones"]["AAPL"]
    assert aapl["pct_byma"] == aapl["pct"]          # como antes del arreglo, no «sin operar»
    fdh._cache.clear()
    fdh.estado(["AAPL"], byma=["AAPL"], pedir=y, traer=v, ahora=ahora)
    assert v.pedidos == ["AAPL"]                    # la falla se recuerda un rato


@pytest.mark.parametrize("ahora,sesiones,esperado", [
    (dt.datetime(2026, 11, 16, 19, 0), {dt.date(2026, 11, 16)}, dt.datetime(2026, 11, 16, 17, 0)),
    (dt.datetime(2026, 11, 16, 16, 59), {dt.date(2026, 11, 13), dt.date(2026, 11, 16)},
     dt.datetime(2026, 11, 13, 17, 0)),                           # todavía no cerró hoy: el viernes
    (dt.datetime(2026, 11, 17, 9, 0), None, dt.datetime(2026, 11, 16, 17, 0)),   # sin Merval: de lunes a viernes
    (dt.datetime(2026, 10, 13, 9, 0), {dt.date(2026, 10, 9)}, dt.datetime(2026, 10, 9, 17, 0)),   # el 12 fue feriado
])
def test_el_ultimo_cierre_de_byma(ahora, sesiones, esperado):
    assert fdh.cierre_de_byma(ahora.replace(tzinfo=AR), sesiones) == esperado.replace(tzinfo=AR)


def test_el_chat_y_la_pantalla_eligen_el_mismo_porcentaje():
    # La regla de `pct_segun_via` y la de `pctDeLaTenencia` (utils/fueraDeHorario.js).
    q = {"pct": 0.98, "pct_byma": 3.0}
    assert fdh.pct_segun_via(q, "propio") == 0.98
    assert fdh.pct_segun_via(q, "eeuu") == 3.0
    assert fdh.pct_segun_via(q, "adr") == 3.0
    assert fdh.pct_segun_via({"pct": 0.98}, "eeuu") == 0.98     # no se pidió desde BYMA
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "frontend", "src", "utils", "fueraDeHorario.js")
    js = open(ruta, encoding="utf-8").read()
    assert "ref.via !== 'propio' && q.pct_byma !== undefined ? q.pct_byma : q.pct" in js


def test_el_resumen_del_chat_usa_el_de_byma_para_el_cedear_y_el_de_ny_para_la_accion():
    datos = {"sesion": "post", "byma_abierto": False, "cierra": "22:00",
             "cotizaciones": {"AAPL": {"pct": 1.0, "pct_byma": 3.0, "base": "2026-11-16"}}}
    lotes = [{"asset": "AAPL", "valor": 1000.0, "ref": ("AAPL", "propio")},
             {"asset": "AAPL", "valor": 1000.0, "ref": ("AAPL", "eeuu")}]
    r = fdh.resumen_de_lotes(lotes, datos)
    assert r["usd"] == pytest.approx(10.0 + 30.0)
    por = {a["via"]: a for a in r["activos"]}
    assert por["propio"]["pct"] == 1.0 and por["eeuu"]["pct"] == 3.0


def test_el_mail_mide_el_cedear_desde_el_cierre_de_byma():
    mar = dt.date(2026, 11, 17)
    velas, cierres = VELAS_AAPL_INVIERNO
    velas = velas + [(dt.datetime.combine(mar, dt.time(9, 25), NY), 104.0)]
    cierre = dt.datetime(2026, 11, 16, 17, 0, tzinfo=AR)
    f = fdh.franjas_de_velas(velas, cierres, mar, cierre_byma=cierre)
    assert f["post"]["pct"] == pytest.approx((103 / 102 - 1) * 100, abs=1e-4)
    assert f["post"]["pct_byma"] == pytest.approx(3.0, abs=1e-4)
    assert f["pre"]["pct_byma"] == pytest.approx(4.0, abs=1e-4)
    lotes = [{"asset": "NVDA", "valor": 1000.0, "ref": ("AAPL", "propio")},
             {"asset": "AAPL", "valor": 1000.0, "ref": ("AAPL", "eeuu")}]
    r = fdh.resumen_de_la_manana(lotes, {"AAPL": f}, ahora=dt.datetime(2026, 11, 17, 11, 0, tzinfo=AR))
    assert r["post"]["usd"] == pytest.approx(1000 * (103 / 102 - 1) + 30.0, abs=0.01)
    assert r["pre"]["usd"] == pytest.approx(1000 * (104 / 102 - 1) + 40.0, abs=0.01)



# ── Segunda auditoría (2026-10-15) ───────────────────────────────────────────

def test_brk_punto_b_en_schwab_pide_brk_guion_b():
    assert fdh.referencia_en_eeuu("BRK.B") == ("BRK-B", "propio")
    assert fdh.referencia_en_eeuu("BRK B") == ("BRK-B", "propio")


def test_la_noche_se_nombra_con_el_dia_argentino():
    jueves = "2026-10-15"
    a_las_2330 = dt.datetime(2026, 10, 15, 23, 30, tzinfo=AR)
    a_las_0030 = dt.datetime(2026, 10, 16, 0, 30, tzinfo=AR)
    assert fdh._nombre_de_la_noche(jueves, a_las_2330.date()) == "esta noche"
    assert fdh._nombre_de_la_noche(jueves, a_las_0030.date()) == "anoche"


def test_el_chat_separa_la_accion_de_su_cedear():
    datos = {"sesion": "pre", "byma_abierto": False,
             "cotizaciones": {"AAPL": {"pct": 1.0, "precio": 101.0, "base": "2026-10-14"}}}
    r = fdh.resumen_de_lotes([{"asset": "AAPL", "valor": 1000.0, "ref": ("AAPL", "propio")},
                              {"asset": "AAPL", "valor": 500.0, "ref": ("AAPL", "eeuu")}], datos)
    vias = sorted(a["via"] for a in r["activos"])
    assert vias == ["eeuu", "propio"]


def test_el_endpoint_tiene_un_limite_por_usuario(cliente):
    c, _y = cliente
    import main as _m
    _m._rate_store.clear()
    codigos = [c.get("/api/fuera-de-horario", params={"symbols": "AAPL"}).status_code for _ in range(32)]
    assert codigos[:30] == [200] * 30
    assert 429 in codigos[30:]
    _m._rate_store.clear()
