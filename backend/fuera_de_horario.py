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

# ─── A qué acción de EE.UU. mira cada tenencia ──────────────────────────────
# COPIA de las dos tablas de frontend/src/utils/tickers.js (CEDEAR_EN_EEUU,
# CEDEAR_ESPECIE_ALIAS y ADR_DE_ACCION_AR): la pantalla y el chat tienen que
# traducir igual. tests/test_fuera_de_horario.py compara las dos copias —si
# cambiás una sin la otra, falla.
CEDEAR_EN_EEUU = {"DISN": "DIS", "BRKB": "BRK-B", "NOKA": "NOK"}
CEDEAR_ESPECIE_ALIAS = {"SI": "SID"}
ADR_DE_ACCION_AR = {
    "GGAL": "GGAL", "BMA": "BMA", "CEPU": "CEPU", "EDN": "EDN", "BBAR": "BBAR", "SUPV": "SUPV",
    "YPFD": "YPF", "PAMP": "PAM", "TGSU2": "TGS", "CRES": "CRESY", "TECO2": "TEO",
    "LOMA": "LOMA", "IRSA": "IRS",
}


def referencia_en_eeuu(clave_precio: Optional[str], asset_type: Optional[str] = None):
    """La acción de EE.UU. que anticipa a una tenencia, o None. Mismas reglas
    que `referenciaEnEEUU` (utils/fueraDeHorario.js):

      · '<X>.BA' de un CEDEAR → su acción en EE.UU. ('eeuu'; DISN → DIS).
      · '<X>.BA' de una acción argentina con ADR → el ADR ('adr'; YPFD → YPF).
      · '<X>.BA' de cualquier otra cosa (bono, acción sin ADR) → None: el ticker
        local tal cual en Yahoo sería OTRA empresa (AGRO → Adecoagro).
      · Un ticker de EE.UU. (broker del exterior) → él mismo ('propio'), salvo
        cripto, bonos, fondos y efectivo.

    `clave_precio` es la de `snapshots_job.position_price_key`: la MISMA con
    que el chat valúa la tenencia. Devuelve (símbolo, vía) o None.
    """
    if not clave_precio:
        return None
    from cripto import CRYPTO_SYMBOLS
    from ai.trade_tickers import CEDEAR_TICKERS, AR_STOCK_TICKERS
    from behavioral import _is_ar_bond
    clave = str(clave_precio).upper()
    tipo = (asset_type or "").upper()
    if clave.startswith("FCI:") or tipo in ("FUND", "BOND", "CRYPTO"):
        return None
    if clave.endswith(".BA"):
        base = clave[:-3]
        if base in CRYPTO_SYMBOLS:
            return None
        if base in AR_STOCK_TICKERS and tipo != "CEDEAR":
            adr = ADR_DE_ACCION_AR.get(base)
            return (adr, "adr") if adr else None
        especie = CEDEAR_ESPECIE_ALIAS.get(base, base)
        if base in CEDEAR_TICKERS or especie in CEDEAR_TICKERS or tipo == "CEDEAR":
            return (CEDEAR_EN_EEUU.get(especie, especie), "eeuu")
        return None
    if clave in CRYPTO_SYMBOLS or clave in ("USD", "USDT", "USDC", "ARS") or _is_ar_bond(clave):
        return None
    return (clave, "propio")


