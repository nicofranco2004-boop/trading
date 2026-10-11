"""Una tenencia sin su costo guardado: al venderla, TODO lo cobrado salía como ganancia.

EL CASO (medido por HTTP el 2026-10-10 contra `86dfacf7`). Broker en pesos.
`POST /api/positions` con precio 5.000 y cantidad 10, SIN `invested` — la API lo
acepta. Después `POST /api/positions/sell` de 4 a 8.000 con TC 1.250. La
operación quedaba con `pnl_usd = 25,6`: los 32.000 pesos cobrados enteros,
divididos por el TC. El resultado real son 9,6 (4 × (8.000 − 5.000) / 1.250).

DÓNDE SE ROMPÍA. En dos eslabones, y ninguno era la pantalla:

  1. EL ALTA. `_insert_manual_position` ya sabía el costo: le descontaba al
     efectivo `invested ?? precio × cantidad` (`_manual_position_cost`). Pero en
     la fila guardaba `invested` tal cual llegó: NULL. La plata salía de la caja
     y el lote quedaba anotado como si no hubiera costado nada. La edición
     (`PUT /api/positions/{id}`) hacía lo mismo: mandar el campo vacío BORRABA
     un costo que estaba bien.
  2. LA VENTA. Los tres motores (`sell_position_fifo`, `_persist_sell_fifo`,
     `rebuild._replay_asset`) tenían la red —"sin costo guardado, precio ×
     cantidad"— escrita SÓLO en la rama de dólares. La de pesos restaba
     `(entry_invested or 0)`: costo cero, en silencio. Y la red de dólares tenía
     su propio agujero: con comisión de compra cargada, el costo era la comisión
     sola.

El cobro de amortización de un bono (`cobros_bonos.aplicar_amortizacion`, que
baja el lote, y `main._costo_amortizado_en_caja`, que calcula la ganancia) hacía
la misma cuenta sin red en ninguna moneda, y además dejaba el resto del lote con
costo 0 escrito. El cambio de precio promedio del grupo, lo mismo.

EL ARREGLO. Una sola definición del costo de un lote, `fx.costo_del_lote`, que
usan el alta (para la caja Y para la fila), la edición, los tres motores de
venta, los dos de amortización y el cambio de precio promedio.

POR QUÉ ALGUNOS ESCENARIOS PLANTAN EL LOTE A MANO. Con el alta arreglada, por
HTTP ya no se puede fabricar un lote sin costo. Pero en producción existen (3
lotes en la copia del 2026-08-16, los tres de un alta a mano en un broker en
pesos), así que la venta tiene que saber qué hacer con ellos. Esos escenarios
escriben el lote directo —el ESTADO de partida— y todo lo que se mide después
pasa por la ruta real.

Corre con: cd backend && python3 -m pytest tests/test_venta_sin_costo_guardado.py
"""
import io
import json
import unittest
import uuid

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")

PESOS = "Cocos"
DOLARES = "Bull"


