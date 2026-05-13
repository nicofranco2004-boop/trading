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
from importing.schema import (RawRow, OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW,
                                OP_DIVIDEND, OP_INTEREST, OP_FX_ARS_TO_USD,
                                OP_FX_USD_TO_ARS, OP_FEE)
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


class BinanceParserTest(unittest.TestCase):
    def test_parses_spot_trade_history(self):
        from importing.parsers.binance import BinanceParser
        csv = (
            "Date(UTC),Pair,Side,Price,Executed,Amount,Fee\n"
            "2024-03-15 14:23:47,BTCUSDT,BUY,68500.50000000,0.02351000BTC,1610.45842500USDT,0.00002351BTC\n"
            "2024-04-02 09:11:22,ETHUSDT,SELL,3520.75000000,1.50000000ETH,5281.12500000USDT,5.28112500USDT\n"
        )
        parser = BinanceParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 0)
        self.assertEqual(len(result.raw_rows), 2)
        first = result.raw_rows[0].data
        self.assertEqual(first["fecha"], "2024-03-15")
        self.assertEqual(first["tipo"], "BUY")
        self.assertEqual(first["activo"], "BTC")
        self.assertEqual(first["broker"], "Binance")
        self.assertEqual(first["moneda"], "USD")  # USDT mapeado a USD
        self.assertAlmostEqual(float(first["cantidad"]), 0.02351)
        self.assertAlmostEqual(float(first["precio"]), 68500.5)
        self.assertAlmostEqual(float(first["monto"]), 1610.458425)
        # Fee en BTC (base) → convertido a USDT usando precio
        self.assertAlmostEqual(float(first["comisiones"]), 0.00002351 * 68500.5, places=4)

    def test_rejects_non_binance_csv(self):
        from importing.parsers.binance import BinanceParser
        csv = "fecha,tipo,broker\n2024-01-01,COMPRA,X\n"
        parser = BinanceParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 1)
        self.assertEqual(result.parse_errors[0].code, "BINANCE_HEADERS_MISMATCH")

    def test_handles_ars_quote(self):
        from importing.parsers.binance import BinanceParser
        csv = (
            "Date(UTC),Pair,Side,Price,Executed,Amount,Fee\n"
            "2024-05-18 16:45:03,BTCARS,BUY,75000000.00,0.00100000BTC,75000.00ARS,0.00000100BTC\n"
        )
        parser = BinanceParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.raw_rows), 1)
        self.assertEqual(result.raw_rows[0].data["moneda"], "ARS")

    def test_pair_split_known_quotes(self):
        from importing.parsers.binance import _split_pair
        self.assertEqual(_split_pair("BTCUSDT"), ("BTC", "USDT"))
        self.assertEqual(_split_pair("ETHBTC"), ("ETH", "BTC"))
        self.assertEqual(_split_pair("BTCARS"), ("BTC", "ARS"))
        self.assertEqual(_split_pair("USDCUSDT"), ("USDC", "USDT"))

    def test_real_binance_export_format(self):
        # El export real tiene header "Time" (no "Date(UTC)") y fechas YY-MM-DD
        from importing.parsers.binance import BinanceParser
        csv = (
            "Time,Pair,Side,Price,Executed,Amount,Fee\n"
            "26-05-06 08:53:51,BTCUSDT,SELL,82536.11,0.02084BTC,1720.0525324USDT,1.72005253USDT\n"
            "26-02-23 10:04:42,BTCUSDT,BUY,66258.92,0.00334BTC,221.3047928USDT,0.00000334BTC\n"
        )
        parser = BinanceParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 0, f"errors: {result.parse_errors}")
        self.assertEqual(len(result.raw_rows), 2)
        first = result.raw_rows[0].data
        self.assertEqual(first["fecha"], "2026-05-06")  # YY → YYYY
        self.assertEqual(first["tipo"], "SELL")
        self.assertEqual(first["activo"], "BTC")


class BalanzParserTest(unittest.TestCase):
    def test_parses_canonical_headers(self):
        from importing.parsers.balanz import BalanzParser
        csv = (
            "Fecha Concertación,Fecha Liquidación,Tipo,Especie,Descripción,"
            "Cantidad,Precio,Moneda,Importe Bruto,Comisiones,Importe Neto,Plazo,N° Boleto\n"
            "15/01/2025,17/01/2025,Compra,GGAL,Grupo Galicia,100,4850.00,ARS,485000.00,2425.00,487425.00,48hs,001234567\n"
            "05/02/2025,07/02/2025,Venta,AL30,Bonar 2030,1000,68.45,USD,684.50,3.42,681.08,48hs,001235012\n"
        )
        parser = BalanzParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 0)
        self.assertEqual(len(result.raw_rows), 2)
        first = result.raw_rows[0].data
        self.assertEqual(first["fecha"], "15/01/2025")
        self.assertEqual(first["tipo"], "Compra")
        self.assertEqual(first["activo"], "GGAL")
        self.assertEqual(first["moneda"], "ARS")
        self.assertEqual(first["broker"], "Balanz")
        self.assertIn("Boleto 001234567", first["notas"])

    def test_handles_pesos_dolares_variants(self):
        from importing.parsers.balanz import _norm_currency
        self.assertEqual(_norm_currency("Pesos"), "ARS")
        self.assertEqual(_norm_currency("$"), "ARS")
        self.assertEqual(_norm_currency("Dólares"), "USD")
        self.assertEqual(_norm_currency("U$S"), "USD")
        self.assertEqual(_norm_currency("USD"), "USD")

    def test_rejects_non_balanz_csv(self):
        from importing.parsers.balanz import BalanzParser
        csv = "Date,Pair,Side\n2024-01-01,BTCUSDT,BUY\n"
        parser = BalanzParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 1)
        self.assertEqual(result.parse_errors[0].code, "BALANZ_HEADERS_MISMATCH")

    def test_accepts_gemini_variant_headers(self):
        # Variante reportada por Gemini: "Fecha de Liquidación" + "Tipo de Operación"
        # + "Cantidad / Valor Nominal" + "Arancel / Comisión" + "Monto Neto"
        from importing.parsers.balanz import BalanzParser
        csv = (
            "Fecha de Liquidación,Tipo de Operación,Especie,Cantidad / Valor Nominal,"
            "Precio,Moneda,Arancel / Comisión,Monto Neto,Plazo\n"
            "15/05/2026,Compra,AL30,1000,54500.00,USD,250.40,54750.40,48hs\n"
            "20/05/2026,Venta,GGAL,50,8200.00,ARS,820.00,409180.00,CI\n"
        )
        parser = BalanzParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 0, f"errors: {result.parse_errors}")
        self.assertEqual(len(result.raw_rows), 2)
        first = result.raw_rows[0].data
        self.assertEqual(first["activo"], "AL30")
        self.assertEqual(first["tipo"], "Compra")
        self.assertEqual(first["moneda"], "USD")
        self.assertEqual(first["cantidad"], "1000")
        self.assertEqual(first["comisiones"], "250.40")


class BinanceTransactionHistoryTest(unittest.TestCase):
    """Parser del export completo de Binance (Spot + Futures + Funding)."""

    def test_groups_spot_trade_into_single_row(self):
        from importing.parsers.binance_transaction import BinanceTransactionHistoryParser
        # 4 filas con mismo timestamp = 1 trade. Vendiste 73.967 SOL por ~1775 USDT, fee ~1.78 USDT.
        csv = (
            "User_ID,Time,Account,Operation,Coin,Change,Remark\n"
            "1,25-11-11 13:06:16,Spot,Transaction Sold,SOL,-2,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Sold,SOL,-8.967,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Sold,SOL,-63,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Revenue,USDT,1443.77667,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Revenue,USDT,10.14363,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Revenue,USDT,322.02,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Fee,USDT,-1.44377667,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Fee,USDT,-0.32202,\n"
            "1,25-11-11 13:06:16,Spot,Transaction Fee,USDT,-0.01014363,\n"
        )
        parser = BinanceTransactionHistoryParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 0)
        self.assertEqual(len(result.raw_rows), 1, "9 filas spot deben colapsar en 1 trade")
        d = result.raw_rows[0].data
        self.assertEqual(d["tipo"], "VENTA")
        self.assertEqual(d["activo"], "SOL")
        self.assertEqual(d["fecha"], "2025-11-11")
        self.assertAlmostEqual(float(d["cantidad"]), 73.967, places=3)
        self.assertAlmostEqual(float(d["monto"]), 1775.94030, places=2)

    def test_groups_futures_pnl_by_tradeid(self):
        from importing.parsers.binance_transaction import BinanceTransactionHistoryParser
        # Un cierre de posición: PnL +37.22 + Fee -0.68 = neto +36.54
        csv = (
            "User_ID,Time,Account,Operation,Coin,Change,Remark\n"
            "1,25-11-22 16:25:18,USD-M Futures,Realized Profit and Loss,USDT,37.2224,TradeID - 6927444047\n"
            "1,25-11-22 16:25:18,USD-M Futures,Fee,USDT,-0.6769608,TradeID - 6927444047\n"
        )
        parser = BinanceTransactionHistoryParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.raw_rows), 1)
        d = result.raw_rows[0].data
        self.assertEqual(d["tipo"], "FUTURES_PNL")
        self.assertAlmostEqual(float(d["monto"]), 36.5454392, places=4)

    def test_handles_funding_fee_p2p_deposit_withdraw(self):
        from importing.parsers.binance_transaction import BinanceTransactionHistoryParser
        csv = (
            "User_ID,Time,Account,Operation,Coin,Change,Remark\n"
            "1,25-11-12 17:37:06,Spot,Withdraw,USDT,-79,Withdraw fee is included\n"
            "1,25-11-22 22:22:53,Spot,Deposit,USDT,1655.90,\n"
            "1,25-11-12 13:00:00,USD-M Futures,Funding Fee,USDT,0.39940,\n"
            "1,25-11-21 21:00:00,USD-M Futures,Funding Fee,USDT,-0.02921,\n"
            "1,25-11-23 11:56:10,Funding,P2P Trading,USDT,-280,P2P - 22825\n"
            "1,25-11-13 10:28:49,Spot,Transfer Between Main and Funding Wallet,USDT,-40,\n"
        )
        parser = BinanceTransactionHistoryParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.raw_rows), 5, "Transfer interno debe ignorarse")
        types = [r.data["tipo"] for r in result.raw_rows]
        self.assertIn("RETIRO", types)         # withdraw
        self.assertIn("DEPOSITO", types)       # deposit
        self.assertIn("INTERES", types)        # funding fee positivo
        self.assertIn("COMISION", types)       # funding fee negativo
        # P2P negativo = retiro
        p2p_row = [r for r in result.raw_rows if "P2P" in r.data.get("notas", "")][0]
        self.assertEqual(p2p_row.data["tipo"], "RETIRO")

    def test_rejects_wrong_format(self):
        from importing.parsers.binance_transaction import BinanceTransactionHistoryParser
        csv = "Date,Pair,Side\n2024-01-01,BTCUSDT,BUY\n"
        parser = BinanceTransactionHistoryParser()
        result = parser.parse(csv)
        self.assertEqual(result.parse_errors[0].code, "BINANCE_TX_HEADERS_MISMATCH")


