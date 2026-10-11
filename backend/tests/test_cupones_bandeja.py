"""La bandeja de cobros de bonos de Cartera: confirmar un pago del cronograma.

Gemela de test_dividendos_bandeja.py. Entra por las MISMAS puertas que la app
(importar, /api/positions, /api/bonds/cashflow/pago, borrar desde Movimientos);
lo único reemplazado es el login.

Lo que fija, con los tres errores que tenía el registro de cobros hasta el
2026-10-09:

  1. Una amortización es tu plata que vuelve: sólo cuenta como GANANCIA lo que
     cobraste por encima de lo que te había costado esa parte. Antes la fila
     guardaba el cobro entero y el recálculo mensual lo sumaba como ganancia
     (un pago de GD30 de US$ 795 anotaba US$ 795 en vez de US$ 334).
  2. Los nominales de un bono importado los baja el barrido de amortizaciones
     (por calendario). Confirmar la amortización NO los vuelve a bajar (antes:
     6.400 → 5.630,77).
  3. Lo que ya está anotado no se anota dos veces (409), y si después se importa
     el archivo con el mismo pago, el renglón del archivo se saltea (o, si a mano
     había sólo un cupón con otro monto, lo reemplaza): nunca entra además.

Y lo de la cuenta: un bono en dólares comprado en la cuenta en pesos cobra en la
cuenta en dólares; borrar el cobro devuelve el nominal a la cuenta del bono.
"""
import io
import json
import unittest

from fastapi.testclient import TestClient

import main

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


class _Base(unittest.TestCase):
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
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cupones_bandeja@rendi.test", "x")).lastrowid
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    # ── infra ────────────────────────────────────────────────────────────────
    def _broker(self, name, currency, parent=None):
        pid = None
        if parent:
            pid = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                    (self.uid, parent)).fetchone()["id"]
        self.conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                          "VALUES (?,?,?,?)", (self.uid, name, currency, pid))
        self.conn.commit()

    def _importar(self, broker, *rows):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(*rows)), "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def _efectivo(self, broker):
        return sum(float(p.get("invested") or 0) for p in self.client.get("/api/positions").json()
                   if p.get("is_cash") and p["broker"] == broker)

    def _nominal(self, asset):
        return sum(float(p["quantity"] or 0) for p in self.client.get("/api/positions").json()
                   if not p.get("is_cash") and p["asset"] == asset)

    def _ganancia_realizada(self):
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()[0])

    def _ops(self, asset):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM operations WHERE user_id=? AND asset=? ORDER BY id",
            (self.uid, asset)).fetchall()]

    def _pago(self, **kw):
        return self.client.post("/api/bonds/cashflow/pago", json=kw)


