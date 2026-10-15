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

    def test_el_estado_inicial_va_al_dolar_del_dia_del_import(self):
        # El "Estado inicial" del importador pregunta "¿cuánto efectivo tenés HOY?"
        # y anota la diferencia como depósitos sintéticos —uno por moneda— fechados
        # el día ANTES del primer movimiento: los montos son del día del import.
        # La pata en dólares iba sin pesos y la pantalla la pasaba al dólar de SU
        # fecha: en la cuenta 826 de prod, −$24 M + US$ 19.756 × 16 (el dólar de
        # 2017) daba "Capital aportado" en pesos −$23,6 M. Por la puerta real:
        # preview + confirm con `seed_state`, lo mismo que manda el asistente.
        conn = main.get_db()
        try:
            padre = conn.execute("SELECT id FROM brokers WHERE user_id=? AND name='IOL'",
                                 (self.uid,)).fetchone()["id"]
            conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                         "VALUES (?, 'IOL · USD', 'USDT', ?)", (self.uid, padre))
            # El dólar del día del import (la serie sólo tiene hoy: los movimientos
            # de 2024 no lo usan).
            hoy = conn.execute("SELECT date('now')").fetchone()[0]
            conn.execute("INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta) "
                         "VALUES (?, 1450, 1500)", (hoy,))
            conn.commit()
        finally:
            conn.close()
        csv = (HDR + "2024-01-05,DEPOSITO,IOL,,,,3000000,,,,ARS,dep real\n"
                     "2024-01-06,COMPRA,IOL,GGAL,1000,2000,2000000,,,,ARS,compra\n")
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("x.csv", io.BytesIO(csv.encode("utf-8")), "text/csv"))],
            data={"format": "rendi_generic", "broker": "IOL"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", headers=self.h, json={
            "session_id": r.json()["session_id"],
            "seed_state": {"seed_date": "2024-01-04", "brokers": [
                {"broker": "IOL", "cash": {"ARS": 5_000_000}, "assets": []},
                {"broker": "IOL · USD", "cash": {"USDT": 1_000}, "assets": []}]}})
        self.assertEqual(r.status_code, 200, r.text)
        # Y un depósito REAL en dólares en el mismo mes, importado en el broker en dólares.
        self.importar("IOL · USD", "2024-01-20,DEPOSITO,IOL · USD,,,,500,,,,USD,dep usd real\n")

        # Los dos sintéticos existen y son lo que dicen ser (sin huella, con su nota).
        conn = main.get_db()
        try:
            sint = conn.execute(
                """SELECT n.broker, n.gross_amount, n.fingerprint FROM import_normalized_tx n
                     JOIN import_batches b ON b.id = n.batch_id
                    WHERE b.user_id=? AND n.operation_type='DEPOSIT'
                      AND n.notes LIKE 'Estado inicial%' ORDER BY n.broker""",
                (self.uid,)).fetchall()
        finally:
            conn.close()
        self.assertEqual([(x["broker"], round(x["gross_amount"])) for x in sint],
                         [("IOL", 5_000_000), ("IOL · USD", 1_000)])
        self.assertTrue(all(x["fingerprint"] is None for x in sint))

        filas = self.client.get("/api/monthly", headers=self.h).json()
        # La pata en pesos: sus pesos (del día del import), junto con el depósito real.
        pesos = self.fila(filas, "IOL", 2024, 1)
        self.assertAlmostEqual(pesos["pesos_importados_dep"], 3_000_000 + 5_000_000, places=2)
        # La pata en dólares: al dólar del día del import, no al de enero de 2024.
        usd = self.fila(filas, "IOL · USD", 2024, 1)
        self.assertAlmostEqual(usd["pesos_importados_dep_usd"], 1_000, places=4)
        self.assertAlmostEqual(usd["pesos_importados_dep"], 1_000 * 1500, places=2)
        self.assertAlmostEqual(usd["deposits"], 1_000 + 500, places=4)
        # Viaja por UN solo lado: con pesos, y no también como depósito en dólares con
        # su día (`usd_con_dia`) — ahí queda sólo el real, y los dólares del mes cierran:
        # los que llevan pesos + los que van con su día = todo lo que entró.
        importado = usd["usd_con_dia"]["importado"]
        self.assertEqual(importado["dep"], [["2024-01-20", 500.0]])
        self.assertAlmostEqual(usd["pesos_importados_dep_usd"] + sum(x[1] for x in importado["dep"]),
                               usd["deposits"], places=4)

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


