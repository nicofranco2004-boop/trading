"""`PositionIn` no acotaba sus montos, y es la puerta de carga manual.

EL BUG (auditoría 1B, casos borde). `SellIn`, `OperationIn` y `MonthlyIn` aplican
`_FINITE_BOUND = 1e12` a todos sus montos; `PositionIn` no lo hacía. Medido en la
auditoría: una posición con `invested = 1e308` entraba, se propagaba a
`monthly_entries.capital_final` y salía por `compute_broker_value_usd`.

Había una razón mecánica: `_FINITE_BOUND` se definía ~8.000 líneas MÁS ABAJO que
`PositionIn`, así que el modelo no podía referenciarlo. La constante subió al
bloque de cotas (junto a `MAX_STR`), que es lo que permite que la usen todos.

Ojo: `le=` en el Field NO ataja NaN — ninguna comparación con NaN da True. Por eso
va además el validador `_finite`, el mismo de los modelos hermanos.

Corre con: cd backend && python3 -m pytest tests/test_position_in_cota.py
"""
import unittest

import main
from pydantic import ValidationError


class PositionInCotaTest(unittest.TestCase):

    def _pos(self, **kw):
        return main.PositionIn(broker="B", asset="X", **kw)

    def test_invested_absurdo_se_rechaza(self):
        """REGRESIÓN: 1e308 entraba y llegaba a capital_final."""
        with self.assertRaises(ValidationError):
            self._pos(invested=1e308)

    def test_nan_se_rechaza(self):
        """`le=` no alcanza: NaN no es mayor ni menor que nada."""
        for campo in ("buy_price", "quantity", "invested", "commissions"):
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                self._pos(**{campo: float("nan")})

    def test_infinito_se_rechaza(self):
        for campo in ("buy_price", "quantity", "invested", "price_override"):
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                self._pos(**{campo: float("inf")})

    def test_tc_compra_absurdo_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self._pos(tc_compra=1e308)

    def test_una_posicion_normal_sigue_entrando(self):
        p = self._pos(invested=10_000, quantity=5, buy_price=2000, commissions=12.5)
        self.assertEqual(p.invested, 10_000)
        self.assertEqual(p.quantity, 5)

    def test_el_limite_exacto_sigue_siendo_valido(self):
        self.assertEqual(self._pos(invested=1e12).invested, 1e12)

    def test_coincide_con_sus_modelos_hermanos(self):
        """La cota tiene que ser LA MISMA que la de SellIn/OperationIn/MonthlyIn:
        si cada modelo elige la suya, vuelve a haber drift."""
        with self.assertRaises(ValidationError):
            main.SellIn(broker="B", asset="X", quantity=1e13, exit_price=1)
        with self.assertRaises(ValidationError):
            self._pos(quantity=1e13)


if __name__ == "__main__":
    unittest.main()
