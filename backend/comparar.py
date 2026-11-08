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

HASTA CUÁNDO. Todas las líneas terminan el último día con precio de los
activos (nunca después de hoy: la UVA se publica por adelantado). Una línea
sin precios de la última semana contada desde HOY (`tecnico.es_vieja`: un activo
que dejó de cotizar, un índice que la fuente dejó de mandar) NO se dibuja: se
dice hasta cuándo llega (`faltan`, motivo 'vieja'). Dibujarla daba su último
valor como si fuera de hoy y la frase la comparaba contra el S&P de ayer
(auditoría 29/10). Contada desde el activo más nuevo, un activo solo que dejó
de cotizar se dibujaba igual (auditoría de «Una cartera» 05/11, H9).

CÓMO SE ELIGE EL DÍA DEL 100.
  · El pedido trae tu primera compra (`desde`, la calcula la pantalla con la
    misma regla de la ficha, `primeraCompra`) o «1 año» / «3 años» (`anios`):
    los últimos N años que terminan en el último precio de los activos, no hoy
    (Nico, 06/11/2026: desde hoy, un domingo, un lunes o después de un feriado
    arrancaba otro día que el Backtesting para el mismo activo), y el 100 es el
    cierre de N × 365 días atrás (`tecnico.dia_de_arranque`, LA regla
    de la ficha y de «Una cartera»; Nico, 06/11: «como la ficha»). Con el cierre
    del primer día, un día movido daba otro número que la ficha (+21 % contra +5 %).
  · Si `desde` cae un día sin precio (fin de semana, feriado), vale el último
    cierre anterior: es el precio que tenía ese día.
  · Si un activo empieza DESPUÉS de `desde`, el 100 se corre para TODOS al
    primer día que tienen todos (cada uno con su propio día de arranque no sería
    comparar desde la misma base) y la respuesta dice por qué: `base_corrida_por`
    es el activo que cotiza hace menos; si todos empiezan juntos donde empieza
    lo guardado (el S&P 500 guarda la historia entera), no es culpa de ninguno:
    `base_corrida` sin `base_corrida_por`.
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

from datetime import date

import tecnico

MAX_ACTIVOS = 4
# «1 año» y «3 años», en años: se cortan por FECHA (días corridos) hasta el
# último precio, como la ficha (`tecnico.dia_de_arranque`).
PLAZOS = {"1a": 1, "3a": 3}
VARAS = ("sp500", "mep", "cer")
# Un activo que empieza hasta una semana después del día pedido no «corre» el
# 100: es el borde de lo guardado (3 años justos) o un feriado largo, no un
# activo que cotiza hace menos. El 100 va a su primer día igual, sin aviso.
DIAS_MARGEN = 7


