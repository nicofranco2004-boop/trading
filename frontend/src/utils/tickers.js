// CEDEARs más líquidos en Argentina (sin .BA — el sistema lo agrega solo para brokers ARS)
export const CEDEARS = [
  // Big Tech USA
  'AAPL','MSFT','GOOGL','GOOG','AMZN','META','NVDA','TSLA','NFLX','ADBE',
  'AMD','INTC','QCOM','AVGO','CRM','ORCL','IBM','CSCO','TXN','MU',
  'LRCX','KLAC','AMAT','ASML','TSM','MRVL','SNPS','CDNS','ANSS','MPWR',
  // Fintech / Pagos
  'V','MA','PYPL','SQ','COIN','HOOD','SOFI','AFRM','UPST','LC',
  'JPM','BAC','GS','MS','C','WFC','BLK','SCHW','AXP','COF',
  // Consumo / Retail
  'MCD','SBUX','NKE','KO','PEP','WMT','COST','TGT','HD','LOW',
  'AMZN','ETSY','CHWY','CVNA','CARVANA','GME','AMC',
  // Salud / Pharma
  'JNJ','PFE','MRK','ABBV','LLY','MRNA','BNTX','GILD','AMGN','REGN','VRTX',
  // Energía
  'XOM','CVX','OXY','SLB','HAL','BKR',
  // Media / Entertainment
  'DIS','WBD','PARA','NFLX','SPOT','PINS','SNAP','RBLX','U',
  // EV / Autos
  'TSLA','LCID','RIVN','NIO','LI','XPEV','F','GM',
  // Software / Cloud / Cyber
  'CRM','NOW','SNOW','PLTR','DDOG','NET','CRWD','PANW','ZS','OKTA',
  'DOCU','ZM','TWLO','MDB','GTLB','ASAN','HCP','BILL','PATH','DOMO',
  // Latam
  'MELI','PBR','VALE','ITUB','ABEV','BBD','NU','GRAB',
  // ETFs populares en Argentina
  'SPY','QQQ','IWM','GLD','SLV','IAU','TLT','EWZ','ARGT','EEM','VWO',
  // Otros populares
  'UBER','ABNB','SHOP','BABA','JD','PDD','BIDU','TWTR','HOOD',
]

// Acciones argentinas — Panel Líder (25 más líquidas)
export const ARG_PANEL_LIDER = [
  'GGAL','BMA','YPF','PAMP','TECO2','TXAR','ALUA','BYMA','CEPU','CRES',
  'TGNO4','TGSU2','SUPV','EDN','LOMA','VALO','MIRG','BPAT','IRSA','IRCP',
  'COME','BOLT','DGCU2','METR','GARO',
]

// Acciones argentinas — Panel General (más líquidas)
export const ARG_PANEL_GENERAL = [
  'SEMI','LONG','AGRO','POLL','RICH','GCLA','BHIP','MORI','CAPU','CELU',
  'CTIO','DYCA','FERR','FIPL','GBAN','HAVA','INVJ','LEDE','MOLA','OEST',
  'PATA','PCAR','ROSE','REGE','SAMI','TGLT','AUSO','BRIO','CAPX','INAG',
  'HARG','GFGC','NIQO','TECO2','TRAN','YPFD','HAVA','EURN','CADO','SLAN',
]

// Cryptos (para brokers USDT)
export const CRYPTO_LIST = [
  'BTC','ETH','BNB','SOL','XRP','ADA','AVAX','DOGE','TRX','DOT',
  'MATIC','LINK','LTC','BCH','NEAR','UNI','ATOM','XLM','ETC','APT',
  'ARB','OP','AAVE','MKR','CRV','COMP','SUSHI','GRT','FIL','THETA',
  'XTZ','ALGO','VET','EGLD','FTM','HBAR','IMX','SAND','MANA','AXS',
  'SHIB','PEPE','BONK','WIF','FLOKI','DEGEN',
  'SUI','SEI','TIA','INJ','JTO','PYTH','STRK','WLD','ORDI','RUNE',
  'ZEC','DASH','XMR','SNX','YFI','1INCH','DYDX','GMX','LDO','RPL',
]

// US Stocks populares (para brokers USDT — directo sin .BA)
export const US_STOCKS = [
  'AAPL','MSFT','GOOGL','AMZN','META','NVDA','TSLA','NFLX','ADBE','AMD',
  'INTC','QCOM','AVGO','CRM','ORCL','IBM','CSCO','TXN','MU','ASML',
  'V','MA','PYPL','SQ','COIN','JPM','BAC','GS','MS','C',
  'MCD','KO','PEP','WMT','NKE','DIS','XOM','CVX','JNJ','PFE','LLY',
  'MELI','PBR','VALE','ITUB','SHOP','SNOW','PLTR','DDOG','NET','CRWD',
  'PANW','ZS','UBER','ABNB','RIVN','LCID','NIO','BABA','SOFI','HOOD',
  'SPY','QQQ','GLD','SLV','TLT','IWM',
]

export const ARS_TICKERS = [...new Set([...CEDEARS, ...ARG_PANEL_LIDER, ...ARG_PANEL_GENERAL])].sort()
export const USDT_TICKERS = [...new Set([...CRYPTO_LIST, ...US_STOCKS])].sort()
