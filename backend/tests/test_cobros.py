"""La pestaña Cobros: lo que le pagaron al usuario sus inversiones, en dólares del DÍA.

Todo entra por los caminos reales —el importador (preview + confirm, que corre el
persister y el recálculo) y la bandeja de cupones de Cartera
(POST /api/bonds/cashflow/pago)— y se mira por GET /api/cobros, lo mismo que pide
la pantalla.

Lo que se prueba:
  · Un cobro en pesos vale los dólares del día en que se cobró, no los de hoy:
    $14.500 del día en que el dólar estaba a 1.450 son US$ 10, aunque el dólar
    del usuario hoy sea 2.000.
  · El total es el mismo "Cobrado" de Movimientos (dividendos + intereses de
    /api/movements): las dos pantallas leen las mismas filas.
  · La amortización de un bono NO es un cobro: es capital que vuelve.
  · La comparación con el año anterior es contra el MISMO PERÍODO (1/1 → hoy).

Las fechas salen de HOY (no son fijas): una prueba con fecha escrita a mano
vence sola cuando el año cambia.

Corre con: cd backend && python3 -m pytest tests/test_cobros.py
"""
import io
import unittest
import uuid
from unittest import mock
from datetime import date

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


class Cobros(unittest.TestCase):
    BROKER = "IOL"

    def setUp(self):
        self.client = TestClient(main.app)
        self.hoy = date.fromisoformat(main._iso_today())
        self.anio = self.hoy.year
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)",
            (f"cobros-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                     (self.uid, self.BROKER))
        # El dólar del usuario HOY: si algo dividiera por éste en vez del del día,
        # los montos darían otra cosa.
        conn.execute("INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?, 'tc_blue', '2000')",
                     (self.uid,))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── caminos reales ──────────────────────────────────────────────────────
    def _dolar_del_dia(self, fecha, tc):
        conn = main.get_db()
        conn.execute(
            "INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?, ?, ?, 'test')", (fecha, tc, tc))
        conn.commit()
        conn.close()

    def _importar(self, filas):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("cobros.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": self.BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", headers=self.h,
                             json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def _cobros(self):
        r = self.client.get("/api/cobros", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _cobrado_de_movimientos(self):
        """El KPI "Cobrado" de Movimientos: dividendos + intereses de /api/movements."""
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return sum(m["amount_usd"] or 0 for m in r.json() if m["type"] in ("DIVIDEND", "INTEREST"))

    # ── el dólar del día ────────────────────────────────────────────────────
    def test_un_dividendo_en_pesos_vale_el_dolar_del_dia_en_que_se_cobro(self):
        hoy = self.hoy.isoformat()
        self._dolar_del_dia(hoy, 1450)
        self._importar(f"{hoy},DIVIDENDO,{self.BROKER},GGAL,,,14500,,,,ARS,\n")
        c = self._cobros()
        # 14.500 / 1.450 (el del día) = 10. Con el del usuario hoy serían 7,25.
        self.assertAlmostEqual(c["total_anio"], 10.0, places=2)
        self.assertEqual(c["anio"], self.anio)
        self.assertAlmostEqual(c["por_mes"][self.hoy.month - 1]["anio"], 10.0, places=2)
        self.assertEqual([a["activo"] for a in c["por_activo"]], ["GGAL"])
        self.assertEqual(c["por_activo"][0]["tipos"], ["DIVIDEND"])
        self.assertEqual(len(c["ultimos_12_meses"]), 1)
        self.assertEqual(c["ultimos_12_meses"][0]["fecha"], hoy)

    def test_un_cupon_confirmado_en_la_bandeja_va_al_dolar_de_su_dia(self):
        """El cupón en pesos de la bandeja de Cartera: la fila guarda el dólar del
        día del cobro (`fx_for_date_detail`) y Cobros lo lee por `leer_cobro`."""
        hoy = self.hoy.isoformat()
        self._dolar_del_dia(hoy, 1250)
        r = self.client.post("/api/bonds/cashflow/pago", headers=self.h, json={
            "broker": self.BROKER, "asset": "TX26", "date": hoy,
            "coupon_amount": 25000, "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        c = self._cobros()
        self.assertAlmostEqual(c["total_anio"], 20.0, places=2)   # 25.000 / 1.250
        self.assertEqual([a["activo"] for a in c["por_activo"]], ["TX26"])

    # ── el mismo número que Movimientos ─────────────────────────────────────
    def test_el_total_es_el_cobrado_de_movimientos_y_la_amortizacion_no_cuenta(self):
        hoy = self.hoy.isoformat()
        self._dolar_del_dia(hoy, 1000)
        self._importar(
            f"{hoy},DIVIDENDO,{self.BROKER},KO,,,30,,,,USD,\n"
            f"{hoy},DIVIDENDO,{self.BROKER},GGAL,,,5000,,,,ARS,\n")
        # Un pago del cronograma con cupón Y amortización: sólo el cupón es cobro.
        r = self.client.post("/api/bonds/cashflow/pago", headers=self.h, json={
            "broker": self.BROKER, "asset": "AL30", "date": hoy,
            "coupon_amount": 4, "amort_amount": 40, "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        c = self._cobros()
        self.assertAlmostEqual(c["total_anio"], 30 + 5 + 4, places=2)
        self.assertAlmostEqual(c["total_anio"], self._cobrado_de_movimientos(), places=2)
        self.assertEqual([a["activo"] for a in c["por_activo"]], ["KO", "GGAL", "AL30"])
        self.assertAlmostEqual(sum(a["usd"] for a in c["por_activo"]), c["total_anio"], places=2)

    def test_la_amortizacion_importada_sin_cantidad_no_es_un_cobro(self):
        """Balanz/IOL mandan la amortización como un cobro sin cantidad; el
        importador la guarda como DIVIDEND y el persister la anota como
        'Amortización' (capital que vuelve). Movimientos tiene que decir lo mismo:
        antes la mostraba como "Dividendo" y la sumaba a lo cobrado."""
        hoy = self.hoy.isoformat()
        self._importar(
            f"{hoy},RENTA,{self.BROKER},AL30,,,4,,,,USD,Renta AL30\n"
            f"{hoy},AMORTIZACION,{self.BROKER},AL30,,,40,,,,USD,Amortización AL30\n")
        r = self.client.get("/api/movements", headers=self.h)
        tipos = sorted((m["type"], m["amount_usd"]) for m in r.json() if m["asset"] == "AL30")
        self.assertEqual(tipos, [("AMORTIZATION", 40), ("DIVIDEND", 4)])
        c = self._cobros()
        self.assertAlmostEqual(c["total_anio"], 4, places=2)
        self.assertAlmostEqual(c["total_anio"], self._cobrado_de_movimientos(), places=2)
        # El CSV para el contador lee las mismas filas: tampoco la llama dividendo.
        with mock.patch.object(main, "_gate_export", lambda *a, **k: None):
            r = self.client.get("/api/export/transactions.csv", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        al30 = sorted(l.split(",")[1] for l in r.text.splitlines() if ",AL30," in l)
        self.assertEqual(al30, ["AMORTIZACIÓN", "DIVIDENDO"], r.text)

    # ── contra el año anterior ──────────────────────────────────────────────
    def test_el_anio_anterior_se_compara_contra_el_mismo_periodo(self):
        ant = self.anio - 1
        hoy = self.hoy.isoformat()
        principio, fin = f"{ant}-01-01", f"{ant}-12-31"
        self._importar(
            f"{hoy},DIVIDENDO,{self.BROKER},KO,,,50,,,,USD,\n"
            f"{principio},DIVIDENDO,{self.BROKER},KO,,,20,,,,USD,\n"
            f"{fin},DIVIDENDO,{self.BROKER},KO,,,15,,,,USD,\n")
        c = self._cobros()
        self.assertAlmostEqual(c["total_anio"], 50, places=2)
        self.assertAlmostEqual(c["total_anterior"], 35, places=2)
        # El 31/12 del año anterior es posterior a "hoy hace un año", salvo que hoy
        # sea justo 31/12: entonces entra.
        esperado = 35 if (self.hoy.month, self.hoy.day) == (12, 31) else 20
        self.assertAlmostEqual(c["total_anterior_a_la_fecha"], esperado, places=2)
        self.assertAlmostEqual(c["por_mes"][0]["anterior"], 20, places=2)
        self.assertAlmostEqual(c["por_mes"][11]["anterior"], 15, places=2)
        self.assertEqual([y["anio"] for y in c["por_anio"]], [ant, self.anio])
        # La historia para el estimado: sólo los últimos 12 meses (hasta hoy).
        fechas = [u["fecha"] for u in c["ultimos_12_meses"]]
        self.assertIn(hoy, fechas)
        self.assertNotIn(principio, fechas)

    def test_sin_cobros_todo_en_cero(self):
        c = self._cobros()
        self.assertEqual(c["total_anio"], 0)
        self.assertEqual(c["por_activo"], [])
        self.assertEqual(len(c["por_mes"]), 12)
        self.assertEqual(c["ultimos_12_meses"], [])


if __name__ == "__main__":
    unittest.main()
