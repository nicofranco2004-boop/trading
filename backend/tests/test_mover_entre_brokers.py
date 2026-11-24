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

EL DESHACER Y LAS GUARDAS (E7). `POST /api/positions/traspaso/{id}/deshacer` y
`GET /api/positions/traspasos`, por HTTP. La prueba central es #12: `estado()` entero
(F.1: contabilidad, comisiones, Movimientos, el CSV de transacciones y las fotos
medidas) antes del pase == después del deshacer, con sus variantes. Las guardas de las
otras puertas (#20, #22–#26) frenan con su texto y no tocan nada.

LOS IMPORTS DESPUÉS DE UN PASE (E8). Con los archivos de verdad de Bull Market y
Balanz (`test_traspaso_entre_brokers.py`), por `POST /api/imports/preview` +
`/confirm` (y por `main.import_confirm(...)` directo, forzando los repetidos): la
llegada o la salida que el pase ya anotó no entra otra vez y queda anotada en el pase
(#15, #17, #44); una con otra fecha frena o entra con aviso (#16); lo que cambiaría la
historia anterior al pase frena el archivo entero (#17, #21); y en el orden inverso el
pase frena con instrucciones (#18, #19).

MOVIMIENTOS, EL CSV Y LAS COMISIONES (E9). `GET /api/movements`,
`GET /api/export/transactions.csv` y `GET /api/insights/commissions`, por HTTP: del
pase se ven sus dos patas (con `traspaso_id`, `contraparte` y `estado`) y el gasto, y
nada más cambia —ni la venta a precio 0 de A ni las compras de llegada en B, cuya
comisión se contaba dos veces—; la compra original de un lote cargado a mano que se
pasó sigue (`trp-…`). El total de comisiones queda igual (#6, #7).

EL DETECTOR DE DESFASE (E10). Si algo se escapa de las puertas —una fila sembrada
directo en el registro, o editar en grupo el precio promedio de lo que quedó en A—, el
próximo rearmado del registro (el rebuild real, un import, un borrado, la migración del
dólar) marca el pase desfasado; GET /traspasos, Movimientos e Importaciones lo dicen, y
el deshacer deja la cuenta como antes del pase (#34). Y no marca en falso: cada
`_rebuild()` de este archivo afirma qué pases quedaron marcados (ninguno, salvo los que
la prueba desfasó a propósito).

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

    def _rebuild(self, *, desfasados=frozenset()):
        """«Después del rebuild» (F.1): el rearmado entero, como el backfill.

        El rearmado corre el detector de pases desfasados (E10, D.5.5). Por eso cada
        rebuild de estas pruebas afirma además QUÉ pases quedaron marcados: ninguno
        salvo `desfasados` (los ids que la prueba desfasó a propósito). Así toda
        prueba que rearma una cuenta con pases sanos —totales, parciales, con lotes
        cargados a mano, encadenados, con los archivos de Bull Market y Balanz…— es
        también una prueba de que el detector no marca en falso. `desfasados=None`
        no mira."""
        conn = main.get_db()
        try:
            with conn:
                recompute_user(conn, self.uid, recalc=main._recalc_pnl_realized_from_ops)
            if desfasados is not None:
                marcados = {r["id"] for r in conn.execute(
                    "SELECT id FROM traspasos_a_mano WHERE user_id=? AND deshecho_at IS NULL "
                    "AND desfasado_at IS NOT NULL", (self.uid,))}
                self.assertEqual(marcados, set(desfasados),
                                 "el rebuild marcó desfasado un pase que no lo está (o no marcó "
                                 "el que sí)")
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
        la etapa E9, D.9: `CsvDeTransacciones`.)"""
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


# ═══════════════════════════════════════════════════════════════════════════════
# E7 — Deshacer el pase (C.8), cómo está cada pase (B.5) y las guardas (D.10, D.3.4)
# ═══════════════════════════════════════════════════════════════════════════════

# Fotos MEDIDAS del cron entre la fecha del pase y ayer, a mitad y a fin de mes, con
# su dólar y su composición: ningún pase ni deshacer las puede tocar (son mediciones
# a mercado de ese día, no se pueden volver a derivar).
FOTOS_MEDIDAS = {"2025-06-20": (1950.0, 1400.0), "2025-06-30": (1960.0, 1410.0),
                 "2025-07-15": (1970.0, 1420.0), "2025-07-31": (1980.0, 1430.0),
                 "2025-12-15": (1990.0, 1440.0), "2025-12-31": (2000.0, 1450.0),
                 "2026-03-15": (2010.0, 1460.0)}

MSG_DESHACE_EL_PASE = traspaso_a_mano.MSG_DESHACE_EL_PASE
MSG_REVERT_ES_PASE = traspaso_a_mano.MSG_REVERT_ES_PASE


class _Deshacer(_Confirmar):
    """Lo que necesitan las pruebas del deshacer: las dos puertas nuevas por HTTP y el
    `estado()` entero de F.1 (la contabilidad, lo que publican Movimientos, las
    comisiones y el CSV de transacciones, y las fotos medidas)."""
    maxDiff = None

    def _deshacer(self, tid, headers=None):
        return self.http.post(f"/api/positions/traspaso/{tid}/deshacer", headers=headers or self.h)

    def _deshacer_ok(self, tid):
        r = self._deshacer(tid)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(set(r.json()), {"ok", "mensaje"})
        return r.json()["mensaje"]

    def _no_deshace(self, tid, status, texto):
        r = self._deshacer(tid)
        self.assertEqual(r.status_code, status, r.text)
        self.assertEqual(r.json()["detail"], texto)
        return r

    def _traspasos(self, headers=None):
        r = self.http.get("/api/positions/traspasos", headers=headers or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _uno(self, tid):
        hay = [t for t in self._traspasos()["traspasos"] if t["id"] == tid]
        self.assertEqual(len(hay), 1, f"el pase {tid} no está en GET /traspasos")
        return hay[0]

    def _plantar_fotos(self):
        conn = main.get_db()
        try:
            for d, (valor, aportado) in FOTOS_MEDIDAS.items():
                conn.execute(
                    """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                           net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                       VALUES (?,?,?,?,?,1200,'[{"asset": "NVDA", "value_usd": 1}]',
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

    def _get(self, url):
        r = self.http.get(url, headers=self.h)
        self.assertEqual(r.status_code, 200, f"{url}: {r.text[:300]}")
        return r

    def estado_completo(self):
        """`estado()` de F.1 entero: la contabilidad (`estado`), las comisiones, lo que
        publica Movimientos, las filas del CSV de transacciones y las fotos MEDIDAS
        (las del cron, sin la de hoy, que se reescribe sola)."""
        e = self.estado()
        com = self._get("/api/insights/commissions").json()
        e["comisiones"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in com.items()}
        movs = self._get("/api/movements").json()
        movs = movs.get("movements", movs) if isinstance(movs, dict) else movs
        e["movimientos"] = sorted(
            (str(m.get("type")), str(m.get("date"))[:10], str(m.get("broker")),
             str(m.get("asset") or ""), round(float(m.get("amount_usd") or 0), 2),
             round(float(m.get("fees_usd") or 0), 2), round(float(m.get("quantity") or 0), 6))
            for m in movs)
        filas = list(csv.reader(io.StringIO(self._get("/api/export/transactions.csv").text)))
        e["csv"] = sorted(tuple(f) for f in filas)
        conn = main.get_db()
        try:
            e["fotos"] = sorted(
                (r["date"], round(float(r["total_value"]), 4), round(float(r["net_deposited"]), 4))
                for r in conn.execute(
                    "SELECT date, total_value, net_deposited FROM snapshots WHERE user_id=? "
                    "AND fx_to_usd_blue IS NOT NULL AND date < ?", (self.uid, main._iso_today())))
            e["brokers"] = sorted(r["name"] for r in conn.execute(
                "SELECT name FROM brokers WHERE user_id=?", (self.uid,)))
        finally:
            conn.close()
        return e

    def _igual(self, despues, antes, sin=()):
        """Igual clave por clave. La contabilidad de cada mes (`mensual`) con la
        tolerancia de la propia cadena (`_repair_monthly_chain`, EPS = US$ 0,01): un
        import con una venta deja el mes de la venta con un resto PREEXISTENTE —el
        persister escribe el capital final con el resultado sin redondear (8,5275) y el
        recálculo pone el realizado en 8,53 sin rearmar el capital de un mes cerrado:
        2,5 diezmilésimos medidos—, que la reparación no toca por debajo de EPS. Una
        puerta que cambia el capital inicial de esos meses (el pase y su deshacer) los
        rearma con la fórmula y el resto desaparece; la comparación lo vería como un
        cambio del pase."""
        for clave in antes:
            if clave in sin:
                continue
            if clave == "mensual":
                self.assertEqual(set(despues[clave]), set(antes[clave]), "cambiaron los meses")
                lejos = {k: (antes[clave][k], despues[clave][k]) for k in antes[clave]
                         if any(abs(a - b) > 0.01 for a, b in zip(antes[clave][k],
                                                                   despues[clave][k]))}
                self.assertEqual(lejos, {}, "cambió «mensual» (antes, después)")
                continue
            self.assertEqual(despues[clave], antes[clave], f"cambió «{clave}»")

    def _lotes_del_pase(self, tid):
        conn = main.get_db()
        try:
            reg = conn.execute("SELECT lote_salida, lote_entrada, deshecho_at FROM traspasos_a_mano "
                               "WHERE id=? AND user_id=?", (tid, self.uid)).fetchone()
            estados = [conn.execute("SELECT status FROM import_batches WHERE id=?", (x,))
                       .fetchone()["status"] for x in (reg["lote_salida"], reg["lote_entrada"])]
            return estados, reg["deshecho_at"]
        finally:
            conn.close()

    def _id_broker(self, nombre):
        conn = main.get_db()
        try:
            return conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                (self.uid, nombre)).fetchone()["id"]
        finally:
            conn.close()

    def _lote_original(self, broker="Cocos"):
        """El import de la historia de ese broker (no un lote de pase)."""
        conn = main.get_db()
        try:
            return conn.execute(
                "SELECT id FROM import_batches WHERE user_id=? AND broker=? AND status='confirmed' "
                "AND COALESCE(parser_format,'') <> 'traspaso_a_mano' ORDER BY created_at, id",
                (self.uid, broker)).fetchone()["id"]
        finally:
            conn.close()

    def _fila(self, tid, op, lote="lote_salida"):
        conn = main.get_db()
        try:
            return conn.execute(
                f"SELECT n.id FROM import_normalized_tx n JOIN traspasos_a_mano t "
                f"ON t.{lote} = n.batch_id WHERE t.id=? AND n.operation_type=? ORDER BY n.id",
                (tid, op)).fetchone()["id"]
        finally:
            conn.close()


class DeshacerDejaLaCuentaIdentica(_Deshacer):

    def test_deshacer_deja_la_cuenta_identica(self):
        """#12, la prueba más importante de la función. Fecha del pase de un mes
        anterior, un gasto de $5.000 y fotos medidas plantadas entre la fecha y ayer.
        `estado()` (F.1 entero) antes del pase == después del deshacer; los dos lotes
        del pase quedan 'reverted' y el registro deshecho. Y lo mismo después del
        rebuild real, y el segundo click dice que ya se deshizo."""
        self._historia()
        self._plantar_fotos()
        antes = self.estado_completo()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, gasto=5000)
        tid = p["traspaso_id"]
        durante = self.estado_completo()
        self.assertNotEqual(durante["lotes"], antes["lotes"], "control: el pase movió los lotes")
        self.assertEqual(durante["fotos"], antes["fotos"], "el pase tocó una foto medida")
        t = self._uno(tid)
        self.assertEqual({k: t[k] for k in ("estado", "puede_deshacer", "motivo", "aviso",
                                            "broker_origen", "broker_destino", "asset",
                                            "cantidad", "moneda", "fecha")},
                         {"estado": "vivo", "puede_deshacer": True, "motivo": None, "aviso": None,
                          "broker_origen": "Cocos", "broker_destino": "Balanz", "asset": "NVDA",
                          "cantidad": 10.0, "moneda": "ARS", "fecha": FECHA_PASE})
        self.assertAlmostEqual(t["valor_usd"], round(p["V"], 2), places=2)
        self.assertAlmostEqual(t["costo_usd"], round(p["C"], 2), places=2)

        self.assertEqual(self._deshacer_ok(tid), "Listo: los 10 NVDA volvieron a Cocos.")
        self._igual(self.estado_completo(), antes)
        self.assertEqual(self._lotes_del_pase(tid)[0], ["reverted", "reverted"])
        self.assertIsNotNone(self._lotes_del_pase(tid)[1])
        self.assertEqual(self._traspasos()["traspasos"], [])
        self._no_deshace(tid, 409, "Ese pase ya se deshizo.")
        self._rebuild()
        self._igual(self.estado_completo(), antes)

    def test_lote_cargado_a_mano_parcial(self):
        """#12, variante: un lote cargado a mano del que se pasa una parte (y uno viejo,
        sin `invested`: su costo es precio × cantidad). Vuelven enteros, con su foto."""
        self._historia()
        self._broker("IOL")
        self._lote_a_mano("IOL", "GGAL", 10, 1000, "2025-02-03", notes="compra del aguinaldo")
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO positions (user_id, broker, asset, quantity, invested, buy_price, "
                "commissions, entry_date, is_cash, currency, asset_type) VALUES "
                "(?, 'IOL', 'GGAL', 6, NULL, 1100, 30, '2025-03-03', 0, 'ARS', 'STOCK')",
                (self.uid,))
            conn.commit()
        finally:
            conn.close()
        self._plantar_fotos()
        antes = self.estado_completo()
        p = self._fabricar_pase("GGAL", "IOL", "Balanz", FECHA_PASE, 1500, cantidad=13)
        self.assertEqual([(l["origen"], l["parcial"]) for l in p["receta"]["lotes"]],
                         [("a_mano", False), ("a_mano", True)])
        self.assertEqual(self._deshacer_ok(p["traspaso_id"]), "Listo: los 13 GGAL volvieron a IOL.")
        self._igual(self.estado_completo(), antes)
        # El que salió entero vuelve con su foto: también sus notas.
        self.assertEqual(self._lote("IOL", "GGAL", "2025-02-03")["notes"], "compra del aguinaldo")

    def test_importados_y_a_mano_con_un_importado_parcial(self):
        """#12, variante: un lote cargado a mano viejo (2 del 02/01) y el importado (10
        del 10/01); se pasan 7 (el a mano entero y 5 del importado). A queda a salvo
        (sólo importados): el deshacer la rearma desde el registro y devuelve el que
        era a mano con su foto."""
        self._historia()
        self._lote_a_mano("Cocos", "NVDA", 2, 28000, "2025-01-02")
        self._plantar_fotos()
        antes = self.estado_completo()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=7)
        self.assertEqual([(l["origen"], l["parcial"]) for l in p["receta"]["lotes"]],
                         [("a_mano", False), ("importado", True)])
        partido = p["receta"]["lotes"][1]["lote_id"]
        self._deshacer_ok(p["traspaso_id"])
        self._igual(self.estado_completo(), antes)
        # A quedó a salvo, así que se rearmó desde el registro (C.8 paso 3 a): el lote
        # importado renace entero, con un id nuevo. Por el vínculo (paso 3 b) habría
        # vuelto sumándole al mismo id.
        self.assertNotEqual(self._lote("Cocos", entry_date="2025-01-10")["id"], partido)

    def test_con_un_rebuild_de_a_en_el_medio(self):
        """#12, variante: entre el pase y el deshacer A se rearma entero (el rebuild
        real, como el backfill) y tiene una venta posterior de OTRO activo. Los ids de
        lo que quedó en A cambian: el deshacer no busca por id."""
        self._historia()
        self._importar("Cocos", ["2025-07-01,COMPRA,Cocos,AAPL,5,20000,100000,,,0,ARS,compra",
                                 "2025-08-01,VENTA,Cocos,AAPL,2,25000,50000,,,0,ARS,venta"])
        self._plantar_fotos()
        antes = self.estado_completo()
        ids_antes = {l["id"] for l in self._lotes_ids("Cocos")}
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        self._rebuild()
        self.assertFalse({l["id"] for l in self._lotes_ids("Cocos")} & ids_antes,
                         "control: el rebuild del medio cambió los ids de A")
        self._deshacer_ok(p["traspaso_id"])
        self._igual(self.estado_completo(), antes)

    def _lotes_ids(self, broker):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT id FROM positions WHERE user_id=? AND broker=? AND is_cash=0",
                (self.uid, broker))]
        finally:
            conn.close()

    def test_a_no_reconstruible_vuelve_por_el_vinculo(self):
        """C.8 paso 3 (b) y `_devolver_al_lote(link=…)`: A tiene además un lote cargado a
        mano del activo, así que no se puede rearmar. Un pase parcial del importado
        vuelve sumándole al lote vivo; uno total lo vuelve a crear (con su id) y deja el
        vínculo de la fila de origen apuntándole: después, revertir el archivo original
        de A lo saca, sin dejar un lote huérfano."""
        self._historia()
        self._lote_a_mano("Cocos", "NVDA", 3, 33000, "2025-03-01")
        antes = self.estado_completo()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=4)
        self.assertEqual([(l["origen"], l["parcial"]) for l in p["receta"]["lotes"]],
                         [("importado", True)])
        partido = p["receta"]["lotes"][0]["lote_id"]
        self._deshacer_ok(p["traspaso_id"])
        self._igual(self.estado_completo(), antes)
        self.assertEqual(self._lote("Cocos", entry_date="2025-01-10")["id"], partido,
                         "A no se puede rearmar: el lote vuelve por el vínculo, al mismo id")

        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=10)
        lote = p["receta"]["lotes"][0]
        self.assertEqual((lote["origen"], lote["parcial"]), ("importado", False))
        self.assertIsNone(self._lote("Cocos", entry_date="2025-01-10"), "control: salió entero")
        self._deshacer_ok(p["traspaso_id"])
        self._igual(self.estado_completo(), antes)
        vuelto = self._lote("Cocos", entry_date="2025-01-10")
        self.assertEqual(vuelto["id"], lote["lote_id"], "vuelve con su mismo id")
        fo = lote["fila_origen"]
        conn = main.get_db()
        try:
            self.assertEqual([r["position_id"] for r in conn.execute(
                "SELECT position_id FROM import_op_links WHERE batch_id=? AND raw_row_id=?",
                (fo["batch_id"], fo["raw_row_id"]))], [vuelto["id"]])
        finally:
            conn.close()
        r = self.http.post(f"/api/imports/{self._lote_original('Cocos')}/revert", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual([(l[0], l[3]) for l in self._sin_ids("Cocos")], [(3.0, "2025-03-01")],
                         "revertir el archivo de A dejó un lote huérfano")

    def test_con_el_id_ocupado_el_vinculo_sigue_al_lote_nuevo(self):
        """`_devolver_al_lote(link=…)`, el borde: si el id del lote que salió entero ya
        no está libre, vuelve con uno nuevo y el vínculo de su fila de origen (y el lote
        que el revert del archivo borra) pasa a ese id. Sin eso, revertir el archivo
        original de A dejaba el lote huérfano. (Los ids no se reusan: se ocupa a mano,
        con un lote de otra cuenta.)"""
        self._historia()
        self._lote_a_mano("Cocos", "NVDA", 3, 33000, "2025-03-01")
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=10)
        lote = p["receta"]["lotes"][0]
        conn = main.get_db()
        try:
            otro = conn.execute(
                "INSERT INTO users (email, password_hash, approved, tier) VALUES (?, 'x', 1, 'plus')",
                (f"ocupa-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'X', 'USD')",
                         (otro,))
            conn.execute("INSERT INTO positions (id, user_id, broker, asset, is_cash, quantity, "
                         "invested, buy_price) VALUES (?, ?, 'X', 'ZZZ', 0, 1, 1, 1)",
                         (lote["lote_id"], otro))
            conn.commit()
        finally:
            conn.close()
        self._deshacer_ok(p["traspaso_id"])
        vuelto = self._lote("Cocos", entry_date="2025-01-10")
        self.assertNotEqual(vuelto["id"], lote["lote_id"])
        fo = lote["fila_origen"]
        conn = main.get_db()
        try:
            self.assertEqual([r["position_id"] for r in conn.execute(
                "SELECT position_id FROM import_op_links WHERE batch_id=? AND raw_row_id=?",
                (fo["batch_id"], fo["raw_row_id"]))], [vuelto["id"]])
        finally:
            conn.close()
        r = self.http.post(f"/api/imports/{self._lote_original('Cocos')}/revert", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual([(l[0], l[3]) for l in self._sin_ids("Cocos")], [(3.0, "2025-03-01")])

    def test_gasto_vuelve_a_la_caja(self):
        """#8, el deshacer: el gasto (US$ 5) vuelve a la caja de A y el realizado de A
        deja de llevarlo; la identidad vuelve a ser la de antes del pase."""
        self._broker("IBKR", "USD")
        self._broker("Schwab", "USD")
        self._importar("IBKR", ["2025-01-05,DEPOSITO,IBKR,,,,1000,,,,USD,dep",
                                "2025-01-10,COMPRA,IBKR,MSFT,2,300,600,,,1,USD,compra"])
        antes = self.estado()
        p = self._aplicar(self._pedido("MSFT", "IBKR", "Schwab", FECHA_PASE, moneda="USD",
                                       precio_manual=420, gasto={"monto": 5, "moneda": "USD"}))
        self.assertEqual(self.estado()["caja"]["IBKR"], 394.0)
        self._deshacer_ok(p["traspaso_id"])
        despues = self.estado()
        self.assertEqual(despues["caja"]["IBKR"], 399.0)
        self.assertEqual({k: v for k, v in despues.items() if k != "mensual"},
                         {k: v for k, v in antes.items() if k != "mensual"})
        for k, v in antes["mensual"].items():
            if k[0] in ("IBKR", "global"):
                self.assertEqual(despues["mensual"][k], v, k)
        for k, v in despues["mensual"].items():
            if k[0] == "Schwab":
                self.assertEqual(v, (0.0, 0.0, 0.0, 0.0), f"Schwab sin el pase {k}")

    def test_precio_cargado_vuelve(self):
        """C.8 paso 5 y el precio de A: el precio cargado a mano viajó a B (que no tenía
        uno); al deshacer, B vuelve a no tenerlo y A lo recupera aunque el pase se haya
        llevado todos sus lotes."""
        self._historia()
        # Balanz tiene su propio NVDA, sin precio cargado: el pase se lo pone (C.7.8).
        self._importar("Balanz", ["2025-03-01,COMPRA,Balanz,NVDA,3,35000,105000,,,0,ARS,compra"])
        conn = main.get_db()
        try:
            conn.execute("UPDATE positions SET price_override=46000 WHERE user_id=? "
                         "AND broker='Cocos' AND asset='NVDA' AND is_cash=0", (self.uid,))
            conn.commit()
        finally:
            conn.close()
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", main._iso_today()))
        self.assertEqual(p["receta"]["precio_cargado_en_destino"]["brokers_destino"], ["Balanz"])
        self._deshacer_ok(p["traspaso_id"])
        conn = main.get_db()
        try:
            precios = sorted((r["broker"], r["price_override"]) for r in conn.execute(
                "SELECT broker, price_override FROM positions WHERE user_id=? AND asset='NVDA' "
                "AND is_cash=0", (self.uid,)))
        finally:
            conn.close()
        self.assertEqual(precios, [("Balanz", None), ("Cocos", 46000.0)])

    def test_cuenta_manual_deshacer_no_borra_fotos(self):
        """#46 (la parte del deshacer, por HTTP): una cuenta 100 % cargada a mano hace un
        pase y lo deshace; la cuenta no pasa a reconstruible y las fotos del cron
        quedan intactas."""
        self._broker("IBKR", "USD")
        self._broker("Schwab", "USD")
        self._lote_a_mano("IBKR", "MSFT", 5, 300, "2025-02-01", moneda="USD")
        self._plantar_fotos()
        antes = self.estado_completo()
        p = self._aplicar(self._pedido("MSFT", "IBKR", "Schwab", "2025-06-10", moneda="USD",
                                       precio_manual=380))
        self._deshacer_ok(p["traspaso_id"])
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute(bf._HAY_IMPORT_RECONSTRUIBLE, (self.uid,)).fetchone())
        finally:
            conn.close()
        despues = self.estado_completo()
        self.assertEqual(despues["fotos"], antes["fotos"])
        self.assertEqual(despues["lotes"], antes["lotes"])
        self.assertEqual(despues["caja"], antes["caja"])


class DeshacerBloqueado(_Deshacer):

    def test_deshacer_bloqueado_si_b_vendio_o_lo_paso(self):
        """#13. Una venta en B de lo que llegó → 409 «vendiste»; borrar la venta → se
        deshace. Un pase posterior B → IOL → deshacer A → B da 409 «los pasaste a IOL»;
        deshecho ése, el primero se deshace."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        tid = p["traspaso_id"]
        r = self.http.post("/api/positions/sell", headers=self.h, json={
            "broker": "Balanz", "asset": "NVDA", "quantity": 3, "exit_price": 50000,
            "date": "2025-07-01", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        texto = ("Los NVDA que llegaron a Balanz ya no están como llegaron: vendiste 3 de los "
                 "10. Para deshacer el pase, primero borrá esa venta.")
        self._no_deshace(tid, 409, texto)
        t = self._uno(tid)
        self.assertEqual((t["puede_deshacer"], t["motivo"]), (False, texto))
        conn = main.get_db()
        try:
            oid = conn.execute("SELECT id FROM operations WHERE user_id=? AND op_type='Venta' "
                               "ORDER BY id DESC", (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        r = self.http.delete(f"/api/operations/{oid}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._deshacer_ok(tid)

        self._broker("IOL")
        p1 = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        p2 = self._fabricar_pase("NVDA", "Balanz", "IOL", "2025-08-01", PRECIO_PASE)
        self._no_deshace(p1["traspaso_id"], 409,
                         "Los NVDA que llegaron a Balanz los pasaste a IOL el 01/08. Deshacé "
                         "primero ese pase.")
        self._deshacer_ok(p2["traspaso_id"])
        self._deshacer_ok(p1["traspaso_id"])
        self.assertEqual(self._sin_ids("Balanz") + self._sin_ids("IOL"), [])
        self.assertEqual([l[0] for l in self._sin_ids("Cocos")], [10.0])

    def test_deshacer_bloqueado_si_a_vendio_despues(self):
        """#14. Una venta en A posterior al pase → 409; borrarla → se deshace. Un pase
        posterior A → IOL → 409 «deshacé primero ese pase». Y una venta en A del MISMO
        día del pase, anotada antes, no frena (ya estaba)."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        r = self.http.post("/api/positions/sell", headers=self.h, json={
            "broker": "Cocos", "asset": "NVDA", "quantity": 2, "exit_price": 50000,
            "date": "2025-07-01", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._no_deshace(p["traspaso_id"], 409,
                         "Después de este pase vendiste NVDA en Cocos el 01/07. Para deshacerlo, "
                         "primero borrá esa venta.")
        conn = main.get_db()
        try:
            oid = conn.execute("SELECT id FROM operations WHERE user_id=? AND op_type='Venta' "
                               "ORDER BY id DESC", (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        self.assertEqual(self.http.delete(f"/api/operations/{oid}", headers=self.h).status_code, 200)
        self._esperar_reconstruccion()
        self._deshacer_ok(p["traspaso_id"])

        self._broker("IOL")
        p1 = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        p2 = self._fabricar_pase("NVDA", "Cocos", "IOL", "2025-08-01", PRECIO_PASE)
        self._no_deshace(p1["traspaso_id"], 409,
                         "Después de este pase pasaste NVDA de Cocos a IOL el 01/08. Deshacé "
                         "primero ese pase.")
        self._deshacer_ok(p2["traspaso_id"])
        self._deshacer_ok(p1["traspaso_id"])

        # La venta del mismo día, anotada ANTES del pase: ya estaba, no frena.
        r = self.http.post("/api/positions/sell", headers=self.h, json={
            "broker": "Cocos", "asset": "NVDA", "quantity": 1, "exit_price": 50000,
            "date": FECHA_PASE, "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=4)
        self.assertTrue(self._uno(p["traspaso_id"])["puede_deshacer"])
        self._deshacer_ok(p["traspaso_id"])
        self.assertEqual(sum(l[0] for l in self._sin_ids("Cocos")), 9.0)

    def test_idor_y_un_pase_que_no_existe(self):
        """#30, la parte del deshacer: el pase de otra cuenta da el mismo 404 que uno que
        no existe, y GET /traspasos sólo trae los propios."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        conn = main.get_db()
        try:
            otro = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'plus')", (f"otro-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        finally:
            conn.close()
        h2 = {"Authorization": f"Bearer {main.create_token(otro)}"}
        r = self._deshacer(p["traspaso_id"], headers=h2)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "No encontramos ese pase."))
        self.assertEqual(self._traspasos(headers=h2)["traspasos"], [])
        self._no_deshace("no-existe", 404, "No encontramos ese pase.")
        self.assertEqual(self._lotes_del_pase(p["traspaso_id"])[0], ["confirmed", "confirmed"])


class InterruptorYEstados(_Deshacer):

    def test_deshacer_anda_con_el_interruptor_apagado(self):
        """B.4 y G.3: apagar el interruptor frena pases nuevos (y GET dice
        `habilitado: false`), pero los hechos se siguen viendo y deshaciendo. Es lo que
        hay que hacer antes de volver atrás un deploy."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        self.assertTrue(self._traspasos()["habilitado"])
        self._interruptor(False)
        t = self._traspasos()
        self.assertFalse(t["habilitado"])
        self.assertEqual([x["id"] for x in t["traspasos"]], [p["traspaso_id"]])
        self.assertEqual(self._vista(self._pedido("NVDA", "Balanz", "Cocos", FECHA_PASE,
                                                  precio_manual=PRECIO_PASE)).status_code, 403)
        self._deshacer_ok(p["traspaso_id"])

    def test_desfasado_se_ve_y_se_deshace(self):
        """B.5: un pase marcado desfasado (el detector es de E10; acá se marca a mano)
        dice `desfasado` con el aviso, y se deshace igual."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        conn = main.get_db()
        try:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=datetime('now'), "
                         "desfasado_motivo='origen' WHERE id=?", (p["traspaso_id"],))
            conn.commit()
        finally:
            conn.close()
        t = self._uno(p["traspaso_id"])
        self.assertEqual((t["estado"], t["aviso"], t["puede_deshacer"]),
                         ("desfasado", "Cambió la historia de Cocos y este pase quedó "
                                       "desactualizado: deshacelo y hacelo de nuevo.", True))
        self._deshacer_ok(p["traspaso_id"])


class OtrasPuertas(_Deshacer):

    def test_no_se_desarma_por_otras_puertas(self):
        """#20. Mientras el pase está vivo, ninguna otra puerta lo desarma: cada una
        frena con su texto y la cuenta queda igual. Al final el deshacer deja la cuenta
        como antes del pase."""
        self._historia()
        self._lote_a_mano("Cocos", "NVDA", 2, 28000, "2025-01-02")
        # Una edición de grupo ANTES del pase (con su deshacer guardado).
        r = self.http.patch("/api/positions/group", headers=self.h, json={
            "broker": "Cocos", "asset": "NVDA", "tc_mode": "fixed", "tc_value": 998})
        self.assertEqual(r.status_code, 200, r.text)
        tok = r.json()
        self._esperar_reconstruccion()
        antes = self.estado_completo()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=7,
                                gasto=2000)
        tid = p["traspaso_id"]
        durante = self.estado_completo()
        a_mano, importado = p["receta"]["lotes"]
        self.assertEqual((a_mano["origen"], importado["origen"], importado["parcial"]),
                         ("a_mano", "importado", True))
        original = self._lote_original("Cocos")
        lote_b = self._lote("Balanz", entry_date="2025-01-10")

        def frena(r, status, texto=None, contiene=None):
            self.assertEqual(r.status_code, status, r.text)
            if texto is not None:
                self.assertEqual(r.json()["detail"], texto)
            if contiene is not None:
                self.assertIn(contiene, r.json()["detail"])
            self._esperar_reconstruccion()
            self._igual(self.estado_completo(), durante)

        for lote in (p["lote_salida"], p["lote_entrada"]):
            frena(self.http.post(f"/api/imports/{lote}/revert", headers=self.h), 400,
                  MSG_REVERT_ES_PASE)
            frena(self.http.post(f"/api/imports/{lote}/redo", headers=self.h), 400,
                  MSG_REVERT_ES_PASE)
        for op, lote in (("SELL", "lote_salida"), ("TRASPASO_SALIDA", "lote_salida"),
                         ("FEE", "lote_salida"), ("BUY", "lote_entrada"),
                         ("TRASPASO_ENTRADA", "lote_entrada")):
            frena(self.http.delete(f"/api/movements/tx-{self._fila(tid, op, lote)}",
                                   headers=self.h), 409, MSG_DESHACE_EL_PASE)
        frena(self.http.delete(f"/api/positions/{lote_b['id']}", headers=self.h), 409,
              MSG_DESHACE_EL_PASE)
        # Lo que queda en A del lote importado partido: por Cartera (el lote) y por
        # Movimientos (su compra).
        frena(self.http.delete(f"/api/positions/{importado['lote_id']}", headers=self.h), 409,
              traspaso_a_mano.MSG_LOTE_PASADO)
        conn = main.get_db()
        try:
            compra = conn.execute(
                "SELECT id FROM import_normalized_tx WHERE batch_id=? AND raw_row_id=?",
                (importado["fila_origen"]["batch_id"],
                 importado["fila_origen"]["raw_row_id"])).fetchone()["id"]
        finally:
            conn.close()
        frena(self.http.delete(f"/api/movements/tx-{compra}", headers=self.h), 409,
              "Parte de esta compra se pasó a Balanz el 16/06. Para borrarla, primero deshacé "
              "ese pase.")
        frena(self.http.delete("/api/assets/history", params={"asset": "NVDA"}, headers=self.h),
              409, traspaso_a_mano.MSG_ACTIVO_CON_PASE)
        origen = ("Hay títulos de esta importación que pasaste a Balanz el 16/06/2025. "
                  "Deshacé ese pase antes de revertir el archivo.")
        frena(self.http.post(f"/api/imports/{original}/revert", headers=self.h), 400, origen)
        frena(self.http.post(f"/api/imports/{original}/redo", headers=self.h), 400,
              contiene=origen)
        for cambio in ({"new_asset": "NVDA2"}, {"new_asset_type": "STOCK"}):
            frena(self.http.patch("/api/positions/group", headers=self.h,
                                  json={"broker": "Cocos", "asset": "NVDA", **cambio}),
                  409, traspaso_a_mano.MSG_EDITAR_ACTIVO_CON_PASE)
            frena(self.http.patch("/api/positions/group", headers=self.h,
                                  json={"broker": "Balanz", "asset": "NVDA", **cambio}),
                  409, traspaso_a_mano.MSG_EDITAR_ACTIVO_CON_PASE)
        # La edición de grupo hecha ANTES del pase no se deshace después (D.10.15).
        frena(self.http.post(f"/api/positions/group/undo/{tok['undo_token']}", headers=self.h),
              409, traspaso_a_mano.MSG_EDITAR_ACTIVO_CON_PASE)
        frena(self.http.post("/api/imports/wipe-broker", params={"broker": "Cocos"},
                             headers=self.h), 409, traspaso_a_mano.MSG_LIMPIAR_CON_PASE)
        frena(self.http.post("/api/imports/wipe-broker", params={"broker": "Balanz"},
                             headers=self.h), 409, traspaso_a_mano.MSG_LIMPIAR_CON_PASE)

        self._deshacer_ok(tid)
        self._igual(self.estado_completo(), antes)
        # Deshecho el pase, la edición de antes se deshace y las puertas vuelven a andar.
        r = self.http.post(f"/api/positions/group/undo/{tok['undo_token']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def test_cambios_anteriores_al_pase_frenan_en_las_puertas_de_borrado(self):
        """C.11 en las puertas de E7 (#21, la parte que no es del importador): borrar
        una venta importada de A anterior al pase (o del mismo día) → 409; deshacer el
        borrado de una compra de A más vieja que lo que se movió, hecho antes del pase →
        409. Deshecho el pase, las dos puertas vuelven a andar."""
        self._importar("Cocos", [
            "2025-01-05,DEPOSITO,Cocos,,,,900000,,,,ARS,dep",
            "2025-01-08,COMPRA,Cocos,NVDA,2,29000,58000,,,0,ARS,compra",
            "2025-01-10,COMPRA,Cocos,NVDA,10,30000,300000,,,0,ARS,compra"])

        def tx(op, fecha):
            conn = main.get_db()
            try:
                return conn.execute(
                    "SELECT n.id FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
                    "WHERE b.user_id=? AND n.operation_type=? AND n.date=?",
                    (self.uid, op, fecha)).fetchone()["id"]
            finally:
                conn.close()
        # Borrada ANTES del pase (con su deshacer guardado): la compra del 08/01, más
        # vieja que lo que después se mueve.
        r = self.http.delete(f"/api/movements/tx-{tx('BUY', '2025-01-08')}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["undo_token"]
        self._esperar_reconstruccion()
        self._importar("Cocos", ["2025-03-10,VENTA,Cocos,NVDA,1,35000,35000,,,0,ARS,venta",
                                 "2025-09-10,VENTA,Cocos,NVDA,1,36000,36000,,,0,ARS,venta"])
        venta_mar, venta_sep = tx("SELL", "2025-03-10"), tx("SELL", "2025-09-10")
        # Con la fecha del 16/06 la venta de septiembre quedaría después y frenaría el
        # pase (#15): va el 10/09, el mismo día.
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", "2025-09-10", PRECIO_PASE, cantidad=6)
        cambia = ("Esto cambia la historia de NVDA en Cocos antes de tu pase del 10/09/2025 a "
                  "Balanz, y el pase quedaría con otros lotes. Primero deshacé el pase "
                  "(Movimientos → la fila «Pase» → Deshacer), hacé este cambio y después volvé "
                  "a moverlos.")
        r = self.http.delete(f"/api/movements/tx-{venta_mar}", headers=self.h)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, cambia))
        r = self.http.post(f"/api/operations/undo/{token}", headers=self.h)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, cambia))
        # La del mismo día del pase también es «antes» (la consumió primero).
        r = self.http.delete(f"/api/movements/tx-{venta_sep}", headers=self.h)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, cambia))
        self._deshacer_ok(p["traspaso_id"])
        r = self.http.post(f"/api/operations/undo/{token}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)


class DeshacerUnBorradoDeHistorial(_Deshacer):

    def test_deshacer_el_borrado_del_historial_anterior_al_pase_frena(self):
        """C.11 en el deshacer del borrado del historial de un activo (la misma regla
        que D.10.11): se borró el historial importado de NVDA en Cocos (la compra del
        10/01), después se cargó a mano un lote del 01/02 y se lo pasó a Balanz. Deshacer
        el borrado devolvería una compra más vieja que lo que se movió: el pase habría
        consumido otra cosa. Frena; deshecho el pase, anda."""
        self._historia()
        r = self.http.delete("/api/assets/history", params={"asset": "NVDA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["undo_token"]
        self._esperar_reconstruccion()
        self._lote_a_mano("Cocos", "NVDA", 2, 31000, "2025-02-01")
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        r = self.http.post(f"/api/assets/undo/{token}", headers=self.h)
        self.assertEqual((r.status_code, r.json()["detail"]), (409,
                         "Esto cambia la historia de NVDA en Cocos antes de tu pase del "
                         "16/06/2025 a Balanz, y el pase quedaría con otros lotes. Primero "
                         "deshacé el pase (Movimientos → la fila «Pase» → Deshacer), hacé este "
                         "cambio y después volvé a moverlos."))
        cambia = r.json()["detail"]
        self._deshacer_ok(p["traspaso_id"])
        # Deshecho el pase, la regla del pase ya no frena. (Frena la de siempre: con el
        # lote cargado a mano de vuelta, deshacer el borrado se lo llevaría.)
        r = self.http.post(f"/api/assets/undo/{token}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertNotEqual(r.json()["detail"], cambia)
        self.assertIn("cargadas a mano", r.json()["detail"])


class BorrarUnLadoYDeshacer(_Deshacer):

    def test_borrar_a_y_deshacer_lo_que_queda(self):
        """#22. Borrar Cocos (A) pide confirmación con `counts.traspasos`; con
        `?force=true`, el global del mes ve sólo la pata de B (aportes + V, realizado −(V
        − C)); GET dice `incompleto`; deshacer saca los títulos de B y el global queda
        sin la pata."""
        self._historia()
        antes = self._mensual()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        V, C = p["V"], p["C"]
        r = self.http.delete(f"/api/brokers/{self._id_broker('Cocos')}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["counts"]["traspasos"], 1)
        r = self.http.delete(f"/api/brokers/{self._id_broker('Cocos')}", params={"force": "true"},
                             headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        m = self._mensual()
        jun = ("global", 2025, 6)
        self.assertAlmostEqual(m[jun]["deposits"], antes[("Balanz", 2025, 6)]["deposits"] + V,
                               places=4)
        self.assertAlmostEqual(m[jun]["pnl_realized"], -(V - C), places=4)
        t = self._uno(p["traspaso_id"])
        self.assertEqual((t["estado"], t["puede_deshacer"], t["broker_origen"]),
                         ("incompleto", True, "Cocos"))
        self.assertEqual(self._deshacer_ok(p["traspaso_id"]), "Listo: los 10 NVDA salieron de Balanz.")
        self.assertEqual(self._sin_ids("Balanz"), [])
        m = self._mensual()
        self.assertAlmostEqual(m[jun]["deposits"], antes[("Balanz", 2025, 6)]["deposits"], places=4)
        self.assertAlmostEqual(m[jun]["pnl_realized"], 0.0, places=4)
        self.assertIsNotNone(self._lotes_del_pase(p["traspaso_id"])[1])
        self.assertEqual(self._traspasos()["traspasos"], [])

    def test_borrar_b_y_deshacer_lo_que_queda(self):
        """#23. El caso simétrico: se borra Balanz (B) y el deshacer devuelve los títulos
        a Cocos con su costo, y el gasto a la caja."""
        self._historia()
        lotes_antes = self._sin_ids("Cocos")
        caja_antes = self.estado()["caja"]["Cocos"]
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, gasto=3000)
        r = self.http.delete(f"/api/brokers/{self._id_broker('Balanz')}", params={"force": "true"},
                             headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._uno(p["traspaso_id"])["estado"], "incompleto")
        self.assertEqual(self._deshacer_ok(p["traspaso_id"]),
                         "Listo: Balanz ya no existe, así que los 10 NVDA volvieron a Cocos.")
        self.assertEqual(self._sin_ids("Cocos"), lotes_antes)
        self.assertEqual(self.estado()["caja"]["Cocos"], caja_antes)
        m = self._mensual()
        self.assertAlmostEqual(m[("Cocos", 2025, 6)]["withdrawals"],
                               m[("global", 2025, 6)]["withdrawals"], places=4)
        self.assertAlmostEqual(m[("global", 2025, 6)]["pnl_realized"], 0.0, places=4)

    def test_la_cuenta_en_dolares_sola_no_se_borra_con_un_pase_vivo(self):
        """La «B · USD» que creó el pase, sola: su lado del pase es de la cuenta (la
        raíz), así que borrarla no lo revertiría. Frena (aun con `force`) hasta
        deshacer el pase; la cuenta entera sí se puede borrar (#22)."""
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        self._lote_a_mano("Cocos", "NVDA", 3, 15.0, "2025-01-20", moneda="USD")
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, moneda="USD",
                                       precio_manual=PRECIO_PASE))
        self.assertEqual(p["receta"]["brokers_usd_creados"], ["Balanz · USD"])
        r = self.http.delete(f"/api/brokers/{self._id_broker('Balanz · USD')}",
                             params={"force": "true"}, headers=self.h)
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (409, traspaso_a_mano.MSG_BORRAR_PATA_CON_PASE.format(nombre="Balanz · USD")))
        self.assertEqual([l[0] for l in self._sin_ids("Balanz · USD")], [3.0])
        self._deshacer_ok(p["traspaso_id"])
        r = self.http.delete(f"/api/brokers/{self._id_broker('Balanz · USD')}",
                             params={"force": "true"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def test_borrar_los_dos_y_deshacer(self):
        """Los dos brokers borrados: el pase queda «incompleto» sin ningún lado vivo y el
        deshacer sólo lo marca deshecho (no hay títulos que mover)."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        for b in ("Cocos", "Balanz"):
            r = self.http.delete(f"/api/brokers/{self._id_broker(b)}", params={"force": "true"},
                                 headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._uno(p["traspaso_id"])["estado"], "incompleto")
        self.assertEqual(self._deshacer_ok(p["traspaso_id"]),
                         "Listo: Cocos y Balanz ya no existen, así que no había títulos que "
                         "mover. El pase quedó deshecho.")
        self.assertEqual(self._traspasos()["traspasos"], [])

    def test_limpiar_broker_con_pase_vivo_frena(self):
        """#24: «Limpiar broker» (`POST /api/imports/wipe-broker`) frena en los dos lados
        y no toca nada."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        antes = self._tablas()
        for b in ("Cocos", "Balanz"):
            r = self.http.post("/api/imports/wipe-broker", params={"broker": b}, headers=self.h)
            self.assertEqual((r.status_code, r.json()["detail"]),
                             (409, traspaso_a_mano.MSG_LIMPIAR_CON_PASE))
        self.assertEqual(self._tablas(), antes)
        self._deshacer_ok(p["traspaso_id"])
        r = self.http.post("/api/imports/wipe-broker", params={"broker": "Balanz"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def test_renombrar_a_y_b_y_deshacer(self):
        """#25. Renombrar Cocos y Balanz (con la «Balanz · USD» que creó el pase): la
        receta queda con los nombres nuevos (también `brokers_usd_creados`), GET dice
        los nombres de hoy y el deshacer devuelve los títulos a la A renombrada."""
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        self._lote_a_mano("Cocos", "NVDA", 3, 15.0, "2025-01-20", moneda="USD")
        antes = self._sin_ids("Cocos · USD")
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, moneda="USD",
                                       precio_manual=PRECIO_PASE, gasto={"monto": 1, "moneda": "USD"}))
        for viejo, nuevo in (("Cocos", "Cocos Capital"), ("Balanz", "Balanz SA")):
            r = self.http.put(f"/api/brokers/{self._id_broker(viejo)}", headers=self.h,
                              json={"name": nuevo, "currency": "ARS"})
            self.assertEqual(r.status_code, 200, r.text)
        receta = self._pase_escrito(p["traspaso_id"])["receta"]
        self.assertEqual((receta["broker_origen"], receta["broker_destino"],
                          receta["brokers_usd_creados"], receta["gasto"]["broker"],
                          [(l["broker"], l["broker_destino"]) for l in receta["lotes"]]),
                         ("Cocos Capital", "Balanz SA", ["Balanz SA · USD"], "Cocos Capital · USD",
                          [("Cocos Capital · USD", "Balanz SA · USD")]))
        t = self._uno(p["traspaso_id"])
        self.assertEqual((t["broker_origen"], t["broker_destino"]), ("Cocos Capital", "Balanz SA"))
        self.assertEqual(self._deshacer_ok(p["traspaso_id"]),
                         "Listo: los 3 NVDA volvieron a Cocos Capital.")
        self.assertEqual(self._sin_ids("Cocos Capital · USD"), antes)
        self.assertEqual(self._sin_ids("Balanz SA · USD"), [])

    def test_put_con_otro_broker_bloqueado(self):
        """#26 (D.19): `PUT /api/positions/{id}` con otro broker da 409, para un lote
        importado y para uno cargado a mano; editarlo sin cambiar el broker sigue en 200."""
        self._historia()
        self._lote_a_mano("Cocos", "GGAL", 10, 1000, "2025-02-03")
        for lote in (self._lote("Cocos", "NVDA"), self._lote("Cocos", "GGAL")):
            body = {"broker": "Balanz", "asset": lote["asset"], "quantity": lote["quantity"],
                    "buy_price": lote["buy_price"], "invested": lote["invested"],
                    "commissions": lote["commissions"], "entry_date": lote["entry_date"][:10],
                    "currency": lote["currency"], "asset_type": lote["asset_type"]}
            r = self.http.put(f"/api/positions/{lote['id']}", json=body, headers=self.h)
            self.assertEqual((r.status_code, r.json()["detail"]),
                             (409, traspaso_a_mano.MSG_PUT_OTRO_BROKER))
            self.assertEqual(self._lote(None, lote["asset"], lote["entry_date"][:10])["broker"],
                             "Cocos")
        self._editar(self._lote("Cocos", "GGAL"), notes="corregido")


class VentaAManoAntesDeLaLlegada(_Deshacer):

    def test_venta_a_mano_no_consume_lo_que_llego_despues(self):
        """Hueco C4 de la revisión: en B, una venta a mano fechada ANTES de que llegaran
        los títulos del pase no los consume (no estaban). Si lo propio de B alcanza,
        consume eso; si no, 409 con la fecha. Después de la llegada, consume primero lo
        más viejo (lo que llegó), como siempre."""
        self._historia()
        self._importar("Balanz", ["2025-03-01,COMPRA,Balanz,NVDA,3,35000,105000,,,0,ARS,compra"])
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)

        def vender(q, fecha):
            return self.http.post("/api/positions/sell", headers=self.h, json={
                "broker": "Balanz", "asset": "NVDA", "quantity": q, "exit_price": 50000,
                "date": fecha, "currency": "ARS"})
        r = vender(5, "2025-05-01")
        self.assertEqual((r.status_code, r.json()["detail"]), (409,
                         "El 01/05/2025 todavía no tenías en Balanz todos estos NVDA: 10 llegaron "
                         "desde otro broker tuyo el 16/06/2025. Elegí una fecha del 16/06/2025 en "
                         "adelante o vendé hasta 3."))
        r = vender(2, "2025-05-01")
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual([(l[0], l[3]) for l in self._sin_ids("Balanz")],
                         [(10.0, "2025-01-10"), (1.0, "2025-03-01")])
        self.assertTrue(self._uno(p["traspaso_id"])["puede_deshacer"],
                        "la venta de antes de la llegada no tocó lo que llegó")
        r = vender(1, "2025-07-01")
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual([(l[0], l[3]) for l in self._sin_ids("Balanz")],
                         [(9.0, "2025-01-10"), (1.0, "2025-03-01")])


class AsesorGrupal(_Deshacer):

    def test_deshacer_grupal_del_asesor_saltea_el_lote_pasado(self):
        """D.10.6 (#20): la compra que un asesor cargó en grupo y el cliente pasó (en
        parte) a otro broker no se borra con el deshacer del grupo: queda salteada con
        el motivo y el lote del grupo sin deshacer. Deshecho el pase, el lote vuelve con
        su mismo id y el asesor puede reintentar."""
        conn = main.get_db()
        try:
            tag = uuid.uuid4().hex[:8]
            asesor = conn.execute("INSERT INTO users (email, password_hash, approved, tier) "
                                  "VALUES (?, 'x', 1, 'advisor')", (f"asesor-{tag}@rendi.test",)).lastrowid
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, "
                         "permission, status, label) VALUES (?,?,'managed','read_write','active','Yo')",
                         (asesor, self.uid))
            conn.commit()
        finally:
            conn.close()

        def limpiar():
            k = main.get_db()
            try:
                k.execute("DELETE FROM advisor_op_batch_items WHERE batch_id IN "
                          "(SELECT id FROM advisor_op_batches WHERE advisor_uid=?)", (asesor,))
                k.execute("DELETE FROM advisor_op_batches WHERE advisor_uid=?", (asesor,))
                k.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (asesor,))
                k.commit()
            finally:
                k.close()
        self.addCleanup(limpiar)
        ha = {"Authorization": f"Bearer {main.create_token(asesor)}"}
        self._historia()
        r = self.http.post("/api/advisor/group-op", headers=ha, json={
            "asset": "GGAL", "currency": "ARS", "entry_date": "2025-02-03",
            "rows": [{"client_uid": self.uid, "broker": "Cocos", "quantity": 10,
                      "buy_price": 1000}]})
        self.assertEqual(r.status_code, 200, r.text)
        lote_grupal = r.json()["batch_id"]
        self._esperar_reconstruccion()
        pid = self._lote("Cocos", "GGAL")["id"]
        p = self._fabricar_pase("GGAL", "Cocos", "Balanz", FECHA_PASE, 1500, cantidad=4)
        r = self.http.post(f"/api/advisor/group-op/{lote_grupal}/undo", headers=ha)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["undone"], r.json()["fully_undone"]), ([], False))
        self.assertEqual(r.json()["skipped"], [{"client_uid": self.uid,
                                                "reason": traspaso_a_mano.MOTIVO_ASESOR}])
        self.assertEqual(self._lote("Cocos", "GGAL")["quantity"], 6.0)
        self._deshacer_ok(p["traspaso_id"])
        self.assertEqual(self._lote("Cocos", "GGAL")["id"], pid)
        r = self.http.post(f"/api/advisor/group-op/{lote_grupal}/undo", headers=ha)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["fully_undone"])
        self.assertIsNone(self._lote("Cocos", "GGAL"))


