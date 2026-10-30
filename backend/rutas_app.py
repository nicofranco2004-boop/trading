"""Las rutas de la app que viajan en un mail o en una notificación.

Un link a la ficha se armaba a mano en cada lugar (`f"/activo/{asset}"`), y en
el que no se codificaba el activo, uno con «/», «?» o «#» llevaba a otra
pantalla (`../../alertas?tab=mis`, auditoría E7, 29/10). Ahora es UNA función:
el que arme un link a la ficha la usa, y el activo sale codificado siempre.
"""
from urllib.parse import quote


def ruta_de_la_ficha(asset: str) -> str:
    """'/activo/<asset>' con el activo codificado entero (también la «/»)."""
    return f"/activo/{quote(str(asset or ''), safe='')}"
