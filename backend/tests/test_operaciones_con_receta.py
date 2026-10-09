"""Toda operación que se crea a mano nace con su RECETA: se puede borrar y deshacer.

Por qué. Borrar una operación cargada a mano (`_delete_manual_operation_cascade`)
revierte lo que hizo al crearse leyendo su receta (`operations.undo_meta_json`): de
qué puerta salió y qué movió. Sin receta frena con `_MANUAL_LEGACY_MSG` ("la
cargaste antes de que guardáramos cómo deshacerla"), que está bien para las filas
viejas. Pero hasta 2026-10-09 dos puertas ACTUALES escribían filas sin receta, así
que nacían imposibles de borrar, con un mensaje falso:

  · cobrar un plazo fijo (`cobrar_plazo_fijo`): cierra el plazo fijo, acredita
    capital + interés y anota el 'Interés PF';
  · comprar o vender dólares dentro de un broker (`create_conversion`): mueve la
    caja en pesos y la '· USD' (y el TC promedio de los dólares).

Y sin receta el formulario de edición les ofrecía "mueve efectivo": prenderlo en
un interés de plazo fijo de $14.794 acreditó $20.934.245 (el interés en pesos
leído como dólares, encima de lo que ya había entrado al cobrarlo).

Decisión de Nico (2026-10-09): borrar el interés de un plazo fijo DESHACE EL COBRO
entero — el plazo fijo vuelve abierto y sale lo que entró —, igual que borrar el
cierre de un futuro reabre la posición.

Acá se fija, todo por HTTP como la app (sólo se reemplaza el login):
  · cada puerta deja su receta, y borrar → deshacer → borrar deja la cuenta
    exactamente como estaba en cada paso: efectivo de cada caja (y su TC
    promedio), plazos fijos, operaciones, capital aportado y resultado del mes;
  · las filas viejas sin receta siguen bloqueadas, y la palanca de efectivo no
    se les ofrece;
  · deshacer el borrado del historial de un activo devuelve cada fila CON su receta;
  · nadie vuelve a crear operaciones sin receta, ni a escribir una receta que el
    borrado no sepa leer (guardián del código).
"""
import ast
import json
import os
import re
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
import main
import snapshots_job

MAIN = os.path.join(BACKEND, "main.py")


