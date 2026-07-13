"""register_trade / undo_last_trade — write-path conversacional del Coach
(REDISEÑADO tras el review adversarial). Cubre los bloqueantes que el review
encontró en la v1:
  B1 confirmación stateless + turn-boundary (el server lleva el estado, no un
     token que viaja al modelo; confirmar solo desde un request DISTINTO)
  B2 venta ARS con tc_venta (P&L en USD, no pnl_ars contado como USD ×1415)
  B3 coherencia moneda↔broker + FIFO currency-aware
  B4 cuota: 1 registro completo = 1 uso (continuaciones gratis, cap anti-abuso)
  B5 claim atómico (pop-first)
+ E2E HONESTO del endpoint real: el fake model construye sus tool_use SOLO
  desde messages (prohibido leer estado del server) — el flujo funciona por la
  inyección del draft en el contexto, no por trampa.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import main
from ai.trade_tickers import resolve_asset


def _h(input_data, uid, request_id="req1", confirm_signal=""):
    return main._register_trade_handler(input_data, uid, request_id=request_id,
                                        confirm_signal=confirm_signal)


def _yes(input_data, uid, request_id="B"):
    """Confirmación con señal-sí del usuario (como la computa ai_chat)."""
    return _h(input_data, uid, request_id=request_id, confirm_signal="yes")


class TestResolveAsset(unittest.TestCase):
    def test_unambiguous_alias_ambiguous_garbage(self):
        self.assertEqual(resolve_asset("BTC"), ("BTC", {"CRYPTO"}))
        self.assertEqual(resolve_asset("bitcoin")[0], "BTC")
        self.assertEqual(resolve_asset("GGAL"), ("GGAL", {"AR_STOCK"}))
        self.assertEqual(resolve_asset("amazon"), ("AMZN", {"STOCK", "CEDEAR"}))
        self.assertEqual(resolve_asset("CHORIPAN"), (None, set()))

    def test_multiword_and_separator_variants(self):
        """El caso REAL de la prueba de Nico: 'space x' (con espacio) no
        resolvía → el modelo inventaba tickers. SPCX SÍ está en Rendi."""
        self.assertEqual(resolve_asset("space x")[0], "SPCX")
        self.assertEqual(resolve_asset("spacex")[0], "SPCX")
        self.assertEqual(resolve_asset("coca cola")[0], "KO")
        self.assertEqual(resolve_asset("brk.b")[0], "BRK-B")
        self.assertEqual(resolve_asset("BRK B")[0], "BRK-B")
        # y lo compactado NO abre falsos positivos
        self.assertEqual(resolve_asset("CHORI PAN"), (None, set()))


class _Base(unittest.TestCase):
    def setUp(self):
        main._TRADE_DRAFT.clear()
        main._LAST_CHAT_TRADE.clear()
        main._CHAT_VAL_CACHE.clear()
        # Los tests NUNCA tocan el feed real: fail-open por default (los tests
        # del cinturón/market_today lo re-parchean con su propio valor).
        _mp = patch.object(main, "_trade_market_price", return_value=None)
        _mp.start()
        self.addCleanup(_mp.stop)
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("operations", "monthly_entries", "positions", "brokers", "users", "ai_usage_daily"):
            self.conn.execute(f"DELETE FROM {t}")
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'free')",
            (f"rt-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Binance", "USDT"))
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Balanz", "ARS"))
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, currency) "
            "VALUES (?,?,?,1,5000,'USD')", (self.uid, "Binance", "USD"))
        self.conn.commit()

    def tearDown(self):
        for t in ("operations", "monthly_entries", "positions", "brokers", "users", "ai_usage_daily"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    def _cash(self, broker="Binance"):
        r = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()
        return float(r["invested"]) if r else 0.0


class TestPhase1Validation(_Base):
    def test_needs_info_lists_missing_with_hints(self):
        r = _h({"action": "buy", "asset": "BTC"}, self.uid)
        self.assertEqual(r["status"], "needs_info")
        joined = " ".join(r["missing"])
        self.assertIn("broker", joined)
        self.assertIn("price", joined)
        self.assertTrue(any("Binance" in h for h in r["hints"]))

    def test_ambiguous_asset_asks_with_holdings_hint(self):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, currency) VALUES (?,?,?,?,0,100000,20,'ARS')",
            (self.uid, "Balanz", "AMZN", "CEDEAR"))
        self.conn.commit()
        r = _h({"action": "sell", "asset": "amazon", "broker": "Balanz",
                "quantity": 20, "price": 5000}, self.uid)
        self.assertEqual(r["status"], "needs_info")
        self.assertTrue(any("asset_type" in m for m in r["missing"]))
        self.assertTrue(any("CEDEAR" in h and "Balanz" in h for h in r["hints"]))

    def test_unknown_broker_and_asset_rejected(self):
        self.assertIn("error", _h({"action": "buy", "asset": "BTC", "broker": "Cocos",
                                    "amount": 100, "price": 65000}, self.uid))
        self.assertIn("error", _h({"action": "buy", "asset": "CHORIPAN", "broker": "Binance",
                                    "amount": 100, "price": 1}, self.uid))

    def test_currency_forced_to_broker(self):
        """Broker conocido → la moneda la manda el server (la del broker)."""
        r = _h({"action": "buy", "asset": "BTC", "broker": "Binance",
                "amount": 2000, "price": 65000}, self.uid)  # sin currency
        self.assertEqual(r["status"], "needs_confirmation")
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["currency"], "USD")

    def test_currency_broker_mismatch_rejected(self):
        r = _h({"action": "buy", "asset": "GGAL", "asset_type": "AR_STOCK",
                "broker": "Balanz", "currency": "USD", "amount": 1000, "price": 2000}, self.uid)
        self.assertIn("error", r)
        self.assertIn("ARS", r["error"])

    def test_inconsistent_qty_amount_rejected(self):
        r = _h({"action": "buy", "asset": "BTC", "broker": "Binance",
                "quantity": 1.0, "amount": 2000, "price": 65000}, self.uid)
        self.assertIn("error", r)

    def test_quantity_rounds_to_zero_rejected(self):
        r = _h({"action": "buy", "asset": "BTC", "broker": "Binance",
                "amount": 0.0000001, "price": 65000}, self.uid)
        self.assertIn("error", r)

    def test_retroactive_market_price_rejected(self):
        r = _h({"action": "buy", "asset": "BTC", "broker": "Binance", "amount": 2000,
                "price": 65000, "date": "2026-06-01", "price_source": "market_today"}, self.uid)
        self.assertIn("error", r)
        self.assertIn("retroactiva", r["error"])

    def test_cedear_market_price_as_usd_rejected(self):
        """get_current_prices da .BA en ARS → no registrar CEDEAR/acción AR como USD."""
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "IOL·USD", "USD"))
        self.conn.commit()
        r = _h({"action": "buy", "asset": "GGAL", "asset_type": "AR_STOCK",
                "broker": "IOL·USD", "currency": "USD", "amount": 1000, "price": 2000,
                "price_source": "market_today"}, self.uid)
        self.assertIn("error", r)

    def test_notional_cap_per_currency(self):
        # ARS 5M NO se bloquea (compra AR rutinaria); ARS 6000M sí
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, currency) "
            "VALUES (?,?,?,1,9000000000,'ARS')", (self.uid, "Balanz", "ARS"))
        self.conn.commit()
        ok = _h({"action": "buy", "asset": "GGAL", "asset_type": "AR_STOCK",
                 "broker": "Balanz", "amount": 5_000_000, "price": 2000}, self.uid)
        self.assertEqual(ok["status"], "needs_confirmation")
        main._TRADE_DRAFT.clear()
        bad = _h({"action": "buy", "asset": "GGAL", "asset_type": "AR_STOCK",
                  "broker": "Balanz", "amount": 6_000_000_000, "price": 2000}, self.uid)
        self.assertIn("error", bad)

    def test_phase1_writes_nothing(self):
        r = _h({"action": "buy", "asset": "BTC", "broker": "Binance",
                "amount": 2000, "price": 65000}, self.uid)
        self.assertEqual(r["status"], "needs_confirmation")
        self.assertNotIn("confirmation_token", r)      # ya no hay token al modelo
        n = self.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=0",
            (self.uid,)).fetchone()[0]
        self.assertEqual(n, 0)                          # NADA escrito en fase 1
        self.assertEqual(self._cash(), 5000.0)


class TestTurnBoundary(_Base):
    def test_confirm_same_request_rejected(self):
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "amount": 2000, "price": 65000}, self.uid, request_id="A")
        r = _h({"confirm_pending": True}, self.uid, request_id="A", confirm_signal="yes")  # MISMO request
        self.assertIn("error", r)
        self.assertIn("NO confirmes", r["error"])
        # el draft sigue vivo (no se perdió)
        self.assertIn(self.uid, main._TRADE_DRAFT)

    def test_confirm_next_request_executes(self):
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "amount": 2000, "price": 65000}, self.uid, request_id="A")
        r = _h({"confirm_pending": True}, self.uid, request_id="B", confirm_signal="yes")  # request nuevo
        self.assertEqual(r["status"], "registered")
        self.assertEqual(self._cash(), 3000.0)

    def test_confirm_without_pending_rejected(self):
        r = _h({"confirm_pending": True}, self.uid, request_id="Z", confirm_signal="yes")
        self.assertIn("error", r)

    def test_cancel_clears_draft(self):
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "amount": 2000, "price": 65000}, self.uid, request_id="A")
        r = _h({"cancel": True}, self.uid, request_id="B")
        self.assertEqual(r["status"], "cancelled")
        self.assertNotIn(self.uid, main._TRADE_DRAFT)


class TestConfirmAtomicAndBoundary(_Base):
    def test_double_confirm_writes_once(self):
        """Claim atómico (pop-first): dos confirmaciones del mismo draft →
        una sola escribe."""
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "amount": 2000, "price": 65000}, self.uid, request_id="A")
        r1 = _h({"confirm_pending": True}, self.uid, request_id="B", confirm_signal="yes")
        r2 = _h({"confirm_pending": True}, self.uid, request_id="C", confirm_signal="yes")
        statuses = {r1.get("status"), r2.get("status")}
        self.assertIn("registered", statuses)
        self.assertTrue("error" in r1 or "error" in r2)  # el segundo rebota
        n = self.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()[0]
        self.assertEqual(n, 1)


class TestSellARS(_Base):
    def setUp(self):
        super().setUp()
        # GGAL en Balanz (ARS): 50 nominales @ 2000
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, buy_price, currency, entry_date) "
            "VALUES (?,?,?,?,0,100000,50,2000,'ARS','2026-01-10')",
            (self.uid, "Balanz", "GGAL", "STOCK"))
        self.conn.commit()

    def test_sell_ars_captures_tc_venta(self):
        with patch.object(main, "_current_cedear_rate", return_value=1415.0):
            r = _h({"action": "sell", "asset": "GGAL", "broker": "Balanz",
                    "quantity": 20, "price": 5000}, self.uid, request_id="A")
        self.assertEqual(r["status"], "needs_confirmation")
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["tc_venta"], 1415.0)

    def test_sell_ars_pnl_in_usd_not_inflated(self):
        """El bug critical: sin tc_venta, pnl_usd = pnl_ars = ~1415× inflado."""
        with patch.object(main, "_current_cedear_rate", return_value=1415.0):
            _h({"action": "sell", "asset": "GGAL", "broker": "Balanz",
                "quantity": 20, "price": 5000}, self.uid, request_id="A")
            r = _h({"confirm_pending": True}, self.uid, request_id="B", confirm_signal="yes")
        self.assertEqual(r["status"], "registered")
        op = self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND asset='GGAL'",
            (self.uid,)).fetchone()
        # 20×5000 − 40000 costo = 60000 ARS de P&L → /1415 ≈ US$42, NO 60000
        self.assertLess(abs(op["pnl_usd"]), 1000)   # en USD, no en pesos
        self.assertGreater(op["pnl_usd"], 10)

    def test_sell_more_than_held_rejected(self):
        r = _h({"action": "sell", "asset": "GGAL", "broker": "Balanz",
                "quantity": 999, "price": 5000}, self.uid, request_id="A")
        self.assertIn("error", r)


class TestSellFifoCurrencyAware(_Base):
    def test_legacy_null_currency_lots_counted(self):
        """Lotes legacy con currency=NULL: el gate usa _native_ccy (el MISMO
        predicado del endpoint) → los cuenta y NO rechaza en falso (review M1).
        Broker USDT + lote NULL → _native_ccy lo resuelve USD."""
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, currency, entry_date) "
            "VALUES (?,?,?,?,0,5000,10,NULL,'2026-01-10')",
            (self.uid, "Binance", "SOL", "CRYPTO"))
        self.conn.commit()
        r = _h({"action": "sell", "asset": "SOL", "broker": "Binance",
                "quantity": 5, "price": 100}, self.uid, request_id="A")
        self.assertEqual(r["status"], "needs_confirmation")  # NO falso rechazo

    def test_fallback_any_ccy_when_no_same_ccy(self):
        """Sin lotes de la moneda de venta pero con lotes cross-ccy: el gate
        cae al total (misma red de seguridad legacy del endpoint) y no crashea."""
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
            "invested, quantity, currency, entry_date) "
            "VALUES (?,?,?,?,0,100000,10,'ARS','2026-01-10')",
            (self.uid, "Binance", "SOL", "CRYPTO"))
        self.conn.commit()
        r = _h({"action": "sell", "asset": "SOL", "broker": "Binance",
                "quantity": 5, "price": 100}, self.uid, request_id="A")
        self.assertIn(r.get("status", "error"), ("needs_confirmation", "error"))


class TestUndo(_Base):
    def _register_buy(self, amount=2000):
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "amount": amount, "price": 65000}, self.uid, request_id="A")
        return _h({"confirm_pending": True}, self.uid, request_id="B", confirm_signal="yes")

    def test_undo_returns_exact_cash(self):
        self._register_buy()
        self.assertEqual(self._cash(), 3000.0)
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertEqual(r["status"], "undone")
        n = self.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()[0]
        self.assertEqual(n, 0)
        self.assertEqual(self._cash(), 5000.0)

    def test_undo_blocked_after_autodeposit(self):
        self._register_buy(amount=8000)   # cash 5000 < 8000 → autodeposit real
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertIn("error", r)
        self.assertIn("depósito", r["error"])

    def test_undo_no_recent(self):
        self.assertIn("error", main._execute_ai_tool_inner("undo_last_trade", {}, self.uid))

    def test_undo_survives_broker_rename(self):
        """Undo resuelve el broker por ID → un rename entre registro y undo no
        deja cash fantasma."""
        self._register_buy()
        # Rename REAL de Rendi: cascadea a positions (linkeado por nombre)
        self.conn.execute("UPDATE brokers SET name='Binance PRO' WHERE user_id=? AND name='Binance'", (self.uid,))
        self.conn.execute("UPDATE positions SET broker='Binance PRO' WHERE user_id=? AND broker='Binance'", (self.uid,))
        self.conn.commit()
        r = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertEqual(r["status"], "undone")
        cash = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker='Binance PRO' AND is_cash=1",
            (self.uid,)).fetchone()
        self.assertEqual(float(cash["invested"]), 5000.0)   # cash al broker renombrado


class TestFreeTurnsCapSurvivesRearm(_Base):
    def test_free_turns_preserved_across_replants(self):
        """H1 del re-review: el contador anti-abuso vive en el draft y el
        handler lo re-plantaba en 0 en cada needs_info/needs_confirmation →
        chat gratis ilimitado. Ahora se preserva."""
        _h({"action": "buy", "asset": "BTC"}, self.uid, request_id="A")  # needs_info
        main._TRADE_DRAFT[self.uid]["free_turns"] = 5   # simular 5 turnos gratis
        # re-plant vía otra llamada incompleta (needs_info de nuevo)
        _h({"action": "buy", "asset": "BTC", "broker": "Binance"}, self.uid, request_id="B")
        self.assertEqual(main._TRADE_DRAFT[self.uid].get("free_turns"), 5)
        # re-plant vía needs_confirmation (draft completo)
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "amount": 2000, "price": 65000}, self.uid, request_id="C")
        self.assertEqual(main._TRADE_DRAFT[self.uid].get("free_turns"), 5)


class TestPromptsNoStaleToken(unittest.TestCase):
    def test_prompts_no_longer_mention_token_flow(self):
        """M2 del re-review: los prompts dictaban el flujo de token ELIMINADO →
        el modelo intentaba confirmed=true+confirmation_token y la confirmación
        se rompía silenciosa."""
        for sys_prompt in (main._AI_CHAT_SYSTEM, main._AI_CHAT_SYSTEM_FREE):
            self.assertNotIn("confirmation_token", sys_prompt)
            self.assertNotIn("confirmed=true", sys_prompt)
            self.assertIn("confirm_pending", sys_prompt)


class TestQuotaRefund(unittest.TestCase):
    def test_undo_ok_refunds_when_reserved(self):
        with patch.object(main, "_refund_chat_quota") as m:
            main._maybe_refund_trade_turn(1, {"undo_ok"}, reserved=True)
        m.assert_called_once_with(1)

    def test_undo_in_free_turn_no_refund(self):
        """L1 del re-review: un undo en turno GRATIS (skip-reserve) no debe
        devolver un slot que nunca se cobró."""
        with patch.object(main, "_refund_chat_quota") as m:
            main._maybe_refund_trade_turn(1, {"undo_ok"}, reserved=False)
        m.assert_not_called()

    def test_non_undo_no_refund(self):
        with patch.object(main, "_refund_chat_quota") as m:
            main._maybe_refund_trade_turn(1, {"trade_registered"}, reserved=True)
        m.assert_not_called()


class TestGateIntent(unittest.TestCase):
    def test_registration_and_undo_verbs_pass(self):
        for msg in ("compré 2000 usd de btc a 65000", "Vendí 20 de amazon",
                    "anotame una compra de 10 GGAL", "quiero registrar 0.1 eth",
                    "agregá una compra", "deshacelo", "me equivoqué"):
            self.assertTrue(main._is_trade_intent(msg), msg)

    def test_non_trade_blocked(self):
        for msg in ("¿está cara NVDA?", "dame un análisis", "hola",
                    "¿qué opinás del merval?"):
            self.assertFalse(main._is_trade_intent(msg), msg)

    def test_flow_open_allows_continuation(self):
        uid = 999001
        main._TRADE_DRAFT.pop(uid, None)
        self.assertFalse(main._trade_flow_open(uid))
        import time as _t
        main._TRADE_DRAFT[uid] = {"status": "gathering", "fields": {}, "ts": _t.time()}
        self.assertTrue(main._trade_flow_open(uid))
        main._TRADE_DRAFT[uid]["ts"] -= (main._TRADE_DRAFT_TTL + 1)
        self.assertFalse(main._trade_flow_open(uid))
        main._TRADE_DRAFT.pop(uid, None)


class TestConfirmWord(unittest.TestCase):
    """El short-circuit EJECUTA un write sin pasar por el modelo → todo lo
    dudoso tiene que dar '' (ambiguo) para que decida el modelo."""

    def test_clear_yes(self):
        for msg in ("sí", "si", "dale", "ok", "confirmá", "confirmo", "listo",
                    "sí, dale", "perfecto", "de una", "registralo", "hacelo",
                    "SI", "Dale!", "correcto"):
            self.assertEqual(main._confirm_word(msg), "yes", msg)

    def test_clear_no(self):
        for msg in ("no", "cancelá", "cancelalo", "mejor no", "esperá", "nop"):
            self.assertEqual(main._confirm_word(msg), "no", msg)

    def test_ambiguous_goes_to_model(self):
        for msg in (
            "va",                          # débil, ya no cuenta como sí
            "bien",
            "¿cómo va mi cartera?",        # pregunta con 'va'
            "como va mi cartera en general esta semana",  # largo, >5 palabras
            "sí, pero a 64000",            # dígitos = enmienda
            "dale pero cambiá el precio a 100",
            "ok?",                         # pregunta
            "sí o no?",
            "",
            "   ",
            "y cuánto sería en dólares?",  # pregunta sin dígitos
            "sí no sé",                    # señales mezcladas
        ):
            self.assertEqual(main._confirm_word(msg), "", repr(msg))

    def test_mixed_signals_ambiguous(self):
        self.assertEqual(main._confirm_word("sí... no, esperá"), "")
        self.assertEqual(main._confirm_word("no, dale"), "")


class TestToolRegistration(unittest.TestCase):
    def test_registered_all_tiers(self):
        names = {t["name"] for t in main._AI_TOOLS}
        self.assertIn("register_trade", names)
        self.assertIn("undo_last_trade", names)
        free = {t["name"] for t in main._AI_TOOLS_FREE}
        self.assertTrue({"register_trade", "undo_last_trade", "get_current_prices"} <= free)


# ── E2E HONESTO del endpoint real ────────────────────────────────────────────
class _TB:
    type = "text"
    def __init__(self, t): self.text = t
    def model_dump(self): return {"type": "text", "text": self.text}


class _UB:
    type = "tool_use"
    def __init__(self, name, inp, bid="tu1"):
        self.name, self.input, self.id = name, inp, bid
    def model_dump(self):
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


class _Resp:
    def __init__(self, content, stop="end_turn"):
        self.content, self.stop_reason, self.usage = content, stop, None


class TestE2EHonest(_Base):
    """El fake model construye sus tool_use SOLO desde messages (el contexto que
    el server le manda) — NO puede leer main._TRADE_DRAFT. Si el flujo funciona,
    es por la inyección del draft en el contexto, no por trampa."""

    def setUp(self):
        super().setUp()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _chat(self, text):
        return self.client.post(
            "/api/ai/chat",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messages": [{"role": "user", "content": text}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [],
                                "monthly": [], "brokers": []}, "stream": False})

    def _count(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(chat_count),0) FROM ai_usage_daily WHERE user_id=?",
            (self.uid,)).fetchone()
        return r[0]

    def test_free_two_turn_registration_one_quota(self):
        def fake_create(**kw):
            # Reconstruye el estado SOLO desde los messages (lo que ve un modelo real)
            msgs = kw.get("messages", [])
            blob = str(msgs)
            last_user = ""
            for m in reversed(msgs):
                c = m.get("content")
                if m.get("role") == "user":
                    last_user = c if isinstance(c, str) else str(c)
                    break
            pending = "REGISTRO PENDIENTE DE CONFIRMAR" in blob
            confirming_word = any(w in last_user.lower() for w in ("sí", "si", "dale", "confirm"))
            if pending and confirming_word:
                return _Resp([_UB("register_trade", {"confirm_pending": True})], stop="tool_use")
            if "compré" in last_user.lower() or "compre" in last_user.lower():
                return _Resp([_UB("register_trade", {
                    "action": "buy", "asset": "BTC", "broker": "Binance",
                    "amount": 2000, "price": 65000})], stop="tool_use")
            return _Resp([_TB("¿Confirmás? (esto solo lo anota en Rendi)")])

        mc = MagicMock()
        mc.messages.create.side_effect = fake_create
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            r1 = self._chat("compré 2000 usd de btc a 65000")
            self.assertEqual(r1.status_code, 200, r1.text)
            self.assertEqual(self._count(), 1)               # turno 1 cobra
            self.assertIn(self.uid, main._TRADE_DRAFT)
            self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")
            r2 = self._chat("sí, confirmá")
            self.assertEqual(r2.status_code, 200, r2.text)
        # registrado por el camino real
        row = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["invested"], 2000.0, places=2)
        self.assertEqual(self._cash(), 3000.0)
        self.assertEqual(self._count(), 1)                    # 1 registro = 1 uso

    def test_free_non_trade_still_403(self):
        with patch.object(main, "_get_anthropic_client", return_value=MagicMock()):
            r = self._chat("dame un análisis profundo de mi cartera")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._count(), 0)


# ── Ronda nocturna: la red de seguridad NO escribe sin un sí del usuario ──────
class TestSafetyNetRequiresYes(_Base):
    """Review nocturno B1 (CRITICAL): una re-llamada del modelo sobre un
    pendiente solo ejecuta con señal-sí del USUARIO (confirm_signal='yes') y
    con action+asset presentes. Preguntas / input vacío / campos alucinados
    → re-mostrar el resumen, JAMÁS escribir."""

    FIELDS = {"action": "buy", "asset": "BTC", "broker": "Binance",
              "quantity": 0.03, "price": 65000}

    def _arm(self):
        r = _h(dict(self.FIELDS), self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)

    def test_recall_without_yes_does_not_write(self):
        self._arm()
        # turno-pregunta: el modelo re-manda los MISMOS campos (señal ambigua)
        r = _h(dict(self.FIELDS), self.uid, request_id="B", confirm_signal="")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        self.assertIn("no", r["_note"].lower())
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone())
        # el draft sigue vivo (el usuario todavía puede confirmar)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")

    def test_empty_recall_never_confirms_even_with_yes(self):
        self._arm()
        r = _h({}, self.uid, request_id="B", confirm_signal="yes")
        self.assertNotEqual(r.get("status"), "registered", r)
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone())

    def test_recall_with_yes_executes_pending(self):
        self._arm()
        r = _h(dict(self.FIELDS), self.uid, request_id="B", confirm_signal="yes")
        self.assertEqual(r.get("status"), "registered", r)

    def test_unresolvable_asset_is_amendment_not_confirmation(self):
        self._arm()
        bad = dict(self.FIELDS); bad["asset"] = "CHORIPAN"
        r = _h(bad, self.uid, request_id="B", confirm_signal="yes")
        self.assertNotEqual(r.get("status"), "registered", r)
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone())

    def test_hallucinated_date_change_rearms_not_writes(self):
        self._arm()
        amended = dict(self.FIELDS); amended["date"] = "2020-01-02"
        r = _h(amended, self.uid, request_id="B", confirm_signal="yes")
        # fecha distinta = contradicción → re-arma (no escribe el pendiente)
        self.assertNotEqual(r.get("status"), "registered", r)


class TestAmendMergeFromPending(_Base):
    """Falla real de la prueba e2e: 'no, mejor a 5500' perdía el registro
    entero. Ahora una re-llamada PARCIAL sobre un confirming hereda el resto
    del payload y re-deriva el monto."""

    def test_partial_price_amend_keeps_rest(self):
        r = _h({"action": "buy", "asset": "GGAL", "broker": "Balanz",
                "quantity": 10, "price": 6000}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        # el modelo re-llama SOLO con el precio corregido
        r2 = _h({"price": 5500}, self.uid, request_id="B", confirm_signal="")
        self.assertEqual(r2.get("status"), "needs_confirmation", r2)
        p = main._TRADE_DRAFT[self.uid]["payload"]
        self.assertEqual(p["price"], 5500)
        self.assertEqual(p["quantity"], 10)
        self.assertEqual(p["asset"], "GGAL")
        self.assertAlmostEqual(p["amount"], 55000.0, places=2)   # re-derivado
        # y el sí siguiente ejecuta el ENMENDADO
        r3 = _h({"confirm_pending": True}, self.uid, request_id="C",
                confirm_signal="yes")
        self.assertEqual(r3.get("status"), "registered", r3)
        row = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND asset='GGAL' AND is_cash=0",
            (self.uid,)).fetchone()
        self.assertAlmostEqual(row["invested"], 55000.0, places=2)


class TestConfirmPendingRequiresYes(_Base):
    def test_confirm_pending_without_signal_reshows(self):
        r = _h({"action": "buy", "asset": "BTC", "broker": "Binance",
                "quantity": 0.03, "price": 65000}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation")
        r2 = _h({"confirm_pending": True}, self.uid, request_id="B",
                confirm_signal="")
        self.assertEqual(r2.get("status"), "needs_confirmation", r2)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")


class TestGatheringTtlNotRefreshed(_Base):
    """Review nocturno B3: el re-plant de needs_info preserva el ts — un draft
    basura de un falso positivo muere a los 15 min del ARRANQUE aunque el
    usuario siga chateando."""

    def test_replant_preserves_ts(self):
        _h({"action": "buy", "asset": "BTC"}, self.uid, request_id="A")
        ts0 = main._TRADE_DRAFT[self.uid]["ts"]
        main._TRADE_DRAFT[self.uid]["ts"] = ts0 - 100   # envejecer
        _h({"broker": "Binance"}, self.uid, request_id="B")
        self.assertAlmostEqual(main._TRADE_DRAFT[self.uid]["ts"], ts0 - 100, places=1)


class TestTradeErrorHuman(unittest.TestCase):
    def test_no_pending_and_model_directed_strings(self):
        self.assertIn("pendiente", main._trade_error_human("no_pending"))
        self.assertIn("pendiente", main._trade_error_human(None))
        out = main._trade_error_human(
            "El broker ya no existe (¿lo borraron/renombraron?). Pedile al usuario que rearme el registro.")
        self.assertNotIn("Pedile", out)
        out2 = main._trade_error_human(
            "No se pudo registrar por un error interno. Que lo cargue desde la app.")
        self.assertNotIn("Que lo cargue", out2)
        self.assertIn("app", out2)


class TestUndoShortCircuitGating(unittest.TestCase):
    """El undo determinístico solo dispara ante pedidos EXPLÍCITOS: verbo
    fuerte + (una sola palabra clítica o mención de la operación), sin
    dígitos, sin pregunta, sin draft abierto."""

    def _fires(self, msg):
        return bool(
            main._UNDO_STRONG_RE.search(msg)
            and not any(c.isdigit() for c in msg)
            and "?" not in msg and "¿" not in msg
            and len(msg.split()) <= 6
            and (len(msg.split()) == 1 or main._UNDO_OBJECT_RE.search(msg)))

    def test_fires_on_explicit(self):
        for m in ("deshacelo", "borrala", "deshacé la última operación",
                  "deshacé eso", "revertí la compra", "borrá lo de recién"):
            self.assertTrue(self._fires(m), m)

    def test_does_not_fire_on_other_things(self):
        for m in ("borrá el broker Binance",        # objeto ≠ operación
                  "me equivoqué",                    # no es verbo fuerte
                  "¿podés deshacer la última operación?",  # pregunta → modelo
                  "deshacé la compra de 10 GGAL de ayer que cargué mal a 6000",  # larga+dígitos
                  "hola"):
            self.assertFalse(self._fires(m), m)


class TestMarketPriceServerSide(_Base):
    """Bug real de la demo de Nico (2026-07-13): el precio de mercado viajaba
    POR el LLM — AMZN llegó ÷1000 (separador es-AR: 2675→'2.675') e INTC llegó
    en USD del ticker US (105 vs .BA 34.380) → cantidades infladas 327-1000×.
    Con price_source='market_today' el server cotiza el activo él solo e
    IGNORA el price del modelo."""

    def test_market_today_without_price_uses_server(self):
        # el path limpio (lo que instruye el prompt): market_today SIN price
        with patch.object(main, "_trade_market_price", return_value=2675.0) as mp:
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "amount": 500000,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        p = main._TRADE_DRAFT[self.uid]["payload"]
        self.assertEqual(p["price"], 2675.0)
        self.assertAlmostEqual(p["quantity"], 500000 / 2675.0, places=6)
        mp.assert_called_with("AMZN", "CEDEAR", "ARS", self.uid)

    def test_market_today_with_echoed_price_uses_server(self):
        # el modelo re-manda el precio del feed casi igual (echo ≤10%) → ref
        with patch.object(main, "_trade_market_price", return_value=2675.0):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "amount": 500000, "price": 2700,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["price"], 2675.0)

    def test_market_today_with_mangled_price_reasks(self):
        # el bug real: 2675 relayado como '2.675' (÷1000) — ya no se registra
        # NI se pisa en silencio: cae al cinturón y repregunta
        with patch.object(main, "_trade_market_price", return_value=2675.0):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "amount": 500000, "price": 2.675,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertIn("error", r)
        self.assertIn("lejísimos", r["error"])

    def test_mislabeled_dictated_price_not_overridden(self):
        # 'a 105 cada uno' etiquetado market_today: NO pisar el dictado con el
        # de mercado — 105 vs 32860 (313×) → el cinturón repregunta (falla
        # real del e2e: antes registraba 0,32 CEDEARs al precio de mercado)
        with patch.object(main, "_trade_market_price", return_value=34380.0):
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 100, "price": 105,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertIn("error", r)
        self.assertIn("lejísimos", r["error"])

    def test_mislabeled_dictated_plausible_price_respected(self):
        # dictado 30.000 con mercado 32.860 (9,5% off... >10%? no: 1.095) —
        # dentro del eco 10% usa ref; a 28.000 (17% off, <4×) respeta el dictado
        with patch.object(main, "_trade_market_price", return_value=32860.0):
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 6, "price": 28000,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["price"], 28000)

    def test_market_today_feed_down_with_price_fails_open(self):
        # feed caído + precio declarado → dictado (la palabra del usuario manda)
        with patch.object(main, "_trade_market_price", return_value=None):
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 6, "price": 30000,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["price"], 30000)

    def test_feed_down_missing_text_does_not_bait_market_today(self):
        # el needs_info de feed-caído NO debe re-ofrecer market_today (loop)
        with patch.object(main, "_trade_market_price", return_value=None):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "amount": 500000,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_info", r)
        price_items = [m for m in r["missing"] if m.startswith("price")]
        self.assertTrue(price_items and all("market_today" not in m for m in price_items),
                        price_items)

    def test_replant_does_not_persist_server_price(self):
        # market_today con quantity faltante: el draft NO guarda el precio
        # cotizado (el próximo turno re-cotiza fresco, server-vs-server nunca)
        with patch.object(main, "_trade_market_price", return_value=2675.0):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "price_source": "market_today"},
                   self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_info", r)
        self.assertNotIn("price", main._TRADE_DRAFT[self.uid]["fields"])
        self.assertEqual(main._TRADE_DRAFT[self.uid]["fields"].get("price_source"),
                         "market_today")

    def test_amend_pending_to_market_price(self):
        # 'mejor usá el precio de mercado' sobre un pendiente DICTADO: la
        # re-llamada {price_source: market_today} sin price re-arma al precio
        # real (review: antes era IMPOSIBLE enmendar a mercado — loopeaba el
        # summary viejo)
        with patch.object(main, "_trade_market_price", return_value=32860.0):
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 6, "price": 30000},
                   self.uid, request_id="A")
            self.assertEqual(r.get("status"), "needs_confirmation", r)
            r2 = _h({"price_source": "market_today"}, self.uid,
                    request_id="B", confirm_signal="")
        self.assertEqual(r2.get("status"), "needs_confirmation", r2)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["price"], 32860.0)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["quantity"], 6)

    def test_amend_price_with_hallucinated_market_today_not_swallowed(self):
        # 'en realidad la pagué a 2000' + market_today alucinado en un turno
        # NO-sí: cuenta como enmienda (review: la exención vieja la tragaba y
        # el sí posterior registraba el precio VIEJO)
        with patch.object(main, "_trade_market_price", return_value=2675.0):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 10,
                    "price_source": "market_today"}, self.uid, request_id="A")
            self.assertEqual(r.get("status"), "needs_confirmation", r)
            self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["price"], 2675.0)
            r2 = _h({"price": 2000, "price_source": "market_today"}, self.uid,
                    request_id="B", confirm_signal="")
        self.assertEqual(r2.get("status"), "needs_confirmation", r2)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["payload"]["price"], 2000)

    def test_confirm_recall_with_market_today_echo_still_executes(self):
        # el turno del SÍ con la re-llamada típica de Haiku (campos + su
        # número + market_today) sigue ejecutando el payload pendiente
        with patch.object(main, "_trade_market_price", return_value=2675.0):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 10,
                    "price_source": "market_today"}, self.uid, request_id="A")
            self.assertEqual(r.get("status"), "needs_confirmation", r)
            r2 = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                     "broker": "Balanz", "quantity": 10, "price": 2.675,
                     "price_source": "market_today"}, self.uid,
                    request_id="B", confirm_signal="yes")
        self.assertEqual(r2.get("status"), "registered", r2)

    def test_market_today_feed_down_asks_user(self):
        with patch.object(main, "_trade_market_price", return_value=None):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "amount": 500000,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_info", r)
        self.assertTrue(any("price" in m for m in r["missing"]), r)
        # el price_source viciado no queda pegado en el draft
        self.assertNotIn("price_source", main._TRADE_DRAFT[self.uid]["fields"])

    def test_dictated_price_far_from_market_rejected(self):
        # INTC dictado/mangleado a 105 con mercado .BA en 34.380 → 327× → error
        with patch.object(main, "_trade_market_price", return_value=34380.0):
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "CEDEAR",
                    "broker": "Balanz", "amount": 200000, "price": 105},
                   self.uid, request_id="A")
        self.assertIn("error", r)
        self.assertIn("lejísimos", r["error"])
        self.assertNotIn(self.uid, main._TRADE_DRAFT)

    def test_dictated_price_near_market_ok(self):
        with patch.object(main, "_trade_market_price", return_value=6000.0):
            r = _h({"action": "buy", "asset": "GGAL", "asset_type": "AR_STOCK",
                    "broker": "Balanz", "quantity": 10, "price": 5500},
                   self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)

    def test_retroactive_price_not_checked(self):
        # precio viejo legítimamente lejos del mercado de hoy → pasa sin belt
        with patch.object(main, "_trade_market_price", return_value=34380.0) as mp:
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 100, "price": 105,
                    "date": "2020-03-01"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        mp.assert_not_called()

    def test_dictated_today_feed_down_fail_open(self):
        with patch.object(main, "_trade_market_price", return_value=None):
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "CEDEAR",
                    "broker": "Balanz", "quantity": 100, "price": 105},
                   self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)


class TestBrokerCurrencyDisambiguation(_Base):
    """Prueba real de Nico: el modelo etiquetó INTC como STOCK (acción US) en
    Balanz (pesos) → el precio de mercado moría en un loop de 'preguntale el
    precio exacto'. Una acción US no puede vivir en un broker ARS: si el
    ticker tiene CEDEAR, el server corrige el tipo él solo."""

    def test_stock_in_ars_broker_corrected_to_cedear(self):
        with patch.object(main, "_trade_market_price", return_value=32860.0) as mp:
            r = _h({"action": "buy", "asset": "INTC", "asset_type": "STOCK",
                    "broker": "Balanz", "amount": 200000, "currency": "ARS",
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        p = main._TRADE_DRAFT[self.uid]["payload"]
        self.assertEqual(p["kind"], "CEDEAR")
        self.assertEqual(p["price"], 32860.0)
        mp.assert_called_once_with("INTC", "CEDEAR", "ARS", self.uid)

    def test_pure_us_stock_in_ars_broker_rejected(self):
        with patch("ai.trade_tickers.resolve_asset",
                   return_value=("FAKEUS", {"STOCK"})):
            r = _h({"action": "buy", "asset": "FAKEUS", "asset_type": "STOCK",
                    "broker": "Balanz", "quantity": 10, "price": 100},
                   self.uid, request_id="A")
        self.assertIn("error", r)
        self.assertIn("pesos", r["error"])
        self.assertNotIn(self.uid, main._TRADE_DRAFT)


class TestTradeMarketPriceSymbolResolution(unittest.TestCase):
    """El helper resuelve el símbolo canónico y solo cotiza cuando la moneda
    de la operación coincide con la del feed (CEDEAR/.BA=ARS; US/cripto=USD)."""

    def test_cedear_ars_uses_ba(self):
        with patch.object(main, "get_prices", return_value={"AMZN.BA": 2675.0}) as gp:
            self.assertEqual(main._trade_market_price("AMZN", "CEDEAR", "ARS", 1), 2675.0)
            gp.assert_called_once_with("AMZN.BA", 1)

    def test_cedear_usd_returns_none(self):
        # comparar un precio USD contra el feed ARS sería un falso positivo
        self.assertIsNone(main._trade_market_price("AMZN", "CEDEAR", "USD", 1))

    def test_us_stock_ars_returns_none(self):
        self.assertIsNone(main._trade_market_price("NVDA", "STOCK", "ARS", 1))

    def test_crypto_uses_usd_suffix(self):
        # el ticker PELADO colisiona con equities homónimos (DASH→DoorDash,
        # FET→Forum Energy 318×) — la cripto SIEMPRE se cotiza '<X>-USD'
        with patch.object(main, "get_prices", return_value={"BTC-USD": 65000.0}) as gp:
            self.assertEqual(main._trade_market_price("BTC", "CRYPTO", "USD", 1), 65000.0)
            gp.assert_called_once_with("BTC-USD", 1)
        with patch.object(main, "get_prices", return_value={"DASH-USD": 33.31}) as gp:
            self.assertEqual(main._trade_market_price("DASH", "CRYPTO", "USD", 1), 33.31)
            gp.assert_called_once_with("DASH-USD", 1)

    def test_feed_error_returns_none(self):
        with patch.object(main, "get_prices", side_effect=RuntimeError("boom")):
            self.assertIsNone(main._trade_market_price("AMZN", "CEDEAR", "ARS", 1))

    def test_stale_last_known_rejected(self):
        # get_prices puede servir un last-known viejo: para ESCRIBIR un lote
        # "de hoy" no alcanza — >48h de la última persistencia → None
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM asset_last_price WHERE symbol='AMZN.BA'")
            conn.execute(
                "INSERT INTO asset_last_price (symbol, price, updated_at) VALUES (?,?,?)",
                ("AMZN.BA", 2675.0, "2026-06-01T10:00:00"))
            conn.commit()
            with patch.object(main, "get_prices", return_value={"AMZN.BA": 2675.0}):
                self.assertIsNone(main._trade_market_price("AMZN", "CEDEAR", "ARS", 1))
            conn.execute("DELETE FROM asset_last_price WHERE symbol='AMZN.BA'")
            conn.commit()
        finally:
            conn.close()

    def test_fresh_last_known_accepted(self):
        from datetime import datetime
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM asset_last_price WHERE symbol='AMZN.BA'")
            conn.execute(
                "INSERT INTO asset_last_price (symbol, price, updated_at) VALUES (?,?,?)",
                ("AMZN.BA", 2675.0, datetime.utcnow().isoformat()))
            conn.commit()
            with patch.object(main, "get_prices", return_value={"AMZN.BA": 2675.0}):
                self.assertEqual(main._trade_market_price("AMZN", "CEDEAR", "ARS", 1), 2675.0)
            conn.execute("DELETE FROM asset_last_price WHERE symbol='AMZN.BA'")
            conn.commit()
        finally:
            conn.close()


class TestPendingSummaryEpilogue(_Base):
    """Garantía server-side: si el turno termina con un confirming y el texto
    del modelo no muestra el precio del pendiente, se anexa el resumen (e2e
    real: Haiku dijo 'cambio el precio a $15.000' pero el pendiente había
    quedado a precio de mercado → el sí ejecutaba algo nunca visto)."""

    def _arm(self, price=2697.5):
        with patch.object(main, "_trade_market_price", return_value=price):
            r = _h({"action": "buy", "asset": "AMZN", "asset_type": "CEDEAR",
                    "broker": "Balanz", "amount": 500000,
                    "price_source": "market_today"}, self.uid, request_id="A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)

    def test_appends_when_model_hides_the_price(self):
        self._arm()
        ep = main._pending_summary_epilogue(self.uid, "Entendido — cambio el precio a $ 15.000.")
        self.assertIn("Registro pendiente", ep)
        self.assertIn("¿Confirmás?", ep)

    def test_silent_when_price_shown(self):
        self._arm()
        self.assertEqual(main._pending_summary_epilogue(
            self.uid, "COMPRA 185,36 AMZN @ $ 2.697,50 ¿Confirmás?"), "")

    def test_silent_without_confirming_draft(self):
        self.assertEqual(main._pending_summary_epilogue(self.uid, "hola"), "")
        main._TRADE_DRAFT[self.uid] = {"status": "gathering", "fields": {},
                                        "ts": __import__("time").time()}
        self.assertEqual(main._pending_summary_epilogue(self.uid, "hola"), "")


class TestSanitizeAssistantBlocks(unittest.TestCase):
    """El SDK agrega campos (parsed_output) que la API rechaza con 400 si se
    re-mandan en el historial del loop. La proyección tiene que dejar SOLO los
    campos válidos y conservar los ids de tool_use (coherencia con su
    tool_result)."""

    def test_projects_valid_fields_only(self):
        class _TBx:
            type = "text"
            def model_dump(self):
                return {"type": "text", "text": "hola", "parsed_output": {"x": 1}}

        class _UBx:
            type = "tool_use"
            def model_dump(self):
                return {"type": "tool_use", "id": "tu9", "name": "register_trade",
                        "input": {"a": 1}, "parsed_output": None, "caching": "x"}

        out = main._sanitize_assistant_blocks([_TBx(), _UBx()])
        self.assertEqual(out[0], {"type": "text", "text": "hola"})
        self.assertEqual(out[1]["id"], "tu9")
        self.assertEqual(out[1]["name"], "register_trade")
        self.assertEqual(out[1]["input"], {"a": 1})
        self.assertNotIn("parsed_output", out[1])
        self.assertNotIn("caching", out[1])


class TestConfirmWordNight(unittest.TestCase):
    """Casos del review nocturno B2: condicionales y enmiendas SIN dígitos."""

    def test_conditional_and_amendment_phrases_ambiguous(self):
        for m in ("dale, pero en dólares", "sí, en dólares", "si querés",
                  "si es en pesos dale", "sí solo si es hoy",
                  "quedó listo lo anterior", "no sé", "todavía no",
                  "sí pero mañana", "dale cuando puedas"):
            self.assertEqual(main._confirm_word(m), "", m)

    def test_clear_still_clear(self):
        self.assertEqual(main._confirm_word("de una"), "yes")
        self.assertEqual(main._confirm_word("sí, dale nomás"), "yes")
        self.assertEqual(main._confirm_word("mejor no"), "no")
        self.assertEqual(main._confirm_word("cancelalo"), "no")


class TestE2EQuestionOnPendingDoesNotWrite(_Base):
    """E2E del CRITICAL del review: draft confirmando + pregunta del usuario
    ('¿y cuánto sería en pesos?') + modelo que re-llama register_trade con los
    campos → NO escribe, re-muestra el resumen."""

    def setUp(self):
        super().setUp()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def _chat(self, text):
        return self.client.post(
            "/api/ai/chat",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messages": [{"role": "user", "content": text}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [],
                                "monthly": [], "brokers": []}, "stream": False})

    def test_question_recall_no_write(self):
        def fake_create(**kw):
            msgs = kw.get("messages", [])
            last_user = ""
            for m in reversed(msgs):
                if m.get("role") == "user":
                    c = m.get("content")
                    last_user = c if isinstance(c, str) else str(c)
                    break
            if "compré" in last_user.lower():
                return _Resp([_UB("register_trade", {
                    "action": "buy", "asset": "BTC", "broker": "Binance",
                    "amount": 2000, "price": 65000})], stop="tool_use")
            if "pesos" in last_user.lower():
                # Haiku-style: ante la pregunta re-llama la tool con los campos
                return _Resp([_UB("register_trade", {
                    "action": "buy", "asset": "BTC", "broker": "Binance",
                    "amount": 2000, "price": 65000})], stop="tool_use")
            return _Resp([_TB("resumen: COMPRA 0.03 BTC. ¿Confirmás?")])

        mc = MagicMock()
        mc.messages.create.side_effect = fake_create
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            r1 = self._chat("compré 2000 usd de btc a 65000")
            self.assertEqual(r1.status_code, 200, r1.text)
            self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")
            r2 = self._chat("¿y cuánto sería en pesos?")
            self.assertEqual(r2.status_code, 200, r2.text)
        # NO se escribió nada; el draft sigue esperando el sí
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone())
        self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")

    def test_explicit_undo_message_is_deterministic(self):
        """El undo por chat no depende del modelo: pedido explícito → se
        ejecuta server-side (el fake model EXPLOTARÍA si lo llamaran)."""
        def boom(**kw):
            raise AssertionError("el undo explícito no debe llamar al LLM")
        mc = MagicMock()
        mc.messages.create.side_effect = boom
        # armar y confirmar una compra por el camino del handler
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "quantity": 0.02, "price": 65000}, self.uid, request_id="A")
        r = _h({"confirm_pending": True}, self.uid, request_id="B",
               confirm_signal="yes")
        self.assertEqual(r.get("status"), "registered", r)
        cash_after_buy = self._cash()
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            r2 = self._chat("deshacé la última operación")
            self.assertEqual(r2.status_code, 200, r2.text)
            self.assertIn("Deshecho", r2.json()["reply"])
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='BTC' AND is_cash=0",
            (self.uid,)).fetchone())
        self.assertAlmostEqual(self._cash(), cash_after_buy + 1300.0, places=2)


if __name__ == "__main__":
    unittest.main()
