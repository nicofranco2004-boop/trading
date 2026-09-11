"""F6 — el % del AÑO en pesos publicaba el número de DÓLARES.

EL BUG, y por qué daba vuelta DOS veredictos a la vez
─────────────────────────────────────────────────────
Para el año, `delta_pct` tiene tres fuentes posibles y sólo dos estaban en la
moneda del selector:

  · `_pct_puntas_ars`                  → en pesos ✅
  · el motor `curva_indexada`          → recibe `moneda=`, en pesos ✅
  · la COMPOSICIÓN de `monthly_entries` → en DÓLARES ❌, y PISA a las otras

`monthly_entries` lleva la contabilidad en dólares, así que el producto de los
Dietz mensuales es un retorno en dólares. Esa rama corre justo cuando el motor
canónico no puede medir —el usuario sin fotos de mercado suficientes, que es
mayoría— y treinta líneas más abajo pisa a `delta_pct`.

Del otro lado, el benchmark del año SÍ se convierte a pesos. Con lo cual la resta
quedaba cruzada, y no en una comparación sino en las dos.

MEDIDO por `compute_metrics_for_period` con este fixture — cartera PLANA en
dólares (+26,82 % el año por P&L realizado), el peso valiendo la mitad al cierre
(TC 1.000 → 2.000), S&P +2 % e inflación 50 %:

                        ANTES (roto)        AHORA           la verdad en pesos
    delta_pct           26,82 %  ⚠️ = usd   153,64 %        153,64 %
    sp500_return_pct   104,00 %            104,00 %        104,00 %
    vs_sp500_pct       −77,18 pp  "te ganó" +49,64 pp       le ganaste
    vs_inflation_pct   −23,18 pp  "te ganó" +103,64 pp      le ganaste
    retorno_ars_pct     26,82 %  ⚠️ = usd   153,64 %        153,64 %

LA PRUEBA DE QUE EL NÚMERO BUENO YA EXISTÍA: con el selector en DÓLARES, la misma
respuesta publicaba `retorno_ars_pct = 153,64` — el año en pesos, bien calculado.
Con el selector en PESOS nadie lo miraba. Es el patrón del hallazgo O-01 del
informe: "el dato para decirlo bien viaja en la misma respuesta y nadie lo mira".

⚠️ ESTABA EN PRODUCCIÓN (`e9211ca5`, verificado con /api/health y version.json).

EL ARREGLO: se CONVIERTE la composición, no se recalcula (regla de F5), con las
puntas de `_ventana_comp` — el tramo que esa composición realmente cubre, que es
el MISMO que se le pasa al benchmark del año. Si las dos se midieran sobre tramos
distintos, la devaluación no se cancelaría entre rendimiento e índice y la resta
volvería a mezclar unidades, con un disfraz más difícil de ver.

CUÁL MIDE DE VERDAD
───────────────────
Todos los de `ElAnioEnPesosTest` atraviesan `compute_metrics_for_period`, el mismo
camino que producción, y todos fallan contra el código viejo:

    test_el_anio_en_pesos_no_es_el_de_dolares      →  26.82 != 153.64
    test_los_dos_veredictos_estaban_invertidos     →  -77.18 not greater than 0
    test_el_veredicto_no_depende_del_selector      →  False != True

`LaConversionTest` prueba el helper y NO mide el bug (la función es nueva).

⚠️ Para verificarlo hay que revertir SÓLO el código, dejando este archivo:
   git checkout <commit-anterior> -- backend/reporting/builder.py

Corre con: cd backend && python3 -m pytest tests/test_anio_en_pesos.py
"""
import unittest
import uuid

import main
from reporting import builder


