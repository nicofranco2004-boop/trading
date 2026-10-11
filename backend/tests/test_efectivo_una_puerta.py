"""El efectivo de un broker se mueve por UNA sola puerta (efectivo.mover).

Hasta 2026-10-07 había cinco copias de "sumarle algo al saldo", cada una con su
regla. Estas pruebas fijan las diferencias que había entre ellas y que ahora son
una sola regla, cada una por el endpoint que la usa:

  · El nombre de la caja sale de la moneda del broker, también en el importador
    (que creaba 'USDT' para un broker en dólares: el efectivo de un Schwab
    importado se mostraba como Tether).
  · Un cobro entra aunque el saldo esté en rojo (la copia de las conversiones lo
    rechazaba con "Saldo insuficiente" al acreditar un cupón).
  · Un retiro o una conversión que no alcanza rebota sin tocar nada.
  · El TC promedio de los dólares pesa sólo los dólares que había de verdad.
  · Ese precio es de los dólares que HAY: lo escribe sólo la puerta, una caja
    vacía no lo tiene, y lo que un archivo vende de más no lo lleva.
"""
import ast
import io
import os
import unittest
import uuid

import efectivo
import main
from fastapi.testclient import TestClient


class _Base(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)

    def usuario(self, brokers):
        """brokers: [(nombre, moneda, saldo o None = sin caja)]."""
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"puerta-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        for nombre, ccy, saldo in brokers:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, nombre, ccy))
            if saldo is not None:
                conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                             "VALUES (?,?,?,1,?)",
                             (self.uid, nombre, 'ARS' if ccy == 'ARS' else 'USD', saldo))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def cajas(self, broker):
        conn = main.get_db()
        filas = conn.execute(
            "SELECT asset, invested, tc_compra FROM positions WHERE user_id=? AND broker=? "
            "AND is_cash=1 ORDER BY id", (self.uid, broker)).fetchall()
        conn.close()
        return [dict(f) for f in filas]

    def saldo(self, broker):
        return sum(float(c["invested"] or 0) for c in self.cajas(broker))


# ═════════════════════════════════════════════════════════════════════════════
class ElNombreDeLaCaja(_Base):

    def test_importar_un_deposito_a_un_broker_en_dolares_crea_la_caja_USD(self):
        """El importador tenía su propia copia y creaba 'USDT' para todo lo que no
        fuera pesos. En la base de producción del 2026-08-16, 35 de las 81 cajas de
        brokers en dólares eran 'USDT', y las 35 las había creado el importador."""
        self.usuario([("Schwab", "USD", None)])
        csv = (b"fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
               b"2025-11-14,DEPOSITO,Schwab,,,,1000,,,,USD,\n")
        p = self.client.post("/api/imports/preview", headers=self.h,
                             files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                             data={"format": "rendi_generic", "broker": "Schwab"})
        self.assertEqual(p.status_code, 200, p.text)
        r = self.client.post("/api/imports/confirm", headers=self.h, json={
            "session_id": p.json()["session_id"], "skip_row_indices": [], "aprobar_tickers": []})
        self.assertEqual(r.status_code, 200, r.text)
        cajas = self.cajas("Schwab")
        self.assertEqual(len(cajas), 1, cajas)
        self.assertEqual(cajas[0]["asset"], "USD",
                         "el importador creó la caja de un broker en dólares como Tether")
        self.assertAlmostEqual(float(cajas[0]["invested"]), 1000, places=2)

    def test_conciliar_un_broker_en_dolares_sin_caja_la_crea_USD(self):
        self.usuario([("Schwab", "USD", None)])
        r = self.client.post("/api/brokers/reconcile-cash", headers=self.h,
                             json={"broker_name": "Schwab", "target_cash": 750})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([(c["asset"], round(float(c["invested"]), 2)) for c in self.cajas("Schwab")],
                         [("USD", 750.0)])

    def test_un_exchange_sigue_teniendo_caja_USDT(self):
        self.usuario([("Binance", "USDT", None)])
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Binance", "direction": "deposit", "amount": 300})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([c["asset"] for c in self.cajas("Binance")], ["USDT"])


