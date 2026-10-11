"""El contrato de IDA Y VUELTA entre la bandeja de cobros de bonos y el servidor.

Un solo archivo, `fixtures/cupones_contrato.json`, con dos mitades:

  · "pantalla": lo que el servidor le da a la bandeja después de importar por
    las mismas puertas que la app (/api/positions, /api/operations,
    /api/brokers, /api/bonds/cashflow/skips), con TODOS los campos de los que
    depende: con cuántos nominales nació cada lote (`nominal_original`,
    `nominal_al_cargar`, `nominal_por_barrido`), qué operaciones son importadas
    y cuáles son la "venta" con la que Balanz anota una amortización. Lo escribe
    ESTE test (REGENERAR_FIXTURE=1) y lo lee
    frontend/src/utils/cuponesContrato.test.js.
  · "pagos": lo que la bandeja le manda a POST /api/bonds/cashflow/pago para
    confirmar cada pago que propone. Lo escribe el test de la pantalla
    (REGENERAR_PAGOS=1, con la MISMA función que usa el hook:
    `cuerpoDelPago`) y lo postea ESTE test, tal cual.

Por qué existe (auditoría 2026-10-10, prueba de mutación): ninguna prueba del
servidor le mandaba a /pago lo que manda la pantalla —los montos estaban
escritos a mano y sin `face_amortized`—, y el fixture de vuelta no llevaba ni
uno de los campos nuevos. Se podía romper cualquiera de las dos mitades (el
servidor deja de mandar `importada`; el hook manda otra cuenta) con todo verde.

Lo único reemplazado es el login.
"""
import io
import json
import os
import pathlib
import unittest

from fastapi.testclient import TestClient

import main

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "cupones_contrato.json"
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"

# El "hoy" de la mitad de pantalla (los pagos del cronograma hasta ese día).
HOY_DE_LA_PANTALLA = "2026-10-10"

ESCENARIOS = {
    # AL30 importado en la cuenta en pesos; el pago de julio 2025 ya vino en el
    # archivo, en dólares (el importador lo acredita en «Cocos · USD»).
    "importado_con_barrido": {
        "broker": ("Cocos", "ARS"),
        "filas": [
            "2025-03-01,DEPOSITO,Cocos,,,,10000000,,,0,ARS,",
            "2025-03-03,COMPRA,Cocos,AL30,10000,800,8000000,,,0,ARS,",
            "2025-07-10,RENTA Y AMORTIZACION,Cocos,AL30,,,831.6,,,0,USD,",
        ],
    },
    # GD46 importado (el servidor no tiene su cronograma): el pago de enero 2026
    # el archivo lo anota como una VENTA de los nominales amortizados (Balanz).
    "importado_sin_cronograma": {
        "broker": ("Balanz", "USDT"),
        "filas": [
            "2025-03-01,DEPOSITO,Balanz,,,,20000,,,0,USD,",
            "2025-03-03,COMPRA,Balanz,GD46,10000,0.6,6000,,,0,USD,",
            "2026-01-12,VENTA,Balanz,GD46,227.27,1.888,429.1,,,0,USD,Renta y Amortizacion",
        ],
    },
}


