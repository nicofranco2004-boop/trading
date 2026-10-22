"""Estructura del mercado en velas diarias y el Fibonacci del último tramo.

QUÉ ES. La regla que describió Nico (2026-10-22), escrita para que una
computadora la siga sin adivinar:

  1. PICOS Y POZOS ("pivotes"). Un día es PICO si su máximo supera los máximos
     de los `N` días anteriores y no lo supera ninguno de los `N` posteriores.
     POZO, lo mismo con los mínimos. Por eso un pivote recién se CONFIRMA `N`
     días después: hasta que no pasan esos días no se sabe si alguno lo supera.

  2. TRAMO DE SUBA: el precio hace picos cada vez más altos y, entre pico y
     pico, pozos cada vez más altos. El "último pozo más alto" es el pozo que
     dejó el precio antes de su último pico más alto: mientras ninguna vela
     CIERRE por debajo de él, la suba sigue viva (puede haber un pico más bajo
     en el medio; eso solo no rompe nada).
     RUPTURA: el día que una vela cierra por debajo de ese pozo, se confirma
     que el pico más alto fue el final de la suba. El tramo va del POZO DE
     ARRANQUE (el mínimo desde donde empezó) a ese PICO.
     TRAMO DE BAJADA: exactamente al revés (techos cada vez más bajos; la
     ruptura es un cierre por ENCIMA del último techo más bajo).

  3. Al romperse un tramo empieza el contrario, desde el extremo del que se
     rompió: después de una suba rota, se mide una bajada desde su pico. Así la
     lectura no depende de dónde empieza la historia guardada (salvo el primer
     tramo, que se descarta).

  4. FIBONACCI del último tramo CONFIRMADO: los niveles 0,236 · 0,382 · 0,5 ·
     0,618 · 0,786 entre su pozo de arranque y su pico, cuánto devolvió el
     precio de ese tramo hoy (con el cierre) y lo más que llegó a devolver.

QUÉ NO HACE. No recomienda nada: describe dónde está el precio contra el
último movimiento. Tampoco mira al usuario ni la moneda: recibe velas.

POR QUÉ N = 3. Medido el 2026-10-22 con 3 años de velas reales de 12 activos
(AAPL, MSFT, SPY, NVDA, TSLA, KO, MELI, GGAL.BA, YPFD.BA, PAMP.BA, BTC-USD,
ETH-USD), mediana de los 12:
      N   ruedas entre picos   tramos en 3 años   ruedas por tramo   ruptura, ruedas después del final
      2          7,5                 32                 20                    7
      3         10,5                 22                 25                   11,5
      4         13,5                 15                 34,5                 14
      5         16,5                 13                 34,5                 16,5
  · N = 2 confunde el ruido de una semana con estructura (un pico cada
    semana y media).
  · N = 3 deja tramos de ~5 semanas, los que se ven a ojo en un gráfico
    diario de 1 año, y avisa la ruptura ~2 semanas después del pico.
  · N = 5 tarda una semana entera en confirmar cada pivote: la ruptura llega
    una semana más tarde y se pierden los retrocesos cortos.
"""
from __future__ import annotations

# Días de cada lado para que un día sea pico o pozo (ver arriba por qué 3).
N_PIVOTE = 3
# Los niveles de Fibonacci que se dibujan (0 y 1 son los extremos del tramo).
NIVELES = (0.236, 0.382, 0.5, 0.618, 0.786)
# Un tramo que mide menos que esto, en "rangos diarios típicos" (el promedio
# de máximo − mínimo de las 14 ruedas anteriores a su final), es ruido de
# pocos días y no se mide. Ver `_es_claro`.
MIN_RANGOS_TRAMO = 4.0
# Un tramo que terminó hace más que esto (en ruedas, ~1 año) ya no describe
# cómo se mueve el precio hoy: 'tramo_viejo' en vez de medir uno viejo.
MAX_RUEDAS_DESDE_EL_FINAL = 252
# Menos ruedas que esto no alcanza para hablar de estructura.
MIN_RUEDAS = 30


