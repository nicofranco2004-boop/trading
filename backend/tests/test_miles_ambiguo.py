"""El separador de miles es-AR: "150.000" son ciento cincuenta mil, no 150,0.

`parse_number` ve un valor por vez y, con un solo punto, asume decimal. Un
usuario que escribe "150.000" en el CSV termina con un costo MIL VECES más chico,
sin un solo error y con la fila figurando como válida en el preview.

No se arregla adivinando: `reconciled_unit_price` (persister) ya documenta que un
"660.400" mal parseado tiene la misma firma que un FCI legítimo, y convertir el
"0.715" de un bono en 715 es igual de caro para el otro lado.

Lo que sí se puede es PROBARLO con el triángulo precio × cantidad = monto. Estos
tests fijan las tres conductas: corregir cuando está probado, no tocar cuando ya
cierra, y AVISAR cuando no se puede decidir — nunca elegir en silencio.

Corre con: cd backend && python3 -m pytest tests/test_miles_ambiguo.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.normalizer import (                                   # noqa: E402
    _es_ambiguo_miles, _desambiguar_por_triangulo, normalize_rows, parse_number,
)
from importing.schema import RawRow                                  # noqa: E402


# ── qué forma es ambigua ─────────────────────────────────────────────────────

def test_la_forma_ambigua_es_punto_con_tres_digitos():
    for s in ("150.000", "1.500", "12.345", "999.999"):
        assert _es_ambiguo_miles(s), s


def test_el_precio_de_bono_con_cero_adelante_NO_es_ambiguo():
    """"0.715" es el precio por 1 VN que la propia UI le sugiere al usuario. Una
    agrupación de miles nunca arranca en cero: es decimal con certeza."""
    for s in ("0.715", "0.001", "0.500"):
        assert not _es_ambiguo_miles(s), s
        assert parse_number(s) == float(s)


def test_lo_que_no_puede_ser_miles_no_es_ambiguo():
    for s in ("1.5", "1234.56", "1.234.567", "1234", "", None, "12.34", "1.23456"):
        assert not _es_ambiguo_miles(s), s


# ── el triángulo decide ──────────────────────────────────────────────────────

def test_corrige_el_precio_cuando_el_triangulo_lo_prueba():
    q, p, m, fix = _desambiguar_por_triangulo(10.0, 150.0, 1_500_000.0, ("precio",))
    assert fix == "precio" and p == 150_000.0 and q == 10.0


def test_corrige_la_cantidad_cuando_el_triangulo_lo_prueba():
    q, p, m, fix = _desambiguar_por_triangulo(1.5, 100.0, 150_000.0, ("cantidad",))
    assert fix == "cantidad" and q == 1500.0


def test_solo_toca_el_campo_ambiguo():
    """Con precio "150.000" y cantidad 10, multiplicar la CANTIDAD por mil también
    cierra la cuenta. Si se probaran los tres campos, quedaban 10.000 unidades en
    vez del precio arreglado — un bug peor que el original."""
    q, p, m, fix = _desambiguar_por_triangulo(10.0, 150.0, 1_500_000.0, ("precio",))
    assert fix == "precio", "no puede haber elegido cantidad"
    assert q == 10.0


def test_una_fila_sana_no_se_toca():
    """660,4 × 1000 = 660.400 ya cierra. Tocarla rompería un dato correcto."""
    q, p, m, fix = _desambiguar_por_triangulo(1000.0, 660.4, 660_400.0, ("precio",))
    assert fix == "ya_cerraba" and p == 660.4


def test_ya_cerraba_NO_es_lo_mismo_que_no_se_puede_decidir():
    """El precio por VN de un GD30: 7 × 142,857 = 1000. La forma es ambigua pero
    la ARITMÉTICA ya lo decidió — es decimal, probado. Colapsar este caso con "no
    sé" hacía avisar sobre filas perfectamente sanas."""
    q, p, m, fix = _desambiguar_por_triangulo(7.0, 142.857, 1000.0, ("precio",))
    assert fix == "ya_cerraba" and p == 142.857
    txs, errs = normalize_rows([_fila(activo="GD30", moneda="USD", cantidad="7",
                                      precio="142.857", monto="1000")])
    assert not errs, f"no tenía que avisar: {errs}"
    assert txs[0].unit_price == 142.857


def test_la_comision_embebida_no_rompe_el_triangulo():
    """1% de tolerancia: el monto del broker trae comisiones adentro."""
    q, p, m, fix = _desambiguar_por_triangulo(100.0, 10.0, 1005.0, ("precio",))
    assert fix == "ya_cerraba", "1.005 vs 1.000 es medio punto: cierra"


def test_sin_el_tercer_lado_no_decide():
    for args in ((10.0, 150.0, None), (None, 150.0, 1500.0), (10.0, None, 1500.0)):
        assert _desambiguar_por_triangulo(*args, ("precio",))[3] is None


# ── de punta a punta ─────────────────────────────────────────────────────────

def _fila(**kw):
    base = {"fecha": "2026-01-15", "tipo": "COMPRA", "broker": "Cocos",
            "activo": "GGAL", "moneda": "ARS"}
    return RawRow(row_index=1, data={**base, **kw})


def test_e2e_el_precio_con_punto_de_miles_entra_bien():
    txs, errs = normalize_rows([_fila(cantidad="10", precio="150.000",
                                      monto="1500000")])
    assert not errs, errs
    assert txs[0].unit_price == 150_000.0


def test_e2e_lo_indecidible_avisa_en_vez_de_elegir():
    """LA garantía. Antes esto entraba como 150,0 sin decir nada y el usuario se
    enteraba meses después mirando una cartera mil veces más chica."""
    txs, errs = normalize_rows([_fila(cantidad="10", precio="150.000")])
    assert errs, "tenía que avisar"
    assert errs[0].code == "NUMERO_AMBIGUO_MILES"
    assert "150000" in errs[0].message and "150.000" in errs[0].message


def test_e2e_el_bono_a_0_715_sigue_entrando_sin_ruido():
    txs, errs = normalize_rows([_fila(activo="AL30", cantidad="1000",
                                      precio="0.715", monto="715")])
    assert not errs, errs
    assert txs[0].unit_price == 0.715
