"""La historia a mercado cuenta lo que la persona tenía: tipo mezclado, venta a mano y pases.

La curva de «Evolución» de una cuenta importada sale de reconstruir, para cada fin
de mes cerrado, qué títulos había en cada broker y cuánto valían
(`scripts/backfill_historical_mtm.py`). Esta prueba (F.2 #45 de la especificación
de «Mover a otro broker», etapa E3) fija tres cosas que esa reconstrucción contaba
mal, dos de ellas desde antes de los pases:

  · TIPO MEZCLADO. Las compras y las ventas de un mismo broker se agrupaban también
    por tipo de activo. Una venta que llegaba con otro tipo (Bull Market, PPI e IEB
    dejan OTHER; Cocos y Balanz mandan CEDEAR o STOCK) caía en un grupo aparte, daba
    cantidad negativa y se descartaba: la tenencia no bajaba nunca. Medido abajo:
    10 AAPL comprados, 4 vendidos, y la foto de junio valía 10.
  · VENTA A MANO DE UN LOTE IMPORTADO. La venta a mano no escribe el registro de lo
    importado: la compra seguía ahí y la curva valuaba a mercado, para siempre,
    títulos que la persona ya había vendido.
  · PASES ENTRE BROKERS. La salida de un pase se lleva el costo de SUS lotes (no el
    promedio); un lote que llegó por un pase no estaba en el broker nuevo antes de
    llegar; un lote cargado a mano que salió por un pase sí estaba en el viejo hasta
    ese día.

CAMINO. Las filas importadas entran por el mismo camino que el confirm después de
leer el archivo (`store_preview_txs` → `load_session_for_confirm` → `persist_batch`
→ `rebuild_fifo_after_import` → `_recalc_pnl_realized_from_ops`); se usa ese camino
y no `POST /api/imports/preview` porque el tipo de activo de cada fila lo decide el
lector de cada broker, y acá se necesita elegirlo. La venta a mano, su borrado y el
alta de un lote a mano van por HTTP con un token real (`main.create_token`). La
historia se arma con la misma función que corre en producción después de cada
pedido (`main._reconstruir_mtm`). Lo único reemplazado es lo que sale a internet:
los cierres de Yahoo (fijos y sabidos) y la lista de bonos de data912 (vacía).

LOS PASES. Todavía no hay endpoint que haga un pase (llega en E6): las filas del pase
se escriben como las va a escribir (sección A.6), por el mismo camino del confirm, y
la fila de `traspasos_a_mano` con su receta (A.2) se inserta como la va a insertar
`aplicar_plan`. Cuando exista el endpoint, `test_mover_entre_brokers.py` repite estos
casos por HTTP.

Corre con: cd backend && python3 -m pytest tests/test_holdings_asof_tipo_mezclado_y_venta_manual.py
"""
import json
import os
import secrets
import sys
import time
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from importing import pipeline as pl  # noqa: E402
from importing import persister as ps  # noqa: E402
from importing import rebuild as rb  # noqa: E402
from importing import traspaso_a_mano as tam  # noqa: E402
from importing.schema import (  # noqa: E402
    NormalizedTx, OP_BUY, OP_SELL, OP_DEPOSIT, OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA,
)


def _meses(desde_anio=2025, hasta_anio=2030):
    for y in range(desde_anio, hasta_anio + 1):
        for m in range(1, 13):
            yield f"{y}-{m:02d}"


# Cierre de fin de mes, fijo y sabido: AAPL arranca en 200 en enero de 2025 y sube
# 10 por mes; MSFT arranca en 300 y sube 5. Hasta 2030, así ningún mes cerrado de
# los próximos años queda sin precio.
PRECIOS = {
    "AAPL": {ym: 200.0 + 10 * n for n, ym in enumerate(_meses())},
    "MSFT": {ym: 300.0 + 5 * n for n, ym in enumerate(_meses())},
    # Una obligación negociable cuyo cierre llega por cada 100 nominales: 1,0 cuando
    # cada nominal costó 100 (el 1 %). La banda de renta fija lo descarta; la general no.
    "ZZON": {ym: 1.0 for ym in _meses()},
}


def _fila(i, fecha, broker, op, activo=None, qty=None, precio=None, monto=None, *,
          tipo="STOCK", moneda="USD", comision=0.0, **extra):
    return NormalizedTx(row_index=i, date=fecha, broker=broker, operation_type=op,
                        asset_symbol=activo, asset_type=tipo if activo else None,
                        quantity=qty, unit_price=precio, gross_amount=monto, fees=comision,
                        currency=moneda, **extra)


