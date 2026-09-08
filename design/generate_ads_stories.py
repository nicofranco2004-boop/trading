"""
Carrusel META ADS → versión STORIES (1080×1920, 9:16). Mismo contenido y orden
que el set FINAL del feed, reflowed vertical y respetando safe zones de Stories
(arriba ~280px perfil/cerrar, abajo ~280px botón del anuncio/reply).

  story 1 — gancho: ¿tus inversiones le ganan al S&P 500 y a la inflación?
  story 2 — "no te lo contamos, te lo mostramos" + el gráfico real (sin CTA)
  story 3 — 3 pasos + CTA "empezá gratis en rendi.finance"

Tono claro/cálido. Fuentes de marca (Geist + JetBrains Mono). Colores del chart
exactos del componente real (#21D07A / #46C6E0).
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

FONTS_DIR = "/Users/nicolaspussetto/Documents/trading/design/fonts"
LOGO_DIR = "/Users/nicolaspussetto/Documents/rendi 2/brand-kit/logos"
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"
W, H = 1080, 1920

# Clara
FROST, FROST_WARM = (245, 243, 251), (250, 248, 252)
INK_STRONG, INK_BODY, INK_MUTE, INK_FAINT = (17, 19, 26), (52, 56, 68), (120, 124, 140), (182, 184, 198)
WHITE, CARD_BORDER, TRACK = (255, 255, 255), (228, 224, 240), (232, 229, 244)
VIOLET, VIOLET_INK, VIOLET_SOFT = (139, 125, 255), (96, 80, 222), (176, 165, 250)
GREEN = (20, 168, 92)
# Dark (la "captura")
D_BG, D_BAR, D_CARD, D_LINE = (13, 15, 21), (22, 25, 33), (18, 21, 28), (38, 43, 56)
D_INK0, D_INK1, D_INK3 = (236, 238, 244), (188, 195, 210), (110, 118, 138)
C_CARTERA, C_SP500, C_INFLA = (33, 208, 122), (70, 198, 224), (120, 128, 148)


def font(n, s):
    return ImageFont.truetype(os.path.join(FONTS_DIR, n), s)

F_SEMI, F_MED, F_REG = (lambda s: font("Geist-SemiBold.ttf", s),
                        lambda s: font("Geist-Medium.ttf", s),
                        lambda s: font("Geist-Regular.ttf", s))
MONO_M, MONO_R = lambda s: font("JetBrainsMono-Medium.ttf", s), lambda s: font("JetBrainsMono-Regular.ttf", s)


def mix(fg, bg, a):
    return tuple(int(bg[i] + (fg[i] - bg[i]) * a) for i in range(3))

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

def cen_seg(d, segs, y, f):
    total = sum(d.textlength(t, font=f) for t, _ in segs)
    x = (W - total) / 2
    for t, c in segs:
        d.text((x, y), t, font=f, fill=c)
        x += d.textlength(t, font=f)

def pts(vals, x0, x1, y0, y1, ymax):
    n = len(vals)
    return [(x0 + (x1 - x0) * i / (n - 1), y1 - (v / ymax) * (y1 - y0)) for i, v in enumerate(vals)]


def canvas():
    img = Image.new("RGBA", (W, H), (*FROST, 255))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = max(0.0, 1 - y / (H * 0.7))
        d.line([(0, y), (W, y)], fill=tuple(int(FROST[i] + (FROST_WARM[i] - FROST[i]) * t) for i in range(3)) + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(560, 0, -12):
        gd.ellipse([W // 2 - r, 560 - r, W // 2 + r, 560 + r], fill=(*VIOLET, int((1 - r / 560) * 9)))
    return Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(90)))


_logo = {}
def logo(h):
    if h not in _logo:
        m = Image.open(os.path.join(LOGO_DIR, "rendi-mark-ink.png")).convert("RGBA")
        _logo[h] = m.resize((int(m.width * h / m.height), h), Image.LANCZOS)
    return _logo[h]


def header(img, eyebrow):
    d = ImageDraw.Draw(img, "RGBA")
    mark = logo(40)
    wf = F_SEMI(38)
    ww = d.textlength("rendi", font=wf)
    x0 = (W - (mark.width + 13 + ww)) / 2
    img.alpha_composite(mark, (int(x0), 300))
    d.text((x0 + mark.width + 13, 301), "rendi", font=wf, fill=INK_STRONG)
    cen_spaced(d, eyebrow.upper(), 372, MONO_R(20), VIOLET_INK, sp=3)
    return d


def footer(img):
    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "rendi.finance", 1600, MONO_R(24), INK_MUTE)


def soft_card(img, box, radius=30):
    x0, y0, x1, y1 = box
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + 16, x1, y1 + 16], radius=radius, fill=(74, 62, 128, 42))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(box, radius=radius, fill=WHITE, outline=CARD_BORDER, width=1)
    return d


def cta_pill(img, d, y):
    cta = "Empezá gratis en rendi.finance"
    cf = F_SEMI(34)
    cwd = d.textlength(cta, font=cf)
    px, py = 42, 24
    bw, bh = cwd + px * 2, cf.size + py * 2
    bx = (W - bw) / 2
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([bx, y + 9, bx + bw, y + bh + 9], radius=bh // 2, fill=(96, 80, 222, 75))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh // 2, fill=VIOLET)
    d.text((bx + px, y + py - 3), cta, font=cf, fill=WHITE)
    return d


def save(img, name, n):
    out = os.path.join(OUT_DIR, name)
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"✓ story {n}: {name} ({os.path.getsize(out) / 1024:.1f}KB)")


# ═══════════════════════════ STORY 1 — HOOK ═════════════════════════════════
def story_1():
    img = canvas()
    d = header(img, "/ tu rendimiento real")

    cen(d, "¿Tus inversiones", 640, F_SEMI(68), INK_STRONG)
    cen_seg(d, [("le ganan al ", INK_STRONG), ("S&P 500", GREEN)], 730, F_SEMI(68))
    cen_seg(d, [("y a la ", INK_STRONG), ("inflación", VIOLET_INK), ("?", INK_STRONG)], 820, F_SEMI(68))

    cen(d, "Tu rendimiento real en dólares, comparado", 968, F_REG(33), INK_BODY)
    cen(d, "con los benchmarks que de verdad importan.", 1014, F_REG(33), INK_BODY)

    cen(d, "Y todos tus brokers, en un solo lugar.", 1108, F_REG(28), INK_MUTE)

    # chips
    chips = ["COCOS", "IOL", "BINANCE", "SCHWAB"]
    cf = MONO_R(22)
    pad = 21
    widths = [d.textlength(c, font=cf) + pad * 2 + 24 for c in chips]
    gap = 15
    x = (W - (sum(widths) + gap * (len(chips) - 1))) / 2
    cy = 1240
    for c, wd in zip(chips, widths):
        d.rounded_rectangle([x, cy, x + wd, cy + 54], radius=27, fill=WHITE, outline=CARD_BORDER, width=1)
        d.ellipse([x + pad, cy + 20, x + pad + 13, cy + 33], fill=VIOLET_SOFT)
        d.text((x + pad + 25, cy + 14), c, font=cf, fill=INK_BODY)
        x += wd + gap

    footer(img)
    save(img, "rendi_ads_story_1.png", 1)


# ════════════════════════════ STORY 2 — CHART ═══════════════════════════════
def story_2():
    img = canvas()
    d = header(img, "/ así se ve en rendi")

    cen(d, "No te lo contamos.", 560, F_SEMI(66), INK_STRONG)
    cen(d, "Te lo mostramos.", 654, F_SEMI(66), VIOLET_INK)

    cx, cy, cw, ch = 80, 808, 920, 660
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([cx, cy + 20, cx + cw, cy + ch + 20], radius=24, fill=(40, 34, 70, 75))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(38)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=24, fill=D_BG, outline=D_LINE, width=1)

    bar_h = 54
    d.rounded_rectangle([cx, cy, cx + cw, cy + bar_h + 16], radius=24, fill=D_BAR)
    d.rectangle([cx, cy + bar_h, cx + cw, cy + bar_h + 16], fill=D_BG)
    for i, col in enumerate([(255, 95, 109), (255, 189, 68), (40, 206, 124)]):
        d.ellipse([cx + 30 + i * 28, cy + 20, cx + 30 + i * 28 + 13, cy + 33], fill=col)
    url = "rendi.finance/insights"
    uf = MONO_R(20)
    uw = d.textlength(url, font=uf)
    px = cx + (cw - (uw + 48)) / 2
    d.rounded_rectangle([px, cy + 13, px + uw + 48, cy + 42], radius=14, fill=D_CARD)
    d.text((px + 24, cy + 16), url, font=uf, fill=D_INK3)

    ix = cx + 44
    spaced(d, "PERFORMANCE · TU CARTERA vs EL MUNDO".upper(), ix, cy + bar_h + 30, MONO_R(18), D_INK3, sp=1)
    legs = [("Tu cartera", C_CARTERA), ("S&P 500", C_SP500), ("Inflación", C_INFLA)]
    lf = MONO_R(18)
    lx = cx + cw - 44
    for name, col in reversed(legs):
        tw = d.textlength(name, font=lf)
        lx -= tw
        d.text((lx, cy + bar_h + 30), name, font=lf, fill=D_INK1)
        lx -= 12
        d.ellipse([lx - 12, cy + bar_h + 32, lx, cy + bar_h + 44], fill=col)
        lx -= 30

    px0, px1 = ix + 56, cx + cw - 124
    py0, py1 = cy + bar_h + 96, cy + ch - 60
    ymax = 21.0
    yl = MONO_R(16)
    for v in (0, 5, 10, 15, 20):
        gy = py1 - (v / ymax) * (py1 - py0)
        d.line([(px0, gy), (px1 + 104, gy)], fill=D_LINE, width=1)
        d.text((ix, gy - 10), f"{v}%", font=yl, fill=D_INK3)

    cartera = [0, 3.1, 5.0, 4.4, 9.2, 13.4, 18.2]
    sp500 = [0, 2.0, 3.6, 3.1, 6.2, 9.0, 12.4]
    infla = [0, 0.6, 1.3, 1.9, 2.6, 3.4, 4.1]
    p_inf = pts(infla, px0, px1, py0, py1, ymax)
    p_sp = pts(sp500, px0, px1, py0, py1, ymax)
    p_ca = pts(cartera, px0, px1, py0, py1, ymax)
    d.polygon(p_ca + [(px1, py1), (px0, py1)], fill=mix(C_CARTERA, D_BG, 0.10))
    d.line(p_inf, fill=C_INFLA, width=2, joint="curve")
    d.line(p_sp, fill=C_SP500, width=3, joint="curve")
    d.line(p_ca, fill=C_CARTERA, width=5, joint="curve")
    for x, y in p_ca:
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=C_CARTERA)
    ef = MONO_M(22)
    for vals, p, col in [(cartera, p_ca, C_CARTERA), (sp500, p_sp, C_SP500), (infla, p_inf, C_INFLA)]:
        x, y = p[-1]
        d.text((px1 + 16, y - 12), f"+{vals[-1]:.1f}%".replace(".", ","), font=ef, fill=col)
    months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul"]
    mf = MONO_R(16)
    for i, m in enumerate(months):
        x = px0 + (px1 - px0) * i / (len(months) - 1)
        d.text((x - d.textlength(m, font=mf) / 2, py1 + 16), m, font=mf, fill=D_INK3)

    cen(d, "Ejemplo ilustrativo — en tu cuenta son tus datos reales", cy + ch + 34, F_REG(22), INK_FAINT)
    footer(img)
    save(img, "rendi_ads_story_2.png", 2)


# ═══════════════════════════ STORY 3 — 3 PASOS + CTA ════════════════════════
def story_3():
    img = canvas()
    d = header(img, "/ así de fácil")

    cen(d, "Listo en 3 pasos.", 560, F_SEMI(78), INK_STRONG)

    steps = [
        ("1", "Entrás a rendi.finance", "y creás tu cuenta gratis."),
        ("2", "Importás el CSV", "de movimientos de tu broker."),
        ("3", "Listo.", "Ves tu cartera entera, en dólares."),
    ]
    cx, cy, cw, ch = 100, 720, 880, 600
    d = soft_card(img, [cx, cy, cx + cw, cy + ch])
    pad = 60
    ix = cx + pad
    rh = (ch - pad) / 3
    for i, (num, t1, t2) in enumerate(steps):
        ry = cy + pad / 2 + i * rh + 24
        r = 36
        ccx, ccy = ix + r, ry + r
        d.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=mix(VIOLET, WHITE, 0.14), outline=VIOLET, width=2)
        nf = MONO_M(34)
        nw = d.textlength(num, font=nf)
        d.text((ccx - nw / 2, ccy - 24), num, font=nf, fill=VIOLET_INK)
        tx = ix + 96
        d.text((tx, ry + 6), t1, font=F_SEMI(37), fill=INK_STRONG)
        d.text((tx, ry + 54), t2, font=F_REG(30), fill=INK_BODY)
        if num != "3":
            for dy in range(0, int(rh - 72), 14):
                d.line([(ccx, ccy + r + dy), (ccx, ccy + r + dy + 6)], fill=CARD_BORDER, width=2)

    cen(d, "Sin planillas. Sin cargar nada a mano.", cy + ch + 54, F_REG(28), INK_MUTE)
    d = cta_pill(img, d, cy + ch + 118)

    footer(img)
    save(img, "rendi_ads_story_3.png", 3)


if __name__ == "__main__":
    story_1()
    story_2()
    story_3()
    print("\nDone — 3 stories 1080×1920.")
