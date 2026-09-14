# -*- coding: utf-8 -*-
"""ai/asset_names.py no puede desincronizarse de frontend/src/utils/tickers.js.

Por qué existe este test y no un script generador: `ai/trade_tickers.py` dice
en su encabezado "GENERADO desde tickers.js — si agregás un ticker allá,
regenerá o agregalo acá", y confiar en que alguien se acuerde es exactamente
como se generan las copias que dejan de ser copias. Acá el .js se vuelve a
parsear en cada corrida: si se agrega, se saca o se renombra un activo del
catálogo del frontend y no se regenera el del backend, esto se pone rojo.

Efecto de que se desincronice: la voz de Rendi diría el CÓDIGO en vez del
nombre ("N-V-D-A" en lugar de "Nvidia") para los activos que falten.
"""
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
REPO = os.path.dirname(BACKEND)
TICKERS_JS = os.path.join(REPO, "frontend", "src", "utils", "tickers.js")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from ai.asset_names import ASSET_NAMES, asset_name   # noqa: E402


# Las MISMAS listas y en el MISMO orden que `tickerName()` del frontend: cuando
# un código está en dos listas (AAPL es acción US y también CEDEAR) gana la
# primera, y el backend tiene que elegir igual.
LISTAS = ["CRYPTO", "STOCKS_US", "ETFS", "INDICES", "CEDEARS_LIST",
          "ARG_LIDER", "ARG_GENERAL", "BONDS_AR_SOV_USD", "BONDS_AR_CER",
          "BONDS_AR_ONS", "BONDS_US_ETF"]

_ENTRY = re.compile(r"\{\s*s:\s*'([^']+)'\s*,\s*n:\s*'([^']*)'\s*\}")
# Lo que se saca para que el nombre se pueda DECIR. Ver el encabezado de
# ai/asset_names.py: el paréntesis es una nota al pie visual y leído suena a
# formulario; las siglas societarias nadie las pronuncia.
_PARENS = re.compile(r"\s*\([^)]*\)")
_SUFIJO = re.compile(r"[,]?\s+(Inc|Corp|Corporation|Ltd|Co|S\.A|SA)\.?$", re.I)


def _hablable(n):
    limpio = _SUFIJO.sub("", _PARENS.sub("", n)).strip()
    return limpio or n


def _parse_js():
    src = io.open(TICKERS_JS, encoding="utf-8").read()
    out = {}
    for nombre in LISTAS:
        m = re.search(r"export const %s = \[" % nombre, src)
        assert m, "lista %s no encontrada en tickers.js" % nombre
        i = m.end() - 1
        prof, j = 0, i
        while j < len(src):
            if src[j] == "[":
                prof += 1
            elif src[j] == "]":
                prof -= 1
                if prof == 0:
                    break
            j += 1
        for s, n in _ENTRY.findall(src[i:j]):
            if s not in out:
                out[s] = _hablable(n)
    return out


class TestCatalogoSincronizado(unittest.TestCase):
    def test_el_backend_dice_lo_mismo_que_el_frontend(self):
        js = _parse_js()
        self.assertTrue(len(js) > 400, "el parser del .js trajo muy poco: %d" % len(js))

        faltan = sorted(set(js) - set(ASSET_NAMES))
        sobran = sorted(set(ASSET_NAMES) - set(js))
        distintos = sorted(t for t in set(js) & set(ASSET_NAMES) if js[t] != ASSET_NAMES[t])

        self.assertEqual(faltan, [], (
            "Estos activos están en tickers.js y NO en ai/asset_names.py — la voz "
            "diría el código en vez del nombre: %s" % faltan[:15]))
        self.assertEqual(sobran, [], (
            "Estos activos están en ai/asset_names.py y ya no en tickers.js: %s" % sobran[:15]))
        self.assertEqual(distintos, [], (
            "Se les cambió el nombre en tickers.js y el backend quedó con el viejo: %s"
            % [(t, ASSET_NAMES[t], js[t]) for t in distintos[:8]]))


