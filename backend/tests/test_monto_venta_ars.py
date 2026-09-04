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


# ─────────────────────────────────────────────────────────────────────────────
# La pata COMPRA de una venta: el mismo bug, con otro dólar.
#
# REPORTE REAL (2026-09-03), verificado contra el Excel del usuario: AUSO en
# Movimientos mostraba la compra de 485 a $67 (32.495 pesos de 2021) como
# "US$32.495" — el número más grande de la pantalla para la compra más chica
# del activo. La compra pasó en 2021 y la venta en 2022: cada una vale su
# propio dólar, y el de la compra sale de `fx_for_date(entry_date)`, que es la
# misma función con la que se rellena `positions.tc_compra`.
# ─────────────────────────────────────────────────────────────────────────────

TC_COMPRA_2021 = 161.33   # el dólar del 03-jun-2021
TC_VENTA_2022 = 269.39    # el dólar del 12-sep-2022
AUSO_QTY = 485.0
AUSO_COMPRA = 67.0
AUSO_VENTA = 283.43


class PataCompraDeUnaVenta(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"compra-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,'Default','ARS')",
            (self.uid,),
        )
        for fecha, tc in (("2021-06-03", TC_COMPRA_2021), ("2022-09-12", TC_VENTA_2022)):
            conn.execute(
                "INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta) "
                "VALUES (?,?,?)", (fecha, tc, tc))
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_date, entry_price,
                  exit_price, quantity, pnl_usd, pnl_pct, currency, fx_to_usd)
               VALUES (?,'2022-09-12','Default','AUSO','Venta','2021-06-03',?,?,?,
                       388.81,NULL,'ARS',?)""",
            (self.uid, AUSO_COMPRA, AUSO_VENTA, AUSO_QTY, TC_VENTA_2022),
        )
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _filas(self):
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        por_tipo = {m["type"]: m for m in r.json() if m.get("asset") == "AUSO"}
        self.assertIn("BUY", por_tipo)
        self.assertIn("SELL", por_tipo)
        return por_tipo

    def test_la_compra_vale_el_dolar_de_su_propia_fecha(self):
        """485 a $67 en 2021 son ~US$201, no US$32.495."""
        esperado = (AUSO_QTY * AUSO_COMPRA) / TC_COMPRA_2021
        monto = self._filas()["BUY"]["amount_usd"]
        self.assertAlmostEqual(
            monto, esperado, places=2,
            msg=f"la compra debería valer ~US${esperado:,.2f}, no US${monto:,.2f}")

    def test_la_compra_no_usa_el_dolar_de_la_venta(self):
        """El error sutil: convertir las dos patas con el TC de la venta.

        Daría US$120 en vez de US$201 — plausible a simple vista, y encima
        borraría la ganancia en dólares del activo.
        """
        monto = self._filas()["BUY"]["amount_usd"]
        con_tc_de_venta = (AUSO_QTY * AUSO_COMPRA) / TC_VENTA_2022
        self.assertNotAlmostEqual(monto, con_tc_de_venta, places=2)

    def test_cada_pata_con_su_dolar(self):
        """La venta sigue con el suyo: las dos conviven en la misma fila."""
        filas = self._filas()
        self.assertAlmostEqual(
            filas["SELL"]["amount_usd"],
            (AUSO_QTY * AUSO_VENTA) / TC_VENTA_2022, places=2)

    def test_una_compra_en_dolares_no_se_toca(self):
        """Sin ARS de por medio, la pata compra queda como está."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_date, entry_price,
                  exit_price, quantity, pnl_usd, pnl_pct, currency, fx_to_usd)
               VALUES (?,'2022-09-12','Default','NVDA','Venta','2021-06-03',
                       100.0,150.0,10.0,500.0,NULL,'USD',NULL)""",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/movements", headers=self.h)
        buy = [m for m in r.json()
               if m.get("asset") == "NVDA" and m["type"] == "BUY"][0]
        self.assertAlmostEqual(buy["amount_usd"], 1000.0, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# Las COMISIONES: el mismo bug, tercera superficie.
#
# REPORTE REAL (2026-09-04): el KPI de Movimientos decía "Comisiones US$24.718"
# contra "Aportado neto US$14.988" — más fees que plata puesta. `commissions` se
# guarda en moneda NATIVA (la venta estampa `chunk_commission_native`; la
# posición, lo que se pagó al comprar), y el KPI suma `fees_usd` de TODAS las
# filas (Operations.jsx:1160). Sin convertir, las comisiones en pesos entraban
# como dólares.
#
# El detalle que lo delataba: en la fila de una posición abierta, `invested` YA
# se convertía y la comisión de esa MISMA fila no.
# ─────────────────────────────────────────────────────────────────────────────

COMI_VENTA_ARS = 964.73    # AUSO 12-sep-2022, del Excel del usuario
COMI_COMPRA_ARS = 4391.50  # AUSO 16-dic-2024
TC_COMPRA_2024 = 1098.30


class ComisionesEnPesos(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"comi-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,'Default','ARS')",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _movs(self):
        r = self.client.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _fila(self, asset, tipo):
        f = [m for m in self._movs()
             if m.get("asset") == asset and m.get("type") == tipo]
        self.assertEqual(len(f), 1, f"esperaba 1 fila {tipo} de {asset}: {f}")
        return f[0]

    def test_la_comision_de_una_venta_en_pesos_vale_sus_dolares(self):
        """$964,73 al TC de la venta son ~US$3,58 — no US$964,73."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_price, exit_price,
                  quantity, pnl_usd, pnl_pct, commissions, currency, fx_to_usd)
               VALUES (?,'2022-09-12','Default','AUSO','Venta',67.0,283.43,485.0,
                       388.81,NULL,?,'ARS',?)""",
            (self.uid, COMI_VENTA_ARS, TC_VENTA_2022),
        )
        conn.commit()
        conn.close()
        esperado = COMI_VENTA_ARS / TC_VENTA_2022
        real = self._fila("AUSO", "SELL")["fees_usd"]
        self.assertAlmostEqual(
            real, esperado, places=4,
            msg=f"la comisión debería ser ~US${esperado:,.2f}, no US${real:,.2f}")

    def test_la_comision_de_una_posicion_abierta_tambien(self):
        """La fila ya convertía `invested`; la comisión iba en pesos."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions
                 (user_id, broker, asset, is_cash, buy_price, quantity, invested,
                  tc_compra, entry_date, currency, commissions)
               VALUES (?,'Default','AUSO',0,3525.0,1287.0,4536675.0,?,'2024-12-16','ARS',?)""",
            (self.uid, TC_COMPRA_2024, COMI_COMPRA_ARS),
        )
        conn.commit()
        conn.close()
        fila = self._fila("AUSO", "BUY")
        self.assertAlmostEqual(
            fila["fees_usd"], COMI_COMPRA_ARS / TC_COMPRA_2024, places=4)
        # La guarda que delataba el bug: las dos cifras de la fila, mismo dólar.
        self.assertAlmostEqual(
            fila["amount_usd"], 4536675.0 / TC_COMPRA_2024, places=4)

    def test_las_comisiones_en_dolares_no_se_tocan(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_price, exit_price,
                  quantity, pnl_usd, pnl_pct, commissions, currency, fx_to_usd)
               VALUES (?,'2022-09-12','Default','NVDA','Venta',100.0,150.0,10.0,
                       500.0,NULL,7.5,'USD',NULL)""",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        self.assertAlmostEqual(self._fila("NVDA", "SELL")["fees_usd"], 7.5, places=6)

    def test_las_comisiones_no_pueden_superar_lo_aportado(self):
        """La forma del reporte: el total de fees tiene que ser plausible."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_price, exit_price,
                  quantity, pnl_usd, pnl_pct, commissions, currency, fx_to_usd)
               VALUES (?,'2022-09-12','Default','AUSO','Venta',67.0,283.43,485.0,
                       388.81,NULL,?,'ARS',?)""",
            (self.uid, COMI_VENTA_ARS, TC_VENTA_2022),
        )
        conn.commit()
        conn.close()
        total_fees = sum(m.get("fees_usd") or 0 for m in self._movs())
        self.assertLess(
            total_fees, 100.0,
            f"US${total_fees:,.2f} de comisiones por una sola venta chica: "
            f"está sumando pesos como dólares")


if __name__ == "__main__":
    unittest.main()
