"""Cerrar la canilla del bug per-100: reconciliar el triángulo cantidad×precio=monto.

El motor lee el COSTO de `gross_amount` (persister.py:411) y los INGRESOS de
`unit_price × quantity` (persister.py:536→609), y nunca los compara. Con el costo
sano, todo error de escala en el precio cae íntegro sobre el P&L: un bono cotizado
por 100 nominales produce `pnl = 99 × costo`.

El normalizer ya resolvía el triángulo cuando FALTABA un valor; no hacía nada cuando
los tres venían y se contradecían. Estos tests fijan ese comportamiento: ante un
desvío de un orden de magnitud gana `monto` (la plata que se movió), que es lo que ya
hacen IOL y Cocos derivando `precio = monto/cantidad`.

El umbral de 5× tiene que dejar pasar intactas las comisiones embebidas (1-3%) — eso
es lo que verifican los tests de no-regresión.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.normalizer import normalize_rows
from importing.schema import RawRow


def _norm(**kw):
    data = {"fecha": "2026-07-01", "tipo": "COMPRA", "activo": "GD30", "broker": "Balanz",
            "cantidad": "", "precio": "", "monto": "", "moneda": "USD"}
    data.update(kw)
    txs, errs = normalize_rows([RawRow(row_index=1, data=data)])
    assert txs, f"normalize_rows no devolvió nada: {errs}"
    return txs[0]


class TriangleReconcileTest(unittest.TestCase):
    # ── Lo que se corrige ────────────────────────────────────────────────
    def test_bono_per_100_el_precio_pasa_a_per_1(self):
        """GD30 del fixture real de Balanz: 1000 nominales, precio 66,04, monto 660,4."""
        tx = _norm(cantidad="1000", precio="66.04", monto="660.4")
        self.assertAlmostEqual(tx.unit_price, 0.6604, places=6)
        self.assertAlmostEqual(tx.gross_amount, 660.4, places=4)
        self.assertAlmostEqual(tx.quantity, 1000, places=4)
        # El triángulo cierra ⇒ el motor ya no puede inflar el P&L ×100.
        self.assertAlmostEqual(tx.quantity * tx.unit_price, tx.gross_amount, places=4)

    def test_fci_vcp_por_1000(self):
        tx = _norm(activo="RFPESOS", cantidad="1000", precio="2290", monto="2290", moneda="ARS")
        self.assertAlmostEqual(tx.unit_price, 2.29, places=6)
        self.assertAlmostEqual(tx.quantity * tx.unit_price, tx.gross_amount, places=4)

    def test_venta_tambien_se_corrige(self):
        tx = _norm(tipo="VENTA", cantidad="1000", precio="70", monto="700")
        self.assertAlmostEqual(tx.unit_price, 0.70, places=6)
        self.assertAlmostEqual(tx.quantity * tx.unit_price, tx.gross_amount, places=4)

    def test_precio_demasiado_chico_tambien(self):
        """El desvío inverso (ratio ≤ 0,2) también se reconcilia."""
        tx = _norm(cantidad="10", precio="0.5", monto="500")
        self.assertAlmostEqual(tx.unit_price, 50.0, places=6)

    # ── Lo que NO se toca (el umbral tiene que dejarlo pasar) ────────────
    def test_comision_embebida_del_3pct_no_se_toca(self):
        """balanz_movimientos.py:428 admite hasta 3% de gap como comisión embebida."""
        tx = _norm(cantidad="100", precio="10.30", monto="1000")   # ratio 1,03
        self.assertAlmostEqual(tx.unit_price, 10.30, places=6)     # intacto
        self.assertAlmostEqual(tx.gross_amount, 1000, places=4)

    def test_ruido_de_redondeo_fx_no_se_toca(self):
        tx = _norm(cantidad="7", precio="142.857", monto="1000")   # ratio 0,99999…
        self.assertAlmostEqual(tx.unit_price, 142.857, places=6)

    def test_triangulo_exacto_no_se_toca(self):
        tx = _norm(cantidad="10", precio="150", monto="1500")
        self.assertAlmostEqual(tx.unit_price, 150.0, places=6)

    def test_gap_de_4x_no_llega_al_umbral(self):
        """Frontera: 4× queda fuera. El umbral es 5×, no 'cualquier diferencia'."""
        tx = _norm(cantidad="10", precio="40", monto="100")        # ratio 4,0
        self.assertAlmostEqual(tx.unit_price, 40.0, places=6)

    # ── El comportamiento viejo sigue igual ──────────────────────────────
    def test_sigue_rellenando_huecos(self):
        self.assertAlmostEqual(_norm(cantidad="10", precio="150").gross_amount, 1500, places=4)
        self.assertAlmostEqual(_norm(cantidad="10", monto="1500").unit_price, 150, places=6)
        self.assertAlmostEqual(_norm(precio="150", monto="1500").quantity, 10, places=6)

    def test_monto_ausente_no_dispara_la_reconciliacion(self):
        tx = _norm(cantidad="1000", precio="66.04")
        self.assertAlmostEqual(tx.unit_price, 66.04, places=6)     # no hay con qué comparar
        self.assertAlmostEqual(tx.gross_amount, 66040, places=2)


if __name__ == "__main__":
    unittest.main()
