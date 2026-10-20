"""Todos los CEDEARs que cotizan en BYMA, con su precio en pesos y en dólares.

QUÉ ES. Un CEDEAR cotiza en BYMA en tres "especies": en pesos (AAPL), en
dólar-MEP (AAPLD) y en dólar-cable (AAPLC). El buscador de "Registrar compra"
muestra, en un broker argentino, el CEDEAR en pesos y el CEDEAR en dólares como
dos opciones; esto le da la lista entera (no sólo los 168 de la lista curada del
frontend) y el precio en dólares para precargar la compra.

DE DÓNDE SALE. Del mismo feed que ya cotiza los CEDEARs en pesos
(`main._fetch_data912_equities`, data912 → arg_cedears). No hay otra fuente: el
`/live/mep` de data912 trae sólo 79 pares y sin los códigos.

TRES COSAS QUE NO SON OBVIAS (medidas el 2026-10-20 sobre el feed real):

1. El código en dólares muchas veces NO es el de pesos + 'D'. Google es GOGLD,
   Bank of America es BA.CD (pesos BA.C; el 'BAC' del feed es otra cosa, en
   dólares), Berkshire BRKBD, Petrobras PETRD (pesos PETR3), Vale VAL3D (pesos
   VALE3), Citigroup C.D, Barrick B.D, ALAB ALAD, AKO.B AKOBD. Y hay tickers
   reales que terminan en D sin ser la especie dólar de nada: BBD (Bradesco) no
   es "BB en dólares". Por eso una especie es "la de dólares de X" sólo si su
   PRECIO lo confirma (pesos ÷ dólares ≈ el MEP) además del código. Sin eso, la
   primera versión ofrecía PETRD como "CEDEAR en pesos" a $13 (un auditor lo
   midió: guardado así valía 1.540 veces menos) y Petrobras quedaba sin dólares.

2. El precio en dólares de BYMA no siempre sirve. De 337 CEDEARs con especie D,
   57 no habían operado ese día (el precio es de otra rueda) y 17 se alejaban más
   de 5 % de lo que valen en pesos al MEP — ELPC +63 %, URBN +26 %, YELP −21 %.
   Se usa el precio D sólo si operó hoy y está cerca del precio en pesos ÷ MEP;
   si no, se muestra el de pesos ÷ MEP, marcado como estimado. Es el mismo número
   con el que Cartera ya valúa un CEDEAR comprado en dólares.

3. No se ofrece lo que la app no puede cotizar: un código con punto que no está
   mapeado (AKO.B) termina en 'AKO.B.BA', que `/api/prices` rechaza — en Cartera
   quedaría "sin precio" para siempre.
"""
import re
from statistics import median
from typing import Optional

from snapshots_job import BYMA_EXCEPCIONES

# Código de la especie EN PESOS cuando no es el ticker (canónico → BYMA). La
# tabla de la valuación (`snapshots_job.BYMA_EXCEPCIONES`, espejo de
# valuation.js) más BAC: BAC no está ahí porque Cartera lo cotiza por otro camino
# (la acción de EE.UU. × CCL ÷ ratio, `CEDEAR_USD_RATIOS`), pero en la Bolsa su
# CEDEAR en pesos es 'BA.C'.
PESOS_EXCEPCIONES = {**BYMA_EXCEPCIONES, 'BAC': 'BA.C'}
# La vuelta: código de pesos del feed → ticker con el que Rendi guarda el activo.
_CANONICO = {'BRKB': 'BRK-B', 'BA.C': 'BAC'}
# Especies en dólares que ni el código ni el precio alcanzan para atar solas
# (prefijo demasiado corto): verificadas a mano en el feed.
DOLARES_EXCEPCIONES = {'GOOGL': 'GOGLD'}

