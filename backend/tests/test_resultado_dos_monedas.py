"""El resultado de cada venta en pesos Y en dólares, cada punta a su dólar.

EL CASO. GGAL comprada a $4.500 con el dólar en 1.000 y vendida a $6.900 con el
dólar en 1.500. `pnl_pct` guardaba +53,3 % (pesos) y la columna «P&L %» lo mostraba
igual con la app en dólares, donde la ganancia fue +2,2 % (US$ 450 → US$ 460).

LO QUE SE PRUEBA. Todo por las rutas reales: alta por `POST /api/positions`, venta
por `POST /api/positions/sell` o por un archivo (`/api/imports/*`), lectura por
`GET /api/operations`. El histórico por el botón de Admin
(`POST /api/admin/resultado-dos-monedas`), sobre filas a las que se les vaciaron
las columnas nuevas: tiene que dar EXACTAMENTE lo que había escrito el motor.

Y que `pnl_usd` / `pnl_pct` no se movieron: alimentan el P&L realizado y la curva.

Corre con: cd backend && python3 -m pytest tests/test_resultado_dos_monedas.py
"""
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")
PESOS = "Cocos"
DOLARES = "Bull"
COLS = ("costo_ars", "costo_usd", "cobrado_ars", "cobrado_usd",
        "pnl_pct_ars", "pnl_pct_usd", "pnl_sin_dato")

# El dólar de cada día (MEP y blue iguales: la prueba no es sobre el riel).
DOLAR = {"2024-01-10": 1000.0, "2024-03-11": 1200.0, "2024-06-10": 1500.0}


def setUpModule():
    conn = main.get_db()
    for fecha, tc in DOLAR.items():
        conn.execute("INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta) "
                     "VALUES (?,?,?)", (fecha, tc, tc))
    conn.commit()
    conn.close()


