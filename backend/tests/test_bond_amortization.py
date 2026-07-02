"""Sweep de amortización de bonos AR (importing/maturity.sweep_bond_amortizations).

Bug que cubre (reporte real de un usuario): "me tomó como posición activa AL30 y
una LECAP que ya estaba 100% amortizada que ya no tenía". Los bonos que amortizan
(AL30/GD30) devuelven capital en cuotas; el mercado los cotiza por nominal
RESIDUAL, pero Rendi guarda el nominal ORIGINAL (la amortización entra como
dividendo = solo cash) → tenencia/valuación sobrevaluadas, y un bono 100%
amortizado sigue figurando.

El sweep baja el nominal a (comprado − vendido) × factor_residual(fecha).
AL30/GD30 (verificado Rava/IOL): 13 cuotas semestrales, 1ª 4% (9-jul-2024) + 12×8%.
A 2026-06-25 pagaron 4+8+8+8 = 28% → residual 72%.

Corre con: cd backend && python3 -m pytest tests/test_bond_amortization.py
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

from importing import pipeline as pl    # noqa: E402
from importing import persister as ps   # noqa: E402
from importing import maturity as mat   # noqa: E402
from pricing import bond_amortization as ba  # noqa: E402
import main                             # noqa: E402


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


# ── tests del helper de factor residual (puros, sin DB) ─────────────────────
class ResidualFactorTest(unittest.TestCase):
    def test_al30_schedule(self):
        self.assertAlmostEqual(ba.residual_factor("AL30", "2024-01-01"), 1.0)      # antes de amortizar
        self.assertAlmostEqual(ba.residual_factor("AL30", "2024-07-09"), 0.96)     # tras 1ª cuota (4%)
        self.assertAlmostEqual(ba.residual_factor("AL30", "2026-06-25"), 0.72)     # 28% pagado
        self.assertAlmostEqual(ba.residual_factor("AL30", "2030-07-09"), 0.0)      # 100% amortizado

    def test_variants_and_gd30(self):
        for tk in ("GD30", "AL30D", "AL30.BA", "GD30D"):
            self.assertAlmostEqual(ba.residual_factor(tk, "2026-06-25"), 0.72, msg=tk)

    def test_al29_gd29_schedule(self):
        # 10 cuotas de 10% (9-ene/9-jul, 1ª 9-ene-2025). A 2026-06-25: 3 cuotas = 30%.
        self.assertAlmostEqual(ba.residual_factor("AL29", "2024-12-01"), 1.0)
        self.assertAlmostEqual(ba.residual_factor("AL29", "2025-01-09"), 0.90)
        self.assertAlmostEqual(ba.residual_factor("AL29", "2026-06-25"), 0.70)
        self.assertAlmostEqual(ba.residual_factor("GD29", "2026-06-25"), 0.70)
        self.assertAlmostEqual(ba.residual_factor("AL29", "2029-07-09"), 0.0)

    def test_non_amortizing_is_noop(self):
        # GD35 todavía no amortiza; AAPL no es bono → R=1 (no se toca).
        self.assertEqual(ba.residual_factor("GD35", "2026-06-25"), 1.0)
        self.assertEqual(ba.residual_factor("AAPL", "2026-06-25"), 1.0)
        self.assertFalse(ba.is_amortizing_bond("GD35"))
        self.assertTrue(ba.is_amortizing_bond("AL30"))


# ── tests del sweep (con DB + pipeline real) ────────────────────────────────
class SweepBondAmortTest(unittest.TestCase):
    BROKER = "Balanz"

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
            ("bondamort@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, "ARS"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self, csv_bytes: bytes):
        """Importa SIN correr el sweep (lo invocamos a mano con ref_date fijo)."""
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
        return sid

    def _qty(self, asset: str) -> float:
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions "
            "WHERE user_id=? AND asset=? AND is_cash=0", (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def _invested(self, asset: str) -> float:
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) i FROM positions "
            "WHERE user_id=? AND asset=? AND is_cash=0", (self.uid, asset)).fetchone()
        return float(r["i"] or 0)

    def test_reduces_to_residual(self):
        # Compra 1000 VN de AL30 a 0.70/VN. A 2026-06-25 el residual es 72% → 720 VN.
        self._import(_csv("2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,"))
        self.assertEqual(self._qty("AL30"), 1000.0)
        with self.conn:
            res = mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 720.0, places=4)
        # invested baja proporcional (mantiene costo unitario 0.70): 720×0.70 = 504.
        self.assertAlmostEqual(self._invested("AL30"), 504.0, places=2)
        self.assertEqual(len(res["adjusted"]), 1)

    def test_fully_amortized_disappears(self):
        # A 2030-07-09 amortizó el 100% → la posición desaparece (era el caso del user).
        self._import(_csv("2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,"))
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2030-07-09")
        self.assertEqual(self._qty("AL30"), 0.0)

    def test_idempotent(self):
        # Correr el sweep dos veces con la misma fecha no baja de más.
        self._import(_csv("2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,"))
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 720.0, places=4)

    def test_non_amortizing_bond_untouched(self):
        # GD35 todavía no amortiza → no se toca.
        self._import(_csv("2024-01-15,COMPRA,Balanz,GD35,500,90,45000,,,0,ARS,"))
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertEqual(self._qty("GD35"), 500.0)

    def test_non_bond_untouched(self):
        # Una acción cualquiera no se toca.
        self._import(_csv("2024-01-15,COMPRA,Balanz,GGAL,100,1000,100000,,,0,ARS,"))
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertEqual(self._qty("GGAL"), 100.0)

    def test_respects_partial_sell(self):
        # Compra 1000, vende 200 → base 800 VN. Residual 72% → 800×0.72 = 576.
        self._import(_csv(
            "2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,",
            "2024-02-15,VENTA,Balanz,AL30,200,0.75,150,,,0,ARS,",
        ))
        self.assertAlmostEqual(self._qty("AL30"), 800.0, places=4)
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 576.0, places=4)

    def test_amort_sell_not_double_reduced(self):
        # Bug real (Balanz "Renta y Amortización" con cantidad): la amortización
        # entra como VENTA que cierra la cuota al valor de rescate (P&L correcto,
        # baja el nominal). El sweep NO debe volver a aplicar el factor del schedule
        # sobre esa cuota ya cerrada. Compra 1000, la VENTA-amort ya bajó 280 VN
        # (28% a 2026-06-25) → quedan 720. El sweep debe DEJARLO en 720, no bajarlo
        # a 518.4 (= 720×0.72) que era la DOBLE reducción.
        self._import(_csv(
            "2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,",
            "2026-06-20,VENTA,Balanz,AL30,280,0.78,218.4,,,0,ARS,Renta y Amortización",
        ))
        self.assertAlmostEqual(self._qty("AL30"), 720.0, places=4)  # tras la VENTA-amort
        with self.conn:
            res = mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 720.0, places=4)  # NO 518.4
        self.assertEqual(len(res["adjusted"]), 0)                   # no-op (ya está en residual)

    def test_amort_sell_stale_export_catches_up(self):
        # Export viejo: la VENTA-amort solo cerró 160 VN (16%), pero a 2026-06-25 ya
        # amortizó 28% → el sweep debe bajar de 840 a 720 (alcanza la cuota faltante
        # del calendario), SIN doble-contar la cuota ya cerrada por la VENTA. La base
        # del sweep es el nominal original (1000), no 1000−160.
        self._import(_csv(
            "2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,",
            "2025-08-01,VENTA,Balanz,AL30,160,0.78,124.8,,,0,ARS,Renta y Amortización",
        ))
        self.assertAlmostEqual(self._qty("AL30"), 840.0, places=4)
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 720.0, places=4)

    def test_genuine_sell_still_counts(self):
        # Una VENTA genuina (sin 'amortiz' en notes) SÍ entra en la base: compra
        # 1000, vende 200 → base 800, residual 72% → 576 (no debe cambiar con el fix).
        self._import(_csv(
            "2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,",
            "2024-02-15,VENTA,Balanz,AL30,200,0.75,150,,,0,ARS,Venta parcial",
        ))
        self.assertAlmostEqual(self._qty("AL30"), 800.0, places=4)
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 576.0, places=4)

    def test_manual_position_untouched(self):
        # Una posición de AL30 creada a mano (no import-linked) NO se toca.
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested, currency) "
            "VALUES (?,?,?,0,?,?,?)", (self.uid, "Balanz", "AL30", 1000, 700, "ARS"))
        self.conn.commit()
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertEqual(self._qty("AL30"), 1000.0)  # intacta (manual)

    def test_foto_seed_exempt_from_amort(self):
        # La foto de tenencia siembra el nominal RESIDUAL real de HOY (lo que el broker
        # reporta), NO el original. Esos lotes ('Tenencia — apertura') NO se re-amortizan
        # (sería doble-conteo) y tampoco cuentan en la BASE del sweep. Movimientos AL30
        # 1000 (se amortiza a 720 = 1000×0.72) + seed de foto 300 (intacto) → 1020.
        # Los números distinguen la regresión: 1236 = falló Change 2a (base infló con el
        # seed); 720 = falló Change 2b (se re-amortizó el seed).
        self._import(_csv(
            "2024-01-15,COMPRA,Balanz,AL30,1000,0.70,700,,,0,ARS,",
            "2026-06-30,COMPRA,Balanz,AL30,300,0.75,225,,,0,ARS,"
            "Tenencia — apertura AL30 a precio de 2026-06-30 (P&L 0)",
        ))
        self.assertAlmostEqual(self._qty("AL30"), 1300.0, places=4)   # 1000 + 300 seed
        with self.conn:
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 1020.0, places=4)   # 720 (amort) + 300 (seed intacto)
        with self.conn:  # idempotente: re-correr no cambia nada
            mat.sweep_bond_amortizations(self.conn, self.uid, ref_date="2026-06-25")
        self.assertAlmostEqual(self._qty("AL30"), 1020.0, places=4)


if __name__ == "__main__":
    unittest.main()
