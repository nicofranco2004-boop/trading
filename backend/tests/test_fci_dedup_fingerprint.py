"""Dedup de FCI: el fingerprint no puede depender del catálogo curado.

Bug real (usuario de Cocos, 2026-07): "tengo 3 FCI y me aparece uno cuadruplicado,
otro triplicado y otro duplicado". Una de las dos causas era ésta — el fingerprint
de dedup incluía el símbolo YA canonicalizado (`FCI:<slug>`), y ese símbolo cambia
cuando agregamos un fondo al mapa curado (`fci_map`). Consecuencia: la MISMA
operación importada antes y después del cambio tenía fingerprints distintos → el
dedup cross-batch no la reconocía → se re-importaba como lote nuevo. Afectaba SOLO
a los FCI (los CEDEAR conservan su ticker crudo).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from importing.pipeline import _row_fingerprint, _row_fingerprint_legacy  # noqa: E402
from importing.schema import NormalizedTx  # noqa: E402


def _tx(symbol, raw=None, **kw):
    base = dict(
        row_index=1, date="2026-03-15", broker="Balanz", operation_type="BUY",
        asset_symbol=symbol, asset_symbol_raw=raw, quantity=1000.0,
        unit_price=1.5, gross_amount=1500.0,
    )
    base.update(kw)
    return NormalizedTx(**base)


def test_fingerprint_estable_ante_canonicalizacion_del_catalogo():
    """La misma operación, antes y después de que el fondo entre al mapa curado."""
    antes = _tx("COCORMA", raw="COCORMA")          # no estaba en el mapa
    despues = _tx("FCI:cocos-rendimiento-a", raw="COCORMA")  # ya mapeado
    assert _row_fingerprint(antes) == _row_fingerprint(despues), (
        "agregar el fondo al catálogo NO puede cambiar el fingerprint"
    )


def test_legacy_reconoce_los_fingerprints_ya_guardados():
    """Los imports viejos guardaron el fingerprint con el símbolo canónico:
    el dedup tiene que seguir reconociéndolos (si no, estabilizar el hash
    duplicaría una vez más a todo el que ya importó FCI)."""
    tx = _tx("FCI:cocos-rendimiento-a", raw="COCORMA")
    guardado_viejo = _row_fingerprint_legacy(tx)
    # El legacy usa el símbolo canónico → matchea lo que hay en la DB.
    assert guardado_viejo == _row_fingerprint(_tx("FCI:cocos-rendimiento-a", raw=None))
    # …y es DISTINTO del nuevo (por eso hay que chequear ambos en el dedup).
    assert guardado_viejo != _row_fingerprint(tx)


def test_no_afecta_a_los_no_fci():
    """Sin canonicalización (todo lo que no es FCI), ambos hashes coinciden →
    cero cambio de comportamiento para acciones/CEDEARs/bonos."""
    tx = _tx("AAPL", raw="AAPL")
    assert _row_fingerprint(tx) == _row_fingerprint_legacy(tx)
    sin_raw = _tx("AAPL", raw=None)
    assert _row_fingerprint(sin_raw) == _row_fingerprint_legacy(sin_raw)


def test_sigue_distinguiendo_operaciones_distintas():
    """El fingerprint no puede volverse tan laxo que colapse ops legítimas."""
    a = _tx("COCORMA", raw="COCORMA")
    distinta_fecha = _tx("COCORMA", raw="COCORMA", date="2026-04-15")
    distinto_monto = _tx("COCORMA", raw="COCORMA", gross_amount=3000.0)
    distinto_fondo = _tx("COCOA", raw="COCOA")
    distinto_broker = _tx("COCORMA", raw="COCORMA", broker="Cocos")
    fps = {_row_fingerprint(x) for x in
           (a, distinta_fecha, distinto_monto, distinto_fondo, distinto_broker)}
    assert len(fps) == 5, "cada operación distinta debe tener su propio fingerprint"


def test_combine_dedup_entre_archivos_solapados():
    """Dos exports con rango solapado (caso real "movimientos (2)/(3).csv"):
    las filas repetidas ENTRE archivos se descartan; las repetidas DENTRO de un
    mismo archivo se respetan (pueden ser dos ops legítimas iguales)."""
    from importing.pipeline import combine_csv_files
    a = b"nroTicket;fecha;monto\n1;01-01-2026;100\n2;02-01-2026;200\n"
    b = b"nroTicket;fecha;monto\n2;02-01-2026;200\n3;03-01-2026;300\n"
    out, _name, err = combine_csv_files([(a, "a.csv"), (b, "b.csv")])
    assert err is None
    filas = out.decode().splitlines()[1:]
    assert filas == ["1;01-01-2026;100", "2;02-01-2026;200", "3;03-01-2026;300"]

    # Intra-archivo: NO se toca.
    c = b"nroTicket;fecha;monto\n9;05-01-2026;500\n9;05-01-2026;500\n"
    d = b"nroTicket;fecha;monto\n7;06-01-2026;700\n"
    out2, _n2, err2 = combine_csv_files([(c, "c.csv"), (d, "d.csv")])
    assert err2 is None
    assert len(out2.decode().splitlines()[1:]) == 3
