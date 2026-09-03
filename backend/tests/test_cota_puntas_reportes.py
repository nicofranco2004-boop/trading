"""La cota de cordura en las PUNTAS, y el modo pesos de la vía contable.

Dos agujeros que quedaron abiertos después de que la composición mes a mes
heredara la cota del motor:

§1 — La composición vive dentro de `if rows and not _hay_agujero and
     _cubre_el_periodo`. Al usuario cuya contabilidad tiene un hueco no se le
     compone nada: `year_twr_pct` queda en None y el año publica el Modified
     Dietz punta a punta, que nadie revisó. Medido sobre la copia de producción
     del 2026-08-16, año 2026: el uid 659 leía **+70.683 %** (v0 = 0, US$113,87
     de flujo, US$40.359 de valor final) y el uid 176 leía **−199,28 %**, que es
     imposible: el piso de un retorno es −100 %.

§2 — `bordes_mercado_periodo` devuelve DÓLARES y la cadena contable también. Con
     el selector global en Pesos, el calendario mezclaba las dos monedas en la
     misma grilla y las componía como si fueran la misma unidad. Medido en
     pantalla: ENE–JUN idénticos a los de dólares y sólo AGO convertido.

⚠️ El fixture del §2 necesita TC en dos fechas distintas. Con un solo TC —o con
el mismo valor en las dos puntas— el factor se cancela y el caso es inexhibible:
el test pasaría con el bug puesto.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main  # noqa: E402
from reporting import builder  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries",
                  "fx_rates_daily", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cotapuntas@t", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def mes(self, month, ci, cf, dep=0.0, wd=0.0, year=2026):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, "
            "capital_inicio, capital_final, deposits, withdrawals) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.uid, "global", year, month, ci, cf, dep, wd))
        self.conn.commit()

    def fx(self, date, mep):
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, mep_venta, blue_venta) VALUES (?,?,?)",
            (date, mep, mep))
        self.conn.commit()

    def anio(self, moneda="usd"):
        return builder.compute_metrics_for_period(
            self.conn, self.uid, "year", "2026-01-01", "2026-12-31",
            "global", None, moneda=moneda)[0]


class CotaEnLasPuntasTest(_Base):

    def test_el_salto_sin_aportes_que_lo_explique_no_se_publica(self):
        """El caso del uid 659: US$113 de flujo, US$40.359 de valor final."""
        self.mes(1, 0.0, 84.5, dep=84.5)
        self.mes(2, 84.5, 40359.55, dep=29.37)   # el hueco: falta marzo en adelante
        m = self.anio()
        self.assertIsNone(m.delta_pct,
                          "un +70.683 % no es un rendimiento, es el agujero de la contabilidad")
        self.assertEqual(m.motor_motivo, "medicion_dudosa")
        self.assertTrue(m.basis_incomparable,
                        "sin esto el frontend cae en isFlat y publica 'Sin movimientos'")

    def test_el_desborde_tampoco(self):
        """El caso del uid 176: −199,28 %, y el piso de un retorno es −100 %.

        `leg_dudoso` ya sabe cazarlo ('desborde', el Dietz tocando su piso), pero
        sólo se lo llamaba con v0 > 0 — y acá v0 es 0, que es justo la forma en la
        que llegaba.
        """
        self.mes(1, 0.0, 8330.16, dep=2333425.46, wd=21239.17)
        m = self.anio()
        self.assertIsNone(m.delta_pct)
        self.assertEqual(m.motor_motivo, "medicion_dudosa")

    def test_la_cuenta_nueva_SANA_sigue_publicando(self):
        """La cota no puede comerse al usuario que simplemente empezó de cero.

        Deposita 1.000 y termina en 1.100: el flujo explica el capital, no hay
        nada dudoso. Si este test se pone rojo, la cota está de más.
        """
        self.mes(1, 0.0, 1000.0, dep=1000.0)
        self.mes(2, 1000.0, 1100.0)
        m = self.anio()
        self.assertIsNotNone(m.delta_pct, "esta cuenta no tiene nada de raro")
        # El motivo puede venir igual ('sin_historia': el motor canónico no tiene
        # serie que medir en este fixture). Lo que NO puede es ser uno de los que
        # CORTAN: ésa es toda la diferencia entre "no tengo con qué medirlo" y "lo
        # que tengo no se puede creer", y confundirlas dejaba sin número a seis
        # tests de usuarios perfectamente sanos.
        self.assertNotIn(m.motor_motivo, builder.MOTIVOS_DATO_ROTO)
        self.assertFalse(m.basis_incomparable)


class ModoPesosViaContableTest(_Base):

    def test_el_mismo_ano_en_pesos_incluye_la_devaluacion(self):
        """+10 % en dólares con el TC subiendo 20 % NO es +10 % en pesos."""
        self.fx("2025-12-31", 1000.0)
        self.fx("2026-12-31", 1200.0)
        self.mes(1, 1000.0, 1000.0)
        self.mes(12, 1000.0, 1100.0)

        usd = self.anio("usd").delta_pct
        ars = self.anio("ars").delta_pct
        self.assertIsNotNone(usd)
        self.assertIsNotNone(ars)
        self.assertNotEqual(
            usd, ars,
            "si el FX se cancela arriba y abajo, el 'retorno en pesos' es el de dólares")
        # (1 + r_usd) · (f1/f0) − 1, que es la propiedad que la pantalla necesita:
        # cartera y benchmark convertidos por el MISMO factor.
        esperado = ((1 + usd / 100.0) * (1200.0 / 1000.0) - 1) * 100
        self.assertAlmostEqual(ars, esperado, delta=0.5)

    def test_sin_TC_no_inventa_un_numero(self):
        """Sin serie de FX la conversión no se puede hacer — se deja el de dólares,
        no un cero ni un None que borre el dato."""
        self.mes(1, 1000.0, 1000.0)
        self.mes(12, 1000.0, 1100.0)
        self.assertEqual(self.anio("ars").delta_pct, self.anio("usd").delta_pct)


if __name__ == "__main__":
    unittest.main()