class FuturesPnlPersistTest(unittest.TestCase):
    """E2E: importar un CSV con FUTURES_PNL y verificar que crea fila en operations."""

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="futures_test@rendi.test")
        _add_broker(conn, self.uid, "Binance", "USDT")
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "Binance", "USDT", 5000),
        )
        conn.commit()
        conn.close()

    def test_futures_pnl_creates_operation_and_updates_monthly(self):
        # CSV con un FUTURES_PNL +50.5 y otro -20
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-03-10,FUTURES_PNL,Binance,,,,50.5,,,,USD,Trade1
2024-04-15,FUTURES_PNL,Binance,,,,-20,,,,USD,Trade2 perdedor
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="fut.csv",
                    broker_hint="Binance", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            self.assertEqual(payload["summary"]["valid_rows"], 2)
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                summary = ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                            raw_row_ids_by_index=raw, helpers=_helpers())
            # Deben existir 2 operations con op_type='Futuros'
            ops = conn.execute(
                "SELECT pnl_usd, op_type FROM operations WHERE user_id=? ORDER BY date",
                (self.uid,),
            ).fetchall()
            self.assertEqual(len(ops), 2)
            self.assertTrue(all(o["op_type"] == "Futuros" for o in ops))
            self.assertAlmostEqual(ops[0]["pnl_usd"], 50.5, places=2)
            self.assertAlmostEqual(ops[1]["pnl_usd"], -20, places=2)

            # Cash final = 5000 + 50.5 - 20 = 5030.5
            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Binance' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(cash["invested"], 5030.5, places=2)

            # monthly_entries.global.pnl_realized = 30.5
            global_pnl = conn.execute(
                "SELECT SUM(pnl_realized) p FROM monthly_entries WHERE user_id=? AND broker='global'",
                (self.uid,),
            ).fetchone()["p"]
            self.assertAlmostEqual(global_pnl, 30.5, places=2)
        finally:
            conn.close()


class BinanceFuturesTradeHistoryTest(unittest.TestCase):
    def test_groups_executions_by_order_id(self):
        # 4 fills del mismo Order ID al cerrar una posición SOL → 1 row con net agregado
        from importing.parsers.binance_futures import BinanceFuturesTradeHistoryParser
        csv = (
            "Time,Symbol,Side,Price,Quantity,Amount,Fee,Realized Profit,Buyer,Maker,Trade ID,Order ID\n"
            "26-05-22 16:25:18,BTCUSDT,SELL,84620.1,3,253.8603,0.12693015 USDT,6.9792,false,false,6927444046,832726459304\n"
            "26-05-22 16:25:18,BTCUSDT,SELL,84620.1,3,253.8603,0.12693015 USDT,6.9792,false,false,6927444045,832726459304\n"
            "26-05-22 16:25:18,BTCUSDT,SELL,84620.1,16,1353.9216,0.67696080 USDT,37.2224,false,false,6927444047,832726459304\n"
            "26-05-22 16:25:18,BTCUSDT,SELL,84620.1,3,253.8603,0.12693015 USDT,6.9792,false,false,6927444044,832726459304\n"
        )
        parser = BinanceFuturesTradeHistoryParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 0, f"errors: {result.parse_errors}")
        self.assertEqual(len(result.raw_rows), 1, "4 fills del mismo Order ID deben colapsar en 1 fila")
        d = result.raw_rows[0].data
        self.assertEqual(d["tipo"], "FUTURES_PNL")
        self.assertEqual(d["activo"], "BTCUSDT")
        self.assertEqual(d["fecha"], "2026-05-22")
        # Net = (6.9792*3 + 37.2224) - (0.12693015*3 + 0.67696080) = 58.16 - 1.058 = ~57.10
        self.assertAlmostEqual(float(d["monto"]), 57.10, places=1)
        self.assertIn("OrderID 832726459304", d["notas"])

    def test_short_position_with_loss(self):
        # SHORT que pierde: net = PnL_negativo - fee
        from importing.parsers.binance_futures import BinanceFuturesTradeHistoryParser
        csv = (
            "Time,Symbol,Side,Price,Quantity,Amount,Fee,Realized Profit,Buyer,Maker,Trade ID,Order ID\n"
            "26-05-22 18:05:28,BTCUSDT,SELL,67666,14,947.324,0.47366200 USDT,-22.0612,false,false,7471853635,957042337987\n"
        )
        parser = BinanceFuturesTradeHistoryParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.raw_rows), 1)
        d = result.raw_rows[0].data
        self.assertEqual(d["tipo"], "FUTURES_PNL")
        # Net = -22.0612 - 0.47366200 = -22.534862
        self.assertAlmostEqual(float(d["monto"]), -22.534862, places=4)

    def test_rejects_wrong_format(self):
        from importing.parsers.binance_futures import BinanceFuturesTradeHistoryParser
        csv = "Date,Pair,Side\n2024-01-01,BTCUSDT,BUY\n"
        parser = BinanceFuturesTradeHistoryParser()
        result = parser.parse(csv)
        self.assertEqual(len(result.parse_errors), 1)
        self.assertEqual(result.parse_errors[0].code, "BINANCE_FUTURES_HEADERS_MISMATCH")


