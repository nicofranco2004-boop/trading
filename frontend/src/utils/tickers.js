// Base de datos de tickers con nombre estilo TradingView.
// Formato: { s: 'AAPL', n: 'Apple Inc.' }

// === CRIPTOMONEDAS (top ~120 por market cap) ===
export const CRYPTO = [
  { s: 'BTC', n: 'Bitcoin' }, { s: 'ETH', n: 'Ethereum' }, { s: 'USDT', n: 'Tether' },
  { s: 'BNB', n: 'BNB' }, { s: 'SOL', n: 'Solana' }, { s: 'XRP', n: 'XRP' },
  { s: 'USDC', n: 'USD Coin' }, { s: 'ADA', n: 'Cardano' }, { s: 'AVAX', n: 'Avalanche' },
  { s: 'DOGE', n: 'Dogecoin' }, { s: 'TRX', n: 'TRON' }, { s: 'DOT', n: 'Polkadot' },
  { s: 'MATIC', n: 'Polygon' }, { s: 'LINK', n: 'Chainlink' }, { s: 'TON', n: 'Toncoin' },
  { s: 'LTC', n: 'Litecoin' }, { s: 'BCH', n: 'Bitcoin Cash' }, { s: 'NEAR', n: 'NEAR Protocol' },
  { s: 'UNI', n: 'Uniswap' }, { s: 'ATOM', n: 'Cosmos' }, { s: 'XLM', n: 'Stellar' },
  { s: 'ETC', n: 'Ethereum Classic' }, { s: 'APT', n: 'Aptos' }, { s: 'ARB', n: 'Arbitrum' },
  { s: 'OP', n: 'Optimism' }, { s: 'AAVE', n: 'Aave' }, { s: 'MKR', n: 'Maker' },
  { s: 'CRV', n: 'Curve DAO' }, { s: 'COMP', n: 'Compound' }, { s: 'SUSHI', n: 'SushiSwap' },
  { s: 'GRT', n: 'The Graph' }, { s: 'FIL', n: 'Filecoin' }, { s: 'THETA', n: 'Theta Network' },
  { s: 'XTZ', n: 'Tezos' }, { s: 'ALGO', n: 'Algorand' }, { s: 'VET', n: 'VeChain' },
  { s: 'EGLD', n: 'MultiversX' }, { s: 'FTM', n: 'Fantom' }, { s: 'HBAR', n: 'Hedera' },
  { s: 'IMX', n: 'Immutable' }, { s: 'SAND', n: 'The Sandbox' }, { s: 'MANA', n: 'Decentraland' },
  { s: 'AXS', n: 'Axie Infinity' }, { s: 'SHIB', n: 'Shiba Inu' }, { s: 'PEPE', n: 'Pepe' },
  { s: 'BONK', n: 'Bonk' }, { s: 'WIF', n: 'dogwifhat' }, { s: 'FLOKI', n: 'Floki' },
  { s: 'DEGEN', n: 'Degen' }, { s: 'SUI', n: 'Sui' }, { s: 'SEI', n: 'Sei' },
  { s: 'TIA', n: 'Celestia' }, { s: 'INJ', n: 'Injective' }, { s: 'JTO', n: 'Jito' },
  { s: 'PYTH', n: 'Pyth Network' }, { s: 'STRK', n: 'Starknet' }, { s: 'WLD', n: 'Worldcoin' },
  { s: 'ORDI', n: 'ORDI' }, { s: 'RUNE', n: 'THORChain' }, { s: 'ZEC', n: 'Zcash' },
  { s: 'DASH', n: 'Dash' }, { s: 'XMR', n: 'Monero' }, { s: 'SNX', n: 'Synthetix' },
  { s: 'YFI', n: 'yearn.finance' }, { s: '1INCH', n: '1inch' }, { s: 'DYDX', n: 'dYdX' },
  { s: 'GMX', n: 'GMX' }, { s: 'LDO', n: 'Lido DAO' }, { s: 'RPL', n: 'Rocket Pool' },
  { s: 'JUP', n: 'Jupiter' }, { s: 'ENA', n: 'Ethena' }, { s: 'PENDLE', n: 'Pendle' },
  { s: 'BLUR', n: 'Blur' }, { s: 'GMT', n: 'STEPN' }, { s: 'APE', n: 'ApeCoin' },
  { s: 'ENS', n: 'Ethereum Name Service' }, { s: 'CHZ', n: 'Chiliz' }, { s: 'ICP', n: 'Internet Computer' },
  { s: 'KAS', n: 'Kaspa' }, { s: 'STX', n: 'Stacks' }, { s: 'ROSE', n: 'Oasis Network' },
  { s: 'KAVA', n: 'Kava' }, { s: 'ZIL', n: 'Zilliqa' }, { s: 'IOTA', n: 'IOTA' },
  { s: 'NEO', n: 'Neo' }, { s: 'WAVES', n: 'Waves' }, { s: 'BAT', n: 'Basic Attention Token' },
  { s: 'BAL', n: 'Balancer' }, { s: 'ZRX', n: '0x' }, { s: 'ANKR', n: 'Ankr' },
  { s: 'CELO', n: 'Celo' }, { s: 'ONE', n: 'Harmony' }, { s: 'QNT', n: 'Quant' },
  { s: 'GALA', n: 'Gala' }, { s: 'FLOW', n: 'Flow' }, { s: 'MINA', n: 'Mina' },
  { s: 'CFX', n: 'Conflux' }, { s: 'KSM', n: 'Kusama' }, { s: 'ENJ', n: 'Enjin Coin' },
  { s: 'FET', n: 'Fetch.ai' }, { s: 'AGIX', n: 'SingularityNET' }, { s: 'OCEAN', n: 'Ocean Protocol' },
  { s: 'RNDR', n: 'Render' }, { s: 'AR', n: 'Arweave' }, { s: 'JASMY', n: 'JasmyCoin' },
  { s: 'BOME', n: 'BOOK OF MEME' }, { s: 'POPCAT', n: 'Popcat' }, { s: 'MEW', n: 'cat in a dogs world' },
]

