"""`operations.pnl_usd` NO siempre está en USD — y los 4 lectores tienen que
convertirlo IGUAL.

El bug de producción: un cupón de bono en pesos que el dashboard mostraba como
US$100 y la IA, en el MISMO request, le contaba al usuario como US$125.000. La
columna se llama `pnl_usd` pero en Cupón/Amortización guarda el monto en moneda
del broker. La conversión se agregó a UN lector (el del dashboard) y los otros
tres —los que alimentan a la IA— siguieron sumando la columna cruda.

El escenario de cada test es el caso real: cupón de $125.000 ARS con el MEP del
día sellado en 1250 → tienen que ser US$100, en los cuatro lectores.

Corre con: cd backend && python3 -m pytest tests/test_realized_pnl_cupon.py
"""
import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import realized_pnl
import main

# El caso real de producción.
CUPON_ARS = 125_000.0
MEP = 1250.0
CUPON_USD = 100.0            # 125.000 / 1250


class TestHelperUnitario(unittest.TestCase):
    """El criterio, sin base de datos."""

    def test_cupon_ars_con_fx_se_divide(self):
        row = {"op_type": "Cupón", "pnl_usd": CUPON_ARS,
               "currency": "ARS", "fx_to_usd": MEP}
        self.assertAlmostEqual(realized_pnl.realized_usd(row), CUPON_USD)

    def test_amortizacion_ars_con_fx_se_divide(self):
        row = {"op_type": "Amortización", "pnl_usd": CUPON_ARS,
               "currency": "ARS", "fx_to_usd": MEP}
        self.assertAlmostEqual(realized_pnl.realized_usd(row), CUPON_USD)

    def test_venta_NO_se_divide_aunque_tenga_fx(self):
        """En Venta el pnl_usd YA es USD y fx_to_usd guarda el tc_venta.
        Dividir acá sería el bug opuesto — y hay 56.827 filas así en prod."""
        row = {"op_type": "Venta", "pnl_usd": 500.0,
               "currency": "ARS", "fx_to_usd": MEP}
        self.assertEqual(realized_pnl.realized_usd(row), 500.0)

    def test_fila_vieja_sin_fx_queda_como_esta(self):
        """Decisión explícita: sin FX sellado NO se infiere nada."""
        row = {"op_type": "Cupón", "pnl_usd": CUPON_ARS,
               "currency": "ARS", "fx_to_usd": None}
        self.assertEqual(realized_pnl.realized_usd(row), CUPON_ARS)

    def test_fx_cero_o_negativo_no_divide(self):
        for fx in (0, -1250.0):
            row = {"op_type": "Cupón", "pnl_usd": CUPON_ARS,
                   "currency": "ARS", "fx_to_usd": fx}
            self.assertEqual(realized_pnl.realized_usd(row), CUPON_ARS,
                             f"fx={fx} no debe dividir (ni romper)")

    def test_cupon_en_dolares_no_se_toca(self):
        row = {"op_type": "Cupón", "pnl_usd": 100.0,
               "currency": "USD", "fx_to_usd": 1.0}
        self.assertEqual(realized_pnl.realized_usd(row), 100.0)

    def test_closed_filter_excluye_lo_que_no_es_trade(self):
        for t in ("Compra", "Dividendo", "Interés", "", None,
                  "CONVERSION IMPORT ARS→USDT", "Conversión MEP"):
            self.assertFalse(realized_pnl.is_closed_op(t), f"{t!r} no es un trade")

    def test_closed_filter_deja_pasar_cupon_y_venta(self):
        for t in ("Cupón", "Amortización", "Venta"):
            self.assertTrue(realized_pnl.is_closed_op(t))

    def test_sql_y_python_coinciden(self):
        """Las dos implementaciones del criterio no pueden divergir — que hayan
        divergido es exactamente lo que causó el bug."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE operations (op_type TEXT, pnl_usd REAL, "
                     "currency TEXT, fx_to_usd REAL)")
        casos = [
            ("Cupón", CUPON_ARS, "ARS", MEP),
            ("Cupón", CUPON_ARS, "ARS", None),
            ("Amortización", 5000.0, "ARS", 1000.0),
            ("Venta", 500.0, "ARS", MEP),
            ("Cupón", 100.0, "USD", 1.0),
            ("Venta", -250.0, None, None),
        ]
        conn.executemany("INSERT INTO operations VALUES (?,?,?,?)", casos)
        expr = realized_pnl.realized_usd_sql()
        for row in conn.execute(f"SELECT *, {expr} AS calc FROM operations"):
            self.assertAlmostEqual(
                row["calc"], realized_pnl.realized_usd(row), places=6,
                msg=f"SQL y Python difieren en {row['op_type']}/{row['currency']}",
            )
        conn.close()


def _db_con_cupon(conn, uid):
    """Un cupón en pesos con el MEP sellado + una venta normal en dólares."""
    conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                 (uid, "Cocos", "ARS"))
    conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type,
                                   pnl_usd, currency, fx_to_usd)
           VALUES (?, '2026-08-16', 'Cocos', 'AL35', 'Cupón', ?, 'ARS', ?)""",
        (uid, CUPON_ARS, MEP))
    conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type,
                                   entry_price, exit_price, quantity, pnl_usd)
           VALUES (?, '2026-08-10', 'Cocos', 'NVDA', 'Venta', 100, 150, 5, 250)""",
        (uid,))
    conn.commit()


class TestLectoresDeLaIA(unittest.TestCase):
    """Los 3 lectores que alimentan a la IA."""

    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("operations", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"cupon-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        _db_con_cupon(self.conn, self.uid)

    def tearDown(self):
        for t in ("operations", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    def test_tool_de_la_ia_convierte_el_cupon(self):
        """get_realized_vs_unrealized: el que le habla al usuario en el chat."""
        with patch.object(main, "fetch_prices_for_symbols", return_value={}):
            r = main._execute_ai_tool_inner("get_realized_vs_unrealized", {}, self.uid)
        # 250 de la venta + 100 del cupón = 350. Con el bug daba 125.250.
        self.assertAlmostEqual(r["realized_pnl_usd"], 250 + CUPON_USD, places=2,
                               msg=f"realized_pnl_usd={r['realized_pnl_usd']} — si da "
                                   f"~125.250 está sumando los pesos como si fueran dólares")

    def test_tool_de_la_ia_filtrado_por_asset(self):
        """La rama con asset_filter es OTRA query — tiene que convertir igual."""
        with patch.object(main, "fetch_prices_for_symbols", return_value={}):
            r = main._execute_ai_tool_inner(
                "get_realized_vs_unrealized", {"asset": "AL35"}, self.uid)
        self.assertAlmostEqual(r["realized_pnl_usd"], CUPON_USD, places=2)

    def test_insights_attribution_convierte_el_cupon(self):
        from ai.builders import insights_attribution
        out = insights_attribution.build(self.conn, self.uid)
        por_ticker = {c["ticker"]: c for c in
                      out["top_contributors"] + out["top_detractors"]}
        self.assertIn("AL35", por_ticker, "el cupón debería aparecer atribuido a AL35")
        self.assertAlmostEqual(
            por_ticker["AL35"]["combined_pnl_usd"], CUPON_USD, places=2,
            msg="AL35 con ~125.000 significa que sumó los pesos crudos")


class TestConsistenciaEntreLectores(unittest.TestCase):
    """El punto del ejercicio: que los lectores no vuelvan a divergir."""

    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("operations", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"consist-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        _db_con_cupon(self.conn, self.uid)

    def tearDown(self):
        for t in ("operations", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    def test_el_tool_y_la_atribucion_dan_lo_mismo(self):
        from ai.builders import insights_attribution
        with patch.object(main, "fetch_prices_for_symbols", return_value={}):
            tool = main._execute_ai_tool_inner(
                "get_realized_vs_unrealized", {}, self.uid)["realized_pnl_usd"]
        attr = insights_attribution.build(self.conn, self.uid)
        suma_attr = sum(c["combined_pnl_usd"] for c in
                        attr["top_contributors"] + attr["top_detractors"])
        self.assertAlmostEqual(
            tool, suma_attr, places=2,
            msg=f"los dos lectores de la IA discrepan: {tool} vs {suma_attr}")


if __name__ == "__main__":
    unittest.main()
