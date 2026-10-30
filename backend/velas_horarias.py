"""Velas de 1 hora y de 4 horas para el gráfico técnico de la ficha.

QUÉ ES. El menú «1D ▾» del gráfico suma «1H» y «4H» (Nico, 30/10). Cada vela es
una hora (o un bloque de cuatro) y la ÚLTIMA es la que está en curso: se mueve
sola mientras la pantalla está a la vista, porque la ficha vuelve a pedir cada
60 s (frontend/src/utils/velasPorHora.js).

DE DÓNDE. Yahoo, velas de 1 hora (`interval='1h'`, hasta ~2 años; medido el
30/10 bien en AAPL, AAPL.BA, GGAL.BA y BTC-USD). La última que manda es la hora
en curso: la vela viva sale de la MISMA descarga, no de otro precio.

4 HORAS. Yahoo no las tiene: se arman juntando las de 1 hora, cortadas como
TradingView, desde la apertura de cada rueda (alerts_engine._SESION_US y
_SESION_BYMA, LA definición del horario de Rendi):
  · Nueva York: 9:30–13:30 y 13:30–16:00, hora de Nueva York;
  · BYMA: 11:00–15:00 y 15:00–17:00, hora argentina;
  · cripto: cada 4 horas corridas desde las 00:00 UTC (21:00 hora argentina).
El bloque en curso incluye la hora en curso.

QUÉ SERIE. La misma que el gráfico diario: `tecnico.serie` decide qué ticker
(la acción de afuera o la de BYMA) y si se convierte con el MEP. Acá no se
copia esa decisión. Las de BYMA ('.BA') pasan por la MISMA lista de cambios de
ratio que las diarias (`velas_diarias._empalmar`): Yahoo tampoco corrige el
ratio de un CEDEAR en las de 1 hora. La conversión, con el dólar de CADA día
(`tecnico._convertir`, la regla del diario).

LAS CUENTAS. Medias de 50 y 200, RSI, ADX, Squeeze y Bandas de Bollinger con
las funciones de tecnico.py, sobre toda la historia de horas: la media de 200
en 1 hora son 200 HORAS. La lectura (tendencia, tarjetas), Señales, Tu lista y
los avisos siguen siendo DIARIOS: esto es sólo el dibujo.

SIN TABLA. Nada se guarda en la base: se pide cuando alguien elige 1H o 4H.
En memoria y compartido entre usuarios, por ticker: la historia se renueva cada
10 minutos y los últimos 2 días cada 60 s (el patrón de `_PRICE_CACHE` de
main.py y `_QUOTE_CACHE` de home/market.py). Una descarga sirve para 1 h y 4 h.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Cada cuánto es una vela, en minutos.
CADAS = {"1h": 60, "4h": 240}
# Lo que se le pide a Yahoo: toda la historia de horas que da (~2 años) y, para
# que la vela en curso se mueva, los últimos 2 días.
PERIODO_HISTORIA = "730d"
PERIODO_RECIENTE = "2d"
TTL_HISTORIA_SEG = 10 * 60
TTL_RECIENTE_SEG = 60
# Si Yahoo no contestó, no se le vuelve a pedir ese ticker hasta pasado esto:
# cada pedido sin respuesta espera el tope entero (8 s).
ESPERA_TRAS_FALLA_SEG = 60
# Las velas de 1 hora que se guardan por ticker (las más nuevas): una cripto
# cotiza 24 por día y 2 años serían 17.500. Con 6.000 alcanza para lo que se
# manda a la pantalla más las 200 de antes que pide la media de 200.
VELAS_GUARDADAS = 6000
# Cuántos tickers en memoria a la vez (cada uno ~1 MB): el que hace más que
# nadie mira se va primero.
TICKERS_MAXIMOS = 40
# Lo que va a la pantalla: las 1.000 velas más nuevas (1 hora en Nueva York:
# ~7 meses; 4 horas: los 2 años). Es lo que pesa la serie diaria (~750 días).
VELAS_A_LA_PANTALLA = 1000
# Las cuentas se hacen sobre lo que va a la pantalla más estas velas de antes:
# la media de 200 necesita 200, y el RSI y el ADX (promedios de Wilder, que
# arrastran memoria) con 600 de antes ya dan lo mismo que con toda la historia
# (lo que pesa la vela de hace 600 es (13/14)^600, ~10⁻¹⁹). Con las 6.000 de
# una cripto eran ~0,5 s por pedido.
VELAS_DE_CALENTAMIENTO = 600

# El horario de cada rueda: zona horaria y (hora, minuto) de apertura y cierre.
ZONAS = {"us": "America/New_York", "byma": "America/Argentina/Buenos_Aires", "cripto": "UTC"}


def _sesion(mercado: str):
    """(abre, cierra) en minutos del día local; cripto, el día entero."""
    if mercado == "cripto":
        return 0, 24 * 60
    from alerts_engine import _SESION_BYMA, _SESION_US
    h1, m1, h2, m2 = _SESION_BYMA if mercado == "byma" else _SESION_US
    return h1 * 60 + m1, h2 * 60 + m2


def _ahora() -> float:
    return time.time()


# ─── Yahoo, en memoria ───────────────────────────────────────────────────────
# ticker → {"velas": [(t, fecha, minuto, o, h, l, c, v)], "t_hist", "t_rec",
#           "actualizada", "usada"}. Tuplas y no dicts: ~6 veces menos memoria.
_CACHE: dict = {}
# Lo ya armado para la pantalla, por (ticker, cada, conversión): mientras Yahoo
# no traiga nada nuevo (`actualizada`), el refresco de cada minuto de cada
# persona sale de acá y no rehace las cuentas.
_ARMADAS: dict = {}
_LOCK = threading.Lock()
_LOCKS_TICKER: dict = {}
_FALLAS: dict = {}   # ticker → cuándo falló la última descarga


def _numero(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _velas_de(df, mercado: str) -> list:
    """[(t, fecha, minuto, o, h, l, c, v)] de una tabla de Yahoo de 1 hora:
    `t` el inicio de la vela (segundos UTC), `fecha` el día de la rueda en su
    hora local (el de la vela DIARIA a la que pertenece: hora de Nueva York,
    argentina o UTC en cripto) y `minuto` el minuto del día local. La regla de
    vela sana es la de las diarias (`velas_diarias._velas_de`): sin cierre
    válido no hay vela; con el máximo o el mínimo roto se guarda sólo el cierre."""
    out = []
    if df is None or getattr(df, "empty", True):
        return out
    idx = df.index
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    locales = idx.tz_convert(ZONAS.get(mercado, "UTC"))
    segundos = idx.asi8 // 10**9
    fechas = [f.isoformat() for f in locales.date]
    minutos = locales.hour * 60 + locales.minute
    col = lambda k: df[k].tolist() if k in df.columns else [None] * len(df)   # noqa: E731
    for k, (o, h, l, c, vol) in enumerate(zip(col("Open"), col("High"), col("Low"), col("Close"), col("Volume"))):
        o, h, l, c, vol = (_numero(x) for x in (o, h, l, c, vol))
        if c is None or c <= 0:
            continue
        if not (h and l and h >= c >= l > 0):
            h = l = None
        out.append((int(segundos[k]), fechas[k], int(minutos[k]),
                    o if o and o > 0 else None, h, l, c, vol if vol and vol >= 0 else None))
    return out


def _bajar(ticker: str, periodo: str, mercado: str) -> list:
    """Las velas de 1 hora de `ticker` (sólo por pricing.yahoo, con su tope)."""
    from pricing import yahoo
    tabla = yahoo.descargar(ticker, period=periodo, interval="1h", auto_adjust=False,
                            group_by="ticker", que="velas de 1 hora")
    if tabla is None or tabla.empty or ticker not in tabla.columns.get_level_values(0):
        return []
    return _velas_de(tabla[ticker].dropna(how="all"), mercado)


def _lock_de(ticker: str) -> threading.Lock:
    with _LOCK:
        return _LOCKS_TICKER.setdefault(ticker, threading.Lock())


def _podar():
    """Con más de TICKERS_MAXIMOS en memoria, se va el que hace más que nadie mira."""
    with _LOCK:
        while len(_CACHE) > TICKERS_MAXIMOS:
            viejo = min(_CACHE, key=lambda t: _CACHE[t]["usada"])
            _CACHE.pop(viejo, None)
        for clave in [k for k in _ARMADAS if k[0] not in _CACHE]:
            _ARMADAS.pop(clave, None)


def velas_1h(ticker: str, mercado: str):
    """(velas de 1 hora, cuándo se bajaron por última vez en segundos UTC) de
    `ticker`, de la memoria compartida o de Yahoo. ([], None) si Yahoo no las
    tiene o no contestó y no hay nada guardado."""
    with _lock_de(ticker):
        ahora = _ahora()
        e = _CACHE.get(ticker)
        fallo = ahora - _FALLAS.get(ticker, -1e12) < ESPERA_TRAS_FALLA_SEG
        if not fallo and (not e or ahora - e["t_hist"] >= TTL_HISTORIA_SEG):
            try:
                velas = _bajar(ticker, PERIODO_HISTORIA, mercado)
            except Exception as ex:
                log.warning("velas de 1 hora de %s: Yahoo falló: %r", ticker, ex)
                velas = []
            if velas:
                e = {"velas": velas[-VELAS_GUARDADAS:], "t_hist": ahora, "t_rec": ahora, "actualizada": ahora}
                _FALLAS.pop(ticker, None)
            else:
                _FALLAS[ticker] = ahora
        elif not fallo and ahora - e["t_rec"] >= TTL_RECIENTE_SEG:
            try:
                nuevas = _bajar(ticker, PERIODO_RECIENTE, mercado)
            except Exception as ex:
                log.warning("velas de 1 hora recientes de %s: Yahoo falló: %r", ticker, ex)
                nuevas = []
            if nuevas:
                # Lo reciente reemplaza desde su primera vela: la hora en curso
                # cambia en cada descarga y puede haber empezado otra.
                corte = nuevas[0][0]
                velas = [v for v in e["velas"] if v[0] < corte] + nuevas
                e = {**e, "velas": velas[-VELAS_GUARDADAS:], "t_rec": ahora, "actualizada": ahora}
                _FALLAS.pop(ticker, None)
            else:
                _FALLAS[ticker] = ahora
        if not e:
            return [], None
        e["usada"] = ahora
        _CACHE[ticker] = e
    _podar()
    return e["velas"], e["actualizada"]


# ─── De la hora a la serie del gráfico ───────────────────────────────────────

def _como_vela(x) -> dict:
    t, fecha, minuto, o, h, l, c, v = x
    return {"t": t, "date": fecha, "minuto": minuto, "open": o, "high": h, "low": l, "close": c, "volume": v}


def bloques(velas: list, cada: str, mercado: str) -> list:
    """Las velas de `cada` ('1h' o '4h') a partir de las de 1 hora (dicts de
    `_como_vela`). Un bloque de 4 horas se corta desde la apertura de su rueda,
    como TradingView: apertura de la primera hora, máximo y mínimo del bloque,
    cierre de la última, volumen sumado. Una hora con el máximo roto aporta su
    apertura y su cierre (como la completa `velaCompleta` de la pantalla)."""
    if cada != "4h":
        return velas
    abre, _ = _sesion(mercado)
    largo = CADAS["4h"]
    out, clave = [], None
    for v in velas:
        b = (v["minuto"] - abre) // largo
        if (v["date"], b) != clave:
            clave = (v["date"], b)
            inicio = abre + b * largo
            out.append({"t": v["t"] - (v["minuto"] - inicio) * 60, "date": v["date"], "minuto": inicio,
                        "open": v["open"], "high": None, "low": None, "close": v["close"], "volume": None})
        x = out[-1]
        altos = [y for y in (v["high"], v["open"], v["close"]) if y]
        bajos = [y for y in (v["low"], v["open"], v["close"]) if y]
        x["high"] = max([x["high"]] + altos if x["high"] else altos)
        x["low"] = min([x["low"]] + bajos if x["low"] else bajos)
        x["close"] = v["close"]
        if v["volume"] is not None:
            x["volume"] = (x["volume"] or 0) + v["volume"]
    return out


def _fin_de(v: dict, cada: str, mercado: str) -> int:
    """Cuándo termina la vela (segundos UTC): su largo o el cierre de la rueda."""
    _, cierra = _sesion(mercado)
    hasta = min(v["minuto"] + CADAS[cada], cierra)
    return v["t"] + (hasta - v["minuto"]) * 60


def _serie_elegida(conn, asset: str, moneda: str, local: bool):
    """Qué ticker y si se convierte: lo que decide `tecnico.serie` para el
    gráfico diario (no se copia esa regla). None si el activo no tiene serie."""
    import tecnico
    s = tecnico.serie(conn, asset, moneda, local)
    if not s.get("velas"):
        return None
    return {"ticker": s["ticker"], "convertida": s["convertida"]}


def _armar(abrir, ticker: str, crudas: list, cada: str, mercado: str, por):
    """Las velas de `cada` y sus puntos para la pantalla (las últimas
    VELAS_A_LA_PANTALLA, con sus cuentas). `por`: None, 'dividir' (pesos →
    dólares) o 'multiplicar', con el MEP de cada día. None si no queda nada."""
    import tecnico
    import velas_diarias
    velas = [_como_vela(x) for x in crudas]
    with abrir() as conn:
        if ticker.endswith(".BA"):
            import cambios_ratio
            velas = velas_diarias._empalmar(velas, cambios_ratio.para_el_grafico(conn, ticker))
        if por:
            velas = tecnico._convertir(conn, velas, por)
    velas = bloques(velas, cada, mercado)
    velas = velas[-(VELAS_A_LA_PANTALLA + VELAS_DE_CALENTAMIENTO):]
    if not velas:
        return None
    primero = max(0, len(velas) - VELAS_A_LA_PANTALLA)
    puntos = tecnico.puntos_del_grafico(velas, tecnico.indicadores(velas), primero)
    for v, p in zip(velas[primero:], puntos):
        p["t"] = v["t"]
    return {"ultima": velas[-1], "puntos": puntos}


def para_la_ficha(abrir, asset: str, cada: str = "1h", moneda: str = "usd", local: bool = False,
                  desde: int = None) -> dict:
    """Lo que dibuja el gráfico en 1H o 4H. `abrir()` abre la base (la de
    main.db_abierta): se usa dos veces y se cierra mientras se espera a Yahoo,
    para no dejar una transacción abierta esos segundos (Postgres). `desde`:
    sólo los puntos que empiezan en ese momento o después (el refresco de cada
    60 s pide desde su última vela, no la serie entera).

    {disponible, ticker, convertida, mercado, cada, sesion, en_horario,
     actualizada, puntos: [{d, t, o, h, l, c, s50, s200, …, enCurso?}]}.
    `disponible: False` con `motivo`: 'sin_serie' (no hay gráfico diario) o
    'sin_datos' (Yahoo no tiene velas de 1 hora o no contestó)."""
    from alerts_engine import rueda_en_horario
    from home.market import mercado_de

    moneda = "ars" if moneda == "ars" else "usd"
    cada = cada if cada in CADAS else "1h"
    base = {"asset": (asset or "").upper(), "moneda": moneda, "cada": cada}
    with abrir() as conn:
        eleccion = _serie_elegida(conn, asset, moneda, local)
    if not eleccion:
        return {**base, "disponible": False, "motivo": "sin_serie"}
    ticker = eleccion["ticker"]
    mercado = mercado_de(ticker)
    crudas, actualizada = velas_1h(ticker, mercado)     # Yahoo, sin la base abierta
    if not crudas:
        return {**base, "disponible": False, "motivo": "sin_datos", "ticker": ticker}
    por = ("dividir" if moneda == "usd" else "multiplicar") if eleccion["convertida"] else None
    clave = (ticker, cada, por)
    hecha = _ARMADAS.get(clave)
    if not hecha or hecha["actualizada"] != actualizada:
        hecha = _armar(abrir, ticker, crudas, cada, mercado, por)
        if not hecha:
            return {**base, "disponible": False, "motivo": "sin_datos", "ticker": ticker}
        hecha["actualizada"] = actualizada
        with _LOCK:
            _ARMADAS[clave] = hecha
    puntos, ultima = hecha["puntos"], hecha["ultima"]
    if desde is not None:
        puntos = puntos[next((i for i, p in enumerate(puntos) if p["t"] >= desde), len(puntos)):]
    # La vela en curso se marca al servir (lo armado se comparte y la hora pasa).
    if puntos and puntos[-1]["t"] == ultima["t"] and _ahora() < _fin_de(ultima, cada, mercado):
        puntos = puntos[:-1] + [{**puntos[-1], "enCurso": True}]
    abre, cierra = _sesion(mercado)
    # Cuántas horas está corrida la hora local de la rueda respecto de UTC, en
    # la última vela (Nueva York cambia de hora): la pantalla la usa para
    # ubicar un dibujo hacia adelante, en las velas que todavía no existen.
    desfase = ((ultima["minuto"] - (ultima["t"] // 60) % 1440 + 720) % 1440) - 720
    return {
        **base,
        "disponible": True,
        "ticker": ticker,
        "convertida": eleccion["convertida"],
        "mercado": mercado,
        "sesion": {"abre": abre, "cierra": cierra, "desfase": desfase, "todos_los_dias": mercado == "cripto",
                   "velas_por_dia": -(-(cierra - abre) // CADAS[cada])},
        # Para el ritmo del refresco de la pantalla (60 s con la rueda en
        # horario; con todo cerrado, espaciado: utils/relojVisible.refrescoSegunRueda).
        "en_horario": rueda_en_horario(mercado, datetime.now(timezone.utc)),
        "actualizada": datetime.fromtimestamp(actualizada, timezone.utc).isoformat().replace("+00:00", "Z"),
        "puntos": puntos,
    }