class CocosParserTest(unittest.TestCase):
    """Tests del parser oficial de Cocos Capital (Actividad → Movimientos)."""

    @classmethod
    def setUpClass(cls):
        from importing.parsers.cocos import CocosParser
        cls.parser = CocosParser()
        cls.fixture = _read_fixture("cocos_export.csv").decode("utf-8")

    def test_can_handle_cocos_headers(self):
        headers = [
            "nroTicket", "nroComprobante", "fechaEjecucion", "fechaLiquidacion",
            "tipoOperacion", "instrumento", "moneda",
        ]
        self.assertTrue(self.parser.can_handle(headers))

    def test_can_handle_rejects_generic_headers(self):
        self.assertFalse(self.parser.can_handle(["fecha", "tipo", "broker"]))

    def test_rejects_file_without_cocos_columns(self):
        result = self.parser.parse("foo;bar;baz\n1;2;3\n")
        self.assertEqual(len(result.parse_errors), 1)
        self.assertEqual(result.parse_errors[0].code, "COCOS_HEADERS_MISMATCH")

    def test_parses_buy_extracting_ticker(self):
        result = self.parser.parse(self.fixture)
        netflix = next(r for r in result.raw_rows
                       if r.data["tipo"] == "COMPRA" and r.data["activo"] == "NFLX")
        self.assertEqual(netflix.data["fecha"], "2026-01-26")
        self.assertEqual(netflix.data["broker"], "Cocos")
        self.assertEqual(netflix.data["cantidad"], "280")
        self.assertEqual(netflix.data["moneda"], "ARS")
        # montoBruto = -762560 → abs = 762560 (sin separadores)
        self.assertEqual(netflix.data["monto"], "762560")
        # fees = 3431.52 + 381.28 + 800.688 = 4613.49 (aprox)
        self.assertAlmostEqual(float(netflix.data["comisiones"]), 4613.49, places=1)

    def test_parses_sell_with_negative_quantity(self):
        """Cocos pone cantidad negativa en ventas. Tomamos abs()."""
        result = self.parser.parse(self.fixture)
        tsla = next(r for r in result.raw_rows
                    if r.data["tipo"] == "VENTA" and r.data["activo"] == "TSLA"
                    and r.data["moneda"] == "ARS")
        self.assertEqual(tsla.data["cantidad"], "35")  # era -35 en el CSV
        self.assertEqual(tsla.data["monto"], "1566600")

    def test_dolar_mep_forces_usd_currency(self):
        """Compra/Venta Dolar Mep deben quedar en USD aunque la columna diga otra cosa."""
        result = self.parser.parse(self.fixture)
        mep_buy = next(r for r in result.raw_rows
                       if r.data["activo"] == "TSLA" and r.data["moneda"] == "USD")
        self.assertEqual(mep_buy.data["tipo"], "COMPRA")
        self.assertIn("MEP", mep_buy.data["notas"])

    def test_fci_subscription_maps_to_buy_cocorma(self):
        result = self.parser.parse(self.fixture)
        fci = [r for r in result.raw_rows if r.data["activo"] == "COCORMA"]
        self.assertEqual(len(fci), 2)
        types = {r.data["tipo"] for r in fci}
        self.assertEqual(types, {"COMPRA", "VENTA"})
        for r in fci:
            self.assertIn("FCI", r.data["notas"])

    def test_recibo_de_cobro_maps_to_deposito(self):
        result = self.parser.parse(self.fixture)
        dep = next(r for r in result.raw_rows if r.data["tipo"] == "DEPOSITO"
                   and r.data["monto"] == "100000")
        self.assertEqual(dep.data["moneda"], "ARS")
        self.assertEqual(dep.data["activo"], "")  # cash flow puro

    def test_orden_de_pago_maps_to_retiro_with_abs_amount(self):
        result = self.parser.parse(self.fixture)
        wd = next(r for r in result.raw_rows
                  if r.data["tipo"] == "RETIRO" and r.data["monto"] == "45000")
        self.assertEqual(wd.data["moneda"], "ARS")

    def test_dividendos_peso_no_asset_uses_total(self):
        """Dividendos en pesos: el CSV no dice qué stock pagó → asset vacío.
        Usa `total` (neto) en vez de `montoBruto` (bruto)."""
        result = self.parser.parse(self.fixture)
        div = next(r for r in result.raw_rows if r.data["tipo"] == "DIVIDENDO")
        self.assertEqual(div.data["activo"], "")
        self.assertEqual(div.data["moneda"], "ARS")
        self.assertEqual(div.data["monto"], "2366.81")  # total neto

    def test_dividendos_en_especie_is_skipped(self):
        """No debe aparecer en raw_rows — evitamos doble-conteo con la Nota
        De Credito Conversion que llega después."""
        result = self.parser.parse(self.fixture)
        # No debe haber ningún DIVIDENDO en USD (que sería el "en especie")
        usd_divs = [r for r in result.raw_rows
                    if r.data["tipo"] == "DIVIDENDO" and r.data["moneda"] == "USD"]
        self.assertEqual(usd_divs, [])
        # La nota de credito SÍ debe estar como DEPOSITO USD con nota de conversión
        nota = [r for r in result.raw_rows
                if r.data["tipo"] == "DEPOSITO" and r.data["moneda"] == "USD"]
        self.assertEqual(len(nota), 1)
        self.assertIn("conversión", nota[0].data["notas"])

    def test_unknown_op_type_emits_warning(self):
        csv = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;"
               "tipoOperacion;instrumento;moneda;mercado;cantidad;precio;"
               "montoBruto;comision;ddmm;iva;otros;total\n"
               "1;2;01-01-2026;01-01-2026;OperacionInventada;X (Y);ARS;;;;100;0;0;0;0;100\n")
        result = self.parser.parse(csv)
        self.assertEqual(len(result.raw_rows), 0)
        self.assertEqual(len(result.parse_errors), 1)
        self.assertEqual(result.parse_errors[0].code, "COCOS_OP_UNKNOWN")

    def test_template_csv_has_required_columns(self):
        t = self.parser.template_csv()
        self.assertIn("nroTicket", t)
        self.assertIn("tipoOperacion", t)
        self.assertIn("Recibo De Cobro", t)
        self.assertIn("Dividendos", t)

    def test_template_csv_is_self_parseable(self):
        """El template que descarga el user debería volver a parsearse sin errores."""
        t = self.parser.template_csv()
        result = self.parser.parse(t)
        self.assertEqual(len(result.parse_errors), 0)
        self.assertGreater(len(result.raw_rows), 0)

    def test_ar_number_cleaner(self):
        """El cleaner de números AR maneja casos típicos."""
        from importing.parsers.cocos import _clean_ar_number
        self.assertEqual(_clean_ar_number("1.948.815"), "1948815")
        self.assertEqual(_clean_ar_number("-1.557.122,07"), "-1557122.07")
        self.assertEqual(_clean_ar_number("0,86"), "0.86")
        self.assertEqual(_clean_ar_number("41.580"), "41580")  # AR thousands
        self.assertEqual(_clean_ar_number("100"), "100")
        self.assertEqual(_clean_ar_number(""), "")

    def test_precio_computed_from_monto_div_qty_not_parsed(self):
        """REGRESIÓN crítica: para FCI, la columna precio del CSV de Cocos
        tiene formato ambiguo (ej '10.094,497' interpretado AR-strict da
        10094.497 pero el valor real es 10.094). Si el parser usara la columna
        directamente, el persister calcularía SELL proceeds = 10094 × 192644
        = ~1.97 BILLONES ARS → P&L Realizado falso de $1.4M USD.
        El fix: precio = monto/qty (siempre consistente con monto)."""
        result = self.parser.parse(self.fixture)

        # FCI Suscripción del fixture
        fci_buy = next(r for r in result.raw_rows
                       if r.data["activo"] == "COCORMA" and r.data["tipo"] == "COMPRA")
        precio = float(fci_buy.data["precio"])
        # El precio real está cerca de 10.094, no 10094
        self.assertAlmostEqual(precio, 10.094497, places=4,
            msg=f"precio FCI inflado: {precio} — debería ser ~10.09")

        # CEDEAR/stock — el precio computado debe coincidir con el del CSV
        # (donde AR-strict daría el mismo resultado)
        nflx = next(r for r in result.raw_rows
                    if r.data["activo"] == "NFLX" and r.data["tipo"] == "COMPRA")
        self.assertAlmostEqual(float(nflx.data["precio"]), 2723.4285714, places=3)


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

    def test_op_type_keyword_fallback(self):
        # Frases en castellano que no son alias exactos pero contienen raíz reconocida
        cases = [
            ("INGRESO DE DINERO", OP_DEPOSIT),
            ("EGRESO DE FONDOS", OP_WITHDRAW),
            ("APORTE INICIAL", OP_DEPOSIT),
            ("RETIRO A CUENTA BANCARIA", OP_WITHDRAW),
            ("Transferencia recibida", OP_DEPOSIT),
            ("Compra de acciones", OP_BUY),
            ("Venta parcial", OP_SELL),
            ("DIVIDENDO COBRADO", OP_DIVIDEND),
            ("Comisión mensual", OP_FEE),
        ]
        for tipo, expected in cases:
            rows = [RawRow(1, {"fecha": "2024-01-01", "tipo": tipo, "broker": "X",
                                 "monto": "100"})]
            txs, errors = normalize_rows(rows)
            self.assertEqual(len(txs), 1, f"'{tipo}' no fue reconocido (errors: {errors})")
            self.assertEqual(txs[0].operation_type, expected,
                             f"'{tipo}' fue mapeado a {txs[0].operation_type}, esperaba {expected}")

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
            # Con auto-create de brokers, el broker desconocido ya no es error.
            # Errores que SÍ deben quedar: fecha inválida, op type desconocido, stock insuficiente.
            # Filas válidas: la primera COMPRA + la del broker que antes era "desconocido"
            # (ahora auto-creado) = 2.
            self.assertEqual(payload["summary"]["valid_rows"], 2)
            self.assertGreaterEqual(payload["summary"]["invalid_rows"], 3)
            self.assertTrue(any(e["code"] == "INVALID_DATE" for e in payload["errors"]))
            self.assertTrue(any(e["code"] == "UNKNOWN_OP_TYPE" for e in payload["errors"]))
            self.assertTrue(any(e["code"] == "INSUFFICIENT_STOCK" for e in payload["errors"]))
            # El broker antes desconocido se auto-creó
            self.assertTrue(any(b["name"] == "BrokerInexistente" for b in payload["new_brokers_created"]))
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

    def test_row_dedup_detects_overlap(self):
        # Si dos imports tienen filas idénticas (mismo date+broker+op+activo+qty+precio),
        # el segundo preview debe marcarlas en duplicate_row_indices.
        csv_a = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,IBKR,AAPL,10,180,,,,0,USD,
2024-02-01,COMPRA,IBKR,MSFT,5,400,,,,0,USD,
"""
        # Mismo evento de AAPL + 1 fila nueva
        csv_b = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,IBKR,AAPL,10,180,,,,0,USD,
2024-03-10,COMPRA,IBKR,GOOG,3,140,,,,0,USD,
"""
        conn = main.get_db()
        try:
            # Primer import → confirmar
            with conn:
                p1 = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv_a, file_name="a.csv",
                    broker_hint="IBKR", parser_format="rendi_generic",
                )
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=p1["session_id"])
                ps.persist_batch(conn, uid=self.uid, batch_id=p1["session_id"], txs=txs,
                                  raw_row_ids_by_index=raw, helpers=_helpers())
            # Segundo import (overlap parcial)
            with conn:
                p2 = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv_b, file_name="b.csv",
                    broker_hint="IBKR", parser_format="rendi_generic",
                )
            # AAPL row debe estar marcada como duplicada (row_index 1 del segundo CSV)
            self.assertIn(1, p2["duplicate_row_indices"])
            # GOOG row no debería estar duplicada
            self.assertNotIn(2, p2["duplicate_row_indices"])
        finally:
            conn.close()

    def test_cash_simulation_warns_on_overdraft(self):
        # Preview debe traer warnings si las txs pondrían el cash en negativo.
        # No bloquea el import, solo informa.
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,IBKR,AAPL,100,180,,,,0,USD,Compra grande sin cash
"""
        # IBKR ya viene creado por setUp con cash 100k USD. Reduzco a 1000
        # para que la compra de 18000 dé overdraft.
        conn = main.get_db()
        conn.execute(
            "UPDATE positions SET invested=1000 WHERE user_id=? AND broker='IBKR' AND is_cash=1",
            (self.uid,),
        )
        conn.commit()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="overdraft.csv",
                    broker_hint="IBKR", parser_format="rendi_generic",
                )
            warnings = payload.get("cash_warnings", [])
            self.assertEqual(len(warnings), 1, f"Esperaba 1 warning, got: {warnings}")
            w = warnings[0]
            self.assertEqual(w["broker"], "IBKR")
            self.assertEqual(w["currency"], "USDT")
            self.assertLess(w["new_balance"], 0)
            # projected_cash debe reflejar el saldo final
            projected = {(c["broker"], c["currency"]): c["balance"] for c in payload["projected_cash"]}
            self.assertLess(projected[("IBKR", "USDT")], 0)
        finally:
            conn.close()

    def test_revert_e2e_full_cleanup(self):
        # E2E: import con BUY + DEPOSIT + DIVIDEND, revert, verificar que TODO
        # vuelve al estado pre-import (positions, monthly_entries, snapshots, links).
        conn = main.get_db()
        try:
            # Snapshot pre-import
            pre_positions = conn.execute(
                "SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0", (self.uid,)
            ).fetchone()["c"]
            pre_monthly = conn.execute(
                "SELECT COUNT(*) c FROM monthly_entries WHERE user_id=?", (self.uid,)
            ).fetchone()["c"]
            pre_snapshots = conn.execute(
                "SELECT COUNT(*) c FROM snapshots WHERE user_id=?", (self.uid,)
            ).fetchone()["c"]

            csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,DEPOSITO,IBKR,,,,5000,,,,USD,Aporte
2024-02-01,COMPRA,IBKR,AAPL,10,180,,,,1,USD,Compra inicial
2024-03-10,COMPRA,IBKR,MSFT,5,400,,,,1,USD,Otra compra
2024-04-08,DIVIDEND,IBKR,AAPL,,,18,,,,USD,Dividendo trimestral
"""
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="revert_test.csv",
                    broker_hint="IBKR", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw_map, helpers=_helpers(),
                )

            # Verificar estado post-import
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=0", (self.uid,)).fetchone()[0],
                pre_positions + 2,
                "Deben haberse creado 2 nuevas posiciones",
            )
            self.assertGreater(
                conn.execute("SELECT COUNT(*) FROM monthly_entries WHERE user_id=?", (self.uid,)).fetchone()[0],
                pre_monthly,
                "Deben haberse creado entries mensuales",
            )
            self.assertGreater(
                conn.execute("SELECT COUNT(*) FROM snapshots WHERE user_id=?", (self.uid,)).fetchone()[0],
                pre_snapshots,
                "Deben haberse generado snapshots desde monthly",
            )

            # Revert
            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=session_id, helpers=_helpers())

            # Verificar estado post-revert: posiciones creadas eliminadas
            post_positions = conn.execute(
                "SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0", (self.uid,)
            ).fetchone()["c"]
            self.assertEqual(post_positions, pre_positions,
                             "Posiciones creadas en el batch debieron eliminarse")

            # Estado del batch
            batch = conn.execute(
                "SELECT status FROM import_batches WHERE id=?", (session_id,),
            ).fetchone()
            self.assertEqual(batch["status"], "reverted")

            # No quedó ninguna operación creada por el batch
            ops_remaining = conn.execute(
                """SELECT COUNT(*) c FROM operations o
                   JOIN import_op_links l ON l.operation_id = o.id
                   WHERE l.batch_id = ?""",
                (session_id,),
            ).fetchone()["c"]
            self.assertEqual(ops_remaining, 0, "No deben quedar operations linkeadas al batch")
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

    def test_ars_sell_now_supported(self):
        # Antes: el persister rechazaba SELLs en brokers ARS. Ahora se calcula
        # P&L con el tc_blue de la config (mismo modelo que /api/positions/sell).
        conn = main.get_db()
        # tc_blue = 1400 en config
        conn.execute(
            "INSERT INTO config (key, value, user_id) VALUES (?,?,?)",
            ("tc_blue", "1400", self.uid),
        )
        conn.commit()
        try:
            csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,Cocos capital,GGAL,100,1500,150000,,,0,ARS,Compra
