"""FX/MEP capital fix (bug #1): una conversión ARS→USD debe corregir el Capital
Aportado para que refleje los USD efectivamente obtenidos (al MEP), no el valor
blue subvaluado del depósito original.

Sin el fix, depositar 1.000.000 ARS (=706,71 USD al blue 1415) y convertirlos a
1.000 USD al MEP dejaba el capital en 706,71 → return fantasma de +41%. El FX no
escribía monthly_entries. Con el fix, el capital queda en 1.000 (lo que el user
realmente puso, en USD) y el cash vivo sigue exacto."""
import unittest

import main
from importing import pipeline as pl, persister as ps


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    return h


class FxCapitalTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) VALUES ('fx@rendi.test','x',1,1)"
        ).lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'ARS')", (self.uid, 'TestMEP'))
        conn.commit()
        conn.close()

    def _import(self, csv):
        conn = main.get_db()
        with conn:
            payload = pl.run_preview(conn, uid=self.uid, file_bytes=csv, file_name='fx.csv',
                                     broker_hint=None, parser_format='rendi_generic')
        self.assertIsNone(payload.get('error'))
        sid = payload['session_id']
        with conn:
            txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=sid)
            ps.persist_batch(conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
        return conn

    def test_mep_conversion_corrects_capital(self):
        # blue por defecto = 1415; MEP = 1000. 1M ARS (706,71 al blue) → 1000 USD.
        csv = (b"fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
               b"2022-01-10,DEPOSITO,TestMEP,,,,1000000,,,,ARS,dep\n"
               b"2022-01-11,CONVERSION_ARS_USD,TestMEP,,,,1000000,1000,1000,,,MEP\n")
        conn = self._import(csv)
        # Capital aportado global = deposits - withdrawals = 1000 (NO 706,71)
        row = conn.execute(
            "SELECT deposits, withdrawals FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,),
        ).fetchone()
        capital = (row["deposits"] or 0) - (row["withdrawals"] or 0)
        self.assertAlmostEqual(capital, 1000.0, places=1)
        # Cash vivo: ARS 0, USD 1000 (exacto, como antes del fix)
        cash = {r["broker"]: r["invested"] for r in conn.execute(
            "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1", (self.uid,))}
        self.assertAlmostEqual(cash.get("TestMEP", 0), 0, places=1)
        self.assertAlmostEqual(cash.get("TestMEP · USD", 0), 1000, places=1)
        conn.close()

    def test_no_conversion_capital_unchanged(self):
        # Control: sin conversión, un depósito ARS queda al blue (706,71) y NO se
        # toca — el fix solo actúa cuando hay un FX.
        csv = (b"fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
               b"2022-01-10,DEPOSITO,TestMEP,,,,1000000,,,,ARS,dep\n")
        conn = self._import(csv)
        row = conn.execute(
            "SELECT deposits, withdrawals FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,),
        ).fetchone()
        capital = (row["deposits"] or 0) - (row["withdrawals"] or 0)
        self.assertAlmostEqual(capital, 1000000 / 1415.0, places=1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
