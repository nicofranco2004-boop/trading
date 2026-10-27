"""La elección Certero/Estimado es UNA, se guarda en la cuenta y la respeta TODO
cálculo de rendimiento — y cada benchmark se mide sobre el MISMO período que el
número contra el que se compara.

Antes: cuatro pantallas con su propio `useState('certero')`, y todo lo que el
servidor calculaba sin `modo` (la IA, Metas, el informe mensual, el inicio del
celular) medía en certero aunque la app estuviera en estimado. Y los paquetes de
la IA comparaban la inflación de los últimos 12 meses (o del último mes) contra
un rendimiento medido sobre otra ventana, y en otra moneda.

Los tests atraviesan el camino de producción: el endpoint o el builder SIN modo,
con la elección escrita en `users.modo_rendimiento`, como la deja el PUT.
"""
import calendar
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

from fastapi.testclient import TestClient

import main
import performance
import twr

# Inflación de 2 % mensual, S&P plano y blue que sube 1 % por mes.
_BENCH = {
    "inflation_ar": {f"2025-{m:02d}": 2.0 for m in range(1, 13)},
    "sp500": {f"2025-{m:02d}": 100.0 for m in range(1, 13)},
    "dolar_blue": {f"2025-{m:02d}": 1000.0 * (1.01 ** m) for m in range(1, 13)},
}