def resumen_de_lotes(lotes: list, datos: dict, tc_pesos: Optional[float] = None, top: int = 6) -> Optional[dict]:
    """El pre/post de una cartera YA valuada, para el chat y el mail. None si no
    hay pre ni post o si ninguna tenencia lo tiene.

    Cada lote: {asset, valor (USD), ref: (símbolo, vía) | None}. La plata es
    valor × % (la misma regla que la pantalla). Con BYMA abierta los CEDEARs y
    las acciones argentinas ya tienen precio propio: su anticipo no se cuenta.
    `tc_pesos`: el dólar con que el chat pasa pesos a dólares, para decir cuánto
    mueve un 1 % del CCL sobre lo que está en pesos.
    """
    sesion = (datos or {}).get("sesion")
    if not sesion:
        return None
    cot = datos.get("cotizaciones") or {}
    total_valor = sum(float(l.get("valor") or 0) for l in lotes)
    por_activo: Dict[str, dict] = {}
    sin_operar = set()
    exacto = anticipo = anticipo_valor = 0.0
    for l in lotes:
        ref = l.get("ref")
        if not ref:
            continue
        simbolo, via = ref
        if via != "propio" and datos.get("byma_abierto"):
            continue
        q = cot.get(simbolo)
        if not q:
            continue
        if q.get("pct") is None:
            sin_operar.add(l.get("asset"))
            continue
        valor = float(l.get("valor") or 0)
        usd = valor * float(q["pct"]) / 100
        if via == "propio":
            exacto += usd
        else:
            anticipo += usd
            anticipo_valor += valor
        a = por_activo.setdefault(l.get("asset"), {
            "asset": l.get("asset"), "sigue_a": simbolo, "via": via,
            "pct": round(float(q["pct"]), 2), "usd": 0.0})
        a["usd"] += usd
    if not por_activo and not sin_operar:
        return None
    total = exacto + anticipo
    nombre = "pre-mercado" if sesion == "pre" else "post-mercado"

    def _usd(v):
        from money_fmt import fmt_money
        s = fmt_money(round(v, 2), "USD")
        return s if v < 0 else "+" + s

    def _pct(v):
        from money_fmt import fmt_num
        return f"{fmt_num(v, 2, signed=True)}%"

    activos = sorted(por_activo.values(), key=lambda a: abs(a["usd"]), reverse=True)
    for a in activos:
        a["usd"] = round(a["usd"], 2)
        a["usd_txt"] = _usd(a["usd"])
        a["pct_txt"] = _pct(a["pct"])
        a["como"] = {"propio": "la acción misma", "eeuu": "CEDEAR: sigue a su acción en Nueva York",
                     "adr": "acción argentina: sigue a su ADR en Nueva York"}[a["via"]]
    pct_cartera = (total / total_valor * 100) if total_valor > 0 else None
    out = {
        "sesion": nombre if sesion != "post_cerrado" else "post-mercado (ya cerró)",
        "abierto": sesion in ("pre", "post"),
        "cierra_hora_argentina": datos.get("cierra"),
        "usd": round(total, 2),
        "usd_txt": _usd(total),
        "pct_sobre_la_cartera": None if pct_cartera is None else round(pct_cartera, 2),
        "pct_sobre_la_cartera_txt": None if pct_cartera is None else _pct(pct_cartera),
        "exacto_usd_txt": _usd(exacto),
        "anticipo_usd_txt": _usd(anticipo) if anticipo_valor > 0 else None,
        "activos": activos[:top],
        "sin_operar_todavia": sorted(a for a in sin_operar if a),
    }
    if anticipo_valor > 0 and tc_pesos:
        from money_fmt import fmt_money
        out["ccl_1pct_en_pesos_txt"] = fmt_money(round(anticipo_valor * tc_pesos * 0.01), "ARS")
    return out


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
    if ahora is None:
        # El reloj compartido de Rendi (las pruebas lo fijan): sin esto, si BYMA
        # está abierta dependía de la hora a la que corriera la suite.
        import fechas
        ahora = fechas.ahora_art().replace(tzinfo=ZONA_AR)
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


# ─── Lo que ya pasó: el post-mercado de anoche y el pre de esta mañana ──────
# Para el mail de las 11:00. MEDIDO 2026-10-15: apenas arranca el pre-mercado,
# la cotización en vivo de Yahoo ya NO trae el post de la noche anterior
# (postMarketChangePercent vacío a las 9:26 de NY), y en la rueda normal
# tampoco el pre. El historial de velas de 5 minutos con `prepost=True` sí trae
# las dos franjas (AAPL: post del 14 hasta las 19:55; pre del 15 hasta las 9:25).
# Contra qué se mide: el CIERRE OFICIAL de la rueda anterior (vela diaria), el
# mismo que usa la cotización en vivo, no la última vela de 5 minutos (que
# difiere por la subasta de cierre: NVDA 221,50 contra 221,30 oficial).

