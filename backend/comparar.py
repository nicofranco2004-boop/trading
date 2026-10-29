"""Comparar el PRECIO de varios activos desde la misma base (pieza 16).

QUÉ ES. De 1 a 4 activos y, como vara, el S&P 500, guardar dólares (el MEP) y
la inflación (el CER, sólo en pesos), todos arrancando en 100 el MISMO día y en
la MISMA moneda. Abajo la pantalla dice «cada US$ 100 de tal fecha hoy son…»:
es el último valor de cada línea, sin otra cuenta.

UNA SOLA CUENTA. La regla de «arrancar en 100» (`base_cien`) y en qué moneda va
cada línea viven acá; la pantalla sólo dibuja. Las series de los activos son las
de la ficha (`tecnico.serie`: corrige los cambios de ratio de un CEDEAR y pasa
una acción argentina a dólares con el MEP de CADA día) y la del S&P 500 la de
«Cuánto se mueve» (`tecnico.sp500`). Acá no se arma ninguna serie de precios.

CÓMO SE ELIGE EL DÍA DEL 100.
  · El pedido trae `desde`: tu primera compra (la calcula la pantalla con la
    misma regla de la ficha, `primeraCompra`) o hoy menos 1 o 3 años.
  · Si `desde` cae un día sin precio (fin de semana, feriado), vale el último
    cierre anterior: es el precio que tenía ese día.
  · Si un activo empieza DESPUÉS de `desde` (cotiza hace menos, o lo guardado
    no llega tan atrás), el 100 se corre para TODOS al primer día que tienen
    todos, y la respuesta dice cuál lo corrió (`base_corrida_por`). Cada uno con
    su propio día de arranque no sería comparar desde la misma base.
  · Una vara sin dato ese día (el CER de un mes que no bajó) no mueve la base:
    no aparece y la respuesta dice por qué.

LAS VARAS EN CADA MONEDA.
  · Guardar dólares: en dólares es una línea quieta en 100 (un dólar sigue
    siendo un dólar); en pesos es el MEP de cada día (`fx.serie_diaria`, la
    regla de `fx.fx_for_date`).
  · Inflación (CER): sólo en pesos. En dólares no se ofrece: lo que la mide es
    el poder de compra de los pesos. La serie la pasa quien llama (vive en
    `main`, con su plan B por UVA y su `basis`).
  · S&P 500: en dólares, el índice; en pesos, × el MEP de cada día.
  · Merval: no hay fuente (Yahoo dejó de publicar ^MERV el 16/10/2026). No va.

QUÉ NO HACE. No recomienda nada ni mira para adelante: dice qué pasó.
"""
from __future__ import annotations

from datetime import date, timedelta

import tecnico

MAX_ACTIVOS = 4
# «1 año» y «3 años» se cortan por FECHA (días corridos), como la ficha.
PLAZOS = {"1a": tecnico.DIAS_ANIO, "3a": 3 * tecnico.DIAS_ANIO}
VARAS = ("sp500", "mep", "cer")
# Un activo que empieza hasta una semana después del día pedido no «corre» el
# 100: es el borde de lo guardado (3 años justos) o un feriado largo, no un
# activo que cotiza hace menos. El 100 va a su primer día igual, sin aviso.
DIAS_MARGEN = 7
NOMBRE_VARA = {"sp500": "S&P 500", "mep": "Guardar dólares", "cer": "Inflación (CER)"}


def desde_plazo(plazo: str, hoy: date) -> str:
    """El día de arranque de «1 año» o «3 años» contado desde `hoy`."""
    return (hoy - timedelta(days=PLAZOS[plazo])).isoformat()


def _valor_al(puntos: list, fecha: str):
    """El último valor de `puntos` [(fecha, valor)] en `fecha` o antes: el que
    tenía ese día (un sábado vale el cierre del viernes). None si no hay."""
    v = None
    for d, x in puntos:
        if d > fecha:
            break
        v = x
    return v


def base_cien(puntos: list, base: str) -> list:
    """LA regla de «arrancar en 100»: `puntos` [(fecha, valor)] ordenados →
    [{d, v}] desde `base`, con v = valor ÷ valor del día `base` × 100. El primer
    punto es el día `base` en 100 aunque ese día no haya habido rueda (vale el
    cierre anterior). [] si no hay valor ese día o antes."""
    inicial = _valor_al(puntos, base)
    if not inicial or inicial <= 0:
        return []
    out = [{"d": base, "v": 100.0}]
    for d, x in puntos:
        if d > base and x is not None and x > 0:
            out.append({"d": d, "v": round(x / inicial * 100.0, 4)})
    return out


