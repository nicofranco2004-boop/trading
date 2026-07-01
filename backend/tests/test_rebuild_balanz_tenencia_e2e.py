"""E2E Balanz: la FOTO (Resumen de Cuenta) aplicada en modo OVERRIDE sobre el
estado reconstruido, con el pipeline REAL + rebuild, sobre una DB temporal.

A diferencia de las otras fotos (gap-fill: sólo completan huecos), Balanz PISA el
estado: además de seedear lo que falta, REDUCE lo que Rendi tiene de más y ELIMINA
lo que la foto no lista. Este test valida las 4 ramas + las invariantes críticas
del override (el wizard lo aplica SIN checkpoint del usuario):
  • to_seed  (foto > rendi)          → COMPRA del hueco (P&L 0);
  • matched  (foto == rendi)          → intacto (no duplica ni toca);
  • over     (foto < rendi)           → VENTA de la diferencia a COSTO (P&L 0, sin cash);
  • not_in_snapshot (rendi, no foto)  → VENTA total a COSTO (P&L 0, sin cash);
  • el override SOBREVIVE el rebuild (transfer_out persistido, no re-derivado);
  • NO inyecta P&L fantasma (las reducciones cierran a costo);
  • NO agrega cash (transfer_out proceeds 0) → el cash lo fija el true-up con la foto;
  • re-subir la MISMA foto es idempotente (nada que ajustar);
  • el cap de sanidad frena un parse roto (no vacía la cartera).

Corre con: cd backend && python3 -m pytest tests/test_rebuild_balanz_tenencia_e2e.py
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
from importing import tenencia as tn
import main


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


def _H(tk, at, qty, price):
    return tn.Holding(ticker=tk, asset_type=at, quantity=qty, value=qty * price,
                      currency="ARS", price_per1=price)


class BalanzFotoOverrideE2E(unittest.TestCase):
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
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("balanz_e2e@rendi.test", "x"))
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

    # "Movimientos": persistimos un batch de BUY/DEPOSITO ya armados (lotes
    # import-linked → _is_safe_to_rebuild True), + confirm + rebuild.
    def _import_mov(self, txs):
        with self.conn:
            for i, t in enumerate(txs):
                t.row_index = -100 - i
            sid = pl.store_preview_txs(
                self.conn, self.uid, broker=self.BROKER, parser_format="balanz_movimientos",
                file_name="mov.xlsx", txs=txs)
            txs2, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs2,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
        return sid

    # FOTO Balanz: réplica EXACTA de la rama aggregated + override del endpoint
    # import_tenencia_preview (guardas incluidas).
    def _import_foto(self, snap):
        from importing.persister import broker_pair
        from importing.rebuild import _is_safe_to_rebuild
        seed_date = snap.date or "2026-07-01"
        with self.conn:
            pair = broker_pair(self.conn, self.uid, self.BROKER)
            pair_l = list(pair)
            ph = ",".join("?" * len(pair))
            current, invested = {}, {}
            for r in self.conn.execute(
                f"SELECT asset, SUM(quantity) q, SUM(invested) inv FROM positions "
                f"WHERE user_id=? AND is_cash=0 AND broker IN ({ph}) GROUP BY asset",
                (self.uid, *pair)):
                current[r["asset"]] = current.get(r["asset"], 0.0) + (r["q"] or 0)
                invested[r["asset"]] = invested.get(r["asset"], 0.0) + (r["inv"] or 0)
            rec = tn.compute_reconcile(current, snap)

            # guardas del override (idénticas al endpoint)
            sibling_assets = set()
            sibs = [b for b in pair_l if b != self.BROKER]
            if sibs:
                sph = ",".join("?" * len(sibs))
                for r in self.conn.execute(
                    f"SELECT DISTINCT asset FROM positions "
                    f"WHERE user_id=? AND is_cash=0 AND broker IN ({sph})",
                    (self.uid, *sibs)):
                    sibling_assets.add(r["asset"])

            def _reducible(tk):
                return _is_safe_to_rebuild(self.conn, self.uid, pair_l, tk) and tk not in sibling_assets

            safe_over, safe_nis, unsafe = [], [], []
            for tk, rq, sq in rec.over:
                (safe_over.append((tk, rq, sq)) if _reducible(tk) else unsafe.append(tk))
            for tk, rq in rec.not_in_snapshot:
                (safe_nis.append((tk, rq)) if _reducible(tk) else unsafe.append(tk))
            total_inv = sum(abs(v) for tk, v in invested.items()
                            if tk not in sibling_assets) or 0.0
            cut = sum(abs(invested.get(tk, 0.0)) for tk, _ in safe_nis)
            cut += sum(abs(invested.get(tk, 0.0)) * ((rq - sq) / rq if rq else 0)
                       for tk, rq, sq in safe_over)
            n_current = len(current)
            n_cut = len(safe_over) + len(safe_nis)
            capped = (total_inv > 0 and cut > 0.5 * total_inv) \
                or (n_current > 0 and n_cut > 0.5 * n_current)
            if capped:
                rec.over, rec.not_in_snapshot = [], []
            else:
                rec.over, rec.not_in_snapshot = safe_over, safe_nis
            self.last_capped = capped

            mx = self.conn.execute(
                f"SELECT MAX(n.date) d FROM import_normalized_tx n "
                f"JOIN import_batches b ON b.id=n.batch_id "
                f"WHERE b.user_id=? AND b.status='confirmed' AND n.broker IN ({ph}) "
                f"AND n.operation_type IN ('BUY','SELL')",
                (self.uid, *pair)).fetchone()
            red_date = max(seed_date, mx["d"]) if mx and mx["d"] else seed_date
            seed_txs = tn.build_tenencia_seed_txs(
                self.BROKER, rec, seed_date, override=True, complete=True, override_date=red_date)

            # cash true-up (ARS en el padre)
            def _cur_cash(bname):
                row = self.conn.execute(
                    "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                    (self.uid, bname)).fetchone()
                return float(row["invested"] or 0) if row else 0.0
            adj = []
            if snap.cash_ars is not None:
                adj.append((self.BROKER, "ARS", _cur_cash(self.BROKER), snap.cash_ars, 1.0))
            cash_txs, _ = tn.build_cash_trueup_txs(adj, seed_date)
            seed_txs += cash_txs
            for i, t in enumerate(seed_txs):
                t.row_index = -20000 - i
            if not seed_txs:
                return None
            # fund_price_overrides (espejo del /preview): FCI que Rendi no cotiza →
            # guardamos el precio de la foto en moneda nativa para price_override.
            import json as _json
            pair = ps.broker_pair(self.conn, self.uid, self.BROKER)
            php = ",".join("?" * len(pair))
            fpo = []
            for h in snap.holdings:
                if (h.asset_type or "").upper() != "FUND" or not h.price_per1:
                    continue
                for prow in self.conn.execute(
                    f"SELECT DISTINCT broker,currency FROM positions WHERE user_id=? AND is_cash=0 "
                    f"AND broker IN ({php}) AND asset=? AND UPPER(asset_type)='FUND' AND asset NOT LIKE 'FCI:%'",
                    (self.uid, *pair, h.ticker)):
                    is_usd = (prow["broker"] != self.BROKER) or (prow["currency"] or "").upper() in ("USD", "USDT")
                    if is_usd:
                        if not snap.fx_mep:
                            continue
                        po = round(h.price_per1 / snap.fx_mep, 8)
                    else:
                        po = round(h.price_per1, 6)
                    fpo.append({"asset": h.ticker, "broker": prow["broker"], "po": po})
            sid = pl.store_preview_txs(
                self.conn, self.uid, broker=self.BROKER, parser_format="balanz_tenencia",
                file_name="resumen.pdf", txs=seed_txs)
            if fpo:
                self.conn.execute("UPDATE import_batches SET fund_price_overrides=? WHERE id=?",
                                  (_json.dumps(fpo), sid))
            txs2, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs2,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
            # aplicar (espejo de import_confirm, DESPUÉS del rebuild)
            brow = self.conn.execute(
                "SELECT fund_price_overrides FROM import_batches WHERE id=?", (sid,)).fetchone()
            if brow and brow["fund_price_overrides"]:
                for o in _json.loads(brow["fund_price_overrides"]):
                    self.conn.execute(
                        "UPDATE positions SET price_override=? WHERE user_id=? AND broker=? "
                        "AND asset=? AND is_cash=0 AND UPPER(asset_type)='FUND'",
                        (o["po"], self.uid, o["broker"], o["asset"]))
        return sid

    def _held(self, asset):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions "
            "WHERE user_id=? AND asset=? AND is_cash=0", (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def _cash(self, broker):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) v FROM positions "
            "WHERE user_id=? AND broker=? AND is_cash=1", (self.uid, broker)).fetchone()
        return float(r["v"] or 0)

    def _sell_pnl(self, asset):
        return [float(r["pnl_usd"] or 0) for r in self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND asset=? AND op_type='Venta'",
            (self.uid, asset))]

    def _mk_mov(self):
        from importing.schema import NormalizedTx, OP_BUY, OP_DEPOSIT
        return [
            NormalizedTx(row_index=0, date="2026-06-01", broker=self.BROKER,
                         operation_type=OP_DEPOSIT, gross_amount=5_000_000, currency="ARS"),
            # SPY: rendi 70 → foto 63 (over, reduce 7)
            NormalizedTx(row_index=0, date="2026-06-02", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="SPY", asset_type="CEDEAR", quantity=70, unit_price=19000,
                         gross_amount=70 * 19000, currency="ARS"),
            # GGAL: rendi 10 → foto no lista (not_in_snapshot, remove)
            NormalizedTx(row_index=0, date="2026-06-03", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="GGAL", asset_type="STOCK", quantity=10, unit_price=5000,
                         gross_amount=10 * 5000, currency="ARS"),
            # AAPL: rendi 1 → foto 3 (to_seed +2)
            NormalizedTx(row_index=0, date="2026-06-04", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="AAPL", asset_type="CEDEAR", quantity=1, unit_price=23000,
                         gross_amount=23000, currency="ARS"),
            # YPFD: rendi 14 → foto 14 (matched)
            NormalizedTx(row_index=0, date="2026-06-05", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="YPFD", asset_type="STOCK", quantity=14, unit_price=60000,
                         gross_amount=14 * 60000, currency="ARS"),
        ]

    def _mk_foto(self):
        snap = tn.TenenciaSnapshot(date="2026-07-01")
        snap.holdings = [
            _H("SPY", "CEDEAR", 63, 19630),
            _H("AAPL", "CEDEAR", 3, 23140),
            _H("YPFD", "STOCK", 14, 69550),
        ]
        snap.cash_ars = 837.14
        snap.cash_usd = 0.65
        return snap

    def _po(self, asset):
        return [r["price_override"] for r in self.conn.execute(
            "SELECT DISTINCT price_override FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset))]

    # ── Tests ────────────────────────────────────────────────────────────────
    def test_fci_override_fija_valor_de_foto(self):
        # Los FCI que Rendi NO cotiza en vivo se valuaban a COSTO y diferían del
        # Resumen. La foto ahora estampa price_override con el precio-por-cuotaparte
        # (en moneda nativa) → muestran el valor de Balanz. CEDEARs/acciones intactos.
        from importing.schema import NormalizedTx, OP_BUY, OP_DEPOSIT
        _parent = self.conn.execute("SELECT * FROM brokers WHERE user_id=? AND name=?",
                                    (self.uid, self.BROKER)).fetchone()
        main._ensure_usd_sibling(self.conn, self.uid, _parent)   # 'Balanz · USD' con parent_broker_id
        self.conn.commit()
        mov = [
            NormalizedTx(row_index=0, date="2026-06-01", broker=self.BROKER,
                         operation_type=OP_DEPOSIT, gross_amount=5_000_000, currency="ARS"),
            # FCI ARS money-market: costo 200/cp, la foto lo valúa 210/cp
            NormalizedTx(row_index=0, date="2026-06-02", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="BMMA", asset_type="FUND", quantity=1000, unit_price=200,
                         gross_amount=200000, currency="ARS"),
            NormalizedTx(row_index=0, date="2026-06-03", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="AAPL", asset_type="CEDEAR", quantity=1, unit_price=23000,
                         gross_amount=23000, currency="ARS"),
            # FCI USD (sibling): costo 5 USD/cp, la foto lo valúa 0.5 pesos/cp (casi cero)
            NormalizedTx(row_index=0, date="2026-06-04", broker="Balanz · USD",
                         operation_type=OP_DEPOSIT, gross_amount=1000, currency="USD"),
            NormalizedTx(row_index=0, date="2026-06-05", broker="Balanz · USD", operation_type=OP_BUY,
                         asset_symbol="BDOLA", asset_type="FUND", quantity=100, unit_price=5,
                         gross_amount=500, currency="USD"),
        ]
        self._import_mov(mov)
        snap = tn.TenenciaSnapshot(date="2026-07-01")
        snap.fx_mep = 1000.0
        snap.holdings = [
            _H("BMMA", "FUND", 1000, 210),     # ARS → override = 210
            _H("AAPL", "CEDEAR", 1, 23000),    # control → sin override
            _H("BDOLA", "FUND", 100, 0.5),     # USD → override = 0.5/mep = 0.0005
        ]
        snap.cash_ars = 837.14
        self._import_foto(snap)
        self.assertAlmostEqual(self._po("BMMA")[0], 210.0, places=4)
        self.assertAlmostEqual(self._po("BDOLA")[0], 0.0005, places=8)   # 0.5 / 1000 (MEP)
        self.assertEqual(self._po("AAPL"), [None])   # CEDEAR sigue el precio en vivo

    def test_backfill_reaplica_y_revert_limpia_fci_override(self):
        # El rebuild pone price_override=None; el backfill (que re-rebuildea) debe
        # RE-APLICAR el precio de la foto. Y el revert de la foto debe LIMPIARLO.
        from importing import recompute_backfill as rcb
        import json as _json
        self.conn.execute(
            "INSERT INTO positions (user_id,broker,asset,is_cash,buy_price,quantity,invested,currency,asset_type) "
            "VALUES (?,?,?,0,?,?,?,?,?)", (self.uid, "Balanz", "BMMA", 200, 1000, 200000, "ARS", "FUND"))
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status,fund_price_overrides) "
            "VALUES (?,?,?,?,?,?,?)",
            ("b1", self.uid, "Balanz", "balanz_tenencia", "h1", "confirmed",
             _json.dumps([{"asset": "BMMA", "broker": "Balanz", "po": 210.0}])))
        self.conn.commit()
        # post-rebuild deja override=None → el re-apply del backfill lo restaura
        self.conn.execute("UPDATE positions SET price_override=NULL WHERE user_id=? AND asset='BMMA'", (self.uid,))
        with self.conn:
            rcb._reapply_fund_overrides(self.conn, self.uid)
        self.assertAlmostEqual(self._po("BMMA")[0], 210.0, places=4)
        # revert: batch a 'reverted' + limpiar + re-aplicar los que sigan confirmados (ninguno) → None
        self.conn.execute("UPDATE import_batches SET status='reverted' WHERE id='b1'")
        self.conn.execute("UPDATE positions SET price_override=NULL WHERE user_id=? AND asset='BMMA'", (self.uid,))
        with self.conn:
            rcb._reapply_fund_overrides(self.conn, self.uid)
        self.assertEqual(self._po("BMMA"), [None])   # la foto revertida ya no aplica

    def test_override_pisa_estado_exacto(self):
        self._import_mov(self._mk_mov())
        self.assertAlmostEqual(self._held("SPY"), 70.0, places=6)
        self.assertAlmostEqual(self._held("GGAL"), 10.0, places=6)
        self.assertAlmostEqual(self._held("AAPL"), 1.0, places=6)

        self._import_foto(self._mk_foto())
        self.assertFalse(getattr(self, "last_capped", False))
        # Cada activo EXACTO a la foto (las 4 ramas):
        self.assertAlmostEqual(self._held("SPY"), 63.0, places=6)    # over → reducido
        self.assertAlmostEqual(self._held("GGAL"), 0.0, places=6)    # not_in_snapshot → eliminado
        self.assertAlmostEqual(self._held("AAPL"), 3.0, places=6)    # to_seed → completado
        self.assertAlmostEqual(self._held("YPFD"), 14.0, places=6)   # matched → intacto

    def test_override_no_inyecta_pnl_fantasma(self):
        self._import_mov(self._mk_mov())
        self._import_foto(self._mk_foto())
        # Las VENTAS del override cierran a COSTO → P&L 0 (no ganancia/pérdida falsa).
        for tk in ("SPY", "GGAL"):
            pnls = self._sell_pnl(tk)
            self.assertTrue(pnls, f"esperaba una venta de override para {tk}")
            for p in pnls:
                self.assertAlmostEqual(p, 0.0, places=2, msg=f"{tk} bookeó P&L fantasma: {p}")

    def test_override_cash_igual_a_foto_sin_doble_conteo(self):
        self._import_mov(self._mk_mov())
        self._import_foto(self._mk_foto())
        # El cash queda EXACTO a la foto; las ventas del override no agregan proceeds
        # (transfer_out) → el true-up no doble-cuenta.
        self.assertAlmostEqual(self._cash("Balanz"), 837.14, places=2)

    def test_reupload_foto_es_idempotente(self):
        self._import_mov(self._mk_mov())
        self._import_foto(self._mk_foto())
        sid2 = self._import_foto(self._mk_foto())
        self.assertIsNone(sid2, "re-subir la MISMA foto no debe generar ajustes")
        self.assertAlmostEqual(self._held("SPY"), 63.0, places=6)
        self.assertAlmostEqual(self._held("GGAL"), 0.0, places=6)

    def test_override_no_reduce_activo_en_sibling_usd(self):
        # Un activo que vive en el sibling '· USD' (cross-currency) NO debe ser
        # reducido/eliminado por el override (guarda mismo-broker), aunque la foto
        # ARS no lo liste. Las reducciones same-currency del padre SÍ se aplican.
        from importing.schema import NormalizedTx, OP_BUY, OP_DEPOSIT
        _parent = self.conn.execute("SELECT * FROM brokers WHERE user_id=? AND name=?",
                                    (self.uid, self.BROKER)).fetchone()
        main._ensure_usd_sibling(self.conn, self.uid, _parent)   # linkeado por parent_broker_id
        self.conn.commit()
        mov = self._mk_mov() + [
            NormalizedTx(row_index=0, date="2026-06-06", broker="Balanz · USD",
                         operation_type=OP_DEPOSIT, gross_amount=1000, currency="USD"),
            NormalizedTx(row_index=0, date="2026-06-07", broker="Balanz · USD", operation_type=OP_BUY,
                         asset_symbol="NVDA", asset_type="CEDEAR", quantity=5, unit_price=100,
                         gross_amount=500, currency="USD"),
        ]
        self._import_mov(mov)
        self.assertAlmostEqual(self._held("NVDA"), 5.0, places=6)
        self._import_foto(self._mk_foto())
        self.assertFalse(getattr(self, "last_capped", False))
        self.assertAlmostEqual(self._held("NVDA"), 5.0, places=6)   # sibling → intacto
        self.assertAlmostEqual(self._held("SPY"), 63.0, places=6)   # padre → reducido
        self.assertAlmostEqual(self._held("GGAL"), 0.0, places=6)   # padre → eliminado

    def test_safe_revert_bloquea_override_con_ventas(self):
        # El batch de override trae VENTAS sintéticas → el revert SAFE lo bloquea
        # con mensaje claro (no corrompe). El nuclear (editar y rehacer) sí puede.
        self._import_mov(self._mk_mov())
        foto_sid = self._import_foto(self._mk_foto())
        with self.assertRaises(ps.PersistError):
            with self.conn:
                ps.revert_batch(self.conn, uid=self.uid, batch_id=foto_sid,
                                helpers=main._import_helpers, nuclear=False)

    def test_nuclear_revert_override_deja_estado_sano(self):
        # Nuclear revert del batch de override: NO corrompe (sin lotes negativos ni
        # huérfanos) y restaura el cash. LIMITACIÓN CONOCIDA (igual que cualquier
        # batch con ventas): el nuclear "acepta drift" → NO recrea los lotes que las
        # VENTAS de reducción consumieron (SPY queda 63, no vuelve a 70). El camino
        # SEGURO es el safe revert, que BLOQUEA (test de arriba); por eso el override
        # sólo se deshace re-importando, no revirtiéndolo a medias.
        self._import_mov(self._mk_mov())
        cash_before = self._cash("Balanz")
        foto_sid = self._import_foto(self._mk_foto())
        with self.conn:
            res = ps.revert_batch(self.conn, uid=self.uid, batch_id=foto_sid,
                                  helpers=main._import_helpers, nuclear=True)
        self.assertTrue(res.get("reverted"))
        # cash restaurado exacto (el ajuste de la foto se deshizo):
        self.assertAlmostEqual(self._cash("Balanz"), cash_before, places=2)
        # estado SANO: nada con cantidad negativa.
        neg = self.conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE user_id=? AND is_cash=0 AND quantity<0",
            (self.uid,)).fetchone()["n"]
        self.assertEqual(neg, 0)
        # el gap-fill (AAPL +2) sí se revierte → AAPL vuelve a 1 (no queda huérfano).
        self.assertAlmostEqual(self._held("AAPL"), 1.0, places=6)

    def test_override_reduce_aunque_foto_sea_mas_vieja_que_un_movimiento(self):
        # BUG (HIGH) del review: si la foto es MÁS VIEJA que un movimiento, la VENTA
        # de reducción fechada en la foto sortearía ANTES de la compra real → no
        # reduciría (fallo silencioso). El fix fecha la venta en max(foto, último
        # movimiento). Acá la foto es 2026-05-15 pero SPY se compró 2026-06-02.
        self._import_mov(self._mk_mov())
        snap = tn.TenenciaSnapshot(date="2026-05-15")   # más vieja que los movimientos
        # SPY reduce, GGAL elimina, AAPL/YPFD matched → 2 de 4 cambian (no dispara el cap).
        snap.holdings = [_H("SPY", "CEDEAR", 63, 19630), _H("AAPL", "CEDEAR", 1, 23140),
                         _H("YPFD", "STOCK", 14, 69550)]
        snap.cash_ars = 837.14
        self._import_foto(snap)
        self.assertFalse(getattr(self, "last_capped", False))
        self.assertAlmostEqual(self._held("SPY"), 63.0, places=6)   # reducido pese a foto vieja
        self.assertAlmostEqual(self._held("GGAL"), 0.0, places=6)   # eliminado
        # y la reducción no bookeó P&L fantasma
        for p in self._sell_pnl("SPY"):
            self.assertAlmostEqual(p, 0.0, places=2)

    def test_cap_por_cantidad_cuando_invested_es_cero(self):
        # BUG (MEDIUM) del review: si los lotes tienen invested=0 (seeds/transfer-in),
        # el cap por VALOR no protege (total_inv=0) → el cap por CANTIDAD sí frena un
        # parse roto que borraría casi todo.
        from importing.schema import NormalizedTx, OP_BUY, OP_DEPOSIT
        mov = [
            NormalizedTx(row_index=0, date="2026-06-01", broker=self.BROKER,
                         operation_type=OP_DEPOSIT, gross_amount=1000, currency="ARS"),
            NormalizedTx(row_index=0, date="2026-06-02", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="AAA", asset_type="STOCK", quantity=10, unit_price=0,
                         gross_amount=0, currency="ARS"),
            NormalizedTx(row_index=0, date="2026-06-03", broker=self.BROKER, operation_type=OP_BUY,
                         asset_symbol="BBB", asset_type="STOCK", quantity=5, unit_price=0,
                         gross_amount=0, currency="ARS"),
        ]
        self._import_mov(mov)
        broken = tn.TenenciaSnapshot(date="2026-07-01")
        broken.holdings = [_H("ZZZ", "STOCK", 1, 100)]   # no lista AAA ni BBB
        broken.cash_ars = 1000
        self._import_foto(broken)
        self.assertTrue(self.last_capped, "el cap por cantidad debía frenar el borrado")
        self.assertAlmostEqual(self._held("AAA"), 10.0, places=6)
        self.assertAlmostEqual(self._held("BBB"), 5.0, places=6)

    def test_cap_de_sanidad_frena_parse_roto(self):
        # Un "parse roto" devuelve casi nada → not_in_snapshot borraría >50% del valor
        # → el cap frena TODAS las reducciones (sólo gap-fill + cash), no vacía la cartera.
        self._import_mov(self._mk_mov())
        broken = tn.TenenciaSnapshot(date="2026-07-01")
        broken.holdings = [_H("AAPL", "CEDEAR", 1, 23140)]  # sólo 1 → borraría SPY/GGAL/YPFD
        broken.cash_ars = 837.14
        self._import_foto(broken)
        self.assertTrue(self.last_capped, "el cap debía dispararse")
        # NADA se redujo/eliminó (la cartera sigue intacta salvo cash):
        self.assertAlmostEqual(self._held("SPY"), 70.0, places=6)
        self.assertAlmostEqual(self._held("GGAL"), 10.0, places=6)
        self.assertAlmostEqual(self._held("YPFD"), 14.0, places=6)


if __name__ == "__main__":
    unittest.main()
