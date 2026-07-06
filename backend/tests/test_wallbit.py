"""E2E Wallbit: trades de la API → posiciones + P&L, con el pipeline REAL
(store_preview_txs → persist_batch → rebuild FIFO), sobre una DB temporal.

Caso sintético AUTO-CONSISTENTE (conocemos la verdad):
  BUY 10 AAPL a 190 (gastó 1900)   → lote1
  BUY 10 AAPL a 210 (gastó 2100)   → lote2
  SELL 12 AAPL a 220 (recibió 2640) → FIFO: 10@190 + 2@210
    proceeds = 2640 ; costo vendido = 1900 + 420 = 2320 ; P&L realizado = +320
    tenencia restante = 8 AAPL, invested = 8×210 = 1680

Valida:
  • el mapeo TRADE→NormalizedTx da costo/proceeds EXACTOS (gross = USD real);
  • replay por el pipeline → posición 8 AAPL / invested 1680, y SELL con P&L +320;
  • el sync es IDEMPOTENTE: re-sincronizar los MISMOS trades no duplica nada;
  • el cifrado de la API key hace round-trip.

Corre con: cd backend && python3 -m pytest tests/test_wallbit.py
"""
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
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-wallbit-" + "x" * 20)

import wallbit as W
import main


def _trade(direction, symbol, shares, usd, price, date, uuid):
    """Arma un TRADE de Wallbit crudo. BUY: source=USD/dest=activo; SELL al revés."""
    if direction == "BUY":
        src_cur, dst_cur, src_amt, dst_amt = "USD", symbol, usd, shares
    else:
        src_cur, dst_cur, src_amt, dst_amt = symbol, "USD", shares, usd
    return {
        "uuid": uuid, "type": "TRADE", "status": "COMPLETED",
        "source_currency": {"code": src_cur}, "dest_currency": {"code": dst_cur},
        "trade_info": {"direction": direction, "symbol": symbol, "share_price": price},
        "source_amount": src_amt, "dest_amount": dst_amt,
        "created_at": date + "T12:00:00.000000Z", "comment": None,
    }


TRADES = [
    _trade("BUY",  "AAPL", 10, 1900.0, 190.0, "2026-01-10", "u1"),
    _trade("BUY",  "AAPL", 10, 2100.0, 210.0, "2026-02-15", "u2"),
    _trade("SELL", "AAPL", 12, 2640.0, 220.0, "2026-03-20", "u3"),
    # ruido de neobanco: NO deben entrar
    {"uuid": "n1", "type": "CARD_SPENT", "status": "COMPLETED", "source_amount": 10, "dest_amount": 10,
     "source_currency": {"code": "USD"}, "dest_currency": {"code": "USD"}, "created_at": "2026-03-01T00:00:00Z"},
    {"uuid": "n2", "type": "TRADE", "status": "PENDING", "source_currency": {"code": "USD"},
     "dest_currency": {"code": "AAPL"}, "trade_info": {"direction": "BUY", "symbol": "AAPL", "share_price": 200},
     "source_amount": 200, "dest_amount": 1, "created_at": "2026-03-02T00:00:00Z"},
]


class WallbitMappingTest(unittest.TestCase):
    def test_mapping_amounts_exact(self):
        txs = W.trades_to_normalized(TRADES, "Wallbit")
        # solo los 3 TRADE COMPLETED (el CARD y el PENDING se saltean)
        self.assertEqual(len(txs), 3)
        buy1, buy2, sell = txs
        self.assertEqual((buy1.operation_type, buy1.asset_symbol, buy1.currency), ("BUY", "AAPL", "USD"))
        # costo/proceeds exactos: unit×qty == gross (el fee queda embebido en el precio)
        for t in txs:
            self.assertAlmostEqual(t.unit_price * t.quantity, t.gross_amount, places=6)
        self.assertAlmostEqual(sell.gross_amount, 2640.0, places=6)
        self.assertEqual(sell.operation_type, "SELL")

    def test_crypto_roundtrip(self):
        enc = main._wallbit_encrypt("wb_read_only_ABC123")
        self.assertNotEqual(enc, "wb_read_only_ABC123")
        self.assertEqual(main._wallbit_decrypt(enc), "wb_read_only_ABC123")


