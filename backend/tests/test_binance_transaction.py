"""BinanceTransactionHistoryParser — el export completo (Spot + Futures + Funding).

Lo crítico: el saldo de CADA coin = Σ Change del archivo (el parser no inventa ni
pierde tenencia). El bug que motivó esto: operaciones que el parser tragaba en
silencio (Crypto Box / regalos, Small Assets Exchange BNB / polvo, Binance Convert,
retiros de cripto, fees en el propio coin) dejaban saldos torcidos — BONK regalado
desaparecía, HBAR se inflaba por retiros no descontados, y quedaban fantasmas de
polvo. Además: un retiro de cripto NO es una venta → cierra el lote a COSTO (P&L 0),
no a pérdida (flag `transfer_out`, espejado en persister y rebuild)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from importing.parsers.binance_transaction import BinanceTransactionHistoryParser  # noqa: E402
from importing.parsers.registry import autodetect                                  # noqa: E402
from importing import pipeline as pl   # noqa: E402
from importing import persister as ps  # noqa: E402
from importing import rebuild as rb    # noqa: E402
import main                            # noqa: E402

HDR = "User_ID,Time,Account,Operation,Coin,Change,Remark"

# Cubre las operaciones que antes se perdían + las que ya funcionaban.
ROWS = [
    "1,25-01-01 10:00:00,Spot,Deposit,USDT,1000,",            # +1000 USDT (cash)
    "1,25-01-02 10:00:00,Spot,Transaction Spend,USDT,-500,",  # compra HBAR: -500 USDT
    "1,25-01-02 10:00:00,Spot,Transaction Buy,HBAR,5000,",    #              +5000 HBAR
    "1,25-01-02 10:00:00,Spot,Transaction Fee,HBAR,-5,",      # fee en HBAR: -5 (antes no se descontaba)
    "1,25-01-03 10:00:00,Spot,Crypto Box,BONK,10000,",        # regalo: +10000 BONK (antes desaparecía)
    "1,25-01-04 10:00:00,Spot,Withdraw,HBAR,-1000,",          # retiro a wallet: -1000 HBAR (antes no bajaba)
    "1,25-01-05 10:00:00,Funding,Small Assets Exchange BNB,HBAR,-50,",  # polvo→BNB
    "1,25-01-05 10:00:00,Funding,Small Assets Exchange BNB,BNB,0.01,",
    "1,25-01-06 10:00:00,Spot,Transfer Between Spot and Funding,USDT,-100,",  # interno → se ignora
    "1,25-01-06 10:00:00,Funding,Transfer Between Spot and Funding,USDT,100,",
]

# Σ Change a mano por coin (la verdad):
#   USDT: +1000 -500 (-100+100 interno) = 500 (cash)
#   HBAR: +5000 -5 -1000 -50 = 3945
#   BONK: 10000 ; BNB: 0.01
TRUTH = {"HBAR": 3945.0, "BONK": 10000.0, "BNB": 0.01}
STABLE = {"USDT", "USDC", "USD"}


def _csv(rows=ROWS):
    return HDR + "\n" + "\n".join(rows) + "\n"


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


class BinanceParserUnitTest(unittest.TestCase):
    def setUp(self):
        self.res = BinanceTransactionHistoryParser().parse(_csv())

    def test_no_parse_errors(self):
        self.assertEqual(self.res.parse_errors, [])

    def test_detection(self):
        self.assertIsNotNone(autodetect(HDR.split(",")))

    def test_coin_balance_reconciles(self):
        """Saldo neto de cada coin cripto = Σ Change (no se traga ni infla nada)."""
        net = {}
        for rr in self.res.raw_rows:
            d = rr.data
            a = d.get("activo")
            if not a:
                continue
            q = float(d.get("cantidad") or 0)
            net[a] = net.get(a, 0.0) + (q if d["tipo"] == "COMPRA" else -q if d["tipo"] == "VENTA" else 0)
        for coin, expected in TRUTH.items():
            self.assertAlmostEqual(net.get(coin, 0.0), expected, places=6,
                                   msg=f"{coin}: {net.get(coin)} != {expected}")

    def test_crypto_box_credita_el_regalo(self):
        compras = [d for d in (rr.data for rr in self.res.raw_rows)
                   if d["tipo"] == "COMPRA" and d.get("activo") == "BONK"]
        self.assertTrue(compras and float(compras[0]["cantidad"]) == 10000.0)

    def test_retiro_de_cripto_es_transfer_out(self):
        # El retiro de HBAR sale como VENTA marcada _transfer_out (cierra a costo).
        ventas = [rr.data for rr in self.res.raw_rows
                  if rr.data["tipo"] == "VENTA" and rr.data.get("activo") == "HBAR"]
        self.assertTrue(ventas)
        self.assertTrue(all(d.get("_transfer_out") for d in ventas))

    def test_stablecoin_es_cash_no_tenencia(self):
        # USDT depósito → DEPOSITO (sin activo); nunca una posición de coin.
        self.assertFalse(any(rr.data.get("activo") == "USDT" for rr in self.res.raw_rows))
        self.assertTrue(any(rr.data["tipo"] == "DEPOSITO" for rr in self.res.raw_rows))

    def test_transferencia_interna_se_ignora(self):
        # Las dos patas "Transfer Between Spot and Funding" netean → no aparecen.
        for rr in self.res.raw_rows:
            self.assertNotIn("Transfer Between", rr.data.get("notas", ""))


class BinanceTransferOutPipelineTest(unittest.TestCase):
    """End-to-end: un retiro de cripto baja la tenencia SIN bookear pérdida (P&L 0).
    Guarda el flag `transfer_out` a través de persister + rebuild."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("bnc@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "Binance", "USDT"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, rows):
        with self.conn:
            payload = pl.run_preview(self.conn, uid=self.uid, file_bytes=_csv(rows).encode(),
                                     file_name="b.csv", broker_hint="Binance",
                                     parser_format="binance_transaction_history")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid,
                                         tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    def test_withdraw_reduce_tenencia_y_no_bookea_perdida(self):
        rows = [
            "1,25-01-01 10:00:00,Spot,Deposit,USDT,1000,",
            "1,25-01-02 10:00:00,Spot,Transaction Spend,USDT,-500,",
            "1,25-01-02 10:00:00,Spot,Transaction Buy,HBAR,5000,",   # compra 5000 HBAR a costo real
            "1,25-01-04 10:00:00,Spot,Withdraw,HBAR,-1000,",          # retira 1000 a la wallet
        ]
        self._import(rows)
        qty = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset='HBAR' AND is_cash=0",
            (self.uid,)).fetchone()["q"]
        self.assertAlmostEqual(float(qty), 4000.0, places=4)   # 5000 - 1000 retirado
        # El retiro NO debe figurar como pérdida realizada (cierra a costo, P&L 0).
        pnl = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) s FROM operations WHERE user_id=? AND asset='HBAR' AND op_type='Venta'",
            (self.uid,)).fetchone()["s"]
        self.assertAlmostEqual(float(pnl), 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
