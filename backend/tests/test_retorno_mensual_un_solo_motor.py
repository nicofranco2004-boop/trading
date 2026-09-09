"""Un solo denominador para el retorno mensual, en todo lo que se publica.

El mismo mes se calculaba de cinco formas distintas. Ninguna era la del motor:
todas dividían por `capital_inicio` a secas, cuando el aporte del mes entró a
mitad de mes y el denominador de Modified Dietz es `capital_inicio + 0,5·flujo`.

Medido (el caso del audit — ci=1000, cf=2100, dep=1000):

    denominador viejo   (2100 − 1000 − 1000) / 1000  = +10,00 %
    `twr.dietz`         (2100 − 1000 − 1000) / 1500  =  +6,67 %

y compuesto a doce meses, +213,8 % contra +116,9 %. El slide del Wrapped que
publica ese número se exporta como PNG; los otros cuatro lectores le arman el
contexto a la IA.

Este test NO re-implementa la cuenta: le pregunta a `twr.dietz` y exige que cada
lector diga lo mismo. Si mañana alguien vuelve a escribir la fórmula a mano en
uno de ellos, este test es el que se pone en rojo.

Corre con: cd backend && python3 -m pytest tests/test_retorno_mensual_un_solo_motor.py
"""
from __future__ import annotations
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
import twr as _twr
from ai.builders import insights, insights_evolution, reports, dashboard_evolution

# El mes del audit.
CI, CF, DEP = 1000.0, 2100.0, 1000.0
ESPERADO_PCT = round(_twr.retorno_mensual(CI, CF, DEP) * 100, 2)   # 6.67
VIEJO_PCT = round((CF - CI - DEP) / CI * 100, 2)            # 10.0


class TestNingunLectorReimplementaLaRegla(unittest.TestCase):
    """Sólo lee código fuente: sin DB, sin usuarios (ver la clase gemela
    en test_advisor_plan.py)."""

    def test_ningun_lector_reimplementa_la_regla(self):
        """El guard `ci > 0` vive en `twr.retorno_mensual`, no copiado en cada uno.

        Es la regla 2 del CLAUDE.md: si el mismo cálculo existe en más de un
        lugar, la respuesta no es arreglar los dos — es que haya uno solo.
        """
        import re, pathlib
        raiz = pathlib.Path(__file__).resolve().parent.parent
        lectores = ["wrapped.py", "ai/builders/insights.py",
                    "ai/builders/insights_evolution.py", "ai/builders/reports.py",
                    "ai/builders/dashboard_evolution.py"]
        for rel in lectores:
            txt = (raiz / rel).read_text(encoding="utf-8")
            self.assertIn("_twr.retorno_mensual(", txt, f"{rel} no usa el helper")
            # Ni la cuenta a mano ni el primitivo pelado (que se saltea el guard).
            self.assertNotIn("_twr.dietz(", txt, f"{rel} llama al primitivo sin el guard")
            self.assertIsNone(
                re.search(r"\(\s*cf\s*-\s*ci\s*-\s*net\s*\)\s*/", txt),
                f"{rel} volvió a escribir la cuenta a mano")


class TestElMesDeAltaNoSeMide(unittest.TestCase):
    """`capital_inicio = 0` no se mide, aunque `dietz` sepa dar un número.

    Con ci=0 y un depósito, el denominador queda en 0,5·flujo y el 0,5 del Dietz
    INFLA el mes: el motor lo midió en 23,71 % reportado contra 20,10 % real, y
    por eso `twr.tramos` arranca recién en el primer mes calendario completo.

    Los cinco lectores traían el guard `ci > 0` de antes. Al pasarlos al
    primitivo era fácil dejarlo caer creyendo que `dietz` ya lo cubría —no lo
    cubre: sólo corta cuando el denominador es <= 0, y 0,5·flujo da positivo.
    """

    def test_dietz_sí_mide_ese_mes_y_por_eso_hace_falta_el_guard(self):
        # `dietz` solo: mide feliz, porque 0,5·flujo es un denominador positivo.
        self.assertIsNotNone(_twr.dietz(0, 1200, 1000))
        # `retorno_mensual`: los DOS guards, en un solo lugar para los 5 lectores.
        self.assertIsNone(_twr.retorno_mensual(0, 1200, 1000))
        self.assertIsNone(_twr.retorno_mensual(None, 1200, 1000))

    def test_ningun_lector_publica_el_mes_de_alta(self):
        import wrapped
        alta = [{"year": 2026, "month": 1, "broker": "global",
                 "capital_inicio": 0, "capital_final": 1200, "deposits": 1000,
                 "withdrawals": 0, "pnl_realized": 200, "pnl_unrealized": 0}]
        self.assertIsNone(wrapped._twr_for_period(alta))
        self.assertIsNone(wrapped._slide_best_month(alta))