_franjas_cache: Dict[tuple, tuple] = {}   # (símbolo, día NY) → (ts, franjas)
_FRANJAS_TTL_S = 600


def franjas_de_velas(velas: list, cierres: dict, hoy_ny: _dt.date) -> dict:
    """El post de la rueda anterior y el pre de hoy, a partir de las velas.

    `velas`: [(datetime con zona de NY, cierre de la vela)], de 5 minutos.
    `cierres`: {fecha: cierre oficial} de las ruedas (velas diarias).
    Devuelve {"post": {pct, dia, hasta} | None, "pre": {pct, dia, hasta} | None},
    con pct en PUNTOS (0,64 = 0,64 %), contra el cierre oficial de la rueda
    anterior a hoy.
    """
    anteriores = sorted(d for d in cierres if d < hoy_ny)
    if not anteriores:
        return {"post": None, "pre": None}
    previa = anteriores[-1]
    base = cierres[previa]
    if not base:
        return {"post": None, "pre": None}

    def _ultima(dia, desde, hasta):
        dentro = [(t, c) for t, c in velas
                  if t.date() == dia and desde <= t.time() < hasta and c]
        return max(dentro, key=lambda x: x[0]) if dentro else None

    out = {}
    for franja, dia, desde, hasta in (("post", previa, _dt.time(16, 0), _dt.time(20, 0)),
                                      ("pre", hoy_ny, _dt.time(4, 0), _dt.time(9, 30))):
        u = _ultima(dia, desde, hasta)
        out[franja] = None if u is None else {
            "pct": round((float(u[1]) / float(base) - 1) * 100, 4),
            "dia": dia.isoformat(),
            "hasta": u[0].strftime("%H:%M"),
        }
    return out


def _traer_velas(simbolo: str):
    """Velas de 5 minutos con pre y post, y cierres diarios oficiales (5 días)."""
    import yfinance as yf
    t = yf.Ticker(simbolo)
    h5 = t.history(period="5d", interval="5m", prepost=True)
    hd = t.history(period="5d", interval="1d")
    velas = [(ts.tz_convert(ZONA_NY).to_pydatetime(), float(c))
             for ts, c in zip(h5.index, h5["Close"]) if c == c]
    cierres = {ts.tz_convert(ZONA_NY).date(): float(c)
               for ts, c in zip(hd.index, hd["Close"]) if c == c}
    return velas, cierres


def franjas(simbolos: List[str], ahora: _dt.datetime = None, traer: Callable = None) -> Dict[str, dict]:
    """{símbolo: franjas_de_velas(...)} para estos símbolos de EE.UU. Un pedido
    por símbolo, en paralelo, con el tope de los trabajos de fondo (lo usa el
    mail); cacheado 10 minutos por símbolo y día."""
    traer = traer or _traer_velas
    if ahora is None:
        import fechas
        ahora = fechas.ahora_art().replace(tzinfo=ZONA_AR)
    hoy_ny = ahora.astimezone(ZONA_NY).date()
    t0 = time.time()
    out, faltan = {}, []
    for s in dict.fromkeys(simbolos):
        hit = _franjas_cache.get((s, hoy_ny))
        if hit and t0 - hit[0] < _FRANJAS_TTL_S:
            out[s] = hit[1]
        else:
            faltan.append(s)
    if faltan:
        crudos, _ = _yahoo.varios(traer, faltan, tope=_yahoo.TOPE_FONDO_SEG, que="velas pre/post")
        for s, (velas, cierres) in crudos.items():
            f = franjas_de_velas(velas, cierres, hoy_ny)
            _franjas_cache[(s, hoy_ny)] = (t0, f)
            out[s] = f
    return out


