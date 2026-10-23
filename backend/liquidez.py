"""Liquidez en BYMA de un CEDEAR o una acción argentina, para la ficha.

QUÉ ES. Cuánto se opera de un papel en BYMA y cuánto cuesta entrar y salir:
  · la plata que se opera por día (promedio de las últimas `RUEDAS` ruedas);
  · cuántas de esas ruedas no tuvo ninguna operación;
  · la diferencia entre el mejor precio de compra y el de venta AHORA (lo que
    perdés si comprás y vendés enseguida, aunque el precio no se mueva).
Y un veredicto con los cortes de abajo: mucha, media o poca.

POR QUÉ. El gráfico técnico de un CEDEAR mira, por defecto, la acción en Nueva
York, que se opera muchísimo. Pero el usuario compra y vende el CEDEAR en BYMA,
donde puede casi no haber operaciones: medido el 23/10/2026, 240 de los 1.022
CEDEARs no tuvieron ni una operación en el día, y la diferencia entre puntas iba
de 0,07 % (AAPL) a 2,4 % (IRENC). Describe un riesgo; nunca dice qué hacer.

DE DÓNDE. data912 (la misma fuente que ya da el precio en vivo de BYMA): el
volumen y las puntas de hoy (`main._fetch_data912_equities`) y la historia
diaria de cada papel. Los CEDEARs chicos no tienen historia en data912: para
ésos, el volumen diario que Yahoo publica del '.BA'. Nada se guarda en la base:
se cachea en memoria unas horas. Sólo papeles que data912 lista (los que
cotizan en BYMA): no hay forma de pedir descargas de cualquier cosa.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

RUEDAS = 20
# Plata operada por día (pesos) para cada veredicto.
MUCHA_DESDE = 500_000_000
POCA_HASTA = 50_000_000
# Más días que éstos sin ninguna operación en las últimas RUEDAS = poca.
DIAS_SIN_OPERAR_POCA = 3
# Una diferencia entre puntas mayor a esto (%) = poca.
SPREAD_POCA = 1.0
CACHE_SEG = 6 * 3600
# Lo que vino vacío (la fuente no contestó o no tiene el papel) se reintenta
# antes: si data912 estuvo caído un rato, no queda "sin datos" seis horas.
CACHE_VACIO_SEG = 10 * 60
TOPE_SEG = 8.0
# El papel de referencia para saber qué días hubo rueda en BYMA (se opera todos
# los días): sin él no se pueden contar los días SIN operaciones de los otros.
REFERENCIA = ("stocks", "GGAL")

_cache = {}
_lock = threading.Lock()


def _cacheado(clave, fn):
    """`fn()` cacheado en memoria. Si `fn` falla, cuenta como vacío (y se
    cachea poco): una fuente caída no traba la ficha en cada pedido."""
    ahora = time.time()
    with _lock:
        hit = _cache.get(clave)
        if hit and ahora - hit[0] < (CACHE_SEG if hit[1] else CACHE_VACIO_SEG):
            return hit[1]
    try:
        valor = fn()
    except Exception as ex:
        log.warning("liquidez: %s falló: %r", clave, ex)
        valor = {}
    with _lock:
        _cache[clave] = (ahora, valor)
    return valor


def _historia_data912(tipo: str, papel: str) -> dict:
    """{fecha: nominales operados} de data912. {} si no tiene ese papel (los
    CEDEARs chicos: contesta un error en vez de la lista)."""
    import requests
    r = requests.get(f"https://data912.com/historical/{tipo}/{papel}", timeout=TOPE_SEG)
    filas = r.json() if r.status_code == 200 else None
    if not isinstance(filas, list) or len(filas) < 2:
        return {}
    out = {}
    for f in filas:
        d = str(f.get("date") or "")[:10]
        if d:
            out[d] = float(f.get("v") or 0)
    return out


def _historia_yahoo(papel: str) -> dict:
    """{fecha: nominales operados} del '.BA' en Yahoo, último mes. Sólo el
    volumen: Yahoo a veces manda el precio de una rueda .BA vacío, el volumen no."""
    from pricing import yahoo as _yahoo
    df = _yahoo._historia(f"{papel}.BA", "1mo", "1d", False, TOPE_SEG)
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for idx, row in df.iterrows():
        try:
            v = float(row.get("Volume") or 0)
        except (TypeError, ValueError):
            v = 0.0
        out[idx.date().isoformat()] = v if v == v else 0.0   # NaN → 0
    # Una o dos filas no es la historia del papel (IRENC.BA: Yahoo devuelve una
    # sola): contada contra las 20 ruedas, decía "20 días sin operar" de algo
    # que se opera todos los días.
    return out if len(out) >= RUEDAS // 2 else {}


def _ruedas_de_byma() -> list:
    """Las últimas RUEDAS fechas en que hubo rueda en BYMA (las del papel de
    referencia)."""
    tipo, papel = REFERENCIA
    hist = _cacheado(("ruedas",), lambda: _historia_data912(tipo, papel))
    return sorted(hist)[-RUEDAS:]


def nivel(pesos_por_dia, dias_sin_operar, spread_pct):
    """'mucha' | 'media' | 'poca' | None (sin datos para decir nada)."""
    if spread_pct is not None and spread_pct > SPREAD_POCA:
        return "poca"
    if dias_sin_operar is not None and dias_sin_operar > DIAS_SIN_OPERAR_POCA:
        return "poca"
    if pesos_por_dia is None:
        return None
    if pesos_por_dia < POCA_HASTA:
        return "poca"
    return "mucha" if pesos_por_dia >= MUCHA_DESDE else "media"


def para_la_ficha(papel: str) -> dict:
    """Lo que muestra la ficha. `papel`: el código de BYMA ('MELI', 'GGAL',
    'AAPL'), con o sin '.BA'. {disponible: False} si no cotiza en BYMA o no hay
    nada que medir."""
    from main import _fetch_data912_equities
    p = (papel or "").strip().upper()
    if p.endswith(".BA"):
        p = p[:-3]
    vivo = (_fetch_data912_equities() or {}).get(p)
    if not p or not vivo:
        return {"papel": p, "disponible": False}
    es_cedear = vivo.get("mercado") == "arg_cedears"
    precio = float(vivo.get("c") or 0)

    hist = _cacheado(("d912", p), lambda: _historia_data912("cedears" if es_cedear else "stocks", p))
    fuente = "data912" if hist else None
    if not hist:
        hist = _cacheado(("yahoo", p), lambda: _historia_yahoo(p))
        fuente = "yahoo" if hist else None

    pesos_por_dia = dias_sin_operar = None
    ruedas = []
    if hist:
        ruedas = _ruedas_de_byma()
        # Sin la referencia, las ruedas son las del propio papel (no se pueden
        # contar los días sin operar: ésos no aparecen en su historia).
        ruedas = ruedas or sorted(hist)[-RUEDAS:]
        volumenes = [hist.get(d, 0.0) for d in ruedas]
        if precio > 0 and volumenes:
            pesos_por_dia = sum(volumenes) / len(volumenes) * precio
        dias_sin_operar = sum(1 for v in volumenes if not v)

    bid, ask = vivo.get("px_bid"), vivo.get("px_ask")
    # Fuera de horario las puntas vienen vacías: no hay diferencia que medir.
    spread_pct = round((ask - bid) / bid * 100, 2) if bid and ask and ask >= bid > 0 else None

    n = nivel(pesos_por_dia, dias_sin_operar, spread_pct)
    if n is None:
        return {"papel": p, "disponible": False}
    return {
        "papel": p,
        "disponible": True,
        "es_cedear": es_cedear,
        "nivel": n,
        "pesos_por_dia": round(pesos_por_dia) if pesos_por_dia is not None else None,
        "ruedas": len(ruedas) if hist else None,
        "dias_sin_operar": dias_sin_operar,
        "spread_pct": spread_pct,
        "fuente": fuente,
    }
