"""Tests del sistema de alertas: gating por plan, edge-trigger de price_target,
cooldown de pct_move, y expansión holdings-scope. Sin red (precios/entrega
mockeados)."""
from __future__ import annotations
import os
import sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402  (conftest ya seteó DB_PATH temporal)
import alerts_engine as ae       # noqa: E402
from home.market import _stamp_session   # noqa: E402  (misma función que estampa en prod)

# El fixture de abajo deja `_market_open_now` en "siempre abierto" para todo el
# módulo. Los tests del reloj miden la función DE VERDAD, así que la guardamos
# acá, al importar, antes de que el fixture la pise.
_RELOJ_REAL = ae._market_open_now
# Ídem la entrega: el fixture la anula para no tocar la red, pero los tests
# del mail agrupado necesitan la de verdad (mockean un escalón más abajo).
_ENTREGA_REAL = ae._deliver
from ai import plan              # noqa: E402


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    conn = main.get_db()
    for t in ("alert_symbol_state", "alert_events", "alerts", "positions", "brokers", "users"):
        try:
            conn.execute(f"DELETE FROM {t}")
        except Exception:
            pass
    conn.execute("INSERT INTO users (id,email,name,password_hash) VALUES (1,'a@a.co','A','x')")          # free
    conn.execute("INSERT INTO users (id,email,name,password_hash,tier) VALUES (2,'b@b.co','B','x','plus')")  # plus
    conn.commit()
    # Nunca tocar red en tests.
    monkeypatch.setattr(ae, "_deliver", lambda *a, **k: (True, False))
    # Por defecto el mercado está "abierto" (los tests de acciones asumen horario);
    # los tests del gate lo sobreescriben explícitamente.
    monkeypatch.setattr(ae, "_market_open_now", lambda now: True)
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


def _q(price, change, *, sym="AAPL", hoy=True):
    """Un quote con la MISMA forma que el de producción: el porcentaje viaja con
    la RUEDA que lo midió (`as_of`), y `is_today` lo deriva la función de
    producción — el test no lo escribe a mano, porque si lo escribiera estaría
    certificando su propia copia del guard en vez del guard.

    `hoy=False` = la última barra que trajo el proveedor es la de ayer: es lo que
    pasa antes de que abra el mercado, en un feriado, o cuando la barra del día
    viene con los OHLC en NaN (frecuente en los `.BA`)."""
    dia = ae._sesion_hoy(sym)
    ayer = (date.fromisoformat(dia) - timedelta(days=1)).isoformat()
    return _stamp_session({"price": price, "change_pct": change,
                           "as_of": dia if hoy else ayer}, sym)


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

def test_pct_move_once_per_day_no_oscillation_dupes(clean, monkeypatch):
    # Bug de Nico: ADBE avisó a las 16:20 (3.2%) y OTRA vez 16:50 (3.3%) — oscilando
    # alrededor del 3%. Debe avisar UNA sola vez por jornada.
    conn = clean
    _mk_alert(conn, kind="pct_move", down_pct=5, threshold=None, symbol="AAPL", repeat="always")
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -7.0)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1   # cruza → dispara (1 hoy)
    # baja a -1% (dentro de banda) y vuelve a -6% → NO re-dispara (ya avisó hoy)
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(99, -1.0)})
    ae.evaluate_alerts(conn, only_user=1)
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -6.0)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0   # mismo día → 1 aviso y basta
    # DÍA NUEVO (simulado): el % congelado NO re-dispara (armed=0), pero un mov nuevo sí
    conn.execute("UPDATE alert_symbol_state SET last_fired_date='2000-01-01'"); conn.commit()
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0   # -6% congelado → no
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(100, -0.5)})
    ae.evaluate_alerts(conn, only_user=1)                        # resetea → re-arma
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -7.0)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1   # mov nuevo del día → dispara


