"""La tarjeta del año dice "vs el S&P" Y "vs la inflación", medidos en el mismo
tramo y con el número del modo que se está mirando.

EL REPORTE
──────────
El inicio decía "Este año · desde el 31 de enero · +13,0 % · vs el S&P 500
+1,5 pp" y nada sobre la inflación. El usuario la fue a buscar a "¿Le ganás a las
alternativas?" (Métricas), que mide TODA su historia, encontró "Inflación: le
perdés −6,4 %" y lo leyó como un error: ¿cómo le gano al S&P y le pierdo a la
inflación?

EL MECANISMO
────────────
Cuando el año entero no se puede medir, `/api/reports/years` publica el tramo que
sí (`parcial_*`). Ese tramo se armaba en el endpoint, aparte de
`compute_metrics_for_period`, y copió sólo el veredicto contra el S&P: la cuenta de
la inflación vivía escrita adentro del builder y nunca le llegó. La pantalla, sin
el dato, lo escondía (`vsInfl = parcial ? null : ...`).

Ese tramo además salía de una SEGUNDA curva del motor, pedida aparte: sin el
valor de hoy, sin mirar el broker y arrancando el 1/1 (sin el cierre del 31/12).
Y en ESTIMADO el año en curso no se publicaba nunca entero: el motor cierra la
ventana en "hoy" y `_ventana_cubre` no lo leía como fecha. Con la historia completa
el inicio decía "desde el 31 de enero", con enero afuera del número.

EL ARREGLO
──────────
`builder.veredicto_inflacion` es la única cuenta de la tarjeta, y la piden el año,
el mes y el tramo — los tres dentro de `compute_metrics_for_period`, y el tramo sale
de la MISMA curva que el año. El rendimiento que entra es el que la tarjeta
publica, ya medido con el modo elegido: el veredicto no puede salir de otro número
que el que tiene al lado. El dólar se toma en las puntas del número, así que el
veredicto es el mismo en dólares y en pesos.

Los tests atraviesan el camino de producción: el endpoint (o
`compute_metrics_for_period` para el año entero), sobre una base con fotos,
contabilidad y dólar por día.
"""
import calendar
import datetime as _d
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main  # noqa: E402
import twr  # noqa: E402
from reporting import builder  # noqa: E402


def _fx(dia):
    """El dólar del fixture: sube 0,5 % por mes, plano dentro del mes."""
    return 1400.0 * (1.005 ** ((dia.year - 2020) * 12 + dia.month))


