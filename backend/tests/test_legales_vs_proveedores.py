"""Los legales dicen a qué proveedor de IA le llegan datos, y QUÉ le llega.

Por qué existe: la voz y el dictado de Mervall-E AI le mandan datos a OpenAI —el
resumen hablado de una respuesta para leerla en voz alta, y la grabación de lo
que el usuario dicta, con los códigos y nombres de sus activos y brokers—. La
Política de Privacidad lo declaraba; los Términos no lo nombraron nunca, ni en
la definición de Mervall-E AI ni entre los Terceros, y nadie se enteró: un proveedor
que falta en un texto legal no rompe nada ni tira ningún error. Se agregó el
2026-09-26 (y ese mismo día se corrigió que la voz viene PRENDIDA, no a pedido:
eso lo vigila `frontend/src/pages/Privacidad.test.js`).

Qué es a mano y qué se lee del código, para no mentir en este docstring:
  · la TABLA de proveedores es a mano (dos: Anthropic y OpenAI); lo que se lee
    del código es si cada uno se sigue usando, y dónde;
  · QUÉ le llega a OpenAI se mide pasando por las mismas funciones que usa
    producción (`tts.speak`, `oido.escuchar`), con el cliente HTTP reemplazado;
  · que el navegador no le mande la voz a un tercero MÁS (Google o Apple, con
    su reconocimiento propio) se lee del código del frontend.

Límite declarado: un proveedor nuevo que no esté en la tabla y se llame por un
camino que nadie reconoce (una URL armada por partes) no lo ve este test.

El mismo criterio que `Privacidad.test.js`: no verifica que el texto esté bien
redactado —eso lo lee una persona—, verifica que los HECHOS que afirma sigan
siendo los hechos.

Corre con: cd backend && python3 -m pytest tests/test_legales_vs_proveedores.py
"""
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
FRONTEND = os.path.join(os.path.dirname(BACKEND), "frontend")
PAGINAS = os.path.join(FRONTEND, "src", "pages")

# Cómo se reconoce en el código que el backend le habla a cada proveedor de IA.
PROVEEDORES_DE_IA = {
    "Anthropic": re.compile(r"api\.anthropic\.com|^\s*(?:import|from)\s+anthropic\b", re.M),
    "OpenAI": re.compile(r"api\.openai\.com|^\s*(?:import|from)\s+openai\b", re.M),
}
# Los tests los nombran a propósito; los scripts no corren en producción.
NO_SE_LEEN = {"tests", "scripts", "__pycache__", "node_modules", "venv"}
# El plazo que OpenAI guarda lo que recibe, en cualquiera de las formas en que
# lo dicen los legales ("OpenAI los guarda hasta", "lo retiene hasta", "queda hasta").
_PLAZO = re.compile(r"(?:guarda|retiene|queda) hasta (\d+) días")


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
    """Como lo lee la persona: sin comentarios (un párrafo comentado no lo ve
    nadie), sin etiquetas, sin `{' '}` y sin cortes de línea."""
    s = re.sub(r"\{/\*.*?\*/\}", " ", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s.replace("{' '}", " ")))


def _pagina(nombre: str) -> str:
    with open(os.path.join(PAGINAS, nombre), encoding="utf-8") as f:
        return f.read()


class LosLegalesNombranALaIA(unittest.TestCase):

    def _seccion(self, pagina: str, titulo: str) -> str:
        """El texto de la sección que se llama `titulo` (por su título, no por su
        número: si alguien renumera, esto sigue mirando la sección correcta)."""
        src = _pagina(pagina)
        m = re.search(r'<Section title="\d+\. ' + re.escape(titulo), src)
        self.assertTrue(m, f"{pagina} ya no tiene la sección «{titulo}»: revisar este test")
        fin = src.find("<Section title=", m.end())
        return _texto(src[m.start():fin if fin != -1 else len(src)])

    def test_la_tabla_es_la_de_hoy(self):
        """Cada proveedor de la tabla se sigue usando: si uno se dejara de usar,
        los legales nombrarían a alguien que ya no recibe nada."""
        usados = _usados()
        for nombre in PROVEEDORES_DE_IA:
            self.assertIn(nombre, usados,
                          f"no encuentro cómo el backend le habla a {nombre}: revisá el "
                          f"patrón de la tabla. Sacalo sólo si de verdad dejó de usarse, "
                          f"y en ese caso revisá qué dicen Términos y Privacidad")
        # La voz (tts.py) y el dictado (oido.py) son los que le hablan a OpenAI.
        self.assertIn(os.path.join("ai", "tts.py"), usados["OpenAI"])
        self.assertIn(os.path.join("ai", "oido.py"), usados["OpenAI"])

    def test_terminos_los_nombra_en_la_definicion_y_entre_los_terceros(self):
        definiciones = self._seccion("Terminos.jsx", "Definiciones")
        terceros = self._seccion("Terminos.jsx", "Servicios y datos de terceros")
        for nombre in _usados():
            self.assertIn(nombre, definiciones, f"Términos (qué es Mervall-E AI) no nombra a {nombre}")
            self.assertIn(nombre, terceros, f"Términos (Terceros) no nombra a {nombre}")

    def test_privacidad_los_nombra_entre_con_quien_compartimos(self):
        compartimos = self._seccion("Privacidad.jsx", "Con quién compartimos")
        for nombre in _usados():
            self.assertIn(nombre, compartimos, f"Privacidad (con quién compartimos) no nombra a {nombre}")

    def test_un_parrafo_comentado_no_cuenta(self):
        """Comentar un párrafo es la forma habitual de esconderlo "por un rato":
        la persona deja de verlo, y el test también tiene que dejar de verlo."""
        self.assertNotIn("OpenAI", _texto("<li>{/* <strong>OpenAI</strong> recibe… */}</li>"))

    def test_todas_las_veces_que_dicen_el_plazo_de_openai_dicen_el_mismo(self):
        """OpenAI guarda lo que recibe un tiempo para controlar abusos. Lo dicen
        el resumen de Privacidad, su §4 y los Términos: si el plazo cambia y se
        corrige uno solo, se contradicen."""
        plazos = [d for p in ("Terminos.jsx", "Privacidad.jsx")
                  for d in _PLAZO.findall(_texto(_pagina(p)))]
        self.assertGreaterEqual(len(plazos), 3, f"se esperaban al menos 3 menciones del plazo: {plazos}")
        self.assertEqual(len(set(plazos)), 1, f"los legales dicen plazos distintos de OpenAI: {plazos}")


