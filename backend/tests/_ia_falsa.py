"""Los eventos que entrega el SDK de Anthropic al recorrer un stream
(`for ev in stream`), para los modelos de mentira de los tests.

El chat lee la IA con `main._texto_y_etapas(stream)`, que recorre estos
eventos — no `stream.text_stream` — para poder ver cuándo la IA empieza a
pensar. Un modelo de mentira que sólo trae `text_stream` ya no pasa por el
mismo camino que producción: que su `__iter__` devuelva `eventos(...)`.
"""
from types import SimpleNamespace


def eventos(pedazos, pensar=False):
    """`pensar=True` abre antes un bloque de pensamiento, como hace Sonnet 5.5."""
    if pensar:
        yield SimpleNamespace(type="message_start")
        yield SimpleNamespace(type="content_block_start", index=0,
                              content_block=SimpleNamespace(type="thinking"))
        yield SimpleNamespace(type="content_block_stop", index=0)
    yield SimpleNamespace(type="content_block_start", index=1,
                          content_block=SimpleNamespace(type="text"))
    for p in pedazos:
        yield SimpleNamespace(type="content_block_delta", index=1,
                              delta=SimpleNamespace(type="text_delta", text=p))
        # El SDK también manda un evento `text` (con el acumulado) por cada
        # pedazo: el chat lo tiene que ignorar, o duplicaría el texto.
        yield SimpleNamespace(type="text", text=p, snapshot=p)
    yield SimpleNamespace(type="content_block_stop", index=1)
