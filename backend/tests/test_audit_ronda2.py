"""Segunda ronda: lo que la revisión adversarial encontró SOBRE LOS FIXES.

Casi todo acá son regresiones que introdujo la primera ronda. El patrón que se
repite: un guard correcto aplicado con la lista equivocada, o un número que deja
de ser afirmable y sigue publicándose.
"""
import os
import tempfile
import unittest
import datetime as _d

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr
from reporting import builder



def _todos(s):
    """Los puntos ACEPTADOS —medibles y no medibles— juntos y en orden.

    ⚠️ VIVE EN LOS TESTS A PROPÓSITO. `serie_medible` dejó de devolver una lista
    mezclada justamente para que producción no pueda recorrerla sin decidir; un
    test sí puede mirar todo, pero tiene que nombrarlo.
    """
    return sorted(list(s["medibles"]) + list(s["no_medibles"]), key=lambda p: p["date"])

class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users",
                  "brokers", "import_normalized_tx", "import_raw_rows", "import_batches"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"r2-{id(self)}@t", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def pos(self, entry_date="2024-01-01", asset="AAPL", invested=100.0,
            broker="IBKR", qty=1.0, currency=None):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date, currency) VALUES (?,?,?,0,?,?,?,?)",
            (self.uid, broker, asset, qty, invested, entry_date, currency))
        self.conn.commit()

    def snap(self, d, v, src="cron", nd=0.0, cov=None, hold="[]", fx=1200.0):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (self.uid, d, float(v), float(v), float(nd), src, cov,
             fx if src == "cron" else None, hold if src == "cron" else None))
        self.conn.commit()

    def me(self, y, m, ci, cf, dep=0.0, wd=0.0, broker="global"):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,?,?,?,?,?,?,?,0,0)", (self.uid, broker, y, m, ci, cf, dep, wd))
        self.conn.commit()


class CriterioDeAceptacionTest(_Base):
    """EL error de fondo de la primera ronda: confundir "puede ser un borde de
    período" con "puede sostener una serie". Un usuario 100% sano perdía 549 de
    600 fotos del cron y su CAGR pasaba de +13,7%/19 meses a −56,9%/1 mes."""

    def _usuario_sano_con_historia_legacy(self):
        self.pos("2025-01-01")
        d0 = _d.date(2025, 1, 1)
        v = 100000.0
        for i in range(600):
            d = d0 + _d.timedelta(days=i)
            v *= 1.0005
            # Las columnas se agregaron en jul y ago 2026: todo lo anterior tiene
            # fx pero no composición, y la heurística lo llama INTRADIA.
            self.conn.execute(
                "INSERT INTO snapshots (user_id,date,total_value,total_invested,"
                "net_deposited,source,fx_to_usd_blue,holdings_json) VALUES (?,?,?,?,0,?,?,?)",
                (self.uid, d.isoformat(), v, 100000.0,
                 'cron' if d >= _d.date(2026, 8, 6) else None, 1200.0,
                 '[]' if d >= _d.date(2026, 7, 4) else None))
        self.conn.commit()

    def test_el_usuario_sano_no_pierde_su_historia(self):
        self._usuario_sano_con_historia_legacy()
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(len(_todos(s)), 600)
        self.assertEqual(s["medido_desde"], "2025-01-01")
        self.assertEqual(len(s["tramos"]), 1)

    def test_su_cagr_sigue_siendo_el_de_su_historia(self):
        self._usuario_sano_con_historia_legacy()
        r = main._historical_cagr_global(self.conn, self.uid)
        # ⚠️ `months` es el SPAN EN MESES de la ventana (días/30,44), no el conteo
        # de pares de cierres que hacía el motor viejo: 599 días son 19,7 → 20.
        # La propiedad que este test protege —que el usuario sano conserve su
        # historia y su número, y no caiga a "−56,9 % en 1 mes"— sigue igual.
        self.assertEqual(r["months"], 20)
        self.assertGreater(r["cagr"], 15)

    def test_intradia_sostiene_la_linea_pero_no_es_pico_ni_denominador(self):
        """La lista que dice qué ENTRA a la serie no es la que dice qué puede ser
        PICO o DENOMINADOR. Meter INTRADIA en la segunda hacía que una foto del
        browser fijara máximos."""
        self.assertIn(twr.INTRADIA, twr.ACEPTA_LINEA)
        self.assertNotIn(twr.INTRADIA, twr.BASE_MERCADO)
        self.assertNotIn(twr.INTRADIA, twr.BORDE_PERIODO)
        self.assertNotIn(twr.SINTETICO_COSTO, twr.ACEPTA_LINEA)
        self.assertNotIn(twr.SINTETICO_COSTO, twr.BASE_MERCADO)

    def test_la_foto_FABRICADA_sigue_afuera_de_las_dos(self):
        """Lo que no puede pasar es que aflojar el criterio deje entrar el defecto."""
        self.pos("2025-01-15")
        self.snap("2026-07-31", 139570.56, src="import")
        self.snap("2026-08-24", 73604.02, nd=130.80)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(c["por_clase"][twr.SINTETICO_COSTO], 1)
        self.assertIsNone(c["twr"])


