"""Tests del backfill de valuación histórica a mercado (scripts/backfill_historical_mtm.py).

Mockea el fetch de precios históricos (sin red). Verifica: el unrealized se suma a
capital_final, los snapshots reflejan el MTM, idempotencia, fallback al costo cuando
no hay precio, y skip de cuentas sin import.
"""
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import scripts.backfill_historical_mtm as bf


class HistMtmTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("monthly_entries", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "brokers", "users", "snapshots", "positions",
                  "fx_rates_daily", "config"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("hmtm@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "IBKR", "USDT"))
        bid = "batchH"
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, broker, parser_format, file_hash, status) "
            "VALUES (?,?,?,?,?,?)", (bid, self.uid, "IBKR", "generic", "h1", "confirmed"))
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status) VALUES (?,?,?,?)",
            (bid, 0, "{}", "valid")).lastrowid
        # Compra AAPL 10 @ 200 (gross 2000) el 2024-08-15 → tenencia abierta.
        self.conn.execute(
            """INSERT INTO import_normalized_tx
                  (batch_id, raw_row_id, date, broker, operation_type, asset_symbol,
                   asset_type, quantity, unit_price, gross_amount, currency)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (bid, rr, "2024-08-15", "IBKR", "BUY", "AAPL", "STOCK_US", 10, 200, 2000, "USD"))
        # monthly_entries cost-based (pnl_unrealized=0): ago y sep 2024, global + IBKR.
        for (y, mo, ci, dep, cf) in [(2024, 8, 0, 2000, 2000), (2024, 9, 2000, 0, 2000)]:
            for b in ("global", "IBKR"):
                self.conn.execute(
                    """INSERT INTO monthly_entries
                          (user_id, year, month, broker, capital_inicio, capital_final,
                           deposits, withdrawals, pnl_realized, pnl_unrealized)
                       VALUES (?,?,?,?,?,?,?,0,0,0)""",
                    (self.uid, y, mo, b, ci, cf, dep))
        self.conn.commit()
        bf._HIST_CACHE.clear()

    def tearDown(self):
        self.conn.close()

    def _mock_prices(self, mapping):
        bf._fetch_monthly_close = lambda pk, start: (mapping if pk == "AAPL" else {})

    def test_unrealized_added_to_capital_final(self):
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        s = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.assertFalse(s["skipped"])
        cf = {m["ym"]: m["after"] for m in s["months"]}
        self.assertAlmostEqual(cf["2024-08"], 2500.0, places=1)   # 2000 + (250-200)*10
        self.assertAlmostEqual(cf["2024-09"], 2750.0, places=1)   # 2000 + (275-200)*10

    def test_snapshots_reflect_mtm(self):
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        snap = {r["date"][:7]: r["total_value"] for r in self.conn.execute(
            "SELECT date, total_value FROM snapshots WHERE user_id=?", (self.uid,))}
        self.assertAlmostEqual(snap["2024-08"], 2500.0, places=1)
        self.assertAlmostEqual(snap["2024-09"], 2750.0, places=1)

    def _snap(self, ym):
        """El valor RECONSTRUIDO vive en snapshots, no en monthly_entries: ahi lo
        recomputaria al costo `_repair_monthly_chain` (main.py:9314-9318)."""
        y, m = (int(x) for x in ym.split("-"))
        import calendar as _c
        d = f"{y}-{m:02d}-{_c.monthrange(y, m)[1]:02d}"
        r = self.conn.execute(
            "SELECT total_value, source, mtm_coverage FROM snapshots WHERE user_id=? AND date=?",
            (self.uid, d)).fetchone()
        return r

    def test_idempotent(self):
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))  # 2da corrida
        self.assertAlmostEqual(self._snap("2024-08")["total_value"], 2500.0, places=1)

    def test_no_price_falls_back_to_cost(self):
        self._mock_prices({})   # sin precio histórico → costo
        s = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        cf = {m["ym"]: m["after"] for m in s["months"]}
        self.assertAlmostEqual(cf["2024-08"], 2000.0, places=1)   # queda al costo, NO infla
        self.assertGreaterEqual(s["cost_fallbacks"], 1)

    def test_skip_account_without_import(self):
        self.conn.execute("UPDATE import_batches SET status='reverted' WHERE user_id=?", (self.uid,))
        s = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.assertTrue(s["skipped"])

    def test_guard_valor_negativo_cae_a_costo(self):
        # EL BUG DEL MTM (#417: 485→-592.944): compute_broker_value_usd puede
        # devolver un valor NEGATIVO (cross-currency mal valuado) y su trustMktValue
        # NO lo atrapa (trusta value≤0). Nuestro guard sí → cae al costo, no mete
        # un capital_final negativo gigante. Mockeamos el valor negativo directo.
        self._mock_prices({"2024-08": 250.0, "2024-09": 250.0})
        orig = bf.sj.compute_broker_value_usd
        bf.sj.compute_broker_value_usd = lambda *a, **k: {"value": -50000.0, "invested": 2000.0}
        try:
            s = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        finally:
            bf.sj.compute_broker_value_usd = orig
        cf = {m["ym"]: m["after"] for m in s["months"]}
        self.assertAlmostEqual(cf["2024-08"], 2000.0, places=1)   # costo, NO -50000
        self.assertAlmostEqual(cf["2024-09"], 2000.0, places=1)
        self.assertGreaterEqual(s["cost_fallbacks"], 1)

    def test_guard_valor_negativo_con_costo_CERO(self):
        # EL HUECO que dejó pasar #417 en la 1ra versión: un free lot (invested=0)
        # con valor de mercado negativo. El guard `if inv>0` lo salteaba → el negativo
        # se colaba. Ahora `val<0` se chequea SIEMPRE → cae al costo.
        self._mock_prices({"2024-08": 250.0, "2024-09": 250.0})
        orig = bf.sj.compute_broker_value_usd
        bf.sj.compute_broker_value_usd = lambda *a, **k: {"value": -90000.0, "invested": 0.0}
        try:
            s = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        finally:
            bf.sj.compute_broker_value_usd = orig
        cf = {m["ym"]: m["after"] for m in s["months"]}
        self.assertAlmostEqual(cf["2024-08"], 2000.0, places=1)   # costo, NO -90000
        self.assertGreaterEqual(cf["2024-08"], 0.0)               # nunca negativo

    def test_precio_absurdo_alto_no_infla(self):
        # Precio per-100 (AAPL ×100) → compute_broker_value_usd ya lo degrada a costo
        # (su trustMktValue agarra el over-distortion). Verificamos que no infla.
        self._mock_prices({"2024-08": 25000.0, "2024-09": 25000.0})
        s = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        cf = {m["ym"]: m["after"] for m in s["months"]}
        self.assertAlmostEqual(cf["2024-08"], 2000.0, places=1)   # NO 250.000

    def test_guard_no_toca_ganancias_reales(self):
        # Una ganancia razonable (250 vs 200 = +25%) SÍ se confía (no la degrada).
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        s = bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        cf = {m["ym"]: m["after"] for m in s["months"]}
        self.assertAlmostEqual(cf["2024-08"], 2500.0, places=1)   # MTM real, sin degradar

    def test_current_month_untouched(self):
        # Un mes = el mes en curso no se debe tocar.
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker, capital_inicio,
                   capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized)
               VALUES (?,?,?,'global',5000,5000,0,0,0,0)""",
            (self.uid, 2026, 6))
        self._mock_prices({"2024-08": 250.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        cf = self.conn.execute(
            "SELECT capital_final FROM monthly_entries WHERE user_id=? AND broker='global' AND year=2026 AND month=6",
            (self.uid,)).fetchone()["capital_final"]
        self.assertAlmostEqual(cf, 5000.0, places=1)   # mes en curso intacto

    def test_costo_negativo_el_mtm_no_lo_empeora(self):
        # #791: cuenta con costo YA negativo (corrupción vieja de pnl_realized). El
        # unrealized del MTM (acá una depreciación legítima, confiada por el guard) lo
        # haría MÁS negativo. El clamp lo frena: max(costo, resultado) → nos quedamos en
        # el costo (el menos negativo), nunca peor. Sin esto era -8000 → -9000.
        self.conn.execute(
            "UPDATE monthly_entries SET pnl_realized=-10000 WHERE user_id=? AND year=2024 AND month=8",
            (self.uid,))                                    # cost = 0+2000-0-10000 = -8000
        self.conn.commit()
        self._mock_prices({"2024-08": 100.0, "2024-09": 100.0})
        orig = bf.sj.compute_broker_value_usd
        bf.sj.compute_broker_value_usd = lambda *a, **k: {"value": 1000.0, "invested": 2000.0}  # u=-1000
        try:
            bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        finally:
            bf.sj.compute_broker_value_usd = orig
        self.assertAlmostEqual(self._snap("2024-08")["total_value"], -8000.0, places=1)

    def test_costo_negativo_pero_mejora_se_respeta(self):
        # El otro lado del clamp: si el costo es negativo PERO el unrealized lo MEJORA
        # (lo acerca a 0), respetamos la mejora — no lo forzamos de vuelta al costo.
        # Esto es lo que el `if cost<0: =cost` plano hubiera roto; el max() lo preserva.
        self.conn.execute(
            "UPDATE monthly_entries SET pnl_realized=-10000 WHERE user_id=? AND year=2024 AND month=8",
            (self.uid,))                                    # cost = -8000
        self.conn.commit()
        self._mock_prices({"2024-08": 500.0, "2024-09": 500.0})
        orig = bf.sj.compute_broker_value_usd
        bf.sj.compute_broker_value_usd = lambda *a, **k: {"value": 5000.0, "invested": 2000.0}  # u=+3000
        try:
            bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        finally:
            bf.sj.compute_broker_value_usd = orig
        self.assertAlmostEqual(self._snap("2024-08")["total_value"], -5000.0, places=1)

    def test_clamp_costo_positivo_no_flipea_a_negativo(self):
        # Caso #417 a nivel clamp: aunque el guard CONFÍE un unrealized negativo grande
        # (val/inv dentro de banda), el clamp no deja que un costo positivo termine
        # negativo → al costo. cost=2000; val=10/inv=3000 → mult≈0.0033 (confiado) →
        # u=-2990 → -990 < 0 → max(2000,-990) = 2000.
        self._mock_prices({"2024-08": 1.0, "2024-09": 1.0})
        orig = bf.sj.compute_broker_value_usd
        bf.sj.compute_broker_value_usd = lambda *a, **k: {"value": 10.0, "invested": 3000.0}  # u=-2990
        try:
            bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        finally:
            bf.sj.compute_broker_value_usd = orig
        cf = self._snap("2024-08")["total_value"]
        self.assertAlmostEqual(cf, 2000.0, places=1)        # costo, NO -990
        self.assertGreaterEqual(cf, 0.0)

    # ── Los tres defectos de plomeria que tenian la reconstruccion desconectada ──

    def test_source_propio_no_disfrazado_de_import(self):
        """Defecto 1: persistia via `_backfill_snapshots_from_monthly`, que estampa
        source='import' (persister.py:1290) → el trabajo a mercado salia disfrazado
        de contable y cualquier filtro por `source` lo descartaba."""
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        r = self._snap("2024-08")
        self.assertEqual(r["source"], bf.MTM_SOURCE)
        self.assertNotEqual(r["source"], "import")

    def test_pisa_la_foto_sintetica_que_dejo_el_import(self):
        """Defecto 2: `ON CONFLICT DO NOTHING` (persister.py:1291) → reconstruir no
        pisaba ni la fila sintetica del propio import, asi que el grafico seguia
        mostrando exactamente lo mismo que antes."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,?,?,?,?,'import')",
            (self.uid, "2024-08-31", 2000.0, 2000.0, 2000.0))
        self.conn.commit()
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        r = self._snap("2024-08")
        self.assertAlmostEqual(r["total_value"], 2500.0, places=1)   # pisada, no ignorada
        self.assertEqual(r["source"], bf.MTM_SOURCE)

    def test_no_pisa_una_medicion_real_del_cron(self):
        """El limite de lo anterior: una foto REAL del cron manda sobre cualquier
        reconstruccion. El criterio no se reescribe: lo decide twr.clasificar_fila."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,?,'cron',?,?)",
            (self.uid, "2024-08-31", 1234.5, 2000.0, 2000.0, 1000.0, '[]'))
        self.conn.commit()
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        r = self._snap("2024-08")
        self.assertAlmostEqual(r["total_value"], 1234.5, places=1)
        self.assertEqual(r["source"], "cron")

    def test_sobrevive_a_repair_monthly_chain(self):
        """Defecto 3 — EL que hacia que la reconstruccion se autodestruyera.
        `_repair_monthly_chain` (main.py:9314-9318) recomputa capital_final al costo
        para todo mes cerrado, y se dispara desde ~20 lugares de main.py. Mientras el
        ancla vivia en monthly_entries, la siguiente alta de una operacion la borraba.
        Ahora vive en snapshots y la corrida no la toca."""
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        antes = self._snap("2024-08")["total_value"]
        self.assertAlmostEqual(antes, 2500.0, places=1)
        main._repair_monthly_chain(self.conn, self.uid, "global")
        main._repair_monthly_chain(self.conn, self.uid, "IBKR")
        self.conn.commit()
        self.assertAlmostEqual(self._snap("2024-08")["total_value"], antes, places=1)

    def test_cobertura_estampada_y_degradada_cuando_cae_al_costo(self):
        """Sin cobertura, un mes mayormente al costo se presenta como medido — que es
        cambiar una mentira etiquetada por una sin etiquetar."""
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.assertAlmostEqual(self._snap("2024-08")["mtm_coverage"], 1.0, places=3)
        # Sin precio historico: todo cae al costo → cobertura 0.
        for t in ("snapshots",):
            self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
        self.conn.commit()
        self._mock_prices({})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        self.assertAlmostEqual(self._snap("2024-08")["mtm_coverage"], 0.0, places=3)

    def test_no_escribe_en_monthly_entries(self):
        """La contabilidad queda intacta: la reconstruccion es una MEDICION, no un
        asiento. Mezclarlas es lo que fabricaba el fantasma."""
        cf_antes = self.conn.execute(
            "SELECT capital_final FROM monthly_entries WHERE user_id=? AND "
            "broker='global' AND year=2024 AND month=8", (self.uid,)).fetchone()["capital_final"]
        self._mock_prices({"2024-08": 250.0, "2024-09": 275.0})
        bf.backfill_user(self.conn, self.uid, date(2026, 6, 26))
        cf_despues = self.conn.execute(
            "SELECT capital_final FROM monthly_entries WHERE user_id=? AND "
            "broker='global' AND year=2024 AND month=8", (self.uid,)).fetchone()["capital_final"]
        self.assertAlmostEqual(cf_antes, cf_despues, places=4)


if __name__ == "__main__":
    unittest.main()
