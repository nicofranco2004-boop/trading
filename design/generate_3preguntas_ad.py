"""
Anuncio WEB (conversión) — "3 preguntas" como IMAGEN ÚNICA (no carrusel), 4:5.
Autocontenido: muestra las 3 preguntas en un solo frame para que funcione como
ad de registro (el CTA va en el botón de Meta). Tono claro (da variedad vs los
de inflación/coach que son oscuros). Estética de marca real.
Salida: rendi_ad_3preguntas_45.png (1080×1350).
"""

from PIL import ImageDraw
import brand as b
from brand import LIGHT, FEED, canvas, header, footer, save, mix, cen, cen_seg, card, F_SEMI, F_REG, MONO_R

t = LIGHT
W, H = FEED

QS = [
    ("01", "¿Le estás ganando a la inflación?"),
    ("02", "¿Cuánto pesa tu activo más grande?"),
    ("03", "¿Cuánto te llevaron las comisiones?"),
]


def build():
    img = canvas(t, FEED)
    header(img, t, "/ para los que invierten", W)
    d = ImageDraw.Draw(img, "RGBA")

    cen(d, "3 preguntas sobre tus", 238, F_SEMI(58), t.ink0, W)
    cen_seg(d, [("inversiones que hoy ", t.ink0), ("no", t.accent)], 312, F_SEMI(58), W)
    cen_seg(d, [("podés responder", t.accent), (".", t.ink0)], 386, F_SEMI(58), W)

    # card con las 3 preguntas
    cx, cy, cw = 110, 540, 860
    rowh = 150
    ch = rowh * 3 + 36
    d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=30)
    for i, (num, q) in enumerate(QS):
        ry = cy + 18 + i * rowh
        d.text((cx + 48, ry + 30), num, font=F_SEMI(72), fill=mix(t.violet_soft, t.card_fill, 0.55))
        d.text((cx + 196, ry + 48), q, font=F_SEMI(33), fill=t.ink0)
        if i < len(QS) - 1:
            d.line([(cx + 48, ry + rowh - 2), (cx + cw - 48, ry + rowh - 2)], fill=t.card_border, width=1)

    cen(d, "Rendi te las responde con tu cartera, no de memoria.", cy + ch + 56, F_REG(28), t.ink1, W)
    cen(d, "Empezá gratis", cy + ch + 104, F_SEMI(30), t.accent, W)

    footer(img, t, W, H)
    save(img, "rendi_ad_3preguntas_45.png")


def build_916():
    W, H = 1080, 1920
    img = canvas(t, (W, H))
    header(img, t, "/ para los que invierten", W, y=300, mark_h=42)
    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "3 preguntas sobre tus", 560, F_SEMI(56), t.ink0, W)
    cen_seg(d, [("inversiones que hoy ", t.ink0), ("no", t.accent)], 636, F_SEMI(56), W)
    cen_seg(d, [("podés responder", t.accent), (".", t.ink0)], 712, F_SEMI(56), W)

    cx, cy, cw = 100, 880, 880
    rowh = 168
    ch = rowh * 3 + 36
    d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=30)
    for i, (num, q) in enumerate(QS):
        ry = cy + 22 + i * rowh
        d.text((cx + 50, ry + 34), num, font=F_SEMI(78), fill=mix(t.violet_soft, t.card_fill, 0.55))
        d.text((cx + 210, ry + 54), q, font=F_SEMI(33), fill=t.ink0)
        if i < len(QS) - 1:
            d.line([(cx + 50, ry + rowh - 2), (cx + cw - 50, ry + rowh - 2)], fill=t.card_border, width=1)

    cen(d, "Rendi te las responde con tu cartera.", cy + ch + 60, F_REG(28), t.ink1, W)
    cen(d, "Empezá gratis · rendi.finance", cy + ch + 108, F_SEMI(30), t.accent, W)
    save(img, "rendi_ad_3preguntas_916.png")


if __name__ == "__main__":
    build()
    build_916()
