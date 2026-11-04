"""Liquidez en BYMA de un CEDEAR o una acción argentina, para la ficha.

QUÉ ES. Cuánto se opera de un papel en BYMA y cuánto cuesta entrar y salir:
  · la plata que se opera por día (promedio de las últimas `RUEDAS` ruedas);
  · cuántas de esas ruedas no tuvo ninguna operación;
  · la diferencia entre el mejor precio de compra y el de venta AHORA (lo que
    perdés si comprás y vendés enseguida, aunque el precio no se mueva), sólo
    con la rueda abierta: fuera de horario las puntas no dicen nada.
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
    from pricing import data912
    filas = data912.filas(tipo, papel, timeout=TOPE_SEG)
    if len(filas) < 2:
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


def _byma_abierto() -> bool:
    """La regla única de horario de BYMA (fuera_de_horario.byma_abierto)."""
    from datetime import datetime, timezone
    from fuera_de_horario import byma_abierto
    return byma_abierto(datetime.now(timezone.utc))


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


def _especie_en_dolares(p: str, vivos: dict):
    """Si `p` es la especie en dólares de un CEDEAR (MELID = MEP, MELIC = cable),
    el precio en PESOS de su especie base (MELI); si no, None. Las D y las C
    cotizan en dólares: multiplicar su volumen por su precio y llamarlo pesos
    hacía «poca liquidez» de cualquier especie en dólares (auditoría 24/10:
    IRENC salía «poca» y el CEDEAR de IREN en pesos se opera $ 1.585 millones
    por día). Se reconoce por el precio, no por la letra: YPFD es una acción
    argentina en pesos que también termina en D."""
    if len(p) < 3 or p[-1] not in "DC":
        return None
    base = vivos.get(p[:-1])
    yo = vivos.get(p)
    if not base or not yo or base.get("mercado") != yo.get("mercado"):
        return None
    cb, cp = float(base.get("c") or 0), float(yo.get("c") or 0)
    # Un dólar de BYMA vale cientos de pesos: la base cotiza muchas veces más.
    return cb if cp > 0 and cb / cp > 100 else None


def _ruedas_para(hist: dict, ref: list, fuente: str) -> list:
    """Las ruedas contra las que se cuenta un papel: las de BYMA (data912). Si
    la historia es de Yahoo, menos las últimas que Yahoo todavía no cargó (a
    veces va un día atrás: sin esto, ese día contaba como "sin operaciones");
    si le faltan más de 2, no es atraso: el papel dejó de operarse, y cuentan.
    Con historia de data912 (la misma fuente que las ruedas) un día que falta
    es un día sin operaciones, siempre."""
    ultimo = max(hist)
    despues = [d for d in ref if d > ultimo]
    if fuente == "yahoo" and 0 < len(despues) <= 2:
        ref = [d for d in ref if d <= ultimo]
    return ref[-RUEDAS:]


def para_la_ficha(papel: str) -> dict:
    """Lo que muestra la ficha. `papel`: el código de BYMA ('MELI', 'GGAL',
    'AAPL'), con o sin '.BA'.

    Cuando no hay dato, `disponible` es False y `motivo` dice por qué, para que
    la ficha no calle algo que importa:
      · 'sin_fuente': data912 no contesta (no se sabe nada; la ficha lo dice);
      · 'no_cotiza':  data912 contesta y el papel no está (un bono, un fondo, un
        código que BYMA no lista): no hay nada que decir.
    Sin historia de días anteriores (ni data912 ni Yahoo), se usa la última
    rueda del precio en vivo (`periodo: 'ultima_rueda'`): un papel chico sin
    historia es justo el que más importa avisar."""
    from main import _fetch_data912_equities
    p = (papel or "").strip().upper()
    if p.endswith(".BA"):
        p = p[:-3]
    vivos = _fetch_data912_equities() or {}
    if not vivos:
        return {"papel": p, "disponible": False, "motivo": "sin_fuente"}
    vivo = vivos.get(p)
    if not p or not vivo:
        return {"papel": p, "disponible": False, "motivo": "no_cotiza"}
    es_cedear = vivo.get("mercado") == "arg_cedears"
    # El precio en PESOS con el que se pasa a plata el volumen: el propio, o el
    # de la especie base si ésta es la especie en dólares.
    base_pesos = _especie_en_dolares(p, vivos) if es_cedear else None
    precio = base_pesos or float(vivo.get("c") or 0)

    hist = _cacheado(("d912", p), lambda: _historia_data912("cedears" if es_cedear else "stocks", p))
    fuente = "data912" if hist else None
    if not hist:
        hist = _cacheado(("yahoo", p), lambda: _historia_yahoo(p))
        fuente = "yahoo" if hist else None

    pesos_por_dia = dias_sin_operar = ruedas = None
    periodo = "promedio"
    if hist:
        ref = _ruedas_de_byma()
        if ref:
            dias = _ruedas_para(hist, ref, fuente)
            dias_sin_operar = sum(1 for d in dias if not hist.get(d))
        else:
            # Sin las ruedas de BYMA no se pueden contar los días SIN
            # operaciones (no aparecen en la historia del papel): no se dice
            # "se operó todos los días" de algo que no se midió.
            dias = sorted(hist)[-RUEDAS:]
        ruedas = len(dias)
        if precio > 0 and dias:
            pesos_por_dia = sum(hist.get(d, 0.0) for d in dias) / len(dias) * precio
    elif vivo.get("v") is not None and precio > 0:
        # Sin historia: la última rueda (del precio en vivo de data912).
        periodo, fuente, ruedas = "ultima_rueda", "data912_vivo", 1
        pesos_por_dia = float(vivo.get("v") or 0) * precio
        dias_sin_operar = 0 if vivo.get("v") else 1

    # La diferencia entre puntas, sólo con la rueda abierta: con BYMA cerrada
    # (a la noche, el fin de semana) quedan órdenes colgadas lejos del precio y
    # la diferencia no es lo que cuesta operar. Medido un sábado: MUX daba 7,97 %
    # contra 0,41 % en la rueda (24/10).
    bid, ask = vivo.get("px_bid"), vivo.get("px_ask")
    spread_pct = (round((ask - bid) / bid * 100, 2)
                  if _byma_abierto() and bid and ask and ask >= bid > 0 else None)

    n = nivel(pesos_por_dia, dias_sin_operar if periodo == "promedio" else None, spread_pct)
    if periodo == "ultima_rueda" and dias_sin_operar:
        n = "poca"          # la última rueda no tuvo ni una operación
    if n is None:
        return {"papel": p, "disponible": False, "motivo": "sin_datos"}
    return {
        "papel": p,
        "disponible": True,
        "es_cedear": es_cedear,
        "en_dolares": bool(base_pesos),
        "nivel": n,
        "periodo": periodo,
        "pesos_por_dia": round(pesos_por_dia) if pesos_por_dia is not None else None,
        "ruedas": ruedas,
        "dias_sin_operar": dias_sin_operar,
        "spread_pct": spread_pct,
        "fuente": fuente,
    }
