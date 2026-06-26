"""Backfill de recompute de posiciones (scripts/backfill_recompute_positions.py).

Corrige cuentas YA importadas (currency-aware + neteo cross-broker MEP + amort de
bonos) sin re-importar, corriendo la misma secuencia post-import que import_confirm
(rebuild por batch → sweep letras → sweep amort → recalc).

Lo crítico que cubre:
  - SEGURIDAD: sobre una cuenta correcta es no-op (no corrompe ni toca cash).
  - Cura fantasmas: un lote fantasma (import fuera de orden) se netea.
  - Baja bonos amortizantes a su residual.
  - Dry-run no muta; --apply sí; idempotente.

Corre con: cd backend && python3 -m pytest tests/test_backfill_recompute.py
"""
import importlib
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

from importing import pipeline as pl   # noqa: E402
from importing import persister as ps  # noqa: E402
import main                            # noqa: E402

bf = importlib.import_module("scripts.backfill_recompute_positions")


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


class BackfillRecomputeTest(unittest.TestCase):
    BROKER = "Cocos"

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
            ("backfill@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        self.conn.execute("INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
                          (self.uid, "tc_blue", "1000"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes):
        """Importa SIN correr rebuild/sweeps (simula el estado PRE-backfill)."""
        with self.conn:
            p = pl.run_preview(self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                               broker_hint=self.BROKER, parser_format="rendi_generic")
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=p["session_id"])
            ps.persist_batch(self.conn, uid=self.uid, batch_id=p["session_id"], txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())

    def _qty(self, asset):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    # ── tests ───────────────────────────────────────────────────────────────

    def test_noop_on_correct_portfolio(self):
        """SEGURIDAD: una cartera correcta (CEDEARs en orden) no cambia ni en
        posiciones ni en cash tras el recompute."""
        self._import(_csv(
            "2024-01-10,COMPRA,Cocos,GGAL,100,1000,100000,,,0,ARS,",
            "2024-01-11,COMPRA,Cocos,AL30,500,0.70,350,,,0,ARS,",  # bono no amortizado aún a esta fecha
        ))
        pos_before = bf._positions_snapshot(self.conn, self.uid)
        cash_before = bf._cash_total(self.conn, self.uid)
        with self.conn:
            bf._recompute_user(self.conn, self.uid)
        # GGAL intacto; cash intacto (el rebuild NO toca cash).
        self.assertEqual(self._qty("GGAL"), 100.0)
        self.assertEqual(bf._cash_total(self.conn, self.uid), cash_before)
        # GGAL no cambió (AL30 sí baja por amort — eso es correcto, ver test aparte).
        self.assertEqual(pos_before[(self.BROKER, "GGAL")],
                         bf._positions_snapshot(self.conn, self.uid)[(self.BROKER, "GGAL")])

    def test_heals_out_of_order_phantom(self):
        """Importar la VENTA antes que la COMPRA (fuera de orden) deja un lote
        fantasma; el backfill lo netea (recompute desde el historial)."""
        self._import(_csv("2025-06-20,VENTA,Cocos,AAPL,10,200,2000,,,0,ARS,"))  # venta primero
        self._import(_csv("2024-03-15,COMPRA,Cocos,AAPL,10,150,1500,,,0,ARS,"))  # compra después
        self.assertAlmostEqual(self._qty("AAPL"), 10.0, places=4)  # fantasma (compra abierta)
        with self.conn:
            bf._recompute_user(self.conn, self.uid)
        self.assertAlmostEqual(self._qty("AAPL"), 0.0, places=4)   # neteado: se vendió todo

    def test_reduces_amortizing_bond(self):
        """El backfill incluye el sweep de amort: AL30 1000 → residual."""
        self._import(_csv("2024-01-15,COMPRA,Cocos,AL30,1000,0.70,700,,,0,ARS,"))
        self.assertEqual(self._qty("AL30"), 1000.0)
        with self.conn:
            bf._recompute_user(self.conn, self.uid)
        # a la fecha de hoy AL30 ya amortizó parte → < 1000.
        self.assertLess(self._qty("AL30"), 1000.0)
        self.assertGreater(self._qty("AL30"), 0.0)

    def test_dryrun_no_mutation_then_apply_idempotent(self):
        """run() en dry-run no muta; --apply sí; segundo --apply es no-op."""
        self._import(_csv("2025-06-20,VENTA,Cocos,AAPL,10,200,2000,,,0,ARS,"))
        self._import(_csv("2024-03-15,COMPRA,Cocos,AAPL,10,150,1500,,,0,ARS,"))
        # run() abre su PROPIA conexión al mismo DB → leemos con una conn fresca
        # cada vez (self.conn tiene su propio snapshot y no vería los commits de run).
        self.conn.commit()
        self.conn.close()

        def _qty_fresh():
            c = main.get_db()
            try:
                r = c.execute("SELECT COALESCE(SUM(quantity),0) q FROM positions "
                              "WHERE user_id=? AND asset='AAPL' AND is_cash=0", (self.uid,)).fetchone()
                return float(r["q"] or 0)
            finally:
                c.close()

        bf.run(apply=False, only_uid=self.uid)          # dry-run
        self.assertAlmostEqual(_qty_fresh(), 10.0, places=4)  # NO mutó
        bf.run(apply=True, only_uid=self.uid)           # apply
        self.assertAlmostEqual(_qty_fresh(), 0.0, places=4)   # neteado
        bf.run(apply=True, only_uid=self.uid)           # idempotente
        self.assertAlmostEqual(_qty_fresh(), 0.0, places=4)

        # reabrir self.conn para que tearDown la cierre sin error
        self.conn = main.get_db()


