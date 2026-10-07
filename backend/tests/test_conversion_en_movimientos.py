"""Una conversión de moneda en Movimientos vale los DÓLARES que se compraron o vendieron.

REPORTE (2026-10-07, base de prueba local): "Comprar USD" de $15.400 a 10 USD
con TC 1539,65 aparecía en Movimientos como **"Venta IOL · ARS→USDT
US$23.710.610,00"**. Es 15.400 pesos × 1539,65: la pantalla leía la conversión
como una venta de acciones (cantidad × precio).

Medido por el camino real, había CUATRO formas rotas, no una:
  1. Comprar USD con el botón → pesos × TC (US$23.710.610 por US$10).
  2. Vender USD con el botón → los pesos cobrados rotulados en dólares
     (US$6.400 por US$4).
  3. Conversión importada sin columna de moneda — 533 de 534 en el backup de
     prod del 2026-08-16 — → los pesos como dólares (US$1.400.000 por US$1.000).
     El arreglo de `stamp_tx_gross_usd` sellaba bien `gross_amount_usd`, pero
     Movimientos sólo lo leía cuando la fila decía `currency='ARS'`.
  4. Cada mes con una conversión importada mostraba un "Depósito manual" en el
     broker en dólares y un "Retiro manual" en el de pesos que el usuario nunca
     hizo: Movimientos derivaba lo manual con una COPIA de la query de imports
     que no sabía de conversiones (el helper `_import_flows_for_period` sí).

Todo pasa por HTTP: el botón es POST /api/conversions, el importador es
preview + confirm (que corre el persister Y el recalc), y lo que se mira es
GET /api/movements, lo mismo que pide la pantalla.

Corre con: cd backend && python3 -m pytest tests/test_conversion_en_movimientos.py
"""
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


