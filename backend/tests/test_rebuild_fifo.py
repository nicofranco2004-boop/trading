"""Tests del rebuild global de FIFO post-import (importing/rebuild.py).

El bug que cubre: importar el historial en tandas y FUERA de orden cronológico
(p.ej. subir 2025 con ventas, después 2024 con las compras) rompe el cost basis
porque el persister es incremental. El rebuild replaya todo el historial
importado de cada (broker, activo) en orden de fecha y reconstruye lotes +
ventas. Equivale a "importar todo junto".

Corre con: cd backend && python3 -m pytest tests/test_rebuild_fifo.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# DB temporal — setear ANTES de importar main
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
import main


HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows: str) -> bytes:
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    h._recalc_pnl_realized_from_ops = main._recalc_pnl_realized_from_ops
    return h


class _Base(unittest.TestCase):
    BROKER = "IBKR"
    BROKER_CCY = "USDT"   # → USD directo

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("rebuild_test@rendi.test", "x"),
        )
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, self.BROKER_CCY),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _set_tc_blue(self, v: float):
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", str(v)),
        )
        self.conn.commit()

    def _import(self, csv_bytes: bytes, *, rebuild: bool) -> str:
        """Importa un CSV (preview → confirm). Si rebuild=True, corre el rebuild
        + recalc igual que el endpoint /imports/confirm."""
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic",
            )
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            if rebuild:
                tc = ps._read_tc_blue(self.conn, uid=self.uid)
                rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
                main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    # ── inspección ──────────────────────────────────────────────────────────
    def _open_qty(self, asset: str) -> float:
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset),
        ).fetchone()
        return float(r["q"] or 0)

    def _ventas(self, asset: str):
        return self.conn.execute(
            "SELECT pnl_usd, quantity, exit_price, entry_price FROM operations "
            "WHERE user_id=? AND asset=? AND op_type='Venta' ORDER BY id",
            (self.uid, asset),
        ).fetchall()

    def _global_pnl(self) -> float:
        r = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,),
        ).fetchone()
        return float(r["p"] or 0)

    def _broker_cash(self, broker=None) -> float:
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) c FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker or self.BROKER),
        ).fetchone()
        return float(r["c"] or 0)


class OutOfOrderUSD(_Base):
    SELL_2025 = _csv("2025-06-20,VENTA,IBKR,AAPL,10,200,2000,,,0,USD,")
    BUY_2024 = _csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,")

    def test_corrupt_then_heal(self):
        # 1) Subir 2025 (venta) y 2024 (compra) FUERA de orden, SIN rebuild.
        self._import(self.SELL_2025, rebuild=False)
        sid2 = self._import(self.BUY_2024, rebuild=False)

        # Estado corrupto: la compra quedó como lote ABIERTO fantasma (10 AAPL)
        # y la venta marcó P&L ~0 (lote semilla al precio de venta).
        self.assertAlmostEqual(self._open_qty("AAPL"), 10.0, places=6)
        ventas = self._ventas("AAPL")
        self.assertEqual(len(ventas), 1)
        self.assertAlmostEqual(ventas[0]["pnl_usd"], 0.0, places=2)
        cash_before = self._broker_cash()

        # 2) Rebuild (como lo haría el confirm).
        with self.conn:
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            res = rb.rebuild_fifo_after_import(self.conn, self.uid, sid2, tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)

        # Sano: 0 AAPL en tenencia (se vendió todo), 1 venta con P&L +500.
        self.assertAlmostEqual(self._open_qty("AAPL"), 0.0, places=6)
        ventas = self._ventas("AAPL")
        self.assertEqual(len(ventas), 1)
        self.assertAlmostEqual(ventas[0]["pnl_usd"], 500.0, places=2)   # 10*(200-150)
        self.assertAlmostEqual(ventas[0]["entry_price"], 150.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 500.0, places=2)
        self.assertEqual(len(res["rebuilt"]), 1)

        # Cash NO cambió con el rebuild (es order-independent).
        self.assertAlmostEqual(self._broker_cash(), cash_before, places=2)
        # Neto de cash = +2000 (venta) -1500 (compra) = +500
        self.assertAlmostEqual(self._broker_cash(), 500.0, places=2)

    def test_in_order_is_correct_and_rebuild_idempotent(self):
        # En orden correcto, con rebuild en cada import → mismo resultado sano.
        self._import(self.BUY_2024, rebuild=True)
        sid2 = self._import(self.SELL_2025, rebuild=True)
        self.assertAlmostEqual(self._open_qty("AAPL"), 0.0, places=6)
        self.assertAlmostEqual(self._global_pnl(), 500.0, places=2)

        # Rebuild de nuevo = idempotente (no duplica ventas ni cambia P&L).
        with self.conn:
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid2, tc_blue=1415.0)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        self.assertEqual(len(self._ventas("AAPL")), 1)
        self.assertAlmostEqual(self._global_pnl(), 500.0, places=2)


class RegressionInOrderVsRebuilt(_Base):
    """El estado final tras rebuild (out-of-order) debe ser IDÉNTICO al de
    importar en orden — prueba que el motor de replay no diverge del persister."""

    # Historial con 2 compras + 2 ventas parciales, cruzado entre años.
    BUY_A = _csv("2024-02-01,COMPRA,IBKR,MSFT,10,100,1000,,,0,USD,")
    BUY_B = _csv("2024-09-01,COMPRA,IBKR,MSFT,10,120,1200,,,0,USD,")
    SELL_1 = _csv("2025-01-15,VENTA,IBKR,MSFT,8,150,1200,,,0,USD,")
    SELL_2 = _csv("2025-08-20,VENTA,IBKR,MSFT,7,180,1260,,,0,USD,")

    def _state(self):
        pos = self.conn.execute(
            "SELECT asset, ROUND(quantity,4) q, ROUND(invested,4) inv, entry_date "
            "FROM positions WHERE user_id=? AND is_cash=0 ORDER BY entry_date, q",
            (self.uid,),
        ).fetchall()
        ops = self.conn.execute(
            "SELECT asset, ROUND(pnl_usd,2) p, ROUND(quantity,4) q, ROUND(exit_price,4) ex "
            "FROM operations WHERE user_id=? AND op_type='Venta' ORDER BY date, q, ex",
            (self.uid,),
        ).fetchall()
        return ([tuple(r) for r in pos], [tuple(r) for r in ops])

    def test_identical_state(self):
        # Camino A: en orden.
        self._import(self.BUY_A, rebuild=True)
        self._import(self.BUY_B, rebuild=True)
        self._import(self.SELL_1, rebuild=True)
        self._import(self.SELL_2, rebuild=True)
        in_order = self._state()
        gpnl_in = self._global_pnl()

        # Reset y Camino B: TODO al revés (ventas primero, compras después).
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

        self._import(self.SELL_2, rebuild=True)
        self._import(self.SELL_1, rebuild=True)
        self._import(self.BUY_B, rebuild=True)
        self._import(self.BUY_A, rebuild=True)   # último import dispara el rebuild final
        out_of_order = self._state()
        gpnl_out = self._global_pnl()

        self.assertEqual(in_order[0], out_of_order[0], "positions divergen")
        self.assertEqual(in_order[1], out_of_order[1], "operations divergen")
        self.assertAlmostEqual(gpnl_in, gpnl_out, places=2)
        # Sanity del P&L total: 8*(150-100)+ (2*(180-120)+5*(180-... )) calculado por FIFO
        # FIFO: SELL1 8@150 consume 8 de lote A(100) → 8*50=400
        #       SELL2 7@180 consume 2 de A(100)=2*80=160 + 5 de B(120)=5*60=300 → 460
        # total = 400+460 = 860
        self.assertAlmostEqual(gpnl_in, 860.0, places=2)
        # Tenencia final: lote B con 5 restantes
        self.assertAlmostEqual(self._open_qty("MSFT"), 5.0, places=6)


class ManualOpSafeguard(_Base):
    SELL_2025 = _csv("2025-06-20,VENTA,IBKR,AAPL,10,200,2000,,,0,USD,")
    BUY_2024 = _csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,")

    def test_skips_asset_with_manual_position(self):
        self._import(self.SELL_2025, rebuild=False)
        sid2 = self._import(self.BUY_2024, rebuild=False)

        # Posición MANUAL (no vinculada a ningún import) del mismo activo.
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price,
                   quantity, invested, entry_date, currency)
               VALUES (?,?,?,0,?,?,?,?,?)""",
            (self.uid, self.BROKER, "AAPL", 140.0, 5, 700.0, "2023-01-01", "USD"),
        )
        self.conn.commit()
        qty_before = self._open_qty("AAPL")  # 10 (import) + 5 (manual) = 15

        with self.conn:
            res = rb.rebuild_fifo_after_import(self.conn, self.uid, sid2, tc_blue=1415.0)

        # El activo se saltea: NADA se tocó (ni la manual ni la import-fantasma).
        self.assertIn({"broker": self.BROKER, "asset": "AAPL"}, res["skipped_manual"])
        self.assertEqual(len(res["rebuilt"]), 0)
        self.assertAlmostEqual(self._open_qty("AAPL"), qty_before, places=6)
        # La posición manual sigue intacta.
        manual = self.conn.execute(
            "SELECT 1 FROM positions WHERE user_id=? AND asset='AAPL' AND ROUND(buy_price,2)=140.0",
            (self.uid,),
        ).fetchone()
        self.assertIsNotNone(manual)