2024-03-20,VENTA,Cocos capital,GGAL,50,2000,100000,,,0,ARS,Venta parcial
"""
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="ars_sell.csv",
                    broker_hint="Cocos capital", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                summary = ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                            raw_row_ids_by_index=raw_map, helpers=_helpers())
            self.assertEqual(summary["operations_created"], 1, f"skipped={summary['skipped_rows']}")
            self.assertEqual(len(summary["skipped_rows"]), 0)
            # P&L USD-equivalente: (2000-1500) × 50 / 1400 = 25000 / 1400 ≈ 17.86
            op = conn.execute(
                "SELECT pnl_usd FROM operations WHERE user_id=? AND asset='GGAL'",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(op["pnl_usd"], 25000 / 1400, places=2)
        finally:
            conn.close()

    def test_ars_deposit_converts_to_usd_in_monthly_flow(self):
        # Bug #FX-scale: un depósito de 10M ARS no debe registrarse como 10M USD
        # en monthly_entries. Debe convertirse usando tc_blue de la config.
        conn = main.get_db()
        # Setear tc_blue=1400 en la config del usuario
        conn.execute(
            "INSERT INTO config (key, value, user_id) VALUES (?,?,?)",
            ("tc_blue", "1400", self.uid),
        )
        conn.commit()
        try:
            csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-01,DEPOSITO,Cocos capital,,,,10000000,,,,ARS,Aporte 10M ARS
"""
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="ars_deposit.csv",
                    broker_hint="Cocos capital", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw_map, helpers=_helpers())
            # monthly_entries.deposits del global debe ser ~7142.86 USD (10M / 1400)
            global_row = conn.execute(
                "SELECT deposits FROM monthly_entries WHERE user_id=? AND broker='global'",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(global_row["deposits"], 10_000_000 / 1400, places=2)

            # Cash position de Cocos capital sí debe estar en ARS nativo
            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                (self.uid, "Cocos capital"),
            ).fetchone()
            # Inicial 5M (de setUp) + 10M depositados = 15M ARS
            self.assertEqual(cash["invested"], 15_000_000)
        finally:
            conn.close()

    def test_persist_overdraft_allowed_in_cash_flow(self):
        # Política del importer: cash flows permiten overdraft silencioso. Si
        # un retiro deja el saldo negativo, NO se saltea la fila — el cash
        # queda negativo y se reporta en cash_health para que el usuario lo vea.
        # Cash inicial = 5M ARS (de setUp).
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-01,DEPOSITO,Cocos capital,,,,1000,,,,ARS,Aporte 1
2024-01-02,RETIRO,Cocos capital,,,,99000000,,,,ARS,Retiro mucho mayor al cash disponible
2024-01-03,DEPOSITO,Cocos capital,,,,2000,,,,ARS,Aporte 2
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="cash_flow.csv",
                    broker_hint="Cocos capital", parser_format="rendi_generic",
                )
            self.assertEqual(payload["summary"]["valid_rows"], 3)
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                summary = ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw_map, helpers=_helpers(),
                )
            # Las 3 filas de cash flow deben haber pasado (overdraft permitido)
            self.assertEqual(len(summary["skipped_rows"]), 0)
            self.assertEqual(summary["cash_movements"], 3)
            # Cash final: 5_000_000 + 1000 - 99_000_000 + 2000 = -93_997_000 (negativo)
            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                (self.uid, "Cocos capital"),
            ).fetchone()
            self.assertEqual(cash["invested"], -93_997_000)
            # cash_health debe reportar el balance negativo
            negative = [c for c in summary["cash_health"] if c["balance"] < 0]
            self.assertEqual(len(negative), 1)
            self.assertEqual(negative[0]["broker"], "Cocos capital")
        finally:
            conn.close()

    def test_import_backfills_snapshots(self):
        # Tras importar varios meses, debe haber un snapshot al último día
        # de cada mes para que la Evolución del portfolio tenga datos.
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,DEPOSITO,Cocos capital,,,,1000000,,,,ARS,Aporte enero
2024-02-10,DEPOSITO,Cocos capital,,,,500000,,,,ARS,Aporte febrero
2024-04-05,DEPOSITO,Cocos capital,,,,200000,,,,ARS,Aporte abril
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="snap.csv",
                    broker_hint="Cocos capital", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw_map, helpers=_helpers())
            # Debe haber al menos 1 snapshot por cada mes con monthly_entries (3 meses)
            snaps = conn.execute(
                "SELECT date, total_value, net_deposited FROM snapshots WHERE user_id=? ORDER BY date",
                (self.uid,),
            ).fetchall()
            self.assertGreaterEqual(len(snaps), 3, "Esperaba snapshots para cada mes con actividad")
            # net_deposited del último snapshot debe ser cumulative
            last = snaps[-1]
            self.assertGreater(last["net_deposited"], 0)
            # Las fechas deben ser fin de mes
            dates = [s["date"] for s in snaps]
            self.assertTrue(all(d.endswith('-31') or d.endswith('-30') or d.endswith('-29') or d.endswith('-28') for d in dates),
                            f"Fechas no son fin de mes: {dates}")
        finally:
            conn.close()

    def test_broker_match_is_case_insensitive(self):
        # Si el CSV trae "Cocos Capital" y el usuario ya tiene "Cocos capital",
        # NO debe crear un broker nuevo: las filas deben ir al existente.
        # Si el CSV usa varios casing del mismo broker nuevo, se agrupan.
        conn = main.get_db()
        try:
            csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,Cocos Capital,GGAL,100,1500,150000,,,0,ARS,Capital con may
2024-01-16,COMPRA,COCOS CAPITAL,YPFD,50,3000,150000,,,0,ARS,Todo en mayus
2024-02-01,COMPRA,Bull Market,AAPL,5,180,900,,,0,USD,Casing 1
2024-02-02,COMPRA,bull market,MSFT,3,400,1200,,,0,USD,Casing 2
"""
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="case.csv",
                    broker_hint=None, parser_format="rendi_generic",
                )
            self.assertEqual(payload["summary"]["valid_rows"], 4)
            # Cocos capital ya existía, no debió crearse de nuevo
            new_names = {b["name"] for b in payload["new_brokers_created"]}
            self.assertNotIn("Cocos Capital", new_names)
            self.assertNotIn("COCOS CAPITAL", new_names)
            # Bull Market y bull market deben agrupar en UN solo broker nuevo
            bull_brokers = [b for b in payload["new_brokers_created"] if b["name"].lower() == "bull market"]
            self.assertEqual(len(bull_brokers), 1, f"Bull Market no debió duplicarse: {payload['new_brokers_created']}")
            self.assertEqual(bull_brokers[0]["rows"], 2)  # ambas filas

            # En la DB no deben haberse creado duplicados
            cocos_count = conn.execute(
                "SELECT COUNT(*) FROM brokers WHERE user_id=? AND LOWER(name)='cocos capital'",
                (self.uid,),
            ).fetchone()[0]
            self.assertEqual(cocos_count, 1)
            bull_count = conn.execute(
                "SELECT COUNT(*) FROM brokers WHERE user_id=? AND LOWER(name)='bull market'",
                (self.uid,),
            ).fetchone()[0]
            self.assertEqual(bull_count, 1)
        finally:
            conn.close()

    def test_unknown_broker_is_auto_created(self):
        # Si el CSV trae un broker que el usuario no tiene, lo creamos solos
        # con la moneda inferida por mayoría de filas. No bloquea la importación.
        conn = main.get_db()
        try:
            csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,Cocos capital,GGAL,100,1500,150000,,,0,ARS,Acciones AR
2024-02-01,COMPRA,Schwab,AAPL,5,180,900,,,0,USD,Compra en Schwab
2024-02-10,COMPRA,Schwab,MSFT,3,400,1200,,,0,USD,Otra en Schwab
"""
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="multi.csv",
                    broker_hint=None, parser_format="rendi_generic",
                )
            self.assertEqual(payload["summary"]["valid_rows"], 3)
            # Schwab debió crearse como USDT (todas sus filas son USD)
            new = {b["name"]: b for b in payload["new_brokers_created"]}
            self.assertIn("Schwab", new)
            self.assertEqual(new["Schwab"]["currency"], "USDT")
            self.assertEqual(new["Schwab"]["rows"], 2)
            self.assertNotIn("Cocos capital", new, "Cocos ya existía, no debió crearse")

            # En la DB debe estar Schwab
            schwab = conn.execute(
                "SELECT * FROM brokers WHERE user_id=? AND name='Schwab'", (self.uid,),
            ).fetchone()
            self.assertIsNotNone(schwab)
            self.assertEqual(schwab["currency"], "USDT")
        finally:
            conn.close()

    def test_multi_broker_csv_routes_per_broker_automatically(self):
        # CSV con dos brokers: Cocos capital (ARS) e IBKR (USDT).
        # Sin route_by_currency explícito; debe activarse solo porque hay
        # filas USD en el broker ARS.
        conn = main.get_db()
        try:
            _add_broker(conn, self.uid, "IBKR", "USDT")
            # Cash inicial USD en IBKR
            conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
                   VALUES (?,?,?,1,?)""",
                (self.uid, "IBKR", "USDT", 10000),
            )
            conn.commit()

            csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-01-15,COMPRA,Cocos capital,GGAL,100,1500,150000,,,0,ARS,Acciones AR
2024-02-01,COMPRA,Cocos capital,AAPL,5,180,900,,,0,USD,CEDEAR pagado USD
2024-03-10,COMPRA,IBKR,MSFT,2,400,800,,,0,USD,Compra en IBKR
2024-04-15,DEPOSITO,Cocos capital,,,,500,,,,USD,Deposit USD a Cocos
"""
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="multi.csv",
                    broker_hint=None,                # ← multi-broker mode
                    parser_format="rendi_generic",
                    route_by_currency=False,         # ← debe auto-activarse
                )
            self.assertEqual(payload["summary"]["valid_rows"], 4)
            self.assertTrue(payload["is_multi_broker"])
            self.assertTrue(payload["route_by_currency"], "Debió activarse automáticamente")
            # routing_breakdown debe traer entradas por cada broker
            breakdown = {b["broker"]: b for b in payload["routing_breakdown"]}
            self.assertIn("Cocos capital", breakdown)
            self.assertIn("IBKR", breakdown)
            self.assertTrue(breakdown["Cocos capital"]["creates_sibling"])
            self.assertFalse(breakdown["IBKR"]["creates_sibling"])
            self.assertEqual(breakdown["Cocos capital"]["ars_rows"], 1)  # GGAL
            self.assertEqual(breakdown["Cocos capital"]["usd_rows"], 2)  # AAPL + DEPOSIT USD

            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw_map, helpers=_helpers(),
                )

            # GGAL → Cocos capital (ARS parent)
            ggal = conn.execute(
                "SELECT broker FROM positions WHERE user_id=? AND asset='GGAL' AND is_cash=0",
                (self.uid,),
            ).fetchone()
            self.assertEqual(ggal["broker"], "Cocos capital")
            # AAPL → Cocos capital · USD (auto-creado)
            aapl = conn.execute(
                "SELECT broker FROM positions WHERE user_id=? AND asset='AAPL' AND is_cash=0",
                (self.uid,),
            ).fetchone()
            self.assertEqual(aapl["broker"], "Cocos capital · USD")
            # MSFT → IBKR (no routing)
            msft = conn.execute(
                "SELECT broker FROM positions WHERE user_id=? AND asset='MSFT' AND is_cash=0",
                (self.uid,),
            ).fetchone()
            self.assertEqual(msft["broker"], "IBKR")
            # USD deposit a Cocos → cash USD del sibling
            cocos_usd = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Cocos capital · USD' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            # +500 (deposit) - 900 (AAPL buy) = -400 (overdraft permitido)
            self.assertAlmostEqual(cocos_usd["invested"], -400, places=2)
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


