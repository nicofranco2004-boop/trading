"""Las velas del DEMO, estiradas para que terminen en sus precios (19/11/2026).

El demo (frontend/src/utils/demo.js) muestra una cartera inventada con precios
fijos: NVDA a US$ 178,50, GGAL a $ 4.820. Su análisis técnico lo arma el MISMO
motor que el de una cuenta (main.py, «La puerta del demo»), sobre las velas
REALES guardadas, multiplicadas por un factor para que la última vela cierre en
el precio del demo. Es como agrandar una foto: la forma no cambia. Los
promedios, los niveles y Fibonacci quedan multiplicados por el mismo factor; el
RSI, el ADX, el Squeeze y los porcentajes no cambian (son proporciones). Sin
esto, el gráfico de NVDA terminaba en su precio de verdad al lado de «Lo tenés:
35 acciones · +25,3 %», que es la cuenta con el del demo.

DÓNDE SE APLICA: en las tres puertas por donde entran velas crudas al motor, y
sólo mientras corre un pedido de la puerta del demo (`usando`):
  · `velas_diarias.serie` (las guardadas): terminan en el precio del demo;
  · `velas_horarias.para_la_ficha` (las de 1 y 4 horas): también terminan en
    él, con su propio factor (la última vela de una hora no es la de ayer);
  · `velas_diarias.ruedas_recientes` (la vela de HOY, de Yahoo): en el demo no
    hay. Con ella el gráfico terminaba en el precio de verdad de hoy estirado
    (NVDA 175,08 al lado de los 178,50 del demo, visto el 19/11): el demo no
    tiene un «hoy» de verdad, así que su gráfico termina en el último cierre.
Fuera de un pedido del demo nada cambia: es una variable del pedido
(contextvars), no del proceso, así que un pedido de una cuenta que corre al
mismo tiempo no la ve.

⚠️ LO YA CALCULADO SE GUARDA PARA TODOS. Un pedido del demo no lee ni escribe
las memorias de cosas armadas con velas (`tecnico._leer_varios`,
`velas_horarias._ARMADAS`): la lectura estirada del demo le llegaría a una cuenta,
y como los precios del demo los manda quien pide, cada precio distinto dejaba
otra entrada (memoria que crece sin tope y empuja afuera lo de las cuentas;
revisión a ciegas, 19/11). Lo del demo lo guarda su puerta, con tope de bytes
(main.py, `_RESPUESTAS_DEMO`). Lo que se guarda CRUDO (las velas de Yahoo en
memoria) se estira al leerlo y nunca se escribe estirado.

Este módulo no importa nada de la app: lo importan las puertas de velas, que
están abajo de todo.
"""
import contextvars
import math
from contextlib import contextmanager

# {ticker de las velas: precio en que tiene que terminar}. None: no es el demo.
_OBJETIVOS = contextvars.ContextVar("rendi_precios_del_demo", default=None)

_PRECIOS = ("open", "high", "low", "close")


@contextmanager
def usando(objetivos: dict):
    """Mientras dure el bloque, el pedido es del demo y las velas de cada ticker
    de `objetivos` ({ticker: precio}) terminan en ese precio."""
    marca = _OBJETIVOS.set({(t or "").strip().upper(): p for t, p in (objetivos or {}).items()})
    try:
        yield
    finally:
        _OBJETIVOS.reset(marca)


def en_el_demo() -> bool:
    """¿Este pedido es de la puerta del demo?"""
    return _OBJETIVOS.get() is not None


def clave(ticker: str):
    """El precio del demo en que terminan las velas de `ticker`, o None (fuera
    del demo, o un ticker sin precio en el demo)."""
    o = _OBJETIVOS.get()
    return o.get((ticker or "").strip().upper()) if o else None


def _factor(ticker: str, ultimo):
    p = clave(ticker)
    if not p or not isinstance(ultimo, (int, float)) or not math.isfinite(ultimo) or ultimo <= 0:
        return None
    return p / ultimo


def _por(x, k):
    return x * k if isinstance(x, (int, float)) and math.isfinite(x) else x


def velas(ticker: str, lista: list) -> list:
    """Las velas diarias [{date, open, high, low, close, volume}] de `ticker`
    (de la más vieja a la más nueva), estiradas para que la última cierre en el
    precio del demo si el pedido es del demo. Copias: lo que entra puede ser compartido."""
    k = _factor(ticker, lista[-1].get("close")) if lista else None
    if not k:
        return lista
    return [{**v, **{c: _por(v.get(c), k) for c in _PRECIOS if c in v}} for v in lista]


def tanda(ticker: str, t):
    """La tanda de ruedas recientes de `velas_diarias.ruedas_recientes`: la de
    Yahoo, o None en un pedido del demo (no tiene vela de hoy; ver arriba)."""
    return None if en_el_demo() else t


def tuplas_de_hora(ticker: str, lista: list) -> list:
    """Las velas de 1 hora de `velas_horarias` como las guarda en memoria
    (t, fecha, minuto, apertura, máximo, mínimo, cierre, volumen), estiradas
    para que la última cierre en el precio del demo si el pedido es del demo."""
    k = _factor(ticker, lista[-1][6]) if lista else None
    if not k:
        return lista
    return [v[:3] + tuple(_por(x, k) for x in v[3:7]) + v[7:] for v in lista]
