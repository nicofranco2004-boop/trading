"""El resultado de cada venta en pesos Y en dólares, cada punta a su dólar.

EL CASO. GGAL comprada a $4.500 con el dólar en 1.000 (US$ 450) y vendida a $6.900
con el dólar en 1.500 (US$ 460). La venta anotaba `pnl_usd` = 240.000 ÷ 1.500 =
+US$ 160 y `pnl_pct` = +53,3 % (el de pesos), mientras Cartera en dólares mostraba
+US$ 10 un minuto antes de vender: vender fabricaba US$ 150.

LA REGLA (Nico, 24/10/2026). En las cuentas v2 el resultado en dólares es lo
cobrado al dólar de la venta menos el costo al dólar de compra DEL LOTE
(`positions.tc_compra`, el que usa Cartera). En v1 no cambia (fx.py,
"Versionado por usuario"). En pesos, el resultado en pesos.

LO QUE SE PRUEBA, todo por las rutas reales: alta por `POST /api/positions`, venta
por `POST /api/positions/sell` o por archivo (`/api/imports/*`), lectura por
`GET /api/operations`, el mes por `monthly_entries`. El histórico: ventas "viejas"
escritas por el MISMO motor con la regla nueva apagada (`_regla_vieja`, que es lo
que hacía el código anterior), corregidas por `POST /api/admin/resultado-dos-monedas`
y comparadas contra una cuenta gemela que vendió con la regla nueva.

Corre con: cd backend && python3 -m pytest tests/test_resultado_dos_monedas.py
"""
import contextlib
import io
import unittest
import uuid
from unittest import mock

import fx
import main
import resultado_dual
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


@contextlib.contextmanager
def _regla_vieja():
    """El motor de venta como era antes: sin el resultado en dos monedas y con
    `pnl_usd` = ganancia en pesos ÷ dólar de la venta. Así nacen las filas que
    hoy están en producción."""
    with mock.patch.object(resultado_dual, "resultado_en_dolares", lambda r: None), \
            mock.patch.object(resultado_dual, "guardar", lambda *a, **k: None):
        yield


