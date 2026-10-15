"""`/api/monthly` manda los PESOS de los aportes y retiros de cada fila de broker.

Para mostrar "Capital aportado" en pesos, la pantalla necesita los pesos que se
pusieron (frontend/src/utils/capitalAportado.js). `monthly_entries` guarda los
flujos en dólares; lo cargado a mano además guarda los pesos (`manual_*_native`),
pero lo IMPORTADO no: la pantalla los reconstruía con el dólar del mes. Medido
sobre la copia de prod del 2026-08-16 (648 cuentas con depósitos importados en
pesos), esa reconstrucción erraba más del 20 % de lo depositado en 1 de cada 10.

Ahora cada fila de broker trae `pesos_importados_dep`/`_ret` (pesos) y
`pesos_importados_dep_usd`/`_ret_usd` (los dólares de la fila que esos pesos
cubren). Lo cargado a mano ya traía sus pesos en `manual_*_native`.
Todo entra por las puertas reales: el botón de efectivo (POST /api/cash/flow) y
el importador (preview + confirm, que corre el persister y el recalc), y se lee
GET /api/monthly, lo mismo que pide la pantalla.

Corre con: cd backend && python3 -m pytest tests/test_aportes_en_pesos.py
"""
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


class AportesEnPesos(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"pesos-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'IOL', 'ARS')",
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

    def fila(self, filas, broker, y, m):
        f = [x for x in filas if x["broker"] == broker and x["year"] == y and x["month"] == m]
        self.assertEqual(len(f), 1, f"{broker} {y}-{m}: {[(x['broker'], x['year'], x['month']) for x in filas]}")
        return f[0]

    def test_pesos_de_lo_importado_lo_cargado_a_mano_y_las_conversiones(self):
        # Enero: dos depósitos en pesos a dólares distintos y un retiro.
        self.importar("IOL",
                      "2024-01-05,DEPOSITO,IOL,,,,3000000,,,,ARS,dep 1\n"
                      "2024-01-25,DEPOSITO,IOL,,,,2000000,,,,ARS,dep 2\n"
                      "2024-01-28,RETIRO,IOL,,,,500000,,,,ARS,ret\n"
                      # Febrero: una conversión de $1.400.000 a US$ 1.000.
                      "2024-02-10,CONVERSION_ARS_USD,IOL,,,,1400000,1000,1400,,,MEP feb\n")
        # Marzo: un depósito cargado a mano con el botón de efectivo.
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "IOL", "direction": "deposit", "amount": 800000, "date": "2024-03-15"})
        self.assertEqual(r.status_code, 200, r.text)

        r = self.client.get("/api/monthly", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = r.json()

        ene = self.fila(filas, "IOL", 2024, 1)
        self.assertAlmostEqual(ene["pesos_importados_dep"], 5_000_000, places=2)
        self.assertAlmostEqual(ene["pesos_importados_ret"], 500_000, places=2)
        # Los dólares que esos pesos cubren son los de la fila (todo lo de enero es importado en pesos).
        self.assertAlmostEqual(ene["pesos_importados_dep_usd"], ene["deposits"], places=4)
        self.assertAlmostEqual(ene["pesos_importados_ret_usd"], ene["withdrawals"], places=4)

        # La conversión: la pata en pesos retira $1.400.000 y la pata en dólares
        # deposita LOS MISMOS pesos — suma cero al aportado, como en dólares.
        feb_pesos = self.fila(filas, "IOL", 2024, 2)
        sub = [b["name"] for b in self.client.get("/api/brokers", headers=self.h).json()
               if b["name"] != "IOL"]
        self.assertEqual(len(sub), 1, sub)
        feb_usd = self.fila(filas, sub[0], 2024, 2)
        self.assertAlmostEqual(feb_pesos["pesos_importados_ret"], 1_400_000, places=2)
        self.assertAlmostEqual(feb_usd["pesos_importados_dep"], 1_400_000, places=2)
        self.assertAlmostEqual(feb_pesos["pesos_importados_ret_usd"], feb_usd["pesos_importados_dep_usd"], places=4)
        self.assertAlmostEqual(feb_usd["pesos_importados_dep_usd"], feb_usd["deposits"], places=4)

        # Lo cargado a mano: sus pesos viajan en `manual_deposits_native`, no acá.
        mar = self.fila(filas, "IOL", 2024, 3)
        self.assertEqual(mar["pesos_importados_dep"], 0)
        self.assertAlmostEqual(mar["manual_deposits_native"], 800_000, places=2)

        # 'global' no lleva los campos: es la suma en dólares de los brokers.
        for g in (x for x in filas if x["broker"] == "global"):
            self.assertNotIn("pesos_importados_dep", g)

        # En total, los pesos conocidos son exactamente los que entraron y salieron.
        neto = sum(x.get("pesos_importados_dep", 0) - x.get("pesos_importados_ret", 0)
                   + (x.get("manual_deposits_native") or 0) - (x.get("manual_withdrawals_native") or 0)
                   for x in filas if x["broker"] != "global")
        self.assertAlmostEqual(neto, 3_000_000 + 2_000_000 - 500_000 + 800_000, places=2)

    def test_cuenta_sin_imports(self):
        # Sin nada importado la respuesta sigue llegando, con los campos en cero.
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "IOL", "direction": "deposit", "amount": 1000, "date": "2025-06-10"})
        self.assertEqual(r.status_code, 200, r.text)
        filas = self.client.get("/api/monthly", headers=self.h).json()
        jun = self.fila(filas, "IOL", 2025, 6)
        self.assertEqual((jun["pesos_importados_dep"], jun["pesos_importados_ret"]), (0, 0))
        self.assertAlmostEqual(jun["manual_deposits_native"], 1000, places=2)


if __name__ == "__main__":
    unittest.main()
