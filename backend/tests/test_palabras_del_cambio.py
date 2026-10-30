"""D6 y D11 (auditoría D, 29/10): las palabras de cada cambio de «Tus señales»,
del mail y la notificación de los sábados y de la columna «Último cambio».

D6. El asunto decía «Tu semana: KO tiene el ADX en 23,0» y la notificación lo
mismo: `_titular` cortaba el texto en los dos puntos y se quedaba con la parte
técnica; la explicación («deja de ir de costado y marca dirección») quedaba
afuera. La pantalla («Último cambio» de Tu lista) hacía el mismo corte por su
lado. Ahora el servidor arma UNA frase corta que se entiende sola (`corta`) y
las dos la usan: ninguna corta nada.

D11. «Máximo del año · hace 5 semanas» cuando el último cierre en máximo fue hace una
semana: la regla (`tecnico.senal_desde('maximo_12m')`) marca el PRIMER máximo
después de un mes sin máximos (para no avisar todos los días mientras sube). La
regla queda —es la de la alerta— y el texto dice lo que mide: «empezó a marcar
máximos del año… después de un mes sin hacerlo», en la frase CORTA (la de la celda).

Corre con: cd backend && python3 -m pytest tests/test_palabras_del_cambio.py
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import senales_semana  # noqa: E402

CAMBIOS = [
    {"tipo": "media200", "sentido": "arriba"}, {"tipo": "media200", "sentido": "abajo"},
    {"tipo": "media50", "sentido": "arriba"}, {"tipo": "media50", "sentido": "abajo"},
    {"tipo": "rsi_bajo_30", "sentido": "abajo", "rsi": 28.4, "rsi_antes": 52},
    {"tipo": "rsi_sobre_70", "sentido": "arriba", "rsi": 73.1, "rsi_antes": None},
    {"tipo": "maximo_12m", "sentido": "arriba"},
    {"tipo": "adx23", "sentido": "arriba", "adx": 23.04, "squeeze": 1},
    {"tipo": "adx23", "sentido": "arriba", "adx": 31.2, "squeeze": -1},
    {"tipo": "adx23", "sentido": "arriba", "adx": 24.0, "squeeze": None},
]
JERGA = re.compile(r"\b(ADX|RSI|Squeeze)\b")


class CortaTest(unittest.TestCase):
    def test_cada_cambio_trae_una_frase_corta_sin_jerga_ni_numeros(self):
        for c in CAMBIOS:
            t = senales_semana.texto_del_cambio(c)
            self.assertIn("corta", t, c)
            self.assertNotRegex(t["corta"], JERGA, (c, t["corta"]))
            # Ningún número suelto (los «200 días» del promedio sí son palabras).
            self.assertNotRegex(t["corta"], r"\d(?!\d* días)", (c, t["corta"]))
            self.assertNotIn(":", t["corta"], (c, t["corta"]))

    def test_en_el_texto_entero_la_jerga_va_explicada(self):
        for c in CAMBIOS:
            t = senales_semana.texto_del_cambio(c)["texto"]
            for m in JERGA.finditer(t):
                antes = t[max(0, m.start() - 30):m.start()]
                self.assertIn("fuerza", antes, (c, t))

    def test_el_asunto_del_sabado_usa_la_frase_corta(self):
        def senal(c, asset="KO"):
            return {**c, **senales_semana.texto_del_cambio(c), "asset": asset, "tenes": True, "peso": 0.2}
        adx = senal(CAMBIOS[7])
        tit = senales_semana._titular([adx])
        self.assertEqual(tit, f"Tu semana: KO {adx['corta']}")
        self.assertNotRegex(tit, JERGA)
        self.assertNotRegex(tit, r"23,0")
        rsi = senal(CAMBIOS[4], "MELI")
        self.assertNotRegex(senales_semana._titular([rsi, adx]), JERGA)


class MaximoTest(unittest.TestCase):
    """D11 (re-test de la auditoría D): «Volvió a cerrar en su precio más alto del
    año · hace 5 semanas» se leía como que hace 5 semanas fue la ÚLTIMA vez (el
    último había sido hace una). La regla marca el PRIMERO de una racha: la frase
    corta, la que va sola en la celda y en el asunto, tiene que decir eso."""

    def test_el_maximo_dice_lo_que_mide_la_regla(self):
        t = senales_semana.texto_del_cambio({"tipo": "maximo_12m", "sentido": "arriba"})
        self.assertEqual(t["corta"], "empezó a marcar máximos del año")
        self.assertIn("empezó a marcar máximos del año", t["texto"])
        self.assertIn("los últimos 12 meses", t["texto"])
        self.assertIn("después de un mes sin hacerlo", t["texto"])
        self.assertNotIn("volvió a cerrar", t["corta"])


if __name__ == "__main__":
    unittest.main()
