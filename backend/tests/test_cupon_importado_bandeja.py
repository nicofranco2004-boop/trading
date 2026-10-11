"""Un cupón que entró IMPORTADO no puede aparecer como «cobro para confirmar».

EL BUG (2026-10-09). La bandeja de Cartera («Tenés N cobros para confirmar»)
compara el cronograma del bono con los cobros ya registrados, pero sólo
reconocía las filas 'Cupón' / 'Amortización' — los nombres que escribe la carga
A MANO. Un cupón importado (fila RENTA / COUPON / DIVIDENDO del archivo del
broker) el persister lo guarda como 'Dividendo' o 'Interés'. Resultado: la
bandeja ofrecía como pendiente un cupón que ya había acreditado el cash, y
confirmarlo lo anotaba OTRA VEZ (cash del broker + P&L realizado).

Segundo hueco del mismo eslabón: el cupón en dólares de un bono comprado en
pesos el importador lo acredita en la pata «Cocos · USD», mientras el bono vive
en «Cocos». La bandeja comparaba el nombre exacto del broker.

Este archivo es la mitad BACKEND del contrato: importa por las MISMAS puertas que
la app (`/api/imports/preview` + `/confirm`) y lee lo que la pantalla lee
(`/api/positions`, `/api/operations`, `/api/brokers`, `/api/bonds/cashflow/skips`).
Lo que devuelven tiene que ser exactamente `fixtures/cupon_importado_bandeja.json`,
que es la entrada de `frontend/src/utils/pendingCashflows.importado.test.js` — ahí
pasa por el mismo filtro y el mismo detector que `Positions.jsx`. Si el importador
cambia la forma en que guarda un cupón, se pone rojo acá, y el fixture nuevo
(`REGENERAR_FIXTURE=1`) vuelve a probar la pantalla con la forma real.

Lo único reemplazado es el login (`dependency_overrides`).
"""
import io
import json
import os
import pathlib
import unittest

from fastapi.testclient import TestClient

import main

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "cupon_importado_bandeja.json"

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"

# AL30 paga el 9 de enero y el 9 de julio. Comprado en marzo de 2025: los dos
# pagos que ya pasaron al «hoy» del test de pantalla (2026-03-01) son el
# 2025-07-09 y el 2026-01-09. El broker los acredita un par de días después.
ESCENARIOS = {
    # Bono y cupón en la MISMA pata (pesos).
    "cupon_en_pesos": [
        "2025-03-01,DEPOSITO,Cocos,,,,10000000,,,0,ARS,",
        "2025-03-03,COMPRA,Cocos,AL30,10000,800,8000000,,,0,ARS,",
        "2025-07-10,RENTA,Cocos,AL30,,,350000,,,0,ARS,",
        "2026-01-12,RENTA Y AMORTIZACION,Cocos,AL30,,,420000,,,0,ARS,",
    ],
    # El bono en pesos, el cupón en dólares: el importador lo manda a «Cocos · USD».
    "cupon_en_la_pata_usd": [
        "2025-03-01,DEPOSITO,Cocos,,,,10000000,,,0,ARS,",
        "2025-03-03,COMPRA,Cocos,AL30,10000,800,8000000,,,0,ARS,",
        "2025-07-10,RENTA,Cocos,AL30,,,250,,,0,USD,",
        "2026-01-12,RENTA,Cocos,AL30,,,300,,,0,USD,",
    ],
}


def _csv(rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


# Sólo los campos que la bandeja usa. `quantity` de la posición se reduce con
# las amortizaciones que el barrido de vencimientos aplica HASTA HOY, así que
# cambia con el calendario: el contrato fija que sea > 0, no el número.
def _lo_que_ve_la_pantalla(client):
    pos = client.get("/api/positions").json()
    ops = client.get("/api/operations").json()
    brokers = client.get("/api/brokers").json()
    skips = client.get("/api/bonds/cashflow/skips").json()
    return {
        "positions": [
            {"broker": p["broker"], "asset": p["asset"], "is_cash": bool(p.get("is_cash")),
             "entry_date": p.get("entry_date"),
             "quantity_mayor_a_cero": bool(p.get("quantity") and p["quantity"] > 0)}
            for p in sorted(pos, key=lambda p: (p["broker"], p["asset"]))
        ],
        "operations": [
            {"date": o["date"], "broker": o["broker"], "asset": o["asset"], "op_type": o["op_type"]}
            for o in sorted(ops, key=lambda o: (o["date"], o["broker"], o["asset"]))
        ],
        "brokers": [
            {"id": b["id"], "name": b["name"], "currency": b["currency"],
             "parent_broker_id": b.get("parent_broker_id")}
            for b in sorted(brokers, key=lambda b: b["id"])
        ],
        "skips": skips,
    }


class CuponImportadoBandejaTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "bond_cashflow_skips", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        # Los ids de broker van al fixture (parent_broker_id): que arranquen igual.
        try:
            self.conn.execute("DELETE FROM sqlite_sequence WHERE name='brokers'")
            self.conn.commit()
        except Exception:
            pass

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _importar(self, rows):
        uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cupon_importado@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (uid, "Cocos", "ARS"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: uid
        client = TestClient(main.app)
        r = client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(rows)), "text/csv"))],
            data={"format": "rendi_generic", "broker": "Cocos"})
        self.assertEqual(r.status_code, 200, r.text)
        r = client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        return client

    def test_lo_que_lee_la_pantalla_es_el_fixture(self):
        real = {}
        for nombre, rows in ESCENARIOS.items():
            self.setUp()
            real[nombre] = _lo_que_ve_la_pantalla(self._importar(rows))
            self.tearDown()

        if os.environ.get("REGENERAR_FIXTURE"):
            FIXTURE.write_text(json.dumps(real, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        contrato = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(real, contrato,
                         "El importador cambió lo que la bandeja recibe. Regenerá el fixture "
                         "con REGENERAR_FIXTURE=1 y corré el test de pantalla "
                         "(pendingCashflows.importado.test.js).")

    def test_el_cupon_importado_no_se_llama_cupon(self):
        """La premisa del bug: si un día el importador escribe 'Cupón', este test
        avisa que la bandeja vieja ya no tenía el hueco — no que haya que borrar el
        arreglo (la pata USD sigue necesitándolo)."""
        client = self._importar(ESCENARIOS["cupon_en_pesos"])
        tipos = {o["op_type"] for o in client.get("/api/operations").json()
                 if o["asset"] == "AL30"}
        self.assertTrue(tipos)
        self.assertFalse(tipos & {"Cupón", "Amortización"}, tipos)

    def test_el_cupon_en_dolares_va_a_la_otra_pata(self):
        client = self._importar(ESCENARIOS["cupon_en_la_pata_usd"])
        brokers_del_cupon = {o["broker"] for o in client.get("/api/operations").json()
                             if o["asset"] == "AL30"}
        bono = [p for p in client.get("/api/positions").json() if p["asset"] == "AL30"]
        self.assertEqual({p["broker"] for p in bono}, {"Cocos"})
        self.assertEqual(brokers_del_cupon, {"Cocos · USD"})


if __name__ == "__main__":
    unittest.main()
