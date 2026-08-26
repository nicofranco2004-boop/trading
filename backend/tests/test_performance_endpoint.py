"""FASE 3 — la sección Performance servida desde un solo lugar.

El criterio que motiva el recorte: hoy el S&P se dibuja COMPLETO y la cartera no,
así que arrancan de puntos distintos y el usuario compara su tramo contra la
historia entera del índice.
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
        for t in ("snapshots", "positions", "operations", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("perf@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,100,?)",
            (self.uid, "IBKR", "AAPL", "2024-01-01"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def snap(self, date, value, source="cron", nd=0.0, cov=None):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (self.uid, date, value, value, nd, source, cov,
             1200.0 if source == "cron" else None, "[]" if source == "cron" else None))
        self.conn.commit()


# El S&P arranca MUCHO antes que la cartera y sube fuerte en ese tramo previo:
# si no se recortara, el usuario compararía contra esa historia que no vivió.
SP = {"2025-01": 50.0, "2025-06": 80.0, "2026-01": 100.0,
      "2026-02": 110.0, "2026-03": 121.0}


class RecorteTest(_Base):
    def test_arrancan_en_la_misma_fecha_y_en_el_mismo_valor(self):
        self.snap("2026-01-31", 1000.0)
        self.snap("2026-02-28", 1100.0)
        self.snap("2026-03-31", 1200.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP}, "sp500")
        self.assertEqual(len(r["curva"]), len(r["benchmark"]))
        self.assertEqual(r["curva"][0]["date"], r["benchmark"][0]["date"])
        self.assertEqual(r["curva"][-1]["date"], r["benchmark"][-1]["date"])
        # Los dos anclan en 1.0: nadie arrastra capitalización previa.
        self.assertAlmostEqual(r["curva"][0]["index"], 1.0, places=6)
        self.assertAlmostEqual(r["benchmark"][0]["index"], 1.0, places=6)

    def test_no_arrastra_el_tramo_previo_del_indice(self):
        """El S&P hizo 50→100 (×2) ANTES de que el usuario tuviera historia. Ese
        tramo no puede aparecer en la comparación."""
        self.snap("2026-01-31", 1000.0)
        self.snap("2026-03-31", 1200.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP}, "sp500")
        # 100 → 121 en el rango del usuario = +21%, no +142%.
        self.assertAlmostEqual(r["benchmark"][-1]["index"], 1.21, places=4)

    def test_si_el_usuario_arranca_mas_tarde_el_bench_se_mueve_con_el(self):
        self.snap("2026-02-28", 1000.0)
        self.snap("2026-03-31", 1200.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP}, "sp500")
        self.assertEqual(r["benchmark"][0]["date"], "2026-02-28")
        # 110 → 121 = +10%
        self.assertAlmostEqual(r["benchmark"][-1]["index"], 1.10, places=4)

    def test_mes_sin_dato_del_indice_arrastra_plano_no_inventa(self):
        self.snap("2026-01-31", 1000.0)
        self.snap("2026-04-30", 1200.0)      # el S&P no tiene 2026-04
        r = perf.performance(self.conn, self.uid, {"sp500": SP}, "sp500")
        self.assertAlmostEqual(r["benchmark"][-1]["index"], 1.21, places=4)

    def test_benchmark_porcentual_se_compone(self):
        self.snap("2026-01-31", 1000.0)
        self.snap("2026-02-28", 1000.0)
        self.snap("2026-03-31", 1000.0)
        infl = {"2026-01": 5.0, "2026-02": 10.0, "2026-03": 10.0}
        r = perf.performance(self.conn, self.uid, {"inflation_ar": infl}, "inflation_ar")
        self.assertAlmostEqual(r["benchmark"][0]["index"], 1.0, places=6)
        self.assertAlmostEqual(r["benchmark"][-1]["index"], 1.21, places=4)  # 1.1×1.1


class CalidadDelDatoTest(_Base):
    def test_la_banda_contable_viaja_aparte_y_no_entra_en_el_indice(self):
        self.snap("2025-12-31", 99999.0, source="import")
        self.snap("2026-01-31", 1000.0)
        self.snap("2026-02-28", 1100.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP}, "sp500")
        self.assertEqual(len(r["contable"]), 1)
        self.assertEqual([p["date"] for p in r["curva"]],
                         ["2026-01-31", "2026-02-28"])
        # El 99.999 no pudo fijar un pico.
        self.assertGreater(r["drawdown_maximo"], -0.5)

    def test_sin_mediciones_devuelve_el_motivo_no_un_cero(self):
        self.snap("2026-01-31", 1000.0, source="import")
        r = perf.performance(self.conn, self.uid, {"sp500": SP}, "sp500")
        self.assertEqual(r["curva"], [])
        self.assertEqual(r["benchmark"], [])
        self.assertEqual(r["motivo"], "importado_sin_mediciones")
        self.assertEqual(r["motivo_texto"], twr.MOTIVO_TEXTO["importado_sin_mediciones"])
        self.assertIsNone(r["twr"])

    def test_expone_medido_desde_y_cobertura(self):
        self.snap("2026-01-31", 1000.0, source="mtm_backfill", cov=1.0)
        self.snap("2026-02-28", 1100.0)
        r = perf.performance(self.conn, self.uid, {"sp500": SP}, "sp500")
        self.assertEqual(r["medido_desde"], "2026-01-31")
        self.assertAlmostEqual(r["cobertura_reconstruccion"], 1.0, places=3)
        self.assertEqual(r["por_clase"][twr.RECONSTRUIDO], 1)


class EndpointTest(_Base):
    def test_el_endpoint_responde_la_forma_completa(self):
        from fastapi.testclient import TestClient
        self.snap("2026-01-31", 1000.0)
        self.snap("2026-02-28", 1100.0)
        main._bench_cache["data"] = {"sp500": SP}
        main._bench_cache["ts"] = 9e18       # fresco: no sale a la red
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            r = TestClient(main.app).get("/api/insights/performance?bench=sp500")
            self.assertEqual(r.status_code, 200)
            j = r.json()
            for k in ("curva", "benchmark", "contable", "medido_desde",
                      "cobertura", "motivo", "drawdown_actual", "twr"):
                self.assertIn(k, j)
            self.assertEqual(len(j["curva"]), len(j["benchmark"]))
        finally:
            main.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
