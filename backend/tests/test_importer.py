"""Tests del pipeline de import. Corre con: cd backend && python3 -m pytest tests/

Cubre:
- Parser genérico (headers, fechas, números)
- Normalizer (tipos de op, validación de campos)
- Validator (broker, stock FIFO virtual)
- Pipeline E2E (preview → confirm) en una DB temporal
- Revert (solo BUY+DEPOSIT, no SELL/FX)
"""
import os
import sys
import tempfile
import unittest

# Asegurar que el módulo backend/ esté en el path
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# DB temporal por test run — debe setearse ANTES de importar main
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name


from importing.normalizer import parse_date, parse_number, normalize_rows
from importing.parsers.generic import RendiGenericParser
from importing.parsers.registry import get_parser, autodetect
from importing.schema import RawRow, OP_BUY, OP_SELL, OP_DEPOSIT, OP_FX_ARS_TO_USD
from importing.validator import validate
from importing import pipeline as pl
from importing import persister as ps
from importing import mapper as mp

import main  # init_db() crea las tablas


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _read_fixture(name: str) -> bytes:
    with open(os.path.join(HERE, "fixtures", name), "rb") as f:
        return f.read()


def _new_user(conn, email: str = "test@rendi.test") -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"),
    )
    return cur.lastrowid


def _add_broker(conn, uid: int, name: str, currency: str = "USDT") -> int:
    cur = conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
        (uid, name, currency),
    )
    return cur.lastrowid


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    return h


# ─── Tests ────────────────────────────────────────────────────────────────────

class ParseHelpersTest(unittest.TestCase):
    def test_parse_date_iso(self):
        self.assertEqual(parse_date("2024-03-15"), "2024-03-15")

    def test_parse_date_ddmmyyyy(self):
        self.assertEqual(parse_date("15/03/2024"), "2024-03-15")
        self.assertEqual(parse_date("15-03-2024"), "2024-03-15")

    def test_parse_date_invalid(self):
        self.assertIsNone(parse_date("2024-13-40"))
        self.assertIsNone(parse_date("not-a-date"))
        self.assertIsNone(parse_date(""))

    def test_parse_number_formats(self):
        self.assertEqual(parse_number("1234"), 1234.0)
        self.assertEqual(parse_number("1234.56"), 1234.56)
        self.assertEqual(parse_number("1234,56"), 1234.56)        # es-AR
        self.assertEqual(parse_number("1.234,56"), 1234.56)       # es-AR con miles
        self.assertEqual(parse_number("1,234.56"), 1234.56)       # en-US con miles
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number("abc"))


class GenericParserTest(unittest.TestCase):
    def test_parses_basic_csv(self):
        parser = RendiGenericParser()
        result = parser.parse(_read_fixture("generic_basic.csv").decode())
        self.assertFalse(result.parse_errors)
        self.assertEqual(len(result.raw_rows), 4)

    def test_can_handle_headers(self):
        parser = RendiGenericParser()
        self.assertTrue(parser.can_handle(["fecha", "tipo", "broker", "extra"]))
        self.assertFalse(parser.can_handle(["foo", "bar"]))

    def test_template_csv(self):
        parser = RendiGenericParser()
        t = parser.template_csv()
        self.assertIn("fecha", t)
        self.assertIn("COMPRA", t)


