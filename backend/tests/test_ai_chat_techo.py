"""El techo de salida del chat tiene que dejar aire para PENSAR y ESCRIBIR.

El techo (max_tokens) se calibró para Haiku, que no piensa antes de escribir y
cuenta el texto en menos tokens. Desde que el chat es Sonnet (2026-09-12), el
razonamiento sale del MISMO techo: medido por el endpoint real, con Sonnet 5 y
usuario Plus, "¿Qué activo es el que más riesgo me agrega?" salía cortada y sin
tarjetas 2 de 2 veces (650/650), y en Pro con Sonnet 5.5 "explicame en
detalle…" se cortaba 2 de 2 (1350/1350). Las respuestas normales ya usaban
hasta 646 (Plus) y 1344 (Pro): todo el chat vivía al borde.

Este test pasa por el endpoint y mira el techo que de verdad le llega al
modelo, en los dos caminos (streaming y JSON) y en la síntesis de respaldo.
Los mínimos son los medidos + margen: si alguien los baja, que sea midiendo.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402

# Lo que midió el uso real + margen para pensar. Ver el docstring.
MINIMO = {"plus": 1500, "pro": 2500}
MINIMO_SINTESIS = {"plus": 1000, "pro": 1500}


class _Txt:
    type = "text"
    def __init__(self, t): self.text = t
    def model_dump(self): return {"type": "text", "text": self.text}


class _Tool:
    type = "tool_use"
    def __init__(self, n): self.name, self.input, self.id = n, {}, "tu1"
    def model_dump(self): return {"type": "tool_use", "id": self.id, "name": self.name, "input": {}}


class _Resp:
    def __init__(self, content, stop="end_turn"):
        self.content, self.stop_reason, self.usage = content, stop, None


class TestTechoDelChat(unittest.TestCase):

    def _usuario(self, tier):
        conn = main.get_db()
        self.addCleanup(conn.close)
        for t in ("positions", "brokers", "users", "ai_usage_daily"):
            conn.execute(f"DELETE FROM {t}")
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,?)",
            (f"techo-{tier}@rendi.test", "x", tier)).lastrowid
        conn.commit()
        return main.create_token(uid)

    def _techos(self, tier, stream, con_herramienta=False):
        """max_tokens de cada llamado al modelo en un turno real del endpoint."""
        token = self._usuario(tier)
        vistos = []

        def respuesta(kw):
            vistos.append(((kw.get("tool_choice") or {}).get("type"), kw["max_tokens"]))
            if con_herramienta and (kw.get("tool_choice") or {}).get("type") != "none":
                return _Resp([_Tool("get_fx_rates")], stop="tool_use")
            return _Resp([_Txt("Bien.")])

        class _Stream:
            def __init__(s, kw): s.r = respuesta(kw); s.text_stream = []
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def get_final_message(s): return s.r

        mc = MagicMock()
        mc.messages.create.side_effect = lambda **kw: respuesta(kw)
        mc.messages.stream.side_effect = lambda **kw: _Stream(kw)
        from fastapi.testclient import TestClient
        tool_fake = lambda content, uid, tier, tc, mx, **k: (
            [{"type": "tool_result", "tool_use_id": "tu1", "content": "{}"}], tc + 1)
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None), \
             patch.object(main, "_ai_chat_exec_tools", side_effect=tool_fake):
            r = TestClient(main.app).post(
                "/api/ai/chat", headers={"Authorization": f"Bearer {token}"},
                json={"messages": [{"role": "user", "content": "¿Cómo está mi portfolio en general?"}],
                      "snapshot": {"summary": {}, "positions": [], "operations": [],
                                   "monthly": [], "brokers": []},
                      "stream": stream})
        self.assertEqual(r.status_code, 200, r.text)
        return vistos

    def test_el_techo_deja_aire_en_cada_plan_y_cada_camino(self):
        for tier in ("plus", "pro"):
            for stream in (False, True):
                with self.subTest(tier=tier, stream=stream):
                    vistos = self._techos(tier, stream)
                    self.assertTrue(vistos)
                    for _, techo in vistos:
                        self.assertGreaterEqual(techo, MINIMO[tier])

    def test_la_sintesis_de_respaldo_tambien(self):
        """Cuando se agotan las vueltas con herramientas, la última respuesta
        sale por la síntesis (tool_choice none), con su propio techo."""
        for stream in (False, True):
            with self.subTest(stream=stream):
                vistos = self._techos("pro", stream, con_herramienta=True)
                sintesis = [t for tipo, t in vistos if tipo == "none"]
                self.assertTrue(sintesis, vistos)
                self.assertGreaterEqual(min(sintesis), MINIMO_SINTESIS["pro"])


if __name__ == "__main__":
    unittest.main()
