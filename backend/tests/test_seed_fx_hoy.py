"""El depósito del "Estado inicial" se dolariza al TC de HOY, nunca al de su fecha.

El wizard, cuando el archivo importado deja el cash en negativo (un export de
ÓRDENES no trae ningún depósito, así que todas las compras sobregiran), le
pregunta al usuario "¿cuánto efectivo tenés HOY?" y emite un depósito sintético
por la diferencia. El MONTO está en pesos de hoy. Pero la FECHA es `earliest − 1
día` (seed.py `_minus_one_day`): la más vieja de toda la cuenta.

Dolarizar ese monto con el dólar de esa fecha lo multiplica por 33. Medido en
prod sobre la cuenta #324: una fila de 130.667.268 pesos fechada 2019-07-21 —un
DOMINGO, que es la firma de "earliest − 1 día" y no de ningún dato de broker—
daba US$ 3.090.522 migrados, el 92% del aportado de esa cuenta.

`fx_migrate.py` ya dejó de re-estampar estas filas. Este test cubre el OTRO
camino, el del import: sin él, cada cuenta que pasa a v2 vuelve a generar el bug
en su próximo import — y son ~470 cuentas después de la migración masiva.
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importing.persister as ps  # noqa: E402
import importing.pipeline as pl   # noqa: E402
import importing.seed as sd       # noqa: E402


class SeedSeDolarizaAlDolarDeHoyTest(unittest.TestCase):

    def _bloque_del_seed(self):
        src = inspect.getsource(ps)
        i = src.index("_synthetic_seed")
        return src[i:i + 3000]

    def test_el_seed_no_pasa_fecha_a_la_conversion(self):
        """Sin `date=`, `_stamp_gross_amount_usd` usa el tc_blue actual."""
        bloque = self._bloque_del_seed()
        j = bloque.index("_stamp_gross_amount_usd(st.currency")
        llamada = bloque[j:j + 260]
        self.assertNotIn("date=", llamada, f"el seed volvió al TC de su fecha:\n{llamada}")
        self.assertNotIn("fx_version", llamada)
        self.assertIn("_tc_blue_seed", llamada)

    def test_la_conversion_ignora_la_fecha_si_no_se_la_pasan(self):
        """Contrato de `_stamp_gross_amount_usd`: sin conn/date cae al tc_blue."""
        # 130.667.268 pesos al dólar de hoy (1415) = 92.344, no 3.090.522.
        hoy = pl._stamp_gross_amount_usd("ARS", 130_667_268, 1415.0)
        self.assertAlmostEqual(hoy, 92_344.4, places=0)
        self.assertLess(hoy, 200_000)

    def test_el_mismo_monto_al_dolar_de_2019_es_el_bug(self):
        """Documenta la magnitud: por qué esto no puede ir al TC de la fecha."""
        con_tc_2019 = 130_667_268 / 42.28
        self.assertGreater(con_tc_2019, 3_000_000)
        self.assertGreater(con_tc_2019 / (130_667_268 / 1415.0), 30)   # ×33

    def test_las_filas_REALES_si_van_al_tc_de_su_fecha(self):
        """El fix es quirúrgico: sólo el seed. En una fila del archivo la fecha y
        el monto pertenecen al mismo momento, así que ahí el TC histórico va."""
        src = inspect.getsource(pl)
        self.assertIn("date=tx.date if _hist else None", src)
        self.assertIn("date=tx.date if _hist2 else None", src)

    def test_la_fecha_del_seed_sigue_siendo_la_vieja(self):
        """Si algún día el seed dejara de fecharse en el pasado, este fix podría
        revisarse. Mientras `_minus_one_day` siga ahí, no."""
        s = inspect.getsource(sd)
        self.assertIn("_minus_one_day", s)
        self.assertIn("earliest = min(all_dates)", s)


if __name__ == "__main__":
    unittest.main()