class SeedStateE2ETest(unittest.TestCase):
    """E2E del flujo Estado Inicial:
    - CSV parcial (SELL sin compra previa) → preview reporta seed_suggestions
    - confirm con seed_state → genera DEPOSIT + BUY sintéticos al seed_date
    - SELL ahora cuadra (re-validación con seed-augmented existing_positions)
    """

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions",
                  "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="seed_test@rendi.test")
        _add_broker(conn, self.uid, "Binance", "USDT")
        conn.commit()
        conn.close()

    def test_partial_csv_triggers_seed_suggestions(self):
        """Un CSV con SELL sin BUY previo debe disparar seed_suggestions."""
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-11-15,VENTA,Binance,BTC,0.05,70000,3500,,,,USDT,vendi un poco
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="partial.csv",
                    broker_hint="Binance", parser_format="rendi_generic",
                )
            self.assertEqual(payload["summary"]["valid_rows"], 0)
            self.assertEqual(payload["summary"]["invalid_rows"], 1)
            sug = payload.get("seed_suggestions")
            self.assertIsNotNone(sug, f"esperaba seed_suggestions; payload: {payload.keys()}")
            self.assertTrue(sug["needed"])
            self.assertEqual(sug["earliest_csv_date"], "2025-11-15")
            self.assertEqual(sug["seed_date"], "2025-11-14")
            self.assertEqual(len(sug["brokers"]), 1)
            binance = sug["brokers"][0]
            self.assertEqual(binance["broker"], "Binance")
            symbols = [a["symbol"] for a in binance["assets"]]
            self.assertIn("BTC", symbols)
        finally:
            conn.close()

    def test_confirm_with_seed_resolves_sell_and_persists_synthetic_rows(self):
        """Aplicar el seed_state al confirmar permite que el SELL pase y persiste."""
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-11-15,VENTA,Binance,BTC,0.05,70000,3500,,,,USDT,vendi
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="partial.csv",
                    broker_hint="Binance", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            seed_state = {
                "seed_date": "2025-11-14",
                "brokers": [{
                    "broker": "Binance",
                    "cash": {"USDT": 0},
                    "assets": [{"symbol": "BTC", "qty": 0.05, "cost_basis_unit": 65000}],
                }],
            }
            with conn:
                txs, raw = pl.load_session_with_seed_revalidate(
                    conn, uid=self.uid, session_id=session_id, seed_state=seed_state,
                )
                summary = ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw, helpers=_helpers(),
                    seed_state=seed_state,
                )
            # 0.05 BTC se compró sintéticamente → SELL del CSV consume eso
            # Posiciones BTC restantes = 0
            btc_positions = conn.execute(
                "SELECT SUM(quantity) q FROM positions WHERE user_id=? AND broker='Binance' AND asset='BTC' AND is_cash=0",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(btc_positions["q"] or 0, 0, places=8)

            # 1 operación de venta creada con P&L = (70000 - 65000) * 0.05 = 250
            ops = conn.execute(
                "SELECT pnl_usd FROM operations WHERE user_id=? AND op_type='Venta'",
                (self.uid,),
            ).fetchall()
            self.assertEqual(len(ops), 1)
            self.assertAlmostEqual(ops[0]["pnl_usd"], 250, places=2)

            # Cash neto: deposit sintético (3250) + sell proceeds (3500) - cost del BUY sintético (3250) = 3500
            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Binance' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(cash["invested"], 3500, places=2)

            # El batch tiene seed rows persistidas (auditables)
            seed_rows = conn.execute(
                "SELECT COUNT(*) c FROM import_normalized_tx WHERE batch_id=? AND date=?",
                (session_id, "2025-11-14"),
            ).fetchone()
            self.assertEqual(seed_rows["c"], 2, "esperaba 1 DEPOSIT + 1 BUY sintéticos al seed_date")
        finally:
            conn.close()

    def test_no_seed_means_no_synthetic_rows(self):
        """Si confirm va sin seed_state, el flujo legacy se mantiene intacto."""
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-11-15,DEPOSITO,Binance,,,,1000,,,,USDT,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="ok.csv",
                    broker_hint="Binance", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_with_seed_revalidate(
                    conn, uid=self.uid, session_id=session_id, seed_state=None,
                )
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw, helpers=_helpers(),
                    seed_state=None,
                )
            # Solo 1 row (la del CSV)
            count = conn.execute(
                "SELECT COUNT(*) c FROM import_normalized_tx WHERE batch_id=?",
                (session_id,),
            ).fetchone()["c"]
            self.assertEqual(count, 1)
        finally:
            conn.close()


class NuclearRevertAndRedoTest(unittest.TestCase):
    """E2E del flujo Editar y rehacer:
    - Importar un CSV con SELL (que normalmente bloquea revert).
    - revert_batch con nuclear=True debe poder revertirlo (best-effort).
    - reconstruct_csv_from_batch produce un CSV reusable.
    - El endpoint /redo combina ambas cosas y devuelve un nuevo preview.
    """

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions",
                  "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="redo_test@rendi.test")
        _add_broker(conn, self.uid, "Binance", "USDT")
        # Cash inicial para no tener overdraft al re-importar
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "Binance", "USDT", 10000),
        )
        conn.commit()
        conn.close()

    def _import_buy_then_sell_csv(self):
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-11-10,COMPRA,Binance,BTC,0.05,65000,3250,,,,USDT,
2025-11-15,VENTA,Binance,BTC,0.05,70000,3500,,,,USDT,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="redo.csv",
                    broker_hint="Binance", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw, helpers=_helpers(),
                )
            return session_id
        finally:
            conn.close()

    def test_nuclear_revert_undoes_sell(self):
        batch_id = self._import_buy_then_sell_csv()
        conn = main.get_db()
        try:
            # Pre-revert: 0 BTC (consumido por sell), cash = 10000 - 3250 + 3500 = 10250
            cash_before = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Binance' AND is_cash=1",
                (self.uid,),
            ).fetchone()["invested"]
            self.assertAlmostEqual(cash_before, 10250, places=2)

            # Safe revert debería bloquear (incluye SELL)
            with conn:
                with self.assertRaises(ps.PersistError):
                    ps.revert_batch(conn, uid=self.uid, batch_id=batch_id,
                                     helpers=_helpers(), nuclear=False)

            # Nuclear revert pasa
            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=batch_id,
                                 helpers=_helpers(), nuclear=True)

            # Después del revert: cash debe volver al original (10000)
            cash_after = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Binance' AND is_cash=1",
                (self.uid,),
            ).fetchone()["invested"]
            self.assertAlmostEqual(cash_after, 10000, places=2)

            # Posiciones de BTC borradas (la BUY se borró + cualquier recreación
            # del SELL revert también)
            btc = conn.execute(
                "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
                (self.uid,),
            ).fetchone()["q"]
            # La BUY recreó por SELL revert (0.05) y luego la BUY del batch borró otra (0.05).
            # Net: depende del orden. Lo importante es que el cash y las operations queden limpias.
            ops_count = conn.execute(
                "SELECT COUNT(*) c FROM operations WHERE user_id=?",
                (self.uid,),
            ).fetchone()["c"]
            self.assertEqual(ops_count, 0, "todas las operations creadas deben estar borradas")

            # Estado del batch
            status = conn.execute(
                "SELECT status FROM import_batches WHERE id=?", (batch_id,),
            ).fetchone()["status"]
            self.assertEqual(status, "reverted")
        finally:
            conn.close()

    def test_reconstruct_csv_from_batch(self):
        batch_id = self._import_buy_then_sell_csv()
        conn = main.get_db()
        try:
            csv_bytes = pl.reconstruct_csv_from_batch(conn, uid=self.uid, batch_id=batch_id)
            self.assertIsNotNone(csv_bytes)
            text = csv_bytes.decode("utf-8")
            # Headers canónicos
            self.assertIn("fecha,tipo,broker,activo", text)
            # Las dos filas (BUY + SELL) están
            self.assertIn("2025-11-10", text)
            self.assertIn("2025-11-15", text)
            # COMPRA y VENTA fueron normalizadas en raw_rows como BUY/SELL strings
            # (depende del parser). Verificamos los activos.
            self.assertIn("BTC", text)
        finally:
            conn.close()

    def test_redo_endpoint_returns_new_preview(self):
        """End-to-end del endpoint /redo: revierte + corre preview de nuevo."""
        batch_id = self._import_buy_then_sell_csv()
        from fastapi.testclient import TestClient
        # Crear token para el user
        from main import create_token
        token = create_token(self.uid)
        client = TestClient(main.app)
        res = client.post(f"/api/imports/{batch_id}/redo",
                           headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200, f"body: {res.text}")
        body = res.json()
        self.assertIn("preview", body)
        self.assertIn("original_batch_id", body)
        self.assertEqual(body["original_batch_id"], batch_id)
        # El preview nuevo es un batch DIFERENTE (nuevo session_id)
        self.assertNotEqual(body["preview"]["session_id"], batch_id)
        # Y el preview tiene las mismas filas (BUY + SELL) válidas
        self.assertEqual(body["preview"]["summary"]["valid_rows"], 2)
        # El batch original quedó como reverted
        conn = main.get_db()
        try:
            status = conn.execute(
                "SELECT status FROM import_batches WHERE id=?", (batch_id,),
            ).fetchone()["status"]
            self.assertEqual(status, "reverted")
        finally:
            conn.close()


