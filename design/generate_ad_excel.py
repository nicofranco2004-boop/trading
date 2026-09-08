"""
Ad TOFU (tráfico, awareness) — "Tu Excel te miente. Rendi, no."
Diseño antes → después: arriba el Excel roto (chico, apagado: #REF!, ??, total ???);
abajo la cartera real de Rendi (hero: total en US$ + pesos, posiciones con P&L,
toggle de moneda). Muestra el producto y la transformación, no solo el problema.

Salidas:
  rendi_ad_excel_45.png    1080×1350 (4:5)  — feed Meta
  rendi_ad_excel_916.png   1080×1920 (9:16) — historias / reels
"""
from PIL import Image, ImageDraw, ImageFilter
import brand as b
from brand import (DARK, canvas, header, footer, save, mix,
                   F_SEMI, F_MED, F_REG, MONO_M, MONO_R, cen, cen_seg, spaced, sw)

t = DARK
NEG = (255, 83, 96)
GRN = (33, 208, 122)
SKY = (70, 198, 224)
VIO = (139, 125, 255)
VIO_S = (176, 165, 250)
AMBER = (255, 189, 68)
XLS_GREEN = (33, 150, 83)


def label_tab(d, x, y, text, color, dotcol):
    """Mini-etiqueta arriba de cada card: ● TEXTO (mono, mayúscula spaced)."""
    d.ellipse([x, y + 3, x + 11, y + 14], fill=dotcol)
    spaced(d, text.upper(), x + 24, y, MONO_R(19), color, sp=2)


# ─── ANTES: Excel roto (chico, apagado) ──────────────────────────────────────
def excel_card(img, box):
    x, y, w, h = box
    BG = (15, 16, 21)
    GRID = (30, 34, 44)
    I1, I3 = (140, 146, 162), (92, 98, 116)  # apagados (menos contraste = "lo malo")
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x, y + 12, x + w, y + h + 12], radius=22, fill=(0, 0, 0, 90))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(28)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([x, y, x + w, y + h], radius=22, fill=BG, outline=GRID, width=1)
    pad = 34
    L, R = x + pad, x + w - pad
    # tab + stale
    d.rounded_rectangle([L, y + 26, L + 16, y + 42], radius=4, fill=mix(XLS_GREEN, BG, 0.85))
    d.text((L + 26, y + 24), "inversiones.xlsx", font=MONO_R(20), fill=I3)
    stale = "desactualizado · hace 4 meses"
    sf = MONO_R(18)
    d.text((R - d.textlength(stale, font=sf), y + 25), stale, font=sf, fill=mix(NEG, BG, 0.78))
    d.line([(L, y + 64), (R, y + 64)], fill=GRID, width=1)
    # 2 filas rotas + total
    nf = MONO_R(25)
    af = MONO_M(25)
    rows = [("AAPL", "#REF!", NEG), ("BTC", "?? sin actualizar", I3)]
    ry = y + 92
    for act, val, col in rows:
        d.text((L, ry), act, font=af, fill=I1)
        d.text((R - d.textlength(val, font=nf), ry), val, font=nf, fill=col)
        ry += 50
    d.line([(L, ry + 6), (R, ry + 6)], fill=GRID, width=1)
    d.text((L, ry + 24), "Rendimiento real", font=F_MED(25), fill=I3)
    q = "???"
    d.text((R - d.textlength(q, font=F_SEMI(30)), ry + 18), q, font=F_SEMI(30), fill=NEG)
    return d