// === ACCIONES US (S&P 500 más relevantes + populares) ===
export const STOCKS_US = [
  // Mega caps
  { s: 'AAPL', n: 'Apple' }, { s: 'MSFT', n: 'Microsoft' }, { s: 'GOOGL', n: 'Alphabet (A)' },
  { s: 'GOOG', n: 'Alphabet (C)' }, { s: 'AMZN', n: 'Amazon' }, { s: 'META', n: 'Meta Platforms' },
  { s: 'NVDA', n: 'NVIDIA' }, { s: 'TSLA', n: 'Tesla' }, { s: 'BRK-B', n: 'Berkshire Hathaway' },
  { s: 'AVGO', n: 'Broadcom' }, { s: 'LLY', n: 'Eli Lilly' }, { s: 'JPM', n: 'JPMorgan Chase' },
  { s: 'V', n: 'Visa' }, { s: 'XOM', n: 'Exxon Mobil' }, { s: 'WMT', n: 'Walmart' },
  { s: 'UNH', n: 'UnitedHealth' }, { s: 'MA', n: 'Mastercard' }, { s: 'PG', n: 'Procter & Gamble' },
  { s: 'HD', n: 'Home Depot' }, { s: 'JNJ', n: 'Johnson & Johnson' }, { s: 'COST', n: 'Costco' },
  { s: 'ORCL', n: 'Oracle' }, { s: 'NFLX', n: 'Netflix' }, { s: 'BAC', n: 'Bank of America' },
  { s: 'ABBV', n: 'AbbVie' }, { s: 'KO', n: 'Coca-Cola' }, { s: 'CVX', n: 'Chevron' },
  { s: 'MRK', n: 'Merck' }, { s: 'ADBE', n: 'Adobe' }, { s: 'PEP', n: 'PepsiCo' },
  { s: 'CRM', n: 'Salesforce' }, { s: 'TMO', n: 'Thermo Fisher' }, { s: 'CSCO', n: 'Cisco' },
  { s: 'ACN', n: 'Accenture' }, { s: 'AMD', n: 'AMD' }, { s: 'LIN', n: 'Linde' },
  { s: 'MCD', n: "McDonald's" }, { s: 'ABT', n: 'Abbott Labs' }, { s: 'WFC', n: 'Wells Fargo' },
  { s: 'DIS', n: 'Walt Disney' }, { s: 'IBM', n: 'IBM' }, { s: 'INTC', n: 'Intel' },
  { s: 'QCOM', n: 'Qualcomm' }, { s: 'TXN', n: 'Texas Instruments' }, { s: 'GE', n: 'General Electric' },
  { s: 'CAT', n: 'Caterpillar' }, { s: 'DE', n: 'John Deere' }, { s: 'AXP', n: 'American Express' }, { s: 'PFE', n: 'Pfizer' },
  { s: 'GS', n: 'Goldman Sachs' }, { s: 'MS', n: 'Morgan Stanley' }, { s: 'NOW', n: 'ServiceNow' },
  { s: 'BLK', n: 'BlackRock' }, { s: 'AMGN', n: 'Amgen' }, { s: 'NKE', n: 'Nike' },
  { s: 'BKNG', n: 'Booking Holdings' }, { s: 'SPGI', n: 'S&P Global' }, { s: 'UBER', n: 'Uber' },
  { s: 'BX', n: 'Blackstone' }, { s: 'C', n: 'Citigroup' }, { s: 'GILD', n: 'Gilead Sciences' },
  { s: 'BSX', n: 'Boston Scientific' }, { s: 'PYPL', n: 'PayPal' }, { s: 'MU', n: 'Micron' },
  { s: 'INTU', n: 'Intuit' }, { s: 'AMAT', n: 'Applied Materials' }, { s: 'LRCX', n: 'Lam Research' },
  { s: 'KLAC', n: 'KLA Corp' }, { s: 'PANW', n: 'Palo Alto Networks' }, { s: 'CRWD', n: 'CrowdStrike' },
  { s: 'SNOW', n: 'Snowflake' }, { s: 'PLTR', n: 'Palantir' }, { s: 'COIN', n: 'Coinbase' },
  { s: 'SHOP', n: 'Shopify' }, { s: 'SQ', n: 'Block' }, { s: 'HOOD', n: 'Robinhood' },
  { s: 'SOFI', n: 'SoFi Technologies' }, { s: 'ABNB', n: 'Airbnb' }, { s: 'MELI', n: 'MercadoLibre' },
  { s: 'BABA', n: 'Alibaba' }, { s: 'JD', n: 'JD.com' }, { s: 'PDD', n: 'PDD Holdings' },
  { s: 'NIO', n: 'NIO' }, { s: 'LI', n: 'Li Auto' }, { s: 'XPEV', n: 'XPeng' },
  { s: 'RIVN', n: 'Rivian' }, { s: 'LCID', n: 'Lucid Group' }, { s: 'F', n: 'Ford' },
  { s: 'GM', n: 'General Motors' }, { s: 'BA', n: 'Boeing' }, { s: 'LMT', n: 'Lockheed Martin' },
  { s: 'RTX', n: 'RTX Corporation' }, { s: 'NOC', n: 'Northrop Grumman' }, { s: 'GD', n: 'General Dynamics' },
  { s: 'RKLB', n: 'Rocket Lab' }, { s: 'ASTS', n: 'AST SpaceMobile' }, { s: 'ANET', n: 'Arista Networks' },
  { s: 'SPCX', n: 'SpaceX' },
  { s: 'SBUX', n: 'Starbucks' }, { s: 'CMG', n: 'Chipotle' }, { s: 'MDLZ', n: 'Mondelez' },
  { s: 'ETSY', n: 'Etsy' }, { s: 'TGT', n: 'Target' }, { s: 'LOW', n: "Lowe's" },
  { s: 'DASH', n: 'DoorDash' }, { s: 'LYFT', n: 'Lyft' }, { s: 'ROKU', n: 'Roku' },
  { s: 'SNAP', n: 'Snap' }, { s: 'PINS', n: 'Pinterest' }, { s: 'SPOT', n: 'Spotify' },
  { s: 'EA', n: 'Electronic Arts' }, { s: 'TTWO', n: 'Take-Two Interactive' }, { s: 'RBLX', n: 'Roblox' },
  { s: 'U', n: 'Unity Software' }, { s: 'DDOG', n: 'Datadog' }, { s: 'NET', n: 'Cloudflare' },
  { s: 'ZS', n: 'Zscaler' }, { s: 'OKTA', n: 'Okta' }, { s: 'MDB', n: 'MongoDB' },
  { s: 'TWLO', n: 'Twilio' }, { s: 'DOCU', n: 'DocuSign' }, { s: 'ZM', n: 'Zoom' },
  { s: 'ASML', n: 'ASML Holding' }, { s: 'TSM', n: 'TSMC' }, { s: 'MRVL', n: 'Marvell Tech' },
  { s: 'ADSK', n: 'Autodesk' }, { s: 'WDAY', n: 'Workday' }, { s: 'TEAM', n: 'Atlassian' },
  { s: 'PBR', n: 'Petrobras' }, { s: 'VALE', n: 'Vale' }, { s: 'ITUB', n: 'Itaú Unibanco' },
  { s: 'NU', n: 'Nu Holdings' }, { s: 'ABEV', n: 'Ambev' }, { s: 'BBD', n: 'Banco Bradesco' },
  { s: 'AFRM', n: 'Affirm' }, { s: 'UPST', n: 'Upstart' }, { s: 'CVNA', n: 'Carvana' },
  { s: 'GME', n: 'GameStop' }, { s: 'AMC', n: 'AMC Entertainment' }, { s: 'BB', n: 'BlackBerry' },
  { s: 'MRNA', n: 'Moderna' }, { s: 'BNTX', n: 'BioNTech' }, { s: 'NVAX', n: 'Novavax' },
  { s: 'OXY', n: 'Occidental Petroleum' }, { s: 'SLB', n: 'Schlumberger' }, { s: 'COP', n: 'ConocoPhillips' },
  { s: 'EOG', n: 'EOG Resources' }, { s: 'PSX', n: 'Phillips 66' }, { s: 'MPC', n: 'Marathon Petroleum' },
  { s: 'VIST', n: 'Vista Energy' }, { s: 'VST', n: 'Vistra Energy' },
  { s: 'WBD', n: 'Warner Bros. Discovery' }, { s: 'PARA', n: 'Paramount Global' }, { s: 'T', n: 'AT&T' },
  { s: 'VZ', n: 'Verizon' }, { s: 'TMUS', n: 'T-Mobile US' }, { s: 'CMCSA', n: 'Comcast' },
]