class WallbitSyncE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = main.get_db()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("wallbit-e2e@test.local", "x"))
        cls.uid = cur.lastrowid
        conn.commit()
        conn.close()
        # monkeypatch del fetch para no pegarle a la API real (se restaura en tearDown)
        cls._orig_fetch = W.fetch_trades
        W.fetch_trades = lambda api_key, from_date=None: list(TRADES)

    @classmethod
    def tearDownClass(cls):
        W.fetch_trades = cls._orig_fetch   # no dejar el monkeypatch pegado para otros tests

    def _positions(self, conn):
        return {r["asset"]: r for r in conn.execute(
            "SELECT asset, quantity, invested, is_cash FROM positions "
            "WHERE user_id=? AND broker='Wallbit' AND is_cash=0", (self.uid,)).fetchall()}

    def test_1_initial_sync_builds_positions_and_pnl(self):
        conn = main.get_db()
        try:
            res = main._wallbit_do_sync(conn, self.uid, "fake_key", full=True)
            self.assertEqual(res["new_trades"], 3)
            pos = self._positions(conn)
            self.assertIn("AAPL", pos)
            self.assertAlmostEqual(pos["AAPL"]["quantity"], 8.0, places=6)      # 10+10-12
            self.assertAlmostEqual(pos["AAPL"]["invested"], 1680.0, places=2)   # 8×210
            # SELL con P&L realizado +320
            ops = conn.execute(
                "SELECT op_type, pnl_usd FROM operations WHERE user_id=? AND asset='AAPL'",
                (self.uid,)).fetchall()
            sells = [o for o in ops if (o["op_type"] or "").upper() in ("SELL", "VENTA")]
            self.assertTrue(sells, "debería haber una operación de venta")
            self.assertAlmostEqual(sum(o["pnl_usd"] or 0 for o in sells), 320.0, places=1)
        finally:
            conn.close()

    def test_2_resync_is_idempotent(self):
        conn = main.get_db()
        try:
            res = main._wallbit_do_sync(conn, self.uid, "fake_key", full=True)
            self.assertEqual(res["new_trades"], 0, "re-sync no debe agregar trades")
            pos = self._positions(conn)
            self.assertAlmostEqual(pos["AAPL"]["quantity"], 8.0, places=6)
            self.assertAlmostEqual(pos["AAPL"]["invested"], 1680.0, places=2)
        finally:
            conn.close()


class WallbitAuditFixesTest(unittest.TestCase):
    """Regresiones de los hallazgos del audit adversarial de la Fase 1."""

    def test_broker_collision_non_usd_rejected(self):
        # Fix MEDIUM: si el user ya tiene un broker 'Wallbit' NO-USD, abortar (no
        # meter trades USD en un broker ARS → misvaluación).
        conn = main.get_db()
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                ("wb-collide@test.local", "x"))
            uid2 = cur.lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'Wallbit', 'ARS')", (uid2,))
            conn.commit()
            with self.assertRaises(W.WallbitError):
                main._wallbit_ensure_broker(conn, uid2)
        finally:
            conn.close()

    def test_pages_nonnumeric_no_crash(self):
        # Fix LOW: pages no-numérico no debe crashear el sync (cae a 1 página).
        orig = W._get
        W._get = lambda path, key, params=None: {"data": {"data": [
            {"type": "TRADE", "status": "COMPLETED", "uuid": "z",
             "trade_info": {"direction": "BUY", "symbol": "AAPL", "share_price": 1},
             "source_currency": {"code": "USD"}, "dest_currency": {"code": "AAPL"},
             "source_amount": 1, "dest_amount": 1, "created_at": "2026-01-01T00:00:00Z"}],
            "pages": "invalid"}}
        try:
            self.assertEqual(len(W.fetch_trades("k")), 1)
        finally:
            W._get = orig

    def test_pages_over_max_raises(self):
        # Fix LOW: más páginas que el tope → error claro en vez de truncar en silencio.
        orig = W._get
        W._get = lambda path, key, params=None: {"data": {"data": [{"x": 1}], "pages": W._MAX_PAGES + 5}}
        try:
            with self.assertRaises(W.WallbitError):
                W.fetch_trades("k")
        finally:
            W._get = orig

    def test_sync_lock_exists_per_user(self):
        # Fix HIGH: existe el lock por-usuario que serializa la sección crítica.
        import threading
        self.assertIsInstance(main._wallbit_sync_locks[999], type(threading.Lock()))


if __name__ == "__main__":
    unittest.main()
