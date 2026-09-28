"""El chat con un modelo que NO acepta que lo obliguen a usar una herramienta.

Sonnet 5.5 (y los modelos nuevos de Anthropic) devuelven 400 si el pedido trae
tool_choice={"type": "tool"} o {"type": "any"}. El turno de registro ("compré
2000 usd de btc a 65000") lo mandaba así para garantizar que se armara el
borrador. Estos tests cubren el reemplazo, por los DOS caminos del endpoint
(JSON y streaming), a través del endpoint real — no de los helpers sueltos:

  1. Ningún llamado al modelo obliga a usar una herramienta.
  2. El turno de registro se lo PIDE (nota al final del mensaje del usuario), y
     una pregunta común no lleva esa nota.
  3. Si contesta sin llamar la herramienta, se le pide UNA vez más — y lo que
     había escrito se borra de la pantalla en vez de quedar como respuesta.
  4. Si el modelo se niega (stop_reason='refusal'), el usuario ve un mensaje y
     la consulta se le devuelve.
  5. El modelo del chat tiene su precio en la tabla (si falta, se cobra al más
     caro y el costo guardado sale inflado sin que nada avise).
"""
import copy
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402
from ai import llm  # noqa: E402


class _Txt:
    type = "text"
    def __init__(self, t): self.text = t
    def model_dump(self): return {"type": "text", "text": self.text}


class _Tool:
    type = "tool_use"
    def __init__(self, name, inp, bid="tu1"):
        self.name, self.input, self.id = name, inp, bid
    def model_dump(self):
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


class _Resp:
    def __init__(self, content, stop="end_turn", stop_details=None, usage=None):
        self.content, self.stop_reason, self.usage = content, stop, usage
        self.stop_details = stop_details


class _Usage:
    def __init__(self, inp=0, out=0, cw=0, cr=0):
        self.input_tokens, self.output_tokens = inp, out
        self.cache_creation_input_tokens, self.cache_read_input_tokens = cw, cr


class _Detalle:
    def __init__(self, category): self.category, self.explanation = category, "x"


COMPRA = {"action": "buy", "asset": "BTC", "broker": "Binance",
          "amount": 2000, "price": 65000}


def _ultimo_user(msgs) -> str:
    for m in reversed(msgs):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
    return ""


class _Base(unittest.TestCase):
    TIER = "pro"

    def setUp(self):
        main._TRADE_DRAFT.clear()
        main._LAST_CHAT_TRADE.clear()
        main._CHAT_VAL_CACHE.clear()
        _mp = patch.object(main, "_trade_market_price", return_value=None)
        _mp.start()
        self.addCleanup(_mp.stop)
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("operations", "monthly_entries", "positions", "brokers", "users", "ai_usage_daily"):
            self.conn.execute(f"DELETE FROM {t}")
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,?)",
            (f"s55-{id(self)}@rendi.test", "x", self.TIER))
        self.uid = cur.lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Binance", "USDT"))
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, currency) "
            "VALUES (?,?,?,1,5000,'USD')", (self.uid, "Binance", "USD"))
        self.conn.commit()
        self.token = main.create_token(self.uid)
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        # Todos los kwargs con que se llamó al modelo, en orden. Los mensajes van
        # COPIADOS: el endpoint sigue agregándole a la misma lista después.
        self.llamados = []

    def tearDown(self):
        for t in ("operations", "monthly_entries", "positions", "brokers", "users", "ai_usage_daily"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
        main._TRADE_DRAFT.clear()

    def _count(self):
        return self.conn.execute(
            "SELECT COALESCE(SUM(chat_count),0) FROM ai_usage_daily WHERE user_id=?",
            (self.uid,)).fetchone()[0]

    def _post(self, texto, stream=False):
        return self.client.post(
            "/api/ai/chat",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messages": [{"role": "user", "content": texto}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [],
                               "monthly": [], "brokers": []},
                  "stream": stream})

    def _json(self, texto, respuestas):
        """Turno por el camino JSON; `respuestas(kwargs, n)` arma la n-ésima."""
        def fake_create(**kw):
            self.llamados.append(dict(kw, messages=copy.deepcopy(kw["messages"])))
            return respuestas(kw, len(self.llamados))
        mc = MagicMock()
        mc.messages.create.side_effect = fake_create
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            return self._post(texto)

    def _stream(self, texto, respuestas):
        """Turno por el camino streaming; `respuestas(kwargs, n)` devuelve
        (pedazos_de_texto, _Resp final). Devuelve los frames del navegador."""
        test = self

        class _FakeStream:
            def __init__(s, kw):
                test.llamados.append(dict(kw, messages=copy.deepcopy(kw["messages"])))
                s.pedazos, s.final = respuestas(kw, len(test.llamados))
                s.text_stream = s.pedazos
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def get_final_message(s): return s.final

        mc = MagicMock()
        mc.messages.stream.side_effect = lambda **kw: _FakeStream(kw)
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            r = self._post(texto, stream=True)
        self.assertEqual(r.status_code, 200, r.text)
        frames = []
        for linea in r.text.splitlines():
            if linea.startswith("data:"):
                try:
                    frames.append(json.loads(linea[5:]))
                except ValueError:
                    pass
        return frames

    def assertNadieObligo(self):
        self.assertTrue(self.llamados, "el modelo no se llamó nunca")
        for kw in self.llamados:
            tc = kw.get("tool_choice")
            self.assertFalse(tc and tc.get("type") in ("tool", "any"),
                             f"un llamado obligó a usar una herramienta: {tc}")


