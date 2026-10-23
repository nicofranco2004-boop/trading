"""Lectura técnica de un activo: medias, fuerza del movimiento y máximo del año.

QUÉ ES. Toma las velas que guarda `velas_diarias` y arma, para la ficha del
activo, la serie del gráfico (precio, media de 50, media de 200, RSI, ADX y
Squeeze) y los números de la lectura (dónde está el precio contra cada media,
hacia dónde va la de 200, el RSI, la fuerza de la tendencia y la distancia al
máximo de 12 meses). Las PALABRAS de la pantalla ("alcista", "muy estirado")
las pone la pantalla; acá van los números, en un lugar. La excepción son los
hechos del resumen de Mervall-E (al final del archivo): ahí Rendi escribe las
cuentas ya en palabras para que la IA no tenga que hacer ninguna.

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
`estructura.py`; acá sólo se le pasa la misma serie que va al gráfico.

QUÉ NO HACE. No sabe nada del usuario: tu precio promedio y tus compras se
dibujan en la pantalla con lo que ya tiene la ficha.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import estructura

# Todo lo que es "un año" o "un mes" se corta por FECHA (días corridos), no por
# cantidad de velas: una cripto cotiza los 7 días y la bolsa 5.
DIAS_ANIO = 365
# Lo que se manda a la pantalla: 2 años de calendario, el rango más largo.
DIAS_GRAFICO = 2 * DIAS_ANIO
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
# así que lo calcula sobre los últimos días (la radiografía de la Cartera pide
# la lectura de cada activo y no usa el Squeeze).
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
    # que la radiografía de la Cartera pide por cada activo). Con la suma
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
    ruedas, 'squeeze': signo del Squeeze ESE día (1, -1 o 0)}. Pasar 23 para
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

    def _r(x, d=4):
        return round(x, d) if x is not None else None

    def _sig(x):
        # El Squeeze está en unidades de precio: con decimales fijos el de una
        # cripto de US$ 0,0004 daría 0. Van 6 cifras significativas.
        return float(f"{x:.6g}") if x is not None else None

    # o/h/l: apertura, máximo y mínimo, para el gráfico de velas. Pueden venir
    # vacíos (una vela de Yahoo con el máximo roto se guarda sólo con cierre).
    puntos = [{"d": velas[i]["date"], "o": _r(velas[i].get("open")), "h": _r(velas[i].get("high")),
               "l": _r(velas[i].get("low")), "c": _r(cierres[i]), "s50": _r(m50[i]),
               "s200": _r(m200[i]), "rsi": _r(r[i], 2), "adx": _r(dmi["adx"][i], 2),
               "squeeze": _sig(sqz["valor"][i]), "squeeze_color": sqz["color"][i]}
              for i in range(desde, len(velas))]
    return {
        "asset": (asset or "").upper(),
        "moneda": moneda,
        "disponible": True,
        "ticker": s["ticker"],
        "convertida": s["convertida"],
        "puntos": puntos,
        "lectura": lectura(velas, m50, m200, r, dmi, sqz),
        # El último cierre del instrumento con el que se valúa tu tenencia
        # (`ref`): la pantalla lo compara con el precio en vivo para que la línea
        # de tu precio no se corra lo que se movió hoy (auditoría 22/10).
        "cierre_ref": cierre_de(conn, ref) if ref else None,
        # Fibonacci del último tramo (estructura.py), sobre TODA la historia
        # guardada de esta misma serie: los niveles quedan en la moneda del gráfico.
        "fibonacci": estructura.fibonacci(velas),
    }


# ─── Los hechos del resumen de Mervall-E, ya en palabras ─────────────────────
#
# El resumen de la ficha lo redacta la IA, pero LAS CUENTAS LAS HACE RENDI: la
# prueba con Sonnet del 22/10 dijo «recuperó un tercio» y en otra corrida «dos
# tercios» de MercadoLibre, que había recuperado casi la mitad. Acá se calculan
# las proporciones, se redondean los precios y se escriben las fechas; la IA
# recibe frases hechas y sólo elige y une (ai/resumen_tecnico.py le prohíbe
# calcular, y revisa que no aparezca ningún número que no esté acá).
#
# TODO EN PRECIOS DE CIERRE. El tramo de Fibonacci (estructura.py) se marca con
# los picos DENTRO del día, y el máximo de 12 meses es de CIERRE: con los dos en
# el mismo texto salía «cerró en su máximo del año, 344» y dos renglones después
# «llegó a 348 el 13 de octubre». Para contar la historia se usan las FECHAS del
# tramo y los cierres de esos días; el único número de un pico del día que queda
# es el precio que, si se pasa al cierre, terminaría el movimiento, y va dicho
# como lo que es.
#
# LA ÚLTIMA VELA SE NOMBRA CON SU FECHA («el último cierre, el martes 21 de
# octubre»), nunca «hoy» ni «ayer»: las velas se guardan de noche y la de hoy
# no se guarda nunca (velas_diarias._velas_de), así que el resumen se lee casi
# siempre al día siguiente, y lo leen todos durante todo ese día: una palabra
# relativa sería falsa para una parte de los que lo leen.

_MESES_LARGOS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

# Proporción de un tramo → palabras que entiende cualquiera. Cada corte es el
# techo (sin incluir) de su frase. Fracciones conocidas: un cuarto, un tercio,
# la mitad, dos tercios, tres cuartos.
_PROPORCIONES = (
    (0.06, "casi nada"),
    (0.20, "una parte chica"),
    (0.29, "cerca de un cuarto"),
    (0.38, "cerca de un tercio"),
    (0.45, "algo menos de la mitad"),
    (0.49, "casi la mitad"),
    (0.52, "la mitad"),
    (0.60, "un poco más de la mitad"),
    (0.71, "cerca de dos tercios"),
    (0.80, "cerca de tres cuartos"),
    (0.94, "casi todo"),
    (1.00, "prácticamente todo"),
)

# Lo que se considera "casi en el promedio" (no arriba ni abajo).
_CERCA_DEL_PROMEDIO_PCT = 2.0
# Un movimiento posterior más chico que esta parte del tramo no se cuenta.
_MOVIMIENTO_MINIMO = 0.10
# El precio que terminaría el movimiento se cuenta sólo si está a menos de esto.
_UMBRAL_LEJOS_PCT = 25.0


def proporcion_en_palabras(p: float) -> str:
    """0,47 → «casi la mitad». Más de 1 (se pasó del punto de partida) → «todo, y más»."""
    if p is None:
        return None
    if p < 0:
        p = 0.0
    if p > 1.0:
        return "todo, y más"
    for techo, frase in _PROPORCIONES:
        if p < techo:
            return frase
    return "prácticamente todo"  # justo 1: volvió exacto al punto de partida


def numero_en_palabras(x: float) -> str:
    """El número redondeado como se dice: 84.000 · 1.855 · 222 · 13,45 ·
    0,0004. Punto de miles y coma decimal, a la argentina. De 10.000 para arriba
    va a la centena: «75.613 dólares» de un Bitcoin no se dice así."""
    if x is None:
        return None
    a = abs(x)
    if a >= 10000:
        s = f"{_redondo(x / 100) * 100:,}".replace(",", ".")
    elif a >= 20:
        s = f"{_redondo(x):,}".replace(",", ".")
    elif a >= 1:
        s = f"{x:.2f}".replace(".", ",")
    else:
        s = f"{float(f'{x:.3g}'):f}".rstrip("0").rstrip(".").replace(".", ",")
    return s


def precio_en_palabras(x: float, moneda: str) -> str:
    n = numero_en_palabras(x)
    return None if n is None else f"{n} {'pesos' if moneda == 'ars' else 'dólares'}"


def _redondo(x: float) -> int:
    """Redondeo de la escuela (12,5 → 13). `round` de Python redondea al par
    (12,5 → 12), y el número que se lee tiene que ser el que uno haría a mano."""
    return int(math.floor(x + 0.5))


def pct_en_palabras(x: float) -> str:
    """9,4 → «un 9 %»; 0,6 → «menos de un 1 %»."""
    if x is None:
        return None
    a = abs(x)
    return "menos de un 1 %" if a < 1 else f"un {_redondo(a)} %"


def parte_de(p: float, lo_que: str) -> str:
    """«casi la mitad de lo que había subido» · «casi todo lo que había subido» ·
    «todo lo que había subido, y más»."""
    frase = proporcion_en_palabras(p)
    if frase == "todo, y más":
        return f"todo lo que {lo_que}, y más"
    if frase.endswith("todo"):
        return f"{frase} lo que {lo_que}"
    return f"{frase} de lo que {lo_que}"


def fecha_en_palabras(iso: str, ultima: str, con_dia: bool = False) -> str:
    """'2026-10-20' → «el 20 de octubre». Con otro año que el de la última vela,
    lo lleva («el 15 de diciembre de 2025»): sin él, un diciembre leído en
    octubre parece el que viene. `con_dia`: «el martes 21 de octubre»."""
    d = date.fromisoformat(iso)
    texto = f"{d.day} de {_MESES_LARGOS[d.month - 1]}"
    if ultima and d.year != date.fromisoformat(ultima).year:
        texto += f" de {d.year}"
    return f"el {_DIAS_SEMANA[d.weekday()]} {texto}" if con_dia else f"el {texto}"


def _extremo(cierres: list, desde: str, hasta: str = None, alto: bool = True):
    """(fecha, cierre) del cierre más alto (o más bajo) entre dos fechas, ambas incluidas."""
    tramo = [(d, c) for d, c in cierres if d >= desde and (hasta is None or d <= hasta)]
    if not tramo:
        return None
    return (max if alto else min)(tramo, key=lambda x: x[1])


def _tramo_en_cierres(cierres: list, dir_: str, desde: str, hasta: str, hasta_final="igual"):
    """Un tramo de estructura.py (marcado con picos del día) pasado a cierres:
    (arranque, final), cada uno (fecha, cierre). El arranque es el cierre más
    bajo (de una suba) entre `desde` y `hasta`; el final, el más alto desde el
    arranque hasta `hasta_final` (None = hasta el último cierre: un tramo que
    sigue vivo). Las FECHAS que se dicen son las de esos cierres: con la del
    pico del día, «viene subiendo desde el 31 de julio» convivía con «subió de
    23.970 pesos el 12 de agosto»."""
    suba = dir_ == "suba"
    arranque = _extremo(cierres, desde, hasta, alto=not suba)
    if not arranque:
        return None
    final = _extremo(cierres, arranque[0], hasta if hasta_final == "igual" else hasta_final, alto=suba)
    if not final or final[1] == arranque[1]:
        return None
    return arranque, final


def _historia(cierres: list, dir_: str, desde: str, hasta: str, moneda: str, ultima: str,
              hasta_final="igual"):
    """La historia del último tramo en cierres: de dónde a dónde, lo más lejos
    que fue después, y dónde quedó al último cierre, con las proporciones ya en
    palabras. Devuelve (frases, fecha del final del tramo)."""
    suba = dir_ == "suba"
    p = lambda x: precio_en_palabras(x, moneda)
    f = lambda d: fecha_en_palabras(d, ultima)
    t = _tramo_en_cierres(cierres, dir_, desde, hasta, hasta_final)
    if not t:
        return [], None
    arranque, final = t
    amplitud = abs(final[1] - arranque[1])
    ultimo_d, ultimo_c = cierres[-1]
    frases = [f"{'Subió' if suba else 'Bajó'} de {p(arranque[1])} ({f(arranque[0])}) a "
              f"{p(final[1])} ({f(final[0])})."]
    despues = [(d, c) for d, c in cierres if d > final[0]]
    if not despues:
        return frases, final[0]
    # Lo más lejos que llegó en contra del tramo.
    ext = (min if suba else max)(despues, key=lambda x: x[1])
    contra = abs(final[1] - ext[1]) / amplitud if (ext[1] < final[1] if suba else ext[1] > final[1]) else 0.0
    if contra < _MOVIMIENTO_MINIMO:
        frases.append(f"Desde ahí casi no se movió: al último cierre estaba en {p(ultimo_c)}.")
        return frases, final[0]
    verbo, lo_que = ("perdió", "había subido") if suba else ("recuperó", "había caído")
    if ext[0] == ultimo_d:
        frases.append(f"Después {'bajó' if suba else 'subió'} hasta {p(ext[1])} al último cierre: "
                      f"{verbo} {parte_de(contra, lo_que)}.")
        return frases, final[0]
    frases.append(f"Después {'bajó' if suba else 'subió'} hasta {p(ext[1])} ({f(ext[0])}): "
                  f"{verbo} {parte_de(contra, lo_que)}.")
    # Y desde ese extremo, cuánto volvió.
    vuelta = abs(ultimo_c - ext[1]) / abs(final[1] - ext[1])
    volvio = ultimo_c > ext[1] if suba else ultimo_c < ext[1]
    if volvio and vuelta >= _MOVIMIENTO_MINIMO:
        verbo2, lo_que2 = ("recuperó", "había perdido") if suba else ("volvió a perder", "había recuperado")
        frases.append(f"Al último cierre estaba en {p(ultimo_c)}: desde {f(ext[0])} "
                      f"{verbo2} {parte_de(vuelta, lo_que2)}.")
    else:
        frases.append(f"Al último cierre estaba en {p(ultimo_c)}.")
    return frases, final[0]


def hechos_para_el_resumen(ficha: dict, nombre: str = None) -> dict:
    """Los hechos del resumen de Mervall-E, en el orden en que importan, cada uno
    ya escrito en castellano con sus números redondeados. Sale de la MISMA
    respuesta que dibuja la ficha (`para_la_ficha`), sin nada del usuario.
    None si no hay datos para contar."""
    if not ficha or not ficha.get("disponible") or not ficha.get("puntos"):
        return None
    moneda = ficha.get("moneda") or "usd"
    l = ficha.get("lectura") or {}
    cierres = [(x["d"], x["c"]) for x in ficha["puntos"] if x.get("c") is not None]
    if len(cierres) < 30:
        return None
    ultima, ultimo = cierres[-1]
    p = lambda x: precio_en_palabras(x, moneda)
    f = lambda d: fecha_en_palabras(d, ultima)
    hechos = []

    # 1. Para dónde viene ahora (el tramo vivo) y la historia del último tramo.
    fib = ficha.get("fibonacci") or {}
    vivo = fib.get("en_curso")
    # El tramo medido y el vivo se dan la mano en UN cierre: el pico (o el
    # piso) de cierre donde uno termina y el otro arranca. Con los picos del día
    # cada uno caía en una fecha distinta: Tesla «subió hasta 380 el 23 de
    # septiembre» y «venía bajando desde el 25».
    tf = fib.get("disponible") and _tramo_en_cierres(cierres, fib["dir"], fib["desde"]["fecha"],
                                                     fib["hasta"]["fecha"])
    opuesto = bool(tf and vivo and vivo["dir"] != fib["dir"])
    desde_vivo = vivo and vivo["desde"]["fecha"]
    if opuesto:
        desde_vivo = min(desde_vivo, tf[1][0])
    tv = vivo and _tramo_en_cierres(cierres, vivo["dir"], desde_vivo, vivo["hasta"]["fecha"],
                                    hasta_final=None)
    if tv:
        # Un tramo vivo puede haberse dado vuelta en los cierres sin romperse
        # todavía (se rompe con un cierre que pase el pico o el piso del día):
        # Tesla «viene bajando» con el último cierre arriba del de su pico.
        # Si ya deshizo más de la mitad, se dice «venía».
        (_, c0), (_, c1) = tv
        sube = vivo["dir"] == "suba"
        vuelta = ((c1 - ultimo) if sube else (ultimo - c1)) / abs(c1 - c0)
        palabra = "subiendo" if sube else "bajando"
        if vuelta >= 0.6:
            hechos.append(f"Desde {f(tv[0][0])} venía {palabra}, pero ya volvió a {'bajar' if sube else 'subir'}.")
        else:
            hechos.append(f"Viene {palabra} desde {f(tv[0][0])}.")
    historia, fin_tramo = [], None
    if fib.get("disponible"):
        # Si en cierres el tramo vivo arrancó DESPUÉS del final del tramo medido
        # (Apple: el piso del día fue el 31/7, pero el cierre más bajo, el 12/8),
        # el tramo medido se cuenta hasta ese cierre: si no, «viene subiendo
        # desde el 12 de agosto» y «bajó hasta 309 el 31 de julio» no cierran.
        hasta_final = "igual"
        if tv and opuesto and tv[0][0] > fib["hasta"]["fecha"]:
            hasta_final = tv[0][0]
        historia, fin_tramo = _historia(cierres, fib["dir"], fib["desde"]["fecha"],
                                        fib["hasta"]["fecha"], moneda, ultima, hasta_final)
    elif vivo:
        historia, fin_tramo = _historia(cierres, vivo["dir"], vivo["desde"]["fecha"],
                                        vivo["hasta"]["fecha"], moneda, ultima, hasta_final=None)
    hechos += historia

    # 2. El máximo del año, de cierre. Si es el final del tramo que ya se contó,
    #    se dice ahí mismo (un solo número para el mismo pico).
    if l.get("maximo_12m") is not None and l.get("anio_completo"):
        piso = (date.fromisoformat(ultima) - timedelta(days=DIAS_ANIO)).isoformat()
        maxi = _extremo(cierres, piso, alto=True)
        if maxi and maxi[0] == ultima:
            hechos.append("El último cierre es el más alto del último año.")
        elif maxi and maxi[0] == fin_tramo:
            hechos.append(f"El cierre del {f(maxi[0])[3:]} fue el más alto del último año; al último "
                          f"cierre está {pct_en_palabras(_pct(ultimo, maxi[1]))} abajo.")
        elif maxi:
            hechos.append(f"El cierre más alto del último año fue {p(maxi[1])} ({f(maxi[0])}); "
                          f"al último cierre está {pct_en_palabras(_pct(ultimo, maxi[1]))} abajo.")
        mini = _extremo(cierres, piso, alto=False)
        if mini and mini[0] == ultima:
            hechos.append("El último cierre es el más bajo del último año.")

    # 3. La tendencia de fondo: el promedio de 200 días y hacia dónde va.
    d200 = l.get("dist_media200")
    if d200 is not None and l.get("media200"):
        if abs(d200) < _CERCA_DEL_PROMEDIO_PCT:
            lado = f"casi justo en el promedio de los últimos 200 días ({p(l['media200'])})"
        else:
            lado = (f"{pct_en_palabras(d200)} {'arriba' if d200 > 0 else 'abajo'} del promedio de "
                    f"los últimos 200 días ({p(l['media200'])})")
        pend = l.get("pendiente_media200")
        # «todavía» cuando el promedio va para el otro lado que el precio: si no,
        # «abajo del promedio, que viene subiendo: tendencia para abajo» se lee
        # como una contradicción.
        todavia = "todavía " if (pend is not None and abs(d200) >= _CERCA_DEL_PROMEDIO_PCT
                                 and (pend > 0) != (d200 > 0)) else ""
        va = ("" if pend is None else
              f", y ese promedio {todavia}viene subiendo" if pend > 0.5 else
              f", y ese promedio {todavia}viene bajando" if pend < -0.5 else ", y ese promedio está casi quieto")
        fondo = ("" if abs(d200) < _CERCA_DEL_PROMEDIO_PCT else
                 ": la tendencia de fondo es para arriba" if d200 > 0 else
                 ": la tendencia de fondo es para abajo")
        hechos.append(f"Está {lado}{va}{fondo}.")

    # 4. Lo que miraría alguien: el cierre que terminaría el movimiento de ahora.
    #    Es un pico (o un pozo) de DENTRO del día, y se dice así.
    if vivo and vivo.get("se_rompe_si_cierra"):
        r = vivo["se_rompe_si_cierra"]
        nivel = r.get("debajo_de") if vivo["dir"] == "suba" else r.get("encima_de")
        if nivel and abs(_pct(nivel, ultimo)) <= _UMBRAL_LEJOS_PCT:
            # «La suba que arrancó el…», no «esta suba»: el tramo vivo puede
            # estar dado vuelta en los cierres (Tesla: «ya volvió a subir… esta
            # bajada se terminaría») y entonces «esta» no se entiende.
            arranco = f" que arrancó {f(tv[0][0])}" if tv else ""
            hechos.append(
                f"La {'suba' if vivo['dir'] == 'suba' else 'bajada'}{arranco} se terminaría si cierra "
                f"{'abajo' if vivo['dir'] == 'suba' else 'arriba'} de {p(nivel)} (el "
                f"{'piso' if vivo['dir'] == 'suba' else 'pico'} que tocó durante el día {f(r['fecha'])}).")

    # 5. La fuerza del precio (RSI).
    rsi_v = l.get("rsi")
    if rsi_v is not None:
        # La palabra sale del número que se muestra (44,6 se dice 45, y 45 es neutro).
        n = _redondo(rsi_v)
        que = ("cayó muy rápido" if n < 30 else "viene perdiendo fuerza" if n < 45 else
               "ni gana ni pierde fuerza" if n <= 55 else "viene ganando fuerza" if n <= 70 else
               "subió muy rápido")
        hechos.append(f"La fuerza del precio (RSI, de 0 a 100) está en {n}: {que}.")
        c = l.get("rsi_cruce")
        if c and c.get("hace") is not None and c["hace"] < len(cierres):
            cuando = f(cierres[-1 - c["hace"]][0])
            hechos.append(f"{cuando[0].upper()}{cuando[1:]} la fuerza del precio "
                          + ("salió de abajo de 30, después de haber caído muy rápido."
                             if c["tipo"] == "salio_de_abajo" else
                             "bajó de 70, después de haber subido muy rápido."))

    # 6. La fuerza de la tendencia (ADX) y el empuje de los últimos días (Squeeze).
    a = l.get("adx")
    if a is not None:
        pend = l.get("adx_pendiente")
        va = ("" if pend is None else ", y viene creciendo" if pend > 0.5 else
              ", y viene aflojando" if pend < -0.5 else "")
        n = _redondo(a)
        hechos.append(f"La fuerza de la tendencia (ADX) está en {n}: la tendencia es "
                      f"{'firme' if n >= ADX_CLAVE else 'floja'}{va} (se considera firme de 23 para arriba).")
        c = l.get("adx_cruce")
        if c and c.get("hace") is not None and c["hace"] < len(cierres):
            cuando = f(cierres[-1 - c["hace"]][0])
            hechos.append(f"{cuando[0].upper()}{cuando[1:]} la fuerza de la tendencia "
                          + ("pasó de 23: la tendencia tomó fuerza." if c["tipo"] == "paso_arriba"
                             else "bajó de 23: la tendencia perdió fuerza."))
    color = l.get("squeeze_color")
    if color:
        hechos.append({
            "verde_fuerte": "El empuje de los últimos días es para arriba, y cada vez más fuerte.",
            "verde_apagado": "El empuje de los últimos días es para arriba, pero cada vez más flojo.",
            "rojo_fuerte": "El empuje de los últimos días es para abajo, y cada vez más fuerte.",
            "rojo_apagado": "El empuje de los últimos días es para abajo, pero cada vez más flojo.",
        }.get(color))

    # 7. Un volumen fuera de lo común en el último cierre.
    vol = l.get("volumen_vs_promedio")
    if vol is not None and vol >= 1.8:
        veces = "el doble" if vol < 2.5 else "el triple" if vol < 3.5 else "varias veces"
        hechos.append(f"En el último cierre se negoció {veces} de lo normal.")

    # 8. En pesos, parte del movimiento es el dólar.
    if moneda == "ars":
        hechos.append("Está medido en pesos: parte de lo que sube o baja en pesos es el dólar, no la empresa.")

    return {
        "activo": nombre or (ficha.get("asset") or "").upper(),
        "moneda": "pesos" if moneda == "ars" else "dólares",
        "ultimo_cierre": f"{fecha_en_palabras(ultima, ultima, con_dia=True)}: {p(ultimo)}",
        "hechos": [h for h in hechos if h],
    }
