"""
Banner de LinkedIn para Rendi — perfil personal (founder), 1584×396 px.

Estética "Nocturnal Precision" del resto de los assets: fondo Ink, glow violeta,
una curva de equity refinada (portfolio en violeta + benchmark en cielo) sobre
candles tenues. El bloque de texto va a la izquierda-centro, despejando la
esquina inferior-izquierda donde LinkedIn superpone la foto de perfil.

Voz/brand kit: dato primero, voseo, sentence case, CERO emoji. Violeta solo en
marca/acción (wordmark + URL). Verde/rojo solo en datos con polaridad (candles).

Salida: rendi_linkedin_banner.png
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import math
import random

random.seed(7)  # determinístico: misma curva en cada corrida

FONTS_DIR = (
    "/Users/nicolaspussetto/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "bcfbadf3-5949-46c4-95ea-f77e7e18d7ad/"
    "6a7d8d68-f39a-4be8-86c7-653fd22de85c/skills/canvas-design/canvas-fonts/"
)
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"
W, H = 1584, 396

# ─── Colores (brand kit) ──────────────────────────────────────────────────────
BG = (10, 11, 14)
BG_GLOW = (17, 14, 28)
INK_0 = (244, 244, 248)
INK_1 = (198, 199, 209)
INK_2 = (128, 131, 142)
INK_3 = (84, 90, 104)
VIOLET = (139, 125, 255)
CIELO = (91, 157, 249)
POS = (33, 208, 122)
NEG = (255, 83, 96)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)


F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)
F_MONO_REG = lambda s: font("GeistMono-Regular.ttf", s)


def spaced_width(draw, text, font_obj, spacing):
    if not text:
        return 0
    return sum(draw.textlength(ch, font=font_obj) for ch in text) + spacing * (len(text) - 1)


def draw_spaced(draw, text, x, y, font_obj, fill, spacing):
    cur = x
    for ch in text:
        draw.text((cur, y), ch, font=font_obj, fill=fill)
        cur += draw.textlength(ch, font=font_obj) + spacing
    return cur - x


# ─── Base: fondo Ink + glow violeta a la derecha ──────────────────────────────
def build_base():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # gradiente vertical sutil
    for y in range(H):
        t = 1 - abs(y - H / 2) / (H / 2)
        r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.4)
        g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.4)
        b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.4)
        d.line([(0, y), (W, y)], fill=(r, g, b))

    # glow violeta concentrado a la derecha (deja la izquierda oscura p/ texto)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = int(W * 0.74), int(H * 0.42)
    for r in range(360, 0, -8):
        alpha = int((1 - r / 360) * 22)
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*VIOLET, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    return img


# ─── Curva de equity (candles tenues + línea portfolio + benchmark) ───────────
def draw_chart(img):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    n = 58
    x0, x1 = 150, W - 70
    step = (x1 - x0) / n

    # serie de precios: arranca, dip suave, recupera y termina arriba (V + breakout)
    price = 100.0
    closes, opens, highs, lows = [], [], [], []
    for i in range(n):
        frac = i / n
        drift = 0.9 if frac < 0.30 else (-1.9 if frac < 0.48 else 2.4)
        price += drift + random.uniform(-2.4, 2.4)
        price = max(60, price)
        o = price + random.uniform(-1.5, 1.5)
        c = price + random.uniform(-1.5, 1.5)
        hi = max(o, c) + random.uniform(0.5, 3.0)
        lo = min(o, c) - random.uniform(0.5, 3.0)
        opens.append(o); closes.append(c); highs.append(hi); lows.append(lo)

    pmin, pmax = min(lows), max(highs)
    pad_top, pad_bot = 70, 86

    def py(p):
        return pad_top + (pmax - p) / (pmax - pmin) * (H - pad_top - pad_bot)

    def px(i):
        return x0 + i * step

    # candles tenues — alpha sube hacia la derecha (entra desde la izquierda)
    cw = max(3, int(step * 0.42))
    for i in range(n):
        x = px(i)
        ramp = min(1.0, (x - x0) / (W * 0.55))   # fade-in izquierda → derecha
        a = int(26 + 52 * ramp)
        up = closes[i] >= opens[i]
        col = (*(POS if up else NEG), a)
        wick = (*(POS if up else NEG), int(a * 0.7))
        d.line([(x, py(highs[i])), (x, py(lows[i]))], fill=wick, width=2)
        yb1, yb2 = py(opens[i]), py(closes[i])
        if yb1 > yb2:
            yb1, yb2 = yb2, yb1
        d.rectangle([x - cw / 2, yb1, x + cw / 2, max(yb2, yb1 + 2)], fill=col)

    # benchmark (cielo) — línea más lenta y baja, punteada
    bench = []
    base = closes[0]
    for i in range(n):
        base += (closes[i] - base) * 0.06 + 0.55
        bench.append(base)
    bpts = [(px(i), py(bench[i])) for i in range(n)]
    for i in range(0, len(bpts) - 1, 2):  # dash
        d.line([bpts[i], bpts[i + 1]], fill=(*CIELO, 150), width=3)

    # portfolio (violeta) — suavizado, con área de glow debajo
    sm = []
    acc = closes[0]
    for c in closes:
        acc += (c - acc) * 0.32
        sm.append(acc)
    ppts = [(px(i), py(sm[i])) for i in range(n)]

    area = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(area)
    poly = ppts + [(ppts[-1][0], H), (ppts[0][0], H)]
    ad.polygon(poly, fill=(*VIOLET, 30))
    area = area.filter(ImageFilter.GaussianBlur(18))
    layer = Image.alpha_composite(layer, area)
    d = ImageDraw.Draw(layer)

    # glow de la línea + línea nítida
    glow_line = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_line)
    gd.line(ppts, fill=(*VIOLET, 130), width=9, joint="curve")
    glow_line = glow_line.filter(ImageFilter.GaussianBlur(7))
    layer = Image.alpha_composite(layer, glow_line)
    d = ImageDraw.Draw(layer)
    d.line(ppts, fill=(*VIOLET, 255), width=4, joint="curve")

    # punto final con halo
    ex, ey = ppts[-1]
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    for r in range(26, 0, -2):
        hd.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(*VIOLET, int((1 - r / 26) * 120)))
    halo = halo.filter(ImageFilter.GaussianBlur(4))
    layer = Image.alpha_composite(layer, halo)
    d = ImageDraw.Draw(layer)
    d.ellipse([ex - 6, ey - 6, ex + 6, ey + 6], fill=INK_0)
    d.ellipse([ex - 4, ey - 4, ex + 4, ey + 4], fill=VIOLET)

    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    return img


# ─── Vignette izquierda: oscurece la izq para legibilidad del texto ───────────
def left_scrim(img):
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    reach = 920
    for x in range(W):
        if x < reach:
            a = int(238 * (1 - x / reach) ** 1.15)
            sd.line([(x, 0), (x, H)], fill=(BG[0], BG[1], BG[2], a))
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")
    return img


def render():
    img = build_base()
    img = draw_chart(img)
    img = left_scrim(img)

    # Placa oscura difuminada detrás de la tagline + chips: sube el contraste
    # del texto sobre los candles sin dibujar una caja visible (bordes feathered).
    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.rounded_rectangle([40, 196, 975, 332], radius=46, fill=(*BG, 175))
    plate = plate.filter(ImageFilter.GaussianBlur(30))
    img = Image.alpha_composite(img.convert("RGBA"), plate).convert("RGB")

    d = ImageDraw.Draw(img)

    LX = 96  # margen izquierdo del bloque de texto

    # Eyebrow mono (violeta, spaced) — estilo de los posts.
    # Bloque elevado: la esquina inferior-izquierda la tapa la foto de perfil.
    eyebrow = "PORTFOLIO TRACKER · ARGENTINA"
    ey_font = F_MONO_REG(21)
    ey_y = 56
    draw_spaced(d, eyebrow, LX, ey_y, ey_font, VIOLET, spacing=3)

    # Wordmark
    wm_font = F_SANS_BOLD(92)
    wm_y = ey_y + 40
    d.text((LX - 2, wm_y), "rendi", font=wm_font, fill=INK_0)
    wm_w = d.textlength("rendi", font=wm_font)
    # acento violeta bajo el wordmark
    ul_y = wm_y + 104
    d.rounded_rectangle([LX, ul_y, LX + 60, ul_y + 5], radius=2, fill=VIOLET)

    # Tagline (sentence case, sin emoji)
    tag_font = F_SANS_REG(38)
    tag_y = ul_y + 24
    d.text((LX, tag_y), "Tu portfolio en dólares, con Coach IA", font=tag_font, fill=INK_0)

    # Sub: value props en mono. Palabras en INK_0 (máx contraste sobre el chart),
    # separadores tenues. Sin polaridad → nada de violeta (regla de marca).
    sub_font = F_MONO_REG(24)
    sub_y = tag_y + 54
    parts = [("Multi-broker", INK_0), ("   ·   ", INK_3),
             ("dólar blue", INK_0), ("   ·   ", INK_3),
             ("análisis de comportamiento", INK_0)]
    cx = LX
    for txt, col in parts:
        d.text((cx, sub_y), txt, font=sub_font, fill=col)
        cx += d.textlength(txt, font=sub_font)

    # URL (acción → violeta) abajo-derecha, lejos del avatar
    url_font = F_MONO_BOLD(28)
    url = "rendi.finance"
    uw = d.textlength(url, font=url_font)
    d.text((W - 70 - uw, H - 64), url, font=url_font, fill=VIOLET)

    # marco de precisión: hairline superior sutil
    d.line([(0, 0), (W, 0)], fill=(40, 40, 52), width=2)

    out = os.path.join(OUT_DIR, "rendi_linkedin_banner.png")
    img.save(out, "PNG")
    print("OK →", out, img.size)


if __name__ == "__main__":
    render()
