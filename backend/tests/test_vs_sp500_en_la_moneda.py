"""F6 — el S&P se compara EN LA MONEDA EN QUE SE MIDE LA CARTERA.

EL BUG
──────
`benchmark_return_for_period` devuelve números en MONEDAS DISTINTAS según la
`key` —el S&P en dólares, la inflación del INDEC en pesos— y no lo declara en
ninguna parte. `delta_pct`, en cambio, sigue el selector de moneda (`:1544` lo
pisa con `_pct_puntas_ars`).

O sea que SIEMPRE había exactamente una de las dos patas cruzada, y cuál era
dependía del selector. F5 arregló la pata de la inflación —la que se cruza con el
selector en dólares— y dejó la del S&P, que se cruza con el selector en pesos, a
treinta líneas de distancia en el mismo `return`.

MEDIDO con este fixture (cartera 100 % en dólares y PLANA, 20 % de devaluación en
el mes, S&P +2 %), pasando por `compute_metrics_for_period`:

    selector        delta_pct   S&P publicado   vs S&P 500     veredicto
    ───────────────────────────────────────────────────────────────────────
    Dólares            0,0 %        +2,0 %        −2,0 pp      te ganó   ✅
    Pesos, ANTES      20,0 %        +2,0 %       **+18,0 pp**  LE GANASTE ❌
    Pesos, AHORA      20,0 %       +22,4 %        −2,4 pp      te ganó   ✅

Los 20 puntos que el usuario "le ganaba" al S&P eran la devaluación, que su
cartera en dólares nunca ganó. El veredicto se daba vuelta con sólo tocar el
selector, sobre la misma cartera y el mismo mes.

LA REGLA, y de dónde sale: el S&P es un índice de PRECIO, y "el S&P en pesos"
existe —es lo que valdría en pesos la misma plata puesta en el índice—, así que
se mueve el ÍNDICE a la moneda de la cartera. Con la inflación es al revés (una
tasa en pesos no tiene versión en dólares) y por eso tiene su propia función,
`twr.vs_inflacion_ar`. Quién está en qué moneda lo decide `performance.BENCH_EN_ARS`,
la misma tabla que ya usaba el motor del gráfico (`performance`, :238) — no hay
una segunda lista.

CUÁLES MIDEN DE VERDAD
──────────────────────
Contra el código viejo, los de `LaReglaTest` fallan con ImportError porque
`performance.retorno_bench_en_moneda` todavía no existe: eso prueba que la
función es nueva, NO que el número estaba mal.

Los que MIDEN son los de `ReportesLoUsaTest`, que atraviesan
`compute_metrics_for_period` —el mismo camino que producción— y fallan así:

    test_en_pesos_el_sp_tambien_va_en_pesos    →  2.0 != 22.4
    test_el_veredicto_no_depende_del_selector  →  True != False  (el signo)
    test_sin_serie_de_dolar_no_publica_el_vs   →  18.0 is not None

⚠️ Para verificarlo hay que revertir SÓLO el código, dejando este archivo:
   git checkout <commit-anterior> -- backend/performance.py backend/reporting/builder.py
   Revertir el commit entero se lleva el test y no prueba nada.

Corre con: cd backend && python3 -m pytest tests/test_vs_sp500_en_la_moneda.py
"""
import unittest
import uuid

import main
import performance
import twr
from reporting import builder