# Pesos ÷ dólares, dividido por el MEP de referencia: tiene que caer en esta banda
# para atar una especie a su raíz.
#  · Código "raíz + D/C" (AAPLD): banda ANCHA, el código ya es casi prueba — tolera
#    especies que operaron poco (ELPCD estaba 63 % arriba y sigue siendo de ELPC).
#  · Código irregular (PETRD ↔ PETR3, C.D ↔ C): el código tiene que compartir al
#    menos 3 letras con la raíz, o ser "raíz.X" (con UNA letra alcanzaba una
#    casualidad de precio: B.C se ataba a BMY, PETRC a PHG, SBSPD a SHW). Y hay
#    DOS preguntas con DOS bandas:
#      - ¿es una especie en dólares (y entonces NO se lista como raíz)? → banda
#        MUY ancha: PETRC, la cable de Petrobras sin operar, daba 2,36 y se
#        colaba como un CEDEAR "en pesos" a $6.
#      - ¿es LA especie en dólares de ESA raíz (la que se ofrece)? → banda
#        ANGOSTA: antes de la apertura el feed trae la mitad de los códigos, y
#        VALED (Vale ADR en dólares, sin su raíz VALE en el feed) se ataba a
#        VALE3 (la acción brasileña) con un 2,01 — un precio equivocado.
#    Pesos contra pesos da ~1/1.500 del MEP: dos raíces nunca se confunden.
_BANDA_ANCHA = (0.33, 3.0)
_BANDA_ES_DOLAR = (0.2, 5.0)
_BANDA_ANGOSTA = (0.8, 1.25)
_PREFIJO_MINIMO = 3
# Un código terminado en C/D con precio de dólar es una especie en dólares
# aunque su raíz no esté en el feed (antes de la apertura el feed trae la mitad:
# SPYD, MELID y KOD sin SPY, MELI ni KO, y se listaban como CEDEARs "en pesos" a
# 13, 16 y 19). Medido el 20/10 sobre el feed completo: la raíz en pesos más
# barata que termina en C/D vale $3.507 (LAC) y la especie en dólares más cara
# US$ 239 (HWMC). El corte en 1.000 deja margen de los dos lados.
_PRECIO_DE_DOLAR = 1000
# Cerca de cuánto del precio en pesos ÷ MEP tiene que estar el precio D para
# usarlo tal cual.
TOLERANCIA_PRECIO_USD = 0.05
# Lo que `/api/prices` acepta como base de un símbolo '.BA' (main._SYMBOL_RE sin
# el sufijo): sin punto. El guión sí (BRK-B → BRKB.BA por la excepción).
_COTIZABLE = re.compile(r'^[A-Z0-9\-]{1,12}$')


def especie_pesos(asset: str) -> str:
    a = (asset or '').upper()
    return PESOS_EXCEPCIONES.get(a, a)


def _px(fila) -> Optional[float]:
    if not fila:
        return None
    c = fila.get('c')
    return float(c) if c and c > 0 else None


def dolar_implicito(feed: dict) -> Optional[float]:
    """Mediana de pesos ÷ dólares sobre todas las especies X / XD del feed. Es el
    MEP que usa la propia Bolsa: sirve de vara para reconocer familias aunque el
    caché del dólar de la app esté frío."""
    ratios = []
    for sym, fila in feed.items():
        d = feed.get(sym + 'D')
        a, u = _px(fila), _px(d)
        if a and u:
            ratios.append(a / u)
    return median(ratios) if ratios else None


def _ratio(px_ars, px_usd, ref):
    if not (px_ars and px_usd and ref):
        return None
    return (px_ars / px_usd) / ref


def _en(r, banda):
    return r is not None and banda[0] <= r <= banda[1]


