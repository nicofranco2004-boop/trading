"""«Mover a otro broker», etapa E2b: los motores entienden las filas de un pase.

Todavía no hay pantalla ni endpoint que haga un pase: eso llega en E5–E7. Pero las
filas que va a escribir (sección A.6 de la especificación) ya tienen que pasar por
los motores de siempre sin que ninguno las tome por lo que no son:

  · la LLEGADA al broker de destino es una COMPRA con `traspaso_id` y la fecha de
    compra original aparte (`fecha_compra`): abre un lote con esa fecha de compra,
    anota desde cuándo está ahí (`en_broker_desde`) y NO toca la caja (los títulos
    ya estaban pagos);
  · la SALIDA del broker de origen es una VENTA a precio 0 con `traspaso_id`:
    consume los lotes, pero no es una venta —ni fila en `operations`, ni resultado
    del mes— y si faltan títulos frena en vez de fabricar un lote;
  · las patas TRASPASO_SALIDA / TRASPASO_ENTRADA no mueven nada (las lee el recálculo
    en una etapa posterior), y una sin pase es un error;
  · el rebuild hace lo mismo que el persister, y una venta posterior en el destino
    consume primero el lote de compra más vieja aunque haya llegado después (H2);
  · los que leen el registro por su cuenta (el borrado de una fila, la caja
    reconstruida, los splits, el resultado en dos monedas) ven lo mismo.

CAMINO. Las filas entran como entrará el pase (C.7.4–6): `store_preview_txs` →
`load_session_for_confirm` → `persist_batch` con los ayudantes reales de main, y
después el rebuild real (`rebuild_fifo_after_import` / `rebuild_pair_asset`) y el
recálculo real del mes. La venta a mano (D.10.12–13) va por HTTP con un token real.

Corre con: cd backend && python3 -m pytest tests/test_motores_neutros_pase.py
"""
import json
import os
import sys
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import fx  # noqa: E402
import ledger_replay  # noqa: E402
import resultado_dual  # noqa: E402
from importing import pipeline as pl  # noqa: E402
from importing import persister as ps  # noqa: E402
from importing import rebuild as rb  # noqa: E402
from importing.schema import (  # noqa: E402
    NormalizedTx, OP_BUY, OP_SELL, OP_FEE, OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA,
)
from _limpieza import vaciar  # noqa: E402

PASE = "c0ffee00c0ffee00c0ffee00c0ffee00"
TC_BLUE = 1400.0

# fx_rates_daily: fecha → (blue_venta, mep_venta). Uno distinto por fecha, así se ve
# de qué día salió cada dólar.
DOLARES = {
    "2023-01-15": (380.0, 350.0),
    "2023-07-01": (500.0, 480.0),
    "2024-01-10": (1100.0, 1000.0),
    "2024-03-01": (1150.0, 1050.0),
    "2024-05-01": (1200.0, 1100.0),
    "2024-06-01": (1300.0, 1250.0),
    "2024-06-10": (1310.0, 1260.0),
}

TABLAS = ("import_op_links", "import_normalized_tx", "import_raw_rows",
          "import_batches", "operations", "positions", "monthly_entries",
          "snapshots", "config", "brokers", "users")

NOTA_SALIDA = "Traspaso a otro broker tuyo el 10/06/2024 — sale al costo, sin ganancia"
NOTA_LLEGADA = "Llegó desde otro broker tuyo el 01/05/2024 · compra original del 15/01/2023"


def _fila(i, fecha, broker, op, activo, qty, precio, monto, comision, moneda, **extra):
    return NormalizedTx(row_index=i, date=fecha, broker=broker, operation_type=op,
                        asset_symbol=activo, asset_type=extra.pop("tipo", "CEDEAR"),
                        quantity=qty, unit_price=precio, gross_amount=monto, fees=comision,
                        currency=moneda, **extra)


