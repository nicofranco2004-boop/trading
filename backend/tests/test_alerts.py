"""Tests del sistema de alertas: gating por plan, edge-trigger de price_target,
cooldown de pct_move, y expansión holdings-scope. Sin red (precios/entrega
mockeados)."""
from __future__ import annotations
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402  (conftest ya seteó DB_PATH temporal)
import alerts_engine as ae       # noqa: E402
from ai import plan              # noqa: E402


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    conn = main.get_db()
    for t in ("alert_events", "alerts", "positions", "brokers", "users"):
        try:
            conn.execute(f"DELETE FROM {t}")
        except Exception:
            pass
    conn.execute("INSERT INTO users (id,email,name,password_hash) VALUES (1,'a@a.co','A','x')")          # free
    conn.execute("INSERT INTO users (id,email,name,password_hash,tier) VALUES (2,'b@b.co','B','x','plus')")  # plus
    conn.commit()
    # Nunca tocar red en tests.
    monkeypatch.setattr(ae, "_deliver", lambda *a, **k: (True, False))
    yield conn
    conn.close()


def _mk_alert(conn, **kw):
    d = dict(user_id=1, kind="price_target", symbol="AAPL", scope="ticker",
             direction="above", threshold=200.0, up_pct=None, down_pct=None,
             currency="USD", baseline="prev_close",
             channel="push", repeat="once", cooldown_min=360, armed=1, active=1)
    d.update(kw)
    cur = conn.execute(
        """INSERT INTO alerts (user_id,kind,symbol,scope,direction,threshold,up_pct,down_pct,
           currency,baseline,channel,repeat,cooldown_min,armed,active)
           VALUES (:user_id,:kind,:symbol,:scope,:direction,:threshold,:up_pct,:down_pct,
           :currency,:baseline,:channel,:repeat,:cooldown_min,:armed,:active)""", d)
    conn.commit()
    return cur.lastrowid


def _events(conn, uid=1):
    return conn.execute("SELECT * FROM alert_events WHERE user_id=? ORDER BY id", (uid,)).fetchall()


# ── condition_met (lógica pura) ──────────────────────────────────────────────

def test_condition_price_target():
    assert ae.condition_met("price_target", "above", 200, 210, None) is True
    assert ae.condition_met("price_target", "above", 200, 190, None) is False
    assert ae.condition_met("price_target", "below", 200, 190, None) is True
    assert ae.condition_met("price_target", "below", 200, 210, None) is False
    # precio ausente → None (no adivinar, no disparar)
    assert ae.condition_met("price_target", "above", 200, None, None) is None


def test_pct_move_side_asymmetric():
    # umbrales asimétricos en una alerta: sube ≥3% o cae ≥2%
    assert ae.pct_move_side(4, 3, 2) == "up"
    assert ae.pct_move_side(-2.5, 3, 2) == "down"
    assert ae.pct_move_side(1, 3, 2) is None       # dentro de la banda
    assert ae.pct_move_side(-1.5, 3, 2) is None
    # un solo lado
    assert ae.pct_move_side(-6, None, 5) == "down"
    assert ae.pct_move_side(-6, 5, None) is None    # solo mira subas
    assert ae.pct_move_side(12, 10, None) == "up"
    assert ae.pct_move_side(None, 3, 2) is None     # sin quote → no dispara


# ── Gating por plan ──────────────────────────────────────────────────────────

def test_quota_free_caps_at_3(clean):
    conn = clean
    for i in range(3):
        _mk_alert(conn, symbol=f"T{i}")
    ok, info = plan.check_alert_quota(conn, 1)
    assert ok is False and info["limit"] == 3 and info["current_count"] == 3


def test_quota_plus_higher(clean):
    conn = clean
    ok, info = plan.check_alert_quota(conn, 2)   # plus
    assert ok is True and info["limit"] == 25


def test_pct_move_gated_free_not_plus(clean):
    conn = clean
    assert plan.can_access(conn, 1, "alerts.pct_move") is False   # free
    assert plan.can_access(conn, 2, "alerts.pct_move") is True    # plus


# ── Edge-trigger de price_target ─────────────────────────────────────────────

def test_price_target_fires_on_cross_once(clean, monkeypatch):
    conn = clean
    _mk_alert(conn, direction="above", threshold=200, repeat="once", armed=1)
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 210.0})
    res = ae.evaluate_alerts(conn, only_user=1)
    assert res["fired"] == 1
    a = conn.execute("SELECT armed,active FROM alerts").fetchone()
    assert a["armed"] == 0 and a["active"] == 0            # once → inactiva
    # segunda evaluación: no re-dispara (inactiva)
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
    assert len(_events(conn)) == 1


def test_price_target_no_fire_when_not_met_then_fires(clean, monkeypatch):
    conn = clean
    _mk_alert(conn, direction="above", threshold=200, armed=1)
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 190.0})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0   # aún por debajo
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 205.0})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1   # cruzó


