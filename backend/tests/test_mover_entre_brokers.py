"""«Mover a otro broker»: la función entera, por el mismo camino que producción.

QUÉ ES. El usuario pasa títulos de un broker suyo (A) a otro suyo (B). No es una
venta: los lotes llegan a B con su costo y su fecha de compra, y A se queda sin
ellos. El capital aportado de B sube lo que valían ese día (V) y el de A baja lo
mismo; el resultado del mes de A lleva el «puente» V − C (C: lo que costaron) y el
de B el mismo con el signo al revés, así cada uno cierra al costo. En la cuenta
entera las dos patas se anulan (especificación, sección 0 y D.8).

EL ARNÉS (especificación F.1). Una cuenta con dos brokers en pesos (Cocos y Balanz)
y un token real (`main.create_token`): sin `dependency_overrides`, que saltea
`_contabilidad_tocada`. La historia entra por el importador de verdad
(`POST /api/imports/preview` + `/confirm`, formato `rendi_generic`), que corre el
persister, el recálculo y la reconstrucción a mercado (se espera a que termine).
Lo único reemplazado es lo que sale a internet: Yahoo (precios fijos), la lista de
bonos de data912 (vacía) y los benchmarks de Reportes (vacíos). El dólar de cada
día está sembrado en `fx_rates_daily`, así cada número se puede escribir a mano.

EL PASE: EL PLAN DE VERDAD, APLICADO POR UN ANDAMIO (`_fabricar_pase`). Desde la
etapa E5 las filas del pase las arma `traspaso_a_mano.armar_plan`, el MISMO que usa
la vista previa (`POST /api/positions/traspaso/vista-previa`) y que va a usar el
confirmar: las validaciones de B.6, los lotes, V, C y las filas. El endpoint que
las aplica (`POST /api/positions/traspaso`) llega en la etapa E6; hasta entonces las
aplica `_aplicar`, como lo va a hacer él (B.3 y C.7): turno, lotes tomados, plan,
`store_preview_txs` con `parser_format='traspaso_a_mano'` → `load_session_for_confirm`
→ `persist_batch`, la fila de `traspasos_a_mano`, y después la cola de cualquier
puerta (`_cascade_after_movement_delete`: cadena, RECÁLCULO REAL y fotos). Lo que se
mira sale de los endpoints reales (`GET /api/monthly`, el CSV mensual, Reportes, la
vista previa). E6 reemplaza el andamio por el endpoint y estas pruebas tienen que
seguir en verde.

LA RED. Lo único reemplazado es lo que sale a internet: Yahoo (precios mensuales y
los cambios de ratio de cada `.BA`, `main._splits_de_yahoo`), la lista de bonos de
data912 y los benchmarks de Reportes. El interruptor `mover_entre_brokers` se prende
en el `setUp` (en la base, como lo prende un admin) y se borra al terminar.

Los números de las pruebas son los de la tabla F.2 de la especificación (#n).

Corre con: cd backend && python3 -m pytest tests/test_mover_entre_brokers.py
"""
import csv
import io
import json
import os
import secrets
import sys
import time
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import fx  # noqa: E402
import snapshots_job  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from importing import pipeline as pl  # noqa: E402
from importing import persister as ps  # noqa: E402
from importing import tramo  # noqa: E402
from importing import traspaso_a_mano  # noqa: E402
from importing.recompute_backfill import recompute_user  # noqa: E402
from importing.schema import (  # noqa: E402
    NormalizedTx, OP_BUY, OP_SELL, OP_FEE, OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA,
)
from _limpieza import vaciar  # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"

TABLAS = ("traspasos_a_mano", "import_op_links", "import_normalized_tx", "import_raw_rows",
          "import_batches", "operations", "positions", "monthly_entries", "snapshots",
          "config", "brokers", "users")

# Los precios que alguna prueba siembra (el último precio y las velas del día).
SIMBOLOS_SEMBRADOS = ("NVDA.BA", "AAPL.BA", "BTC", "BTC-USD", "GGAL.BA")

# El dólar de cada día (blue = MEP), subiendo medio peso por día desde el 1/1/2025:
# uno distinto por fecha, así se ve de qué día salió cada número.
_DIA_0 = date(2025, 1, 1)
_DIAS = [_DIA_0 + timedelta(days=i) for i in range((date(2026, 12, 31) - _DIA_0).days + 1)]


def dolar(fecha: str) -> float:
    return round(1000.0 + (date.fromisoformat(fecha) - _DIA_0).days * 0.5, 2)


# Yahoo de mentira para la reconstrucción a mercado: el mismo cierre todos los meses.
PRECIOS = {f"{d.year}-{d.month:02d}": 40000.0 for d in _DIAS}

FECHA_PASE = "2025-06-16"
PRECIO_PASE = 45000.0          # NVDA (CEDEAR) en pesos el día del pase