class ConversionEnMovimientos(unittest.TestCase):
    BROKER = "IOL"
    SIB = "IOL · USD"

    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)",
            (f"conv-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                     (self.uid, self.BROKER))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── caminos reales ──────────────────────────────────────────────────────
    def _deposito_pesos(self, monto):
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": self.BROKER, "direction": "deposit", "amount": monto,
            "tc_blue": 1400, "date": "2024-03-01"})
        self.assertEqual(r.status_code, 200, r.text)

    def _boton(self, direction, ars, usd, tc, broker=None):
        r = self.client.post("/api/conversions", headers=self.h, json={
            "from_broker": broker or self.BROKER, "direction": direction,
            "ars_amount": ars, "usd_amount": usd, "tc": tc, "kind": "MEP",
            "date": "2024-03-05"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _importar(self, filas):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("fx.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": self.BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", headers=self.h,
                             json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def _movimientos(self):
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _conversiones(self):
        return [m for m in self._movimientos()
                if m["type"] in ("FX_ARS_TO_USD", "FX_USD_TO_ARS")]

    def _pesos_en_pantalla(self, m):
        """Lo que muestra la vista en pesos: `amount_usd` × el TC sellado de la
        fila (resolveHistoricalFx usa `fx_to_usd` cuando la fila es ARS)."""
        self.assertEqual(m["currency"], "ARS", m)
        return m["amount_usd"] * m["fx_to_usd"]

    # ── 1 y 2: el botón ─────────────────────────────────────────────────────
    def test_comprar_usd_con_el_boton_vale_los_dolares_comprados(self):
        """El caso reportado: $15.400 a TC 1539,65 son ~US$10, no US$23.710.610."""
        self._deposito_pesos(100_000)
        self._boton("ars_to_usd", 15_400, 10, 1539.65)
        movs = self._movimientos()
        # Ninguna fila de la conversión puede salir como venta ni como compra.
        self.assertFalse(
            [m for m in movs if "→" in (m.get("asset") or "") and m["type"] in ("BUY", "SELL")],
            f"la conversión sigue saliendo como trade: {movs}")
        conv = self._conversiones()
        self.assertEqual(len(conv), 1, conv)
        m = conv[0]
        self.assertEqual(m["type"], "FX_ARS_TO_USD")
        # La fila no guarda los US$10 exactos que se acreditaron (el formulario
        # redondea), sino pesos y TC: 15.400 / 1539,65 = 10,0023.
        self.assertAlmostEqual(m["amount_usd"], 10.0, delta=0.01)
        self.assertAlmostEqual(self._pesos_en_pantalla(m), 15_400, places=2)
        self.assertEqual(m["broker"], self.BROKER)

    def test_vender_usd_con_el_boton_vale_los_dolares_vendidos(self):
        """US$4 vendidos a 1600 son US$4 (y $6.400 en la vista en pesos), no US$6.400."""
        self._deposito_pesos(100_000)
        self._boton("ars_to_usd", 15_400, 10, 1540)
        self._boton("usd_to_ars", 6_400, 4, 1600, broker=self.SIB)
        venta = [m for m in self._conversiones() if m["type"] == "FX_USD_TO_ARS"]
        self.assertEqual(len(venta), 1, venta)
        m = venta[0]
        self.assertAlmostEqual(m["amount_usd"], 4.0, places=6)
        self.assertAlmostEqual(self._pesos_en_pantalla(m), 6_400, places=2)
        # La ganancia cambiaria (vendió a 1600 lo que compró a 1540) sigue
        # viajando en la fila: 4 × (1600 − 1540) / 1600 = US$0,15.
        self.assertAlmostEqual(m["pnl_usd"], 0.15, places=2)

    # ── 3: el importador ────────────────────────────────────────────────────
    def test_conversion_importada_sin_moneda_no_muestra_pesos_como_dolares(self):
        self._importar(
            "2024-03-01,DEPOSITO,IOL,,,,2000000,,,,ARS,dep\n"
            "2024-03-02,CONVERSION_ARS_USD,IOL,,,,1400000,1000,1400,,,sin moneda\n")
        conv = self._conversiones()
        self.assertEqual(len(conv), 1, conv)
        m = conv[0]
        self.assertAlmostEqual(m["amount_usd"], 1000.0, places=6,
                               msg=f"muestra US${m['amount_usd']:,.0f} por US$1.000")
        self.assertAlmostEqual(self._pesos_en_pantalla(m), 1_400_000, places=2)

    def test_conversion_importada_con_moneda_vale_lo_mismo(self):
        self._importar(
            "2024-03-01,DEPOSITO,IOL,,,,2000000,,,,ARS,dep\n"
            "2024-03-02,CONVERSION_ARS_USD,IOL,,,,1400000,1000,1400,,ARS,con moneda\n")
        (m,) = self._conversiones()
        self.assertAlmostEqual(m["amount_usd"], 1000.0, places=6)
        self.assertAlmostEqual(self._pesos_en_pantalla(m), 1_400_000, places=2)

    def test_boton_e_importador_dan_la_misma_fila(self):
        """La misma operación no puede verse distinta según por dónde entró."""
        self._deposito_pesos(3_000_000)
        self._boton("ars_to_usd", 1_400_000, 1000, 1400)
        self._importar(
            "2024-03-02,CONVERSION_ARS_USD,IOL,,,,1400000,1000,1400,,,importada\n")
        conv = self._conversiones()
        self.assertEqual(len(conv), 2, conv)
        boton = next(m for m in conv if m["source"] == "manual")
        imp = next(m for m in conv if m["source"] == "import")
        for k in ("type", "asset", "amount_usd", "currency", "fx_to_usd",
                  "quantity", "unit_price"):
            self.assertEqual(boton[k], imp[k], f"{k}: botón {boton[k]!r} ≠ import {imp[k]!r}")

    # ── 4: los depósitos manuales que nadie hizo ────────────────────────────
    def test_conversion_importada_no_inventa_depositos_ni_retiros_manuales(self):
        self._importar(
            "2024-03-01,DEPOSITO,IOL,,,,2000000,,,,ARS,dep\n"
            "2024-03-02,CONVERSION_ARS_USD,IOL,,,,1400000,1000,1400,,,MEP\n")
        fantasmas = [m for m in self._movimientos() if m["source"] == "monthly"]
        self.assertEqual(fantasmas, [],
                         "la conversión aparece como depósito/retiro manual")

    def test_un_deposito_manual_real_en_el_mismo_mes_sigue_apareciendo(self):
        """La contracara: sacar los fantasmas no puede llevarse puesto un depósito
        que el usuario SÍ cargó a mano, en el mismo broker y el mismo mes."""
        self._importar(
            "2024-03-01,DEPOSITO,IOL,,,,2000000,,,,ARS,dep\n"
            "2024-03-02,CONVERSION_ARS_USD,IOL,,,,1400000,1000,1400,,,MEP\n")
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": self.SIB, "direction": "deposit", "amount": 250,
            "date": "2024-03-20"})
        self.assertEqual(r.status_code, 200, r.text)
        manuales = [m for m in self._movimientos() if m["source"] == "monthly"]
        self.assertEqual(len(manuales), 1, manuales)
        self.assertEqual(manuales[0]["type"], "DEPOSIT")
        self.assertEqual(manuales[0]["broker"], self.SIB)
        self.assertAlmostEqual(manuales[0]["amount_usd"], 250.0, places=2)


if __name__ == "__main__":
    unittest.main()
