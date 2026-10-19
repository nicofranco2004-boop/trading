"""Allowlist de tickers para register_trade (el write-path del chat IA).

GENERADO desde frontend/src/utils/tickers.js (la fuente de verdad del buscador
de la app) — si agregás un ticker allá, regenerá o agregalo acá. La allowlist es
un GUARD del write: el chat solo puede registrar activos que la app sabe valuar
(mismo criterio que el alta manual, que también sale de esas listas).

MVP: cripto + acciones US/ETFs + CEDEARs + acciones AR. Bonos/FCI = v2 (unidad
per-100 y NAV por nombre son trampas conocidas — no se registran por chat aún).
"""

CRYPTO_TICKERS = {
    '1INCH', 'AAVE', 'ADA', 'ALGO', 'ANKR', 'APE', 'APT', 'AR', 'ARB', 'ATOM',
    'AVAX', 'AXS', 'BAL', 'BAT', 'BCH', 'BLUR', 'BNB', 'BOME', 'BONK', 'BTC',
    'CELO', 'CFX', 'CHZ', 'COMP', 'CRV', 'DEGEN', 'DOGE', 'DOT', 'DYDX', 'EGLD',
    'ENA', 'ENJ', 'ENS', 'ETC', 'ETH', 'FET', 'FIL', 'FLOKI', 'FLOW', 'FTM', 'GALA',
    'GMT', 'GMX', 'GRT', 'HBAR', 'ICP', 'IMX', 'INJ', 'IOTA', 'JASMY', 'JTO', 'JUP',
    'KAS', 'KAVA', 'KSM', 'LDO', 'LINK', 'LTC', 'MANA', 'MATIC', 'MEW', 'MINA',
    'MKR', 'NEAR', 'NEO', 'OCEAN', 'ONE', 'OP', 'ORDI', 'PENDLE', 'PEPE', 'POPCAT',
    'PYTH', 'QNT', 'RNDR', 'RPL', 'RUNE', 'SAND', 'SEI', 'SHIB', 'SNX', 'SOL',
    'STRK', 'STX', 'SUI', 'SUSHI', 'THETA', 'TIA', 'TON', 'TRX', 'UNI', 'USDC',
    'USDT', 'VET', 'WAVES', 'WIF', 'WLD', 'XLM', 'XMR', 'XRP', 'XTZ', 'YFI', 'ZEC',
    'ZIL', 'ZRX'
}