class _Cuenta(unittest.TestCase):
    """Una cuenta con dos brokers en dólares (IBKR y Schwab)."""

    BROKERS = (("IBKR", "USDT"), ("Schwab", "USDT"))

    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"historia-pases-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        for nombre, moneda in self.BROKERS:
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, nombre, moneda))
        self.conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        _data912 = mock.patch.object(main, "_fetch_data912_bonds", return_value={})
        _data912.start()
        self.addCleanup(_data912.stop)
        _orig = bf._fetch_monthly_close
        self.addCleanup(setattr, bf, "_fetch_monthly_close", _orig)
        bf._fetch_monthly_close = lambda pk, start: dict(PRECIOS.get(pk, {}))
        bf._HIST_CACHE.clear()
        self.addCleanup(bf._HIST_CACHE.clear)

    def tearDown(self):
        self._esperar_la_reconstruccion()
        self.conn.close()

    # ── el camino del confirm ──
    def _confirmar(self, broker, txs, formato="rendi_generic", *, rebuild=True):
        """Lo que hace `import_confirm` después de leer el archivo."""
        with self.conn:
            sid = pl.store_preview_txs(self.conn, self.uid, broker=broker, parser_format=formato,
                                       file_name="historia.csv", txs=txs)
        with self.conn:
            txs_db, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            r = ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs_db,
                                 raw_row_ids_by_index=raw, helpers=main._import_helpers)
        self.assertEqual(r["skipped_rows"], [], r)
        if rebuild:
            with self.conn:
                rb.rebuild_fifo_after_import(self.conn, self.uid, sid,
                                             tc_blue=ps._read_tc_blue(self.conn, self.uid))
        with self.conn:
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    def _pase(self, *, fecha, de, a, activo, salida=(), llegadas=(), lotes_receta=(),
              valor_usd, costo_usd):
        """Un pase como lo va a escribir `aplicar_plan` (A.6/A.7/C.7): un lote de import
        confirmado por broker, sin rebuild, y su fila en `traspasos_a_mano`.

        `salida`: [(cantidad, costo_sin_comisiones)] de lotes IMPORTADOS que salen de A.
        `llegadas`: [(cantidad, precio, monto, fecha_compra)] que llegan a B.
        `lotes_receta`: los lotes de la receta (los cargados a mano llevan su foto)."""
        pid = secrets.token_hex(16)
        dd = f"{fecha[8:10]}/{fecha[5:7]}/{fecha[:4]}"
        q = sum(c for c, *_ in llegadas)
        filas_a, k = [], 0
        for cant, costo in salida:
            filas_a.append(_fila(-49999 + k, fecha, de, OP_SELL, activo, cant, 0.0, 0.0,
                                 transfer_out=True, traspaso_id=pid, costo_nativo=costo,
                                 notes=f"Traspaso a otro broker tuyo el {dd} — sale al costo, "
                                       f"sin ganancia"))
            k += 1
        filas_a.append(_fila(-49999 + k, fecha, de, OP_TRASPASO_SALIDA, activo, q, valor_usd / q,
                             None, traspaso_id=pid, valor_usd=valor_usd, valor_ars=valor_usd * 1400,
                             costo_usd=costo_usd, costo_nativo=costo_usd,
                             notes=f"Salieron {q:g} {activo} a otro broker tuyo (valor del día)"))
        filas_b, k = [], 0
        for cant, precio, monto, fecha_compra in llegadas:
            fc = f"{fecha_compra[8:10]}/{fecha_compra[5:7]}/{fecha_compra[:4]}"
            filas_b.append(_fila(-49999 + k, fecha, a, OP_BUY, activo, cant, precio, monto,
                                 traspaso_id=pid, fecha_compra=fecha_compra,
                                 notes=f"Llegó desde otro broker tuyo el {dd} · compra original "
                                       f"del {fc}"))
            k += 1
        filas_b.append(_fila(-49999 + k, fecha, a, OP_TRASPASO_ENTRADA, activo, q, valor_usd / q,
                             None, traspaso_id=pid, valor_usd=valor_usd, valor_ars=valor_usd * 1400,
                             costo_usd=costo_usd, costo_nativo=costo_usd,
                             notes=f"Entraron {q:g} {activo} desde otro broker tuyo (valor del día)"))
        lote_a = self._confirmar(de, filas_a, tam.FORMATO, rebuild=False)
        lote_b = self._confirmar(a, filas_b, tam.FORMATO, rebuild=False)
        receta = {"v": 1, "broker_origen": de, "broker_destino": a, "fx_version": "v2",
                  "lotes": list(lotes_receta), "gasto": None,
                  "valor_usd": valor_usd, "costo_usd": costo_usd, "brokers_usd_creados": [],
                  "precio_cargado_en_destino": None}
        with self.conn:
            self.conn.execute(
                "INSERT INTO traspasos_a_mano (id, user_id, lote_salida, lote_entrada, fecha, "
                "asset, cantidad, moneda, receta_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, self.uid, lote_a, lote_b, fecha, activo, q, "USD", json.dumps(receta)))
        return pid, lote_a, lote_b

    # ── HTTP con token real ──
    def _esperar_la_reconstruccion(self):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción de fondo no terminó en 60 s")

    def _ok(self, r):
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_la_reconstruccion()
        return r.json()

    def _vender_a_mano(self, broker, activo, cantidad, precio, fecha):
        self._ok(self.http.post("/api/positions/sell", headers=self.h, json={
            "broker": broker, "asset": activo, "quantity": cantidad, "exit_price": precio,
            "date": fecha, "currency": "USD"}))

    # ── lo que se mira ──
    def _tenencia(self, fecha):
        """{(broker, activo): (cantidad, costo)} que la reconstrucción ve a esa fecha."""
        return {(h["broker"], h["asset"]): (round(h["quantity"], 6), round(h["invested"], 6))
                for h in bf._holdings_asof(self.conn, self.uid, fecha)}

    def _reconstruir(self):
        self._esperar_la_reconstruccion()
        res = main._reconstruir_mtm(self.uid)
        self.assertTrue(res.get("reconstruida"), res)

    def _fotos(self):
        """{AAAA-MM: valor} de las fotos reconstruidas."""
        return {r["date"][:7]: round(r["total_value"], 2) for r in self.conn.execute(
            "SELECT date, total_value FROM snapshots WHERE user_id=? AND source=?",
            (self.uid, bf.MTM_SOURCE)).fetchall()}

    def _caja(self, broker):
        r = self.conn.execute("SELECT COALESCE(SUM(invested),0) c FROM positions "
                              "WHERE user_id=? AND broker=? AND is_cash=1",
                              (self.uid, broker)).fetchone()
        return round(float(r["c"] or 0), 6)


# ═════════════════════════════════════════════════════════════════════════════
class TipoMezcladoEnElMismoBroker(_Cuenta):
    """10 AAPL comprados con tipo OTHER (un lector que no lo informa) y 4 vendidos con
    tipo STOCK (otro archivo). La venta tiene que bajar la tenencia."""

    def setUp(self):
        super().setUp()
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 200.0, 2000.0, tipo="OTHER"),
        ])
        self._confirmar("IBKR", [
            _fila(0, "2025-06-10", "IBKR", OP_SELL, "AAPL", 4.0, 230.0, 920.0, tipo="STOCK"),
        ])

    def test_control_la_cartera_ya_lo_tenia_bien(self):
        """`positions` (el persister y el rebuild consumen por activo, no por tipo) ya
        tenía 6: lo que estaba mal era sólo la historia."""
        r = self.conn.execute("SELECT SUM(quantity) q FROM positions WHERE user_id=? "
                              "AND asset='AAPL' AND is_cash=0", (self.uid,)).fetchone()
        self.assertAlmostEqual(r["q"], 6.0)
        self.assertAlmostEqual(self._caja("IBKR"), 8920.0)

    def test_la_venta_con_otro_tipo_baja_la_tenencia(self):
        self.assertEqual(self._tenencia("2025-05-31"), {("IBKR", "AAPL"): (10.0, 2000.0)})
        self.assertEqual(self._tenencia("2025-06-30"), {("IBKR", "AAPL"): (6.0, 1200.0)})

    def test_el_tipo_sale_de_las_compras(self):
        h = bf._holdings_asof(self.conn, self.uid, "2025-06-30")
        self.assertEqual([x["asset_type"] for x in h], ["OTHER"])

    def test_la_foto_vale_la_caja_mas_los_6_que_quedan(self):
        """Toda la cuenta sale del archivo: la foto es la caja de ese fin de mes más
        la tenencia a su cierre. Antes, junio valía 8.920 + 10 × 260."""
        self._reconstruir()
        fotos = self._fotos()
        for ym in ("2025-03", "2025-04", "2025-05"):
            self.assertAlmostEqual(fotos[ym], 8000.0 + 10 * PRECIOS["AAPL"][ym], places=2, msg=ym)
        for ym in ("2025-06", "2025-07", "2025-12", "2026-06"):
            self.assertAlmostEqual(fotos[ym], 8920.0 + 6 * PRECIOS["AAPL"][ym], places=2, msg=ym)


