"""F5 — "¿le ganaste a la inflación?" se contesta SIEMPRE en pesos.

EL BUG
──────
Cinco superficies restaban la inflación del INDEC —que mide precios argentinos,
o sea pesos— a un rendimiento medido en DÓLARES. A la resta le faltaba la
devaluación, que es exactamente lo que separa las dos monedas.

Lo más caro estaba en Reportes: `delta_pct` YA se convertía a pesos cuando el
selector estaba en Pesos (`_pct_puntas_ars`), y el benchmark contra el que se lo
restaba no. Se movía la cartera y no la referencia.

MEDIDO con inflación del INDEC y la serie de dólar reales, sobre una cartera
100 % en dólares y PLANA:

    el veredicto se daba vuelta con sólo tocar el selector de moneda
    en 65 de 186 meses (35 %), y en 6 de los últimos 14

    2024 completo → "te ganó por 117,7pp" en dólares · por 44,9pp en pesos
    2025 completo → "te ganó por  31,5pp" en dólares · por  5,4pp en pesos

DECIDIDO POR EL DUEÑO: la comparación se hace siempre en pesos — es la pregunta
que la gente quiere contestar ("¿mi plata le ganó a los precios del
supermercado?") y los precios del supermercado están en pesos.

CUÁLES MIDEN DE VERDAD. Contra el código viejo, los de `LaReglaTest` fallan
porque `twr.vs_inflacion_ar` todavía no existe — eso prueba que la función es
nueva, no que el número estaba mal. El que MIDE es
`ReportesLaUsaTest::test_en_dolares_la_comparacion_va_en_pesos`, que atraviesa
`compute_metrics_for_period` —el mismo camino que producción— y falla con
`5.02 != 26.92`: el viejo publicaba 5,02pp donde la respuesta en pesos es 26,92.
Y `test_sin_serie_de_dolar_no_publica_el_vs`, que falla con `5.02 is not None`.

Corre con: cd backend && python3 -m pytest tests/test_vs_inflacion_en_pesos.py
"""
import unittest

import main
import twr
from reporting import builder


class LaReglaTest(unittest.TestCase):
    """`twr.vs_inflacion_ar` — la aritmética, sin base de datos."""

    def test_cartera_plana_en_dolares_con_devaluacion_le_gana(self):
        """EL CASO. 0 % en dólares, 50 % de devaluación, 20 % de inflación."""
        r_ars, delta = twr.vs_inflacion_ar(0.0, 20.0, fx0=1000, fx1=1500)
        self.assertAlmostEqual(r_ars, 50.0, places=6)
        self.assertAlmostEqual(delta, 30.0, places=6)
        self.assertGreater(delta, 0, "con la devaluación adentro, le ganó")
        # Lo que publicaba antes sobre la MISMA cartera:
        self.assertLess(0.0 - 20.0, 0, "sin la devaluación, 'te ganó'")

    def test_compone_no_suma(self):
        """+10 % con +20 % de devaluación es +32 %, no +30 %."""
        r_ars, _ = twr.vs_inflacion_ar(10.0, 0.0, fx0=1000, fx1=1200)
        self.assertAlmostEqual(r_ars, 32.0, places=6)

    def test_en_pesos_el_motor_ya_lo_midio_y_no_se_toca(self):
        """Con el selector en Pesos el retorno viene medido en pesos por el motor.

        Esa vía es la EXACTA (leg a leg, cada punta al TC de su fecha); la
        conversión es la aproximación. Volver a convertirlo contaría la
        devaluación dos veces.
        """
        r_ars, delta = twr.vs_inflacion_ar(31.42, 4.5, moneda=twr.MONEDA_ARS,
                                           fx0=1000, fx1=1200)
        self.assertAlmostEqual(r_ars, 31.42, places=6)
        self.assertAlmostEqual(delta, 26.92, places=6)

    def test_sin_tc_no_publica(self):
        """Un `None` es "no sé". Publicar la resta de dos monedas es afirmar algo
        falso, y es lo que hacía antes."""
        self.assertEqual(twr.vs_inflacion_ar(10.0, 4.5), (None, None))
        self.assertEqual(twr.vs_inflacion_ar(10.0, 4.5, fx0=1000, fx1=None), (None, None))
        self.assertEqual(twr.vs_inflacion_ar(10.0, 4.5, fx0=0, fx1=1200), (None, None))

    def test_sin_inflacion_no_publica(self):
        self.assertEqual(twr.vs_inflacion_ar(10.0, None, fx0=1000, fx1=1200), (None, None))

    def test_el_exceso_sale_del_retorno_que_devuelve(self):
        """La pantalla muestra las dos cosas; si no salen una de la otra, se
        contradice sola."""
        r_ars, delta = twr.vs_inflacion_ar(7.0, 3.0, fx0=900, fx1=1100)
        self.assertAlmostEqual(r_ars - 3.0, delta, places=9)


