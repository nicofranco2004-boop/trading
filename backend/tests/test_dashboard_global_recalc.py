"""Fix: la fila sintética broker='global' de monthly_entries debe recomputarse
como Σ(per-broker) en el recalc.

Bug: el dashboard lee de monthly_entries broker='global' (capital aportado /
ganancias retiradas / resultado). Cada flujo manual se escribe per-broker Y en
'global', pero al borrar un broker su manual_* per-broker se borraba y el de
'global' NO se decrementaba → quedaban valores fantasma que no volvían a cero
con revert / recalcular / limpiar brokers, y bloqueaban el limpiado de snapshots.
"""
import unittest

import main


def _new_user(conn, email="dash@rendi.test"):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"),
    )
    return cur.lastrowid


def _add_broker(conn, uid, name, currency="USD"):
    conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
        (uid, name, currency),
    )


def _ins_monthly(conn, uid, broker, y, m, *, deposits=0, manual_deposits=0):
    conn.execute(
        """INSERT INTO monthly_entries
              (user_id, year, month, broker, deposits, withdrawals,
               pnl_realized, pnl_unrealized, capital_inicio, capital_final,
               manual_deposits, manual_withdrawals)
           VALUES (?,?,?,?,?,0,0,0,0,0,?,0)""",
        (uid, y, m, broker, deposits, manual_deposits),
    )


def _global_row(conn, uid, y, m):
    return conn.execute(
        "SELECT deposits, withdrawals FROM monthly_entries "
        "WHERE user_id=? AND broker='global' AND year=? AND month=?",
        (uid, y, m),
    ).fetchone()


class GlobalRecalcGhostTest(unittest.TestCase):
    Y, M = 2026, 6

    def setUp(self):
        conn = main.get_db()
        for t in ("monthly_entries", "snapshots", "operations", "positions",
                  "import_batches", "import_normalized_tx", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.uid = _new_user(conn)
        conn.commit()
        conn.close()

    def test_ghost_global_cleared_when_no_brokers(self):
        """Sin brokers reales (todos borrados) queda solo el residuo: fila
        'global' con depósito fantasma + un snapshot. El recalc pone 'global' en
        0 (Σ per-broker = 0), la fila se limpia y los snapshots también →
        dashboard en cero."""
        conn = main.get_db()
        try:
            with conn:
                _ins_monthly(conn, self.uid, "global", self.Y, self.M,
                             deposits=5242, manual_deposits=5242)
                conn.execute(
                    "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, fx_to_usd_blue) "
                    "VALUES (?,?,?,?,?,?)",
                    (self.uid, "2026-06-25", 0, 0, 5242, 1415),
                )
            with conn:
                main._recalc_pnl_realized_from_ops(conn, self.uid)
            self.assertIsNone(_global_row(conn, self.uid, self.Y, self.M),
                              "la fila 'global' fantasma debió borrarse")
            snaps = conn.execute(
                "SELECT COUNT(*) c FROM snapshots WHERE user_id=?", (self.uid,)
            ).fetchone()
            self.assertEqual(snaps["c"], 0, "los snapshots debieron limpiarse")
        finally:
            conn.close()

    def test_global_equals_sum_of_real_brokers(self):
        """Caso con data: 'global' = Σ(per-broker). No se rompe (parte adversarial)."""
        conn = main.get_db()
        try:
            with conn:
                _add_broker(conn, self.uid, "Cocos", "ARS")
                _add_broker(conn, self.uid, "Schwab", "USD")
                _ins_monthly(conn, self.uid, "Cocos", self.Y, self.M, deposits=1000, manual_deposits=1000)
                _ins_monthly(conn, self.uid, "Schwab", self.Y, self.M, deposits=3000, manual_deposits=3000)
                _ins_monthly(conn, self.uid, "global", self.Y, self.M, deposits=9999, manual_deposits=9999)  # stale
            with conn:
                main._recalc_pnl_realized_from_ops(conn, self.uid)
            g = _global_row(conn, self.uid, self.Y, self.M)
            self.assertIsNotNone(g)
            self.assertAlmostEqual(g["deposits"], 4000, places=2)  # 1000 + 3000
        finally:
            conn.close()

    def test_delete_one_of_two_recomputes_global(self):
        """Borrado un broker (queda su residuo en 'global'): el recalc deja
        'global' = solo el broker que queda, sin el fantasma del borrado."""
        conn = main.get_db()
        try:
            with conn:
                _add_broker(conn, self.uid, "Schwab", "USD")  # Cocos ya borrado
                _ins_monthly(conn, self.uid, "Schwab", self.Y, self.M, deposits=3000, manual_deposits=3000)
                _ins_monthly(conn, self.uid, "global", self.Y, self.M, deposits=4000, manual_deposits=4000)  # 1000 Cocos + 3000
            with conn:
                main._recalc_pnl_realized_from_ops(conn, self.uid)
            g = _global_row(conn, self.uid, self.Y, self.M)
            self.assertIsNotNone(g)
            self.assertAlmostEqual(g["deposits"], 3000, places=2)  # solo Schwab
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
