"""La limpieza de las comisiones falsas ya escritas.

El guard del normalizer impide que entren nuevas; esto arregla las 469 que ya
están en la base y hacen que 78 usuarios vean pérdidas que no existen.

Es una escritura masiva sobre plata de gente, así que lo que estos tests fijan no
es tanto "borra bien" como las CUATRO garantías que la hacen segura:
  1. dry-run por defecto — hay que pedir apply=true explícitamente,
  2. no toca las comisiones legítimas (los USD 10 de Balanz son un fee real),
  3. guarda el valor viejo para poder revertir,
  4. y al guardarlo NO pisa el `undo_meta_json` que ya había — esa columna guarda
     el CAMINO de creación y la cascada de borrado lo lee.

Corre con: cd backend && python3 -m pytest tests/test_repair_comisiones.py
"""
import json
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402

UID = 5150


@pytest.fixture(autouse=True)
def _limpio():
    conn = main.get_db()
    with conn:
        conn.execute("DELETE FROM positions WHERE user_id=?", (UID,))
        conn.execute("DELETE FROM users WHERE id=?", (UID,))
        conn.execute("INSERT INTO users (id,email,password_hash,approved) VALUES (?,?,?,1)",
                     (UID, "repair@rendi.test", "h"))
    conn.close()
    yield


def _pos(asset, qty, buy, comm, undo=None, ccy="ARS"):
    conn = main.get_db()
    with conn:
        cur = conn.execute(
            """INSERT INTO positions (user_id,broker,asset,is_cash,quantity,buy_price,
                                      invested,commissions,undo_meta_json,currency)
               VALUES (?,?,?,0,?,?,?,?,?,?)""",
            (UID, "Balanz", asset, qty, buy, qty * buy, comm, undo, ccy))
        pid = cur.lastrowid
    conn.close()
    return pid


def _leer(pid):
    conn = main.get_db()
    try:
        return conn.execute(
            "SELECT commissions, undo_meta_json FROM positions WHERE id=?", (pid,)).fetchone()
    finally:
        conn.close()


def test_por_defecto_es_un_simulacro_y_NO_escribe():
    """LA garantía más importante. Un `apply` que fuera true por defecto convierte
    un 'a ver qué haría' en una escritura masiva irreversible."""
    pid = _pos("NFLX", 1234, 2473.0, 3_038_265.12)
    r = main.admin_repair_comisiones(uid=1)          # sin apply

    assert r["aplicado"] is False
    assert r["posiciones"] == 1
    assert "SIMULACRO" in r["siguiente_paso"]
    assert _leer(pid)["commissions"] == 3_038_265.12, "no tenía que tocar nada"


def test_con_apply_pone_la_comision_en_cero():
    pid = _pos("NFLX", 1234, 2473.0, 3_038_265.12)
    r = main.admin_repair_comisiones(apply=True, uid=1)

    assert r["aplicado"] is True
    assert _leer(pid)["commissions"] == 0


def test_no_toca_una_comision_legitima():
    """Los Balanz·USD con un fee real de USD 10, y una comisión del 0,55% de IOL.
    Si la limpieza se los llevara puestos, estaríamos rompiendo el cost basis de
    gente que estaba bien para arreglar a otra."""
    a = _pos("VST", 2, 140.43, 10.0)        # fee real, 3,6%
    b = _pos("MELI", 10, 2950.0, 168.15)    # 0,57%
    r = main.admin_repair_comisiones(apply=True, uid=1)

    assert r["posiciones"] == 0, r["detalle"]
    assert _leer(a)["commissions"] == 10.0
    assert _leer(b)["commissions"] == 168.15


def test_guarda_el_valor_viejo_para_poder_revertir():
    pid = _pos("NFLX", 1234, 2473.0, 3_038_265.12)
    main.admin_repair_comisiones(apply=True, uid=1)

    meta = json.loads(_leer(pid)["undo_meta_json"])
    assert meta["comision_reparada"]["antes"] == 3_038_265.12
    assert meta["comision_reparada"]["pct"] > 99


def test_NO_pisa_el_undo_meta_que_ya_estaba():
    """`undo_meta_json` guarda el CAMINO de creación (`src`) y la cascada de
    borrado lo lee para saber cómo revertir. Sobreescribirlo dejaría esas
    posiciones sin poder borrarse — un bug peor que el que vinimos a arreglar."""
    pid = _pos("NFLX", 1234, 2473.0, 3_038_265.12,
               undo='{"src": "manual_position", "cost": 3051682.0}')
    main.admin_repair_comisiones(apply=True, uid=1)

    meta = json.loads(_leer(pid)["undo_meta_json"])
    assert meta["src"] == "manual_position", "se perdió el camino de creación"
    assert meta["cost"] == 3051682.0
    assert meta["comision_reparada"]["antes"] == 3_038_265.12


