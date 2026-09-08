"""
Carrusel para META ADS (objetivo: VENDER / conversión).
5 slides 1080×1080 (1:1 — spec de carousel ads de Meta).

Estructura de venta:
  1. HOOK      — frena el scroll: el dolor en una pregunta (thumbnail).
  2. SOLUCIÓN  — Rendi junta todo en un número, en USD (se muestra YA).
  3. CÓMO      — 3 pasos, listo en 2 minutos (baja la fricción).
  4. POR QUÉ   — diferenciadores (multi-broker, USD real, FIFO, Coach IA).
  5. CTA       — empezá gratis · rendi.finance.

Fuentes de marca (design/fonts): Geist sans + JetBrains Mono. Cero serif.
Mono = eyebrows MAYÚSCULA, números y URLs (letter-spacing). Sans = títulos/cuerpo.
Paleta exacta del brand kit. Voz: voseo, sentence case, dato-first, cero emoji.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

# ─── Paths ─────────────────────────────────────────────────────────────────
FONTS_DIR = "/Users/nicolaspussetto/Documents/trading/design/fonts"
LOGO_DIR = "/Users/nicolaspussetto/Documents/rendi 2/brand-kit/logos"
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"

W, H = 1080, 1080

# ─── Paleta (brand kit exacto) ───────────────────────────────────────────────
BG       = (7, 9, 12)        # Ink #07090C
BG_GLOW  = (16, 14, 26)
CARD_BG  = (14, 16, 22)
CARD_BG2 = (19, 17, 33)
INK_0    = (236, 238, 244)
INK_1    = (198, 204, 218)
INK_2    = (150, 158, 176)
INK_3    = (96, 104, 124)
INK_4    = (38, 44, 58)
VIOLET   = (139, 125, 255)   # #8B7DFF
GREEN    = (33, 208, 122)    # #21D07A
RED      = (255, 83, 96)     # #FF5360


# ─── Fonts ───────────────────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SEMI = lambda s: font("Geist-SemiBold.ttf", s)
F_MED  = lambda s: font("Geist-Medium.ttf", s)
F_REG  = lambda s: font("Geist-Regular.ttf", s)
MONO_M = lambda s: font("JetBrainsMono-Medium.ttf", s)
MONO_R = lambda s: font("JetBrainsMono-Regular.ttf", s)


# ─── Helpers ───────────────────────────────────────────────────────────────
def spaced_text(draw, text, x, y, fnt, fill, spacing=4):
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=fnt, fill=fill)
        cx += draw.textlength(ch, font=fnt) + spacing
    return cx - x

def spaced_w(draw, text, fnt, spacing=4):
    if not text:
        return 0
    return sum(draw.textlength(c, font=fnt) for c in text) + spacing * (len(text) - 1)

def center(draw, text, y, fnt, fill, stroke=0, stroke_fill=None):
    w = draw.textlength(text, font=fnt)
    draw.text((W / 2 - w / 2, y), text, font=fnt, fill=fill,
              stroke_width=stroke, stroke_fill=stroke_fill or fill)
    return w

def center_spaced(draw, text, y, fnt, fill, spacing=4):
    w = spaced_w(draw, text, fnt, spacing)
    spaced_text(draw, text, W / 2 - w / 2, y, fnt, fill, spacing)
    return w


def base_canvas():
    img = Image.new("RGB", (W, H), BG)
    dg = ImageDraw.Draw(img)
    for y in range(H):
        if y < 460:
            t = 1 - (y / 460)
            dg.line([(0, y), (W, y)], fill=tuple(
                int(BG[i] + (BG_GLOW[i] - BG[i]) * t * 0.55) for i in range(3)))
        elif y > H - 320:
            t = (y - (H - 320)) / 320
            dg.line([(0, y), (W, y)], fill=tuple(
                int(BG[i] + (BG_GLOW[i] - BG[i]) * t * 0.32) for i in range(3)))
    # violet glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(420, 0, -10):
        a = int((1 - r / 420) * 15)
        gd.ellipse([W // 2 - r, 430 - r, W // 2 + r, 430 + r], fill=(*VIOLET, a))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


_logo_cache = {}
def logo(mh):
    key = mh
    if key not in _logo_cache:
        m = Image.open(os.path.join(LOGO_DIR, "rendi-mark-violet.png")).convert("RGBA")
        mw = int(m.width * mh / m.height)
        _logo_cache[key] = m.resize((mw, mh), Image.LANCZOS)
    return _logo_cache[key]


def header(img, draw, eyebrow):
    top = 74
    mark = logo(38)
    wf = F_SEMI(36)
    word = "rendi"
    ww = draw.textlength(word, font=wf)
    gap = 13
    total = mark.width + gap + ww
    x0 = (W - total) / 2
    img.paste(mark, (int(x0), top), mark)
    draw.text((x0 + mark.width + gap, top + 1), word, font=wf, fill=INK_0)
    center_spaced(draw, eyebrow, top + 64, MONO_R(19), VIOLET, spacing=3)


def footer(img, draw, current, total=5):
    ds, gap = 7, 13
    tw = ds * total + gap * (total - 1)
    sx = (W - tw) / 2
    y = H - 96
    for i in range(total):
        cx = sx + i * (ds + gap)
        draw.ellipse([cx, y, cx + ds, y + ds], fill=VIOLET if i == current else INK_4)
    center(draw, "rendi.finance", H - 66, MONO_R(21), INK_2)


def sub_lines(draw, lines, y, color=INK_2, fnt=None, lh=37):
    fnt = fnt or F_REG(25)
    for ln in lines:
        center(draw, ln, y, fnt, color)
        y += lh
    return y


# ═════════════════════════════ SLIDE 1 — HOOK ═══════════════════════════════
def slide_1():
    img = base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, "/ TU PORTFOLIO, SIN VUELTAS")

    center(draw, "¿Cuánto ganaste", 300, F_SEMI(88), INK_0)
    center(draw, "de verdad?", 396, F_SEMI(88), VIOLET)

    sub_lines(draw, [
        "Tenés la plata repartida en varios brokers.",
        "Tu rendimiento real en dólares no lo ves en ninguno.",
    ], 540, INK_1, F_REG(27), lh=40)

    # broker chips + un "US$ ?" que representa el dato que falta
    chips = ["COCOS", "IOL", "BINANCE", "SCHWAB"]
    cf = MONO_R(20)
    pad = 20
    widths = [draw.textlength(c, font=cf) + pad * 2 for c in chips]
    gap = 14
    total = sum(widths) + gap * (len(chips) - 1)
    x = (W - total) / 2
    cy = 690
    for c, w in zip(chips, widths):
        draw.rounded_rectangle([x, cy, x + w, cy + 46], radius=23,
                               fill=CARD_BG, outline=(*INK_4, 220), width=1)
        draw.text((x + pad, cy + 11), c, font=cf, fill=INK_2)
        x += w + gap

    # tarjeta del "número que no ves"
    card_w, card_h = 560, 150
    cx = (W - card_w) / 2
    cyy = 786
    draw.rounded_rectangle([cx, cyy, cx + card_w, cyy + card_h], radius=18,
                           fill=CARD_BG, outline=(*VIOLET, 90), width=1)
    center_spaced(draw, "// TU RESULTADO REAL EN USD", cyy + 26, MONO_R(18), INK_3, spacing=2)
    center(draw, "US$ ?", cyy + 56, F_SEMI(70), INK_3)

    footer(img, draw, 0)
    save(img, "rendi_ads_carousel_1.png", 1)


# ══════════════════════════ SLIDE 2 — SOLUCIÓN ══════════════════════════════
def slide_2():
    img = base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, "/ RENDI LO JUNTA TODO")

    center(draw, "Una cartera.", 286, F_SEMI(82), INK_0)
    center(draw, "Un número. En USD.", 374, F_SEMI(82), INK_0)

    # ── tarjeta dashboard: el resultado consolidado ──
    card_w, card_h = 760, 350
    cx = (W - card_w) / 2
    cy = 520
    draw.rounded_rectangle([cx, cy, cx + card_w, cy + card_h], radius=20,
                           fill=CARD_BG, outline=(*GREEN, 110), width=1)
    pad = 40
    spaced_text(draw, "// RESULTADO TOTAL · AL DÓLAR DEL DÍA",
                cx + pad, cy + 30, MONO_R(19), INK_3, spacing=2)
    draw.text((cx + pad, cy + 66), "+US$ 3.420", font=F_SEMI(96), fill=GREEN)
    spaced_text(draw, "+18,2%  ·  3 BROKERS  ·  FIFO APLICADO",
                cx + pad, cy + 184, MONO_R(20), INK_2, spacing=1)

    # divider + brokers que alimentan el número
    dvy = cy + 238
    draw.line([(cx + pad, dvy), (cx + card_w - pad, dvy)], fill=(*INK_4, 160), width=1)
    rows = [("Cocos", "+US$ 1.910", GREEN), ("IOL", "+US$ 1.140", GREEN), ("Binance", "+US$ 370", GREEN)]
    bx = cx + pad
    bw = (card_w - pad * 2) / 3
    for lbl, val, col in rows:
        draw.text((bx, dvy + 24), lbl, font=F_REG(22), fill=INK_2)
        draw.text((bx, dvy + 52), val, font=MONO_M(24), fill=col)
        bx += bw

    sub_lines(draw, [
        "Conectás tus brokers y Rendi consolida todo:",
        "P&L real en dólares, no el saldo en pesos.",
    ], cy + card_h + 40, INK_1, F_REG(26), lh=38)

    footer(img, draw, 1)
    save(img, "rendi_ads_carousel_2.png", 2)


# ═══════════════════════════ SLIDE 3 — CÓMO ═════════════════════════════════
def slide_3():
    img = base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, "/ EN 3 PASOS")

    center(draw, "Listo en 2 minutos.", 300, F_SEMI(84), INK_0)

    steps = [
        ("1", "Subís el CSV de movimientos de tu broker"),
        ("2", "Rendi reconstruye la cartera entera, sola"),
        ("3", "Ves tu P&L real en dólares — FIFO ya hecho"),
    ]
    y = 438
    row_h = 138
    box_w = 800
    bx = (W - box_w) / 2
    for num, txt in steps:
        # círculo violeta con número (mono)
        r = 30
        ccx, ccy = bx + r, y + r
        draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=(*VIOLET, 38),
                     outline=VIOLET, width=2)
        nf = MONO_M(30)
        nw = draw.textlength(num, font=nf)
        draw.text((ccx - nw / 2, ccy - 21), num, font=nf, fill=VIOLET)
        # texto del paso (wrap a 2 líneas si hace falta)
        tf = F_MED(31)
        tx = bx + 80
        from_lines = wrap(draw, txt, tf, box_w - 90)
        ty = y + r - (len(from_lines) * 38) / 2 + 4
        for ln in from_lines:
            draw.text((tx, ty), ln, font=tf, fill=INK_0)
            ty += 38
        # conector punteado entre pasos
        if num != "3":
            for dy in range(0, row_h - 60, 14):
                draw.line([(ccx, ccy + r + dy), (ccx, ccy + r + dy + 6)], fill=INK_4, width=2)
        y += row_h

    sub_lines(draw, ["Sin cargar operación por operación.",
                     "El mismo CSV que ya te da tu broker."],
              y + 6, INK_2, F_REG(25), lh=37)

    footer(img, draw, 2)
    save(img, "rendi_ads_carousel_3.png", 3)


def wrap(draw, text, fnt, max_w):
    words = text.split()
    lines, cur = [], []
    for w in words:
        if draw.textlength(' '.join(cur + [w]), font=fnt) <= max_w:
            cur.append(w)
        else:
            if cur:
                lines.append(' '.join(cur))
            cur = [w]
    if cur:
        lines.append(' '.join(cur))
    return lines


# ═══════════════════════════ SLIDE 4 — POR QUÉ ══════════════════════════════
def slide_4():
    img = base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, "/ POR QUÉ RENDI")

    center(draw, "Pensado para el", 286, F_SEMI(78), INK_0)
    center(draw, "inversor argentino.", 372, F_SEMI(78), VIOLET)

    feats = [
        ("MULTI-BROKER", ["Cocos, IOL, Binance,", "Schwab y más"]),
        ("USD REAL", ["Convertido al dólar", "blue del día"]),
        ("FIFO AUTOMÁTICO", ["Criterio fiscal AR", "aplicado al vender"]),
        ("COACH IA", ["Con memoria de", "tu cartera"]),
    ]
    gw, gh = 372, 180
    gx_gap, gy_gap = 28, 24
    gx0 = (W - (gw * 2 + gx_gap)) / 2
    gy0 = 510
    for i, (title, body) in enumerate(feats):
        col, row = i % 2, i // 2
        x = gx0 + col * (gw + gx_gap)
        y = gy0 + row * (gh + gy_gap)
        draw.rounded_rectangle([x, y, x + gw, y + gh], radius=18,
                               fill=CARD_BG, outline=(*INK_4, 200), width=1)
        # acento violeta arriba-izq
        draw.rounded_rectangle([x + 30, y + 30, x + 30 + 34, y + 30 + 4], radius=2, fill=VIOLET)
        spaced_text(draw, title, x + 30, y + 48, MONO_M(21), INK_0, spacing=1)
        ty = y + 88
        for ln in body:
            draw.text((x + 30, ty), ln, font=F_REG(23), fill=INK_2)
            ty += 32

    footer(img, draw, 3)
    save(img, "rendi_ads_carousel_4.png", 4)


# ═══════════════════════════ SLIDE 5 — CTA ══════════════════════════════════
def slide_5():
    img = base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, "/ EMPEZÁ HOY")

    # logo mark grande centrado
    mark = logo(110)
    img.paste(mark, (int((W - mark.width) / 2), 250), mark)

    center(draw, "Empezá gratis.", 410, F_SEMI(96), INK_0)
    sub_lines(draw, ["Tu cartera consolidada en dólares,",
                     "con P&L real y Coach IA. Hoy."],
              548, INK_1, F_REG(29), lh=44)

    # CTA pill violeta
    cta = "Creá tu cuenta en rendi.finance"
    cf = F_SEMI(32)
    cw = draw.textlength(cta, font=cf)
    px, py = 40, 22
    bw, bh = cw + px * 2, cf.size + py * 2
    bx = (W - bw) / 2
    by = 700
    # glow del botón
    gl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gld = ImageDraw.Draw(gl)
    gld.rounded_rectangle([bx - 6, by - 6, bx + bw + 6, by + bh + 6], radius=bh // 2 + 6, fill=(*VIOLET, 70))
    gl = gl.filter(ImageFilter.GaussianBlur(22))
    img.paste(Image.alpha_composite(img.convert("RGBA"), gl).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=VIOLET)
    draw.text((bx + px, by + py - 3), cta, font=cf, fill=(12, 10, 26))

    center_spaced(draw, "GRATIS PARA EMPEZAR · SIN TARJETA", by + bh + 36, MONO_R(19), INK_3, spacing=2)

    footer(img, draw, 4)
    save(img, "rendi_ads_carousel_5.png", 5)


def save(img, name, n):
    out = os.path.join(OUT_DIR, name)
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide {n}: {name} ({os.path.getsize(out) / 1024:.1f}KB)")


if __name__ == "__main__":
    slide_1()
    slide_2()
    slide_3()
    slide_4()
    slide_5()
    print("\nDone — 5 slides 1080×1080.")
