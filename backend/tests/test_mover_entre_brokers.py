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

EL PASE, POR AHORA, FABRICADO (`_fabricar_pase`). El endpoint `POST
/api/positions/traspaso` llega en la etapa E6. Hasta entonces las filas del pase se
arman como las va a armar él (A.6/A.7 y C.7): `store_preview_txs` con
`parser_format='traspaso_a_mano'` → `load_session_for_confirm` → `persist_batch`,
la fila de `traspasos_a_mano`, y después la cola de cualquier puerta
(`_cascade_after_movement_delete`: cadena, RECÁLCULO REAL y fotos). Lo que se mira
sale de los endpoints reales (`GET /api/monthly`, el CSV mensual, Reportes). E6
reemplaza el fabricante por el endpoint y estas pruebas tienen que seguir en verde.

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
        # TODO(E5/E6): prender el interruptor `mover_entre_brokers` acá cuando exista.
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        for nombre, valor in (("_fetch_data912_bonds", {}), ("_bench_para_reportes", {})):
            p = mock.patch.object(main, nombre, return_value=valor)
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

    def _fabricar_pase(self, asset, origen, destino, fecha, precio, *, gasto=None):
        """Las filas de un pase de TODO `asset` de `origen` a `destino`, escritas como las
        va a escribir `POST /api/positions/traspaso` (C.4–C.7, A.6–A.7).

        ⚠️ ES UN ANDAMIO DE LA ETAPA E4: E6 lo reemplaza por el endpoint. Cubre sólo lo
        que E4 necesita: lotes importados en pesos, una sola pata por lado, precio en
        pesos. V = cantidad × precio al dólar del día (`tc_pase` = `tc_venta`, C.4.3);
        C con `tramo.costo_y_resultado_del_tramo`, la cuenta única de los motores
        (C.5). Todo en UNA transacción, como C.7, con la cola de las puertas
        (`_cascade_after_movement_delete`: cadena, recálculo real y fotos)."""
        conn = main.get_db()
        try:
            with conn:
                main._tomar_turno_de_la_puerta(conn, self.uid)
                hist = fx.fx_version(conn, self.uid) == fx.FX_V2
                tc_blue = main._config_tc_blue(conn, self.uid)
                tc_venta = fx.fx_for_date(conn, fecha, fallback=tc_blue) if hist else tc_blue
                lotes = [dict(r) for r in conn.execute(
                    "SELECT * FROM positions WHERE user_id=? AND broker=? AND asset=? "
                    "AND is_cash=0 ORDER BY entry_date, id", (self.uid, origen, asset))]
                self.assertTrue(lotes, f"{origen} no tiene {asset}")
                tid = secrets.token_hex(16)
                compras, recetas = [], []
                q = inv_sin_com = c_nat = c_usd = 0.0
                for k, lote in enumerate(lotes):
                    origen_fila = conn.execute(
                        "SELECT n.batch_id, n.raw_row_id, n.asset_type, n.asset_name "
                        "FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id "
                        "WHERE b.user_id=? AND n.created_position_id=? AND n.operation_type='BUY'",
                        (self.uid, lote["id"])).fetchone()
                    self.assertIsNotNone(origen_fila, "el andamio sólo mueve lotes importados")
                    take = float(lote["quantity"])
                    moneda = (lote["currency"] or "ARS").upper()
                    self.assertEqual(moneda, "ARS", "el andamio sólo mueve lotes en pesos")
                    t = tramo.costo_y_resultado_del_tramo(
                        conn, lote=lote, take=take, currency=moneda, sell_currency=moneda,
                        exit_price=precio, chunk_commission=0.0, tc_venta=tc_venta,
                        tc_blue=tc_blue, hist=hist, op_date=fecha, transfer_out=False)
                    inv, com = float(lote["invested"] or 0), float(lote["commissions"] or 0)
                    q += take
                    inv_sin_com += inv
                    c_nat += inv + com
                    c_usd += t["invested_usd"]
                    compra_original = str(lote["entry_date"])[:10]
                    compras.append(NormalizedTx(
                        row_index=-49999 + k, date=fecha, broker=destino, operation_type=OP_BUY,
                        asset_symbol=asset, asset_type=lote["asset_type"] or origen_fila["asset_type"],
                        asset_name=origen_fila["asset_name"], quantity=take,
                        unit_price=lote["buy_price"] or ((inv + com) / take),
                        gross_amount=inv, fees=com, currency=moneda, tc_compra=lote["tc_compra"],
                        fecha_compra=compra_original, traspaso_id=tid,
                        notes=(f"Llegó desde otro broker tuyo el {_ddmmaaaa(fecha)} · compra "
                               f"original del {_ddmmaaaa(compra_original)}")))
                    recetas.append({"origen": "importado", "lote_id": lote["id"], "broker": origen,
                                    "broker_destino": destino,
                                    "fila_origen": {"batch_id": origen_fila["batch_id"],
                                                    "raw_row_id": origen_fila["raw_row_id"]},
                                    "cantidad": take, "invested": inv, "commissions": com,
                                    "parcial": False,
                                    "foto": {c: lote[c] for c in (
                                        "id", "broker", "asset", "quantity", "invested",
                                        "commissions", "buy_price", "entry_date", "currency",
                                        "tc_compra", "asset_type", "notes")}})
                tipo = compras[0].asset_type
                v_ars = q * precio
                v_usd = v_ars / tc_venta
                patas = dict(asset_symbol=asset, asset_type=tipo, quantity=q, unit_price=precio,
                             gross_amount=None, fees=0.0, currency="ARS", traspaso_id=tid,
                             valor_usd=v_usd, valor_ars=v_ars, costo_usd=c_usd,
                             costo_nativo=c_nat)
                filas_a = [
                    NormalizedTx(row_index=-49999, date=fecha, broker=origen,
                                 operation_type=OP_SELL, asset_symbol=asset, asset_type=tipo,
                                 quantity=q, unit_price=0.0, gross_amount=0.0, fees=0.0,
                                 currency="ARS", transfer_out=True, traspaso_id=tid,
                                 costo_nativo=inv_sin_com,
                                 notes=(f"Traspaso a otro broker tuyo el {_ddmmaaaa(fecha)} — "
                                        "sale al costo, sin ganancia")),
                    NormalizedTx(row_index=-49998, date=fecha, broker=origen,
                                 operation_type=OP_TRASPASO_SALIDA,
                                 notes=f"Salieron {q:g} {asset} a otro broker tuyo (valor del día)",
                                 **patas),
                ]
                gasto_usd = 0.0
                if gasto:
                    gasto_usd = gasto / tc_venta
                    filas_a.append(NormalizedTx(
                        row_index=-49997, date=fecha, broker=origen, operation_type=OP_FEE,
                        gross_amount=gasto, fees=0.0, currency="ARS", traspaso_id=tid,
                        valor_usd=gasto_usd,
                        notes=f"Costo del pase de {asset} a otro broker tuyo"))
                filas_b = compras + [NormalizedTx(
                    row_index=-49999 + len(compras), date=fecha, broker=destino,
                    operation_type=OP_TRASPASO_ENTRADA,
                    notes=f"Entraron {q:g} {asset} desde otro broker tuyo (valor del día)",
                    **patas)]

                antes = main._foto_contable(conn, self.uid)
                sid_a = pl.store_preview_txs(conn, self.uid, broker=origen,
                                             parser_format=traspaso_a_mano.FORMATO,
                                             file_name="Pase entre brokers", txs=filas_a)
                sid_b = pl.store_preview_txs(conn, self.uid, broker=destino,
                                             parser_format=traspaso_a_mano.FORMATO,
                                             file_name="Pase entre brokers", txs=filas_b)
                receta = {"v": 1, "broker_origen": origen, "broker_destino": destino,
                          "fx_version": "v2" if hist else "v1", "lotes": recetas,
                          "gasto": ({"broker": origen, "monto": gasto, "moneda": "ARS"}
                                    if gasto else None),
                          "precio": {"unitario": precio, "moneda": "ARS",
                                     "fuente": "precio_a_mano", "fecha": fecha},
                          "valor_nativo": v_ars, "valor_usd": v_usd, "valor_ars": v_ars,
                          "costo_usd": c_usd, "tc_pase": tc_venta, "tc_venta": tc_venta,
                          "brokers_usd_creados": [], "precio_cargado_en_destino": None}
                conn.execute(
                    "INSERT INTO traspasos_a_mano (id, user_id, lote_salida, lote_entrada, fecha, "
                    "asset, cantidad, moneda, receta_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tid, self.uid, sid_a, sid_b, fecha, asset, q, "ARS", json.dumps(receta)))
                for sid in (sid_a, sid_b):
                    txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=sid)
                    r = ps.persist_batch(conn, uid=self.uid, batch_id=sid, txs=txs,
                                         raw_row_ids_by_index=raw, helpers=main._import_helpers)
                    self.assertEqual(r["skipped_rows"], [], r)
                main._cascade_after_movement_delete(conn, self.uid, fecha, {origen, destino},
                                                    antes=antes)
        finally:
            conn.close()
        return {"traspaso_id": tid, "lote_salida": sid_a, "lote_entrada": sid_b,
                "V": v_usd, "V_ars": v_ars, "C": c_usd, "C_nativo": c_nat,
                "gasto_usd": gasto_usd, "cantidad": q}

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
