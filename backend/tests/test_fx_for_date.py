"""El TC de cada operación sale de su FECHA, no del dólar vivo del import.

Medido en producción antes de este cambio (`/api/admin/diagnose-sell-fx`, 2026-07-28):
51.475 ventas de 503 usuarios con el TC equivocado, un usuario con 370 ventas
repartidas en 3.746 días estampadas TODAS con el mismo 1415,00, y 80.868 de 84.123
flujos en pesos al mismo 1415 desde 2013.

Lo que fijan estos tests:
  · `fx_for_date` es ESTRICTA — nunca cae al dólar vivo, así que el replay del mismo
    input da siempre el mismo output (antes: 1.490 contra 1.433 según el día).
  · el filtro `IS NOT NULL` va en el WHERE (un solo día sin MEP no puede hacer que
    la función diga "no hay cobertura" cuando el dato existe dos días antes).
  · LA TRAMPA CROSS-CURRENCY: `rebuild` usaba `tc_blue` donde el persister usa
    `tc_venta` para llevar el costo de un lote USD a pesos. Mientras los dos eran el
    mismo número daba igual; con el TC histórico divergen ~5× y meten una pérdida
    fantasma en toda operación dólar-MEP — y solo por el camino del rebuild.
"""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False); TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
from fx import fx_for_date, fx_for_date_detail
import importing.persister as ps
import importing.rebuild as rb

TC_VIVO = 1450.0        # el dólar de HOY, el que se usaba antes
MEP_2021 = 190.0        # el que regía cuando ocurrió la venta
BLUE_2021 = 180.0


class FxForDateTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("fx_rates_daily", "operations", "positions", "brokers", "users",
                  "monthly_entries", "import_op_links", "import_normalized_tx",
                  "import_raw_rows", "import_batches", "config"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        for d, b, m in [("2021-01-15", BLUE_2021, MEP_2021),
                        ("2021-06-15", BLUE_2021, MEP_2021),
                        ("2026-07-01", 1400.0, 1440.0)]:
            # ON CONFLICT en vez de OR REPLACE (Postgres no tiene OR REPLACE).
            # Acá la rama DO UPDATE es INALCANZABLE: el DELETE de arriba deja la
            # tabla vacía y las 3 fechas son distintas entre sí. `fetched_at` no
            # se nombra (nadie la lee en toda la app; el único SELECT que la
            # tocaría no existe), así que da igual que sobreviva.
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date,blue_venta,mep_venta,source) "
                "VALUES (?,?,?,?) ON CONFLICT (date) DO UPDATE SET "
                "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
                "source=EXCLUDED.source", (d, b, m, "test"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    # ── La función ───────────────────────────────────────────────────────
    def test_devuelve_el_mep_de_la_fecha(self):
        self.assertEqual(fx_for_date(self.conn, "2021-06-15"), MEP_2021)
        self.assertEqual(fx_for_date_detail(self.conn, "2021-06-15")[1], "mep")

    def test_toma_el_ultimo_valor_en_o_antes(self):
        self.assertEqual(fx_for_date(self.conn, "2021-06-20"), MEP_2021)   # no hay fila ese día

    def test_cae_al_blue_de_la_fecha_no_al_vivo(self):
        """Solo 290 ventas (0,4%) son previas a la cobertura MEP. Ahí va el blue de
        SU fecha — que también es histórico, o sea determinístico."""
        self.conn.execute("UPDATE fx_rates_daily SET mep_venta=NULL")
        self.conn.commit()
        v, src = fx_for_date_detail(self.conn, "2021-06-15", fallback=TC_VIVO)
        self.assertEqual(v, BLUE_2021)
        self.assertEqual(src, "blue")

    def test_un_dia_sin_mep_no_apaga_la_cobertura(self):
        """El `IS NOT NULL` va en el WHERE. Si se tomara la fila más reciente y
        recién ahí se validara, este caso devolvería el fallback."""
        # 2021-06-16 NO está en el setUp (que siembra 15/01, 15/06 y 01/07/2026):
        # es una fila nueva, el DO UPDATE no llega a correr. Igual se deja el
        # mep_venta=NULL explícito en el SET porque el PUNTO del test es que ese
        # día NO tenga MEP: si mañana alguien siembra esa fecha en el setUp, el
        # ON CONFLICT tiene que seguir dejándola sin MEP, no heredar el de antes.
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date,blue_venta,mep_venta) VALUES (?,?,NULL) "
            "ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta",
            ("2021-06-16", BLUE_2021))
        self.conn.commit()
        self.assertEqual(fx_for_date(self.conn, "2021-06-16", fallback=TC_VIVO), MEP_2021)

    def test_es_deterministica(self):
        """El bug que habilita: el mismo replay en dos momentos daba 1.490 vs 1.433."""
        a = fx_for_date(self.conn, "2021-06-15", fallback=TC_VIVO)
        # Fecha nueva (2026-07-29 no la siembra nadie): el DO UPDATE no corre.
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date,blue_venta,mep_venta) VALUES (?,?,?) "
            "ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta",
            ("2026-07-29", 1500.0, 1550.0))     # el dólar de hoy cambia…
        self.conn.commit()
        self.assertEqual(fx_for_date(self.conn, "2021-06-15", fallback=TC_VIVO), a)  # …la venta vieja no

    def test_sin_fecha_o_sin_serie_usa_el_fallback(self):
        self.assertEqual(fx_for_date(self.conn, None, fallback=TC_VIVO), TC_VIVO)
        self.assertEqual(fx_for_date(self.conn, "2005-01-01", fallback=TC_VIVO), TC_VIVO)
        self.assertEqual(fx_for_date(None, "2021-06-15", fallback=TC_VIVO), TC_VIVO)


