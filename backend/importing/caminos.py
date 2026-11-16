"""Los caminos del menú de cada broker que nombran los textos del servidor.

POR QUÉ EXISTE. Cómo bajar cada archivo lo explica la guía de la app:
BROKER_GUIDES, en `frontend/src/components/import/BrokerInstructions.jsx`. Es
la que se corrige cuando un broker cambia su menú. El servidor también nombra
caminos —en el aviso de «este archivo no es el que esperábamos» y en el nombre
de cada export— y los tenía copiados a mano, cada uno en su lector. Se habían
separado de la guía sin que nada avisara (al 16/11/2026):

  · PPI: el servidor decía «Mi cuenta → Movimientos»; la guía, «Actividad →
    Todos los movimientos». Y para la foto, «Mi cuenta → Estado de cuenta»; la
    guía, la pantalla principal → Exportar.
  · Cocos: la foto en «Inversiones → Estado de cuenta → Exportar»; la guía,
    Portfolio → «Descargar portfolio». Y los movimientos en «Actividad →
    Movimientos»; la guía, «Actividad → Descargar Movimientos».
  · Binance: «Asset History → Transaction History»; la guía, «Wallet →
    Transaction History».

Ahora cada camino se escribe UNA vez en el servidor, acá, y
`tests/test_caminos.py` se pone rojo si:
  · un camino de EN_LA_GUIA deja de estar, letra por letra, en los pasos de su
    broker en la guía (se corrigió uno y no el otro);
  · un texto del servidor escribe a mano un «Algo → Otra» con una palabra de
    los menús de broker, en vez de leerlo de acá.
"""
from __future__ import annotations

# (id de la guía en BROKER_GUIDES, archivo) → un pedazo de los pasos de ese
# broker en la guía, copiado tal cual. No hace falta que sea un camino con
# flechas: tiene que leerse bien dentro del aviso y estar en la guía.
EN_LA_GUIA = {
    ("cocos", "movimientos"): "Actividad → Descargar Movimientos",
    ("cocos", "foto"): "en la WEB de Cocos andá a Portfolio, arriba tocá “Descargar portfolio”",
    ("balanz", "movimientos"): "Actividad → Movimientos",
    ("balanz_internacional", "movimientos"): "Actividad → Movimientos",
    ("bullmarket", "movimientos"): "Mi Cuenta → Cuenta Corriente",
    ("iol", "movimientos"): "Mi Cuenta → Movimientos → Detalle de Movimientos",
    ("ppi", "movimientos"): "Actividad → Todos los movimientos",
    ("ppi", "foto"): ("en la pantalla principal —donde ves tu cartera— tocá Exportar "
                      "arriba a la derecha y elegí Excel (no PDF)"),
    ("schwab", "movimientos"): "Accounts → History",
    ("binance", "movimientos"): "Wallet → Transaction History",
}

# Exports que el servidor reconoce pero que la guía no explica, porque no son
# los que pedimos: igual se nombran en algún texto (el nombre del export, o el
# aviso de que ese no sirve) y viven acá para que no haya otra copia.
FUERA_DE_LA_GUIA = {
    ("balanz", "ordenes"): "Operaciones → Órdenes",
    ("balanz", "resultados"): "Actividad → Resultados",
    ("binance", "spot"): "Spot → Trade History",
    ("binance", "futuros"): "Futures → Trade History",
}


def camino(guia: str, archivo: str) -> str:
    """El camino de ese archivo. KeyError si no existe: los lectores lo piden
    al importarse, así que un nombre mal escrito rompe al arrancar (y en las
    pruebas), no en medio de la importación de alguien."""
    clave = (guia, archivo)
    return EN_LA_GUIA[clave] if clave in EN_LA_GUIA else FUERA_DE_LA_GUIA[clave]
