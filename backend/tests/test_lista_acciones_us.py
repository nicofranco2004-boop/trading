"""Las acciones y ETFs de EE.UU. del chat son las de la pantalla, ni una menos.

`ai/trade_tickers.US_TICKERS` es la lista con la que el chat decide qué puede
registrar, y es una COPIA de STOCKS_US + ETFS + BONDS_US_ETF de
frontend/src/utils/tickers.js. Nadie la comparaba: el 2026-10-19 le faltaban 8
que la pantalla sí tenía (NVO, RIO, SNDK, SCHD, VIG, VYM, BND, TIP). La de
CEDEARs la vigila tests/test_fuera_de_horario.py.
"""
import os
import re
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from ai.trade_tickers import US_TICKERS  # noqa: E402

TICKERS_JS = os.path.join(BACKEND, "..", "frontend", "src", "utils", "tickers.js")


def _lista(src, nombre):
    m = re.search(r"export const %s = \[(.*?)\n\]" % nombre, src, re.S)
    assert m, "no encontré %s en tickers.js" % nombre
    leidos = re.findall(r"\bs:\s*'([^']+)'", m.group(1))
    assert len(leidos) == len(re.findall(r"\bs:", m.group(1))), \
        "%s: hay una entrada `s:` que no se pudo leer" % nombre
    return set(leidos)


def test_la_lista_del_chat_es_la_de_la_pantalla():
    src = open(TICKERS_JS, encoding="utf-8").read()
    pantalla = set()
    for nombre in ("STOCKS_US", "ETFS", "BONDS_US_ETF"):
        pantalla |= _lista(src, nombre)
    assert sorted(pantalla - US_TICKERS) == [], "la pantalla los tiene y el chat no"
    assert sorted(US_TICKERS - pantalla) == [], "el chat los tiene y la pantalla no"
