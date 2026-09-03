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
    "LAC", "PDD", "SAND", "SCHD", "SID", "SSEC", "TSMC", "USDC", "WBD", "WFC",
    "WLD", "XLC", "YPFD", "ZEC",
    # ── Renta en dólares y REITs (2026-09-03) ────────────────────────────────
    # Estos NO están en tickers.js —no son activos que la app deje agregar a
    # mano— pero SÍ entran por import: son lo que compra una cuenta del exterior
    # (Balanz Internacional, Schwab, IBKR). Hoy se salvan de milagro, porque el
    # normalizador no los clasifica como STOCK y `consolidate_cd` gatea por
    # asset_type. El día que alguien mejore esa clasificación —que es lo
    # CORRECTO— truncan todos. El peor es SPYD→SPY: se fusionaría con el ticker
    # más tenido de la base, en el mismo ledger FIFO.
    "AGNC",   # AGNC Investment  → AGN (Allergan, delisted)
    "ARCC",   # Ares Capital     → ARC
    "EPD",    # Enterprise Prod. → EP
    "LAD",    # Lithia Motors    → LA
    "PLD",    # Prologis         → PL
    "QYLD", "RYLD", "SPYD", "XYLD",   # ETFs de covered call / dividendos
}
# LAC (Lithium Americas) entró a la allowlist de CEDEARs en f60502d y lo cazó
# `test_tickers_cd_sync` — el mismo guard que se escribió para SID. Termina en "C", así
# que el motor lo leía como pata-C de "LA" y lo truncaba. Verificado con yfinance:
# LAC = 3,26 USD y LAC.BA = 5.170 ARS cotizan; "LA" está delisted (no existe). Sin
# proteger, un usuario con LAC lo veía con precio "—".
# SID y SCHD se agregaron el 2026-08-06, reportados por un usuario de IOL:
#   · SID  = Companhia Siderúrgica Nacional (CEDEAR brasileño, ticker NYSE real).
#     Su export traía SID (78 filas, especie en pesos) y SIDD (10, pata dólar).
#     Sin proteger a SID, el motor lo leía como "pata dólar de SI" y lo truncaba:
#     SID→SI (un símbolo que no cotiza en ningún lado → precio "—" en la cartera)
#     y SIDD→SID, o sea las dos patas quedaban como activos SEPARADOS. Con SID
#     protegido, SID queda SID y SIDD consolida a SID: se arreglan los dos
#     síntomas de una.
#   · SCHD = Schwab US Dividend Equity. Mismo mecanismo (SCHD→SCH). No lo reportó
#     nadie todavía; salió del barrido de la allowlist entera.
# El barrido completo (588 símbolos de tickers.js) dejó UN solo terminado en C/D
# sin proteger: BA37D (Buenos Aires 2037 USD ley NY), que SÍ es una especie en
# dólares y por lo tanto SÍ debe truncarse a BA37. Lo cubre
# test_tickers_cd_sync.py, que vuelve a correr ese barrido en cada test run.

# Tipos de activo donde la pata D/C existe: bonos, acciones argentinas y CEDEARs
# se operan en pesos y en dólares con el mismo subyacente. Un FCI NO (su ticker
# termina en D/C legítimamente: IOLDOLD…), y cripto/fiat tampoco.
CD_ASSET_TYPES = {"BOND", "STOCK", "CEDEAR"}

# ── CEDEARs de acciones BRASILEÑAS ────────────────────────────────────────────
# Usan el ticker de Bovespa, que lleva un sufijo NUMÉRICO de clase (3 = ordinaria,
# 4 = preferida, 11 = unit): PETR3, VALE3, ITUB4… Su pata dólar en el broker se
# forma sacando ese número y agregando la D — o sea PETR3 ↔ PETRD.
#
# La regla genérica de abajo NO puede resolverlo: sacarle la D a PETRD da "PETR",
# que no existe (ni cotiza: BYMA lo lista como PETR3.BA). Y sin consolidar
# tampoco matchean. Hace falta el par explícito.
#
# Reportado por un usuario de IOL con su export real: 21 operaciones de PETR3 y
# 14 de PETRD que nunca se cruzaban. Las ventas en dólares no encontraban stock,
# se les sintetizaba un lote al precio de venta (P&L 0 — se ve en la app como
# "P. Entrada = P. Salida") y le quedaba abierto un remanente de PETR3 que ya
# había vendido.
#
# ES UN MAPA EXACTO, NO UNA REGLA, y a propósito: una regla de prefijo sobre
# tickers terminados en dígito arrasaría con los bonos y letras argentinos, que
# son casi todos (AL30, GD30, TX26, TZXD5, DGCU2, TGNO4…). En el export de ese
# usuario había 36 tickers terminados en número y sólo UNO era brasileño.
# Se agregan pares de a uno, verificados contra un export real.
BR_DOLLAR_LEG = {
    "PETRD": "PETR3",
}


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
    # Pata dólar de un CEDEAR brasileño: lookup EXACTO, antes que cualquier regla.
    # Va incluso para FCI y para tickers con punto: es un dict escrito a mano, sólo
    # puede tocar los símbolos que alguien puso ahí.
    if t in BR_DOLLAR_LEG:
        return BR_DOLLAR_LEG[t]
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
    if not raw_ticker:
        return raw_ticker
    # El mapa brasileño NO pasa por el gate de tipos: es un lookup exacto y los
    # parsers rara vez clasifican estas filas (IOL manda asset_type vacío → el
    # normalizador cae a OTHER, que no está en CD_ASSET_TYPES). Sin esta línea el
    # mapa sería letra muerta justo para el broker que lo reportó.
    _up = raw_ticker.strip().upper()
    if _up in BR_DOLLAR_LEG:
        return BR_DOLLAR_LEG[_up]
    if (asset_type or "").upper() not in CD_ASSET_TYPES:
        return raw_ticker
    return strip_cd_suffix(raw_ticker, is_fci=False)