def test_holdings_frozen_move_does_not_refire(clean, monkeypatch):
    # Bug de Nico: "toda mi cartera 3%" avisó de MU/INTC/ADBE ayer y volvió a avisar
    # HOY sobre esos mismos (el change_pct de ayer quedaba congelado).
    conn = clean
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None,
              up_pct=3, down_pct=3, threshold=None, repeat="always")
    monkeypatch.setattr(ae, "_holding_symbols", lambda c, u: ["MU", "INTC", "ADBE", "AAPL"])
    frozen = {"MU": _q(96, -4.0), "INTC": _q(96, -4.0),
              "ADBE": _q(96, -4.0), "AAPL": _q(99, -1.0)}
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: frozen)
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 3            # ayer: MU/INTC/ADBE
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0            # mismo día / congelado → no
    # DÍA NUEVO: congelado no re-dispara; al resetear re-arma; MU cae 3% de nuevo → solo MU
    conn.execute("UPDATE alert_symbol_state SET last_fired_date='2000-01-01'"); conn.commit()
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0            # -4% congelado (armed=0)
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {k: _q(100, 0.0) for k in frozen})
    ae.evaluate_alerts(conn, only_user=1)                                # resetea → re-arma
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"MU": _q(97, -3.2),
        "INTC": _q(100, 0.0), "ADBE": _q(100, 0.0), "AAPL": _q(100, 0.0)})
    res = ae.evaluate_alerts(conn, only_user=1)
    assert res["fired"] == 1 and _events(conn)[-1]["symbol"] == "MU"     # solo MU (mov nuevo)


def test_pct_move_holdings_scope_expands(clean, monkeypatch):
    conn = clean
    # asimétrico: sube ≥10% o cae ≥5%
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None,
              up_pct=10, down_pct=5, threshold=None, cooldown_min=360, repeat="always")
    monkeypatch.setattr(ae, "_holding_symbols", lambda conn, uid: ["AAPL", "MSFT", "KO"])
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {
        "AAPL": _q(90, -8.0),    # cae ≥5 → dispara (down)
        "MSFT": _q(400, 3.0),    # ni sube 10 ni cae 5 → no
        "KO":   _q(60, 11.0),    # sube ≥10 → dispara (up)
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
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"BTC": _q(65000, 6.0, sym="BTC")})
    res = ae.evaluate_alerts(conn, only_user=1)
    assert res["fired"] == 1
    assert _events(conn)[0]["symbol"] == "BTC"   # normalizado, no BTC.BA


def test_pct_move_once_deactivates(clean, monkeypatch):
    # 'una vez' en pct_move: dispara y se APAGA (antes re-disparaba tras el cooldown).
    conn = clean
    _mk_alert(conn, kind="pct_move", down_pct=3, threshold=None, symbol="AAPL",
              repeat="once", cooldown_min=360)
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -5.0)})
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
        "AAPL": _q(90, -8.0),
        "KO":   _q(60, -6.0),
    })
    ae.evaluate_alerts(conn, only_user=1)
    assert conn.execute("SELECT active FROM alerts").fetchone()["active"] == 0
    # próximo ciclo: inactiva → 0 disparos
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0


# ── Horario de mercado + baseline "Desde ahora" (set_price) ──────────────────

def test_market_hours_gate_stock_vs_crypto(clean, monkeypatch):
    conn = clean
    _mk_alert(conn, kind="pct_move", symbol="AAPL", up_pct=1, threshold=None, baseline="prev_close")
    _mk_alert(conn, kind="pct_move", symbol="BTC", up_pct=1, threshold=None, baseline="prev_close", user_id=1)
    monkeypatch.setattr(ae, "_market_open_now", lambda now: False)   # mercado CERRADO
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {
        "AAPL": _q(200, 5.0),                    # acción: gateada → no dispara
        "BTC":  _q(65000, 5.0, sym="BTC"),       # cripto: 24/7 → dispara
    })
    res = ae.evaluate_alerts(conn, only_user=1)
    fired_syms = {e["symbol"] for e in _events(conn)}
    assert res["fired"] == 1 and fired_syms == {"BTC"}   # solo cripto


