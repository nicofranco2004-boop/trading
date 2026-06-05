"""Casos borde adversariales del rebuild FIFO (complementa test_rebuild_fifo.py).

Estrategia principal: para cualquier feature (comisiones, mismo-día, etc.), el
test más fuerte es comparar "importar EN ORDEN" (ground truth del persister) vs
"importar FUERA de orden + rebuild" → deben dar estado IDÉNTICO. Si difieren, el
motor de replay divergió del persister.

Corre con: cd backend && python3 -m pytest tests/test_rebuild_fifo_edge.py
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


class _H(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self._wipe()
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("edge@rendi.test", "x"),
        )
        self.uid = cur.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _wipe(self):
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()

    def _broker(self, name, ccy="USDT"):
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, name, ccy),
        )
        self.conn.commit()

    def _imp(self, csv_bytes, broker, *, rebuild):
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=broker, parser_format="rendi_generic",
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

    def _state(self):
        pos = self.conn.execute(
            "SELECT broker, asset, ROUND(quantity,4) q, ROUND(invested,4) inv, "
            "ROUND(COALESCE(commissions,0),4) c, entry_date FROM positions "
            "WHERE user_id=? AND is_cash=0 ORDER BY broker, asset, entry_date, q",
            (self.uid,),
        ).fetchall()
        ops = self.conn.execute(
            "SELECT broker, asset, op_type, ROUND(pnl_usd,2) p, ROUND(quantity,4) q, "
            "ROUND(COALESCE(commissions,0),4) c FROM operations "
            "WHERE user_id=? ORDER BY date, broker, asset, op_type, q, p",
            (self.uid,),
        ).fetchall()
        return ([tuple(r) for r in pos], [tuple(r) for r in ops])

    def _open_qty(self, asset, broker=None):
        if broker:
            r = self.conn.execute(
                "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND broker=? AND asset=? AND is_cash=0",
                (self.uid, broker, asset)).fetchone()
        else:
            r = self.conn.execute(
                "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
                (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def _gpnl(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,)).fetchone()
        return float(r["p"] or 0)


class FeesRegression(_H):
    """Con comisiones de compra Y venta, out-of-order+rebuild == in-order."""
    BUY = _csv("2024-03-15,COMPRA,IBKR,AAPL,10,100,1000,,,5,USD,")
    SELL = _csv("2025-06-20,VENTA,IBKR,AAPL,10,150,1500,,,3,USD,")

    def test_identical_with_fees(self):
        self._broker("IBKR")
        self._imp(self.BUY, "IBKR", rebuild=True)
        self._imp(self.SELL, "IBKR", rebuild=True)
        in_order = self._state()
        gpnl_in = self._gpnl()

        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

        self._imp(self.SELL, "IBKR", rebuild=True)
        self._imp(self.BUY, "IBKR", rebuild=True)
        out = self._state()
        gpnl_out = self._gpnl()

        self.assertEqual(in_order, out)
        self.assertAlmostEqual(gpnl_in, gpnl_out, places=2)
        # pnl = 1500 - (1000+5 buy fee) - 3 sell fee = 492
        self.assertAlmostEqual(gpnl_in, 492.0, places=2)


class SameDayRegression(_H):
    """Compra y venta el MISMO día, en batches separados y fuera de orden."""
    BUY = _csv("2025-01-10,COMPRA,IBKR,AAPL,10,100,1000,,,0,USD,")
    SELL = _csv("2025-01-10,VENTA,IBKR,AAPL,10,150,1500,,,0,USD,")

    def test_same_day_buy_first(self):
        self._broker("IBKR")
        # Fuera de orden: venta primero (mismo día), compra después.
        self._imp(self.SELL, "IBKR", rebuild=False)
        self._imp(self.BUY, "IBKR", rebuild=True)
        # BUY-antes-de-SELL el mismo día → venta consume la compra → 0 held, +500
        self.assertAlmostEqual(self._open_qty("AAPL"), 0.0, places=6)
        self.assertAlmostEqual(self._gpnl(), 500.0, places=2)


class TwoBrokersSameAsset(_H):
    """El scope por (broker, activo) trata brokers distintos independientes."""
    IBKR_BUY = _csv("2024-03-15,COMPRA,IBKR,AAPL,10,100,1000,,,0,USD,")
    IBKR_SELL = _csv("2025-06-20,VENTA,IBKR,AAPL,10,150,1500,,,0,USD,")
    SCHWAB_BUY = _csv("2024-04-01,COMPRA,Schwab,AAPL,5,200,1000,,,0,USD,")

    def test_independent(self):
        self._broker("IBKR")
        self._broker("Schwab")
        self._imp(self.IBKR_SELL, "IBKR", rebuild=False)
        self._imp(self.SCHWAB_BUY, "Schwab", rebuild=False)
        self._imp(self.IBKR_BUY, "IBKR", rebuild=True)
        # IBKR AAPL: vendido todo → 0 held, +500. Schwab AAPL: 5 held intacto.
        self.assertAlmostEqual(self._open_qty("AAPL", "IBKR"), 0.0, places=6)
        self.assertAlmostEqual(self._open_qty("AAPL", "Schwab"), 5.0, places=6)
        self.assertAlmostEqual(self._gpnl(), 500.0, places=2)


class DividendPreserved(_H):
    """El rebuild solo toca ventas (op_type='Venta'); dividendos se preservan."""
    BUY = _csv("2024-02-01,COMPRA,IBKR,KO,10,50,500,,,0,USD,")
    DIV = _csv("2024-12-15,DIVIDENDO,IBKR,KO,,,20,,,0,USD,Q4")
    SELL = _csv("2025-06-20,VENTA,IBKR,KO,10,60,600,,,0,USD,")

    def test_dividend_survives_rebuild(self):
        self._broker("IBKR")
        # La compra es el último import → su confirm dispara el rebuild de KO
        # (un batch de solo-dividendo no toca compras/ventas, no dispararía nada).
        self._imp(self.DIV, "IBKR", rebuild=False)
        self._imp(self.SELL, "IBKR", rebuild=False)
        self._imp(self.BUY, "IBKR", rebuild=True)
        # Venta sana: 0 KO held, +100 (10*(60-50)). Dividendo +20 preservado.
        self.assertAlmostEqual(self._open_qty("KO"), 0.0, places=6)
        divs = self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND op_type='Dividendo'",
            (self.uid,)).fetchall()
        self.assertEqual(len(divs), 1)
        self.assertAlmostEqual(divs[0]["pnl_usd"], 20.0, places=2)
        ventas = self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND op_type='Venta'",
            (self.uid,)).fetchall()
        self.assertEqual(len(ventas), 1)
        self.assertAlmostEqual(ventas[0]["pnl_usd"], 100.0, places=2)
        # global pnl = 100 (venta) + 20 (dividendo) = 120
        self.assertAlmostEqual(self._gpnl(), 120.0, places=2)


class DoubleRebuildStable(_H):
    BUY = _csv("2024-03-15,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,")
    SELL = _csv("2025-06-20,VENTA,IBKR,AAPL,10,200,2000,,,0,USD,")

    def test_rebuild_twice_is_stable(self):
        self._broker("IBKR")
        self._imp(self.SELL, "IBKR", rebuild=False)
        sid = self._imp(self.BUY, "IBKR", rebuild=True)   # 1er rebuild
        s1 = self._state()
        g1 = self._gpnl()
        with self.conn:                                   # 2do rebuild
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=1415.0)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        s2 = self._state()
        g2 = self._gpnl()
        self.assertEqual(s1, s2)             # estado estable
        self.assertAlmostEqual(g1, g2, places=2)
        self.assertAlmostEqual(g1, 500.0, places=2)
        # No se duplicaron ventas
        n = self.conn.execute(
            "SELECT COUNT(*) c FROM operations WHERE user_id=? AND op_type='Venta'",
            (self.uid,)).fetchone()["c"]
        self.assertEqual(n, 1)


class OversellSeed(_H):
    """Vender más de lo comprado en TODA la historia: lote semilla al precio de
    venta (P&L 0 sobre el faltante), sin crashear, holdings 0."""
    BUY = _csv("2024-03-15,COMPRA,IBKR,AAPL,4,100,400,,,0,USD,")
    SELL = _csv("2025-06-20,VENTA,IBKR,AAPL,10,150,1500,,,0,USD,")

    def test_oversell_seed_pnl(self):
        self._broker("IBKR")
        self._imp(self.SELL, "IBKR", rebuild=False)
        self._imp(self.BUY, "IBKR", rebuild=True)
        # 4 reales: 4*(150-100)=200. 6 faltantes (semilla @150): 0. Total +200.
        self.assertAlmostEqual(self._open_qty("AAPL"), 0.0, places=6)
        self.assertAlmostEqual(self._gpnl(), 200.0, places=2)


if __name__ == "__main__":
    unittest.main()
