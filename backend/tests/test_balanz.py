"""Regresión de Balanz "Resultados" — acciones societarias + fixes del audit.

El audit (2026-06-25) encontró 2 bugs HIGH en el parser de Balanz Resultados,
ambos por `_pos()` rechazando precio 0:
  • Lotes de "Dividendo en acciones" (acciones recibidas GRATIS) con Precio
    Compra=0 se tiraban en silencio → BYMA y SPY quedaban con menos nominales
    de los reales (21/26, 29/63).
  • "Reducción de capital" (Orden con PrecioVenta=0) no emitía la VENTA → la
    posición quedaba FANTASMA abierta (DESP a 22600 ARS, inflando la cartera).

Fixes LOW también cubiertos: asset_type propagado a la renta (cupón/dividendo),
Descripcion → asset_name (para el sweep de vencimientos), y Tipo Movimiento
desconocido → RowError no-fatal (en vez de COMPRA espuria).

Corre con: cd backend && python3 -m pytest tests/test_balanz.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.parsers.balanz_resultados import BalanzResultadosParser
from importing.normalizer import normalize_rows
from importing.validator import validate
import importing.pipeline as pl
import importing.persister as ps
import main  # init_db() crea las tablas


# Header de la hoja `por_realizado` (17 columnas). Mismo orden que template_csv().
BALANZ_HEADER = (
    "Cantidad,Descripcion,Fecha,FechaCompra,Gastos,Moneda Compra,Moneda Venta,"
    "Operacion Compra,Operacion Venta,Precio Compra,PrecioVenta,Ticker,Tipo,"
    "Tipo Movimiento,Cupones,Dividendos,Intereses"
)


def _csv(*rows):
    return "\n".join([BALANZ_HEADER, *rows]) + "\n"


def _parse(*rows):
    return BalanzResultadosParser().parse(_csv(*rows))


def _rows_for(result, ticker):
    """(tipo, precio, cantidad) de las raw_rows de un ticker."""
    return [(r.data.get("tipo"), r.data.get("precio"), r.data.get("cantidad"))
            for r in result.raw_rows if r.data.get("activo") == ticker]


# ─── Helpers de persist (mismo patrón que test_importer.py) ──────────────────

def _new_user(conn, email):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"))
    return cur.lastrowid


def _add_broker(conn, uid, name, currency):
    conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                 (uid, name, currency))


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    return h


# ─── HIGH A: lotes de costo-cero (Dividendo en acciones / Split) ─────────────

class ZeroCostLotsTest(unittest.TestCase):
    def test_dividendo_en_acciones_importa_a_costo_cero(self):
        # Antes: Precio Compra=0 → _pos(0)=None → lote tirado en silencio.
        r = _parse(
            "5,ACCION BYMA,2025-03-10,2025-03-10,0,Pesos,,"
            "Dividendo en acciones / BYMA,,0,,BYMA,Acciones,No Realizado,,,")
        rows = _rows_for(r, "BYMA")
        self.assertEqual(rows, [("COMPRA", "0.0", "5.0")])
        self.assertEqual(len(r.parse_errors), 0)

    def test_split_recibido_importa_a_costo_cero(self):
        r = _parse(
            "3,DERECHOS X,2025-04-01,2025-04-01,0,Pesos,,"
            "Split / XYZ,,0,,XYZ,Acciones,No Realizado,,,")
        self.assertEqual(_rows_for(r, "XYZ"), [("COMPRA", "0.0", "3.0")])

    def test_lote_normal_precio_cero_NO_se_importa(self):
        # Regresión: un "Boleto" (compra normal) con Precio Compra=0 NO es un
        # lote de costo-cero válido — sigue salteándose (no inventamos lotes).
        r = _parse(
            "10,ACCION RARA,2025-04-01,2025-04-01,0,Pesos,,"
            "Boleto,,0,,RARA,Acciones,No Realizado,,,")
        self.assertEqual(_rows_for(r, "RARA"), [])
        self.assertEqual(len(r.parse_errors), 0)  # skip silencioso, no es error

    def test_costo_cero_pasa_validacion_como_compra_normal(self):
        # El lote a precio 0 NO debe caer en cost_basis_pending ni dar error.
        r = _parse(
            "5,ACCION BYMA,2025-03-10,2025-03-10,0,Pesos,,"
            "Dividendo en acciones / BYMA,,0,,BYMA,Acciones,No Realizado,,,")
        norm, nerrs = normalize_rows(r.raw_rows)
        self.assertEqual(len(nerrs), 0)
        valid, verrs = validate(
            norm, user_brokers={"Balanz": {"id": 1, "currency": "ARS", "parent_broker_id": None}},
            existing_positions={})
        self.assertEqual(len(verrs), 0)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0].operation_type, "BUY")
        self.assertEqual(valid[0].unit_price, 0.0)
        self.assertFalse(valid[0].cost_basis_pending)


# ─── HIGH B: Reducción de capital cierra la posición ─────────────────────────

class CapitalReductionTest(unittest.TestCase):
    def test_reduccion_de_capital_emite_venta_a_cero(self):
        # Antes: PrecioVenta=0 → la VENTA no se emitía → DESP quedaba fantasma.
        r = _parse(
            "1,CEDEAR DESPEGAR.COM CORP.,2024-12-23,2024-12-20,0,Pesos,Pesos,"
            "Boleto,Reducción de capital / DESP,22600,0,DESP,Cedears,Orden,,,")
        rows = _rows_for(r, "DESP")
        self.assertEqual(rows, [("COMPRA", "22600.0", "1.0"), ("VENTA", "0.0", "1.0")])

    def test_venta_de_cierre_marca_corporate_close_y_pasa_validacion(self):
        r = _parse(
            "1,CEDEAR DESPEGAR.COM CORP.,2024-12-23,2024-12-20,0,Pesos,Pesos,"
            "Boleto,Reducción de capital / DESP,22600,0,DESP,Cedears,Orden,,,")
        norm, _ = normalize_rows(r.raw_rows)
        sell = [t for t in norm if t.operation_type == "SELL"][0]
        self.assertTrue(sell.corporate_close)
        # El validador NO debe rechazar la venta a precio 0 (corporate_close).
        valid, verrs = validate(
            norm, user_brokers={"Balanz": {"id": 1, "currency": "ARS", "parent_broker_id": None}},
            existing_positions={})
        self.assertEqual([e.code for e in verrs], [])
        self.assertEqual(len(valid), 2)  # COMPRA + VENTA, ninguna descartada

    def test_devolucion_de_capital_tambien_cierra(self):
        r = _parse(
            "1,ALGO,2024-12-23,2024-12-20,0,Pesos,Pesos,"
            "Boleto,Devolución de capital / ABC,500,0,ABC,Acciones,Orden,,,")
        self.assertEqual(_rows_for(r, "ABC"),
                         [("COMPRA", "500.0", "1.0"), ("VENTA", "0.0", "1.0")])

    def test_ggalx_split_mas_reduccion_neto_cero(self):
        # Ambos precios 0: Split (compra costo-cero) + Reducción (venta a 0).
        # Antes se tiraba entera (sin rastro); ahora deja COMPRA 0 + VENTA 0.
        r = _parse(
            "1,GGAL DERECHOS,2024-11-01,2024-11-01,0,Pesos,Pesos,"
            "Split / GGAL,Reducción de capital / GGALX,0,0,GGALX,Acciones,Orden,,,")
        self.assertEqual(_rows_for(r, "GGALX"),
                         [("COMPRA", "0.0", "1.0"), ("VENTA", "0.0", "1.0")])

    def test_venta_normal_a_precio_cero_SIGUE_rechazada(self):
        # Regresión del validador: el flag corporate_close es la ÚNICA puerta para
        # aceptar una venta a precio 0. Sin el flag, MISSING_PRICE sigue activo —
        # así no se silencian errores de mapeo del usuario en otros brokers.
        # (Nota: el parser de Balanz nunca produce una venta normal a 0 — la
        # saltea —; por eso testeamos el validador directo.)
        from importing.schema import NormalizedTx
        brokers = {"Balanz": {"id": 1, "currency": "ARS", "parent_broker_id": None}}

        plain = NormalizedTx(row_index=1, date="2025-01-15", broker="Balanz",
                             operation_type="SELL", asset_symbol="YPFD",
                             quantity=10, unit_price=0.0)
        _, verrs = validate([plain], user_brokers=brokers, existing_positions={})
        self.assertIn("MISSING_PRICE", [e.code for e in verrs])

        flagged = NormalizedTx(row_index=1, date="2025-01-15", broker="Balanz",
                               operation_type="SELL", asset_symbol="YPFD",
                               quantity=10, unit_price=0.0, corporate_close=True)
        valid, verrs2 = validate([flagged], user_brokers=brokers, existing_positions={})
        self.assertEqual([e.code for e in verrs2], [])
        self.assertEqual(len(valid), 1)


# ─── LOW: asset_type a renta + Descripcion→asset_name + Tipo desconocido ─────

class LowSeverityFixesTest(unittest.TestCase):
    def test_dividendo_lleva_asset_type(self):
        r = _parse("0,CEDEAR AMZN,2026-06-17,,0,,Dólares,,Dividendo,,,AMZN,Cedears,Dividendo,,0.13,")
        d = [x.data for x in r.raw_rows if x.data["activo"] == "AMZN"][0]
        self.assertEqual(d["tipo"], "DIVIDENDO")
        self.assertEqual(d.get("asset_type"), "CEDEAR")

    def test_cupon_lleva_asset_type(self):
        r = _parse("0,BONO AL30,2025-10-31,,0,,Dólares,,Renta,,,AL30,Bonos - Dólar,Cupón,146.7,,")
        d = [x.data for x in r.raw_rows if x.data["activo"] == "AL30"][0]
        self.assertEqual(d["tipo"], "INTERES")
        self.assertEqual(d.get("asset_type"), "BOND")

    def test_descripcion_se_pasa_como_asset_name(self):
        r = _parse(
            "1000,BONO GD30 V.09/07/30,2026-06-25,2025-05-29,0,Pesos,,"
            "Boleto,,66,,GD30,Bonos - Dólar,No Realizado,,,")
        d = [x.data for x in r.raw_rows if x.data["activo"] == "GD30"][0]
        self.assertEqual(d.get("asset_name"), "BONO GD30 V.09/07/30")
        # El normalizer lo expone en NormalizedTx.asset_name (lo lee el sweep).
        norm, _ = normalize_rows(r.raw_rows)
        self.assertEqual(norm[0].asset_name, "BONO GD30 V.09/07/30")

    def test_tipo_movimiento_desconocido_no_emite_compra_espuria(self):
        # "Rescate" (FCI) con precio+cantidad: antes generaba una COMPRA espuria
        # → posición fantasma. Ahora se omite con un RowError no-fatal.
        r = _parse("10,FONDO X,2025-03-01,2025-03-01,0,Pesos,,Boleto,,100,,FCIX,Fondos,Rescate,,,")
        self.assertEqual(_rows_for(r, "FCIX"), [])
        self.assertEqual([e.code for e in r.parse_errors], ["BALANZ_RES_TIPO_DESCONOCIDO"])

    def test_movimientos_conocidos_no_disparan_error(self):
        # No Realizado + Orden + Cupón + Dividendo → 0 parse_errors.
        r = _parse(
            "10,CEDEAR AAPL,2025-02-01,2025-02-01,0,Pesos,,Boleto,,200,,AAPL,Cedears,No Realizado,,,",
            "100,ACCION YPF,2025-01-15,2025-01-10,0,Pesos,Pesos,Boleto,Boleto,1000,1200,YPFD,Acciones,Orden,,,",
            "0,BONO AL30,2025-10-31,,0,,Dólares,,Renta,,,AL30,Bonos - Dólar,Cupón,146.7,,")
        self.assertEqual(len(r.parse_errors), 0)


# ─── Persist end-to-end: el efecto económico real ───────────────────────────

class BalanzPersistTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, "balanz_test@rendi.test")
        _add_broker(conn, self.uid, "Balanz", "ARS")
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
            (self.uid, "Balanz", "ARS", 100000))
        conn.commit()
        conn.close()

    def _import(self, *rows):
        csv_bytes = _csv(*rows).encode("utf-8")
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv_bytes, file_name="balanz.csv",
                    broker_hint="Balanz", parser_format="balanz_resultados")
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                 raw_row_ids_by_index=raw, helpers=_helpers())
            return payload, conn.execute(
                "SELECT broker, asset, is_cash, quantity, invested FROM positions "
                "WHERE user_id=? ORDER BY is_cash, asset", (self.uid,)).fetchall()
        finally:
            conn.close()

    def test_reduccion_de_capital_cierra_sin_cash_fantasma(self):
        # DESP comprado a 22600 ARS, cerrado por reducción de capital.
        payload, positions = self._import(
            "1,CEDEAR DESPEGAR.COM CORP.,2024-12-23,2024-12-20,0,Pesos,Pesos,"
            "Boleto,Reducción de capital / DESP,22600,0,DESP,Cedears,Orden,,,")
        self.assertEqual(payload["summary"]["valid_rows"], 2)  # COMPRA + VENTA
        # NO debe quedar posición DESP abierta (era el bug: fantasma a 22600).
        desp = [p for p in positions if p["asset"] == "DESP" and not p["is_cash"]]
        self.assertEqual(desp, [], "DESP debió cerrarse, no quedar fantasma abierta")
        # Cash = 100000 − 22600 (compra real, debitada al comprar). La venta a 0
        # NO acredita cash (proceeds=0) → no infla el saldo. Es el trade-off
        # conciente: registra una pérdida realizada = costo del lote, y el capital
        # devuelto entra POR SEPARADO (en el archivo real, como Dividendo en USD).
        # Acá no hay fila de Dividendo, así que el cash refleja solo la compra.
        cash = [p for p in positions if p["is_cash"]][0]
        self.assertAlmostEqual(cash["invested"], 77400, places=2)

    def test_lote_costo_cero_no_debita_cash(self):
        # 5 BYMA recibidas como dividendo en acciones (Precio Compra=0).
        payload, positions = self._import(
            "5,ACCION BYMA,2025-03-10,2025-03-10,0,Pesos,,"
            "Dividendo en acciones / BYMA,,0,,BYMA,Acciones,No Realizado,,,")
        self.assertEqual(payload["summary"]["valid_rows"], 1)
        byma = [p for p in positions if p["asset"] == "BYMA" and not p["is_cash"]]
        self.assertEqual(len(byma), 1)
        self.assertAlmostEqual(byma[0]["quantity"], 5, places=6)
        self.assertAlmostEqual(byma[0]["invested"] or 0, 0, places=6)
        # El lote gratis NO debita cash (costo 0).
        cash = [p for p in positions if p["is_cash"]][0]
        self.assertAlmostEqual(cash["invested"], 100000, places=2)


class FlagInjectionHardeningTest(unittest.TestCase):
    """El namespace de flags internos (_corporate_close, _cost_basis_pending…) no
    debe ser inyectable desde un CSV de usuario vía el parser genérico — si no,
    cualquiera saltearía el guard MISSING_PRICE de una venta a precio 0."""

    def test_user_no_puede_inyectar_corporate_close(self):
        from importing.parsers.generic import RendiGenericParser
        csv = ("fecha,tipo,broker,activo,cantidad,precio,_corporate_close\n"
               "2025-01-10,VENTA,Balanz,AAPL,10,0,1\n")
        res = RendiGenericParser().parse(csv)
        self.assertEqual(len(res.raw_rows), 1)
        # La columna con "_" inicial se descarta — no llega al data dict.
        self.assertNotIn("_corporate_close", res.raw_rows[0].data)
        norm, _ = normalize_rows(res.raw_rows)
        self.assertFalse(norm[0].corporate_close)
        # Y la venta a precio 0 SIGUE siendo rechazada (no inyectó el flag).
        _, verrs = validate(
            norm, user_brokers={"Balanz": {"id": 1, "currency": "ARS", "parent_broker_id": None}},
            existing_positions={})
        self.assertIn("MISSING_PRICE", [e.code for e in verrs])

    def test_columnas_normales_no_se_descartan(self):
        # Regresión: monto_usd (con "_" interno, no inicial) debe sobrevivir.
        from importing.parsers.generic import RendiGenericParser
        csv = ("fecha,tipo,broker,activo,cantidad,precio,monto_usd,moneda\n"
               "2025-01-10,DIVIDENDO,Balanz,AAPL,,,12.50,USD\n")
        res = RendiGenericParser().parse(csv)
        self.assertIn("monto_usd", res.raw_rows[0].data)
        self.assertEqual(res.raw_rows[0].data["monto_usd"], "12.50")


if __name__ == "__main__":
    unittest.main()