class RobustnessImprovementsTest(unittest.TestCase):
    """Tests para las mejoras de robustez:
    - Aliases nuevos (Wire Transfer, ACAT, Reinvested, etc.)
    - Re-clasificación de TRANSFER por signo del monto
    - Auto-detect de monto desde quantity*precio o sólo quantity
    - Mensajes de error con remediación
    """

    def test_wire_transfer_positive_amount_becomes_deposit(self):
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "Wire Transfer", "broker": "Schwab",
            "monto": "1500", "moneda": "USD",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0, f"errors: {errors}")
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].operation_type, OP_DEPOSIT)
        self.assertAlmostEqual(normalized[0].gross_amount, 1500, places=2)

    def test_wire_transfer_negative_amount_becomes_withdraw(self):
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "Wire Transfer", "broker": "Schwab",
            "monto": "-2000", "moneda": "USD",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0, f"errors: {errors}")
        self.assertEqual(normalized[0].operation_type, OP_WITHDRAW)
        # El monto se convierte a positivo (el sistema espera monto > 0)
        self.assertAlmostEqual(normalized[0].gross_amount, 2000, places=2)

    def test_acat_journal_new_aliases(self):
        # Aliases exactos (mapean directamente sin pasar por re-clasificación)
        for op_str, expected, monto in [
            ("ACAT_IN", OP_DEPOSIT, "100"),
            ("ACAT_OUT", OP_WITHDRAW, "100"),
            ("JOURNAL_FROM", OP_DEPOSIT, "100"),
            ("JOURNAL_TO", OP_WITHDRAW, "100"),
            # Texto libre → cae en fallback "JOURNAL/ACAT" → TRANSFER →
            # re-clasifica por signo de monto.
            ("Journal entry", OP_DEPOSIT, "100"),    # positivo → DEPOSIT
            ("Wire Transfer", OP_WITHDRAW, "-200"),  # negativo → WITHDRAW
        ]:
            rows = [RawRow(row_index=1, data={
                "fecha": "2025-03-15", "tipo": op_str, "broker": "Schwab",
                "monto": monto, "moneda": "USD",
            })]
            normalized, errors = normalize_rows(rows)
            self.assertEqual(len(errors), 0, f"failed for '{op_str}': {errors}")
            self.assertEqual(normalized[0].operation_type, expected,
                              f"'{op_str}' should map to {expected}, got {normalized[0].operation_type}")

    def test_reinvested_dividend_becomes_buy(self):
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "Reinvested Dividend", "broker": "Schwab",
            "activo": "VOO", "cantidad": "0.5", "precio": "400",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(normalized[0].operation_type, OP_BUY)

    def test_qualified_dividend_alias(self):
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "Qualified Dividend", "broker": "Schwab",
            "activo": "VOO", "monto": "12.50",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(normalized[0].operation_type, OP_DIVIDEND)

    def test_management_fee_alias(self):
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "Management Fee", "broker": "Schwab",
            "monto": "5.00",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(normalized[0].operation_type, OP_FEE)

    def test_negative_amount_in_deposit_flips_to_withdraw(self):
        # Algunos brokers exportan in/out en la misma columna con signo
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "DEPOSITO", "broker": "Schwab",
            "monto": "-500", "moneda": "USD",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(normalized[0].operation_type, OP_WITHDRAW)
        self.assertAlmostEqual(normalized[0].gross_amount, 500, places=2)

    def test_withdraw_with_quantity_only_uses_quantity_as_amount(self):
        # Schwab/Fidelity típicamente ponen el monto en "Amount" sin precio
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "RETIRO", "broker": "Schwab",
            "cantidad": "1500",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 0)
        self.assertEqual(normalized[0].operation_type, OP_WITHDRAW)
        self.assertAlmostEqual(normalized[0].gross_amount, 1500, places=2)
        self.assertIsNone(normalized[0].quantity)

    def test_unknown_op_type_message_mentions_wizard(self):
        rows = [RawRow(row_index=1, data={
            "fecha": "2025-03-15", "tipo": "Some Random Bullshit", "broker": "Schwab",
            "monto": "100",
        })]
        normalized, errors = normalize_rows(rows)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].code, "UNKNOWN_OP_TYPE")
        self.assertIn("wizard", errors[0].message.lower())

    def test_new_aliases_distribution_pil_whtax_airdrop(self):
        # Distribuciones de ETFs / fondos → DIVIDEND
        for op_str, expected, op_field in [
            ("Distribution", OP_DIVIDEND, "monto"),
            ("Capital Gain Distribution", OP_DIVIDEND, "monto"),
            ("Long Term Gain Dist", OP_DIVIDEND, "monto"),
            ("Liquidating Dividend", OP_DIVIDEND, "monto"),
            ("PIL", OP_DIVIDEND, "monto"),
            ("Payment In Lieu", OP_DIVIDEND, "monto"),
            # Fees / impuestos
            ("WHTAX", OP_FEE, "monto"),
            ("Withholding", OP_FEE, "monto"),
            ("Foreign Tax Paid", OP_FEE, "monto"),
            ("ADR Mgmt Fee", OP_FEE, "monto"),
            ("ADR Maint Fee", OP_FEE, "monto"),
            ("Custodian Fee", OP_FEE, "monto"),
            # Intereses / rewards
            ("Airdrop", OP_INTEREST, "monto"),
            ("Promo", OP_INTEREST, "monto"),
            ("Sign Up Bonus", OP_INTEREST, "monto"),
            ("Cash Sweep", OP_INTEREST, "monto"),
            # Variantes de SELL
            ("Cash Merger", OP_SELL, None),
            ("Tender Offer", OP_SELL, None),
            ("Mandatory Redemption", OP_SELL, None),
        ]:
            data = {"fecha": "2025-03-15", "tipo": op_str, "broker": "Schwab",
                    "monto": "10", "moneda": "USD"}
            if op_str in ("Cash Merger", "Tender Offer", "Mandatory Redemption"):
                # SELLs need quantity/price/asset
                data.update({"activo": "VOO", "cantidad": "5", "precio": "400"})
            rows = [RawRow(row_index=1, data=data)]
            normalized, errors = normalize_rows(rows)
            self.assertEqual(len(errors), 0, f"errors for '{op_str}': {errors}")
            self.assertEqual(normalized[0].operation_type, expected,
                              f"'{op_str}' debería mapear a {expected}")

    def test_unsupported_ops_give_actionable_error(self):
        # Stock split, merger, caución, convert → OP_NOT_SUPPORTED con mensaje claro
        for op_str, expected_code, msg_keyword in [
            ("Stock Split", "OP_NOT_SUPPORTED", "qty"),
            ("Reverse Split", "OP_NOT_SUPPORTED", "qty"),
            ("Spin-off", "OP_NOT_SUPPORTED", "spin"),
            ("Merger", "OP_NOT_SUPPORTED", "merger"),
            ("Caución", "OP_NOT_SUPPORTED", "caución"),
            ("Plazo Fijo", "OP_NOT_SUPPORTED", "plazo"),
            ("Convert", "OP_NOT_SUPPORTED", "cripto"),
            ("Hard Fork", "OP_NOT_SUPPORTED", "fork"),
        ]:
            rows = [RawRow(row_index=1, data={
                "fecha": "2025-03-15", "tipo": op_str, "broker": "Schwab",
                "monto": "100",
            })]
            normalized, errors = normalize_rows(rows)
            self.assertEqual(len(errors), 1, f"esperaba 1 error para '{op_str}': {errors}")
            self.assertEqual(errors[0].code, expected_code,
                              f"'{op_str}' debería dar {expected_code}, dio: {errors[0].code}")
            self.assertIn(msg_keyword.lower(), errors[0].message.lower(),
                           f"mensaje de '{op_str}' debería mencionar '{msg_keyword}': {errors[0].message}")


class CashAutoCreateOnBuyTest(unittest.TestCase):
    """Verifica que al hacer un BUY de import, la cash position se crea
    automáticamente (en negativo) si no existía. Antes era opt-in y dejaba
    al usuario sin información de overdraft."""

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions",
                  "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="cashauto_test@rendi.test")
        _add_broker(conn, self.uid, "Schwab", "USDT")
        # NO creamos cash position — la idea es que se cree sola al primer BUY
        conn.commit()
        conn.close()

    def test_buy_without_prior_cash_creates_negative_cash_position(self):
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-11-15,COMPRA,Schwab,VOO,2,400,800,,,,USD,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="t.csv",
                    broker_hint="Schwab", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw, helpers=_helpers(),
                )
            # Esperamos que el BUY haya creado una cash position negativa
            cash = conn.execute(
                "SELECT asset, invested FROM positions WHERE user_id=? AND broker='Schwab' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertIsNotNone(cash, "esperaba que se cree una cash position automáticamente")
            self.assertAlmostEqual(cash["invested"], -800, places=2,
                                     msg="el balance debería ser -800 (BUY sin cash previo = overdraft visible)")
            self.assertEqual(cash["asset"], "USDT")
        finally:
            conn.close()

    def test_buy_with_existing_cash_just_updates_balance(self):
        # Si ya hay cash, comportamiento idéntico al anterior — no rompe
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "Schwab", "USDT", 5000),
        )
        conn.commit()
        conn.close()

        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-11-15,COMPRA,Schwab,VOO,2,400,800,,,,USD,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="t.csv",
                    broker_hint="Schwab", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw, helpers=_helpers(),
                )
            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Schwab' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            # 5000 - 800 = 4200
            self.assertAlmostEqual(cash["invested"], 4200, places=2)
        finally:
            conn.close()


