"""
Imagen para el post de COACH IA (LinkedIn + X). Reproduce FIEL el panel real
del Coach de Rendi (frontend/src/components/AICoach.jsx):
  - header: sparkle (rendi-accent #5B9DF9) + "Coach IA" + badge "Pro · libre"
    (violeta) + cuota "x/y esta semana".
  - burbuja usuario: rendi-accent/15 con borde /30 (NO violeta sólido).
  - burbuja coach: bg-2, texto ink-0.
  - disclaimer real: "Claude Haiku · Observaciones orientativas. No constituyen
    asesoramiento financiero." (refuerza el "no te dice qué comprar" del post).
  - input con placeholder real "Preguntale lo que quieras sobre tu cartera…".

No es un mockup genérico: colores, copy y layout salen del componente real.
Números de la respuesta = ejemplo ilustrativo.

Salidas:
  rendi_coach_45.png    1080×1350 (4:5)  — LinkedIn
  rendi_coach_169.png   1600×900 (16:9)  — X / Twitter
"""

from PIL import Image, ImageDraw, ImageFilter
import os
import brand as b
from brand import (DARK, canvas, header, footer, save, mix, wrap,
                   F_SEMI, F_MED, F_REG, MONO_M, MONO_R, cen, spaced)

t = DARK
SKY = (91, 157, 249)      # #5B9DF9 rendi-accent
VIOLET = (139, 125, 255)  # #8B7DFF
D_BG = (13, 15, 21)
D_BAR = (22, 25, 33)
D_BUBBLE = (26, 30, 40)   # bg-2 burbuja coach
D_LINE = (40, 45, 58)
INK0, INK1, INK2, INK3 = (236, 238, 244), (198, 204, 218), (150, 158, 176), (112, 120, 140)

Q = "¿Estoy muy concentrado en un activo?"
A = ("El 41% de tu cartera está en una sola acción. Cuando una posición pesa más "
     "del 25-30%, un mal trimestre de ese activo te mueve toda la cartera.\n\n"
     "No te digo que vendas: te muestro cuánto dependés de una sola apuesta.")
DISCLAIMER = "Claude Haiku · Observaciones orientativas. No constituyen asesoramiento financiero."
PLACEHOLDER = "Preguntale lo que quieras sobre tu cartera…"


def sparkle(d, cx, cy, r, col):
    pts = [(cx, cy - r), (cx + r * .26, cy - r * .26), (cx + r, cy), (cx + r * .26, cy + r * .26),
           (cx, cy + r), (cx - r * .26, cy + r * .26), (cx - r, cy), (cx - r * .26, cy - r * .26)]
    d.polygon(pts, fill=col)


def bubble(d, x_anchor, y, text, side, maxw, font, lh, pad=22, radius=26):
    """Dibuja una burbuja. side='r' usuario (anclada a la derecha en x_anchor),
    'l' coach (anclada a la izquierda en x_anchor). Devuelve y final."""
    lines = []
    for para in text.split("\n"):
        lines += wrap(d, para, font, maxw - pad * 2) if para else [""]
    tw = max((d.textlength(ln, font=font) for ln in lines if ln), default=0)
    bw = tw + pad * 2
    bh = len([l for l in lines]) * lh + pad * 2 - (lh - font.size)
    if side == "r":
        x0 = x_anchor - bw
        fill = mix(SKY, D_BG, 0.16)
        border = mix(SKY, D_BG, 0.42)
        txt = INK0
    else:
        x0 = x_anchor
        fill = D_BUBBLE
        border = D_LINE
        txt = INK1
    d.rounded_rectangle([x0, y, x0 + bw, y + bh], radius=radius, fill=fill, outline=border, width=1)
    ty = y + pad
    for ln in lines:
        d.text((x0 + pad, ty), ln, font=font, fill=txt)
        ty += lh
    return y + bh