def test_price_target_recurring_rearms(clean, monkeypatch):
    conn = clean
    _mk_alert(conn, direction="above", threshold=200, repeat="always", armed=1)
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 210.0})
    ae.evaluate_alerts(conn, only_user=1)                        # dispara, desarma
    assert conn.execute("SELECT armed,active FROM alerts").fetchone()["armed"] == 0
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 180.0})
    ae.evaluate_alerts(conn, only_user=1)                        # vuelve abajo → re-arma
    assert conn.execute("SELECT armed FROM alerts").fetchone()["armed"] == 1
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 210.0})
    ae.evaluate_alerts(conn, only_user=1)                        # cruza de nuevo → dispara
    assert len(_events(conn)) == 2


def test_price_target_no_fire_on_none_price(clean, monkeypatch):
    conn = clean
    _mk_alert(conn, direction="above", threshold=200, armed=1)
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": None})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
    assert conn.execute("SELECT armed FROM alerts").fetchone()["armed"] == 1  # sigue armada


# ── pct_move: cooldown + holdings scope ──────────────────────────────────────

def test_pct_move_cooldown(clean, monkeypatch):
    conn = clean
    _mk_alert(conn, kind="pct_move", down_pct=5, threshold=None, symbol="AAPL",
              cooldown_min=360, repeat="always")
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": {"price": 90, "change_pct": -7.0}})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    # segunda evaluación inmediata: dentro del cooldown → no re-dispara
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
    # envejecemos el evento más allá del cooldown → re-dispara
    old = (datetime.utcnow() - timedelta(hours=7)).isoformat()
    conn.execute("UPDATE alert_events SET fired_at=?", (old,)); conn.commit()
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1


def test_pct_move_holdings_scope_expands(clean, monkeypatch):
    conn = clean
    # asimétrico: sube ≥10% o cae ≥5%
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None,
              up_pct=10, down_pct=5, threshold=None, cooldown_min=360, repeat="always")
    monkeypatch.setattr(ae, "_holding_symbols", lambda conn, uid: ["AAPL", "MSFT", "KO"])
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {
        "AAPL": {"price": 90, "change_pct": -8.0},   # cae ≥5 → dispara (down)
        "MSFT": {"price": 400, "change_pct": 3.0},   # ni sube 10 ni cae 5 → no
        "KO":   {"price": 60, "change_pct": 11.0},   # sube ≥10 → dispara (up)
    })
    res = ae.evaluate_alerts(conn, only_user=1)
    assert res["fired"] == 2
    fired_syms = {e["symbol"] for e in _events(conn)}
    assert fired_syms == {"AAPL", "KO"}


# ── Fixes del audit ──────────────────────────────────────────────────────────

def test_norm_sym_crypto():
    # cripto en broker AR llega como 'BTC.BA' → se normaliza a 'BTC' (BTC-USD)
    assert ae._norm_sym("BTC.BA") == "BTC"
    assert ae._norm_sym("ETH.BA") == "ETH"
    # NO toca CEDEARs ni tickers normales
    assert ae._norm_sym("AAPL.BA") == "AAPL.BA"
    assert ae._norm_sym("AAPL") == "AAPL"
    assert ae._norm_sym("BTC") == "BTC"


def test_crypto_holdings_resolves(clean, monkeypatch):
    # Plus con cripto comprada en Cocos (broker AR): build_price_symbols da 'BTC.BA'.
    # El motor debe normalizar a 'BTC' y disparar (antes quedaba muerta).
    conn = clean
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None,
              up_pct=5, down_pct=5, threshold=None, repeat="always")
    monkeypatch.setattr(ae, "_holding_symbols", lambda conn, uid: ["BTC.BA"])
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"BTC": {"price": 65000, "change_pct": 6.0}})
    res = ae.evaluate_alerts(conn, only_user=1)
    assert res["fired"] == 1
    assert _events(conn)[0]["symbol"] == "BTC"   # normalizado, no BTC.BA


def test_pct_move_once_deactivates(clean, monkeypatch):
    # 'una vez' en pct_move: dispara y se APAGA (antes re-disparaba tras el cooldown).
    conn = clean
    _mk_alert(conn, kind="pct_move", down_pct=3, threshold=None, symbol="AAPL",
              repeat="once", cooldown_min=360)
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": {"price": 90, "change_pct": -5.0}})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    assert conn.execute("SELECT active FROM alerts").fetchone()["active"] == 0
    # aunque envejezca el evento más allá del cooldown, NO re-dispara (inactiva)
    old = (datetime.utcnow() - timedelta(hours=8)).isoformat()
    conn.execute("UPDATE alert_events SET fired_at=?", (old,)); conn.commit()
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0


def test_pct_move_once_holdings_fires_once_then_stops(clean, monkeypatch):
    # holdings 'once': dispara el/los que se movieron este ciclo y se apaga.
    conn = clean
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None,
              down_pct=5, threshold=None, repeat="once")
    monkeypatch.setattr(ae, "_holding_symbols", lambda conn, uid: ["AAPL", "KO"])
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {
        "AAPL": {"price": 90, "change_pct": -8.0},
        "KO":   {"price": 60, "change_pct": -6.0},
    })
    ae.evaluate_alerts(conn, only_user=1)
    assert conn.execute("SELECT active FROM alerts").fetchone()["active"] == 0
    # próximo ciclo: inactiva → 0 disparos
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
