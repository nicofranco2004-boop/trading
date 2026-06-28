"""E2E PPI: Movimientos (VENTANA) + Estado de Cuenta (SEED de tenencia), con el
pipeline REAL + rebuild, sobre una DB temporal.

Caso sintético AUTO-CONSISTENTE (conocemos la verdad): la ventana de Movimientos
NO trae las posiciones de apertura (el usuario tenía 80 GGAL de antes + un bono
en dólares que la ventana no cubre); el Estado de Cuenta es la FOTO real y
completa SOLO el hueco. Valida lo que los archivos anonimizados no dejaban probar:
  • replay(Movimientos) + seed(Estado) == tenencia de la foto, exacto;
  • el cash cierra (cada depósito sintético financia sus compras → neto 0);
  • re-subir el MISMO Estado no duplica (reconcile da vacío);
  • el revert del batch del seed deshace EXACTO (valida el fix de row_index único
    entre las particiones ARS/USD — sin él, el revert borraba/orfanaba mal).

Corre con: cd backend && python3 -m pytest tests/test_rebuild_ppi_e2e.py
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


# ─── Movimientos PPI (VENTANA): depósito + compra de 20 GGAL. La apertura (80
# GGAL + 50 GD30 en dólares) quedó ANTES de la ventana → la trae el Estado. ────
PPI_MOV_HDR = "Fecha,Descripción,Cantidad,Precio,Importe,Saldo,Moneda,Especie,_hoja\n"
CSV_MOV = (PPI_MOV_HDR +
    "2026-06-01,Ingreso de Fondos,0,0,1000000,1000000,Pesos,,Pesos\n"
    "2026-06-02,COMPRA GGAL,20,7000,-140000,860000,Pesos,,Pesos\n"
).encode("utf-8")

_H8 = ['ESPECIE', 'DESCRIPCIÓN', 'CANT. DISPONIBLE', 'CANT. GARANTÍA', 'PRECIO',
       'VALOR MONEDA COTIZACIÓN', 'VALOR CORRIENTE', '% CARTERA']
# Estado de Cuenta (verdad a 2026-06-30): GGAL 100 (ARS) y GD30 50 (USD).
ESTADO_ROWS = [
    ['ESTADO DE CUENTA'],
    ['TITULAR', None, 'FECHA'],
    ['TEST USER', None, '30/06/2026'],
    ['COMITENTE'], ['999'],
    ['TOTAL CARTERA EXPRESADO EN PESOS $', None, 800000],
    ['POR TIPO DE ACTIVO'],
    ['MONEDAS'],
    ['MONEDA', 'DESCRIPCIÓN', 'CANT. DISPONIBLE', 'PRECIO', 'VALOR CORRIENTE', '% CARTERA'],
    ['$', 'Peso', 860000, 1, 860000, 0],
    ['SUBTOTAL', None, None, None, 860000, 0],
    ['ACCIONES'],
    _H8,
    ['GGAL', 'Grupo Galicia', 100, 0, 7000, 700000, 700000, 50],
    ['SUBTOTAL', None, None, None, None, None, 700000, 50],
    ['BONOS'],
    _H8,
    # USD: VALOR MONEDA COTIZACIÓN (100 USD) ≠ VALOR CORRIENTE (100000 ARS-equiv).
    ['GD30', 'Global 2030 USD', 50, 0, 2, 100, 100000, 10],
    ['SUBTOTAL', None, None, None, None, None, 100000, 10],
]


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


class PpiEstadoE2E(unittest.TestCase):
    BROKER = "PPI"

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
            ("ppi_e2e@rendi.test", "x"))
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

    # Movimientos: pipeline real, igual que en producción.
    def _import_mov(self, csv_bytes):
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="mov.csv",
                broker_hint=self.BROKER, parser_format="ppi")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
        return sid

    # Estado de Cuenta: replica EXACTA de la rama PPI del endpoint tenencia/preview.
    def _import_estado(self, rows):
        snap = tn.parse_ppi_tenencia(rows)
        seed_date = snap.date or "2026-06-30"
        with self.conn:
            usd_broker = self.BROKER
            if any(h.currency == "USD" for h in snap.holdings):
                parent = self.conn.execute(
                    "SELECT * FROM brokers WHERE user_id=? AND name=?", (self.uid, self.BROKER)).fetchone()
                usd_broker = main._ensure_usd_sibling(self.conn, self.uid, parent)["name"]

            def _cur_qty(bname):
                d = {}
                for r in self.conn.execute(
                    "SELECT asset, SUM(quantity) q FROM positions "
                    "WHERE user_id=? AND is_cash=0 AND broker=? GROUP BY asset",
                    (self.uid, bname)):
                    d[r["asset"]] = (r["q"] or 0)
                return d

            seed_txs = []
            for ccy in ("ARS", "USD"):
                hs = [h for h in snap.holdings if h.currency == ccy]
                if not hs:
                    continue
                sub = self.BROKER if ccy == "ARS" else usd_broker
                r1 = tn.compute_reconcile(_cur_qty(sub), tn.TenenciaSnapshot(holdings=hs, date=snap.date))
                seed_txs += tn.build_tenencia_seed_txs(sub, r1, seed_date, currency=ccy)
            for i, t in enumerate(seed_txs):
                t.row_index = -20000 - i
            # fix #1: row_index únicos entre particiones (sino el confirm colapsa el mapa)
            assert len({t.row_index for t in seed_txs}) == len(seed_txs)
            if not seed_txs:
                return None
            sid = pl.store_preview_txs(
                self.conn, self.uid, broker=self.BROKER, parser_format="ppi_tenencia",
                file_name="estado.xlsx", txs=seed_txs)
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
        return sid

    def _held(self, asset, broker=None):
        if broker:
            r = self.conn.execute(
                "SELECT COALESCE(SUM(quantity),0) q FROM positions "
                "WHERE user_id=? AND asset=? AND broker=? AND is_cash=0",
                (self.uid, asset, broker)).fetchone()
        else:
            r = self.conn.execute(
                "SELECT COALESCE(SUM(quantity),0) q FROM positions "
                "WHERE user_id=? AND asset=? AND is_cash=0", (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def _cash(self, broker):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) v FROM positions "
            "WHERE user_id=? AND broker=? AND is_cash=1", (self.uid, broker)).fetchone()
        return float(r["v"] or 0)

    def _pos_rows(self, asset):
        return self.conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
            (self.uid, asset)).fetchone()["n"]

    # ── Tests ────────────────────────────────────────────────────────────────
    def test_windowed_mov_plus_estado_equals_truth(self):
        # 1) Movimientos (ventana) → solo 20 GGAL; el bono dólar no aparece.
        self._import_mov(CSV_MOV)
        self.assertAlmostEqual(self._held("GGAL"), 20.0, places=6)
        self.assertAlmostEqual(self._held("GD30"), 0.0, places=6)
        self.assertAlmostEqual(self._cash("PPI"), 860000.0, places=2)

        # 2) Estado de Cuenta (foto) → completa el hueco (80 GGAL + 50 GD30 USD).
        self._import_estado(ESTADO_ROWS)
        # replay + seed == tenencia de la foto:
        self.assertAlmostEqual(self._held("GGAL"), 100.0, places=6)
        self.assertAlmostEqual(self._held("GD30"), 50.0, places=6)
        # el bono dólar quedó en el sibling '· USD' (no en el padre ARS):
        self.assertAlmostEqual(self._held("GD30", broker="PPI · USD"), 50.0, places=6)
        self.assertAlmostEqual(self._held("GD30", broker="PPI"), 0.0, places=6)
        # cash cierra: el depósito sintético financia las compras del seed → neto 0
        # sobre el ARS del padre (sigue 860k); el USD del sibling neteó a 0.
        self.assertAlmostEqual(self._cash("PPI"), 860000.0, places=2)
        self.assertAlmostEqual(self._cash("PPI · USD"), 0.0, places=2)

    def test_reupload_estado_is_idempotent(self):
        self._import_mov(CSV_MOV)
        self._import_estado(ESTADO_ROWS)
        rows_ggal = self._pos_rows("GGAL")
        # Re-subir el MISMO Estado: Rendi ya coincide con la foto → seed vacío.
        sid2 = self._import_estado(ESTADO_ROWS)
        self.assertIsNone(sid2)                       # nada que seedear
        self.assertAlmostEqual(self._held("GGAL"), 100.0, places=6)   # sin duplicar
        self.assertAlmostEqual(self._held("GD30"), 50.0, places=6)
        self.assertEqual(self._pos_rows("GGAL"), rows_ggal)           # no creó lotes nuevos

    def test_revert_seed_undoes_exactly(self):
        # Valida el fix de row_index: con particiones ARS+USD, el revert del seed
        # debe borrar EXACTO los lotes seedeados (sin el fix, borraba/orfanaba mal).
        self._import_mov(CSV_MOV)
        sid = self._import_estado(ESTADO_ROWS)
        self.assertAlmostEqual(self._held("GGAL"), 100.0, places=6)
        self.assertAlmostEqual(self._held("GD30"), 50.0, places=6)
        with self.conn:
            ps.revert_batch(self.conn, uid=self.uid, batch_id=sid, helpers=_helpers())
        # Vuelve al estado post-Movimientos: 20 GGAL (el lote de la ventana), 0 GD30.
        self.assertAlmostEqual(self._held("GGAL"), 20.0, places=6)
        self.assertAlmostEqual(self._held("GD30"), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
