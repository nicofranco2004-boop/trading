"""Simular una cartera: qué habría pasado con US$ 100 repartidos en varios activos,
comprados el primer día y sin tocar, al lado del S&P 500 y del Nasdaq.

QUÉ ES. «Una cartera», dentro de la pestaña Backtesting de Análisis técnico (Nico,
05/11/2026: «antes de publicar, agregá simular cartera contra el S&P 500 y el
Nasdaq»; boceto aprobado, opción A: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5).
La persona arranca con su cartera de hoy o de cero, pone cada activo con su peso
sobre 100 y elige de 1 a 4 años.

CÓMO SE SIMULA.
  · Todo se compra el primer día con esos pesos y no se toca más: sin
    rebalancear, el que sube pesa cada vez más (comprar y mantener, la misma vara
    que el Backtesting de una regla).
  · Cada activo con LA serie de la ficha (`tecnico.serie`: la acción de afuera de
    un CEDEAR; una acción argentina, su precio de BYMA ÷ el MEP de cada día) y LA
    regla de «arrancar en 100» del comparador de precios (`comparar.base_cien`).
  · El S&P 500 y el Nasdaq compuesto: los índices que se guardan todas las noches
    (`velas_diarias.INDICES`), en dólares.
  · Sin comisiones ni dividendos, ni en la cartera ni en los índices: precio
    contra precio, para que la comparación sea pareja. (El S&P 500 de Insights
    incluye dividendos: contesta otra pregunta, la de tu plata de verdad.)
  · Los días: los de cualquier activo de la cartera. El que ese día no cotizó (un
    feriado, una acción un sábado al lado de una cripto) vale su último cierre, y
    los índices también.

CUÁNDO ARRANCA. Los últimos `anios` años contados por calendario desde el último
precio, como el Backtesting de una regla. Si un activo cotiza desde después,
arranca el día de ese activo y lo dice (`recorte_por`); hasta una semana después
no es un recorte (`comparar.DIAS_MARGEN`: el borde de lo guardado, un feriado).

QUÉ NO HACE. No recomienda nada ni mira para adelante: dice qué habría pasado.
"""
from __future__ import annotations

import bisect
import math
from datetime import date, timedelta

import backtest
import comparar
import tecnico
import velas_diarias
from pesado import pesado

# Cuántos activos entran en una cartera (la torta se lee hasta ahí).
MAX_ACTIVOS = 10
# Los períodos, los del Backtesting de una regla: los dos se eligen en la misma
# pestaña y con el mismo selector.
ANIOS = backtest.ANIOS
# Los porcentajes tienen que sumar 100, con esta tolerancia por los decimales.
TOLERANCIA = 0.05
# (clave, nombre, símbolo de Yahoo), en el orden en que se muestran.
INDICES = (("sp500", "S&P 500", velas_diarias.SP500), ("nasdaq", "Nasdaq", velas_diarias.NASDAQ))
# Con menos días que esto no alcanza para decir nada (los del Backtesting).
MIN_DIAS = backtest.MIN_RUEDAS


def _puntos(velas: list) -> list:
    """[(fecha, cierre)] de las velas que sirven, en orden."""
    return comparar._cierres(backtest.velas_que_sirven(velas))


class _EnCien:
    """Una serie en 100 el día `base` (`comparar.base_cien`) que se puede leer
    cualquier día: vale el último cierre que tenía (un sábado, el del viernes)."""

    def __init__(self, puntos: list, base: str):
        b = comparar.base_cien(puntos, base)
        self.fechas = [p["d"] for p in b]
        self.valores = [p["v"] for p in b]

    def al(self, fecha: str):
        i = bisect.bisect_right(self.fechas, fecha) - 1
        return self.valores[i] if i >= 0 else None


