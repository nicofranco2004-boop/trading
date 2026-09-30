"""El indicador "Abierto / Cerrado" de las secciones de mercado del inicio, y
la tarjeta "subió hoy" de "Lo que te afecta".

La regla de las dos: un número sólo se presenta como "de hoy" si ES de la rueda
de hoy. El horario solo no alcanza — a primera hora, o con los movers guardados
30 minutos, el reloj ya dice "abierto" pero el porcentaje es el de ayer.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main                                  # noqa: E402  (conftest ya seteó DB_PATH temporal)
import alerts_engine as ae                   # noqa: E402
from home import market                      # noqa: E402
from home.briefing import detect_holdings_movers   # noqa: E402

# Martes 29/09/2026 a las 19:00 UTC: 15:00 en Nueva York y 16:00 en Buenos
# Aires — las dos ruedas abiertas.
MARTES_NY_ABIERTO = datetime(2026, 9, 29, 19, 0, tzinfo=timezone.utc)
# El mismo martes a las 22:00 UTC: las dos cerradas.
MARTES_NOCHE = datetime(2026, 9, 29, 22, 0, tzinfo=timezone.utc)
SABADO = datetime(2026, 10, 3, 17, 0, tzinfo=timezone.utc)


def _hoy(monkeypatch, iso="2026-09-29"):
    monkeypatch.setattr(market, "session_today", lambda sym: iso)


def test_abierto_si_esta_en_horario_y_el_numero_es_de_hoy(monkeypatch):
    _hoy(monkeypatch)
    items = [{"symbol": "AAPL", "as_of": "2026-09-29"}]
    assert market.estado_de_rueda(items, MARTES_NY_ABIERTO) == {
        "abierto": True, "en_rueda": 1, "total": 1, "en_horario": True, "rueda": "2026-09-29"}


def test_en_horario_pero_con_los_numeros_de_ayer_no_esta_en_rueda(monkeypatch):
    """El caso que motivó la regla: 09:35 en Nueva York, los movers guardados
    todavía son los de la rueda anterior. Un punto que late ahí mentiría. Pero
    tampoco es "Cerrado": el mercado está en horario (`en_horario`)."""
    _hoy(monkeypatch)
    items = [{"symbol": "AAPL", "as_of": "2026-09-28"}, {"symbol": "MSFT", "as_of": "2026-09-28"}]
    est = market.estado_de_rueda(items, MARTES_NY_ABIERTO)
    assert est["abierto"] is False and est["en_rueda"] == 0
    assert est["en_horario"] is True
    assert est["rueda"] == "2026-09-28"     # el cartel dice de cuándo son


def test_merval_con_la_barra_ba_en_nan_no_dice_cerrado_en_plena_rueda(monkeypatch):
    """La barra `.BA` del día llega en NaN y se descarta: los números son de
    ayer. Con la bolsa porteña abierta, eso es "esperando la rueda de hoy", no
    "Cerrado"."""
    _hoy(monkeypatch)
    est = market.estado_de_rueda([{"symbol": "GGAL.BA", "as_of": "2026-09-28"}], MARTES_NY_ABIERTO)
    assert est["en_horario"] is True and est["abierto"] is False


def test_fuera_de_horario_no_esta_en_rueda_aunque_el_numero_sea_de_hoy(monkeypatch):
    _hoy(monkeypatch)
    est = market.estado_de_rueda([{"symbol": "AAPL", "as_of": "2026-09-29"}], MARTES_NOCHE)
    assert est["abierto"] is False and est["en_horario"] is False


def test_el_fin_de_semana_la_bolsa_esta_cerrada_y_la_cripto_no(monkeypatch):
    _hoy(monkeypatch, "2026-10-03")
    assert market.estado_de_rueda([{"symbol": "AAPL", "as_of": "2026-10-02"}], SABADO)["abierto"] is False
    assert market.estado_de_rueda([{"symbol": "BTC-USD", "as_of": "2026-10-03"}], SABADO)["abierto"] is True


def test_una_cripto_no_pone_en_abierto_una_lista_con_acciones_del_viernes(monkeypatch):
    """Antes bastaba con UNO: la watchlist AAPL + BTC latía "Abierto" un sábado
    al lado del porcentaje del viernes de AAPL. Ahora es "1 de 2 en rueda"."""
    _hoy(monkeypatch, "2026-10-03")
    items = [{"symbol": "AAPL", "as_of": "2026-10-02"}, {"symbol": "BTC-USD", "as_of": "2026-10-03"}]
    est = market.estado_de_rueda(items, SABADO)
    assert est["abierto"] is False
    assert (est["en_rueda"], est["total"]) == (1, 2)
    assert est["rueda"] == "2026-10-03"


def test_sin_fecha_de_rueda_no_se_afirma_nada(monkeypatch):
    _hoy(monkeypatch)
    vacio = {"abierto": False, "en_rueda": 0, "total": 0, "en_horario": True, "rueda": None}
    assert market.estado_de_rueda([{"symbol": "AAPL", "as_of": None}], MARTES_NY_ABIERTO) == vacio
    assert market.estado_de_rueda([], MARTES_NY_ABIERTO)["abierto"] is False


def test_mercado_de_cada_simbolo():
    assert market.mercado_de("AAPL") == "us"
    assert market.mercado_de("GGAL.BA") == "byma"
    assert market.mercado_de("BTC-USD") == "cripto"
    assert market.mercado_de("BTC") == "cripto"


def test_el_horario_por_mercado_es_el_mismo_reloj_de_las_alertas():
    """Una sola definición del horario: la unión de las dos ruedas es lo que
    usan las alertas para decidir si disparan."""
    for t in (MARTES_NY_ABIERTO, MARTES_NOCHE, SABADO,
              datetime(2026, 9, 29, 13, 1, tzinfo=timezone.utc),
              datetime(2026, 9, 29, 14, 5, tzinfo=timezone.utc)):
        assert ae._market_open_now(t) == (ae.rueda_en_horario("us", t) or ae.rueda_en_horario("byma", t))
    # BYMA 11–17 ART: a las 13:01 UTC (10:01 ART) todavía no abrió.
    assert ae.rueda_en_horario("byma", datetime(2026, 9, 29, 13, 1, tzinfo=timezone.utc)) is False
    assert ae.rueda_en_horario("byma", datetime(2026, 9, 29, 14, 5, tzinfo=timezone.utc)) is True
    assert ae.rueda_en_horario("cripto", SABADO) is True


# ─── El endpoint de movers ──────────────────────────────────────────────────

def test_movers_trae_el_estado_y_no_lo_escribe_en_la_copia_guardada(monkeypatch):
    guardado = {
        "gainers": [{"symbol": "AAPL", "change_pct": 2.0, "as_of": "2026-09-29"}],
        "losers": [{"symbol": "MSFT", "change_pct": -1.0, "as_of": "2026-09-29"}],
        "actualizado": "2026-09-29T18:40:00Z",
    }
    monkeypatch.setattr(main, "get_movers", lambda m: guardado)
    monkeypatch.setattr(main, "estado_de_rueda", lambda items: {"abierto": True, "rueda": "2026-09-29"})
    r = main.home_movers("sp500", uid=1)
    assert r["abierto"] is True and r["rueda"] == "2026-09-29"
    assert r["actualizado"] == "2026-09-29T18:40:00Z"
    # El objeto guardado por `_cached` quedó como estaba: el próximo pedido
    # calcula el estado de nuevo, a su hora.
    assert "abierto" not in guardado


def test_build_movers_anota_la_rueda_y_la_hora_del_pedido(monkeypatch):
    monkeypatch.setattr(market, "_fetch_batch_quotes", lambda syms: {
        "AAPL": {"price": 200.0, "change_pct": 1.2, "as_of": "2026-09-29"},
        "MSFT": {"price": 400.0, "change_pct": -0.4, "as_of": "2026-09-29"},
    })
    out = market._build_movers("sp500")
    assert out["gainers"][0]["as_of"] == "2026-09-29"
    assert out["actualizado"].endswith("Z")


# ─── "subió hoy" ────────────────────────────────────────────────────────────

def test_la_tarjeta_dice_hoy_solo_si_el_movimiento_es_de_hoy():
    hoy = detect_holdings_movers([{"asset": "META", "price": 738.79, "change_pct": 3.2,
                                   "is_today": True, "as_of": "2026-09-29"}])
    assert hoy[0].headline == "META subió hoy"
    ayer = detect_holdings_movers([{"asset": "META", "price": 738.79, "change_pct": 3.2,
                                    "is_today": False, "as_of": "2026-09-25"}])
    assert ayer[0].headline == "META subió el 25/09"
    sin_fecha = detect_holdings_movers([{"asset": "NFLX", "price": 70.3, "change_pct": -1.6}])
    assert sin_fecha[0].headline == "NFLX bajó en la última rueda"


def test_la_tarjeta_trae_el_numero_para_animarlo():
    c = detect_holdings_movers([{"asset": "META", "price": 738.79, "change_pct": 3.24,
                                 "is_today": True, "as_of": "2026-09-29"}])[0]
    assert c.value == "+3,2%"
    assert c.value_num == 3.2


# ─── El refresco de noticias en segundo plano ──────────────────────────────

def test_el_refresco_de_noticias_no_abre_un_hilo_por_pedido(monkeypatch):
    """El inicio pide noticias cada 5 min por pestaña. Dos pedidos seguidos del
    mismo lote arrancan UN refresco, no dos."""
    import threading
    corridas = []
    listo = threading.Event()

    def lento(specs, ttl):
        corridas.append(specs)
        listo.wait(2)

    monkeypatch.setattr(main, "_ensure_news_batch_parallel", lento)
    monkeypatch.setattr(main, "_NEWS_REFRESH_ULTIMO", {})
    monkeypatch.setattr(main, "_NEWS_REFRESH_EN_CURSO", set())
    specs = [("fed", "es", "market")]
    main._refresh_news_in_background(specs, 60)
    main._refresh_news_in_background(specs, 60)      # mientras el primero corre
    listo.set()
    import time as _t
    _t.sleep(0.2)
    main._refresh_news_in_background(specs, 60)      # terminó, pero hace < 1 min
    assert len(corridas) == 1
    # Otro lote (las noticias de la cartera de otro usuario) no espera al primero.
    main._refresh_news_in_background([("GGAL acciones", "es", "portfolio")], 60)
    _t.sleep(0.2)
    assert len(corridas) == 2


def test_la_memoria_del_refresco_de_noticias_no_crece_sin_limite(monkeypatch):
    """Cada cartera distinta es una clave: sin poda, el proceso acumulaba una
    por usuario durante semanas."""
    monkeypatch.setattr(main, "_ensure_news_batch_parallel", lambda specs, ttl: None)
    viejo = {("q%d" % i,): 0.0 for i in range(500)}           # todos ya pasaron la pausa
    monkeypatch.setattr(main, "_NEWS_REFRESH_ULTIMO", viejo)
    monkeypatch.setattr(main, "_NEWS_REFRESH_EN_CURSO", set())
    main._refresh_news_in_background([("nueva", "es", "portfolio")], 60)
    assert len(main._NEWS_REFRESH_ULTIMO) == 1