# ═════════════════════════════════════════════════════════════════════════════
class CobrosConElSaldoEnRojo(_Base):

    def test_un_cupon_se_cobra_aunque_el_saldo_este_en_rojo(self):
        """Antes iba por la copia estricta de las conversiones, que chequeaba
        "¿queda negativo?" también al ACREDITAR: −500 + 100 = −400 → 400."""
        self.usuario([("Schwab", "USD", -500.0)])
        r = self.client.post("/api/bonds/cashflow", headers=self.h, json={
            "broker": "Schwab", "asset": "AL30", "flow_type": "coupon",
            "amount": 100, "date": main._iso_today()})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self.saldo("Schwab"), -400, places=2)

    def test_un_deposito_achica_el_descubierto(self):
        self.usuario([("Schwab", "USD", -500.0)])
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Schwab", "direction": "deposit", "amount": 200})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self.saldo("Schwab"), -300, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class LoQueNoAlcanzaRebota(_Base):

    def test_un_retiro_mayor_al_saldo_rebota_sin_tocar_nada(self):
        self.usuario([("Schwab", "USD", 100.0)])
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Schwab", "direction": "withdraw", "amount": 150})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Saldo insuficiente", r.text)
        self.assertAlmostEqual(self.saldo("Schwab"), 100, places=2)

    def test_un_retiro_sin_caja_rebota_y_no_crea_una_caja_en_rojo(self):
        self.usuario([("Schwab", "USD", None)])
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Schwab", "direction": "withdraw", "amount": 50})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.cajas("Schwab"), [])

    def test_retirar_todo_el_saldo_lo_deja_en_cero(self):
        self.usuario([("Schwab", "USD", 0.3)])
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Schwab", "direction": "withdraw", "amount": 0.1 + 0.2})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.saldo("Schwab"), 0)

    def test_comprar_dolares_sin_pesos_suficientes_rebota_sin_tocar_nada(self):
        self.usuario([("Balanz", "ARS", 50_000.0)])
        r = self.client.post("/api/conversions", headers=self.h, json={
            "from_broker": "Balanz", "direction": "ars_to_usd",
            "ars_amount": 100_000, "usd_amount": 100, "tc": 1000})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Saldo insuficiente", r.text)
        self.assertAlmostEqual(self.saldo("Balanz"), 50_000, places=2)
        conn = main.get_db()
        ops = conn.execute("SELECT COUNT(*) n FROM operations WHERE user_id=?",
                           (self.uid,)).fetchone()["n"]
        conn.close()
        self.assertEqual(ops, 0, "la conversión rechazada dejó una operación anotada")


# ═════════════════════════════════════════════════════════════════════════════
class ElTipoDeCambioDeLosDolares(_Base):

    def _comprar(self, ars, usd, tc):
        r = self.client.post("/api/conversions", headers=self.h, json={
            "from_broker": "Balanz", "direction": "ars_to_usd",
            "ars_amount": ars, "usd_amount": usd, "tc": tc})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["to_broker"]

    def test_dos_compras_promedian_y_la_venta_gana_contra_el_promedio(self):
        self.usuario([("Balanz", "ARS", 1_000_000.0)])
        self._comprar(100_000, 100, 1000)
        sub = self._comprar(200_000, 100, 2000)
        caja = self.cajas(sub)[0]
        self.assertAlmostEqual(float(caja["invested"]), 200, places=4)
        self.assertAlmostEqual(float(caja["tc_compra"]), 1500, places=4)
        r = self.client.post("/api/conversions", headers=self.h, json={
            "from_broker": sub, "direction": "usd_to_ars",
            "ars_amount": 200_000, "usd_amount": 100, "tc": 2000})
        self.assertEqual(r.status_code, 200, r.text)
        # 100 USD que costaron 150.000 ARS (promedio 1500) vendidos por 200.000:
        # 50.000 ARS de ganancia = US$ 25 al TC de la venta.
        self.assertAlmostEqual(r.json()["pnl_usd_realized"], 25, places=2)
        self.assertAlmostEqual(float(self.cajas(sub)[0]["tc_compra"]), 1500, places=4,
                               msg="vender no cambia el costo de los dólares que quedan")

    def test_con_el_saldo_en_dolares_en_rojo_vale_el_tc_de_la_compra(self):
        """Un saldo en rojo no tiene dólares que pesar. Antes el promedio los pesaba
        igual: −100 a 500 y +200 a 1000 daba (−50.000 + 200.000) / 100 = 1500,
        un costo más alto que lo que se pagó por cualquiera de los dólares."""
        self.usuario([("Balanz", "ARS", 1_000_000.0)])
        sub = self._comprar(100_000, 100, 1000)
        conn = main.get_db()
        conn.execute("UPDATE positions SET invested=-100, tc_compra=500 WHERE user_id=? "
                     "AND broker=? AND is_cash=1", (self.uid, sub))
        conn.commit()
        conn.close()
        self._comprar(200_000, 200, 1000)
        caja = self.cajas(sub)[0]
        self.assertAlmostEqual(float(caja["invested"]), 100, places=4)
        self.assertAlmostEqual(float(caja["tc_compra"]), 1000, places=4)


