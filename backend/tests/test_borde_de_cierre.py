"""FASE 1 — el borde de CIERRE, que es el que nadie miró.

Once rondas enchufaron guards en el borde de APERTURA de cada lector
(`fetch_snapshot_at_or_before` con `accept=` / `mtm_only=True`). Ninguna miró la
otra punta, y la punta también puede ser una fila al costo: el día que el usuario
importa, la foto que el import FABRICA es la más nueva y gana cualquier
`ORDER BY date DESC LIMIT 1`.

Con la punta al costo la resta sale INVERTIDA. En vez del −65% fantasma que todos
fueron a buscar, publica un +96% fantasma — mismo defecto, signo opuesto. Por eso
sobrevivió: nadie audita un número que da bien.

Medido sobre la copia de producción del 16/08/2026: 180 de 822 usuarios (22%)
tienen la última fila al costo; 178 de ésos no tienen NINGUNA medición.

⚠️ LOS FIXTURES DE ACÁ TIENEN QUE PODER FALLAR. Un fixture con una sola naturaleza
de fila no puede disparar nada. Por eso cada caso mezcla import + cron, y el de
`net_deposited` lo usa NEGATIVO: con un `net_deposited` positivo el bug de
§4.4 es INEXHIBIBLE, y ése fue exactamente el error de un barrido anterior.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main  # noqa: E402
from reporting.builder import fetch_latest_measured_snapshot  # noqa: E402
from twr import MEDICION, INDETERMINADO  # noqa: E402


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
            ("bordecierre@t", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def snap(self, date, value, source, *, net_dep=0.0, invested=None):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,?,?,?,?,?)",
            (self.uid, date, value,
             value if invested is None else invested, net_dep, source))
        self.conn.commit()

    def pos(self, fecha="2025-01-02"):
        """Una posición no-cash: sin esto `clasificar_fila` no puede afirmar nada."""
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested, "
            "entry_date, is_cash) VALUES (?,?,?,?,?,?,0)",
            (self.uid, "Cocos", "AAPL", 1, 100.0, fecha))
        self.conn.commit()


class BordeDeCierreTest(_Base):

    def test_la_punta_fabricada_no_sirve_de_cierre(self):
        """El caso de los 178: toda la serie la fabricó el import → no hay número.

        Sin el filtro, `_latest_snapshot_value` devolvía 196.631,56 —la cadena
        contable— y el mes publicaba "Mes sólido — +96,6%" con cero operaciones.
        """
        self.pos()
        for d, v in (("2026-05-31", 192650.50),
                     ("2026-06-30", 197297.51),
                     ("2026-07-31", 196631.56)):
            self.snap(d, v, "import", net_dep=-1789.39)

        crudo = self.conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=? ORDER BY date DESC LIMIT 1",
            (self.uid,)).fetchone()
        self.assertAlmostEqual(crudo["total_value"], 196631.56, places=2,
                               msg="el fixture tiene que exhibir la punta al costo")

        self.assertIsNone(
            fetch_latest_measured_snapshot(self.conn, self.uid,
                                           accept=(MEDICION, INDETERMINADO)),
            "una foto fabricada por el import no cierra un período")
        self.assertIsNone(main._latest_snapshot_value(self.conn, self.uid))

    def test_elige_la_medicion_aunque_la_fila_al_costo_sea_mas_nueva(self):
        """La forma exacta del 452 al revés: el import llega DESPUÉS del cron.

        Es el caso que hace fallar al test si el filtro se cae: sin él, la punta
        es la fila `import` (mucho más alta) y el % sale inflado.
        """
        self.pos()
        self.snap("2026-08-14", 67648.94, "cron", net_dep=-5726.38)
        self.snap("2026-08-15", 67214.75, "cron", net_dep=-5726.38)
        # El import corre HOY y fabrica el cierre del mes pasado, más nuevo por fecha.
        self.snap("2026-08-16", 196631.56, "import", net_dep=-1789.39)

        r = fetch_latest_measured_snapshot(self.conn, self.uid,
                                           accept=(MEDICION, INDETERMINADO))
        self.assertIsNotNone(r, "hay mediciones: tiene que devolver una")
        self.assertEqual(r["date"], "2026-08-15")
        self.assertAlmostEqual(r["total_value"], 67214.75, places=2)

    def test_una_serie_sana_no_pierde_su_numero(self):
        """El guard sólo saca lo fabricado. Si todo está medido, no toca nada.

        Es la mitad que evita que el arreglo se convierta en la regresión: 200 de
        816 usuarios dejan de publicar un número, y ninguno de ellos puede ser uno
        con la serie sana.
        """
        self.pos()
        for i in range(10):
            self.snap(f"2026-08-{10+i:02d}", 1000.0 + i, "cron", net_dep=900.0)
        r = fetch_latest_measured_snapshot(self.conn, self.uid,
                                           accept=(MEDICION, INDETERMINADO))
        self.assertIsNotNone(r)
        self.assertEqual(r["date"], "2026-08-19")
        self.assertAlmostEqual(main._latest_snapshot_value(self.conn, self.uid),
                               1009.0, places=2)


class NetDepositedNegativoTest(_Base):
    """§4.4 del lado del backend — el que el audit sólo ubicó en el frontend.

    ⚠️ EL FIXTURE USA `net_deposited` NEGATIVO A PROPÓSITO. Con uno positivo este
    bug es INEXHIBIBLE: el `<= 0` nunca dispara y el test pasa sin probar nada.
    En producción son 4.744 filas (11,7%) en 192 usuarios.
    """

    def test_dos_cierres_iguales_dan_cero_y_no_un_122_por_ciento(self):
        """Los números salen de la serie REAL del uid 452 (copia del 16/08).

        El 15 y el 16 tienen EXACTAMENTE el mismo `total_value`: la cartera no se
        movió un centavo. Con el `<= 0`, `net_deposited=−5.726,38` se leía como
        "falta" y se reemplazaba por `total_invested=76.795,18` —o sea COSTO—, y el
        chip Δ1d publicaba +122,77%.
        """
        self.pos()
        self.snap("2026-08-15", 67214.75, "cron", net_dep=-5726.38, invested=76795.18)
        self.snap("2026-08-16", 67214.75, "cron", net_dep=-5726.38, invested=76795.18)

        d = main._snapshot_delta(self.conn, self.uid, 67214.75, "2026-08-16",
                                 days=1, latest_netdep=-5726.38)
        self.assertIsNotNone(d, "hay dos cierres medidos: el chip existe")
        self.assertEqual(d["prev_date"], "2026-08-15")
        self.assertAlmostEqual(d["usd"], 0.0, places=2,
                               msg="la cartera no se movió: el delta es 0")
        self.assertAlmostEqual(d["pct"], 0.0, places=2)

    def test_el_cero_sigue_cayendo_al_cost_basis(self):
        """La otra mitad de la regla: 0 SÍ significa "no lo tengo".

        La columna es `NOT NULL DEFAULT 0`, así que las filas anteriores a Phase 6
        traen exactamente 0. Ese fallback tiene que seguir vivo o se le desfasa el
        delta a los usuarios viejos.
        """
        self.pos()
        self.snap("2026-08-15", 1000.0, "cron", net_dep=0.0, invested=800.0)
        self.snap("2026-08-16", 1100.0, "cron", net_dep=0.0, invested=800.0)

        d = main._snapshot_delta(self.conn, self.uid, 1100.0, "2026-08-16",
                                 days=1, latest_netdep=800.0)
        self.assertIsNotNone(d)
        # prev_netdep cae a total_invested (800), igual que latest_netdep → el
        # delta es el movimiento puro de valor: 1100 − 1000 = 100.
        self.assertAlmostEqual(d["usd"], 100.0, places=2)


if __name__ == "__main__":
    unittest.main()


class Ronda2Test(_Base):
    """Lo que la pasada adversarial encontró abierto en la ronda 1."""

    def test_cierre_en_cero_es_una_medicion_no_un_hueco(self):
        """El uid 330: vendió todo, sus 6 últimas filas son `cron` con valor 0.

        Con `total_value > 0` heredado del borde de APERTURA, el lector las
        salteaba y retrocedía hasta encontrar una fila con valor —hasta 57 días—,
        publicando la variación de dos días de junio como "el último cierre".
        160 usuarios tenían su última fila medida descartada por esto.
        """
        self.pos()
        self.snap("2026-06-29", 5000.0, "cron", net_dep=5000.0)
        self.snap("2026-06-30", 5400.0, "cron", net_dep=5000.0)   # +8% — el fantasma
        for d in ("2026-08-11", "2026-08-12", "2026-08-13"):
            self.snap(d, 0.0, "cron", net_dep=5000.0)             # vendió todo

        r = fetch_latest_measured_snapshot(self.conn, self.uid,
                                           accept=(MEDICION, INDETERMINADO))
        self.assertIsNotNone(r, "una cartera vacía SÍ tiene cierre: vale cero")
        self.assertEqual(r["date"], "2026-08-13")
        self.assertEqual(float(r["total_value"]), 0.0)
        self.assertEqual(main._latest_snapshot_value(self.conn, self.uid), 0.0)

    def test_el_borde_de_APERTURA_sigue_exigiendo_valor_positivo(self):
        """La otra mitad: en la apertura un 0 es el DENOMINADOR y no sirve.

        Si esto se afloja, el período divide por cero. Las dos puntas piden cosas
        distintas y por eso `require_positive` existe.
        """
        from reporting.builder import fetch_snapshot_at_or_before
        self.pos()
        self.snap("2026-07-31", 0.0, "cron", net_dep=5000.0)
        self.snap("2026-08-16", 100.0, "cron", net_dep=5000.0)
        r = fetch_snapshot_at_or_before(self.conn, self.uid, "2026-08-01",
                                        accept=(MEDICION, INDETERMINADO))
        self.assertIsNone(r, "un 0 no puede ser base de un porcentaje")


class MesEnCursoSinMedicionTest(_Base):
    """El mes EN CURSO sin cierre medido NO es un mes cerrado.

    Con `live_value=None`, `month_is_current` quedaba False y el mes en curso se
    calculaba con la cadena contable: 195 usuarios leían "Mes sin grandes
    movimientos" —que AFIRMA que no pasó nada— y uno leía "+2,5%".
    """

    def _reporte(self, live):
        from reporting.builder import build_period_report
        from reporting.schema import report_to_dict
        from datetime import date as _date
        return report_to_dict(build_period_report(
            self.conn, self.uid, "month", "2026-08", "global", None,
            live_value=live, today=_date(2026, 8, 16))) or {}

    def test_sin_cierre_medido_lo_dice_en_vez_de_afirmar_que_no_paso_nada(self):
        self.pos()
        # Sólo filas que fabricó el import: hay historia, pero nada medido.
        for d, v in (("2026-06-30", 190000.0), ("2026-07-31", 196631.56)):
            self.snap(d, v, "import", net_dep=-1789.39)
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, "
            "capital_inicio, capital_final, deposits, withdrawals) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.uid, "global", 2026, 8, 196631.56, 196700.0, 0, 0))
        self.conn.commit()

        d = self._reporte(main._latest_snapshot_value(self.conn, self.uid))
        self.assertIsNone(main._latest_snapshot_value(self.conn, self.uid),
                          "el fixture tiene que exhibir el caso: sin cierre medido")
        self.assertTrue(d["metrics"]["basis_incomparable"])
        self.assertIsNone(d["metrics"]["delta_pct"])
        self.assertIn("sin base para medir", (d.get("headline") or "").lower())

    def test_la_cuenta_VACIA_no_recibe_el_sermon(self):
        """"No se puede medir" y "no hay nada" son dos cosas distintas.

        Sin este chequeo, el usuario recién registrado leía "Mes sin base para
        medir el rendimiento" sobre una cuenta vacía —le contesta una pregunta que
        no hizo— y además el mes le quedaba `is_relevant` en la timeline.
        """
        d = self._reporte(None)
        self.assertFalse(d["metrics"].get("basis_incomparable"),
                         "una cuenta sin nada no tiene nada que declarar")