# ═════════════════════════════════════════════════════════════════════════════
class ElTipoLoDiceLaCompraMasNueva(_Cuenta):
    """Con el tipo que no parte el grupo, ¿cuál se usa si las compras dicen tipos
    distintos? `MAX` compara texto y OTHER le ganaba a ON, BOND, LETRA y CEDEAR.

    El caso real: dos compras de una ON que el lector dejó en OTHER, la primera ya
    vendida, y el usuario corrige el tipo del lote que le queda («Editar posición» →
    ON). La corrección llega sólo a la compra del lote abierto (`_cambiar_tipo_del_lote`);
    la vendida sigue en OTHER."""

    def setUp(self):
        super().setUp()
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "ZZON", 10.0, 100.0, 1000.0, tipo="OTHER"),
            _fila(2, "2025-04-04", "IBKR", OP_BUY, "ZZON", 10.0, 100.0, 1000.0, tipo="OTHER"),
            _fila(3, "2025-05-05", "IBKR", OP_SELL, "ZZON", 10.0, 100.0, 1000.0, tipo="OTHER"),
        ])
        lote = dict(self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset='ZZON' AND is_cash=0",
            (self.uid,)).fetchone())
        self.assertEqual((lote["quantity"], lote["entry_date"]), (10.0, "2025-04-04"))
        self._ok(self.http.put(f"/api/positions/{lote['id']}", headers=self.h, json={
            "broker": "IBKR", "asset": "ZZON", "buy_price": 100.0, "quantity": 10,
            "invested": 1000.0, "commissions": 0, "entry_date": "2025-04-04",
            "currency": "USD", "asset_type": "ON"}))

    def test_control_la_correccion_llego_solo_a_la_compra_abierta(self):
        tipos = [r["asset_type"] for r in self.conn.execute(
            "SELECT n.asset_type FROM import_normalized_tx n JOIN import_batches b "
            "ON b.id=n.batch_id WHERE b.user_id=? AND n.operation_type='BUY' ORDER BY n.date",
            (self.uid,)).fetchall()]
        self.assertEqual(tipos, ["OTHER", "ON"])

    def test_la_tenencia_es_una_on(self):
        h = bf._holdings_asof(self.conn, self.uid, "2025-06-30")
        self.assertEqual([(x["asset"], x["asset_type"], round(x["quantity"], 6)) for x in h],
                         [("ZZON", "ON", 10.0)])

    def test_y_el_precio_por_100_nominales_no_se_confia(self):
        """El cierre llega por 100 nominales (1 % del valor). Con la banda de renta fija
        se descarta y la ON vale su costo; tomada por OTHER se confiaba y la foto
        mostraba una caída del 99 % que nunca existió."""
        self._reconstruir()
        fotos = self._fotos()
        for ym in ("2025-06", "2025-12", "2026-06"):
            self.assertAlmostEqual(fotos[ym], 9000.0 + 1000.0, places=2, msg=ym)

    def test_entre_dos_tipos_que_dicen_algo_gana_la_compra_mas_nueva(self):
        """La compra más nueva es la del lote que sigue abierto (el FIFO vende primero
        la vieja). STOCK vendida y CEDEAR abierta: CEDEAR (MAX decía STOCK)."""
        self._confirmar("IBKR", [
            _fila(0, "2025-03-10", "IBKR", OP_BUY, "MSFT", 2.0, 300.0, 600.0, tipo="STOCK"),
            _fila(1, "2025-04-10", "IBKR", OP_BUY, "MSFT", 2.0, 300.0, 600.0, tipo="CEDEAR"),
            _fila(2, "2025-05-10", "IBKR", OP_SELL, "MSFT", 2.0, 320.0, 640.0, tipo="STOCK"),
        ])
        tipos = {x["asset"]: x["asset_type"]
                 for x in bf._holdings_asof(self.conn, self.uid, "2025-06-30")}
        self.assertEqual(tipos["MSFT"], "CEDEAR")
        # Antes de la segunda compra, el único tipo es el de la primera.
        tipos = {x["asset"]: x["asset_type"]
                 for x in bf._holdings_asof(self.conn, self.uid, "2025-03-31")}
        self.assertEqual(tipos["MSFT"], "STOCK")