def _mk_setprice(conn, anchor, up=1, repeat="always"):
    cur = conn.execute(
        """INSERT INTO alerts (user_id,kind,scope,symbol,up_pct,baseline,anchor_price,
           repeat,cooldown_min,armed,active)
           VALUES (1,'pct_move','ticker','AAPL',?,'set_price',?,?,360,1,1)""",
        (up, anchor, repeat))
    conn.commit()
    return cur.lastrowid


def test_set_price_fires_vs_anchor_and_reanchors(clean, monkeypatch):
    conn = clean
    _mk_setprice(conn, anchor=250.0, up=1, repeat="always")
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 253.0})   # +1.2% vs 250
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    assert conn.execute("SELECT anchor_price FROM alerts").fetchone()["anchor_price"] == 253.0  # re-anclado
    # desde el nuevo anchor (253) sigue en 253 → 0% → no re-dispara
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
    # +1.2% desde 253 → dispara de nuevo (el "cada X%")
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 256.0})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1


def test_set_price_once_deactivates(clean, monkeypatch):
    conn = clean
    _mk_setprice(conn, anchor=100.0, up=1, repeat="once")
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 105.0})   # +5%
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    a = conn.execute("SELECT active,anchor_price FROM alerts").fetchone()
    assert a["active"] == 0 and a["anchor_price"] == 100.0   # once: no re-ancla, se apaga


# ─── Formato de plata (convención argentina) ────────────────────────────────
# Se testea a través de las funciones que ARMAN el mensaje (_compose_message
# arma el asunto, _email_detail arma el cuerpo), no contra fmt_money suelto:
# un test del primitivo pasaría en verde aunque el call site se olvide de
# usarlo, que es exactamente el bug que había.

def _alert(kind="pct_move", currency="USD", threshold=None,
           direction=None, baseline="prev_close"):
    return {"kind": kind, "currency": currency, "threshold": threshold,
            "direction": direction, "baseline": baseline, "id": 1}


def test_dolares_en_formato_argentino_en_asunto_y_cuerpo():
    """US$ 2.145,30 — punto de miles, coma decimal. Antes salía US$2,145.30."""
    a = _alert()
    assert "US$ 2.145,30" in ae._email_detail(a, "MELI", 2145.30, -3.14)
    c = _alert(kind="price_target", threshold=200.0, direction="above")
    assert "US$ 200,10" in ae._compose_message(c, "MSFT", 200.10, None)
    assert "US$ 200,00" in ae._email_detail(c, "MSFT", 200.10, None)


def test_pesos_siguen_con_punto_de_miles_y_sin_decimales():
    d = _alert(currency="ARS")
    assert "$7.350" in ae._email_detail(d, "GGAL.BA", 7350.0, 3.0)


def test_el_cuerpo_del_mail_trae_los_numeros_y_no_manda_a_buscarlos():
    """El bug original: el cuerpo decía 'entrá a Rendi para ver' y el asunto
    informaba más que el mail. El cuerpo tiene que traer % y precio."""
    body = ae._email_detail(_alert(), "MELI", 2145.30, -3.14)
    assert "3,1%" in body and "US$ 2.145,30" in body
    assert "Entrá a Rendi" not in body


# ─── Que el aviso sea del DÍA que dice ──────────────────────────────────────
# El 15/09/2026 a las 10:01 de Buenos Aires salieron cuatro mails —INTC −5,8%,
# ADBE +4,1%, NVDA −3,4%, NFLX +3,4%— con el título "hoy". Los cuatro números
# eran el cierre a cierre del LUNES, medido al centavo. A esa hora no había
# ninguna rueda abierta (Nueva York abre 10:30 ART en verano, BYMA 11:00), así
# que el proveedor todavía servía las barras de ayer y anteayer.


def test_el_movimiento_de_ayer_no_dispara_aunque_el_mercado_este_abierto(clean, monkeypatch):
    conn = clean
    _mk_alert(conn, kind="pct_move", symbol="AAPL", up_pct=3, down_pct=3,
              threshold=None, repeat="always")
    # Mercado "abierto" a propósito: el guard que importa no es el reloj.
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -5.8, hoy=False)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
    assert _events(conn) == []