class BackfillEndpointTest(unittest.TestCase):
    """El botón admin: POST /api/admin/backfill-recompute (dry-run/apply + gate)."""

    def setUp(self):
        from fastapi.testclient import TestClient
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.admin = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?,?,1,1)",
            ("admin@rendi.test", "x")).lastrowid
        self.user = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?,?,1,0)",
            ("plebe@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.admin, "Cocos", "ARS"))
        self.conn.execute("INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
                          (self.admin, "tc_blue", "1000"))
        self.conn.commit()
        # import fuera de orden en la cuenta admin → AAPL fantasma (10).
        for csv in (_csv("2025-06-20,VENTA,Cocos,AAPL,10,200,2000,,,0,ARS,"),
                    _csv("2024-03-15,COMPRA,Cocos,AAPL,10,150,1500,,,0,ARS,")):
            with self.conn:
                p = pl.run_preview(self.conn, uid=self.admin, file_bytes=csv, file_name="x.csv",
                                   broker_hint="Cocos", parser_format="rendi_generic")
            with self.conn:
                txs, raw = pl.load_session_for_confirm(self.conn, uid=self.admin, session_id=p["session_id"])
                ps.persist_batch(self.conn, uid=self.admin, batch_id=p["session_id"], txs=txs,
                                 raw_row_ids_by_index=raw, helpers=_helpers())
        self.conn.close()
        self.client = TestClient(main.app)

    def _hdr(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _aapl(self):
        c = main.get_db()
        try:
            return float(c.execute("SELECT COALESCE(SUM(quantity),0) q FROM positions "
                                   "WHERE asset='AAPL' AND is_cash=0").fetchone()["q"] or 0)
        finally:
            c.close()

    def test_non_admin_forbidden(self):
        r = self.client.post("/api/admin/backfill-recompute", headers=self._hdr(self.user))
        self.assertEqual(r.status_code, 403, r.text)

    def test_dryrun_reports_without_mutating_then_apply(self):
        # DRY-RUN: reporta el cambio pero NO toca la base real.
        r = self.client.post("/api/admin/backfill-recompute?apply=false", headers=self._hdr(self.admin))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["applied"])
        self.assertEqual(body["users_changed"], 1)
        self.assertEqual(body["cash_warnings"], 0)
        self.assertTrue(any(c.get("asset") == "AAPL" and c["after"] == 0 for c in body["changes"]))
        self.assertEqual(self._aapl(), 10.0)   # real NO mutó

        # APPLY: ahora sí.
        r2 = self.client.post("/api/admin/backfill-recompute?apply=true", headers=self._hdr(self.admin))
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertTrue(r2.json()["applied"])
        self.assertEqual(self._aapl(), 0.0)    # neteado en la real


if __name__ == "__main__":
    unittest.main()
