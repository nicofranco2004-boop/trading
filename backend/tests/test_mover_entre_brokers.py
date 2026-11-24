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

EL PASE, POR LAS PUERTAS DE PRODUCCIÓN (`_aplicar`, desde la etapa E6). Igual que
la pantalla: `POST /api/positions/traspaso/vista-previa` y después
`POST /api/positions/traspaso` con el mismo cuerpo, la `firma` y la `valuacion` que
devolvió la vista previa. El confirmar vuelve a armar el plan con los lotes tomados
(`traspaso_a_mano.armar_plan`), escribe todo o nada (`aplicar_plan`: los dos lotes
con `parser_format='traspaso_a_mano'`, `persist_batch`, la fila de
`traspasos_a_mano`) y corre la cola de cualquier puerta
(`_cascade_after_movement_delete`: cadena, RECÁLCULO REAL y fotos); al terminar el
pedido, la reconstrucción a mercado. Lo que se mira sale de los endpoints reales
(`GET /api/monthly`, el CSV mensual, Reportes, la vista previa) y de lo que quedó
escrito en la base. En E4–E5 lo escribía un andamio que imitaba al confirmar; estas
pruebas lo cambiaron por el endpoint y siguieron en verde.

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
import sys
import time
import unittest
import uuid
from datetime import date, datetime, timedelta
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
from _sentencias import escrituras  # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"

TABLAS = ("traspasos_a_mano", "import_op_links", "import_normalized_tx", "import_raw_rows",
          "import_batches", "operations", "positions", "monthly_entries", "snapshots",
          "config", "brokers", "users")

# Los precios que alguna prueba siembra (el último precio y las velas del día).
SIMBOLOS_SEMBRADOS = ("NVDA.BA", "AAPL.BA", "BTC", "BTC-USD", "GGAL.BA")

# El dólar de cada día (blue = MEP), subiendo medio peso por día desde el 1/1/2025:
# uno distinto por fecha, así se ve de qué día salió cada número.
_DIA_0 = date(2025, 1, 1)
# Hasta fin de 2026 o pasado mañana, lo que venga después: hay pruebas con fecha de
# HOY, y una siembra con fecha fija vence (el día real la pasa).
_HASTA = max(date(2026, 12, 31), date.today() + timedelta(days=2))
_DIAS = [_DIA_0 + timedelta(days=i) for i in range((_HASTA - _DIA_0).days + 1)]


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

    def _importar(self, broker, filas, hdr=HDR):
        csv_txt = (hdr + "".join(f + "\n" for f in filas)).encode()
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

    def _confirmar(self, body, *, vista=None, headers=None, **cambios):
        """POST /api/positions/traspaso como lo manda la pantalla (`MoverDeBrokerModal`):
        el MISMO cuerpo de la vista previa, más la `firma` y la `valuacion` que ésta
        devolvió. `cambios` reemplaza campos del pedido (una firma vieja, otra
        valuación) para las pruebas de lo que el servidor rechaza."""
        if vista is None:
            r = self._vista(body, headers=headers)
            self.assertEqual(r.status_code, 200, r.text)
            vista = r.json()
        pedido = {**body, "firma": vista["firma"], "valuacion": vista["valuacion"], **cambios}
        pedido = {k: v for k, v in pedido.items() if v is not None}
        return self.http.post("/api/positions/traspaso", json=pedido, headers=headers or self.h)

    def _aplicar(self, body):
        """El pase entero por las puertas de producción: la vista previa y el confirmar
        (`POST /api/positions/traspaso`), que arma el plan con los lotes tomados,
        compara la firma, escribe todo o nada y corre la cola de cualquier puerta
        (cadena, RECÁLCULO REAL, fotos); al terminar el pedido, la reconstrucción a
        mercado. Lo que devuelve sale de lo que quedó ESCRITO (las patas del pase en
        la base, sin redondear), no de la vista previa."""
        r = self._vista(body)
        self.assertEqual(r.status_code, 200, r.text)
        vista = r.json()
        c = self._confirmar(body, vista=vista)
        self.assertEqual(c.status_code, 200, c.text)
        self._esperar_reconstruccion()
        hecho = c.json()
        self.assertEqual(set(hecho), {"ok", "traspaso_id", "mensaje"})
        return {**self._pase_escrito(hecho["traspaso_id"]), "vista": vista,
                "mensaje": hecho["mensaje"]}

    def _pase_escrito(self, tid):
        """Lo que el pase `tid` dejó en la base: el registro y las cuentas de sus patas
        (V, V en pesos, C y C nativo de las TRASPASO_SALIDA; el gasto de su FEE)."""
        conn = main.get_db()
        try:
            reg = dict(conn.execute("SELECT * FROM traspasos_a_mano WHERE id=? AND user_id=?",
                                    (tid, self.uid)).fetchone())
            filas = [dict(f) for f in conn.execute(
                "SELECT n.* FROM import_normalized_tx n WHERE n.traspaso_id=? "
                "AND n.batch_id IN (?, ?) ORDER BY n.id",
                (tid, reg["lote_salida"], reg["lote_entrada"])).fetchall()]
        finally:
            conn.close()
        salida = [f for f in filas if f["operation_type"] == OP_TRASPASO_SALIDA]
        gasto = [f for f in filas if f["operation_type"] == OP_FEE]
        return {"traspaso_id": tid, "lote_salida": reg["lote_salida"],
                "lote_entrada": reg["lote_entrada"], "registro": reg,
                "receta": json.loads(reg["receta_json"]), "filas": filas,
                "V": sum(f["valor_usd"] for f in salida),
                "V_ars": sum(f["valor_ars"] for f in salida),
                "C": sum(f["costo_usd"] for f in salida),
                "C_nativo": sum(f["costo_nativo"] for f in salida),
                "gasto_usd": sum(f["valor_usd"] for f in gasto),
                "cantidad": reg["cantidad"]}

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
        """Lo que la contabilidad dice de cada mes, por broker y en 'global'."""
        return {k: tuple(round(float(f[c] or 0), 4) for c in claves)
                for k, f in mensual.items()}

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
        """#31 (test_cadena_y_meses_sembrados_en_broker_nuevo). El mes del pase se siembra
        para las dos patas: un broker que recibe títulos un mes en que no tuvo ningún
        otro movimiento igual tiene su fila, con el aporte de V, el puente y su capital
        al costo; y la cadena sigue: los meses siguientes arrancan y cierran con ese
        capital."""
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
        for mes in range(7, 13):
            g = m.get(("IOL", 2025, mes))
            self.assertIsNotNone(g, f"la cadena de IOL se cortó en {mes}/2025")
            self.assertAlmostEqual(g["capital_inicio"], C, places=3, msg=f"{mes}")
            self.assertAlmostEqual(g["capital_final"], C, places=3, msg=f"{mes}")
        self.assertNotIn(("IOL", 2025, 5), m, "IOL no tenía nada antes del pase")
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