def test_el_movimiento_de_ayer_tampoco_re_arma(clean, monkeypatch):
    """La puerta real por la que se coló. El tope de "1 aviso por jornada" ya
    existía y el edge-trigger también: lo que faltaba es que un número viejo no
    cuente como "volvió adentro de la banda". De madrugada el proveedor alterna
    entre la barra de ayer y una barra del día sin datos; con esa oscilación el
    símbolo se re-armaba solo y a la mañana siguiente disparaba con el
    porcentaje de ayer."""
    conn = clean
    _mk_alert(conn, kind="pct_move", symbol="AAPL", down_pct=3, threshold=None,
              repeat="always")
    # Ayer disparó de verdad.
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -5.0)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    conn.execute("UPDATE alert_symbol_state SET last_fired_date='2000-01-01'"); conn.commit()
    # De madrugada llega un 0% que NO es de hoy: no puede re-armar.
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(100, 0.0, hoy=False)})
    ae.evaluate_alerts(conn, only_user=1)
    assert conn.execute("SELECT armed FROM alert_symbol_state").fetchone()["armed"] == 0
    # …y a la mañana, con el −5% de ayer todavía servido, sigue sin disparar.
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -5.0, hoy=False)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0


def test_la_rueda_de_hoy_si_dispara(clean, monkeypatch):
    """Control positivo: el guard no puede ser "nunca avisar"."""
    conn = clean
    _mk_alert(conn, kind="pct_move", symbol="AAPL", down_pct=3, threshold=None)
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -5.0)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1


def test_quote_sin_fecha_de_rueda_no_dispara(clean, monkeypatch):
    """"No sé de qué rueda es" tiene que pesar igual que "es vieja"."""
    conn = clean
    _mk_alert(conn, kind="pct_move", symbol="AAPL", down_pct=3, threshold=None)
    monkeypatch.setattr(ae, "_quotes_for",
                        lambda syms: {"AAPL": {"price": 90, "change_pct": -5.0}})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0


def test_la_barra_del_dia_en_NaN_no_se_hace_pasar_por_hoy(monkeypatch):
    """Atraviesa el camino de producción: se le da a `_fetch_batch_quotes` la
    forma EXACTA que devuelve yfinance cuando la barra de hoy viene con los OHLC
    en NaN (pasa seguido con los `.BA`, ver project_ba_nan_bar). El `dropna()`
    la descarta en silencio y quedan ayer y anteayer — el porcentaje sale igual,
    pero ahora sale marcado."""
    import numpy as np
    import pandas as pd
    from home import market as hm

    hoy = date.fromisoformat(hm.session_today("INTC.BA"))
    fechas = pd.to_datetime([(hoy - timedelta(days=d)).isoformat() for d in (4, 1, 0)])
    df = pd.concat(
        {"INTC.BA": pd.DataFrame({"Close": [32920.0, 31020.0, np.nan]}, index=fechas)},
        axis=1)
    monkeypatch.setattr(hm.yf, "download", lambda *a, **k: df)
    hm._QUOTE_CACHE.clear()
    q = hm._fetch_batch_quotes(["INTC.BA"])["INTC.BA"]
    assert q["change_pct"] == -5.77                       # el número de AYER
    assert q["as_of"] == (hoy - timedelta(days=1)).isoformat()
    assert q["is_today"] is False                          # …y ahora lo dice
    hm._QUOTE_CACHE.clear()


# ─── El reloj: a las 13:01 UTC no hay ninguna rueda abierta ─────────────────

