"""
Post 6 — Coach IA (feature). Formato feed 4:5 (1080×1350).
Distinto de la story que_es_3: acá el ángulo es "analista que conoce tu cartera"
+ las 12 herramientas conectadas + ejemplos de preguntas.

Slides:
  - rendi_post_coach_1.png — HOOK: "Un analista que conoce tu cartera." (chat mock)
  - rendi_post_coach_2.png — "Responde con tus números." (12 herramientas)
  - rendi_post_coach_3.png — CTA: preguntas de ejemplo + Pro

Voz del manual: dato primero, voseo profesional, sentence case, cero emoji.
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
W, H = 1080, 1350

# ─── Colors ────────────────────────────────────────────────────────────────
BG = (10, 11, 14)
BG_GLOW = (16, 14, 26)
CARD_BG = (15, 17, 23)
CARD_BG_PLUS = (22, 18, 38)
INK_0 = (244, 244, 248)
INK_1 = (200, 200, 210)
INK_2 = (130, 132, 142)
INK_3 = (90, 96, 110)
INK_4 = (50, 54, 64)
VIOLET = (139, 125, 255)
RENDI_POS = (54, 211, 153)
RENDI_NEG = (231, 92, 92)


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


def draw_footer(draw, current, total=3):
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


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 1 — HOOK (chat mock)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_1():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ COACH IA")

    hero_top = 280
    f = F_SANS_BOLD(72)
    for i, (line, color) in enumerate([("Un analista que", INK_0), ("conoce tu cartera.", VIOLET)]):
        lw = draw.textlength(line, font=f)
        draw.text((W / 2 - lw / 2, hero_top + i * 92), line, font=f, fill=color)

    # ─── Chat mock ──────────────────────────────────────────────────────────
    bubble_top = hero_top + 270

    # User bubble (right)
    user_text = "¿Por qué bajó mi cartera en mayo?"
    ub_font = F_SANS_REG(28)
    ub_w = draw.textlength(user_text, font=ub_font)
    ub_pad = 28
    ub_x1 = W - 90
    ub_x0 = ub_x1 - (ub_w + ub_pad * 2)
    ub_y0 = bubble_top
    ub_y1 = ub_y0 + 64
    draw.rounded_rectangle([ub_x0, ub_y0, ub_x1, ub_y1], radius=18, fill=CARD_BG,
                           outline=(*INK_4, 180), width=1)
    draw.text((ub_x0 + ub_pad, ub_y0 + 16), user_text, font=ub_font, fill=INK_1)
    draw_spaced_text(draw, "TÚ", ub_x1 - 48, ub_y1 + 10, F_MONO_REG(15), INK_3, spacing=2)

    # Coach bubble (left, violet)
    cb_top = ub_y1 + 70
    coach_lines = ["NVDA explica el 71% de la caída.",
                   "Pesa 28% de tu portfolio —",
                   "es tu mayor concentración."]
    cb_font = F_SANS_REG(28)
    max_w = max(draw.textlength(l, font=cb_font) for l in coach_lines)
    cb_pad_x, cb_pad_y = 28, 22
    cb_line_h = 42
    cb_x0 = 90
    cb_x1 = cb_x0 + max_w + cb_pad_x * 2
    cb_y0 = cb_top
    cb_y1 = cb_y0 + len(coach_lines) * cb_line_h + cb_pad_y * 2 - 4
    draw.rounded_rectangle([cb_x0, cb_y0, cb_x1, cb_y1], radius=18, fill=CARD_BG_PLUS,
                           outline=(*VIOLET, 130), width=2)
    ty = cb_y0 + cb_pad_y
    for line in coach_lines:
        draw.text((cb_x0 + cb_pad_x, ty), line, font=cb_font, fill=INK_0)
        ty += cb_line_h
    ct_y = cb_y1 + 10
    draw.ellipse([cb_x0 + 4, ct_y + 6, cb_x0 + 14, ct_y + 16], fill=VIOLET)
    draw_spaced_text(draw, "COACH IA", cb_x0 + 24, ct_y + 2, F_MONO_REG(15), VIOLET, spacing=2)

    # ─── Sub ────────────────────────────────────────────────────────────────
    sub_y = cb_y1 + 90
    sub_font = F_SANS_REG(28)
    for line in ["No es un chatbot genérico.", "Conoce tu portfolio real."]:
        lw = draw.textlength(line, font=sub_font)
        draw.text((W / 2 - lw / 2, sub_y), line, font=sub_font, fill=INK_2)
        sub_y += 40

    draw_footer(draw, current=0)
    out = os.path.join(OUT_DIR, "rendi_post_coach_1.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ coach 1: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 2 — 12 herramientas (chips grid)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_2():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ 12 HERRAMIENTAS CONECTADAS")

    title_font = F_SANS_BOLD(56)
    t_top = 290
    for i, (line, color) in enumerate([("Responde con tus números.", INK_0),
                                       ("No con generalidades.", VIOLET)]):
        lw = draw.textlength(line, font=title_font)
        draw.text((W / 2 - lw / 2, t_top + i * 80), line, font=title_font, fill=color)

    # ─── Chips wrap ─────────────────────────────────────────────────────────
    chips = ["Fundamentales", "Earnings", "Ratings de analistas", "Bonos AR",
             "Noticias", "Value scorecard", "Precios live", "Memoria"]
    chip_font = F_MONO_REG(24)
    chip_h = 60
    pad_x = 26
    gap = 14
    max_row_w = 880
    # Layout en filas centradas
    rows, cur, cur_w = [], [], 0
    for c in chips:
        cw = draw.textlength(c, font=chip_font) + pad_x * 2
        if cur and cur_w + gap + cw > max_row_w:
            rows.append((cur, cur_w))
            cur, cur_w = [], 0
        if cur:
            cur_w += gap
        cur.append((c, cw))
        cur_w += cw
    if cur:
        rows.append((cur, cur_w))

    y = t_top + 230
    for row, row_w in rows:
        x = (W - row_w) / 2
        for c, cw in row:
            draw.rounded_rectangle([x, y, x + cw, y + chip_h], radius=12,
                                   fill=CARD_BG, outline=(*VIOLET, 90), width=1)
            tw = draw.textlength(c, font=chip_font)
            draw.text((x + cw / 2 - tw / 2, y + 16), c, font=chip_font, fill=INK_1)
            x += cw + gap
        y += chip_h + 16

    # ─── Sub ────────────────────────────────────────────────────────────────
    sub_y = y + 50
    sub_font = F_SANS_REG(28)
    for line in ["Conectado a tu portfolio real,", "y a tu memoria entre conversaciones."]:
        lw = draw.textlength(line, font=sub_font)
        draw.text((W / 2 - lw / 2, sub_y), line, font=sub_font, fill=INK_2)
        sub_y += 40

    draw_footer(draw, current=1)
    out = os.path.join(OUT_DIR, "rendi_post_coach_2.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ coach 2: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 3 — CTA (preguntas de ejemplo)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_3():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ DISPONIBLE EN PRO")

    hero_top = 300
    f1 = F_SANS_BOLD(96)
    lw1 = draw.textlength("Tu analista.", font=f1)
    draw.text((W / 2 - lw1 / 2, hero_top), "Tu analista.", font=f1, fill=INK_0)
    f2 = F_SANS_BOLD(72)
    lw2 = draw.textlength("Cuando lo necesités.", font=f2)
    draw.text((W / 2 - lw2 / 2, hero_top + 116), "Cuando lo necesités.", font=f2, fill=VIOLET)

    # ─── Preguntas de ejemplo como bubbles ──────────────────────────────────
    qs = ["¿Estoy sobre-concentrado?",
          "¿Qué pasa si vendo NVDA?",
          "¿Le gano a la inflación este año?"]
    q_font = F_SANS_REG(30)
    y = hero_top + 300
    for q in qs:
        qw = draw.textlength(q, font=q_font)
        pad = 28
        bw = qw + pad * 2
        bx = (W - bw) / 2
        draw.rounded_rectangle([bx, y, bx + bw, y + 70], radius=16, fill=CARD_BG,
                               outline=(*INK_4, 200), width=1)
        draw.text((bx + pad, y + 18), q, font=q_font, fill=INK_1)
        y += 86

    # ─── CTA pill ───────────────────────────────────────────────────────────
    cta_y = y + 50
    cta_text = "Probalo en rendi.finance"
    cta_font = F_SANS_BOLD(30)
    cta_w = draw.textlength(cta_text, font=cta_font)
    pad_x, pad_y = 36, 20
    btn_w = cta_w + pad_x * 2
    btn_h = cta_font.size + pad_y * 2
    btn_x = (W - btn_w) / 2
    draw.rounded_rectangle([btn_x, cta_y, btn_x + btn_w, cta_y + btn_h],
                           radius=btn_h // 2, fill=VIOLET)
    draw.text((btn_x + pad_x, cta_y + pad_y - 4), cta_text, font=cta_font, fill=(15, 12, 30))

    draw_footer(draw, current=2)
    out = os.path.join(OUT_DIR, "rendi_post_coach_3.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ coach 3: {out} ({os.path.getsize(out)/1024:.1f}KB)")


if __name__ == "__main__":
    generate_slide_1()
    generate_slide_2()
    generate_slide_3()
    print("\nDone.")