class LoQueLeLlegaAOpenAI(unittest.TestCase):
    """Los legales dicen QUÉ le llega a OpenAI: el texto a leer; la grabación con
    la ayuda de vocabulario. Esto lo mide por el mismo camino que producción: si
    alguien le suma al pedido el email o un identificador de la persona, rojo."""

    def test_lo_que_viaja_al_leer_y_al_dictar(self):
        from ai import oido, tts
        visto = {}

        class _Corte(Exception):
            pass

        class _ClienteFalso:
            def stream(self, metodo, url, json=None, headers=None):
                visto["leer"] = (json, headers)
                raise _Corte

            def post(self, url, headers=None, data=None, files=None):
                visto["dictar"] = (data, files, headers)
                raise _Corte

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-no-se-usa"}), \
                mock.patch.object(tts, "_client", _ClienteFalso), \
                mock.patch.object(oido, "_client", _ClienteFalso):
            with self.assertRaises(_Corte):
                list(tts.speak("Tu cartera subió 2 %."))
            with self.assertRaises(_Corte):
                oido.escuchar(b"audio", "audio/webm", pista=oido.pista(["NVDA"], ["Balanz"]))

        cuerpo, cabeceras = visto["leer"]
        self.assertEqual(set(cuerpo), {"model", "voice", "input", "instructions", "response_format"})
        self.assertEqual(cuerpo["input"], "Tu cartera subió 2 %.")
        self.assertEqual(set(cabeceras), {"Authorization", "Content-Type"})

        datos, archivos, cabeceras = visto["dictar"]
        self.assertEqual(set(datos), {"model", "language", "response_format", "prompt"})
        self.assertEqual(set(archivos), {"file"})
        self.assertEqual(set(cabeceras), {"Authorization"})
        self.assertIn("NVDA", datos["prompt"])
        self.assertIn("Balanz", datos["prompt"])


class ElNavegadorNoLeMandaLaVozAOtroTercero(unittest.TestCase):
    """`ai/oido.py` explica por qué el dictado va por OpenAI y no por el
    reconocimiento de voz del navegador: ése le manda la voz a Google (Chrome) o
    a Apple (Safari), terceros que no están en ningún legal. Si alguien lo usa
    "porque es gratis", los legales pasan a mentir sin que cambie una línea suya."""

    def test_el_frontend_no_usa_el_reconocimiento_ni_la_sintesis_del_navegador(self):
        patron = re.compile(r"\b(?:webkit)?SpeechRecognition\b|\bspeechSynthesis\b")
        hallazgos = []
        for raiz, dirs, archivos in os.walk(os.path.join(FRONTEND, "src")):
            dirs[:] = [d for d in dirs if d != "node_modules"]
            for a in archivos:
                if a.endswith((".js", ".jsx", ".ts", ".tsx")) and ".test." not in a:
                    with open(os.path.join(raiz, a), encoding="utf-8") as f:
                        for i, linea in enumerate(f, 1):
                            if patron.search(linea):
                                hallazgos.append(f"{os.path.relpath(os.path.join(raiz, a), FRONTEND)}:{i}")
        self.assertEqual(hallazgos, [],
                         "el navegador le mandaría la voz a Google o Apple, que no están en "
                         "Términos ni en Privacidad (ver el docstring de ai/oido.py)")


if __name__ == "__main__":
    unittest.main()
