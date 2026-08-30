"""Ronda 11: la cota de cordura sobre el PICO.

La familia de bugs de las diez rondas anteriores pregunta siempre lo mismo: CON QUÉ
REGLA se midió este número. Eso funciona. Lo que nunca se preguntó es si el
resultado es POSIBLE: una fila puede estar impecablemente etiquetada
(`source='cron'`, MEDICION, `base='mercado'`, `apto=1`) y aun así decir que una
cartera de US$108,96 valió US$16.229.949. Contra ese pico se mide "cuánto cayó", y
sale por mail al asesor: "su ganancia cayó 492.864% desde el mejor momento".

Estos tests fijan las dos mitades de la decisión del dueño:
  1. la alerta NO se emite cuando el pico es implausible, y
  2. lo silenciado queda en la cola de admin (no se esconde).

Y sobre todo fijan lo que NO se puede romper: las alertas plausibles siguen saliendo.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
from main import _pico_es_plausible, PICO_MAX_VECES_LA_CARTERA


class ClampPicoTest(unittest.TestCase):
    """El criterio puro: ¿este pico es posible contra la cartera de hoy?"""

    def test_una_cartera_normal_pasa(self):
        # Lo habitual: el pico está por encima del valor de hoy, pero en un orden
        # de magnitud que existe. Estas son las que TIENEN que seguir saliendo.
        self.assertTrue(_pico_es_plausible(1_500, 1_000))       # 1,5x
        self.assertTrue(_pico_es_plausible(12_000, 10_000))     # 1,2x
        self.assertTrue(_pico_es_plausible(41_800, 10_000))     # 4,18x — el sobreviviente
        #                                                         más extremo de producción

    def test_el_pico_imposible_no_pasa(self):
        # uid 513 de producción: pico US$16.229.949 contra una cartera de US$108,96.
        self.assertFalse(_pico_es_plausible(16_229_949.43, 108.96))
        # uid 557, el dato roto MÁS SUAVE que hay: 10,16x. Tiene que caer igual.
        self.assertFalse(_pico_es_plausible(341_371.37, 33_591.06))

    def test_el_umbral_cae_dentro_de_la_banda_vacia(self):
        # Medido sobre la copia de producción: los ratios saltan de 4,18x a 10,16x
        # sin un solo usuario en el medio. El umbral tiene que vivir ahí adentro —
        # si algún día alguien lo mueve fuera de la banda, este test lo frena.
        self.assertGreater(PICO_MAX_VECES_LA_CARTERA, 4.18)
        self.assertLess(PICO_MAX_VECES_LA_CARTERA, 10.16)

    def test_el_borde_exacto_es_plausible(self):
        # `<=` y no `<`: justo en el umbral todavía se publica. Importa porque el
        # sesgo elegido es no silenciar de más.
        self.assertTrue(_pico_es_plausible(8_000, 1_000))
        self.assertFalse(_pico_es_plausible(8_000.01, 1_000))

    def test_cartera_en_cero_o_negativa_es_implausible(self):
        # 6 usuarios en producción. Con la cartera en 0 el cociente es infinito; con
        # la cartera NEGATIVA (uid 396: −US$2.613.820) el cociente cambia de signo y
        # un `> umbral` lo dejaría pasar como si fuera plausible. Por eso la guarda
        # es explícita y va primero.
        self.assertFalse(_pico_es_plausible(9_472.57, 0.0))
        self.assertFalse(_pico_es_plausible(872_937.48, -2_613_820.97))
        self.assertFalse(_pico_es_plausible(500, None))

    def test_mide_una_relacion_y_no_un_valor(self):
        # "Más de un millón" no serviría: hay carteras de un millón. Un pico de
        # US$8.000.000 sobre una cartera de US$5.000.000 es perfectamente posible;
        # uno de US$8.000 sobre una de US$100 no lo es.
        self.assertTrue(_pico_es_plausible(8_000_000, 5_000_000))
        self.assertFalse(_pico_es_plausible(8_000, 100))


class ClampNoTocaElDatoTest(unittest.TestCase):
    """El clamp decide QUÉ SE PUBLICA, no qué está guardado."""

    def test_es_una_funcion_pura(self):
        # Sin conexión, sin escritura, sin efectos. Si algún día alguien la hace
        # "corregir" el snapshot, la firma deja de cerrar y este test lo dice.
        import inspect
        firma = inspect.signature(_pico_es_plausible)
        self.assertEqual(list(firma.parameters), ["adj_mx", "total_value"])


class ColaDeRevisionTest(unittest.TestCase):
    """Silenciar sin registrar sería esconder el problema."""

    def test_el_endpoint_de_diagnostico_expone_la_cola(self):
        src = inspect_source(main.admin_diagnose_reportes_basis)
        self.assertIn("picos_implausibles", src)
        # La cola tiene que recalcular con la MISMA función que corre en la alerta;
        # un diagnóstico que reimplemente el criterio mide otra cosa.
        self.assertIn("_pico_es_plausible", src)

    def test_la_alerta_usa_la_misma_funcion(self):
        src = inspect_source(main.advisor_book)
        self.assertIn("_pico_es_plausible", src)
        # Y sigue conviviendo con la cota que ya estaba (piso de US$500).
        self.assertIn('adj_mx"] >= 500', src)


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)


if __name__ == "__main__":
    unittest.main()