def _alto(v: dict) -> float:
    """El máximo de la vela. Una vela rota (sin máximo guardado, ver
    `velas_diarias._velas_de`) usa lo que sí tiene: apertura y cierre."""
    if v.get("high") is not None:
        return v["high"]
    return max(x for x in (v.get("open"), v["close"]) if x is not None)


def _bajo(v: dict) -> float:
    if v.get("low") is not None:
        return v["low"]
    return min(x for x in (v.get("open"), v["close"]) if x is not None)


def pivotes(velas: list, n: int = N_PIVOTE) -> list:
    """Los picos y pozos: [{'i', 'tipo': 'pico'|'pozo', 'precio', 'confirmado': i + n}].
    Un día es pico si su máximo es MAYOR que el de los `n` anteriores y
    MAYOR O IGUAL que el de los `n` posteriores (dos días con el mismo máximo:
    el pico es el primero). Los últimos `n` días todavía no pueden serlo."""
    altos = [_alto(v) for v in velas]
    bajos = [_bajo(v) for v in velas]
    out = []
    for i in range(n, len(velas) - n):
        h, l = altos[i], bajos[i]
        if h > max(altos[i - n:i]) and h >= max(altos[i + 1:i + n + 1]):
            out.append({"i": i, "tipo": "pico", "precio": h, "confirmado": i + n})
        if l < min(bajos[i - n:i]) and l <= min(bajos[i + 1:i + n + 1]):
            out.append({"i": i, "tipo": "pozo", "precio": l, "confirmado": i + n})
    return out


def _rango_tipico(velas: list, i: int, ruedas: int = 14) -> float:
    """El promedio de (máximo − mínimo) de las `ruedas` anteriores a `i`."""
    tramo = velas[max(0, i - ruedas + 1):i + 1]
    rangos = [_alto(v) - _bajo(v) for v in tramo]
    return sum(rangos) / len(rangos) if rangos else 0.0


def tramos(velas: list, n: int = N_PIVOTE) -> dict:
    """Recorre las velas día por día, viendo sólo lo que se sabía ese día
    (un pivote entra recién cuando se confirma), y devuelve:
      · 'confirmados': los tramos terminados, del más viejo al más nuevo;
      · 'en_curso': el que está vivo hoy, con el nivel que lo rompería.
    Cada tramo: {'dir': 'suba'|'bajada', 'inicio': i, 'fin': i, 'ruptura': i,
    'protegido': i del pozo/techo que se rompió, 'primero': bool}."""
    piv = sorted(pivotes(velas, n), key=lambda p: (p["confirmado"], p["i"]))
    altos = [_alto(v) for v in velas]
    bajos = [_bajo(v) for v in velas]
    cierres = [v["close"] for v in velas]

    confirmados = []
    estado = None
    ult_pico = ult_pozo = None   # el último pico/pozo confirmado (para arrancar)
    k = 0
    for i in range(len(velas)):
        # 1. Los pivotes que se confirman hoy.
        while k < len(piv) and piv[k]["confirmado"] <= i:
            p = piv[k]
            k += 1
            if p["tipo"] == "pico":
                ult_pico = p["i"]
            else:
                ult_pozo = p["i"]
            if estado is not None and p["i"] > estado["inicio"]:
                _aplicar(estado, p, altos, bajos, cierres, i)

        # 2. El extremo del tramo vivo (el máximo de una suba, el mínimo de una bajada).
        if estado is not None:
            if estado["dir"] == "suba" and altos[i] > altos[estado["extremo"]]:
                estado["extremo"] = i
            if estado["dir"] == "bajada" and bajos[i] < bajos[estado["extremo"]]:
                estado["extremo"] = i

        # 3. ¿Hoy se rompió?
        c = cierres[i]
        if estado is None:
            # Para arrancar: el primer cierre que pasa un pico o un pozo confirmado.
            # Este primer tramo no se informa: empezó antes de la historia guardada.
            if ult_pico is not None and c > altos[ult_pico]:
                ini = min(range(ult_pico, i + 1), key=lambda j: bajos[j])
                estado = _nuevo("suba", ini, i, piv, altos, bajos, cierres, primero=True)
            elif ult_pozo is not None and c < bajos[ult_pozo]:
                ini = max(range(ult_pozo, i + 1), key=lambda j: altos[j])
                estado = _nuevo("bajada", ini, i, piv, altos, bajos, cierres, primero=True)
            continue
        if estado["dir"] == "suba" and c < bajos[estado["protegido"]]:
            confirmados.append(_cerrar(estado, i))
            estado = _nuevo("bajada", estado["extremo"], i, piv, altos, bajos, cierres)
        elif estado["dir"] == "bajada" and c > altos[estado["protegido"]]:
            confirmados.append(_cerrar(estado, i))
            estado = _nuevo("suba", estado["extremo"], i, piv, altos, bajos, cierres)

    en_curso = None
    if estado is not None:
        en_curso = {"dir": estado["dir"], "inicio": estado["inicio"], "fin": estado["extremo"],
                    "protegido": estado["protegido"]}
    return {"confirmados": confirmados, "en_curso": en_curso}


