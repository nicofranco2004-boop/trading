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


class Phase3DCashflowExtensionsTest(unittest.TestCase):
    """Tests de Phase 3D: currency stamping + fx_to_usd + decrement_quantity.

    Asegura que las nuevas columnas y el comportamiento amortizante funcionen
    sin romper el flujo legacy.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    # Serie de FX sembrada. SIN esto la tabla queda vacía, `fx_for_date_detail`
    # devuelve (None, None) y los asserts de sellado pasan por la razón
    # equivocada — verde sin haber ejercitado nada.
    MEP_MAYO = 1250.0
    BLUE_MAYO = 1300.0

    def setUp(self):
        conn = main.get_db()
        self.uid = _new_user(conn, f"phase3d-{self.id()}@rendi.test")
        _add_broker(conn, self.uid, "Cocos", "ARS")
        _add_broker(conn, self.uid, "IBKR", "USD")
        # Crear posición de prueba: 1000 VN de AL30, costo USD 700
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested,
               quantity, buy_price, commissions, entry_date)
               VALUES (?, 'IBKR', 'AL30', 0, 700, 1000, 0.70, 0, '2024-06-01')""",
            (self.uid,),
        )
        # 2026-05-10 es la fecha que usan casi todos los tests de esta clase.
        # 2026-05-08 tiene blue pero NO mep: sirve para el walk-back.
        for d, blue, mep in [("2026-05-08", self.BLUE_MAYO, None),
                             ("2026-05-10", self.BLUE_MAYO, self.MEP_MAYO)]:
            conn.execute(
                # DO UPDATE y no DO NOTHING: el setUp corre antes de CADA test de
                # la clase sobre la misma base de módulo, y 2026-05-08 tiene que
                # quedar con mep_venta NULL sí o sí — es lo que hace que
                # test_fx_stamped_walks_back_when_date_has_no_mep pase por el
                # camino del blue. Con DO NOTHING, un mep que dejó otra escritura
                # sobrevive y el test pasa en verde por el camino equivocado.
                # `fetched_at` no se nombra: ningún SELECT de la app la lee.
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                "VALUES (?,?,?,?) ON CONFLICT (date) DO UPDATE SET "
                "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
                "source=EXCLUDED.source", (d, blue, mep, "test"))
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)

    def _post(self, body):
        return self.client.post(
            "/api/bonds/cashflow",
            json=body,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    # ─── Currency stamping ───────────────────────────────────────────────────

    def test_currency_defaults_to_broker_currency(self):
        """Sin currency explícito: usa la del broker (Cocos → ARS)."""
        res = self._post({
            "broker": "Cocos", "asset": "AL30",
            "flow_type": "coupon", "amount": 5000, "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["currency"], "ARS")

        conn = main.get_db()
        op = conn.execute(
            "SELECT currency, fx_to_usd FROM operations WHERE user_id=? AND asset='AL30'",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertEqual(op["currency"], "ARS")
        # ARS broker sin fx explícito → se sella el MEP de la FECHA DEL PAGO
        # (antes quedaba NULL y cada lector inventaba su propio fallback).
        self.assertEqual(op["fx_to_usd"], self.MEP_MAYO)
        self.assertEqual(body["fx_source"], "mep")

    def test_fx_to_usd_default_one_for_usd_broker(self):
        """Broker USD/USDT: fx_to_usd default = 1.0."""
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "coupon", "amount": 25, "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["currency"], "USD")
        self.assertEqual(body["fx_to_usd"], 1.0)

    def test_explicit_currency_and_fx_are_stamped(self):
        """Si el cliente manda currency + fx_to_usd, se respetan."""
        res = self._post({
            "broker": "Cocos", "asset": "AL30",
            "flow_type": "coupon", "amount": 32480,
            "date": "2026-05-10",
            "currency": "ARS",
            "fx_to_usd": 1250.0,  # ARS por USD (MEP) — nativa/USD, como el resto del sistema
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["fx_to_usd"], 1250.0)
        # El explícito del cliente GANA sobre el de la serie y queda marcado como tal.
        self.assertEqual(body["fx_source"], "client")

        conn = main.get_db()
        op = conn.execute(
            "SELECT currency, fx_to_usd FROM operations WHERE user_id=? AND asset='AL30'",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertEqual(op["currency"], "ARS")
        self.assertAlmostEqual(op["fx_to_usd"], 1250.0, places=6)

    # ─── Sellado del TC por fecha (broker ARS sin fx explícito) ──────────────

    def test_fx_stamped_uses_mep_of_payment_date_not_today(self):
        """El TC sellado es el de la FECHA DEL PAGO, no el más reciente de la serie.

        Es el corazón de la feature: un cupón viejo confirmado hoy tiene que quedar
        con el dólar de cuando se cobró. Sembramos un MEP MUY distinto en una fecha
        posterior — si el endpoint tomara "el último", el assert falla.
        """
        conn = main.get_db()
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES ('2026-08-01', 9000.0, 9999.0, 'test') "
            "ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source")
        conn.commit()
        conn.close()

        res = self._post({
            "broker": "Cocos", "asset": "AL30",
            "flow_type": "coupon", "amount": 5000, "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["fx_to_usd"], self.MEP_MAYO)
        self.assertNotEqual(res.json()["fx_to_usd"], 9999.0)

    def test_fx_stamped_walks_back_when_date_has_no_mep(self):
        """Fin de semana / feriado: cae al último día CON mep, no al blue del día.

        `_lookup` filtra IS NOT NULL en el WHERE, así que un día sin mep no degrada
        a blue — usa el mep anterior. 2026-05-08 tiene blue pero no mep.
        """
        res = self._post({
            "broker": "Cocos", "asset": "AL30",
            "flow_type": "coupon", "amount": 5000, "date": "2026-05-09",
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # 2026-05-09 no existe en la serie; el último con mep ≤ esa fecha no hay
        # (2026-05-08 tiene mep NULL) → cae al blue de 2026-05-08.
        self.assertEqual(body["fx_to_usd"], self.BLUE_MAYO)
        self.assertEqual(body["fx_source"], "blue")

    def test_fx_not_invented_when_date_predates_series(self):
        """Fecha anterior a toda la serie: NULL, no un número inventado."""
        res = self._post({
            "broker": "Cocos", "asset": "AL30",
            "flow_type": "coupon", "amount": 5000, "date": "2010-01-04",
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIsNone(body["fx_to_usd"])
        self.assertIsNone(body["fx_source"])

    def test_fx_source_queda_en_undo_meta(self):
        """El rastro del riel queda en la fila, no sólo en el response."""
        self._post({
            "broker": "Cocos", "asset": "AL30",
            "flow_type": "coupon", "amount": 5000, "date": "2026-05-10",
        })
        conn = main.get_db()
        row = conn.execute(
            "SELECT undo_meta_json FROM operations WHERE user_id=? AND asset='AL30'",
            (self.uid,),
        ).fetchone()
        conn.close()
        import json as _j
        self.assertEqual(_j.loads(row["undo_meta_json"])["fx_source"], "mep")

    def test_pnl_realized_no_suma_pesos_del_cupon_como_dolares(self):
        """`pnl_usd` de un cupón ARS son PESOS; el mensual los sumaba como dólares.

        Un cupón de $125.000 sumaba US$125.000 al P&L realizado del mes. Ahora se
        divide por el TC sellado — pero SÓLO en cobranzas: en una Venta el `pnl_usd`
        ya viene en USD y `fx_to_usd` guarda el tc_venta, así que dividir ahí
        rompería el número que hoy está bien.
        """
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type,
                 pnl_usd, commissions, currency, fx_to_usd)
               VALUES (?, '2026-05-10', 'Cocos', 'AL30', 'Cupón', 125000, 0, 'ARS', 1250.0)""",
            (self.uid,))
        conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type,
                 pnl_usd, commissions, currency, fx_to_usd)
               VALUES (?, '2026-05-20', 'Cocos', 'GGAL', 'Venta', 50, 0, 'ARS', 1250.0)""",
            (self.uid,))
        conn.commit()

        main._recalc_pnl_realized_from_ops(conn, self.uid)
        conn.commit()
        row = conn.execute(
            """SELECT pnl_realized FROM monthly_entries
                WHERE user_id=? AND broker='Cocos' AND year=2026 AND month=5""",
            (self.uid,)).fetchone()
        conn.close()

        # 125000/1250 = 100 (cupón, convertido) + 50 (venta, intacta) = 150
        self.assertAlmostEqual(row["pnl_realized"], 150.0, places=2)
        # El bug viejo daba 125.050
        self.assertNotAlmostEqual(row["pnl_realized"], 125050.0, places=2)

    def test_pnl_realized_deja_las_filas_legacy_como_estaban(self):
        """Cupón sin TC sellado (los ya cargados): cae al ELSE, no empeora."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type,
                 pnl_usd, commissions, currency, fx_to_usd)
               VALUES (?, '2026-05-10', 'Cocos', 'AL30', 'Cupón', 125000, 0, 'ARS', NULL)""",
            (self.uid,))
        conn.commit()
        main._recalc_pnl_realized_from_ops(conn, self.uid)
        conn.commit()
        row = conn.execute(
            """SELECT pnl_realized FROM monthly_entries
                WHERE user_id=? AND broker='Cocos' AND year=2026 AND month=5""",
            (self.uid,)).fetchone()
        conn.close()
        self.assertAlmostEqual(row["pnl_realized"], 125000.0, places=2)

    def test_broker_usd_ignora_un_fx_del_cliente_que_no_sea_uno(self):
        """Guarda: en una fila en dólares el factor a USD es 1, diga lo que diga el cliente.

        El modal, sugiriendo para un bono en pesos dentro de una cuenta en dólares,
        podía mandar el TC de la conversión (1250) sobre una fila cuya moneda es USD.
        Todo lector que divida mostraría esos US$100 como US$0,08.
        """
        res = self._post({
            "broker": "IBKR", "asset": "TZX26",
            "flow_type": "coupon", "amount": 100, "date": "2026-05-10",
            "fx_to_usd": 1250.0,   # lo que mandaría un cliente confundido
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["currency"], "USD")
        self.assertEqual(body["fx_to_usd"], 1.0)     # la guarda gana
        self.assertEqual(body["fx_source"], "par")

    def test_usd_broker_sigue_en_uno_sin_tocar_la_serie(self):
        """Regresión: un broker USD no convierte nada aunque haya serie sembrada."""
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "coupon", "amount": 25, "date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["fx_to_usd"], 1.0)
        self.assertEqual(res.json()["fx_source"], "par")

    # ─── Amortization decrement ──────────────────────────────────────────────

    def test_amort_without_decrement_flag_preserves_legacy(self):
        """Sin decrement_quantity, la posición no cambia (comportamiento Fase 1-2)."""
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 76.92, "date": "2026-07-09",
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["qty_decremented"], 0.0)

        conn = main.get_db()
        pos = conn.execute(
            "SELECT quantity, invested FROM positions WHERE user_id=? AND asset='AL30' AND is_cash=0",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertAlmostEqual(pos["quantity"], 1000)
        self.assertAlmostEqual(pos["invested"], 700)

    def test_amort_with_decrement_reduces_quantity_and_invested(self):
        """decrement_quantity=true Y flow_type=amortization → qty y cost basis bajan."""
        # Amortización del 7.692% de 1000 VN = 76.92 (= USD recibidos = face devuelto)
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 76.92, "date": "2026-07-09",
            "decrement_quantity": True,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertAlmostEqual(body["qty_decremented"], 76.92, places=2)
        # invested decrementado proporcional: 700 × (76.92/1000) = 53.844
        self.assertAlmostEqual(body["invested_decremented"], 53.844, places=2)

        conn = main.get_db()
        pos = conn.execute(
            "SELECT quantity, invested FROM positions WHERE user_id=? AND asset='AL30' AND is_cash=0",
            (self.uid,),
        ).fetchone()
        conn.close()
        # Quantity remanente: 1000 - 76.92 = 923.08
        self.assertAlmostEqual(pos["quantity"], 923.08, places=2)
        # Invested remanente: 700 × (1 - 76.92/1000) = 700 × 0.9231 = 646.16
        self.assertAlmostEqual(pos["invested"], 646.156, places=2)
        # Cost basis por VN se preserva: 646.16 / 923.08 = 0.70 ✓
        self.assertAlmostEqual(pos["invested"] / pos["quantity"], 0.70, places=3)

    def test_amort_with_decrement_no_effect_on_coupon(self):
        """flow_type=coupon + decrement_quantity=true: la quantity NO cambia."""
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "coupon", "amount": 5, "date": "2026-07-09",
            "decrement_quantity": True,  # ignorado para coupon
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["qty_decremented"], 0.0)

        conn = main.get_db()
        pos = conn.execute(
            "SELECT quantity FROM positions WHERE user_id=? AND asset='AL30' AND is_cash=0",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertAlmostEqual(pos["quantity"], 1000)

    def test_amort_fifo_across_multiple_lots(self):
        """Si hay múltiples lotes del mismo bono, decrementa FIFO."""
        conn = main.get_db()
        # Agregar segundo lote (más viejo) — debe consumirse primero
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested,
               quantity, buy_price, commissions, entry_date)
               VALUES (?, 'IBKR', 'AL30', 0, 100, 100, 1.00, 0, '2024-01-01')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        # Amort de 150 — debe consumir todo el lote viejo (100) + 50 del nuevo
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 150, "date": "2026-07-09",
            "decrement_quantity": True,
        })
        self.assertEqual(res.status_code, 200, res.text)

        conn = main.get_db()
        lots = conn.execute(
            """SELECT id, quantity, invested FROM positions
               WHERE user_id=? AND asset='AL30' AND is_cash=0
               ORDER BY entry_date""",
            (self.uid,),
        ).fetchall()
        conn.close()
        # El lote viejo debe haberse borrado, queda solo el nuevo con 950 VN
        self.assertEqual(len(lots), 1)
        self.assertAlmostEqual(lots[0]["quantity"], 950)  # 1000 - 50
        # Invested del lote nuevo: 700 × (1 - 50/1000) = 665
        self.assertAlmostEqual(lots[0]["invested"], 665)

    # ─── Realized gain por amort (sub-fix Phase 3D) ──────────────────────────
    # CASO CANÓNICO del audit financiero: la amortización tiene DOS componentes:
    #   1. Devolución de capital (NO ganancia) = cost basis consumido
    #   2. Ganancia realizada = cash recibido − cost basis consumido
    # Que la "ganancia" sea positiva, cero o negativa depende del precio al
    # que se compró el bono vs el face que se devuelve.

    def test_amort_at_par_has_zero_realized_gain(self):
        """Bono comprado a la par: amort = devolución de capital pura, gain = 0."""
        # Setup: comprar 1000 VN a USD 1000 (precio 100/100 = par)
        conn = main.get_db()
        # Borrar la posición de setUp y crear una nueva al par
        conn.execute("DELETE FROM positions WHERE user_id=? AND broker='IBKR' AND is_cash=0", (self.uid,))
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested,
               quantity, buy_price, commissions, entry_date)
               VALUES (?, 'IBKR', 'AL30', 0, 1000, 1000, 1.00, 0, '2024-06-01')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        # Amort de USD 76.92 (= 7.69% del face)
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 76.92, "date": "2026-07-09",
            "decrement_quantity": True,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Cost basis consumido = invested × take/qty = 1000 × 76.92/1000 = 76.92
        self.assertAlmostEqual(body["cost_basis_consumed"], 76.92, places=2)
        # Realized gain = cash − cost_basis = 76.92 − 76.92 = 0
        self.assertAlmostEqual(body["realized_gain"], 0.0, places=2)

    def test_amort_below_par_has_positive_realized_gain(self):
        """Bono comprado BAJO la par: amort tiene ganancia realizada > 0.

        Es el caso típico de los soberanos AR canje 2020 cotizando a ~70%.
        """
        # Setup en setUp: 1000 VN, invested 700 (precio 70/100). Bajo par.
        # Amort de USD 76.92
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 76.92, "date": "2026-07-09",
            "decrement_quantity": True,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Cost basis consumido = 700 × 76.92/1000 = 53.844
        self.assertAlmostEqual(body["cost_basis_consumed"], 53.844, places=2)
        # Realized gain = 76.92 − 53.844 = 23.076 (≈ 30% del face devuelto)
        self.assertAlmostEqual(body["realized_gain"], 23.076, places=2)

    def test_amort_above_par_has_negative_realized_gain(self):
        """Bono comprado en premium (sobre par): amort tiene pérdida realizada."""
        conn = main.get_db()
        conn.execute("DELETE FROM positions WHERE user_id=? AND broker='IBKR' AND is_cash=0", (self.uid,))
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested,
               quantity, buy_price, commissions, entry_date)
               VALUES (?, 'IBKR', 'AL30', 0, 1100, 1000, 1.10, 0, '2024-06-01')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 76.92, "date": "2026-07-09",
            "decrement_quantity": True,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Cost basis consumido = 1100 × 76.92/1000 = 84.612
        self.assertAlmostEqual(body["cost_basis_consumed"], 84.612, places=2)
        # Realized gain = 76.92 − 84.612 = -7.692 (pérdida)
        self.assertAlmostEqual(body["realized_gain"], -7.692, places=2)

    def test_amort_without_decrement_still_computes_cost_basis(self):
        """Aún si decrement_quantity=false, calculamos cost_basis_consumed
        para reportes (el user puede preferir no decrementar pero igual queremos
        el P&L correcto del bono)."""
        # Setup de setUp: 1000 VN invested 700 (bajo par)
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 76.92, "date": "2026-07-09",
            "decrement_quantity": False,  # NO decrementar
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Cost basis consumido SE CALCULA igual (read-only FIFO)
        self.assertAlmostEqual(body["cost_basis_consumed"], 53.844, places=2)
        self.assertAlmostEqual(body["realized_gain"], 23.076, places=2)
        # Pero qty NO cambió
        self.assertEqual(body["qty_decremented"], 0.0)

        conn = main.get_db()
        pos = conn.execute(
            "SELECT quantity, invested FROM positions WHERE user_id=? AND asset='AL30' AND is_cash=0",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertAlmostEqual(pos["quantity"], 1000)
        self.assertAlmostEqual(pos["invested"], 700)

    def test_coupon_has_no_cost_basis_consumed(self):
        """Para cupones, cost_basis_consumed siempre es NULL (no aplica)."""
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "coupon", "amount": 5, "date": "2026-07-09",
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIsNone(body["cost_basis_consumed"])
        self.assertIsNone(body["realized_gain"])

    def test_cost_basis_consumed_persisted_in_operations(self):
        """El valor se guarda en operations.cost_basis_consumed para queries posteriores."""
        self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 50, "date": "2026-07-09",
            "decrement_quantity": True,
        })
        conn = main.get_db()
        op = conn.execute(
            "SELECT pnl_usd, cost_basis_consumed FROM operations WHERE user_id=? AND op_type='Amortización'",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(op["cost_basis_consumed"])
        # 700 × 50/1000 = 35
        self.assertAlmostEqual(op["cost_basis_consumed"], 35, places=2)
        # Pnl_usd sigue guardando el cash neto (50)
        self.assertAlmostEqual(op["pnl_usd"], 50, places=2)

    # ─── Phase 3F: sanity check cross-currency (hallazgo N1 audit final) ─────
    # Bug que detectaba: en broker ARS con bono USD, `amount` está en pesos
    # pero `quantity` está en VN. Tratar amount como face borra la posición
    # entera. Fix: sanity check + face_amortized explícito.

    def test_amort_cross_currency_without_face_amortized_triggers_sanity_check(self):
        """Sin face_amortized, si amount (en moneda broker) >> total qty, abortamos
        decrement para no destruir la posición."""
        # Setup: posición típica AR — Cocos ARS broker, AL30 USD bono.
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'CocosARS', 'ARS')", (self.uid,))
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested,
               quantity, buy_price, commissions, entry_date)
               VALUES (?, 'CocosARS', 'AL30', 0, 715000, 1000, 715, 0, '2024-06-01')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        # User registra amort: 95.000 ARS (= ~76 USD al MEP). 95000 >> 1000 VN.
        res = self._post({
            "broker": "CocosARS", "asset": "AL30",
            "flow_type": "amortization", "amount": 95000, "date": "2026-07-09",
            "decrement_quantity": True,
            # face_amortized NO se manda — bug se manifestaría
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # El sanity check disparó: qty NO se decrementó.
        self.assertEqual(body["qty_decremented"], 0.0)
        self.assertTrue(body["cross_currency_skipped"])

        # Posición sigue intacta
        conn = main.get_db()
        pos = conn.execute(
            "SELECT quantity, invested FROM positions WHERE user_id=? AND broker='CocosARS' AND asset='AL30' AND is_cash=0",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertAlmostEqual(pos["quantity"], 1000)
        self.assertAlmostEqual(pos["invested"], 715000)

    def test_amort_cross_currency_with_face_amortized_decrements_correctly(self):
        """Con face_amortized explícito, decrementa el VN correcto (no el monto ARS)."""
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'CocosARS2', 'ARS')", (self.uid,))
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested,
               quantity, buy_price, commissions, entry_date)
               VALUES (?, 'CocosARS2', 'AL30', 0, 715000, 1000, 715, 0, '2024-06-01')""",
            (self.uid,),
        )
        conn.commit()
        conn.close()

        # User registra amort: 95.000 ARS cash + 76.92 VN amortizados.
        res = self._post({
            "broker": "CocosARS2", "asset": "AL30",
            "flow_type": "amortization",
            "amount": 95000,             # cash en ARS
            "face_amortized": 76.92,      # VN explícito
            "date": "2026-07-09",
            "decrement_quantity": True,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertAlmostEqual(body["qty_decremented"], 76.92, places=2)
        self.assertFalse(body["cross_currency_skipped"])

        conn = main.get_db()
        pos = conn.execute(
            "SELECT quantity, invested FROM positions WHERE user_id=? AND broker='CocosARS2' AND asset='AL30' AND is_cash=0",
            (self.uid,),
        ).fetchone()
        conn.close()
        # Quantity remanente: 1000 - 76.92 = 923.08
        self.assertAlmostEqual(pos["quantity"], 923.08, places=2)
        # Invested remanente proporcional: 715000 × (1 - 76.92/1000) = 660.998
        self.assertAlmostEqual(pos["invested"], 715000 * (1 - 76.92/1000), places=1)

    def test_amort_same_currency_without_face_amortized_still_works(self):
        """Backward compat: en broker USD con bono USD, amount ≈ face → fallback works."""
        # Usar el setup default de setUp: IBKR USD broker + AL30 USD bono
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 76.92, "date": "2026-07-09",
            "decrement_quantity": True,
            # face_amortized no se manda → fallback a amount
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertAlmostEqual(body["qty_decremented"], 76.92, places=2)
        self.assertFalse(body["cross_currency_skipped"])

    def test_amort_with_amount_grossly_exceeding_qty_triggers_sanity_check(self):
        """Phase 3F (post audit final): si amount >> qty (señal típica de
        cross-currency mismatch — usuario pasó ARS donde VN se esperaba),
        el sanity check aborta el decrement. La cobranza igual queda
        registrada. La posición sobrevive intacta.

        Reemplaza el test legacy 'caps_at_available' que asumía decrement
        ciego — eso era exactamente el bug N1 reportado en audit final."""
        res = self._post({
            "broker": "IBKR", "asset": "AL30",
            "flow_type": "amortization", "amount": 9999,  # >> 1000 VN
            "date": "2026-07-09",
            "decrement_quantity": True,
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Sanity check disparado → no decrementa
        self.assertEqual(body["qty_decremented"], 0.0)
        self.assertTrue(body["cross_currency_skipped"])

        # Posición sigue viva con qty original
        conn = main.get_db()
        pos = conn.execute(
            "SELECT quantity FROM positions WHERE user_id=? AND asset='AL30' AND is_cash=0",
            (self.uid,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos["quantity"], 1000)


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
