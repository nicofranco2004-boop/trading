"""El veredicto anual — "¿le gané al mercado en 2025?" — y la ventana en la que
se mide.

Hasta ahora `benchmark_return_for_period` contestaba SÓLO para meses: para
cualquier otro período devolvía None (`builder.py`, "Phase 1: no soportamos
benchmark sub-mensual"). Reportes publicaba el rendimiento del año y ninguna
comparación al lado, y el frontend escondía la fila porque el dato llegaba vacío.

Lo que estos tests fijan no es que el número exista, sino CONTRA QUÉ VENTANA se
mide. El TWR de un año cubre lo que el motor pudo medir —"del 3 de marzo al 11 de
septiembre"— y no el año del almanaque. Comparar ese tramo contra el S&P de enero
a diciembre no es una comparación: en un año donde el índice hizo casi todo su
recorrido fuera de la ventana, el veredicto sale INVERTIDO. Y el veredicto es lo
único que el usuario lee de acá.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main  # noqa: E402  (setea DB_PATH antes de importar)
from reporting import builder  # noqa: E402


# ─── Series de benchmark de laboratorio ──────────────────────────────────────
# Valores redondos a propósito: cualquier assert de abajo se puede verificar a
# mano. El S&P DIARIO tiene los puntos justos — `benchmark_recortado` resuelve
# cada fecha con el cierre de ese día o del último hábil anterior, así que no
# hace falta una rueda por día para fijar el criterio.
SP_DIARIO = {
    "2024-12-31": 100.0,
    "2025-03-17": 120.0,
    "2025-09-11": 132.0,
    "2025-12-31": 110.0,   # el índice VUELVE abajo: el año cierra +10%
}
SP_MENSUAL = {
    "2024-12": 100.0,
    "2025-03": 120.0,
    "2025-09": 132.0,
    "2025-11": 132.0,
    "2025-12": 110.0,
}
INFLACION = {f"2025-{m:02d}": 2.0 for m in range(1, 13)}  # 2% por mes


def bench(diario=True, mensual=True, inflacion=True):
    b = {}
    if diario:
        b["sp500_d"] = dict(SP_DIARIO)
    if mensual:
        b["sp500"] = dict(SP_MENSUAL)
    if inflacion:
        b["inflation_ar"] = dict(INFLACION)
    return b


class VentanaTest(unittest.TestCase):
    """`benchmark_entre_fechas` — el primitivo, sin base de datos."""

    def test_el_ano_entero_mide_el_ano_entero(self):
        r = builder.benchmark_entre_fechas(bench(), "2024-12-31", "2025-12-31", "sp500")
        self.assertAlmostEqual(r, 10.0, places=6)

    def test_la_ventana_manda_sobre_el_almanaque(self):
        """EL CASO QUE JUSTIFICA TODO ESTE TRABAJO.

        El índice cerró el año en +10%, pero entre marzo y septiembre hizo +10%
        sobre un nivel ya alto: 120 → 132. Un usuario que sólo pudo medirse en ese
        tramo tiene que compararse contra ESE tramo. Si se lo compara contra el
        +10% del año calendario, el número coincide por casualidad; lo que no
        coincide es el veredicto de cualquier otro tramo — por eso abajo se
        verifica también que los dos recortes NO son intercambiables.
        """
        ventana = builder.benchmark_entre_fechas(bench(), "2025-03-17", "2025-09-11", "sp500")
        self.assertAlmostEqual(ventana, 10.0, places=6)         # 120 → 132
        # Y el tramo que va de marzo a fin de año es MUY otro: −8,33%.
        otro = builder.benchmark_entre_fechas(bench(), "2025-03-17", "2025-12-31", "sp500")
        self.assertAlmostEqual(otro, -8.333333, places=4)
        self.assertNotAlmostEqual(ventana, otro, places=2)

    def test_sin_serie_diaria_la_ventana_pegada_al_borde_de_mes_SI_se_mide(self):
        r = builder.benchmark_entre_fechas(bench(diario=False), "2024-12-31",
                                           "2025-12-31", "sp500")
        self.assertAlmostEqual(r, 10.0, places=6)

    def test_sin_serie_diaria_una_ventana_a_mitad_de_mes_NO_se_publica(self):
        """Un benchmark mensual no sabe de medio marzo. Contarlo entero
        sobreestima al índice (le come mérito al usuario) y saltearlo lo
        subestima (se lo regala): las dos direcciones son sesgo, y ninguna se
        puede declarar. Sin la serie diaria, no hay número."""
        self.assertIsNone(
            builder.benchmark_entre_fechas(bench(diario=False), "2025-03-17",
                                           "2025-09-11", "sp500"))

    def test_el_primer_dia_del_ano_ancla_en_el_cierre_de_diciembre(self):
        """La ventana que arranca el 1 de enero cubre enero entero, así que el
        ancla es el cierre del 31 de diciembre — no el de enero, que se comería
        el primer mes."""
        r = builder.benchmark_entre_fechas(bench(diario=False), "2025-01-01",
                                           "2025-12-31", "sp500")
        self.assertAlmostEqual(r, 10.0, places=6)

    def test_la_inflacion_compone_los_meses_de_la_ventana(self):
        r = builder.benchmark_entre_fechas(bench(), "2024-12-31", "2025-12-31",
                                           "inflation_ar")
        self.assertAlmostEqual(r, (1.02 ** 12 - 1) * 100, places=4)

    def test_en_pesos_el_indice_se_lleva_la_devaluacion(self):
        """Un S&P en dólares comparado contra una cartera medida en pesos le
        esconde la devaluación, que es justo lo que separa las dos monedas."""
        tc = {"2024-12-31": 1000.0, "2025-12-31": 1500.0}
        r = builder.benchmark_entre_fechas(bench(), "2024-12-31", "2025-12-31",
                                           "sp500", fx=lambda d: tc.get(d))
        # 1,10 × 1,50 − 1 = +65%
        self.assertAlmostEqual(r, 65.0, places=6)

    def test_un_indice_que_arranca_despues_NO_publica_cero(self):
        """`benchmark_recortado` ancla en la primera fecha CON cierre. Si la
        historia del índice arranca después que la ventana, el primer punto viene
        vacío y la base se corre al segundo: el retorno saldría 0,0% donde la
        respuesta verdadera es "no sé"."""
        tarde = {"sp500_d": {"2025-06-30": 100.0, "2025-12-31": 110.0}}
        self.assertIsNone(
            builder.benchmark_entre_fechas(tarde, "2024-12-31", "2025-12-31", "sp500"))

    def test_si_la_diaria_no_llega_tan_atras_cae_a_la_MENSUAL(self):
        """La serie diaria se baja con `period="5y"` y la mensual con "max" (llega
        a 1988). Para un año de más de cinco años la diaria no tiene el ancla —
        quedarse ahí devolvía None con el dato mensual disponible al lado. Medido
        contra yfinance real: 2021 y 2020 se quedaban sin veredicto mientras
        2022-2025 lo tenían."""
        b = {
            "sp500_d": {"2025-06-30": 300.0, "2025-12-31": 330.0},   # arranca tarde
            "sp500": dict(SP_MENSUAL),                                # llega al 2024
        }
        r = builder.benchmark_entre_fechas(b, "2024-12-31", "2025-12-31", "sp500")
        self.assertAlmostEqual(r, 10.0, places=6)

    def test_una_ventana_al_reves_no_publica(self):
        """Sin este corte devolvía el retorno del tramo NEGADO: −9,09 % donde el
        índice hizo +10 %. Un veredicto dado vuelta es peor que ninguno."""
        self.assertIsNone(
            builder.benchmark_entre_fechas(bench(), "2025-12-31", "2024-12-31", "sp500"))

    def test_sin_datos_no_inventa(self):
        self.assertIsNone(builder.benchmark_entre_fechas({}, "2024-12-31",
                                                          "2025-12-31", "sp500"))
        self.assertIsNone(builder.benchmark_entre_fechas(bench(), None,
                                                          "2025-12-31", "sp500"))


class _Base(unittest.TestCase):
    """Un usuario con un año entero medido a mercado — el camino de producción."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("bench@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,100,?)",
            (self.uid, "IBKR", "AAPL", "2024-01-01"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def me(self, y, m, ci, cf, dep=0.0, wd=0.0, rz=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,?,?,?,0)", (self.uid, y, m, ci, cf, dep, wd, rz))
        self.conn.commit()

    def snap(self, d, v, source="cron"):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,?,?,?)",
            (self.uid, d, v, v, source, 1200.0, "[]"))
        self.conn.commit()

    def metrics(self, ptype, start, end, moneda="usd", b=None, live=None):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, ptype, start, end, "global",
            bench() if b is None else b, live_value=live, moneda=moneda)
        return m

    def ano_medido(self):
        """Cadencia real del cron: un cierre por mes. El motor encadena y la
        ventana que declara va del 31/12 anterior al 31/12."""
        import calendar as _c
        valor = 100000.0
        self.snap("2024-12-31", valor)
        for mes in range(1, 13):
            valor *= 1.02
            self.snap(f"2025-{mes:02d}-{_c.monthrange(2025, mes)[1]:02d}", round(valor, 2))
        for mes in range(1, 13):
            self.me(2025, mes, 100000.0, 100000.0)