# ═════════════════════════════════════════════════════════════════════════════
class VentaAManoDeDosLotesConCostosDistintos(_Cuenta):
    """IBKR compró 10 AAPL a 100 y 10 a 300. La venta a mano consume los de 100 (FIFO):
    lo que queda tiene que llevar el costo de SUS lotes, no el promedio (200)."""

    def setUp(self):
        super().setUp()
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 100.0, 1000.0),
            _fila(2, "2025-04-04", "IBKR", OP_BUY, "AAPL", 10.0, 300.0, 3000.0),
        ])

    def test_vende_4_del_primer_lote(self):
        self._vender_a_mano("IBKR", "AAPL", 4.0, 230.0, "2025-06-10")
        self.assertEqual(self._tenencia("2025-06-09"), {("IBKR", "AAPL"): (20.0, 4000.0)})
        # 6 a 100 + 10 a 300 = 3.600 (restado al promedio daría 3.200)
        self.assertEqual(self._tenencia("2025-06-30"), {("IBKR", "AAPL"): (16.0, 3600.0)})

    def test_vende_12_y_cruza_al_segundo_lote(self):
        """La venta a mano deja una 'Venta' por lote consumido, cada una con su foto."""
        self._vender_a_mano("IBKR", "AAPL", 12.0, 230.0, "2025-06-10")
        # quedan 8 a 300
        self.assertEqual(self._tenencia("2025-06-30"), {("IBKR", "AAPL"): (8.0, 2400.0)})