class ConRecetaBase(unittest.TestCase):
    PESOS = "Cocos"           # broker en pesos (su '· USD' lo crea la primera compra)
    DOLARES = "IBKR"          # broker en dólares

    def setUp(self):
        self.conn = main.get_db()
        self.conn.execute("PRAGMA foreign_keys=OFF")
        for t in ("flujos_a_mano", "deleted_ops_journal", "positions", "operations",
                  "monthly_entries", "snapshots", "plazos_fijos", "brokers", "config",
                  "import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"receta-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        for b, mon in ((self.PESOS, "ARS"), (self.DOLARES, "USD")):
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, b, mon))
        self.conn.commit()
        # La reconstrucción a mercado en otro hilo no es lo que se mide.
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)
        self.http = TestClient(main.app)

    def tearDown(self):
        self.conn.close()

    # ── puertas ──
    def _ok(self, r, codigo=200):
        self.assertEqual(r.status_code, codigo, r.text)
        return r.json()

    def _depositar(self, broker, monto):
        self._ok(self.http.post("/api/cash/flow", json={
            "broker_name": broker, "direction": "deposit", "amount": monto}))

    def _convertir(self, desde, direccion, pesos, dolares, tc):
        self._ok(self.http.post("/api/conversions", json={
            "from_broker": desde, "direction": direccion, "ars_amount": pesos,
            "usd_amount": dolares, "tc": tc, "kind": "MEP"}))
        return self._ultima_op()

    def _plazo_fijo(self, capital, moneda="ARS", desde=None, dias_atras=40, plazo=30):
        """Un plazo fijo que ya venció (así el interés no depende de la hora)."""
        return self._ok(self.http.post("/api/plazos-fijos", json={
            "banco": "Galicia", "capital": capital, "moneda": moneda, "tasa": 0.36,
            "fecha_inicio": (date.today() - timedelta(days=dias_atras)).isoformat(),
            "plazo_dias": plazo, "source_broker": desde}))["id"]

    def _cobrar(self, pid, broker):
        return self._ok(self.http.post(f"/api/plazos-fijos/{pid}/cobrar", json={"broker": broker}))

    def _ultima_op(self):
        return dict(self.conn.execute(
            "SELECT * FROM operations WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (self.uid,)).fetchone())

    def _borrar(self, op, puerta="movimientos", codigo=200):
        if puerta == "movimientos":
            sufijo = "fx" if main.realized_pnl.es_conversion(op["op_type"]) else "sell"
            r = self.http.delete(f"/api/movements/op-{op['id']}-{sufijo}")
        else:
            r = self.http.delete(f"/api/operations/{op['id']}")
        return self._ok(r, codigo)

    def _deshacer(self, token, codigo=200):
        return self._ok(self.http.post(f"/api/operations/undo/{token}"), codigo)

    # ── lo que se mide ──
    def estado(self):
        """La cuenta entera, en números que no dependen de ids ni de la hora."""
        self.conn.commit()   # ver lo que escribió el pedido (otra conexión)
        cajas = {r["broker"]: (round(float(r["invested"] or 0), 6),
                               None if r["tc_compra"] is None else round(float(r["tc_compra"]), 6))
                 for r in self.conn.execute(
                     "SELECT broker, invested, tc_compra FROM positions "
                     "WHERE user_id=? AND is_cash=1", (self.uid,))}
        pfs = {r["id"]: r["closed_at"] for r in self.conn.execute(
            "SELECT id, closed_at FROM plazos_fijos WHERE user_id=?", (self.uid,))}
        ops = sorted((r["op_type"], r["broker"], round(float(r["pnl_usd"] or 0), 6),
                      r["undo_meta_json"] or "") for r in self.conn.execute(
            "SELECT * FROM operations WHERE user_id=?", (self.uid,)))
        resultado = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized), 0) AS s FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["s"]
        # El aportado, al centavo: el recálculo de la cascada redondea los
        # depósitos a 4 decimales (US$ 706,713781 → 706,7138), con o sin esto.
        return {"cajas": cajas, "plazos_fijos": pfs, "operaciones": ops,
                "aportado": round(snapshots_job.compute_net_deposited_db(self.conn, self.uid), 2),
                "resultado_del_mes": round(float(resultado or 0), 4)}

    def assertMismaCuenta(self, antes, despues, cuando):
        for k in antes:
            self.assertEqual(antes[k], despues[k], f"{cuando}: cambió {k}")


