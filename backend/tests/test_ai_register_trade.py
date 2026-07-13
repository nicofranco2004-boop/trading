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


def _h(input_data, uid, request_id="req1"):
    return main._register_trade_handler(input_data, uid, request_id=request_id)


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
        r = _h({"confirm_pending": True}, self.uid, request_id="A")  # MISMO request
        self.assertIn("error", r)
        self.assertIn("NO confirmes", r["error"])
        # el draft sigue vivo (no se perdió)
        self.assertIn(self.uid, main._TRADE_DRAFT)

    def test_confirm_next_request_executes(self):
        _h({"action": "buy", "asset": "BTC", "broker": "Binance",
            "amount": 2000, "price": 65000}, self.uid, request_id="A")
        r = _h({"confirm_pending": True}, self.uid, request_id="B")  # request nuevo
        self.assertEqual(r["status"], "registered")
        self.assertEqual(self._cash(), 3000.0)

    def test_confirm_without_pending_rejected(self):
        r = _h({"confirm_pending": True}, self.uid, request_id="Z")
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
        r1 = _h({"confirm_pending": True}, self.uid, request_id="B")
        r2 = _h({"confirm_pending": True}, self.uid, request_id="C")
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
            r = _h({"confirm_pending": True}, self.uid, request_id="B")
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
        return _h({"confirm_pending": True}, self.uid, request_id="B")

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


if __name__ == "__main__":
    unittest.main()
