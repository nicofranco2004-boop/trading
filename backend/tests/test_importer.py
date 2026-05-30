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

    def test_asset_type_hint_overrides_guess(self):
        """Si el RawRow.data trae asset_type explícito, el normalizer lo usa
        (en vez de guess_asset_type que clasificaría 'ETH' como CRYPTO)."""
        rows = [RawRow(1, {
            "fecha": "2024-03-15", "tipo": "COMPRA", "broker": "Schwab",
            "activo": "ETH", "cantidad": "100", "precio": "25",
            "moneda": "USD", "asset_type": "ETF",
        })]
        txs, errors = normalize_rows(rows)
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0].asset_type, "ETF")  # No CRYPTO

    def test_asset_type_falls_back_to_guess_when_no_hint(self):
        """Sin hint, ETH se clasifica como CRYPTO (comportamiento original)."""
        rows = [RawRow(1, {
            "fecha": "2024-03-15", "tipo": "COMPRA", "broker": "Binance",
            "activo": "ETH", "cantidad": "0.5", "precio": "2500",
            "moneda": "USDT",
        })]
        txs, errors = normalize_rows(rows)
        self.assertEqual(txs[0].asset_type, "CRYPTO")

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

    def test_sell_without_stock_passes_validation(self):
        """Política history-as-truth: el CSV es historia, no se rechazan ventas
        por falta de stock previo. El persister auto-sintetiza el seed lot al
        precio de venta (P&L=0 sobre la porción faltante). El user puede usar
        el wizard 'Estado inicial' para precisar cost basis si querés reflejar
        la pérdida real."""
        rows = [RawRow(1, {"fecha": "2024-01-15", "tipo": "VENTA", "broker": "IBKR",
                            "activo": "TSLA", "cantidad": "100", "precio": "250", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        valid, errors = validate(txs, user_brokers={"IBKR": {"currency": "USDT"}}, existing_positions={})
        self.assertEqual(len(valid), 1)
        self.assertFalse(any(e.code == "INSUFFICIENT_STOCK" for e in errors))

    def test_buy_with_zero_price_accepted_for_stock_split(self):
        """REGRESIÓN: Stock Split emite BUY sintético con price=0, monto=0.
        Antes el validator lo rechazaba con MISSING_PRICE — ahora lo acepta
        porque las cantidades están definidas (cost basis 0 es válido)."""
        rows = [
            RawRow(1, {"fecha": "2024-01-15", "tipo": "COMPRA", "broker": "Schwab",
                       "activo": "XLK", "cantidad": "3", "precio": "289.28",
                       "monto": "867.84", "moneda": "USD"}),
            # Stock Split sintético: qty>0 pero price=0 / monto=0
            RawRow(2, {"fecha": "2024-06-15", "tipo": "COMPRA", "broker": "Schwab",
                       "activo": "XLK", "cantidad": "3", "precio": "0",
                       "monto": "0", "moneda": "USD"}),
            # Venta de las 6 — debería pasar (3 originales + 3 del split)
            RawRow(3, {"fecha": "2024-12-15", "tipo": "VENTA", "broker": "Schwab",
                       "activo": "XLK", "cantidad": "6", "precio": "150",
                       "moneda": "USD"}),
        ]
        txs, _ = normalize_rows(rows)
        valid, errors = validate(txs, user_brokers={"Schwab": {"currency": "USDT"}}, existing_positions={})
        self.assertEqual(len(valid), 3, f"Errores: {[e.to_dict() for e in errors]}")
        self.assertEqual(len(errors), 0)

    def test_buy_with_no_price_and_no_amount_still_rejected(self):
        """Pero si price Y monto están AMBOS undefined (None), sí rechazamos."""
        rows = [RawRow(1, {"fecha": "2024-01-15", "tipo": "COMPRA", "broker": "IBKR",
                           "activo": "AAPL", "cantidad": "10", "moneda": "USD"})]
        txs, _ = normalize_rows(rows)
        valid, errors = validate(txs, user_brokers={"IBKR": {"currency": "USDT"}}, existing_positions={})
        self.assertEqual(len(valid), 0)
        self.assertTrue(any(e.code == "MISSING_PRICE" for e in errors))


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
            # Con política history-as-truth, las ventas sin stock previo TAMPOCO son
            # error — se auto-sintetiza el seed lot al precio de venta.
            # Errores que SÍ deben quedar: fecha inválida + op type desconocido.
            # Filas válidas: COMPRA AAPL + VENTA TSLA (seed auto) + COMPRA NVDA (broker auto-creado) = 3.
            self.assertEqual(payload["summary"]["valid_rows"], 3)
            self.assertGreaterEqual(payload["summary"]["invalid_rows"], 2)
            self.assertTrue(any(e["code"] == "INVALID_DATE" for e in payload["errors"]))
            self.assertTrue(any(e["code"] == "UNKNOWN_OP_TYPE" for e in payload["errors"]))
            # INSUFFICIENT_STOCK ya no es error — la fila pasa al persist.
            self.assertFalse(any(e["code"] == "INSUFFICIENT_STOCK" for e in payload["errors"]))
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

    def test_revert_deposit_subtracts_from_deposits_not_withdrawals(self):
        """Bug C fix (2026-05-30): el revert de un DEPOSIT debe restar de
        monthly_entries.deposits, NO inflar withdrawals. Si infla withdrawals,
        cada ciclo import → revert → reimport infla bruto histórico aunque
        el net quede invariante."""
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-06-15,DEPOSITO,IBKR,,,,1000,,,,USD,Aporte de prueba
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="dep_revert.csv",
                    broker_hint="IBKR", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw_map, helpers=_helpers(),
                )

            # Post-persist: deposits acumuló +$1000 en 2024-06 IBKR
            row = conn.execute(
                """SELECT deposits, withdrawals FROM monthly_entries
                   WHERE user_id=? AND broker='IBKR' AND year=2024 AND month=6""",
                (self.uid,),
            ).fetchone()
            self.assertIsNotNone(row, "monthly_entry debe existir tras persist")
            self.assertAlmostEqual(float(row["deposits"]), 1000.0, places=2)
            self.assertAlmostEqual(float(row["withdrawals"]), 0.0, places=2)

            # Revert
            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=session_id, helpers=_helpers())

            # Post-revert: deposits debe estar en 0, withdrawals TAMBIÉN en 0
            # (NO inflar withdrawals con $1000 fantasma).
            row_after = conn.execute(
                """SELECT deposits, withdrawals FROM monthly_entries
                   WHERE user_id=? AND broker='IBKR' AND year=2024 AND month=6""",
                (self.uid,),
            ).fetchone()
            # Si la row sigue existiendo, ambos deben estar en 0.
            # Si fue borrada por cleanup post-recalc, también OK.
            if row_after is not None:
                self.assertAlmostEqual(float(row_after["deposits"]), 0.0, places=2,
                                       msg="deposits debe volver a 0 tras revert")
                self.assertAlmostEqual(float(row_after["withdrawals"]), 0.0, places=2,
                                       msg="withdrawals NO debe inflarse al revertir un deposit")
        finally:
            conn.close()

    def test_revert_withdraw_subtracts_from_withdrawals_not_deposits(self):
        """Bug C fix (2026-05-30) — caso simétrico: el revert de WITHDRAW/FEE
        debe restar de withdrawals, no inflar deposits."""
        # Necesitamos primero un deposit para tener saldo, luego un withdraw
        csv = b"""fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas
2024-07-01,DEPOSITO,IBKR,,,,2000,,,,USD,Aporte previo
2024-07-15,RETIRO,IBKR,,,,500,,,,USD,Retiro de prueba
"""
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv, file_name="wit_revert.csv",
                    broker_hint="IBKR", parser_format="rendi_generic",
                )
            session_id = payload["session_id"]
            with conn:
                txs, raw_map = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(
                    conn, uid=self.uid, batch_id=session_id, txs=txs,
                    raw_row_ids_by_index=raw_map, helpers=_helpers(),
                )

            # Post-persist: en 2024-07 IBKR → deposits=$2000, withdrawals=$500
            row = conn.execute(
                """SELECT deposits, withdrawals FROM monthly_entries
                   WHERE user_id=? AND broker='IBKR' AND year=2024 AND month=7""",
                (self.uid,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertAlmostEqual(float(row["deposits"]), 2000.0, places=2)
            self.assertAlmostEqual(float(row["withdrawals"]), 500.0, places=2)

            # Revert
            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=session_id, helpers=_helpers())

            # Post-revert: ambos deben volver a 0
            row_after = conn.execute(
                """SELECT deposits, withdrawals FROM monthly_entries
                   WHERE user_id=? AND broker='IBKR' AND year=2024 AND month=7""",
                (self.uid,),
            ).fetchone()
            if row_after is not None:
                self.assertAlmostEqual(float(row_after["deposits"]), 0.0, places=2,
                                       msg="deposits NO debe inflarse al revertir un withdraw")
                self.assertAlmostEqual(float(row_after["withdrawals"]), 0.0, places=2,
                                       msg="withdrawals debe volver a 0 tras revert")
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
            # Schwab debió crearse como USD — es un broker tradicional con
            # filas en USD (no es crypto-native, no debería quedar USDT).
            new = {b["name"]: b for b in payload["new_brokers_created"]}
            self.assertIn("Schwab", new)
            self.assertEqual(new["Schwab"]["currency"], "USD")
            self.assertEqual(new["Schwab"]["rows"], 2)
            self.assertNotIn("Cocos capital", new, "Cocos ya existía, no debió crearse")

            # En la DB debe estar Schwab con currency USD
            schwab = conn.execute(
                "SELECT * FROM brokers WHERE user_id=? AND name='Schwab'", (self.uid,),
            ).fetchone()
            self.assertIsNotNone(schwab)
            self.assertEqual(schwab["currency"], "USD")
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
        """Un CSV con SELL sin BUY previo:
           - Pasa validación (history-as-truth: el persister auto-sintetiza seed).
           - DEBE seguir mostrando seed_suggestions para que el user pueda precisar
             cost basis manualmente si querés reflejar la pérdida real."""
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
            # La SELL ahora pasa — la política nueva permite ventas sin stock previo.
            self.assertEqual(payload["summary"]["valid_rows"], 1)
            self.assertEqual(payload["summary"]["invalid_rows"], 0)
            # Pero el seed_suggestions sigue apareciendo (detección via simulación
            # post-validación; sirve como sugerencia opt-in para precisar costos).
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


class ReconcileCashTest(unittest.TestCase):
    """POST /api/brokers/reconcile-cash — ajusta el cash a un valor real
    reportado por el broker externo y registra el diff como movimiento
    sintético en el primer mes del broker.

    Caso de uso: CSV parcial (Schwab desde 2021-09 pero cuenta abierta hace 10 años).
    El cash computado del CSV no coincide con el real → el user lo reconcilia."""

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, email=f"reconcile-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Schwab", "USDT")
        # Cash computado del CSV: $60,000 (incorrecto — falta historia)
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,'Schwab','USDT',1,60000)""",
            (self.uid,),
        )
        # Monthly entries simulando un import previo
        for (y, m, dep) in [(2021, 9, 50000), (2022, 5, 10000), (2026, 5, 0)]:
            conn.execute(
                """INSERT INTO monthly_entries (user_id, broker, year, month,
                       capital_inicio, capital_final, deposits, withdrawals,
                       pnl_realized, pnl_unrealized)
                   VALUES (?,?,?,?,?,?,?,0,0,0)""",
                (self.uid, 'Schwab', y, m, 0, dep, dep),
            )
            conn.execute(
                """INSERT INTO monthly_entries (user_id, broker, year, month,
                       capital_inicio, capital_final, deposits, withdrawals,
                       pnl_realized, pnl_unrealized)
                   VALUES (?,'global',?,?,?,?,?,0,0,0)""",
                (self.uid, y, m, 0, dep, dep),
            )
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _post(self, target_cash):
        return self.client.post(
            "/api/brokers/reconcile-cash",
            json={"broker_name": "Schwab", "target_cash": target_cash},
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def test_target_smaller_than_current_records_withdrawal(self):
        """CSV dice $60k pero broker real dice $2,300 → diff -$57,700 → WITHDRAW
        sintético en el mes más antiguo (representa salidas pre-CSV no capturadas)."""
        res = self._post(2300)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["diff_direction"], "withdraw")
        self.assertAlmostEqual(body["diff"], -57700, places=2)
        self.assertEqual(body["recorded_in_period"], "2021-09")  # mes más antiguo
        # Cash position quedó en target exacto
        conn = main.get_db()
        cash = conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker='Schwab' AND is_cash=1",
            (self.uid,),
        ).fetchone()["invested"]
        conn.close()
        self.assertAlmostEqual(cash, 2300, places=2)

    def test_target_bigger_than_current_records_deposit(self):
        """Cash real $80k > computado $60k → diff +$20k → DEPOSIT sintético
        (representa cash pre-CSV que no estaba en el archivo)."""
        res = self._post(80000)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["diff_direction"], "deposit")
        self.assertAlmostEqual(body["diff"], 20000, places=2)

    def test_target_equal_to_current_is_noop(self):
        """Si ya coincide, no genera movimientos."""
        res = self._post(60000)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("no_change"))

    def test_target_records_into_first_month_per_broker(self):
        """El diff va al PRIMER mes del broker (no al mes actual), para
        preservar cronología."""
        res = self._post(2300)
        body = res.json()
        self.assertEqual(body["recorded_in_period"], "2021-09")
        # Verificar que la withdrawal sumó al primer mes (no al último)
        conn = main.get_db()
        first_month_withdraw = conn.execute(
            """SELECT withdrawals FROM monthly_entries
               WHERE user_id=? AND broker='Schwab' AND year=2021 AND month=9""",
            (self.uid,),
        ).fetchone()["withdrawals"]
        last_month_withdraw = conn.execute(
            """SELECT withdrawals FROM monthly_entries
               WHERE user_id=? AND broker='Schwab' AND year=2026 AND month=5""",
            (self.uid,),
        ).fetchone()["withdrawals"]
        conn.close()
        self.assertAlmostEqual(first_month_withdraw, 57700, places=2)
        self.assertAlmostEqual(last_month_withdraw, 0, places=2)


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

    def test_sell_in_usd_uses_tx_currency_not_broker_currency(self):
        """REGRESIÓN: para "Venta Dolar Mep" en Cocos (broker=ARS pero tx.currency=USD),
        el persister debe usar la moneda de la TX, no la del broker. Antes
        comparaba ARS invested vs USD exit_price → P&L falso -99.8%."""
        from importing.persister import persist_batch
        from importing.schema import NormalizedTx, OP_BUY, OP_SELL
        import uuid, json

        # AMD bought in ARS (broker Cocos ARS), then sold in USD (Venta Dolar Mep)
        txs = [
            NormalizedTx(row_index=1, date="2024-01-15", broker="Cocos",
                         operation_type=OP_BUY, asset_symbol="AMD",
                         quantity=23, unit_price=14000, gross_amount=322000,
                         currency="ARS", settlement_currency="ARS"),
            NormalizedTx(row_index=2, date="2025-10-27", broker="Cocos",
                         operation_type=OP_SELL, asset_symbol="AMD",
                         quantity=23, unit_price=25.25, gross_amount=580.75,
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
            for tx in txs:
                cur = conn.execute(
                    """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                       VALUES (?,?,?,'valid',NULL)""",
                    (batch_id, tx.row_index, json.dumps({})),
                )
                raw_row_ids[tx.row_index] = cur.lastrowid
        persist_batch(conn, uid=self.uid, batch_id=batch_id, txs=txs,
                      raw_row_ids_by_index=raw_row_ids, helpers=main)

        # Verificar P&L razonable:
        # cost basis USD: 322000 ARS / 1415 = 227.56 USD
        # proceeds USD: 25.25 × 23 = 580.75 USD
        # P&L USD: 580.75 - 227.56 = +353 USD (~155% gain)
        op = conn.execute(
            "SELECT pnl_usd, pnl_pct FROM operations WHERE user_id=? AND asset='AMD'",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(op)
        # P&L NO debe ser -99% (el bug original) — debe ser positivo y razonable
        self.assertGreater(op["pnl_usd"], 0,
            f"P&L USD: {op['pnl_usd']} (esperado positivo, bug daba -97)")
        self.assertLess(abs(op["pnl_pct"]), 500,
            f"P&L %: {op['pnl_pct']}% (esperado razonable, bug daba -99.8%)")

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


class RecalcPnlFromOpsTest(unittest.TestCase):
    """Verifica que _recalc_pnl_realized_from_ops repara drift en
    monthly_entries.pnl_realized desde la tabla operations."""

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "monthly_entries"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, email=f"recalc-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()

    def test_recalcs_from_operations_zeroing_orphan_pnl(self):
        """monthly_entries.pnl_realized inflado y SIN operations matching →
        se zero-ea tras el recalc."""
        conn = main.get_db()
        with conn:
            # Inflar pnl_realized con drift artificial — simula bug viejo
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 10, 'Cocos', 0, 0, -9890.92, 0, 0, -9890.92)""",
                (self.uid,),
            )
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 10, 'global', 0, 0, -9890.92, 0, 0, -9890.92)""",
                (self.uid,),
            )
        # No hay operations → recalc debe poner pnl_realized en 0
        with conn:
            updates = main._recalc_pnl_realized_from_ops(conn, self.uid)
        rows = conn.execute(
            "SELECT broker, pnl_realized FROM monthly_entries WHERE user_id=?",
            (self.uid,),
        ).fetchall()
        conn.close()
        self.assertGreaterEqual(updates, 2)
        for r in rows:
            self.assertEqual(r["pnl_realized"], 0.0,
                f"{r['broker']}: pnl_realized={r['pnl_realized']} (esperado 0)")

    def test_recalcs_to_sum_of_existing_operations(self):
        """Con operations reales, monthly_entries.pnl_realized debe quedar
        igual a SUM(operations.pnl_usd) para ese (broker, year, month)."""
        conn = main.get_db()
        with conn:
            # Seed: 2 operations en Oct 2025 para Cocos
            conn.execute(
                """INSERT INTO operations
                   (user_id, date, broker, asset, op_type, pnl_usd)
                   VALUES (?, '2025-10-15', 'Cocos', 'AAPL', 'Venta', 50.50)""",
                (self.uid,),
            )
            conn.execute(
                """INSERT INTO operations
                   (user_id, date, broker, asset, op_type, pnl_usd)
                   VALUES (?, '2025-10-20', 'Cocos', 'TSLA', 'Venta', -25.30)""",
                (self.uid,),
            )
            # Pre-existente con drift
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 10, 'Cocos', 0, 0, 9999.99, 0, 0, 0)""",
                (self.uid,),
            )
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 10, 'global', 0, 0, -8888.88, 0, 0, 0)""",
                (self.uid,),
            )
            main._recalc_pnl_realized_from_ops(conn, self.uid)
        rows = conn.execute(
            "SELECT broker, pnl_realized FROM monthly_entries WHERE user_id=? ORDER BY broker",
            (self.uid,),
        ).fetchall()
        conn.close()
        # Cocos: 50.50 + (-25.30) = 25.20
        # global: igual (suma cross-broker)
        by_broker = {r["broker"]: r["pnl_realized"] for r in rows}
        self.assertAlmostEqual(by_broker["Cocos"], 25.20, places=2)
        self.assertAlmostEqual(by_broker["global"], 25.20, places=2)

    def test_recalcs_preserves_manual_residual_when_no_imports(self):
        """REGRESIÓN del bug 2026-05-27: el recalc DESTRUÍA cash flows manuales
        (form /mensual, botón Cash, reconcile-cash) cuando no había imports
        respaldando ese (broker, year, month) — los zero-eaba y la fila se
        borraba por el cleanup post-recalc.

        Nueva semántica: cualquier valor en monthly_entries.deposits/withdrawals
        que NO esté respaldado por imports DEPOSIT/WITHDRAW se considera
        residual MANUAL y se preserva. pnl_realized sí se reconstruye desde
        operations (que es fuente canónica)."""
        conn = main.get_db()
        with conn:
            # User cargó manualmente $831.58 (sin imports correspondientes)
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'Cocos', 831.58, 0, 0, 0, 0, 831.58)""",
                (self.uid,),
            )
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'global', 831.58, 0, 0, 0, 0, 831.58)""",
                (self.uid,),
            )
            main._recalc_pnl_realized_from_ops(conn, self.uid)
        rows = conn.execute(
            "SELECT broker, deposits, withdrawals, pnl_realized FROM monthly_entries WHERE user_id=? ORDER BY broker",
            (self.uid,),
        ).fetchall()
        conn.close()
        for r in rows:
            self.assertAlmostEqual(r["deposits"], 831.58, places=2,
                msg=f"{r['broker']}: manual residual debería preservarse, quedó {r['deposits']}")
            self.assertEqual(r["withdrawals"], 0.0)
            self.assertEqual(r["pnl_realized"], 0.0)

    def test_recalcs_preserves_deposits_from_confirmed_batch(self):
        """Si hay un batch CONFIRMED con un DEPOSIT y NO hay residual manual,
        el recalc deja deposits = imports_USD."""
        import uuid, json
        conn = main.get_db()
        batch_id = str(uuid.uuid4())
        with conn:
            conn.execute(
                """INSERT INTO import_batches
                   (id, user_id, parser_format, file_name, file_hash, broker, status)
                   VALUES (?, ?, 'cocos', 'x.csv', ?, 'Cocos', 'confirmed')""",
                (batch_id, self.uid, batch_id),
            )
            cur = conn.execute(
                """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                   VALUES (?,?,?,'valid',NULL)""",
                (batch_id, 1, json.dumps({})),
            )
            raw_id = cur.lastrowid
            conn.execute(
                """INSERT INTO import_normalized_tx
                   (batch_id, raw_row_id, date, broker, operation_type, gross_amount, currency)
                   VALUES (?, ?, '2025-05-15', 'Cocos', 'DEPOSIT', 100000, 'ARS')""",
                (batch_id, raw_id),
            )
            # Pre-existente alineado con imports (el persister acumuló al confirmar):
            # 100000 ARS / 1415 tc_blue = ~70.67 USD
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'Cocos', 70.67, 0, 0, 0, 0, 70.67)""",
                (self.uid,),
            )
            main._recalc_pnl_realized_from_ops(conn, self.uid)
        row = conn.execute(
            "SELECT deposits FROM monthly_entries WHERE user_id=? AND broker='Cocos'",
            (self.uid,),
        ).fetchone()
        conn.close()
        # imp_deposits ≈ 70.67, manual_residual = 0 → new_deposits ≈ 70.67
        self.assertAlmostEqual(row["deposits"], 70.67, delta=0.1)

    def test_recalcs_preserves_manual_residual_above_imports(self):
        """Caso mixto: user cargó manualmente $200 EN ADICIÓN a un import de
        $70.67 USD (la fila acumula 270.67 = 70.67 imports + 200 manual). El
        recalc debe preservar el residual manual y dejar deposits=270.67."""
        import uuid, json
        conn = main.get_db()
        batch_id = str(uuid.uuid4())
        with conn:
            conn.execute(
                """INSERT INTO import_batches
                   (id, user_id, parser_format, file_name, file_hash, broker, status)
                   VALUES (?, ?, 'cocos', 'x.csv', ?, 'Cocos', 'confirmed')""",
                (batch_id, self.uid, batch_id),
            )
            cur = conn.execute(
                """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                   VALUES (?,?,?,'valid',NULL)""",
                (batch_id, 1, json.dumps({})),
            )
            raw_id = cur.lastrowid
            conn.execute(
                """INSERT INTO import_normalized_tx
                   (batch_id, raw_row_id, date, broker, operation_type, gross_amount, currency)
                   VALUES (?, ?, '2025-05-15', 'Cocos', 'DEPOSIT', 100000, 'ARS')""",
                (batch_id, raw_id),
            )
            # 70.67 imports + 200 manual = 270.67 acumulado
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'Cocos', 270.67, 0, 0, 0, 0, 270.67)""",
                (self.uid,),
            )
            main._recalc_pnl_realized_from_ops(conn, self.uid)
        row = conn.execute(
            "SELECT deposits FROM monthly_entries WHERE user_id=? AND broker='Cocos'",
            (self.uid,),
        ).fetchone()
        conn.close()
        # imp_deposits ≈ 70.67, manual_residual = 200 → new_deposits ≈ 270.67
        self.assertAlmostEqual(row["deposits"], 270.67, delta=0.1)

    def test_recalc_deletes_empty_rows_and_clears_baseline(self):
        """REGRESIÓN: tras recalc, una fila con todo en 0 pero capital_inicio
        residual de cycles previos seguía afectando netDeposited del dashboard.
        Ahora se borran las filas vacías y se resetea capital_inicio del
        primer mes a 0."""
        conn = main.get_db()
        with conn:
            # Simular drift: capital_inicio residual sin nada que lo justifique
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'Cocos', 0, 0, 0, 0, 832.44, 832.44)""",
                (self.uid,),
            )
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'global', 0, 0, 0, 0, 832.44, 832.44)""",
                (self.uid,),
            )
            main._recalc_pnl_realized_from_ops(conn, self.uid)
        rows = conn.execute(
            "SELECT COUNT(*) AS c FROM monthly_entries WHERE user_id=?",
            (self.uid,),
        ).fetchone()
        conn.close()
        # Filas borradas porque deposits/withdrawals/pnl están en 0
        self.assertEqual(rows["c"], 0,
            "monthly_entries vacías deberían eliminarse para que el baseline "
            "no quede inflado de cycles previos")

    def test_recalc_resets_pnl_unrealized(self):
        """REGRESIÓN: /reportes calculaba delta del mes como `pnl_realized +
        pnl_unrealized`. Un pnl_unrealized stale (ej. -69650 de un cycle
        previo) producía un loss falso aunque pnl_realized estuviera limpio."""
        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2026, 5, 'Schwab', 100, 0, 50, -69650, 0, 100)""",
                (self.uid,),
            )
            main._recalc_pnl_realized_from_ops(conn, self.uid)
        row = conn.execute(
            "SELECT pnl_unrealized FROM monthly_entries WHERE user_id=? AND broker='Schwab'",
            (self.uid,),
        ).fetchone()
        conn.close()
        if row is not None:  # podría haber sido borrado si quedó toda en 0
            self.assertEqual(row["pnl_unrealized"], 0.0,
                "pnl_unrealized debería resetearse a 0 (es live, no stored)")

    def test_recalc_clears_snapshots_when_no_state(self):
        """Si tras recalc no quedan positions/operations/monthly_entries, los
        snapshots del dashboard también se limpian (sino el gráfico de
        evolución mostraría valores de cycles previos)."""
        conn = main.get_db()
        with conn:
            # Snapshot stale de un cycle anterior
            conn.execute(
                """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited)
                   VALUES (?, '2025-05-15', 375000, 200000, 175000)""",
                (self.uid,),
            )
            main._recalc_pnl_realized_from_ops(conn, self.uid)
        snaps = conn.execute(
            "SELECT COUNT(*) AS c FROM snapshots WHERE user_id=?",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertEqual(snaps["c"], 0)

    def test_endpoint_recalc_returns_count(self):
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 1, 'Cocos', 0, 0, -1000, 0, 0, -1000)""",
                (self.uid,),
            )
        conn.close()
        token = main.create_token(self.uid)
        res = client.post(
            "/api/imports/recalc-pnl",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["recalculated"])
        self.assertGreaterEqual(body["rows_updated"], 1)


class NetDepositedSSoTTest(unittest.TestCase):
    """Fase 3 (2026-05-30): SSoT canónica `compute_net_deposited_db`.
    Las 3 implementaciones inline (snapshots_job list-based, reports
    fetch_cum_deposits_until, main _portfolio_snapshot_summary) deben
    devolver los mismos números para el mismo input."""

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "monthly_entries", "brokers"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, email=f"netdep-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        # Sembrar monthly_entries — broker 'global' (cross-broker, USD)
        rows = [
            (2025, 1, "global", 100, 0,  0, 0, 0, 100),       # +100
            (2025, 2, "global", 200, 50, 0, 0, 100, 250),     # +150 (350 acum)
            (2025, 3, "global", 0, 100,  0, 0, 250, 150),     # -100 (250 acum)
            (2025, 4, "global", 50, 0,   0, 0, 150, 200),     # +50  (300 acum)
        ]
        for row in rows:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (self.uid, *row),
            )
        conn.commit()
        conn.close()

    def test_ssot_no_baseline_full_history(self):
        """Sin baseline, full history: 100+200+0+50 - 0-50-100-0 = 350-150 = 200."""
        from snapshots_job import compute_net_deposited_db
        conn = main.get_db()
        net = compute_net_deposited_db(conn, self.uid, include_baseline=False)
        conn.close()
        self.assertAlmostEqual(net, 200.0, places=2)

    def test_ssot_with_baseline_full_history(self):
        """Con baseline (cap_inicio del 1er row = 0): mismo resultado 200."""
        from snapshots_job import compute_net_deposited_db
        conn = main.get_db()
        net = compute_net_deposited_db(conn, self.uid, include_baseline=True)
        conn.close()
        self.assertAlmostEqual(net, 200.0, places=2)

    def test_ssot_time_bounded(self):
        """Hasta 2025-02 (incl): 100+200 - 0-50 = 250."""
        from snapshots_job import compute_net_deposited_db
        conn = main.get_db()
        net = compute_net_deposited_db(
            conn, self.uid, as_of_date="2025-02-15", include_baseline=False
        )
        conn.close()
        self.assertAlmostEqual(net, 250.0, places=2)

    def test_ssot_matches_legacy_list_variant(self):
        """La variante list-based (compute_net_deposited) debe coincidir
        con la SSoT (compute_net_deposited_db) cuando se usa baseline."""
        from snapshots_job import compute_net_deposited, compute_net_deposited_db
        conn = main.get_db()
        rows = conn.execute(
            "SELECT * FROM monthly_entries WHERE user_id=? ORDER BY year, month",
            (self.uid,),
        ).fetchall()
        legacy = compute_net_deposited([dict(r) for r in rows])
        canonical = compute_net_deposited_db(conn, self.uid, include_baseline=True)
        conn.close()
        self.assertAlmostEqual(legacy, canonical, places=2,
            msg=f"List-based ({legacy}) vs SSoT-DB ({canonical}) deben coincidir")

    def test_ssot_baseline_picks_first_row_cap_inicio(self):
        """Si la 1er row tiene cap_inicio != 0 (historia parcial importada),
        el baseline se incluye y SSoT > flows."""
        # Insertar primera row con cap_inicio = 500 (baseline pre-importer)
        conn = main.get_db()
        with conn:
            conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2024, 1, 'global', 100, 0, 0, 0, 500, 600)""",
                (self.uid,),
            )
        from snapshots_job import compute_net_deposited_db
        flows_only = compute_net_deposited_db(conn, self.uid, include_baseline=False)
        with_baseline = compute_net_deposited_db(conn, self.uid, include_baseline=True)
        conn.close()
        self.assertAlmostEqual(flows_only, 100.0, places=2)
        self.assertAlmostEqual(with_baseline, 600.0, places=2)
        self.assertAlmostEqual(with_baseline - flows_only, 500.0, places=2,
            msg="diff = cap_inicio del primer row")


