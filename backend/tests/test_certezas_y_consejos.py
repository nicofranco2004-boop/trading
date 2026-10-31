"""Lo que la IA técnica no puede decir: UNA lista para el chat y el resumen.

Auditoría final (31/10, B1+B2): el chat de Mervall-E (ai/lectura_tecnica_chat)
y el resumen de la ficha (ai/resumen_tecnico) tenían cada uno su lista de
certezas y consejos, y las dos dejaban pasar consejos de operar dichos de otra
forma («Conviene comprar», «Yo vendería», «Es hora de salir»…). Ahora las dos
revisiones leen la misma lista (ai/certezas_y_consejos.py).

Se prueba con las funciones que usa producción para decidir si un texto se
publica: `lectura_tecnica_chat.problemas` (la llama main._corregir_lectura_tecnica
en los cuatro finales del chat) y `resumen_tecnico.problemas` (la llama
resumen_tecnico.generar antes de guardar). El recorrido HTTP entero de cada una
está en test_lectura_tecnica_chat.py y test_resumen_tecnico.py.

Corre con: cd backend && python3 -m pytest tests/test_certezas_y_consejos.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from ai import lectura_tecnica_chat as ltc
from ai import resumen_tecnico

# Las que encontró la auditoría (sondas auditB/probe_filtros y probe_resumen).
CONSEJOS_DE_LA_AUDITORIA = [
    "Conviene comprar ahora que la tendencia de fondo es alcista.",
    "Sería prudente vender una parte y tomar ganancias.",
    "Yo vendería antes de que siga cayendo.",
    "Para quien no lo tiene, puede ser un buen punto para entrar.",
    "Lo razonable es mantener la posición y sumar en las bajas.",
    "Lo mejor es esperar a que pase su promedio de 200 días antes de comprar.",
    "Podés aprovechar para acumular.",
    "Es hora de salir.",
    "Es hora de salir y tomar ganancias.",
    "Lo prudente sería reducir la posición.",
]
CERTEZAS_DE_LA_AUDITORIA = [
    "La suba continúa: el precio subiría hasta 50.",
    "El precio probablemente siga subiendo.",
]
# Otras formas del mismo consejo.
OTRAS_FORMAS = [
    "Te conviene esperar.", "Comprá ahora.", "Vendelo.", "Tomá ganancias.", "Yo compraría acá.",
    "Te diría que vendas.", "Convendría desarmar la posición.", "Es momento de entrar.",
    "Lo ideal sería comprarla en las bajas.", "Deberías vender.", "Recomiendo mantener.",
    "Yo que vos espero.", "Es un buen punto de entrada.", "Habría que reducir.",
]
# Textos que describen y tienen que pasar en los dos (falsos positivos).
DESCRIPTIVOS = [
    "El precio salió del canal que venía siguiendo.",
    "Mantiene la tendencia de fondo alcista.",
    "La suba se mantiene, y la caída de octubre ya se deshizo.",
    "Entró en tendencia bajista en septiembre.",
    "Cerró en su precio más alto del año.",
    "Lo que se mira: si cierra por encima de su último pico, podría ser una señal de que la caída "
    "está perdiendo fuerza.",
    "La tendencia de fondo es bajista y la caída tiene fuerza aún, pero esa fuerza viene bajando.",
    "Mucha gente salió a vender en la última semana.",
    "Volvió a subir después de tocar su precio más bajo del año.",
    "Viene subiendo desde hace un tiempo y está arriba de su promedio de los últimos meses.",
]
# Sólo del chat: cosas de la app y la negación de lo que se preguntó.
DESCRIPTIVOS_DEL_CHAT = [
    "Podés entrar a la ficha para ver el gráfico completo.",
    "Podés sumarlo a tu lista para seguirlo.",
    "Hay que esperar al cierre de hoy para saberlo.",
    "No te puedo decir si conviene comprar: nadie sabe lo que viene.",
    "Tu compra fue a 40 dólares.",
]


def _consejo_o_certeza_en_el_resumen(texto):
    graves, _ = resumen_tecnico.problemas(texto, {"activo": "Microsoft"})
    return graves


class LaMismaListaEnLosDosTest(unittest.TestCase):

    def test_los_consejos_de_la_auditoria_no_pasan_en_ninguno(self):
        for t in CONSEJOS_DE_LA_AUDITORIA + OTRAS_FORMAS:
            with self.subTest(texto=t):
                chat = ltc.problemas(t, "¿cómo viene GGAL?")
                self.assertTrue(any("le dijiste qué hacer" in p for p in chat), (t, chat))
                self.assertTrue(_consejo_o_certeza_en_el_resumen(t), t)

    def test_las_certezas_de_la_auditoria_no_pasan_en_ninguno(self):
        for t in CERTEZAS_DE_LA_AUDITORIA:
            with self.subTest(texto=t):
                chat = ltc.problemas(t, "¿cómo viene GGAL?")
                self.assertTrue(any("como seguro" in p for p in chat), (t, chat))
                graves = _consejo_o_certeza_en_el_resumen(t)
                self.assertTrue(any("como seguro" in g for g in graves), (t, graves))

    def test_lo_que_describe_pasa_en_los_dos(self):
        for t in DESCRIPTIVOS:
            with self.subTest(texto=t):
                self.assertEqual(ltc.problemas(t, "¿cómo viene GGAL?"), [], t)
                # El resumen tiene además su propia lista, más estricta («vender»
                # a secas, «hoy»): acá sólo importa que la parte común no lo frene.
                comun = [g for g in _consejo_o_certeza_en_el_resumen(t)
                         if "números" not in g and "palabras prohibidas" not in g]
                self.assertEqual(comun, [], t)
        for t in DESCRIPTIVOS_DEL_CHAT:
            with self.subTest(texto=t):
                self.assertEqual(ltc.problemas(t, "¿Conviene comprar GGAL?"), [], t)

    def test_repetir_la_pregunta_no_exime_un_consejo(self):
        """Una certeza que repite la pregunta no predice («la semana que viene»);
        un consejo que la repite, sí aconseja: «¿Conviene comprar?» → «Conviene
        comprar» no pasa."""
        self.assertTrue(ltc.problemas("Conviene comprar ahora.", "¿Conviene comprar GGAL?"))

    def test_el_resumen_no_tiene_una_lista_propia_de_certezas(self):
        """La parte compartida vive en un solo lugar: el resumen no repite en su
        lista las frases que ya revisa el módulo común."""
        from ai import certezas_y_consejos as cc
        for repetida in ("seguramente", "sin duda", "con seguridad", "seguro que"):
            self.assertNotIn(repetida, resumen_tecnico._PROHIBIDAS)
            self.assertIn(repetida, cc.CERTEZAS)
        self.assertFalse(hasattr(ltc, "_CERTEZAS"), "el chat lee la lista común")
        self.assertFalse(hasattr(ltc, "_CONSEJOS"), "el chat lee la lista común")


if __name__ == "__main__":
    unittest.main()
