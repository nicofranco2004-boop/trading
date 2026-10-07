"""Los pasos que Mervall-E AI muestra mientras piensa salen de etapas REALES.

Hasta el 2026-09-30 el servidor sólo anunciaba las herramientas: una pregunta
que se contestaba con la cartera no mostraba ningún paso (lo reportó Nico:
"no muestra la lista de las cosas que está haciendo"). Ahora anuncia también
las dos etapas que recorre toda respuesta — leer la cartera, y armar la
respuesta con lo que encontró si salió a buscar datos — en el momento en que
empiezan. Este test pasa por el endpoint real con un modelo de mentira y lee
los frames del stream en orden.
"""
import json
import time
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402
from tests._ia_falsa import eventos  # noqa: E402


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


class TestPasosDelChat(unittest.TestCase):

    def _frames(self, con_herramienta, pensar=False):
        conn = main.get_db()
        self.addCleanup(conn.close)
        for t in ("positions", "brokers", "users", "ai_usage_daily"):
            conn.execute(f"DELETE FROM {t}")
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,?)",
            ("pasos@rendi.test", "x", "pro")).lastrowid
        conn.commit()
        token = main.create_token(uid)
        llamados = []

        def respuesta(kw):
            llamados.append(1)
            # 1ª vuelta: sale a buscar el dólar; 2ª: contesta.
            if con_herramienta and len(llamados) == 1:
                return _Resp([_Tool("get_fx_rates")], stop="tool_use")
            return _Resp([_Txt("Bien.")])

        class _Stream:
            def __init__(s, kw):
                s.r = respuesta(kw)
                s.pedazos = [b.text for b in s.r.content if b.type == "text"]
            def __iter__(s): return eventos(s.pedazos, pensar=pensar)
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def get_final_message(s): return s.r

        mc = MagicMock()
        mc.messages.create.side_effect = lambda **kw: respuesta(kw)
        mc.messages.stream.side_effect = lambda **kw: _Stream(kw)
        from fastapi.testclient import TestClient
        def tool_fake(content, uid, tier, tc, mx, **k):
            time.sleep(0.05)            # buscar el dólar tarda algo
            return [{"type": "tool_result", "tool_use_id": "tu1", "content": "{}"}], tc + 1

        # Qué viaja en cada ENVÍO (no sólo en qué orden): se espía el mismo
        # `_con_latido` que usa producción, adentro de `_respuesta_sse`.
        self.escrituras = []
        real = main._con_latido

        async def espia(frames, cada=main._LATIDO_SSE_SEG):
            async for x in real(frames, cada):
                self.escrituras.append(x)
                yield x

        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None), \
             patch.object(main, "_ai_chat_exec_tools", side_effect=tool_fake), \
             patch.object(main, "_con_latido", espia):
            r = TestClient(main.app).post(
                "/api/ai/chat", headers={"Authorization": f"Bearer {token}"},
                json={"messages": [{"role": "user", "content": "¿Cómo está mi portfolio en general?"}],
                      "snapshot": {"summary": {}, "positions": [], "operations": [],
                                   "monthly": [], "brokers": []},
                      "stream": True})
        self.assertEqual(r.status_code, 200, r.text)
        frames = []
        for linea in r.text.splitlines():
            if linea.startswith("data:"):
                frames.append(json.loads(linea[5:].strip()))
        return frames

    def test_sin_herramientas_igual_muestra_que_lee_la_cartera(self):
        frames = self._frames(con_herramienta=False)
        pasos = [f["d"] for f in frames if f.get("t") == "paso"]
        self.assertEqual(pasos, [main._PASO_LEYENDO])
        # Y llega ANTES que el texto: es lo que se ve mientras espera.
        tipos = [f.get("t") for f in frames]
        self.assertLess(tipos.index("paso"), tipos.index("delta"))

    def test_con_herramienta_lee_busca_y_arma_en_ese_orden(self):
        frames = self._frames(con_herramienta=True)
        pasos = [f["d"] for f in frames if f.get("t") == "paso"]
        self.assertEqual(pasos, [main._PASO_LEYENDO, "Mirando el dólar", main._PASO_ARMANDO])
        tipos = [f.get("t") for f in frames]
        # "Armando…" se anuncia antes del texto de la respuesta, no después.
        ult_paso = max(i for i, t in enumerate(tipos) if t == "paso")
        self.assertLess(ult_paso, tipos.index("delta"))

    def test_cuando_la_ia_piensa_se_anuncia_antes_del_texto(self):
        """MEDIDO el 2026-10-01: 4 s pensando sin ningún paso nuevo — la lista
        se quedaba en «Leyendo tu cartera» y parecía trabada. Anthropic avisa
        cuándo empieza a pensar: ese aviso es el paso."""
        frames = self._frames(con_herramienta=False, pensar=True)
        pasos = [f["d"] for f in frames if f.get("t") == "paso"]
        self.assertEqual(pasos, [main._PASO_LEYENDO, main._PASO_PENSANDO])
        tipos = [f.get("t") for f in frames]
        ult_paso = max(i for i, t in enumerate(tipos) if t == "paso")
        self.assertLess(ult_paso, tipos.index("delta"))
        # Leer los eventos uno por uno no duplica el texto: el SDK manda
        # también un evento `text` por cada pedazo, y ése se ignora.
        texto = "".join(f["d"] for f in frames if f.get("t") == "delta")
        self.assertEqual(texto.split("\n---RENDI---")[0], "Bien.")

    def test_sin_pensar_no_se_inventa_el_paso(self):
        frames = self._frames(con_herramienta=False, pensar=False)
        pasos = [f["d"] for f in frames if f.get("t") == "paso"]
        self.assertNotIn(main._PASO_PENSANDO, pasos)

    def test_la_apertura_y_leyendo_viajan_en_el_mismo_envio(self):
        """MEDIDO el 2026-10-01: salían en dos envíos seguidos y Vercel se
        guardaba el segundo hasta el latido — «Leyendo tu cartera» 0,25 s tarde
        en 3 de 4 preguntas."""
        self._frames(con_herramienta=False)
        primero = self.escrituras[0]
        self.assertTrue(primero.startswith(": ok"), primero)
        self.assertIn(f'"d": "{main._PASO_LEYENDO}"', primero)

    def test_el_reset_y_la_herramienta_viajan_juntos(self):
        self._frames(con_herramienta=True)
        juntos = [e for e in self.escrituras if '"t": "reset"' in e]
        self.assertEqual(len(juntos), 1, self.escrituras)
        self.assertIn("Mirando el dólar", juntos[0])
        # «Armando…» sale DESPUÉS de buscar el dólar: otro envío.
        self.assertNotIn(main._PASO_ARMANDO, juntos[0])

    def test_con_herramienta_piensa_una_sola_vez(self):
        """La vuelta que arma la respuesta también piensa, pero eso ya lo dice
        «Armando la respuesta con lo que encontré»: no se repite."""
        frames = self._frames(con_herramienta=True, pensar=True)
        pasos = [f["d"] for f in frames if f.get("t") == "paso"]
        self.assertEqual(pasos, [main._PASO_LEYENDO, main._PASO_PENSANDO,
                                 "Mirando el dólar", main._PASO_ARMANDO])


if __name__ == "__main__":
    unittest.main()
