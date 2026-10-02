"""Resend y reloj de mentira, para medir los mails por el camino de producción.

Los tests que miden la pausa entre mails o lo que pasa cuando Resend rechaza
uno tienen que pasar por los `send_*` y el `_send` de verdad: la pausa vive en
`_send` (`emails._esperar_turno`), y un test que reemplaza el `send_*` no la ve.
Lo único de mentira es Resend (`httpx.post`) y el reloj de `billing.emails`
(su `sleep` avanza el reloj en vez de esperar). Se apaga la guarda de pytest de
`_send` y la clave es de mentira: aunque un pedido se escapara, Resend lo
rechazaría.

Lo usan test_ritmo_de_envio.py, test_envio_masivo.py y test_feedback_prueba.py.
"""
import threading
import time
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import httpx

from billing import emails


class Reloj:
    """El `time` que ve `billing.emails`: `sleep` avanza el reloj en vez de
    esperar, y anota cuánto se pidió dormir."""

    def __init__(self):
        self.ahora = 1000.0
        self.siestas = []

    def monotonic(self):
        return self.ahora

    def sleep(self, s):
        self.siestas.append(s)
        self.ahora += s


class Resend:
    """Hace de Resend: anota cada pedido (hora, destinatario) y contesta lo que
    el test haya encolado para ese destinatario — un código HTTP o una
    excepción de httpx —, o 200."""

    def __init__(self, reloj=None, demora=0.3):
        self.reloj = reloj
        self.demora = demora            # lo que tarda en contestar (reloj de mentira)
        self.pedidos = []               # [(hora, to)]
        self.mails = []                 # [(to, asunto, texto)]
        self.htmls = {}                 # to -> [html, ...]
        self.respuestas = {}            # to -> [200 | 429 | Exception, ...]
        self._lock = threading.Lock()

    def post(self, url, headers=None, json=None, timeout=None):
        assert url == "https://api.resend.com/emails"
        to = json["to"][0]
        with self._lock:
            hora = self.reloj.ahora if self.reloj else time.monotonic()
            self.pedidos.append((hora, to))
            self.mails.append((to, json.get("subject", ""), json.get("text", "")))
            self.htmls.setdefault(to, []).append(json.get("html", ""))
            if self.reloj:
                self.reloj.ahora += self.demora
            cola = self.respuestas.get(to) or []
            r = cola.pop(0) if cola else 200
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r, json={"id": "re_x"},
                              request=httpx.Request("POST", url))

    def a(self, to):
        return [h for h, t in self.pedidos if t == to]

    def horas(self):
        return [h for h, _ in self.pedidos]


@contextmanager
def red_de_mentira(reloj=None, demora=0.3, direcciones_de_prueba=False,
                   todo_sleep_en_el_reloj=False):
    """`direcciones_de_prueba=True` deja pedir también para las @rendi.test
    (los tests del panel de admin crean así a sus usuarios).

    `todo_sleep_en_el_reloj=True`: CUALQUIER `time.sleep` (no sólo el de
    `emails`) avanza el reloj de mentira. Sirve para ver una pausa de más que
    alguien agregue afuera de `_send`: si no, dormiría de verdad y el reloj no
    se enteraría."""
    resend = Resend(reloj, demora)
    with ExitStack() as st:
        st.enter_context(patch.object(emails, "_running_under_pytest", lambda: False))
        st.enter_context(patch.object(emails, "_api_key", lambda: "re_de_mentira"))
        if direcciones_de_prueba:
            st.enter_context(patch.object(emails, "_is_test_address", lambda a: False))
        # `create=True`: así un archivo corre ENTERO contra el código de antes
        # de la pausa central y falla por lo que mide, no por un nombre que falta.
        st.enter_context(patch.object(emails, "_ultimo_pedido", None, create=True))
        st.enter_context(patch("httpx.post", resend.post))
        if reloj is not None:
            st.enter_context(patch.object(emails, "time", reloj, create=True))
            if todo_sleep_en_el_reloj:
                st.enter_context(patch("time.sleep", reloj.sleep))
        yield resend


def separaciones(horas):
    horas = sorted(horas)
    return [b - a for a, b in zip(horas, horas[1:])]
