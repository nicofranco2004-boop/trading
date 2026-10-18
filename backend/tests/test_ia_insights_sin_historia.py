"""El paquete de la IA de Análisis no afirma nada que la contabilidad al costo no sabe.

Medido el 2026-10-14 con la cuenta "compra y mantiene en pesos": depósito de
$10 M y siete compras con fecha de hace un año, cargados a mano. La cartera
ganaba en pesos, pero sin fotos a precio real del pasado la única historia es
la contabilidad (`monthly_entries`), que para un mes cerrado está AL COSTO. El
paquete `ai/builders/insights.py` componía esa contabilidad por su cuenta: le
pasaba a la IA `twr_pct = 0,0` y, contra la inflación, un exceso negativo — "la
inflación te ganó" — mientras la pantalla decía "sin historia".

Ahora el número sale de `twr.rendimiento_publicable` (el mismo motor que la
pantalla) con su procedencia (`twr_base`), y la comparación contra la inflación
y el S&P sólo se hace con un rendimiento medido a mercado.

La cuenta entra por las puertas reales (`/api/brokers`, `/api/cash/flow`,
`/api/positions`, `/api/monthly`). Lo único fijado a mano es lo que sale a
internet: la serie del dólar y los índices del caché de benchmarks.
"""
import os
import sys
import unittest
import uuid
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FECHA = "2025-10-13"
# De 2025-10 hasta el mes de HOY (como el día en que se escribió, 2026-10): con la
# serie cortada en 2026-10 la inflación del período se quedaba sin meses y la
# prueba se ponía roja sola (medido: ya en enero de 2028). No llega al futuro: un
# dólar con fecha de mañana sería «el último» para quien lo busque.
_HOY = date.today()
MESES = [f"{2025 + (i // 12)}-{i % 12 + 1:02d}"
         for i in range(9, (_HOY.year - 2025) * 12 + _HOY.month)]   # 2025-10 … el mes de hoy


class LaIaNoComparaLaContabilidadAlCosto(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM fx_rates_daily WHERE date >= '2025-09-01' AND date <= ?",
                         (MESES[-1] + "-31",))
            for i, ym in enumerate(MESES):
                v = 1400.0 * 1.02 ** i
                conn.execute(
                    "INSERT INTO fx_rates_daily (date, blue_venta, blue_compra, mep_venta, mep_compra, source) "
                    "VALUES (?,?,?,?,?,'test')", (ym + "-01", v, v, v, v))
            self.uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                (f"ia-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
            conn.commit()
        finally:
            conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        # Lo que trae /api/benchmarks: inflación de 2 % por mes, S&P +1 % por mes.
        bench = {"inflation_ar": {ym: 2.0 for ym in MESES},
                 "sp500": {ym: 100.0 * 1.01 ** i for i, ym in enumerate(MESES)}}
        p = mock.patch.dict(main._bench_cache, {"data": bench})
        p.start()
        self.addCleanup(p.stop)

        def ok(r):
            self.assertEqual(r.status_code, 200, r.text)
            return r.json()
        ok(self.http.post("/api/brokers", json={"name": "Balanz", "currency": "ARS"}, headers=self.h))
        ok(self.http.post("/api/cash/flow", json={"broker_name": "Balanz", "direction": "deposit",
                                                  "amount": 10_000_000, "date": FECHA}, headers=self.h))
        ok(self.http.post("/api/positions", json={"broker": "Balanz", "asset": "GGAL", "quantity": 300,
                                                  "buy_price": 4750, "invested": 300 * 4750,
                                                  "entry_date": FECHA}, headers=self.h))
        ok(self.http.get("/api/monthly", headers=self.h))

    def _paquete(self):
        from ai.builders import insights
        conn = main.get_db()
        try:
            return insights.build(conn, self.uid)
        finally:
            conn.close()

    def test_sin_fotos_a_mercado_no_hay_veredicto_contra_la_inflacion(self):
        p = self._paquete()
        vs = p["vs_benchmarks"]
        self.assertIsNone(vs["delta_inflation_pp"], vs)
        self.assertIsNone(vs["retorno_ars_pct"], vs)
        self.assertIsNone(vs["delta_sp500_pp"], vs)
        # La inflación y el S&P se siguen informando: lo que no se hace es la resta.
        self.assertIsNotNone(vs["inflation_ar_pct"])

    def test_el_numero_dice_de_donde_sale(self):
        p = self._paquete()
        self.assertIn("twr_base", p)
        self.assertNotEqual(p["twr_base"], "mercado")

    def test_es_el_mismo_numero_que_el_motor(self):
        import twr
        from datetime import date, timedelta
        conn = main.get_db()
        try:
            esperado = twr.rendimiento_publicable(
                conn, self.uid, desde=(date.today() - timedelta(days=365)).isoformat())
        finally:
            conn.close()
        self.assertEqual(self._paquete()["twr_pct"], esperado["pct"])


if __name__ == "__main__":
    unittest.main()
