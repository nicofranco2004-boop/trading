"""El benchmark por FECHA, el índice publicado por punto y la cota de cordura del leg.

Salen del AUDIT_benchmark_2026-09-01: la línea del S&P era una escalera mensual
anclada al fin del primer mes; el KPI leía el índice DIBUJADO; y un leg diario
×240 sin flujo publicaba +25.757% en modo certero.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import performance as perf
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
            (f"bd-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,100,?)",
            (self.uid, "IBKR", "AAPL", "2024-01-01"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def snap(self, date, value, source="cron", nd=0.0):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) VALUES (?,?,?,?,?,?,?,?)",
            (self.uid, date, value, value, nd, source,
             1200.0 if source == "cron" else None, "[]" if source == "cron" else None))
        self.conn.commit()


# Cierres DIARIOS: el viernes 10 y el lunes 13; el fin de semana no cotiza.
SP_D = {"2026-07-01": 100.0, "2026-07-02": 102.0, "2026-07-03": 101.0,
        "2026-07-06": 104.0, "2026-07-10": 110.0, "2026-07-13": 111.0,
        "2026-07-31": 120.0}
SP_M = {"2026-06": 90.0, "2026-07": 120.0}


class BenchmarkDiarioTest(unittest.TestCase):
    def test_ancla_en_la_primera_fecha_y_resuelve_por_dia(self):
        b = perf.benchmark_recortado(SP_D, ["2026-07-02", "2026-07-03", "2026-07-06"], "sp500")
        self.assertEqual([p["date"] for p in b], ["2026-07-02", "2026-07-03", "2026-07-06"])
        self.assertAlmostEqual(b[0]["index"], 1.0, places=6)
        self.assertAlmostEqual(b[1]["index"], 101.0 / 102.0, places=6)
        self.assertAlmostEqual(b[2]["index"], 104.0 / 102.0, places=6)

    def test_el_fin_de_semana_arrastra_el_viernes(self):
        b = perf.benchmark_recortado(SP_D, ["2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13"], "sp500")
        self.assertAlmostEqual(b[1]["index"], 1.0, places=6)      # sábado = viernes
        self.assertAlmostEqual(b[2]["index"], 1.0, places=6)      # domingo = viernes
        self.assertAlmostEqual(b[3]["index"], 111.0 / 110.0, places=6)

    def test_antes_del_primer_cierre_no_hay_punto_y_el_ancla_es_la_primera_con_dato(self):
        b = perf.benchmark_recortado(SP_D, ["2026-06-20", "2026-07-01", "2026-07-02"], "sp500")
        self.assertEqual(len(b), 3)
        self.assertIsNone(b[0]["index"])
        self.assertAlmostEqual(b[1]["index"], 1.0, places=6)
        self.assertAlmostEqual(b[2]["index"], 1.02, places=6)

    def test_hoy_toma_el_ultimo_cierre(self):
        b = perf.benchmark_recortado(SP_D, ["2026-07-10", "hoy"], "sp500")
        self.assertAlmostEqual(b[-1]["index"], 120.0 / 110.0, places=6)

    def test_el_mensual_sigue_igual_para_claves_de_mes(self):
        b = perf.benchmark_recortado(SP_M, ["2026-06-30", "2026-07-31"], "sp500")
        self.assertAlmostEqual(b[0]["index"], 1.0, places=6)
        self.assertAlmostEqual(b[1]["index"], 120.0 / 90.0, places=6)

    def test_los_porcentuales_no_pasan_por_el_diario(self):
        infl = {"2026-06": 5.0, "2026-07": 10.0}
        b = perf.benchmark_recortado(infl, ["2026-06-30", "2026-07-31"], "inflation_ar")
        self.assertAlmostEqual(b[-1]["index"], 1.10, places=6)


class PerformancePrefiereElDiarioTest(_Base):
    def test_usa_la_serie_diaria_si_existe(self):
        self.snap("2026-07-02", 1000.0)
        self.snap("2026-07-03", 1010.0)
        self.snap("2026-07-06", 1020.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP_M, "sp500_d": SP_D}, "sp500")
        self.assertEqual(r["benchmark_resolucion"], "diaria")
        self.assertEqual(len(r["benchmark"]), len(r["curva"]))
        self.assertAlmostEqual(r["benchmark"][-1]["index"], 104.0 / 102.0, places=6)

    def test_sin_diario_cae_al_mensual(self):
        self.snap("2026-07-02", 1000.0)
        self.snap("2026-07-06", 1020.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP_M}, "sp500")
        self.assertEqual(r["benchmark_resolucion"], "mensual")
        self.assertAlmostEqual(r["benchmark"][-1]["index"], 1.0, places=6)   # mismo mes → plano

    def test_diario_que_no_cubre_ninguna_fecha_cae_al_mensual(self):
        self.snap("2026-06-20", 1000.0)
        self.snap("2026-06-25", 1020.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP_M, "sp500_d": SP_D}, "sp500")
        self.assertEqual(r["benchmark_resolucion"], "mensual")


class IndicePublicadoTest(_Base):
    def test_cada_punto_trae_el_indice_publicado_y_la_intradia_no_lo_mueve(self):
        self.snap("2026-06-26", 3329.0, source="browser")      # intradía rota
        self.snap("2026-06-27", 22746.0, source="browser")     # intradía
        self.snap("2026-07-01", 23205.0)
        self.snap("2026-07-02", 23678.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        for p in r["curva"]:
            self.assertIn("index_publicado", p)
        aptos = [p for p in r["curva"] if p["apto"]]
        self.assertAlmostEqual(aptos[0]["index_publicado"], 1.0, places=6)
        self.assertAlmostEqual(aptos[-1]["index_publicado"], 23678.0 / 23205.0, places=5)
        self.assertAlmostEqual(r["twr"], 23678.0 / 23205.0 - 1, places=5)
        # La intradía ×6,8 NO parte el tramo (no publica) pero SÍ parte el DIBUJO.
        self.assertFalse(r["serie_partida"])
        segs = {p["segmento"] for p in r["curva"]}
        self.assertGreaterEqual(len(segs), 2)


class LegDudosoTest(_Base):
    def test_salto_x240_sin_flujo_no_publica_y_dice_por_que(self):
        """uid 282 de producción: 4,6 → 1.116 en una rueda, aportado quieto."""
        self.snap("2026-06-30", 4.6, nd=3.4)
        self.snap("2026-07-01", 1116.1, nd=3.4)
        self.snap("2026-07-02", 1120.0, nd=3.4)
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        self.assertIsNone(r["twr"])
        self.assertTrue(r["serie_partida"])
        self.assertEqual(r["motivo"], "medicion_dudosa")
        self.assertEqual(r["motivo_texto"], twr.MOTIVO_TEXTO["medicion_dudosa"])
        self.assertEqual(len(r["cortes_dudosos"]), 1)
        self.assertEqual(r["cortes_dudosos"][0]["motivo"], "salto")
        self.assertEqual(r["cortes_dudosos"][0]["hasta"], "2026-07-01")

    def test_el_mismo_salto_con_el_deposito_registrado_si_se_mide(self):
        self.snap("2026-06-30", 1000.0, nd=1000.0)
        self.snap("2026-07-01", 6000.0, nd=6000.0)      # entraron 5.000
        self.snap("2026-07-02", 6060.0, nd=6000.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        self.assertIsNotNone(r["twr"])
        self.assertEqual(r["cortes_dudosos"], [])
        self.assertAlmostEqual(r["twr"], 0.01, places=3)

    def test_un_x2_y_medio_sin_flujo_sigue_pasando_y_un_x4_no(self):
        """La cota es ×3 (medida: con ×5 quedaban dos +300% publicados). Un ×2,5 en
        una rueda es raro pero una cartera cripto concentrada puede darlo; un ×4 no."""
        self.snap("2026-06-30", 100.0)
        self.snap("2026-07-01", 250.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        self.assertAlmostEqual(r["twr"], 1.5, places=6)
        self.assertEqual(r["cortes_dudosos"], [])
        self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
        self.conn.commit()
        self.snap("2026-06-30", 100.0)
        self.snap("2026-07-01", 400.0)
        self.snap("2026-07-02", 404.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        self.assertIsNone(r["twr"])
        self.assertEqual(r["cortes_dudosos"][0]["motivo"], "salto")
        self.assertEqual(twr.SALTO_MAX_VECES, 3.0)

    def test_la_foto_de_16_millones_no_deja_la_curva_en_menos_100_para_siempre(self):
        """uid 513: 16.229.949 → 109 → el índice quedaba en 0 (absorbente)."""
        self.snap("2026-06-25", 16229949.4)
        self.snap("2026-06-26", 109.0)
        self.snap("2026-06-27", 110.0)
        self.snap("2026-06-28", 112.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500")
        self.assertEqual(r["motivo"], "medicion_dudosa")
        self.assertIsNone(r["twr"])
        # El tramo posterior sí se mide solo: 109 → 112.
        ult = r["tramos_detalle"][-1]
        self.assertAlmostEqual(ult["twr"], 112.0 / 109.0 - 1, places=5)

    def test_estimado_la_cadena_contable_no_queda_en_menos_100(self):
        """uid 193: 18,9 → 52,2 con un flujo de 327 → dietz = −1 → idx_est = 0."""
        self.snap("2020-11-30", 18.9, source="import", nd=269.7)
        self.snap("2020-12-31", 52.2, source="import", nd=596.7)
        self.snap("2021-01-31", 55.0, source="import", nd=596.7)
        self.snap("2021-02-28", 60.0, source="import", nd=596.7)
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO)
        self.assertIsNotNone(r["twr"])
        self.assertGreater(r["twr"], -0.5)
        self.assertEqual(r["cortes_dudosos"][0]["motivo"], "desborde")
        self.assertEqual(r["cortes_dudosos"][0]["cadena"], "contable")
        # y la ventana publicada arranca DESPUÉS del corte
        self.assertGreaterEqual(r["ventana_desde"], "2020-12-31")

    def test_certero_no_toca_la_cadena_contable(self):
        """En CERTERO las filas al costo no entran a la línea: el corte contable no aplica."""
        self.snap("2020-11-30", 18.9, source="import", nd=269.7)
        self.snap("2020-12-31", 52.2, source="import", nd=596.7)
        self.snap("2026-07-01", 1000.0)
        self.snap("2026-07-02", 1010.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_CERTERO)
        self.assertEqual(r["cortes_dudosos"], [])
        self.assertAlmostEqual(r["twr"], 0.01, places=6)


class EstimadoSinCortesTest(_Base):
    """El estimado es el certero MÁS historia: no el certero más agujeros."""

    def _contable(self, pares, nd=1000.0):
        for d, v in pares:
            self.snap(d, v, source="import", nd=nd)

    def test_un_mes_contable_faltante_no_parte_la_linea(self):
        # Sep, Oct, Nov, (Dic falta), Ene: 62 días entre Nov y Ene → antes cortaba.
        self._contable([("2025-09-30", 1000.0), ("2025-10-31", 1010.0),
                        ("2025-11-30", 1020.0), ("2026-01-31", 1040.0)])
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO)
        self.assertEqual(r["tramos"], 1)
        self.assertFalse(r["serie_partida"])
        self.assertAlmostEqual(r["twr"], 1040.0 / 1000.0 - 1, places=6)
        # en CERTERO no cambia nada: la contabilidad no entra
        c = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_CERTERO)
        self.assertEqual(c["curva"], [])

    def test_un_año_perdido_si_parte(self):
        self._contable([("2024-01-31", 1000.0), ("2025-06-30", 1100.0), ("2025-07-31", 1110.0)])
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO)
        self.assertEqual(r["tramos"], 2)

    def test_la_contabilidad_se_apaga_en_la_primera_medicion(self):
        self._contable([("2026-05-31", 1000.0), ("2026-06-30", 1050.0), ("2026-07-31", 1200.0)])
        self.snap("2026-07-11", 1100.0, nd=1000.0)      # cron: primera medición real
        self.snap("2026-07-12", 1110.0, nd=1000.0)
        self.snap("2026-08-10", 1150.0, nd=1000.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO)
        fechas = [p["date"] for p in r["curva"]]
        self.assertNotIn("2026-07-31", fechas)            # superada: no entra a la línea
        self.assertIn("2026-07-31", [p["date"] for p in r["contable"]])   # pero sí a la banda
        self.assertEqual(r["contable_superado"], 1)
        self.assertEqual(r["tramos"], 1)

    def test_el_dibujo_es_continuo_en_el_cambio_de_regla_y_termina_en_el_numero(self):
        self._contable([("2026-05-31", 1000.0), ("2026-06-30", 1050.0)])
        self.snap("2026-07-11", 2000.0, nd=1000.0)
        self.snap("2026-07-12", 2100.0, nd=1000.0)
        self.snap("2026-08-10", 1900.0, nd=1000.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO)
        segs = {p["segmento"] for p in r["curva"]}
        self.assertEqual(len(segs), 1)                    # UNA línea, sin corte
        idx = {p["date"]: p["index"] for p in r["curva"]}
        # contable: 1000 → 1050 = ×1,05; mercado: 2000 → 1900 = ×0,95. Producto.
        self.assertAlmostEqual(idx["2026-06-30"], 1.05, places=5)
        self.assertAlmostEqual(idx["2026-07-11"], 1.05, places=5)   # arranca donde quedó
        self.assertAlmostEqual(idx["2026-08-10"], 1.05 * 0.95, places=5)
        self.assertAlmostEqual(r["twr"], 1.05 * 0.95 - 1, places=5)  # el chip = el final de la línea
        # y NO se restó 1.050 contra 2.000: ningún leg de +90 %
        self.assertLess(max(p["index"] for p in r["curva"]), 1.2)

    def test_un_traspaso_de_mas_de_45_dias_sigue_partiendo(self):
        self._contable([("2026-01-31", 1000.0), ("2026-02-28", 1050.0)])
        self.snap("2026-07-11", 2000.0, nd=1000.0)
        self.snap("2026-07-12", 2100.0, nd=1000.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO)
        self.assertEqual(r["tramos"], 2)
        self.assertEqual(len({p["segmento"] for p in r["curva"]}), 2)


class EstimadoHoyTest(_Base):
    def test_el_hoy_continua_la_linea_y_publica_la_misma_cadena_que_el_chip(self):
        # nd=0 en todas: sin `monthly_entries` el flujo del leg "hoy" sale de
        # compute_net_deposited_db (0) menos la estampa, y una estampa de 1.000
        # se leería como un retiro de 1.000 el día de hoy.
        for d, v in (("2026-05-31", 1000.0), ("2026-06-30", 1050.0)):
            self.snap(d, v, source="import", nd=0.0)
        self.snap("2026-07-11", 2000.0, nd=0.0)
        self.snap("2026-07-12", 2100.0, nd=0.0)
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO,
                             valor_live=1890.0)          # hoy: 2100 → 1890 = ×0,9
        hoy = r["curva"][-1]
        self.assertEqual(hoy["date"], "hoy")
        # línea: 1,05 (contable) × 1,05 (2000→2100) × 0,9 = 0,99225, sin escalón
        self.assertAlmostEqual(hoy["index"], 1.05 * 1.05 * 0.9, places=4)
        self.assertAlmostEqual(hoy["index_publicado"], 1.0 + r["twr"], places=4)
        self.assertAlmostEqual(r["twr"], 1.05 * 1.05 * 0.9 - 1, places=4)
        # y en cada punto de la cadena, index_publicado == la cadena del chip
        for q in r["curva"]:
            self.assertIn("index_publicado", q)


class HoyConIntradiaAlFinalTest(_Base):
    """La foto de media rueda del Dashboard al final del tramo no apaga el "hoy"."""

    def test_certero_agrega_hoy_aunque_el_ultimo_punto_sea_intradia(self):
        self.snap("2026-08-24", 18000.0)
        self.snap("2026-08-25", 18077.0)
        self.snap("2026-09-02", 16594.0, source="browser")      # intradía de hoy
        r = perf.performance(self.conn, self.uid, {}, "sp500", valor_live=16595.0)
        self.assertEqual(r["curva"][-1]["date"], "hoy")
        # el número incluye la pata live desde el ÚLTIMO APTO (18077 → 16595)
        self.assertAlmostEqual(r["twr"], 16595.0 / 18000.0 - 1, places=5)
        self.assertAlmostEqual(r["curva"][-1]["index_publicado"], 1 + r["twr"], places=5)

    def test_estimado_el_hoy_no_cuenta_la_caida_dos_veces(self):
        self.snap("2026-05-31", 1000.0, source="import", nd=0.0)
        self.snap("2026-06-30", 1050.0, source="import", nd=0.0)
        self.snap("2026-07-11", 2000.0)
        self.snap("2026-07-12", 2100.0)
        self.snap("2026-07-13", 1900.0, source="browser")        # intradía: −9,5 %
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO,
                             valor_live=1890.0)                   # hoy: 2100 → 1890 = ×0,9
        hoy = r["curva"][-1]
        self.assertEqual(hoy["date"], "hoy")
        # línea: 1,05 × 1,05 × 0,9 — desde el último apto, no desde la intradía
        self.assertAlmostEqual(hoy["index"], 1.05 * 1.05 * 0.9, places=4)
        self.assertAlmostEqual(hoy["index_publicado"], 1 + r["twr"], places=4)
        self.assertAlmostEqual(r["twr"], 1.05 * 1.05 * 0.9 - 1, places=4)


class YfinanceReintentoTest(unittest.TestCase):
    """Si `history()` viene vacío o explota (caché de zonas horarias corrupto),
    se reapunta el caché UNA vez y se reintenta; si sigue mal, devuelve None."""

    def setUp(self):
        main._yf_cache_reset["ts"] = 0.0

    def test_reintenta_sobre_cache_nuevo_y_devuelve_datos(self):
        import pandas as pd
        from unittest.mock import patch, MagicMock
        ok = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2026-08-31"]))
        t_roto = MagicMock(); t_roto.history.side_effect = Exception("disk I/O error")
        t_ok = MagicMock(); t_ok.history.return_value = ok
        with patch("main.yf.Ticker", side_effect=[t_roto, t_ok]), \
             patch("main.yf.set_tz_cache_location") as setcache:
            d = main._yf_history("^SP500TR", "max", "1mo")
        self.assertIsNotNone(d)
        self.assertEqual(len(d), 1)
        setcache.assert_called_once()

    def test_no_reapunta_dos_veces_en_una_hora(self):
        import pandas as pd
        from unittest.mock import patch, MagicMock
        vacio = pd.DataFrame({"Close": []})
        t = MagicMock(); t.history.return_value = vacio
        with patch("main.yf.Ticker", return_value=t), \
             patch("main.yf.set_tz_cache_location") as setcache:
            main._yf_history("SHV", "max", "1mo")
            main._yf_history("GLD", "max", "1mo")
        setcache.assert_called_once()


class MotorDelAsesorTest(_Base):
    """`tramos`/`sellar`/`twr_de`: el mismo leg dudoso no se compone en el libro."""

    def _cron_fin_de_mes(self, pares):
        import json as _j
        for d, v in pares:
            self.conn.execute(
                "INSERT INTO snapshots (user_id,date,total_value,total_invested,"
                "fx_to_usd_blue,holdings_json,source,net_deposited) VALUES (?,?,?,?,1400,?,'cron',0)",
                (self.uid, d, v, v, _j.dumps([{"asset": "AAPL", "value_usd": v}])))
        self.conn.commit()

    def test_un_mes_x240_sin_flujo_queda_dudoso_y_el_libro_no_publica(self):
        """uid 282: 4,6 → 1.133 entre dos cierres de mes, aportado quieto."""
        self._cron_fin_de_mes([("2026-01-31", 100.0), ("2026-02-28", 110.0),
                               ("2026-03-31", 4.6), ("2026-04-30", 1133.2),
                               ("2026-05-31", 1150.0)])
        ts = twr.tramos(self.conn, self.uid, hasta_mes="2027-01")
        por_mes = {t["month"]: t["quality"] for t in ts}
        self.assertEqual(por_mes["2026-04"], "dudoso")
        self.assertEqual(por_mes["2026-03"], "dudoso")
        self.assertEqual(por_mes["2026-02"], "ok")
        twr.sellar(self.conn, self.uid, hasta_mes="2027-01")
        self.conn.commit()
        r = twr.twr_de(self.conn, self.uid)
        self.assertIsNone(r["twr"])
        self.assertEqual(r["motivo"], "medicion_dudosa")
        # Una foto rota genera DOS legs dudosos: el que entra (110 → 4,6) y el
        # que sale (4,6 → 1.133). Los dos meses quedan marcados.
        self.assertEqual(r["meses_dudosos"], ["2026-03", "2026-04"])
        self.assertEqual(r["meses"], 4)          # los meses siguen sellados

    def test_corregida_la_foto_el_sello_se_revisa_y_el_numero_vuelve(self):
        self._cron_fin_de_mes([("2026-01-31", 100.0), ("2026-02-28", 4.6),
                               ("2026-03-31", 110.0)])
        twr.sellar(self.conn, self.uid, hasta_mes="2027-01"); self.conn.commit()
        self.assertIsNone(twr.twr_de(self.conn, self.uid)["twr"])
        # alguien corrige la foto rota
        self.conn.execute("UPDATE snapshots SET total_value=105.0 WHERE user_id=? AND date='2026-02-28'",
                          (self.uid,))
        self.conn.commit()
        r = twr.sellar(self.conn, self.uid, hasta_mes="2027-01"); self.conn.commit()
        self.assertGreaterEqual(r["revisados"], 1)
        t = twr.twr_de(self.conn, self.uid)
        self.assertAlmostEqual(t["twr"], 110.0 / 100.0 - 1, places=9)
        self.assertEqual(t["meses_dudosos"], [])

    def test_un_mes_de_mas_80_sigue_siendo_ok(self):
        self._cron_fin_de_mes([("2026-01-31", 100.0), ("2026-02-28", 180.0), ("2026-03-31", 190.0)])
        ts = twr.tramos(self.conn, self.uid, hasta_mes="2027-01")
        self.assertEqual({t["month"]: t["quality"] for t in ts}["2026-02"], "ok")


if __name__ == "__main__":
    unittest.main()