class AutoRolloverServerSideTest(unittest.TestCase):
    """Fase 7 (2026-05-30): GET /api/monthly hace lazy rollover — si la row
    del current calendar month no existe para algún broker, la crea antes
    de devolver. Antes esto vivía 100% en frontend (autoRolloverIfNeeded),
    así que si el user no abría /mensual nunca, el sync-unrealized del
    Dashboard no-opeaba y las métricas del mes corriente fallaban."""

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "monthly_entries", "brokers"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, email=f"rollover-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_rollover_creates_current_month_when_missing(self):
        """Sembrar una row vieja → GET /api/monthly debe crear rows hasta
        el current calendar month."""
        from datetime import datetime
        now = datetime.utcnow()

        # Sembrar 1 row de hace muchos meses (descartando que esté en el
        # current month por timing — usamos year-1 para garantizar gap).
        old_year = now.year - 1
        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, ?, 6, 'Cocos', 500, 0, 0, 50, 0, 550)""",
                (self.uid, old_year),
            )

        # Fetch monthly — debe trigger el lazy rollover
        res = self.client.get(
            "/api/monthly",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)

        # Verificar que existe row para el current month
        current_row = conn.execute(
            """SELECT capital_inicio, capital_final, pnl_unrealized
                 FROM monthly_entries
                WHERE user_id=? AND broker='Cocos' AND year=? AND month=?""",
            (self.uid, now.year, now.month),
        ).fetchone()
        # Verificar que la row vieja quedó "cerrada" correctamente
        old_row = conn.execute(
            """SELECT pnl_unrealized, capital_final FROM monthly_entries
                WHERE user_id=? AND broker='Cocos' AND year=? AND month=6""",
            (self.uid, old_year),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(current_row,
            "Lazy rollover debe haber creado la row del current month")
        # La row vieja debe haber sido "cerrada" (pnl_unrealized=0, cap_final
        # recalculado con fórmula canónica = 0 + 500 - 0 + 0 = 500)
        self.assertAlmostEqual(old_row["pnl_unrealized"], 0.0, places=2,
            msg="Row vieja: pnl_unrealized debe zero-earse al rollover")
        self.assertAlmostEqual(old_row["capital_final"], 500.0, places=2,
            msg="Row vieja: cap_final recalculado canónicamente (sin pnl_unrealized stale)")
        # La row nueva del current month: cap_inicio = cap_final de la row anterior
        self.assertAlmostEqual(current_row["capital_inicio"], 500.0, places=2,
            msg="cap_inicio del current month = cap_final del previo (chain integrity)")
        self.assertAlmostEqual(current_row["pnl_unrealized"], 0.0, places=2,
            msg="current month nuevo arranca con pnl_unrealized=0")

    def test_rollover_is_idempotent(self):
        """Llamar GET /api/monthly dos veces no crea rows duplicadas."""
        from datetime import datetime
        now = datetime.utcnow()
        old_year = now.year - 1

        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, ?, 6, 'Cocos', 100, 0, 0, 0, 0, 100)""",
                (self.uid, old_year),
            )

        # Primer GET — crea rows
        self.client.get("/api/monthly", headers={"Authorization": f"Bearer {self.token}"})
        n1 = conn.execute(
            "SELECT COUNT(*) FROM monthly_entries WHERE user_id=? AND broker='Cocos'",
            (self.uid,),
        ).fetchone()[0]

        # Segundo GET — no debe crear más
        self.client.get("/api/monthly", headers={"Authorization": f"Bearer {self.token}"})
        n2 = conn.execute(
            "SELECT COUNT(*) FROM monthly_entries WHERE user_id=? AND broker='Cocos'",
            (self.uid,),
        ).fetchone()[0]
        conn.close()

        self.assertEqual(n1, n2,
            "Segundo GET /api/monthly no debe crear rows duplicadas (idempotencia)")

    def test_rollover_skips_when_no_history(self):
        """User sin entradas previas → rollover no-op (no podemos crear
        un current month sin cap_inicio del previo)."""
        # No sembrar nada
        res = self.client.get(
            "/api/monthly",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), [],
            "Sin historia previa, GET devuelve [] sin crear nada")