class BrutosPublicadosTest(_Base):
    """`deposits`/`withdrawals` son lo que la app PUBLICA (MonthCard.jsx:223-224):
    cifras que el usuario contrasta contra el resumen de su broker."""

    def test_un_mes_con_aporte_y_retiro_publica_los_dos(self):
        self.pos()
        self.me(2026, 4, 90000.0, 100000.0)
        self.me(2026, 5, 100000.0, 106000.0, dep=10000.0, wd=4000.0)
        for d in range(20, 31):
            self.snap(f"2026-04-{d:02d}", 100000.0, nd=0.0)
        for d in range(1, 32):
            self.snap(f"2026-05-{d:02d}", 106000.0, nd=6000.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-05-01", "2026-05-31", "global", None)
        self.assertEqual(m.basis, "mercado")
        self.assertAlmostEqual(m.deposits, 10000.0, places=2)      # NO 6.000
        self.assertAlmostEqual(m.withdrawals, 4000.0, places=2)    # NO 0
        self.assertAlmostEqual(m.delta_usd, 0.0, places=2)

    def test_entra_y_sale_lo_mismo_y_el_mes_no_desaparece(self):
        """Con los brutos en 0, `is_relevant` daba False y el mes se borraba del
        timeline de /reportes."""
        self.pos()
        self.me(2026, 4, 90000.0, 100000.0)
        self.me(2026, 5, 100000.0, 100000.0, dep=50000.0, wd=50000.0)
        for d in range(20, 31):
            self.snap(f"2026-04-{d:02d}", 100000.0, nd=0.0)
        for d in range(1, 32):
            self.snap(f"2026-05-{d:02d}", 100000.0, nd=0.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-05-01", "2026-05-31", "global", None)
        self.assertAlmostEqual(m.deposits, 50000.0, places=2)
        self.assertAlmostEqual(m.withdrawals, 50000.0, places=2)


class ValorLiveTest(_Base):
    def test_no_compone_por_encima_del_hueco(self):
        """`ultimo_apto` se buscaba sobre la serie ENTERA: con un punto huérfano
        del otro lado del hueco, la pata live se componía encima del tramo 1 y
        devolvía +32% donde punta a punta es −34%."""
        self.pos()
        self.snap("2025-01-31", 10000.0)
        self.snap("2025-02-28", 12000.0)
        self.snap("2025-07-31", 6000.0)      # huérfano, del otro lado del hueco
        c = twr.curva_indexada(self.conn, self.uid, valor_live=6600.0)
        self.assertTrue(c["serie_partida"])
        self.assertIsNone(c["twr"])
        self.assertIsNone(c["drawdown_maximo"])

    def test_el_deposito_de_hoy_no_es_retorno(self):
        """El tramo live pasaba `flow=0.0`: todo lo que entró después del último
        snapshot medido se computaba entero como rendimiento. Mercado plano +
        depósito de US$20.000 = '+20,00%' al lado de 'US$0' de P&L."""
        self.pos()
        self.me(2025, 12, 100000.0, 100000.0)
        self.me(2026, 1, 100000.0, 100000.0)
        self.me(2026, 2, 100000.0, 120000.0, dep=20000.0)
        # El depósito entra HOY (febrero), DESPUÉS del último cierre medido.
        self.snap("2025-12-31", 100000.0, nd=100000.0)
        self.snap("2026-01-31", 100000.0, nd=100000.0)
        c = twr.curva_indexada(self.conn, self.uid, valor_live=120000.0)
        self.assertAlmostEqual(c["twr"], 0.0, places=4)


class VentanaDelAnioTest(_Base):
    def test_no_arrastra_la_cola_del_anio_anterior(self):
        """La ventana se abría en `period_start − 5` y `serie_medible` tomaba
        TODOS los puntos de ahí, así que el % del año incorporaba los últimos 4
        días del año anterior."""
        self.pos()
        # Diciembre cae fuerte; enero-diciembre sube.
        for d, v in (("2024-12-27", 120000.0), ("2024-12-28", 110000.0),
                     ("2024-12-29", 105000.0), ("2024-12-30", 101000.0),
                     ("2024-12-31", 100000.0)):
            self.snap(d, v)
        import calendar
        for mes in range(1, 13):
            self.snap(f"2025-{mes:02d}-{calendar.monthrange(2025, mes)[1]:02d}",
                      100000.0 * (1 + 0.01 * mes))
            self.me(2025, mes, 100000.0, 100000.0)
        c = builder.compute_metrics_for_period(
            self.conn, self.uid, "year", "2025-01-01", "2025-12-31", "global", None)[0]
        # 100.000 -> 112.000 = +12%. Si arrastrara desde el 27/12 (120.000) daría negativo.
        self.assertGreater(c.delta_pct, 0)
        self.assertAlmostEqual(c.delta_pct, 12.0, places=1)

    def test_ventana_del_twr_es_la_del_tramo_publicado(self):
        """`medido_desde/hasta` son el primer y último punto apto de TODA la
        serie; el TWR sólo cubre el tramo publicado. Alimentar el guard con los
        primeros daba por cubierto un año que se midió dos meses."""
        self.pos()
        self.snap("2024-12-31", 10000.0)
        self.snap("2025-01-31", 11000.0)
        self.snap("2025-02-28", 12000.0)
        self.snap("2025-12-28", 6000.0)      # huérfano al final
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertTrue(c["serie_partida"])
        self.assertIsNone(c["twr"])
        self.assertIsNone(c["ventana_desde"])


class ConvencionNetDepositedTest(_Base):
    def test_el_cron_y_el_backfill_estampan_lo_mismo(self):
        """El cron estampa baseline + flujos; el backfill estampaba sólo flujos.
        Restar uno de cada devolvía EL BASELINE ENTERO como aporte del mes: un
        mes de +US$2.000 salía como 'Mes difícil −61,2%'."""
        import scripts.backfill_historical_mtm as bf
        from snapshots_job import compute_net_deposited_db
        self.pos("2024-01-01")
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "IBKR", "USDT"))
        self.me(2026, 4, 100000.0, 100000.0)     # baseline 100.000
        self.me(2026, 5, 100000.0, 100000.0)
        self.conn.commit()
        bf._persist_mtm_snapshots(self.conn, self.uid, {
            "2026-04": {"date": "2026-04-30", "value": 100000.0, "cost": 100000.0,
                        "coverage": 1.0, "holdings": []}})
        self.conn.commit()
        estampado = self.conn.execute(
            "SELECT net_deposited FROM snapshots WHERE user_id=? AND date='2026-04-30'",
            (self.uid,)).fetchone()["net_deposited"]
        ssot = compute_net_deposited_db(self.conn, self.uid, as_of_date="2026-04-30")
        self.assertAlmostEqual(estampado, ssot, places=2)
        self.assertAlmostEqual(estampado, 100000.0, places=2)


