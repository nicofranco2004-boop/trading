"""register_trade / undo_last_trade — el write-path conversacional del Coach.

Cubre el diseño completo: 2 fases server-enforced (needs_info →
needs_confirmation+token → registered), token single-use/TTL, derivación
quantity↔amount server-side, regla de precio retroactivo, allowlist,
ambigüedad CEDEAR/acción, venta contra FIFO real, undo con cash exacto y el
refund de cuota (1 registro completo = 1 uso)."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import main
from ai.trade_tickers import resolve_asset


def _call(input_data, uid):
    """Vía el dispatch real (cubre el wiring, no solo el handler)."""
    return main._execute_ai_tool_inner("register_trade", input_data, uid)


class TestResolveAsset(unittest.TestCase):
    def test_unambiguous_and_aliases(self):
        self.assertEqual(resolve_asset("BTC"), ("BTC", {"CRYPTO"}))
        self.assertEqual(resolve_asset("bitcoin")[0], "BTC")
        self.assertEqual(resolve_asset("GGAL"), ("GGAL", {"AR_STOCK"}))

    def test_ambiguous_amzn(self):
        t, kinds = resolve_asset("amazon")
        self.assertEqual(t, "AMZN")
        self.assertEqual(kinds, {"STOCK", "CEDEAR"})

    def test_garbage(self):
        self.assertEqual(resolve_asset("CHORIPAN"), (None, set()))


class _TradeBase(unittest.TestCase):
    def setUp(self):
        main._PENDING_TRADES.clear()
        main._LAST_CHAT_TRADE.clear()
        main._CHAT_VAL_CACHE.clear()
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("operations", "monthly_entries", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"rt-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Binance", "USDT"))
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Balanz", "ARS"))
        # Cash inicial en Binance: 5.000 USD
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, currency) "
            "VALUES (?,?,?,1,5000,'USD')", (self.uid, "Binance", "USD"))
        self.conn.commit()

    def tearDown(self):
        for t in ("operations", "monthly_entries", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    def _cash(self, broker="Binance"):
        r = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()
        return float(r["invested"]) if r else 0.0

    def _buy_btc_phase1(self, **over):
        base = {"action": "buy", "asset": "BTC", "broker": "Binance",
                "currency": "USD", "amount": 2000, "price": 65000}
        base.update(over)
        return _call(base, self.uid)


class TestPhase1(_TradeBase):
    def test_needs_info_lists_missing_with_hints(self):
        r = _call({"action": "buy", "asset": "BTC"}, self.uid)
        self.assertEqual(r["status"], "needs_info")
        joined = " ".join(r["missing"])
        self.assertIn("broker", joined)
        self.assertIn("price", joined)
        self.assertTrue(any("Binance" in h for h in r["hints"]))  # sus brokers reales

    def test_ambiguous_asset_asks_with_holdings_hint(self):
        # El user YA tiene AMZN CEDEAR en Balanz → el hint lo dice
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, currency) VALUES (?,?,?,?,0,100000,20,'ARS')",
            (self.uid, "Balanz", "AMZN", "CEDEAR"))
        self.conn.commit()
        r = _call({"action": "sell", "asset": "amazon", "broker": "Balanz",
                   "currency": "ARS", "quantity": 20, "price": 5000}, self.uid)
        self.assertEqual(r["status"], "needs_info")
        self.assertTrue(any("asset_type" in m for m in r["missing"]))
        self.assertTrue(any("CEDEAR" in h and "Balanz" in h for h in r["hints"]))

    def test_unknown_broker_lists_real_ones(self):
        r = self._buy_btc_phase1(broker="Cocos")
        self.assertIn("error", r)
        self.assertIn("Binance", r["error"])

    def test_unknown_asset_rejected(self):
        r = self._buy_btc_phase1(asset="CHORIPAN")
        self.assertIn("error", r)

    def test_phase1_returns_token_and_writes_NOTHING(self):
        r = self._buy_btc_phase1()
        self.assertEqual(r["status"], "needs_confirmation")
        self.assertTrue(r["confirmation_token"].startswith("ct_"))
        self.assertIn("0,03076923", r["summary"])       # derivación server-side
        self.assertIn("no toca tu cuenta", r["_note"])
        n = self.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=0",
            (self.uid,)).fetchone()[0]
        self.assertEqual(n, 0)                            # NADA escrito
        self.assertEqual(self._cash(), 5000.0)            # cash intacto

    def test_inconsistent_qty_amount_rejected(self):
        r = self._buy_btc_phase1(quantity=1.0)  # 1×65000 ≠ 2000
        self.assertIn("error", r)
        self.assertIn("no cierran", r["error"])

    def test_retroactive_with_market_price_rejected(self):
        r = self._buy_btc_phase1(date="2026-06-01", price_source="market_today")
        self.assertIn("error", r)
        self.assertIn("retroactiva", r["error"])

    def test_future_date_rejected(self):
        r = self._buy_btc_phase1(date="2030-01-01")
        self.assertIn("error", r)

    def test_notional_cap(self):
        r = self._buy_btc_phase1(amount=9_000_000, price=65000)
        self.assertIn("error", r)

    def test_sell_more_than_held_rejected_in_phase1(self):
        r = _call({"action": "sell", "asset": "BTC", "broker": "Binance",
                   "currency": "USD", "quantity": 5, "price": 65000}, self.uid)
        self.assertIn("error", r)
        self.assertIn("quiere vender", r["error"])

    def test_autodeposit_warned_in_summary(self):
        r = self._buy_btc_phase1(amount=8000, price=65000)  # cash 5000 < 8000
        self.assertEqual(r["status"], "needs_confirmation")
        self.assertIn("depósito", r["summary"])            # transparencia


class TestPhase2Confirm(_TradeBase):
    def test_confirm_writes_position_and_debits_cash(self):
        r1 = self._buy_btc_phase1()
        r2 = _call({"action": "buy", "asset": "BTC", "confirmed": True,
                    "confirmation_token": r1["confirmation_token"]}, self.uid)
        self.assertEqual(r2["status"], "registered")
        row = self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["quantity"], 2000 / 65000, places=8)
        self.assertAlmostEqual(row["invested"], 2000.0, places=2)
        self.assertEqual(row["asset_type"], "CRYPTO")
        self.assertEqual(row["currency"], "USD")
        self.assertEqual(self._cash(), 3000.0)             # 5000 − 2000

    def test_token_single_use(self):
        r1 = self._buy_btc_phase1()
        tok = r1["confirmation_token"]
        _call({"confirmed": True, "confirmation_token": tok,
               "action": "buy", "asset": "BTC"}, self.uid)
        r3 = _call({"confirmed": True, "confirmation_token": tok,
                    "action": "buy", "asset": "BTC"}, self.uid)
        self.assertIn("error", r3)                          # segundo uso rebota
        n = self.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()[0]
        self.assertEqual(n, 1)                              # UNA sola posición

    def test_wrong_token_rejected(self):
        self._buy_btc_phase1()
        r = _call({"confirmed": True, "confirmation_token": "ct_trucho",
                   "action": "buy", "asset": "BTC"}, self.uid)
        self.assertIn("error", r)

    def test_expired_token_rejected(self):
        r1 = self._buy_btc_phase1()
        main._PENDING_TRADES[self.uid]["ts"] -= (main._PENDING_TRADE_TTL + 1)
        r = _call({"confirmed": True,
                   "confirmation_token": r1["confirmation_token"],
                   "action": "buy", "asset": "BTC"}, self.uid)
        self.assertIn("error", r)

    def test_executes_SAVED_payload_not_resent_numbers(self):
        """Anti-manipulación: el modelo re-manda números distintos en la
        confirmación → se escribe LO QUE EL USER CONFIRMÓ (el payload)."""
        r1 = self._buy_btc_phase1()  # amount 2000 @ 65000
        _call({"action": "buy", "asset": "BTC", "amount": 999999,
               "price": 1, "quantity": 999999, "confirmed": True,
               "confirmation_token": r1["confirmation_token"]}, self.uid)
        row = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()
        self.assertAlmostEqual(row["invested"], 2000.0, places=2)

    def test_sell_happy_path_creates_operation(self):
        # Seed: 0.1 BTC comprado a 50k
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, buy_price, currency, entry_date) "
            "VALUES (?,?,?,?,0,5000,0.1,50000,'USD','2026-01-10')",
            (self.uid, "Binance", "BTC", "CRYPTO"))
        self.conn.commit()
        r1 = _call({"action": "sell", "asset": "BTC", "broker": "Binance",
                    "currency": "USD", "quantity": 0.05, "price": 70000}, self.uid)
        self.assertEqual(r1["status"], "needs_confirmation")
        r2 = _call({"confirmed": True,
                    "confirmation_token": r1["confirmation_token"],
                    "action": "sell", "asset": "BTC"}, self.uid)
        self.assertEqual(r2["status"], "registered")
        op = self.conn.execute(
            "SELECT * FROM operations WHERE user_id=? AND asset='BTC'",
            (self.uid,)).fetchone()
        self.assertIsNotNone(op)                            # VENTA registrada
        left = self.conn.execute(
            "SELECT quantity FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()
        self.assertAlmostEqual(float(left["quantity"]), 0.05, places=8)


class TestUndo(_TradeBase):
    def _register_buy(self):
        r1 = self._buy_btc_phase1()
        return _call({"confirmed": True,
                      "confirmation_token": r1["confirmation_token"],
                      "action": "buy", "asset": "BTC"}, self.uid)

    def test_undo_deletes_position_and_returns_exact_cash(self):
        self._register_buy()
        self.assertEqual(self._cash(), 3000.0)
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertEqual(r["status"], "undone")
        n = self.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()[0]
        self.assertEqual(n, 0)                              # posición borrada
        self.assertEqual(self._cash(), 5000.0)              # cash EXACTO devuelto

    def test_undo_without_recent_trade(self):
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertIn("error", r)

    def test_undo_sell_not_automatic(self):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, buy_price, currency) VALUES (?,?,?,?,0,5000,0.1,50000,'USD')",
            (self.uid, "Binance", "BTC", "CRYPTO"))
        self.conn.commit()
        r1 = _call({"action": "sell", "asset": "BTC", "broker": "Binance",
                    "currency": "USD", "quantity": 0.05, "price": 70000}, self.uid)
        _call({"confirmed": True, "confirmation_token": r1["confirmation_token"],
               "action": "sell", "asset": "BTC"}, self.uid)
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertIn("error", r)
        self.assertIn("COMPRAS", r["error"])

    def test_undo_blocked_if_position_changed(self):
        self._register_buy()
        self.conn.execute(
            "UPDATE positions SET quantity = quantity / 2 "
            "WHERE user_id=? AND asset='BTC' AND is_cash=0", (self.uid,))
        self.conn.commit()
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertIn("error", r)
        self.assertEqual(self._cash(), 3000.0)              # cash NO tocado

    def test_undo_blocked_after_autodeposit(self):
        r1 = self._buy_btc_phase1(amount=8000, price=65000)  # cash 5000 < 8000
        _call({"confirmed": True, "confirmation_token": r1["confirmation_token"],
               "action": "buy", "asset": "BTC"}, self.uid)
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertIn("error", r)
        self.assertIn("depósito", r["error"])


class TestQuotaRefund(unittest.TestCase):
    def test_continuation_with_trade_tool_refunds(self):
        with patch.object(main, "_refund_chat_quota") as m:
            main._maybe_refund_trade_turn(1, True, {"trade_tool"})
        m.assert_called_once_with(1)

    def test_first_turn_no_refund(self):
        with patch.object(main, "_refund_chat_quota") as m:
            main._maybe_refund_trade_turn(1, False, {"trade_tool"})
        m.assert_not_called()

    def test_pending_but_no_trade_tool_no_refund(self):
        """Chatear de otra cosa con un pending abierto NO refundea."""
        with patch.object(main, "_refund_chat_quota") as m:
            main._maybe_refund_trade_turn(1, True, set())
        m.assert_not_called()

    def test_successful_undo_refunds(self):
        with patch.object(main, "_refund_chat_quota") as m:
            main._maybe_refund_trade_turn(1, False, {"undo_ok"})
        m.assert_called_once_with(1)


class TestFreeGateTradeIntent(unittest.TestCase):
    """El gate de whitelist de Free deja pasar SOLO texto libre con intención
    de registro (o continuaciones de un flujo abierto) — el resto sigue 403."""

    def test_trade_intents_pass(self):
        for msg in ("compré 2000 usd de btc a 65000", "Vendí 20 nominales de amazon",
                    "anotá una compra de 10 GGAL", "registrame 0.1 eth"):
            self.assertTrue(main._is_trade_intent(msg), msg)

    def test_non_trade_text_blocked(self):
        for msg in ("¿está cara NVDA?", "dame un análisis de mi cartera",
                    "hola", "¿qué opinás del merval?"):
            self.assertFalse(main._is_trade_intent(msg), msg)

    def test_flow_open_allows_continuations(self):
        uid = 424242
        main._PENDING_TRADES.pop(uid, None)
        main._TRADE_FLOW_OPEN.pop(uid, None)
        self.assertFalse(main._trade_flow_open(uid))
        # needs_info marca el flujo abierto → "a 65000" pasa el gate
        main._TRADE_FLOW_OPEN[uid] = __import__("time").time()
        self.assertTrue(main._trade_flow_open(uid))
        # y expira a los 10 min
        main._TRADE_FLOW_OPEN[uid] -= (main._PENDING_TRADE_TTL + 1)
        self.assertFalse(main._trade_flow_open(uid))
        main._TRADE_FLOW_OPEN.pop(uid, None)

    def test_pending_confirmation_allows_continuation(self):
        uid = 424243
        main._PENDING_TRADES[uid] = {"token": "x", "payload": {}, "summary": "",
                                      "ts": __import__("time").time()}
        self.assertTrue(main._trade_flow_open(uid))
        main._PENDING_TRADES.pop(uid, None)


class TestToolRegistration(unittest.TestCase):
    def test_tools_registered_all_tiers(self):
        names = {t["name"] for t in main._AI_TOOLS}
        self.assertIn("register_trade", names)
        self.assertIn("undo_last_trade", names)
        free = {t["name"] for t in main._AI_TOOLS_FREE}
        self.assertIn("register_trade", free)
        self.assertIn("undo_last_trade", free)
        self.assertIn("get_current_prices", free)  # para el default de precio-hoy


class _TB:
    type = "text"
    def __init__(self, t):
        self.text = t
    def model_dump(self):
        return {"type": "text", "text": self.text}


class _UB:
    type = "tool_use"
    def __init__(self, name, tool_input, bid="tu1"):
        self.name, self.input, self.id = name, tool_input, bid
    def model_dump(self):
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


class _Resp:
    def __init__(self, content, stop="end_turn"):
        self.content, self.stop_reason, self.usage = content, stop, None


class TestChatEndToEnd(_TradeBase):
    """E2E del ENDPOINT real (/api/ai/chat, path JSON) con el LLM mockeado:
    valida el wiring completo — gate Free por intención, reserva atómica,
    ejecución de la tool, token, y que 1 registro completo = 1 uso de cuota."""

    def setUp(self):
        super().setUp()
        self.conn.execute("UPDATE users SET tier='free' WHERE id=?", (self.uid,))
        self.conn.execute("DELETE FROM ai_usage_daily")
        self.conn.commit()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _chat(self, text):
        return self.client.post(
            "/api/ai/chat",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messages": [{"role": "user", "content": text}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [],
                                "monthly": [], "brokers": []},
                  "stream": False})

    def _chat_count(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(chat_count),0) FROM ai_usage_daily WHERE user_id=?",
            (self.uid,)).fetchone()
        return r[0]

    def test_free_registers_via_endpoint_one_quota_total(self):
        calls = {"n": 0}

        def fake_create(**kwargs):
            calls["n"] += 1
            # Turno 1 (mensaje "compré..."): el modelo llama register_trade
            if calls["n"] == 1:
                return _Resp([_UB("register_trade", {
                    "action": "buy", "asset": "BTC", "broker": "Binance",
                    "currency": "USD", "amount": 2000, "price": 65000,
                })], stop="tool_use")
            if calls["n"] == 2:
                return _Resp([_TB("Voy a registrar: COMPRA 0,0308 BTC… ¿Confirmás?")])
            # Turno 2 ("sí"): el modelo confirma con el token real
            if calls["n"] == 3:
                tok = main._PENDING_TRADES[self.uid]["token"]
                return _Resp([_UB("register_trade", {
                    "action": "buy", "asset": "BTC", "confirmed": True,
                    "confirmation_token": tok,
                })], stop="tool_use")
            return _Resp([_TB("Listo, registrado ✅")])

        from unittest.mock import MagicMock
        mclient = MagicMock()
        mclient.messages.create.side_effect = fake_create
        with patch.object(main, "_get_anthropic_client", return_value=mclient), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            # Turno 1: texto libre de un FREE con intención → pasa el gate
            r1 = self._chat("compré 2000 usd de btc a 65000")
            self.assertEqual(r1.status_code, 200, r1.text)
            self.assertIn("Confirmás", r1.json()["reply"])
            self.assertEqual(self._chat_count(), 1)          # 1er turno cobra
            self.assertIn(self.uid, main._PENDING_TRADES)
            # Turno 2: continuación ("sí") → pasa el gate por flujo abierto
            r2 = self._chat("sí, confirmá")
            self.assertEqual(r2.status_code, 200, r2.text)
        # El registro quedó escrito por el MISMO camino que el alta manual
        row = self.conn.execute(
            "SELECT quantity, invested FROM positions "
            "WHERE user_id=? AND asset='BTC' AND is_cash=0", (self.uid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["invested"], 2000.0, places=2)
        self.assertEqual(self._cash(), 3000.0)
        # CUOTA: el turno 2 se refundeó → 1 registro completo = 1 uso total
        self.assertEqual(self._chat_count(), 1)

    def test_free_non_trade_text_still_403(self):
        from unittest.mock import MagicMock
        with patch.object(main, "_get_anthropic_client", return_value=MagicMock()):
            r = self._chat("dame un análisis profundo de mi cartera")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._chat_count(), 0)              # no consumió cuota


if __name__ == "__main__":
    unittest.main()