def _aplicar(estado: dict, p: dict, altos: list, bajos: list, cierres: list, hoy: int) -> None:
    """Un pivote confirmado dentro del tramo vivo. En una suba:
      · un POZO es candidato a "pozo más alto": el más bajo desde el pico más
        alto del tramo ("pendiente");
      · el PICO siguiente decide. Si es MÁS ALTO que todos los del tramo, la
        suba sigue y el pozo que dejó antes pasa a ser el que hay que defender
        ("protegido"). Si NO lo supera ("ya no puede superar el máximo más
        alto"), el pozo también pasa a ser el que hay que defender: si un
        cierre lo rompe, el pico más alto fue el final.
      · el primer pico del tramo no protege nada todavía: un pozo es "más
        alto" recién cuando queda entre dos picos.
      · un pozo que algún cierre ya perforó (entre su día y `hoy`) no pasa a
        defenderse: como el pico se confirma 3 ruedas después, el precio pudo
        haberlo cerrado por debajo antes de que se sepa. Decir "se termina si
        cierra debajo de X" cuando ya cerró debajo sería falso; queda el que
        se defendía antes.
    En una bajada, al revés."""
    suba = estado["dir"] == "suba"
    if p["tipo"] == ("pozo" if suba else "pico"):
        pend = estado["pendiente"]
        if pend is None or (bajos[p["i"]] < bajos[pend] if suba else altos[p["i"]] > altos[pend]):
            estado["pendiente"] = p["i"]
        return
    previo = estado["previo"]
    if previo is None:
        estado["previo"], estado["pendiente"] = p["i"], None
        return
    mas_extremo = altos[p["i"]] > altos[previo] if suba else bajos[p["i"]] < bajos[previo]
    cand = estado["pendiente"]
    if cand is not None and _en_pie(cand, suba, altos, bajos, cierres, hoy):
        estado["protegido"] = cand
    if mas_extremo:
        estado["previo"], estado["pendiente"] = p["i"], None


def _en_pie(j: int, suba: bool, altos: list, bajos: list, cierres: list, hoy: int) -> bool:
    """¿Ningún cierre desde el día `j` hasta `hoy` pasó el pozo (o techo) de `j`?"""
    tramo = cierres[j:hoy + 1]
    return min(tramo) >= bajos[j] if suba else max(tramo) <= altos[j]


def _nuevo(direccion: str, inicio: int, hoy: int, piv: list, altos: list, bajos: list,
           cierres: list, primero: bool = False) -> dict:
    """Un tramo que arranca en `inicio` (el extremo del que se rompió). Hasta que
    haga su segundo pico más alto con un pozo en el medio, lo que defiende es su
    propio arranque. Los pivotes que ya se confirmaron entre el arranque y hoy
    se le aplican en orden: el tramo nuevo nace sabiendo lo que pasó, y con los
    cierres hasta hoy (un pozo que ya se perforó no se defiende)."""
    serie = altos if direccion == "suba" else bajos
    rango = range(inicio, hoy + 1)
    extremo = (max(rango, key=lambda j: serie[j]) if direccion == "suba"
               else min(rango, key=lambda j: serie[j]))
    estado = {"dir": direccion, "inicio": inicio, "extremo": extremo, "protegido": inicio,
              "pendiente": None, "previo": None, "primero": primero}
    for p in piv:
        if p["confirmado"] <= hoy and p["i"] > inicio:
            _aplicar(estado, p, altos, bajos, cierres, hoy)
    return estado


