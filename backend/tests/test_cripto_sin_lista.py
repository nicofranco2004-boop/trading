"""Las criptos que el buscador ofrecía y la lista de cripto no conocía.

Medido el 2026-10-08: el buscador (`frontend/src/utils/tickers.js` CRYPTO) y la
lista del chat (`ai/trade_tickers.py` CRYPTO_TICKERS) dejaban cargar 22 criptos
que NO estaban en `main.CRYPTO_SYMBOLS`. Para la valuación no eran cripto:

  · en una cuenta en pesos se pedía '<X>.BA', que no cotiza en ningún lado;
  · en dólares se pedía el código pelado. Para AR, ENS, FET y QNT eso es una
    ACCIÓN de EE.UU. (Antero Resources US$ 36, EnerSys US$ 178, Forum Energy
    US$ 84, Quantinuum US$ 42): Fetch.ai (US$ 0,21) valía 394 veces más;
  · si el pelado no traía nada, /api/prices probaba '<X>-USD' — y para JUP y ONE
    eso es OTRA moneda ("Jupiter" US$ 0,0003 en vez de US$ 0,34; "BigONE Token"
    en vez de Harmony). La foto diaria y la variación del día no tenían ese
    respaldo: quedaban sin precio.

Cada nombre se buscó en Yahoo (nombre + precio) y se cruzó con CoinGecko.

Corre con: cd backend && python3 -m pytest tests/test_cripto_sin_lista.py
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import io
import os
import re
import sys
from unittest.mock import patch

import pandas as pd
import pytest
import yfinance

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402  (conftest ya seteó DB_PATH temporal)
import snapshots_job             # noqa: E402
from ai import trade_tickers     # noqa: E402
from ai.asset_names import asset_name   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# La cripto opera 7 días y su vela diaria es el día UTC: las fechas salen del
# reloj de verdad, así el número es "de hoy" corra el test el día que corra.
HOY = _dt.datetime.utcnow().date()
AYER = HOY - _dt.timedelta(days=1)
ANTEAYER = HOY - _dt.timedelta(days=2)

# ─── Yahoo, nombre por nombre, como contestaba el 2026-10-08 ────────────────
# {nombre en Yahoo: (cierre del 06/10, del 07/10, del 08/10)}. Un nombre que no
# está acá, Yahoo no lo tiene (tabla vacía) — como 'KAS', 'GMT-USD' o 'RNDR-USD'.
YAHOO = {
    # Kaspa: el nombre limpio es la moneda, el pelado no trae nada.
    "KAS-USD": (0.043216, 0.040525, 0.0381319),
    # Jupiter (Solana) y el homónimo que Yahoo tiene con el nombre limpio.
    "JUP29210-USD": (0.351817, 0.358858, 0.3385),
    "JUP-USD": (0.000321, 0.000303, 0.000301568),         # "Jupiter", otra moneda
    # Harmony y "BigONE Token".
    "ONE3945-USD": (0.002207, 0.002115, 0.00200111),
    "ONE-USD": (0.000394, 0.000425, 0.000436698),         # BigONE Token
    # STEPN, cat in a dogs world, Popcat: el nombre limpio no trae nada.
    "GMT18069-USD": (0.008782, 0.008218, 0.00765),
    "MEW30126-USD": (0.000519, 0.000489, 0.000455892),
    "POPCAT28782-USD": (0.053195, 0.049264, 0.04488),
    # Render: RNDR pasó a RENDER; 'RNDR-USD' no trae nada.
    "RENDER-USD": (2.14269, 2.02497, 1.8079),
    # Las cuatro que con el código pelado son una ACCIÓN de EE.UU.
    "FET-USD": (0.239001, 0.229959, 0.21293),
    "FET": (84.43, 82.3, 83.81),                          # Forum Energy Technologies
    "AR-USD": (4.53767, 4.23468, 3.88177),
    "AR": (35.72, 35.57, 36.255),                         # Antero Resources
    "ENS-USD": (6.75335, 6.48029, 6.088),
    "ENS": (192.49, 182.49, 178.425),                     # EnerSys
    "QNT-USD": (265.476, 252.956, 225.02),
    "QNT": (40.0, 41.0, 41.64),                           # Quantinuum
    # Las que quedan afuera: el código es la acción, y sigue siéndolo.
    "DASH": (193.62, 191.24, 190.95),                     # DoorDash
    "DASH-USD": (55.7564, 53.8678, 49.68),
    "ROSE.BA": (1500.0, 1520.0, 1530.0),                  # Instituto Rosenbusch (BYMA)
    "ROSE-USD": (0.008373, 0.007817, 0.007231),           # Oasis Network
}


class _TickerDeYahoo:
    """`yf.Ticker` con la forma de yfinance. `.history()` → DataFrame con las
    velas diarias (índice con zona horaria); un nombre que Yahoo no tiene →
    DataFrame vacío ("possibly delisted")."""
    pedidos: list = []

    def __init__(self, nombre):
        self.nombre = str(nombre).upper()
        _TickerDeYahoo.pedidos.append(self.nombre)
        velas = YAHOO.get(self.nombre)
        self.fast_info = type("FI", (), {"previous_close": velas[-2] if velas else None,
                                         "last_price": velas[-1] if velas else None})()

    def history(self, *a, **k):
        velas = YAHOO.get(self.nombre)
        if not velas:
            return pd.DataFrame()
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in (ANTEAYER, AYER, HOY)]).tz_localize("UTC")
        return pd.DataFrame({"Open": velas, "High": velas, "Low": velas, "Close": velas,
                             "Volume": [1e6] * 3}, index=idx)


class _Resp:
    def __init__(self, cuerpo, status=200):
        self._cuerpo, self.status_code = cuerpo, status

    def json(self):
        return self._cuerpo


def _vaciar_caches():
    from home import market as hm
    main._PRICE_CACHE.clear()
    main._PRICE_META.clear()
    main._history_cache.clear()
    main._data912_eq_cache.update({"data": None, "ts": 0})
    main._data912_cache.update({"data": None, "ts": 0})
    for c in (main._PREVCLOSE_CACHE, main._PREVCLOSE_RUEDA, main._PREVCLOSE_ULTIMO,
              main._PREVCLOSE_VENCE, hm._QUOTE_CACHE):
        c.clear()


@contextlib.contextmanager
def yahoo():
    """Yahoo contesta por nombre (arriba); data912 y los dólares no tienen nada."""
    _vaciar_caches()
    _TickerDeYahoo.pedidos = []
    with patch.object(yfinance, "Ticker", _TickerDeYahoo), \
         patch("requests.get", side_effect=lambda *a, **k: _Resp([], 404)), \
         patch.object(main, "_fill_last_known_prices"):
        yield _TickerDeYahoo.pedidos
    _vaciar_caches()


def _pct(prev, last):
    return round((last / prev - 1) * 100, 2)


ENTRAN = {"ANKR", "AR", "BOME", "CELO", "ENA", "ENS", "FET", "GMT", "JASMY", "JUP",
          "KAS", "KSM", "MEW", "MINA", "OCEAN", "ONE", "POPCAT", "QNT", "RNDR"}
AFUERA = {"AGIX", "DASH", "ROSE"}


@pytest.fixture
def conn():
    c = main.get_db()
    for t in ("snapshots", "positions", "brokers", "users"):
        c.execute(f"DELETE FROM {t}")
    c.execute("INSERT INTO users (id, email, name, password_hash, approved, tier) "
              "VALUES (1, 'cripto@rendi.test', 'C', 'x', 1, 'plus')")
    for name, ccy in (("IOL", "ARS"), ("Binance", "USDT"), ("Schwab", "USD"),
                      ("Cocos", "ARS")):
        c.execute("INSERT INTO brokers (user_id, name, currency) VALUES (1, ?, ?)", (name, ccy))
    c.commit()
    yield c
    c.close()


def _posicion(c, broker, asset, qty, invested, ccy="USD", asset_type="CRYPTO"):
    c.execute("INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, "
              "quantity, commissions, price_override, currency) VALUES (1,?,?,?,0,?,?,0,NULL,?)",
              (broker, asset, asset_type, invested, qty, ccy))
    c.commit()


# ─── Cuánto pasa en producción: el panel de admin lo mide (Q14) ─────────────

def test_el_panel_cuenta_las_acciones_que_el_arreglo_pasaria_a_cripto(conn):
    """Q14 del panel «Alcance de la auditoría» (admin): sólo agregados. La
    columna que manda es el RIESGO del arreglo: AR/ENS/FET/QNT que no están
    marcadas cripto ni viven en un exchange pueden ser la acción."""
    import alcance_auditoria as alc
    _posicion(conn, "Binance", "FET", 1000, 300)                         # Fetch.ai de verdad
    _posicion(conn, "Schwab", "FET", 10, 800, asset_type="STOCK")        # Forum Energy
    _posicion(conn, "IOL", "AR", 5, 250000, ccy="ARS", asset_type=None)  # sin tipo: no se sabe
    _posicion(conn, "IOL", "KAS", 2000, 120000, ccy="ARS")               # Kaspa en pesos
    _posicion(conn, "Cocos", "ROSE", 100, 90000, ccy="ARS", asset_type="AR_STOCK")  # Rosenbusch
    _posicion(conn, "Binance", "DASH", 2, 100)                           # Dash: queda afuera
    _posicion(conn, "Binance", "BTC", 0.01, 800)                         # no es de la tanda
    q14 = next(h for h in alc.informe(conn)["hallazgos"] if h["id"] == "Q14")
    assert q14["numero"] == 2                              # Forum Energy y el AR sin tipo
    assert q14["veredicto"] == "urgente"
    d = q14["detalle"]
    assert (d["tenencias_que_entran"], d["usuarios_afectados"]) == (4, 1)
    assert d["cripto_valuada_como_accion"] == 1           # el FET de Binance
    assert d["cripto_en_pesos_sin_precio"] == 2           # AR y KAS en IOL
    assert d["criptos_que_quedan_afuera"] == 1            # DASH (la ROSE es Rosenbusch)
    assert set(d["simbolos_en_uso"].split(",")) == {"FET", "AR", "KAS", "DASH"}


# ─── 1. Lo que la app ofrece como cripto, la app lo sabe valuar ─────────────

def _cripto_del_buscador():
    """Los códigos de la lista CRYPTO de frontend/src/utils/tickers.js (el
    buscador del alta manual), leídos del archivo de verdad."""
    src = io.open(os.path.join(REPO, "frontend", "src", "utils", "tickers.js"),
                  encoding="utf-8").read()
    i = src.index("export const CRYPTO = [")
    bloque = src[i:src.index("\n]", i)]
    return set(re.findall(r"\{\s*s:\s*'([^']+)'", bloque))


def test_todo_lo_que_el_buscador_ofrece_como_cripto_esta_en_la_lista():
    """El defecto de fondo: dos listas que no coincidían. Si alguien agrega una
    cripto al buscador o al chat sin agregarla a CRYPTO_SYMBOLS (con su nombre de
    Yahoo), esto se pone rojo."""
    sabe_valuar = main.CRYPTO_SYMBOLS | main.CRIPTO_ESTABLES
    assert _cripto_del_buscador() - sabe_valuar == set()
    assert trade_tickers.CRYPTO_TICKERS - sabe_valuar == set()
    assert ENTRAN <= main.CRYPTO_SYMBOLS


def test_dash_rose_y_agix_no_se_ofrecen_como_cripto():
    """La acción del catálogo manda: DASH es DoorDash, ROSE es Rosenbusch."""
    for s in AFUERA:
        assert s not in main.CRYPTO_SYMBOLS, s
        assert s not in _cripto_del_buscador(), s
        assert s not in trade_tickers.CRYPTO_TICKERS, s
    assert trade_tickers.resolve_asset("DASH") == ("DASH", {"STOCK"})
    assert trade_tickers.resolve_asset("ROSE") == ("ROSE", {"AR_STOCK"})
    assert trade_tickers.resolve_asset("AGIX") == (None, set())


def test_la_voz_nombra_la_accion_y_no_la_cripto():
    """El nombre sale de la primera lista que tiene el código, y la de cripto va
    primero: el que tenía Rosenbusch escuchaba «Oasis Network»."""
    assert asset_name("ROSE") == "Instituto Rosenbusch"
    assert asset_name("DASH") == "DoorDash"
    assert asset_name("FET") == "Fetch.ai"


def test_el_nombre_largo_de_yahoo_pasa_el_validador_y_la_basura_no():
    """Para que entre 'POPCAT28782-USD' el validador acepta hasta 12 caracteres
    antes del sufijo. Lo que frenaba lo sigue frenando."""
    assert main._SYMBOL_RE.match("POPCAT28782-USD")
    for basura in ("FCI:COCOS-AHORRO-A", "BRK B", "ABCDEFGHIJKLM", "AAPL.BAAAA", "BTC-USD-X"):
        assert not main._SYMBOL_RE.match(basura), basura


# ─── 2. Posiciones: el precio y la "Var. día" ───────────────────────────────

def test_posiciones_valua_cada_moneda_y_no_la_accion_ni_el_homonimo(conn):
    pedir = "FET,AR,ENS,QNT,KAS,JUP,ONE,GMT,MEW,POPCAT,RNDR,RENDER"
    with yahoo() as pedidos:
        p = main.get_prices(pedir, 1)
        pc = main.get_prev_close(pedir, 1)
    assert p["FET"] == 0.21293          # antes: 83,81 (Forum Energy) — 394× de más
    assert p["AR"] == 3.88177           # antes: 36,26 (Antero Resources)
    assert p["ENS"] == 6.088            # antes: 178,43 (EnerSys)
    assert p["QNT"] == 225.02           # antes: 41,64 (Quantinuum)
    assert p["KAS"] == 0.0381319
    assert p["JUP"] == 0.3385           # antes: 0,0003 ("Jupiter", otra moneda)
    assert p["ONE"] == 0.00200111       # antes: 0,00044 (BigONE Token)
    assert p["GMT"] == 0.00765          # antes: sin precio
    assert p["MEW"] == 0.000455892
    assert p["POPCAT"] == 0.04488
    assert p["RNDR"] == p["RENDER"] == 1.8079
    assert pc["FET"] == 0.229959 and pc["JUP"] == 0.358858 and pc["KAS"] == 0.040525
    for malo in ("FET", "AR", "ENS", "QNT", "JUP-USD", "ONE-USD", "RNDR-USD"):
        assert malo not in pedidos, malo


def test_lo_que_queda_afuera_se_sigue_valuando_como_la_accion(conn):
    with yahoo():
        p = main.get_prices("DASH,ROSE.BA", 1)
    assert p["DASH"] == 190.95          # DoorDash, como siempre
    assert p["ROSE.BA"] == 1530.0       # Rosenbusch, como siempre


def test_kaspa_en_una_cuenta_en_pesos_se_cotiza_como_cripto(conn):
    """Antes KAS no era cripto para la valuación: en IOL se pedía 'KAS.BA', que
    no cotiza en ningún lado, y la tenencia quedaba al costo."""
    from snapshots_job import build_price_symbols
    _posicion(conn, "IOL", "KAS", 2000, 120000, ccy="ARS")
    pos = [dict(r) for r in conn.execute("SELECT * FROM positions WHERE user_id=1")]
    brk = [dict(r) for r in conn.execute("SELECT * FROM brokers WHERE user_id=1")]
    assert build_price_symbols(pos, brk) == ["KAS"]
    # Y Posiciones, que la pide como 'KAS.BA', recibe el precio en pesos al dólar cripto.
    with yahoo(), patch.object(main, "_current_cripto_rate", return_value=1500.0):
        p = main.get_prices("KAS.BA", 1)
    assert p["KAS.BA"] == pytest.approx(0.0381319 * 1500.0)


# ─── 3. La variación del día y la foto diaria ───────────────────────────────

def test_la_watchlist_tiene_la_variacion_de_fetch_y_jupiter(conn):
    conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (1, 'FET'), (1, 'JUP')")
    conn.commit()
    try:
        with yahoo():
            r = main.watchlist_list(1)
    finally:
        conn.execute("DELETE FROM watchlist")
        conn.commit()
    filas = {it["symbol"]: it for it in r["items"]}
    assert filas["FET"]["price"] == 0.21293
    assert filas["FET"]["change_pct"] == _pct(0.229959, 0.21293)   # no la de Forum Energy
    assert filas["JUP"]["change_pct"] == _pct(0.358858, 0.3385)


def test_la_foto_diaria_valua_cada_moneda_a_su_precio(conn):
    """Los mismos argumentos que el cron (`run_daily_snapshot` → `crypto_yf=CRYPTO_YF`).
    Antes: FET al precio de Forum Energy, JUP y GMT sin precio."""
    _posicion(conn, "Binance", "FET", 1000, 300)
    _posicion(conn, "Binance", "JUP", 500, 200)
    _posicion(conn, "Binance", "GMT", 10000, 100)
    with yahoo() as pedidos:
        with conn:
            r = snapshots_job.take_snapshot_for_user(conn, 1, 1400.0, main.CRYPTO_YF,
                                                     HOY.isoformat(), tc_mep=1400.0)
    assert r["ok"], r
    total = conn.execute("SELECT total_value FROM snapshots WHERE user_id=1").fetchone()[0]
    assert total == pytest.approx(1000 * 0.21293 + 500 * 0.3385 + 10000 * 0.00765, abs=0.01)
    assert "FET" not in pedidos and "JUP" not in pedidos


# ─── 4. El chat ─────────────────────────────────────────────────────────────

def test_el_chat_registra_jupiter_al_precio_de_jupiter(conn):
    with yahoo():
        assert main._trade_market_price("JUP", "CRYPTO", "USD", 1) == 0.3385
        assert main._trade_market_price("FET", "CRYPTO", "USD", 1) == 0.21293
