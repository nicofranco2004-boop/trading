"""Neteo cross-broker del par padre↔'· USD' (dólar-MEP con acciones/CEDEARs).

Bug real reportado por un usuario (captura "Cocos · USD" con BMA 37 / YPFD 4): una
acción comprada vía dólar-MEP (pata USD que el routing manda al sub-broker '· USD')
y vendida después en pesos (pata ARS en el broker padre) quedaba como tenencia
FANTASMA en '· USD'. El FIFO nunca la neteaba porque las dos patas viven en brokers
distintos (padre ARS vs sibling USD). El fix hace que el FIFO —persister, rebuild y
venta manual— consuma lotes del activo across el PAR de brokers, manteniendo el cash
per-broker (el USD sale del sibling, los pesos entran al padre).

Corre con: cd backend && python3 -m pytest tests/test_xbroker_mep_netting.py
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

from importing import pipeline as pl   # noqa: E402
from importing import persister as ps  # noqa: E402
from importing import rebuild as rb    # noqa: E402
import main                            # noqa: E402


HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows: str) -> bytes:
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    for name in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
                 "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
                 "_recalc_pnl_realized_from_ops"):
        setattr(h, name, getattr(main, name))
    return h


class XBrokerMepNetting(unittest.TestCase):
    BROKER = "Cocos"   # broker ARS → route_by_currency crea el sibling '· USD'

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
            ("xbroker@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes: bytes, *, rebuild: bool = True) -> str:
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic")
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

    def _qty(self, asset: str, broker_like: str = None) -> float:
        q = ("SELECT COALESCE(SUM(quantity),0) s FROM positions "
             "WHERE user_id=? AND asset=? AND is_cash=0")
        a = [self.uid, asset]
        if broker_like:
            q += " AND broker LIKE ?"
            a.append(broker_like)
        return float(self.conn.execute(q, a).fetchone()["s"])

    def _ventas(self, asset: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM operations WHERE user_id=? AND asset=? AND op_type='Venta'",
            (self.uid, asset)).fetchone()["c"]

    def _sibling_exists(self) -> bool:
        r = self.conn.execute(
            "SELECT COUNT(*) c FROM brokers WHERE user_id=? AND name LIKE ?",
            (self.uid, "%· USD%")).fetchone()
        return r["c"] > 0

    # ── tests ─────────────────────────────────────────────────────────────

    def test_usd_buy_ars_sell_nets_across_pair(self):
        """Compra USD (→ sibling '· USD') + venta ARS (→ padre), misma cantidad →
        tenencia neta 0. Es el bug exacto del usuario (BMA 37)."""
        csv = _csv(
            "2025-09-09,COMPRA,Cocos,BMA,37,4.5959,170.05,,,0,USD,",
            "2025-10-09,VENTA,Cocos,BMA,37,7365,272505,,,0,ARS,",
        )
        self._import(csv, rebuild=True)
        self.assertTrue(self._sibling_exists(), "el routing debería haber creado el sibling '· USD'")
        self.assertAlmostEqual(self._qty("BMA"), 0.0, places=6)               # neto 0
        self.assertAlmostEqual(self._qty("BMA", "%· USD%"), 0.0, places=6)    # sin fantasma en '· USD'
        self.assertEqual(self._ventas("BMA"), 1)                              # una venta registrada

    def test_usd_buy_without_sell_stays(self):
        """Solo compra USD, sin venta → tenencia GENUINA en '· USD' (no la borramos).
        Es el caso YPFD del usuario: sin venta en los datos no hay nada que netear."""
        csv = _csv("2025-09-09,COMPRA,Cocos,YPFD,4,27,108,,,0,USD,")
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("YPFD"), 4.0, places=6)
        self.assertAlmostEqual(self._qty("YPFD", "%· USD%"), 4.0, places=6)

    def test_partial_ars_sell_leaves_remainder_in_sibling(self):
        """Compra USD 10, venta ARS 4 → quedan 6 (neteo parcial cross-broker), y el
        remanente sigue en el sibling '· USD' con su moneda nativa."""
        csv = _csv(
            "2025-09-09,COMPRA,Cocos,BMA,10,5,50,,,0,USD,",
            "2025-10-09,VENTA,Cocos,BMA,4,7000,28000,,,0,ARS,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("BMA"), 6.0, places=6)
        self.assertAlmostEqual(self._qty("BMA", "%· USD%"), 6.0, places=6)
        self.assertEqual(self._ventas("BMA"), 1)

    def test_ars_only_asset_unaffected(self):
        """Un activo comprado y vendido SOLO en pesos (sin pata USD) sigue neteando
        en el padre como siempre — el cambio no afecta el caso no-MEP."""
        csv = _csv(
            "2025-09-09,COMPRA,Cocos,GGAL,100,1000,100000,,,0,ARS,",
            "2025-10-09,VENTA,Cocos,GGAL,100,1200,120000,,,0,ARS,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("GGAL"), 0.0, places=6)
        self.assertEqual(self._ventas("GGAL"), 1)


if __name__ == "__main__":
    unittest.main()
