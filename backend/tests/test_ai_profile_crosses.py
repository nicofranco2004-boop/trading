"""Regresión de los cruces test↔cartera de los builders de perfil.

═══════════════════════════════════════════════════════════════════════════
Blinda dos bugs que el deep audit de profile.summary destapó — ambos vivían
en `_build_card_data` (compartido por profile.card y profile.summary) y hacían
que la lectura IA contradijera las cards que el user ve justo debajo:

  #1  El eje 'estilo' filtraba `op_type == "SELL"`, pero el DB guarda 'Venta'
      (español) → el cross daba SIEMPRE no_data para todo user real, mientras
      la card del frontend (computeStyleCoherence) sí lo computaba.
  #2  Stablecoins (USDT/USDC/DAI) NO marcadas is_cash caían en el bucket
      'alternative' (volátil), pero classifyAssetBucket del frontend las cuenta
      como 'cash' → contradicción directa en Liquidez/Allocation.

Tests herméticos (DB in-memory) — corren siempre, sin depender de trading.db.
"""
from __future__ import annotations
import json
import sqlite3
import pytest

from ai.builders.profile_card import _build_card_data, _is_trade_op
from ai.builders.profile_summary import build as build_summary


_PROFILE = {
    "horizon": "medium", "drawdown": "hold", "goal": "freedom", "style": "mixed",
    "net_worth": "10_to_30", "liquidity": "no", "experience": "2_to_5",
    "return_expectation": "grow",
}


def _conn(positions=(), operations=(), profile=_PROFILE, tc_blue="1450"):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, investor_profile TEXT)")
    conn.execute("CREATE TABLE positions (user_id INT, asset TEXT, invested REAL, broker TEXT, asset_type TEXT, is_cash INT, currency TEXT)")
    conn.execute("CREATE TABLE brokers (user_id INT, name TEXT, currency TEXT, parent_broker_id INT, id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE operations (user_id INT, date TEXT, asset TEXT, op_type TEXT, quantity REAL, entry_price REAL, broker TEXT)")
    conn.execute("CREATE TABLE config (user_id INT, key TEXT, value TEXT)")
    conn.execute("INSERT INTO users VALUES (1, ?)", (json.dumps(profile) if profile else "{}",))
    conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (1,'Binance','USD')")
    for asset, invested, is_cash in positions:
        conn.execute(
            "INSERT INTO positions (user_id,asset,invested,broker,asset_type,is_cash,currency) VALUES (1,?,?,'Binance','crypto',?,'USD')",
            (asset, invested, is_cash),
        )
    for date, op_type in operations:
        conn.execute(
            "INSERT INTO operations (user_id,date,asset,op_type,quantity,entry_price,broker) VALUES (1,?,'AAPL',?,10,180,'Binance')",
            (date, op_type),
        )
    conn.execute("INSERT INTO config (user_id,key,value) VALUES (1,'tc_blue',?)", (tc_blue,))
    conn.commit()
    return conn


def _ops(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM operations WHERE user_id=1")]


# ── #1: eje estilo con op_type en español ────────────────────────────────────

@pytest.mark.parametrize("op_type,is_trade", [
    ("Venta", True), ("Futuros", True), ("SELL", True),
    ("Compra", False), ("Dividendo", False), ("Interés", False),
    ("Conversión USD→ARS", False), ("CONVERSION IMPORT USD→ARS", False),
    ("", False), (None, False), ("  ", False),
])
def test_is_trade_op_canonical(op_type, is_trade):
    assert _is_trade_op(op_type) is is_trade


def test_style_counts_venta_not_sell():
    """#1 — 4 ventas ('Venta', no 'SELL') → el eje deja de estar muerto."""
    ops = [("2026-01-10", "Venta"), ("2026-02-15", "Venta"),
           ("2026-03-20", "Venta"), ("2026-05-01", "Venta"),
           ("2026-01-05", "Compra"), ("2026-01-06", "Dividendo")]
    conn = _conn(operations=ops)
    card = _build_card_data("style", _PROFILE, [], [], _ops(conn), conn, 1, 1450.0, 1450.0)
    assert card["status"] == "ready", "con ventas en español el eje debe tener data"
    assert card["actual"]["trades_per_month"] > 0
    assert card["actual"]["trades_total_6m"] == 4  # compra/dividendo NO cuentan


def test_style_under_3_trades_is_no_data():
    """#1 — umbral <3 igual que computeStyleCoherence del frontend."""
    conn = _conn(operations=[("2026-01-10", "Venta"), ("2026-02-10", "Venta")])
    card = _build_card_data("style", _PROFILE, [], [], _ops(conn), conn, 1, 1450.0, 1450.0)
    assert card["status"] == "no_data"


# ── #2: stablecoins no-is_cash → bucket cash ─────────────────────────────────

def test_stablecoin_bucketed_as_cash():
    """#2 — USDT sin is_cash cuenta como cash, no alternative."""
    conn = _conn(positions=[("USDT", 10000, 0), ("BTC", 8000, 0), ("AAPL", 6000, 0)])
    positions = [dict(r) for r in conn.execute("SELECT * FROM positions WHERE user_id=1")]
    card = _build_card_data("allocation", _PROFILE, positions, [], [], conn, 1, 1450.0, 1450.0)
    buckets = card["actual"]["buckets_pct"]
    assert buckets["cash"] > 0, "USDT debe sumar al bucket cash"
    assert buckets["cash"] > buckets["alternative"], "USDT(10k)>BTC(8k) → cash domina alt"
    # BTC sigue siendo alternative (no lo tocamos)
    assert buckets["alternative"] > 0


@pytest.mark.parametrize("stable", ["USDT", "USDC", "DAI"])
def test_all_stablecoins_are_cash(stable):
    conn = _conn(positions=[(stable, 5000, 0), ("AAPL", 5000, 0)])
    positions = [dict(r) for r in conn.execute("SELECT * FROM positions WHERE user_id=1")]
    card = _build_card_data("allocation", _PROFILE, positions, [], [], conn, 1, 1450.0, 1450.0)
    assert card["actual"]["buckets_pct"]["cash"] == 50


# ── invariantes del summary ──────────────────────────────────────────────────

def test_summary_has_no_phantom_return():
    conn = _conn(positions=[("BTC", 8000, 0)], operations=[("2026-01-10", "Venta")])
    raw = json.dumps(build_summary(conn, 1), ensure_ascii=False).lower()
    for banned in ("twr", "real_return", "retorno_real", "-64.9", "rendimiento"):
        assert banned not in raw, f"'{banned}' no debería estar en el packet"


def test_summary_empty_profile_returns_empty_crosses():
    conn = _conn(profile=None)
    pkt = build_summary(conn, 1)
    assert pkt["crosses"] == {}
    assert pkt["profile_declared"] == {}