US_TICKERS = {
    'AAL', 'AAPL', 'ABBV', 'ABEV', 'ABNB', 'ABT', 'ACN', 'ADBE', 'ADSK', 'AFRM',
    'AGG', 'ALAB', 'AMAT', 'AMC', 'AMD', 'AMGN', 'AMZN', 'ANET', 'ARGT', 'ARKG',
    'ARKK', 'ASML', 'ASTS', 'AVGO', 'AXP', 'AZN', 'BA', 'BABA', 'BAC', 'BAK', 'BB',
    'BBD', 'BIDU', 'BIOX', 'BKNG', 'BLK', 'BMNR', 'BMY', 'BND', 'BNTX', 'BRK-B',
    'BSX', 'BX', 'C', 'CAT', 'CEG', 'CMCSA', 'CMG', 'COIN', 'COP', 'COST', 'CRM',
    'CRWD', 'CRWV', 'CSCO', 'CVNA', 'CVX', 'DASH', 'DBC', 'DDOG', 'DE', 'DIA',
    'DIS', 'DOCU', 'DOW', 'EA', 'EEM', 'EFA', 'EOG', 'ETHE', 'ETSY', 'EWJ', 'EWZ',
    'F', 'FBTC', 'GBTC', 'GD', 'GE', 'GILD', 'GLD', 'GLOB', 'GM', 'GME', 'GOOG',
    'GOOGL', 'GPRK', 'GS', 'HD', 'HIMS', 'HMY', 'HON', 'HOOD', 'HUT', 'HYG', 'IAU',
    'IBIT', 'IBM', 'IEF', 'INDA', 'INTC', 'INTU', 'IREN', 'ITUB', 'IVV', 'IWM',
    'JD', 'JMIA', 'JNJ', 'JPM', 'KEEL', 'KLAC', 'KO', 'LAC', 'LAR', 'LCID', 'LI',
    'LIN', 'LLY', 'LMT', 'LOW', 'LQD', 'LRCX', 'LYFT', 'MA', 'MCD', 'MCHI', 'MDB',
    'MDLZ', 'MELI', 'META', 'MMM', 'MP', 'MPC', 'MRK', 'MRNA', 'MRVL', 'MS', 'MSFT',
    'MSTR', 'MU', 'MUX', 'NBIS', 'NET', 'NFLX', 'NIO', 'NKE', 'NOC', 'NOK', 'NOW',
    'NU', 'NVAX', 'NVDA', 'NVO', 'NVS', 'O', 'OKLO', 'OKTA', 'ONDS', 'ORCL', 'OXY',
    'PAGS', 'PANW', 'PARA', 'PATH', 'PBR', 'PDD', 'PEP', 'PFE', 'PG', 'PINS',
    'PLTR', 'PSX', 'PYPL', 'QCOM', 'QQQ', 'QQQM', 'RBLX', 'RGTI', 'RIO', 'RIOT',
    'RIVN', 'RKLB', 'ROKU', 'RTX', 'SATL', 'SBUX', 'SCHD', 'SE', 'SHOP', 'SHY',
    'SID', 'SLB', 'SLV', 'SMH', 'SNAP', 'SNDK', 'SNOW', 'SOFI', 'SOXL', 'SOXX',
    'SPCE', 'SPCX', 'SPGI', 'SPOT', 'SPY', 'SQ', 'SQQQ', 'STNE', 'T', 'TEAM', 'TGT',
    'TIP', 'TLT', 'TMF', 'TMO', 'TMUS', 'TQQQ', 'TRIP', 'TSLA', 'TSM', 'TTWO',
    'TWLO', 'TXN', 'U', 'UBER', 'UNG', 'UNH', 'UPRO', 'UPST', 'USO', 'V', 'VALE',
    'VEA', 'VIG', 'VIST', 'VOO', 'VST', 'VTI', 'VWO', 'VYM', 'VZ', 'WBD', 'WDAY',
    'WFC', 'WMT', 'XLB', 'XLC', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU',
    'XLV', 'XLY', 'XOM', 'XPEV', 'XYZ', 'ZM', 'ZS'
}

# Los CEDEARs de la pantalla (CEDEARS_LIST), TODOS. Hasta 2026-10-19 eran 119 de
# 168: el chat no podía registrar IREN, MSTR, MCD, NOW… y fuera_de_horario.py
# tenía su propia copia completa para tapar el hueco. Ahora esta es la única
# copia del servidor; tests/test_fuera_de_horario.py la compara con la pantalla.
CEDEAR_TICKERS = {
    'AAL', 'AAPL', 'ABBV', 'ABEV', 'ABNB', 'ACWI', 'ADBE', 'ALAB', 'AMC', 'AMD',
    'AMGN', 'AMZN', 'ANET', 'ARKK', 'ASML', 'ASTS', 'AVGO', 'AXP', 'AZN', 'BA',
    'BABA', 'BAC', 'BAK', 'BB', 'BBD', 'BIDU', 'BIOX', 'BLK', 'BMNR', 'BMY',
    'BRK-B', 'BRKB', 'C', 'CAT', 'CEG', 'COIN', 'COP', 'COPX', 'COST', 'CRM',
    'CRWD', 'CRWV', 'CSCO', 'CVX', 'DDOG', 'DE', 'DISN', 'DOCU', 'DOW', 'EA', 'EEM',
    'ETHA', 'EWY', 'EWZ', 'F', 'FXI', 'GE', 'GILD', 'GLD', 'GLOB', 'GM', 'GME',
    'GOOGL', 'GPRK', 'GS', 'HD', 'HIMS', 'HMY', 'HON', 'HOOD', 'HUT', 'IBIT', 'IBM',
    'INTC', 'IREN', 'ITUB', 'JD', 'JMIA', 'JNJ', 'JPM', 'KEEL', 'KO', 'LAC', 'LAR',
    'LLY', 'LMT', 'MA', 'MCD', 'MELI', 'META', 'MMM', 'MP', 'MRK', 'MRNA', 'MS',
    'MSFT', 'MSTR', 'MU', 'MUX', 'NBIS', 'NET', 'NFLX', 'NIO', 'NKE', 'NOKA', 'NOW',
    'NU', 'NVDA', 'NVO', 'NVS', 'O', 'OKLO', 'ONDS', 'ORCL', 'PAGS', 'PANW', 'PATH',
    'PBR', 'PDD', 'PEP', 'PFE', 'PINS', 'PLTR', 'PYPL', 'QCOM', 'QQQ', 'RGTI',
    'RIO', 'RIOT', 'RKLB', 'ROKU', 'RTX', 'SATL', 'SBUX', 'SE', 'SHOP', 'SID',
    'SNAP', 'SNDK', 'SNOW', 'SPCE', 'SPCX', 'SPOT', 'SPY', 'STNE', 'T', 'TGT',
    'TRIP', 'TSLA', 'TSM', 'TTWO', 'TWLO', 'UBER', 'UNH', 'URA', 'V', 'VALE', 'VIG',
    'VIST', 'VST', 'WFC', 'WMT', 'XLE', 'XLF', 'XLV', 'XOM', 'XYZ', 'ZM'
}

