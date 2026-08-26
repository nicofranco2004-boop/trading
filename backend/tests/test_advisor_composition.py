"""Composición del libro del asesor — GET /api/advisor/book/composition.

Las tres tortas del libro (tipo de activo, activo, sector) salen de acá. El
backend VALÚA Y AGREGA; el frontend clasifica con el mismo código del retail.

Lo que estos tests protegen, en orden de "qué pasa si se rompe":

1. AUTORIZACIÓN. La lista de clientes se deriva de la DB, nunca del HTTP: un
   asesor no puede ver el libro de otro, y un cliente revocado desaparece.
2. LAS TRES FUENTES. El motor de valuación excluye el cash POR SQL y los
   plazos fijos ni siquiera están en el snapshot. Una torta armada solo sobre
   posiciones no cierra contra el patrimonio — y ese hueco exacto ya causó un
   bug documentado en la IA del libro (un cliente 80% cash veía su única
   posición como el 100% de la cartera).
3. EL MERCADO PRE-RESUELTO. `is_ar_market` es la única señal que el
   clasificador del frontend saca de la lista de brokers. Si el backend la
   resuelve mal, AAPL en Balanz deja de ser un CEDEAR y la torta cambia sola.
4. QUE `excluded` NO MIENTA. Sin precio ≠ P&L 0: lo que queda afuera se
   reporta, no se disimula.

Corre con: cd backend && python3 -m pytest tests/test_advisor_composition.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

from fastapi.testclient import TestClient   # noqa: E402
import main                                 # noqa: E402


class CompositionBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("plazos_fijos", "positions", "brokers", "asset_last_price",
                  "fx_rates_daily", "advisor_clients", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.asesor = self._user("asesor@rendi.test", tier="advisor")
        self.otro_asesor = self._user("otro@rendi.test", tier="advisor")
        self.ana = self._user("ana@rendi.test")
        self.beto = self._user("beto@rendi.test")
        self._link(self.asesor, self.ana)
        self._link(self.asesor, self.beto)
        # FX del día: MEP 1000 y blue 1250 a propósito DISTINTOS, para que un
        # test que use el tipo equivocado dé un número distinto y se vea.
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES ('2026-08-25', 1250, 1000)")
        self.conn.commit()

    # ─── fixture helpers ───────────────────────────────────────────────────
    def _user(self, email, tier=None):
        return self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
            "VALUES (?,?,1,1,?)", (email, "x", tier)).lastrowid

    def _link(self, advisor, client, status="active"):
        self.conn.execute(
            "INSERT INTO advisor_clients (advisor_uid, client_uid, status) VALUES (?,?,?)",
            (advisor, client, status))

    def _broker(self, uid, name, currency="ARS", parent=None):
        return self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
            (uid, name, currency, parent)).lastrowid

    def _pos(self, uid, broker, asset, qty, invested, asset_type=None, is_cash=0):
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, quantity, invested,
                                      asset_type, is_cash, entry_date)
               VALUES (?,?,?,?,?,?,?, '2026-01-02')""",
            (uid, broker, asset, qty, invested, asset_type, is_cash))

    def _price(self, symbol, price):
        self.conn.execute(
            "INSERT OR REPLACE INTO asset_last_price (symbol, price, updated_at) "
            "VALUES (?,?, '2026-08-25 20:00:00')", (symbol, price))

    def _pf(self, uid, capital, moneda="ARS", tasa=0.0, plazo=30):
        self.conn.execute(
            """INSERT INTO plazos_fijos (user_id, banco, capital, moneda, tasa,
                                         rate_type, fecha_inicio, plazo_dias,
                                         fecha_vencimiento)
               VALUES (?, 'Banco', ?, ?, ?, 'TNA', '2026-08-01', ?, '2026-08-31')""",
            (uid, capital, moneda, tasa, plazo))

    def _op(self, uid, broker, asset, op_type, pnl_usd, pnl_pct=None, date="2026-05-10"):
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd, pnl_pct)
               VALUES (?,?,?,?,?,?,?)""",
            (uid, date, broker, asset, op_type, pnl_usd, pnl_pct))

    def _realized(self, body, asset):
        return next((r for r in body["realized_by_asset"] if r["asset"] == asset), None)

    def _get(self, uid=None):
        uid = self.asesor if uid is None else uid
        return self.client.get(
            "/api/advisor/book/composition",
            headers={"Authorization": f"Bearer {main.create_token(uid)}"})

    def _row(self, body, asset):
        return next((r for r in body["rows"] if r["asset"] == asset), None)


class AutorizacionTest(CompositionBase):
    """La lista de clientes se DERIVA de la DB. Nunca del HTTP."""

    def test_sin_plan_asesor_403(self):
        pepe = self._user("pepe@rendi.test")
        self.conn.commit()
        self.assertEqual(self._get(pepe).status_code, 403)

    def test_asesor_ajeno_no_ve_este_libro(self):
        # El otro asesor tiene el plan pero no tiene clientes: libro vacío,
        # NO el libro de nadie más.
        self._broker(self.ana, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "AAPL", 10, 100000)
        self._price("AAPL.BA", 20000)
        self.conn.commit()

        propio = self._get().json()
        self.assertGreater(propio["total_usd"], 0)

        ajeno = self._get(self.otro_asesor).json()
        self.assertEqual(ajeno["rows"], [])
        self.assertEqual(ajeno["total_usd"], 0)
        self.assertEqual(ajeno["clients"], 0)

    def test_cliente_revocado_sale_del_libro(self):
        self._broker(self.beto, "Balanz", "ARS")
        self._pos(self.beto, "Balanz", "AAPL", 10, 100000)
        self._price("AAPL.BA", 20000)
        self.conn.commit()
        self.assertIsNotNone(self._row(self._get().json(), "AAPL"))

        self.conn.execute(
            "UPDATE advisor_clients SET status='revoked' WHERE client_uid=?", (self.beto,))
        self.conn.commit()
        self.assertIsNone(self._row(self._get().json(), "AAPL"))

    def test_el_header_de_contexto_de_cliente_no_aplica(self):
        # /api/advisor está en CLIENT_CTX_EXEMPT_PREFIXES: el endpoint es
        # inmune a X-Rendi-Client-Id y uid sigue siendo el asesor. Si alguien
        # lo montara fuera del prefijo, esto pasaría a 403 (el cliente no
        # tiene tier advisor) y el test lo caza.
        self._broker(self.ana, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "AAPL", 10, 100000)
        self._price("AAPL.BA", 20000)
        self.conn.commit()
        r = self.client.get(
            "/api/advisor/book/composition",
            headers={"Authorization": f"Bearer {main.create_token(self.asesor)}",
                     "X-Rendi-Client-Id": str(self.ana)})
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(self._row(r.json(), "AAPL"))

    def test_roster_vacio_devuelve_forma_completa(self):
        # El frontend lee .rows/.included/.excluded sin chequear: la forma
        # vacía tiene que traer todas las claves, no un objeto pelado.
        body = self._get(self.otro_asesor).json()
        for k in ("total_usd", "clients", "as_of", "rows", "included", "excluded"):
            self.assertIn(k, body)
        self.assertIn("cash_usd", body["included"])
        self.assertIn("no_price", body["excluded"])


class AgregacionTest(CompositionBase):
    """Una fila por (activo, asset_type, mercado) — cross-cliente."""

    def test_el_mismo_activo_en_dos_clientes_es_UNA_fila(self):
        for u in (self.ana, self.beto):
            self._broker(u, "Balanz", "ARS")
            self._pos(u, "Balanz", "AAPL", 10, 100000)
        self._price("AAPL.BA", 20000)
        self.conn.commit()

        body = self._get().json()
        filas = [r for r in body["rows"] if r["asset"] == "AAPL"]
        self.assertEqual(len(filas), 1)
        # 10 × 20000 = 200.000 ARS ÷ 1000 (MEP) = 200 USD por cliente.
        self.assertAlmostEqual(filas[0]["value_usd"], 400.0, places=2)
        self.assertEqual(filas[0]["clients"], 2)
        self.assertEqual(body["clients"], 2)

    def test_el_mercado_separa_el_mismo_ticker_en_dos_filas(self):
        # AAPL en BYMA es un CEDEAR; AAPL en el exterior es la acción. Si se
        # colapsaran en una fila, la torta mezclaría dos cosas distintas.
        self._broker(self.ana, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "AAPL", 10, 100000)
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.beto, "Schwab", "AAPL", 2, 300)
        self._price("AAPL.BA", 20000)
        self._price("AAPL", 250)
        self.conn.commit()

        filas = [r for r in self._get().json()["rows"] if r["asset"] == "AAPL"]
        self.assertEqual(len(filas), 2)
        self.assertEqual({r["is_ar_market"] for r in filas}, {True, False})

    def test_pnl_es_valor_menos_costo(self):
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 2, 300)
        self._price("AAPL", 250)
        self.conn.commit()
        r = self._row(self._get().json(), "AAPL")
        self.assertAlmostEqual(r["value_usd"], 500.0, places=2)
        self.assertAlmostEqual(r["invested_usd"], 300.0, places=2)
        self.assertAlmostEqual(r["pnl_usd"], 200.0, places=2)

    def test_total_cierra_con_la_suma_de_las_partes(self):
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 2, 300)
        self._pos(self.ana, "Schwab", "USD", 0, 1000, is_cash=1)
        self._price("AAPL", 250)
        self._pf(self.ana, 500, moneda="USD")
        self.conn.commit()

        b = self._get().json()
        inc = b["included"]
        self.assertAlmostEqual(
            b["total_usd"],
            inc["positions_usd"] + inc["cash_usd"] + inc["plazos_fijos_usd"], places=2)


class MercadoPreResueltoTest(CompositionBase):
    """is_ar_market — la única señal que el clasificador saca de `brokers`."""

    def test_broker_ars_es_mercado_argentino(self):
        self._broker(self.ana, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "AAPL", 10, 100000)
        self._price("AAPL.BA", 20000)
        self.conn.commit()
        self.assertTrue(self._row(self._get().json(), "AAPL")["is_ar_market"])

    def test_subbroker_usd_de_padre_argentino_sigue_siendo_BYMA(self):
        # "Balanz · USD": moneda USD pero el padre es ARS → es un CEDEAR
        # comprado por dólar-MEP. Parent-aware, no por el sufijo del nombre.
        padre = self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.ana, "Cuenta dolares", "USD", parent=padre)
        self._pos(self.ana, "Cuenta dolares", "MSFT", 10, 200)
        self._price("MSFT.BA", 20000)
        self.conn.commit()
        r = self._row(self._get().json(), "MSFT")
        self.assertIsNotNone(r)
        self.assertTrue(r["is_ar_market"],
                        "el sub-broker USD de un padre ARS es mercado argentino")

    def test_broker_del_exterior_no_es_mercado_argentino(self):
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.beto, "Schwab", "AAPL", 2, 300)
        self._price("AAPL", 250)
        self.conn.commit()
        self.assertFalse(self._row(self._get().json(), "AAPL")["is_ar_market"])

    def test_asset_type_CEDEAR_manda_aunque_el_broker_sea_USD(self):
        # Mismo orden que el clasificador del frontend: el hint del importador
        # gana sobre la moneda de la cuenta.
        self._broker(self.beto, "Exterior", "USD")
        self._pos(self.beto, "Exterior", "KO", 10, 200, asset_type="CEDEAR")
        self._price("KO.BA", 5000)
        self.conn.commit()
        r = self._row(self._get().json(), "KO")
        self.assertIsNotNone(r)
        self.assertTrue(r["is_ar_market"])
        self.assertEqual(r["asset_type"], "CEDEAR")


class LasTresFuentesTest(CompositionBase):
    """Cash y plazos fijos: los dos huecos del motor de valuación."""

    def test_el_cash_entra_en_la_torta(self):
        # El motor los excluye por SQL (AND COALESCE(is_cash,0)=0).
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "USD", 0, 1000, is_cash=1)
        self.conn.commit()

        b = self._get().json()
        fila = self._row(b, "USD")
        self.assertIsNotNone(fila, "el efectivo tiene que llegar como fila")
        self.assertTrue(fila["is_cash"])
        self.assertAlmostEqual(fila["value_usd"], 1000.0, places=2)
        self.assertAlmostEqual(b["included"]["cash_usd"], 1000.0, places=2)

    def test_el_cash_en_pesos_va_al_MEP_no_al_blue(self):
        # 1.000.000 ARS: al MEP (1000) son 1000 USD; al blue (1250) serían 800.
        self._broker(self.ana, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "ARS", 0, 1_000_000, is_cash=1)
        self.conn.commit()
        self.assertAlmostEqual(self._get().json()["included"]["cash_usd"], 1000.0, places=2)

    def test_el_cash_no_tiene_PnL(self):
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "USD", 0, 1000, is_cash=1)
        self.conn.commit()
        self.assertAlmostEqual(self._row(self._get().json(), "USD")["pnl_usd"], 0.0, places=2)

    def test_un_cliente_todo_cash_no_desaparece_del_libro(self):
        # El bug documentado de la IA del libro: sin cash, un cliente 80%
        # efectivo aportaba solo su posición y la concentración se leía mal.
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.beto, "Schwab", "USD", 0, 5000, is_cash=1)
        self.conn.commit()
        b = self._get().json()
        self.assertAlmostEqual(b["total_usd"], 5000.0, places=2)
        self.assertEqual(b["clients"], 1)

    def test_los_plazos_fijos_entran_valuados_a_hoy(self):
        # Los PF no están en el snapshot ni en el motor.
        self._pf(self.ana, 1000, moneda="USD", tasa=0.0)
        self.conn.commit()
        b = self._get().json()
        self.assertAlmostEqual(b["included"]["plazos_fijos_usd"], 1000.0, places=2)
        self.assertEqual(b["included"]["plazos_fijos_count"], 1)
        self.assertAlmostEqual(b["total_usd"], 1000.0, places=2)

    def test_plazo_fijo_cerrado_no_cuenta(self):
        self._pf(self.ana, 1000, moneda="USD")
        self.conn.execute("UPDATE plazos_fijos SET closed_at = datetime('now')")
        self.conn.commit()
        self.assertEqual(self._get().json()["included"]["plazos_fijos_count"], 0)

    def test_el_interes_devengado_del_PF_esta_en_el_valor_no_en_el_capital(self):
        self._pf(self.ana, 1000, moneda="USD", tasa=3.65, plazo=30)  # TNA alta
        self.conn.commit()
        inc = self._get().json()["included"]
        self.assertGreater(inc["plazos_fijos_usd"], inc["plazos_fijos_invested_usd"])


class ExcluidoTest(CompositionBase):
    """Lo que queda afuera se REPORTA. Sin precio ≠ P&L 0."""

    def test_posicion_sin_precio_se_excluye_y_se_cuenta(self):
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 2, 300)
        self._pos(self.ana, "Schwab", "ZZZZ", 5, 500)   # sin precio conocido
        self._price("AAPL", 250)
        self.conn.commit()

        b = self._get().json()
        self.assertIsNone(self._row(b, "ZZZZ"))
        self.assertEqual(b["excluded"]["no_price"], 1)
        # Y NO se contó como si valiera su costo:
        self.assertAlmostEqual(b["total_usd"], 500.0, places=2)

    def test_broker_huerfano_se_cuenta_aparte(self):
        # Posición cuyo broker no existe (borrado/renombrado sin cascada).
        # Defaultear a USD contaría un costo en pesos 1:1 como dólares.
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Fantasma", "AAPL", 2, 300)
        self._price("AAPL", 250)
        self.conn.commit()

        b = self._get().json()
        self.assertEqual(b["excluded"]["orphan_broker"], 1)
        self.assertEqual(b["excluded"]["no_price"], 0)
        self.assertEqual(b["total_usd"], 0)

    def test_cash_con_broker_huerfano_no_infla_el_patrimonio(self):
        self._pos(self.ana, "Fantasma", "ARS", 0, 1_000_000, is_cash=1)
        self.conn.commit()
        b = self._get().json()
        self.assertEqual(b["included"]["cash_usd"], 0)
        self.assertEqual(b["excluded"]["orphan_broker"], 1)


class ResultadoPorPorcionTest(CompositionBase):
    """Lo CERRADO y la RENTA — las otras dos patas del resultado.

    Una torta que solo mire posiciones abiertas cuenta el rendimiento a
    medias: un bono que pagó cupones toda su vida tiene su rendimiento EN LOS
    CUPONES, no en la variación del precio.
    """

    def setUp(self):
        super().setUp()
        self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.beto, "Schwab", "USD")

    def test_una_venta_llega_con_su_costo_despejado(self):
        # El costo sale del par (pnl_usd, pnl_pct): +200 al 25% ⇒ costo 800.
        self._op(self.ana, "Balanz", "AAPL", "Venta", 200.0, 25.0)
        self.conn.commit()
        r = self._realized(self._get().json(), "AAPL")
        self.assertEqual(r["realized_usd"], 200.0)
        self.assertAlmostEqual(r["cost_usd"], 800.0, places=2)
        self.assertFalse(r["cost_incomplete"])

    def test_sin_pnl_pct_el_costo_se_marca_incompleto_y_no_se_inventa(self):
        self._op(self.ana, "Balanz", "AAPL", "Venta", 200.0, None)
        self.conn.commit()
        r = self._realized(self._get().json(), "AAPL")
        self.assertEqual(r["realized_usd"], 200.0)
        self.assertEqual(r["cost_usd"], 0.0)
        self.assertTrue(r["cost_incomplete"])

    def test_la_renta_suma_al_resultado_pero_NO_al_costo(self):
        # No invertiste para cobrar el cupón: el capital ya está contado.
        self._op(self.ana, "Balanz", "AL30", "Cupón", 50.0, None)
        self._op(self.ana, "Balanz", "AL30", "Dividendo", 30.0, None)
        self._op(self.ana, "Balanz", "AL30", "Interés", 20.0, None)
        self.conn.commit()
        r = self._realized(self._get().json(), "AL30")
        self.assertEqual(r["income_usd"], 100.0)
        self.assertEqual(r["realized_usd"], 0.0)
        self.assertEqual(r["cost_usd"], 0.0)
        self.assertFalse(r["cost_incomplete"])

    def test_agrega_cross_cliente_por_activo_y_mercado(self):
        self._op(self.ana, "Balanz", "AAPL", "Venta", 100.0, 10.0)     # BYMA
        self._op(self.beto, "Schwab", "AAPL", "Venta", 300.0, 30.0)    # exterior
        self.conn.commit()
        filas = [r for r in self._get().json()["realized_by_asset"] if r["asset"] == "AAPL"]
        self.assertEqual(len(filas), 2)
        self.assertEqual({r["is_ar_market"] for r in filas}, {True, False})
        ar = next(r for r in filas if r["is_ar_market"])
        self.assertEqual(ar["realized_usd"], 100.0)

    def test_dos_ventas_del_mismo_activo_suman_monto_y_costo(self):
        self._op(self.ana, "Balanz", "AAPL", "Venta", 200.0, 25.0)   # costo 800
        self._op(self.ana, "Balanz", "AAPL", "Venta", 100.0, 50.0)   # costo 200
        self.conn.commit()
        r = self._realized(self._get().json(), "AAPL")
        self.assertEqual(r["realized_usd"], 300.0)
        self.assertAlmostEqual(r["cost_usd"], 1000.0, places=2)

    def test_las_conversiones_de_moneda_no_son_un_activo(self):
        self._op(self.ana, "Balanz", "ARS→USDT", "Conversion", 5.0, None)
        self._op(self.ana, "Balanz", "USD", "CONVERSION_OUT", 7.0, None)
        self.conn.commit()
        self.assertEqual(self._get().json()["realized_by_asset"], [])

    def test_el_hint_de_tipo_viaja_para_que_el_clasificador_no_se_equivoque(self):
        # Venta de un CEDEAR en una cuenta DÓLAR: sin el hint se clasificaría
        # como acción US y la ganancia caería en la porción equivocada.
        self._broker(self.beto, "Exterior", "USD")
        self._pos(self.beto, "Exterior", "KO", 10, 200, asset_type="CEDEAR")
        self._price("KO.BA", 5000)
        self._op(self.beto, "Exterior", "KO", "Venta", 40.0, 20.0)
        self.conn.commit()
        r = self._realized(self._get().json(), "KO")
        self.assertEqual(r["asset_type"], "CEDEAR")
        self.assertTrue(r["is_ar_market"])

    def test_una_venta_de_un_activo_que_ya_no_se_tiene_igual_cuenta(self):
        # No hay posición abierta: la fila no está en `rows` pero sí acá.
        self._op(self.ana, "Balanz", "GGAL", "Venta", 75.0, 15.0)
        self.conn.commit()
        b = self._get().json()
        self.assertIsNone(self._row(b, "GGAL"))
        self.assertIsNotNone(self._realized(b, "GGAL"))

    def test_pnl_cero_no_genera_fila(self):
        self._op(self.ana, "Balanz", "AAPL", "Venta", 0.0, 0.0)
        self.conn.commit()
        self.assertEqual(self._get().json()["realized_by_asset"], [])

    def test_las_operaciones_de_otro_asesor_no_entran(self):
        self._op(self.ana, "Balanz", "AAPL", "Venta", 200.0, 25.0)
        self.conn.commit()
        self.assertEqual(self._get(self.otro_asesor).json()["realized_by_asset"], [])


class TasaQueNoEsTasaTest(CompositionBase):
    """_rate_pct — cuándo el % deja de comunicar un rendimiento.

    total/costo se rompe cuando la plata se ganó sobre un capital que ya no
    está: un bono que amortizó casi todo sigue sumando años de cupones contra
    un costo residual. En el libro demo, GD35 con US$15 de posición y US$1.463
    de renta daba +9.804%.
    """

    def test_tasa_normal(self):
        self.assertAlmostEqual(main._rate_pct(200, 1000, False), 20.0)
        self.assertAlmostEqual(main._rate_pct(-300, 1000, False), -30.0)

    def test_sin_costo_o_costo_incompleto_no_hay_tasa(self):
        self.assertIsNone(main._rate_pct(200, 0, False))
        self.assertIsNone(main._rate_pct(200, -5, False))
        self.assertIsNone(main._rate_pct(200, 1000, True))

    def test_el_denominador_evaporado_no_da_tasa(self):
        self.assertIsNone(main._rate_pct(1464, 15, False))     # GD35
        self.assertIsNone(main._rate_pct(-1464, 15, False))    # y la pérdida igual

    def test_el_borde_es_10x_y_sigue_valiendo(self):
        self.assertAlmostEqual(main._rate_pct(1000, 100, False), 1000.0)
        self.assertIsNone(main._rate_pct(1001, 100, False))

    def test_misma_constante_que_el_frontend(self):
        # Si alguien mueve una sola de las dos, el rango del asesor y el % de
        # la torta empiezan a contar historias distintas.
        import re, os
        js = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "utils", "assetPnl.js")
        with open(js, encoding="utf-8") as f:
            m = re.search(r"const MAX_PNL_TO_COST = (\d+)", f.read())
        self.assertIsNotNone(m, "no encontré MAX_PNL_TO_COST en assetPnl.js")
        self.assertEqual(int(m.group(1)), main.MAX_PNL_TO_COST)


class DispersionEntreClientesTest(CompositionBase):
    """return_spread — lo que el % agrupado esconde.

    "AAPL +9,8%" puede ser un cliente en −20% y otro en +40%: el libro se ve
    bien y hay alguien enojado. El rango se calcula POR CLIENTE con las mismas
    tres patas y el mismo guard que el agrupado, si no podría no contener al
    número que está justo al lado.
    """

    def _spread(self, body, asset):
        return next((r for r in body["return_spread"] if r["asset"] == asset), None)

    def test_dos_clientes_con_el_mismo_activo_dan_un_rango(self):
        # Ana: costo 100 → vale 80 (−20%). Beto: costo 100 → vale 140 (+40%).
        self._broker(self.ana, "Schwab", "USD")
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 1, 100)
        self._pos(self.beto, "Schwab", "AAPL", 1, 100)
        self._price("AAPL", 80)
        self.conn.commit()
        # Mismo precio para los dos: el rango arranca en cero.
        s = self._spread(self._get().json(), "AAPL")
        self.assertIsNotNone(s)
        self.assertEqual(s["clients"], 2)
        self.assertAlmostEqual(s["min_pct"], -20.0, places=1)
        self.assertAlmostEqual(s["max_pct"], -20.0, places=1)

    def test_el_rango_separa_al_que_compro_caro_del_que_compro_barato(self):
        self._broker(self.ana, "Schwab", "USD")
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 1, 200)    # compró caro
        self._pos(self.beto, "Schwab", "AAPL", 1, 50)    # compró barato
        self._price("AAPL", 100)
        self.conn.commit()
        s = self._spread(self._get().json(), "AAPL")
        self.assertAlmostEqual(s["min_pct"], -50.0, places=1)
        self.assertAlmostEqual(s["max_pct"], 100.0, places=1)

    def test_el_rango_CONTIENE_al_porcentaje_agrupado(self):
        # La propiedad que hace que las dos cifras no se contradigan.
        self._broker(self.ana, "Schwab", "USD")
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 1, 200)
        self._pos(self.beto, "Schwab", "AAPL", 1, 50)
        self._price("AAPL", 100)
        self.conn.commit()
        b = self._get().json()
        fila = self._row(b, "AAPL")
        agrupado = fila["pnl_usd"] / fila["invested_usd"] * 100    # 50/250 = 20%
        s = self._spread(b, "AAPL")
        self.assertLessEqual(s["min_pct"], agrupado)
        self.assertGreaterEqual(s["max_pct"], agrupado)

    def test_un_solo_cliente_no_tiene_dispersion(self):
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 1, 100)
        self._price("AAPL", 120)
        self.conn.commit()
        self.assertIsNone(self._spread(self._get().json(), "AAPL"))

    def test_lo_cerrado_y_la_renta_entran_en_el_retorno_de_cada_cliente(self):
        # Si el rango mirara solo lo abierto, podría quedar afuera del
        # agrupado (que sí suma las tres patas).
        self._broker(self.ana, "Schwab", "USD")
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 1, 100)
        self._pos(self.beto, "Schwab", "AAPL", 1, 100)
        self._price("AAPL", 100)
        self._op(self.beto, "Schwab", "AAPL", "Dividendo", 50.0)
        self.conn.commit()
        s = self._spread(self._get().json(), "AAPL")
        self.assertAlmostEqual(s["min_pct"], 0.0, places=1)     # Ana, sin renta
        self.assertAlmostEqual(s["max_pct"], 50.0, places=1)    # Beto, con el dividendo

    def test_un_cliente_con_la_tasa_rota_no_entra_en_el_rango(self):
        # Bono amortizado con mucha renta: su % no es un rendimiento, así que
        # no puede definir el extremo del rango.
        self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.beto, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "AL30", 10, 100000, asset_type="BONO")
        self._pos(self.beto, "Balanz", "AL30", 10, 100000, asset_type="BONO")
        self._price("AL30.BA", 10000)
        self._op(self.beto, "Balanz", "AL30", "Cupón", 999999.0)
        self.conn.commit()
        s = self._spread(self._get().json(), "AL30")
        # Beto queda excluido por el guard → un solo cliente medible → sin rango
        self.assertIsNone(s)

    def test_los_dos_mercados_del_mismo_ticker_NO_se_mezclan(self):
        # El CEDEAR de AAPL y la acción de AAPL caen en porciones DISTINTAS de
        # la torta por tipo, cada una con su propio %. Un rango que juntara los
        # dos describiría una población que no es la de la porción donde se
        # muestra — medido en el libro demo, la fila de NU en "Acciones US"
        # decía +6,8% con un rango que era el de los dos mercados juntos.
        self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.ana, "Balanz", "AAPL", 10, 100000)   # CEDEAR
        self._pos(self.beto, "Schwab", "AAPL", 1, 100)      # acción US
        self._price("AAPL.BA", 20000)
        self._price("AAPL", 150)
        self.conn.commit()

        # Un cliente por mercado ⇒ ningún mercado tiene dispersión que contar.
        filas = [r for r in self._get().json()["return_spread"] if r["asset"] == "AAPL"]
        self.assertEqual(filas, [])

    def test_cada_mercado_lleva_su_propio_rango(self):
        cara = self._user("cara2@rendi.test")
        dani = self._user("dani@rendi.test")
        self._link(self.asesor, cara)
        self._link(self.asesor, dani)
        # Dos clientes en el CEDEAR, dos en la acción del exterior.
        for u in (self.ana, self.beto):
            self._broker(u, "Balanz", "ARS")
            self._pos(u, "Balanz", "AAPL", 10, 100000)
        for u in (cara, dani):
            self._broker(u, "Schwab", "USD")
            self._pos(u, "Schwab", "AAPL", 1, 100)
        self._price("AAPL.BA", 20000)
        self._price("AAPL", 150)
        self.conn.commit()

        filas = {r["is_ar_market"]: r for r in self._get().json()["return_spread"]
                 if r["asset"] == "AAPL"}
        self.assertEqual(set(filas), {True, False}, "un rango por mercado")
        self.assertEqual(filas[True]["clients"], 2)
        self.assertEqual(filas[False]["clients"], 2)
        # El CEDEAR va +100% (200.000 ARS al MEP 1000 = US$200 sobre US$100) y
        # la acción +50%: rangos distintos, no uno solo de +50% a +100%.
        self.assertAlmostEqual(filas[True]["min_pct"], 100.0, places=1)
        self.assertAlmostEqual(filas[False]["min_pct"], 50.0, places=1)


class MonedaNativaDeLasCobranzasTest(CompositionBase):
    """`operations.pnl_usd` NO es USD en las cobranzas de renta fija.

    Guarda el monto en la MONEDA DEL BROKER (bond_cashflow inserta net_amount
    tal cual). Sumarlo crudo contaba un cupón de $125.000 como US$125.000. El
    repo tiene un módulo — realized_pnl.py — que es el criterio ÚNICO, y existe
    porque esto ya paso en produccion: el dashboard decia US$100 y la IA
    US$125.000 en el MISMO request. Este endpoint es el quinto lector.
    """

    def setUp(self):
        super().setUp()
        self._broker(self.ana, "Balanz", "ARS")

    def _op_fx(self, uid, broker, asset, op_type, pnl_usd, currency, fx):
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type,
                                       pnl_usd, pnl_pct, currency, fx_to_usd)
               VALUES (?, '2026-06-01', ?,?,?,?, NULL, ?, ?)""",
            (uid, broker, asset, op_type, pnl_usd, currency, fx))

    def test_un_cupon_en_pesos_entra_en_dolares(self):
        # $125.000 al FX sellado 1250 = US$100. Crudo serian US$125.000.
        self._op_fx(self.ana, "Balanz", "AL30", "Cupón", 125000.0, "ARS", 1250.0)
        self.conn.commit()
        r = self._realized(self._get().json(), "AL30")
        self.assertAlmostEqual(r["income_usd"], 100.0, places=2)

    def test_la_amortizacion_tambien(self):
        self._op_fx(self.ana, "Balanz", "AL30", "Amortización", 62500.0, "ARS", 1250.0)
        self.conn.commit()
        r = self._realized(self._get().json(), "AL30")
        self.assertAlmostEqual(r["realized_usd"], 50.0, places=2)

    def test_una_venta_NO_se_convierte(self):
        # En Venta pnl_usd YA es USD y fx_to_usd guarda el tc_venta: dividir
        # ahi romperia todo (lo dice el docstring del modulo).
        self._op_fx(self.ana, "Balanz", "AAPL", "Venta", 200.0, "ARS", 1250.0)
        self.conn.commit()
        r = self._realized(self._get().json(), "AAPL")
        self.assertAlmostEqual(r["realized_usd"], 200.0, places=2)

    def test_un_cupon_en_dolares_no_se_toca(self):
        self._op_fx(self.ana, "Balanz", "GD35", "Cupón", 100.0, "USD", 1250.0)
        self.conn.commit()
        self.assertAlmostEqual(self._realized(self._get().json(), "GD35")["income_usd"], 100.0, places=2)

    def test_las_filas_viejas_sin_FX_quedan_como_estaban(self):
        # Deliberado: de los 276 cupones marcados ARS sin FX sellado, ~125 son
        # de bonos en dolares que YA estan bien. Convertirlos a todos los haria
        # 1250x mas chicos. Ver el docstring de realized_pnl.py.
        self._op_fx(self.ana, "Balanz", "AL30", "Cupón", 125000.0, "ARS", None)
        self.conn.commit()
        self.assertAlmostEqual(self._realized(self._get().json(), "AL30")["income_usd"], 125000.0, places=2)

    def test_el_endpoint_usa_el_criterio_canonico_no_una_copia(self):
        # Si alguien vuelve a leer la columna cruda, este test lo caza.
        import inspect
        src = inspect.getsource(main._advisor_realized_raw)
        self.assertIn("realized_usd_sql", src,
                      "_advisor_realized_raw tiene que pasar por realized_pnl, no leer pnl_usd crudo")

    def test_la_lista_de_cobranzas_nativas_no_puede_divergir_del_frontend(self):
        # El espejo en JS (opPnlUsd en utils/assetPnl.js) tiene que cubrir los
        # MISMOS op_type. Si alguien agrega uno de un lado y no del otro, la
        # torta del libro y la del cliente vuelven a dar numeros distintos.
        import os
        import realized_pnl
        js = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "utils", "assetPnl.js")
        with open(js, encoding="utf-8") as f:
            txt = f.read()
        for op in realized_pnl._NATIVE_CCY_OPS:
            self.assertIn("'" + op + "'", txt,
                          "assetPnl.js no cubre " + op + " en NATIVE_CCY_OPS")