class AnualIntegracionTest(_Base):

    def test_el_ano_publica_el_sp_de_SU_ventana(self):
        self.ano_medido()
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertEqual((m.medido_desde, m.medido_hasta), ("2024-12-31", "2025-12-31"))
        # El benchmark declara la MISMA ventana que el número.
        self.assertEqual((m.bench_desde, m.bench_hasta), ("2024-12-31", "2025-12-31"))
        self.assertIsNotNone(m.delta_pct)
        # El S&P de esa ventana exacta, no el del almanaque.
        self.assertAlmostEqual(m.sp500_return_pct, 10.0, places=2)
        self.assertAlmostEqual(m.vs_sp500_pct, round(m.delta_pct - 10.0, 2), places=2)

    def test_en_dolares_NO_se_compara_contra_la_inflacion_argentina(self):
        """La inflación es un fenómeno del PESO. Restarle un retorno medido en
        dólares no da un veredicto, da una mezcla de unidades: en 2024 daría
        "96 puntos abajo" de algo contra lo que la cartera nunca jugó."""
        self.ano_medido()
        m = self.metrics("year", "2025-01-01", "2025-12-31", moneda="usd")
        self.assertIsNone(m.inflation_pct)
        self.assertIsNone(m.vs_inflation_pct)

    def test_en_pesos_SI(self):
        self.ano_medido()
        m = self.metrics("year", "2025-01-01", "2025-12-31", moneda="ars")
        self.assertIsNotNone(m.inflation_pct)
        self.assertAlmostEqual(m.inflation_pct, (1.02 ** 12 - 1) * 100, places=1)

    def test_sin_ventana_declarada_NO_hay_veredicto(self):
        """La contabilidad con agujeros no compone y el motor no publica: queda
        el Dietz punta a punta, que no sabe qué tramo cubre. Un veredicto ahí
        sería contra una ventana inventada."""
        self.me(2025, 1, 100000.0, 101200.0, rz=1200.0)
        self.me(2025, 6, 101200.0, 102400.0, rz=1200.0)   # faltan feb-may
        self.me(2025, 12, 102400.0, 103600.0, rz=1200.0)
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertIsNotNone(m.delta_pct)          # el % sí se publica
        self.assertIsNone(m.sp500_return_pct)      # el veredicto NO
        self.assertIsNone(m.vs_sp500_pct)

    def test_el_ano_contable_COMPLETO_si_tiene_veredicto(self):
        """Sin mediciones pero con los doce meses seguidos, la composición cubre
        el año y su ventana es declarable: ahí el veredicto se publica."""
        ci = 100000.0
        for mes in range(1, 13):
            cf = ci * 1.01
            self.me(2025, mes, round(ci, 2), round(cf, 2), rz=round(cf - ci, 2))
            ci = cf
        m = self.metrics("year", "2025-01-01", "2025-12-31")
        self.assertIsNotNone(m.delta_pct)
        self.assertAlmostEqual(m.sp500_return_pct, 10.0, places=2)

    def test_el_ano_EN_CURSO_compara_hasta_HOY(self):
        """El % del año en curso llega hasta HOY (su último mes cierra con el valor
        vivo), así que el índice también. El índice de este test está PLANO hasta el
        fin del mes pasado y salta al doble después: si la ventana se cortara ahí,
        daría 0%.

        ⚠️ ALCANCE HONESTO DE ESTE TEST. Fija que la ventana declarada llega a hoy
        y que el índice la respeta. NO discrimina de cuál de las dos fuentes salió
        —la composición contable y las puntas dan la MISMA ventana en el año en
        curso, porque la composición tiene que cubrir desde enero y el borde medido
        está pegado al 1/1—. Se intentó separarlas y no se pudo construir el caso;
        queda anotado en vez de fingir que el test lo cubre."""
        import datetime
        hoy = builder._hoy_iso()
        y, mes_actual = int(hoy[:4]), int(hoy[5:7])
        if mes_actual < 3:
            self.skipTest("hacen falta al menos dos meses cerrados en el año")
        ci = 10000.0
        # El cierre del 31/12 anterior, medido: sin él el año en curso queda
        # "base incomparable" y no publica ningún %.
        self.snap(f"{y - 1}-12-31", ci)
        for m in range(1, mes_actual):          # sin fila del mes en curso
            cf = ci * 1.01
            self.me(y, m, round(ci, 2), round(cf, 2), rz=round(cf - ci, 2))
            ci = cf
        corte = datetime.date(y, mes_actual, 1) - datetime.timedelta(days=1)
        sp, d = {}, datetime.date(y - 1, 12, 1)
        while d <= datetime.date(y, 12, 31):
            sp[d.isoformat()] = 100.0 if d <= corte else 200.0
            d += datetime.timedelta(days=1)
        m = self.metrics("year", f"{y}-01-01", f"{y}-12-31",
                         b={"sp500_d": sp, "sp500": {}, "inflation_ar": {}},
                         live=round(ci, 2))
        self.assertIsNotNone(m.delta_pct)
        # La ventana declarada tiene que llegar a hoy — y el índice medirlo.
        self.assertEqual(m.bench_hasta, hoy)
        self.assertAlmostEqual(m.sp500_return_pct, 100.0, places=1)

    def test_el_mes_sigue_midiendo_como_siempre(self):
        """Regresión: el mensual es un número publicado hace meses. Este trabajo
        no lo toca — ni el S&P (cierre de mes contra cierre de mes anterior) ni la
        inflación, que en el mes se sigue publicando también en dólares."""
        self.ano_medido()
        m = self.metrics("month", "2025-12-01", "2025-12-31")
        # El camino del mes es el de siempre: cierre de noviembre (132) contra
        # cierre de diciembre (110) = −16,67%. Sin arrastre — si al mes anterior
        # le falta el cierre, el mes no publica, y eso tampoco se tocó.
        self.assertAlmostEqual(m.sp500_return_pct, -16.67, places=2)
        self.assertIsNotNone(m.inflation_pct)


