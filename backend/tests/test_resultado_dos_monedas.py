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
        "pnl_pct_ars", "pnl_pct_usd", "pnl_sin_dato", "costo_moneda")

# El dólar de cada día (MEP y blue iguales: la prueba no es sobre el riel).
DOLAR = {"2024-01-10": 1000.0, "2024-03-11": 1200.0, "2024-06-10": 1500.0}
# Días con MEP ≠ blue (el blue apenas por debajo del MEP): la ventana en que, con una comisión de
# compra de 1 %, la reconstrucción elegía el dólar de compra equivocado.
DOLAR_SEPARADO = {"2024-02-05": (1126.83, 1142.83), "2024-04-01": (1200.0, 1200.0)}


def setUpModule():
    conn = main.get_db()
    for fecha, (blue, mep) in DOLAR_SEPARADO.items():
        conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?) "
                     "ON CONFLICT (date) DO UPDATE SET blue_venta=EXCLUDED.blue_venta, "
                     "mep_venta=EXCLUDED.mep_venta", (fecha, blue, mep))
    for fecha, tc in DOLAR.items():
        # ON CONFLICT y no INSERT OR REPLACE: el mismo SQL en SQLite y en Postgres (pgshim
        # rechaza a propósito el segundo). La tabla está vacía al empezar el módulo.
        conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?) "
                     "ON CONFLICT (date) DO UPDATE SET blue_venta=EXCLUDED.blue_venta, "
                     "mep_venta=EXCLUDED.mep_venta", (fecha, tc, tc))
    conn.commit()
    conn.close()


@contextlib.contextmanager
def _regla_vieja():
    """El motor de venta de 73e20fa4: sin el resultado en dos monedas y con `pnl_usd` =
    ganancia en pesos ÷ dólar de la venta. Fabrica filas como las de producción para ese
    motor; NO genera las que tienen `currency` y `fx_to_usd` NULL (anteriores al 28/7) ni
    `fx_to_usd` = 1,0 (el campo TC vacío, antes del 8/9): esas se plantan con un UPDATE
    después de vender (ver `Auditoria`)."""
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

    def _corregir(self, *, apply, user_id=None, tanda=10, dias=60, saltear=()):
        q = f"apply={'true' if apply else 'false'}&tanda={tanda}&dias={dias}"
        if user_id is not None:
            q += f"&user_id={user_id}"
        if saltear:
            q += "&saltear=" + ",".join(str(u) for u in saltear)
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
    """Las cuentas que todavía no pasaron al dólar por fecha: ni la regla ni las columnas."""

    def test_v1_no_escribe_nada_y_queda_pendiente(self):
        self.uid, self.h = self._cuenta(v1=True)
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS", tc_venta=1500)
        op = self._ventas("GGAL")[0]
        self.assertAlmostEqual(op["pnl_usd"], 160, places=2)
        self.assertAlmostEqual(op["pnl_pct"], 53.3333, places=3)
        for c in COLS:
            self.assertIsNone(op[c], c)


