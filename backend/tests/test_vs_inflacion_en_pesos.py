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
        # En pesos: (1,0952 × 1,20 − 1) = 31,42 %  →  31,42 − 4,5 = 26,92pp
        self.assertAlmostEqual(m.vs_inflation_pct, 31.42 - self.INFLACION_MES, places=1)
        self.assertNotAlmostEqual(m.vs_inflation_pct, 9.52 - self.INFLACION_MES, places=1)
        self.assertAlmostEqual(m.retorno_ars_pct, 31.42, places=1)

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

    def test_el_retorno_en_pesos_ES_delta_pct_visto_en_pesos(self):
        """LA PROPIEDAD. No "un número exacto": EL MISMO número, en pesos.

        `1 + r_ars = (1 + r_usd) × (fx1/fx0)`, al bit. Si esto se rompe, la
        tarjeta publica un exceso que no sale del rendimiento que muestra — y eso
        es indistinguible de un error de cuenta para quien la lee.

        Con tolerancia APRETADA a propósito: la primera versión de este arreglo
        recalculaba el rendimiento con `_pct_en_pesos` en vez de convertir
        `delta_pct`, y fallaba acá por 0,09pp. Esa forma chica es la misma que en
        un mes donde el motor publica se vuelve enorme (ver la clase de abajo).
        """
        m = self._metrics("usd")
        fx0, fx1 = 1000.0, 1200.0
        esperado = ((1 + m.delta_pct / 100) * (fx1 / fx0) - 1) * 100
        self.assertAlmostEqual(m.retorno_ars_pct, esperado, places=1)
        self.assertAlmostEqual(m.retorno_ars_pct - m.inflation_pct,
                               m.vs_inflation_pct, places=1)

    def test_sin_serie_de_dolar_no_publica_el_vs(self):
        """Y entonces tampoco publica el retorno convertido: los dos o ninguno."""
        self.conn.execute("DELETE FROM fx_rates_daily")
        self.conn.commit()
        m = self._metrics("usd")
        self.assertIsNone(m.vs_inflation_pct)
        self.assertIsNone(m.retorno_ars_pct)
        # El rendimiento en dólares sigue publicándose: ése nunca estuvo mal.
        self.assertAlmostEqual(m.delta_pct, 9.52, places=1)


class CuandoElMotorPisaElNumeroTest(unittest.TestCase):
    """EL CASO GRAVE, reproducido. Para un MES CERRADO sin bordes de mercado el
    día exacto anterior, `curva_indexada` igual mide con las fotos que hay
    ADENTRO y su número pisa `delta_pct` — pero `start_value`/`end_value` se
    quedan siendo los de la CADENA CONTABLE (esa rama no los reemplaza; la otra,
    la de `bordes_mercado_periodo`, sí).

    Con lo cual recalcular el rendimiento en pesos desde `start_value`/`end_value`
    publica un número que no tiene NADA que ver con el `delta_pct` que la misma
    tarjeta muestra. Medido con este fixture:

        delta_pct          −40,00 %   (el mercado: la cartera se derrumbó)
        retorno_ars_pct    +24,32 %   (la contabilidad llevada a pesos)
        vs_inflation_pct   +19,82pp   → "LE GANASTE A LA INFLACIÓN"

    52 puntos de diferencia y el signo invertido, sobre un mes en que el usuario
    perdió el 40 %. Por eso el rendimiento en pesos se COMPONE desde `delta_pct` y
    no se recalcula: la composición sigue a `delta_pct` sea cual sea el motor que
    lo haya producido.
    """

    INFLACION_MES = 4.5
    BENCH = {"inflation_ar": {"2026-03": INFLACION_MES}}
    FX0, FX1 = 1000.0, 1200.0          # +20 % de devaluación en el mes

    def setUp(self):
        import uuid
        self.conn = main.get_db()
        self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES (?,'x',1,1)", (f"motor-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.uid = self.conn.execute(
            "SELECT id FROM users ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.conn.execute(
            "INSERT INTO positions (user_id,broker,asset,is_cash,quantity,invested,entry_date) "
            "VALUES (?,'IBKR','AAPL',0,1,100000,'2025-01-01')", (self.uid,))
        # CONTABILIDAD: 100.000 → 103.600, todo realizado. +3,6 %.
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id,broker,year,month,capital_inicio,"
            "capital_final,deposits,withdrawals,pnl_realized,pnl_unrealized) "
            "VALUES (?,'global',2026,3,100000,103600,0,0,3600,0)", (self.uid,))
        # MERCADO: fotos DENTRO del mes y NINGUNA el día anterior. Esa ausencia es
        # lo que manda el mes a la rama donde el motor mide pero start/end no se
        # reemplazan — con una foto el 28/02 el bug no se reproduce.
        for d, v in (("2026-03-05", 100000.0), ("2026-03-12", 85000.0),
                     ("2026-03-20", 70000.0), ("2026-03-28", 60000.0)):
            self.conn.execute(
                "INSERT INTO snapshots (user_id,date,total_value,total_invested,"
                "net_deposited,source,fx_to_usd_blue,holdings_json) "
                "VALUES (?,?,?,?,0,'cron',1200.0,'[]')", (self.uid, d, v, v))
        for d, tc in (("2026-02-28", self.FX0), ("2026-03-31", self.FX1)):
            self.conn.execute(
                "INSERT OR REPLACE INTO fx_rates_daily (date,blue_venta,mep_venta) "
                "VALUES (?,?,?)", (d, tc, tc))
        self.conn.commit()

    def tearDown(self):
        for sql, args in (
            ("DELETE FROM snapshots WHERE user_id=?", (self.uid,)),
            ("DELETE FROM positions WHERE user_id=?", (self.uid,)),
            ("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,)),
            ("DELETE FROM users WHERE id=?", (self.uid,)),
            ("DELETE FROM fx_rates_daily WHERE date IN (?,?)", ("2026-02-28", "2026-03-31")),
        ):
            try:
                self.conn.execute(sql, args)
            except Exception:
                pass
        self.conn.commit()
        self.conn.close()

    def _metrics(self):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-03-01", "2026-03-31",
            broker_filter="global", bench=self.BENCH, moneda="usd")
        return m

    def test_el_fixture_mide(self):
        """Si el motor no pisara `delta_pct`, o si start/end vinieran del mercado,
        este archivo entero certificaría en verde algo que no está probando."""
        m = self._metrics()
        self.assertEqual(m.basis, "mercado")
        self.assertAlmostEqual(m.delta_pct, -40.0, places=1)
        self.assertAlmostEqual(m.start_value, 100000.0, places=2)
        self.assertAlmostEqual(m.end_value, 103600.0, places=2)   # la CONTABLE

    def test_el_retorno_en_pesos_sigue_a_delta_pct_y_no_a_la_contabilidad(self):
        m = self._metrics()
        esperado = ((1 + m.delta_pct / 100) * (self.FX1 / self.FX0) - 1) * 100
        self.assertAlmostEqual(m.retorno_ars_pct, esperado, places=1,
                               msg="el rendimiento en pesos no es `delta_pct` en pesos")
        self.assertAlmostEqual(m.retorno_ars_pct, -28.0, places=1)

    def test_no_publica_que_le_gano_a_la_inflacion_en_un_mes_que_perdio_40(self):
        m = self._metrics()
        self.assertLess(m.vs_inflation_pct, 0,
                        "publicó 'le ganaste a la inflación' sobre un derrumbe del 40 %")
        self.assertAlmostEqual(m.vs_inflation_pct, -28.0 - self.INFLACION_MES, places=1)


if __name__ == "__main__":
    unittest.main()
