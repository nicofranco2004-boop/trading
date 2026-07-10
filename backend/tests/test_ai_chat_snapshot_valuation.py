"""Audit IA #2 — M1/M2 (snapshot valuado server-side).

El snapshot del chat traía `invested` en moneda NATIVA mezclada (ARS+USD 1:1) y
SIN valor de mercado → la IA rankeaba "posición más grande" con pesos crudos e
inflaba el "total invertido" ~MEP×. Ahora se valúa server-side con la función
canónica. Tests:

1. INVARIANTE: valuar posición-por-posición (lista de 1) == valuar por-broker.
   Es lo que hace que el desglose por-posición no tenga drift.
2. B-1: un CEDEAR en pesos NO infla el total invertido USD.
3. B-2: el ranking por value_usd elige el activo correcto (no el de más pesos).
"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from snapshots_job import compute_broker_value_usd
import main


class TestPerPositionInvariant(unittest.TestCase):
    """La suma de valuar cada posición sola == valuar todas juntas por broker.
    Sin esto, el value_usd por-posición del snapshot divergería del total."""

    def _assert_matches(self, positions, prices, ccy, tc, mep, name=''):
        whole = compute_broker_value_usd(positions, prices, ccy, tc,
                                         broker_name=name, cedear_rate=mep)
        sv = si = 0.0
        for p in positions:
            r = compute_broker_value_usd([p], prices, ccy, tc,
                                         broker_name=name, cedear_rate=mep)
            sv += r['value']; si += r['invested']
        self.assertAlmostEqual(whole['value'], sv, places=4)
        self.assertAlmostEqual(whole['invested'], si, places=4)

    def test_ars_broker_mixed_lots(self):
        pos = [
            {'asset': 'AAPL', 'asset_type': 'cedear', 'is_cash': False,
             'invested': 1_400_000, 'quantity': 10, 'commissions': 0,
             'price_override': None, 'currency': 'ARS'},
            {'asset': 'ARS', 'asset_type': None, 'is_cash': True,
             'invested': 700_000, 'quantity': 0, 'commissions': 0,
             'price_override': None, 'currency': 'ARS'},
        ]
        self._assert_matches(pos, {'AAPL.BA': 140_000}, 'ARS', 1000, 1400)

    def test_usd_broker_multi(self):
        pos = [
            {'asset': 'MSFT', 'asset_type': 'stock', 'is_cash': False,
             'invested': 5000, 'quantity': 10, 'commissions': 0,
             'price_override': None, 'currency': 'USD'},
            {'asset': 'NVDA', 'asset_type': 'stock', 'is_cash': False,
             'invested': 2000, 'quantity': 5, 'commissions': 0,
             'price_override': None, 'currency': 'USD'},
        ]
        self._assert_matches(pos, {'MSFT': 600, 'NVDA': 500}, 'USD', 1000, 1400)


class TestChatSnapshotValuation(unittest.TestCase):
    """_valuate_positions_for_chat / _enrich_chat_snapshot_valuation contra una
    DB real (main.get_db) con un CEDEAR en pesos + una acción US."""

    def setUp(self):
        main._CHAT_VAL_CACHE.clear()  # uid puede reusarse entre tests
        self.conn = main.get_db()
        # addCleanup: cierra la conn AUNQUE setUp falle a mitad — si no, la
        # write-txn abierta queda como lock permanente para el resto de la
        # suite (cascada de "database is locked" de 45s en otros archivos).
        self.addCleanup(self.conn.close)
        for t in ("positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"aisnap-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "IOL", "ARS"))
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Schwab", "USD"))
        # CEDEAR comprado en 1.400.000 ARS (~US$1.000 al MEP 1400)
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, commissions, price_override, currency) "
            "VALUES (?,?,?,?,0,?,?,0,NULL,?)",
            (self.uid, "IOL", "AAPL", "cedear", 1_400_000, 10, "ARS"))
        # Acción US de US$5.000 (vale 6.000 hoy)
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, commissions, price_override, currency) "
            "VALUES (?,?,?,?,0,?,?,0,NULL,?)",
            (self.uid, "Schwab", "MSFT", "stock", 5000, 10, "USD"))
        self.conn.commit()

    def tearDown(self):
        # No dejar minas FK a otros archivos de test sobre la misma DB: si
        # dejamos positions/brokers apuntando a users, el "DELETE FROM users"
        # de otro setUp viola FK. La conn la cierra addCleanup.
        for t in ("positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    def _valuate(self):
        main._CHAT_VAL_CACHE.pop(self.uid, None)  # evitar hit de test previo
        with patch.object(main, "fetch_prices_for_symbols",
                          return_value={'AAPL.BA': 140_000, 'MSFT': 600, 'NVDA': 500}), \
             patch.object(main, "_user_tc_blue", return_value=1500), \
             patch.object(main, "_user_tc_cedear", return_value=1400):
            return main._valuate_positions_for_chat(self.conn, self.uid)

    def test_b1_total_invested_not_inflated(self):
        """total_invested_usd = 1000 (CEDEAR) + 5000 (US) = 6000 — NO 1.405.000."""
        valued, totals = self._valuate()
        self.assertAlmostEqual(totals["total_invested_usd"], 6000, delta=2)
        self.assertLess(totals["total_invested_usd"], 10000)  # jamás ~1.4M

    def test_b2_largest_position_by_value(self):
        """Ordenado por value_usd, MSFT (6000) > AAPL (1000). El bug del front
        rankeaba AAPL (1.400.000 crudo > 5.000)."""
        valued, _ = self._valuate()
        by_val = sorted(valued, key=lambda p: p["value_usd"], reverse=True)
        self.assertEqual(by_val[0]["asset"], "MSFT")
        aapl = next(p for p in valued if p["asset"] == "AAPL")
        self.assertAlmostEqual(aapl["value_usd"], 1000, delta=2)
        self.assertAlmostEqual(aapl["invested_usd"], 1000, delta=2)

    def test_weights_sum_100_over_holdings(self):
        valued, _ = self._valuate()
        w = sum(p["weight_pct"] for p in valued if p["weight_pct"] is not None)
        self.assertAlmostEqual(w, 100.0, delta=0.5)

    def test_totals_and_fx_stamped(self):
        valued, totals = self._valuate()
        self.assertAlmostEqual(totals["total_value_usd"], 7000, delta=2)  # 1000+6000
        self.assertEqual(totals["tc_mep"], 1400)
        self.assertEqual(totals["tc_blue"], 1500)

    def test_b2_dca_multi_lot_aggregated_by_holding(self):
        """3 lotes de NVDA (US$3.000 c/u = 9.000) en un broker USD deben
        colapsar a UNA entrada de 9.000 y ganarle a MSFT (6.000). Sin agrupar,
        cada lote (3.000) perdía contra MSFT (review B2)."""
        for _ in range(3):
            self.conn.execute(
                "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
                "invested, quantity, commissions, price_override, currency) "
                "VALUES (?,?,?,?,0,?,?,0,NULL,?)",
                (self.uid, "Schwab", "NVDA", "stock", 3000, 6, "USD"))
        self.conn.commit()
        valued, _ = self._valuate()
        nvda = [p for p in valued if p["asset"] == "NVDA"]
        self.assertEqual(len(nvda), 1)                       # UNA entrada, no 3
        self.assertAlmostEqual(nvda[0]["value_usd"], 9000, delta=5)  # 500×18
        by_val = sorted(valued, key=lambda p: p["value_usd"], reverse=True)
        self.assertEqual(by_val[0]["asset"], "NVDA")         # 9000 > MSFT 6000

    def test_quantity_not_double_counted(self):
        """quantity agregado = suma REAL de lotes (no siembra+acumula). MSFT de
        1 lote de 10 → 10, no 20 (review: el 1er lote se contaba dos veces)."""
        # MSFT ya es 1 lote de 10 (setUp). Agrego NVDA 6+4 = 10.
        for q in (6, 4):
            self.conn.execute(
                "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
                "invested, quantity, commissions, price_override, currency) "
                "VALUES (?,?,?,?,0,?,?,0,NULL,?)",
                (self.uid, "Schwab", "NVDA", "stock", 3000, q, "USD"))
        self.conn.commit()
        valued, _ = self._valuate()
        msft = next(p for p in valued if p["asset"] == "MSFT")
        nvda = next(p for p in valued if p["asset"] == "NVDA")
        self.assertEqual(msft["quantity"], 10)   # 1 lote, NO 20
        self.assertEqual(nvda["quantity"], 10)   # 6+4, NO 16

    def test_mutation_invalidates_cache(self):
        """_ai_cache_invalidate dropea la valuación cacheada del chat → tras una
        mutación el chat no sirve números viejos."""
        self._valuate()  # puebla el cache
        self.assertIn(self.uid, main._CHAT_VAL_CACHE)
        main._ai_cache_invalidate(self.uid)
        self.assertNotIn(self.uid, main._CHAT_VAL_CACHE)

    def test_b1_orphan_position_skipped_not_usd_default(self):
        """Una posición cuyo broker NO está en `brokers` (huérfana) se DESCARTA,
        no se valúa como USD (que contaría pesos 1:1 → ~MEP× inflado)."""
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, commissions, price_override, currency) "
            "VALUES (?,?,?,?,0,?,?,0,NULL,?)",
            (self.uid, "BrokerBorrado", "GGAL", "stock", 2_000_000, 100, "ARS"))
        self.conn.commit()
        valued, totals = self._valuate()
        self.assertFalse(any(p["asset"] == "GGAL" for p in valued))
        self.assertLess(totals["total_value_usd"], 10000)   # sin el ×2M fantasma

    def test_cash_has_no_weight(self):
        """El cash entra a total_value_usd pero weight_pct=None (no compite por
        'posición más grande')."""
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, commissions, price_override, currency) "
            "VALUES (?,?,?,NULL,1,?,0,0,NULL,?)",
            (self.uid, "Schwab", "USD", 3000, "USD"))
        self.conn.commit()
        valued, _ = self._valuate()
        cash = next(p for p in valued if p["is_cash"])
        self.assertIsNone(cash["weight_pct"])

    def test_ttl_cache_avoids_refetch(self):
        """2da llamada dentro del TTL no re-fetchea precios (cache hit)."""
        main._CHAT_VAL_CACHE.pop(self.uid, None)
        with patch.object(main, "fetch_prices_for_symbols",
                          return_value={'AAPL.BA': 140_000, 'MSFT': 600}) as mock_fetch, \
             patch.object(main, "_user_tc_blue", return_value=1500), \
             patch.object(main, "_user_tc_cedear", return_value=1400):
            main._valuate_positions_for_chat(self.conn, self.uid)
            main._valuate_positions_for_chat(self.conn, self.uid)
        self.assertEqual(mock_fetch.call_count, 1)  # 2da vino del cache
        main._CHAT_VAL_CACHE.pop(self.uid, None)

    def test_enrich_overwrites_client_summary(self):
        """El wrapper pisa el total_invested_usd (posiblemente inflado) del cliente
        y agrega el valuation_note + posiciones valuadas."""
        client_snap = {
            "summary": {"total_invested_usd": 1_405_000, "months_count": 3},
            "positions": [{"asset": "AAPL", "invested": 1_400_000}],  # crudo, se descarta
            "operations": [],
        }
        # El wrapper abre su propia conn vía main.get_db() → la misma DB de test
        # donde ya commiteamos las posiciones en setUp.
        with patch.object(main, "fetch_prices_for_symbols",
                          return_value={'AAPL.BA': 140_000, 'MSFT': 600}), \
             patch.object(main, "_user_tc_blue", return_value=1500), \
             patch.object(main, "_user_tc_cedear", return_value=1400):
            out = main._enrich_chat_snapshot_valuation(self.uid, client_snap)
        self.assertLess(out["summary"]["total_invested_usd"], 10000)   # pisado
        self.assertEqual(out["summary"]["months_count"], 3)            # preservado
        self.assertIn("valuation_note", out["summary"])
        self.assertTrue(all("value_usd" in p for p in out["positions"]))

    def test_enrich_never_raises_on_failure(self):
        """Si la valuación falla, devuelve el snapshot como vino (degradación)."""
        snap = {"summary": {"x": 1}, "positions": []}
        with patch.object(main, "_valuate_positions_for_chat",
                          side_effect=RuntimeError("boom")):
            out = main._enrich_chat_snapshot_valuation(self.uid, snap)
        self.assertEqual(out, snap)


if __name__ == "__main__":
    unittest.main()