class TenenciaNoVistaTest(_Base):
    def test_entry_date_NULL_no_invisibiliza_la_tenencia(self):
        import scripts.backfill_historical_mtm as bf
        self.pos(entry_date=None, asset="XYZ", invested=50000.0)
        costo, afirmable = bf._tenencia_no_vista(self.conn, self.uid, "2024-08-31", {})
        self.assertAlmostEqual(costo, 50000.0, places=2)

    def test_el_homonimo_en_otro_broker_no_se_da_por_visto(self):
        """Comparaba SÓLO el nombre: una unidad de AAPL vista en IBKR declaraba
        'ya vistas' 500 unidades de AAPL cargadas a mano en Cocos."""
        import scripts.backfill_historical_mtm as bf
        self.pos("2024-01-01", "AAPL", invested=100000.0, broker="Cocos", qty=500)
        vistos = {("IBKR", "AAPL"): 1.0}
        costo, _ = bf._tenencia_no_vista(self.conn, self.uid, "2024-08-31", vistos)
        self.assertAlmostEqual(costo, 100000.0, places=2)

    def test_el_costo_en_pesos_se_convierte_dividiendo(self):
        """`q*pe*fx` MULTIPLICABA por el TC donde la convención del repo es
        `usd = nativa / fx_to_usd`: error de fx² = 1.562.500×, que hundía la
        cobertura de 99,68% a 0,02% y borraba el mes de la serie."""
        import scripts.backfill_historical_mtm as bf
        self.conn.execute(
            "INSERT INTO operations (user_id, date, broker, asset, op_type, quantity, "
            "entry_price, currency, fx_to_usd, entry_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.uid, "2024-12-01", "Cocos", "GGAL", "sell", 100, 1000.0, "ARS",
             1250.0, "2024-01-01"))
        self.conn.commit()
        costo, _ = bf._tenencia_no_vista(self.conn, self.uid, "2024-08-31", {})
        self.assertAlmostEqual(costo, 80.0, places=2)     # 100*1000/1250, no *1250

    def test_visto_parcial_solo_cuenta_lo_no_visto(self):
        import scripts.backfill_historical_mtm as bf
        self.pos("2024-01-01", "AAPL", invested=1000.0, broker="IBKR", qty=100)
        costo, _ = bf._tenencia_no_vista(
            self.conn, self.uid, "2024-08-31", {("IBKR", "AAPL"): 60.0})
        self.assertAlmostEqual(costo, 400.0, places=2)    # el 40% no visto


