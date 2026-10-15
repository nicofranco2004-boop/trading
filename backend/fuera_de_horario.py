"""Pre y post mercado de Wall Street: cuánto se mueve cada acción fuera de la rueda.

QUÉ ES
──────
Antes de abrir (pre-mercado, 4:00 a 9:30 de Nueva York) y después de cerrar
(post-mercado, 16:00 a 20:00) las acciones de EE.UU. siguen operando. Rendi
muestra ese movimiento como un ANTICIPO: el % de cada acción y, en la pantalla,
la plata que mueve en la tenencia del usuario. **No se suma a nada**: ni al
total, ni a la ganancia, ni a la foto diaria, ni a las alertas. El total se
mueve recién cuando abre la rueda y el precio pasa a ser el de la rueda.

Este módulo NO calcula plata: devuelve el % de cada símbolo de EE.UU. y en qué
momento del día está el mercado. La plata (valor de la fila × %) la calcula UN
helper del frontend (`utils/fueraDeHorario.js`) sobre el MISMO valor que la
pantalla muestra, para que «35 NVDA = USD 6.247,50 × −1,60 %» cierre con lo que
el usuario ve en la fila.

DE DÓNDE SALE
─────────────
El endpoint de cotizaciones de Yahoo (`/v7/finance/quote`), el mismo que usa
yfinance por dentro para `.info`, pero con TODOS los símbolos en un pedido:
medido el 2026-10-15 a las 7:58 de NY, 22 símbolos en 0,8 s. Con `.info` era
~1,1 s por símbolo.

Qué trae cada cotización (medido):
  · `marketState`: PRE · REGULAR · POST · POSTPOST · PREPRE · CLOSED.
  · `preMarketChangePercent` / `postMarketChangePercent`: el % contra el ÚLTIMO
    CIERRE de la rueda (`regularMarketPrice`), en puntos (0,64 = 0,64 %). Es el
    mismo precio con que Rendi valúa la tenencia fuera de horario, así que
    valor × % es exactamente lo que se movería.
  · Los ADRs poco operados (PAM, BMA, CEPU… a las 7:58) vienen SIN esos campos:
    todavía no operaron en el pre. Eso es «sin operar», no 0 %: se devuelve
    `pct: None` y la pantalla muestra «—».

QUÉ MOMENTO ES (`sesion`)
─────────────────────────
Sale del `marketState` de SPY, que es lo que Yahoo sabe (feriados de EE.UU.
incluidos), no de un reloj nuestro:
  · PRE                        → 'pre'
  · POST                       → 'post'
  · POSTPOST / PREPRE / CLOSED → 'post_cerrado' si hubo post-mercado después
                                  del último cierre; si no, None.
  · REGULAR                    → None (la «Var. día» ya muestra la rueda).
'post_cerrado' es la decisión de producto: el resultado del post queda a la
vista, marcado «cerrado», hasta que abre el pre del día siguiente (el fin de
semana, el del viernes).

Cada % se acepta sólo si su hora es POSTERIOR al último cierre: un pre o post
viejo que Yahoo todavía arrastre no se muestra como si fuera de hoy (ver la
regla «el número que dice hoy»).
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from pricing import yahoo as _yahoo

log = logging.getLogger(__name__)

ZONA_NY = ZoneInfo("America/New_York")
ZONA_AR = ZoneInfo("America/Argentina/Buenos_Aires")

_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
_TTL_S = 60          # cada cuánto se vuelve a preguntar por un símbolo
_LOTE = 50           # símbolos por pedido a Yahoo
MAX_SIMBOLOS = 150
_SIMBOLO_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")

# El termómetro del mercado: los ETFs de los tres índices, que sí operan fuera
# de horario (los índices en sí no).
INDICES = [
    {"s": "SPY", "n": "S&P 500"},
    {"s": "QQQ", "n": "Nasdaq"},
    {"s": "DIA", "n": "Dow Jones"},
]

# Las acciones argentinas que cotizan en Nueva York: los ADRs de la tabla
# `ADR_DE_ACCION_AR` del frontend (utils/tickers.js), más VIST. Con nombre
# para la pantalla.
ADRS = [
    {"s": "GGAL", "n": "Grupo Galicia"},
    {"s": "YPF", "n": "YPF"},
    {"s": "PAM", "n": "Pampa Energía"},
    {"s": "BMA", "n": "Banco Macro"},
    {"s": "BBAR", "n": "BBVA Argentina"},
    {"s": "SUPV", "n": "Supervielle"},
    {"s": "CEPU", "n": "Central Puerto"},
    {"s": "EDN", "n": "Edenor"},
    {"s": "TGS", "n": "Transportadora Gas del Sur"},
    {"s": "TEO", "n": "Telecom Argentina"},
    {"s": "CRESY", "n": "Cresud"},
    {"s": "IRS", "n": "IRSA"},
    {"s": "LOMA", "n": "Loma Negra"},
    {"s": "VIST", "n": "Vista Energy"},
]

# Acciones y ETFs de EE.UU. populares en Argentina como CEDEAR. Lista fija: es
# la que se ve aunque el usuario no tenga ninguna.
POPULARES = [
    {"s": "AAPL", "n": "Apple"}, {"s": "MSFT", "n": "Microsoft"},
    {"s": "NVDA", "n": "Nvidia"}, {"s": "AMZN", "n": "Amazon"},
    {"s": "GOOGL", "n": "Alphabet"}, {"s": "META", "n": "Meta"},
    {"s": "TSLA", "n": "Tesla"}, {"s": "MELI", "n": "MercadoLibre"},
    {"s": "KO", "n": "Coca-Cola"}, {"s": "BRK-B", "n": "Berkshire Hathaway"},
    {"s": "JPM", "n": "JPMorgan"}, {"s": "V", "n": "Visa"},
    {"s": "DIS", "n": "Disney"}, {"s": "NFLX", "n": "Netflix"},
    {"s": "AMD", "n": "AMD"}, {"s": "PBR", "n": "Petrobras"},
    {"s": "BABA", "n": "Alibaba"}, {"s": "XOM", "n": "Exxon Mobil"},
    {"s": "WMT", "n": "Walmart"}, {"s": "NU", "n": "Nu Holdings"},
    {"s": "SPY", "n": "S&P 500 (ETF)"}, {"s": "QQQ", "n": "Nasdaq 100 (ETF)"},
]

_cache: Dict[str, tuple] = {}      # símbolo → (ts, cotización cruda de Yahoo | None)
_lock = threading.Lock()


def _pedir_yahoo(simbolos: List[str]) -> List[dict]:
    """Un pedido a Yahoo con todos los `simbolos`. Devuelve las cotizaciones
    crudas (las que Yahoo conozca). Puede tirar: el que llama decide."""
    from yfinance.data import YfData
    j = YfData().get_raw_json(_URL, params={
        "symbols": ",".join(simbolos), "formatted": "false",
        "lang": "en-US", "region": "US",
    }, timeout=6)
    return ((j or {}).get("quoteResponse") or {}).get("result") or []


def _cotizaciones(simbolos: Iterable[str], pedir: Callable = None,
                  tope: float = _yahoo.TOPE_PANTALLA_SEG) -> Dict[str, dict]:
    """{símbolo: cotización cruda} de los que Yahoo conoce, cacheado 60 s.
    Un símbolo que Yahoo no conoce también se cachea (como None) para no
    volver a pedirlo en cada refresco."""
    pedir = pedir or _pedir_yahoo
    ahora = time.time()
    out: Dict[str, dict] = {}
    faltan: List[str] = []
    with _lock:
        for s in dict.fromkeys(simbolos):
            hit = _cache.get(s)
            if hit and ahora - hit[0] < _TTL_S:
                if hit[1] is not None:
                    out[s] = hit[1]
            else:
                faltan.append(s)
    for i in range(0, len(faltan), _LOTE):
        lote = faltan[i:i + _LOTE]
        try:
            crudas = _yahoo.con_tope(pedir, lote, tope=tope, que="pre/post de Yahoo")
        except Exception as ex:
            # Sin respuesta NO se cachea: el próximo refresco vuelve a probar.
            log.warning("fuera_de_horario: Yahoo no dio el pre/post de %d símbolos: %r", len(lote), ex)
            continue
        por_simbolo = {q.get("symbol"): q for q in crudas if q.get("symbol")}
        with _lock:
            for s in lote:
                q = por_simbolo.get(s)
                _cache[s] = (ahora, q)
                if q is not None:
                    out[s] = q
    return out


def _vaciar_cache() -> None:
    with _lock:
        _cache.clear()


def _es_de_eeuu(q: dict) -> bool:
    # El CEDEAR AAPL.BA también viene de Yahoo, con su propio estado (PREPRE)
    # y sin pre/post. Sólo cuenta lo que opera en EE.UU.
    return (q.get("market") or "us_market") == "us_market"


def sesion_de(spy: Optional[dict]) -> Optional[str]:
    """'pre' · 'post' · 'post_cerrado' · None, a partir de la cotización de SPY."""
    if not spy:
        return None
    estado = (spy.get("marketState") or "").upper()
    if estado == "PRE":
        return "pre"
    if estado == "POST":
        return "post"
    if estado in ("POSTPOST", "PREPRE", "CLOSED"):
        hubo_post = (spy.get("postMarketChangePercent") is not None
                     and (spy.get("postMarketTime") or 0) > (spy.get("regularMarketTime") or 0))
        return "post_cerrado" if hubo_post else None
    return None


def _pct(q: dict, sesion: Optional[str]) -> Optional[float]:
    """El % de pre o post de una cotización, o None si no operó desde el último
    cierre (o si es de otro momento)."""
    if not sesion or not _es_de_eeuu(q):
        return None
    campo = "preMarket" if sesion == "pre" else "postMarket"
    pct = q.get(f"{campo}ChangePercent")
    hora = q.get(f"{campo}Time") or 0
    cierre = q.get("regularMarketTime") or 0
    if pct is None or hora <= cierre:
        return None
    try:
        return round(float(pct), 4)
    except (TypeError, ValueError):
        return None


def _hora_ar(hora_ny: _dt.time, ahora: _dt.datetime) -> str:
    """Una hora de Nueva York (de hoy) en hora argentina, 'H:MM'."""
    hoy_ny = ahora.astimezone(ZONA_NY).date()
    t = _dt.datetime.combine(hoy_ny, hora_ny, tzinfo=ZONA_NY).astimezone(ZONA_AR)
    return f"{t.hour}:{t.minute:02d}"


def byma_abierto(ahora: _dt.datetime) -> bool:
    """BYMA opera de 11 a 17 hora argentina, de lunes a viernes. Desde que abre,
    un CEDEAR tiene precio propio y su anticipo de EE.UU. deja de mostrarse
    (pasa del 1/11 a marzo: el pre de EE.UU. termina 11:30)."""
    a = ahora.astimezone(ZONA_AR)
    return a.weekday() < 5 and _dt.time(11, 0) <= a.time() < _dt.time(17, 0)


def limpiar_simbolos(texto: str) -> List[str]:
    crudos = [s.strip().upper() for s in (texto or "").split(",") if s.strip()]
    return [s for s in dict.fromkeys(crudos) if _SIMBOLO_RE.match(s)][:MAX_SIMBOLOS]


def estado(simbolos: List[str], listas: bool = False, ahora: _dt.datetime = None,
           pedir: Callable = None) -> dict:
    """Lo que devuelve `/api/fuera-de-horario`.

    {
      sesion: 'pre'|'post'|'post_cerrado'|None,
      cierra: '10:30' (hora argentina en que termina la franja; None si cerrada),
      byma_abierto: bool,
      actualizado: ISO,
      cotizaciones: {símbolo: {pct, precio}}   — pct None = no operó todavía,
      listas: {indices, adrs, populares}       — sólo con listas=True,
    }
    Los símbolos que Yahoo no conoce no aparecen en `cotizaciones`.
    """
    ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
    pedidos = list(simbolos)
    if listas:
        for grupo in (INDICES, ADRS, POPULARES):
            pedidos += [x["s"] for x in grupo]
    crudas = _cotizaciones(["SPY", *pedidos], pedir=pedir)
    sesion = sesion_de(crudas.get("SPY"))

    cotizaciones = {}
    if sesion:
        campo = "preMarketPrice" if sesion == "pre" else "postMarketPrice"
        for s in dict.fromkeys(pedidos):
            q = crudas.get(s)
            if not q or not _es_de_eeuu(q):
                continue
            pct = _pct(q, sesion)
            cotizaciones[s] = {"pct": pct, "precio": q.get(campo) if pct is not None else None}

    cierra = None
    if sesion == "pre":
        cierra = _hora_ar(_dt.time(9, 30), ahora)
    elif sesion == "post":
        cierra = _hora_ar(_dt.time(20, 0), ahora)

    out = {
        "sesion": sesion,
        "cierra": cierra,
        "byma_abierto": byma_abierto(ahora),
        "actualizado": ahora.astimezone(_dt.timezone.utc).isoformat(timespec="seconds"),
        "cotizaciones": cotizaciones,
    }
    if listas:
        out["listas"] = {"indices": INDICES, "adrs": ADRS, "populares": POPULARES}
    return out
