"""Los chequeos de invariantes post-import.

La regla de diseño es CERO FALSOS POSITIVOS: un chequeo que marca datos sanos
deja de mirarse a la semana y entonces no sirve para nada. Por eso cada test va
en dos direcciones — que salte con el dato roto Y que se quede callado con el
dato legítimo parecido.

Corre con: cd backend && python3 -m pytest tests/test_invariantes.py
"""
import io
import os
import sqlite3
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main                                                          # noqa: E402
from fastapi.testclient import TestClient                            # noqa: E402
from importing.invariantes import (                                  # noqa: E402
    correr, check_moneda_posicion_vs_broker, check_broker_inexistente,
    check_costo_no_positivo, check_subbroker_usd_bien_formado, check_cash_moneda,
    check_caja_concilia, check_receta_con_broker_inexistente,
    check_futuro_abierto_sin_broker, check_caja_vacia_con_precio,
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
                                asset_type TEXT, undo_meta_json TEXT, tc_compra REAL);
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


def _caja(db, broker, saldo, tc=None, rotulo="USDT", currency=None):
    """Una caja como la arma producción (`efectivo.mover`): el saldo en `invested`,
    `quantity` vacía, y `currency` vacía hasta que el arranque (init_db) la completa
    desde el rótulo. Hasta 2026-10-27 estos tests la armaban con el saldo en
    `quantity` —lo contrario de producción— y el chequeo de la caja cruzada, que
    filtraba por `quantity`, pasaba en verde sin poder disparar nunca."""
    db.execute("INSERT INTO positions (user_id,broker,asset,is_cash,invested,tc_compra,currency) "
               "VALUES (?,?,?,1,?,?,?)", (UID, broker, rotulo, saldo, tc, currency))


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
    _caja(db, "Cocos", 5000, rotulo="ARS", currency="ARS")
    _caja(db, "Cocos · USD", 300, rotulo="USDT", currency="USD")
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
    """La caja no es una tenencia comprada: su `invested` es el saldo, y un saldo en
    cero o en rojo es legítimo."""
    _broker(db, "Cocos", "ARS")
    _broker(db, "Balanz", "ARS")
    _caja(db, "Cocos", 0, rotulo="ARS")
    _caja(db, "Balanz", -70, rotulo="ARS")
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
    _caja(db, "Schwab", 100000, rotulo="ARS")
    v = check_cash_moneda(db, UID)
    assert len(v) == 1 and v[0]["severidad"] == "aviso"
    assert v[0]["detalle"]["marcas"] == ["asset"] and v[0]["detalle"]["saldo"] == 100000


def test_caja_en_rojo_cruzada_tambien_dispara(db):
    """Una deuda contada en la moneda equivocada también es plata mal contada."""
    _broker(db, "Cocos", "ARS")
    _caja(db, "Cocos", -250, rotulo="USD")
    assert len(check_cash_moneda(db, UID)) == 1


def test_caja_en_cero_no_dispara(db):
    """Un saldo residual de redondeo no es plata en la moneda equivocada. Tampoco un
    `quantity` viejo con la caja vacía: el saldo es `invested`."""
    _broker(db, "Schwab", "USD")
    _caja(db, "Schwab", 0.001, rotulo="ARS")
    db.execute("UPDATE positions SET quantity=100000 WHERE broker='Schwab'")
    assert check_cash_moneda(db, UID) == []


def test_caja_con_currency_cruzada_dispara(db):
    """El rótulo coincide con el broker pero `currency` no. Es la marca que lee
    PRIMERO `behavioral._native_ccy`: metas, reportes e insights de la IA
    (`_position_value_usd`) valúan esos pesos como dólares."""
    from behavioral import _position_value_usd
    _broker(db, "Cocos", "ARS")
    _caja(db, "Cocos", 1_500_000, rotulo="ARS", currency="USD")
    v = check_cash_moneda(db, UID)
    assert len(v) == 1 and v[0]["detalle"]["marcas"] == ["currency"]
    fila = dict(db.execute("SELECT * FROM positions WHERE broker='Cocos'").fetchone())
    assert _position_value_usd(fila, tc_blue=1000.0) == 1_500_000.0    # no US$1.500


def test_caja_sin_currency_o_con_la_del_broker_no_dispara(db):
    """`currency` vacía es la caja recién creada, antes de que el arranque la
    complete: `_native_ccy` cae al rótulo, que acá coincide. Y 'USD' en un broker
    'USDT' (el sub-broker "· USD", un exchange) es el mismo dólar."""
    pid = _broker(db, "Cocos", "ARS")
    _broker(db, "Cocos · USD", "USDT", parent=pid)
    _broker(db, "Binance", "USDT")
    _caja(db, "Cocos", 1_500_000, rotulo="ARS")
    _caja(db, "Cocos · USD", 500, rotulo="USDT", currency="USD")
    _caja(db, "Binance", 80, rotulo="USDT", currency="USD")
    assert check_cash_moneda(db, UID) == []


# ── 5b. cash cruzado, armado por las puertas reales ──────────────────────────
# Las cajas de arriba se arman a mano. Éstas las arma producción: la plantilla de
# Rendi entra por la vista previa y la confirmación HTTP, el arranque es
# `main.init_db`, y el chequeo se pide por `/api/admin/check-invariantes`, que es
# su único llamador.

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


