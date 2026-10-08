"""La variación del día de un activo sale de UN solo lugar.

Hasta 2026-10-08 había dos:

  1. `main._prev_close_con_rueda` (/api/prices/prev-close): data912 —el feed de
     BYMA, la MISMA fila que el precio— para los `.BA` y los bonos, yfinance para
     EEUU y cripto. La columna "Var. día" de Posiciones y el chat.
  2. `home.market._fetch_batch_quotes`: yfinance para TODO, también los `.BA`.
     Las alertas de % del día, «Lo que te afecta», la watchlist, los mapas y
     movers del inicio y Mervall-E en el inicio.

yfinance trae la vela del día de los `.BA` en NaN o el ticker congelado (ver
`_fetch_data912_equities`), así que la misma acción tenía una variación en
Posiciones y otra en las alertas. Y los bonos no tenían ninguna fuera de
Posiciones (yfinance no los cotiza).

Ahora la 2 le pide a `main._variacion_del_dia`, que sale de la 1. Estas pruebas
entran por las funciones que usa producción (los endpoints, el motor de
alertas) y simulan la red en el BORDE, con la forma cruda de cada proveedor:
las filas de data912 como las manda su servidor (`symbol`, `c`, `pct_change`;
velas con `date`, `c`, `dr`) y la tabla de yfinance como la devuelve
`yf.download` (columnas ("Close", ticker)).

El caso de las 9:32, MEDIDO el 2026-10-08: BYMA abre a las 11:00 y el feed ya
mostraba AAPL +1,04 % — que era la rueda del 7. Ese número no puede llegar como
"de hoy" a ningún lado (el guard `is_today` de las alertas).

Corre con: cd backend && python3 -m pytest tests/test_variacion_una_fuente.py
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402  (conftest ya seteó DB_PATH temporal)
main._fetch_prev_close_one_real = main._fetch_prev_close_one
import alerts_engine as ae       # noqa: E402
from home import market as hm    # noqa: E402

HOY = "2026-10-08"        # jueves
AYER = "2026-10-07"
ANTEAYER = "2026-10-06"
# La hora argentina de cada escenario: `_rueda_byma` no acepta "hoy" antes de
# las 11:00 (el reloj puede vetarlo, nunca afirmarlo).
A_LAS_932 = _dt.datetime(2026, 10, 8, 9, 32)
A_LAS_14 = _dt.datetime(2026, 10, 8, 14, 0)

# ─── El mundo, con la forma cruda de cada proveedor ─────────────────────────

# Feed live de data912 a las 9:32 (medido): idéntico a las velas del 7. `v` es
# el volumen operado HOY (todavía no abrió: 0).
LIVE_0932 = {
    "arg_cedears": [{"symbol": "AAPL", "c": 27100.0, "pct_change": 1.04, "px_bid": 27050.0, "v": 0.0, "q_op": 12.0},
                    {"symbol": "SPY", "c": 20900.0, "pct_change": -0.19, "px_bid": 20880.0, "v": 0.0, "q_op": 30.0},
                    {"symbol": "CX", "c": 15520.0, "pct_change": -3.48, "px_bid": 15500.0, "v": 0.0, "q_op": 8.0}],
    "arg_stocks": [{"symbol": "GGAL", "c": 6000.0, "pct_change": -2.10, "px_bid": 5990.0, "v": 0.0, "q_op": 40.0}],
    "arg_bonds": [{"symbol": "AL30", "c": 85800.0, "pct_change": -0.05, "v": 0.0},
                  {"symbol": "AL30D", "c": 61.20, "pct_change": -0.12, "v": 0.0}],
    "arg_corp": [],
}
# La misma hora con la rueda del 8 ya abierta. CX todavía no operó: trae el
# precio y el % del 7, idénticos a su vela (MEDIDO 2026-10-08 11:53).
LIVE_ABIERTA = {
    "arg_cedears": [{"symbol": "AAPL", "c": 27300.0, "pct_change": 0.74, "px_bid": 27280.0, "v": 3.1e8, "q_op": 12.0},
                    {"symbol": "SPY", "c": 20950.0, "pct_change": 0.24, "px_bid": 20940.0, "v": 9.5e8, "q_op": 30.0},
                    {"symbol": "CX", "c": 15520.0, "pct_change": -3.48, "px_bid": 15500.0, "v": 0.0, "q_op": 8.0}],
    "arg_stocks": [{"symbol": "GGAL", "c": 5850.0, "pct_change": -2.50, "px_bid": 5840.0, "v": 2.2e9, "q_op": 40.0}],
    "arg_bonds": [{"symbol": "AL30", "c": 86200.0, "pct_change": 0.47, "v": 7.4e9},
                  {"symbol": "AL30D", "c": 61.38, "pct_change": 0.30, "v": 1.1e6},
                  {"symbol": "BAM27", "c": 1.02, "pct_change": -0.64, "v": 0.0},
                  {"symbol": "BAM27D", "c": 1.01, "pct_change": -0.64, "v": 0.0}],
    "arg_corp": [],
}
# Última vela histórica de data912 de las referencias con que se fecha la rueda.
VELAS_DEL_7 = {
    "cedears/SPY": [{"date": AYER, "o": 20920.0, "c": 20900.0, "v": 1e6, "dr": -0.0019}],
    "bonds/AL30": [{"date": AYER, "o": 85900.0, "c": 85800.0, "v": 1e9, "dr": -0.0005}],
}


def _tabla_yahoo(cierres: dict, fechas: list) -> pd.DataFrame:
    """La forma de `yf.download(..., group_by='column')`: columnas (dato, ticker)."""
    cols = pd.MultiIndex.from_tuples([("Close", t) for t in cierres], names=["Price", "Ticker"])
    return pd.DataFrame(list(zip(*cierres.values())), index=pd.to_datetime(fechas), columns=cols)


# yfinance: lo que trae para los `.BA` es justamente lo que no hay que creer.
# AAPL.BA con la vela del 8 en NaN y un +5 % entre el 6 y el 7 que no existió en
# BYMA; GGAL (sin sufijo) es el ADR de Nueva York, +5 % el 8.
YAHOO = _tabla_yahoo({
    "AAPL.BA": [25000.0, 26250.0, np.nan],
    "GGAL.BA": [6200.0, 6510.0, np.nan],
    "GGAL": [40.0, 40.0, 42.0],
    "MSFT": [580.0, 590.0, 600.0],
    "BAC": [40.0, 40.0, 41.0],
}, [ANTEAYER, AYER, HOY])


class _Resp:
    def __init__(self, cuerpo, status=200):
        self._cuerpo, self.status_code = cuerpo, status

    def json(self):
        return self._cuerpo


def _servidor(live: dict):
    """`requests.get` de mentira: sirve data912 con la forma de su API."""
    def get(url, *a, **k):
        if "data912.com/live/" in url:
            return _Resp(live.get(url.rsplit("/", 1)[1], []))
        if "data912.com/historical/" in url:
            clave = url.split("/historical/", 1)[1]
            return _Resp(VELAS_DEL_7.get(clave, []))
        return _Resp([], 404)        # ArgentinaDatos y cualquier otra cosa: no hay
    return get


def _vaciar_caches():
    main._data912_eq_cache.update({"data": None, "ts": 0})
    main._data912_cache.update({"data": None, "ts": 0})
    main._data912_bonds_pct.clear()
    main._ad_letras_cache.update({"data": None, "ts": 0})
    main._RUEDA_BYMA_HIST.update({"ts": 0, "ultimas": {}})
    for c in (main._PREVCLOSE_CACHE, main._PREVCLOSE_RUEDA, main._PREVCLOSE_ULTIMO,
              hm._QUOTE_CACHE):
        c.clear()


@contextlib.contextmanager
def mundo(live=LIVE_ABIERTA, yahoo=YAHOO, ahora=None):
    _vaciar_caches()
    ahora = ahora or (A_LAS_932 if live is LIVE_0932 else A_LAS_14)
    with patch("requests.get", side_effect=_servidor(live)), \
         patch("fechas.hoy_art", return_value=HOY), \
         patch("fechas.ahora_art", return_value=ahora), \
         patch.object(main._yahoo, "descargar", side_effect=lambda *a, **k: yahoo), \
         patch.object(main, "_fetch_prev_close_one", return_value=None), \
         patch.object(main, "_fetch_one", return_value=None), \
         patch.object(main, "_prices_cache_get", side_effect=lambda s: ({}, list(s))), \
         patch.object(main, "_prices_cache_set"), \
         patch.object(main, "_fill_last_known_prices"):
        yield
    _vaciar_caches()


@pytest.fixture
def conn():
    c = main.get_db()
    for t in ("alert_symbol_state", "alert_events", "alerts", "watchlist",
              "positions", "brokers", "users"):
        c.execute(f"DELETE FROM {t}")
    c.execute("INSERT INTO users (id, email, name, password_hash, approved) "
              "VALUES (1, 'var@rendi.test', 'V', 'x', 1)")
    for name, ccy in (("IOL", "ARS"), ("Schwab", "USD")):
        c.execute("INSERT INTO brokers (user_id, name, currency) VALUES (1, ?, ?)", (name, ccy))
    c.commit()
    yield c
    c.close()


def _posicion(c, broker, asset, asset_type, qty, invested, ccy):
    c.execute("INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, "
              "quantity, commissions, price_override, currency) VALUES (1,?,?,?,0,?,?,0,NULL,?)",
              (broker, asset, asset_type, invested, qty, ccy))
    c.commit()


def _var_de_posiciones(simbolo: str, uid: int = 1) -> float:
    """La cuenta de la columna "Var. día" (Positions.jsx dayVarOf): el precio de
    /api/prices contra el cierre de /api/prices/prev-close."""
    precio = main.get_prices(simbolo, uid)[simbolo]
    previo = main.get_prev_close(simbolo, uid)[simbolo]
    return round((precio / previo - 1) * 100, 2)


# ─── 1. El mismo número que Posiciones ──────────────────────────────────────

def test_el_cedear_tiene_la_variacion_de_posiciones_y_no_la_de_yfinance(conn):
    with mundo():
        q = hm._fetch_batch_quotes(["AAPL.BA"])["AAPL.BA"]
        en_posiciones = _var_de_posiciones("AAPL.BA")
    assert q["change_pct"] == en_posiciones == 0.74
    assert q["price"] == 27300.0
    # Lo que daba antes, leyendo yfinance: el +5 % fantasma del 7.
    assert q["change_pct"] != 5.0
    assert (q["as_of"], q["is_today"]) == (HOY, True)


def test_la_accion_de_eeuu_sigue_saliendo_de_yfinance_con_su_fecha(conn):
    with mundo():
        q = hm._fetch_batch_quotes(["MSFT"])["MSFT"]
        en_posiciones = _var_de_posiciones("MSFT")
    assert q["change_pct"] == en_posiciones == round((600 / 590 - 1) * 100, 2)
    assert (q["mercado"], q["as_of"], q["is_today"]) == ("eeuu", HOY, True)


# ─── 2. Antes de las 11: la rueda de AYER, y lo dice ────────────────────────

def test_a_las_932_el_porcentaje_de_byma_es_de_ayer(conn):
    with mundo(live=LIVE_0932):
        q = hm._fetch_batch_quotes(["AAPL.BA"])["AAPL.BA"]
    assert q["change_pct"] == 1.04           # el número que mostraba el feed…
    assert q["as_of"] == AYER                # …es la rueda del 7…
    assert q["is_today"] is False            # …y no se hace pasar por hoy


def test_sin_con_que_fechar_la_rueda_de_byma_no_es_hoy(conn):
    """Sin velas históricas no se sabe de qué rueda es: "no sé" ≠ "hoy"."""
    with mundo(), patch.dict(VELAS_DEL_7, {}, clear=True):
        q = hm._fetch_batch_quotes(["AAPL.BA"])["AAPL.BA"]
    assert q["change_pct"] == 0.74
    assert (q["as_of"], q["is_today"]) == (None, False)


# ─── 3. Los lectores, por su camino de producción ───────────────────────────

def test_la_watchlist_ahora_tiene_la_variacion_de_los_bonos(conn):
    """AL30 en la watchlist de un broker en dólares: AL30D, de la misma fila de
    data912 que su precio. Antes yfinance no lo tenía y la fila iba sin %."""
    conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (1, 'AL30'), (1, 'GGAL.BA')")
    conn.commit()
    with mundo():
        r = main.watchlist_list(1)
    filas = {it["symbol"]: it for it in r["items"]}
    assert filas["AL30"]["change_pct"] == 0.30
    assert filas["AL30"]["as_of"] == HOY
    assert filas["GGAL.BA"]["change_pct"] == -2.50
    assert filas["GGAL.BA"]["price"] == 5850.0


def test_lo_que_te_afecta_usa_el_simbolo_con_que_se_valua_la_tenencia(conn):
    """GGAL comprada en pesos (IOL) es la de BYMA. Antes se pedía "GGAL" pelado
    y la tarjeta decía "GGAL subió +5 %" con el ADR de Nueva York, en "US$"."""
    _posicion(conn, "IOL", "GGAL", "stock", 100, 600_000, "ARS")
    _posicion(conn, "Schwab", "MSFT", "stock", 10, 5000, "USD")
    with mundo():
        cards = main.home_personal(1)["cards"]
    ggal = next(c for c in cards if c["headline"].startswith("GGAL"))
    assert ggal["headline"] == "GGAL bajó hoy"
    assert ggal["value"] == "-2,5%"
    assert ggal["context"] == "$5.850"


def test_lo_que_te_afecta_a_las_932_no_dice_hoy(conn):
    _posicion(conn, "IOL", "GGAL", "stock", 100, 600_000, "ARS")
    with mundo(live=LIVE_0932):
        cards = main.home_personal(1)["cards"]
    ggal = next(c for c in cards if c["headline"].startswith("GGAL"))
    assert ggal["headline"] == "GGAL bajó el 07/10"


def test_el_movers_del_merval_sale_de_byma(conn):
    with mundo():
        movers = hm._build_movers("merval")
    ggal = next(m for m in movers["losers"] if m["symbol"] == "GGAL.BA")
    assert (ggal["change_pct"], ggal["as_of"]) == (-2.50, HOY)


def _alerta_de_cartera(c, down_pct):
    c.execute("""INSERT INTO alerts (user_id, kind, symbol, scope, direction, threshold,
                 up_pct, down_pct, currency, baseline, channel, repeat, cooldown_min, armed, active)
                 VALUES (1, 'pct_move', NULL, 'holdings', 'either', NULL, NULL, ?, 'USD',
                         'prev_close', 'push', 'always', 360, 1, 1)""", (down_pct,))
    c.commit()


def test_la_alerta_de_cartera_no_dispara_con_la_rueda_de_ayer_y_si_con_la_de_hoy(conn):
    """El motor entero: tenencias → símbolos de valuación → variación del día →
    guard `is_today`. A las 9:32 GGAL marca −2,10 % (el 7): ni dispara ni
    re-arma. Con la rueda abierta marca −2,50 % (el 8): dispara una vez."""
    _posicion(conn, "IOL", "GGAL", "stock", 100, 600_000, "ARS")
    _alerta_de_cartera(conn, down_pct=2)
    with patch.object(ae, "_deliver", lambda *a, **k: (True, False)), \
         patch.object(ae, "_market_open_now", lambda now: True):
        with mundo(live=LIVE_0932):
            assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
        with mundo(live=LIVE_ABIERTA):
            assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    ev = conn.execute("SELECT symbol, message FROM alert_events").fetchall()
    assert [(e["symbol"], e["message"]) for e in ev] == [("GGAL.BA", "GGAL cayó 2,5% hoy")]


# ─── 4. Sin usuario (alertas): el dólar se cancela ──────────────────────────

def test_el_cedear_cotizado_en_dolares_sin_usuario_tiene_la_variacion_del_subyacente(conn):
    """BAC.BA se valúa con BAC × CCL ÷ ratio. Las alertas corren para todos a la
    vez (sin uid): el CCL sale del caché, y como multiplica al precio y al
    cierre en la misma pasada, el porcentaje es el de BAC."""
    with mundo(), patch.object(main, "_current_ccl", return_value=1500.0):
        q = main._variacion_del_dia(["BAC.BA"])["BAC.BA"]
    assert q["change_pct"] == 2.5
    assert q["price"] == round(41.0 * 1500.0 / main.CEDEAR_USD_RATIOS["BAC"], 6)


def test_sin_dolar_no_hay_precio_en_pesos(conn):
    with mundo(), patch.object(main, "_current_ccl", return_value=None):
        assert "BAC.BA" not in main._variacion_del_dia(["BAC.BA"])


# ─── 5. Qué día es "hoy" lo decide el mercado que midió ─────────────────────

def test_la_cripto_en_un_broker_en_pesos_es_de_hoy_por_el_dia_utc():
    """BTC.BA se mide con la vela UTC de BTC-USD. A las 22:00 de Buenos Aires
    esa vela ya es la del día siguiente: sigue siendo "hoy"."""
    import datetime as _dt
    utc = _dt.datetime.utcnow().date().isoformat()
    ayer_art = (_dt.date.fromisoformat(utc) - _dt.timedelta(days=1)).isoformat()
    with patch("fechas.hoy_art", return_value=ayer_art):
        q = hm._stamp_session({"as_of": utc, "mercado": "cripto"}, "BTC.BA")
    assert q["is_today"] is True


def test_un_fondo_no_tiene_variacion_en_la_rueda(conn):
    with mundo():
        assert main._variacion_del_dia(["FCI:ALGUNO"]) == {}


def test_con_el_historico_caido_no_se_le_pregunta_en_cada_pedido(conn):
    """Sin velas no hay fecha (→ no es hoy). Y no se reintenta en cada pedido:
    cada intento puede esperar hasta 6 s, y ahora de acá comen la watchlist, el
    inicio y las alertas."""
    pedidos = []
    servir = _servidor(LIVE_ABIERTA)

    def contar(url, *a, **k):
        if "/historical/" in url:
            pedidos.append(url)
            return _Resp([], 503)
        return servir(url, *a, **k)

    with mundo():
        with patch("requests.get", side_effect=contar):
            primero = main._variacion_del_dia(["AAPL.BA"])["AAPL.BA"]
            hm._QUOTE_CACHE.clear()
            segundo = main._variacion_del_dia(["AAPL.BA"])["AAPL.BA"]
    assert primero["as_of"] is None and segundo["as_of"] is None
    assert len(pedidos) == 2              # AL30 y SPY, una sola vez


def test_con_data912_y_argentinadatos_caidos_no_se_repite_el_pedido_por_cada_accion(conn):
    """MEDIDO 2026-10-08: con las dos fuentes caídas, un refresco del mapa del
    Merval (25 acciones) disparaba 125 pedidos de hasta 8 s cada uno — cada
    símbolo volvía a preguntar. Ahora la caída queda anotada 20 s."""
    pedidos = []

    def caido(url, *a, **k):
        pedidos.append(url)
        return _Resp([], 503)

    with mundo(yahoo=pd.DataFrame()), patch("requests.get", side_effect=caido):
        hm._build_movers("merval")
        hm._QUOTE_CACHE.clear()
        hm._build_movers("merval")          # el segundo, dentro del minuto
    assert len([u for u in pedidos if "data912.com/live/" in u]) == 4
    assert len([u for u in pedidos if "argentinadatos" in u]) == 1


def test_las_alertas_con_el_dolar_frio_no_le_dejan_un_hueco_a_posiciones(conn):
    """Las alertas corren sin usuario: con el caché del dólar frío, BAC.BA (un
    CEDEAR cotizado en USD) no tiene precio en pesos. Ese "no hay" se guardaba
    en el caché que comparte Posiciones, y la columna mostraba "—" 10 minutos
    aunque con su usuario sí lo resolvía."""
    with mundo(), patch.object(main, "_current_ccl", return_value=None):
        assert "BAC.BA" not in main._variacion_del_dia(["BAC.BA"])
        with patch.object(main, "_display_ccl", return_value=1500.0):
            cierre = main.get_prev_close("BAC.BA", 1)["BAC.BA"]
    assert cierre == round(40.0 * 1500.0 / main.CEDEAR_USD_RATIOS["BAC"], 4)


# ─── 6. Un papel que hoy no operó trae el número de su última rueda ─────────

def test_el_cedear_que_hoy_no_opero_no_dice_hoy(conn):
    """CX con la rueda abierta y volumen 0: −3,48 % es lo del 7. Con la fecha
    del mercado (SPY ya operó: "hoy") salía como movimiento de hoy."""
    with mundo():
        q = hm._fetch_batch_quotes(["CX.BA", "AAPL.BA"])
    assert q["CX.BA"]["change_pct"] == -3.48
    assert (q["CX.BA"]["as_of"], q["CX.BA"]["is_today"]) == (None, False)
    assert (q["AAPL.BA"]["as_of"], q["AAPL.BA"]["is_today"]) == (HOY, True)   # el control


def test_la_on_que_hoy_no_opero_tampoco(conn):
    with mundo():
        q = main._variacion_del_dia(["BAM27", "AL30"])
    assert q["BAM27"]["as_of"] is None
    assert q["AL30"]["as_of"] == HOY


def test_la_alerta_no_dispara_con_el_cedear_que_hoy_no_opero(conn):
    """El motor entero: tenencia de CX en pesos, alerta de −3 % en la cartera.
    Con la rueda abierta y CX sin operar, el −3,48 % de ayer no dispara."""
    _posicion(conn, "IOL", "CX", "cedear", 50, 700_000, "ARS")
    _alerta_de_cartera(conn, down_pct=3)
    with patch.object(ae, "_deliver", lambda *a, **k: (True, False)), \
         patch.object(ae, "_market_open_now", lambda now: True), mundo():
        assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0


def test_antes_de_abrir_el_volumen_cero_no_cambia_nada(conn):
    """A las 9:32 todo tiene volumen 0 y la rueda del mercado ya es la del 7:
    el volumen sólo importa cuando la rueda es la de hoy."""
    with mundo(live=LIVE_0932):
        q = hm._fetch_batch_quotes(["AAPL.BA"])["AAPL.BA"]
    assert (q["as_of"], q["is_today"]) == (AYER, False)


def test_la_marca_de_caida_ahorra_el_pedido_pero_no_cambia_la_respuesta():
    """Cada lector ya decidía qué devolver al fallar (con error del servidor:
    nada, y Posiciones cae a Yahoo; con la conexión cortada: la última lectura).
    Mientras dura la marca se devuelve exactamente eso."""
    _vaciar_caches()
    main._data912_eq_cache.update({"data": {"AAPL": {"c": 1.0, "pct": 0.0}}, "ts": 0})
    pedidos = []

    def error_del_servidor(url, *a, **k):
        pedidos.append(url)
        return _Resp([], 503)

    with patch("requests.get", side_effect=error_del_servidor):
        assert main._fetch_data912_equities() == {}
        assert main._fetch_data912_equities() == {}
    assert len(pedidos) == 2                 # los dos endpoints, una sola vez

    main._FUENTE_CAIDA.clear()

    def sin_conexion(url, *a, **k):
        pedidos.append(url)
        raise ConnectionError("sin red")

    with patch("requests.get", side_effect=sin_conexion):
        assert main._fetch_data912_equities() == {"AAPL": {"c": 1.0, "pct": 0.0}}
        assert main._fetch_data912_equities() == {"AAPL": {"c": 1.0, "pct": 0.0}}
    assert len(pedidos) == 3
    _vaciar_caches()


# ─── 7. Yahoo no devolvió una columna del lote ──────────────────────────────

class _TickerFalso:
    """`yf.Ticker` con la forma de yfinance: `.history()` → DataFrame con
    "Close" por fecha; `.fast_info` con previous_close / last_price."""
    def __init__(self, serie, prev=None, last=None):
        self._serie = serie
        self.fast_info = type("FI", (), {"previous_close": prev, "last_price": last})()

    def history(self, **k):
        return pd.DataFrame({"Close": list(self._serie.values())},
                            index=pd.to_datetime(list(self._serie.keys())))


def test_si_yahoo_no_devuelve_la_columna_la_cripto_sigue_teniendo_fecha(conn):
    """MEDIDO 2026-10-08 12:05: en un lote mezclado Yahoo no devolvió BTC-USD y
    el respaldo de a uno (fast_info) no trae fecha → "no es de hoy" → la alerta
    de BTC no disparaba. El respaldo pide primero la serie, que sí la trae."""
    tickers = {"BTC-USD": _TickerFalso({AYER: 83275.93, HOY: 82483.26})}
    sin_btc = _tabla_yahoo({"MSFT": [580.0, 590.0, 600.0]}, [ANTEAYER, AYER, HOY])
    with mundo(yahoo=sin_btc), \
         patch.object(main, "_fetch_prev_close_one", main.__dict__["_fetch_prev_close_one_real"]), \
         patch.object(main.yf, "Ticker", side_effect=lambda t: tickers[t]):
        q = hm._fetch_batch_quotes(["BTC", "MSFT"])
    assert q["BTC"]["change_pct"] == round((82483.26 / 83275.93 - 1) * 100, 2)
    assert (q["BTC"]["mercado"], q["BTC"]["as_of"]) == ("cripto", HOY)
    assert q["MSFT"]["as_of"] == HOY


def test_el_cedear_iliquido_sin_serie_cae_a_fast_info_sin_fecha(conn):
    """COIN.BA: la serie trae sólo la vela de hoy. fast_info tiene el cierre
    anterior, pero no dice de qué día: el número sale, sin "hoy"."""
    tickers = {"COIN.BA": _TickerFalso({HOY: 30000.0}, prev=29000.0, last=30000.0)}
    with mundo(yahoo=pd.DataFrame()), \
         patch.object(main, "_fetch_prev_close_one", main.__dict__["_fetch_prev_close_one_real"]), \
         patch.object(main.yf, "Ticker", side_effect=lambda t: tickers[t]):
        q = main._variacion_del_dia(["COIN.BA"])["COIN.BA"]
    assert q["change_pct"] == round((30000 / 29000 - 1) * 100, 2)
    assert q["as_of"] is None


def test_pasado_el_freno_se_vuelve_a_probar_byma():
    """El freno es corto: mientras dura, Posiciones también toma los `.BA` de
    Yahoo. Pasado el plazo, el pedido siguiente vuelve a preguntarle a data912."""
    _vaciar_caches()
    pedidos = []

    def caido(url, *a, **k):
        pedidos.append(url)
        return _Resp([], 503)

    with patch("requests.get", side_effect=caido):
        main._fetch_data912_equities()
        main._fetch_data912_equities()
        assert len(pedidos) == 2
        cuando, resp = main._FUENTE_CAIDA["data912_acciones"]
        main._FUENTE_CAIDA["data912_acciones"] = (cuando - main._FUENTE_REINTENTO_S - 1, resp)
        main._fetch_data912_equities()
    assert len(pedidos) == 4
    assert main._FUENTE_REINTENTO_S <= 30
    _vaciar_caches()


# ─── 8. El caché que comparte con Posiciones ────────────────────────────────

def test_un_refresco_sin_respuesta_de_yahoo_no_le_borra_el_cierre_a_posiciones(conn):
    """Escenario medido por la revisión del 2026-10-08: Posiciones lee MSFT
    (cierre 590). Pasa un minuto —para la variación del día el dato ya venció,
    para la pantalla no— y el refresco del inicio no recibe respuesta de Yahoo.
    Guardaba "no hay cierre" encima del bueno: Posiciones mostraba "—" hasta
    10 minutos."""
    with mundo():
        assert main.get_prev_close("MSFT", 1)["MSFT"] == 590.0
        ts, valor = main._PREVCLOSE_CACHE["MSFT"]
        main._PREVCLOSE_CACHE["MSFT"] = (ts - 61, valor)
        with patch.object(main._yahoo, "descargar", return_value=pd.DataFrame()):
            assert "MSFT" not in main._variacion_del_dia(["MSFT"])
            assert main.get_prev_close("MSFT", 1)["MSFT"] == 590.0


def test_vencido_para_la_pantalla_el_no_hay_se_guarda_como_antes(conn):
    """El arreglo de arriba no puede convertirse en reintentar en cada pedido un
    símbolo que no tiene cierre: con el bueno vencido, el "no hay" se guarda."""
    with mundo():
        main.get_prev_close("MSFT", 1)
        ts, valor = main._PREVCLOSE_CACHE["MSFT"]
        main._PREVCLOSE_CACHE["MSFT"] = (ts - main._PREVCLOSE_CACHE_TTL_S - 1, valor)
        with patch.object(main._yahoo, "descargar", return_value=pd.DataFrame()):
            assert main.get_prev_close("MSFT", 1)["MSFT"] is None
        assert main._PREVCLOSE_CACHE["MSFT"][1] is None
