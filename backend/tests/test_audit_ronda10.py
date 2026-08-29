"""Décima ronda: el error tiene que ser INEXPRESABLE, no corregido lector por lector.

Nueve rondas arreglaron `curva_indexada`. El que TODOS leían era `serie_medible`, y
devolvía `puntos`: UNA lista mezclada donde `apto` y `base` eran campos que se podían
no mirar. Mientras se pudiera escribir `p["value"]` sin mirar `p["base"]`, alguien lo
iba a escribir — y lo escribieron cuatro lugares distintos, incluida la pantalla del
reclamo original y el informe que el asesor le firma al cliente.

Esta ronda no agrega el arreglo número diez: cambia la forma del dato.
  · `serie_medible` ya no devuelve `puntos`: devuelve `medibles` y `no_medibles`.
  · un punto que no mide NO trae `value` — trae `value_no_medible`.
Los dos son KeyError, o sea que el uso inseguro no se puede escribir por descuido.
"""
import datetime as _d
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr
from reporting import builder


class _Base(unittest.TestCase):
    COSTO = 139570.56        # la cadena contable — lo que el import fabricó
    MERCADO = 73604.02       # la medición real del cron

    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"r10-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IOL','AL30',0,1,100,'2026-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def recon(self, d, v, cov):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, holdings_json) "
            "VALUES (?,?,?,?,0,'mtm_backfill',?,'[]')", (self.uid, d, float(v), float(v), cov))
        self.conn.commit()

    def cron(self, d, v):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,'cron',1200,'[]')", (self.uid, d, float(v), float(v)))
        self.conn.commit()

    def mensual(self, y, m, ci, cf):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,0,0,0,0)", (self.uid, y, m, ci, cf))
        self.conn.commit()

    def _cartera_del_reclamo(self):
        """La forma exacta del caso 452: la historia reconstruida AL COSTO y después
        un mes entero medido a mercado. La contabilidad se movió +0,1%; el −47,3%
        que se publicaba era la brecha entre las dos formas de medir."""
        for d in ("2026-04-30", "2026-05-31", "2026-06-30"):
            self.recon(d, self.COSTO, 0.05)
        for i in range(1, 32):
            self.cron(f"2026-07-{i:02d}", self.MERCADO)
        self.mensual(2026, 6, self.COSTO, self.COSTO)
        self.mensual(2026, 7, self.COSTO, self.COSTO * 1.001)


class LaFormaNoDejaEscribirElError(_Base):
    """El fix estructural. Si esto se afloja, la ronda 11 vuelve a encontrar
    lectores nuevos."""

    def test_no_existe_mas_la_lista_mezclada(self):
        self.recon("2026-06-30", self.COSTO, 0.05)
        s = twr.serie_medible(self.conn, self.uid)
        with self.assertRaises(KeyError):
            s["puntos"]

    def test_un_punto_que_no_mide_NO_trae_value(self):
        """El corazón: `p["value"]` sobre un punto al costo levanta KeyError, así
        que publicar su número por descuido no se puede escribir."""
        self.recon("2026-06-30", self.COSTO, 0.05)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["medibles"], [])
        self.assertEqual(len(s["no_medibles"]), 1)
        with self.assertRaises(KeyError):
            s["no_medibles"][0]["value"]
        # El número existe, pero hay que NOMBRARLO.
        self.assertAlmostEqual(s["no_medibles"][0]["value_no_medible"], self.COSTO, places=2)
        self.assertAlmostEqual(twr.valor_para_dibujar(s["no_medibles"][0]), self.COSTO, places=2)

    def test_los_medibles_si_traen_value(self):
        self.cron("2026-06-30", 1000.0)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(len(s["medibles"]), 1)
        self.assertAlmostEqual(s["medibles"][0]["value"], 1000.0, places=2)
        self.assertEqual(s["no_medibles"], [])

    def test_y_lo_mismo_en_los_puntos_de_la_curva(self):
        self.recon("2026-06-30", self.COSTO, 0.05)
        c = twr.curva_indexada(self.conn, self.uid)
        for p in c["curva"]:
            if not p["apto"]:
                with self.assertRaises(KeyError):
                    p["value"]


