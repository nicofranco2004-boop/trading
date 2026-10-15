"""Reportes: el mejor y el peor mes de cada año los elige el servidor, sin mezclar bases.

La fila de cada año de Reportes ("Mejor mes" / "Peor mes") tomaba el máximo y el
mínimo de los `delta_pct` de sus meses en la pantalla, sin mirar `basis`. Un mes
contable —el de alta, o uno sin fotos— entra con ~0 % aunque la cartera se haya
movido, y competía contra los meses medidos a mercado. En una cartera que cayó
todos los meses, el "Mejor mes" publicado era ese 0,0 % plano de la contabilidad.

Ahora `/api/reports/timeline` manda `ranking_por_anio`, elegido con
`twr.mejor_y_peor_mes` sobre LOS MISMOS números que dibuja cada barra.

La cuenta entra por las puertas reales: un import (`/api/imports/preview` +
`/confirm`), que dispara la reconstrucción a precio de mercado de cada fin de mes
(como en producción). Lo único reemplazado es lo que sale a internet: los cierres
mensuales de Yahoo (fijados para hacer la cuenta a mano) y el benchmark.

    SPY:  ene 100 · feb 95 (−5 %) · mar 76 (−20 %) · abr 74,48 (−2 %) · después plano
    Cuenta: US$10.000 depositados y 100 SPY comprados a 100 el 10/01/2025. Nada más.
"""
import io
import os
import sys
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MESES = [f"{2025 + (i // 12)}-{i % 12 + 1:02d}" for i in range(21)]   # 2025-01 … 2026-09
SPY = {ym: 74.48 for ym in MESES}
SPY.update({"2025-01": 100.0, "2025-02": 95.0, "2025-03": 76.0, "2025-04": 74.48})


class MejorYPeorMesDeReportes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(main.app)
        conn = main.get_db()
        cls.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"ranking-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (cls.uid, "IBKR", "USD"))
        conn.commit()
        conn.close()
        cls.h = {"Authorization": f"Bearer {main.create_token(cls.uid)}"}
        fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = (
            lambda key, start: dict(SPY) if key.upper().startswith("SPY") else {})
        try:
            with mock.patch.object(main, "_fetch_data912_bonds", return_value={}):
                csv = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
                       "2025-01-10,DEPOSITO,IBKR,,,,10000,,,0,USD,\n"
                       "2025-01-10,COMPRA,IBKR,SPY,100,100,10000,,,0,USD,\n").encode()
                p = cls.http.post("/api/imports/preview",
                                  files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                                  data={"format": "rendi_generic", "broker": "IBKR"},
                                  headers=cls.h)
                assert p.status_code == 200, p.text
                c = cls.http.post("/api/imports/confirm",
                                  json={"session_id": p.json()["session_id"],
                                        "skip_row_indices": [], "aprobar_tickers": []},
                                  headers=cls.h)
                assert c.status_code == 200, c.text
                cls._esperar_reconstruccion()
                # Lo que pide la pantalla al abrir: no cambia la contabilidad.
                assert cls.http.get("/api/monthly", headers=cls.h).status_code == 200
                cls._esperar_reconstruccion()
        finally:
            bf._fetch_monthly_close = fetch_orig
            bf._HIST_CACHE.clear()
        cls.timeline = cls._pedir("global")

    @classmethod
    def _pedir(cls, broker):
        # Lo mismo que pide Reportes al abrir (`useReportsTimeline`, 36 meses).
        with mock.patch.object(main, "_bench_para_reportes", return_value={}):
            r = cls.http.get(f"/api/reports/timeline?broker={broker}&months=36"
                             "&modo=certero&moneda=usd", headers=cls.h)
        assert r.status_code == 200, r.text
        return r.json()

    @classmethod
    def _esperar_reconstruccion(cls):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if (cls.uid not in main._MTM_RUNNING and cls.uid not in main._MTM_FILA
                        and not main._MTM_FILA_ACTIVA):
                    return
            time.sleep(0.02)
        raise AssertionError("la reconstrucción no terminó en 60 s")

    def _barras(self, data, anio):
        """Lo que la fila del año usa: los meses relevantes con número."""
        return {r["period_key"]: r["metrics"] for r in data["reports"]
                if r["period_key"].startswith(anio) and r["is_relevant"]
                and r["metrics"]["delta_pct"] is not None}

    # ── 0. el caso discrimina ────────────────────────────────────────────────

    def test_la_regla_vieja_publicaba_el_cero_contable_como_mejor_mes(self):
        """Sin esto el test no probaría nada. Enero (el mes de alta) llega como
        barra contable en 0 %, y los tres meses de mercado son negativos: el
        máximo a ciegas de la pantalla vieja era ese 0 % de la contabilidad."""
        barras = self._barras(self.timeline, "2025")
        self.assertEqual(barras["2025-01"]["basis"], "contable")
        self.assertAlmostEqual(barras["2025-01"]["delta_pct"], 0.0, places=2)
        for ym in ("2025-02", "2025-03", "2025-04"):
            self.assertEqual(barras[ym]["basis"], "mercado", ym)
            self.assertLess(barras[ym]["delta_pct"], 0, ym)
        mejor_viejo = max(barras, key=lambda k: barras[k]["delta_pct"])
        self.assertEqual(mejor_viejo, "2025-01")

    # ── 1. lo que recibe la pantalla ─────────────────────────────────────────

    def test_el_ranking_del_anio_no_mezcla_bases(self):
        rk = self.timeline["ranking_por_anio"]["2025"]
        self.assertEqual(rk["base"], "mercado")
        self.assertEqual(rk["mejor"]["mes"], "2025-04")
        self.assertAlmostEqual(rk["mejor"]["pct"], -2.0, places=2)
        self.assertEqual(rk["peor"]["mes"], "2025-03")
        self.assertAlmostEqual(rk["peor"]["pct"], -20.0, places=2)
        self.assertNotIn("2025-01", [m["mes"] for m in rk["meses"]])
        # Quedó afuera un mes que no es de mercado: la pantalla tiene que decir
        # "a precio de mercado" porque el mejor no es la barra más alta.
        self.assertEqual(rk["sin_medir_a_mercado"], 1)
        self.assertEqual((rk["positivos"], rk["total"]), (0, 3))

    def test_el_ranking_usa_los_numeros_de_las_barras(self):
        """El "Mejor mes" escrito debajo tiene que ser una de las barras de
        arriba, al centavo: dos números para el mismo mes en la misma fila
        serían dos verdades."""
        barras = self._barras(self.timeline, "2025")
        rk = self.timeline["ranking_por_anio"]["2025"]
        for m in (rk["mejor"], rk["peor"]):
            self.assertEqual(m["pct"], barras[m["mes"]]["delta_pct"])
            self.assertEqual(m["base"], barras[m["mes"]]["basis"])

    def test_sin_meses_de_mercado_el_ranking_dice_que_es_contable(self):
        """Filtrado por broker no hay fotos propias: todo es contable. El
        ranking existe, pero dice de qué está hecho."""
        data = self._pedir("IBKR")
        barras = self._barras(data, "2025")
        self.assertTrue(barras)
        self.assertTrue(all(b["basis"] == "contable" for b in barras.values()), barras)
        rk = data["ranking_por_anio"]["2025"]
        self.assertEqual(rk["base"], "contable")
        self.assertEqual(rk["total"], len(barras))
        self.assertEqual(rk["sin_medir_a_mercado"], rk["total"])


if __name__ == "__main__":
    unittest.main()
