"""Los BORDES de la bandeja de cobros de bonos.

Cada prueba de acá existe porque la prueba de mutación del 2026-10-10 rompió esa
línea a propósito y ninguna otra prueba se puso roja:

  · la ventana de ±14 días (se cambió a 1, 7 y 45 y todo seguía verde: todas las
    pruebas usaban "un día después");
  · la decisión del importador cuando el archivo y lo anotado están en monedas
    distintas (todos los archivos de prueba eran en dólares);
  · qué tipos de operación cuentan como cobro;
  · el cupón reemplazado que NO vuelve al revertir si el pago quedó cubierto;
  · re-aplicar las amortizaciones a mano cuando se BORRA un movimiento importado
    (sólo estaba probado el camino "se importa una venta");
  · el barrido de amortizaciones que corre después de confirmar un cobro.

Entra por las mismas puertas que la app; lo único reemplazado es el login.
"""
import io
import json
import unittest

import main
import cobros_bonos
from tests.test_cupones_bandeja import _Base, _csv


class _ConBonoAMano(_Base):
    """GD46 cargado por la app en una cuenta en dólares: 10.000 nominales a 0,60."""

    def setUp(self):
        super().setUp()
        self._broker("IOL", "USDT")
        self._ok(self.client.post("/api/cash/flow", json={
            "broker_name": "IOL", "direction": "deposit", "amount": 6000}))
        self._ok(self.client.post("/api/positions", json={
            "broker": "IOL", "asset": "GD46", "buy_price": 0.6, "quantity": 10000,
            "invested": 6000, "entry_date": "2025-03-03", "asset_type": "BOND"}))

    def _ok(self, r, codigo=200):
        self.assertEqual(r.status_code, codigo, r.text)
        return r

    def _importar_y_leer(self, broker, *rows):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(*rows)), "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        self._ok(r)
        return self._ok(self.client.post("/api/imports/confirm",
                                         json={"session_id": r.json()["session_id"]})).json()


class LaVentanaDeCatorceDias(_ConBonoAMano):
    def _cupon_el(self, fecha):
        self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "coupon", "amount": 20, "date": fecha}))

    def test_a_catorce_dias_es_el_mismo_pago_a_quince_es_otro(self):
        self._cupon_el("2026-07-09")
        for fecha, codigo in (("2026-06-25", 409), ("2026-07-23", 409),      # ±14: el mismo
                              ("2026-06-24", 200), ("2026-07-24", 200)):     # ±15: otro
            with self.subTest(fecha=fecha):
                r = self._pago(broker="IOL", asset="GD46", date=fecha, coupon_amount=5, amort_amount=0)
                self.assertEqual(r.status_code, codigo, r.text)
                if codigo == 200:      # se borra para que no tape al siguiente
                    oid = r.json()["partes"][0]["operation_id"]
                    self._ok(self.client.delete(f"/api/movements/op-{oid}-cobro"))

    def test_el_importador_usa_la_misma_ventana(self):
        self._cupon_el("2026-07-09")
        # A 14 días: es el cupón anotado → se saltea. A 15: es otro pago → entra.
        self._importar_y_leer("IOL", "2026-07-23,RENTA,IOL,GD46,,,20,,,0,USD,")
        self.assertEqual([o["op_type"] for o in self._ops("GD46")], ["Cupón"])
        self._importar_y_leer("IOL", "2026-07-24,RENTA,IOL,GD46,,,20,,,0,USD,")
        self.assertEqual(sorted(o["op_type"] for o in self._ops("GD46")), ["Cupón", "Dividendo"])

    def test_el_numero_es_catorce(self):
        self.assertEqual(cobros_bonos.VENTANA_DIAS, 14)


