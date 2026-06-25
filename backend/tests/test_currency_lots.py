"""Lote = (broker, asset, currency): el MISMO ticker en pesos Y en dólares no se
mezcla. Reportado por un usuario real ("complicaciones al comprar el mismo ticker
en pesos y dólares") — antes el FIFO consumía cualquier lote sin mirar la moneda
y create_position no guardaba la moneda (lotes NULL → mezclados).

Corre con: cd backend && python3 -m pytest tests/test_currency_lots.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
from fastapi.testclient import TestClient


def _new_user(conn, email):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)", (email, "x"))
    return cur.lastrowid


class CurrencyLotsTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, email=f"ccy-{id(self)}@rendi.test")
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "Cocos", "ARS"))
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.client = TestClient(main.app)

    def _hdr(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _add(self, **kw):
        return self.client.post("/api/positions", json=kw, headers=self._hdr())

    def _lots(self):
        conn = main.get_db()
        rows = conn.execute(
            "SELECT currency, quantity FROM positions WHERE user_id=? AND asset='AAPL' "
            "AND is_cash=0 AND quantity > 0 ORDER BY currency", (self.uid,)).fetchall()
        conn.close()
        return {r["currency"]: r["quantity"] for r in rows}

    def test_same_ticker_two_currencies_stored_separately(self):
        # Mismo ticker AAPL en ARS y en USD, mismo broker → dos lotes distintos.
        r1 = self._add(broker="Cocos", asset="AAPL", quantity=10, buy_price=50000, currency="ARS")
        r2 = self._add(broker="Cocos", asset="AAPL", quantity=5, buy_price=200, currency="USD")
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(self._lots(), {"ARS": 10.0, "USD": 5.0})

    def test_currency_inferred_from_broker_when_absent(self):
        # Sin currency en el body → inferida del broker (Cocos = ARS).
        r = self._add(broker="Cocos", asset="GGAL", quantity=100, buy_price=1500)
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        c = conn.execute("SELECT currency FROM positions WHERE user_id=? AND asset='GGAL'",
                         (self.uid,)).fetchone()["currency"]
        conn.close()
        self.assertEqual(c, "ARS")

    def test_sell_in_usd_consumes_only_usd_lot(self):
        # ARS lote primero (más viejo) — sin filtro por moneda el FIFO lo comería.
        self._add(broker="Cocos", asset="AAPL", quantity=10, buy_price=50000, currency="ARS")
        self._add(broker="Cocos", asset="AAPL", quantity=5, buy_price=200, currency="USD")
        r = self.client.post("/api/positions/sell", json={
            "broker": "Cocos", "asset": "AAPL", "quantity": 5, "exit_price": 220,
            "currency": "USD",
        }, headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        # El lote USD se cerró; el ARS quedó INTACTO (10).
        self.assertEqual(self._lots(), {"ARS": 10.0})

    def test_sell_in_ars_consumes_only_ars_lot(self):
        self._add(broker="Cocos", asset="AAPL", quantity=10, buy_price=50000, currency="ARS")
        self._add(broker="Cocos", asset="AAPL", quantity=5, buy_price=200, currency="USD")
        r = self.client.post("/api/positions/sell", json={
            "broker": "Cocos", "asset": "AAPL", "quantity": 4, "exit_price": 55000,
            "currency": "ARS", "tc_venta": 1400,
        }, headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        # Consumió 4 del lote ARS (queda 6); el USD intacto (5).
        self.assertEqual(self._lots(), {"ARS": 6.0, "USD": 5.0})

    def test_oversell_in_one_currency_blocked(self):
        # Tener 5 USD + 10 ARS, vender 8 USD → excede los 5 USD disponibles.
        self._add(broker="Cocos", asset="AAPL", quantity=10, buy_price=50000, currency="ARS")
        self._add(broker="Cocos", asset="AAPL", quantity=5, buy_price=200, currency="USD")
        r = self.client.post("/api/positions/sell", json={
            "broker": "Cocos", "asset": "AAPL", "quantity": 8, "exit_price": 220,
            "currency": "USD",
        }, headers=self._hdr())
        self.assertEqual(r.status_code, 400, r.text)  # no puede vender 8 USD si tiene 5


if __name__ == "__main__":
    unittest.main()
