"""Simular una cartera: qué habría pasado con US$ 100 repartidos en varios activos,
comprados el primer día y sin tocar, al lado del S&P 500 y del Nasdaq.

QUÉ ES. «Una cartera», dentro de la pestaña Backtesting de Análisis técnico (Nico,
05/11/2026: «antes de publicar, agregá simular cartera contra el S&P 500 y el
Nasdaq»; boceto aprobado, opción A: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5).
La persona arranca con su cartera de hoy o de cero, pone cada activo con su peso
sobre 100 y elige de 1 a 5 años.

CÓMO SE SIMULA.
  · Todo se compra el primer día con esos pesos y no se toca más (comprar y
    mantener, la misma vara que el Backtesting de una regla). Sin rebalancear, el
    que sube MÁS QUE EL RESTO pesa cada vez más, y el que sube menos (o baja),
    cada vez menos: subir solo no alcanza (auditoría 05/11, A4).
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
Los índices, con la misma semana y LA regla de Comparar (`comparar.dia_del_cien`):
con 5 años, lo que se pide es justo lo guardado, y si ese día cae un sábado el
S&P 500 empieza el lunes. Se arranca el lunes, en vez de dejarlo afuera.

AÑO POR AÑO (Nico, 06/11/2026: el total esconde si fue parejo o si un año lo
explica casi todo, «algo que probablemente no se vuelva a repetir»). El mismo
período, abierto en años de LA regla del período (`_primer_dia`: 365 días para
atrás desde el último precio), con la misma cartera sin tocar (`_anio_por_anio`).

QUÉ NO HACE. No recomienda nada ni mira para adelante: dice qué habría pasado.
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta

import backtest
import comparar
import tecnico
import velas_diarias
from pesado import pesado

# Cuántos activos entran en una cartera (la tabla y la barra se leen hasta ahí).
MAX_ACTIVOS = 10
# Los períodos: hasta todo lo que se guarda (`velas_diarias.ANIOS_GUARDADOS`). Eran
# los del Backtesting de una regla, que llega a 4 porque la media de 200 necesita
# casi un año ANTES del primer día; una cartera no necesita nada antes, y con 4 las
# cuatro ventanas caían en la suba que siguió a 2022 (producto 05/11, A5).
ANIOS = tuple(range(1, velas_diarias.ANIOS_GUARDADOS + 1))
# Los porcentajes tienen que sumar 100, con esta tolerancia por los decimales.
TOLERANCIA = 0.05
# (clave, nombre, símbolo de Yahoo), en el orden en que se muestran.
INDICES = (("sp500", "S&P 500", velas_diarias.SP500), ("nasdaq", "Nasdaq", velas_diarias.NASDAQ))
# Con menos días que esto no alcanza para decir nada (los del Backtesting).
MIN_DIAS = backtest.MIN_RUEDAS
# «Año por año»: lo de antes del primer año entero, si dura menos que esto, va con
# el año que sigue (un renglón de diez días no dice nada).
TRAMO_MIN_DIAS = 31


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


def _primer_dia(hasta: str, anios: int) -> str:
    """El primer día de los últimos `anios` años que terminan en `hasta`, el último
    precio: LA regla del período, la del pedido y la de cada año de «Año por año»."""
    corte = date.fromisoformat(hasta) - timedelta(days=anios * tecnico.DIAS_ANIO)
    return (corte + timedelta(days=1)).isoformat()


def _anio_por_anio(base: str, hasta: str, al: dict):
    """El período abierto en años (Nico, 06/11/2026). `al`: {clave: lo que vale ese
    día} de la cartera ('cartera', en dólares de cada US$ 100) y de cada índice que
    está, con su último cierre hasta ese día.

    Un año es el de LA regla del período (`_primer_dia`), contado para atrás desde
    el último precio: el último año de un índice da lo mismo que elegir «1 año».
    La cartera es la de todo el período, sin tocar: cada año arranca con los pesos
    que le dejó el anterior («1 año» la compra de nuevo con los tuyos). Lo de antes
    del primer año entero es un tramo más corto (`completo` False), o va con el año
    que sigue si dura menos de `TRAMO_MIN_DIAS`. None con un solo tramo: sería el
    total otra vez.

    {'tramos': [{desde, hasta, dias, completo, aporte, <clave>: %}], 'por_anio':
    {<clave>: %}}. `aporte`: cuánto de cada US$ 100 habría ganado (o perdido) la
    cartera en ese tramo; los de todos suman su resultado. `por_anio`: lo que
    habría que ganar todos los años, igual, para llegar al mismo total (compuesto,
    a 365 días, como el «Por año» del diario de operaciones)."""
    cortes = []
    for k in range(1, len(ANIOS) + 1):
        d = _primer_dia(hasta, k)
        if d <= base:
            break
        cortes.append(d)
    bordes = [base] + sorted(cortes) + [hasta]
    if len(bordes) > 2 and comparar._dias(bordes[0], bordes[1]) < TRAMO_MIN_DIAS:
        del bordes[1]
    if len(bordes) < 3:
        return None
    tramos = []
    for a, b in zip(bordes, bordes[1:]):
        dias = comparar._dias(a, b)
        tramos.append({"desde": a, "hasta": b, "dias": dias,
                       "completo": dias >= tecnico.DIAS_ANIO - comparar.DIAS_MARGEN,
                       "aporte": al["cartera"](b) - al["cartera"](a),
                       **{clave: (f(b) / f(a) - 1) * 100 for clave, f in al.items()}})
    dias = comparar._dias(base, hasta)
    return {"tramos": tramos,
            "por_anio": {clave: ((f(hasta) / f(base)) ** (tecnico.DIAS_ANIO / dias) - 1) * 100
                         for clave, f in al.items()}}


def simular(activos: list, indices: dict, anios: int) -> dict:
    """La simulación entera, sin base de datos (la usan la ruta y las pruebas).

    `activos`: [{asset, local, peso, velas, ticker, convertida}]. Los pesos
    suman 100 con `TOLERANCIA` (33,33 × 3, lo controla la ruta) y acá se llevan a
    100 exacto: así la cartera arranca en US$ 100 y los «aportó» suman su
    resultado (auditoría 05/11, H5). `indices`: {clave: velas} de `INDICES`.
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

    pedido = _primer_dia(hasta, anios)
    primeras = {s: p[0][0] for s, p in puntos.items()}
    ultimo_en_llegar = max(primeras, key=lambda s: (primeras[s], s))
    # El primer día, con LA regla de Comparar (`comparar.dia_del_cien`): el primero
    # que tienen todos los activos, y si un índice empieza unos días después (con 5
    # años, el lunes después de un sábado), ése. Un índice sin su historia no corre
    # nada: queda afuera, en `faltan`.
    de_los_indices = {clave: _puntos(indices.get(clave) or []) for clave, _, _ in INDICES}
    base, de_los_activos = comparar.dia_del_cien(pedido, list(puntos.values()), list(de_los_indices.values()), hasta)
    recortado = comparar._dias(pedido, de_los_activos) > comparar.DIAS_MARGEN
    fechas = sorted({base} | {d for p in puntos.values() for d, _ in p if base < d <= hasta})
    out.update({"pedido_desde": pedido, "recortado": recortado,
                "recorte_por": ultimo_en_llegar if recortado else None})
    if len(fechas) < MIN_DIAS:
        # `recorte_por` sólo si hubo recorte: con pocas ruedas sin recorte (una
        # acción poco negociada) no es que «cotiza hace muy poco» (auditoría 05/11, H10).
        return {**out, "disponible": False, "motivo": "poca_historia"}

    escritos = {a["asset"]: float(a["peso"]) for a in activos}
    suma = sum(escritos.values())
    pesos = {s: p * 100 / suma for s, p in escritos.items()}
    lineas = {s: _EnCien(p, base) for s, p in puntos.items()}

    def valor(d):
        # Lo que vale la cartera ese día, en dólares de cada US$ 100: la del gráfico
        # y la de «Año por año».
        return sum(pesos[s] / 100 * lineas[s].al(d) for s in pesos)

    cartera = [valor(d) for d in fechas]

    resumen_indices, faltan, curvas, varas = [], [], {}, {}
    for clave, nombre, simbolo in INDICES:
        p = de_los_indices[clave]
        # Primero si quedó viejo, como Comparar: uno que dejó de llegar y además
        # empieza en el borde decía «todavía no tenemos la historia» en vez de «no
        # tenemos precios desde el…» (auditoría de código 06/11, 6).
        if p and comparar._dias(p[-1][0], hasta) > comparar.DIAS_VIEJA:
            faltan.append({"clave": clave, "motivo": "vieja", "hasta": p[-1][0]})
            continue
        if not p or p[0][0] > base:
            faltan.append({"clave": clave, "motivo": "sin_datos"})
            continue
        linea = varas[clave] = _EnCien(p, base)
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
        "anio_por_anio": _anio_por_anio(base, hasta, {"cartera": valor, **{c: v.al for c, v in varas.items()}}),
        "curva": [{"d": d, "cartera": round(cartera[k], 2), **{c: round(curvas[c][k], 2) for c in curvas}}
                  for k, d in enumerate(fechas)],
    }


