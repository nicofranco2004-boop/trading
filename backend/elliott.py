"""Ondas de Elliott: un conteo POSIBLE sobre los picos y pozos de la estructura.

QUÉ ES. La teoría de Elliott dice que el precio avanza en 5 ondas (1, 3 y 5 a
favor; 2 y 4 de descanso) y corrige en 3 (A, B y C). Contar ondas es
subjetivo: dos personas pueden contar distinto el mismo gráfico. Por eso esto
devuelve UN conteo posible (el que mejor cumple las proporciones habituales),
cuánta confianza merece en palabras, el precio que lo invalida y, si hay, otro
conteo distinto que también cumple las reglas.

SOBRE QUÉ PUNTOS. Los MISMOS picos y pozos que usa el Fibonacci
(`estructura.pivotes`, N = 3 velas a cada lado): no hay otro detector. Se
ordenan en una línea que alterna pico y pozo (dos picos seguidos sin pozo en el
medio: queda el más alto). Una onda puede saltear picos y pozos chicos de
adentro (una onda 3 tiene sus propios descansos), pero cada punto contado tiene
que ser el EXTREMO de las dos ondas que toca: el final de la onda 1 es el
máximo entre el arranque de la 1 y el final de la 2, y así. El último punto
contado, además, es el extremo desde ahí hasta hoy.

REGLAS DURAS (si una no se cumple, ese conteo no existe):
  · la onda 2 no baja más que el arranque de la 1;
  · la onda 3 pasa el final de la 1 y no es la más corta de 1, 3 y 5;
  · la onda 4 no se mete en el terreno de la 1 (no baja del final de la 1);
  · la onda 5 pasa el final de la 3. La teoría admite una 5 "truncada" que no
    llega, pero es rara, y con picos y pozos automáticos producía conteos
    forzados (TSLA, 22/10/26: una "5" en 342 con la 3 en 297): no se cuenta;
  · cada onda dura al menos `MIN_RUEDAS_ONDA` días de mercado (un pico y un
    pozo en días seguidos no son una onda: YPFD, una "onda 4" de un día);
  · en una corrección A-B-C, la B no pasa el arranque de la A y la C pasa el
    final de la A; y suelta (no pegada a un impulso) tiene que corregir algo:
    antes de una A-B-C a la baja hubo una suba al menos del tamaño de la A,
    que la corrección no borró entera.
  En una bajada, todo al revés.

PAUTAS (no excluyen; dan la confianza): onda 2 ≈ 50–61,8 % de la 1; onda 3 ≈
1,618 veces la 1; onda 4 ≈ 38,2 % de la 3; la 5 parecida a la 1; alternancia
entre 2 y 4 (una honda —50 % o más— y la otra no —38,2 % o menos—, o una el
triple de larga que la otra); en A-B-C, B ≈ 50–61,8 % de A y C ≈ A.

EL ALTERNATIVO tiene que decir otra cosa de hoy: estar en otra onda. "Onda 5"
contra "onda 5" con otro arranque es la misma lectura, y "en la B" contra "en
la corrección" con los mismos puntos también; no se ofrecen.

QUÉ ES "HOY". Un conteo puede estar terminado o a mitad: 1-2 contadas y la 3
en curso, 1-2-3 y la 4 en curso, etc. Lo que pasó desde el último punto
contado tiene que encajar con la onda que estaría en curso (no puede haber
pasado el nivel que invalida). Un conteo cuyo último punto quedó lejos (más
tiempo desde ahí que lo que duró todo lo contado, o más de un año) ya no
describe el presente y no se ofrece.

NO MIRA EL FUTURO. Un pico o pozo entra recién cuando se confirma (N ruedas
después), y el conteo de un día usa sólo las velas hasta ese día.

QUÉ NO HACE. No recomienda ni dice qué va a pasar: las palabras las pone la
pantalla (utils/elliott.js) y siempre como "un conteo posible".
"""
from __future__ import annotations

import math
from datetime import date

import estructura

# Cuántos picos y pozos (los últimos) se miran para buscar el conteo.
MAX_PUNTOS = 26
# Una onda principal (1, 3, 5, A, C) mide al menos esto en rangos diarios
# típicos, y todo lo contado al menos `MIN_RANGOS_TOTAL` (como el Fibonacci).
MIN_RANGOS_ONDA = 1.5
MIN_RANGOS_TOTAL = estructura.MIN_RANGOS_TRAMO
# Más de esto desde el último punto contado y el conteo ya no es "de hoy".
MAX_DIAS_DESDE_EL_ULTIMO = 365

