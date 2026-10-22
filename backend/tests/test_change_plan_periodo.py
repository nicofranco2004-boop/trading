"""RENDI-B02: pasar de mensual a anual (mismo plan) NO debe fabricar días.

El crédito se valúa al rate del período que la persona PAGÓ; cambiar de período
sólo reetiqueta, no regala el descuento anual sobre crédito ya comprado. El cambio
de PLAN (plus<->pro) sí ajusta por el ratio de precios, en el mismo período.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402
from billing import credits as C  # noqa: E402


def _user_con_credito(plan, period, dias):
    conn = main.get_db()
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,?)",
        (f"cp-{os.urandom(4).hex()}@rendi.test", "x", plan)).lastrowid
    hasta = (datetime.utcnow() + timedelta(days=dias)).isoformat()
    conn.execute(
        "UPDATE users SET credit_active_until=?, credit_anchor_plan=?, "
        "credit_anchor_period=?, credit_anchor_amount_usd=?, credit_anchor_at=? WHERE id=?",
        (hasta, plan, period, C.PLAN_PRICES_USD[(plan, period)], datetime.utcnow().isoformat(), uid))
    conn.commit()
    conn.close()
    return uid


class CambioDePeriodoTest(unittest.TestCase):
    def test_mensual_a_anual_mismo_plan_no_regala_dias(self):
        conn = main.get_db()
        try:
            uid = _user_con_credito("plus", "monthly", 30)
            r = C.convert_plan(conn, uid, "plus", "annual")
            # Cambiar de período no agrega días: sigue con ~30 (los que pagó).
            self.assertAlmostEqual(r["days_remaining"], 30.0, places=1)
        finally:
            conn.close()

    def test_mensual_a_anual_pro_tampoco(self):
        conn = main.get_db()
        try:
            uid = _user_con_credito("pro", "monthly", 30)
            r = C.convert_plan(conn, uid, "pro", "annual")
            self.assertAlmostEqual(r["days_remaining"], 30.0, places=1)
        finally:
            conn.close()

    def test_cambio_de_plan_mismo_periodo_sigue_ajustando(self):
        # plus->pro mensual: pro es más caro, así que el crédito rinde MENOS días.
        conn = main.get_db()
        try:
            uid = _user_con_credito("plus", "monthly", 30)
            r = C.convert_plan(conn, uid, "pro", "monthly")
            self.assertLess(r["days_remaining"], 30.0)
            self.assertGreater(r["days_remaining"], 0.0)
        finally:
            conn.close()
