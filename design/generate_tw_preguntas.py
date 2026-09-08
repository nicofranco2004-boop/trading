"""
Imagen principal del hilo: las 5 preguntas que un broker no contesta.

Pieza tipográfica (sin captura) para que el tweet de arranque no repita el
visual de las respuestas. Cada fila lleva a la derecha, en mono tenue, la
pantalla del hilo que la contesta.

Salida: outputs/social/rendi_tw_preguntas.png (1600×900).
"""

from PIL import Image, ImageDraw, ImageFilter
import brand as b
from brand import DARK as T, F_SEMI, F_MED, F_REG, MONO_M, MONO_R, mix, spaced, sw

W, H = 1600, 900
INK0, INK1, INK2, INK3 = T.ink0, T.ink1, T.ink2, T.ink3
FAINT = T.ink_faint
VIOLET = T.violet

X0, X1 = 56, 1544

# Una pregunta por captura del hilo: la etiqueta de la derecha es una promesa,
# así que no puede haber más preguntas que respuestas.
PREGUNTAS = [
    ("01", "¿Cuánto tengo en total, sumando todas mis cuentas?", "CARTERA"),
    ("02", "¿Cómo me fue cada mes del último año?",              "REPORTES"),
    ("03", "¿Qué error repito cada vez que opero?",              "COMPORTAMIENTO"),
    ("04", "¿Qué se viene en mis activos esta semana?",          "NOVEDADES"),
]

# ── canvas ──────────────────────────────────────────────────────────────────
img = Image.new("RGBA", (W, H), (*T.bg, 255))
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
for r in range(620, 0, -12):
    gd.ellipse([300 - r, 240 - r, 300 + r, 240 + r], fill=(*VIOLET, 8))
img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(130)))
d = ImageDraw.Draw(img, "RGBA")

# ── header ──────────────────────────────────────────────────────────────────
mark = b.logo(T, 28)
img.alpha_composite(mark, (X0, 44))
d = ImageDraw.Draw(img, "RGBA")
d.text((X0 + mark.width + 10, 45), "rendi", font=F_SEMI(26), fill=INK0)

d.text((X0, 122), "4 preguntas que tu broker", font=F_SEMI(52), fill=INK0)
d.text((X0, 182), "no te contesta.", font=F_SEMI(52), fill=INK0)

# ── lista ───────────────────────────────────────────────────────────────────
f_num, f_q, f_tag = MONO_M(21), F_MED(32), MONO_R(14)
y = 320
for i, (num, q, tag) in enumerate(PREGUNTAS):
    d.text((X0, y + 8), num, font=f_num, fill=VIOLET)
    d.text((X0 + 66, y), q, font=f_q, fill=INK1)
    tw = sw(d, tag, f_tag, 3)
    spaced(d, tag, X1 - tw, y + 12, f_tag, INK3, sp=3)
    if i < len(PREGUNTAS) - 1:
        d.line([(X0, y + 84), (X1, y + 84)], fill=(30, 34, 46), width=1)
    y += 120

# ── footer ──────────────────────────────────────────────────────────────────
d.text((X0, 838), "Las cuatro respuestas, acá abajo.", font=F_REG(22), fill=INK2)
uf = MONO_M(21)
url = "rendi.finance"
d.text((X1 - d.textlength(url, font=uf), 839), url, font=uf, fill=VIOLET)

b.save(img, "rendi_tw_preguntas.png")
