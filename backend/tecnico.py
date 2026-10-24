"""Lectura técnica de un activo: medias, fuerza del movimiento y máximo del año.

QUÉ ES. Toma las velas que guarda `velas_diarias` y arma, para la ficha del
activo, la serie del gráfico (precio, media de 50, media de 200, RSI, ADX y
Squeeze) y los números de la lectura (dónde está el precio contra cada media,
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


def cruce_rsi(r: list, abajo: float = 30.0, arriba: float = 70.0):
    """El último cruce del RSI hacia AFUERA de una zona extrema en las últimas
    `RUEDAS_CRUCE_RSI` ruedas: {'tipo': 'salio_de_abajo'|'salio_de_arriba',
    'hace': ruedas}. Salir de abajo de 30 es lo que muchos leen como "vuelve a
    tomar fuerza"; salir de arriba de 70, "pierde fuerza". None si no hubo."""
    n = len(r)
    for i in range(n - 1, max(0, n - 1 - RUEDAS_CRUCE_RSI), -1):
        a, b = r[i - 1], r[i]
        if a is None or b is None:
            continue
        if a < abajo <= b:
            return {"tipo": "salio_de_abajo", "hace": n - 1 - i}
        if a > arriba >= b:
            return {"tipo": "salio_de_arriba", "hace": n - 1 - i}
    return None


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
    m_bb, m_kc = _prom(largo_bb), _prom(largo_kc)
    tr = _rango_verdadero(hs, ls, cs)
    k_bb = mult_kc if como_lazybear else mult_bb
    activo = [None] * N
    for i in range(N):
        if m_bb[i] is None or m_kc[i] is None or i < largo_kc:
            continue
        w = cs[i - largo_bb + 1:i + 1]
        desvio = (sum((x - m_bb[i]) ** 2 for x in w) / largo_bb) ** 0.5   # poblacional, como `ta.stdev`
        rango = sum(tr[i - largo_kc + 1:i + 1]) / largo_kc
        activo[i] = (m_bb[i] - k_bb * desvio > m_kc[i] - mult_kc * rango
                     and m_bb[i] + k_bb * desvio < m_kc[i] + mult_kc * rango)
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


def lectura(velas: list, m50=None, m200=None, r=None, dmi=None, sqz=None) -> dict:
    """Los números de la lectura técnica sobre la última vela. Las medias, el
    RSI, el ADX y el Squeeze se pueden pasar ya calculados (la ficha los calcula
    para el gráfico)."""
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
    a = dmi["adx"]
    ultimo = cierres[-1]
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
    dmi, sqz = adx(velas), squeeze(velas)
    desde = _desde_dias(velas, DIAS_GRAFICO)
    lect = lectura(velas, m50, m200, r, dmi, sqz)

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
               "s200": p(m200[i]), "rsi": _r(r[i], 2),
               "v": velas[i].get("volume"), "adx": _r(dmi["adx"][i], 2),
               "squeeze": _sig(sqz["valor"][i]), "squeeze_color": sqz["color"][i]}
              for i in range(desde, len(velas))]
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
