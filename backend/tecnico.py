"""Lectura técnica de un activo: medias, fuerza del movimiento y máximo del año.

QUÉ ES. Toma las velas que guarda `velas_diarias` y arma, para la ficha del
activo, la serie del gráfico (precio, media de 50, media de 200, RSI) y los
números de la lectura (dónde está el precio contra cada media, hacia dónde va la
de 200, el RSI y la distancia al máximo de 12 meses). Las PALABRAS ("alcista",
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

QUÉ NO HACE. No sabe nada del usuario: tu precio promedio y tus compras se
dibujan en la pantalla con lo que ya tiene la ficha.
"""
from __future__ import annotations

from datetime import date, timedelta

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


def lectura(velas: list, m50=None, m200=None, r=None) -> dict:
    """Los números de la lectura técnica sobre la última vela. Las medias y el
    RSI se pueden pasar ya calculados (la ficha los calcula para el gráfico)."""
    cierres = [v["close"] for v in velas]
    n = len(cierres)
    if not n:
        return {"ruedas": 0}
    m50 = m50 if m50 is not None else media(cierres, 50)
    m200 = m200 if m200 is not None else media(cierres, 200)
    r = r if r is not None else rsi(cierres)
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
    desde = _desde_dias(velas, DIAS_GRAFICO)

    def _r(x, d=4):
        return round(x, d) if x is not None else None

    # o/h/l: apertura, máximo y mínimo, para el gráfico de velas. Pueden venir
    # vacíos (una vela de Yahoo con el máximo roto se guarda sólo con cierre).
    puntos = [{"d": velas[i]["date"], "o": _r(velas[i].get("open")), "h": _r(velas[i].get("high")),
               "l": _r(velas[i].get("low")), "c": _r(cierres[i]), "s50": _r(m50[i]),
               "s200": _r(m200[i]), "rsi": _r(r[i], 2)} for i in range(desde, len(velas))]
    return {
        "asset": (asset or "").upper(),
        "moneda": moneda,
        "disponible": True,
        "ticker": s["ticker"],
        "convertida": s["convertida"],
        "puntos": puntos,
        "lectura": lectura(velas, m50, m200, r),
        # El último cierre del instrumento con el que se valúa tu tenencia
        # (`ref`): la pantalla lo compara con el precio en vivo para que la línea
        # de tu precio no se corra lo que se movió hoy (auditoría 22/10).
        "cierre_ref": cierre_de(conn, ref) if ref else None,
    }


# ─── Señales para las alertas técnicas ───────────────────────────────────────
#
# Lo que una alerta técnica vigila (alerts_engine.evaluar_tecnicas). Cada una es
# un CAMBIO que pasa en un día de mercado, no un estado: «cruzó su promedio de
# 200 días» pasa el día que el cierre queda del otro lado, no todos los días que
# sigue ahí. Se calculan con las mismas cuentas que la ficha (`media`, `rsi`,
# `ultimo_cruce`) sobre la misma serie (`serie`), así que lo que avisa la alerta
# es lo que después se ve en la tarjeta.

SENALES = ("media200", "media50", "rsi_bajo_30", "rsi_sobre_70", "rsi_sube_30", "maximo_12m")
# Las de las medias se pueden pedir para un solo lado (arriba / abajo) o para
# los dos; las del RSI y el máximo ya dicen el sentido en el nombre.
SENALES_CON_SENTIDO = ("media200", "media50")
_RSI = {"rsi_bajo_30": (30.0, "abajo"), "rsi_sobre_70": (70.0, "arriba"),
        "rsi_sube_30": (30.0, "arriba")}
# «En su máximo» con la misma tolerancia que la tarjeta de la ficha
# (`tarjetas()` en frontend/src/utils/tecnico.js: dist_maximo_12m ≥ −0,1 %).
TOLERANCIA_MAXIMO = 0.001
# Un activo que cierra en su máximo varios días seguidos (Apple lo hizo 36 días
# en un año) avisa la PRIMERA vez: vuelve a avisar sólo después de un mes de
# mercado sin máximos.
RUEDAS_ENTRE_MAXIMOS = 20


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


def senal_desde(velas: list, senal: str, desde: str = None, sentido: str = None):
    """La última vez que pasó `senal` en una vela POSTERIOR a la fecha `desde`
    (None = en cualquiera): {'fecha', 'sentido', 'cierre', 'referencia', 'rsi'}
    o None. `sentido` ('arriba'|'abajo') acota las de las medias.

    `referencia` es contra qué se midió: el valor del promedio ese día, el nivel
    del RSI (30/70) o el máximo del año. Sin velas suficientes (menos de 200
    días para la media de 200) no pasa nada: no se inventa."""
    if not velas or senal not in SENALES:
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
        c = ultimo_cruce(cierres, m, desde_i, sentido if sentido in ("arriba", "abajo") else None)
        return _ev(c[0], c[1], m[c[0]]) if c else None
    if senal in _RSI:
        nivel, hacia = _RSI[senal]
        r = rsi(cierres)
        c = ultimo_cruce(r, nivel, desde_i, hacia)
        return _ev(c[0], c[1], nivel, r[c[0]]) if c else None
    # maximo_12m: el primer máximo después de un mes sin máximos.
    en_max = _en_maximo(velas, cierres, desde_i - RUEDAS_ENTRE_MAXIMOS)
    for i in range(len(velas) - 1, desde_i - 1, -1):
        if not en_max.get(i):
            continue
        antes = range(i - RUEDAS_ENTRE_MAXIMOS, i)
        if i - RUEDAS_ENTRE_MAXIMOS < 0 or any(en_max.get(k) is None for k in antes):
            continue    # sin el mes de antes no se sabe si es la PRIMERA vez
        if not any(en_max[k] for k in antes):
            return _ev(i, "arriba", cierres[i])
    return None
