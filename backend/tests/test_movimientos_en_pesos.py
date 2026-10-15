"""`/api/movements` manda cada depósito y retiro EN PESOS con los pesos exactos.

Movimientos muestra cada fila en pesos multiplicando sus dólares (`amount_usd`) por
un dólar (frontend/src/hooks/useHistoricalMoney.js). Si la fila trae
`currency='ARS'` y `fx_to_usd`, usa ese: es el dólar con que se guardó, así que
vuelve EXACTO a los pesos. Si no lo trae, usa el MEP de la fecha — que para lo
importado (estampado con otro dólar) o para una carga vieja dolarizada con el dólar
del día en que se cargó, NO devuelve los pesos que entraron.

Antes: lo importado venía con `currency='ARS'` y sin `fx_to_usd`, y lo cargado a
mano en un broker en pesos venía como `currency='USD'`. Ahora los dos traen el
dólar con que se guardaron. Los pesos son los mismos que usa "Capital aportado"
(`/api/monthly`: `pesos_importados_*`, `manual_*_native`).

Todo entra por las puertas reales (importador, botón de efectivo) y se lee por
GET /api/movements, lo mismo que pide la pantalla.

Corre con: cd backend && python3 -m pytest tests/test_movimientos_en_pesos.py
"""
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


def en_pesos(m):
    """Lo que hace `resolveHistoricalFx` con una fila que trae su dólar."""
    assert m["currency"] == "ARS", m
    assert m["fx_to_usd"] and m["fx_to_usd"] > 0, m
    return m["amount_usd"] * m["fx_to_usd"]


class MovimientosEnPesos(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
            "VALUES (?, 'x', 1, 1, 'pro')", (f"movs-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'IOL', 'ARS')",
                     (self.uid,))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'IBKR', 'USD')",
                     (self.uid,))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def importar(self, broker, filas):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("x.csv", io.BytesIO((HDR + filas).encode("utf-8")), "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", headers=self.h,
                             json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def movimientos(self):
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return [m for m in r.json() if m["type"] in ("DEPOSIT", "WITHDRAW")]

    def test_lo_importado_vuelve_a_sus_pesos(self):
        self.importar("IOL",
                      "2024-01-05,DEPOSITO,IOL,,,,3000000,,,,ARS,dep 1\n"
                      "2024-01-25,DEPOSITO,IOL,,,,2000000,,,,ARS,dep 2\n"
                      "2024-01-28,RETIRO,IOL,,,,500000,,,,ARS,ret\n")
        movs = {m["notes"]: m for m in self.movimientos() if m["source"] == "import"}
        self.assertAlmostEqual(en_pesos(movs["dep 1"]), 3_000_000, places=2)
        self.assertAlmostEqual(en_pesos(movs["dep 2"]), 2_000_000, places=2)
        self.assertAlmostEqual(en_pesos(movs["ret"]), 500_000, places=2)

    def test_lo_cargado_a_mano_en_pesos_vuelve_a_sus_pesos(self):
        for direccion, monto, fecha in (("deposit", 800_000, "2024-03-15"),
                                        ("withdraw", 120_000, "2024-04-02")):
            r = self.client.post("/api/cash/flow", headers=self.h, json={
                "broker_name": "IOL", "direction": direccion, "amount": monto, "date": fecha})
            self.assertEqual(r.status_code, 200, r.text)
        movs = {m["date"]: m for m in self.movimientos() if m["broker"] == "IOL"}
        self.assertAlmostEqual(en_pesos(movs["2024-03-15"]), 800_000, places=2)
        self.assertAlmostEqual(en_pesos(movs["2024-04-02"]), 120_000, places=2)

    def test_lo_cargado_en_dolares_sigue_en_dolares(self):
        # Un broker en dólares no tiene pesos que devolver: la pantalla lo lleva al
        # dólar de su fecha, como siempre.
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "IBKR", "direction": "deposit", "amount": 2000, "date": "2024-03-02"})
        self.assertEqual(r.status_code, 200, r.text)
        m = [x for x in self.movimientos() if x["broker"] == "IBKR"][0]
        self.assertEqual(m["currency"], "USD")
        self.assertIsNone(m["fx_to_usd"])
        self.assertAlmostEqual(m["amount_usd"], 2000, places=6)


    def test_un_broker_que_paso_de_dolares_a_pesos_no_inventa_pesos(self):
        # La carga se hizo cuando el broker estaba en dólares: su "monto nativo" son
        # esos dólares. Si después el broker pasa a pesos, NO son pesos — si viajara
        # como ARS con dólar 1,0, en pesos se leería $2.000 en vez de ~$2 millones.
        # Mismo control que "Capital aportado" (`pesosAMano` en capitalAportado.js).
        # La historia del dólar de ese día, como en producción (la tabla viene llena
        # desde 2011): sin ella el control no tiene contra qué comparar.
        conn = main.get_db()
        conn.execute("INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                     "VALUES ('2024-03-15', 1020, 1010, 'test')")
        conn.commit()
        conn.close()
        r = self.client.post("/api/brokers", headers=self.h, json={"name": "Cocos"})
        self.assertEqual(r.status_code, 200, r.text)
        bid = r.json()["id"]
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Cocos", "direction": "deposit", "amount": 2000, "date": "2024-03-15"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.put(f"/api/brokers/{bid}", headers=self.h, json={"name": "Cocos", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        m = [x for x in self.movimientos() if x["broker"] == "Cocos"][0]
        self.assertEqual(m["currency"], "USD")
        self.assertIsNone(m["fx_to_usd"])
        self.assertAlmostEqual(m["amount_usd"], 2000, places=6)

    def test_lo_cargado_sin_dia_tambien_vuelve_a_sus_pesos(self):
        # Una carga vieja, de antes del detalle por carga: el mes tiene los pesos
        # (`manual_deposits_native`) pero no hay renglón con día. Va como fila
        # "del mes" (`mr-`) y tiene que traer sus pesos igual.
        conn = main.get_db()
        conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, manual_deposits, manual_deposits_native) "
            "VALUES (?, 'IOL', 2023, 5, 0, 1000, 1000, 0, 1000, 480000)", (self.uid,))
        conn.commit()
        conn.close()
        m = [x for x in self.movimientos() if x["broker"] == "IOL" and x["id"].startswith("mr-")]
        self.assertEqual(len(m), 1, m)
        self.assertAlmostEqual(en_pesos(m[0]), 480_000, places=2)

if __name__ == "__main__":
    unittest.main()