class BonoImportadoTest(_Base):
    """GD30 importado en una cuenta en dólares: 10.000 nominales a 0,60."""

    def setUp(self):
        super().setUp()
        self._broker("Balanz", "USDT")
        self._importar("Balanz",
                       "2025-03-01,DEPOSITO,Balanz,,,,10000,,,0,USD,",
                       "2025-03-03,COMPRA,Balanz,GD30,10000,0.6,6000,,,0,USD,")
        # El barrido ya lo llevó al nominal vivo de hoy (4 % + 4×8 % devueltos = 64 %).
        self.nominal_antes = self._nominal("GD30")
        self.efectivo_antes = self._efectivo("Balanz")

    def test_la_posicion_dice_que_su_nominal_ya_es_el_vivo(self):
        gd30 = [p for p in self.client.get("/api/positions").json() if p["asset"] == "GD30"]
        self.assertTrue(gd30 and all(p["nominal_por_barrido"] for p in gd30))

    def test_el_nominal_original_no_depende_de_cuando_corrio_el_barrido(self):
        """El barrido corre al importar, no todos los días: un lote importado en
        junio sigue con el residual de junio. El original que manda el servidor
        sale de las compras y ventas del archivo, no de esa cantidad."""
        self.conn.execute("UPDATE positions SET quantity=7200, invested=4320 "
                          "WHERE user_id=? AND asset='GD30'", (self.uid,))
        self.conn.commit()
        gd30 = [p for p in self.client.get("/api/positions").json() if p["asset"] == "GD30"]
        self.assertAlmostEqual(sum(p["nominal_original"] for p in gd30), 10000, places=2)
        self.assertAlmostEqual(sum(p["quantity"] for p in gd30), 7200, places=2)

    def test_confirmar_el_pago_entero(self):
        # Julio 2026 por 10.000 nominales: cupón 0,75 %/2 sobre el 72 % vivo = 27;
        # cuota de 8 % = 800 (a la par). Costo de esos 800 nominales: 800 × 0,60.
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800)
        self.assertEqual(r.status_code, 200, r.text)
        ops = {o["op_type"]: o for o in self._ops("GD30")}
        self.assertEqual(set(ops), {"Cupón", "Amortización"})
        # (2) los nominales NO se bajan otra vez: ya los bajó el barrido.
        self.assertAlmostEqual(self._nominal("GD30"), self.nominal_antes, places=4)
        # (1) la amortización anota sólo su ganancia; lo cobrado va en quantity.
        self.assertAlmostEqual(ops["Amortización"]["quantity"], 800, places=2)
        self.assertAlmostEqual(ops["Amortización"]["cost_basis_consumed"], 480, places=2)
        self.assertAlmostEqual(ops["Amortización"]["pnl_usd"], 320, places=2)
        self.assertAlmostEqual(ops["Cupón"]["pnl_usd"], 27, places=2)
        # Efectivo: entra el pago entero. Ganancia realizada: 27 + 320, ya, sin esperar.
        self.assertAlmostEqual(self._efectivo("Balanz") - self.efectivo_antes, 827, places=2)
        self.assertAlmostEqual(self._ganancia_realizada(), 347, places=2)

    def test_no_se_anota_dos_veces(self):
        self.assertEqual(self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                                    coupon_amount=27, amort_amount=800).status_code, 200)
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-10",
                       coupon_amount=27, amort_amount=800)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(len(self._ops("GD30")), 2)

    def test_un_cupon_importado_tambien_frena(self):
        self._importar("Balanz", "2026-07-10,RENTA Y AMORTIZACION,Balanz,GD30,,,827,,,0,USD,")
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800)
        self.assertEqual(r.status_code, 409, r.text)

    def test_importar_despues_no_lo_suma_dos_veces(self):
        """Lo confirmado a mano manda: separa cupón (ganancia) de amortización
        (capital) y ya resolvió los nominales. La fila del archivo se saltea con un
        aviso — y revertir ese import no toca lo confirmado."""
        self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                   coupon_amount=27, amort_amount=800)
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(
                "2026-07-10,RENTA Y AMORTIZACION,Balanz,GD30,,,827,,,0,USD,")), "text/csv"))],
            data={"format": "rendi_generic", "broker": "Balanz"})
        r = self.client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("ya lo anotaste", json.dumps(r.json(), ensure_ascii=False))
        tipos = sorted(o["op_type"] for o in self._ops("GD30"))
        self.assertEqual(tipos, ["Amortización", "Cupón"])
        # El pago entró UNA vez al efectivo, no dos; la ganancia sigue separada.
        self.assertAlmostEqual(self._efectivo("Balanz") - self.efectivo_antes, 827, places=2)
        self.assertAlmostEqual(self._ganancia_realizada(), 347, places=2)

    def test_la_fila_salteada_no_queda_viva_en_lo_importado(self):
        """La fila del archivo que se salteó no aparece en Movimientos y revertir
        ese import no le saca al efectivo una plata que nunca entró por ella."""
        self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                   coupon_amount=27, amort_amount=800)
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(
                "2026-07-10,RENTA Y AMORTIZACION,Balanz,GD30,,,827,,,0,USD,")), "text/csv"))],
            data={"format": "rendi_generic", "broker": "Balanz"})
        r = self.client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        batch = r.json()["batch_id"]
        movs = [m for m in self.client.get("/api/movements").json()
                if m.get("asset") == "GD30" and m["type"] in ("DIVIDEND", "AMORTIZATION")]
        self.assertEqual(sorted(m["source"] for m in movs), ["manual", "manual"])
        efectivo = self._efectivo("Balanz")
        self.assertEqual(self.client.post(f"/api/imports/{batch}/revert").status_code, 200)
        self.assertAlmostEqual(self._efectivo("Balanz"), efectivo, places=2)
        self.assertEqual(len(self._ops("GD30")), 2)

    def test_el_archivo_trae_la_amortizacion_que_faltaba(self):
        """A mano sólo el cupón (formulario). El archivo trae el cupón y, aparte, la
        amortización: el cupón se saltea (ya está) y la amortización entra."""
        self.assertEqual(self.client.post("/api/bonds/cashflow", json={
            "broker": "Balanz", "asset": "GD30", "flow_type": "coupon",
            "amount": 27, "date": "2026-07-09"}).status_code, 200)
        self._importar("Balanz", "2026-07-10,RENTA,Balanz,GD30,,,27,,,0,USD,",
                       "2026-07-10,AMORTIZACION,Balanz,GD30,,,800,,,0,USD,")
        self.assertAlmostEqual(self._efectivo("Balanz") - self.efectivo_antes, 827, places=2)

    def test_el_archivo_trae_todo_junto_y_a_mano_estaba_solo_el_cupon(self):
        """El renglón "renta y amortización" trae ADENTRO el cupón ya anotado: el de
        a mano se reemplaza (no bajó nominales), y la plata entra una sola vez."""
        self.assertEqual(self.client.post("/api/bonds/cashflow", json={
            "broker": "Balanz", "asset": "GD30", "flow_type": "coupon",
            "amount": 27, "date": "2026-07-09"}).status_code, 200)
        self._importar("Balanz", "2026-07-10,RENTA Y AMORTIZACION,Balanz,GD30,,,827,,,0,USD,")
        self.assertEqual([o["op_type"] for o in self._ops("GD30")], ["Dividendo"])
        self.assertAlmostEqual(self._efectivo("Balanz") - self.efectivo_antes, 827, places=2)

    def test_el_csv_del_contador_trae_lo_cobrado(self):
        self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                   coupon_amount=27, amort_amount=800)
        self.conn.execute("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))
        self.conn.commit()
        csv = self.client.get("/api/export/transactions.csv").text
        filas = [l for l in csv.splitlines() if ",GD30," in l and "2026-07-09" in l]
        self.assertTrue(any("DIVIDENDO" in l and ",27.0," in l for l in filas), filas)
        self.assertTrue(any("AMORTIZACIÓN" in l and ",800.0," in l for l in filas), filas)

    def test_movimientos_muestra_lo_cobrado_no_una_venta(self):
        self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                   coupon_amount=27, amort_amount=800)
        movs = [m for m in self.client.get("/api/movements").json()
                if m.get("asset") == "GD30" and m.get("source") == "manual"]
        por_tipo = {m["type"]: m for m in movs}
        self.assertEqual(set(por_tipo), {"DIVIDEND", "AMORTIZATION"})
        self.assertAlmostEqual(por_tipo["AMORTIZATION"]["amount_usd"], 800, places=2)
        self.assertAlmostEqual(por_tipo["AMORTIZATION"]["pnl_usd"], 320, places=2)
        self.assertAlmostEqual(por_tipo["DIVIDEND"]["amount_usd"], 27, places=2)

    def test_el_formulario_tambien_frena_lo_ya_importado(self):
        self._importar("Balanz", "2026-07-10,RENTA Y AMORTIZACION,Balanz,GD30,,,827,,,0,USD,")
        r = self.client.post("/api/bonds/cashflow", json={
            "broker": "Balanz", "asset": "GD30", "flow_type": "coupon",
            "amount": 27, "date": "2026-07-09"})
        self.assertEqual(r.status_code, 409, r.text)

    def test_el_formulario_deja_cargar_cupon_y_amortizacion_del_mismo_pago(self):
        for flow, monto in (("coupon", 27), ("amortization", 800)):
            r = self.client.post("/api/bonds/cashflow", json={
                "broker": "Balanz", "asset": "GD30", "flow_type": flow,
                "amount": monto, "date": "2026-07-09"})
            self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/bonds/cashflow", json={
            "broker": "Balanz", "asset": "GD30", "flow_type": "coupon",
            "amount": 27, "date": "2026-07-09"})
        self.assertEqual(r.status_code, 409, r.text)

    def test_lotes_mezclados_el_cobro_baja_solo_los_que_no_baja_el_barrido(self):
        """Un lote importado (lo baja el barrido) y uno cargado a mano (no lo baja
        nadie más) del mismo bono: el cobro descuenta la parte del de a mano y no
        toca el importado."""
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, commissions, asset_type, currency)
               VALUES (?, 'Balanz', 'GD30', 0, 0.6, 880, 528, '2025-03-03', 0, 'BOND', 'USD')""",
            (self.uid,))
        self.conn.commit()
        # El de a mano: 880 vivos al 03/03/2025 (quedaba el 88 %) = 1.000 originales.
        # El importado: 10.000 originales. El pago es el 8 % de los 11.000, a la par,
        # y se reparte por nominal ORIGINAL: 80 del de a mano, 800 del importado.
        lotes = {p["id"]: p for p in self.client.get("/api/positions").json() if p["asset"] == "GD30"}
        self.assertAlmostEqual(sum(p["nominal_original"] for p in lotes.values()
                                   if p["nominal_por_barrido"]), 10000, places=2)
        self.assertEqual([p["nominal_al_cargar"] for p in lotes.values()
                          if not p["nominal_por_barrido"]], [880])
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                       coupon_amount=0, amort_amount=880)
        self.assertEqual(r.status_code, 200, r.text)
        lotes = {p["id"]: p for p in self.client.get("/api/positions").json() if p["asset"] == "GD30"}
        a_mano = [p for p in lotes.values() if not p["nominal_por_barrido"]]
        importado = [p for p in lotes.values() if p["nominal_por_barrido"]]
        self.assertAlmostEqual(sum(p["quantity"] for p in importado), self.nominal_antes, places=4)
        self.assertAlmostEqual(sum(p["quantity"] for p in a_mano), 800, places=4)
        # Lo de a mano sigue diciendo con cuánto nació (800 de hoy + los 80 que bajó).
        self.assertEqual([p["nominal_al_cargar"] for p in a_mano], [880])
        # Costo: 0,60 por nominal en los dos lotes → 880 × 0,60 = 528; ganancia 352.
        am = [o for o in self._ops("GD30") if o["op_type"] == "Amortización"][0]
        self.assertAlmostEqual(am["cost_basis_consumed"], 528, places=2)
        self.assertAlmostEqual(am["pnl_usd"], 352, places=2)

    def test_lote_a_mano_comprado_despues_del_pago_no_entra_en_el_reparto(self):
        """Importado + un lote a mano comprado DESPUÉS de la fecha del pago: el de a
        mano no cobró ese pago, así que ni se le baja nominal ni entra en el costo."""
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, commissions, asset_type, currency)
               VALUES (?, 'Balanz', 'GD30', 0, 0.9, 6400, 5760, '2026-09-01', 0, 'BOND', 'USD')""",
            (self.uid,))
        self.conn.commit()
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                       coupon_amount=0, amort_amount=800)
        self.assertEqual(r.status_code, 200, r.text)
        a_mano = [p for p in self.client.get("/api/positions").json()
                  if p["asset"] == "GD30" and not p["nominal_por_barrido"]]
        self.assertEqual([p["quantity"] for p in a_mano], [6400])
        am = self._ops("GD30")[0]
        self.assertAlmostEqual(am["cost_basis_consumed"], 480, places=2)   # 800 × 0,60
        self.assertAlmostEqual(am["pnl_usd"], 320, places=2)

    def test_lote_importado_comprado_despues_del_pago_no_entra_en_el_costo(self):
        """Un segundo lote importado, comprado en agosto a 0,90. El pago de julio
        no lo cobró: el costo de lo amortizado sale sólo del primero (800 × 0,60).
        Anotaba costo 600 y ganancia 200."""
        self._importar("Balanz", "2026-08-03,COMPRA,Balanz,GD30,2000,0.9,1800,,,0,USD,")
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                       coupon_amount=0, amort_amount=800)
        self.assertEqual(r.status_code, 200, r.text)
        am = self._ops("GD30")[-1]
        self.assertAlmostEqual(am["cost_basis_consumed"], 480, places=2)
        self.assertAlmostEqual(am["pnl_usd"], 320, places=2)

    def test_deshacer_desde_movimientos(self):
        r = self._pago(broker="Balanz", asset="GD30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800)
        for p in r.json()["partes"]:
            d = self.client.delete(f"/api/movements/op-{p['operation_id']}-cobro")
            self.assertEqual(d.status_code, 200, d.text)
        self.assertEqual(self._ops("GD30"), [])
        self.assertAlmostEqual(self._efectivo("Balanz"), self.efectivo_antes, places=2)
        self.assertAlmostEqual(self._nominal("GD30"), self.nominal_antes, places=4)
        self.assertAlmostEqual(self._ganancia_realizada(), 0, places=2)


class BonoSinCronogramaEnElServidorTest(_Base):
    """GD46 importado: el servidor no tiene su cronograma, así que el barrido no le
    baja nominales — se los baja el cobro. Y los lotes importados se REARMAN cada
    vez que un archivo nuevo trae una compra o una venta de ese bono."""

    def setUp(self):
        super().setUp()
        self._broker("Balanz", "USDT")
        self._importar("Balanz",
                       "2025-03-01,DEPOSITO,Balanz,,,,20000,,,0,USD,",
                       "2025-03-03,COMPRA,Balanz,GD46,10000,0.6,6000,,,0,USD,")

    def test_la_cantidad_importada_es_nominal_original(self):
        """Una sola lectura de la cantidad del archivo: nominal ORIGINAL, como en
        AL30. La pantalla la tomaba como "lo vivo el día de la compra" y de 10.000
        hacía 10.476. Y sigue en 10.000 después de cobrar una amortización."""
        def gd46():
            return [p for p in self.client.get("/api/positions").json() if p["asset"] == "GD46"]
        self.assertEqual([(p["nominal_original"], p["nominal_por_barrido"], p.get("nominal_al_cargar"))
                          for p in gd46()], [(10000, False, None)])
        self.assertEqual(self._pago(broker="Balanz", asset="GD46", date="2026-07-09",
                                    coupon_amount=0, amort_amount=227).status_code, 200)
        self.assertEqual([(p["quantity"], p["nominal_original"]) for p in gd46()], [(9773, 10000)])

    def test_el_asesor_lee_los_mismos_nominales_que_la_cartera_del_cliente(self):
        """Cobros (asesor) y Cartera (cliente) salen de la MISMA función. El asesor
        tenía una copia, y ya le faltaba la regla de arriba."""
        del_cliente = [(p["quantity"], p.get("nominal_original"), p.get("nominal_al_cargar"))
                       for p in self.client.get("/api/positions").json() if p["asset"] == "GD46"]
        fila = [a for a in main._advisor_fixed_income_positions(self.conn, [self.uid])
                if a["asset"] == "GD46"][0]
        del_asesor = [(l["quantity"], l.get("nominal_original"), l.get("nominal_al_cargar"))
                      for l in fila["_lots"]]
        self.assertEqual(del_asesor, del_cliente)
        self.assertEqual(del_asesor, [(10000, 10000, None)])
        self.assertEqual(sorted(fila["_lots"][0]), ["entry_date", "nominal_original",
                                                    "nominal_por_barrido", "quantity"])

    def test_importar_una_venta_despues_no_devuelve_lo_amortizado(self):
        r = self._pago(broker="Balanz", asset="GD46", date="2026-07-09",
                       coupon_amount=0, amort_amount=227)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._nominal("GD46"), 9773, places=4)
        # Un archivo nuevo con una venta: el lote se rearma desde las compras y
        # ventas importadas. Antes quedaba en 9.000: se perdían los 227.
        self._importar("Balanz", "2026-08-03,VENTA,Balanz,GD46,1000,0.7,700,,,0,USD,")
        self.assertAlmostEqual(self._nominal("GD46"), 8773, places=4)
        # Y el cobro se sigue pudiendo borrar (apunta al lote nuevo).
        oid = r.json()["partes"][0]["operation_id"]
        self.assertEqual(self.client.delete(f"/api/movements/op-{oid}-cobro").status_code, 200)
        self.assertAlmostEqual(self._nominal("GD46"), 9000, places=4)


    def test_revertir_y_volver_a_importar_la_compra_no_devuelve_lo_amortizado(self):
        """Deshacer el import de la compra y subirlo de nuevo dejaba el lote otra
        vez en 10.000, con los 227 ya cobrados, y el cobro imposible de borrar."""
        compra = self.conn.execute(
            "SELECT id FROM import_batches WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
            (self.uid,)).fetchone()["id"]
        r = self._pago(broker="Balanz", asset="GD46", date="2026-07-09",
                       coupon_amount=0, amort_amount=227)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.post(f"/api/imports/{compra}/revert").status_code, 200)
        self.assertAlmostEqual(self._nominal("GD46"), 0, places=4)
        self._importar("Balanz",
                       "2025-03-01,DEPOSITO,Balanz,,,,20000,,,0,USD,",
                       "2025-03-03,COMPRA,Balanz,GD46,10000,0.6,6000,,,0,USD,")
        self.assertAlmostEqual(self._nominal("GD46"), 9773, places=4)
        # Y el cobro se puede borrar: devuelve el nominal al lote nuevo.
        oid = r.json()["partes"][0]["operation_id"]
        self.assertEqual(self.client.delete(f"/api/movements/op-{oid}-cobro").status_code, 200)
        self.assertAlmostEqual(self._nominal("GD46"), 10000, places=4)