// === ETFs POPULARES ===
export const ETFS = [
  { s: 'SPY', n: 'SPDR S&P 500' }, { s: 'VOO', n: 'Vanguard S&P 500' }, { s: 'IVV', n: 'iShares S&P 500' },
  { s: 'QQQ', n: 'Invesco QQQ (Nasdaq 100)' }, { s: 'QQQM', n: 'Invesco Nasdaq 100' },
  { s: 'DIA', n: 'SPDR Dow Jones' }, { s: 'IWM', n: 'iShares Russell 2000' },
  { s: 'VTI', n: 'Vanguard Total Stock Market' }, { s: 'VEA', n: 'Vanguard Developed Markets' },
  { s: 'VIG', n: 'Vanguard Dividend Appreciation' }, { s: 'VYM', n: 'Vanguard High Dividend Yield' }, { s: 'SCHD', n: 'Schwab US Dividend Equity' },
  { s: 'VWO', n: 'Vanguard Emerging Markets' }, { s: 'EEM', n: 'iShares Emerging Markets' },
  { s: 'EFA', n: 'iShares MSCI EAFE' }, { s: 'EWZ', n: 'iShares Brasil' },
  { s: 'ARGT', n: 'Global X Argentina' }, { s: 'MCHI', n: 'iShares China' },
  { s: 'INDA', n: 'iShares India' }, { s: 'EWJ', n: 'iShares Japón' },
  // Sectores
  { s: 'XLK', n: 'Tecnología (SPDR)' }, { s: 'XLF', n: 'Financiero (SPDR)' },
  { s: 'XLE', n: 'Energía (SPDR)' }, { s: 'XLV', n: 'Salud (SPDR)' },
  { s: 'XLI', n: 'Industrial (SPDR)' }, { s: 'XLY', n: 'Consumo Discrecional' },
  { s: 'XLP', n: 'Consumo Defensivo' }, { s: 'XLU', n: 'Utilities' },
  { s: 'XLRE', n: 'Real Estate' }, { s: 'XLB', n: 'Materiales' }, { s: 'XLC', n: 'Comunicaciones' },
  { s: 'SOXX', n: 'iShares Semiconductors' }, { s: 'SMH', n: 'VanEck Semiconductors' },
  { s: 'ARKK', n: 'ARK Innovation' }, { s: 'ARKG', n: 'ARK Genomic' },
  // Commodities / Renta fija
  { s: 'GLD', n: 'SPDR Gold' }, { s: 'IAU', n: 'iShares Gold' },
  { s: 'SLV', n: 'iShares Silver' }, { s: 'USO', n: 'United States Oil' },
  { s: 'UNG', n: 'United States Natural Gas' }, { s: 'DBC', n: 'Invesco Commodity' },
  { s: 'TLT', n: 'iShares 20+Y Treasury' }, { s: 'IEF', n: 'iShares 7-10Y Treasury' },
  { s: 'SHY', n: 'iShares 1-3Y Treasury' }, { s: 'HYG', n: 'iShares High Yield' },
  { s: 'LQD', n: 'iShares Investment Grade' }, { s: 'AGG', n: 'iShares Aggregate Bond' },
  // Cripto ETFs
  { s: 'IBIT', n: 'iShares Bitcoin Trust' }, { s: 'FBTC', n: 'Fidelity Bitcoin' },
  { s: 'GBTC', n: 'Grayscale Bitcoin' }, { s: 'ETHE', n: 'Grayscale Ethereum' },
  // Apalancados / Inversos
  { s: 'TQQQ', n: 'ProShares 3x Nasdaq' }, { s: 'SQQQ', n: 'ProShares -3x Nasdaq' },
  { s: 'UPRO', n: 'ProShares 3x S&P 500' }, { s: 'SOXL', n: 'Direxion 3x Semis' },
  { s: 'TMF', n: 'Direxion 3x Treasury' },
]

// === ÍNDICES ===
export const INDICES = [
  { s: 'SPX', n: 'S&P 500' }, { s: 'NDX', n: 'Nasdaq 100' },
  { s: 'DJI', n: 'Dow Jones Industrial' }, { s: 'RUT', n: 'Russell 2000' },
  { s: 'VIX', n: 'CBOE Volatility Index' }, { s: 'NYA', n: 'NYSE Composite' },
  { s: 'COMP', n: 'Nasdaq Composite' },
  // Internacionales
  { s: 'DAX', n: 'DAX (Alemania)' }, { s: 'FTSE', n: 'FTSE 100 (Reino Unido)' },
  { s: 'CAC', n: 'CAC 40 (Francia)' }, { s: 'IBEX', n: 'IBEX 35 (España)' },
  { s: 'STOXX50', n: 'Euro Stoxx 50' }, { s: 'N225', n: 'Nikkei 225 (Japón)' },
  { s: 'HSI', n: 'Hang Seng (Hong Kong)' }, { s: 'SSEC', n: 'Shanghai Composite' },
  { s: 'KOSPI', n: 'KOSPI (Corea)' }, { s: 'BSESN', n: 'BSE Sensex (India)' },
  { s: 'BVSP', n: 'Bovespa (Brasil)' }, { s: 'MERVAL', n: 'S&P MERVAL (Argentina)' },
  { s: 'MXX', n: 'IPC México' },
  // Futuros
  { s: 'ES1!', n: 'E-mini S&P 500 Futuros' }, { s: 'NQ1!', n: 'E-mini Nasdaq Futuros' },
  { s: 'YM1!', n: 'E-mini Dow Futuros' }, { s: 'RTY1!', n: 'E-mini Russell Futuros' },
  // Forex / commodities como indicador
  { s: 'DXY', n: 'Dollar Index' }, { s: 'GOLD', n: 'Oro (spot)' },
  { s: 'SILVER', n: 'Plata (spot)' }, { s: 'WTI', n: 'Petróleo WTI' },
  { s: 'BRENT', n: 'Petróleo Brent' }, { s: 'NATGAS', n: 'Gas Natural' },
]