class _Base(unittest.TestCase):

    def setUp(self):
        self.conn = main.get_db()
        vaciar(self.conn, *TABLAS)
        self.conn.execute(f"DELETE FROM fx_rates_daily WHERE date IN "
                          f"({','.join('?' * len(DOLARES))})", tuple(DOLARES))
        for fecha, (blue, mep) in DOLARES.items():
            self.conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                              "VALUES (?,?,?, 'test')", (fecha, blue, mep))
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"motores-pase-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        for nombre in ("Cocos", "Balanz"):
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, nombre, "ARS"))
        fx.set_fx_version(self.conn, self.uid, "v2")
        self.conn.execute("INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
                          "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
                          (self.uid, "tc_blue", str(TC_BLUE)))
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute(f"DELETE FROM fx_rates_daily WHERE date IN "
                              f"({','.join('?' * len(DOLARES))})", tuple(DOLARES))
            self.conn.commit()
        except Exception:
            pass
        try:
            vaciar(self.conn, *TABLAS)
            self.conn.commit()
        finally:
            self.conn.close()

    # ── el camino del confirm ──
    def _confirmar(self, broker, txs, formato="rendi_generic"):
        """Guardar, releer de la base y aplicar, como el confirm (y como el pase)."""
        with self.conn:
            sid = pl.store_preview_txs(self.conn, self.uid, broker=broker, parser_format=formato,
                                       file_name="motores.csv", txs=txs)
        with self.conn:
            txs_db, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            r = ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs_db,
                                 raw_row_ids_by_index=raw, helpers=main._import_helpers)
        return sid, r

    def _confirmar_sin_saltear(self, broker, txs, formato="rendi_generic"):
        sid, r = self._confirmar(broker, txs, formato)
        self.assertEqual(r["skipped_rows"], [], r)
        return sid

    def _rebuild_del_lote(self, sid):
        with self.conn:
            res = rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=TC_BLUE)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return res

    # ── lo que se mira ──
    def _lotes(self, broker, activo):
        return [tuple(r) for r in self.conn.execute(
            "SELECT entry_date, en_broker_desde, quantity, invested, commissions, tc_compra "
            "FROM positions WHERE user_id=? AND broker=? AND asset=? AND is_cash=0 "
            "ORDER BY entry_date, id", (self.uid, broker, activo)).fetchall()]

    def _ventas(self, activo):
        return [tuple(r) for r in self.conn.execute(
            "SELECT broker, entry_date, quantity, pnl_usd FROM operations "
            "WHERE user_id=? AND asset=? AND op_type='Venta' ORDER BY entry_date, id",
            (self.uid, activo)).fetchall()]

    def _caja(self, broker):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) c FROM positions "
            "WHERE user_id=? AND broker=? AND is_cash=1", (self.uid, broker)).fetchone()
        return round(float(r["c"] or 0), 6)

    def _resultado_del_mes(self, broker, y, m):
        r = self.conn.execute(
            "SELECT pnl_realized FROM monthly_entries WHERE user_id=? AND broker=? "
            "AND year=? AND month=?", (self.uid, broker, y, m)).fetchone()
        return round(float(r["pnl_realized"] or 0), 6) if r else 0.0

    # ── las filas ──
    def _compra_previa_en_b(self):
        """Balanz ya tenía 10 KO comprados el 01/03/2024 a $1.000."""
        return self._confirmar_sin_saltear("Balanz", [
            _fila(0, "2024-03-01", "Balanz", OP_BUY, "KO", 10.0, 1000.0, 10000.0, 0.0, "ARS")])

    def _llegada_a_b(self, *, extra=()):
        """El 01/05/2024 llegan 5 KO por un pase, comprados el 15/01/2023 a $500 con
        $25 de comisión. Sin `tc_compra`: el persister lo tiene que buscar en la fecha
        de COMPRA (350), no en la de llegada (1.100)."""
        return self._confirmar_sin_saltear("Balanz", [
            _fila(-49999, "2024-05-01", "Balanz", OP_BUY, "KO", 5.0, 500.0, 2500.0, 25.0, "ARS",
                  traspaso_id=PASE, fecha_compra="2023-01-15", notes=NOTA_LLEGADA),
            _fila(-49998, "2024-05-01", "Balanz", OP_TRASPASO_ENTRADA, "KO", 5.0, 1100.0, None,
                  0.0, "ARS", traspaso_id=PASE, valor_usd=5.0, valor_ars=5500.0,
                  costo_usd=7.21, costo_nativo=2525.0),
            *extra,
        ], formato="traspaso_a_mano")

    def _compra_previa_en_a(self):
        """Cocos tenía 10 NVDA del 10/01/2024 a $30.000, con $1.500 de comisión."""
        return self._confirmar_sin_saltear("Cocos", [
            _fila(0, "2024-01-10", "Cocos", OP_BUY, "NVDA", 10.0, 30000.0, 300000.0, 1500.0, "ARS")])

    def _salida_de_a(self, cantidad=4.0, *, gasto=None):
        filas = [
            _fila(-49999, "2024-06-10", "Cocos", OP_SELL, "NVDA", cantidad, 0.0, 0.0, 0.0, "ARS",
                  transfer_out=True, traspaso_id=PASE, costo_nativo=30000.0 * cantidad,
                  notes=NOTA_SALIDA),
            _fila(-49998, "2024-06-10", "Cocos", OP_TRASPASO_SALIDA, "NVDA", cantidad, 62500.0,
                  None, 0.0, "ARS", traspaso_id=PASE, valor_usd=198.41, valor_ars=250000.0,
                  costo_usd=95.71, costo_nativo=120600.0),
        ]
        if gasto:
            filas.append(_fila(-49997, "2024-06-10", "Cocos", OP_FEE, None, None, None, gasto,
                               0.0, "ARS", tipo=None, traspaso_id=PASE, valor_usd=gasto / 1260.0,
                               notes="Costo del pase de NVDA a otro broker tuyo"))
        return self._confirmar("Cocos", filas, formato="traspaso_a_mano")