class A1_ReportesTest(_Base):
    """El bug ORIGINAL, en la pantalla del reclamo ORIGINAL, después de 9 rondas."""

    def test_el_mes_no_publica_mercado_con_la_apertura_al_costo(self):
        self._cartera_del_reclamo()
        r = builder.build_period_report(self.conn, self.uid, "month", "2026-07",
                                        today=_d.date(2026, 8, 26))
        m = r.metrics
        self.assertNotEqual(m.basis, "mercado")
        self.assertNotIn("-47", r.headline)
        self.assertNotIn("-47", (r.narrative or ""))
        # el número que queda es el de la contabilidad, que es lo que de verdad
        # se movió: +0,1%
        self.assertAlmostEqual(m.delta_pct, 0.1, places=1)

    def test_no_hay_bordes_de_mercado_si_la_apertura_es_contable(self):
        self._cartera_del_reclamo()
        self.assertIsNone(builder.bordes_mercado_periodo(
            self.conn, self.uid, "2026-07-01", "2026-07-31", "global"))

    def test_el_borde_de_periodo_rechaza_la_foto_al_costo(self):
        self.recon("2026-06-30", self.COSTO, 0.05)
        self.assertIsNone(builder.fetch_snapshot_at_or_before(
            self.conn, self.uid, "2026-06-30", accept=twr.BORDE_PERIODO))

    def test_pero_acepta_una_reconstruccion_a_precio_real(self):
        """La contraprueba: el guard no puede comerse la reconstrucción buena."""
        self.recon("2026-06-30", 1000.0, 0.97)
        b = builder.fetch_snapshot_at_or_before(
            self.conn, self.uid, "2026-06-30", accept=twr.BORDE_PERIODO)
        self.assertIsNotNone(b)

    def test_y_el_chip_de_variacion_legacy_no_se_rompe(self):
        """El guard es estrecho a propósito: una fila INDETERMINADA que el caller
        aceptó explícitamente sigue sirviendo (main.py:31707). Endurecerla acá le
        borraba el chip a los usuarios anteriores a la columna `source`."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited) VALUES (?,'2026-06-15',1000,1000,0)", (self.uid,))
        self.conn.commit()
        b = builder.fetch_snapshot_at_or_before(
            self.conn, self.uid, "2026-06-15",
            accept=(twr.MEDICION, twr.INDETERMINADO))
        self.assertIsNotNone(b)

    def test_el_ANIO_tampoco(self):
        """La misma rama, para el año cerrado. Medido en HEAD con este fixture:
            HEADLINE "Año difícil — -47.3%" · basis='mercado' · delta_pct=-47.26
        El cierre del año TIENE que caer el último día del período o el guard de
        frescura del cierre corta antes y el test pasaría sin probar nada."""
        import calendar
        for d in ("2025-10-31", "2025-11-30", "2025-12-31"):
            self.recon(d, self.COSTO, 0.05)
        for mes in range(1, 13):
            ult = calendar.monthrange(2026, mes)[1]
            self.cron(f"2026-{mes:02d}-14", self.MERCADO)
            self.cron(f"2026-{mes:02d}-{ult:02d}", self.MERCADO)
            self.mensual(2026, mes, self.COSTO, self.COSTO)
        self.assertIsNone(builder.bordes_mercado_periodo(
            self.conn, self.uid, "2026-01-01", "2026-12-31", "global"))
        r = builder.build_period_report(self.conn, self.uid, "year", "2026",
                                        today=_d.date(2027, 2, 1))
        self.assertNotIn("-47", r.headline)
        self.assertNotEqual(r.metrics.basis, "mercado")


class A2_InformeDelAsesorTest(_Base):
    """La superficie donde un número inventado hace más daño: sale firmado."""

    def test_no_firma_un_menos_47_por_un_mes_sin_operaciones(self):
        self._cartera_del_reclamo()
        p = main._advisor_report_payload(
            self.conn, self.uid, self.uid, "jul 2026", "2026-07-01", "2026-07-31",
            None, {"name": "x", "matricula": None, "logo": None}, 1200.0, 1250.0)
        self.assertNotEqual(p.get("ret_pct"), -47.26)
        self.assertNotEqual(round(float(p.get("market_usd") or 0), 2), -65966.54)
        # julio a mercado fue PLANO, y eso es lo que tiene que decir
        self.assertAlmostEqual(float(p.get("ret_pct") or 0), 0.0, places=2)

    def test_la_base_del_informe_nunca_sale_de_una_fila_al_costo(self):
        self._cartera_del_reclamo()
        p = main._advisor_report_payload(
            self.conn, self.uid, self.uid, "jul 2026", "2026-07-01", "2026-07-31",
            None, {"name": "x", "matricula": None, "logo": None}, 1200.0, 1250.0)
        self.assertNotEqual(p.get("base_date"), "2026-06-30")


class A3_GoalsCagrTest(_Base):
    def test_no_publica_un_cagr_de_la_brecha_entre_dos_bases(self):
        self._cartera_del_reclamo()
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertNotEqual(r.get("cagr"), -92.27)
        c = twr.curva_indexada(self.conn, self.uid)
        # y no puede contradecir a la pantalla: si la pantalla mide 0%, el CAGR no
        # puede publicar un derrumbe
        if c["twr"] is not None and abs(c["twr"]) < 1e-9:
            self.assertTrue(r.get("cagr") is None or abs(r["cagr"]) < 1.0, r)


class A4_PacketsDeIATest(_Base):
    def _cartera_452_sin_tramo_medido(self):
        for d in ("2026-06-05", "2026-06-15", "2026-06-25"):
            self.recon(d, self.COSTO, 0.05)
        self.cron("2026-07-10", self.MERCADO)

    def test_no_le_afirma_al_modelo_un_drawdown_de_la_brecha(self):
        from ai.builders import insights_drawdown
        self._cartera_452_sin_tramo_medido()
        d = insights_drawdown.build(self.conn, self.uid, window_days=365)
        self.assertNotEqual(d.get("max_pct"), -47.26)
        self.assertNotEqual(d.get("peak_value"), self.COSTO)
        self.assertIsNone(d.get("max_pct"))          # la pantalla dice "—"; el packet también

    def test_dashboard_evolution_tampoco(self):
        from ai.builders import dashboard_evolution
        self._cartera_452_sin_tramo_medido()
        e = dashboard_evolution.build(self.conn, self.uid)
        self.assertNotEqual(e.get("delta_pct"), -0.4726)
        self.assertNotEqual(e.get("value_start"), 139571)


class B1_CoberturaOscilanteTest(_Base):
    """El caso NORMAL de la reconstrucción, con la mediana real del padrón en 0,614."""

    def test_la_cartera_que_gano_30_LA_VE_pero_no_la_publica(self):
        """⚠️ RONDA 11 · ESTE TEST AFIRMABA EL COMPORTAMIENTO DE LA MEDIANA, Y LA
        MEDIANA SE FUE. Ver `test_la_cartera_que_gano_30_por_ciento_paga_el_precio`
        en test_audit_ronda9.py: la mediana arreglaba este dibujo y a cambio
        ascendía a 'mercado' filas cuyo valor ES el costo (0,05 y hasta 0,00), con
        lo que volvían el pico fabricado y el −47,26% del informe firmado.

        Lo que NO se negocia y este test sigue afirmando: el usuario ve sus 7
        puntos. Lo que se perdió: la línea no cuenta la historia completa.
        """
        for d, v, cob in (("2026-01-31", 10000, 0.95), ("2026-02-28", 10500, 0.93),
                          ("2026-03-31", 11000, 0.88), ("2026-04-30", 11500, 0.91),
                          ("2026-05-31", 12000, 0.94), ("2026-06-30", 12500, 0.87),
                          ("2026-07-31", 13000, 0.92)):
            self.recon(d, float(v), cob)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(c["curva"]), 7, "los 7 puntos se siguen viendo")
        # y ninguna fila bajo el piso quedó apta, esté donde esté la mediana
        for p in c["curva"]:
            self.assertEqual(p["apto"], p["base"] == twr.VALUADO_A_MERCADO)

    def test_una_reconstruccion_mala_sigue_sin_medir(self):
        """El otro lado: la mediana manda, y con 0,05 no mide nada."""
        for d, v in (("2026-01-31", 10000), ("2026-02-28", 11000)):
            self.recon(d, float(v), 0.05)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertIsNone(c["twr"])
        self.assertEqual([p["base"] for p in c["curva"]], [twr.VALUADO_AL_COSTO] * 2)
        # …pero la DIBUJA con su forma real (lo que ganó la ronda 7)
        self.assertAlmostEqual(c["curva"][-1]["index"], 1.10, places=4)


class B2_ElAnclaEsDeLaMismaBaseTest(_Base):
    def test_un_punto_al_costo_en_el_medio_no_borra_lo_medido(self):
        """Regresión de la ronda 9: `ancla_dib` era el punto ANTERIOR, así que una
        fila contable en el medio reseteaba el índice dibujado y borraba del gráfico
        el rendimiento ya medido."""
        self.cron("2026-06-01", 10000.0)
        self.cron("2026-06-05", 10500.0)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,'2026-06-10',99999,99999,0,'import')",
            (self.uid,))
        self.conn.commit()
        self.cron("2026-06-15", 11000.0)
        self.cron("2026-06-20", 11500.0)
        c = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        mercado = [p for p in c["curva"] if p["base"] == twr.VALUADO_A_MERCADO]
        self.assertEqual(len({p["segmento"] for p in mercado}), 1)
        self.assertAlmostEqual(mercado[-1]["index"], 1.15, places=4)
        self.assertAlmostEqual(c["twr"], 0.15, places=6)


class B3_SinYuxtaponerDosBasesTest(_Base):
    def test_la_curva_no_pone_dos_bases_en_el_mismo_eje(self):
        """El rebase deja a cada base arrancando en 0%: una cadena contable que
        terminó en −40% y una primera medición dibujada en 0% se leen como +66,7%
        de recuperación que nadie vivió."""
        self.recon("2026-01-31", 10000.0, 0.05)
        self.recon("2026-02-28", 6000.0, 0.05)      # la contabilidad "cae" 40%
        self.cron("2026-03-10", 5000.0)
        c = twr.curva_indexada(self.conn, self.uid)
        # ⚠️ RONDA 11 · las dos bases se DIBUJAN (esconder puntos le borraba la
        # historia al 61% del padrón), pero en SEGMENTOS distintos y cada una
        # rebaseada en 1,0. Lo que impide leer el salto es que no se tocan.
        self.assertEqual(len(c["curva"]), 3)
        contables = [p for p in c["curva"] if p["base"] == twr.VALUADO_AL_COSTO]
        mercado = [p for p in c["curva"] if p["base"] == twr.VALUADO_A_MERCADO]
        self.assertEqual(len(contables), 2)
        self.assertEqual(len(mercado), 1)
        self.assertNotEqual(contables[-1]["segmento"], mercado[0]["segmento"])
        # la medición arranca su propia cadena en 1,0 — no "recupera" un −40%
        self.assertAlmostEqual(mercado[0]["index"], 1.0, places=6)
        # y lo contable sigue también en su propio panel, en dólares crudos
        self.assertEqual([q["date"] for q in c["contable"]],
                         ["2026-01-31", "2026-02-28"])

    def test_sin_ninguna_medicion_la_contable_SI_se_dibuja(self):
        """Lo que ganó la ronda 7 y no se toca: sin nada que medir, la cadena
        contable es lo único que el usuario tiene. Ahí no hay con qué yuxtaponerla."""
        for d, v in (("2026-01-31", 1000.0), ("2026-02-28", 1200.0), ("2026-03-31", 1100.0)):
            self.recon(d, v, 0.55)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual([round(p["index"], 4) for p in c["curva"]], [1.0, 1.2, 1.1])
        self.assertIsNone(c["twr"])


class B7_ElPuntoLiveTest(_Base):
    def test_viaja_con_base_y_segmento(self):
        for i in range(1, 20):
            self.cron(f"2026-07-{i:02d}", 10000.0 + i * 100)
        c = twr.curva_indexada(self.conn, self.uid, valor_live=12000.0)
        hoy = [p for p in c["curva"] if p["date"] == "hoy"]
        self.assertEqual(len(hoy), 1)
        self.assertEqual(hoy[0]["base"], twr.VALUADO_A_MERCADO)
        self.assertIsNotNone(hoy[0].get("segmento"))


if __name__ == "__main__":
    unittest.main()


class ElBarridoEncontroDosMasTest(_Base):
    """El re-barrido que pide el criterio: `serie_medible` ya no deja escribir el
    error, pero hay lectores que van a `snapshots` DIRECTO. Éstos dos restan un
    valor VIVO (mercado) contra "el último snapshot" sin preguntar en qué base
    está — o sea el mismo defecto que A-2, en otras dos superficies del asesor."""

    def _cliente_reconstruido_sin_cron(self):
        """Sin una sola foto del cron: su último snapshot es la reconstrucción."""
        self.recon("2026-06-30", self.COSTO, 0.05)

    def test_el_brief_del_asesor_no_toma_una_foto_al_costo_de_base(self):
        import advisor_brief  # noqa: F401  (importable = la query se puede leer)
        self._cliente_reconstruido_sin_cron()
        base = self.conn.execute(
            """SELECT s.total_value FROM snapshots s
                WHERE s.user_id = ? AND s.date < '2026-08-26'
                  AND COALESCE(s.source,'') NOT IN ('import','mtm_backfill')
                  AND s.date = (SELECT MAX(s2.date) FROM snapshots s2
                                WHERE s2.user_id = s.user_id AND s2.date < '2026-08-26'
                                  AND COALESCE(s2.source,'') NOT IN ('import','mtm_backfill'))""",
            (self.uid,)).fetchone()
        self.assertIsNone(base, "la foto al costo no puede ser base de un % contra live")

    def test_pero_una_medicion_del_cron_SI_sirve_de_base(self):
        self.cron("2026-06-30", 1000.0)
        base = self.conn.execute(
            """SELECT s.total_value FROM snapshots s
                WHERE s.user_id = ? AND s.date < '2026-08-26'
                  AND COALESCE(s.source,'') NOT IN ('import','mtm_backfill')
                  AND s.date = (SELECT MAX(s2.date) FROM snapshots s2
                                WHERE s2.user_id = s.user_id AND s2.date < '2026-08-26'
                                  AND COALESCE(s2.source,'') NOT IN ('import','mtm_backfill'))""",
            (self.uid,)).fetchone()
        self.assertIsNotNone(base)
        self.assertAlmostEqual(float(base["total_value"]), 1000.0, places=2)

    def test_y_una_fila_LEGACY_sin_source_sigue_sirviendo(self):
        """La trampa de la ronda 3: las fotos del cron anteriores a la columna
        `source` la tienen en NULL. Excluir por `source IS NOT NULL` les borraría
        la base a los usuarios viejos."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, fx_to_usd_blue) VALUES (?,'2026-06-30',1000,1000,0,1200)",
            (self.uid,))
        self.conn.commit()
        base = self.conn.execute(
            """SELECT s.total_value FROM snapshots s
                WHERE s.user_id = ? AND s.date < '2026-08-26'
                  AND COALESCE(s.source,'') NOT IN ('import','mtm_backfill')""",
            (self.uid,)).fetchone()
        self.assertIsNotNone(base)