// === CEDEARs (acciones extranjeras en Argentina) ===
export const CEDEARS_LIST = [
  { s: 'AAPL', n: 'Apple' }, { s: 'MSFT', n: 'Microsoft' }, { s: 'GOOGL', n: 'Alphabet' },
  { s: 'AMZN', n: 'Amazon' }, { s: 'META', n: 'Meta Platforms' }, { s: 'NVDA', n: 'NVIDIA' },
  { s: 'TSLA', n: 'Tesla' }, { s: 'NFLX', n: 'Netflix' }, { s: 'ADBE', n: 'Adobe' },
  { s: 'AMD', n: 'AMD' }, { s: 'INTC', n: 'Intel' }, { s: 'QCOM', n: 'Qualcomm' }, { s: 'MU', n: 'Micron Technology' },
  { s: 'AVGO', n: 'Broadcom' }, { s: 'ORCL', n: 'Oracle' }, { s: 'IBM', n: 'IBM' },
  { s: 'CSCO', n: 'Cisco' }, { s: 'CRM', n: 'Salesforce' }, { s: 'PYPL', n: 'PayPal' },
  { s: 'V', n: 'Visa' }, { s: 'MA', n: 'Mastercard' }, { s: 'JPM', n: 'JPMorgan' },
  { s: 'BAC', n: 'Bank of America' }, { s: 'GS', n: 'Goldman Sachs' }, { s: 'MS', n: 'Morgan Stanley' },
  { s: 'C', n: 'Citigroup' }, { s: 'WFC', n: 'Wells Fargo' }, { s: 'BLK', n: 'BlackRock' },
  { s: 'AXP', n: 'American Express' }, { s: 'KO', n: 'Coca-Cola' }, { s: 'PEP', n: 'PepsiCo' },
  { s: 'MCD', n: "McDonald's" }, { s: 'SBUX', n: 'Starbucks' }, { s: 'NKE', n: 'Nike' },
  { s: 'WMT', n: 'Walmart' }, { s: 'COST', n: 'Costco' }, { s: 'HD', n: 'Home Depot' },
  { s: 'TGT', n: 'Target' }, { s: 'DISN', n: 'Walt Disney' }, { s: 'JNJ', n: 'Johnson & Johnson' },
  { s: 'PFE', n: 'Pfizer' }, { s: 'MRK', n: 'Merck' }, { s: 'ABBV', n: 'AbbVie' },
  { s: 'LLY', n: 'Eli Lilly' }, { s: 'BMY', n: 'Bristol-Myers' }, { s: 'GILD', n: 'Gilead' },
  { s: 'AMGN', n: 'Amgen' }, { s: 'MRNA', n: 'Moderna' }, { s: 'XOM', n: 'Exxon Mobil' },
  { s: 'CVX', n: 'Chevron' }, { s: 'COP', n: 'ConocoPhillips' }, { s: 'VIST', n: 'Vista Energy' }, { s: 'VST', n: 'Vistra Energy' }, { s: 'BA', n: 'Boeing' },
  { s: 'CAT', n: 'Caterpillar' }, { s: 'DE', n: 'John Deere' }, { s: 'GE', n: 'General Electric' }, { s: 'F', n: 'Ford' },
  { s: 'HON', n: 'Honeywell' }, { s: 'MMM', n: '3M' }, { s: 'UNH', n: 'UnitedHealth' }, { s: 'LMT', n: 'Lockheed Martin' }, { s: 'RTX', n: 'RTX (Raytheon)' },
  { s: 'GM', n: 'General Motors' }, { s: 'UBER', n: 'Uber' }, { s: 'ABNB', n: 'Airbnb' },
  { s: 'SHOP', n: 'Shopify' }, { s: 'XYZ', n: 'Block (ex-Square)' }, { s: 'COIN', n: 'Coinbase' },
  { s: 'HOOD', n: 'Robinhood' }, { s: 'RKLB', n: 'Rocket Lab' }, { s: 'ASTS', n: 'AST SpaceMobile' }, { s: 'ANET', n: 'Arista Networks' },
  { s: 'SPCX', n: 'SpaceX' },
  { s: 'PLTR', n: 'Palantir' }, { s: 'SNOW', n: 'Snowflake' }, { s: 'PANW', n: 'Palo Alto' },
  { s: 'CRWD', n: 'CrowdStrike' }, { s: 'NET', n: 'Cloudflare' }, { s: 'DDOG', n: 'Datadog' },
  { s: 'DOCU', n: 'DocuSign' }, { s: 'ZM', n: 'Zoom' }, { s: 'TWLO', n: 'Twilio' },
  { s: 'SPOT', n: 'Spotify' }, { s: 'ROKU', n: 'Roku' }, { s: 'SNAP', n: 'Snap' },
  { s: 'PINS', n: 'Pinterest' }, { s: 'EA', n: 'Electronic Arts' }, { s: 'TTWO', n: 'Take-Two' },
  { s: 'GME', n: 'GameStop' }, { s: 'AMC', n: 'AMC' }, { s: 'BB', n: 'BlackBerry' },
  { s: 'TSM', n: 'TSMC' }, { s: 'BABA', n: 'Alibaba' }, { s: 'JD', n: 'JD.com' },
  { s: 'PDD', n: 'PDD Holdings' }, { s: 'NIO', n: 'NIO' }, { s: 'BIDU', n: 'Baidu' },
  { s: 'MELI', n: 'MercadoLibre' }, { s: 'PBR', n: 'Petrobras' }, { s: 'VALE', n: 'Vale' },
  { s: 'ITUB', n: 'Itaú Unibanco' }, { s: 'BBD', n: 'Banco Bradesco' }, { s: 'NU', n: 'Nu Holdings' },
  { s: 'SID', n: 'Companhia Siderúrgica Nacional' },
  { s: 'ABEV', n: 'Ambev' }, { s: 'AZN', n: 'AstraZeneca' }, { s: 'NVS', n: 'Novartis' }, { s: 'T', n: 'AT&T' },
  { s: 'BRK-B', n: 'Berkshire Hathaway' }, { s: 'OKLO', n: 'Oklo' },
  // ETFs disponibles como CEDEAR
  { s: 'SPY', n: 'SPDR S&P 500 (CEDEAR)' }, { s: 'QQQ', n: 'Nasdaq 100 (CEDEAR)' },
  { s: 'EEM', n: 'Emerging Markets (CEDEAR)' }, { s: 'EWZ', n: 'Brasil (CEDEAR)' },
  { s: 'ARKK', n: 'ARK Innovation (CEDEAR)' }, { s: 'XLE', n: 'Energía (CEDEAR)' },
  { s: 'XLF', n: 'Financiero (CEDEAR)' }, { s: 'GLD', n: 'Oro (CEDEAR)' },
  { s: 'XLV', n: 'Salud (CEDEAR)' }, { s: 'IBIT', n: 'iShares Bitcoin (CEDEAR)' },
  { s: 'VIG', n: 'Vanguard Dividend Appreciation (CEDEAR)' },
]