# Las pautas: (desde, hasta) del cociente. Un poco de aire alrededor del número
# de libro: nadie espera un 61,8 % exacto.
P_ONDA2 = (0.40, 0.72)          # retroceso de la 2 sobre la 1 (≈ 50–61,8 %)
P_ONDA3 = (1.38, 1.90)          # la 3 contra la 1 (≈ 1,618)
P_ONDA4 = (0.24, 0.50)          # retroceso de la 4 sobre la 3 (≈ 38,2 %)
P_ONDA5 = (0.75, 1.33)          # la 5 contra la 1 (≈ igual)
P_ONDA_B = (0.40, 0.79)         # retroceso de la B sobre la A (≈ 50–61,8 %)
P_ONDA_C = (0.75, 1.33)         # la C contra la A (≈ igual)
# Alternancia: una de las dos correcciones (2 y 4) es honda (devuelve 50 % o
# más) y la otra no (alrededor de 38,2 % o menos), o una dura al menos el triple que la
# otra. Más floja (cualquier diferencia, o el doble) se cumplía en casi todos
# los conteos reales (22/10/26) y sólo inflaba la confianza.
HONDA = 0.5
PLAYA = 0.40           # ≈ 38,2 %, con el mismo aire que las otras pautas
VECES_MAS_LARGA = 3.0
# Una onda dura al menos esto en días de mercado (lo que tarda en confirmarse
# un pico o pozo).
MIN_RUEDAS_ONDA = estructura.N_PIVOTE

ORDEN_CONFIANZA = {"alta": 2, "media": 1, "baja": 0}


def _zigzag(velas: list, n: int) -> list:
    """Los pivotes de `estructura.pivotes`, alternando pico y pozo:
    [{'i', 'tipo', 'precio'}]. Dos del mismo tipo seguidos: queda el más
    extremo. Un día que es pico y pozo a la vez (una vela enorme) entra con el
    tipo que alterna con el anterior; el otro se descarta."""
    piv = sorted(estructura.pivotes(velas, n), key=lambda p: p["i"])
    # Un día que es pico y pozo: queda el que alterna con el anterior (sin
    # anterior, el pico). Antes entraba siempre el pico, aunque el anterior
    # también lo fuera, y el pozo se perdía (auditoría 23/10).
    juntos = {}
    for p in piv:
        juntos.setdefault(p["i"], []).append(p)
    out = []
    for i in sorted(juntos):
        grupo = juntos[i]
        if len(grupo) > 1:
            quiero = "pozo" if out and out[-1]["tipo"] == "pico" else "pico"
            grupo = [g for g in grupo if g["tipo"] == quiero]
        p = grupo[0]
        q = {"i": p["i"], "tipo": p["tipo"], "precio": p["precio"]}
        if out and out[-1]["tipo"] == q["tipo"]:
            mas = q["precio"] > out[-1]["precio"] if q["tipo"] == "pico" else q["precio"] < out[-1]["precio"]
            if mas:
                out[-1] = q
            continue
        out.append(q)
    return out


def _espejo(zz: list) -> list:
    """El zigzag dado vuelta (precios negativos, picos ↔ pozos): una bajada se
    cuenta con la misma cuenta que una suba."""
    return [{"i": p["i"], "tipo": "pozo" if p["tipo"] == "pico" else "pico", "precio": -p["precio"]} for p in zz]


class _Vista:
    """Máximos y mínimos de las velas (dados vuelta si es una bajada), con
    consultas de rango. `altos[i]` es "lo más a favor" del día i."""

    def __init__(self, velas: list, espejo: bool):
        a = [estructura._alto(v) for v in velas]
        b = [estructura._bajo(v) for v in velas]
        self.altos, self.bajos = ([-x for x in b], [-x for x in a]) if espejo else (a, b)
        self.hoy = len(velas) - 1

    def max_alto(self, i: int, j: int) -> float:
        return max(self.altos[i:j + 1])

    def min_bajo(self, i: int, j: int) -> float:
        return min(self.bajos[i:j + 1])


def _es_extremo(vista: _Vista, pts: list, k: int, hasta_hoy: bool = False) -> bool:
    """¿El punto k es el extremo de las dos ondas que toca? Un pico, el máximo
    entre el punto anterior y el siguiente (o hoy, si es el último); un pozo,
    el mínimo. El primero, sólo contra el siguiente."""
    p = pts[k]
    ini = pts[k - 1]["i"] if k > 0 else p["i"]
    fin = vista.hoy if hasta_hoy else pts[k + 1]["i"]
    if p["tipo"] == "pico":
        return vista.max_alto(ini, fin) <= p["precio"]
    return vista.min_bajo(ini, fin) >= p["precio"]


