"""Las lecturas pesadas pasan TODAS por el mismo freno (`main._freno_tecnico`).

Una lectura técnica de muchos activos, o de 3 años de velas de uno, ocupa uno
de los 40 lugares del único proceso del servidor. El freno se ponía ruta por
ruta, y cada ronda de la auditoría encontraba otra que lo leía sin él: «Tus
señales», la ficha, después tus tesis y el peso (auditoría E1, 29/10, y sus dos
re-tests). Un freno por ruta depende de que el que agrega la ruta se acuerde.

Acá se da vuelta: la FUNCIÓN pesada se marca una vez, donde se define
(`@pesado`). Si corre dentro de un pedido HTTP (`_en_pedido`, lo pone
`MarcarPedido`) que no pasó por el freno (`_con_freno`, lo pone
`main._freno_tecnico`), queda anotada en `SIN_FRENO` y en el log. La suite
(conftest) se pone en rojo en el test que la provocó: una ruta nueva que llega
a una lectura pesada sin freno no pasa, aunque nadie se acuerde de ella.

Fuera de un pedido (la noche, los mails del sábado, los avisos) no aplica: no
compiten con nadie por los 40 lugares de la misma forma.
"""
import contextvars
import functools
import logging

log = logging.getLogger(__name__)

_en_pedido = contextvars.ContextVar("rendi_en_pedido", default=None)   # "GET /api/…"
_con_freno = contextvars.ContextVar("rendi_con_freno", default=False)

SIN_FRENO = []        # (pedido, función) que corrieron sin freno; lo mira el conftest
_YA_AVISADOS = set()  # para el log: una vez por par
_MAX_ANOTADOS = 200


def pesado(fn):
    """Marca una función como lectura pesada: dentro de un pedido HTTP tiene que
    correr adentro del freno."""
    @functools.wraps(fn)
    def envuelta(*a, **k):
        pedido = _en_pedido.get()
        if pedido and not _con_freno.get():
            par = (pedido, fn.__qualname__)
            if len(SIN_FRENO) < _MAX_ANOTADOS:
                SIN_FRENO.append(par)
            if par not in _YA_AVISADOS:
                _YA_AVISADOS.add(par)
                log.error("lectura pesada SIN FRENO: %s llamó a %s (pasala por main._freno_tecnico)",
                          *par)
        return fn(*a, **k)
    envuelta._rendi_pesado = True
    return envuelta


class MarcarPedido:
    """Middleware ASGI: marca que lo que corre adentro es parte de un pedido
    HTTP. Puro ASGI (no `@app.middleware`) para que la marca llegue hasta el
    hilo donde corre la ruta (Starlette copia el contexto al hilo)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _en_pedido.set(f"{scope.get('method')} {scope.get('path')}")
        try:
            await self.app(scope, receive, send)
        finally:
            _en_pedido.reset(token)