def _prefijo(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _familias(feed: dict, ref: float):
    """(`padre`, `variantes`): `padre` = {especie dólar/cable: raíz a la que se
    ofrece}; `variantes` = todo lo que es una especie en dólares/cable (atada o
    no) y por lo tanto NUNCA se lista como un CEDEAR en pesos."""
    padre = {}
    variantes = set()
    # 1. Las excepciones verificadas.
    for canon, cod in DOLARES_EXCEPCIONES.items():
        raiz = especie_pesos(canon)
        for c in (cod, cod[:-1] + 'C'):
            if c in feed and raiz in feed:
                padre[c] = raiz
    # 2. "Raíz + D/C" con el precio de acuerdo (banda ancha).
    for sym in feed:
        if sym in padre or sym[-1:] not in ('C', 'D'):
            continue
        raiz = sym[:-1]
        if raiz in feed and _en(_ratio(_px(feed[raiz]), _px(feed[sym]), ref), _BANDA_ANCHA):
            padre[sym] = raiz
    # 3. Códigos irregulares: "raíz.X" (C.D, B.C, CAR.D) o 3+ letras en común
    #    (PETRD/PETR3, VAL3D/VALE3, ALAD/ALAB) + precio. Gana la raíz con el
    #    prefijo más largo y, a igualdad, el dólar más parecido al MEP.
    raices = [s for s in feed if s not in padre]
    for sym in feed:
        if sym in padre or sym[-1:] not in ('C', 'D'):
            continue
        base = sym.rsplit('.', 1)[0] if '.' in sym else None
        mejor = None
        for r in raices:
            if r == sym or r in padre:
                continue
            k = _prefijo(sym, r)
            if base is not None:
                if r != base:
                    continue
            elif k < _PREFIJO_MINIMO:
                continue
            q = _ratio(_px(feed[r]), _px(feed[sym]), ref)
            if _en(q, _BANDA_ES_DOLAR):
                variantes.add(sym)
            if not _en(q, _BANDA_ANGOSTA):
                continue
            score = (k, -abs(q - 1))
            if mejor is None or score > mejor[0]:
                mejor = (score, r)
        if mejor:
            padre[sym] = mejor[1]
    variantes |= set(padre)
    return padre, variantes


def universo(feed: dict, mep: Optional[float] = None) -> list:
    """Una fila por CEDEAR del feed `{símbolo: {'c','pct','v'}}` (sólo arg_cedears).

    Cada fila: `s` (el ticker con el que Rendi lo guarda), `pesos` y `dolares`
    (los códigos de BYMA; `dolares` None si no tiene especie en dólares),
    `px_ars`, `px_usd` y `fuente_usd` ('byma' = precio D de hoy; 'estimado' =
    pesos ÷ MEP). `mep` es el dólar de la app; sin él se usa el implícito del feed.
    """
    ref = dolar_implicito(feed)
    mep = mep or ref
    if not ref:
        return []
    padre, variantes = _familias(feed, ref)
    # Las especies en dólares de cada raíz (las MEP: terminan en D; la cable no
    # se ofrece — no es el dólar con el que se compra en el broker).
    dolar_de = {}
    for cod, raiz in padre.items():
        if not cod.endswith('D'):
            continue
        q = _ratio(_px(feed[raiz]), _px(feed[cod]), ref)
        previo = dolar_de.get(raiz)
        if previo is None or abs((q or 9) - 1) < previo[0]:
            dolar_de[raiz] = (abs((q or 9) - 1), cod)

    # Un código del feed que ES el ticker canónico de otra especie (el 'BAC' del
    # feed cotiza en dólares y sin operar; Bank of America en pesos es 'BA.C') no
    # es una raíz: si no, el buscador mostraba dos "BAC".
    tapados = {c for b, c in _CANONICO.items() if b in feed}

    filas = []
    for sym, fila in feed.items():
        if sym in variantes or sym in tapados:
            continue
        px_ars = _px(fila)
        if not px_ars or px_ars < 1:   # YZCA a $0,01: basura del feed, no un CEDEAR
            continue
        if sym[-1:] in ('C', 'D') and px_ars < _PRECIO_DE_DOLAR:
            continue                   # especie en dólares sin su raíz en el feed
        canon = _CANONICO.get(sym, sym)
        if not _COTIZABLE.match(canon):
            continue
        cod_usd = (dolar_de.get(sym) or (None, None))[1]
        fila_usd = feed.get(cod_usd) if cod_usd else None
        px_d = _px(fila_usd)
        estimado = px_ars / mep if mep else None
        if px_d and (fila_usd.get('v') or 0) > 0 and estimado \
                and abs(px_d / estimado - 1) <= TOLERANCIA_PRECIO_USD:
            px_usd, fuente = px_d, 'byma'
        elif cod_usd:
            px_usd, fuente = estimado, 'estimado'
        else:
            px_usd, fuente = None, None
        filas.append({
            's': canon, 'pesos': sym, 'dolares': cod_usd,
            'px_ars': px_ars,
            'px_usd': round(px_usd, 4) if px_usd else None,
            'fuente_usd': fuente,
        })
    filas.sort(key=lambda f: f['s'])
    return filas
