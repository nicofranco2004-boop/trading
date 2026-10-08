"""⭐ LA lista de cripto de Rendi: qué es cripto y con qué nombre lo cotiza Yahoo.

Vive en su propio archivo, sin depender de nada, para que la puedan leer TODOS
los que preguntan «¿esto es cripto?» — también los que no pueden importar `main`
(el importador, los armadores de la IA): main importa a esos módulos al cargar,
y si ellos importaran main se armaría un círculo. Hasta 2026-10-08 esa pregunta
la contestaban, además de esta lista, cuatro listas sueltas de 13 a 19 códigos
(el tipo que anota el importador, la tarjeta de perfil y el reparto por país de
la IA, los grupos del asesor) y el sector del diagnóstico: una tenencia de PEPE,
KAS o FET era cripto para la valuación y para la torta, «acción» para lo que
decía la IA y «OTHER» para el importador. `main` re-exporta todo con los mismos
nombres (`main.CRYPTO_SYMBOLS`, `main.yahoo_de_cripto`…).

Espejo en el frontend: `frontend/src/utils/crypto.js` (test de paridad en
crypto.test.js, que lee ESTE archivo).
"""

# NOTA: 'CVX' y 'DASH' NO van acá aunque existan como cripto (Convex Finance /
# Dash): colisionan con Chevron (CVX) y DoorDash (DASH), que son acciones/CEDEARs
# que los users SÍ tienen. El routing de /api/prices es por símbolo, así que
# incluirlos los preciaría como la cripto (Chevron ~156× barato, incl. el CEDEAR
# CVX.BA). Ver CORRECTNESS_AUDIT_2026-06-25.md (C3).
# La regla, entonces: un código que es cripto Y otra cosa entra sólo si la otra
# cosa NO está en el catálogo de Rendi (`frontend/src/utils/tickers.js`). STX es
# también Seagate y AXS Axis Capital, y entran; lo que queda es medirlo (Q12 del
# panel de alcance). Por la misma regla tampoco entran ROSE (Oasis Network: es
# Rosenbusch, acción argentina del catálogo — en una cuenta en pesos se valuaría
# la acción como la moneda) ni AGIX (SingularityNET: se fusionó en FET en 2024 y
# Yahoo no tiene un precio confiable — US$ 0,59 un día, 0,09 el siguiente, contra
# US$ 0,0007 en CoinGecko; el pelado es un ETF de US$ 48). Ninguna de las tres
# está en el buscador de cripto ni en el chat: la app no ofrece lo que no sabe
# valuar (tests/test_cripto_sin_lista.py).
CRYPTO_SYMBOLS = {
    'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOGE', 'TRX', 'DOT',
    'MATIC', 'POL', 'LINK', 'LTC', 'BCH', 'NEAR', 'UNI', 'ATOM', 'XLM', 'ETC',
    'APT', 'ARB', 'OP', 'AAVE', 'MKR', 'SNX', 'CRV', 'COMP', 'SUSHI', 'YFI',
    '1INCH', 'BAL', 'DYDX', 'GMX', 'BLUR', 'GRT', 'LRC', 'ZRX', 'BAT', 'REN',
    'ALGO', 'VET', 'EGLD', 'FTM', 'FLOW', 'HBAR', 'THETA', 'XTZ', 'EOS', 'WAVES',
    'ZIL', 'NEO', 'QTUM', 'ICX', 'ONT', 'IOTA', 'ZEC', 'XMR', 'KAVA',
    'SAND', 'MANA', 'AXS', 'ENJ', 'IMX', 'CHZ', 'GALA', 'ILV',
    'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'DEGEN',
    'SUI', 'SEI', 'TIA', 'INJ', 'JTO', 'PYTH', 'STRK', 'WLD', 'MANTA', 'ALT',
    'ORDI', 'RUNE', 'FIL', 'STX', 'CORE', 'CFX', 'ID', 'ARKM', 'CYBER',
    'RDNT', 'APE', 'LDO', 'RPL', 'FXS', 'FRAX', 'PENDLE', 'SSV',
    'WBTC', 'STETH',
    # Toncoin e Internet Computer: estaban sólo en la copia de `home.market` (hasta
    # 2026-10-08), así que Posiciones y la foto diaria no los reconocían como
    # cripto (en una cuenta en pesos pedían TON.BA, que no cotiza en ningún lado).
    'TON', 'ICP',
    # El buscador y el chat las ofrecían como cripto y no estaban acá (hasta
    # 2026-10-08): en pesos se pedía '<X>.BA', que no cotiza; en dólares el
    # código pelado, que para AR, ENS, FET y QNT es una ACCIÓN de EE.UU. (Antero,
    # EnerSys, Forum Energy, Quantinuum — Fetch.ai valía 394 veces de más). Esas
    # cuatro acciones no están en el catálogo de Rendi: entran, igual que STX
    # (Q12 y Q14 del panel de alcance miden las que no estén marcadas cripto).
    'ANKR', 'AR', 'BOME', 'CELO', 'ENA', 'ENS', 'FET', 'GMT', 'JASMY', 'JUP',
    'KAS', 'KSM', 'MEW', 'MINA', 'OCEAN', 'ONE', 'POPCAT', 'QNT', 'RNDR',
    # Render cambió su código RNDR por RENDER (2024): los exchanges ya exportan
    # RENDER, y Yahoo sólo cotiza 'RENDER-USD'.
    'RENDER',
}