class PuenteNegativo(_Cuenta):

    def test_puente_con_v_menor_que_c(self):
        """El puente con V < C, por HTTP: los títulos valían menos de lo que costaron (10
        NVDA a $20.000 el 16/06; costaron $301.500 el 10/01). A lleva la pérdida V − C y B
        la ganancia C − V en el mes del pase; el global no cambia. (Con el valor absoluto
        del puente en el recálculo, A ganaba lo que perdía.)"""
        self._historia()
        antes = self._mensual()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, 20000.0)
        self.assertLess(p["V"], p["C"])
        m = self._mensual()
        delta = lambda b: m[(b, 2025, 6)]["pnl_realized"] - antes[(b, 2025, 6)]["pnl_realized"]
        self.assertAlmostEqual(delta("Cocos"), p["V"] - p["C"], places=4)
        self.assertAlmostEqual(delta("Balanz"), p["C"] - p["V"], places=4)
        self.assertAlmostEqual(delta("global"), 0.0, places=4)
        self._cierra_la_cadena(m)


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

    def _editar(self, lote, **cambios):
        body = {"broker": lote["broker"], "asset": lote["asset"], "quantity": lote["quantity"],
                "buy_price": lote["buy_price"], "invested": lote["invested"],
                "commissions": lote["commissions"], "entry_date": lote["entry_date"][:10],
                "currency": lote["currency"], "asset_type": lote["asset_type"], **cambios}
        r = self.http.put(f"/api/positions/{lote['id']}", json=body, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()

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

    def _tablas(self):
        """Cada fila de la cuenta en las tablas que un pase escribe, tal cual (con ids):
        si un pase que falla dejara CUALQUIER cosa, esto cambia."""
        conn = main.get_db()
        try:
            out = {}
            for t, orden in (("positions", "id"), ("brokers", "id"), ("operations", "id"),
                             ("monthly_entries", "id"), ("traspasos_a_mano", "id"),
                             ("import_batches", "id"), ("flujos_a_mano", "id")):
                out[t] = [tuple(r) for r in conn.execute(
                    f"SELECT * FROM {t} WHERE user_id=? ORDER BY {orden}", (self.uid,))]
            out["import_normalized_tx"] = [tuple(r) for r in conn.execute(
                "SELECT n.* FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
                "WHERE b.user_id=? ORDER BY n.id", (self.uid,))]
            out["config"] = [tuple(r) for r in conn.execute(
                "SELECT key, value FROM config WHERE user_id=? ORDER BY key", (self.uid,))]
            return out
        finally:
            conn.close()

    def _sin_ids(self, broker, asset="NVDA"):
        """Los lotes de (broker, activo) como los ve la persona: sin ids."""
        conn = main.get_db()
        try:
            return [tuple(r) for r in conn.execute(
                "SELECT quantity, ROUND(invested, 6), ROUND(commissions, 6), "
                "substr(entry_date, 1, 10), substr(COALESCE(en_broker_desde, ''), 1, 10), "
                "tc_compra, currency, asset_type FROM positions WHERE user_id=? AND broker=? "
                "AND asset=? AND is_cash=0 ORDER BY entry_date, id",
                (self.uid, broker, asset)).fetchall()]
        finally:
            conn.close()


class VistaPrevia(_Vista):

    def test_vista_previa_no_escribe(self):
        """#27. Dos vistas previas iguales no escriben nada y dan la misma firma. «No
        escriben» se mira en la sentencia (`_sentencias.escrituras`: ningún INSERT,
        UPDATE ni DELETE corre durante el pedido) y en el contenido de cada fila de la
        cuenta (no sólo en cuántas hay: un UPDATE no cambia ningún conteo, y lo que no
        se commitea se deshace solo al cerrar la conexión). La respuesta trae lo que
        lee la pantalla (`VistaPreviaDelPase`), con los números a mano: 10 NVDA a
        $45.000 el 16/06, que costaron $300.000 + $1.500 el 10/01. Y el confirmar arma
        el MISMO plan: la misma firma."""
        self._historia()
        lote = self._lote("Cocos")
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        antes, filas = self._contar(), self._tablas()
        with escrituras(main) as escribio:
            r1, r2 = self._vista(body), self._vista(body)
        self.assertEqual((r1.status_code, r2.status_code), (200, 200), r1.text)
        self.assertEqual(escribio, [], "la vista previa escribió en la base")
        self.assertEqual(self._contar(), antes, "la vista previa escribió algo")
        self.assertEqual(self._tablas(), filas, "la vista previa cambió una fila")
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

        # El confirmar arma el mismo plan: acepta la firma de la PRIMERA vista previa
        # (si su plan diera otra, contestaría 409 «Tu cartera cambió…»).
        r = self._confirmar(body, vista=j)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
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
        """#15 y #16: una venta importada o a mano después de la fecha, en A o en B. En B
        cuenta también la del mismo día (`test_salida_de_b_el_mismo_dia_frena`), así que la
        fecha que se propone es la del día siguiente a la última venta."""
        self._historia()
        self._importar("Cocos", ["2025-08-01,VENTA,Cocos,NVDA,4,50000,200000,,,0,ARS,venta"])
        self._importar("Balanz", ["2025-03-01,COMPRA,Balanz,NVDA,2,32000,64000,,,0,ARS,compra",
                                  "2025-09-01,VENTA,Balanz,NVDA,1,52000,52000,,,0,ARS,venta"])
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede(body, 409, "Después del 16/06/2025 vendiste NVDA en Cocos. Para no cambiar "
                                  "esas ventas, elegí una fecha del 01/08/2025 en adelante.")
        self._no_puede({**body, "fecha": "2025-08-01"}, 409, (
            "Después del 01/08/2025 vendiste NVDA en Balanz. Si lo pasamos con esa fecha "
            "cambiarían esas ventas: elegí una fecha del 02/09/2025 en adelante."))
        self._no_puede({**body, "fecha": "2025-09-01"}, 409, (
            "El 01/09/2025 vendiste NVDA en Balanz. Si lo pasamos con esa fecha cambiarían "
            "esas ventas: elegí una fecha del 02/09/2025 en adelante."))
        self.assertEqual(self._ok({**body, "fecha": "2025-09-02"})["cantidad"], 6.0)
        # Una venta a mano (la puerta «Vender»), también.
        r = self.http.post("/api/positions/sell", json={
            "broker": "Cocos", "asset": "NVDA", "quantity": 1, "exit_price": 51000,
            "date": "2025-10-01", "currency": "ARS"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._no_puede({**body, "fecha": "2025-09-02"}, 409, (
            "Después del 02/09/2025 vendiste NVDA en Cocos. Para no cambiar esas ventas, elegí "
            "una fecha del 01/10/2025 en adelante."))

    def test_salida_de_b_el_mismo_dia_frena(self):
        """#16 desde el MISMO día. Balanz ya tenía 3 NVDA propios (01/03) y vendió 1 el
        16/06, el día del pase: cuando se importó, esa venta consumió un lote de Balanz.
        Con el pase del 16/06, el próximo rebuild de Balanz ordenaría ese día «la compra
        antes que la venta» y, por fecha de compra (H2), la haría consumir el lote que
        llegó (de enero): cambiarían los lotes y el resultado de la venta sin que nadie
        haga nada. Frena, y propone el día siguiente; con el 17/06 pasa y el rebuild no
        cambia nada. Lo mismo con un pase que sacó NVDA de Balanz ese día. En A, una
        venta del mismo día NO frena: las dos salidas se ordenan por id (control)."""
        self._historia()
        self._importar("Balanz", ["2025-03-01,COMPRA,Balanz,NVDA,3,35000,105000,,,0,ARS,compra",
                                  f"{FECHA_PASE},VENTA,Balanz,NVDA,1,50000,50000,,,0,ARS,venta"])
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede(body, 409, (
            "El 16/06/2025 vendiste NVDA en Balanz. Si lo pasamos con esa fecha cambiarían esas "
            "ventas: elegí una fecha del 17/06/2025 en adelante."))
        self._broker("IOL")
        self._fabricar_pase("NVDA", "Balanz", "IOL", "2025-06-20", 46000, cantidad=1)
        self._no_puede({**body, "fecha": "2025-06-20"}, 409, (
            "El 20/06/2025 ya pasaste NVDA de Balanz a IOL. Elegí una fecha del 21/06/2025 en "
            "adelante, o deshacé primero ese pase."))
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", "2025-06-21", PRECIO_PASE)
        self.assertEqual(p["cantidad"], 10.0)
        conn = main.get_db()
        ventas = lambda: [(r["date"][:10], r["quantity"], round(r["pnl_usd"] or 0, 6))
                          for r in conn.execute(
                              "SELECT date, quantity, pnl_usd FROM operations WHERE user_id=? "
                              "AND op_type='Venta' ORDER BY id", (self.uid,)).fetchall()]
        try:
            lotes, vendidas = self._sin_ids("Balanz"), ventas()
        finally:
            conn.close()
        self._rebuild()
        conn = main.get_db()
        try:
            self.assertEqual((self._sin_ids("Balanz"), ventas()), (lotes, vendidas))
        finally:
            conn.close()

        # En A, una venta del mismo día no frena, y el rebuild no cambia nada.
        self._importar("Balanz", ["2025-07-01,VENTA,Balanz,NVDA,1,52000,52000,,,0,ARS,venta"])
        self._fabricar_pase("NVDA", "Balanz", "Cocos", "2025-07-01", 52000, cantidad=2)
        conn = main.get_db()
        try:
            antes = (self._sin_ids("Balanz"), self._sin_ids("Cocos"), ventas())
        finally:
            conn.close()
        self._rebuild()
        conn = main.get_db()
        try:
            self.assertEqual((self._sin_ids("Balanz"), self._sin_ids("Cocos"), ventas()), antes)
        finally:
            conn.close()

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
                       "02/09/2025 en adelante, o deshacé primero ese pase.")

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

    def test_pata_usd_suelta_con_movimientos_frena(self):
        """«Balanz · USD» existe como broker SUELTO (sin padre), en dólares y con
        movimientos: una compra el 01/02 y una venta el 01/08. El confirmar lo adoptaría
        como la pata en dólares de Balanz (`_ensure_usd_sibling`) sin que el plan hubiera
        mirado su venta posterior (#16): el próximo rebuild la hacía consumir el lote que
        llegó, más viejo (medido: el resultado de agosto pasaba de US$ 5 a US$ 7). Frena
        con el motivo. Vacío, adoptarlo no cambia nada: entra, y el aviso dice que se suma
        (no que se crea). Lo mismo del lado de A con un gasto en dólares que necesita
        «Cocos · USD»."""
        self._lote_a_mano("Cocos", "NVDA", 1, 13.0, "2025-01-20", moneda="USD")
        self._broker("Balanz · USD", "USD")
        self._importar("Balanz · USD", [
            "2025-01-05,DEPOSITO,Balanz · USD,,,,1000,,,,USD,dep",
            "2025-02-01,COMPRA,Balanz · USD,NVDA,2,15,30,,,0,USD,compra",
            "2025-08-01,VENTA,Balanz · USD,NVDA,1,20,20,,,0,USD,venta"])
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, moneda="USD",
                            precio_manual=PRECIO_PASE)
        suelta = ("Tenés un broker «Balanz · USD» con movimientos que no está unido a Balanz. "
                  "Para pasar estos títulos Rendi lo tendría que sumar como la cuenta en dólares "
                  "de Balanz, y eso cambiaría su historia. Escribinos y lo acomodamos.")
        self._no_puede(body, 409, suelta)
        r = self._confirmar(body, vista={"firma": "x", "valuacion": None})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, suelta))
        # Vacío: se suma.
        self._broker("IOL")
        self._broker("IOL · USD", "USD")
        j = self._ok({**body, "broker_destino": "IOL"})
        self.assertEqual(j["avisos"], ["Vamos a sumar tu broker «IOL · USD» como la cuenta en "
                                       "dólares de IOL."])
        # Del lado de A: el gasto en dólares de una cuenta sin su «· USD», con un
        # «Bull · USD» suelto con movimientos.
        self._broker("Bull")
        self._broker("Bull · USD", "USD")
        self._importar("Bull · USD", ["2025-01-05,DEPOSITO,Bull · USD,,,,100,,,,USD,dep"])
        self._lote_a_mano("Bull", "GGAL", 10, 1000, "2025-02-03")
        self._no_puede(self._pedido("GGAL", "Bull", "Balanz", FECHA_PASE, precio_manual=1500,
                                    gasto={"monto": 5, "moneda": "USD"}), 409,
                       suelta.replace("Balanz · USD", "Bull · USD").replace("Balanz", "Bull"))

    def test_cantidad_minima(self):
        """Las cantidades por debajo de lo que Rendi distingue (6 decimales): una que no
        llega se rechaza con un texto que lo dice (antes: «se cotizan de dos formas
        distintas» con 1e-13, «no coinciden con tus archivos» con 5e-10, y con 1e-7
        «Listo: pasaste 0 NVDA» dejando polvo en los dos brokers). Y no se parte un lote
        para dejar polvo: 9,9999995 de 10 mueve el lote entero."""
        self._historia()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        for q in (1e-13, 5e-10, 5e-7):
            self._no_puede({**body, "cantidad": q}, 400, traspaso_a_mano.MSG_CANTIDAD_CHICA)
        j = self._ok({**body, "cantidad": 9.9999995})
        self.assertEqual(j["cantidad"], 10.0)
        self.assertEqual([(l["cantidad"], l["de_un_lote_de"]) for l in j["lotes"]], [(10.0, 10.0)])
        self.assertEqual(j["costo_usd"], round(301500 / dolar("2025-01-10"), 2))

    def test_wallbit_por_su_conexion_y_llegada_por_transfer_in(self):
        """#6 por la conexión (`user_broker_credentials`), no por el nombre: un broker
        conectado a la API de Wallbit con otro nombre. Y #13 por `transfer_in` (la
        entrada de un archivo que la marca así, sin la nota IEB:DETR)."""
        self._historia()
        self._broker("Mi cuenta")
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO user_broker_credentials (user_id, broker, api_key_enc) "
                         "VALUES (?, 'Mi cuenta', 'x')", (self.uid,))
            conn.commit()
        finally:
            conn.close()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        self._no_puede({**body, "broker_destino": "Mi cuenta"}, 400,
                       "Wallbit se sincroniza sola con tu cuenta real: no se le pueden pasar ni "
                       "sacar títulos a mano.")
        self._importar("Balanz", ["2025-06-14,COMPRA,Balanz,NVDA,10,30000,300000,,,0,ARS,llegada"])
        conn = main.get_db()
        try:
            conn.execute(
                "UPDATE import_normalized_tx SET transfer_in=1 WHERE broker='Balanz' "
                "AND operation_type='BUY' AND batch_id IN (SELECT id FROM import_batches "
                "WHERE user_id=?)", (self.uid,))
            conn.commit()
        finally:
            conn.close()
        r = self._vista(body)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertTrue(r.json()["detail"].startswith(
            "Balanz ya tiene registrada la llegada de 10 NVDA el 14/06"), r.text)

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


# ══════════════════════════════════════════════════════════════════════════════
# Etapa E6: confirmar el pase (`POST /api/positions/traspaso`), todo o nada
# ══════════════════════════════════════════════════════════════════════════════

class _Confirmar(_Vista):
    """Lo que necesitan las pruebas del confirmar: el estado entero de la cuenta (para
    afirmar «no cambió nada»), los lotes de un activo sin ids y la última vela."""

    def _ultimo_precio(self, simbolo, precio):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM asset_last_price WHERE symbol=?", (simbolo,))
            conn.execute("INSERT INTO asset_last_price (symbol, price, updated_at) VALUES (?,?,?)",
                         (simbolo, precio, main._iso_today() + " 12:00:00"))
            conn.commit()
        finally:
            conn.close()

    def _no_confirma(self, body, status, texto, **cambios):
        r = self._confirmar(body, **cambios)
        self.assertEqual(r.status_code, status, r.text)
        self.assertEqual(r.json()["detail"], texto)
        return r