# ═════════════════════════════════════════════════════════════════════════════
class VentaAManoDeUnLoteImportado(_Cuenta):
    """10 AAPL importados a 200; el 10/06/2025 la persona vende 4 a mano a 230 desde
    Cartera. La historia los saca desde la fecha de la venta, y si la borra, vuelven."""

    def setUp(self):
        super().setUp()
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 200.0, 2000.0),
        ])
        self._vender_a_mano("IBKR", "AAPL", 4.0, 230.0, "2025-06-10")
        self.venta = self.conn.execute(
            "SELECT id, undo_meta_json FROM operations WHERE user_id=? AND op_type='Venta'",
            (self.uid,)).fetchone()

    def test_control_la_venta_es_a_mano_y_el_lote_es_del_registro(self):
        """Sin esto la prueba no mide lo que dice: la venta no tiene vínculo con el
        registro y el lote que consumió sí."""
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM import_op_links WHERE operation_id=?", (self.venta["id"],)).fetchone())
        lote = json.loads(self.venta["undo_meta_json"])["lot"]
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM import_op_links WHERE position_id=?", (lote["id"],)).fetchone())
        self.assertAlmostEqual(lote["consumed"], 4.0)

    def test_la_historia_los_saca_desde_la_fecha_de_la_venta(self):
        self.assertEqual(self._tenencia("2025-06-09"), {("IBKR", "AAPL"): (10.0, 2000.0)})
        self.assertEqual(self._tenencia("2025-06-10"), {("IBKR", "AAPL"): (6.0, 1200.0)})
        self.assertEqual(self._tenencia("2025-12-31"), {("IBKR", "AAPL"): (6.0, 1200.0)})

    def test_la_foto_ya_no_valua_lo_vendido(self):
        """La caja la cuenta la contabilidad (la venta es a mano): 10.000 aportados,
        +120 de la venta. Junio valía, antes, 10.120 + 10 × (260 − 200)."""
        self._reconstruir()
        fotos = self._fotos()
        for ym in ("2025-03", "2025-05"):
            self.assertAlmostEqual(fotos[ym], 10000.0 + 10 * (PRECIOS["AAPL"][ym] - 200), places=2,
                                   msg=ym)
        for ym in ("2025-06", "2025-09", "2026-06"):
            self.assertAlmostEqual(fotos[ym], 10120.0 + 6 * (PRECIOS["AAPL"][ym] - 200), places=2,
                                   msg=ym)

    def test_borrar_la_venta_la_devuelve_a_la_historia(self):
        self._reconstruir()
        self._ok(self.http.delete(f"/api/operations/{self.venta['id']}", headers=self.h))
        self.assertEqual(self._tenencia("2025-12-31"), {("IBKR", "AAPL"): (10.0, 2000.0)})
        self._reconstruir()
        fotos = self._fotos()
        for ym in ("2025-06", "2026-06"):
            self.assertAlmostEqual(fotos[ym], 10000.0 + 10 * (PRECIOS["AAPL"][ym] - 200), places=2,
                                   msg=ym)

    def test_la_venta_a_mano_de_un_lote_a_mano_no_toca_el_registro(self):
        """Un lote cargado a mano nunca estuvo en el registro: venderlo no resta nada."""
        self._ok(self.http.post("/api/positions", headers=self.h, json={
            "broker": "IBKR", "asset": "MSFT", "quantity": 5, "buy_price": 300,
            "invested": 1500, "entry_date": "2025-04-01", "currency": "USD"}))
        self._vender_a_mano("IBKR", "MSFT", 5.0, 320.0, "2025-07-01")
        self.assertEqual(
            [(b, a) for b, a, *_ in bf._ventas_a_mano_de_lotes_del_registro(
                self.conn, self.uid, "2025-12-31")],
            [("IBKR", "AAPL")])