class ArsCrossYear(_Base):
    BROKER = "Cocos"
    BROKER_CCY = "ARS"

    SELL_2025 = _csv("2025-06-20,VENTA,Cocos,GGAL,10,1500,15000,,,0,ARS,")
    BUY_2024 = _csv("2024-03-15,COMPRA,Cocos,GGAL,10,1000,10000,,,0,ARS,")

    def test_ars_pnl_via_tc_blue(self):
        self._set_tc_blue(1000.0)   # 1 USD = 1000 ARS
        self._import(self.SELL_2025, rebuild=False)
        sid2 = self._import(self.BUY_2024, rebuild=False)

        with self.conn:
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid2, tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)

        # pnl ARS = 15000 - 10000 = 5000; pnl USD = 5000 / 1000 = 5.0
        self.assertAlmostEqual(self._open_qty("GGAL"), 0.0, places=6)
        ventas = self._ventas("GGAL")
        self.assertEqual(len(ventas), 1)
        self.assertAlmostEqual(ventas[0]["pnl_usd"], 5.0, places=2)


class RevertIntegrity(_Base):
    SELL_2025 = _csv("2025-06-20,VENTA,IBKR,AAPL,10,200,2000,,,0,USD,")
    BUY_2024 = _csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,")

    def test_safe_revert_of_consumed_buy_is_blocked(self):
        """Tras el rebuild, la compra de 2024 quedó totalmente consumida por la
        venta. El revert SEGURO del batch de compra debe BLOQUEARSE (el tombstone
        preserva la señal 'ya se vendió'), en vez de revertir y devolver cash."""
        self._import(self.SELL_2025, rebuild=False)
        sid_buy = self._import(self.BUY_2024, rebuild=False)
        with self.conn:
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid_buy, tc_blue=1415.0)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)

        with self.assertRaises(ps.PersistError):
            with self.conn:
                ps.revert_batch(self.conn, uid=self.uid, batch_id=sid_buy,
                                helpers=_helpers())


if __name__ == "__main__":
    unittest.main()
