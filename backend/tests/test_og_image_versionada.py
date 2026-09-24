"""La imagen del link: el nombre versionado tiene que decir lo mismo en los tres lados.

POR QUÉ EXISTE ESTE ARCHIVO. El 2026-09-24 Nico mandó una captura de cómo se
veía rendi.finance compartido en X: el dibujo VIEJO, el que ofrecía un plan
gratis y precios en dólares de hace meses. La imagen nueva estaba servida y
correcta —verificado bajándola de producción—, pero las redes la cachean POR
URL, y el nombre del archivo no había cambiado. X, además, no tiene desde que
retiró el Card Validator ninguna forma de pedirle que vuelva a leer: su copia
vieja vive días.

O sea: con el nombre fijo, cambiar el arte no cambia NADA de lo que ve la
gente. La única forma de forzarlo es que la URL sea otra.

Y de ahí el riesgo que este test cubre: el nombre vive en TRES archivos que no
se pueden importar entre sí —un script de Python, un HTML estático y un
componente de React—, así que subir la versión en dos de los tres deja el sitio
declarando una imagen que no existe. Eso no da error en ninguna parte: la red
no encuentra nada y muestra el link pelado, sin tarjeta.

Corre con: cd backend && python3 -m pytest tests/test_og_image_versionada.py
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "frontend")
if not os.path.isdir(FRONT):     # layout de worktree
    FRONT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "frontend")

GENERADOR = os.path.join(FRONT, "scripts", "generate-og-image.py")
INDEX = os.path.join(FRONT, "index.html")
PAGEMETA = os.path.join(FRONT, "src", "components", "PageMeta.jsx")
PUBLIC = os.path.join(FRONT, "public")


def _leer(p):
    return open(p, encoding="utf-8").read()


class ElNombreDeLaImagenDelLink(unittest.TestCase):

    def setUp(self):
        for p in (GENERADOR, INDEX, PAGEMETA):
            self.assertTrue(os.path.exists(p), f"no encontré {p}")

    def _version(self) -> str:
        m = re.search(r"^OG_VERSION\s*=\s*'([^']+)'", _leer(GENERADOR), re.M)
        self.assertIsNotNone(m, "el generador no declara OG_VERSION")
        return m.group(1)

    def _archivo(self) -> str:
        return f"og-image-{self._version()}.png"

    def test_el_archivo_que_el_generador_escribe_existe(self):
        """Sin esto, el sitio declara una imagen que no está: la red no
        encuentra nada y muestra el link pelado, sin tarjeta y sin error."""
        self.assertTrue(
            os.path.exists(os.path.join(PUBLIC, self._archivo())),
            f"falta {self._archivo()} en public/ — corré "
            f"`python3 frontend/scripts/generate-og-image.py`")

    def test_los_dos_metas_del_html_apuntan_ahi(self):
        html = _leer(INDEX)
        for prop in ('property="og:image"', 'name="twitter:image"'):
            m = re.search(r'<meta %s content="([^"]+)"' % re.escape(prop), html)
            self.assertIsNotNone(m, f"falta el meta {prop}")
            self.assertTrue(
                m.group(1).endswith("/" + self._archivo()),
                f"{prop} apunta a «{m.group(1)}» y el generador escribe "
                f"«{self._archivo()}»")

    def test_el_default_de_react_apunta_ahi(self):
        m = re.search(r"const DEFAULT_OG_IMAGE = '([^']+)'", _leer(PAGEMETA))
        self.assertIsNotNone(m, "PageMeta.jsx no declara DEFAULT_OG_IMAGE")
        self.assertEqual(m.group(1), "/" + self._archivo())

    def test_la_imagen_vieja_sigue_estando(self):
        """Los posteos que ya salieron apuntan al nombre anterior. Borrarlo les
        rompe la tarjeta retroactivamente, que es peor que dejar el archivo."""
        self.assertTrue(
            os.path.exists(os.path.join(PUBLIC, "og-image.png")),
            "se borró og-image.png: los links ya compartidos pierden la tarjeta")

    def test_la_version_no_quedo_en_v1(self):
        """Contraveneno del bug original: si alguien cambia el arte y se olvida
        de subir la versión, este test no puede saberlo — pero sí puede exigir
        que el mecanismo esté estrenado, o sea que la versión no sea la
        primera. Si algún día se vuelve a v1, es que el versionado se deshizo."""
        self.assertNotEqual(self._version(), "v1")


if __name__ == "__main__":
    unittest.main()
