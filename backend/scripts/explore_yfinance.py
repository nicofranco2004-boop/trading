"""explore_yfinance — probe de campos disponibles para Pack A v2.

Antes de implementar las tools de fundamentales / scorecard, validamos
qué devuelve yfinance EN LA REALIDAD para los tipos de ticker que cubre
Rendi (US stocks, CEDEARs AR, cripto). Esto evita asumir que campos
estarán disponibles cuando en realidad fallan.

Output: dump estructurado de campos clave por ticker para tomar
decisiones informadas sobre el shape de las tools.

Correr: cd backend && python3 -m scripts.explore_yfinance
"""
import yfinance as yf
import json
from pprint import pformat

# Tickers que cubren los casos reales del producto
TICKERS = [
    ("NVDA", "US stock — large cap tech"),
    ("MSFT", "US stock — el del screenshot del user"),
    ("AAPL", "US stock — dividend payer + buyback heavy"),
    ("AL30.BA", "Bono AR (probable que yfinance no tenga)"),
    ("GGAL", "Banco Galicia ADR (US listed)"),
    ("BTC-USD", "Cripto"),
    ("ETH-USD", "Cripto"),
    ("FAKEXYZ", "Ticker inválido — testear fallback"),
]

# Campos que vamos a usar en las 5 tools nuevas
FIELDS_NEEDED = {
    "fundamentals": [
        "trailingPE", "forwardPE", "trailingEps", "forwardEps",
        "dividendYield", "marketCap", "fiftyTwoWeekHigh",
        "fiftyTwoWeekLow", "beta", "sector", "industry",
    ],
    "scorecard": [
        "targetMeanPrice", "currentPrice", "targetHighPrice",
        "targetLowPrice", "trailingPE", "pegRatio", "payoutRatio",
        "returnOnEquity", "debtToEquity", "profitMargins",
        "revenueGrowth", "freeCashflow",
    ],
    "earnings": [
        "earningsDate",  # tuple (next, prev?)
    ],
    "analysts": [
        "recommendationMean", "recommendationKey",
        "numberOfAnalystOpinions", "targetMeanPrice",
    ],
    "profile": [
        "longName", "shortName", "longBusinessSummary",
        "sector", "industry", "fullTimeEmployees",
        "country", "website",
    ],
}


def probe(ticker_symbol, desc):
    """Probe un ticker. Devuelve dict con campos disponibles + faltantes."""
    print(f"\n{'═' * 70}")
    print(f"Ticker: {ticker_symbol} — {desc}")
    print("═" * 70)
    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info
        if not info or len(info) < 5:
            print(f"  ⚠ info vacío o muy chico — probable ticker inválido. keys: {list(info.keys())[:5] if info else []}")
            return
        print(f"  → info OK ({len(info)} keys total)")
    except Exception as e:
        print(f"  ✗ EXCEPCIÓN: {type(e).__name__}: {e}")
        return

    # Por tool, mostrar qué tenemos
    for tool_name, fields in FIELDS_NEEDED.items():
        available = {f: info.get(f) for f in fields if f in info and info.get(f) is not None}
        missing = [f for f in fields if f not in info or info.get(f) is None]
        print(f"\n  [{tool_name.upper()}] {len(available)}/{len(fields)} disponibles")
        for f, v in available.items():
            # Truncar strings largos para legibilidad
            val_str = str(v)
            if len(val_str) > 80:
                val_str = val_str[:80] + "..."
            print(f"     ✓ {f}: {val_str}")
        if missing:
            print(f"     ✗ Faltantes: {missing}")

    # Earnings calendar (es un método aparte, no en info)
    try:
        cal = t.calendar
        if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
            print(f"\n  [CALENDAR]")
            if isinstance(cal, dict):
                # yfinance reciente devuelve dict en lugar de DataFrame
                for k, v in cal.items():
                    print(f"     ✓ {k}: {v}")
            else:
                print(f"     ✓ (type {type(cal).__name__})")
                # Si es DataFrame, mostrar las columnas
                if hasattr(cal, 'columns'):
                    print(f"        columns: {list(cal.columns)}")
        else:
            print(f"\n  [CALENDAR] ✗ vacío o None")
    except Exception as e:
        print(f"\n  [CALENDAR] ✗ ERROR: {e}")

    # Earnings history
    try:
        eh = t.earnings_history
        if eh is not None and not (hasattr(eh, 'empty') and eh.empty):
            print(f"\n  [EARNINGS_HISTORY]")
            print(f"     ✓ {len(eh)} rows; columns: {list(eh.columns) if hasattr(eh, 'columns') else 'N/A'}")
            # Mostrar el último quarter
            if hasattr(eh, 'iloc') and len(eh) > 0:
                print(f"     sample (último):")
                last = eh.iloc[-1]
                for k, v in last.items():
                    print(f"        {k}: {v}")
        else:
            print(f"\n  [EARNINGS_HISTORY] ✗ vacío o None")
    except Exception as e:
        print(f"\n  [EARNINGS_HISTORY] ✗ ERROR: {e}")

    # Recommendations (rating analistas)
    try:
        rec = t.recommendations
        if rec is not None and not (hasattr(rec, 'empty') and rec.empty):
            print(f"\n  [RECOMMENDATIONS]")
            print(f"     ✓ {len(rec)} rows; columns: {list(rec.columns) if hasattr(rec, 'columns') else 'N/A'}")
        else:
            print(f"\n  [RECOMMENDATIONS] ✗ vacío o None")
    except Exception as e:
        print(f"\n  [RECOMMENDATIONS] ✗ ERROR: {e}")


if __name__ == "__main__":
    for ticker, desc in TICKERS:
        probe(ticker, desc)
    print(f"\n\n{'═' * 70}")
    print("Probe completo.")
    print("═" * 70)