def test_a_las_13_01_utc_no_hay_ninguna_rueda_abierta():
    """La ventana vieja ("13:00–21:00 UTC") abría media hora antes que Nueva
    York y una hora antes que BYMA. Ese hueco es el de la ráfaga del 15/09."""
    martes = "2026-09-15T{}:00"                            # horario de verano en EE.UU.
    def abierto(hhmm):
        return _RELOJ_REAL(datetime.fromisoformat(martes.format(hhmm)))
    assert abierto("13:01") is False    # NY 09:01 · BYMA 10:01 — el bug
    assert abierto("13:29") is False    # un minuto antes de la campana de NY
    assert abierto("13:35") is True     # NY ya abrió
    assert abierto("14:30") is True     # las dos abiertas
    assert abierto("19:59") is True     # NY todavía no cerró
    assert abierto("20:30") is False    # cerraron las dos
    # Sábado: no hay rueda ni en el medio del horario.
    assert _RELOJ_REAL(datetime.fromisoformat("2026-09-19T15:00:00")) is False


def test_el_reloj_se_corre_solo_con_el_horario_de_verano_de_eeuu():
    """En invierno del norte la misma hora UTC cae en otra hora de Nueva York.
    Un offset fijo acierta en una mitad del año y erra en la otra."""
    def abierto(iso):
        return _RELOJ_REAL(datetime.fromisoformat(iso))
    assert abierto("2026-01-13T14:05:00") is True    # NY 09:05 cerrado, pero BYMA 11:05 abierto
    assert abierto("2026-01-13T13:30:00") is False   # en invierno NY abre recién 14:30 UTC
    assert abierto("2026-01-13T20:30:00") is True    # …y cierra 21:00 UTC, no 20:00
    assert abierto("2026-09-15T20:30:00") is False   # la misma hora en verano: cerrado


# ─── La moneda sale del activo, no de la fila de la alerta ──────────────────

def test_la_moneda_sale_del_activo_y_no_de_la_fila_de_la_alerta():
    """El mail decía "INTC cayó 5,8% … y cotiza a US$ 31.020,00". Esos 31.020
    eran PESOS: es el CEDEAR en BYMA. Una alerta de "toda mi cartera" guarda UNA
    moneda al crearse y después se expande a tenencias de los dos rieles, así
    que la moneda tiene que salir del símbolo que disparó."""
    a = _alert(currency="USD")                      # lo que guarda una alerta de cartera
    cuerpo = ae._email_detail(a, "INTC.BA", 31020.0, -5.77)
    assert "$31.020" in cuerpo and "US$" not in cuerpo
    assert "US$" not in ae._compose_message(
        _alert(kind="price_target", currency="USD", threshold=30000.0, direction="below"),
        "INTC.BA", 31020.0, None)
    # …y el activo que sí está en dólares no se toca, con la misma alerta.
    assert "US$ 212,29" in ae._email_detail(a, "NVDA", 212.29, -3.4)


# ─── El tope diario cuenta la JORNADA, no el día de Greenwich ──────────────

def test_el_tope_diario_es_la_jornada_argentina_y_no_el_dia_utc(clean, monkeypatch):
    """`utcnow()` cambia de día a las 21:00 de Buenos Aires. Un aviso disparado
    a las 22:00 quedaba anotado con la fecha de MAÑANA y se comía el cupo del
    día siguiente."""
    import fechas
    conn = clean
    _mk_alert(conn, kind="pct_move", symbol="AAPL", down_pct=3, threshold=None,
              repeat="always")

    class _Reloj(datetime):                     # 22:00 ART del martes = 01:00 UTC del miércoles
        @classmethod
        def utcnow(cls):
            return datetime(2026, 9, 16, 1, 0, 0)
    monkeypatch.setattr(fechas, "datetime", _Reloj)

    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90, -5.0)})
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    anotado = conn.execute("SELECT last_fired_date FROM alert_symbol_state").fetchone()[0]
    assert anotado == "2026-09-15"              # la jornada, no el 16 de UTC