class RangoQueNoContieneAlAgrupadoTest(CompositionBase):
    """El caso que rompía la invariante que el docstring prometía.

    El agrupado (Σtotal/Σcost) es un promedio ponderado de los retornos
    individuales, así que SIEMPRE cae entre el mínimo y el máximo... de los
    clientes que entraron en la cuenta. Un cliente cuya tasa no es publicable
    (denominador evaporado) quedaba AFUERA del rango pero su plata seguía en el
    promedio: la pantalla mostraba "+18,3%" arriba y "de +5,0% a +5,0%" abajo.

    Ahora viajan los dos conteos y la UI escribe "2 de 3 carteras".
    """

    def _spread(self, body, asset):
        return next((r for r in body["return_spread"] if r["asset"] == asset), None)

    def test_el_rango_avisa_cuando_no_cubre_a_todos(self):
        # Ana: GD35 con el denominador evaporado (poca posición, mucha renta).
        # Beto y Caro: medibles y parecidos. Caro se crea acá y no en el
        # fixture para no cambiarle el roster a los otros tests.
        cara = self._user("cara@rendi.test")
        self._link(self.asesor, cara)
        for u in (self.ana, self.beto, cara):
            self._broker(u, "Balanz", "ARS")
            self._pos(u, "Balanz", "GD35", 10, 100000, asset_type="BONO")
        self._price("GD35.BA", 10000)
        self._op(self.ana, "Balanz", "GD35", "Cupón", 999999.0)
        self.conn.commit()

        s = self._spread(self._get().json(), "GD35")
        self.assertIsNotNone(s, "con dos clientes medibles tiene que haber rango")
        self.assertEqual(s["clients"], 2, "Ana no es medible")
        self.assertEqual(s["clients_total"], 3, "pero Ana TIENE el activo")

    def test_cuando_todos_son_medibles_los_dos_conteos_coinciden(self):
        for u in (self.ana, self.beto):
            self._broker(u, "Schwab", "USD")
            self._pos(u, "Schwab", "AAPL", 1, 100)
        self._price("AAPL", 120)
        self.conn.commit()
        s = self._spread(self._get().json(), "AAPL")
        self.assertEqual(s["clients"], s["clients_total"])