class LaReglaTest(unittest.TestCase):
    """`performance.retorno_bench_en_moneda` — la aritmética, sin base de datos.

    NO MIDE EL BUG (la función es nueva). Mide que la regla sea la correcta.
    """

    def test_el_sp_con_el_selector_en_pesos_se_convierte(self):
        """EL CASO. +2 % en dólares con 20 % de devaluación es +22,4 % en pesos."""
        r = performance.retorno_bench_en_moneda(
            2.0, "sp500", moneda=twr.MONEDA_ARS, fx0=1000, fx1=1200)
        self.assertAlmostEqual(r, 22.4, places=6)

    def test_compone_no_suma(self):
        """22,4 y no 22: la devaluación multiplica, no se suma."""
        r = performance.retorno_bench_en_moneda(
            2.0, "sp500", moneda=twr.MONEDA_ARS, fx0=1000, fx1=1200)
        self.assertNotAlmostEqual(r, 22.0, places=2)

    def test_el_sp_en_dolares_no_se_toca(self):
        """Con el selector en dólares el índice YA está en la moneda de la
        cartera. Convertirlo contaría la devaluación al revés."""
        r = performance.retorno_bench_en_moneda(
            2.0, "sp500", moneda=twr.MONEDA_USD, fx0=1000, fx1=1200)
        self.assertAlmostEqual(r, 2.0, places=9)

    def test_el_merval_en_pesos_no_se_toca(self):
        """El Merval cotiza en pesos: con el selector en pesos ya coinciden.
        Multiplicarlo por el TC lo contaría dos veces — es justo lo que
        `BENCH_EN_ARS` existe para evitar, y acá se lee de esa misma tabla."""
        self.assertIn("merval", performance.BENCH_EN_ARS)
        r = performance.retorno_bench_en_moneda(
            60.0, "merval", moneda=twr.MONEDA_ARS, fx0=1000, fx1=1200)
        self.assertAlmostEqual(r, 60.0, places=9)

    def test_el_merval_en_dolares_se_des_convierte(self):
        """La identidad con las puntas al revés: +60 % en pesos con 20 % de
        devaluación es +33,33 % en dólares."""
        r = performance.retorno_bench_en_moneda(
            60.0, "merval", moneda=twr.MONEDA_USD, fx0=1000, fx1=1200)
        self.assertAlmostEqual(r, (1.60 / 1.20 - 1) * 100, places=6)

    def test_la_inflacion_no_se_convierte_NUNCA_y_se_devuelve_cruda(self):
        """Una tasa en pesos no tiene versión en dólares, así que el índice no se
        mueve: se mueve la CARTERA, y eso lo hace `twr.vs_inflacion_ar`.

        ⚠️ ACÁ ESTABA MI ERROR, y el test lo cristalizaba. La primera versión
        devolvía None razonando que "no hay respuesta en dólares". Pero esta
        función no contesta "¿le ganaste?" — sólo entrega el número del índice, y
        `vs_inflacion_ar` necesita justamente ese número crudo para comparar.
        Devolver None le sacaba el dato y el veredicto contra inflación
        desaparecía en dólares: el defecto que F5 vino a cerrar, por la puerta de
        al lado. Lo cazaron cuatro tests de `test_benchmark_anual.py` — el test
        ajeno tenía razón y el mío estaba afirmando el bug.
        """
        self.assertIn("inflation_ar", performance.BENCH_PORCENTUAL)
        for moneda in (twr.MONEDA_USD, twr.MONEDA_ARS, None):
            for key in ("inflation_ar", "plazo_fijo"):
                self.assertAlmostEqual(
                    performance.retorno_bench_en_moneda(
                        4.5, key, moneda=moneda, fx0=1000, fx1=1200),
                    4.5, places=6, msg=f"{key} / {moneda}")

    def test_sin_tc_no_publica(self):
        """Misma política que `twr.vs_inflacion_ar`: sin devaluación no hay
        conversión, y publicar el número de una moneda con la etiqueta de la otra
        es el defecto que esto viene a cerrar."""
        for fx0, fx1 in ((None, None), (1000, None), (None, 1200), (0, 1200)):
            self.assertIsNone(
                performance.retorno_bench_en_moneda(
                    2.0, "sp500", moneda=twr.MONEDA_ARS, fx0=fx0, fx1=fx1),
                f"fx0={fx0} fx1={fx1}")

    def test_sin_benchmark_no_inventa(self):
        self.assertIsNone(performance.retorno_bench_en_moneda(
            None, "sp500", moneda=twr.MONEDA_ARS, fx0=1000, fx1=1200))