class PaseTotal(_Confirmar):

    def test_pase_total_importado_lleva_costo_y_fecha_original(self):
        """#1. Cocos importó dos compras de NVDA (10/01 y 10/03); Balanz no tiene. Pase de
        todo con fecha de HOY, al último precio. Cocos queda sin NVDA; Balanz con los dos
        lotes, cada uno con su fecha de compra, su costo, sus comisiones y su dólar de
        compra, y `en_broker_desde` = hoy. Ninguna venta nueva, las cajas iguales, dos
        lotes de import confirmados (uno por broker) y la receta. Después del rebuild
        real (F.1), todo igual."""
        self._importar("Cocos", [
            "2025-01-05,DEPOSITO,Cocos,,,,400000,,,,ARS,dep",
            "2025-01-10,COMPRA,Cocos,NVDA,4,30000,120000,,,600,ARS,compra",
            "2025-03-10,COMPRA,Cocos,NVDA,6,32000,192000,,,960,ARS,compra"])
        hoy = main._iso_today()
        self._ultimo_precio("NVDA.BA", 45000.0)
        antes = self.estado()
        lotes_a = self._sin_ids("Cocos")
        self.assertEqual([l[3] for l in lotes_a], ["2025-01-10", "2025-03-10"])

        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", hoy))
        self.assertEqual(p["mensaje"], "Listo: pasaste 10 NVDA de Cocos a Balanz.")
        self.assertEqual({k: p["vista"]["valuacion"][k] for k in ("precio_unitario", "fuente")},
                         {"precio_unitario": 45000.0, "fuente": "ultimo_precio"})
        self.assertAlmostEqual(p["V"], 450000 / dolar(hoy), places=6)

        self.assertEqual(self._sin_ids("Cocos"), [])
        self.assertEqual(self._sin_ids("Balanz"), [l[:4] + (hoy,) + l[5:] for l in lotes_a])
        despues = self.estado()
        self.assertEqual(despues["caja"], antes["caja"])
        self.assertEqual(despues["ventas"], antes["ventas"])
        self.assertAlmostEqual(despues["aportado"]["global"], antes["aportado"]["global"], places=3)

        # Lo escrito: dos lotes confirmados con el formato del pase, uno por cuenta.
        conn = main.get_db()
        try:
            lotes = {r["id"]: dict(r) for r in conn.execute(
                "SELECT id, broker, parser_format, status, file_name FROM import_batches "
                "WHERE id IN (?, ?)", (p["lote_salida"], p["lote_entrada"]))}
            links = {(r["batch_id"], r["raw_row_id"]) for r in conn.execute(
                "SELECT l.batch_id, l.raw_row_id FROM import_op_links l JOIN import_batches b "
                "ON b.id=l.batch_id WHERE b.user_id=? AND b.parser_format='rendi_generic'",
                (self.uid,))}
        finally:
            conn.close()
        self.assertEqual({(l["broker"], l["parser_format"], l["status"], l["file_name"])
                          for l in lotes.values()},
                         {("Cocos", "traspaso_a_mano", "confirmed", "Pase entre brokers"),
                          ("Balanz", "traspaso_a_mano", "confirmed", "Pase entre brokers")})
        # Las filas: SELL de salida + pata en A; dos BUY + pata en B. `fecha_compra` es la
        # fecha de compra de cada lote en 'AAAA-MM-DD' (el orden H2 compara textos).
        ops = [(f["broker"], f["operation_type"], f["quantity"], f["fecha_compra"], f["date"])
               for f in p["filas"]]
        self.assertEqual(ops, [
            ("Cocos", "SELL", 10.0, None, hoy), ("Cocos", "TRASPASO_SALIDA", 10.0, None, hoy),
            ("Balanz", "BUY", 4.0, "2025-01-10", hoy), ("Balanz", "BUY", 6.0, "2025-03-10", hoy),
            ("Balanz", "TRASPASO_ENTRADA", 10.0, None, hoy)])
        self.assertTrue(all(f["traspaso_id"] == p["traspaso_id"] for f in p["filas"]))
        # La receta: los dos lotes importados, con la fila del archivo de donde vinieron
        # y la fila de B adonde llegaron; la regla del dólar con que se calcularon V y C.
        r = p["receta"]
        self.assertEqual((r["v"], r["broker_origen"], r["broker_destino"], r["fx_version"]),
                         (1, "Cocos", "Balanz", "v2"))
        self.assertEqual([(l["origen"], l["cantidad"], l["parcial"]) for l in r["lotes"]],
                         [("importado", 4.0, False), ("importado", 6.0, False)])
        for l in r["lotes"]:
            self.assertIn((l["fila_origen"]["batch_id"], l["fila_origen"]["raw_row_id"]), links)
            self.assertIsNotNone(l["fila_destino_raw_row_id"])
        # Y cada lote apunta a SU fila: la BUY de B con su fecha de compra y su cantidad,
        # y la BUY del archivo de A de donde vino (lo leen el deshacer y la reposición
        # por vínculo de E7). Un índice corrido o invertido apuntaba al otro lote.
        conn = main.get_db()
        try:
            for l, (compra, q) in zip(r["lotes"], (("2025-01-10", 4.0), ("2025-03-10", 6.0))):
                destino = conn.execute(
                    "SELECT operation_type, fecha_compra, quantity FROM import_normalized_tx "
                    "WHERE batch_id=? AND raw_row_id=?",
                    (p["lote_entrada"], l["fila_destino_raw_row_id"])).fetchone()
                self.assertEqual(tuple(destino), ("BUY", compra, q))
                origen = conn.execute(
                    "SELECT operation_type, substr(date, 1, 10), quantity FROM import_normalized_tx "
                    "WHERE batch_id=? AND raw_row_id=?",
                    (l["fila_origen"]["batch_id"], l["fila_origen"]["raw_row_id"])).fetchone()
                self.assertEqual(tuple(origen), ("BUY", compra, q))
        finally:
            conn.close()
        self.assertEqual(p["registro"]["omitidas_json"], None)
        self.assertEqual(p["registro"]["deshecho_at"], None)

        # Después del rebuild real, todo igual.
        self._rebuild()
        self.assertEqual(self.estado(), despues)
        self.assertEqual(self._sin_ids("Balanz"), [l[:4] + (hoy,) + l[5:] for l in lotes_a])


class PrecioCargado(_Confirmar):

    def test_precio_cargado_viaja_a_b(self):
        """C.7.8. Los lotes de A tienen un precio cargado a mano y B no tiene ninguno para
        ese activo: el pase de hoy se valúa con ese precio y el precio viaja a B (y queda
        anotado en la receta, para que el deshacer lo saque)."""
        self._historia()
        hoy = main._iso_today()
        conn = main.get_db()
        try:
            conn.execute("UPDATE positions SET price_override=62000 WHERE user_id=? AND asset='NVDA'",
                         (self.uid,))
            conn.commit()
        finally:
            conn.close()
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", hoy))
        self.assertEqual(p["vista"]["valuacion"]["fuente"], "precio_cargado")
        self.assertAlmostEqual(p["V"], 10 * 62000 / dolar(hoy), places=6)
        self.assertEqual(p["receta"]["precio_cargado_en_destino"],
                         {"brokers_destino": ["Balanz"], "antes": None, "puesto": 62000.0})
        conn = main.get_db()
        try:
            self.assertEqual({r["price_override"] for r in conn.execute(
                "SELECT price_override FROM positions WHERE user_id=? AND broker='Balanz' "
                "AND asset='NVDA'", (self.uid,))}, {62000.0})
        finally:
            conn.close()


    def _precio_cargado(self, broker, valor, asset="NVDA"):
        conn = main.get_db()
        try:
            conn.execute("UPDATE positions SET price_override=? WHERE user_id=? AND broker=? "
                         "AND asset=? AND is_cash=0", (valor, self.uid, broker, asset))
            conn.commit()
        finally:
            conn.close()

    def _precios_cargados(self, asset="NVDA"):
        conn = main.get_db()
        try:
            return {(r["broker"], r["price_override"]) for r in conn.execute(
                "SELECT broker, price_override FROM positions WHERE user_id=? AND asset=? "
                "AND is_cash=0", (self.uid, asset))}
        finally:
            conn.close()

    def test_el_precio_cargado_va_solo_a_la_pata_que_recibe(self):
        """C.7.8, sólo a las patas de B que reciben los lotes. Cocos tiene 10 NVDA en pesos
        con precio cargado $62.000; Balanz tiene 3 NVDA propios en «Balanz · USD», sin
        precio cargado. El pase va a la raíz de Balanz: el precio viaja ahí y NO a la
        «· USD», que lo leería en dólares (sus 3 NVDA pasaban de valer US$ 39 a
        US$ 186.000, en Cartera, en las fotos y en el valor de la cuenta, sin un aviso).
        La receta anota exactamente esa pata (la que el deshacer limpia)."""
        self._historia()
        self._broker("Balanz · USD", "USDT", padre="Balanz")
        self._lote_a_mano("Balanz", "NVDA", 3, 13.0, "2025-02-01", moneda="USD")
        self._precio_cargado("Cocos", 62000)
        hoy = main._iso_today()
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", hoy))
        self.assertEqual(p["receta"]["precio_cargado_en_destino"],
                         {"brokers_destino": ["Balanz"], "antes": None, "puesto": 62000.0})
        self.assertEqual(self._precios_cargados(), {("Balanz", 62000.0), ("Balanz · USD", None)})

    def test_precio_cargado_en_la_pata_en_dolares(self):
        """El precio cargado de un CEDEAR en dólares que vive en «Cocos · USD» está en
        DÓLARES (así lo lee Cartera: `valuation.js`, `compute_broker_value_usd`), aunque su
        clave de precio sea la .BA en pesos. 3 NVDA a US$ 14 con precio cargado US$ 15: el
        pase de hoy vale US$ 45 (antes: 15 «pesos» = US$ 0,01, y un puente de −US$ 42 en el
        mes de cada broker). Va a «Balanz · USD», que el confirmar crea, y el precio viaja
        a esa pata (la que lo lee en dólares, como la de origen)."""
        self._lote_a_mano("Cocos", "NVDA", 3, 14.0, "2025-02-03", moneda="USD")
        self._precio_cargado("Cocos · USD", 15.0)
        hoy = main._iso_today()
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", hoy, moneda="USD"))
        self.assertEqual({k: p["vista"]["valuacion"][k] for k in
                          ("precio_unitario", "moneda_precio", "fuente")},
                         {"precio_unitario": 15.0, "moneda_precio": "USD",
                          "fuente": "precio_cargado"})
        self.assertAlmostEqual(p["V"], 45.0, places=6)
        self.assertAlmostEqual(p["C"], 42.0, places=6)
        self.assertEqual(p["receta"]["precio_cargado_en_destino"],
                         {"brokers_destino": ["Balanz · USD"], "antes": None, "puesto": 15.0})
        self.assertEqual(self._precios_cargados(), {("Balanz · USD", 15.0)})