class QueCuentaComoCobro(_ConBonoAMano):
    def test_los_cinco_tipos_y_ninguno_mas(self):
        for t in ("Cupón", "Cupon", "CUPÓN", "Amortización", "amortizacion", "Dividendo",
                  "Interés", "Interes", "Renta", " renta "):
            self.assertTrue(cobros_bonos.es_cobro_de_renta(t), t)
        for t in ("Interés PF", "Venta", "Compra", "", None, "CONVERSION MEP ARS→USDT"):
            self.assertFalse(cobros_bonos.es_cobro_de_renta(t), t)

    def test_un_interes_importado_del_bono_frena_a_la_bandeja(self):
        """El archivo de algunos brokers llama «interés» al cupón."""
        self._importar_y_leer("IOL", "2026-07-10,INTERES,IOL,GD46,,,20,,,0,USD,")
        self.assertEqual([o["op_type"] for o in self._ops("GD46")], ["Interés"])
        self.assertEqual(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                                    coupon_amount=20, amort_amount=0).status_code, 409)

    def test_la_venta_amortizacion_de_otro_bono_no_frena(self):
        self._importar_y_leer("IOL", "2025-03-03,COMPRA,IOL,GD35,1000,0.6,600,,,0,USD,",
                              "2026-07-10,VENTA,IOL,GD35,100,1,100,,,0,USD,Renta y Amortizacion")
        self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                            coupon_amount=20, amort_amount=0))