class TestUnSoloDenominador(unittest.TestCase):

    def setUp(self):
        import datetime as _d
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"dietz-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.addCleanup(self._limpiar)
        # Un mes del año en curso, para caer dentro de las ventanas por defecto.
        hoy = _d.date.today()
        self.year, self.month = hoy.year, hoy.month
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker, deposits,
                                            withdrawals, pnl_realized, pnl_unrealized,
                                            capital_inicio, capital_final)
               VALUES (?,?,?,'global',?,0,?,0,?,?)""",
            (self.uid, self.year, self.month, DEP, CF - CI - DEP, CI, CF))
        # dashboard_evolution corta antes si no hay curva: dos cierres del cron
        # en base de mercado alcanzan para que llegue al bloque del mejor mes.
        for i, (d, v) in enumerate(((hoy - _d.timedelta(days=40), CI),
                                    (hoy, CF))):
            self.conn.execute(
                """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                                          net_deposited, fx_to_usd_blue, source,
                                          holdings_json, apto)
                   VALUES (?,?,?,?,?,1400,'cron','[{"a":1}]',1)""",
                (self.uid, d.isoformat(), v, v, CI + DEP * i))
        self.conn.commit()

    def _limpiar(self):
        conn = main.get_db()
        conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
        conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
        conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        conn.commit(); conn.close()

    def test_el_caso_del_audit_no_es_ambiguo(self):
        self.assertAlmostEqual(ESPERADO_PCT, 6.67, places=2)
        self.assertAlmostEqual(VIEJO_PCT, 10.0, places=2)

    def test_insights_evolution(self):
        p = insights_evolution.build(self.conn, self.uid)
        mes = p["monthly_returns"][0]
        self.assertEqual(mes["return_pct"], ESPERADO_PCT)
        self.assertNotEqual(mes["return_pct"], VIEJO_PCT)
        self.assertEqual(p["twr_pct"], ESPERADO_PCT)

    def test_insights(self):
        p = insights.build(self.conn, self.uid)
        self.assertEqual(p["twr_pct"], ESPERADO_PCT)
        self.assertNotEqual(p["twr_pct"], VIEJO_PCT)

    def test_reports(self):
        p = reports.build(self.conn, self.uid, year=self.year)
        self.assertEqual(p["twr_year_pct"], ESPERADO_PCT)
        self.assertNotEqual(p["twr_year_pct"], VIEJO_PCT)
        for k in ("best_month", "worst_month"):
            self.assertEqual(p[k]["delta_pct"], ESPERADO_PCT, f"{k}")

    def test_dashboard_evolution_mejor_y_peor_mes(self):
        p = dashboard_evolution.build(self.conn, self.uid)
        for k in ("best_month", "worst_month"):
            self.assertEqual(round(p[k]["pct"] * 100, 2), ESPERADO_PCT,
                             f"{k} publica su propia cuenta")

    def test_wrapped(self):
        import wrapped
        rows = [{"year": self.year, "month": self.month, "broker": "global",
                 "capital_inicio": CI, "capital_final": CF, "deposits": DEP,
                 "withdrawals": 0, "pnl_realized": CF - CI - DEP,
                 "pnl_unrealized": 0}]
        self.assertAlmostEqual(wrapped._twr_for_period(rows) * 100,
                               ESPERADO_PCT, places=2)


if __name__ == "__main__":
    unittest.main()