# ═════════════════════════════════════════════════════════════════════════════
class ElTipoDeCambioDeLosDolaresImportados(_Base):
    """Lo mismo que la clase de arriba, pero cuando las conversiones llegan en un
    ARCHIVO: el importador pasa por la misma puerta (`tc_compra=`), y hasta la
    auditoría del 2026-10-07 ninguna prueba lo miraba — se podía sacar el promedio
    del importador entero y la suite seguía en verde. Por el camino real: subir el
    archivo y confirmarlo, que corre el persister y después el recálculo."""

    HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
           "comisiones,moneda,notas\n")
    SUB = "Balanz · USD"

    def _importar(self, filas):
        csv = (self.HDR + filas).encode()
        p = self.client.post("/api/imports/preview", headers=self.h,
                             files=[("files", ("fx.csv", io.BytesIO(csv), "text/csv"))],
                             data={"format": "rendi_generic", "broker": "Balanz"})
        self.assertEqual(p.status_code, 200, p.text)
        r = self.client.post("/api/imports/confirm", headers=self.h, json={
            "session_id": p.json()["session_id"], "skip_row_indices": [], "aprobar_tickers": []})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("skipped_rows"), [], r.text)

    def _venta_importada(self):
        conn = main.get_db()
        fila = conn.execute(
            "SELECT entry_price, pnl_usd FROM operations WHERE user_id=? AND "
            "op_type LIKE 'CONVERSION IMPORT %USDT→ARS'", (self.uid,)).fetchone()
        conn.close()
        self.assertIsNotNone(fila, "no se anotó la venta de dólares del archivo")
        return fila

    def test_dos_compras_promedian_y_la_venta_gana_contra_el_promedio(self):
        self.usuario([("Balanz", "ARS", None)])
        self._importar(
            "2026-01-05,DEPOSITO,Balanz,,,,1000000,,,,ARS,\n"
            "2026-01-06,CONVERSION_ARS_USD,Balanz,,,,100000,100,1000,,,MEP\n"
            "2026-02-06,CONVERSION_ARS_USD,Balanz,,,,200000,100,2000,,,MEP\n")
        caja = self.cajas(self.SUB)
        self.assertEqual(len(caja), 1, caja)
        self.assertAlmostEqual(float(caja[0]["invested"]), 200, places=4)
        self.assertAlmostEqual(float(caja[0]["tc_compra"]), 1500, places=4,
                               msg="el importador no promedió el TC de los dólares comprados")

        # Un segundo archivo vende 100 USD a 2000: costaron 150.000 (promedio
        # 1500) y se cobran 200.000 → 50.000 ARS de ganancia = US$ 25.
        self._importar(
            "2026-03-06,CONVERSION_USD_ARS,Balanz · USD,,,,200000,100,2000,,,MEP\n")
        venta = self._venta_importada()
        self.assertAlmostEqual(float(venta["entry_price"]), 1500, places=4)
        self.assertAlmostEqual(float(venta["pnl_usd"]), 25, places=2)
        caja = self.cajas(self.SUB)[0]
        self.assertAlmostEqual(float(caja["invested"]), 100, places=4)
        self.assertAlmostEqual(float(caja["tc_compra"]), 1500, places=4,
                               msg="vender no cambia el costo de los dólares que quedan")

    def test_con_el_saldo_en_dolares_en_rojo_vale_el_tc_de_la_compra(self):
        """Un archivo puede dejar la subcuenta en dólares en rojo (le faltan
        compras viejas). El promedio viejo del importador pesaba ese rojo como si
        fueran dólares: −100 a 500 y +200 a 1000 daba (−50.000 + 200.000) / 100 =
        1500, más caro que cualquier dólar que se pagó."""
        self.usuario([("Balanz", "ARS", None)])
        self._importar(
            "2026-01-05,DEPOSITO,Balanz,,,,1000000,,,,ARS,\n"
            "2026-01-06,CONVERSION_ARS_USD,Balanz,,,,50000,100,500,,,MEP\n"
            "2026-01-07,CONVERSION_USD_ARS,Balanz · USD,,,,100000,200,500,,,MEP\n"
            "2026-02-06,CONVERSION_ARS_USD,Balanz,,,,200000,200,1000,,,MEP\n")
        caja = self.cajas(self.SUB)[0]
        self.assertAlmostEqual(float(caja["invested"]), 100, places=4)
        self.assertAlmostEqual(float(caja["tc_compra"]), 1000, places=4)


    def _ventas_importadas(self):
        conn = main.get_db()
        filas = [dict(f) for f in conn.execute(
            "SELECT date, quantity, entry_price, exit_price, pnl_usd FROM operations "
            "WHERE user_id=? AND op_type LIKE 'CONVERSION IMPORT %USDT→ARS' ORDER BY date, id",
            (self.uid,))]
        realizado = conn.execute(
            "SELECT COALESCE(SUM(pnl_realized), 0) s FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["s"]
        conn.close()
        return filas, round(float(realizado or 0), 2)

    def test_un_dividendo_despues_de_vaciar_la_caja_no_hereda_el_precio_viejo(self):
        """Casi todas las compras y ventas de dólares de producción llegan por
        archivo (base del 2026-08-16: 306 compras importadas contra 2 a mano). Se
        compran 100 dólares a 400 y se venden; meses después entra un dividendo de
        US$ 10 y se vende a 1.300: antes anotaba US$ 6,92 de ganancia cambiaria,
        contra la compra vieja. Mirado DESPUÉS del recálculo del confirm, que es
        lo que queda en la cuenta."""
        self.usuario([("Balanz", "ARS", None)])
        self._importar(
            "2026-01-05,DEPOSITO,Balanz,,,,1000000,,,,ARS,\n"
            "2026-01-06,CONVERSION_ARS_USD,Balanz,,,,40000,100,400,,,MEP\n"
            "2026-01-07,CONVERSION_USD_ARS,Balanz · USD,,,,40000,100,400,,,MEP\n"
            "2026-02-10,DIVIDENDO,Balanz · USD,AAPL,,,10,,,,USD,\n"
            "2026-02-11,CONVERSION_USD_ARS,Balanz · USD,,,,13000,10,1300,,,MEP\n")
        ventas, realizado = self._ventas_importadas()
        self.assertEqual([(v["quantity"], v["entry_price"], v["pnl_usd"]) for v in ventas],
                         [(100.0, 400.0, 0.0), (10.0, 1300.0, 0.0)])
        self.assertEqual(realizado, 10.0, "el resultado es el dividendo y nada más")
        caja = self.cajas(self.SUB)[0]
        self.assertAlmostEqual(float(caja["invested"]), 0, places=4)
        self.assertIsNone(caja["tc_compra"])

    def test_lo_que_el_archivo_vende_de_mas_no_lleva_precio(self):
        """Un archivo puede vender más dólares de los que hay (le faltan compras
        viejas). Con 30 a 400 en la caja y una venta de 100 a 1.300, los 100 salían
        a 400: US$ 69,23. Lo que se sabe son los 30: 30 × 900 / 1.300 = US$ 20,77."""
        self.usuario([("Balanz", "ARS", None)])
        self._importar(
            "2026-01-05,DEPOSITO,Balanz,,,,1000000,,,,ARS,\n"
            "2026-01-06,CONVERSION_ARS_USD,Balanz,,,,12000,30,400,,,MEP\n"
            "2026-02-11,CONVERSION_USD_ARS,Balanz · USD,,,,130000,100,1300,,,MEP\n")
        ventas, realizado = self._ventas_importadas()
        self.assertEqual([v["pnl_usd"] for v in ventas], [20.77])
        self.assertEqual(realizado, 20.77)
        caja = self.cajas(self.SUB)[0]
        self.assertAlmostEqual(float(caja["invested"]), -70, places=4)
        self.assertIsNone(caja["tc_compra"], "una caja en rojo no tiene dólares: no tiene precio")
        # Y los dólares que entren después no heredan el de los 30.
        self._importar(
            "2026-03-10,DIVIDENDO,Balanz · USD,AAPL,,,100,,,,USD,\n"
            "2026-03-11,CONVERSION_USD_ARS,Balanz · USD,,,,42000,30,1400,,,MEP\n")
        ventas, realizado = self._ventas_importadas()
        self.assertEqual([v["pnl_usd"] for v in ventas], [20.77, 0.0])
        self.assertEqual(realizado, 120.77)

    def test_con_la_caja_en_rojo_la_venta_no_usa_el_precio_que_haya_quedado(self):
        """La cuenta de la ganancia tampoco lee el precio de una caja sin dólares,
        aunque esté guardado (así estaban las de antes del arreglo, hasta que el
        arranque las limpia): con la caja en −20 y un 400 viejo, vender 10 a 1.300
        no gana ni pierde, y esos 10 salen al precio de la venta."""
        self.usuario([("Balanz", "ARS", None)])
        self._importar(
            "2026-01-05,DEPOSITO,Balanz,,,,1000000,,,,ARS,\n"
            "2026-01-06,CONVERSION_ARS_USD,Balanz,,,,12000,30,400,,,MEP\n"
            "2026-01-07,CONVERSION_USD_ARS,Balanz · USD,,,,20000,50,400,,,MEP\n")
        conn = main.get_db()
        conn.execute("UPDATE positions SET tc_compra=400 WHERE user_id=? AND broker=? AND is_cash=1",
                     (self.uid, self.SUB))
        conn.commit()
        conn.close()
        self.assertEqual([(c["invested"], c["tc_compra"]) for c in self.cajas(self.SUB)],
                         [(-20.0, 400.0)])
        self._importar(
            "2026-02-11,CONVERSION_USD_ARS,Balanz · USD,,,,13000,10,1300,,,MEP\n")
        ventas, _ = self._ventas_importadas()
        self.assertEqual([(v["entry_price"], v["pnl_usd"]) for v in ventas][-1], (1300.0, 0.0))
        self.assertEqual([(c["invested"], c["tc_compra"]) for c in self.cajas(self.SUB)],
                         [(-30.0, None)])


# ═════════════════════════════════════════════════════════════════════════════
class ElEfectivoNoEsUnaPosicion(_Base):
    """El saldo no se cambia por las rutas de las posiciones comunes. "Editar
    posición" sobre la fila de efectivo escribía el número sin anotar el aporte:
    de 1.000 a 5.000 aparecía como 4.000 de ganancia que no existe (verificado en
    una base de prueba el 2026-10-07). Y "Eliminar" nunca funcionó: respondía un
    error que no correspondía."""

    def _caja_id(self, broker):
        conn = main.get_db()
        r = conn.execute("SELECT id FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                         (self.uid, broker)).fetchone()
        conn.close()
        return r["id"]

    def _aportado(self):
        conn = main.get_db()
        r = conn.execute("SELECT COALESCE(SUM(deposits),0) - COALESCE(SUM(withdrawals),0) a "
                         "FROM monthly_entries WHERE user_id=? AND broker='global'",
                         (self.uid,)).fetchone()
        conn.close()
        return float(r["a"] or 0)

    def test_editar_el_saldo_como_posicion_rebota_y_no_toca_nada(self):
        self.usuario([("Schwab", "USD", None)])
        self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Schwab", "direction": "deposit", "amount": 1000})
        pid = self._caja_id("Schwab")
        r = self.client.put(f"/api/positions/{pid}", headers=self.h, json={
            "broker": "Schwab", "asset": "USD", "is_cash": True, "invested": 5000})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Depositar o Retirar", r.text)
        self.assertAlmostEqual(self.saldo("Schwab"), 1000, places=2)
        self.assertAlmostEqual(self._aportado(), 1000, places=2)

    def test_editar_ni_siquiera_con_el_tilde_de_efectivo_apagado(self):
        """El que manda es lo que la fila ES en la base, no lo que dice el pedido."""
        self.usuario([("Schwab", "USD", 1000.0)])
        r = self.client.put(f"/api/positions/{self._caja_id('Schwab')}", headers=self.h,
                            json={"broker": "Schwab", "asset": "USD", "is_cash": False,
                                  "invested": 5000, "quantity": 1, "buy_price": 5000})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertAlmostEqual(self.saldo("Schwab"), 1000, places=2)

    def test_un_lote_no_se_convierte_en_efectivo(self):
        self.usuario([("Schwab", "USD", 0.0)])
        conn = main.get_db()
        pid = conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, quantity,
                                buy_price, invested) VALUES (?, 'Schwab', 'AAPL', 0, 10, 100, 1000)""",
                           (self.uid,)).lastrowid
        conn.commit()
        conn.close()
        r = self.client.put(f"/api/positions/{pid}", headers=self.h, json={
            "broker": "Schwab", "asset": "AAPL", "is_cash": True, "invested": 1000})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(len(self.cajas("Schwab")), 1, "el lote pasó a ser una segunda caja")

    def test_cargar_una_caja_como_posicion_rebota(self):
        self.usuario([("Schwab", "USD", None)])
        r = self.client.post("/api/positions", headers=self.h, json={
            "broker": "Schwab", "asset": "USD", "is_cash": True, "invested": 500})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.cajas("Schwab"), [])
        self.assertAlmostEqual(self._aportado(), 0, places=2)

    def test_borrar_la_caja_rebota_con_un_mensaje_que_dice_que_hacer(self):
        self.usuario([("Schwab", "USD", 1000.0)])
        r = self.client.delete(f"/api/positions/{self._caja_id('Schwab')}", headers=self.h)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Retirar", r.text)
        self.assertAlmostEqual(self.saldo("Schwab"), 1000, places=2)

    def test_editar_y_borrar_una_tenencia_sigue_funcionando(self):
        """El rechazo es sólo para el efectivo."""
        self.usuario([("Schwab", "USD", 10_000.0)])
        r = self.client.post("/api/positions", headers=self.h, json={
            "broker": "Schwab", "asset": "AAPL", "quantity": 10, "buy_price": 100,
            "invested": 1000, "entry_date": "2026-01-15"})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["id"]
        r = self.client.put(f"/api/positions/{pid}", headers=self.h, json={
            "broker": "Schwab", "asset": "AAPL", "quantity": 10, "buy_price": 100,
            "invested": 1000, "notes": "nota", "entry_date": "2026-01-15"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.delete(f"/api/positions/{pid}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self.saldo("Schwab"), 10_000, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class LasCajasViejasSeRenombranAlArrancar(_Base):
    """Las cajas 'USDT' que el importador creó para brokers en DÓLARES (35 en la
    base de prod del 2026-08-16) se renombran a 'USD' en el arranque (init_db, el
    mismo camino que corre producción al reiniciar). Sólo esas: un exchange y una
    subcuenta en dólares de un broker en pesos siguen con 'USDT', y la plata no
    se toca."""

    def test_al_arrancar_quedan_USD_y_lo_demas_no_se_toca(self):
        self.usuario([("Schwab", "USD", None), ("Binance", "USDT", None),
                      ("Balanz", "ARS", 500_000.0)])
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                     "SELECT ?, 'Balanz · USD', 'USDT', id FROM brokers WHERE user_id=? "
                     "AND name='Balanz'", (self.uid, self.uid))
        for broker, saldo in (("Schwab", 1234.5), ("Binance", 300.0), ("Balanz · USD", 80.0)):
            conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                         "VALUES (?,?,'USDT',1,?)", (self.uid, broker, saldo))
        conn.commit()
        conn.close()

        main.init_db()
        main.init_db()      # idempotente: la segunda pasada no encuentra nada

        self.assertEqual([(c["asset"], c["invested"]) for c in self.cajas("Schwab")],
                         [("USD", 1234.5)])
        self.assertEqual([c["asset"] for c in self.cajas("Binance")], ["USDT"])
        self.assertEqual([c["asset"] for c in self.cajas("Balanz · USD")], ["USDT"])
        self.assertEqual([(c["asset"], c["invested"]) for c in self.cajas("Balanz")],
                         [("ARS", 500_000.0)])


# ═════════════════════════════════════════════════════════════════════════════
class LasCajasVaciasPierdenElPrecioAlArrancar(_Base):
    """Las cajas vacías que quedaron con precio de compra (9 en la base de prod del
    2026-08-16) lo pierden en el arranque (init_db, el mismo camino que corre
    producción al reiniciar). Sólo esas, y sólo el precio: no se toca ningún saldo,
    ni el precio de una caja con dólares, ni el TC de compra de un lote."""

    def test_al_arrancar_quedan_sin_precio_y_lo_demas_no_se_toca(self):
        self.usuario([(f"B{i}", "ARS", None) for i in range(6)])
        conn = main.get_db()
        casos = {"B0 · USD": (0.0, 400.0), "B1 · USD": (0.003, 1300.0), "B2 · USD": (-70.0, 900.0),
                 "B3 · USD": (0.01, 400.0), "B4 · USD": (250.0, 1100.0), "B5 · USD": (80.0, None)}
        for nombre, (saldo, tc) in casos.items():
            conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                         "SELECT ?, ?, 'USDT', id FROM brokers WHERE user_id=? AND name=?",
                         (self.uid, nombre, self.uid, nombre.split(" · ")[0]))
            conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested, tc_compra) "
                         "VALUES (?,?,'USDT',1,?,?)", (self.uid, nombre, saldo, tc))
        # Un lote vendido entero (cantidad 0) con su TC de compra: no es una caja.
        conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested, "
                     "tc_compra) VALUES (?,'B0','GGAL',0,0,0,1050)", (self.uid,))
        conn.commit()
        conn.close()

        main.init_db()
        main.init_db()      # idempotente: la segunda pasada no encuentra nada

        quedo = {n: (self.cajas(n)[0]["invested"], self.cajas(n)[0]["tc_compra"]) for n in casos}
        self.assertEqual(quedo, {
            "B0 · USD": (0.0, None), "B1 · USD": (0.003, None), "B2 · USD": (-70.0, None),
            "B3 · USD": (0.01, 400.0), "B4 · USD": (250.0, 1100.0), "B5 · USD": (80.0, None)})
        conn = main.get_db()
        lote = conn.execute("SELECT tc_compra FROM positions WHERE user_id=? AND asset='GGAL'",
                            (self.uid,)).fetchone()
        sueltas = conn.execute(
            f"SELECT COUNT(*) c FROM positions WHERE user_id=? AND {efectivo.SQL_CAJA_VACIA_CON_PRECIO}",
            (self.uid,)).fetchone()["c"]
        conn.close()
        self.assertEqual(lote["tc_compra"], 1050)
        self.assertEqual(sueltas, 0)


# ═════════════════════════════════════════════════════════════════════════════
class ElPrecioDeLaCajaSeEscribeEnUnSoloLugar(unittest.TestCase):
    """Guardián del código. La regla "una caja vacía no tiene precio" se sostiene
    porque el precio lo escribe UNA función (`efectivo.mover`) y la ganancia
    cambiaria la calcula UNA (`efectivo.venta_de_dolares`). Las dos veces que se
    rompió fue por una copia: borrar una conversión escribía el precio por su
    cuenta, después de la puerta, y el importador leía el de la caja con su propia
    consulta. El comportamiento lo fijan las pruebas de arriba y las de
    `test_operaciones_con_receta.py`; esto avisa si vuelve a aparecer una copia."""

    BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _fuentes(self):
        for carpeta, _, archivos in os.walk(self.BACKEND):
            if any(p in carpeta for p in ("tests", "scripts", "__pycache__", "node_modules")):
                continue
            for a in archivos:
                if a.endswith(".py"):
                    ruta = os.path.join(carpeta, a)
                    with open(ruta, encoding="utf-8") as f:
                        yield os.path.relpath(ruta, self.BACKEND), ast.parse(f.read())

    @staticmethod
    def _textos(nodo):
        """Los textos escritos adentro de `nodo`, con los pedazos de un f-string y
        los de una concatenación pegados (una consulta partida en dos renglones)."""
        fuera = set()
        for n in ast.walk(nodo):
            if isinstance(n, ast.JoinedStr):
                fuera.update(id(x) for x in ast.walk(n) if x is not n)
                yield "".join(v.value for v in n.values
                              if isinstance(v, ast.Constant) and isinstance(v.value, str))
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in fuera:
                yield n.value

    def test_solo_mover_escribe_el_precio_de_una_caja(self):
        arbol = dict(self._fuentes())["efectivo.py"]
        escriben = set()
        for fn in (n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef)):
            sql = " ".join(" ".join(self._textos(fn)).split()).upper()
            if "TC_COMPRA=?" in sql.replace(" ", "") or (
                    "INSERT INTO POSITIONS" in sql and "TC_COMPRA" in sql):
                escriben.add(fn.name)
        self.assertEqual(escriben, {"mover"})

    def test_nadie_mas_lee_ni_escribe_el_precio_de_una_caja_con_su_propia_consulta(self):
        """Fuera de efectivo.py, ninguna consulta junta `tc_compra` con `is_cash=1`:
        el precio de una caja se pide a efectivo.py, que sabe cuándo no vale."""
        hallados = []
        for ruta, arbol in self._fuentes():
            if ruta == "efectivo.py":
                continue
            for llamada in (n for n in ast.walk(arbol) if isinstance(n, ast.Call)):
                sql = "".join(" ".join(self._textos(llamada)).split()).lower()
                if "tc_compra" in sql and "is_cash=1" in sql and "positions" in sql:
                    hallados.append(f"{ruta}:{llamada.lineno}")
        self.assertEqual(hallados, [])

    def test_el_guardian_ve_lo_que_dice_ver(self):
        """Las dos copias que hubo, como estaban escritas."""
        vieja_escritura = ast.parse(
            "def revertir(conn):\n"
            "    conn.execute('UPDATE positions SET tc_compra=? WHERE id=? AND user_id=?', (1, 2, 3))\n")
        fn = vieja_escritura.body[0]
        self.assertIn("TC_COMPRA=?", " ".join(self._textos(fn)).upper().replace(" ", ""))
        vieja_lectura = ast.parse(
            "cash = conn.execute(\n"
            "    'SELECT tc_compra FROM positions WHERE user_id=? AND broker=? AND is_cash=1 '\n"
            "    'ORDER BY id LIMIT 1', (uid, b)).fetchone()\n")
        llamadas = [n for n in ast.walk(vieja_lectura) if isinstance(n, ast.Call)]
        self.assertTrue(any(
            "tc_compra" in s and "is_cash=1" in s
            for s in ("".join(" ".join(self._textos(c)).split()).lower() for c in llamadas)))


if __name__ == "__main__":
    unittest.main()
