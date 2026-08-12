"""Una conversión de moneda no puede figurar ×1400 en Movimientos.

Comprar USD 1.000 con $1.400.000 aparecía como **USD 1.400.000**. La causa:
una conversión tiene DOS monedas, así que la fila no trae `moneda`, y el
estampado a dólares solo divide cuando el campo dice literalmente "ARS" — con
`currency` en None devolvía el monto en pesos tal cual, rotulado como dólares.

Se ve desde que Balanz empezó a traer estas conversiones (`e47db69`), que fue
lo que las hizo visibles: antes ni se importaban.

La regla que fijan estos tests: para una conversión, los dólares NO se
calculan con ninguna cotización — la fila ya trae las dos patas, y esa es la
más exacta que hay (es el dólar que el usuario pagó, no uno de referencia).

Corre con: cd backend && python3 -m pytest tests/test_fx_gross_usd.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from importing.pipeline import stamp_tx_gross_usd
from importing.schema import NormalizedTx
import main


def _tx(op, **kw):
    base = dict(row_index=0, date="2026-06-01", broker="Balanz", operation_type=op)
    base.update(kw)
    return NormalizedTx(**base)


class EstampadoDeConversiones(unittest.TestCase):
    TC = 1400.0

    def test_una_conversion_vale_sus_dolares_no_sus_pesos(self):
        fx = _tx("FX_ARS_TO_USD", gross_amount=1_400_000.0, quantity=1000.0,
                 unit_price=1400.0, currency=None)
        self.assertAlmostEqual(stamp_tx_gross_usd(fx, self.TC), 1000.0, places=6)

    def test_la_vuelta_tambien(self):
        fx = _tx("FX_USD_TO_ARS", gross_amount=1_400_000.0, quantity=1000.0,
                 unit_price=1400.0, currency=None)
        self.assertAlmostEqual(stamp_tx_gross_usd(fx, self.TC), 1000.0, places=6)

    def test_usa_el_dolar_DE_LA_OPERACION_no_el_de_referencia(self):
        # Convirtió a 1.600 (MEP) mientras el blue de referencia estaba en 1.400:
        # el resultado tiene que ser 1.000, los dólares que realmente recibió.
        fx = _tx("FX_ARS_TO_USD", gross_amount=1_600_000.0, quantity=1000.0,
                 unit_price=1600.0, currency=None)
        self.assertAlmostEqual(stamp_tx_gross_usd(fx, self.TC), 1000.0, places=6)

    def test_sin_la_pata_en_dolares_convierte_en_vez_de_mentir(self):
        # Caso defensivo: no hay quantity. Los pesos siguen en gross_amount, así
        # que se dolariza — nunca se devuelve el número en pesos tal cual.
        fx = _tx("FX_ARS_TO_USD", gross_amount=1_400_000.0, quantity=None,
                 currency=None)
        self.assertAlmostEqual(stamp_tx_gross_usd(fx, self.TC), 1000.0, places=6)

    # ── lo que NO cambia ────────────────────────────────────────────────────

    def test_un_deposito_en_pesos_sigue_dolarizandose(self):
        d = _tx("DEPOSIT", gross_amount=1_400_000.0, currency="ARS")
        self.assertAlmostEqual(stamp_tx_gross_usd(d, self.TC), 1000.0, places=6)

    def test_un_deposito_en_dolares_sigue_intacto(self):
        d = _tx("DEPOSIT", gross_amount=500.0, currency="USD")
        self.assertAlmostEqual(stamp_tx_gross_usd(d, self.TC), 500.0, places=6)

    def test_una_compra_en_pesos_sigue_dolarizandose(self):
        b = _tx("BUY", asset_symbol="GGAL", quantity=10.0, unit_price=140_000.0,
                gross_amount=1_400_000.0, currency="ARS")
        self.assertAlmostEqual(stamp_tx_gross_usd(b, self.TC), 1000.0, places=6)


class ReparacionDeLoYaImportado(unittest.TestCase):
    """Las conversiones ya importadas se arreglan sin re-importar: la fila
    guarda `quantity`, que SON los dólares."""

    def setUp(self):
        self.conn = main.get_db()
        # Sin esto, una transacción abierta de un test anterior hace que el
        # siguiente espere el busy_timeout entero antes de fallar.
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("import_normalized_tx", "import_raw_rows", "import_batches", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,'x',1)",
            ("fxrepair@rendi.test",))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, broker, parser_format, file_name, "
            "                            file_hash, status) "
            "VALUES ('b1', ?, 'Balanz', 'balanz_movimientos', 'mov.csv', 'h1', 'confirmed')",
            (self.uid,))
        self.conn.execute(
            "INSERT INTO import_raw_rows (id, batch_id, row_index, raw_json, status) "
            "VALUES (1, 'b1', 0, '{}', 'valid')")
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def _fila(self, op, gross, qty, gross_usd):
        self.conn.execute(
            """INSERT INTO import_normalized_tx
                   (batch_id, raw_row_id, date, broker, operation_type,
                    quantity, gross_amount, gross_amount_usd)
               VALUES ('b1', 1, '2026-06-01', 'Balanz', ?, ?, ?, ?)""",
            (op, qty, gross, gross_usd))
        self.conn.commit()

    def _usd(self, op):
        return self.conn.execute(
            "SELECT gross_amount_usd u FROM import_normalized_tx WHERE operation_type=?",
            (op,)).fetchone()["u"]

    def test_repara_la_conversion_rota(self):
        self._fila("FX_ARS_TO_USD", 1_400_000.0, 1000.0, 1_400_000.0)   # rota
        self.assertEqual(main._repair_fx_gross_usd(self.conn), 1)
        self.assertAlmostEqual(self._usd("FX_ARS_TO_USD"), 1000.0, places=6)

    def test_no_toca_los_depositos(self):
        self._fila("DEPOSIT", 1_400_000.0, None, 1000.0)
        self.assertEqual(main._repair_fx_gross_usd(self.conn), 0)
        self.assertAlmostEqual(self._usd("DEPOSIT"), 1000.0, places=6)

    def test_es_idempotente(self):
        self._fila("FX_ARS_TO_USD", 1_400_000.0, 1000.0, 1_400_000.0)
        main._repair_fx_gross_usd(self.conn)
        self.assertEqual(main._repair_fx_gross_usd(self.conn), 0,
                         "el segundo pase volvió a tocar filas ya sanas")


if __name__ == "__main__":
    unittest.main()
