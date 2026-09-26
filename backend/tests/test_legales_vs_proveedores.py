"""Los legales nombran a cada proveedor de IA al que el backend le manda datos.

Por qué existe: la voz y el dictado de Rendi AI le mandan datos a OpenAI —el
texto de una respuesta para leerla en voz alta, y la grabación de lo que el
usuario dicta, con los nombres de sus activos y brokers—. La Política de
Privacidad lo declaraba; los Términos no lo nombraron nunca, ni en la definición
de Rendi AI ni entre los Terceros, y nadie se enteró: un proveedor que falta en
un texto legal no rompe nada ni tira ningún error. Se agregó el 2026-09-26.

A quién le habla el backend se lee del CÓDIGO (el host de la API o el import
del SDK), no de una lista escrita a mano. Y al revés: si un proveedor de la
tabla deja de usarse, el test también avisa, porque los legales pasarían a
nombrar a alguien que ya no recibe nada.

El mismo criterio que `frontend/src/pages/Privacidad.test.js`: no verifica que
el texto esté bien redactado —eso lo lee una persona—, verifica que los HECHOS
que afirma sigan siendo los hechos.

Corre con: cd backend && python3 -m pytest tests/test_legales_vs_proveedores.py
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
PAGINAS = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "pages")

# Cómo se reconoce en el código que el backend le habla a cada proveedor de IA.
PROVEEDORES_DE_IA = {
    "Anthropic": re.compile(r"api\.anthropic\.com|^\s*(?:import|from)\s+anthropic\b", re.M),
    "OpenAI": re.compile(r"api\.openai\.com|^\s*(?:import|from)\s+openai\b", re.M),
}
# Los tests los nombran a propósito; los scripts no corren en producción.
NO_SE_LEEN = {"tests", "scripts", "__pycache__", "node_modules", "venv"}


def _usados() -> dict:
    """{proveedor: [archivos del backend que le hablan]}, según el código de hoy."""
    usados = {}
    for raiz, dirs, archivos in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in NO_SE_LEEN and not d.startswith(".")]
        for a in archivos:
            if not a.endswith(".py"):
                continue
            ruta = os.path.join(raiz, a)
            with open(ruta, encoding="utf-8") as f:
                src = f.read()
            for nombre, patron in PROVEEDORES_DE_IA.items():
                if patron.search(src):
                    usados.setdefault(nombre, []).append(os.path.relpath(ruta, BACKEND))
    return usados


def _texto(s: str) -> str:
    """Como lo lee la persona: sin etiquetas, sin `{' '}` y sin cortes de línea."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s.replace("{' '}", " ")))


class LosLegalesNombranALaIA(unittest.TestCase):

    def _seccion(self, pagina: str, numero: int) -> str:
        """El texto de la sección `numero` de una página legal, hasta la siguiente."""
        src = open(os.path.join(PAGINAS, pagina), encoding="utf-8").read()
        desde = src.find('<Section title="%d. ' % numero)
        hasta = src.find('<Section title="%d. ' % (numero + 1), desde)
        self.assertNotEqual(desde, -1, f"{pagina} ya no tiene la sección {numero}: revisar este test")
        self.assertNotEqual(hasta, -1, f"{pagina} ya no tiene la sección {numero + 1}: revisar este test")
        return _texto(src[desde:hasta])

    def test_la_tabla_es_la_de_hoy(self):
        """Cada proveedor de la tabla se sigue usando. Si uno se deja de usar,
        los legales nombrarían a alguien que ya no recibe datos."""
        usados = _usados()
        for nombre in PROVEEDORES_DE_IA:
            self.assertIn(nombre, usados,
                          f"el backend ya no le habla a {nombre}: sacalo de la tabla y "
                          f"revisá qué dicen Términos y Privacidad")
        # La voz (tts.py) y el dictado (oido.py) son los que le hablan a OpenAI.
        self.assertIn(os.path.join("ai", "tts.py"), usados["OpenAI"])
        self.assertIn(os.path.join("ai", "oido.py"), usados["OpenAI"])

    def test_terminos_los_nombra_en_la_definicion_y_entre_los_terceros(self):
        definiciones = self._seccion("Terminos.jsx", 1)
        terceros = self._seccion("Terminos.jsx", 11)
        for nombre in _usados():
            self.assertIn(nombre, definiciones, f"Términos §1 (qué es Rendi AI) no nombra a {nombre}")
            self.assertIn(nombre, terceros, f"Términos §11 (Terceros) no nombra a {nombre}")

    def test_privacidad_los_nombra_entre_con_quien_compartimos(self):
        compartimos = self._seccion("Privacidad.jsx", 5)
        for nombre in _usados():
            self.assertIn(nombre, compartimos, f"Privacidad §5 no nombra a {nombre}")

    def test_los_dos_dicen_el_mismo_plazo_de_openai(self):
        """OpenAI guarda lo que recibe un tiempo para controlar abusos. Si ese
        plazo cambia y se corrige un legal y no el otro, se contradicen."""
        terminos = re.search(r"OpenAI los guarda hasta (\d+) días", self._seccion("Terminos.jsx", 11))
        privacidad = re.search(r"queda hasta (\d+) días", self._seccion("Privacidad.jsx", 4))
        self.assertTrue(terminos, "Términos §11 ya no dice cuánto guarda OpenAI: revisar este test")
        self.assertTrue(privacidad, "Privacidad §4 ya no dice cuánto guarda OpenAI: revisar este test")
        self.assertEqual(terminos.group(1), privacidad.group(1),
                         "Términos y Privacidad dicen plazos distintos de OpenAI")


if __name__ == "__main__":
    unittest.main()