class _Base(unittest.TestCase):
    """Un usuario 100 % contable: en certero no hay número; en estimado sí."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users",
                  "fx_rates_daily"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"modo-{id(self)}@t", "x")).lastrowid
        cap = 10000.0
        for m in range(1, 13):
            ci, cf = cap, cap * 1.02
            self.conn.execute(
                "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
                "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
                "VALUES (?,'global',2025,?,?,?,0,0,?,0)", (self.uid, m, ci, cf, cf - ci))
            # Lo que escribe el import: la foto de fin de mes, al COSTO.
            d = f"2025-{m:02d}-{calendar.monthrange(2025, m)[1]:02d}"
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                "net_deposited, source) VALUES (?,?,?,?,10000,'import')",
                (self.uid, d, cf, 10000.0))
            cap = cf
        # El dólar de cada día (sube 1 % por mes): sin él no hay rendimiento EN
        # PESOS, y el "vs inflación" no tendría contra qué medirse.
        import datetime as _d
        dia = _d.date(2024, 12, 1)
        while dia <= _d.date(2025, 12, 31):
            fx = 1000.0 * (1.01 ** ((dia.year - 2024) * 12 + dia.month - 12))
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, blue_compra, "
                "mep_compra, source) VALUES (?,?,?,?,?,'test')",
                (dia.isoformat(), fx, fx, fx, fx))
            dia += _d.timedelta(days=1)
        twr.estampar_base(self.conn)
        self.conn.commit()
        self._bench_antes = main._bench_cache.get("data")
        main._bench_cache["data"] = dict(_BENCH)

    def tearDown(self):
        main._bench_cache["data"] = self._bench_antes
        self.conn.close()

    def elegir(self, modo):
        self.conn.execute("UPDATE users SET modo_rendimiento=? WHERE id=?", (modo, self.uid))
        self.conn.commit()


class ModoDeTest(_Base):
    def test_sin_eleccion_es_certero(self):
        self.assertEqual(twr.modo_de(self.conn, self.uid), twr.MODO_CERTERO)

    def test_la_eleccion_guardada_es_el_default(self):
        self.elegir("estimado")
        self.assertEqual(twr.modo_de(self.conn, self.uid), twr.MODO_ESTIMADO)

    def test_lo_que_pide_la_pantalla_gana(self):
        self.elegir("estimado")
        self.assertEqual(twr.modo_de(self.conn, self.uid, "certero"), twr.MODO_CERTERO)

    def test_basura_guardada_o_pedida_cae_a_lo_valido(self):
        self.elegir("cualquiera")
        self.assertEqual(twr.modo_de(self.conn, self.uid), twr.MODO_CERTERO)
        self.elegir("estimado")
        self.assertEqual(twr.modo_de(self.conn, self.uid, "xx"), twr.MODO_ESTIMADO)


class TodosLosLectoresUsanLaEleccionTest(_Base):
    """Cada superficie llamada SIN modo, como la llaman en producción."""

    def test_motor(self):
        self.assertIsNone(twr.curva_indexada(self.conn, self.uid)["twr"])
        self.elegir("estimado")
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertIsNotNone(c["twr"])
        self.assertEqual(c["base_del_twr"], "contable")

    def test_endpoint_de_metricas(self):
        self.elegir("estimado")
        r = main.insights_performance(bench="inflation_ar", desde=None, hasta=None,
                                      valor_live=None, incluir_indeterminado=False,
                                      modo=None, moneda="usd", uid=self.uid)
        self.assertEqual(r["modo"], "estimado")
        self.assertIsNotNone(r["twr"])

    def test_metas_y_dashboard(self):
        self.elegir("estimado")
        r = main.historical_cagr(modo=None, moneda="usd", uid=self.uid)
        self.assertIsNotNone(r.get("total_return"))

    def test_rendimiento_publicable_declara_base_y_ventana(self):
        """En estimado el número del motor es CONTABLE: etiquetarlo 'mercado' le
        hacía decir a la IA 'medido a precio real' sobre una reconstrucción."""
        self.elegir("estimado")
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertEqual(r["base"], "contable")
        self.assertEqual(r["modo"], "estimado")
        self.assertEqual((r["desde"], r["hasta"]), ("2025-01-31", "2025-12-31"))

    def test_paquete_de_benchmarks_de_la_ia(self):
        from ai.builders import insights_benchmarks
        self.elegir("estimado")
        p = insights_benchmarks.build(self.conn, self.uid)
        self.assertEqual(p["modo"], "estimado")
        self.assertIsNotNone(p["user_return_pct"])


class LaIaRespetaElModoAunqueLosDosTenganNumeroTest(_Base):
    """Si certero también mide, la IA tiene que usar el que eligió el usuario —
    antes probaba certero primero y sólo caía a estimado si no había número."""

    def setUp(self):
        super().setUp()
        import datetime as _d
        for i in range(45):     # fotos del cron, a precio de mercado
            d = (_d.date(2026, 1, 1) + _d.timedelta(days=i)).isoformat()
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                "net_deposited, source, fx_to_usd_blue, holdings_json, base, apto) "
                "VALUES (?,?,?,10000,10000,'cron',1200,'[]','mercado',1)",
                (self.uid, d, 12700.0 + i * 15))
        self.conn.commit()

    def test_los_dos_modos_miden(self):
        for modo in twr.MODOS:
            self.assertIsNotNone(twr.curva_indexada(self.conn, self.uid, modo=modo)["twr"], modo)

    def test_la_ia_usa_el_elegido(self):
        from ai.builders import insights_benchmarks
        for modo in twr.MODOS:
            with self.subTest(modo=modo):
                self.elegir(modo)
                self.assertEqual(insights_benchmarks.build(self.conn, self.uid)["modo"], modo)


class ElBenchmarkEsDelMismoPeriodoTest(_Base):

    def test_misma_regla_que_el_grafico(self):
        """`bench_pct_entre` y la línea del gráfico tienen que dar lo mismo."""
        self.elegir("estimado")
        r = main.insights_performance(bench="inflation_ar", desde=None, hasta=None,
                                      valor_live=None, incluir_indeterminado=False,
                                      modo=None, moneda="usd", uid=self.uid)
        b = [p["index"] for p in r["benchmark"] if p.get("index") is not None]
        del_grafico = round((b[-1] / b[0] - 1) * 100, 2)
        self.assertEqual(
            performance.bench_pct_entre(_BENCH, "inflation_ar",
                                        r["ventana_desde"], r["ventana_hasta"]),
            del_grafico)

    def test_inflacion_compone_los_meses_posteriores_al_arranque(self):
        # Del 31/01 al 31/03: febrero y marzo (2 % y 2 %), no enero.
        self.assertEqual(
            performance.bench_pct_entre(_BENCH, "inflation_ar", "2025-01-31", "2025-03-31"),
            round((1.02 * 1.02 - 1) * 100, 2))

    def test_sin_ventana_no_hay_benchmark(self):
        self.assertIsNone(performance.bench_pct_entre(_BENCH, "inflation_ar", None, "2025-03-31"))

    def test_ia_compara_inflacion_en_pesos_y_en_la_ventana_del_numero(self):
        """Antes: `user_return_pct` (DÓLARES) − inflación (PESOS)."""
        from ai.builders import insights_benchmarks
        self.elegir("estimado")
        p = insights_benchmarks.build(self.conn, self.uid)
        infl = p["benchmarks"]["inflation_ar_pct"]
        ars = p["user_return_ars_pct"]
        self.assertIsNotNone(ars)
        self.assertIsNotNone(infl)
        # En pesos el rendimiento incluye la devaluación: no es el de dólares.
        self.assertGreater(ars, p["user_return_pct"])
        self.assertEqual(p["deltas_pp"]["vs_inflation"], round(ars - infl, 2))
        # Y la inflación es la de la ventana de ESE número, con la regla del gráfico.
        p_ars = performance.performance(self.conn, self.uid, _BENCH, bench_key="inflation_ar",
                                        modo="estimado", moneda=twr.MONEDA_ARS)
        self.assertEqual(infl, performance.bench_pct_entre(
            _BENCH, "inflation_ar", p_ars["ventana_desde"], p_ars["ventana_hasta"]))


class ElPutGuardaLaEleccionTest(_Base):

    def setUp(self):
        super().setUp()
        main.app.dependency_overrides[main.get_current_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_current_user, None)
        super().tearDown()

    def test_put_y_get(self):
        self.assertEqual(self.client.get("/api/preferencias/modo-rendimiento").json(),
                         {"modo": None})
        r = self.client.put("/api/preferencias/modo-rendimiento", json={"modo": "estimado"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/preferencias/modo-rendimiento").json(),
                         {"modo": "estimado"})
        # Y el motor lo usa sin que nadie se lo pase.
        self.assertEqual(twr.modo_de(self.conn, self.uid), twr.MODO_ESTIMADO)

    def test_put_rechaza_basura(self):
        r = self.client.put("/api/preferencias/modo-rendimiento", json={"modo": "todo"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()


class ElWrappedComparaElMismoTramoTest(unittest.TestCase):
    """Una cuenta medida desde el 30/06: la inflación del slide es la de jul–dic,
    no la del año entero (antes: 12 meses de inflación contra 6 de cartera)."""

    def _wrapped(self, rendimiento):
        import wrapped
        rows = [{"year": 2025, "month": m, "capital_inicio": 1000.0, "capital_final": 1010.0,
                 "deposits": 0, "withdrawals": 0, "pnl_realized": 10, "pnl_unrealized": 0}
                for m in range(1, 13)]
        infl = {f"2025-{m:02d}": 2.0 for m in range(1, 13)}
        return wrapped.build_wrapped(
            2025, rows, [], [], {}, inflation_ytd=None, fx_de=lambda d: 1000.0,
            rendimiento=rendimiento, inflacion_mensual=infl)

    def _slide(self, w):
        return next(s for s in w["slides"] if s["code"] == "vs_inflation")

    def test_tramo_parcial(self):
        w = self._wrapped({"pct": 20.0, "base": "mercado",
                           "desde": "2025-06-30", "hasta": "2025-12-31"})
        s = self._slide(w)
        infl = next(b["value"] for b in s["bars"] if b["label"].startswith("Inflación"))
        self.assertAlmostEqual(infl, 1.02 ** 6 - 1, places=4)
        self.assertIn("del 30/06 al 31/12", s["bars"][1]["label"])

    def test_anio_entero(self):
        w = self._wrapped({"pct": 20.0, "base": "mercado",
                           "desde": "2024-12-31", "hasta": "2025-12-31"})
        s = self._slide(w)
        infl = next(b["value"] for b in s["bars"] if b["label"].startswith("Inflación"))
        self.assertAlmostEqual(infl, 1.02 ** 12 - 1, places=4)
        self.assertIn("de 2025", s["bars"][1]["label"])