class BonoEnLaCuentaEnPesosTest(_Base):
    """AL30 cargado A MANO en «Cocos» (pesos); paga en «Cocos · USD»."""

    def setUp(self):
        super().setUp()
        self._broker("Cocos", "ARS")
        self._broker("Cocos · USD", "USDT", parent="Cocos")
        # El dólar del día de la compra: el costo en dólares de un lote en pesos
        # sale de ahí, igual que en una venta (`fx.costo_en_moneda_de_venta`).
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date='2024-01-15'")
        self.conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                          "VALUES ('2024-01-15', 1000, 1000, 'manual')")
        # 9.200 nominales vivos (ya registró las amortizaciones anteriores),
        # pagados $ 5.520.000 al dólar de 1.000 → US$ 0,60 cada nominal.
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, tc_compra, entry_date, commissions, asset_type, currency)
               VALUES (?, 'Cocos', 'AL30', 0, 600, 9200, 5520000, 1000, '2024-01-15', 0, 'BOND', 'ARS')""",
            (self.uid,))
        self.conn.commit()

    def test_el_lote_a_mano_dice_con_cuanto_nacio_aunque_le_bajen_nominales(self):
        antes = [p for p in self.client.get("/api/positions").json() if p["asset"] == "AL30"]
        self.assertEqual([(p["nominal_por_barrido"], p["nominal_al_cargar"]) for p in antes],
                         [(False, 9200)])
        self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                   coupon_amount=27, amort_amount=800, cash_broker="Cocos · USD")
        despues = [p for p in self.client.get("/api/positions").json() if p["asset"] == "AL30"]
        self.assertEqual([(p["quantity"], p["nominal_al_cargar"]) for p in despues], [(8400, 9200)])

    def test_bono_en_las_dos_patas_la_amortizacion_alcanza_a_las_dos(self):
        """El mismo bono con un lote en «Cocos» y otro en «Cocos · USD»: la
        amortización les baja a los dos, no sólo a la pata que nombra el pedido."""
        self.conn.execute("UPDATE positions SET quantity=500, invested=300000 "
                          "WHERE user_id=? AND asset='AL30'", (self.uid,))
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, commissions, asset_type, currency)
               VALUES (?, 'Cocos · USD', 'AL30', 0, 0.6, 8700, 5220, '2024-03-01', 0, 'BOND', 'USD')""",
            (self.uid,))
        self.conn.commit()
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=0, amort_amount=800, cash_broker="Cocos · USD")
        self.assertEqual(r.status_code, 200, r.text)
        lotes = {p["broker"]: p["quantity"] for p in self.client.get("/api/positions").json()
                 if p["asset"] == "AL30"}
        # En proporción a lo que tiene cada uno (500 y 8.700 de 9.200): cada lámina
        # amortiza igual, estén en la pata que estén.
        self.assertAlmostEqual(lotes["Cocos"], 500 - 800 * 500 / 9200, places=4)
        self.assertAlmostEqual(lotes["Cocos · USD"], 8700 - 800 * 8700 / 9200, places=4)
        # Y borrar el cobro devuelve cada lote a SU cuenta.
        oid = r.json()["partes"][0]["operation_id"]
        self.assertEqual(self.client.delete(f"/api/movements/op-{oid}-cobro").status_code, 200)
        lotes = {p["broker"]: p["quantity"] for p in self.client.get("/api/positions").json()
                 if p["asset"] == "AL30"}
        self.assertEqual(lotes, {"Cocos": 500.0, "Cocos · USD": 8700.0})

    def test_cobra_en_dolares_y_baja_el_nominal_del_bono(self):
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800, cash_broker="Cocos · USD")
        self.assertEqual(r.status_code, 200, r.text)
        ops = {o["op_type"]: o for o in self._ops("AL30")}
        self.assertEqual({o["broker"] for o in ops.values()}, {"Cocos · USD"})
        self.assertAlmostEqual(self._efectivo("Cocos · USD"), 827, places=2)
        # Lote a mano: el cobro sí descuenta los 800 nominales amortizados.
        self.assertAlmostEqual(self._nominal("AL30"), 8400, places=4)
        # Costo en dólares con el TC de la compra: 800 × 600 / 1.000 = 480.
        self.assertAlmostEqual(ops["Amortización"]["cost_basis_consumed"], 480, places=2)
        self.assertAlmostEqual(ops["Amortización"]["pnl_usd"], 320, places=2)
        meta = json.loads(ops["Amortización"]["undo_meta_json"])
        self.assertEqual(meta["lot_broker"], "Cocos")

    def test_borrarlo_devuelve_el_nominal_a_la_cuenta_del_bono(self):
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800, cash_broker="Cocos · USD")
        for p in r.json()["partes"]:
            self.assertEqual(self.client.delete(
                f"/api/movements/op-{p['operation_id']}-cobro").status_code, 200)
        lotes = [p for p in self.client.get("/api/positions").json() if p["asset"] == "AL30"]
        self.assertEqual({p["broker"] for p in lotes}, {"Cocos"})
        self.assertAlmostEqual(sum(p["quantity"] for p in lotes), 9200, places=4)
        self.assertAlmostEqual(self._efectivo("Cocos · USD"), 0, places=2)

    def tearDown(self):
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date='2024-01-15'")
        self.conn.commit()
        super().tearDown()

    # ── Lo que encontró la auditoría del 2026-10-09 ──────────────────────────
    def test_amortizacion_en_pesos_sin_nominales_no_inventa_una_perdida(self):
        """El formulario viejo, para un bono en dólares de la cuenta en pesos, manda
        el monto en PESOS y ningún nominal. Tomar los pesos como nominal topeaba en
        la tenencia entera y anotaba TODO su costo como pérdida (−US$ 3.007 donde
        la ganancia real era +US$ 320). Sin nominal confiable no se toca el lote, y
        entonces tampoco se le resta su costo a la ganancia (el costo que se resta
        tiene que SALIR del lote, o la venta de después lo resta otra vez): el
        cobro es ganancia entera, como antes de 2026-10-09, y los nominales quedan
        como estaban. Con ganancia 0, como estuvo un día, la plata no cerraba."""
        r = self.client.post("/api/bonds/cashflow", json={
            "broker": "Cocos", "asset": "AL30", "flow_type": "amortization",
            "amount": 1160000, "date": "2026-07-09", "decrement_quantity": False,
            "fx_to_usd": 1450})
        self.assertEqual(r.status_code, 200, r.text)
        op = self._ops("AL30")[0]
        self.assertAlmostEqual(op["pnl_usd"], 1160000, places=2)
        self.assertIsNone(op["cost_basis_consumed"])
        self.assertAlmostEqual(op["quantity"], 1160000, places=2)
        self.assertAlmostEqual(self._ganancia_realizada(), 800, places=2)
        self.assertAlmostEqual(self._nominal("AL30"), 9200, places=4)

    def test_en_pesos_sin_nominales_tampoco_baja_la_tenencia(self):
        r = self.client.post("/api/bonds/cashflow", json={
            "broker": "Cocos", "asset": "AL30", "flow_type": "amortization",
            "amount": 5000, "date": "2026-07-09", "decrement_quantity": True,
            "fx_to_usd": 1450})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["cross_currency_skipped"])
        self.assertAlmostEqual(self._nominal("AL30"), 9200, places=4)

    def test_un_cobro_no_se_edita_se_borra_y_se_carga_de_nuevo(self):
        """Hasta 2026-10-10 esta prueba editaba el cobro (le cambiaba la cuenta) y
        medía que borrarlo devolviera la plata de donde entró. Editar un cobro
        cambiaba la ganancia del mes o la cuenta de la fila sin tocar el efectivo
        ni los nominales: ahora se rechaza con la explicación (igual que un
        dividendo de la bandeja). La nota sí se puede cambiar."""
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=27, amort_amount=800, cash_broker="Cocos · USD")
        am = [p for p in r.json()["partes"] if p["op_type"] == "Amortización"][0]
        o = [x for x in self._ops("AL30") if x["id"] == am["operation_id"]][0]
        body = {k: o[k] for k in ("date", "broker", "asset", "op_type", "entry_price",
                                  "exit_price", "quantity", "pnl_usd", "pnl_pct",
                                  "commissions", "currency", "fx_to_usd")}
        for cambio in ({"broker": "Cocos"}, {"pnl_usd": 500}, {"date": "2026-07-01"}):
            resp = self.client.put(f"/api/operations/{o['id']}", json={**body, **cambio})
            self.assertEqual(resp.status_code, 400, resp.text)
            self.assertIn("borralo en Movimientos", resp.text)
        self.assertEqual(self.client.put(f"/api/operations/{o['id']}",
                                         json={**body, "notes": "lo vi en el resumen"}).status_code, 200)
        despues = [x for x in self._ops("AL30") if x["id"] == o["id"]][0]
        self.assertEqual((despues["pnl_usd"], despues["quantity"], despues["broker"]),
                         (o["pnl_usd"], o["quantity"], o["broker"]))
        self.assertEqual(self.client.delete(
            f"/api/movements/op-{o['id']}-cobro").status_code, 200)
        # Los 800 salen de la cuenta en dólares (donde entraron); queda el cupón.
        self.assertAlmostEqual(self._efectivo("Cocos · USD"), 27, places=2)
        self.assertAlmostEqual(self._efectivo("Cocos"), 0, places=2)
        self.assertAlmostEqual(self._nominal("AL30"), 9200, places=4)

    def test_el_lote_que_se_amortizo_entero_vuelve_con_sus_datos(self):
        # El último pago del bono: se lleva los 9.200 que quedan y el lote se borra.
        # Al borrar ese cobro el lote tiene que volver igual: mismo id (las fotos de
        # otros cobros lo nombran por id), su fecha y su moneda.
        antes = [p for p in self.client.get("/api/positions").json() if p["asset"] == "AL30"][0]
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=0, amort_amount=9200, cash_broker="Cocos · USD")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._nominal("AL30"), 0, places=4)
        oid = r.json()["partes"][0]["operation_id"]
        self.assertEqual(self.client.delete(f"/api/movements/op-{oid}-cobro").status_code, 200)
        despues = [p for p in self.client.get("/api/positions").json() if p["asset"] == "AL30"]
        self.assertEqual([(p["id"], p["entry_date"], p["quantity"], p["currency"]) for p in despues],
                         [(antes["id"], "2024-01-15", 9200.0, "ARS")])

    def test_un_lote_comprado_despues_del_pago_no_lo_cobro(self):
        """Dos lotes; uno comprado DESPUÉS de la fecha del pago. La amortización de
        ese pago sólo le baja al que ya estaba."""
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, tc_compra, entry_date, commissions, asset_type, currency)
               VALUES (?, 'Cocos', 'AL30', 0, 600, 3000, 1800000, 1000, '2026-09-01', 0, 'BOND', 'ARS')""",
            (self.uid,))
        self.conn.commit()
        self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                   coupon_amount=0, amort_amount=800, cash_broker="Cocos · USD")
        lotes = {p["entry_date"]: p["quantity"] for p in self.client.get("/api/positions").json()
                 if p["asset"] == "AL30"}
        self.assertEqual(lotes, {"2024-01-15": 8400.0, "2026-09-01": 3000.0})

    def test_la_comision_mas_grande_que_el_cupon_sale_de_la_amortizacion(self):
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=5, amort_amount=800, commissions=6,
                       cash_broker="Cocos · USD")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._efectivo("Cocos · USD"), 799, places=2)

    def test_otra_cuenta_que_no_es_del_broker_se_rechaza(self):
        self._broker("IOL", "USDT")
        r = self._pago(broker="Cocos", asset="AL30", date="2026-07-09",
                       coupon_amount=27, amort_amount=0, cash_broker="IOL")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self._ops("AL30"), [])


class LoQueEncontroLaAuditoria4Test(_Base):
    """Auditoría del 2026-10-10. Bono cargado A MANO por la app (depósito + alta
    de la posición) en una cuenta en dólares: 10.000 nominales de GD46 a 0,60."""

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

    def _lote(self):
        return [p for p in self.client.get("/api/positions").json() if p["asset"] == "GD46"]

    def _vender_todo(self, precio):
        self._ok(self.client.post("/api/positions/sell", json={
            "broker": "IOL", "asset": "GD46", "quantity": self._nominal("GD46"),
            "exit_price": precio, "date": "2026-08-03"}))

    # ── la regla: el costo que se resta de la ganancia sale del lote ──────────
    def test_sin_bajar_nominales_la_plata_cierra(self):
        """Amortización de 227 por el formulario con "descontar nominales" apagado,
        y después se vende todo a 0,70. Plata real: 227 + 7.000 − 6.000 = 1.227.
        Rendi anotaba 1.090,8: le restaba al cobro un costo que quedaba en el lote,
        y la venta lo volvía a restar."""
        self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "amortization",
            "amount": 227, "date": "2026-07-09", "decrement_quantity": False}))
        self.assertAlmostEqual(self._nominal("GD46"), 10000, places=4)
        self._vender_todo(0.70)
        self.assertAlmostEqual(self._ganancia_realizada(), 1227, places=2)

    def test_bajando_nominales_tambien_cierra(self):
        self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                            coupon_amount=0, amort_amount=227))
        self.assertAlmostEqual(self._nominal("GD46"), 9773, places=4)
        self._vender_todo(0.70)
        # 227 + 9.773 × 0,70 − 6.000
        self.assertAlmostEqual(self._ganancia_realizada(), 227 + 6841.1 - 6000, places=2)

    def test_el_costo_de_una_amortizacion_grande(self):
        """El costo sale de lo que el lote tenía ANTES de bajarlo. Calculado después
        (un error de la tarde del 2026-10-10), amortizar 6.000 de 10.000 anotaba
        el costo de los 4.000 que quedaban, y el último pago del bono —que se
        lleva el lote— anotaba todo lo cobrado como ganancia. Las pruebas de
        entonces amortizaban siempre poco y no lo veían."""
        for nominales, costo, ganancia in ((227, 136.2, 90.8), (4000, 2400, 1600),
                                           (6000, 3600, 2400), (10000, 6000, 4000)):
            with self.subTest(nominales=nominales):
                r = self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                                        coupon_amount=0, amort_amount=nominales,
                                        face_amortized=nominales))
                parte = r.json()["partes"][0]
                self.assertAlmostEqual(parte["cost_basis_consumed"], costo, places=2)
                op = [o for o in self._ops("GD46") if o["id"] == parte["operation_id"]][0]
                self.assertAlmostEqual(op["pnl_usd"], ganancia, places=2)
                self.assertAlmostEqual(self._nominal("GD46"), 10000 - nominales, places=4)
                self.assertAlmostEqual(self._ganancia_realizada(), ganancia, places=2)
                self._ok(self.client.delete(f"/api/movements/op-{parte['operation_id']}-cobro"))
                self.assertEqual([(p["quantity"], p["invested"]) for p in self._lote()],
                                 [(10000, 6000)])

    def test_el_ultimo_pago_y_despues_no_queda_nada_la_plata_cierra(self):
        """El bono devuelve todo: 10.000 cobrados sobre 6.000 de costo = 4.000."""
        self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                            coupon_amount=50, amort_amount=10000, face_amortized=10000))
        self.assertEqual(self._lote(), [])
        self.assertAlmostEqual(self._ganancia_realizada(), 4050, places=2)
        self.assertAlmostEqual(self._efectivo("IOL"), 10050, places=2)

    def test_amortizar_mas_de_la_mitad_y_vender_el_resto_la_plata_cierra(self):
        self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                            coupon_amount=0, amort_amount=6000, face_amortized=6000))
        self._vender_todo(0.70)          # quedan 4.000 → 2.800
        # Plata real: 6.000 + 2.800 − 6.000 de costo.
        self.assertAlmostEqual(self._ganancia_realizada(), 2800, places=2)

    def test_un_nominal_mayor_a_lo_que_hay_no_se_lleva_el_lote(self):
        """Pedir bajar 12.000 nominales con 10.000 en cartera se llevaba el lote
        ENTERO y anotaba su costo completo como pérdida (un cobro de 100: −5.900).
        No se baja nada, se avisa, y el cobro es ganancia entera."""
        r = self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "amortization",
            "amount": 100, "date": "2026-07-09", "decrement_quantity": True,
            "face_amortized": 12000}))
        self.assertTrue(r.json()["cross_currency_skipped"])
        self.assertAlmostEqual(self._nominal("GD46"), 10000, places=4)
        self.assertAlmostEqual(self._ganancia_realizada(), 100, places=2)

    def test_la_comision_no_cambia_cuantos_nominales_volvieron(self):
        self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "amortization",
            "amount": 227, "commissions": 20, "date": "2026-07-09",
            "decrement_quantity": True}))
        self.assertAlmostEqual(self._nominal("GD46"), 9773, places=4)   # no 9.793
        self.assertAlmostEqual(self._efectivo("IOL"), 207, places=2)

    # ── deshacer deja todo como estaba ───────────────────────────────────────
    def test_el_lote_amortizado_entero_vuelve_con_todo_lo_suyo(self):
        """Volvía sin precio manual, sin nota y sin la receta para borrarlo."""
        lote = self._lote()[0]
        self.conn.execute("UPDATE positions SET price_override=0.97, notes='mi bono' WHERE id=?",
                          (lote["id"],))
        self.conn.commit()
        fila = dict(self.conn.execute("SELECT * FROM positions WHERE id=?", (lote["id"],)).fetchone())
        r = self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                                coupon_amount=0, amort_amount=10000))
        self.assertEqual(self._lote(), [])
        oid = r.json()["partes"][0]["operation_id"]
        self._ok(self.client.delete(f"/api/movements/op-{oid}-cobro"))
        vuelta = dict(self.conn.execute("SELECT * FROM positions WHERE id=?", (lote["id"],)).fetchone())
        self.assertEqual(vuelta, fila)
        # Y se puede borrar desde Cartera, como cualquier lote cargado a mano.
        self._ok(self.client.delete(f"/api/positions/{lote['id']}"))

    def test_vender_todo_borrar_la_venta_y_borrar_la_amortizacion(self):
        """El lote renacía con otro número y la amortización quedaba imborrable
        ("ya no queda nominal"); la bandeja creía que había nacido con 9.773."""
        r = self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                                coupon_amount=0, amort_amount=227))
        self._vender_todo(0.70)
        venta = [o for o in self._ops("GD46") if o["op_type"] != "Amortización"][0]
        self._ok(self.client.delete(f"/api/operations/{venta['id']}"))
        self.assertEqual([(p["quantity"], p["nominal_al_cargar"]) for p in self._lote()],
                         [(9773, 10000)])
        oid = r.json()["partes"][0]["operation_id"]
        self._ok(self.client.delete(f"/api/movements/op-{oid}-cobro"))
        self.assertEqual([(p["quantity"], p["invested"]) for p in self._lote()], [(10000, 6000)])
        self.assertAlmostEqual(self._efectivo("IOL"), 0, places=2)

    def test_renombrar_la_cuenta_y_borrar_el_cobro(self):
        """El cobro guarda en qué cuenta entró la plata y en cuál viven los lotes.
        Renombrar sin tocar eso dejaba la plata en la cuenta real y un saldo
        negativo en una cuenta que ya no existía."""
        r = self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                                coupon_amount=20, amort_amount=10000))   # se lleva el lote
        b = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name='IOL'",
                              (self.uid,)).fetchone()
        self._ok(self.client.put(f"/api/brokers/{b['id']}", json={"name": "IOL Inversiones", "currency": "USDT"}))
        # Un impostor con el nombre viejo: si el borrado mira el nombre viejo, sale de acá.
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "IOL", "USDT"))
        self.conn.commit()
        for pt in r.json()["partes"]:
            self._ok(self.client.delete(f"/api/movements/op-{pt['operation_id']}-cobro"))
        self.assertAlmostEqual(self._efectivo("IOL Inversiones"), 0, places=2)
        self.assertAlmostEqual(self._efectivo("IOL"), 0, places=2)
        self.assertEqual([(p["broker"], p["quantity"]) for p in self._lote()],
                         [("IOL Inversiones", 10000)])

    # ── el importador ────────────────────────────────────────────────────────
    def _importar_y_leer(self, *rows):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(*rows)), "text/csv"))],
            data={"format": "rendi_generic", "broker": "IOL"})
        self._ok(r)
        return self._ok(self.client.post("/api/imports/confirm",
                                         json={"session_id": r.json()["session_id"]})).json()

    def test_el_archivo_trae_el_cupon_con_otro_monto_manda_el_broker(self):
        """A mano 75; el archivo dice 50. Quedaban los dos (+125). Ahora el del
        broker reemplaza al de a mano — y revertir ese import lo trae de vuelta."""
        self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "coupon",
            "amount": 75, "date": "2026-07-09"}))
        batch = self._importar_y_leer("2026-07-10,RENTA,IOL,GD46,,,50,,,0,USD,")["batch_id"]
        self.assertEqual([o["op_type"] for o in self._ops("GD46")], ["Dividendo"])
        self.assertAlmostEqual(self._efectivo("IOL"), 50, places=2)
        self._ok(self.client.post(f"/api/imports/{batch}/revert"))
        self.assertEqual([o["op_type"] for o in self._ops("GD46")], ["Cupón"])
        self.assertAlmostEqual(self._efectivo("IOL"), 75, places=2)
        self.assertAlmostEqual(self._ganancia_realizada(), 75, places=2)

    def test_cupon_y_amortizacion_anotados_y_el_archivo_trae_otro_monto(self):
        """Están las dos partes anotadas (y la amortización ya bajó nominales): el
        renglón del archivo no puede ser "otra parte". Se saltea aunque el monto
        difiera más de 25 %. Entraba además: efectivo +577."""
        self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                            coupon_amount=20, amort_amount=227))
        res = self._importar_y_leer("2026-07-10,RENTA Y AMORTIZACION,IOL,GD46,,,330,,,0,USD,")
        self.assertIn("ya lo anotaste", json.dumps(res, ensure_ascii=False))
        self.assertAlmostEqual(self._efectivo("IOL"), 247, places=2)

    def test_el_archivo_trae_solo_la_amortizacion_y_el_cupon_a_mano_se_queda(self):
        """Borraba el cupón de 20 (creía que el renglón lo traía adentro). Cuando
        el archivo DICE que el renglón es una amortización (la descripción llega
        en la nota, como en Balanz e IEB), es la otra parte del pago: entra, y el
        cupón a mano se queda."""
        self._ok(self.client.post("/api/bonds/cashflow", json={
            "broker": "IOL", "asset": "GD46", "flow_type": "coupon",
            "amount": 20, "date": "2026-07-09"}))
        self._importar_y_leer("2026-07-10,AMORTIZACION,IOL,GD46,,,227,,,0,USD,Amortizacion")
        self.assertEqual(sorted(o["op_type"] for o in self._ops("GD46")), ["Amortización", "Cupón"])
        self.assertAlmostEqual(self._efectivo("IOL"), 247, places=2)

    def test_la_amortizacion_que_el_archivo_trae_como_venta(self):
        """Balanz anota "Renta y Amortización" con cantidad como una VENTA de esos
        nominales. Es el mismo pago: ya confirmado, el renglón se saltea."""
        self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                            coupon_amount=20, amort_amount=227))
        res = self._importar_y_leer(
            "2026-07-10,VENTA,IOL,GD46,227,1.088,247,,,0,USD,Renta y Amortizacion")
        self.assertIn("ya lo anotaste", json.dumps(res, ensure_ascii=False))
        self.assertAlmostEqual(self._efectivo("IOL"), 247, places=2)
        self.assertAlmostEqual(self._nominal("GD46"), 9773, places=4)

    def test_la_venta_amortizacion_ya_importada_frena_a_la_bandeja(self):
        self._importar_y_leer(
            "2026-07-10,VENTA,IOL,GD46,227,1.088,247,,,0,USD,Renta y Amortizacion")
        ops = [o for o in self.client.get("/api/operations").json() if o["asset"] == "GD46"]
        self.assertEqual([o["amortizacion_importada"] for o in ops], [True])
        r = self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                       coupon_amount=20, amort_amount=227)
        self.assertEqual(r.status_code, 409, r.text)

    def test_una_venta_comun_no_es_un_cobro(self):
        self._importar_y_leer("2026-07-10,VENTA,IOL,GD46,227,0.7,158.9,,,0,USD,")
        ops = [o for o in self.client.get("/api/operations").json() if o["asset"] == "GD46"]
        self.assertEqual([o["amortizacion_importada"] for o in ops], [False])
        self._ok(self._pago(broker="IOL", asset="GD46", date="2026-07-09",
                            coupon_amount=20, amort_amount=0))


if __name__ == "__main__":
    unittest.main()