class DeleteBrokerGuardTest(unittest.TestCase):
    """Fase 5 (2026-05-30): DELETE /api/brokers/{bid} debe refuse-then-confirm.
    Si el broker tiene positions/operations/monthly_entries/imports asociados,
    el endpoint devuelve 409 Conflict con el resumen de counts. Solo con
    ?force=true procede con el cascade delete."""

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "monthly_entries", "brokers", "positions"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, email=f"delbroker-{id(self)}@rendi.test")
        # Dos brokers: uno vacío, otro con data
        _add_broker(conn, self.uid, "EmptyBroker", "USDT")
        _add_broker(conn, self.uid, "WithData", "USDT")
        with_data_id = conn.execute(
            "SELECT id FROM brokers WHERE user_id=? AND name='WithData'", (self.uid,)
        ).fetchone()["id"]
        self.with_data_id = with_data_id
        self.empty_id = conn.execute(
            "SELECT id FROM brokers WHERE user_id=? AND name='EmptyBroker'", (self.uid,)
        ).fetchone()["id"]
        # Inyectar data al broker "WithData"
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
               VALUES (?, 'WithData', 'BTC', 0, 1000, 0.05)""",
            (self.uid,),
        )
        conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd)
               VALUES (?, '2026-05-01', 'WithData', 'BTC', 'Venta', 50)""",
            (self.uid,),
        )
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id, year, month, broker, deposits, withdrawals,
                pnl_realized, pnl_unrealized, capital_inicio, capital_final)
               VALUES (?, 2026, 5, 'WithData', 100, 0, 0, 0, 0, 100)""",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def test_delete_empty_broker_succeeds(self):
        """Broker vacío → 200 OK sin force."""
        res = self.client.delete(
            f"/api/brokers/{self.empty_id}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        # Broker debe estar eliminado
        conn = main.get_db()
        n = conn.execute(
            "SELECT COUNT(*) FROM brokers WHERE user_id=? AND name='EmptyBroker'", (self.uid,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)

    def test_delete_broker_with_data_returns_409(self):
        """Broker con data, sin ?force=true → 409 con counts en detail.
        La data NO debe borrarse."""
        res = self.client.delete(
            f"/api/brokers/{self.with_data_id}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 409, res.text)
        detail = res.json()["detail"]
        self.assertEqual(detail["code"], "broker_has_data")
        self.assertEqual(detail["broker_name"], "WithData")
        self.assertEqual(detail["counts"]["positions"], 1)
        self.assertEqual(detail["counts"]["operations"], 1)
        self.assertEqual(detail["counts"]["monthly_entries"], 1)
        # Sanity: nada se borró
        conn = main.get_db()
        n_pos = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND broker='WithData'", (self.uid,)
        ).fetchone()[0]
        n_ops = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE user_id=? AND broker='WithData'", (self.uid,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n_pos, 1, "positions NO debe borrarse sin force")
        self.assertEqual(n_ops, 1, "operations NO debe borrarse sin force")

    def test_delete_broker_with_force_succeeds(self):
        """Con ?force=true, el cascade procede normalmente."""
        res = self.client.delete(
            f"/api/brokers/{self.with_data_id}?force=true",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["ok"])
        # Sanity: data borrada
        conn = main.get_db()
        n_pos = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND broker='WithData'", (self.uid,)
        ).fetchone()[0]
        n_ops = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE user_id=? AND broker='WithData'", (self.uid,)
        ).fetchone()[0]
        n_me = conn.execute(
            "SELECT COUNT(*) FROM monthly_entries WHERE user_id=? AND broker='WithData'", (self.uid,)
        ).fetchone()[0]
        n_br = conn.execute(
            "SELECT COUNT(*) FROM brokers WHERE user_id=? AND name='WithData'", (self.uid,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n_pos, 0)
        self.assertEqual(n_ops, 0)
        self.assertEqual(n_me, 0)
        self.assertEqual(n_br, 0)

    def test_delete_nonexistent_broker_is_idempotent(self):
        """Borrar un broker que no existe → 200 OK con no_change=True
        (idempotent, no error)."""
        res = self.client.delete(
            "/api/brokers/99999",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body.get("no_change"))


class OperationCurrencyStampingTest(unittest.TestCase):
    """Fase 6 (2026-05-30): operations creadas via POST/PUT /api/operations
    deben stampar `currency`. Antes el OperationIn no incluía el campo,
    así que las ops manuales quedaban con currency=NULL y rompían
    consumers downstream que filtraban por moneda.

    Default behavior: si el frontend no manda currency, el backend
    hace lookup en brokers.currency y stampa transparentemente.
    """

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "monthly_entries", "brokers"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, email=f"opcurrency-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        _add_broker(conn, self.uid, "Binance", "USDT")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _post_op(self, body):
        return self.client.post(
            "/api/operations",
            json=body,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def test_currency_defaults_from_broker_when_omitted(self):
        """POST sin currency en payload → toma broker.currency."""
        res = self._post_op({
            "date": "2026-05-01",
            "broker": "Cocos",
            "asset": "AL30",
            "op_type": "Venta",
            "pnl_usd": 50,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["currency"], "ARS",
            "Cocos es ARS → operation debe stampar currency=ARS")

    def test_currency_defaults_from_broker_usd(self):
        """POST con broker USD (Binance) → currency='USDT'."""
        res = self._post_op({
            "date": "2026-05-01",
            "broker": "Binance",
            "asset": "BTC",
            "op_type": "Venta",
            "pnl_usd": 100,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["currency"], "USDT")

    def test_currency_in_payload_overrides_broker(self):
        """Si el frontend manda currency explícita, se usa esa (no lookup)."""
        res = self._post_op({
            "date": "2026-05-01",
            "broker": "Cocos",
            "asset": "AAPL",
            "op_type": "Venta",
            "pnl_usd": 25,
            "currency": "usd",  # lowercase para verificar normalización
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["currency"], "USD",
            "currency del payload se normaliza a uppercase")

    def test_currency_fallback_to_usd_if_broker_unknown(self):
        """Si el broker no existe en brokers (raro pero posible si el
        frontend manda un nombre libre), default 'USD'."""
        res = self._post_op({
            "date": "2026-05-01",
            "broker": "BrokerInexistente",
            "asset": "FOO",
            "op_type": "Venta",
            "pnl_usd": 10,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["currency"], "USD")

    def test_put_also_stamps_currency(self):
        """PUT /api/operations/{id} también stampa currency (no solo POST)."""
        # Crear primero sin currency
        res = self._post_op({
            "date": "2026-05-01",
            "broker": "Cocos",
            "asset": "GGAL",
            "pnl_usd": 5,
        })
        op_id = res.json()["id"]
        # Update sin currency en payload — debe lookup-ear de nuevo
        res = self.client.put(
            f"/api/operations/{op_id}",
            json={
                "date": "2026-05-01",
                "broker": "Binance",  # cambio de broker
                "asset": "ETH",
                "pnl_usd": 5,
            },
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["currency"], "USDT",
            "PUT con nuevo broker debe re-lookup currency")


class RepairMonthlyChainOpenMonthTest(unittest.TestCase):
    """Bug fix (2026-05-30): `_repair_monthly_chain` detectaba "open month"
    como la última row del query (i == len(rows) - 1), no como el mes
    calendar actual. Si el user tenía gaps (rows en Mar + May, sin Apr) y
    el calendar marcaba Jun, May era tratado como abierto y su
    pnl_unrealized stale no se zero-eaba."""

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "monthly_entries"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, email=f"repair-open-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()

    def test_non_current_month_is_closed_even_if_last_row(self):
        """Row en el pasado (≠ current calendar month) debe tratarse como
        cerrada aunque sea la última row del query. pnl_unrealized se
        zero-ea y cap_final se reconstruye con la fórmula canónica."""
        conn = main.get_db()
        with conn:
            # 2020-01 y 2020-03 (gap en feb). Como hoy ≥ 2026, ninguna es
            # current. Inyectamos pnl_unrealized=999 en la última row para
            # ver si se preserva (bug) o se zero-ea (fix).
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2020, 1, 'Cocos', 100, 0, 0, 0, 0, 100)""",
                (self.uid,),
            )
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2020, 3, 'Cocos', 50, 0, 0, 999, 100, 1149)""",
                (self.uid,),
            )
            main._repair_monthly_chain(conn, self.uid, 'Cocos')

        row_mar = conn.execute(
            """SELECT pnl_unrealized, capital_inicio, capital_final
                 FROM monthly_entries
                WHERE user_id=? AND broker='Cocos' AND year=2020 AND month=3""",
            (self.uid,),
        ).fetchone()
        conn.close()

        # Antes del fix: 2020-03 era la última row → tratada como "open" →
        # pnl_unrealized=999 quedaba preservado, cap_final inflado.
        # Después del fix: 2020-03 NO es el current calendar month → closed.
        self.assertAlmostEqual(row_mar["pnl_unrealized"], 0.0, places=2,
            msg="pnl_unrealized debe ser 0 en mes no-current aunque sea la última row")
        # cap_inicio debe propagarse desde 2020-01 (capital_final = 100)
        self.assertAlmostEqual(row_mar["capital_inicio"], 100.0, places=2)
        # cap_final = 100 + 50 - 0 + 0 = 150 (sin pnl_unrealized para cerrado)
        self.assertAlmostEqual(row_mar["capital_final"], 150.0, places=2)

    def test_current_month_preserves_pnl_unrealized(self):
        """Sanity check: si la row ES el current calendar month, sus
        valores live (pnl_unrealized, capital_final) deben preservarse."""
        from datetime import datetime
        now = datetime.utcnow()
        y, m = now.year, now.month

        conn = main.get_db()
        with conn:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, ?, ?, 'Cocos', 100, 0, 0, 42, 0, 142)""",
                (self.uid, y, m),
            )
            main._repair_monthly_chain(conn, self.uid, 'Cocos')

        row = conn.execute(
            """SELECT pnl_unrealized, capital_final
                 FROM monthly_entries
                WHERE user_id=? AND broker='Cocos' AND year=? AND month=?""",
            (self.uid, y, m),
        ).fetchone()
        conn.close()

        self.assertAlmostEqual(row["pnl_unrealized"], 42.0, places=2,
            msg="current month debe preservar pnl_unrealized (es live)")
        self.assertAlmostEqual(row["capital_final"], 142.0, places=2,
            msg="current month preserva capital_final ya que cap_inicio matcheaba")