AR_STOCK_TICKERS = {
    'A3', 'AGRO', 'ALUA', 'AUSO', 'BBAR', 'BHIP', 'BMA', 'BOLT', 'BPAT', 'BYMA',
    'CADO', 'CAPU', 'CAPX', 'CARC', 'CECO2', 'CELU', 'CEPU', 'CGPA2', 'COME', 'CRES',
    'CTIO', 'CVH', 'DGCU2', 'DOME', 'DYCA', 'ECOG', 'EDN', 'FERR', 'FIPL', 'GBAN',
    'GCLA', 'GGAL', 'GRIM', 'HARG', 'HAVA', 'INAG', 'INVJ', 'IRCP', 'IRSA', 'LEDE',
    'LOMA', 'LONG', 'METR', 'MIRG', 'MOLA', 'MORI', 'OEST', 'PAMP', 'PATA',
    'POLL', 'RICH', 'ROSE', 'SAMI', 'SEMI', 'SUPV', 'TECO2', 'TGLT', 'TGNO4', 'TGSU2',
    'TRAN', 'TXAR', 'VALO', 'YPFD',
    'GARO', 'GCDI', 'MOLI',
}
# ☝️ Es LA lista de acciones argentinas del servidor: la usan también el
# diagnóstico de sesgo local y los sectores (behavioral.es_accion_argentina),
# el análisis de Mervall-E AI por país (ai/builders/insights), los grupos del
# asesor y el importador (la pata dólar GGALD → GGAL, importing/tickers_cd).
# Copia de frontend/src/utils/tickers.js (ARG_LIDER + ARG_GENERAL): las pruebas
# tests/test_lista_acciones_ar.py y frontend/src/utils/listaAccionesAr.test.js
# se ponen en rojo si se separan. Cada acción nueva necesita además su sector
# (behavioral._SECTOR_AR_PANTALLA y assetSector.js) y su nombre para la voz
# (ai/asset_names.py).