def simular(activos: list, indices: dict, anios: int) -> dict:
    """La simulación entera, sin base de datos (la usan la ruta y las pruebas).

    `activos`: [{asset, local, peso, velas, ticker, convertida}], con los pesos
    sumando 100 (lo controla la ruta). `indices`: {clave: velas} de `INDICES`.
    {'disponible': False, 'motivo', 'faltan'} si no se puede: 'sin_serie' (un
    activo sin precios), 'vieja' (un activo sin precios de la última semana) o
    'poca_historia'. Un índice que falta no frena la cartera: va en `faltan`."""
    out = {"anios": anios, "moneda": "usd"}
    puntos = {a["asset"]: _puntos(a.get("velas") or []) for a in activos}
    sin = [a["asset"] for a in activos if not puntos[a["asset"]]]
    if sin:
        return {**out, "disponible": False, "motivo": "sin_serie",
                "faltan": [{"asset": s, "motivo": "sin_serie"} for s in sin]}
    hasta = max(p[-1][0] for p in puntos.values())
    viejas = [s for s, p in puntos.items() if comparar._dias(p[-1][0], hasta) > comparar.DIAS_VIEJA]
    if viejas:
        return {**out, "disponible": False, "motivo": "vieja",
                "faltan": [{"asset": s, "motivo": "vieja", "hasta": puntos[s][-1][0]} for s in viejas]}

    corte = date.fromisoformat(hasta) - timedelta(days=anios * tecnico.DIAS_ANIO)
    pedido = (corte + timedelta(days=1)).isoformat()
    primeras = {s: p[0][0] for s, p in puntos.items()}
    ultimo_en_llegar = max(primeras, key=lambda s: (primeras[s], s))
    base = max(pedido, primeras[ultimo_en_llegar])
    recortado = comparar._dias(pedido, base) > comparar.DIAS_MARGEN
    fechas = sorted({base} | {d for p in puntos.values() for d, _ in p if base < d <= hasta})
    out.update({"pedido_desde": pedido, "recortado": recortado,
                "recorte_por": ultimo_en_llegar if recortado else None})
    if len(fechas) < MIN_DIAS:
        return {**out, "disponible": False, "motivo": "poca_historia", "recorte_por": ultimo_en_llegar}

    pesos = {a["asset"]: float(a["peso"]) for a in activos}
    lineas = {s: _EnCien(p, base) for s, p in puntos.items()}
    cartera = [sum(pesos[s] / 100 * lineas[s].al(d) for s in pesos) for d in fechas]

    resumen_indices, faltan, curvas = [], [], {}
    for clave, nombre, simbolo in INDICES:
        p = _puntos(indices.get(clave) or [])
        if not p or p[0][0] > base:
            faltan.append({"clave": clave, "motivo": "sin_datos"})
            continue
        if comparar._dias(p[-1][0], hasta) > comparar.DIAS_VIEJA:
            faltan.append({"clave": clave, "motivo": "vieja", "hasta": p[-1][0]})
            continue
        linea = _EnCien(p, base)
        curvas[clave] = [linea.al(d) for d in fechas]
        resumen_indices.append({"clave": clave, "nombre": nombre, "ticker": simbolo,
                                **backtest._resumen([v / 100 for v in curvas[clave]])})

    final = cartera[-1]
    detalle = []
    for a in activos:
        s = a["asset"]
        v = lineas[s].al(hasta)
        detalle.append({
            "asset": s, "local": bool(a.get("local")), "peso": pesos[s],
            "ticker": a.get("ticker"), "convertida": a.get("convertida"),
            "primera_vela": primeras[s],
            # Lo que hizo el activo en el período, cuántos puntos del resultado de
            # la cartera vienen de él (suman el de la cartera) y cuánto pesaba al
            # final sin haberla tocado.
            "resultado": v - 100,
            "aporte": pesos[s] * (v - 100) / 100,
            "peso_final": pesos[s] * v / final,
        })
    return {
        **out,
        "disponible": True,
        "desde": base,
        "hasta": hasta,
        "dias": len(fechas),
        "activos": detalle,
        "cartera": backtest._resumen([v / 100 for v in cartera]),
        "indices": resumen_indices,
        "faltan": faltan,
        "curva": [{"d": d, "cartera": round(cartera[k], 2), **{c: round(curvas[c][k], 2) for c in curvas}}
                  for k, d in enumerate(fechas)],
    }