class _Base(unittest.TestCase):

    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users",
                  "fx_rates_daily"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'pro')",
            (f"infl-anio-{id(self)}@t", "x")).lastrowid
        self._bench_antes = main._bench_cache.get("data")

    def tearDown(self):
        main._bench_cache["data"] = self._bench_antes
        self.conn.close()

    def dolar_por_dia(self, desde, hasta, fx=_fx):
        dia = desde
        while dia <= hasta:
            v = fx(dia)
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, blue_compra, "
                "mep_compra, source) VALUES (?,?,?,?,?,'test')",
                (dia.isoformat(), v, v, v, v))
            dia += _d.timedelta(days=1)

    def sp_diario(self, desde, hasta):
        sp, dia = {}, desde
        while dia <= hasta:
            sp[dia.isoformat()] = 100.0 * (1.0002 ** (dia - desde).days)
            dia += _d.timedelta(days=1)
        return sp

    def anio_en_curso(self, dia_inicio_cron=1, cierre_de_diciembre=False):
        """El año en curso, con la forma de la cuenta del reporte.

        · Contabilidad importada: una foto AL COSTO a fin de cada mes cerrado (lo
          que lee el ESTIMADO). Con `cierre_de_diciembre`, también la del 31/12
          anterior: la historia cubre el año entero.
        · Fotos del cron a precio de mercado (lo que lee el CERTERO), desde el día
          `dia_inicio_cron` de hace dos meses.
        Las fotos no declaran plata aportada: no hay depósitos cargados, y el cierre
        con el valor de hoy pregunta los aportes reales."""
        self.hoy = _d.date.fromisoformat(builder._hoy_iso())
        Y, M = self.hoy.year, self.hoy.month
        if M < 4:
            self.skipTest("hacen falta al menos tres meses cerrados en el año")
        self.dolar_por_dia(_d.date(Y - 1, 12, 1), self.hoy)
        sp_d = self.sp_diario(_d.date(Y - 1, 12, 1), self.hoy)
        main._bench_cache["data"] = {
            # El INDEC publica con atraso: el mes en curso no tiene IPC.
            "inflation_ar": {f"{Y}-{m:02d}": 2.0 for m in range(1, M)},
            "sp500_d": sp_d,
            "sp500": {k[:7]: v for k, v in sorted(sp_d.items())},
        }
        cap = 10000.0
        fotos = [(f"{Y - 1}-12-31", cap)] if cierre_de_diciembre else []
        for m in range(1, M):
            cap *= 1.02
            fotos.append((f"{Y}-{m:02d}-{calendar.monthrange(Y, m)[1]:02d}", cap))
        for fecha, valor in fotos:
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                "net_deposited, source) VALUES (?,?,?,10000,0,'import')",
                (self.uid, fecha, valor))
        self.inicio_cron = _d.date(Y, M - 2, dia_inicio_cron)
        v, dia = 12000.0, self.inicio_cron
        while dia <= self.hoy:
            self.conn.execute(
                "INSERT OR IGNORE INTO snapshots (user_id, date, total_value, "
                "total_invested, net_deposited, source, fx_to_usd_blue, holdings_json, "
                "base, apto) VALUES (?,?,?,10000,0,'cron',1200,'[]','mercado',1)",
                (self.uid, dia.isoformat(), round(v, 2)))
            v *= 1.0005
            dia += _d.timedelta(days=1)
        twr.estampar_base(self.conn)
        self.conn.commit()

    def anio(self, modo, moneda, broker="global"):
        r = main.reports_years(broker=broker, modo=modo, moneda=moneda, uid=self.uid)
        return next(a for a in r["years"] if a["is_current"])