def _secuencias(zz: list, tipos: tuple, vista: _Vista):
    """Todas las secuencias de puntos del zigzag con esos tipos en orden, cada
    uno extremo de las ondas que toca (el último, hasta hoy). Búsqueda con
    poda: un punto que ya no es extremo contra el siguiente no se extiende."""
    out = []

    def seguir(pts, desde):
        if len(pts) == len(tipos):
            if _es_extremo(vista, pts, len(pts) - 1, hasta_hoy=True):
                out.append(list(pts))
            return
        for j in range(desde, len(zz)):
            q = zz[j]
            if q["tipo"] != tipos[len(pts)]:
                continue
            pts.append(q)
            # El anterior ya puede juzgarse: tiene a los dos vecinos.
            if len(pts) < 2 or _es_extremo(vista, pts, len(pts) - 2):
                seguir(pts, j + 1)
            pts.pop()

    for j0, q in enumerate(zz):
        if q["tipo"] == tipos[0]:
            seguir([q], j0 + 1)
    return out


def _dentro(x, rango) -> bool:
    return x is not None and rango[0] <= x <= rango[1]


def _impulsos(zz: list, vista: _Vista) -> list:
    """Los conteos de impulso (en la dirección "a favor" de esta vista): de
    0-1-2 (la 3 en curso) a 0-1-2-3-4-5 (terminado). Sólo los que cumplen las
    reglas duras con lo que ya pasó."""
    out = []
    for largo in (3, 4, 5, 6):
        tipos = tuple("pozo" if k % 2 == 0 else "pico" for k in range(largo))
        for pts in _secuencias(zz, tipos, vista):
            c = _impulso(pts, vista)
            if c:
                out.append(c)
    return out


