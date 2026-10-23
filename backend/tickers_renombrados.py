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


# Renombres que valen SÓLO para lo que llega de un broker (archivo o foto de
# tenencias), no para lo que la persona tipea.
#
# Barrick pasó de GOLD a B (mayo 2025). Yahoo ya no cotiza GOLD.BA y data912
# sólo lista B, así que un CEDEAR guardado como GOLD queda sin precio. Y Bull
# Market mezcla los dos códigos en el mismo archivo: compra "GOLD" en 2021 y
# vende "B" en 2023 — sin traducir son dos papeles y la compra queda abierta
# para siempre (medido 2026-10-22 con la cuenta de Agustín: GOLD 4 fantasma).
# No va en TICKERS_RENOMBRADOS porque en la pantalla "GOLD" es también el
# indicador «Oro (spot)» (frontend/src/utils/tickers.js): quien lo sigue en su
# lista no puede pasar a seguir Barrick.
RENOMBRADOS_AL_IMPORTAR = {
    "GOLD": "B",   # Barrick Gold → Barrick Mining, mayo 2025
    # Canje de ON: Cresud cambió la Clase XXIII por la Clase XXXVIII (CS38O, vto
    # 3/3/2026), cierre el 8/7/2022. Bull Market lo anota como "CANJ" SIN ticker,
    # así que la XXIII quedaba abierta para siempre y, si la CS38O se traspasaba
    # a otro broker, el cierre del traspaso no la reconocía (cuenta de Agustín,
    # 2026-10-22: CSDOO 298 fantasma; entraron 306 CS38O a Balanz). Que CSDOO
    # sea la XXIII es deducido —la fecha del CANJ coincide con el cierre del
    # canje—, no sale de una fuente oficial del ticker.
    "CSDOO": "CS38O",
}


def _traducir(sym: Optional[str], tabla: dict) -> Optional[str]:
    if not sym:
        return sym
    s = sym.strip().upper()
    base, sufijo = (s[:-3], ".BA") if s.endswith(".BA") else (s, "")
    nuevo = tabla.get(base)
    return f"{nuevo}{sufijo}" if nuevo else sym


def ticker_vigente(sym: Optional[str]) -> Optional[str]:
    """El código con el que cotiza hoy. Respeta el sufijo de BYMA (SQ.BA → XYZ.BA).

    Si el código no cambió, devuelve EXACTAMENTE lo que recibió (mismas
    mayúsculas, mismos espacios): quien lo llame no cambia de comportamiento
    para ningún otro activo."""
    return _traducir(sym, TICKERS_RENOMBRADOS)


def ticker_importado(sym: Optional[str]) -> Optional[str]:
    """`ticker_vigente` más los renombres que sólo aplican a lo que manda un
    broker (ver RENOMBRADOS_AL_IMPORTAR). Lo usan los dos lugares por donde
    entra todo lo importado: importing/schema.NormalizedTx e
    importing/tenencia.Holding."""
    return _traducir(sym, {**TICKERS_RENOMBRADOS, **RENOMBRADOS_AL_IMPORTAR})


def codigos_anteriores(sym: Optional[str]) -> list:
    """Los códigos viejos que hoy se guardan como `sym` (B → ["GOLD"]).

    Lo usa el anti-duplicados: la huella de una fila guardada lleva el código
    con el que entró. Si se importó antes de que existiera el renombre, la misma
    fila hoy da OTRA huella y entraría dos veces (la compra y su débito de caja)."""
    s = (sym or "").strip().upper()
    base, sufijo = (s[:-3], ".BA") if s.endswith(".BA") else (s, "")
    tabla = {**TICKERS_RENOMBRADOS, **RENOMBRADOS_AL_IMPORTAR}
    return [f"{viejo}{sufijo}" for viejo, nuevo in tabla.items() if nuevo == base]