def _ddmmaaaa(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


class _Cuenta(unittest.TestCase):
    """Cocos y Balanz, dos cuentas en pesos, con la historia de 2025 importada."""

    def setUp(self):
        conn = main.get_db()
        try:
            vaciar(conn, *TABLAS)
            conn.execute(f"DELETE FROM fx_rates_daily WHERE date >= ? AND date <= ?",
                         (_DIAS[0].isoformat(), _DIAS[-1].isoformat()))
            conn.executemany(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                "VALUES (?,?,?, 'test')",
                [(d.isoformat(), dolar(d.isoformat()), dolar(d.isoformat())) for d in _DIAS])
            self.uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, is_admin, tier) "
                "VALUES (?, 'x', 1, 1, 1, 'plus')",
                (f"mover-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
            for nombre in ("Cocos", "Balanz"):
                conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                             (self.uid, nombre))
            fx.set_fx_version(conn, self.uid, "v2")
            conn.commit()
        finally:
            conn.close()
        self._interruptor(True)
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        for nombre, valor in (("_fetch_data912_bonds", {}), ("_bench_para_reportes", {})):
            p = mock.patch.object(main, nombre, return_value=valor)
            p.start()
            self.addCleanup(p.stop)
        # Los cambios de ratio de Yahoo (`_splits_de_yahoo`, lo que va a internet):
        # {símbolo .BA: {fecha: factor}} que cada prueba siembra. La caché de main se
        # vacía antes y se restaura después: un split sembrado no puede filtrarse a
        # otra prueba.
        self.splits = {}
        p = mock.patch.object(main, "_splits_de_yahoo", lambda sym: dict(self.splits.get(sym, {})))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(main._splits_cache, clear=True)
        p.start()
        self.addCleanup(p.stop)
        # El dólar del día de dolarapi (lo que `precargar` trae para una cripto en una
        # cuenta en pesos): sin red, y la caché de main se restaura al terminar.
        p = mock.patch.object(main, "_fetch_dolar", return_value=None)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(main._dolar_cache)
        p.start()
        self.addCleanup(p.stop)
        self._fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda price_key, start_iso: dict(PRECIOS)

    def tearDown(self):
        bf._fetch_monthly_close = self._fetch_orig
        bf._HIST_CACHE.clear()
        self._esperar_reconstruccion()
        conn = main.get_db()
        try:
            vaciar(conn, *TABLAS)
            conn.execute("DELETE FROM fx_rates_daily WHERE date >= ? AND date <= ?",
                         (_DIAS[0].isoformat(), _DIAS[-1].isoformat()))
            for sym in SIMBOLOS_SEMBRADOS:
                conn.execute("DELETE FROM asset_last_price WHERE symbol=?", (sym,))
                conn.execute("DELETE FROM velas_diarias WHERE symbol=?", (sym,))
            conn.execute("DELETE FROM interruptores WHERE nombre=?", (traspaso_a_mano.INTERRUPTOR,))
            conn.commit()
        finally:
            conn.close()

    def _interruptor(self, encendido):
        """El interruptor `mover_entre_brokers`, en la base (como lo prende un admin)."""
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO interruptores (nombre, encendido, cambiado_at) VALUES (?, ?, "
                "datetime('now')) ON CONFLICT(nombre) DO UPDATE SET encendido=excluded.encendido",
                (traspaso_a_mano.INTERRUPTOR, 1 if encendido else 0))
            conn.commit()
        finally:
            conn.close()

    # ── las puertas reales ──────────────────────────────────────────────────────
    def _esperar_reconstruccion(self):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción a mercado no terminó en 60 s")

    def _importar(self, broker, filas):
        csv_txt = (HDR + "".join(f + "\n" for f in filas)).encode()
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(csv_txt), "text/csv"))],
                           data={"format": "rendi_generic", "broker": broker}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        self._esperar_reconstruccion()
        return c.json()

    def _historia(self):
        """2025: Cocos deposita $400.000 en enero y $100.000 cada mes, y el 10/01 compra
        10 NVDA a $30.000 con $1.500 de comisión. Balanz deposita $50.000 cada mes.
        Un depósito por mes en los dos: cada broker tiene fila todos los meses (la
        composición del año de Reportes necesita los doce)."""
        self._importar("Cocos", [
            "2025-01-05,DEPOSITO,Cocos,,,,400000,,,,ARS,dep",
            "2025-01-10,COMPRA,Cocos,NVDA,10,30000,300000,,,1500,ARS,compra",
            *[f"2025-{m:02d}-05,DEPOSITO,Cocos,,,,100000,,,,ARS,dep" for m in range(2, 13)]])
        self._importar("Balanz", [
            f"2025-{m:02d}-05,DEPOSITO,Balanz,,,,50000,,,,ARS,dep" for m in range(1, 13)])

    def _pedido(self, asset, origen, destino, fecha, *, moneda="ARS", **extra):
        """El cuerpo de la vista previa (`PaseIn`), sin los campos que van vacíos."""
        body = {"broker_origen": origen, "asset": asset, "moneda": moneda,
                "broker_destino": destino, "fecha": fecha}
        body.update({k: v for k, v in extra.items() if v is not None})
        return body

    def _vista(self, body, headers=None):
        """POST /api/positions/traspaso/vista-previa, como lo pide la pantalla."""
        return self.http.post("/api/positions/traspaso/vista-previa", json=body,
                              headers=headers or self.h)

    def _fabricar_pase(self, asset, origen, destino, fecha, precio, *, gasto=None,
                       cantidad=None, moneda="ARS"):
        """Un pase de `asset` de `origen` a `destino` (todo, o `cantidad`), con el
        precio escrito a mano (`precio_manual`) y, si hay, un gasto en pesos."""
        body = self._pedido(asset, origen, destino, fecha, moneda=moneda, precio_manual=precio,
                            cantidad=cantidad,
                            gasto=({"monto": gasto, "moneda": "ARS"} if gasto else None))
        return self._aplicar(body)

    def _aplicar(self, body):
        """El confirmar, como lo va a hacer `POST /api/positions/traspaso` (B.3 y C.7):
        el plan es el de verdad (`armar_plan`, el de la vista previa); lo que escribe
        es este andamio hasta que exista `aplicar_plan`.

        ⚠️ ANDAMIO DE LAS ETAPAS E4–E5: E6 lo reemplaza por el endpoint."""
        pedido = main.PaseIn(**body)
        conn = main.get_db()
        try:
            with conn:
                main._tomar_turno_de_la_puerta(conn, self.uid)
                hoy = main._iso_today()
                cuentas = traspaso_a_mano.cuentas_del_pedido(conn, self.uid, pedido, hoy=hoy)
                main._tomar_lotes(conn, self.uid, cuentas.patas_a, cuentas.asset)
                main._tomar_lotes(conn, self.uid, cuentas.patas_b, cuentas.asset)
                plan = traspaso_a_mano.armar_plan(conn, self.uid, pedido, hoy=hoy,
                                                  cuentas=cuentas, helpers=main._import_helpers,
                                                  para_confirmar=True)
                antes = main._foto_contable(conn, self.uid)
                tid = secrets.token_hex(16)
                # C.7.2 — las «· USD» que hagan falta, antes de cualquier otra escritura.
                for nombre in plan.brokers_a_crear:
                    raiz = nombre[:-len(" · USD")]
                    self.assertEqual(main._pata_de_la_moneda(conn, self.uid, raiz, "USD"), nombre)
                # C.7.3 — los cargados a mano salen de `positions`, primero.
                for l in plan.lotes:
                    if l.origen != "a_mano":
                        continue
                    q = float(l.lote["quantity"])
                    if l.parcial:
                        n = conn.execute(
                            "UPDATE positions SET quantity=?, invested=?, commissions=? "
                            "WHERE id=? AND user_id=? AND quantity=?",
                            (q - l.take,
                             (fx.costo_del_lote(l.lote["invested"], l.lote["buy_price"], q)
                              or 0) - l.mov_inv,
                             float(l.lote["commissions"] or 0) - l.mov_com,
                             l.lote_id, self.uid, q)).rowcount
                    else:
                        n = conn.execute("DELETE FROM positions WHERE id=? AND user_id=? AND quantity=?",
                                         (l.lote_id, self.uid, q)).rowcount
                    self.assertEqual(n, 1)
                filas_a, filas_b = plan.filas(tid)
                sid_a = pl.store_preview_txs(conn, self.uid, broker=cuentas.raiz_a,
                                             parser_format=traspaso_a_mano.FORMATO,
                                             file_name=traspaso_a_mano.ARCHIVO_DEL_PASE, txs=filas_a)
                sid_b = pl.store_preview_txs(conn, self.uid, broker=cuentas.raiz_b,
                                             parser_format=traspaso_a_mano.FORMATO,
                                             file_name=traspaso_a_mano.ARCHIVO_DEL_PASE, txs=filas_b)
                receta = plan.receta()
                _, raw_b = pl.load_session_for_confirm(conn, uid=self.uid, session_id=sid_b)
                for k, lote in enumerate(receta["lotes"]):
                    lote["fila_destino_raw_row_id"] = raw_b.get(traspaso_a_mano.BASE_ROW_INDEX + k)
                conn.execute(
                    "INSERT INTO traspasos_a_mano (id, user_id, lote_salida, lote_entrada, fecha, "
                    "asset, cantidad, moneda, receta_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tid, self.uid, sid_a, sid_b, plan.fecha, plan.asset, plan.cantidad,
                     plan.moneda, json.dumps(receta)))
                for sid in (sid_a, sid_b):
                    txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=sid)
                    r = ps.persist_batch(conn, uid=self.uid, batch_id=sid, txs=txs,
                                         raw_row_ids_by_index=raw, helpers=main._import_helpers)
                    self.assertEqual(r["skipped_rows"], [], r)
                if plan.precio_cargado_en_destino:
                    conn.execute(
                        "UPDATE positions SET price_override=? WHERE user_id=? AND broker IN "
                        f"({','.join('?' * len(cuentas.patas_b))}) AND asset=? AND is_cash=0",
                        (plan.precio_cargado_en_destino["puesto"], self.uid, *cuentas.patas_b,
                         plan.asset))
                main._cascade_after_movement_delete(conn, self.uid, plan.fecha,
                                                    set(plan.patas_tocadas), antes=antes)
        finally:
            conn.close()
        self._esperar_reconstruccion()
        return {"traspaso_id": tid, "lote_salida": sid_a, "lote_entrada": sid_b,
                "V": plan.valor_usd, "V_ars": plan.valor_ars, "C": plan.costo_usd,
                "C_nativo": sum(p["c_nativo"] for p in plan.pares()),
                "gasto_usd": plan.gasto["valor_usd"] if plan.gasto else 0.0,
                "cantidad": plan.cantidad, "plan": plan}

    def _rebuild(self):
        """«Después del rebuild» (F.1): el rearmado entero, como el backfill."""
        conn = main.get_db()
        try:
            with conn:
                recompute_user(conn, self.uid, recalc=main._recalc_pnl_realized_from_ops)
        finally:
            conn.close()

    # ── lo que se mira ──────────────────────────────────────────────────────────
    def _mensual(self):
        """GET /api/monthly, lo que pide /mensual: {(broker, año, mes): fila}."""
        r = self.http.get("/api/monthly", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return {(f["broker"], f["year"], f["month"]): f for f in r.json()}

    def _cadena(self, mensual, claves=("deposits", "withdrawals", "pnl_realized",
                                       "capital_final")):
        """Lo que la contabilidad dice de cada mes de 2025 (los cerrados)."""
        return {k: tuple(round(float(f[c] or 0), 4) for c in claves)
                for k, f in mensual.items() if k[1] == 2025}

    def estado(self):
        """La parte de `estado()` (F.1) que necesita esta etapa: caja y lotes por
        broker, cuántas 'Venta' hay, la contabilidad de cada mes y lo aportado."""
        conn = main.get_db()
        try:
            caja = {r["broker"]: round(float(r["c"] or 0), 4) for r in conn.execute(
                "SELECT broker, SUM(invested) c FROM positions WHERE user_id=? AND is_cash=1 "
                "GROUP BY broker", (self.uid,))}
            lotes = sorted(tuple(r) for r in conn.execute(
                "SELECT broker, asset, quantity, ROUND(invested, 4), ROUND(commissions, 4), "
                "substr(entry_date, 1, 10), substr(COALESCE(en_broker_desde, ''), 1, 10), "
                "tc_compra, currency, asset_type FROM positions WHERE user_id=? AND is_cash=0",
                (self.uid,)))
            ventas = conn.execute(
                "SELECT COUNT(*) c FROM operations WHERE user_id=? AND op_type='Venta'",
                (self.uid,)).fetchone()["c"]
            aportado = {b: round(snapshots_job.compute_net_deposited_db(
                conn, self.uid, broker_filter=b, include_baseline=(b == "global")), 4)
                for b in ("global", "Cocos", "Balanz")}
        finally:
            conn.close()
        return {"caja": caja, "lotes": lotes, "ventas": ventas, "aportado": aportado,
                "mensual": self._cadena(self._mensual())}

    def _cierra_la_cadena(self, mensual):
        """capital_final = capital_inicio + aportes − retiros + realizado, y cada mes
        arranca donde cerró el anterior: por broker y en 'global' (meses cerrados)."""
        por_broker = {}
        for (b, y, m), f in mensual.items():
            por_broker.setdefault(b, []).append(((y, m), f))
        for b, filas in por_broker.items():
            filas.sort()
            previo = None
            for (y, m), f in filas:
                if (y, m) >= (date.today().year, date.today().month):
                    continue
                ci, cf = float(f["capital_inicio"] or 0), float(f["capital_final"] or 0)
                esperado = ci + float(f["deposits"] or 0) - float(f["withdrawals"] or 0) \
                    + float(f["pnl_realized"] or 0)
                self.assertAlmostEqual(cf, esperado, delta=0.01, msg=f"{b} {y}-{m:02d}")
                if previo is not None:
                    self.assertAlmostEqual(ci, previo, delta=0.01, msg=f"{b} {y}-{m:02d} arranque")
                previo = cf


class AportadoYPuente(_Cuenta):

    def test_aportado_y_puente_por_broker_y_global(self):
        """#4. V ≠ C. A (Cocos): retiros +V y realizado +(V − C) en el mes del pase. B
        (Balanz): aportes +V y realizado −(V − C). La cuenta entera, igual que antes.
        El capital de A baja C y el de B sube C desde ese mes. La cadena cierra por
        broker y en 'global', también después del rebuild real."""
        self._historia()
        antes = self.estado()
        m_antes = self._mensual()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        V, C = p["V"], p["C"]
        # Los números del escenario, escritos a mano: el pase vale 10 × $45.000 al dólar
        # del 16/06 y costó $301.500 al dólar de la compra (10/01).
        self.assertAlmostEqual(V, 450000 / dolar(FECHA_PASE), places=6)
        self.assertAlmostEqual(C, 301500 / dolar("2025-01-10"), places=4)
        self.assertGreater(abs(V - C), 50, "el escenario necesita V ≠ C")

        m = self._mensual()
        a, b = ("Cocos", 2025, 6), ("Balanz", 2025, 6)
        self.assertAlmostEqual(m[a]["withdrawals"], m_antes[a]["withdrawals"] + V, places=3)
        self.assertAlmostEqual(m[a]["deposits"], m_antes[a]["deposits"], places=3)
        self.assertAlmostEqual(m[a]["pnl_realized"], m_antes[a]["pnl_realized"] + (V - C), places=3)
        self.assertAlmostEqual(m[b]["deposits"], m_antes[b]["deposits"] + V, places=3)
        self.assertAlmostEqual(m[b]["withdrawals"], m_antes[b]["withdrawals"], places=3)
        self.assertAlmostEqual(m[b]["pnl_realized"], m_antes[b]["pnl_realized"] - (V - C), places=3)
        # Desde el mes del pase, A queda con C menos de capital y B con C más.
        for mes in range(6, 13):
            for broker, signo in (("Cocos", -1), ("Balanz", +1)):
                k = (broker, 2025, mes)
                self.assertAlmostEqual(m[k]["capital_final"],
                                       m_antes[k]["capital_final"] + signo * C, places=3,
                                       msg=f"{broker} {mes}")
        for mes in range(1, 6):
            for broker in ("Cocos", "Balanz"):
                k = (broker, 2025, mes)
                self.assertAlmostEqual(m[k]["capital_final"], m_antes[k]["capital_final"],
                                       places=4)
        # La cuenta entera no se enteró: las patas se anulan.
        globales = {k: v for k, v in self._cadena(m).items() if k[0] == "global"}
        self.assertEqual(globales, {k: v for k, v in antes["mensual"].items() if k[0] == "global"})
        self._cierra_la_cadena(m)

        # Lo que la pantalla lee para explicarlo (contrato, notas de la tanda 2, punto 5).
        self.assertAlmostEqual(m[a]["puente_salida_usd"], V - C, places=4)
        self.assertNotIn("puente_entrada_usd", m[a])
        self.assertAlmostEqual(m[b]["puente_entrada_usd"], V - C, places=4)
        self.assertNotIn("puente_salida_usd", m[b])
        g = m[("global", 2025, 6)]
        for campo in ("puente_salida_usd", "puente_entrada_usd", "gasto_pase_usd",
                      "traspaso_neto_usd", "traspaso_neto_pesos"):
            self.assertNotIn(campo, g, f"con las dos patas vivas 'global' no lleva {campo}")
        # «Capital aportado» en pesos: las patas en pesos van aparte de lo importado.
        self.assertAlmostEqual(m[a]["traspaso_pesos_ret"], p["V_ars"], places=2)
        self.assertAlmostEqual(m[a]["traspaso_pesos_ret_usd"], V, places=4)
        self.assertAlmostEqual(m[b]["traspaso_pesos_dep"], p["V_ars"], places=2)
        self.assertAlmostEqual(m[b]["traspaso_pesos_dep_usd"], V, places=4)
        self.assertEqual(m[a]["pesos_importados_ret"], m_antes[a]["pesos_importados_ret"])
        self.assertEqual(m[b]["pesos_importados_dep"], m_antes[b]["pesos_importados_dep"])

        despues = self.estado()
        # Lo aportado: el total igual, A baja V y B sube V.
        self.assertAlmostEqual(despues["aportado"]["global"], antes["aportado"]["global"], places=3)
        self.assertAlmostEqual(despues["aportado"]["Cocos"], antes["aportado"]["Cocos"] - V, places=3)
        self.assertAlmostEqual(despues["aportado"]["Balanz"], antes["aportado"]["Balanz"] + V, places=3)
        # Las cajas no se tocan y no aparece ninguna venta.
        self.assertEqual(despues["caja"], antes["caja"])
        self.assertEqual(despues["ventas"], antes["ventas"])
        # El lote llegó a B con su costo y su fecha de compra; A se quedó sin NVDA.
        self.assertEqual([l for l in despues["lotes"] if l[1] == "NVDA"],
                         [("Balanz",) + l[1:6] + (FECHA_PASE,) + l[7:]
                          for l in antes["lotes"] if l[1] == "NVDA"])

        # Después del rebuild real, todo igual (el recálculo vuelve a leer las patas).
        self._rebuild()
        self.assertEqual(self.estado(), despues)
        self._cierra_la_cadena(self._mensual())

    def test_con_una_sola_pata_viva_global_cuenta_el_neto(self):
        """#4 (la otra mitad). Si se borra A, de la cuenta entera queda B como si hubiera
        arrancado con esos títulos al valor del día: 'global' suma V a lo aportado y
        −(V − C) al realizado, y lo explica con el neto (D.8.2, D.8.6, D.19)."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        V, C = p["V"], p["C"]
        conn = main.get_db()
        try:
            bid = conn.execute("SELECT id FROM brokers WHERE user_id=? AND name='Cocos'",
                               (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        r = self.http.delete(f"/api/brokers/{bid}", params={"force": "true"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        m = self._mensual()
        for (broker, y, mes), f in m.items():
            if broker != "global" or y != 2025:
                continue
            bz = m[("Balanz", y, mes)]
            for campo in ("deposits", "withdrawals", "pnl_realized"):
                self.assertAlmostEqual(f[campo], bz[campo], places=3, msg=f"{campo} {mes}")
        g = m[("global", 2025, 6)]
        self.assertAlmostEqual(g["traspaso_neto_usd"], V, places=4)
        self.assertAlmostEqual(g["traspaso_neto_pesos"], p["V_ars"], places=2)
        self.assertAlmostEqual(g["puente_entrada_usd"], V - C, places=4)
        self.assertNotIn("puente_salida_usd", g)
        self._cierra_la_cadena(m)
        # La IA (D.15.4): el realizado del año sigue siendo sólo trades cerrados; el
        # puente que quedó en 'global' viaja aparte.
        rep = self._paquete_de_reportes(2025)
        self.assertAlmostEqual(rep["traspasos_puente_year_usd"], round(-(V - C), 2), places=2)
        self.assertAlmostEqual(rep["realized_pnl_year_usd"], 0.0, places=2)
        self.assertIn("traspasos_puente_year_usd", rep["_field_docs"])

    def _paquete_de_reportes(self, anio):
        """Lo que recibe la IA sobre Reportes (`ai/builders/reports.py`)."""
        from ai.builders import reports as _reports
        conn = main.get_db()
        try:
            return _reports.build(conn, self.uid, year=anio)
        finally:
            conn.close()

    def test_broker_sin_otra_actividad_tiene_su_fila(self):
        """#4/#31 (núcleo). El mes del pase se siembra para las dos patas: un broker que
        recibe títulos un mes en que no tuvo ningún otro movimiento igual tiene su fila,
        con el aporte de V, el puente y su capital al costo."""
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'IOL', 'ARS')",
                         (self.uid,))
            conn.commit()
        finally:
            conn.close()
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "IOL", FECHA_PASE, PRECIO_PASE)
        V, C = p["V"], p["C"]
        m = self._mensual()
        f = m.get(("IOL", 2025, 6))
        self.assertIsNotNone(f, "el broker que recibió el pase no tiene fila del mes")
        self.assertAlmostEqual(f["deposits"], V, places=3)
        self.assertAlmostEqual(f["withdrawals"], 0.0, places=6)
        self.assertAlmostEqual(f["pnl_realized"], -(V - C), places=3)
        self.assertAlmostEqual(f["capital_final"], C, places=3)
        self._cierra_la_cadena(m)
        # Y con el paquete de la IA: con las dos patas vivas no hay puente en el año.
        rep = self._paquete_de_reportes(2025)
        self.assertEqual(rep["traspasos_puente_year_usd"], 0.0)
        self.assertAlmostEqual(rep["realized_pnl_year_usd"], 0.0, places=2)

    def test_gasto_es_perdida_del_que_lo_paga(self):
        """#8 (núcleo). El gasto del pase sale de la caja de A y es una pérdida de A: entra
        a su realizado (y al de la cuenta entera), así su capital sigue siendo su costo
        más su caja. Sin esto la FEE bajaba la caja sin ningún flujo que la explique."""
        self._historia()
        m_antes = self._mensual()
        antes = self.estado()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, gasto=5000.0)
        V, C, g = p["V"], p["C"], p["gasto_usd"]
        self.assertAlmostEqual(g, 5000.0 / dolar(FECHA_PASE), places=6)
        m = self._mensual()
        a, gl = ("Cocos", 2025, 6), ("global", 2025, 6)
        self.assertAlmostEqual(m[a]["pnl_realized"], m_antes[a]["pnl_realized"] + (V - C) - g, places=3)
        self.assertAlmostEqual(m[a]["gasto_pase_usd"], g, places=4)
        self.assertAlmostEqual(m[gl]["pnl_realized"], m_antes[gl]["pnl_realized"] - g, places=3)
        self.assertAlmostEqual(m[gl]["gasto_pase_usd"], g, places=4)
        for campo in ("deposits", "withdrawals"):
            self.assertAlmostEqual(m[gl][campo], m_antes[gl][campo], places=3)
        self.assertAlmostEqual(m[a]["capital_final"], m_antes[a]["capital_final"] - C - g, places=3)
        self._cierra_la_cadena(m)
        despues = self.estado()
        self.assertAlmostEqual(despues["caja"]["Cocos"], antes["caja"]["Cocos"] - 5000.0, places=2)
        self.assertEqual(despues["caja"]["Balanz"], antes["caja"]["Balanz"])


class RecalculoYMensual(_Cuenta):

    def test_recalculo_y_mensual_no_lo_vuelven_manual(self):
        """#5. El recálculo de siempre y el formulario de /mensual no convierten las patas
        del pase en un depósito o un retiro «a mano» (H14): `GET /api/monthly` igual
        antes y después de `POST /api/imports/recalc-pnl`; Movimientos sin filas
        manuales; un `PUT /api/monthly` de ese mes deja lo manual en 0 y el próximo
        recálculo vuelve a lo mismo."""
        self._historia()
        self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        m1 = self._mensual()
        r = self.http.post("/api/imports/recalc-pnl", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        # Fila por fila, con todos sus campos (los del pase incluidos). Sin el id: el
        # recálculo borra las filas del mes en curso que quedan en cero y el GET las
        # vuelve a crear (`_rollover_all_brokers`).
        sin_id = lambda m: {k: {c: v for c, v in f.items() if c != "id"} for k, f in m.items()}
        self.assertEqual(sin_id(self._mensual()), sin_id(m1))

        mov = self.http.get("/api/movements", headers=self.h)
        self.assertEqual(mov.status_code, 200, mov.text)
        filas = mov.json()
        filas = filas.get("movements", filas) if isinstance(filas, dict) else filas
        self.assertEqual([f for f in filas if f.get("source") == "monthly"], [],
                         "las patas del pase aparecieron como un movimiento a mano")

        for broker in ("Cocos", "Balanz"):
            f = m1[(broker, 2025, 6)]
            body = {c: f[c] for c in ("year", "month", "broker", "deposits", "withdrawals",
                                      "pnl_realized", "pnl_unrealized", "capital_inicio",
                                      "capital_final")}
            r = self.http.put(f"/api/monthly/{f['id']}", json=body, headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
            conn = main.get_db()
            try:
                man = conn.execute(
                    "SELECT manual_deposits, manual_withdrawals FROM monthly_entries WHERE id=?",
                    (f["id"],)).fetchone()
            finally:
                conn.close()
            # Menos de un centavo: el resto de redondeo que deja cualquier fila importada
            # (la fila guarda 4 decimales y lo importado se suma sin redondear). Lo que
            # no puede pasar es que la pata entera (V) quede como carga a mano.
            self.assertLess(abs(man["manual_deposits"] or 0), 0.01, broker)
            self.assertLess(abs(man["manual_withdrawals"] or 0), 0.01, broker)
        r = self.http.post("/api/imports/recalc-pnl", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        despues, antes = self._cadena(self._mensual()), self._cadena(m1)
        self.assertEqual(set(despues), set(antes))
        for k in antes:
            for x, y in zip(despues[k], antes[k]):
                self.assertAlmostEqual(x, y, delta=0.01, msg=f"{k}: {despues[k]} ≠ {antes[k]}")


class RendimientoEnReportes(_Cuenta):

    def _reporte(self, tipo, clave, broker):
        r = self.http.get(f"/api/reports/period/{tipo}/{clave}", params={"broker": broker},
                          headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_rendimiento_por_broker_del_mes_del_pase(self):
        """#41. Con un broker filtrado, el mes se mide con la contabilidad (Dietz de
        inicio, fin y flujos). Las patas al valor V daban a A +(V−C) de «ganancia» y a
        B lo mismo en contra en un mes sin ventas; con las patas al costo los dos dan 0.
        El año, que compone los doce meses, tampoco compone el puente. Los depósitos y
        retiros publicados siguen siendo los brutos, y la narrativa no dice que
        «aportaste» títulos que sólo cambiaron de broker."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        V, C = p["V"], p["C"]
        m = self._mensual()
        for broker, lado in (("Cocos", "salida"), ("Balanz", "entrada")):
            mes = self._reporte("month", "2025-06", broker)
            met = mes["metrics"]
            self.assertEqual(met["basis"], "contable", broker)
            self.assertAlmostEqual(met["delta_pct"], 0.0, places=6, msg=broker)
            self.assertAlmostEqual(met["delta_usd"], 0.0, places=2, msg=broker)
            fila = m[(broker, 2025, 6)]
            self.assertAlmostEqual(met["deposits"], round(fila["deposits"], 2), places=2)
            self.assertAlmostEqual(met["withdrawals"], round(fila["withdrawals"], 2), places=2)
            self.assertAlmostEqual(met[f"traspaso_{lado}_usd"], round(V, 2), places=2)
            self.assertAlmostEqual(met[f"traspaso_{lado}_costo_usd"], round(C, 2), places=2)
            narr = mes.get("narrative") or ""
            prep = "a" if lado == "salida" else "desde"
            self.assertIn(f"Pasaste títulos por US$ {round(V):,}".replace(",", "."), narr)
            self.assertIn(f"{prep} otro broker tuyo", narr)
            self.assertNotIn("Retiraste", narr, narr)

            anio = self._reporte("year", "2025", broker)["metrics"]
            self.assertAlmostEqual(anio["delta_pct"], 0.0, places=6, msg=f"año {broker}")
            self.assertAlmostEqual(anio["delta_usd"], 0.0, places=2, msg=f"año {broker}")