if __name__ == "__main__":
    unittest.main()


class EndpointAniosTest(_Base):
    """`/api/reports/years` — el contrato que consume la pantalla.

    Los tests de arriba cubren el motor; este cubre la ruta, que es lo que se
    rompe cuando alguien cambia un nombre de campo y la pantalla se queda muda.
    """

    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)
        # Sin red en los tests: el caché de benchmarks se llena a mano con las
        # mismas series de laboratorio que usa el resto del archivo.
        self._bench_previo = main._bench_cache["data"]
        main._bench_cache["data"] = {
            "sp500": dict(SP_MENSUAL), "sp500_d": dict(SP_DIARIO),
            "inflation_ar": dict(INFLACION),
        }
        # Con plan: los años anteriores son de pago y el usuario de laboratorio
        # nace sin tier (= free). El corte en sí lo cubre `PlanDeLosAniosTest`.
        self.conn.execute("UPDATE users SET tier='pro' WHERE id=?", (self.uid,))
        self.conn.commit()

    def tearDown(self):
        main._bench_cache["data"] = self._bench_previo
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        super().tearDown()

    def test_lista_los_anios_con_historia_del_mas_nuevo_al_mas_viejo(self):
        self.ano_medido()
        r = self.client.get("/api/reports/years?modo=certero&moneda=usd")
        self.assertEqual(r.status_code, 200)
        anios = [a["year"] for a in r.json()["years"]]
        self.assertEqual(anios, sorted(anios, reverse=True))
        self.assertIn(2025, anios)

    def test_cada_anio_trae_los_campos_que_la_pantalla_lee(self):
        self.ano_medido()
        fila = next(a for a in self.client.get(
            "/api/reports/years?modo=certero&moneda=usd").json()["years"] if a["year"] == 2025)
        for campo in ("pct", "usd", "basis", "medido_desde", "medido_hasta",
                      "bench_desde", "bench_hasta", "sp500_return_pct", "vs_sp500_pct",
                      "inflation_pct", "vs_inflation_pct", "deposits", "withdrawals",
                      "realized_pnl", "trades_count", "win_rate", "is_current", "motivo"):
            self.assertIn(campo, fila, f"falta `{campo}` — la pantalla lo lee")
        self.assertAlmostEqual(fila["sp500_return_pct"], 10.0, places=2)

    def test_el_anio_en_curso_viene_marcado(self):
        """La pantalla NO deduce el año actual con `new Date()`: el "hoy" de Rendi
        es el día ARGENTINO y vive en el backend. Si este flag falta, el inicio
        muestra el año equivocado los días en que las dos fechas no coinciden."""
        self.ano_medido()
        años = self.client.get("/api/reports/years?modo=certero&moneda=usd").json()["years"]
        actuales = [a for a in años if a["is_current"]]
        self.assertEqual(len(actuales), 1)
        self.assertEqual(actuales[0]["year"], int(builder._hoy_iso()[:4]))

    def test_una_cuenta_vacia_devuelve_lista_vacia_sin_romperse(self):
        r = self.client.get("/api/reports/years?modo=certero&moneda=usd")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["years"], [])

    def test_en_pesos_aparece_la_inflacion_y_en_dolares_no(self):
        self.ano_medido()
        def infl(moneda):
            fila = next(a for a in self.client.get(
                f"/api/reports/years?modo=certero&moneda={moneda}").json()["years"]
                if a["year"] == 2025)
            return fila["inflation_pct"]
        self.assertIsNone(infl("usd"))
        self.assertIsNotNone(infl("ars"))