class ElAnioEnPesosTest(unittest.TestCase):
    """El camino de producción. La cartera está PLANA EN DÓLARES a propósito: todo
    lo que se vea de más en pesos es devaluación, no mérito."""

    SP500_PCT_USD = 2.0
    INFLACION_PCT = 50.0
    # 12 meses de 5.000 → 5.100 sin flujos = (1,02)¹² − 1 = +26,82 % en dólares.
    RET_USD = 26.82
    # El peso vale la mitad: 1,2682 × 2 − 1 = +153,64 % en pesos.
    RET_ARS = 153.64
    # El S&P: 1,02 × 2 − 1 = +104 %.
    SP500_PCT_ARS = 104.0
    FECHAS_FX = ("2024-12-31", "2025-12-31")
    BENCH = {"sp500": {"2024-12": 100.0, "2025-12": 102.0},
             "inflation_ar": {"2025-12": INFLACION_PCT}}

    def setUp(self):
        self.conn = main.get_db()
        self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES (?,'x',1,1)", (f"anio-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.uid = self.conn.execute(
            "SELECT id FROM users ORDER BY id DESC LIMIT 1").fetchone()[0]
        for mes in range(1, 13):
            self.conn.execute(
                """INSERT INTO monthly_entries
                      (user_id, broker, year, month, capital_inicio, capital_final,
                       deposits, withdrawals, pnl_realized, pnl_unrealized)
                   VALUES (?, 'global', 2025, ?, 5000, 5100, 0, 0, 100, 0)""",
                (self.uid, mes))
        for fecha, tc in zip(self.FECHAS_FX, (1000.0, 2000.0)):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                (fecha, tc, tc))
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            # `fx_rates_daily` es GLOBAL: se borran las fechas que sembró este
            # test, no la tabla. Borrarla entera rompe otros archivos, y sólo en
            # la suite completa.
            self.conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                              self.FECHAS_FX)
        except Exception:
            pass
        self.conn.commit()
        self.conn.close()

    def _metrics(self, moneda="usd"):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "year", "2025-01-01", "2025-12-31",
            broker_filter="global", bench=self.BENCH, moneda=moneda)
        return m

    def test_en_dolares_nada_cambia(self):
        """La rama de dólares nunca estuvo mal y tiene que seguir igual."""
        m = self._metrics("usd")
        self.assertAlmostEqual(m.delta_pct, self.RET_USD, places=1)
        self.assertAlmostEqual(m.sp500_return_pct, self.SP500_PCT_USD, places=1)

    def test_el_anio_en_pesos_no_es_el_de_dolares(self):
        """EL QUE MIDE. Contra el código viejo falla con `26.82 != 153.64`."""
        m = self._metrics("ars")
        self.assertAlmostEqual(m.delta_pct, self.RET_ARS, places=1)
        self.assertNotAlmostEqual(m.delta_pct, self.RET_USD, places=1)

    def test_los_dos_veredictos_estaban_invertidos(self):
        """Contra el código viejo: −77,18 y −23,18, o sea "te ganaron los dos"
        sobre una cartera que les ganó a los dos."""
        m = self._metrics("ars")
        self.assertGreater(m.vs_sp500_pct, 0, "el S&P: decía 'te ganó por 77'")
        self.assertGreater(m.vs_inflation_pct, 0, "la inflación: decía 'te ganó por 23'")
        self.assertAlmostEqual(m.vs_sp500_pct, self.RET_ARS - self.SP500_PCT_ARS, places=1)

    def test_el_veredicto_no_depende_del_selector(self):
        """La misma cartera, el mismo año, la misma respuesta en las dos monedas.
        El exceso cambia de tamaño al cambiar de moneda —se escala con la
        devaluación, y eso es correcto—; el SIGNO no puede cambiar, porque es lo
        que la tarjeta publica en palabras."""
        for campo in ("vs_sp500_pct", "vs_inflation_pct"):
            en_usd = getattr(self._metrics("usd"), campo)
            en_ars = getattr(self._metrics("ars"), campo)
            self.assertIsNotNone(en_usd, campo)
            self.assertIsNotNone(en_ars, campo)
            self.assertEqual(en_usd >= 0, en_ars >= 0,
                             f"{campo} se da vuelta: {en_usd} vs {en_ars}")

    def test_la_inflacion_da_LO_MISMO_en_las_dos_monedas(self):
        """VERIFICACIÓN CRUZADA, y es la más fuerte del archivo.

        El veredicto contra inflación se mide SIEMPRE en pesos (decisión de F5), y
        se llega por dos caminos independientes: con el selector en dólares lo
        convierte `twr.vs_inflacion_ar`; con el selector en pesos, `delta_pct` ya
        viene convertido por el arreglo de acá. Si los dos están bien, el número
        es el MISMO — y si alguno se rompe, esto lo caza.

        Contra el código viejo: 103,64 contra −23,18.
        """
        self.assertAlmostEqual(self._metrics("usd").vs_inflation_pct,
                               self._metrics("ars").vs_inflation_pct, places=1)

    def test_el_retorno_en_pesos_es_el_mismo_por_los_dos_caminos(self):
        """`retorno_ars_pct` es el rendimiento en pesos del que sale la resta
        contra inflación. Tiene que valer lo mismo mire uno donde mire, y con el
        selector en pesos tiene que ser `delta_pct`."""
        en_usd = self._metrics("usd")
        en_ars = self._metrics("ars")
        self.assertAlmostEqual(en_usd.retorno_ars_pct, self.RET_ARS, places=1)
        self.assertAlmostEqual(en_ars.retorno_ars_pct, self.RET_ARS, places=1)
        self.assertAlmostEqual(en_ars.retorno_ars_pct, en_ars.delta_pct, places=1)

    def test_sin_TC_no_se_pisa_con_el_numero_de_dolares(self):
        """Si no se puede convertir, la composición NO pisa: `delta_pct` se queda
        con el punta-a-punta, que ya está medido en pesos. Degradar al número de
        la otra moneda sería volver a publicar el defecto."""
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                          self.FECHAS_FX)
        self.conn.commit()
        m = self._metrics("ars")
        if m.delta_pct is not None:
            self.assertNotAlmostEqual(
                m.delta_pct, self.RET_USD, places=1,
                msg="publicó el número de dólares con el selector en pesos")


class LaConversionTest(unittest.TestCase):
    """`_pct_comp_en_pesos` — el helper. NO MIDE EL BUG (es nuevo)."""

    def test_compone_no_suma(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                         ("2024-12-31", "2025-12-31"))
            for fecha, tc in (("2024-12-31", 1000.0), ("2025-12-31", 2000.0)):
                conn.execute("INSERT INTO fx_rates_daily "
                             "(date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (fecha, tc, tc))
            conn.commit()
            r = builder._pct_comp_en_pesos(
                conn, 26.82, ("2024-12-31", "2025-12-31"))
            # 1,2682 × 2 − 1 = 153,64 %, no 26,82 + 100.
            self.assertAlmostEqual(r, 153.64, places=1)
            self.assertNotAlmostEqual(r, 126.82, places=1)
        finally:
            conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                         ("2024-12-31", "2025-12-31"))
            conn.commit()
            conn.close()

    def test_sin_ventana_no_inventa(self):
        conn = main.get_db()
        try:
            for ventana in (None, (None, None), ("2025-12-31", None),
                            (None, "2025-12-31")):
                self.assertIsNone(
                    builder._pct_comp_en_pesos(conn, 26.82, ventana), str(ventana))
            self.assertIsNone(
                builder._pct_comp_en_pesos(conn, None, ("2024-12-31", "2025-12-31")))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