class _Base(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.uid, self.h = self._cuenta()

    def _cuenta(self):
        conn = main.get_db()
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)",
            (f"sincosto-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                     (uid, PESOS))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'USD')",
                     (uid, DOLARES))
        conn.commit()
        conn.close()
        return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}

    # ── rutas reales ────────────────────────────────────────────────────────
    def _alta(self, h=None, **campos):
        r = self.client.post("/api/positions", headers=h or self.h, json=campos)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _vender(self, h=None, **campos):
        r = self.client.post("/api/positions/sell", headers=h or self.h, json=campos)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["operations"]

    # ── el estado que ya existe en producción ───────────────────────────────
    def _plantar(self, uid, broker, asset, precio, cantidad, moneda, *,
                 invested=None, comisiones=0, asset_type=None):
        conn = main.get_db()
        pid = conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price,
                   quantity, invested, entry_date, commissions, currency, asset_type)
               VALUES (?,?,?,0,?,?,?,'2024-01-10',?,?,?)""",
            (uid, broker, asset, precio, cantidad, invested, comisiones, moneda,
             asset_type)).lastrowid
        conn.commit()
        conn.close()
        return pid

    def _lote(self, pid):
        conn = main.get_db()
        row = conn.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _mes(self, uid, broker, anio, mes):
        conn = main.get_db()
        row = conn.execute(
            "SELECT pnl_realized FROM monthly_entries "
            "WHERE user_id=? AND broker=? AND year=? AND month=?",
            (uid, broker, anio, mes)).fetchone()
        conn.close()
        return float(row["pnl_realized"] or 0) if row else None


class ElAltaGuardaElCosto(_Base):
    """La puerta: lo que se le descuenta a la caja es lo que queda anotado."""

    def test_sin_invertido_guarda_precio_por_cantidad(self):
        fila = self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                          entry_date="2026-01-10", currency="ARS", tc_compra=1000)
        self.assertIsNotNone(fila["invested"],
                             "el lote nació sin costo aunque la caja pagó 50.000")
        self.assertAlmostEqual(fila["invested"], 50000, places=4)

    def test_lo_guardado_es_lo_que_pago_la_caja(self):
        fila = self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                          commissions=250, entry_date="2026-01-10", currency="ARS")
        pagado = json.loads(fila["undo_meta_json"])["cost"]
        self.assertAlmostEqual(fila["invested"] + fila["commissions"], pagado, places=4)

    def test_el_invertido_que_manda_el_usuario_gana(self):
        fila = self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                          invested=48000, entry_date="2026-01-10", currency="ARS")
        self.assertAlmostEqual(fila["invested"], 48000, places=4)

    def test_en_dolares_tambien(self):
        fila = self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100,
                          entry_date="2026-01-10")
        self.assertAlmostEqual(fila["invested"], 1000, places=4)

    def test_editar_con_el_campo_vacio_no_borra_el_costo(self):
        fila = self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                          invested=50000, entry_date="2026-01-10", currency="ARS")
        r = self.client.put(f"/api/positions/{fila['id']}", headers=self.h, json={
            "broker": PESOS, "asset": "GGAL", "quantity": 12, "buy_price": 5000,
            "invested": None, "entry_date": "2026-01-10", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNotNone(r.json()["invested"], "editar dejó el lote sin costo")
        self.assertAlmostEqual(r.json()["invested"], 60000, places=4)


class VenderLoQueSeCargoSinInvertido(_Base):
    """El recorrido entero, como lo hace un usuario: alta sin el campo → venta."""

    def test_en_pesos_la_ganancia_no_es_todo_lo_cobrado(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                   entry_date="2026-01-10", currency="ARS", tc_compra=1000)
        ops = self._vender(broker=PESOS, asset="GGAL", quantity=4, exit_price=8000,
                           date="2026-02-10", tc_venta=1250)
        self.assertEqual(len(ops), 1)
        self.assertNotAlmostEqual(ops[0]["pnl_usd"], 25.6, places=2,
                                  msg="anotó lo cobrado entero como ganancia")
        self.assertAlmostEqual(ops[0]["pnl_usd"], 9.6, places=2)
        self.assertAlmostEqual(ops[0]["pnl_pct"], 60.0, places=2)
        self.assertAlmostEqual(self._mes(self.uid, "global", 2026, 2), 9.6, places=2)
        self.assertAlmostEqual(self._mes(self.uid, PESOS, 2026, 2), 9.6, places=2)

    def test_da_lo_mismo_que_con_el_campo_lleno(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                   entry_date="2026-01-10", currency="ARS")
        self._alta(broker=PESOS, asset="YPFD", quantity=10, buy_price=5000,
                   invested=50000, entry_date="2026-01-10", currency="ARS")
        sin = self._vender(broker=PESOS, asset="GGAL", quantity=4, exit_price=8000,
                           date="2026-02-10", tc_venta=1250)[0]
        con = self._vender(broker=PESOS, asset="YPFD", quantity=4, exit_price=8000,
                           date="2026-02-10", tc_venta=1250)[0]
        self.assertAlmostEqual(sin["pnl_usd"], con["pnl_usd"], places=2)
        self.assertAlmostEqual(sin["pnl_pct"], con["pnl_pct"], places=2)

    def test_en_dolares_sigue_dando_lo_de_siempre(self):
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100,
                   entry_date="2026-01-10")
        op = self._vender(broker=DOLARES, asset="AAPL", quantity=4, exit_price=150,
                          date="2026-02-10")[0]
        self.assertAlmostEqual(op["pnl_usd"], 200, places=2)


class VenderUnLoteQueYaEstabaSinCosto(_Base):
    """Los que ya existen: la venta no puede tomar costo cero en silencio."""

    def test_en_pesos(self):
        self._plantar(self.uid, PESOS, "GGAL", 5000, 10, "ARS")
        op = self._vender(broker=PESOS, asset="GGAL", quantity=4, exit_price=8000,
                          date="2026-02-10", tc_venta=1250)[0]
        self.assertAlmostEqual(op["pnl_usd"], 9.6, places=2)
        self.assertAlmostEqual(self._mes(self.uid, "global", 2026, 2), 9.6, places=2)

    def test_en_dos_ventas_parciales(self):
        self._plantar(self.uid, PESOS, "GGAL", 5000, 10, "ARS")
        a = self._vender(broker=PESOS, asset="GGAL", quantity=4, exit_price=8000,
                         date="2026-02-10", tc_venta=1250)[0]
        b = self._vender(broker=PESOS, asset="GGAL", quantity=6, exit_price=8000,
                         date="2026-02-11", tc_venta=1250)[0]
        self.assertAlmostEqual(a["pnl_usd"] + b["pnl_usd"], 24.0, places=2)

    def test_en_dolares_con_comision_de_compra(self):
        # La red de dólares tenía su agujero: con comisión cargada, el costo del
        # lote era la comisión SOLA (2) en vez de precio × cantidad + comisión (402).
        self._plantar(self.uid, DOLARES, "AAPL", 100, 10, "USD", comisiones=5)
        op = self._vender(broker=DOLARES, asset="AAPL", quantity=4, exit_price=150,
                          date="2026-02-10")[0]
        self.assertAlmostEqual(op["pnl_usd"], 198, places=2)

    def test_en_pesos_con_comision_de_compra(self):
        self._plantar(self.uid, PESOS, "GGAL", 5000, 10, "ARS", comisiones=500)
        op = self._vender(broker=PESOS, asset="GGAL", quantity=4, exit_price=8000,
                          date="2026-02-10", tc_venta=1250)[0]
        # 32.000 − (50.000 + 500) × 0,4 = 11.800 pesos → 9,44 dólares
        self.assertAlmostEqual(op["pnl_usd"], 9.44, places=2)


class CambiarElPrecioPromedioDelGrupo(_Base):
    """«Editar posición» sobre la fila agregada escala el costo de cada lote. El
    lote sin costo guardado no entraba en el total: el promedio daba bien, pero él
    quedaba con un 0 escrito y el otro cargaba con todo."""

    def test_cada_lote_conserva_su_parte(self):
        sin = self._plantar(self.uid, PESOS, "GGAL", 5000, 10, "ARS")                  # 50.000
        con = self._plantar(self.uid, PESOS, "GGAL", 6000, 10, "ARS", invested=60000)  # 60.000
        # Promedio de hoy: 5.500. Lo llevan a 11.000 → todo se duplica.
        r = self.client.patch("/api/positions/group", headers=self.h, json={
            "broker": PESOS, "asset": "GGAL", "currency": "ARS", "avg_price": 11000})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._lote(sin)["invested"], 100000, places=2)
        self.assertAlmostEqual(self._lote(con)["invested"], 120000, places=2)
        self.assertAlmostEqual(self._lote(sin)["buy_price"], 10000, places=2)
        self.assertAlmostEqual(self._lote(con)["buy_price"], 12000, places=2)


class LaVentaQueEntraPorUnArchivo(_Base):
    """El importador tiene su propio motor de venta (`_persist_sell_fifo`), copia
    del manual. Un lote cargado a mano se respeta en la reconstrucción, así que el
    número que escribe ese motor es el que queda."""

    def _importar(self, h, filas):
        r = self.client.post(
            "/api/imports/preview", headers=h,
            files=[("files", ("v.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": PESOS})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", headers=h,
                             json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def _venta(self, uid):
        conn = main.get_db()
        rows = conn.execute(
            "SELECT pnl_usd, pnl_pct, quantity FROM operations "
            "WHERE user_id=? AND op_type='Venta' AND asset='GGAL'", (uid,)).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1, [dict(r) for r in rows])
        return dict(rows[0])

    def test_en_pesos_da_lo_mismo_que_un_lote_con_costo(self):
        otra_uid, otra_h = self._cuenta()
        self._plantar(self.uid, PESOS, "GGAL", 5000, 10, "ARS")                  # sin costo
        self._plantar(otra_uid, PESOS, "GGAL", 5000, 10, "ARS", invested=50000)  # con costo
        fila = "2024-03-15,VENTA,Cocos,GGAL,4,8000,32000,,,0,ARS,\n"
        self._importar(self.h, fila)
        self._importar(otra_h, fila)
        sin, con = self._venta(self.uid), self._venta(otra_uid)
        self.assertGreater(con["pnl_usd"], 0)
        self.assertAlmostEqual(sin["pnl_usd"], con["pnl_usd"], places=2)
        self.assertAlmostEqual(sin["pnl_pct"], con["pnl_pct"], places=2)


class LaAmortizacionDeUnBonoSinCosto(_Base):
    """El cobro de una amortización le saca costo al lote con la misma cuenta
    (`cobros_bonos.aplicar_amortizacion` y `main._costo_amortizado_en_caja`)."""

    def _amortizar(self):
        r = self.client.post("/api/bonds/cashflow", headers=self.h, json={
            "broker": DOLARES, "asset": "AL30", "flow_type": "amortization",
            "amount": 100, "face_amortized": 100, "date": "2026-02-10",
            "decrement_quantity": True})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        row = conn.execute(
            "SELECT id, pnl_usd, cost_basis_consumed FROM operations "
            "WHERE user_id=? AND op_type='Amortización'", (self.uid,)).fetchone()
        conn.close()
        return dict(row)

    def test_la_ganancia_no_es_todo_lo_cobrado(self):
        pid = self._plantar(self.uid, DOLARES, "AL30", 0.7, 1000, "USD",
                            asset_type="BOND")
        # Vuelven 100 de 1.000 nominales comprados a 0,70: 70 eran costo, 30 ganancia.
        op = self._amortizar()
        self.assertAlmostEqual(op["cost_basis_consumed"], 70, places=4)
        self.assertAlmostEqual(op["pnl_usd"], 30, places=4)
        resto = self._lote(pid)
        self.assertAlmostEqual(resto["quantity"], 900, places=4)
        self.assertAlmostEqual(resto["invested"], 630, places=4)

    def test_da_lo_mismo_que_un_lote_con_costo(self):
        otra_uid, otra_h = self._cuenta()
        self._plantar(self.uid, DOLARES, "AL30", 0.7, 1000, "USD", asset_type="BOND")
        self._plantar(otra_uid, DOLARES, "AL30", 0.7, 1000, "USD", invested=700,
                      asset_type="BOND")
        sin = self._amortizar()
        self.uid, self.h = otra_uid, otra_h
        con = self._amortizar()
        self.assertAlmostEqual(sin["pnl_usd"], con["pnl_usd"], places=4)
        self.assertAlmostEqual(sin["cost_basis_consumed"], con["cost_basis_consumed"], places=4)

    def test_borrar_el_cobro_devuelve_el_costo_entero(self):
        pid = self._plantar(self.uid, DOLARES, "AL30", 0.7, 1000, "USD",
                            asset_type="BOND")
        op = self._amortizar()
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        lote = self._lote(pid)
        self.assertAlmostEqual(lote["quantity"], 1000, places=4)
        self.assertAlmostEqual(lote["invested"], 700, places=4)


if __name__ == "__main__":
    unittest.main()
