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



# ── `Interés PF`: el cuarto tipo que guarda pesos en `pnl_usd` ──────────────
#
# El caso del audit: un plazo fijo de $10.000.000 a 30 días al 40 % TNA paga
# $328.767 de interés. Sin TC sellado y fuera de `_NATIVE_CCY_OPS`, ese número
# entraba como US$328.767 en las 5 pantallas que leen P&L realizado.
PF_CAPITAL = 10_000_000.0
PF_TNA = 0.40
PF_DIAS = 30
PF_INTERES_ARS = PF_CAPITAL * PF_TNA * PF_DIAS / 365   # 328.767,12


class TestInteresPFMoneda(unittest.TestCase):
    """El interés de un PF en pesos no puede leerse como dólares."""

    def test_con_fx_sellado_se_divide(self):
        row = {"op_type": "Interés PF", "pnl_usd": PF_INTERES_ARS,
               "currency": "ARS", "fx_to_usd": MEP}
        self.assertAlmostEqual(realized_pnl.realized_usd(row),
                               PF_INTERES_ARS / MEP, places=6)

    def test_la_fila_vieja_sin_fx_NO_se_mueve(self):
        """Agregarlo a `_NATIVE_CCY_OPS` no puede tocar lo ya escrito.

        Las filas de antes nacieron con `fx_to_usd = NULL`; las dos ramas exigen
        `fx > 0`, así que caen al crudo — exactamente el mismo número que antes
        del cambio. Es lo que hace que el cambio sea seguro sin backfill.
        """
        row = {"op_type": "Interés PF", "pnl_usd": PF_INTERES_ARS,
               "currency": "ARS", "fx_to_usd": None}
        self.assertEqual(realized_pnl.realized_usd(row), PF_INTERES_ARS)

    def test_en_dolares_no_se_toca(self):
        row = {"op_type": "Interés PF", "pnl_usd": 500.0,
               "currency": "USD", "fx_to_usd": 1.0}
        self.assertEqual(realized_pnl.realized_usd(row), 500.0)

    def test_sql_y_python_coinciden_tambien_para_pf(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE operations (op_type TEXT, pnl_usd REAL, "
                     "currency TEXT, fx_to_usd REAL)")
        casos = [
            ("Interés PF", PF_INTERES_ARS, "ARS", MEP),
            ("Interés PF", PF_INTERES_ARS, "ARS", None),
            ("Interés PF", 500.0, "USD", 1.0),
        ]
        conn.executemany("INSERT INTO operations VALUES (?,?,?,?)", casos)
        expr = realized_pnl.realized_usd_sql()
        for row in conn.execute(f"SELECT *, {expr} AS calc FROM operations"):
            self.assertAlmostEqual(row["calc"], realized_pnl.realized_usd(row),
                                   places=6)
        conn.close()

    def test_sigue_contando_como_trade_cerrado(self):
        """NO se tocó: `Interés PF` no está en `_NOT_A_TRADE`, así que suma una
        'operación ganada' a los 6 win rates. Es decisión de producto (cambiarle
        el significado a la métrica) y queda fijado acá para que quien la tome
        tenga que venir a este test, en vez de romperlo de refilón."""
        self.assertTrue(realized_pnl.is_closed_op("Interés PF"))


class TestCobrarPFSellaElTC(unittest.TestCase):
    """El write-path: la fila tiene que NACER con el TC del día del cobro."""

    def setUp(self):
        import datetime as _d
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"pf-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.addCleanup(lambda: self._limpiar())
        hoy = _d.date.today()
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?, 1400, ?, 'manual') ON CONFLICT (date) DO UPDATE SET "
            "mep_venta=EXCLUDED.mep_venta", (hoy.isoformat(), MEP))
        inicio = (hoy - _d.timedelta(days=PF_DIAS)).isoformat()
        cur = self.conn.execute(
            """INSERT INTO plazos_fijos (user_id, banco, capital, moneda, tasa,
                                         rate_type, fecha_inicio, plazo_dias,
                                         fecha_vencimiento)
               VALUES (?, 'Galicia', ?, 'ARS', ?, 'TNA', ?, ?, ?)""",
            (self.uid, PF_CAPITAL, PF_TNA, inicio, PF_DIAS, hoy.isoformat()))
        self.pid = cur.lastrowid
        self.conn.commit()

    def _limpiar(self):
        conn = main.get_db()
        conn.execute("DELETE FROM operations WHERE user_id=?", (self.uid,))
        conn.execute("DELETE FROM plazos_fijos WHERE user_id=?", (self.uid,))
        conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        conn.commit(); conn.close()

    def _cobrar_y_leer(self):
        main.cobrar_plazo_fijo(self.pid, main.CobrarIn(broker=None), uid=self.uid)
        conn = main.get_db()
        row = conn.execute(
            "SELECT * FROM operations WHERE user_id=? AND op_type='Interés PF'",
            (self.uid,)).fetchone()
        conn.close()
        return row

    def test_la_fila_nace_con_el_mep_del_dia(self):
        row = self._cobrar_y_leer()
        self.assertIsNotNone(row, "el cobro tiene que registrar el interés")
        self.assertEqual(row["currency"], "ARS")
        self.assertEqual(row["fx_to_usd"], MEP)

    def test_el_interes_en_pesos_deja_de_leerse_como_dolares(self):
        row = self._cobrar_y_leer()
        # $328.767 al MEP 1250 ⇒ US$263. Sin el fix la app leía US$328.767.
        self.assertAlmostEqual(realized_pnl.realized_usd(row),
                               PF_INTERES_ARS / MEP, delta=1.0)
        self.assertLess(realized_pnl.realized_usd(row), 1000)


