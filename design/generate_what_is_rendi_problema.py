"""
Genera el carousel "Qué es Rendi" — ángulo PROBLEMA → SOLUCIÓN.
Distinto al set de stories feature-tour (generate_what_is_rendi_stories.py).
4 slides en 1080×1350 (4:5 vertical, óptimo para feed IG).

Narrativa:
  1. Hook / problema  — "Tu plata está en 5 lugares. Ninguno te dice cuánto ganás."
  2. El caos (hoy)    — saldos sueltos, 2 monedas, sin rendimiento real
  3. Con Rendi        — una vista consolidada, USD real, vs S&P 500
  4. CTA              — "Toda tu plata. Una sola verdad."

Voz del manual: dato primero, voseo profesional, sentence case, cero emoji.
Verde/rojo solo en datos con polaridad. Cielo para benchmark. Violeta solo
en acción/énfasis.

NOTA gating: multi-broker es Plus (3) / Pro (ilimitado); Free = 1 broker
(backend/ai/plan.py). El post vende consolidación multi-broker → el CTA es
"Probalo en" (NO "gratis"), porque lo que se muestra no está en el plan Free.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

# ─── Paths ─────────────────────────────────────────────────────────────────
FONTS_DIR = (
    "/Users/nicolaspussetto/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "bcfbadf3-5949-46c4-95ea-f77e7e18d7ad/"
    "6a7d8d68-f39a-4be8-86c7-653fd22de85c/skills/canvas-design/canvas-fonts/"
)
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"

# Format feed vertical 4:5
W, H = 1080, 1350

# ─── Colors (alineados con tailwind.config.js del producto) ──────────────────
BG = (10, 11, 14)
BG_GLOW = (16, 14, 26)
CARD_BG = (15, 17, 23)
CARD_BG_2 = (20, 25, 35)
CARD_BG_PLUS = (22, 18, 38)
INK_0 = (230, 234, 242)
INK_1 = (195, 202, 216)
INK_2 = (150, 156, 172)
INK_3 = (90, 100, 120)
INK_4 = (40, 46, 60)
VIOLET = (139, 125, 255)
RENDI_POS = (54, 211, 153)
RENDI_NEG = (231, 92, 92)
AMBER = (230, 180, 70)
SKY = (91, 157, 249)
AQUA = (70, 198, 224)


# ─── Fonts ─────────────────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG  = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)
F_MONO_REG  = lambda s: font("GeistMono-Regular.ttf", s)


# ─── Helpers ───────────────────────────────────────────────────────────────
def draw_spaced_text(draw, text, x, y, font_obj, fill, spacing=4):
    cursor = x
    for ch in text:
        draw.text((cursor, y), ch, font=font_obj, fill=fill)
        cursor += draw.textlength(ch, font=font_obj) + spacing
    return cursor - x

def spaced_width(draw, text, font_obj, spacing=4):
    if not text:
        return 0
    return sum(draw.textlength(ch, font=font_obj) for ch in text) + spacing * (len(text) - 1)

def wrap_text(draw, text, font_obj, max_width):
    words = text.split()
    lines, current = [], []
    for word in words:
        test = ' '.join(current + [word])
        if draw.textlength(test, font=font_obj) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))
    return lines

def draw_hero(draw, lines, top, hero_font, accent_idx, line_h):
    """Hero centrado; la línea accent_idx en violet, el resto en INK_0."""
    ty = top
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=hero_font)
        color = VIOLET if i == accent_idx else INK_0
        draw.text((W / 2 - lw / 2, ty), line, font=hero_font, fill=color)
        ty += line_h
    return ty


def build_base_canvas():
    img = Image.new("RGB", (W, H), BG)
    dg = ImageDraw.Draw(img)
    for y in range(H):
        if y < 500:
            t = 1 - (y / 500)
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.5)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.5)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.5)
            dg.line([(0, y), (W, y)], fill=(r, g, b))
        elif y > H - 350:
            t = (y - (H - 350)) / 350
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.3)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.3)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.3)
            dg.line([(0, y), (W, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(380, 0, -10):
        alpha = int((1 - r / 380) * 16)
        gd.ellipse([W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r], fill=(*VIOLET, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    return img


def draw_header(draw, eyebrow_text):
    HEADER_TOP = 80
    logo_font = F_SANS_BOLD(44)
    logo_w = draw.textlength("rendi", font=logo_font)
    draw.text((W / 2 - logo_w / 2, HEADER_TOP), "rendi", font=logo_font, fill=INK_0)
    ul_y = HEADER_TOP + 64
    draw.line([(W / 2 - 14, ul_y), (W / 2 + 14, ul_y)], fill=VIOLET, width=2)
    eyebrow_font = F_MONO_REG(20)
    ey_w = spaced_width(draw, eyebrow_text, eyebrow_font, spacing=3)
    draw_spaced_text(draw, eyebrow_text, W / 2 - ey_w / 2, HEADER_TOP + 100, eyebrow_font, VIOLET, spacing=3)


def draw_footer(draw, current, total=4):
    dot_size, gap = 8, 14
    total_w = (dot_size * total) + (gap * (total - 1))
    start_x = (W - total_w) / 2
    y = H - 120
    for i in range(total):
        cx = start_x + i * (dot_size + gap)
        draw.ellipse([cx, y, cx + dot_size, y + dot_size], fill=VIOLET if i == current else INK_4)
    brand_font = F_MONO_REG(22)
    brand_w = draw.textlength("rendi.finance", font=brand_font)
    draw.text((W / 2 - brand_w / 2, H - 75), "rendi.finance", font=brand_font, fill=INK_2)


def draw_sub(draw, lines, y, color=INK_2, size=26, lh=38):
    f = F_SANS_REG(size)
    for line in lines:
        lw = draw.textlength(line, font=f)
        draw.text((W / 2 - lw / 2, y), line, font=f, fill=color)
        y += lh
    return y


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 1 — Hook / el problema
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_1():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ QUÉ ES RENDI · 1 DE 4")

    # Hero grande (el problema)
    draw_hero(draw, ["Tu plata está", "en 5 lugares."], 330, F_SANS_BOLD(82), -1, 100)

    # Reveal (el twist) — más chico, "de verdad." en violet
    reveal_top = 590
    rf = F_SANS_BOLD(46)
    l1 = "Ninguno te dice cuánto"
    lw1 = draw.textlength(l1, font=rf)
    draw.text((W / 2 - lw1 / 2, reveal_top), l1, font=rf, fill=INK_1)
    # línea 2 con dos colores: "ganás " (INK_1) + "de verdad." (violet)
    part_a, part_b = "ganás ", "de verdad."
    wa = draw.textlength(part_a, font=rf)
    wb = draw.textlength(part_b, font=rf)
    start_x = W / 2 - (wa + wb) / 2
    draw.text((start_x, reveal_top + 60), part_a, font=rf, fill=INK_1)
    draw.text((start_x + wa, reveal_top + 60), part_b, font=rf, fill=VIOLET)

    # Chips de los "5 lugares" (muted) — siembran la fragmentación
    chips = ["Cocos", "IOL", "Binance", "Schwab", "Excel"]
    chip_font = F_MONO_REG(22)
    chip_h = 54
    pad_x = 20
    gap = 14
    widths = [draw.textlength(c, font=chip_font) + pad_x * 2 for c in chips]
    total_w = sum(widths) + gap * (len(chips) - 1)
    cx = (W - total_w) / 2
    chips_y = 830
    for c, cw in zip(chips, widths):
        draw.rounded_rectangle([cx, chips_y, cx + cw, chips_y + chip_h], radius=12,
                               fill=CARD_BG, outline=(*INK_4, 220), width=1)
        tw = draw.textlength(c, font=chip_font)
        draw.text((cx + cw / 2 - tw / 2, chips_y + 13), c, font=chip_font, fill=INK_2)
        cx += cw + gap

    draw_sub(draw, ["Cada uno te muestra una parte.",
                    "Tu rendimiento real, completo: ninguno."],
             chips_y + chip_h + 56)

    draw_footer(draw, current=0)
    out = os.path.join(OUT_DIR, "rendi_que_es_problema_1.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 1: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 2 — El caos (hoy)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_2():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ HOY · 2 DE 4")

    # Headline
    hl_font = F_SANS_BOLD(54)
    hl = "Saldos sueltos."
    lw = draw.textlength(hl, font=hl_font)
    draw.text((W / 2 - lw / 2, 270), hl, font=hl_font, fill=INK_0)
    draw_sub(draw, ["Distintas apps. Distintas monedas."], 348, color=INK_2, size=28)

    # Grid 2×2 de broker tiles
    card_w = 390
    card_h = 165
    gap = 26
    left_x = (W - card_w * 2 - gap) / 2
    right_x = left_x + card_w + gap
    grid_top = 430

    tiles = [
        ("COCOS",   "$ 2.840.000"),
        ("IOL",     "$ 1.920.000"),
        ("BINANCE", "US$ 1.240"),
        ("SCHWAB",  "US$ 3.100"),
    ]

    def draw_tile(x, y, name, balance):
        draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=16,
                               fill=CARD_BG, outline=(*INK_4, 200), width=1)
        draw_spaced_text(draw, name, x + 28, y + 26, F_MONO_REG(19), INK_3, spacing=2)
        draw.text((x + 28, y + 58), balance, font=F_SANS_BOLD(40), fill=INK_1)
        # rendimiento real desconocido — el "?" en amber (no es polaridad)
        rl_font = F_MONO_REG(18)
        rx = x + 28
        draw.text((rx, y + 118), "rend. real", font=rl_font, fill=INK_3)
        qx = rx + draw.textlength("rend. real ", font=rl_font) + 6
        draw.text((qx, y + 118), "?", font=F_MONO_BOLD(20), fill=AMBER)

    draw_tile(left_x,  grid_top,                 *tiles[0])
    draw_tile(right_x, grid_top,                 *tiles[1])
    draw_tile(left_x,  grid_top + card_h + gap,  *tiles[2])
    draw_tile(right_x, grid_top + card_h + gap,  *tiles[3])

    grid_bottom = grid_top + card_h * 2 + gap
    draw_sub(draw, ["5 saldos en 2 monedas.",
                    "Ninguna app te da el total real."],
             grid_bottom + 50, color=INK_2, size=28, lh=42)

    draw_footer(draw, current=1)
    out = os.path.join(OUT_DIR, "rendi_que_es_problema_2.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 2: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 3 — Con Rendi (la solución)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_3():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ CON RENDI · 3 DE 4")

    # Headline
    hl_font = F_SANS_BOLD(54)
    hl = "Todo junto. En dólares."
    lw = draw.textlength(hl, font=hl_font)
    draw.text((W / 2 - lw / 2, 270), hl, font=hl_font, fill=INK_0)

    # Card consolidada (réplica del dashboard) — total + desglose por broker
    card_w = 820
    card_x = (W - card_w) / 2
    card_y = 345
    card_h = 580
    pad = 40
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                           radius=18, fill=CARD_BG, outline=(*VIOLET, 150), width=2)

    # Header de card: título + indicador de sync (aqua = brokers conectados)
    draw_spaced_text(draw, "// TODO TU PORTFOLIO · USD", card_x + pad, card_y + 30,
                     F_MONO_REG(19), INK_3, spacing=2)
    bk_text = "4 brokers"
    bk_font = F_MONO_REG(19)
    bk_w = draw.textlength(bk_text, font=bk_font)
    dot_r = 5
    draw.ellipse([card_x + card_w - pad - bk_w - 20, card_y + 36,
                  card_x + card_w - pad - bk_w - 20 + dot_r * 2, card_y + 36 + dot_r * 2],
                 fill=AQUA)
    draw.text((card_x + card_w - pad - bk_w, card_y + 30), bk_text, font=bk_font, fill=INK_2)

    # Balance consolidado (el número que frena el scroll)
    draw.text((card_x + pad, card_y + 64), "US$ 42.180", font=F_SANS_BOLD(84), fill=INK_0)

    # P&L
    pnl = "+12.4%"
    pf = F_MONO_BOLD(26)
    draw.text((card_x + pad, card_y + 176), pnl, font=pf, fill=RENDI_POS)
    pw = draw.textlength(pnl, font=pf)
    draw.text((card_x + pad + pw + 16, card_y + 180), "· USD real", font=F_MONO_REG(20), fill=INK_3)

    # Divider 1
    dv_y = card_y + 224
    draw.line([(card_x + pad, dv_y), (card_x + card_w - pad, dv_y)], fill=(*INK_4, 150), width=1)

    # Desglose por broker — los saldos sueltos de la slide 2, ya en USD y sumados.
    # Barras en AQUA (sync/neutro = brokers conectados, regla de marca).
    draw_spaced_text(draw, "// POR BROKER", card_x + pad, dv_y + 16,
                     F_MONO_REG(17), INK_3, spacing=2)
    brokers = [
        ("Schwab",  "US$ 18.400", 0.436),
        ("Cocos",   "US$ 12.300", 0.292),
        ("IOL",     "US$ 7.480",  0.177),
        ("Binance", "US$ 4.000",  0.095),
    ]
    name_f = F_SANS_REG(24)
    val_f = F_MONO_REG(23)
    bar_x0 = card_x + pad + 140
    bar_x1 = card_x + card_w - pad - 150
    bar_track = bar_x1 - bar_x0
    bar_h = 14
    row_y0 = dv_y + 52
    for i, (nm, val, share) in enumerate(brokers):
        ry = row_y0 + i * 56
        draw.text((card_x + pad, ry), nm, font=name_f, fill=INK_1)
        bar_cy = ry + 15
        draw.rounded_rectangle([bar_x0, bar_cy - bar_h / 2, bar_x1, bar_cy + bar_h / 2],
                               radius=bar_h / 2, fill=(*INK_4, 160))
        fill_w = bar_track * share
        draw.rounded_rectangle([bar_x0, bar_cy - bar_h / 2, bar_x0 + fill_w, bar_cy + bar_h / 2],
                               radius=bar_h / 2, fill=AQUA)
        vw = draw.textlength(val, font=val_f)
        draw.text((card_x + card_w - pad - vw, ry), val, font=val_f, fill=INK_0)

    # Divider 2 + benchmark (label cielo = referencia; valor verde = polaridad)
    dv2_y = row_y0 + 4 * 56 + 8
    draw.line([(card_x + pad, dv2_y), (card_x + card_w - pad, dv2_y)], fill=(*INK_4, 150), width=1)
    by = dv2_y + 22
    draw.text((card_x + pad, by), "vs S&P 500", font=F_SANS_REG(24), fill=SKY)
    v1 = "+3.2%"
    v1f = F_MONO_BOLD(24)
    v1w = draw.textlength(v1, font=v1f)
    draw.text((card_x + card_w - pad - v1w, by), v1, font=v1f, fill=RENDI_POS)

    draw_sub(draw, ["4 brokers, 2 monedas →",
                    "una sola verdad, en dólares."],
             card_y + card_h + 44, color=INK_2, size=28, lh=42)

    draw_footer(draw, current=2)
    out = os.path.join(OUT_DIR, "rendi_que_es_problema_3.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 3: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 4 — CTA
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_4():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ ESO ES RENDI · 4 DE 4")

    hero_top = 360
    hero_font = F_SANS_BOLD(82)
    l1 = "Toda tu plata."
    lw1 = draw.textlength(l1, font=hero_font)
    draw.text((W / 2 - lw1 / 2, hero_top), l1, font=hero_font, fill=INK_0)
    l2 = "Una sola verdad."
    lw2 = draw.textlength(l2, font=hero_font)
    draw.text((W / 2 - lw2 / 2, hero_top + 100), l2, font=hero_font, fill=VIOLET)

    # Bullets
    list_y = hero_top + 270
    bullets = [
        "Conectás tus brokers → una vista",
        "Tu rendimiento en USD real",
        "Sabés si le ganás al mercado",
    ]
    bullet_font = F_SANS_REG(28)
    for b in bullets:
        ix = W / 2 - 300
        iy = list_y + 8
        s = 18
        draw.line([(ix + s * 0.1, iy + s * 0.5), (ix + s * 0.42, iy + s * 0.82)], fill=VIOLET, width=3)
        draw.line([(ix + s * 0.42, iy + s * 0.82), (ix + s * 0.92, iy + s * 0.18)], fill=VIOLET, width=3)
        draw.text((ix + 36, list_y), b, font=bullet_font, fill=INK_0)
        list_y += 52

    # CTA pill — multi-broker es Plus/Pro, NO decir "gratis"
    cta_y = list_y + 70
    cta_text = "Probalo en rendi.finance"
    cta_font = F_SANS_BOLD(30)
    cta_w = draw.textlength(cta_text, font=cta_font)
    pad_x, pad_y = 34, 19
    btn_w = cta_w + pad_x * 2
    btn_h = cta_font.size + pad_y * 2
    btn_x = (W - btn_w) / 2
    draw.rounded_rectangle([btn_x, cta_y, btn_x + btn_w, cta_y + btn_h],
                           radius=btn_h // 2, fill=VIOLET)
    draw.text((btn_x + pad_x, cta_y + pad_y - 4), cta_text, font=cta_font, fill=(15, 12, 30))

    draw_footer(draw, current=3)
    out = os.path.join(OUT_DIR, "rendi_que_es_problema_4.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 4: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    generate_slide_1()
    generate_slide_2()
    generate_slide_3()
    generate_slide_4()
    print("\nDone.")
