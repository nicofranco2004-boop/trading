"""El resultado de un período en pesos lo calcula el SERVIDOR, y dice de qué tipo es.

EL DEFECTO (tercera auditoría del 30/10/2026). `delta_usd` se arma de cuatro maneras
—resta de puntas a mercado, resta de la cadena al costo, delta del motor mensual,
realizado de un broker filtrado— y la pantalla en Pesos intentaba adivinar cuál era
mirando los números. Se equivocaba en las dos direcciones:

  · en períodos al COSTO (broker filtrado, cuentas sin fotos del cron, primer año
    cerrado) la identidad `delta == fin − inicio − flujos` se cumple por
    construcción, la pantalla la tomaba por mercado y multiplicaba costo en dólares
    por el dólar de las fechas: un año con +$32.546 reales salía +$66.771;
  · en los meses del MOTOR la identidad no se cumple, la pantalla caía a otra
    fórmula y el monto salía con el signo contrario al % de la misma tarjeta.

EL ARREGLO. `PeriodMetrics.medicion` dice de qué tipo es el delta ('mercado',
'motor', 'costo', 'realizado'). Con puntas a mercado trae además las fechas de las dos
fotos (`puntas_desde`/`puntas_hasta`: la pantalla pone cada punta a SU dólar) y, si el
delta es del motor mensual —otra ventana que start/end_value—, el resultado en pesos del
tramo (`delta_ars`: `fin − inicio − flujo`, cada punta al dólar de su fecha y el flujo al
dólar medio, las mismas patas que el `delta_pct` en pesos).

CÓMO SE PRUEBA. Todo atraviesa `compute_metrics_for_period`, el camino de producción,
con fotos del cron y dólares de fechas DISTINTAS: con el mismo dólar en todas las
fechas cualquier cuenta daría lo mismo y el test no mediría nada. Cada valor esperado
sale de multiplicar a mano.

Corre con: cd backend && python3 -m pytest tests/test_delta_ars_del_periodo.py
"""
import math
import unittest
from datetime import date

import main
from reporting import builder