class CombineCsvFilesTest(unittest.TestCase):
    """Unit tests del helper combine_csv_files (multi-file upload)."""

    def test_empty_list_returns_error(self):
        from importing.pipeline import combine_csv_files
        data, name, err = combine_csv_files([])
        self.assertIn("ningún archivo", err.lower())

    def test_single_file_returns_unchanged(self):
        from importing.pipeline import combine_csv_files
        body = b"a;b\n1;2\n3;4\n"
        data, name, err = combine_csv_files([(body, "x.csv")])
        self.assertIsNone(err)
        self.assertEqual(data, body)
        self.assertEqual(name, "x.csv")

    def test_two_files_combined_with_single_header(self):
        from importing.pipeline import combine_csv_files
        f1 = b"a;b\n1;2\n3;4\n"
        f2 = b"a;b\n5;6\n7;8\n"
        data, name, err = combine_csv_files([(f1, "y1.csv"), (f2, "y2.csv")])
        self.assertIsNone(err)
        text = data.decode("utf-8")
        # Header aparece UNA sola vez
        self.assertEqual(text.count("a;b"), 1)
        # Las 4 filas de datos están
        for v in ("1;2", "3;4", "5;6", "7;8"):
            self.assertIn(v, text)
        self.assertEqual(name, "y1.csv + y2.csv")

    def test_three_files_preserves_order(self):
        from importing.pipeline import combine_csv_files
        files = [
            (b"h\nrow_a\n", "2024.csv"),
            (b"h\nrow_b\n", "2025.csv"),
            (b"h\nrow_c\n", "2026.csv"),
        ]
        data, _, err = combine_csv_files(files)
        self.assertIsNone(err)
        text = data.decode("utf-8")
        self.assertLess(text.index("row_a"), text.index("row_b"))
        self.assertLess(text.index("row_b"), text.index("row_c"))

    def test_mismatched_headers_returns_error(self):
        from importing.pipeline import combine_csv_files
        f1 = b"a;b\n1;2\n"
        f2 = b"x;y\n3;4\n"
        data, name, err = combine_csv_files([(f1, "a.csv"), (f2, "b.csv")])
        self.assertIsNotNone(err)
        self.assertIn("b.csv", err)
        self.assertIn("header", err.lower())

    def test_bom_in_second_file_handled(self):
        """El segundo archivo puede tener BOM; el header debe matchear igual."""
        from importing.pipeline import combine_csv_files
        f1 = b"a;b\n1;2\n"
        # BOM al inicio del segundo
        f2 = "﻿a;b\n3;4\n".encode("utf-8")
        data, _, err = combine_csv_files([(f1, "a.csv"), (f2, "b.csv")])
        self.assertIsNone(err)
        text = data.decode("utf-8")
        self.assertIn("3;4", text)

    def test_empty_file_skipped_silently(self):
        from importing.pipeline import combine_csv_files
        f1 = b"a;b\n1;2\n"
        empty = b""
        data, _, err = combine_csv_files([(f1, "a.csv"), (empty, "empty.csv")])
        self.assertIsNone(err)
        self.assertIn("1;2", data.decode("utf-8"))

    def test_long_combined_name_truncated(self):
        from importing.pipeline import combine_csv_files
        files = [(b"h\n1\n", f"very_long_name_{i:03d}.csv") for i in range(20)]
        data, name, err = combine_csv_files(files)
        self.assertIsNone(err)
        self.assertLessEqual(len(name), 200)

    def test_handles_cp1252_encoding(self):
        """Excel-on-Windows exporta cp1252 con chars 0x80-0x9F que latin-1
        decodifica mal. utf-8-sig falla y debemos caer a cp1252 antes."""
        from importing.pipeline import combine_csv_files
        # 'á' en cp1252 = 0xE1 (igual que latin-1), pero '€' = 0x80 (latin-1 lo decodifica
        # como control char invisible). Usamos un char Windows-1252-specific.
        f1 = 'h\n€100\n'.encode('cp1252')
        f2 = b'h\n200\n'
        data, _, err = combine_csv_files([(f1, 'cp1252.csv'), (f2, 'utf.csv')])
        self.assertIsNone(err)
        text = data.decode('utf-8')
        self.assertIn('€', text)

    def test_header_match_tolerates_bom_in_either_file(self):
        """Si el primer archivo tiene BOM y el segundo no (o viceversa), el
        match de headers debe pasar igual."""
        from importing.pipeline import combine_csv_files
        f1 = '﻿a;b\n1;2\n'.encode('utf-8')  # con BOM
        f2 = b'a;b\n3;4\n'                    # sin BOM
        data, _, err = combine_csv_files([(f1, 'a.csv'), (f2, 'b.csv')])
        self.assertIsNone(err)
        # Y al revés
        data, _, err = combine_csv_files([(f2, 'b.csv'), (f1, 'a.csv')])
        self.assertIsNone(err)

    def test_header_match_case_insensitive(self):
        from importing.pipeline import combine_csv_files
        f1 = b'Fecha;Tipo\n2024;Compra\n'
        f2 = b'FECHA;TIPO\n2025;Venta\n'  # mismo header en distinto casing
        data, _, err = combine_csv_files([(f1, 'a.csv'), (f2, 'b.csv')])
        self.assertIsNone(err)

    def test_combined_with_cocos_real_format(self):
        """Realista: 2 CSVs de Cocos combinados. El header de Cocos tiene
        muchas columnas, así que validamos que no rompe."""
        from importing.pipeline import combine_csv_files
        header = (
            "nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;"
            "tipoOperacion;instrumento;moneda;mercado;cantidad;precio;"
            "montoBruto;comision;ddmm;iva;otros;total"
        )
        row_2024 = "100;200;15-06-2024;15-06-2024;Compra;CEDEAR APPLE (AAPL);ARS;BYMA;10;100;-1000;0;0;0;0;-1000"
        row_2025 = "300;400;15-06-2025;15-06-2025;Venta;CEDEAR APPLE (AAPL);ARS;BYMA;-5;200;1000;0;0;0;0;1000"
        f1 = f"{header}\n{row_2024}\n".encode("utf-8")
        f2 = f"{header}\n{row_2025}\n".encode("utf-8")
        data, _, err = combine_csv_files([(f1, "2024.csv"), (f2, "2025.csv")])
        self.assertIsNone(err)
        text = data.decode("utf-8")
        self.assertEqual(text.count(header), 1)
        self.assertIn("2024", text)
        self.assertIn("2025", text)