class LaConversionSeBorraYSeDeshace(ConRecetaBase):

    def test_comprar_dolares_borrar_deshacer_y_borrar_otra_vez(self):
        self._depositar(self.PESOS, 1_000_000)
        e0 = self.estado()
        op = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        e1 = self.estado()
        self.assertEqual(e1["cajas"][self.PESOS], (870_000.0, None))
        self.assertEqual(e1["cajas"][f"{self.PESOS} · USD"], (100.0, 1300.0))
        self.assertEqual(json.loads(op["undo_meta_json"])["src"], "conversion")

        token = self._borrar(op)["undo_token"]
        e2 = self.estado()
        self.assertEqual(e2["cajas"][self.PESOS], (1_000_000.0, None))
        # La caja de dólares queda vacía y SIN precio: como antes de la compra.
        self.assertEqual(e2["cajas"][f"{self.PESOS} · USD"], (0.0, None))
        self.assertEqual(e2["operaciones"], e0["operaciones"])
        self.assertEqual(e2["aportado"], e0["aportado"])

        self._deshacer(token)
        self.assertMismaCuenta(e1, self.estado(), "después de deshacer")
        # Y la fila que volvió se puede volver a borrar (volvió con su receta).
        self._borrar(self._ultima_op())
        self.assertEqual(self.estado()["cajas"][self.PESOS], (1_000_000.0, None))

    def test_vender_dolares_con_ganancia_borrar_y_deshacer(self):
        self._depositar(self.PESOS, 1_000_000)
        self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        e_a = self.estado()
        venta = self._convertir(f"{self.PESOS} · USD", "usd_to_ars", 80_000, 50, 1600)
        e_b = self.estado()
        self.assertGreater(venta["pnl_usd"], 0)   # vendió a 1600 lo que costó 1300
        self.assertNotEqual(e_b["resultado_del_mes"], e_a["resultado_del_mes"])

        token = self._borrar(venta)["undo_token"]
        self.assertMismaCuenta(e_a, self.estado(), "después de borrar la venta")
        self._deshacer(token)
        self.assertMismaCuenta(e_b, self.estado(), "después de deshacer")

    def test_dos_compras_borrar_la_primera_deja_el_precio_de_la_segunda(self):
        self._depositar(self.PESOS, 1_000_000)
        primera = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        self._convertir(self.PESOS, "ars_to_usd", 150_000, 100, 1500)
        e_antes = self.estado()
        self.assertEqual(e_antes["cajas"][f"{self.PESOS} · USD"], (200.0, 1400.0))

        token = self._borrar(primera)["undo_token"]
        # Quedan los 100 de la segunda, a SU precio: exacto.
        self.assertEqual(self.estado()["cajas"][f"{self.PESOS} · USD"], (100.0, 1500.0))
        self.assertEqual(self.estado()["cajas"][self.PESOS], (850_000.0, None))
        self._deshacer(token)
        self.assertMismaCuenta(e_antes, self.estado(), "después de deshacer")

    def test_dos_compras_al_mismo_precio_borrar_la_primera_no_deja_dolares_sin_precio(self):
        """Lo encontró la prueba en el navegador: con la caja vacía, 100 y después 10
        dólares a 1.300 dejan el promedio igual, y "volver al de antes" (ninguno)
        dejaba los 10 dólares de la segunda compra sin precio de compra."""
        self._depositar(self.PESOS, 1_000_000)
        primera = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        self._convertir(self.PESOS, "ars_to_usd", 13_000, 10, 1300)
        e_antes = self.estado()
        token = self._borrar(primera)["undo_token"]
        self.assertEqual(self.estado()["cajas"][f"{self.PESOS} · USD"], (10.0, 1300.0))
        self._deshacer(token)
        self.assertMismaCuenta(e_antes, self.estado(), "después de deshacer")

    def test_con_casi_todos_los_dolares_vendidos_el_precio_no_se_dispara(self):
        """La cuenta inversa del promedio divide por lo que queda: 100 a 1.000, 100
        a 1.800 y 99 vendidos daban un dólar a 41.400. Con poco saldo, no se toca."""
        self._depositar(self.PESOS, 1_000_000)
        primera = self._convertir(self.PESOS, "ars_to_usd", 100_000, 100, 1000)
        self._convertir(self.PESOS, "ars_to_usd", 180_000, 100, 1800)
        self._convertir(f"{self.PESOS} · USD", "usd_to_ars", 138_600, 99, 1400)
        self._borrar(primera)
        dolares, tc = self.estado()["cajas"][f"{self.PESOS} · USD"]
        self.assertAlmostEqual(dolares, 1.0, places=6)      # 200 − 99 − 100: la plata, exacta
        self.assertTrue(1000 <= tc <= 1800, tc)

    def test_por_la_otra_puerta_tambien(self):
        self._depositar(self.PESOS, 1_000_000)
        e0 = self.estado()
        op = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        self._borrar(op, puerta="operaciones")
        self.assertEqual(self.estado()["cajas"][self.PESOS], e0["cajas"][self.PESOS])

    def test_doble_click_en_borrar_y_en_deshacer_mueve_la_plata_una_vez(self):
        self._depositar(self.PESOS, 1_000_000)
        op = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        token = self._borrar(op)["undo_token"]
        r = self.http.delete(f"/api/movements/op-{op['id']}-fx")
        self.assertIn(r.status_code, (404, 409), r.text)
        self.assertEqual(self.estado()["cajas"][self.PESOS], (1_000_000.0, None))
        self._deshacer(token)
        self._deshacer(token, codigo=404)
        self.assertEqual(self.estado()["cajas"][self.PESOS], (870_000.0, None))

    def test_si_el_broker_ya_no_esta_frena_sin_mover_nada(self):
        self._depositar(self.PESOS, 1_000_000)
        op = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        self.conn.execute("DELETE FROM brokers WHERE user_id=? AND name=?",
                          (self.uid, f"{self.PESOS} · USD"))
        self.conn.commit()
        antes = self.estado()
        r = self.http.delete(f"/api/movements/op-{op['id']}-fx")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertMismaCuenta(antes, self.estado(), "después del 409")

    def test_movimientos_ofrece_borrar_sola_la_que_tiene_receta(self):
        self._depositar(self.PESOS, 1_000_000)
        nueva = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        vieja = self._convertir(self.PESOS, "ars_to_usd", 13_000, 10, 1300)
        self.conn.execute("UPDATE operations SET undo_meta_json=NULL WHERE id=?", (vieja["id"],))
        self.conn.commit()
        filas = {m["id"]: m for m in self._ok(self.http.get("/api/movements"))
                 if m["id"].endswith("-fx")}
        self.assertIs(filas[f"op-{nueva['id']}-fx"]["borrable"], True)
        self.assertIs(filas[f"op-{vieja['id']}-fx"]["borrable"], False)

    def test_la_conversion_vieja_sigue_bloqueada(self):
        self._depositar(self.PESOS, 1_000_000)
        op = self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
        self.conn.execute("UPDATE operations SET undo_meta_json=NULL WHERE id=?", (op["id"],))
        self.conn.commit()
        antes = self.estado()
        r = self.http.delete(f"/api/movements/op-{op['id']}-fx")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"], main._MANUAL_LEGACY_MSG)
        self.assertMismaCuenta(antes, self.estado(), "después del 400")