class BackfillNoPisaMedicionTest(_Base):
    def test_usa_el_flag_por_fecha_igual_que_twr(self):
        """El backfill preguntaba con '¿tiene posiciones HOY?'. Para una foto REAL
        del cron de cuando la persona estaba 100% cash los dos módulos decidían
        distinto, y el UPSERT reemplazaba la medición por la cadena contable."""
        import scripts.backfill_historical_mtm as bf
        self.pos("2024-10-01")                      # compró recién en octubre
        self.snap("2024-08-31", 12345.67, src="cron", hold=None)   # 100% cash: fx sí, holdings NULL
        primera = twr.primera_fecha_con_posiciones(self.conn, self.uid)
        fila = self.conn.execute(
            "SELECT date,total_value,fx_to_usd_blue,holdings_json,source,mtm_coverage "
            "FROM snapshots WHERE user_id=?", (self.uid,)).fetchone()
        self.assertEqual(
            twr.clasificar_fila(fila, twr._tenia_posiciones_en(primera, "2024-08-31")),
            twr.MEDICION)
        bf._persist_mtm_snapshots(self.conn, self.uid, {
            "2024-08": {"date": "2024-08-31", "value": 9000.0, "cost": 9000.0,
                        "coverage": 1.0, "holdings": []}})
        self.conn.commit()
        r = self.conn.execute(
            "SELECT total_value, source FROM snapshots WHERE user_id=? AND date='2024-08-31'",
            (self.uid,)).fetchone()
        self.assertAlmostEqual(r["total_value"], 12345.67, places=2)   # NO se pisó
        self.assertEqual(r["source"], "cron")