class PuenteEnPesos(_Cuenta):

    def test_puente_en_pesos(self):
        """#42. La pestaña en pesos de A muestra V − C en PESOS exacto (lo que valían
        menos lo que costaron los lotes, comisiones incluidas) y sin cartel: el
        realizado en pesos del mes del pase lo trae, con los dólares que cubre. B, lo
        mismo con el signo al revés; 'global', nada (las patas se anulan). El CSV
        mensual dice lo mismo."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        V, C, v_ars, c_ars = p["V"], p["C"], p["V_ars"], p["C_nativo"]
        self.assertEqual((v_ars, c_ars), (450000.0, 301500.0))
        m = self._mensual()
        a, b, g = m[("Cocos", 2025, 6)], m[("Balanz", 2025, 6)], m[("global", 2025, 6)]
        self.assertAlmostEqual(a["realized_ars"], v_ars - c_ars, places=2)
        self.assertAlmostEqual(a["realized_ars_cubre_usd"], V - C, places=4)
        self.assertFalse(a["realized_ars_valuado"])
        # Lo que la pantalla pasaría al dólar del mes con un cartel: nada.
        self.assertAlmostEqual(a["pnl_realized"] - a["realized_ars_cubre_usd"], 0.0, places=3)
        self.assertAlmostEqual(b["realized_ars"], -(v_ars - c_ars), places=2)
        self.assertAlmostEqual(b["realized_ars_cubre_usd"], -(V - C), places=4)
        self.assertEqual((g["realized_ars"], g["realized_ars_cubre_usd"]), (0.0, 0.0))

        r = self.http.get("/api/export/monthly.csv", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = list(csv.reader(io.StringIO(r.text)))
        cab = filas[0]
        i_per, i_bro = cab.index("Período"), cab.index("Broker")
        i_ars = next(i for i, c in enumerate(cab) if c.startswith("P&L realizado en pesos"))
        por = {(f[i_bro], f[i_per]): f[i_ars] for f in filas[1:]}
        self.assertAlmostEqual(float(por[("Cocos", "2025-06")]), v_ars - c_ars, places=2)
        self.assertAlmostEqual(float(por[("Balanz", "2025-06")]), -(v_ars - c_ars), places=2)
        self.assertEqual(por[("global", "2025-06")], "")


# ══════════════════════════════════════════════════════════════════════════════
# Etapa E5: la vista previa (`armar_plan`), por HTTP
# ══════════════════════════════════════════════════════════════════════════════

TABLAS_CONTADAS = ("import_batches", "import_normalized_tx", "import_raw_rows",
                   "import_op_links", "positions", "operations", "traspasos_a_mano",
                   "brokers", "monthly_entries", "snapshots", "config", "flujos_a_mano")


class _Vista(_Cuenta):
    """Lo que necesitan las pruebas de la vista previa: brokers, lotes a mano y lo que
    dice el servidor cuando frena (status y texto exacto de B.6)."""

    def _broker(self, nombre, moneda="ARS", padre=None):
        conn = main.get_db()
        try:
            pid = None
            if padre:
                pid = conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                   (self.uid, padre)).fetchone()["id"]
            bid = conn.execute(
                "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
                (self.uid, nombre, moneda, pid)).lastrowid
            conn.commit()
            return bid
        finally:
            conn.close()

    def _lote_a_mano(self, broker, asset, cantidad, precio, fecha, moneda="ARS", **extra):
        """Un lote cargado a mano por la puerta de siempre (`POST /api/positions`)."""
        body = {"broker": broker, "asset": asset, "quantity": cantidad, "buy_price": precio,
                "invested": round(cantidad * precio, 6), "entry_date": fecha,
                "currency": moneda, **extra}
        r = self.http.post("/api/positions", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        return self._lote(broker=None, asset=asset, entry_date=fecha)

    def _lote_viejo(self, broker, asset, cantidad, invertido, fecha, moneda):
        """Un lote como los que quedaron de antes de las reglas de hoy (en pesos en una
        pata en dólares, o sin fecha). Ninguna puerta los crea ya: se siembran."""
        conn = main.get_db()
        try:
            pid = conn.execute(
                "INSERT INTO positions (user_id, broker, asset, quantity, invested, buy_price, "
                "commissions, entry_date, is_cash, currency, asset_type) "
                "VALUES (?,?,?,?,?,?,0,?,0,?,?)",
                (self.uid, broker, asset, cantidad, invertido, invertido / cantidad, fecha,
                 moneda, "CRYPTO" if asset == "BTC" else "CEDEAR")).lastrowid
            conn.commit()
            return pid
        finally:
            conn.close()

    def _lote(self, broker=None, asset="NVDA", entry_date=None):
        conn = main.get_db()
        try:
            q = "SELECT * FROM positions WHERE user_id=? AND asset=? AND is_cash=0"
            args = [self.uid, asset]
            if broker:
                q += " AND broker=?"
                args.append(broker)
            if entry_date:
                q += " AND substr(entry_date, 1, 10)=?"
                args.append(entry_date)
            r = conn.execute(q + " ORDER BY id DESC LIMIT 1", args).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def _lotes(self, broker, asset="NVDA"):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT broker, quantity, invested, commissions, substr(entry_date, 1, 10) AS ed, "
                "substr(COALESCE(en_broker_desde, ''), 1, 10) AS desde, currency "
                "FROM positions WHERE user_id=? AND broker=? AND asset=? AND is_cash=0 "
                "ORDER BY entry_date, id", (self.uid, broker, asset)).fetchall()]
        finally:
            conn.close()

    def _no_puede(self, body, status, texto, headers=None):
        r = self._vista(body, headers=headers)
        self.assertEqual(r.status_code, status, r.text)
        self.assertEqual(r.json()["detail"], texto)
        return r

    def _ok(self, body):
        r = self._vista(body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _contar(self):
        conn = main.get_db()
        try:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                    for t in TABLAS_CONTADAS}
        finally:
            conn.close()


class VistaPrevia(_Vista):

    def test_vista_previa_no_escribe(self):
        """#27. Dos vistas previas iguales no escriben nada (las filas de cada tabla de la
        cuenta, contadas antes y después) y dan la misma firma. La respuesta trae lo que
        lee la pantalla (`VistaPreviaDelPase`), con los números a mano: 10 NVDA a
        $45.000 el 16/06, que costaron $300.000 + $1.500 el 10/01. Y el confirmar (acá,
        el andamio de E6) arma el MISMO plan: la misma firma."""
        self._historia()
        lote = self._lote("Cocos")
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        antes = self._contar()
        r1, r2 = self._vista(body), self._vista(body)
        self.assertEqual((r1.status_code, r2.status_code), (200, 200), r1.text)
        self.assertEqual(self._contar(), antes, "la vista previa escribió algo")
        j = r1.json()
        self.assertEqual(j["firma"], r2.json()["firma"])
        self.assertRegex(j["firma"], r"^[0-9a-f]{16}$")
        V, C = 450000 / dolar(FECHA_PASE), 301500 / dolar("2025-01-10")
        self.assertEqual(j, {
            "ok": True,
            "origen": {"cuenta": "Cocos", "etiqueta": "Cocos · en pesos"},
            "destino": {"cuenta": "Balanz", "brokers_a_crear": []},
            "asset": "NVDA", "moneda": "ARS", "fecha": FECHA_PASE,
            "cantidad": 10.0, "cantidad_disponible": 10.0,
            "lotes": [{"lote_id": lote["id"], "a_mano": False, "fecha_compra": "2025-01-10",
                       "cantidad": 10.0, "de_un_lote_de": 10.0, "costo": 300000.0,
                       "comisiones": 1500.0, "moneda": "ARS", "broker_origen": "Cocos",
                       "broker_destino": "Balanz"}],
            "valuacion": {"precio_unitario": PRECIO_PASE, "moneda_precio": "ARS",
                          "fuente": "precio_a_mano", "fecha_precio": FECHA_PASE,
                          "dolar": dolar(FECHA_PASE)},
            "valor_nativo": 450000.0, "valor_ars": 450000.0, "valor_usd": round(V, 2),
            "costo_usd": round(C, 2), "puente_usd": round(V - C, 2),
            "gasto": None, "avisos": [], "firma": j["firma"]})
        # La valuación vuelve tal cual al confirmar: tiene la forma exacta de `ValuacionIn`.
        main.ValuacionIn(**j["valuacion"])
        # La firma no lleva el precio (C.9): con otro precio, la misma.
        otra = self._ok({**body, "precio_manual": PRECIO_PASE + 1000})
        self.assertEqual(otra["firma"], j["firma"])
        self.assertNotEqual(otra["valor_nativo"], j["valor_nativo"])

        # Parte de un lote: 4 de los 10, en proporción (C.3); otra firma.
        p = self._ok({**body, "cantidad": 4})
        self.assertNotEqual(p["firma"], j["firma"])
        self.assertEqual({k: p["lotes"][0][k] for k in ("cantidad", "de_un_lote_de", "costo",
                                                       "comisiones")},
                         {"cantidad": 4.0, "de_un_lote_de": 10.0, "costo": 120000.0,
                          "comisiones": 600.0})
        self.assertEqual(self._contar(), antes)

        # El confirmar arma el mismo plan (la misma firma) y lo aplica.
        hecho = self._aplicar(body)
        self.assertEqual(hecho["plan"].firma, j["firma"])
        self.assertEqual(self._lotes("Balanz")[0]["desde"], FECHA_PASE)
        # Después del pase, la vista previa de lo mismo ya no encuentra lotes.
        self._no_puede(body, 400, "No tenés NVDA en Cocos en pesos que estuvieran ahí el "
                                  "16/06/2025.")

    def test_tramos_por_pata(self):
        """A.6, nota 1: la salida de los importados se parte en tramos contiguos de la
        misma pata, en el orden FIFO ([hija, padre, hija] → tres SELL), y los cargados a
        mano no tienen SELL (salen de `positions`). Sin base: un plan escrito a mano."""
        def lote(i, pata, q, origen="importado"):
            return traspaso_a_mano.LoteDelPlan(
                lote={"id": i, "quantity": q, "entry_date": f"2025-01-0{i}"}, origen=origen,
                fila_origen=None, asset_type="CEDEAR", asset_name=None, take=q, parcial=False,
                mov_inv=10.0 * q, mov_com=0.0, moneda="USD", pata_a=pata, pata_b="Balanz")
        plan = traspaso_a_mano.Plan(
            cuentas=None, cantidad=0, disponible=0,
            lotes=[lote(1, "Cocos · USD", 5), lote(2, "Cocos", 3), lote(3, "Cocos", 1, "a_mano"),
                   lote(4, "Cocos · USD", 2)],
            fx_version="v2", tc_blue=1, tc_venta=1, tc_pase=1, dolar_del_dia=1, precio=1,
            moneda_precio="USD", fuente="precio_a_mano", fecha_precio="", brokers_a_crear=[],
            gasto=None, precio_cargado_en_destino=None)
        self.assertEqual([(t["pata"], t["cantidad"], t["inv"]) for t in plan.tramos()],
                         [("Cocos · USD", 5, 50.0), ("Cocos", 3, 30.0), ("Cocos · USD", 2, 20.0)])


class ValidacionesDeLaVistaPrevia(_Vista):
    """B.6, cada una con su status y su texto exacto, en el orden de la tabla."""

    def test_fecha_brokers_interruptor_e_idor(self):
        """#1–#5, el interruptor apagado y otra cuenta (B.7: el mismo 404)."""
        self._historia()
        base = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        sin_fecha = {k: v for k, v in base.items() if k != "fecha"}
        self._no_puede(sin_fecha, 400, "Elegí la fecha del pase.")
        self._no_puede({**base, "fecha": ""}, 400, "Elegí la fecha del pase.")
        for mala in ("2025-02-30", "16/06/2025", "2025-6-16"):
            self._no_puede({**base, "fecha": mala}, 400,
                           "Fecha inválida. Usá el formato día/mes/año.")
        manana = (date.fromisoformat(main._iso_today()) + timedelta(days=1)).isoformat()
        self._no_puede({**base, "fecha": manana}, 400,
                       "La fecha del pase no puede ser posterior a hoy.")
        self._no_puede({**base, "broker_origen": "Nadie"}, 404,
                       "No encontramos ese broker en tu cuenta.")
        self._no_puede({**base, "broker_destino": "Nadie"}, 404,
                       "No encontramos el broker al que querés pasarlo. Si es nuevo, crealo "
                       "primero.")
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        mismo = "Ése es el mismo broker: las dos monedas de una cuenta son una sola. Elegí otro broker."
        self._no_puede({**base, "broker_destino": "Cocos · USD"}, 400, mismo)
        self._no_puede({**base, "broker_origen": "Cocos · USD", "broker_destino": "Cocos",
                        "moneda": "USD"}, 400, mismo)
        # Otra cuenta con los mismos nombres a la vista: para ella no existen.
        conn = main.get_db()
        try:
            otro = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'plus')", (f"otro-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        finally:
            conn.close()
        self._no_puede(base, 404, "No encontramos ese broker en tu cuenta.",
                       headers={"Authorization": f"Bearer {main.create_token(otro)}"})
        # Apagado, nadie arma pases nuevos.
        self._interruptor(False)
        self._no_puede(base, 403, "Esta opción no está disponible por ahora.")
        self._interruptor(True)
        self.assertEqual(self._vista(base).status_code, 200)

    def test_bloqueos_de_familia_tipo_y_wallbit(self):
        """#10 (y #6–#11): de un broker argentino a uno de afuera, un exchange, Wallbit, el
        efectivo, un bono, un fondo y un código de ticker viejo."""
        for nombre, moneda in (("Schwab", "USD"), ("Binance", "USDT"), ("Wallbit", "USD")):
            self._broker(nombre, moneda)
        self._lote_a_mano("Cocos", "NVDA", 5, 30000, "2025-02-03")
        base = self._pedido("NVDA", "Cocos", "Balanz", "2025-06-16", precio_manual=45000)
        self._no_puede({**base, "broker_destino": "Schwab"}, 400,
                       "No se puede pasar de Cocos a Schwab: uno opera en el mercado argentino "
                       "y el otro afuera. Un CEDEAR no es lo mismo que la acción de Estados "
                       "Unidos.")
        self._no_puede({**base, "broker_origen": "Binance", "broker_destino": "Schwab",
                        "moneda": "USD"}, 400,
                       "No se puede pasar de Binance a Schwab: uno es un exchange cripto y el "
                       "otro un broker.")
        self._no_puede({**base, "broker_destino": "Binance"}, 400,
                       "No se puede pasar de Cocos a Binance: uno es un exchange cripto y el "
                       "otro un broker.")
        wallbit = ("Wallbit se sincroniza sola con tu cuenta real: no se le pueden pasar ni "
                   "sacar títulos a mano.")
        self._no_puede({**base, "broker_destino": "Wallbit"}, 400, wallbit)
        self._no_puede({**base, "broker_origen": "Wallbit", "broker_destino": "Schwab",
                        "moneda": "USD"}, 400, wallbit)
        efectivo = ("El efectivo no se mueve con esta opción. Usá Retirar en un broker y "
                    "Depositar en el otro.")
        for caja in ("USD", "ARS", "usdt"):
            self._no_puede({**base, "asset": caja}, 400, efectivo)
        bono = "Por ahora los bonos y las letras no se pueden pasar entre brokers desde Rendi."
        self._no_puede({**base, "asset": "AL30"}, 400, bono)
        self._lote_a_mano("Cocos", "ONCRE", 100, 1000, "2025-02-03", asset_type="BOND")
        self._no_puede({**base, "asset": "ONCRE"}, 400, bono)
        fondo = ("Los fondos comunes no se pasan entre brokers: se rescatan en uno y se "
                 "suscriben en el otro. Registralo como una venta y una compra.")
        self._no_puede({**base, "asset": "FCI:COCOSPPA"}, 400, fondo)
        self._lote_a_mano("Cocos", "COCOSPPA", 100, 10, "2025-02-03", asset_type="FUND")
        self._no_puede({**base, "asset": "COCOSPPA"}, 400, fondo)
        self._no_puede({**base, "asset": "SQ"}, 409,
                       "SQ ahora cotiza como XYZ. Editá el lote para que diga XYZ y volvé a "
                       "moverlo.")
        self.assertEqual(self._vista(base).status_code, 200)

    def test_traspaso_automatico_ya_cerrado(self):
        """#12. El archivo de A ya trae la salida hacia B con la marca del cruce
        automático («Traspaso a {B}», sin pase): no se mueve dos veces. Vale también
        con B renombrado (la nota guarda el nombre viejo: `nombres_anteriores`)."""
        self._historia()
        self._importar("Cocos", ["2025-06-14,VENTA,Cocos,NVDA,10,45000,450000,,,0,ARS,"
                                 "Traspaso a Balanz el 14/06/2025"])
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede(body, 409, "Rendi ya pasó estos NVDA de Cocos a Balanz el 14/06, cuando "
                                  "importaste el archivo de Balanz. No hace falta moverlos otra vez.")
        conn = main.get_db()
        try:
            bid = conn.execute("SELECT id FROM brokers WHERE user_id=? AND name='Balanz'",
                               (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        r = self.http.put(f"/api/brokers/{bid}", json={"name": "Balanz Nuevo", "currency": "ARS"},
                          headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._no_puede({**body, "broker_destino": "Balanz Nuevo"}, 409,
                       "Rendi ya pasó estos NVDA de Cocos a Balanz Nuevo el 14/06, cuando "
                       "importaste el archivo de Balanz Nuevo. No hace falta moverlos otra vez.")
        # A más de 4 días ya no es ése (y no quedan lotes: el #17).
        self._no_puede({**body, "broker_destino": "Balanz Nuevo", "fecha": "2025-06-20"}, 400,
                       "No tenés NVDA en Cocos en pesos que estuvieran ahí el 20/06/2025.")

    def test_llegada_ya_importada_en_b(self):
        """#13 y su aviso: B ya trae la entrada en su archivo (marca IEB:DETR). A ≤ 60 días
        frena con las instrucciones; más lejos entra con un aviso."""
        self._historia()
        self._importar("Balanz", ["2025-06-14,COMPRA,Balanz,NVDA,10,30000,300000,,,0,ARS,"
                                  "Transferencia IEB:DETR"])
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede(body, 409, (
            "Balanz ya tiene registrada la llegada de 10 NVDA el 14/06 (vino en el archivo que "
            "importaste). Si la movés también a mano, se cuentan dos veces.\n\nHacé esto: en "
            "Movimientos, filtrá por Balanz y borrá la «Compra» de NVDA del 14/06 y el «Depósito» "
            "del mismo día. Después volvé y mové los NVDA desde Cocos con fecha 14/06: así quedan "
            "con lo que pagaste originalmente."))
        j = self._ok({**body, "fecha": "2025-09-20"})
        self.assertEqual(j["avisos"], ["Ojo: Balanz ya tiene una entrada de NVDA por traspaso "
                                       "del 14/06 (del archivo). Si es la misma, no la muevas a mano."])

    def test_fecha_antes_del_capital_declarado_frena(self):
        """#43 (#14). La historia de A arranca en marzo con un capital inicial cargado a
        mano: un pase de febrero lo volvería segundo renglón y la cadena le pisaría el
        capital. Lo mismo del lado de B."""
        r = self.http.post("/api/monthly", json={"year": 2025, "month": 3, "broker": "Cocos",
                                                 "capital_inicio": 100000,
                                                 "capital_final": 100000}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._lote_a_mano("Cocos", "NVDA", 5, 30000, "2025-03-15")
        body = self._pedido("NVDA", "Cocos", "Balanz", "2025-02-20", precio_manual=45000)
        self._no_puede(body, 409, (
            "Tu historia de Cocos en Rendi arranca en marzo de 2025 con un capital inicial que "
            "cargaste a mano. El pase no puede tener una fecha anterior: elegí desde el 01/03/2025."))
        r = self.http.post("/api/monthly", json={"year": 2025, "month": 4, "broker": "Balanz",
                                                 "capital_inicio": 5000, "capital_final": 5000},
                           headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._no_puede({**body, "fecha": "2025-03-20"}, 409, (
            "Tu historia de Balanz en Rendi arranca en abril de 2025 con un capital inicial que "
            "cargaste a mano. El pase no puede tener una fecha anterior: elegí desde el 01/04/2025."))
        self.assertEqual(self._ok({**body, "fecha": "2025-04-02"})["cantidad"], 5.0)

    def test_ventas_posteriores_en_a_y_en_b(self):
        """#15 y #16: una venta importada o a mano después de la fecha, en A o en B."""
        self._historia()
        self._importar("Cocos", ["2025-08-01,VENTA,Cocos,NVDA,4,50000,200000,,,0,ARS,venta"])
        self._importar("Balanz", ["2025-03-01,COMPRA,Balanz,NVDA,2,32000,64000,,,0,ARS,compra",
                                  "2025-09-01,VENTA,Balanz,NVDA,1,52000,52000,,,0,ARS,venta"])
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede(body, 409, "Después del 16/06/2025 vendiste NVDA en Cocos. Para no cambiar "
                                  "esas ventas, elegí una fecha del 01/08/2025 en adelante.")
        self._no_puede({**body, "fecha": "2025-08-01"}, 409, (
            "Después del 01/08/2025 vendiste NVDA en Balanz. Si lo pasamos con esa fecha "
            "cambiarían esas ventas: elegí una fecha del 01/09/2025 en adelante."))
        self.assertEqual(self._ok({**body, "fecha": "2025-09-01"})["cantidad"], 6.0)
        # Una venta a mano (la puerta «Vender»), también.
        r = self.http.post("/api/positions/sell", json={
            "broker": "Cocos", "asset": "NVDA", "quantity": 1, "exit_price": 51000,
            "date": "2025-10-01", "currency": "ARS"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._no_puede({**body, "fecha": "2025-09-01"}, 409, (
            "Después del 01/09/2025 vendiste NVDA en Cocos. Para no cambiar esas ventas, elegí "
            "una fecha del 01/10/2025 en adelante."))

    def test_pases_posteriores_en_a_y_en_b(self):
        """#15 y #16, cuando lo posterior es otro pase: el texto pide deshacerlo."""
        self._historia()
        self._broker("IOL")
        self._fabricar_pase("NVDA", "Cocos", "IOL", "2025-08-01", 50000, cantidad=4)
        self._no_puede(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE,
                                    precio_manual=PRECIO_PASE), 409,
                       "El 01/08/2025 ya pasaste NVDA de Cocos a IOL. Elegí una fecha del "
                       "01/08/2025 en adelante, o deshacé primero ese pase.")
        self._fabricar_pase("NVDA", "IOL", "Balanz", "2025-09-01", 51000, cantidad=2)
        self._no_puede(self._pedido("NVDA", "Cocos", "IOL", "2025-08-15",
                                    precio_manual=PRECIO_PASE), 409,
                       "El 01/09/2025 ya pasaste NVDA de IOL a Balanz. Elegí una fecha del "
                       "01/09/2025 en adelante, o deshacé primero ese pase.")

    def test_lotes_que_no_estaban_cantidad_y_sin_fecha(self):
        """#17, #18 y #19."""
        self._historia()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede({**body, "fecha": "2025-01-05"}, 400,
                       "No tenés NVDA en Cocos en pesos que estuvieran ahí el 05/01/2025.")
        self._no_puede({**body, "moneda": "USD"}, 400,
                       "No tenés NVDA en Cocos en dólares que estuvieran ahí el 16/06/2025.")
        self._no_puede({**body, "cantidad": 12}, 400,
                       "En Cocos tenés 10 NVDA en pesos que estaban ahí el 16/06/2025. No podés "
                       "pasar 12.")
        self._no_puede({**body, "cantidad": 10.5}, 400,
                       "En Cocos tenés 10 NVDA en pesos que estaban ahí el 16/06/2025. No podés "
                       "pasar 10,5.")
        self.assertEqual(self._ok({**body, "cantidad": 2.5})["lotes"][0]["costo"], 75000.0)
        self._lote_viejo("Cocos", "GGAL", 5, 5000.0, None, "ARS")
        self._no_puede({**body, "asset": "GGAL"}, 400,
                       "Uno de los lotes que se moverían no tiene fecha de compra. Editalo, poné "
                       "la fecha y volvé a intentar.")

    def test_split_pendiente_o_que_no_viaja_frena(self):
        """#35. Un cambio de ratio que A todavía no ajustó → #20. Ajustado en A (el aviso
        «Ajustar» de Cartera, `POST /api/positions/{id}/adjust-ratio`), B lo volvería a
        ofrecer sobre el lote que llega → #21."""
        self._historia()
        self.splits = {"NVDA.BA": {"2025-03-03": 3.0}}
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede(body, 409, "NVDA tuvo un cambio de ratio que todavía no ajustaste en Cocos. "
                                  "Primero ajustalo en Cartera (el aviso «Ajustar» de esa fila) y "
                                  "después volvé a moverlo.")
        lote = self._lote("Cocos")
        r = self.http.post(f"/api/positions/{lote['id']}/adjust-ratio", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertAlmostEqual(self._lote("Cocos")["quantity"], 30.0)
        self._no_puede(body, 409, (
            "En Cocos estos NVDA ya tienen aplicado un cambio de ratio que Balanz no conoce: si "
            "los pasamos, quedarían contados dos veces. Por ahora no se pueden pasar. Si los "
            "pasaste de verdad, podés registrar una venta en Cocos y una compra en Balanz (así sí "
            "cuenta como venta)."))

    def test_marca_de_split_corporativo_no_viaja(self):
        """#35, la otra mitad: A trae el split como un lote a $0 («Split 1:3», como Balanz),
        que en A cuenta como ya aplicado. Esa marca es de A: en B el cambio se volvería a
        ofrecer → #21."""
        self._historia()
        self.splits = {"NVDA.BA": {"2025-03-03": 3.0}}
        self._importar("Cocos", ["2025-03-05,COMPRA,Cocos,NVDA,20,0,0,,,0,ARS,Split 1:3"])
        self._no_puede(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE,
                                    precio_manual=PRECIO_PASE), 409, (
            "En Cocos estos NVDA ya tienen aplicado un cambio de ratio que Balanz no conoce: si "
            "los pasamos, quedarían contados dos veces. Por ahora no se pueden pasar. Si los "
            "pasaste de verdad, podés registrar una venta en Cocos y una compra en Balanz (así sí "
            "cuenta como venta)."))

    def _editar(self, lote, **cambios):
        body = {"broker": lote["broker"], "asset": lote["asset"], "quantity": lote["quantity"],
                "buy_price": lote["buy_price"], "invested": lote["invested"],
                "commissions": lote["commissions"], "entry_date": lote["entry_date"][:10],
                "currency": lote["currency"], "asset_type": lote["asset_type"], **cambios}
        r = self.http.put(f"/api/positions/{lote['id']}", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()

    def test_lote_importado_editado_frena(self):
        """#36. Un lote importado editado a mano (sólo `positions` cambia) en una A que va a
        quedar a salvo: el pase no cuadraría con el próximo rebuild → #23, con el campo
        que cambió. Si A conserva un lote cargado a mano, manda `positions` (C.2.7)."""
        self._historia()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        texto = ("El lote de NVDA del 10/01/2025 en Cocos vino de un archivo y lo cambiaste a mano "
                 "({}). Rendi arma Cocos desde tus archivos, así que el pase no cuadraría. Para "
                 "corregirlo de forma que quede: Importaciones → ese archivo → «Editar y rehacer», "
                 "corregí la fila y volvé a moverlo.")
        lote = self._lote("Cocos")
        self._editar(lote, quantity=12)
        self._no_puede(body, 409, texto.format("cantidad"))
        self._editar(lote, quantity=10, invested=310000)
        self._no_puede(body, 409, texto.format("costo"))
        self._editar(lote, quantity=12, invested=310000)
        self._no_puede(body, 409, texto.format("cantidad y costo"))
        # Con un lote a mano que se queda en A, A no está a salvo: manda lo que se ve.
        self._lote_a_mano("Cocos", "NVDA", 1, 40000, "2025-05-02")
        self.assertEqual(self._ok({**body, "cantidad": 12})["lotes"][0]["cantidad"], 12.0)
        # Pero si ese lote a mano también se va (todo), A queda a salvo DESPUÉS del pase
        # (`_is_safe_to_rebuild(..., sin_lotes=…)`) y la comprobación vuelve a frenar.
        self._no_puede(body, 409, texto.format("cantidad y costo"))
        self._editar(lote, quantity=10, invested=300000)
        self.assertEqual(self._ok(body)["cantidad"], 11.0)

    def test_lote_en_pesos_en_la_pata_en_dolares(self):
        """La contradicción C.1.3 contra C.1.4, decidida: la segunda condición de C.1.4
        (misma moneda de cuenta en A y en B) vale SÓLO para cripto, que es su motivo. Un
        CEDEAR en pesos que vive en «Cocos · USD» (dato de antes del freno de pesos) va
        a la raíz de B y el pase se aplica (#9); una cripto en pesos en la misma pata
        cambiaría de valuación (con y sin el dólar cripto) → #22."""
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        self._lote_viejo("Cocos · USD", "NVDA", 5, 150000.0, "2025-02-03", "ARS")
        body = self._pedido("NVDA", "Cocos · USD", "Balanz", "2025-06-16", precio_manual=45000)
        j = self._ok(body)
        self.assertEqual([(l["broker_origen"], l["broker_destino"], l["moneda"]) for l in j["lotes"]],
                         [("Cocos · USD", "Balanz", "ARS")])
        self.assertEqual(j["destino"]["brokers_a_crear"], [])
        self._aplicar(body)
        self.assertEqual([(l["quantity"], l["currency"]) for l in self._lotes("Balanz")],
                         [(5.0, "ARS")])
        self.assertEqual(self._lotes("Cocos · USD"), [])
        self._lote_viejo("Cocos · USD", "BTC", 0.01, 600000.0, "2025-02-03", "ARS")
        self._no_puede({**body, "asset": "BTC"}, 400,
                       "En Balanz BTC se cotiza distinto que en Cocos, así que no se puede pasar.")

    def test_pata_en_dolares_de_b(self):
        """Lotes en dólares de «Cocos · USD» a una B sin su «· USD»: la vista previa avisa
        que se va a crear y NO la crea; el confirmar la crea. Si ya hay un «Balanz · USD»
        en pesos con datos, no se puede crear → #24 con el motivo de
        `por_que_no_hay_pata_usd`, tal cual."""
        self._lote_a_mano("Cocos", "NVDA", 2, 20.0, "2025-02-03", moneda="USD", commissions=1.0)
        self.assertEqual(self._lote(asset="NVDA")["broker"], "Cocos · USD")
        body = self._pedido("NVDA", "Cocos", "Balanz", "2025-06-16", moneda="USD",
                            precio_manual=45000)
        antes = self._contar()
        j = self._ok(body)
        self.assertEqual(self._contar(), antes, "la vista previa creó algo")
        self.assertEqual(j["destino"]["brokers_a_crear"], ["Balanz · USD"])
        self.assertEqual(j["avisos"], ["Vamos a crear «Balanz · USD» para los lotes en dólares."])
        self.assertEqual(j["lotes"][0]["broker_destino"], "Balanz · USD")
        # Un CEDEAR en dólares se valúa por su precio en pesos ÷ el dólar del día (C.4.3).
        self.assertEqual(j["valuacion"]["moneda_precio"], "ARS")
        self.assertEqual(j["valuacion"]["dolar"], dolar("2025-06-16"))
        self.assertAlmostEqual(j["valor_usd"], round(2 * 45000 / dolar("2025-06-16"), 2), places=2)
        self.assertAlmostEqual(j["costo_usd"], 41.0, places=2)
        self._aplicar(body)
        self.assertEqual([l["quantity"] for l in self._lotes("Balanz · USD")], [2.0])
        # Otra vez, ahora con un «IOL · USD» en pesos con datos que no se puede adoptar.
        self._broker("IOL")
        self._broker("IOL · USD", "ARS")
        self._lote_a_mano("IOL · USD", "GGAL", 1, 1000, "2025-02-03")
        self._lote_a_mano("Cocos", "NVDA", 2, 20.0, "2025-02-04", moneda="USD")
        conn = main.get_db()
        try:
            iol = dict(conn.execute("SELECT id, name FROM brokers WHERE user_id=? AND name='IOL'",
                                    (self.uid,)).fetchone())
            motivo = pl.por_que_no_hay_pata_usd(conn, self.uid, iol)
        finally:
            conn.close()
        self.assertTrue(motivo)
        self._no_puede({**body, "broker_destino": "IOL"}, 409, motivo)

    def test_pesos_a_una_caja_en_dolares(self):
        """#25. Un lote en pesos que va a una pata sin caja en pesos."""
        self._broker("Schwab", "USD")
        self._broker("IBKR", "USD")
        self._lote_viejo("Schwab", "NVDA", 5, 150000.0, "2025-02-03", "ARS")
        self._no_puede(self._pedido("NVDA", "Schwab", "IBKR", "2025-06-16", precio_manual=45000),
                       400, "IBKR no tiene caja en pesos, y estos NVDA se compraron en pesos.")

    def test_precio_del_dia(self):
        """#26 y C.4.2: la vela del día, la última de la semana (con aviso), el último precio
        de hoy, el precio cargado a mano y, sin nada, el «sin precio» con la moneda."""
        self._historia()
        conn = main.get_db()
        try:
            conn.executemany("INSERT INTO velas_diarias (symbol, date, close) VALUES (?,?,?)",
                             [("NVDA.BA", "2025-06-12", 43000.0), ("NVDA.BA", "2025-06-13", 44000.0)])
            conn.commit()
        finally:
            conn.close()
        body = self._pedido("NVDA", "Cocos", "Balanz", "2025-06-13")
        j = self._ok(body)
        self.assertEqual({k: j["valuacion"][k] for k in ("precio_unitario", "fuente", "fecha_precio")},
                         {"precio_unitario": 44000.0, "fuente": "cierre_del_dia",
                          "fecha_precio": "2025-06-13"})
        self.assertEqual(j["avisos"], [])
        j = self._ok({**body, "fecha": "2025-06-15"})
        self.assertEqual({k: j["valuacion"][k] for k in ("precio_unitario", "fuente", "fecha_precio")},
                         {"precio_unitario": 44000.0, "fuente": "ultimo_precio",
                          "fecha_precio": "2025-06-13"})
        self.assertEqual(j["avisos"], ["Usamos el cierre del viernes 13/06."])
        self.assertAlmostEqual(j["valor_usd"], round(440000 / dolar("2025-06-15"), 2), places=2)
        r = self._no_puede({**body, "fecha": "2025-05-02"}, 409, {
            "codigo": "sin_precio",
            "mensaje": ("No encontramos a cuánto cotizaba NVDA el 02/05/2025. Escribí el precio de "
                        "ese día (en pesos) para calcular cuánto valía lo que pasaste."),
            "moneda_precio": "ARS"})
        hoy = main._iso_today()
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO asset_last_price (symbol, price, updated_at) VALUES (?,?,?)",
                         ("NVDA.BA", 61000.0, hoy + " 12:00:00"))
            conn.commit()
        finally:
            conn.close()
        j = self._ok({**body, "fecha": hoy})
        self.assertEqual({k: j["valuacion"][k] for k in ("precio_unitario", "fuente", "fecha_precio")},
                         {"precio_unitario": 61000.0, "fuente": "ultimo_precio", "fecha_precio": hoy})
        conn = main.get_db()
        try:
            conn.execute("UPDATE positions SET price_override=62000 WHERE user_id=? AND asset='NVDA'",
                         (self.uid,))
            conn.commit()
        finally:
            conn.close()
        j = self._ok({**body, "fecha": hoy})
        self.assertEqual({k: j["valuacion"][k] for k in ("precio_unitario", "fuente")},
                         {"precio_unitario": 62000.0, "fuente": "precio_cargado"})

    def test_gasto_del_tramite(self):
        """#27 y los avisos del gasto: en pesos desde una cuenta sin caja en pesos frena;
        la caja que queda en negativo se avisa con el monto (moneda adelante); en
        dólares desde una cuenta argentina sin su «· USD», se avisa que se crea."""
        self._historia()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        caja = 400000 + 11 * 100000 - 301500
        j = self._ok({**body, "gasto": {"monto": 2000000, "moneda": "ARS"}})
        self.assertEqual(j["gasto"], {"monto": 2000000.0, "moneda": "ARS", "broker": "Cocos",
                                      "caja_queda_negativa": True})
        queda = f"{caja - 2000000:,.0f}".replace(",", ".").replace("-", "")
        self.assertEqual(j["avisos"], [f"Con el gasto, la caja de Cocos queda en −${queda}."])
        j = self._ok({**body, "gasto": {"monto": 10, "moneda": "USD"}})
        self.assertEqual(j["gasto"]["broker"], "Cocos · USD")
        self.assertEqual(j["destino"]["brokers_a_crear"], [])
        self.assertIn("Vamos a crear «Cocos · USD» para el gasto en dólares.", j["avisos"])
        self._broker("Schwab", "USD")
        self._broker("IBKR", "USD")
        self._lote_a_mano("Schwab", "NVDA", 2, 100.0, "2025-02-03", moneda="USD")
        self._no_puede(self._pedido("NVDA", "Schwab", "IBKR", "2025-06-16", moneda="USD",
                                    precio_manual=120, gasto={"monto": 5000, "moneda": "ARS"}),
                       400, "Schwab no tiene caja en pesos.")

    def test_precio_muy_lejos_avisa(self):
        """El aviso de la banda (B.6), comparando en dólares: un precio escrito a mano
        mil veces más chico que lo que se pagó pide revisar la moneda."""
        self._historia()
        j = self._ok(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=10))
        k = (10 / dolar(FECHA_PASE)) / ((301500 / dolar("2025-01-10")) / 10)
        self.assertLess(k, 0.002)
        self.assertEqual(j["avisos"], [f"El precio de ese día está muy lejos de lo que pagaste "
                                       f"(×{traspaso_a_mano._veces(k)}). Revisá que esté en pesos."])

    def test_cripto_en_pesos(self):
        """#38. BTC en Cocos (lote en pesos) a otro broker argentino, con fecha de hoy:
        V = spot × dólar cripto, en pesos, y a dólares con el dólar del día (el factor
        cripto/MEP de Cartera). C con el dólar de la compra, no 1. Con fecha pasada no hay
        dólar cripto: «sin precio» en pesos; con el precio escrito a mano, sí."""
        hoy = main._iso_today()
        self._lote_a_mano("Cocos", "BTC", 0.01, 60000000, "2025-03-03", asset_type="CRYPTO")
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO asset_last_price (symbol, price, updated_at) VALUES (?,?,?)",
                         ("BTC", 95000.0, hoy + " 12:00:00"))
            conn.commit()
        finally:
            conn.close()
        cache = {"data": {"cripto": {"venta": 1500.0}}, "ts": time.time()}
        with mock.patch.dict(main._dolar_cache, cache):
            j = self._ok(self._pedido("BTC", "Cocos", "Balanz", hoy))
        self.assertEqual({k: j["valuacion"][k] for k in ("precio_unitario", "moneda_precio",
                                                         "fuente", "dolar")},
                         {"precio_unitario": 95000.0 * 1500.0, "moneda_precio": "ARS",
                          "fuente": "ultimo_precio", "dolar": dolar(hoy)})
        self.assertAlmostEqual(j["valor_ars"], 0.01 * 95000 * 1500, places=2)
        self.assertAlmostEqual(j["valor_usd"], round(0.01 * 95000 * (1500 / dolar(hoy)), 2), places=2)
        self.assertAlmostEqual(j["costo_usd"], round(600000 / dolar("2025-03-03"), 2), places=2)
        with mock.patch.dict(main._dolar_cache, cache):
            self._no_puede(self._pedido("BTC", "Cocos", "Balanz", "2025-06-16"), 409, {
                "codigo": "sin_precio",
                "mensaje": ("No encontramos a cuánto cotizaba BTC el 16/06/2025. Escribí el precio "
                            "de ese día (en pesos) para calcular cuánto valía lo que pasaste."),
                "moneda_precio": "ARS"})
            j = self._ok(self._pedido("BTC", "Cocos", "Balanz", "2025-06-16",
                                      precio_manual=100000000))
        self.assertEqual((j["valuacion"]["fuente"], j["valor_ars"]), ("precio_a_mano", 1000000.0))


class PasesEncadenados(_Vista):

    def _iol_a_cocos(self):
        """IOL compra AAPL el 10/01 y el 10/02 y el 10/06 los pasa a Cocos."""
        self._broker("IOL")
        self._importar("IOL", ["2025-01-05,DEPOSITO,IOL,,,,300000,,,,ARS,dep",
                               "2025-01-10,COMPRA,IOL,AAPL,5,20000,100000,,,0,ARS,compra",
                               "2025-02-10,COMPRA,IOL,AAPL,5,21000,105000,,,0,ARS,compra"])
        self._fabricar_pase("AAPL", "IOL", "Cocos", "2025-06-10", 25000)

    def test_pase_encadenado_usa_en_broker_desde(self):
        """#39. Los AAPL llegaron a Cocos el 10/06 con sus compras de enero y febrero. Un
        pase de Cocos con fecha anterior a esa llegada no los encuentra (#17); uno
        posterior los mueve con su compra original, y después del rebuild real Cocos
        queda sin AAPL."""
        self._iol_a_cocos()
        self.assertEqual([(l["ed"], l["desde"]) for l in self._lotes("Cocos", "AAPL")],
                         [("2025-01-10", "2025-06-10"), ("2025-02-10", "2025-06-10")])
        body = self._pedido("AAPL", "Cocos", "Balanz", "2025-05-01", precio_manual=26000)
        self._no_puede(body, 400, "No tenés AAPL en Cocos en pesos que estuvieran ahí el "
                                  "01/05/2025.")
        j = self._ok({**body, "fecha": "2025-06-15"})
        self.assertEqual([l["fecha_compra"] for l in j["lotes"]], ["2025-01-10", "2025-02-10"])
        self._aplicar({**body, "fecha": "2025-06-15"})
        self._rebuild()
        self.assertEqual(self._lotes("Cocos", "AAPL"), [])
        self.assertEqual([(l["ed"], l["desde"], l["quantity"]) for l in self._lotes("Balanz", "AAPL")],
                         [("2025-01-10", "2025-06-15", 5.0), ("2025-02-10", "2025-06-15", 5.0)])

    def test_la_salida_no_se_lleva_lo_que_llego_despues(self):
        """C.2.2 en el persister: Cocos tiene su propio AAPL (01/03) y los que llegaron de
        IOL el 10/06 (compras de enero y febrero, más viejas). Un pase de Cocos del 01/05
        mueve sólo el suyo: es lo que había ese día, lo que mostró la vista previa y lo
        que se lleva el registro. Antes el persister se llevaba el más viejo de HOY (uno
        que llegó después) y B recibía otro lote. Después del rebuild real, igual."""
        self._iol_a_cocos()
        self._importar("Cocos", ["2025-02-20,DEPOSITO,Cocos,,,,100000,,,,ARS,dep",
                                 "2025-03-01,COMPRA,Cocos,AAPL,2,22000,44000,,,0,ARS,compra"])
        body = self._pedido("AAPL", "Cocos", "Balanz", "2025-05-01", precio_manual=26000)
        j = self._ok(body)
        self.assertEqual((j["cantidad_disponible"], [l["fecha_compra"] for l in j["lotes"]]),
                         (2.0, ["2025-03-01"]))
        self._no_puede({**body, "cantidad": 3}, 400,
                       "En Cocos tenés 2 AAPL en pesos que estaban ahí el 01/05/2025. No podés "
                       "pasar 3.")
        self._aplicar(body)
        esperado_b = [("2025-03-01", "2025-05-01", 2.0)]
        esperado_a = [("2025-01-10", "2025-06-10", 5.0), ("2025-02-10", "2025-06-10", 5.0)]
        mirar = lambda b: [(l["ed"], l["desde"], l["quantity"]) for l in self._lotes(b, "AAPL")]
        self.assertEqual((mirar("Balanz"), mirar("Cocos")), (esperado_b, esperado_a))
        self._rebuild()
        self.assertEqual((mirar("Balanz"), mirar("Cocos")), (esperado_b, esperado_a))


class LaMonedaDelPar(_Vista):

    def test_moneda_de_la_cuenta_del_par(self):
        """`rebuild._moneda_del_par`: la moneda con que el replay resuelve una venta sin la
        suya (la del padre del par). Estaba copiada en los dos rearmados y la usa también
        la comprobación en seco del pase: una sola, con los mismos casos."""
        from importing import rebuild as rb
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        self._broker("Schwab", "USD")
        self._broker("Binance", "USDT")
        conn = main.get_db()
        try:
            dice = {tuple(p): rb._moneda_del_par(conn, self.uid, list(p)) for p in (
                ("Cocos", "Cocos · USD"), ("Cocos · USD",), ("Schwab",), ("Binance",), ("Nadie",))}
        finally:
            conn.close()
        self.assertEqual(dice, {("Cocos", "Cocos · USD"): "ARS", ("Cocos · USD",): "USD",
                                ("Schwab",): "USD", ("Binance",): "USD", ("Nadie",): "USD"})


class ElDetectorDeAportesNoCuentaLosPases(unittest.TestCase):
    """D.15.3. `detect_deposits_vs_gains` («la cartera creció por tus aportes, no por el
    mercado») no puede leer como aporte los títulos que llegaron desde otro broker
    del usuario: `deposits` los trae al valor del día. Es una función pura sobre el
    reporte; acá se le da uno escrito a mano."""

    @staticmethod
    def _reporte(deposits, entrada):
        from reporting.schema import PeriodMetrics, PeriodReport
        met = PeriodMetrics(start_value=1000.0, end_value=1000.0 + deposits, delta_usd=0.0,
                            delta_pct=0.0, delta_pct_over_contrib=None, realized_pnl=0.0,
                            unrealized_pnl=0.0, deposits=deposits, withdrawals=0.0,
                            trades_count=0, win_count=0, loss_count=0, win_rate=None,
                            vs_sp500_pct=None, vs_inflation_pct=None,
                            traspaso_entrada_usd=entrada, traspaso_entrada_costo_usd=entrada * 0.8)
        return PeriodReport(period_type="month", period_key="2025-06", period_label="Junio 2025",
                            period_start="2025-06-01", period_end="2025-06-30", is_current=False,
                            is_relevant=True, headline="", subheadline=None, metrics=met)

    def test_los_titulos_que_llegaron_no_son_aportes(self):
        from reporting.detectors import detect_deposits_vs_gains
        self.assertIsNotNone(detect_deposits_vs_gains(self._reporte(5000.0, 0.0)))
        self.assertIsNone(detect_deposits_vs_gains(self._reporte(5000.0, 5000.0)))
        ins = detect_deposits_vs_gains(self._reporte(5000.0, 2000.0))
        self.assertEqual(ins.evidence["deposits"], 3000.0)


class LaCuentaUnicaDeLasPatas(unittest.TestCase):
    """`traspaso_a_mano.resumen`: la cuenta que comparten el recálculo, /api/monthly,
    Movimientos y Reportes. Sin base: filas escritas a mano con la forma de
    `patas_del_registro`."""

    @staticmethod
    def _pata(tid, broker, op, v, c, v_ars=0.0, c_nat=0.0, moneda="ARS", fecha="2025-06-16"):
        return {"traspaso_id": tid, "broker": broker, "fecha": fecha, "op": op,
                "moneda": moneda, "valor_usd": v, "costo_usd": c, "valor_ars": v_ars,
                "costo_nativo": c_nat}

    def test_las_dos_patas_se_anulan_y_una_sola_cuenta_entera(self):
        filas = [self._pata("t1", "Cocos", "TRASPASO_SALIDA", 400.0, 300.0, 450000, 301500),
                 self._pata("t1", "Balanz", "TRASPASO_ENTRADA", 400.0, 300.0, 450000, 301500),
                 self._pata("t1", "Cocos", "FEE", 4.0, 0.0),
                 # Otro pase, en dólares y con pérdida, del que sólo vive la salida.
                 self._pata("t2", "IOL · USD", "TRASPASO_SALIDA", 100.0, 130.0, moneda="USD")]
        a = traspaso_a_mano.resumen(filas, ("Cocos",))
        self.assertEqual((a["dep_usd"], a["wit_usd"]), (0.0, 400.0))
        self.assertEqual((a["puente_salida_usd"], a["puente_entrada_usd"], a["gasto_usd"]),
                         (100.0, 0.0, 4.0))
        self.assertEqual((a["pesos_ret"], a["pesos_ret_usd"]), (450000, 400.0))
        self.assertEqual((a["puente_ars"], a["puente_ars_usd"]), (148500, 100.0))
        b = traspaso_a_mano.resumen(filas, ("Balanz",))
        self.assertEqual((b["dep_usd"], b["puente_entrada_usd"], b["puente_ars"]),
                         (400.0, 100.0, -148500))
        iol = traspaso_a_mano.resumen(filas, ("IOL", "IOL · USD"))
        self.assertEqual(iol["puente_salida_usd"], -30.0)
        self.assertEqual(iol["usd_con_dia"], {"dep": [], "ret": [["2025-06-16", 100.0]]})
        g = traspaso_a_mano.resumen(filas, None)
        # t1 se anula entero; de t2 queda la salida (con su pérdida); el gasto, entero.
        self.assertEqual((g["dep_usd"], g["wit_usd"]), (0.0, 100.0))
        self.assertEqual((g["puente_salida_usd"], g["puente_entrada_usd"], g["gasto_usd"]),
                         (-30.0, 0.0, 4.0))
        self.assertEqual((g["neto_usd"], g["puente_ars"]), (-100.0, 0.0))
        self.assertEqual((g["salida_valor_usd"], g["salida_costo_usd"]), (100.0, 130.0))
        # Lo lineal no depende de cómo se reparte: salida − entrada = la suma sin filtro.
        sin_filtro = sum((f["valor_usd"] - f["costo_usd"]) * (1 if f["op"] == "TRASPASO_SALIDA" else -1)
                         for f in filas if f["op"] != "FEE")
        self.assertAlmostEqual(g["puente_salida_usd"] - g["puente_entrada_usd"], sin_filtro)


if __name__ == "__main__":
    unittest.main()
