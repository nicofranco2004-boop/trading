"""La pestaña Cobros: lo que le pagaron al usuario sus inversiones, en dólares del DÍA.

Todo entra por los caminos reales —el importador (preview + confirm, que corre el
persister y el recálculo) y la bandeja de cupones de Cartera
(POST /api/bonds/cashflow/pago)— y se mira por GET /api/cobros, lo mismo que pide
la pantalla.

Lo que se prueba:
  · Un cobro en pesos vale los dólares del día en que se cobró, no los de hoy:
    $14.500 del día en que el dólar estaba a 1.450 son US$ 10, aunque el dólar
    del usuario hoy sea 2.000.
  · Los cobros son el mismo "Cobrado" de Movimientos (dividendos + intereses de
    /api/movements): las dos pantallas leen las mismas filas.
  · La amortización sola de un bono NO es un cobro: es capital que vuelve.
  · El pago que trae cupón y amortización en UN renglón ("Renta y
    Amortización", con o sin cantidad) no va entero a cobros ni se pierde:
    viaja en `pagos_mixtos` para que la pantalla separe el cupón con el
    cronograma (frontend/src/utils/cobros.js · cuponDelPago).

Las sumas (mes, año, activo) las hace la pantalla y se prueban en
frontend/src/utils/cobros.test.js.

Las fechas salen de HOY (no son fijas): una prueba con fecha escrita a mano
vence sola cuando el año cambia.

Corre con: cd backend && python3 -m pytest tests/test_cobros.py
"""
import io
import json
import os
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
        self.assertEqual(c["cobros"], [{"fecha": hoy, "activo": "GGAL", "tipo": "DIVIDEND", "usd": 10.0}])
        self.assertEqual(c["hoy"], hoy)
        self.assertEqual(c["dias_hasta_el_pago"], 21)

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
        self.assertEqual([(x["activo"], round(x["usd"], 2)) for x in c["cobros"]], [("TX26", 20.0)])   # 25.000 / 1.250

    # ── el mismo número que Movimientos ─────────────────────────────────────
    def test_los_cobros_son_el_cobrado_de_movimientos_y_la_amortizacion_no_cuenta(self):
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
        self.assertAlmostEqual(sum(x["usd"] for x in c["cobros"]), 30 + 5 + 4, places=2)
        self.assertAlmostEqual(sum(x["usd"] for x in c["cobros"]), self._cobrado_de_movimientos(), places=2)
        self.assertEqual(c["pagos_mixtos"], [])

    def test_la_amortizacion_sola_importada_no_es_un_cobro(self):
        """El archivo trae el cupón y la amortización en renglones separados: el de
        amortización (capital que vuelve) no entra en ninguna de las dos listas, y
        Movimientos y el CSV del contador lo llaman amortización."""
        hoy = self.hoy.isoformat()
        self._importar(
            f"{hoy},RENTA,{self.BROKER},AL30,,,4,,,,USD,Renta AL30\n"
            f"{hoy},AMORTIZACION,{self.BROKER},AL30,,,40,,,,USD,Amortización AL30\n")
        r = self.client.get("/api/movements", headers=self.h)
        tipos = sorted((m["type"], m["amount_usd"]) for m in r.json() if m["asset"] == "AL30")
        self.assertEqual(tipos, [("AMORTIZATION", 40), ("DIVIDEND", 4)])
        c = self._cobros()
        self.assertEqual([(x["activo"], x["usd"]) for x in c["cobros"]], [("AL30", 4.0)])
        self.assertEqual(c["pagos_mixtos"], [])
        self.assertAlmostEqual(sum(x["usd"] for x in c["cobros"]), self._cobrado_de_movimientos(), places=2)
        with mock.patch.object(main, "_gate_export", lambda *a, **k: None):
            r = self.client.get("/api/export/transactions.csv", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        al30 = sorted(l.split(",")[1] for l in r.text.splitlines() if ",AL30," in l)
        self.assertEqual(al30, ["AMORTIZACIÓN", "DIVIDENDO"], r.text)

    # ── cupón y amortización en un solo renglón ──────────────────────────────
    def test_renta_y_amortizacion_sin_cantidad_viaja_como_pago_mixto(self):
        """Balanz sin cantidad: "Renta y Amortización" es UN renglón con las dos
        partes. No va entero a cobros (inflaba el cupón) ni se pierde: viaja
        aparte para que la pantalla separe el cupón con el cronograma."""
        hoy = self.hoy.isoformat()
        self._importar(f"{hoy},DIVIDENDO,{self.BROKER},AL30,,,43.20,,,,USD,Renta y Amortización AL30\n")
        c = self._cobros()
        self.assertEqual(c["cobros"], [])
        self.assertEqual(c["pagos_mixtos"], [{"fecha": hoy, "activo": "AL30", "tipo": "MIXTO", "usd": 43.2}])

    def test_renta_y_amortizacion_con_cantidad_tambien(self):
        """Balanz con cantidad: el lector lo importa como una VENTA de los
        nominales devueltos (`cobros_bonos.ventas_que_son_amortizacion`). Esos
        cupones antes no aparecían en ningún lado de Cobros."""
        hoy = self.hoy.isoformat()
        compra = (self.hoy.replace(day=1) if self.hoy.day > 1 else self.hoy).isoformat()
        self._importar(
            f"{compra},COMPRA,{self.BROKER},AL30,1000,0.60,,,,,USD,\n"
            f"{hoy},VENTA,{self.BROKER},AL30,80,0.54,,,,,USD,Renta y Amortización AL30\n")
        c = self._cobros()
        self.assertEqual(c["cobros"], [])
        self.assertEqual([(x["activo"], round(x["usd"], 2)) for x in c["pagos_mixtos"]], [("AL30", 43.2)])

    # ── el rango ────────────────────────────────────────────────────────────
    def test_cobros_desde_el_anio_anterior_y_totales_de_los_viejos(self):
        ant = self.anio - 1
        hoy = self.hoy.isoformat()
        self._importar(
            f"{hoy},DIVIDENDO,{self.BROKER},KO,,,50,,,,USD,\n"
            f"{ant}-01-01,DIVIDENDO,{self.BROKER},KO,,,20,,,,USD,\n"
            f"{ant - 2}-06-01,DIVIDENDO,{self.BROKER},KO,,,7,,,,USD,\n"
            f"{ant - 2}-07-01,DIVIDENDO,{self.BROKER},KO,,,8,,,,USD,\n")
        c = self._cobros()
        self.assertEqual([x["fecha"] for x in c["cobros"]], [f"{ant}-01-01", hoy])
        self.assertEqual(c["anios_previos"], [{"anio": ant - 2, "usd": 15.0}])

    def test_sin_cobros_todo_vacio(self):
        c = self._cobros()
        self.assertEqual((c["cobros"], c["pagos_mixtos"], c["anios_previos"]), ([], [], []))


# ═════════════════════════════════════════════════════════════════════════════
# "Cobrado" de Movimientos == total del año de Cobros, al centavo.
#
# Las dos pantallas suman con la misma función de la pantalla
# (frontend/src/utils/cobros.js · cobradoDe / resumirCobros), pero cada una
# arranca de SU pedido: Movimientos de /api/movements, Cobros de /api/cobros.
# Esta prueba arma un caso con los dos pagos mixtos de Balanz (sin cantidad y
# con cantidad), un dividendo en pesos, un interés y uno del año anterior,
# por el importador de verdad, y guarda lo que devuelven LOS DOS pedidos en
# frontend/src/utils/fixtures/cobrosYMovimientos.json. La prueba de la
# pantalla (cobrosYMovimientos.test.js) lee ese archivo y compara al centavo.
#
# Si el servidor cambia lo que devuelve, esta prueba falla hasta regenerar el
# archivo (REGENERAR_FIXTURE_COBROS=1): así el archivo no queda viejo sin que
# nadie se entere. "Hoy" está fijo (22/10/2026) para que no venza con la fecha.
FIXTURE = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "utils",
                       "fixtures", "cobrosYMovimientos.json")
