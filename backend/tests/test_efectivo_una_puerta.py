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
"""
import io
import unittest
import uuid

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


if __name__ == "__main__":
    unittest.main()