class ElTramoParcialTraeLosDosVeredictosTest(_Base):
    """El caso del reporte: el año en curso no se puede medir entero.

    · ESTIMADO: la contabilidad arranca con la foto del 31 de enero → tramo
      "desde el 31 de enero".
    · CERTERO: sólo las fotos a mercado del cron, desde el día 1 de hace dos
      meses → otro tramo, otro número.
    """

    def setUp(self):
        super().setUp()
        self.anio_en_curso()

    def inflacion_esperada(self, desde_iso):
        """2 % por cada mes con IPC publicado DESPUÉS del mes base. Arrancar el
        último día de un mes cuenta desde el siguiente; arrancar el día 1, desde
        ese mismo mes (la ventana lo cubre entero)."""
        d = _d.date.fromisoformat(desde_iso)
        primero = d.month + 1 if d.day == calendar.monthrange(d.year, d.month)[1] else d.month
        return (1.02 ** (self.hoy.month - primero) - 1) * 100

    def test_el_tramo_publica_el_veredicto_contra_la_inflacion(self):
        """Antes: `parcial_vs_sp500_pct` sí, `parcial_vs_inflation_pct` no existía."""
        for modo in twr.MODOS:
            for moneda in ("usd", "ars"):
                with self.subTest(modo=modo, moneda=moneda):
                    f = self.anio(modo, moneda)
                    self.assertIsNone(f["pct"], "el escenario es el del tramo parcial")
                    self.assertIsNotNone(f["parcial_pct"])
                    self.assertIsNotNone(f["parcial_vs_sp500_pct"])
                    self.assertIsNotNone(f["parcial_vs_inflation_pct"])
                    self.assertIsNone(f["parcial_vs_inflation_motivo"])

    def test_la_inflacion_es_la_del_tramo_y_no_la_del_anio(self):
        for modo in twr.MODOS:
            with self.subTest(modo=modo):
                f = self.anio(modo, "usd")
                self.assertAlmostEqual(f["parcial_inflation_pct"],
                                       self.inflacion_esperada(f["parcial_desde"]), places=1)

    def test_en_dolares_el_retorno_se_pasa_a_pesos_con_el_dolar_de_las_puntas_del_tramo(self):
        for modo in twr.MODOS:
            with self.subTest(modo=modo):
                f = self.anio(modo, "usd")
                d0 = _d.date.fromisoformat(f["parcial_desde"])
                d1 = _d.date.fromisoformat(f["parcial_hasta"])
                esperado = ((1 + f["parcial_pct"] / 100) * _fx(d1) / _fx(d0) - 1) * 100
                self.assertAlmostEqual(f["parcial_retorno_ars_pct"], esperado, places=1)

    def test_el_veredicto_no_cambia_con_el_selector_de_moneda(self):
        """La misma cartera, el mismo tramo: "le ganás a la inflación por X" no puede
        depender de si mirás en dólares o en pesos. (Tomar el dólar en el cierre
        del mes base de la inflación, y no en la punta del número, daba +2,1 en
        dólares y +1,56 en pesos para el tramo del certero.)"""
        for modo in twr.MODOS:
            with self.subTest(modo=modo):
                usd, ars = self.anio(modo, "usd"), self.anio(modo, "ars")
                self.assertEqual(usd["parcial_desde"], ars["parcial_desde"])
                self.assertAlmostEqual(usd["parcial_vs_inflation_pct"],
                                       ars["parcial_vs_inflation_pct"], delta=0.05)

    def test_en_pesos_el_retorno_no_se_vuelve_a_convertir(self):
        for modo in twr.MODOS:
            with self.subTest(modo=modo):
                f = self.anio(modo, "ars")
                self.assertAlmostEqual(f["parcial_retorno_ars_pct"], f["parcial_pct"], places=2)

    def test_la_resta_que_ve_el_usuario_da_el_veredicto(self):
        """Lo que el globo muestra (tu cartera en pesos, la inflación) y el
        veredicto salen de la MISMA resta."""
        for modo in twr.MODOS:
            for moneda in ("usd", "ars"):
                with self.subTest(modo=modo, moneda=moneda):
                    f = self.anio(modo, moneda)
                    self.assertAlmostEqual(
                        f["parcial_vs_inflation_pct"],
                        f["parcial_retorno_ars_pct"] - f["parcial_inflation_pct"], delta=0.011)

    def test_cada_modo_compara_SU_rendimiento(self):
        """Certero y estimado miden tramos distintos con números distintos, y cada
        veredicto sale del número de su modo — no del otro."""
        cert, est = self.anio("certero", "usd"), self.anio("estimado", "usd")
        self.assertEqual(est["parcial_desde"], f"{self.hoy.year}-01-31")
        self.assertEqual(cert["parcial_desde"], self.inicio_cron.isoformat())
        self.assertNotAlmostEqual(cert["parcial_pct"], est["parcial_pct"], places=1)
        self.assertNotAlmostEqual(cert["parcial_vs_inflation_pct"],
                                  est["parcial_vs_inflation_pct"], places=1)

    def test_el_tramo_es_el_de_la_curva_del_anio_y_termina_hoy(self):
        """Una sola curva para el año y su tramo: termina HOY (con el valor vivo),
        y nunca en la palabra "hoy", que la pantalla no puede leer como fecha."""
        for modo in twr.MODOS:
            with self.subTest(modo=modo):
                self.assertEqual(self.anio(modo, "usd")["parcial_hasta"], self.hoy.isoformat())

    def test_sin_modo_en_el_pedido_usa_el_que_eligio_el_usuario(self):
        """El inicio del celular monta la tarjeta sin `modo`."""
        for modo in twr.MODOS:
            with self.subTest(modo=modo):
                self.conn.execute("UPDATE users SET modo_rendimiento=? WHERE id=?",
                                  (modo, self.uid))
                self.conn.commit()
                pedido = self.anio(modo, "usd")
                guardado = self.anio(None, "usd")
                self.assertEqual(guardado["parcial_pct"], pedido["parcial_pct"])
                self.assertEqual(guardado["parcial_vs_inflation_pct"],
                                 pedido["parcial_vs_inflation_pct"])

    def test_las_claves_del_tramo_viajan_siempre(self):
        f = self.anio("certero", "usd")
        for clave in builder.CAMPOS_TRAMO_PARCIAL:
            self.assertIn(clave, f)

    def test_si_falla_el_veredicto_el_numero_del_tramo_queda(self):
        """Antes un solo try envolvía el tramo entero: si la comparación fallaba,
        se perdía también el número, y la tarjeta volvía a "todavía sin dos
        mediciones" — el defecto que el tramo vino a cerrar."""
        from unittest import mock
        original = builder.veredicto_inflacion

        def rompe_en_el_tramo(conn, bench, retorno_pct, **kw):
            if retorno_pct is not None:          # sólo el del tramo trae número
                raise RuntimeError("serie de inflación rota")
            return original(conn, bench, retorno_pct, **kw)

        with mock.patch.object(builder, "veredicto_inflacion", side_effect=rompe_en_el_tramo):
            f = self.anio("estimado", "usd")
        self.assertIsNotNone(f["parcial_pct"])
        self.assertIsNotNone(f["parcial_vs_sp500_pct"])
        self.assertIsNone(f["parcial_vs_inflation_pct"])


