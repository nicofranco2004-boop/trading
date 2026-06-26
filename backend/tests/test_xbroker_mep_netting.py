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

    def _pnl(self, asset: str) -> float:
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) s FROM operations WHERE user_id=? AND asset=? AND op_type='Venta'",
            (self.uid, asset)).fetchone()["s"])

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

    def test_ars_oversell_spills_to_usd_lot(self):
        """Caso real IOL (AAPL/XLRE/JNJ): YA hay lotes ARS + una pata USD (dólar-MEP),
        y una venta ARS supera los lotes ARS (oversell). El remanente debe consumir
        el lote USD del sibling (spill cross-currency) y NETEAR a 0 — no dejar el
        fantasma USD. Antes (`_same if _same else lots`) el remanente NO tocaba el
        lote USD porque había lotes ARS → fantasma de 2 en '· USD'."""
        csv = _csv(
            "2025-07-28,COMPRA,Cocos,AAPL,11,100,1100,,,0,ARS,",   # 11 ARS (genuino)
            "2025-07-29,COMPRA,Cocos,AAPL,2,10,20,,,0,USD,",       # 2 USD (dólar-MEP)
            "2026-01-16,VENTA,Cocos,AAPL,13,120,1560,,,0,ARS,",    # vende 13 ARS → oversell por 2
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("AAPL"), 0.0, places=6)               # total neteado
        self.assertAlmostEqual(self._qty("AAPL", "%· USD%"), 0.0, places=6)    # SIN fantasma USD
        # P&L del chunk cross-currency (lote USD consumido por venta ARS, valuado con
        # tc_blue) tiene que ser SANO — no un 100× fake. Costo USD 20 → ARS≈20k vs
        # proceeds ARS 1560×(2/13)≈240 → pérdida acotada, lejos de cualquier 100×.
        self.assertLess(abs(self._pnl("AAPL")), 1e6, "P&L del spill cross-currency fuera de rango")

    def test_genuine_dual_currency_partial_oversell_preserves_usd(self):
        """Tenencia GENUINA dual-currency: 5 ARS + 5 USD. Una venta ARS de 7 (oversell
        de 2, PERO MENOR que la pata USD de 5) NO debe comerse la pata USD genuina —
        el faltante se cubre con un seed same-currency (history-as-truth). El spill
        cross-currency solo aplica cuando el oversell consume ENTERA la pata USD
        (neteo total dólar-MEP), no a un oversell parcial. Regresión del audit
        2026-06-26 (over-netting): antes `_same + _other` se comía 2 de la pata USD."""
        csv = _csv(
            "2025-07-01,COMPRA,Cocos,GGAL,5,1000,5000,,,0,ARS,",
            "2025-07-02,COMPRA,Cocos,GGAL,5,10,50,,,0,USD,",
            "2026-01-16,VENTA,Cocos,GGAL,7,1200,8400,,,0,ARS,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("GGAL", "%· USD%"), 5.0, places=6)   # pata USD GENUINA intacta
        self.assertAlmostEqual(self._qty("GGAL"), 5.0, places=6)             # total = 5 (USD), ARS 0

    def test_genuine_dual_currency_split_oversell_preserves_usd(self):
        """Igual que el anterior pero el oversell ARS llega en DOS ventas (7 + 2). La
        primera drena los lotes ARS; la segunda ve _same_total==0 y NO debe tratar la
        pata USD genuina como conduit (case (a)) — el activo SÍ tuvo compra ARS
        (seen_buy_ccy), así que se preserva. Order-independence (regresión audit
        2026-06-26: la 2da venta se comía 2 de la pata USD)."""
        csv = _csv(
            "2025-07-01,COMPRA,Cocos,GGAL,5,1000,5000,,,0,ARS,",
            "2025-07-02,COMPRA,Cocos,GGAL,5,10,50,,,0,USD,",
            "2026-01-16,VENTA,Cocos,GGAL,7,1200,8400,,,0,ARS,",
            "2026-02-16,VENTA,Cocos,GGAL,2,1300,2600,,,0,ARS,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("GGAL", "%· USD%"), 5.0, places=6)   # pata USD GENUINA intacta
        self.assertAlmostEqual(self._qty("GGAL"), 5.0, places=6)

    def test_ars_sell_within_lots_preserves_genuine_usd(self):
        """Tenencia USD genuina NO se toca cuando la venta ARS se cubre con lotes ARS:
        SPY 14 ARS + 4 USD, vende 10 ARS (dentro de los 14) → quedan 4 ARS + 4 USD = 8.
        El spill cross-currency solo aplica al OVERSELL, no a ventas normales."""
        csv = _csv(
            "2025-07-28,COMPRA,Cocos,SPY,14,100,1400,,,0,ARS,",
            "2025-07-29,COMPRA,Cocos,SPY,4,10,40,,,0,USD,",
            "2026-01-16,VENTA,Cocos,SPY,10,120,1200,,,0,ARS,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("SPY", "%· USD%"), 4.0, places=6)     # USD genuino preservado
        self.assertAlmostEqual(self._qty("SPY"), 8.0, places=6)               # 4 ARS + 4 USD

    def test_gradual_cross_currency_oversell_nets_to_zero(self):
        """EL BUG BALANZ: un ticker con compras same-currency YA cerradas MÁS una pata
        cruzada que se consume GRADUALMENTE en varias ventas chicas. 10 ARS (genuino,
        se cierra) + 50 USD (dólar-MEP); después se venden 10 ARS (cierra la pata ARS)
        y 50 ARS más en CINCO ventas de 10. Ninguna venta sola oversella ≥ la pata USD
        de 50, así que el full_net por-venta NUNCA dispara y la decisión vieja dejaba
        50 USD FANTASMA (AAPL/XLP/GD35/etc. del export real). El presupuesto AGREGADO
        (oversell[ARS]=50 == pata USD=50 → full net global) lo netea a 0."""
        csv = _csv(
            "2025-01-02,COMPRA,Cocos,AAPL,10,1000,10000,,,0,ARS,",
            "2025-01-03,COMPRA,Cocos,AAPL,50,10,500,,,0,USD,",
            "2025-02-01,VENTA,Cocos,AAPL,10,1200,12000,,,0,ARS,",
            "2025-03-01,VENTA,Cocos,AAPL,10,1300,13000,,,0,ARS,",
            "2025-03-02,VENTA,Cocos,AAPL,10,1300,13000,,,0,ARS,",
            "2025-03-03,VENTA,Cocos,AAPL,10,1300,13000,,,0,ARS,",
            "2025-03-04,VENTA,Cocos,AAPL,10,1300,13000,,,0,ARS,",
            "2025-03-05,VENTA,Cocos,AAPL,10,1300,13000,,,0,ARS,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("AAPL"), 0.0, places=6)               # neto total 0
        self.assertAlmostEqual(self._qty("AAPL", "%· USD%"), 0.0, places=6)    # SIN fantasma USD

    def test_usd_oversell_partial_spills_to_ars_leg(self):
        """ASIMETRÍA (caso AMZN del archivo real): una venta USD oversold consume PARCIAL
        la pata ARS genuina (no la entera). 100 ARS genuino + 30 USD; vende 50 USD
        (oversell 20 < pata ARS 100). Debe quedar 80 ARS (se bajó el nominal ARS en 20
        por el dólar-MEP), NO 100 (la regla binaria pura dejaría 100) ni 0."""
        csv = _csv(
            "2025-01-02,COMPRA,Cocos,AMZN,100,1000,100000,,,0,ARS,",
            "2025-01-03,COMPRA,Cocos,AMZN,30,10,300,,,0,USD,",
            "2025-02-01,VENTA,Cocos,AMZN,50,12,600,,,0,USD,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("AMZN"), 80.0, places=6)             # 100 ARS − 20 spill
        self.assertAlmostEqual(self._qty("AMZN", "%· USD%"), 0.0, places=6)   # pata USD cerrada

    def test_bidirectional_cross_currency_nets_to_zero(self):
        """BIDIRECCIONAL (regresión que evita el enfoque combinado): el mismo ticker
        operado por dólar-MEP en AMBAS direcciones. Compra 10 USD, vende 10 ARS, compra
        10 ARS, vende 10 USD → neto 0. Los oversell AGREGADOS por moneda dan 0 (cada
        moneda está balanceada), así que un presupuesto puro lo dejaría fantasma; la
        decisión per-venta (never_held_same / full_net cronológicos) lo cierra. El
        máximo entre ambas capacidades preserva este caso."""
        csv = _csv(
            "2025-01-02,COMPRA,Cocos,NVDA,10,10,100,,,0,USD,",
            "2025-02-01,VENTA,Cocos,NVDA,10,1200,12000,,,0,ARS,",
            "2025-03-01,COMPRA,Cocos,NVDA,10,1000,10000,,,0,ARS,",
            "2025-04-01,VENTA,Cocos,NVDA,10,12,120,,,0,USD,",
        )
        self._import(csv, rebuild=True)
        self.assertAlmostEqual(self._qty("NVDA"), 0.0, places=6)              # neto total 0
        self.assertAlmostEqual(self._qty("NVDA", "%· USD%"), 0.0, places=6)   # sin fantasma


if __name__ == "__main__":
    unittest.main()
