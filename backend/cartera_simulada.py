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
precio, con la compra al cierre de `anios` × 365 días atrás
(`tecnico.dia_de_arranque`, LA regla de la ficha y de Comparar; Nico, 06/11:
«como la ficha». Con el cierre del primer día, un día movido daba otro número que
la ficha). Un activo o un índice sin precios de la última semana, contada desde
hoy (`tecnico.es_vieja`), no entra y se dice. Si un activo cotiza desde después,
arranca el día de ese activo y lo dice (`recorte_por`); hasta una semana después
no es un recorte (`comparar.DIAS_MARGEN`: el borde de lo guardado, un feriado).
Los índices, con la misma semana y LA regla de Comparar (`comparar.dia_del_cien`):
con 5 años, lo que se pide es justo lo guardado, y si ese día cae un sábado el
S&P 500 empieza el lunes. Se arranca el lunes, en vez de dejarlo afuera.

AÑO POR AÑO (Nico, 06/11/2026: el total esconde si fue parejo o si un año lo
explica casi todo, «algo que probablemente no se vuelva a repetir»). El mismo
período, abierto en años de LA regla del período (`tecnico.dia_de_arranque`: el
cierre de 365 días para atrás desde el último precio), con la misma cartera sin tocar (`_anio_por_anio`).

