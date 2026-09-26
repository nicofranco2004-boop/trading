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


class LosDiasDeLaPruebaQueDiceLaLANDING(unittest.TestCase):
    """La landing es PÚBLICA: no hay sesión, así que no puede preguntarle los
    días de la prueba al backend como hace la app. Los tiene escritos en
    `planCatalog.js`, y sin este test nadie se enteraría el día que la prueba
    cambie de largo: la home seguiría ofreciendo 20 días para siempre."""

    def _const_del_catalogo(self, nombre: str) -> int:
        fuente = open(CATALOGO, encoding="utf-8").read()
        m = re.search(r"export const %s = (\d+)" % re.escape(nombre), fuente)
        assert m, f"no encontré {nombre} en planCatalog.js"
        return int(m.group(1))

    def test_el_total_coincide_con_el_backend(self):
        from billing.trial import TRIAL_TOTAL_DAYS
        self.assertEqual(
            self._const_del_catalogo("TRIAL_TOTAL_DAYS"), TRIAL_TOTAL_DAYS,
            "la landing ofrece una cantidad de días que el backend no da")

    def test_las_dos_etapas_tambien(self):
        from billing.trial import TRIAL_PRO_DAYS, TRIAL_PLUS_DAYS
        self.assertEqual(self._const_del_catalogo("TRIAL_PRO_DAYS"), TRIAL_PRO_DAYS)
        self.assertEqual(self._const_del_catalogo("TRIAL_PLUS_DAYS"), TRIAL_PLUS_DAYS)

    def test_y_las_etapas_suman_el_total(self):
        """Contra el falso verde: los tres podrían coincidir con el backend y
        no cerrar entre ellos si alguien toca sólo uno en los dos lados."""
        self.assertEqual(
            self._const_del_catalogo("TRIAL_PRO_DAYS")
            + self._const_del_catalogo("TRIAL_PLUS_DAYS"),
            self._const_del_catalogo("TRIAL_TOTAL_DAYS"))

    def test_el_html_estatico_dice_los_mismos_dias(self):
        """`index.html` trae un bloque para los que no corren JavaScript (el
        scraper de WhatsApp, el de Facebook, Googlebot en cola) que dice
        "Probar N días gratis". Es HTML estático: no puede importar el catálogo,
        así que el número está a mano y sólo esto lo ata al backend."""
        from billing.trial import TRIAL_TOTAL_DAYS
        html = open(os.path.join(os.path.dirname(BACKEND), "frontend", "index.html"),
                    encoding="utf-8").read()
        dias = re.findall(r"(\d+) días gratis", html)
        self.assertTrue(dias, "index.html ya no menciona la prueba: revisar este test")
        for d in dias:
            self.assertEqual(
                int(d), TRIAL_TOTAL_DAYS,
                f"index.html ofrece {d} días gratis y la prueba es de {TRIAL_TOTAL_DAYS}")


class ElPRECIOQueLeeGOOGLE(unittest.TestCase):
    """`frontend/index.html` lleva un bloque JSON-LD con los precios, y eso es
    lo que Google puede mostrar en los resultados de búsqueda. Es HTML estático:
    no puede importar `src/data/pricing.js`, así que los números están a mano.

    Estaban ofreciendo el plan Free y los precios en DÓLARES VIEJOS ($4 y $9)
    — el precio real está en pesos y hace meses que es otro. Nadie se enteró
    porque un dato estructurado desactualizado no produce ningún error: sale
    mal en Google y calla."""

    INDEX = os.path.join(os.path.dirname(BACKEND), "frontend", "index.html")

    def _ofertas(self) -> dict:
        import json
        s = open(self.INDEX, encoding="utf-8").read()
        i = s.index("application/ld+json")
        j = s.index("</script>", i)
        d = json.loads(s[s.index("{", i):j])
        return {o["name"]: o for o in d.get("offers", [])}

    def test_el_json_ld_es_json_valido(self):
        """Un comentario HTML adentro del <script> rompe el bloque entero y
        Google deja de leerlo. Ya pasó una vez, escribiéndolo."""
        self._ofertas()      # revienta si el JSON está roto

    def test_los_precios_son_los_del_backend_y_en_pesos(self):
        from billing.pricing import PLUS_ARS_MONTHLY_TOTAL, ARS_MONTHLY_TOTAL
        ofertas = self._ofertas()
        for nombre, real in (("Plus", PLUS_ARS_MONTHLY_TOTAL),
                             ("Pro", ARS_MONTHLY_TOTAL)):
            self.assertIn(nombre, ofertas, "falta la oferta en el JSON-LD")
            self.assertEqual(
                ofertas[nombre]["price"], str(real),
                f"Google muestra {ofertas[nombre]['price']} para {nombre} y el "
                f"precio real es {real}")
            self.assertEqual(
                ofertas[nombre]["priceCurrency"], "ARS",
                "se cobra en pesos; el JSON-LD dice otra moneda")

    def test_ya_no_se_ofrece_el_plan_free(self):
        """Quien se registra de ahora en adelante no tiene plan gratis: la home
        no puede ofrecerlo, y menos en el dato que lee Google."""
        self.assertNotIn("Free", self._ofertas())


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