class LaLlegadaAlDestino(_Base):

    def test_el_lote_conserva_su_compra_y_no_toca_la_caja(self):
        self._compra_previa_en_b()
        caja_antes = self._caja("Balanz")
        self._llegada_a_b()
        self.assertEqual(self._caja("Balanz"), caja_antes,
                         "la llegada de un pase no se paga: los títulos ya eran del usuario")
        self.assertEqual(self._lotes("Balanz", "KO"), [
            # fecha de compra original · desde cuándo está acá · dólar de la COMPRA
            ("2023-01-15", "2024-05-01", 5.0, 2500.0, 25.0, 350.0),
            ("2024-03-01", None, 10.0, 10000.0, 0.0, 1050.0),
        ])
        # La pata de entrada no crea ninguna posición ni vínculo.
        n = self.conn.execute(
            "SELECT created_position_id, created_operation_id FROM import_normalized_tx "
            "WHERE operation_type=?", (OP_TRASPASO_ENTRADA,)).fetchone()
        self.assertEqual((n["created_position_id"], n["created_operation_id"]), (None, None))

    def test_una_venta_posterior_consume_primero_la_compra_mas_vieja(self):
        """H2 por el camino de producción: el persister (que ordena por entry_date) y
        el rebuild (que ordenaba por llegada) eligen el MISMO lote."""
        self._compra_previa_en_b()
        self._llegada_a_b()
        sid = self._confirmar_sin_saltear("Balanz", [
            _fila(0, "2024-06-01", "Balanz", OP_SELL, "KO", 3.0, 2000.0, 6000.0, 0.0, "ARS")])
        lotes_persister = self._lotes("Balanz", "KO")
        ventas_persister = [(b, d, q) for b, d, q, _ in self._ventas("KO")]
        self.assertEqual(ventas_persister, [("Balanz", "2023-01-15", 3.0)])

        res = self._rebuild_del_lote(sid)
        self.assertEqual((res["errors"], res["skipped_manual"], len(res["rebuilt"])), ([], [], 1), res)
        self.assertEqual([(b, d, q) for b, d, q, _ in self._ventas("KO")], ventas_persister)
        self.assertEqual(self._lotes("Balanz", "KO"), lotes_persister)
        self.assertEqual(lotes_persister, [
            ("2023-01-15", "2024-05-01", 2.0, 1000.0, 10.0, 350.0),
            ("2024-03-01", None, 10.0, 10000.0, 0.0, 1050.0),
        ])

    def test_el_resultado_en_dos_monedas_encuentra_la_compra_por_su_fecha_original(self):
        """`resultado_dual._compras_importadas` busca la compra del lote que consumió
        la venta por la fecha de compra: la de la llegada es otra."""
        self._compra_previa_en_b()
        self._llegada_a_b()
        self._confirmar_sin_saltear("Balanz", [
            _fila(0, "2024-06-01", "Balanz", OP_SELL, "KO", 3.0, 2000.0, 6000.0, 0.0, "ARS")])
        op = dict(self.conn.execute(
            "SELECT * FROM operations WHERE user_id=? AND op_type='Venta'", (self.uid,)).fetchone())
        compras = resultado_dual._compras_importadas(self.conn, self.uid, op)
        self.assertEqual([(r["quantity"], r["gross_amount"], r["fees"]) for r in compras],
                         [(5.0, 2500.0, 25.0)])

    def test_borrar_la_llegada_no_devolveria_plata(self):
        """`_plata_de_fila_importada` es el espejo del persister: la compra del pase no
        debitó, así que no devuelve. Una compra común sí."""
        self._compra_previa_en_b()
        self._llegada_a_b()
        filas = {r["date"]: r for r in self.conn.execute(
            "SELECT n.* FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
            "WHERE b.user_id=? AND n.operation_type='BUY'", (self.uid,)).fetchall()}
        self.assertEqual(main._plata_de_fila_importada(self.conn, self.uid, filas["2024-05-01"]),
                         ("Balanz", 0.0))
        self.assertEqual(main._plata_de_fila_importada(self.conn, self.uid, filas["2024-03-01"]),
                         ("Balanz", 10000.0))

    def test_un_lote_gratis_que_llega_conserva_la_marca_del_dia_de_compra(self):
        """Un lote a $0 (el que deja un split) que pasa de broker: la marca que usan
        los splits es la de su compra, no la del pase."""
        self._llegada_a_b(extra=[
            _fila(-49997, "2024-05-01", "Balanz", OP_BUY, "MSFT", 2.0, 0.0, 0.0, 0.0, "ARS",
                  traspaso_id=PASE, fecha_compra="2023-07-01", notes=NOTA_LLEGADA)])
        self.assertEqual(main._corporate_zero_dates(self.conn, self.uid).get(("Balanz", "MSFT")),
                         ["2023-07-01"])


