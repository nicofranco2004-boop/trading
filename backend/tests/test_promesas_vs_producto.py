"""Lo que la pantalla PROMETE tiene que ser lo que el producto HACE.

Este archivo existe por un bug concreto y caro: la pantalla de "elegí un plan"
—la que le pide la plata al usuario— tenía la lista de features escrita a mano
y prometía cuatro cosas falsas a la vez:

  · "Brokers ilimitados" en Plus, cuando Plus tiene tope 3 (ilimitado es Pro);
  · "20 análisis por semana" en Plus, cuando son 6;
  · "sin límite de análisis" en Pro, cuando son 60 por semana;
  · "calendario de cobros" y "carpeta de impuestos", que ni existen.

Ninguna de las cuatro produce un error en ninguna parte: se cobra, y recién
después el producto no cumple. El arreglo fue que la pantalla lea el catálogo
(`frontend/src/data/planCatalog.js`), pero eso sólo mueve el problema: nada
impedía que el CATÁLOGO se desincronizara de los límites que el backend aplica
de verdad. Este test cierra ese último eslabón.

Lee el catálogo del frontend como TEXTO a propósito: es la única forma de que
un test de Python vigile un archivo de JavaScript, y lo que se compara es
justamente el número que el usuario ve contra el número que lo bloquea.

Corre con: cd backend && python3 -m pytest tests/test_promesas_vs_producto.py
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

CATALOGO = os.path.join(
    os.path.dirname(BACKEND), "frontend", "src", "data", "planCatalog.js")

from ai.quota import LIMITS            # noqa: E402
from ai.plan import PLAN_LIMITS        # noqa: E402


def _quotas_del_catalogo(plan: str) -> dict:
    """Los tres números del bloque `quotas` de un plan, como {label: value}."""
    fuente = open(CATALOGO, encoding="utf-8").read()
    bloque = re.search(
        r"export const %s_FEATURES = \{(.*?)\n\}\n" % plan.upper(),
        fuente, re.S)
    assert bloque, f"no encontré {plan.upper()}_FEATURES en {CATALOGO}"
    quotas = re.search(r"quotas: \[(.*?)\]", bloque.group(1), re.S)
    assert quotas, f"{plan} no declara quotas"
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"\{ label: '([^']+)', value: '([^']+)'",
                             quotas.group(1))
    }


class LosCuposQuePrometeLaPantalla(unittest.TestCase):
    """Cada número del catálogo contra el límite que se aplica de verdad."""

    def test_el_catalogo_existe_donde_lo_buscamos(self):
        """Si alguien mueve el archivo, este test tiene que avisar — no pasar
        en verde por no encontrar nada que comparar."""
        self.assertTrue(os.path.exists(CATALOGO), CATALOGO)

    def test_los_analisis_por_semana(self):
        for plan in ("free", "plus", "pro"):
            con_q = _quotas_del_catalogo(plan)
            prometido = con_q.get("Análisis IA / sem")
            real = LIMITS[plan]["analyses_per_week"]
            self.assertEqual(
                prometido, str(real),
                f"{plan}: la pantalla promete {prometido} análisis/semana y "
                f"quota.LIMITS aplica {real}")

    def test_el_chat_por_semana(self):
        for plan in ("free", "plus", "pro"):
            con_q = _quotas_del_catalogo(plan)
            prometido = con_q.get("Chat Rendi AI / sem")
            real = LIMITS[plan]["chat_per_week"]
            self.assertEqual(
                prometido, str(real),
                f"{plan}: la pantalla promete {prometido} chats/semana y "
                f"quota.LIMITS aplica {real}")

    def test_los_brokers(self):
        """El caso que se fue a producción en el muro: "ilimitados" en el plan
        que tiene tope. `None` en el backend = sin tope = '∞' en la pantalla."""
        for plan in ("free", "plus", "pro"):
            con_q = _quotas_del_catalogo(plan)
            prometido = con_q.get("Brokers")
            real = PLAN_LIMITS[plan]["brokers_max"]
            esperado = "∞" if real is None else str(real)
            self.assertEqual(
                prometido, esperado,
                f"{plan}: la pantalla promete {prometido} brokers y "
                f"plan.PLAN_LIMITS aplica {esperado}")

    def test_solo_pro_tiene_brokers_ilimitados(self):
        """Regresión directa del bug: Plus decía "Brokers ilimitados"."""
        self.assertIsNone(PLAN_LIMITS["pro"]["brokers_max"])
        self.assertIsNotNone(PLAN_LIMITS["plus"]["brokers_max"])
        self.assertNotEqual(_quotas_del_catalogo("plus").get("Brokers"), "∞")


class LosMultiplosQueLaPaginaCanta(unittest.TestCase):
    """El catálogo no sólo dice cupos: dice "60× más que Free · 30× que Plus".
    Ese múltiplo es una cuenta entre dos cupos, así que se desincroniza solo el
    día que cambia cualquiera de los dos — y ya pasó: decía "10× que Plus"
    cuando el Plus bajó de 6 a 2."""

    def _sub_de(self, plan: str, etiqueta: str) -> str:
        fuente = open(CATALOGO, encoding="utf-8").read()
        bloque = re.search(
            r"export const %s_FEATURES = \{(.*?)\n\}\n" % plan.upper(),
            fuente, re.S).group(1)
        m = re.search(
            r"\{ label: '%s'[^}]*?sub: '([^']+)'" % re.escape(etiqueta), bloque)
        assert m, f"no encontré el sub de «{etiqueta}» en {plan}"
        return m.group(1)

    def test_el_multiplo_contra_free_es_el_real(self):
        sub = self._sub_de("pro", "60 análisis IA / semana")
        real = LIMITS["pro"]["analyses_per_week"] // LIMITS["free"]["analyses_per_week"]
        self.assertIn(f"{real}× más que Free", sub,
                      f"el catálogo dice otro múltiplo; el real es {real}× — «{sub}»")

    def test_el_multiplo_contra_plus_es_el_real(self):
        sub = self._sub_de("pro", "60 análisis IA / semana")
        real = LIMITS["pro"]["analyses_per_week"] // LIMITS["plus"]["analyses_per_week"]
        self.assertIn(f"{real}× que Plus", sub,
                      f"el catálogo dice otro múltiplo; el real es {real}× — «{sub}»")


class LoQueTodaviaNoExisteNoSeVende(unittest.TestCase):
    """El catálogo separa `roadmap` de las features activas, y avisa en un
    comentario que NUNCA van mezcladas. El muro las mezcló: vendía "carpeta de
    impuestos" (que en el catálogo es el roadmap `Tax helper AFIP`) como si
    fuera una feature de Pro."""

    MURO = os.path.join(os.path.dirname(BACKEND), "frontend", "src",
                        "components", "plan", "MuroElegirPlan.jsx")

    def test_el_muro_no_escribe_features_a_mano(self):
        fuente = open(self.MURO, encoding="utf-8").read()
        self.assertIn("from '../../data/planCatalog'", fuente,
                      "el muro tiene que leer las features del catálogo")

    def test_el_muro_no_promete_el_roadmap(self):
        fuente = open(self.MURO, encoding="utf-8").read()
        # Se buscan en el JSX, no en los comentarios (que sí nombran el bug).
        jsx = "\n".join(l for l in fuente.splitlines()
                        if not l.lstrip().startswith(("//", "*", "/*")))
        for promesa in ("carpeta de impuestos", "calendario de cobros",
                        "sin límite de análisis"):
            self.assertNotIn(
                promesa.lower(), jsx.lower(),
                f"el muro volvió a prometer «{promesa}», que no existe o no es así")


if __name__ == "__main__":
    unittest.main()