// CEDEARS_LIST en el shape del buscador (SearchBar/MobileSearch). El símbolo lleva
// '.BA' (el CEDEAR cotiza en BYMA). Se agrega al universo de búsqueda por query para
// que TODOS los CEDEARs del allowlist sean encontrables (no solo el subset de
// POPULAR_TICKERS). Nombres que ya traen '(CEDEAR)' (ETFs) no se duplican.
export const CEDEAR_SEARCH = CEDEARS_LIST.map(x => ({
  symbol: `${x.s}.BA`,
  name: /\(CEDEAR\)/.test(x.n) ? x.n : `${x.n} (CEDEAR)`,
  exchange: 'BCBA',
  type: 'cedear',
}))

// === ACCIONES ARGENTINAS — Panel Líder ===
export const ARG_LIDER = [
  { s: 'GGAL', n: 'Grupo Financiero Galicia' }, { s: 'BMA', n: 'Banco Macro' },
  { s: 'YPFD', n: 'YPF' }, { s: 'PAMP', n: 'Pampa Energía' },
  { s: 'TECO2', n: 'Telecom Argentina' }, { s: 'TXAR', n: 'Ternium Argentina' },
  { s: 'ALUA', n: 'Aluar' }, { s: 'BYMA', n: 'Bolsas y Mercados Argentinos' },
  { s: 'CEPU', n: 'Central Puerto' }, { s: 'CRES', n: 'Cresud' },
  { s: 'TGNO4', n: 'Transportadora Gas del Norte' }, { s: 'TGSU2', n: 'Transportadora Gas del Sur' },
  { s: 'SUPV', n: 'Grupo Supervielle' }, { s: 'EDN', n: 'Edenor' },
  { s: 'LOMA', n: 'Loma Negra' }, { s: 'VALO', n: 'Grupo Financiero Valores' },
  { s: 'MIRG', n: 'Mirgor' }, { s: 'BPAT', n: 'Banco Patagonia' },
  { s: 'IRSA', n: 'IRSA Inversiones' }, { s: 'COME', n: 'Sociedad Comercial del Plata' },
  { s: 'TRAN', n: 'Transener' }, { s: 'METR', n: 'MetroGas' },
  { s: 'BBAR', n: 'BBVA Argentina' }, { s: 'CVH', n: 'Cablevisión Holding' },
  { s: 'HARG', n: 'Holcim Argentina' },
]

// === ACCIONES ARGENTINAS — Panel General ===
export const ARG_GENERAL = [
  { s: 'AGRO', n: 'Agrometal' }, { s: 'AUSO', n: 'Autopistas del Sol' },
  { s: 'BHIP', n: 'Banco Hipotecario' }, { s: 'BOLT', n: 'Boldt' },
  { s: 'CADO', n: 'Carlos Casado' }, { s: 'CAPU', n: 'Capex' },
  { s: 'CAPX', n: 'Capex' }, { s: 'CARC', n: 'Caputo' },
  { s: 'CECO2', n: 'Central Costanera' }, { s: 'CELU', n: 'Celulosa Argentina' },
  { s: 'CGPA2', n: 'Camuzzi Gas Pampeana' }, { s: 'CTIO', n: 'Consultatio' },
  { s: 'DGCU2', n: 'Distribuidora Gas Cuyana' }, { s: 'DOME', n: 'Domec' },
  { s: 'DYCA', n: 'Dycasa' }, { s: 'FERR', n: 'Ferrum' },
  { s: 'FIPL', n: 'Fiplasto' }, { s: 'GBAN', n: 'Gas Natural BAN' },
  { s: 'GCLA', n: 'Grupo Clarín' }, { s: 'GRIM', n: 'Grimoldi' },
  { s: 'HAVA', n: 'Havanna' }, { s: 'INAG', n: 'Insumos Agroquímicos' },
  { s: 'INVJ', n: 'Inversora Juramento' }, { s: 'IRCP', n: 'IRSA Propiedades' },
  { s: 'LEDE', n: 'Ledesma' }, { s: 'LONG', n: 'Longvie' },
  { s: 'MOLA', n: 'Molinos Agro' }, { s: 'MORI', n: 'Morixe' },
  { s: 'OEST', n: 'Oeste Grupo Concesionario' }, { s: 'PATA', n: 'Importadora Patagonia' },
  { s: 'PCAR', n: 'Petrolera Pampa' }, { s: 'POLL', n: 'Polledo' },
  { s: 'RICH', n: 'Laboratorios Richmond' }, { s: 'ROSE', n: 'Instituto Rosenbusch' },
  { s: 'SAMI', n: 'San Miguel' }, { s: 'SEMI', n: 'Molinos Juan Semino' },
  { s: 'TGLT', n: 'TGLT' },
  { s: 'ECOG', n: 'Ecogas' }, { s: 'A3', n: 'A3 Mercados' },
]

// Acciones argentinas (panel líder + general) en el shape del buscador. Símbolo
// PELADO (el precio se pide como '<TICKER>.BA' vía priceSymbol/ARG_STOCK_TICKERS).
// Se suma al universo de búsqueda por query para que TODAS las acciones AR del
// allowlist sean encontrables (no solo el subset de POPULAR_TICKERS).
export const AR_STOCK_SEARCH = [...ARG_LIDER, ...ARG_GENERAL].map(x => ({
  symbol: x.s,
  name: x.n,
  exchange: 'BCBA',
  type: 'stock_ar',
}))

// Acciones US + ETFs US en el shape del buscador (símbolo pelado, cotiza en EE.UU.).
// Se suma al universo de búsqueda por query para que TODO el allowlist US sea
// encontrable (no solo el subset de POPULAR_TICKERS) — ej. VIG/VYM/SCHD que están
// en ETFS pero no en POPULAR_TICKERS no aparecían para agregar a la watchlist.
export const US_SEARCH = [
  ...STOCKS_US.map(x => ({ symbol: x.s, name: x.n, exchange: 'NASDAQ', type: 'stock_us' })),
  ...ETFS.map(x => ({ symbol: x.s, name: x.n, exchange: 'NYSE', type: 'etf' })),
]