def _impulso(pts: list, vista: _Vista):
    P = [p["precio"] for p in pts]
    I = [p["i"] for p in pts]
    hecho = len(pts) - 1                         # ondas terminadas
    w1 = P[1] - P[0]
    # Regla: la 2 no baja más que el arranque de la 1.
    if P[2] <= P[0]:
        return None
    if hecho >= 3:
        # Regla: la 3 pasa el final de la 1.
        if P[3] <= P[1]:
            return None
    if hecho >= 4:
        # Regla: la 4 no se mete en el terreno de la 1.
        if P[4] <= P[1]:
            return None
    w3 = P[3] - P[2] if hecho >= 3 else None
    if hecho == 5:
        w5 = P[5] - P[4]
        # Regla: la 3 no es la más corta.
        if w3 < w1 and w3 < w5:
            return None
        # Regla (ver arriba): la 5 pasa el final de la 3.
        if P[5] <= P[3]:
            return None
    # Lo que pasó desde el último punto tiene que encajar con la onda en curso.
    ultimo = I[-1]
    if hecho == 4:
        # En la 5: si la 3 fue más corta que la 1, la 5 no puede pasar a la 3.
        if w3 < w1 and vista.max_alto(ultimo, vista.hoy) - P[4] > w3:
            return None
    if hecho == 3:
        # En la 4: no puede haber bajado del final de la 1.
        if vista.min_bajo(ultimo, vista.hoy) <= P[1]:
            return None
    if hecho == 5:
        # Corrigiendo después de la 5: si devolvió TODO el impulso, no lo era.
        if vista.min_bajo(ultimo, vista.hoy) <= P[0]:
            return None

    pautas = []
    r2 = (P[1] - P[2]) / w1
    pautas.append({"id": "onda2", "valor": r2, "cumple": _dentro(r2, P_ONDA2)})
    if hecho >= 3:
        pautas.append({"id": "onda3", "valor": w3 / w1, "cumple": _dentro(w3 / w1, P_ONDA3)})
    if hecho >= 4:
        r4 = (P[3] - P[4]) / w3
        pautas.append({"id": "onda4", "valor": r4, "cumple": _dentro(r4, P_ONDA4)})
        d2, d4 = I[2] - I[1], I[4] - I[3]
        alterna = ((r2 >= HONDA and r4 <= PLAYA) or (r4 >= HONDA and r2 <= PLAYA)
                   or max(d2, d4) >= VECES_MAS_LARGA * max(1, min(d2, d4)))
        pautas.append({"id": "alternancia", "valor": None, "cumple": alterna})
    if hecho == 5:
        pautas.append({"id": "onda5", "valor": w5 / w1, "cumple": _dentro(w5 / w1, P_ONDA5)})

    ahora = {2: "onda_3", 3: "onda_4", 4: "onda_5", 5: "correccion"}[hecho]
    # El precio que invalida: el que rompería una regla dura.
    if hecho == 2:
        inval, por = P[0], "arranque_1"           # la 2 bajaría más que el arranque de la 1
    elif hecho in (3, 4):
        inval, por = P[1], "final_1"              # la 4 se metería en el terreno de la 1
    else:
        inval, por = P[5], "final_5"              # la 5 no habría terminado
    # El OTRO nivel que también lo corta, del otro lado (ver `_limites`):
    #   · en la 5 con una 3 más corta que la 1: la 5 no puede pasar el largo de la 3;
    #   · después de la 5: si devuelve todo el impulso, no lo era.
    otro = None
    if hecho == 4 and w3 < w1:
        otro = (P[4] + w3, "tope_3_corta", "encima")
    elif hecho == 5:
        otro = (P[0], "arranque_1", "debajo")
    ondas = [str(k) for k in range(len(pts))]
    return {"tipo": "impulso", "pts": pts, "ondas": ondas, "ahora": ahora, "pautas": pautas,
            "invalida": inval, "invalida_por": por, "invalida_lado": "encima" if hecho == 5 else "debajo",
            "otro": otro, "principales": [(0, 1), (2, 3), (4, 5)][:(hecho + 1) // 2]}


def _correcciones(zz: list, vista: _Vista, impulsos: list) -> list:
    """Las correcciones A-B-C "en contra" de esta vista (una suba en la vista
    dada vuelta es una bajada de verdad): sueltas, o pegadas a un impulso
    terminado (la A arranca en el final de su onda 5)."""
    sueltas = []
    for largo in (3, 4):
        # En la vista "a favor", una corrección arranca en un pico y baja.
        tipos = tuple("pico" if k % 2 == 0 else "pozo" for k in range(largo))
        for pts in _secuencias(zz, tipos, vista):
            c = _abc(pts, vista)
            if c:
                sueltas.append(c)
    pegadas = []
    for imp in impulsos:
        if imp["ahora"] != "correccion":
            continue
        p5 = imp["pts"][-1]
        # Pegada a un impulso, lo que corrige es el impulso (ya revisado).
        pegadas += [_pegar(imp, c) for c in sueltas if c["pts"][0]["i"] == p5["i"]]
        # La B en curso: sólo pegada a un impulso terminado (una A suelta no
        # es nada). La A, del final de la 5 al mínimo desde ahí hasta hoy.
        for pts in _secuencias([p for p in zz if p["i"] >= p5["i"]], ("pico", "pozo"), vista):
            if pts[0]["i"] == p5["i"]:
                b = {"tipo": "correccion", "pts": pts, "ondas": ["0", "A"], "ahora": "onda_B",
                     "pautas": [], "invalida": p5["precio"], "invalida_por": "arranque_A",
                     "invalida_lado": "encima", "otro": None, "principales": [(0, 1)]}
                pegadas.append(_pegar(imp, b))
    # Suelta, una A-B-C tiene que corregir algo (ver `_corrige_algo`).
    return [c for c in sueltas if _corrige_algo(c, vista)] + pegadas


def _corrige_algo(c: dict, vista: _Vista) -> bool:
    """Una corrección corrige un movimiento anterior en contra suyo: antes de
    una A-B-C a la baja tuvo que haber una suba. Se mira hacia atrás tanto
    como dura la corrección (al menos 20 ruedas): desde el mínimo de ahí hasta
    el arranque de la A, la suba tiene que medir al menos lo que la A, y la
    corrección no puede haberla borrado entera (eso ya es otra bajada)."""
    I = [p["i"] for p in c["pts"]]
    largo = max((I[-1] if len(I) == 4 else vista.hoy) - I[0], 20)
    desde = max(0, I[0] - largo)
    if desde >= I[0]:
        return False
    piso = vista.min_bajo(desde, I[0])
    P = [p["precio"] for p in c["pts"]]
    # Lo más bajo de la corrección: el final de la A y el de la C; con la C
    # en curso, lo que ya bajó desde la B hasta hoy (antes no se miraba y se
    # ofrecía "en la C" con la suba ya borrada entera: auditoría 23/10).
    hondo = min(P[1], P[3]) if len(P) == 4 else min(P[1], vista.min_bajo(I[2], vista.hoy))
    if not (P[0] - piso >= P[0] - P[1] and hondo > piso):
        return False
    if c["ahora"] == "onda_C":
        c["otro"] = (piso, "borro_lo_corregido", "debajo")
    return True


def _abc(pts: list, vista: _Vista):
    """A-B-C a la baja en la vista: arranque (pico) → A (pozo) → B (pico) → C (pozo)."""
    P = [p["precio"] for p in pts]
    I = [p["i"] for p in pts]
    hecho = len(pts) - 1
    a = P[0] - P[1]
    # Regla: la B no pasa el arranque de la A.
    if P[2] >= P[0]:
        return None
    if hecho == 3:
        # Regla: la C pasa el final de la A.
        if P[3] >= P[1]:
            return None
        # Terminada: si después volvió a pasar el arranque de la A, quedó vieja.
        if vista.max_alto(I[3], vista.hoy) >= P[0]:
            return None
    pautas = [{"id": "ondaB", "valor": (P[2] - P[1]) / a, "cumple": _dentro((P[2] - P[1]) / a, P_ONDA_B)}]
    if hecho == 3:
        c = P[2] - P[3]
        pautas.append({"id": "ondaC", "valor": c / a, "cumple": _dentro(c / a, P_ONDA_C)})
    return {"tipo": "correccion", "pts": pts, "ondas": ["0", "A", "B", "C"][:len(pts)],
            "ahora": "onda_C" if hecho == 2 else "fin_abc", "pautas": pautas,
            "invalida": P[0] if hecho == 2 else P[3],
            "invalida_por": "arranque_A" if hecho == 2 else "final_C",
            "invalida_lado": "encima" if hecho == 2 else "debajo",
            # Terminada, también deja de valer si vuelve a pasar el arranque de
            # la A (ya chequeado arriba con lo que pasó). En la C, el otro
            # límite lo pone `_corrige_algo` (suelta) o `_pegar` (pegada).
            "otro": (P[0], "arranque_A", "encima") if hecho == 3 else None,
            "principales": [(0, 1), (2, 3)][:(hecho + 1) // 2]}


def _pegar(imp: dict, abc: dict) -> dict:
    """Un impulso terminado y la corrección que le sigue, en un solo conteo."""
    corr = abc["ondas"][1:]                      # sin el "0"/"5" del arranque de la A
    # En la B y en la C, el conteo también cae si el precio devuelve todo el
    # impulso (ya chequeado con lo que pasó, en `_impulso`).
    otro = abc["otro"] if abc["ahora"] == "fin_abc" else (imp["pts"][0]["precio"], "arranque_1", "debajo")
    return {**abc, "tipo": "impulso_y_correccion", "pts": imp["pts"] + abc["pts"][1:], "otro": otro,
            "ondas": imp["ondas"] + corr, "pautas": imp["pautas"] + abc["pautas"],
            "principales": imp["principales"] + [(a + 5, b + 5) for a, b in abc["principales"]]}


def _duracion_ok(c: dict) -> bool:
    """Cada onda (de un punto contado al siguiente) dura al menos
    `MIN_RUEDAS_ONDA` días de mercado."""
    I = [p["i"] for p in c["pts"]]
    return all(b - a >= MIN_RUEDAS_ONDA for a, b in zip(I, I[1:]))


def _tamanio_ok(c: dict, velas: list) -> bool:
    """Las ondas principales y todo lo contado tienen que ser movimientos de
    verdad, no el ruido de pocos días (ver `estructura._es_claro`)."""
    pts = c["pts"]
    rango = estructura._rango_tipico(velas, pts[-1]["i"], 30)
    if rango <= 0:
        return False
    for a, b in c["principales"]:
        if b < len(pts) and abs(pts[b]["precio"] - pts[a]["precio"]) < MIN_RANGOS_ONDA * rango:
            return False
    precios = [p["precio"] for p in pts]
    return max(precios) - min(precios) >= MIN_RANGOS_TOTAL * rango


def _fresco(c: dict, velas: list) -> bool:
    """¿Describe el presente? Desde el último punto contado no pasó más tiempo
    que lo que duró todo lo contado, ni más de un año."""
    d = lambda i: date.fromisoformat(str(velas[i]["date"])[:10])
    hoy = len(velas) - 1
    ini, fin = c["pts"][0]["i"], c["pts"][-1]["i"]
    desde = (d(hoy) - d(fin)).days
    return desde <= MAX_DIAS_DESDE_EL_ULTIMO and desde <= max((d(fin) - d(ini)).days, 1)


def confianza(pautas: list) -> str:
    """Alta: cumple 3 de cada 4 pautas y hay al menos 3 para mirar. Media: la
    mitad (con al menos 2). Baja: el resto, o casi nada para mirar."""
    if not pautas:
        return "baja"
    si = sum(1 for p in pautas if p["cumple"])
    frac = si / len(pautas)
    if len(pautas) >= 3 and frac >= 0.75:
        return "alta"
    if len(pautas) >= 2 and frac >= 0.5:
        return "media"
    return "baja"


# El número "de libro" de cada pauta, para desempatar (ver `_desvio`).
IDEAL = {"onda2": 0.559, "onda3": 1.618, "onda4": 0.382, "onda5": 1.0, "ondaB": 0.559, "ondaC": 1.0}


def _desvio(c: dict) -> float:
    """Cuánto se alejan, en promedio, las proporciones del número de libro
    (en escala logarítmica: el doble y la mitad están igual de lejos)."""
    xs = [abs(math.log(p["valor"] / IDEAL[p["id"]])) for p in c["pautas"]
          if p["id"] in IDEAL and p["valor"] and p["valor"] > 0]
    return sum(xs) / len(xs) if xs else 1.0


def _clave(c: dict):
    """Orden de preferencia: más confianza, más ondas contadas (explica más),
    el último punto más reciente, la proporción de pautas que cumple y, al
    final, el más parecido al libro. Sin ese último desempate, BTC (22/10/26)
    elegía unas ondas 1 y 2 de 9 y 3 días al pie de la suba en vez de unas
    parejas, con la misma confianza."""
    si = sum(1 for p in c["pautas"] if p["cumple"])
    frac = si / len(c["pautas"]) if c["pautas"] else 0.0
    return (ORDEN_CONFIANZA[c["confianza"]], len(c["pts"]), c["pts"][-1]["i"], frac, -_desvio(c))


def candidatos(velas: list, n: int = estructura.N_PIVOTE) -> list:
    """Todos los conteos que cumplen las reglas y describen el presente,
    ordenados del mejor al peor. Cada uno con 'dir' en la dirección de verdad
    (la del impulso; en una corrección suelta, la de su onda A)."""
    zz_real = _zigzag(velas, n)[-MAX_PUNTOS:]
    out = []
    for espejo in (False, True):
        zz = _espejo(zz_real) if espejo else zz_real
        vista = _Vista(velas, espejo)
        imp = _impulsos(zz, vista)
        corr = _correcciones(zz, vista, imp)
        for c in imp:
            c["dir"] = "bajada" if espejo else "suba"
        for c in corr:
            # Una A-B-C a la baja en la vista: en la realidad baja si la vista
            # no está dada vuelta. Pegada a un impulso, el 'dir' es el del impulso.
            if c["tipo"] == "impulso_y_correccion" or c["ahora"] == "onda_B":
                c["dir"] = "bajada" if espejo else "suba"
            else:
                c["dir"] = "suba" if espejo else "bajada"
        for c in imp + corr:
            c["espejo"] = espejo
            if _duracion_ok(c) and _tamanio_ok(c, velas) and _fresco(c, velas):
                c["confianza"] = confianza(c["pautas"])
                out.append(c)
    out.sort(key=_clave, reverse=True)
    return out


def conteo(velas: list, n: int = estructura.N_PIVOTE) -> dict:
    """El conteo para la ficha.

    {'disponible': False, 'motivo': 'pocos_datos'|'sin_conteo', 'n_pivote'} o
    {'disponible': True, 'n_pivote', 'principal': {...}, 'alternativo': {...}|None}

    Cada conteo: {'tipo': 'impulso'|'correccion'|'impulso_y_correccion',
    'dir': 'suba'|'bajada', 'ondas': [{'onda': '0'|'1'..'5'|'A'|'B'|'C', 'fecha',
    'precio', 'tipo': 'pico'|'pozo'}], 'ahora': 'onda_3'|'onda_4'|'onda_5'|
    'correccion'|'onda_B'|'onda_C'|'fin_abc', 'invalida': {'precio', 'lado':
    'debajo'|'encima', 'por'}, 'confianza': 'alta'|'media'|'baja', 'pautas':
    [{'id', 'valor', 'cumple'}]}. El "0" es el arranque (no lleva número en el
    gráfico). Los precios, en la moneda de las velas."""
    velas = [v for v in velas if v.get("close") is not None and v["close"] > 0]
    if len(velas) < estructura.MIN_RUEDAS:
        return {"disponible": False, "motivo": "pocos_datos", "ruedas": len(velas), "n_pivote": n}
    lista = candidatos(velas, n)
    if not lista:
        return {"disponible": False, "motivo": "sin_conteo", "ruedas": len(velas), "n_pivote": n}
    principal = lista[0]
    distinto = next((c for c in lista[1:] if _dice_otra_cosa(principal, c)), None)
    return {"disponible": True, "n_pivote": n, "ruedas": len(velas),
            "fecha_hoy": velas[-1]["date"], "precio_hoy": _r(velas[-1]["close"]),
            "principal": _para_afuera(principal, velas),
            "alternativo": _para_afuera(distinto, velas) if distinto else None}


def _fase(c: dict) -> str:
    return "impulso" if c["ahora"] in ("onda_3", "onda_4", "onda_5") else "correccion"


def _dice_otra_cosa(a: dict, b: dict) -> bool:
    """¿`b` dice otra cosa de HOY que `a`? Tiene que estar en otra onda (u
    otra dirección): "onda 5" contra "onda 5" con otro arranque es la misma
    lectura (AAPL, GGAL, BTC el 22/10/26). Y si es el mismo conteo con una
    onda más o una menos, tiene que estar en otra fase: "en la B" contra "en la
    corrección" con los mismos puntos tampoco es otra lectura (MELI)."""
    if (a["ahora"], a["dir"], a["espejo"]) == (b["ahora"], b["dir"], b["espejo"]):
        return False
    ia, ib = [(p["i"], p["tipo"]) for p in a["pts"]], [(p["i"], p["tipo"]) for p in b["pts"]]
    corto, largo = (ia, ib) if len(ia) <= len(ib) else (ib, ia)
    if largo[:len(corto)] == corto and a["espejo"] == b["espejo"]:
        return _fase(a) != _fase(b)
    return True


def zona(c: dict):
    """Dónde suele terminar la onda EN CURSO según las mismas proporciones de
    las pautas (en la vista: dada vuelta si es una bajada). (desde, hasta) o
    None si no hay una onda en curso que medir (5 ondas terminadas sin A
    todavía, o la A-B-C terminada).
      · en la 3: desde el final de la 2, entre 1,38 y 1,9 veces la 1;
      · en la 4: desde el final de la 3, devolviendo entre 24 % y 50 % de la 3;
      · en la 5: desde el final de la 4, entre 0,75 y 1,33 veces la 1;
      · en la B: desde el final de la A, devolviendo entre 40 % y 79 % de la A;
      · en la C: desde el final de la B, entre 0,75 y 1,33 veces la A.
    Cuánto acierta, medido con la historia: `ACIERTO_ZONA`."""
    z = _zona_de_libro(c)
    if z is None:
        return None
    # Recortada por los niveles que cortan el conteo (`_limites`) y por la regla
    # del final de la onda: una zona que cae donde el propio conteo ya no vale
    # no es una zona (auditoría 23/10: en la 4, entera debajo del final de la 1).
    piso, techo = _limites(c)
    lo, hi = max(z[0], piso), min(z[1], techo)
    return (lo, hi) if lo < hi else None


def _limites(c: dict):
    """(piso, techo) en la vista: entre esos precios el conteo vale, contando
    el nivel que invalida, el otro límite y la regla del final de la onda en
    curso (la 3 pasa la 1, la 4 no se mete en la 1, la C pasa la A)."""
    piso, techo = -math.inf, math.inf
    for precio, lado in [(c["invalida"], c["invalida_lado"])] + ([(c["otro"][0], c["otro"][2])] if c.get("otro") else []):
        if lado == "debajo":
            piso = max(piso, precio)
        else:
            techo = min(techo, precio)
    P = [p["precio"] for p in c["pts"]]
    if c["ahora"] == "onda_3":
        piso = max(piso, P[1])
    if c["ahora"] == "onda_C":
        k = 5 if c["tipo"] == "impulso_y_correccion" else 0
        techo = min(techo, P[k + 1])
    return piso, techo


def _zona_de_libro(c: dict):
    """La franja de la pauta de la onda en curso, sin recortar."""
    P = [p["precio"] for p in c["pts"]]
    a = c["ahora"]
    if a == "onda_3":
        w1 = P[1] - P[0]
        return P[2] + P_ONDA3[0] * w1, P[2] + P_ONDA3[1] * w1
    if a == "onda_4":
        w3 = P[3] - P[2]
        return P[3] - P_ONDA4[1] * w3, P[3] - P_ONDA4[0] * w3
    if a == "onda_5":
        w1 = P[1] - P[0]
        return P[4] + P_ONDA5[0] * w1, P[4] + P_ONDA5[1] * w1
    if a in ("onda_B", "onda_C"):
        # El arranque de la A: el final de la 5 si va pegada, si no el "0".
        k = 5 if c["tipo"] == "impulso_y_correccion" else 0
        ini, fa = P[k], P[k + 1]
        largo_a = ini - fa
        if a == "onda_B":
            return fa + P_ONDA_B[0] * largo_a, fa + P_ONDA_B[1] * largo_a
        b = P[k + 2]
        return b - P_ONDA_C[1] * largo_a, b - P_ONDA_C[0] * largo_a
    return None


# Cuántas veces, en la historia, la onda en curso terminó DENTRO de su zona
# (`zona`), y cuántas una franja "tonta" del mismo ancho puesta justo delante
# del precio de ese día. {ahora: (aciertos, ondas terminadas, aciertos de la tonta)}.
# La pantalla lo dice al lado de la zona: sin este número la zona no se muestra.
#
# Medido el 2026-10-23 (después de la auditoría: zona recortada por los
# límites del conteo, los dos niveles que lo cortan, sin "final más lejano")
# con `scripts/medir_zonas_elliott.py` sobre 3 años de velas de 42 activos (23
# de EE.UU., 2 CEDEAR en pesos, 13 acciones argentinas en pesos, 4 cripto), día
# por día sin mirar el futuro: 2.381 conteos con zona, 1.212 ondas que
# terminaron, 852 conteos que se invalidaron antes (más de 1 de 3).
# Fibonacci 40 % contra 68 % de la tonta (EE.UU. 40/70, BYMA 39/69, cripto
# 43/60). En ninguna onda ni grupo le gana: la zona NO adivina mejor que
# "termina cerca de donde está". La auditoría lo confirmó con recorridos al
# azar, sin ninguna estructura: da lo mismo (42 % contra 72 %). Se muestra
# igual porque Nico la quiso ver (23/10), con estos números al lado, y queda
# para la auditoría de dos semanas.
ACIERTO_ZONA = {
    "onda_3": (48, 250, 134),
    "onda_4": (134, 218, 187),
    "onda_5": (131, 388, 247),
    "onda_B": (69, 141, 119),
    "onda_C": (108, 215, 143),
}
ACTIVOS_MEDIDOS = 42


def _para_afuera(c: dict, velas: list) -> dict:
    s = -1 if c["espejo"] else 1
    tipo_real = lambda t: ({"pico": "pozo", "pozo": "pico"}[t] if c["espejo"] else t)
    z = zona(c)
    medido = ACIERTO_ZONA.get(c["ahora"])
    return {
        # La zona donde suele terminar la onda en curso, en precios de verdad
        # (de menor a mayor), con cuántas veces acertó en la historia medida.
        "zona": ({"desde": _r(min(s * z[0], s * z[1])), "hasta": _r(max(s * z[0], s * z[1])),
                  "aciertos": medido[0], "casos": medido[1], "tonta": medido[2],
                  "activos": ACTIVOS_MEDIDOS}
                 if z and medido else None),
        "tipo": c["tipo"],
        "dir": c["dir"],
        "ondas": [{"onda": o, "fecha": velas[p["i"]]["date"], "precio": _r(s * p["precio"]),
                   "tipo": tipo_real(p["tipo"])} for o, p in zip(c["ondas"], c["pts"])],
        "ahora": c["ahora"],
        "invalida": {"precio": _r(s * c["invalida"]),
                     "lado": c["invalida_lado"] if not c["espejo"] else
                     {"debajo": "encima", "encima": "debajo"}[c["invalida_lado"]],
                     "por": c["invalida_por"],
                     # El otro nivel que también lo corta, del otro lado (o None).
                     "otro": ({"precio": _r(s * c["otro"][0]),
                               "lado": c["otro"][2] if not c["espejo"] else
                               {"debajo": "encima", "encima": "debajo"}[c["otro"][2]],
                               "por": c["otro"][1]} if c.get("otro") else None)},
        "confianza": c["confianza"],
        "pautas": [{"id": p["id"], "valor": _r(p["valor"], 3), "cumple": bool(p["cumple"])} for p in c["pautas"]],
    }


def _r(x, d=4):
    return round(x, d) if x is not None else None
