"""Los LECTORES de un cobro de bono: todo lo que lee la fila después de anotada.

La causa raíz más frecuente de este repo es el arreglo que no se propaga. La
bandeja de bonos cambió qué guarda la fila de un cobro (`quantity` = lo que
entró, `pnl_usd` = la ganancia, en la moneda de la cuenta; la fila vive en la
cuenta donde entró la plata, que puede ser «· USD»), y la auditoría del
2026-10-10 encontró lectores que seguían leyendo la fila como una venta:

  · el chat de IA recibía un cupón de $ 95.000 como `pnl_usd: 95000` (US$ 76) y
    "operación cerrada", y una amortización como "800 unidades";
  · la herramienta del bot y el paquete de la posición, lo mismo — y el paquete
    filtraba por el nombre exacto de la cuenta y no veía ningún cobro;
  · el archivo de operaciones ponía la plata cobrada bajo "Cantidad";
  · el libro del asesor marcaba el costo del bono como incompleto.

Entra por las mismas puertas que la app (el pago se confirma por
/api/bonds/cashflow/pago); lo único reemplazado es el login.
"""
import unittest

import main
import realized_pnl
from ai.builders import position_lots
from tests.test_cupones_bandeja import _Base


class LectoresTest(_Base):
    """AL30 (dólares) y TX26 (pesos) cargados en «Cocos»; el AL30 cobra en
    «Cocos · USD» y el TX26 en pesos, con el dólar del día a 1.250."""

    def setUp(self):
        super().setUp()
        self._broker("Cocos", "ARS")
        self._broker("Cocos · USD", "USDT", parent="Cocos")
        for fecha, tc in (("2024-01-15", 1000), ("2026-08-10", 1250)):
            self.conn.execute("DELETE FROM fx_rates_daily WHERE date=?", (fecha,))
            self.conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                              "VALUES (?,?,?, 'manual')", (fecha, tc, tc))
        for activo, cant, inv in (("AL30", 9200, 5520000), ("TX26", 1000000, 900000)):
            self.conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                       invested, tc_compra, entry_date, commissions, asset_type, currency)
                   VALUES (?, 'Cocos', ?, 0, 1, ?, ?, 1000, '2024-01-15', 0, 'BOND', 'ARS')""",
                (self.uid, activo, cant, inv))
        self.conn.commit()
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800, cash_broker="Cocos · USD")
        self.assertEqual(r.status_code, 200, r.text)
        r = self._pago(broker="Cocos", asset="TX26", date="2026-08-10",
                       coupon_amount=95000, amort_amount=0)
        self.assertEqual(r.status_code, 200, r.text)

    def test_la_fila_guarda_pesos_y_la_regla_los_lee_en_dolares(self):
        cupon = self._ops("TX26")[0]
        self.assertEqual((cupon["pnl_usd"], cupon["currency"], cupon["fx_to_usd"]), (95000, "ARS", 1250))
        leido = realized_pnl.leer_cobro(cupon)
        self.assertAlmostEqual(leido["amount_usd"], 76, places=2)
        self.assertAlmostEqual(leido["pnl_usd"], 76, places=2)
        amort = [o for o in self._ops("AL30") if o["op_type"] == "Amortización"][0]
        leido = realized_pnl.leer_cobro(amort)
        self.assertEqual(leido["type"], "AMORTIZATION")
        self.assertAlmostEqual(leido["amount_usd"], 800, places=2)
        self.assertAlmostEqual(leido["pnl_usd"], 320, places=2)

    def test_el_chat_recibe_cobros_no_operaciones_cerradas(self):
        """La foto que arma el navegador son las filas de /api/operations tal cual."""
        foto = main._sanitize_chat_snapshot({"operations": self.client.get("/api/operations").json()})
        por = {(o["asset"], o["op_type"]): o for o in foto["operations"]}
        self.assertEqual({o["_kind"] for o in foto["operations"]}, {"income"})
        self.assertEqual(por[("TX26", "Cupón")]["amount_usd"], 76.0)
        self.assertEqual(por[("TX26", "Cupón")]["gain_usd"], 76.0)
        self.assertEqual(por[("AL30", "Amortización")]["amount_usd"], 800.0)
        self.assertEqual(por[("AL30", "Amortización")]["gain_usd"], 320.0)
        for o in foto["operations"]:
            self.assertFalse({"quantity", "pnl_usd", "fx_to_usd", "currency"} & set(o), o)

    def test_una_venta_sigue_siendo_una_operacion_cerrada(self):
        foto = main._sanitize_chat_snapshot({"operations": [
            {"date": "2026-08-03", "broker": "Cocos", "asset": "GGAL", "op_type": "Venta",
             "quantity": 10, "exit_price": 5, "pnl_usd": 12.5, "fx_to_usd": 1250, "currency": "ARS"}]})
        self.assertEqual(foto["operations"], [
            {"date": "2026-08-03", "broker": "Cocos", "asset": "GGAL", "op_type": "Venta",
             "quantity": 10, "exit_price": 5, "pnl_usd": 12.5, "currency": "ARS",
             "_kind": "closed_trade"}])

    def test_la_herramienta_del_bot(self):
        out = main._execute_ai_tool_inner("get_asset_operations", {"asset": "TX26"}, self.uid)
        self.assertEqual(out["operations"], [{"date": "2026-08-10", "op_type": "Cupón",
                                              "amount_usd": 76.0, "gain_usd": 76.0, "kind": "income"}])

    def test_el_paquete_de_la_posicion_ve_el_cobro_de_la_otra_pata(self):
        """La pantalla pide por la cuenta del LOTE («Cocos»); el cobro del AL30
        vive en «Cocos · USD»."""
        paquete = position_lots.build(self.conn, self.uid, asset="AL30", broker="Cocos")
        self.assertEqual(sorted((l["op_type"], l["kind"], l["amount_usd"], l["pnl_usd"])
                                for l in paquete["lots"]),
                         [("Amortización", "income", 800.0, 320.0), ("Cupón", "income", 27.0, 27.0)])
        self.assertFalse(any("qty" in l for l in paquete["lots"]))

    def test_el_archivo_de_operaciones_no_pone_la_plata_bajo_cantidad(self):
        self.conn.execute("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))
        self.conn.commit()
        import csv, io
        filas = list(csv.DictReader(io.StringIO(self.client.get("/api/export/operations.csv").text.lstrip("﻿"))))
        cobros = [f for f in filas if f["Activo"] in ("AL30", "TX26")]
        self.assertEqual(len(cobros), 3)
        self.assertEqual({f["Cantidad"] for f in cobros}, {""})

    def test_el_libro_del_asesor_conoce_el_costo_de_la_amortizacion(self):
        agg = main._advisor_realized_raw(self.conn, [self.uid])
        al30 = [v for k, v in agg.items() if k[1] == "AL30"][0]
        self.assertFalse(al30["cost_incomplete"])
        self.assertAlmostEqual(al30["realized_usd"], 320, places=2)   # la amortización
        self.assertAlmostEqual(al30["cost_usd"], 480, places=2)       # 800 × 0,60
        self.assertAlmostEqual(al30["income_usd"], 27, places=2)      # el cupón


if __name__ == "__main__":
    unittest.main()
