"""Una "comisión" mayor al 5% de la operación no es una comisión.

EL PROBLEMA (medido en prod el 2026-08-13). 469 posiciones de ~78 usuarios tienen
en `commissions` un monto que no es una comisión. El P&L de Cartera calcula
`invested + commissions` (calcARS: `realCostArs`), así que eso infla el costo y
**muestra pérdidas que no existen**. El caso que lo destapó: un NFLX con una
"comisión" del 99,56% de la compra mostraba -48,1% cuando en realidad ganaba
+3,5%.

CAUSA ESTRUCTURAL: `fees` viaja SIN MONEDA. En schema.py, `gross_amount` tiene
`currency`, `tc` y `usd_amount`; `fees` es un float pelado que se guarda tal cual
en `positions.commissions`. Si un parser emite la comisión en PESOS sobre un lote
en DÓLARES, nadie lo nota. En los Balanz·USD el ratio era CONSTANTE por usuario y
el MEP implícito coherente (1567 en dos filas del mismo usuario): la firma exacta
de pesos-sobre-dólares.

Este guard no arregla la causa —eso es darle moneda a `fees`— pero corta la
hemorragia: hoy no hay NINGUNA defensa y una comisión del 4600% entra sin que
nadie chiste.

El umbral (5%) lo fijó el dueño. Las comisiones legítimas medidas en la base van
de 0,55% (IOL) a 3,67%.

Corre con: cd backend && python3 -m pytest tests/test_comision_implausible.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.normalizer import normalize_rows, _FEE_MAX_FRAC  # noqa: E402
from importing.schema import RawRow  # noqa: E402


def _fila(idx=0, tipo="COMPRA", monto="1000", comisiones="5", **extra):
    d = {"fecha": "2026-08-13", "tipo": tipo, "broker": "Balanz", "activo": "MELI",
         "cantidad": "10", "precio": "100", "monto": monto,
         "comisiones": comisiones, "moneda": "USD"}
    d.update(extra)
    return RawRow(row_index=idx, data=d)


def _norm(*filas):
    out, errores = normalize_rows(list(filas))
    return out, errores


def test_una_comision_normal_pasa_intacta():
    """0,5% es una comisión de verdad. Si el guard la tocara, estaríamos
    rompiendo el cost basis de todo el mundo para arreglar a unos pocos."""
    out, _ = _norm(_fila(monto="1000", comisiones="5"))
    assert len(out) == 1
    assert out[0].fees == 5.0


def test_justo_en_el_limite_pasa():
    """5% exacto NO se descarta: el umbral es 'mayor a'."""
    out, _ = _norm(_fila(monto="1000", comisiones="50"))
    assert out[0].fees == 50.0


def test_la_comision_del_nflx_se_descarta():
    """El caso real: 99,56% de la compra."""
    out, _ = _norm(_fila(monto="3051682", comisiones="3038265.12"))
    assert out[0].fees == 0.0, "una comisión del 99% tiene que quedar en cero"


def test_el_caso_de_los_4600_por_ciento_tambien():
    """Cocos AO28: comisión de 6.893.749 sobre una compra de 149.864."""
    out, _ = _norm(_fila(monto="149864.1", comisiones="6893749"))
    assert out[0].fees == 0.0


def test_avisa_en_la_fila_por_que_la_descarto():
    """Sin el aviso, el usuario ve un costo distinto al del broker y no sabe por
    qué. La nota viaja con la operación y queda persistida."""
    out, _ = _norm(_fila(monto="1000", comisiones="900"))
    assert out[0].fees == 0.0
    assert out[0].notes and "90%" in out[0].notes, out[0].notes
    assert "implausible" in out[0].notes.lower()


def test_la_nota_no_pisa_las_notas_que_ya_traia_la_fila():
    out, _ = _norm(_fila(monto="1000", comisiones="900", notas="Orden 12345"))
    assert "Orden 12345" in out[0].notes
    assert "Comisión" in out[0].notes


def test_la_fila_NO_se_descarta():
    """Descartar la operación entera sería peor que el problema: el costo sin
    comisión es mucho más correcto que no tener la operación."""
    out, errores = _norm(_fila(monto="1000", comisiones="900"))
    assert len(out) == 1, "la operación tiene que seguir entrando"
    assert out[0].quantity == 10.0 and out[0].gross_amount == 1000.0


def test_una_fila_que_ES_un_cargo_no_se_toca():
    """En una operación de tipo COMISION el monto ES la comisión: compararla
    contra sí misma y ponerla en cero borraría el cargo real."""
    out, _ = _norm(_fila(tipo="COMISION", monto="500", comisiones="500",
                         activo="", cantidad="", precio=""))
    assert len(out) == 1
    assert out[0].fees == 500.0, "un cargo real no se descarta"


def test_sin_monto_cae_a_cantidad_por_precio():
    """Varios parsers no traen 'monto'. Sin este fallback el guard no mediría
    nada y las filas de esos brokers quedarían sin protección."""
    out, _ = _norm(_fila(monto="", comisiones="900", cantidad="10", precio="100"))
    assert out[0].fees == 0.0


def test_el_umbral_es_el_que_fijo_el_dueno():
    assert _FEE_MAX_FRAC == 0.05