QUÉ NO HACE. No recomienda nada ni mira para adelante: dice qué habría pasado.
"""
from __future__ import annotations

import bisect
from datetime import date

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


def _anio_por_anio(base: str, hasta: str, al: dict, recortado: bool = False):
    """El período abierto en años (Nico, 06/11/2026). `al`: {clave: lo que vale ese
    día} de la cartera ('cartera', en dólares de cada US$ 100) y de cada índice que
    está, con su último cierre hasta ese día. `recortado`: el de `simular`.

    Un año es el de LA regla del período (`tecnico.dia_de_arranque`), contado para atrás desde
    el último precio: el último año de un índice da lo mismo que elegir «1 año»
    (salvo un caso que hoy no pasa: el OTRO índice con menos de un año de historia,
    que arranca en la semana después del corte; «1 año» corre su primer día por él
    y acá queda afuera; auditoría de método 06/11, H3).
    La cartera es la de todo el período, sin tocar: cada año arranca con los pesos
    que le dejó el anterior («1 año» la compra de nuevo con los tuyos). Lo de antes
    del primer año entero es un tramo más corto (`completo` False), o va con el año
    que sigue si dura menos de `TRAMO_MIN_DIAS`. Sin recorte, el primero es un año
    aunque dure unos días menos: el primer día puede correrse una semana por un
    activo y otra por un índice, y salía «12 meses» debajo de «Los 5 años» (H2).
    Un tramo que arranca en 0 (un activo que se fue a cero, con el redondeo de
    `comparar.base_cien`) queda vacío en vez de dividir por cero (H1). None con un
    solo tramo: sería el total otra vez.

    {'tramos': [{desde, hasta, dias, completo, aporte, <clave>: %}], 'por_anio':
    {<clave>: %}}. `aporte`: cuánto de cada US$ 100 habría ganado (o perdido) la
    cartera en ese tramo; los de todos suman su resultado. `por_anio`: lo que
    habría que ganar todos los años, igual, para llegar al mismo total (compuesto,
    a 365 días, como el «Por año» del diario de operaciones)."""
    cortes = []
    for k in range(1, len(ANIOS) + 1):
        d = tecnico.dia_de_arranque(hasta, k * tecnico.DIAS_ANIO)
        if d <= base:
            break
        cortes.append(d)
    bordes = [base] + sorted(cortes) + [hasta]
    if len(bordes) > 2 and comparar._dias(bordes[0], bordes[1]) < TRAMO_MIN_DIAS:
        del bordes[1]
    if len(bordes) < 3:
        return None
    tramos = []
    for i, (a, b) in enumerate(zip(bordes, bordes[1:])):
        dias = comparar._dias(a, b)
        tramos.append({"desde": a, "hasta": b, "dias": dias,
                       "completo": dias >= tecnico.DIAS_ANIO - comparar.DIAS_MARGEN or (i == 0 and not recortado),
                       "aporte": al["cartera"](b) - al["cartera"](a),
                       **{clave: (f(b) / f(a) - 1) * 100 if f(a) else None for clave, f in al.items()}})
    dias = comparar._dias(base, hasta)
    return {"tramos": tramos,
            "por_anio": {clave: ((f(hasta) / f(base)) ** (tecnico.DIAS_ANIO / dias) - 1) * 100
                         for clave, f in al.items()}}


def simular(activos: list, indices: dict, anios: int, hoy: date) -> dict:
    """La simulación entera, sin base de datos (la usan la ruta y las pruebas).
    `hoy`: el día argentino, contra el que se mide si un precio es viejo.

    `activos`: [{asset, local, peso, velas, ticker, convertida}]. Los pesos
    suman 100 con `TOLERANCIA` (33,33 × 3, lo controla la ruta) y acá se llevan a
    100 exacto: así la cartera arranca en US$ 100 y los «aportó» suman su
    resultado (auditoría 05/11, H5). `indices`: {clave: velas} de `INDICES`.
    {'disponible': False, 'motivo', 'faltan'} si no se puede: 'sin_serie' (un
    activo sin precios), 'vieja' (un activo sin precios de la última semana,
    contada desde `hoy`; un activo solo también: auditoría 05/11, H9) o
    'poca_historia'. Un índice que falta no frena la cartera: va en `faltan`."""
    out = {"anios": anios, "moneda": "usd"}
    puntos = {a["asset"]: _puntos(a.get("velas") or []) for a in activos}
    sin = [a["asset"] for a in activos if not puntos[a["asset"]]]
    if sin:
        return {**out, "disponible": False, "motivo": "sin_serie",
                "faltan": [{"asset": s, "motivo": "sin_serie"} for s in sin]}
    viejas = [s for s, p in puntos.items() if tecnico.es_vieja(p[-1][0], hoy)]
    if viejas:
        return {**out, "disponible": False, "motivo": "vieja",
                "faltan": [{"asset": s, "motivo": "vieja", "hasta": puntos[s][-1][0]} for s in viejas]}

    hasta = max(p[-1][0] for p in puntos.values())
    pedido = tecnico.dia_de_arranque(hasta, anios * tecnico.DIAS_ANIO)
    primeras = {s: p[0][0] for s, p in puntos.items()}
    ultimo_en_llegar = max(primeras, key=lambda s: (primeras[s], s))
    # El primer día, con LA regla de Comparar (`comparar.dia_del_cien`): el primero
    # que tienen todos los activos, y si un índice empieza unos días después (con 5
    # años, el lunes después de un sábado), ése. Un índice sin su historia no corre
    # nada: queda afuera, en `faltan`.
    de_los_indices = {clave: _puntos(indices.get(clave) or []) for clave, _, _ in INDICES}
    base, de_los_activos = comparar.dia_del_cien(pedido, list(puntos.values()), list(de_los_indices.values()), hoy)
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
        if p and tecnico.es_vieja(p[-1][0], hoy):
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
        "anio_por_anio": _anio_por_anio(base, hasta, {"cartera": valor, **{c: v.al for c, v in varas.items()}},
                                        recortado),
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


def de_hoy(car: dict, hasta, hoy: date) -> dict:
    """«Mi cartera de hoy»: los activos de `car` (`senales_semana.cartera`, LA
    valuación de «tu plata») que se pueden simular, con su peso sobre 100 entre
    ellos (los porcentajes, nunca la plata). Quedan afuera, y se dice cuáles:
      · los que no tienen precio de todos los días (bonos, letras, fondos,
        efectivo, monedas estables): LA regla de la noche (`velas_diarias._yahoo_de`
        devuelve vacío), no una lista copiada;
      · los que no tienen precios de la última semana, contada desde `hoy`:
        LA regla con que después los rechaza la simulación (`tecnico.es_vieja`),
        con la fecha de LA serie con que se simula (`hasta`). Un activo que dejó
        de cotizar frenaba la cartera entera, y al sacarlo quedaba «Faltan 20%»:
        la única forma de volver a tus pesos era hacer la cuenta a mano
        (auditoría de pantalla 06/11, H3; Nico, 06/11: «Sí, así»). Si ninguno
        tiene precios de la última semana (la noche sin correr más de una
        semana), no se saca ninguno: sin ellos la tabla quedaba vacía y decía
        «Todavía no tenés acciones…»; con ellos, la simulación dice desde cuándo
        no hay precios. Uno sin precios guardados no cuenta como al día: con la
        noche caída y uno comprado después, quedaba ése solo, al 100 %, y los
        demás afuera como si hubieran dejado de cotizar (revisión 06/11);
      · si son más de `MAX_ACTIVOS`, los que menos pesan.
    `hasta(asset, local)`: el día del último precio con que se simularía
    (`ultimo_precio`), o None si todavía no hay ninguno (lo baja la simulación,
    como a un activo que nadie sigue): ése no queda afuera. Se pregunta de mayor
    a menor peso, sólo hasta llenar los `MAX_ACTIVOS`: cada pregunta lee la
    serie entera, la misma que lee la simulación.
    El mismo papel en BYMA y en Nueva York (GGAL de IOL y el ADR de Schwab) va
    junto: la cartera no repite activos. Su marca `local` es LA de la ficha
    (`esAccionLocal` de utils/accionLocal.js): acción argentina sólo si TODOS sus
    lotes son de BYMA; si no, el ADR. Antes decidía el lote más grande, y la
    cartera usaba otra serie que la ficha (auditoría 05/11, H3).
    `parte`: qué porcentaje de toda tu plata (`car['total']`: también el
    efectivo, los bonos, los fondos y los plazos fijos) es lo que se simula. Sin
    él, una cartera mitad fondo y mitad CEDEARs se veía como «tu cartera», toda en
    CEDEARs (auditoría de producto 05/11, A4). Un porcentaje, nunca la plata.
    `efectivo_o_plazos`: si en lo que no se simula hay efectivo o plazos fijos
    (`car['sin_medir']`), un sí o un no, nunca cuánto. Con MU afuera por sus
    precios, la nota decía «el 62% de tu plata» sin nombrar el 23 % en efectivo, y
    parecía que lo que faltaba era todo MU (revisión 06/11; Nico, 06/11: «Sí, que
    lo nombre»)."""
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
    quedan, viejas, k, al_dia = [], [], 0, False
    while k < len(orden) and len(quedan) < MAX_ACTIVOS:
        j, k = orden[k], k + 1
        h = hasta(j["asset"], j["local"])
        if h and tecnico.es_vieja(h, hoy):
            viejas.append({"asset": j["asset"], "tipo": j["tipo"], "motivo": "vieja", "hasta": h})
        else:
            quedan.append(j)
            al_dia = al_dia or bool(h)
    sobran = orden[k:]
    if not al_dia:
        quedan, sobran, viejas = orden[:MAX_ACTIVOS], orden[MAX_ACTIVOS:], []
    afuera += viejas + [{"asset": j["asset"], "tipo": j["tipo"], "motivo": "tope"} for j in sobran]
    pesos = _sobre_cien([j["valor"] for j in quedan]) if quedan else []
    total = car.get("total") or sum(v for v in car["tenencias"].values() if v > 0)
    simulado = sum(j["valor"] for j in quedan)
    return {"activos": [{"asset": j["asset"], "local": j["local"], "peso": p, "tipo": j["tipo"]}
                        for j, p in zip(quedan, pesos)],
            "afuera": sorted(afuera, key=lambda x: (x["motivo"], x["asset"])),
            "parte": round(simulado / total * 100) if total > 0 and quedan else None,
            "efectivo_o_plazos": (car.get("sin_medir") or 0) > 0}


def _serie(conn, asset: str, local: bool) -> dict:
    """LA serie con que se simula un activo: la de la ficha, en dólares (`tecnico.serie`)."""
    return tecnico.serie(conn, asset, "usd", local)


def ultimo_precio(conn, asset: str, local: bool):
    """El día del último precio con que se simularía `asset` (`_serie`, con las
    velas que sirven: `_puntos`), o None si todavía no hay ninguno. Lo pregunta
    «Mi cartera de hoy» (`de_hoy`). Con otra serie diría «al día» lo que la
    simulación rechaza: una acción argentina guardada hasta ayer, sin MEP de las
    últimas semanas, se simula sólo hasta el último día con dólar."""
    p = _puntos(_serie(conn, asset, local)["velas"])
    return p[-1][0] if p else None


@pesado
def para_la_pantalla(conn, activos: list, anios: int, hoy: date) -> dict:
    """La simulación con LAS series de la ficha (`_serie`) y los índices que se
    guardan todas las noches (`tecnico.indice`). `activos`: [(asset, local, peso)].
    `hoy`: el día argentino."""
    lista = []
    for asset, local, peso in activos:
        s = _serie(conn, asset, local)
        lista.append({"asset": asset, "local": bool(local), "peso": peso, "velas": s["velas"],
                      "ticker": s.get("ticker"), "convertida": s.get("convertida")})
    return simular(lista, {clave: tecnico.indice(conn, simbolo) for clave, _, simbolo in INDICES}, anios, hoy)
