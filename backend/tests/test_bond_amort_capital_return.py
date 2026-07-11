"""Amortización de bono SIN cantidad = devolución de capital (P&L-neutral).

Bug reportado (2026-07-09, TX26 en Balanz): "Renta y Amortización / TX26" viene
con cantidad 0 → caía en DIVIDENDO → los $3,2M de capital devuelto se contaban
ENTEROS como ganancia realizada → P&L de la cartera super inflado.

Fix (persister._is_amort_capital_return): ese cash entra igual, pero la operation
queda como 'Amortización' con pnl_usd=0 y NO toca monthly pnl_realized (misma
semántica que el flujo manual bond_cashflow). Revert simétrico.

Corre con: cd backend && python3 -m pytest tests/test_bond_amort_capital_return.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import importing.pipeline as pl
import importing.persister as ps
from importing.persister import _is_amort_capital_return
import main  # init_db() crea las tablas (DB_PATH aislada por conftest)

# Header del export de Movimientos de Balanz (el libro de caja).
MOV_HEADER = (
    "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
    "Liquidacion,Moneda,Importe"
)

# Filas REALES del reporte del usuario (TX26, bono CER en pesos).
ROW_AMORT = "Renta y Amortización / TX26,TX26,Bonos,2026-05-11,0,-1,2026-05-11,Pesos,3217055.59"
ROW_BUY = "Boleto / 12758746 / COMPRA / 1 / TX26 / $,TX26,Bonos,2025-12-29,663557,11.591208,2025-12-30,Pesos,-7730076.4"


def _csv(*rows):
    return "\n".join([MOV_HEADER, *rows]) + "\n"


def _new_user(conn, email):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"))
    return cur.lastrowid


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    return h


class AmortPredicateTest(unittest.TestCase):
    """Unit del predicado — el contrato 'amortiz' + bono."""

    def test_amort_de_bono_matchea(self):
        self.assertTrue(_is_amort_capital_return(
            "DIVIDEND", "TX26", "BOND", "Renta y Amortización / TX26"))

    def test_bono_conocido_sin_asset_type(self):
        # TX26 es bono AR conocido aunque el parser no estampe asset_type.
        self.assertTrue(_is_amort_capital_return(
            "DIVIDEND", "TX26", None, "Renta y Amortización / TX26"))

    def test_renta_pura_NO_matchea(self):
        # Cupón puro (sin 'amortiz') sigue siendo ingreso.
        self.assertFalse(_is_amort_capital_return(
            "DIVIDEND", "TX26", "BOND", "Renta / TX26"))

    def test_dividendo_de_accion_NO_matchea(self):
        # Una acción con nota rara no se reclasifica (gate de bono).
        self.assertFalse(_is_amort_capital_return(
            "DIVIDEND", "AAPL", "STOCK", "dividendo amortizado x"))

    def test_sin_asset_NO_matchea(self):
        self.assertFalse(_is_amort_capital_return(
            "DIVIDEND", None, "BOND", "Amortización"))

    def test_buy_NO_matchea(self):
        self.assertFalse(_is_amort_capital_return(
            "BUY", "TX26", "BOND", "Amortización"))


class AmortPersistTest(unittest.TestCase):
    """End-to-end: parse Balanz Movimientos → persist → P&L/cash/operations."""

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, "amort_test@rendi.test")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "Balanz", "ARS"))
        conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
            (self.uid, "Balanz", "ARS", 10_000_000))
        conn.commit()
        conn.close()

    def _import(self, *rows):
        csv_bytes = _csv(*rows).encode("utf-8")
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=csv_bytes, file_name="mov.csv",
                    broker_hint="Balanz", parser_format="balanz_movimientos")
            session_id = payload["session_id"]
            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                 raw_row_ids_by_index=raw, helpers=_helpers())
            return session_id, conn
        except Exception:
            conn.close()
            raise

    def _pnl_realized(self, conn, broker):
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries "
            "WHERE user_id=? AND broker=?", (self.uid, broker)).fetchone()
        return float(row["p"] or 0)

    def _cash(self, conn):
        row = conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker='Balanz' AND is_cash=1",
            (self.uid,)).fetchone()
        return float(row["invested"] or 0)

    def test_amort_no_infla_pnl_pero_acredita_cash(self):
        sid, conn = self._import(ROW_AMORT)
        try:
            # cash SÍ entra (los $3,2M son reales)
            self.assertAlmostEqual(self._cash(conn), 10_000_000 + 3_217_055.59, places=2)
            # P&L realizado NO se infla (antes: +3,2M/tc como ganancia)
            self.assertAlmostEqual(self._pnl_realized(conn, "Balanz"), 0.0, places=2)
            self.assertAlmostEqual(self._pnl_realized(conn, "global"), 0.0, places=2)
            # operations: fila 'Amortización' con pnl 0 (visible, pero no ganancia)
            op = conn.execute(
                "SELECT op_type, pnl_usd, asset FROM operations WHERE user_id=?",
                (self.uid,)).fetchone()
            self.assertEqual(op["op_type"], "Amortización")
            self.assertEqual(op["asset"], "TX26")
            self.assertAlmostEqual(float(op["pnl_usd"] or 0), 0.0, places=2)
        finally:
            conn.close()

    def test_renta_pura_sigue_siendo_ingreso(self):
        # Un cupón sin 'Amortización' en la descripción NO cambia: suma P&L.
        sid, conn = self._import(
            "Renta / TX26,TX26,Bonos,2026-05-11,0,-1,2026-05-11,Pesos,100000")
        try:
            self.assertGreater(self._pnl_realized(conn, "Balanz"), 0.0)
            op = conn.execute(
                "SELECT op_type, pnl_usd FROM operations WHERE user_id=?",
                (self.uid,)).fetchone()
            self.assertEqual(op["op_type"], "Dividendo")
            self.assertGreater(float(op["pnl_usd"]), 0.0)
        finally:
            conn.close()

    def test_dividendo_de_accion_intacto(self):
        sid, conn = self._import(
            "Dividendo en efectivo / XLE,XLE,Cedears,2026-05-11,0,-1,2026-05-11,Pesos,50000")
        try:
            self.assertGreater(self._pnl_realized(conn, "Balanz"), 0.0)
        finally:
            conn.close()

    def test_revert_simetrico(self):
        # Revertir el import debe dejar pnl_realized en 0 (no en NEGATIVO por
        # restar un profit que nunca se sumó) y el cash de vuelta.
        sid, conn = self._import(ROW_AMORT)
        try:
            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=sid, helpers=_helpers())
            self.assertAlmostEqual(self._pnl_realized(conn, "Balanz"), 0.0, places=2)
            self.assertAlmostEqual(self._pnl_realized(conn, "global"), 0.0, places=2)
            self.assertAlmostEqual(self._cash(conn), 10_000_000, places=2)
            n_ops = conn.execute(
                "SELECT COUNT(*) c FROM operations WHERE user_id=?", (self.uid,)).fetchone()["c"]
            self.assertEqual(n_ops, 0)
        finally:
            conn.close()

    def test_amort_CON_cantidad_sigue_siendo_venta(self):
        # Parte A intacta: si el export SÍ trae cantidad, la amort cierra nominal
        # como VENTA al valor de rescate (no pasa por el path capital-return).
        sid, conn = self._import(
            ROW_BUY,
            "Renta y Amortización / TX26,TX26,Bonos,2026-05-11,-100000,-1,2026-05-11,Pesos,1200000")
        try:
            ops = [r["op_type"] for r in conn.execute(
                "SELECT op_type FROM operations WHERE user_id=?", (self.uid,))]
            self.assertIn("Venta", ops)                 # la amort-con-cantidad cerró como VENTA
            self.assertNotIn("Amortización", ops)       # NO pasó por el path capital-return
            # el nominal bajó (663557 - 100000)
            pos = conn.execute(
                "SELECT SUM(quantity) q FROM positions WHERE user_id=? AND asset='TX26'",
                (self.uid,)).fetchone()
            self.assertAlmostEqual(float(pos["q"]), 663557 - 100000, places=2)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
