"""Un capital NEGATIVO en la cadena contable no es un arranque: es una cadena rota.

Una cartera no vale menos que cero. Cuando `monthly_entries` tiene un
`capital_inicio` negativo (la carga se rompió: el caso conocido es el broker
argentino marcado en dólares, ver `_capital_roto`), medir el período desde ahí
publica el agujero como ganancia. Medido el 2026-10-01 sobre origin/main, con
`build_period_report(..., today=date(2026, 10, 15))`:

    arranque −5.000, aporte 1.000, cartera hoy 12.000   → "Mes: +US$ 16.000"
    arranque −10.000, sin flujos, cartera vacía          → "Mes: +US$ 10.000"
    enero en −5.000, cartera hoy 12.000                  → "Año: +US$ 16.000"
    mes cerrado de −5.000 a −3.000                       → "Mes: +US$ 2.000"
    sin fila de octubre, septiembre cerró en −5.000      → "Mes sin grandes movimientos"

`_basis_is_incomparable` daba "comparable" con un arranque ≤ 0, y las cotas de
`v0 = 0` (`twr.leg_dudoso`, `SALTO_MAX_VECES`) sólo corrían si había un `%`: con
arranque negativo el Dietz da None y el MONTO salía igual.

Todos los casos van por `build_period_report`, que es lo que llaman /reportes, la
lista de años y el paquete de la IA, y con FECHA FIJA: si el caso depende de dónde
cae una fila respecto del período, un test relativo a hoy lo prueba unos días por
mes y el resto está verde (ver la memoria del rojo del día 1).
"""
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main  # noqa: E402
from reporting import builder  # noqa: E402
from reporting.builder import build_period_report  # noqa: E402
from reporting.schema import report_to_dict  # noqa: E402

HOY = date(2026, 10, 15)


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("arranque-negativo@t", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def mes(self, y, m, ci, cf, dep=0.0, ret=0.0, pnl=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,?,?,?,0)",
            (self.uid, y, m, ci, cf, dep, ret, pnl))
        self.conn.commit()

    def reporte(self, tipo, clave, live=None):
        return report_to_dict(build_period_report(
            self.conn, self.uid, tipo, clave, "global", None,
            live_value=live, today=HOY))

    def assertSinBase(self, d, palabra):
        m = d["metrics"]
        self.assertTrue(m["basis_incomparable"], d.get("headline"))
        self.assertEqual(m["delta_usd"], 0.0)
        self.assertIsNone(m["delta_pct"])
        self.assertEqual(d["headline"], f"{palabra} sin base para medir el rendimiento.")
        # La causa REAL, no "falta el cierre a mercado": mandar al usuario a buscar
        # un cierre que no falta es decirle la causa equivocada.
        self.assertIn("capital negativo", d["subheadline"] or "")


class MesEnCursoTest(_Base):

    def test_arranque_negativo_con_aporte_no_publica_el_agujero(self):
        """El caso del hallazgo: −5.000 + 1.000 de aporte, la cartera vale 12.000.
        La resta daba 12.000 − (−5.000) − 1.000 = +16.000 de "ganancia"."""
        self.mes(2026, 10, -5000.0, -4000.0, dep=1000.0)
        self.assertSinBase(self.reporte("month", "2026-10", live=12000.0), "Mes")

    def test_arranque_negativo_con_la_cartera_vacia(self):
        """Sin flujos y la última foto en 0 (`_latest_snapshot_value` devuelve 0.0
        para una cartera medida vacía): daba "+US$ 10.000"."""
        self.mes(2026, 10, -10000.0, -10000.0)
        self.assertSinBase(self.reporte("month", "2026-10", live=0.0), "Mes")

    def test_sin_fila_del_mes_hereda_el_cierre_negativo(self):
        """Octubre todavía sin fila (el rollover es perezoso) y septiembre cerró en
        −5.000. El `> 0` del heredado lo tiraba, el arranque quedaba en 0 y el mes
        decía "Mes sin grandes movimientos": afirma que no pasó nada."""
        self.mes(2026, 9, -3000.0, -5000.0, ret=2000.0)
        self.assertSinBase(self.reporte("month", "2026-10", live=12000.0), "Mes")

    def test_residuo_de_redondeo_no_es_cadena_rota(self):
        """Control: −0,004 es una cuenta en cero con polvo, no una cadena rota. El
        primer mes de un usuario nuevo tiene que seguir midiéndose."""
        self.mes(2026, 10, -0.004, 1000.0, dep=1000.0)
        m = self.reporte("month", "2026-10", live=1050.0)["metrics"]
        self.assertFalse(m["basis_incomparable"])
        self.assertAlmostEqual(m["delta_usd"], 50.0, places=1)

    def test_control_onboarding_sigue_igual(self):
        """Control: arranque 0 con aporte es el alta, y ahí start = 0 es CORRECTO."""
        self.mes(2026, 10, 0.0, 1000.0, dep=1000.0)
        d = self.reporte("month", "2026-10", live=1050.0)
        self.assertFalse(d["metrics"]["basis_incomparable"])
        self.assertAlmostEqual(d["metrics"]["delta_usd"], 50.0, places=1)
        self.assertAlmostEqual(d["metrics"]["delta_pct"], 10.0, places=1)


