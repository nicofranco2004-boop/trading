"""resumen_tecnico_hechos — los datos que recibe Mervall-E para el resumen de la ficha.

LAS CUENTAS LAS HACE RENDI, NO LA IA. Toma la MISMA respuesta que dibuja la
ficha (`tecnico.para_la_ficha`, sin nada del usuario) y la pasa a palabras:
números redondeados a la argentina («84.000», «1.855», «4,56»), fechas como
«21 de octubre», la proporción de lo que se deshizo del último movimiento
(«más o menos un tercio»), el dato del titular elegido por una regla fija, y
cada indicador con lo que significa. El modelo sólo ordena y cuenta.

La primera prueba con Sonnet (22/10) dijo «un tercio» y otra vez «dos tercios»
donde MercadoLibre había recuperado casi la mitad, y «ayer» por un dato del día.

Lo armó y lo midió la sesión «Redacción del resumen de Mervall-E» (vuelta 8: 20
resúmenes, 0 números inventados) junto con el pedido, que vive al lado en
`resumen_tecnico_pedido.txt`. Se reemplazan juntos: el pedido nombra las claves
de acá («para_el_titular», «movimientos_recientes»…).

Precios de los movimientos: lo que TOCÓ en el día (los picos de estructura.py),
porque contar los giros con el cierre de ese día contaba peor la historia
(vuelta 5). El cierre más alto y el más bajo del año son de CIERRE; cuando caen
el mismo día que un giro, se dice que no se repita su precio, para que nunca
haya dos precios para un mismo día.
"""
import math
from datetime import date, timedelta

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


# ─── formato a la argentina ──────────────────────────────────────────────────

def num(x):
    """Redondeo para leer: 84.000 · 1.855 · 222 · 37,5 · 4,56."""
    ax = abs(x)
    if ax >= 10000:
        x, d = round(x, -2), 0
    elif ax >= 100:
        x, d = round(x), 0
    elif ax >= 10:
        x, d = round(x, 1), 1
    elif ax >= 1 or ax == 0:
        x, d = round(x, 2), 2
    else:
        # Abajo de 1 (una cripto de US$ 0,0004): 3 cifras significativas. Con
        # dos decimales fijos decía «0 dólares».
        d = max(2, 2 - int(math.floor(math.log10(ax))))
        x = round(x, d)
    s = f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def plata(x, moneda):
    return f"{num(x)} {'pesos' if moneda == 'ars' else 'dólares'}"


def pct(x):
    """Porcentaje entero, con signo en palabras lo pone quien lo usa."""
    v = abs(x)
    return f"{round(v)} %" if v >= 1 else "menos de 1 %"


def fecha(iso, hoy_iso):
    d, h = date.fromisoformat(iso), date.fromisoformat(hoy_iso)
    base = f"{d.day} de {MESES[d.month - 1]}"
    if d.year == h.year:
        return base
    if d.year == h.year - 1:
        return base + " del año pasado"
    return base + f" de {d.year}"


def proporcion(q):
    """Fracción de un movimiento que se deshizo, en palabras."""
    if q < 0.12:
        return "casi nada"
    if q < 0.30:
        return "más o menos un cuarto"
    if q < 0.42:
        return "más o menos un tercio"
    if q < 0.58:
        return "más o menos la mitad"
    if q < 0.70:
        return "casi dos tercios"
    if q < 0.85:
        return "más o menos tres cuartos"
    if q < 0.97:
        return "casi todo"
    if q <= 1.03:
        return "todo"
    return "todo y un poco más"


# ─── los hechos ──────────────────────────────────────────────────────────────

def _cierre_hace(puntos, dias):
    piso = (date.fromisoformat(puntos[-1]["d"]) - timedelta(days=dias)).isoformat()
    previos = [p for p in puntos if p["d"] <= piso]
    return previos[-1] if previos else None