def _sobre_cien(valores: list, decimales: int = 1) -> list:
    """Los `valores` como porcentajes con `decimales` que suman EXACTAMENTE 100
    (al que más se le recortó en el redondeo, se le devuelve lo que falta)."""
    total = sum(valores)
    paso = 10 ** decimales
    crudos = [v / total * 100 * paso for v in valores]
    enteros = [math.floor(c) for c in crudos]
    faltan = round(100 * paso - sum(enteros))
    for k in sorted(range(len(crudos)), key=lambda k: (enteros[k] - crudos[k], k))[:faltan]:
        enteros[k] += 1
    return [e / paso for e in enteros]


def de_hoy(car: dict) -> dict:
    """«Mi cartera de hoy»: los activos de `car` (`senales_semana.cartera`, LA
    valuación de «tu plata») que se pueden simular, con su peso sobre 100 entre
    ellos (los porcentajes, nunca la plata). Quedan afuera, y se dice cuáles:
      · los que no tienen precio de todos los días (bonos, letras, fondos,
        efectivo, monedas estables): LA regla de la noche (`velas_diarias._yahoo_de`
        devuelve vacío), no una lista copiada;
      · si son más de `MAX_ACTIVOS`, los que menos pesan.
    El mismo papel en BYMA y en Nueva York (GGAL de IOL y el ADR de Schwab) va
    junto, con la marca `local` del que más pesa: la cartera no repite activos."""
    from cripto import yahoo_de_cripto
    juntos, afuera = {}, []
    for (asset, local), valor in car["tenencias"].items():
        tipo = car["tipos"].get((asset, local)) or None
        if valor <= 0:
            continue
        if not velas_diarias._yahoo_de(asset, tipo, bool(local), yahoo_de_cripto):
            afuera.append({"asset": asset, "tipo": tipo, "motivo": "sin_serie"})
            continue
        j = juntos.setdefault(asset, {"asset": asset, "valor": 0.0, "mayor": 0.0, "local": False, "tipo": tipo})
        j["valor"] += valor
        if valor > j["mayor"]:
            j.update(mayor=valor, local=bool(local), tipo=tipo)
    orden = sorted(juntos.values(), key=lambda j: (-j["valor"], j["asset"]))
    quedan, sobran = orden[:MAX_ACTIVOS], orden[MAX_ACTIVOS:]
    afuera += [{"asset": j["asset"], "tipo": j["tipo"], "motivo": "tope"} for j in sobran]
    pesos = _sobre_cien([j["valor"] for j in quedan]) if quedan else []
    return {"activos": [{"asset": j["asset"], "local": j["local"], "peso": p, "tipo": j["tipo"]}
                        for j, p in zip(quedan, pesos)],
            "afuera": sorted(afuera, key=lambda x: (x["motivo"], x["asset"]))}


@pesado
def para_la_pantalla(conn, activos: list, anios: int) -> dict:
    """La simulación con LAS series de la ficha (`tecnico.serie`) y los índices que
    se guardan todas las noches (`tecnico.indice`). `activos`: [(asset, local, peso)]."""
    lista = []
    for asset, local, peso in activos:
        s = tecnico.serie(conn, asset, "usd", local)
        lista.append({"asset": asset, "local": bool(local), "peso": peso, "velas": s["velas"],
                      "ticker": s.get("ticker"), "convertida": s.get("convertida")})
    return simular(lista, {clave: tecnico.indice(conn, simbolo) for clave, _, simbolo in INDICES}, anios)