class ElTramoEsDeLaCarteraEnteraTest(_Base):
    """El motor mide la cartera ENTERA. Reportes filtrado por un broker mostraba el
    tramo de toda la cartera como si fuera de ese broker (lo pedía una segunda
    curva sin broker)."""

    def setUp(self):
        super().setUp()
        self.anio_en_curso()
        # Un broker cuyo año no se puede medir (sin capital ni flujos): es el caso
        # en que la pantalla busca el tramo.
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'IOL',?,1,0,0,0,0,0,0)", (self.uid, self.hoy.year))
        self.conn.commit()

    def test_filtrado_por_broker_no_hay_tramo(self):
        self.assertIsNotNone(self.anio("certero", "usd")["parcial_pct"])
        f = self.anio("certero", "usd", broker="IOL")
        self.assertIsNone(f["pct"], "el escenario es el del año de IOL sin medir")
        self.assertIsNone(f["parcial_pct"])
        self.assertIsNone(f["parcial_vs_inflation_pct"])


class ElTramoQueArrancaAMitadDeMesTest(_Base):
    """El IPC es mensual: con el tramo arrancando el 17, compararlo inventaría
    medio mes, y no se publica. Pero tampoco se calla — viaja el motivo, para que
    la pantalla no muestre "vs el S&P" solo (lo que se leyó como un error)."""

    def setUp(self):
        super().setUp()
        self.anio_en_curso(dia_inicio_cron=17)

    def test_sin_veredicto_pero_con_el_motivo(self):
        f = self.anio("certero", "usd")
        self.assertEqual(f["parcial_desde"], self.inicio_cron.isoformat())
        self.assertIsNotNone(f["parcial_vs_sp500_pct"], "el S&P es diario: ése sí se mide")
        self.assertIsNone(f["parcial_vs_inflation_pct"])
        self.assertIn("arranca el 17 de", f["parcial_vs_inflation_motivo"])