def _mov(p0, p1, moneda, hoy):
    sube = p1["precio"] >= p0["precio"]
    return (f"{'subió' if sube else 'bajó'} de {plata(p0['precio'], moneda)} ({fecha(p0['fecha'], hoy)}) "
            f"a {plata(p1['precio'], moneda)} ({fecha(p1['fecha'], hoy)})")


def hechos(nombre, r):
    l, pts, mon = r["lectura"], r["puntos"], r["moneda"]
    hoy = l["fecha"]
    precio = l["precio"]
    h = {
        "activo": nombre,
        "moneda": "pesos" if mon == "ars" else "dólares",
        "ultimo_cierre": f"{fecha(hoy, hoy)} (es el último dato; puede no ser hoy)",
        "precio_al_ultimo_cierre": plata(precio, mon),
    }
    # El dato del titular lo elige una regla fija (v7: dejarlo al modelo hizo que contrapusiera
    # plazos en casi todos los textos y, una vez, que se corrigiera en voz alta).
    var = {}
    for etiqueta, dias in (("en tres meses", 91), ("en un año", 365)):
        p0 = _cierre_hace(pts, dias)
        if p0:
            var[etiqueta] = (precio / p0["c"] - 1) * 100

    def dicho(etiqueta):
        v = var[etiqueta]
        return f"{etiqueta[0].upper() + etiqueta[1:]} {'subió' if v >= 0 else 'bajó'} {pct(v)}"
    # Máximo y mínimo del año, de cierre
    piso = (date.fromisoformat(hoy) - timedelta(days=365)).isoformat()
    anio = [p for p in pts if p["d"] > piso]
    pmax = max(anio, key=lambda p: p["c"])
    pmin = min(anio, key=lambda p: p["c"])
    dmax = (precio / pmax["c"] - 1) * 100
    dmin = (precio / pmin["c"] - 1) * 100
    # «Cerró en su precio más alto del año» sólo si ES el más alto. Con «a menos
    # de 0,5 %» Coca-Cola en pesos lo decía cerrando en 30.300 un día después de
    # cerrar en 30.420 (22/10): queda «muy cerca».
    en_max, en_min = pmax["d"] == hoy, pmin["d"] == hoy
    cerca_max, cerca_min = not en_max and dmax > -0.5, not en_min and dmin < 0.5
    h["cierre_mas_alto_del_año"] = (f"{plata(pmax['c'], mon)} el {fecha(pmax['d'], hoy)}; "
                                     + ("el último cierre es ese mismo" if en_max else f"al último cierre está {pct(dmax)} abajo"))
    a1, a3 = var.get("en un año"), var.get("en tres meses")
    if en_max or cerca_max:
        tit = (f"Cerró {'en' if en_max else 'muy cerca de'} su precio más alto del año"
               + (f"; {dicho('en un año').lower()}" if a1 is not None else ""))
    elif en_min or cerca_min:
        tit = (f"Cerró {'en' if en_min else 'muy cerca de'} su precio más bajo del año"
               + (f"; {dicho('en un año').lower()}" if a1 is not None else ""))
    elif a1 is not None and a3 is not None and (a1 >= 0) != (a3 >= 0) and abs(a1) >= 10 and abs(a3) >= 10:
        tit = f"{dicho('en un año')}, pero {dicho('en tres meses').lower()}"
    elif a1 is not None:
        tit = dicho("en un año")
    else:
        tit = dicho("en tres meses") if a3 is not None else None
    if tit:
        h = {"para_el_titular": tit, **h}
    h["cierre_mas_bajo_del_año"] = (f"{plata(pmin['c'], mon)} el {fecha(pmin['d'], hoy)}; "
                                     + ("el último cierre es ese mismo" if en_min else f"al último cierre está {pct(dmin)} arriba"))
    # Promedios
    if l.get("media200"):
        d = l["dist_media200"]
        pend = l.get("pendiente_media200")
        if abs(d) < 2:
            lect = (f"el precio está prácticamente sobre ese promedio ({pct(d)} {'arriba' if d >= 0 else 'abajo'})"
                    " → no hay una tendencia de fondo clara")
        else:
            lect = (f"el precio está {pct(d)} {'arriba' if d >= 0 else 'abajo'} de ese promedio"
                    + (" → la tendencia de fondo es para arriba" if d >= 0 else " → la tendencia de fondo es para abajo"))
        h["promedio_de_los_ultimos_200_dias"] = (
            f"{plata(l['media200'], mon)}; {lect}"
            + (f"; el promedio mismo viene {'subiendo' if pend >= 0 else 'bajando'} en el último mes" if pend is not None else ""))
    # Movimientos recientes (los de la estructura de Fibonacci)
    f = r.get("fibonacci") or {}
    cierre_de = {p["d"]: p["c"] for p in pts}

    def al_cierre(punto):  # v5 probó el cierre del día del giro: peor (ver tabla de vueltas)
        return punto

    movs = {}
    t = f if f.get("disponible") else f.get("superado")
    if t:
        t = {**t, "desde": al_cierre(t["desde"]), "hasta": al_cierre(t["hasta"])}
        a, b = t["desde"]["precio"], t["hasta"]["precio"]
        q = (b - precio) / (b - a) if b != a else None
        txt = _mov(t["desde"], t["hasta"], mon, hoy)
        if q is not None:
            if t["dir"] == "suba":
                fin = (f"; al último cierre, de esa suba había perdido {proporcion(q)}" if q > 0
                       else "; al último cierre está todavía más arriba que el final de esa suba")
                if q > 1.03:
                    fin += f" (quedó más abajo que los {plata(t['desde']['precio'], mon)} donde había arrancado)"
            else:
                fin = (f"; al último cierre, de esa bajada había recuperado {proporcion(q)}" if q > 0
                       else "; al último cierre está todavía más abajo que el final de esa bajada")
                if q > 1.03:
                    fin += f" (quedó más arriba que los {plata(t['desde']['precio'], mon)} donde había arrancado)"
            txt += fin
        movs["la_ultima_suba_o_bajada_terminada"] = txt + " (precios que tocó)"
    e = f.get("en_curso")
    if e:
        e = {**e, "desde": al_cierre(e["desde"]), "hasta": al_cierre(e["hasta"])}
        # Termina el mismo último día: va el CIERRE, no lo que tocó (dos precios
        # para un día confunden). Lo mismo si el último cierre es el más alto
        # del año y la suba viene de ahí: Apple «cerró en su precio más alto
        # del año» (344) y «subió a 348 el 13 de octubre» (lo que tocó ese día)
        # se leían como una contradicción (22/10).
        if (e["hasta"]["fecha"] == hoy or (e["dir"] == "suba" and en_max)
                or (e["dir"] == "bajada" and en_min)):
            txt = (f"la que viene ahora: {'subió' if e['dir'] == 'suba' else 'bajó'} de "
                   f"{plata(e['desde']['precio'], mon)} ({fecha(e['desde']['fecha'], hoy)}) "
                   f"hasta el último cierre")
        else:
            b = e["hasta"]["precio"]
            txt = "la que viene ahora: " + _mov(e["desde"], e["hasta"], mon, hoy) + " (precios que tocó)"
            dist = (precio / b - 1) * 100
            if abs(dist) >= 0.5:
                txt += f"; al último cierre está {pct(dist)} {'arriba' if dist > 0 else 'abajo'} de ese punto"
        movs["el_movimiento_de_ahora"] = txt
        s = e.get("se_rompe_si_cierra") or {}
        if "encima_de" in s:
            movs["que_terminaria_la_bajada_de_ahora"] = (f"que cierre arriba de {plata(s['encima_de'], mon)}, "
                                                         f"el máximo que tocó el {fecha(s['fecha'], hoy)}")
        if "debajo_de" in s:
            movs["que_terminaria_la_suba_de_ahora"] = (f"que cierre abajo de {plata(s['debajo_de'], mon)}, "
                                                       f"el mínimo que tocó el {fecha(s['fecha'], hoy)}")
    if movs:
        h["movimientos_recientes"] = movs
        giros = {x["fecha"] for m in (t, e) if m for x in (m["desde"], m["hasta"])}
        for clave, punto in (("cierre_mas_alto_del_año", pmax), ("cierre_mas_bajo_del_año", pmin)):
            if punto["d"] in giros and punto["d"] != hoy:
                dd = (precio / punto["c"] - 1) * 100
                h[clave] = (f"el del {fecha(punto['d'], hoy)}, el mismo día que arranca o termina uno de los movimientos "
                            f"(no repitas su precio); al último cierre está {pct(dd)} {'arriba' if dd >= 0 else 'abajo'}")
    # Indicadores, ya leídos
    ind = {}
    rsi = l.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            lect = "arriba de 70: subió muy rápido en poco tiempo"
        elif rsi <= 30:
            lect = "abajo de 30: cayó muy rápido en poco tiempo"
        elif rsi >= 55:
            lect = "arriba de 50: el precio viene ganando fuerza"
        elif rsi <= 45:
            lect = "abajo de 50: el precio viene perdiendo fuerza"
        else:
            lect = "cerca de 50: ni gana ni pierde fuerza"
        c = l.get("rsi_cruce")
        if c:
            lect += ("; hace " + str(c["hace"]) + " días de mercado salió de abajo de 30 (había caído muy rápido)"
                     if c["tipo"] == "salio_de_abajo" else
                     "; hace " + str(c["hace"]) + " días de mercado bajó de 70 (venía de subir muy rápido)")
        ind["fuerza_del_precio_RSI"] = f"{round(rsi)} ({lect})"
    a = l.get("adx")
    if a is not None:
        lect = "arriba de 23: la tendencia es firme" if a >= 23 else "abajo de 23: la tendencia es floja, sin un rumbo firme"
        p = l.get("adx_pendiente")
        if p is not None and abs(p) >= 1:
            lect += "; viene creciendo" if p > 0 else "; viene aflojando"
        c = l.get("adx_cruce")
        if c:
            lect += (f"; hace {c['hace']} días de mercado pasó arriba de 23" if c["tipo"] == "paso_arriba"
                     else f"; hace {c['hace']} días de mercado bajó de 23")
        ind["fuerza_de_la_tendencia_ADX"] = f"{round(a)} ({lect}; no dice para dónde va)"
    col = l.get("squeeze_color")
    if col:
        ind["empuje_de_los_ultimos_dias_Squeeze"] = {
            "verde_fuerte": "verde y creciendo: empuja para arriba, cada vez más",
            "verde_apagado": "verde pero achicándose: empuja para arriba, cada vez menos",
            "rojo_fuerte": "rojo y creciendo: empuja para abajo, cada vez más",
            "rojo_apagado": "rojo pero achicándose: empuja para abajo, cada vez menos",
        }.get(col, col)
    v = l.get("volumen_vs_promedio")
    if v and (v >= 1.5 or v <= 0.5):
        ind["cantidad_negociada"] = (f"el último día se negoció {num(v)} veces lo normal de las últimas 4 semanas" if v >= 1.5
                                     else "el último día se negoció menos de la mitad de lo normal de las últimas 4 semanas")
    h["indicadores"] = ind
    return h


def para_el_resumen(ficha: dict, nombre: str):
    """Los hechos del resumen, o None si la ficha no tiene con qué contar."""
    if not ficha or not ficha.get("disponible") or len(ficha.get("puntos") or []) < 30:
        return None
    if not (ficha.get("lectura") or {}).get("fecha"):
        return None
    return hechos(nombre, ficha)
