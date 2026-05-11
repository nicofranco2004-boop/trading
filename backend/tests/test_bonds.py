"""Tests del endpoint POST /api/bonds/cashflow — registrar cupón o amortización
recibida de un bono. Corre con: cd backend && python3 -m pytest tests/test_bonds.py

Cubre:
- Happy path: cupón → INSERT operations + acreditación al cash (USDT/USD/ARS)
- Happy path: amortización → idem con op_type 'Amortización'
- Comisiones: monto neto = amount - commissions
- Validación: flow_type debe ser 'coupon' o 'amortization'
- 404 si el broker no pertenece al user
- 400 si el monto neto queda ≤ 0 (comisiones mayores al monto)
- Cash asset correcto según currency del broker (ARS → ARS, USD → USD, USDT → USDT)
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# DB temporal por test run — debe setearse ANTES de importar main
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _new_user(conn, email: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x"),
    )
    return cur.lastrowid


def _add_broker(conn, uid: int, name: str, currency: str = "USDT") -> int:
    cur = conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
        (uid, name, currency),
    )
    return cur.lastrowid


class BondCashflowEndpointTest(unittest.TestCase):
    """E2E del endpoint /api/bonds/cashflow via TestClient."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        # Usuario y brokers nuevos por test (DB compartida pero scoping por uid)
        conn = main.get_db()
        # Email único por test para evitar UNIQUE collisions entre tests
        self.uid = _new_user(conn, f"bond-{self.id()}@rendi.test")
        # Tres brokers con currencies distintas para cubrir el mapeo cash asset
        _add_broker(conn, self.uid, "Binance", "USDT")
        _add_broker(conn, self.uid, "IBKR", "USD")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _post(self, body):
        return self.client.post(
            "/api/bonds/cashflow",
            json=body,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    # ─── Happy paths ─────────────────────────────────────────────────────────

    def test_coupon_creates_operation_and_credits_cash_usdt(self):
        """Cupón en USDT broker → op_type 'Cupón' + cash USDT acreditado."""
        res = self._post({
            "broker": "Binance",
            "asset": "TLT",
            "flow_type": "coupon",
            "amount": 100.0,
            "date": "2026-05-10",
            "commissions": 0,
            "notes": "Cupón mensual TLT",
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["op_type"], "Cupón")
        self.assertAlmostEqual(body["amount_net"], 100.0)

        # Verificar operación
        conn = main.get_db()
        try:
            op = conn.execute(
                "SELECT * FROM operations WHERE user_id=? AND broker='Binance' AND asset='TLT'",
                (self.uid,),
            ).fetchone()
            self.assertIsNotNone(op)
            self.assertEqual(op["op_type"], "Cupón")
            self.assertEqual(op["notes"], "Cupón mensual TLT")
            self.assertAlmostEqual(op["pnl_usd"], 100.0)

            # Verificar cash position USDT
            cash = conn.execute(
                "SELECT * FROM positions WHERE user_id=? AND broker='Binance' AND asset='USDT' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertIsNotNone(cash)
            self.assertAlmostEqual(cash["invested"], 100.0)
        finally:
            conn.close()

    def test_amortization_creates_operation_with_op_type_amortizacion(self):
        """Amortización en USD broker → op_type 'Amortización' + cash USD acreditado."""
        res = self._post({
            "broker": "IBKR",
            "asset": "AL30",
            "flow_type": "amortization",
            "amount": 250.0,
            "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["op_type"], "Amortización")

        conn = main.get_db()
        try:
            op = conn.execute(
                "SELECT op_type FROM operations WHERE user_id=? AND broker='IBKR' AND asset='AL30'",
                (self.uid,),
            ).fetchone()
            self.assertEqual(op["op_type"], "Amortización")

            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='IBKR' AND asset='USD' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertIsNotNone(cash)
            self.assertAlmostEqual(cash["invested"], 250.0)
        finally:
            conn.close()

    def test_commissions_deducted_from_net_amount(self):
        """Comisiones reducen el monto neto acreditado (cupón nominal 100 − fee 5 = 95 al cash)."""
        res = self._post({
            "broker": "Binance",
            "asset": "GD30",
            "flow_type": "coupon",
            "amount": 100.0,
            "date": "2026-05-10",
            "commissions": 5.0,
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertAlmostEqual(res.json()["amount_net"], 95.0)

        conn = main.get_db()
        try:
            cash = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Binance' AND asset='USDT' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(cash["invested"], 95.0)
            # La operación guarda commissions explícitamente
            op = conn.execute(
                "SELECT commissions, pnl_usd FROM operations WHERE user_id=? AND asset='GD30'",
                (self.uid,),
            ).fetchone()
            self.assertAlmostEqual(op["commissions"], 5.0)
            self.assertAlmostEqual(op["pnl_usd"], 95.0)  # neto guardado
        finally:
            conn.close()

    def test_ars_broker_credits_cash_in_ars(self):
        """Broker ARS: el monto se acredita en la posición ARS, no en USDT/USD."""
        res = self._post({
            "broker": "Cocos",
            "asset": "TX26",
            "flow_type": "coupon",
            "amount": 50000.0,
            "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200, res.text)

        conn = main.get_db()
        try:
            cash_ars = conn.execute(
                "SELECT invested FROM positions WHERE user_id=? AND broker='Cocos' AND asset='ARS' AND is_cash=1",
                (self.uid,),
            ).fetchone()
            self.assertIsNotNone(cash_ars)
            self.assertAlmostEqual(cash_ars["invested"], 50000.0)
            # Y que NO se haya creado un cash en USDT/USD para este broker
            cash_other = conn.execute(
                "SELECT COUNT(*) FROM positions WHERE user_id=? AND broker='Cocos' AND asset IN ('USDT','USD') AND is_cash=1",
                (self.uid,),
            ).fetchone()[0]
            self.assertEqual(cash_other, 0)
        finally:
            conn.close()

    def test_asset_uppercased_in_operation(self):
        """El asset se guarda en uppercase aunque el cliente lo mande en minúscula."""
        res = self._post({
            "broker": "Binance",
            "asset": "al30",
            "flow_type": "coupon",
            "amount": 10.0,
            "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["asset"], "AL30")

    # ─── Errores ─────────────────────────────────────────────────────────────

    def test_invalid_flow_type_rejected(self):
        """flow_type fuera de {'coupon','amortization'} → 422."""
        res = self._post({
            "broker": "Binance",
            "asset": "TLT",
            "flow_type": "rebalance",   # inválido
            "amount": 100,
            "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 422)

    def test_invalid_date_format_rejected(self):
        """Fechas que no matchean YYYY-MM-DD → 422."""
        res = self._post({
            "broker": "Binance",
            "asset": "TLT",
            "flow_type": "coupon",
            "amount": 100,
            "date": "10/05/2026",   # formato no ISO
        })
        self.assertEqual(res.status_code, 422)

    def test_amount_must_be_positive(self):
        """amount ≤ 0 → 422 (validación de Pydantic gt=0)."""
        res = self._post({
            "broker": "Binance",
            "asset": "TLT",
            "flow_type": "coupon",
            "amount": 0,
            "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 422)

    def test_unknown_broker_returns_404(self):
        """Broker que no existe (o no pertenece al user) → 404."""
        res = self._post({
            "broker": "NoExiste",
            "asset": "TLT",
            "flow_type": "coupon",
            "amount": 10,
            "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 404)

    def test_net_amount_zero_or_negative_returns_400(self):
        """Comisiones ≥ amount → monto neto ≤ 0 → 400."""
        res = self._post({
            "broker": "Binance",
            "asset": "TLT",
            "flow_type": "coupon",
            "amount": 50,
            "date": "2026-05-10",
            "commissions": 50,  # neto = 0
        })
        self.assertEqual(res.status_code, 400)

    def test_unauthorized_without_token(self):
        """Sin Authorization header → 401."""
        res = self.client.post(
            "/api/bonds/cashflow",
            json={
                "broker": "Binance",
                "asset": "TLT",
                "flow_type": "coupon",
                "amount": 10,
                "date": "2026-05-10",
            },
        )
        # FastAPI security devuelve 401 o 403 según config; el endpoint
        # depende de get_current_user que lanza 401.
        self.assertIn(res.status_code, (401, 403))

    def test_cross_user_isolation(self):
        """Un user no puede registrar cashflow en el broker de otro user."""
        # Crear segundo user con su propio broker (mismo nombre, distinto uid)
        conn = main.get_db()
        other_uid = _new_user(conn, f"other-{self.id()}@rendi.test")
        _add_broker(conn, other_uid, "BrokerOther", "USDT")
        conn.commit()
        conn.close()

        # Intentamos cobrar contra 'BrokerOther' usando el token de self.uid
        res = self._post({
            "broker": "BrokerOther",
            "asset": "TLT",
            "flow_type": "coupon",
            "amount": 10,
            "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 404)


class CashAssetForCurrencyTest(unittest.TestCase):
    """Helper puro: mapeo currency → asset name."""

    def test_ars_currency_maps_to_ars(self):
        self.assertEqual(main._cash_asset_for_currency("ARS"), "ARS")

    def test_usd_currency_maps_to_usd(self):
        self.assertEqual(main._cash_asset_for_currency("USD"), "USD")

    def test_usdt_currency_maps_to_usdt(self):
        self.assertEqual(main._cash_asset_for_currency("USDT"), "USDT")

    def test_unknown_currency_falls_back_to_usdt(self):
        """Cualquier valor desconocido (legado, futuras monedas) → USDT por compat."""
        self.assertEqual(main._cash_asset_for_currency("EUR"), "USDT")
        self.assertEqual(main._cash_asset_for_currency(""), "USDT")


if __name__ == "__main__":
    unittest.main()