def _dias(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days
NOMBRE_VARA = {"sp500": "S&P 500", "mep": "Guardar dólares", "cer": "Inflación (CER)"}


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


def dia_del_cien(desde: str, activos: list, varas: list, hoy: date) -> tuple:
    """LA regla del día en que todo arranca en 100, la de Comparar y la de «Una
    cartera» de Backtesting (cartera_simulada.simular). `activos` y `varas`:
    listas de puntos [(fecha, valor)] ordenados; `varas`, las series contra las que
    se compara que tienen su propia historia guardada (el S&P 500, el Nasdaq).
    Devuelve (el día del 100, el de los activos solos).

    El de los activos: el más tardío entre `desde` y el día desde el que cuenta cada
    activo (`arranque`: su primer precio si cotiza desde después; el primero después
    del hueco si le faltan precios de más de 10 días justo antes de `desde`,
    `tecnico.base_vieja`). Si queda a más de `DIAS_MARGEN` días de `desde`, un activo cotiza
    hace menos o tiene un hueco (o lo guardado empieza ahí), y cada pantalla lo dice.

    El del 100: si una vara empieza hasta `DIAS_MARGEN` días DESPUÉS del de los
    activos, el de esa vara. En el borde de lo guardado cada serie tiene su
    calendario (la cripto opera el sábado, BYMA y Nueva York tienen feriados
    distintos) y su propio día de bajada entera, y el S&P 500 empezaba el lunes y
    quedaba afuera («sin datos desde esa fecha»): en «Una cartera» con 5 años y en
    Comparar con «desde tu primera compra» de antes de lo guardado (auditoría de
    método 06/11, H1). Una vara que empieza mucho después (no tenemos su historia)
    o que quedó vieja (`tecnico.es_vieja`, contra `hoy`) no corre nada: queda
    afuera y se dice."""
    de_los_activos = max([desde] + [arranque(p, desde)["dia"] for p in activos if p])
    corren = [p[0][0] for p in varas
              if p and de_los_activos < p[0][0] and _dias(de_los_activos, p[0][0]) <= DIAS_MARGEN
              and not tecnico.es_vieja(p[-1][0], hoy)]
    return max([de_los_activos] + corren), de_los_activos


def arranque(puntos: list, desde: str):
    """Desde qué día cuenta `puntos` [(fecha, valor)] en un período que arranca
    `desde`: LA regla, `tecnico.arranque_de_la_serie` ({'dia', 'hueco'})."""
    return tecnico.arranque_de_la_serie([d for d, _ in puntos], desde)


def _mep(conn, desde: str) -> list:
    """El MEP de cada día desde `desde` (y el último anterior, para el día del
    100), con la regla de `fx.fx_for_date`."""
    from fx import serie_diaria
    return [(d, tc) for d, tc, _ in serie_diaria(conn, desde)]


def comparar(conn, activos: list, moneda: str, desde: str = None, *, anios: int = None,
             cer=None, cer_basis: str = None, hoy: date = None) -> dict:
    """La comparación entera.

    `activos`: [(asset, local)] con `local` igual que la ficha (acción argentina
    → su precio de BYMA). `moneda`: 'usd' | 'ars'. Desde cuándo: `desde`
    ('YYYY-MM-DD', tu primera compra) o `anios` (los últimos N años hasta el
    último precio de los activos, con el 100 de `tecnico.dia_de_arranque`). `cer`: la serie del
    índice desde un día, `cer(dia)` → [(fecha, valor)] (sólo en pesos; vive en
    `main`, y el día lo sabe esta cuenta), y `cer_basis` con qué se armó ('CER' o
    'UVA'). `hoy`: el día argentino (ninguna línea pasa de hoy, y la que no tiene
    precios de la última semana contada desde hoy no se dibuja).

    {moneda, desde, base, base_corrida, base_corrida_por, base_corrida_hueco, hasta, series:
    [{clave, tipo, nombre, ticker, convertida, puntos, final, fecha_final}],
    faltan: [{clave, motivo, hasta?}]}. `base` es el día del 100 y `hasta` el
    último día (None si ningún activo tiene precios de la última semana).
    `base_corrida_hueco`: si el que corrió el 100 tiene un hueco de precios justo
    antes de `desde`, los días que le faltan ({desde, hasta}); si no, None."""
    from fechas import hoy_art_date
    moneda = "ars" if moneda == "ars" else "usd"
    hoy = hoy or hoy_art_date()
    tope = hoy.isoformat()
    out = {"moneda": moneda, "desde": desde, "base": None, "base_corrida": False,
           "base_corrida_por": None, "base_corrida_hueco": None, "hasta": None, "series": [], "faltan": []}

    crudas = []
    for asset, local in activos:
        # Todo arranca en 100: la escala de un CEDEAR estimado en pesos no cambia
        # ninguna línea, y uno sin escala conocida se compara igual (la acción de
        # afuera × el MEP). Sin esto, NET desaparecía de Comparar en pesos
        # (auditoría 06/11, H4 de la serie).
        s = tecnico.serie(conn, asset, moneda, bool(local), escala_obligatoria=False)
        puntos = [p for p in _cierres(s["velas"]) if p[0] <= tope]
        if not puntos:
            out["faltan"].append({"clave": asset, "motivo": "sin_datos"})
            continue
        crudas.append({"clave": asset, "tipo": "activo", "nombre": asset, "local": bool(local),
                       "ticker": s.get("ticker"), "convertida": s.get("convertida"), "puntos": puntos})
    # El que no tiene precios de la última semana, contada desde hoy, no se dibuja.
    for c in [c for c in crudas if tecnico.es_vieja(c["puntos"][-1][0], hoy)]:
        crudas.remove(c)
        out["faltan"].append({"clave": c["clave"], "motivo": "vieja", "hasta": c["puntos"][-1][0]})
    if not crudas:
        return out

    # Hasta cuándo: el último día con precio de los activos. «1 año» y «3 años»
    # terminan ahí, y arrancan con el cierre de N años antes (`tecnico.dia_de_arranque`).
    hasta = max(c["puntos"][-1][0] for c in crudas)
    out["hasta"] = hasta
    if anios:
        desde = tecnico.dia_de_arranque(hasta, anios * tecnico.DIAS_ANIO)
        out["desde"] = desde

    # El día del 100: `desde`, o el primero que tienen TODOS si alguno empieza
    # después; y si el S&P 500 empieza unos días después (el borde de lo guardado),
    # ése (`dia_del_cien`, LA regla de las dos pantallas).
    sp = _cierres(tecnico.sp500(conn, moneda))
    base, de_los_activos = dia_del_cien(desde, [c["puntos"] for c in crudas], [sp], hoy)
    # El que llega último, y si llega tarde por un hueco de precios: eso se dice
    # siempre, aunque el primer precio después caiga en la semana de margen (el
    # hueco ya tiene más de 10 días: no es un feriado largo).
    inicios = {c["clave"]: arranque(c["puntos"], desde) for c in crudas}
    ultimo_en_llegar = max(crudas, key=lambda c: inicios[c["clave"]]["dia"])
    hueco = inicios[ultimo_en_llegar["clave"]]["hueco"]
    if _dias(desde, de_los_activos) > DIAS_MARGEN or hueco:
        out["base_corrida"] = True
        # ¿Cotiza hace menos, o es donde empieza lo guardado para todos? El S&P
        # guarda la historia entera: si arranca bastante antes, es el activo.
        guardado = sp[0][0] if sp else min(c["puntos"][0][0] for c in crudas)
        if hueco or _dias(guardado, inicios[ultimo_en_llegar["clave"]]["dia"]) > DIAS_MARGEN:
            out["base_corrida_por"] = ultimo_en_llegar["clave"]
            out["base_corrida_hueco"] = hueco
    out["base"] = base

    varas = [{"clave": "sp500", "puntos": sp, "ticker": "^GSPC"}]
    if moneda == "usd":
        # Un dólar guardado sigue siendo un dólar: 100 de punta a punta.
        varas.append({"clave": "mep", "puntos": [(base, 1.0), (hasta, 1.0)], "ticker": None})
        out["faltan"].append({"clave": "cer", "motivo": "solo_en_pesos"})
    else:
        varas.append({"clave": "mep", "puntos": _mep(conn, base), "ticker": None})
        varas.append({"clave": "cer", "puntos": sorted(cer(base) if cer else []), "ticker": cer_basis})

    for c in crudas:
        c["puntos"] = base_cien(c["puntos"], base)
    for v in varas:
        # Vieja contra hoy, con lo que llegó hasta hoy (la UVA se publica
        # adelantada); se dibuja hasta el último día de los activos.
        hasta_aca = [x for x in v["puntos"] if x[0] <= tope]
        if hasta_aca and tecnico.es_vieja(hasta_aca[-1][0], hoy):
            out["faltan"].append({"clave": v["clave"], "motivo": "vieja", "hasta": hasta_aca[-1][0]})
            continue
        puntos = [x for x in v["puntos"] if x[0] <= hasta]
        p = base_cien(puntos, base)
        if len(p) < 2:
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
