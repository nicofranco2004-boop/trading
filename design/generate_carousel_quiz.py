"""
Genera el carousel "Test rápido: 3 preguntas que tu broker no te contesta".
4 slides en 1080×1350 (4:5 vertical, óptimo para feed IG).

Output:
  - rendi_carousel_quiz_1.png — "¿Estás demasiado concentrado en tech?"   → sector_concentration
  - rendi_carousel_quiz_2.png — "¿Cuánto te llevaron las comisiones?"      → diagnostic comisiones
  - rendi_carousel_quiz_3.png — "¿Vendiste tu mejor activo demasiado pronto?" → counterfactual
  - rendi_carousel_quiz_4.png — CTA "Rendi te lo dice"

Cada pregunta mapea a un análisis REAL del producto (ver backend/behavioral.py
y frontend/src/utils/diagnostics.js). Los visuales recrean readouts auténticos
de Rendi, no charts genéricos.

Voz del manual: dato primero, voseo profesional, sentence case, cero emoji.
Verde/rojo solo en datos con polaridad. Violeta solo en acción/énfasis.
NOTA: Comportamiento es feature Plus → el CTA es "Probalo en" (NO "gratis").
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

def draw_question(draw, lines, q_top, q_font, accent_idx, line_h):
    """Hero pregunta centrada; la línea accent_idx en violet."""
    ty = q_top
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=q_font)
        color = VIOLET if i == accent_idx else INK_0
        draw.text((W / 2 - lw / 2, ty), line, font=q_font, fill=color)
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
# SLIDE 1 — Concentración (sector_concentration)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_1():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ TEST RÁPIDO · 1 DE 4")

    draw_question(draw, ["¿Estás demasiado", "concentrado", "en tech?"], 280, F_SANS_BOLD(80), 1, 96)

    # ─── Card: readout de sector_concentration ──────────────────────────────
    card_w = 820
    card_x = (W - card_w) / 2
    card_y = 600
    card_h = 320
    pad = 36
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                           radius=16, fill=CARD_BG, outline=(*INK_4, 200), width=1)

    draw_spaced_text(draw, "// CONCENTRACIÓN SECTORIAL", card_x + pad, card_y + 28,
                     F_MONO_REG(19), INK_3, spacing=2)

    # Top sector readout
    draw.text((card_x + pad, card_y + 60), "Tecnología", font=F_SANS_BOLD(40), fill=INK_0)
    pct_txt = "60%"
    pf = F_SANS_BOLD(40)
    draw.text((card_x + card_w - pad - draw.textlength(pct_txt, font=pf), card_y + 60),
              pct_txt, font=pf, fill=SKY)

    # Barra stacked (colores de dato, sin polaridad)
    bar_y = card_y + 130
    bar_h = 30
    bar_x0 = card_x + pad
    bar_w = card_w - pad * 2
    segments = [("Tech", 0.60, SKY), ("Acciones AR", 0.25, AQUA), ("Bonos / cash", 0.15, INK_3)]
    cx = bar_x0
    for i, (lbl, pct, color) in enumerate(segments):
        seg_w = bar_w * pct
        r0 = cx
        r1 = cx + seg_w - (4 if i < len(segments) - 1 else 0)
        draw.rounded_rectangle([r0, bar_y, r1, bar_y + bar_h], radius=6, fill=color)
        cx += seg_w

    # Leyenda
    leg_y = bar_y + bar_h + 28
    lf = F_MONO_REG(20)
    lx = bar_x0
    for lbl, pct, color in segments:
        draw.ellipse([lx, leg_y + 4, lx + 12, leg_y + 16], fill=color)
        txt = f"{lbl} {int(pct*100)}%"
        draw.text((lx + 22, leg_y), txt, font=lf, fill=INK_2)
        lx += 22 + draw.textlength(txt, font=lf) + 36

    # Divider + warning line
    dv_y = leg_y + 56
    draw.line([(bar_x0, dv_y), (bar_x0 + bar_w, dv_y)], fill=(*INK_4, 150), width=1)
    warn_f = F_SANS_REG(23)
    draw.text((bar_x0, dv_y + 22),
              "Si NVDA cae 20%, tu cartera lo siente.",
              font=warn_f, fill=INK_1)

    draw_sub(draw, ["Tu broker te muestra el saldo.",
                    "Rendi te muestra la concentración por sector."],
             card_y + card_h + 46)

    draw_footer(draw, current=0)
    out = os.path.join(OUT_DIR, "rendi_carousel_quiz_1.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 1: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 2 — Comisiones (diagnostic commissions_summary)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_2():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ TEST RÁPIDO · 2 DE 4")

    draw_question(draw, ["¿Cuánto te", "llevaron las", "comisiones?"], 280, F_SANS_BOLD(80), 2, 96)

    # ─── Card: número grande (diagnóstico real) ─────────────────────────────
    card_w = 820
    card_x = (W - card_w) / 2
    card_y = 600
    card_h = 320
    pad = 36
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                           radius=16, fill=CARD_BG, outline=(*RENDI_NEG, 110), width=1)

    draw_spaced_text(draw, "// COMISIONES ACUMULADAS · 2026", card_x + pad, card_y + 28,
                     F_MONO_REG(19), INK_3, spacing=2)

    draw.text((card_x + pad, card_y + 64), "US$ 847", font=F_SANS_BOLD(96), fill=RENDI_NEG)
    draw_spaced_text(draw, "2.1% DE TU PORTFOLIO · 34 OPERACIONES",
                     card_x + pad, card_y + 184, F_MONO_REG(19), INK_3, spacing=2)

    # Divider + comparación brokers
    dv_y = card_y + 230
    draw.line([(card_x + pad, dv_y), (card_x + card_w - pad, dv_y)], fill=(*INK_4, 150), width=1)
    bf = F_MONO_REG(21)
    bx = card_x + pad
    by = dv_y + 22
    for lbl, val, col in [("COCOS", "0.6%", INK_1), ("IOL", "0.5%", INK_1), ("SCHWAB", "0%", RENDI_POS)]:
        draw_spaced_text(draw, lbl, bx, by, F_MONO_REG(18), INK_3, spacing=1)
        draw.text((bx, by + 26), val, font=F_MONO_BOLD(26), fill=col)
        bx += 250

    draw_sub(draw, ["Cada operación suma. ¿Sabés tu total?",
                    "Rendi lo calcula sobre tu historial real."],
             card_y + card_h + 46)

    draw_footer(draw, current=1)
    out = os.path.join(OUT_DIR, "rendi_carousel_quiz_2.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 2: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 3 — Vendiste pronto (counterfactual · "Tu yo de hace meses")
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_3():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ TEST RÁPIDO · 3 DE 4")

    draw_question(draw, ["¿Vendiste tu mejor", "activo demasiado", "pronto?"], 280, F_SANS_BOLD(74), 2, 90)

    # ─── Card: readout de counterfactual ────────────────────────────────────
    card_w = 820
    card_x = (W - card_w) / 2
    card_y = 596
    card_h = 330
    pad = 36
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                           radius=16, fill=CARD_BG, outline=(*VIOLET, 110), width=1)

    draw_spaced_text(draw, "// TU YO DE HACE MESES · NVDA", card_x + pad, card_y + 28,
                     F_MONO_REG(19), INK_3, spacing=2)

    # Big stat: lo que dejaste en la mesa
    draw.text((card_x + pad, card_y + 60), "+US$ 1.240", font=F_SANS_BOLD(82), fill=VIOLET)
    draw_spaced_text(draw, "LO QUE DEJASTE EN LA MESA",
                     card_x + pad, card_y + 162, F_MONO_REG(19), INK_3, spacing=2)

    # Divider + evidence rows (exit → current, como el detector real)
    dv_y = card_y + 208
    draw.line([(card_x + pad, dv_y), (card_x + card_w - pad, dv_y)], fill=(*INK_4, 150), width=1)

    def ev_row(y, label, value, vcolor):
        draw.text((card_x + pad, y), label, font=F_SANS_REG(23), fill=INK_2)
        vf = F_MONO_REG(23)
        vw = draw.textlength(value, font=vf)
        draw.text((card_x + card_w - pad - vw, y), value, font=vf, fill=vcolor)

    ev_row(dv_y + 24, "Vendiste a", "US$ 118", INK_1)
    ev_row(dv_y + 62, "Cotiza hoy", "US$ 174  (+47%)", RENDI_POS)

    draw_sub(draw, ["Rendi compara tu P&L real",
                    "con el de no haber vendido. Trade por trade."],
             card_y + card_h + 42)

    draw_footer(draw, current=2)
    out = os.path.join(OUT_DIR, "rendi_carousel_quiz_3.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 3: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 4 — CTA
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_4():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ RESPUESTA · 4 DE 4")

    hero_top = 360
    hero_font = F_SANS_BOLD(108)
    lw1 = draw.textlength("Rendi", font=hero_font)
    draw.text((W / 2 - lw1 / 2, hero_top), "Rendi", font=hero_font, fill=INK_0)
    lw2 = draw.textlength("te lo dice.", font=hero_font)
    draw.text((W / 2 - lw2 / 2, hero_top + 116), "te lo dice.", font=hero_font, fill=VIOLET)

    # Bullets — mapean a las 3 preguntas / detectores
    list_y = hero_top + 290
    bullets = [
        "Concentración por sector de tu cartera",
        "Costo real de tus comisiones",
        "Cuánto dejaste en la mesa al vender",
    ]
    bullet_font = F_SANS_REG(28)
    for b in bullets:
        ix = W / 2 - 300
        iy = list_y + 8
        s = 18
        draw.line([(ix + s * 0.1, iy + s * 0.5), (ix + s * 0.42, iy + s * 0.82)], fill=VIOLET, width=3)
        draw.line([(ix + s * 0.42, iy + s * 0.82), (ix + s * 0.92, iy + s * 0.18)], fill=VIOLET, width=3)
        draw.text((ix + 36, list_y), b, font=bullet_font, fill=INK_0)
        list_y += 50

    # CTA pill — Comportamiento es Plus, NO decir "gratis"
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
    out = os.path.join(OUT_DIR, "rendi_carousel_quiz_4.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ slide 4: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    generate_slide_1()
    generate_slide_2()
    generate_slide_3()
    generate_slide_4()
    print("\nDone.")
