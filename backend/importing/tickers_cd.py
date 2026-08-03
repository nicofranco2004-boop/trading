"""Consolidación del sufijo dólar/cable (D/C) al ticker base.

POR QUÉ EXISTE
──────────────
Hacer "dólar MEP" en Argentina son DOS operaciones el mismo día sobre el MISMO
instrumento: se compra el bono en pesos (AL30) y se vende su pata dólar (AL30D)
unas horas después. El broker las exporta con TICKERS DISTINTOS.

El replay FIFO arma un ledger por símbolo EXACTO (`rebuild.py _full_events`
filtra `n.asset_symbol = ?`), así que AL30 y AL30D son dos libros separados que
nunca se ven. Resultado, reproducido en test:

  · la compra de AL30 queda ABIERTA → un activo fantasma que el usuario no tiene
  · la venta de AL30D no encuentra stock → se le sintetiza un lote semilla al
    precio de venta y sale con P&L = 0

Con las dos patas bajo el MISMO símbolo la maquinaria que ya existe las netea
sola —BUY-first en `persister.py`, el ORDER BY de `rebuild.py`,
`_cancel_conduit_pairs` y el spill cross-currency de `_replay_asset`— y no queda
nada abierto. Medido: la ÚNICA diferencia entre el caso sano y el roto es esa
letra final.

Reportado por un usuario (2026-08-01): "puede registrarse una ganancia irreal o
que te tome venta de un activo que no tenías registro inicial y posterior
comprar, dejando un activo en la cartera que no existe".

Este código estaba SOLO en el parser de IOL (`iol.py`), donde lleva tiempo
corriendo en producción. Acá se comparte para el resto de los brokers.
"""
from __future__ import annotations

import re

# Tickers que terminan en C/D de forma LEGÍTIMA — no son la pata dólar de nada.
# Espejo de los símbolos de frontend/src/utils/tickers.js que terminan en C/D:
# sin esta lista AMD→AM, GOLD→GOL, INTC→INT. Si tickers.js suma uno nuevo
# terminado en C/D, agregalo acá.
KNOWN_CD_TICKERS = {
    "AMC", "AMD", "BAC", "BBD", "BND", "BTC", "CAC", "CARC", "CRWD", "DBC",
    "EGLD", "ETC", "FBTC", "GBTC", "GD", "GILD", "GLD", "GOLD", "HD", "HOOD",
    "INTC", "JD", "KLAC", "LCID", "LQD", "LTC", "MATIC", "MCD", "MPC", "NOC",
    "PDD", "SAND", "SSEC", "TSMC", "USDC", "WBD", "WFC", "WLD", "XLC", "YPFD",
    "ZEC",
}

# Tipos de activo donde la pata D/C existe: bonos, acciones argentinas y CEDEARs
# se operan en pesos y en dólares con el mismo subyacente. Un FCI NO (su ticker
# termina en D/C legítimamente: IOLDOLD…), y cripto/fiat tampoco.
CD_ASSET_TYPES = {"BOND", "STOCK", "CEDEAR"}


def strip_cd_suffix(raw_ticker: str, is_fci: bool = False) -> str:
    """Devuelve el ticker base: le saca el sufijo de moneda y la D/C final.

    NO toca el ticker cuando:
      • es un FCI (`is_fci`): su ticker no es una pata dólar-MEP y suele terminar
        en D/C de verdad → truncarlo lo desalinea de la foto de tenencia;
      • tiene un punto (BA.C, BR.K…): el punto ya marca la clase y la letra final
        es parte del símbolo, no un sufijo;
      • está en `KNOWN_CD_TICKERS`;
      • mide menos de 3 caracteres (no queda ticker si le sacás una letra).
    """
    t = (raw_ticker or "").strip().upper()
    if not t:
        return t
    t = re.sub(r"\s*(US\$|U\$S)$", "", t).strip()
    if is_fci or "." in t:
        return t
    if len(t) >= 3 and t[-1] in ("D", "C") and t not in KNOWN_CD_TICKERS:
        t = t[:-1]
    return t


def consolidate_cd(raw_ticker: str, asset_type: str | None) -> str:
    """Variante gateada por `asset_type`, para el normalizador.

    Sólo consolida los tipos donde la pata dólar existe de verdad. Cualquier otro
    tipo —FUND, CRYPTO, FIAT, ETF, OTHER, o sin clasificar— vuelve intacto: es el
    lado seguro, porque un ticker consolidado de más partiría en dos el historial
    de un activo que estaba bien.
    """
    if not raw_ticker or (asset_type or "").upper() not in CD_ASSET_TYPES:
        return raw_ticker
    return strip_cd_suffix(raw_ticker, is_fci=False)
