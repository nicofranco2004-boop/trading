"""Posiciones donde el precio de compra y el costo se contradicen.

EL CASO REAL. Un NFLX en la cartera del papá del dueño:

    cantidad 1234 · compra ARS 2.473 · actual ARS 2.560 · valor ARS 3.159.040
    P&L: -ARS 2.930.907 (-48,1%)

La fila se contradice sola: dice que compró a 2.473 y que hoy vale 2.560 —o sea
que está ganando— y al lado muestra 48% de pérdida. La aritmética explica por qué:

    valor 3.159.040 = 1234 × 2.560                          ✓ correcto
    costo según la columna = 1234 × 2.473 = 3.051.682
    costo que USA el P&L  = 3.159.040 + 2.930.907 = 6.089.947   ← casi el doble

Es que la grilla muestra `buy_price` y el P&L calcula con `invested`
(Positions.jsx: la columna hace `p.buy_price ?? invested/quantity`, y calcARS
hace `valor − invested`). Mientras coincidan da igual cuál se use; cuando no,
la fila miente.

La misma cartera tiene un GGAL que cierra perfecto (ratio 1,0000), así que no es
un problema general de la valuación: son posiciones puntuales con el dato torcido.

Corre con: cd backend && python3 -m pytest tests/test_costo_inconsistente.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
import pytest  # noqa: E402


UID = 4242


@pytest.fixture(autouse=True)
def _limpio():
    conn = main.get_db()
    with conn:
        conn.execute("DELETE FROM positions WHERE user_id=?", (UID,))
        conn.execute("DELETE FROM users WHERE id=?", (UID,))
        conn.execute("INSERT INTO users (id,email,password_hash,approved) VALUES (?,?,?,1)",
                     (UID, "papa@rendi.test", "h"))
    conn.close()
    yield


def _pos(asset, qty, buy, invested, is_cash=0):
    conn = main.get_db()
    with conn:
        conn.execute(
            """INSERT INTO positions (user_id,broker,asset,is_cash,quantity,buy_price,invested)
               VALUES (?,?,?,?,?,?,?)""",
            (UID, "Cocos", asset, is_cash, qty, buy, invested))
    conn.close()


def test_encuentra_el_caso_del_nflx():
    """Los números son los de la pantalla, no inventados."""
    _pos("NFLX", 1234, 2473.0, 6_089_947.0)
    r = main.admin_diagnose_costo_inconsistente(uid=1)

    assert len(r["posiciones"]) == 1, r["veredicto"]
    p = r["posiciones"][0]
    assert p["asset"] == "NFLX"
    assert p["costo_segun_buy_price"] == 3_051_682.0
    assert p["invested"] == 6_089_947.0
    assert 1.99 <= p["ratio"] <= 2.0, p["ratio"]
    # El ratio ES el diagnóstico: ~2 apunta a duplicación, no a un problema de FX.
    assert r["por_forma_del_ratio"].get("~2x") == 1, r["por_forma_del_ratio"]


def test_el_ggal_sano_de_la_misma_cartera_no_aparece():
    """Control. Si el diagnóstico marcara también las posiciones buenas, no
    serviría para nada: hay 32.684 posiciones en producción."""
    _pos("GGAL", 807, 7430.0, 5_996_010.0)      # 807 × 7430, exacto
    r = main.admin_diagnose_costo_inconsistente(uid=1)
    assert r["posiciones"] == [], r["posiciones"]
    assert "Ninguna" in r["veredicto"]


def test_las_comisiones_y_el_redondeo_no_cuentan_como_error():
    """Un costo 1,5% arriba del precio×cantidad es una comisión, no un bug.
    Sin este colchón el informe vendría lleno de ruido y taparía lo real."""
    _pos("AAPL", 100, 1000.0, 101_500.0)        # +1,5%
    assert main.admin_diagnose_costo_inconsistente(uid=1)["posiciones"] == []
    # pero con tolerancia 0 sí se ve
    assert main.admin_diagnose_costo_inconsistente(tol=0.0, uid=1)["posiciones"]


def test_una_posicion_importada_sin_precio_de_compra_NO_es_inconsistencia():
    """Muchas posiciones de import tienen buy_price NULL. Ahí la grilla ya cae a
    `invested/quantity` y la fila cierra sola: marcarlas sería un falso positivo
    masivo."""
    _pos("MELI", 10, None, 50_000.0)
    assert main.admin_diagnose_costo_inconsistente(uid=1)["posiciones"] == []


def test_el_cash_no_se_mira():
    """El efectivo no tiene precio de compra; `invested` ES el saldo."""
    _pos("ARS", 0, 1.0, 500_000.0, is_cash=1)
    assert main.admin_diagnose_costo_inconsistente(uid=1)["posiciones"] == []


def test_clasifica_las_otras_formas_conocidas():
    """El ratio separa causas distintas, que piden fixes distintos."""
    _pos("AL30", 100, 100.0, 1_000_000.0)     # ×100 → bono per-100 vs per-1
    _pos("SPY", 10, 100.0, 1_500_000.0)       # ×1500 → pesos contados como dólares
    r = main.admin_diagnose_costo_inconsistente(uid=1)
    formas = r["por_forma_del_ratio"]
    assert formas.get("~100x") == 1, formas
    assert formas.get("~FX (1000-1600x)") == 1, formas