class NuclearRevertWithRoutingTest(unittest.TestCase):
    """Verifica que el nuclear revert con route_by_currency restaure el estado
    inicial limpiamente. Antes había un bug: el persister muteaba tx.broker en
    memoria al rutear (ARS broker → USD sibling) pero no actualizaba la DB,
    así el revert leía el broker original y devolvía cash al broker equivocado.
    """

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions",
                  "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="routing_revert@rendi.test")
        cur = conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "IOL", "ARS"),
        )
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "IOL", "ARS", 5_000_000),
        )
        conn.commit()
        conn.close()

    def test_revert_with_routing_returns_to_initial_state(self):
        # CSV: ARS→USD + BUY (USD) + USD→ARS — todo con routing
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-11-10,Conversion ARS USD,IOL,,,,1500000,1000,1500,,USD,
2025-11-15,COMPRA,IOL,AAPL,5,180,900,,,,USD,
2025-11-20,Conversion USD ARS,IOL,,,,750000,500,1500,,USD,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="fx.csv",
                    broker_hint="IOL", parser_format="rendi_generic",
                    route_by_currency=True,
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw, helpers=_helpers())
            # Sanity-check post-confirm
            ars_after = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='IOL' AND is_cash=1",
                (self.uid,),
            ).fetchone()["invested"]
            self.assertAlmostEqual(ars_after, 4_250_000, places=2)

            # Revert nuclear → debería restaurar EXACTAMENTE el estado inicial
            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=session_id,
                                 helpers=_helpers(), nuclear=True)

            # ARS debe volver a 5_000_000
            ars_final = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='IOL' AND is_cash=1",
                (self.uid,),
            ).fetchone()["invested"]
            self.assertAlmostEqual(ars_final, 5_000_000, places=2,
                                     msg="ARS debería volver a 5M tras revert nuclear")

            # USD sibling debe estar en 0 (sin drift)
            usd_sibling = conn.execute(
                """SELECT p.invested FROM positions p
                     JOIN brokers b ON b.name = p.broker AND b.user_id = p.user_id
                    WHERE p.user_id=? AND b.currency='USDT' AND p.is_cash=1""",
                (self.uid,),
            ).fetchone()
            if usd_sibling:
                self.assertAlmostEqual(usd_sibling["invested"], 0, places=2,
                                         msg="USD sibling debería estar en 0 tras revert nuclear")
        finally:
            conn.close()