# Monedas estables: se cotizan como cripto (Yahoo '-USD', rueda 24/7) pero NO están
# en CRYPTO_SYMBOLS, porque el resto de la app las trata como dólares (efectivo,
# cajas 'USDT', sin premium del dólar cripto). Antes vivían sólo en la copia de
# `home.market` y el nombre pelado que se le pide a Yahoo no es la moneda:
# medido 2026-10-08, 'USDT' no existe y 'USDC' es otro instrumento (US$ 0,0012).
CRIPTO_ESTABLES = {'USDT', 'USDC'}

# Con qué nombre cotiza Yahoo cada cripto. Casi todas son '<SÍMBOLO>-USD', pero
# cuando dos monedas comparten el símbolo Yahoo le pega un número a la conocida y
# deja el nombre limpio para la OTRA. Medido el 2026-10-08 contra el buscador de
# Yahoo (nombre + precio de cada una):
#   · el nombre limpio es OTRA moneda: 'TON-USD' es "TON Token" (US$ 0,0045, no
#     Toncoin US$ 1,36), 'ARB-USD' "ARbit" (US$ 0,0006 vs Arbitrum US$ 0,17),
#     'CORE-USD' "cVault.finance" (US$ 5.924 vs Core US$ 0,018), 'CYBER-USD'
#     "Cyberpunk City", 'ID-USD' "Everest", 'STRK-USD' "Strike", 'APE-USD'
#     "APEcoin.dev" — una tenencia valía lo que vale otra moneda;
#   · el nombre limpio no trae nada: APT, GRT, IMX, PEPE, STX, SUI, UNI, COMP, GMX,
#     DEGEN, ALT, MATIC y POL — quedaban con el último precio conocido o sin precio.
#   · 2026-10-08, las que entraron desde el buscador: 'JUP-USD' es "Jupiter"
#     (US$ 0,0003, no el Jupiter de Solana US$ 0,34), 'ONE-USD' "BigONE Token"
#     (no Harmony); GMT, MEW y POPCAT con el nombre limpio no traen nada. Cada
#     precio se cruzó con CoinGecko.
# MATIC → POL: Polygon cambió MATIC por POL 1 a 1 y Yahoo sólo cotiza POL.
# RNDR → RENDER: lo mismo con Render; 'RNDR-USD' no trae nada.
# FTM y FXS no tienen serie en Yahoo con ningún nombre: quedan como estaban.
# Si agregás una cripto: buscala en Yahoo y fijate el NOMBRE, no sólo que traiga
# precio (tests/test_cripto_una_lista.py).
_YAHOO_CRIPTO_DISTINTO = {
    'TON': 'TON11419-USD', 'ARB': 'ARB11841-USD', 'CORE': 'CORE23254-USD',
    'CYBER': 'CYBER24781-USD', 'ID': 'ID21846-USD', 'STRK': 'STRK22691-USD',
    'APE': 'APE18876-USD',
    'APT': 'APT21794-USD', 'GRT': 'GRT6719-USD', 'IMX': 'IMX10603-USD',
    'PEPE': 'PEPE24478-USD', 'STX': 'STX4847-USD', 'SUI': 'SUI20947-USD',
    'UNI': 'UNI7083-USD', 'COMP': 'COMP5692-USD', 'GMX': 'GMX11857-USD',
    'DEGEN': 'DEGEN30096-USD', 'ALT': 'ALT29073-USD',
    'MATIC': 'POL28321-USD', 'POL': 'POL28321-USD',
    'JUP': 'JUP29210-USD', 'ONE': 'ONE3945-USD',
    'GMT': 'GMT18069-USD', 'MEW': 'MEW30126-USD', 'POPCAT': 'POPCAT28782-USD',
    'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
}

