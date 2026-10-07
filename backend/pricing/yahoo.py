"""pricing.yahoo — la ÚNICA puerta del servidor hacia Yahoo (yfinance) cuando
hay alguien esperando la respuesta.

POR QUÉ EXISTE (medido 2026-10-02). `GET /api/prices` con 13 símbolos tardó 66 s
una vez y ~6 s las otras. Dos mecanismos de yfinance, los dos medidos:

1. `yf.download` NO se puede llamar dos veces a la vez en el mismo proceso.
   Guarda lo que baja en un diccionario GLOBAL del módulo (`yfinance.shared._DFS`):
   lo vacía al empezar y se queda esperando "hasta que tenga tantos tickers como
   pedí". Si otra descarga arranca en el medio, le vacía el diccionario a la
   primera:
     · una devuelve tickers que NO pidió y le faltan los suyos (pedí SPY+QQQ y
       volvieron BTC-USD y META);
     · la otra espera un conteo que ya no va a llegar — PARA SIEMPRE, hasta que
       alguna otra descarga cualquiera llene el diccionario (cortada a los 75 s,
       seguía esperando).
   En producción corre UN solo proceso: la cinta de cotizaciones, /api/prices,
   el cierre anterior, la foto diaria, las alertas y Mervall-E AI descargaban todos
   en el mismo diccionario.

2. Yahoo puede no contestar, y yfinance espera hasta 30 s por pedido: la cookie
   la pide con 30 s fijos, sin importar el `timeout` que uno le pase.

Qué hace este módulo:
  · `descargar` reemplaza a `yf.download`. Baja cada ticker por separado con
    `Ticker.history` —exactamente lo que yf.download hace por dentro— y arma la
    MISMA tabla. Sin nada global compartido, dos pedidos a la vez no se pisan.
  · todo tiene tope. Lo que no llegó a tiempo se deja de esperar: el hilo sigue
    hasta que yfinance se rinde solo, pero nadie lo espera, y el que llamó sigue
    con lo que tiene (el último precio conocido, la caché vieja, "sin dato").
  · los hilos salen de UN pool global que no se cierra (el "fix B1" de
    `_yf_fetch_cached`: un `with ThreadPoolExecutor()` espera al hilo colgado al
    salir y anula el tope). Si Yahoo se cuelga, el pool se llena, lo que llega
    después espera en la cola, se le vence el tope y se cancela sin haber salido.

Cómo se usa:
  · `descargar(tickers, ...)` en lugar de `yf.download(...)`.
  · `con_tope(fn, *args, tope=...)` para una llamada suelta (un historial, un
    split, la búsqueda de símbolos).
  · `varios(fn, items, tope=...)` para la misma llamada sobre varios símbolos,
    en paralelo y con UN tope para todos (no uno por símbolo: con 10 símbolos y
    8 s cada uno serían 80 s).
  · `ultimos_cierres(tabla, tickers)` lee el último cierre VÁLIDO de cada ticker
    de esa tabla (ver la función: la "última fila" de la tabla NO sirve).

El guard `tests/test_yahoo_con_tope.py` falla si alguien vuelve a escribir
`yf.download` en el servidor.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from concurrent.futures import (FIRST_COMPLETED, ThreadPoolExecutor,
                                TimeoutError as _FuturoVencido, wait)

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# Lo máximo que una pantalla espera a Yahoo (el mismo orden que
# `YF_FETCH_TIMEOUT_SECONDS` y `EVENTOS_ESPERA_MAX_SEG` en main.py).
TOPE_PANTALLA_SEG = 8.0
# Para los trabajos de fondo (la foto diaria, las alertas): nadie mira la
# pantalla, pero tampoco pueden quedar colgados para siempre.
TOPE_FONDO_SEG = 120.0

# Cuántos tickers de UN mismo pedido salen a la vez. yf.download usaba
# min(tickers, 2 × CPUs); con un tope por pedido, uno grande (la foto diaria)
# no acapara el pool entero y uno chico (una pantalla) entra en el medio.
_EN_VUELO_POR_PEDIDO = 12


def _pool_nuevo() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=24, thread_name_prefix="yahoo")


_pool = _pool_nuevo()


class YahooNoRespondio(TimeoutError):
    """Yahoo no contestó dentro del tope. Hereda de TimeoutError: los `except
    Exception` que ya rodeaban cada llamada lo atrapan igual que a un error."""


def _nombre(fn) -> str:
    return getattr(fn, "__name__", None) or repr(fn)


def con_tope(fn, *args, tope: float = TOPE_PANTALLA_SEG, que: str = None,
             pool=None, **kwargs):
    """`fn(*args, **kwargs)` en el pool, esperando como mucho `tope` segundos.

    Devuelve lo que devuelve `fn`, o propaga su excepción. Si no terminó a
    tiempo tira `YahooNoRespondio` y NO espera al hilo (ver docstring del módulo).
    `pool` permite usar otro pool global (el de `_yf_fetch_cached`); nunca uno
    creado con `with`.

    ⚠️ No llamar `con_tope`/`varios` desde ADENTRO de una función que ya corre
    en el pool: con el pool lleno, la de afuera esperaría a una de adentro que
    está en la cola detrás de ella.
    """
    q = que or _nombre(fn)
    try:
        fut = (pool or _pool).submit(fn, *args, **kwargs)
    except RuntimeError:   # el pool ya se apagó (el proceso se está cerrando)
        raise YahooNoRespondio(f"{q}: el servidor se está apagando") from None
    try:
        return fut.result(timeout=max(float(tope), 0.0))
    except _FuturoVencido:
        fut.cancel()  # si todavía estaba en la cola, no sale nunca
        log.warning("yahoo: %s no respondió en %.1f s — se sigue sin esperarlo", q, tope)
        raise YahooNoRespondio(f"{q}: Yahoo no respondió en {tope:.1f} s") from None


def varios(fn, items, tope: float = TOPE_PANTALLA_SEG, que: str = None,
           en_vuelo: int = _EN_VUELO_POR_PEDIDO):
    """`fn(item)` para cada item, en paralelo, con UN tope para todos juntos.

    Devuelve `(resultados, sin_respuesta)`:
      · `resultados`: {item: lo que devolvió fn} de los que terminaron a tiempo.
        Un item cuya `fn` tiró excepción NO está (se registra en debug): para el
        que llama es lo mismo que "Yahoo no tiene ese dato".
      · `sin_respuesta`: los items que no terminaron a tiempo, en orden.
    """
    lista = list(dict.fromkeys(items))
    fin = time.monotonic() + max(float(tope), 0.0)
    cola = deque(lista)
    en_curso = {}
    resultados = {}
    while cola or en_curso:
        restante = fin - time.monotonic()
        if restante <= 0:
            break
        try:
            while cola and len(en_curso) < en_vuelo:
                en_curso[_pool.submit(fn, cola[0])] = cola[0]
                cola.popleft()
        except RuntimeError:   # el pool ya se apagó: lo que falta queda sin respuesta
            if not en_curso:
                break
        listos, _ = wait(list(en_curso), timeout=restante, return_when=FIRST_COMPLETED)
        for f in listos:
            it = en_curso.pop(f)
            try:
                resultados[it] = f.result()
            except Exception as ex:
                log.debug("yahoo: %s(%s) falló: %r", _nombre(fn), it, ex)
    sin_respuesta = list(en_curso.values()) + list(cola)
    for f in en_curso:
        f.cancel()
    if sin_respuesta:
        log.warning("yahoo: %s — %d de %d sin respuesta en %.1f s: %s",
                    que or _nombre(fn), len(sin_respuesta), len(lista), tope,
                    ", ".join(map(str, sin_respuesta[:15])))
    return resultados, sin_respuesta


def apagar() -> None:
    """Al cerrar el proceso: lo que todavía no salió se descarta (los hilos del
    pool no son "daemon": sin esto, el proceso viejo de cada deploy esperaría
    la cola entera). Lo que ya está corriendo termina solo.

    Queda un pool NUEVO y vacío en su lugar (sin hilos hasta que alguien lo
    use, así que no demora el cierre): un pedido que llega durante el apagado
    —o el arranque siguiente en el mismo proceso, como en las pruebas— sigue
    teniendo Yahoo en vez de un pool muerto para siempre."""
    global _pool
    viejo, _pool = _pool, _pool_nuevo()
    try:
        viejo.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass


def _historia(ticker: str, period: str, interval: str, auto_adjust: bool, timeout: float):
    # Los mismos parámetros que yf.download le pasa a cada ticker (`_download_one`).
    return yf.Ticker(ticker).history(period=period, interval=interval,
                                     auto_adjust=auto_adjust, actions=False,
                                     timeout=timeout)


def descargar(tickers, period: str = "1mo", interval: str = "1d",
              auto_adjust: bool = True, group_by: str = "column",
              tope: float = TOPE_PANTALLA_SEG, que: str = "descarga") -> pd.DataFrame:
    """Reemplazo de `yf.download(tickers, period=, interval=, auto_adjust=,
    group_by=)` que no comparte nada con otros pedidos y tiene tope.

    Devuelve la MISMA forma de tabla que yf.download: columnas de dos niveles
    (dato, ticker) con `group_by="column"` —`tabla["Close"]` da una columna por
    ticker— o (ticker, dato) con `group_by="ticker"`; índice de fechas sin zona
    horaria para velas diarias o más largas. Un ticker que falló o no llegó a
    tiempo NO aparece (yf.download lo ponía como columna vacía): quien lee tiene
    que preguntar si está, nunca asumir.
    """
    if isinstance(tickers, str):
        tickers = tickers.replace(",", " ").split()
    lista = list(dict.fromkeys(str(t).strip().upper() for t in (tickers or []) if str(t).strip()))
    if not lista:
        return pd.DataFrame()
    # El `timeout` de yfinance es por pedido HTTP; el tope de acá es el del total.
    t_http = max(1.0, min(10.0, float(tope)))
    resultados, _ = varios(lambda t: _historia(t, period, interval, auto_adjust, t_http),
                           lista, tope=tope, que=f"{que} ({len(lista)} tickers)")
    diaria = not interval.endswith(("m", "h"))  # '1d', '1wk', '1mo' sí; '5m', '1h' no
    tablas = {}
    for t in lista:  # en el orden pedido
        df = resultados.get(t)
        if df is None or getattr(df, "empty", True):
            continue
        df = df[~df.index.duplicated(keep="last")]
        if diaria and getattr(df.index, "tz", None) is not None:
            # Lo mismo que yf.download (`ignore_tz` para velas diarias): la vela
            # de Nueva York y la de Buenos Aires del mismo día caen en la misma
            # fila, y se pueden juntar zonas horarias distintas en una tabla.
            df = df.copy()
            df.index = df.index.tz_localize(None)
        tablas[t] = df
    if not tablas:
        return pd.DataFrame()
    data = pd.concat(list(tablas.values()), axis=1, sort=True,
                     keys=list(tablas.keys()), names=["Ticker", "Price"])
    if group_by == "column":
        data.columns = data.columns.swaplevel(0, 1)
        data = data.sort_index(level=0, axis=1)
    return data


def es_cripto(yf_ticker: str) -> bool:
    """Las cripto (BTC-USD…) operan los 7 días, a cualquier hora. Las acciones no."""
    return str(yf_ticker).upper().endswith("-USD")


def ultimos_cierres(tabla, tickers=None) -> dict:
    """{ticker: (precio, 'YYYY-MM-DD')}: el último cierre VÁLIDO (> 0, no NaN) de
    cada ticker de una tabla de `descargar`, con la fecha de esa vela. El que no
    tiene ninguno no está. `tickers=None` → todos los de la tabla.

    ⚠️ POR QUÉ NO "LA ÚLTIMA FILA" (medido 2026-10-02, 09:40): antes se leía la
    última fila de la tabla. Con una cripto en el pedido, esa fila es la de HOY
    —Bitcoin ya tiene vela a las 00:00 UTC— y las acciones todavía no: todas
    venían NaN. Pasaba todas las noches desde las 21:00 hasta que abre Wall
    Street, y los fines de semana enteros. `/api/prices` las volvía a bajar una
    por una (11 pedidos de más) y las marcaba como "precio de una rueda
    anterior"; `fetch_prices_for_symbols` (Mervall-E AI, alertas) las devolvía SIN
    precio.
    """
    out = {}
    if tabla is None or getattr(tabla, "empty", True):
        return out
    try:
        close = tabla["Close"]
    except Exception:
        return out
    if tickers is None:
        tickers = list(getattr(close, "columns", []))
    tickers = list(dict.fromkeys(tickers))
    if isinstance(close, pd.Series):
        # Tabla de UN ticker sin columna por ticker. Con más de uno no se puede
        # saber de quién es: antes se le asignaba igual, y un ticker que faltaba
        # se llevaba el precio de otro.
        if len(tickers) != 1:
            return out
        close = close.to_frame(name=tickers[0])
    columnas = set(getattr(close, "columns", []))
    for t in tickers:
        if t not in columnas:
            continue
        try:
            serie = pd.to_numeric(close[t], errors="coerce").dropna()
            serie = serie[serie > 0]
            if len(serie):
                out[t] = (float(serie.iloc[-1]), str(serie.index[-1])[:10])
        except Exception:
            continue
    return out


def ruedas_de_referencia(cierres: dict) -> dict:
    """La vela más nueva de cada calendario: {'cripto': fecha, 'resto': fecha}.

    Sirve para saber qué precio se quedó atrás: una acción cuya última vela es
    más vieja que la más nueva de las OTRAS acciones se salteó su rueda (la
    vela de .BA que yfinance devuelve en NaN). Una cripto se compara con las
    cripto: con el mismo criterio, el Bitcoin del sábado haría ver "atrasadas"
    a todas las acciones.
    """
    ref = {}
    for t, (_, fecha) in cierres.items():
        grupo = "cripto" if es_cripto(t) else "resto"
        if fecha and fecha > ref.get(grupo, ""):
            ref[grupo] = fecha
    return ref


def rueda_de_referencia_para(yf_ticker: str, referencias: dict):
    return referencias.get("cripto" if es_cripto(yf_ticker) else "resto")