class CacheDeBenchmarksTest(unittest.TestCase):
    """`_bench_para_reportes` — el dict que Reportes y el inicio le pasan al builder."""

    def setUp(self):
        self._previo = main._bench_cache["data"]

    def tearDown(self):
        main._bench_cache["data"] = self._previo

    def test_usa_el_cache_y_no_baja_de_nuevo(self):
        """LEÍA el caché sin llenarlo nunca: con el caché frío —el estado normal
        hasta que alguien abre Métricas— cada visita a Reportes y al Dashboard
        volvía a bajar las tres series de yfinance (medido: 0,77 s CADA vez)."""
        main._bench_cache["data"] = None
        llamadas = {"n": 0}
        real = main._fetch_sp500_monthly

        def contando():
            llamadas["n"] += 1
            return {"2025-12": 100.0}
        main._fetch_sp500_monthly = contando
        try:
            main._bench_para_reportes()
            main._bench_para_reportes()
            main._bench_para_reportes()
        finally:
            main._fetch_sp500_monthly = real
        self.assertEqual(llamadas["n"], 1, "bajó el S&P una vez por llamada")

    def test_no_pisa_las_otras_series_del_cache(self):
        """El caché tiene más series (blue, merval, oro, UVA) que
        `/api/insights/performance` lee de ahí: reemplazarlo con estas tres se las
        borraría, y esa pantalla se quedaría sin sus benchmarks."""
        main._bench_cache["data"] = {"merval": {"2025-12": 1.0}, "uva": {"2025-12": 2.0},
                                     "sp500": {"2025-12": 100.0}, "sp500_d": {"2025-12-31": 100.0},
                                     "inflation_ar": {"2025-12": 2.0}}
        main._bench_para_reportes()
        self.assertIn("merval", main._bench_cache["data"])
        self.assertIn("uva", main._bench_cache["data"])

    def test_el_ts_del_cache_no_se_toca(self):
        """Este caché queda INCOMPLETO (sólo tres series), así que el refresco en
        background de `/api/benchmarks` tiene que seguir viéndolo como viejo."""
        main._bench_cache["data"] = None
        ts_previo = main._bench_cache["ts"]
        main._bench_para_reportes()
        self.assertEqual(main._bench_cache["ts"], ts_previo)


