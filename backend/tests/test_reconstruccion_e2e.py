"""La cadena completa: import → reconstrucción a mercado → serie medible.

Es la afirmación central del trabajo y la razón por la que el plan se invirtió:
filtrar y listo apagaba el número falso pero le BORRABA la historia al que importa.
Reconstruir primero le da valor apenas la carga.
"""
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr
import scripts.backfill_historical_mtm as bf
from importing.persister import _backfill_snapshots_from_monthly



def _todos(s):
    """Los puntos ACEPTADOS —medibles y no medibles— juntos y en orden.

    ⚠️ VIVE EN LOS TESTS A PROPÓSITO. `serie_medible` dejó de devolver una lista
    mezclada justamente para que producción no pueda recorrerla sin decidir; un
    test sí puede mirar todo, pero tiene que nombrarlo.
    """
    return sorted(list(s["medibles"]) + list(s["no_medibles"]), key=lambda p: p["date"])

class ReconstruccionE2ETest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "monthly_entries", "import_normalized_tx",
                  "import_raw_rows", "import_batches", "brokers", "positions",
                  "operations", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("e2e@t", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "IBKR", "USDT"))
        bid = "B1"
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, broker, parser_format, file_hash, status) "
            "VALUES (?,?,?,?,?,'confirmed')", (bid, self.uid, "IBKR", "generic", "h"))
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status) "
            "VALUES (?,?,?,'valid')", (bid, 0, "{}")).lastrowid
        self.conn.execute(
            """INSERT INTO import_normalized_tx
               (batch_id, raw_row_id, broker, asset_symbol, asset_type, operation_type,
                quantity, unit_price, gross_amount, currency, date)
               VALUES (?,?,'IBKR','AAPL','STOCK','BUY',10,200,2000,'USD','2024-08-05')""",
            (bid, rr))
        for (y, m, ci, cf) in ((2024, 8, 0, 2000), (2024, 9, 2000, 2000), (2024, 10, 2000, 2000)):
            for b in ("global", "IBKR"):
                self.conn.execute(
                    "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
                    "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
                    "VALUES (?,?,?,?,?,?,?,0,0,0)",
                    (self.uid, b, y, m, ci, cf, 2000 if m == 8 else 0))
        self.conn.commit()
        self._orig_fetch = bf._fetch_monthly_close

    def tearDown(self):
        bf._fetch_monthly_close = self._orig_fetch
        self.conn.close()

    def test_de_la_foto_fabricada_a_la_historia_recuperada(self):
        # ── PASO 1: lo que deja el import son fotos FABRICADAS y PLANAS ────────
        _backfill_snapshots_from_monthly(self.conn, self.uid)
        self.conn.commit()
        filas = self.conn.execute(
            "SELECT date, total_value, source FROM snapshots WHERE user_id=? ORDER BY date",
            (self.uid,)).fetchall()
        self.assertEqual([r["source"] for r in filas], ["import"] * 3)
        self.assertEqual([r["total_value"] for r in filas], [2000.0] * 3)  # planas: es el costo

        s0 = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(_todos(s0), [])          # nada de eso es medible
        self.assertEqual(s0["motivo"], "importado_sin_mediciones")

        # ── PASO 2: la reconstrucción a precio de mercado histórico ────────────
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda pk, si: {
            "2024-08": 250.0, "2024-09": 300.0, "2024-10": 275.0}
        res = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.conn.commit()
        self.assertEqual(res["snapshots_escritos"], 3)

        filas = self.conn.execute(
            "SELECT date, total_value, source, mtm_coverage FROM snapshots "
            "WHERE user_id=? ORDER BY date", (self.uid,)).fetchall()
        # Pisó las fabricadas (el viejo ON CONFLICT DO NOTHING no lo hacía) y las
        # etiquetó con su propio source (no 'import').
        self.assertEqual([r["source"] for r in filas], ["mtm_backfill"] * 3)
        self.assertEqual([r["total_value"] for r in filas], [2500.0, 3000.0, 2750.0])
        self.assertEqual([r["mtm_coverage"] for r in filas], [1.0] * 3)

        # ── PASO 3: ahora SÍ hay historia medible ─────────────────────────────
        cv = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(_todos(cv)), 3)
        self.assertEqual(cv["medido_desde"], "2024-08-31")
        self.assertEqual(cv["por_clase"][twr.RECONSTRUIDO], 3)
        self.assertAlmostEqual(cv["twr"], 0.10, places=6)          # 2500 → 2750
        self.assertAlmostEqual(cv["drawdown_maximo"], -1 / 12, places=4)  # 3000 → 2750
        self.assertEqual(cv["contable"], [])       # ya no queda nada afuera

    def test_la_contabilidad_queda_intacta_y_sobrevive_al_repair(self):
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda pk, si: {
            "2024-08": 250.0, "2024-09": 300.0, "2024-10": 275.0}
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.conn.commit()
        cf = [r["capital_final"] for r in self.conn.execute(
            "SELECT capital_final FROM monthly_entries WHERE user_id=? AND broker='global' "
            "ORDER BY year, month", (self.uid,))]
        self.assertEqual(cf, [2000.0, 2000.0, 2000.0])   # la contabilidad no se tocó

        # Y la reconstrucción sobrevive a la pasada que antes la borraba.
        main._repair_monthly_chain(self.conn, self.uid, "global")
        main._repair_monthly_chain(self.conn, self.uid, "IBKR")
        self.conn.commit()
        cv = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(cv["twr"], 0.10, places=6)

    def test_el_hook_post_import_reconstruye_sin_tocar_la_contabilidad(self):
        """Hasta acá el reconstructor existía y no lo llamaba nadie más que
        POST /api/admin/backfill-mtm. Sin hook, el valor no llegaba nunca."""
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda pk, si: {
            "2024-08": 250.0, "2024-09": 300.0, "2024-10": 275.0}
        cf_antes = [r["capital_final"] for r in self.conn.execute(
            "SELECT capital_final FROM monthly_entries WHERE user_id=? AND "
            "broker='global' ORDER BY year, month", (self.uid,))]
        r = main._reconstruir_mtm(self.uid)
        self.assertTrue(r["reconstruida"])
        self.assertEqual(r["snapshots"], 3)
        self.assertAlmostEqual(r["cobertura_media"], 1.0, places=3)
        cf_despues = [r2["capital_final"] for r2 in self.conn.execute(
            "SELECT capital_final FROM monthly_entries WHERE user_id=? AND "
            "broker='global' ORDER BY year, month", (self.uid,))]
        self.assertEqual(cf_antes, cf_despues)
        cv = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(cv["twr"], 0.10, places=6)

    def test_el_hook_no_corre_dentro_del_request(self):
        """`_fetch_monthly_close` sale a yfinance con timeout=8 POR TICKER: si eso
        colgara del POST de confirmación, una cartera de 20 símbolos dejaría al
        usuario esperando minutos. El disparo tiene que ser un thread."""
        import inspect
        src = inspect.getsource(main._reconstruir_mtm_post_import)
        self.assertIn("Thread", src)
        self.assertIn("daemon=True", src)

    def test_una_cuenta_sin_import_no_se_reconstruye(self):
        self.conn.execute("UPDATE import_batches SET status='reverted' WHERE user_id=?",
                          (self.uid,))
        self.conn.commit()
        r = main._reconstruir_mtm(self.uid)
        self.assertFalse(r["reconstruida"])
        self.assertIn("import", (r.get("motivo") or ""))


if __name__ == "__main__":
    unittest.main()