class PaseParcial(_Confirmar):

    def test_pase_parcial_parte_el_ultimo_lote_en_proporcion(self):
        """#2. Tres lotes de 4; se mueven 6 (un lote y medio): el primero entero y la mitad
        del segundo, con inversión y comisiones en proporción exacta (C.3). Lo de A más
        lo de B es lo de antes, lote por lote. Después del rebuild real, igual (el
        persister y el rebuild parten igual). Y un lote cargado a mano SIN `invested` se
        parte con su costo (`costo_del_lote`: precio × cantidad)."""
        self._importar("Cocos", [
            "2025-01-05,DEPOSITO,Cocos,,,,500000,,,,ARS,dep",
            "2025-01-10,COMPRA,Cocos,NVDA,4,30000,120000,,,600,ARS,compra",
            "2025-02-10,COMPRA,Cocos,NVDA,4,31000,124000,,,620,ARS,compra",
            "2025-03-10,COMPRA,Cocos,NVDA,4,32000,128000,,,640,ARS,compra"])
        antes = self._sin_ids("Cocos")
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, cantidad=6,
                                       precio_manual=PRECIO_PASE))
        self.assertEqual(p["cantidad"], 6.0)
        b, a = self._sin_ids("Balanz"), self._sin_ids("Cocos")
        self.assertEqual([(l[0], l[3], l[4]) for l in b],
                         [(4.0, "2025-01-10", FECHA_PASE), (2.0, "2025-02-10", FECHA_PASE)])
        self.assertEqual([(l[0], l[3], l[4]) for l in a],
                         [(2.0, "2025-02-10", ""), (4.0, "2025-03-10", "")])
        self.assertAlmostEqual(b[1][1], 62000.0, delta=1e-6)
        self.assertAlmostEqual(b[1][2], 310.0, delta=1e-6)
        self.assertAlmostEqual(a[0][1], 62000.0, delta=1e-6)
        self.assertAlmostEqual(a[0][2], 310.0, delta=1e-6)
        # A + B = antes, por fecha de compra (cantidad, inversión y comisiones).
        suma = {}
        for l in a + b:
            s = suma.setdefault(l[3], [0.0, 0.0, 0.0])
            for i in range(3):
                s[i] += l[i]
        for l in antes:
            for i in range(3):
                self.assertAlmostEqual(suma[l[3]][i], l[i], delta=1e-6, msg=f"{l[3]} [{i}]")
        self._rebuild()
        self.assertEqual((self._sin_ids("Balanz"), self._sin_ids("Cocos")), (b, a))

        # Un lote cargado a mano sin `invested` (de antes de que el alta lo exigiera), y
        # con hora en la fecha de compra: la llegada guarda sólo el día ('AAAA-MM-DD'), que
        # es lo que el orden de las ventas de B compara como texto (H2).
        self._broker("IOL")
        conn = main.get_db()
        try:
            pid = conn.execute(
                "INSERT INTO positions (user_id, broker, asset, quantity, invested, buy_price, "
                "commissions, entry_date, is_cash, currency, asset_type) VALUES "
                "(?, 'IOL', 'GGAL', 10, NULL, 1000, 30, '2025-02-03 10:30:00', 0, 'ARS', 'STOCK')",
                (self.uid,)).lastrowid
            conn.commit()
        finally:
            conn.close()
        p = self._aplicar(self._pedido("GGAL", "IOL", "Balanz", FECHA_PASE, cantidad=4,
                                       precio_manual=1500))
        self.assertEqual(self._sin_ids("IOL", "GGAL"),
                         [(6.0, 6000.0, 18.0, "2025-02-03", "", None, "ARS", "STOCK")])
        self.assertEqual([l[:5] for l in self._sin_ids("Balanz", "GGAL")],
                         [(4.0, 4000.0, 12.0, "2025-02-03", FECHA_PASE)])
        lote = p["receta"]["lotes"][0]
        self.assertEqual((lote["origen"], lote["lote_id"], lote["parcial"], lote["invested"],
                          lote["commissions"], lote["foto"]["invested"], lote["foto"]["quantity"]),
                         ("a_mano", pid, True, 4000.0, 12.0, None, 10.0))
        self.assertAlmostEqual(p["C_nativo"], 4012.0, places=6)
        self.assertEqual([f["fecha_compra"] for f in p["filas"] if f["operation_type"] == "BUY"],
                         ["2025-02-03"])
        conn = main.get_db()
        try:
            self.assertEqual(conn.execute(
                "SELECT entry_date FROM positions WHERE user_id=? AND broker='Balanz' "
                "AND asset='GGAL'", (self.uid,)).fetchone()["entry_date"][:10], "2025-02-03")
        finally:
            conn.close()


    def test_parte_un_lote_que_no_divide_exacto(self):
        """C.3 con números que no dan redondos: 3 de un lote de 7 que costó $100.000 con
        $77 de comisión. Lo que se mueve es el COMPLEMENTO de lo que queda en A (redondeado
        a 6 decimales, la fórmula del persister): A + B da EXACTAMENTE lo de antes. Con
        lo movido calculado aparte (`round(base × ratio, 2)`), se perdían centavos."""
        self._importar("Cocos", [
            "2025-01-05,DEPOSITO,Cocos,,,,200000,,,,ARS,dep",
            "2025-01-10,COMPRA,Cocos,NVDA,7,14285.714286,100000,,,77,ARS,compra"])
        self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, cantidad=3,
                                   precio_manual=PRECIO_PASE))
        conn = main.get_db()
        try:
            filas = {r["broker"]: (r["quantity"], r["invested"], r["commissions"])
                     for r in conn.execute(
                         "SELECT broker, quantity, invested, commissions FROM positions "
                         "WHERE user_id=? AND asset='NVDA' AND is_cash=0", (self.uid,))}
        finally:
            conn.close()
        (qa, ia, ca), (qb, ib, cb) = filas["Cocos"], filas["Balanz"]
        self.assertEqual((qa, qb), (4.0, 3.0))
        self.assertAlmostEqual(ia, round(100000 * 4 / 7, 6), delta=1e-9)
        self.assertAlmostEqual(ia + ib, 100000.0, delta=1e-9)
        self.assertAlmostEqual(ca + cb, 77.0, delta=1e-9)


class MezclaAManoEImportados(_Confirmar):

    def test_mezcla_a_mano_e_importados_y_fifo_posterior_en_b(self):
        """#3. Cocos tiene un lote cargado a mano viejo (02/01) y el importado del 10/01;
        Balanz, uno suyo del 01/03. El pase lleva los dos de Cocos: el cargado a mano
        sale de `positions` (sin fila de salida) y queda en la receta con su foto. Después
        se importa en Balanz una venta de 3 (el 01/07): el persister Y el rebuild consumen
        primero el de fecha de compra más vieja (H2) — el que era a mano, aunque llegó a
        Balanz después que el propio de Balanz."""
        self._historia()
        lote_a_mano = self._lote_a_mano("Cocos", "NVDA", 2, 28000, "2025-01-02")
        self._importar("Balanz", ["2025-03-01,COMPRA,Balanz,NVDA,3,35000,105000,,,0,ARS,compra"])
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE,
                                       precio_manual=PRECIO_PASE))
        self.assertEqual(self._sin_ids("Cocos"), [])
        lotes = p["receta"]["lotes"]
        self.assertEqual([(l["origen"], l["lote_id"], l["cantidad"]) for l in lotes],
                         [("a_mano", lote_a_mano["id"], 2.0), ("importado", lotes[1]["lote_id"], 10.0)])
        self.assertIsNone(lotes[0]["fila_origen"])
        self.assertEqual({k: lotes[0]["foto"][k] for k in ("broker", "quantity", "invested",
                                                           "entry_date")},
                         {"broker": "Cocos", "quantity": 2.0, "invested": 56000.0,
                          "entry_date": lote_a_mano["entry_date"]})
        # Sólo los importados tienen salida en el registro de A.
        self.assertEqual([(f["operation_type"], f["quantity"]) for f in p["filas"]
                          if f["batch_id"] == p["lote_salida"]],
                         [("SELL", 10.0), ("TRASPASO_SALIDA", 12.0)])
        mirar = lambda: [(l[0], l[3], l[4]) for l in self._sin_ids("Balanz")]
        self.assertEqual(mirar(), [(2.0, "2025-01-02", FECHA_PASE), (10.0, "2025-01-10", FECHA_PASE),
                                   (3.0, "2025-03-01", "")])
        self._importar("Balanz", ["2025-07-01,VENTA,Balanz,NVDA,3,50000,150000,,,0,ARS,venta"])
        esperado = [(9.0, "2025-01-10", FECHA_PASE), (3.0, "2025-03-01", "")]
        self.assertEqual(mirar(), esperado, "el persister no consumió primero el más viejo")
        self._rebuild()
        self.assertEqual(mirar(), esperado, "el rebuild no consumió primero el más viejo")
        self.assertEqual(self._sin_ids("Cocos"), [])


class SinVentasNiEstadisticas(_Confirmar):

    def test_sin_ventas_ni_estadisticas(self):
        """#6 (la parte de E6). El pase no es una venta: `GET /api/operations`, el % de
        acierto de toda la historia y `operations.csv` quedan iguales, con una venta
        real en la cuenta para que haya algo que comparar. (Las filas de
        `transactions.csv` —«TRASPASO (SALE)/(ENTRA)» en vez de COMPRA/VENTA— son de
        la etapa E9, D.9.)"""
        from reporting.timeline import _compute_user_historical_win_rate
        self._historia()
        self._importar("Cocos", ["2025-04-01,COMPRA,Cocos,AAPL,5,20000,100000,,,0,ARS,compra",
                                 "2025-05-01,VENTA,Cocos,AAPL,5,24000,120000,,,0,ARS,venta"])

        def mirar():
            ops = self.http.get("/api/operations", headers=self.h)
            csv_ops = self.http.get("/api/export/operations.csv", headers=self.h)
            self.assertEqual((ops.status_code, csv_ops.status_code), (200, 200))
            conn = main.get_db()
            try:
                acierto = _compute_user_historical_win_rate(conn, self.uid)
            finally:
                conn.close()
            return ops.json(), csv_ops.text, acierto

        antes = mirar()
        self.assertEqual(len(antes[0]), 1)
        self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        self.assertEqual(mirar(), antes)