def _cierres(velas: list) -> list:
    return [(v["date"], v["close"]) for v in velas if v.get("close") is not None]


def _mep(conn, desde: str) -> list:
    """El MEP de cada día desde `desde` (y el último anterior, para el día del
    100), con la regla de `fx.fx_for_date`."""
    from fx import serie_diaria
    return [(d, tc) for d, tc, _ in serie_diaria(conn, desde)]


def comparar(conn, activos: list, moneda: str, desde: str, *, cer: list = None,
             cer_basis: str = None) -> dict:
    """La comparación entera.

    `activos`: [(asset, local)] con `local` igual que la ficha (acción argentina
    → su precio de BYMA). `moneda`: 'usd' | 'ars'. `desde`: 'YYYY-MM-DD'. `cer`:
    [(fecha, valor)] del índice (sólo se usa en pesos) y `cer_basis` con qué se
    armó ('CER' o 'UVA').

    {moneda, desde, base, base_corrida_por, series: [{clave, tipo, nombre,
    ticker, convertida, puntos, final, fecha_final}], faltan: [{clave, motivo}]}
    `base` es el día del 100 (None si ningún activo tiene precios)."""
    moneda = "ars" if moneda == "ars" else "usd"
    out = {"moneda": moneda, "desde": desde, "base": None, "base_corrida_por": None,
           "series": [], "faltan": []}

    crudas = []
    for asset, local in activos:
        s = tecnico.serie(conn, asset, moneda, bool(local))
        puntos = _cierres(s["velas"])
        if not puntos:
            out["faltan"].append({"clave": asset, "motivo": "sin_datos"})
            continue
        crudas.append({"clave": asset, "tipo": "activo", "nombre": asset, "local": bool(local),
                       "ticker": s.get("ticker"), "convertida": s.get("convertida"), "puntos": puntos})
    if not crudas:
        return out

    # El día del 100: `desde`, o el primero que tienen TODOS si alguno empieza después.
    base, por = desde, None
    for c in crudas:
        primero = c["puntos"][0][0]
        if primero > base:
            base = primero
            tarde = (date.fromisoformat(primero) - date.fromisoformat(desde)).days > DIAS_MARGEN
            por = c["clave"] if tarde else por
    out["base"], out["base_corrida_por"] = base, por

    varas = [{"clave": "sp500", "puntos": _cierres(tecnico.sp500(conn, moneda)), "ticker": "^GSPC"}]
    if moneda == "usd":
        # Un dólar guardado sigue siendo un dólar: 100 de punta a punta.
        ultimo = max(c["puntos"][-1][0] for c in crudas)
        varas.append({"clave": "mep", "puntos": [(base, 1.0), (ultimo, 1.0)], "ticker": None})
        out["faltan"].append({"clave": "cer", "motivo": "solo_en_pesos"})
    else:
        varas.append({"clave": "mep", "puntos": _mep(conn, base), "ticker": None})
        varas.append({"clave": "cer", "puntos": sorted(cer or []), "ticker": cer_basis})

    for c in crudas:
        c["puntos"] = base_cien(c["puntos"], base)
    for v in varas:
        p = base_cien(v["puntos"], base)
        if not p:
            out["faltan"].append({"clave": v["clave"], "motivo": "sin_datos"})
            continue
        # El CER se sirve con la UVA cuando su fuente no responde (main.
        # `_serie_cer_o_uva`), y se dice: el mismo rótulo con otro índice sería
        # cambiar un número inventado por otro.
        nombre = NOMBRE_VARA[v["clave"]]
        if v["clave"] == "cer" and v["ticker"] == "UVA":
            nombre = "Inflación (CER, vía UVA)"
        crudas.append({"clave": v["clave"], "tipo": "vara", "nombre": nombre,
                       "ticker": v["ticker"], "convertida": None, "puntos": p})

    for c in crudas:
        p = c["puntos"]
        c["final"] = round(p[-1]["v"], 2)
        c["fecha_final"] = p[-1]["d"]
        c["puntos"] = [{"d": x["d"], "v": round(x["v"], 2)} for x in p]
        out["series"].append(c)
    return out