# ═════════════════════════════════════════════════════════════════════════════
class LaSalidaDeUnPaseSeLlevaSuCosto(_Cuenta):
    """IBKR compró 10 AAPL a 100 y 10 a 300; el pase del 10/06/2025 lleva a Schwab los
    10 más viejos (los de 100). Lo que queda en IBKR cuesta 3.000, no el promedio."""

    def setUp(self):
        super().setUp()
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 100.0, 1000.0),
            _fila(2, "2025-04-04", "IBKR", OP_BUY, "AAPL", 10.0, 300.0, 3000.0),
        ])
        self.pase, _, _ = self._pase(
            fecha="2025-06-10", de="IBKR", a="Schwab", activo="AAPL",
            salida=[(10.0, 1000.0)], llegadas=[(10.0, 100.0, 1000.0, "2025-03-04")],
            valor_usd=2550.0, costo_usd=1000.0)

    def test_control_la_cartera(self):
        lotes = {r["broker"]: (r["quantity"], r["invested"]) for r in self.conn.execute(
            "SELECT broker, quantity, invested FROM positions WHERE user_id=? AND is_cash=0",
            (self.uid,)).fetchall()}
        self.assertEqual(lotes, {"IBKR": (10.0, 3000.0), "Schwab": (10.0, 1000.0)})

    def test_antes_del_pase_todo_en_ibkr(self):
        self.assertEqual(self._tenencia("2025-06-09"), {("IBKR", "AAPL"): (20.0, 4000.0)})

    def test_despues_cada_broker_con_el_costo_de_sus_lotes(self):
        self.assertEqual(self._tenencia("2025-06-30"), {("IBKR", "AAPL"): (10.0, 3000.0),
                                                        ("Schwab", "AAPL"): (10.0, 1000.0)})

    def test_deshecho_el_pase_vuelve_todo_a_ibkr(self):
        """Deshacer deja los dos lotes del pase en `reverted` (C.8): TX_VIVAS los saca."""
        with self.conn:
            self.conn.execute("UPDATE import_batches SET status='reverted' WHERE id IN "
                              "(SELECT lote_salida FROM traspasos_a_mano WHERE id=? UNION "
                              " SELECT lote_entrada FROM traspasos_a_mano WHERE id=?)",
                              (self.pase, self.pase))
        self.assertEqual(self._tenencia("2025-06-30"), {("IBKR", "AAPL"): (20.0, 4000.0)})