class TestNombresHablables(unittest.TestCase):
    def test_sin_parentesis_ni_siglas(self):
        # El caso que motivó todo: leído tal cual, el nombre del catálogo dice
        # "paréntesis U-S-D ley local".
        self.assertEqual(asset_name("AL30"), "Bonar 2030")     # era '… (USD ley local)'
        self.assertEqual(asset_name("MUX"), "McEwen")          # era 'McEwen Inc.'
        self.assertEqual(asset_name("GOOGL"), "Alphabet")      # era 'Alphabet (A)'

    def test_sacar_el_parentesis_no_puede_borrar_LA_DIFERENCIA(self):
        """🔴 AL30 y GD30 se decían los DOS "Argentina 2030".

        Son bonos distintos: ley argentina y ley Nueva York. Distinto precio y
        distinto riesgo legal — la primera distinción que hace cualquiera acá.
        Lo único que los separaba era el paréntesis ("(USD ley local)" contra
        "(USD ley extranjera)"), y el paréntesis es justo lo que se saca para
        que el nombre se pueda decir. Un usuario con los dos escuchaba el mismo
        nombre dos veces y no tenía cómo saber de cuál le estaban hablando.

        Los nombres de mercado los distinguen solos, que es lo que una persona
        diría en voz alta.
        """
        for anio in ("30", "35", "41"):
            self.assertEqual(asset_name("AL" + anio), "Bonar 20" + anio)
            self.assertEqual(asset_name("GD" + anio), "Global 20" + anio)
        self.assertEqual(asset_name("AE38"), "Bonar 2038")
        self.assertEqual(asset_name("GD38"), "Global 2038")
        # AL29 queda afuera del patrón A PROPÓSITO: "Bonar 2029" ya es AO29, que
        # es OTRO bono del mismo año. Quién se queda con ese nombre es una
        # decisión de producto, no de código — mientras tanto los tres se
        # llaman distinto, que es lo que este test protege.
        self.assertEqual(asset_name("AL29"), "Argentina 2029")
        self.assertEqual(asset_name("AO29"), "Bonar 2029")
        self.assertEqual(asset_name("GD29"), "Global 2029")

    def test_dos_activos_distintos_no_pueden_llamarse_igual(self):
        """El guard general del de arriba, para el próximo par que se agregue.

        Se permiten sólo los que SON el mismo instrumento escrito de dos formas
        (la clase A y la C de Alphabet, el ticker viejo y el nuevo de Block).
        Cualquier par nuevo que comparta nombre hay que mirarlo: o son lo mismo
        y va a esta lista, o es el bug de los bonos otra vez.
        """
        MISMO_INSTRUMENTO = {
            ("GOOG", "GOOGL"),          # Alphabet clase C y clase A
            ("BRK-B", "BRKB"),          # Berkshire, dos formas del mismo código
            ("SQ", "XYZ"),              # Block, ticker viejo y nuevo
            ("DIS", "DISN"),            # Disney, US y CEDEAR
            ("CAPU", "CAPX"),           # Capex, dos códigos del mismo papel
            ("TLC5O", "TLCMO"),         # Telecom 2031, misma ON
        }
        import collections
        por_nombre = collections.defaultdict(list)
        for t, n in ASSET_NAMES.items():
            por_nombre[n].append(t)
        choques = [tuple(sorted(ts)) for ts in por_nombre.values() if len(ts) > 1]
        inesperados = [c for c in choques if c not in MISMO_INSTRUMENTO]
        self.assertEqual(inesperados, [],
                         "activos distintos con el mismo nombre hablado: %s" % (inesperados,))

    def test_ningun_nombre_tiene_parentesis(self):
        con_parentesis = [f"{t}={n}" for t, n in ASSET_NAMES.items() if "(" in n or ")" in n]
        self.assertEqual(con_parentesis, [], "quedaron nombres con paréntesis: %s" % con_parentesis[:10])

    def test_ningun_nombre_vacio(self):
        vacios = [t for t, n in ASSET_NAMES.items() if not (n or "").strip()]
        self.assertEqual(vacios, [])

    def test_tolera_minusculas_y_espacios(self):
        self.assertEqual(asset_name("  nvda "), "NVIDIA")

    def test_desconocido_devuelve_none(self):
        # None es una respuesta legítima: el prompt le pide a la IA que ahí no
        # invente el nombre. Un bono inventado suena igual de convincente.
        self.assertIsNone(asset_name("NO_EXISTE_ESTE"))
        self.assertIsNone(asset_name(""))
        self.assertIsNone(asset_name(None))


if __name__ == "__main__":
    unittest.main()
