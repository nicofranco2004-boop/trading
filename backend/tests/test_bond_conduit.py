"""Conductos dólar-MEP de BONOS: un bono usado como "puente" para cambiar de
moneda (comprado en una moneda, vendido en la otra, mismo nominal) NO es tenencia
y debe netear, SIN inflar ni destruir la tenencia genuina del mismo bono.

Bug real (backfill de prod): AL30/GD30/DHS9O usados de conducto + tenencia genuina
→ el rebuild inflaba (5000 USD fantasma en vez de 1000 ARS genuino) o desplomaba.
Causa: las patas-puente que el parser no colapsa llegan al rebuild como BUY/SELL.
Fix: _cancel_conduit_pairs cancela los pares (compra+venta, igual nominal, cruce de
moneda, ≤ventana) antes del FIFO; y la base de amortización usa el neto genuino.

Corre con: cd backend && python3 -m pytest tests/test_bond_conduit.py
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

from importing import pipeline as pl          # noqa: E402
from importing import persister as ps         # noqa: E402
from importing import recompute_backfill as rb  # noqa: E402
import main                                   # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


class BondConduitTest(unittest.TestCase):
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
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("bondconduit@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "ARS"))
        self.conn.execute("INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
                          (self.uid, "tc_blue", "1000"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes):
        with self.conn:
            p = pl.run_preview(self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                               broker_hint="Cocos", parser_format="rendi_generic")
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=p["session_id"])
            ps.persist_batch(self.conn, uid=self.uid, batch_id=p["session_id"], txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())

    def _recompute(self):
        with self.conn:
            rb.recompute_user(self.conn, self.uid, recalc=main._recalc_pnl_realized_from_ops)

    def _qty(self, asset, broker_like=None):
        q = ("SELECT COALESCE(SUM(quantity),0) s FROM positions "
             "WHERE user_id=? AND asset=? AND is_cash=0")
        a = [self.uid, asset]
        if broker_like:
            q += " AND broker LIKE ?"
            a.append(broker_like)
        return float(self.conn.execute(q, a).fetchone()["s"])

    # ── tests ────────────────────────────────────────────────────────────

    def test_genuine_bond_plus_conduit_amortizes_genuine_only(self):
        """El BUG de prod: 1000 AL30 genuino (ARS) + conducto (compra 5000 USD, vende
        5000 ARS) → antes inflaba a 5000 USD fantasma. Ahora: conducto neteado, queda
        el genuino 1000 → amortizado a 720 (R=0.72 a jun-2026). Sin fantasma en '· USD'."""
        self._import(_csv(
            "2024-01-01,COMPRA,Cocos,AL30,1000,108,108000,,,0,ARS,",     # genuino
            "2024-02-01,COMPRA,Cocos,AL30,5000,0.07,350,,,0,USD,",       # conducto: compra USD
            "2024-02-01,VENTA,Cocos,AL30,5000,108,540000,,,0,ARS,",      # conducto: venta ARS
        ))
        self._recompute()
        self.assertAlmostEqual(self._qty("AL30"), 720.0, places=1)            # genuino amortizado
        self.assertAlmostEqual(self._qty("AL30", "%· USD%"), 0.0, places=4)   # SIN fantasma USD

    def test_pure_conduit_bond_nets_to_zero(self):
        """Conducto puro (sin tenencia genuina): compra 1M DHS9O USD + vende 1M ARS
        mismo día → neto 0. (DHS9O = ON, se detecta por nombre.)"""
        self._import(_csv(
            "2025-09-09,COMPRA,Cocos,DHS9O,1000000,0.075,75000,,,0,USD,ON CREDICUOTAS V27/09 (DHS9O)",
            "2025-09-09,VENTA,Cocos,DHS9O,1000000,108,108000000,,,0,ARS,ON CREDICUOTAS V27/09 (DHS9O)",
        ))
        self._recompute()
        self.assertAlmostEqual(self._qty("DHS9O"), 0.0, places=2)

    def test_genuine_bond_no_conduit_still_amortizes(self):
        """Regresión: un bono genuino SIN conducto sigue amortizando normal."""
        self._import(_csv("2024-01-15,COMPRA,Cocos,AL30,1000,108,108000,,,0,ARS,"))
        self._recompute()
        self.assertAlmostEqual(self._qty("AL30"), 720.0, places=1)

    def test_conduit_crossday_within_window_nets(self):
        """Conducto cross-día DENTRO de la ventana (3 días) — el parser lo deja pasar
        (>... su gate), pero la cancelación del rebuild lo netea igual."""
        self._import(_csv(
            "2025-03-01,COMPRA,Cocos,GD30,2000,0.50,1000,,,0,USD,",
            "2025-03-04,VENTA,Cocos,GD30,2000,108,216000,,,0,ARS,",
        ))
        self._recompute()
        self.assertAlmostEqual(self._qty("GD30"), 0.0, places=2)

    def test_dual_currency_genuine_amortizes_proportionally(self):
        """Audit 2026-06-26 (issue 3/4): tenencia GENUINA dual-currency del mismo bono
        amortizante (1000 AL30 USD + 500 ARS) debe amortizar PROPORCIONAL cada moneda
        (× 0.72) → 720 USD + 360 ARS, no consumir una sola por FIFO."""
        self._import(_csv(
            "2024-01-01,COMPRA,Cocos,AL30,1000,0.70,700,,,0,USD,",
            "2024-01-02,COMPRA,Cocos,AL30,500,108,54000,,,0,ARS,",
        ))
        self._recompute()
        usd = self._qty("AL30", "%· USD%")
        total = self._qty("AL30")
        self.assertAlmostEqual(usd, 720.0, places=1)            # USD × 0.72
        self.assertAlmostEqual(total - usd, 360.0, places=1)    # ARS × 0.72
        self.assertAlmostEqual(total, 1080.0, places=1)

    def test_no_cancel_when_currency_not_net_short(self):
        """Audit 2026-06-26 (issues 1 y 2): NO cancelar cuando las compras same-currency
        cubren las ventas (moneda no 'corta') — es tenencia genuina, no conducto."""
        from importing.rebuild import _cancel_conduit_pairs
        from importing.schema import OP_BUY, OP_SELL

        def ev(op, ccy, qty, date):
            return {"operation_type": op, "currency": ccy, "quantity": qty, "date": date,
                    "asset_symbol": "GD30", "asset_name": ""}

        # Issue 1: dual genuino 5000 USD + 5000 ARS, venta parcial USD + venta total ARS.
        e1 = [ev(OP_BUY, "USD", 5000, "2025-12-20"), ev(OP_BUY, "ARS", 5000, "2025-12-21"),
              ev(OP_SELL, "USD", 2500, "2025-12-24"), ev(OP_SELL, "ARS", 5000, "2025-12-27")]
        self.assertEqual(len(_cancel_conduit_pairs(e1)), len(e1))   # nada cancelado

        # Issue 2: 500 ARS + 2×500 USD + venta 500 USD (round-trip same-currency).
        e2 = [ev(OP_BUY, "ARS", 500, "2026-01-01"), ev(OP_BUY, "USD", 500, "2026-01-03"),
              ev(OP_BUY, "USD", 500, "2026-01-05"), ev(OP_SELL, "USD", 500, "2026-01-06")]
        self.assertEqual(len(_cancel_conduit_pairs(e2)), len(e2))   # nada cancelado

    def test_genuine_roundtrip_outside_window_preserved(self):
        """NO cancelar: compra USD + venta ARS de igual nominal pero MESES después es
        un round-trip genuino (con P&L real), no un conducto. La venta consume el
        lote vía FIFO/spill, no por cancelación de conducto."""
        self._import(_csv(
            "2025-01-01,COMPRA,Cocos,GD30,2000,0.50,1000,,,0,USD,",
            "2025-09-01,VENTA,Cocos,GD30,2000,120,240000,,,0,ARS,",   # 8 meses después
        ))
        self._recompute()
        # vendió todo el lote (vía spill cross-currency, no cancelación) → 0, pero por
        # otra vía. Lo clave: el resultado es correcto (neto 0, no fantasma).
        self.assertAlmostEqual(self._qty("GD30", "%· USD%"), 0.0, places=4)


if __name__ == "__main__":
    unittest.main()