class ReportesLoUsaTest(unittest.TestCase):
    """EL CAMINO DE PRODUCCIÓN: `compute_metrics_for_period`, el mismo que
    atraviesa Reportes. Acá es donde vivía el bug, así que acá es donde se mide.

    LA CARTERA DEL FIXTURE ESTÁ PLANA EN DÓLARES a propósito: 5.000 → 5.000 sin
    flujos. Todo lo que se vea en pesos es devaluación pura, o sea que cualquier
    "le ganaste" es enteramente falso.
    """

    SP500_MES_PCT = 2.0
    BENCH = {"sp500": {"2026-02": 100.0, "2026-03": 102.0}}
    FECHAS_FX = ("2026-02-28", "2026-03-31")

    def setUp(self):
        self.conn = main.get_db()
        self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES (?,'x',1,1)", (f"sp500-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.uid = self.conn.execute(
            "SELECT id FROM users ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.conn.execute(
            """INSERT INTO monthly_entries
                  (user_id, broker, year, month, capital_inicio, capital_final,
                   deposits, withdrawals, pnl_realized, pnl_unrealized)
               VALUES (?, 'global', 2026, 3, 5000, 5000, 0, 0, 0, 0)""",
            (self.uid,))
        # El peso se devalúa 20 % dentro del mes. Las dos puntas son el último día
        # del mes anterior y el último del mes, igual que el motor.
        for fecha, tc in zip(self.FECHAS_FX, (1000.0, 1200.0)):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                (fecha, tc, tc))
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            # `fx_rates_daily` es GLOBAL (no lleva user_id): se borran las fechas
            # que sembró este test, no la tabla. Borrarla entera rompe a otros
            # archivos, y sólo en la suite completa.
            self.conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                              self.FECHAS_FX)
        except Exception:
            pass
        self.conn.commit()
        self.conn.close()

    def _metrics(self, moneda="usd"):
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-03-01", "2026-03-31",
            broker_filter="global", bench=self.BENCH, moneda=moneda)
        return m

    def test_en_dolares_nada_cambia(self):
        """La cartera plana pierde contra un S&P que subió 2 %. Esto ya estaba
        bien y tiene que seguir igual."""
        m = self._metrics("usd")
        self.assertAlmostEqual(m.delta_pct, 0.0, places=1)
        self.assertAlmostEqual(m.sp500_return_pct, self.SP500_MES_PCT, places=1)
        self.assertAlmostEqual(m.vs_sp500_pct, -2.0, places=1)

    def test_en_pesos_el_sp_tambien_va_en_pesos(self):
        """EL QUE MIDE. Contra el código viejo falla con `2.0 != 22.4`.

        La aserción que mide va sobre `sp500_return_pct`, un campo que YA EXISTÍA
        antes del arreglo: si lo primero que se toca fuera un campo nuevo, el test
        fallaría con AttributeError y estaría probando que el campo es nuevo, no
        que el número estaba mal.
        """
        m = self._metrics("ars")
        # La cartera, en pesos, es pura devaluación: +20 %.
        self.assertAlmostEqual(m.delta_pct, 20.0, places=1)
        # Y el S&P también tiene que estar en pesos: 1,02 × 1,20 − 1 = 22,4 %.
        self.assertAlmostEqual(m.sp500_return_pct, 22.4, places=1)
        self.assertNotAlmostEqual(m.sp500_return_pct, self.SP500_MES_PCT, places=1)

    def test_el_veredicto_no_depende_del_selector(self):
        """LA PROPIEDAD QUE IMPORTA. La misma cartera, el mismo mes, la misma
        respuesta en las dos monedas.

        El EXCESO en puntos sí cambia de tamaño al cambiar de moneda (2 puntos en
        dólares son 2,4 en pesos: se escalan con la devaluación, y eso es
        correcto). Lo que no puede cambiar es el SIGNO, que es el veredicto que
        la tarjeta publica en palabras.

        Contra el código viejo falla con `True != False`: en pesos daba +18,0.
        """
        en_usd = self._metrics("usd").vs_sp500_pct
        en_ars = self._metrics("ars").vs_sp500_pct
        self.assertIsNotNone(en_usd)
        self.assertIsNotNone(en_ars)
        self.assertEqual(en_usd >= 0, en_ars >= 0,
                         f"el veredicto se da vuelta: {en_usd} vs {en_ars}")
        self.assertLess(en_ars, 0, "la cartera plana NO le ganó al S&P")

    def test_los_18_puntos_que_publicaba_antes_eran_la_devaluacion(self):
        """El número viejo, nombrado. `delta_pct − S&P_en_dólares` era +18,0pp
        sobre una cartera que en dólares no se movió."""
        m = self._metrics("ars")
        viejo = m.delta_pct - self.SP500_MES_PCT
        self.assertAlmostEqual(viejo, 18.0, places=1)
        self.assertNotAlmostEqual(m.vs_sp500_pct, viejo, places=1)

    def test_el_exceso_sale_del_sp_que_la_tarjeta_muestra(self):
        """La tarjeta muestra los dos juntos ("El S&P hizo X · vs S&P Y"). Si el X
        que muestra no es el X del que salió la resta, se contradice sola. Es la
        misma razón por la que `vs_inflacion_ar` devuelve el retorno convertido
        además del exceso."""
        for moneda in ("usd", "ars"):
            m = self._metrics(moneda)
            self.assertAlmostEqual(m.delta_pct - m.sp500_return_pct,
                                   m.vs_sp500_pct, places=1, msg=moneda)

    def test_sin_serie_de_dolar_no_publica_el_vs(self):
        """Y entonces tampoco publica el retorno del índice: los dos o ninguno.
        Publicar el S&P en dólares con etiqueta de pesos es peor que no publicar.

        Contra el código viejo falla con `18.0 is not None`.
        """
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                          self.FECHAS_FX)
        self.conn.commit()
        m = self._metrics("ars")
        self.assertIsNone(m.vs_sp500_pct)
        self.assertIsNone(m.sp500_return_pct)
        # El rendimiento sigue publicándose: ése no depende de esta conversión.
        self.assertIsNotNone(m.delta_pct)

    def test_en_dolares_sin_tc_el_sp_sigue_saliendo(self):
        """Sin TC, en dólares no hace falta convertir nada: el S&P ya está en la
        moneda de la cartera. El guard no puede tapar lo que no necesita TC."""
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date IN (?,?)",
                          self.FECHAS_FX)
        self.conn.commit()
        m = self._metrics("usd")
        self.assertAlmostEqual(m.sp500_return_pct, self.SP500_MES_PCT, places=1)
        self.assertAlmostEqual(m.vs_sp500_pct, -2.0, places=1)