class GastoYCaja(_Confirmar):

    def test_caja_intacta_y_gasto_como_perdida_de_a(self):
        """#8 (la identidad). Dos cuentas en dólares, para que «capital = costo + caja» se
        lea sin dólares de por medio: IBKR deposita US$ 1.000 y compra 2 MSFT a US$ 300
        con US$ 1 de comisión (costo US$ 601, caja US$ 399). Pasa todo a Schwab con un
        gasto de US$ 5. IBKR: capital = 0 de títulos + caja US$ 394; Schwab: capital =
        US$ 601 de títulos + caja 0. Sin gasto, las cajas no se mueven (lo mira #4). El
        resto de #8 (el realizado de A con el gasto, el gasto en pesos) está en
        `test_gasto_es_perdida_del_que_lo_paga`; el deshacer, en E7."""
        self._broker("IBKR", "USD")
        self._broker("Schwab", "USD")
        self._importar("IBKR", ["2025-01-05,DEPOSITO,IBKR,,,,1000,,,,USD,dep",
                                "2025-01-10,COMPRA,IBKR,MSFT,2,300,600,,,1,USD,compra"])
        p = self._aplicar(self._pedido("MSFT", "IBKR", "Schwab", FECHA_PASE, moneda="USD",
                                       precio_manual=420, gasto={"monto": 5, "moneda": "USD"}))
        self.assertAlmostEqual(p["V"], 840.0, places=6)
        self.assertAlmostEqual(p["C"], 601.0, places=6)
        self.assertAlmostEqual(p["gasto_usd"], 5.0, places=6)
        est = self.estado()
        self.assertEqual((est["caja"]["IBKR"], est["caja"].get("Schwab", 0.0)), (394.0, 0.0))
        m = self._mensual()
        for broker, capital in (("IBKR", 394.0), ("Schwab", 601.0)):
            for mes in range(6, 13):
                self.assertAlmostEqual(m[(broker, 2025, mes)]["capital_final"], capital, places=4,
                                       msg=f"{broker} {mes}")
        self.assertAlmostEqual(m[("IBKR", 2025, 6)]["pnl_realized"], 840 - 601 - 5, places=4)
        self.assertAlmostEqual(m[("Schwab", 2025, 6)]["pnl_realized"], -(840 - 601), places=4)
        self.assertAlmostEqual(m[("global", 2025, 6)]["pnl_realized"], -5.0, places=4)
        self._cierra_la_cadena(m)
        # Los lotes en dólares: cada fila de broker trae su pata con el día
        # (`traspaso_usd_con_dia`, lo lee capitalAportado.js), y la de 'global' no.
        self.assertEqual(m[("IBKR", 2025, 6)].get("traspaso_usd_con_dia"),
                         {"dep": [], "ret": [[FECHA_PASE, 840.0]]})
        self.assertEqual(m[("Schwab", 2025, 6)].get("traspaso_usd_con_dia"),
                         {"dep": [[FECHA_PASE, 840.0]], "ret": []})
        self.assertNotIn("traspaso_usd_con_dia", m[("global", 2025, 6)])

    def test_gasto_en_dolares_crea_la_pata_de_a(self):
        """Un gasto en dólares desde una cuenta argentina sin su «· USD»: el confirmar la
        crea (como cualquier puerta que mueve dólares ahí) y el gasto sale de esa caja,
        como pérdida de esa pata. El global baja el gasto y la cadena cierra."""
        self._historia()
        antes = self._mensual()
        self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE,
                                   precio_manual=PRECIO_PASE, gasto={"monto": 10, "moneda": "USD"}))
        conn = main.get_db()
        try:
            hija = conn.execute(
                "SELECT h.currency, p.name AS padre FROM brokers h JOIN brokers p "
                "ON p.id=h.parent_broker_id WHERE h.user_id=? AND h.name='Cocos · USD'",
                (self.uid,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(hija), ("USDT", "Cocos"))
        self.assertEqual(self.estado()["caja"]["Cocos · USD"], -10.0)
        m = self._mensual()
        self.assertAlmostEqual(m[("Cocos · USD", 2025, 6)]["pnl_realized"], -10.0, places=4)
        self.assertAlmostEqual(m[("global", 2025, 6)]["pnl_realized"]
                               - antes[("global", 2025, 6)]["pnl_realized"], -10.0, places=4)
        self._cierra_la_cadena(m)


class ParPadreYUsd(_Confirmar):

    def test_par_padre_y_usd(self):
        """#9. Cocos y «Cocos · USD»: en la hija un lote en dólares cargado a mano (20/01,
        el más viejo) y dos importados (25/01 y 01/03); en el padre, un CEDEAR en dólares
        importado (03/02). A Balanz, que no tiene «· USD»: el confirmar la crea; los de la
        hija van a «Balanz · USD» y el del padre a Balanz. Las salidas de los importados
        van por tramo contiguo de la misma pata ([hija, padre, hija] → tres SELL) y cada
        una consume su pata: la historia (`_holdings_asof`) de cada pata queda en cero
        después del pase, sin un negativo en una y un sobrante en la otra. Y Cocos →
        «Cocos · USD» es la misma cuenta (#5)."""
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        # El genérico deja pasar la columna `asset_type`: así el CEDEAR comprado en
        # dólares queda en el padre (la plata sale de la hija), como lo deja el
        # archivo de Cocos o de Balanz (`persister.cash_broker_for`).
        con_tipo = HDR.rstrip("\n") + ",asset_type\n"
        self._importar("Cocos", ["2025-01-05,DEPOSITO,Cocos,,,,1000,,,,USD,dep,",
                                 "2025-02-03,COMPRA,Cocos,NVDA,2,15,30,,,0,USD,compra,CEDEAR"],
                       hdr=con_tipo)
        self._importar("Cocos · USD", [
            "2025-01-06,DEPOSITO,Cocos · USD,,,,500,,,,USD,dep,",
            "2025-01-25,COMPRA,Cocos · USD,NVDA,3,14,42,,,0,USD,compra,CEDEAR",
            "2025-03-01,COMPRA,Cocos · USD,NVDA,4,16,64,,,0,USD,compra,CEDEAR"], hdr=con_tipo)
        self._lote_a_mano("Cocos", "NVDA", 1, 13.0, "2025-01-20", moneda="USD")
        donde = {(l[3], l[0]): b for b in ("Cocos", "Cocos · USD")
                 for l in self._sin_ids(b)}
        self.assertEqual(donde, {("2025-01-20", 1.0): "Cocos · USD", ("2025-01-25", 3.0): "Cocos · USD",
                                 ("2025-02-03", 2.0): "Cocos", ("2025-03-01", 4.0): "Cocos · USD"},
                         "el escenario no quedó armado como se pensó")
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, moneda="USD",
                            precio_manual=PRECIO_PASE)
        self._no_confirma({**body, "broker_destino": "Cocos · USD"}, 400,
                          "Ése es el mismo broker: las dos monedas de una cuenta son una sola. "
                          "Elegí otro broker.", vista={"firma": "x", "valuacion": None})
        p = self._aplicar(body)
        self.assertEqual(p["vista"]["destino"]["brokers_a_crear"], ["Balanz · USD"])
        conn = main.get_db()
        try:
            hija = conn.execute(
                "SELECT h.currency, p.name AS padre FROM brokers h JOIN brokers p "
                "ON p.id=h.parent_broker_id WHERE h.user_id=? AND h.name='Balanz · USD'",
                (self.uid,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(hija), ("USDT", "Balanz"))
        self.assertEqual(p["receta"]["brokers_usd_creados"], ["Balanz · USD"])
        self.assertEqual([(f["broker"], f["quantity"]) for f in p["filas"]
                          if f["operation_type"] == "SELL"],
                         [("Cocos · USD", 3.0), ("Cocos", 2.0), ("Cocos · USD", 4.0)])
        self.assertEqual(sorted((f["broker"], f["operation_type"], f["quantity"]) for f in p["filas"]
                                if f["operation_type"].startswith("TRASPASO")),
                         [("Balanz", "TRASPASO_ENTRADA", 2.0), ("Balanz · USD", "TRASPASO_ENTRADA", 8.0),
                          ("Cocos", "TRASPASO_SALIDA", 2.0), ("Cocos · USD", "TRASPASO_SALIDA", 8.0)])
        self.assertEqual(self._sin_ids("Cocos") + self._sin_ids("Cocos · USD"), [])
        self.assertEqual([(l[0], l[3]) for l in self._sin_ids("Balanz · USD")],
                         [(1.0, "2025-01-20"), (3.0, "2025-01-25"), (4.0, "2025-03-01")])
        self.assertEqual([(l[0], l[3]) for l in self._sin_ids("Balanz")], [(2.0, "2025-02-03")])

        conn = main.get_db()
        try:
            def tenencia(dia):
                return {h["broker"]: round(h["quantity"], 6)
                        for h in bf._holdings_asof(conn, self.uid, dia)
                        if h["asset"] == "NVDA" and abs(h["quantity"]) > 1e-9}
            antes, despues = tenencia("2025-05-31"), tenencia("2025-06-30")
        finally:
            conn.close()
        # Antes del pase, el registro de A tiene sólo los importados (7 en la hija, 2 en
        # el padre): el cargado a mano no es de un archivo y la historia lo cuenta como
        # «no visto» (`_tenencia_no_vista`, E3). Desde el pase, el registro de B tiene los
        # cuatro, el que era a mano incluido (su BUY de llegada).
        self.assertEqual(antes, {"Cocos · USD": 7.0, "Cocos": 2.0})
        self.assertEqual(despues, {"Balanz · USD": 8.0, "Balanz": 2.0})
        # Y el rebuild real de las patas de A no fabrica nada (cada SELL encontró lo suyo).
        self._rebuild()
        self.assertEqual(self._sin_ids("Cocos") + self._sin_ids("Cocos · USD"), [])


class FechaPasada(_Confirmar):

    def test_fecha_pasada(self):
        """#11. El confirmar vuelve a validar con lo que hay al confirmar: (a) una venta en
        A posterior a la fecha, que llegó entre la vista previa y el confirmar → 409; (b)
        lo mismo con una venta en B → 409. (c) Sin ventas que lo frenen, un pase con fecha
        pasada (con un lote cargado a mano además de los importados, D.13.2b) siembra el
        mes de A y de B, y la cobertura a mercado de los meses entre la compra y el pase
        NO baja: la historia sigue viendo los títulos en A hasta el día del pase.

        ⚠️ Lo que esta prueba NO afirma, a propósito: `_holdings_asof` valúa con el costo
        PROMEDIO del grupo (preexistente). En una cuenta con una venta parcial previa,
        el global de la historia a mercado muestra un escalón el mes del pase (A valuaba
        al promedio, B recibe el costo real de los lotes que quedaron). Acá no hay venta
        parcial previa; el escalón es de antes del pase y no se tapa."""
        self._historia()
        self._lote_a_mano("Cocos", "NVDA", 2, 28000, "2025-02-03")
        conn = main.get_db()
        try:
            cob = lambda: {r["date"]: r["mtm_coverage"] for r in conn.execute(
                "SELECT date, mtm_coverage FROM snapshots WHERE user_id=? AND date >= '2025-01-31' "
                "AND date <= '2025-07-31' ORDER BY date", (self.uid,)).fetchall()}
            cob_antes = cob()
        finally:
            conn.close()
        self.assertTrue(any((c or 0) > 0 for c in cob_antes.values()),
                        f"el escenario necesita meses con cobertura: {cob_antes}")
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        # (a) Una venta en A posterior a la fecha llega entre la vista previa y el confirmar.
        vista = self._ok(body)
        self._importar("Cocos", ["2025-08-01,VENTA,Cocos,NVDA,1,50000,50000,,,0,ARS,venta"])
        self._no_confirma(body, 409, "Después del 16/06/2025 vendiste NVDA en Cocos. Para no "
                                     "cambiar esas ventas, elegí una fecha del 01/08/2025 en "
                                     "adelante.", vista=vista)
        # (b) Lo mismo en B.
        body_b = {**body, "fecha": "2025-08-01"}
        vista_b = self._ok(body_b)
        self._importar("Balanz", ["2025-03-01,COMPRA,Balanz,NVDA,2,32000,64000,,,0,ARS,compra",
                                  "2025-09-01,VENTA,Balanz,NVDA,1,52000,52000,,,0,ARS,venta"])
        self._no_confirma(body_b, 409, "Después del 01/08/2025 vendiste NVDA en Balanz. Si lo "
                                       "pasamos con esa fecha cambiarían esas ventas: elegí una "
                                       "fecha del 02/09/2025 en adelante.", vista=vista_b)
        # (c) Sin ventas que lo frenen: todo (importados y el cargado a mano) a IOL, una
        # cuenta nueva sin actividad, el 05/08.
        self._broker("IOL")
        conn = main.get_db()
        try:
            cob_antes = cob()
        finally:
            conn.close()
        p = self._aplicar({**body, "broker_destino": "IOL", "fecha": "2025-08-05"})
        self.assertEqual([l["origen"] for l in p["receta"]["lotes"]], ["importado", "a_mano"])
        m = self._mensual()
        self.assertIn(("Cocos", 2025, 8), m)
        self.assertIn(("IOL", 2025, 8), m)
        self.assertAlmostEqual(m[("IOL", 2025, 8)]["deposits"], p["V"], places=3)
        conn = main.get_db()
        try:
            cob_despues = cob()
        finally:
            conn.close()
        for dia, c in cob_antes.items():
            self.assertGreaterEqual(cob_despues.get(dia) or 0, (c or 0) - 1e-9,
                                    f"la cobertura de {dia} bajó: {c} → {cob_despues.get(dia)}")


    def test_la_historia_antes_del_pase_no_cambia(self):
        """#11 (c), lo que «la cobertura no baja» no podía ver. Cocos tiene GGAL SÓLO
        cargado a mano (el registro de lo importado no lo ve) y lo pasa a IOL el 05/08. Las
        fotos de fin de mes ANTERIORES al pase quedan IGUALES, valor y cobertura: la
        historia sigue viendo el lote en Cocos hasta ese día (`lotes_a_mano_que_salieron`,
        D.13.2b). Sin esa lista el lote desaparecía de la historia de A y la cobertura
        SUBÍA (se iba lo «no visto»): un «no baja» no lo detectaba. Y la reconstrucción
        corrió después del pase (cambió la huella): si no, «iguales» no diría nada."""
        self._historia()
        self._lote_a_mano("Cocos", "GGAL", 10, 1000, "2025-02-03")
        self._broker("IOL")
        dias = ("2025-03-31", "2025-05-31", "2025-07-31")

        def mirar():
            conn = main.get_db()
            try:
                fotos = {r["date"]: (round(r["total_value"] or 0, 2), r["mtm_coverage"])
                         for r in conn.execute(
                             f"SELECT date, total_value, mtm_coverage FROM snapshots "
                             f"WHERE user_id=? AND date IN ({','.join('?' * len(dias))}) "
                             f"ORDER BY date", (self.uid, *dias)).fetchall()}
                huella = conn.execute("SELECT huella, escrita_at FROM mtm_huella WHERE user_id=?",
                                      (self.uid,)).fetchone()
                return fotos, (tuple(huella) if huella else None)
            finally:
                conn.close()

        fotos_antes, huella_antes = mirar()
        self.assertEqual(sorted(fotos_antes), list(dias), "el escenario necesita esas fotos")
        self.assertTrue(any((c or 0) < 1 for _, c in fotos_antes.values()),
                        f"el lote a mano tiene que verse como «no visto»: {fotos_antes}")
        self._aplicar(self._pedido("GGAL", "Cocos", "IOL", "2025-08-05", precio_manual=1500))
        fotos_despues, huella_despues = mirar()
        self.assertNotEqual(huella_despues, huella_antes, "la reconstrucción no corrió")
        self.assertEqual(fotos_despues, fotos_antes)


class FirmaYValuacion(_Confirmar):

    def test_firma_y_valuacion(self):
        """#28 y #29 (la valuación). El confirmar usa el precio que la persona VIO: la
        vista previa dice $45.000 (último precio de hoy), el precio se reescribe a
        $47.000 antes de confirmar, y V sale con $45.000. Lo que el servidor rechaza, y
        no escribe nada: sin firma o con otra (409 «Tu cartera cambió…»), sin la
        valuación (400), con el precio en otra moneda (400 «Precio inválido.»), con el
        dólar corrido más de 3 % (409, con los dos dólares), y con la firma vieja
        después de una compra nueva (409). Un dólar corrido 2 % pasa, y se escribe con
        el del servidor. El interruptor apagado: 403."""
        self._historia()
        hoy = main._iso_today()
        self._ultimo_precio("NVDA.BA", 45000.0)
        body = self._pedido("NVDA", "Cocos", "Balanz", hoy)
        vista = self._ok(body)
        self.assertEqual({k: vista["valuacion"][k] for k in ("precio_unitario", "fuente", "dolar")},
                         {"precio_unitario": 45000.0, "fuente": "ultimo_precio", "dolar": dolar(hoy)})
        tablas = self._tablas()
        cambio = traspaso_a_mano.MSG_CARTERA_CAMBIO
        self._no_confirma(body, 409, cambio, vista=vista, firma=None)
        self._no_confirma(body, 409, cambio, vista=vista, firma="0" * 16)
        self._no_confirma(body, 400, "Falta la vista previa del pase.", vista=vista, valuacion=None)
        self._no_confirma(body, 400, "Precio inválido.", vista=vista,
                          valuacion={**vista["valuacion"], "moneda_precio": "USD"})
        corrido = round(dolar(hoy) * 1.04, 2)
        ddd = lambda x: "$" + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        self._no_confirma(body, 409, f"El dólar de ese día cambió (de {ddd(corrido)} a "
                                     f"{ddd(dolar(hoy))}). Revisá la vista previa antes de "
                                     "confirmar.", vista=vista,
                          valuacion={**vista["valuacion"], "dolar": corrido})
        self._interruptor(False)
        self._no_confirma(body, 403, "Esta opción no está disponible por ahora.", vista=vista)
        self._interruptor(True)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), tablas, "un confirmar rechazado escribió algo")

        # Una compra nueva entre la vista previa y el confirmar: la firma vieja no vale.
        self._importar("Cocos", ["2025-05-01,COMPRA,Cocos,NVDA,2,33000,66000,,,0,ARS,compra"])
        self._no_confirma(body, 409, cambio, vista=vista)
        # Vista previa nueva (12 NVDA); el último precio cambia antes de confirmar.
        vista = self._ok(body)
        self.assertEqual(vista["cantidad"], 12.0)
        self._ultimo_precio("NVDA.BA", 47000.0)
        r = self._confirmar(body, vista=vista,
                            valuacion={**vista["valuacion"], "dolar": round(dolar(hoy) * 1.02, 2)})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        p = self._pase_escrito(r.json()["traspaso_id"])
        self.assertAlmostEqual(p["V"], 12 * 45000 / dolar(hoy), places=6)
        self.assertEqual(p["receta"]["precio"], {"unitario": 45000.0, "moneda": "ARS",
                                                 "fuente": "ultimo_precio", "fecha": hoy})
        self.assertEqual(p["receta"]["tc_pase"], dolar(hoy))
        # El segundo click con la misma vista previa: ya no hay NVDA en Cocos.
        self._no_confirma(body, 400, f"No tenés NVDA en Cocos en pesos que estuvieran ahí el "
                                     f"{_ddmmaaaa(hoy)}.", vista=vista)

    def test_doble_envio_de_un_pase_parcial(self):
        """C.9: la firma frena el doble envío. En un pase PARCIAL el segundo envío arma un
        plan con el mismo lote, la misma cantidad y el mismo costo en proporción (4 de 10
        y después 4 de 6 cuestan lo mismo): sin la cantidad del lote en la firma, el
        segundo click hacía un segundo pase."""
        self._historia()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, cantidad=4,
                            precio_manual=PRECIO_PASE)
        vista = self._ok(body)
        r = self._confirmar(body, vista=vista)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._no_confirma(body, 409, traspaso_a_mano.MSG_CARTERA_CAMBIO, vista=vista)
        self.assertEqual([l[0] for l in self._sin_ids("Balanz")], [4.0])
        self.assertEqual([l[0] for l in self._sin_ids("Cocos")], [6.0])


    def test_la_firma_cubre_fecha_gasto_destino_y_montos(self):
        """C.9: con la firma de una vista previa, el confirmar no escribe un pase que la
        persona no vio. Otra fecha, un gasto que no estaba, otro destino, o el MISMO lote
        con la MISMA cantidad pero otro costo u otra fecha de compra → 409 «Tu cartera
        cambió…», y nada escrito."""
        self._historia()
        self._broker("IOL")
        lote = self._lote_a_mano("Cocos", "GGAL", 10, 1000, "2025-02-03")
        body = self._pedido("GGAL", "Cocos", "Balanz", FECHA_PASE, precio_manual=1500)
        vista = self._ok(body)
        tablas = self._tablas()
        cambio = traspaso_a_mano.MSG_CARTERA_CAMBIO
        self._no_confirma({**body, "fecha": "2025-06-20"}, 409, cambio, vista=vista)
        self._no_confirma({**body, "gasto": {"monto": 900000, "moneda": "ARS"}}, 409, cambio,
                          vista=vista)
        self._no_confirma({**body, "broker_destino": "IOL"}, 409, cambio, vista=vista)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), tablas, "un confirmar rechazado escribió algo")
        for cambios in ({"invested": 12000.0}, {"entry_date": "2025-02-04"}):
            self._editar(self._lote("Cocos", "GGAL"), **cambios)
            self._no_confirma(body, 409, cambio, vista=vista)
            vista = self._ok(body)
        self.assertEqual(self._confirmar(body, vista=vista).status_code, 200)
        self._esperar_reconstruccion()

    def test_la_etiqueta_y_la_fecha_del_precio(self):
        """La valuación que manda la pantalla no decide la etiqueta ni la fecha que guarda
        la receta (las leen el deshacer y la revaluación de las patas, C.10). Una fecha que
        no es un día, o que no es del pase ni de la semana anterior → 400 «Precio
        inválido.». Con el precio del servidor, van su fuente y su fecha aunque el pedido
        diga otra. Con otro precio y una fuente que no se mueve sola, queda como lo que
        es: «precio_a_mano», con la fecha del pase. (El último precio que se movió entre
        la vista previa y el confirmar conserva su etiqueta: `test_firma_y_valuacion`.)"""
        self._historia()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        vista = self._ok(body)
        v = vista["valuacion"]
        tablas = self._tablas()
        for fecha in ("xx-yy-zzzz", "2025-06-17", "2025-06-01"):
            self._no_confirma(body, 400, "Precio inválido.", vista=vista,
                              valuacion={**v, "fecha_precio": fecha})
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), tablas)
        r = self._confirmar(body, vista=vista, valuacion={**v, "fuente": "cierre_del_dia",
                                                          "fecha_precio": "2025-06-13"})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        receta = self._pase_escrito(r.json()["traspaso_id"])["receta"]
        self.assertEqual(receta["precio"], {"unitario": PRECIO_PASE, "moneda": "ARS",
                                            "fuente": "precio_a_mano", "fecha": FECHA_PASE})
        # Otro precio que dice ser el cierre de un día: es un precio del pedido.
        self._broker("IOL")
        body2 = self._pedido("NVDA", "Balanz", "IOL", "2025-07-01", cantidad=1,
                             precio_manual=PRECIO_PASE)
        vista2 = self._ok(body2)
        r = self._confirmar(body2, vista=vista2, valuacion={
            **vista2["valuacion"], "precio_unitario": 9.9e11, "fuente": "cierre_del_dia",
            "fecha_precio": "2025-06-30"})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        receta = self._pase_escrito(r.json()["traspaso_id"])["receta"]
        self.assertEqual(receta["precio"], {"unitario": 9.9e11, "moneda": "ARS",
                                            "fuente": "precio_a_mano", "fecha": "2025-07-01"})


