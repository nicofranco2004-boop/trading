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
    def test_la_cobertura_NO_filtra_nada(self):
        """El criterio principal: con 0,70 / 0,82 / 0,88 / 0,94 / 0,99 el modo por
        DEFECTO muestra la curva en los cinco, y declara la cobertura. Un piso
        —fuera 0,70 o 0,995— le esconde la curva entera al que no llega, que es lo
        contrario de lo que hace falta."""
        for cov in (0.70, 0.8214, 0.88, 0.94, 0.99):
            with self.subTest(cobertura=cov):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.recon("2026-01-31", 1000.0, cov, al_costo=("FCI Balanz",))
                self.recon("2026-02-28", 1100.0, cov, al_costo=("FCI Balanz",))
                c = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
                idx = [p["index"] for p in c["curva"]]
                self.assertGreater(max(idx), min(idx))     # la curva SE VE
                self.assertAlmostEqual(c["cobertura_reconstruccion"], cov, places=4)
                self.assertIn("FCI Balanz", c["instrumentos_al_costo"])

    def test_una_cartera_mixta_argentina_al_55_ve_su_curva(self):
        """55% es la cobertura medida de una cartera mixta (CEDEARs + bonos + FCI).
        Con el piso de 0,995 no veía NADA en el modo por defecto."""
        self.recon("2026-01-31", 1000.0, 0.55, al_costo=("AL30", "FCI Balanz"))
        self.recon("2026-02-28", 1100.0, 0.55, al_costo=("AL30", "FCI Balanz"))
        c = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
        idx = [p["index"] for p in c["curva"]]
        self.assertGreater(max(idx), min(idx))
        self.assertEqual(c["instrumentos_al_costo"], ["AL30", "FCI Balanz"])

    def test_lo_que_separa_los_modos_es_la_cadena_contable(self):
        """No la cobertura. CERTERO = todo lo valuado a PRECIO REAL (a cualquier
        cobertura). ESTIMADO = además la cadena contable, que es el "aproximado
        que puede estar mal y lo sabés" — y nunca es el default, porque de ahí
        salía el −45% del caso 452."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,?,?,?,0,'import')",
            (self.uid, "2025-12-31", 99999.0, 99999.0))
        self.recon("2026-01-31", 1000.0, 0.55)
        self.recon("2026-02-28", 1100.0, 0.55)
        self.conn.commit()
        cert = twr.serie_medible(self.conn, self.uid, modo=twr.MODO_CERTERO)
        est = twr.serie_medible(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertEqual(len(cert["puntos"]), 2)      # la contable NO entra
        self.assertEqual(len(est["puntos"]), 3)       # en estimado sí, a la LÍNEA
        # ...pero jamás como pico ni denominador, ni siquiera en estimado.
        self.assertFalse(any(p["apto"] for p in est["puntos"]
                             if p["clase"] == twr.SINTETICO_COSTO))

    def test_una_reconstruccion_a_precio_real_SI_es_apta_en_certero(self):
        """Un CEDEAR o una acción reconstruidos son exactos: entran en CERTERO."""
        self.recon("2026-01-31", 1000.0, 1.0)
        self.recon("2026-02-28", 1100.0, 1.0)
        c = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
        self.assertAlmostEqual(c["twr"], 0.10, places=6)

    def test_el_default_no_deja_entrar_la_cadena_contable(self):
        """La garantía que no se puede perder: el defecto original salía de
        encadenar la foto FABRICADA por el import."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,?,?,?,0,'import')",
            (self.uid, "2026-07-31", 139570.56, 139570.56))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,130.8,'cron',1400,'[]')",
            (self.uid, "2026-08-24", 73604.02, 73604.02))
        self.conn.commit()
        c = twr.curva_indexada(self.conn, self.uid)      # default = certero
        self.assertEqual(len(c["puntos"]), 1)
        self.assertIsNone(c["twr"])
        self.assertIsNone(c["drawdown_maximo"])

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
        # ⚠️ ESTE ASSERT PEDÍA LO CONTRARIO y por eso la suite no cazaba el bug:
        # fijaba como correcto que una cobertura del 88% dejara SIN CURVA al modo
        # por defecto. Con 0,88 el usuario tiene que VER su curva y leer qué parte
        # es estimada; esconderla es justo lo que había que eliminar.
        # La curva se ve en los dos; el número, sólo por encima del piso de medición.
        self.assertTrue(len(cert["curva"]) > 0)
        self.assertTrue(len(est["curva"]) > 0)
        self.assertAlmostEqual(cert["cobertura_reconstruccion"], 0.88, places=3)


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