class LaPuertaSinGuardiaTest(unittest.TestCase):
    """El agujero que aparecio al UNIFICAR con la otra sesion, y no antes.

    Las dos sesiones llegaron a la misma regla el mismo dia: ellos adentro de
    `benchmark_entre_fechas` (solo para el ANIO), yo en el call site (para todos
    los periodos). Las dos conversiones son algebraicamente identicas —con
    `pct = (i1-1)x100`, `(1+pct/100)*(f1/f0)-1` se reduce a `i1*f1/f0-1`— asi que
    dejar las dos apiladas habria contado la devaluacion DOS VECES para el anio.

    Al unificarlas quedo una puerta sin guardia: la conversion se decidia con
    `if fx is not None`, o sea que "estoy en pesos" se INFERIA de que el TC
    estuviera disponible. Pero el caller envuelve `serie_fx` en try/except y deja
    `fx = None` si falla — y entonces el indice salia EN DOLARES, sin convertir,
    contra una cartera en pesos. El bug entero, entrando por la puerta de al lado.

    Por eso `moneda` viaja aparte de `fx`: la falta de TC se distingue de la falta
    de NECESIDAD de TC, y sin TC no se publica.
    """

    def test_en_pesos_sin_TC_no_se_publica_el_indice_en_dolares(self):
        from reporting import builder as _b
        BENCH = {"sp500": {"2026-02": 100.0, "2026-03": 102.0}}
        # Con TC: convierte.
        con = _b.benchmark_return_for_period(
            BENCH, "month", "2026-03-01", "2026-03-31", "sp500",
            fx=lambda d: 1200.0 if str(d) >= "2026-03-01" else 1000.0, moneda="ars")
        self.assertAlmostEqual(con, 22.4, places=1)
        # Sin TC y en pesos: NO se publica. Antes devolvia 2.0 — el S&P en dolares
        # con etiqueta de pesos.
        sin = _b.benchmark_return_for_period(
            BENCH, "month", "2026-03-01", "2026-03-31", "sp500",
            fx=None, moneda="ars")
        self.assertIsNone(sin, "publico el indice en dolares con etiqueta de pesos")

    def test_en_dolares_sin_TC_se_publica_normal(self):
        """En dolares el S&P no necesita conversion: el guard no puede taparlo."""
        from reporting import builder as _b
        BENCH = {"sp500": {"2026-02": 100.0, "2026-03": 102.0}}
        for moneda in (None, "usd"):
            r = _b.benchmark_return_for_period(
                BENCH, "month", "2026-03-01", "2026-03-31", "sp500",
                fx=None, moneda=moneda)
            self.assertAlmostEqual(r, 2.0, places=1, msg=str(moneda))

    def test_la_inflacion_nunca_se_convierte_por_esta_via(self):
        """Aunque venga TC: es una tasa en pesos y su regla es `vs_inflacion_ar`."""
        from reporting import builder as _b
        BENCH = {"inflation_ar": {"2026-03": 4.5}}
        for moneda in (None, "usd", "ars"):
            r = _b.benchmark_return_for_period(
                BENCH, "month", "2026-03-01", "2026-03-31", "inflation_ar",
                fx=lambda d: 1200.0, moneda=moneda)
            self.assertAlmostEqual(r, 4.5, places=2, msg=str(moneda))