class MesCerradoTest(_Base):

    def test_mes_cerrado_que_arranca_negativo(self):
        """Las dos puntas de la cadena: el Dietz da None (denominador ≤ 0), la cota
        de las puntas se salteaba por eso, y el monto salía: "Mes: +US$ 2.000"."""
        self.mes(2026, 9, -5000.0, -3000.0, pnl=2000.0)
        self.assertSinBase(self.reporte("month", "2026-09"), "Mes")

    def test_mes_cerrado_negativo_con_aporte_grande_no_da_un_porcentaje(self):
        """Con un aporte grande el denominador vuelve a dar positivo y salía un %
        calculado sobre una base que no existe: +20 % donde, sin el agujero, el
        mismo resultado sobre lo aportado es la mitad."""
        self.mes(2026, 9, -5000.0, 16000.0, dep=20000.0, pnl=1000.0)
        self.assertSinBase(self.reporte("month", "2026-09"), "Mes")

    def test_control_mes_cerrado_positivo_sigue_igual(self):
        self.mes(2026, 9, 1000.0, 1100.0, pnl=100.0)
        m = self.reporte("month", "2026-09")["metrics"]
        self.assertFalse(m["basis_incomparable"])
        self.assertAlmostEqual(m["delta_usd"], 100.0, places=1)
        self.assertAlmostEqual(m["delta_pct"], 10.0, places=1)


class AnioTest(_Base):

    def test_anio_en_curso_que_arranca_negativo(self):
        """Mismo cruce que el mes (cadena contra el valor de hoy): "Año: +US$ 16.000"."""
        self.mes(2026, 1, -5000.0, -5000.0)
        for mm in range(2, 10):
            self.mes(2026, mm, -5000.0, -5000.0)
        self.mes(2026, 10, -5000.0, -4000.0, dep=1000.0)
        self.assertSinBase(self.reporte("year", "2026", live=12000.0), "Año")

    def _anio_2025(self, feb_ci):
        """Enero arranca en 1.000 y retira 1.400 (la cadena cierra en −400: ninguna
        cartera puede); febrero arranca ahí y entran 3.000. `leg_dudoso` no ve el
        hueco: el Dietz de enero da 0 % y el de febrero, con el aporte, también."""
        self.mes(2025, 1, 1000.0, feb_ci, ret=1000.0 - feb_ci)
        self.mes(2025, 2, feb_ci, feb_ci + 3000.0, dep=3000.0)
        cap = feb_ci + 3000.0
        for mm in range(3, 12):
            self.mes(2025, mm, cap, cap)
        self.mes(2025, 12, cap, cap + 100.0, pnl=100.0)

    def test_anio_cerrado_con_un_mes_que_arranca_negativo(self):
        """La composición mes a mes salteaba callado el mes roto (Dietz None → lo
        contaba como 0 %) y publicaba "+3,85 %" para el año. Un mes que no se puede
        creer tumba el producto entero, igual que un salto de `leg_dudoso`."""
        self._anio_2025(-400.0)
        self.assertSinBase(self.reporte("year", "2025"), "Año")

    def test_control_anio_cerrado_sano_compone(self):
        """El mismo año con la cadena en 0 (retiró todo): se compone como siempre."""
        self._anio_2025(0.0)
        m = self.reporte("year", "2025")["metrics"]
        self.assertFalse(m["basis_incomparable"])
        self.assertIsNotNone(m["delta_pct"])


class UnaSolaReglaTest(unittest.TestCase):
    """La regla vive en `_capital_roto` y la pregunta `_basis_is_incomparable`, que
    es el guard que comparten mes, año y —en el arreglo de día/semana—
    `_ancla_permite_publicar`. Si alguien vuelve a escribir `start_value <= 0 →
    comparable`, este test lo dice antes que la pantalla."""

    def test_el_guard_compartido_tapa_el_negativo(self):
        self.assertTrue(builder._basis_is_incomparable(False, -5000.0, 1000.0, 0.0))
        self.assertTrue(builder._basis_is_incomparable(False, -5000.0, 0.0, 0.0))

    def test_el_cero_y_el_residuo_siguen_siendo_comparables(self):
        self.assertFalse(builder._basis_is_incomparable(False, 0.0, 1000.0, 0.0))
        self.assertFalse(builder._basis_is_incomparable(False, -0.004, 1000.0, 0.0))


if __name__ == "__main__":
    unittest.main()