def _nombre_de_la_noche(dia_iso: str, hoy_ny: _dt.date) -> str:
    d = _dt.date.fromisoformat(dia_iso)
    if d == hoy_ny - _dt.timedelta(days=1):
        return "anoche"
    dias = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    return f"el {dias[d.weekday()]} a la noche"


def resumen_de_la_manana(lotes: list, por_simbolo: Dict[str, dict], tc_pesos: Optional[float] = None,
                         ahora: _dt.datetime = None) -> Optional[dict]:
    """Para el mail: cuánto movió la cartera el post-mercado de la noche anterior
    y el pre-mercado de hoy. Misma cuenta que la pantalla y el chat
    (`resumen_de_lotes`). None si ninguna de las dos franjas tiene nada."""
    if ahora is None:
        import fechas
        ahora = fechas.ahora_art().replace(tzinfo=ZONA_AR)
    ny = ahora.astimezone(ZONA_NY)
    out = {}
    for franja in ("post", "pre"):
        cot = {s: {"pct": f[franja]["pct"]} for s, f in por_simbolo.items() if f.get(franja)}
        if not cot:
            continue
        # Los CEDEARs SÍ cuentan: a las 11 BYMA recién abre, y lo que se movió su
        # acción de noche es justo lo que todavía no estaba en su precio.
        r = resumen_de_lotes(lotes, {"sesion": "post_cerrado" if franja == "post" else "pre",
                                     "byma_abierto": False, "cotizaciones": cot}, tc_pesos=tc_pesos)
        if not r or not r["activos"]:
            continue
        dia = next(f[franja]["dia"] for f in por_simbolo.values() if f.get(franja))
        if franja == "post":
            r["cuando"] = _nombre_de_la_noche(dia, ny.date())
            r["abierto"] = False
        else:
            r["abierto"] = ny.time() < _dt.time(9, 30) and ny.weekday() < 5
            r["cuando"] = "esta mañana"
        r.pop("sin_operar_todavia", None)
        out[franja] = r
    return out or None


# ─── Para las alertas: ¿el movimiento de ahora tiene operaciones detrás? ────
# Fuera de la rueda opera poca gente y UNA operación suelta marca un salto
# falso. MEDIDO 2026-10-15: PAM figuraba +5,26 % en el post del 14 por una sola
# vela, la de las 16:15, y nada más. Una alerta que salta por eso le enseña al
# usuario a ignorar las alertas. Por eso una alerta fuera de la rueda pide al
# menos MIN_VELAS velas de 5 minutos con operaciones en la franja de hoy.
MIN_VELAS = 3

_VENTANAS = {"pre": (_dt.time(4, 0), _dt.time(9, 30)), "post": (_dt.time(16, 0), _dt.time(20, 0))}


def velas_en_franja(velas: list, hoy_ny: _dt.date, sesion: str) -> int:
    """Cuántas velas de 5 minutos con operaciones tuvo HOY la franja `sesion`
    ('pre' o 'post'). `velas` = [(datetime de NY, cierre)], como `_traer_velas`
    (Yahoo sólo arma velas donde hubo operaciones)."""
    ventana = _VENTANAS.get(sesion)
    if not ventana:
        return 0
    desde, hasta = ventana
    return sum(1 for t, c in velas if c and t.date() == hoy_ny and desde <= t.time() < hasta)


def con_operaciones(simbolos: List[str], sesion: str, ahora: _dt.datetime = None,
                    traer: Callable = None) -> Dict[str, int]:
    """{símbolo: velas de hoy en la franja}. Un pedido de velas por símbolo,
    sólo para los que ya cruzaron el umbral de alguna alerta (son pocos)."""
    traer = traer or _traer_velas
    if ahora is None:
        import fechas
        ahora = fechas.ahora_art().replace(tzinfo=ZONA_AR)
    hoy_ny = ahora.astimezone(ZONA_NY).date()
    crudos, _ = _yahoo.varios(traer, list(dict.fromkeys(simbolos)),
                              tope=_yahoo.TOPE_FONDO_SEG, que="velas para alertas")
    return {s: velas_en_franja(v, hoy_ny, sesion) for s, (v, _c) in crudos.items()}