class BorrarElInteresDeshaceElCobro(ConRecetaBase):

    def test_borrar_el_interes_deshace_el_cobro_y_deshacer_lo_vuelve_a_cobrar(self):
        self._depositar(self.PESOS, 1_000_000)
        pid = self._plazo_fijo(500_000, desde=self.PESOS)
        e_abierto = self.estado()
        self.assertEqual(e_abierto["cajas"][self.PESOS], (500_000.0, None))
        cobro = self._cobrar(pid, self.PESOS)
        e_cobrado = self.estado()
        self.assertEqual(e_cobrado["cajas"][self.PESOS], (round(500_000 + cobro["monto"], 6), None))
        self.assertIsNotNone(e_cobrado["plazos_fijos"][pid])
        # El interés entra al resultado del mes en el momento del cobro.
        self.assertNotEqual(e_cobrado["resultado_del_mes"], e_abierto["resultado_del_mes"])
        interes = self._ultima_op()
        self.assertEqual(interes["op_type"], "Interés PF")

        token = self._borrar(interes)["undo_token"]
        # Como si nunca se hubiera cobrado: abierto, sin la plata, sin la ganancia.
        self.assertMismaCuenta(e_abierto, self.estado(), "después de borrar el interés")

        self._deshacer(token)
        self.assertMismaCuenta(e_cobrado, self.estado(), "después de deshacer")
        # Volvió con su receta: se puede borrar otra vez.
        self._borrar(self._ultima_op())
        self.assertMismaCuenta(e_abierto, self.estado(), "después de borrarlo otra vez")

    def test_cobrado_sin_broker_solo_vuelve_el_plazo_fijo(self):
        """Si se cobró sin elegir broker, la plata no entró a ninguna cuenta. La fila
        lleva el BANCO como broker, que no es un broker de Rendi: deshacer no puede
        frenar por eso."""
        pid = self._plazo_fijo(500_000)            # plata de afuera de Rendi
        e_abierto = self.estado()
        self._cobrar(pid, None)
        e_cobrado = self.estado()
        interes = self._ultima_op()
        self.assertEqual(interes["broker"], "Galicia")
        token = self._borrar(interes)["undo_token"]
        self.assertMismaCuenta(e_abierto, self.estado(), "después de borrar el interés")
        self._deshacer(token)
        self.assertMismaCuenta(e_cobrado, self.estado(), "después de deshacer")

    def test_en_dolares(self):
        self._depositar(self.DOLARES, 10_000)
        pid = self._plazo_fijo(5_000, moneda="USD", desde=self.DOLARES)
        e_abierto = self.estado()
        self._cobrar(pid, self.DOLARES)
        e_cobrado = self.estado()
        token = self._borrar(self._ultima_op(), puerta="operaciones")["undo_token"]
        self.assertMismaCuenta(e_abierto, self.estado(), "después de borrar el interés")
        self._deshacer(token)
        self.assertMismaCuenta(e_cobrado, self.estado(), "después de deshacer")

    def test_si_lo_volviste_a_cobrar_el_deshacer_viejo_frena(self):
        self._depositar(self.PESOS, 1_000_000)
        pid = self._plazo_fijo(500_000, desde=self.PESOS)
        self._cobrar(pid, self.PESOS)
        token = self._borrar(self._ultima_op())["undo_token"]
        self._cobrar(pid, self.PESOS)
        antes = self.estado()
        self._deshacer(token, codigo=409)
        self.assertMismaCuenta(antes, self.estado(), "después del 409")

    def test_si_lo_renovaste_el_deshacer_frena(self):
        self._depositar(self.PESOS, 1_000_000)
        pid = self._plazo_fijo(500_000, desde=self.PESOS)
        self._cobrar(pid, self.PESOS)
        token = self._borrar(self._ultima_op())["undo_token"]
        self._ok(self.http.post(f"/api/plazos-fijos/{pid}/renovar"))
        antes = self.estado()
        self._deshacer(token, codigo=409)
        self.assertMismaCuenta(antes, self.estado(), "después del 409")

    def test_doble_click_en_borrar_mueve_la_plata_una_vez(self):
        self._depositar(self.PESOS, 1_000_000)
        pid = self._plazo_fijo(500_000, desde=self.PESOS)
        self._cobrar(pid, self.PESOS)
        interes = self._ultima_op()
        self._borrar(interes)
        r = self.http.delete(f"/api/movements/op-{interes['id']}-sell")
        self.assertIn(r.status_code, (404, 409), r.text)
        self.assertEqual(self.estado()["cajas"][self.PESOS], (500_000.0, None))

    def test_movimientos_avisa_lo_que_deshace(self):
        self._depositar(self.PESOS, 1_000_000)
        pid = self._plazo_fijo(500_000, desde=self.PESOS)
        cobro = self._cobrar(pid, self.PESOS)
        interes = self._ultima_op()
        fila = [m for m in self._ok(self.http.get("/api/movements"))
                if m["id"] == f"op-{interes['id']}-sell"][0]
        self.assertEqual(fila["deshace_cobro_pf"], {
            "banco": "Galicia", "monto": cobro["monto"], "broker": self.PESOS, "moneda": "ARS"})

    def test_el_interes_viejo_sigue_bloqueado(self):
        self._depositar(self.PESOS, 1_000_000)
        pid = self._plazo_fijo(500_000, desde=self.PESOS)
        self._cobrar(pid, self.PESOS)
        interes = self._ultima_op()
        self.conn.execute("UPDATE operations SET undo_meta_json=NULL WHERE id=?", (interes["id"],))
        self.conn.commit()
        antes = self.estado()
        r = self.http.delete(f"/api/movements/op-{interes['id']}-sell")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertMismaCuenta(antes, self.estado(), "después del 400")
        fila = [m for m in self._ok(self.http.get("/api/movements"))
                if m["id"] == f"op-{interes['id']}-sell"][0]
        self.assertIsNone(fila["deshace_cobro_pf"])


