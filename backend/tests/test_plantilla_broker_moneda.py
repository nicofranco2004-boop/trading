"""La plantilla de Rendi no guarda pesos como dólares (AUDIT_plantilla_rendi, PL1).

El broker que el import crea porque el usuario no lo tenía tomaba la moneda de la
MAYORÍA de las filas; con empate o más filas en dólares quedaba en dólares. Un broker
en dólares no tiene dónde poner pesos: el importador los sumaba a su caja tal cual
(un depósito de $1.000.000 + US$500 quedaba "US$1.000.500"), rechazaba las
conversiones MEP, y el rendimiento de la cuenta salía en ~0 % (medido con la
historia de la auditoría: +0,2 % contra +25,2 % real, faltando UNA venta en pesos).

Ahora:
  · si el archivo le manda pesos a un broker nuevo, se crea en pesos (sus dólares van
    solos a "<broker> · USD");
  · si el broker ya existía en dólares y está vacío, se cura (revertir y volver a
    subir arregla la cuenta);
  · si ya tiene datos, la fila en pesos se rechaza con un mensaje claro, también al
    confirmar con "Estado inicial".

Todo entra por las puertas reales: vista previa y confirmación HTTP, y se lee lo que
quedó en la base (brokers, cajas, tenencia).

Corre con: cd backend && python3 -m pytest tests/test_plantilla_broker_moneda.py
"""
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


