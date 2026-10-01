"""El aviso que Vercel se guarda: el latido de los streams del chat.

MEDIDO el 2026-10-01 en producción: cuando dos avisos salen pegados y después
hay silencio, Vercel retiene el segundo hasta que llega algo más. «Leyendo tu
cartera» llegaba 8,7 s tarde, junto con la respuesta. El remedio medido es un
comentario SSE vacío cada `_LATIDO_SSE_SEG` de silencio (ver `_con_latido`).

Estos tests cuidan tres cosas:
  1. que el latido salga mientras el generador está callado, y no cuando no
     hace falta;
  2. que cortar el stream (el usuario cierra la pestaña) siga corriendo el
     `finally` del generador — ahí vive el cobro o la devolución de la consulta;
  3. que el chat REAL pase por el latido (endpoint completo, modelo de mentira
     que tarda en contestar), y que ningún stream nuevo se lo saltee.
"""
import asyncio
import json
import logging
import os
import re
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


async def _juntar(gen, cortar_despues_de=None, tras_corte=0.0):
    """Recorre `_con_latido` como lo hace StreamingResponse. Con
    `cortar_despues_de=N` lo cierra después del aviso N (el navegador se fue)."""
    out = []
    agen = main._con_latido(gen, cada=0.1)
    try:
        async for f in agen:
            out.append(f)
            if cortar_despues_de and sum(1 for x in out if x != main._LATIDO_SSE) >= cortar_despues_de:
                break
    finally:
        await agen.aclose()
    if tras_corte:
        await asyncio.sleep(tras_corte)
    return out


class TestLatido(unittest.TestCase):

    def test_late_mientras_el_generador_esta_callado(self):
        def gen():
            yield "data: a\n\n"
            time.sleep(0.45)            # la IA pensando
            yield "data: b\n\n"
        out = asyncio.run(_juntar(gen()))
        avisos = [f for f in out if f != main._LATIDO_SSE]
        self.assertEqual(avisos, ["data: a\n\n", "data: b\n\n"])
        entre = out[out.index("data: a\n\n") + 1:out.index("data: b\n\n")]
        self.assertGreaterEqual(len(entre), 3)      # ~4 latidos en 0,45 s cada 0,1 s
        self.assertTrue(all(f == main._LATIDO_SSE for f in entre))

    def test_sin_silencio_no_hay_latidos(self):
        def gen():
            for i in range(20):
                yield f"data: {i}\n\n"
        out = asyncio.run(_juntar(gen()))
        self.assertNotIn(main._LATIDO_SSE, out)
        self.assertEqual(len(out), 20)

    def test_el_latido_es_un_comentario_que_el_navegador_ignora(self):
        # El lector del navegador (utils/api.js chatStream) separa por línea en
        # blanco y sólo mira las líneas que empiezan con "data:".
        self.assertTrue(main._LATIDO_SSE.endswith("\n\n"))
        self.assertTrue(main._LATIDO_SSE.startswith(":"))
        self.assertNotIn("data:", main._LATIDO_SSE)

    def _con_avisos_del_log(self):
        avisos = []
        class _H(logging.Handler):
            def emit(s, r): avisos.append(r.getMessage())
        h = _H()
        main.log.addHandler(h)
        self.addCleanup(main.log.removeHandler, h)
        return avisos

    def test_cortar_con_el_generador_quieto_corre_su_finally(self):
        avisos = self._con_avisos_del_log()
        cerro = []
        def gen():
            try:
                yield "data: a\n\n"
                yield "data: b\n\n"
                yield "data: c\n\n"
            finally:
                cerro.append(threading.current_thread() is threading.main_thread())

        async def correr():
            await _juntar(gen(), cortar_despues_de=1)
            await asyncio.sleep(0.2)
            return list(cerro)
        # Una sola vez, y en un hilo aparte: no frena al resto del servidor.
        self.assertEqual(asyncio.run(correr()), [False])
        self.assertEqual([a for a in avisos if "cerrar" in a], [])

    def test_cortar_mientras_espera_a_la_ia_corre_su_finally_cuando_vuelve(self):
        # El corte llega con un hilo adentro del generador (esperando a la
        # IA): no se lo puede cerrar mientras corre. Tiene que cerrarse apenas
        # devuelva, por el camino de `_con_latido` y no por el recolector de
        # basura. MEDIDO: cancelar el pedido hacía que el cierre fallara con
        # "generator already executing" y quedara librado al recolector.
        avisos = self._con_avisos_del_log()
        cerro = []
        def gen():
            try:
                yield "data: a\n\n"
                time.sleep(0.3)
                yield "data: b\n\n"
                yield "data: c\n\n"
            finally:
                cerro.append(True)

        async def correr():
            agen = main._con_latido(gen(), cada=0.05)
            primero = await agen.__anext__()
            self.assertEqual(primero, "data: a\n\n")
            # Llega un latido: el hilo está adentro del sleep.
            self.assertEqual(await agen.__anext__(), main._LATIDO_SSE)
            await agen.aclose()
            self.assertEqual(cerro, [])          # todavía está corriendo
            await asyncio.sleep(0.6)
            return list(cerro)
        self.assertEqual(asyncio.run(correr()), [True])
        self.assertEqual([a for a in avisos if "cerrar" in a], [])