# ═════════════════════════════════════════════════════════════════════════════
class LoQueElRegistroNoVeConPases(_Cuenta):
    """`_tenencia_no_vista`: lo que la reconstrucción no ve en el registro y cuenta al
    costo para no declarar una cobertura que no tiene. Con pases, cada lote se cuenta
    UNA vez y en el broker donde estaba ese día."""

    def _no_visto(self, fecha):
        vistos = {(h["broker"], h["asset"]): float(h["quantity"] or 0)
                  for h in bf._holdings_asof(self.conn, self.uid, fecha)}
        costo, afirmable = bf._tenencia_no_vista(self.conn, self.uid, fecha, vistos)
        return round(costo, 6), afirmable

    def _importado_y_pasado(self):
        """10 AAPL importados en IBKR el 04/03/2025 que pasan a Schwab el 10/06/2025."""
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 100.0, 1000.0),
        ])
        return self._pase(fecha="2025-06-10", de="IBKR", a="Schwab", activo="AAPL",
                          salida=[(10.0, 1000.0)], llegadas=[(10.0, 100.0, 1000.0, "2025-03-04")],
                          valor_usd=2550.0, costo_usd=1000.0)

    def _a_mano_y_pasado(self):
        """5 MSFT cargados a mano en IBKR el 01/02/2025 a 300, que pasan a Schwab el
        10/06/2025: el lote sale de `positions` de IBKR (C.7) y su foto queda en la receta."""
        self._ok(self.http.post("/api/positions", headers=self.h, json={
            "broker": "IBKR", "asset": "MSFT", "quantity": 5, "buy_price": 300,
            "invested": 1500, "entry_date": "2025-02-01", "currency": "USD"}))
        foto = dict(self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset='MSFT' AND is_cash=0",
            (self.uid,)).fetchone())
        with self.conn:
            self.conn.execute("DELETE FROM positions WHERE id=?", (foto["id"],))
        lote = {"origen": "a_mano", "lote_id": foto["id"], "broker": "IBKR",
                "broker_destino": "Schwab", "fila_origen": None, "cantidad": 5.0,
                "invested": 1500.0, "commissions": 0.0, "parcial": False, "foto": foto}
        return self._pase(fecha="2025-06-10", de="IBKR", a="Schwab", activo="MSFT",
                          llegadas=[(5.0, 300.0, 1500.0, "2025-02-01")], lotes_receta=[lote],
                          valor_usd=1900.0, costo_usd=1500.0)

    # (a) el lote que llegó no estaba en Schwab antes de llegar
    def test_el_lote_importado_que_llego_no_se_cuenta_dos_veces(self):
        self._importado_y_pasado()
        lote = self.conn.execute("SELECT entry_date, en_broker_desde FROM positions "
                                 "WHERE user_id=? AND broker='Schwab'", (self.uid,)).fetchone()
        self.assertEqual(tuple(lote), ("2025-03-04", "2025-06-10"))
        # En abril estaba en IBKR, y el registro lo valúa ahí: nada queda sin ver.
        # Antes se contaba también en Schwab, al costo: 1.000 de más.
        self.assertEqual(self._no_visto("2025-04-30"), (0.0, True))
        self.assertEqual(self._no_visto("2025-06-30"), (0.0, True))

    # (b) el lote cargado a mano estaba en IBKR hasta el día del pase
    def test_el_lote_a_mano_que_salio_se_cuenta_en_su_broker_hasta_el_pase(self):
        pid, lote_a, _ = self._a_mano_y_pasado()
        salieron = tam.lotes_a_mano_que_salieron(self.conn, self.uid)
        self.assertEqual(len(salieron), 1)
        self.assertEqual({k: salieron[0][k] for k in ("broker", "asset", "entry_date",
                                                     "fecha_pase", "cantidad", "invested",
                                                     "currency", "traspaso_id", "k")},
                         {"broker": "IBKR", "asset": "MSFT", "entry_date": "2025-02-01",
                          "fecha_pase": "2025-06-10", "cantidad": 5.0, "invested": 1500.0,
                          "currency": "USD", "traspaso_id": pid, "k": 0})
        self.assertEqual(self._no_visto("2025-01-31"), (0.0, True))     # no lo había comprado
        self.assertEqual(self._no_visto("2025-03-31"), (1500.0, True))  # en IBKR, una sola vez
        self.assertEqual(self._no_visto("2025-06-30"), (0.0, True))     # ya en Schwab: lo ve el registro

    def test_pase_deshecho_o_broker_de_origen_borrado_no_cuenta_el_lote(self):
        pid, lote_a, _ = self._a_mano_y_pasado()
        with self.conn:
            self.conn.execute("UPDATE import_batches SET status='reverted' WHERE id=?", (lote_a,))
        self.assertEqual(tam.lotes_a_mano_que_salieron(self.conn, self.uid), [])
        with self.conn:
            self.conn.execute("UPDATE import_batches SET status='confirmed' WHERE id=?", (lote_a,))
            self.conn.execute("UPDATE traspasos_a_mano SET deshecho_at=datetime('now') "
                              "WHERE id=?", (pid,))
        self.assertEqual(tam.lotes_a_mano_que_salieron(self.conn, self.uid), [])

    # (c) la venta en Schwab de un lote que llegó por un pase
    def test_la_venta_del_lote_que_llego_se_cuenta_desde_la_llegada(self):
        self._importado_y_pasado()
        self._vender_a_mano("Schwab", "AAPL", 10.0, 280.0, "2025-08-05")
        self.assertEqual(tam.llegadas_por_lote(self.conn, self.uid),
                         {("Schwab", "AAPL", "2025-03-04"): "2025-06-10"})
        venta = self.conn.execute("SELECT broker, entry_date, date FROM operations "
                                  "WHERE user_id=? AND op_type='Venta'", (self.uid,)).fetchone()
        self.assertEqual(tuple(venta), ("Schwab", "2025-03-04", "2025-08-05"))
        # Abril: el lote estaba en IBKR (lo ve el registro). Antes, la venta de Schwab
        # se contaba además desde la compra original: 1.000 de más.
        self.assertEqual(self._no_visto("2025-04-30"), (0.0, True))
        # Julio: en Schwab, lo ve el registro. Septiembre: ya vendido.
        self.assertEqual(self._no_visto("2025-07-31"), (0.0, True))
        self.assertEqual(self._tenencia("2025-09-30"), {})
        self.assertEqual(self._no_visto("2025-09-30"), (0.0, True))


class LlegadaAUnaPataDeLaFamilia(LoQueElRegistroNoVeConPases):
    """El lote llega a la pata en dólares de Balanz («Balanz · USD»). La llegada se
    anota por la cuenta RAÍZ («Balanz»: un lote de la familia pudo llegar a una pata y
    venderse desde la otra), y la venta se busca por la raíz de su pata."""

    BROKERS = (("IBKR", "USDT"), ("Balanz", "ARS"), ("Balanz · USD", "USDT"))

    def setUp(self):
        super().setUp()
        with self.conn:
            self.conn.execute(
                "UPDATE brokers SET parent_broker_id=(SELECT id FROM brokers WHERE user_id=? "
                "AND name='Balanz') WHERE user_id=? AND name='Balanz · USD'", (self.uid, self.uid))

    def test_la_llegada_se_anota_en_la_cuenta_raiz(self):
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 100.0, 1000.0),
        ])
        self._pase(fecha="2025-06-10", de="IBKR", a="Balanz · USD", activo="AAPL",
                   salida=[(10.0, 1000.0)], llegadas=[(10.0, 100.0, 1000.0, "2025-03-04")],
                   valor_usd=2550.0, costo_usd=1000.0)
        self.assertEqual(tam.llegadas_por_lote(self.conn, self.uid),
                         {("Balanz", "AAPL", "2025-03-04"): "2025-06-10"})
        # La venta, con la forma que deja `sell_position_fifo`, anotada en la pata.
        with self.conn:
            self.conn.execute(
                "INSERT INTO operations (user_id, date, broker, asset, op_type, entry_price, "
                "exit_price, quantity, pnl_usd, entry_date, currency) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (self.uid, "2025-08-05", "Balanz · USD", "AAPL", "Venta", 100.0, 280.0, 10.0,
                 1800.0, "2025-03-04", "USD"))
        # Abril: el lote estaba en IBKR. Sin buscar por la raíz, la venta no
        # encontraba su llegada y se contaba también desde marzo, al costo.
        self.assertEqual(self._no_visto("2025-04-30"), (0.0, True))

    # Los casos de la clase madre no se repiten acá.
    test_el_lote_importado_que_llego_no_se_cuenta_dos_veces = None
    test_el_lote_a_mano_que_salio_se_cuenta_en_su_broker_hasta_el_pase = None
    test_pase_deshecho_o_broker_de_origen_borrado_no_cuenta_el_lote = None
    test_la_venta_del_lote_que_llego_se_cuenta_desde_la_llegada = None


