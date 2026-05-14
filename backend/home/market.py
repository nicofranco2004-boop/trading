"""Market data para el Home — índices del día, heatmap S&P, movers.

Reusa yfinance vía la misma lógica que `/api/prices`. Cachea para no
martillar.

V1: data del día (close anterior o mid-day si hay snapshot).
V2: real-time con polling/WebSocket.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Any, Tuple

import yfinance as yf

log = logging.getLogger("home.market")


# ─── Lista hardcodeada de S&P 500 top 50 por market cap (Q1 2026) ────────────
# Para evitar rate-limits, no fetcheamos la lista dinámica. Si en un par de
# años cambia el orden, actualizamos manualmente. Top 50 cubre ~60% del S&P.
SP500_TOP_50 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "BRK-B", "TSLA", "LLY", "AVGO",
    "JPM", "V", "WMT", "XOM", "UNH",
    "MA", "PG", "JNJ", "HD", "COST",
    "ABBV", "BAC", "ORCL", "CRM", "CVX",
    "KO", "ADBE", "MRK", "AMD", "PEP",
    "NFLX", "TMO", "QCOM", "LIN", "INTC",
    "DIS", "CSCO", "ABT", "WFC", "ACN",
    "MCD", "DHR", "TXN", "INTU", "VZ",
    "AMGN", "PFE", "PM", "IBM", "NOW",
]

# Mapeo de símbolos a (nombre, market_cap aproximado en B USD).
# El market_cap se usa solo como peso visual del heatmap. Es estático para
# evitar 50 llamadas a yfinance al primer render. Actualizar manualmente
# cada Q (cambia poco día a día). El change_pct sí viene en tiempo (semi-)real.
SP500_META = {
    "AAPL":  ("Apple",          3800), "MSFT":  ("Microsoft",     3500),
    "NVDA":  ("NVIDIA",         3200), "GOOGL": ("Alphabet",      2400),
    "AMZN":  ("Amazon",         2200), "META":  ("Meta",          1700),
    "BRK-B": ("Berkshire",      1000), "TSLA":  ("Tesla",          950),
    "LLY":   ("Eli Lilly",       850), "AVGO":  ("Broadcom",       820),
    "JPM":   ("JPMorgan",        680), "V":     ("Visa",           620),
    "WMT":   ("Walmart",         610), "XOM":   ("ExxonMobil",     580),
    "UNH":   ("UnitedHealth",    550), "MA":    ("Mastercard",     500),
    "PG":    ("P&G",             420), "JNJ":   ("J&J",            400),
    "HD":    ("Home Depot",      390), "COST":  ("Costco",         380),
    "ABBV":  ("AbbVie",          360), "BAC":   ("Bank of Am.",    340),
    "ORCL":  ("Oracle",          330), "CRM":   ("Salesforce",     310),
    "CVX":   ("Chevron",         300), "KO":    ("Coca-Cola",      290),
    "ADBE":  ("Adobe",           270), "MRK":   ("Merck",          265),
    "AMD":   ("AMD",             260), "PEP":   ("PepsiCo",        240),
    "NFLX":  ("Netflix",         230), "TMO":   ("Thermo Fisher",  225),
    "QCOM":  ("Qualcomm",        210), "LIN":   ("Linde",          205),
    "INTC":  ("Intel",           200), "DIS":   ("Disney",         195),
    "CSCO":  ("Cisco",           190), "ABT":   ("Abbott",         185),
    "WFC":   ("Wells Fargo",     180), "ACN":   ("Accenture",      175),
    "MCD":   ("McDonald's",      170), "DHR":   ("Danaher",        165),
    "TXN":   ("Texas Instr.",    160), "INTU":  ("Intuit",         155),
    "VZ":    ("Verizon",         150), "AMGN":  ("Amgen",          145),
    "PFE":   ("Pfizer",          140), "PM":    ("Philip Morris",  135),
    "IBM":   ("IBM",             130), "NOW":   ("ServiceNow",     125),
}


# ─── Merval — Panel general BCBA (acciones AR top 25 por liquidez) ───────────
# Tickers en formato yfinance ".BA". Market caps en miles de millones de ARS
# (aprox); para visualización en el heatmap los usamos crudos (proporciones
# relativas se preservan independientemente de la moneda).
MERVAL_TOP_25 = [
    "GGAL.BA", "YPFD.BA", "PAMP.BA", "BMA.BA", "BBAR.BA",
    "ALUA.BA", "CRES.BA", "TXAR.BA", "COME.BA", "EDN.BA",
    "TGSU2.BA", "TGNO4.BA", "CEPU.BA", "MIRG.BA", "VALO.BA",
    "TRAN.BA", "LOMA.BA", "AGRO.BA", "SUPV.BA", "BYMA.BA",
    "HARG.BA", "CVH.BA", "DGCU2.BA", "GCLA.BA", "CGPA2.BA",
]

MERVAL_META = {
    "GGAL.BA":  ("Galicia",          900),  "YPFD.BA":  ("YPF",              780),
    "PAMP.BA":  ("Pampa Energía",    600),  "BMA.BA":   ("Banco Macro",      550),
    "BBAR.BA":  ("BBVA Argentina",   400),  "ALUA.BA":  ("Aluar",            350),
    "CRES.BA":  ("Cresud",           280),  "TXAR.BA":  ("Ternium AR",       260),
    "COME.BA":  ("Sociedad Com.",    200),  "EDN.BA":   ("Edenor",           180),
    "TGSU2.BA": ("TGS",              170),  "TGNO4.BA": ("TGN",              160),
    "CEPU.BA":  ("Central Puerto",   150),  "MIRG.BA":  ("Mirgor",           130),
    "VALO.BA":  ("Banco de Valores", 120),  "TRAN.BA":  ("Transener",        110),
    "LOMA.BA":  ("Loma Negra",       100),  "AGRO.BA":  ("Agrometal",         85),
    "SUPV.BA":  ("Supervielle",       80),  "BYMA.BA":  ("BYMA",              75),
    "HARG.BA":  ("Holcim AR",         70),  "CVH.BA":   ("Cablevisión",       65),
    "DGCU2.BA": ("Distrib. de Gas",   60),  "GCLA.BA":  ("Grupo Clarín",      55),
    "CGPA2.BA": ("Camuzzi Gas",       50),
}


# ─── Cripto top 30 (por market cap aproximado) ───────────────────────────────
CRYPTO_TOP_30 = [
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "BNB-USD",
    "ADA-USD", "DOGE-USD", "TRX-USD", "AVAX-USD", "DOT-USD",
    "LINK-USD", "MATIC-USD", "TON-USD", "SHIB-USD", "LTC-USD",
    "BCH-USD", "UNI-USD", "ATOM-USD", "ETC-USD", "XLM-USD",
    "NEAR-USD", "APT-USD", "ARB-USD", "OP-USD", "FIL-USD",
    "ALGO-USD", "ICP-USD", "VET-USD", "HBAR-USD", "AAVE-USD",
]

CRYPTO_META = {
    "BTC-USD":  ("Bitcoin",       1600), "ETH-USD":   ("Ethereum",       500),
    "SOL-USD":  ("Solana",         140), "XRP-USD":   ("XRP",            135),
    "BNB-USD":  ("BNB",            120), "ADA-USD":   ("Cardano",         45),
    "DOGE-USD": ("Dogecoin",        38), "TRX-USD":   ("TRON",            30),
    "AVAX-USD": ("Avalanche",       25), "DOT-USD":   ("Polkadot",        20),
    "LINK-USD": ("Chainlink",       18), "MATIC-USD": ("Polygon",         15),
    "TON-USD":  ("Toncoin",         14), "SHIB-USD":  ("Shiba Inu",       12),
    "LTC-USD":  ("Litecoin",        10), "BCH-USD":   ("Bitcoin Cash",     8),
    "UNI-USD":  ("Uniswap",          7), "ATOM-USD":  ("Cosmos",           6),
    "ETC-USD":  ("Ethereum Classic", 6), "XLM-USD":   ("Stellar",          5),
    "NEAR-USD": ("NEAR Protocol",    5), "APT-USD":   ("Aptos",            4),
    "ARB-USD":  ("Arbitrum",         4), "OP-USD":    ("Optimism",         3),
    "FIL-USD":  ("Filecoin",         3), "ALGO-USD":  ("Algorand",         3),
    "ICP-USD":  ("Internet Comp.",   2), "VET-USD":   ("VeChain",          2),
    "HBAR-USD": ("Hedera",           2), "AAVE-USD":  ("Aave",             2),
}


# Índices de referencia que muestra el strip superior del Home
# (S&P 500 vía SPY ETF para tener un símbolo con datos consistentes en yfinance)
INDICES = [
    {"symbol": "^GSPC", "label": "S&P 500",    "kind": "index"},
    {"symbol": "^IXIC", "label": "Nasdaq 100", "kind": "index"},
    {"symbol": "^MERV", "label": "Merval",     "kind": "index"},
    {"symbol": "BTC-USD", "label": "Bitcoin",  "kind": "crypto"},
    {"symbol": "ETH-USD", "label": "Ethereum", "kind": "crypto"},
    {"symbol": "GC=F", "label": "Oro",         "kind": "commodity"},
]


# ─── Cache simple in-memory ──────────────────────────────────────────────────
# TTL configurable por endpoint — heatmap se actualiza poco, índices más seguido.
# Estructura: { key: (timestamp, data) }
_cache: Dict[str, Tuple[float, Any]] = {}


def _cached(key: str, ttl_s: int):
    """Decorator: cachea el resultado de la func bajo `key` por `ttl_s` segundos."""
    def deco(fn):
        def wrapper(*args, **kwargs):
            now = time.time()
            cached = _cache.get(key)
            if cached and (now - cached[0]) < ttl_s:
                return cached[1]
            result = fn(*args, **kwargs)
            _cache[key] = (now, result)
            return result
        return wrapper
    return deco


# ─── Fetchers ────────────────────────────────────────────────────────────────

def _fetch_daily_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Devuelve dict {price, change_pct, prev_close} con la última cotización
    del símbolo. Usa yfinance 2 días de history. None si falla."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d")
        if hist.empty or len(hist) < 2:
            return None
        prev_close = float(hist["Close"].iloc[-2])
        last_close = float(hist["Close"].iloc[-1])
        change_pct = ((last_close / prev_close) - 1) * 100 if prev_close > 0 else 0
        return {
            "symbol": symbol,
            "price": round(last_close, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": round(change_pct, 2),
        }
    except Exception as ex:
        log.warning(f"_fetch_daily_quote falló para {symbol}: {ex}")
        return None


# Crypto tickers que yfinance espera con sufijo "-USD" (BTC, ETH, …).
# Mantenemos la lista local para evitar dependencia circular con main.py.
# El símbolo del user/holdings llega como "BTC" — lo mapeamos a "BTC-USD"
# para el download y revertimos al construir la respuesta.
_CRYPTO_TICKERS = {
    'BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOGE', 'AVAX', 'DOT',
    'MATIC', 'LINK', 'USDT', 'USDC', 'TRX', 'LTC', 'BCH', 'ETC', 'XLM',
    'NEAR', 'ATOM', 'FIL', 'APT', 'ARB', 'OP', 'TON', 'HBAR', 'ICP',
    'VET', 'ALGO', 'GRT', 'AAVE', 'UNI', 'MKR', 'SUSHI', 'COMP', 'CRV',
    'SAND', 'MANA', 'AXS', 'SHIB', 'PEPE', 'SUI', 'SEI', 'TIA', 'INJ',
    'WLD', 'ORDI', 'RUNE', 'STX', 'WBTC', 'STETH',
}


def _to_yf(sym: str) -> str:
    """Convierte un símbolo de la app a su forma yfinance."""
    s = (sym or "").upper()
    if s in _CRYPTO_TICKERS:
        return f"{s}-USD"
    return s


def _fetch_batch_quotes(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Versión batched — un solo download de yfinance para N símbolos.

    Mantiene un mapeo bidireccional para revertir el ticker yfinance al
    símbolo original de la app (BTC-USD → BTC). Sin esto, los holdings de
    cripto del user no resolvían quote y no aparecían en "Lo que te afecta".
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not symbols:
        return out
    # Mapeo orig → yf, y reverse para encontrar el símbolo original al parsear.
    yf_for: Dict[str, str] = {s: _to_yf(s) for s in symbols}
    orig_for: Dict[str, str] = {v: k for k, v in yf_for.items()}
    yf_symbols = list(orig_for.keys())
    try:
        data = yf.download(
            tickers=" ".join(yf_symbols), period="5d",
            interval="1d", group_by="ticker", auto_adjust=False,
            progress=False, threads=True,
        )
        for yf_sym, orig_sym in orig_for.items():
            try:
                sub = data[yf_sym] if yf_sym in data else None
                if sub is None or sub.empty:
                    continue
                closes = sub["Close"].dropna()
                if len(closes) < 2:
                    continue
                prev = float(closes.iloc[-2])
                last = float(closes.iloc[-1])
                if prev <= 0:
                    continue
                out[orig_sym] = {
                    "symbol": orig_sym,
                    "price": round(last, 2),
                    "prev_close": round(prev, 2),
                    "change_pct": round(((last / prev) - 1) * 100, 2),
                }
            except Exception as ex:
                log.warning(f"_fetch_batch_quotes parsing {yf_sym} (orig {orig_sym}): {ex}")
    except Exception as ex:
        log.error(f"_fetch_batch_quotes batch download falló: {ex}")
    return out


# Nota: removí _fetch_market_caps porque 50 llamadas sequenciales a yfinance
# bloqueaban el first render del Home. Usamos SP500_META con valores estáticos
# para el peso visual — el change_pct sí es semi-real-time.


# ─── Public API del módulo ───────────────────────────────────────────────────

@_cached("indices_strip", ttl_s=900)  # 15min
def get_indices_strip() -> List[Dict[str, Any]]:
    """Strip superior del Home: 6 índices/activos de referencia."""
    symbols = [i["symbol"] for i in INDICES]
    quotes = _fetch_batch_quotes(symbols)
    out = []
    for cfg in INDICES:
        q = quotes.get(cfg["symbol"])
        out.append({
            "symbol": cfg["symbol"],
            "label": cfg["label"],
            "kind": cfg["kind"],
            "price": q["price"] if q else None,
            "change_pct": q["change_pct"] if q else None,
        })
    return out


# Registry de mercados soportados — clave usada por los endpoints
# (?market=sp500 | merval | crypto).
MARKETS = {
    "sp500":  {"symbols": SP500_TOP_50,  "meta": SP500_META,  "label": "S&P 500"},
    "merval": {"symbols": MERVAL_TOP_25, "meta": MERVAL_META, "label": "Merval"},
    "crypto": {"symbols": CRYPTO_TOP_30, "meta": CRYPTO_META, "label": "Cripto top 30"},
}


def _build_heatmap(market_key: str) -> List[Dict[str, Any]]:
    """Versión genérica de get_heatmap_X. Recorre los símbolos de un mercado,
    fetchea quotes batched y compone los bloques."""
    cfg = MARKETS.get(market_key)
    if not cfg:
        return []
    quotes = _fetch_batch_quotes(cfg["symbols"])
    out = []
    for sym in cfg["symbols"]:
        q = quotes.get(sym)
        if not q:
            continue
        meta = cfg["meta"].get(sym, (sym, 100))
        out.append({
            "symbol": sym,
            "name": meta[0],
            "price": q["price"],
            "change_pct": q["change_pct"],
            "market_cap": meta[1],
        })
    return out


def _build_movers(market_key: str) -> Dict[str, List[Dict[str, Any]]]:
    """Top 5 gainers / losers de un mercado."""
    cfg = MARKETS.get(market_key)
    if not cfg:
        return {"gainers": [], "losers": []}
    quotes = _fetch_batch_quotes(cfg["symbols"])
    with_data = [
        {
            "symbol": sym,
            "name": cfg["meta"].get(sym, (sym, 0))[0],
            "price": q["price"],
            "change_pct": q["change_pct"],
        }
        for sym, q in quotes.items()
    ]
    sorted_by_change = sorted(with_data, key=lambda x: x["change_pct"], reverse=True)
    return {
        "gainers": sorted_by_change[:5],
        "losers": sorted_by_change[-5:][::-1],
    }


# Wrappers con cache por mercado (TTL 30min — sintonizable por mercado)
@_cached("heatmap_sp500",  ttl_s=1800)
def get_heatmap_sp500()  -> List[Dict[str, Any]]: return _build_heatmap("sp500")

@_cached("heatmap_merval", ttl_s=1800)
def get_heatmap_merval() -> List[Dict[str, Any]]: return _build_heatmap("merval")

@_cached("heatmap_crypto", ttl_s=900)  # crypto se mueve más rápido → 15min
def get_heatmap_crypto() -> List[Dict[str, Any]]: return _build_heatmap("crypto")


@_cached("movers_sp500",  ttl_s=1800)
def get_movers_sp500()  -> Dict[str, List[Dict[str, Any]]]: return _build_movers("sp500")

@_cached("movers_merval", ttl_s=1800)
def get_movers_merval() -> Dict[str, List[Dict[str, Any]]]: return _build_movers("merval")

@_cached("movers_crypto", ttl_s=900)
def get_movers_crypto() -> Dict[str, List[Dict[str, Any]]]: return _build_movers("crypto")


def get_heatmap(market: str) -> List[Dict[str, Any]]:
    """Dispatch por mercado. Usado desde el endpoint /api/home/heatmap."""
    if market == "sp500":  return get_heatmap_sp500()
    if market == "merval": return get_heatmap_merval()
    if market == "crypto": return get_heatmap_crypto()
    return []


def get_movers(market: str) -> Dict[str, List[Dict[str, Any]]]:
    if market == "sp500":  return get_movers_sp500()
    if market == "merval": return get_movers_merval()
    if market == "crypto": return get_movers_crypto()
    return {"gainers": [], "losers": []}
