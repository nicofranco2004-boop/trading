"""
Serie de 3 imágenes de la sección Alertas, para subir juntas en un mismo tweet.

Secuencia: se arma → queda corriendo → te avisa.
Las capturas salen de dos vistas reales (`/alertas` y `/alertas?new=GGAL`), sin
montos que ofuscar: la única cifra en pesos/dólares es la cotización pública de
GGAL, y el resto son porcentajes y umbrales.

Uso:  python3 generate_tw_alertas.py [carpeta_con_capturas_crudas]
Salida: outputs/social/rendi_tw_alertas_{1..3}_*.png (1600×900 cada una).
"""

from PIL import Image
import os
import sys
from social_frame import compose, CAPS

TOUR = sys.argv[1] if len(sys.argv) > 1 else "_caps/raw"

# (archivo crudo, recorte, nombre final)
# La tira de alertas sola queda demasiado chata (ratio 6.5) y el marco se llena
# de aire: va la página entera —título, alertas activas y el feed de avisos—
# que además cuenta la historia completa en una sola imagen.
CROPS = [
    ("alertas_form.png", (716, 592, 3200, 1350), "app_alertas_form.png"),
    ("alertas.png",      (716, 264, 3200, 1310), "app_alertas_pagina.png"),
]

for src, box, out in CROPS:
    path = os.path.join(TOUR, src)
    if os.path.exists(path):
        Image.open(path).crop(box).save(os.path.join(CAPS, out))
        print(f"  ✂ {out} {Image.open(os.path.join(CAPS, out)).size}")

NOTA = "Pantalla real de la app"          # acá no hay montos que ofuscar

compose("app_alertas_form.png", "Alertas",
        "Ponés el precio y te olvidás.",
        "rendi_tw_alertas_1_form.png",
        note="Precio objetivo o variación. Push, email o los dos.",
        caption=NOTA)

compose("app_alertas_pagina.png", "Alertas",
        "Y no solo por ticker: sobre toda tu cartera.",
        "rendi_tw_alertas_2_pagina.png",
        note="“Avisame si algo de lo que tengo se mueve más de 3% en el día.”",
        caption=NOTA)