# Nombre común → ticker ("AMAZON" → AMZN). Ayuda de resolución; el guard real
# son los sets de arriba.
NAME_ALIASES = {
    'ABBVIE': 'ABBV',
    'ACCENTURE': 'ACN',
    'ADOBE': 'ADBE',
    'AFFIRM': 'AFRM',
    'AGROMETAL': 'AGRO',
    'AIRBNB': 'ABNB',
    'ALGORAND': 'ALGO',
    'ALIBABA': 'BABA',
    'ALPHABET': 'GOOGL',
    'ALUAR': 'ALUA',
    'AMAZON': 'AMZN',
    'AMBEV': 'ABEV',
    'AMGEN': 'AMGN',
    'APECOIN': 'APE',
    'APPLE': 'AAPL',
    'APTOS': 'APT',
    'ARBITRUM': 'ARB',
    'ARWEAVE': 'AR',
    'ASTRAZENECA': 'AZN',
    'AT&T': 'T',
    'ATLASSIAN': 'TEAM',
    'AUTODESK': 'ADSK',
    'AVALANCHE': 'AVAX',
    'BAIDU': 'BIDU',
    'BALANCER': 'BAL',
    'BANCO MACRO': 'BMA',
    'BERKSHIRE': 'BRK-B',
    'BIONTECH': 'BNTX',
    'BITCOIN': 'BTC',
    'BLACKBERRY': 'BB',
    'BLACKROCK': 'BLK',
    'BLACKSTONE': 'BX',
    'BLOCK': 'SQ',
    'BOEING': 'BA',
    'BOLDT': 'BOLT',
    'BRASIL': 'EWZ',
    'BRISTOL-MYERS': 'BMY',
    'BROADCOM': 'AVGO',
    'CAPEX': 'CAPU',
    'CAPUTO': 'CARC',
    'CARDANO': 'ADA',
    'CARVANA': 'CVNA',
    'CATERPILLAR': 'CAT',
    'CELESTIA': 'TIA',
    'CHAINLINK': 'LINK',
    'CHEVRON': 'CVX',
    'CHILIZ': 'CHZ',
    'CHIPOTLE': 'CMG',
    'CISCO': 'CSCO',
    'CITIGROUP': 'C',
    'CLOUDFLARE': 'NET',
    'COCA COLA': 'KO',
    'COCA-COLA': 'KO',
    'COINBASE': 'COIN',
    'COMCAST': 'CMCSA',
    'COMPOUND': 'COMP',
    'COMUNICACIONES': 'XLC',
    'CONFLUX': 'CFX',
    'CONOCOPHILLIPS': 'COP',
    'CONSULTATIO': 'CTIO',
    'COSMOS': 'ATOM',
    'COSTCO': 'COST',
    'CRESUD': 'CRES',
    'CROWDSTRIKE': 'CRWD',
    'DATADOG': 'DDOG',
    'DECENTRALAND': 'MANA',
    'DOCUSIGN': 'DOCU',
    'DOGECOIN': 'DOGE',
    'DOGWIFHAT': 'WIF',
    'DOMEC': 'DOME',
    'DOORDASH': 'DASH',
    'DYCASA': 'DYCA',
    'ECOGAS': 'ECOG',
    'EDENOR': 'EDN',
    'ENERGÍA': 'XLE',
    'ETHENA': 'ENA',
    'ETHEREUM': 'ETH',
    'FANTOM': 'FTM',
    'FERRUM': 'FERR',
    'FETCH.AI': 'FET',
    'FILECOIN': 'FIL',
    'FINANCIERO': 'XLF',
    'FIPLASTO': 'FIPL',
    'FORD': 'F',
    'GALICIA': 'GGAL',
    'GAMESTOP': 'GME',
    'GILEAD': 'GILD',
    'GRIMOLDI': 'GRIM',
    'HARMONY': 'ONE',
    'HAVANNA': 'HAVA',
    'HEDERA': 'HBAR',
    'HONEYWELL': 'HON',
    'IMMUTABLE': 'IMX',
    'INDUSTRIAL': 'XLI',
    'INJECTIVE': 'INJ',
    'INTEL': 'INTC',
    'INTUIT': 'INTU',
    'JASMYCOIN': 'JASMY',
    'JD.COM': 'JD',
    'JITO': 'JTO',
    'JPMORGAN': 'JPM',
    'JUPITER': 'JUP',
    'KASPA': 'KAS',
    'KUSAMA': 'KSM',
    'LEDESMA': 'LEDE',
    'LINDE': 'LIN',
    'LITECOIN': 'LTC',
    'LONGVIE': 'LONG',
    'MAKER': 'MKR',
    'MASTERCARD': 'MA',
    'MATERIALES': 'XLB',
    'MERCADO LIBRE': 'MELI',
    'MERCADOLIBRE': 'MELI',
    'MERCK': 'MRK',
    'METROGAS': 'METR',
    'MICRON': 'MU',
    'MICROSOFT': 'MSFT',
    'MIRGOR': 'MIRG',
    'MODERNA': 'MRNA',
    'MONDELEZ': 'MDLZ',
    'MONERO': 'XMR',
    'MONGODB': 'MDB',
    'MORIXE': 'MORI',
    'MULTIVERSX': 'EGLD',
    'NETFLIX': 'NFLX',
    'NIKE': 'NKE',
    'NOVARTIS': 'NVS',
    'NOVAVAX': 'NVAX',
    'NVIDIA': 'NVDA',
    'OPTIMISM': 'OP',
    'ORACLE': 'ORCL',
    'PALANTIR': 'PLTR',
    'PAMPA': 'PAMP',
    'PAYPAL': 'PYPL',
    'PEPSICO': 'PEP',
    'PETROBRAS': 'PBR',
    'PFIZER': 'PFE',
    'PINTEREST': 'PINS',
    'POLKADOT': 'DOT',
    'POLLEDO': 'POLL',
    'POLYGON': 'MATIC',
    'QUALCOMM': 'QCOM',
    'QUANT': 'QNT',
    'RENDER': 'RNDR',
    'RIVIAN': 'RIVN',
    'ROBINHOOD': 'HOOD',
    'ROBLOX': 'RBLX',
    'SALESFORCE': 'CRM',
    'SALUD': 'XLV',
    'SCHLUMBERGER': 'SLB',
    'SERVICENOW': 'NOW',
    'SHOPIFY': 'SHOP',
    'SINGULARITYNET': 'AGIX',
    'SNOWFLAKE': 'SNOW',
    'SOLANA': 'SOL',
    'SPACEX': 'SPCX',
    'SPOTIFY': 'SPOT',
    'STACKS': 'STX',
    'STARBUCKS': 'SBUX',
    'STARKNET': 'STRK',
    'STELLAR': 'XLM',
    'STEPN': 'GMT',
    'SUSHISWAP': 'SUSHI',
    'SYNTHETIX': 'SNX',
    'TAKE-TWO': 'TTWO',
    'TARGET': 'TGT',
    'TECNOLOGÍA': 'XLK',
    'TESLA': 'TSLA',
    'TETHER': 'USDT',
    'TEZOS': 'XTZ',
    'THORCHAIN': 'RUNE',
    'TONCOIN': 'TON',
    'TRANSENER': 'TRAN',
    'TRON': 'TRX',
    'TSMC': 'TSM',
    'TWILIO': 'TWLO',
    'UNISWAP': 'UNI',
    'UNITEDHEALTH': 'UNH',
    'UPSTART': 'UPST',
    'UTILITIES': 'XLU',
    'VECHAIN': 'VET',
    'VERIZON': 'VZ',
    'VISA': 'V',
    'WALMART': 'WMT',
    'WORKDAY': 'WDAY',
    'WORLDCOIN': 'WLD',
    'XPENG': 'XPEV',
    'YEARN.FINANCE': 'YFI',
    'YPF': 'YPFD',
    'ZCASH': 'ZEC',
    'ZILLIQA': 'ZIL',
    'ZOOM': 'ZM',
    'ZSCALER': 'ZS',
}