class PaseQueCambia(_Deshacer):

    def test_la_regla_unica_de_lo_que_cambia_un_pase(self):
        """C.11, `pase_que_cambia`, sobre un pase real (Cocos → Balanz el 16/06, se mueve
        el lote comprado el 10/01). Lado A: una compra del día del pase o antes y no
        más nueva que lo movido, o una venta del día del pase o antes. Lado B: una venta
        anterior al pase. Lo demás no: compras de A posteriores o más nuevas que lo
        movido, ventas posteriores, compras de B, otro activo, las filas del propio pase
        y un pase excluido."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        tid = p["traspaso_id"]
        conn = main.get_db()
        try:
            def cambia(broker, op, fecha, fecha_compra=None, asset="NVDA", traspaso_id=None,
                       excluir=None):
                r = traspaso_a_mano.pase_que_cambia(
                    conn, self.uid, [{"broker": broker, "asset": asset, "op": op, "date": fecha,
                                      "fecha_compra": fecha_compra, "traspaso_id": traspaso_id}],
                    excluir=excluir)
                return (r["lado"], r["contraparte"]) if r else None
            self.assertEqual(cambia("Cocos", "BUY", "2025-01-09"), ("origen", "Balanz"))
            self.assertEqual(cambia("Cocos", "BUY", "2025-01-10"), ("origen", "Balanz"))
            self.assertIsNone(cambia("Cocos", "BUY", "2025-02-01"), "más nueva que lo movido")
            self.assertIsNone(cambia("Cocos", "BUY", "2025-07-01"), "posterior al pase")
            self.assertEqual(cambia("Cocos", "SELL", "2025-03-01"), ("origen", "Balanz"))
            self.assertEqual(cambia("Cocos", "SELL", FECHA_PASE), ("origen", "Balanz"))
            self.assertIsNone(cambia("Cocos", "SELL", "2025-06-17"))
            self.assertEqual(cambia("Balanz", "SELL", "2025-06-15"), ("destino", "Cocos"))
            self.assertIsNone(cambia("Balanz", "SELL", FECHA_PASE), "B: sólo ANTES del pase")
            self.assertIsNone(cambia("Balanz", "BUY", "2025-01-01"))
            self.assertIsNone(cambia("Cocos", "SELL", "2025-03-01", asset="AAPL"))
            self.assertIsNone(cambia("Cocos", "SELL", "2025-03-01", traspaso_id=tid))
            self.assertIsNone(cambia("Cocos", "SELL", "2025-03-01", excluir={tid}))
            self.assertIsNone(cambia("Cocos", "DEPOSIT", "2025-03-01"))
            r = traspaso_a_mano.pase_que_cambia(conn, self.uid, [{
                "broker": "Cocos", "asset": "NVDA", "op": "SELL", "date": "2025-03-01"}])
            self.assertEqual(r["mensaje"], traspaso_a_mano.MSG_CAMBIA_UN_PASE.format(
                asset="NVDA", broker="Cocos", fecha="16/06/2025", hacia="a", contraparte="Balanz"))
        finally:
            conn.close()
        self._deshacer_ok(tid)
        conn = main.get_db()
        try:
            self.assertIsNone(traspaso_a_mano.pase_que_cambia(conn, self.uid, [{
                "broker": "Cocos", "asset": "NVDA", "op": "SELL", "date": "2025-03-01"}]),
                "un pase deshecho no frena nada")
        finally:
            conn.close()


# ── E8: los imports que llegan DESPUÉS de un pase ───────────────────────────────
#
# Con los archivos de verdad de `test_traspaso_entre_brokers.py` (F.1): el libro de
# caja de Bull Market (compra de VIST y el gasto «GTOS. TRANS. TITULOS» del día en
# que salieron los títulos) y los movimientos de Balanz («Transferencia Externa
# (Crédito)» con su depósito compensatorio, «Boleto … COMPRA», «Transferencia
# Externa (Débito)»). Los mismos renglones, con fechas de 2025 (las del dólar
# sembrado) y 7 VIST en los dos lados (el archivo original trae 21 en Balanz por un
# cambio de ratio del CEDEAR que acá no se siembra).

BM_HDR = "F.Liquid;Cpbt;N.Cpbt;Importe;Dolares;Mda;Ref./Cantidad\n"
BZ_HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
          "Liquidacion,Moneda,Importe\n")
RECIBO = "Recibo de Cobro / 1,,,2025-06-02,0,-1,2025-06-02,Pesos,1000000"
FECHA_PASE_VIST = "2025-06-16"
PRECIO_VIST = 15000.0


def _bull_market(*gastos):
    """El libro de caja de Bull Market: $500.000 el 03/01, 7 VIST el 10/02 y el gasto
    del traspaso de títulos en cada fecha de `gastos` ('dd/mm/aa')."""
    filas = ["03/01/25;COBA;6668;-500000;;;CREDITO CTA. CTE.",
             "10/02/25;CPRA;1753959;67957,11;;;7.0000  VIST"]
    filas += [f"{g};DTRT;257047;1210;;;GTOS. TRANS. TITULOS" for g in gastos]
    return (BM_HDR + "".join(f + "\n" for f in filas)).encode("utf-8")


def _balanz(*filas):
    return (BZ_HDR + "".join(f + "\n" for f in filas)).encode("utf-8")


def _credito(fecha, q, precio=13492, asset="VIST"):
    return (f"Transferencia Externa (Crédito) / CEDEAR {asset},{asset},Cedears,{fecha},{q},"
            f"{precio},{fecha},,0")


def _debito(fecha, q, precio, asset="GLOB"):
    d = date.fromisoformat(fecha)
    return (f"Transferencia Externa (Débito) / {d.day}/{d.month}/{d.year},{asset},Cedears,"
            f"{fecha},-{q},{precio},{fecha},,0")


def _boleto(fecha, q, precio, asset="GLOB"):
    return (f"Boleto / 100 / COMPRA ,{asset},Cedears,{fecha},{q},{precio},{fecha},Pesos,"
            f"-{q * precio}")


class _Archivos(_Deshacer):
    """Lo que necesitan las pruebas de E8: subir un archivo de verdad por las puertas
    de producción (`POST /api/imports/preview` + `/confirm`) y mirar qué quedó."""

    def _subir(self, broker, data, fmt):
        r = self.http.post("/api/imports/preview",
                           files=[("files", ("movimientos.csv", io.BytesIO(data), "text/csv"))],
                           data={"format": fmt, "broker": broker}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _confirmar_archivo(self, prev, aprobar=(), include_duplicates=False):
        r = self.http.post("/api/imports/confirm", json={
            "session_id": prev["session_id"], "skip_row_indices": [],
            "aprobar_tickers": list(aprobar), "include_duplicates": include_duplicates},
            headers=self.h)
        self._esperar_reconstruccion()
        return r

    def _importar_archivo(self, broker, data, fmt, aprobar=()):
        prev = self._subir(broker, data, fmt)
        r = self._confirmar_archivo(prev, aprobar)
        self.assertEqual(r.status_code, 200, r.text)
        return prev, r.json()

    def _no_entra(self, prev, texto, aprobar=()):
        """El confirm frena con `texto` (409) y no escribe NADA: cada fila de la cuenta
        queda como estaba con la vista previa hecha."""
        antes = self._tablas()
        r = self._confirmar_archivo(prev, aprobar)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], texto)
        self.assertEqual(self._tablas(), antes, "el confirm que frena escribió algo")

    def _cantidad(self, broker, asset):
        return round(sum(l["quantity"] for l in self._lotes(broker, asset)), 6)

    def _aportado(self, broker="global"):
        conn = main.get_db()
        try:
            return snapshots_job.compute_net_deposited_db(
                conn, self.uid, broker_filter=broker, include_baseline=(broker == "global"))
        finally:
            conn.close()

    def _omitidas(self, tid):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT omitidas_json FROM traspasos_a_mano WHERE id=? AND user_id=?",
                             (tid, self.uid)).fetchone()
            return json.loads(r["omitidas_json"] or "[]")
        finally:
            conn.close()

    def _filas_del_lote(self, sid):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT n.operation_type, n.asset_symbol, n.quantity, n.notes, r.row_index "
                "FROM import_normalized_tx n JOIN import_raw_rows r ON r.id = n.raw_row_id "
                "WHERE n.batch_id=? ORDER BY r.row_index", (sid,)).fetchall()]
        finally:
            conn.close()

    def _indice(self, prev, op, asset=None):
        """El row_index de la fila de la vista previa (la primera de ese tipo)."""
        for f in prev["rows_preview"]:
            if f["operation_type"] == op and (asset is None or f["asset_symbol"] == asset):
                return f["row_index"]
        self.fail(f"no hay {op} en la vista previa")

    def _ventas(self):
        conn = main.get_db()
        try:
            return conn.execute("SELECT COUNT(*) c FROM operations WHERE user_id=? "
                                "AND op_type='Venta'", (self.uid,)).fetchone()["c"]
        finally:
            conn.close()

    # El escenario de Agustín, con el pase hecho a mano: VIST de Bull Market a Balanz.
    def _bull_market_y_pase(self, cantidad=4, gastos=("18/06/25",)):
        self._broker("Bull Market")
        self._importar_archivo("Bull Market", _bull_market(*gastos), "bullmarket")
        return self._fabricar_pase("VIST", "Bull Market", "Balanz", FECHA_PASE_VIST, PRECIO_VIST,
                                   cantidad=cantidad)

    # A = Balanz con 10 GLOB importados (y, si se pide, 5 más cargados a mano).
    def _balanz_y_pase_de_glob(self, a_mano=False):
        historia = [RECIBO.replace("2025-06-02", "2025-01-02").replace("1000000", "2000000"),
                    _boleto("2025-01-10", 10, 10000)]
        self._importar_archivo("Balanz", _balanz(*historia), "balanz_movimientos")
        if a_mano:
            self._lote_a_mano("Balanz", "GLOB", 5, 11000, "2025-02-01", asset_type="CEDEAR")
        p = self._fabricar_pase("GLOB", "Balanz", "Cocos", FECHA_PASE_VIST, 40000.0)
        return historia, p


class ImportDeBDespuesDelPase(_Archivos):

    def test_import_de_b_despues_del_pase_no_duplica(self):
        """#15. Pase de 4 VIST de Bull Market a Balanz el 16/06; después se importa el
        archivo de Balanz, que trae esa misma llegada («Transferencia Externa
        (Crédito)», el 18/06, con su depósito compensatorio) y un cobro de verdad. La
        llegada y su depósito no entran (la vista previa los lista en
        `ya_traspasados` y entre los que se omiten): Balanz sigue con los 4 VIST del
        pase y el aportado global sube sólo el cobro. Lo omitido queda anotado en el
        pase. Y el cruce automático (D.6) no propone cerrar en Bull Market los 3 VIST
        que quedaron allá: la llegada ya es del pase."""
        p = self._bull_market_y_pase(cantidad=4)
        tid = p["traspaso_id"]
        self.assertEqual((self._cantidad("Bull Market", "VIST"), self._cantidad("Balanz", "VIST")),
                         (3.0, 4.0))
        aportado = self._aportado()
        archivo = _balanz(RECIBO, _credito("2025-06-18", 4))
        prev = self._subir("Balanz", archivo, "balanz_movimientos")
        compra, deposito = self._indice(prev, "BUY", "VIST"), None
        for f in prev["rows_preview"]:
            if f["operation_type"] == "DEPOSIT" and "entrada de título" in (f["notes"] or ""):
                deposito = f["row_index"]
        self.assertIsNotNone(deposito, "el lector de Balanz emite el depósito compensatorio")
        self.assertEqual(prev["ya_traspasados"], [
            {"fecha": "2025-06-18", "activo": "VIST", "cantidad": 4.0, "broker": "Balanz",
             "lado": "entrada"}])
        self.assertEqual(sorted(prev["duplicate_row_indices"]), sorted([compra, deposito]))
        self.assertIsNone(prev["cambian_un_pase"])
        self.assertEqual(prev["avisos_de_pases"], [])
        self.assertEqual(prev["traspasos"], [], "D.6: el cruce automático no cierra lo del pase")
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["omitidas_por_pases"], r.json()["auto_skipped_duplicates"]),
                         (2, 0))
        self.assertEqual((self._cantidad("Bull Market", "VIST"), self._cantidad("Balanz", "VIST")),
                         (3.0, 4.0))
        self.assertAlmostEqual(self._aportado(), aportado + 1000000 / dolar("2025-06-02"),
                               delta=0.01)
        quedaron = self._filas_del_lote(prev["session_id"])
        self.assertEqual([f["operation_type"] for f in quedaron], ["DEPOSIT"],
                         "en el registro queda sólo el cobro")
        self.assertEqual(sorted((o["row_index"], o["lado"], o["batch_id"]) for o in self._omitidas(tid)),
                         sorted([(compra, "entrada", prev["session_id"]),
                                 (deposito, "entrada", prev["session_id"])]))
        # Después del rebuild real (F.1): todo igual.
        self._rebuild()
        self.assertEqual((self._cantidad("Bull Market", "VIST"), self._cantidad("Balanz", "VIST")),
                         (3.0, 4.0))

    def test_tambien_por_el_confirm_directo_y_forzando_los_repetidos(self):
        """#15, las otras dos puertas: el confirm llamado desde adentro
        (`main.import_confirm(...)`, como la tanda del asesor) y con los repetidos
        FORZADOS (`include_duplicates=True`). Se sube dos veces el mismo archivo de
        Balanz: la segunda vez, forzando, el cobro entra de nuevo (es lo que pide
        quien fuerza) pero la llegada del pase no: forzar los repetidos no fuerza que
        los títulos del pase se cuenten dos veces. Cada lote queda anotado."""
        p = self._bull_market_y_pase(cantidad=7, gastos=())
        tid = p["traspaso_id"]
        archivo = _balanz(RECIBO, _credito("2025-06-17", 7))
        prev1 = self._subir("Balanz", archivo, "balanz_movimientos")
        out = main.import_confirm(main.ImportConfirmIn(
            session_id=prev1["session_id"], skip_row_indices=[], aprobar_tickers=[]), self.uid)
        self._esperar_reconstruccion()
        self.assertEqual(out["omitidas_por_pases"], 2)
        aportado = self._aportado()
        prev2 = self._subir("Balanz", archivo, "balanz_movimientos")
        out = main.import_confirm(main.ImportConfirmIn(
            session_id=prev2["session_id"], skip_row_indices=[], aprobar_tickers=[],
            include_duplicates=True), self.uid)
        self._esperar_reconstruccion()
        self.assertEqual((out["omitidas_por_pases"], out["auto_skipped_duplicates"]), (2, 0))
        self.assertEqual(self._cantidad("Balanz", "VIST"), 7.0)
        self.assertEqual(self._cantidad("Bull Market", "VIST"), 0.0)
        self.assertAlmostEqual(self._aportado(), aportado + 1000000 / dolar("2025-06-02"),
                               delta=0.01, msg="forzando, el cobro repetido sí entra")
        self.assertEqual({o["batch_id"] for o in self._omitidas(tid)},
                         {prev1["session_id"], prev2["session_id"]})

    def test_omitidas_frenan_el_deshacer(self):
        """#44. Después de #15, deshacer el pase frena: el archivo de Balanz no cargó la
        llegada porque ya estaba el pase, y sin él esos títulos quedarían sin
        registrar. Revertido ese archivo, el deshacer anda; vuelto a subir, la llegada
        entra (ya no hay pase). La lista de Importaciones muestra los dos lotes del
        pase como el pase (D.2.6), con su lado y cómo está."""
        p = self._bull_market_y_pase(cantidad=4)
        tid = p["traspaso_id"]
        archivo = _balanz(RECIBO, _credito("2025-06-18", 4))
        prev, _ = self._importar_archivo("Balanz", archivo, "balanz_movimientos")
        lista = self._get("/api/imports").json()
        pases = {(b["broker"], b["traspaso"]["lado"], b["traspaso"]["contraparte"],
                  b["traspaso"]["estado"], b["traspaso"]["id"], b["traspaso"]["asset"],
                  b["traspaso"]["cantidad"]) for b in lista if b.get("traspaso")}
        self.assertEqual(pases, {("Bull Market", "salida", "Balanz", "vivo", tid, "VIST", 4.0),
                                 ("Balanz", "entrada", "Bull Market", "vivo", tid, "VIST", 4.0)})
        self.assertTrue(all("traspaso" not in b for b in lista
                            if b["parser_format"] != traspaso_a_mano.FORMATO))
        conn = main.get_db()
        try:
            cuando = conn.execute("SELECT COALESCE(confirmed_at, created_at) AS c FROM import_batches "
                                  "WHERE id=?", (prev["session_id"],)).fetchone()["c"]
        finally:
            conn.close()
        fecha = _ddmmaaaa(str(cuando)[:10])
        texto = (f"Cuando importaste el archivo de Balanz del {fecha}, Rendi no cargó la llegada "
                 "de VIST porque ya estaba este pase. Si lo deshacés, esos títulos quedarían sin "
                 f"registrar. Primero revertí ese archivo (Importaciones → el archivo del {fecha} → "
                 "Revertir), después deshacé el pase y volvé a subir el archivo.")
        self._no_deshace(tid, 409, texto)
        self.assertEqual(self._uno(tid)["motivo"], texto)
        r = self.http.post(f"/api/imports/{prev['session_id']}/revert", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._deshacer_ok(tid)
        lista = self._get("/api/imports").json()
        self.assertEqual({b["traspaso"]["estado"] for b in lista if b.get("traspaso")},
                         {"deshecho"})
        self.assertEqual((self._cantidad("Bull Market", "VIST"), self._cantidad("Balanz", "VIST")),
                         (7.0, 0.0))
        prev, _ = self._importar_archivo("Balanz", archivo, "balanz_movimientos")
        self.assertEqual(prev["ya_traspasados"], [])
        self.assertEqual(self._cantidad("Balanz", "VIST"), 4.0, "sin pase, la llegada entra")

    def test_import_de_b_con_otra_fecha_frena(self):
        """#16. El mismo archivo con la llegada a 20 días del pase: puede ser la misma
        con la fecha del pase mal anotada, así que el import frena (409) con la fecha
        que hay que ponerle al pase; la vista previa lo anticipa (`cambian_un_pase`).
        A 90 días es otro movimiento: entra, con un aviso."""
        p = self._bull_market_y_pase(cantidad=4, gastos=())
        prev = self._subir("Balanz", _balanz(_credito("2025-07-06", 4)), "balanz_movimientos")
        texto = ("El archivo de Balanz dice que los VIST llegaron el 06/07 y el pase lo anotaste "
                 "el 16/06. Para no contarlos dos veces, deshacé el pase y hacelo de nuevo con "
                 "fecha 06/07; después importá el archivo.")
        self.assertEqual(prev["cambian_un_pase"]["mensaje"], texto)
        self.assertEqual(prev["ya_traspasados"], [])
        self._no_entra(prev, texto)
        prev = self._subir("Balanz", _balanz(_credito("2025-09-14", 4)), "balanz_movimientos")
        self.assertIsNone(prev["cambian_un_pase"])
        self.assertEqual(prev["avisos_de_pases"], [
            "Ojo: este archivo trae una llegada de 4 VIST a Balanz el 14/09, lejos de tu pase "
            "desde Bull Market del 16/06: la cargamos como otra llegada. Si es la misma, deshacé "
            "el pase antes de importar el archivo."])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._cantidad("Balanz", "VIST"), 8.0)
        self.assertEqual(self._omitidas(p["traspaso_id"]), [])

    def test_dos_pases_cada_llegada_con_el_suyo(self):
        """Dos pases del mismo activo (2 VIST el 16/06 y 2 el 01/08) y un archivo de
        Balanz con las dos llegadas, la de agosto primero. Cada llegada se compara con
        el pase más cercano en fecha que la pueda explicar: las dos se omiten, cada una
        anotada en su pase (con el primero de la lista, la de agosto quedaría a 47
        días del pase de junio y frenaría el archivo)."""
        p1 = self._bull_market_y_pase(cantidad=2, gastos=())
        p2 = self._fabricar_pase("VIST", "Bull Market", "Balanz", "2025-08-01", PRECIO_VIST,
                                 cantidad=2)
        prev = self._subir("Balanz", _balanz(_credito("2025-08-02", 2), _credito("2025-06-17", 2)),
                           "balanz_movimientos")
        self.assertIsNone(prev["cambian_un_pase"])
        self.assertEqual(sorted(d["fecha"] for d in prev["ya_traspasados"]),
                         ["2025-06-17", "2025-08-02"])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        agosto, junio = (f["row_index"] for f in prev["rows_preview"]
                         if f["operation_type"] == "BUY")
        self.assertEqual([o["row_index"] for o in self._omitidas(p1["traspaso_id"])
                          if o["row_index"] in (agosto, junio)], [junio])
        self.assertEqual([o["row_index"] for o in self._omitidas(p2["traspaso_id"])
                          if o["row_index"] in (agosto, junio)], [agosto])
        self.assertEqual(self._cantidad("Balanz", "VIST"), 4.0)

    def test_mas_titulos_de_los_que_paso_entran_con_un_aviso(self):
        """Ante la duda se omite de menos (D.7): una llegada cerca del pase pero con
        más títulos de los que el pase llevó a esa cuenta no se omite (no es seguro
        que sea la misma: puede venir de un tercero, o de un cambio de ratio). Entra,
        con un aviso que dice qué hacer si incluye los del pase."""
        self._bull_market_y_pase(cantidad=4, gastos=())
        prev = self._subir("Balanz", _balanz(_credito("2025-06-17", 6)), "balanz_movimientos")
        self.assertEqual(prev["ya_traspasados"], [])
        self.assertIsNone(prev["cambian_un_pase"])
        self.assertEqual(prev["avisos_de_pases"], [
            "Ojo: este archivo trae una llegada de 6 VIST a Balanz el 17/06, cerca de tu pase "
            "desde Bull Market del 16/06, pero son más de los 4 que pasaste: la cargamos. Si "
            "incluye los del pase, deshacé el pase antes de importar el archivo."])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._cantidad("Balanz", "VIST"), 10.0)


class ImportDeADespuesDelPase(_Archivos):

    def test_import_de_a_despues_del_pase_no_duplica_la_salida(self):
        """#17. A = Balanz (10 GLOB importados); pase de todo a Cocos el 16/06. Después
        se importa el export completo de Balanz: los renglones de antes (repetidos por
        huella) y la salida («Transferencia Externa (Débito)», el 18/06). El Débito ya
        es del pase: se omite (sin lote semilla ni una 'Venta' de más), y como la
        compra del 10/01 se repite por huella, la regla única no frena nada."""
        historia, p = self._balanz_y_pase_de_glob()
        ventas = self._ventas()
        prev = self._subir("Balanz", _balanz(*historia, _debito("2025-06-18", 10, 40000)),
                           "balanz_movimientos")
        debito = self._indice(prev, "SELL", "GLOB")
        self.assertEqual(prev["ya_traspasados"], [
            {"fecha": "2025-06-18", "activo": "GLOB", "cantidad": 10.0, "broker": "Balanz",
             "lado": "salida"}])
        self.assertIn(debito, prev["duplicate_row_indices"])
        self.assertEqual(len(prev["duplicate_row_indices"]), 3)
        self.assertIsNone(prev["cambian_un_pase"])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["omitidas_por_pases"], r.json()["auto_skipped_duplicates"]),
                         (1, 2))
        self.assertEqual(self._lotes("Balanz", "GLOB"), [], "sin lote semilla en A")
        self.assertEqual(self._cantidad("Cocos", "GLOB"), 10.0)
        self.assertEqual(self._ventas(), ventas, "sin una 'Venta' de más")
        self.assertEqual(self._omitidas(p["traspaso_id"]),
                         [{"batch_id": prev["session_id"], "row_index": debito, "lado": "salida"}])
        self._rebuild()
        self.assertEqual(self._lotes("Balanz", "GLOB"), [])
        self.assertEqual(self._cantidad("Cocos", "GLOB"), 10.0)
        self.assertEqual(self._ventas(), ventas)

    def test_el_debito_de_antes_o_del_mismo_dia_tambien_se_omite(self):
        """El orden de las reglas. (1) Un Débito DOS DÍAS ANTES del pase es una venta
        de A anterior al pase, que la regla única frenaría (D.10.16); pero es la salida
        del pase y el antiduplicado la omite antes: la regla mira lo que queda. (2) Un
        Débito del MISMO DÍA tiene la huella de la salida del pase (venta a precio 0 en
        A ese día): igual cuenta como omitido POR EL PASE —en la lista de la vista
        previa y anotado en el pase—, así deshacerlo no lo deja sin registrar."""
        historia, p = self._balanz_y_pase_de_glob()
        prev = self._subir("Balanz", _balanz(_debito("2025-06-14", 10, 40000)),
                           "balanz_movimientos")
        self.assertEqual([d["fecha"] for d in prev["ya_traspasados"]], ["2025-06-14"])
        self.assertIsNone(prev["cambian_un_pase"])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._lotes("Balanz", "GLOB"), [])
        prev2 = self._subir("Balanz", _balanz(_debito(FECHA_PASE_VIST, 10, 40000)),
                            "balanz_movimientos")
        self.assertEqual([d["fecha"] for d in prev2["ya_traspasados"]], [FECHA_PASE_VIST])
        r = self._confirmar_archivo(prev2)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["omitidas_por_pases"], r.json()["auto_skipped_duplicates"]),
                         (1, 0))
        self.assertEqual({o["batch_id"] for o in self._omitidas(p["traspaso_id"])},
                         {prev["session_id"], prev2["session_id"]})
        self.assertEqual(self._lotes("Balanz", "GLOB"), [])
        self.assertEqual(self._cantidad("Cocos", "GLOB"), 10.0)

    def test_debito_con_otra_fecha_frena_con_la_fecha(self):
        """#16, el espejo del lado de A: un Débito 20 días ANTES del pase. También es una
        venta de A anterior al pase (la regla única la frenaría con su texto general),
        pero lo más probable es que sea la salida del pase con la fecha mal anotada:
        manda el texto que dice qué fecha ponerle al pase."""
        historia, p = self._balanz_y_pase_de_glob()
        prev = self._subir("Balanz", _balanz(_debito("2025-05-27", 10, 40000)),
                           "balanz_movimientos")
        texto = ("El archivo de Balanz dice que los GLOB salieron el 27/05 y el pase lo anotaste "
                 "el 16/06. Para no contarlos dos veces, deshacé el pase y hacelo de nuevo con "
                 "fecha 27/05; después importá el archivo.")
        self.assertEqual(prev["cambian_un_pase"]["mensaje"], texto)
        self._no_entra(prev, texto)

    def test_salida_con_lotes_cargados_a_mano_frena_por_su_compra(self):
        """#17, la segunda mitad. El pase se llevó 10 GLOB importados y 5 cargados a
        mano; después el archivo de Balanz trae la compra de esos 5 (01/02) y un Débito
        de 15. El Débito no se omite (es más de lo que salió de los archivos: entra con
        un aviso) y la compra cambiaría la historia de A antes del pase: el import
        entero frena con `MSG_IMPORT_CAMBIA_UN_PASE` (la vista previa lo anticipa)."""
        historia, p = self._balanz_y_pase_de_glob(a_mano=True)
        self.assertEqual(self._cantidad("Cocos", "GLOB"), 15.0)
        prev = self._subir("Balanz", _balanz(*historia, _boleto("2025-02-01", 5, 11000),
                                             _debito("2025-06-18", 15, 40000)),
                           "balanz_movimientos")
        texto = ("Este archivo trae compras de GLOB en Balanz del 01/02/2025, anteriores a tu pase "
                 "del 16/06/2025 a Cocos. Si lo confirmamos, el pase quedaría con otros lotes. "
                 "Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), importá el archivo "
                 "y volvé a moverlos.")
        self.assertEqual(prev["ya_traspasados"], [])
        self.assertEqual(prev["cambian_un_pase"]["mensaje"], texto)
        self.assertEqual(prev["avisos_de_pases"], [
            "Ojo: este archivo trae una salida de 15 GLOB de Balanz el 18/06, cerca de tu pase a "
            "Cocos del 16/06, pero son más de los 10 que salieron de tus archivos: la cargamos. "
            "Si incluye los del pase, deshacé el pase antes de importar el archivo."])
        self._no_entra(prev, texto)


class ImportDeBAntesDelPase(_Archivos):

    def test_import_de_b_antes_del_pase_frena_con_instrucciones(self):
        """#18. El orden inverso: primero se importó el archivo de Balanz con la llegada
        (y su depósito) y después se quiere mover a mano desde Bull Market → el pase
        frena (#13) con las instrucciones. Hechas (borrar la «Compra» y el «Depósito»
        por Movimientos), el pase anda y no se cuenta nada dos veces: Balanz queda con
        los títulos del pase, al costo de Bull Market, y el aportado global con el
        cobro y nada más."""
        self._broker("Bull Market")
        self._importar_archivo("Bull Market", _bull_market(), "bullmarket")
        aportado = self._aportado()
        prev, _ = self._importar_archivo("Balanz", _balanz(RECIBO, _credito("2025-06-14", 4)),
                                         "balanz_movimientos")
        self.assertEqual(self._cantidad("Balanz", "VIST"), 4.0)
        body = self._pedido("VIST", "Bull Market", "Balanz", FECHA_PASE_VIST,
                            precio_manual=PRECIO_VIST, cantidad=4)
        r = self._vista(body)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertTrue(r.json()["detail"].startswith(
            "Balanz ya tiene registrada la llegada de 4 VIST el 14/06"), r.text)
        conn = main.get_db()
        try:
            filas = {r["operation_type"]: r["id"] for r in conn.execute(
                "SELECT id, operation_type FROM import_normalized_tx WHERE batch_id=? "
                "AND operation_type IN ('BUY', 'DEPOSIT') AND (asset_symbol='VIST' OR "
                "notes LIKE '%entrada de título%')", (prev["session_id"],)).fetchall()}
        finally:
            conn.close()
        for op in ("BUY", "DEPOSIT"):
            r = self.http.delete(f"/api/movements/tx-{filas[op]}", headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
            self._esperar_reconstruccion()
        p = self._aplicar(body)
        self.assertEqual(self._cantidad("Balanz", "VIST"), 4.0, "sin doble conteo")
        self.assertEqual(self._cantidad("Bull Market", "VIST"), 3.0)
        lote = self._lotes("Balanz", "VIST")[0]
        self.assertEqual((lote["ed"], lote["desde"]), ("2025-02-10", FECHA_PASE_VIST))
        self.assertAlmostEqual(lote["invested"], 67957.11 * 4 / 7, places=4)
        self.assertAlmostEqual(self._aportado(), aportado + 1000000 / dolar("2025-06-02"),
                               delta=0.01)
        self.assertTrue(p["traspaso_id"])


class TraspasoAutomaticoYaCerrado(_Archivos):

    def test_traspaso_automatico_ya_cerrado_frena(self):
        """#19. El cruce automático de verdad: Bull Market (con el gasto del traspaso el
        18/06) y después Balanz con la llegada de los 7 VIST ese día, aprobando el
        cierre. Rendi ya los pasó: mover los mismos VIST a mano frena (#12)."""
        self._broker("Bull Market")
        self._importar_archivo("Bull Market", _bull_market("18/06/25"), "bullmarket")
        prev, _ = self._importar_archivo("Balanz", _balanz(RECIBO, _credito("2025-06-18", 7)),
                                         "balanz_movimientos", aprobar=["VIST"])
        self.assertEqual([t["activo"] for t in prev["traspasos"]], ["VIST"])
        self.assertEqual((self._cantidad("Bull Market", "VIST"), self._cantidad("Balanz", "VIST")),
                         (0.0, 7.0))
        body = self._pedido("VIST", "Bull Market", "Balanz", FECHA_PASE_VIST,
                            precio_manual=PRECIO_VIST)
        self._no_puede(body, 409, "Rendi ya pasó estos VIST de Bull Market a Balanz el 18/06, "
                                  "cuando importaste el archivo de Balanz. No hace falta moverlos "
                                  "otra vez.")


class CambiosAnterioresAlPaseEnElImportador(_Archivos):

    def test_cambios_anteriores_al_pase_frenan(self):
        """#21, las puertas del importador (las de borrar y deshacer un borrado son de
        E7: `test_cambios_anteriores_al_pase_frenan_en_las_puertas_de_borrado`). Pase
        de los 10 NVDA de Cocos (comprados el 10/01) a Balanz el 16/06. Un archivo de
        Cocos con una compra más vieja (05/01) frena; uno de Balanz con una venta
        anterior al pase (10/06) frena; uno de Cocos con una compra posterior entra."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)

        def subir(broker, fila):
            csv_txt = (HDR + fila + "\n").encode()
            return self._subir(broker, csv_txt, "rendi_generic")

        prev = subir("Cocos", "2025-01-05,COMPRA,Cocos,NVDA,1,29000,29000,,,0,ARS,compra vieja")
        texto = ("Este archivo trae compras de NVDA en Cocos del 05/01/2025, anteriores a tu pase "
                 "del 16/06/2025 a Balanz. Si lo confirmamos, el pase quedaría con otros lotes. "
                 "Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), importá el archivo y "
                 "volvé a moverlos.")
        self.assertEqual(prev["cambian_un_pase"]["mensaje"], texto)
        self._no_entra(prev, texto)
        prev = subir("Balanz", "2025-06-10,VENTA,Balanz,NVDA,1,44000,44000,,,0,ARS,venta vieja")
        texto = ("Este archivo trae ventas de NVDA en Balanz del 10/06/2025, anteriores a tu pase "
                 "del 16/06/2025 desde Cocos. Si lo confirmamos, el pase quedaría con otros lotes. "
                 "Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), importá el archivo y "
                 "volvé a moverlos.")
        self.assertEqual(prev["cambian_un_pase"]["mensaje"], texto)
        self._no_entra(prev, texto)
        prev = subir("Cocos", "2025-07-01,COMPRA,Cocos,NVDA,2,46000,92000,,,0,ARS,compra nueva")
        self.assertIsNone(prev["cambian_un_pase"])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._cantidad("Cocos", "NVDA"), 2.0)
        self.assertEqual(self._cantidad("Balanz", "NVDA"), 10.0)
        # Deshecho el pase, la compra vieja entra.
        self._deshacer_ok(p["traspaso_id"])
        prev = subir("Cocos", "2025-01-05,COMPRA,Cocos,NVDA,1,29000,29000,,,0,ARS,compra vieja")
        self.assertIsNone(prev["cambian_un_pase"])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)

    def test_un_cierre_propuesto_sin_aprobar_no_frena_la_vista_previa(self):
        """La vista previa mira lo que entraría POR DEFECTO: el cierre que propone el
        cruce automático (requiere aprobación) no entra si nadie lo aprueba, así que no
        bloquea el archivo. Si la persona lo aprueba, el confirm mira lo que de verdad
        entra y frena: ese cierre es una venta en Bull Market anterior al pase.
        (Bull Market se quedó con 3 VIST; el archivo de Balanz trae otra llegada, del
        01/03, con el gasto del traspaso de Bull Market ese mismo día.)"""
        self._bull_market_y_pase(cantidad=4, gastos=("01/03/25",))
        prev = self._subir("Balanz", _balanz(_credito("2025-03-01", 3)), "balanz_movimientos")
        self.assertEqual([(t["activo"], t["cantidad"]) for t in prev["traspasos"]], [("VIST", 3.0)])
        self.assertIsNone(prev["cambian_un_pase"])
        self._no_entra(prev, (
            "Este archivo trae ventas de VIST en Bull Market del 01/03/2025, anteriores a tu pase "
            "del 16/06/2025 a Balanz. Si lo confirmamos, el pase quedaría con otros lotes. "
            "Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), importá el archivo y "
            "volvé a moverlos."), aprobar=["VIST"])
        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((self._cantidad("Bull Market", "VIST"), self._cantidad("Balanz", "VIST")),
                         (3.0, 7.0))


class SinPasesNadaCambia(_Archivos):

    def test_sin_pases_la_vista_previa_no_trae_nada_del_pase(self):
        """Quien no hizo ningún pase importa como siempre: `ya_traspasados` vacío,
        `cambian_un_pase` nulo (la pantalla bloquea el confirmar con cualquier valor
        verdadero: una lista vacía también lo es) y la lista de Importaciones sin
        `traspaso`."""
        self._broker("Bull Market")
        prev, out = self._importar_archivo("Bull Market", _bull_market(), "bullmarket")
        self.assertEqual((prev["ya_traspasados"], prev["cambian_un_pase"], prev["avisos_de_pases"]),
                         ([], None, []))
        self.assertEqual(out["omitidas_por_pases"], 0)
        self.assertTrue(all("traspaso" not in b for b in self._get("/api/imports").json()))


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



# ── E9: Movimientos, el CSV de transacciones y las comisiones (D.9) ─────────────

class _Movimientos(_Deshacer):
    """Lo que necesitan las pruebas de E9: Movimientos (`GET /api/movements`), el CSV
    para el contador (`GET /api/export/transactions.csv`) y el total de comisiones
    (`GET /api/insights/commissions`), por HTTP como los pide la pantalla.

    La cuenta: la historia de siempre (Cocos importó 10 NVDA el 10/01 a $30.000 con
    $1.500 de comisión) y un lote de NVDA CARGADO A MANO en Cocos, más viejo (2 del
    02/01 a $28.000 con $280 de comisión): el pase lo saca de `positions`, así que su
    compra original tiene que seguir en Movimientos (D.9.2)."""

    def _escenario(self):
        self._historia()
        return self._lote_a_mano("Cocos", "NVDA", 2, 28000, "2025-01-02", commissions=280)

    def _movs(self):
        return self._get("/api/movements").json()

    def _csv(self):
        return list(csv.DictReader(io.StringIO(self._get("/api/export/transactions.csv").text)))

    def _comisiones(self):
        return self._get("/api/insights/commissions").json()

    @staticmethod
    def _como_se_ve(m):
        """Una fila de Movimientos como la ve la persona, sin ids."""
        return (m["type"], str(m["date"] or "")[:10], m["broker"], m["asset"] or "",
                round(float(m["amount_usd"] or 0), 6), round(float(m["fees_usd"] or 0), 6),
                round(float(m["quantity"] or 0), 6))

    @staticmethod
    def _partes(movs):
        """(las dos patas, el gasto del trámite, las compras originales de lotes
        cargados a mano que se pasaron, el resto)."""
        patas = [m for m in movs if m["type"] in (OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA)]
        gasto = [m for m in movs if m["type"] == OP_FEE and m.get("traspaso_id")]
        pasadas = [m for m in movs if str(m["id"]).startswith("trp-")]
        resto = [m for m in movs if m not in patas and m not in gasto and m not in pasadas]
        return patas, gasto, pasadas, resto

    @staticmethod
    def _total_como_la_pantalla(movs):
        """El total de comisiones como lo suma la pantalla (`commTotalUsd`,
        Operations.jsx): las FEE sueltas más la comisión de cada fila que no es FEE
        ni IMPUESTO."""
        return (sum(float(m["amount_usd"] or 0) for m in movs if m["type"] == "FEE")
                + sum(float(m["fees_usd"] or 0) for m in movs
                      if m["type"] not in ("FEE", "IMPUESTO")))


class MovimientosDelPase(_Movimientos):

    def test_movimientos_muestran_las_patas_y_no_las_compras_internas(self):
        """#6 (Movimientos, D.9.1 y D.9.2). Después del pase (todo, con un gasto de
        $5.000), Movimientos muestra las dos patas —«Pase (salió)» en Cocos y «Pase
        (entró)» en Balanz, con lo que valían ese día, el cociente exacto de sus pesos,
        `traspaso_id`, `contraparte` y `estado`— y el gasto, y NADA más cambia: sin la
        venta a precio 0 de Cocos ni las compras de llegada en Balanz, y con la compra
        original del lote cargado a mano (ahora `trp-…`, la misma fila que antes era
        `pos-…`). La compra pasada no se borra suelta (409 con el camino para deshacer
        el pase) y el rebuild real no cambia nada."""
        lote = self._escenario()
        antes = self._movs()
        self.assertEqual(sorted(str(m["id"]).split("-")[0] for m in antes if m["asset"] == "NVDA"),
                         ["pos", "tx"], "control: la compra importada y la cargada a mano")
        com_antes = self._comisiones()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, gasto=5000)
        tid = p["traspaso_id"]
        despues = self._movs()
        patas, gasto, pasadas, resto = self._partes(despues)

        # Nada inventado y nada perdido: sin las filas del pase, lo de antes.
        self.assertEqual(sorted(map(self._como_se_ve, resto + pasadas)),
                         sorted(map(self._como_se_ve, antes)))
        self.assertEqual([m for m in despues if m["type"] in ("BUY", "SELL")
                          and str(m["date"])[:10] == FECHA_PASE], [],
                         "una compra o una venta interna del pase llegó a Movimientos")

        # Las dos patas.
        self.assertEqual(sorted((m["type"], m["broker"], m["contraparte"], m["estado"]) for m in patas),
                         [(OP_TRASPASO_ENTRADA, "Balanz", "Cocos", "vivo"),
                          (OP_TRASPASO_SALIDA, "Cocos", "Balanz", "vivo")])
        for m in patas:
            self.assertEqual((str(m["id"])[:3], m["date"], m["asset"], m["quantity"], m["currency"],
                              m["traspaso_id"], m["borrable"], m["fees_usd"], m["cobro"]),
                             ("tx-", FECHA_PASE, "NVDA", 12.0, "ARS", tid, False, 0, None))
            self.assertAlmostEqual(m["amount_usd"], p["V"], places=9)
            self.assertAlmostEqual(m["fx_to_usd"], p["V_ars"] / p["V"], places=9)
            # La vista en pesos (amount_usd × el dólar sellado) da los pesos de la pata.
            self.assertAlmostEqual(m["amount_usd"] * m["fx_to_usd"], 12 * PRECIO_PASE, places=6)
            self.assertAlmostEqual(m["unit_price"], PRECIO_PASE, places=6)

        # El gasto del trámite: una comisión de Cocos, que no se borra suelta.
        self.assertEqual([(g["broker"], g["traspaso_id"], g["borrable"]) for g in gasto],
                         [("Cocos", tid, False)])
        self.assertAlmostEqual(gasto[0]["amount_usd"], p["gasto_usd"], places=9)

        # La compra original del lote cargado a mano.
        self.assertEqual([{k: c[k] for k in ("id", "type", "date", "broker", "asset", "quantity",
                                             "unit_price", "currency", "source", "traspaso_id",
                                             "borrable", "notes")} for c in pasadas],
                         [{"id": f"trp-{tid}-0", "type": "BUY", "date": "2025-01-02",
                           "broker": "Cocos", "asset": "NVDA", "quantity": 2.0,
                           "unit_price": 28000.0, "currency": "ARS", "source": "traspaso",
                           "traspaso_id": tid, "borrable": False,
                           "notes": "La pasaste a Balanz el 16/06/2025"}])
        self.assertNotIn(f"pos-{lote['id']}", {m["id"] for m in despues})

        # Las comisiones: las de antes más el gasto (una fila más).
        com = self._comisiones()
        self.assertAlmostEqual(com["total_usd"], com_antes["total_usd"] + p["gasto_usd"], places=4)
        self.assertEqual(com["count"], com_antes["count"] + 1)
        self.assertAlmostEqual(self._total_como_la_pantalla(despues), com["total_usd"], places=4)

        # Borrar la compra pasada: 409 con el camino para deshacer el pase; nada escrito.
        tablas = self._tablas()
        r = self.http.delete(f"/api/movements/{pasadas[0]['id']}", headers=self.h)
        self.assertEqual((r.status_code, r.json()["detail"]),
                         (409, traspaso_a_mano.MSG_DESHACE_EL_PASE), r.text)
        self.assertEqual(self._tablas(), tablas)

        # El rebuild real no cambia nada de lo que se ve.
        self._rebuild()
        self.assertEqual(sorted(map(self._como_se_ve, self._movs())),
                         sorted(map(self._como_se_ve, despues)))

    def test_contraparte_y_estado_siguen_al_pase(self):
        """D.9.1: `contraparte` es el nombre de HOY de la otra cuenta (renombrar B lo
        cambia en las patas, en el CSV y en la compra pasada) y `estado` el del pase:
        desfasado (el detector es de E10; acá se marca a mano, como en
        `test_desfasado_se_ve_y_se_deshace`), incompleto si se borra B (queda la pata
        de A y la compra pasada, que es de A). Deshecho el pase, no queda ninguna fila
        suya y la compra cargada a mano vuelve a ser una posición abierta."""
        self._escenario()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        tid = p["traspaso_id"]

        def patas():
            return {m["type"]: m for m in self._movs() if m["type"].startswith("TRASPASO")}

        r = self.http.put(f"/api/brokers/{self._id_broker('Balanz')}", headers=self.h,
                          json={"name": "Balanz SA", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        ps_ = patas()
        self.assertEqual({op: (m["broker"], m["contraparte"]) for op, m in ps_.items()},
                         {OP_TRASPASO_SALIDA: ("Cocos", "Balanz SA"),
                          OP_TRASPASO_ENTRADA: ("Balanz SA", "Cocos")})
        self.assertEqual(sorted(f["Notas"] for f in self._csv() if f["Tipo"].startswith("TRASPASO")),
                         [f"llegaron desde Cocos · costo original US$ {p['C']:.2f}",
                          f"pasaron a Balanz SA · costo original US$ {p['C']:.2f}"])
        self.assertEqual([m["notes"] for m in self._movs() if str(m["id"]).startswith("trp-")],
                         ["La pasaste a Balanz SA el 16/06/2025"])

        conn = main.get_db()
        try:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=datetime('now'), "
                         "desfasado_motivo='origen' WHERE id=?", (tid,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual({op: m["estado"] for op, m in patas().items()},
                         {OP_TRASPASO_SALIDA: "desfasado", OP_TRASPASO_ENTRADA: "desfasado"})
        conn = main.get_db()
        try:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=NULL, desfasado_motivo=NULL "
                         "WHERE id=?", (tid,))
            conn.commit()
        finally:
            conn.close()

        r = self.http.delete(f"/api/brokers/{self._id_broker('Balanz SA')}",
                             params={"force": "true"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual({op: (m["broker"], m["contraparte"], m["estado"]) for op, m in patas().items()},
                         {OP_TRASPASO_SALIDA: ("Cocos", "Balanz SA", "incompleto")})
        self.assertEqual([m["id"] for m in self._movs() if str(m["id"]).startswith("trp-")],
                         [f"trp-{tid}-0"])

        self._deshacer_ok(tid)
        movs = self._movs()
        self.assertEqual([m["id"] for m in movs if m.get("traspaso_id")
                          or m["type"].startswith("TRASPASO")], [])
        self.assertEqual([(m["type"], m["broker"], m["quantity"]) for m in movs
                          if str(m["id"]).startswith("pos-")], [("BUY", "Cocos", 2.0)])

    def test_borrar_a_saca_la_compra_pasada_y_deja_la_llegada(self):
        """Con A borrado (`?force=true`), el pase queda incompleto del lado de B: la pata
        de entrada sigue, con `contraparte` = la A que ya no existe (de la receta), y la
        compra pasada se va con A (era una compra de A: `lotes_a_mano_que_salieron`
        sólo cuenta los pases cuyo lote de salida sigue confirmado)."""
        self._escenario()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        r = self.http.delete(f"/api/brokers/{self._id_broker('Cocos')}", params={"force": "true"},
                             headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        movs = self._movs()
        self.assertEqual([(m["type"], m["broker"], m["contraparte"], m["estado"], m["traspaso_id"])
                          for m in movs if m["type"].startswith("TRASPASO")],
                         [(OP_TRASPASO_ENTRADA, "Balanz", "Cocos", "incompleto", p["traspaso_id"])])
        self.assertEqual([m for m in movs if str(m["id"]).startswith("trp-")], [])
        self.assertEqual([m for m in movs if m["broker"] == "Cocos"], [])


class ComisionesIgualesAntesYDespues(_Movimientos):

    def test_kpi_comisiones_igual_antes_y_despues(self):
        """#7. `/api/insights/commissions` igual antes y después del pase (todo, sin
        gasto), también con el lote cargado a mano movido (su comisión sigue en la fila
        `trp-`): la comisión de la compra de llegada en Balanz es la COPIA de la de
        Cocos y antes se contaba dos veces. Igual después del rebuild real y del
        deshacer. Y la pantalla, que suma las mismas filas, da lo mismo, igual que el
        diagnóstico de admin que «espeja» este total (D.9.5: sin la compra de llegada)."""
        self._escenario()
        antes = self._comisiones()
        self.assertEqual(antes["count"], 2, "control: la comisión importada y la cargada a mano")

        def diagnostico():
            return self._get(f"/api/admin/commissions-debug?user_id={self.uid}").json()

        diag_antes = diagnostico()
        self.assertGreater(diag_antes["comisiones_usd"], 0)
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        self.assertEqual([l["origen"] for l in p["receta"]["lotes"]], ["a_mano", "importado"])
        self.assertEqual(self._comisiones(), antes)
        self.assertEqual(diagnostico()["comisiones_usd"], diag_antes["comisiones_usd"])
        self.assertAlmostEqual(self._total_como_la_pantalla(self._movs()), antes["total_usd"], places=4)
        self._rebuild()
        self.assertEqual(self._comisiones(), antes)
        self._deshacer_ok(p["traspaso_id"])
        self.assertEqual(self._comisiones(), antes)

    def test_parte_de_un_lote_cargado_a_mano(self):
        """#7, variante: se pasa 1 de los 2 cargados a mano. La compra se ve en dos
        renglones —lo que quedó en Cocos (`pos-`) y lo que se pasó (`trp-`), con la
        mitad de la comisión cada uno— y el total de comisiones no cambia. (`count`
        sube uno: es la misma compra en dos renglones.)"""
        lote = self._escenario()
        antes = self._comisiones()
        fila_antes = [m for m in self._movs() if m["id"] == f"pos-{lote['id']}"][0]
        self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=1)
        despues = self._comisiones()
        self.assertAlmostEqual(despues["total_usd"], antes["total_usd"], places=4)
        self.assertEqual(despues["count"], antes["count"] + 1)
        dos = [m for m in self._movs() if m["type"] == "BUY" and str(m["date"])[:10] == "2025-01-02"]
        self.assertEqual(sorted((str(m["id"]).split("-")[0], m["quantity"]) for m in dos),
                         [("pos", 1.0), ("trp", 1.0)])
        for campo in ("amount_usd", "fees_usd"):
            self.assertAlmostEqual(sum(m[campo] for m in dos), fila_antes[campo], places=9)


class CsvDeTransacciones(_Movimientos):

    def test_transactions_csv_con_las_patas_y_sin_compras_ni_ventas_de_mas(self):
        """#6 (la parte de E9, D.9.3 y D.9.4). `transactions.csv` después del pase (con
        gasto): una fila «TRASPASO (SALE)» en Cocos y una «TRASPASO (ENTRA)» en Balanz,
        con lo que valían en pesos (12 × $45.000), el precio del día, sin comisión y
        las notas «pasaron a Balanz / llegaron desde Cocos · costo original US$ C»;
        el gasto como COMISIÓN; ni la VENTA a precio 0 ni las COMPRAS de llegada. El
        resto, igual que antes: la compra del lote cargado a mano sigue (sus notas
        dicen ahora a dónde se pasó)."""
        self._escenario()
        antes = self._csv()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, gasto=5000)
        despues = self._csv()
        patas = [f for f in despues if f["Tipo"].startswith("TRASPASO")]
        campos = ("Fecha", "Tipo", "Broker", "Activo", "Cantidad", "Precio unit.", "Monto",
                  "Moneda", "Comisiones", "Notas")
        costo = f"{p['C']:.2f}"
        self.assertEqual(sorted(tuple(f[c] for c in campos) for f in patas), [
            (FECHA_PASE, "TRASPASO (ENTRA)", "Balanz", "NVDA", "12.0", "45000.0", "540000.0",
             "ARS", "0", f"llegaron desde Cocos · costo original US$ {costo}"),
            (FECHA_PASE, "TRASPASO (SALE)", "Cocos", "NVDA", "12.0", "45000.0", "540000.0",
             "ARS", "0", f"pasaron a Balanz · costo original US$ {costo}")])
        self.assertEqual([f for f in despues if f["Tipo"] in ("COMPRA", "VENTA")
                          and f["Fecha"] == FECHA_PASE], [])
        gasto = [f for f in despues if f["Tipo"] == "COMISIÓN" and f["Fecha"] == FECHA_PASE]
        self.assertEqual([(f["Broker"], f["Monto"], f["Moneda"]) for f in gasto],
                         [("Cocos", "5000.0", "ARS")])
        resto = [f for f in despues if f not in patas and f not in gasto]

        def sin_notas(filas):
            return sorted(tuple(f[c] for c in campos if c != "Notas") for f in filas)

        self.assertEqual(sin_notas(resto), sin_notas(antes))
        self.assertEqual([f["Notas"] for f in antes if f["Fecha"] == "2025-01-02"],
                         ["manual · posición abierta"])
        self.assertEqual([f["Notas"] for f in resto if f["Fecha"] == "2025-01-02"],
                         ["manual · La pasaste a Balanz el 16/06/2025"])
        self.assertEqual(sorted(f["Notas"] for f in resto if f["Fecha"] != "2025-01-02"),
                         sorted(f["Notas"] for f in antes if f["Fecha"] != "2025-01-02"))

    def test_lote_en_dolares_valuado_en_pesos(self):
        """Un CEDEAR comprado en dólares (en «Cocos · USD») se valúa con su precio en
        PESOS: la pata guarda `unit_price` = $45.000 y `currency` = USD. Movimientos y
        el CSV muestran el monto en la moneda de los lotes (US$ V) y el precio por
        título en esa MISMA moneda (V / 3), así cantidad × precio = monto. Con la
        comisión de la compra en dólares, el total de comisiones no cambia."""
        self._broker("Cocos · USD", "USDT", padre="Cocos")
        con_tipo = HDR.rstrip("\n") + ",asset_type\n"
        self._importar("Cocos · USD", [
            "2025-01-06,DEPOSITO,Cocos · USD,,,,500,,,,USD,dep,",
            "2025-01-25,COMPRA,Cocos · USD,NVDA,3,14,42,,,0.5,USD,compra,CEDEAR"], hdr=con_tipo)
        com_antes = self._comisiones()
        p = self._aplicar(self._pedido("NVDA", "Cocos", "Balanz", FECHA_PASE, moneda="USD",
                                       precio_manual=PRECIO_PASE))
        salida = [f for f in p["filas"] if f["operation_type"] == OP_TRASPASO_SALIDA]
        self.assertEqual([(f["currency"], f["unit_price"]) for f in salida], [("USD", PRECIO_PASE)],
                         "control: el precio guardado es en pesos y los lotes en dólares")
        V = p["V"]
        self.assertAlmostEqual(V, 3 * PRECIO_PASE / dolar(FECHA_PASE), places=6)
        patas = [m for m in self._movs() if m["type"].startswith("TRASPASO")]
        self.assertEqual(sorted((m["type"], m["broker"], m["contraparte"]) for m in patas),
                         [(OP_TRASPASO_ENTRADA, "Balanz · USD", "Cocos"),
                          (OP_TRASPASO_SALIDA, "Cocos · USD", "Balanz")])
        for m in patas:
            self.assertEqual((m["currency"], m["quantity"]), ("USD", 3.0))
            self.assertAlmostEqual(m["amount_usd"], V, places=9)
            self.assertAlmostEqual(m["unit_price"], V / 3, places=9)
            self.assertAlmostEqual(m["fx_to_usd"], p["V_ars"] / V, places=9)
        filas = [f for f in self._csv() if f["Tipo"].startswith("TRASPASO")]
        self.assertEqual(len(filas), 2)
        for f in filas:
            self.assertEqual((f["Moneda"], f["Cantidad"], f["Monto"], f["Precio unit."]),
                             ("USD", "3.0", str(round(V, 2)), str(round(V / 3, 6))))
            self.assertAlmostEqual(float(f["Cantidad"]) * float(f["Precio unit."]),
                                   float(f["Monto"]), delta=0.01)
        self.assertEqual(self._comisiones(), com_antes)



# ── E10: el detector de pases desfasados (D.5.5) ───────────────────────────────

class _Desfase(_Deshacer):
    """Lo que necesitan las pruebas del detector (E10). Las puertas (`pase_que_cambia`,
    C.11, y las guardas de D.10) frenan lo que reescribiría la historia anterior a un
    pase vivo; para probar el detector algo tiene que escaparse de verdad: una fila
    SEMBRADA DIRECTO en el registro de lo importado, que ninguna puerta ve pasar. El
    detector la ve recién cuando algo rearma el registro (el rebuild real, un import,
    un borrado, la migración del dólar), que es cuando corre en producción."""

    def _plantar(self, batch_id, broker, op, fecha, asset, cantidad, precio=0.0, monto=0.0,
                 moneda="ARS", tipo="CEDEAR"):
        """Una fila en el registro, escrita directo en la base (ni el importador ni otra
        puerta la ven). Sin plata (precio y monto 0): ninguna caja la explica, así que
        borrarla después por la puerta de Movimientos tampoco devuelve nada."""
        conn = main.get_db()
        try:
            n = conn.execute("SELECT COUNT(*) AS c FROM import_raw_rows WHERE batch_id=?",
                             (batch_id,)).fetchone()["c"]
            raw = conn.execute(
                "INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status) "
                "VALUES (?, ?, '{}', 'valid')", (batch_id, 90000 + n)).lastrowid
            nid = conn.execute(
                "INSERT INTO import_normalized_tx (batch_id, raw_row_id, date, broker, "
                "operation_type, asset_symbol, asset_type, quantity, unit_price, gross_amount, "
                "fees, currency, transfer_out, fingerprint, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0,?, 'sembrada directo')",
                (batch_id, raw, fecha, broker, op, asset, tipo, cantidad, precio, monto, moneda,
                 f"sembrada-{uuid.uuid4().hex}")).lastrowid
            conn.commit()
            return nid
        finally:
            conn.close()

    def _arrancar(self, nid):
        """Saca la fila sembrada `nid` como llegó: directo, sin ninguna puerta."""
        conn = main.get_db()
        try:
            raw = conn.execute("SELECT raw_row_id FROM import_normalized_tx WHERE id=?",
                               (nid,)).fetchone()["raw_row_id"]
            conn.execute("DELETE FROM import_op_links WHERE raw_row_id=?", (raw,))
            conn.execute("DELETE FROM import_normalized_tx WHERE id=?", (nid,))
            conn.execute("DELETE FROM import_raw_rows WHERE id=?", (raw,))
            conn.commit()
        finally:
            conn.close()

    def _marca(self, tid):
        """(desfasado_at, desfasado_motivo) del pase, en la base."""
        conn = main.get_db()
        try:
            r = conn.execute("SELECT desfasado_at, desfasado_motivo FROM traspasos_a_mano "
                             "WHERE id=? AND user_id=?", (tid, self.uid)).fetchone()
            return (r["desfasado_at"], r["desfasado_motivo"])
        finally:
            conn.close()

    def _desmarcar(self, tid):
        conn = main.get_db()
        try:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=NULL, desfasado_motivo=NULL "
                         "WHERE id=? AND user_id=?", (tid, self.uid))
            conn.commit()
        finally:
            conn.close()

    def _como_se_ve(self, tid):
        """El estado del pase en las tres pantallas que lo dicen: GET /traspasos, sus
        dos patas en Movimientos y sus dos lotes en Importaciones."""
        t = self._uno(tid)
        patas = [m["estado"] for m in self._get("/api/movements").json()
                 if m.get("traspaso_id") == tid and str(m["type"]).startswith("TRASPASO")]
        lotes = [b["traspaso"]["estado"] for b in self._get("/api/imports").json()
                 if (b.get("traspaso") or {}).get("id") == tid]
        return t["estado"], sorted(patas), sorted(lotes)

    def _lotes_cortos(self, broker, asset="NVDA"):
        return [(l["quantity"], round(float(l["invested"] or 0), 4),
                 round(float(l["commissions"] or 0), 4), l["ed"], l["desde"])
                for l in self._lotes(broker, asset)]


AVISO_COCOS = ("Cambió la historia de Cocos y este pase quedó desactualizado: deshacelo y "
               "hacelo de nuevo.")
AVISO_BALANZ = ("Cambió la historia de Balanz y este pase quedó desactualizado: deshacelo y "
                "hacelo de nuevo.")


class DesfasadoVisibleYDeshacerLoArregla(_Desfase):

    def test_desfasado_visible_y_deshacer_lo_arregla(self):
        """#34, del lado de A (origen). Pase de 6 de los 10 NVDA de Cocos; el rebuild real
        dos veces lo deja vivo. Se escapa de las puertas una compra VIEJA en el archivo
        de Cocos (3 NVDA del 02/01, sembrada directo). El próximo rebuild real rearma
        Cocos desde el registro: la salida del pase ahora se lleva los 3 sembrados y 3 de
        los 10, no los 6 que movió el pase → desfasado por «origen». GET /traspasos,
        Movimientos e Importaciones lo dicen, con el aviso; otro rebuild no lo vuelve a
        sellar. El deshacer deja Cocos como dice su registro (los 3 sembrados y los 10)
        y Balanz sin NVDA; sacada la fila que se escapó por la puerta de siempre
        (Movimientos → borrar), `estado()` (F.1 entero, con las fotos medidas) es el de
        antes del pase, también después de otro rebuild."""
        self._historia()
        self._plantar_fotos()
        antes = self.estado_completo()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        tid = p["traspaso_id"]
        self._rebuild()
        self._rebuild()
        self.assertEqual(self._como_se_ve(tid), ("vivo", ["vivo", "vivo"], ["vivo", "vivo"]))

        fila = self._plantar(self._lote_original("Cocos"), "Cocos", "BUY", "2025-01-02", "NVDA", 3)
        self.assertEqual(self._marca(tid), (None, None), "control: sembrar no corre el detector")
        self._rebuild(desfasados={tid})
        marca = self._marca(tid)
        self.assertEqual(marca[1], "origen")
        self.assertEqual(self._como_se_ve(tid),
                         ("desfasado", ["desfasado", "desfasado"], ["desfasado", "desfasado"]))
        t = self._uno(tid)
        self.assertEqual((t["aviso"], t["puede_deshacer"], t["motivo"]), (AVISO_COCOS, True, None))
        # El rearmado dejó en Cocos lo que dice el registro (la salida se llevó los 3
        # sembrados y 3 de los 10), no lo que el pase movió (6 de los 10).
        self.assertEqual([l[0] for l in self._lotes_cortos("Cocos")], [7.0])
        self._rebuild(desfasados={tid})
        self.assertEqual(self._marca(tid), marca, "otro rebuild volvió a sellar el desfase")

        self.assertEqual(self._deshacer_ok(tid), "Listo: los 6 NVDA volvieron a Cocos.")
        self.assertEqual(self._lotes_cortos("Cocos"),
                         [(3.0, 0.0, 0.0, "2025-01-02", ""),
                          (10.0, 300000.0, 1500.0, "2025-01-10", "")])
        self.assertEqual(self._lotes("Balanz"), [])
        self.assertEqual(self._traspasos()["traspasos"], [])
        self.assertEqual(self._lotes_del_pase(tid)[0], ["reverted", "reverted"])

        r = self.http.delete(f"/api/movements/tx-{fila}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._igual(self.estado_completo(), antes)
        self._rebuild()
        self._igual(self.estado_completo(), antes)

    def test_desfasado_por_destino(self):
        """#34, del lado de B (destino). Pase de los 10 NVDA de Cocos a Balanz. Se escapa
        una VENTA en el archivo de Balanz ANTERIOR a la llegada (2 NVDA del 03/03,
        sembrada directo): el rebuild real de Balanz la cubre con un lote semilla y deja
        los 10 que llegaron enteros (títulos de más) → desfasado por «destino», con el
        aviso de Balanz. El deshacer saca de Balanz lo que llegó y devuelve los 10 a
        Cocos; sacada la venta que se escapó por la puerta de siempre, `estado()` es el
        de antes del pase."""
        self._historia()
        self._plantar_fotos()
        antes = self.estado_completo()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE)
        tid = p["traspaso_id"]
        fila = self._plantar(self._lote_original("Balanz"), "Balanz", "SELL", "2025-03-03",
                             "NVDA", 2)
        self._rebuild(desfasados={tid})
        self.assertEqual(self._marca(tid)[1], "destino")
        self.assertEqual(self._como_se_ve(tid),
                         ("desfasado", ["desfasado", "desfasado"], ["desfasado", "desfasado"]))
        self.assertEqual(self._uno(tid)["aviso"], AVISO_BALANZ)
        self.assertEqual(self._lotes_cortos("Balanz"),
                         [(10.0, 300000.0, 1500.0, "2025-01-10", FECHA_PASE)],
                         "control: la venta vieja no tocó lo que llegó")

        self.assertEqual(self._deshacer_ok(tid), "Listo: los 10 NVDA volvieron a Cocos.")
        self.assertEqual(self._lotes("Balanz"), [])
        r = self.http.delete(f"/api/movements/tx-{fila}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._igual(self.estado_completo(), antes)


class UnaPuertaQueSeEscapa(_Desfase):

    def test_editar_el_precio_promedio_en_a_lo_desfasa(self):
        """Algo que se escapa de las puertas SIN sembrar nada: editar en grupo el precio
        promedio de lo que quedó en A (`PATCH /api/positions/group`, que no frena con un
        pase vivo: la regla de C.11 sólo frena el ticker y el tipo) escala también la
        COMPRA del archivo de la que salió parte del pase. Pase de 6 de los 10 NVDA de
        Cocos; promedio de los 4 que quedan: $30.000 → $33.000 (×1,1). La edición no
        rearma nada (el pase sigue vivo); el próximo rebuild real ve que la salida del
        pase ahora se lleva $198.000 de costo y el pase movió $180.000 → desfasado por
        «origen». El deshacer rearma Cocos desde el registro: los 10 con el costo nuevo
        ($330.000)."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        tid = p["traspaso_id"]
        r = self.http.patch("/api/positions/group", headers=self.h,
                            json={"broker": "Cocos", "asset": "NVDA", "currency": "ARS",
                                  "avg_price": 33000})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._lotes_cortos("Cocos"),
                         [(4.0, 132000.0, 600.0, "2025-01-10", "")])
        self.assertEqual(self._marca(tid), (None, None), "control: la edición no rearma")
        self._rebuild(desfasados={tid})
        self.assertEqual(self._marca(tid)[1], "origen")
        self.assertEqual(self._uno(tid)["aviso"], AVISO_COCOS)
        self.assertEqual(self._deshacer_ok(tid), "Listo: los 6 NVDA volvieron a Cocos.")
        self.assertEqual(self._lotes_cortos("Cocos"),
                         [(10.0, 330000.0, 1500.0, "2025-01-10", "")])
        self.assertEqual(self._lotes("Balanz"), [])


