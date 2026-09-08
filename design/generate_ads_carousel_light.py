"""
Carrusel META ADS — versión CLARA/cálida (no la dark). 3 slides 1080×1080 (1:1).
Objetivo: vender. Gancho rápido + comparación vs inflación y S&P 500.

  1. HOOK    — la pregunta: todos tus brokers en un lugar + rendimiento en USD,
               contra la inflación y el S&P 500.
  2. 3 PASOS — creás cuenta en rendi.finance → importás el CSV → listo.
  3. PAYOFF  — la comparación (tu cartera vs S&P vs inflación) + CTA gratis.

Estética: fondo Frost, tarjetas blancas con sombra suave, acentos violeta/verde
legibles sobre claro. Fuentes de marca reales: Geist sans + JetBrains Mono
(design/fonts). Cero serif. Voz: voseo, sentence case, dato-first, cero emoji.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

FONTS_DIR = "/Users/nicolaspussetto/Documents/trading/design/fonts"
LOGO_DIR = "/Users/nicolaspussetto/Documents/rendi 2/brand-kit/logos"
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"
W, H = 1080, 1080

# ─── Paleta clara (legible) ──────────────────────────────────────────────────
FROST      = (245, 243, 251)
FROST_WARM = (250, 248, 252)
INK_STRONG = (17, 19, 26)
INK_BODY   = (52, 56, 68)
INK_MUTE   = (120, 124, 140)
INK_FAINT  = (182, 184, 198)
WHITE      = (255, 255, 255)
CARD_BORDER = (228, 224, 240)
TRACK      = (232, 229, 244)
VIOLET     = (139, 125, 255)
VIOLET_INK = (96, 80, 222)
VIOLET_SOFT = (176, 165, 250)
GREEN      = (20, 168, 92)
GREEN_BAR  = (38, 190, 110)
RED        = (224, 64, 78)
SKY        = (70, 140, 235)


# ─── Fonts (marca real) ──────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SEMI = lambda s: font("Geist-SemiBold.ttf", s)
F_MED  = lambda s: font("Geist-Medium.ttf", s)
F_REG  = lambda s: font("Geist-Regular.ttf", s)
MONO_M = lambda s: font("JetBrainsMono-Medium.ttf", s)
MONO_R = lambda s: font("JetBrainsMono-Regular.ttf", s)


def mix(fg, bg, a):
    return tuple(int(bg[i] + (fg[i] - bg[i]) * a) for i in range(3))


# ─── Helpers texto ───────────────────────────────────────────────────────────
def sw(d, t, f, sp=4):
    return sum(d.textlength(c, font=f) for c in t) + sp * (len(t) - 1) if t else 0

def spaced(d, t, x, y, f, fill, sp=4):
    cx = x
    for c in t:
        d.text((cx, y), c, font=f, fill=fill)
        cx += d.textlength(c, font=f) + sp
    return cx - x

def cen(d, t, y, f, fill):
    w = d.textlength(t, font=f)
    d.text((W / 2 - w / 2, y), t, font=f, fill=fill)
    return w

def cen_spaced(d, t, y, f, fill, sp=4):
    w = sw(d, t, f, sp)
    spaced(d, t, W / 2 - w / 2, y, f, fill, sp)
    return w

def cen_seg(d, segs, y, f):
    total = sum(d.textlength(t, font=f) for t, _ in segs)
    x = (W - total) / 2
    for t, c in segs:
        d.text((x, y), t, font=f, fill=c)
        x += d.textlength(t, font=f)

def wrap(d, text, f, mw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= mw:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ─── Canvas + chrome ─────────────────────────────────────────────────────────
def canvas():
    img = Image.new("RGBA", (W, H), (*FROST, 255))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = max(0.0, 1 - y / (H * 0.7))
        d.line([(0, y), (W, y)], fill=tuple(
            int(FROST[i] + (FROST_WARM[i] - FROST[i]) * t) for i in range(3)) + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(480, 0, -12):
        gd.ellipse([W // 2 - r, 150 - r, W // 2 + r, 150 + r], fill=(*VIOLET, int((1 - r / 480) * 9)))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    return Image.alpha_composite(img, glow)


_logo = {}
def logo(h):
    if h not in _logo:
        m = Image.open(os.path.join(LOGO_DIR, "rendi-mark-ink.png")).convert("RGBA")
        _logo[h] = m.resize((int(m.width * h / m.height), h), Image.LANCZOS)
    return _logo[h]


def soft_card(img, box, radius=26, fill=WHITE, border=CARD_BORDER,
              sa=42, sb=34, sdy=16):
    x0, y0, x1, y1 = box
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + sdy, x1, y1 + sdy], radius=radius,
                                         fill=(74, 62, 128, sa))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(sb)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=1)
    return d


def header(img, eyebrow):
    d = ImageDraw.Draw(img, "RGBA")
    mark = logo(36)
    wf = F_SEMI(34)
    word = "rendi"
    ww = d.textlength(word, font=wf)
    gap = 12
    x0 = (W - (mark.width + gap + ww)) / 2
    img.alpha_composite(mark, (int(x0), 70))
    d.text((x0 + mark.width + gap, 71), word, font=wf, fill=INK_STRONG)
    cen_spaced(d, eyebrow.upper(), 132, MONO_R(18), VIOLET_INK, sp=3)
    return d


def footer(img, current, total=3):
    d = ImageDraw.Draw(img, "RGBA")
    dot, gap = 8, 14
    sx = (W - (dot * total + gap * (total - 1))) / 2
    y = H - 92
    for i in range(total):
        cx = sx + i * (dot + gap)
        d.ellipse([cx, y, cx + dot, y + dot], fill=VIOLET if i == current else INK_FAINT)
    cen(d, "rendi.finance", H - 64, MONO_R(20), INK_MUTE)


def chip_row(d, img, chips, y):
    cf = MONO_R(20)
    pad = 19
    widths = [d.textlength(c, font=cf) + pad * 2 + 22 for c in chips]
    gap = 13
    x = (W - (sum(widths) + gap * (len(chips) - 1))) / 2
    for c, w in zip(chips, widths):
        d.rounded_rectangle([x, y, x + w, y + 48], radius=24, fill=WHITE, outline=CARD_BORDER, width=1)
        d.ellipse([x + pad, y + 18, x + pad + 11, y + 29], fill=VIOLET_SOFT)
        d.text((x + pad + 22, y + 13), c, font=cf, fill=INK_BODY)
        x += w + gap


# ════════════════════════════ SLIDE 1 — HOOK ════════════════════════════════
def slide_1():
    img = canvas()
    d = header(img, "/ tu rendimiento real")

    # GANCHO: ¿tus inversiones le ganan a los benchmarks? (en dólares)
    cen(d, "¿Tus inversiones", 278, F_SEMI(62), INK_STRONG)
    cen_seg(d, [("le ganan al ", INK_STRONG), ("S&P 500", GREEN)], 358, F_SEMI(62))
    cen_seg(d, [("y a la ", INK_STRONG), ("inflación", VIOLET_INK), ("?", INK_STRONG)], 438, F_SEMI(62))

    cen(d, "Tu rendimiento real en dólares, comparado", 566, F_REG(30), INK_BODY)
    cen(d, "con los benchmarks que de verdad importan.", 608, F_REG(30), INK_BODY)

    # beneficio secundario (el gráfico va en la slide 3 para no spoilear)
    cen(d, "Y todos tus brokers, en un solo lugar.", 684, F_REG(26), INK_MUTE)
    chip_row(d, img, ["COCOS", "IOL", "BINANCE", "SCHWAB"], 776)

    footer(img, 0)
    save(img, "rendi_ads_light_1.png", 1)


# ═══════════════════════════ SLIDE 2 — 3 PASOS ══════════════════════════════
def slide_2():
    img = canvas()
    d = header(img, "/ así de fácil")

    cen(d, "Listo en 3 pasos.", 204, F_SEMI(72), INK_STRONG)

    steps = [
        ("1", "Entrás a rendi.finance", "y creás tu cuenta gratis."),
        ("2", "Importás el CSV", "de movimientos de tu broker."),
        ("3", "Listo.", "Ves tu cartera entera, en dólares."),
    ]
    cx, cy, cw = 120, 312, 840
    ch = 432
    d = soft_card(img, [cx, cy, cx + cw, cy + ch], radius=30)
    pad = 52
    ix = cx + pad
    rh = (ch - pad) / 3
    for i, (num, t1, t2) in enumerate(steps):
        ry = cy + pad / 2 + i * rh + 20
        # círculo violeta + número (mono)
        r = 32
        ccx, ccy = ix + r, ry + r
        d.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=mix(VIOLET, WHITE, 0.14), outline=VIOLET, width=2)
        nf = MONO_M(30)
        nw = d.textlength(num, font=nf)
        d.text((ccx - nw / 2, ccy - 21), num, font=nf, fill=VIOLET_INK)
        # texto: línea fuerte + línea de apoyo
        tx = ix + 86
        d.text((tx, ry + 4), t1, font=F_SEMI(33), fill=INK_STRONG)
        d.text((tx, ry + 46), t2, font=F_REG(27), fill=INK_BODY)
        # conector
        if num != "3":
            for dy in range(0, int(rh - 64), 13):
                d.line([(ccx, ccy + r + dy), (ccx, ccy + r + dy + 5)], fill=CARD_BORDER, width=2)

    cen(d, "Sin planillas. Sin cargar nada a mano.", cy + ch + 40, F_REG(25), INK_MUTE)

    # CTA — cierra el carrusel (última slide en el orden del anuncio)
    cta = "Empezá gratis en rendi.finance"
    cf = F_SEMI(31)
    cwd = d.textlength(cta, font=cf)
    pxx, pyy = 38, 21
    bw, bh = cwd + pxx * 2, cf.size + pyy * 2
    bx, by2 = (W - bw) / 2, cy + ch + 92
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([bx, by2 + 8, bx + bw, by2 + bh + 8], radius=bh // 2, fill=(96, 80, 222, 70))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([bx, by2, bx + bw, by2 + bh], radius=bh // 2, fill=VIOLET)
    d.text((bx + pxx, by2 + pyy - 3), cta, font=cf, fill=WHITE)

    footer(img, 2)
    save(img, "rendi_ads_light_2.png", 2)


# ════════════════════════ SLIDE 3 — PAYOFF + CTA ════════════════════════════
def slide_3():
    img = canvas()
    d = header(img, "/ la respuesta")

    cen(d, "Acá lo ves,", 236, F_SEMI(68), INK_STRONG)
    cen(d, "sin vueltas.", 318, F_SEMI(68), INK_STRONG)

    # ── tarjeta comparación ──
    cx, cy, cw = 120, 410, 840
    ch = 360
    d = soft_card(img, [cx, cy, cx + cw, cy + ch], radius=30)
    pad = 46
    ix = cx + pad
    iw = cw - pad * 2
    spaced(d, "TU RENDIMIENTO ESTE AÑO · EN USD", ix, cy + 34, MONO_R(19), INK_MUTE, sp=2)

    comp = [
        ("Tu cartera", "+18,2%", 1.00, GREEN_BAR, INK_STRONG),
        ("S&P 500", "+12,4%", 0.68, SKY, INK_BODY),
        ("Inflación (USD)", "+4,1%", 0.23, INK_FAINT, INK_BODY),
    ]
    ry = cy + 92
    for name, val, frac, col, namecol in comp:
        d.text((ix, ry), name, font=F_MED(29), fill=namecol)
        vf = MONO_M(28)
        vcol = GREEN if name == "Tu cartera" else INK_MUTE
        d.text((ix + iw - d.textlength(val, font=vf), ry - 1), val, font=vf, fill=vcol)
        by = ry + 44
        d.rounded_rectangle([ix, by, ix + iw, by + 12], radius=6, fill=TRACK)
        d.rounded_rectangle([ix, by, ix + int(iw * frac), by + 12], radius=6, fill=col)
        ry += 92

    cen(d, "Ejemplo ilustrativo", cy + ch + 26, F_REG(20), INK_FAINT)

    # ── CTA pill violeta ──
    cta = "Empezá gratis en rendi.finance"
    cf = F_SEMI(31)
    cwd = d.textlength(cta, font=cf)
    px, py = 38, 21
    bw, bh = cwd + px * 2, cf.size + py * 2
    bx, by = (W - bw) / 2, cy + ch + 70
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([bx, by + 8, bx + bw, by + bh + 8], radius=bh // 2, fill=(96, 80, 222, 70))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=VIOLET)
    d.text((bx + px, by + py - 3), cta, font=cf, fill=WHITE)

    footer(img, 2)
    save(img, "rendi_ads_light_3.png", 3)


def save(img, name, n):
    out = os.path.join(OUT_DIR, name)
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"✓ slide {n}: {name} ({os.path.getsize(out) / 1024:.1f}KB)")


if __name__ == "__main__":
    slide_1()
    slide_2()
    slide_3()
    print("\nDone — 3 slides claras 1080×1080.")