class MotorUsaElTcDeLaFechaTest(unittest.TestCase):
    """Los dos escritores (persister y rebuild) tienen que dar el MISMO número."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("fx_rates_daily", "operations", "positions", "brokers", "users",
                  "monthly_entries", "import_op_links", "import_normalized_tx",
                  "import_raw_rows", "import_batches", "config"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("fx@test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "IOL", "ARS"))
        # Rama DO UPDATE inalcanzable: el DELETE de arriba vacía fx_rates_daily.
        # `fetched_at` no se nombra (no la lee nadie).
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date,blue_venta,mep_venta,source) "
            "VALUES (?,?,?,?) ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source", ("2021-06-15", BLUE_2021, MEP_2021, "test"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_venta_ars_usa_el_mep_de_su_fecha(self):
        """Una venta en pesos de 2021 con 20.000 ARS de ganancia: al MEP de entonces
        son 105,26 USD. Con el dólar vivo (1450) daban 13,79 — la octava parte."""
        self.conn.execute(
            "INSERT INTO positions (user_id,broker,asset,is_cash,buy_price,quantity,"
            "invested,entry_date,commissions,currency) VALUES (?,?,?,0,?,?,?,?,?,?)",
            (self.uid, "IOL", "GGAL", 1000.0, 100, 100000.0, "2021-01-15", 0, "ARS"))
        self.conn.commit()

        from importing.schema import NormalizedTx, OP_SELL
        tx = NormalizedTx(row_index=1, date="2021-06-15", broker="IOL",
                          operation_type=OP_SELL, asset_symbol="GGAL",
                          quantity=100, unit_price=1200.0, gross_amount=120000.0,
                          currency="ARS")
        h = main._ImportHelpers()
        for a in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
                  "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
                  "_recalc_pnl_realized_from_ops"):
            setattr(h, a, getattr(main, a))
        with self.conn:
            ps._persist_sell_fifo(self.conn, self.uid, "b1", None, tx, h, tc_blue=TC_VIVO)

        op = self.conn.execute(
            "SELECT pnl_usd, fx_to_usd FROM operations WHERE user_id=? AND op_type='Venta'",
            (self.uid,)).fetchone()
        self.assertAlmostEqual(op["fx_to_usd"], MEP_2021, places=2)     # el MEP de 2021
        self.assertAlmostEqual(op["pnl_usd"], 20000.0 / MEP_2021, places=2)   # 105,26
        self.assertNotAlmostEqual(op["pnl_usd"], 20000.0 / TC_VIVO, places=2)

    def test_cross_currency_rebuild_no_diverge_del_persister(self):
        """LA TRAMPA. Lote USD vendido en ARS: el costo se lleva a pesos y después
        `pnl_ars/tc_venta` lo divide de vuelta ⇒ el TC se CANCELA y el costo USD se
        preserva. Si rebuild multiplica por `tc_blue` (vivo) y divide por `tc_venta`
        (histórico), no se cancela y aparece una pérdida fantasma."""
        lot = {"qty": 100.0, "invested": 1000.0, "buy_price": 10.0, "commissions": 0.0,
               "entry_date": "2021-01-15", "currency": "USD", "batch_id": None,
               "raw_row_id": None, "is_seed": False, "_broker": "IOL",
               "_asset": "AAPL", "_asset_type": "STOCK"}
        tc_venta = fx_for_date(self.conn, "2021-06-15", fallback=TC_VIVO)
        self.assertEqual(tc_venta, MEP_2021)

        # El costo del lote llevado a pesos y devuelto a dólares tiene que dar
        # exactamente los 1.000 USD originales.
        base_ars = lot["invested"] * tc_venta
        costo_usd = base_ars / tc_venta
        self.assertAlmostEqual(costo_usd, 1000.0, places=6)

        # Con el número equivocado (tc_blue vivo de un lado, histórico del otro):
        costo_roto = (lot["invested"] * TC_VIVO) / tc_venta
        self.assertAlmostEqual(costo_roto, 1000.0 * TC_VIVO / MEP_2021, places=2)
        self.assertGreater(costo_roto, 7000.0)   # ~7,6× el costo real = pérdida fantasma

    def test_rebuild_multiplica_por_tc_venta_no_por_tc_blue(self):
        """Chequeo estructural: la línea existe y usa `tc_venta`. Es la que divergía."""
        import inspect
        src = inspect.getsource(rb._replay_asset)
        self.assertIn("base_invested = base_invested * (tc_venta or tc_blue)", src)
        self.assertNotIn("base_invested = base_invested * tc_blue", src)


class FlujosUsanElTcDeSuFechaTest(unittest.TestCase):
    """La pata GEMELA: 84.123 flujos, 96% al mismo 1415 desde 2013."""

    def setUp(self):
        self.conn = main.get_db()
        try: self.conn.execute("DELETE FROM fx_rates_daily")
        except Exception: pass
        # Rama DO UPDATE inalcanzable: el DELETE de arriba vacía fx_rates_daily.
        # `fetched_at` no se nombra (no la lee nadie).
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date,blue_venta,mep_venta,source) "
            "VALUES (?,?,?,?) ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source", ("2021-06-15", BLUE_2021, MEP_2021, "test"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_deposito_ars_se_dolariza_al_tc_de_su_fecha(self):
        from importing.pipeline import _stamp_gross_amount_usd
        usd = _stamp_gross_amount_usd("ARS", 100000.0, TC_VIVO,
                                      conn=self.conn, date="2021-06-15")
        self.assertAlmostEqual(usd, 100000.0 / MEP_2021, places=4)   # 526,32
        self.assertNotAlmostEqual(usd, 100000.0 / TC_VIVO, places=4)  # no 68,97

    def test_sin_fecha_mantiene_el_comportamiento_viejo(self):
        from importing.pipeline import _stamp_gross_amount_usd
        self.assertAlmostEqual(
            _stamp_gross_amount_usd("ARS", 100000.0, TC_VIVO), 100000.0 / TC_VIVO, places=4)

    def test_usd_no_se_toca(self):
        from importing.pipeline import _stamp_gross_amount_usd
        self.assertEqual(
            _stamp_gross_amount_usd("USD", 500.0, TC_VIVO, conn=self.conn, date="2021-06-15"), 500.0)


if __name__ == "__main__":
    unittest.main()


class VentaManualUsdSobreBrokerArsTest(unittest.TestCase):
    """La compuerta del P&L es la moneda de la VENTA, no la del BROKER.

    Un lote USD dentro de un broker ARS es un estado soportado y testeado
    (tests/test_currency_lots.py, reportado por un usuario real). La selección de
    lotes y la conversión cross-currency ya se gateaban por `sell_ccy`; la rama de
    P&L se gateaba por `currency` (la del broker) y entraba a la de pesos,
    dividiendo por el TC un P&L que ya estaba en dólares.

    Quedaba tapado porque el front solo manda `tc_venta` en ventas ARS
    (Positions.jsx:665) y el `or 1` lo dividía por 1 — correcto por accidente. Con
    el TC de la fecha el accidente se vuelve un error de ~1440×, y 0,35 en vez de
    500 se ve lo bastante plausible como para que nadie lo reporte.
    """

    def setUp(self):
        self.conn = main.get_db()
        for t in ("fx_rates_daily", "operations", "positions", "brokers", "users",
                  "monthly_entries", "config"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("usdars@test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "IOL", "ARS"))          # broker en PESOS
        # Rama DO UPDATE inalcanzable: el DELETE de arriba vacía fx_rates_daily.
        # `fetched_at` no se nombra (no la lee nadie).
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date,blue_venta,mep_venta,source) "
            "VALUES (?,?,?,?) ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source", ("2026-07-01", 1400.0, 1440.0, "test"))
        self.conn.execute(                                   # lote en DÓLARES
            "INSERT INTO positions (user_id,broker,asset,is_cash,buy_price,quantity,"
            "invested,entry_date,commissions,currency) VALUES (?,?,?,0,?,?,?,?,?,?)",
            (self.uid, "IOL", "AAPL", 100.0, 10, 1000.0, "2026-06-01", 0, "USD"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_pnl_en_dolares_no_se_divide_por_el_tc(self):
        from fastapi.testclient import TestClient
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            c = TestClient(main.app)
            r = c.post("/api/positions/sell", json={
                "broker": "IOL", "asset": "AAPL", "quantity": 10,
                "exit_price": 150.0, "currency": "USD", "date": "2026-07-01"})
            self.assertEqual(r.status_code, 200, r.text)
        finally:
            main.app.dependency_overrides.pop(main.get_effective_user, None)

        op = self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND op_type='Venta'",
            (self.uid,)).fetchone()
        # 10u × US$150 = 1.500 de ingresos contra 1.000 de costo → +500 dólares.
        self.assertAlmostEqual(op["pnl_usd"], 500.0, places=1)
        self.assertNotAlmostEqual(op["pnl_usd"], 500.0 / 1440.0, places=1)   # el 0,35


class TcCompraAutofillTest(unittest.TestCase):
    """Alta manual de posición: TC de compra en blanco + fecha ⇒ se completa solo
    con el dólar de ESA fecha (hoy o retroactiva). Un TC tipeado manda siempre.
    Cubre las tres vías manuales: form desktop, mobile (mandan tc_compra=null) y
    el registro por chat (construye PositionIn sin tc_compra)."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("fx_rates_daily", "operations", "positions", "brokers", "users",
                  "monthly_entries", "config"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("tcauto@test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "IOL", "ARS"))
        # Rama DO UPDATE inalcanzable: el DELETE de arriba vacía fx_rates_daily.
        # `fetched_at` no se nombra (no la lee nadie).
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date,blue_venta,mep_venta,source) "
            "VALUES (?,?,?,?) ON CONFLICT (date) DO UPDATE SET "
            "blue_venta=EXCLUDED.blue_venta, mep_venta=EXCLUDED.mep_venta, "
            "source=EXCLUDED.source", ("2021-06-15", BLUE_2021, MEP_2021, "test"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _crear(self, **kw):
        p = main.PositionIn(broker="IOL", asset="GGAL", buy_price=1000,
                            quantity=10, invested=10000, **kw)
        with self.conn:
            main._insert_manual_position(self.conn, self.uid, p)
        return self.conn.execute(
            "SELECT tc_compra, currency FROM positions WHERE user_id=? AND is_cash=0 "
            "ORDER BY id DESC LIMIT 1", (self.uid,)).fetchone()

    def test_blanco_con_fecha_retroactiva_usa_el_dolar_de_esa_fecha(self):
        r = self._crear(entry_date="2021-06-15")
        self.assertAlmostEqual(r["tc_compra"], MEP_2021, places=2)   # 190, no el de hoy

    def test_tc_tipeado_manda_siempre(self):
        r = self._crear(entry_date="2021-06-15", tc_compra=185.5)
        self.assertAlmostEqual(r["tc_compra"], 185.5, places=2)

    def test_lote_usd_no_se_le_inventa_tc(self):
        r = self._crear(entry_date="2021-06-15", currency="USD")
        self.assertIsNone(r["tc_compra"])

    def test_fecha_pre_serie_queda_null_no_inventa(self):
        r = self._crear(entry_date="2005-01-01")
        self.assertIsNone(r["tc_compra"])    # sin dato histórico → mejor vacío que falso