class PlanDeLosAniosTest(_Base):
    """Los años anteriores son de plan pago; el año EN CURSO es gratis.

    El calendario de Reportes siempre estuvo fuera del muro, así que colgarle el
    cierre de cada año y sus veredictos los dejaba visibles en Free sin que nadie
    lo decidiera. El corte va en el SERVIDOR: un gate que vive sólo en la pantalla
    es una cortina, no una puerta.
    """

    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)
        self._bench_previo = main._bench_cache["data"]
        main._bench_cache["data"] = {"sp500": dict(SP_MENSUAL), "sp500_d": dict(SP_DIARIO),
                                     "inflation_ar": dict(INFLACION)}
        self.ano_medido()

    def tearDown(self):
        main._bench_cache["data"] = self._bench_previo
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        super().tearDown()

    def _tier(self, tier):
        self.conn.execute("UPDATE users SET tier=? WHERE id=?", (tier, self.uid))
        self.conn.commit()

    def _pedir(self):
        return self.client.get("/api/reports/years?modo=certero&moneda=usd").json()

    def test_free_ve_solo_el_anio_en_curso(self):
        self._tier("free")
        d = self._pedir()
        self.assertFalse(d["historicos"])
        self.assertEqual([a["year"] for a in d["years"]], [int(builder._hoy_iso()[:4])])

    def test_pro_ve_todos(self):
        self._tier("pro")
        d = self._pedir()
        self.assertTrue(d["historicos"])
        self.assertIn(2025, [a["year"] for a in d["years"]])

    def test_free_igual_recibe_el_flag_para_poder_explicarlo(self):
        """Sin el flag la pantalla no puede distinguir "no tenés plan" de "no hay
        datos", y terminaría diciéndole al usuario que le faltan mediciones cuando
        lo que le falta es el plan — la peor de las dos mentiras posibles."""
        self._tier("free")
        self.assertIn("historicos", self._pedir())