class Atomico(_Confirmar):
    """#29. Las fallas al escribir de B.3 (las tres de F.2 y el lote a mano que cambió),
    cada una sin dejar nada: ni lote de import, ni posición tocada, ni registro, ni
    «B · USD», ni un peso de caja."""

    def _cocos_par(self):
        """Cocos y su «· USD»: un lote en dólares cargado a mano en la hija (20/01) y un
        CEDEAR en dólares importado en el padre (03/02). El pase de los dos a Balanz
        (sin «· USD») con un gasto de $5.000: el confirmar, si llega al final, borra el
        lote a mano, crea «Balanz · USD», guarda los dos lotes, baja la caja y anota la
        receta — todo eso es lo que una falla tiene que deshacer."""
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        self._importar("Cocos", ["2025-01-05,DEPOSITO,Cocos,,,,1000,,,,USD,dep",
                                 "2025-01-06,DEPOSITO,Cocos,,,,100000,,,,ARS,dep",
                                 "2025-02-03,COMPRA,Cocos,NVDA,2,15,30,,,0,USD,compra"])
        self._lote_a_mano("Cocos", "NVDA", 1, 13.0, "2025-01-20", moneda="USD")
        return self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, moneda="USD",
                            precio_manual=PRECIO_PASE, gasto={"monto": 5000, "moneda": "ARS"})

    def test_atomico(self):
        body = self._cocos_par()
        vista = self._ok(body)
        self.assertEqual(vista["destino"]["brokers_a_crear"], ["Balanz · USD"])
        antes = self._tablas()

        # (a) Una fila del lote de B que el persister no puede guardar (lo saltea y sigue):
        # el lote de A ya estaba guardado y la caja bajada. 500, y no queda nada.
        real = ps._persist_buy

        def se_corta(conn, uid, batch_id, raw_row_id, tx, helpers):
            if getattr(tx, "traspaso_id", None):
                raise RuntimeError("se cortó la luz")
            return real(conn, uid, batch_id, raw_row_id, tx, helpers)

        with mock.patch.object(ps, "_persist_buy", se_corta):
            self._no_confirma(body, 500, "No pudimos guardar el pase (se cortó la luz). No se "
                                         "cambió nada en tu cartera.", vista=vista)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), antes)

        # (c) La «Balanz · USD» que no se puede crear (`_ensure_usd_sibling` → 409).
        def no_se_puede(conn, uid, fila):
            raise main.HTTPException(409, "«Balanz · USD» ya existe en pesos (prueba).")

        with mock.patch.object(main, "_ensure_usd_sibling", no_se_puede):
            self._no_confirma(body, 409, "«Balanz · USD» ya existe en pesos (prueba).", vista=vista)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), antes)

        # (d) El lote cargado a mano cambió entre lo que leyó el plan y la escritura (otro
        # pedido): el `DELETE … AND quantity=?` no toca nada → 409 «Tu cartera cambió…».
        # Se simula con un plan que leyó una cantidad que ya no es la de la base.
        armar = traspaso_a_mano.armar_plan

        def leyo_otra_cosa(*a, **k):
            plan = armar(*a, **k)
            if k.get("para_confirmar"):
                for l in plan.lotes:
                    if l.origen == "a_mano":
                        l.lote = {**l.lote, "quantity": float(l.lote["quantity"]) + 1}
            return plan

        with mock.patch.object(traspaso_a_mano, "armar_plan", leyo_otra_cosa):
            self._no_confirma(body, 409, traspaso_a_mano.MSG_CARTERA_CAMBIO, vista=vista)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), antes)

        # (e) Cualquier otra falla a mitad de camino (acá, al guardar los lotes del pase,
        # con el lote a mano ya borrado): 500 con el texto de «no se cambió nada», que es
        # lo que pasó, y no un error crudo.
        def se_rompe(*a, **k):
            raise RuntimeError("disco lleno")

        with mock.patch.object(pl, "store_preview_txs", se_rompe):
            self._no_confirma(body, 500, "No pudimos guardar el pase (un error inesperado). No "
                                         "se cambió nada en tu cartera.", vista=vista)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), antes)

        # (f) La SELL de A que el persister no puede guardar (la saltea y sigue con el
        # resto, y con el lote de B): 500 con su motivo, y no queda nada.
        real_salida = ps._persist_sell_fifo

        def no_alcanza(conn, uid, batch_id, raw_row_id, tx, helpers, **k):
            if getattr(tx, "traspaso_id", None):
                raise ps.PersistError(tx.row_index, "No alcanzan los títulos para el pase.")
            return real_salida(conn, uid, batch_id, raw_row_id, tx, helpers, **k)

        with mock.patch.object(ps, "_persist_sell_fifo", no_alcanza):
            self._no_confirma(body, 500, "No pudimos guardar el pase (no alcanzan los títulos "
                                         "para el pase). No se cambió nada en tu cartera.",
                              vista=vista)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), antes)

        # (g) Como (d), con el lote cargado a mano PARTIDO (medio título): el
        # `UPDATE … AND quantity=?` no toca nada → 409, y no queda nada.
        parcial = {**body, "cantidad": 0.5}
        vista_p = self._ok(parcial)
        self.assertEqual([(l["a_mano"], l["cantidad"]) for l in vista_p["lotes"]], [(True, 0.5)])
        with mock.patch.object(traspaso_a_mano, "armar_plan", leyo_otra_cosa):
            self._no_confirma(parcial, 409, traspaso_a_mano.MSG_CARTERA_CAMBIO, vista=vista_p)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), antes)

        # Sin fallas, el mismo pedido escribe todo (el control de que había qué deshacer).
        p = self._aplicar(body)
        despues = self._tablas()
        self.assertNotEqual(despues, antes)
        conn = main.get_db()
        try:
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM brokers WHERE user_id=? AND name='Balanz · USD'",
                (self.uid,)).fetchone())
        finally:
            conn.close()
        self.assertEqual(self.estado()["caja"]["Cocos"],
                         round(100000 - 5000.0, 4))
        self.assertEqual([l["origen"] for l in p["receta"]["lotes"]], ["a_mano", "importado"])

    def test_freno_de_pesos_del_persister(self):
        """#29 (b). El freno de «pesos a una cuenta en dólares» del persister sale ANTES de
        las filas (`PersistError`): el confirmar lo responde 409 con su texto, no un 500
        crudo, y no queda nada. Para llegar hasta ahí, el plan tiene que creer que la
        cuenta acepta pesos (si no, frena antes con #25): sólo `armar_plan` ve la lista
        vacía; el persister ve la de verdad."""
        self._broker("Schwab", "USD")
        self._broker("IBKR", "USD")
        self._lote_viejo("Schwab", "NVDA", 5, 150000.0, "2025-02-03", "ARS")
        body = self._pedido("NVDA", "Schwab", "IBKR", FECHA_PASE, precio_manual=45000)
        real = pl.brokers_que_no_aceptan_pesos

        def solo_el_plan_no_ve(brokers, base=None):
            if sys._getframe(1).f_code.co_name == "armar_plan":
                return set()
            return real(brokers, base)

        with mock.patch.object(pl, "brokers_que_no_aceptan_pesos", solo_el_plan_no_ve):
            vista = self._ok(body)
            antes = self._tablas()
            self._no_confirma(body, 409, (
                "«IBKR» está en dólares y este import le trae pesos: Rendi no puede guardar "
                "pesos en una cuenta en dólares. Si cambiaste la moneda del broker después de "
                "la vista previa, volvé a subir el archivo."), vista=vista)
        self._esperar_reconstruccion()
        self.assertEqual(self._tablas(), antes)


