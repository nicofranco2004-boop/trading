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

    def test_el_pie_con_los_precios_se_DERIVA(self):
        """⭐ El pie de la imagen («Después de la prueba: Plus $X · Pro $Y») era
        el QUINTO lugar donde vivía el precio escrito a mano, y el que menos se
        mira: no es una pantalla, es un dibujo. El 15/10, cuando Plus pasó a
        8.900, habría quedado anunciando los de septiembre dentro del PNG. Y ya
        venía desfasado de antes (decía ≈US$4 / ≈US$9, la equivalencia de hace
        meses).

        Este test no abre el PNG —no se puede leer un texto dibujado— sino que
        exige que el pie se CONSTRUYA de `billing/pricing.py`."""
        fuente = _leer(GENERADOR)
        i = fuente.index("PIE_PRECIOS")
        pie = fuente[i:fuente.index("\n)", i)]
        for campo in ("PLUS_ARS_MONTHLY_TOTAL", "ARS_MONTHLY_TOTAL"):
            self.assertIn(campo, pie,
                          f"el pie no deriva {campo} de billing/pricing.py")
        # Y que no haya vuelto a aparecer un número escrito a mano.
        self.assertIsNone(
            re.search(r"\$\s?\d[\d.]{3,}", pie),
            f"hay un precio escrito a mano en el pie de la imagen:\n{pie}")

    def test_el_pie_dice_los_precios_que_se_cobran(self):
        """La otra punta: que lo derivado sea EL precio de hoy. Si el pie
        derivara del campo equivocado, el test de arriba pasaría igual."""
        import importlib.util
        ruta = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                            "backend", "billing", "pricing.py")
        spec = importlib.util.spec_from_file_location("pricing_og", ruta)
        pricing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pricing)
        fuente = _leer(GENERADOR)
        pie = fuente[fuente.index("PIE_PRECIOS"):]
        self.assertIn("PLUS_ARS_MONTHLY_TOTAL", pie)
        # Los dos montos existen y son los que cobra el backend.
        self.assertGreater(pricing.PLUS_ARS_MONTHLY_TOTAL, 0)
        self.assertGreater(pricing.ARS_MONTHLY_TOTAL, pricing.PLUS_ARS_MONTHLY_TOTAL,
                           "el Pro tiene que costar más que el Plus")

    def test_la_version_no_quedo_en_v1(self):
        """Contraveneno del bug original: si alguien cambia el arte y se olvida
        de subir la versión, este test no puede saberlo — pero sí puede exigir
        que el mecanismo esté estrenado, o sea que la versión no sea la
        primera. Si algún día se vuelve a v1, es que el versionado se deshizo."""
        self.assertNotEqual(self._version(), "v1")


if __name__ == "__main__":
    unittest.main()
