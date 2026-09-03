"""El "Monto" de una venta en pesos no puede figurar como si fueran dólares.

REPORTE REAL (2026-09-03): en Movimientos, una venta de 485 BPAT a $2.510
aparecía como **US$1.217.350**. Es precio × cantidad en PESOS, rotulado en
dólares: 485 × 2.510 = 1.217.350, sin dividir por ningún TC.

La causa: `entry_price`/`exit_price` viven en la moneda de la operación, pero
el frontend trata `amount_usd` como USD canónico y sólo MULTIPLICA por fx para
mostrarlo en pesos, nunca divide (useHistoricalMoney.js:61). Con el toggle en
pesos era peor todavía: agarraba ese número que YA estaba en pesos y lo volvía
a multiplicar → ~$1.860 millones.

El arreglo usa el `fx_to_usd` que la venta ya sella desde 2026-08-15, que para
una `Venta` ES el tc_venta — el TC exacto de esa fecha, no una inferencia.

Las filas viejas sin FX sellado quedan como estaban, a propósito y por el mismo
criterio que `realized_pnl`: sin el TC del día no hay forma confiable de saber
si el monto ya venía en dólares, y convertirlas a todas sería un bug peor.

Corre con: cd backend && python3 -m pytest tests/test_monto_venta_ars.py
"""
import unittest
import uuid

import main


QTY = 485.0
PRECIO_ARS = 2510.0          # BPAT cotiza en pesos
TC_VENTA = 1528.15           # el MEP del día, sellado en fx_to_usd
BRUTO_ARS = QTY * PRECIO_ARS  # 1.217.350 pesos
BRUTO_USD = BRUTO_ARS / TC_VENTA  # ≈ US$796,62


def _cliente():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class MontoDeVentaEnPesos(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"monto-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,'Cocos','ARS')",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _venta(self, asset, ccy, fx, precio=PRECIO_ARS, qty=QTY, pnl=100.0):
        """Inserta una Venta ya cerrada. Sin entry_date: no genera fila BUY,
        así el test mide sólo la pata que estamos arreglando."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_price, exit_price,
                  quantity, pnl_usd, pnl_pct, currency, fx_to_usd)
               VALUES (?,'2024-12-04','Cocos',?,'Venta',?,?,?,?,NULL,?,?)""",
            (self.uid, asset, precio * 0.9, precio, qty, pnl, ccy, fx),
        )
        conn.commit()
        conn.close()

    def _fila(self, asset):
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = [m for m in r.json()
                 if m.get("asset") == asset and m.get("type") == "SELL"]
        self.assertEqual(len(filas), 1, f"esperaba 1 fila SELL de {asset}: {filas}")
        return filas[0]

    def test_una_venta_en_pesos_vale_sus_dolares(self):
        """485 BPAT a $2.510 con TC 1528,15 son US$796,62 — no US$1.217.350."""
        self._venta("BPAT", "ARS", TC_VENTA)
        monto = self._fila("BPAT")["amount_usd"]
        self.assertAlmostEqual(
            monto, BRUTO_USD, places=2,
            msg=f"la venta debería valer ~US${BRUTO_USD:,.2f}, no US${monto:,.2f}",
        )
        # El síntoma exacto que reportó el usuario, explícito:
        self.assertLess(
            monto, BRUTO_ARS / 100,
            f"sigue mostrando el bruto en pesos como dólares: {monto}",
        )

    def test_una_venta_en_dolares_queda_intacta(self):
        """Sin ARS de por medio no se divide nada."""
        self._venta("NVDA", "USD", 1.0, precio=150.0, qty=10.0)
        self.assertAlmostEqual(self._fila("NVDA")["amount_usd"], 1500.0, places=6)

    def test_una_venta_vieja_sin_fx_sellado_no_se_toca(self):
        """Legacy (fx NULL): se deja como estaba, no se infiere un TC."""
        self._venta("AUSO", None, None, precio=283.43)
        self.assertAlmostEqual(
            self._fila("AUSO")["amount_usd"], 283.43 * QTY, places=4)

    def test_fx_en_cero_no_divide_por_cero(self):
        """Un fx corrupto no puede tumbar la lista ni inflar el monto."""
        self._venta("TX26", "ARS", 0.0)
        self.assertAlmostEqual(self._fila("TX26")["amount_usd"], BRUTO_ARS, places=4)


if __name__ == "__main__":
    unittest.main()