class DetectorSinFalsos(_Desfase):

    def test_pases_sanos_siguen_vivos_despues_de_varios_rebuilds(self):
        """Sin nada escapado, el detector no marca nada, por más rebuilds que corran
        (aparte, cada `_rebuild()` de este archivo lo afirma: ninguna prueba con pases
        sanos termina con un pase desfasado). Una cuenta con los casos que más fácil
        podrían dar un falso aviso:
          · NVDA: un lote cargado a mano viejo + el lote importado ya achicado por una
            venta (inversión redondeada) + una parte del segundo lote (pase parcial);
            después Cocos vende más y Balanz vende todo lo que llegó y 2 más (otra
            semilla, POSTERIOR a la llegada: B vendió de más, no es cosa del pase);
          · Balanz ya había vendido 2 NVDA el 03/03, ANTES del pase, sin tenerlos (su
            archivo empieza tarde: el replay pone un lote semilla). Esa semilla anterior
            a la llegada ya estaba cuando se hizo el pase: no es un desfase;
          · AAPL: 3 de 7 (una división que no da exacta) a Balanz, y de ahí a IOL (un
            pase encadenado).
        Tres rebuilds reales: los tres pases siguen vivos en la base y en las pantallas, y
        el detector los MIRÓ (no se los salteó): A de los tres y B de los dos cuyo par
        tiene ventas, todos cuadrando, con la semilla vieja de Balanz a la vista."""
        self._historia()
        self._broker("IOL")
        self._importar("Cocos", [
            "2025-02-10,COMPRA,Cocos,NVDA,5,32000,160000,,,0,ARS,compra",
            "2025-02-15,COMPRA,Cocos,AAPL,7,14285.7142857,100000,,,77,ARS,compra",
            "2025-03-10,VENTA,Cocos,NVDA,3,35000,105000,,,0,ARS,venta"])
        self._importar("Balanz", ["2025-03-03,VENTA,Balanz,NVDA,2,38000,76000,,,0,ARS,venta"])
        self._lote_a_mano("Cocos", "NVDA", 2, 28000, "2025-01-02", commissions=280)
        p1 = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=11)
        self.assertEqual([(l["origen"], l["parcial"]) for l in p1["receta"]["lotes"]],
                         [("a_mano", False), ("importado", False), ("importado", True)])
        p2 = self._fabricar_pase("AAPL", "Cocos", "Balanz", "2025-06-20", 20000.0, cantidad=3)
        p3 = self._fabricar_pase("AAPL", "Balanz", "IOL", "2025-07-15", 21000.0)
        self._importar("Cocos", ["2025-08-01,VENTA,Cocos,NVDA,2,41000,82000,,,0,ARS,venta"])
        self._importar("Balanz", ["2025-09-01,VENTA,Balanz,NVDA,13,42000,546000,,,0,ARS,venta"])
        tids = {p["traspaso_id"] for p in (p1, p2, p3)}

        vistos = []
        lados = []
        real_marcar = traspaso_a_mano.marcar_desfasados
        real_lados = traspaso_a_mano._lados_que_no_cuadran

        def espia_marcar(conn, uid, replay):
            vistos.append(replay)
            return real_marcar(conn, uid, replay)

        def espia_lados(conn, t, salidas, llegadas, replay):
            out = real_lados(conn, t, salidas, llegadas, replay)
            lados.append((t["id"], tuple(out[0]), tuple(out[1])))
            return out

        with mock.patch.object(traspaso_a_mano, "marcar_desfasados", espia_marcar), \
                mock.patch.object(traspaso_a_mano, "_lados_que_no_cuadran", espia_lados):
            for _ in range(3):
                self._rebuild()

        self.assertEqual([l for l in lados if l[1]], [], "un lado no cuadró")
        mirados = {(tid, lado) for tid, _, buenos in lados for lado in buenos}
        self.assertEqual(mirados, {(t, "origen") for t in tids}
                         | {(p1["traspaso_id"], "destino"), (p2["traspaso_id"], "destino")})
        # Las dos semillas de Balanz —la del 03/03, anterior a la llegada del pase de
        # NVDA pero que ya estaba cuando se hizo, y la del 01/09, escrita después pero
        # posterior a la llegada— estuvieron a la vista del detector y no lo marcaron.
        self.assertTrue(any(
            p1["traspaso_id"] in (r.get("llegadas_de_pases") or {})
            and {s["fecha"] for s in r.get("semillas_detalle") or []} == {"2025-03-03",
                                                                           "2025-09-01"}
            for r in vistos), "control: las semillas de Balanz no llegaron al detector")
        for tid in tids:
            self.assertEqual(self._marca(tid), (None, None))
            self.assertEqual(self._como_se_ve(tid), ("vivo", ["vivo", "vivo"], ["vivo", "vivo"]))

    def test_un_pase_sano_sigue_vivo_por_cada_puerta_que_rearma(self):
        """Los mismos escritores que `test_el_detector_corre_en_cada_puerta_que_rearma`
        (un import posterior, el borrado desde Movimientos, el rebuild real y la migración
        del dólar), sobre un pase sano: ninguno lo marca."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        tid = p["traspaso_id"]
        self._importar("Cocos", ["2025-08-01,COMPRA,Cocos,NVDA,1,40000,40000,,,0,ARS,compra"])
        self.assertEqual(self._marca(tid), (None, None), "el import")
        conn = main.get_db()
        try:
            nid = conn.execute(
                "SELECT n.id FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
                "WHERE b.user_id=? AND n.date='2025-08-01' AND n.operation_type='BUY'",
                (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        r = self.http.delete(f"/api/movements/tx-{nid}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._marca(tid), (None, None), "el borrado")
        self._rebuild()
        conn = main.get_db()
        try:
            fx.set_fx_version(conn, self.uid, "v1")
            conn.commit()
        finally:
            conn.close()
        r = self.http.post("/api/admin/fx-migrate-user", headers=self.h,
                           params={"user_id": self.uid, "apply": "true", "force": "true"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("ok"), r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._marca(tid), (None, None), "la migración del dólar")
        self.assertEqual(self._como_se_ve(tid), ("vivo", ["vivo", "vivo"], ["vivo", "vivo"]))

    def test_sin_pases_no_consulta_nada(self):
        """La enorme mayoría de los rearmados no tiene pases: el detector vuelve sin
        tocar la base (acá ni siquiera hay conexión)."""
        self.assertEqual(traspaso_a_mano.marcar_desfasados(
            None, self.uid, {"operations": [], "open_lots": [], "traspasos": {},
                             "llegadas_de_pases": {}, "semillas": ["2025-03-03"],
                             "semillas_detalle": [{"fecha": "2025-03-03", "fila": 9,
                                                   "traspaso_id": None, "cantidad": 1.0}]}),
            {})


class SiElDetectorFalla(_Desfase):

    def test_si_el_detector_falla_la_reconstruccion_sigue(self):
        """El detector es un aviso: si se rompe (acá, una consulta que la base rechaza
        adentro de él), la reconstrucción que lo llamó sigue y escribe los lotes. Corre en
        su propio punto de guardado: en Postgres un error de SQL aborta la transacción
        entera, y sin el punto de guardado la sentencia siguiente del rearmado (y el
        commit) caían con él. Un import y un borrado desde Movimientos de un activo con
        un pase vivo, con el detector roto: los dos terminan bien."""
        self._historia()
        self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)

        def roto(conn, *a, **k):
            conn.execute("SELECT columna_que_no_existe FROM traspasos_a_mano")

        with mock.patch.object(traspaso_a_mano, "_lados_que_no_cuadran", roto):
            self._importar("Cocos", ["2025-08-01,COMPRA,Cocos,NVDA,1,40000,40000,,,0,ARS,compra"])
            self.assertEqual([l[0] for l in self._lotes_cortos("Cocos")], [4.0, 1.0])
            conn = main.get_db()
            try:
                nid = conn.execute(
                    "SELECT n.id FROM import_normalized_tx n JOIN import_batches b "
                    "ON b.id=n.batch_id WHERE b.user_id=? AND n.date='2025-08-01'",
                    (self.uid,)).fetchone()["id"]
            finally:
                conn.close()
            r = self.http.delete(f"/api/movements/tx-{nid}", headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
            self._esperar_reconstruccion()
        self.assertEqual([l[0] for l in self._lotes_cortos("Cocos")], [4.0])


class DesfaseQueVuelveACuadrar(_Desfase):

    def test_vuelve_a_cuadrar_y_se_desmarca_solo_su_lado(self):
        """D.5.5: si el registro vuelve a cuadrar, el próximo rearmado desmarca el pase,
        pero sólo si el motivo era el lado que acaba de mirar. Se siembra la compra vieja
        en Cocos (desfasado por «origen») y se arranca igual que llegó: el rebuild real lo
        deja vivo otra vez, con Cocos en los 4 que le quedaban. Marcado a mano por
        «destino», un rebuild que sólo rearma Cocos no lo toca; un import de Balanz (una
        venta posterior a la llegada, que pasa por las puertas) rearma Balanz, ve que
        cuadra y lo desmarca."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        tid = p["traspaso_id"]
        fila = self._plantar(self._lote_original("Cocos"), "Cocos", "BUY", "2025-01-02", "NVDA", 3)
        self._rebuild(desfasados={tid})
        self.assertEqual(self._marca(tid)[1], "origen")
        self._arrancar(fila)
        self._rebuild()
        self.assertEqual(self._marca(tid), (None, None))
        self.assertEqual(self._como_se_ve(tid), ("vivo", ["vivo", "vivo"], ["vivo", "vivo"]))
        self.assertEqual([l[0] for l in self._lotes_cortos("Cocos")], [4.0])

        conn = main.get_db()
        try:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=datetime('now'), "
                         "desfasado_motivo='destino' WHERE id=?", (tid,))
            conn.commit()
        finally:
            conn.close()
        self._rebuild(desfasados={tid})
        self.assertEqual(self._marca(tid)[1], "destino", "el lado de A desmarcó el de B")
        self._importar("Balanz", ["2025-09-01,VENTA,Balanz,NVDA,1,42000,42000,,,0,ARS,venta"])
        self.assertEqual(self._marca(tid), (None, None))


