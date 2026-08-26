"""Los 5 bloqueantes de la auditoría, cada uno con su repro.

Ninguno de estos escenarios estaba cubierto: los tests de
`test_reportes_base_mercado.py` corrían todos SIN aportes, y el de la serie
partida sólo miraba que no encadenara — no que no publicara un número.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr
from reporting import builder


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users",
                  "brokers", "import_normalized_tx", "import_raw_rows", "import_batches"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        # Email único por test: `DELETE FROM users` puede no correr si la tabla
        # tiene dependencias, y ahí el INSERT choca contra el UNIQUE.
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"aud-{id(self)}@t", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def pos(self, entry_date="2024-01-01", asset="AAPL", invested=100.0):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,?,?)",
            (self.uid, "IBKR", asset, invested, entry_date))
        self.conn.commit()

    def snap(self, d, v, src="cron", nd=0.0, cov=None):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (self.uid, d, float(v), float(v), float(nd), src, cov,
             1200.0 if src == "cron" else None, "[]" if src == "cron" else None))
        self.conn.commit()

    def me(self, y, m, ci, cf, dep=0.0, wd=0.0, rz=0.0, broker="global"):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,?,?,?,?,?,?,?,?,0)", (self.uid, broker, y, m, ci, cf, dep, wd, rz))
        self.conn.commit()


class B1_AporteRestadoDosVecesTest(_Base):
    """El borde de apertura era la foto del PROPIO día 1, que ya tiene el depósito
    adentro, mientras `deposits` seguía saliendo del mes calendario completo."""

    def _mes_plano_con_aporte_el_dia_1(self):
        self.pos()
        # La fila de ABRIL tambien: una cuenta con snapshots de abril SIEMPRE tiene
        # su fila del mes. Sin ella, el `capital_inicio` de mayo pasa a ser el
        # BASELINE de toda la cuenta y el aportado canonico salta de 0 a 110.000
        # dentro de mayo — un estado que la app no produce.
        self.me(2026, 4, 100000.0, 100000.0)
        self.me(2026, 5, 100000.0, 110000.0, dep=10000.0)
        for d in range(20, 31):
            self.snap(f"2026-04-{d:02d}", 100000.0, nd=0.0)
        for d in range(1, 32):
            self.snap(f"2026-05-{d:02d}", 110000.0, nd=10000.0)

    def test_mes_plano_con_aporte_el_dia_1_da_cero(self):
        self._mes_plano_con_aporte_el_dia_1()
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-05-01", "2026-05-31", "global", None)
        self.assertEqual(m.basis, "mercado")
        self.assertAlmostEqual(m.start_value, 100000.0, places=2)   # cierre de ABRIL
        self.assertAlmostEqual(m.end_value, 110000.0, places=2)
        self.assertAlmostEqual(m.delta_usd, 0.0, places=2)
        self.assertAlmostEqual(m.delta_pct, 0.0, places=2)

    def test_el_borde_de_apertura_es_anterior_al_periodo(self):
        self._mes_plano_con_aporte_el_dia_1()
        b = builder.bordes_mercado_periodo(
            self.conn, self.uid, "2026-05-01", "2026-05-31", "global")
        self.assertIsNotNone(b)
        v0, v1 = b
        self.assertAlmostEqual(v0, 100000.0, places=2)     # cierre de ABRIL
        self.assertAlmostEqual(v1, 110000.0, places=2)

    def test_el_mes_con_ganancia_real_sigue_midiendo_la_ganancia(self):
        """La contracara: el fix no puede apagar un mes que sí ganó."""
        self.pos()
        self.me(2026, 4, 100000.0, 100000.0)
        self.me(2026, 5, 100000.0, 115000.0, dep=10000.0)
        self.snap("2026-04-30", 100000.0, nd=0.0)
        for d in range(1, 32):
            self.snap(f"2026-05-{d:02d}", 115000.0, nd=10000.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-05-01", "2026-05-31", "global", None)
        self.assertAlmostEqual(m.delta_usd, 5000.0, places=2)
        self.assertGreater(m.delta_pct, 0)

    def test_el_flujo_NO_sale_de_restar_dos_estampas(self):
        """`snapshots.net_deposited` no es un hecho del día: es una medición hecha
        sobre `monthly_entries` en el momento de escribir la fila. Un import la
        reescribe hacia atrás sin re-estampar las fotos viejas, así que restar dos
        estampas mide cuánto cambió la contabilidad entre dos momentos, no el flujo.
        El flujo correcto son los `deposits`/`withdrawals` del propio período, y son
        exactamente la ventana porque el borde de apertura es el cierre anterior."""
        self.pos()
        self.me(2026, 4, 100000.0, 100000.0)
        self.me(2026, 5, 100000.0, 110000.0, dep=10000.0)
        # Estampas MENTIROSAS a propósito: si el flujo saliera de acá, daría 999.
        self.snap("2026-04-30", 100000.0, nd=1.0)
        for d in range(1, 32):
            self.snap(f"2026-05-{d:02d}", 110000.0, nd=1000.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-05-01", "2026-05-31", "global", None)
        self.assertEqual(m.basis, "mercado")
        self.assertAlmostEqual(m.deposits, 10000.0, places=2)
        self.assertAlmostEqual(m.delta_usd, 0.0, places=2)


class B2_SeriePartidaTest(_Base):
    def test_no_publica_un_twr_positivo_con_la_caida_en_el_hueco(self):
        self.pos()
        self.snap("2026-01-31", 10000.0)
        self.snap("2026-02-28", 12000.0)
        # Hueco REAL de tres meses (antes se forzaba con una cobertura baja, que
        # ya no excluye nada — la cobertura es un número, no un filtro).
        self.snap("2026-06-30", 6000.0)
        self.snap("2026-07-31", 6600.0)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(c["tramos"]), 2)
        self.assertIsNone(c["twr"])              # NO +32%
        self.assertTrue(c["serie_partida"])
        self.assertEqual(c["motivo"], "serie_partida")
        self.assertTrue(c["motivo_texto"])

    def test_el_indice_se_reinicia_en_cada_tramo(self):
        self.pos()
        self.snap("2026-01-31", 10000.0)
        self.snap("2026-02-28", 12000.0)
        self.snap("2026-04-30", 6000.0)
        self.snap("2026-05-31", 6600.0)
        c = twr.curva_indexada(self.conn, self.uid)
        idx = {p["date"]: p["index"] for p in c["curva"]}
        self.assertAlmostEqual(idx["2026-02-28"], 1.20, places=4)
        self.assertAlmostEqual(idx["2026-04-30"], 1.00, places=4)   # reinicia
        self.assertAlmostEqual(idx["2026-05-31"], 1.10, places=4)

    def test_el_drawdown_maximo_tampoco_se_publica_partido(self):
        """Sería una COTA INFERIOR con nombre de máximo: el peor momento puede
        haber estado adentro del hueco."""
        self.pos()
        self.snap("2026-01-31", 10000.0)
        self.snap("2026-02-28", 12000.0)
        self.snap("2026-04-30", 6000.0)
        self.snap("2026-05-31", 6600.0)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertIsNone(c["drawdown_maximo"])
        self.assertIsNone(c["drawdown_actual"])

    def test_un_punto_suelto_al_final_no_pone_el_drawdown_en_cero(self):
        """Regresión que introdujo el propio fix de la serie partida: `dd_actual`
        era UNA variable que se pisaba en cada punto apto de cualquier tramo. Con
        un punto suelto al final, el último valor escrito era el de ese punto
        —cuyo índice arranca en 1,0— y el drawdown daba 0,0% con el usuario 36%
        abajo de su pico."""
        self.pos()
        self.snap("2026-01-31", 10000.0)
        self.snap("2026-02-28", 11000.0)
        self.snap("2026-03-31", 7000.0)
        self.snap("2026-09-30", 7000.0)     # suelto, hueco > max_hueco_dias
        c = twr.curva_indexada(self.conn, self.uid)
        # Con un hueco, el drawdown punta a punta NO es afirmable (el peor momento
        # pudo estar adentro): va None, y el del tramo queda en `tramos_detalle`.
        self.assertTrue(c["serie_partida"])
        self.assertIsNone(c["drawdown_maximo"])
        self.assertIsNone(c["drawdown_actual"])
        medido = [t for t in c["tramos_detalle"] if t["legs"] > 0][0]
        self.assertAlmostEqual(medido["drawdown_maximo"], -0.363636, places=5)
        self.assertAlmostEqual(medido["drawdown_actual"], -0.363636, places=5)
        # Y lo que NO puede pasar es el 0,0%: eso decia "nunca caiste".
        self.assertNotEqual(c["drawdown_maximo"], 0.0)

    def test_un_solo_tramo_sigue_publicando_normal(self):
        self.pos()
        for d, v in (("2026-01-31", 10000.0), ("2026-02-28", 12000.0),
                     ("2026-03-31", 9000.0)):
            self.snap(d, v)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertFalse(c["serie_partida"])
        self.assertAlmostEqual(c["twr"], -0.10, places=6)
        self.assertAlmostEqual(c["drawdown_maximo"], -0.25, places=6)


class B3_DrawdownCeroSinMedirTest(_Base):
    def test_una_sola_medicion_no_publica_drawdown(self):
        self.pos("2025-01-15")
        self.snap("2026-07-31", 139570.56, src="import")
        self.snap("2026-08-24", 73604.02, nd=130.80)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertIsNone(c["twr"])
        self.assertIsNone(c["drawdown_actual"])
        self.assertIsNone(c["drawdown_maximo"])
        self.assertIsNone(c["drawdown_maximo_fecha"])

    def test_dos_mediciones_separadas_por_un_hueco_tampoco(self):
        self.pos()
        self.snap("2026-01-31", 10000.0)
        self.snap("2026-05-31", 3700.0)          # -63% real, 120 días de hueco
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(c["tramos_medidos"], 0)
        self.assertIsNone(c["drawdown_maximo"])

    def test_el_endpoint_expone_tramos_medidos(self):
        """Gatear por `perf.tramos_medidos` daba undefined: `performance` exponía
        `tramos` (el conteo de pedazos) y omitía `tramos_medidos`."""
        import performance as perf
        self.pos()
        self.snap("2026-01-31", 10000.0)
        self.snap("2026-02-28", 11000.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        self.assertIn("tramos_medidos", r)
        self.assertEqual(r["tramos_medidos"], 1)
        self.assertIn("serie_partida", r)


class B4_AnioParcialTest(_Base):
    def test_el_porcentaje_y_el_monto_cubren_la_misma_ventana(self):
        self.pos()
        hoy = date.today()
        Y = hoy.year
        self.me(Y, 1, 1000.0, 51000.0, dep=50000.0)
        self.me(Y, hoy.month, 51000.0, 44000.0)
        import calendar
        for mo in range(7, hoy.month + 1):
            ult = min(calendar.monthrange(Y, mo)[1], hoy.day if mo == hoy.month else 31)
            self.snap(f"{Y}-{mo:02d}-{ult:02d}", 40000.0 + mo * 100, nd=50000.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "year", f"{Y}-01-01", f"{Y}-12-31", "global", None,
            live_value=44000.0)
        # El % no puede ser el de julio-a-hoy (positivo) al lado de un monto anual
        # negativo. Los dos describen start→end.
        self.assertEqual(m.basis, "contable")
        self.assertLess(m.delta_usd, 0)
        self.assertLess(m.delta_pct, 0)

    def test_ventana_cubierta_si_acepta_el_motor_canonico(self):
        self.pos()
        import calendar
        valor = 100000.0
        self.snap("2024-12-31", valor)
        for mes in range(1, 13):
            valor *= 0.97
            self.snap(f"2025-{mes:02d}-{calendar.monthrange(2025, mes)[1]:02d}",
                      round(valor, 2))
        for mes in range(1, 13):
            self.me(2025, mes, 100000.0, 100000.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "year", "2025-01-01", "2025-12-31", "global", None)
        self.assertEqual(m.basis, "mercado")
        self.assertLess(m.delta_pct, 0)

    def test_ventana_cubre_helper(self):
        self.assertTrue(builder._ventana_cubre(
            "2025-01-02", "2025-12-30", "2025-01-01", "2025-12-31", False))
        self.assertFalse(builder._ventana_cubre(
            "2025-07-01", "2025-12-30", "2025-01-01", "2025-12-31", False))
        self.assertFalse(builder._ventana_cubre(
            "2025-01-02", "2025-06-30", "2025-01-01", "2025-12-31", False))
        self.assertFalse(builder._ventana_cubre(
            None, None, "2025-01-01", "2025-12-31", False))


class B5_CoberturaSinPreciosTest(_Base):
    def _cuenta_con_tenencia_invisible(self):
        import scripts.backfill_historical_mtm as bf
        # Sin esto el test sale a yfinance de verdad (medido: 154s la suite).
        self._orig_fetch = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda pk, si: {}
        self.addCleanup(self._restaurar_fetch, bf)
        self.pos("2024-08-01", "AAPL", invested=9000.0)
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "IBKR", "USDT"))
        bid = "B5"
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,'confirmed')", (bid, self.uid, "IBKR", "generic", "h5"))
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
            "VALUES (?,?,?,'valid')", (bid, 0, "{}")).lastrowid
        # El import SOLO trae un DEPOSIT: la tenencia real vive en `positions`.
        self.conn.execute(
            """INSERT INTO import_normalized_tx (batch_id,raw_row_id,broker,asset_symbol,
               asset_type,operation_type,quantity,unit_price,gross_amount,currency,date)
               VALUES (?,?,'IBKR',NULL,NULL,'DEPOSIT',NULL,NULL,10000,'USD','2024-08-01')""",
            (bid, rr))
        for (y, mo, ci, cf, dep) in ((2024, 8, 0, 10000, 10000), (2024, 9, 10000, 13000, 0)):
            for b in ("global", "IBKR"):
                self.me(y, mo, ci, cf, dep=dep, broker=b)
        self.conn.commit()
        return bf

    def _restaurar_fetch(self, bf):
        bf._fetch_monthly_close = self._orig_fetch
        bf._HIST_CACHE.clear()

    def test_no_hay_cobertura_1_sin_haber_consultado_un_precio(self):
        bf = self._cuenta_con_tenencia_invisible()
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.conn.commit()
        covs = [r["mtm_coverage"] for r in self.conn.execute(
            "SELECT mtm_coverage FROM snapshots WHERE user_id=?", (self.uid,))]
        self.assertTrue(covs)
        for c in covs:
            self.assertNotEqual(c, 1.0)

    def test_esa_foto_no_entra_como_base_de_mercado(self):
        bf = self._cuenta_con_tenencia_invisible()
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.conn.commit()
        c = twr.curva_indexada(self.conn, self.uid)
        # Ya no desaparece de la serie: entra con su cobertura, pero NO es apta —
        # no puede sostener un pico ni ser denominador.
        self.assertEqual(sum(1 for p in c["puntos"] if p["apto"]), 0)
        self.assertIsNone(c["twr"])

    def test_cash_real_afirmable_sigue_dando_cobertura_1(self):
        """La contracara: una cartera de verdad toda en cash no necesitó ningún
        precio, y eso SÍ se puede afirmar (no hay nada no-cash en ningún lado)."""
        import scripts.backfill_historical_mtm as bf
        costo, afirmable = bf._tenencia_no_vista(self.conn, self.uid, "2024-08-31", set())
        self.assertEqual(costo, 0.0)
        self.assertTrue(afirmable)

    def test_tenencia_sin_costo_conocido_no_es_afirmable(self):
        import scripts.backfill_historical_mtm as bf
        self.pos("2024-01-01", "XYZ", invested=0.0)     # hay algo, no sé cuánto
        costo, afirmable = bf._tenencia_no_vista(self.conn, self.uid, "2024-08-31", set())
        self.assertFalse(afirmable)


if __name__ == "__main__":
    unittest.main()
