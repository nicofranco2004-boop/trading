"""Aviso de precio de un CEDEAR en dólares (AAPL en la Bolsa como AAPLD).

El caso de Nico (20/10): el formulario dejaba poner «AAPL (CEDEAR) baja a
US$ 15», pero la moneda era sólo un rótulo — el motor comparaba 15 contra el
precio EN PESOS (~$27.780) y no avisaba nunca.

Las alertas se crean por `POST /api/alerts` (el camino de la app) y se evalúan
con `evaluate_alerts` (el del cron). Lo único simulado es la red: el feed de la
Bolsa (`_fetch_data912_equities`, el mismo que arma la lista del buscador de
"Registrar compra") y el precio en pesos (`_prices_for`).
"""
from __future__ import annotations
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                      # noqa: E402
import alerts_engine as ae       # noqa: E402

# Recorte del feed real del 20/10 (ver test_cedears_dolar): MEP implícito ~1.540.
_FEED = {k: {'c': c, 'v': 100.0, 'pct': 0.0, 'mercado': 'arg_cedears'} for k, c in {
    'AAPL': 27780, 'AAPLD': 18.04,
    'SPY': 20780, 'SPYD': 13.52,
    'KO': 30300, 'KOD': 19.65,
    'ABEV3': 3100,                 # CEDEAR sin especie en dólares
}.items()}


@pytest.fixture
def h(monkeypatch):
    conn = main.get_db()
    for t in ("alert_symbol_state", "alert_events", "alerts"):
        conn.execute(f"DELETE FROM {t}")
    uid = conn.execute("INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'plus')",
                       (f"ced-usd-{uuid.uuid4().hex}@rendi.test", "x")).lastrowid
    conn.commit()
    conn.close()
    monkeypatch.setattr(main, "_fetch_data912_equities", lambda: _FEED)
    monkeypatch.setattr(main, "_current_cedear_rate", lambda: 1540.0)
    monkeypatch.setitem(main._CEDEARS_ULTIMO, "items", None)
    monkeypatch.setitem(main._CEDEARS_ULTIMO, "n_feed", 0)
    # El precio en pesos del riel .BA (lo que ya usaba el motor).
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {
        s: {'AAPL.BA': 27780.0, 'ABEV3.BA': 3100.0}.get(s) for s in syms})
    monkeypatch.setattr(ae, "_deliver", lambda *a, **k: (True, False))
    monkeypatch.setattr(ae, "_market_open_now", lambda now: True)
    return {"uid": uid, "c": TestClient(main.app),
            "auth": {"Authorization": f"Bearer {main.create_token(uid)}"}}


def _crear(h, **kw):
    pedido = {"kind": "price_target", "scope": "ticker", "channel": "push", "repeat": "once", **kw}
    return h["c"].post("/api/alerts", json=pedido, headers=h["auth"])


def _evaluar(h):
    conn = main.get_db()
    try:
        return ae.evaluate_alerts(conn, only_user=h["uid"])
    finally:
        conn.close()


def _eventos(h):
    conn = main.get_db()
    try:
        return conn.execute("SELECT * FROM alert_events WHERE user_id=? ORDER BY id",
                            (h["uid"],)).fetchall()
    finally:
        conn.close()


def _feed_con(monkeypatch, **precios):
    feed = {k: dict(v) for k, v in _FEED.items()}
    for k, c in precios.items():
        feed[k]['c'] = c
    monkeypatch.setattr(main, "_fetch_data912_equities", lambda: feed)
    main._CEDEARS_ULTIMO.update({"items": None, "n_feed": 0})