// === BONOS — Soberanos AR en USD ============================================
// Los AL son ley local, los GD ley extranjera (NY/UK). AE = ley local variantes.
// Los sufijos C/D = USD nominal (vs los normales que se operan en pesos al TC).
export const BONDS_AR_SOV_USD = [
  { s: 'AL29', n: 'Argentina 2029 (USD ley local)' },
  { s: 'AL30', n: 'Argentina 2030 (USD ley local)' },
  { s: 'AL35', n: 'Argentina 2035 (USD ley local)' },
  { s: 'AE38', n: 'Argentina 2038 (USD ley local)' },
  { s: 'AL41', n: 'Argentina 2041 (USD ley local)' },
  { s: 'GD29', n: 'Argentina 2029 (USD ley extranjera)' },
  { s: 'GD30', n: 'Argentina 2030 (USD ley extranjera)' },
  { s: 'GD35', n: 'Argentina 2035 (USD ley extranjera)' },
  { s: 'GD38', n: 'Argentina 2038 (USD ley extranjera)' },
  { s: 'GD41', n: 'Argentina 2041 (USD ley extranjera)' },
  { s: 'GD46', n: 'Argentina 2046 (USD ley extranjera)' },
  // Sub-soberano provincial (precio live en data912):
  { s: 'BA37D', n: 'Buenos Aires 2037 (Prov., USD ley NY)' },
  // BOPREAL (BCRA, USD). El Serie 3 (BPY26) venció 31/05/26 → no tiene precio
  // live en data912 (delisteado): se carga y valúa a costo.
  { s: 'BPY26', n: 'BOPREAL Serie 3 2026 (BCRA, USD)' },
  // BOPREAL Serie 1 — strips A/B/C/D (precio live en data912; ya reconocidos en
  // AR_BONDS_DATA912). BPOB7 reportado por user 2026-07-10.
  { s: 'BPOA7', n: 'BOPREAL Serie 1-A (BCRA, USD)' }, { s: 'BPOB7', n: 'BOPREAL Serie 1-B (BCRA, USD)' },
  { s: 'BPOC7', n: 'BOPREAL Serie 1-C (BCRA, USD)' }, { s: 'BPOD7', n: 'BOPREAL Serie 1-D (BCRA, USD)' },
]

// === BONOS — Soberanos AR en pesos / CER ====================================
// Bonos del Tesoro AR que ajustan por CER (inflación) o son a tasa fija ARS.
export const BONDS_AR_CER = [
  { s: 'TX26', n: 'Bonos CER 2026 (TX26)' },
  { s: 'TX28', n: 'Bonos CER 2028 (TX28)' },
  { s: 'T2X5', n: 'Bonos CER 2025 (T2X5)' },
  { s: 'TZX26', n: 'Bonos Cero-Cupón CER 2026 (TZX26)' },
  { s: 'TZX27', n: 'Bonos Cero-Cupón CER 2027 (TZX27)' },
  { s: 'TZX28', n: 'Bonos Cero-Cupón CER 2028 (TZX28)' },
]

// === BONOS — Obligaciones Negociables (ONs) AR ==============================
// Bonos corporativos argentinos en USD. Si tu ON no está, agregala con su
// meta-data en bondMeta.js o usá el flujo de bono custom (Fase 2).
export const BONDS_AR_ONS = [
  { s: 'YCA0O', n: 'YPF Clase XXIII Garantizada 2026' },
  { s: 'YCAMO', n: 'YPF Clase XXVII 2026' },
  { s: 'YCAQO', n: 'YPF Clase IX 2031' },
  { s: 'YMCFO', n: 'YPF Clase XXXIX 2028' },
  { s: 'TLC1O', n: 'Telecom Argentina 2026' },
  { s: 'TLC5O', n: 'Telecom Argentina 2031' },
  { s: 'PMCAO', n: 'Pampa Energía 2027' },
  { s: 'PMCJO', n: 'Pampa Energía 2029' },
  { s: 'MGC1O', n: 'Mastellone Hnos. 2026' },
  { s: 'IRC1O', n: 'IRSA 2028' },
  { s: 'IRC9O', n: 'IRSA Propiedades 2030' },
  { s: 'GNCAO', n: 'Genneia 2027' },
  { s: 'DNC1O', n: 'Edenor 2030' },
  { s: 'CGCDO', n: 'CGC 2025' },
  { s: 'TGN1O', n: 'TGN 2025' },
  { s: 'CSC1O', n: 'Capex 2026' },
]

// === BONOS — ETFs de bonos US ===============================================
// ETFs con bonos como underlying. Tienen logo real en FMP y se valúan
// directo en USD. Conceptualmente se tratan como bonos diversificados.
export const BONDS_US_ETF = [
  { s: 'TLT', n: 'iShares 20+ Year Treasury Bond ETF' },
  { s: 'IEF', n: 'iShares 7-10 Year Treasury Bond ETF' },
  { s: 'SHY', n: 'iShares 1-3 Year Treasury Bond ETF' },
  { s: 'AGG', n: 'iShares Core US Aggregate Bond ETF' },
  { s: 'BND', n: 'Vanguard Total Bond Market ETF' },
  { s: 'LQD', n: 'iShares iBoxx $ Investment Grade Corporate Bond ETF' },
  { s: 'HYG', n: 'iShares iBoxx $ High Yield Corporate Bond ETF' },
  { s: 'TIP', n: 'iShares TIPS Bond ETF' },
]

// Para autocomplete simple (compat retro). Incluye bonos AR en ARS_TICKERS
// (porque se operan en brokers AR) y ETFs US bond en USDT_TICKERS.
const sym = arr => arr.map(x => x.s)
export const ARS_TICKERS = [...new Set([
  ...sym(CEDEARS_LIST), ...sym(ARG_LIDER), ...sym(ARG_GENERAL),
  ...sym(BONDS_AR_SOV_USD), ...sym(BONDS_AR_CER), ...sym(BONDS_AR_ONS),
])].sort()
export const USDT_TICKERS = [...new Set([
  ...sym(CRYPTO), ...sym(STOCKS_US), ...sym(ETFS), ...sym(BONDS_US_ETF),
])].sort()

// Set rápido de tickers que son bonos (de cualquier subcategoría)
export const BOND_TICKERS = new Set([
  ...sym(BONDS_AR_SOV_USD), ...sym(BONDS_AR_CER),
  ...sym(BONDS_AR_ONS), ...sym(BONDS_US_ETF),
])

// Acciones argentinas (panel líder + general): son instrumentos de BYMA que se
// valúan SIEMPRE por su precio LOCAL .BA (no tienen ticker US propio — la ADR
// usa otro símbolo, ej YPF vs YPFD). Set para que priceSymbol les ponga el sufijo
// .BA aunque vivan en un broker USD (compra dólar-MEP) que no se reconoce como AR.
export const ARG_STOCK_TICKERS = new Set([...sym(ARG_LIDER), ...sym(ARG_GENERAL)])

// CEDEARs reconocidos (el símbolo del allowlist ES el ticker US del subyacente:
// AAPL, MSFT, MELI…). Set para gatear qué tenencias de un broker AR/BYMA tienen
// fundamentals CONFIABLES en yfinance: solo un CEDEAR mapea a una empresa US real
// por su MISMO símbolo. Una acción local o una especie dólar-MEP (ej. 'SID') NO →
// evita analizar una homónima yanqui al azar. Ver holdingHasReliableFundamentals.
export const CEDEAR_TICKERS = new Set(sym(CEDEARS_LIST))

