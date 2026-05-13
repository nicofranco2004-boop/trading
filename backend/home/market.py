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


def _fetch_batch_quotes(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Versión batched — un solo download de yfinance para N símbolos."""
    out: Dict[str, Dict[str, Any]] = {}
    if not symbols:
        return out
    try:
        # group_by="ticker" devuelve un MultiIndex; period=5d para tener prev_close
        data = yf.download(
            tickers=" ".join(symbols), period="5d",
            interval="1d", group_by="ticker", auto_adjust=False,
            progress=False, threads=True,
        )
        for sym in symbols:
            try:
                sub = data[sym] if sym in data else None
                if sub is None or sub.empty:
                    continue
                closes = sub["Close"].dropna()
                if len(closes) < 2:
                    continue
                prev = float(closes.iloc[-2])
                last = float(closes.iloc[-1])
                if prev <= 0:
                    continue
                out[sym] = {
                    "symbol": sym,
                    "price": round(last, 2),
                    "prev_close": round(prev, 2),
                    "change_pct": round(((last / prev) - 1) * 100, 2),
                }
            except Exception as ex:
                log.warning(f"_fetch_batch_quotes parsing {sym}: {ex}")
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


@_cached("heatmap_sp500", ttl_s=1800)  # 30min
def get_heatmap_sp500() -> List[Dict[str, Any]]:
    """Datos del heatmap S&P 500 top 50.

    Devuelve lista de bloques con: symbol, name, price, change_pct, market_cap.
    Frontend ordena por market_cap (block size) y colorea por change_pct.
    """
    quotes = _fetch_batch_quotes(SP500_TOP_50)
    out = []
    for sym in SP500_TOP_50:
        q = quotes.get(sym)
        if not q:
            continue
        meta = SP500_META.get(sym, (sym, 100))
        out.append({
            "symbol": sym,
            "name": meta[0],
            "price": q["price"],
            "change_pct": q["change_pct"],
            "market_cap": meta[1],  # en B USD (estático)
        })
    return out


@_cached("movers_sp500", ttl_s=1800)  # 30min
def get_movers_sp500() -> Dict[str, List[Dict[str, Any]]]:
    """Top 5 gainers y top 5 losers del S&P top 50."""
    quotes = _fetch_batch_quotes(SP500_TOP_50)
    with_data = [
        {
            "symbol": sym,
            "name": SP500_META.get(sym, (sym, 0))[0],
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