class ElArchivoEnOtraMoneda(_Base):
    """AL30 a mano en «Cocos» (pesos), con su hermana «Cocos · USD». El cupón se
    anota en dólares; el archivo del broker lo trae en pesos."""

    def setUp(self):
        super().setUp()
        self._broker("Cocos", "ARS")
        self._broker("Cocos · USD", "USDT", parent="Cocos")
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date='2024-01-15'")
        self.conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                          "VALUES ('2024-01-15', 1000, 1000, 'manual')")
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, tc_compra, entry_date, commissions, asset_type, currency)
               VALUES (?, 'Cocos', 'AL30', 0, 600, 9200, 5520000, 1000, '2024-01-15', 0, 'BOND', 'ARS')""",
            (self.uid,))
        self.conn.commit()
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=27, amort_amount=0, cash_broker="Cocos · USD")
        self.assertEqual(r.status_code, 200, r.text)
        self.tc = float(main._user_tc_blue(self.conn, self.uid))

    def _importar_en_pesos(self, pesos):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(
                f"2026-07-10,RENTA,Cocos,AL30,,,{pesos},,,0,ARS,")), "text/csv"))],
            data={"format": "rendi_generic", "broker": "Cocos"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_el_mismo_cupon_en_pesos_se_reconoce(self):
        """US$ 27 anotados; el archivo trae los pesos equivalentes. Es el mismo
        cobro: se saltea. Comparando 37.800 contra 27 sin convertir, no se
        parecían y el archivo reemplazaba (o duplicaba) lo anotado."""
        res = self._importar_en_pesos(round(27 * self.tc))
        self.assertIn("ya lo anotaste", json.dumps(res, ensure_ascii=False))
        self.assertEqual([o["op_type"] for o in self._ops("AL30")], ["Cupón"])
        self.assertAlmostEqual(self._efectivo("Cocos · USD"), 27, places=2)
        self.assertAlmostEqual(self._efectivo("Cocos"), 0, places=2)

    def test_un_monto_en_pesos_que_no_es_ese_cupon_no_se_descarta(self):
        """Con monedas distintas alcanzaba con el tipo: un cupón a mano de US$ 27
        hacía descartar un renglón de $ 900.000 (más de US$ 600). Ahora se compara
        en dólares: no se parece, y como a mano hay sólo un cupón, manda el broker."""
        self._importar_en_pesos(900000)
        self.assertEqual([o["op_type"] for o in self._ops("AL30")], ["Dividendo"])
        self.assertAlmostEqual(self._efectivo("Cocos"), 900000, places=2)
        self.assertAlmostEqual(self._efectivo("Cocos · USD"), 0, places=2)

    def test_sin_tipo_de_cambio_alcanza_con_el_tipo(self):
        """Si el renglón en pesos no se puede pasar a dólares, no se adivina: es
        un cobro del mismo tipo en la ventana → se saltea (no entra además)."""
        accion, dato = cobros_bonos.que_hacer_con_el_renglon(
            self.conn, self.uid, "Cocos", "AL30", "2026-07-10",
            monto=900000, moneda="ARS", tc=None)
        self.assertEqual(accion, cobros_bonos.SALTEAR)
        self.assertEqual(dato["op_type"], "Cupón")


class ElCuponReemplazadoYElRevert(_ConBonoAMano):
    def test_no_vuelve_si_el_pago_quedo_cubierto_por_otro_import(self):
        """A mano 75. El archivo A trae 50 y lo reemplaza. El archivo B trae otro
        renglón del mismo pago. Al revertir A, el cupón a mano NO vuelve: el pago
        ya está anotado por B, y volver lo contaría dos veces."""
        self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "coupon", "amount": 75, "date": "2026-07-09"}))
        a = self._importar_y_leer("IOL", "2026-07-10,RENTA,IOL,GD46,,,50,,,0,USD,")["batch_id"]
        self._importar_y_leer("IOL", "2026-07-13,RENTA,IOL,GD46,,,52,,,0,USD,")
        self._ok(self.client.post(f"/api/imports/{a}/revert"))
        ops = self._ops("GD46")
        self.assertEqual([(o["op_type"], o["quantity"]) for o in ops], [("Dividendo", 52.0)])
        self.assertAlmostEqual(self._efectivo("IOL"), 52, places=2)

    def test_vuelve_si_no_quedo_nada_que_lo_cubra(self):
        self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "coupon", "amount": 75, "date": "2026-07-09"}))
        a = self._importar_y_leer("IOL", "2026-07-10,RENTA,IOL,GD46,,,50,,,0,USD,")["batch_id"]
        self._ok(self.client.post(f"/api/imports/{a}/revert"))
        self.assertEqual([(o["op_type"], o["quantity"]) for o in self._ops("GD46")], [("Cupón", 75.0)])
        self.assertAlmostEqual(self._efectivo("IOL"), 75, places=2)
        # Y la tabla de lo reemplazado quedó vacía (no vuelve dos veces).
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM dividendos_reemplazados WHERE user_id=?", (self.uid,)).fetchone()[0], 0)


class RearmarLosLotesAlBorrarUnMovimientoImportado(_Base):
    """GD46 IMPORTADO, con una amortización confirmada a mano y una venta importada."""

    def setUp(self):
        super().setUp()
        self._broker("Balanz", "USDT")
        self._importar("Balanz",
                       "2025-03-01,DEPOSITO,Balanz,,,,20000,,,0,USD,",
                       "2025-03-03,COMPRA,Balanz,GD46,10000,0.6,6000,,,0,USD,")
        r = self._pago(broker="Balanz", asset="GD46", date="2026-07-09",
                       coupon_amount=0, amort_amount=227, face_amortized=227)
        self.assertEqual(r.status_code, 200, r.text)
        self.cobro = r.json()["partes"][0]["operation_id"]
        self._importar("Balanz", "2026-08-03,VENTA,Balanz,GD46,1000,0.7,700,,,0,USD,")
        self.assertAlmostEqual(self._nominal("GD46"), 8773, places=4)

    def test_la_venta_importada_de_un_bono_no_se_borra_de_a_una(self):
        """La prueba de mutación marcó que el rearmado al BORRAR un movimiento
        importado (`rebuild.rebuild_pair_asset`) podía dejar de re-aplicar las
        amortizaciones a mano sin que nada se pusiera rojo. Medido: hoy ese
        camino no existe para un bono — la venta importada de un bono no se
        borra de a una (ni etiquetada BOND ni sin etiquetar), y el borrado del
        activo entero exige borrar antes los cobros a mano
        (`BorrarElBonoEnteroConCobrosAMano`). Lo que se fija acá es eso: que la
        puerta siga cerrada. Si algún día se abre, esta prueba se pone roja y
        hay que medir el rearmado con una amortización confirmada."""
        venta = [m for m in self.client.get("/api/movements").json()
                 if m.get("asset") == "GD46" and m["type"] == "SELL"][0]
        self.assertEqual(self.client.delete(f"/api/movements/{venta['id']}").status_code, 400)
        self.conn.execute("UPDATE import_normalized_tx SET asset_type='OTHER' WHERE asset_symbol='GD46'")
        self.conn.commit()
        self.assertEqual(self.client.delete(f"/api/movements/{venta['id']}").status_code, 400)
        self.assertAlmostEqual(self._nominal("GD46"), 8773, places=4)


class ElBarridoCorreAlConfirmar(_Base):
    """GD30 importado. El barrido de amortizaciones corre al importar, no todos
    los días: el lote puede estar con el residual de hace meses."""

    def setUp(self):
        super().setUp()
        self._broker("Balanz", "USDT")
        self._importar("Balanz",
                       "2025-03-01,DEPOSITO,Balanz,,,,10000,,,0,USD,",
                       "2025-03-03,COMPRA,Balanz,GD30,10000,0.6,6000,,,0,USD,")

    def test_confirmar_la_amortizacion_deja_el_lote_al_dia(self):
        """El costo que se le resta a la ganancia tiene que salir del lote. En un
        lote del barrido lo saca el barrido: si no corre al confirmar, el costo
        seguía adentro hasta el próximo archivo (y una venta en el medio lo
        restaba otra vez)."""
        al_dia = self._nominal("GD30")
        # Como quedó después de un import de hace un año: 80 % vivo.
        self.conn.execute("UPDATE positions SET quantity=8000, invested=4800 "
                          "WHERE user_id=? AND asset='GD30'", (self.uid,))
        self.conn.commit()
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800, face_amortized=800)
        self.assertEqual(r.status_code, 200, r.text)
        am = [p for p in r.json()["partes"] if p["op_type"] == "Amortización"][0]
        self.assertAlmostEqual(am["cost_basis_consumed"], 480, places=2)     # 800 × 0,60
        lote = self.conn.execute("SELECT quantity, invested FROM positions WHERE user_id=? "
                                 "AND asset='GD30' AND is_cash=0", (self.uid,)).fetchone()
        self.assertAlmostEqual(lote["quantity"], al_dia, places=4)
        self.assertAlmostEqual(lote["invested"], al_dia * 0.6, places=2)


class BorrarElBonoEnteroConCobrosAMano(_Base):
    def test_el_mensaje_dice_como_salir_y_la_salida_funciona(self):
        """Decía "llega en la próxima versión" y no había forma de saber qué hacer."""
        self._broker("Balanz", "USDT")
        self._importar("Balanz",
                       "2025-03-01,DEPOSITO,Balanz,,,,20000,,,0,USD,",
                       "2025-03-03,COMPRA,Balanz,GD46,10000,0.6,6000,,,0,USD,")
        r = self._pago(broker="Balanz", asset="GD46", date="2026-07-09",
                       coupon_amount=20, amort_amount=227, face_amortized=227)
        self.assertEqual(r.status_code, 200, r.text)
        borrar = lambda: self.client.delete("/api/assets/history", params={"asset": "GD46"})
        resp = borrar()
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("2 cobros anotados a mano", resp.text)
        self.assertIn("Borralos primero en Movimientos", resp.text)
        for pt in r.json()["partes"]:
            self.assertEqual(self.client.delete(
                f"/api/movements/op-{pt['operation_id']}-cobro").status_code, 200)
        self.assertEqual(borrar().status_code, 200)
        self.assertAlmostEqual(self._nominal("GD46"), 0, places=4)
        self.assertAlmostEqual(self._efectivo("Balanz"), 20000, places=2)


if __name__ == "__main__":
    unittest.main()
