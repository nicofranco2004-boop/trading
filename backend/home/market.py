"""Market data para el Home — índices del día, heatmap S&P, movers.

La variación del día de cada símbolo sale de `main._variacion_del_dia` (la de
Posiciones): data912 para BYMA, yfinance para EEUU y cripto. Cachea para no
martillar.

V1: data del día (close anterior o mid-day si hay snapshot).
V2: real-time con polling/WebSocket.
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Any, Tuple

from pricing import yahoo as _yahoo

log = logging.getLogger("home.market")

# Executor dedicado para refrescos SWR background. Tamaño chico — solo
# necesitamos 1-2 refreshes concurrent porque hay pocas keys distintas.
# Patrón módulo-level (no `with`) para que el thread no muera al terminar
# la request — la idea es que el refresh continúe en bg después de que
# devolvimos la stale data al user.
_swr_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="market-swr")

# Lock por key para evitar dispatch múltiple del mismo refresh.
# Sin esto, si 10 users entran al mismo tiempo y el cache está stale,
# disparamos 10 refreshes idénticos a yfinance → throttle garantizado.
_swr_inflight: Dict[str, bool] = {}
_swr_lock = threading.Lock()


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
# ^IXIC es el Nasdaq COMPUESTO (unas 3.000 empresas), no el Nasdaq 100 (^NDX,
# las 100 más grandes): son dos índices distintos que no valen lo mismo. El
# rótulo decía "Nasdaq 100" al lado del precio del compuesto.
INDICES = [
    {"symbol": "^GSPC", "label": "S&P 500",    "kind": "index"},
    {"symbol": "^IXIC", "label": "Nasdaq",     "kind": "index"},
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
    """Decorator stale-while-revalidate:
       • cache fresco (< ttl_s) → return inmediato.
       • cache stale pero existente → return stale + dispatch refresh background.
       • sin cache → bloquea fetcheando (cold start).

    Sin SWR, un cache stale post-restart bloqueaba el primer request del día
    por 15-30s mientras yfinance respondía. Con SWR, el user que pidió ve
    data un poco vieja (ej. heatmap de hace 35min) pero instantáneo, y el
    próximo request ve data fresca.

    Lock `_swr_inflight` evita disparar 10 refreshes idénticos si 10 users
    entran simultáneo al cache stale. Solo 1 thread refresca; los otros
    también devuelven stale.
    """
    def deco(fn):
        def _refresh_in_bg(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                _cache[key] = (time.time(), result)
            except Exception as ex:
                log.warning(f"SWR refresh failed for {key}: {ex}")
            finally:
                with _swr_lock:
                    _swr_inflight.pop(key, None)

        def wrapper(*args, **kwargs):
            now = time.time()
            cached = _cache.get(key)

            # Cache fresco → return inmediato
            if cached and (now - cached[0]) < ttl_s:
                return cached[1]

            # Cache stale pero existe → return stale + refresh bg
            if cached:
                with _swr_lock:
                    already_refreshing = _swr_inflight.get(key, False)
                    if not already_refreshing:
                        _swr_inflight[key] = True
                        _swr_executor.submit(_refresh_in_bg, *args, **kwargs)
                return cached[1]

            # Cold start (cache vacío) → bloquea fetcheando.
            # Este path solo se ejecuta el PRIMER request post-restart.
            result = fn(*args, **kwargs)
            _cache[key] = (now, result)
            return result
        return wrapper
    return deco


# ─── Mercados ────────────────────────────────────────────────────────────────

# Qué es cripto lo decide UNA lista: `cripto.CRYPTO_YF` (las criptos + las monedas
# estables, con su nombre en Yahoo). Hasta 2026-10-08 acá había una copia que no
# coincidía (tenía TON, ICP, USDT y USDC; le faltaban ~55 de las de main): desde
# que la cotización sale de `main._variacion_del_dia`, esas cuatro se le pedían a
# Yahoo con el nombre pelado y se quedaban sin variación en «Lo que te afecta», la
# watchlist y las alertas. `cripto.py` no depende de nada: se importa directo,
# sin el rodeo por main (que antes, si fallaba, contestaba «no es cripto»).
from cripto import es_cripto as _es_cripto  # noqa: E402


# ─── ¿De qué RUEDA es este número? ───────────────────────────────────────────
# Un `change_pct` sin fecha no alcanza para decir "hoy". yfinance devuelve las
# dos últimas barras diarias que TENGA: antes de que abra el mercado —o cuando
# la barra del día viene con los OHLC en NaN, que con los `.BA` pasa seguido
# (ver project_ba_nan_bar)— esas dos barras son las de AYER y ANTEAYER, y el
# porcentaje sale igual, sin nada que lo distinga del de hoy.
#
# Es la MISMA lección que ya se había aprendido cuando `/api/prices` devolvía un
# precio pelado y se le estampó procedencia (`src`/`as_of`/`stale`): ese arreglo
# nunca se propagó hasta acá, que es de donde comen las alertas y la IA.
# Desde ahora cada quote viaja con `as_of` (la rueda que midió) e `is_today`.

def hoy_de_mercado(mercado: Optional[str]) -> str:
    """Qué día es "hoy" para una rueda, en ISO.

    · Cripto: las barras diarias de yfinance son días UTC (cortan a las 00:00
      UTC = 21:00 ART) y opera 24/7 → su día es el día UTC.
    · Acciones y CEDEARs: BYMA (11–17 ART) y NYSE/Nasdaq (9:30–16 ET) caen
      enteras dentro del mismo día calendario argentino, que es el "hoy" de
      Rendi → se lo preguntamos al dueño del calendario, no lo recalculamos.
    """
    if mercado == "cripto":
        return _dt.datetime.utcnow().date().isoformat()
    from fechas import hoy_art
    return hoy_art()


def session_today(symbol: str) -> str:
    """Qué día es "hoy" para el mercado de `symbol` (ver `hoy_de_mercado`)."""
    return hoy_de_mercado(mercado_de(symbol))


def mercado_de(symbol: str) -> str:
    """En qué rueda cotiza `symbol`: 'cripto' (24/7), 'byma' (los `.BA`) o 'us'."""
    s = (symbol or "").upper()
    if s.endswith("-USD") or _es_cripto(s):
        return "cripto"
    if s.endswith(".BA"):
        return "byma"
    return "us"


def _ahora_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def estado_de_rueda(items: List[Dict[str, Any]], now=None) -> Dict[str, Any]:
    """El indicador de rueda de las secciones de mercado del inicio (EnVivo).

    Un número cuenta como "en rueda" si cumple las dos cosas:
      1. su rueda está en horario AHORA (alerts_engine.rueda_en_horario), y
      2. el número ES de la rueda de hoy (`as_of` == session_today).
    La 2 es la que importa: a primera hora, o con los movers guardados 30 min,
    el horario ya dice "abierto" pero el porcentaje todavía es el de ayer — y un
    punto que late al lado de números de ayer es el mismo "hoy" que mentía en
    las alertas del 15/09. De paso cubre los feriados, que el horario no sabe.

    Devuelve:
      · `abierto`   — TODOS los números con fecha están en rueda. No "alguno":
                      con "alguno", una sola cripto en la watchlist un sábado
                      ponía la lista entera en "Abierto" al lado de acciones con
                      el porcentaje del viernes.
      · `en_rueda` / `total` — cuántos lo están, para el caso mezclado
                      ("En rueda 1 de 3").
      · `en_horario` — alguna rueda de la lista está en horario aunque sus
                      números todavía no sean de hoy. Sin esto, durante la
                      rueda de BYMA con la barra `.BA` en NaN (project_ba_nan_bar)
                      el cartel decía "Cerrado" con el mercado abierto.
      · `rueda`     — la fecha más nueva de los números, para decir DE CUÁNDO
                      son ("rueda del 26/09").

    Se calcula al SERVIR, no se guarda en ningún cache: el horario cambia solo.
    """
    from alerts_engine import rueda_en_horario
    ahora = now or _dt.datetime.now(_dt.timezone.utc)
    lista = items or []
    horario = {m: rueda_en_horario(m, ahora) for m in {mercado_de(it.get("symbol")) for it in lista}}
    con_fecha = [it for it in lista if it.get("as_of")]
    en_rueda = [
        it for it in con_fecha
        if it["as_of"] == session_today(it.get("symbol"))
        and horario[mercado_de(it.get("symbol"))]
    ]
    return {
        "abierto": bool(con_fecha) and len(en_rueda) == len(con_fecha),
        "en_rueda": len(en_rueda),
        "total": len(con_fecha),
        "en_horario": any(horario.values()),
        "rueda": max(it["as_of"] for it in con_fecha) if con_fecha else None,
    }


def _stamp_session(entry: Dict[str, Any], orig_sym: str) -> Dict[str, Any]:
    """Marca si el `change_pct` de este quote es el de la rueda de HOY.

    Se recalcula al SERVIR y no se guarda en el cache: el cache dura 60s y
    puede cruzar el cambio de día. Sin `as_of` → `is_today` False: "no sé de
    qué rueda es" tiene que pesar lo mismo que "es vieja".

    El "hoy" sale del mercado que MIDIÓ el número (`mercado`, lo pone
    `main._variacion_del_dia`), no del símbolo: una cripto en un broker en
    pesos (`BTC.BA`) se mide con la vela UTC de BTC-USD."""
    hoy = (hoy_de_mercado(entry["mercado"]) if entry.get("mercado")
           else session_today(orig_sym))
    entry["is_today"] = bool(entry.get("as_of")) and entry["as_of"] == hoy
    return entry


# ─── Quote cache per-symbol ──────────────────────────────────────────────────
# Cada quote vive 60s. Antes el watchlist refetcheaba yfinance entero en cada
# GET — 1-3s de latencia. Con cache, solo los símbolos nuevos/expirados se
# piden; el resto sale instantáneo. Mismo wrapper para todos los callers
# (watchlist, alertas, «Lo que te afecta», mapas del inicio, IA).
_QUOTE_CACHE: Dict[str, Dict[str, Any]] = {}  # symbol → { ..., '_ts': float }
_QUOTE_TTL_S = 60


def _fetch_batch_quotes(symbols: List[str],
                        tope: float = _yahoo.TOPE_PANTALLA_SEG) -> Dict[str, Dict[str, Any]]:
    """{símbolo: {symbol, price, prev_close, change_pct, mercado, as_of,
    is_today}} — la variación del día de cada símbolo, cacheada 60 s.

    ⭐ NO calcula nada: la variación sale de `main._variacion_del_dia`, la MISMA
    que la columna "Var. día" de Posiciones y que el chat. Hasta 2026-10-08 esta
    función bajaba de yfinance por su cuenta, también los `.BA`, y yfinance
    trae la vela del día de los `.BA` en NaN o el ticker congelado: la misma
    acción tenía una variación en Posiciones y otra en las alertas, en «Lo que
    te afecta» y en la watchlist. Los bonos ni aparecían (yfinance no los
    tiene). Ver tests/test_variacion_una_fuente.py.

    `tope`: lo máximo que se espera a Yahoo (las alertas, que corren de fondo,
    pasan el largo).
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not symbols:
        return out
    now = time.time()
    to_fetch: List[str] = []
    for s in dict.fromkeys(symbols):
        cached = _QUOTE_CACHE.get(s)
        if cached and now - cached.get("_ts", 0) < _QUOTE_TTL_S:
            out[s] = _stamp_session({k: v for k, v in cached.items() if k != "_ts"}, s)
        else:
            to_fetch.append(s)
    if not to_fetch:
        return out
    try:
        import main as _main
        frescas = _main._variacion_del_dia(to_fetch, tope=tope)
    except Exception as ex:
        log.error(f"_fetch_batch_quotes: la variación del día falló: {ex}")
        return out
    for s, q in frescas.items():
        _QUOTE_CACHE[s] = {**q, "_ts": now}
        out[s] = _stamp_session(dict(q), s)
    return out


def _invalidate_quote_cache(symbols: Optional[List[str]] = None) -> None:
    """Permite forzar refresh manual (ej. tras un import grande). Si no se
    pasan símbolos, limpia todo."""
    if symbols is None:
        _QUOTE_CACHE.clear()
        return
    for s in symbols:
        _QUOTE_CACHE.pop(s, None)


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
            # De qué rueda es el porcentaje: lo necesita estado_de_rueda para no
            # decir "Abierto" al lado de los movers de AYER.
            "as_of": q.get("as_of"),
        }
        for sym, q in quotes.items()
    ]
    sorted_by_change = sorted(with_data, key=lambda x: x["change_pct"], reverse=True)
    return {
        "gainers": sorted_by_change[:5],
        "losers": sorted_by_change[-5:][::-1],
        # Cuándo se le pidieron los datos al proveedor. Se escribe ACÁ adentro,
        # no en el endpoint: esta función vive guardada hasta 30 min (`_cached`),
        # y "actualizado hace X" tiene que contar desde el pedido, no desde que
        # se sirvió la copia guardada.
        "actualizado": _ahora_iso(),
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