def _cerrar(estado: dict, hoy: int) -> dict:
    return {"dir": estado["dir"], "inicio": estado["inicio"], "fin": estado["extremo"],
            "ruptura": hoy, "protegido": estado["protegido"], "primero": estado["primero"]}


def _es_claro(velas: list, t: dict) -> bool:
    """¿Es un movimiento de verdad o ruido? Mide al menos `MIN_RANGOS_TRAMO`
    veces lo que se mueve el precio en un día típico. En un activo lateral los
    tramos que salen son del tamaño de unas pocas velas y no pasan."""
    alto = _alto(velas[t["fin"]]) if t["dir"] == "suba" else _alto(velas[t["inicio"]])
    bajo = _bajo(velas[t["inicio"]]) if t["dir"] == "suba" else _bajo(velas[t["fin"]])
    rango = _rango_tipico(velas, t["fin"])
    return rango > 0 and (alto - bajo) >= MIN_RANGOS_TRAMO * rango


def fibonacci(velas: list, n: int = N_PIVOTE) -> dict:
    """El Fibonacci del último tramo confirmado, listo para la ficha.

    {'disponible': False, 'motivo': 'pocos_datos'|'sin_tramo_terminado'|'tramos_chicos'|
     'tramo_viejo'|'superado',
     'en_curso': {...}} o
    {'disponible': True, 'dir', 'desde': {fecha, precio}, 'hasta': {fecha, precio},
     'ruptura': {fecha, cierre, nivel}, 'niveles': [{nivel, precio}],
     'retroceso_hoy', 'retroceso_maximo': {valor, precio, fecha}, 'entre': [a, b],
     'en_curso': {...} | None, 'n_pivote', 'tramos': [...]}

    El retroceso es la parte del tramo que el precio devolvió: 0 = sigue en el
    final del tramo, 0,5 = devolvió la mitad, 1 = volvió al arranque. Si hoy
    está fuera de 0 a 1 (pasó el arranque, o hizo un extremo nuevo), el tramo
    quedó 'superado': sus niveles quedaron lejos y no se miden; se devuelve el
    tramo vivo ('en_curso') para contarlo. 'retroceso_maximo' sí puede pasar
    de 1: es lo más lejos que llegó desde el final del tramo."""
    velas = [v for v in velas if v.get("close") is not None and v["close"] > 0]
    if len(velas) < MIN_RUEDAS:
        return {"disponible": False, "motivo": "pocos_datos", "ruedas": len(velas), "n_pivote": n}
    res = tramos(velas, n)
    hoy = len(velas) - 1
    terminados = [t for t in res["confirmados"] if not t["primero"]]
    validos = [t for t in terminados if _es_claro(velas, t)]
    lista = [_tramo_para_afuera(velas, t) for t in validos[-4:]]
    en_curso = _en_curso_para_afuera(velas, res["en_curso"])
    base = {"disponible": False, "ruedas": len(velas), "n_pivote": n, "tramos": lista,
            "en_curso": en_curso}
    # Tres motivos distintos para no medir, y la pantalla dice cada uno:
    #   · ningún tramo terminó todavía (una suba que viene de lejos y nunca se rompió);
    #   · terminaron, pero todos del tamaño de unas pocas velas (un activo lateral);
    #   · el último claro terminó hace más de un año.
    if not terminados:
        return {**base, "motivo": "sin_tramo_terminado"}
    if not validos:
        return {**base, "motivo": "tramos_chicos"}
    if hoy - validos[-1]["fin"] > MAX_RUEDAS_DESDE_EL_FINAL:
        return {**base, "motivo": "tramo_viejo", "viejo": lista[-1]}

    t = validos[-1]
    suba = t["dir"] == "suba"
    ini, fin = velas[t["inicio"]], velas[t["fin"]]
    p0 = _bajo(ini) if suba else _alto(ini)        # el arranque
    p1 = _alto(fin) if suba else _bajo(fin)        # el final
    alto, bajo = max(p0, p1), min(p0, p1)
    amplitud = alto - bajo

    def retroceso(precio):
        # Cuánto del tramo devolvió: desde el final hacia el arranque.
        return (p1 - precio) / (p1 - p0)

    # Lo más que devolvió desde el final del tramo hasta hoy: el mínimo (de una
    # suba) o el máximo (de una bajada) de esas velas.
    despues = range(t["fin"] + 1, hoy + 1)
    if despues:
        j = (min(despues, key=lambda x: _bajo(velas[x])) if suba
             else max(despues, key=lambda x: _alto(velas[x])))
        extremo = _bajo(velas[j]) if suba else _alto(velas[j])
        r_max = {"valor": _r(retroceso(extremo)), "precio": _r(extremo), "fecha": velas[j]["date"]}
    else:
        r_max = None
    r_hoy = retroceso(velas[hoy]["close"])
    if not 0.0 <= r_hoy <= 1.0:
        # El precio ya salió del tramo: pasó el arranque de la última bajada (o
        # de la última suba) o hizo un extremo nuevo. Sus niveles quedaron
        # lejos y no describen nada: lo que importa es el tramo que está vivo.
        return {**base, "motivo": "superado", "superado": lista[-1], "precio_hoy": _r(velas[hoy]["close"])}
    marcas = (0.0,) + NIVELES + (1.0,)
    entre = None
    for a, b in zip(marcas, marcas[1:]):
        if a <= r_hoy <= b:
            entre = [a, b]
            break
    rup = velas[t["ruptura"]]
    return {
        "disponible": True,
        "n_pivote": n,
        "dir": t["dir"],
        "desde": {"fecha": ini["date"], "precio": _r(p0)},
        "hasta": {"fecha": fin["date"], "precio": _r(p1)},
        "ruptura": {"fecha": rup["date"], "cierre": _r(rup["close"]),
                    "nivel": _r(_bajo(velas[t["protegido"]]) if suba else _alto(velas[t["protegido"]])),
                    "nivel_fecha": velas[t["protegido"]]["date"]},
        "niveles": [{"nivel": r, "precio": _r(p1 - r * (p1 - p0))} for r in NIVELES],
        "amplitud_pct": _r((amplitud / bajo) * 100.0, 2) if bajo > 0 else None,
        "retroceso_hoy": _r(r_hoy),
        "retroceso_maximo": r_max,
        "entre": entre,
        "precio_hoy": _r(velas[hoy]["close"]),
        "fecha_hoy": velas[hoy]["date"],
        "en_curso": en_curso,
        "tramos": lista,
    }


