"""Acciones que cambiaron de código: el viejo se traduce al vigente AL ENTRAR.

POR QUÉ EXISTE
──────────────
Block (ex-Square) dejó de cotizar como SQ y pasó a XYZ en enero de 2025, en Nueva
York y en BYMA. Medido el 2026-10-19: Yahoo contesta "symbol may be delisted"
para SQ y SQ.BA, data912 (el feed de BYMA) sólo lista XYZ/XYZD/XYZC, y Yahoo
tiene la historia de XYZ desde ANTES del cambio (enero 2024: US$ 65), así que el
código nuevo sirve también para valuar operaciones viejas.

Una posición guardada como SQ queda sin precio en todos lados: la pantalla la
muestra al costo (sin ganancia ni pérdida) y la foto diaria la cuenta como «sin
precio» — si pesa más del 5 % de la cuenta, ese día no se escribe. Y si la misma
persona tiene compras viejas como SQ y nuevas como XYZ, son dos libros FIFO que
nunca se ven (el mismo problema que AL30/AL30D, ver importing/tickers_cd.py):
la venta de XYZ no encuentra las compras de SQ.

Por eso la traducción va en la ENTRADA —importador, carga a mano, chat— y no al
pedir el precio: el papel queda guardado una sola vez, con el código que cotiza,
y todos los lectores (precios, historia, dividendos, alertas, foto diaria) lo
encuentran sin saber que existió otro código.

Si otra empresa cambia de código, se agrega acá y nada más: lo usan
importing/schema.NormalizedTx (todo lo importado), importing/tenencia.Holding (la
foto de tenencias), los formularios de main.py y ai/trade_tickers (el chat). La
lista de la pantalla (frontend/src/utils/tickers.js) tiene que ofrecer sólo el
código nuevo.
"""
from typing import Optional

# código viejo → código vigente
TICKERS_RENOMBRADOS = {
    "SQ": "XYZ",   # Block (ex-Square), enero 2025
}


def ticker_vigente(sym: Optional[str]) -> Optional[str]:
    """El código con el que cotiza hoy. Respeta el sufijo de BYMA (SQ.BA → XYZ.BA).

    Si el código no cambió, devuelve EXACTAMENTE lo que recibió (mismas
    mayúsculas, mismos espacios): quien lo llame no cambia de comportamiento
    para ningún otro activo."""
    if not sym:
        return sym
    s = sym.strip().upper()
    base, sufijo = (s[:-3], ".BA") if s.endswith(".BA") else (s, "")
    nuevo = TICKERS_RENOMBRADOS.get(base)
    return f"{nuevo}{sufijo}" if nuevo else sym