class ElDetectorCorreEnCadaPuerta(_Desfase):

    def test_el_detector_corre_en_cada_puerta_que_rearma(self):
        """Todos los escritores que rearman lotes desde el registro pasan por las dos
        reconstrucciones, y el detector corre en las dos. Con la compra vieja sembrada
        en Cocos, cada uno marca el pase (se desmarca a mano entre uno y otro):
          · un import posterior del activo en Cocos (`rebuild_fifo_after_import`);
          · borrar esa compra desde Movimientos (la cascada: `rebuild_pair_asset`);
          · el rebuild real (`recompute_user`, como el backfill);
          · la migración del dólar de una cuenta v1 (`migrate_user_fx`, por el panel de
            admin, que rearma lote por lote)."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        tid = p["traspaso_id"]
        self._plantar(self._lote_original("Cocos"), "Cocos", "BUY", "2025-01-02", "NVDA", 3)
        self.assertEqual(self._marca(tid), (None, None))

        self._importar("Cocos", ["2025-08-01,COMPRA,Cocos,NVDA,1,40000,40000,,,0,ARS,compra"])
        self.assertEqual(self._marca(tid)[1], "origen", "el import no corrió el detector")
        self._desmarcar(tid)

        conn = main.get_db()
        try:
            nid = conn.execute(
                "SELECT n.id FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
                "WHERE b.user_id=? AND n.date='2025-08-01' AND n.operation_type='BUY'",
                (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        r = self.http.delete(f"/api/movements/tx-{nid}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._marca(tid)[1], "origen", "el borrado no corrió el detector")
        self._desmarcar(tid)

        self._rebuild(desfasados={tid})
        self._desmarcar(tid)

        conn = main.get_db()
        try:
            fx.set_fx_version(conn, self.uid, "v1")
            conn.commit()
        finally:
            conn.close()
        r = self.http.post("/api/admin/fx-migrate-user", headers=self.h,
                           params={"user_id": self.uid, "apply": "true", "force": "true"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("ok"), r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._marca(tid)[1], "origen", "la migración del dólar no corrió el detector")


class DeshacerUnDesfasadoSinPoderRearmar(_Desfase):

    def test_desfasado_con_a_no_reconstruible_frena_con_la_salida(self):
        """C.8 con un pase desfasado por «origen»: los lotes de A son los que dejó el
        REGISTRO. Si después se carga a mano un lote del activo en A, A ya no se puede
        rearmar y el deshacer por el vínculo devolvería los lotes de la receta encima
        (otros costos y fechas). Frena (409, también en GET: `puede_deshacer` falso, con el
        motivo) sin tocar nada; borrado el lote cargado a mano, el deshacer rearma A
        desde el registro."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", FECHA_PASE, PRECIO_PASE, cantidad=6)
        tid = p["traspaso_id"]
        self._plantar(self._lote_original("Cocos"), "Cocos", "BUY", "2025-01-02", "NVDA", 3)
        self._rebuild(desfasados={tid})
        lote = self._lote_a_mano("Cocos", "NVDA", 1, 41000, "2025-09-01")
        texto = traspaso_a_mano.MSG_DESFASADO_CON_A_MANO.format(A="Cocos", asset="NVDA")
        self.assertEqual(texto, "Este pase quedó desactualizado y en Cocos tenés NVDA cargados a "
                                "mano, así que Rendi no puede rearmar Cocos desde tus archivos para "
                                "devolverle bien los títulos. Borrá en Cocos lo que cargaste a mano "
                                "de NVDA, deshacé el pase y después volvé a cargarlo.")
        t = self._uno(tid)
        self.assertEqual((t["estado"], t["puede_deshacer"], t["motivo"]), ("desfasado", False, texto))
        tablas = self._tablas()
        self._no_deshace(tid, 409, texto)
        self.assertEqual(self._tablas(), tablas)

        r = self.http.delete(f"/api/positions/{lote['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._deshacer_ok(tid)
        self.assertEqual([l[:4] for l in self._lotes_cortos("Cocos")],
                         [(3.0, 0.0, 0.0, "2025-01-02"), (10.0, 300000.0, 1500.0, "2025-01-10")])
        self.assertEqual(self._lotes("Balanz"), [])


if __name__ == "__main__":
    unittest.main()