if __name__ == "__main__":
    unittest.main()


class TestRepararInteresPFViejo(unittest.TestCase):
    """Las filas que nacieron sin TC: se sella el MEP de su fecha y el recálculo
    las lleva a `monthly_entries`. Atraviesa el mismo camino que producción."""

    def setUp(self):
        import datetime as _d
        self.conn = main.get_db(); self.addCleanup(self.conn.close)
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,'x',1)",
            (f"pfrep-{id(self)}@rendi.test",))
        self.uid = cur.lastrowid; self.addCleanup(self._limpiar)
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Galicia", "ARS"))
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) VALUES "
            "('2026-08-01', 1400, ?, 'manual') ON CONFLICT (date) DO UPDATE SET mep_venta=EXCLUDED.mep_venta",
            (MEP,))
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd, currency, fx_to_usd)
               VALUES (?, '2026-08-05', 'Galicia', 'Galicia', 'Interés PF', ?, 'ARS', NULL)""",
            (self.uid, PF_INTERES_ARS))
        self.conn.commit()

    def _limpiar(self):
        c = main.get_db()
        for t in ("operations", "monthly_entries", "brokers"):
            c.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
        c.execute("DELETE FROM users WHERE id=?", (self.uid,)); c.commit(); c.close()

    def _fila(self):
        return main.get_db().execute(
            "SELECT fx_to_usd FROM operations WHERE user_id=? AND op_type='Interés PF'",
            (self.uid,)).fetchone()["fx_to_usd"]

    def test_preview_lista_sin_tocar(self):
        r = main._repair_interes_pf(self.conn, apply=False)
        mias = [c for c in r["filas_a_sellar"] if c["fecha"] == "2026-08-05"]
        self.assertEqual(len(mias), 1)
        self.assertEqual(mias[0]["tc"], MEP)
        self.assertIsNone(self._fila(), "el preview escribió")

    def test_aplicar_sella_y_el_recalculo_lo_lleva_al_mensual(self):
        main._repair_interes_pf(self.conn, apply=True)
        self.assertEqual(self._fila(), MEP)
        # El escritor POSTERIOR: monthly_entries tiene que quedar en USD reales.
        m = main.get_db().execute(
            "SELECT pnl_realized FROM monthly_entries WHERE user_id=? AND broker='global' "
            "AND year=2026 AND month=8", (self.uid,)).fetchone()
        self.assertIsNotNone(m, "el recálculo no escribió el mes")
        self.assertAlmostEqual(m["pnl_realized"], PF_INTERES_ARS / MEP, delta=1.0)

    def test_segunda_pasada_no_toca_nada(self):
        main._repair_interes_pf(self.conn, apply=True)
        r = main._repair_interes_pf(self.conn, apply=True)
        self.assertEqual([c for c in r["filas_a_sellar"] if c["fecha"] == "2026-08-05"], [])


class TestRepararCaja1415(unittest.TestCase):
    """El dólar correcto es el de la FECHA DE RECONCILIACIÓN (pesos de ese día),
    reconstruida del lote confirmado — no el del mes anotado, que es el más viejo
    del broker y puede ser 2021."""

    PESOS = 1_415_000.0
    USD_VIEJO = 1000.0            # la firma: 1.415.000 / 1415
    MEP_RECONCILIACION = 1250.0   # 2026-06-01, el día del lote
    MEP_MES_ANOTADO = 152.0       # 2021-05-01 — el que NO hay que usar

    def setUp(self):
        self.conn = main.get_db(); self.addCleanup(self.conn.close)
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,'x',1)",
            (f"caja1415-{id(self)}@rendi.test",))
        self.uid = cur.lastrowid; self.addCleanup(self._limpiar)
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "ARS"))
        for d, mep in (("2021-05-01", self.MEP_MES_ANOTADO), ("2026-06-01", self.MEP_RECONCILIACION)):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) VALUES (?, ?, ?, 'manual') "
                "ON CONFLICT (date) DO UPDATE SET mep_venta=EXCLUDED.mep_venta", (d, mep, mep))
        self.conn.execute(
            """INSERT INTO import_batches (user_id, broker, parser_format, file_name, file_hash,
                   total_rows, valid_rows, invalid_rows, status, created_at, confirmed_at)
               VALUES (?, 'Cocos', 'cocos', 'x.csv', ?, 1, 1, 0, 'confirmed',
                       '2026-06-01T10:00:00', '2026-06-01T10:05:00')""",
            (self.uid, f"h-{id(self)}"))
        for broker in ("Cocos", "global"):
            self.conn.execute(
                """INSERT INTO monthly_entries (user_id, year, month, broker, deposits, withdrawals,
                       manual_deposits, manual_deposits_native, pnl_realized, pnl_unrealized,
                       capital_inicio, capital_final)
                   VALUES (?, 2021, 5, ?, ?, 0, ?, ?, 0, 0, 0, ?)""",
                (self.uid, broker, self.USD_VIEJO, self.USD_VIEJO, self.PESOS, self.USD_VIEJO))
        self.conn.commit()

    def _limpiar(self):
        c = main.get_db()
        for t in ("monthly_entries", "brokers", "import_batches"):
            c.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
        c.execute("DELETE FROM users WHERE id=?", (self.uid,)); c.commit(); c.close()

    def _fila(self, broker):
        return main.get_db().execute(
            "SELECT manual_deposits, deposits FROM monthly_entries WHERE user_id=? AND broker=? "
            "AND year=2021 AND month=5", (self.uid, broker)).fetchone()

    def _mio(self, r):
        return [c for c in r["meses_a_corregir"] if c["broker"] == "Cocos" and c["mes"] == "2021-05"]

    def test_usa_el_dolar_del_dia_de_la_reconciliacion_no_el_del_mes_anotado(self):
        r = main._repair_caja_1415(self.conn, apply=False)
        (m,) = self._mio(r)
        self.assertEqual(m["reconciliado_el"], "2026-06-01")
        self.assertEqual(m["tc_nuevo"], self.MEP_RECONCILIACION)
        self.assertAlmostEqual(m["manual_deposits"]["usd_despues"], self.PESOS / self.MEP_RECONCILIACION, places=2)
        self.assertLess(m["manual_deposits"]["usd_despues"], 2000)   # con el de 2021 daría 9.309
        self.assertEqual(self._fila("Cocos")["manual_deposits"], self.USD_VIEJO, "el preview escribió")

    def test_el_total_separa_depositos_de_retiros(self):
        r = main._repair_caja_1415(self.conn, apply=False)
        nuevo = round(self.PESOS / self.MEP_RECONCILIACION, 2)
        self.assertAlmostEqual(r["delta_depositos_usd"], nuevo - self.USD_VIEJO, places=1)
        self.assertAlmostEqual(r["cambio_capital_aportado_usd"], nuevo - self.USD_VIEJO, places=1)

    def test_sin_lote_confirmado_no_se_toca(self):
        c = main.get_db(); c.execute("DELETE FROM import_batches WHERE user_id=?", (self.uid,)); c.commit(); c.close()
        r = main._repair_caja_1415(self.conn, apply=True)
        self.assertEqual(self._mio(r), [])
        self.assertTrue(any(x["broker"] == "Cocos" for x in r["sin_fecha"]))
        self.assertEqual(self._fila("Cocos")["manual_deposits"], self.USD_VIEJO)

    def test_aplicar_corrige_el_broker_y_el_recalculo_arrastra_deposits_y_global(self):
        main._repair_caja_1415(self.conn, apply=True)
        nuevo = round(self.PESOS / self.MEP_RECONCILIACION, 2)
        self.assertAlmostEqual(self._fila("Cocos")["manual_deposits"], nuevo, places=2)
        self.assertAlmostEqual(self._fila("Cocos")["deposits"], nuevo, places=2)
        self.assertAlmostEqual(self._fila("global")["deposits"], nuevo, places=2)

    def test_segunda_pasada_no_toca_nada(self):
        main._repair_caja_1415(self.conn, apply=True)
        r = main._repair_caja_1415(self.conn, apply=True)
        self.assertEqual(self._mio(r), [])


class TestReconcileCashDolarizaAlDolarDeHoy(unittest.TestCase):
    """Hacia adelante: la reconciliación se anota en el mes más viejo del broker
    (puede ser 2021) pero los pesos son de HOY. El endpoint dolariza a hoy."""

    def test_el_endpoint_usa_hoy_y_no_el_mes_anotado(self):
        src = open(os.path.join(BACKEND, "main.py"), encoding="utf-8").read()
        i = src.index('@app.post("/api/brokers/reconcile-cash")')
        L = src[i:i + 8000]
        self.assertIn("_ref_date = _iso_today()", L)
        self.assertNotIn('f"{target_year:04d}-{target_month:02d}-01"', L)