class Idor(_Confirmar):

    def test_idor(self):
        """#30. Otra cuenta con los nombres de los brokers de ésta: 404 en la vista previa y
        en el confirmar (el mismo que un broker que no existe). Si esa cuenta tiene
        brokers con los mismos nombres, ve los SUYOS (vacíos), no los de ésta. Y nada de
        ésta cambia. (El deshacer del pase de otra cuenta → 404 es de E7.)"""
        self._historia()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        vista = self._ok(body)
        tablas = self._tablas()
        conn = main.get_db()
        try:
            otro = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, is_admin, tier) "
                "VALUES (?, 'x', 1, 1, 0, 'plus')",
                (f"otro-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
            conn.commit()
        finally:
            conn.close()
        h2 = {"Authorization": f"Bearer {main.create_token(otro)}"}
        no_hay = "No encontramos ese broker en tu cuenta."
        r = self._vista(body, headers=h2)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, no_hay))
        r = self._confirmar(body, vista=vista, headers=h2)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, no_hay))
        conn = main.get_db()
        try:
            for nombre in ("Cocos", "Balanz"):
                conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                             (otro, nombre))
            conn.commit()
        finally:
            conn.close()
        vacio = "No tenés NVDA en Cocos en pesos que estuvieran ahí el 16/06/2025."
        r = self._vista(body, headers=h2)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, vacio))
        r = self._confirmar(body, vista=vista, headers=h2)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, vacio))
        self.assertEqual(self._tablas(), tablas)
        conn = main.get_db()
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) c FROM import_batches WHERE user_id=?", (otro,)).fetchone()["c"], 0)
        finally:
            conn.close()
        # La cuenta dueña sigue pudiendo confirmar con su vista previa.
        r = self._confirmar(body, vista=vista)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()


FOTOS_DEL_CRON = {"2025-03-31": (1600.0, 1500.0), "2025-06-30": (1700.0, 1500.0),
                  "2025-09-30": (1800.0, 1500.0)}


