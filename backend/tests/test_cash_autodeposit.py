"""El cash nunca queda negativo en una alta MANUAL de posición.

Si el user agrega una posición/compra sin haber cargado el depósito antes, el
sistema auto-deposita el faltante (sube cash a 0 + lo registra como capital
aportado, para que el P&L no muestre una ganancia falsa).

Corre con: cd backend && python3 -m pytest tests/test_cash_autodeposit.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main


class CashAutodepositTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("positions", "operations", "monthly_entries", "config",
                  "brokers", "users", "import_op_links", "import_normalized_tx",
                  "import_raw_rows", "import_batches", "snapshots"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cash@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _broker(self, name, ccy):
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, name, ccy))
        self.conn.commit()

    def _seed_cash(self, broker, asset, amount):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
            (self.uid, broker, asset, amount))
        self.conn.commit()

    def _cash(self, broker):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) c FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()
        return float(r["c"] or 0)

    def _global_deposits(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,)).fetchone()
        return float(r["d"] or 0)

    def _pos(self, broker, asset="BTC", invested=1000.0):
        return main.PositionIn(broker=broker, asset=asset, is_cash=False,
                               invested=invested, quantity=0.01, buy_price=100000.0,
                               entry_date="2026-01-15")

    # ── casos ────────────────────────────────────────────────────────────────
    def test_usd_buy_no_cash_floors_at_zero(self):
        self._broker("Binance", "USDT")
        main.create_position(self._pos("Binance"), self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 0.0, places=2)      # no negativo
        self.assertAlmostEqual(self._global_deposits(), 1000.0, places=2)  # capital aportado +1000

    def test_buy_with_enough_cash_no_autodeposit(self):
        self._broker("Binance", "USDT")
        self._seed_cash("Binance", "USDT", 5000)
        main.create_position(self._pos("Binance"), self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 4000.0, places=2)   # 5000 - 1000
        self.assertAlmostEqual(self._global_deposits(), 0.0, places=2)    # nada auto-depositado

    def test_partial_cash_autodeposits_only_shortfall(self):
        self._broker("Binance", "USDT")
        self._seed_cash("Binance", "USDT", 300)
        main.create_position(self._pos("Binance"), self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 0.0, places=2)      # 300 + 700 - 1000
        self.assertAlmostEqual(self._global_deposits(), 700.0, places=2)  # solo el faltante

    def test_ars_buy_autodeposit_converted_usd(self):
        self._broker("Cocos", "ARS")
        # Conflicto por la PK compuesta (key, user_id) de `config`. La query nombra
        # las 3 columnas de la tabla, así que no hay nada que se pierda al convertir:
        # el DO UPDATE es equivalente al borrar-y-reinsertar de antes. Igual el
        # setUp hace DELETE FROM config, así que acá nunca hay conflicto real.
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        main.create_position(self._pos("Cocos", asset="GGAL", invested=100000.0), self.uid)
        self.assertAlmostEqual(self._cash("Cocos"), 0.0, places=2)
        # capital aportado en USD = 100.000 ARS / 1000 = 100
        self.assertAlmostEqual(self._global_deposits(), 100.0, places=2)

    def test_cash_position_itself_not_affected(self):
        # Agregar una posición de CASH (is_cash) no debe disparar auto-deposit.
        self._broker("Binance", "USDT")
        p = main.PositionIn(broker="Binance", asset="USDT", is_cash=True, invested=500.0,
                            entry_date="2026-01-15")
        main.create_position(p, self.uid)
        self.assertAlmostEqual(self._cash("Binance"), 500.0, places=2)
        self.assertAlmostEqual(self._global_deposits(), 0.0, places=2)

    def test_plazo_fijo_funding_no_cash_floors_at_zero(self):
        # Crear un PF desde un broker sin cash suficiente → mismo auto-deposit.
        self._broker("Banco Galicia", "ARS")
        # Mismo caso que test_ars_buy_autodeposit_converted_usd: 3 de 3 columnas
        # nombradas, conflicto por (key, user_id), y la tabla arranca vacía.
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        pf = main.PlazoFijoIn(banco="Galicia", capital=100000.0, moneda="ARS",
                              tasa=0.30, rate_type="TNA", fecha_inicio="2026-01-15",
                              plazo_dias=30, source_broker="Banco Galicia")
        main.create_plazo_fijo(pf, self.uid)
        self.assertAlmostEqual(self._cash("Banco Galicia"), 0.0, places=2)   # no negativo
        self.assertAlmostEqual(self._global_deposits(), 100.0, places=2)     # 100k ARS / 1000


class AutodepositRateTest(unittest.TestCase):
    """El autodepósito ES capital aportado (el denominador del rendimiento), así que el
    dólar con que se dolariza importa. Antes usaba `config.tc_blue`: un número GUARDADO
    que arranca en 1415 y solo cambia a mano — ajeno al MEP que usa el resto de la app, y
    encima el de HOY aunque la compra fuera retroactiva. Ahora: MEP de la FECHA."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("positions", "monthly_entries", "config", "brokers", "users", "fx_rates_daily"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("adr@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "ARS"))
        # El valor viejo y ajeno que se usaba antes.
        # Se nombran las columnas a propósito: el VALUES posicional asumía el orden
        # (key, value, user_id) del CREATE TABLE — coincide hoy, pero la próxima
        # columna que se agregue a `config` lo rompe en silencio. Cubre las 3
        # columnas, conflicto por la PK (key, user_id); setUp vacía la tabla antes.
        self.conn.execute(
            "INSERT INTO config (key, value, user_id) VALUES ('tc_blue','1415',?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid,))
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(fx_rates_daily)")]
        if "mep_venta" not in cols:
            self.conn.execute("ALTER TABLE fx_rates_daily ADD COLUMN mep_venta REAL")
        # Conflicto por la PK (date). La query NO nombra `fetched_at`: con
        # INSERT OR REPLACE esa columna se reseteaba por su DEFAULT, así que la
        # ponemos EXPLÍCITA en el SET para conservar exactamente eso (mismo criterio
        # que el escritor real, _persist_blue_for_date en main.py:4246). Da igual en
        # la práctica —setUp vacía fx_rates_daily y se siembra una sola fila, o sea
        # que el DO UPDATE no llega a correr, y ningún test lee fetched_at— pero se
        # deja escrito para que nadie copie de acá un upsert que pierde el refresh.
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT (date) DO UPDATE SET "
            "  blue_venta = EXCLUDED.blue_venta, "
            "  mep_venta  = EXCLUDED.mep_venta, "
            "  source     = EXCLUDED.source, "
            "  fetched_at = datetime('now')",
            ("2024-05-03", 1050.0, 1180.0, "test"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_usa_el_mep_de_la_fecha_no_el_config_viejo(self):
        self.assertAlmostEqual(
            main._autodeposit_rate(self.conn, self.uid, "2024-05-03"), 1180.0, places=2,
            msg="no tomó el MEP de esa fecha")

    def test_el_capital_aportado_sale_al_mep_de_la_compra(self):
        main.create_position(main.PositionIn(
            broker="Cocos", asset="GGAL", quantity=100, buy_price=1180,
            invested=118000, entry_date="2024-05-03"), uid=self.uid)
        aportado = float(self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) v FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["v"] or 0)
        # 118.000 / 1180 = 100. Con el 1415 viejo daba 83,39 (20% menos aportado → el
        # rendimiento salía inflado porque el denominador quedaba chico).
        self.assertAlmostEqual(aportado, 100.0, places=2)


class CashFlowFechaTest(unittest.TestCase):
    """El depósito a mano ahora lleva FECHA (calendario en la UI, hoy por defecto) y el
    dólar lo resuelve el SERVIDOR según esa fecha. Antes el form no mandaba fecha: todo
    caía en el mes en curso, y el rate era el que mandaba el navegador (el de hoy)."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("positions", "monthly_entries", "config", "brokers", "users", "fx_rates_daily"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cfd@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "ARS"))
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(fx_rates_daily)")]
        if "mep_venta" not in cols:
            self.conn.execute("ALTER TABLE fx_rates_daily ADD COLUMN mep_venta REAL")
        # Idéntico al seed de AutodepositRateTest: conflicto por la PK (date) y
        # `fetched_at` explícito en el SET (antes lo reseteaba el DEFAULT al
        # reinsertar). La tabla arranca vacía, así que el DO UPDATE no corre.
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT (date) DO UPDATE SET "
            "  blue_venta = EXCLUDED.blue_venta, "
            "  mep_venta  = EXCLUDED.mep_venta, "
            "  source     = EXCLUDED.source, "
            "  fetched_at = datetime('now')",
            ("2024-05-03", 1050.0, 1180.0, "test"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_deposito_retroactivo_va_al_mes_y_al_dolar_de_esa_fecha(self):
        # El navegador manda 1415 (el de hoy); el server tiene que ignorarlo y usar el
        # MEP del 2024-05-03 (1180).
        main.cash_flow(main.CashFlowIn(broker_name="Cocos", direction="deposit",
                                       amount=118000, tc_blue=1415, date="2024-05-03"),
                       uid=self.uid)
        r = self.conn.execute(
            "SELECT year, month, deposits FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()
        self.assertEqual((r["year"], r["month"]), (2024, 5), "no quedó en el mes de la fecha")
        self.assertAlmostEqual(r["deposits"], 100.0, places=2,
                               msg="no usó el dólar de esa fecha (al de hoy daba 83,39)")


if __name__ == "__main__":
    unittest.main()