class ElEstimadoConLaHistoriaCompletaPublicaElAnioTest(_Base):
    """Con la contabilidad desde el 31/12, el ESTIMADO cubre el año entero. Pero el
    motor cierra su ventana en "hoy" y `_ventana_cubre` no lo leía: el año no se
    publicaba nunca y caía a un tramo que arrancaba el 31 de ENERO — enero afuera
    del número. Era la tarjeta del reporte: "Este año · desde el 31 de enero"."""

    def setUp(self):
        super().setUp()
        self.anio_en_curso(cierre_de_diciembre=True)

    def test_el_anio_entero_con_sus_dos_veredictos(self):
        for moneda in ("usd", "ars"):
            with self.subTest(moneda=moneda):
                f = self.anio("estimado", moneda)
                self.assertIsNotNone(f["pct"], "el año entero se publica")
                self.assertIsNone(f["parcial_pct"])
                self.assertEqual(f["bench_desde"], f"{self.hoy.year - 1}-12-31")
                self.assertEqual(f["bench_hasta"], self.hoy.isoformat())
                self.assertIsNotNone(f["vs_sp500_pct"])
                self.assertIsNotNone(f["vs_inflation_pct"])

    def test_enero_esta_adentro_del_numero(self):
        """Doce meses de contabilidad al 2 %: sin enero, el número es un mes más
        chico."""
        f = self.anio("estimado", "usd")
        con_enero = (1.02 ** (self.hoy.month - 1) - 1) * 100
        self.assertGreater(f["pct"], con_enero - 0.5)


class ElAnioEnteroConvierteConElDolarDeSuVentanaTest(_Base):
    """La ventana medida del año arranca el 2/1 y el dólar saltó 10 % entre el 31/12
    y el 2/1 —antes de que el número empezara a medir—. Adentro de la ventana el
    dólar no se movió: en pesos, el rendimiento es el mismo que en dólares, y el
    veredicto el mismo con los dos selectores.

    Antes se convertía con el dólar del 31/12 del almanaque: en dólares el
    rendimiento en pesos llevaba un 10 % que en pesos no estaba."""

    def setUp(self):
        super().setUp()
        self.dolar_por_dia(_d.date(2024, 12, 1), _d.date(2025, 12, 31),
                           fx=lambda dia: 1000.0 if dia <= _d.date(2025, 1, 1) else 1100.0)
        valor = 100000.0
        self.snap("2025-01-02", valor)
        for mes in range(1, 13):
            valor *= 1.02
            self.snap(f"2025-{mes:02d}-{calendar.monthrange(2025, mes)[1]:02d}", round(valor, 2))
            self.conn.execute(
                "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
                "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
                "VALUES (?,'global',2025,?,100000,100000,0,0,0,0)", (self.uid, mes))
        self.conn.commit()
        self.bench = {"inflation_ar": {f"2025-{m:02d}": 2.0 for m in range(1, 13)},
                      "sp500_d": self.sp_diario(_d.date(2024, 12, 1), _d.date(2025, 12, 31))}

    def snap(self, d, v):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,'cron',1200,'[]')", (self.uid, d, v, v))

    def metrics(self, moneda):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "year", "2025-01-01", "2025-12-31", "global",
            self.bench, moneda=moneda)
        return m

    def test_el_retorno_en_pesos_usa_las_puntas_de_la_ventana(self):
        m = self.metrics("usd")
        self.assertEqual(m.bench_desde, "2025-01-02", "el escenario es el de la ventana corrida")
        self.assertIsNotNone(m.delta_pct)
        self.assertIsNotNone(m.vs_inflation_pct)
        # Dentro de la ventana el dólar está quieto: en pesos rinde lo mismo.
        # Con las puntas del almanaque daba delta·1,10 + 10 puntos.
        self.assertAlmostEqual(m.retorno_ars_pct, m.delta_pct, places=2)
        self.assertAlmostEqual(m.vs_inflation_pct, m.retorno_ars_pct - m.inflation_pct,
                               delta=0.011)

    def test_el_veredicto_es_el_mismo_en_dolares_y_en_pesos(self):
        usd, ars = self.metrics("usd"), self.metrics("ars")
        self.assertIsNotNone(ars.vs_inflation_pct)
        self.assertAlmostEqual(usd.vs_inflation_pct, ars.vs_inflation_pct, delta=0.05)


if __name__ == "__main__":
    unittest.main()