def test_e2e_la_rafaga_del_15_09_no_vuelve_a_salir(clean, monkeypatch):
    """La prueba entera, sin mockear el quote: se le dan a yfinance las barras
    con la forma que tenían el 15/09 a las 13:01 UTC —viernes, lunes, y la del
    día sin datos— y corre el motor completo (`_quotes_for` →
    `_fetch_batch_quotes` → `evaluate_alerts`).

    El mercado está declarado ABIERTO a propósito: la ráfaga no se frena por el
    reloj, se frena porque el número no es de la rueda de hoy. Los porcentajes
    son los reales, medidos contra BYMA: INTC −5,77 %, ADBE +4,11 %."""
    import numpy as np
    import pandas as pd
    from home import market as hm

    conn = clean
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None,
              up_pct=3, down_pct=3, threshold=None, repeat="always")
    monkeypatch.setattr(ae, "_holding_symbols",
                        lambda c, u: ["INTC.BA", "ADBE.BA", "NVDA.BA", "NFLX.BA"])

    hoy = date.fromisoformat(hm.session_today("INTC.BA"))
    fechas = pd.to_datetime([(hoy - timedelta(days=d)).isoformat() for d in (4, 1, 0)])
    #                viernes    lunes
    cierres = {"INTC.BA": (32920.0, 31020.0),     # −5,77 %
               "ADBE.BA": (9240.0, 9620.0),       # +4,11 %
               "NVDA.BA": (14580.0, 14080.0),     # −3,43 %
               "NFLX.BA": (2587.5, 2675.0)}       # +3,38 %

    def _barras(hoy_close):
        return pd.concat(
            {s: pd.DataFrame({"Close": [v, l, hoy_close(s, l)]}, index=fechas)
             for s, (v, l) in cierres.items()}, axis=1)

    # 13:01 UTC: la barra del día todavía no tiene datos.
    monkeypatch.setattr(hm.yf, "download", lambda *a, **k: _barras(lambda s, l: np.nan))
    hm._QUOTE_CACHE.clear()
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 0
    assert _events(conn) == []

    # Abre BYMA y llegan los precios de hoy: INTC apenas +1,3 % (no avisa) y
    # NFLX −3,2 % (sí). Es el día real: el martes INTC subió, no cayó 5,8 %.
    hoy_real = {"INTC.BA": 31420.0, "ADBE.BA": 9450.0, "NVDA.BA": 14140.0, "NFLX.BA": 2590.0}
    monkeypatch.setattr(hm.yf, "download", lambda *a, **k: _barras(lambda s, l: hoy_real[s]))
    hm._QUOTE_CACHE.clear()
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 1
    assert _events(conn)[0]["symbol"] == "NFLX.BA"
    assert _events(conn)[0]["message"] == "NFLX cayó 3,2% hoy"
    hm._QUOTE_CACHE.clear()


# ─── Un mail por alerta, no uno por activo ──────────────────────────────────
# El 15/09/2026 a las 10:01 salieron CUATRO mails en el mismo minuto, uno por
# cada CEDEAR que había cruzado el 3 %. Una alerta de "toda mi cartera" se
# expande a todas las tenencias, así que un día movido son muchos avisos a la
# vez. Van en uno solo. Los avisos DE LA APP siguen siendo uno por activo: se
# movieron cuatro cosas, no una.


@pytest.fixture
def buzon(monkeypatch):
    """Intercepta un escalón más abajo que el fixture general: la entrega real
    corre entera (arma el asunto, la lista y el push) y lo único mockeado es el
    envío. Si mockeáramos `_deliver`, el agrupado no se probaría nunca."""
    import main as _main
    from billing import emails as _emails
    mails, pushes = [], []
    monkeypatch.setattr(ae, "_deliver", _ENTREGA_REAL)
    monkeypatch.setattr(_main, "_send_push_to_user",
                        lambda uid, payload: (pushes.append(payload), 1)[1])
    monkeypatch.setattr(_emails, "send_alert_email",
                        lambda **kw: (mails.append(kw), True)[1])
    return mails, pushes


