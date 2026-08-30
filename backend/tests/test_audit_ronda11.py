"""Undécima ronda: la base es un DATO ESTAMPADO, no un cálculo de lectura.

Once rondas calcularon la base en tiempo de LECTURA, y cada una encontró un lector
más que se olvidaba de preguntarla. La ronda 10 llegó a poner la decisión en la
MEDIANA de la serie, y eso hizo tres cosas malas a la vez:
  · ASCENDÍA a 'mercado' filas cuyo valor ES el costo (cobertura 0,05 y hasta 0,00),
  · hacía que la respuesta dependiera de QUÉ VENTANA pidió el lector,
  · y reescribía el pasado: un mes nuevo re-etiquetaba meses ya cerrados.

Ahora `snapshots.base` y `snapshots.apto` son columnas: las escribe quien crea la
fila (`twr.base_y_apto_para`) y las lee todo el mundo igual. Este archivo afirma,
uno por uno, los criterios de aceptación de la ronda.
"""
import calendar
import datetime as _d
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr
from reporting import builder


class _Base(unittest.TestCase):
    COSTO = 139570.56
    MERCADO = 73604.02

    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"r11-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IOL','AL30',0,1,100,'2025-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def recon(self, d, v, cov):
        b, a = twr.base_y_apto_para(twr.RECONSTRUIDO, cov)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, holdings_json, base, apto) "
            "VALUES (?,?,?,?,0,'mtm_backfill',?,'[]',?,?)",
            (self.uid, d, float(v), float(v), cov, b, a))
        self.conn.commit()

    def cron(self, d, v):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json, base, apto) "
            "VALUES (?,?,?,?,0,'cron',1200,'[]','mercado',1)",
            (self.uid, d, float(v), float(v)))
        self.conn.commit()

    def sin_estampar(self, d, v, source=None, cov=None, fx=None, hold=None):
        """Una fila como las que ya están en producción: sin `base` ni `apto`."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,?,?,?,?)",
            (self.uid, d, float(v), float(v), source, cov, fx, hold))
        self.conn.commit()

    def mensual(self, y, m, ci, cf):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,0,0,0,0)", (self.uid, y, m, ci, cf))
        self.conn.commit()


class ElEstampoExisteYSeUsaTest(_Base):
    """B-0 · las columnas, la vista y la migración."""

    def test_las_columnas_existen(self):
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(snapshots)")]
        self.assertIn("base", cols)
        self.assertIn("apto", cols)

    def test_la_vista_existe_y_solo_trae_lo_medible(self):
        self.recon("2026-01-31", 1000.0, 0.97)     # apto
        self.recon("2026-02-28", self.COSTO, 0.05)  # no apto
        self.sin_estampar("2026-03-31", 5000.0, source="import")
        twr.estampar_base(self.conn)
        self.conn.commit()
        vista = [r["date"] for r in self.conn.execute(
            "SELECT date FROM snapshots_medibles WHERE user_id=? ORDER BY date", (self.uid,))]
        self.assertEqual(vista, ["2026-01-31"])

    def test_el_indice_esta_y_va_DESPUES_de_la_columna(self):
        """Un CREATE INDEX sobre una columna que todavía no existe tiró producción
        20 minutos el 2026-08-02. El índice se crea después del ALTER, y este test
        afirma que el resultado final es coherente."""
        idx = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='snapshots'")]
        self.assertIn("idx_snapshots_apto", idx)
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(snapshots)")]
        self.assertIn("apto", cols)

    def test_la_migracion_estampa_TAMBIEN_las_filas_legacy(self):
        """No excluir las filas sin `source` fue la trampa de la ronda 3: las fotos
        que el cron escribió antes de que existiera la columna tienen source NULL."""
        for i in range(1, 11):
            self.sin_estampar(f"2026-05-{i:02d}", 1000.0 + i, fx=1200.0)
        r = twr.estampar_base(self.conn)
        self.conn.commit()
        self.assertEqual(r["filas"], 10)
        sin = self.conn.execute(
            "SELECT COUNT(*) c FROM snapshots WHERE user_id=? AND base IS NULL",
            (self.uid,)).fetchone()["c"]
        self.assertEqual(sin, 0)
        # y la cadencia diaria las reconoce como del cron → medibles
        self.assertEqual(len(twr.serie_medible(self.conn, self.uid)["medibles"]), 10)

    def test_los_cuatro_escritores_estampan(self):
        """El contrato de `base_y_apto_para`, que es de donde sacan el estampo los
        cuatro (cron, browser, import, reconstructor)."""
        for clase, cob, esperado in (
                (twr.MEDICION, None, ("mercado", 1)),
                (twr.INTRADIA, None, ("mercado", 0)),
                (twr.RECONSTRUIDO, 0.97, ("mercado", 1)),
                (twr.RECONSTRUIDO, 0.05, ("costo", 0)),
                (twr.RECONSTRUIDO, 0.00, ("costo", 0)),
                (twr.SINTETICO_COSTO, None, ("costo", 0)),
                (twr.INDETERMINADO, None, ("costo", 0))):
            with self.subTest(clase=clase, cobertura=cob):
                self.assertEqual(twr.base_y_apto_para(clase, cob), esperado)


class CeroYCincoNuncaMidenTest(_Base):
    """CRITERIO · Cobertura 0,00 y 0,05 NUNCA pueden ser pico ni denominador, esté
    donde esté la mediana. Es lo que la ronda 10 rompió."""

    def _serie_con(self, cob_mala, cobs_del_resto):
        for i, cob in enumerate(cobs_del_resto):
            self.recon(f"2026-0{i + 1}-28", 100000.0, cob)
        self.recon("2026-07-31", self.COSTO, cob_mala)

    def test_con_la_mediana_alta_tampoco(self):
        self._serie_con(0.05, [0.95, 0.95, 0.95, 0.95])
        s = twr.serie_medible(self.conn, self.uid)
        mala = [p for p in s["medibles"] if p["date"] == "2026-07-31"]
        self.assertEqual(mala, [], "una fila cuyo valor ES el costo entró a medibles")

    def test_cobertura_cero_tampoco(self):
        self._serie_con(0.00, [0.99, 0.99, 0.99, 0.99])
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual([p for p in s["medibles"] if p["date"] == "2026-07-31"], [])

    def test_y_no_puede_fijar_el_pico_ni_el_drawdown(self):
        self.recon("2026-06-25", 100000.0, 0.95)
        self.recon("2026-06-30", self.COSTO, 0.05)     # el pico fabricado
        self.cron("2026-07-05", self.MERCADO)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertNotEqual(c["drawdown_maximo"], -0.472639)
        self.assertNotEqual(c["drawdown_maximo_fecha"], "2026-06-30")


class LaMismaFilaLaMismaRespuestaTest(_Base):
    """CRITERIO · la MISMA fila tiene la MISMA base para todos los lectores, en toda
    ventana, y no cambia cuando llega un mes nuevo."""

    def _cartera(self):
        for m, cob in ((1, 0.88), (2, 0.89), (3, 0.93), (4, 0.99)):
            ult = calendar.monthrange(2026, m)[1]
            self.recon(f"2026-{m:02d}-{ult:02d}", 100000.0 + m, cob)

    def _foto(self, desde=None, hasta=None):
        s = twr.serie_medible(self.conn, self.uid, desde, hasta)
        d = {p["date"]: (p["base"], True) for p in s["medibles"]}
        d.update({p["date"]: (p["base"], False) for p in s["no_medibles"]})
        return d

    def test_no_depende_de_la_ventana(self):
        self._cartera()
        completa = self._foto()
        ventana = self._foto("2026-03-01", "2026-04-30")
        for fecha, val in ventana.items():
            self.assertEqual(val, completa[fecha], f"{fecha} cambió con la ventana")

    def test_no_cambia_cuando_llega_un_mes_nuevo(self):
        self._cartera()
        antes = self._foto()
        self.recon("2026-05-31", 100000.0, 0.60)      # movería la mediana
        despues = self._foto()
        for fecha, val in antes.items():
            self.assertEqual(val, despues[fecha], f"{fecha} se re-etiquetó sola")

    def test_no_cambia_cuando_se_importa_historia_VIEJA(self):
        """CRITERIO · Un mes YA CERRADO no se puede reescribir por importar historia
        vieja. Es el que más duele: un mes cerrado no se autocura nunca."""
        self._cartera()
        antes = self._foto()
        for m in range(1, 13):                        # 12 meses de 2025, cobertura baja
            ult = calendar.monthrange(2025, m)[1]
            self.recon(f"2025-{m:02d}-{ult:02d}", 50000.0, 0.60)
        despues = self._foto()
        for fecha, val in antes.items():
            self.assertEqual(val, despues[fecha], f"{fecha} se reescribió por un import")

    def test_el_mes_cerrado_publica_lo_mismo_antes_y_despues_del_import(self):
        for m, cob in ((3, 0.95), (4, 0.96), (5, 0.93), (6, 0.99)):
            ult = calendar.monthrange(2026, m)[1]
            self.recon(f"2026-{m:02d}-{ult:02d}", 100000.0 + m * 1000, cob)
            self.mensual(2026, m, 100000.0, 100000.0 + m * 1000)
        hoy = _d.date(2026, 9, 15)
        antes = builder.build_period_report(self.conn, self.uid, "month", "2026-06", today=hoy)
        for m in range(1, 13):
            ult = calendar.monthrange(2025, m)[1]
            self.recon(f"2025-{m:02d}-{ult:02d}", 50000.0, 0.60)
        despues = builder.build_period_report(self.conn, self.uid, "month", "2026-06", today=hoy)
        self.assertEqual(antes.headline, despues.headline)
        self.assertEqual(antes.metrics.basis, despues.metrics.basis)
        self.assertEqual(antes.metrics.delta_pct, despues.metrics.delta_pct)

    def test_api_snapshots_responde_igual_con_days_30_y_3650(self):
        """mobile y desktop no se pueden contradecir el mismo día."""
        from fastapi.testclient import TestClient
        for i in range(1, 41):
            self.sin_estampar((_d.date(2026, 6, 1) + _d.timedelta(days=i)).isoformat(),
                              1000.0 + i, fx=1200.0)
        self.recon("2026-05-31", self.COSTO, 0.05)
        twr.estampar_base(self.conn)
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            cli = TestClient(main.app)
            a = {f["date"]: f["apto"] for f in cli.get("/api/snapshots?days=30").json()}
            b = {f["date"]: f["apto"] for f in cli.get("/api/snapshots?days=3650").json()}
        finally:
            main.app.dependency_overrides.clear()
        for fecha in set(a) & set(b):
            self.assertEqual(a[fecha], b[fecha], f"{fecha}: days=30 dice {a[fecha]}")


class LaCurvaNoDesapareceTest(_Base):
    """CRITERIO · Con cobertura 0,61 —la mediana real del padrón— el usuario SIGUE
    VIENDO su curva. La ronda 10 la vaciaba: 12 meses desaparecían del gráfico en
    cuanto hubiera una foto del cron."""

    def test_los_12_meses_al_061_se_siguen_viendo(self):
        for m in range(1, 13):
            ult = calendar.monthrange(2026, m)[1]
            self.recon(f"2026-{m:02d}-{ult:02d}", 10000.0 + m * 250, 0.61)
        for i in range(1, 15):
            self.cron(f"2027-01-{i:02d}", 13000.0 + i * 10)
        for modo in (twr.MODO_CERTERO, twr.MODO_ESTIMADO):
            with self.subTest(modo=modo):
                c = twr.curva_indexada(self.conn, self.uid, modo=modo)
                fechas = {p["date"] for p in c["curva"]}
                faltan = [f"2026-{m:02d}-{calendar.monthrange(2026, m)[1]:02d}"
                          for m in range(1, 13)
                          if f"2026-{m:02d}-{calendar.monthrange(2026, m)[1]:02d}" not in fechas]
                self.assertEqual(faltan, [], f"{modo}: desaparecieron del gráfico")
                # …y siguen sin poder medir
                for p in c["curva"]:
                    if p["base"] == twr.VALUADO_AL_COSTO:
                        self.assertFalse(p["apto"])

    def test_las_dos_bases_no_comparten_segmento(self):
        """Lo que impide leer el salto no es esconder puntos: es que las series no
        se toquen."""
        for m in range(1, 13):
            ult = calendar.monthrange(2026, m)[1]
            self.recon(f"2026-{m:02d}-{ult:02d}", 10000.0 + m * 250, 0.61)
        for i in range(1, 15):
            self.cron(f"2027-01-{i:02d}", 13000.0 + i * 10)
        c = twr.curva_indexada(self.conn, self.uid)
        por_seg = {}
        for p in c["curva"]:
            por_seg.setdefault(p["segmento"], set()).add(p["base"])
        for seg, bases in por_seg.items():
            self.assertEqual(len(bases), 1, f"el segmento {seg} mezcla {bases}")


class NingunLectorPublicaLaBrechaTest(_Base):
    """CRITERIO · Reportes, el informe firmado, /api/goals/cagr, los packets de IA y
    home.py: ninguno publica un % de mercado con una punta al costo. Uno por uno."""

    def _cartera_del_reclamo(self, cobs_altas=True):
        """La del caso 452, y con el resto de la serie en cobertura ALTA — que es lo
        que la mediana usaba para ascender la fila mala."""
        for i, m in enumerate((1, 2, 3)):
            self.recon(f"2026-{m:02d}-28", 100000.0, 0.95 if cobs_altas else 0.20)
        self.recon("2026-06-30", self.COSTO, 0.05)
        for i in range(1, 32):
            self.cron(f"2026-07-{i:02d}", self.MERCADO)
        self.mensual(2026, 6, self.COSTO, self.COSTO)
        self.mensual(2026, 7, self.COSTO, self.COSTO * 1.001)

    def test_reportes_el_mes(self):
        self._cartera_del_reclamo()
        r = builder.build_period_report(self.conn, self.uid, "month", "2026-07",
                                        today=_d.date(2026, 8, 26))
        self.assertNotEqual(r.metrics.basis, "mercado")
        self.assertNotIn("-47", r.headline)
        self.assertNotIn("-47", (r.narrative or ""))

    def test_reportes_el_anio(self):
        for d in ("2025-10-31", "2025-11-30"):
            self.recon(d, 100000.0, 0.95)
        self.recon("2025-12-31", self.COSTO, 0.05)
        for m in range(1, 13):
            ult = calendar.monthrange(2026, m)[1]
            self.cron(f"2026-{m:02d}-14", self.MERCADO)
            self.cron(f"2026-{m:02d}-{ult:02d}", self.MERCADO)
            self.mensual(2026, m, self.COSTO, self.COSTO)
        self.assertIsNone(builder.bordes_mercado_periodo(
            self.conn, self.uid, "2026-01-01", "2026-12-31", "global"))
        r = builder.build_period_report(self.conn, self.uid, "year", "2026",
                                        today=_d.date(2027, 2, 1))
        self.assertNotIn("-47", r.headline)
        self.assertNotEqual(r.metrics.basis, "mercado")

    def test_el_informe_que_firma_el_asesor(self):
        self._cartera_del_reclamo()
        p = main._advisor_report_payload(
            self.conn, self.uid, self.uid, "jul 2026", "2026-07-01", "2026-07-31",
            None, {"name": "x", "matricula": None, "logo": None}, 1200.0, 1250.0)
        import json as _j
        crudo = _j.dumps(p, default=str)
        self.assertNotIn("-47.26", crudo)
        self.assertNotIn("-65966.54", crudo)
        self.assertNotEqual(p.get("base_date"), "2026-06-30")

    def test_api_goals_cagr(self):
        self._cartera_del_reclamo()
        r = main._historical_cagr_global(self.conn, self.uid)
        c = twr.curva_indexada(self.conn, self.uid)
        if c["twr"] is None:
            self.assertIsNone(r.get("cagr"), r)
        else:
            self.assertIsNotNone(r.get("reason") if r.get("cagr") is None else True)

    def test_api_goals_cagr_no_cae_a_la_cadena_contable(self):
        """El fallback a `monthly_entries` publicaba −78,34% el mismo día en que la
        pantalla medía 0,0%. Ahora devuelve el motivo, y el número contable viaja
        con nombre propio."""
        self.recon("2026-06-30", self.COSTO, 0.05)
        self.mensual(2026, 5, 100000.0, 100000.0)
        self.mensual(2026, 6, 100000.0, 20000.0)      # la cadena contable se derrumba
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertIsNone(r.get("cagr"))
        self.assertTrue(r.get("reason"))
        self.assertEqual(r.get("basis"), "contable")

    def test_el_primer_pantallazo_home(self):
        """home.py restaba los dos últimos snapshots y publicaba −47,26% "HOY"."""
        self.recon("2026-06-29", self.COSTO, 0.05)
        self.recon("2026-06-30", self.COSTO, 0.05)
        self.cron("2026-07-01", self.MERCADO)
        filas = self.conn.execute(
            "SELECT date, total_value FROM snapshots_medibles WHERE user_id=? "
            "ORDER BY date DESC LIMIT 2", (self.uid,)).fetchall()
        self.assertEqual(len(filas), 1, "la vista dejó pasar una punta al costo")

    def test_el_packet_del_dashboard(self):
        self.recon("2026-06-29", self.COSTO, 0.05)
        self.cron("2026-07-01", self.MERCADO)
        filas = self.conn.execute(
            "SELECT date, total_value FROM snapshots_medibles WHERE user_id=? "
            "ORDER BY date DESC LIMIT 90", (self.uid,)).fetchall()
        self.assertEqual([r["date"] for r in filas], ["2026-07-01"])

    def test_los_builders_de_ia_de_la_curva(self):
        from ai.builders import insights_drawdown
        self.recon("2026-06-05", self.COSTO, 0.05)
        self.recon("2026-06-15", self.COSTO, 0.05)
        self.cron("2026-07-10", self.MERCADO)
        d = insights_drawdown.build(self.conn, self.uid, window_days=365)
        self.assertNotEqual(d.get("max_pct"), -47.26)
        self.assertNotEqual(d.get("peak_value"), self.COSTO)


class LosGuardsDelAsesorMiranElDatoTest(_Base):
    """B10-7 · filtraban por el STRING `source` y se equivocaban en las dos
    direcciones sobre la misma fila."""

    _WHERE = ("SELECT date FROM snapshots s WHERE s.user_id=? AND "
              "COALESCE(s.apto, CASE WHEN COALESCE(s.source,'') "
              "IN ('import','mtm_backfill') THEN 0 ELSE 1 END) = 1")

    def test_la_fila_legacy_del_import_YA_NO_pasa(self):
        """source NULL, fin de mes, sin fx ni holdings: es la cadena contable, y el
        filtro por string la dejaba pasar."""
        self.sin_estampar("2026-06-30", self.COSTO)
        twr.estampar_base(self.conn)
        self.conn.commit()
        self.assertEqual(self.conn.execute(self._WHERE, (self.uid,)).fetchall(), [])

    def test_una_reconstruccion_BUENA_ya_no_se_rechaza(self):
        """Cobertura 0,99: `es_apto` la acepta y el filtro por string la tiraba."""
        self.recon("2026-06-30", 100000.0, 0.99)
        filas = self.conn.execute(self._WHERE, (self.uid,)).fetchall()
        self.assertEqual([r["date"] for r in filas], ["2026-06-30"])

    def test_y_la_foto_del_cron_legacy_sigue_pasando(self):
        """La trampa de la ronda 3: no se le puede borrar la base al usuario viejo."""
        for i in range(1, 11):
            self.sin_estampar(f"2026-05-{i:02d}", 1000.0, fx=1200.0)
        twr.estampar_base(self.conn)
        self.conn.commit()
        self.assertEqual(len(self.conn.execute(self._WHERE, (self.uid,)).fetchall()), 10)


class ElErrorSigueSiendoInexpresableTest(_Base):
    """B10-12 · la banda `contable` seguía exponiendo el número crudo bajo `value`,
    así que la resta del caso 452 se podía escribir sin un solo KeyError."""

    def test_la_banda_no_expone_value(self):
        self.recon("2026-06-30", self.COSTO, 0.05)
        self.cron("2026-07-10", self.MERCADO)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertTrue(c["contable"])
        for q in c["contable"]:
            self.assertNotIn("value", q)
            self.assertIn("value_no_medible", q)

    def test_no_queda_ninguna_superficie_con_value_en_algo_no_apto(self):
        """El censo: ninguna colección del retorno puede traer `value` en una fila
        que no mide."""
        self.recon("2026-06-30", self.COSTO, 0.05)
        self.cron("2026-07-10", self.MERCADO)
        c = twr.curva_indexada(self.conn, self.uid)
        for nombre in ("medibles", "no_medibles", "curva", "contable"):
            for q in c[nombre]:
                if q.get("apto") is False or nombre == "contable":
                    self.assertNotIn("value", q, f"{nombre}: {q}")


if __name__ == "__main__":
    unittest.main()
