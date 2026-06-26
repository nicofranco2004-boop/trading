"""Fix: el gate de split-check / adjust-ratio se alinea con el de la valuación.

Un equity de BYMA en un broker ARS (SPY/QQQ que quedó taggeado OTHER/ETF, o una
acción AR) se precia vía .BA → puede tener cambio de ratio aunque su asset_type
no sea exactamente 'CEDEAR'. Antes el gate exigía asset_type='CEDEAR' literal y se
perdía esos casos: la valuación los mostraba en pesos (pérdida fantasma) pero el
banner/ajuste no aparecía. Ahora califica si asset_type='CEDEAR' O broker ARS,
excluyendo bonos/ONs, FCI, cripto y fiat. Schwab (USD) sigue afuera salvo CEDEAR.
"""
import unittest
from unittest.mock import patch

import main


def _new_user(conn, email):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)", (email, "x"),
    )
    return cur.lastrowid


def _add_broker(conn, uid, name, currency):
    conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (uid, name, currency),
    )


def _add_pos(conn, uid, broker, asset, asset_type, *, buy_price=44900, qty=10,
             invested=449000, entry="2026-01-15"):
    cur = conn.execute(
        """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
               invested, entry_date, asset_type)
           VALUES (?,?,?,0,?,?,?,?,?)""",
        (uid, broker, asset, buy_price, qty, invested, entry, asset_type),
    )
    return cur.lastrowid


SPLITS = [("2026-05-29", 3.0)]


class SplitArsBrokerGateTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        for t in ("positions", "snapshots", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(conn, f"split-ars-{id(self)}@rendi.test")
        _add_broker(conn, self.uid, "IOL", "ARS")        # broker ARS
        _add_broker(conn, self.uid, "Schwab", "USDT")    # broker USD
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _adjust(self, pid, splits=SPLITS):
        with patch.object(main, "_fetch_ba_splits", return_value=list(splits)):
            return self.client.post(
                f"/api/positions/{pid}/adjust-ratio",
                headers={"Authorization": f"Bearer {self.token}"},
            )

    def _check(self, splits=SPLITS):
        with patch.object(main, "_fetch_ba_splits", return_value=list(splits)):
            return self.client.get(
                "/api/positions/split-check",
                headers={"Authorization": f"Bearer {self.token}"},
            )

    def _qty(self, pid):
        conn = main.get_db()
        r = conn.execute("SELECT quantity, invested FROM positions WHERE id=?", (pid,)).fetchone()
        conn.close()
        return r

    def test_adjust_spy_in_ars_broker_even_if_not_cedear(self):
        """SPY (asset_type=OTHER) en IOL (ARS) ahora SÍ ajusta. qty 10→30, invested intacto."""
        conn = main.get_db(); pid = _add_pos(conn, self.uid, "IOL", "SPY", "OTHER")
        conn.commit(); conn.close()
        res = self._adjust(pid)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertAlmostEqual(res.json()["factor"], 3.0)
        r = self._qty(pid)
        self.assertAlmostEqual(r["quantity"], 30.0)
        self.assertAlmostEqual(r["invested"], 449000)  # NO cambia

    def test_split_check_detects_spy_in_ars_broker(self):
        conn = main.get_db(); pid = _add_pos(conn, self.uid, "IOL", "SPY", "OTHER")
        conn.commit(); conn.close()
        res = self._check()
        self.assertEqual(res.status_code, 200, res.text)
        pids = [s["pid"] for s in res.json().get("suggestions", [])]
        self.assertIn(pid, pids)

    def test_us_stock_in_usd_broker_still_rejected(self):
        """Regresión: Schwab (USD) AAPL/STOCK sigue rechazado (ni ARS ni CEDEAR)."""
        conn = main.get_db()
        pid = _add_pos(conn, self.uid, "Schwab", "AAPL", "STOCK", buy_price=150, qty=10, invested=1500)
        conn.commit(); conn.close()
        self.assertEqual(self._adjust(pid).status_code, 400)
        self.assertAlmostEqual(self._qty(pid)["quantity"], 10.0)

    def test_bond_in_ars_broker_excluded(self):
        """Un bono en broker ARS NO entra (no tiene split de equity)."""
        conn = main.get_db()
        pid = _add_pos(conn, self.uid, "IOL", "AL30", "BOND", buy_price=70, qty=100, invested=7000)
        conn.commit(); conn.close()
        self.assertEqual(self._adjust(pid).status_code, 400)
        pids = [s["pid"] for s in self._check().json().get("suggestions", [])]
        self.assertNotIn(pid, pids)


if __name__ == "__main__":
    unittest.main()