def _csv(rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


def _lo_que_ve_la_pantalla(client):
    pos = client.get("/api/positions").json()
    ops = client.get("/api/operations").json()
    brokers = client.get("/api/brokers").json()
    skips = client.get("/api/bonds/cashflow/skips").json()

    def lote(p):
        out = {"broker": p["broker"], "asset": p["asset"], "is_cash": bool(p.get("is_cash")),
               "entry_date": p.get("entry_date"), "currency": p.get("currency"),
               "nominal_por_barrido": p.get("nominal_por_barrido"),
               "nominal_original": p.get("nominal_original"),
               "nominal_al_cargar": p.get("nominal_al_cargar")}
        # La cantidad de un lote que lleva el barrido de amortizaciones cambia con
        # el calendario (se barre hasta HOY): el contrato fija que sea > 0. La de
        # los demás no depende del día: va el número.
        if p.get("nominal_por_barrido"):
            out["quantity_mayor_a_cero"] = bool(p.get("quantity") and p["quantity"] > 0)
        elif not p.get("is_cash"):
            out["quantity"] = p.get("quantity")
        return out

    return {
        "positions": [lote(p) for p in sorted(pos, key=lambda p: (p["broker"], p["asset"]))],
        "operations": [
            {"date": o["date"], "broker": o["broker"], "asset": o["asset"], "op_type": o["op_type"],
             "importada": o["importada"], "amortizacion_importada": o["amortizacion_importada"]}
            for o in sorted(ops, key=lambda o: (o["date"], o["broker"], o["asset"]))
        ],
        "brokers": [
            {"id": b["id"], "name": b["name"], "currency": b["currency"],
             "parent_broker_id": b.get("parent_broker_id")}
            for b in sorted(brokers, key=lambda b: b["id"])
        ],
        "skips": skips,
    }


class CuponesContratoTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "bond_cashflow_skips", "deleted_ops_journal",
                  "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        try:        # los ids de broker van al fixture (parent_broker_id)
            self.conn.execute("DELETE FROM sqlite_sequence WHERE name='brokers'")
            self.conn.commit()
        except Exception:
            pass

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _armar(self, escenario):
        nombre, moneda = escenario["broker"]
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cupones_contrato@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, nombre, moneda))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        client = TestClient(main.app)
        r = client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(escenario["filas"])), "text/csv"))],
            data={"format": "rendi_generic", "broker": nombre})
        self.assertEqual(r.status_code, 200, r.text)
        r = client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        return client

    def _guardado(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else {}

    # ── vuelta: lo que el servidor le da a la pantalla ───────────────────────
    def test_lo_que_lee_la_pantalla_es_el_fixture(self):
        real = {}
        for nombre, esc in ESCENARIOS.items():
            self.setUp()
            real[nombre] = _lo_que_ve_la_pantalla(self._armar(esc))
            self.tearDown()
        guardado = self._guardado()
        if os.environ.get("REGENERAR_FIXTURE"):
            guardado["hoy"] = HOY_DE_LA_PANTALLA
            guardado["pantalla"] = real
            guardado.setdefault("pagos", {})
            FIXTURE.write_text(json.dumps(guardado, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        self.setUp()   # el tearDown del framework cierra una conexión abierta
        self.assertEqual(guardado.get("hoy"), HOY_DE_LA_PANTALLA)
        self.assertEqual(
            real, guardado.get("pantalla"),
            "Lo que el servidor le da a la bandeja cambió. Si es a propósito: "
            "REGENERAR_FIXTURE=1 pytest tests/test_cupones_contrato.py, y después "
            "REGENERAR_PAGOS=1 npx vitest run src/utils/cuponesContrato.test.js")

    def test_el_fixture_lleva_los_campos_de_los_que_depende_la_bandeja(self):
        """Que el contrato no se vuelva a quedar sin lo importante."""
        p = self._guardado()["pantalla"]
        al30 = [x for x in p["importado_con_barrido"]["positions"] if x["asset"] == "AL30"][0]
        self.assertEqual((al30["nominal_por_barrido"], al30["nominal_original"]), (True, 10000))
        gd46 = [x for x in p["importado_sin_cronograma"]["positions"] if x["asset"] == "GD46"][0]
        # Importado sin cronograma: 10.000 originales aunque la "venta" del
        # archivo le haya bajado 227,27 a la cantidad.
        self.assertEqual(gd46["nominal_por_barrido"], False)
        self.assertAlmostEqual(gd46["nominal_original"], 10000, places=2)
        self.assertAlmostEqual(gd46["quantity"], 9772.73, places=2)
        ops = {(o["asset"], o["op_type"]): o
               for esc in p.values() for o in esc["operations"]}
        self.assertEqual((ops[("AL30", "Dividendo")]["importada"],
                          ops[("AL30", "Dividendo")]["amortizacion_importada"]), (True, False))
        self.assertTrue(ops[("GD46", "Venta")]["amortizacion_importada"])

    # ── ida: lo que la pantalla le manda al servidor ─────────────────────────
    def test_los_pagos_que_arma_la_pantalla_se_anotan_bien(self):
        pagos = self._guardado().get("pagos") or {}
        self.assertEqual(sorted(pagos), sorted(ESCENARIOS),
                         "faltan los pagos de la pantalla: REGENERAR_PAGOS=1 npx vitest run "
                         "src/utils/cuponesContrato.test.js")
        for nombre, esc in ESCENARIOS.items():
            with self.subTest(escenario=nombre):
                self.setUp()
                client = self._armar(esc)
                cuerpos = pagos[nombre]
                self.assertTrue(cuerpos, "la pantalla no propone ningún pago en este escenario")
                for cuerpo in cuerpos:
                    # Lo que la pantalla SIEMPRE manda en un pago con amortización.
                    if cuerpo["amort_amount"] > 0:
                        self.assertGreater(cuerpo.get("face_amortized") or 0, 0, cuerpo)
                    efectivo_antes = self._efectivo(client, cuerpo["cash_broker"])
                    nominal_antes = self._nominal(client, cuerpo["asset"])
                    r = client.post("/api/bonds/cashflow/pago", json=cuerpo)
                    self.assertEqual(r.status_code, 200, f"{cuerpo} → {r.text}")
                    partes = {p["op_type"]: p for p in r.json()["partes"]}
                    neto = cuerpo["coupon_amount"] + cuerpo["amort_amount"] - cuerpo["commissions"]
                    self.assertAlmostEqual(self._efectivo(client, cuerpo["cash_broker"]) - efectivo_antes,
                                           neto, places=2)
                    if cuerpo["amort_amount"] > 0:
                        am = partes["Amortización"]
                        # El costo salió de los lotes y la ganancia es lo demás.
                        self.assertGreater(am["cost_basis_consumed"], 0)
                        self.assertAlmostEqual(am["realized_gain"],
                                               cuerpo["amort_amount"] - am["cost_basis_consumed"], places=4)
                        baja = nominal_antes - self._nominal(client, cuerpo["asset"])
                        if esc is ESCENARIOS["importado_sin_cronograma"]:
                            # Nadie más le baja nominales: los baja este cobro.
                            self.assertAlmostEqual(baja, cuerpo["face_amortized"], places=2)
                        else:
                            self.assertAlmostEqual(baja, 0, places=2)   # los lleva el barrido
                    # Y no se anota dos veces.
                    self.assertEqual(client.post("/api/bonds/cashflow/pago", json=cuerpo).status_code, 409)
                self.tearDown()
        self.setUp()

    def _efectivo(self, client, broker):
        return sum(float(p.get("invested") or 0) for p in client.get("/api/positions").json()
                   if p.get("is_cash") and p["broker"] == broker)

    def _nominal(self, client, asset):
        return sum(float(p["quantity"] or 0) for p in client.get("/api/positions").json()
                   if not p.get("is_cash") and p["asset"] == asset)


if __name__ == "__main__":
    unittest.main()