def test_cedear_en_dolares_avisa_al_precio_en_dolares(h, monkeypatch):
    r = _crear(h, symbol="AAPL.BA", currency="USD", direction="below", threshold=17.5)
    assert r.status_code == 200, r.text
    assert r.json()["current_price"] == 18.04          # el AAPLD, no los $27.780
    assert r.json()["armed"] is True                   # 18,04 está arriba de 17,5

    assert _evaluar(h)["fired"] == 0                   # todavía no bajó

    # AAPLD baja a 17,30 (y el CEDEAR en pesos acompaña, como en la Bolsa).
    _feed_con(monkeypatch, AAPL=26640, AAPLD=17.30)
    assert _evaluar(h)["fired"] == 1
    ev = _eventos(h)[-1]
    assert ev["price"] == 17.30
    assert "US$" in ev["message"] and "17,30" in ev["message"]


def test_el_mismo_cedear_en_pesos_sigue_mirando_los_pesos(h):
    r = _crear(h, symbol="AAPL.BA", currency="ARS", direction="above", threshold=27000)
    assert r.status_code == 200, r.text
    assert r.json()["current_price"] == 27780.0
    assert r.json()["armed"] is False                  # ya está arriba: espera a que baje y vuelva


def test_en_pesos_y_en_dolares_a_la_vez_cada_uno_con_su_precio(h, monkeypatch):
    assert _crear(h, symbol="AAPL.BA", currency="USD", direction="above", threshold=18.5).status_code == 200
    assert _crear(h, symbol="AAPL.BA", currency="ARS", direction="above", threshold=28500).status_code == 200
    # Sube el AAPLD pero no los pesos: sólo avisa la de dólares. (Dentro del 5 %
    # de pesos ÷ MEP: más lejos, la regla del buscador lo toma por un precio
    # raro y usa pesos ÷ MEP — ver cedears_dolar.TOLERANCIA_PRECIO_USD.)
    _feed_con(monkeypatch, AAPLD=18.9)
    assert _evaluar(h)["fired"] == 1
    assert "US$" in _eventos(h)[-1]["message"]


def test_la_trampa_del_selector_ya_no_existe(h):
    """Lo que hacía el formulario viejo: un CEDEAR sin especie en dólares con
    la moneda pasada a US$. Antes se guardaba y no avisaba nunca."""
    r = _crear(h, symbol="ABEV3.BA", currency="USD", direction="below", threshold=2)
    assert r.status_code == 400
    assert "dólares" in r.json()["detail"]


def test_una_accion_de_eeuu_no_se_marca_en_pesos(h):
    r = _crear(h, symbol="AAPL", currency="ARS", direction="above", threshold=300000)
    assert r.status_code == 400
    assert "US$" in r.json()["detail"]


def test_sin_moneda_va_la_del_activo(h):
    conn = main.get_db()
    try:
        _crear(h, symbol="AAPL.BA", direction="above", threshold=30000)
        _crear(h, symbol="AAPL", direction="above", threshold=300)
        filas = conn.execute("SELECT symbol, currency FROM alerts WHERE user_id=? ORDER BY id",
                             (h["uid"],)).fetchall()
    finally:
        conn.close()
    assert [tuple(f) for f in filas] == [("AAPL.BA", "ARS"), ("AAPL", "USD")]


def test_sin_la_lista_de_la_bolsa_no_se_rechaza_ni_se_adivina(h, monkeypatch):
    """data912 caído: no se sabe si tiene especie en dólares. Se guarda (no es
    culpa del usuario) y el motor no dispara sin precio."""
    monkeypatch.setattr(main, "_fetch_data912_equities", lambda: {})
    r = _crear(h, symbol="AAPL.BA", currency="USD", direction="below", threshold=50)
    assert r.status_code == 200, r.text
    assert r.json()["resolved"] is False
    assert _evaluar(h)["fired"] == 0


def test_toda_mi_cartera_no_se_vuelve_dolares_por_la_moneda_guardada(h):
    """Una alerta de % de toda la cartera guarda una moneda cualquiera: los
    CEDEARs que dispara siguen en su riel (pesos)."""
    a = {"kind": "pct_move", "scope": "holdings", "currency": "USD"}
    assert ae.cedear_en_dolares(a["kind"], a["scope"], "AAPL.BA", a["currency"]) is False
    assert ae._moneda(a, "AAPL.BA") == "ARS"