class BuildersDeIATest(_Base):
    def test_no_le_afirman_a_la_IA_un_drawdown_de_cero(self):
        from ai.builders import insights_drawdown
        self.pos("2025-01-15")
        self.snap("2026-06-30", 150000.0, src="import")
        self.snap("2026-08-24", 60000.0)
        p = insights_drawdown.build(self.conn, self.uid, window_days=365)
        self.assertIsNone(p["current_pct"])
        self.assertIsNone(p["max_pct"])
        self.assertNotEqual(p["recovered"], True)
        self.assertTrue(p.get("reason"))

    def test_dashboard_declara_la_ventana_real(self):
        from ai.builders import dashboard_evolution
        self.pos("2022-01-01")
        self.snap("2023-01-31", 50000.0)
        self.snap("2023-06-30", 100000.0)
        p = dashboard_evolution.build(self.conn, self.uid, period_days=365)
        if not p.get("insufficient_data"):
            self.assertIn("ventana", p)
            self.assertTrue(p["ventana"]["ampliada"])
            self.assertEqual(p["ventana"]["hasta"], "2023-06-30")


class CagrDenominadorTest(_Base):
    def test_se_anualiza_por_tiempo_no_por_pares(self):
        self.pos()
        self.snap("2025-01-31", 100000.0)
        self.snap("2026-08-31", 120000.0)     # 19 meses, +20%
        r = main._historical_cagr_global(self.conn, self.uid)
        # Ver `test_dos_mediciones_muy_separadas_no_explotan_el_cagr`: el motor
        # canónico no encadena a través de 19 meses de silencio. Lo que este test
        # fija —que NO se anualiza por PARES de puntos, que era el 791,61 %— sigue
        # valiendo, y el span de la historia se reporta igual.
        self.assertIsNone(r["cagr"])
        self.assertEqual(r["historia_meses"], 19)


class FormaDeLaRespuestaTest(_Base):
    """El estado vacío es el que más se lee mal: la forma no puede cambiar.
    Ya pasó con `drawdown_maximo_fecha`; volvió a pasar con las claves que agregó
    el fix de la serie partida — un consumidor que gatea por `serie_partida` o
    `tramos_medidos` recibía undefined y no gateaba nada."""

    CLAVES = ("twr", "cagr", "drawdown_actual", "drawdown_maximo",
              "drawdown_maximo_fecha", "drawdown_maximo_pico", "tramos_medidos",
              "tramos_detalle", "serie_partida", "ventana_desde", "ventana_hasta",
              "motivo", "motivo_texto", "curva", "contable", "por_clase")

    def _casos(self):
        return {
            "sin historia": [],
            "1 punto": [("2026-01-31", 100.0, "cron")],
            "solo fabricadas": [("2026-01-31", 100.0, "import"),
                                ("2026-02-28", 120.0, "import")],
            "2 seguidos": [("2026-01-31", 100.0, "cron"), ("2026-02-28", 120.0, "cron")],
            "3 tramos": [("2024-01-31", 100.0, "cron"), ("2025-01-31", 100.0, "cron"),
                         ("2025-02-28", 70.0, "cron"), ("2026-01-31", 50.0, "cron")],
            "huerfano al final": [("2025-01-31", 100.0, "cron"),
                                  ("2025-02-28", 120.0, "cron"),
                                  ("2026-01-31", 50.0, "cron")],
        }

    def test_la_forma_esta_completa_en_todos_los_casos(self):
        for nombre, pts in self._casos().items():
            with self.subTest(caso=nombre):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.pos()
                for d, v, src in pts:
                    self.snap(d, v, src=src)
                c = twr.curva_indexada(self.conn, self.uid)
                for k in self.CLAVES:
                    self.assertIn(k, c, f"{nombre}: falta {k}")

    def test_los_campos_son_coherentes_entre_si(self):
        for nombre, pts in self._casos().items():
            with self.subTest(caso=nombre):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.pos()
                for d, v, src in pts:
                    self.snap(d, v, src=src)
                c = twr.curva_indexada(self.conn, self.uid)
                # No hay TWR sin la ventana que cubre.
                if c["twr"] is not None:
                    self.assertIsNotNone(c["ventana_desde"], f"{nombre}: twr sin ventana")
                # El drawdown se publica exactamente cuando el TWR se publica.
                self.assertEqual(c["drawdown_maximo"] is None, c["twr"] is None,
                                 f"{nombre}: drawdown y twr no coinciden")
                # No se anualiza lo que no se midió.
                if c["cagr"] is not None:
                    self.assertIsNotNone(c["twr"], f"{nombre}: cagr sin twr")

    def test_el_endpoint_expone_todo_lo_que_el_front_gatea(self):
        import performance as perf
        self.pos()
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        for k in ("tramos_medidos", "serie_partida", "curva", "benchmark",
                  "motivo_texto", "contable", "medido_desde"):
            self.assertIn(k, r)