FECHAS_FX = {
    "2024-05-31": 1000.0,
    "2024-06-03": 1050.0,
    "2024-06-07": 1000.0,
    "2024-06-09": 1100.0,
    "2024-06-16": 1100.0,
    "2024-06-20": 1400.0,
    "2024-06-28": 1450.0,
    "2024-06-30": 1500.0,
}
HOY_CERRADO = date(2024, 8, 1)


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"dars-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2024-01-01')",
            (self.uid,))
        self._fx(FECHAS_FX)
        self.conn.commit()

    def tearDown(self):
        # `fx_rates_daily` es GLOBAL: se borran las fechas sembradas acá, no la tabla.
        try:
            for fecha in self._fechas_fx:
                self.conn.execute("DELETE FROM fx_rates_daily WHERE date=?", (fecha,))
            for t in ("snapshots", "positions", "operations", "monthly_entries"):
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        finally:
            self.conn.close()

    _fechas_fx = ()

    def _fx(self, tabla):
        self._fechas_fx = tuple(self._fechas_fx) + tuple(tabla)
        for fecha, tc in tabla.items():
            self.conn.execute("DELETE FROM fx_rates_daily WHERE date=?", (fecha,))
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                (fecha, tc, tc))
        self.conn.commit()

    def _foto(self, fecha, valor, aportado=0.0):
        """Un cierre MEDIDO del cron (el único tipo que sirve de borde a mercado)."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,?,'cron',1000,'[]')",
            (self.uid, fecha, float(valor), float(valor), float(aportado)))
        self.conn.commit()

    def _mes(self, y, m, inicio, final, dep=0.0, ret=0.0, pnl=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,?,?,?,0)",
            (self.uid, y, m, inicio, final, dep, ret, pnl))
        self.conn.commit()

    def _metricas(self, tipo, desde, hasta, moneda="ars", broker="global",
                  live=None, today=HOY_CERRADO):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, tipo, desde, hasta, broker, None,
            live_value=live, modo="certero", moneda=moneda, today=today)
        return m


class MesCerradoConBordesTest(_Base):
    """Junio 2024: la cartera valía US$ 1.000 el 31/5 (dólar 1.000) y US$ 1.100 el 30/6
    (dólar 1.500). Las dos puntas son fotos medidas: tipo 'mercado'."""

    def _bordes(self):
        self._foto("2024-05-31", 1000, 1000)
        self._foto("2024-06-30", 1100, 1000)
        self._mes(2024, 6, 1000, 1000)          # la cadena al costo no sabe del mercado

    def test_dice_que_es_mercado_y_de_que_fechas_son_las_dos_fotos(self):
        self._bordes()
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertEqual(m.medicion, "mercado")
        self.assertAlmostEqual(m.delta_usd, 100.0, places=2)
        self.assertEqual((m.puntas_desde, m.puntas_hasta), ("2024-05-31", "2024-06-30"))

    def test_el_monto_en_pesos_de_este_tipo_lo_arma_la_pantalla(self):
        """El servidor sólo conoce un dólar medio para los aportes; la pantalla sabe los
        pesos que de verdad entraron. Por eso acá no publica un monto."""
        self._bordes()
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertIsNone(m.delta_ars)

    def test_con_el_selector_en_dolares_tambien_se_dice_el_tipo(self):
        self._bordes()
        m = self._metricas("month", "2024-06-01", "2024-06-30", moneda="usd")
        self.assertEqual(m.medicion, "mercado")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), ("2024-05-31", "2024-06-30"))


class MesAlCostoTest(_Base):
    """El caso de la documentación: 100 GGAL comprados a $4.500 con el dólar a 1.000
    (costo US$ 450) y vendidos a $6.900 con el dólar a 1.500 (US$ 460). La cadena
    al costo dice +US$ 10; multiplicar costo por el dólar de las fechas inventaría
    pesos que no existieron."""

    def test_la_cadena_al_costo_no_es_mercado_ni_trae_fechas_ni_monto(self):
        self._mes(2024, 6, 450, 460, pnl=10)
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertEqual(m.medicion, "costo")
        self.assertIsNone(m.delta_ars)
        self.assertEqual((m.puntas_desde, m.puntas_hasta), (None, None))
        self.assertAlmostEqual(m.delta_usd, 10.0, places=2)

    def test_la_identidad_se_cumple_en_el_costo_y_aun_asi_no_es_mercado(self):
        """`delta == fin − inicio − flujos` vale por construcción en la cadena: es
        exactamente la trampa en la que cayó la pantalla."""
        self._mes(2024, 6, 450, 460, pnl=10)
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertAlmostEqual(m.delta_usd, m.end_value - m.start_value, places=2)
        self.assertEqual(m.medicion, "costo")

    def test_el_ano_cerrado_al_costo_tampoco(self):
        for mes in range(1, 13):
            self._mes(2023, mes, 1000 + 10 * (mes - 1), 1000 + 10 * mes, pnl=10)
        m = self._metricas("year", "2023-01-01", "2023-12-31")
        self.assertEqual(m.medicion, "costo")
        self.assertIsNone(m.delta_ars)

    def test_un_broker_filtrado_en_el_mes_es_al_costo(self):
        """Los snapshots son globales: con un broker filtrado no hay mercado."""
        self._foto("2024-05-31", 1000, 1000)
        self._foto("2024-06-30", 1100, 1000)
        self._mes(2024, 6, 1000, 1000)
        m = self._metricas("month", "2024-06-01", "2024-06-30", broker="IBKR")
        self.assertEqual(m.medicion, "costo")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), (None, None))


class MesDelMotorTest(_Base):
    """Sin una foto pegada al 31/5 el mes no tiene bordes a mercado, pero el motor
    mensual mide la ventana con los puntos que hay (3/6 → 28/6)."""

    def _ventana(self, fin=1100):
        self._foto("2024-06-03", 1000, 1000)
        self._foto("2024-06-28", fin, 1000)
        self._mes(2024, 6, 1000, 1000)

    def test_el_monto_en_pesos_es_el_de_la_ventana_del_motor(self):
        self._ventana()
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertEqual(m.medicion, "motor")
        self.assertAlmostEqual(m.delta_usd, 100.0, places=2)
        # Cada punta al dólar de SU foto (3/6 → 1.050, 28/6 → 1.450), no al del 31/5
        # (1.000) ni al del 30/6 (1.500) que tomaría un cálculo por la fecha del mes.
        self.assertAlmostEqual(m.delta_ars, 1100 * 1450 - 1000 * 1050, places=2)

    def test_el_motor_no_trae_fechas_de_puntas_porque_no_son_start_ni_end_value(self):
        self._ventana()
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), (None, None))

    def test_una_cartera_en_dolares_que_cae_gana_en_pesos_si_el_dolar_sube_mas(self):
        """El caso B de la auditoría: −0,2 % en dólares con el dólar +38 %. El monto
        en pesos tiene que ser positivo como el % de la misma tarjeta."""
        self._ventana(fin=998)
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertEqual(m.medicion, "motor")
        self.assertLess(m.delta_usd, 0)
        self.assertGreater(m.delta_ars, 0)
        self.assertGreater(m.delta_pct, 0)

    def test_con_el_selector_en_dolares_no_se_publica_el_monto_en_pesos(self):
        self._ventana()
        m = self._metricas("month", "2024-06-01", "2024-06-30", moneda="usd")
        self.assertEqual(m.medicion, "motor")
        self.assertIsNone(m.delta_ars)

    def test_con_un_deposito_el_flujo_va_al_dolar_medio_de_la_ventana(self):
        self._foto("2024-06-03", 1000, 1000)
        self._foto("2024-06-28", 1300, 1200)
        self._mes(2024, 6, 1000, 1200, dep=200)
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertEqual(m.medicion, "motor")
        esperado = 1300 * 1450 - 1000 * 1050 - 200 * math.sqrt(1050 * 1450)
        self.assertAlmostEqual(m.delta_ars, esperado, places=1)

    def test_el_monto_y_el_porcentaje_en_pesos_salen_de_las_mismas_patas(self):
        self._ventana()
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertAlmostEqual(m.delta_ars / (1000 * 1050) * 100, m.delta_pct, places=0)

    def test_sin_dolar_de_esas_fechas_no_se_afirma_un_monto(self):
        """Sin dólar usable no hay pesos: queda None y la pantalla lo dice."""
        self._ventana()
        self.conn.execute("DELETE FROM fx_rates_daily")
        self.conn.commit()
        m = self._metricas("month", "2024-06-01", "2024-06-30")
        self.assertIsNone(m.delta_ars)


class SemanaTest(_Base):
    def test_las_fechas_son_las_de_las_fotos_y_no_las_del_periodo(self):
        """La semana del 10 al 16/6 arranca con la foto del VIERNES 7/6. Adivinar por la
        fecha del período tomaba el domingo 9/6 (otro dólar) y contaba el cierre del
        propio viernes como ganancia del dólar sobre todo el capital."""
        self._foto("2024-06-07", 1000, 1000)
        self._foto("2024-06-16", 1050, 1000)
        m = self._metricas("week", "2024-06-10", "2024-06-16")
        self.assertEqual(m.medicion, "mercado")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), ("2024-06-07", "2024-06-16"))

    def test_la_semana_en_curso_cierra_hoy(self):
        self._foto("2024-06-07", 1000, 1000)
        m = self._metricas("week", "2024-06-10", "2024-06-16", live=1050,
                           today=date(2024, 6, 12))
        self.assertEqual(m.medicion, "mercado")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), ("2024-06-07", "2024-06-12"))

    def test_una_foto_de_cierre_que_no_es_medida_no_es_mercado(self):
        """La fila cruda del cierre puede ser la que el import fabricó al costo."""
        self._foto("2024-06-07", 1000, 1000)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,?,?,?,?,'import')",
            (self.uid, "2024-06-16", 1050.0, 1050.0, 1000.0))
        self.conn.commit()
        m = self._metricas("week", "2024-06-10", "2024-06-16")
        self.assertEqual(m.medicion, "costo")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), (None, None))

    def test_con_un_broker_filtrado_el_delta_es_el_realizado(self):
        self._foto("2024-06-07", 1000, 1000)
        self._foto("2024-06-16", 1050, 1000)
        m = self._metricas("week", "2024-06-10", "2024-06-16", broker="IBKR")
        self.assertEqual(m.medicion, "realizado")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), (None, None))
        self.assertIsNone(m.delta_ars)

    def test_sin_ninguna_foto_medida_no_hay_tramo_a_mercado(self):
        m = self._metricas("week", "2024-06-10", "2024-06-16")
        self.assertEqual(m.medicion, "costo")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), (None, None))


class MesEnCursoTest(_Base):
    def test_el_cierre_es_el_valor_vivo_de_hoy(self):
        self._foto("2024-05-31", 1000, 1000)
        self._mes(2024, 6, 1000, 1000)
        m = self._metricas("month", "2024-06-01", "2024-06-30", live=1100,
                           today=date(2024, 6, 20))
        self.assertEqual(m.medicion, "mercado")
        # Hoy es el 20/6; el 30/6 todavía no pasó.
        self.assertEqual((m.puntas_desde, m.puntas_hasta), ("2024-05-31", "2024-06-20"))

    def test_el_ano_en_curso_arranca_con_el_cierre_de_diciembre(self):
        self._foto("2023-12-29", 1000, 1000)
        self._fx({"2023-12-29": 900.0})
        m = self._metricas("year", "2024-01-01", "2024-12-31", live=1100,
                           today=date(2024, 6, 20))
        self.assertEqual(m.medicion, "mercado")
        self.assertEqual((m.puntas_desde, m.puntas_hasta), ("2023-12-29", "2024-06-20"))


if __name__ == "__main__":
    unittest.main()
