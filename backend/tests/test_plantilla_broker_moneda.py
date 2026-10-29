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

    def caja_en_dolares(self, broker, tc=1000.0):
        """Lo que vale la caja para metas, tableros de la IA y reportes: el lector
        real (`behavioral._position_value_usd`), no las columnas sueltas."""
        from behavioral import _position_value_usd
        fila = self.sql("SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                        self.uid, broker)
        self.assertEqual(len(fila), 1, fila)
        return round(_position_value_usd(fila[0], tc_blue=tc), 2)

    def crear_broker(self, nombre, moneda, con_datos=False):
        conn = main.get_db()
        with conn:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, nombre, moneda))
            # Una caja en cero (lo que queda después de revertir un import): no es data.
            # Con `currency` como en producción: el arranque (init_db) la completa
            # desde el rótulo, así que una caja "USD" lleva currency USD.
            conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested, "
                         "currency) VALUES (?,?,?,1,0,'USD')", (self.uid, nombre, "USD"))
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
        # La caja en cero que quedó del import viejo se llamaba "USD": los pesos
        # se sumaban ahí con ese rótulo.
        self.assertEqual(self.cajas()["MiBroker"], ("ARS", 1_000_000.0))
        self.assertEqual(self.caja_en_dolares("MiBroker"), 1000.0)    # no US$1.000.000
        self.assertEqual(self.cajas()["MiBroker · USD"][1], 500.0)

    def test_revertir_y_volver_a_subir_cura_el_broker(self):
        """El camino de verdad, de punta a punta: una plantilla sólo en dólares crea
        el broker en dólares; se revierte; la plantilla con pesos lo cura."""
        prev = self.vista_previa("Cocos", "2026-01-05,DEPOSITO,Cocos,,,,1000,,,,USD,\n")
        self.confirmar(prev)
        self.assertEqual(self.brokers()["Cocos"], "USD")
        r = self.client.post(f"/api/imports/{prev['session_id']}/revert", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.confirmar(self.vista_previa("Cocos", "2026-01-05,DEPOSITO,Cocos,,,,1000,,,,USD,\n"
                                                  "2026-01-06,DEPOSITO,Cocos,,,,2000000,,,,ARS,\n"))
        self.assertEqual(self.brokers()["Cocos"], "ARS")
        self.assertEqual(self.caja_en_dolares("Cocos"), 2000.0)
        self.assertEqual(self.cajas()["Cocos · USD"][1], 1000.0)

    def test_un_broker_en_dolares_con_historia_no_se_cura(self):
        """Vendió todo: caja en cero y ninguna tenencia, pero su historia está en
        dólares. Pasarlo a pesos la reinterpretaría."""
        self.crear_broker("MiIBKR", "USD")
        conn = main.get_db()
        with conn:
            conn.execute("INSERT INTO operations (user_id, date, broker, asset, op_type, "
                         "entry_price, exit_price, quantity, pnl_usd) "
                         "VALUES (?,'2025-08-01',?,'AAPL','Venta',180,210,5,150)",
                         (self.uid, "MiIBKR"))
        conn.close()
        prev = self.vista_previa("MiIBKR", "2026-01-05,DEPOSITO,MiIBKR,,,,1000000,,,,ARS,\n")
        self.assertEqual([e["code"] for e in prev["errors"]], ["PESOS_EN_BROKER_EN_DOLARES"])
        self.assertEqual(self.brokers()["MiIBKR"], "USD")

    def test_un_broker_en_dolares_con_movimientos_importados_no_se_cura(self):
        """Depositó y retiró lo mismo: caja en cero, sin tenencia ni operaciones,
        pero con movimientos importados en dólares."""
        self.confirmar(self.vista_previa("MiIBKR", "2026-01-05,DEPOSITO,MiIBKR,,,,1000,,,,USD,\n"
                                                   "2026-01-06,RETIRO,MiIBKR,,,,1000,,,,USD,\n"))
        self.assertEqual(self.cajas()["MiIBKR"][1], 0.0)
        r = self.subir_foto("MiIBKR", self.FOTO)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.brokers()["MiIBKR"], "USD")

    def test_un_broker_en_dolares_con_datos_rechaza_los_pesos(self):
        self.crear_broker("MiIBKR", "USD", con_datos=True)
        prev = self.vista_previa("MiIBKR",
                                 "2026-01-05,DEPOSITO,MiIBKR,,,,1000000,,,,ARS,\n"
                                 "2026-01-06,DEPOSITO,MiIBKR,,,,500,,,,USD,\n")
        self.assertEqual([e["code"] for e in prev["errors"]], ["PESOS_EN_BROKER_EN_DOLARES"])
        self.confirmar(prev)
        self.assertEqual(self.brokers()["MiIBKR"], "USD")
        self.assertEqual(self.cajas()["MiIBKR"][1], 500.0)     # no 1.000.500

    def test_un_export_de_cocos_a_un_cocos_en_dolares_con_datos_rechaza_los_pesos(self):
        """Auditoría 28/10: la guarda de arriba era sólo de la plantilla. Un export de
        broker (Cocos, Balanz…) a un broker que quedó en dólares (un import viejo con
        la regla de mayoría) y ya tiene datos no se cura —cambiarle la moneda
        reinterpretaría lo que tiene— y sus pesos entraban a la caja en dólares tal
        cual: $1.000.000 quedaban como US$ 1.000.000."""
        self.crear_broker("Cocos", "USD", con_datos=True)
        mov = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
               "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;"
               "total\n1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;1.000.000;0;0;0;0;"
               "1.000.000\n")
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("mov.csv", io.BytesIO(mov.encode()), "text/csv"))],
            data={"format": "cocos", "broker": "Cocos"})
        self.assertEqual(r.status_code, 200, r.text)
        prev = r.json()
        self.assertEqual([e["code"] for e in prev["errors"]], ["PESOS_EN_BROKER_EN_DOLARES"])
        self.confirmar(prev)
        self.assertEqual(self.brokers()["Cocos"], "USD")
        self.assertEqual(self.cajas()["Cocos"][1], 0.0)        # no 1.000.000

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

    def test_el_estado_inicial_no_ofrece_pesos_para_un_broker_en_dolares(self):
        """El "Estado inicial" arma sus casilleros con las monedas de las filas
        VÁLIDAS: rechazada la compra en pesos, no pide efectivo en pesos para un
        broker en dólares (y no hay por dónde mandarlos)."""
        self.crear_broker("MiIBKR", "USD", con_datos=True)
        prev = self.vista_previa("MiIBKR",
                                 "2026-01-05,COMPRA,MiIBKR,GGAL,10,5000,,,,,ARS,\n"
                                 "2026-01-06,COMPRA,MiIBKR,KO,10,60,,,,,USD,\n")
        self.assertEqual([e["code"] for e in prev["errors"]], ["PESOS_EN_BROKER_EN_DOLARES"])
        monedas = {c for b in (prev.get("seed_suggestions") or {}).get("brokers", [])
                   for c in b.get("cash_overdraft", {})}
        self.assertTrue(monedas, "la compra en dólares sin efectivo tiene que pedir estado inicial")
        self.assertNotIn("ARS", monedas)

    # ── la foto de tenencia ──
    # La foto no crea el broker: va a uno que ya existe y da por hecho que es en
    # pesos, con sus dólares en "<broker> · USD".
    def subir_foto(self, broker, csv):
        r = self.client.post(
            "/api/imports/tenencia/preview", headers=self.h,
            data={"broker": broker, "format": "cocos"},
            files={"file": ("portfolio_report_20260301.csv", csv, "text/csv")})
        if r.status_code == 200:
            self.confirmar(r.json())
        return r

    FOTO = ("instrumento;cantidad;precio;moneda;total\n"
            "CEDEAR APPLE INC. (AAPL);20;22000;ARS;440000\n"
            "ARS;1500000;1;ARS;1500000\n"
            "USD;800;1;USD;800\n")

    def tenencia(self):
        return {(r["broker"], r["asset"]): (r["currency"], r["quantity"]) for r in self.sql(
            "SELECT broker, asset, currency, SUM(quantity) quantity FROM positions "
            "WHERE user_id=? AND is_cash=0 GROUP BY broker, asset, currency", self.uid)}

    def test_la_foto_entra_en_el_broker_que_creo_la_plantilla(self):
        """El camino completo: plantilla con pesos → el broker nace en pesos → la
        foto pone pesos en el broker y dólares en "· USD"."""
        self.confirmar(self.vista_previa("Cocos",
                                         "2026-01-05,DEPOSITO,Cocos,,,,1000000,,,,ARS,\n"
                                         "2026-01-06,DEPOSITO,Cocos,,,,500,,,,USD,\n"))
        r = self.subir_foto("Cocos", self.FOTO)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.brokers()["Cocos"], "ARS")
        cajas = self.cajas()
        self.assertEqual(cajas["Cocos"], ("ARS", 1_500_000.0))
        self.assertEqual(cajas["Cocos · USD"][1], 800.0)
        self.assertEqual(self.tenencia()[("Cocos", "AAPL")], ("ARS", 20.0))

    def test_una_foto_con_pesos_no_entra_a_un_broker_en_dolares_con_datos(self):
        """Antes: el CEDEAR en pesos quedaba adentro del broker en dólares. La foto
        trae títulos en pesos y efectivo SÓLO en dólares: lo que dispara el rechazo
        son los títulos."""
        self.crear_broker("Cocos", "USD", con_datos=True)
        antes = (self.brokers(), self.cajas(), self.tenencia())
        r = self.subir_foto("Cocos", "instrumento;cantidad;precio;moneda;total\n"
                                     "CEDEAR APPLE INC. (AAPL);20;22000;ARS;440000\n"
                                     "USD;800;1;USD;800\n")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("está en dólares y esta foto trae pesos", r.text)
        self.assertEqual((self.brokers(), self.cajas(), self.tenencia()), antes)

    def test_una_foto_con_pesos_cura_un_broker_en_dolares_vacio(self):
        """Antes: $1.500.000 de la foto quedaban como "US$1.500.000". La foto trae
        efectivo en pesos y NINGÚN título en pesos: lo que cura es el efectivo."""
        self.crear_broker("Cocos", "USD")
        r = self.subir_foto("Cocos", "instrumento;cantidad;precio;moneda;total\n"
                                     "CEDEAR APPLE INC. (AAPL);5;180;USD;900\n"
                                     "ARS;1500000;1;ARS;1500000\n"
                                     "USD;800;1;USD;800\n")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.brokers()["Cocos"], "ARS")
        cajas = self.cajas()
        self.assertEqual(cajas["Cocos"], ("ARS", 1_500_000.0))
        self.assertEqual(self.caja_en_dolares("Cocos"), 1500.0)       # no US$1.500.000
        self.assertEqual(cajas["Cocos · USD"][1], 800.0)

    def test_la_foto_con_pesos_no_va_a_la_subcuenta_en_dolares(self):
        conn = main.get_db()
        with conn:
            padre = conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                                 (self.uid, "Cocos", "ARS")).lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                         "VALUES (?,?,?,?)", (self.uid, "Cocos · USD", "USDT", padre))
            conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                         "VALUES (?,?,?,1,0)", (self.uid, "Cocos · USD", "USDT"))
        conn.close()
        r = self.subir_foto("Cocos · USD", self.FOTO)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("subila al broker «Cocos»", r.text)
        self.assertEqual(self.brokers()["Cocos · USD"], "USDT")

    # ── cambiar la moneda a mano (lo que pide el mensaje de la foto rechazada) ──
    def editar_broker(self, nombre, nuevo_nombre, moneda):
        bid = self.sql("SELECT id FROM brokers WHERE user_id=? AND name=?", self.uid, nombre)[0]["id"]
        r = self.client.put(f"/api/brokers/{bid}", headers=self.h,
                            json={"name": nuevo_nombre, "currency": moneda})
        self.assertEqual(r.status_code, 200, r.text)

    def test_cambiar_la_moneda_a_mano_cambia_el_rotulo_de_la_caja(self):
        """El camino que indica el mensaje: revertir (queda la caja "USD" en cero),
        pasar el broker a pesos y volver a subir. Antes los pesos se sumaban en la
        caja rotulada "USD"."""
        self.crear_broker("Cocos", "USD")
        self.editar_broker("Cocos", "Cocos", "ARS")
        self.assertEqual(self.cajas()["Cocos"], ("ARS", 0.0))
        self.confirmar(self.vista_previa("Cocos", "2026-01-05,DEPOSITO,Cocos,,,,1000,,,,USD,\n"
                                                  "2026-01-06,DEPOSITO,Cocos,,,,2000000,,,,ARS,\n"))
        self.assertEqual(self.cajas()["Cocos"], ("ARS", 2_000_000.0))
        self.assertEqual(self.caja_en_dolares("Cocos"), 2000.0)
        self.assertEqual(self.cajas()["Cocos · USD"][1], 1000.0)

    def test_renombrar_y_cambiar_la_moneda_tambien(self):
        self.crear_broker("MiBroker", "USD")
        self.editar_broker("MiBroker", "Cocos", "ARS")
        self.assertEqual(self.brokers(), {"Cocos": "ARS"})
        self.assertEqual(self.cajas(), {"Cocos": ("ARS", 0.0)})
        self.assertEqual(self.sql("SELECT currency FROM positions WHERE user_id=? AND is_cash=1",
                                  self.uid), [{"currency": "ARS"}])

    def test_una_foto_solo_en_dolares_sigue_entrando_a_un_broker_en_dolares(self):
        """Control: sin pesos en la foto, nada cambia."""
        self.crear_broker("MiIBKR", "USD", con_datos=True)
        r = self.subir_foto("MiIBKR", "instrumento;cantidad;precio;moneda;total\n"
                                      "CEDEAR APPLE INC. (AAPL);5;180;USD;900\n"
                                      "USD;800;1;USD;800\n")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.brokers()["MiIBKR"], "USD")


if __name__ == "__main__":
    unittest.main()