def coach_panel(img, box, scale=1.0):
    """Reproduce el panel del Coach real. box=(x,y,w,h)."""
    cx, cy, cw, ch = box
    # sombra + card
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([cx, cy + 16, cx + cw, cy + ch + 16], radius=26, fill=(0, 0, 0, 120))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=26, fill=D_BG, outline=D_LINE, width=1)

    pad = int(34 * scale)
    ix = cx + pad
    # ── header ──
    hy = cy + pad
    sparkle(d, ix + 12, hy + 14, int(13 * scale), SKY)
    tf = F_SEMI(int(30 * scale))
    d.text((ix + 32, hy), "Coach IA", font=tf, fill=INK0)
    tw = d.textlength("Coach IA", font=tf)
    # badge "Pro · libre"
    bf = MONO_R(int(15 * scale))
    btxt = "PRO · LIBRE"
    bx = ix + 32 + tw + 16
    bw = d.textlength(btxt, font=bf) + 20
    d.rounded_rectangle([bx, hy + 2, bx + bw, hy + 2 + int(26 * scale)], radius=6,
                        fill=mix(VIOLET, D_BG, 0.08), outline=mix(VIOLET, D_BG, 0.42), width=1)
    d.text((bx + 10, hy + int(5 * scale)), btxt, font=bf, fill=mix(VIOLET, D_BG, 0.9))
    # cuota a la derecha
    qf = MONO_R(int(17 * scale))
    quota = "3/30 esta semana"
    d.text((cx + cw - pad - d.textlength(quota, font=qf), hy + 4), quota, font=qf, fill=INK3)
    # subtítulo
    d.text((ix + 32, hy + int(38 * scale)), "Preguntale lo que quieras sobre tu cartera",
           font=F_REG(int(19 * scale)), fill=INK3)
    # divider
    dvy = hy + int(74 * scale)
    d.line([(cx, dvy), (cx + cw, dvy)], fill=D_LINE, width=1)

    # ── mensajes ──
    msg_font = F_REG(int(26 * scale))
    lh = int(36 * scale)
    maxw = int(cw * 0.74)
    by = dvy + pad
    by = bubble(d, cx + cw - pad, by, Q, "r", int(cw * 0.62), F_MED(int(26 * scale)), lh) + int(20 * scale)
    by = bubble(d, cx + pad, by, A, "l", maxw, msg_font, lh) + int(8 * scale)

    # ── input ──
    iy = cy + ch - pad - int(54 * scale)
    d.rounded_rectangle([ix, iy, cx + cw - pad - int(64 * scale), iy + int(54 * scale)],
                        radius=12, fill=D_BAR, outline=D_LINE, width=1)
    d.text((ix + 18, iy + int(15 * scale)), PLACEHOLDER, font=F_REG(int(21 * scale)), fill=INK3)
    # botón violeta de enviar
    bxs = cx + cw - pad - int(54 * scale)
    d.rounded_rectangle([bxs, iy, bxs + int(54 * scale), iy + int(54 * scale)], radius=10, fill=VIOLET)
    # flechita ↑
    aw = int(54 * scale)
    acx, acy = bxs + aw / 2, iy + aw / 2
    d.line([(acx, acy + 9), (acx, acy - 9)], fill=(255, 255, 255), width=3)
    d.line([(acx, acy - 9), (acx - 7, acy - 2)], fill=(255, 255, 255), width=3)
    d.line([(acx, acy - 9), (acx + 7, acy - 2)], fill=(255, 255, 255), width=3)

    # ── disclaimer ──
    dy = iy - int(40 * scale)
    df = MONO_R(int(15 * scale))
    dw = d.textlength(DISCLAIMER, font=df)
    d.text((cx + (cw - dw) / 2, dy), DISCLAIMER, font=df, fill=INK3)


# ───────────────────────── 4:5 (LinkedIn) ──────────────────────────────────
def render_45():
    W, H = 1080, 1350
    img = canvas(t, (W, H))
    header(img, t, "/ coach ia", W)
    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "Preguntale a la IA", 222, F_SEMI(58), INK0, W)
    cen(d, "sobre tu cartera.", 296, F_SEMI(58), INK0, W)
    cen(d, "Te responde con tus datos, no con consejos genéricos.", 392, F_REG(28), INK2, W)
    coach_panel(img, (70, 468, 940, 678), scale=1.0)
    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "Ejemplo ilustrativo — en tu cuenta responde con tus números reales", 1178, F_REG(20), (90, 96, 112), W)
    footer(img, t, W, H)
    save(img, "rendi_coach_45.png")


# ───────────────────────── 16:9 (X / Twitter) ──────────────────────────────
def render_169():
    W, H = 1600, 900
    img = canvas(t, (W, H))
    d = ImageDraw.Draw(img, "RGBA")
    mark = b.logo(t, 34)
    img.alpha_composite(mark, (80, 70))
    d.text((80 + mark.width + 12, 71), "rendi", font=F_SEMI(33), fill=INK0)
    spaced(d, "COACH IA", 84, 118, MONO_R(17), mix(VIOLET, D_BG, 0.9), sp=3)

    d.text((80, 250), "Preguntale", font=F_SEMI(64), fill=INK0)
    d.text((80, 326), "a tu cartera.", font=F_SEMI(64), fill=INK0)
    for i, ln in enumerate(["Le escribís en lenguaje natural y te", "responde con tus datos reales.",
                            "No te dice qué comprar:", "te traduce lo que ya tenés."]):
        col = INK2 if i < 2 else INK1
        d.text((80, 446 + i * 40), ln, font=F_REG(27), fill=col)
    d.text((80, 800), "rendi.finance", font=MONO_R(22), fill=INK3)

    coach_panel(img, (720, 110, 800, 680), scale=0.96)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((720, 812), "Ejemplo ilustrativo — en tu cuenta son tus números reales",
           font=F_REG(19), fill=(90, 96, 112))
    save(img, "rendi_coach_169.png")


# ───────────────────────── 9:16 (Historias / Reels) ────────────────────────
def render_916():
    W, H = 1080, 1920
    img = canvas(t, (W, H))
    header(img, t, "/ coach ia", W, y=250, mark_h=42)
    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "Preguntale a la IA", 408, F_SEMI(58), INK0, W)
    cen(d, "sobre tu cartera.", 482, F_SEMI(58), INK0, W)
    cen(d, "Te responde con tus datos,", 592, F_REG(27), INK2, W)
    cen(d, "no con consejos genéricos.", 630, F_REG(27), INK2, W)
    coach_panel(img, (55, 720, 970, 720), scale=1.1)
    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "Ejemplo ilustrativo — en tu cuenta son tus números reales", 1490, F_REG(20), (90, 96, 112), W)
    cen(d, "rendi.finance", 1534, MONO_R(24), INK3, W)
    save(img, "rendi_coach_916.png")


if __name__ == "__main__":
    render_45()
    render_916()
    render_169()
    print("\nDone — 4:5 + 9:16 + 16:9.")