def test_un_undo_meta_corrupto_no_rompe_la_reparacion():
    pid = _pos("NFLX", 1234, 2473.0, 3_038_265.12, undo="{esto no es json")
    main.admin_repair_comisiones(apply=True, uid=1)

    assert _leer(pid)["commissions"] == 0
    assert json.loads(_leer(pid)["undo_meta_json"])["comision_reparada"]["antes"] > 0


def test_reporta_cuanta_plata_falsa_saca():
    _pos("A", 100, 1000.0, 90_000.0)
    _pos("B", 100, 1000.0, 50_000.0)
    r = main.admin_repair_comisiones(uid=1)
    assert r["comisiones_falsas_total"] == 140_000.0
    assert r["usuarios"] == 1


def test_avisa_que_faltan_los_snapshots():
    """El error fácil de cometer: dar por cerrado el arreglo con las posiciones
    limpias mientras la curva de evolución sigue con el número viejo, porque el
    snapshot diario guardó `invested + commissions`."""
    _pos("NFLX", 1234, 2473.0, 3_038_265.12)
    r = main.admin_repair_comisiones(apply=True, uid=1)
    assert "snapshot" in r["siguiente_paso"].lower()


# ── El piso absoluto ─────────────────────────────────────────────────────────

def test_un_fee_FIJO_sobre_una_posicion_chica_NO_se_toca():
    """El caso real que motivó el piso: un SMR.E con una compra de USD 12,22 y un
    fee de USD 14,13. Como porcentaje es 115%, pero ES un fee legítimo —Balanz
    cobra un fijo—. Sin el piso, la limpieza ensuciaría un dato sano."""
    pid = _pos("SMR.E", 1, 12.22, 14.13, ccy="USD")
    r = main.admin_repair_comisiones(apply=True, uid=1)

    assert r["posiciones"] == 0, r["detalle"]
    assert _leer(pid)["commissions"] == 14.13, "el fee fijo tenía que quedar intacto"


def test_lo_que_queda_afuera_por_el_piso_se_REPORTA():
    """No hay un número que separe todo: las comisiones falsas de Cocos son de
    ~ARS 13.000, o sea POR DEBAJO del piso que hace falta para proteger el fee de
    Balanz. Esas quedan sin tocar — pero NO en silencio, que es lo único
    inaceptable cuando se trata de plata ajena."""
    _pos("AE38", 49, 528.74, 12_954.25)     # 50% exacto: falsa, pero chica
    r = main.admin_repair_comisiones(uid=1)

    assert r["posiciones"] == 0
    assert r["no_tocadas_por_el_piso"]["cuantas"] == 1
    assert r["no_tocadas_por_el_piso"]["detalle"][0]["asset"] == "AE38"
    assert "a mano" in r["no_tocadas_por_el_piso"]["por_que"]


def test_una_comision_falsa_grande_sigue_cayendo():
    """El piso no puede volver inútil la limpieza: lo que motivó todo esto son
    comisiones de cientos de miles."""
    pid = _pos("NFLX", 1234, 2473.0, 3_038_265.12)
    r = main.admin_repair_comisiones(apply=True, uid=1)

    assert r["posiciones"] == 1
    assert _leer(pid)["commissions"] == 0


def test_el_piso_depende_de_la_moneda_de_la_posicion():
    """USD 30 es plata; ARS 30 no es nada. Un piso único en cualquiera de las dos
    monedas sería demasiado alto o demasiado bajo del otro lado."""
    usd = _pos("AAPL", 10, 100.0, 30.0, ccy="USD")   # 3% → ni llega al piso
    ars = _pos("GGAL", 10, 100.0, 30.0, ccy="ARS")   # 3% → tampoco
    r = main.admin_repair_comisiones(uid=1)
    assert r["posiciones"] == 0 and r["no_tocadas_por_el_piso"]["cuantas"] == 0

    # ahora con 20% en cada moneda: el USD queda bajo el piso (20 < 25), el ARS no
    _pos("MSFT", 10, 100.0, 200.0, ccy="USD")        # 200 > 25 → cae
    _pos("YPFD", 10, 1000.0, 2000.0, ccy="ARS")      # 2000 < 35.000 → no cae
    r2 = main.admin_repair_comisiones(uid=1)
    assets = {d["asset"] for d in r2["detalle"]}
    saltados = {d["asset"] for d in r2["no_tocadas_por_el_piso"]["detalle"]}
    assert "MSFT" in assets, r2["detalle"]
    assert "YPFD" in saltados, saltados
    del usd, ars