class UnaSolaTablaDeMonedasGuardTest(unittest.TestCase):
    """Guard contra la re-copia. LEE CÓDIGO, no números.

    Un test de comportamiento pasa igual aunque mañana alguien escriba la copia
    número 2 de "qué benchmarks están en pesos" en otro archivo. La causa raíz de
    este repo no es que el cálculo esté mal: es que está escrito en varios lados y
    el arreglo llega a uno.
    """

    def test_la_lista_de_benchmarks_en_pesos_vive_en_un_solo_lugar(self):
        import pathlib
        raiz = pathlib.Path(__file__).resolve().parent.parent
        culpables = []
        for py in raiz.rglob("*.py"):
            if "/tests/" in str(py) or py.name == "performance.py":
                continue
            try:
                txt = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # Definir la lista, no importarla: `X = (... "merval" ...)`.
            for linea in txt.splitlines():
                s = linea.strip()
                if (s.startswith("BENCH_EN_ARS") or s.startswith("BENCH_PORCENTUAL")) \
                        and "=" in s and "import" not in s:
                    culpables.append(f"{py.relative_to(raiz)}: {s[:70]}")
        self.assertEqual(culpables, [],
                         "la tabla de monedas de benchmark se copió; vive en "
                         "performance.BENCH_EN_ARS y se importa desde ahí:\n"
                         + "\n".join(culpables))

    def test_reportes_no_reimplementa_la_conversion(self):
        """`reporting/builder.py` tiene que PEDIRLE la conversión a
        `performance`, no multiplicar por el TC por su cuenta."""
        import pathlib
        b = (pathlib.Path(__file__).resolve().parent.parent
             / "reporting" / "builder.py").read_text(encoding="utf-8")
        self.assertIn("retorno_bench_en_moneda", b,
                      "Reportes dejó de usar el conversor canónico")


if __name__ == "__main__":
    unittest.main()