class EditarLaVenta(_Base):

    def _venta_y_cuerpo(self, **cambios):
        self._alta(broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("GGAL")[0]
        cuerpo = {"date": op["date"], "broker": op["broker"], "asset": op["asset"],
                  "op_type": "Venta", "entry_price": op["entry_price"],
                  "exit_price": op["exit_price"], "quantity": op["quantity"],
                  "pnl_usd": op["pnl_usd"], "pnl_pct": op["pnl_pct"], "commissions": 0,
                  "currency": "ARS", "fx_to_usd": op["fx_to_usd"]}
        cuerpo.update(cambios)
        r = self.client.put(f"/api/operations/{op['id']}", headers=self.h, json=cuerpo)
        self.assertEqual(r.status_code, 200, r.text)
        return op, self._ventas("GGAL")[0]

    def test_guardar_sin_tocar_deja_la_fila_como_estaba(self):
        antes, despues = self._venta_y_cuerpo()
        for c in COLS + ("pnl_usd", "pnl_pct"):
            self.assertEqual(antes[c], despues[c], c)

    def test_cambiar_el_precio_pasa_a_numeros_del_usuario(self):
        _, op = self._venta_y_cuerpo(exit_price=7200, pnl_usd=15, pnl_pct=6.6667)
        self.assertEqual(op["pnl_sin_dato"], "manual")
        for c in ("costo_ars", "costo_usd", "cobrado_ars", "cobrado_usd", "pnl_pct_ars", "pnl_pct_usd"):
            self.assertIsNone(op[c], c)
        self.assertAlmostEqual(op["pnl_usd"], 15, places=2)      # el que escribió

    def test_una_venta_tipeada_a_mano_es_del_usuario(self):
        r = self.client.post("/api/operations", headers=self.h, json={
            "date": "2024-06-10", "broker": PESOS, "asset": "GGAL", "op_type": "Venta",
            "entry_price": 4500, "exit_price": 6900, "quantity": 100,
            "pnl_usd": 160, "pnl_pct": 53.3, "commissions": 0, "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        op = self._ventas("GGAL")[0]
        self.assertEqual(op["pnl_sin_dato"], "manual")
        self.assertAlmostEqual(op["pnl_usd"], 160, places=2)


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
        # Las filas guardan 2 decimales y el mes acumula sin redondear: centavos de diferencia.
        self.assertAlmostEqual(self._mes(nueva[0]), self._mes(vieja[0]), delta=0.02)
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


class Auditoria(_Base):
    """Los huecos que dejó ver la auditoría del 29/10: el ciclo de vida de una cuenta v1, las
    filas que el usuario editó o con un dólar raro, la tanda con una cuenta que falla, lo
    manual de /mensual y el acceso de un usuario común."""

    _gemelas = Historico._gemelas
    _comparar = Historico._comparar

    def _vieja(self, h=None, **extra):
        """Una venta en pesos con el motor de 73e20fa4 (sin columnas, regla vieja)."""
        cuenta = (self._cuenta() if h is None else None)
        uid, hh = cuenta if cuenta else (None, h)
        with _regla_vieja():
            self._alta(hh, broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                       entry_date="2024-01-10", currency="ARS")
            self._vender(hh, broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                         date="2024-06-10", currency="ARS", **extra)
        return uid, hh

    def _sql(self, sql, params=()):
        conn = main.get_db()
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def test_v1_vende_se_migra_y_la_tanda_la_corrige_igual_que_a_una_v2(self):
        # Vende con el motor NUEVO (sin _regla_vieja) en una cuenta v1...
        uid, h = self._cuenta(v1=True)
        self._alta(h, broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(h, broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS", tc_venta=1500)
        self.assertAlmostEqual(self._ventas("GGAL", h)[0]["pnl_usd"], 160, places=2)
        # ...pasa a v2 y se corre la tanda: tiene que quedar como una venta v2 de entrada.
        conn = main.get_db()
        fx.set_fx_version(conn, uid, fx.FX_V2)
        conn.commit()
        conn.close()
        self._corregir(apply=True, user_id=uid)
        gemela_uid, gemela_h = self._cuenta()
        self._alta(gemela_h, broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(gemela_h, broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS", tc_venta=1500)
        self.assertMismaVenta(self._ventas("GGAL", gemela_h), self._ventas("GGAL", h))
        self.assertAlmostEqual(self._mes(uid), 10, delta=0.02)

    def test_una_venta_editada_antes_de_la_correccion_no_se_pisa(self):
        uid, h = self._vieja()
        # El usuario la había editado: otro P&L y otro %, que ya no cierran con los precios.
        self._sql("UPDATE operations SET pnl_usd=999, pnl_pct=11.11 WHERE user_id=?", (uid,))
        self._corregir(apply=True, user_id=uid)
        op = self._ventas("GGAL", h)[0]
        self.assertEqual(op["pnl_sin_dato"], "no_cierra")
        self.assertAlmostEqual(op["pnl_usd"], 999, places=2)
        self.assertAlmostEqual(op["pnl_pct"], 11.11, places=2)

    def test_un_dolar_estampado_raro_no_fabrica_ganancias(self):
        # El campo TC vacío estampaba 1,0 y el P&L quedaba en pesos (240.000).
        uid, h = self._vieja()
        self._sql("UPDATE operations SET fx_to_usd=1.0, pnl_usd=240000 WHERE user_id=?", (uid,))
        self._corregir(apply=True, user_id=uid)
        op = self._ventas("GGAL", h)[0]
        self.assertAlmostEqual(op["pnl_usd"], 10, places=2)          # cobrado al dólar de su fecha
        self.assertAlmostEqual(op["pnl_pct"], 2.2222, places=3)

    def test_lote_en_dolares_vendido_en_pesos_sin_foto_no_invierte_el_signo(self):
        # Ventas anteriores al 9/10: sin undo_meta_json. AL30 US$50 → vendido por US$60.
        uid, h = self._cuenta()
        with _regla_vieja():
            self._alta(h, broker=PESOS, asset="AL30", quantity=100, buy_price=0.5,
                       entry_date="2024-01-10", currency="USD")
            self._vender(h, broker=PESOS, asset="AL30", quantity=100, exit_price=900,
                         date="2024-06-10", currency="ARS")
        self._sql("UPDATE operations SET undo_meta_json=NULL WHERE user_id=?", (uid,))
        self._corregir(apply=True, user_id=uid)
        op = self._ventas("AL30", h)[0]
        self.assertAlmostEqual(op["pnl_usd"], 10, places=2)          # no −15
        self.assertAlmostEqual(op["costo_usd"], 50, places=3)
        self.assertAlmostEqual(op["pnl_pct_ars"], 80, places=2)

    def test_una_venta_sin_foto_ni_nada_que_la_valide_no_se_toca(self):
        uid, h = self._vieja()
        self._sql("UPDATE operations SET undo_meta_json=NULL, entry_price=NULL WHERE user_id=?", (uid,))
        self._corregir(apply=True, user_id=uid)
        op = self._ventas("GGAL", h)[0]
        self.assertEqual(op["pnl_sin_dato"], "moneda_del_lote")
        self.assertAlmostEqual(op["pnl_usd"], 160, places=2)

    def test_lo_cargado_a_mano_en_mensual_sobrevive_a_la_tanda(self):
        uid, h = self._vieja()
        self._sql("INSERT INTO monthly_entries (user_id, year, month, broker, deposits, withdrawals, "
                  "pnl_realized, pnl_unrealized, capital_inicio, capital_final) "
                  "VALUES (?,2023,5,?,0,0,500,0,1000,1500)", (uid, PESOS))
        self._corregir(apply=True, user_id=uid)
        self.assertAlmostEqual(self._mes(uid, PESOS, 2023, 5), 500, places=2)   # no se recalcula entero
        self.assertAlmostEqual(self._mes(uid, PESOS, 2024, 6), 10, delta=0.02)

    def test_una_venta_sin_precio_ni_cantidad_no_traba_la_cola(self):
        uid_solo, h_solo = self._cuenta()
        r = self.client.post("/api/operations", headers=h_solo, json={
            "date": "2024-06-10", "broker": PESOS, "asset": "GGAL", "op_type": "Venta",
            "pnl_usd": 50, "commissions": 0})
        self.assertEqual(r.status_code, 200, r.text)
        uid, h = self._vieja()
        self._sql("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?, date('now'), 'x', 1)", (uid_solo,))
        self._sql("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?, date('now'), 'x', 1)", (uid,))
        out = self._corregir(apply=True, tanda=5)
        self.assertEqual(out["con_error"], 0)
        self.assertAlmostEqual(self._ventas("GGAL", h)[0]["pnl_usd"], 10, places=2)
        self.assertAlmostEqual(self._ventas("GGAL", h_solo)[0]["pnl_usd"], 50, places=2)   # intacta
        self.assertEqual(self._corregir(apply=False, tanda=5)["con_ventas_pendientes"], 0)

    def test_una_cuenta_que_falla_no_traba_las_siguientes(self):
        cuentas = [self._vieja() for _ in range(3)]
        for uid, _h in cuentas:
            self._sql("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?, date('now'), 'x', 1)", (uid,))
        rota = cuentas[0][0]
        real = resultado_dual.corregir_usuario

        def _falla_la_primera(conn, uid, **kw):
            if uid == rota:
                raise RuntimeError("boom")
            return real(conn, uid, **kw)
        with mock.patch.object(resultado_dual, "corregir_usuario", _falla_la_primera):
            primera = self._corregir(apply=True, tanda=1)
            self.assertEqual((primera["corregidas"], primera["con_error"]), (0, 1))
            self.assertEqual(primera["quedan_despues"], 3)               # lo hecho, no lo intentado
            segunda = self._corregir(apply=True, tanda=1, saltear=[rota])
            self.assertEqual((segunda["corregidas"], segunda["con_error"]), (1, 0))
        pnl = [self._ventas("GGAL", h)[0]["pnl_usd"] for _u, h in cuentas]
        self.assertAlmostEqual(pnl[0], 160, places=2)                    # la que falló, intacta
        self.assertEqual(sum(1 for v in pnl[1:] if abs(v - 10) < 0.01), 1)

    def test_importada_con_comision_y_blue_apenas_bajo_el_mep_queda_igual_que_la_gemela(self):
        # Lote en pesos con comisión de compra del 1 % vendido en dólares (dólar MEP). El nominal
        # sin comisión hacía ganar al blue (apenas por debajo del MEP) y una pérdida pasaba a ganancia.
        def cargar(h):
            self._importar("2024-02-05,COMPRA,Cocos,AL30,1000,500,500000,,,5000,ARS,\n"
                           "2024-04-01,VENTA,Cocos,AL30,1000,0.4375,437.5,,,0,USD,\n", h=h)
        nueva, vieja = self._gemelas(cargar)
        self.assertLess(self._ventas("AL30", nueva[1])[0]["pnl_usd"], 0)
        self._comparar("AL30", nueva, vieja)

    def test_sin_foto_ni_archivo_y_con_dos_dolares_posibles_no_se_adivina(self):
        # Venta a mano anterior al 9/10 (sin foto) con MEP y blue apenas distintos: la comisión de
        # compra no está en ningún lado, así que no hay forma de saber con cuál se costeó.
        uid, h = self._cuenta()
        with _regla_vieja():
            self._alta(h, broker=PESOS, asset="AL30", quantity=1000, buy_price=500,
                       commissions=5000, entry_date="2024-02-05", currency="ARS")
            self._vender(h, broker=PESOS, asset="AL30", quantity=1000, exit_price=0.4375,
                         date="2024-04-01", currency="USD")
        self._sql("UPDATE operations SET undo_meta_json=NULL WHERE user_id=?", (uid,))
        antes = self._ventas("AL30", h)[0]
        self._corregir(apply=True, user_id=uid)
        op = self._ventas("AL30", h)[0]
        self.assertEqual(op["pnl_sin_dato"], "no_cierra")
        self.assertAlmostEqual(op["pnl_usd"], antes["pnl_usd"], places=2)

    def test_lote_en_pesos_vendido_en_dolares_con_la_cantidad_editada_no_se_toca(self):
        uid, h = self._cuenta()
        with _regla_vieja():
            self._alta(h, broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                       entry_date="2024-01-10", currency="ARS")
            self._vender(h, broker=PESOS, asset="GGAL", quantity=100, exit_price=4.6,
                         date="2024-06-10", currency="USD")
        self._sql("UPDATE operations SET quantity=50 WHERE user_id=?", (uid,))
        self._corregir(apply=True, user_id=uid)
        op = self._ventas("GGAL", h)[0]
        self.assertEqual(op["pnl_sin_dato"], "no_cierra")
        self.assertAlmostEqual(op["pnl_usd"], 10, places=2)          # el que había, intacto

    def test_guardar_sin_tocar_una_venta_vieja_sin_moneda_no_la_marca_manual(self):
        uid, h = self._vieja()
        self._sql("UPDATE operations SET currency=NULL WHERE user_id=?", (uid,))   # anterior al 28/7
        op = self.client.get("/api/operations", headers=h).json()[0]
        cuerpo = {k: op[k] for k in ("date", "broker", "asset", "op_type", "entry_price", "exit_price",
                                     "quantity", "pnl_usd", "pnl_pct", "commissions", "currency", "fx_to_usd")}
        self.assertIsNone(cuerpo["currency"])
        r = self.client.put(f"/api/operations/{op['id']}", headers=h, json=cuerpo)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self._ventas("GGAL", h)[0]["pnl_sin_dato"])
        self._corregir(apply=True, user_id=uid)
        self.assertAlmostEqual(self._ventas("GGAL", h)[0]["pnl_usd"], 10, places=2)

    def test_un_usuario_comun_no_puede_correrlo(self):
        r = self.client.post("/api/admin/resultado-dos-monedas?apply=false", headers=self.h)
        self.assertEqual(r.status_code, 403, r.text)

    def test_las_ventas_ya_corregidas_no_se_vuelven_a_tocar(self):
        uid, h = self._vieja()
        self._corregir(apply=True, user_id=uid)
        antes = self._ventas("GGAL", h)
        self.assertEqual(self._corregir(apply=True, user_id=uid)["ventas"], 0)
        self.assertEqual(self._ventas("GGAL", h), antes)


# ─── El realizado EN PESOS: una sola cuenta para todas las pantallas ─────────────────────────

class RealizadoEnPesosEnTodasLasPantallas(_Base):
    """Nico, 29/10: Reportes y el Resumen mensual en Pesos tienen que mostrar el resultado EXACTO
    en pesos (pesos de venta − pesos de compra), igual que Movimientos, para que coincida con el
    broker. GGAL comprada a $4.500 con el dólar en 1.000 y vendida a $6.900 con el dólar en 1.500
    dejó +$240.000 (y +US$10): US$10 × 1.500 daban $15.000 en Reportes.

    La cuenta vive en `resultado_dual.resultado_en_pesos`/`realizado_en_pesos`. Acá se mira que
    CADA pantalla la lea por su puerta real (operaciones, movimientos, el mes, el reporte del
    período, «Última op cerrada», el CSV del contador) y dé el MISMO número."""

    # Las dos columnas que el CSV mensual trae al final (backend/main.py, export_monthly_csv).
    COL_PESOS = "P&L realizado en pesos (ventas en pesos — lo comprado o vendido en dólares, al dólar de cada fecha)"
    COL_VALUADO = "El P&L en pesos incluye compras o ventas en dólares valuadas"
    # La del CSV de operaciones (al final, igual que las del mensual).
    COL_TIPO = "Tipo de resultado en pesos (exacto o valuado al dólar de cada fecha)"

    def _plantar(self, sql, params=()):
        conn = main.get_db()
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def _csv_mensual(self, h=None):
        import csv
        self._plantar("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))
        r = self.client.get("/api/export/monthly.csv", headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))

    def _ggal(self, h=None):
        self._alta(h, broker=PESOS, asset="GGAL", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(h, broker=PESOS, asset="GGAL", quantity=100, exit_price=6900,
                     date="2024-06-10", currency="ARS")

    def _fila_mensual(self, h=None, broker="global"):
        filas = self.client.get("/api/monthly", headers=h or self.h).json()
        return [m for m in filas if m["broker"] == broker and (m["year"], m["month"]) == (2024, 6)][0]

    def _reporte(self, h=None, broker="global"):
        with mock.patch.object(main, "_tiene_reportes_historicos", lambda *a, **k: True), \
                mock.patch.object(main, "_bench_para_reportes", lambda *a, **k: {}):
            r = self.client.get("/api/reports/period/month/2024-06", headers=h or self.h,
                                params={"moneda": "ars", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["metrics"]

    def _ultima_op(self, uid):
        conn = main.get_db()
        try:
            return main._portfolio_snapshot_summary(conn, uid, "global")["last_op"]
        finally:
            conn.close()

    # ── el caso de siempre ──
    def test_ggal_da_240_mil_en_las_cinco_pantallas(self):
        self._ggal()
        op = self._ventas("GGAL")[0]
        self.assertEqual(op["resultado_ars"], 240000)                       # Operaciones
        self.assertEqual(op["resultado_ars_tipo"], "exacto")
        mov = [m for m in self.client.get("/api/movements", headers=self.h).json()
               if m.get("type") == "SELL" and m.get("asset") == "GGAL"][0]
        self.assertEqual(mov["resultado_ars"], 240000)                      # Todos los movimientos
        for broker in ("global", PESOS):
            mes = self._fila_mensual(broker=broker)                          # Resumen mensual / Dashboard
            self.assertAlmostEqual(mes["realized_ars"], 240000, places=2)
            self.assertAlmostEqual(mes["realized_ars_cubre_usd"], 10, places=2)
            self.assertAlmostEqual(mes["pnl_realized"], 10, places=2)
            rep = self._reporte(broker=broker)                               # Reportes
            self.assertAlmostEqual(rep["realized_ars"], 240000, places=2)
            self.assertAlmostEqual(rep["realized_ars_cubre_usd"], 10, places=2)
            self.assertAlmostEqual(rep["realized_pnl"], 10, places=2)
            self.assertFalse(rep["realized_ars_valuado"])
        self.assertEqual(self._ultima_op(self.uid)["resultado_ars"], 240000)  # Última op cerrada

    def test_el_csv_del_contador_dice_lo_mismo(self):
        import csv
        self._ggal()
        self._plantar("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))   # el CSV es de planes pagos
        r = self.client.get("/api/export/operations.csv", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
        venta = [f for f in filas if f.get("Activo") == "GGAL" or f.get("asset") == "GGAL"][0]
        self.assertAlmostEqual(float(str(venta["Resultado en pesos"]).replace(",", ".")), 240000, places=1)

    # ── los casos raros ──
    def test_venta_en_dolares_se_dice_valuada_y_suma_lo_que_cartera_en_pesos(self):
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100, entry_date="2024-01-10")
        self._vender(broker=DOLARES, asset="AAPL", quantity=10, exit_price=150, date="2024-06-10")
        op = self._ventas("AAPL")[0]
        self.assertEqual(op["resultado_ars_tipo"], "valuado")
        self.assertAlmostEqual(op["resultado_ars"], 2250000 - 1000000, places=2)
        mes = self._fila_mensual(broker=DOLARES)
        self.assertTrue(mes["realized_ars_valuado"])
        self.assertAlmostEqual(mes["realized_ars_cubre_usd"], 500, places=2)
        self.assertTrue(self._reporte(broker=DOLARES)["realized_ars_valuado"])

    def test_un_dividendo_en_dolares_no_tiene_pesos_y_queda_para_convertir(self):
        self._ggal()
        r = self.client.post("/api/operations", headers=self.h, json={
            "date": "2024-06-12", "broker": DOLARES, "asset": "KO", "op_type": "Dividendo",
            "quantity": 1, "entry_price": 0, "exit_price": 0, "pnl_usd": 20, "pnl_pct": 0,
            "commissions": 0, "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        div = [o for o in self.client.get("/api/operations", headers=self.h).json()
               if o["op_type"] == "Dividendo"][0]
        self.assertIsNone(div["resultado_ars"])
        rep = self._reporte()
        # 240.000 de las ventas en pesos + los US$ 20 del dividendo, que la pantalla convierte.
        self.assertAlmostEqual(rep["realized_pnl"], 30, places=2)
        self.assertAlmostEqual(rep["realized_ars"], 240000, places=2)
        self.assertAlmostEqual(rep["realized_pnl"] - rep["realized_ars_cubre_usd"], 20, places=2)
        mes = self._fila_mensual()
        self.assertAlmostEqual(mes["pnl_realized"] - mes["realized_ars_cubre_usd"], 20, places=2)

    def test_un_cupon_en_pesos_es_exacto(self):
        self._ggal()
        self._plantar(
            "INSERT INTO operations (user_id, date, broker, asset, op_type, quantity, entry_price, "
            "exit_price, pnl_usd, pnl_pct, commissions, currency, fx_to_usd) "
            "VALUES (?, '2024-06-12', ?, 'AL30', 'Cupón', 1, 0, 0, 125000, 0, 0, 'ARS', 1000)",
            (self.uid, PESOS))
        cupon = [o for o in self.client.get("/api/operations", headers=self.h).json()
                 if o["op_type"] == "Cupón"][0]
        self.assertEqual(cupon["resultado_ars"], 125000)
        self.assertEqual(cupon["resultado_ars_tipo"], "exacto")
        rep = self._reporte()
        self.assertAlmostEqual(rep["realized_pnl"], 10 + 125, places=2)       # 125.000 ÷ 1.000, como siempre
        self.assertAlmostEqual(rep["realized_ars"], 240000 + 125000, places=2)
        self.assertAlmostEqual(rep["realized_pnl"] - rep["realized_ars_cubre_usd"], 0, places=2)

    def test_una_venta_vieja_en_pesos_sin_columnas_usa_su_dolar_estampado(self):
        uid, h = Auditoria._vieja(self)
        op = self._ventas("GGAL", h)[0]
        self.assertIsNone(op["costo_ars"])                                    # regla vieja: sin columnas
        self.assertAlmostEqual(op["pnl_usd"], 160, places=2)
        self.assertAlmostEqual(op["resultado_ars"], 240000, delta=1)          # 160 × 1.500, el pesos de entonces
        rep = self._reporte(h)
        self.assertAlmostEqual(rep["realized_ars"], 240000, delta=1)
        self.assertAlmostEqual(rep["realized_ars_cubre_usd"], 160, places=2)

    def test_lo_que_no_se_puede_saber_no_se_inventa(self):
        """Una venta en dólares vieja (sin las columnas), sin dólar estampado: no hay pesos
        honestos. La cuenta devuelve None y el resto lo resuelve la pantalla, avisando."""
        sin_columnas_usd = {"op_type": "Venta", "currency": "USD", "pnl_usd": 500, "fx_to_usd": None}
        self.assertEqual(resultado_dual.resultado_en_pesos(sin_columnas_usd), (None, None))
        sin_dolar = {"op_type": "Venta", "currency": "ARS", "pnl_usd": 160, "fx_to_usd": None}
        self.assertEqual(resultado_dual.resultado_en_pesos(sin_dolar), (None, None))
        self.assertEqual(resultado_dual.resultado_en_pesos(
            {"op_type": "Cupón", "currency": "USD", "pnl_usd": 20, "fx_to_usd": None}), (None, None))
        self.assertEqual(resultado_dual.resultado_en_pesos(
            {"op_type": "Dividendo", "currency": "ARS", "pnl_usd": 20, "fx_to_usd": 1000}), (None, None))
        self.assertEqual(resultado_dual.resultado_en_pesos({"op_type": "Compra", "pnl_usd": 1}), (None, None))
        # …y el resumen suma sólo lo que tiene, devolviendo los dólares que cubre
        self.assertEqual(resultado_dual.realizado_en_pesos([sin_columnas_usd, sin_dolar]), (0.0, 0.0, False))

    def test_lote_en_dolares_vendido_en_pesos_se_dice_valuado(self):
        """AL30 comprado en dólares (100 × US$ 0,5 con el dólar en 1.000 = $ 50.000 de entonces) y
        vendido en pesos por $ 90.000: la venta SÍ entró en pesos, pero el costo en pesos no es plata
        que se haya pagado: son dólares al dólar de la compra. Se muestra +$ 40.000, y se dice que es
        valuado, no que es el resultado exacto del broker."""
        self._alta(broker=PESOS, asset="AL30", quantity=100, buy_price=0.5,
                   entry_date="2024-01-10", currency="USD")
        self._vender(broker=PESOS, asset="AL30", quantity=100, exit_price=900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("AL30")[0]
        self.assertEqual(op["costo_moneda"], "USD")
        self.assertAlmostEqual(op["resultado_ars"], 40000, places=2)
        self.assertEqual(op["resultado_ars_tipo"], "valuado")
        rep = self._reporte()
        self.assertAlmostEqual(rep["realized_ars"], 40000, places=2)
        self.assertAlmostEqual(rep["realized_ars_cubre_usd"], op["pnl_usd"], places=2)
        self.assertTrue(rep["realized_ars_valuado"])
        self.assertTrue(self._fila_mensual()["realized_ars_valuado"])

    def test_un_lote_en_pesos_vendido_en_pesos_es_exacto(self):
        self._ggal()
        op = self._ventas("GGAL")[0]
        self.assertEqual(op["costo_moneda"], "ARS")
        self.assertEqual(op["resultado_ars_tipo"], "exacto")
        self.assertFalse(self._reporte()["realized_ars_valuado"])

    def test_una_venta_en_dolares_de_un_lote_en_pesos_es_valuada(self):
        self._alta(broker=DOLARES, asset="GGAL", quantity=10, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=DOLARES, asset="GGAL", quantity=10, exit_price=5, date="2024-06-10",
                     currency="USD")
        op = self._ventas("GGAL")[0]
        self.assertEqual(op["resultado_ars_tipo"], "valuado")

    def test_el_total_cierra_sumando_las_partes(self):
        """Pesos exactos + (dólares totales − dólares que ya tienen pesos) × dólar = lo que se
        muestra. Con una venta en pesos, una en dólares y un dividendo, ninguna plata se cuenta
        dos veces ni se pierde."""
        self._ggal()
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100, entry_date="2024-01-10")
        self._vender(broker=DOLARES, asset="AAPL", quantity=10, exit_price=150, date="2024-06-10")
        self.client.post("/api/operations", headers=self.h, json={
            "date": "2024-06-12", "broker": DOLARES, "asset": "KO", "op_type": "Dividendo",
            "quantity": 1, "entry_price": 0, "exit_price": 0, "pnl_usd": 20, "pnl_pct": 0,
            "commissions": 0, "currency": "USD"})
        rep = self._reporte()
        self.assertAlmostEqual(rep["realized_pnl"], 10 + 500 + 20, places=2)
        resto = rep["realized_pnl"] - rep["realized_ars_cubre_usd"]
        self.assertAlmostEqual(resto, 20, places=2)                           # sólo el dividendo
        total_pesos = rep["realized_ars"] + resto * 1500
        self.assertAlmostEqual(total_pesos, 240000 + 1250000 + 20 * 1500, places=2)
        # el mes dice lo mismo que el reporte
        mes = self._fila_mensual()
        self.assertAlmostEqual(mes["realized_ars"], rep["realized_ars"], places=2)
        self.assertAlmostEqual(mes["realized_ars_cubre_usd"], rep["realized_ars_cubre_usd"], places=2)


    # ── La auditoría del 30/10: lo que la cuenta NO puede afirmar como exacto ──
    def _vaciar_columnas(self, asset, uid=None, **extra):
        """La fila como la dejaban los motores anteriores: sin ninguna de las columnas nuevas."""
        sets = ", ".join(f"{c}=NULL" for c in COLS)
        for k in extra:
            sets += f", {k}=?"
        self._plantar(f"UPDATE operations SET {sets} WHERE user_id=? AND asset=? AND op_type='Venta'",
                      (*extra.values(), uid or self.uid, asset))

    def test_editar_una_venta_no_deja_un_exacto_falso(self):
        """El formulario de edición reenvía `pnl_usd` (US$ 10, de la regla nueva) y `al_editar` vacía
        las columnas: sin ellas la cuenta tomaba US$ 10 × 1.500 = $15.000 como si fueran los pesos
        del broker. Una fila editada a mano es del usuario: no hay forma honesta de saber sus pesos,
        la cuenta dice None y la pantalla convierte ese resto AVISANDO."""
        self._ggal()
        op = self._ventas("GGAL")[0]
        self.assertEqual(op["resultado_ars"], 240000)                       # antes de editar
        cuerpo = {k: op.get(k) for k in ("date", "broker", "asset", "op_type", "entry_price", "exit_price",
                                         "quantity", "pnl_usd", "pnl_pct", "currency", "fx_to_usd")}
        cuerpo["commissions"] = 500
        r = self.client.put(f"/api/operations/{op['id']}", headers=self.h, json=cuerpo)
        self.assertEqual(r.status_code, 200, r.text)
        editada = self._ventas("GGAL")[0]
        self.assertEqual(editada["pnl_sin_dato"], "manual")
        self.assertIsNone(editada["resultado_ars"])                          # Operaciones
        self.assertIsNone(editada["resultado_ars_tipo"])
        mov = [m for m in self.client.get("/api/movements", headers=self.h).json()
               if m.get("type") == "SELL" and m.get("asset") == "GGAL"][0]
        self.assertIsNone(mov["resultado_ars"])                              # Movimientos
        for broker in ("global", PESOS):
            mes = self._fila_mensual(broker=broker)                          # el mes: no cubre nada
            self.assertAlmostEqual(mes["realized_ars"], 0, places=2)
            self.assertAlmostEqual(mes["realized_ars_cubre_usd"], 0, places=2)
            self.assertAlmostEqual(mes["pnl_realized"], 10, places=2)        # …y el resto lo convierte la pantalla
            rep = self._reporte(broker=broker)                               # Reportes
            self.assertAlmostEqual(rep["realized_ars"], 0, places=2)
            self.assertAlmostEqual(rep["realized_ars_cubre_usd"], 0, places=2)
            self.assertAlmostEqual(rep["realized_pnl"], 10, places=2)
        self.assertIsNone(self._ultima_op(self.uid)["resultado_ars"])        # Última op cerrada

    def test_un_dolar_estampado_de_uno_no_son_pesos(self):
        """El TC vacío (29/7 al 8/9) dividía por el dólar de la fecha y estampaba `fx_to_usd` = 1,0.
        `pnl_usd` (160) × 1,0 daba $160 «exactos» donde la venta fue de $240.000."""
        self._ggal()
        self._vaciar_columnas("GGAL", fx_to_usd=1.0, pnl_usd=160)
        op = self._ventas("GGAL")[0]
        self.assertIsNone(op["resultado_ars"])
        mes = self._fila_mensual()
        self.assertAlmostEqual(mes["realized_ars"], 0, places=2)
        self.assertAlmostEqual(mes["realized_ars_cubre_usd"], 0, places=2)
        # (`monthly_entries` no se recalcula al plantar la fila a mano: los 160 dólares se ven en el reporte)
        rep = self._reporte()
        self.assertAlmostEqual(rep["realized_ars"], 0, places=2)
        self.assertAlmostEqual(rep["realized_pnl"] - rep["realized_ars_cubre_usd"], 160, places=2)

    def test_un_lote_en_dolares_sin_dolar_de_compra_es_valuado_nunca_exacto(self):
        """AL30 pagado en dólares cuya fecha de compra no tiene dólar guardado: `costo_ars` queda
        vacío y la fila caía a `pnl_usd × dólar`: $15.000 «exactos» sin la nota, mientras la misma
        venta con dólar de compra da $40.000 «valuado»."""
        self._alta(broker=PESOS, asset="AL30", quantity=100, buy_price=0.5,
                   entry_date="1999-01-05", currency="USD")
        self._vender(broker=PESOS, asset="AL30", quantity=100, exit_price=900,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("AL30")[0]
        self.assertIsNone(op["costo_ars"])                                    # no hay dólar de compra
        self.assertEqual(op["costo_moneda"], "USD")
        self.assertEqual(op["resultado_ars_tipo"], "valuado")
        self.assertTrue(self._reporte()["realized_ars_valuado"])
        self.assertTrue(self._fila_mensual()["realized_ars_valuado"])

    def test_una_perdida_conserva_su_signo_en_pesos_y_en_lo_que_cubre(self):
        """Comprada a $4.500 y vendida a $4.000: −$50.000. Lo que la cuenta cubre en dólares es
        −US$ 183,33 (con su signo): con valor absoluto el resto en dólares daba −US$ 366 y la
        pantalla sumaba una pérdida fantasma encima."""
        self._alta(broker=PESOS, asset="YPFD", quantity=100, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="YPFD", quantity=100, exit_price=4000,
                     date="2024-06-10", currency="ARS")
        op = self._ventas("YPFD")[0]
        self.assertEqual(op["resultado_ars"], -50000)
        rep = self._reporte()
        self.assertAlmostEqual(rep["realized_ars"], -50000, places=2)
        self.assertAlmostEqual(rep["realized_ars_cubre_usd"], op["pnl_usd"], places=2)
        self.assertLess(rep["realized_ars_cubre_usd"], 0)
        self.assertAlmostEqual(rep["realized_pnl"] - rep["realized_ars_cubre_usd"], 0, places=2)

    def test_cada_mes_tiene_su_suma(self):
        """Una venta en marzo y otra en junio: cada mes (y el global, que las junta) con SU número.
        Agrupar por año o por broker solo daría a marzo y a junio lo mismo."""
        self._ggal()                                                          # junio: +$240.000
        self._alta(broker=PESOS, asset="YPFD", quantity=10, buy_price=4500,
                   entry_date="2024-01-10", currency="ARS")
        self._vender(broker=PESOS, asset="YPFD", quantity=10, exit_price=6000,
                     date="2024-03-11", currency="ARS")                       # marzo: +$15.000
        filas = {(m["broker"], m["month"]): m for m in self.client.get("/api/monthly", headers=self.h).json()
                 if m["year"] == 2024}
        self.assertAlmostEqual(filas[("global", 3)]["realized_ars"], 15000, places=2)
        self.assertAlmostEqual(filas[("global", 6)]["realized_ars"], 240000, places=2)
        self.assertAlmostEqual(filas[(PESOS, 3)]["realized_ars"], 15000, places=2)
        self.assertAlmostEqual(filas[(PESOS, 6)]["realized_ars"], 240000, places=2)
        # marzo: US$ 60.000 ÷ 1.200 = 50 cobrados − US$ 45 de costo (4.500 × 10 ÷ 1.000) = +US$ 5
        self.assertAlmostEqual(filas[("global", 3)]["realized_ars_cubre_usd"], 5, places=2)
        self.assertAlmostEqual(filas[("global", 6)]["realized_ars_cubre_usd"], 10, places=2)

    def test_cupon_amortizacion_e_interes_en_pesos_por_la_ruta_real(self):
        """El cobro se carga por la puerta de la app (con su recálculo del mes), no por SQL: el mes
        tiene que traer sus pesos exactos y los dólares que cubre."""
        self._ggal()
        for i, tipo in enumerate(("Cupón", "Amortización", "Interés PF")):
            r = self.client.post("/api/operations", headers=self.h, json={
                "date": f"2024-06-{12 + i}", "broker": PESOS, "asset": "AL30", "op_type": tipo,
                "quantity": 1, "entry_price": 0, "exit_price": 0, "pnl_usd": 125000, "pnl_pct": 0,
                "commissions": 0, "currency": "ARS", "fx_to_usd": 1000})
            self.assertEqual(r.status_code, 200, r.text)
        cobros = [o for o in self.client.get("/api/operations", headers=self.h).json()
                  if o["op_type"] in ("Cupón", "Amortización", "Interés PF")]
        self.assertEqual(len(cobros), 3)
        self.assertEqual({o["resultado_ars"] for o in cobros}, {125000})
        mes = self._fila_mensual()
        self.assertAlmostEqual(mes["realized_ars"], 240000 + 3 * 125000, places=2)
        self.assertAlmostEqual(mes["realized_ars_cubre_usd"], 10 + 3 * 125, places=2)
        self.assertAlmostEqual(mes["pnl_realized"] - mes["realized_ars_cubre_usd"], 0, places=2)
        # «Última op cerrada» con un cupón: sus pesos (no los 125 dólares ni 125 pesos)
        ultima = self._ultima_op(self.uid)
        self.assertEqual(ultima["resultado_ars"], 125000)
        self.assertAlmostEqual(ultima["pnl_usd"], 125, places=2)

    def test_la_cuenta_nunca_dice_exacto_cuando_no_lo_es(self):
        """Todas las combinaciones de moneda de la venta, moneda del lote, columnas, edición a mano y
        dólar estampado. Reglas: 'exacto' exige venta en pesos, lote que no se pagó en dólares y
        — sin las columnas — un dólar estampado de verdad y una fila que no sea del usuario."""
        import itertools
        n_exacto = 0
        for mon, lote, cols, manual, fx in itertools.product(
                ("ARS", "USD", None), ("ARS", "USD", None), (True, False), (True, False), (1500.0, 1.0, None)):
            op = {"op_type": "Venta", "currency": mon, "costo_moneda": lote, "pnl_usd": 10.0,
                  "fx_to_usd": fx, "pnl_sin_dato": "manual" if manual else None}
            if cols:
                op.update(cobrado_ars=690000.0, costo_ars=450000.0)
            pesos, tipo = resultado_dual.resultado_en_pesos(op)
            msg = f"{op}"
            self.assertEqual(pesos is None, tipo is None, msg)
            if tipo == resultado_dual.EXACTO:
                n_exacto += 1
                self.assertNotEqual(lote, "USD", msg)
                if cols:
                    self.assertNotEqual(mon, "USD", msg)
                else:
                    self.assertEqual(mon, "ARS", msg)
                    self.assertTrue(fx and fx > 1.0, msg)
                    self.assertFalse(manual, msg)
            if (mon == "USD" or lote == "USD") and cols:
                self.assertEqual(tipo, resultado_dual.VALUADO, msg)
        self.assertGreater(n_exacto, 0)                                       # la matriz no es vacía de exactos

    def test_cada_guarda_de_la_cuenta_corta_por_su_cuenta(self):
        """Los guards de moneda y de dólar se prueban uno por vez: cada uno tapaba al otro."""
        venta = {"op_type": "Venta", "pnl_usd": 10.0}
        self.assertEqual(resultado_dual.resultado_en_pesos({**venta, "currency": "ARS", "fx_to_usd": 1500.0}),
                         (15000.0, "exacto"))
        self.assertEqual(resultado_dual.resultado_en_pesos({**venta, "currency": "USD", "fx_to_usd": 1500.0}),
                         (None, None))                                        # sólo la moneda
        self.assertEqual(resultado_dual.resultado_en_pesos({**venta, "currency": None, "fx_to_usd": 1500.0}),
                         (None, None))
        self.assertEqual(resultado_dual.resultado_en_pesos({**venta, "currency": "ARS", "fx_to_usd": None}),
                         (None, None))                                        # sólo el dólar
        self.assertEqual(resultado_dual.resultado_en_pesos({**venta, "currency": "ARS", "fx_to_usd": 1.0}),
                         (None, None))
        # sin resultado guardado (venta cargada sin costo): sin dato, no un error (`float(None)`)
        self.assertEqual(resultado_dual.resultado_en_pesos(
            {"op_type": "Venta", "currency": "ARS", "fx_to_usd": 1500.0, "pnl_usd": None}), (None, None))
        self.assertEqual(resultado_dual.resultado_en_pesos(
            {"op_type": "Cupón", "currency": "ARS", "fx_to_usd": 1000.0, "pnl_usd": None}), (None, None))
        self.assertEqual(resultado_dual.resultado_en_pesos(
            {"op_type": "Venta", "currency": "ARS", "fx_to_usd": 1500.0, "pnl_usd": 0}), (0.0, "exacto"))
        cupon = {"op_type": "Cupón", "pnl_usd": 125000.0}
        self.assertEqual(resultado_dual.resultado_en_pesos({**cupon, "currency": "ARS", "fx_to_usd": 1000.0}),
                         (125000.0, "exacto"))
        self.assertEqual(resultado_dual.resultado_en_pesos({**cupon, "currency": "USD", "fx_to_usd": 1000.0}),
                         (None, None))
        self.assertEqual(resultado_dual.resultado_en_pesos({**cupon, "currency": "ARS", "fx_to_usd": None}),
                         (None, None))

    def test_las_filas_historicas_de_la_cuenta(self):
        """Filas de antes del `costo_moneda`, o con una sola de las dos columnas en pesos."""
        base = {"op_type": "Venta", "currency": "ARS", "fx_to_usd": 1500.0, "pnl_usd": 10.0}
        # con las dos columnas pero sin `costo_moneda` (corrección anterior a esa columna): se toma la de la venta
        self.assertEqual(resultado_dual.resultado_en_pesos({**base, "cobrado_ars": 690000.0, "costo_ars": 450000.0}),
                         (240000.0, "exacto"))
        self.assertEqual(resultado_dual.resultado_en_pesos(
            {**base, "currency": "USD", "cobrado_ars": 690000.0, "costo_ars": 450000.0}), (240000.0, "valuado"))
        # sólo `cobrado_ars` (el lote no tiene dólar de compra): cae a la venta vieja, con su dólar estampado
        self.assertEqual(resultado_dual.resultado_en_pesos({**base, "cobrado_ars": 690000.0}), (15000.0, "exacto"))
        self.assertEqual(resultado_dual.resultado_en_pesos({**base, "cobrado_ars": 690000.0, "costo_moneda": "USD"}),
                         (15000.0, "valuado"))

    def test_el_paquete_de_ia_y_la_herramienta_de_activos_dicen_lo_mismo(self):
        self._ggal()
        op = self._ventas("GGAL")[0]
        from ai.builders import operation_trade
        conn = main.get_db()
        try:
            paquete = operation_trade.build(conn, self.uid, operation_id=op["id"])
        finally:
            conn.close()
        self.assertEqual(paquete["trade"]["result_ars"], 240000)
        r = main._execute_ai_tool("get_asset_operations", {"asset": "GGAL"}, self.uid)
        ventas = [o for o in r["operations"] if o.get("op_type") == "Venta"]
        self.assertEqual(ventas[0]["result_ars"], 240000)

    def test_el_csv_de_una_venta_vieja_y_el_mensual_dicen_los_pesos(self):
        import csv
        uid, h = Auditoria._vieja(self)                                       # sin columnas, regla vieja
        self._plantar("UPDATE users SET tier='plus' WHERE id=?", (uid,))
        r = self.client.get("/api/export/operations.csv", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
        venta = [f for f in filas if f.get("Activo") == "GGAL" or f.get("asset") == "GGAL"][0]
        self.assertAlmostEqual(float(str(venta["Resultado en pesos"]).replace(",", ".")), 240000, delta=1)
        # El CSV mensual: las columnas de siempre (dólares) y, al final, los pesos de las operaciones en pesos
        r = self.client.get("/api/export/monthly.csv", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
        junio = [f for f in filas if f["Período"] == "2024-06" and f["Broker"] == "global"][0]
        self.assertAlmostEqual(float(junio["P&L realizado"]), 160, places=1)             # dólares, como siempre
        self.assertAlmostEqual(float(junio[self.COL_PESOS]), 240000, delta=1)
        self.assertEqual(junio[self.COL_VALUADO], "no")                                  # ventas en pesos: exacto
        self.assertEqual(list(filas[0].keys())[-2:], [self.COL_PESOS, self.COL_VALUADO])  # al final: no mueven columnas


    def test_el_resumen_del_ano_del_calendario_trae_los_pesos(self):
        """/api/reports/years alimenta la fila del año del calendario de Reportes: tiene que traer
        la misma cuenta (pesos exactos, dólares que cubre, si hubo valuados) que el mes."""
        self._ggal()
        self._plantar("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))   # los años cerrados son de plan pago
        with mock.patch.object(main, "_tiene_reportes_historicos", lambda *a, **k: True), \
                mock.patch.object(main, "_bench_para_reportes", lambda *a, **k: {}):
            r = self.client.get("/api/reports/years", headers=self.h, params={"moneda": "ars"})
        self.assertEqual(r.status_code, 200, r.text)
        anio = [y for y in r.json()["years"] if y["year"] == 2024][0]
        self.assertAlmostEqual(anio["realized_ars"], 240000, places=2)
        self.assertAlmostEqual(anio["realized_ars_cubre_usd"], 10, places=2)
        self.assertAlmostEqual(anio["realized_pnl"], 10, places=2)
        self.assertFalse(anio["realized_ars_valuado"])

    # ── el CSV mensual para el contador ──
    def test_el_csv_mensual_con_dos_brokers_dice_cada_uno_lo_suyo(self):
        """Cocos (ventas en pesos, +$240.000) y Bull (venta en dólares, US$ 500 → $1.250.000 valuados) el mismo
        mes. Cada fila de broker trae SU número, el global la suma, y la marca de «valuado» dice cuál no es
        de pesos cobrados (un contador que lee 1.250.000 como pesos de un broker en dólares se equivoca)."""
        self._ggal()
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100, entry_date="2024-01-10")
        self._vender(broker=DOLARES, asset="AAPL", quantity=10, exit_price=150, date="2024-06-10")
        filas = self._csv_mensual()
        junio = {f["Broker"]: f for f in filas if f["Período"] == "2024-06"}
        self.assertEqual(float(junio[PESOS][self.COL_PESOS]), 240000)
        self.assertEqual(junio[PESOS][self.COL_VALUADO], "no")
        self.assertEqual(float(junio[DOLARES][self.COL_PESOS]), 1250000)
        self.assertEqual(junio[DOLARES][self.COL_VALUADO], "sí")
        self.assertEqual(float(junio["global"][self.COL_PESOS]), 240000 + 1250000)
        self.assertEqual(junio["global"][self.COL_VALUADO], "sí")

    def test_el_global_marca_valuado_aunque_la_venta_en_dolares_sea_la_primera(self):
        """La marca no depende del orden de carga: con la venta en dólares ANTES que la de pesos, el global
        también avisa. (Si gana la última operación, un contador lee $1.490.000 como pesos cobrados.)"""
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100, entry_date="2024-01-10")
        self._vender(broker=DOLARES, asset="AAPL", quantity=10, exit_price=150, date="2024-06-10")
        self._ggal()
        junio = {f["Broker"]: f for f in self._csv_mensual() if f["Período"] == "2024-06"}
        self.assertEqual(junio["global"][self.COL_VALUADO], "sí")
        self.assertEqual(junio[PESOS][self.COL_VALUADO], "no")

    def test_un_mes_con_solo_un_cupon_en_dolares_no_dice_cero_en_pesos(self):
        """Un cupón de US$ 25 y nada más: no se pasa a pesos acá. La celda va VACÍA —un 0 dice «no ganaste
        nada en pesos» donde el dato es «no se pudo pasar»— y la marca de valuado también."""
        r = self.client.post("/api/operations", headers=self.h, json={
            "date": "2024-07-12", "broker": DOLARES, "asset": "KO", "op_type": "Cupón", "quantity": 1,
            "entry_price": 0, "exit_price": 0, "pnl_usd": 25, "pnl_pct": 0, "commissions": 0,
            "currency": "USD", "fx_to_usd": 1})
        self.assertEqual(r.status_code, 200, r.text)
        filas = self._csv_mensual()
        julio = [f for f in filas if f["Período"] == "2024-07" and f["Broker"] == DOLARES]
        self.assertTrue(julio, "el mes del cupón tiene que figurar en el CSV")
        self.assertEqual(float(julio[0]["P&L realizado"]), 25)
        self.assertEqual(julio[0][self.COL_PESOS], "")
        self.assertEqual(julio[0][self.COL_VALUADO], "")

    def test_el_csv_de_operaciones_dice_cuales_son_valuadas(self):
        """El que se le manda al contador distingue lo exacto de lo valuado, como la pantalla y el mensual."""
        import csv
        self._ggal()
        self._alta(broker=DOLARES, asset="AAPL", quantity=10, buy_price=100, entry_date="2024-01-10")
        self._vender(broker=DOLARES, asset="AAPL", quantity=10, exit_price=150, date="2024-06-10")
        self._plantar("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))
        r = self.client.get("/api/export/operations.csv", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
        por_activo = {f["Activo"]: f for f in filas if f.get("Resultado en pesos")}
        self.assertEqual(por_activo["GGAL"][self.COL_TIPO], "exacto")
        self.assertEqual(por_activo["AAPL"][self.COL_TIPO], "valuado")
        # La columna va al final: las hojas ya armadas leen por posición.
        self.assertEqual(list(filas[0].keys())[-1], self.COL_TIPO)

    def test_el_csv_mensual_deja_vacio_el_mes_sin_ventas(self):
        """Un mes sin ninguna operación con pesos: celda VACÍA (no 0, que diría «no ganaste»)."""
        self._ggal()
        self._plantar("INSERT INTO monthly_entries (user_id, year, month, broker, capital_inicio, capital_final, "
                      "deposits, withdrawals, pnl_realized) VALUES (?,?,?,?,?,?,?,?,?)",
                      (self.uid, 2024, 7, PESOS, 1000, 1000, 0, 0, 0))
        filas = self._csv_mensual()
        julio = [f for f in filas if f["Período"] == "2024-07" and f["Broker"] == PESOS][0]
        self.assertEqual(julio[self.COL_PESOS], "")
        self.assertEqual(julio[self.COL_VALUADO], "")

    # ── una venta sin resultado guardado no rompe las pantallas ──
    def test_una_venta_sin_resultado_guardado_no_rompe_operaciones_ni_movimientos(self):
        """`pnl_usd` NULL (la venta cargada sin costo): la cuenta en pesos devuelve «sin dato» y las pantallas
        siguen respondiendo. Sin la guarda `pnl is not None`, `float(None)` tumba /api/operations."""
        self._ggal()
        self._plantar("UPDATE operations SET pnl_usd=NULL, cobrado_ars=NULL, costo_ars=NULL WHERE user_id=? "
                      "AND op_type='Venta'", (self.uid,))
        r = self.client.get("/api/operations", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        venta = [o for o in r.json() if o["op_type"] == "Venta"][0]
        self.assertIsNone(venta["resultado_ars"])
        self.assertEqual(self.client.get("/api/movements", headers=self.h).status_code, 200)
        self.assertEqual(self.client.get("/api/monthly", headers=self.h).status_code, 200)


if __name__ == "__main__":
    unittest.main()