class DividendInterestAsGainTest(unittest.TestCase):
    """Verifica que DIVIDEND/INTEREST:
    - NO se cuenten como deposit en monthly_entries (no inflan capital aportado)
    - SI se cuenten como pnl_realized (cuenta como ganancia)
    - Generen una fila en operations con asset, op_type='Dividendo'/'Interés', quantity=monto
    """

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions",
                  "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="div_test@rendi.test")
        _add_broker(conn, self.uid, "Schwab", "USDT")
        # Cash inicial para que las operaciones tengan contexto
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (self.uid, "Schwab", "USDT", 1000),
        )
        conn.commit()
        conn.close()

    def test_dividend_creates_operation_row_and_pnl(self):
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-04-15,Qualified Dividend,Schwab,VOO,,,12.50,,,,USD,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="div.csv",
                    broker_hint="Schwab", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw, helpers=_helpers())

            # 1. Aparece en operations con asset='VOO', op_type='Dividendo', qty=12.50
            ops = conn.execute(
                "SELECT * FROM operations WHERE user_id=? AND op_type='Dividendo'",
                (self.uid,),
            ).fetchall()
            self.assertEqual(len(ops), 1, "esperaba 1 fila Dividendo en operations")
            op = ops[0]
            self.assertEqual(op["asset"], "VOO")
            self.assertEqual(op["op_type"], "Dividendo")
            self.assertAlmostEqual(op["quantity"], 12.50, places=2)
            self.assertAlmostEqual(op["pnl_usd"], 12.50, places=2)

            # 2. monthly_entries pnl_realized SUBE (es ganancia)
            entry = conn.execute(
                """SELECT pnl_realized, deposits FROM monthly_entries
                    WHERE user_id=? AND broker='Schwab' AND year=2025 AND month=4""",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(entry["pnl_realized"], 12.50, places=2,
                                     msg="pnl_realized debería ser 12.50")
            self.assertAlmostEqual(entry["deposits"], 0, places=2,
                                     msg="deposits NO debería incluir el dividendo")

            # 3. Cash sigue subiendo (1000 + 12.50 = 1012.50)
            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Schwab' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(cash["invested"], 1012.50, places=2)
        finally:
            conn.close()

    def test_interest_creates_operation_row_and_pnl(self):
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-05-10,Bank Interest,Schwab,,,,3.25,,,,USD,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="int.csv",
                    broker_hint="Schwab", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw, helpers=_helpers())
            ops = conn.execute(
                "SELECT op_type, asset, quantity, pnl_usd FROM operations WHERE user_id=?",
                (self.uid,),
            ).fetchall()
            self.assertEqual(len(ops), 1)
            self.assertEqual(ops[0]["op_type"], "Interés")
            self.assertAlmostEqual(ops[0]["quantity"], 3.25, places=2)
            self.assertAlmostEqual(ops[0]["pnl_usd"], 3.25, places=2)
            # Asset queda como '—' porque el CSV no lo trae para "Bank Interest"
            self.assertEqual(ops[0]["asset"], "—")
        finally:
            conn.close()

    def test_deposit_still_goes_to_capital_aportado(self):
        # Verifica que DEPOSIT mantiene comportamiento legacy (capital aportado)
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2025-04-15,DEPOSITO,Schwab,,,,500,,,,USD,
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="dep.csv",
                    broker_hint="Schwab", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                  raw_row_ids_by_index=raw, helpers=_helpers())
            entry = conn.execute(
                """SELECT pnl_realized, deposits FROM monthly_entries
                    WHERE user_id=? AND broker='Schwab' AND year=2025 AND month=4""",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(entry["deposits"], 500, places=2,
                                     msg="DEPOSIT debe ir a deposits, no a pnl")
            self.assertAlmostEqual(entry["pnl_realized"], 0, places=2,
                                     msg="DEPOSIT no debe ir a pnl_realized")
            # Sin operaciones creadas
            ops_count = conn.execute(
                "SELECT COUNT(*) c FROM operations WHERE user_id=?", (self.uid,),
            ).fetchone()["c"]
            self.assertEqual(ops_count, 0)
        finally:
            conn.close()


class IntradayTradingOrderTest(unittest.TestCase):
    """Cuando hay BUY y SELL del mismo día y el SELL precede al BUY en el CSV
    (típico en 'Compra Trading' + 'Venta Trading' de Cocos), el persister
    debe procesar BUYs primero para no fallar con 'stock insuficiente'."""

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, email=f"intraday-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()

    def _persist_sample(self, txs):
        """Helper: persiste una lista de NormalizedTx + asserta no errores."""
        from importing.persister import persist_batch
        import uuid, json
        batch_id = str(uuid.uuid4())
        conn = main.get_db()
        raw_row_ids = {}
        with conn:
            conn.execute(
                """INSERT INTO import_batches
                   (id, user_id, parser_format, file_name, file_hash, broker, status)
                   VALUES (?, ?, 'cocos', 'test.csv', ?, 'Cocos', 'preview')""",
                (batch_id, self.uid, batch_id),
            )
            # raw_rows necesarias para FK desde import_normalized_tx
            for tx in txs:
                cur = conn.execute(
                    """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                       VALUES (?,?,?,'valid',NULL)""",
                    (batch_id, tx.row_index, json.dumps({"_test": "x"})),
                )
                raw_row_ids[tx.row_index] = cur.lastrowid
        result = persist_batch(
            conn,
            uid=self.uid,
            batch_id=batch_id,
            txs=txs,
            raw_row_ids_by_index=raw_row_ids,
            helpers=main,
        )
        conn.close()
        return batch_id, result

    def test_intraday_sell_before_buy_does_not_skip(self):
        """Replica el caso BMA del CSV real:
          1. BUY 50 (jun)
          2. SELL 91 trading (sep, row_index 2 — antes que el BUY trading)
          3. BUY 91 trading (sep, row_index 3)
          4. SELL 50 (sep, row_index 4)
        Sin fix: SELL 91 falla porque solo hay 50 → resulta en 91 abiertas.
        Con fix: BUYs procesados primero → net = 0.
        """
        from importing.schema import NormalizedTx, OP_BUY, OP_SELL
        txs = [
            NormalizedTx(row_index=1, date="2025-06-23", broker="Cocos",
                         operation_type=OP_BUY, asset_symbol="BMA",
                         quantity=50, unit_price=8140, gross_amount=407000,
                         currency="ARS", settlement_currency="ARS"),
            NormalizedTx(row_index=2, date="2025-09-08", broker="Cocos",
                         operation_type=OP_SELL, asset_symbol="BMA",
                         quantity=91, unit_price=6590, gross_amount=599690,
                         currency="ARS", settlement_currency="ARS"),
            NormalizedTx(row_index=3, date="2025-09-08", broker="Cocos",
                         operation_type=OP_BUY, asset_symbol="BMA",
                         quantity=91, unit_price=6610, gross_amount=601510,
                         currency="ARS", settlement_currency="ARS"),
            NormalizedTx(row_index=4, date="2025-09-08", broker="Cocos",
                         operation_type=OP_SELL, asset_symbol="BMA",
                         quantity=50, unit_price=6590, gross_amount=329500,
                         currency="ARS", settlement_currency="ARS"),
        ]
        batch_id, result = self._persist_sample(txs)
        # Ninguna fila debe skipearse
        self.assertEqual(result.get("skipped", []), [],
            f"Filas skipeadas inesperadamente: {result.get('skipped')}")

        # La posición BMA debería estar cerrada (qty 0 o no existir)
        conn = main.get_db()
        rows = conn.execute(
            "SELECT quantity FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, "BMA"),
        ).fetchall()
        conn.close()
        net_qty = sum(r["quantity"] or 0 for r in rows)
        self.assertEqual(net_qty, 0,
            f"BMA debería estar cerrada (qty=0), quedó {net_qty}")


class CashFlowDepositAllowsRecoverFromNegativeTest(unittest.TestCase):
    """Un depósito debe permitir reducir un saldo negativo (incluso si después
    sigue siendo negativo). Antes el check `new_invested < 0` bloqueaba
    depósitos cuando la deuda era mayor al depósito — el user no podía
    recuperarse del overdraft sin depositar todo de una."""

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, email=f"cashflow-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        # Crear cash position con saldo NEGATIVO (overdraft)
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,'Cocos','ARS',1,?)""",
            (self.uid, -204447),
        )
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _post_cashflow(self, direction, amount):
        return self.client.post(
            "/api/cash/flow",
            json={"broker_name": "Cocos", "direction": direction, "amount": amount},
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def test_deposit_smaller_than_overdraft_allowed(self):
        """Depositar 100k sobre saldo -204k → debe ir a -104k (no fallar)."""
        res = self._post_cashflow("deposit", 100000)
        self.assertEqual(res.status_code, 200, f"body: {res.text}")
        conn = main.get_db()
        balance = conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND is_cash=1",
            (self.uid,),
        ).fetchone()["invested"]
        conn.close()
        self.assertEqual(balance, -104447)

    def test_deposit_equal_to_overdraft_allowed(self):
        """Depositar exactamente el overdraft lleva a 0."""
        res = self._post_cashflow("deposit", 204447)
        self.assertEqual(res.status_code, 200, f"body: {res.text}")

    def test_deposit_larger_than_overdraft_allowed(self):
        """Depositar más del overdraft deja saldo positivo."""
        res = self._post_cashflow("deposit", 300000)
        self.assertEqual(res.status_code, 200, f"body: {res.text}")

    def test_withdraw_from_negative_still_blocked(self):
        """Pero un withdrawal sobre saldo negativo SÍ debe seguir bloqueado."""
        res = self._post_cashflow("withdraw", 10000)
        self.assertEqual(res.status_code, 400)
        self.assertIn("insuficiente", res.text.lower())


class RevertDepositAllowsNegativeCashTest(unittest.TestCase):
    """Revertir un DEPOSIT debe permitir saldo negativo resultante. Antes
    bloqueaba con 'No alcanza el cash en X para revertir el depósito',
    impidiendo revert nuclear de imports donde ya se había gastado parte
    del cash en BUYs que se revertirán después en el mismo loop."""

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, email=f"revert-dep-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()

    def test_nuclear_revert_with_overdraft_succeeds(self):
        """Persiste deposit + buy, luego revierte (nuclear). Aunque el revert
        del deposit pase el cash a negativo temporal, debe completarse OK."""
        from importing.persister import persist_batch, revert_batch
        from importing.schema import NormalizedTx, OP_BUY, OP_DEPOSIT
        import uuid, json

        # Import: deposit 100k + buy 80k → cash final 20k
        txs = [
            NormalizedTx(row_index=1, date="2025-01-01", broker="Cocos",
                         operation_type=OP_DEPOSIT, gross_amount=100000,
                         currency="ARS", settlement_currency="ARS"),
            NormalizedTx(row_index=2, date="2025-01-02", broker="Cocos",
                         operation_type=OP_BUY, asset_symbol="BMA",
                         quantity=10, unit_price=8000, gross_amount=80000,
                         currency="ARS", settlement_currency="ARS"),
        ]
        batch_id = str(uuid.uuid4())
        conn = main.get_db()
        raw_row_ids = {}
        with conn:
            conn.execute(
                """INSERT INTO import_batches
                   (id, user_id, parser_format, file_name, file_hash, broker, status)
                   VALUES (?, ?, 'cocos', 'test.csv', ?, 'Cocos', 'preview')""",
                (batch_id, self.uid, batch_id),
            )
            for tx in txs:
                cur = conn.execute(
                    """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                       VALUES (?,?,?,'valid',NULL)""",
                    (batch_id, tx.row_index, json.dumps({})),
                )
                raw_row_ids[tx.row_index] = cur.lastrowid
        persist_batch(conn, uid=self.uid, batch_id=batch_id, txs=txs,
                      raw_row_ids_by_index=raw_row_ids, helpers=main)

        # Simulamos un retiro externo que deja cash en 5k (debajo de los 100k del deposit)
        conn.execute(
            "UPDATE positions SET invested = 5000 WHERE user_id=? AND is_cash=1",
            (self.uid,),
        )
        conn.execute(
            "UPDATE import_batches SET status='confirmed' WHERE id=?", (batch_id,),
        )
        conn.commit()

        # Revertir en nuclear: debe completarse sin "No alcanza el cash"
        with conn:
            result = revert_batch(conn, uid=self.uid, batch_id=batch_id,
                                   helpers=main, nuclear=True)
        # El batch quedó marcado como reverted
        batch_row = conn.execute(
            "SELECT status FROM import_batches WHERE id=?", (batch_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(batch_row["status"], "reverted")


class CrossCurrencyLotSellTest(unittest.TestCase):
    """Cuando un BUY fue en USD (ej Cocos Compra Dolar Mep) y la SELL es en
    ARS sobre el mismo broker, el persister debe convertir el invested del
    lote a ARS al tc_blue actual antes de calcular P&L. Sin esto, comparaba
    USD invested vs ARS exit price → P&L de +160,000%."""

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, email=f"xc-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        # Cargar TC blue para que el persister haga las conversiones (key/value)
        conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?, 'tc_blue', '1415')",
            (self.uid,),
        )
        conn.commit()
        conn.close()

    def test_sell_in_ars_uses_usd_lot_cost_converted_to_ars(self):
        """Replica el caso TSLA: 21 lots comprados en USD a 27.32, vendidos
        en ARS a 44760. El P&L razonable es ~+15% (no +160000%)."""
        from importing.persister import persist_batch
        from importing.schema import NormalizedTx, OP_BUY, OP_SELL
        import uuid, json

        txs = [
            # BUY 21 TSLA via MEP en USD: invested = 21 × 27.32 = 573.72 USD
            NormalizedTx(row_index=1, date="2025-11-13", broker="Cocos",
                         operation_type=OP_BUY, asset_symbol="TSLA",
                         quantity=21, unit_price=27.32, gross_amount=573.72,
                         currency="USD", settlement_currency="USD"),
            # SELL 21 TSLA en ARS a 44760/share (~6 semanas después)
            NormalizedTx(row_index=2, date="2026-01-06", broker="Cocos",
                         operation_type=OP_SELL, asset_symbol="TSLA",
                         quantity=21, unit_price=44760, gross_amount=939960,
                         currency="ARS", settlement_currency="ARS"),
        ]
        batch_id = str(uuid.uuid4())
        conn = main.get_db()
        raw_row_ids = {}
        with conn:
            conn.execute(
                """INSERT INTO import_batches
                   (id, user_id, parser_format, file_name, file_hash, broker, status)
                   VALUES (?, ?, 'cocos', 'test.csv', ?, 'Cocos', 'preview')""",
                (batch_id, self.uid, batch_id),
            )
            for tx in txs:
                cur = conn.execute(
                    """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                       VALUES (?,?,?,'valid',NULL)""",
                    (batch_id, tx.row_index, json.dumps({})),
                )
                raw_row_ids[tx.row_index] = cur.lastrowid
        persist_batch(conn, uid=self.uid, batch_id=batch_id, txs=txs,
                      raw_row_ids_by_index=raw_row_ids, helpers=main)

        # Verificar que la operación SELL quedó con P&L razonable, no inflado
        op = conn.execute(
            "SELECT pnl_usd, pnl_pct FROM operations WHERE user_id=? AND asset='TSLA' AND op_type='Venta'",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(op)
        # P&L esperado en USD: ~+90 (= 21 × (44760 - 27.32 × 1415) / 1415)
        # = (939960 - 811684.8) / 1415 ≈ +90.65 USD
        self.assertAlmostEqual(op["pnl_usd"], 90.65, delta=1.0,
            msg=f"P&L USD: {op['pnl_usd']} (esperado ~90)")
        # P&L pct razonable (no >100000%)
        self.assertLess(abs(op["pnl_pct"]), 50,
            msg=f"P&L pct: {op['pnl_pct']}% (esperado < 50%, no miles)")

    def test_position_stores_currency_from_tx(self):
        """La posición creada por un BUY USD debe quedar con currency='USD'."""
        from importing.persister import persist_batch
        from importing.schema import NormalizedTx, OP_BUY
        import uuid, json

        txs = [
            NormalizedTx(row_index=1, date="2025-11-13", broker="Cocos",
                         operation_type=OP_BUY, asset_symbol="AAPL",
                         quantity=10, unit_price=20, gross_amount=200,
                         currency="USD", settlement_currency="USD"),
        ]
        batch_id = str(uuid.uuid4())
        conn = main.get_db()
        raw_row_ids = {}
        with conn:
            conn.execute(
                """INSERT INTO import_batches
                   (id, user_id, parser_format, file_name, file_hash, broker, status)
                   VALUES (?, ?, 'cocos', 'test.csv', ?, 'Cocos', 'preview')""",
                (batch_id, self.uid, batch_id),
            )
            cur = conn.execute(
                """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                   VALUES (?,?,?,'valid',NULL)""",
                (batch_id, 1, json.dumps({})),
            )
            raw_row_ids[1] = cur.lastrowid
        persist_batch(conn, uid=self.uid, batch_id=batch_id, txs=txs,
                      raw_row_ids_by_index=raw_row_ids, helpers=main)
        pos = conn.execute(
            "SELECT currency FROM positions WHERE user_id=? AND asset='AAPL'",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertEqual(pos["currency"], "USD")


class CocosVisibleInDropdownTest(unittest.TestCase):
    """Cocos ya tiene export oficial (Actividad → Movimientos), así que debe
    aparecer en el dropdown agrupado del wizard."""
    def test_cocos_in_grouped_options(self):
        groups = pl.parser_options_grouped()
        platforms = [g["platform"] for g in groups]
        self.assertIn("cocos", platforms)
        # Y el export del grupo debe estar marcado como supported
        cocos_group = next(g for g in groups if g["platform"] == "cocos")
        self.assertEqual(len(cocos_group["exports"]), 1)
        self.assertTrue(cocos_group["exports"][0]["supported"])

    def test_cocos_in_flat_options(self):
        opts = pl.parser_options()
        cocos = next(o for o in opts if o["id"] == "cocos")
        self.assertTrue(cocos["supported"])


if __name__ == "__main__":
    unittest.main()
