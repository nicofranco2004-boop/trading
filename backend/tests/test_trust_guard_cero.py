"""El guard anti-distorsión no puede confiar en un precio de cero.

CONTEXTO. `_trust_mkt_value` existe para rechazar precios absurdos (colisión de
ticker, bono cotizado ×100, CEDEAR priceado como la acción US): si el valor de
mercado se va lejos del costo, no se confía y se cae a costo.

EL BUG (auditoría 1B, casos borde). La guarda de entrada era
`if not (real_cost > 0) or not (mkt_value > 0): return True`, o sea que metía dos
cosas distintas en la misma condición:

  · costo ≤ 0  → "no hay con qué comparar", y devolver True está bien.
  · valor NEGATIVO o no finito → NO es eso. No existe caso legítimo, y sin
    embargo se publicaba: la posición valía MENOS QUE NADA, o NaN.

DÓNDE **NO** VA EL FIX. La primera versión de este arreglo rechazaba también el
CERO, y estaba mal — lo probó un test que ya existía
(`valuation.test.js`, "null quantity → value = 0"). Lo que entra a esta función es
un VALOR (precio × CANTIDAD), no un precio: una posición con cantidad 0 vale 0 de
verdad, y hacerla caer a costo publica un valor fantasma de algo que no se tiene.
Un `price_override = 0` es lo mismo: el usuario marcando el activo sin valor.

El caso que sí hay que atajar —precio 0 con cantidad > 0— no se puede distinguir
desde acá porque llega multiplicado. Se rechaza en la FUENTE: `pricing/fci.py`
aceptaba `vcp = 0` porque sólo chequeaba el tipo, y `0` es un `int`.

Corre con: cd backend && python3 -m pytest tests/test_trust_guard_cero.py
"""
import unittest

from snapshots_job import _trust_mkt_value
from behavioral import _trust_mkt_value_usd

COSTO = 1000.0


class TrustGuardCeroTest(unittest.TestCase):

    # ── lo que el bug dejaba pasar ───────────────────────────────────────────
    def test_precio_negativo_no_se_confia(self):
        """Valía MENOS que nada."""
        self.assertFalse(_trust_mkt_value(-50.0, COSTO, None))

    def test_nan_no_se_confia(self):
        self.assertFalse(_trust_mkt_value(float('nan'), COSTO, None))

    def test_infinito_no_se_confia(self):
        self.assertFalse(_trust_mkt_value(float('inf'), COSTO, None))

    def test_none_no_se_confia(self):
        self.assertFalse(_trust_mkt_value(None, COSTO, None))

    # ── el cero SÍ es legítimo, y por eso no se toca ─────────────────────────
    def test_valor_cero_se_acepta(self):
        """Cantidad 0 → valor 0. Rechazarlo haría que la posición valga su COSTO:
        un valor fantasma de algo que el usuario no tiene."""
        self.assertTrue(_trust_mkt_value(0.0, COSTO, None))
        self.assertTrue(_trust_mkt_value(0.0, COSTO, None, has_override=True))
        self.assertTrue(_trust_mkt_value(0.0, COSTO, 'BOND'))

    def test_un_precio_casi_cero_sigue_rechazandose(self):
        """Con cantidad > 0, un valor ínfimo cae fuera de la banda: eso ya andaba
        y tiene que seguir andando."""
        self.assertFalse(_trust_mkt_value(0.0001, COSTO, None))

    # ── lo que ya andaba tiene que seguir andando ────────────────────────────
    def test_sin_costo_sigue_devolviendo_true(self):
        self.assertTrue(_trust_mkt_value(500.0, 0.0, None))
        self.assertTrue(_trust_mkt_value(500.0, None, None))

    def test_precio_normal_se_confia(self):
        self.assertTrue(_trust_mkt_value(1200.0, COSTO, None))

    def test_las_bandas_no_cambiaron(self):
        self.assertTrue(_trust_mkt_value(COSTO * 50, COSTO, None))
        self.assertFalse(_trust_mkt_value(COSTO * 51, COSTO, None))
        self.assertTrue(_trust_mkt_value(COSTO * 4, COSTO, 'BOND'))
        self.assertFalse(_trust_mkt_value(COSTO * 5, COSTO, 'BOND'))

    # ── la tercera copia ─────────────────────────────────────────────────────
    def test_behavioral_delega_en_el_canonico(self):
        """`behavioral._trust_mkt_value_usd` era una tercera copia con el mismo
        defecto. Mientras sean copias, arreglar una no arregla las otras."""
        for mkt in (0.0, -50.0, 0.0001):
            with self.subTest(mkt=mkt):
                self.assertEqual(_trust_mkt_value_usd(mkt, COSTO, None),
                                 _trust_mkt_value(mkt, COSTO, None))
        self.assertTrue(_trust_mkt_value_usd(1200.0, COSTO, None))


if __name__ == "__main__":
    unittest.main()