class LaPalancaDeEfectivoNoSeOfrece(ConRecetaBase):
    """Las puertas que mueven plata por su cuenta no aceptan "mueve efectivo": ni el
    formulario la muestra ni el servidor la aplica si llega igual. Para las filas
    nuevas lo dice su receta; para las viejas, su tipo."""

    def _editar_prendiendo_la_palanca(self, op):
        cuerpo = {k: op[k] for k in ("date", "broker", "asset", "op_type", "entry_price",
                                     "exit_price", "quantity", "pnl_usd", "pnl_pct",
                                     "commissions", "currency", "fx_to_usd")}
        cuerpo["commissions"] = cuerpo["commissions"] or 0
        cuerpo["mueve_efectivo"] = True
        return self._ok(self.http.put(f"/api/operations/{op['id']}", json=cuerpo))

    def _editable(self, op):
        return [o for o in self._ok(self.http.get("/api/operations"))
                if o["id"] == op["id"]][0]["mueve_efectivo_editable"]

    def _caso(self, op, vieja):
        if vieja:
            self.conn.execute("UPDATE operations SET undo_meta_json=NULL WHERE id=?", (op["id"],))
            self.conn.commit()
            op = dict(op, undo_meta_json=None)
        self.assertIs(self._editable(op), False)
        antes = self.estado()["cajas"]
        self._editar_prendiendo_la_palanca(op)
        self.assertEqual(self.estado()["cajas"], antes, "la palanca movió plata")

    def test_interes_de_plazo_fijo_nuevo_y_viejo(self):
        for vieja in (False, True):
            with self.subTest(vieja=vieja):
                self._depositar(self.PESOS, 1_000_000)
                pid = self._plazo_fijo(500_000, desde=self.PESOS)
                self._cobrar(pid, self.PESOS)
                self._caso(self._ultima_op(), vieja)

    def test_venta_de_dolares_nueva_y_vieja(self):
        for vieja in (False, True):
            with self.subTest(vieja=vieja):
                self._depositar(self.PESOS, 1_000_000)
                self._convertir(self.PESOS, "ars_to_usd", 130_000, 100, 1300)
                venta = self._convertir(f"{self.PESOS} · USD", "usd_to_ars", 80_000, 50, 1600)
                self.assertGreater(venta["pnl_usd"], 0)
                self._caso(venta, vieja)

    def test_lo_tipeado_en_el_formulario_la_sigue_teniendo(self):
        """Aunque le ponga 'Interés PF' de tipo: con receta de formulario es suya."""
        for tipo in ("Venta", "Interés PF"):
            with self.subTest(tipo=tipo):
                op = self._ok(self.http.post("/api/operations", json={
                    "date": "2026-03-10", "broker": self.DOLARES, "asset": "KO",
                    "op_type": tipo, "pnl_usd": 50.0}))
                self.assertIs(self._editable(op), True)