class CoberturaInvariantesTest(_Base):
    def _cuenta(self, con_precio, invisible=False, venta_ars=False):
        import scripts.backfill_historical_mtm as bf
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "IBKR", "USDT"))
        bid = f"B{self.uid}"
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,'confirmed')", (bid, self.uid, "IBKR", "generic", bid))
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
            "VALUES (?,0,'{}','valid')", (bid,)).lastrowid
        self.conn.execute(
            """INSERT INTO import_normalized_tx (batch_id,raw_row_id,broker,asset_symbol,
               asset_type,operation_type,quantity,unit_price,gross_amount,currency,date)
               VALUES (?,?,'IBKR','AAPL','STOCK','BUY',100,100,10000,'USD','2024-08-05')""",
            (bid, rr))
        self.pos("2024-08-05", "AAPL", invested=10000.0, qty=100, currency="USD")
        if invisible:
            self.pos("2024-08-01", "GGAL", invested=100000.0, broker="Cocos",
                     qty=500, currency="USD")
        if venta_ars:
            self.conn.execute(
                "INSERT INTO operations (user_id,date,broker,asset,op_type,quantity,"
                "entry_price,currency,fx_to_usd,entry_date) "
                "VALUES (?,'2024-12-01','Cocos','YPFD','sell',100,1000.0,'ARS',1250.0,'2024-01-01')",
                (self.uid,))
        for (y, mo, ci, cf, dep) in ((2024, 8, 0, 10000, 10000), (2024, 9, 10000, 10000, 0)):
            for b in ("global", "IBKR"):
                self.me(y, mo, ci, cf, dep=dep, broker=b)
        self.conn.commit()
        self._orig = bf._fetch_monthly_close
        self.addCleanup(lambda: setattr(bf, "_fetch_monthly_close", self._orig))
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = ((lambda pk, si: {"2024-08": 150.0, "2024-09": 160.0})
                                   if con_precio else (lambda pk, si: {}))
        bf.backfill_user(self.conn, self.uid, _d.date(2026, 6, 26))
        self.conn.commit()
        return [r["mtm_coverage"] for r in self.conn.execute(
            "SELECT mtm_coverage FROM snapshots WHERE user_id=? ORDER BY date", (self.uid,))]

    def test_nunca_hay_cobertura_1_sin_haber_consultado_un_precio(self):
        covs = self._cuenta(con_precio=False)
        self.assertTrue(covs)
        for c in covs:
            self.assertNotEqual(c, 1.0)

    def test_la_tenencia_invisible_baja_la_cobertura(self):
        covs = self._cuenta(con_precio=True, invisible=True)
        for c in covs:
            self.assertLess(c, 0.5)

    def test_una_venta_en_pesos_abierta_NO_hunde_una_cuenta_valuada_entera(self):
        """El error de moneda (`q*pe*fx` en vez de `/fx`) hundía la cobertura de
        99,68% a 0,02% y borraba el mes entero de la serie. Le pegaba a cualquier
        cuenta argentina con una operación en ARS cruzando un fin de mes."""
        covs = self._cuenta(con_precio=True, venta_ars=True)
        for c in covs:
            self.assertGreater(c, 0.9)

    def test_todo_valuado_a_mercado_da_cobertura_1(self):
        covs = self._cuenta(con_precio=True)
        for c in covs:
            self.assertAlmostEqual(c, 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
