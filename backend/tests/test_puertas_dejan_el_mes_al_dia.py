"""Toda puerta que anota una operación deja el RESULTADO DEL MES al día, en el momento.

Por qué. El resultado realizado del mes (`monthly_entries.pnl_realized`) es una
copia: la verdad son las filas de `operations`, y la copia la rehace
`_recalc_pnl_realized_from_ops` (pnl_realized = Σ de las operaciones del mes, en
dólares). Cada puerta que inserta una operación tiene que actualizar esa copia
ella misma; la que se olvida deja al Dashboard y a Reportes mostrando un mes sin
esa operación hasta que OTRA acción recalcule.

Ya pasó tres veces, siempre igual:
  · cargar una operación a mano (`create_operation`, 2026-05-31);
  · cobrar un plazo fijo (`cobrar_plazo_fijo`, 2026-10-09, `8e7f5b72`);
  · cobrar un cupón o una amortización (`bond_cashflow`, 2026-10-10): anotaba la
    operación y acreditaba el efectivo, y el mes no se enteraba. Medido por HTTP
    sobre una base vacía: después de cobrar un cupón de US$ 100, GET /api/monthly
    no traía ningún resultado; guardar una edición de cualquier operación sin
    cambiar nada lo hacía aparecer (+100).

Qué se fija acá, todo por HTTP como la app (sólo se reemplaza el login):
  · cada puerta, una por una: se hace la acción y se lee el mes por el MISMO
    pedido que usa el Dashboard (GET /api/monthly), SIN forzar un recálculo antes.
    Recién después se fuerza uno para comparar: si el recálculo cambia algo, la
    puerta había dejado el mes viejo;
  · y que la puerta le avisa a la IA que los datos cambiaron (si no, el chat
    contesta hasta 24 hs con la cartera de antes). Faltaba en dos: el cobro de
    bonos y comprar/vender dólares;
  · el cupón en pesos entra al mes en DÓLARES (dividido por el dólar del día del
    cobro, que sella el servidor), no como pesos leídos como dólares;
  · nadie agrega una puerta nueva sin su escenario (guardián del código). Ojo con
    su punto ciego: sólo ve los `INSERT INTO operations` escritos a mano. Lo que
    reinserta filas armando el SQL (deshacer un borrado) lo cubre su escenario de
    comportamiento, no el guardián.
"""
import ast
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

import main
import realized_pnl

# Ayer: ni futura (el cobro de un cupón la rechaza) ni pegada al cambio de día
# entre el reloj del servidor (UTC) y el argentino.
AYER = (date.today() - timedelta(days=1)).isoformat()
# Un corte de dividendo de hace dos semanas: el cobro (AYER) tiene que caer dentro
# de los 45 días del corte. Con el corte escrito a mano («2026-09-15») la prueba
# se ponía roja sola desde el 31/10/2026.
CORTE_RECIENTE = (date.today() - timedelta(days=15)).isoformat()
DOLAR = 1250.0


