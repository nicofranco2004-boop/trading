"""
Post — Coach IA vs IA genérica. Formato feed 4:5 (1080×1350).
Ángulo: posicionar a Coach IA contra el reflexo "yo uso ChatGPT" sin nombrar
la marca (decisión de producto: "IA genérica" — clean, sin riesgo de marca).

Slides:
  - rendi_coach_vs_ia_1.png — HOOK: pregunta + "Misma pregunta, dos respuestas"
  - rendi_coach_vs_ia_2.png — REVEAL: las 2 respuestas comparadas
  - rendi_coach_vs_ia_3.png — CTA: por qué es distinto + Plus

Voz: dato primero, voseo, sentence case, cero emoji. Mismo manual que el
resto de los carruseles de Rendi.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

# ─── Paths (mismo pattern que generate_post_coach_feed.py) ────────────────────
FONTS_DIR = (
    "/Users/nicolaspussetto/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "bcfbadf3-5949-46c4-95ea-f77e7e18d7ad/"
    "6a7d8d68-f39a-4be8-86c7-653fd22de85c/skills/canvas-design/canvas-fonts/"
)
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"
W, H = 1080, 1350

# ─── Colors (alineado con brand kit) ───────────────────────────────────────────
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


# ─── Fonts ────────────────────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)


F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)
F_MONO_REG = lambda s: font("GeistMono-Regular.ttf", s)


# ─── Helpers de texto (idem feed) ─────────────────────────────────────────────
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
    """Word-wrap simple. Devuelve lista de líneas que entran en max_width."""
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip()
        if draw.textlength(candidate, font=font_obj) <= max_width:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ─── Base canvas con glow violet centrado (idem feed) ─────────────────────────
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
# SLIDE 1 — HOOK (pregunta única + tease)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_1():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ COACH IA vs IA GENERICA")

    hero_top = 290
    f = F_SANS_BOLD(72)
    for i, (line, color) in enumerate([("Misma pregunta,", INK_0), ("dos respuestas.", VIOLET)]):
        lw = draw.textlength(line, font=f)
        draw.text((W / 2 - lw / 2, hero_top + i * 92), line, font=f, fill=color)

    # ─── Bubble centrada con la pregunta ─────────────────────────────────────
    q_text = "¿Por qué bajó mi cartera este mes?"
    q_font = F_SANS_REG(34)
    q_pad_x, q_pad_y = 40, 32
    q_w = draw.textlength(q_text, font=q_font)
    bw = q_w + q_pad_x * 2
    bh = q_font.size + q_pad_y * 2
    bx = (W - bw) / 2
    by = hero_top + 280

    # Glow alrededor para destacar
    glow_box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_box)
    gd.rounded_rectangle([bx - 8, by - 8, bx + bw + 8, by + bh + 8], radius=24,
                          fill=(*VIOLET, 18))
    glow_box = glow_box.filter(ImageFilter.GaussianBlur(18))
    img.paste(glow_box, (0, 0), glow_box)
    draw = ImageDraw.Draw(img, "RGBA")  # re-bind tras paste

    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=20, fill=CARD_BG,
                           outline=(*VIOLET, 160), width=2)
    draw.text((bx + q_pad_x, by + q_pad_y - 4), q_text, font=q_font, fill=INK_0)

    # ─── Tease ─────────────────────────────────────────────────────────────────
    tease_y = by + bh + 100
    tease_font = F_SANS_REG(28)
    for line in ["Le preguntamos a una IA genérica", "y al Coach IA de Rendi.", "Desliza →"]:
        lw = draw.textlength(line, font=tease_font)
        color = VIOLET if line == "Desliza →" else INK_2
        draw.text((W / 2 - lw / 2, tease_y), line, font=tease_font, fill=color)
        tease_y += 42

    draw_footer(draw, current=0)
    out = os.path.join(OUT_DIR, "rendi_coach_vs_ia_1.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ vs_ia 1: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 2 — REVEAL (las 2 respuestas, una arriba de la otra)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_2():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ RESPUESTAS")

    # Textos
    answer_generic = (
        "Las caídas suelen deberse a varios factores: tipos de interés, "
        "sentimiento del mercado, eventos macro. Revisá tu cartera y "
        "considerá diversificar."
    )
    answer_coach = (
        "NVDA explica el 71% de la caída. Pesa 28% de tu cartera — tu "
        "mayor concentración. Con perfil 'moderado' estás overweight en "
        "tech vs lo declarado."
    )

    # ─── Bubble 1: IA genérica (top, gris) ────────────────────────────────────
    bubble_x = 70
    bubble_w = W - 140
    bubble_pad_x = 36
    bubble_pad_y = 28
    txt_font = F_SANS_REG(28)
    inner_w = bubble_w - bubble_pad_x * 2
    lines1 = wrap_text(draw, answer_generic, txt_font, inner_w)
    line_h = 42

    b1_top = 280
    b1_height = len(lines1) * line_h + bubble_pad_y * 2 + 30  # +30 para el label
    draw.rounded_rectangle([bubble_x, b1_top, bubble_x + bubble_w, b1_top + b1_height],
                           radius=22, fill=CARD_BG, outline=(*INK_4, 200), width=1)
    ty = b1_top + bubble_pad_y
    for line in lines1:
        draw.text((bubble_x + bubble_pad_x, ty), line, font=txt_font, fill=INK_2)
        ty += line_h

    # Label IA genérica
    label_y = b1_top + b1_height - 38
    label_font = F_MONO_REG(18)
    label_text = "IA GENERICA — SIN TU CARTERA"
    draw.ellipse([bubble_x + bubble_pad_x, label_y + 6, bubble_x + bubble_pad_x + 10, label_y + 16],
                 fill=INK_3)
    draw_spaced_text(draw, label_text, bubble_x + bubble_pad_x + 24, label_y + 2,
                     label_font, INK_3, spacing=2)

    # ─── Separador visual "vs" ────────────────────────────────────────────────
    vs_y = b1_top + b1_height + 30
    vs_font = F_SANS_BOLD(38)
    vs_w = draw.textlength("vs", font=vs_font)
    # Línea izquierda
    line_y = vs_y + 22
    draw.line([(W / 2 - 60, line_y), (W / 2 - vs_w / 2 - 14, line_y)], fill=INK_4, width=1)
    draw.line([(W / 2 + vs_w / 2 + 14, line_y), (W / 2 + 60, line_y)], fill=INK_4, width=1)
    draw.text((W / 2 - vs_w / 2, vs_y), "vs", font=vs_font, fill=INK_3)

    # ─── Bubble 2: Coach IA (bottom, violet) ──────────────────────────────────
    lines2 = wrap_text(draw, answer_coach, txt_font, inner_w)
    b2_top = vs_y + 100
    b2_height = len(lines2) * line_h + bubble_pad_y * 2 + 30

    # Glow violeta sutil
    glow_box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_box)
    gd.rounded_rectangle([bubble_x - 6, b2_top - 6, bubble_x + bubble_w + 6, b2_top + b2_height + 6],
                          radius=26, fill=(*VIOLET, 20))
    glow_box = glow_box.filter(ImageFilter.GaussianBlur(16))
    img.paste(glow_box, (0, 0), glow_box)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.rounded_rectangle([bubble_x, b2_top, bubble_x + bubble_w, b2_top + b2_height],
                           radius=22, fill=CARD_BG_PLUS, outline=(*VIOLET, 150), width=2)
    ty = b2_top + bubble_pad_y
    for line in lines2:
        draw.text((bubble_x + bubble_pad_x, ty), line, font=txt_font, fill=INK_0)
        ty += line_h

    label2_y = b2_top + b2_height - 38
    label2_text = "COACH IA — SABE TU CARTERA"
    draw.ellipse([bubble_x + bubble_pad_x, label2_y + 6, bubble_x + bubble_pad_x + 10, label2_y + 16],
                 fill=VIOLET)
    draw_spaced_text(draw, label2_text, bubble_x + bubble_pad_x + 24, label2_y + 2,
                     label_font, VIOLET, spacing=2)

    draw_footer(draw, current=1)
    out = os.path.join(OUT_DIR, "rendi_coach_vs_ia_2.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ vs_ia 2: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 3 — CTA (por qué es distinto + Plus)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_3():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ POR QUE ES DISTINTO")

    hero_top = 290
    f1 = F_SANS_BOLD(72)
    lw1 = draw.textlength("La diferencia está", font=f1)
    draw.text((W / 2 - lw1 / 2, hero_top), "La diferencia está", font=f1, fill=INK_0)
    lw2 = draw.textlength("en tus números.", font=f1)
    draw.text((W / 2 - lw2 / 2, hero_top + 92), "en tus números.", font=f1, fill=VIOLET)

    # ─── 4 features con check ─────────────────────────────────────────────────
    features = [
        "Conoce tus tickers, fechas de compra y costo base",
        "Identifica concentración real, no genérica",
        "Compara contra tu perfil declarado",
        "Recuerda lo que le aclaraste antes",
    ]
    feat_font = F_SANS_REG(26)
    y = hero_top + 260
    for f_text in features:
        # Check dot
        draw.ellipse([100, y + 12, 116, y + 28], fill=VIOLET)
        draw.text((140, y + 4), f_text, font=feat_font, fill=INK_1)
        y += 60

    # ─── CTA pill ──────────────────────────────────────────────────────────────
    # Free tier ya incluye Coach IA (12 preguntas guiadas + 3 chats/sem).
    # CTA "Probalo gratis" = cero fricción, max conversion. Precio aparece
    # solo cuando el user se entusiasme con el producto.
    cta_y = y + 80
    cta_text = "Probalo gratis"
    cta_font = F_SANS_BOLD(34)
    cta_w = draw.textlength(cta_text, font=cta_font)
    pad_x, pad_y = 44, 24
    btn_w = cta_w + pad_x * 2
    btn_h = cta_font.size + pad_y * 2
    btn_x = (W - btn_w) / 2
    draw.rounded_rectangle([btn_x, cta_y, btn_x + btn_w, cta_y + btn_h],
                           radius=btn_h // 2, fill=VIOLET)
    draw.text((btn_x + pad_x, cta_y + pad_y - 4), cta_text, font=cta_font, fill=(15, 12, 30))

    # Sub debajo de la pill
    sub_y = cta_y + btn_h + 24
    sub_text = "Coach IA disponible en el plan Free"
    sub_font = F_SANS_REG(24)
    sw = draw.textlength(sub_text, font=sub_font)
    draw.text((W / 2 - sw / 2, sub_y), sub_text, font=sub_font, fill=INK_2)

    draw_footer(draw, current=2)
    out = os.path.join(OUT_DIR, "rendi_coach_vs_ia_3.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ vs_ia 3: {out} ({os.path.getsize(out)/1024:.1f}KB)")


if __name__ == "__main__":
    generate_slide_1()
    generate_slide_2()
    generate_slide_3()
    print("\nDone.")