// Alias de especie de CEDEAR: algunos CEDEARs cotizan su especie en PESOS con un
// código propio distinto del ticker US real (que es la especie dólar-MEP). Mapea
// la especie-pesos → el ticker canónico (US) para reconocer/analizar/agrupar como
// UNA sola empresa. Ej: el CEDEAR de Companhia Siderúrgica Nacional cotiza 'SI'
// (pesos) y 'SID' (dólar-MEP); 'SID' ES el ticker NYSE real → canónico. Solo se
// aplica en contexto AR/BYMA (en un broker US 'SI' es otra empresa real).
export const CEDEAR_ESPECIE_ALIAS = { SI: 'SID' }

// Ticker canónico de un CEDEAR: upper + sin '.BA' + alias de especie-pesos.
export function cedearEspecieBase(asset) {
  const t = (asset || '').toUpperCase().replace(/\.BA$/, '')
  return CEDEAR_ESPECIE_ALIAS[t] || t
}

// Helper para encontrar nombre de un ticker (incluye bonos)
export function tickerName(s) {
  const all = [
    ...CRYPTO, ...STOCKS_US, ...ETFS, ...INDICES,
    ...CEDEARS_LIST, ...ARG_LIDER, ...ARG_GENERAL,
    ...BONDS_AR_SOV_USD, ...BONDS_AR_CER, ...BONDS_AR_ONS, ...BONDS_US_ETF,
  ]
  return all.find(x => x.s === s)?.n || null
}

// Helper: dado un ticker, devuelve true si es un bono.
export function isBondTicker(s) {
  return BOND_TICKERS.has((s || '').toUpperCase())
}

// Igual que isBondTicker pero también cubre bonos/ONs importados con asset_type='BOND'
// que no estén en el catálogo estático (p.ej. OT42 cargado vía Cocos o entrada libre).
export function isBondPosition(p) {
  return isBondTicker(p?.asset) || p?.asset_type === 'BOND'
}