class _Base(unittest.TestCase):
    PESOS, DOLARES, CRIPTO = "Cocos", "IBKR", "Binance"

    def setUp(self):
        self.conn = main.get_db()
        # `fx_rates_daily` es GLOBAL: primero y en su propio try.
        try:
            self.conn.execute("DELETE FROM fx_rates_daily")
        except Exception:
            pass
        self.conn.execute("PRAGMA foreign_keys=OFF")
        for t in ("flujos_a_mano", "deleted_ops_journal", "positions", "operations",
                  "monthly_entries", "snapshots", "plazos_fijos", "futures_positions",
                  "brokers", "config", "import_op_links", "import_normalized_tx",
                  "import_raw_rows", "import_batches"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=ON")
        # La serie del dólar, como en producción (cubre desde 2011): el servidor
        # sella el del día del cobro buscándolo ACÁ, no se lo simula.
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source, fetched_at) "
            "VALUES (?,?,?,?,datetime('now'))", ("2025-01-02", DOLAR, DOLAR, "test"))
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"mes-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        for b, mon in ((self.PESOS, "ARS"), (self.DOLARES, "USD"), (self.CRIPTO, "USDT")):
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, b, mon))
        self.conn.commit()
        # La reconstrucción de la curva en otro hilo no es lo que se mide.
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)
        self.http = TestClient(main.app)

    def tearDown(self):
        self.conn.close()

    def _ok(self, r, codigo=200):
        self.assertEqual(r.status_code, codigo, r.text)
        return r.json()

    # ── lo que se mide ──
    def mes(self):
        """El resultado realizado por cuenta, tal como lo recibe el Dashboard."""
        total = {}
        for f in self._ok(self.http.get("/api/monthly")):
            total[f["broker"]] = total.get(f["broker"], 0.0) + float(f["pnl_realized"] or 0)
        return {b: round(v, 2) for b, v in total.items() if abs(v) > 0.005}

    def segun_las_operaciones(self):
        """La verdad: Σ de las operaciones en dólares, por cuenta y en total."""
        total = {}
        c = main.get_db()
        try:
            for o in c.execute("SELECT * FROM operations WHERE user_id=?", (self.uid,)):
                usd = realized_pnl.realized_usd(o)
                for b in (o["broker"], "global"):
                    total[b] = total.get(b, 0.0) + usd
        finally:
            c.close()
        return {b: round(v, 2) for b, v in total.items() if abs(v) > 0.005}

    def recalcular(self):
        c = main.get_db()
        try:
            with c:
                main._recalc_pnl_realized_from_ops(c, self.uid)
        finally:
            c.close()

    def ia_con_datos_viejos(self):
        """Se llama JUSTO ANTES de la acción que se mide (los pasos previos
        —depositar, comprar— también avisan, y borrarían la marca ellos)."""
        main._CHAT_VAL_CACHE[self.uid] = "cartera de antes"
        self.addCleanup(main._CHAT_VAL_CACHE.pop, self.uid, None)
        self._ia_marcada = True

    def al_dia(self, espera=None):
        """El mes YA está al día: lo que se lee justo después de la acción es lo
        que dicen las operaciones, y un recálculo completo no le cambia nada."""
        self.assertTrue(getattr(self, "_ia_marcada", False),
                        "falta `ia_con_datos_viejos()` antes de la acción")
        self.assertNotIn(self.uid, main._CHAT_VAL_CACHE,
                         "la puerta no le avisó a la IA que los datos cambiaron")
        leido = self.mes()                       # ⚠️ ANTES de recalcular nada
        self.assertTrue(leido, "la acción no dejó ningún resultado en el mes")
        if espera is not None:
            self.assertEqual(leido, espera)
        self.assertEqual(leido, self.segun_las_operaciones(),
                         "el mes no coincide con las operaciones")
        self.recalcular()
        self.assertEqual(self.mes(), leido,
                         "un recálculo cambió el mes: la puerta lo había dejado viejo")
        return leido

    # ── puertas ──
    def _depositar(self, broker, monto):
        self._ok(self.http.post("/api/cash/flow", json={
            "broker_name": broker, "direction": "deposit", "amount": monto}))

    def _comprar(self, broker, activo, cantidad, precio, moneda, **extra):
        self._ok(self.http.post("/api/positions", json={
            "broker": broker, "asset": activo, "quantity": cantidad, "buy_price": precio,
            "invested": cantidad * precio, "entry_date": "2026-01-10", "currency": moneda,
            **extra}))

    def _cobrar_bono(self, broker, activo, tipo, monto, **extra):
        self.ia_con_datos_viejos()
        return self._ok(self.http.post("/api/bonds/cashflow", json={
            "broker": broker, "asset": activo, "flow_type": tipo, "amount": monto,
            "date": AYER, **extra}))

    def _ultima_op(self):
        return dict(self.conn.execute(
            "SELECT * FROM operations WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (self.uid,)).fetchone())


# ═════════════════════════════════════════════════════════════════════════════
class CobrarUnBono(_Base):
    """La puerta que estaba rota: `POST /api/bonds/cashflow`."""

    def test_el_cupon_en_dolares_entra_al_mes_en_el_momento(self):
        self._cobrar_bono(self.DOLARES, "GD30", "coupon", 100)
        self.al_dia({self.DOLARES: 100.0, "global": 100.0})

    def test_el_cupon_en_pesos_entra_en_dolares_no_como_pesos(self):
        """$125.000 al dólar de ese día (1.250) son US$ 100. El dólar lo sella el
        servidor (acá el pedido no lo manda): sin sello la fila se leería cruda."""
        self._cobrar_bono(self.PESOS, "AL30", "coupon", 125000)
        self.assertEqual(self._ultima_op()["fx_to_usd"], DOLAR)
        self.al_dia({self.PESOS: 100.0, "global": 100.0})

    def test_el_cupon_en_pesos_con_el_dolar_que_manda_el_formulario(self):
        self._cobrar_bono(self.PESOS, "AL30", "coupon", 130000, fx_to_usd=1300)
        self.al_dia({self.PESOS: 100.0, "global": 100.0})

    def test_la_amortizacion_entra_al_mes_en_el_momento(self):
        """Sin número fijo a propósito: cuánto de una amortización es ganancia
        (todo lo cobrado, o sólo lo cobrado por encima del costo) es otra
        decisión. Acá se fija que el mes diga lo mismo que la operación."""
        self._comprar(self.DOLARES, "GD30", 1000, 0.6, "USD")
        self._cobrar_bono(self.DOLARES, "GD30", "amortization", 80,
                          decrement_quantity=True, face_amortized=80)
        self.al_dia()

    def test_dos_cobros_de_bonos_distintos_se_suman(self):
        self._cobrar_bono(self.DOLARES, "GD30", "coupon", 100)
        self._cobrar_bono(self.DOLARES, "AE38", "coupon", 40)
        self.al_dia({self.DOLARES: 140.0, "global": 140.0})

    def test_borrar_el_cupon_lo_saca_del_mes_y_deshacer_lo_devuelve(self):
        self._cobrar_bono(self.DOLARES, "GD30", "coupon", 100)
        op = self._ultima_op()
        token = self._ok(self.http.delete(f"/api/operations/{op['id']}"))["undo_token"]
        self.assertEqual(self.mes(), {})
        self.ia_con_datos_viejos()
        self._ok(self.http.post(f"/api/operations/undo/{token}"))
        self.al_dia({self.DOLARES: 100.0, "global": 100.0})

    def test_el_pago_entero_de_la_bandeja_entra_al_mes_en_el_momento(self):
        """La bandeja de cobros de Cartera registra cupón + amortización de una
        (`/api/bonds/cashflow/pago`). Mientras esa puerta no exista, no hay nada
        que medir."""
        if not any(getattr(r, "path", "") == "/api/bonds/cashflow/pago"
                   for r in main.app.routes):
            self.skipTest("la bandeja de cobros de bonos todavía no está en esta rama")
        self._comprar(self.DOLARES, "GD30", 1000, 0.6, "USD")
        self.ia_con_datos_viejos()
        self._ok(self.http.post("/api/bonds/cashflow/pago", json={
            "broker": self.DOLARES, "asset": "GD30", "date": AYER,
            "coupon_amount": 20, "amort_amount": 80, "face_amortized": 80}))
        self.al_dia()


# ═════════════════════════════════════════════════════════════════════════════
class LasDemasPuertas(_Base):
    """Las que ya lo hacían bien, para que sigan."""

    def test_vender_en_dolares(self):
        self._comprar(self.DOLARES, "AAPL", 10, 100, "USD")
        self.ia_con_datos_viejos()
        self._ok(self.http.post("/api/positions/sell", json={
            "broker": self.DOLARES, "asset": "AAPL", "quantity": 4, "exit_price": 150,
            "date": AYER}))
        self.al_dia({self.DOLARES: 200.0, "global": 200.0})

    def test_vender_en_pesos(self):
        # 4 × ($8.000 / 1.250 − $5.000 / 1.000) = 4 × (6,40 − 5,00) = US$ 5,60
        self._comprar(self.PESOS, "GGAL", 10, 5000, "ARS", tc_compra=1000)
        self.ia_con_datos_viejos()
        self._ok(self.http.post("/api/positions/sell", json={
            "broker": self.PESOS, "asset": "GGAL", "quantity": 4, "exit_price": 8000,
            "date": AYER, "tc_venta": 1250}))
        self.al_dia()

    def test_vender_dolares_con_ganancia(self):
        self._depositar(self.PESOS, 2_000_000)
        self._ok(self.http.post("/api/conversions", json={
            "from_broker": self.PESOS, "direction": "ars_to_usd", "ars_amount": 1_000_000,
            "usd_amount": 1000, "tc": 1000, "kind": "MEP", "date": AYER}))
        self.ia_con_datos_viejos()
        self._ok(self.http.post("/api/conversions", json={
            "from_broker": f"{self.PESOS} · USD", "direction": "usd_to_ars",
            "ars_amount": 625_000, "usd_amount": 500, "tc": 1250, "kind": "MEP", "date": AYER}))
        # US$ 500 comprados a 1.000 y vendidos a 1.250: $125.000 = US$ 100.
        self.al_dia({f"{self.PESOS} · USD": 100.0, "global": 100.0})

    def test_cerrar_un_futuro(self):
        self._depositar(self.CRIPTO, 5000)
        f = self._ok(self.http.post("/api/futures", json={
            "broker": self.CRIPTO, "symbol": "BTCUSDT", "side": "long", "quantity": 0.5,
            "entry_price": 60000, "opened_at": "2026-08-01"}))
        self.ia_con_datos_viejos()
        self._ok(self.http.post(f"/api/futures/{f['id']}/close",
                                json={"exit_price": 62000, "closed_at": AYER}))
        self.al_dia({self.CRIPTO: 1000.0, "global": 1000.0})

    def test_cobrar_un_plazo_fijo(self):
        self._depositar(self.PESOS, 2_000_000)
        pid = self._ok(self.http.post("/api/plazos-fijos", json={
            "banco": "Galicia", "capital": 1_000_000, "moneda": "ARS", "tasa": 0.36,
            "fecha_inicio": (date.today() - timedelta(days=40)).isoformat(),
            "plazo_dias": 30, "source_broker": self.PESOS}))["id"]
        self.ia_con_datos_viejos()
        self._ok(self.http.post(f"/api/plazos-fijos/{pid}/cobrar", json={"broker": self.PESOS}))
        self.al_dia()

    def test_cargar_una_operacion_a_mano(self):
        self.ia_con_datos_viejos()
        self._ok(self.http.post("/api/operations", json={
            "date": AYER, "broker": self.DOLARES, "asset": "TSLA", "op_type": "Venta",
            "quantity": 1, "entry_price": 100, "exit_price": 180, "pnl_usd": 80}))
        self.al_dia({self.DOLARES: 80.0, "global": 80.0})

    def test_cobrar_un_dividendo_desde_la_bandeja(self):
        padre = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                  (self.uid, self.PESOS)).fetchone()["id"]
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
            (self.uid, f"{self.PESOS} · USD", "USDT", padre))
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, asset_type, currency)
               VALUES (?,?,?,0,?,?,?,?,?,?)""",
            (self.uid, self.PESOS, "KO", 14000, 150, 2100000, "2026-08-01", "CEDEAR", "ARS"))
        self.conn.commit()
        self.ia_con_datos_viejos()
        self._ok(self.http.post("/api/dividendos/cobro", json=dict(
            broker=self.PESOS, asset="KO", ex_date=CORTE_RECIENTE, fecha=AYER,
            bruto=15.90, impuesto=4.77, otros=0.80, comision_pesos=0, cedears=150)))
        self.al_dia({f"{self.PESOS} · USD": 10.33, "global": 10.33})


# ═════════════════════════════════════════════════════════════════════════════
class NadieAgregaUnaPuertaSinSuEscenario(unittest.TestCase):
    """Cada función del servidor que escribe en `operations`, con quién responde
    por el mes. Si aparece una que no está en la lista, este test se pone rojo:
    hay que agregarla con su escenario arriba (o decir por qué no hace falta)."""

    QUIEN_RESPONDE = {
        # — puertas que usa la gente: su escenario está en este archivo —
        "bond_cashflow":             "CobrarUnBono",
        "sell_position_fifo":        "test_vender_en_dolares / test_vender_en_pesos",
        "create_conversion":         "test_vender_dolares_con_ganancia",
        "close_futuro":              "test_cerrar_un_futuro",
        "cobrar_plazo_fijo":         "test_cobrar_un_plazo_fijo",
        "create_operation":          "test_cargar_una_operacion_a_mano",
        "registrar_cobro":           "test_cobrar_un_dividendo_desde_la_bandeja",
        # — deshacer —
        "undo_delete_asset_history": "recalcula al final (`_cascade_after_movement_delete`); "
                                     "test_borrar_conserva_el_dia",
        "restaurar_reemplazados":    "corre dentro de revertir un import, que recalcula; "
                                     "test_dividendos_bandeja",
        # — el importador: confirmar y reconstruir recalculan al terminar —
        "_persist_sell_fifo":            "import: confirm recalcula (test_importer)",
        "_persist_futures_pnl":          "import: confirm recalcula (test_importer)",
        "_persist_dividend_or_interest": "import: confirm recalcula (test_importer)",
        "_persist_fx":                   "import: confirm recalcula (test_importer)",
        "_write_rebuilt":                "reconstrucción: recalcula al terminar",
        # — llegan con la bandeja de cobros de bonos (rama `claude/bold-bouman-487b77`,
        #   sin publicar al 2026-10-10; este archivo se corrió contra ese código) —
        # El INSERT de `bond_cashflow` se muda a esta función, que usan
        # `/api/bonds/cashflow` y `/api/bonds/cashflow/pago`.
        "_registrar_cobro_bono":          "CobrarUnBono (incluye el pago entero de la bandeja)",
        "_restaurar_cobros_reemplazados": "corre dentro de revertir un import, antes de su recálculo",
        # — no son puertas —
        "init_db": "migración de arranque",
        "seed":    "datos de ejemplo de desarrollo",
    }

    def _las_que_escriben(self):
        halladas = {}
        for carpeta, _, archivos in os.walk(BACKEND):
            partes = set(os.path.relpath(carpeta, BACKEND).split(os.sep))
            if partes & {"tests", "scripts", "__pycache__", ".venv", "venv", "node_modules"}:
                continue
            for nombre in archivos:
                if not nombre.endswith(".py"):
                    continue
                ruta = os.path.join(carpeta, nombre)
                with open(ruta, encoding="utf-8") as fh:
                    fuente = fh.read()
                if not re.search(r"INSERT (OR \w+ )?INTO operations\b", fuente):
                    continue
                lineas = fuente.splitlines()
                funciones = [n for n in ast.walk(ast.parse(fuente))
                             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                for i, linea in enumerate(lineas, 1):
                    if not re.search(r"INSERT (OR \w+ )?INTO operations\b", linea):
                        continue
                    if linea.lstrip().startswith("#"):
                        continue
                    dentro = [f for f in funciones if f.lineno <= i <= f.end_lineno]
                    self.assertTrue(dentro, f"{nombre}:{i} escribe en operations fuera de una función")
                    # La de más afuera: la puerta, no un ayudante anidado.
                    puerta = min(dentro, key=lambda f: f.lineno).name
                    halladas.setdefault(puerta, f"{os.path.relpath(ruta, BACKEND)}:{i}")
        return halladas

    def test_toda_funcion_que_anota_operaciones_tiene_quien_responda_por_el_mes(self):
        halladas = self._las_que_escriben()
        self.assertGreaterEqual(len(halladas), 10, "el guardián dejó de encontrar las puertas")
        nuevas = {f: donde for f, donde in halladas.items() if f not in self.QUIEN_RESPONDE}
        self.assertFalse(
            nuevas,
            "Funciones que escriben en `operations` y no están en QUIEN_RESPONDE: "
            f"{nuevas}. Una puerta que anota una operación tiene que dejar el mes al día "
            "(`_recalc_pnl_realized_from_ops` en la misma transacción): agregale su "
            "escenario en este archivo y anotala en la lista.")


if __name__ == "__main__":
    unittest.main()