def resolve_asset(raw: str):
    """Normaliza el input del modelo a un ticker de la allowlist.
    Devuelve (ticker, kinds) donde kinds = set de tipos posibles
    ('CRYPTO'|'CEDEAR'|'STOCK'|'AR_STOCK') — si hay más de uno, hay que
    desambiguar. ((None, set()) si no está en ninguna lista)."""
    s = (raw or "").strip().upper()
    if not s:
        return None, set()
    s = NAME_ALIASES.get(s, s)
    # Nombres con espacios/puntos/guiones ("space x", "coca-cola"): probar la
    # versión compactada contra los aliases Y contra los tickers directos.
    if (s not in CRYPTO_TICKERS and s not in CEDEAR_TICKERS
            and s not in US_TICKERS and s not in AR_STOCK_TICKERS):
        import re as _re
        def _known(t):
            return (t in CRYPTO_TICKERS or t in CEDEAR_TICKERS
                    or t in US_TICKERS or t in AR_STOCK_TICKERS)
        compact = _re.sub(r"[\s.\-]+", "", s)      # "SPACE X" → "SPACEX"
        dashed = _re.sub(r"[\s.]+", "-", s)         # "BRK.B" → "BRK-B"
        # El guion va antes que lo compactado: "BRK.B" es BRK-B (acción y
        # CEDEAR), no BRKB (sólo la especie del CEDEAR en BYMA).
        for cand in (NAME_ALIASES.get(compact), dashed if _known(dashed) else None,
                     compact if _known(compact) else None):
            if cand:
                s = cand
                break
    kinds = set()
    if s in CRYPTO_TICKERS:
        kinds.add("CRYPTO")
    if s in CEDEAR_TICKERS:
        kinds.add("CEDEAR")
    if s in US_TICKERS:
        kinds.add("STOCK")
    if s in AR_STOCK_TICKERS:
        kinds.add("AR_STOCK")
    return (s if kinds else None), kinds