class _Txt:
    type = "text"
    def __init__(self, t): self.text = t
    def model_dump(self): return {"type": "text", "text": self.text}


class _Resp:
    def __init__(self, content):
        self.content, self.stop_reason, self.usage = content, "end_turn", None


class TestChatConLatido(unittest.TestCase):

    def test_el_chat_late_mientras_la_ia_piensa(self):
        """Endpoint completo: «Leyendo tu cartera» sale, la IA tarda en
        escribir, y en ese silencio tienen que salir latidos — son los que
        sueltan el aviso que Vercel retenía."""
        conn = main.get_db()
        self.addCleanup(conn.close)
        for t in ("positions", "brokers", "users", "ai_usage_daily"):
            conn.execute(f"DELETE FROM {t}")
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,?)",
            ("latido@rendi.test", "x", "pro")).lastrowid
        conn.commit()
        token = main.create_token(uid)

        class _Stream:
            def __init__(s, kw): s.r = _Resp([_Txt("Bien.")])
            def __enter__(s): return s
            def __exit__(s, *a): return False
            @property
            def text_stream(s):
                time.sleep(3 * main._LATIDO_SSE_SEG + 0.2)    # pensando
                yield "Bien."
            def get_final_message(s): return s.r

        mc = MagicMock()
        mc.messages.stream.side_effect = lambda **kw: _Stream(kw)
        from fastapi.testclient import TestClient
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            r = TestClient(main.app).post(
                "/api/ai/chat", headers={"Authorization": f"Bearer {token}"},
                json={"messages": [{"role": "user", "content": "¿Cómo está mi portfolio en general?"}],
                      "snapshot": {"summary": {}, "positions": [], "operations": [],
                                   "monthly": [], "brokers": []},
                      "stream": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["content-type"].split(";")[0], "text/event-stream")
        trozos = [t + "\n\n" for t in r.text.split("\n\n") if t]
        tipos = []
        for t in trozos:
            if t == main._LATIDO_SSE:
                tipos.append("latido")
            elif t.startswith("data:"):
                tipos.append(json.loads(t[5:])["t"])
        i_paso, i_delta = tipos.index("paso"), tipos.index("delta")
        self.assertLess(i_paso, i_delta)
        self.assertGreaterEqual(tipos[i_paso:i_delta].count("latido"), 2, tipos)
        self.assertEqual(tipos[-1], "done")


class TestNingunStreamSeSalteaElLatido(unittest.TestCase):

    def test_todo_text_event_stream_sale_de_respuesta_sse(self):
        """Propagación: un stream SSE nuevo armado a mano con StreamingResponse
        vuelve a tener el aviso retenido por Vercel. El único lugar que puede
        decir `text/event-stream` es `_respuesta_sse`."""
        src = open(os.path.join(AQUI, "..", "main.py"), encoding="utf-8").read()
        usos = [m.start() for m in re.finditer(r'media_type="text/event-stream"', src)]
        ini = src.index("def _respuesta_sse(")
        fin = src.index("\ndef ", ini + 1)
        afuera = [src.count("\n", 0, p) + 1 for p in usos if not ini <= p < fin]
        self.assertEqual(afuera, [], f"main.py arma SSE sin _respuesta_sse en las líneas {afuera}")


if __name__ == "__main__":
    unittest.main()