class DeshacerElHistorialConservaLaReceta(ConRecetaBase):
    """Deshacer "borrar el historial de un activo" vuelve a insertar los cupones y
    dividendos que el borrado sacó. Hoy ahí sólo llegan filas importadas (con
    cupones cargados a mano el borrado frena antes), que se borran por el camino del
    import y no necesitan receta. Igual tiene que volver cada fila como era: si
    vuelve sin su receta, la que la tenía queda imposible de borrar. Se le planta
    una receta a un dividendo importado para ver que viaja."""

    def _importar(self, *filas):
        hdr = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
        archivo = (hdr + "".join(f + "\n" for f in filas)).encode("utf-8")
        h = main._ImportHelpers()
        for n in ("_adjust_broker_cash", "_update_monthly_pnl_realized",
                  "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
                  "_recalc_pnl_realized_from_ops"):
            setattr(h, n, getattr(main, n))
        with self.conn:
            sid = pl.run_preview(self.conn, uid=self.uid, file_bytes=archivo, file_name="x.csv",
                                 broker_hint=self.DOLARES,
                                 parser_format="rendi_generic")["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=h)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid,
                                         tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))

    def test_el_dividendo_vuelve_con_su_receta(self):
        self._importar("2025-12-02,DEPOSITO,IBKR,,,,100000,,,0,USD,",
                       "2025-12-03,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,",
                       "2025-12-10,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,")
        receta = json.dumps({"src": "plantada", "marca": 1})
        self.conn.execute("UPDATE operations SET undo_meta_json=? WHERE user_id=? "
                          "AND op_type='Dividendo'", (receta, self.uid))
        self.conn.commit()
        token = self._ok(self.http.delete("/api/assets/history", params={"asset": "AAPL"}))["undo_token"]
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM operations WHERE user_id=? AND op_type='Dividendo'",
            (self.uid,)).fetchone())
        self._ok(self.http.post(f"/api/assets/undo/{token}"))
        self.conn.commit()
        vuelta = self.conn.execute(
            "SELECT undo_meta_json FROM operations WHERE user_id=? AND op_type='Dividendo'",
            (self.uid,)).fetchone()
        self.assertEqual(vuelta["undo_meta_json"], receta)


