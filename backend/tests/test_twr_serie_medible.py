"""FASE 2 — la serie canónica: `twr.serie_medible` / `twr.curva_indexada`.

El caso que da nombre a todo esto es `test_452_*`: un usuario real al que la app
le publicaba "Drawdown actual −45,0%" porque encadenaba una foto FABRICADA por el
import (139.570,56, la cadena contable) contra una medición real a mercado
(73.604,02). El usuario lo diagnosticó solo: "yo nunca llegué tan arriba".
Tenía razón — ese pico lo puso el sistema.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr


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
            ("twrserie@t", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def snap(self, date, value, source, *, net_dep=0.0, cov=None, fx=None, hold=None):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (self.uid, date, value, value, net_dep, source, cov, fx, hold))
        self.conn.commit()

    def pos(self, entry_date, asset="AAPL"):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,100,?)",
            (self.uid, "IBKR", asset, entry_date))
        self.conn.commit()


class Regresion452Test(_Base):
    """Los números duros de /api/admin/diagnose-reportes-basis?user_id=452."""
    CI_CADENA = 139570.56       # capital_inicio_cadena — FABRICADO por el import
    DEPOSITS = 130.80
    ULTIMA = 73604.02           # ultima_medicion (24-ago) — medición real

    def test_el_motor_viejo_daba_menos_45(self):
        """Primero se reproduce el defecto: sin filtrar la base, la aritmética da
        el −45/−47% que el usuario vio. Si este número dejara de salir, el test de
        abajo estaría pasando por la razón equivocada."""
        r = twr.dietz(self.CI_CADENA, self.ULTIMA, self.DEPOSITS)
        self.assertLess(r, -0.45)

    def test_452_no_publica_el_drawdown_falso(self):
        self.pos("2025-01-15")
        self.snap("2026-07-31", self.CI_CADENA, "import", net_dep=0.0)
        self.snap("2026-08-24", self.ULTIMA, "cron",
                  net_dep=self.DEPOSITS, fx=1400.0, hold="[]")
        c = twr.curva_indexada(self.conn, self.uid)
        # La foto contable NO entra: queda una sola medición → no hay período.
        self.assertEqual(len(c["puntos"]), 1)
        self.assertIsNone(c["twr"])
        self.assertEqual(c["drawdown_maximo"], 0.0)
        self.assertEqual(c["motivo"], "una_sola_medicion")
        self.assertTrue(c["motivo_texto"])
        # Y lo descartado no se tira: queda para la banda contable.
        self.assertEqual(len(c["contable"]), 1)
        self.assertAlmostEqual(c["contable"][0]["value"], self.CI_CADENA, places=2)

    def test_452_reconstruido_a_mercado_recupera_la_historia(self):
        """El objetivo de negocio: si el mes de julio se RECONSTRUYE a precio real
        (no la cadena contable), el usuario recupera su historia y el drawdown pasa
        a medir el mercado, no la brecha entre dos bases."""
        self.pos("2025-01-15")
        self.snap("2026-07-31", 74000.0, "mtm_backfill", net_dep=0.0, cov=0.95)
        self.snap("2026-08-24", self.ULTIMA, "cron",
                  net_dep=self.DEPOSITS, fx=1400.0, hold="[]")
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(c["puntos"]), 2)
        self.assertGreater(c["drawdown_actual"], -0.05)   # ~0, no −45%
        self.assertGreater(c["twr"], -0.05)


class ClaseYCoberturaTest(_Base):
    def test_reconstruido_bajo_el_piso_vuelve_a_ser_contable(self):
        """Un mes reconstruido mayormente AL COSTO no puede presentarse como medido:
        sería cambiar una mentira etiquetada por una sin etiquetar."""
        self.pos("2025-01-15")
        self.snap("2026-06-30", 100.0, "mtm_backfill", cov=0.20)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["puntos"], [])
        self.assertEqual(s["por_clase"][twr.SINTETICO_COSTO], 1)

    def test_reconstruido_sin_cobertura_estampada_no_se_confia(self):
        self.pos("2025-01-15")
        self.snap("2026-06-30", 100.0, "mtm_backfill", cov=None)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["puntos"], [])

    def test_reconstruido_sobre_el_piso_es_base_de_mercado(self):
        self.pos("2025-01-15")
        self.snap("2026-06-30", 100.0, "mtm_backfill", cov=0.90)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(len(s["puntos"]), 1)
        self.assertEqual(s["puntos"][0]["clase"], twr.RECONSTRUIDO)
        self.assertTrue(s["puntos"][0]["apto"])
        self.assertAlmostEqual(s["cobertura_reconstruccion"], 0.90, places=3)


class CaveatPosicionesPorFechaTest(_Base):
    def test_el_que_vendio_todo_no_asciende_sus_filas_viejas(self):
        """⚠️ EL CAVEAT. `_usuarios_con_posiciones` mira las posiciones de HOY. Un
        usuario que vendió todo da tenia_posiciones=False, y con ese False sus filas
        VIEJAS de browser (fx sin holdings) dejaban de ser INTRADIA y ASCENDÍAN a
        MEDICION — pasaban a habilitar bordes que nunca fueron una medición."""
        # Vendió todo: no queda NADA en positions, sólo la operación cerrada.
        self.conn.execute(
            "INSERT INTO operations (user_id, date, broker, asset, op_type, quantity, "
            "entry_date) VALUES (?,?,?,?,?,?,?)",
            (self.uid, "2026-05-10", "IBKR", "AAPL", "sell", 1, "2025-02-01"))
        self.conn.commit()
        self.assertEqual(twr.primera_fecha_con_posiciones(self.conn, self.uid), "2025-02-01")
        # Fila de browser de 2026: fx sin holdings, POSTERIOR a que tuviera cartera.
        self.snap("2026-03-31", 5000.0, None, fx=1200.0)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["por_clase"][twr.INTRADIA], 1)
        self.assertEqual(s["puntos"], [])          # NO ascendió

    def test_el_100_por_ciento_cash_sigue_siendo_medicion(self):
        """El otro lado: sin posiciones NUNCA, el cron deja holdings NULL con razón
        y esa fila SÍ es una medición válida. El fix no puede castigarlo."""
        self.assertIsNone(twr.primera_fecha_con_posiciones(self.conn, self.uid))
        self.snap("2026-03-31", 5000.0, None, fx=1200.0)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(len(s["puntos"]), 1)
        self.assertEqual(s["puntos"][0]["clase"], twr.MEDICION)


class HuecosTest(_Base):
    def test_un_hueco_largo_parte_la_serie_y_no_se_rellena(self):
        self.pos("2025-01-15")
        for d, v in (("2026-01-31", 100.0), ("2026-02-28", 110.0),
                     ("2026-08-31", 120.0)):
            self.snap(d, v, "cron", fx=1200.0, hold="[]")
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(len(s["tramos"]), 2)
        self.assertEqual(len(s["tramos"][0]), 2)
        self.assertEqual(len(s["tramos"][1]), 1)
        # No se inventó ningún punto en el medio.
        self.assertEqual(len(s["puntos"]), 3)

    def test_el_tramo_nuevo_no_encadena_contra_el_viejo(self):
        self.pos("2025-01-15")
        self.snap("2026-01-31", 100.0, "cron", fx=1200.0, hold="[]")
        self.snap("2026-08-31", 500.0, "cron", fx=1200.0, hold="[]")
        c = twr.curva_indexada(self.conn, self.uid)
        # El salto ×5 cruza el hueco: no puede convertirse en un +400% de retorno.
        self.assertIsNone(c["curva"][1]["ret"])


class IndeterminadoTest(_Base):
    """La regla explícita: puede sostener UNA LÍNEA, nunca un pico ni un denominador."""
    def _flojo(self):
        return twr.BASE_MERCADO + (twr.INDETERMINADO,)

    def test_indeterminado_no_entra_en_el_nivel_estricto(self):
        self.pos("2025-01-15")
        self.snap("2026-03-15", 100.0, None)      # sin fx, sin holdings, no fin de mes
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["por_clase"][twr.INDETERMINADO], 1)
        self.assertEqual(s["puntos"], [])

    def test_indeterminado_sostiene_linea_pero_no_es_denominador(self):
        self.pos("2025-01-15")
        self.snap("2026-03-15", 1000.0, None)                       # INDETERMINADO
        self.snap("2026-03-20", 2000.0, "cron", fx=1200.0, hold="[]")
        c = twr.curva_indexada(self.conn, self.uid, aceptar=self._flojo())
        self.assertEqual(len(c["puntos"]), 2)                        # está en la línea
        self.assertFalse(c["puntos"][0]["apto"])
        # El ×2 NO se publica como retorno: su v0 no es base de mercado.
        self.assertIsNone(c["curva"][1]["ret"])
        self.assertTrue(c["curva"][1]["estimado"])

    def test_indeterminado_no_puede_ser_pico(self):
        self.pos("2025-01-15")
        self.snap("2026-03-01", 100.0, "cron", fx=1200.0, hold="[]")
        self.snap("2026-03-10", 99999.0, None)                       # pico falso
        self.snap("2026-03-20", 90.0, "cron", fx=1200.0, hold="[]")
        c = twr.curva_indexada(self.conn, self.uid, aceptar=self._flojo())
        # Si el punto no-apto hubiera fijado el pico, el drawdown sería catastrófico.
        self.assertGreater(c["drawdown_maximo"], -0.5)


class SinClampAsimetricoTest(_Base):
    def test_un_mes_de_mas_80_por_ciento_no_se_trunca(self):
        """`Insights.jsx:683` y `evolution.js:317` hacen Math.min(..., 0.5): truncan
        la CARTERA a +50% mensual y no le aplican nada al BENCHMARK. El sesgo va
        siempre en contra del usuario y se compone mes a mes."""
        self.pos("2025-01-15")
        self.snap("2026-01-31", 100.0, "cron", fx=1200.0, hold="[]")
        self.snap("2026-02-28", 180.0, "cron", fx=1200.0, hold="[]")
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["curva"][1]["ret"], 0.80, places=6)
        self.assertAlmostEqual(c["twr"], 0.80, places=6)

    def test_el_piso_de_menos_100_sigue(self):
        self.assertEqual(twr.dietz(100.0, -500.0, 0.0), -1.0)


class SinDatosTest(_Base):
    def test_estado_vacio_trae_el_motivo_redactado(self):
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["puntos"], [])
        self.assertEqual(s["motivo"], "sin_historia")
        self.assertEqual(s["motivo_texto"], twr.MOTIVO_TEXTO["sin_historia"])

    def test_importado_sin_mediciones_dice_por_que(self):
        self.pos("2025-01-15")
        self.snap("2026-06-30", 100.0, "import")
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["motivo"], "importado_sin_mediciones")
        self.assertIn("contables", s["motivo_texto"])


if __name__ == "__main__":
    unittest.main()