class UnClienteEsUnClienteTest(CompositionBase):
    """El mismo papel en dos mercados es UNA exposición, no dos clientes."""

    def _spread(self, body, asset):
        return next((r for r in body["return_spread"] if r["asset"] == asset), None)

    def test_un_solo_cliente_con_el_ticker_en_dos_mercados_no_genera_rango(self):
        # Ana es la ÚNICA cliente y tiene AAPL como CEDEAR y como acción US.
        # Antes el endpoint decía clients:1 en el libro y clients:2 en el rango,
        # en la MISMA respuesta.
        padre = self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Balanz", "AAPL", 10, 100000)   # CEDEAR, +100%
        self._pos(self.ana, "Schwab", "AAPL", 1, 100)       # acción US, -20%
        self._price("AAPL.BA", 20000)
        self._price("AAPL", 80)
        self.conn.commit()

        b = self._get().json()
        self.assertEqual(b["clients"], 1)
        self.assertIsNone(self._spread(b, "AAPL"),
                          "un solo cliente no tiene dispersión, aunque tenga dos mercados")

    def test_el_cliente_con_dos_mercados_cuenta_una_vez_en_CADA_uno(self):
        # Ana tiene AAPL en los dos mercados; Beto solo la acción del exterior.
        # En el mercado del exterior son DOS clientes (Ana y Beto), no tres.
        self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.ana, "Schwab", "USD")
        self._broker(self.beto, "Schwab", "USD")
        self._pos(self.ana, "Balanz", "AAPL", 10, 100000)
        self._pos(self.ana, "Schwab", "AAPL", 1, 100)
        self._pos(self.beto, "Schwab", "AAPL", 1, 100)
        self._price("AAPL.BA", 20000)
        self._price("AAPL", 80)
        self.conn.commit()

        filas = {r["is_ar_market"]: r for r in self._get().json()["return_spread"]
                 if r["asset"] == "AAPL"}
        # Exterior: Ana y Beto, las dos al -20% (mismo costo, mismo precio).
        self.assertEqual(filas[False]["clients"], 2)
        self.assertAlmostEqual(filas[False]["min_pct"], -20.0, places=1)
        self.assertAlmostEqual(filas[False]["max_pct"], -20.0, places=1)
        # BYMA: solo Ana ⇒ no hay dispersión que contar.
        self.assertNotIn(True, filas)