class LaSalidaDelOrigen(_Base):

    def test_consume_los_lotes_sin_ser_una_venta(self):
        self._compra_previa_en_a()
        caja_antes = self._caja("Cocos")
        sid, r = self._salida_de_a(4.0)
        self.assertEqual(r["skipped_rows"], [], r)
        self.assertEqual(r["operations_created"], 0)
        self.assertEqual(self._ventas("NVDA"), [], "el pase no es una venta")
        self.assertEqual(self._lotes("Cocos", "NVDA"),
                         [("2024-01-10", None, 6.0, 180000.0, 900.0, 1000.0)])
        self.assertEqual(self._caja("Cocos"), caja_antes, "sin gasto, la caja no se mueve")
        self.assertEqual(self._resultado_del_mes("Cocos", 2024, 6), 0.0)
        self.assertEqual(self._resultado_del_mes("global", 2024, 6), 0.0)
        # Ni vínculo de operación: no hay ninguna.
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM import_op_links WHERE batch_id=? AND operation_id IS NOT NULL",
            (sid,)).fetchone())
        # Y la venta a $0 del pase no es un evento societario: los splits no la ven.
        self.assertNotIn(("Cocos", "NVDA"), main._corporate_zero_dates(self.conn, self.uid))

    def test_el_rebuild_hace_lo_mismo_y_dice_que_se_llevo(self):
        compra = self._compra_previa_en_a()
        sid, _ = self._salida_de_a(4.0)
        lotes_persister = self._lotes("Cocos", "NVDA")

        res = self._rebuild_del_lote(sid)
        self.assertEqual((res["errors"], res["skipped_manual"], len(res["rebuilt"])), ([], [], 1), res)
        self.assertEqual(self._ventas("NVDA"), [])
        self.assertEqual(self._lotes("Cocos", "NVDA"), lotes_persister)

        with self.conn:
            out = rb.rebuild_pair_asset(self.conn, self.uid, "Cocos", "NVDA", tc_blue=TC_BLUE)
        self.assertEqual(self._lotes("Cocos", "NVDA"), lotes_persister)
        raw_compra = self.conn.execute(
            "SELECT raw_row_id FROM import_normalized_tx WHERE batch_id=?", (compra,)).fetchone()[0]
        self.assertEqual(out["traspasos"], {PASE: [{
            "entry_date": "2024-01-10", "qty": 4.0, "invested": 120000.0, "commissions": 600.0,
            "currency": "ARS", "batch_id": compra, "raw_row_id": raw_compra}]})

    def test_si_faltan_titulos_frena_y_no_fabrica_un_lote(self):
        self._compra_previa_en_a()
        _, r = self._salida_de_a(12.0)
        mensajes = [s["message"] for s in r["skipped_rows"]]
        self.assertIn("No alcanzan los títulos para el pase.", mensajes)
        self.assertEqual(self._lotes("Cocos", "NVDA"),
                         [("2024-01-10", None, 10.0, 300000.0, 1500.0, 1000.0)],
                         "sin lote semilla y sin consumir nada")

    def test_el_gasto_sale_de_la_caja_como_cualquier_comision(self):
        self._compra_previa_en_a()
        caja_antes = self._caja("Cocos")
        _, r = self._salida_de_a(4.0, gasto=5000.0)
        self.assertEqual(r["skipped_rows"], [], r)
        self.assertEqual(self._caja("Cocos"), round(caja_antes - 5000.0, 6))

    def test_una_pata_sin_pase_es_un_error(self):
        _, r = self._confirmar("Cocos", [
            _fila(0, "2024-06-10", "Cocos", OP_TRASPASO_SALIDA, "NVDA", 4.0, 62500.0, None, 0.0,
                  "ARS", valor_usd=198.41)], formato="traspaso_a_mano")
        self.assertEqual([s["message"] for s in r["skipped_rows"]], ["Fila interna de pase sin pase."])