# ⭐ LA lista de cripto de la app → su nombre en Yahoo. Todo el que cotice una
# cripto (Posiciones, la variación del día, la foto diaria, las alertas, el chat,
# el inicio) sale de acá; `home.market` la lee de acá en vez de tener su copia.
CRYPTO_YF = {sym: _YAHOO_CRIPTO_DISTINTO.get(sym, f"{sym}-USD")
             for sym in CRYPTO_SYMBOLS | CRIPTO_ESTABLES}


def yahoo_de_cripto(symbol):
    """El nombre con que Yahoo cotiza la cripto `symbol`, o None si no es una
    cripto de la lista. Acepta el símbolo pelado ('TON') y también con '-USD'
    pegado a mano ('TON-USD', como lo guardan el inicio y el chat): pegarle el
    sufijo NO es el nombre de Yahoo — 'TON-USD' es otra moneda."""
    s = (symbol or '').strip().upper()
    if s in CRYPTO_YF:
        return CRYPTO_YF[s]
    if s.endswith('-USD') and s[:-4] in CRYPTO_YF:
        return CRYPTO_YF[s[:-4]]
    return None


# Brokers cripto (exchanges). Su par de brokers tradicionales, ARS_BROKER_NAMES,
# vive en main — se usan para inferir currency al auto-crear un broker desde un
# import o desde la migración del admin. Lemon NO está acá a propósito (Lemon
# Cash maneja ARS y cripto): queda en ARS por fidelidad histórica; si algún día
# Lemon tiene un parser propio cripto, ese parser hardcodea el nombre.
CRYPTO_BROKER_NAMES = {'binance', 'coinbase', 'kraken', 'bybit', 'kucoin',
                       'bitget', 'okx', 'huobi', 'gemini', 'crypto.com',
                       'ripio', 'buenbit', 'satoshitango', 'fiwind'}


def is_exchange_broker(name) -> bool:
    """¿El broker es un EXCHANGE cripto (Binance, Ripio…) y no un broker AR
    (Cocos, Balanz…)? Decide el dólar con que se valúa la cripto: exchange →
    spot/USDT; broker → dólar MEP (lo que muestra el broker). SSoT única,
    compartida por la API (/api/brokers stampa is_exchange) y los valuadores."""
    return (name or '').strip().lower() in CRYPTO_BROKER_NAMES


def es_cripto(symbol) -> bool:
    """¿El código `symbol` es una cripto de la lista (o una moneda estable)?

    UNA respuesta para toda la app: la misma lista que decide cómo se cotiza
    (`yahoo_de_cripto`), así que lo que se valúa como cripto también se llama
    cripto. Acepta el código pelado ('PEPE') o con '-USD' pegado ('PEPE-USD').
    Las estables (USDT/USDC) cuentan: el que las quiera tratar como efectivo
    (la tarjeta de perfil, la torta) lo decide ANTES de preguntar esto.

    Los códigos que son cripto Y una acción del catálogo (DASH, ROSE, CVX) no
    están en la lista a propósito (ver la NOTA arriba de CRYPTO_SYMBOLS): para
    esos manda el tipo que anotó el importador (`es_tenencia_cripto`)."""
    return yahoo_de_cripto(symbol) is not None


def es_tenencia_cripto(p) -> bool:
    """¿Esta TENENCIA (fila de positions: `asset`, `asset_type`) es cripto?

    La misma regla que la torta de la pantalla (frontend assetClass.classifyAsset:
    `isCrypto(ticker) || asset_type === 'CRYPTO'`) y que el sesgo local
    (behavioral._en_bolsa_argentina): el código está en la lista, o el
    importador la marcó CRYPTO — ROSE comprada en un exchange es la cripto
    Oasis, no el Instituto Rosenbusch, aunque el código pelado sea la acción."""
    if (p.get("asset_type") or "").strip().upper() == "CRYPTO":
        return True
    return es_cripto(p.get("asset"))