class AportesEnDolaresConSuDia(unittest.TestCase):
    """`/api/monthly` manda también los aportes EN DÓLARES con su día (`usd_con_dia`),
    para que la pantalla los pase a pesos con el dólar de ESE día — el mismo con que
    Movimientos muestra cada fila — y no con el del cierre del mes (hasta el
    2026-10-15: US$2.000 del 02/03/2026 eran $2.835.200 en Movimientos y $2.852.100
    en "Capital aportado").

    La prueba: cada depósito o retiro en dólares de Movimientos aparece, con su día y
    sus dólares, en la fila de su broker y su mes; y nada más."""

    importar = AportesEnPesos.importar
    fila = AportesEnPesos.fila

    def setUp(self):
        AportesEnPesos.setUp(self)
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'IBKR', 'USD')",
                     (self.uid,))
        conn.commit()
        conn.close()

    def test_cada_fila_en_dolares_de_movimientos_esta_con_su_dia(self):
        # Importado: dos depósitos en dólares el mismo mes, un retiro, y un depósito
        # en pesos (ése viaja con sus pesos, no acá).
        self.importar("IBKR",
                      "2024-04-08,DEPOSITO,IBKR,,,,1500,,,,USD,dep usd 1\n"
                      "2024-04-22,DEPOSITO,IBKR,,,,700,,,,USD,dep usd 2\n"
                      "2024-06-03,RETIRO,IBKR,,,,200,,,,USD,ret usd\n")
        self.importar("IOL", "2024-04-10,DEPOSITO,IOL,,,,3000000,,,,ARS,dep ars\n")
        # A mano: un depósito y un retiro en dólares con el botón de efectivo.
        for direccion, monto, fecha in (("deposit", 2000, "2024-05-20"), ("withdraw", 300, "2024-05-28")):
            r = self.client.post("/api/cash/flow", headers=self.h, json={
                "broker_name": "IBKR", "direction": direccion, "amount": monto, "date": fecha})
            self.assertEqual(r.status_code, 200, r.text)

        filas = self.client.get("/api/monthly", headers=self.h).json()
        movs = self.client.get("/api/movements", headers=self.h).json()

        en_monthly = []
        for f in filas:
            if f["broker"] == "global":
                self.assertNotIn("usd_con_dia", f)
                continue
            dia = f.get("usd_con_dia") or {}
            for clave in ("importado", "a_mano"):
                for lado, tipo in (("dep", "DEPOSIT"), ("ret", "WITHDRAW")):
                    for fecha, usd in (dia.get(clave) or {}).get(lado, []):
                        self.assertEqual(fecha[:7], f"{f['year']:04d}-{f['month']:02d}")
                        en_monthly.append((f["broker"], tipo, fecha, round(usd, 4), clave))

        en_movs = sorted(
            (m["broker"], m["type"], m["date"][:10], round(m["amount_usd"], 4),
             "importado" if m["source"] == "import" else "a_mano")
            for m in movs if m["type"] in ("DEPOSIT", "WITHDRAW") and m["currency"] == "USD")
        self.assertEqual(len(en_movs), 5, en_movs)
        # Lo cargado a mano en el broker en PESOS también viaja (la pantalla lo usa sólo
        # si no puede usar sus pesos); lo importado en pesos, no.
        self.assertEqual(sorted(x for x in en_monthly if x[0] == "IBKR"), en_movs)
        self.assertEqual([x for x in en_monthly if x[0] == "IOL"], [])
        self.assertIn(("IBKR", "DEPOSIT", "2024-05-20", 2000.0, "a_mano"), en_movs)
        self.assertIn(("IBKR", "DEPOSIT", "2024-04-22", 700.0, "importado"), en_movs)

        # Y suman exactamente los dólares de su fila: no hay plata de más ni de menos.
        for f in filas:
            if f["broker"] != "IBKR" or not f.get("usd_con_dia"):
                continue
            d = f["usd_con_dia"]
            dep = sum(u for c in ("importado", "a_mano") for _, u in d[c]["dep"])
            ret = sum(u for c in ("importado", "a_mano") for _, u in d[c]["ret"])
            self.assertAlmostEqual(dep, f["deposits"], places=4)
            self.assertAlmostEqual(ret, f["withdrawals"], places=4)

    def test_en_un_broker_en_pesos_lo_cargado_a_mano_va_con_su_dia(self):
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "IOL", "direction": "deposit", "amount": 1_000_000, "date": "2025-06-10"})
        self.assertEqual(r.status_code, 200, r.text)
        jun = self.fila(self.client.get("/api/monthly", headers=self.h).json(), "IOL", 2025, 6)
        self.assertEqual(jun["usd_con_dia"]["a_mano"]["dep"],
                         [["2025-06-10", round(jun["manual_deposits"], 6)]])
        self.assertEqual(jun["usd_con_dia"]["importado"], {"dep": [], "ret": []})
