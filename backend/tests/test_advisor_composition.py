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

    def test_plazo_fijo_en_pesos_va_al_blue(self):
        # Espejo de pfUsd() del frontend, que convierte al blue (1250).
        self._pf(self.ana, 1_250_000, moneda="ARS", tasa=0.0)
        self.conn.commit()
        self.assertAlmostEqual(
            self._get().json()["included"]["plazos_fijos_usd"], 1000.0, places=2)

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


if __name__ == "__main__":
    unittest.main()