class NormalizerTest(unittest.TestCase):
    def test_normalizes_buy_row(self):
        rows = [RawRow(1, {"fecha": "2024-03-15", "tipo": "COMPRA", "broker": "IBKR",
                            "activo": "AAPL", "cantidad": "10", "precio": "180",
                            "comisiones": "2", "moneda": "USD"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(txs), 1)
        self.assertEqual(len(errors), 0)
        self.assertEqual(txs[0].operation_type, OP_BUY)
        self.assertEqual(txs[0].quantity, 10)
        self.assertEqual(txs[0].fees, 2)

    def test_invalid_date_skips_row(self):
        rows = [RawRow(1, {"fecha": "bad", "tipo": "COMPRA", "broker": "IBKR"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(txs), 0)
        self.assertEqual(errors[0].code, "INVALID_DATE")

    def test_unknown_op_type(self):
        rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": "WEIRD", "broker": "X"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(txs), 0)
        self.assertEqual(errors[0].code, "UNKNOWN_OP_TYPE")

    def test_autocomplete_amount_from_qty_and_price(self):
        # BUY con qty + precio, sin monto → calcula monto
        rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": "COMPRA", "broker": "IBKR",
                            "activo": "AAPL", "cantidad": "10", "precio": "180", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        self.assertEqual(txs[0].quantity, 10)
        self.assertEqual(txs[0].unit_price, 180)
        self.assertEqual(txs[0].gross_amount, 1800)

    def test_autocomplete_price_from_qty_and_amount(self):
        # SELL con qty + monto, sin precio → calcula precio
        rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": "VENTA", "broker": "IBKR",
                            "activo": "AAPL", "cantidad": "5", "monto": "1100", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        self.assertEqual(txs[0].quantity, 5)
        self.assertEqual(txs[0].gross_amount, 1100)
        self.assertEqual(txs[0].unit_price, 220)

    def test_autocomplete_qty_from_price_and_amount(self):
        # BUY con precio + monto, sin cantidad → calcula cantidad
        rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": "COMPRA", "broker": "IBKR",
                            "activo": "AAPL", "precio": "200", "monto": "1000", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        self.assertEqual(txs[0].unit_price, 200)
        self.assertEqual(txs[0].gross_amount, 1000)
        self.assertEqual(txs[0].quantity, 5)

    def test_autocomplete_fx_usd_from_ars_and_tc(self):
        # Caso real del usuario: solo ARS + TC, falta USD → calcular
        rows = [RawRow(1, {"fecha": "2024-03-15", "tipo": "CONVERSION_USD_ARS",
                            "broker": "Cocos", "monto": "2200000", "tc": "1100"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0, f"errors: {[e.message for e in errors]}")
        self.assertEqual(len(txs), 1)
        # Tras normalize: gross_amount=ARS, quantity=USD, unit_price=TC
        self.assertEqual(txs[0].gross_amount, 2200000)
        self.assertEqual(txs[0].quantity, 2000)         # 2200000 / 1100
        self.assertEqual(txs[0].unit_price, 1100)

    def test_autocomplete_fx_ars_from_usd_and_tc(self):
        rows = [RawRow(1, {"fecha": "2024-03-15", "tipo": "CONVERSION_ARS_USD",
                            "broker": "Cocos", "monto_usd": "1000", "tc": "1200"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(txs[0].gross_amount, 1200000)  # 1000 × 1200
        self.assertEqual(txs[0].quantity, 1000)
        self.assertEqual(txs[0].unit_price, 1200)

    def test_autocomplete_fx_tc_from_ars_and_usd(self):
        rows = [RawRow(1, {"fecha": "2024-03-15", "tipo": "CONVERSION_ARS_USD",
                            "broker": "Cocos", "monto": "1500000", "monto_usd": "1250"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(txs[0].gross_amount, 1500000)
        self.assertEqual(txs[0].quantity, 1250)
        self.assertEqual(txs[0].unit_price, 1200)        # 1500000 / 1250

    def test_cash_in_alias(self):
        rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": "CASH_IN", "broker": "X",
                            "monto": "5000", "moneda": "USD"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(txs[0].operation_type, OP_DEPOSIT)
        self.assertEqual(txs[0].gross_amount, 5000)

    def test_dividend_with_only_monto_usd(self):
        # CSV separa monto_ars y monto_usd. Para un dividendo USD, monto vacío,
        # monto_usd lleno. Debe usar monto_usd como gross_amount.
        rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": "DIVIDEND", "broker": "X",
                            "activo": "KO", "monto_usd": "15.5", "moneda": "USD"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0, f"errors: {[e.message for e in errors]}")
        self.assertEqual(txs[0].gross_amount, 15.5)

    def test_autodetect_monto_ars(self):
        # Headers típicos de CSV multi-moneda Argentina
        m = mp.autodetect_mapping(["fecha", "operacion", "monto_ars", "monto_usd",
                                    "tipo_cambio", "moneda_csv"])
        self.assertEqual(m.columns["monto"], "monto_ars")
        self.assertEqual(m.columns["monto_usd"], "monto_usd")
        self.assertEqual(m.columns["tc"], "tipo_cambio")
        self.assertEqual(m.columns["moneda"], "moneda_csv")

    def test_fx_with_only_one_value_fails(self):
        # Solo ARS, sin USD ni TC → no se puede deducir, error
        rows = [RawRow(1, {"fecha": "2024-03-15", "tipo": "CONVERSION_USD_ARS",
                            "broker": "Cocos", "monto": "2200000"})]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(txs), 0)
        self.assertEqual(errors[0].code, "MISSING_FX_FIELDS")

    def test_autocomplete_does_not_override_user_data(self):
        # Si el usuario dio los 3 valores (incluso inconsistentes) los respetamos
        rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": "COMPRA", "broker": "IBKR",
                            "activo": "AAPL", "cantidad": "10", "precio": "180",
                            "monto": "9999", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        self.assertEqual(txs[0].gross_amount, 9999)  # respeta el valor del usuario


class ValidatorTest(unittest.TestCase):
    def test_unknown_broker(self):
        rows = [RawRow(1, {"fecha": "2024-01-15", "tipo": "COMPRA", "broker": "XYZ",
                            "activo": "AAPL", "cantidad": "10", "precio": "180", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        valid, errors = validate(txs, user_brokers={"IBKR": {"currency": "USDT"}}, existing_positions={})
        self.assertEqual(len(valid), 0)
        self.assertTrue(any(e.code == "UNKNOWN_BROKER" for e in errors))

    def test_sell_sees_buys_in_same_csv(self):
        # Compra antes que venta en orden cronológico → debe permitir vender
        rows = [
            RawRow(1, {"fecha": "2024-02-01", "tipo": "VENTA", "broker": "IBKR",
                       "activo": "AAPL", "cantidad": "5", "precio": "200", "moneda": "USD"}),
            RawRow(2, {"fecha": "2024-01-01", "tipo": "COMPRA", "broker": "IBKR",
                       "activo": "AAPL", "cantidad": "10", "precio": "150", "moneda": "USD"}),
        ]
        txs, _ = normalize_rows(rows)
        valid, errors = validate(txs, user_brokers={"IBKR": {"currency": "USDT"}}, existing_positions={})
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(errors), 0)

    def test_sell_without_stock_fails(self):
        rows = [RawRow(1, {"fecha": "2024-01-15", "tipo": "VENTA", "broker": "IBKR",
                            "activo": "TSLA", "cantidad": "100", "precio": "250", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        valid, errors = validate(txs, user_brokers={"IBKR": {"currency": "USDT"}}, existing_positions={})
        self.assertEqual(len(valid), 0)
        self.assertTrue(any(e.code == "INSUFFICIENT_STOCK" for e in errors))


class PipelineE2ETest(unittest.TestCase):
    def setUp(self):
        # Reset DB para tener un escenario limpio por test
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn)
        _add_broker(conn, self.uid, "IBKR", "USDT")
        # Cash inicial para ver el debit
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "IBKR", "USDT", 100000),
        )
        conn.commit()
        conn.close()

    def test_preview_then_confirm_basic(self):
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=_read_fixture("generic_basic.csv"),
                    file_name="generic_basic.csv", broker_hint="IBKR", parser_format="rendi_generic",
                )
            self.assertIn("session_id", payload)
            self.assertEqual(payload["summary"]["valid_rows"], 4)
            self.assertEqual(payload["summary"]["invalid_rows"], 0)
            session_id = payload["session_id"]

            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                summary = ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw_map, helpers=_helpers(),
                )
            # 2 BUY (positions_created=2) + 1 VENTA FIFO sobre la primera (operations_created=1)
            self.assertEqual(summary["positions_created"], 2)
            self.assertEqual(summary["operations_created"], 1)
            self.assertEqual(summary["cash_movements"], 1)
            # Verificar que las posiciones existen
            rows = conn.execute(
                "SELECT * FROM positions WHERE user_id=? AND is_cash=0 AND asset='AAPL'", (self.uid,)
            ).fetchall()
            # 2 compras de AAPL, una venta parcial de 8 unidades. 10+5=15 comprado, 8 vendido.
            # FIFO: la primera (10 a 180) queda con 2 unidades; la segunda (5 a 200) intacta.
            qtys = sorted(r["quantity"] for r in rows)
            self.assertEqual(qtys, [2, 5])

            # Verificar batch en estado confirmed
            batch = conn.execute(
                "SELECT status FROM import_batches WHERE id=?", (session_id,)
            ).fetchone()
            self.assertEqual(batch["status"], "confirmed")
        finally:
            conn.close()

    def test_preview_with_errors_does_not_block_valid_rows(self):
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=_read_fixture("generic_errors.csv"),
                    file_name="generic_errors.csv", broker_hint="IBKR", parser_format="rendi_generic",
                )
            # 1 fila válida (la primera COMPRA), 4 inválidas
            self.assertEqual(payload["summary"]["valid_rows"], 1)
            self.assertGreaterEqual(payload["summary"]["invalid_rows"], 4)
            self.assertTrue(any(e["code"] == "INVALID_DATE" for e in payload["errors"]))
            self.assertTrue(any(e["code"] == "UNKNOWN_OP_TYPE" for e in payload["errors"]))
            self.assertTrue(any(e["code"] == "INSUFFICIENT_STOCK" for e in payload["errors"]))
            self.assertTrue(any(e["code"] == "UNKNOWN_BROKER" for e in payload["errors"]))
        finally:
            conn.close()

    def test_revert_buy_only_batch(self):
        # Subimos un CSV con solo compras + depósito → debe permitir revert
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,IBKR,AAPL,10,180,,,,2,USD,
2024-02-01,DEPOSITO,IBKR,,,,5000,,,,USD,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="x.csv",
                    broker_hint="IBKR", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw_map, helpers=_helpers())
            # Confirmar que la posición existe
            n_pos = conn.execute("SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0", (self.uid,)).fetchone()["c"]
            self.assertEqual(n_pos, 1)

            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=session_id, helpers=_helpers())

            n_pos_after = conn.execute("SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0", (self.uid,)).fetchone()["c"]
            self.assertEqual(n_pos_after, 0)
            batch = conn.execute("SELECT status FROM import_batches WHERE id=?", (session_id,)).fetchone()
            self.assertEqual(batch["status"], "reverted")
        finally:
            conn.close()

    def test_revert_with_sell_blocked(self):
        # Si el batch incluye venta, no se puede revertir
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=_read_fixture("generic_basic.csv"),
                    file_name="x.csv", broker_hint="IBKR", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw_map, helpers=_helpers())
            with self.assertRaises(ps.PersistError):
                with conn:
                    ps.revert_batch(conn, uid=self.uid, batch_id=session_id, helpers=_helpers())
        finally:
            conn.close()


class MapperTest(unittest.TestCase):
    def test_autodetect_basic_es_headers(self):
        m = mp.autodetect_mapping(["fecha", "tipo", "broker", "activo", "cantidad", "precio"])
        self.assertEqual(m.columns["fecha"], "fecha")
        self.assertEqual(m.columns["tipo"], "tipo")
        self.assertEqual(m.columns["activo"], "activo")

    def test_autodetect_english_headers(self):
        m = mp.autodetect_mapping(["Trade Date", "Action", "Symbol", "Quantity", "Price", "Commission"])
        self.assertEqual(m.columns["fecha"], "Trade Date")
        self.assertEqual(m.columns["tipo"], "Action")
        self.assertEqual(m.columns["activo"], "Symbol")
        self.assertEqual(m.columns["cantidad"], "Quantity")
        self.assertEqual(m.columns["precio"], "Price")
        self.assertEqual(m.columns["comisiones"], "Commission")

    def test_autodetect_partial_match_leaves_blank(self):
        m = mp.autodetect_mapping(["foo", "bar"])
        self.assertNotIn("fecha", m.columns)
        self.assertNotIn("tipo", m.columns)

    def test_autodetect_underscore_headers(self):
        # Headers típicos de exports CSV con underscores (no espacios)
        m = mp.autodetect_mapping([
            "date", "operation_type", "asset_symbol", "asset_name", "asset_type",
            "quantity", "unit_price", "gross_amount", "fees", "taxes",
            "currency", "settlement_currency", "notes",
        ])
        self.assertEqual(m.columns["fecha"], "date")
        self.assertEqual(m.columns["tipo"], "operation_type")
        self.assertEqual(m.columns["activo"], "asset_symbol")
        self.assertEqual(m.columns["cantidad"], "quantity")
        self.assertEqual(m.columns["precio"], "unit_price")
        self.assertEqual(m.columns["monto"], "gross_amount")
        self.assertEqual(m.columns["comisiones"], "fees")
        self.assertEqual(m.columns["moneda"], "currency")
        self.assertEqual(m.columns["notas"], "notes")

    def test_inspect_returns_headers_and_sample(self):
        content = _read_fixture("ibkr_export.csv").decode()
        info = mp.inspect_csv(content, sample_size=3)
        self.assertEqual(info["headers"][:3], ["Trade Date", "Action", "Symbol"])
        self.assertEqual(len(info["sample_rows"]), 3)
        self.assertIn("fecha", info["suggested_mapping"]["columns"])

    def test_apply_mapping_translates_to_internal_format(self):
        content = _read_fixture("ibkr_export.csv").decode()
        mapping = mp.Mapping(
            columns={
                "fecha": "Trade Date",
                "tipo": "Action",
                "activo": "Symbol",
                "cantidad": "Quantity",
                "precio": "Price",
                "comisiones": "Commission",
                "moneda": "Currency",
                "notas": "Description",
            },
            defaults={"broker": "IBKR"},
        )
        translated, err = mp.apply_mapping(content, mapping)
        self.assertIsNone(err)
        self.assertIn("fecha,tipo,broker,activo", translated.split("\n")[0])
        # Una fila debería tener IBKR como broker (default) y "BUY" como tipo
        self.assertIn("IBKR", translated)
        self.assertIn("BUY", translated)

    def test_apply_mapping_missing_required_field(self):
        # Falta el campo broker (required + allow_default), no en columns ni defaults
        mapping = mp.Mapping(columns={"fecha": "Trade Date", "tipo": "Action"})
        _, err = mp.apply_mapping("Trade Date,Action\n2024-01-01,BUY\n", mapping)
        self.assertIsNotNone(err)
        self.assertIn("Broker", err)


class IBKRImportE2ETest(unittest.TestCase):
    """End-to-end con un CSV estilo IBKR + mapping confirmado por el usuario."""

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="ibkr_test@rendi.test")
        _add_broker(conn, self.uid, "IBKR", "USDT")
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "IBKR", "USDT", 50000),
        )
        conn.commit()
        conn.close()

    def test_preview_with_ibkr_mapping(self):
        conn = main.get_db()
        try:
            mapping = {
                "columns": {
                    "fecha": "Trade Date",
                    "tipo": "Action",
                    "activo": "Symbol",
                    "cantidad": "Quantity",
                    "precio": "Price",
                    "monto": "Amount",
                    "comisiones": "Commission",
                    "moneda": "Currency",
                    "notas": "Description",
                },
                "defaults": {"broker": "IBKR"},
            }
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid,
                    file_bytes=_read_fixture("ibkr_export.csv"),
                    file_name="ibkr_export.csv",
                    broker_hint="IBKR", parser_format=None, mapping=mapping,
                )
            self.assertNotIn("error", payload)
            # 4 filas: 2 BUY (con Bought y BUY), 1 Sold, 1 Deposit. Todas válidas.
            self.assertEqual(payload["summary"]["valid_rows"], 4)
            self.assertEqual(payload["summary"]["invalid_rows"], 0)
            ops = {it["type"] for it in payload["summary"]["by_operation_type"]}
            self.assertIn("BUY", ops)
            self.assertIn("SELL", ops)
            self.assertIn("DEPOSIT", ops)
        finally:
            conn.close()


class CurrencyRoutingTest(unittest.TestCase):
    """ARS broker con route_by_currency=True debe rutear filas USD al sub-broker."""

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="cocos_test@rendi.test")
        _add_broker(conn, self.uid, "Cocos capital", "ARS")
        # Cash inicial ARS
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "Cocos capital", "ARS", 5_000_000),
        )
        conn.commit()
        conn.close()

    def test_fx_usd_to_ars_routes_from_sibling(self):
        # FX_USD_TO_ARS debe partir del sibling USD aunque la fila diga currency=ARS.
        # Setup: pre-crear cash USD en el sibling para que la conversión tenga fondos.
        conn = main.get_db()
        try:
            parent = conn.execute(
                "SELECT * FROM brokers WHERE name=? AND user_id=?", ("Cocos capital", self.uid)
            ).fetchone()
            sibling_name = "Cocos capital · USD"
            conn.execute(
                "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
                (self.uid, sibling_name, "USDT", parent["id"]),
            )
            conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, invested, tc_compra)
                   VALUES (?,?,?,1,?,?)""",
                (self.uid, sibling_name, "USDT", 500, 1100),
            )
            conn.commit()

            csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-03-15,CONVERSION_USD_ARS,Cocos capital,,,,240000,200,1200,0,ARS,Vendo USD por ARS
"""
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="fx.csv",
                    broker_hint="Cocos capital", parser_format="rendi_generic",
                    route_by_currency=True,
                )
            self.assertEqual(payload["summary"]["valid_rows"], 1)
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw_map, helpers=_helpers())
            # ARS cash del padre debe haber subido en 240000
            ars_cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                (self.uid, "Cocos capital"),
            ).fetchone()
            self.assertGreaterEqual(ars_cash["invested"], 5_000_000 + 240_000 - 1)
            # USD cash del sibling debe haber bajado en 200
            usd_cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                (self.uid, sibling_name),
            ).fetchone()
            self.assertEqual(usd_cash["invested"], 300)
        finally:
            conn.close()

    def test_route_usd_rows_to_sibling(self):
        # CSV con mezcla ARS + USD desde un broker ARS. Compras CEDEAR pagadas
        # en USD deben ir al sub-broker auto-creado.
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,Cocos capital,GGAL,100,1500,,,,0,ARS,Compra acciones AR
2024-02-01,COMPRA,Cocos capital,AAPL,5,180,,,,0,USD,CEDEAR pagado en USD
2024-03-10,DEPOSITO,Cocos capital,,,,500,,,,USD,Aporte USD del exterior
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="cocos_mix.csv",
                    broker_hint="Cocos capital", parser_format="rendi_generic",
                    route_by_currency=True,
                )
            self.assertTrue(payload["route_by_currency"])
            self.assertEqual(payload["routing_summary"]["ars_rows_to_parent"], 1)
            self.assertEqual(payload["routing_summary"]["usd_rows_to_sibling"], 2)
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw_map, helpers=_helpers())
            # Sub-broker debería existir
            sibling = conn.execute(
                "SELECT * FROM brokers WHERE user_id=? AND parent_broker_id=(SELECT id FROM brokers WHERE name='Cocos capital' AND user_id=?)",
                (self.uid, self.uid),
            ).fetchone()
            self.assertIsNotNone(sibling, "Sub-broker USD debió ser auto-creado")
            self.assertEqual(sibling["currency"], "USDT")

            # GGAL debe estar en el broker padre (ARS)
            ggal = conn.execute(
                "SELECT broker FROM positions WHERE user_id=? AND asset='GGAL' AND is_cash=0",
                (self.uid,),
            ).fetchone()
            self.assertEqual(ggal["broker"], "Cocos capital")

            # AAPL debe estar en el sub-broker (USD)
            aapl = conn.execute(
                "SELECT broker FROM positions WHERE user_id=? AND asset='AAPL' AND is_cash=0",
                (self.uid,),
            ).fetchone()
            self.assertEqual(aapl["broker"], sibling["name"])

            # Cash USD del sub-broker debe reflejar el depósito
            usd_cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                (self.uid, sibling["name"]),
            ).fetchone()
            # 500 (deposit) - cualquier compra USD que haya consumido cash del sibling
            # En este caso AAPL se compró antes del deposit (orden cronológico).
            # AAPL costó 5 * 180 = 900 → cash USD se va a -900 con la compra,
            # después +500 con depósito → -400. El sistema permite negativos.
            self.assertIsNotNone(usd_cash)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