class NadieCreaOperacionesSinReceta(unittest.TestCase):
    """El borrado de lo cargado a mano sirve sólo si TODA puerta que crea una
    operación deja su receta. La causa raíz más frecuente de este repo es el arreglo
    que no se propagó: hasta 2026-10-09 dos puertas nuevas (cobrar un plazo fijo,
    comprar/vender dólares) escribían filas sin receta, imposibles de borrar.

    Si alguien agrega otro INSERT INTO operations en el backend (menos los tests),
    esto sale en rojo y lo obliga a elegir: guardar la receta (en el INSERT o con un
    UPDATE posterior en la misma función, como `sell_position_fifo`), o vincular la
    fila a su import (las importadas las borra el camino del import). Y si escribe
    una receta con un `src` nuevo, tiene que enseñarle al borrado a leerla."""

    INSERT = re.compile(r"INSERT\s+(OR\s+\w+\s+)?INTO\s+operations\b", re.I)
    RECETA_DESPUES = re.compile(r"UPDATE\s+operations\s+SET\s+undo_meta_json", re.I)
    VINCULO = re.compile(r"INSERT\s+(OR\s+\w+\s+)?INTO\s+import_op_links", re.I)
    # (archivo, función) que insertan sin receta, y por qué está bien.
    PERMITIDO = {
        ("main.py", "init_db"): "migración vieja: copia la tabla entera (anterior a la receta)",
        ("seed.py", "seed"): "datos de demostración de una base local",
        ("scripts/seed_f1.py", "<módulo>"): "script de desarrollo",
        ("scripts/base_sintetica.py", "poblar"): "base sintética para medir, no producción",
        ("scripts/test_bot_profile_boundaries.py", "*"): "script de prueba del bot",
    }
    # Las que insertan con el nombre de la tabla en una variable, y por qué está bien.
    DINAMICO = {
        "_reinsert": "el Deshacer re-inserta la fila ENTERA que guardó el borrado "
                     "(`op_row`: todas las columnas menos el id), receta incluida",
    }

    def _archivos(self):
        for d, _, fs in os.walk(BACKEND):
            if os.path.relpath(d, BACKEND).split(os.sep)[0] in ("tests", "node_modules"):
                continue
            for f in fs:
                if f.endswith(".py"):
                    yield os.path.join(d, f)

    @staticmethod
    def _textos(nodo):
        return [n.value for n in ast.walk(nodo)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    def _funciones_que_insertan(self, codigo, ruta="x.py"):
        """{(ruta, función): [(línea, ¿receta en el INSERT?)]} — también las del módulo."""
        arbol = ast.parse(codigo)
        padres = {}
        for n in ast.walk(arbol):
            for h in ast.iter_child_nodes(n):
                padres[h] = n
        out = {}
        for n in ast.walk(arbol):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and self.INSERT.search(n.value)):
                continue
            fn, p = None, n
            while p in padres:
                p = padres[p]
                if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = p
                    break
            out.setdefault((ruta, fn.name if fn else "<módulo>"), {"nodo": fn, "inserts": []})[
                "inserts"].append((n.lineno, "undo_meta_json" in n.value))
        return out

    def _sin_receta(self, codigo, ruta):
        malos = []
        for (r, nombre), info in self._funciones_que_insertan(codigo, ruta).items():
            if (r, nombre) in self.PERMITIDO or (r, "*") in self.PERMITIDO:
                continue
            fn = info["nodo"]
            textos = self._textos(fn) if fn is not None else []
            despues = any(self.RECETA_DESPUES.search(t) for t in textos)
            vincula = (any(self.VINCULO.search(t) for t in textos) or any(
                isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", None)) == "_link"
                and any(k.arg == "operation_id" for k in c.keywords)
                for c in ast.walk(fn))) if fn is not None else False
            for linea, con_receta in info["inserts"]:
                if not (con_receta or despues or vincula):
                    malos.append(f"{r}:{linea} en {nombre}")
        return malos

    def test_toda_puerta_que_crea_una_operacion_deja_su_receta(self):
        malos = []
        for ruta in self._archivos():
            malos += self._sin_receta(open(ruta, encoding="utf-8").read(),
                                      os.path.relpath(ruta, BACKEND))
        self.assertEqual(malos, [], "crean operaciones sin receta (imposibles de borrar): "
                                    "guardá `undo_meta_json` o vinculala a su import")

    TABLA_EN_VARIABLE = re.compile(r"INSERT\s+(OR\s+\w+\s+)?INTO\s+$", re.I)

    def _insertan_en_tabla_variable(self, codigo):
        """Funciones con un f-string `INSERT INTO {tabla}`: el nombre de la tabla no
        se ve en el texto, así que el guardián de arriba no las puede revisar."""
        arbol = ast.parse(codigo)
        padres = {}
        for n in ast.walk(arbol):
            for h in ast.iter_child_nodes(n):
                padres[h] = n
        donde = set()
        for n in ast.walk(arbol):
            if not isinstance(n, ast.JoinedStr):
                continue
            if not any(isinstance(a, ast.Constant) and isinstance(b, ast.FormattedValue)
                       and self.TABLA_EN_VARIABLE.search(a.value)
                       for a, b in zip(n.values, n.values[1:])):
                continue
            p = n        # la función MÁS de adentro que lo contiene
            while p in padres and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                p = padres[p]
            donde.add(getattr(p, "name", "<módulo>"))
        return donde

    def test_nadie_inserta_operaciones_con_el_nombre_de_la_tabla_en_una_variable(self):
        donde = set()
        for ruta in self._archivos():
            donde |= self._insertan_en_tabla_variable(open(ruta, encoding="utf-8").read())
        self.assertEqual(donde, set(self.DINAMICO),
                         "inserta en una tabla que no se ve en el texto: si puede ser "
                         "`operations`, que lleve la receta, y anotalo en DINAMICO")

    def test_toda_receta_que_se_escribe_la_sabe_leer_el_borrado(self):
        """Cada `src` que una puerta escribe en una operación lo atiende
        `_delete_manual_operation_cascade`; si no, la fila nace con receta y el
        borrado igual contesta "la cargaste antes de que guardáramos…"."""
        arbol = ast.parse(open(MAIN, encoding="utf-8").read())
        borrado = [f for f in ast.walk(arbol) if isinstance(f, ast.FunctionDef)
                   and f.name == "_delete_manual_operation_cascade"][0]
        atiende = {c.comparators[0].value for c in ast.walk(borrado)
                   if isinstance(c, ast.Compare) and getattr(c.left, "id", None) == "src"
                   and isinstance(c.comparators[0], ast.Constant)}
        escritas = set()
        for fn in ast.walk(arbol):
            if not isinstance(fn, ast.FunctionDef):
                continue
            textos = self._textos(fn)
            if not any(self.INSERT.search(t) or self.RECETA_DESPUES.search(t)
                       or "undo_meta_json=COALESCE" in t for t in textos):
                continue
            for d in ast.walk(fn):
                if isinstance(d, ast.Dict):
                    for k, v in zip(d.keys, d.values):
                        if (isinstance(k, ast.Constant) and k.value == "src"
                                and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                            escritas.add(v.value)
            for t in textos:
                escritas |= set(re.findall(r'"src"\s*:\s*"(\w+)"', t))
        # `manual_position` es la receta de las POSICIONES (otra tabla, otro borrado).
        escritas.discard("manual_position")
        self.assertTrue({"manual_form", "manual_futures", "fifo_sell", "bond_cashflow",
                         "pf_cobro", "conversion"} <= escritas, escritas)
        self.assertEqual(escritas - atiende, set(),
                         "recetas que el borrado no sabe leer")

    def test_las_que_mueven_plata_solas_no_aceptan_la_palanca(self):
        """Toda receta que no sea del formulario mueve la plata por su cuenta: si no
        está en `_SRC_CON_EFECTIVO_PROPIO`, la edición le ofrece "mueve efectivo" y
        prenderlo acredita dos veces."""
        arbol = ast.parse(open(MAIN, encoding="utf-8").read())
        borrado = [f for f in ast.walk(arbol) if isinstance(f, ast.FunctionDef)
                   and f.name == "_delete_manual_operation_cascade"][0]
        atiende = {c.comparators[0].value for c in ast.walk(borrado)
                   if isinstance(c, ast.Compare) and getattr(c.left, "id", None) == "src"
                   and isinstance(c.comparators[0], ast.Constant)}
        self.assertEqual(atiende - {"manual_form", "manual_futures"},
                         set(main._SRC_CON_EFECTIVO_PROPIO))

    def test_el_guardian_ve_lo_que_dice_ver(self):
        """Control del instrumento: una puerta sin receta sale; con receta en el
        INSERT, con UPDATE posterior o vinculada a su import, no."""
        codigo = (
            "def sin(conn):\n"
            "    conn.execute('INSERT INTO operations (user_id, pnl_usd) VALUES (?,?)', (1, 2))\n"
            "def con(conn):\n"
            "    conn.execute('INSERT INTO operations (user_id, undo_meta_json) VALUES (?,?)', (1, 'x'))\n"
            "def despues(conn):\n"
            "    conn.execute('''INSERT OR IGNORE INTO operations (user_id) VALUES (?)''', (1,))\n"
            "    conn.execute('UPDATE operations SET undo_meta_json=? WHERE id=?', ('x', 1))\n"
            "def vinculada(conn):\n"
            "    cur = conn.execute('INSERT INTO operations (user_id) VALUES (?)', (1,))\n"
            "    _link(conn, 'b', 1, operation_id=cur.lastrowid)\n")
        self.assertEqual(self._sin_receta(codigo, "x.py"), ["x.py:2 en sin"])
        self.assertEqual(self._insertan_en_tabla_variable(
            "def a(conn, t):\n    conn.execute(f'INSERT INTO {t} (x) VALUES (1)')\n"
            "def b(conn, c):\n    conn.execute(f'INSERT INTO positions ({c}) VALUES (1)')\n"),
            {"a"})


if __name__ == "__main__":
    unittest.main()
