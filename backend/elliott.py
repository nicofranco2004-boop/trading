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

LA ZONA DONDE "SUELE TERMINAR" LA ONDA EN CURSO SE PROBÓ Y SE SACÓ (23/10).
Con las proporciones de Fibonacci de cada onda, medida en la historia día por
día sin mirar el futuro: 42 activos × 3 años, 40 % de aciertos contra 68 % de
una franja del mismo ancho puesta delante del precio; la sesión de verificación
(2 años, 70 activos, `audit/09_ficha_tecnica/resultados/tabla_rebobinado.md` en
`claude/zen-lewin-4c71cc`) dio 4,1 de 10 contra 7,2 de una franja al azar.
Peor que el azar en todas las ondas: Nico decidió sacarla. Las proporciones
siguen sirviendo para la confianza (lo que YA pasó), no para marcar precios.

NO MIRA EL FUTURO. Un pico o pozo entra recién cuando se confirma (N ruedas
después), y el conteo de un día usa sólo las velas hasta ese día.

QUÉ NO HACE. No recomienda ni dice qué va a pasar: las palabras las pone la
pantalla (utils/elliott.js) y siempre como "un conteo posible".
"""
from __future__ import annotations

import math
from datetime import date

import estructura

# Cuántos picos y pozos (los últimos) se miran para buscar el conteo, en cada
# grado (ver `_grados`).
MAX_PUNTOS = 26
# Los grados más grandes: el mismo zigzag, quedándose sólo con los giros de al
# menos este tamaño (en logaritmo: 0,13 ≈ un 14 % de ida o de vuelta). Se sube
# de a un escalón hasta que los MAX_PUNTOS puntos cubren toda la historia.
UMBRALES_GRADO = (0.045, 0.065, 0.09, 0.13, 0.18, 0.25, 0.35, 0.5)
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


def _resumir(zz: list, umbral: float) -> list:
    """El zigzag de un grado más grande: un giro más chico que `umbral` (en
    logaritmo del precio) no cuenta, y de los picos (o pozos) que quedan
    seguidos se queda el más extremo. Son los MISMOS picos y pozos del zigzag
    (un subconjunto): ninguno nuevo, ninguno corrido de fecha o de precio."""
    out = []
    for p in zz:
        if out and out[-1]["tipo"] == p["tipo"]:
            q = out[-1]
            if (p["precio"] > q["precio"]) if p["tipo"] == "pico" else (p["precio"] < q["precio"]):
                out[-1] = p
            continue
        if not out or abs(math.log(p["precio"] / out[-1]["precio"])) >= umbral:
            out.append(p)
    return out


def _grados(zz: list) -> list:
    """Los zigzags sobre los que se busca el conteo, del grado más chico al más
    grande. El chico son los últimos MAX_PUNTOS picos y pozos: con N = 3 velas
    eso cubre unos meses (INTC, 31/10/26: desde febrero) y un impulso que
    arrancó antes no se podía contar. Los grandes resumen la historia guardada
    (`_resumir`) hasta que entra entera. No se busca sobre todos los puntos de
    una vez: con 100 o 200 la búsqueda tarda segundos."""
    out = [zz[-MAX_PUNTOS:]]
    for u in UMBRALES_GRADO:
        s = _resumir(zz, u)
        if len(s) < 3:
            break
        w = s[-MAX_PUNTOS:]
        if [p["i"] for p in w] != [p["i"] for p in out[-1]]:
            out.append(w)
        if len(s) <= MAX_PUNTOS:
            break
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
        # Tablas para contestar «el máximo entre el día i y el j» sin recorrer
        # los días (la búsqueda lo pregunta decenas de miles de veces: con
        # max(lista[i:j]) se iba ahí el 60 % del tiempo, 02/11). Fila k: el
        # máximo de los 2^k días que empiezan en cada día.
        self._tmax, self._tmin = [self.altos], [self.bajos]
        k = 1
        while (1 << k) <= len(velas):
            m, h = self._tmax[-1], 1 << (k - 1)
            self._tmax.append([max(m[x], m[x + h]) for x in range(len(m) - h)])
            m = self._tmin[-1]
            self._tmin.append([min(m[x], m[x + h]) for x in range(len(m) - h)])
            k += 1

    def max_alto(self, i: int, j: int) -> float:
        k = (j - i + 1).bit_length() - 1
        t = self._tmax[k]
        return max(t[i], t[j - (1 << k) + 1])

    def min_bajo(self, i: int, j: int) -> float:
        k = (j - i + 1).bit_length() - 1
        t = self._tmin[k]
        return min(t[i], t[j - (1 << k) + 1])


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


def _secuencias(zz: list, tipos: tuple, vista: _Vista, largos=None) -> dict:
    """Todas las secuencias de puntos del zigzag con esos tipos en orden, cada
    uno extremo de las ondas que toca (el último, hasta hoy), por largo:
    {largo: [secuencias]} para cada largo de `largos` (sin `largos`, el de
    `tipos`). Una sola búsqueda para todos los largos: las de 3 puntos son el
    principio de las de 4, 5 y 6 (antes se buscaba cada largo de nuevo).
    Búsqueda con poda: un punto que ya no es extremo contra el siguiente no se
    extiende."""
    largos = tuple(largos or (len(tipos),))
    out = {n: [] for n in largos}
    tope = max(largos)

    def seguir(pts, desde):
        n = len(pts)
        if n in out and _es_extremo(vista, pts, n - 1, hasta_hoy=True):
            out[n].append(list(pts))
        if n == tope:
            return
        for j in range(desde, len(zz)):
            q = zz[j]
            if q["tipo"] != tipos[n]:
                continue
            pts.append(q)
            # El anterior ya puede juzgarse: tiene a los dos vecinos.
            if n < 1 or _es_extremo(vista, pts, n - 1):
                seguir(pts, j + 1)
            pts.pop()

    for j0, q in enumerate(zz):
        if q["tipo"] == tipos[0]:
            seguir([q], j0 + 1)
    return out


def _dentro(x, rango) -> bool:
    return x is not None and rango[0] <= x <= rango[1]


def _pauta(id_: str, valor: float, rango: tuple) -> dict:
    """Una pauta con el rango que decidió si se cumple: la pantalla escribe ESE
    rango (auditoría D, 29/10: el texto decía «entre 50 % y 61,8 %» al lado de
    un ✓ con 68 %, porque el ✓ salía de 40–72 % y el texto, de otro número)."""
    # Se decide con el número como se muestra (68 %, 1,62 veces: dos decimales
    # del cociente), para que un 72,4 % que la pantalla escribe «72 %» no salga
    # sin ✓ al lado de «entre 40 % y 72 %».
    valor = round(valor, 2)
    return {"id": id_, "valor": valor, "cumple": _dentro(valor, rango), "desde": rango[0], "hasta": rango[1]}


def _impulsos(zz: list, vista: _Vista) -> list:
    """Los conteos de impulso (en la dirección "a favor" de esta vista): de
    0-1-2 (la 3 en curso) a 0-1-2-3-4-5 (terminado). Sólo los que cumplen las
    reglas duras con lo que ya pasó."""
    out = []
    tipos = tuple("pozo" if k % 2 == 0 else "pico" for k in range(6))
    por_largo = _secuencias(zz, tipos, vista, (3, 4, 5, 6))
    for largo in (3, 4, 5, 6):
        for pts in por_largo[largo]:
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
    pautas.append(_pauta("onda2", r2, P_ONDA2))
    if hecho >= 3:
        pautas.append(_pauta("onda3", w3 / w1, P_ONDA3))
    if hecho >= 4:
        r4 = (P[3] - P[4]) / w3
        pautas.append(_pauta("onda4", r4, P_ONDA4))
        d2, d4 = I[2] - I[1], I[4] - I[3]
        alterna = ((r2 >= HONDA and r4 <= PLAYA) or (r4 >= HONDA and r2 <= PLAYA)
                   or max(d2, d4) >= VECES_MAS_LARGA * max(1, min(d2, d4)))
        pautas.append({"id": "alternancia", "valor": None, "cumple": alterna})
    if hecho == 5:
        pautas.append(_pauta("onda5", w5 / w1, P_ONDA5))

    ahora = {2: "onda_3", 3: "onda_4", 4: "onda_5", 5: "correccion"}[hecho]
    # El precio que invalida: el que rompería una regla dura.
    if hecho == 2:
        inval, por = P[0], "arranque_1"           # la 2 bajaría más que el arranque de la 1
    elif hecho in (3, 4):
        inval, por = P[1], "final_1"              # la 4 se metería en el terreno de la 1
    else:
        inval, por = P[5], "final_5"              # la 5 no habría terminado
    # El OTRO nivel que también lo corta, del otro lado (la tarjeta lo dice):
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
    # En la vista "a favor", una corrección arranca en un pico y baja.
    por_largo = _secuencias(zz, ("pico", "pozo", "pico", "pozo"), vista, (3, 4))
    for largo in (3, 4):
        for pts in por_largo[largo]:
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
        for pts in _secuencias([p for p in zz if p["i"] >= p5["i"]], ("pico", "pozo"), vista)[2]:
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
    pautas = [_pauta("ondaB", (P[2] - P[1]) / a, P_ONDA_B)]
    if hecho == 3:
        c = P[2] - P[3]
        pautas.append(_pauta("ondaC", c / a, P_ONDA_C))
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
    out, vistos = [], set()
    vistas = {e: _Vista(velas, e) for e in (False, True)}
    for zz_real, espejo in ((g, e) for g in _grados(_zigzag(velas, n)) for e in (False, True)):
        zz = _espejo(zz_real) if espejo else zz_real
        vista = vistas[espejo]
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
            # El mismo conteo puede salir en dos grados: va una vez.
            clave = (espejo, c["tipo"], c["ahora"], tuple(p["i"] for p in c["pts"]))
            if clave in vistos:
                continue
            vistos.add(clave)
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


def impulso_para_fibonacci(e: dict):
    """El impulso de 5 ondas TERMINADO del conteo principal, para que el
    Fibonacci lo mida entero (estructura.fibonacci): {'dir', 'fechas': {onda:
    fecha}} o None (sin conteo, o sin un impulso terminado: en la 3, la 4 o la
    5, o una corrección suelta)."""
    c = (e or {}).get("principal") if (e or {}).get("disponible") else None
    if not c or not (c["tipo"] == "impulso_y_correccion" or (c["tipo"] == "impulso" and c["ahora"] == "correccion")):
        return None
    return {"dir": c["dir"], "fechas": {o["onda"]: o["fecha"] for o in c["ondas"]}}


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


def _para_afuera(c: dict, velas: list) -> dict:
    s = -1 if c["espejo"] else 1
    tipo_real = lambda t: ({"pico": "pozo", "pozo": "pico"}[t] if c["espejo"] else t)
    return {
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
        "pautas": [{"id": p["id"], "valor": _r(p["valor"], 3), "cumple": bool(p["cumple"]),
                    **({"desde": p["desde"], "hasta": p["hasta"]} if "desde" in p else {})} for p in c["pautas"]],
    }


def _r(x, d=None):
    # Sin `d`, un precio: ver estructura.precio_redondo (con 4 decimales fijos
    # PEPE o SHIB llegaban con todas las ondas en 0, 29/10).
    if d is None:
        return estructura.precio_redondo(x)
    return round(x, d) if x is not None else None