class TestCajaCruzadaPorLasPuertasReales:

    @pytest.fixture(autouse=True)
    def _admin(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, 1)", (f"invariantes-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def importar(self, broker, filas):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("plantilla.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        assert r.status_code == 200, r.text
        assert r.json()["errors"] == []
        r = self.client.post("/api/imports/confirm", headers=self.h,
                             json={"session_id": r.json()["session_id"]})
        assert r.status_code == 200, r.text

    def sql(self, q, *a):
        conn = main.get_db()
        try:
            with conn:
                return [dict(r) for r in conn.execute(q, a).fetchall()]
        finally:
            conn.close()

    def cajas(self):
        return {r["broker"]: r for r in self.sql(
            "SELECT broker, asset, currency, quantity, invested FROM positions "
            "WHERE user_id=? AND is_cash=1", self.uid)}

    def cajas_cruzadas(self):
        r = self.client.get("/api/admin/check-invariantes", headers=self.h,
                            params={"user_id": self.uid})
        assert r.status_code == 200, r.text
        assert r.json()["chequeos_rotos"] == {}
        return [v for v in r.json()["violaciones"] if v["chequeo"] == "cash_moneda"]

    def test_la_cuenta_en_dos_monedas_no_dispara(self):
        """Pesos en el broker, dólares en "· USD": cada caja en la moneda de su broker,
        antes y después de que el arranque les complete `currency`."""
        self.importar("MiBroker", "2026-01-05,DEPOSITO,MiBroker,,,,1000000,,,,ARS,\n"
                                  "2026-01-06,DEPOSITO,MiBroker,,,,500,,,,USD,\n")
        cajas = self.cajas()
        # Así guarda producción la caja: el saldo en `invested`, nada en `quantity`.
        assert cajas["MiBroker"]["invested"] == 1_000_000.0
        assert cajas["MiBroker · USD"]["invested"] == 500.0
        assert not cajas["MiBroker"]["quantity"] and not cajas["MiBroker · USD"]["quantity"]
        assert self.cajas_cruzadas() == []
        main.init_db()
        assert {b: c["currency"] for b, c in self.cajas().items()} == {
            "MiBroker": "ARS", "MiBroker · USD": "USD"}
        assert self.cajas_cruzadas() == []

    def test_la_caja_que_quedo_en_la_otra_moneda_dispara(self):
        """Hasta 86a2559, cambiarle la moneda a un broker a mano (PUT /api/brokers/{id})
        cambiaba sólo `brokers.currency`: la caja seguía con el rótulo y la
        `currency` viejos. Es el daño que este chequeo vino a medir, y el que no
        podía ver mientras miraba `quantity`."""
        self.importar("MiIBKR", "2026-01-05,DEPOSITO,MiIBKR,,,,1000,,,,USD,\n")
        main.init_db()
        assert self.cajas_cruzadas() == []
        # La única escritura que hacía el PUT de entonces.
        self.sql("UPDATE brokers SET currency='ARS' WHERE user_id=? AND name='MiIBKR'", self.uid)
        v = self.cajas_cruzadas()
        assert len(v) == 1, v
        assert v[0]["detalle"]["broker"] == "MiIBKR" and v[0]["detalle"]["saldo"] == 1000.0
        assert v[0]["detalle"]["marcas"] == ["asset", "currency"]

    def test_el_cambio_de_moneda_de_hoy_no_deja_la_caja_cruzada(self):
        """El mismo cambio por el PUT de hoy lleva las dos marcas de la caja con la
        moneda (`escrituras_para_cambiar_moneda`): el chequeo no tiene nada que decir."""
        self.importar("MiIBKR", "2026-01-05,DEPOSITO,MiIBKR,,,,1000,,,,USD,\n")
        main.init_db()
        bid = self.sql("SELECT id FROM brokers WHERE user_id=? AND name='MiIBKR'", self.uid)[0]["id"]
        r = self.client.put(f"/api/brokers/{bid}", headers=self.h,
                            json={"name": "MiIBKR", "currency": "ARS"})
        assert r.status_code == 200, r.text
        assert (self.cajas()["MiIBKR"]["asset"], self.cajas()["MiIBKR"]["currency"]) == ("ARS", "ARS")
        assert self.cajas_cruzadas() == []


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


# ── 9. caja vacía con precio de compra ───────────────────────────────────────
def test_caja_vacia_o_en_rojo_con_precio_es_error(db):
    """El precio es de los dólares que hay. En cero, con centavos que la pantalla
    muestra como 0,00, o en rojo, el que quede guardado no es de ninguno."""
    for nombre, saldo in (("A · USD", 0.0), ("B · USD", 0.003), ("C · USD", -70.0)):
        _caja(db, nombre, saldo, 400.0)
    v = check_caja_vacia_con_precio(db, UID)
    assert sorted(x["detalle"]["broker"] for x in v) == ["A · USD", "B · USD", "C · USD"]
    assert {x["severidad"] for x in v} == {"error"}


def test_caja_con_dolares_y_precio_o_vacia_sin_precio_no_dispara(db):
    _caja(db, "A · USD", 100.0, 400.0)     # dólares comprados: el precio es de ellos
    _caja(db, "B · USD", 0.01, 400.0)      # un centavo ya es plata
    _caja(db, "C · USD", 0.0, None)        # vacía y sin precio: como tiene que quedar
    _caja(db, "D · USD", -70.0, None)
    _pos(db, "Balanz", "GGAL", "ARS", qty=0, invested=0)   # un lote no es una caja
    db.execute("UPDATE positions SET tc_compra=1000 WHERE asset='GGAL'")
    assert check_caja_vacia_con_precio(db, UID) == []
