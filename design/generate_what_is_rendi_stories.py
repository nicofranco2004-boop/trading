"""
Genera las 3 historias destacadas "Qué es Rendi" para Instagram.
Cada una con un visual hero distintivo + hero text + sub-texto explicativo.

Output:
  - rendi_que_es_1_multibroker.png — "5 brokers. 1 vista."
  - rendi_que_es_2_usd_real.png    — "USD real. No la ilusión en pesos."
  - rendi_que_es_3_coach_ia.png    — "Preguntale. Sabe tu cartera."

Todas en 1080x1920 PNG, dark mode, aesthetic "Nocturnal Precision".
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
W, H = 1080, 1920

# ─── Colors ────────────────────────────────────────────────────────────────
BG = (10, 11, 14)
BG_GLOW = (16, 14, 26)
CARD_BG = (15, 17, 23)
INK_0 = (244, 244, 248)
INK_1 = (200, 200, 210)
INK_2 = (130, 132, 142)
INK_3 = (90, 96, 110)
INK_4 = (50, 54, 64)
INK_5 = (40, 44, 54)
VIOLET = (139, 125, 255)
VIOLET_DIM = (110, 95, 220)
RENDI_POS = (54, 211, 153)   # verde positivo para mock P&L

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


def build_base_canvas(plan_glow=False):
    """Canvas base con gradient + soft glow optional."""
    img = Image.new("RGB", (W, H), BG)
    dg = ImageDraw.Draw(img)
    for y in range(H):
        if y < 700:
            t = 1 - (y / 700)
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.5)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.5)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.5)
            dg.line([(0, y), (W, y)], fill=(r, g, b))
        elif y > H - 500:
            t = (y - (H - 500)) / 500
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.3)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.3)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.3)
            dg.line([(0, y), (W, y)], fill=(r, g, b))

    if plan_glow:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for r in range(420, 0, -10):
            alpha = int((1 - r / 420) * 18)
            gd.ellipse([W // 2 - r, 900 - r, W // 2 + r, 900 + r], fill=(*VIOLET, alpha))
        glow = glow.filter(ImageFilter.GaussianBlur(60))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    return img


def draw_header(draw, eyebrow_text):
    """Header común: logo + underline + eyebrow."""
    HEADER_TOP = 130
    logo = "rendi"
    logo_font = F_SANS_BOLD(56)
    logo_w = draw.textlength(logo, font=logo_font)
    draw.text((W / 2 - logo_w / 2, HEADER_TOP), logo, font=logo_font, fill=INK_0)
    ul_w = 36
    ul_y = HEADER_TOP + 84
    draw.line([(W / 2 - ul_w / 2, ul_y), (W / 2 + ul_w / 2, ul_y)], fill=VIOLET, width=2)

    eyebrow_top = HEADER_TOP + 130
    eyebrow_font = F_MONO_REG(24)
    ey_w = spaced_width(draw, eyebrow_text, eyebrow_font, spacing=4)
    draw_spaced_text(draw, eyebrow_text, W / 2 - ey_w / 2, eyebrow_top, eyebrow_font, VIOLET, spacing=4)


def draw_footer(draw):
    """Footer común: hairline + brand + tagline."""
    footer_y = H - 200
    draw.line([(W / 2 - 40, footer_y), (W / 2 + 40, footer_y)], fill=INK_4, width=1)
    brand_font = F_MONO_REG(28)
    brand_w = draw.textlength("rendi.finance", font=brand_font)
    draw.text((W / 2 - brand_w / 2, footer_y + 30), "rendi.finance", font=brand_font, fill=INK_1)
    tag_font = F_SANS_REG(24)
    tag_text = "Tu portfolio multi-broker, con Coach IA."
    tag_w = draw.textlength(tag_text, font=tag_font)
    draw.text((W / 2 - tag_w / 2, footer_y + 84), tag_text, font=tag_font, fill=INK_3)


# ─────────────────────────────────────────────────────────────────────────────
# HISTORIA 1: "Conectá tus brokers. Tu rendimiento, en dólares."
# Combina multi-broker + USD real en una sola historia. No usa números
# específicos (ni "5 brokers") para no limitar — los brokers aparecen como
# ejemplos visuales sin lista cerrada.
# ─────────────────────────────────────────────────────────────────────────────
def generate_brokers_usd():
    img = build_base_canvas(plan_glow=True)
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ QUÉ ES RENDI · 1 DE 3")

    # ─── HERO TEXT (2 líneas, segunda en violet) ───────────────────────────
    hero_top = 400
    hero_font = F_SANS_BOLD(82)
    line1 = "Conectá tus brokers."
    lw1 = draw.textlength(line1, font=hero_font)
    draw.text((W / 2 - lw1 / 2, hero_top), line1, font=hero_font, fill=INK_0)
    # Línea 2 destacada en violet — esto es lo nuevo del valor prop
    line2_top = hero_top + 100
    line2 = "Tu rendimiento,"
    lw2 = draw.textlength(line2, font=hero_font)
    draw.text((W / 2 - lw2 / 2, line2_top), line2, font=hero_font, fill=INK_2)
    line3 = "en dólares."
    lw3 = draw.textlength(line3, font=hero_font)
    draw.text((W / 2 - lw3 / 2, line2_top + 96), line3, font=hero_font, fill=VIOLET)

    # ─── BROKERS CHIPS — varios, con "+ más" para no limitar ────────────────
    # Diseño wrap con 2 filas — sugiere variedad sin decir un número exacto.
    brokers_y = line2_top + 220
    # Más brokers + "+ más" al final para sugerir que la lista es amplia
    brokers_row1 = ["Cocos", "IOL", "Schwab", "Binance"]
    brokers_row2 = ["Balanz", "IBKR", "+ más"]
    chip_font = F_MONO_REG(22)
    chip_h = 56
    chip_pad_x = 22
    chip_gap = 12

    def draw_chip_row(brokers_list, y, special_last=False):
        widths = [draw.textlength(b, font=chip_font) + chip_pad_x * 2 for b in brokers_list]
        total_w = sum(widths) + (len(brokers_list) - 1) * chip_gap
        cursor = (W - total_w) / 2
        for i, b in enumerate(brokers_list):
            cw = widths[i]
            is_last_special = special_last and (i == len(brokers_list) - 1)
            # "+ más" chip diferente — dashed border violet
            if is_last_special:
                # Dibujar un borde "dashed" simulado con segmentos
                # Por simplicidad usamos un borde violet sólido más delgado.
                draw.rounded_rectangle(
                    [cursor, y, cursor + cw, y + chip_h],
                    radius=10,
                    fill=(*VIOLET, 12),
                    outline=(*VIOLET, 160),
                    width=1,
                )
                text_color = VIOLET
            else:
                draw.rounded_rectangle(
                    [cursor, y, cursor + cw, y + chip_h],
                    radius=10,
                    fill=CARD_BG,
                    outline=(*INK_4, 220),
                    width=1,
                )
                text_color = INK_1
            tw = draw.textlength(b, font=chip_font)
            draw.text(
                (cursor + cw / 2 - tw / 2, y + 14),
                b,
                font=chip_font,
                fill=text_color,
            )
            cursor += cw + chip_gap

    draw_chip_row(brokers_row1, brokers_y, special_last=False)
    draw_chip_row(brokers_row2, brokers_y + chip_h + 14, special_last=True)

    # ─── ARROW vertical violet ─────────────────────────────────────────────
    arrow_top = brokers_y + (chip_h + 14) * 2 + 30
    arrow_bottom = arrow_top + 56
    cx = W / 2
    draw.line([(cx, arrow_top), (cx, arrow_bottom - 8)], fill=VIOLET, width=3)
    draw.polygon(
        [(cx - 12, arrow_bottom - 10), (cx + 12, arrow_bottom - 10), (cx, arrow_bottom + 6)],
        fill=VIOLET,
    )

    # ─── DASHBOARD MOCK (USD-focused) ──────────────────────────────────────
    mock_y = arrow_bottom + 28
    mock_w = 820
    mock_h = 220
    mock_x = (W - mock_w) / 2
    draw.rounded_rectangle(
        [mock_x, mock_y, mock_x + mock_w, mock_y + mock_h],
        radius=20,
        fill=CARD_BG,
        outline=(*VIOLET, 110),
        width=2,
    )

    # Header del mock
    mh_font = F_MONO_REG(18)
    draw_spaced_text(draw, "// TU PORTFOLIO · USD", mock_x + 40, mock_y + 26, mh_font, INK_3, spacing=2)

    # Balance grande
    bal_font = F_SANS_BOLD(70)
    draw.text((mock_x + 40, mock_y + 58), "USD 42.180", font=bal_font, fill=INK_0)

    # P&L indicator
    pnl_font = F_MONO_BOLD(22)
    pnl_text = "+12.4%"
    draw.text((mock_x + 40, mock_y + 152), pnl_text, font=pnl_font, fill=RENDI_POS)
    pl_font = F_MONO_REG(18)
    pl_w = draw.textlength(pnl_text, font=pnl_font)
    draw.text((mock_x + 40 + pl_w + 16, mock_y + 156), "USD real · TC blue", font=pl_font, fill=INK_3)

    # Sparkline derecha
    sp_x0 = mock_x + 460
    sp_x1 = mock_x + mock_w - 40
    sp_y_base = mock_y + mock_h - 50
    sp_height = 90
    import math
    n_points = 30
    points = []
    for i in range(n_points):
        x = sp_x0 + (sp_x1 - sp_x0) * (i / (n_points - 1))
        t = i / (n_points - 1)
        progress = 0.4 + 0.5 * t + 0.06 * math.sin(t * 9) + 0.04 * math.sin(t * 22)
        y = sp_y_base - progress * sp_height
        points.append((x, y))
    draw.line(points, fill=VIOLET, width=3)
    area = [(sp_x0, sp_y_base)] + points + [(sp_x1, sp_y_base)]
    draw.polygon(area, fill=(*VIOLET, 32))

    draw_footer(draw)
    out = os.path.join(OUT_DIR, "rendi_que_es_1_brokers_usd.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ brokers_usd: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# HISTORIA 2: "El Google Analytics de tu portfolio."
# Insights + detectores de comportamiento. Mostramos un grid de mini-cards
# con métricas mock (drawdown, concentración, win rate, behavior) para
# ilustrar la idea de "medimos cómo decidís".
# ─────────────────────────────────────────────────────────────────────────────
def generate_insights_behavior():
    img = build_base_canvas(plan_glow=True)
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ QUÉ ES RENDI · 2 DE 3")

    # ─── HERO TEXT ──────────────────────────────────────────────────────────
    hero_top = 410
    hero_font_big = F_SANS_BOLD(96)
    hero_font_med = F_SANS_BOLD(82)

    # 3 líneas: "El Google Analytics" (regular) / "de tu" (gris) / "portfolio." (violet)
    # Wait — mejor: 2 líneas, primera gris/regular, segunda violet con la frase clave
    line1 = "El Google Analytics"
    lw1 = draw.textlength(line1, font=hero_font_med)
    draw.text((W / 2 - lw1 / 2, hero_top), line1, font=hero_font_med, fill=INK_0)

    line2 = "de tu portfolio."
    lw2 = draw.textlength(line2, font=hero_font_med)
    draw.text((W / 2 - lw2 / 2, hero_top + 100), line2, font=hero_font_med, fill=VIOLET)

    # ─── INSIGHTS GRID (2 × 2 mini cards) ──────────────────────────────────
    grid_top = hero_top + 250
    card_w = 410
    card_h = 200
    gap = 26
    left_x = (W - card_w * 2 - gap) / 2
    right_x = left_x + card_w + gap

    def draw_metric_card(x, y, eyebrow, value, sub, value_color=None, tone='neutral'):
        """Card de métrica simple. tone: 'neutral' | 'pos' | 'warn' | 'violet'"""
        border_color = (*INK_4, 200)
        if tone == 'violet':
            border_color = (*VIOLET, 110)
        draw.rounded_rectangle(
            [x, y, x + card_w, y + card_h],
            radius=18,
            fill=CARD_BG,
            outline=border_color,
            width=2 if tone == 'violet' else 1,
        )
        # Eyebrow mono
        eb_font = F_MONO_REG(18)
        draw_spaced_text(draw, eyebrow, x + 28, y + 28, eb_font, INK_3, spacing=2)
        # Value — auto-shrink si es texto largo (ej. "LOSS AVERSION") para
        # que no desborde la card. Métricas numéricas cortas (−14.2%, +8.4%)
        # quedan con 52pt; texto largo cae a 38pt.
        is_long_text = len(value) > 7 and not any(c.isdigit() or c in '+-' for c in value[:3])
        val_size = 38 if is_long_text else 52
        val_font = F_SANS_BOLD(val_size)
        vc = value_color or INK_0
        # Auto-uppercase para values de texto (más punchy, fintech-style)
        display_value = value.upper() if is_long_text else value
        # Y-offset adjust según size para mantener baseline consistente
        val_y_offset = 68 if is_long_text else 60
        draw.text((x + 28, y + val_y_offset), display_value, font=val_font, fill=vc)
        # Sub
        sub_font = F_MONO_REG(18)
        sub_lines = wrap_text(draw, sub, sub_font, card_w - 56)
        ty = y + 132
        for line in sub_lines:
            draw.text((x + 28, ty), line, font=sub_font, fill=INK_3)
            ty += 26

    # Top-left: VS S&P 500 — la comparación contra el mercado es la métrica
    # más viral en finanzas. "Le ganás al S&P" engancha en 0.5 segundos.
    draw_metric_card(
        left_x, grid_top,
        "VS S&P 500",
        "+8.4%",
        "le ganás al benchmark",
        value_color=RENDI_POS,
        tone='violet',
    )
    # Top-right: bias psicológico LOSS AVERSION — clásico y reconocible.
    # El value = nombre del bias en grande (auto-shrink lo achica para que
    # entre prolijo en la card).
    draw_metric_card(
        right_x, grid_top,
        "COMPORTAMIENTO",
        "loss aversion",
        "vendés ganadores, mantenés perdedores",
        value_color=(230, 180, 70),  # amber
        tone='neutral',
    )
    # Bottom-left: DRAWDOWN vs tolerancia declarada — sugiere acción.
    draw_metric_card(
        left_x, grid_top + card_h + gap,
        "DRAWDOWN MÁX",
        "−14.2%",
        "tolerás −20% declarado",
        value_color=(231, 92, 92),  # red soft
        tone='neutral',
    )
    # Bottom-right: bias FOMO BUY — universal, todos lo entienden al leer.
    draw_metric_card(
        right_x, grid_top + card_h + gap,
        "COMPORTAMIENTO",
        "fomo buy",
        "comprás cerca de máximos",
        value_color=(230, 180, 70),  # amber
        tone='neutral',
    )

    # ─── SUB-COPY ───────────────────────────────────────────────────────────
    sub_y = grid_top + (card_h + gap) * 2 + 50
    sub_font = F_SANS_REG(28)
    sub_lines = [
        "Le ganás al S&P? Caés en FOMO?",
        "Rendi te lo muestra con tu data real.",
    ]
    for line in sub_lines:
        lw = draw.textlength(line, font=sub_font)
        draw.text((W / 2 - lw / 2, sub_y), line, font=sub_font, fill=INK_2)
        sub_y += 42

    draw_footer(draw)
    out = os.path.join(OUT_DIR, "rendi_que_es_2_insights_behavior.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ insights_behavior: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# HISTORIA 3: "Preguntale. Sabe tu cartera."
# Visual: chat bubble (pregunta del user) + bubble de respuesta del Coach IA
# Minimalista, con tono fintech serio (no chatbot juguetón).
# ─────────────────────────────────────────────────────────────────────────────
def generate_coach_ia():
    img = build_base_canvas(plan_glow=True)
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ QUÉ ES RENDI · 3 DE 3")

    # ─── HERO TEXT ──────────────────────────────────────────────────────────
    hero_top = 410
    hero_font = F_SANS_BOLD(108)
    line1 = "Preguntale."
    lw1 = draw.textlength(line1, font=hero_font)
    draw.text((W / 2 - lw1 / 2, hero_top), line1, font=hero_font, fill=INK_0)
    line2 = "Sabe tu cartera."
    line2_font = F_SANS_BOLD(80)
    lw2 = draw.textlength(line2, font=line2_font)
    draw.text((W / 2 - lw2 / 2, hero_top + 130), line2, font=line2_font, fill=VIOLET)

    # ─── CHAT BUBBLES ───────────────────────────────────────────────────────
    bubble_top = hero_top + 320

    # User bubble (right-aligned, neutral gray)
    user_text = "¿Por qué bajó mi P&L este mes?"
    ub_font = F_SANS_REG(28)
    ub_w = draw.textlength(user_text, font=ub_font)
    ub_pad_x, ub_pad_y = 28, 18
    ub_width = ub_w + ub_pad_x * 2
    ub_height = 64
    ub_x1 = W - 90  # right margin
    ub_x0 = ub_x1 - ub_width
    ub_y0 = bubble_top
    ub_y1 = ub_y0 + ub_height
    draw.rounded_rectangle(
        [ub_x0, ub_y0, ub_x1, ub_y1],
        radius=18,
        fill=CARD_BG,
        outline=(*INK_4, 180),
        width=1,
    )
    draw.text(
        (ub_x0 + ub_pad_x, ub_y0 + ub_pad_y - 2),
        user_text,
        font=ub_font,
        fill=INK_1,
    )
    # Tag "TÚ"
    tag_font = F_MONO_REG(15)
    draw_spaced_text(draw, "TÚ", ub_x1 - 50, ub_y1 + 10, tag_font, INK_3, spacing=2)

    # Coach bubble (left-aligned, violet accent)
    cb_top = ub_y1 + 70
    coach_lines = [
        "Por NVDA: cayó 8% en 2 semanas, ",
        "y representa 23% de tu cartera.",
        "Es tu mayor concentración.",
    ]
    cb_font = F_SANS_REG(28)
    max_text_w = max(draw.textlength(l, font=cb_font) for l in coach_lines)
    cb_pad_x, cb_pad_y = 28, 22
    cb_width = max_text_w + cb_pad_x * 2
    cb_line_h = 42
    cb_height = len(coach_lines) * cb_line_h + cb_pad_y * 2 - 4
    cb_x0 = 90  # left margin
    cb_x1 = cb_x0 + cb_width
    cb_y0 = cb_top
    cb_y1 = cb_y0 + cb_height
    # Bubble with violet tint
    draw.rounded_rectangle(
        [cb_x0, cb_y0, cb_x1, cb_y1],
        radius=18,
        fill=(22, 18, 38),
        outline=(*VIOLET, 130),
        width=2,
    )
    # Lines
    ty = cb_y0 + cb_pad_y
    for line in coach_lines:
        draw.text((cb_x0 + cb_pad_x, ty), line, font=cb_font, fill=INK_0)
        ty += cb_line_h
    # Tag "COACH IA" (with violet sparkle dot)
    coach_tag_y = cb_y1 + 10
    draw.ellipse(
        [cb_x0 + 4, coach_tag_y + 6, cb_x0 + 14, coach_tag_y + 16],
        fill=VIOLET,
    )
    draw_spaced_text(draw, "COACH IA", cb_x0 + 24, coach_tag_y + 2, tag_font, VIOLET, spacing=2)

    # ─── SUB-COPY ───────────────────────────────────────────────────────────
    sub_y = cb_y1 + 100
    sub_font = F_SANS_REG(28)
    sub_lines = [
        "Coach IA con contexto completo de tu portfolio.",
        "Análisis con tus datos, no respuestas en abstracto.",
    ]
    for line in sub_lines:
        lw = draw.textlength(line, font=sub_font)
        draw.text((W / 2 - lw / 2, sub_y), line, font=sub_font, fill=INK_2)
        sub_y += 42

    draw_footer(draw)
    out = os.path.join(OUT_DIR, "rendi_que_es_3_coach_ia.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ coach_ia: {out} ({os.path.getsize(out) / 1024:.1f}KB)")


# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Limpiar archivos viejos (renombramos las 2 primeras historias en v2)
    for old in ("rendi_que_es_1_multibroker.png", "rendi_que_es_2_usd_real.png"):
        old_path = os.path.join(OUT_DIR, old)
        if os.path.exists(old_path):
            os.remove(old_path)
            print(f"× removed old: {old}")

    generate_brokers_usd()
    generate_insights_behavior()
    generate_coach_ia()
    print("\nDone.")