def _sobre_cien(valores: list, decimales: int = 1) -> list:
    """Los `valores` (todos > 0) como porcentajes con `decimales` que suman
    EXACTAMENTE 100: LA cuenta del resto mayor de «tu plata»
    (`senales_semana.repartir_enteros`), en décimos. Ninguno queda en 0: el que
    pesa menos de un décimo lleva uno, sacado del que más pesa. Con 0 la fila
    quedaba vacía y «Mi cartera de hoy» no se simulaba (US$ 20 de BTC al lado de
    US$ 50.000 en acciones; auditoría 05/11, H7)."""
    import senales_semana
    total = sum(valores)
    paso = 10 ** decimales
    enteros = senales_semana.repartir_enteros([v / total * 100 * paso for v in valores], 100 * paso)
    for k, e in enumerate(enteros):
        if e < 1:
            mayor = max(range(len(enteros)), key=lambda i: enteros[i])
            enteros[mayor] -= 1 - e
            enteros[k] = 1
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
    junto: la cartera no repite activos. Su marca `local` es LA de la ficha
    (`esAccionLocal` de utils/accionLocal.js): acción argentina sólo si TODOS sus
    lotes son de BYMA; si no, el ADR. Antes decidía el lote más grande, y la
    cartera usaba otra serie que la ficha (auditoría 05/11, H3).
    `parte`: qué porcentaje de toda tu plata (`car['total']`: también el
    efectivo, los bonos, los fondos y los plazos fijos) es lo que se simula. Sin
    él, una cartera mitad fondo y mitad CEDEARs se veía como «tu cartera», toda en
    CEDEARs (auditoría de producto 05/11, A4). Un porcentaje, nunca la plata."""
    from cripto import yahoo_de_cripto
    juntos, afuera = {}, []
    for (asset, local), valor in car["tenencias"].items():
        tipo = car["tipos"].get((asset, local)) or None
        if valor <= 0:
            continue
        if not velas_diarias._yahoo_de(asset, tipo, bool(local), yahoo_de_cripto):
            afuera.append({"asset": asset, "tipo": tipo, "motivo": "sin_serie"})
            continue
        j = juntos.setdefault(asset, {"asset": asset, "valor": 0.0, "mayor": 0.0, "local": True, "tipo": tipo})
        j["valor"] += valor
        j["local"] = j["local"] and bool(local)
        if valor > j["mayor"]:
            j.update(mayor=valor, tipo=tipo)
    orden = sorted(juntos.values(), key=lambda j: (-j["valor"], j["asset"]))
    quedan, sobran = orden[:MAX_ACTIVOS], orden[MAX_ACTIVOS:]
    afuera += [{"asset": j["asset"], "tipo": j["tipo"], "motivo": "tope"} for j in sobran]
    pesos = _sobre_cien([j["valor"] for j in quedan]) if quedan else []
    total = car.get("total") or sum(v for v in car["tenencias"].values() if v > 0)
    simulado = sum(j["valor"] for j in quedan)
    return {"activos": [{"asset": j["asset"], "local": j["local"], "peso": p, "tipo": j["tipo"]}
                        for j, p in zip(quedan, pesos)],
            "afuera": sorted(afuera, key=lambda x: (x["motivo"], x["asset"])),
            "parte": round(simulado / total * 100) if total > 0 and quedan else None}


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
