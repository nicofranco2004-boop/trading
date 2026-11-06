"""resumen_tecnico_hechos — los datos que recibe Mervall-E para el resumen de la ficha.

LAS CUENTAS LAS HACE RENDI, NO LA IA. Toma la MISMA respuesta que dibuja la
ficha (`tecnico.para_la_ficha`, sin nada del usuario) y la pasa a palabras:
números redondeados a la argentina («84.000», «1.855», «4,56»), fechas como
«21 de octubre», la proporción de lo que se deshizo del último movimiento
(«más o menos un tercio»), el dato del titular elegido por una regla fija, y
cada indicador con lo que significa. El modelo sólo ordena y cuenta.

La primera prueba con Sonnet (22/10) dijo «un tercio» y otra vez «dos tercios»
donde MercadoLibre había recuperado casi la mitad, y «ayer» por un dato del día.

Lo armó y lo midió la sesión «Redacción del resumen de Mervall-E» (vuelta 20, sobre 24
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
    # v18: «todo» sólo desde 1. Tesla decía «ya recuperó todo» con 386 contra un pico de 387 (0,976).
    if q < 1.0:
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


def hechos(nombre, r, todos_los_indicadores=False):
    """Los indicadores van por lo que significan, sin sigla: «la fuerza de la
    tendencia», no «(ADX)» (Nico, 30/10: «no tiene que usar tecnicismos… que use
    palabras normales»; antes el resumen las ponía entre paréntesis). El nombre
    de la clave también es parte del pedido: el modelo repite lo que lee.
    `todos_los_indicadores`: el chat recibe además todos los indicadores leídos
    (alguien puede preguntar «¿tiene fuerza?» aunque ninguno «sume» a la historia)."""
    l, pts, mon = r["lectura"], r["puntos"], r["moneda"]
    hoy = l["fecha"]
    precio = l["precio"]
    h = {
        "activo": nombre,
        "moneda": "pesos" if mon == "ars" else "dólares",
        "ultimo_cierre": f"{fecha(hoy, hoy)} (es el último dato que hay)",
        "precio_al_ultimo_cierre": plata(precio, mon),
    }
    if r.get("escala"):
        # En pesos, un CEDEAR sin su serie en pesos al día: el gráfico es un
        # ESTIMADO (la acción de Nueva York × el contado con liqui ÷ los CEDEARs
        # que hacen una acción, `tecnico.serie`; el MEP en una base que todavía no
        # tiene el contado con liqui: `convertida`) y sus precios quedan un poco
        # lejos de los de la Bolsa. El pie del gráfico lo dice; el texto que dé un
        # precio, también.
        h["los_precios_en_pesos_son"] = (
            "un estimado del CEDEAR hecho con la acción de Nueva York y el MEP: pueden estar unos pocos % "
            "lejos de su precio en la Bolsa" if r.get("convertida") == "mep" else
            "un estimado del CEDEAR hecho con la acción de Nueva York y el contado con liqui: pueden estar "
            "alrededor de 1 % lejos de su precio en la Bolsa")
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
    # Máximo y mínimo del año, de cierre (el año de la ficha: tecnico.primer_dia)
    import tecnico
    desde = tecnico.primer_dia(hoy, tecnico.DIAS_ANIO)
    anio = [p for p in pts if p["d"] >= desde]
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
    # v15: frase natural («En un año subió 31 % y cerró en…»). Con el «;» el modelo
    # intentaba reacomodarla y una vez dejó el borrador a la vista (Netflix, v14).
    if en_max or cerca_max:
        tit = ((f"{dicho('en un año')} y cerró " if a1 is not None else "Cerró ")
               + f"{'en' if en_max else 'muy cerca de'} su precio más alto del año")
    elif en_min or cerca_min:
        tit = ((f"{dicho('en un año')} y cerró " if a1 is not None else "Cerró ")
               + f"{'en' if en_min else 'muy cerca de'} su precio más bajo del año")
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
                    # Las palabras de Nico (30/10): «la tendencia de fondo es bajista», no «de fondo va para abajo».
                    + (" → la tendencia de fondo es alcista" if d >= 0 else " → la tendencia de fondo es bajista"))
        # v11: 200 días de mercado dichos en meses (una cripto cotiza todos los días:
        # 200 días son ~7 meses, no ~10). El juez a ciegas marcó en 15 de 20 textos que
        # «el promedio de 200 días» no explicaba por qué dice algo de la tendencia.
        meses = None
        if len(pts) >= 200:
            meses = round((date.fromisoformat(hoy) - date.fromisoformat(pts[-200]["d"])).days / 30.44)
        h["promedio_de_los_ultimos_200_dias"] = (
            f"{plata(l['media200'], mon)}"
            + (f" (es su precio promedio de los últimos {meses} meses)" if meses else "")
            + f"; {lect}"
            # v9: sólo cuando va EN CONTRA del lado del precio (precio arriba y promedio
            # bajando, o al revés). Si van juntos no agrega nada y alargaba 4 de 20 textos.
            + ("; ojo: el promedio mismo viene " + ("subiendo" if pend >= 0 else "bajando") + " en el último mes"
               if pend is not None and abs(d) >= 2 and (pend >= 0) != (d >= 0) else ""))
    # Movimientos recientes (los de la estructura de Fibonacci). Si la ficha
    # mide el impulso de Elliott entero, el último tramo viene aparte: el
    # resumen cuenta los movimientos recientes, no el impulso (estructura.py).
    f = r.get("fibonacci") or {}
    f = f.get("tramo") or f
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
        # v10: si el precio ya salió de ese movimiento (lo deshizo entero o lo pasó), es
        # historia vieja: no va. Apple contaba una caída de julio ya recuperada (95 palabras).
        if q is not None and 0.12 <= q < 0.97:
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
            # v11: «esta bajada» confundía cuando el precio ya había vuelto casi arriba (Tesla).
            a0 = e["desde"]["precio"]
            q2 = (precio - b) / (a0 - b) if a0 != b else 0
            if q2 >= 0.25:
                txt += (f"; de esa {'bajada' if e['dir'] == 'bajada' else 'suba'} ya "
                        f"{'recuperó' if e['dir'] == 'bajada' else 'perdió'} {proporcion(q2)}")
        movs["el_movimiento_de_ahora"] = txt
        # Lo que se mira, dicho como POSIBILIDAD y no como certeza (Nico, 23/10:
        # «ahí se termina la bajada» sonaba seguro). La misma forma que la
        # tarjeta de Fibonacci de la ficha (utils/fibonacci.js), para que hablen
        # igual. Antes la clave se llamaba «que_terminaria_…» y el modelo lo
        # repetía: el nombre de la clave también es parte del pedido. Y sin «el
        # máximo que tocó el…, el último pico de esta bajada»: decía dos veces lo
        # mismo y 4 de 11 textos pasaban de 120 palabras.
        # Nico (30/10) pidió mejor redacción que «si cierra arriba de 4,06 dólares,
        # el último pico, del 6 de octubre: si pasa, podría ser…»: una sola
        # condición, el porqué entre paréntesis y «caída» como en el resto.
        s = e.get("se_rompe_si_cierra") or {}
        if "encima_de" in s:
            movs["lo_que_se_mira"] = (f"si cierra por encima de {plata(s['encima_de'], mon)} (el último pico, del "
                                      f"{fecha(s['fecha'], hoy)}), podría ser una señal de que la caída "
                                      f"está perdiendo fuerza")
        if "debajo_de" in s:
            movs["lo_que_se_mira"] = (f"si cierra por debajo de {plata(s['debajo_de'], mon)} (el último pozo, del "
                                      f"{fecha(s['fecha'], hoy)}), podría ser una señal de que la suba "
                                      f"está perdiendo fuerza")
    # (Con menos de un año de historia el titular sale de los tres meses: `a1` es
    # None y compararlo con 0 tiraba el pedido entero, 23/10.)
    # v14: el titular trae armado qué está haciendo AHORA si va en otra dirección que el
    # dato del titular (en v13 el modelo lo agregaba solo y repetía la oración 2).
    if tit and e:
        tdir = ("suba" if (en_max or cerca_max) else "bajada" if (en_min or cerca_min)
                else ("suba" if (a3 if ("pero" in tit or a1 is None) else a1) >= 0 else "bajada"))
        b_ = e["hasta"]["precio"]; a_ = e["desde"]["precio"]
        q2 = 0 if e["hasta"]["fecha"] == hoy else ((precio - b_) / (a_ - b_) if a_ != b_ else 0)
        if e["dir"] != tdir and q2 < 0.5 and "pero" not in tit:
            h["para_el_titular"] = (tit + f", pero desde el {fecha(e['desde']['fecha'], hoy)} viene "
                                    + ("subiendo" if e["dir"] == "suba" else "bajando"))
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
            # v14: el cruce va PRIMERO: es lo que matiza (en v13 Galicia decía «viene
            # perdiendo fuerza» y recién al final que había dejado de caer tan rápido).
            # v16: sólo el cruce (con la lectura de base al lado, el modelo se quedaba con
            # «viene perdiendo fuerza» y tiraba lo nuevo: Galicia, v15).
            lect = (f"hace {c['hace']} días de mercado salió de abajo de 30, o sea que dejó de caer tan rápido"
                    if c["tipo"] == "salio_de_abajo" else
                    f"hace {c['hace']} días de mercado bajó de 70, o sea que dejó de subir tan rápido")
        ind["fuerza_del_precio"] = f"{round(rsi)} ({lect})"
    a = l.get("adx")
    if a is not None:
        lect = "arriba de 23: la tendencia tiene fuerza" if a >= 23 else "abajo de 23: la tendencia es floja, sin fuerza"
        p = l.get("adx_pendiente")
        if p is not None and abs(p) >= 1:
            lect += "; viene creciendo" if p > 0 else "; viene aflojando"
        c = l.get("adx_cruce")
        if c:
            lect += (f"; hace {c['hace']} días de mercado pasó arriba de 23" if c["tipo"] == "paso_arriba"
                     else f"; hace {c['hace']} días de mercado bajó de 23")
        ind["fuerza_de_la_tendencia"] = f"{round(a)} ({lect}; no dice para dónde va)"
    col = l.get("squeeze_color")
    if col:
        ind["empuje_de_los_ultimos_dias"] = {
            "verde_fuerte": "verde y creciendo: empuja para arriba cada vez más",
            "verde_apagado": "verde pero achicándose: empuja para arriba cada vez menos",
            "rojo_fuerte": "rojo y creciendo: empuja para abajo cada vez más",
            "rojo_apagado": "rojo pero achicándose: empuja para abajo cada vez menos",
        }.get(col, col)
    v = l.get("volumen_vs_promedio")
    if v and (v >= 1.5 or v <= 0.5):
        ind["cantidad_negociada"] = (f"el último día se negoció {num(v)} veces lo normal de las últimas 4 semanas" if v >= 1.5
                                     else "el último día se negoció menos de la mitad de lo normal de las últimas 4 semanas")
    # v13: va UN indicador y sólo si matiza la historia, elegido por regla (en v12 el
    # modelo ponía «la fuerza de la tendencia… no hay rumbo firme» en 11 de 20 textos,
    # varias veces justo después de «de fondo no hay rumbo claro»). Prioridad:
    # 1) fuerza del precio en un extremo o recién salida de uno; 2) el empuje de los
    # últimos días en contra del movimiento de ahora; 3) la fuerza de la tendencia
    # recién cruzando 23. Si ninguno, no hay oración de indicador.
    mov_dir = (e or {}).get("dir")
    sq_arriba = (col or "").startswith("verde")
    # v18: la lectura combinada ADX + Squeeze (como Jaime Merino, pedido de Nico) va
    # PRIMERO cuando cuenta un hecho: tomó fuerza, se está cansando o se quedó sin
    # fuerza (con el día en que cambió el empuje, que es el momento que él mira).
    fz = fuerza(r)
    elegido = None
    if fz and fz[1]:
        elegido = "fuerza_del_movimiento"
        ind[elegido] = fz[0][0].upper() + fz[0][1:]
    elif rsi is not None and (rsi >= 70 or rsi <= 30 or l.get("rsi_cruce")):
        elegido = "fuerza_del_precio"
    elif col and mov_dir and sq_arriba != (mov_dir == "suba"):
        elegido = "empuje_de_los_ultimos_dias"
    if elegido and elegido in ind:
        h["indicador_que_suma"] = {elegido: ind[elegido]}
    if todos_los_indicadores and ind:
        h["todos_los_indicadores"] = ind
    return h


def _lado(sq):
    return "suba" if sq > 0 else "bajada"


def fuerza(ficha):
    """La fuerza del movimiento leída como Jaime Merino: ADX (cuánta fuerza, si crece o se
    cansa) + Squeeze (para dónde empuja), en UNA frase. Devuelve (frase, cuenta_algo):
    `cuenta_algo` es True cuando hay un hecho (tomó fuerza, se está cansando, se quedó sin
    fuerza); False cuando sólo describe. Nunca como señal: describe lo que pasó.

    De QUÉ movimiento habla el ADX lo dicen sus dos líneas (+DI / −DI), no el Squeeze: Nike
    (21/10) tenía el ADX en 25 bajando y el Squeeze verde, y «la suba todavía es firme pero
    se está cansando» era falso: la suba tenía 2 semanas y lo que se apagaba era la bajada
    de meses. Si el lado que manda cambió hace menos de 10 días de mercado, el ADX todavía
    describe el movimiento anterior y no se cuenta como hecho."""
    import tecnico
    l, pts = ficha["lectura"], ficha["puntos"]
    hoy = l["fecha"]
    el = lambda hace: "el " + fecha(pts[-1 - hace]["d"], hoy)
    a, pend, sq = l.get("adx"), l.get("adx_pendiente"), l.get("squeeze")
    color, cruce = l.get("squeeze_color") or "", l.get("adx_cruce")
    if a is None or sq is None:
        return None
    dmi = tecnico.adx([{"open": x.get("o"), "high": x.get("h"), "low": x.get("l"), "close": x["c"]} for x in pts])
    dm, dn = dmi["di_mas"], dmi["di_menos"]
    if dm[-1] is None or dn[-1] is None:
        return None
    arriba = lambda i: dm[i] > dn[i]
    lado = "suba" if arriba(-1) else "bajada"
    dias_lado = 0
    while dias_lado < len(dm) - 1 and dm[-1 - dias_lado] is not None and arriba(-1 - dias_lado) == arriba(-1):
        dias_lado += 1
    n = round(a)
    sube, baja = (pend or 0) >= 1, (pend or 0) <= -1
    sqs = [x.get("squeeze") for x in pts if x.get("squeeze") is not None]
    giro = next((k for k in range(1, min(len(sqs), 15)) if (sqs[-k - 1] > 0) != (sqs[-1] > 0)), None)
    para = "para arriba" if sq > 0 else "para abajo"
    # Las palabras de Nico (30/10): «la caída tiene fuerza aún», «pero está bajando
    # la fuerza», no «la bajada todavía es firme, pero se está cansando». El 23 se
    # explica una vez, en la misma oración.
    mov = lambda x: "caída" if x == "bajada" else "suba"
    LINEA = "la línea que separa una tendencia con fuerza de una floja"
    if cruce and cruce["tipo"] == "paso_abajo":
        i = -1 - cruce["hace"]
        antes = "suba" if arriba(i) else "bajada"
        sq_antes = sqs[i] if cruce["hace"] < len(sqs) else sq
        # Se nombra el movimiento sólo si las líneas del ADX y el empuje coinciden ese día
        # (Pampa en pesos, 8/10: el ADX decía suba y el empuje bajada).
        quien = (f"la {mov(antes)} se quedó sin fuerza" if (antes == "suba") == (sq_antes > 0)
                 else "el precio se quedó sin una tendencia con fuerza")
        txt = f"{quien}: {el(cruce['hace'])} la fuerza de la tendencia bajó de 23, {LINEA}"
        if giro is not None and (sq_antes > 0) != (sq > 0):
            # v18: el segundo día sin el mes si es el mismo.
            d1, d2 = pts[-1 - cruce["hace"]]["d"], pts[-giro]["d"]
            dia2 = f"el {int(d2[8:])}" if d1[:7] == d2[:7] else el(giro - 1)
            # v20: «el empuje de los últimos días» completo: el juez marcó que «el
            # empuje» a secas no se entiende (v19 perdió 10 de 10 contra la frase larga).
            txt += f"; y {dia2}, el empuje de los últimos días cambió {para}"
        else:
            txt += f", y el empuje {para} se achica" if "apagado" in color else f", aunque el empuje sigue {para}"
        return txt, True
    if cruce and cruce["tipo"] == "paso_arriba" and sube and (sq > 0) == (lado == "suba"):
        return (f"la {mov(lado)} tomó fuerza: {el(cruce['hace'])} la fuerza de la tendencia pasó de 23, {LINEA}, "
                f"y sigue creciendo; el empuje de los últimos días es {para}"), True
    if n >= 23 and baja and dias_lado >= 10:
        return (f"la {mov(lado)} tiene fuerza aún (la fuerza de la tendencia está en {n}, arriba de 23), pero esa "
                f"fuerza viene bajando" + (" y el empuje se achica" if "apagado" in color else "")), True
    if n >= 23 and dias_lado >= 10:
        return (f"la {mov(lado)} tiene fuerza (la fuerza de la tendencia está en {n}, arriba de 23)"
                + (" y sigue ganando" if sube and "fuerte" in color else
                   ", aunque el empuje de los últimos días se achica" if "apagado" in color else "")), False
    if n >= 23:
        return None  # con fuerza, pero el lado que manda cambió hace poco: no se sabe de qué movimiento habla
    return (f"la tendencia es floja, sin fuerza (la fuerza de la tendencia está en {n}, abajo de 23); "
            f"el empuje de los últimos días es {para}" + (", cada vez más" if "fuerte" in color else ", cada vez menos")), False


def _hay_con_que(ficha: dict) -> bool:
    return bool(ficha and ficha.get("disponible") and len(ficha.get("puntos") or []) >= 30
                and (ficha.get("lectura") or {}).get("fecha"))


def para_el_resumen(ficha: dict, nombre: str):
    """Los hechos del resumen, o None si la ficha no tiene con qué contar."""
    return hechos(nombre, ficha) if _hay_con_que(ficha) else None


def para_el_chat(ficha: dict, nombre: str):
    """Los MISMOS hechos para el chat de Mervall-E (ai/lectura_tecnica_chat.py),
    más todos los indicadores leídos. Mismos números que la ficha y el resumen:
    salen de la misma respuesta de `tecnico.para_la_ficha` y de esta función."""
    return hechos(nombre, ficha, todos_los_indicadores=True) if _hay_con_que(ficha) else None