class TestRegistroSinObligar(_Base):

    def test_registro_json_pide_la_herramienta_y_arma_el_borrador(self):
        def resp(kw, n):
            if n == 1:
                return _Resp([_Tool("register_trade", COMPRA)], stop="tool_use")
            return _Resp([_Txt("COMPRA 0.03 BTC. ¿Confirmás?")])
        r = self._json("compré 2000 usd de btc a 65000", resp)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNadieObligo()
        self.assertIn("llamá a register_trade", _ultimo_user(self.llamados[0]["messages"]))
        self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")

    def test_pregunta_comun_no_lleva_el_pedido(self):
        r = self._json("¿cómo viene mi cartera?", lambda kw, n: _Resp([_Txt("Bien.")]))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNadieObligo()
        self.assertNotIn("Nota de Rendi", _ultimo_user(self.llamados[0]["messages"]))

    def test_si_contesta_sin_llamar_se_le_pide_otra_vez(self):
        def resp(kw, n):
            if n == 1:
                return _Resp([_Txt("Para registrarlo necesito el broker.")])
            if n == 2:
                self.assertIn("Todavía no llamaste a register_trade",
                              _ultimo_user(kw["messages"]))
                return _Resp([_Tool("register_trade", COMPRA)], stop="tool_use")
            return _Resp([_Txt("COMPRA 0.03 BTC. ¿Confirmás?")])
        r = self._json("compré 2000 usd de btc a 65000", resp)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.llamados), 3)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")
        # La respuesta es la del final, no el texto que se descartó.
        self.assertIn("Confirmás", r.json()["reply"])
        self.assertNotIn("necesito el broker", r.json()["reply"])

    def test_el_segundo_pedido_es_uno_solo(self):
        """Si igual no la llama, se queda con lo que contestó: nada de un
        loop pidiéndole lo mismo hasta agotar las vueltas."""
        r = self._json("compré 2000 usd de btc a 65000",
                       lambda kw, n: _Resp([_Txt(f"respuesta {n}")]))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.llamados), 2)
        self.assertEqual(r.json()["reply"], "respuesta 2")

    def test_stream_borra_lo_escrito_y_no_adelanta_su_voz(self):
        voz_descartada = ('Para registrarlo necesito el broker.---RENDI---'
                          '{"voz":"Necesito el broker","verdict":"x"}')

        def resp(kw, n):
            if n == 1:
                return [voz_descartada], _Resp([_Txt(voz_descartada)])
            if n == 2:
                return [], _Resp([_Tool("register_trade", COMPRA)], stop="tool_use")
            return ["COMPRA 0.03 BTC. ¿Confirmás?"], _Resp([_Txt("COMPRA 0.03 BTC. ¿Confirmás?")])
        frames = self._stream("compré 2000 usd de btc a 65000", resp)
        self.assertNadieObligo()
        tipos = [f.get("t") for f in frames]
        # Escribió → se borró (reset) → siguió con la herramienta → respuesta.
        self.assertIn("reset", tipos)
        self.assertLess(tipos.index("reset"), len(tipos) - 1)
        self.assertEqual(tipos[-1], "done")
        # La voz del texto descartado NO salió adelantada.
        self.assertFalse(any(f.get("t") == "voz" and "broker" in f["voz"]["text"]
                             for f in frames), frames)
        self.assertEqual(main._TRADE_DRAFT[self.uid]["status"], "confirming")


