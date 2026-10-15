"""El rendimiento de CADA MES sale del motor, a mercado — no de la contabilidad.

Para un mes cerrado `monthly_entries` está AL COSTO (`_repair_monthly_chain` deja
`capital_final = capital_inicio + flujos + pnl_realized`). Una cartera que compró
y no vendió da ~0 % todos los meses en esa tabla, aunque el precio haya subido
20 % un mes y bajado 25 % el siguiente. Cinco lectores elegían el mejor y el peor
mes con ese número: los paquetes de la IA de evolución, reportes, dashboard y
métricas pro, y los slides del Wrapped. El acumulado ya se le pedía al motor (F6);
el mes no.

La cuenta entra por las puertas reales: un import (`/api/imports/preview` +
`/confirm`), que dispara la reconstrucción a precio de mercado de cada fin de mes
(`scripts/backfill_historical_mtm.py`, en su hilo, como en producción). Lo único
reemplazado es lo que sale a internet: los cierres mensuales de Yahoo, fijados
para poder hacer la cuenta a mano. Se lee por donde leen la IA y el Wrapped.

    SPY:  ene 100 · feb 120 (+20 %) · mar 90 (−25 %) · abr 99 (+10 %) · después plano
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
import twr  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MESES = [f"{2025 + (i // 12)}-{i % 12 + 1:02d}" for i in range(21)]   # 2025-01 … 2026-09
SPY = {ym: 99.0 for ym in MESES}
SPY.update({"2025-01": 100.0, "2025-02": 120.0, "2025-03": 90.0, "2025-04": 99.0})

# Lo que se movió la cartera (100 SPY, sin caja) entre el cierre del mes anterior
# y el del mes. Ningún aporte después de enero.
ESPERADO = {"2025-02": 20.0, "2025-03": -25.0, "2025-04": 10.0, "2025-05": 0.0}


class RendimientoDeCadaMes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(main.app)
        conn = main.get_db()
        cls.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"meses-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
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

    def _conn(self):
        conn = main.get_db()
        self.addCleanup(conn.close)
        return conn

    # ── 0. el caso discrimina: la contabilidad dice ~0 % ────────────────────

    def test_la_contabilidad_de_esos_meses_dice_cero(self):
        """Sin esto el test no probaría nada: si la tabla ya trajera el mercado,
        el lector viejo también pasaría."""
        conn = self._conn()
        for ym in ("2025-02", "2025-03", "2025-04"):
            r = conn.execute(
                "SELECT capital_inicio, capital_final, deposits, withdrawals "
                "FROM monthly_entries WHERE user_id=? AND broker='global' "
                "AND year=? AND month=?", (self.uid, int(ym[:4]), int(ym[5:]))).fetchone()
            self.assertIsNotNone(r, ym)
            ret = twr.retorno_mensual(r["capital_inicio"], r["capital_final"],
                                      r["deposits"] - r["withdrawals"])
            self.assertAlmostEqual(ret or 0.0, 0.0, places=4, msg=ym)

    # ── 1. la función ───────────────────────────────────────────────────────

    def test_cada_mes_se_mide_a_mercado(self):
        meses = {m["mes"]: m for m in twr.rendimientos_mensuales(self._conn(), self.uid)}
        for ym, esperado in ESPERADO.items():
            self.assertEqual(meses[ym]["base"], "mercado", meses[ym])
            self.assertAlmostEqual(meses[ym]["pct"], esperado, places=4, msg=ym)
        # El monto del mes: lo que se movió la cartera, sin aportes.
        self.assertAlmostEqual(meses["2025-02"]["resultado_usd"], 2000.0, places=2)
        self.assertAlmostEqual(meses["2025-03"]["resultado_usd"], -3000.0, places=2)

    def test_el_mes_de_alta_no_se_mide_y_dice_por_que(self):
        """Enero no tiene cierre anterior: no hay número de mercado, y la
        contabilidad tampoco lo mide (el mes de alta no se mide). Se dice."""
        ene = twr.rendimientos_mensuales(self._conn(), self.uid)[0]
        self.assertEqual(ene["mes"], "2025-01")
        self.assertIsNone(ene["pct"])
        self.assertEqual(ene["motivo"], "mes_sin_cierre_anterior")
        self.assertTrue(ene["motivo_texto"])

    # ── 2. lo que lee la IA ─────────────────────────────────────────────────

    def test_paquete_de_evolucion_del_insights(self):
        from ai.builders import insights_evolution
        p = insights_evolution.build(self._conn(), self.uid, window_days=3650)
        self.assertEqual(p["monthly_base"], "mercado")
        self.assertEqual(p["best_month"]["month"], "2025-02")
        self.assertEqual(p["best_month"]["return_pct"], 20.0)
        self.assertEqual(p["worst_month"]["month"], "2025-03")
        self.assertEqual(p["worst_month"]["return_pct"], -25.0)

    def test_paquete_de_reportes(self):
        from ai.builders import reports
        p = reports.build(self._conn(), self.uid, year=2025)
        self.assertEqual(p["months_base"], "mercado")
        self.assertEqual(p["best_month"], {"month": "2025-02", "delta_pct": 20.0})
        self.assertEqual(p["worst_month"], {"month": "2025-03", "delta_pct": -25.0})

    def test_paquete_de_la_evolucion_del_dashboard(self):
        from ai.builders import dashboard_evolution
        p = dashboard_evolution.build(self._conn(), self.uid, period_days=3650)
        self.assertEqual(p.get("meses_base"), "mercado", p)
        self.assertEqual(p["best_month"], {"month": "2025-02", "pct": 0.2})
        self.assertEqual(p["worst_month"], {"month": "2025-03", "pct": -0.25})

    def test_paquete_de_metricas_pro(self):
        """`pnl_realized + pnl_unrealized` de la fila no es lo que ganaste ese mes."""
        from ai.builders import metrics_pro_card
        p = metrics_pro_card.build(self._conn(), self.uid, code="sharpe", value=1.0)
        rango = p["context"]["monthly_pnl_range"]
        self.assertEqual(rango["base"], "mercado")
        self.assertAlmostEqual(rango["worst_usd"], -3000.0, places=2)
        self.assertAlmostEqual(rango["best_usd"], 2000.0, places=2)

    # ── 3. lo que se comparte como imagen ───────────────────────────────────

    def test_el_wrapped_dice_el_mes_que_de_verdad_fue_el_mejor_y_el_peor(self):
        r = self.http.get("/api/wrapped/2025", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        slides = {s["code"]: s for s in r.json()["slides"]}
        self.assertIn("best_month", slides)
        self.assertEqual(slides["best_month"]["metric"]["label"], "FEBRERO")
        self.assertEqual(slides["best_month"]["metric"]["value"], "+20,00%")
        self.assertEqual(slides["best_month"]["base"], "mercado")
        self.assertIn("worst_month", slides, "con un −25 % el slide del peor mes no puede faltar")
        self.assertEqual(slides["worst_month"]["metric"]["label"], "MARZO")
        self.assertEqual(slides["worst_month"]["metric"]["value"], "−25,00%")
        # El intro anuncia el MISMO mejor mes que el slide.
        intro = {s["label"]: s["value"] for s in slides["intro"]["stats"]}
        self.assertEqual(intro.get("Mejor mes"), "Febrero")


class SinMercadoSeDiceContable(unittest.TestCase):
    """Sin fotos a mercado, el ranking sale de la contabilidad y lo DICE."""

    def test_ranking_contable_etiquetado(self):
        filas = [
            {"year": 2026, "month": 1, "capital_inicio": 10000, "capital_final": 10500,
             "deposits": 0, "withdrawals": 0},
            {"year": 2026, "month": 2, "capital_inicio": 10500, "capital_final": 10000,
             "deposits": 0, "withdrawals": 0},
        ]
        rk = twr.mejor_y_peor_mes(twr.meses_contables(filas))
        self.assertEqual(rk["base"], "contable")
        self.assertEqual(rk["mejor"]["mes"], "2026-01")
        self.assertEqual(rk["peor"]["mes"], "2026-02")

    def test_no_se_mezclan_reglas(self):
        """Un mes contable plano no puede ser el "peor" al lado de meses de mercado."""
        meses = [
            {"mes": "2026-01", "pct": 0.0, "base": "contable"},
            {"mes": "2026-02", "pct": 5.0, "base": "mercado"},
            {"mes": "2026-03", "pct": 2.0, "base": "mercado"},
            {"mes": "2026-04", "pct": None, "base": None},
        ]
        rk = twr.mejor_y_peor_mes(meses)
        self.assertEqual(rk["base"], "mercado")
        self.assertEqual(rk["peor"]["mes"], "2026-03")
        self.assertEqual(rk["total"], 2)
        self.assertEqual(rk["sin_medir_a_mercado"], 2)


if __name__ == "__main__":
    unittest.main()