def test_toda_la_cartera_manda_un_solo_mail_con_la_lista(clean, buzon, monkeypatch):
    conn = clean
    mails, pushes = buzon
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None,
              up_pct=3, down_pct=3, threshold=None, repeat="always", channel="both")
    monkeypatch.setattr(ae, "_holding_symbols",
                        lambda c, u: ["INTC.BA", "NVDA.BA", "NFLX.BA", "KO"])
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {
        "INTC.BA": _q(31020.0, -5.8, sym="INTC.BA"),
        "NVDA.BA": _q(14080.0, -3.4, sym="NVDA.BA"),
        "NFLX.BA": _q(2675.0, 3.4, sym="NFLX.BA"),
        "KO": _q(60.0, 0.4, sym="KO"),           # no cruza: no entra en el mail
    })
    assert ae.evaluate_alerts(conn, only_user=1)["fired"] == 3

    assert len(mails) == 1 and len(pushes) == 1        # UN mail y UN push
    m = mails[0]
    assert m["lines"] == [                             # ordenado por tamaño del movimiento
        "INTC cayó 5,8% y cotiza a $31.020",
        "NVDA cayó 3,4% y cotiza a $14.080",
        "NFLX subió 3,4% y cotiza a $2.675",
    ]
    assert m["heading"] == "INTC cayó 5,8%, NVDA cayó 3,4% y 1 más hoy"
    assert "se movieron 3 activos de tu cartera hoy" in m["detail"]
    # …y en la app siguen siendo tres avisos, los tres marcados como entregados.
    ev = _events(conn)
    assert [e["symbol"] for e in ev] == ["INTC.BA", "NVDA.BA", "NFLX.BA"]
    assert all(e["delivered_email"] == 1 and e["delivered_push"] == 1 for e in ev)


def test_dos_activos_se_nombran_los_dos(clean, buzon, monkeypatch):
    conn = clean
    mails, _ = buzon
    _mk_alert(conn, kind="pct_move", scope="holdings", symbol=None, channel="both",
              up_pct=3, down_pct=3, threshold=None, repeat="always")
    monkeypatch.setattr(ae, "_holding_symbols", lambda c, u: ["AAPL", "KO"])
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {
        "AAPL": _q(90.0, -8.0), "KO": _q(60.0, 11.0)})
    ae.evaluate_alerts(conn, only_user=1)
    assert mails[0]["heading"] == "KO subió 11% y AAPL cayó 8% hoy"


def test_un_solo_activo_manda_el_mail_de_siempre(clean, buzon, monkeypatch):
    """El agrupado no puede cambiarle el mail al que se movió uno solo."""
    conn = clean
    mails, pushes = buzon
    aid = _mk_alert(conn, kind="pct_move", symbol="AAPL", down_pct=3,
                    threshold=None, channel="both")
    monkeypatch.setattr(ae, "_quotes_for", lambda syms: {"AAPL": _q(90.0, -5.0)})
    ae.evaluate_alerts(conn, only_user=1)
    assert len(mails) == 1
    assert mails[0]["heading"] == "AAPL cayó 5% hoy"
    assert mails[0]["lines"] is None
    assert mails[0]["detail"] == "AAPL cayó 5% desde el cierre de ayer y cotiza a US$ 90,00."
    assert pushes[0]["tag"] == f"alert-{aid}-AAPL"     # el tag por activo, como antes


def test_el_mail_agrupado_arma_la_lista_en_html_y_en_texto(monkeypatch):
    """Que el `lines` llegue hasta el mail de verdad, no sólo al motor."""
    from billing import emails as _emails
    capturado = {}
    monkeypatch.setattr(_emails, "_send",
                        lambda to, subject, html_, text, **kw:
                        capturado.update(subject=subject, html=html_, text=text) or True)
    _emails.send_alert_email(to="a@a.co", user_name="nicolas",
                             heading="INTC cayó 5,8% y NVDA cayó 3,4% hoy",
                             detail="se movieron 2 activos de tu cartera hoy:",
                             lines=["INTC cayó 5,8% y cotiza a $31.020",
                                    "NVDA cayó 3,4% y cotiza a $14.080"])
    assert capturado["subject"] == "INTC cayó 5,8% y NVDA cayó 3,4% hoy"
    assert "<li" in capturado["html"] and "INTC cayó 5,8% y cotiza a $31.020" in capturado["html"]
    assert "  · NVDA cayó 3,4% y cotiza a $14.080" in capturado["text"]