class TickerNormalizadoEnElRangoTest(CompositionBase):
    """El sufijo .BA no puede partir el rango en dos filas."""

    def _spread(self, body, asset):
        return next((r for r in body["return_spread"] if r["asset"] == asset), None)

    def test_GGAL_y_GGAL_BA_son_el_mismo_activo(self):
        # El sufijo llega por OPERACIONES, no por posiciones: una posición
        # guardada como "GGAL.BA" el motor la excluye antes (pide GGAL.BA.BA y
        # no hay precio), pero una fila de `operations` no pasa por ningún
        # lookup de precio y entra con el símbolo crudo.
        #
        # Antes, esas dos filas creaban DOS entradas de rango que el Map del
        # frontend colapsaba a una — y la segunda le robaba el rango a la
        # primera, así que un activo mostraba la dispersión de otro.
        self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.beto, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "GGAL", 100, 100000)
        self._pos(self.beto, "Balanz", "GGAL", 100, 200000)
        self._price("GGAL.BA", 2000)
        self._op(self.ana, "Balanz", "GGAL.BA", "Venta", 50.0, 10.0)
        self.conn.commit()

        b = self._get().json()
        filas = [r for r in b["return_spread"] if r["asset"] in ("GGAL", "GGAL.BA")]
        self.assertEqual(len(filas), 1, "tiene que haber UNA fila, no dos que se pisen")
        self.assertEqual(filas[0]["asset"], "GGAL")
        self.assertEqual(filas[0]["clients"], 2)

    def test_la_venta_con_sufijo_suma_al_retorno_del_mismo_cliente(self):
        # Y no crea un "tercer cliente" fantasma.
        self._broker(self.ana, "Balanz", "ARS")
        self._broker(self.beto, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "GGAL", 100, 100000)
        self._pos(self.beto, "Balanz", "GGAL", 100, 100000)
        self._price("GGAL.BA", 2000)
        self._op(self.ana, "Balanz", "GGAL.BA", "Venta", 100.0, 20.0)
        self.conn.commit()
        s = self._spread(self._get().json(), "GGAL")
        self.assertEqual(s["clients"], 2)
        self.assertEqual(s["clients_total"], 2)