# ─── DESPUÉS: cartera Rendi (hero, viva) ─────────────────────────────────────
def rendi_card(img, box):
    x, y, w, h = box
    CARD = (16, 18, 26)
    GRID = (40, 44, 60)
    I0, I1, I2 = (236, 238, 244), (190, 196, 212), (140, 148, 168)
    # sombra con glow violeta (es el "bueno")
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x, y + 18, x + w, y + h + 18], radius=28, fill=(*VIO, 46))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(46)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([x, y, x + w, y + h], radius=28, fill=CARD, outline=mix(VIO, CARD, 0.55), width=1)
    pad = 46
    L, R = x + pad, x + w - pad
    # header: "Tu cartera"  +  toggle US$ · $
    d.text((L, y + 34), "Tu cartera", font=F_MED(28), fill=I2)
    tg = "US$ · $"
    tf = MONO_M(21)
    tw = d.textlength(tg, font=tf)
    tx0 = R - tw - 36
    d.rounded_rectangle([tx0, y + 30, R, y + 30 + 40], radius=20, fill=mix(VIO, CARD, 0.16), outline=mix(VIO, CARD, 0.5), width=1)
    d.text((tx0 + 18, y + 38), tg, font=tf, fill=VIO_S)
    # total grande + chip verde
    tot = "US$ 12.480"
    bf = F_SEMI(72)
    d.text((L, y + 86), tot, font=bf, fill=I0)
    chip = "+18,2%"
    cf = F_SEMI(26)
    cw = d.textlength(chip, font=cf)
    cx = L + d.textlength(tot, font=bf) + 24
    d.rounded_rectangle([cx, y + 112, cx + cw + 36, y + 112 + 44], radius=22, fill=mix(GRN, CARD, 0.16))
    d.text((cx + 18, y + 119), chip, font=cf, fill=GRN)
    d.text((L, y + 176), "≈ $ 18.720.000 en pesos", font=MONO_R(22), fill=I2)
    d.line([(L, y + 224), (R, y + 224)], fill=GRID, width=1)
    # filas con P&L
    rows = [("MELI", "Mercado Libre", "US$ 4.120", "+12,3%", GRN),
            ("AAPL", "Apple", "US$ 3.080", "−2,1%", NEG),
            ("PF", "Plazo fijo", "US$ 2.260", "+4,1%", SKY)]
    ry = y + 252
    nf = F_MED(28)
    pf = F_REG(22)
    pcf = MONO_M(24)
    vf = MONO_M(26)
    for sym, name, val, pnl, col in rows:
        d.ellipse([L, ry + 6, L + 38, ry + 44], fill=mix(VIO, CARD, 0.22))
        d.text((L + (38 - d.textlength(sym[:2], font=MONO_M(18))) / 2, ry + 14), sym[:2], font=MONO_M(18), fill=VIO_S)
        d.text((L + 56, ry + 2), name, font=nf, fill=I1)
        d.text((R - d.textlength(val, font=vf), ry + 4), val, font=vf, fill=I0)
        pw = d.textlength(pnl, font=pcf)
        d.text((R - d.textlength(val, font=vf) - 24 - pw, ry + 8), pnl, font=pcf, fill=col)
        ry += 64
    return d


def connector(img, cx, y):
    d = ImageDraw.Draw(img, "RGBA")
    # círculo violeta con flecha abajo
    r = 28
    d.ellipse([cx - r, y - r, cx + r, y + r], fill=mix(VIO, t.bg, 0.18), outline=mix(VIO, t.bg, 0.55), width=1)
    d.line([(cx, y - 11), (cx, y + 11)], fill=VIO_S, width=4)
    d.line([(cx - 11, y + 1), (cx, y + 13)], fill=VIO_S, width=4)
    d.line([(cx + 11, y + 1), (cx, y + 13)], fill=VIO_S, width=4)
    spaced(d, "EN 2 MINUTOS", cx + r + 22, y - 11, MONO_R(19), VIO_S, sp=3)
    return d


def render(W, H, top, story=False):
    img = canvas(t, (W, H))
    if story:
        header(img, t, "/ si invertís", W, y=top, mark_h=42)
        y0 = top + 250
    else:
        header(img, t, "/ si invertís", W)
        y0 = 206
    d = ImageDraw.Draw(img, "RGBA")
    cen_seg(d, [("Tu Excel te ", t.title), ("miente", NEG), (".", t.title)], y0, F_SEMI(56), W)
    cen_seg(d, [("Rendi", VIO_S), (", no.", t.title)], y0 + 76, F_SEMI(56), W)

    ey = y0 + 196
    eh = 268
    d = excel_card(img, (174, ey, 732, eh))
    label_tab(d, 174, ey - 36, "en tu excel", (150, 156, 174), mix(NEG, t.bg, 0.6))

    cy = ey + eh + 48
    connector(img, W / 2 - 96, cy)

    ry = cy + 54
    d = rendi_card(img, (90, ry, 900, 446))
    label_tab(d, 90, ry - 36, "en rendi", VIO_S, VIO)

    if story:
        cen(d, "rendi.finance", ry + 446 + 70, MONO_R(24), t.ink2, W)
    else:
        footer(img, t, W, H)
    return img


if __name__ == "__main__":
    save(render(1080, 1350, 206), "rendi_ad_excel_45.png")
    save(render(1080, 1920, 300, story=True), "rendi_ad_excel_916.png")
    print("Done — 4:5 + 9:16.")