class LaPlantillaNoGuardaPesosComoDolares(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"plantilla-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── las puertas ──
    def vista_previa(self, broker, filas):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("plantilla.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def confirmar(self, prev, seed_state=None):
        body = {"session_id": prev["session_id"]}
        if seed_state:
            body["seed_state"] = seed_state
        r = self.client.post("/api/imports/confirm", headers=self.h, json=body)
        self.assertEqual(r.status_code, 200, r.text)

    def sql(self, q, *a):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(q, a).fetchall()]
        finally:
            conn.close()

    def brokers(self):
        return {r["name"]: r["currency"] for r in self.sql(
            "SELECT name, currency FROM brokers WHERE user_id=?", self.uid)}

    def cajas(self):
        return {r["broker"]: (r["asset"], round(float(r["invested"] or 0), 2)) for r in self.sql(
            "SELECT broker, asset, invested FROM positions WHERE user_id=? AND is_cash=1",
            self.uid)}

    def crear_broker(self, nombre, moneda, con_datos=False):
        conn = main.get_db()
        with conn:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, nombre, moneda))
            # Una caja en cero (lo que queda después de revertir un import): no es data.
            conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                         "VALUES (?,?,?,1,0)", (self.uid, nombre, "USD"))
            if con_datos:
                conn.execute(
                    "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested, "
                    "buy_price, entry_date, currency) VALUES (?,?,?,0,5,900,180,'2025-06-01','USD')",
                    (self.uid, nombre, "AAPL"))
        conn.close()

    # ── broker nuevo ──
    def test_mas_filas_en_dolares_no_dejan_el_broker_en_dolares(self):
        """1 fila en pesos y 2 en dólares: antes, broker en USD y caja "US$1.000.365"."""
        prev = self.vista_previa("MiBroker",
                                 "2026-01-05,DEPOSITO,MiBroker,,,,1000000,,,,ARS,\n"
                                 "2026-01-06,DEPOSITO,MiBroker,,,,500,,,,USD,\n"
                                 "2026-01-07,COMPRA,MiBroker,AAPL,10,13.5,,,,,USD,\n")
        self.assertEqual({b["name"]: b["currency"] for b in prev["new_brokers_created"]},
                         {"MiBroker": "ARS"})
        self.assertEqual(prev["errors"], [])
        self.confirmar(prev)
        self.assertEqual(self.brokers()["MiBroker"], "ARS")
        cajas = self.cajas()
        self.assertEqual(cajas["MiBroker"], ("ARS", 1_000_000.0))
        self.assertEqual(cajas["MiBroker · USD"][1], 365.0)

    def test_la_conversion_mep_entra(self):
        """Con el broker en dólares, el MEP se rechazaba (FX_BROKER_MISMATCH)."""
        prev = self.vista_previa("MiBroker",
                                 "2026-01-05,DEPOSITO,MiBroker,,,,1500000,,,,ARS,\n"
                                 "2026-01-08,CONVERSION_ARS_USD,MiBroker,,,,1200000,1000,1200,,,\n"
                                 "2026-01-09,COMPRA,MiBroker,KO,10,60,,,,,USD,\n"
                                 "2026-02-09,DIVIDENDO,MiBroker,KO,,,4.6,,,,USD,\n")
        self.assertEqual(prev["errors"], [])
        self.confirmar(prev)
        cajas = self.cajas()
        self.assertEqual(cajas["MiBroker"], ("ARS", 300_000.0))
        self.assertAlmostEqual(cajas["MiBroker · USD"][1], 1000 - 600 + 4.6, places=2)

    def test_solo_dolares_sigue_en_dolares(self):
        prev = self.vista_previa("MiIBKR",
                                 "2026-01-05,DEPOSITO,MiIBKR,,,,5000,,,,USD,\n"
                                 "2026-01-07,COMPRA,MiIBKR,AAPL,10,200,,,,,USD,\n")
        self.assertEqual({b["name"]: b["currency"] for b in prev["new_brokers_created"]},
                         {"MiIBKR": "USD"})

    def test_un_broker_cripto_sigue_en_usdt(self):
        prev = self.vista_previa("Binance",
                                 "2026-01-05,DEPOSITO,Binance,,,,1000,,,,USDT,\n")
        self.assertEqual({b["name"]: b["currency"] for b in prev["new_brokers_created"]},
                         {"Binance": "USDT"})

    def test_la_subcuenta_en_dolares_que_nombra_el_archivo_sigue_en_dolares(self):
        """La venta de dólares sale de la cuenta EN DÓLARES: no es señal de pesos."""
        prev = self.vista_previa("MiBroker",
                                 "2026-01-05,DEPOSITO,MiBroker,,,,1000000,,,,ARS,\n"
                                 "2026-01-06,CONVERSION_ARS_USD,MiBroker,,,,100000,100,1000,,,\n"
                                 "2026-01-07,CONVERSION_USD_ARS,MiBroker · USD,,,,60000,50,1200,,,\n")
        self.assertEqual(prev["errors"], [])
        self.confirmar(prev)
        self.assertEqual(self.brokers()["MiBroker"], "ARS")
        self.assertNotEqual(self.brokers()["MiBroker · USD"], "ARS")
        self.assertEqual(self.cajas()["MiBroker · USD"][1], 50.0)

    # ── broker que ya existía en dólares ──
    def test_un_broker_en_dolares_vacio_se_cura(self):
        """El caso "revertí y lo vuelvo a subir": el broker quedó en USD de un import
        viejo, sólo con su caja en cero."""
        self.crear_broker("MiBroker", "USD")
        prev = self.vista_previa("MiBroker",
                                 "2026-01-05,DEPOSITO,MiBroker,,,,1000000,,,,ARS,\n"
                                 "2026-01-06,DEPOSITO,MiBroker,,,,500,,,,USD,\n")
        self.assertEqual(prev["errors"], [])
        self.confirmar(prev)
        self.assertEqual(self.brokers()["MiBroker"], "ARS")
        self.assertEqual(self.cajas()["MiBroker · USD"][1], 500.0)

    def test_un_broker_en_dolares_con_datos_rechaza_los_pesos(self):
        self.crear_broker("MiIBKR", "USD", con_datos=True)
        prev = self.vista_previa("MiIBKR",
                                 "2026-01-05,DEPOSITO,MiIBKR,,,,1000000,,,,ARS,\n"
                                 "2026-01-06,DEPOSITO,MiIBKR,,,,500,,,,USD,\n")
        self.assertEqual([e["code"] for e in prev["errors"]], ["PESOS_EN_BROKER_EN_DOLARES"])
        self.confirmar(prev)
        self.assertEqual(self.brokers()["MiIBKR"], "USD")
        self.assertEqual(self.cajas()["MiIBKR"][1], 500.0)     # no 1.000.500

    def test_confirmar_con_estado_inicial_tampoco_deja_pasar_los_pesos(self):
        """El confirm con "Estado inicial" re-valida por otro camino."""
        self.crear_broker("MiIBKR", "USD", con_datos=True)
        prev = self.vista_previa("MiIBKR",
                                 "2026-01-05,DEPOSITO,MiIBKR,,,,1000000,,,,ARS,\n"
                                 "2026-01-06,DEPOSITO,MiIBKR,,,,500,,,,USD,\n")
        self.confirmar(prev, seed_state={
            "seed_date": "2026-01-04",
            "brokers": [{"broker": "MiIBKR", "cash": {"USD": 100.0}, "assets": []}]})
        self.assertEqual(self.cajas()["MiIBKR"][1], 600.0)     # 100 + 500, sin los pesos


if __name__ == "__main__":
    unittest.main()