class _Base(unittest.TestCase):

    def setUp(self):
        # La reconstrucción a mercado en otro hilo no es lo que se mide, y traba la
        # base a mitad de un rebuild ("database is locked"). Igual que las otras
        # pruebas de puertas (test_operaciones_con_receta.py).
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(main.app)
        self.uid, self.h = self._cuenta()
        self._admin = None

    def _cuenta(self, admin=False, v1=False):
        conn = main.get_db()
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, ?)",
            (f"dual-{uuid.uuid4().hex[:10]}@rendi.test", 1 if admin else 0)).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                     (uid, PESOS))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'USD')",
                     (uid, DOLARES))
        fx.set_fx_version(conn, uid, fx.FX_V1 if v1 else fx.FX_V2)
        conn.commit()
        conn.close()
        return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _h_admin(self):
        if self._admin is None:
            self._admin = self._cuenta(admin=True)[1]
        return self._admin

    def _alta(self, h=None, **campos):
        r = self.client.post("/api/positions", headers=h or self.h, json=campos)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _vender(self, h=None, **campos):
        r = self.client.post("/api/positions/sell", headers=h or self.h, json=campos)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["operations"]

    def _ventas(self, asset, h=None):
        r = self.client.get("/api/operations", headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        ops = [o for o in r.json() if o["asset"] == asset and o["op_type"] == "Venta"]
        return sorted(ops, key=lambda o: (o.get("entry_date") or "", o["quantity"]))

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

    def _mes(self, uid, broker="global", anio=2024, mes=6):
        conn = main.get_db()
        row = conn.execute(
            "SELECT pnl_realized FROM monthly_entries "
            "WHERE user_id=? AND broker=? AND year=? AND month=?",
            (uid, broker, anio, mes)).fetchone()
        conn.close()
        return float(row["pnl_realized"] or 0) if row else None

    def _corregir(self, *, apply, user_id=None, tanda=10, dias=60):
        q = f"apply={'true' if apply else 'false'}&tanda={tanda}&dias={dias}"
        if user_id is not None:
            q += f"&user_id={user_id}"
        r = self.client.post(f"/api/admin/resultado-dos-monedas?{q}", headers=self._h_admin())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def assertMismaVenta(self, nueva, corregida):
        """La venta corregida por el histórico == la que escribe hoy el motor."""
        self.assertEqual(len(nueva), len(corregida))
        for a, d in zip(nueva, corregida):
            for c in COLS + ("pnl_usd", "pnl_pct"):
                if isinstance(a[c], float):
                    self.assertAlmostEqual(a[c], d[c], delta=abs(a[c]) * 1e-5 + 0.011,
                                           msg=f"{c}: motor {a[c]} vs histórico {d[c]}")
                else:
                    self.assertEqual(a[c], d[c], c)


# ─── La regla nueva, en los motores ──────────────────────────────────────────

class VentaEnPesosConDevaluacion(_Base):

    def setUp(self):
        super().setUp()
        self.lote = self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                               entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        self.op = self._ventas("GGAL")[0]

    def test_el_resultado_en_dolares_es_el_de_cartera(self):
        # Cartera en dólares: costo = invertido ÷ tc_compra del lote (costBasisRate).
        costo_cartera = self.lote["invested"] / self.lote["tc_compra"]
        self.assertAlmostEqual(costo_cartera, 450, places=4)
        op = self.op
        self.assertAlmostEqual(op["pnl_usd"], 10, places=2)          # US$ 460 − US$ 450
        self.assertAlmostEqual(op["pnl_pct"], 2.2222, places=3)
        self.assertAlmostEqual(op["costo_usd"], costo_cartera, places=4)
        self.assertAlmostEqual(op["cobrado_usd"], 460, places=4)

    def test_en_pesos_sigue_siendo_el_de_pesos(self):
        self.assertAlmostEqual(self.op["pnl_pct_ars"], 53.3333, places=3)
        self.assertAlmostEqual(self.op["cobrado_ars"] - self.op["costo_ars"], 240000, places=2)

    def test_el_mes_anota_lo_mismo_global_y_broker(self):
        self.assertAlmostEqual(self._mes(self.uid), 10, places=2)
        self.assertAlmostEqual(self._mes(self.uid, PESOS), 10, places=2)

    def test_el_dolar_que_escribio_el_usuario_en_la_venta_gana(self):
        self._alta(broker=PESOS, asset="YPFD", quantity=10, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="YPFD", quantity=10, exit_price=6900,
                     date="2024-06-10", currency="ARS", tc_venta=1380)
        op = self._ventas("YPFD")[0]
        self.assertAlmostEqual(op["cobrado_usd"], 50, places=4)        # 69.000 ÷ 1.380
        self.assertAlmostEqual(op["pnl_usd"], 5, places=2)             # 45 → 50


class LoQueLeeLaPantalla(_Base):

    def test_la_regla_que_usa_la_vista_previa_de_vender(self):
        r = self.client.get("/api/positions/regla-de-venta", headers=self.h)
        self.assertEqual(r.json(), {"cada_punta_a_su_dolar": True})
        _, h_v1 = self._cuenta(v1=True)
        r = self.client.get("/api/positions/regla-de-venta", headers=h_v1)
        self.assertEqual(r.json(), {"cada_punta_a_su_dolar": False})

    def test_movimientos_trae_el_resultado_en_pesos(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = r.json() if isinstance(r.json(), list) else r.json().get("movements", [])
        venta = [m for m in filas if m.get("type") == "SELL" and m.get("asset") == "GGAL"][0]
        self.assertAlmostEqual(venta["cobrado_ars"] - venta["costo_ars"], 240000, places=2)
        self.assertAlmostEqual(venta["pnl_usd"], 10, places=2)


class ElDolarDeCompraDelLote(_Base):
    """Si el usuario escribió el dólar de la compra al cargar el lote, Cartera usa
    ése; el resultado de la venta también."""

    def test_tc_compra_escrito(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS", tc_compra=1125)
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("GGAL")[0]
        self.assertAlmostEqual(op["costo_usd"], 400, places=4)        # 450.000 ÷ 1.125
        self.assertAlmostEqual(op["pnl_usd"], 60, places=2)            # 460 − 400
        self.assertAlmostEqual(op["pnl_pct"], 15, places=3)


class VentaEnDolares(_Base):

    def test_no_cambia_y_suma_el_de_pesos(self):
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100,
                   entry_date="2024-01-10")
        self._vender(broker=DOLARES, asset="AAPL", quantity=10, exit_price=150,
                     date="2024-06-10")
        op = self._ventas("AAPL")[0]
        self.assertAlmostEqual(op["pnl_usd"], 500, places=2)
        self.assertAlmostEqual(op["pnl_pct"], 50, places=4)
        # $ 1.000.000 (1.000 × 1.000) → $ 2.250.000 (1.500 × 1.500)
        self.assertAlmostEqual(op["pnl_pct_ars"], 125, places=4)


class CedearEnPesos(_Base):

    def test_cedear_comprado_y_vendido_en_pesos(self):
        self._alta(broker=PESOS, asset="KO", quantity=10, buy_price=20000,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="KO", quantity=10, exit_price=33000,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("KO")[0]
        self.assertAlmostEqual(op["pnl_pct_ars"], 65, places=4)
        self.assertAlmostEqual(op["pnl_usd"], 20, places=2)            # US$ 200 → 220
        self.assertAlmostEqual(op["pnl_pct"], 10, places=4)


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
        self.assertAlmostEqual(a["pnl_usd"], 1, places=2)              # 45 → 46
        # 25.000 ÷ 1.200 = US$ 20,83 → 34.500 ÷ 1.500 = US$ 23
        self.assertAlmostEqual(b["pnl_usd"], 2.17, places=2)
        self.assertAlmostEqual(b["pnl_pct_ars"], 38, places=3)
        self.assertAlmostEqual(self._mes(self.uid), 3.17, places=2)


class LoteEnDolaresVendidoEnPesos(_Base):

    def test_da_lo_mismo_que_antes(self):
        self._alta(broker=PESOS, asset="AL30", quantity=100, buy_price=0.5,
                   entry_date="2024-01-10", currency="USD")
        self._vender(broker=PESOS, asset="AL30", quantity=100, exit_price=900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("AL30")[0]
        self.assertAlmostEqual(op["pnl_usd"], 10, places=2)            # 50 → 60
        self.assertAlmostEqual(op["pnl_pct"], 20, places=4)
        self.assertAlmostEqual(op["pnl_pct_ars"], 80, places=4)        # 50.000 → 90.000


class SinFechaDeCompra(_Base):

    def test_queda_la_regla_de_siempre_y_el_porque(self):
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
        self.assertAlmostEqual(op["pnl_usd"], 16, places=2)            # 24.000 ÷ 1.500

    def test_sin_dolar_para_esa_fecha(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, commissions, currency)
               VALUES (?,?,?,0,4500,10,45000,'2005-01-10',0,'ARS')""", (self.uid, PESOS, "GGAL"))
        conn.commit()
        conn.close()
        self._vender(broker=PESOS, asset="GGAL", quantity=10, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("GGAL")[0]
        self.assertIsNone(op["pnl_pct_usd"])
        self.assertEqual(op["pnl_sin_dato"], "sin_dolar_compra")


class CuentaV1(_Base):
    """Las cuentas que todavía no pasaron al dólar por fecha no cambian."""

    def test_v1_sigue_con_la_regla_vieja(self):
        self.uid, self.h = self._cuenta(v1=True)
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS", tc_venta=1500)
        op = self._ventas("GGAL")[0]
        self.assertAlmostEqual(op["pnl_usd"], 160, places=2)
        self.assertAlmostEqual(op["pnl_pct_usd"], 2.2222, places=3)   # la columna, igual


class EditarLaVenta(_Base):

    def test_cambiar_el_precio_recalcula_las_columnas(self):
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("GGAL")[0]
        r = self.client.put(f"/api/operations/{op['id']}", headers=self.h, json={
            "date": op["date"], "broker": op["broker"], "asset": op["asset"],
            "op_type": "Venta", "entry_price": 4500, "exit_price": 7200,
            "quantity": 50, "pnl_usd": 15, "pnl_pct": 6.6667, "commissions": 0,
            "currency": "ARS", "fx_to_usd": op["fx_to_usd"]})
        self.assertEqual(r.status_code, 200, r.text)
        op = self._ventas("GGAL")[0]
        # La mitad del lote: US$ 225 de costo, 360.000 ÷ 1.500 = US$ 240 cobrados.
        self.assertAlmostEqual(op["costo_usd"], 225, places=3)
        self.assertAlmostEqual(op["pnl_pct_usd"], 6.6667, places=3)
        self.assertAlmostEqual(op["pnl_pct_ars"], 60, places=3)
        self.assertAlmostEqual(op["pnl_usd"], 15, places=2)            # el que escribió


class PorArchivo(_Base):

    def test_importar_y_que_el_rebuild_no_lo_pise(self):
        self._importar("2024-01-10,COMPRA,Cocos,GGAL,100,4500,450000,,,0,ARS,\n"
                       "2024-06-10,VENTA,Cocos,GGAL,100,6900,690000,,,0,ARS,\n")
        op = self._ventas("GGAL")[0]
        self.assertAlmostEqual(op["pnl_usd"], 10, places=2)
        self.assertAlmostEqual(op["pnl_pct_ars"], 53.3333, places=3)
        self.assertAlmostEqual(self._mes(self.uid), 10, places=2)
        # Una compra MÁS VIEJA del mismo activo obliga a reconstruir la historia
        # (rebuild): la venta se borra y se vuelve a escribir.
        antes_id = op["id"]
        self._importar("2023-12-01,COMPRA,Cocos,GGAL,1,4000,4000,,,0,ARS,\n")
        despues = self._ventas("GGAL")
        self.assertNotIn(antes_id, [o["id"] for o in despues], "no hubo rebuild")
        lote_2023 = [o for o in despues if o["entry_date"] == "2023-12-01"][0]
        lote_2024 = [o for o in despues if o["entry_date"] == "2024-01-10"][0]
        # El de 2023 no tiene dólar en la serie de prueba: regla de siempre + porqué.
        self.assertEqual(lote_2023["pnl_sin_dato"], "sin_dolar_compra")
        self.assertAlmostEqual(lote_2023["pnl_usd"], (6900 - 4000) / 1500, places=2)
        # 99 de los 100 del lote de 2024: costo 445.500 ÷ 1.000, cobro 683.100 ÷ 1.500
        self.assertAlmostEqual(lote_2024["pnl_usd"], 683100 / 1500 - 445.5, places=2)
        self.assertAlmostEqual(lote_2024["pnl_pct_usd"], 2.2222, places=3)

    def test_dolar_mep_compra_en_pesos_venta_en_dolares(self):
        self._importar("2024-01-10,COMPRA,Cocos,AL30,1000,500,500000,,,0,ARS,\n"
                       "2024-06-10,VENTA,Cocos,AL30,1000,0.55,550,,,0,USD,\n")
        op = self._ventas("AL30")[0]
        self.assertEqual(op["currency"], "USD")
        self.assertAlmostEqual(op["pnl_usd"], 50, places=2)            # 500 → 550
        self.assertAlmostEqual(op["pnl_pct_ars"], 65, places=3)       # 550 × 1.500 = 825.000


# ─── El histórico: ventas viejas, corregidas por el botón de Admin ───────────

class Historico(_Base):

    def _gemelas(self, cargar):
        """Dos cuentas con lo mismo: una vende con la regla nueva y la otra con la
        vieja (como las filas de producción). Devuelve (nueva, vieja) uids/headers."""
        nueva = self._cuenta()
        vieja = self._cuenta()
        cargar(nueva[1])
        with _regla_vieja():
            cargar(vieja[1])
        return nueva, vieja

    def _comparar(self, asset, nueva, vieja):
        antes = self._ventas(asset, vieja[1])
        self.assertTrue(all(o["pnl_pct_ars"] is None for o in antes), "no es una fila vieja")
        mirar = self._corregir(apply=False, user_id=vieja[0])
        self.assertFalse(mirar["applied"])
        self.assertEqual(self._ventas(asset, vieja[1]), antes, "mirar escribió algo")
        hecho = self._corregir(apply=True, user_id=vieja[0])
        self.assertEqual(hecho["errores"], [])
        self.assertMismaVenta(self._ventas(asset, nueva[1]), self._ventas(asset, vieja[1]))
        self.assertAlmostEqual(self._mes(nueva[0]), self._mes(vieja[0]), places=2)
        self.assertEqual(self._corregir(apply=True, user_id=vieja[0])["ventas"], 0,
                         "la segunda vez tocó algo")
        return mirar

    def test_venta_en_pesos(self):
        def cargar(h):
            self._alta(h, broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                       entry_date="2024-01-10", currency="ARS")
            self._vender(h, broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                         date="2024-06-10", currency="ARS")
        nueva, vieja = self._gemelas(cargar)
        self.assertAlmostEqual(self._mes(vieja[0]), 160, places=2)    # el número viejo
        mirar = self._comparar("GGAL", nueva, vieja)
        cuenta = mirar["cuentas"][0]
        self.assertAlmostEqual(cuenta["realizado_antes"], 160, places=2)
        self.assertAlmostEqual(cuenta["realizado_despues"], 10, places=2)
        self.assertAlmostEqual(self._mes(vieja[0]), 10, places=2)
        self.assertAlmostEqual(self._mes(vieja[0], PESOS), 10, places=2)

    def test_tc_compra_escrito_y_dos_lotes(self):
        def cargar(h):
            self._alta(h, broker=PESOS, asset="GGAL", quantity=10, buy_price=4500,
                       entry_date="2024-01-10", currency="ARS", tc_compra=1125)
            self._alta(h, broker=PESOS, asset="GGAL", quantity=10, buy_price=5000,
                       entry_date="2024-03-11", currency="ARS")
            self._vender(h, broker=PESOS, asset="GGAL", quantity=15, exit_price=6900,
                         date="2024-06-10", currency="ARS")
        self._comparar("GGAL", *self._gemelas(cargar))

    def test_dolares_y_lote_en_dolares_vendido_en_pesos(self):
        def cargar(h):
            self._alta(h, broker=DOLARES, asset="AAPL", quantity=10, buy_price=100,
                       entry_date="2024-01-10")
            self._vender(h, broker=DOLARES, asset="AAPL", quantity=10, exit_price=150,
                         date="2024-06-10")
            self._alta(h, broker=PESOS, asset="AL30", quantity=100, buy_price=0.5,
                       entry_date="2024-01-10", currency="USD")
            self._vender(h, broker=PESOS, asset="AL30", quantity=100, exit_price=900,
                         date="2024-06-10", currency="ARS")
        nueva, vieja = self._gemelas(cargar)
        self._comparar("AAPL", nueva, vieja)
        self.assertMismaVenta(self._ventas("AL30", nueva[1]), self._ventas("AL30", vieja[1]))

    def test_sin_fecha_de_compra(self):
        # La venta sin fecha de compra se planta con el lote a mano en cada cuenta.
        nueva, vieja = self._cuenta(), self._cuenta()
        for (uid, h), vieja_ in ((nueva, False), (vieja, True)):
            conn = main.get_db()
            conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                       invested, entry_date, commissions, currency)
                   VALUES (?,?,?,0,4500,10,45000,NULL,0,'ARS')""", (uid, PESOS, "GGAL"))
            conn.commit()
            conn.close()
            with (_regla_vieja() if vieja_ else contextlib.nullcontext()):
                self._vender(h, broker=PESOS, asset="GGAL", quantity=10, exit_price=6900,
                             date="2024-06-10", currency="ARS")
        self._comparar("GGAL", nueva, vieja)

    def test_importadas_y_el_rebuild_despues(self):
        def cargar(h):
            self._importar("2024-01-10,COMPRA,Cocos,GGAL,100,4500,450000,,,0,ARS,\n"
                           "2024-06-10,VENTA,Cocos,GGAL,100,6900,690000,,,0,ARS,\n"
                           "2024-01-10,COMPRA,Cocos,AL30,1000,500,500000,,,0,ARS,\n"
                           "2024-06-10,VENTA,Cocos,AL30,1000,0.55,550,,,0,USD,\n", h=h)
        nueva, vieja = self._gemelas(cargar)
        self._comparar("GGAL", nueva, vieja)
        self.assertMismaVenta(self._ventas("AL30", nueva[1]), self._ventas("AL30", vieja[1]))
        # Corregida la cuenta, un rebuild (re-import con una compra más vieja) tiene
        # que escribir lo mismo que el motor en la cuenta gemela.
        for _, h in (nueva, vieja):
            self._importar("2023-12-01,COMPRA,Cocos,GGAL,1,4000,4000,,,0,ARS,\n", h=h)
        self.assertMismaVenta(self._ventas("GGAL", nueva[1]), self._ventas("GGAL", vieja[1]))

    def test_cuenta_v1_no_se_toca_y_queda_pendiente(self):
        vieja = self._cuenta(v1=True)
        with _regla_vieja():
            self._alta(vieja[1], broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                       entry_date="2024-01-10", currency="ARS")
            self._vender(vieja[1], broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                         date="2024-06-10", currency="ARS", tc_venta=1500)
        out = self._corregir(apply=True, user_id=vieja[0])
        self.assertEqual(out["v1_esperan_migracion"], 1)
        self.assertEqual(out["en_esta_tanda"], 0)
        op = self._ventas("GGAL", vieja[1])[0]
        self.assertAlmostEqual(op["pnl_usd"], 160, places=2)
        self.assertIsNone(op["pnl_pct_usd"])
        # Migrada a v2, la misma corrección la toma.
        conn = main.get_db()
        fx.set_fx_version(conn, vieja[0], fx.FX_V2)
        conn.commit()
        conn.close()
        self._corregir(apply=True, user_id=vieja[0])
        self.assertAlmostEqual(self._ventas("GGAL", vieja[1])[0]["pnl_usd"], 10, places=2)


class Tandas(_Base):
    """Sólo cuentas que usaron la app en los últimos 60 días, de a `tanda`."""

    def _vieja_con_venta(self):
        cuenta = self._cuenta()
        with _regla_vieja():
            self._alta(cuenta[1], broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                       entry_date="2024-01-10", currency="ARS")
            self._vender(cuenta[1], broker=PESOS, asset="GGAL", quantity=100,
                         exit_price=6900, date="2024-06-10", currency="ARS")
        return cuenta

    def test_de_a_una_y_nunca_a_los_inactivos(self):
        from datetime import date, timedelta
        hoy = date.today()
        usa_app, entro, inactiva, asesor_activo, cliente = (
            self._vieja_con_venta(), self._vieja_con_venta(), self._vieja_con_venta(),
            self._cuenta(), self._vieja_con_venta())
        conn = main.get_db()
        conn.execute("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,?,1)",
                     (usa_app[0], (hoy - timedelta(days=3)).isoformat(), "pantalla:/posiciones"))
        conn.execute("INSERT INTO login_history (user_id, created_at) VALUES (?,?)",
                     (entro[0], (hoy - timedelta(days=59)).isoformat() + " 10:00:00"))
        conn.execute("INSERT INTO login_history (user_id, created_at) VALUES (?,?)",
                     (inactiva[0], (hoy - timedelta(days=90)).isoformat() + " 10:00:00"))
        conn.execute("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,?,1)",
                     (asesor_activo[0], hoy.isoformat(), "pantalla:/clientes"))
        conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, status) VALUES (?,?,'active')",
                     (asesor_activo[0], cliente[0]))
        conn.commit()
        conn.close()
        mias = {usa_app[0], entro[0], cliente[0]}

        activos = set(resultado_dual.usuarios_activos(main.get_db(), 60))
        self.assertTrue(mias <= activos)
        self.assertNotIn(inactiva[0], activos)

        tocadas = set()
        for _ in range(10):
            out = self._corregir(apply=True, tanda=1)
            self.assertLessEqual(out["en_esta_tanda"], 1)
            tocadas |= {c["user_id"] for c in out["cuentas"]}
            if out["en_esta_tanda"] == 0:
                break
        self.assertTrue(mias <= tocadas, tocadas)
        self.assertNotIn(inactiva[0], tocadas)
        for uid, h in (usa_app, entro, cliente):
            self.assertAlmostEqual(self._ventas("GGAL", h)[0]["pnl_usd"], 10, places=2)
        self.assertAlmostEqual(self._ventas("GGAL", inactiva[1])[0]["pnl_usd"], 160, places=2)


if __name__ == "__main__":
    unittest.main()
