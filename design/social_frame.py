"""
Marco común de las piezas sociales con captura real: logo + eyebrow + titular,
la captura con esquinas redondeadas y glow violeta, y el pie con el dominio.

Lo usan generate_tw_caps.py y generate_tw_alertas.py — el marco es el mismo,
solo cambian las capturas y los titulares.
"""

from PIL import Image, ImageDraw, ImageFilter
import os
import brand as b
from brand import DARK as T, F_SEMI, F_REG, MONO_M, MONO_R, spaced

W, H = 1600, 900
CAPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_caps")
INK0, INK2, INK3, VIOLET = T.ink0, T.ink2, T.ink3, T.violet
LINE_R = (52, 48, 84)

BOX = (56, 178, 1544, 812)          # área donde entra la captura


def compose(cap_file, eyebrow, headline, out_name, note=None,
            caption="Pantalla real · montos ilustrativos"):
    img = Image.new("RGBA", (W, H), (*T.bg, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(560, 0, -12):
        gd.ellipse([800 - r, 320 - r, 800 + r, 320 + r], fill=(*VIOLET, 7))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img, "RGBA")

    mark = b.logo(T, 26)
    img.alpha_composite(mark, (56, 44))
    d = ImageDraw.Draw(img, "RGBA")
    d.text((56 + mark.width + 10, 45), "rendi", font=F_SEMI(24), fill=INK0)
    spaced(d, eyebrow.upper(), 56, 92, MONO_R(15), VIOLET, sp=3)
    d.text((56, 118), headline, font=F_SEMI(34), fill=INK0)

    # captura: entra en BOX conservando proporción, centrada
    cap = Image.open(os.path.join(CAPS, cap_file)).convert("RGBA")
    bw, bh = BOX[2] - BOX[0], BOX[3] - BOX[1]
    f_note = F_REG(24)
    note_h = 62 if note else 0                      # la nota entra en el mismo bloque
    s = min(bw / cap.width, (bh - note_h) / cap.height)
    cw, ch = int(cap.width * s), int(cap.height * s)
    cx = BOX[0] + (bw - cw) // 2
    cy = BOX[1] + (bh - ch - note_h) // 2

    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([cx - 10, cy - 10, cx + cw + 10, cy + ch + 10],
                                         radius=22, fill=(*VIOLET, 38))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(44)))

    im = cap.resize((cw, ch), Image.LANCZOS)
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=13, fill=255)
    im.putalpha(mask)
    img.alpha_composite(im, (cx, cy))

    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([cx, cy, cx + cw - 1, cy + ch - 1], radius=13, outline=LINE_R, width=1)

    if note:
        d.text((cx + (cw - d.textlength(note, font=f_note)) / 2, cy + ch + 26),
               note, font=f_note, fill=INK2)

    uf = MONO_M(21)
    url = "rendi.finance"
    d.text((W - 56 - d.textlength(url, font=uf), 850), url, font=uf, fill=VIOLET)
    d.text((56, 850), caption, font=F_REG(19), fill=INK3)

    b.save(img, out_name)
