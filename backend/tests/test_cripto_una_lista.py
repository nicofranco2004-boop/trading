"""Qué es cripto, y con qué nombre se le pide a Yahoo, sale de UNA lista.

Hasta 2026-10-08 había dos:

  1. `main.CRYPTO_SYMBOLS` / `CRYPTO_YF`: Posiciones (/api/prices y
     /api/prices/prev-close), la variación del día, la foto diaria, las alertas y
     el chat.
  2. `home.market._CRYPTO_TICKERS`: una copia que no coincidía (tenía TON, ICP,
     USDT y USDC; le faltaban ~55 de la 1). Desde que la cotización del inicio
     sale de `main._variacion_del_dia`, esas cuatro se le pedían a Yahoo con el
     nombre pelado y se quedaban sin variación en «Lo que te afecta», la
     watchlist y las alertas.

Y al medir los nombres contra Yahoo apareció algo peor (2026-10-08): pegarle
'-USD' al símbolo NO siempre es el nombre de la moneda. 'TON-USD' es "TON Token"
(US$ 0,0045, no Toncoin US$ 1,36); 'ARB-USD' es "ARbit" (US$ 0,0006, no
Arbitrum); 'CORE-USD' "cVault.finance" (US$ 5.924, no Core US$ 0,018); UNI, SUI,
PEPE, APT… no traen nada. Y el nombre pelado tampoco: 'BTC' es un fondo de NYSE
(US$ 35,81) y 'USDC' un instrumento de US$ 0,0012.

Estas pruebas entran por las funciones que usa producción (los endpoints, el
motor de alertas, la foto diaria, el inicio, el chat) y simulan la red en el
BORDE: `yf.Ticker(nombre).history()` con la forma de yfinance (velas por fecha
con zona horaria, columnas Open/High/Low/Close/Volume; un nombre que Yahoo no
tiene → tabla vacía), poblada con lo que Yahoo devolvía de verdad para cada
nombre el 2026-10-08 — incluidas las monedas equivocadas. Si el código pide el
nombre equivocado, recibe el precio equivocado, igual que en producción.

Corre con: cd backend && python3 -m pytest tests/test_cripto_una_lista.py
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest
import yfinance

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402  (conftest ya seteó DB_PATH temporal)
import alerts_engine as ae       # noqa: E402
import snapshots_job             # noqa: E402
from home import market as hm    # noqa: E402

# La cripto opera 7 días y su vela diaria es el día UTC: las fechas salen del
# reloj de verdad, así el número es "de hoy" corra el test el día que corra.
HOY = _dt.datetime.utcnow().date()
AYER = HOY - _dt.timedelta(days=1)
ANTEAYER = HOY - _dt.timedelta(days=2)

# ─── Yahoo, nombre por nombre, como contestaba el 2026-10-08 ────────────────
# {nombre en Yahoo: (cierre de anteayer, de ayer, de hoy)}. None = sin vela.
YAHOO = {
    # Toncoin y el homónimo que Yahoo tiene con el nombre limpio.
    "TON11419-USD": (1.45, 1.40, 1.3592),
    "TON-USD": (0.0046, 0.0045, 0.004494),          # "TON Token": otra moneda
    # Internet Computer: acá el nombre limpio SÍ es la moneda.
    "ICP-USD": (3.10, 3.05, 2.9902),
    # Monedas estables: el nombre pelado no es la moneda.
    "USDT-USD": (0.9996, 0.9995, 0.9992),
    "USDC-USD": (0.9999, 0.9999, 0.9998),
    "USDC": (0.0011, 0.0012, None),                 # otro instrumento, sin vela hoy
    # Arbitrum / Core: el nombre limpio es otra moneda, de otro orden de magnitud.
    "ARB11841-USD": (0.17, 0.17, 0.16842),
    "ARB-USD": (0.00063, 0.00063, 0.000629),        # "ARbit"
    "CORE23254-USD": (0.0185, 0.0186, 0.018478),
    "CORE-USD": (5900.0, 5910.0, 5924.05),          # "cVault.finance"
    # Uniswap: el nombre limpio no trae nada.
    "UNI7083-USD": (7.60, 7.50, 7.4008),
    # Bitcoin, y el fondo de NYSE que Yahoo tiene con el nombre pelado.
    "BTC-USD": (84000.0, 83275.93, 82483.26),
    "BTC": (36.50, 36.00, 35.81),                   # Grayscale Bitcoin Mini Trust
    "MSFT": (580.0, 590.0, 600.0),
}


class _TickerDeYahoo:
    """`yf.Ticker` con la forma de yfinance. `.history()` → DataFrame con las
    velas diarias (índice con zona horaria, como lo devuelve yfinance); un
    nombre que Yahoo no tiene → DataFrame vacío ("possibly delisted")."""
    pedidos: list = []

    def __init__(self, nombre):
        self.nombre = str(nombre).upper()
        _TickerDeYahoo.pedidos.append(self.nombre)
        velas = YAHOO.get(self.nombre)
        prev = None
        if velas:
            validas = [v for v in velas if v is not None]
            prev = validas[-2] if len(validas) >= 2 else None
        self.fast_info = type("FI", (), {"previous_close": prev,
                                         "last_price": (velas or [None])[-1]})()

    def history(self, *a, **k):
        velas = YAHOO.get(self.nombre)
        if not velas:
            return pd.DataFrame()
        filas = [(d, c) for d, c in zip((ANTEAYER, AYER, HOY), velas) if c is not None]
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in filas]).tz_localize("UTC")
        cierres = [c for _, c in filas]
        return pd.DataFrame({"Open": cierres, "High": cierres, "Low": cierres,
                             "Close": cierres, "Volume": [1e6] * len(filas)}, index=idx)


class _Resp:
    def __init__(self, cuerpo, status=200):
        self._cuerpo, self.status_code = cuerpo, status

    def json(self):
        return self._cuerpo


def _vaciar_caches():
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


@pytest.fixture
def conn():
    c = main.get_db()
    for t in ("alert_symbol_state", "alert_events", "alerts", "watchlist", "snapshots",
              "positions", "brokers", "users"):
        c.execute(f"DELETE FROM {t}")
    c.execute("INSERT INTO users (id, email, name, password_hash, approved, tier) "
              "VALUES (1, 'cripto@rendi.test', 'C', 'x', 1, 'plus')")
    for name, ccy in (("IOL", "ARS"), ("Binance", "USDT")):
        c.execute("INSERT INTO brokers (user_id, name, currency) VALUES (1, ?, ?)", (name, ccy))
    c.commit()
    yield c
    c.close()


def _posicion(c, broker, asset, qty, invested, ccy="USD", asset_type="CRYPTO"):
    c.execute("INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, "
              "quantity, commissions, price_override, currency) VALUES (1,?,?,?,0,?,?,0,NULL,?)",
              (broker, asset, asset_type, invested, qty, ccy))
    c.commit()


def _pct(prev, last):
    return round((last / prev - 1) * 100, 2)


# ─── 1. Una sola lista ───────────────────────────────────────────────────────

def test_home_market_no_tiene_su_propia_lista():
    assert not hasattr(hm, "_CRYPTO_TICKERS")
    # Lo que tenía sólo la copia ahora está en la de main…
    for s in ("TON", "ICP", "USDT", "USDC"):
        assert s in main.CRYPTO_YF, s
    # …y lo que tenía sólo main ahora lo reconoce el inicio.
    for s in ("XMR", "1INCH", "BONK", "WIF", "TON", "ICP", "USDT", "USDC"):
        assert hm.mercado_de(s) == "cripto", s
    assert hm.mercado_de("AAPL") == "us"
    assert hm.mercado_de("GGAL.BA") == "byma"


def test_las_estables_se_cotizan_como_cripto_pero_no_llevan_premio():
    """USDT/USDC: nombre de Yahoo y rueda 24/7, pero NO entran a CRYPTO_SYMBOLS,
    que decide el premio del dólar cripto y el ruteo de la valuación: el resto
    de la app las trata como dólares."""
    assert main.CRIPTO_ESTABLES <= set(main.CRYPTO_YF)
    assert not (main.CRIPTO_ESTABLES & main.CRYPTO_SYMBOLS)
    assert main.crypto_broker_factor("USDT", "IOL", False, 1500, 1400, "ARS") == 1.0
    assert main.crypto_broker_factor("TON", "IOL", False, 1500, 1400, "ARS") == 1500 / 1400


def test_cada_cripto_del_inicio_usa_el_nombre_de_la_lista():
    """El mapa «Cripto top 30» guarda 'TON-USD': se traduce por la lista, no se
    le pide a Yahoo tal cual (es otra moneda)."""
    for s in hm.CRYPTO_TOP_30:
        assert main.yahoo_de_cripto(s), s
    assert main.yahoo_de_cripto("TON-USD") == "TON11419-USD"
    assert main.yahoo_de_cripto("TON") == "TON11419-USD"
    assert main.yahoo_de_cripto("ICP") == "ICP-USD"
    assert main.yahoo_de_cripto("AAPL") is None
    assert main.yahoo_de_cripto("TON.BA") is None


def test_los_nombres_distintos_son_de_criptos_de_la_lista():
    assert set(main._YAHOO_CRIPTO_DISTINTO) <= set(main.CRYPTO_YF)
    for s, nombre in main.CRYPTO_YF.items():
        assert nombre.endswith("-USD"), (s, nombre)    # el calendario 24/7 lo lee así
        assert main._SYMBOL_RE.match(nombre), (s, nombre)  # /api/prices lo acepta


# ─── 2. Posiciones: el precio y la "Var. día" ───────────────────────────────

def test_posiciones_valua_toncoin_y_no_el_homonimo(conn):
    with yahoo() as pedidos:
        p = main.get_prices("TON,ICP,ARB,CORE,UNI,USDC", 1)
        pc = main.get_prev_close("TON,ICP,ARB,CORE,UNI,USDC", 1)
    assert p["TON"] == 1.3592            # antes: 0,0045 (TON Token)
    assert p["ICP"] == 2.9902
    assert p["ARB"] == 0.16842           # antes: 0,00063 (ARbit) — 267× menos
    assert p["CORE"] == 0.018478         # antes: 5.924 (cVault) — 320.000× más
    assert p["UNI"] == 7.4008            # antes: sin precio
    assert p["USDC"] == 0.9998           # antes: 0,0012 (otro instrumento)
    assert pc["TON"] == 1.40 and pc["ICP"] == 3.05 and pc["USDC"] == 0.9999
    for malo in ("TON", "TON-USD", "ARB-USD", "CORE-USD", "USDC", "ICP"):
        assert malo not in pedidos, malo


def test_toncoin_en_una_cuenta_en_pesos_se_cotiza_como_cripto(conn):
    """Antes TON no era cripto para la valuación: en IOL pedía 'TON.BA', que no
    cotiza en ningún lado. Ahora el símbolo de precio es la cripto."""
    from snapshots_job import build_price_symbols
    _posicion(conn, "IOL", "TON", 100, 150000, ccy="ARS")
    pos = [dict(r) for r in conn.execute("SELECT * FROM positions WHERE user_id=1")]
    brk = [dict(r) for r in conn.execute("SELECT * FROM brokers WHERE user_id=1")]
    assert build_price_symbols(pos, brk) == ["TON"]


# ─── 3. La variación del día: «Lo que te afecta», watchlist, alertas, inicio ──

def test_la_watchlist_tiene_la_variacion_de_ton_icp_y_las_estables(conn):
    conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES "
                 "(1, 'TON'), (1, 'ICP'), (1, 'USDT'), (1, 'USDC')")
    conn.commit()
    with yahoo():
        r = main.watchlist_list(1)
    filas = {it["symbol"]: it for it in r["items"]}
    assert filas["TON"]["change_pct"] == _pct(1.40, 1.3592)
    assert filas["TON"]["price"] == 1.3592
    assert filas["ICP"]["change_pct"] == _pct(3.05, 2.9902)
    assert filas["USDT"]["change_pct"] == _pct(0.9995, 0.9992)
    assert filas["USDC"]["change_pct"] == _pct(0.9999, 0.9998)   # no la del instrumento de US$ 0,0012
    assert filas["TON"]["as_of"] == HOY.isoformat()


def test_lo_que_te_afecta_cotiza_la_tenencia_de_toncoin(conn):
    _posicion(conn, "Binance", "TON", 100, 140)
    _posicion(conn, "IOL", "ICP", 10, 45000, ccy="ARS")
    with yahoo():
        q = main._cotizaciones_de_tenencias(conn, 1)
    assert q["TON"]["change_pct"] == _pct(1.40, 1.3592)
    assert q["TON"]["mercado"] == "cripto"
    assert q["ICP"]["change_pct"] == _pct(3.05, 2.9902)


def test_la_alerta_de_porcentaje_del_dia_dispara_con_toncoin(conn):
    """Motor completo: `evaluate_alerts` → `_quotes_for` → `_fetch_batch_quotes`
    → `main._variacion_del_dia` → Yahoo. Toncoin bajó 2,91 % hoy; el homónimo
    que se pedía antes (TON Token) bajó 0,13 % y no disparaba nada."""
    conn.execute(
        """INSERT INTO alerts (user_id,kind,symbol,scope,direction,threshold,up_pct,down_pct,
           currency,baseline,channel,repeat,cooldown_min,armed,active)
           VALUES (1,'pct_move','TON','ticker','above',NULL,NULL,2,'USD','prev_close','push',
                   'always',360,1,1)""")
    conn.commit()
    with yahoo(), patch.object(ae, "_deliver", lambda *a, **k: (True, False)):
        r = ae.evaluate_alerts(conn, only_user=1)
    assert r["fired"] == 1


def test_el_mapa_cripto_del_inicio_muestra_toncoin_y_polygon(conn):
    with yahoo() as pedidos:
        bloques = {b["symbol"]: b for b in hm._build_heatmap("crypto")}
    assert bloques["TON-USD"]["price"] == 1.3592
    assert bloques["TON-USD"]["change_pct"] == _pct(1.40, 1.3592)
    assert bloques["ICP-USD"]["change_pct"] == _pct(3.05, 2.9902)
    assert "TON-USD" not in pedidos and "TON11419-USD" in pedidos
    assert "UNI7083-USD" in pedidos and "POL28321-USD" in pedidos and "MATIC-USD" not in pedidos


# ─── 4. La foto diaria ──────────────────────────────────────────────────────

def test_la_foto_diaria_valua_toncoin_al_precio_de_toncoin(conn):
    """Los mismos argumentos que el cron (`run_daily_snapshot` → `crypto_yf=CRYPTO_YF`)."""
    _posicion(conn, "Binance", "TON", 100, 140)
    _posicion(conn, "Binance", "ARB", 1000, 150)
    with yahoo() as pedidos:
        with conn:
            r = snapshots_job.take_snapshot_for_user(conn, 1, 1400.0, main.CRYPTO_YF,
                                                     HOY.isoformat(), tc_mep=1400.0)
    assert r["ok"], r
    total = conn.execute("SELECT total_value FROM snapshots WHERE user_id=1").fetchone()[0]
    assert total == pytest.approx(100 * 1.3592 + 1000 * 0.16842, abs=0.01)
    assert "TON-USD" not in pedidos and "ARB-USD" not in pedidos


def test_fetch_prices_for_symbols_con_la_lista_de_main(conn):
    with yahoo():
        out = snapshots_job.fetch_prices_for_symbols(["TON", "BTC", "USDC", "MSFT"], main.CRYPTO_YF)
    assert out == {"TON": 1.3592, "BTC": 82483.26, "USDC": 0.9998, "MSFT": 600.0}


# ─── 5. El chat, el mini-gráfico y la serie histórica ───────────────────────

def test_el_chat_registra_toncoin_al_precio_de_toncoin(conn):
    with yahoo():
        assert main._trade_market_price("TON", "CRYPTO", "USD", 1) == 1.3592


def test_el_chat_consulta_el_precio_aunque_pida_ton_usd(conn):
    """La IA pide 'TON-USD' (con el sufijo pegado): es Toncoin, no TON Token."""
    with yahoo() as pedidos:
        r = main._execute_ai_tool_inner("get_current_prices", {"symbols": ["TON-USD", "TON"]}, 1)
    assert r["prices"] == {"TON-USD": 1.3592, "TON": 1.3592}
    assert "TON-USD" not in pedidos


def test_el_mini_grafico_de_toncoin(conn):
    with yahoo() as pedidos:
        r = main.get_price_history("TON", "1w", 1)
    assert [p["close"] for p in r["points"]] == [1.45, 1.40, 1.3592]
    assert pedidos == ["TON11419-USD"]


def test_la_serie_historica_de_bitcoin_no_es_la_del_fondo_de_nyse():
    import price_history
    with yahoo() as pedidos:
        serie = price_history._fetch_yfinance("BTC", ANTEAYER.isoformat())
    assert list(serie.values()) == [84000.0, 83275.93, 82483.26]
    assert pedidos == ["BTC-USD"]


# ─── 6. Cuánto pasa en producción: el panel de admin lo mide ────────────────

def test_el_panel_de_alcance_cuenta_las_tenencias_afectadas(conn):
    """Q13 del panel «Alcance de la auditoría» (admin): sólo agregados."""
    import alcance_auditoria as alc
    _posicion(conn, "Binance", "TON", 100, 140)
    _posicion(conn, "IOL", "CORE", 5000, 90000, ccy="ARS")
    _posicion(conn, "Binance", "UNI", 3, 20)
    _posicion(conn, "Binance", "ICP", 10, 30)
    _posicion(conn, "Binance", "BTC", 0.01, 800)          # no cuenta: Yahoo la cotiza bien
    q13 = next(h for h in alc.informe(conn)["hallazgos"] if h["id"] == "Q13")
    assert q13["numero"] == 2                              # TON y CORE
    assert q13["veredicto"] == "urgente"
    d = q13["detalle"]
    assert (d["tenencias_mal_cotizadas"], d["usuarios_afectados"]) == (4, 1)
    assert (d["sin_precio_de_yahoo"], d["sin_variacion_del_dia"]) == (1, 1)
    assert set(d["simbolos_en_uso"].split(",")) == {"TON", "CORE", "UNI", "ICP"}
