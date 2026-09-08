"""
ALTERNATIVA de la slide 3 (NO toca rendi_ads_light_3.png).
Output: rendi_ads_light_3_alt.png — 1080×1080.

Muestra una "captura" estilo producto: ventana dark (chrome + url
rendi.finance/insights) con EL GRÁFICO real de Rendi (Insights → Performance):
LineChart de tu P/L total (verde #21D07A) vs el S&P 500 (celeste #46C6E0)
vs inflación (gris), tu curva por encima. Enmarcada en el fondo claro.

Fiel al componente real (pages/Insights.jsx, líneas ~1888-1902). Valores de
ejemplo. Fuentes de marca (Geist + JetBrains Mono).
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

FONTS_DIR = "/Users/nicolaspussetto/Documents/trading/design/fonts"
LOGO_DIR = "/Users/nicolaspussetto/Documents/rendi 2/brand-kit/logos"
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"
W, H = 1080, 1080

# Paleta clara (carrusel)
FROST, FROST_WARM = (245, 243, 251), (250, 248, 252)
INK_STRONG, INK_MUTE, INK_FAINT = (17, 19, 26), (120, 124, 140), (182, 184, 198)
WHITE = (255, 255, 255)
VIOLET, VIOLET_INK = (139, 125, 255), (96, 80, 222)

# Paleta dark = la app. Colores EXACTOS del chart real de Insights.
D_BG, D_BAR, D_CARD, D_LINE = (13, 15, 21), (22, 25, 33), (18, 21, 28), (38, 43, 56)
D_INK0, D_INK1, D_INK3 = (236, 238, 244), (188, 195, 210), (110, 118, 138)
C_CARTERA = (33, 208, 122)   # #21D07A  P/L total
C_SP500   = (70, 198, 224)   # #46C6E0  benchmark USD
C_INFLA   = (120, 128, 148)  # gris      inflación


def font(n, s):
    return ImageFont.truetype(os.path.join(FONTS_DIR, n), s)

F_SEMI, F_REG = lambda s: font("Geist-SemiBold.ttf", s), lambda s: font("Geist-Regular.ttf", s)
MONO_M, MONO_R = lambda s: font("JetBrainsMono-Medium.ttf", s), lambda s: font("JetBrainsMono-Regular.ttf", s)


def sw(d, t, f, sp=4):
    return sum(d.textlength(c, font=f) for c in t) + sp * (len(t) - 1) if t else 0

def spaced(d, t, x, y, f, fill, sp=4):
    cx = x
    for c in t:
        d.text((cx, y), c, font=f, fill=fill)
        cx += d.textlength(c, font=f) + sp

def cen(d, t, y, f, fill):
    d.text((W / 2 - d.textlength(t, font=f) / 2, y), t, font=f, fill=fill)

def cen_spaced(d, t, y, f, fill, sp=4):
    spaced(d, t, W / 2 - sw(d, t, f, sp) / 2, y, f, fill, sp)


def canvas():
    img = Image.new("RGBA", (W, H), (*FROST, 255))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = max(0.0, 1 - y / (H * 0.7))
        d.line([(0, y), (W, y)], fill=tuple(int(FROST[i] + (FROST_WARM[i] - FROST[i]) * t) for i in range(3)) + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(480, 0, -12):
        gd.ellipse([W // 2 - r, 150 - r, W // 2 + r, 150 + r], fill=(*VIOLET, int((1 - r / 480) * 9)))
    return Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(80)))


_logo = {}
def logo(h):
    if h not in _logo:
        m = Image.open(os.path.join(LOGO_DIR, "rendi-mark-ink.png")).convert("RGBA")
        _logo[h] = m.resize((int(m.width * h / m.height), h), Image.LANCZOS)
    return _logo[h]


def header(img):
    d = ImageDraw.Draw(img, "RGBA")
    mark = logo(36)
    wf = F_SEMI(34)
    ww = d.textlength("rendi", font=wf)
    x0 = (W - (mark.width + 12 + ww)) / 2
    img.alpha_composite(mark, (int(x0), 70))
    d.text((x0 + mark.width + 12, 71), "rendi", font=wf, fill=INK_STRONG)
    cen_spaced(d, "/ ASÍ SE VE EN RENDI", 132, MONO_R(18), VIOLET_INK, sp=3)
    return d


def footer(img):
    d = ImageDraw.Draw(img, "RGBA")
    dot, gap, total, cur = 8, 14, 3, 1
    sx = (W - (dot * total + gap * (total - 1))) / 2
    for i in range(total):
        cx = sx + i * (dot + gap)
        d.ellipse([cx, H - 92, cx + dot, H - 92 + dot], fill=VIOLET if i == cur else INK_FAINT)
    cen(d, "rendi.finance", H - 64, MONO_R(20), INK_MUTE)


def pts(vals, x0, x1, y0, y1, ymax):
    n = len(vals)
    return [(x0 + (x1 - x0) * i / (n - 1), y1 - (v / ymax) * (y1 - y0)) for i, v in enumerate(vals)]


def build():
    img = canvas()
    d = header(img)

    cen(d, "No te lo contamos.", 222, F_SEMI(58), INK_STRONG)
    d.text((W / 2 - d.textlength("Te lo mostramos.", font=F_SEMI(58)) / 2, 292),
           "Te lo mostramos.", font=F_SEMI(58), fill=VIOLET_INK)

    # ── ventana "captura" (dark) con sombra ──
    cx, cy, cw, ch = 100, 410, 880, 442
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([cx, cy + 18, cx + cw, cy + ch + 18], radius=22, fill=(40, 34, 70, 70))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=22, fill=D_BG, outline=D_LINE, width=1)

    # chrome del browser
    bar_h = 48
    d.rounded_rectangle([cx, cy, cx + cw, cy + bar_h + 16], radius=22, fill=D_BAR)
    d.rectangle([cx, cy + bar_h, cx + cw, cy + bar_h + 16], fill=D_BG)
    for i, col in enumerate([(255, 95, 109), (255, 189, 68), (40, 206, 124)]):
        d.ellipse([cx + 26 + i * 26, cy + 18, cx + 26 + i * 26 + 12, cy + 30], fill=col)
    url = "rendi.finance/insights"
    uf = MONO_R(18)
    uw = d.textlength(url, font=uf)
    px = cx + (cw - (uw + 44)) / 2
    d.rounded_rectangle([px, cy + 12, px + uw + 44, cy + 38], radius=13, fill=D_CARD)
    d.text((px + 22, cy + 15), url, font=uf, fill=D_INK3)

    # cuerpo
    ix = cx + 40
    spaced(d, "PERFORMANCE · TU CARTERA vs EL MUNDO".upper(), ix, cy + bar_h + 26, MONO_R(17), D_INK3, sp=1)

    # leyenda (arriba-derecha)
    legs = [("Tu cartera", C_CARTERA), ("S&P 500", C_SP500), ("Inflación", C_INFLA)]
    lf = MONO_R(17)
    lx = cx + cw - 40
    for name, col in reversed(legs):
        tw = d.textlength(name, font=lf)
        lx -= tw
        d.text((lx, cy + bar_h + 26), name, font=lf, fill=D_INK1)
        lx -= 12
        d.ellipse([lx - 11, cy + bar_h + 28, lx, cy + bar_h + 39], fill=col)
        lx -= 28

    # ── el gráfico (LineChart) ──
    px0, px1 = ix + 52, cx + cw - 116
    py0, py1 = cy + bar_h + 78, cy + ch - 50
    ymax = 21.0

    # gridlines + y-labels
    yl = MONO_R(15)
    for v in (0, 5, 10, 15, 20):
        gy = py1 - (v / ymax) * (py1 - py0)
        d.line([(px0, gy), (px1 + 96, gy)], fill=D_LINE, width=1)
        d.text((ix, gy - 9), f"{v}%", font=yl, fill=D_INK3)

    cartera = [0, 3.1, 5.0, 4.4, 9.2, 13.4, 18.2]
    sp500   = [0, 2.0, 3.6, 3.1, 6.2, 9.0, 12.4]
    infla   = [0, 0.6, 1.3, 1.9, 2.6, 3.4, 4.1]

    p_inf = pts(infla, px0, px1, py0, py1, ymax)
    p_sp = pts(sp500, px0, px1, py0, py1, ymax)
    p_ca = pts(cartera, px0, px1, py0, py1, ymax)

    # área tenue bajo la curva de la cartera (fill sólido premezclado)
    fill_col = tuple(int(D_BG[i] + (C_CARTERA[i] - D_BG[i]) * 0.10) for i in range(3))
    d.polygon(p_ca + [(px1, py1), (px0, py1)], fill=fill_col)

    d.line(p_inf, fill=C_INFLA, width=2, joint="curve")
    d.line(p_sp, fill=C_SP500, width=3, joint="curve")
    d.line(p_ca, fill=C_CARTERA, width=4, joint="curve")
    for x, y in p_ca:
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=C_CARTERA)

    # labels de valor final (a la derecha de cada línea)
    ef = MONO_M(20)
    for vals, p, col in [(cartera, p_ca, C_CARTERA), (sp500, p_sp, C_SP500), (infla, p_inf, C_INFLA)]:
        x, y = p[-1]
        d.text((px1 + 14, y - 11), f"+{vals[-1]:.1f}%".replace(".", ","), font=ef, fill=col)

    # x-axis (meses)
    months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul"]
    mf = MONO_R(15)
    for i, m in enumerate(months):
        x = px0 + (px1 - px0) * i / (len(months) - 1)
        d.text((x - d.textlength(m, font=mf) / 2, py1 + 14), m, font=mf, fill=D_INK3)

    cen(d, "Ejemplo ilustrativo — en tu cuenta son tus datos reales", cy + ch + 30, F_REG(20), INK_FAINT)

    footer(img)
    out = os.path.join(OUT_DIR, "rendi_ads_light_3_alt.png")
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"✓ alt slide 3 (gráfico): {out} ({os.path.getsize(out) / 1024:.1f}KB)")


if __name__ == "__main__":
    build()