class PlazosFijosAlMismoDolarTest(CompositionBase):
    """El PF del libro tiene que valer lo mismo que en el Dashboard del cliente.

    El frontend hace `pfUsd(totals, tcBlue)` y el nombre engaña: el `tcBlue` del
    CurrencyContext TIENE EL VALOR DEL MEP (cascada mep→ccl→blue), y está
    escrito así en su cabecera. Convertir al blue de verdad hacía valer el mismo
    plazo fijo ~25% distinto según qué pantalla lo mirara, y mezclaba dos
    dólares dentro del mismo total.
    """

    def test_el_plazo_fijo_en_pesos_va_al_MEP(self):
        # Fixture: MEP 1000, blue 1250. Al MEP son US$1.250; al blue, US$1.000.
        self._pf(self.ana, 1_250_000, moneda="ARS", tasa=0.0)
        self.conn.commit()
        self.assertAlmostEqual(
            self._get().json()["included"]["plazos_fijos_usd"], 1250.0, places=2)

    def test_el_libro_no_mezcla_dos_dolares(self):
        # Cash en pesos y plazo fijo en pesos, mismo monto ⇒ mismo valor USD.
        self._broker(self.ana, "Balanz", "ARS")
        self._pos(self.ana, "Balanz", "ARS", 0, 1_000_000, is_cash=1)
        self._pf(self.ana, 1_000_000, moneda="ARS", tasa=0.0)
        self.conn.commit()
        inc = self._get().json()["included"]
        self.assertAlmostEqual(inc["cash_usd"], inc["plazos_fijos_usd"], places=2)

    def test_el_plazo_fijo_en_dolares_no_se_convierte(self):
        self._pf(self.ana, 1000, moneda="USD", tasa=0.0)
        self.conn.commit()
        self.assertAlmostEqual(
            self._get().json()["included"]["plazos_fijos_usd"], 1000.0, places=2)