class LaCajaReconstruida(_Base):

    def test_el_replay_de_la_caja_ve_lo_mismo_que_el_persister(self):
        """`ledger_replay.cash_en` rearma la caja desde el registro: la llegada del pase
        no sale de la caja; el gasto del pase sí."""
        self._compra_previa_en_b()
        self._llegada_a_b()
        self._compra_previa_en_a()
        self._salida_de_a(4.0, gasto=5000.0)
        saldos = ledger_replay.cash_en(self.conn, self.uid, "2024-12-31")
        self.assertEqual(round(saldos[("Balanz", "ARS")], 6), -10000.0)
        self.assertEqual(round(saldos[("Cocos", "ARS")], 6), -301500.0 - 5000.0)
        # Y coincide con la caja que dejó el persister.
        self.assertEqual(self._caja("Balanz"), -10000.0)
        self.assertEqual(self._caja("Cocos"), -306500.0)


class LaVentaAManoGuardaLoQueVuelve(unittest.TestCase):
    """D.10.12–13 por HTTP con un token real: la venta a mano guarda en su receta la
    marca del split y desde cuándo está el lote en el broker, y borrarla devuelve el
    lote con las dos (la regla compartida `_devolver_al_lote`)."""

    def setUp(self):
        conn = main.get_db()
        try:
            self.uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                (f"venta-a-mano-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, "IBKR", "USD"))
            conn.commit()
        finally:
            conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)

    def _esperar_la_reconstruccion(self):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción no terminó en 60 s")

    def _ok(self, r):
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_la_reconstruccion()
        return r.json()

    def _lote(self, conn, pid):
        return conn.execute(
            "SELECT id, quantity, invested, commissions, entry_date, split_adjusted_through, "
            "en_broker_desde FROM positions WHERE id=? AND user_id=?", (pid, self.uid)).fetchone()

    def test_vender_y_borrar_la_venta_devuelve_el_lote_entero(self):
        pid = self._ok(self.http.post("/api/positions", headers=self.h, json={
            "broker": "IBKR", "asset": "KO", "buy_price": 50.0, "quantity": 10,
            "invested": 500.0, "commissions": 2.0, "entry_date": "2023-01-15",
            "currency": "USD"}))["id"]
        conn = main.get_db()
        try:
            # Un lote que llegó por un pase y al que ya se le aplicó un split.
            conn.execute("UPDATE positions SET split_adjusted_through=?, en_broker_desde=? "
                         "WHERE id=? AND user_id=?", ("2024-06-10", "2024-05-01", pid, self.uid))
            conn.commit()
        finally:
            conn.close()

        self._ok(self.http.post("/api/positions/sell", headers=self.h, json={
            "broker": "IBKR", "asset": "KO", "quantity": 10, "exit_price": 60.0,
            "date": "2024-07-01", "currency": "USD"}))
        conn = main.get_db()
        try:
            self.assertIsNone(self._lote(conn, pid), "la venta total borra el lote")
            op = conn.execute("SELECT id, undo_meta_json FROM operations WHERE user_id=? "
                              "AND op_type='Venta'", (self.uid,)).fetchone()
            foto = json.loads(op["undo_meta_json"])["lot"]
            self.assertEqual((foto["split_adjusted_through"], foto["en_broker_desde"]),
                             ("2024-06-10", "2024-05-01"))
        finally:
            conn.close()

        self._ok(self.http.delete(f"/api/operations/{op['id']}", headers=self.h))
        conn = main.get_db()
        try:
            lote = self._lote(conn, pid)
            self.assertIsNotNone(lote, "el lote vuelve con su mismo id")
            self.assertEqual(tuple(lote)[1:], (10.0, 500.0, 2.0, "2023-01-15",
                                               "2024-06-10", "2024-05-01"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
