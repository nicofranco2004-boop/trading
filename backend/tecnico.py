"""Lectura técnica de un activo: medias, fuerza del movimiento y máximo del año.

QUÉ ES. Toma las velas que guarda `velas_diarias` y arma, para la ficha del
activo, la serie del gráfico (precio, media de 50, media de 200, Bandas de
Bollinger, RSI, ADX y Squeeze) y los números de la lectura (dónde está el precio contra cada media,
hacia dónde va la de 200, el RSI, la fuerza de la tendencia y la distancia al
máximo de 12 meses). Las PALABRAS ("alcista",
"muy estirado") las pone la pantalla; acá van sólo los números, en un lugar.

EN QUÉ MONEDA. La tendencia se lee en DÓLARES por defecto: un CEDEAR en pesos
sube aunque la empresa no se mueva, sólo porque sube el dólar. Cómo se arma
cada vista con lo que hay guardado:
  · dólares: la serie de afuera si existe (la acción de Nueva York de un CEDEAR,
    una acción o ETF de EE.UU., una cripto); si no, la de BYMA en pesos ÷ el
    dólar MEP de CADA día (una acción argentina).
  · pesos: la de BYMA si existe; si no, la de afuera × el MEP de cada día.
El dólar de cada día sale de `fx.serie_diaria`: la MISMA regla que
`fx.fx_for_date` (el último MEP conocido; el blue sólo si no hubo ninguno).
Las velas llegan ya corregidas por `velas_diarias.serie` (cambios de ratio de un
CEDEAR y precios rotos de un día, que Yahoo no corrige): acá no se corrige nada.

EL FIBONACCI (picos, pozos, tramos de suba y de bajada) vive en
`estructura.py`, las ONDAS DE ELLIOTT (sobre esos mismos picos y pozos) en
`elliott.py`, y «Cuánto se mueve este papel» (peor caída, un día normal contra
el S&P 500, lo que se movió con cada balance y dividendo) en `movimiento.py`;
acá sólo se les pasa la misma serie que va al gráfico.

QUÉ NO HACE. No sabe nada del usuario: tu precio promedio y tus compras se
dibujan en la pantalla con lo que ya tiene la ficha.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta

import elliott
import estructura
import movimiento
from velas_diarias import DIAS_GUARDADOS, SP500

# Todo lo que es "un año" o "un mes" se corta por FECHA (días corridos), no por
# cantidad de velas: una cripto cotiza los 7 días y la bolsa 5.
DIAS_ANIO = 365
# Lo que se manda a la pantalla: TODO lo que se guarda (3 años de calendario),
# para poder arrastrar el gráfico hasta el principio (Nico, 22/10: «no deja ir
# más atrás»). Los botones 3M/1A/2A eligen qué parte se ve de entrada. La media
# de 200 de los primeros ~10 meses no se puede calcular (no hay 200 días antes)
# y esa parte del gráfico va sin esa línea, como en TradingView.
DIAS_GRAFICO = DIAS_GUARDADOS
# Hacia dónde va la media de 200: contra la de hace un mes.
DIAS_PENDIENTE = 30
# Un dólar de hace más días que esto no es "el de ese día" (mismo techo que
# price_history.MAX_DIAS_ATRAS): sin él, la vela no se convierte.
MAX_DIAS_SIN_DOLAR = 7
# Una serie en pesos que se quedó más días que esto atrás de la de afuera no se
# usa (`serie`): es la de algo que nadie sigue y no se actualiza más.
DIAS_ATRASO = 5


# ─── Cuentas ─────────────────────────────────────────────────────────────────

def media(valores: list, n: int) -> list:
    """Media simple de las últimas `n`. None hasta que haya `n` valores."""
    out, suma = [], 0.0
    for i, v in enumerate(valores):
        suma += v
        if i >= n:
            suma -= valores[i - n]
        out.append(suma / n if i >= n - 1 else None)
    return out


def rsi(cierres: list, n: int = 14) -> list:
    """RSI de Wilder (el de TradingView): el promedio de las subas contra el de
    las bajas de las últimas `n` ruedas, suavizado. 0 a 100. None al principio."""
    out = [None] * len(cierres)
    if len(cierres) <= n:
        return out
    subas = bajas = 0.0
    for i in range(1, n + 1):
        d = cierres[i] - cierres[i - 1]
        subas += max(d, 0.0)
        bajas += max(-d, 0.0)
    subas, bajas = subas / n, bajas / n

    def _valor(s, b):
        if b == 0:
            return 100.0 if s > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + s / b)

    out[n] = _valor(subas, bajas)
    for i in range(n + 1, len(cierres)):
        d = cierres[i] - cierres[i - 1]
        subas = (subas * (n - 1) + max(d, 0.0)) / n
        bajas = (bajas * (n - 1) + max(-d, 0.0)) / n
        out[i] = _valor(subas, bajas)
    return out


# Cuántas ruedas para atrás se mira si el RSI cruzó 30 o 70.
RUEDAS_CRUCE_RSI = 10


def _ref(referencia, i):
    return referencia[i] if isinstance(referencia, list) else referencia


def ultimo_cruce(valores: list, referencia, desde_i: int = 1, hacia: str = None):
    """El ÚLTIMO cruce de `valores` con `referencia` desde el índice `desde_i`:
    (índice, 'arriba'|'abajo'), o None si no cruzó.

    `referencia` es una serie (la media de 200 de cada día) o un nivel fijo (el
    30 del RSI). «Arriba» es valor ≥ referencia: la MISMA regla que la tarjeta de
    la ficha (precio ≥ media es «Alcista»). `hacia` busca sólo los cruces en ese
    sentido. Es LA cuenta de "cruzó": la usan el aviso de la ficha
    (`cruce_rsi`) y las alertas técnicas (`senal_desde`). Con una media o un
    valor que todavía no existe (None) ese día no cruza nada."""
    for i in range(len(valores) - 1, max(desde_i, 1) - 1, -1):
        a, b = valores[i - 1], valores[i]
        ra, rb = _ref(referencia, i - 1), _ref(referencia, i)
        if a is None or b is None or ra is None or rb is None:
            continue
        antes, ahora = a >= ra, b >= rb
        if antes != ahora:
            sentido = "arriba" if ahora else "abajo"
            if hacia in (None, sentido):
                return i, sentido
    return None


def cruce_rsi(r: list, abajo: float = 30.0, arriba: float = 70.0):
    """El último cruce del RSI hacia AFUERA de una zona extrema en las últimas
    `RUEDAS_CRUCE_RSI` ruedas: {'tipo': 'salio_de_abajo'|'salio_de_arriba',
    'hace': ruedas}. Salir de abajo de 30 es lo que muchos leen como "vuelve a
    tomar fuerza"; salir de arriba de 70, "pierde fuerza". None si no hubo.
    Sale de `ultimo_cruce`, la misma cuenta que las alertas técnicas."""
    n = len(r)
    desde = max(1, n - RUEDAS_CRUCE_RSI)
    de_abajo = ultimo_cruce(r, abajo, desde, "arriba")
    de_arriba = ultimo_cruce(r, arriba, desde, "abajo")
    if not de_abajo and not de_arriba:
        return None
    if de_abajo and (not de_arriba or de_abajo[0] > de_arriba[0]):
        return {"tipo": "salio_de_abajo", "hace": n - 1 - de_abajo[0]}
    return {"tipo": "salio_de_arriba", "hace": n - 1 - de_arriba[0]}


# ─── Fuerza de la tendencia: ADX + Squeeze Momentum ──────────────────────────
#
# El combo que Nico mira en TradingView («DMI/ADX/KEYLEVEL 14 14 23» +
# «SQZMOM_LB 20 2 20 1,5», el de Jaime Merino): el ADX dice CUÁNTA fuerza tiene
# la tendencia (no para dónde va) y arriba de 23 se lee como "hay tendencia";
# el Squeeze dice para DÓNDE empuja (positivo, a favor de la suba; negativo, de
# la baja). Las cuentas copian las de TradingView paso por paso para que los
# números den iguales: `ta.dmi` para el ADX y el script original de LazyBear
# para el Squeeze. Van sobre las velas DIARIAS (no hay velas de 4 horas).

# La línea clave del ADX: arriba, tendencia con fuerza.
ADX_CLAVE = 23
# Cuántas ruedas para atrás se mira si el ADX cruzó la línea clave.
RUEDAS_CRUCE_ADX = 10
# Lo que necesita el Squeeze para sus últimos valores: 20 días de bandas + 20
# de regresión + el día anterior para el color. La lectura sólo mira el final,
# así que lo calcula sobre los últimos días: la radiografía de la Cartera
# (`para_la_cartera`, que llega en su propia rama) pide la lectura de cada activo
# y no usa el Squeeze.
VELAS_SQUEEZE_LECTURA = 60
# Bandas de Bollinger: el «de costumbre» del ancho es la mediana de los últimos
# 6 meses corridos, con al menos 60 días medidos.
DIAS_ANCHO_BB = 182
MIN_ANCHOS_BB = 60
# Bandas que no se separan más que esto (en proporción al promedio) son un
# precio quieto: con una comparación exacta, el redondeo (7e-15) las separaba en
# la mitad de los precios constantes y la tarjeta decía «en el medio» al lado
# de «Sin movimiento» (auditoría 28/10).
BB_QUIETO = 1e-9
# La vela de «hace 12 meses» tiene que estar a lo sumo a estos días de esa
# fecha: después de un hueco largo era una de hace años (auditoría 28/10).
DIAS_BASE_ANIO = 10
# Cuánto se mueve: el día normal de los últimos 20 días de mercado, contra el
# de su último año (con al menos 120 días medidos). Medido el 28/10 en 15
# acciones: el orden de más tranquila a más movida se repitió de un año al otro
# (0,91), así que describe al activo; no dice para dónde va.
RUEDAS_MOVIMIENTO = 20
MIN_RUEDAS_MOVIMIENTO_ANIO = 120


def _velas_completas(velas: list):
    """Máximos, mínimos y cierres de cada vela. Si a una vela le falta algo
    (Yahoo a veces manda el máximo roto y se guarda sólo el cierre), se completa
    como la dibuja la pantalla (`velaCompleta` de utils/tecnico.js): la apertura
    con el cierre anterior y el máximo/mínimo con la apertura y el cierre."""
    hs, ls, cs = [], [], []
    prev = None
    for v in velas:
        c = v["close"]
        o = v.get("open") if v.get("open") is not None else (prev if prev is not None else c)
        h = max(v["high"], o, c) if v.get("high") is not None else max(o, c)
        lo = min(v["low"], o, c) if v.get("low") is not None else min(o, c)
        hs.append(h)
        ls.append(lo)
        cs.append(c)
        prev = c
    return hs, ls, cs


def _rma(xs: list, n: int) -> list:
    """El promedio de Wilder (`ta.rma` de TradingView): arranca con el promedio
    simple de los primeros `n` valores y después cada día pesa 1/n. Un hueco
    (None) lo hace arrancar de nuevo, como en TradingView."""
    out, prev, ventana = [None] * len(xs), None, []
    for i, x in enumerate(xs):
        if x is None:
            prev, ventana = None, []
            continue
        if prev is None:
            ventana.append(x)
            if len(ventana) > n:
                ventana.pop(0)
            if len(ventana) == n:
                prev = sum(ventana) / n
        else:
            prev = (prev * (n - 1) + x) / n
        out[i] = prev
    return out


def _rango_verdadero(hs: list, ls: list, cs: list) -> list:
    """El rango de cada día contando el salto desde el cierre anterior (`ta.tr`).
    El primer día no tiene cierre anterior: None, como en TradingView."""
    return [None] + [max(hs[i] - ls[i], abs(hs[i] - cs[i - 1]), abs(ls[i] - cs[i - 1]))
                     for i in range(1, len(cs))]


def adx(velas: list, n: int = 14, suavizado: int = None) -> dict:
    """ADX, +DI y −DI con el suavizado de Wilder: lo mismo que el script
    «DMI/ADX/KEYLEVEL» de TradingView (el que usa Nico) y que `ta.dmi(n,
    suavizado)`. {'adx', 'di_mas', 'di_menos'}: listas del largo
    de `velas`, None mientras no haya historia suficiente (el ADX necesita unas
    2×n ruedas)."""
    suavizado = suavizado or n
    hs, ls, cs = _velas_completas(velas)
    tr = _rango_verdadero(hs, ls, cs)
    # El primer día no hay día anterior: el script lo cuenta como 0 (en Pine,
    # `na > x` es falso), no como hueco. Sólo cambia las primeras semanas.
    dm_mas, dm_menos = [0.0], [0.0]
    for i in range(1, len(cs)):
        sube, baja = hs[i] - hs[i - 1], ls[i - 1] - ls[i]
        dm_mas.append(sube if (sube > baja and sube > 0) else 0.0)
        dm_menos.append(baja if (baja > sube and baja > 0) else 0.0)
    atr, s_mas, s_menos = _rma(tr, n), _rma(dm_mas, n), _rma(dm_menos, n)
    di_mas, di_menos, dx = [None] * len(cs), [None] * len(cs), [None] * len(cs)
    ult_mas = ult_menos = None
    for i in range(len(cs)):
        if atr[i] is None:
            continue
        # Con el rango en 0 (un precio que no se mueve) TradingView repite el
        # último valor conocido (`fixnan`).
        if atr[i] > 0:
            ult_mas, ult_menos = 100.0 * s_mas[i] / atr[i], 100.0 * s_menos[i] / atr[i]
        if ult_mas is None:
            continue
        di_mas[i], di_menos[i] = ult_mas, ult_menos
        total = ult_mas + ult_menos
        dx[i] = abs(ult_mas - ult_menos) / (total if total else 1.0)
    return {
        "adx": [100.0 * x if x is not None else None for x in _rma(dx, suavizado)],
        "di_mas": di_mas,
        "di_menos": di_menos,
    }


def _regresion(ys: list, n: int) -> list:
    """`ta.linreg(y, n, 0)`: la recta de mínimos cuadrados de los últimos `n`
    valores, evaluada en el último. None hasta tener `n` seguidos."""
    out = [None] * len(ys)
    sx = n * (n - 1) / 2.0
    sxx = (n - 1) * n * (2 * n - 1) / 6.0
    for i in range(n - 1, len(ys)):
        w = ys[i - n + 1:i + 1]
        if any(y is None for y in w):
            continue
        sy = sum(w)
        sxy = sum(k * y for k, y in enumerate(w))
        pendiente = (n * sxy - sx * sy) / (n * sxx - sx * sx)
        out[i] = (sy - pendiente * sx) / n + pendiente * (n - 1)
    return out


def bollinger(cierres: list, largo: int = 20, mult: float = 2.0) -> dict:
    """Bandas de Bollinger (`ta.bb` de TradingView): el promedio de los últimos
    `largo` cierres ± `mult` desvíos POBLACIONALES de esos mismos cierres.
    {'media', 'arriba', 'abajo'}: listas del largo de `cierres`, None hasta tener
    `largo` días. Es LA cuenta: la usan la ficha y el Squeeze (`squeeze`).
    Cada promedio con SU ventana (ver el comentario de `squeeze`)."""
    N = len(cierres)
    m, arriba, abajo = [None] * N, [None] * N, [None] * N
    for i in range(largo - 1, N):
        w = cierres[i - largo + 1:i + 1]
        prom = sum(w) / largo
        desvio = (sum((x - prom) ** 2 for x in w) / largo) ** 0.5
        m[i], arriba[i], abajo[i] = prom, prom + mult * desvio, prom - mult * desvio
    return {"media": m, "arriba": arriba, "abajo": abajo}


def squeeze(velas: list, largo_bb: int = 20, mult_bb: float = 2.0,
            largo_kc: int = 20, mult_kc: float = 1.5, como_lazybear: bool = True) -> dict:
    """El Squeeze Momentum de LazyBear («SQZMOM_LB»).

    · valor: la regresión lineal de `largo_kc` días de
      `cierre − promedio(promedio(máximo de 20, mínimo de 20), promedio de 20 cierres)`.
      Positivo: el precio empuja para arriba; negativo, para abajo.
    · color: 'verde_fuerte' (positivo y creciendo), 'verde_apagado' (positivo y
      bajando), 'rojo_fuerte' (negativo y bajando), 'rojo_apagado' (negativo y
      subiendo). Contra el día anterior, como el script (un valor en 0 va rojo).
    · activo: True cuando las bandas de Bollinger quedan DENTRO de las de Keltner
      (el precio está "apretado", juntando fuerza); False si no.

    `como_lazybear`: el script original arma las Bollinger con `mult_kc` (1,5) y
    no con `mult_bb` (2): es un error conocido del script, pero es lo que
    dibuja TradingView con «SQZMOM_LB 20 2 20 1,5». Se copia para que el punto
    de "apretado" dé igual que lo que ve la persona. Sólo cambia `activo`."""
    hs, ls, cs = _velas_completas(velas)
    N = len(cs)
    # Cada promedio con SU ventana (no `media()`, que es una suma acumulada):
    # así el resultado sólo depende de esos 20 días y da idéntico, bit a bit,
    # calculado sobre la historia entera (la ficha) o sobre la cola (`lectura`,
    # que la radiografía de la Cartera pedirá por cada activo). Con la suma
    # acumulada el redondeo cambiaba según dónde arrancaba la serie y, como el
    # color compara contra el día anterior, un empate lo decidía el ruido: la
    # ficha decía «rojo apagado» y la Cartera «rojo fuerte» (auditoría 22/10).
    def _prom(n):
        return [sum(cs[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(N)]
    m_kc = _prom(largo_kc)
    tr = _rango_verdadero(hs, ls, cs)
    # Las Bollinger salen de `bollinger`, la misma cuenta que dibuja la ficha.
    bb = bollinger(cs, largo_bb, mult_kc if como_lazybear else mult_bb)
    activo = [None] * N
    for i in range(N):
        if bb["media"][i] is None or m_kc[i] is None or i < largo_kc:
            continue
        rango = sum(tr[i - largo_kc + 1:i + 1]) / largo_kc
        activo[i] = (bb["abajo"][i] > m_kc[i] - mult_kc * rango
                     and bb["arriba"][i] < m_kc[i] + mult_kc * rango)
    base = [None] * N
    for i in range(largo_kc - 1, N):
        medio = (max(hs[i - largo_kc + 1:i + 1]) + min(ls[i - largo_kc + 1:i + 1])) / 2.0
        base[i] = cs[i] - (medio + m_kc[i]) / 2.0
    valor = _regresion(base, largo_kc)
    # Un precio quieto deja un residuo de redondeo (2e-14), no un empuje: va 0.
    # Si no, la pantalla dibujaba barras verdes enteras para algo que no se movió.
    valor = [0.0 if (x is not None and abs(x) <= 1e-9 * abs(cs[i])) else x for i, x in enumerate(valor)]
    color = [None] * N
    for i in range(N):
        x = valor[i]
        if x is None:
            continue
        antes = valor[i - 1] if (i > 0 and valor[i - 1] is not None) else 0.0
        if x > 0:
            color[i] = "verde_fuerte" if x > antes else "verde_apagado"
        else:
            color[i] = "rojo_fuerte" if x < antes else "rojo_apagado"
    return {"valor": valor, "color": color, "activo": activo}


def cruce_adx(a: list, s: list = None, clave: float = ADX_CLAVE):
    """El último cruce del ADX por la línea clave en las últimas
    `RUEDAS_CRUCE_ADX` ruedas: {'tipo': 'paso_arriba'|'paso_abajo', 'hace':
    ruedas, 'squeeze': signo del Squeeze ESE día (1, -1 o 0; None si ese día
    todavía no había Squeeze, con menos de 39 velas)}. Pasar 23 para
    arriba es lo que se lee como "la tendencia toma fuerza". None si no hubo."""
    n = len(a)
    for i in range(n - 1, max(0, n - 1 - RUEDAS_CRUCE_ADX), -1):
        x0, x1 = a[i - 1], a[i]
        if x0 is None or x1 is None:
            continue
        tipo = "paso_arriba" if x0 < clave <= x1 else "paso_abajo" if x0 >= clave > x1 else None
        if tipo:
            sq = s[i] if s else None
            return {"tipo": tipo, "hace": n - 1 - i,
                    "squeeze": (1 if sq > 0 else -1 if sq < 0 else 0) if sq is not None else None}
    return None


def _pct(a, b):
    return (a / b - 1.0) * 100.0 if (a is not None and b) else None


def _desde_dias(velas: list, dias: int) -> int:
    """Índice de la primera vela de los últimos `dias` días CORRIDOS. Se corta
    por fecha, no por cantidad: 252 velas son un año de bolsa pero 8 meses de
    una cripto, que cotiza los 7 días (auditoría 22/10: Bitcoin "3,8 % abajo
    del máximo del año" cuando estaba 27,7 % abajo)."""
    if not velas:
        return 0
    piso = (date.fromisoformat(velas[-1]["date"]) - timedelta(days=dias)).isoformat()
    for i, v in enumerate(velas):
        if v["date"] > piso:
            return i
    return len(velas)


def _ancho_relativo(bb: dict, velas: list):
    """El ancho de las bandas de hoy contra el de costumbre: el ancho (arriba −
    abajo, en % del promedio) ÷ la MEDIANA de ese ancho en los últimos
    `DIAS_ANCHO_BB` días corridos. 1 = como siempre; 0,5 = la mitad de ancho (el
    precio se movió mucho menos que de costumbre). None con menos de
    `MIN_ANCHOS_BB` días medidos o si el ancho de costumbre es 0."""
    def ancho(i):
        m = bb["media"][i]
        if m is None or m <= 0:
            return None
        a = (bb["arriba"][i] - bb["abajo"][i]) / m
        return a if a > BB_QUIETO else 0.0
    hoy = ancho(len(velas) - 1) if velas else None
    anchos = sorted(a for a in (ancho(i) for i in range(_desde_dias(velas, DIAS_ANCHO_BB), len(velas))) if a is not None)
    if hoy is None or len(anchos) < MIN_ANCHOS_BB:
        return None
    k = len(anchos) // 2
    mediana = anchos[k] if len(anchos) % 2 else (anchos[k - 1] + anchos[k]) / 2
    return hoy / mediana if (mediana > 0 and hoy > 0) else None


def movimiento_diario(cierres: list) -> float:
    """Cuánto se movió el precio en un día normal, en %: el desvío
    (poblacional) de los cambios de un día al otro. Para arriba o para abajo:
    2,0 es «un día normal sube o baja alrededor de 2 %». Un cierre en 0 (una
    vela rota) se saltea con su cambio. None con menos de 2 cambios."""
    cambios = [cierres[i] / cierres[i - 1] - 1.0 for i in range(1, len(cierres))
               if cierres[i - 1] > 0 and cierres[i] > 0]
    if len(cambios) < 2:
        return None
    prom = sum(cambios) / len(cambios)
    return (sum((x - prom) ** 2 for x in cambios) / len(cambios)) ** 0.5 * 100.0


def lectura(velas: list, m50=None, m200=None, r=None, dmi=None, sqz=None, bb=None) -> dict:
    """Los números de la lectura técnica sobre la última vela. Las medias, el
    RSI, el ADX, el Squeeze y las Bollinger se pueden pasar ya calculados (la
    ficha los calcula para el gráfico)."""
    cierres = [v["close"] for v in velas]
    n = len(cierres)
    if not n:
        return {"ruedas": 0}
    m50 = m50 if m50 is not None else media(cierres, 50)
    m200 = m200 if m200 is not None else media(cierres, 200)
    r = r if r is not None else rsi(cierres)
    dmi = dmi if dmi is not None else adx(velas)
    if sqz is None:
        cola = squeeze(velas[-VELAS_SQUEEZE_LECTURA:])
        relleno = [None] * (len(velas) - len(cola["valor"]))
        sqz = {k: relleno + lista for k, lista in cola.items()}
    if bb is None:
        # Sólo lo que se usa: los últimos 6 meses de anchos y sus 19 días de
        # antes. Cada banda depende sólo de su ventana de 20, así que da idéntico
        # a calcularlas sobre toda la historia (la ficha), sin el costo (la lista
        # y la Cartera piden una lectura por activo).
        desde = max(0, _desde_dias(velas, DIAS_ANCHO_BB) - 19)
        cola = bollinger(cierres[desde:])
        bb = {k: [None] * desde + lista for k, lista in cola.items()}
    a = dmi["adx"]
    ultimo = cierres[-1]
    bb_arriba, bb_abajo = bb["arriba"][-1], bb["abajo"][-1]
    i_anio = _desde_dias(velas, DIAS_ANIO)
    anio = velas[i_anio:]
    # El máximo y el mínimo del año, de CIERRE contra CIERRE: el pico dentro del
    # día de hoy nunca se alcanza al cierre, así que con el máximo intradiario
    # "En su máximo" no aparecía nunca (Apple cerró en récord 36 días del año).
    maximo = max(v["close"] for v in anio)
    minimo = min(v["close"] for v in anio)
    # Hacia dónde va la media de 200: contra la de hace un mes CORRIDO.
    i_mes = _desde_dias(velas, DIAS_PENDIENTE) - 1
    m200_antes = m200[i_mes] if 0 <= i_mes < n else None
    # Cuánto se mueve: 20 días de mercado, su último año y llevado a un mes
    # (√ de los días de mercado de los últimos 30 corridos: 21 en la bolsa, 30
    # en una cripto que cotiza los 7 días).
    mov_dia = movimiento_diario(cierres[-(RUEDAS_MOVIMIENTO + 1):]) if n > RUEDAS_MOVIMIENTO else None
    mov_anio = movimiento_diario(cierres[i_anio:]) if n - i_anio > MIN_RUEDAS_MOVIMIENTO_ANIO else None
    ruedas_mes = n - _desde_dias(velas, DIAS_PENDIENTE)
    # Ganancia por cada punto de movimiento, en PASADO (pedido de Nico, 28/10):
    # lo que cambió el precio en 12 meses ÷ cuánto se movió en ese año (el día
    # normal llevado a un año: × √ de los días de mercado del año). Medido el
    # 28/10 en 15 acciones: este número NO anticipó qué acción rindió más
    # después (INFORME_riesgo_beneficio.md). Sólo con el año completo.
    base_ok = i_anio > 0 and (date.fromisoformat(velas[-1]["date"]) - timedelta(days=DIAS_ANIO)
                              - date.fromisoformat(velas[i_anio - 1]["date"])).days <= DIAS_BASE_ANIO
    ret_12m = _pct(ultimo, cierres[i_anio - 1]) if base_ok else None
    vol_anual = mov_anio * (n - i_anio) ** 0.5 if mov_anio is not None else None
    vols = [v.get("volume") for v in velas[-21:-1] if v.get("volume")]
    vol_hoy = velas[-1].get("volume")
    return {
        "ruedas": n,
        "fecha": velas[-1]["date"],
        "precio": ultimo,
        "media50": m50[-1],
        "dist_media50": _pct(ultimo, m50[-1]),
        "media200": m200[-1],
        "dist_media200": _pct(ultimo, m200[-1]),
        "pendiente_media200": _pct(m200[-1], m200_antes),
        "rsi": r[-1],
        "rsi_cruce": cruce_rsi(r),
        "maximo_12m": maximo,
        "dist_maximo_12m": _pct(ultimo, maximo),
        "minimo_12m": minimo,
        "volumen_vs_promedio": (vol_hoy / (sum(vols) / len(vols))) if (vol_hoy and len(vols) >= 10) else None,
        "anio_completo": i_anio > 0,
        "adx": a[-1],
        "di_mas": dmi["di_mas"][-1],
        "di_menos": dmi["di_menos"][-1],
        # Cuánto cambió el ADX en los últimos 3 días de mercado: si la fuerza
        # crece o se afloja.
        "adx_pendiente": (a[-1] - a[-4]) if (n >= 4 and a[-1] is not None and a[-4] is not None) else None,
        "adx_cruce": cruce_adx(a, sqz["valor"]),
        "squeeze": sqz["valor"][-1],
        "squeeze_color": sqz["color"][-1],
        "squeeze_activo": sqz["activo"][-1],
        "bb_arriba": bb_arriba,
        "bb_abajo": bb_abajo,
        # Dónde está el precio entre las bandas: 0 en la de abajo, 1 en la de
        # arriba; menos de 0 o más de 1, afuera. None si las bandas no se
        # separan (un precio que no se movió en 20 días).
        "bb_posicion": ((ultimo - bb_abajo) / (bb_arriba - bb_abajo))
        if (bb_arriba is not None and bb["media"][-1]
            and (bb_arriba - bb_abajo) > BB_QUIETO * abs(bb["media"][-1])) else None,
        "bb_ancho_relativo": _ancho_relativo(bb, velas),
        "mov_dia": mov_dia,
        "mov_dia_anio": mov_anio,
        "mov_mes": mov_dia * ruedas_mes ** 0.5 if mov_dia is not None else None,
        "rend_12m": ret_12m,
        "mov_anual": vol_anual,
        "rend_por_movimiento": (ret_12m / vol_anual) if (ret_12m is not None and vol_anual) else None,
    }


# ─── Qué serie y en qué moneda ───────────────────────────────────────────────

def _convertir(conn, velas: list, por: str) -> list:
    """Pasa una serie de moneda: `por`='dividir' (pesos → dólares) o
    'multiplicar' (dólares → pesos), con el dólar de cada día (`fx.serie_diaria`,
    la regla de `fx.fx_for_date`). Si el último MEP conocido tiene más de una
    semana, la vela se saltea: no se inventa con un dólar viejo."""
    from fx import serie_diaria
    if not velas:
        return []
    dolares = serie_diaria(conn, velas[0]["date"])
    out, j, actual = [], 0, None
    for v in velas:
        while j < len(dolares) and dolares[j][0] <= v["date"]:
            actual = dolares[j]
            j += 1
        if not actual or (date.fromisoformat(v["date"]) - date.fromisoformat(actual[2])).days > MAX_DIAS_SIN_DOLAR:
            continue
        tc = actual[1]
        f = (lambda x: x / tc) if por == "dividir" else (lambda x: x * tc)
        out.append({**v, **{k: (f(v[k]) if v.get(k) is not None else None)
                             for k in ("open", "high", "low", "close")}})
    return out


def _atrasada(una: list, otra: list) -> bool:
    """¿La última vela de `una` tiene más de `DIAS_ATRASO` de diferencia con la
    de `otra`? (Feriados de acá o de allá separan las dos series 1 o 2 días.)"""
    return (date.fromisoformat(otra[-1]["date"]) - date.fromisoformat(una[-1]["date"])).days > DIAS_ATRASO


def serie(conn, asset: str, moneda: str = "usd", local: bool = False) -> dict:
    """La serie de `asset` en `moneda` ('usd' | 'ars') con lo que hay guardado.
    {velas, ticker, convertida} o {velas: []} si no hay.

    `local`: es una acción ARGENTINA (lo sabe la ficha por tus lotes). Entonces
    en dólares se usa SU precio de BYMA ÷ el MEP, aunque haya guardado un ticker
    pelado igual: GGAL "de afuera" es el ADR (10 acciones), que otro usuario
    puede tener en Schwab, y su precio no es el de tu acción."""
    from cripto import yahoo_de_cripto
    from snapshots_job import simbolo_byma
    import velas_diarias

    a = (asset or "").strip().upper()
    if a.endswith(".BA"):
        a = a[:-3]
    if not a:
        return {"velas": []}
    cripto = yahoo_de_cripto(a)
    de_afuera = cripto or velas_diarias.ticker_de_afuera(a)
    byma = [] if cripto else velas_diarias.serie(conn, simbolo_byma(a))
    afuera = [] if (local and byma) else velas_diarias.serie(conn, de_afuera)

    if moneda == "ars":
        # La serie en pesos de un CEDEAR que alguien tuvo y nadie sigue queda
        # guardada sin actualizar (a pedido sólo se baja la de afuera): si se
        # quedó atrás de la de afuera, se usa la de afuera × el MEP de cada día,
        # en vez de mostrar una lectura de hace semanas (auditoría 22/10).
        if byma and afuera and _atrasada(byma, afuera):
            byma = []
        if byma:
            return {"velas": byma, "ticker": simbolo_byma(a), "convertida": None}
        if afuera:
            return {"velas": _convertir(conn, afuera, "multiplicar"), "ticker": de_afuera, "convertida": "mep"}
        return {"velas": []}
    if afuera:
        return {"velas": afuera, "ticker": de_afuera, "convertida": None}
    if byma:
        return {"velas": _convertir(conn, byma, "dividir"), "ticker": simbolo_byma(a), "convertida": "mep"}
    return {"velas": []}


def sp500(conn, moneda: str = "usd") -> list:
    """Las velas del S&P 500 en `moneda` (en pesos, × el MEP de cada día, con
    la misma regla que un papel de afuera visto en pesos)."""
    import velas_diarias
    velas = velas_diarias.serie(conn, SP500)
    return _convertir(conn, velas, "multiplicar") if moneda == "ars" else velas


def ticker_de_la_empresa(conn, asset: str, local: bool = False):
    """El ticker de Yahoo con el que se buscan los balances y dividendos de la
    empresa: el de la serie en dólares de la ficha (`serie`, la misma regla:
    la acción de afuera de un CEDEAR, el '.BA' de una acción argentina). None
    para una cripto (no tiene ni balances ni dividendos) o sin velas."""
    from cripto import yahoo_de_cripto
    a = (asset or "").strip().upper()
    if not a or yahoo_de_cripto(a[:-3] if a.endswith(".BA") else a):
        return None
    return serie(conn, a, "usd", local).get("ticker")


def cierre_de(conn, simbolo: str):
    """El último cierre guardado de un símbolo tal como lo pide la valuación
    ('AAPL.BA', 'AAPL', 'BTC', 'BRK.B'), con su fecha. Sirve para saber cuánto se
    movió HOY el precio en vivo de tu tenencia contra el cierre del gráfico."""
    from cripto import yahoo_de_cripto
    import velas_diarias
    s = (simbolo or "").strip().upper()
    if not s:
        return None
    ticker = yahoo_de_cripto(s) or (s if s.endswith(".BA") else velas_diarias.ticker_de_afuera(s))
    v = velas_diarias.ultima_vela(conn, ticker)
    return {"fecha": v["date"], "cierre": v["close"]} if v else None


def para_la_ficha(conn, asset: str, moneda: str = "usd", local: bool = False, ref: str = None) -> dict:
    """Lo que necesita la ficha: la serie del gráfico (2 años de calendario) con
    sus medias y su RSI ya calculados sobre TODA la historia guardada (la media
    de 200 del primer punto del gráfico necesita los 10 meses de antes) y la
    lectura."""
    moneda = "ars" if moneda == "ars" else "usd"
    s = serie(conn, asset, moneda, local)
    velas = s["velas"]
    if not velas:
        return {"asset": (asset or "").upper(), "moneda": moneda, "disponible": False}
    cierres = [v["close"] for v in velas]
    m50, m200, r = media(cierres, 50), media(cierres, 200), rsi(cierres)
    dmi, sqz, bb = adx(velas), squeeze(velas), bollinger(cierres)
    desde = _desde_dias(velas, DIAS_GRAFICO)
    lect = lectura(velas, m50, m200, r, dmi, sqz, bb)

    def _r(x, d=4):
        return round(x, d) if x is not None else None

    def _sig(x):
        # El Squeeze está en unidades de precio: con decimales fijos el de una
        # cripto de US$ 0,0004 daría 0. Van 6 cifras significativas.
        return float(f"{x:.6g}") if x is not None else None

    # o/h/l: apertura, máximo y mínimo, para el gráfico de velas. Pueden venir
    # vacíos (una vela de Yahoo con el máximo roto se guarda sólo con cierre).
    p = estructura.precio_redondo   # abajo de 1, cifras significativas (SHIB, PEPE)
    puntos = [{"d": velas[i]["date"], "o": p(velas[i].get("open")), "h": p(velas[i].get("high")),
               "l": p(velas[i].get("low")), "c": p(cierres[i]), "s50": p(m50[i]),
               "s200": p(m200[i]), "bb_arriba": p(bb["arriba"][i]), "bb_abajo": p(bb["abajo"][i]),
               "rsi": _r(r[i], 2), "adx": _r(dmi["adx"][i], 2),
               "squeeze": _sig(sqz["valor"][i]), "squeeze_color": sqz["color"][i],
               "v": velas[i].get("volume")} for i in range(desde, len(velas))]
    return {
        "asset": (asset or "").upper(),
        "moneda": moneda,
        "disponible": True,
        "ticker": s["ticker"],
        "convertida": s["convertida"],
        "puntos": puntos,
        "lectura": lect,
        # El último cierre del instrumento con el que se valúa tu tenencia
        # (`ref`): la pantalla lo compara con el precio en vivo para que la línea
        # de tu precio no se corra lo que se movió hoy (auditoría 22/10).
        "cierre_ref": cierre_de(conn, ref) if ref else None,
        # Fibonacci del último tramo (estructura.py), sobre TODA la historia
        # guardada de esta misma serie: los niveles quedan en la moneda del gráfico.
        "fibonacci": estructura.fibonacci(velas),
        # Un conteo POSIBLE de ondas de Elliott (elliott.py) sobre los mismos
        # picos y pozos del Fibonacci y la misma serie.
        "elliott": elliott.conteo(velas),
        # «Cuánto se mueve este papel» (movimiento.py), sobre esta misma serie y
        # en su moneda; el S&P 500 en la misma moneda para comparar.
        "movimiento": movimiento.calcular(velas, sp500(conn, moneda), lect),
    }


# ─── La radiografía de la Cartera: varios activos de una vez ────────────────

# «Lo que cambió esta semana»: los cruces de los últimos 7 días corridos
# contados desde HOY (por FECHA, no por cantidad de velas: la cripto cotiza los
# 7 días y la bolsa 5). Desde hoy y no desde la última vela: si un activo dejó
# de tener velas nuevas (Yahoo falló, cambió el ticker), un cruce de hace un mes
# no puede salir como «de esta semana».
DIAS_CAMBIOS = 7
# Tope de activos por pedido: una cartera grande tiene ~60; esto frena un
# pedido armado a mano que haga leer miles de series.
MAX_ACTIVOS_CARTERA = 200


def para_la_cartera(conn, activos: list, hoy: date = None) -> list:
    """La lectura en DÓLARES de varios activos, para la radiografía de la Cartera.

    `activos`: [(asset, local)], con `local` igual que en la ficha (acción
    argentina → su precio de BYMA ÷ el MEP). Cada uno devuelve la MISMA
    `lectura` que la ficha (así las palabras salen de la misma regla) y
    `cambios`: lo que cambió en los últimos `DIAS_CAMBIOS` días (`cambios_desde`,
    la misma cuenta que «Tus señales»). Sin velas: `disponible` False, nunca se
    inventa. `hoy` (día argentino) lo pasa quien ya tiene su reloj: el resumen
    de los sábados."""
    from fechas import hoy_art_date
    desde = ((hoy or hoy_art_date()) - timedelta(days=DIAS_CAMBIOS)).isoformat()
    out = []
    for a, local, velas in _series_en_dolares(conn, activos):
        if not velas:
            out.append({"asset": a, "local": local, "disponible": False})
            continue
        cierres = [v["close"] for v in velas]
        out.append({"asset": a, "local": local, "disponible": True,
                    "lectura": lectura(velas, media(cierres, 50), media(cierres, 200)),
                    "cambios": cambios_desde(velas, desde)})
    return out


def _series_en_dolares(conn, activos: list):
    """(asset, local, velas en dólares) de cada activo de `activos` [(asset,
    local)], una vez cada uno. La serie es la de la ficha (`serie`, con la
    misma marca `local`)."""
    vistos = set()
    for asset, local in activos:
        a = (asset or "").strip().upper()
        clave = (a, bool(local))
        if not a or clave in vistos:
            continue
        vistos.add(clave)
        yield a, bool(local), serie(conn, a, "usd", bool(local))["velas"]


# ─── Tu lista (cartera + watchlist) con su lectura técnica ──────────────────

# La línea chica de cada fila: los cierres de los últimos 3 meses corridos.
DIAS_LINEA = 92
# «Último cambio»: el más reciente del último año contado desde HOY (la cuenta
# de qué es un cambio es `cambios_desde`, la de «qué cambió esta semana»; acá
# no se repite). Desde hoy y no desde la última vela, como la radiografía: con
# la serie cortada, el año no se corre para atrás.
DIAS_ULTIMO_CAMBIO = DIAS_ANIO


def _ultimo_cambio(velas: list, desde: str):
    """El cambio más reciente desde `desde`, de `cambios_desde` (la cuenta
    ÚNICA de cruces, la de «Tus señales»; ya viene el más nuevo primero), con
    sus palabras de `senales_semana.texto_del_cambio` (las mismas de «Tus
    señales» y del mail de los sábados: etiqueta, tono, texto, extra). None si
    no hubo."""
    from senales_semana import texto_del_cambio   # acá: senales_semana importa tecnico
    cambios = cambios_desde(velas, desde) if velas else []
    return {**cambios[0], **texto_del_cambio(cambios[0])} if cambios else None


def para_la_lista(conn, activos: list) -> list:
    """La lectura en DÓLARES de lo que tenés y lo que seguís, para «Tu lista,
    con su lectura técnica». `activos`: [(asset, local)] como en la Cartera.

    Cada uno trae la MISMA `lectura` que su ficha y que la radiografía (de ahí
    salen las palabras de las dos tendencias, la fuerza, el ADX y la distancia
    al máximo del año), `linea`: los cierres de los últimos 3 meses para la
    línea chica de la fila, y `ultimo_cambio` (ver `_ultimo_cambio`). Sin
    velas: `disponible` False, nunca se inventa. Cuánto pesa cada uno lo pone
    la pantalla, con la valuación de la Cartera."""
    from fechas import hoy_art_date
    desde = (hoy_art_date() - timedelta(days=DIAS_ULTIMO_CAMBIO)).isoformat()
    out = []
    for a, local, velas in _series_en_dolares(conn, activos):
        if not velas:
            out.append({"asset": a, "local": local, "disponible": False})
            continue
        cierres = [v["close"] for v in velas]
        linea = [{"d": v["date"], "c": estructura.precio_redondo(v["close"])}
                 for v in velas[_desde_dias(velas, DIAS_LINEA):]]
        out.append({"asset": a, "local": local, "disponible": True,
                    "lectura": lectura(velas, media(cierres, 50), media(cierres, 200)),
                    "linea": linea, "ultimo_cambio": _ultimo_cambio(velas, desde)})
    return out


# ─── Señales para las alertas técnicas ───────────────────────────────────────
#
# Lo que una alerta técnica vigila (alerts_engine.evaluar_tecnicas). Cada una es
# un CAMBIO que pasa en un día de mercado, no un estado: «cruzó su promedio de
# 200 días» pasa el día que el cierre queda del otro lado, no todos los días que
# sigue ahí. Se calculan con las mismas cuentas que la ficha (`media`, `rsi`,
# `ultimo_cruce`) sobre la misma serie (`serie`), así que lo que avisa la alerta
# es lo que después se ve en la tarjeta.

SENALES = ("media200", "media50", "rsi_bajo_30", "rsi_sobre_70", "rsi_sube_30", "rsi_baja_70",
           "maximo_12m")
# Las de las medias se pueden pedir para un solo lado (arriba / abajo) o para
# los dos; las del RSI y el máximo ya dicen el sentido en el nombre.
SENALES_CON_SENTIDO = ("media200", "media50")
# Las dos de "volver" son las que la ficha ya anuncia (`cruce_rsi`): salir de
# abajo de 30 y salir de arriba de 70.
_RSI = {"rsi_bajo_30": (30.0, "abajo"), "rsi_sobre_70": (70.0, "arriba"),
        "rsi_sube_30": (30.0, "arriba"), "rsi_baja_70": (70.0, "abajo")}
# «En su máximo» con la misma tolerancia que la tarjeta de la ficha
# (`tarjetas()` en frontend/src/utils/tecnico.js: dist_maximo_12m ≥ −0,1 %).
TOLERANCIA_MAXIMO = 0.001
# Un activo que cierra en su máximo varios días seguidos (Apple lo hizo 36 días
# en un año) avisa la PRIMERA vez: vuelve a avisar sólo después de un mes sin
# máximos. Días CORRIDOS, como todo lo de "un mes" acá: una cripto cotiza los 7.
DIAS_ENTRE_MAXIMOS = 30


def _en_maximo(velas: list, cierres: list, desde_i: int) -> dict:
    """{i: True/False} desde `desde_i`: ¿el cierre de ese día es el más alto de
    los 12 meses (corridos) que terminan ese día? Sin un año entero de velas
    antes, no se sabe (no figura): el «máximo del año» de 4 meses no es tal."""
    out = {}
    if not velas:
        return out
    j = 0
    primera = date.fromisoformat(velas[0]["date"])
    for i in range(max(0, desde_i), len(velas)):
        piso = date.fromisoformat(velas[i]["date"]) - timedelta(days=DIAS_ANIO)
        if primera > piso:
            continue
        piso_iso = piso.isoformat()
        while velas[j]["date"] <= piso_iso:
            j += 1
        out[i] = cierres[i] >= max(cierres[j:i + 1]) * (1 - TOLERANCIA_MAXIMO)
    return out


# ─── Tu línea (las alertas de un dibujo del gráfico) ─────────────────────────
# «Avisame si el precio toca esta línea» (Nico, 28/10): una línea horizontal o
# de tendencia que la persona dibujó en la ficha (tabla `dibujos_grafico`). No es
# una señal de la ficha: no va en SENALES. La línea se lee de lo dibujado cada
# vez (alerts_engine), así que si la mueven, el aviso la sigue.
SENAL_LINEA = "linea"


def _indice_del_punto(velas: list, p: dict):
    """En qué vela cae un punto dibujado ({d, mas, precio}): el último día con
    fecha ≤ `d` más `mas` días de mercado. La misma cuenta que `diaDelPunto` de
    la ficha (frontend/src/utils/dibujos.js). Antes del primer día: None."""
    fechas = [v["date"] for v in velas]
    i = bisect_right(fechas, str(p.get("d") or "")) - 1
    return None if i < 0 else i + int(p.get("mas") or 0)


def valor_de_linea(velas: list, linea: dict, i: int):
    """El precio de la línea en la vela `i`. Una horizontal, su precio; una de
    tendencia, la recta que pasa por sus dos puntos, también después de su
    segundo punto (sigue en la misma dirección). None si no se puede saber."""
    if linea.get("tipo") == "horizontal":
        return linea.get("precio")
    a, b = linea.get("a") or {}, linea.get("b") or {}
    ia, ib = _indice_del_punto(velas, a), _indice_del_punto(velas, b)
    if ia is None or ib is None or ia == ib:
        return None
    return a["precio"] + (b["precio"] - a["precio"]) * (i - ia) / (ib - ia)


def toque_de_linea(velas: list, linea: dict, desde: str = None):
    """La PRIMERA vela posterior a `desde` que tocó la línea: su mínimo y su
    máximo la encierran, o el cierre quedó del otro lado del de la vela
    anterior (un salto por encima de la línea, sin tocarla en el día).
    {'fecha', 'sentido', 'cierre', 'referencia', 'rsi', 'minimo', 'maximo'}
    o None. `sentido`: 'arriba' si venía de abajo (subió hasta la línea),
    'abajo' si venía de arriba. `referencia`: el precio de la línea ese día."""
    if not velas:
        return None
    desde_i = 0
    if desde:
        desde_i = next((i for i, v in enumerate(velas) if v["date"] > desde), len(velas))
    for i in range(desde_i, len(velas)):
        nivel = valor_de_linea(velas, linea, i)
        if nivel is None or nivel <= 0:
            continue
        v = velas[i]
        cierre = v["close"]
        alto, bajo = v.get("high") or cierre, v.get("low") or cierre
        antes = velas[i - 1]["close"] if i > 0 else None
        nivel_antes = valor_de_linea(velas, linea, i - 1) if i > 0 else None
        salto = (antes is not None and nivel_antes is not None
                 and (antes - nivel_antes) * (cierre - nivel) < 0)
        if bajo <= nivel <= alto or salto:
            venia_de_abajo = antes is not None and nivel_antes is not None and antes < nivel_antes
            return {"fecha": v["date"], "sentido": "arriba" if venia_de_abajo else "abajo",
                    "cierre": cierre, "referencia": nivel, "rsi": None,
                    "minimo": bajo, "maximo": alto}
    return None


def senal_desde(velas: list, senal: str, desde: str = None, sentido: str = None):
    """La última vez que pasó `senal` en una vela POSTERIOR a la fecha `desde`
    (None = en cualquiera): {'fecha', 'sentido', 'cierre', 'referencia', 'rsi'}
    o None. `sentido` ('arriba'|'abajo') acota las de las medias.

    Vale el ÚLTIMO cruce del período, en cualquier sentido: si cruzó para arriba
    y al día siguiente volvió abajo (llegan dos días juntos cuando una noche no
    corrió), lo que muestra la ficha es «Bajista» y una alerta «para arriba» no
    avisa nada. Buscar sólo los cruces del lado pedido avisaba «se volvió
    alcista» con la tarjeta diciendo lo contrario (auditoría 22/10).

    `referencia` es contra qué se midió: el valor del promedio ese día, el nivel
    del RSI (30/70) o el máximo del año. Sin velas suficientes (menos de 200
    días para la media de 200) no pasa nada: no se inventa.

    Además de las de `SENALES` acepta 'adx23' (el ADX pasa 23), que no es un
    tipo de alerta: la usa `cambios_desde` para «Tus señales»."""
    if not velas or senal not in SENALES + ("adx23",):
        return None
    desde_i = 1
    if desde:
        desde_i = next((i for i, v in enumerate(velas) if v["date"] > desde), len(velas))
    if desde_i >= len(velas):
        return None
    cierres = [v["close"] for v in velas]

    def _ev(i, sentido, referencia, r=None):
        return {"fecha": velas[i]["date"], "sentido": sentido, "cierre": cierres[i],
                "referencia": referencia, "rsi": r}

    if senal in ("media200", "media50"):
        m = media(cierres, 200 if senal == "media200" else 50)
        c = ultimo_cruce(cierres, m, desde_i)
        if not c or (sentido in ("arriba", "abajo") and c[1] != sentido):
            return None
        return _ev(c[0], c[1], m[c[0]])
    if senal in _RSI:
        nivel, hacia = _RSI[senal]
        r = rsi(cierres)
        c = ultimo_cruce(r, nivel, desde_i)
        if not c or c[1] != hacia:
            return None
        ev = _ev(c[0], c[1], nivel, r[c[0]])
        # De dónde venía: el RSI una semana de mercado antes («bajó de 52»).
        ev["rsi_antes"] = r[c[0] - RUEDAS_SEMANA] if c[0] >= RUEDAS_SEMANA else None
        return ev
    if senal == "adx23":
        # Fuerza de la tendencia: el ADX pasa la línea clave (la regla de
        # `cruce_adx`, ≥ 23 es arriba). Para DÓNDE marca dirección lo dice el
        # Squeeze de ese día, como la tarjeta de la ficha.
        a = adx(velas)["adx"]
        c = ultimo_cruce(a, ADX_CLAVE, desde_i)
        if not c or (sentido in ("arriba", "abajo") and c[1] != sentido):
            return None
        sq = squeeze(velas)["valor"][c[0]]
        ev = _ev(c[0], c[1], ADX_CLAVE)
        ev["adx"] = a[c[0]]
        ev["squeeze"] = (1 if sq > 0 else -1 if sq < 0 else 0) if sq is not None else None
        return ev
    # maximo_12m: el primer máximo después de un mes sin máximos.
    def _piso(i):
        return (date.fromisoformat(velas[i]["date"]) - timedelta(days=DIAS_ENTRE_MAXIMOS)).isoformat()
    primero = next((k for k, v in enumerate(velas) if v["date"] > _piso(desde_i)), desde_i)
    en_max = _en_maximo(velas, cierres, primero)
    for i in range(len(velas) - 1, desde_i - 1, -1):
        if not en_max.get(i):
            continue
        piso = _piso(i)
        antes, k = [], i - 1
        while k >= 0 and velas[k]["date"] > piso:
            antes.append(k)
            k -= 1
        if velas[0]["date"] > piso or any(en_max.get(k) is None for k in antes):
            continue    # sin el mes de antes no se sabe si es la PRIMERA vez
        if not any(en_max[k] for k in antes):
            return _ev(i, "arriba", cierres[i])
    return None


# ─── Qué cambió: la lista de «Tus señales» ───────────────────────────────────
#
# UNA cuenta de «qué cambió desde tal fecha», hecha con las señales de arriba
# (`senal_desde`, que sale de `ultimo_cruce`): la usan la radiografía de la
# Cartera (`para_la_cartera`), la pestaña «Tus señales» y su resumen de los
# sábados, y la columna «Último cambio» del tablero de la watchlist. Ninguna
# regla se escribe de nuevo acá: un cambio que sale en «Tus señales» es el mismo
# que avisaría una alerta y el que se ve en la tarjeta de la ficha.

# En orden de importancia: así salen en el día y en el resumen.
#   media200 / media50: el precio cruzó su promedio (los dos lados);
#   rsi_bajo_30 / rsi_sobre_70: la fuerza (RSI) cayó / subió muy rápido;
#   maximo_12m: el primer máximo de 12 meses después de un mes sin máximos;
#   adx23: el ADX pasó 23 para arriba (la tendencia marca dirección).
TIPOS_CAMBIO = ("media200", "media50", "rsi_bajo_30", "rsi_sobre_70", "maximo_12m", "adx23")
# Una semana de mercado, para «el RSI venía de…».
RUEDAS_SEMANA = 5


def cambios_desde(velas: list, desde: str) -> list:
    """Los cambios de un activo en las velas POSTERIORES a la fecha `desde`:
    [{'tipo', 'fecha', 'sentido', 'cierre', 'referencia', 'rsi', …}], el más
    nuevo primero (y, el mismo día, en el orden de `TIPOS_CAMBIO`). De cada tipo
    vale el ÚLTIMO del período, como en `senal_desde`: si cruzó para arriba y
    volvió abajo, queda «quedó abajo». Extras: 'rsi_antes' (el RSI una semana de
    mercado antes) en los del RSI; 'adx' y 'squeeze' (signo) en el del ADX.

    `desde` lo pone quien llama, contado desde HOY y no desde la última vela:
    con la serie cortada (Yahoo dejó de mandar), un cruce de hace un mes no es
    «de esta semana» (radiografia-tecnica.md, arreglo 1)."""
    out = []
    for orden, tipo in enumerate(TIPOS_CAMBIO):
        ev = senal_desde(velas, tipo, desde, "arriba" if tipo == "adx23" else None)
        if ev:
            out.append((orden, {"tipo": tipo, **ev}))
    out.sort(key=lambda x: (x[1]["fecha"], -x[0]), reverse=True)
    return [c for _, c in out]
