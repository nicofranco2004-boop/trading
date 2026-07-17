"""Regresión del builder insights.summary (lectura IA del Diagnóstico).

Blinda: (1) el TWR compuesto (bug del fantasma) NO sale como número duro —
va solo en twr_pct_low_confidence; (2) los verdicts/findings que manda el
frontend se sanean (largo, NaN/inf → None); (3) modo empty no rompe.

Test hermético (DB in-memory) — corre siempre.
"""
from __future__ import annotations
import json
import sqlite3
import pytest

from ai.builders.insights_summary import build


def _conn(with_data=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE snapshots (user_id INT, date TEXT, total_value REAL, net_deposited REAL, total_invested REAL)")
    conn.execute("CREATE TABLE monthly_entries (user_id INT, broker TEXT, year INT, month INT, capital_inicio REAL, capital_final REAL, deposits REAL, withdrawals REAL)")
    conn.execute("CREATE TABLE operations (user_id INT, date TEXT, asset TEXT, op_type TEXT, entry_price REAL, exit_price REAL, quantity REAL, pnl_usd REAL, pnl_pct REAL, broker TEXT)")
    conn.execute("CREATE TABLE positions (user_id INT, asset TEXT, broker TEXT, quantity REAL, invested REAL, is_cash INT, currency TEXT, asset_type TEXT, price_override REAL)")
    conn.execute("CREATE TABLE brokers (user_id INT, id INTEGER PRIMARY KEY, name TEXT, currency TEXT, parent_broker_id INT, is_exchange INT)")
    conn.execute("CREATE TABLE config (user_id INT, key TEXT, value TEXT)")
    if with_data:
        conn.execute("INSERT INTO brokers (user_id,name,currency,is_exchange) VALUES (1,'Schwab','USD',0)")
        conn.execute("INSERT INTO positions (user_id,asset,broker,quantity,invested,is_cash,currency,asset_type) VALUES (1,'NVDA','Schwab',10,5000,0,'USD','stock')")
        conn.execute("INSERT INTO positions (user_id,asset,broker,quantity,invested,is_cash,currency) VALUES (1,'USD','Schwab',0,4000,1,'USD')")
        conn.execute("INSERT INTO operations (user_id,date,asset,op_type,quantity,pnl_usd,pnl_pct,broker) VALUES (1,'2025-03-01','INTC','Venta',100,500,25,'Schwab')")
        conn.execute("INSERT INTO monthly_entries (user_id,broker,year,month,capital_inicio,capital_final,deposits,withdrawals) VALUES (1,'global',2025,1,10000,11000,0,0)")
        conn.execute("INSERT INTO snapshots (user_id,date,total_value,net_deposited) VALUES (1,'2025-01-01',10000,10000)")
        conn.execute("INSERT INTO snapshots (user_id,date,total_value,net_deposited) VALUES (1,'2025-06-01',12000,10000)")
        conn.execute("INSERT INTO config (user_id,key,value) VALUES (1,'tc_blue','1450')")
    conn.commit()
    return conn


def test_twr_only_as_low_confidence():
    """El twr crudo (bug fantasma) NO debe estar como 'twr_pct' en el packet."""
    pkt = build(_conn(), 1, archetype="completo")
    raw = json.dumps(pkt, ensure_ascii=False)
    assert pkt["screen"] == "insights.summary"
    assert '"twr_pct":' not in raw, "el twr crudo no debe filtrarse"
    assert "twr_pct_low_confidence" in pkt


def test_verdicts_and_findings_passed_through():
    pkt = build(
        _conn(), 1,
        findings=[{"category": "Riesgo", "severity": "urgent", "text": "**Concentración**."}],
        verdicts=[{"label": "Inflación", "pct": 6.2}],
        months_tracked=12, missing_prices=["PAMP"],
    )
    assert pkt["verdicts"] == [{"label": "Inflación", "pct": 6.2}]
    assert len(pkt["top_findings"]) == 1
    assert pkt["context"]["months_tracked"] == 12
    assert pkt["context"]["missing_prices"] == ["PAMP"]


def test_sanitizes_garbage_params():
    """findings no-lista → []; pct NaN/inf/string → None; label capeado."""
    pkt = build(
        _conn(), 1,
        findings="no-soy-lista",
        verdicts=[{"label": "X" * 200, "pct": "nan"}, {"label": "Y", "pct": float("inf")}],
    )
    assert pkt["top_findings"] == []
    assert pkt["verdicts"][0]["pct"] is None
    assert pkt["verdicts"][1]["pct"] is None
    assert len(pkt["verdicts"][0]["label"]) <= 48


def test_empty_portfolio_no_crash():
    pkt = build(_conn(False), 1, archetype="empty")
    assert pkt["current_holdings_top"] == []
    assert pkt["verdicts"] == []
    assert pkt["top_findings"] == []
    assert pkt["context"]["n_positions"] == 0


def test_only_benchmark_own_returns_kept():
    """vs_benchmarks conserva returns propios, dropea los delta_*_pp (dependen del twr)."""
    pkt = build(_conn(), 1)
    vb = pkt["vs_benchmarks"]
    assert set(vb.keys()) == {"sp500_pct", "inflation_ar_pct"}
    assert "delta_sp500_pp" not in vb