CAMPOS_MOV = ("date", "type", "broker", "asset", "amount_usd", "currency", "fx_to_usd", "cobro", "notes")


class CobradoIgualEnLasDosPantallas(Cobros):
    def _escenario(self):
        self._dolar_del_dia("2026-05-20", 1180)
        self._dolar_del_dia("2026-03-10", 1100)
        self._importar(
            "2025-02-01,COMPRA,IOL,AL30,1000,0.60,,,,,USD,\n"
            "2025-02-01,COMPRA,IOL,GD30,1000,0.60,,,,,USD,\n"
            "2025-07-01,DIVIDENDO,IOL,KO,,,4,,,,USD,\n"
            "2026-01-09,VENTA,IOL,AL30,80,0.54,,,,,USD,Renta y Amortización AL30\n"
            "2026-03-10,INTERES,IOL,,,,20000,,,,ARS,Interés caución\n"
            "2026-04-01,DIVIDENDO,IOL,KO,,,4.10,,,,USD,\n"
            "2026-05-20,DIVIDENDO,IOL,GGAL,,,150000,,,,ARS,\n"
            "2026-07-09,DIVIDENDO,IOL,GD30,,,84.50,,,,USD,Renta y Amortización GD30\n")

    def test_los_dos_pedidos_quedan_guardados_para_la_prueba_de_la_pantalla(self):
        self._escenario()
        with mock.patch.object(main, "_iso_today", lambda: "2026-10-22"):
            cobros = self._cobros()
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        movs = sorted(({k: m.get(k) for k in CAMPOS_MOV} for m in r.json()),
                      key=lambda m: (m["date"] or "", m["type"], m["asset"] or ""))
        # Lo mínimo para que la comparación tenga sentido: los dos pagos mixtos
        # viajan marcados y no como cobros enteros.
        self.assertEqual(sorted(m["asset"] for m in movs if m["cobro"] == "mixto"), ["AL30", "GD30"])
        self.assertEqual(sorted(p["activo"] for p in cobros["pagos_mixtos"]), ["AL30", "GD30"])
        datos = {"movements": movs, "cobros": cobros}
        if os.environ.get("REGENERAR_FIXTURE_COBROS"):
            with open(FIXTURE, "w", encoding="utf-8") as fh:
                json.dump(datos, fh, ensure_ascii=False, indent=1, sort_keys=True)
                fh.write("\n")
        with open(FIXTURE, encoding="utf-8") as fh:
            guardado = json.load(fh)
        self.assertEqual(json.loads(json.dumps(datos)), guardado,
                         "El servidor devuelve otra cosa: correr con REGENERAR_FIXTURE_COBROS=1 "
                         "y volver a correr la prueba de la pantalla (cobrosYMovimientos.test.js).")

    # Las de la clase madre ya corrieron arriba.
    test_un_dividendo_en_pesos_vale_el_dolar_del_dia_en_que_se_cobro = None
    test_un_cupon_confirmado_en_la_bandeja_va_al_dolar_de_su_dia = None
    test_los_cobros_son_el_cobrado_de_movimientos_y_la_amortizacion_no_cuenta = None
    test_la_amortizacion_sola_importada_no_es_un_cobro = None
    test_renta_y_amortizacion_sin_cantidad_viaja_como_pago_mixto = None
    test_renta_y_amortizacion_con_cantidad_tambien = None
    test_cobros_desde_el_anio_anterior_y_totales_de_los_viejos = None
    test_sin_cobros_todo_vacio = None


if __name__ == "__main__":
    unittest.main()