def _tramo_para_afuera(velas: list, t: dict) -> dict:
    suba = t["dir"] == "suba"
    ini, fin = velas[t["inicio"]], velas[t["fin"]]
    return {
        "dir": t["dir"],
        "desde": {"fecha": ini["date"], "precio": _r(_bajo(ini) if suba else _alto(ini))},
        "hasta": {"fecha": fin["date"], "precio": _r(_alto(fin) if suba else _bajo(fin))},
        "ruptura": {"fecha": velas[t["ruptura"]]["date"], "cierre": _r(velas[t["ruptura"]]["close"])},
    }


def _en_curso_para_afuera(velas: list, t: dict):
    """El tramo vivo: desde dónde arrancó, su extremo hasta hoy y qué cierre lo
    rompería (el último pozo más alto de una suba, o techo más bajo de una bajada)."""
    if not t:
        return None
    suba = t["dir"] == "suba"
    ini, fin, pro = velas[t["inicio"]], velas[t["fin"]], velas[t["protegido"]]
    return {
        "dir": t["dir"],
        "desde": {"fecha": ini["date"], "precio": _r(_bajo(ini) if suba else _alto(ini))},
        "hasta": {"fecha": fin["date"], "precio": _r(_alto(fin) if suba else _bajo(fin))},
        "se_rompe_si_cierra": {"debajo_de" if suba else "encima_de": _r(_bajo(pro) if suba else _alto(pro)),
                               "fecha": pro["date"]},
    }


def _r(x, d=4):
    return round(x, d) if x is not None else None
