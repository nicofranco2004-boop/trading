"""La prueba de Yahoo de /admin (`/api/admin/yahoo/prueba`): sólo para admins,
y cuenta lo que contestó Yahoo tal cual, también cuando falla (02/11/2026: el
servidor no bajaba velas y las fallas se anotaban en DEBUG, que no se ve)."""
import logging
import os
import sys
import tempfile
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import pandas as pd
from fastapi.testclient import TestClient

import main


def _usuario(admin: bool) -> dict:
    with main.db_abierta() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, tier, is_admin) "
            "VALUES (?, 'x', 1, 1, 'pro', ?)", (f"yp-{uuid.uuid4().hex[:8]}@rendi.test", 1 if admin else 0))
        conn.commit()
        return {"Authorization": f"Bearer {main.create_token(cur.lastrowid)}"}


class PruebaDeYahooTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)

    def test_sin_ser_admin_no_se_puede(self):
        r = self.client.get("/api/admin/yahoo/prueba", headers=_usuario(False))
        self.assertEqual(r.status_code, 403)

    def test_cuenta_lo_que_contesto_yahoo_aunque_falle(self):
        tabla = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.to_datetime(["2026-10-29", "2026-10-30"]))

        def historia(ticker, period, interval, auto_adjust, timeout):
            if ticker == "AAPL":
                return tabla
            if ticker == "AVAX-USD":
                logging.getLogger("yfinance").error("$AVAX-USD: possibly delisted; no price data found")
                return pd.DataFrame()
            raise RuntimeError("Too Many Requests. Rate limited. Try after a while.")
        with mock.patch("pricing.yahoo._historia", historia):
            r = self.client.get("/api/admin/yahoo/prueba", headers=_usuario(True))
        self.assertEqual(r.status_code, 200, r.text)
        p = {f["ticker"]: f for f in r.json()["pruebas"]}
        self.assertEqual((p["AAPL"]["filas"], p["AAPL"]["ultima"]), (2, "2026-10-30"))
        self.assertEqual(p["AVAX-USD"]["filas"], 0)
        self.assertIn("possibly delisted", p["AVAX-USD"]["yfinance_dijo"][0])
        self.assertIn("Too Many Requests", p["GGAL.BA"]["error"])


if __name__ == "__main__":
    unittest.main()