class _Base(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.uid, self.h = self._cuenta()

    def _cuenta(self, admin=False):
        conn = main.get_db()
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, ?)",
            (f"dual-{uuid.uuid4().hex[:10]}@rendi.test", 1 if admin else 0)).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                     (uid, PESOS))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'USD')",
                     (uid, DOLARES))
        conn.commit()
        conn.close()
        return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _alta(self, **campos):
        r = self.client.post("/api/positions", headers=self.h, json=campos)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _vender(self, **campos):
        r = self.client.post("/api/positions/sell", headers=self.h, json=campos)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["operations"]

    def _ventas(self, asset):
        r = self.client.get("/api/operations", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        ops = [o for o in r.json() if o["asset"] == asset and o["op_type"] == "Venta"]
        return sorted(ops, key=lambda o: (o.get("entry_date") or "", o["id"]))

    def _importar(self, filas, h=None):
        r = self.client.post(
            "/api/imports/preview", headers=h or self.h,
            files=[("files", ("v.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": PESOS})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", headers=h or self.h,
                             json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def _vaciar_y_recalcular(self):
        """Lo que pasa con lo YA guardado: las filas nacen sin las columnas y el
        botón de Admin las completa."""
        conn = main.get_db()
        conn.execute(f"UPDATE operations SET {', '.join(c + '=NULL' for c in COLS)} "
                     "WHERE user_id=?", (self.uid,))
        conn.commit()
        conn.close()
        _, h_admin = self._cuenta(admin=True)
        r = self.client.post(f"/api/admin/resultado-dos-monedas?apply=false&user_id={self.uid}",
                             headers=h_admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["applied"])
        self.assertTrue(all(o["pnl_pct_ars"] is None for o in self._ventas_todas()),
                        "el paso de mirar escribió algo")
        r = self.client.post(f"/api/admin/resultado-dos-monedas?apply=true&user_id={self.uid}",
                             headers=h_admin)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _ventas_todas(self):
        r = self.client.get("/api/operations", headers=self.h)
        return [o for o in r.json() if o["op_type"] == "Venta"]

    def assertMismoResultado(self, antes, despues):
        self.assertEqual(len(antes), len(despues))
        for a, d in zip(antes, despues):
            for c in COLS:
                if isinstance(a[c], float):
                    self.assertAlmostEqual(a[c], d[c], delta=abs(a[c]) * 1e-5 + 1e-4,
                                           msg=f"{c}: motor {a[c]} vs histórico {d[c]}")
                else:
                    self.assertEqual(a[c], d[c], c)


class VentaEnPesosConDevaluacion(_Base):

    def setUp(self):
        super().setUp()
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        self.op = self._ventas("GGAL")[0]

    def test_los_dos_porcentajes(self):
        op = self.op
        self.assertAlmostEqual(op["pnl_pct_ars"], 53.3333, places=3)
        # US$ 450 (450.000 ÷ 1.000) → US$ 460 (690.000 ÷ 1.500)
        self.assertAlmostEqual(op["costo_usd"], 450, places=4)
        self.assertAlmostEqual(op["cobrado_usd"], 460, places=4)
        self.assertAlmostEqual(op["pnl_pct_usd"], 2.2222, places=3)
        self.assertIsNone(op["pnl_sin_dato"])

    def test_lo_de_siempre_no_se_movio(self):
        self.assertAlmostEqual(self.op["pnl_pct"], 53.3333, places=3)
        self.assertAlmostEqual(self.op["pnl_usd"], 160, places=2)   # 240.000 ÷ 1.500

    def test_el_historico_da_lo_mismo(self):
        antes = self._ventas("GGAL")
        out = self._vaciar_y_recalcular()
        self.assertEqual(out["filas"], 1)
        self.assertMismoResultado(antes, self._ventas("GGAL"))

    def test_apretar_dos_veces_no_hace_nada(self):
        self._vaciar_y_recalcular()
        _, h_admin = self._cuenta(admin=True)
        r = self.client.post(f"/api/admin/resultado-dos-monedas?apply=true&user_id={self.uid}",
                             headers=h_admin)
        self.assertEqual(r.json()["filas"], 0)

    def test_el_dolar_que_escribio_el_usuario_gana(self):
        self._alta(broker=PESOS, asset="YPFD", quantity=10, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="YPFD", quantity=10, exit_price=6900,
                     date="2024-06-10", currency="ARS", tc_venta=1380)
        op = self._ventas("YPFD")[0]
        self.assertAlmostEqual(op["cobrado_usd"], 50, places=4)        # 69.000 ÷ 1.380
        self.assertAlmostEqual(op["pnl_pct_usd"], 11.1111, places=3)   # 45 → 50


class VentaEnDolares(_Base):

    def test_el_porcentaje_en_pesos(self):
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100,
                   entry_date="2024-01-10")
        self._vender(broker=DOLARES, asset="AAPL", quantity=10, exit_price=150,
                     date="2024-06-10")
        op = self._ventas("AAPL")[0]
        self.assertAlmostEqual(op["pnl_pct_usd"], 50, places=4)
        self.assertAlmostEqual(op["pnl_pct"], 50, places=4)
        # $ 1.000.000 (1.000 × 1.000) → $ 2.250.000 (1.500 × 1.500)
        self.assertAlmostEqual(op["costo_ars"], 1_000_000, places=2)
        self.assertAlmostEqual(op["cobrado_ars"], 2_250_000, places=2)
        self.assertAlmostEqual(op["pnl_pct_ars"], 125, places=4)
        antes = self._ventas("AAPL")
        self._vaciar_y_recalcular()
        self.assertMismoResultado(antes, self._ventas("AAPL"))


class CedearEnPesos(_Base):

    def test_cedear_comprado_y_vendido_en_pesos(self):
        self._alta(broker=PESOS, asset="KO", quantity=10, buy_price=20000,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="KO", quantity=10, exit_price=33000,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("KO")[0]
        self.assertAlmostEqual(op["pnl_pct_ars"], 65, places=4)
        self.assertAlmostEqual(op["pnl_pct_usd"], 10, places=4)   # US$ 200 → US$ 220


class VentaQueBarreDosLotes(_Base):

    def test_cada_lote_con_su_dolar_de_compra(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                   entry_date="2024-03-11", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=15, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        a, b = self._ventas("GGAL")
        self.assertEqual((a["quantity"], b["quantity"]), (10, 5))
        self.assertAlmostEqual(a["pnl_pct_usd"], 2.2222, places=3)
        # 25.000 pesos ÷ 1.200 = US$ 20,83 → 34.500 ÷ 1.500 = US$ 23
        self.assertAlmostEqual(b["costo_usd"], 20.8333, places=3)
        self.assertAlmostEqual(b["pnl_pct_usd"], 10.4, places=3)
        self.assertAlmostEqual(b["pnl_pct_ars"], 38, places=3)
        antes = self._ventas("GGAL")
        self._vaciar_y_recalcular()
        self.assertMismoResultado(antes, self._ventas("GGAL"))


class LoteEnDolaresVendidoEnPesos(_Base):
    """El costo del lote está en dólares: el motor lo llevó a pesos al dólar de la
    VENTA (para cancelar el TC). El histórico tiene que deshacer esa conversión."""

    def test_motor_e_historico(self):
        self._alta(broker=PESOS, asset="AL30", quantity=100, buy_price=0.5,
                   entry_date="2024-01-10", currency="USD")
        self._vender(broker=PESOS, asset="AL30", quantity=100, exit_price=900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("AL30")[0]
        self.assertAlmostEqual(op["costo_usd"], 50, places=4)
        self.assertAlmostEqual(op["costo_ars"], 50_000, places=2)      # 50 × 1.000
        self.assertAlmostEqual(op["cobrado_usd"], 60, places=4)       # 90.000 ÷ 1.500
        self.assertAlmostEqual(op["pnl_pct_usd"], 20, places=4)
        self.assertAlmostEqual(op["pnl_pct_usd"], op["pnl_pct"], places=3)
        self.assertAlmostEqual(op["pnl_pct_ars"], 80, places=4)
        antes = self._ventas("AL30")
        self._vaciar_y_recalcular()
        self.assertMismoResultado(antes, self._ventas("AL30"))


class SinFechaDeCompra(_Base):

    def test_la_otra_moneda_queda_sin_dato(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, commissions, currency)
               VALUES (?,?,?,0,4500,10,45000,NULL,0,'ARS')""", (self.uid, PESOS, "GGAL"))
        conn.commit()
        conn.close()
        self._vender(broker=PESOS, asset="GGAL", quantity=10, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("GGAL")[0]
        self.assertAlmostEqual(op["pnl_pct_ars"], 53.3333, places=3)
        self.assertIsNone(op["pnl_pct_usd"])
        self.assertEqual(op["pnl_sin_dato"], "sin_fecha_compra")
        antes = self._ventas("GGAL")
        self._vaciar_y_recalcular()
        self.assertMismoResultado(antes, self._ventas("GGAL"))

    def test_sin_dolar_para_esa_fecha(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=10, buy_price=4500,
                   entry_date="2005-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=10, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("GGAL")[0]
        self.assertIsNone(op["pnl_pct_usd"])
        self.assertEqual(op["pnl_sin_dato"], "sin_dolar_compra")


class EditarLaVenta(_Base):

    def test_cambiar_el_precio_recalcula(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("GGAL")[0]
        # El formulario manda la fila entera; el usuario corrige el precio y el %.
        r = self.client.put(f"/api/operations/{op['id']}", headers=self.h, json={
            "date": op["date"], "broker": op["broker"], "asset": op["asset"],
            "op_type": "Venta", "entry_price": 4500, "exit_price": 7200,
            "quantity": 100, "pnl_usd": 180, "pnl_pct": 60, "commissions": 0,
            "currency": "ARS", "fx_to_usd": op["fx_to_usd"]})
        self.assertEqual(r.status_code, 200, r.text)
        op = self._ventas("GGAL")[0]
        self.assertAlmostEqual(op["pnl_pct_ars"], 60, places=3)
        self.assertAlmostEqual(op["costo_usd"], 450, places=3)
        self.assertAlmostEqual(op["pnl_pct_usd"], 6.6667, places=3)   # 450 → 480


class PorArchivo(_Base):

    def test_importar_y_que_el_rebuild_no_lo_pise(self):
        self._importar("2024-01-10,COMPRA,Cocos,GGAL,100,4500,450000,,,0,ARS,\n"
                       "2024-06-10,VENTA,Cocos,GGAL,100,6900,690000,,,0,ARS,\n")
        op = self._ventas("GGAL")[0]
        self.assertAlmostEqual(op["pnl_pct_ars"], 53.3333, places=3)
        self.assertAlmostEqual(op["pnl_pct_usd"], 2.2222, places=3)
        self.assertAlmostEqual(op["pnl_pct"], 53.3333, places=3)
        antes = self._ventas("GGAL")
        # Un archivo con una compra MÁS VIEJA del mismo activo obliga a reconstruir
        # la historia entera (rebuild): la venta se borra y se vuelve a escribir.
        self._importar("2023-12-01,COMPRA,Cocos,GGAL,1,4000,4000,,,0,ARS,\n")
        despues = self._ventas("GGAL")
        self.assertNotEqual(antes[0]["id"], despues[0]["id"], "no hubo rebuild")
        # Ahora la venta barre primero el lote de 2023-12-01 —sin dólar en la serie
        # de prueba, así que su % en dólares queda sin dato— y después el de 2024.
        lote_2023 = [o for o in despues if o["entry_date"] == "2023-12-01"][0]
        lote_2024 = [o for o in despues if o["entry_date"] == "2024-01-10"][0]
        self.assertEqual(lote_2023["pnl_sin_dato"], "sin_dolar_compra")
        self.assertIsNotNone(lote_2023["pnl_pct_ars"])
        self.assertIsNotNone(lote_2024["pnl_pct_usd"], "el rebuild borró lo nuevo")
        self.assertAlmostEqual(lote_2024["pnl_pct_usd"], 2.2222, places=3)
        antes = self._ventas("GGAL")
        self._vaciar_y_recalcular()
        self.assertMismoResultado(antes, self._ventas("GGAL"))

    def test_dolar_mep_compra_en_pesos_venta_en_dolares(self):
        self._importar("2024-01-10,COMPRA,Cocos,AL30,1000,500,500000,,,0,ARS,\n"
                       "2024-06-10,VENTA,Cocos,AL30,1000,0.55,550,,,0,USD,\n")
        ops = self._ventas("AL30")
        self.assertEqual(len(ops), 1, ops)
        op = ops[0]
        self.assertEqual(op["currency"], "USD")
        self.assertAlmostEqual(op["costo_ars"], 500_000, places=2)
        self.assertAlmostEqual(op["costo_usd"], 500, places=3)       # al dólar de la compra
        self.assertAlmostEqual(op["pnl_pct_usd"], 10, places=3)
        self.assertAlmostEqual(op["pnl_pct_ars"], 65, places=3)      # 550 × 1.500 = 825.000
        antes = ops
        self._vaciar_y_recalcular()
        self.assertMismoResultado(antes, self._ventas("AL30"))


if __name__ == "__main__":
    unittest.main()
