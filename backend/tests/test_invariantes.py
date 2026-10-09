"""Los chequeos de invariantes post-import.

La regla de diseño es CERO FALSOS POSITIVOS: un chequeo que marca datos sanos
deja de mirarse a la semana y entonces no sirve para nada. Por eso cada test va
en dos direcciones — que salte con el dato roto Y que se quede callado con el
dato legítimo parecido.

Corre con: cd backend && python3 -m pytest tests/test_invariantes.py
"""
import os
import sqlite3
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.invariantes import (                                  # noqa: E402
    correr, check_moneda_posicion_vs_broker, check_broker_inexistente,
    check_costo_no_positivo, check_subbroker_usd_bien_formado, check_cash_moneda,
    check_caja_concilia, check_receta_con_broker_inexistente,
    check_futuro_abierto_sin_broker,
)

UID = 77


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE brokers (id INTEGER PRIMARY KEY, user_id INT, name TEXT,
                              currency TEXT, parent_broker_id INT);
        CREATE TABLE positions (id INTEGER PRIMARY KEY, user_id INT, broker TEXT,
                                asset TEXT, is_cash INT DEFAULT 0, buy_price REAL,
                                quantity REAL, invested REAL, currency TEXT,
                                asset_type TEXT, undo_meta_json TEXT);
        CREATE TABLE import_batches (id TEXT PRIMARY KEY, user_id INT, status TEXT);
        CREATE TABLE import_normalized_tx (id INTEGER PRIMARY KEY, batch_id TEXT,
                                           broker TEXT, currency TEXT,
                                           gross_amount REAL, notes TEXT);
        CREATE TABLE operations (id INTEGER PRIMARY KEY, user_id INT, broker TEXT,
                                 asset TEXT, undo_meta_json TEXT);
        CREATE TABLE archived_positions (id INTEGER PRIMARY KEY, user_id INT, payload TEXT);
        CREATE TABLE futures_positions (id INTEGER PRIMARY KEY, user_id INT, broker TEXT,
                                        symbol TEXT, closed_at TEXT);
    """)
    yield conn
    conn.close()


def _broker(db, name, ccy, parent=None):
    db.execute("INSERT INTO brokers (user_id,name,currency,parent_broker_id) VALUES (?,?,?,?)",
               (UID, name, ccy, parent))
    return db.execute("SELECT last_insert_rowid() i").fetchone()["i"]


def _pos(db, broker, asset, ccy, qty=10, invested=1000.0, is_cash=0):
    db.execute("""INSERT INTO positions (user_id,broker,asset,is_cash,quantity,invested,currency)
                  VALUES (?,?,?,?,?,?,?)""", (UID, broker, asset, is_cash, qty, invested, ccy))


# ── 1. moneda de la posición vs la del broker ────────────────────────────────

def test_pesos_en_broker_dolar_es_error(db):
    """El bug reportado: el export de Balanz no anclaba la moneda, el broker
    nacía en USD y los pesos del usuario quedaban adentro."""
    _broker(db, "Balanz", "USD")
    _pos(db, "Balanz", "GGAL", "ARS")
    v = check_moneda_posicion_vs_broker(db, UID)
    assert len(v) == 1 and v[0]["severidad"] == "error"
    assert "GGAL" in v[0]["que_pasa"]


def test_dolares_en_broker_ars_NO_es_error(db):
    """El modelo admite same-broker dual-currency (un CEDEAR pagado por MEP) y
    hay lotes viejos con currency en NULL. Marcarlos sería un falso positivo."""
    _broker(db, "Cocos", "ARS")
    _pos(db, "Cocos", "AAPL", "USD")
    _pos(db, "Cocos", "YPFD", None)
    assert check_moneda_posicion_vs_broker(db, UID) == []


def test_la_cuenta_sana_no_dispara_nada(db):
    """La prueba de fondo del diseño: datos correctos, cero ruido."""
    pid = _broker(db, "Cocos", "ARS")
    _broker(db, "Cocos · USD", "USDT", parent=pid)
    _pos(db, "Cocos", "GGAL", "ARS")
    _pos(db, "Cocos · USD", "AAPL", "USD")
    _pos(db, "Cocos", "ARS", "ARS", qty=5000, invested=0, is_cash=1)
    _pos(db, "Cocos · USD", "USD", "USD", qty=300, invested=0, is_cash=1)
    r = correr(db, UID)
    assert r["ok"] is True, r["violaciones"]
    assert r["errores"] == 0 and r["avisos"] == 0


# ── 2. broker inexistente ────────────────────────────────────────────────────

def test_posicion_con_broker_que_no_existe(db):
    """Los brokers se linkean por NOMBRE. Sin la fila, la moneda cae al default
    'USDT' del persister y la cuenta entera se lee en dólares."""
    _pos(db, "BrokerFantasma", "GGAL", "ARS")
    v = check_broker_inexistente(db, UID)
    assert len(v) == 1 and v[0]["detalle"]["broker"] == "BrokerFantasma"


def test_no_marca_posiciones_en_cero(db):
    """Una posición cerrada (quantity 0) no tiene por qué tener broker vivo."""
    _pos(db, "BrokerViejo", "GGAL", "ARS", qty=0)
    assert check_broker_inexistente(db, UID) == []


# ── 3. costo no positivo ─────────────────────────────────────────────────────

def test_tenencia_con_costo_cero_o_negativo(db):
    _broker(db, "Cocos", "ARS")
    _pos(db, "Cocos", "GGAL", "ARS", invested=0)
    _pos(db, "Cocos", "PAMP", "ARS", invested=-5000)
    assert len(check_costo_no_positivo(db, UID)) == 2


def test_el_cash_no_cuenta_como_costo_no_positivo(db):
    """La caja tiene invested=0 por diseño: no es una tenencia comprada."""
    _broker(db, "Cocos", "ARS")
    _pos(db, "Cocos", "ARS", "ARS", qty=5000, invested=0, is_cash=1)
    assert check_costo_no_positivo(db, UID) == []


# ── 4. sub-broker dólar bien formado ─────────────────────────────────────────

def test_subbroker_sin_padre_o_en_pesos(db):
    _broker(db, "Balanz · USD", "USDT", parent=None)      # suelto
    _broker(db, "IOL · USD", "ARS", parent=1)             # marcado en pesos
    v = check_subbroker_usd_bien_formado(db, UID)
    assert len(v) == 2
    assert any("no cuelga" in x["que_pasa"] for x in v)
    assert any("ARS" in x["que_pasa"] for x in v)


def test_subbroker_bien_formado_no_dispara(db):
    pid = _broker(db, "Balanz", "ARS")
    _broker(db, "Balanz · USD", "USDT", parent=pid)
    assert check_subbroker_usd_bien_formado(db, UID) == []


# ── 5. cash cruzado ──────────────────────────────────────────────────────────

def test_caja_en_pesos_dentro_de_un_broker_dolar(db):
    _broker(db, "Schwab", "USD")
    _pos(db, "Schwab", "ARS", "ARS", qty=100000, invested=0, is_cash=1)
    v = check_cash_moneda(db, UID)
    assert len(v) == 1 and v[0]["severidad"] == "aviso"


def test_caja_en_cero_no_dispara(db):
    """Un saldo residual de redondeo no es plata en la moneda equivocada."""
    _broker(db, "Schwab", "USD")
    _pos(db, "Schwab", "ARS", "ARS", qty=0.001, invested=0, is_cash=1)
    assert check_cash_moneda(db, UID) == []


# ── el runner ────────────────────────────────────────────────────────────────

def test_el_resumen_cuenta_TODO_aunque_la_muestra_este_topeada(db):
    """Un tope que además achica el número reportado hace leer '200 problemas'
    donde hay 505. Los totales van sobre todo; la muestra dice qué no listó."""
    _broker(db, "Balanz", "USD")
    for i in range(7):
        _pos(db, "Balanz", f"T{i}", "ARS")
    r = correr(db, UID, limite_por_chequeo=3)
    assert r["errores"] == 7, "el total tiene que contar las 7"
    assert len(r["violaciones"]) == 3
    assert r["no_listadas"]["check_moneda_posicion_vs_broker"] == 4


def test_un_chequeo_roto_no_tumba_a_los_demas(db):
    import importing.invariantes as inv
    def explota(conn, uid=None):
        raise RuntimeError("boom")
    orig = inv.CHEQUEOS
    inv.CHEQUEOS = (explota,) + orig
    try:
        _broker(db, "Balanz", "USD")
        _pos(db, "Balanz", "GGAL", "ARS")
        r = correr(db, UID)
        assert r["errores"] == 1, "los demás tienen que haber corrido igual"
        assert "explota" in r["chequeos_rotos"]
        assert r["ok"] is False
    finally:
        inv.CHEQUEOS = orig


# ── 6. la caja concilia contra el resumen ────────────────────────────────────

def _batch(db, bid, status="confirmed"):
    db.execute("INSERT INTO import_batches (id,user_id,status) VALUES (?,?,?)",
               (bid, UID, status))


def _tx(db, bid, broker, notes, amt=0.0, ccy="ARS"):
    db.execute("""INSERT INTO import_normalized_tx (batch_id,broker,currency,gross_amount,notes)
                  VALUES (?,?,?,?,?)""", (bid, broker, ccy, amt, notes))


def test_ajuste_grande_con_movimientos_es_aviso(db):
    """La plata que los movimientos no explicaron. Es el rastro que deja una fila
    perdida en silencio: no hay error, pero el efectivo no cierra."""
    _batch(db, "b1"); _tx(db, "b1", "Cocos", "Compra GGAL", 1000.0)
    _batch(db, "b2"); _tx(db, "b2", "Cocos", "Ajuste de cash a Estado de Cuenta (ARS)", 3_000_000.0)
    v = check_caja_concilia(db, UID)
    assert len(v) == 1
    assert v[0]["severidad"] == "aviso", "no puede ser error: un rango parcial lo explica igual"
    assert v[0]["detalle"]["ajuste"] == 3_000_000.0


def test_sin_movimientos_no_hay_nada_que_conciliar(db):
    """Subir sólo la foto es un uso legítimo: no hay movimientos contra los cuales
    la caja pudiera cerrar."""
    _batch(db, "b1"); _tx(db, "b1", "Cocos", "Tenencia — apertura GGAL")
    _tx(db, "b1", "Cocos", "Ajuste de cash a Estado de Cuenta (ARS)", 3_000_000.0)
    assert check_caja_concilia(db, UID) == []


def test_el_polvo_de_redondeo_no_avisa(db):
    _batch(db, "b1"); _tx(db, "b1", "Cocos", "Compra GGAL", 1000.0)
    _batch(db, "b2"); _tx(db, "b2", "Cocos", "Ajuste de cash a Estado de Cuenta (ARS)", 800.0)
    _batch(db, "b3"); _tx(db, "b3", "Schwab", "Ajuste de cash a Estado de Cuenta (USD)", 12.0, "USD")
    assert check_caja_concilia(db, UID) == []


def test_un_batch_sin_confirmar_no_cuenta(db):
    """Un preview que el usuario nunca confirmó no tocó los datos de nadie."""
    _batch(db, "b1"); _tx(db, "b1", "Cocos", "Compra GGAL", 1000.0)
    _batch(db, "b2", status="preview")
    _tx(db, "b2", "Cocos", "Ajuste de cash a Estado de Cuenta (ARS)", 3_000_000.0)
    assert check_caja_concilia(db, UID) == []


def test_los_avisos_no_hacen_fallar_el_ok(db):
    """`ok` es sobre ERRORES. Un aviso es "mirá esto", no "está roto" — si un
    aviso tumbara el ok, el resultado dejaría de servir para decidir."""
    _batch(db, "b1"); _tx(db, "b1", "Cocos", "Compra GGAL", 1000.0)
    _batch(db, "b2"); _tx(db, "b2", "Cocos", "Ajuste de cash a Estado de Cuenta (ARS)", 3_000_000.0)
    r = correr(db, UID)
    assert r["avisos"] == 1 and r["errores"] == 0
    assert r["ok"] is True


# ── 7. recetas que nombran un broker que no existe ───────────────────────────
def test_receta_con_el_nombre_viejo_de_un_broker_es_aviso(db):
    """Lo que dejaba renombrar un broker antes del 2026-10-09: la fila con el nombre
    nuevo, su receta (y la del lote, como texto adentro) con el viejo."""
    import json
    _broker(db, "Cocos Capital", "ARS")
    db.execute("INSERT INTO operations (user_id, broker, asset, undo_meta_json) VALUES (?,?,?,?)",
               (UID, "Cocos Capital", "GGAL", json.dumps({
                   "src": "fifo_sell", "cash_broker": "Cocos",
                   "lot": {"broker": "Cocos", "undo_meta": json.dumps(
                       {"src": "manual_position", "broker": "Cocos"})}})))
    v = check_receta_con_broker_inexistente(db, UID)
    assert len(v) == 1 and v[0]["severidad"] == "aviso"
    assert v[0]["detalle"]["nombres"] == ["Cocos"] and v[0]["detalle"]["fila_en_broker_vivo"]


def test_receta_sana_y_texto_libre_no_disparan(db):
    """Un nombre que existe, o el nombre viejo en un campo que NO es de broker (una
    nota), no es una receta rota."""
    import json
    _broker(db, "Cocos", "ARS")
    db.execute("INSERT INTO operations (user_id, broker, asset, undo_meta_json) VALUES (?,?,?,?)",
               (UID, "Cocos", "GGAL", json.dumps({"src": "fifo_sell", "cash_broker": "Cocos",
                                                  "nota": "antes era Balanz"})))
    db.execute("INSERT INTO archived_positions (user_id, payload) VALUES (?,?)",
               (UID, json.dumps([{"broker": "Cocos", "asset": "AL30"}])))
    assert check_receta_con_broker_inexistente(db, UID) == []


def test_seccion_archivada_en_un_broker_que_no_existe_es_aviso(db):
    import json
    _broker(db, "Cocos", "ARS")
    db.execute("INSERT INTO archived_positions (user_id, payload) VALUES (?,?)",
               (UID, json.dumps([{"broker": "BP", "asset": "AL30"}])))
    v = check_receta_con_broker_inexistente(db, UID)
    assert [x["detalle"]["nombres"] for x in v] == [["BP"]]


# ── 8. futuros abiertos sin broker ───────────────────────────────────────────
def test_futuro_abierto_en_un_broker_que_no_existe_es_error(db):
    _broker(db, "Binance Futures", "USDT")
    db.execute("INSERT INTO futures_positions (user_id, broker, symbol) VALUES (?,?,?)",
               (UID, "Binance", "BTCUSDT"))
    v = check_futuro_abierto_sin_broker(db, UID)
    assert len(v) == 1 and v[0]["severidad"] == "error"


def test_futuro_cerrado_o_en_broker_vivo_no_dispara(db):
    """Cerrado ya acreditó (no mueve más plata); en un broker que existe, está bien."""
    _broker(db, "Binance", "USDT")
    db.execute("INSERT INTO futures_positions (user_id, broker, symbol) VALUES (?,?,?)",
               (UID, "Binance", "BTCUSDT"))
    db.execute("INSERT INTO futures_positions (user_id, broker, symbol, closed_at) VALUES (?,?,?,?)",
               (UID, "Viejo", "ETHUSDT", "2026-08-01"))
    assert check_futuro_abierto_sin_broker(db, UID) == []
