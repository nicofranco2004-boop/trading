"""
Genera el carousel "Qué es Rendi" — ángulo CÓMO FUNCIONA EN 3 PASOS.
Distinto a los dos sets previos:
  - generate_what_is_rendi_stories.py  → feature tour (historia destacada)
  - generate_what_is_rendi_problema.py → problema/fragmentación → solución
Este responde "qué es" mostrando el MECANISMO (conectás → consolidás → entendés),
que ninguna pieza mostró todavía. 5 slides en 1080×1350 (4:5, feed IG).

Narrativa:
  1. Intro        — "Rendi, en 3 pasos." + mini-stepper del recorrido
  2. Paso 1       — Conectás tus brokers (import / carga)
  3. Paso 2       — Lo ve todo junto, en USD real (card consolidada)
  4. Paso 3       — Sabés si ganás y cómo decidís (benchmark + sesgo)
  5. CTA          — "Tres pasos. Toda tu plata, clara."

Voz del manual: dato primero, voseo profesional, sentence case, cero emoji,
cero lenguaje motivacional. Violeta SOLO en acción/énfasis (números de paso,
CTA). Verde/rojo SOLO en datos con polaridad (P&L, vs S&P). Cielo = benchmark.
Aqua = sync/brokers conectados. Ámbar = sesgo (no es polaridad de dato).

Gating: multi-broker es Plus/Pro y comportamiento es Plus (NO Free) → el CTA es
"Probalo en rendi.finance" (NO "gratis"), porque lo que se muestra no vive en
el plan Free.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import math
import numpy as np

# ─── Paths ─────────────────────────────────────────────────────────────────
FONTS_DIR = (
    "/Users/nicolaspussetto/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "bcfbadf3-5949-46c4-95ea-f77e7e18d7ad/"
    "6a7d8d68-f39a-4be8-86c7-653fd22de85c/skills/canvas-design/canvas-fonts/"
)
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"
# Capturas REALES de la app (demo mode) recortadas para los pasos 2 y 3.
CAPS_DIR = "/Users/nicolaspussetto/Documents/trading/design/_caps"

# Format feed vertical 4:5
W, H = 1080, 1350
TOTAL_SLIDES = 5

# ─── Colors (alineados con tailwind.config.js del producto) ──────────────────
BG = (10, 11, 14)
BG_GLOW = (16, 14, 26)
CARD_BG = (15, 17, 23)
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

def center_text(draw, text, y, font_obj, fill):
    lw = draw.textlength(text, font=font_obj)
    draw.text((W / 2 - lw / 2, y), text, font=font_obj, fill=fill)
    return lw


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
        gd.ellipse([W // 2 - r, H // 2 - 120 - r, W // 2 + r, H // 2 - 120 + r], fill=(*VIOLET, alpha))
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


def draw_footer(draw, current, total=TOTAL_SLIDES):
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


def draw_sub(draw, lines, y, color=INK_2, size=28, lh=40):
    f = F_SANS_REG(size)
    for line in lines:
        lw = draw.textlength(line, font=f)
        draw.text((W / 2 - lw / 2, y), line, font=f, fill=color)
        y += lh
    return y


def draw_step_badge(draw, n, cy, r=66):
    """Nodo de paso: anillo violeta + numeral centrado. cx = centro del canvas."""
    cx = W / 2
    # Glow suave detrás del badge
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*VIOLET, 90), width=2)
    draw.ellipse([cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8], fill=(*VIOLET, 14))
    num_font = F_SANS_BOLD(74)
    bbox = draw.textbbox((0, 0), str(n), font=num_font)
    nw = bbox[2] - bbox[0]
    nh = bbox[3] - bbox[1]
    draw.text((cx - nw / 2 - bbox[0], cy - nh / 2 - bbox[1]), str(n), font=num_font, fill=VIOLET)
    # Mini-eyebrow "PASO" arriba del badge
    pf = F_MONO_REG(18)
    pw = spaced_width(draw, "PASO", pf, spacing=3)
    draw_spaced_text(draw, "PASO", cx - pw / 2, cy - r - 38, pf, INK_3, spacing=3)


def draw_screenshot_card(base_img, png_path, top, target_w, crop=None,
                         radius=26, border=VIOLET, border_alpha=150, shadow=True):
    """Pega una captura real de la app, recortada y con esquinas redondeadas +
    borde sutil, centrada horizontalmente. Devuelve el bottom Y del card."""
    shot = Image.open(png_path).convert("RGB")
    if crop:
        shot = shot.crop(crop)  # (left, top, right, bottom)
    scale = target_w / shot.width
    target_h = int(round(shot.height * scale))
    shot = shot.resize((target_w, target_h), Image.LANCZOS)
    x = int(round(W / 2 - target_w / 2))

    # Sombra suave detrás del card
    if shadow:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.rounded_rectangle([x - 6, top + 10, x + target_w + 6, top + target_h + 18],
                             radius=radius + 6, fill=(0, 0, 0, 150))
        sh = sh.filter(ImageFilter.GaussianBlur(22))
        base_img.paste(Image.alpha_composite(base_img.convert("RGBA"), sh).convert("RGB"), (0, 0))

    # Máscara redondeada
    mask = Image.new("L", (target_w, target_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, target_w - 1, target_h - 1],
                                           radius=radius, fill=255)
    base_img.paste(shot, (x, top), mask)

    # Borde
    bd = ImageDraw.Draw(base_img, "RGBA")
    bd.rounded_rectangle([x, top, x + target_w - 1, top + target_h - 1],
                         radius=radius, outline=(*border, border_alpha), width=2)
    return top + target_h


def paste_capture(base_img, png_path, top, target_w, cx=None):
    """Pega una captura REAL de la app, escalada a target_w y centrada en cx
    (default: centro del canvas). SIN máscara ni marco: el negro de la app
    (~7,9,12) se normaliza al fondo del slide para que no se vea el rectángulo,
    y cada tarjeta trae su propio borde (verde el benchmark, ámbar el sesgo).
    Es el "utilizá lo real" del brief: nada de mockups dibujados. Devuelve el
    bottom Y de la captura pegada."""
    shot = Image.open(png_path).convert("RGB")

    # Igualar el casi-negro de la app al fondo del slide (BG). Solo toca pixeles
    # del fondo de página; los fills de tarjeta (≥(15,17,23)) quedan intactos.
    arr = np.asarray(shot).astype(np.int16)
    bg_mask = ((np.abs(arr[:, :, 0] - 7) <= 5) &
               (np.abs(arr[:, :, 1] - 9) <= 5) &
               (np.abs(arr[:, :, 2] - 12) <= 6))
    arr[bg_mask] = BG
    shot = Image.fromarray(arr.astype(np.uint8))

    scale = target_w / shot.width
    target_h = int(round(shot.height * scale))
    shot = shot.resize((target_w, target_h), Image.LANCZOS)
    if cx is None:
        cx = W / 2
    x = int(round(cx - target_w / 2))
    base_img.paste(shot, (x, top))
    return top + target_h


def draw_chip_row(draw, chips, y, special_last=False, font_size=22, muted=False):
    chip_font = F_MONO_REG(font_size)
    chip_h = 54
    pad_x, gap = 20, 13
    widths = [draw.textlength(c, font=chip_font) + pad_x * 2 for c in chips]
    total_w = sum(widths) + gap * (len(chips) - 1)
    cx = (W - total_w) / 2
    for i, (c, cw) in enumerate(zip(chips, widths)):
        is_special = special_last and i == len(chips) - 1
        if is_special:
            draw.rounded_rectangle([cx, y, cx + cw, y + chip_h], radius=12,
                                   fill=(*VIOLET, 14), outline=(*VIOLET, 160), width=1)
            tc = VIOLET
        else:
            draw.rounded_rectangle([cx, y, cx + cw, y + chip_h], radius=12,
                                   fill=CARD_BG, outline=(*INK_4, 220), width=1)
            tc = INK_2 if muted else INK_1
        tw = draw.textlength(c, font=chip_font)
        draw.text((cx + cw / 2 - tw / 2, y + 13), c, font=chip_font, fill=tc)
        cx += cw + gap
    return y + chip_h


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 1 — Intro + mini-stepper del recorrido
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_1():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ CÓMO FUNCIONA · 1 DE 5")

    # Hero
    hero_font = F_SANS_BOLD(86)
    center_text(draw, "Rendi,", 320, hero_font, INK_0)
    center_text(draw, "en 3 pasos.", 320 + 104, hero_font, VIOLET)

    # Mini-stepper horizontal: 3 nodos + línea + labels
    nodes = ["Conectás", "Ves todo", "Entendés"]
    node_r = 26
    cy = 720
    span = 720  # ancho total entre centros de nodos extremos
    x0 = W / 2 - span / 2
    centers = [x0 + span * (i / (len(nodes) - 1)) for i in range(len(nodes))]
    # Línea conectora
    draw.line([(centers[0], cy), (centers[-1], cy)], fill=(*INK_4, 220), width=2)
    label_font = F_MONO_REG(22)
    num_font = F_SANS_BOLD(26)
    for i, (cxn, label) in enumerate(zip(centers, nodes)):
        draw.ellipse([cxn - node_r, cy - node_r, cxn + node_r, cy + node_r],
                     fill=BG, outline=VIOLET, width=2)
        draw.ellipse([cxn - node_r + 6, cy - node_r + 6, cxn + node_r - 6, cy + node_r - 6],
                     fill=(*VIOLET, 16))
        nstr = str(i + 1)
        nbb = draw.textbbox((0, 0), nstr, font=num_font)
        nw = nbb[2] - nbb[0]
        nh = nbb[3] - nbb[1]
        draw.text((cxn - nw / 2 - nbb[0], cy - nh / 2 - nbb[1]), nstr, font=num_font, fill=VIOLET)
        lw = draw.textlength(label, font=label_font)
        draw.text((cxn - lw / 2, cy + node_r + 22), label, font=label_font, fill=INK_2)

    # Sub
    draw_sub(draw,
             ["De saldos sueltos en varias apps",
              "a una sola verdad, en dólares y en pesos."],
             900, color=INK_2, size=30, lh=44)

    draw_footer(draw, current=0)
    _save(img, "rendi_que_es_pasos_1.png", "slide 1 (intro)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 2 — Paso 1: Conectás tus brokers
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_2():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ PASO 1 · 2 DE 5")

    draw_step_badge(draw, 1, 330)

    center_text(draw, "Conectás tus brokers.", 450, F_SANS_BOLD(58), INK_0)

    # Chips de brokers (variedad, sin número cerrado)
    y = draw_chip_row(draw, ["Cocos", "IOL", "Schwab", "Binance"], 580)
    draw_chip_row(draw, ["Balanz", "Lemon", "IBKR", "+ más"], y + 14, special_last=True)

    draw_sub(draw,
             ["Importás el CSV de tu broker,",
              "o cargás tus operaciones a mano."],
             y + 14 + 54 + 56, color=INK_2, size=30, lh=44)

    draw_sub(draw,
             ["Las mantenés vos al día. Rendi hace los números."],
             y + 14 + 54 + 56 + 110, color=INK_3, size=25, lh=36)

    draw_footer(draw, current=1)
    _save(img, "rendi_que_es_pasos_2.png", "slide 2 (paso 1)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 3 — Paso 2: Lo ve todo junto, en USD real
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_3():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ PASO 2 · 3 DE 5")

    draw_step_badge(draw, 2, 330)

    center_text(draw, "Toda tu cartera,", 450, F_SANS_BOLD(58), INK_0)
    center_text(draw, "en dólares o en pesos.", 522, F_SANS_BOLD(50), VIOLET)

    # Capturas REALES de Rendi (demo mode), no mockups:
    #   1) el total consolidado en USD ("ves todo en una cifra")
    #   2) el headline de benchmarks ("y cómo vas vs el mercado")
    # Mini-eyebrows mono para que se lea qué es cada bloque.
    eb1 = "// TODO, EN UNA SOLA CIFRA"
    draw_spaced_text(draw, eb1, (W - spaced_width(draw, eb1, F_MONO_REG(18), 2)) / 2,
                     602, F_MONO_REG(18), INK_3, spacing=2)
    paste_capture(img, os.path.join(CAPS_DIR, "cap_value.png"), 634, 500)

    eb2 = "// Y CÓMO VAS VS EL MERCADO"
    draw_spaced_text(draw, eb2, (W - spaced_width(draw, eb2, F_MONO_REG(18), 2)) / 2,
                     826, F_MONO_REG(18), INK_3, spacing=2)
    paste_capture(img, os.path.join(CAPS_DIR, "cap_bench.png"), 858, 900)

    draw_sub(draw,
             ["Todos tus activos en una sola cifra,",
              "y si le ganás al mercado y al dólar."],
             1010, color=INK_2, size=29, lh=42)

    draw_footer(draw, current=2)
    _save(img, "rendi_que_es_pasos_3.png", "slide 3 (paso 2)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 4 — Paso 3: Sabés si ganás y cómo decidís
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_4():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ PASO 3 · 4 DE 5")

    draw_step_badge(draw, 3, 330)

    center_text(draw, "Entendés", 450, F_SANS_BOLD(58), INK_0)
    center_text(draw, "cómo operás.", 520, F_SANS_BOLD(58), VIOLET)

    # Captura REAL del "insight del día" de Rendi (demo mode): la tarjeta ya
    # trae su propio borde y badge de severidad — la pegamos tal cual, sin
    # redibujar nada. Acá un patrón saludable (win rate + payoff), no un mockup
    # genérico ni el mismo sesgo que ya usamos en las historias destacadas.
    paste_capture(img, os.path.join(CAPS_DIR, "cap_winrate.png"), 612, 840)

    draw_sub(draw,
             ["Rendi analiza cómo operás:",
              "qué te funciona y qué te cuesta."],
             1110, color=INK_2, size=29, lh=42)

    draw_footer(draw, current=3)
    _save(img, "rendi_que_es_pasos_4.png", "slide 4 (paso 3)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 5 — CTA
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_5():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ ESO ES RENDI · 5 DE 5")

    hero_font = F_SANS_BOLD(70)
    center_text(draw, "Tres pasos.", 330, hero_font, INK_0)
    center_text(draw, "Tus inversiones, claras.", 330 + 88, hero_font, VIOLET)

    # Recap de los 3 pasos como checks
    list_y = 600
    bullets = [
        "Conectás tus brokers",
        "Lo ves en dólares o pesos, vs el mercado",
        "Entendés cómo operás",
    ]
    bf = F_SANS_REG(30)
    # Centramos el bloque de bullets respecto al más ancho
    max_w = max(draw.textlength(b, font=bf) for b in bullets)
    block_x = W / 2 - (max_w + 44) / 2
    for b in bullets:
        ix, iy, s = block_x, list_y + 9, 20
        draw.line([(ix + s * 0.1, iy + s * 0.5), (ix + s * 0.42, iy + s * 0.82)], fill=VIOLET, width=3)
        draw.line([(ix + s * 0.42, iy + s * 0.82), (ix + s * 0.92, iy + s * 0.16)], fill=VIOLET, width=3)
        draw.text((block_x + 44, list_y), b, font=bf, fill=INK_0)
        list_y += 64

    # CTA pill — multi-broker/comportamiento son pagos, NO "gratis"
    cta_y = list_y + 60
    cta_text = "Probalo en rendi.finance"
    cta_font = F_SANS_BOLD(32)
    cta_w = draw.textlength(cta_text, font=cta_font)
    pad_x, pad_y = 36, 20
    btn_w = cta_w + pad_x * 2
    btn_h = cta_font.size + pad_y * 2
    btn_x = (W - btn_w) / 2
    draw.rounded_rectangle([btn_x, cta_y, btn_x + btn_w, cta_y + btn_h],
                           radius=btn_h // 2, fill=VIOLET)
    draw.text((btn_x + pad_x, cta_y + pad_y - 4), cta_text, font=cta_font, fill=(15, 12, 30))

    draw_footer(draw, current=4)
    _save(img, "rendi_que_es_pasos_5.png", "slide 5 (CTA)")


# ─── Save helper ─────────────────────────────────────────────────────────────
def _save(img, name, label):
    out = os.path.join(OUT_DIR, name)
    img.save(out, "PNG", optimize=True)
    print(f"✓ {label}: {name} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    generate_slide_1()
    generate_slide_2()
    generate_slide_3()
    generate_slide_4()
    generate_slide_5()
    print("\nDone.")