class ClientesConSoloPlazosFijosTest(CompositionBase):
    """Su plata entra en el total, así que tienen que entrar en el conteo."""

    def test_un_cliente_PF_only_cuenta_como_cliente(self):
        self._broker(self.ana, "Schwab", "USD")
        self._pos(self.ana, "Schwab", "AAPL", 2, 300)
        self._price("AAPL", 250)
        self._pf(self.beto, 1_000_000, moneda="ARS", tasa=0.0)   # Beto: solo PF
        self.conn.commit()

        b = self._get().json()
        self.assertEqual(b["clients"], 2,
                         "Beto aporta plata a la torta: no puede faltar en el conteo")
        self.assertGreater(b["included"]["plazos_fijos_usd"], 0)

    def test_un_libro_entero_en_plazos_fijos_cuenta_a_todos(self):
        self._pf(self.ana, 1_000_000, moneda="ARS", tasa=0.0)
        self._pf(self.beto, 2_000_000, moneda="ARS", tasa=0.0)
        self.conn.commit()
        b = self._get().json()
        self.assertEqual(b["clients"], 2)
        self.assertEqual(b["rows"], [], "sin posiciones ni cash, rows queda vacío")
        self.assertGreater(b["total_usd"], 0, "pero el patrimonio existe")


class CostoDeVentasQueSeCancelanTest(CompositionBase):
    """Un neto de cero no significa que no hubo capital en juego."""

    def test_la_fila_sobrevive_aunque_lo_realizado_neto_sea_cero(self):
        # Ana vendió +500 (costo 5.000) y Beto −500 (costo 5.000): neto 0.
        self._broker(self.ana, "Schwab", "USD")
        self._broker(self.beto, "Schwab", "USD")
        self._op(self.ana, "Schwab", "AAPL", "Venta", 500.0, 10.0)
        self._op(self.beto, "Schwab", "AAPL", "Venta", -500.0, -10.0)
        self.conn.commit()

        r = self._realized(self._get().json(), "AAPL")
        self.assertIsNotNone(r, "la fila no se puede tirar: lleva el costo")
        self.assertEqual(r["realized_usd"], 0.0)
        self.assertAlmostEqual(r["cost_usd"], 10000.0, places=2)

    def test_sin_costo_y_sin_resultado_la_fila_no_existe(self):
        self._broker(self.ana, "Schwab", "USD")
        self._op(self.ana, "Schwab", "AAPL", "Venta", 0.0, 0.0)
        self.conn.commit()
        self.assertEqual(self._get().json()["realized_by_asset"], [])


if __name__ == "__main__":
    unittest.main()