// ─── Universo curado para autocomplete (tipo TradingView) ────────────────────
// `type` ∈ stock_us | stock_ar | cedear | bond | crypto | etf.
// Antes vivía en components/home/SearchBar.jsx; centralizado acá para que
// otras features (Fundamentals, etc.) lo reusen sin importar el modal SearchBar.
// SearchBar.jsx re-exporta POPULAR_TICKERS / inferType desde acá para no romper
// imports existentes.
export const POPULAR_TICKERS = [
  // Acciones US (blue chips + tech)
  { symbol: 'AAPL',  name: 'Apple',                   exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'MSFT',  name: 'Microsoft',               exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'NVDA',  name: 'NVIDIA',                  exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'GOOGL', name: 'Alphabet',                exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'AMZN',  name: 'Amazon',                  exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'META',  name: 'Meta',                    exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'TSLA',  name: 'Tesla',                   exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'AMD',   name: 'Advanced Micro Devices',  exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'AVGO',  name: 'Broadcom',                exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'TSM',   name: 'Taiwan Semiconductor',    exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'NFLX',  name: 'Netflix',                 exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'JPM',   name: 'JPMorgan',                exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'V',     name: 'Visa',                    exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'MA',    name: 'Mastercard',              exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'WMT',   name: 'Walmart',                 exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'KO',    name: 'Coca-Cola',               exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'PEP',   name: 'PepsiCo',                 exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'XOM',   name: 'ExxonMobil',              exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'BRK-B', name: 'Berkshire Hathaway',      exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'MELI',  name: 'MercadoLibre',            exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'GLOB',  name: 'Globant',                 exchange: 'NYSE',   type: 'stock_us' },

  // Acciones argentinas (Merval / panel líder)
  { symbol: 'GGAL',  name: 'Grupo Financiero Galicia', exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'YPFD',  name: 'YPF',                       exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'BMA',   name: 'Banco Macro',               exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'PAMP',  name: 'Pampa Energía',             exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'TEN',   name: 'Ternium Argentina',         exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'CRES',  name: 'Cresud',                    exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'COME',  name: 'Sociedad Comercial del Plata', exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'ALUA',  name: 'Aluar',                     exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'ERAR',  name: 'Ternium (Siderar)',         exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'MIRG',  name: 'Mirgor',                    exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'CEPU',  name: 'Central Puerto',            exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'EDN',   name: 'Edenor',                    exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'TGSU2', name: 'Transportadora Gas del Sur', exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'BBAR',  name: 'BBVA Argentina',            exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'TRAN',  name: 'Transener',                 exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'SUPV',  name: 'Banco Supervielle',         exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'BYMA',  name: 'Bolsas y Mercados Argentinos', exchange: 'BCBA', type: 'stock_ar' },
  { symbol: 'VALO',  name: 'Grupo Financiero Valores',  exchange: 'BCBA', type: 'stock_ar' },

  // CEDEARs (acciones US listadas en BCBA, sufijo .BA)
  { symbol: 'AAPL.BA',  name: 'Apple (CEDEAR)',        exchange: 'BCBA', type: 'cedear' },
  { symbol: 'MSFT.BA',  name: 'Microsoft (CEDEAR)',    exchange: 'BCBA', type: 'cedear' },
  { symbol: 'NVDA.BA',  name: 'NVIDIA (CEDEAR)',       exchange: 'BCBA', type: 'cedear' },
  { symbol: 'AMZN.BA',  name: 'Amazon (CEDEAR)',       exchange: 'BCBA', type: 'cedear' },
  { symbol: 'GOOGL.BA', name: 'Alphabet (CEDEAR)',     exchange: 'BCBA', type: 'cedear' },
  { symbol: 'META.BA',  name: 'Meta (CEDEAR)',         exchange: 'BCBA', type: 'cedear' },
  { symbol: 'TSLA.BA',  name: 'Tesla (CEDEAR)',        exchange: 'BCBA', type: 'cedear' },
  { symbol: 'AMD.BA',   name: 'AMD (CEDEAR)',          exchange: 'BCBA', type: 'cedear' },
  { symbol: 'KO.BA',    name: 'Coca-Cola (CEDEAR)',    exchange: 'BCBA', type: 'cedear' },
  { symbol: 'JPM.BA',   name: 'JPMorgan (CEDEAR)',     exchange: 'BCBA', type: 'cedear' },
  { symbol: 'V.BA',     name: 'Visa (CEDEAR)',         exchange: 'BCBA', type: 'cedear' },
  { symbol: 'MELI.BA',  name: 'MercadoLibre (CEDEAR)', exchange: 'BCBA', type: 'cedear' },
  { symbol: 'BABA.BA',  name: 'Alibaba (CEDEAR)',      exchange: 'BCBA', type: 'cedear' },
  { symbol: 'DISN.BA',  name: 'Disney (CEDEAR)',       exchange: 'BCBA', type: 'cedear' },
  { symbol: 'BA.BA',    name: 'Boeing (CEDEAR)',       exchange: 'BCBA', type: 'cedear' },
  { symbol: 'PFE.BA',   name: 'Pfizer (CEDEAR)',       exchange: 'BCBA', type: 'cedear' },

  // Bonos soberanos AR (USD ley NY + ARS CER)
  { symbol: 'AL29',  name: 'Bonar 2029 (USD ley AR)',   exchange: 'BCBA', type: 'bond' },
  { symbol: 'AL30',  name: 'Bonar 2030 (USD ley AR)',   exchange: 'BCBA', type: 'bond' },
  { symbol: 'AL35',  name: 'Bonar 2035 (USD ley AR)',   exchange: 'BCBA', type: 'bond' },
  { symbol: 'AE38',  name: 'Bonar 2038 (USD ley AR)',   exchange: 'BCBA', type: 'bond' },
  { symbol: 'AL41',  name: 'Bonar 2041 (USD ley AR)',   exchange: 'BCBA', type: 'bond' },
  { symbol: 'GD29',  name: 'Global 2029 (USD ley NY)',  exchange: 'BCBA', type: 'bond' },
  { symbol: 'GD30',  name: 'Global 2030 (USD ley NY)',  exchange: 'BCBA', type: 'bond' },
  { symbol: 'GD35',  name: 'Global 2035 (USD ley NY)',  exchange: 'BCBA', type: 'bond' },
  { symbol: 'GD38',  name: 'Global 2038 (USD ley NY)',  exchange: 'BCBA', type: 'bond' },
  { symbol: 'GD41',  name: 'Global 2041 (USD ley NY)',  exchange: 'BCBA', type: 'bond' },
  { symbol: 'GD46',  name: 'Global 2046 (USD ley NY)',  exchange: 'BCBA', type: 'bond' },
  { symbol: 'TX26',  name: 'Boncer 2026 (CER)',         exchange: 'BCBA', type: 'bond' },
  { symbol: 'TX28',  name: 'Boncer 2028 (CER)',         exchange: 'BCBA', type: 'bond' },
  { symbol: 'TX31',  name: 'Boncer 2031 (CER)',         exchange: 'BCBA', type: 'bond' },
  { symbol: 'TZX26', name: 'Boncer Cero 2026 (CER)',    exchange: 'BCBA', type: 'bond' },
  { symbol: 'TZX28', name: 'Boncer Cero 2028 (CER)',    exchange: 'BCBA', type: 'bond' },
  { symbol: 'DICY',  name: 'Discount USD (ley AR)',     exchange: 'BCBA', type: 'bond' },
  { symbol: 'PARY',  name: 'Par USD (ley AR)',          exchange: 'BCBA', type: 'bond' },

  // ETFs (core US)
  { symbol: 'SPY',   name: 'SPDR S&P 500',              exchange: 'NYSE',   type: 'etf' },
  { symbol: 'VOO',   name: 'Vanguard S&P 500',          exchange: 'NYSE',   type: 'etf' },
  { symbol: 'IVV',   name: 'iShares Core S&P 500',      exchange: 'NYSE',   type: 'etf' },
  { symbol: 'QQQ',   name: 'Invesco Nasdaq 100',        exchange: 'NASDAQ', type: 'etf' },
  { symbol: 'VTI',   name: 'Vanguard Total Stock Market', exchange: 'NYSE', type: 'etf' },
  { symbol: 'DIA',   name: 'SPDR Dow Jones',            exchange: 'NYSE',   type: 'etf' },
  { symbol: 'IWM',   name: 'iShares Russell 2000',      exchange: 'NYSE',   type: 'etf' },
  { symbol: 'VEA',   name: 'Vanguard FTSE Developed',   exchange: 'NYSE',   type: 'etf' },
  { symbol: 'VWO',   name: 'Vanguard Emerging Markets', exchange: 'NYSE',   type: 'etf' },
  { symbol: 'IEMG',  name: 'iShares Core MSCI EM',      exchange: 'NYSE',   type: 'etf' },
  { symbol: 'AGG',   name: 'iShares Core US Bond',      exchange: 'NYSE',   type: 'etf' },
  { symbol: 'BND',   name: 'Vanguard Total Bond',       exchange: 'NASDAQ', type: 'etf' },
  { symbol: 'GLD',   name: 'SPDR Gold Trust',           exchange: 'NYSE',   type: 'etf' },
  { symbol: 'SLV',   name: 'iShares Silver Trust',      exchange: 'NYSE',   type: 'etf' },
  { symbol: 'XLK',   name: 'Technology Sector SPDR',    exchange: 'NYSE',   type: 'etf' },
  { symbol: 'XLF',   name: 'Financial Sector SPDR',     exchange: 'NYSE',   type: 'etf' },
  { symbol: 'XLE',   name: 'Energy Sector SPDR',        exchange: 'NYSE',   type: 'etf' },
  { symbol: 'ARKK',  name: 'ARK Innovation',            exchange: 'NYSE',   type: 'etf' },

  // Cripto (top market cap + L1)
  { symbol: 'BTC',   name: 'Bitcoin',                   exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'ETH',   name: 'Ethereum',                  exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'SOL',   name: 'Solana',                    exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'BNB',   name: 'BNB',                       exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'XRP',   name: 'XRP',                       exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'ADA',   name: 'Cardano',                   exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'DOGE',  name: 'Dogecoin',                  exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'AVAX',  name: 'Avalanche',                 exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'DOT',   name: 'Polkadot',                  exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'MATIC', name: 'Polygon',                   exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'LINK',  name: 'Chainlink',                 exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'USDT',  name: 'Tether',                    exchange: 'CRYPTO', type: 'crypto' },
  { symbol: 'USDC',  name: 'USD Coin',                  exchange: 'CRYPTO', type: 'crypto' },
]

// Heurística para inferir tipo a partir del campo `asset` de una posición.
export function inferType(asset) {
  if (!asset) return 'stock_us'
  const a = asset.toUpperCase()
  if (['BTC', 'ETH', 'SOL', 'USDT', 'USDC', 'BNB', 'XRP', 'ADA', 'DOGE', 'AVAX', 'DOT', 'MATIC', 'LINK'].includes(a)) return 'crypto'
  if (a.endsWith('.BA')) return 'cedear'
  if (/^(AL\d|GD\d|AE\d|TX\d|TZ|T2X|S\d|T\d{2}|PARY|DICY|PAR|DIC)/.test(a)) return 'bond'
  const hit = POPULAR_TICKERS.find(t => t.symbol === a)
  if (hit) return hit.type
  return 'stock_us'
}
