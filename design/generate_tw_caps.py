"""
Serie de 4 imágenes para un hilo de X: capturas reales de Rendi, cada una con
un titular corto y la marca. Los montos vienen ofuscados por
`_caps/obfuscate_tour.py` (factor único, porcentajes intactos).

Salida: outputs/social/rendi_tw_cap_{1..4}_*.png (1600×900 cada una).
"""

from social_frame import compose

compose("app_cartera.png", "Cartera en vivo",
        "Todos tus brokers, un solo número.",
        "rendi_tw_cap_1_cartera.png",
        note="Tres cuentas, dos monedas, un número. Todo llevado al dólar MEP.")

compose("app_reportes.png", "Performance histórica",
        "Mes a mes, en verde y en rojo.",
        "rendi_tw_cap_2_reportes.png")

compose("app_comportamiento.png", "Comportamiento",
        "Los sesgos que tu broker no te va a decir.",
        "rendi_tw_cap_3_comportamiento.png",
        caption="Pantalla real de la app")   # esta vista no tiene montos que ofuscar

compose("app_novedades.png", "Novedades",
        "Noticias y eventos, filtrados por tu cartera.",
        "rendi_tw_cap_4_novedades.png",
        note="Y el impacto calculado sobre tu tenencia, no sobre el papel.")