# ═════════════════════════════════════════════════════════════════════════════
class LaHuellaVeLosPases(_Cuenta):
    """La historia se rehace cuando cambia lo que la reconstrucción lee
    (`huella_de_entrada`). Un pase, su deshacer y la llegada de un lote cambian la
    historia: tienen que cambiar la huella."""

    def _huella(self):
        from fechas import hoy_art_date
        return bf.huella_de_entrada(self.conn, self.uid, hoy_art_date())

    def test_motor_version_4(self):
        self.assertEqual(bf.MOTOR_VERSION, 4)

    def test_pase_y_deshacer_cambian_la_huella(self):
        self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 100.0, 1000.0),
        ])
        antes = self._huella()
        pid, _, _ = self._pase(fecha="2025-06-10", de="IBKR", a="Schwab", activo="AAPL",
                               salida=[(10.0, 1000.0)],
                               llegadas=[(10.0, 100.0, 1000.0, "2025-03-04")],
                               valor_usd=2550.0, costo_usd=1000.0)
        con_pase = self._huella()
        self.assertNotEqual(antes, con_pase)
        with self.conn:
            self.conn.execute("UPDATE traspasos_a_mano SET deshecho_at=datetime('now') "
                              "WHERE id=?", (pid,))
        self.assertNotEqual(self._huella(), con_pase)

    def test_adoptar_una_cuenta_como_hija_cambia_la_huella(self):
        """De qué cuenta es cada pata decide si una «· USD» se valúa por su .BA
        (`_broker_name_sets`) y a qué cuenta raíz llega un pase (`raices_de_brokers`).
        Cambiarlo sin tocar el nombre ni la moneda también tiene que rehacer la historia."""
        antes = self._huella()
        with self.conn:
            n = self.conn.execute(
                "UPDATE brokers SET parent_broker_id=(SELECT id FROM brokers p WHERE "
                "p.user_id=brokers.user_id AND p.name='IBKR') WHERE user_id=? AND name='Schwab'",
                (self.uid,)).rowcount
        self.assertEqual(n, 1)
        self.assertNotEqual(self._huella(), antes)

    def test_cada_dato_nuevo_que_lee_entra_en_la_huella(self):
        self._importado = self._confirmar("IBKR", [
            _fila(0, "2025-03-03", "IBKR", OP_DEPOSIT, monto=10000.0),
            _fila(1, "2025-03-04", "IBKR", OP_BUY, "AAPL", 10.0, 100.0, 1000.0),
        ])
        self._pase(fecha="2025-06-10", de="IBKR", a="Schwab", activo="AAPL",
                   salida=[(10.0, 1000.0)], llegadas=[(10.0, 100.0, 1000.0, "2025-03-04")],
                   valor_usd=2550.0, costo_usd=1000.0)
        for sql in ("UPDATE positions SET en_broker_desde='2025-06-11' WHERE user_id=? "
                    "AND broker='Schwab'",
                    "UPDATE import_normalized_tx SET costo_nativo=999 WHERE traspaso_id IS NOT "
                    "NULL AND operation_type='SELL' AND batch_id IN (SELECT id FROM "
                    "import_batches WHERE user_id=?)",
                    "UPDATE import_normalized_tx SET fecha_compra='2025-03-05' WHERE traspaso_id "
                    "IS NOT NULL AND operation_type='BUY' AND batch_id IN (SELECT id FROM "
                    "import_batches WHERE user_id=?)"):
            antes = self._huella()
            with self.conn:
                self.assertEqual(self.conn.execute(sql, (self.uid,)).rowcount, 1, sql)
            self.assertNotEqual(self._huella(), antes, sql)


if __name__ == "__main__":
    unittest.main()
