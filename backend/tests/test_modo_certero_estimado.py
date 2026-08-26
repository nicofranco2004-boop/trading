"""PARTE B · el switch CERTERO / ESTIMADO y la cobertura como porcentaje.

La línea divisoria NO es "foto del cron vs reconstrucción": reconstruir un CEDEAR
o una acción a precio histórico es EXACTO. Es "valuado a precio real vs valuado
al costo".
"""
import json
import os
import tempfile
import unittest
from datetime import date

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
            (f"modo-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2024-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def recon(self, d, v, cov, al_costo=()):
        hold = json.dumps([{"asset": a, "value_usd": 1.0, "al_costo": True} for a in al_costo]
                          or [{"asset": "AAPL", "value_usd": v, "al_costo": False}])
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, holdings_json) "
            "VALUES (?,?,?,?,0,'mtm_backfill',?,?)",
            (self.uid, d, float(v), float(v), cov, hold))
        self.conn.commit()


class DosModosTest(_Base):
    def test_una_reconstruccion_PARCIAL_no_es_apta_en_certero_pero_si_en_estimado(self):
        self.recon("2026-01-31", 1000.0, 0.88, al_costo=("FCI Balanz",))
        self.recon("2026-02-28", 1100.0, 0.88, al_costo=("FCI Balanz",))
        cert = twr.serie_medible(self.conn, self.uid, modo=twr.MODO_CERTERO)
        est = twr.serie_medible(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertEqual(len(cert["puntos"]), 2)                   # NO desaparece
        self.assertFalse(any(p["apto"] for p in cert["puntos"]))
        self.assertTrue(all(p["apto"] for p in est["puntos"]))

    def test_el_mes_ya_no_DESAPARECE_por_no_llegar_a_un_umbral(self):
        """Antes un umbral duro de 0,70 borraba el mes entero. Al que tenía 88%
        valuado a precio real no se le mostraba nada."""
        self.recon("2026-01-31", 1000.0, 0.88)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(len(s["puntos"]), 1)
        self.assertEqual(s["puntos"][0]["clase"], twr.RECONSTRUIDO)
        self.assertAlmostEqual(s["puntos"][0]["cobertura"], 0.88, places=3)

    def test_una_reconstruccion_a_precio_real_SI_es_apta_en_certero(self):
        """Un CEDEAR o una acción reconstruidos son exactos: entran en CERTERO."""
        self.recon("2026-01-31", 1000.0, 1.0)
        self.recon("2026-02-28", 1100.0, 1.0)
        c = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
        self.assertAlmostEqual(c["twr"], 0.10, places=6)

    def test_los_dos_modos_son_coherentes_entre_si(self):
        """Con todo valuado a precio real, los dos modos dan LO MISMO."""
        self.recon("2026-01-31", 1000.0, 1.0)
        self.recon("2026-02-28", 1100.0, 1.0)
        a = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
        b = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertEqual(a["twr"], b["twr"])
        self.assertEqual(a["drawdown_maximo"], b["drawdown_maximo"])

    def test_la_cobertura_publicada_coincide_con_lo_valuado(self):
        self.recon("2026-01-31", 1000.0, 0.94, al_costo=("FCI Balanz",))
        r = perf.performance(self.conn, self.uid, {}, "sp500", modo=twr.MODO_ESTIMADO)
        self.assertAlmostEqual(r["cobertura_reconstruccion"], 0.94, places=3)
        self.assertIn("FCI Balanz", r["instrumentos_al_costo"])
        self.assertEqual(r["modo"], twr.MODO_ESTIMADO)

    def test_el_endpoint_acepta_el_modo(self):
        from fastapi.testclient import TestClient
        self.recon("2026-01-31", 1000.0, 0.88)
        self.recon("2026-02-28", 1100.0, 0.88)
        main._bench_cache["data"] = {"sp500": {}}
        main._bench_cache["ts"] = 9e18
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            cli = TestClient(main.app)
            cert = cli.get("/api/insights/performance?modo=certero").json()
            est = cli.get("/api/insights/performance?modo=estimado").json()
        finally:
            main.app.dependency_overrides.clear()
        self.assertEqual(cert["modo"], "certero")
        self.assertEqual(est["modo"], "estimado")
        self.assertIsNone(cert["twr"])          # parcial: no es certero
        self.assertIsNotNone(est["twr"])        # pero sí estimado


class CedearEnDolaresTest(_Base):
    """B-4 · un CEDEAR que cotiza en dólares se valúa por su SUBYACENTE: no hace
    falta el precio local ni el CCL histórico."""

    def test_el_ratio_convierte_a_acciones_equivalentes(self):
        import scripts.backfill_historical_mtm as bf
        orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda pk, si: ({"2024-08": 40.0} if pk == "BAC" else {})
        try:
            px = bf._precio_por_subyacente("BAC", "2024-08", "2024-01-01")
        finally:
            bf._fetch_monthly_close = orig
            bf._HIST_CACHE.clear()
        # ratio 4 → cada CEDEAR es 1/4 de acción → 40/4 = 10 USD
        self.assertAlmostEqual(px, 10.0, places=6)

    def test_un_activo_que_no_es_cedear_usd_devuelve_None(self):
        import scripts.backfill_historical_mtm as bf
        self.assertIsNone(bf._precio_por_subyacente("AAPL", "2024-08", "2024-01-01"))

    def test_ya_no_se_saltea_el_cedear_en_dolares(self):
        """Estaba en la lista de salteados por el camino largo (precio local ÷ CCL),
        y por eso caía al costo. Se verifica el COMPORTAMIENTO, no el texto."""
        import scripts.backfill_historical_mtm as bf
        llamados = []
        orig = bf._fetch_monthly_close

        def espia(pk, si):
            llamados.append(pk)
            return {"2024-08": 40.0}
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = espia
        try:
            px = bf._precio_por_subyacente("BAC", "2024-08", "2024-01-01")
        finally:
            bf._fetch_monthly_close = orig
            bf._HIST_CACHE.clear()
        self.assertIsNotNone(px)                 # ya no cae al costo
        self.assertEqual(llamados, ["BAC"])      # pidió el SUBYACENTE, no "BAC.BA"

    def test_lo_que_SI_sigue_al_costo_es_lo_que_no_tiene_serie(self):
        """FCI y bonos de data912: no hay fuente histórica, así que van al costo y
        se declaran en la cobertura."""
        import scripts.backfill_historical_mtm as bf
        bf._HIST_CACHE.clear()
        self.assertEqual(bf._fetch_monthly_close("FCI:Balanz Money Market", "2024-01-01"), {})


if __name__ == "__main__":
    unittest.main()