class CuentaCargadaAMano(_Confirmar):

    def _plantar_fotos_del_cron(self):
        conn = main.get_db()
        try:
            for d, (valor, aportado) in FOTOS_DEL_CRON.items():
                conn.execute(
                    """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                           net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                       VALUES (?,?,?,?,?,1200,'[{"asset": "MSFT", "value_usd": 1}]',
                               'cron','mercado',1)
                       ON CONFLICT(user_id, date) DO UPDATE SET
                           total_value=excluded.total_value,
                           total_invested=excluded.total_invested,
                           net_deposited=excluded.net_deposited,
                           fx_to_usd_blue=excluded.fx_to_usd_blue,
                           holdings_json=excluded.holdings_json,
                           source='cron', base='mercado', apto=1""",
                    (self.uid, d, valor, aportado, aportado))
            conn.commit()
        finally:
            conn.close()

    def _metricas(self):
        """Lo que pregunta «¿importó algo?»: la prueba gratis (el mail y el panel) y el
        panel de uso del admin."""
        from billing import trial as tr
        conn = main.get_db()
        try:
            stats = tr._trial_stats(conn, self.uid)
            persona = [x for x in tr.progreso(conn, days=30)["personas"] if x["id"] == self.uid]
            embudo = tr.funnel(conn, days=90)["importaron"]
        finally:
            conn.close()
        uso = self.http.get("/api/admin/uso", params={"internos": "true"}, headers=self.h)
        self.assertEqual(uso.status_code, 200, uso.text)
        self.assertEqual(len(persona), 1, "la persona no está en el panel de la prueba")
        return {"mail": stats.get("operations"), "ultima": persona[0]["ultima_importacion"],
                "ventanas": persona[0]["ventanas"], "embudo": embudo,
                "importaron": uso.json()["resumen"]["importaron"]}

    def test_cuenta_manual_no_se_vuelve_reconstruible(self):
        """#46, por HTTP. Una cuenta 100 % cargada a mano (5 MSFT en IBKR) hace un pase a
        Schwab por el confirmar de verdad: los dos lotes del pase no la vuelven
        «reconstruible» (no tiene un import de un archivo), la reconstrucción no corre y
        las fotos del cron quedan intactas.

        Lo mismo para las otras preguntas de «¿importó algo?» (E6, notas de la tanda 2):
        el mail de la prueba no cuenta el pase como operaciones cargadas, el panel de la
        prueba no lo muestra como una importación ni como filas, y el panel de uso del
        admin no la cuenta entre los que importaron.

        Y la regla del dólar (`fx_version`): la cuenta no la tenía resuelta (nunca
        importó ni vendió). El confirmar la resuelve y la GUARDA antes de escribir el
        pase, con la misma respuesta que usó la vista previa: si quedara sin guardar,
        el próximo que la pregunte vería los lotes del pase como historia y la
        resolvería distinto de como se calcularon V y C. (El deshacer por HTTP es E7.)"""
        self._broker("IBKR", "USD")
        self._broker("Schwab", "USD")
        self._lote_a_mano("IBKR", "MSFT", 5, 300, "2025-02-01", moneda="USD")
        self._plantar_fotos_del_cron()
        ahora = datetime.utcnow()
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM config WHERE user_id=? AND key='fx_version'", (self.uid,))
            conn.execute(
                "UPDATE users SET trial_started_at=?, trial_ends_at=?, credit_active_until=? "
                "WHERE id=?", ((ahora - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                               (ahora + timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S"),
                               (ahora + timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S"),
                               self.uid))
            conn.commit()
        finally:
            conn.close()
        metricas = self._metricas()
        self.assertEqual((metricas["mail"], metricas["ultima"]), (None, None))

        p = self._aplicar(self._pedido("MSFT", "IBKR", "Schwab", "2025-06-10", moneda="USD",
                                       precio_manual=380))
        self.assertEqual([l["origen"] for l in p["receta"]["lotes"]], ["a_mano"])
        self.assertEqual([l[0] for l in self._sin_ids("Schwab", "MSFT")], [5.0])
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute(bf._HAY_IMPORT_RECONSTRUIBLE, (self.uid,)).fetchone())
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) c FROM import_batches WHERE user_id=? AND status='confirmed'",
                (self.uid,)).fetchone()["c"], 2, "control: los dos lotes del pase están confirmados")
            version = conn.execute("SELECT value FROM config WHERE user_id=? AND key='fx_version'",
                                   (self.uid,)).fetchone()
            self.assertEqual(version["value"] if version else None, "v2")
            self.assertEqual(fx.fx_version(conn, self.uid), "v2")
            reconstruidas = conn.execute(
                "SELECT COUNT(*) c FROM snapshots WHERE user_id=? AND source=?",
                (self.uid, bf.MTM_SOURCE)).fetchone()["c"]
            fotos = {r["date"]: (r["total_value"], r["net_deposited"]) for r in conn.execute(
                "SELECT date, total_value, net_deposited FROM snapshots WHERE user_id=? "
                "AND source='cron'", (self.uid,)).fetchall()}
        finally:
            conn.close()
        self.assertEqual(p["receta"]["fx_version"], "v2")
        self.assertEqual(reconstruidas, 0)
        self.assertEqual(fotos, FOTOS_DEL_CRON)
        self.assertEqual(main._reconstruir_mtm(self.uid),
                         {"reconstruida": False, "motivo": "sin import confirmado (cuenta manual)"})
        self.assertEqual(self._metricas(), metricas)
        # La reparación de la caja al 1.415 fecha la reconciliación con el último import
        # del broker: un pase no es un import (sin import, la fila queda «sin fecha»).
        conn = main.get_db()
        try:
            mid = conn.execute(
                "INSERT INTO monthly_entries (user_id, year, month, broker, manual_deposits, "
                "manual_deposits_native) VALUES (?, 2024, 1, 'IBKR', 100, 141500)",
                (self.uid,)).lastrowid
            rep = main._repair_caja_1415(conn, False)
            conn.rollback()
        finally:
            conn.close()
        self.assertIn(mid, [i["id"] for i in rep["sin_fecha"]])


class CuentaV1(_Confirmar):

    def test_cuenta_con_el_dolar_de_la_config(self):
        """Una cuenta con la regla vieja del dólar (v1): los pesos van al dólar de la
        config ($1.200), no al de cada día (C.4.3). V = $450.000 / 1.200 y C = $301.500 /
        1.200; el global queda igual que sin pase y la cadena cierra. (Un import posterior
        la pasa sola a v2 y las patas quedan con los números de v1: eso es de E11,
        `revaluar_patas`. Por eso la regla v1 se pone DESPUÉS de importar la historia.)"""
        self._historia()
        conn = main.get_db()
        try:
            fx.set_fx_version(conn, self.uid, "v1")
            conn.execute("INSERT INTO config (user_id, key, value) VALUES (?, 'tc_blue', '1200') "
                         "ON CONFLICT (key, user_id) DO UPDATE SET value='1200'", (self.uid,))
            conn.commit()
        finally:
            conn.close()
        r = self.http.post("/api/imports/recalc-pnl", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        antes = self._mensual()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        self.assertAlmostEqual(p["V"], 450000 / 1200, places=6)
        self.assertAlmostEqual(p["C"], 301500 / 1200, places=6)
        self.assertEqual((p["receta"]["fx_version"], p["receta"]["tc_pase"]), ("v1", 1200.0))
        m = self._mensual()
        glob = lambda mm: {k: tuple(round(f[c], 4) for c in ("deposits", "withdrawals",
                                                             "pnl_realized"))
                           for k, f in mm.items() if k[0] == "global"}
        self.assertEqual(glob(m), glob(antes))
        self._cierra_la_cadena(m)


class MesEnCurso(_Confirmar):
    """El mes en curso: su capital final es «vivo» (lleva la ganancia no realizada que
    pone sync-unrealized) y la reparación de la cadena no lo vuelve a armar. Lo que sólo
    arma el recálculo —las patas de un pase, las de una conversión— tiene que llegar
    igual a ese capital (`_recalc_pnl_realized_from_ops`)."""

    def _cuadra(self, broker):
        hoy = date.fromisoformat(main._iso_today())
        conn = main.get_db()
        try:
            f = conn.execute(
                "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
                (self.uid, broker, hoy.year, hoy.month)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(f, f"{broker} no tiene el renglón del mes")
        esperado = (float(f["capital_inicio"] or 0) + float(f["deposits"] or 0)
                    - float(f["withdrawals"] or 0) + float(f["pnl_realized"] or 0)
                    + float(f["pnl_unrealized"] or 0))
        self.assertAlmostEqual(float(f["capital_final"] or 0), esperado, places=4,
                               msg=f"{broker}: el capital del mes en curso no cuadra")
        return float(f["capital_final"] or 0)

    def test_pase_de_hoy_deja_el_capital_del_mes_al_dia(self):
        """Un pase de hoy con un gasto de $5.000, en dos brokers que ya tienen el renglón
        del mes (un depósito de hoy). Después del pase, el capital final del mes de cada
        uno cuadra con sus aportes, retiros y realizado: A baja C más el gasto y B sube C.
        Antes quedaba con el de antes del pase (A con C de más, B con C de menos) hasta
        que alguien abría /mensual."""
        self._historia()
        hoy = main._iso_today()
        self._importar("Cocos", [f"{hoy},DEPOSITO,Cocos,,,,10000,,,,ARS,dep"])
        self._importar("Balanz", [f"{hoy},DEPOSITO,Balanz,,,,10000,,,,ARS,dep"])
        antes = {b: self._cuadra(b) for b in ("Cocos", "Balanz", "global")}
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", hoy, PRECIO_PASE, gasto=5000)
        despues = {b: self._cuadra(b) for b in ("Cocos", "Balanz", "global")}
        self.assertAlmostEqual(despues["Cocos"] - antes["Cocos"], -p["C"] - p["gasto_usd"],
                               places=2)
        self.assertAlmostEqual(despues["Balanz"] - antes["Balanz"], p["C"], places=2)
        self.assertAlmostEqual(despues["global"] - antes["global"], -p["gasto_usd"], places=2)

    def test_una_conversion_de_hoy_tambien(self):
        """La misma regla en la otra fuente que sólo arma el recálculo: una conversión de
        pesos a dólares de hoy (el persister mueve las cajas; las patas de capital las
        recompone `_fx_transfer_legs_for_period`). Cocos y «Cocos · USD» quedan con el
        capital del mes en curso que dicen sus flujos."""
        self._historia()
        hoy = main._iso_today()
        self._importar("Cocos", [f"{hoy},DEPOSITO,Cocos,,,,200000,,,,ARS,dep"])
        self._importar("Cocos", [f"{hoy},CONVERSION_ARS_USD,Cocos,,,,140000,100,1400,,,conv"])
        for b in ("Cocos", "Cocos · USD", "global"):
            self._cuadra(b)


class Concurrencia(_Confirmar):

    def test_un_renombre_no_se_mete_en_el_medio(self):
        """El confirmar toma el turno de la cuenta ANTES de leer los brokers, en los dos
        motores. En SQLite el turno de la puerta no hace nada y la base recién se tomaba
        con los lotes: un renombre de Balanz que entraba justo después de leer los
        brokers dejaba el pase escrito en «Balanz», un broker que ya no existía (10 NVDA
        huérfanos y el mes partido entre los dos nombres). Ahora el renombre espera a que
        el pase termine, y renombra también lo que el pase escribió."""
        import threading
        self._historia()
        conn = main.get_db()
        try:
            bid = conn.execute("SELECT id FROM brokers WHERE user_id=? AND name='Balanz'",
                               (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        body = self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, precio_manual=PRECIO_PASE)
        vista = self._ok(body)
        real = traspaso_a_mano.cuentas_del_pedido
        renombre = {}

        def renombrar():
            r = TestClient(main.app).put(f"/api/brokers/{bid}",
                                         json={"name": "Balanz Nuevo", "currency": "ARS"},
                                         headers=self.h)
            renombre["status"] = r.status_code

        def con_renombre_en_el_hueco(*a, **k):
            c = real(*a, **k)
            if "hilo" not in renombre:
                renombre["hilo"] = threading.Thread(target=renombrar)
                renombre["hilo"].start()
                renombre["hilo"].join(1.5)
                renombre["entro_en_el_hueco"] = not renombre["hilo"].is_alive()
            return c

        with mock.patch.object(traspaso_a_mano, "cuentas_del_pedido", con_renombre_en_el_hueco):
            r = self._confirmar(body, vista=vista)
        renombre["hilo"].join(60)
        self._esperar_reconstruccion()
        self.assertFalse(renombre["entro_en_el_hueco"], "el renombre no esperó al pase")
        self.assertEqual((r.status_code, renombre.get("status")), (200, 200), r.text)
        conn = main.get_db()
        try:
            donde = {(x["broker"], x["quantity"]) for x in conn.execute(
                "SELECT broker, quantity FROM positions WHERE user_id=? AND asset='NVDA' "
                "AND is_cash=0", (self.uid,))}
            meses = {x["broker"] for x in conn.execute(
                "SELECT DISTINCT broker FROM monthly_entries WHERE user_id=?", (self.uid,))}
        finally:
            conn.close()
        self.assertEqual(donde, {("Balanz Nuevo", 10.0)})
        self.assertNotIn("Balanz", meses)


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