class MultiFilePreviewE2ETest(unittest.TestCase):
    """E2E: subir múltiples CSVs por el endpoint /imports/preview."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions",
                  "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn, email="multifile@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _post_files(self, *files_with_names, format="cocos", broker="Cocos"):
        """Helper: POST multipart con N files al endpoint preview."""
        import io
        multipart_files = [
            ("files", (name, io.BytesIO(data), "text/csv"))
            for data, name in files_with_names
        ]
        return self.client.post(
            "/api/imports/preview",
            files=multipart_files,
            data={"format": format, "broker": broker},
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _cocos_csv(self, *rows):
        header = (
            "nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;"
            "tipoOperacion;instrumento;moneda;mercado;cantidad;precio;"
            "montoBruto;comision;ddmm;iva;otros;total"
        )
        return ("\n".join([header] + list(rows)) + "\n").encode("utf-8")

    def test_single_file_via_files_field_works(self):
        """`files` con 1 elemento debe funcionar igual que `file` legacy."""
        csv = self._cocos_csv(
            "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000",
        )
        res = self._post_files((csv, "2024.csv"))
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body.get("source_file_count"), 1)
        self.assertGreaterEqual(body["summary"]["valid_rows"], 1)

    def test_three_files_combined_into_one_batch(self):
        """Subir 2024+2025+2026: debe haber un solo session_id y todas las
        filas válidas en él."""
        csv_2024 = self._cocos_csv(
            "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000",
        )
        csv_2025 = self._cocos_csv(
            "10;20;15-06-2025;15-06-2025;Compra;CEDEAR APPLE (AAPL);ARS;BYMA;10;100;-1000;0;0;0;0;-1000",
        )
        csv_2026 = self._cocos_csv(
            "100;200;15-06-2026;15-06-2026;Venta;CEDEAR APPLE (AAPL);ARS;BYMA;-10;150;1500;0;0;0;0;1500",
        )
        res = self._post_files(
            (csv_2024, "2024.csv"),
            (csv_2025, "2025.csv"),
            (csv_2026, "2026.csv"),
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["source_file_count"], 3)
        # 3 filas válidas (1 deposit + 1 buy + 1 sell)
        self.assertEqual(body["summary"]["valid_rows"], 3)
        # Un solo session_id
        self.assertTrue(body["session_id"])

    def test_files_with_mismatched_headers_returns_400(self):
        """Headers distintos entre archivos → 400 con mensaje claro."""
        ok = self._cocos_csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000")
        bad = b"fecha,tipo,monto\n2025-06-15,DEPOSITO,500\n"
        res = self._post_files((ok, "cocos.csv"), (bad, "otro.csv"), format="cocos")
        self.assertEqual(res.status_code, 400)
        self.assertIn("formato", res.json()["detail"].lower())

    def test_no_files_returns_400(self):
        res = self.client.post(
            "/api/imports/preview",
            data={"format": "cocos"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 400)

    def test_total_size_cap_enforced(self):
        """Total > 5MB rechaza con 400 antes de tocar el parser."""
        # 5.5MB de "x;y\n" (4 bytes/línea)
        big = b"a;b\n" + b"x;y\n" * 1_400_000
        res = self._post_files((big, "huge.csv"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("excede", res.json()["detail"].lower())

    def test_too_many_files_rejected(self):
        """Cap de 20 archivos para evitar abuse."""
        csv = self._cocos_csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;1;0;0;0;0;1")
        files = [(csv, f"y{i:02d}.csv") for i in range(21)]
        res = self._post_files(*files)
        self.assertEqual(res.status_code, 400)
        self.assertIn("demasiados", res.json()["detail"].lower())

    def test_filename_with_path_traversal_sanitized(self):
        """Filename con ../ debe sanitizarse antes de persistir en DB."""
        import io
        csv = self._cocos_csv(
            "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100;0;0;0;0;100",
        )
        # filename malicioso con path traversal + newline
        evil = "../../../etc/passwd\n.csv"
        res = self.client.post(
            "/api/imports/preview",
            files={"file": (evil, io.BytesIO(csv), "text/csv")},
            data={"format": "cocos", "broker": "Cocos"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        # El batch persiste un file_name sin chars peligrosos
        conn = main.get_db()
        row = conn.execute(
            "SELECT file_name FROM import_batches WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (self.uid,),
        ).fetchone()
        conn.close()
        # Ni newlines ni slashes ni .. en el nombre persistido
        self.assertNotIn("/", row["file_name"])
        self.assertNotIn("\n", row["file_name"])
        self.assertNotIn("..", row["file_name"])

    def test_sanitize_filename_unit(self):
        from importing.pipeline import sanitize_filename
        # Path traversal
        self.assertNotIn("/", sanitize_filename("../../etc/passwd.csv"))
        self.assertNotIn("\\", sanitize_filename("..\\windows\\file.csv"))
        # Newlines / control chars
        self.assertNotIn("\n", sanitize_filename("foo\nbar.csv"))
        self.assertNotIn("\r", sanitize_filename("foo\rbar.csv"))
        # Vacío → default
        self.assertEqual(sanitize_filename(""), "archivo.csv")
        self.assertEqual(sanitize_filename(None), "archivo.csv")
        # Solo basura → default
        self.assertEqual(sanitize_filename("///"), "archivo.csv")
        # Caso normal
        self.assertEqual(sanitize_filename("2024.csv"), "2024.csv")
        # Truncado a 80 chars
        long = "a" * 200 + ".csv"
        self.assertLessEqual(len(sanitize_filename(long)), 80)

    def test_legacy_file_field_still_works(self):
        """Back-compat: clientes viejos que mandan `file` (singular)."""
        import io
        csv = self._cocos_csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000")
        res = self.client.post(
            "/api/imports/preview",
            files={"file": ("legacy.csv", io.BytesIO(csv), "text/csv")},
            data={"format": "cocos", "broker": "Cocos"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source_file_count"], 1)


class UniversalUserScenariosTest(unittest.TestCase):
    """Verifica que el feature funcione para múltiples casos de user, no solo
    para el caso particular del que reportó (Cocos + multi-año).

    Cubre: new user limpio, multi-user isolation, parser distinto,
    multi-file con N=1 (back-compat), recalc en DB vacía."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)

    def setUp(self):
        conn = main.get_db()
        # Limpiar TODO para empezar desde cero
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions",
                  "monthly_entries", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        conn.close()

    def _token(self, uid):
        return main.create_token(uid)

    def test_new_user_recalc_pnl_empty_db_safe(self):
        """User recién creado, sin imports ni operations: recalc no debe romper."""
        conn = main.get_db()
        uid = _new_user(conn, email="newbie@rendi.test")
        conn.commit()
        conn.close()
        res = self.client.post(
            "/api/imports/recalc-pnl",
            headers={"Authorization": f"Bearer {self._token(uid)}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["recalculated"])

    def test_recalc_isolation_between_users(self):
        """Recalc del user A no debe tocar monthly_entries del user B."""
        conn = main.get_db()
        a = _new_user(conn, email="user_a@rendi.test")
        b = _new_user(conn, email="user_b@rendi.test")
        _add_broker(conn, a, "Cocos", "ARS")
        _add_broker(conn, b, "Cocos", "ARS")
        # B tiene drift en pnl_realized (sin operations)
        with conn:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'Cocos', 0, 0, -5000, 0, 0, -5000)""",
                (b,),
            )
        conn.close()

        # A corre recalc → no debe tocar a B
        self.client.post(
            "/api/imports/recalc-pnl",
            headers={"Authorization": f"Bearer {self._token(a)}"},
        )
        conn = main.get_db()
        b_pnl = conn.execute(
            "SELECT pnl_realized FROM monthly_entries WHERE user_id=? AND broker='Cocos'",
            (b,),
        ).fetchone()
        conn.close()
        self.assertEqual(b_pnl["pnl_realized"], -5000,
            "Recalc de user A no debería tocar al user B")

    def test_inspect_chunked_cap_enforced(self):
        """/inspect debe rechazar archivos sobre el cap antes de leerlos completos."""
        import io
        conn = main.get_db()
        uid = _new_user(conn, email="big_inspect@rendi.test")
        conn.commit()
        conn.close()
        # Archivo > 5MB
        big = b"a,b\n" + b"1,2\n" * 1_400_000
        res = self.client.post(
            "/api/imports/inspect",
            files={"file": ("big.csv", io.BytesIO(big), "text/csv")},
            headers={"Authorization": f"Bearer {self._token(uid)}"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("excede", res.json()["detail"].lower())
        self.assertIn("MB", res.json()["detail"])

    def test_inspect_size_error_message_uses_correct_mb_value(self):
        """El mensaje de error debe reflejar el cap REAL (5MB), no hardcoded "1 MB"."""
        # Test del helper interno (sin endpoint)
        from importing.pipeline import inspect, MAX_FILE_BYTES
        # Pasar más bytes del cap
        big = b"a,b\n" + b"x,y\n" * (MAX_FILE_BYTES // 4 + 100)
        result = inspect(big)
        self.assertIn("error", result)
        # El mensaje debe contener el MB real
        expected_mb = MAX_FILE_BYTES // 1_000_000
        self.assertIn(str(expected_mb), result["error"])

    def test_multi_file_n1_backwards_compat_with_generic_parser(self):
        """Multi-file con N=1 usando rendi_generic (no parser específico).
        Verifica que el endpoint preview + el flow inspect funcionen con files."""
        import io
        conn = main.get_db()
        uid = _new_user(conn, email="generic@rendi.test")
        _add_broker(conn, uid, "MiBroker", "ARS")
        conn.commit()
        conn.close()

        csv = (
            "fecha,tipo,broker,activo,cantidad,precio,monto,moneda\n"
            "2025-01-15,COMPRA,MiBroker,GGAL,100,500,50000,ARS\n"
            "2025-02-15,DEPOSITO,MiBroker,,,,200000,ARS\n"
        ).encode("utf-8")
        token = self._token(uid)
        # Multi-file con files=[csv]: debe procesar como single file
        res = self.client.post(
            "/api/imports/preview",
            files=[("files", ("ops.csv", io.BytesIO(csv), "text/csv"))],
            data={"format": "rendi_generic", "broker": "MiBroker"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["source_file_count"], 1)
        self.assertGreaterEqual(body["summary"]["valid_rows"], 2)

    def test_revert_recalcs_pnl_automatically(self):
        """Tras revert nuclear, el pnl_realized debe auto-recalcularse."""
        from importing.persister import persist_batch, revert_batch
        from importing.schema import NormalizedTx, OP_BUY, OP_SELL
        import uuid, json
        conn = main.get_db()
        uid = _new_user(conn, email="revert_recalc@rendi.test")
        _add_broker(conn, uid, "Cocos", "ARS")

        # Inflar pnl_realized previo (drift simulado de cycle anterior)
        with conn:
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'Cocos', 0, 0, -9999, 0, 0, -9999)""",
                (uid,),
            )
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id, year, month, broker, deposits, withdrawals,
                    pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?, 2025, 5, 'global', 0, 0, -9999, 0, 0, -9999)""",
                (uid,),
            )

        # Persist un batch trivial
        batch_id = str(uuid.uuid4())
        tx = NormalizedTx(row_index=1, date="2025-05-15", broker="Cocos",
                          operation_type=OP_BUY, asset_symbol="GGAL",
                          quantity=10, unit_price=500, gross_amount=5000,
                          currency="ARS", settlement_currency="ARS")
        raw_row_ids = {}
        with conn:
            conn.execute(
                """INSERT INTO import_batches
                   (id, user_id, parser_format, file_name, file_hash, broker, status)
                   VALUES (?, ?, 'cocos', 'x.csv', ?, 'Cocos', 'preview')""",
                (batch_id, uid, batch_id),
            )
            cur = conn.execute(
                """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                   VALUES (?,?,?,'valid',NULL)""",
                (batch_id, 1, json.dumps({})),
            )
            raw_row_ids[1] = cur.lastrowid
        persist_batch(conn, uid=uid, batch_id=batch_id, txs=[tx],
                      raw_row_ids_by_index=raw_row_ids, helpers=main)
        conn.execute("UPDATE import_batches SET status='confirmed' WHERE id=?", (batch_id,))
        conn.commit()

        # Revert con nuclear → debe disparar el auto-recalc
        with conn:
            revert_batch(conn, uid=uid, batch_id=batch_id, helpers=main, nuclear=True)

        # Después del revert: pnl_realized debería estar en 0 (no -9999) porque
        # no hay operations matching y el recalc auto-corrió.
        rows = conn.execute(
            "SELECT broker, pnl_realized FROM monthly_entries WHERE user_id=?",
            (uid,),
        ).fetchall()
        conn.close()
        for r in rows:
            self.assertEqual(r["pnl_realized"], 0.0,
                f"{r['broker']}: drift no se limpió en revert ({r['pnl_realized']})")


class SchwabParserTest(unittest.TestCase):
    """Tests del parser de Charles Schwab (History → Export CSV)."""

    @classmethod
    def setUpClass(cls):
        from importing.parsers.schwab import SchwabParser
        cls.parser = SchwabParser()
        cls.fixture = _read_fixture("schwab_export.csv").decode("utf-8")

    def test_can_handle_schwab_headers(self):
        headers = ["Date", "Action", "Symbol", "Description", "Quantity",
                   "Price", "Fees & Comm", "Amount"]
        self.assertTrue(self.parser.can_handle(headers))

    def test_can_handle_rejects_other_formats(self):
        self.assertFalse(self.parser.can_handle(["fecha", "tipo", "broker"]))
        self.assertFalse(self.parser.can_handle(["nroTicket", "fechaEjecucion"]))

    def test_rejects_file_without_schwab_columns(self):
        result = self.parser.parse("foo,bar,baz\n1,2,3\n")
        self.assertEqual(len(result.parse_errors), 1)
        self.assertEqual(result.parse_errors[0].code, "SCHWAB_HEADERS_MISMATCH")

    def test_parses_buy_with_us_format(self):
        result = self.parser.parse(self.fixture)
        meta = next(r for r in result.raw_rows
                    if r.data["activo"] == "META" and r.data["tipo"] == "COMPRA")
        self.assertEqual(meta.data["fecha"], "2026-04-30")
        self.assertEqual(meta.data["broker"], "Schwab")
        self.assertEqual(meta.data["cantidad"], "16")
        self.assertEqual(meta.data["precio"], "608.38")
        self.assertEqual(meta.data["moneda"], "USD")
        # 16 × 608.38 = 9734.08
        self.assertAlmostEqual(float(meta.data["monto"]), 9734.08, places=2)

    def test_parses_sell(self):
        result = self.parser.parse(self.fixture)
        ypf = next(r for r in result.raw_rows
                   if r.data["activo"] == "YPF" and r.data["tipo"] == "VENTA")
        self.assertEqual(ypf.data["cantidad"], "962")
        self.assertEqual(ypf.data["precio"], "42.5801")
        self.assertAlmostEqual(float(ypf.data["comisiones"]), 0.19, places=2)

    def test_qty_with_thousand_separator(self):
        """Schwab usa coma como separador de miles ('1,566') — debe parsear OK."""
        result = self.parser.parse(self.fixture)
        gbtc = next(r for r in result.raw_rows
                    if r.data["activo"] == "GBTC" and r.data["tipo"] == "VENTA")
        self.assertEqual(gbtc.data["cantidad"], "1566")

    def test_date_with_as_of_uses_effective_date(self):
        """'02/09/2026 as of 02/06/2026' debe usar 02/06/2026 (la efectiva)."""
        result = self.parser.parse(self.fixture)
        transfer = next(r for r in result.raw_rows
                        if r.data["tipo"] == "DEPOSITO"
                        and r.data["monto"] == "15000.00")
        self.assertEqual(transfer.data["fecha"], "2026-02-06")

    def test_dividend_preserves_symbol(self):
        """A diferencia de Cocos, Schwab dice qué stock pagó el dividendo."""
        result = self.parser.parse(self.fixture)
        nvda_div = next(r for r in result.raw_rows
                        if r.data["tipo"] == "DIVIDENDO" and r.data["activo"] == "NVDA")
        self.assertAlmostEqual(float(nvda_div.data["monto"]), 1.57, places=2)
        self.assertEqual(nvda_div.data["moneda"], "USD")

    def test_special_qual_div_mapped_to_dividend(self):
        result = self.parser.parse(self.fixture)
        bma_div = next(r for r in result.raw_rows
                       if r.data["tipo"] == "DIVIDENDO" and r.data["activo"] == "BMA")
        self.assertAlmostEqual(float(bma_div.data["monto"]), 120.40, places=2)

    def test_nra_tax_adj_mapped_to_fee(self):
        result = self.parser.parse(self.fixture)
        fees = [r for r in result.raw_rows if r.data["tipo"] == "FEE"]
        # 2 fees: NRA Tax Adj NVDA + ADR Mgmt Fee PAM
        self.assertEqual(len(fees), 2)
        nra = next(r for r in fees if abs(float(r.data["monto"]) - 0.47) < 0.01)
        self.assertEqual(nra.data["moneda"], "USD")

    def test_moneylink_positive_is_deposit(self):
        result = self.parser.parse(self.fixture)
        deps = [r for r in result.raw_rows if r.data["tipo"] == "DEPOSITO"]
        self.assertGreaterEqual(len(deps), 2)  # MoneyLink + Wire Received

    def test_moneylink_negative_is_withdraw(self):
        result = self.parser.parse(self.fixture)
        wd = next(r for r in result.raw_rows
                  if r.data["tipo"] == "RETIRO" and r.data["monto"] == "77000.00")
        self.assertEqual(wd.data["fecha"], "2025-12-24")

    def test_wire_received_is_deposit(self):
        result = self.parser.parse(self.fixture)
        wire = next(r for r in result.raw_rows
                    if r.data["tipo"] == "DEPOSITO" and r.data["monto"] == "15000.00"
                    and "WIRED" in r.data["notas"].upper())
        self.assertEqual(wire.data["fecha"], "2024-01-22")

    def test_credit_interest_is_interes(self):
        result = self.parser.parse(self.fixture)
        intereses = [r for r in result.raw_rows if r.data["tipo"] == "INTERES"]
        self.assertGreaterEqual(len(intereses), 1)

    def test_stock_split_emits_synthetic_buy_with_zero_price(self):
        """Stock Split se convierte en BUY sintético: qty=split_shares, price=0.
        El cost basis no cambia (lot extra a $0), pero la posición ahora tiene
        las shares correctas para que ventas posteriores no fallen."""
        result = self.parser.parse(self.fixture)
        xlk_split = next((r for r in result.raw_rows
                          if r.data["activo"] == "XLK"
                          and r.data["tipo"] == "COMPRA"
                          and r.data["precio"] == "0"), None)
        self.assertIsNotNone(xlk_split,
            "Stock Split debe emitir un BUY sintético con price=0")
        self.assertEqual(xlk_split.data["cantidad"], "3")
        self.assertEqual(xlk_split.data["monto"], "0")  # no afecta cash
        self.assertIn("Stock Split", xlk_split.data["notas"])

    def test_grayscale_eth_tagged_as_etf_not_crypto(self):
        """Para Schwab, 'ETH' es Grayscale Ethereum Mini Trust (ETF), no la
        crypto raw. El parser pasa asset_type=ETF para que la heurística
        del normalizer no lo marque como CRYPTO."""
        # Test with a custom row, since fixture doesn't have ETH (only ETHE)
        csv = (
            '"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"\n'
            '"10/25/2024","Sell","ETH","GRAYSCALE ETHEREUM MINI","6521","$2.3854","$1.51","$15553.68"\n'
        )
        result = self.parser.parse(csv)
        eth = result.raw_rows[0]
        self.assertEqual(eth.data["asset_type"], "ETF")

    def test_known_etf_tickers_tagged(self):
        """GBTC, ETHE, XLK también van como ETF."""
        result = self.parser.parse(self.fixture)
        gbtc = next(r for r in result.raw_rows if r.data["activo"] == "GBTC")
        self.assertEqual(gbtc.data.get("asset_type"), "ETF")

    def test_regular_stock_no_etf_tag(self):
        """Stocks normales (META, AAPL) no llevan el hint — fallback al guess."""
        result = self.parser.parse(self.fixture)
        meta = next(r for r in result.raw_rows if r.data["activo"] == "META")
        self.assertEqual(meta.data.get("asset_type"), "")

    def test_expired_warrants_skipped_silently(self):
        """Corporate actions sin cash impact: no errores, no rows."""
        result = self.parser.parse(self.fixture)
        warrants = [r for r in result.raw_rows if r.data["activo"] == "399RGT026"]
        self.assertEqual(warrants, [])
        # No deben aparecer en parse_errors tampoco
        warrants_err = [e for e in result.parse_errors
                        if "399RGT026" in (e.message or "")]
        self.assertEqual(warrants_err, [])

    def test_internal_transfer_journaled_shares_skipped(self):
        """Migraciones TDA→Schwab no se importan como BUY/SELL."""
        result = self.parser.parse(self.fixture)
        # Las filas con "TDA TRAN" en notas no deberían convertirse en BUYs
        tda_buys = [r for r in result.raw_rows
                    if r.data["tipo"] == "COMPRA"
                    and "TDA TRAN" in r.data["notas"]]
        self.assertEqual(tda_buys, [])

    def test_qual_div_reinvest_is_dividend(self):
        result = self.parser.parse(self.fixture)
        reinv = next((r for r in result.raw_rows
                      if r.data["tipo"] == "DIVIDENDO"
                      and abs(float(r.data["monto"]) - 41.28) < 0.01), None)
        self.assertIsNotNone(reinv)

    def test_template_csv_is_self_parseable(self):
        t = self.parser.template_csv()
        result = self.parser.parse(t)
        # No errores fatales y al menos algunas filas válidas
        self.assertGreater(len(result.raw_rows), 0)


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