class ReportesLaUsaTest(unittest.TestCase):
    """El camino de producción: `compute_metrics_for_period`, el mismo que
    atraviesa Reportes. No se prueba el helper directo — se prueba que Reportes
    lo use, que es donde vivía el bug."""

    INFLACION_MES = 4.5
    BENCH = {"inflation_ar": {"2026-03": INFLACION_MES}}

    def setUp(self):
        self.conn = main.get_db()
        # Email único por test: `users.email` es UNIQUE y el setUp corre una vez
        # por método.
        import uuid
        self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES (?,'x',1,1)", (f"infl-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.uid = self.conn.execute(
            "SELECT id FROM users ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.conn.execute(
            """INSERT INTO monthly_entries
                  (user_id, broker, year, month, capital_inicio, capital_final,
                   deposits, withdrawals, pnl_realized, pnl_unrealized)
               VALUES (?, 'global', 2026, 3, 5000, 6000, 500, 0, 200, 300)""",
            (self.uid,))
        # El peso se devalúa 20 % dentro del mes. Las dos puntas son el último día
        # del mes anterior y el último del mes, igual que el motor.
        for fecha, tc in (("2026-02-28", 1000.0), ("2026-03-31", 1200.0)):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                (fecha, tc, tc))
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            # `fx_rates_daily` es GLOBAL (no lleva user_id): se borran las fechas
            # que sembró este test, no la tabla.
            self.conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                              ("2026-02-28", "2026-03-31"))
        except Exception:
            pass
        self.conn.commit()
        self.conn.close()

    def _metrics(self, moneda="usd"):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-03-01", "2026-03-31",
            broker_filter="global", bench=self.BENCH, moneda=moneda)
        return m

    def test_en_dolares_la_comparacion_va_en_pesos(self):
        """Contra el código viejo esto falla: publicaba 9,52 − 4,5 = +5,02pp."""
        m = self._metrics("usd")
        # Modified Dietz del mes = 500 / (5000 + 250) = 9,52 % en DÓLARES
        self.assertAlmostEqual(m.delta_pct, 9.52, places=1)
        # LA ASERCIÓN QUE MIDE VA PRIMERO, sobre un campo que YA EXISTÍA. Si lo
        # primero que se toca es `retorno_ars_pct` —que es nuevo— contra el código
        # viejo el test falla con AttributeError, o sea probando que el campo es
        # nuevo y no que el número estaba mal.
        #
        # El número en pesos es 31,33 %, no 31,42 %. La diferencia (0,09pp) NO es
        # un error: es el residuo intrínseco de Modified Dietz que documenta
        # `twr._leg_en_moneda`. Componer `(1 + r_usd) × (fx1/fx0)` daría 31,42,
        # pero acá se usa `_pct_en_pesos` —la MISMA función que la rama de pesos—,
        # que lleva cada punta al TC de SU fecha y el flujo al TC medio geométrico:
        #     ci  = 5.000 × 1.000                    = 5.000.000
        #     cf  = 6.000 × 1.200                    = 7.200.000
        #     net =   500 × √(1.000 × 1.200)         =   547.723
        #     (7.200.000 − 5.000.000 − 547.723) / (5.000.000 + 273.861) = 31,33 %
        # Con flujo CERO las dos cuentas coinciden al bit (lo fija
        # monthlyReturnArs.test.js). El residuo aparece sólo cuando hay aportes.
        self.assertAlmostEqual(m.vs_inflation_pct, 31.33 - self.INFLACION_MES, places=1)
        self.assertNotAlmostEqual(m.vs_inflation_pct, 9.52 - self.INFLACION_MES, places=1)
        self.assertAlmostEqual(m.retorno_ars_pct, 31.33, places=1)

    def test_el_benchmark_propio_no_se_toca(self):
        """`inflation_pct` sigue siendo la inflación del mes, tal cual. Lo que
        cambia es contra QUÉ se la resta."""
        self.assertAlmostEqual(self._metrics("usd").inflation_pct,
                               self.INFLACION_MES, places=2)

    def test_el_veredicto_no_depende_del_selector(self):
        """Lo que el dueño pidió: la misma cartera, el mismo mes, la misma
        respuesta en las dos monedas."""
        en_usd = self._metrics("usd").vs_inflation_pct
        en_ars = self._metrics("ars").vs_inflation_pct
        self.assertIsNotNone(en_usd)
        self.assertIsNotNone(en_ars)
        self.assertEqual(en_usd >= 0, en_ars >= 0,
                         f"el veredicto se da vuelta: {en_usd} vs {en_ars}")

    def test_sin_serie_de_dolar_no_publica_el_vs(self):
        """Y entonces tampoco publica el retorno convertido: los dos o ninguno."""
        self.conn.execute("DELETE FROM fx_rates_daily")
        self.conn.commit()
        m = self._metrics("usd")
        self.assertIsNone(m.vs_inflation_pct)
        self.assertIsNone(m.retorno_ars_pct)
        # El rendimiento en dólares sigue publicándose: ése nunca estuvo mal.
        self.assertAlmostEqual(m.delta_pct, 9.52, places=1)


if __name__ == "__main__":
    unittest.main()
