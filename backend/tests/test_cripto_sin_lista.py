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

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402  (conftest ya seteó DB_PATH temporal)


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