class TestNegativa(_Base):

    def test_json_muestra_el_mensaje_y_devuelve_la_consulta(self):
        r = self._json("¿cómo viene mi cartera?",
                       lambda kw, n: _Resp([], stop="refusal",
                                           stop_details=_Detalle("general_harms")))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["reply"], main._TEXTO_NEGATIVA)
        self.assertEqual(self._count(), 0)

    def test_stream_borra_lo_parcial_y_devuelve_la_consulta(self):
        frames = self._stream(
            "¿cómo viene mi cartera?",
            lambda kw, n: (["Tu cartera "], _Resp([_Txt("Tu cartera ")], stop="refusal",
                                                  stop_details=_Detalle("general_harms"))))
        tipos = [f.get("t") for f in frames]
        self.assertEqual(tipos[-3:], ["reset", "delta", "done"])
        self.assertEqual(frames[-2]["d"], main._TEXTO_NEGATIVA)
        self.assertEqual(self._count(), 0)

    def test_negativa_despues_de_una_herramienta_tambien(self):
        """La síntesis final (después de usar herramientas) también puede
        negarse: el camino de respaldo tiene el mismo cierre."""
        def resp(kw, n):
            if kw.get("tool_choice", {}).get("type") == "none":
                return _Resp([], stop="refusal", stop_details=_Detalle("general_harms"))
            return _Resp([_Tool("get_fx_rates", {}, bid=f"tu{n}")], stop="tool_use")
        with patch.object(main, "_ai_chat_exec_tools",
                          side_effect=lambda content, uid, tier, tc, mx, **k: (
                              [{"type": "tool_result", "tool_use_id": content[0].id,
                                "content": "{}"}], tc + 1)):
            r = self._json("¿a cuánto está el dólar?", resp)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["reply"], main._TEXTO_NEGATIVA)
        self.assertEqual(self._count(), 0)


def _usd(u):
    p = llm._PRICING_USD_PER_M[llm.MODEL_SONNET]
    return (u.input_tokens * p["input"] + u.cache_creation_input_tokens * p["input"] * 1.25
            + u.cache_read_input_tokens * p["input"] * 0.10
            + u.output_tokens * p["output"]) / 1e6


class TestCostoDelTurnoEntero(_Base):
    """Un turno con herramienta son DOS llamados al modelo. Lo que se guarda en
    ai_usage_daily tiene que ser la suma — antes era sólo el último, y medido
    contra la API real eso dejaba afuera el 26% del gasto."""

    U1 = _Usage(inp=1000, out=500, cr=30000)    # la vuelta que pide la herramienta
    U2 = _Usage(out=1000, cr=31000)             # la respuesta

    def _costo_guardado(self):
        return self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd_cents),0) FROM ai_usage_daily WHERE user_id=?",
            (self.uid,)).fetchone()[0]

    def _tool_falsa(self):
        return patch.object(main, "_ai_chat_exec_tools",
                            side_effect=lambda content, uid, tier, tc, mx, **k: (
                                [{"type": "tool_result", "tool_use_id": content[0].id,
                                  "content": "{}"}], tc + 1))

    def _esperado(self, *us):
        return round(sum(_usd(u) for u in us) * 100)

    def test_json_guarda_la_suma_de_los_dos_llamados(self):
        def resp(kw, n):
            if n == 1:
                return _Resp([_Tool("get_fx_rates", {})], stop="tool_use", usage=self.U1)
            return _Resp([_Txt("El MEP está a 1.550.")], usage=self.U2)
        with self._tool_falsa():
            r = self._json("¿a cuánto está el dólar?", resp)
        self.assertEqual(r.status_code, 200, r.text)
        # Los números están elegidos para que "sólo el último" dé OTRO resultado.
        self.assertNotEqual(self._esperado(self.U1, self.U2), self._esperado(self.U2))
        self.assertEqual(self._costo_guardado(), self._esperado(self.U1, self.U2))

    def test_stream_guarda_la_suma_de_los_dos_llamados(self):
        def resp(kw, n):
            if n == 1:
                return [], _Resp([_Tool("get_fx_rates", {})], stop="tool_use", usage=self.U1)
            return ["El MEP está a 1.550."], _Resp([_Txt("El MEP está a 1.550.")], usage=self.U2)
        with self._tool_falsa():
            frames = self._stream("¿a cuánto está el dólar?", resp)
        self.assertEqual(frames[-1].get("t"), "done", frames)
        self.assertEqual(self._costo_guardado(), self._esperado(self.U1, self.U2))

    def test_negativa_despues_de_la_herramienta_anota_todo_y_devuelve(self):
        def resp(kw, n):
            if n == 1:
                return _Resp([_Tool("get_fx_rates", {})], stop="tool_use", usage=self.U1)
            return _Resp([], stop="refusal", stop_details=_Detalle("general_harms"),
                         usage=self.U2)
        with self._tool_falsa():
            r = self._json("¿a cuánto está el dólar?", resp)
        self.assertEqual(r.json()["reply"], main._TEXTO_NEGATIVA)
        self.assertEqual(self._costo_guardado(), self._esperado(self.U1, self.U2))
        self.assertEqual(self._count(), 0)


class TestPrecioDelModelo(unittest.TestCase):

    def test_el_modelo_del_chat_esta_en_la_tabla_de_precios(self):
        self.assertIn(llm.MODEL_SONNET, llm._PRICING_USD_PER_M)
        p = main._precio_por_millon(llm.MODEL_SONNET)
        self.assertEqual(p["input"], llm._PRICING_USD_PER_M[llm.MODEL_SONNET]["input"])
        self.assertEqual(p["output"], llm._PRICING_USD_PER_M[llm.MODEL_SONNET]["output"])


if __name__ == "__main__":
    unittest.main()
